# FILE: src/services/circuit_breaker_service.py
# MODULE: Circuit Breaker Service für externe Services
# Schutz für Stripe, PayPal, Klarna, Social Media APIs

import logging
from typing import Any

from src.core.rate_limiting.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenException,
    CircuitBreakerRegistry,
)

logger = logging.getLogger(__name__)


class CircuitBreakerService:
    """
    Circuit Breaker Service für externe Abhängigkeiten
    Verwaltet Circuit Breaker für:
    - Stripe API
    - PayPal API
    - Klarna API
    - Twitter API
    - Facebook API
    - LinkedIn API
    - Wasabi S3
    - VIES (Steuerprüfung)
    """

    def __init__(self, redis_client):
        self.redis = redis_client
        self.registry = CircuitBreakerRegistry(redis_client)

        # Circuit Breaker Konfigurationen
        self.configs = {
            "stripe": CircuitBreakerConfig(
                name="stripe",
                failure_threshold=5,
                success_threshold=2,
                timeout_seconds=60,
                half_open_max_calls=3,
                rolling_window_seconds=120,
                exclude_exceptions=["stripe.error.CardError", "stripe.error.InvalidRequestError"]
            ),
            "paypal": CircuitBreakerConfig(
                name="paypal",
                failure_threshold=5,
                success_threshold=2,
                timeout_seconds=60,
                half_open_max_calls=3,
                rolling_window_seconds=120
            ),
            "klarna": CircuitBreakerConfig(
                name="klarna",
                failure_threshold=5,
                success_threshold=2,
                timeout_seconds=60,
                half_open_max_calls=3,
                rolling_window_seconds=120
            ),
            "twitter": CircuitBreakerConfig(
                name="twitter",
                failure_threshold=10,
                success_threshold=3,
                timeout_seconds=120,
                half_open_max_calls=5,
                rolling_window_seconds=300
            ),
            "facebook": CircuitBreakerConfig(
                name="facebook",
                failure_threshold=10,
                success_threshold=3,
                timeout_seconds=120,
                half_open_max_calls=5,
                rolling_window_seconds=300
            ),
            "linkedin": CircuitBreakerConfig(
                name="linkedin",
                failure_threshold=8,
                success_threshold=3,
                timeout_seconds=90,
                half_open_max_calls=4,
                rolling_window_seconds=240
            ),
            "wasabi": CircuitBreakerConfig(
                name="wasabi",
                failure_threshold=3,
                success_threshold=1,
                timeout_seconds=30,
                half_open_max_calls=2,
                rolling_window_seconds=60,
                exclude_exceptions=["botocore.exceptions.ClientError"]
            ),
            "vies": CircuitBreakerConfig(
                name="vies",
                failure_threshold=5,
                success_threshold=2,
                timeout_seconds=60,
                half_open_max_calls=3,
                rolling_window_seconds=120
            )
        }

    def get_breaker(self, service_name: str) -> CircuitBreaker:
        """Holt Circuit Breaker für Service"""
        config = self.configs.get(service_name)
        if not config:
            # Default Config
            config = CircuitBreakerConfig(
                name=service_name,
                failure_threshold=5,
                success_threshold=2,
                timeout_seconds=60,
                half_open_max_calls=3,
                rolling_window_seconds=120
            )

        return self.registry.get_or_create(config)

    async def call_with_circuit_breaker(
        self,
        service_name: str,
        func,
        *args,
        fallback: callable | None = None,
        **kwargs
    ) -> Any:
        """
        Führt eine Funktion mit Circuit Breaker Schutz aus
        """
        breaker = self.get_breaker(service_name)

        try:
            return await breaker.call(func, *args, fallback=fallback, **kwargs)
        except CircuitBreakerOpenException as e:
            logger.error(f"Circuit breaker open for {service_name}: {e}")
            if fallback:
                return await fallback(*args, **kwargs)
            raise

    async def get_all_statuses(self) -> dict[str, dict[str, Any]]:
        """Holt Status aller Circuit Breaker"""
        statuses = await self.registry.get_all_statuses()

        result = {}
        for key, status in statuses.items():
            result[key] = {
                "state": status.state.value,
                "failure_count": status.failure_count,
                "success_count": status.success_count,
                "last_failure_at": status.last_failure_at.isoformat() if status.last_failure_at else None,
                "last_success_at": status.last_success_at.isoformat() if status.last_success_at else None,
                "open_until": status.open_until.isoformat() if status.open_until else None,
                "total_failures": status.total_failures,
                "total_successes": status.total_successes
            }

        return result

    async def force_open(self, service_name: str):
        """Erzwingt Open State für einen Service"""
        breaker = self.get_breaker(service_name)
        await breaker.force_open()
        logger.warning(f"Circuit breaker {service_name} manually forced to OPEN")

    async def force_close(self, service_name: str):
        """Erzwingt Closed State für einen Service"""
        breaker = self.get_breaker(service_name)
        await breaker.force_close()
        logger.info(f"Circuit breaker {service_name} manually forced to CLOSED")

    async def reset_all(self):
        """Resetet alle Circuit Breaker"""
        await self.registry.reset_all()
        logger.info("All circuit breakers reset")


# ==================== Decorator für Circuit Breaker ====================

def with_circuit_breaker(service_name: str, fallback_func: callable | None = None):
    """
    Decorator für Circuit Breaker Schutz
    Usage:
        @with_circuit_breaker("stripe", fallback_func=my_fallback)
        async def stripe_payment():
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            service = get_circuit_breaker_service()  # Aus Dependency Injection
            return await service.call_with_circuit_breaker(
                service_name, func, *args, fallback=fallback_func, **kwargs
            )
        return wrapper
    return decorator
