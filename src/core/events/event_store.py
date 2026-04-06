# FILE: src/core/events/event_store.py
# MODULE: Event Store Core Implementation (Greg Young Pattern)
# Unveränderliches Event-Sourcing mit Snapshots, Optimistic Locking, Event Versioning

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from src.core.entities.base import Base

logger = logging.getLogger(__name__)

# ==================== Event Types ====================


class EventType(str, Enum):
    """Standard Event Types für das System"""

    # Donation Events
    DONATION_CREATED = "donation.created"
    DONATION_UPDATED = "donation.updated"
    DONATION_CONFIRMED = "donation.confirmed"
    DONATION_REFUNDED = "donation.refunded"
    DONATION_PSEUDONYMIZED = "donation.pseudonymized"

    # Project Events
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_COMPLETED = "project.completed"
    PROJECT_BUDGET_ADJUSTED = "project.budget.adjusted"

    # Payment Events
    PAYMENT_INTENT_CREATED = "payment.intent.created"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"

    # Inventory Events
    ITEM_CREATED = "inventory.item.created"
    STOCK_UPDATED = "inventory.stock.updated"
    STOCK_RESERVED = "inventory.stock.reserved"
    PACKING_LIST_CREATED = "packing.list.created"
    PACKING_LIST_CONFIRMED = "packing.list.confirmed"

    # User Events
    USER_REGISTERED = "user.registered"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    USER_PSEUDONYMIZED = "user.pseudonymized"

    # Compliance Events
    FOUR_EYES_REQUESTED = "compliance.four_eyes.requested"
    FOUR_EYES_APPROVED = "compliance.four_eyes.approved"
    ML_CHECK_PERFORMED = "compliance.ml.check_performed"
    ML_REPORTED = "compliance.ml.reported"


class EventVersion(str, Enum):
    """Event Versionierung für Schema-Evolution"""

    V1 = "1.0"
    V2 = "2.0"
    V3 = "3.0"


# ==================== Event Models ====================


@dataclass
class DomainEvent:
    """Base Domain Event für Event Sourcing"""

    event_id: UUID
    aggregate_id: UUID
    aggregate_type: str
    event_type: str
    event_version: str
    data: dict[str, Any]
    metadata: dict[str, Any]
    user_id: UUID | None
    timestamp: datetime
    sequence_number: int
    previous_hash: str | None = None
    current_hash: str | None = None

    def compute_hash(self) -> str:
        """Berechnet Event-Hash für Merkle-Tree"""
        content = f"{self.event_id}|{self.aggregate_id}|{self.sequence_number}|{self.event_type}|{json.dumps(self.data, sort_keys=True)}|{self.timestamp.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class Snapshot:
    """Snapshot für schnelle Wiederherstellung von Aggregaten"""

    aggregate_id: UUID
    aggregate_type: str
    version: int
    state: dict[str, Any]
    timestamp: datetime
    last_event_id: UUID


# ==================== SQLAlchemy Models ====================


class EventStoreDB(Base):
    """Event Store Tabelle - unveränderlich"""

    __tablename__ = "event_store"
    __table_args__ = (
        Index("idx_event_aggregate", "aggregate_id", "sequence_number"),
        Index("idx_event_type_time", "event_type", "timestamp"),
        Index("idx_event_hash", "current_hash"),
        UniqueConstraint("aggregate_id", "sequence_number", name="uq_event_sequence"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_id = Column(PGUUID(as_uuid=True), nullable=False, unique=True)
    aggregate_id = Column(PGUUID(as_uuid=True), nullable=False)
    aggregate_type = Column(String(100), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_version = Column(String(20), nullable=False, default="1.0")
    sequence_number = Column(Integer, nullable=False)

    # Event Data
    data = Column(JSONB, nullable=False)
    metadata = Column(JSONB, default={})

    # Audit
    user_id = Column(PGUUID(as_uuid=True), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Merkle Tree (Manipulationssicherheit)
    previous_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=False)

    def to_domain_event(self) -> DomainEvent:
        """Konvertiert DB-Modell zu Domain-Event"""
        return DomainEvent(
            event_id=self.event_id,
            aggregate_id=self.aggregate_id,
            aggregate_type=self.aggregate_type,
            event_type=self.event_type,
            event_version=self.event_version,
            data=self.data,
            metadata=self.metadata,
            user_id=self.user_id,
            timestamp=self.timestamp,
            sequence_number=self.sequence_number,
            previous_hash=self.previous_hash,
            current_hash=self.current_hash,
        )


class SnapshotStoreDB(Base):
    """Snapshot Store für Performance-Optimierung"""

    __tablename__ = "snapshot_store"
    __table_args__ = (Index("idx_snapshot_aggregate", "aggregate_id", "version"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    aggregate_id = Column(PGUUID(as_uuid=True), nullable=False, unique=True)
    aggregate_type = Column(String(100), nullable=False)
    version = Column(Integer, nullable=False)
    state = Column(JSONB, nullable=False)
    last_event_id = Column(PGUUID(as_uuid=True), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Komprimierung
    is_compressed = Column(Boolean, default=False)
    compressed_size = Column(Integer, nullable=True)


class EventSubscriptionDB(Base):
    """Event Subscriptions für CQRS Read Models"""

    __tablename__ = "event_subscriptions"
    __table_args__ = (Index("idx_subscription_name", "subscription_name", "last_processed_event"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    subscription_name = Column(String(100), nullable=False, unique=True)
    last_processed_event_id = Column(BigInteger, nullable=True)
    last_processed_event_position = Column(Integer, nullable=True)
    status = Column(String(20), default="active")  # active, paused, failed
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==================== Event Store Service ====================


class EventStoreService:
    """
    Event Store Service mit:
    - Append-Only Event Storage
    - Optimistic Locking für Concurrency
    - Snapshots für Performance
    - Event Replay für Read Models
    - Merkle Tree für Manipulationssicherheit
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def append_event(
        self,
        aggregate_id: UUID,
        aggregate_type: str,
        event_type: str,
        data: dict[str, Any],
        user_id: UUID | None,
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> DomainEvent:
        """
        Fügt ein neues Event zum Event Store hinzu
        Mit Optimistic Locking (expected_version) für Concurrency Control
        """
        async with self.session_factory() as session:
            # Lade aktuellste Sequence Number
            stmt = select(func.max(EventStoreDB.sequence_number)).where(
                EventStoreDB.aggregate_id == aggregate_id
            )
            result = await session.execute(stmt)
            current_max = result.scalar() or 0

            # Optimistic Locking Check
            if expected_version is not None and current_max != expected_version:
                raise ConcurrencyException(
                    f"Expected version {expected_version} but current is {current_max}"
                )

            # Hole letzten Event für Hash-Kette
            last_event = None
            if current_max > 0:
                stmt = select(EventStoreDB).where(
                    EventStoreDB.aggregate_id == aggregate_id,
                    EventStoreDB.sequence_number == current_max,
                )
                result = await session.execute(stmt)
                last_event = result.scalar_one_or_none()

            # Erstelle neues Event
            new_sequence = current_max + 1
            event = EventStoreDB(
                event_id=uuid4(),
                aggregate_id=aggregate_id,
                aggregate_type=aggregate_type,
                event_type=event_type,
                event_version=EventVersion.V1.value,
                sequence_number=new_sequence,
                data=data,
                metadata=metadata or {},
                user_id=user_id,
                previous_hash=last_event.current_hash if last_event else None,
                current_hash="",  # Wird nach Berechnung gesetzt
            )

            # Berechne Hash (mit vorherigem Hash)
            event.current_hash = self._compute_event_hash(event)

            session.add(event)
            await session.commit()
            await session.refresh(event)

            logger.debug(
                f"Event appended: {event_type} for {aggregate_type}/{aggregate_id} (seq={new_sequence})"
            )

            return event.to_domain_event()

    async def get_events_for_aggregate(
        self, aggregate_id: UUID, from_version: int = 1, to_version: int | None = None
    ) -> list[DomainEvent]:
        """Holt alle Events für ein Aggregate (für Replay)"""
        async with self.session_factory() as session:
            stmt = (
                select(EventStoreDB)
                .where(
                    EventStoreDB.aggregate_id == aggregate_id,
                    EventStoreDB.sequence_number >= from_version,
                )
                .order_by(EventStoreDB.sequence_number)
            )

            if to_version:
                stmt = stmt.where(EventStoreDB.sequence_number <= to_version)

            result = await session.execute(stmt)
            events = result.scalars().all()

            return [e.to_domain_event() for e in events]

    async def get_events_by_type(
        self,
        event_type: str,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
        limit: int = 1000,
    ) -> list[DomainEvent]:
        """Holt Events nach Typ (für Read Model Rebuilds)"""
        async with self.session_factory() as session:
            stmt = (
                select(EventStoreDB)
                .where(EventStoreDB.event_type == event_type)
                .order_by(EventStoreDB.timestamp)
                .limit(limit)
            )

            if from_timestamp:
                stmt = stmt.where(EventStoreDB.timestamp >= from_timestamp)
            if to_timestamp:
                stmt = stmt.where(EventStoreDB.timestamp <= to_timestamp)

            result = await session.execute(stmt)
            events = result.scalars().all()

            return [e.to_domain_event() for e in events]

    async def get_all_events(
        self, from_position: int = 0, batch_size: int = 1000
    ) -> list[DomainEvent]:
        """Holt alle Events ab einer Position (für globale Subscriptions)"""
        async with self.session_factory() as session:
            stmt = (
                select(EventStoreDB)
                .where(EventStoreDB.id > from_position)
                .order_by(EventStoreDB.id)
                .limit(batch_size)
            )

            result = await session.execute(stmt)
            events = result.scalars().all()

            return [e.to_domain_event() for e in events]

    async def create_snapshot(
        self,
        aggregate_id: UUID,
        aggregate_type: str,
        version: int,
        state: dict[str, Any],
        last_event_id: UUID,
    ) -> Snapshot:
        """Erstellt einen Snapshot für schnelle Wiederherstellung"""
        async with self.session_factory() as session:
            # Lösche alten Snapshot
            stmt = delete(SnapshotStoreDB).where(SnapshotStoreDB.aggregate_id == aggregate_id)
            await session.execute(stmt)

            # Erstelle neuen Snapshot
            snapshot = SnapshotStoreDB(
                aggregate_id=aggregate_id,
                aggregate_type=aggregate_type,
                version=version,
                state=state,
                last_event_id=last_event_id,
            )

            session.add(snapshot)
            await session.commit()

            logger.info(
                f"Snapshot created for {aggregate_type}/{aggregate_id} at version {version}"
            )

            return Snapshot(
                aggregate_id=snapshot.aggregate_id,
                aggregate_type=snapshot.aggregate_type,
                version=snapshot.version,
                state=snapshot.state,
                timestamp=snapshot.timestamp,
                last_event_id=snapshot.last_event_id,
            )

    async def get_snapshot(self, aggregate_id: UUID) -> Snapshot | None:
        """Holt den aktuellsten Snapshot für ein Aggregate"""
        async with self.session_factory() as session:
            stmt = select(SnapshotStoreDB).where(SnapshotStoreDB.aggregate_id == aggregate_id)
            result = await session.execute(stmt)
            snapshot = result.scalar_one_or_none()

            if snapshot:
                return Snapshot(
                    aggregate_id=snapshot.aggregate_id,
                    aggregate_type=snapshot.aggregate_type,
                    version=snapshot.version,
                    state=snapshot.state,
                    timestamp=snapshot.timestamp,
                    last_event_id=snapshot.last_event_id,
                )
            return None

    async def replay_aggregate(self, aggregate_id: UUID, aggregate_type: str, event_handler) -> Any:
        """
        Replayt alle Events für ein Aggregate und baut Zustand auf
        """
        # Versuche Snapshot zu laden
        snapshot = await self.get_snapshot(aggregate_id)

        if snapshot:
            # Starte mit Snapshot
            state = snapshot.state
            start_version = snapshot.version + 1
            logger.debug(f"Using snapshot for {aggregate_id} at version {snapshot.version}")
        else:
            # Starte von Anfang
            state = {}
            start_version = 1

        # Lade Events ab Snapshot-Version
        events = await self.get_events_for_aggregate(aggregate_id, start_version)

        # Replay Events
        for event in events:
            state = await event_handler(event, state)

        return state

    def _compute_event_hash(self, event: EventStoreDB) -> str:
        """Berechnet Event-Hash für Merkle-Tree"""
        content = f"{event.event_id}|{event.aggregate_id}|{event.sequence_number}|{event.event_type}|{json.dumps(event.data, sort_keys=True)}|{event.timestamp.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def verify_integrity(self, aggregate_id: UUID) -> bool:
        """
        Verifiziert die Integrität der Event-Kette (Merkle-Tree)
        Prüft ob alle Hashes korrekt sind
        """
        events = await self.get_events_for_aggregate(aggregate_id)

        previous_hash = None
        for event in events:
            # Recompute hash
            computed_hash = self._compute_event_hash_from_domain(event)

            if event.current_hash != computed_hash:
                logger.error(f"Hash mismatch for event {event.event_id}")
                return False

            if previous_hash and event.previous_hash != previous_hash:
                logger.error(f"Chain broken at event {event.event_id}")
                return False

            previous_hash = event.current_hash

        return True

    def _compute_event_hash_from_domain(self, event: DomainEvent) -> str:
        """Berechnet Hash aus Domain-Event"""
        content = f"{event.event_id}|{event.aggregate_id}|{event.sequence_number}|{event.event_type}|{json.dumps(event.data, sort_keys=True)}|{event.timestamp.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()


# ==================== Event Subscription Service ====================


class EventSubscriptionService:
    """
    Event Subscription Service für CQRS Read Models
    Verfolgt Verarbeitungsfortschritt von Read Models
    """

    def __init__(self, session_factory, event_store: EventStoreService):
        self.session_factory = session_factory
        self.event_store = event_store
        self._handlers = {}  # subscription_name -> handler function

    def subscribe(self, subscription_name: str, handler):
        """Registriert einen Event-Handler für eine Subscription"""
        self._handlers[subscription_name] = handler
        logger.info(f"Subscription registered: {subscription_name}")

    async def process_events(self, subscription_name: str, batch_size: int = 100):
        """
        Verarbeitet neue Events für eine Subscription
        Wird typischerweise von einem Background Worker aufgerufen
        """
        async with self.session_factory() as session:
            # Lade Subscription Status
            stmt = select(EventSubscriptionDB).where(
                EventSubscriptionDB.subscription_name == subscription_name
            )
            result = await session.execute(stmt)
            subscription = result.scalar_one_or_none()

            if not subscription:
                subscription = EventSubscriptionDB(
                    subscription_name=subscription_name, status="active"
                )
                session.add(subscription)
                await session.commit()

            last_position = subscription.last_processed_event_id or 0

            # Lade neue Events
            events = await self.event_store.get_all_events(
                from_position=last_position, batch_size=batch_size
            )

            if not events:
                return 0

            handler = self._handlers.get(subscription_name)
            if not handler:
                logger.error(f"No handler for subscription: {subscription_name}")
                return 0

            # Verarbeite Events
            processed = 0
            for event in events:
                try:
                    await handler(event)
                    last_position = event.id
                    processed += 1
                except Exception as e:
                    logger.error(f"Error processing event {event.event_id}: {e}")
                    subscription.status = "failed"
                    subscription.error_message = str(e)
                    subscription.retry_count += 1
                    await session.commit()
                    raise

            # Update Subscription Status
            subscription.last_processed_event_id = events[-1].id
            subscription.last_processed_event_position = events[-1].sequence_number
            subscription.status = "active"
            subscription.error_message = None
            subscription.updated_at = datetime.utcnow()

            await session.commit()

            logger.info(f"Processed {processed} events for subscription {subscription_name}")
            return processed

    async def rebuild_read_model(self, subscription_name: str):
        """
        Rebuildt ein Read Model komplett neu (für Schema-Änderungen)
        """
        logger.info(f"Rebuilding read model for subscription: {subscription_name}")

        # Setze Subscription zurück
        async with self.session_factory() as session:
            stmt = (
                update(EventSubscriptionDB)
                .where(EventSubscriptionDB.subscription_name == subscription_name)
                .values(
                    last_processed_event_id=None,
                    last_processed_event_position=None,
                    status="rebuilding",
                )
            )
            await session.execute(stmt)
            await session.commit()

        # Lösche Read Model Tabelle (implementierungsspezifisch)
        # await self._clear_read_model(subscription_name)

        # Verarbeite alle Events von Anfang an
        while True:
            processed = await self.process_events(subscription_name, batch_size=1000)
            if processed == 0:
                break

        logger.info(f"Read model rebuild complete for {subscription_name}")


# ==================== Aggregate Base Class ====================


class AggregateRoot:
    """
    Base Class für Event-sourced Aggregates
    Verwendet Event Sourcing für Zustandsänderungen
    """

    def __init__(self, event_store: EventStoreService):
        self.event_store = event_store
        self.id: UUID | None = None
        self.version: int = 0
        self._changes: list[DomainEvent] = []
        self._loaded_events: list[DomainEvent] = []

    async def load_from_history(self, aggregate_id: UUID):
        """Lädt Aggregate aus Event-History"""
        self.id = aggregate_id

        # Versuche Snapshot
        snapshot = await self.event_store.get_snapshot(aggregate_id)

        if snapshot:
            self.version = snapshot.version
            self._apply_snapshot(snapshot.state)
            start_version = snapshot.version + 1
        else:
            start_version = 1

        # Lade Events
        events = await self.event_store.get_events_for_aggregate(aggregate_id, start_version)

        for event in events:
            self._apply_event(event)
            self._loaded_events.append(event)
            self.version = event.sequence_number

    def add_event(self, event_type: str, data: dict[str, Any], metadata: dict | None = None):
        """Fügt ein neues Event hinzu (wird noch nicht gespeichert)"""
        event = DomainEvent(
            event_id=uuid4(),
            aggregate_id=self.id,
            aggregate_type=self.__class__.__name__,
            event_type=event_type,
            event_version=EventVersion.V1.value,
            data=data,
            metadata=metadata or {},
            user_id=None,  # Wird später gesetzt
            timestamp=datetime.utcnow(),
            sequence_number=self.version + 1,
        )

        self._apply_event(event)
        self._changes.append(event)

    async def save(self, user_id: UUID | None = None):
        """Speichert alle neuen Events im Event Store"""
        for event in self._changes:
            event.user_id = user_id
            await self.event_store.append_event(
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                event_type=event.event_type,
                data=event.data,
                user_id=user_id,
                metadata=event.metadata,
                expected_version=self.version - len(self._changes) + event.sequence_number - 1,
            )
            self.version = event.sequence_number

        self._changes.clear()

    def _apply_event(self, event: DomainEvent):
        """Wendet ein Event auf das Aggregate an (muss von Subclass implementiert werden)"""
        handler_name = f"apply_{event.event_type.replace('.', '_')}"
        handler = getattr(self, handler_name, None)

        if handler:
            handler(event.data)
        else:
            logger.warning(f"No handler for event type: {event.event_type}")

    def _apply_snapshot(self, state: dict[str, Any]):
        """Stellt Zustand aus Snapshot wieder her (von Subclass zu implementieren)"""
        for key, value in state.items():
            setattr(self, key, value)


# ==================== Exceptions ====================


class ConcurrencyException(Exception):
    """Wird geworfen bei Optimistic Locking Konflikten"""

    pass


class EventStoreException(Exception):
    """Base Exception für Event Store Fehler"""

    pass
