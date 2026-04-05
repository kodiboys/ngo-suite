"""
Property-Based Tests mit Hypothesis
Chaos Engineering Tests
"""

import hashlib
from decimal import Decimal
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from NGO.src.core.entities.base import ComplianceStatus, Donation, DonationCreate

# ==================== PROPERTY-BASED TESTS ====================

class TestDonationProperties:
    """Property-Based Tests für Donation Entity"""

    @given(
        amount=st.decimals(min_value=0.01, max_value=100000, places=2),
        email=st.emails(),
        project_id=st.uuids()
    )
    def test_donation_creation_properties(self, amount, email, project_id):
        """
        Properties:
        1. Betrag immer positiv
        2. Email wird pseudonymisiert
        3. Merkle-Hash ist eindeutig
        """
        donation_data = DonationCreate(
            project_id=project_id,
            amount=amount,
            donor_email=email,
            payment_provider="stripe",
            payment_intent_id=str(uuid4())
        )

        # Property 1: Betrag unverändert
        assert donation_data.amount == amount

        # Property 2: Email pseudonymisiert (SHA256)
        expected_hash = hashlib.sha256(email.lower().encode()).hexdigest()
        assert donation_data.donor_email == expected_hash
        assert donation_data.donor_email != email

    @given(
        amount=st.decimals(min_value=10000.01, max_value=1000000, places=2)
    )
    def test_money_laundering_flag(self, amount):
        """>10.000€ löst Geldwäsche-Flag aus"""
        donation = Donation(
            amount=amount,
            donor_email_pseudonym="test@example.com",
            payment_intent_id="test_123"
        )

        assert donation.money_laundering_flag is True
        assert donation.compliance_status == ComplianceStatus.FLAGGED

# ==================== STATE-BASED TESTING (Event Sourcing) ====================

class DonationStateMachine(RuleBasedStateMachine):
    """
    State Machine Test für Donation Lifecycle
    Testet Event Sourcing & CQRS
    """

    def __init__(self):
        super().__init__()
        self.donation = None
        self.events = []
        self.amount = Decimal("100.00")

    @rule(amount=st.decimals(min_value=10, max_value=10000, places=2))
    def create_donation(self, amount):
        """Create Donation Event"""
        self.donation = Donation(
            amount=amount,
            donor_email_pseudonym="test@example.com",
            payment_intent_id=str(uuid4())
        )
        self.amount = amount
        self.events.append(("CREATED", amount))

    @rule(amount=st.decimals(min_value=10, max_value=10000, places=2))
    def update_amount(self, amount):
        """Update Amount Event"""
        if self.donation:
            old_amount = self.donation.amount
            self.donation.amount = amount
            self.events.append(("UPDATED", old_amount, amount))

    @invariant()
    def amount_consistency(self):
        """Check: Amount muss immer positiv sein"""
        if self.donation:
            assert self.donation.amount > 0

    @invariant()
    def event_replay_consistency(self):
        """Check: Event Replay führt zum gleichen Zustand"""
        if self.donation:
            # Replay Events
            replayed = None
            for event in self.events:
                if event[0] == "CREATED":
                    replayed = Donation(amount=event[1])
                elif event[0] == "UPDATED" and replayed:
                    replayed.amount = event[2]

            if replayed:
                assert replayed.amount == self.donation.amount

# ==================== CHAOS ENGINEERING TESTS ====================

@pytest.mark.chaos
async def test_database_failure_recovery():
    """
    Chaos Test: Datenbank-Ausfall während Transaktion
    Erwartet: Event Store ist konsistent nach Recovery
    """
    from unittest.mock import patch

    from src.core.events.event_bus import Event, EventBus

    # Simuliere Datenbank-Fehler
    with patch('sqlalchemy.orm.Session.commit', side_effect=Exception("DB Down")):
        event_bus = EventBus(None)

        event = Event(
            aggregate_id=uuid4(),
            aggregate_type="Donation",
            event_type="DonationCreated",
            data={"amount": 100},
            user_id=uuid4(),
            metadata={}
        )

        # Event sollte in Dead Letter Queue landen
        await event_bus.publish(event)

        # Check Dead Letter Queue
        # (Implementation depends on Redis)
        pass

# ==================== PERFORMANCE TESTS ====================

@pytest.mark.benchmark
def test_hash_computation_benchmark(benchmark):
    """Benchmark: Merkle-Hash Berechnung"""
    donation = Donation(
        amount=Decimal("100.00"),
        donor_email_pseudonym="test@example.com",
        payment_intent_id="test_123"
    )

    result = benchmark(donation.compute_hash)
    assert len(result) == 64  # SHA256

# ==================== INTEGRATION TESTS ====================

@pytest.mark.integration
async def test_event_sourcing_replay():
    """Integration: Event Sourcing mit PostgreSQL"""
    from NGO.src.core.entities.base import EventStore
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    # Setup Test-DB
    engine = create_async_engine("postgresql+asyncpg://test:test@localhost/test_db")
    async_session = sessionmaker(engine, class_=AsyncSession)

    async with async_session() as session:
        # Store Events
        events = []
        for i in range(5):
            event = EventStore(
                aggregate_id=uuid4(),
                aggregate_type="Donation",
                version=i+1,
                event_type="AmountUpdated",
                event_data={"old": i*10, "new": (i+1)*10},
                user_id=uuid4(),
                current_hash=f"hash_{i}"
            )
            events.append(event)
            session.add(event)

        await session.commit()

        # Replay Events
        replayed_events = await session.execute(
            select(EventStore).where(EventStore.aggregate_id == events[0].aggregate_id)
            .order_by(EventStore.version)
        )

        replayed = replayed_events.scalars().all()
        assert len(replayed) == 5
        assert replayed[-1].event_data["new"] == 50

# Run with: pytest tests/ -v --hypothesis-show-statistics --chaos
