# FILE: src/ports/payment_paypal.py
# MODULE: PayPal Payment Provider Implementation
# Async PayPal Integration mit Orders API, Webhooks

import json
import logging
from datetime import datetime
from decimal import Decimal

import httpx

from src.ports.payment_base import (
    CreatePaymentRequest,
    PaymentIntent,
    PaymentProvider,
    PaymentProviderInterface,
    PaymentStatus,
    RefundRequest,
    RefundResult,
    WebhookEvent,
)

logger = logging.getLogger(__name__)

class PayPalProvider(PaymentProviderInterface):
    """
    PayPal Payment Provider Implementation
    Features:
    - PayPal Checkout (Redirect)
    - Webhook Verification
    - Automatic Token Refresh
    """

    def __init__(self, client_id: str, client_secret: str, webhook_id: str,
                 mode: str = "live", redis_client=None):
        """
        Args:
            client_id: PayPal REST API Client ID
            client_secret: PayPal REST API Secret
            webhook_id: PayPal Webhook ID für Verifikation
            mode: "sandbox" oder "live"
            redis_client: Für Token Caching
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.webhook_id = webhook_id
        self.mode = mode
        self.redis = redis_client

        # Base URL
        self.base_url = "https://api-m.paypal.com" if mode == "live" else "https://api-m.sandbox.paypal.com"

        # HTTP Client
        self.client = httpx.AsyncClient(timeout=30.0)

        # Token Caching
        self.access_token = None
        self.token_expires_at = None

    async def _get_access_token(self) -> str:
        """Holt oder refresh PayPal Access Token"""
        # Check Cache
        if self.redis:
            cached_token = await self.redis.get("paypal:access_token")
            if cached_token:
                return cached_token.decode()

        # Token ist abgelaufen oder nicht vorhanden
        if self.access_token and self.token_expires_at > datetime.utcnow():
            return self.access_token

        # Hole neuen Token
        auth = httpx.BasicAuth(self.client_id, self.client_secret)
        response = await self.client.post(
            f"{self.base_url}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=auth
        )
        response.raise_for_status()

        token_data = response.json()
        self.access_token = token_data["access_token"]
        self.token_expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"] - 60)

        # Cache in Redis
        if self.redis:
            await self.redis.setex(
                "paypal:access_token",
                token_data["expires_in"] - 60,
                self.access_token
            )

        return self.access_token

    async def create_payment_intent(self, request: CreatePaymentRequest) -> PaymentIntent:
        """Erstellt PayPal Order (Payment Intent)"""
        try:
            token = await self._get_access_token()

            # PayPal Order erstellen
            order_data = {
                "intent": "CAPTURE",
                "purchase_units": [{
                    "amount": {
                        "currency_code": request.currency,
                        "value": str(request.amount),
                        "breakdown": {
                            "item_total": {
                                "currency_code": request.currency,
                                "value": str(request.amount)
                            }
                        }
                    },
                    "description": f"Donation to TrueAngels - Project {request.project_id}",
                    "custom_id": str(request.project_id),
                    "invoice_id": f"TA-{request.project_id}-{datetime.utcnow().timestamp()}"
                }],
                "application_context": {
                    "brand_name": "TrueAngels e.V.",
                    "landing_page": "BILLING",
                    "user_action": "PAY_NOW",
                    "return_url": request.success_url or "https://trueangels.de/donation/success",
                    "cancel_url": request.cancel_url or "https://trueangels.de/donation/cancel"
                }
            }

            # PayPal spezifische Metadata
            order_data["purchase_units"][0]["payee"] = {
                "email": "donations@trueangels.de"
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            }

            response = await self.client.post(
                f"{self.base_url}/v2/checkout/orders",
                json=order_data,
                headers=headers
            )
            response.raise_for_status()
            order = response.json()

            # Finde Approval URL für Redirect
            redirect_url = None
            for link in order.get("links", []):
                if link.get("rel") == "approve":
                    redirect_url = link.get("href")
                    break

            return PaymentIntent(
                id=order["id"],
                provider=PaymentProvider.PAYPAL,
                amount=request.amount,
                currency=request.currency,
                status=PaymentStatus.PENDING,
                payment_method=request.payment_method,
                donor_email=request.donor_email,
                donor_name=request.donor_name,
                project_id=request.project_id,
                metadata={
                    "order_id": order["id"],
                    "redirect_url": redirect_url
                },
                created_at=datetime.fromisoformat(order["create_time"].replace('Z', '+00:00'))
            )

        except httpx.HTTPError as e:
            logger.error(f"PayPal error creating order: {e}")
            raise PaymentProviderError(f"PayPal error: {str(e)}") from e

    async def confirm_payment(self, payment_intent_id: str, payment_method_id: str = None) -> PaymentIntent:
        """Capturiert PayPal Order (Zahlung bestätigen)"""
        try:
            token = await self._get_access_token()

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            # Capture Order
            response = await self.client.post(
                f"{self.base_url}/v2/checkout/orders/{payment_intent_id}/capture",
                headers=headers
            )
            response.raise_for_status()
            capture = response.json()

            # Status mapping
            status = PaymentStatus.SUCCEEDED if capture.get("status") == "COMPLETED" else PaymentStatus.FAILED

            return PaymentIntent(
                id=payment_intent_id,
                provider=PaymentProvider.PAYPAL,
                amount=Decimal(capture["purchase_units"][0]["payments"]["captures"][0]["amount"]["value"]),
                currency=capture["purchase_units"][0]["payments"]["captures"][0]["amount"]["currency_code"],
                status=status,
                metadata=capture
            )

        except httpx.HTTPError as e:
            logger.error(f"PayPal error capturing payment: {e}")
            raise

    async def get_payment_status(self, payment_intent_id: str) -> PaymentIntent:
        """Holt PayPal Order Status"""
        try:
            token = await self._get_access_token()

            headers = {"Authorization": f"Bearer {token}"}
            response = await self.client.get(
                f"{self.base_url}/v2/checkout/orders/{payment_intent_id}",
                headers=headers
            )
            response.raise_for_status()
            order = response.json()

            # Map PayPal Status
            status_map = {
                "CREATED": PaymentStatus.PENDING,
                "APPROVED": PaymentStatus.PROCESSING,
                "COMPLETED": PaymentStatus.SUCCEEDED,
                "VOIDED": PaymentStatus.FAILED
            }

            return PaymentIntent(
                id=order["id"],
                provider=PaymentProvider.PAYPAL,
                amount=Decimal(order["purchase_units"][0]["amount"]["value"]),
                currency=order["purchase_units"][0]["amount"]["currency_code"],
                status=status_map.get(order["status"], PaymentStatus.PENDING),
                metadata=order
            )

        except httpx.HTTPError as e:
            logger.error(f"PayPal error getting status: {e}")
            raise

    async def refund_payment(self, refund_request: RefundRequest) -> RefundResult:
        """Führt PayPal Rückerstattung durch"""
        try:
            token = await self._get_access_token()

            # Hole Capture ID
            order = await self.get_payment_status(refund_request.payment_intent_id)
            capture_id = order.metadata.get("purchase_units", [{}])[0].get("payments", {}).get("captures", [{}])[0].get("id")

            if not capture_id:
                raise PaymentProviderError("No capture found for refund")

            refund_data = {
                "amount": {
                    "currency_code": "EUR",
                    "value": str(refund_request.amount) if refund_request.amount else "full"
                },
                "note_to_payer": refund_request.reason or "Refund requested by donor"
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            response = await self.client.post(
                f"{self.base_url}/v2/payments/captures/{capture_id}/refund",
                json=refund_data,
                headers=headers
            )
            response.raise_for_status()
            refund = response.json()

            return RefundResult(
                id=refund["id"],
                payment_intent_id=refund_request.payment_intent_id,
                amount=Decimal(refund["amount"]["value"]),
                status=refund["status"],
                created_at=datetime.fromisoformat(refund["create_time"].replace('Z', '+00:00'))
            )

        except httpx.HTTPError as e:
            logger.error(f"PayPal error refunding: {e}")
            raise

    async def handle_webhook(self, payload: bytes, signature: str) -> WebhookEvent:
        """Verarbeitet PayPal Webhook mit Verifikation"""
        try:
            # PayPal Webhook Verifikation
            token = await self._get_access_token()

            # Verifiziere Webhook
            verification_data = {
                "auth_algo": "SHA256withRSA",
                "cert_url": "https://api.paypal.com/v1/notifications/verify-cert",
                "transmission_id": "TODO",  # Aus Header
                "transmission_sig": signature,
                "transmission_time": "TODO",  # Aus Header
                "webhook_id": self.webhook_id,
                "webhook_event": json.loads(payload.decode())
            }

            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            response = await self.client.post(
                f"{self.base_url}/v1/notifications/verify-webhook-signature",
                json=verification_data,
                headers=headers
            )
            response.raise_for_status()
            verification = response.json()

            if verification.get("verification_status") != "SUCCESS":
                raise WebhookVerificationError("PayPal webhook verification failed")

            event_data = json.loads(payload.decode())

            return WebhookEvent(
                id=event_data["id"],
                provider=PaymentProvider.PAYPAL,
                event_type=event_data["event_type"],
                payment_intent_id=event_data.get("resource", {}).get("id"),
                data=event_data,
                created_at=datetime.fromisoformat(event_data["create_time"].replace('Z', '+00:00')),
                is_test=False
            )

        except Exception as e:
            logger.error(f"PayPal webhook error: {e}")
            raise

    async def cancel_payment(self, payment_intent_id: str) -> PaymentIntent:
        """Storniert PayPal Order"""
        try:
            token = await self._get_access_token()

            headers = {"Authorization": f"Bearer {token}"}
            response = await self.client.post(
                f"{self.base_url}/v2/checkout/orders/{payment_intent_id}/void",
                headers=headers
            )
            response.raise_for_status()

            return await self.get_payment_status(payment_intent_id)

        except httpx.HTTPError as e:
            logger.error(f"PayPal error canceling: {e}")
            raise
