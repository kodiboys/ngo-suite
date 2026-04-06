# FILE: src/adapters/api_inventory.py
# MODULE: Inventory API Endpoints (FastAPI)
# REST Endpoints für Lagerverwaltung, Packlisten, Bewegungen, Bedarfe
# Version: 3.0 - Erweitert um Need-Fulfillment, Transparenz & Trackability

from datetime import datetime, timezone, UUID
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Query, status
from sqlalchemy.sql import select
from sqlalchemy.orm import selectinload

from src.services.inventory_service import InventoryService
from src.services.need_fulfillment_service import NeedFulfillmentService
from src.services.pdf_generator import generate_packing_list_pdf
from src.adapters.auth import get_current_active_user, require_role
from src.core.entities.base import User, UserRole
from src.core.entities.inventory import (
    InventoryItemCreate, StockMovementCreate, PackingListCreate,
    PackingListResponse, StockMovementType
)
from src.core.entities.project import PackingList


router = APIRouter(
    prefix="/api/v1/inventory",
    tags=["inventory"],
)


# ==================== Dependency-Injection ====================

def get_inventory_service(request: Request) -> InventoryService:
    """
    Dependency Injection für Inventory Service via request.app.state.
    """
    db_session_factory = request.app.state.db_session_factory
    redis_client = request.app.state.redis
    event_bus = request.app.state.event_bus
    return InventoryService(
        session_factory=db_session_factory,
        redis_client=redis_client,
        event_bus=event_bus,
    )


def get_need_fulfillment_service(request: Request) -> NeedFulfillmentService:
    """
    Dependency Injection für Need-Fulfillment Service.
    """
    db_session_factory = request.app.state.db_session_factory
    redis_client = request.app.state.redis
    return NeedFulfillmentService(session_factory=db_session_factory, redis_client=redis_client)


# ==================== Inventory Items ====================

@router.post("/items", status_code=status.HTTP_201_CREATED)
async def create_item(
    request: Request,
    item_data: InventoryItemCreate,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Erstellt neuen Lagerartikel (mit optionaler Need-Verknüpfung).
    """
    item = await inventory_service.create_item(item_data=item_data, user_id=current_user.id)

    return {
        "data": {
            "id": str(item.id),
            "name": item.name,
            "sku": item.sku,
            "quantity": item.quantity,
            "need_id": str(item.need_id) if item.need_id else None,
        }
    }


@router.get("/items/low-stock")
async def get_low_stock_items(
    project_id: Optional[UUID] = None,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Listet Artikel mit niedrigem Bestand.
    """
    items = await inventory_service.get_low_stock_items(project_id=project_id)

    return {
        "data": [
            {
                "id": str(item.id),
                "name": item.name,
                "sku": item.sku,
                "quantity": item.quantity,
                "min_stock_level": item.min_stock_level,
                "status": item.status.value,
                "need_id": str(item.need_id) if item.need_id else None,
            }
            for item in items
        ]
    }


@router.get("/items/expiring")
async def get_expiring_items(
    days: int = Query(
        30,
        ge=1,
        le=365,
        description="Wie viele Tage ab heute soll der Ablauf berücksichtigt werden?",
    ),
    project_id: Optional[UUID] = None,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Listet Artikel mit ablaufendem Verfallsdatum.
    """
    items = await inventory_service.get_expiring_items(
        days=days,
        project_id=project_id,
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    return {
        "data": [
            {
                "id": str(item.id),
                "name": item.name,
                "expiration_date": item.expiration_date.isoformat()
                if item.expiration_date
                else None,
                "quantity": item.quantity,
                "days_until_expiry": (
                    (item.expiration_date - now).days
                    if item.expiration_date
                    else None
                ),
                "need_id": str(item.need_id) if item.need_id else None,
            }
            for item in items
        ]
    }


@router.get("/items/for-needs")
async def get_items_for_needs(
    project_id: Optional[UUID] = None,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Listet Lagerartikel, die für Bedarfe relevant sind (z.B. low stock).
    """
    items = await inventory_service.get_low_stock_for_needs(project_id=project_id)

    return {
        "data": items,
    }


@router.get("/transparency", response_model=None)
async def get_transparency_inventory(
    project_id: Optional[UUID] = None,
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> dict:
    """
    Holt Lagerbestände für die Transparenzseite (öffentlich, kein Auth nötig).
    """
    items = await inventory_service.get_transparency_inventory(project_id=project_id)

    return {
        "data": items,
    }


@router.post("/items/{item_id}/link-need/{need_id}")
async def link_item_to_need(
    item_id: UUID,
    need_id: UUID,
    request: Request,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Verknüpft einen Lagerartikel mit einem Bedarf.
    """
    item = await inventory_service.link_item_to_need(
        item_id=item_id,
        need_id=need_id,
        user_id=current_user.id,
        ip_address=request.client.host,
    )

    return {
        "data": {
            "id": str(item.id),
            "name": item.name,
            "need_id": str(item.need_id),
            "message": f"Item {item.name} linked to need",
        }
    }


# ==================== Stock Movements ====================

@router.post("/movements", status_code=status.HTTP_201_CREATED)
async def create_movement(
    request: Request,
    movement_data: StockMovementCreate,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Führt Lagerbewegung durch (Zugang/Abgang).
    """
    movement = await inventory_service.update_stock(
        movement_data=movement_data,
        user_id=current_user.id,
        ip_address=request.client.host,
    )

    return {
        "data": {
            "id": str(movement.id),
            "item_id": str(movement.item_id),
            "movement_type": movement.movement_type.value,
            "quantity": movement.quantity,
            "new_quantity": movement.new_quantity,
            "need_id": str(movement.need_id) if movement.need_id else None,
        }
    }


@router.get("/movements/{item_id}")
async def get_item_movements(
    item_id: UUID,
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Max. Anzahl der Bewegungen, die zurückgeliefert werden",
    ),
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Zeigt Bewegungs-History für ein Item.
    """
    movements = await inventory_service.get_movement_history(item_id=item_id, limit=limit)

    return {
        "data": [
            {
                "id": str(m.id),
                "type": m.movement_type.value,
                "quantity": m.quantity,
                "reason": m.reason,
                "created_at": m.created_at.isoformat(),
                "created_by": str(m.created_by),
                "need_id": str(m.need_id) if m.need_id else None,
            }
            for m in movements
        ]
    }


@router.get("/needs/{need_id}/fulfillment-history")
async def get_need_fulfillment_history(
    need_id: UUID,
    project_id: Optional[UUID] = None,
    limit: int = Query(
        50,
        ge=1,
        description="Max. Anzahl der Einträge in der History",
    ),
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Zeigt History der Bedarfserfüllungen für einen Need.
    """
    history = await inventory_service.get_need_fulfillment_history(
        need_id=need_id,
        project_id=project_id,
        limit=limit,
    )

    return {
        "data": history,
    }


# ==================== Need Fulfillment (v3.0) ====================

@router.post("/needs/{need_id}/reserve")
async def reserve_for_need(
    need_id: UUID,
    quantity: int,
    request: Request,
    fulfillment_service: NeedFulfillmentService = Depends(
        get_need_fulfillment_service
    ),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Reserviert Lagerbestand für einen Bedarf.
    """
    result = await fulfillment_service.reserve_inventory_for_need(
        need_id=need_id,
        quantity=quantity,
        user_id=current_user.id,
        ip_address=request.client.host,
    )

    return {
        "data": result,
    }


@router.post("/needs/{need_id}/fulfill")
async def fulfill_need_from_inventory(
    need_id: UUID,
    quantity: int,
    recipient_name: str,
    recipient_address: str,
    recipient_email: Optional[str] = None,
    shipping_method: Optional[str] = None,
    request: Request | None = None,
    fulfillment_service: NeedFulfillmentService = Depends(
        get_need_fulfillment_service
    ),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Erfüllt einen Bedarf aus dem Lagerbestand.
    """
    result = await fulfillment_service.fulfill_need_from_inventory(
        need_id=need_id,
        quantity=quantity,
        user_id=current_user.id,
        recipient_name=recipient_name,
        recipient_address=recipient_address,
        recipient_email=recipient_email,
        shipping_method=shipping_method,
        ip_address=request.client.host if request else "system",
    )

    return {
        "data": result,
    }


@router.get("/needs/{need_id}/fulfillment-status")
async def get_need_fulfillment_status(
    need_id: UUID,
    fulfillment_service: NeedFulfillmentService = Depends(
        get_need_fulfillment_service
    ),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Holt detaillierten Status der Bedarfserfüllung.
    """
    result = await fulfillment_service.get_need_fulfillment_status(need_id=need_id)

    return {
        "data": result,
    }


@router.get("/projects/{project_id}/fulfillment-summary")
async def get_project_fulfillment_summary(
    project_id: UUID,
    fulfillment_service: NeedFulfillmentService = Depends(
        get_need_fulfillment_service
    ),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Holt Übersicht über alle Bedarfserfüllungen eines Projekts.
    """
    result = await fulfillment_service.get_project_fulfillment_summary(
        project_id=project_id
    )

    return {
        "data": result,
    }


# ==================== Packing Lists ====================

@router.post("/packing-lists", status_code=status.HTTP_201_CREATED)
async def create_packing_list(
    packing_data: PackingListCreate,
    background_tasks: BackgroundTasks,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Erstellt neue Packliste (mit Need-Unterstützung).
    """
    packing_list = await inventory_service.create_packing_list(
        packing_data=packing_data,
        user_id=current_user.id,
    )

    return {
        "data": {
            "id": str(packing_list.id),
            "number": packing_list.packing_list_number,
            "status": packing_list.status,
            "pdf_url": packing_list.pdf_url,
            "transparency_hash": packing_list.transparency_hash,
            "need_ids": packing_list.need_ids,
        }
    }


@router.post("/packing-lists/{packing_list_id}/confirm")
async def confirm_packing_list(
    packing_list_id: UUID,
    request: Request,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Bestätigt Packliste und führt Lagerabgang durch.
    """
    packing_list = await inventory_service.confirm_packing_list(
        packing_list_id=packing_list_id,
        user_id=current_user.id,
        ip_address=request.client.host,
    )

    return {
        "data": {
            "id": str(packing_list.id),
            "number": packing_list.packing_list_number,
            "status": packing_list.status,
            "transparency_hash": packing_list.transparency_hash,
        }
    }


@router.post("/packing-lists/{packing_list_id}/deliver")
async def mark_as_delivered(
    packing_list_id: UUID,
    signature_data: Optional[str] = None,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Markiert Packliste als zugestellt.
    """
    packing_list = await inventory_service.mark_as_delivered(
        packing_list_id=packing_list_id,
        signature_data=signature_data,
    )

    return {
        "data": {
            "id": str(packing_list.id),
            "number": packing_list.packing_list_number,
            "status": packing_list.status,
            "delivered_at": packing_list.delivery_date.isoformat()
            if packing_list.delivery_date
            else None,
            "transparency_hash": packing_list.transparency_hash,
        }
    }


@router.get("/packing-lists/{packing_list_id}/pdf")
async def get_packing_list_pdf(
    packing_list_id: UUID,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Generiert und liefert PDF der Packliste.
    """
    # 1. Prüfe, ob der Benutzer Zugriff auf diese Packliste hat
    has_access = await inventory_service.can_access_packing_list(
        packing_list_id=packing_list_id,
        user_id=current_user.id,
    )
    if not has_access:
        raise HTTPException(
            status_code=403,
            detail="Access forbidden to this packing list",
        )

    pdf_url = await generate_packing_list_pdf(packing_list_id=packing_list_id)

    return {
        "data": {
            "pdf_url": pdf_url,
            "transparency_hash": "tracking_hash_placeholder",
        }
    }


@router.get("/packing-lists/track/{transparency_hash}")
async def track_packing_list(
    transparency_hash: str,
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> dict:
    """
    Öffentliche Sendungsverfolgung (kein Auth nötig).
    """
    async with inventory_service.session_factory() as session:
        stmt = (
            select(PackingList)
            .options(selectinload(PackingList.items))
            .where(PackingList.transparency_hash == transparency_hash)
        )
        result = await session.execute(stmt)
        packing_list = result.scalar_one_or_none()

        if not packing_list:
            raise HTTPException(status_code=404, detail="Packing list not found")

        return {
            "data": {
                "number": packing_list.packing_list_number,
                "status": packing_list.status,
                "recipient_name": packing_list.recipient_name,
                "recipient_address": packing_list.recipient_address,
                "shipping_date": packing_list.shipping_date.isoformat()
                if packing_list.shipping_date
                else None,
                "delivery_date": packing_list.delivery_date.isoformat()
                if packing_list.delivery_date
                else None,
                "tracking_number": packing_list.tracking_number,
                "items": [
                    {
                        "name": item.item_name,
                        "quantity": item.quantity_shipped,
                    }
                    for item in packing_list.items
                ],
            }
        }


# ==================== Reports ====================

@router.get("/reports/inventory-value")
async def get_inventory_value_report(
    project_id: Optional[UUID] = None,
    inventory_service: InventoryService = Depends(get_inventory_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
) -> dict:
    """
    Bericht: Gesamtwert des Lagers nach Kategorie.
    """
    report = await inventory_service.get_inventory_value_report(
        project_id=project_id,
    )

    return {
        "data": report,
    }