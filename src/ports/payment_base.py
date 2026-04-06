# FILE: src/ports/payment_base.py
# MODULE: Payment Base Classes & Adapter Pattern für Stripe/PayPal/Klarna
# Enterprise Payment Integration mit Circuit Breaker, Retry, Idempotency

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


# ==================== Enums & Models ====================

class PaymentProvider(str, Enum):
    """Unterstützte Zahlungsanbieter"""
    STRIPE = "stripe"
    PAYPAL = "paypal"
    KLARNA = "klarna"


class PaymentStatus(str, Enum):
    """Status einer Zahlung"""
    PENDING = "pending"              # Ausstehend
    PROCESSING = "processing"        # In Verarbeitung
    SUCCEEDED = "succeeded"          # Erfolgreich
    FAILED = "failed"                # Fehlgeschlagen
    REFUNDED = "refunded"            # Rückerstattet
    PARTIALLY_REFUNDED = "partially_refunded"  # Teilweise erstattet
    DISPUTED = "disputed"            # Beanstandet
    CHARGEBACK = "chargeback"        # Rückbuchung


class PaymentMethod(str, Enum):
    """Zahlungsmethoden"""
    CREDIT_CARD = "credit_card"      # Kreditkarte
    PAYPAL = "paypal"                # PayPal
    KLARNA_PAY_NOW = "klarna_pay_now"      # Klarna Sofort
    KLARNA_PAY_LATER = "klarna_pay_later"  # Klarna Rechnung
    KLARNA_SLICE_IT = "klarna_slice_it"    # Klarna Raten
    SEPA = "sepa"                    # SEPA Lastschrift
    SOFORT = "sofort"                # SOFORT Überweisung
    GIROPAY = "giropay"              # Giropay


@dataclass
class PaymentIntent:
    """
    Einheitliches Payment Intent Model für alle Provider
    Wird von allen Providern zurückgegeben
    """
    id: str                                              # Provider-spezifische ID
    provider: PaymentProvider                           # Zahlungsanbieter
    amount: Decimal                                     # Betrag
    currency: str                                       # Währung (EUR, USD, etc.)
    status: PaymentStatus                               # Aktueller Status
    client_secret: Optional[str] = None                 # Client Secret (Stripe)
    payment_method: Optional[PaymentMethod] = None      # Zahlungsmethode
    donor_email: Optional[str] = None                   # Spender E-Mail
    donor_name: Optional[str] = None                    # Spender Name
    project_id: Optional[UUID] = None                   # Projekt-ID
    metadata: dict[str, Any] = field(default_factory=dict)  # Zusätzliche Metadaten
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RefundRequest:
    """
    Einheitliches Refund Model für Rückerstattungen
    """
    payment_intent_id: str                              # Original Payment Intent ID
    amount: Optional[Decimal] = None                    # None = vollständige Rückerstattung
    reason: Optional[str] = None                        # Grund für Rückerstattung
    metadata: dict[str, Any] = field(default_factory=dict)  # Zusätzliche Metadaten


@dataclass
class RefundResult:
    """
    Ergebnis einer Rückerstattung
    """
    id: str                                              # Refund ID beim Provider
    payment_intent_id: str                              # Original Payment Intent ID
    amount: Decimal                                     # Rückerstatteter Betrag
    status: str                                         # Status der Rückerstattung
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class WebhookEvent:
    """
    Einheitliches Webhook Event Model für alle Provider
    Wird von Webhook Handlern zurückgegeben
    """
    id: str                                              # Event ID beim Provider
    provider: PaymentProvider                           # Zahlungsanbieter
    event_type: str                                     # Event Typ (z.B. payment_intent.succeeded)
    payment_intent_id: Optional[str] = None             # Betroffene Payment Intent ID
    data: dict[str, Any] = field(default_factory=dict)  # Event-Daten
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_test: bool = False                               # Test-Event (Sandbox)


# ==================== Pydantic Models für API ====================

class CreatePaymentRequest(BaseModel):
    """
    API Request Schema für Payment Creation
    Wird von der API validiert
    """
    amount: Decimal = Field(
        ...,
        gt=0,
        le=100000,
        description="Betrag in EUR (min 1€, max 100.000€)"
    )
    currency: str = Field(
        "EUR",
        regex="^(EUR|USD|GBP)$",
        description="Währung (EUR, USD, GBP)"
    )
    payment_method: PaymentMethod = Field(
        ...,
        description="Zahlungsmethode"
    )
    success_url: Optional[str] = Field(
        None,
        description="URL für erfolgreiche Zahlung (Redirect)"
    )
    cancel_url: Optional[str] = Field(
        None,
        description="URL für abgebrochene Zahlung (Redirect)"
    )
    donor_email: str = Field(
        ...,
        regex=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
        description="E-Mail des Spenders"
    )
    donor_name: Optional[str] = Field(
        None,
        description="Name des Spenders (optional)"
    )
    project_id: UUID = Field(
        ...,
        description="Projekt-ID für die Spende"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Zusätzliche Metadaten"
    )

    @validator('amount')
    def validate_amount(cls, v: Decimal) -> Decimal:
        """Validiert den Spendenbetrag"""
        if v < 1:
            raise ValueError('Minimum donation is 1 EUR')
        if v > 100000:
            raise ValueError('Maximum donation is 100,000 EUR')
        return v

    class Config:
        json_encoders = {
            Decimal: str,
            UUID: str
        }


class PaymentResponse(BaseModel):
    """
    API Response Schema für Payment Creation
    Wird an den Client zurückgegeben
    """
    payment_intent_id: str = Field(..., description="Payment Intent ID")
    client_secret: Optional[str] = Field(None, description="Client Secret (für Stripe)")
    status: PaymentStatus = Field(..., description="Aktueller Status")
    provider: PaymentProvider = Field(..., description="Zahlungsanbieter")
    redirect_url: Optional[str] = Field(None, description="Redirect URL (für PayPal/Klarna)")
    requires_action: bool = Field(False, description="Benötigt zusätzliche Aktion (z.B. 3D Secure)")

    class Config:
        use_enum_values = True


# ==================== Abstract Payment Provider Interface ====================

class PaymentProviderInterface(ABC):
    """
    Abstract Interface für alle Payment Provider (Adapter Pattern)
    Alle Zahlungsanbieter müssen dieses Interface implementieren
    """

    @abstractmethod
    async def create_payment_intent(self, request: CreatePaymentRequest) -> PaymentIntent:
        """
        Erstellt ein Payment Intent beim Provider

        Args:
            request: CreatePaymentRequest mit allen Zahlungsdaten

        Returns:
            PaymentIntent mit den Provider-spezifischen Daten

        Raises:
            PaymentProviderError: Bei Fehlern beim Provider
        """
        pass

    @abstractmethod
    async def confirm_payment(
        self,
        payment_intent_id: str,
        payment_method_id: str | None = None
    ) -> PaymentIntent:
        """
        Bestätigt eine Zahlung (z.B. nach 3D Secure)

        Args:
            payment_intent_id: ID des Payment Intents
            payment_method_id: ID der Zahlungsmethode (optional)

        Returns:
            PaymentIntent mit aktualisiertem Status
        """
        pass

    @abstractmethod
    async def get_payment_status(self, payment_intent_id: str) -> PaymentIntent:
        """
        Holt aktuellen Status einer Zahlung vom Provider

        Args:
            payment_intent_id: ID des Payment Intents

        Returns:
            PaymentIntent mit aktuellem Status
        """
        pass

    @abstractmethod
    async def refund_payment(self, refund_request: RefundRequest) -> RefundResult:
        """
        Führt eine Rückerstattung durch

        Args:
            refund_request: RefundRequest mit Rückerstattungsdaten

        Returns:
            RefundResult mit Details der Rückerstattung
        """
        pass

    @abstractmethod
    async def handle_webhook(
        self,
        payload: bytes,
        signature: str
    ) -> WebhookEvent:
        """
        Verarbeitet eingehende Webhooks vom Provider

        Args:
            payload: Rohdaten des Webhooks (Bytes)
            signature: Signatur zur Verifikation

        Returns:
            WebhookEvent mit verarbeiteten Daten

        Raises:
            WebhookVerificationError: Bei ungültiger Signatur
        """
        pass

    @abstractmethod
    async def cancel_payment(self, payment_intent_id: str) -> PaymentIntent:
        """
        Storniert eine ausstehende Zahlung

        Args:
            payment_intent_id: ID des Payment Intents

        Returns:
            PaymentIntent mit storniertem Status
        """
        pass


# ==================== Idempotency Key Manager ====================

class IdempotencyManager:
    """
    Idempotency Keys für sichere Wiederholungen
    Verhindert doppelte Buchungen bei Netzwerkfehlern

    Funktionsweise:
    1. Vor Ausführung einer Operation wird geprüft, ob der Key bereits existiert
    2. Wenn ja: Gecachtes Ergebnis zurückgeben
    3. Wenn nein: Operation ausführen und Ergebnis cachen

    Beispiel:
        result = await idempotency.process_with_idempotency(
            key=f"payment:donation:{donation_id}",
            func=process_payment,
            amount=100
        )
    """

    def __init__(self, redis_client):
        """
        Initialisiert den Idempotency Manager

        Args:
            redis_client: Redis Client für Caching
        """
        self.redis = redis_client

    async def process_with_idempotency(
        self,
        key: str,
        func,
        ttl_seconds: int = 86400,
        *args,
        **kwargs
    ):
        """
        Führt eine Funktion mit Idempotency-Schutz aus

        Args:
            key: Eindeutiger Schlüssel (z.B. "payment:donation_id:123")
            func: Auszuführende Funktion
            ttl_seconds: Wie lange der Schlüssel gespeichert wird (Default: 24h)
            *args, **kwargs: Argumente für die Funktion

        Returns:
            Ergebnis der Funktion oder gecachtes Ergebnis

        Example:
            result = await idempotency.process_with_idempotency(
                key=f"payment:donation:{donation_id}",
                func=create_stripe_payment,
                amount=100,
                currency="EUR"
            )
        """
        import json

        cache_key = f"idempotency:{key}"

        # 1. Prüfe ob bereits verarbeitet
        cached_result = await self.redis.get(cache_key)

        if cached_result:
            # Gecachtes Ergebnis zurückgeben
            return json.loads(cached_result)

        # 2. Führe Funktion aus
        result = await func(*args, **kwargs)

        # 3. Cache Ergebnis
        result_dict = self._serialize_result(result)
        await self.redis.setex(cache_key, ttl_seconds, json.dumps(result_dict, default=str))

        return result

    def _serialize_result(self, result):
        """
        Serialisiert das Ergebnis für Redis Cache
        Unterstützt Dataclasses und Dicts
        """
        if hasattr(result, '__dataclass_fields__'):
            # Dataclass zu Dict konvertieren
            return asdict(result)
        if isinstance(result, dict):
            return result
        return {"value": result}

    async def invalidate(self, key: str):
        """
        Entfernt einen Idempotency Key aus dem Cache
        Wird verwendet, wenn eine Operation wiederholt werden muss

        Args:
            key: Der zu entfernende Schlüssel
        """
        cache_key = f"idempotency:{key}"
        await self.redis.delete(cache_key)


# ==================== Exceptions ====================

class PaymentProviderError(Exception):
    """
    Base Exception für Payment Provider Fehler
    Wird geworfen, wenn ein Zahlungsanbieter einen Fehler meldet
    """
    def __init__(
        self,
        message: str,
        provider: PaymentProvider | None = None,
        original_error: Exception | None = None
    ):
        self.provider = provider
        self.original_error = original_error
        super().__init__(message)


class WebhookVerificationError(Exception):
    """
    Webhook Signatur Verifikation fehlgeschlagen
    Wird geworfen, wenn die Webhook-Signatur ungültig ist
    """
    def __init__(self, message: str, provider: PaymentProvider | None = None):
        self.provider = provider
        super().__init__(message)


class PaymentTimeoutError(PaymentProviderError):
    """
    Timeout bei der Zahlungsabwicklung
    Wird geworfen, wenn der Zahlungsanbieter nicht antwortet
    """
    pass


class PaymentValidationError(PaymentProviderError):
    """
    Validierungsfehler bei Zahlungsdaten
    Wird geworfen, wenn die Zahlungsdaten ungültig sind
    """
    pass
