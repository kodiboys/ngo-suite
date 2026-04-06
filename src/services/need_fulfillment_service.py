# FILE: src/services/need_fulfillment_service.py
# MODULE: Need Fulfillment Service - Bedarfserfüllung aus Lagerbeständen
# Version: 3.0 - Verbindet Projekt-Bedarfe mit Lagerbeständen

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from src.core.entities.base import AuditLog
from src.core.entities.inventory import (
    InventoryItem,
    PackingList,
    PackingListItem,
    StockMovement,
    StockMovementType,
)
from src.core.entities.needs import NeedHistory, NeedStatus, ProjectNeed
from src.core.events.event_bus import Event, EventBus

logger = logging.getLogger(__name__)


class NeedFulfillmentService:
    """
    Service für Bedarfserfüllung aus Lagerbeständen

    Features:
    - Automatische Reservierung von Lagerbeständen für Bedarfe
    - Erstellung von Packlisten bei Bedarfserfüllung
    - Aktualisierung von Bedarfs-Fortschritten
    - Benachrichtigungen bei kritischen Beständen
    - Integration mit Transparenz-API
    """

    def __init__(self, session_factory, event_bus: EventBus, notification_service=None):
        self.session_factory = session_factory
        self.event_bus = event_bus
        self.notification_service = notification_service

    async def reserve_inventory_for_need(
        self, need_id: UUID, quantity: int, user_id: UUID, ip_address: str = "system"
    ) -> dict[str, Any]:
        """
        Reserviert Lagerbestand für einen Bedarf

        Args:
            need_id: ID des Bedarfs
            quantity: Zu reservierende Menge
            user_id: ID des ausführenden Benutzers
            ip_address: IP-Adresse für Audit

        Returns:
            Dict mit Reservierungsdetails
        """
        async with self.session_factory() as session:
            # 1. Lade Bedarf
            stmt = select(ProjectNeed).where(ProjectNeed.id == need_id)
            result = await session.execute(stmt)
            need = result.scalar_one_or_none()

            if not need:
                raise HTTPException(status_code=404, detail="Need not found")

            if need.status == NeedStatus.FULFILLED:
                raise HTTPException(status_code=400, detail="Need already fulfilled")

            # 2. Finde passendes Inventory Item
            stmt = select(InventoryItem).where(
                InventoryItem.need_id == need_id, InventoryItem.is_active is True
            )
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()

            if not item:
                # Versuche Item nach Kategorie zu finden
                stmt = select(InventoryItem).where(
                    InventoryItem.project_id == need.project_id,
                    InventoryItem.category == need.category,
                    InventoryItem.is_active is True,
                    InventoryItem.available_quantity >= quantity,
                )
                result = await session.execute(stmt)
                item = result.scalar_one_or_none()

            if not item:
                raise HTTPException(
                    status_code=404,
                    detail=f"No inventory item found for need {need.name}. Available: {item.available_quantity if item else 0}",
                )

            # 3. Reserviere Bestand
            success = item.reserve_for_need(quantity)

            if not success:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient inventory. Available: {item.available_quantity}, Requested: {quantity}",
                )

            # 4. Verknüpfe Item mit Need
            if not item.need_id:
                item.need_id = need_id

            # 5. Erstelle Stock Movement für Reservierung
            movement = StockMovement(
                item_id=item.id,
                project_id=need.project_id,
                need_id=need_id,
                movement_type=StockMovementType.ADJUSTMENT,
                quantity=quantity,
                previous_quantity=item.quantity,
                new_quantity=item.quantity,
                reason=f"Reserved for need: {need.name}",
                reference_type="need_reservation",
                reference_id=need_id,
                created_by=user_id,
                ip_address=ip_address,
            )

            session.add(movement)
            await session.commit()

            # 6. Audit Log
            audit = AuditLog(
                user_id=user_id,
                action="NEED_RESERVATION",
                entity_type="project_need",
                entity_id=need_id,
                new_values={
                    "reserved_quantity": quantity,
                    "inventory_item_id": str(item.id),
                    "item_name": item.name,
                },
                ip_address=ip_address,
                retention_until=datetime.utcnow().replace(year=datetime.utcnow().year + 10),
            )
            session.add(audit)
            await session.commit()

            # 7. Publish Event
            await self.event_bus.publish(
                Event(
                    aggregate_id=need_id,
                    aggregate_type="ProjectNeed",
                    event_type="need.reserved",
                    data={
                        "need_name": need.name,
                        "reserved_quantity": quantity,
                        "inventory_item": item.name,
                        "remaining_needed": need.remaining_quantity - quantity,
                    },
                    user_id=user_id,
                    metadata={"ip": ip_address},
                )
            )

            logger.info(f"Reserved {quantity} units of {item.name} for need {need.name}")

            return {
                "need_id": str(need_id),
                "need_name": need.name,
                "reserved_quantity": quantity,
                "inventory_item_id": str(item.id),
                "inventory_item_name": item.name,
                "remaining_needed": need.remaining_quantity - quantity,
            }

    async def fulfill_need_from_inventory(
        self,
        need_id: UUID,
        quantity: int,
        user_id: UUID,
        recipient_name: str,
        recipient_address: str,
        recipient_email: str | None = None,
        shipping_method: str | None = None,
        ip_address: str = "system",
    ) -> dict[str, Any]:
        """
        Erfüllt einen Bedarf aus dem Lagerbestand

        Erstellt eine Packliste und aktualisiert Bestände und Bedarfsfortschritt
        """
        async with self.session_factory() as session:
            # 1. Lade Bedarf
            stmt = select(ProjectNeed).where(ProjectNeed.id == need_id)
            result = await session.execute(stmt)
            need = result.scalar_one_or_none()

            if not need:
                raise HTTPException(status_code=404, detail="Need not found")

            # 2. Lade Inventory Item
            stmt = select(InventoryItem).where(InventoryItem.need_id == need_id)
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()

            if not item:
                raise HTTPException(status_code=404, detail="No inventory item linked to this need")

            if item.reserved_for_need < quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient reserved stock. Reserved: {item.reserved_for_need}, Requested: {quantity}",
                )

            # 3. Erfülle Bedarf aus Lager
            success = item.fulfill_need(quantity)

            if not success:
                raise HTTPException(status_code=400, detail="Failed to fulfill need from inventory")

            # 4. Aktualisiere Bedarf
            old_current = need.quantity_current
            need.add_quantity(quantity, user_id)

            # 5. Erstelle Packliste
            packing_list = PackingList(
                project_id=need.project_id,
                project_name=need.project.name,
                need_ids=[str(need_id)],
                recipient_name=recipient_name,
                recipient_address=recipient_address,
                recipient_email=recipient_email,
                shipping_date=datetime.utcnow(),
                shipping_method=shipping_method,
                status="confirmed",
                created_by=user_id,
            )
            packing_list.generate_number()
            packing_list.generate_transparency_hash()

            session.add(packing_list)
            await session.flush()

            # 6. Erstelle PackListItem
            packing_item = PackingListItem(
                packing_list_id=packing_list.id,
                item_id=item.id,
                need_id=need_id,
                item_name=item.name,
                item_sku=item.sku,
                item_category=item.category,
                quantity_requested=quantity,
                quantity_shipped=quantity,
                condition_at_shipment=item.condition,
                notes=f"Fulfillment of need: {need.name}",
            )
            session.add(packing_item)

            # 7. Erstelle Stock Movement für Auslieferung
            movement = StockMovement(
                item_id=item.id,
                project_id=need.project_id,
                need_id=need_id,
                movement_type=StockMovementType.NEED_FULFILLMENT,
                quantity=quantity,
                previous_quantity=item.quantity + quantity,
                new_quantity=item.quantity,
                reason=f"Need fulfillment: {need.name}",
                reference_type="packing_list",
                reference_id=packing_list.id,
                need_fulfillment_id=need_id,
                destination_location=recipient_address,
                created_by=user_id,
                ip_address=ip_address,
            )
            session.add(movement)

            # 8. Need History Eintrag
            need_history = NeedHistory(
                need_id=need_id,
                action="FULFILLED",
                old_values={"quantity_current": old_current},
                new_values={"quantity_current": need.quantity_current},
                change_reason=f"Fulfilled from inventory. Packing list: {packing_list.packing_list_number}",
                changed_by=user_id,
                source_type="inventory",
                source_id=packing_list.id,
                ip_address=ip_address,
            )
            session.add(need_history)

            await session.commit()

            # 9. Audit Log
            audit = AuditLog(
                user_id=user_id,
                action="NEED_FULFILLED",
                entity_type="project_need",
                entity_id=need_id,
                old_values={"quantity_current": old_current, "status": need.status.value},
                new_values={
                    "quantity_current": need.quantity_current,
                    "status": need.status.value,
                    "fulfillment_percentage": need.fulfillment_percentage,
                },
                ip_address=ip_address,
                retention_until=datetime.utcnow().replace(year=datetime.utcnow().year + 10),
            )
            session.add(audit)
            await session.commit()

            # 10. Publish Events
            await self.event_bus.publish(
                Event(
                    aggregate_id=need_id,
                    aggregate_type="ProjectNeed",
                    event_type="need.fulfilled",
                    data={
                        "need_name": need.name,
                        "fulfilled_quantity": quantity,
                        "new_progress": need.fulfillment_percentage,
                        "packing_list_number": packing_list.packing_list_number,
                        "transparency_hash": packing_list.transparency_hash,
                    },
                    user_id=user_id,
                    metadata={"ip": ip_address},
                )
            )

            # 11. Prüfe ob Bedarf komplett erfüllt ist
            if need.status == NeedStatus.FULFILLED:
                await self.event_bus.publish(
                    Event(
                        aggregate_id=need_id,
                        aggregate_type="ProjectNeed",
                        event_type="need.completed",
                        data={
                            "need_name": need.name,
                            "total_quantity": need.quantity_target,
                            "fulfilled_at": (
                                need.fulfilled_at.isoformat() if need.fulfilled_at else None
                            ),
                        },
                        user_id=user_id,
                        metadata={"ip": ip_address},
                    )
                )

            # 12. Sende Benachrichtigung (optional)
            if self.notification_service and need.alert_enabled:
                await self._send_fulfillment_notification(need, packing_list, quantity)

            logger.info(
                f"Need {need.name} fulfilled: {quantity} units via packing list {packing_list.packing_list_number}"
            )

            return {
                "need_id": str(need_id),
                "need_name": need.name,
                "fulfilled_quantity": quantity,
                "new_progress_percent": need.fulfillment_percentage,
                "is_completed": need.status == NeedStatus.FULFILLED,
                "packing_list": {
                    "id": str(packing_list.id),
                    "number": packing_list.packing_list_number,
                    "transparency_hash": packing_list.transparency_hash,
                    "pdf_url": packing_list.pdf_url,
                },
                "remaining_quantity": need.remaining_quantity,
            }

    async def _send_fulfillment_notification(
        self, need: ProjectNeed, packing_list: PackingList, quantity: int
    ):
        """Sendet Benachrichtigung über Bedarfserfüllung"""
        # Implementierung für Email/Telegram/Slack
        pass

    async def get_need_fulfillment_status(self, need_id: UUID) -> dict[str, Any]:
        """Holt detaillierten Status der Bedarfserfüllung"""
        async with self.session_factory() as session:
            stmt = select(ProjectNeed).where(ProjectNeed.id == need_id)
            result = await session.execute(stmt)
            need = result.scalar_one_or_none()

            if not need:
                raise HTTPException(status_code=404, detail="Need not found")

            # Lade zugehörige Packlisten
            stmt = (
                select(PackingList)
                .where(PackingList.need_ids.containss([str(need_id)]))
                .order_by(PackingList.created_at.desc())
            )
            result = await session.execute(stmt)
            packing_lists = result.scalars().all()

            # Lade zugehörige Inventory Items
            stmt = select(InventoryItem).where(InventoryItem.need_id == need_id)
            result = await session.execute(stmt)
            items = result.scalars().all()

            return {
                "need": {
                    "id": str(need.id),
                    "name": need.name,
                    "category": need.category,
                    "priority": need.priority,
                    "quantity_target": need.quantity_target,
                    "quantity_current": need.quantity_current,
                    "remaining_quantity": need.remaining_quantity,
                    "fulfillment_percentage": need.fulfillment_percentage,
                    "status": need.status.value,
                },
                "inventory_items": [
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "sku": item.sku,
                        "quantity": item.quantity,
                        "reserved_for_need": item.reserved_for_need,
                        "available_for_need": item.available_quantity,
                    }
                    for item in items
                ],
                "packing_lists": [
                    {
                        "id": str(pl.id),
                        "number": pl.packing_list_number,
                        "status": pl.status,
                        "shipping_date": pl.shipping_date.isoformat() if pl.shipping_date else None,
                        "tracking_number": pl.tracking_number,
                        "transparency_hash": pl.transparency_hash,
                        "created_at": pl.created_at.isoformat(),
                    }
                    for pl in packing_lists
                ],
            }

    async def get_project_fulfillment_summary(self, project_id: UUID) -> dict[str, Any]:
        """Holt Übersicht über alle Bedarfserfüllungen eines Projekts"""
        async with self.session_factory() as session:
            stmt = select(ProjectNeed).where(ProjectNeed.project_id == project_id)
            result = await session.execute(stmt)
            needs = result.scalars().all()

            total_needs = len(needs)
            fulfilled_needs = sum(1 for n in needs if n.status == NeedStatus.FULFILLED)
            partial_needs = sum(1 for n in needs if n.status == NeedStatus.PARTIALLY_FULFILLED)
            active_needs = sum(1 for n in needs if n.status == NeedStatus.ACTIVE)

            total_target_quantity = sum(n.quantity_target for n in needs)
            total_current_quantity = sum(n.quantity_current for n in needs)

            # Lade Packlisten für dieses Projekt
            stmt = (
                select(PackingList)
                .where(PackingList.project_id == project_id)
                .order_by(PackingList.created_at.desc())
            )
            result = await session.execute(stmt)
            packing_lists = result.scalars().all()

            return {
                "project_id": str(project_id),
                "summary": {
                    "total_needs": total_needs,
                    "fulfilled_needs": fulfilled_needs,
                    "partial_needs": partial_needs,
                    "active_needs": active_needs,
                    "completion_rate": (
                        round((fulfilled_needs / total_needs * 100), 1) if total_needs > 0 else 0
                    ),
                },
                "quantity_summary": {
                    "total_target": total_target_quantity,
                    "total_fulfilled": total_current_quantity,
                    "remaining": total_target_quantity - total_current_quantity,
                    "progress_percent": (
                        round((total_current_quantity / total_target_quantity * 100), 1)
                        if total_target_quantity > 0
                        else 0
                    ),
                },
                "recent_packing_lists": [
                    {
                        "id": str(pl.id),
                        "number": pl.packing_list_number,
                        "status": pl.status,
                        "transparency_hash": pl.transparency_hash,
                        "created_at": pl.created_at.isoformat(),
                    }
                    for pl in packing_lists[:10]
                ],
            }
