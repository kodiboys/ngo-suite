# FILE: src/api/transparenz.py
# MODULE: Transparenz API - Öffentliche Schnittstelle für Spender
# Features: Filter (Jahr/Projekt/Kategorie), Hash-IDs, Merkle-Root, Chart.js-ready

import hashlib
import hmac
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, or_, extract
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.entities.base import Donation, Project, get_session
from src.core.entities.needs import ProjectNeed, NeedStatus, NeedPriority
from src.core.compliance.merkle import MerkleTreeService
from src.middleware.rate_limit_middleware import RateLimitMiddleware

router = APIRouter(prefix="/api/v1/transparenz", tags=["transparenz"])


# ==================== Pydantic Models ====================

class TransparencyMetrics(BaseModel):
    """Transparenz-Kennzahlen für Dashboard"""
    total_incoming: float = Field(..., description="Gesamteingänge (EUR)")
    total_outgoing: float = Field(..., description="Gesamtausgaben (EUR)")
    project_progress: float = Field(..., description="Projektfortschritt (%)")
    donor_count: int = Field(..., description="Anzahl Spender")
    donation_count: int = Field(..., description="Anzahl Spenden")
    avg_donation: float = Field(..., description="Durchschnittsspende (EUR)")


class TransparencyDonation(BaseModel):
    """Transparenz-Datensatz für Tabelle (pseudonymisiert)"""
    donor_hash: str = Field(..., description="Pseudonymisierter Spender (z.B. SPENDER-A1B2C3)")
    date: str = Field(..., description="Datum (YYYY-MM-DD)")
    project_name: str = Field(..., description="Projektname")
    amount: float = Field(..., description="Spendenbetrag (EUR)")
    category: Optional[str] = Field(None, description="Kategorie")


class TransparencyTimelinePoint(BaseModel):
    """Zeitreihen-Datenpunkt für Chart.js"""
    month: str = Field(..., description="Monat (MM/YYYY)")
    incoming: float = Field(..., description="Eingänge (EUR)")
    outgoing: float = Field(..., description="Ausgaben (EUR)")
    cumulative: float = Field(..., description="Kumulierte Summe (EUR)")


class TransparencyResponse(BaseModel):
    """Vollständige Transparenz-API Response"""
    filters: Dict[str, Any] = Field(..., description="Angewendete Filter")
    metrics: TransparencyMetrics = Field(..., description="Kennzahlen")
    timeline: List[TransparencyTimelinePoint] = Field(..., description="Zeitreihe")
    donations: List[TransparencyDonation] = Field(..., description="Spendentabelle")
    merkle_root: str = Field(..., description="Aktueller Merkle-Root Hash")
    last_updated: str = Field(..., description="Letzte Aktualisierung")


# ==================== Helper Functions ====================

def generate_transparency_hash(donor_email: str, salt: str = None) -> str:
    """
    Generiert pseudonymisierten Spender-Hash für Transparenzseite
    Format: SPENDER-{hash[:6].upper()}
    Beispiel: SPENDER-A1B2C3
    """
    if salt is None:
        salt = datetime.now().strftime("%Y")  # Jährlicher Salt
    
    # HMAC-SHA256 für zusätzliche Sicherheit
    hash_obj = hmac.new(
        salt.encode(),
        donor_email.lower().encode(),
        hashlib.sha256
    )
    hash_hex = hash_obj.hexdigest()[:6].upper()
    return f"SPENDER-{hash_hex}"


async def calculate_project_progress(
    session: AsyncSession,
    project_id: UUID,
    year: int
) -> float:
    """Berechnet Projektfortschritt basierend auf Spenden vs Budget"""
    # Summiere Spenden für das Projekt im Jahr
    stmt = select(func.sum(Donation.amount)).where(
        Donation.project_id == project_id,
        extract('year', Donation.created_at) == year,
        Donation.payment_status == "succeeded"
    )
    result = await session.execute(stmt)
    total_donated = result.scalar() or Decimal(0)
    
    # Hole Projektbudget
    stmt = select(Project.budget_total).where(Project.id == project_id)
    result = await session.execute(stmt)
    budget = result.scalar() or Decimal(1)
    
    return float((total_donated / budget) * 100)


# ==================== Main Endpoint ====================

@router.get("")
@router.get("/")
async def get_transparency_data(
    request: Request,
    jahr: Optional[int] = Query(None, description="Filter nach Jahr", ge=2020, le=2030),
    projekt: Optional[str] = Query(None, description="Filter nach Projekt (Name oder ID)"),
    kat: Optional[str] = Query(None, description="Filter nach Kategorie"),
    limit: int = Query(100, description="Max. Anzahl Spenden", ge=1, le=1000),
    offset: int = Query(0, description="Offset für Paginierung", ge=0),
    session: AsyncSession = Depends(get_session)
) -> TransparencyResponse:
    """
    Transparenz-API Endpoint
    
    Öffentlich zugänglich (Rate-Limited: 100 req/min)
    Liefert pseudonymisierte Spendedaten für Transparenzseite
    
    Filter:
    - jahr: Jahr der Spenden
    - projekt: Projektname oder ID
    - kat: Kategorie (optional, für zukünftige Erweiterung)
    """
    
    # Setze Standard-Jahr auf aktuelles Jahr
    if jahr is None:
        jahr = datetime.now().year
    
    start_date = datetime(jahr, 1, 1)
    end_date = datetime(jahr, 12, 31, 23, 59, 59)
    
    # ==================== 1. Metrics berechnen ====================
    
    # Gesamteingänge (succeeded donations)
    stmt = select(
        func.sum(Donation.amount).label('total_incoming'),
        func.count(Donation.id).label('donation_count'),
        func.count(func.distinct(Donation.donor_email_pseudonym)).label('donor_count')
    ).where(
        Donation.created_at.between(start_date, end_date),
        Donation.payment_status == "succeeded"
    )
    
    if projekt:
        # Versuche als UUID oder als Name
        try:
            project_uuid = UUID(projekt)
            stmt = stmt.where(Donation.project_id == project_uuid)
        except ValueError:
            # Projektname
            stmt = stmt.join(Project).where(Project.name.ilike(f"%{projekt}%"))
    
    result = await session.execute(stmt)
    row = result.one()
    
    total_incoming = float(row.total_incoming or 0)
    donation_count = row.donation_count or 0
    donor_count = row.donor_count or 0
    avg_donation = total_incoming / donation_count if donation_count > 0 else 0
    
    # Gesamtausgaben (approved expenses aus Project)
    stmt = select(func.sum(Project.budget_used)).where(
        extract('year', Project.updated_at) == jahr
    )
    if projekt:
        try:
            project_uuid = UUID(projekt)
            stmt = stmt.where(Project.id == project_uuid)
        except ValueError:
            stmt = stmt.where(Project.name.ilike(f"%{projekt}%"))
    
    result = await session.execute(stmt)
    total_outgoing = float(result.scalar() or 0)
    
    # Projektfortschritt
    project_progress = 0.0
    if projekt:
        try:
            project_uuid = UUID(projekt)
            project_progress = await calculate_project_progress(session, project_uuid, jahr)
        except ValueError:
            # Projektname - finde erste Projekt-ID
            stmt = select(Project.id).where(Project.name.ilike(f"%{projekt}%"))
            result = await session.execute(stmt)
            project_id = result.scalar_one_or_none()
            if project_id:
                project_progress = await calculate_project_progress(session, project_id, jahr)
    else:
        # Durchschnitt aller Projekte
        stmt = select(Project.id)
        result = await session.execute(stmt)
        project_ids = result.scalars().all()
        if project_ids:
            progress_sum = 0
            for pid in project_ids:
                progress_sum += await calculate_project_progress(session, pid, jahr)
            project_progress = progress_sum / len(project_ids)
    
    metrics = TransparencyMetrics(
        total_incoming=total_incoming,
        total_outgoing=total_outgoing,
        project_progress=round(project_progress, 1),
        donor_count=donor_count,
        donation_count=donation_count,
        avg_donation=round(avg_donation, 2)
    )
    
    # ==================== 2. Timeline Daten (Chart.js) ====================
    
    timeline = []
    cumulative = 0.0
    
    for month in range(1, 13):
        month_start = datetime(jahr, month, 1)
        if month == 12:
            month_end = datetime(jahr, 12, 31, 23, 59, 59)
        else:
            month_end = datetime(jahr, month + 1, 1) - timedelta(seconds=1)
        
        # Monatliche Eingänge
        stmt = select(func.sum(Donation.amount)).where(
            Donation.created_at.between(month_start, month_end),
            Donation.payment_status == "succeeded"
        )
        if projekt:
            try:
                project_uuid = UUID(projekt)
                stmt = stmt.where(Donation.project_id == project_uuid)
            except ValueError:
                stmt = stmt.join(Project).where(Project.name.ilike(f"%{projekt}%"))
        
        result = await session.execute(stmt)
        incoming = float(result.scalar() or 0)
        
        # Monatliche Ausgaben (vereinfacht: budget_used Änderungen)
        # In Production: Detaillierte Ausgaben aus SKR42
        outgoing = (total_outgoing / 12) if total_outgoing > 0 else 0
        
        cumulative += incoming - outgoing
        
        timeline.append(TransparencyTimelinePoint(
            month=f"{month:02d}/{jahr}",
            incoming=round(incoming, 2),
            outgoing=round(outgoing, 2),
            cumulative=round(cumulative, 2)
        ))
    
    # ==================== 3. Spendentabelle (pseudonymisiert) ====================
    
    stmt = select(
        Donation.donor_email_pseudonym,
        Donation.created_at,
        Project.name.label('project_name'),
        Donation.amount
    ).join(Project, Donation.project_id == Project.id).where(
        Donation.created_at.between(start_date, end_date),
        Donation.payment_status == "succeeded"
    ).order_by(Donation.created_at.desc()).offset(offset).limit(limit)
    
    if projekt:
        try:
            project_uuid = UUID(projekt)
            stmt = stmt.where(Donation.project_id == project_uuid)
        except ValueError:
            stmt = stmt.where(Project.name.ilike(f"%{projekt}%"))
    
    result = await session.execute(stmt)
    donations_raw = result.all()
    
    donations = []
    for donor_email_hash, created_at, project_name, amount in donations_raw:
        # Generiere lesbaren Hash für Transparenzseite
        donor_hash = generate_transparency_hash(donor_email_hash)
        
        donations.append(TransparencyDonation(
            donor_hash=donor_hash,
            date=created_at.strftime("%Y-%m-%d"),
            project_name=project_name,
            amount=float(amount),
            category=kat
        ))
    
    # ==================== 4. Merkle-Root für Integrität ====================
    
    merkle_service = MerkleTreeService(session)
    merkle_root = await merkle_service.get_daily_root(jahr)
    
    return TransparencyResponse(
        filters={
            "jahr": jahr,
            "projekt": projekt,
            "kategorie": kat,
            "limit": limit,
            "offset": offset
        },
        metrics=metrics,
        timeline=timeline,
        donations=donations,
        merkle_root=merkle_root or "pending",
        last_updated=datetime.now().isoformat()
    )


# ==================== Projekt-Bedarfe Endpoint ====================

class ProjectNeedResponse(BaseModel):
    """Bedarfs-Response für Projektseite"""
    id: str
    name: str
    description: Optional[str]
    category: str
    priority: str
    quantity_target: int
    quantity_current: int
    quantity_remaining: int
    progress_percent: float
    unit: Optional[str]
    status: str


@router.get("/needs/{project_id}")
async def get_project_needs(
    project_id: UUID,
    category: Optional[str] = Query(None, description="Filter nach Kategorie"),
    priority: Optional[str] = Query(None, description="Filter nach Priorität"),
    session: AsyncSession = Depends(get_session)
) -> List[ProjectNeedResponse]:
    """
    Öffentlicher Endpoint für Projekt-Bedarfe
    Zeigt aktuelle Bedarfe eines Projekts an
    """
    stmt = select(ProjectNeed).where(
        ProjectNeed.project_id == project_id,
        ProjectNeed.status == "active"
    )
    
    if category:
        stmt = stmt.where(ProjectNeed.category == category)
    if priority:
        stmt = stmt.where(ProjectNeed.priority == priority)
    
    stmt = stmt.order_by(
        # Critical zuerst
        ProjectNeed.priority.desc(),
        ProjectNeed.category
    )
    
    result = await session.execute(stmt)
    needs = result.scalars().all()
    
    return [
        ProjectNeedResponse(
            id=str(need.id),
            name=need.name,
            description=need.description,
            category=need.category,
            priority=need.priority,
            quantity_target=need.quantity_target,
            quantity_current=need.quantity_current,
            quantity_remaining=need.quantity_target - need.quantity_current,
            progress_percent=round((need.quantity_current / need.quantity_target) * 100, 1),
            unit=need.unit,
            status=need.status
        )
        for need in needs
    ]


# ==================== Projekt-Liste Endpoint ====================

@router.get("/projects")
async def get_transparency_projects(
    year: Optional[int] = Query(None, description="Jahr für Statistiken"),
    session: AsyncSession = Depends(get_session)
) -> List[Dict[str, Any]]:
    """
    Öffentlicher Endpoint für Projekt-Liste mit Transparenz-Statistiken
    """
    if year is None:
        year = datetime.now().year
    
    start_date = datetime(year, 1, 1)
    end_date = datetime(year, 12, 31, 23, 59, 59)
    
    stmt = select(Project).where(Project.status == "active")
    result = await session.execute(stmt)
    projects = result.scalars().all()
    
    project_data = []
    for project in projects:
        # Summiere Spenden für dieses Projekt im Jahr
        stmt = select(func.sum(Donation.amount)).where(
            Donation.project_id == project.id,
            Donation.created_at.between(start_date, end_date),
            Donation.payment_status == "succeeded"
        )
        result = await session.execute(stmt)
        total_donated = float(result.scalar() or 0)
        
        # Zähle Spender
        stmt = select(func.count(func.distinct(Donation.donor_email_pseudonym))).where(
            Donation.project_id == project.id,
            Donation.created_at.between(start_date, end_date),
            Donation.payment_status == "succeeded"
        )
        result = await session.execute(stmt)
        donor_count = result.scalar() or 0
        
        project_data.append({
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "budget_total": float(project.budget_total),
            "donations_total": total_donated,
            "progress_percent": round((total_donated / float(project.budget_total)) * 100, 1) if project.budget_total > 0 else 0,
            "donor_count": donor_count,
            "status": project.status,
            "image_url": getattr(project, 'image_url', None)
        })
    
    return project_data
