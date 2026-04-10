# FILE: src/core/events/event_bus.py
# MODULE: Event Bus mit CQRS & Outbox Pattern
# Version: 3.2 - Korrigierte Importe, EventStoreDB-Anbindung, korrekte Felder

import json
import logging
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
from typing import Any
from uuid import UUID

from celery import Celery
from redis import Redis
from sqlalchemy import select, func

# Korrekter Import: EventStoreDB wird als EventStore alias importiert
from src.core.entities.base import Donation, Project
from src.core.events.event_store import EventStoreDB as EventStore
from src.core.config import settings

logger = logging.getLogger(__name__)

# Celery App Konfiguration (Broker aus Settings)
celery_app = Celery("trueangels", broker=settings.REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Berlin",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)


@dataclass
class Event:
    aggregate_id: UUID
    aggregate_type: str
    event_type: str
    data: dict[str, Any]
    user_id: UUID
    metadata: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    sequence_number: int | None = None   # Wird beim Persistieren gesetzt


class RedisCircuitBreaker:
    """
    Distributed Circuit Breaker via Redis.
    Funktioniert über mehrere API-Instanzen hinweg.
    """

    def __init__(self, redis: Redis, name: str, threshold: int = 5, timeout: int = 60):
        self.redis = redis
        self.name = f"cb:{name}"
        self.threshold = threshold
        self.timeout = timeout

    async def allow_request(self) -> bool:
        state = await self.redis.get(f"{self.name}:state")
        if state == b"OPEN":
            opened_at = await self.redis.get(f"{self.name}:opened_at")
            if opened_at:
                delta = (
                    datetime.now(UTC) - datetime.fromisoformat(opened_at.decode())
                ).total_seconds()
                if delta > self.timeout:
                    await self.redis.set(f"{self.name}:state", "HALF_OPEN")
                    return True
            return False
        return True

    async def record_failure(self):
        fails = await self.redis.incr(f"{self.name}:fails")
        if fails >= self.threshold:
            await self.redis.set(f"{self.name}:state", "OPEN")
            await self.redis.set(f"{self.name}:opened_at", datetime.now(UTC).isoformat())

    async def record_success(self):
        await self.redis.set(f"{self.name}:state", "CLOSED")
        await self.redis.delete(f"{self.name}:fails")


class EventBus:
    """
    Asynchroner Event Bus mit PostgreSQL-Persistenz & Redis-DLQ.
    """

    def __init__(self, redis_client: Redis, session_factory):
        self.redis = redis_client
        self.session_factory = session_factory
        self.handlers: dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, handler: Callable[[Event], Awaitable[None]]):
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)

    async def publish(self, event: Event, store_in_db: bool = True):
        """Publiziert ein Event und triggert Background-Tasks"""
        if store_in_db:
            await self._persist_event(event)

        # Triggere Celery Task für schwere Arbeit (Out-of-Process)
        celery_app.send_task(
            "src.core.events.event_bus.process_event_task", args=[asdict(event)], queue="events"
        )

    async def _persist_event(self, event: Event):
        """Schreibt Event in den PostgreSQL Event Store (Merkle-Hash)"""
        async with self.session_factory() as session:
            stmt = (
                select(EventStore)
                .where(EventStore.aggregate_id == event.aggregate_id)
                .order_by(EventStore.sequence_number.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            last_event = result.scalar_one_or_none()

            # Korrektur: sequence_number, nicht version
            sequence_number = (last_event.sequence_number + 1) if last_event else 1
            prev_hash = last_event.current_hash if last_event else None

            # Hash berechnen mit sequence_number
            curr_hash = self._compute_hash(event, sequence_number, prev_hash)

            # EventStoreDB-Instanz mit korrekten Feldnamen
            db_event = EventStore(
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                sequence_number=sequence_number,
                event_type=event.event_type,
                event_version="1.0",
                data=event.data,                     # Achtung: data, nicht event_data
                event_metadata=event.metadata or {},
                user_id=event.user_id,
                timestamp=event.timestamp,
                previous_hash=prev_hash,
                current_hash=curr_hash,
            )
            session.add(db_event)
            await session.commit()
            # Rückschreiben der Sequence Number in das Event-Objekt
            event.sequence_number = sequence_number

    def _compute_hash(self, event: Event, sequence_number: int, prev_hash: str | None) -> str:
        content = f"{event.aggregate_id}|{sequence_number}|{event.event_type}|{json.dumps(event.data, sort_keys=True)}|{event.timestamp.isoformat()}"
        if prev_hash:
            content += f"|{prev_hash}"
        return hashlib.sha256(content.encode()).hexdigest()


# ==================== CELERY TASKS (Separated Logic) ====================


@celery_app.task(name="src.core.events.event_bus.process_event_task", bind=True)
def process_event_task(self, event_dict: dict):
    """Zentraler Worker-Einstiegspunkt für Events"""
    event_type = event_dict.get("event_type")

    if event_type == "donation.created":
        handle_donation_created.delay(event_dict)
    elif event_type == "project.updated":
        update_project_kpi.delay(event_dict.get("aggregate_id"))


@celery_app.task(bind=True, max_retries=5)
def handle_donation_created(self, event_data: dict):
    """Logik für neue Spenden (Buchhaltung, Belege)"""
    try:
        logger.info(f"Processing Donation {event_data['aggregate_id']}")
        # Hier später die Geschäftslogik einfügen
    except Exception as e:
        logger.error(f"Error in donation task: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task
def update_project_kpi(project_id: str):
    """Berechnet KPIs für das Read Model neu"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        total = (
            session.query(func.sum(Donation.amount))
            .filter(Donation.project_id == project_id, Donation.payment_status == "succeeded")
            .scalar()
            or 0
        )
        session.query(Project).filter(Project.id == project_id).update({"donations_total": total})
        session.commit()
