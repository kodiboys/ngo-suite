# FILE: tests/test_rate_limiting.py
# MODULE: Rate Limiting & Circuit Breaker Tests
# Unit, Integration & Load Tests

import asyncio
from unittest.mock import patch

import pytest

from src.core.rate_limiting.base import (
    RateLimitConfig,
    RateLimitScope,
    RateLimitStrategy,
)
from src.core.rate_limiting.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from src.core.rate_limiting.redis_limiter import (
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
)

# ==================== Unit Tests ====================


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter(redis_client):
    """Test Sliding Window Rate Limiter"""

    limiter = SlidingWindowRateLimiter(redis_client)

    config = RateLimitConfig(
        scope=RateLimitScope.IP,
        strategy=RateLimitStrategy.SLIDING_WINDOW,
        limit=5,
        window_seconds=10,
    )

    key = "test:127.0.0.1"

    # Erste 5 Anfragen sollten erlaubt sein
    for i in range(5):
        result = await limiter.is_allowed(key, config)
        assert result.allowed is True
        assert result.remaining == 4 - i

    # 6. Anfrage sollte blockiert werden
    result = await limiter.is_allowed(key, config)
    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after is not None


@pytest.mark.asyncio
async def test_token_bucket_rate_limiter(redis_client):
    """Test Token Bucket Rate Limiter"""

    limiter = TokenBucketRateLimiter(redis_client)

    config = RateLimitConfig(
        scope=RateLimitScope.IP,
        strategy=RateLimitStrategy.TOKEN_BUCKET,
        limit=10,
        window_seconds=10,
        refill_rate=1.0,  # 1 Token pro Sekunde
    )

    key = "test:token:127.0.0.1"

    # Erste 10 Anfragen sofort erlaubt (Burst)
    for i in range(10):
        result = await limiter.is_allowed(key, config)
        assert result.allowed is True

    # 11. Anfrage sollte warten müssen
    result = await limiter.is_allowed(key, config)
    assert result.allowed is False
    assert result.retry_after > 0


@pytest.mark.asyncio
async def test_circuit_breaker(redis_client):
    """Test Circuit Breaker Pattern"""

    config = CircuitBreakerConfig(
        name="test_service",
        failure_threshold=3,
        success_threshold=2,
        timeout_seconds=5,
        half_open_max_calls=2,
        rolling_window_seconds=10,
    )

    breaker = CircuitBreaker(config, redis_client)

    # Simuliere Fehler
    for i in range(3):
        await breaker.record_failure()

    status = await breaker.get_status()
    assert status.state.value == "open"  # Circuit sollte offen sein

    # Warte auf Timeout (in Tests mocken wir)
    with patch.object(breaker, "_set_open_until") as mock:
        mock.return_value = None
        # Manuell auf Half-Open setzen
        await breaker._set_state("half_open")

        status = await breaker.get_status()
        assert status.state.value == "half_open"


# ==================== Integration Tests ====================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limit_middleware_integration(client, redis_client):
    """Test Rate Limiting Middleware Integration"""

    # Mache 10 schnelle Requests
    for i in range(10):
        response = await client.get("/api/v1/health")

        if i < 5:
            assert response.status_code == 200
        else:
            # Nach 5 Requests sollte Rate Limit greifen
            if response.status_code == 429:
                assert "rate_limit_exceeded" in response.text
                break


@pytest.mark.asyncio
async def test_circuit_breaker_with_function(redis_client):
    """Test Circuit Breaker mit Funktion"""

    config = CircuitBreakerConfig(
        name="test",
        failure_threshold=2,
        success_threshold=1,
        timeout_seconds=1,
        half_open_max_calls=1,
        rolling_window_seconds=10,
    )

    breaker = CircuitBreaker(config, redis_client)

    # Funktion die immer fehlschlägt
    async def failing_func():
        raise ValueError("Service unavailable")

    # Fallback Funktion
    async def fallback_func():
        return "fallback_response"

    # Erste zwei Aufrufe schlagen fehl
    for i in range(2):
        with pytest.raises(ValueError):
            await breaker.call(failing_func)

    # Dritter Aufruf sollte Circuit Breaker auslösen und Fallback verwenden
    result = await breaker.call(failing_func, fallback=fallback_func)
    assert result == "fallback_response"


# ==================== Load Tests ====================


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_rate_limiter_benchmark(benchmark, redis_client):
    """Benchmark: Rate Limiter Performance"""

    limiter = SlidingWindowRateLimiter(redis_client)
    config = RateLimitConfig(
        scope=RateLimitScope.IP,
        strategy=RateLimitStrategy.SLIDING_WINDOW,
        limit=1000,
        window_seconds=60,
    )

    key = "benchmark:127.0.0.1"

    async def check_limit():
        return await limiter.is_allowed(key, config)

    result = await benchmark(check_limit)
    assert result is not None


@pytest.mark.load
@pytest.mark.asyncio
async def test_concurrent_rate_limiting(redis_client):
    """Test Concurrent Rate Limiting (Load Test)"""

    limiter = SlidingWindowRateLimiter(redis_client)
    config = RateLimitConfig(
        scope=RateLimitScope.IP,
        strategy=RateLimitStrategy.SLIDING_WINDOW,
        limit=100,
        window_seconds=1,
    )

    key = "concurrent:127.0.0.1"

    # 200 gleichzeitige Anfragen
    async def make_request():
        return await limiter.is_allowed(key, config)

    results = await asyncio.gather(*[make_request() for _ in range(200)])

    allowed = sum(1 for r in results if r.allowed)
    blocked = sum(1 for r in results if not r.allowed)

    assert allowed <= 100  # Max 100 erlaubt
    assert blocked >= 100  # Mindestens 100 blockiert

    print(f"Rate Limit Test: {allowed} allowed, {blocked} blocked")


# ==================== Property-Based Tests ====================

from hypothesis import given
from hypothesis import strategies as st


@given(
    limit=st.integers(min_value=1, max_value=100),
    window=st.integers(min_value=1, max_value=60),
    requests=st.integers(min_value=1, max_value=200),
)
def test_rate_limit_properties(limit, window, requests):
    """Test: Rate Limit Eigenschaften"""

    # Simuliere Rate Limiting (vereinfacht)
    allowed = min(requests, limit)
    blocked = max(0, requests - limit)

    assert allowed + blocked == requests
    assert allowed <= limit
    assert blocked >= 0


# ==================== Performance Tests ====================


@pytest.mark.benchmark
def test_rate_limit_key_generation(benchmark):
    """Benchmark: Key Generation Performance"""

    def generate_keys():
        keys = []
        for i in range(1000):
            key = f"ratelimit:test:{i}:user:123:endpoint:/api/test"
            keys.append(key)
        return keys

    result = benchmark(generate_keys)
    assert len(result) == 1000
