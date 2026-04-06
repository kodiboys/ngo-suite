# FILE: src/read_models/donation_read_model.py
# MODULE: Donation Read Model für CQRS
# Denormalisierte Tabelle für schnelle Leseoperationen

# 1. Standard-Library Imports
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
import logging
from decimal import Decimal  # WICHTIG: Hier hinzufügen, sonst stürzt der EventHandler ab!

# 2. Third-Party Imports (SQLAlchemy)
from sqlalchemy import (
    Column, String, DateTime, Numeric, Boolean, Index, Integer, func, select
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID

# 3. Local Application Imports
from src.core.entities.base import Base
from src.core.events.event_store import DomainEvent

# 4. Variablen-Zuweisungen (Logger erst JETZT)
logger = logging.getLogger(__name__)

class DonationReadModel(Base):
    """
    Denormalisierte Read Model Tabelle für Spenden
    Optimiert für schnelle Leseoperationen und Reporting
    """

    __tablename__ = "donations_read_model"
    __table_args__ = (
        Index("idx_donation_amount", "amount"),
        Index("idx_donation_project_status", "project_id", "status"),
        Index("idx_donation_date", "created_at"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    project_id = Column(PGUUID(as_uuid=True), nullable=False)
    project_name = Column(String(200), nullable=True)  # Denormalisiert

    # Donor (pseudonymisiert)
    donor_email_hash = Column(String(255), nullable=True)
    donor_name = Column(String(200), nullable=True)

    # Finanzen
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="EUR")

    # Status
    status = Column(String(50), nullable=False, default="pending")
    payment_provider = Column(String(20), nullable=True)
    payment_intent_id = Column(String(255), nullable=True)

    # Compliance
    compliance_status = Column(String(50), default="pending")
    money_laundering_risk = Column(String(20), nullable=True)

    # Steuer
    donation_receipt_generated = Column(Boolean, default=False)
    receipt_number = Column(String(50), nullable=True)

    # Denormalisierte Statistiken
    donor_total_donations = Column(Numeric(12, 2), default=0)
    donor_donation_count = Column(Integer, default=0)

    # Versionierung (für CQRS)
    last_event_version = Column(Integer, default=0)
    last_event_id = Column(PGUUID(as_uuid=True), nullable=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DonationReadModelRepository:
    """
    Repository für Donation Read Model
    Bietet optimierte Leseoperationen
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def get_by_id(self, donation_id: UUID) -> DonationReadModel | None:
        """Holt Spende nach ID"""
        async with self.session_factory() as session:
            stmt = select(DonationReadModel).where(DonationReadModel.id == donation_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_by_project(
        self, project_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[DonationReadModel]:
        """Holt alle Spenden eines Projekts"""
        async with self.session_factory() as session:
            stmt = (
                select(DonationReadModel)
                .where(DonationReadModel.project_id == project_id)
                .order_by(DonationReadModel.created_at.desc())
                .offset(offset)
                .limit(limit)
            )

            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_donations_by_date_range(
        self, start_date: datetime, end_date: datetime, project_id: UUID | None = None
    ) -> list[DonationReadModel]:
        """Holt Spenden im Zeitraum"""
        async with self.session_factory() as session:
            stmt = select(DonationReadModel).where(
                DonationReadModel.created_at.between(start_date, end_date)
            )

            if project_id:
                stmt = stmt.where(DonationReadModel.project_id == project_id)

            stmt = stmt.order_by(DonationReadModel.created_at)

            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_donation_stats(
        self, project_id: UUID | None = None, year: int | None = None
    ) -> dict[str, Any]:
        """Holt aggregierte Statistiken"""
        async with self.session_factory() as session:
            stmt = select(
                func.sum(DonationReadModel.amount).label("total_amount"),
                func.count(DonationReadModel.id).label("total_count"),
                func.avg(DonationReadModel.amount).label("avg_amount"),
                func.max(DonationReadModel.amount).label("max_amount"),
                func.min(DonationReadModel.amount).label("min_amount"),
            ).where(DonationReadModel.status == "succeeded")

            if project_id:
                stmt = stmt.where(DonationReadModel.project_id == project_id)

            if year:
                stmt = stmt.where(func.extract("year", DonationReadModel.created_at) == year)

            result = await session.execute(stmt)
            row = result.one()

            return {
                "total_amount": float(row.total_amount or 0),
                "total_count": row.total_count or 0,
                "average_amount": float(row.avg_amount or 0),
                "max_amount": float(row.max_amount or 0),
                "min_amount": float(row.min_amount or 0),
            }

    async def get_donor_history(self, donor_email_hash: str) -> list[DonationReadModel]:
        """Holt Spenden-History eines Spenders"""
        async with self.session_factory() as session:
            stmt = (
                select(DonationReadModel)
                .where(DonationReadModel.donor_email_hash == donor_email_hash)
                .order_by(DonationReadModel.created_at.desc())
            )

            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_daily_donations(self, days: int = 30) -> list[dict[str, Any]]:
        """Holt tägliche Spenden für Chart"""
        async with self.session_factory() as session:
            stmt = (
                select(
                    func.date(DonationReadModel.created_at).label("date"),
                    func.sum(DonationReadModel.amount).label("total"),
                    func.count(DonationReadModel.id).label("count"),
                )
                .where(
                    DonationReadModel.created_at >= datetime.utcnow() - timedelta(days=days),
                    DonationReadModel.status == "succeeded",
                )
                .group_by(func.date(DonationReadModel.created_at))
            )

            result = await session.execute(stmt)
            return [{"date": r.date, "total": float(r.total), "count": r.count} for r in result]


# ==================== Event Handlers für Read Model ====================


class DonationReadModelEventHandler:
    """
    Event Handler für Donation Read Model
    Aktualisiert das Read Model basierend auf Events
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def handle_donation_created(self, event: DomainEvent):
        """Handler für DonationCreated Event"""
        async with self.session_factory() as session:
            data = event.data

            donation = DonationReadModel(
                id=event.aggregate_id,
                project_id=UUID(data.get("project_id")),
                amount=Decimal(str(data.get("amount"))),
                currency=data.get("currency", "EUR"),
                status="pending",
                payment_provider=data.get("payment_provider"),
                payment_intent_id=data.get("payment_intent_id"),
                donor_email_hash=data.get("donor_email_hash"),
                donor_name=data.get("donor_name"),
                last_event_version=event.sequence_number,
                last_event_id=event.event_id,
            )

            session.add(donation)
            await session.commit()

            logger.debug(f"Read model updated for donation {event.aggregate_id}: created")

    async def handle_donation_confirmed(self, event: DomainEvent):
        """Handler für DonationConfirmed Event"""
        async with self.session_factory() as session:
            stmt = select(DonationReadModel).where(DonationReadModel.id == event.aggregate_id)
            result = await session.execute(stmt)
            donation = result.scalar_one_or_none()

            if donation:
                donation.status = "succeeded"
                donation.last_event_version = event.sequence_number
                donation.last_event_id = event.event_id
                donation.updated_at = datetime.utcnow()

                await session.commit()

                logger.debug(f"Read model updated for donation {event.aggregate_id}: confirmed")

    async def handle_donation_refunded(self, event: DomainEvent):
        """Handler für DonationRefunded Event"""
        async with self.session_factory() as session:
            stmt = select(DonationReadModel).where(DonationReadModel.id == event.aggregate_id)
            result = await session.execute(stmt)
            donation = result.scalar_one_or_none()

            if donation:
                donation.status = "refunded"
                donation.last_event_version = event.sequence_number
                donation.last_event_id = event.event_id
                donation.updated_at = datetime.utcnow()

                await session.commit()

                logger.debug(f"Read model updated for donation {event.aggregate_id}: refunded")


# ==================== Project Read Model ====================


class ProjectReadModel(Base):
    """Denormalisierte Read Model Tabelle für Projekte"""

    __tablename__ = "projects_read_model"

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(String(500))

    # Finanzkennzahlen (denormalisiert)
    budget_total = Column(Numeric(12, 2), default=0)
    donations_total = Column(Numeric(12, 2), default=0)
    donations_count = Column(Integer, default=0)
    average_donation = Column(Numeric(12, 2), default=0)

    # Fortschritt
    progress_percentage = Column(Numeric(5, 2), default=0)

    # Status
    status = Column(String(20), default="active")
    start_date = Column(DateTime)
    end_date = Column(DateTime, nullable=True)

    # Denormalisierte Statistiken
    last_donation_at = Column(DateTime, nullable=True)
    last_donation_amount = Column(Numeric(12, 2), nullable=True)

    # Versionierung
    last_event_version = Column(Integer, default=0)
    last_event_id = Column(PGUUID(as_uuid=True), nullable=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProjectReadModelEventHandler:
    """Event Handler für Project Read Model"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def handle_project_created(self, event: DomainEvent):
        """Handler für ProjectCreated Event"""
        async with self.session_factory() as session:
            data = event.data

            project = ProjectReadModel(
                id=event.aggregate_id,
                name=data.get("name"),
                description=data.get("description"),
                budget_total=Decimal(str(data.get("budget_total", 0))),
                start_date=(
                    datetime.fromisoformat(data.get("start_date"))
                    if data.get("start_date")
                    else datetime.utcnow()
                ),
                status=data.get("status", "active"),
                last_event_version=event.sequence_number,
                last_event_id=event.event_id,
            )

            session.add(project)
            await session.commit()

            logger.debug(f"Read model updated for project {event.aggregate_id}: created")

    async def handle_donation_succeeded(self, event: DomainEvent):
        """Handler für DonationSucceeded Event (aktualisiert Projekt-Statistiken)"""
        async with self.session_factory() as session:
            data = event.data
            project_id = UUID(data.get("project_id"))
            amount = Decimal(str(data.get("amount")))

            stmt = select(ProjectReadModel).where(ProjectReadModel.id == project_id)
            result = await session.execute(stmt)
            project = result.scalar_one_or_none()

            if project:
                # Aktualisiere Statistiken
                project.donations_total += amount
                project.donations_count += 1
                project.average_donation = project.donations_total / project.donations_count
                project.progress_percentage = (
                    (project.donations_total / project.budget_total) * 100
                    if project.budget_total > 0
                    else 0
                )
                project.last_donation_at = datetime.utcnow()
                project.last_donation_amount = amount
                project.last_event_version = event.sequence_number
                project.last_event_id = event.event_id
                project.updated_at = datetime.utcnow()

                await session.commit()

                logger.debug(f"Read model updated for project {project_id}: donation added")