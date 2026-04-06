# FILE: src/adapters/api_compliance.py
# MODULE: Compliance API Endpoints (FastAPI)
# REST Endpoints für 4-Augen-Freigabe, Geldwäscheprüfungen, Reports

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from src.services.compliance_service import ComplianceService
from src.core.compliance.base import FourEyesRequest, ComplianceCheckResult
from src.adapters.auth import get_current_active_user, require_role
from src.core.entities.base import User, UserRole

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])


# ==================== Dependency ====================

async def get_compliance_service(request: Request) -> ComplianceService:
    """Dependency Injection für Compliance Service"""
    redis_client = request.app.state.redis
    session_factory = request.app.state.db_session_factory
    event_bus = request.app.state.event_bus
    return ComplianceService(session_factory, redis_client, event_bus)


# ==================== 4-Augen-Prinzip ====================

@router.post("/four-eyes/request")
async def request_four_eyes_approval(
    request: Request,
    approval_request: FourEyesRequest,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER))
):
    """
    Fordert 4-Augen-Freigabe für Transaktion > 5.000€ an
    """
    approval = await compliance_service.request_four_eyes_approval(
        request=approval_request,
        initiator_id=current_user.id,
        ip_address=request.client.host
    )
    
    return {
        "approval_id": str(approval.id),
        "status": approval.status.value,
        "expires_at": approval.expires_at.isoformat(),
        "message": f"Approval request created. Waiting for {approval.approver_1_id}"
    }


@router.post("/four-eyes/{approval_id}/approve")
async def approve_transaction(
    approval_id: UUID,
    comment: Optional[str] = None,
    request: Request = None,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT))
):
    """
    Gibt eine Transaktion frei (2. Prüfer)
    """
    approval = await compliance_service.approve_transaction(
        approval_id=approval_id,
        approver_id=current_user.id,
        comment=comment,
        ip_address=request.client.host
    )
    
    return {
        "approval_id": str(approval.id),
        "status": approval.status.value,
        "fully_approved": approval.is_fully_approved,
        "message": "Transaction approved" if approval.is_fully_approved else "Waiting for second approval"
    }


@router.post("/four-eyes/{approval_id}/reject")
async def reject_transaction(
    approval_id: UUID,
    reason: str,
    request: Request,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT))
):
    """
    Lehnt eine Transaktion ab
    """
    approval = await compliance_service.reject_transaction(
        approval_id=approval_id,
        approver_id=current_user.id,
        reason=reason,
        ip_address=request.client.host
    )
    
    return {
        "approval_id": str(approval.id),
        "status": approval.status.value,
        "message": "Transaction rejected"
    }


@router.get("/four-eyes/pending")
async def get_pending_approvals(
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(get_current_active_user)
):
    """
    Holt ausstehende Freigaben für aktuellen Benutzer
    """
    approvals = await compliance_service.get_pending_approvals(current_user.id)
    
    return [
        {
            "id": str(a.id),
            "entity_type": a.entity_type,
            "entity_id": str(a.entity_id),
            "amount": float(a.amount),
            "reason": a.reason,
            "initiated_by": str(a.initiator_id),
            "initiated_at": a.initiated_at.isoformat(),
            "expires_at": a.expires_at.isoformat(),
            "days_pending": a.days_pending
        }
        for a in approvals
    ]


# ==================== Geldwäscheprüfung ====================

@router.post("/money-laundering/check")
async def check_money_laundering(
    entity_type: str,
    entity_id: UUID,
    amount: float,
    donor_name: Optional[str] = None,
    donor_email: Optional[str] = None,
    donor_country: Optional[str] = None,
    payment_method: Optional[str] = None,
    request: Request = None,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT))
):
    """
    Führt Geldwäscheprüfung für Transaktion durch
    """
    from decimal import Decimal
    
    ml_check = await compliance_service.check_money_laundering(
        entity_type=entity_type,
        entity_id=entity_id,
        amount=Decimal(str(amount)),
        donor_name=donor_name,
        donor_email=donor_email,
        donor_country=donor_country,
        payment_method=payment_method,
        ip_address=request.client.host if request else None
    )
    
    return {
        "check_id": str(ml_check.id),
        "risk_level": ml_check.risk_level.value,
        "risk_score": ml_check.risk_score,
        "compliance_result": ml_check.compliance_result.value,
        "flags": ml_check.flags,
        "requires_human_review": ml_check.compliance_result == "requires_review"
    }


# ==================== Steuer-Compliance ====================

@router.post("/tax/validate-vat")
async def validate_vat_id(
    vat_id: str,
    country_code: str,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(get_current_active_user)
):
    """
    Validiert Umsatzsteuer-ID über VIES
    """
    result = await compliance_service.validate_vat_id(vat_id, country_code)
    return result


@router.post("/tax/generate-receipt/{donation_id}")
async def generate_tax_receipt(
    donation_id: UUID,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT))
):
    """
    Generiert steuerliche Zuwendungsbescheinigung
    """
    receipt = await compliance_service.generate_tax_receipt(donation_id)
    return receipt


# ==================== GoBD-Compliance ====================

@router.post("/gobd/archive")
async def archive_document(
    record_type: str,
    record_id: UUID,
    filename: str,
    # In Production: File Upload via UploadFile
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Archiviert Dokument GoBD-konform
    """
    # In Production: File content aus Request
    content = b"Sample PDF content"
    
    archive = await compliance_service.archive_for_gobd(
        record_type=record_type,
        record_id=record_id,
        content=content,
        filename=filename,
        created_by=current_user.id
    )
    
    return {
        "archive_id": str(archive.id),
        "record_hash": archive.record_hash[:16] + "...",
        "retention_until": archive.retention_until.isoformat(),
        "message": "Document archived successfully"
    }


# ==================== Dashboard & Reports ====================

@router.get("/dashboard")
async def get_compliance_dashboard(
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_OFFICER))
):
    """
    Compliance Dashboard mit KPIs und Metriken
    """
    dashboard = await compliance_service.get_compliance_dashboard()
    return dashboard


@router.get("/report/four-eyes")
async def get_four_eyes_report(
    start_date: datetime,
    end_date: datetime,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_OFFICER))
):
    """
    Report über 4-Augen-Freigaben
    """
    # In Production: Detaillierter Report mit Filtern
    return {
        "report_type": "four_eyes",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/report/money-laundering")
async def get_money_laundering_report(
    start_date: datetime,
    end_date: datetime,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_OFFICER))
):
    """
    Report über Geldwäsche-Verdachtsfälle
    """
    return {
        "report_type": "money_laundering",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "generated_at": datetime.utcnow().isoformat()
    }