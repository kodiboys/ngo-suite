# FILE: src/adapters/api_reports.py
# MODULE: Report API Endpoints (FastAPI)
# REST Endpoints für PDF-Generierung, Exporte, Dashboards

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from src.adapters.auth import get_current_active_user, require_role
from src.adapters.dependencies import (
    get_receipt_generator,
    get_balance_generator,
    get_project_report_generator,
    get_accounting_service,
    get_export_service,
)
from src.core.entities.base import User, UserRole

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


# ==================== Zuwendungsbescheinigungen ====================

@router.get("/donation-receipt/{donation_id}")
async def get_donation_receipt(
    donation_id: UUID,
    include_personal_data: bool = True,
    receipt_generator=Depends(get_receipt_generator),
    current_user: User = Depends(get_current_active_user),
):
    """Generiert Zuwendungsbescheinigung als PDF (Spender oder Admin)"""
    pdf_bytes = await receipt_generator.generate_donation_receipt(
        donation_id, 
        include_personal_data
    )
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=zuwendungsbescheinigung_{donation_id}.pdf"
        }
    )


# ==================== SKR42 Bilanzen ====================

@router.get("/balance-sheet")
async def get_balance_sheet(
    project_id: Optional[UUID] = None,
    year: Optional[int] = None,
    include_comparison: bool = True,
    balance_generator=Depends(get_balance_generator),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
):
    """Generiert SKR42-Bilanz als PDF"""
    if year is None:
        year = datetime.utcnow().year
    
    pdf_bytes = await balance_generator.generate_balance_sheet(
        project_id=project_id,
        year=year,
        include_comparison=include_comparison
    )
    
    filename = f"skr42_bilanz_{year}"
    if project_id:
        filename += f"_projekt_{project_id}"
    filename += ".pdf"
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ==================== Projektberichte ====================

@router.get("/project/{project_id}")
async def get_project_report(
    project_id: UUID,
    include_donors: bool = False,
    report_generator=Depends(get_project_report_generator),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
):
    """Generiert detaillierten Projektbericht als PDF"""
    pdf_bytes = await report_generator.generate_project_report(
        project_id, 
        include_donors
    )
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=projektbericht_{project_id}.pdf"}
    )


# ==================== DATEV Export ====================

@router.get("/export/datev-csv")
async def export_datev_csv(
    start_date: str,
    end_date: str,
    project_id: Optional[UUID] = None,
    accounting_service=Depends(get_accounting_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
):
    """Exportiert Buchungen im DATEV-CSV-Format"""
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    
    csv_bytes = await accounting_service.export_datev_csv(start, end, project_id)
    
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=datev_export_{start_date}_{end_date}.csv"}
    )


@router.get("/export/datev-fuxt")
async def export_datev_fuxt(
    start_date: str,
    end_date: str,
    accounting_service=Depends(get_accounting_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
):
    """Exportiert Buchungen im DATEV-FUXT-Format"""
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    
    fuxt_bytes = await accounting_service.export_datev_fuxt(start, end)
    
    return Response(
        content=fuxt_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f"attachment; filename=datev_fuxt_{start_date}_{end_date}.xml"}
    )


# ==================== Excel/CSV Exporte ====================

@router.get("/export/donations")
async def export_donations(
    start_date: str,
    end_date: str,
    format: str = "excel",
    export_service=Depends(get_export_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
):
    """Exportiert Spendenbericht als Excel oder CSV"""
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    
    data_bytes = await export_service.export_donations_report(start, end, format)
    
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "excel" else "text/csv"
    extension = "xlsx" if format == "excel" else "csv"
    
    return Response(
        content=data_bytes,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename=spendenbericht_{start_date}_{end_date}.{extension}"}
    )


# ==================== Dashboard Daten ====================

@router.get("/dashboard/kpis")
async def get_dashboard_kpis(
    current_user: User = Depends(get_current_active_user),
):
    """Liefert KPI-Daten für Dashboard (JSON)"""
    return {
        "total_donations_current_year": 125000.00,
        "total_donations_previous_year": 98000.00,
        "active_projects": 5,
        "completed_projects": 12,
        "donors_count": 342,
        "average_donation": 45.50,
        "project_efficiency": 87.5,
        "admin_cost_ratio": 12.3,
        "recent_donations": [
            {"date": "2024-01-15", "amount": 150.00, "project": "Bildungsprojekt"},
            {"date": "2024-01-14", "amount": 50.00, "project": "Gesundheitsversorgung"},
        ]
    }


@router.get("/dashboard/charts")
async def get_dashboard_charts(
    current_user: User = Depends(get_current_active_user),
):
    """Liefert Chart-Daten für Dashboard (Plotly-kompatibel)"""
    return {
        "donations_by_month": {
            "months": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun"],
            "values": [8500, 9200, 10500, 11800, 12400, 13100]
        },
        "donations_by_project": {
            "projects": ["Bildung", "Gesundheit", "Umwelt", "Soziales"],
            "values": [45000, 32000, 28000, 20000]
        },
        "expenses_by_category": {
            "categories": ["Programmkosten", "Verwaltung", "Fundraising"],
            "values": [82.5, 12.3, 5.2]
        }
    }