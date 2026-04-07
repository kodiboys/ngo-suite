# FILE: src/adapters/__init__.py
# MODULE: Adapters Package (API, Auth, etc.)

from src.adapters.api import app
from src.adapters.auth import get_current_user, get_current_active_user, require_role
from src.adapters.dependencies import (
    get_export_service,
    get_backup_service,
    get_compliance_service,
    get_social_service,
    get_inventory_service,
    get_need_fulfillment_service,
    get_payment_service,
    get_audit_service,
    get_accounting_service,
    get_event_store,
    get_subscription_service,
    get_projection_manager,
    get_circuit_breaker_service,
    get_receipt_generator,
    get_balance_generator,
    get_project_report_generator,
)

__all__ = [
    "app",
    "get_current_user",
    "get_current_active_user",
    "require_role",
    "get_export_service",
    "get_backup_service",
    "get_compliance_service",
    "get_social_service",
    "get_inventory_service",
    "get_need_fulfillment_service",
    "get_payment_service",
    "get_audit_service",
    "get_accounting_service",
    "get_event_store",
    "get_subscription_service",
    "get_projection_manager",
    "get_circuit_breaker_service",
    "get_receipt_generator",
    "get_balance_generator",
    "get_project_report_generator",
]