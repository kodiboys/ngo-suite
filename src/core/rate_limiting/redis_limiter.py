# FILE: src/core/rate_limiting/redis_limiter.py
# MODULE: Redis-basierte Rate Limiter Implementierungen
# Sliding Window, Token Bucket, Leaky Bucket Algorithmen

import logging
import time
from datetime import datetime, timedelta

import redis.asyncio as redis

from src.core.rate_limiting.base import (
    RateLimitConfig,
    RateLimiterInterface,
    RateLimitResult,
)

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter(RateLimiterInterface):
    """
    Sliding Window Rate Limiter (Redis)
    Genauer als Fixed Window, gut für API Rate Limiting
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def is_allowed(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Prüft mit Sliding Window Algorithmus"""

        now = time.time()
        window_start = now - config.window_seconds

        # Redis Key für diesen Rate Limiter
        redis_key = f"ratelimit:sliding:{config.scope.value}:{key}"

        # Lua Script für atomare Operation
        lua_script = """
            local key = KEYS[1]
            local now = tonumber(ARGV[1])
            local window_start = tonumber(ARGV[2])
            local limit = tonumber(ARGV[3])
            local window_seconds = tonumber(ARGV[4])

            -- Entferne alte Einträge
            redis.call('ZREMRANGEBYSCORE', key, 0, window_start)

            -- Zähle aktuelle Anfragen
            local current = redis.call('ZCARD', key)

            -- Prüfe ob Limit erreicht
            if current >= limit then
                -- Hole ältesten Timestamp für Reset
                local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
                local reset_at = window_start
                if oldest and #oldest > 0 then
                    reset_at = tonumber(oldest[2]) + window_seconds
                end
                return {0, current, reset_at}
            end

            -- Füge neue Anfrage hinzu
            local member = now .. ':' .. math.random()
            redis.call('ZADD', key, now, member)

            -- Setze Expiry
            redis.call('EXPIRE', key, window_seconds + 10)

            -- Berechne Reset Zeit
            local reset_at = now + window_seconds

            return {1, current + 1, reset_at}
        """

        try:
            # Führe Lua Script aus
            result = await self.redis.eval(
                lua_script, 1, redis_key, now, window_start, config.limit, config.window_seconds
            )

            allowed, current_count, reset_at = result

            return RateLimitResult(
                allowed=bool(allowed),
                remaining=config.limit - current_count,
                reset_at=datetime.fromtimestamp(reset_at),
                limit=config.limit,
                current_count=current_count,
            )

        except Exception as e:
            logger.error(f"Sliding window rate limit error: {e}")
            # Fail open - bei Redis Fehlern erlauben
            return RateLimitResult(
                allowed=True,
                remaining=config.limit,
                reset_at=datetime.utcnow() + timedelta(seconds=config.window_seconds),
                limit=config.limit,
            )

    async def get_current_count(self, key: str, config: RateLimitConfig) -> int:
        """Holt aktuelle Anzahl"""
        redis_key = f"ratelimit:sliding:{config.scope.value}:{key}"
        now = time.time()
        window_start = now - config.window_seconds

        # Entferne alte Einträge und zähle
        await self.redis.zremrangebyscore(redis_key, 0, window_start)
        return await self.redis.zcard(redis_key)

    async def reset(self, key: str, config: RateLimitConfig):
        """Resetet den Rate Limiter"""
        redis_key = f"ratelimit:sliding:{config.scope.value}:{key}"
        await self.redis.delete(redis_key)


class TokenBucketRateLimiter(RateLimiterInterface):
    """
    Token Bucket Rate Limiter (Redis)
    Erlaubt Bursts, gut für variable Last
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def is_allowed(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Prüft mit Token Bucket Algorithmus"""

        redis_key = f"ratelimit:tokenbucket:{config.scope.value}:{key}"
        now = time.time()

        # Hole aktuellen Token Stand
        bucket_data = await self.redis.hgetall(redis_key)

        if not bucket_data:
            # Neuer Bucket
            tokens = config.initial_tokens or config.limit
            last_refill = now
        else:
            tokens = float(bucket_data.get(b"tokens", config.limit))
            last_refill = float(bucket_data.get(b"last_refill", now))

        # Refill Tokens basierend auf vergangener Zeit
        time_passed = now - last_refill
        refill_rate = config.refill_rate or (config.limit / config.window_seconds)
        new_tokens = min(config.limit, tokens + (time_passed * refill_rate))

        # Prüfe ob Token verfügbar
        if new_tokens >= 1:
            # Verbrauche Token
            new_tokens -= 1
            remaining = int(new_tokens)

            # Speichere neuen Zustand
            await self.redis.hset(redis_key, mapping={"tokens": new_tokens, "last_refill": now})
            await self.redis.expire(redis_key, config.window_seconds + 60)

            # Berechne Reset Zeit (wann nächster Token verfügbar)
            time_to_next_token = (1 / refill_rate) if refill_rate > 0 else config.window_seconds
            reset_at = datetime.utcnow() + timedelta(seconds=time_to_next_token)

            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                reset_at=reset_at,
                limit=config.limit,
                current_count=config.limit - remaining,
            )
        else:
            # Keine Token verfügbar
            time_to_next_token = (
                (1 - new_tokens) / refill_rate if refill_rate > 0 else config.window_seconds
            )
            reset_at = datetime.utcnow() + timedelta(seconds=time_to_next_token)

            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=reset_at,
                retry_after=int(time_to_next_token) + 1,
                limit=config.limit,
                current_count=config.limit,
            )

    async def get_current_count(self, key: str, config: RateLimitConfig) -> int:
        """Holt aktuellen Token Stand"""
        redis_key = f"ratelimit:tokenbucket:{config.scope.value}:{key}"
        tokens = await self.redis.hget(redis_key, "tokens")
        if tokens:
            return config.limit - int(float(tokens))
        return 0

    async def reset(self, key: str, config: RateLimitConfig):
        """Resetet den Rate Limiter"""
        redis_key = f"ratelimit:tokenbucket:{config.scope.value}:{key}"
        await self.redis.delete(redis_key)


class LeakyBucketRateLimiter(RateLimiterInterface):
    """
    Leaky Bucket Rate Limiter (Redis)
    Glättet Traffic, gut für konstante Raten
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def is_allowed(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Prüft mit Leaky Bucket Algorithmus"""

        redis_key = f"ratelimit:leaky:{config.scope.value}:{key}"
        now = time.time()

        # Leak Rate (Anfragen pro Sekunde)
        leak_rate = config.limit / config.window_seconds

        # Lua Script für atomare Operation
        lua_script = """
            local key = KEYS[1]
            local now = tonumber(ARGV[1])
            local limit = tonumber(ARGV[2])
            local leak_rate = tonumber(ARGV[3])

            -- Hole aktuellen Bucket Stand
            local bucket = redis.call('GET', key)
            local water_level = 0
            local last_leak = now

            if bucket then
                local parts = {}
                for part in string.gmatch(bucket, "[^:]+") do
                    table.insert(parts, part)
                end
                water_level = tonumber(parts[1]) or 0
                last_leak = tonumber(parts[2]) or now
            end

            -- Leak berechnen
            local time_passed = now - last_leak
            local leaked = time_passed * leak_rate
            water_level = math.max(0, water_level - leaked)

            -- Prüfe ob Platz für neue Anfrage
            if water_level + 1 <= limit then
                water_level = water_level + 1
                redis.call('SET', key, water_level .. ':' .. now)
                redis.call('EXPIRE', key, 3600)
                return {1, limit - water_level, now + (1 / leak_rate)}
            else
                -- Berechne Wartezeit
                local wait_time = (water_level + 1 - limit) / leak_rate
                return {0, 0, now + wait_time}
            end
        """

        try:
            result = await self.redis.eval(lua_script, 1, redis_key, now, config.limit, leak_rate)

            allowed, remaining, reset_at = result

            return RateLimitResult(
                allowed=bool(allowed),
                remaining=int(remaining),
                reset_at=datetime.fromtimestamp(reset_at),
                retry_after=int(reset_at - now) if not allowed else None,
                limit=config.limit,
                current_count=config.limit - int(remaining),
            )

        except Exception as e:
            logger.error(f"Leaky bucket rate limit error: {e}")
            return RateLimitResult(
                allowed=True,
                remaining=config.limit,
                reset_at=datetime.utcnow() + timedelta(seconds=config.window_seconds),
                limit=config.limit,
            )

    async def get_current_count(self, key: str, config: RateLimitConfig) -> int:
        """Holt aktuelle Wasserstand"""
        redis_key = f"ratelimit:leaky:{config.scope.value}:{key}"
        bucket = await self.redis.get(redis_key)
        if bucket:
            water_level = int(bucket.decode().split(":")[0])
            return water_level
        return 0

    async def reset(self, key: str, config: RateLimitConfig):
        """Resetet den Rate Limiter"""
        redis_key = f"ratelimit:leaky:{config.scope.value}:{key}"
        await self.redis.delete(redis_key)


class FixedWindowRateLimiter(RateLimiterInterface):
    """
    Fixed Window Rate Limiter (Einfach, aber weniger genau)
    Gut für einfache Use Cases
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def is_allowed(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Prüft mit Fixed Window Algorithmus"""

        now = datetime.utcnow()
        window_key = int(now.timestamp() / config.window_seconds)
        redis_key = f"ratelimit:fixed:{config.scope.value}:{key}:{window_key}"

        # Inkrementiere Counter
        current = await self.redis.incr(redis_key)

        if current == 1:
            await self.redis.expire(redis_key, config.window_seconds)

        # Berechne Reset Zeit
        window_start = window_key * config.window_seconds
        reset_at = datetime.fromtimestamp(window_start + config.window_seconds)

        allowed = current <= config.limit

        return RateLimitResult(
            allowed=allowed,
            remaining=max(0, config.limit - current),
            reset_at=reset_at,
            retry_after=int((reset_at - now).total_seconds()) if not allowed else None,
            limit=config.limit,
            current_count=current,
        )

    async def get_current_count(self, key: str, config: RateLimitConfig) -> int:
        """Holt aktuelle Anzahl"""
        now = datetime.utcnow()
        window_key = int(now.timestamp() / config.window_seconds)
        redis_key = f"ratelimit:fixed:{config.scope.value}:{key}:{window_key}"
        value = await self.redis.get(redis_key)
        return int(value) if value else 0

    async def reset(self, key: str, config: RateLimitConfig):
        """Resetet den Rate Limiter"""
        now = datetime.utcnow()
        window_key = int(now.timestamp() / config.window_seconds)
        redis_key = f"ratelimit:fixed:{config.scope.value}:{key}:{window_key}"
        await self.redis.delete(redis_key)
