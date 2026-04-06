# FILE: src/adapters/api_compliance.py
# MODULE: Compliance API Endpoints (FastAPI)
# REST Endpoints für 4‑Augen‑Freigabe, Geldwäscheprüfungen, Reports

from datetime import datetime, timezone, UUID
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, Request, HTTPException

from src.adapters.auth import get_current_active_user, require_role
from src.core.compliance.base import FourEyesRequest
from src.core.entities.base import User, UserRole
from src.services.compliance_service import ComplianceService


router = APIRouter(
    prefix="/api/v1/compliance",
    tags=["compliance"],
)


# ==================== Dependency ====================

def get_compliance_service(request: Request) -> ComplianceService:
    """
    Dependency Injection für Compliance Service via request.app.state.
    """
    redis_client = request.app.state.redis
    session_factory = request.app.state.db_session_factory
    event_bus = request.app.state.event_bus
    return ComplianceService(
        session_factory=session_factory,
        redis_client=redis_client,
        event_bus=event_bus,
    )


# ==================== 4‑Augen‑Prinzip ====================

@router.post("/four-eyes/request")
async def request_four_eyes_approval(
    request: Request,
    approval_request: FourEyesRequest,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:
    """
    Fordert 4‑Augen‑Freigabe für Transaktion > 5.000 € an.
    """
    approval = await compliance_service.request_four_eyes_approval(
        request=approval_request,
        initiator_id=current_user.id,
        ip_address=request.client.host,
    )

    return {
        "data": {
            "approval_id": str(approval.id),
            "status": approval.status.value,
            "expires_at": approval.expires_at.isoformat(),
            "message": f"Approval request created. Waiting for {approval.approver_1_id}",
        }
    }


@router.post("/four-eyes/{approval_id}/approve")
async def approve_transaction(
    approval_id: UUID,  # automatic FastAPI UUID‑Validation
    comment: Optional[str] = None,
    request: Request | None = None,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
) -> dict:
    """
    Gibt eine Transaktion frei (2. Prüfer).
    """
    approval = await compliance_service.approve_transaction(
        approval_id=approval_id,
        approver_id=current_user.id,
        comment=comment,
        ip_address=request.client.host if request else "unknown",
    )

    return {
        "data": {
            "approval_id": str(approval.id),
            "status": approval.status.value,
            "fully_approved": approval.is_fully_approved,
            "message": (
                "Transaction approved"
                if approval.is_fully_approved
                else "Waiting for second approval"
            ),
        }
    }


@router.post("/four-eyes/{approval_id}/reject")
async def reject_transaction(
    approval_id: UUID,
    reason: str,
    request: Request,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
) -> dict:
    """
    Lehnt eine Transaktion ab.
    """
    approval = await compliance_service.reject_transaction(
        approval_id=approval_id,
        approver_id=current_user.id,
        reason=reason,
        ip_address=request.client.host,
    )

    return {
        "data": {
            "approval_id": str(approval.id),
            "status": approval.status.value,
            "message": "Transaction rejected",
        }
    }


@router.get("/four-eyes/pending")
async def get_pending_approvals(
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Holt ausstehende 4‑Augen‑Freigaben für den aktuellen Benutzer.
    """
    approvals = await compliance_service.get_pending_approvals(user_id=current_user.id)

    return {
        "data": [
            {
                "id": str(a.id),
                "entity_type": a.entity_type,
                "entity_id": str(a.entity_id),
                "amount": float(a.amount),
                "reason": a.reason,
                "initiated_by": str(a.initiator_id),
                "initiated_at": a.initiated_at.isoformat(),
                "expires_at": a.expires_at.isoformat(),
                "days_pending": a.days_pending,
            }
            for a in approvals
        ]
    }


# ==================== Geldwäscheprüfung ====================

@router.post("/money-laundering/check")
async def check_money_laundering(
    entity_type: str,
    entity_id: UUID,  # Path‑ / Body‑Validiert via FastAPI
    amount: float,
    donor_name: Optional[str] = None,
    donor_email: Optional[str] = None,
    donor_country: Optional[str] = None,
    payment_method: Optional[str] = None,
    request: Request | None = None,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
) -> dict:
    """
    Führt Geldwäscheprüfung für eine Transaktion durch.
    """
    from decimal import Decimal

    ml_check = await compliance_service.check_money_laundering(
        entity_type=entity_type,
        entity_id=entity_id,
        amount=Decimal(str(amount)),  # money‑safe
        donor_name=donor_name,
        donor_email=donor_email,
        donor_country=donor_country,
        payment_method=payment_method,
        ip_address=request.client.host if request else None,
    )

    if ml_check is None:
        raise HTTPException(status_code=500, detail="AML check failed internally")

    return {
        "data": {
            "check_id": str(ml_check.id),
            "risk_level": ml_check.risk_level.value,
            "risk_score": ml_check.risk_score,
            "compliance_result": ml_check.compliance_result.value,
            "flags": ml_check.flags,
            "requires_human_review": ml_check.compliance_result == "requires_review",
        }
    }


# ==================== Steuer‑Compliance ====================

@router.post("/tax/validate-vat")
async def validate_vat_id(
    vat_id: str,
    country_code: str,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Validiert Umsatzsteuer‑ID über VIES‑basierten Service.
    """
    result = await compliance_service.validate_vat_id(vat_id, country_code)

    if result is None:
        raise HTTPException(status_code=400, detail="Invalid VAT ID / country code")

    return {"data": result}


@router.post("/tax/generate-receipt/{donation_id}")
async def generate_tax_receipt(
    donation_id: UUID,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
) -> dict:
    """
    Generiert steuerliche Zuwendungsbescheinigung für eine Spende.
    """
    receipt = await compliance_service.generate_tax_receipt(donation_id)

    if receipt is None:
        raise HTTPException(status_code=404, detail="Donation not found")

    return {"data": receipt}


# ==================== GoBD‑Compliance ====================

@router.post("/gobd/archive")
async def archive_document(
    record_type: str,
    record_id: UUID,
    filename: str,
    # NOTE: In Production: File / raw bytes kommen als body.
    # Hier Demo‑Placeholder; in realer API file‑Upload‑Route.
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """
    Archiviert Dokument GoBD‑konform (mit Hash‑Basis, 10‑Jahres‑Retentions‑Timeline).
    """
    content: bytes = b"GoBD‑secure PDF dummy. Will be replaced by file upload in production."

    archive = await compliance_service.archive_for_gobd(
        record_type=record_type,
        record_id=record_id,
        content=content,
        filename=filename,
        created_by=current_user.id,
    )

    return {
        "data": {
            "archive_id": str(archive.id),
            "record_hash": archive.record_hash[:16] + "...",
            "retention_until": archive.retention_until.isoformat(),
            "message": "Document archived successfully",
        }
    }


# ==================== Dashboard & Reports ====================

@router.get("/dashboard")
async def get_compliance_dashboard(
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_OFFICER)),
) -> dict:
    """
    Compliance‑Dashboard mit KPIs und Metriken (transparenzfähig).
    """
    dashboard = await compliance_service.get_compliance_dashboard()

    if dashboard is None:
        raise HTTPException(status_code=500, detail="Could not load dashboard")

    return {"data": dashboard}


@router.get("/report/four-eyes")
async def get_four_eyes_report(
    start_date: datetime = Query(
        ...,
        description="Startdatum des Berichts (inkl. UTC‑Zeitzone)",
    ),
    end_date: datetime = Query(
        ...,
        description="Enddatum des Berichts (inkl. UTC‑Zeitzone)",
    ),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_OFFICER)),
) -> dict:
    """
    Report über alle 4‑Augen‑Freigaben im Zeitraum.
    """
    created_at = datetime.now(timezone.utc)
    # Hier später: Query an Service‑Layer für Report‑Daten

    return {
        "data": {
            "report_type": "four_eyes",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "generated_at": created_at.isoformat(),
            # NOTE: In Production: `report_data` aus `compliance_service.get_four_eyes_report(...)`
        }
    }


@router.get("/report/money-laundering")
async def get_money_laundering_report(
    start_date: datetime = Query(
        ...,
        description="Startdatum des Berichts (inkl. UTC‑Zeitzone)",
    ),
    end_date: datetime = Query(
        ...,
        description="Enddatum des Berichts (inkl. UTC‑Zeitzone)",
    ),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_OFFICER)),
) -> dict:
    """
    Report über alle Geldwäsche‑Verdachtsfälle im Zeitraum.
    """
    created_at = datetime.now(timezone.utc)
    # Hier später: `report_data = await compliance_service.get_money_laundering_report(...)`

    return {
        "data": {
            "report_type": "money_laundering",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "generated_at": created_at.isoformat(),
            # NOTE: `report_data` via Service‑Layer
        }
    }