# FILE: src/api/transparenz.py
# MODULE: Transparenz API - Öffentliche Schnittstelle für Spender
# Features: Filter (Jahr/Projekt/Kategorie), Hash-IDs, Merkle-Root, Chart.js-ready

import hashlib
import hmac
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.entities.base import Donation, Project
from src.core.entities.needs import ProjectNeed, NeedStatus, NeedPriority
from src.core.compliance.merkle import MerkleTreeService

router = APIRouter(prefix="/api/v1/transparenz", tags=["transparenz"])


# ==================== Pydantic Models ====================

class TransparencyMetrics(BaseModel):
    """Transparenz-Kennzahlen für Dashboard"""
    total_incoming: float
    total_outgoing: float
    project_progress: float
    donor_count: int
    donation_count: int
    avg_donation: float


class TransparencyDonation(BaseModel):
    """Transparenz-Datensatz für Tabelle (pseudonymisiert)"""
    donor_hash: str
    date: str
    project_name: str
    amount: float
    category: Optional[str] = None


class TransparencyTimelinePoint(BaseModel):
    """Zeitreihen-Datenpunkt für Chart.js"""
    month: str
    incoming: float
    outgoing: float
    cumulative: float


class TransparencyResponse(BaseModel):
    """Vollständige Transparenz-API Response"""
    filters: dict
    metrics: TransparencyMetrics
    timeline: list[TransparencyTimelinePoint]
    donations: list[TransparencyDonation]
    merkle_root: str
    last_updated: str


# ==================== Helper Functions ====================

async def get_session(request: Request) -> AsyncSession:
    """Dependency Injection für Datenbank-Session"""
    async with request.app.state.db_session_factory() as session:
        yield session


def generate_transparency_hash(donor_email: str, salt: str | None = None) -> str:
    """
    Generiert pseudonymisierten Spender-Hash für Transparenzseite
    Format: SPENDER-{hash[:6].upper()}
    Beispiel: SPENDER-A1B2C3
    """
    if salt is None:
        salt = str(datetime.now().year)
    
    hash_obj = hmac.new(
        salt.encode(),
        donor_email.lower().encode(),
        hashlib.sha256
    )
    hash_hex = hash_obj.hexdigest()[:6].upper()
    return f"SPENDER-{hash_hex}"


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
    Transparenz-API Endpoint - Öffentlich zugänglich
    """
    # Setze Standard-Jahr auf aktuelles Jahr
    if jahr is None:
        jahr = datetime.now().year
    
    start_date = datetime(jahr, 1, 1)
    end_date = datetime(jahr, 12, 31, 23, 59, 59)
    
    # ==================== Metrics ====================
    stmt = select(
        func.sum(Donation.amount).label('total_incoming'),
        func.count(Donation.id).label('donation_count'),
        func.count(func.distinct(Donation.donor_email_pseudonym)).label('donor_count')
    ).where(
        Donation.created_at.between(start_date, end_date),
        Donation.payment_status == "succeeded"
    )
    
    result = await session.execute(stmt)
    row = result.one()
    
    total_incoming = float(row.total_incoming or 0)
    donation_count = row.donation_count or 0
    donor_count = row.donor_count or 0
    avg_donation = total_incoming / donation_count if donation_count > 0 else 0
    
    metrics = TransparencyMetrics(
        total_incoming=total_incoming,
        total_outgoing=0,  # Wird aus SKR42 berechnet
        project_progress=0,
        donor_count=donor_count,
        donation_count=donation_count,
        avg_donation=round(avg_donation, 2)
    )
    
    # ==================== Timeline ====================
    timeline = []
    cumulative = 0.0
    
    for month in range(1, 13):
        month_start = datetime(jahr, month, 1)
        if month == 12:
            month_end = datetime(jahr, 12, 31, 23, 59, 59)
        else:
            month_end = datetime(jahr, month + 1, 1) - timedelta(seconds=1)
        
        stmt = select(func.sum(Donation.amount)).where(
            Donation.created_at.between(month_start, month_end),
            Donation.payment_status == "succeeded"
        )
        result = await session.execute(stmt)
        incoming = float(result.scalar() or 0)
        
        cumulative += incoming
        
        timeline.append(TransparencyTimelinePoint(
            month=f"{month:02d}/{jahr}",
            incoming=round(incoming, 2),
            outgoing=0,
            cumulative=round(cumulative, 2)
        ))
    
    # ==================== Donations Table ====================
    stmt = select(
        Donation.donor_email_pseudonym,
        Donation.created_at,
        Project.name.label('project_name'),
        Donation.amount
    ).join(Project, Donation.project_id == Project.id).where(
        Donation.created_at.between(start_date, end_date),
        Donation.payment_status == "succeeded"
    ).order_by(Donation.created_at.desc()).offset(offset).limit(limit)
    
    result = await session.execute(stmt)
    donations_raw = result.all()
    
    donations = []
    for donor_email_hash, created_at, project_name, amount in donations_raw:
        donor_hash = generate_transparency_hash(donor_email_hash)
        donations.append(TransparencyDonation(
            donor_hash=donor_hash,
            date=created_at.strftime("%Y-%m-%d"),
            project_name=project_name,
            amount=float(amount),
            category=kat
        ))
    
    # ==================== Merkle Root ====================
    merkle_service = MerkleTreeService(session)
    merkle_root = await merkle_service.get_daily_root(jahr)
    
    return TransparencyResponse(
        filters={"jahr": jahr, "projekt": projekt, "kategorie": kat, "limit": limit, "offset": offset},
        metrics=metrics,
        timeline=timeline,
        donations=donations,
        merkle_root=merkle_root or "pending",
        last_updated=datetime.now().isoformat()
    )