# FILE: src/read_models/project_read_model.py
# MODULE: Project Read Model Event Handler
# Beschreibung: Aktualisiert die Read-Model-Tabellen für Projekte (CQRS)

import logging
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.entities.base import Project, Donation
from src.core.events.event_bus import Event

logger = logging.getLogger(__name__)


class ProjectReadModelEventHandler:
    """
    Event Handler für Projekt-bezogene Events.
    Aktualisiert das Read Model (z.B. Denormalisierte Projekt-Statistiken).
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def handle(self, event: Event):
        """
        Hauptmethode zur Verarbeitung von Events.
        Verteilt an spezifische Handler je nach Event-Typ.
        """
        if event.event_type == "project.created":
            await self._handle_project_created(event)
        elif event.event_type == "project.updated":
            await self._handle_project_updated(event)
        elif event.event_type == "project.completed":
            await self._handle_project_completed(event)
        elif event.event_type == "donation.created":
            await self._handle_donation_created(event)
        else:
            logger.debug(f"Ignoring event type: {event.event_type}")

    async def _handle_project_created(self, event: Event):
        """Neues Projekt in das Read Model aufnehmen"""
        data = event.data
        async with self.session_factory() as session:
            # Prüfen ob bereits vorhanden (idempotent)
            stmt = select(Project).where(Project.id == event.aggregate_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                logger.warning(f"Project {event.aggregate_id} already exists, skipping creation.")
                return

            project = Project(
                id=event.aggregate_id,
                name=data.get("name"),
                description=data.get("description"),
                cost_center=data.get("cost_center"),
                budget_total=data.get("budget_total", 0),
                budget_used=data.get("budget_used", 0),
                donations_total=data.get("donations_total", 0),
                status=data.get("status", "active"),
                start_date=data.get("start_date"),
                end_date=data.get("end_date"),
                skr42_account_id=data.get("skr42_account_id"),
                requires_four_eyes=data.get("requires_four_eyes", True),
                created_at=event.timestamp,
                updated_at=event.timestamp,
            )
            session.add(project)
            await session.commit()
            logger.info(f"Project {event.aggregate_id} created in read model.")

    async def _handle_project_updated(self, event: Event):
        """Projekt-Daten aktualisieren"""
        data = event.data
        async with self.session_factory() as session:
            stmt = (
                update(Project)
                .where(Project.id == event.aggregate_id)
                .values(
                    name=data.get("name"),
                    description=data.get("description"),
                    budget_total=data.get("budget_total"),
                    status=data.get("status"),
                    updated_at=event.timestamp,
                )
            )
            await session.execute(stmt)
            await session.commit()
            logger.info(f"Project {event.aggregate_id} updated in read model.")

    async def _handle_project_completed(self, event: Event):
        """Projekt als abgeschlossen markieren"""
        async with self.session_factory() as session:
            stmt = (
                update(Project)
                .where(Project.id == event.aggregate_id)
                .values(status="completed", updated_at=event.timestamp)
            )
            await session.execute(stmt)
            await session.commit()
            logger.info(f"Project {event.aggregate_id} marked as completed.")

    async def _handle_donation_created(self, event: Event):
        """
        Aktualisiert die Spendensumme eines Projekts im Read Model.
        Das Projekt-Read-Model enthält denormalisierte Spenden-Totale.
        """
        data = event.data
        project_id = data.get("project_id")
        if not project_id:
            logger.warning("Donation event without project_id, skipping.")
            return

        amount = data.get("amount", 0)
        payment_status = data.get("payment_status")

        if payment_status != "succeeded":
            logger.debug(f"Ignoring donation with status {payment_status}")
            return

        async with self.session_factory() as session:
            # Aktuelles Projekt laden
            stmt = select(Project).where(Project.id == project_id)
            result = await session.execute(stmt)
            project = result.scalar_one_or_none()
            if not project:
                logger.warning(f"Project {project_id} not found for donation update.")
                return

            # Neue Spendensumme berechnen
            new_total = (project.donations_total or 0) + amount
            stmt = (
                update(Project)
                .where(Project.id == project_id)
                .values(donations_total=new_total, updated_at=event.timestamp)
            )
            await session.execute(stmt)
            await session.commit()
            logger.info(f"Updated donation total for project {project_id} to {new_total}")
