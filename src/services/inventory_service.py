# FILE: src/services/inventory_service.py
# MODULE: Inventory Management Service
# Bestandsführung, Bewegungen, Packlistengenerierung

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from src.core.entities.base import Project
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
    """

    def __init__(self, session_factory, redis_client, event_bus: EventBus):
        self.session_factory = session_factory
        self.redis = redis_client
        self.event_bus = event_bus

    # ==================== Inventory Item Management ====================

    @audit_log(action="CREATE_ITEM", entity_type="inventory_item")
    async def create_item(self, item_data: InventoryItemCreate, user_id: UUID) -> InventoryItem:
        """Erstellt neuen Lagerartikel"""
        async with self.session_factory() as session:
            # Prüfe ob SKU bereits existiert
            stmt = select(InventoryItem).where(
                InventoryItem.sku == item_data.sku,
                InventoryItem.project_id == item_data.project_id
            )
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                raise HTTPException(status_code=400, detail=f"SKU {item_data.sku} already exists for this project")

            # Hole Projekt für Kostenträger
            stmt = select(Project).where(Project.id == item_data.project_id)
            result = await session.execute(stmt)
            project = result.scalar_one()

            # Erstelle Item
            item = InventoryItem(
                name=item_data.name,
                description=item_data.description,
                sku=item_data.sku,
                category=item_data.category,
                condition=item_data.condition,
                project_id=item_data.project_id,
                cost_center=project.cost_center,
                quantity=item_data.quantity,
                min_stock_level=item_data.min_stock_level,
                unit_price=item_data.unit_price,
                warehouse_location=item_data.warehouse_location,
                batch_number=item_data.batch_number,
                expiration_date=item_data.expiration_date,
                requires_special_handling=item_data.requires_special_handling,
                created_by=user_id
            )

            # Berechne Gesamtwert
            item.calculate_total_value()
            item.update_stock_status()

            session.add(item)
            await session.commit()
            await session.refresh(item)

            # Publish Event
            await self.event_bus.publish(Event(
                aggregate_id=item.id,
                aggregate_type="InventoryItem",
                event_type="ItemCreated",
                data={
                    "name": item.name,
                    "sku": item.sku,
                    "quantity": item.quantity,
                    "project_id": str(item.project_id)
                },
                user_id=user_id,
                metadata={}
            ))

            return item

    @audit_log(action="UPDATE_STOCK", entity_type="inventory_item")
    async def update_stock(self, movement: StockMovementCreate, user_id: UUID, ip_address: str) -> StockMovement:
        """
        Führt Lagerbewegung durch (Zugang/Abgang)
        Mit automatischer SKR42 Buchung für Warenwert
        """
        async with self.session_factory() as session:
            # Lade Item mit Lock (FOR UPDATE für Konsistenz)
            stmt = select(InventoryItem).where(InventoryItem.id == movement.item_id).with_for_update()
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
                        detail=f"Nicht genügend Bestand. Verfügbar: {item.available_quantity}, Benötigt: {movement.quantity}"
                    )
                new_quantity = previous_quantity - movement.quantity
            elif movement.movement_type == StockMovementType.ADJUSTMENT:
                new_quantity = movement.quantity  # Absolute Korrektur
            else:
                new_quantity = previous_quantity

            # Erstelle Movement Record
            stock_movement = StockMovement(
                item_id=movement.item_id,
                project_id=item.project_id,
                movement_type=movement.movement_type,
                quantity=movement.quantity,
                previous_quantity=previous_quantity,
                new_quantity=new_quantity,
                reason=movement.reason,
                destination_location=movement.destination_location,
                reference_type=movement.reference_type,
                reference_id=movement.reference_id,
                created_by=user_id,
                ip_address=ip_address
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
            if item.unit_price and movement.movement_type in [StockMovementType.INBOUND, StockMovementType.OUTBOUND]:
                await self._create_skr42_booking_for_movement(stock_movement, item, session)

            # Prüfe ob Nachbestellung nötig
            if item.status == StockStatus.LOW_STOCK:
                await self._trigger_reorder(item, session)

            # Publish Event
            await self.event_bus.publish(Event(
                aggregate_id=item.id,
                aggregate_type="InventoryItem",
                event_type="StockUpdated",
                data={
                    "movement_type": movement.movement_type.value,
                    "quantity": movement.quantity,
                    "new_quantity": new_quantity,
                    "reason": movement.reason
                },
                user_id=user_id,
                metadata={"ip": ip_address}
            ))

            return stock_movement

    async def get_low_stock_items(self, project_id: UUID | None = None) -> list[InventoryItem]:
        """Listet Artikel mit niedrigem Bestand auf"""
        async with self.session_factory() as session:
            stmt = select(InventoryItem).where(
                InventoryItem.quantity <= InventoryItem.reorder_point,
                InventoryItem.is_active == True
            )
            if project_id:
                stmt = stmt.where(InventoryItem.project_id == project_id)

            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_expiring_items(self, days_threshold: int = 30) -> list[InventoryItem]:
        """Listet Artikel mit ablaufendem Verfallsdatum"""
        async with self.session_factory() as session:
            expiry_date = datetime.utcnow() + timedelta(days=days_threshold)
            stmt = select(InventoryItem).where(
                InventoryItem.expiration_date <= expiry_date,
                InventoryItem.expiration_date > datetime.utcnow(),
                InventoryItem.is_active == True
            ).order_by(InventoryItem.expiration_date)

            result = await session.execute(stmt)
            return result.scalars().all()

    # ==================== Packing List Management ====================

    @audit_log(action="CREATE_PACKINGLIST", entity_type="packing_list")
    async def create_packing_list(self, packing_data: PackingListCreate, user_id: UUID) -> PackingList:
        """
        Erstellt Packliste für Projektauslieferung
        Reserviert Bestand und generiert PDF
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
                created_by=user_id,
                status="draft"
            )
            packing_list.generate_number()

            session.add(packing_list)
            await session.flush()  # Um ID zu erhalten

            # Verarbeite Items
            total_weight = Decimal("0")
            total_volume = Decimal("0")

            for item_data in packing_data.items:
                # Lade Inventory Item
                stmt = select(InventoryItem).where(InventoryItem.id == item_data["item_id"]).with_for_update()
                result = await session.execute(stmt)
                item = result.scalar_one()

                # Prüfe Bestand
                quantity_requested = item_data["quantity"]
                if item.available_quantity < quantity_requested:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Nicht genügend Bestand für {item.name}. Verfügbar: {item.available_quantity}"
                    )

                # Reserviere Bestand
                item.reserved_quantity += quantity_requested

                # Erstelle Packlist Item
                packing_item = PackingListItem(
                    packing_list_id=packing_list.id,
                    item_id=item.id,
                    item_name=item.name,
                    item_sku=item.sku,
                    item_category=item.category.value,
                    quantity_requested=quantity_requested,
                    quantity_shipped=quantity_requested,
                    condition_at_shipment=item.condition,
                    notes=item_data.get("notes")
                )
                session.add(packing_item)

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
            await self.event_bus.publish(Event(
                aggregate_id=packing_list.id,
                aggregate_type="PackingList",
                event_type="PackingListCreated",
                data={
                    "number": packing_list.packing_list_number,
                    "items_count": len(packing_data.items),
                    "recipient": packing_data.recipient_name
                },
                user_id=user_id,
                metadata={}
            ))

            return packing_list

    @audit_log(action="CONFIRM_PACKINGLIST", entity_type="packing_list")
    async def confirm_packing_list(self, packing_list_id: UUID, user_id: UUID) -> PackingList:
        """
        Bestätigt Packliste und führt Lagerabgang durch
        """
        async with self.session_factory() as session:
            # Lade Packliste mit Items
            stmt = select(PackingList).where(PackingList.id == packing_list_id)
            result = await session.execute(stmt)
            packing_list = result.scalar_one()

            if packing_list.status != "draft":
                raise HTTPException(status_code=400, detail=f"Packing list already {packing_list.status}")

            # Führe für jedes Item einen Lagerabgang durch
            for item in packing_list.items:
                # Erstelle Stock Movement
                movement = StockMovementCreate(
                    item_id=item.item_id,
                    movement_type=StockMovementType.OUTBOUND,
                    quantity=item.quantity_shipped,
                    reason=f"Packing list {packing_list.packing_list_number}",
                    reference_type="packing_list",
                    reference_id=packing_list_id,
                    destination_location=packing_list.recipient_address
                )

                await self.update_stock(movement, user_id, "system")

                # Reduziere Reservierung
                stmt = select(InventoryItem).where(InventoryItem.id == item.item_id)
                result = await session.execute(stmt)
                inventory_item = result.scalar_one()
                inventory_item.reserved_quantity -= item.quantity_shipped
                session.add(inventory_item)

            # Update Packliste
            packing_list.status = "confirmed"
            packing_list.confirmed_by = user_id
            packing_list.confirmed_at = datetime.utcnow()

            await session.commit()
            await session.refresh(packing_list)

            return packing_list

    @audit_log(action="DELIVER_PACKINGLIST", entity_type="packing_list")
    async def mark_as_delivered(self, packing_list_id: UUID, signature_data: str | None = None) -> PackingList:
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
            await self.event_bus.publish(Event(
                aggregate_id=packing_list.project_id,
                aggregate_type="Project",
                event_type="SuppliesDelivered",
                data={
                    "packing_list_id": str(packing_list_id),
                    "packing_list_number": packing_list.packing_list_number
                },
                user_id=packing_list.created_by,
                metadata={}
            ))

            return packing_list

    # ==================== Helper Methods ====================

    async def _create_skr42_booking_for_movement(self, movement: StockMovement, item: InventoryItem, session):
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
                description=f"Stock inbound: {item.name} x{movement.quantity}"
            )
        elif movement.movement_type == StockMovementType.OUTBOUND:
            # Abgang: Projektkosten (70000) an Bestandskonto (20000)
            await create_skr42_booking(
                amount=value_change,
                debit_account="70000",  # Projektausgaben
                credit_account="20000",  # Warenlager
                project_id=item.project_id,
                reference_id=movement.id,
                description=f"Stock outbound: {item.name} x{movement.quantity}"
            )

    async def _trigger_reorder(self, item: InventoryItem, session):
        """Löst Nachbestellung aus (kann mit ERPNext/Email verbunden werden)"""
        logger.warning(f"Low stock alert: {item.name} (SKU: {item.sku}) - {item.available_quantity} left, reorder point: {item.reorder_point}")

        # Publish Event für Nachbestellung
        await self.event_bus.publish(Event(
            aggregate_id=item.id,
            aggregate_type="InventoryItem",
            event_type="ReorderNeeded",
            data={
                "item_name": item.name,
                "sku": item.sku,
                "current_stock": item.quantity,
                "reorder_point": item.reorder_point,
                "suggested_order": item.max_stock_level - item.quantity if item.max_stock_level else item.reorder_point * 2
            },
            user_id=None,  # System-Event
            metadata={}
        ))

    # ==================== Reports ====================

    async def get_inventory_value_report(self, project_id: UUID | None = None) -> dict[str, Any]:
        """Bericht: Gesamtwert des Lagers nach Kategorie"""
        async with self.session_factory() as session:
            stmt = select(
                InventoryItem.category,
                func.sum(InventoryItem.total_value).label('total_value'),
                func.sum(InventoryItem.quantity).label('total_quantity')
            ).where(InventoryItem.is_active == True)

            if project_id:
                stmt = stmt.where(InventoryItem.project_id == project_id)

            stmt = stmt.group_by(InventoryItem.category)
            result = await session.execute(stmt)

            report = {
                "generated_at": datetime.utcnow().isoformat(),
                "total_value": Decimal("0"),
                "categories": []
            }

            for row in result:
                category_data = {
                    "category": row.category.value,
                    "total_value": float(row.total_value) if row.total_value else 0,
                    "total_quantity": row.total_quantity
                }
                report["categories"].append(category_data)
                report["total_value"] += row.total_value or 0

            return report

    async def get_movement_history(self, item_id: UUID, limit: int = 100) -> list[StockMovement]:
        """Zeigt Bewegungs-History für ein Item"""
        async with self.session_factory() as session:
            stmt = select(StockMovement).where(
                StockMovement.item_id == item_id
            ).order_by(StockMovement.created_at.desc()).limit(limit)

            result = await session.execute(stmt)
            return result.scalars().all()
