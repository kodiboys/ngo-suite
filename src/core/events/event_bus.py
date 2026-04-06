# FILE: src/core/events/event_bus.py
# MODULE: Event Bus mit CQRS & Outbox Pattern
# Für Event-Sourcing & Async Processing mit Retry/Backoff

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import func
from decimal import Decimal

from celery import Celery
from redis import Redis
from sqlalchemy import select

from src.core.entities.base import EventStore

logger = logging.getLogger(__name__)

# Celery App für Background Jobs
celery_app = Celery("trueangels", broker="redis://redis:6379/0")

# Celery Konfiguration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Berlin",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 Minuten
    task_soft_time_limit=25 * 60,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_annotations={"*": {"rate_limit": "1000/h"}},
)


@dataclass
class Event:
    """Domain Event für Event Sourcing"""

    aggregate_id: UUID
    aggregate_type: str
    event_type: str
    data: dict[str, Any]
    user_id: UUID
    metadata: dict[str, Any]
    timestamp: datetime = datetime.utcnow()
    version: int | None = None


class EventBus:
    """
    Asynchroner Event Bus mit:
    - Retry/Backoff (exponential backoff)
    - Dead Letter Queue (Redis)
    - Outbox Pattern (für Exactly-Once)
    - Circuit Breaker für externe Services
    """

    def __init__(self, redis_client: Redis, session_factory):
        self.redis = redis_client
        self.session_factory = session_factory
        self.handlers: dict[str, list[Callable]] = {}
        self.outbox_queue = asyncio.Queue()
        self.circuit_breakers: dict[str, CircuitBreaker] = {}

    def subscribe(self, event_type: str, handler: Callable[[Event], Awaitable[None]]):
        """Event-Handler registrieren"""
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)
        logger.info(f"Handler registered for event: {event_type}")

    async def publish(self, event: Event, store_in_db: bool = True):
        """
        Event publishen mit:
        - At-least-once delivery
        - Dead Letter Queue bei Fehlern
        - Event Store Persistenz
        """
        # 1. Event im Event Store persistieren
        if store_in_db:
            await self._persist_event(event)

        # 2. In Outbox Queue (für Replay & Recovery)
        await self.outbox_queue.put(event)

        # 3. Async verarbeiten
        asyncio.create_task(self._process_event_with_retry(event))

    async def _persist_event(self, event: Event):
        """Event in PostgreSQL Event Store schreiben"""
        async with self.session_factory() as session:
            # Hole nächste Version
            stmt = (
                select(EventStore)
                .where(EventStore.aggregate_id == event.aggregate_id)
                .order_by(EventStore.version.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            last_event = result.scalar_one_or_none()
            version = (last_event.version + 1) if last_event else 1

            # Speichere Event
            event_store = EventStore(
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                version=version,
                event_type=event.event_type,
                event_data=event.data,
                metadata=event.metadata,
                user_id=event.user_id,
                timestamp=event.timestamp,
                previous_hash=last_event.current_hash if last_event else None,
                current_hash=self._compute_event_hash(event, version),
            )
            session.add(event_store)
            await session.commit()
            event.version = version

    def _compute_event_hash(self, event: Event, version: int) -> str:
        """Berechnet Event-Hash für Merkle-Tree"""
        import hashlib

        data = f"{event.aggregate_id}|{version}|{event.event_type}|{json.dumps(event.data)}|{event.timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()

    async def _process_event_with_retry(self, event: Event, retry_count: int = 0):
        """Event mit Retry-Logik verarbeiten"""
        max_retries = 3
        base_delay = 2  # Sekunden

        try:
            # Circuit Breaker prüfen
            cb_key = f"cb:{event.event_type}"
            if cb_key in self.circuit_breakers:
                if not self.circuit_breakers[cb_key].allow_request():
                    logger.warning(f"Circuit breaker open for {event.event_type}, event queued")
                    await self.redis.lpush(
                        f"cb_queue:{event.event_type}", json.dumps(asdict(event))
                    )
                    return

            handlers = self.handlers.get(event.event_type, [])
            if not handlers:
                logger.warning(f"No handlers for event: {event.event_type}")
                return

            for handler in handlers:
                await handler(event)

            # Erfolg: Event aus Outbox entfernen
            # In Production: Mark as processed in DB

            # Circuit Breaker Erfolg melden
            if cb_key in self.circuit_breakers:
                self.circuit_breakers[cb_key].record_success()

        except Exception as e:
            logger.error(f"Error processing event {event.event_type}: {e}", exc_info=True)

            # Circuit Breaker Fehler melden
            if cb_key in self.circuit_breakers:
                self.circuit_breakers[cb_key].record_failure()

            if retry_count < max_retries:
                # Exponential Backoff
                delay = base_delay**retry_count
                logger.info(
                    f"Retrying event {event.event_type} in {delay}s (attempt {retry_count + 1}/{max_retries})"
                )
                await asyncio.sleep(delay)
                await self._process_event_with_retry(event, retry_count + 1)
            else:
                # Dead Letter Queue
                await self.redis.lpush(
                    f"dead_letter:{event.event_type}",
                    json.dumps(
                        {
                            "event": asdict(event),
                            "error": str(e),
                            "timestamp": datetime.utcnow().isoformat(),
                            "retry_count": retry_count,
                        }
                    ),
                )
                logger.error(
                    f"Event {event.event_type} moved to dead letter queue after {retry_count} retries"
                )

    async def replay_events(self, aggregate_id: UUID):
        """Events für einen Aggregate replays (CQRS Read Model Rebuild)"""
        async with self.session_factory() as session:
            stmt = (
                select(EventStore)
                .where(EventStore.aggregate_id == aggregate_id)
                .order_by(EventStore.version)
            )
            result = await session.execute(stmt)
            events = result.scalars().all()

            for event_store in events:
                # Recreate Event object
                event = Event(
                    aggregate_id=event_store.aggregate_id,
                    aggregate_type=event_store.aggregate_type,
                    event_type=event_store.event_type,
                    data=event_store.event_data,
                    user_id=event_store.user_id,
                    metadata=event_store.metadata,
                    timestamp=event_store.timestamp,
                    version=event_store.version,
                )
                # Process without storing again
                await self._process_event_with_retry(event)

    async def replay_all_for_read_model(self, read_model_name: str):
        """Kompletten Read Model Rebuild aus Event Store"""
        logger.info(f"Rebuilding read model: {read_model_name}")
        async with self.session_factory() as session:
            # Lade alle Events in Batches
            batch_size = 1000
            offset = 0
            while True:
                stmt = select(EventStore).order_by(EventStore.id).offset(offset).limit(batch_size)
                result = await session.execute(stmt)
                events = result.scalars().all()
                if not events:
                    break

                for event_store in events:
                    event = Event(
                        aggregate_id=event_store.aggregate_id,
                        aggregate_type=event_store.aggregate_type,
                        event_type=event_store.event_type,
                        data=event_store.event_data,
                        user_id=event_store.user_id,
                        metadata=event_store.metadata,
                        timestamp=event_store.timestamp,
                        version=event_store.version,
                    )
                    await self._process_event_with_retry(event)

                offset += batch_size
                logger.info(f"Replayed {offset} events for {read_model_name}")

        logger.info(f"Read model {read_model_name} rebuild complete")


class CircuitBreaker:
    """
    Circuit Breaker Pattern für externe Services
    Verhindert Cascade Failures
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.half_open_max_calls = half_open_max_calls

        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_failure_time = None
        self.half_open_calls = 0

    def allow_request(self) -> bool:
        """Prüft ob Request erlaubt ist"""
        if self.state == "CLOSED":
            return True
        elif self.state == "OPEN":
            # Prüfe ob Timeout abgelaufen
            if (
                self.last_failure_time
                and (datetime.utcnow() - self.last_failure_time).seconds > self.timeout_seconds
            ):
                self.state = "HALF_OPEN"
                self.half_open_calls = 0
                return True
            return False
        elif self.state == "HALF_OPEN":
            # Nur begrenzte Anzahl Calls in HALF_OPEN
            if self.half_open_calls < self.half_open_max_calls:
                self.half_open_calls += 1
                return True
            return False
        return False

    def record_success(self):
        """Erfolgreicher Call"""
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.failure_count = 0
            self.half_open_calls = 0
            logger.info(f"Circuit breaker {self.name} closed after success")

    def record_failure(self):
        """Fehlgeschlagener Call"""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

        if self.state == "CLOSED" and self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(
                f"Circuit breaker {self.name} opened after {self.failure_count} failures"
            )
        elif self.state == "HALF_OPEN":
            self.state = "OPEN"
            logger.warning(f"Circuit breaker {self.name} reopened after half-open failure")


# ==================== EVENT HANDLER (Celery Tasks) ====================


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def handle_donation_created(self, event_data: dict):
    """
    Handler für DonationCreated Event
    Tasks:
    1. SKR42 Buchung erstellen
    2. Zuwendungsbescheinigung generieren
    3. Audit-Log schreiben
    4. Projekt-KPI aktualisieren
    """
    try:
        from src.services.accounting import create_skr42_booking
        from src.services.audit import log_audit
        from src.services.pdf_generator import generate_donation_receipt

        donation_id = event_data.get("aggregate_id")
        amount = event_data.get("data", {}).get("amount")
        project_id = event_data.get("data", {}).get("project_id")

        # 1. SKR42 Buchung
        create_skr42_booking(donation_id, amount, project_id)

        # 2. Zuwendungsbescheinigung
        generate_donation_receipt(donation_id)

        # 3. Audit-Log
        log_audit(
            action="DONATION_CREATED",
            entity_type="donation",
            entity_id=donation_id,
            user_id=event_data.get("user_id"),
            new_values={"amount": amount, "project_id": project_id},
        )

        # 4. Projekt-KPI aktualisieren
        update_project_kpi.delay(project_id)

        logger.info(f"Donation {donation_id} processed successfully")

    except Exception as e:
        logger.error(f"Failed to process donation: {e}")
        self.retry(exc=e, countdown=60 * self.request.retries)


@celery_app.task
def update_project_kpi(project_id: UUID):
    """Projekt-KPIs neu berechnen (CQRS Read Model)"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.core.entities.base import Donation, Project

    engine = create_engine("postgresql://admin:password@postgres:5432/trueangels")
    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Summiere alle Spenden für Projekt
        total = (
            session.query(Donation)
            .filter(Donation.project_id == project_id, Donation.payment_status == "succeeded")
            .with_entities(func.sum(Donation.amount))
            .scalar()
            or 0
        )

        # Aktualisiere Projekt
        project = session.query(Project).filter(Project.id == project_id).first()
        if project:
            project.donations_total = total
            session.commit()
            logger.info(f"Updated KPI for project {project_id}: total={total}")


@celery_app.task
def send_donation_confirmation_email(donor_email: str, amount: Decimal, project_name: str):
    """Sende Bestätigungsemail an Spender (DSGVO-konform)"""
    # Implementierung mit SendGrid, AWS SES, etc.
    pass


@celery_app.task
def check_money_laundering(amount: Decimal, donor_email: str):
    """Prüfe auf Geldwäsche-Verdacht (>10.000€)"""
    if amount > 10000:
        # Benachrichtige Compliance Officer
        # Erstelle Verdachtsmeldung
        pass
