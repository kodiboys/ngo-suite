# FILE: src/adapters/api_compliance.py
# MODULE: Compliance API Endpoints (FastAPI)

from datetime import datetime, timezone, UUID
from typing import Optional, List, Annotated

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    HTTPException,
    File,
    UploadFile,
)

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
    Dependency Injection for Compliance Service via request.app.state.
    """
    redis_client = request.app.state.redis
    session_factory = request.app.state.db_session_factory
    event_bus = request.app.state.event_bus
    return ComplianceService(
        session_factory=session_factory,
        redis_client=redis_client,
        event_bus=event_bus,
    )


# ==================== 4-Auge-Prinzip ====================


@router.post("/four-eyes/request")
async def request_four_eyes_approval(
    request: Request,
    approval_request: FourEyesRequest,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> dict:

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
    approval_id: UUID,
    comment: Optional[str] = None,
    request: Request | None = None,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
) -> dict:
    """
    Gibt eine Transaktion frei (2. Pruefer).
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
    Holt ausstehende 4 Auge Freigaben fuer den aktuellen Benutzer.
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


# ==================== Geldwaescheprüfung ====================


@router.post("/money-laundering/check")
async def check_money_laundering(
    entity_type: str,
    entity_id: UUID,
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
    Fuehrt Geldwaeschepruefung für eine Transaktion durch.
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


# ==================== Steuer Compliance ====================


@router.post("/tax/validate-vat")
async def validate_vat_id(
    vat_id: str,
    country_code: str,
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Validiert Umsatzsteuer-ID über VIES basierten Service.
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
    Generiert steuerliche Zuwendungsbescheinigung fuer eine Spende.
    """
    receipt = await compliance_service.generate_tax_receipt(donation_id)

    if receipt is None:
        raise HTTPException(status_code=404, detail="Donation not found")

    return {"data": receipt}


# ==================== GoBD-Compliance ====================


@router.post("/gobd/archive")
async def archive_document(
    record_type: str,
    record_id: UUID,
    file: Annotated[UploadFile, File(...)],
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """
    Archiviert Dokument GoBD konform (mit File Upload).
    """
    content = await file.read()

    archive = await compliance_service.archive_for_gobd(
        record_type=record_type,
        record_id=record_id,
        content=content,
        filename=file.filename,
        created_by=current_user.id,
    )

    return {
        "status": "archived",
        "data": {
            "archive_id": str(archive.id),
            "sha256": archive.record_hash,
            "retention_period": "10 years",
            "retention_until": archive.retention_until.isoformat(),
        },
    }


# ==================== Dashboard & Reports ====================


@router.get("/dashboard")
async def get_compliance_dashboard(
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_OFFICER)),
) -> dict:
    """
    Compliance Dashboard mit KPIs und Metriken (transparenzfaehig).
    """
    dashboard = await compliance_service.get_compliance_dashboard()

    if dashboard is None:
        raise HTTPException(status_code=500, detail="Could not load dashboard")

    return {"data": dashboard}


@router.get("/report/four-eyes")
async def get_four_eyes_report(
    start_date: datetime = Query(
        ...,
        description="Startdatum des Berichts (inkl. UTC Zeitzone)",
    ),
    end_date: datetime = Query(
        ...,
        description="Enddatum des Berichts (inkl. UTC Zeitzone)",
    ),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_OFFICER)),
) -> dict:
    """
    Report ueber alle 4 Auge-Freigaben im Zeitraum.
    """
    created_at = datetime.now(timezone.utc)

    return {
        "data": {
            "report_type": "four_eyes",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "generated_at": created_at.isoformat(),
            # NOTE: In Production: report_data aus compliance_service.get_four_eyes_report(...)
        }
    }


@router.get("/report/money-laundering")
async def get_money_laundering_report(
    start_date: datetime = Query(
        ...,
        description="Startdatum des Berichts (inkl. UTC-Zeitzone)",
    ),
    end_date: datetime = Query(
        ...,
        description="Enddatum des Berichts (inkl. UTC-Zeitzone)",
    ),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_OFFICER)),
) -> dict:
    """
    Report ueber alle Geldwaesche Verdachtsfaelle im Zeitraum.
    """
    created_at = datetime.now(timezone.utc)

    return {
        "data": {
            "report_type": "money_laundering",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "generated_at": created_at.isoformat(),
            # NOTE: report_data aus compliance_service.get_money_laundering_report(...)
        }
    }
