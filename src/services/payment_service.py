# FILE: src/services/payment_service.py
# MODULE: Payment Orchestration Service mit Fallback & Circuit Breaker
# Koordiniert Stripe, PayPal, Klarna mit automatischem Fallback

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from src.core.entities.base import AuditLog, Donation, Project, TransactionType
from src.core.events.event_bus import Event, EventBus
from src.ports.payment_base import (
    CreatePaymentRequest,
    IdempotencyManager,
    PaymentIntent,
    PaymentProvider,
    PaymentStatus,
    RefundRequest,
    RefundResult,
    WebhookEvent,
)
from src.ports.payment_klarna import KlarnaProvider
from src.ports.payment_paypal import PayPalProvider
from src.ports.payment_stripe import StripeProvider

logger = logging.getLogger(__name__)


class PaymentService:
    """
    Payment Orchestration Service
    Features:
    - Multi-Provider Support (Stripe primary, PayPal/Klarna fallback)
    - Automatic Provider Fallback bei Fehlern
    - Idempotency Keys für doppelte Zahlungen
    - SKR42 Auto-Booking
    - Webhook Processing mit Retry
    """

    def __init__(self, session_factory, redis_client, event_bus: EventBus):
        self.session_factory = session_factory
        self.redis = redis_client
        self.event_bus = event_bus
        self.idempotency = IdempotencyManager(redis_client)

        # Provider initialisieren (aus Config laden)
        self.providers = {
            PaymentProvider.STRIPE: StripeProvider(
                api_key="sk_live_xxx",  # Aus Vault laden
                webhook_secret="whsec_xxx",
                redis_client=redis_client,
            ),
            PaymentProvider.PAYPAL: PayPalProvider(
                client_id="xxx",
                client_secret="xxx",
                webhook_id="xxx",
                mode="live",
                redis_client=redis_client,
            ),
            PaymentProvider.KLARNA: KlarnaProvider(username="xxx", password="xxx", mode="live"),
        }

        # Primary und Fallback Provider
        self.primary_provider = PaymentProvider.STRIPE
        self.fallback_providers = [PaymentProvider.PAYPAL, PaymentProvider.KLARNA]

    async def create_donation_with_payment(
        self, request: CreatePaymentRequest, user_id: UUID, ip_address: str
    ) -> dict[str, Any]:
        """
        Erstellt Spende und Payment Intent mit Idempotency
        """
        # Idempotency Key aus Donor Email + Project + Amount
        idempotency_key = f"donation:{request.donor_email}:{request.project_id}:{request.amount}"

        return await self.idempotency.process_with_idempotency(
            key=idempotency_key,
            func=self._create_payment_internal,
            request=request,
            user_id=user_id,
            ip_address=ip_address,
        )

    async def _create_payment_internal(
        self, request: CreatePaymentRequest, user_id: UUID, ip_address: str
    ) -> dict[str, Any]:
        """Interne Payment Creation mit Fallback"""

        # Versuche primären Provider
        last_error = None
        for provider_type in [self.primary_provider] + self.fallback_providers:
            try:
                provider = self.providers[provider_type]
                payment_intent = await provider.create_payment_intent(request)

                # Speichere Spende in DB
                donation = await self._save_donation(
                    request=request,
                    payment_intent=payment_intent,
                    user_id=user_id,
                    ip_address=ip_address,
                )

                # Publish Event
                await self.event_bus.publish(
                    Event(
                        aggregate_id=donation.id,
                        aggregate_type="Donation",
                        event_type="PaymentIntentCreated",
                        data={
                            "payment_intent_id": payment_intent.id,
                            "provider": provider_type.value,
                            "amount": str(request.amount),
                            "project_id": str(request.project_id),
                        },
                        user_id=user_id,
                        metadata={"ip": ip_address},
                    )
                )

                return {
                    "donation_id": str(donation.id),
                    "payment_intent_id": payment_intent.id,
                    "client_secret": payment_intent.client_secret,
                    "provider": provider_type.value,
                    "status": payment_intent.status,
                    "redirect_url": (
                        payment_intent.metadata.get("redirect_url")
                        if payment_intent.metadata
                        else None
                    ),
                }

            except Exception as e:
                logger.error(f"Provider {provider_type.value} failed: {e}")
                last_error = e
                continue

        # Alle Provider fehlgeschlagen
        raise HTTPException(status_code=502, detail=f"All payment providers failed: {last_error}")

    async def _save_donation(
        self,
        request: CreatePaymentRequest,
        payment_intent: PaymentIntent,
        user_id: UUID,
        ip_address: str,
    ) -> Donation:
        """Speichert Spende in Datenbank mit SKR42 Auto-Booking"""

        async with self.session_factory() as session:
            # Hole Projekt für SKR42 Konto
            stmt = select(Project).where(Project.id == request.project_id)
            result = await session.execute(stmt)
            project = result.scalar_one()

            # SKR42 Konto aus Projekt
            skr42_account = project.skr42_account

            # Erstelle Donation Record
            donation = Donation(
                donor_email_pseudonym=request.donor_email,  # Bereits gehasht durch Validator
                donor_name_encrypted=request.donor_name,
                project_id=request.project_id,
                skr42_account_id=skr42_account.id,
                cost_center=project.cost_center,
                amount=request.amount,
                transaction_type=TransactionType.SPENDE,
                payment_provider=payment_intent.provider.value,
                payment_intent_id=payment_intent.id,
                payment_status=payment_intent.status.value,
                created_by=user_id,
                current_hash="",  # Wird später berechnet
                compliance_status="pending",
            )

            # Berechne Merkle Hash
            donation.current_hash = donation.compute_hash()

            session.add(donation)
            await session.commit()
            await session.refresh(donation)

            # Audit Log
            audit = AuditLog(
                user_id=user_id,
                action="CREATE_SPENDE",
                entity_type="donation",
                entity_id=donation.id,
                new_values={
                    "amount": str(donation.amount),
                    "project_id": str(donation.project_id),
                    "payment_provider": donation.payment_provider,
                },
                ip_address=ip_address,
                retention_until=datetime.utcnow().replace(year=datetime.utcnow().year + 10),
            )
            session.add(audit)
            await session.commit()

            return donation

    async def handle_webhook(
        self, provider: PaymentProvider, payload: bytes, signature: str
    ) -> dict[str, Any]:
        """Verarbeitet eingehende Webhooks von allen Providern"""

        provider_handler = self.providers.get(provider)
        if not provider_handler:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

        # Verifiziere und parse Webhook
        webhook_event = await provider_handler.handle_webhook(payload, signature)

        # Verarbeite je nach Event Typ
        if webhook_event.event_type in [
            "payment_intent.succeeded",
            "CHECKOUT.ORDER.APPROVED",
            "AUTHORIZED",
        ]:
            await self._handle_payment_success(webhook_event)
        elif webhook_event.event_type in ["payment_intent.payment_failed", "CHECKOUT.ORDER.VOIDED"]:
            await self._handle_payment_failure(webhook_event)
        elif "refund" in webhook_event.event_type:
            await self._handle_refund(webhook_event)

        return {"status": "processed", "event_id": webhook_event.id}

    async def _handle_payment_success(self, webhook_event: WebhookEvent):
        """Verarbeitet erfolgreiche Zahlung"""

        async with self.session_factory() as session:
            # Update Donation Status
            stmt = select(Donation).where(
                Donation.payment_intent_id == webhook_event.payment_intent_id
            )
            result = await session.execute(stmt)
            donation = result.scalar_one()

            old_status = donation.payment_status
            donation.payment_status = PaymentStatus.SUCCEEDED.value
            donation.updated_at = datetime.utcnow()

            # Update Merkle Hash
            donation.current_hash = donation.compute_hash()

            await session.commit()

            # Publish Success Event für weitere Verarbeitung
            await self.event_bus.publish(
                Event(
                    aggregate_id=donation.id,
                    aggregate_type="Donation",
                    event_type="DonationSucceeded",
                    data={
                        "amount": str(donation.amount),
                        "project_id": str(donation.project_id),
                        "payment_intent_id": donation.payment_intent_id,
                    },
                    user_id=donation.created_by,
                    metadata={"webhook_event": webhook_event.event_type},
                )
            )

            # Audit Log
            audit = AuditLog(
                user_id=donation.created_by,
                action="PAYMENT_SUCCEEDED",
                entity_type="donation",
                entity_id=donation.id,
                old_values={"payment_status": old_status},
                new_values={"payment_status": PaymentStatus.SUCCEEDED.value},
                ip_address="webhook",
                retention_until=datetime.utcnow().replace(year=datetime.utcnow().year + 10),
            )
            session.add(audit)
            await session.commit()

            logger.info(f"Payment succeeded for donation {donation.id}")

    async def _handle_payment_failure(self, webhook_event: WebhookEvent):
        """Verarbeitet fehlgeschlagene Zahlung"""

        async with self.session_factory() as session:
            stmt = select(Donation).where(
                Donation.payment_intent_id == webhook_event.payment_intent_id
            )
            result = await session.execute(stmt)
            donation = result.scalar_one()

            old_status = donation.payment_status
            donation.payment_status = PaymentStatus.FAILED.value
            donation.updated_at = datetime.utcnow()

            await session.commit()

            # Audit Log
            audit = AuditLog(
                user_id=donation.created_by,
                action="PAYMENT_FAILED",
                entity_type="donation",
                entity_id=donation.id,
                old_values={"payment_status": old_status},
                new_values={"payment_status": PaymentStatus.FAILED.value},
                ip_address="webhook",
                reason=webhook_event.data.get("error_message", "Unknown error"),
                retention_until=datetime.utcnow().replace(year=datetime.utcnow().year + 10),
            )
            session.add(audit)
            await session.commit()

            logger.warning(f"Payment failed for donation {donation.id}: {webhook_event.data}")

    async def _handle_refund(self, webhook_event: WebhookEvent):
        """Verarbeitet Rückerstattung"""

        async with self.session_factory() as session:
            stmt = select(Donation).where(
                Donation.payment_intent_id == webhook_event.payment_intent_id
            )
            result = await session.execute(stmt)
            donation = result.scalar_one()

            old_status = donation.payment_status
            donation.payment_status = PaymentStatus.REFUNDED.value
            donation.updated_at = datetime.utcnow()

            await session.commit()

            # Audit Log
            audit = AuditLog(
                user_id=donation.created_by,
                action="REFUND_PROCESSED",
                entity_type="donation",
                entity_id=donation.id,
                old_values={"payment_status": old_status},
                new_values={"payment_status": PaymentStatus.REFUNDED.value},
                ip_address="webhook",
                retention_until=datetime.utcnow().replace(year=datetime.utcnow().year + 10),
            )
            session.add(audit)
            await session.commit()

            logger.info(f"Refund processed for donation {donation.id}")

    async def refund_donation(
        self,
        donation_id: UUID,
        amount: Decimal | None = None,
        reason: str | None = None,
        user_id: UUID | None = None,
    ) -> RefundResult:
        """Rückerstattung einer Spende"""

        async with self.session_factory() as session:
            # Hole Donation
            stmt = select(Donation).where(Donation.id == donation_id)
            result = await session.execute(stmt)
            donation = result.scalar_one()

            if donation.payment_status != PaymentStatus.SUCCEEDED.value:
                raise HTTPException(
                    status_code=400, detail="Only successful donations can be refunded"
                )

            # Hole Provider
            provider = PaymentProvider(donation.payment_provider)
            provider_handler = self.providers[provider]

            # Führe Refund durch
            refund_request = RefundRequest(
                payment_intent_id=donation.payment_intent_id, amount=amount, reason=reason
            )

            refund_result = await provider_handler.refund_payment(refund_request)

            # Update Donation Status
            donation.payment_status = (
                PaymentStatus.REFUNDED.value
                if not amount or amount == donation.amount
                else PaymentStatus.PARTIALLY_REFUNDED.value
            )
            donation.updated_at = datetime.utcnow()
            donation.current_hash = donation.compute_hash()

            await session.commit()

            # Publish Refund Event
            await self.event_bus.publish(
                Event(
                    aggregate_id=donation.id,
                    aggregate_type="Donation",
                    event_type="DonationRefunded",
                    data={
                        "refund_id": refund_result.id,
                        "amount": str(refund_result.amount),
                        "reason": reason,
                    },
                    user_id=user_id or donation.created_by,
                    metadata={},
                )
            )

            return refund_result
