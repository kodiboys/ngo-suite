# FILE: src/core/events/event_store.py
# MODULE: Event Store Core Implementation (Greg Young Pattern)
# Version: 3.0.2 (Fixed Index & Timezone Issues)

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from enum import Enum
from dataclasses import dataclass
import json
import hashlib
import logging

from sqlalchemy import (
    Column, String, DateTime, Integer, BigInteger, Index, Text, Boolean
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import relationship

from src.core.entities.base import Base

logger = logging.getLogger(__name__)


# ==================== Event Types ====================

class EventType(str, Enum):
    """Standard Event Types für das System"""
    DONATION_CREATED = "donation.created"
    DONATION_UPDATED = "donation.updated"
    DONATION_CONFIRMED = "donation.confirmed"
    DONATION_REFUNDED = "donation.refunded"
    DONATION_PSEUDONYMIZED = "donation.pseudonymized"

    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_COMPLETED = "project.completed"

    PAYMENT_INTENT_CREATED = "payment.intent.created"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"

    USER_REGISTERED = "user.registered"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"

    INVENTORY_ITEM_CREATED = "inventory.item.created"
    INVENTORY_STOCK_UPDATED = "inventory.stock.updated"


class EventVersion(str, Enum):
    """Event Versionierung für Schema-Evolution"""
    V1 = "1.0"
    V2 = "2.0"


# ==================== Event Models ====================

@dataclass
class DomainEvent:
    """Base Domain Event für Event Sourcing"""
    event_id: UUID
    aggregate_id: UUID
    aggregate_type: str
    event_type: str
    event_version: str
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    user_id: Optional[UUID]
    timestamp: datetime
    sequence_number: int
    previous_hash: Optional[str] = None
    current_hash: Optional[str] = None
    id: Optional[int] = None  # DB ID für Subscription Tracking

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
    state: Dict[str, Any]
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
	{"extend_existing": True},
    )
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_id = Column(PGUUID(as_uuid=True), nullable=False, unique=True)
    aggregate_id = Column(PGUUID(as_uuid=True), nullable=False)
    aggregate_type = Column(String(100), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_version = Column(String(20), nullable=False, default="1.0")
    sequence_number = Column(Integer, nullable=False)
    
    data = Column(JSONB, nullable=False)
    event_metadata = Column(JSONB, default=dict)
    
    user_id = Column(PGUUID(as_uuid=True), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    
    previous_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=False)
    
    def to_domain_event(self) -> DomainEvent:
        """Konvertiert DB-Modell zu Domain-Event"""
        return DomainEvent(
            id=self.id,
            event_id=self.event_id,
            aggregate_id=self.aggregate_id,
            aggregate_type=self.aggregate_type,
            event_type=self.event_type,
            event_version=self.event_version,
            data=self.data,
            metadata=self.event_metadata,
            user_id=self.user_id,
            timestamp=self.timestamp,
            sequence_number=self.sequence_number,
            previous_hash=self.previous_hash,
            current_hash=self.current_hash
        )


class SnapshotStoreDB(Base):
    """Snapshot Store für Performance-Optimierung"""
    __tablename__ = "snapshot_store"
    __table_args__ = (
        Index("idx_snapshot_aggregate", "aggregate_id", "version"),
    )
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    aggregate_id = Column(PGUUID(as_uuid=True), nullable=False, unique=True)
    aggregate_type = Column(String(100), nullable=False)
    version = Column(Integer, nullable=False)
    state = Column(JSONB, nullable=False)
    last_event_id = Column(PGUUID(as_uuid=True), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_compressed = Column(Boolean, default=False)


class EventSubscriptionDB(Base):
    """Event Subscriptions für CQRS Read Models"""
    __tablename__ = "event_subscriptions"
    __table_args__ = (
        # FIX: Spaltenname korrigiert von 'last_processed_event' zu 'last_processed_event_id'
        Index("idx_subscription_name", "subscription_name", "last_processed_event_id"),
        Index("idx_subscription_status", "status"),
    )
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    subscription_name = Column(String(100), nullable=False, unique=True)
    last_processed_event_id = Column(BigInteger, nullable=True)  # Database ID (BigInteger)
    last_processed_event_position = Column(Integer, nullable=True)
    status = Column(String(20), default="active")  # active, paused, failed
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), 
                       onupdate=lambda: datetime.now(timezone.utc))


# ==================== Event Store Service ====================

class EventStoreService:
    """Event Store Service mit Append-Only Storage und Optimistic Locking"""
    
    def __init__(self, session_factory):
        self.session_factory = session_factory
    
    async def append_event(
        self,
        aggregate_id: UUID,
        aggregate_type: str,
        event_type: str,
        data: Dict[str, Any],
        user_id: Optional[UUID],
        metadata: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None
    ) -> DomainEvent:
        """Fügt ein neues Event zum Event Store hinzu"""
        async with self.session_factory() as session:
            # Lade aktuellste Sequence Number
            stmt = select(func.max(EventStoreDB.sequence_number)).where(
                EventStoreDB.aggregate_id == aggregate_id
            )
            result = await session.execute(stmt)
            current_max = result.scalar() or 0
            
            # Optimistic Locking Check
            if expected_version is not None and current_max != expected_version:
                raise ConcurrencyError(
                    f"Expected version {expected_version} but current is {current_max}"
                )
            
            # Hole letzten Hash
            last_hash = None
            if current_max > 0:
                stmt = select(EventStoreDB.current_hash).where(
                    EventStoreDB.aggregate_id == aggregate_id,
                    EventStoreDB.sequence_number == current_max
                )
                result = await session.execute(stmt)
                last_hash = result.scalar()
            
            # Zeitstempel mit Timezone
            now = datetime.now(timezone.utc)
            
            # Erstelle Event
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
                timestamp=now,
                previous_hash=last_hash,
                current_hash=""  # Wird gleich berechnet
            )
            
            # Berechne Hash
            event.current_hash = self._compute_event_hash(event)
            
            session.add(event)
            await session.commit()
            await session.refresh(event)
            
            logger.debug(f"Event appended: {event_type} for {aggregate_type}/{aggregate_id}")
            
            return event.to_domain_event()
    
    async def get_events_for_aggregate(
        self,
        aggregate_id: UUID,
        from_version: int = 1
    ) -> List[DomainEvent]:
        """Holt alle Events für ein Aggregate"""
        async with self.session_factory() as session:
            stmt = select(EventStoreDB).where(
                EventStoreDB.aggregate_id == aggregate_id,
                EventStoreDB.sequence_number >= from_version
            ).order_by(EventStoreDB.sequence_number)
            
            result = await session.execute(stmt)
            return [e.to_domain_event() for e in result.scalars().all()]
    
    async def get_all_events(
        self,
        from_position: int = 0,
        batch_size: int = 1000
    ) -> List[DomainEvent]:
        """Holt alle Events ab einer Position"""
        async with self.session_factory() as session:
            stmt = select(EventStoreDB).where(
                EventStoreDB.id > from_position
            ).order_by(EventStoreDB.id).limit(batch_size)
            
            result = await session.execute(stmt)
            return [e.to_domain_event() for e in result.scalars().all()]
    
    async def create_snapshot(
        self,
        aggregate_id: UUID,
        aggregate_type: str,
        version: int,
        state: Dict[str, Any],
        last_event_id: UUID
    ):
        """Erstellt einen Snapshot"""
        async with self.session_factory() as session:
            await session.execute(
                delete(SnapshotStoreDB).where(
                    SnapshotStoreDB.aggregate_id == aggregate_id
                )
            )
            
            snapshot = SnapshotStoreDB(
                aggregate_id=aggregate_id,
                aggregate_type=aggregate_type,
                version=version,
                state=state,
                last_event_id=last_event_id
            )
            session.add(snapshot)
            await session.commit()
    
    async def get_snapshot(self, aggregate_id: UUID) -> Optional[Snapshot]:
        """Holt den aktuellsten Snapshot"""
        async with self.session_factory() as session:
            stmt = select(SnapshotStoreDB).where(
                SnapshotStoreDB.aggregate_id == aggregate_id
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            
            if row:
                return Snapshot(
                    aggregate_id=row.aggregate_id,
                    aggregate_type=row.aggregate_type,
                    version=row.version,
                    state=row.state,
                    timestamp=row.timestamp,
                    last_event_id=row.last_event_id
                )
            return None
    
    def _compute_event_hash(self, event: EventStoreDB) -> str:
        """Berechnet Event-Hash für Merkle-Tree"""
        content = f"{event.event_id}|{event.aggregate_id}|{event.sequence_number}|{event.event_type}|{json.dumps(event.data, sort_keys=True)}|{event.timestamp.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    async def verify_integrity(self, aggregate_id: UUID) -> bool:
        """Verifiziert die Integrität der Event-Kette"""
        events = await self.get_events_for_aggregate(aggregate_id)
        
        previous_hash = None
        for event in events:
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
    """Event Subscription Service für CQRS Read Models"""
    
    def __init__(self, session_factory, event_store: EventStoreService):
        self.session_factory = session_factory
        self.event_store = event_store
        self._handlers: Dict[str, callable] = {}
    
    def subscribe(self, subscription_name: str, handler):
        """Registriert einen Event-Handler"""
        self._handlers[subscription_name] = handler
        logger.info(f"Subscription registered: {subscription_name}")
    
    async def process_events(self, subscription_name: str, batch_size: int = 100):
        """Verarbeitet neue Events für eine Subscription"""
        async with self.session_factory() as session:
            # Lade Subscription
            stmt = select(EventSubscriptionDB).where(
                EventSubscriptionDB.subscription_name == subscription_name
            )
            result = await session.execute(stmt)
            subscription = result.scalar_one_or_none()
            
            if not subscription:
                subscription = EventSubscriptionDB(
                    subscription_name=subscription_name,
                    status="active"
                )
                session.add(subscription)
                await session.commit()
                await session.refresh(subscription)
            
            last_position = subscription.last_processed_event_id or 0
            
            # Lade Events
            events = await self.event_store.get_all_events(
                from_position=last_position,
                batch_size=batch_size
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
                    processed += 1
                except Exception as e:
                    logger.error(f"Error processing event {event.event_id}: {e}")
                    subscription.status = "failed"
                    subscription.error_message = str(e)
                    subscription.retry_count += 1
                    await session.commit()
                    raise
            
            # Update Status - FIX: Nutzt jetzt korrekt event.id (BigInteger)
            if events:
                subscription.last_processed_event_id = events[-1].id
                subscription.last_processed_event_position = events[-1].sequence_number
                subscription.status = "active"
                subscription.error_message = None
                subscription.updated_at = datetime.now(timezone.utc)
                await session.commit()
            
            logger.info(f"Processed {processed} events for {subscription_name}")
            return processed
    
    async def reset_subscription(self, subscription_name: str):
        """Setzt eine Subscription zurück (für Rebuilds)"""
        async with self.session_factory() as session:
            stmt = update(EventSubscriptionDB).where(
                EventSubscriptionDB.subscription_name == subscription_name
            ).values(
                last_processed_event_id=None,
                last_processed_event_position=None,
                status="rebuilding",
                error_message=None,
                retry_count=0
            )
            await session.execute(stmt)
            await session.commit()


# ==================== Exceptions ====================

class ConcurrencyError(Exception):
    """Wird geworfen bei Optimistic Locking Konflikten"""
    pass
