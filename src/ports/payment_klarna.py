# FILE: src/ports/payment_klarna.py
# MODULE: Klarna Payment Provider Implementation
# Klarna Payments API für Pay Now, Pay Later, Slice It

import base64
import json
import logging
from datetime import datetime
from decimal import Decimal

import httpx

from src.ports.payment_base import (
    CreatePaymentRequest,
    PaymentIntent,
    PaymentMethod,
    PaymentProvider,
    PaymentProviderInterface,
    PaymentStatus,
    RefundRequest,
    RefundResult,
    WebhookEvent,
)

logger = logging.getLogger(__name__)


class KlarnaProvider(PaymentProviderInterface):
    """
    Klarna Payment Provider Implementation
    Supports:
    - Klarna Pay Now (Sofortüberweisung)
    - Klarna Pay Later (Rechnung)
    - Klarna Slice It (Ratenzahlung)
    """

    def __init__(self, username: str, password: str, mode: str = "live"):
        self.username = username
        self.password = password
        self.mode = mode

        # Base URL
        self.base_url = (
            "https://api.klarna.com" if mode == "live" else "https://api.playground.klarna.com"
        )

        # HTTP Client
        auth_string = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {auth_string}", "Content-Type": "application/json"}
        self.client = httpx.AsyncClient(timeout=30.0)

    async def create_payment_intent(self, request: CreatePaymentRequest) -> PaymentIntent:
        """Erstellt Klarna Order (Payment Intent)"""
        try:
            # Klarna spezifische Payment Method Codes
            payment_method_codes = self._map_payment_method(request.payment_method)

            order_data = {
                "purchase_country": "DE",
                "purchase_currency": request.currency,
                "locale": "de-DE",
                "order_amount": int(request.amount * 100),  # Cent
                "order_tax_amount": 0,  # Spenden sind steuerfrei
                "order_lines": [
                    {
                        "type": "donation",
                        "name": f"Donation to TrueAngels - Project {request.project_id}",
                        "quantity": 1,
                        "unit_price": int(request.amount * 100),
                        "total_amount": int(request.amount * 100),
                        "total_tax_amount": 0,
                    }
                ],
                "merchant_urls": {
                    "confirmation": request.success_url or "https://trueangels.de/donation/success",
                    "cancel": request.cancel_url or "https://trueangels.de/donation/cancel",
                    "back": "https://trueangels.de/donate",
                },
                "merchant_reference1": str(request.project_id),
                "merchant_reference2": request.donor_email,
            }

            # Klarna Payment Session erstellen
            response = await self.client.post(
                f"{self.base_url}/payments/v1/sessions", json=order_data, headers=self.headers
            )
            response.raise_for_status()
            session = response.json()

            return PaymentIntent(
                id=session["order_id"],
                provider=PaymentProvider.KLARNA,
                amount=request.amount,
                currency=request.currency,
                status=PaymentStatus.PENDING,
                client_secret=session.get("client_token"),
                payment_method=request.payment_method,
                donor_email=request.donor_email,
                donor_name=request.donor_name,
                project_id=request.project_id,
                metadata={
                    "session_id": session["order_id"],
                    "redirect_url": f"{self.base_url}/payments/v1/authorizations/{session['order_id']}",
                },
                created_at=datetime.utcnow(),
            )

        except httpx.HTTPError as e:
            logger.error(f"Klarna error creating payment: {e}")
            raise PaymentProviderError(f"Klarna error: {str(e)}") from e

    async def confirm_payment(
        self, payment_intent_id: str, payment_method_id: str = None
    ) -> PaymentIntent:
        """Bestätigt Klarna Zahlung (Autorisierung)"""
        try:
            # Authorisierung der Order
            auth_data = {
                "order_amount": 0,  # Wird aus Session genommen
                "order_tax_amount": 0,
                "order_lines": [],
            }

            response = await self.client.post(
                f"{self.base_url}/payments/v1/authorizations/{payment_intent_id}/order",
                json=auth_data,
                headers=self.headers,
            )
            response.raise_for_status()
            order = response.json()

            return PaymentIntent(
                id=order["order_id"],
                provider=PaymentProvider.KLARNA,
                amount=Decimal(order["order_amount"] / 100),
                currency=order["purchase_currency"],
                status=(
                    PaymentStatus.SUCCEEDED
                    if order["status"] == "AUTHORIZED"
                    else PaymentStatus.PENDING
                ),
                metadata=order,
            )

        except httpx.HTTPError as e:
            logger.error(f"Klarna error confirming payment: {e}")
            raise

    async def get_payment_status(self, payment_intent_id: str) -> PaymentIntent:
        """Holt Klarna Order Status"""
        try:
            response = await self.client.get(
                f"{self.base_url}/payments/v1/orders/{payment_intent_id}", headers=self.headers
            )
            response.raise_for_status()
            order = response.json()

            status_map = {
                "AUTHORIZED": PaymentStatus.SUCCEEDED,
                "PART_CAPTURED": PaymentStatus.PARTIALLY_REFUNDED,
                "CAPTURED": PaymentStatus.SUCCEEDED,
                "CANCELLED": PaymentStatus.FAILED,
            }

            return PaymentIntent(
                id=order["order_id"],
                provider=PaymentProvider.KLARNA,
                amount=Decimal(order["order_amount"] / 100),
                currency=order["purchase_currency"],
                status=status_map.get(order["status"], PaymentStatus.PENDING),
                metadata=order,
            )

        except httpx.HTTPError as e:
            logger.error(f"Klarna error getting status: {e}")
            raise

    async def refund_payment(self, refund_request: RefundRequest) -> RefundResult:
        """Führt Klarna Rückerstattung durch"""
        try:
            refund_data = {
                "refunded_amount": (
                    int(refund_request.amount * 100) if refund_request.amount else None
                ),
                "description": refund_request.reason or "Refund requested",
            }

            response = await self.client.post(
                f"{self.base_url}/payments/v1/orders/{refund_request.payment_intent_id}/refunds",
                json=refund_data,
                headers=self.headers,
            )
            response.raise_for_status()
            refund = response.json()

            return RefundResult(
                id=refund["refund_id"],
                payment_intent_id=refund_request.payment_intent_id,
                amount=Decimal(refund["refunded_amount"] / 100),
                status=refund["status"],
                created_at=datetime.utcnow(),
            )

        except httpx.HTTPError as e:
            logger.error(f"Klarna error refunding: {e}")
            raise

    async def handle_webhook(self, payload: bytes, signature: str) -> WebhookEvent:
        """Verarbeitet Klarna Webhook"""
        try:
            event_data = json.loads(payload.decode())

            # Klarna Webhook Signatur Prüfung
            # (Implementierung abhängig von Klarna Spezifikation)

            return WebhookEvent(
                id=event_data.get("event_id", str(uuid4())),
                provider=PaymentProvider.KLARNA,
                event_type=event_data.get("event_type", "unknown"),
                payment_intent_id=event_data.get("order_id"),
                data=event_data,
                created_at=datetime.utcnow(),
                is_test=False,
            )

        except Exception as e:
            logger.error(f"Klarna webhook error: {e}")
            raise

    async def cancel_payment(self, payment_intent_id: str) -> PaymentIntent:
        """Storniert Klarna Order"""
        try:
            response = await self.client.patch(
                f"{self.base_url}/payments/v1/orders/{payment_intent_id}/cancel",
                headers=self.headers,
            )
            response.raise_for_status()

            return await self.get_payment_status(payment_intent_id)

        except httpx.HTTPError as e:
            logger.error(f"Klarna error canceling: {e}")
            raise

    def _map_payment_method(self, method: PaymentMethod) -> list:
        """Mappt Payment Methods zu Klarna"""
        mapping = {
            PaymentMethod.KLARNA_PAY_NOW: ["pay_now"],
            PaymentMethod.KLARNA_PAY_LATER: ["pay_later"],
            PaymentMethod.KLARNA_SLICE_IT: ["slice_it"],
        }
        return mapping.get(method, ["pay_now"])
