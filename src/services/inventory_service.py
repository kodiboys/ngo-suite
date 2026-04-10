# FILE: src/services/inventory_service.py
# MODULE: Inventory Management Service
# Bestandsführung, Bewegungen, Packlistengenerierung, Bedarfserfüllung
# Version: 3.0 - Erweitert um Need-Fulfillment & Transparenz-Features

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.entities.base import AuditLog, Project
from src.core.entities.inventory import (
    InventoryItem,
    InventoryItemCreate,
    PackingList,
    PackingListCreate,
    PackingListItem,
    StockMovement,
    StockMovementCreate,
    StockMovementType,
    StockStatus,
)
from src.core.entities.needs import NeedHistory, NeedStatus, ProjectNeed
from src.core.events.event_bus import Event, EventBus
from src.services.audit import audit_log

logger = logging.getLogger(__name__)


class InventoryService:
    """
    Lagerverwaltungsservice mit:
    - Bestandsführung & Reservierungen
    - Automatische Nachbestellung bei Mindestbestand
    - Packlistengenerierung mit PDF
    - SKR42-Wertbuchungen
    - Verfallsdatum-Monitoring
    - Bedarfserfüllung aus Lagerbestand (v3.0)
    """

    def __init__(self, session_factory, redis_client, event_bus: EventBus):
        self.session_factory = session_factory
        self.redis = redis_client
        self.event_bus = event_bus

    # ==================== Inventory Item Management ====================

    @audit_log(action="CREATE_ITEM", entity_type="inventory_item")
    async def create_item(self, item_data: InventoryItemCreate, user_id: UUID) -> InventoryItem:
        """Erstellt neuen Lagerartikel (v3.0 mit need_id Unterstützung)"""
        async with self.session_factory() as session:
            # Prüfe ob SKU bereits existiert
            stmt = select(InventoryItem).where(
                InventoryItem.sku == item_data.sku, InventoryItem.project_id == item_data.project_id
            )
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                raise HTTPException(
                    status_code=400, detail=f"SKU {item_data.sku} already exists for this project"
                )

            # Hole Projekt für Kostenträger
            stmt = select(Project).where(Project.id == item_data.project_id)
            result = await session.execute(stmt)
            project = result.scalar_one()

            # Prüfe Need falls angegeben (v3.0)
            need = None
            if item_data.need_id:
                stmt = select(ProjectNeed).where(ProjectNeed.id == item_data.need_id)
                result = await session.execute(stmt)
                need = result.scalar_one_or_none()
                if not need:
                    raise HTTPException(
                        status_code=404, detail=f"Need {item_data.need_id} not found"
                    )

            # Erstelle Item
            item = InventoryItem(
                name=item_data.name,
                description=item_data.description,
                sku=item_data.sku,
                category=item_data.category,
                condition=item_data.condition,
                project_id=item_data.project_id,
                cost_center=project.cost_center,
                need_id=item_data.need_id,
                quantity=item_data.quantity,
                min_stock_level=item_data.min_stock_level,
                unit_price=item_data.unit_price,
                warehouse_location=item_data.warehouse_location,
                batch_number=item_data.batch_number,
                expiration_date=item_data.expiration_date,
                requires_special_handling=item_data.requires_special_handling,
                show_on_transparency=item_data.show_on_transparency,
                created_by=user_id,
            )

            # Berechne Gesamtwert
            item.calculate_total_value()
            item.update_stock_status()

            session.add(item)
            await session.commit()
            await session.refresh(item)

            # Wenn Need vorhanden, erstelle History Eintrag (v3.0)
            if need:
                need_history = NeedHistory(
                    need_id=need.id,
                    action="INVENTORY_LINKED",
                    new_values={
                        "inventory_item_id": str(item.id),
                        "inventory_item_name": item.name,
                        "quantity": item.quantity,
                    },
                    change_reason=f"Inventory item {item.name} linked to need",
                    changed_by=user_id,
                    source_type="inventory",
                    source_id=item.id,
                )
                session.add(need_history)
                await session.commit()

            # Publish Event
            await self.event_bus.publish(
                Event(
                    aggregate_id=item.id,
                    aggregate_type="InventoryItem",
                    event_type="ItemCreated",
                    data={
                        "name": item.name,
                        "sku": item.sku,
                        "quantity": item.quantity,
                        "project_id": str(item.project_id),
                        "need_id": str(item.need_id) if item.need_id else None,
                    },
                    user_id=user_id,
                    metadata={},
                )
            )

            return item

    @audit_log(action="UPDATE_STOCK", entity_type="inventory_item")
    async def update_stock(
        self, movement: StockMovementCreate, user_id: UUID, ip_address: str
    ) -> StockMovement:
        """
        Führt Lagerbewegung durch (Zugang/Abgang)
        Mit automatischer SKR42 Buchung für Warenwert
        Unterstützt Need-Fulfillment (v3.0)
        """
        async with self.session_factory() as session:
            # Lade Item mit Lock (FOR UPDATE für Konsistenz)
            stmt = (
                select(InventoryItem).where(InventoryItem.id == movement.item_id).with_for_update()
            )
            result = await session.execute(stmt)
            item = result.scalar_one()

            previous_quantity = item.quantity

            # Berechne neue Menge
            if movement.movement_type == StockMovementType.INBOUND:
                new_quantity = previous_quantity + movement.quantity
            elif movement.movement_type == StockMovementType.OUTBOUND:
                if item.available_quantity < movement.quantity:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Nicht genügend Bestand. Verfügbar: {item.available_quantity}, Benötigt: {movement.quantity}",
                    )
                new_quantity = previous_quantity - movement.quantity
            elif movement.movement_type == StockMovementType.ADJUSTMENT:
                new_quantity = movement.quantity  # Absolute Korrektur
            elif movement.movement_type == StockMovementType.NEED_FULFILLMENT:
                # Bedarfserfüllung - spezielle Behandlung (v3.0)
                if item.reserved_for_need < movement.quantity:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Nicht genügend für Bedarf reserviert. Reserviert: {item.reserved_for_need}, Benötigt: {movement.quantity}",
                    )
                new_quantity = previous_quantity - movement.quantity
                item.reserved_for_need -= movement.quantity
                item.last_need_fulfillment_at = datetime.utcnow()
                item.need_fulfillment_count += 1
            else:
                new_quantity = previous_quantity

            # Erstelle Movement Record
            stock_movement = StockMovement(
                item_id=movement.item_id,
                project_id=item.project_id,
                need_id=movement.need_id,
                movement_type=movement.movement_type,
                quantity=movement.quantity,
                previous_quantity=previous_quantity,
                new_quantity=new_quantity,
                reason=movement.reason,
                destination_location=movement.destination_location,
                reference_type=movement.reference_type,
                reference_id=movement.reference_id,
                created_by=user_id,
                ip_address=ip_address,
            )

            # Update Item
            item.quantity = new_quantity
            item.updated_at = datetime.utcnow()
            item.update_stock_status()
            item.calculate_total_value()

            session.add(stock_movement)
            await session.commit()
            await session.refresh(stock_movement)

            # SKR42 Buchung (falls Unit Price vorhanden)
            if item.unit_price and movement.movement_type in [
                StockMovementType.INBOUND,
                StockMovementType.OUTBOUND,
                StockMovementType.NEED_FULFILLMENT,
            ]:
                await self._create_skr42_booking_for_movement(stock_movement, item, session)

            # Bei Bedarfserfüllung: Aktualisiere Need (v3.0)
            if movement.movement_type == StockMovementType.NEED_FULFILLMENT and movement.need_id:
                await self._update_need_on_fulfillment(
                    movement.need_id, movement.quantity, user_id, session
                )

            # Prüfe ob Nachbestellung nötig
            if item.status == StockStatus.LOW_STOCK:
                await self._trigger_reorder(item, session)

            # Publish Event
            await self.event_bus.publish(
                Event(
                    aggregate_id=item.id,
                    aggregate_type="InventoryItem",
                    event_type="StockUpdated",
                    data={
                        "movement_type": movement.movement_type.value,
                        "quantity": movement.quantity,
                        "new_quantity": new_quantity,
                        "reason": movement.reason,
                        "need_id": str(movement.need_id) if movement.need_id else None,
                    },
                    user_id=user_id,
                    metadata={"ip": ip_address},
                )
            )

            return stock_movement

    async def get_low_stock_items(self, project_id: UUID | None = None) -> list[InventoryItem]:
        """Listet Artikel mit niedrigem Bestand auf"""
        async with self.session_factory() as session:
            stmt = select(InventoryItem).where(
                InventoryItem.quantity <= InventoryItem.reorder_point,
                InventoryItem.is_active is True,
            )
            if project_id:
                stmt = stmt.where(InventoryItem.project_id == project_id)

            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_expiring_items(self, days_threshold: int = 30) -> list[InventoryItem]:
        """Listet Artikel mit ablaufendem Verfallsdatum"""
        async with self.session_factory() as session:
            expiry_date = datetime.utcnow() + timedelta(days=days_threshold)
            stmt = (
                select(InventoryItem)
                .where(
                    InventoryItem.expiration_date <= expiry_date,
                    InventoryItem.expiration_date > datetime.utcnow(),
                    InventoryItem.is_active is True,
                )
                .order_by(InventoryItem.expiration_date)
            )

            result = await session.execute(stmt)
            return result.scalars().all()

    # ==================== Need-Fulfillment Methods (v3.0) ====================

    async def get_items_for_need(self, need_id: UUID) -> list[InventoryItem]:
        """Holt alle Lagerartikel für einen Bedarf"""
        async with self.session_factory() as session:
            stmt = select(InventoryItem).where(
                InventoryItem.need_id == need_id, InventoryItem.is_active is True
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    async def link_item_to_need(self, item_id: UUID, need_id: UUID, user_id: UUID) -> InventoryItem:
        """Verknüpft einen Lagerartikel mit einem Bedarf"""
        async with self.session_factory() as session:
            stmt = select(InventoryItem).where(InventoryItem.id == item_id)
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()

            if not item:
                raise HTTPException(status_code=404, detail="Inventory item not found")

            stmt = select(ProjectNeed).where(ProjectNeed.id == need_id)
            result = await session.execute(stmt)
            need = result.scalar_one_or_none()

            if not need:
                raise HTTPException(status_code=404, detail="Need not found")

            item.need_id = need_id
            item.updated_at = datetime.utcnow()

            await session.commit()
            await session.refresh(item)

            # Need History Eintrag
            need_history = NeedHistory(
                need_id=need_id,
                action="INVENTORY_LINKED",
                new_values={
                    "inventory_item_id": str(item.id),
                    "inventory_item_name": item.name,
                    "quantity": item.quantity,
                },
                change_reason=f"Inventory item {item.name} linked to need",
                changed_by=user_id,
                source_type="inventory",
                source_id=item.id,
            )
            session.add(need_history)
            await session.commit()

            # Audit Log
            audit = AuditLog(
                user_id=user_id,
                action="LINK_ITEM_TO_NEED",
                entity_type="inventory_item",
                entity_id=item_id,
                new_values={"need_id": str(need_id), "need_name": need.name},
                ip_address="system",
                retention_until=datetime.utcnow() + timedelta(days=3650),
            )
            session.add(audit)
            await session.commit()

            return item

    async def get_low_stock_for_needs(self, project_id: UUID | None = None) -> list[dict[str, Any]]:
        """Listet Artikel mit niedrigem Bestand, die für Bedarfe relevant sind"""
        async with self.session_factory() as session:
            stmt = select(InventoryItem).where(
                InventoryItem.need_id.isnot(None),
                InventoryItem.available_quantity <= InventoryItem.reorder_point,
                InventoryItem.is_active is True,
            )

            if project_id:
                stmt = stmt.where(InventoryItem.project_id == project_id)

            result = await session.execute(stmt)
            items = result.scalars().all()

            result_list = []
            for item in items:
                # Lade zugehörigen Need
                stmt = select(ProjectNeed).where(ProjectNeed.id == item.need_id)
                need_result = await session.execute(stmt)
                need = need_result.scalar_one_or_none()

                result_list.append(
                    {
                        "item": {
                            "id": str(item.id),
                            "name": item.name,
                            "sku": item.sku,
                            "available_quantity": item.available_quantity,
                            "min_stock_level": item.min_stock_level,
                            "status": item.status.value,
                        },
                        "need": (
                            {
                                "id": str(need.id) if need else None,
                                "name": need.name if need else None,
                                "priority": need.priority.value if need else None,
                                "remaining_quantity": need.remaining_quantity if need else 0,
                            }
                            if need
                            else None
                        ),
                    }
                )

            return result_list

    async def get_transparency_inventory(
        self, project_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        """Holt Lagerbestände für Transparenzseite (öffentlich)"""
        async with self.session_factory() as session:
            stmt = select(InventoryItem).where(
                InventoryItem.show_on_transparency is True, InventoryItem.is_active is True
            )

            if project_id:
                stmt = stmt.where(InventoryItem.project_id == project_id)

            result = await session.execute(stmt)
            items = result.scalars().all()

            return [
                {
                    "id": str(item.id),
                    "name": item.name,
                    "category": item.category,
                    "available_quantity": item.available_quantity,
                    "unit_price": float(item.unit_price) if item.unit_price else None,
                    "total_value": float(item.total_value) if item.total_value else None,
                    "image_url": item.image_url,
                    "need": (
                        {
                            "id": str(item.need.id),
                            "name": item.need.name,
                            "progress_percent": item.need.fulfillment_percentage,
                        }
                        if item.need_id
                        else None
                    ),
                }
                for item in items
            ]

    async def _update_need_on_fulfillment(
        self, need_id: UUID, quantity: int, user_id: UUID, session: AsyncSession
    ):
        """Aktualisiert Bedarf bei Lagerabgang (v3.0)"""
        stmt = select(ProjectNeed).where(ProjectNeed.id == need_id)
        result = await session.execute(stmt)
        need = result.scalar_one_or_none()

        if need:
            old_current = need.quantity_current
            need.add_quantity(quantity, user_id)

            # Need History Eintrag
            need_history = NeedHistory(
                need_id=need_id,
                action="FULFILLED_FROM_INVENTORY",
                old_values={"quantity_current": old_current},
                new_values={"quantity_current": need.quantity_current},
                change_reason=f"Fulfilled from inventory: {quantity} units",
                changed_by=user_id,
                source_type="inventory",
            )
            session.add(need_history)
            await session.commit()

    # ==================== Packing List Management ====================

    @audit_log(action="CREATE_PACKINGLIST", entity_type="packing_list")
    async def create_packing_list(
        self, packing_data: PackingListCreate, user_id: UUID
    ) -> PackingList:
        """
        Erstellt Packliste für Projektauslieferung
        Reserviert Bestand und generiert PDF
        Unterstützt Bedarfe (v3.0)
        """
        async with self.session_factory() as session:
            # Hole Projekt
            stmt = select(Project).where(Project.id == packing_data.project_id)
            result = await session.execute(stmt)
            project = result.scalar_one()

            # Erstelle Packliste
            packing_list = PackingList(
                project_id=packing_data.project_id,
                project_name=project.name,
                recipient_name=packing_data.recipient_name,
                recipient_address=packing_data.recipient_address,
                recipient_email=packing_data.recipient_email,
                shipping_date=packing_data.shipping_date,
                shipping_method=packing_data.shipping_method,
                notes=packing_data.notes,
                need_ids=[str(nid) for nid in packing_data.need_ids],
                show_on_transparency=packing_data.show_on_transparency,
                created_by=user_id,
                status="draft",
            )
            packing_list.generate_number()
            packing_list.generate_transparency_hash()

            session.add(packing_list)
            await session.flush()  # Um ID zu erhalten

            # Verarbeite Items
            total_weight = Decimal("0")
            total_volume = Decimal("0")

            for item_data in packing_data.items:
                # Lade Inventory Item
                stmt = (
                    select(InventoryItem)
                    .where(InventoryItem.id == item_data["item_id"])
                    .with_for_update()
                )
                result = await session.execute(stmt)
                item = result.scalar_one()

                # Prüfe Bestand
                quantity_requested = item_data["quantity"]
                if item.available_quantity < quantity_requested:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Nicht genügend Bestand für {item.name}. Verfügbar: {item.available_quantity}",
                    )

                # Reserviere Bestand
                item.reserved_quantity += quantity_requested

                # Erstelle Packlist Item
                packing_item = PackingListItem(
                    packing_list_id=packing_list.id,
                    item_id=item.id,
                    need_id=item_data.get("need_id"),
                    item_name=item.name,
                    item_sku=item.sku,
                    item_category=item.category,
                    quantity_requested=quantity_requested,
                    quantity_shipped=quantity_requested,
                    condition_at_shipment=item.condition,
                    notes=item_data.get("notes"),
                )
                session.add(packing_item)

                # Wenn Need vorhanden, reserviere für Need
                if item.need_id:
                    item.reserve_for_need(quantity_requested)

                # Sammle Gewicht/Volumen (falls vorhanden)
                # In Production: Aus Item-Metadaten

            packing_list.total_weight_kg = total_weight if total_weight > 0 else None
            packing_list.total_volume_m3 = total_volume if total_volume > 0 else None

            await session.commit()
            await session.refresh(packing_list)

            # Generiere PDF (async)
            from src.services.pdf_generator import generate_packing_list_pdf

            pdf_url = await generate_packing_list_pdf(packing_list.id)
            packing_list.pdf_url = pdf_url
            await session.commit()

            # Publish Event
            await self.event_bus.publish(
                Event(
                    aggregate_id=packing_list.id,
                    aggregate_type="PackingList",
                    event_type="PackingListCreated",
                    data={
                        "number": packing_list.packing_list_number,
                        "items_count": len(packing_data.items),
                        "recipient": packing_data.recipient_name,
                        "need_ids": [str(nid) for nid in packing_data.need_ids],
                        "transparency_hash": packing_list.transparency_hash,
                    },
                    user_id=user_id,
                    metadata={},
                )
            )

            return packing_list

    @audit_log(action="CONFIRM_PACKINGLIST", entity_type="packing_list")
    async def confirm_packing_list(self, packing_list_id: UUID, user_id: UUID) -> PackingList:
        """
        Bestätigt Packliste und führt Lagerabgang durch
        Aktualisiert Bedarfe bei Need-Fulfillment (v3.0)
        """
        async with self.session_factory() as session:
            # Lade Packliste mit Items
            stmt = select(PackingList).where(PackingList.id == packing_list_id)
            result = await session.execute(stmt)
            packing_list = result.scalar_one()

            if packing_list.status != "draft":
                raise HTTPException(
                    status_code=400, detail=f"Packing list already {packing_list.status}"
                )

            # Führe für jedes Item einen Lagerabgang durch
            for item in packing_list.items:
                movement_type = (
                    StockMovementType.NEED_FULFILLMENT
                    if item.need_id
                    else StockMovementType.OUTBOUND
                )

                # Erstelle Stock Movement
                movement = StockMovementCreate(
                    item_id=item.item_id,
                    movement_type=movement_type,
                    quantity=item.quantity_shipped,
                    reason=f"Packing list {packing_list.packing_list_number}",
                    reference_type="packing_list",
                    reference_id=packing_list_id,
                    destination_location=packing_list.recipient_address,
                    need_id=item.need_id,
                )

                await self.update_stock(movement, user_id, "system")

                # Reduziere Reservierung
                stmt = select(InventoryItem).where(InventoryItem.id == item.item_id)
                result = await session.execute(stmt)
                inventory_item = result.scalar_one()
                inventory_item.reserved_quantity -= item.quantity_shipped
                session.add(inventory_item)

            # Aktualisiere Need-Status für alle verknüpften Bedarfe
            for need_id_str in packing_list.need_ids:
                try:
                    need_id = UUID(need_id_str)
                    stmt = select(ProjectNeed).where(ProjectNeed.id == need_id)
                    result = await session.execute(stmt)
                    need = result.scalar_one_or_none()

                    if need and need.status != NeedStatus.FULFILLED:
                        need.update_fulfillment()
                        session.add(need)
                except ValueError:
                    pass

            # Update Packliste
            packing_list.status = "confirmed"
            packing_list.confirmed_by = user_id
            packing_list.confirmed_at = datetime.utcnow()

            await session.commit()
            await session.refresh(packing_list)

            return packing_list

    @audit_log(action="DELIVER_PACKINGLIST", entity_type="packing_list")
    async def mark_as_delivered(
        self, packing_list_id: UUID, signature_data: str | None = None
    ) -> PackingList:
        """
        Markiert Packliste als zugestellt (mit Unterschrift)
        """
        async with self.session_factory() as session:
            stmt = select(PackingList).where(PackingList.id == packing_list_id)
            result = await session.execute(stmt)
            packing_list = result.scalar_one()

            packing_list.status = "delivered"
            packing_list.delivery_date = datetime.utcnow()

            if signature_data:
                packing_list.signature_data = signature_data
                packing_list.signed_at = datetime.utcnow()

            await session.commit()
            await session.refresh(packing_list)

            # Publish Event für Projekt-Fortschritt
            await self.event_bus.publish(
                Event(
                    aggregate_id=packing_list.project_id,
                    aggregate_type="Project",
                    event_type="SuppliesDelivered",
                    data={
                        "packing_list_id": str(packing_list_id),
                        "packing_list_number": packing_list.packing_list_number,
                        "transparency_hash": packing_list.transparency_hash,
                    },
                    user_id=packing_list.created_by,
                    metadata={},
                )
            )

            return packing_list

    # ==================== Helper Methods ====================

    async def _create_skr42_booking_for_movement(
        self, movement: StockMovement, item: InventoryItem, session
    ):
        """Erstellt SKR42 Buchung für Warenbewegung"""
        from src.services.accounting import create_skr42_booking

        value_change = movement.quantity * item.unit_price

        if movement.movement_type == StockMovementType.INBOUND:
            # Zugang: Bestandskonto (20000) an Spendenkonto (40000)
            await create_skr42_booking(
                amount=value_change,
                debit_account="20000",  # Warenlager
                credit_account="40000",  # Sachspenden
                project_id=item.project_id,
                reference_id=movement.id,
                description=f"Stock inbound: {item.name} x{movement.quantity}",
            )
        elif movement.movement_type in [
            StockMovementType.OUTBOUND,
            StockMovementType.NEED_FULFILLMENT,
        ]:
            # Abgang: Projektkosten (70000) an Bestandskonto (20000)
            await create_skr42_booking(
                amount=value_change,
                debit_account="70000",  # Projektausgaben
                credit_account="20000",  # Warenlager
                project_id=item.project_id,
                reference_id=movement.id,
                description=f"Stock outbound for need: {item.name} x{movement.quantity}",
            )

    async def _trigger_reorder(self, item: InventoryItem, session):
        """Löst Nachbestellung aus (kann mit ERPNext/Email verbunden werden)"""
        logger.warning(
            f"Low stock alert: {item.name} (SKU: {item.sku}) - {item.available_quantity} left, reorder point: {item.reorder_point}"
        )

        # Publish Event für Nachbestellung
        await self.event_bus.publish(
            Event(
                aggregate_id=item.id,
                aggregate_type="InventoryItem",
                event_type="ReorderNeeded",
                data={
                    "item_name": item.name,
                    "sku": item.sku,
                    "current_stock": item.quantity,
                    "reorder_point": item.reorder_point,
                    "suggested_order": (
                        item.max_stock_level - item.quantity
                        if item.max_stock_level
                        else item.reorder_point * 2
                    ),
                    "need_id": str(item.need_id) if item.need_id else None,
                },
                user_id=None,  # System-Event
                metadata={},
            )
        )

    # ==================== Reports ====================

    async def get_inventory_value_report(self, project_id: UUID | None = None) -> dict[str, Any]:
        """Bericht: Gesamtwert des Lagers nach Kategorie"""
        async with self.session_factory() as session:
            stmt = select(
                InventoryItem.category,
                func.sum(InventoryItem.total_value).label("total_value"),
                func.sum(InventoryItem.quantity).label("total_quantity"),
            ).where(InventoryItem.is_active is True)

            if project_id:
                stmt = stmt.where(InventoryItem.project_id == project_id)

            stmt = stmt.group_by(InventoryItem.category)
            result = await session.execute(stmt)

            report = {
                "generated_at": datetime.utcnow().isoformat(),
                "total_value": Decimal("0"),
                "categories": [],
            }

            for row in result:
                category_data = {
                    "category": row.category.value,
                    "total_value": float(row.total_value) if row.total_value else 0,
                    "total_quantity": row.total_quantity,
                }
                report["categories"].append(category_data)
                report["total_value"] += row.total_value or 0

            return report

    async def get_movement_history(self, item_id: UUID, limit: int = 100) -> list[StockMovement]:
        """Zeigt Bewegungs-History für ein Item"""
        async with self.session_factory() as session:
            stmt = (
                select(StockMovement)
                .where(StockMovement.item_id == item_id)
                .order_by(StockMovement.created_at.desc())
                .limit(limit)
            )

            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_need_fulfillment_history(
        self, need_id: UUID, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Zeigt History der Bedarfserfüllungen (v3.0)"""
        async with self.session_factory() as session:
            stmt = (
                select(StockMovement)
                .where(
                    StockMovement.need_id == need_id,
                    StockMovement.movement_type == StockMovementType.NEED_FULFILLMENT,
                )
                .order_by(StockMovement.created_at.desc())
                .limit(limit)
            )

            result = await session.execute(stmt)
            movements = result.scalars().all()

            return [
                {
                    "id": str(m.id),
                    "quantity": m.quantity,
                    "date": m.created_at.isoformat(),
                    "destination": m.destination_location,
                    "tracking_number": m.tracking_number,
                    "reference_type": m.reference_type,
                    "reference_id": str(m.reference_id) if m.reference_id else None,
                }
                for m in movements
            ]
