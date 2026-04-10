# FILE: src/adapters/api_events.py
# MODULE: Event Sourcing API Endpoints (FastAPI)
# REST Endpoints für Event Store Zugriff und Debugging
# Version: 3.0.0

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from src.adapters.auth import require_role
from src.core.entities.base import UserRole
from src.core.events.event_store import (
    EventStoreService,
    EventSubscriptionDB,
    EventSubscriptionService,
)
from src.read_models.projections import ProjectionManager

router = APIRouter(prefix="/api/v1/events", tags=["events"])


# ==================== Dependencies ====================


async def get_event_store(request: Request) -> EventStoreService:
    """Dependency Injection für Event Store Service"""
    session_factory = request.app.state.db_session_factory
    return EventStoreService(session_factory)


async def get_subscription_service(request: Request) -> EventSubscriptionService:
    """Dependency Injection für Event Subscription Service"""
    session_factory = request.app.state.db_session_factory
    event_store = await get_event_store(request)
    return EventSubscriptionService(session_factory, event_store)


async def get_projection_manager(request: Request) -> ProjectionManager:
    """Dependency Injection für Projection Manager"""
    session_factory = request.app.state.db_session_factory
    event_store = await get_event_store(request)
    return ProjectionManager(session_factory, event_store)


# ==================== Event Store Endpoints ====================


@router.get("/aggregate/{aggregate_id}")
async def get_aggregate_events(
    aggregate_id: UUID,
    from_version: int = Query(1, ge=1, description="Start version"),
    to_version: int | None = Query(None, ge=1, description="End version (optional)"),
    event_store: EventStoreService = Depends(get_event_store),
    current_user=Depends(require_role(UserRole.AUDITOR)),
):
    """
    Holt alle Events eines Aggregates (für Audit-Zwecke)

    **Audit-Zweck:** Vollständige Nachverfolgbarkeit aller Änderungen
    **Berechtigung:** Nur Auditor-Rolle
    """
    events = await event_store.get_events_for_aggregate(aggregate_id, from_version, to_version)

    return [
        {
            "event_id": str(e.event_id),
            "event_type": e.event_type,
            "sequence_number": e.sequence_number,
            "timestamp": e.timestamp.isoformat(),
            "user_id": str(e.user_id) if e.user_id else None,
            "data": e.data,
            "current_hash": e.current_hash,
        }
        for e in events
    ]


@router.get("/aggregate/{aggregate_id}/latest")
async def get_latest_aggregate_event(
    aggregate_id: UUID,
    event_store: EventStoreService = Depends(get_event_store),
    current_user=Depends(require_role(UserRole.AUDITOR)),
):
    """Holt das neueste Event eines Aggregates"""
    events = await event_store.get_events_for_aggregate(aggregate_id)

    if not events:
        return {"message": "No events found for this aggregate"}

    latest = events[-1]

    return {
        "event_id": str(latest.event_id),
        "event_type": latest.event_type,
        "sequence_number": latest.sequence_number,
        "timestamp": latest.timestamp.isoformat(),
        "user_id": str(latest.user_id) if latest.user_id else None,
        "data": latest.data,
        "current_hash": latest.current_hash,
    }


@router.get("/verify/{aggregate_id}")
async def verify_aggregate_integrity(
    aggregate_id: UUID,
    event_store: EventStoreService = Depends(get_event_store),
    current_user=Depends(require_role(UserRole.AUDITOR)),
):
    """
    Verifiziert die Integrität der Event-Kette (Merkle-Tree)

    Prüft ob alle Hashes in der Event-Kette korrekt sind.
    Manipulationen werden erkannt.
    """
    is_valid = await event_store.verify_integrity(aggregate_id)

    return {
        "aggregate_id": str(aggregate_id),
        "is_valid": is_valid,
        "verified_at": datetime.utcnow().isoformat(),
        "message": (
            "Event chain integrity verified"
            if is_valid
            else "Event chain integrity verification FAILED"
        ),
    }


@router.get("/type/{event_type}")
async def get_events_by_type(
    event_type: str,
    limit: int = Query(100, ge=1, le=1000),
    event_store: EventStoreService = Depends(get_event_store),
    current_user=Depends(require_role(UserRole.AUDITOR)),
):
    """Holt Events nach Typ (für Read Model Rebuilds)"""
    events = await event_store.get_events_by_type(event_type, limit=limit)

    return [
        {
            "event_id": str(e.event_id),
            "aggregate_id": str(e.aggregate_id),
            "aggregate_type": e.aggregate_type,
            "sequence_number": e.sequence_number,
            "timestamp": e.timestamp.isoformat(),
            "data": e.data,
        }
        for e in events
    ]


# ==================== Subscription Management ====================


@router.get("/subscriptions")
async def get_subscriptions(
    subscription_service: EventSubscriptionService = Depends(get_subscription_service),
    current_user=Depends(require_role(UserRole.AUDITOR)),
):
    """Listet alle Event Subscriptions mit Status"""
    async with subscription_service.session_factory() as session:
        stmt = select(EventSubscriptionDB)
        result = await session.execute(stmt)
        subscriptions = result.scalars().all()

        return [
            {
                "name": s.subscription_name,
                "last_processed_event": s.last_processed_event_id,
                "last_processed_position": s.last_processed_event_position,
                "status": s.status,
                "error_message": s.error_message,
                "retry_count": s.retry_count,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in subscriptions
        ]


@router.get("/subscriptions/{subscription_name}/status")
async def get_subscription_status(
    subscription_name: str,
    subscription_service: EventSubscriptionService = Depends(get_subscription_service),
    current_user=Depends(require_role(UserRole.AUDITOR)),
):
    """Holt detaillierten Status einer Subscription"""
    async with subscription_service.session_factory() as session:
        stmt = select(EventSubscriptionDB).where(
            EventSubscriptionDB.subscription_name == subscription_name
        )
        result = await session.execute(stmt)
        subscription = result.scalar_one_or_none()

        if not subscription:
            return {"error": f"Subscription '{subscription_name}' not found"}

        return {
            "name": subscription.subscription_name,
            "last_processed_event": subscription.last_processed_event_id,
            "last_processed_position": subscription.last_processed_event_position,
            "status": subscription.status,
            "error_message": subscription.error_message,
            "retry_count": subscription.retry_count,
            "updated_at": subscription.updated_at.isoformat() if subscription.updated_at else None,
        }


@router.post("/subscriptions/{subscription_name}/rebuild")
async def rebuild_read_model(
    subscription_name: str,
    projection_manager: ProjectionManager = Depends(get_projection_manager),
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    """
    Rebuildet ein Read Model komplett neu

    Verwendet für:
    - Schema-Änderungen
    - Datenkorrekturen
    - Performance-Optimierung
    """
    await projection_manager.subscription_service.rebuild_read_model(subscription_name)

    return {
        "subscription_name": subscription_name,
        "status": "rebuilding",
        "message": "Read model rebuild initiated",
        "started_at": datetime.utcnow().isoformat(),
    }


@router.post("/subscriptions/{subscription_name}/pause")
async def pause_subscription(
    subscription_name: str,
    subscription_service: EventSubscriptionService = Depends(get_subscription_service),
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    """Pausiert eine Subscription (vorübergehend)"""
    from sqlalchemy import update

    async with subscription_service.session_factory() as session:
        stmt = (
            update(EventSubscriptionDB)
            .where(EventSubscriptionDB.subscription_name == subscription_name)
            .values(status="paused")
        )
        await session.execute(stmt)
        await session.commit()

    return {
        "subscription_name": subscription_name,
        "status": "paused",
        "message": "Subscription paused",
        "paused_at": datetime.utcnow().isoformat(),
    }


@router.post("/subscriptions/{subscription_name}/resume")
async def resume_subscription(
    subscription_name: str,
    subscription_service: EventSubscriptionService = Depends(get_subscription_service),
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    """Setzt eine pausierte Subscription fort"""
    from sqlalchemy import update

    async with subscription_service.session_factory() as session:
        stmt = (
            update(EventSubscriptionDB)
            .where(EventSubscriptionDB.subscription_name == subscription_name)
            .values(status="active", error_message=None, retry_count=0)
        )
        await session.execute(stmt)
        await session.commit()

    return {
        "subscription_name": subscription_name,
        "status": "active",
        "message": "Subscription resumed",
        "resumed_at": datetime.utcnow().isoformat(),
    }


# ==================== Statistics ====================


@router.get("/stats")
async def get_event_store_stats(
    event_store: EventStoreService = Depends(get_event_store),
    current_user=Depends(require_role(UserRole.AUDITOR)),
):
    """Statistiken über den Event Store"""
    async with event_store.session_factory() as session:
        from src.core.events.event_store import EventStoreDB

        # Gesamtzahl Events
        total_stmt = select(func.count()).select_from(EventStoreDB)
        total_result = await session.execute(total_stmt)
        total_events = total_result.scalar() or 0

        # Events nach Typ
        type_stmt = select(EventStoreDB.event_type, func.count().label("count")).group_by(
            EventStoreDB.event_type
        )
        type_result = await session.execute(type_stmt)
        events_by_type = {row.event_type: row.count for row in type_result}

        # Events nach Aggregat-Typ
        agg_stmt = select(EventStoreDB.aggregate_type, func.count().label("count")).group_by(
            EventStoreDB.aggregate_type
        )
        agg_result = await session.execute(agg_stmt)
        events_by_aggregate = {row.aggregate_type: row.count for row in agg_result}

        # Events pro Tag (letzte 30 Tage)
        day_stmt = (
            select(func.date(EventStoreDB.timestamp).label("date"), func.count().label("count"))
            .where(
                EventStoreDB.timestamp
                >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            )
            .group_by(func.date(EventStoreDB.timestamp))
        )
        day_result = await session.execute(day_stmt)
        events_per_day = {str(row.date): row.count for row in day_result}

        return {
            "total_events": total_events,
            "events_by_type": events_by_type,
            "events_by_aggregate": events_by_aggregate,
            "events_last_30_days": events_per_day,
            "timestamp": datetime.utcnow().isoformat(),
        }


@router.get("/stats/aggregates")
async def get_aggregate_stats(
    event_store: EventStoreService = Depends(get_event_store),
    current_user=Depends(require_role(UserRole.AUDITOR)),
):
    """Statistiken über Aggregate im Event Store"""
    async with event_store.session_factory() as session:
        from sqlalchemy import distinct

        from src.core.events.event_store import EventStoreDB

        # Anzahl einzigartiger Aggregate
        agg_count_stmt = select(func.count(distinct(EventStoreDB.aggregate_id)))
        agg_count_result = await session.execute(agg_count_stmt)
        total_aggregates = agg_count_result.scalar() or 0

        # Aggregate nach Typ
        agg_type_stmt = select(
            EventStoreDB.aggregate_type,
            func.count(distinct(EventStoreDB.aggregate_id)).label("count"),
        ).group_by(EventStoreDB.aggregate_type)
        agg_type_result = await session.execute(agg_type_stmt)
        aggregates_by_type = {row.aggregate_type: row.count for row in agg_type_result}

        # Durchschnittliche Events pro Aggregate
        select(EventStoreDB.aggregate_type, func.avg(func.count()).label("avg_events")).group_by(
            EventStoreDB.aggregate_type
        )

        return {
            "total_aggregates": total_aggregates,
            "aggregates_by_type": aggregates_by_type,
            "timestamp": datetime.utcnow().isoformat(),
        }


# ==================== Snapshot Management ====================


@router.get("/snapshots/{aggregate_id}")
async def get_aggregate_snapshot(
    aggregate_id: UUID,
    event_store: EventStoreService = Depends(get_event_store),
    current_user=Depends(require_role(UserRole.AUDITOR)),
):
    """Holt den aktuellen Snapshot eines Aggregates"""
    snapshot = await event_store.get_snapshot(aggregate_id)

    if not snapshot:
        return {"message": "No snapshot found for this aggregate"}

    return {
        "aggregate_id": str(snapshot.aggregate_id),
        "aggregate_type": snapshot.aggregate_type,
        "version": snapshot.version,
        "state": snapshot.state,
        "last_event_id": str(snapshot.last_event_id),
        "timestamp": snapshot.timestamp.isoformat(),
    }


@router.post("/snapshots/{aggregate_id}")
async def create_aggregate_snapshot(
    aggregate_id: UUID,
    aggregate_type: str,
    version: int,
    event_store: EventStoreService = Depends(get_event_store),
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    """Erzwingt die Erstellung eines Snapshots für ein Aggregate"""
    # Lade letztes Event
    events = await event_store.get_events_for_aggregate(aggregate_id, version, version)

    if not events:
        return {"error": "No events found for this version"}

    last_event = events[0]

    # Replay Aggregate um aktuellen State zu erhalten
    state = await event_store.replay_aggregate(
        aggregate_id, aggregate_type, lambda e, s: {**s, **e.data}
    )

    snapshot = await event_store.create_snapshot(
        aggregate_id=aggregate_id,
        aggregate_type=aggregate_type,
        version=version,
        state=state,
        last_event_id=last_event.event_id,
    )

    return {
        "aggregate_id": str(snapshot.aggregate_id),
        "version": snapshot.version,
        "created_at": snapshot.timestamp.isoformat(),
        "message": "Snapshot created successfully",
    }


# ==================== Health Check ====================


@router.get("/health")
async def event_store_health(
    event_store: EventStoreService = Depends(get_event_store),
):
    """Health Check für Event Store"""
    try:
        async with event_store.session_factory() as session:
            from sqlalchemy import text

            result = await session.execute(text("SELECT 1"))
            if result.scalar() == 1:
                return {
                    "status": "healthy",
                    "event_store": "operational",
                    "timestamp": datetime.utcnow().isoformat(),
                }
    except Exception as e:
        return {
            "status": "unhealthy",
            "event_store": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }

    return {
        "status": "healthy",
        "event_store": "operational",
        "timestamp": datetime.utcnow().isoformat(),
    }
