# FILE: tests/test_compliance.py
# MODULE: Compliance Tests
# Unit, Integration & Property-Based Tests für Compliance Engine

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from hypothesis import given
from hypothesis import strategies as st
import pytest

from src.core.compliance.base import (
    ApprovalStatus,
    FourEyesRequest,
    MoneyLaunderingCheck,
    MoneyLaunderingRisk,
)
from src.services.compliance_service import ComplianceService

# ==================== Unit Tests ====================


@pytest.mark.asyncio
async def test_four_eyes_approval_request():
    """Test 4-Augen-Freigabe Anforderung"""

    request = FourEyesRequest(
        entity_type="donation",
        entity_id=uuid4(),
        amount=Decimal("7500.00"),
        reason="Test donation",
        approver_1_id=uuid4(),
    )

    assert request.amount == Decimal("7500.00")
    assert request.entity_type == "donation"

    # Prüfe Schwellwert
    with pytest.raises(ValueError):
        FourEyesRequest(
            entity_type="donation",
            entity_id=uuid4(),
            amount=Decimal("1000.00"),  # Unter Schwellwert
            reason="Too low",
            approver_1_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_money_laundering_risk_calculation():
    """Test Geldwäsche-Risikoberechnung"""

    ml_check = MoneyLaunderingCheck(
        entity_type="donation",
        entity_id=uuid4(),
        amount=Decimal("15000.00"),
        donor_country="RU",
        payment_method="crypto",
    )

    risk_score = ml_check.calculate_risk_score()

    assert risk_score >= 60  # High risk
    assert ml_check.risk_level in [MoneyLaunderingRisk.HIGH, MoneyLaunderingRisk.CRITICAL]


@pytest.mark.asyncio
async def test_smurfing_detection():
    """Test Smurfing-Erkennung (Strukturierung)"""

    service = ComplianceService(None, None, None)

    # Simuliere mehrere kleine Transaktionen
    with patch("sqlalchemy.ext.asyncio.AsyncSession") as mock_session:
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [
            Mock(amount=Decimal("900.00")),
            Mock(amount=Decimal("950.00")),
            Mock(amount=Decimal("800.00")),
            Mock(amount=Decimal("850.00")),
            Mock(amount=Decimal("920.00")),
        ]
        mock_session.execute.return_value = mock_result

        smurfing = await service._check_smurfing(
            mock_session, "test@example.com", Decimal("1000.00")
        )

        assert smurfing is not None
        assert smurfing["transaction_count"] == 6
        assert smurfing["total_amount"] > 5000


# ==================== Integration Tests ====================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_compliance_flow(db_session, redis_client):
    """Test vollständigen Compliance-Workflow"""

    from src.core.events.event_bus import EventBus

    event_bus = EventBus(redis_client, db_session)
    service = ComplianceService(db_session, redis_client, event_bus)

    # 1. Geldwäscheprüfung
    ml_check = await service.check_money_laundering(
        entity_type="donation",
        entity_id=uuid4(),
        amount=Decimal("25000.00"),
        donor_name="Test Donor",
        donor_email="test@example.com",
        donor_country="DE",
        payment_method="credit_card",
        ip_address="127.0.0.1",
    )

    assert ml_check.id is not None
    assert ml_check.risk_score > 0

    # 2. 4-Augen-Freigabe anfordern
    approval_request = FourEyesRequest(
        entity_type="donation",
        entity_id=uuid4(),
        amount=Decimal("7500.00"),
        reason="Test approval",
        approver_1_id=uuid4(),
    )

    approval = await service.request_four_eyes_approval(
        request=approval_request, initiator_id=uuid4(), ip_address="127.0.0.1"
    )

    assert approval.status == ApprovalStatus.PENDING
    assert approval.expires_at > datetime.utcnow()

    # 3. Freigabe durch ersten Prüfer
    approved = await service.approve_transaction(
        approval_id=approval.id,
        approver_id=approval_request.approver_1_id,
        comment="Approved",
        ip_address="127.0.0.1",
    )

    assert approved.status == ApprovalStatus.APPROVED


# ==================== Property-Based Tests ====================


@given(
    amount=st.decimals(min_value=0.01, max_value=100000, places=2),
    country=st.sampled_from(["DE", "FR", "IT", "RU", "CN", "US"]),
)
def test_risk_score_properties(amount, country):
    """Test: Risikoscore proportional zu Betrag und Land"""

    ml_check = MoneyLaunderingCheck(
        entity_type="donation", entity_id=uuid4(), amount=amount, donor_country=country
    )

    score = ml_check.calculate_risk_score()

    # Hohe Beträge -> Höherer Score
    if amount > 50000:
        assert score >= 40
    elif amount > 10000:
        assert score >= 30

    # Hochrisikoländer -> Zusätzliche Punkte
    if country in ["RU", "CN"]:
        assert score >= 20 if amount > 1000 else True


# ==================== Performance Tests ====================


@pytest.mark.benchmark
def test_hash_computation_benchmark(benchmark):
    """Benchmark: Hash-Berechnung für GoBD"""
    import hashlib

    data = b"Test document content" * 1000

    def compute_hash():
        return hashlib.sha256(data).hexdigest()

    result = benchmark(compute_hash)
    assert len(result) == 64
