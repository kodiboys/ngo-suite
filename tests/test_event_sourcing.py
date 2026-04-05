# FILE: tests/test_event_sourcing.py
# MODULE: Event Sourcing Tests
# Unit, Integration & Property-Based Tests für Event Store

from datetime import datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from src.core.events.event_store import (
    ConcurrencyException,
    DomainEvent,
    EventStoreService,
    EventType,
)

# ==================== Unit Tests ====================

@pytest.mark.asyncio
async def test_event_append():
    """Test Event Append mit Optimistic Locking"""

    mock_session = AsyncMock()
    mock_execute = AsyncMock()
    mock_session.execute = mock_execute

    # Mock current max sequence
    mock_scalar = AsyncMock()
    mock_scalar.return_value = 0
    mock_execute.scalar = mock_scalar

    service = EventStoreService(mock_session)

    event = await service.append_event(
        aggregate_id=uuid4(),
        aggregate_type="Donation",
        event_type=EventType.DONATION_CREATED,
        data={"amount": 100},
        user_id=uuid4(),
        metadata={}
    )

    assert event.event_type == EventType.DONATION_CREATED
    assert event.sequence_number == 1
    assert event.current_hash is not None


@pytest.mark.asyncio
async def test_optimistic_locking():
    """Test Optimistic Locking Concurrency"""

    mock_session = AsyncMock()
    mock_execute = AsyncMock()
    mock_session.execute = mock_execute

    # Mock current max sequence = 5
    mock_scalar = AsyncMock()
    mock_scalar.return_value = 5
    mock_execute.scalar = mock_scalar

    service = EventStoreService(mock_session)

    with pytest.raises(ConcurrencyException):
        await service.append_event(
            aggregate_id=uuid4(),
            aggregate_type="Donation",
            event_type=EventType.DONATION_CREATED,
            data={"amount": 100},
            user_id=uuid4(),
            expected_version=3  # Erwartet Version 3, aber aktuell ist 5
        )


@pytest.mark.asyncio
async def test_event_replay():
    """Test Event Replay für Aggregate"""

    mock_session = AsyncMock()
    mock_execute = AsyncMock()

    # Mock Events
    events = [
        Mock(
            to_domain_event=lambda: DomainEvent(
                event_id=uuid4(),
                aggregate_id=uuid4(),
                aggregate_type="Donation",
                event_type=EventType.DONATION_CREATED,
                event_version="1.0",
                data={"amount": 100},
                metadata={},
                user_id=uuid4(),
                timestamp=datetime.utcnow(),
                sequence_number=1
            )
        )
    ]
    mock_scalars = AsyncMock()
    mock_scalars.all.return_value = events
    mock_execute.scalars.return_value = mock_scalars
    mock_session.execute = mock_execute

    service = EventStoreService(mock_session)

    async def event_handler(event, state):
        state["amount"] = event.data["amount"]
        return state

    state = await service.replay_aggregate(
        aggregate_id=uuid4(),
        aggregate_type="Donation",
        event_handler=event_handler
    )

    assert state["amount"] == 100


# ==================== Integration Tests ====================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_event_sourcing_flow(db_session):
    """Test vollständigen Event Sourcing Flow"""

    from src.core.events.event_store import EventStoreService

    event_store = EventStoreService(db_session)
    aggregate_id = uuid4()

    # 1. Append Events
    event1 = await event_store.append_event(
        aggregate_id=aggregate_id,
        aggregate_type="Donation",
        event_type=EventType.DONATION_CREATED,
        data={"amount": 100, "project_id": str(uuid4()), "donor_email": "test@example.com"},
        user_id=uuid4()
    )

    event2 = await event_store.append_event(
        aggregate_id=aggregate_id,
        aggregate_type="Donation",
        event_type=EventType.DONATION_CONFIRMED,
        data={"payment_intent_id": "pi_123"},
        user_id=uuid4(),
        expected_version=1
    )

    # 2. Get Events
    events = await event_store.get_events_for_aggregate(aggregate_id)

    assert len(events) == 2
    assert events[0].sequence_number == 1
    assert events[1].sequence_number == 2

    # 3. Verify Integrity
    is_valid = await event_store.verify_integrity(aggregate_id)
    assert is_valid is True


# ==================== Performance Tests ====================

@pytest.mark.benchmark
def test_event_serialization_benchmark(benchmark):
    """Benchmark: Event Serialisierung"""

    event = DomainEvent(
        event_id=uuid4(),
        aggregate_id=uuid4(),
        aggregate_type="Donation",
        event_type=EventType.DONATION_CREATED,
        event_version="1.0",
        data={"amount": 100, "project_id": str(uuid4()), "donor_email": "test@example.com"},
        metadata={"ip": "127.0.0.1", "user_agent": "test"},
        user_id=uuid4(),
        timestamp=datetime.utcnow(),
        sequence_number=1
    )

    def serialize():
        import json
        from dataclasses import asdict
        return json.dumps(asdict(event), default=str)

    result = benchmark(serialize)
    assert "donation.created" in result


# ==================== Property-Based Tests ====================

from hypothesis import given
from hypothesis import strategies as st


@given(
    amount=st.decimals(min_value=0.01, max_value=100000, places=2),
    sequence=st.integers(min_value=1, max_value=1000)
)
def test_event_hash_property(amount, sequence):
    """Test: Event Hash ist deterministisch und eindeutig"""

    event1 = DomainEvent(
        event_id=uuid4(),
        aggregate_id=uuid4(),
        aggregate_type="Donation",
        event_type=EventType.DONATION_CREATED,
        event_version="1.0",
        data={"amount": float(amount)},
        metadata={},
        user_id=uuid4(),
        timestamp=datetime.utcnow(),
        sequence_number=sequence
    )

    event2 = DomainEvent(
        event_id=event1.event_id,
        aggregate_id=event1.aggregate_id,
        aggregate_type=event1.aggregate_type,
        event_type=event1.event_type,
        event_version=event1.event_version,
        data=event1.data,
        metadata=event1.metadata,
        user_id=event1.user_id,
        timestamp=event1.timestamp,
        sequence_number=event1.sequence_number
    )

    # Gleiche Events -> Gleiche Hashes
    assert event1.compute_hash() == event2.compute_hash()

    # Unterschiedliche Sequence -> Unterschiedliche Hashes
    event3 = DomainEvent(
        **{**event1.__dict__, "sequence_number": sequence + 1}
    )
    assert event1.compute_hash() != event3.compute_hash()
