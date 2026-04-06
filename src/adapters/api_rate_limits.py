# FILE: src/adapters/api_rate_limits.py
# MODULE: Rate Limiting API Endpoints (Admin)
# Verwaltung von Rate Limits und Circuit Breaker

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from src.adapters.auth import require_role
from src.core.entities.base import UserRole

# Korrekte Imports
from src.services.circuit_breaker_service import CircuitBreakerService

router = APIRouter(prefix="/api/v1/rate-limits", tags=["rate_limits"])

# ==================== Rate Limit Management ====================


@router.get("/status/{key}")
async def get_rate_limit_status(
    key: str,
    request: Request,  # ✅ Request zuerst
    scope: str = "ip",  # ✅ Default danach
    current_user=Depends(require_role(UserRole.ADMIN)),  # ✅ Depends am Ende
):
    """
    Holt aktuellen Rate Limit Status für einen Key
    """
    from src.core.rate_limiting.base import RateLimitConfig, RateLimitScope
    from src.core.rate_limiting.redis_limiter import SlidingWindowRateLimiter

    redis_client = request.app.state.redis
    limiter = SlidingWindowRateLimiter(redis_client)

    config = RateLimitConfig(
        scope=RateLimitScope(scope), strategy="sliding_window", limit=100, window_seconds=60
    )

    current_count = await limiter.get_current_count(key, config)

    return {
        "key": key,
        "scope": scope,
        "current_count": current_count,
        "checked_at": datetime.utcnow().isoformat(),
    }


@router.get("/circuit-breakers")
async def get_circuit_breakers_status(
    request: Request,  # ✅ Request zuerst
    circuit_breaker_service: CircuitBreakerService = Depends(
        get_circuit_breaker_service
    ),  # ✅ Depends
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    """
    Resetet Rate Limit für einen Key
    """
    from src.core.rate_limiting.base import RateLimitConfig, RateLimitScope
    from src.core.rate_limiting.redis_limiter import SlidingWindowRateLimiter

    redis_client = request.app.state.redis
    limiter = SlidingWindowRateLimiter(redis_client)

    config = RateLimitConfig(
        scope=RateLimitScope(scope), strategy="sliding_window", limit=100, window_seconds=60
    )

    await limiter.reset(key, config)

    return {"key": key, "scope": scope, "reset": True, "reset_at": datetime.utcnow().isoformat()}


@router.get("/rules")
async def list_rate_limit_rules(
    request: Request, current_user=Depends(require_role(UserRole.ADMIN))
):
    """
    Listet alle aktiven Rate Limit Regeln
    """
    middleware = None
    for m in request.app.user_middleware:
        if m.cls == RateLimitMiddleware:
            middleware = m
            break

    if middleware and hasattr(middleware, "rules"):
        rules = middleware.rules
        return {
            "rules": [
                {
                    "name": name,
                    "path_pattern": rule.path_pattern,
                    "method": rule.method,
                    "scope": rule.scope.value,
                    "strategy": rule.strategy.value,
                    "limit": rule.limit,
                    "window_seconds": rule.window_seconds,
                    "burst_limit": rule.burst_limit,
                }
                for name, rule in rules.items()
            ]
        }

    return {"rules": []}


# ==================== Circuit Breaker Management ====================


@router.get("/circuit-breakers")
async def get_circuit_breakers_status(
    circuit_breaker_service: CircuitBreakerService = Depends(get_circuit_breaker_service),
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    """
    Holt Status aller Circuit Breaker
    """
    statuses = await circuit_breaker_service.get_all_statuses()
    return statuses


@router.post("/circuit-breakers/{service_name}/open")
async def force_open_circuit_breaker(
    service_name: str,
    circuit_breaker_service: CircuitBreakerService = Depends(get_circuit_breaker_service),
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    """
    Erzwingt Open State für einen Service
    """
    await circuit_breaker_service.force_open(service_name)
    return {
        "service": service_name,
        "action": "forced_open",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/circuit-breakers/{service_name}/close")
async def force_close_circuit_breaker(
    service_name: str,
    circuit_breaker_service: CircuitBreakerService = Depends(get_circuit_breaker_service),
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    """
    Erzwingt Closed State für einen Service
    """
    await circuit_breaker_service.force_close(service_name)
    return {
        "service": service_name,
        "action": "forced_close",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/circuit-breakers/reset")
async def reset_all_circuit_breakers(
    circuit_breaker_service: CircuitBreakerService = Depends(get_circuit_breaker_service),
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    """
    Resetet alle Circuit Breaker
    """
    await circuit_breaker_service.reset_all()
    return {"action": "reset_all", "timestamp": datetime.utcnow().isoformat()}


# ==================== Metrics ====================


@router.get("/metrics")
async def get_rate_limit_metrics(
    request: Request, current_user=Depends(require_role(UserRole.AUDITOR))
):
    """
    Holt Rate Limiting Metriken (für Prometheus)
    """
    redis_client = request.app.state.redis

    # Zähle aktive Rate Limit Keys
    keys = await redis_client.keys("ratelimit:*")

    # Gruppiere nach Typ
    grouped = {}
    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        parts = key_str.split(":")
        if len(parts) > 1:
            type_name = parts[1]
            grouped[type_name] = grouped.get(type_name, 0) + 1

    return {
        "total_active_limits": len(keys),
        "by_type": grouped,
        "timestamp": datetime.utcnow().isoformat(),
    }
