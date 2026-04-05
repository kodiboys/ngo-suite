# FILE: src/adapters/api_inventory.py
# MODULE: Inventory API Endpoints (FastAPI)
# REST Endpoints für Lagerverwaltung, Packlisten, Bewegungen

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from src.adapters.auth import get_current_active_user, require_role
from src.core.entities.base import User, UserRole
from src.core.entities.inventory import (
    InventoryItemCreate,
    PackingListCreate,
    StockMovementCreate,
)
from src.services.inventory_service import InventoryService
from src.services.pdf_generator import generate_packing_list_pdf

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

# ==================== Inventory Items ====================

@router.post("/items")
async def create_item(
    request: Request,
    item_data: InventoryItemCreate,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER))
):
    """Erstellt neuen Lagerartikel"""
    item = await inventory_service.create_item(item_data, current_user.id)
    return {
        "id": str(item.id),
        "name": item.name,
        "sku": item.sku,
        "quantity": item.quantity
    }

@router.get("/items/low-stock")
async def get_low_stock_items(
    project_id: UUID | None = None,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(get_current_active_user)
):
    """Listet Artikel mit niedrigem Bestand"""
    items = await inventory_service.get_low_stock_items(project_id)
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "sku": item.sku,
            "quantity": item.quantity,
            "min_stock_level": item.min_stock_level,
            "status": item.status.value
        }
        for item in items
    ]

@router.get("/items/expiring")
async def get_expiring_items(
    days: int = Query(30, ge=1, le=365),
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER))
):
    """Listet Artikel mit ablaufendem Verfallsdatum"""
    items = await inventory_service.get_expiring_items(days)
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "expiration_date": item.expiration_date.isoformat() if item.expiration_date else None,
            "quantity": item.quantity,
            "days_until_expiry": (item.expiration_date - datetime.utcnow()).days if item.expiration_date else None
        }
        for item in items
    ]

# ==================== Stock Movements ====================

@router.post("/movements")
async def create_movement(
    request: Request,
    movement_data: StockMovementCreate,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER))
):
    """Führt Lagerbewegung durch (Zugang/Abgang)"""
    movement = await inventory_service.update_stock(
        movement_data,
        current_user.id,
        request.client.host
    )
    return {
        "id": str(movement.id),
        "item_id": str(movement.item_id),
        "movement_type": movement.movement_type.value,
        "quantity": movement.quantity,
        "new_quantity": movement.new_quantity
    }

@router.get("/movements/{item_id}")
async def get_item_movements(
    item_id: UUID,
    limit: int = 100,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(get_current_active_user)
):
    """Zeigt Bewegungs-History für ein Item"""
    movements = await inventory_service.get_movement_history(item_id, limit)
    return [
        {
            "id": str(m.id),
            "type": m.movement_type.value,
            "quantity": m.quantity,
            "reason": m.reason,
            "created_at": m.created_at.isoformat(),
            "created_by": str(m.created_by)
        }
        for m in movements
    ]

# ==================== Packing Lists ====================

@router.post("/packing-lists")
async def create_packing_list(
    packing_data: PackingListCreate,
    background_tasks: BackgroundTasks,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER))
):
    """Erstellt neue Packliste"""
    packing_list = await inventory_service.create_packing_list(packing_data, current_user.id)
    return {
        "id": str(packing_list.id),
        "number": packing_list.packing_list_number,
        "status": packing_list.status,
        "pdf_url": packing_list.pdf_url
    }

@router.post("/packing-lists/{packing_list_id}/confirm")
async def confirm_packing_list(
    packing_list_id: UUID,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER))
):
    """Bestätigt Packliste und führt Lagerabgang durch"""
    packing_list = await inventory_service.confirm_packing_list(packing_list_id, current_user.id)
    return {
        "id": str(packing_list.id),
        "number": packing_list.packing_list_number,
        "status": packing_list.status
    }

@router.post("/packing-lists/{packing_list_id}/deliver")
async def mark_as_delivered(
    packing_list_id: UUID,
    signature_data: str | None = None,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER))
):
    """Markiert Packliste als zugestellt"""
    packing_list = await inventory_service.mark_as_delivered(packing_list_id, signature_data)
    return {
        "id": str(packing_list.id),
        "number": packing_list.packing_list_number,
        "status": packing_list.status,
        "delivered_at": packing_list.delivery_date.isoformat() if packing_list.delivery_date else None
    }

@router.get("/packing-lists/{packing_list_id}/pdf")
async def get_packing_list_pdf(
    packing_list_id: UUID,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(get_current_active_user)
):
    """Generiert und liefert PDF der Packliste"""
    # In Production: PDF aus S3/Wasabi laden
    pdf_url = await generate_packing_list_pdf(packing_list_id)
    return {"pdf_url": pdf_url}

# ==================== Reports ====================

@router.get("/reports/inventory-value")
async def get_inventory_value_report(
    project_id: UUID | None = None,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT))
):
    """Bericht: Gesamtwert des Lagers nach Kategorie"""
    report = await inventory_service.get_inventory_value_report(project_id)
    return report
