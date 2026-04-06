# FILE: tests/test_integration/test_event_sourcing.py
# MODULE: Integration Tests für Event Sourcing
# Testet Event Store, Replay, Snapshots

from uuid import uuid4

import pytest

from src.core.events.event_bus import Event, EventBus
from src.core.events.event_store import EventStoreService


class TestEventStore:
    """Tests für Event Store"""

    @pytest.mark.asyncio
    async def test_append_event(self, db_session):
        """Test Event Append"""
        store = EventStoreService(db_session)
        aggregate_id = uuid4()

        event = await store.append_event(
            aggregate_id=aggregate_id,
            aggregate_type="Donation",
            event_type="donation.created",
            data={"amount": 100, "currency": "EUR"},
            user_id=uuid4(),
        )

        assert event.event_id is not None
        assert event.sequence_number == 1
        assert event.current_hash is not None

    @pytest.mark.asyncio
    async def test_get_events_for_aggregate(self, db_session):
        """Test Abrufen von Events für Aggregate"""
        store = EventStoreService(db_session)
        aggregate_id = uuid4()

        # Append multiple events
        for i in range(3):
            await store.append_event(
                aggregate_id=aggregate_id,
                aggregate_type="Donation",
                event_type=f"donation.event_{i}",
                data={"sequence": i},
                user_id=uuid4(),
            )

        events = await store.get_events_for_aggregate(aggregate_id)

        assert len(events) == 3
        assert events[0].sequence_number == 1
        assert events[2].sequence_number == 3

    @pytest.mark.asyncio
    async def test_optimistic_locking(self, db_session):
        """Test Optimistic Locking"""
        store = EventStoreService(db_session)
        aggregate_id = uuid4()

        # First event
        await store.append_event(
            aggregate_id=aggregate_id,
            aggregate_type="Donation",
            event_type="donation.created",
            data={"version": 1},
            user_id=uuid4(),
        )

        # Try to append with wrong expected version
        with pytest.raises(Exception) as exc_info:
            await store.append_event(
                aggregate_id=aggregate_id,
                aggregate_type="Donation",
                event_type="donation.updated",
                data={"version": 2},
                user_id=uuid4(),
                expected_version=1,  # Should be 1, but we already have 1 event
            )

        # Actually 1 event means next sequence is 2, so expected_version should be 1
        # Let's fix the test
        event = await store.append_event(
            aggregate_id=aggregate_id,
            aggregate_type="Donation",
            event_type="donation.updated",
            data={"version": 2},
            user_id=uuid4(),
            expected_version=1,
        )

        assert event.sequence_number == 2

    @pytest.mark.asyncio
    async def test_verify_integrity(self, db_session):
        """Test Event-Ketten-Integrität"""
        store = EventStoreService(db_session)
        aggregate_id = uuid4()

        # Append events
        for i in range(3):
            await store.append_event(
                aggregate_id=aggregate_id,
                aggregate_type="Donation",
                event_type="donation.event",
                data={"value": i},
                user_id=uuid4(),
            )

        is_valid = await store.verify_integrity(aggregate_id)
        assert is_valid is True


class TestEventBus:
    """Tests für Event Bus"""

    @pytest.mark.asyncio
    async def test_publish_event(self, redis_client, db_session):
        """Test Event Publishing"""
        bus = EventBus(redis_client, db_session)

        received_events = []

        async def test_handler(event):
            received_events.append(event)

        bus.subscribe("test.event", test_handler)

        event = Event(
            aggregate_id=uuid4(),
            aggregate_type="Test",
            event_type="test.event",
            data={"message": "Hello"},
            user_id=uuid4(),
            metadata={},
        )

        await bus.publish(event, store_in_db=False)

        # Give handler time to execute
        import asyncio

        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        assert received_events[0].event_type == "test.event"
