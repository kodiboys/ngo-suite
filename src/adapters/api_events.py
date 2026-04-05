# FILE: src/adapters/api_events.py
# MODULE: Event Sourcing API Endpoints (FastAPI)
# REST Endpoints für Event Store Zugriff und Debugging

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.adapters.auth import require_role
from src.core.entities.base import UserRole
from src.core.events.event_store import EventStoreService, EventSubscriptionService
from src.read_models.projections import ProjectionManager

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("/aggregate/{aggregate_id}")
async def get_aggregate_events(
    aggregate_id: UUID,
    from_version: int = Query(1, ge=1),
    to_version: int | None = None,
    event_store: EventStoreService = Depends(get_event_store),
    current_user = Depends(require_role(UserRole.AUDITOR))
):
    """
    Holt alle Events eines Aggregates (für Audit-Zwecke)
    """
    events = await event_store.get_events_for_aggregate(
        aggregate_id, from_version, to_version
    )

    return [
        {
            "event_id": str(e.event_id),
            "event_type": e.event_type,
            "sequence_number": e.sequence_number,
            "timestamp": e.timestamp.isoformat(),
            "user_id": str(e.user_id) if e.user_id else None,
            "data": e.data,
            "current_hash": e.current_hash
        }
        for e in events
    ]


@router.get("/verify/{aggregate_id}")
async def verify_aggregate_integrity(
    aggregate_id: UUID,
    event_store: EventStoreService = Depends(get_event_store),
    current_user = Depends(require_role(UserRole.AUDITOR))
):
    """
    Verifiziert die Integrität der Event-Kette (Merkle-Tree)
    """
    is_valid = await event_store.verify_integrity(aggregate_id)

    return {
        "aggregate_id": str(aggregate_id),
        "is_valid": is_valid,
        "verified_at": datetime.utcnow().isoformat()
    }


@router.post("/subscriptions/{subscription_name}/rebuild")
async def rebuild_read_model(
    subscription_name: str,
    projection_manager: ProjectionManager = Depends(get_projection_manager),
    current_user = Depends(require_role(UserRole.ADMIN))
):
    """
    Rebuildet ein Read Model komplett neu
    """
    await projection_manager.subscription_service.rebuild_read_model(subscription_name)

    return {
        "subscription_name": subscription_name,
        "status": "rebuilding",
        "message": "Read model rebuild initiated"
    }


@router.get("/subscriptions")
async def get_subscriptions(
    subscription_service: EventSubscriptionService = Depends(get_subscription_service),
    current_user = Depends(require_role(UserRole.AUDITOR))
):
    """
    Listet alle Event Subscriptions mit Status
    """
    async with subscription_service.session_factory() as session:
        from sqlalchemy import select

        from src.core.events.event_store import EventSubscriptionDB

        stmt = select(EventSubscriptionDB)
        result = await session.execute(stmt)
        subscriptions = result.scalars().all()

        return [
            {
                "name": s.subscription_name,
                "last_processed_event": s.last_processed_event_id,
                "status": s.status,
                "error_message": s.error_message,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None
            }
            for s in subscriptions
        ]


@router.get("/stats")
async def get_event_store_stats(
    event_store: EventStoreService = Depends(get_event_store),
    current_user = Depends(require_role(UserRole.AUDITOR))
):
    """
    Statistiken über den Event Store
    """
    async with event_store.session_factory() as session:
        from sqlalchemy import func, select

        from src.core.events.event_store import EventStoreDB

        # Gesamtzahl Events
        total_stmt = select(func.count()).select_from(EventStoreDB)
        total_result = await session.execute(total_stmt)
        total_events = total_result.scalar() or 0

        # Events nach Typ
        type_stmt = select(
            EventStoreDB.event_type,
            func.count().label('count')
        ).group_by(EventStoreDB.event_type)
        type_result = await session.execute(type_stmt)
        events_by_type = {row.event_type: row.count for row in type_result}

        # Events nach Aggregat
        agg_stmt = select(
            EventStoreDB.aggregate_type,
            func.count().label('count')
        ).group_by(EventStoreDB.aggregate_type)
        agg_result = await session.execute(agg_stmt)
        events_by_aggregate = {row.aggregate_type: row.count for row in agg_result}

        return {
            "total_events": total_events,
            "events_by_type": events_by_type,
            "events_by_aggregate": events_by_aggregate,
            "timestamp": datetime.utcnow().isoformat()
        }
