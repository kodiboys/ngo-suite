# FILE: src/read_models/projections.py
# MODULE: Event Projections für CQRS
# Verarbeitet Events und aktualisiert Read Models

import asyncio
import logging
from typing import Any

from src.core.events.event_store import EventStoreService, EventSubscriptionService
from src.read_models.donation_read_model import (
    DonationReadModelEventHandler,
    DonationReadModelRepository,
)
from src.read_models.project_read_model import ProjectReadModelEventHandler

logger = logging.getLogger(__name__)


class ProjectionManager:
    """
    Projection Manager für CQRS
    Verwaltet alle Event-Projections und deren Subscriptions
    """

    def __init__(self, session_factory, event_store: EventStoreService):
        self.session_factory = session_factory
        self.event_store = event_store
        self.subscription_service = EventSubscriptionService(session_factory, event_store)

        # Initialisiere Event Handler
        self.donation_handler = DonationReadModelEventHandler(session_factory)
        self.project_handler = ProjectReadModelEventHandler(session_factory)

        # Registriere Subscriptions
        self._register_subscriptions()

    def _register_subscriptions(self):
        """Registriert alle Event Subscriptions"""

        # Donation Read Model Subscription
        self.subscription_service.subscribe("donation_read_model", self._handle_donation_events)

        # Project Read Model Subscription
        self.subscription_service.subscribe("project_read_model", self._handle_project_events)

        # Analytics Read Model Subscription
        self.subscription_service.subscribe("analytics_read_model", self._handle_analytics_events)

    async def _handle_donation_events(self, event):
        """Dispatcher für Donation Events"""
        handlers = {
            "donation.created": self.donation_handler.handle_donation_created,
            "donation.confirmed": self.donation_handler.handle_donation_confirmed,
            "donation.refunded": self.donation_handler.handle_donation_refunded,
        }

        handler = handlers.get(event.event_type)
        if handler:
            await handler(event)

    async def _handle_project_events(self, event):
        """Dispatcher für Project Events"""
        handlers = {
            "project.created": self.project_handler.handle_project_created,
            "payment.succeeded": self.project_handler.handle_donation_succeeded,
        }

        handler = handlers.get(event.event_type)
        if handler:
            await handler(event)

    async def _handle_analytics_events(self, event):
        """Handler für Analytics Read Model"""
        # Hier könnten weitere Analytics-Daten aggregiert werden
        pass

    async def start_processing(self, interval_seconds: int = 5):
        """
        Startet die kontinuierliche Verarbeitung von Events
        Läuft als Background Task
        """
        logger.info("Starting projection processing...")

        while True:
            try:
                # Verarbeite Donation Read Model
                await self.subscription_service.process_events("donation_read_model")

                # Verarbeite Project Read Model
                await self.subscription_service.process_events("project_read_model")

                # Verarbeite Analytics Read Model
                await self.subscription_service.process_events("analytics_read_model")

            except Exception as e:
                logger.error(f"Error in projection processing: {e}")

            await asyncio.sleep(interval_seconds)

    async def rebuild_all_read_models(self):
        """
        Rebuildet alle Read Models komplett neu
        (Für Schema-Änderungen oder Datenkorrekturen)
        """
        logger.info("Rebuilding all read models...")

        # Lösche Read Model Tabellen
        await self._clear_read_models()

        # Rebuild Subscriptions
        await self.subscription_service.rebuild_read_model("donation_read_model")
        await self.subscription_service.rebuild_read_model("project_read_model")
        await self.subscription_service.rebuild_read_model("analytics_read_model")

        logger.info("All read models rebuilt successfully")

    async def _clear_read_models(self):
        """Löscht alle Read Model Tabellen"""
        async with self.session_factory() as session:
            await session.execute("TRUNCATE TABLE donations_read_model CASCADE")
            await session.execute("TRUNCATE TABLE projects_read_model CASCADE")
            await session.commit()

            logger.info("Read model tables truncated")


# ==================== Analytics Read Model ====================


class AnalyticsReadModel:
    """
    Analytics Read Model für Dashboard und Reports
    Aggregiert Daten aus verschiedenen Quellen
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.donation_repo = DonationReadModelRepository(session_factory)

    async def get_dashboard_data(self) -> dict[str, Any]:
        """Holt alle Daten für das Dashboard"""
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        datetime(now.year, 1, 1)
        start_of_month = datetime(now.year, now.month, 1)
        start_of_week = now - timedelta(days=now.weekday())

        # Aktuelle Jahresstatistiken
        yearly_stats = await self.donation_repo.get_donation_stats(year=now.year)

        # Monatliche Statistiken
        monthly_stats = await self.donation_repo.get_donations_by_date_range(start_of_month, now)

        # Wöchentliche Statistiken
        weekly_stats = await self.donation_repo.get_donations_by_date_range(start_of_week, now)

        # Tägliche Spenden für Chart
        daily_donations = await self.donation_repo.get_daily_donations(days=30)

        return {
            "year_to_date": {
                "total_amount": yearly_stats["total_amount"],
                "total_count": yearly_stats["total_count"],
                "average_donation": yearly_stats["average_amount"],
            },
            "this_month": {
                "total_amount": sum(d.amount for d in monthly_stats),
                "total_count": len(monthly_stats),
            },
            "this_week": {
                "total_amount": sum(d.amount for d in weekly_stats),
                "total_count": len(weekly_stats),
            },
            "daily_trend": daily_donations,
            "generated_at": now.isoformat(),
        }
