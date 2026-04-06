# FILE: src/adapters/api_export.py
# MODULE: Export API Endpoints (FastAPI)
# REST Endpoints für CSV, Excel, JSON, DATEV Exporte, DSGVO, Finanzberichte, Backup & Bulk
# Version: 3.0 - Erweitert um Backup‑Management & Bulk‑Export

from typing import Optional, List
from datetime import datetime, timezone

from src.adapters.auth import get_current_active_user, require_role
from src.core.entities.base import User, UserRole
from src.core.config import settings
from src.services.backup_service import WasabiBackupService
from src.services.export_service import ExportService
from fastapi import APIRouter, Depends, Response, HTTPException, Request
from uuid import UUID

router = APIRouter(
    prefix="/api/v1/export",
    tags=["export"]
)


# ==================== Dependency-Injection ====================

def get_export_service(request: Request) -> ExportService:
    """
    Dependency Injection für Export Service.
    Nutzt den zentralen App-State für DB und Cache.
    """
    # Sicherer Zugriff auf die App-Ressourcen
    db_session_factory = request.app.state.db_session_factory
    redis_client = request.app.state.redis
    
    return ExportService(
        session_factory=db_session_factory,
        redis_client=redis_client,
    )

def get_backup_service(request: Request) -> WasabiBackupService:
    """
    Dependency Injection für WasabiBackupService.
    Verbindet Redis für Status-Tracking und Wasabi für S3-Storage.
    """
    return WasabiBackupService(
        redis_client=request.app.state.redis,
        # Falls der Client optional ist, verhindert getattr einen Crash
        wasabi_client=getattr(request.app.state, "wasabi_client", None),
    )


# ==================== Spenden Exporte ====================

@router.get("/donations")
async def export_donations(
    start_date: str,
    end_date: str,
    format: str = "excel",
    project_id: Optional[UUID] = None,
    include_personal_data: bool = True,
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
) -> Response:
    """
    Exportiert Spenden als Excel, CSV oder JSON.
    """
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="start_date und end_date müssen im ISO-Format sein (z.B. 2026-01-01T00:00:00)",
        )

    data: bytes = await export_service.export_donations(
        start_date=start,
        end_date=end,
        format=format,
        project_id=project_id,
        include_personal_data=include_personal_data,
        user_id=current_user.id,
    )

    media_types = {
        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
        "json": "application/json",
    }
    extensions = {
        "excel": "xlsx",
        "csv": "csv",
        "json": "json",
    }

    media_type = media_types.get(format, "application/octet-stream")
    extension = extensions.get(format, "bin")

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename=spenden_export_{start_date}_{end_date}.{extension}"
        },
    )


# ==================== Projekte-Export ====================

@router.get("/projects")
async def export_projects(
    status: Optional[str] = None,
    format: str = "excel",
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
) -> Response:
    """
    Exportiert Projekte mit KPIs.
    """
    data: bytes = await export_service.export_projects(
        status=status,
        format=format,
    )

    extensions = {
        "excel": "xlsx",
        "csv": "csv",
        "json": "json",
    }
    extension = extensions.get(format, "bin")

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename=projekte_export.{extension}"
        },
    )


# ==================== DSGVO Exporte ====================

@router.get("/dsgvo/my-data")
async def export_my_data(
    format: str = "json",
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """
    DSGVO Art. 15: Export der eigenen Daten.
    """
    data: bytes = await export_service.export_dsgvo_data(
        user_id=current_user.id,
        format=format,
    )

    extensions = {
        "json": "json",
        "csv": "csv",
    }
    media_types = {
        "json": "application/json",
        "csv": "text/csv",
    }

    extension = extensions.get(format, "json")
    media_type = media_types.get(format, "application/json")

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename=meine_daten_{current_user.id}.{extension}"
        },
    )


# ==================== Audit Log Exporte ====================

@router.get("/audit-log")
async def export_audit_log(
    start_date: str,
    end_date: str,
    entity_type: Optional[str] = None,
    user_id: Optional[UUID] = None,
    format: str = "excel",
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(require_role(UserRole.AUDITOR)),
) -> Response:
    """
    Exportiert Audit-Log für Compliance Reports.
    """
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="start_date und end_date müssen im ISO-Format sein",
        )

    data: bytes = await export_service.export_audit_log(
        start_date=start,
        end_date=end,
        entity_type=entity_type,
        user_id=user_id,
        format=format,
    )

    extensions = {
        "excel": "xlsx",
        "csv": "csv",
        "json": "json",
    }
    extension = extensions.get(format, "xlsx")

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename=audit_log_{start_date}_{end_date}.{extension}"
        },
    )


# ==================== Finanzberichte ====================

@router.get("/financial-report/{year}")
async def export_financial_report(
    year: int,
    format: str = "excel",
    export_service: ExportService = Depends(get_export_service),
    current_user: User = Depends(require_role(UserRole.ACCOUNTANT)),
) -> Response:
    """
    Exportiert finanziellen Jahresbericht.
    """
    data: bytes = await export_service.export_financial_report(
        year=year,
        format=format,
    )

    extensions = {
        "excel": "xlsx",
        "csv": "csv",
    }
    media_types = {
        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
    }

    extension = extensions.get(format, "xlsx")
    media_type = media_types.get(format, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename=jahresbericht_{year}.{extension}"
        },
    )


# ==================== Backup Management ====================

@router.post("/backup/create")
async def create_backup(
    backup_type: str = "daily",
    backup_service: WasabiBackupService = Depends(get_backup_service),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """
    Erstellt ein manuelles Backup.
    """
    result = await backup_service.create_full_backup(
        database_url=settings.DATABASE_URL,
        backup_type=backup_type,
        user_id=current_user.id,
    )

    return {
        "backup_id": result["backup_id"],
        "size_mb": result["size_bytes"] / 1024 / 1024,
        "created_at": result["created_at"],
        "checksum": result["checksum"][:16] + "...",
    }


@router.get("/backup/list")
async def list_backups(
    backup_type: str = "daily",
    backup_service: WasabiBackupService = Depends(get_backup_service),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> List[dict]:
    """
    Listet alle verfügbaren Backups auf.
    """
    backups = await backup_service.list_backups(backup_type)

    return [
        {
            "backup_id": b["backup_id"],
            "created_at": b["created_at"],
            "size_mb": b["size_bytes"] / 1024 / 1024,
            "encrypted": b.get("encrypted", False),
        }
        for b in backups
    ]


@router.post("/backup/restore/{backup_id}")
async def restore_backup(
    backup_id: str,
    backup_type: str = "daily",
    backup_service: WasabiBackupService = Depends(get_backup_service),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """
    Stellt ein Backup wieder her (Disaster Recovery).
    """
    success = await backup_service.restore_backup(
        backup_id=backup_id,
        database_url=settings.DATABASE_URL,
        backup_type=backup_type,
    )

    return {
        "success": success,
        "backup_id": backup_id,
        "restored_at": datetime.now(timezone.utc).isoformat(),
        "restored_by": str(current_user.id),
    }


@router.get("/backup/verify/{backup_id}")
async def verify_backup(
    backup_id: str,
    backup_type: str = "daily",
    backup_service: WasabiBackupService = Depends(get_backup_service),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """
    Verifiziert die Integrität eines Backups.
    """
    is_valid = await backup_service.verify_backup_integrity(
        backup_id=backup_id,
        backup_type=backup_type,
    )

    return {
        "backup_id": backup_id,
        "is_valid": is_valid,
        "verified_at": datetime.now(timezone.utc).isoformat(),
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
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> Response:
    """
    Erstellt einen Bulk-Export mit mehreren Berichten als ZIP.
    """
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="start_date und end_date müssen im ISO-Format sein",
        )

    exports: List[bytes] = []
    filenames: List[str] = []

    if include_donations:
        donations_data = await export_service.export_donations(
            start_date=start,
            end_date=end,
            format="excel",
            include_personal_data=True,
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
            format="excel",
        )
        exports.append(audit_data)
        filenames.append(f"audit_log_{start_date}_{end_date}.xlsx")

    zip_data: bytes = await export_service.create_export_archive(exports, filenames)

    return Response(
        content=zip_data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=bulk_export_{start_date}_{end_date}.zip"
        },
    )