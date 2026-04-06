# FILE: src/adapters/dependencies.py
# MODULE: Zentrale Dependency Injection Funktionen

from fastapi import Request

from src.services.export_service import ExportService
from src.services.backup_service import WasabiBackupService
from src.services.compliance_service import ComplianceService
from src.services.social_service import SocialMediaService
from src.services.inventory_service import InventoryService
from src.services.need_fulfillment_service import NeedFulfillmentService
from src.services.payment_service import PaymentService
from src.services.audit import AuditService
from src.services.accounting import AccountingService
from src.core.events.event_store import EventStoreService, EventSubscriptionService
from src.read_models.projections import ProjectionManager
from src.services.circuit_breaker_service import CircuitBreakerService
from src.services.pdf_generator import (
    DonationReceiptGenerator,
    SKR42BalanceSheetGenerator,
    ProjectReportGenerator
)


def get_export_service(request: Request) -> ExportService:
    db_session_factory = request.app.state.db_session_factory
    redis_client = request.app.state.redis
    return ExportService(db_session_factory, redis_client)


def get_backup_service(request: Request) -> WasabiBackupService:
    redis_client = request.app.state.redis
    return WasabiBackupService(redis_client, None)


async def get_compliance_service(request: Request) -> ComplianceService:
    redis_client = request.app.state.redis
    session_factory = request.app.state.db_session_factory
    event_bus = request.app.state.event_bus
    return ComplianceService(session_factory, redis_client, event_bus)


async def get_social_service(request: Request) -> SocialMediaService:
    redis_client = request.app.state.redis
    session_factory = request.app.state.db_session_factory
    event_bus = request.app.state.event_bus
    return SocialMediaService(session_factory, redis_client, event_bus)


async def get_inventory_service(request: Request) -> InventoryService:
    redis_client = request.app.state.redis
    session_factory = request.app.state.db_session_factory
    event_bus = request.app.state.event_bus
    return InventoryService(session_factory, redis_client, event_bus)


async def get_need_fulfillment_service(request: Request) -> NeedFulfillmentService:
    session_factory = request.app.state.db_session_factory
    event_bus = request.app.state.event_bus
    return NeedFulfillmentService(session_factory, event_bus)


async def get_payment_service(request: Request) -> PaymentService:
    session_factory = request.app.state.db_session_factory
    redis_client = request.app.state.redis
    event_bus = request.app.state.event_bus
    return PaymentService(session_factory, redis_client, event_bus)


async def get_audit_service(request: Request) -> AuditService:
    session_factory = request.app.state.db_session_factory
    return AuditService(session_factory)


async def get_accounting_service(request: Request) -> AccountingService:
    session_factory = request.app.state.db_session_factory
    event_bus = request.app.state.event_bus
    return AccountingService(session_factory, event_bus)


async def get_event_store(request: Request) -> EventStoreService:
    session_factory = request.app.state.db_session_factory
    return EventStoreService(session_factory)


async def get_subscription_service(request: Request) -> EventSubscriptionService:
    session_factory = request.app.state.db_session_factory
    event_store = await get_event_store(request)
    return EventSubscriptionService(session_factory, event_store)


async def get_projection_manager(request: Request) -> ProjectionManager:
    session_factory = request.app.state.db_session_factory
    event_store = await get_event_store(request)
    return ProjectionManager(session_factory, event_store)


async def get_circuit_breaker_service(request: Request) -> CircuitBreakerService:
    redis_client = request.app.state.redis
    return CircuitBreakerService(redis_client)


async def get_receipt_generator(request: Request) -> DonationReceiptGenerator:
    session_factory = request.app.state.db_session_factory
    return DonationReceiptGenerator(session_factory)


async def get_balance_generator(request: Request) -> SKR42BalanceSheetGenerator:
    session_factory = request.app.state.db_session_factory
    return SKR42BalanceSheetGenerator(session_factory)


async def get_project_report_generator(request: Request) -> ProjectReportGenerator:
    session_factory = request.app.state.db_session_factory
    return ProjectReportGenerator(session_factory)