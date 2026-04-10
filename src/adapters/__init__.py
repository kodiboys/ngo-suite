# FILE: src/adapters/__init__.py
# FIXED: Nur Kern-Exports, keine Lazy-Loading-Seitenwirkungen

# KEINE app-Importe hier! Nur Auth-Dependencies
from src.adapters.auth import get_current_active_user, get_current_user, require_role

# Nur Dependencies (keine vollständigen Services)
from src.adapters.dependencies import (
    get_accounting_service,
    get_compliance_service,
    get_event_store,
)

__all__ = [
    "get_current_user",
    "get_current_active_user",
    "require_role",
    "get_accounting_service",
    "get_compliance_service",
    "get_event_store",
]
