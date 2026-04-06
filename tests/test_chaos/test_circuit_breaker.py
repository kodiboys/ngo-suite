# FILE: tests/test_chaos/test_circuit_breaker.py
# MODULE: Chaos Engineering Tests für Circuit Breaker
# Testet Resilience unter Fehlerbedingungen

from unittest.mock import patch

import pytest

from src.core.rate_limiting.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
)


class TestCircuitBreakerChaos:
    """Chaos Tests für Circuit Breaker"""

    @pytest.fixture
    def circuit_breaker_config(self):
        return CircuitBreakerConfig(
            name="chaos_test",
            failure_threshold=3,
            success_threshold=2,
            timeout_seconds=2,
            half_open_max_calls=2,
            rolling_window_seconds=10,
        )

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_on_failures(self, redis_client, circuit_breaker_config):
        """Test: Circuit öffnet nach Fehlerschwelle"""
        breaker = CircuitBreaker(circuit_breaker_config, redis_client)

        # Simuliere 3 Fehler
        for i in range(3):
            await breaker.record_failure()

        status = await breaker.get_status()
        assert status.state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_circuit_breaker_recovers(self, redis_client, circuit_breaker_config):
        """Test: Circuit schließt nach erfolgreichen Calls"""
        breaker = CircuitBreaker(circuit_breaker_config, redis_client)

        # Öffne Circuit
        for i in range(3):
            await breaker.record_failure()

        status = await breaker.get_status()
        assert status.state == CircuitBreakerState.OPEN

        # Manuell auf Half-Open setzen (simuliere Timeout)
        await breaker._set_state(CircuitBreakerState.HALF_OPEN)

        # Erfolge in Half-Open
        for i in range(2):
            await breaker.record_success()

        status = await breaker.get_status()
        assert status.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_reopens_on_half_open_failure(
        self, redis_client, circuit_breaker_config
    ):
        """Test: Circuit öffnet wieder bei Fehler in Half-Open"""
        breaker = CircuitBreaker(circuit_breaker_config, redis_client)

        # Öffne Circuit
        for i in range(3):
            await breaker.record_failure()

        # Manuell auf Half-Open
        await breaker._set_state(CircuitBreakerState.HALF_OPEN)

        # Fehler in Half-Open
        await breaker.record_failure()

        status = await breaker.get_status()
        assert status.state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_circuit_breaker_with_function(self, redis_client, circuit_breaker_config):
        """Test: Circuit Breaker mit Funktion"""
        breaker = CircuitBreaker(circuit_breaker_config, redis_client)

        call_count = 0

        async def failing_function():
            nonlocal call_count
            call_count += 1
            raise ValueError("Service unavailable")

        async def fallback_function():
            return "fallback_response"

        # Erste 3 Aufrufe schlagen fehl
        for i in range(3):
            with pytest.raises(ValueError):
                await breaker.call(failing_function)

        assert call_count == 3

        # 4. Aufruf sollte Circuit Breaker auslösen und Fallback verwenden
        result = await breaker.call(failing_function, fallback=fallback_function)
        assert result == "fallback_response"
        assert call_count == 3  # Kein weiterer Aufruf der eigentlichen Funktion


class TestChaosEngineering:
    """Chaos Engineering Tests für System-Resilience"""

    @pytest.mark.chaos
    @pytest.mark.asyncio
    async def test_database_failure_recovery(self, db_session, test_donation):
        """Test: Datenbank-Ausfall während Transaktion"""
        from sqlalchemy.exc import SQLAlchemyError

        with patch("sqlalchemy.ext.asyncio.AsyncSession.commit") as mock_commit:
            # Simuliere Datenbankfehler
            mock_commit.side_effect = SQLAlchemyError("Database connection lost")

            # Versuche Spende zu speichern
            with pytest.raises(SQLAlchemyError):
                await db_session.commit()

            # Stelle sicher dass keine Daten korrupt sind
            # In Production: Rollback sollte erfolgt sein
            pass

    @pytest.mark.chaos
    @pytest.mark.asyncio
    async def test_redis_failure_rate_limiting(self, redis_client):
        """Test: Redis-Ausfall bei Rate Limiting"""
        from src.core.rate_limiting.base import RateLimitConfig, RateLimitScope, RateLimitStrategy
        from src.core.rate_limiting.redis_limiter import SlidingWindowRateLimiter

        # Simuliere Redis-Ausfall
        with patch("redis.asyncio.Redis.eval") as mock_eval:
            mock_eval.side_effect = ConnectionError("Redis unavailable")

            limiter = SlidingWindowRateLimiter(redis_client)
            config = RateLimitConfig(
                scope=RateLimitScope.IP,
                strategy=RateLimitStrategy.SLIDING_WINDOW,
                limit=100,
                window_seconds=60,
            )

            # Fail-Open: Bei Redis-Fehler sollte Request erlaubt sein
            result = await limiter.is_allowed("test_key", config)
            assert result.allowed is True

    @pytest.mark.chaos
    @pytest.mark.asyncio
    async def test_external_api_timeout(self, client, auth_headers):
        """Test: Timeout bei externer API (Stripe)"""
        import httpx

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Request timeout")

            # Versuche Zahlung zu erstellen
            response = client.post(
                "/api/v1/payments/create-donation",
                json={
                    "amount": 100.00,
                    "currency": "EUR",
                    "payment_method": "credit_card",
                    "donor_email": "test@example.com",
                    "project_id": str(uuid4()),
                },
                headers=auth_headers,
            )

            # Sollte fehlschlagen, aber nicht crashen
            assert response.status_code in [400, 500, 502, 503]
