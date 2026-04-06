# FILE: src/adapters/api_payments.py
# MODULE: Payment API Endpoints (FastAPI)
# REST Endpoints für Zahlungen, Webhooks, Refunds

from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, BackgroundTasks

from src.adapters.auth import get_current_active_user, require_role
from src.adapters.dependencies import get_payment_service
from src.core.entities.base import User, UserRole
from src.ports.payment_base import CreatePaymentRequest, PaymentProvider
from src.services.payment_service import PaymentService

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


# ==================== Public Endpoints ====================

@router.post("/create-donation")
async def create_donation(
    request: Request,
    payment_request: CreatePaymentRequest,
    payment_service: PaymentService = Depends(get_payment_service),
    current_user: User = Depends(get_current_active_user),
):
    """
    Erstellt eine neue Spende mit Payment Intent
    Unterstützt Stripe, PayPal, Klarna
    """
    result = await payment_service.create_donation_with_payment(
        request=payment_request,
        user_id=current_user.id,
        ip_address=request.client.host
    )
    return result


@router.get("/status/{payment_intent_id}")
async def get_payment_status(
    payment_intent_id: str,
    provider: PaymentProvider,
    payment_service: PaymentService = Depends(get_payment_service),
):
    """
    Holt aktuellen Status einer Zahlung
    """
    status = await payment_service.get_payment_status(payment_intent_id, provider)
    return status


# ==================== Webhook Endpoints (kein Auth) ====================

@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    payment_service: PaymentService = Depends(get_payment_service),
):
    """
    Stripe Webhook Handler
    Verarbeitet payment_intent.succeeded, payment_intent.payment_failed, etc.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    
    # Async verarbeiten (nicht blockieren)
    background_tasks.add_task(
        payment_service.handle_webhook,
        PaymentProvider.STRIPE,
        payload,
        signature
    )
    
    return {"received": True}


@router.post("/webhook/paypal")
async def paypal_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    payment_service: PaymentService = Depends(get_payment_service),
):
    """
    PayPal Webhook Handler
    """
    payload = await request.body()
    signature = request.headers.get("paypal-transmission-sig")
    
    background_tasks.add_task(
        payment_service.handle_webhook,
        PaymentProvider.PAYPAL,
        payload,
        signature
    )
    
    return {"received": True}


@router.post("/webhook/klarna")
async def klarna_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    payment_service: PaymentService = Depends(get_payment_service),
):
    """
    Klarna Webhook Handler
    """
    payload = await request.body()
    signature = request.headers.get("klarna-signature")
    
    background_tasks.add_task(
        payment_service.handle_webhook,
        PaymentProvider.KLARNA,
        payload,
        signature
    )
    
    return {"received": True}


# ==================== Admin Endpoints ====================

@router.post("/refund/{donation_id}")
async def refund_donation(
    donation_id: UUID,
    amount: Optional[Decimal] = None,
    reason: Optional[str] = None,
    payment_service: PaymentService = Depends(get_payment_service),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Rückerstattung einer Spende (Admin only)
    """
    result = await payment_service.refund_donation(
        donation_id=donation_id,
        amount=amount,
        reason=reason,
        user_id=current_user.id
    )
    return result


@router.get("/reports/daily")
async def daily_payment_report(
    date: str,  # YYYY-MM-DD
    payment_service: PaymentService = Depends(get_payment_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
):
    """
    Täglicher Zahlungsreport für Buchhaltung
    """
    report = await payment_service.get_daily_report(date)
    return report