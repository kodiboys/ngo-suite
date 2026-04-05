# FILE: src/adapters/api_export.py
# MODULE: Export API Endpoints (FastAPI)
# REST Endpoints für CSV, Excel, JSON, DATEV Exporte

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from src.adapters.auth import get_current_active_user, require_role
from src.core.entities.base import User, UserRole
from src.services.backup_service import WasabiBackupService
from src.services.export_service import ExportService

router = APIRouter(prefix="/api/v1/export", tags=["export"])


# ==================== Spenden Exporte ====================

@router.get("/donations")
async def export_donations(
    start_date: str,
    end_date: str,
    format: str = "excel",
    project_id: UUID | None = None,
    include_personal_data: bool = True,
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT))
):
    """
    Exportiert Spenden als Excel, CSV oder JSON
    """
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)

    data = await export_service.export_donations(
        start_date=start,
        end_date=end,
        format=format,
        project_id=project_id,
        include_personal_data=include_personal_data,
        user_id=current_user.id
    )

    content_type = {
        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
        "json": "application/json"
    }.get(format, "application/octet-stream")

    extension = {"excel": "xlsx", "csv": "csv", "json": "json"}.get(format, "bin")

    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename=spenden_export_{start_date}_{end_date}.{extension}"
        }
    )


@router.get("/projects")
async def export_projects(
    status: str | None = None,
    format: str = "excel",
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER))
):
    """
    Exportiert Projekte mit KPIs
    """
    data = await export_service.export_projects(
        status=status,
        format=format
    )

    extension = {"excel": "xlsx", "csv": "csv", "json": "json"}.get(format, "bin")

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename=projekte_export.{extension}"}
    )


# ==================== DSGVO Exporte ====================

@router.get("/dsgvo/my-data")
async def export_my_data(
    format: str = "json",
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(get_current_active_user)
):
    """
    DSGVO Art.15: Export der eigenen Daten
    """
    data = await export_service.export_dsgvo_data(
        user_id=current_user.id,
        format=format
    )

    extension = {"json": "json", "csv": "csv"}.get(format, "json")

    return Response(
        content=data,
        media_type="application/json" if format == "json" else "text/csv",
        headers={"Content-Disposition": f"attachment; filename=meine_daten_{current_user.id}.{extension}"}
    )


# ==================== Audit Log Exporte ====================

@router.get("/audit-log")
async def export_audit_log(
    start_date: str,
    end_date: str,
    entity_type: str | None = None,
    user_id: UUID | None = None,
    format: str = "excel",
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(require_role(UserRole.AUDITOR))
):
    """
    Exportiert Audit-Log für Compliance Reports
    """
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)

    data = await export_service.export_audit_log(
        start_date=start,
        end_date=end,
        entity_type=entity_type,
        user_id=user_id,
        format=format
    )

    extension = {"excel": "xlsx", "csv": "csv", "json": "json"}.get(format, "xlsx")

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename=audit_log_{start_date}_{end_date}.{extension}"}
    )


# ==================== Finanzberichte ====================

@router.get("/financial-report/{year}")
async def export_financial_report(
    year: int,
    format: str = "excel",
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT))
):
    """
    Exportiert finanziellen Jahresbericht
    """
    data = await export_service.export_financial_report(
        year=year,
        format=format
    )

    extension = {"excel": "xlsx", "csv": "csv"}.get(format, "xlsx")

    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=jahresbericht_{year}.{extension}"}
    )


# ==================== Backup Management ====================

@router.post("/backup/create")
async def create_backup(
    backup_type: str = "daily",
    backup_service: WasabiBackupService = Depends(get_backup_service),
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Erstellt ein manuelles Backup
    """
    from src.core.config import settings

    result = await backup_service.create_full_backup(
        database_url=settings.DATABASE_URL,
        backup_type=backup_type,
        user_id=current_user.id
    )

    return {
        "backup_id": result["backup_id"],
        "size_mb": result["size_bytes"] / 1024 / 1024,
        "created_at": result["created_at"],
        "checksum": result["checksum"][:16] + "..."
    }


@router.get("/backup/list")
async def list_backups(
    backup_type: str = "daily",
    backup_service: WasabiBackupService = Depends(get_backup_service),
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Listet alle verfügbaren Backups auf
    """
    backups = await backup_service.list_backups(backup_type)

    return [
        {
            "backup_id": b["backup_id"],
            "created_at": b["created_at"],
            "size_mb": b["size_bytes"] / 1024 / 1024,
            "encrypted": b.get("encrypted", False)
        }
        for b in backups
    ]


@router.post("/backup/restore/{backup_id}")
async def restore_backup(
    backup_id: str,
    backup_type: str = "daily",
    backup_service: WasabiBackupService = Depends(get_backup_service),
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Stellt ein Backup wieder her (Disaster Recovery)
    """
    from src.core.config import settings

    success = await backup_service.restore_backup(
        backup_id=backup_id,
        database_url=settings.DATABASE_URL,
        backup_type=backup_type
    )

    return {
        "success": success,
        "backup_id": backup_id,
        "restored_at": datetime.utcnow().isoformat(),
        "restored_by": str(current_user.id)
    }


@router.get("/backup/verify/{backup_id}")
async def verify_backup(
    backup_id: str,
    backup_type: str = "daily",
    backup_service: WasabiBackupService = Depends(get_backup_service),
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Verifiziert die Integrität eines Backups
    """
    is_valid = await backup_service.verify_backup_integrity(
        backup_id=backup_id,
        backup_type=backup_type
    )

    return {
        "backup_id": backup_id,
        "is_valid": is_valid,
        "verified_at": datetime.utcnow().isoformat()
    }


# ==================== Bulk Export ====================

@router.post("/bulk")
async def create_bulk_export(
    start_date: str,
    end_date: str,
    include_donations: bool = True,
    include_projects: bool = True,
    include_audit_log: bool = False,
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Erstellt einen Bulk-Export mit mehreren Berichten als ZIP
    """
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)

    exports = []
    filenames = []

    if include_donations:
        donations_data = await export_service.export_donations(
            start_date=start,
            end_date=end,
            format="excel",
            include_personal_data=True
        )
        exports.append(donations_data)
        filenames.append(f"spenden_{start_date}_{end_date}.xlsx")

    if include_projects:
        projects_data = await export_service.export_projects(format="excel")
        exports.append(projects_data)
        filenames.append("projekte.xlsx")

    if include_audit_log:
        audit_data = await export_service.export_audit_log(
            start_date=start,
            end_date=end,
            format="excel"
        )
        exports.append(audit_data)
        filenames.append(f"audit_log_{start_date}_{end_date}.xlsx")

    # Erstelle ZIP-Archiv
    zip_data = await export_service.create_export_archive(exports, filenames)

    return Response(
        content=zip_data,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=bulk_export_{start_date}_{end_date}.zip"}
    )
