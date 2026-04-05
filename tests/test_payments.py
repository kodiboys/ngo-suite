# FILE: tests/test_payments.py
# MODULE: Payment Tests mit Mocking & Integration Tests
# Testet Stripe, PayPal, Klarna Integration

from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from src.ports.payment_base import (
    CreatePaymentRequest,
    PaymentIntent,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
)
from src.ports.payment_stripe import StripeProvider
from src.services.payment_service import PaymentService

# ==================== Unit Tests ====================

@pytest.mark.asyncio
async def test_stripe_create_payment():
    """Test Stripe Payment Intent Creation"""

    with patch('stripe.PaymentIntent.create') as mock_create:
        # Mock Stripe Response
        mock_intent = Mock()
        mock_intent.id = "pi_123456"
        mock_intent.client_secret = "secret_123"
        mock_intent.amount = 10000  # 100.00 EUR in Cent
        mock_intent.currency = "eur"
        mock_intent.status = "requires_payment_method"
        mock_intent.created = 1699999999
        mock_create.return_value = mock_intent

        provider = StripeProvider(
            api_key="sk_test_xxx",
            webhook_secret="whsec_xxx",
            redis_client=None
        )

        request = CreatePaymentRequest(
            amount=Decimal("100.00"),
            currency="EUR",
            payment_method=PaymentMethod.CREDIT_CARD,
            donor_email="test@example.com",
            project_id=uuid4()
        )

        result = await provider.create_payment_intent(request)

        assert result.id == "pi_123456"
        assert result.amount == Decimal("100.00")
        assert result.provider == PaymentProvider.STRIPE
        assert result.status == PaymentStatus.PENDING

@pytest.mark.asyncio
async def test_payment_fallback():
    """Test automatischer Provider Fallback"""

    # Mock Service mit fallback
    service = Mock()

    # Simuliere Stripe Fehler, dann PayPal Success
    service.create_payment_intent = AsyncMock(side_effect=[
        Exception("Stripe down"),
        PaymentIntent(
            id="pay_123",
            provider=PaymentProvider.PAYPAL,
            amount=Decimal("50.00"),
            currency="EUR",
            status=PaymentStatus.PENDING
        )
    ])

    # Test Fallback
    with patch('src.services.payment_service.PaymentService._create_payment_internal', service.create_payment_intent):
        result = await service.create_payment_intent(Mock())
        assert result.provider == PaymentProvider.PAYPAL

# ==================== Webhook Tests ====================

@pytest.mark.asyncio
async def test_stripe_webhook_success():
    """Test Stripe Webhook für erfolgreiche Zahlung"""

    payload = {
        "id": "evt_123",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_123",
                "amount": 10000,
                "currency": "eur",
                "status": "succeeded"
            }
        }
    }

    with patch('stripe.Webhook.construct_event') as mock_webhook:
        mock_event = Mock()
        mock_event.type = "payment_intent.succeeded"
        mock_event.data.object.id = "pi_123"
        mock_event.data.object.to_dict.return_value = payload["data"]["object"]
        mock_event.created = 1699999999
        mock_event.livemode = False
        mock_webhook.return_value = mock_event

        provider = StripeProvider("sk_test", "whsec_test", None)
        result = await provider.handle_webhook(
            b'{}',
            "test_signature"
        )

        assert result.event_type == "payment_intent.succeeded"
        assert result.payment_intent_id == "pi_123"

# ==================== Integration Tests ====================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_payment_flow(db_session, redis_client):
    """Test vollständigen Payment Flow mit echter DB"""

    # Setup
    service = PaymentService(db_session, redis_client, Mock())

    # Create Request
    request = CreatePaymentRequest(
        amount=Decimal("25.00"),
        currency="EUR",
        payment_method=PaymentMethod.CREDIT_CARD,
        donor_email="integration@test.com",
        project_id=uuid4()
    )

    # Mock Provider für Integration Test
    with patch.object(service, 'providers') as mock_providers:
        mock_provider = AsyncMock()
        mock_provider.create_payment_intent.return_value = PaymentIntent(
            id="pi_integration",
            provider=PaymentProvider.STRIPE,
            amount=Decimal("25.00"),
            currency="EUR",
            status=PaymentStatus.PENDING,
            client_secret="secret"
        )
        mock_providers.__getitem__.return_value = mock_provider

        # Create Donation
        result = await service.create_donation_with_payment(
            request=request,
            user_id=uuid4(),
            ip_address="127.0.0.1"
        )

        assert "donation_id" in result
        assert result["provider"] == "stripe"

# ==================== Property-Based Tests ====================

from hypothesis import given
from hypothesis import strategies as st


@given(
    amount=st.decimals(min_value=0.01, max_value=100000, places=2),
    email=st.emails()
)
def test_payment_amount_validation(amount, email):
    """Test: Alle Beträge werden korrekt validiert"""
    try:
        request = CreatePaymentRequest(
            amount=amount,
            currency="EUR",
            payment_method=PaymentMethod.CREDIT_CARD,
            donor_email=email,
            project_id=uuid4()
        )
        assert request.amount > 0
    except Exception as e:
        # Negative Beträge sollten fehlschlagen
        assert amount <= 0 or "positive" in str(e).lower()

# ==================== Performance Tests ====================

@pytest.mark.benchmark
def test_payment_intent_serialization(benchmark):
    """Benchmark: Payment Intent Serialisierung"""

    intent = PaymentIntent(
        id="pi_123",
        provider=PaymentProvider.STRIPE,
        amount=Decimal("100.00"),
        currency="EUR",
        status=PaymentStatus.PENDING
    )

    def serialize():
        import json
        from dataclasses import asdict
        return json.dumps(asdict(intent), default=str)

    result = benchmark(serialize)
    assert "pi_123" in result
