# FILE: src/core/rate_limiting/circuit_breaker.py
# MODULE: Circuit Breaker Pattern für Resilience
# Schutz vor Cascade Failures, automatische Recovery

import logging
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import redis.asyncio as redis

from src.core.rate_limiting.base import (
    CircuitBreakerConfig,
    CircuitBreakerInterface,
    CircuitBreakerState,
    CircuitBreakerStatus,
)

logger = logging.getLogger(__name__)


class CircuitBreaker(CircuitBreakerInterface):
    """
    Circuit Breaker Pattern Implementierung
    Features:
    - Rolling Window für Fehlerzählung
    - Automatische Recovery (Half-Open)
    - Manuelle Override (Force Open/Close)
    - Redis-basierter Shared State für Multi-Instance
    """

    def __init__(
        self, config: CircuitBreakerConfig, redis_client: redis.Redis, instance_id: str = "default"
    ):
        self.config = config
        self.redis = redis_client
        self.instance_id = instance_id
        self.redis_key = f"circuit_breaker:{config.name}:{instance_id}"

        # Rolling Window für Fehler (falls Redis nicht verfügbar)
        self._local_failures = deque(maxlen=config.failure_threshold * 2)
        self._local_successes = deque(maxlen=config.success_threshold * 2)

    async def call(
        self,
        func: Callable[..., Awaitable[Any]],
        *args,
        fallback: Callable[..., Awaitable[Any]] | None = None,
        **kwargs,
    ) -> Any:
        """
        Führt eine Funktion mit Circuit Breaker Schutz aus
        """
        # Prüfe aktuellen State
        status = await self.get_status()

        if status.state == CircuitBreakerState.OPEN:
            # Prüfe ob Timeout abgelaufen
            if status.open_until and datetime.utcnow() >= status.open_until:
                logger.info(f"Circuit breaker {self.config.name} transitioning to HALF_OPEN")
                await self._set_state(CircuitBreakerState.HALF_OPEN)
                status.state = CircuitBreakerState.HALF_OPEN
            else:
                # Circuit ist offen - verwende Fallback
                if fallback:
                    logger.warning(f"Circuit breaker {self.config.name} is OPEN, using fallback")
                    return await fallback(*args, **kwargs)
                raise CircuitBreakerOpenException(
                    f"Circuit breaker {self.config.name} is OPEN. "
                    f"Open until {status.open_until}"
                )

        # Führe Funktion aus
        try:
            result = await func(*args, **kwargs)
            await self.record_success()
            return result

        except Exception as e:
            # Prüfe ob Exception ignoriert werden soll
            should_record = True
            for exclude in self.config.exclude_exceptions:
                if isinstance(e, eval(exclude)):
                    should_record = False
                    break

            if should_record:
                await self.record_failure()

            # Wenn Fallback vorhanden, verwende diesen
            if fallback:
                logger.warning(f"Function failed, using fallback: {e}")
                return await fallback(*args, **kwargs)

            raise

    async def record_success(self):
        """Recordet einen erfolgreichen Call"""
        now = datetime.utcnow()

        # Redis-basierter Counter (für Multi-Instance)
        await self.redis.lpush(f"{self.redis_key}:successes", now.timestamp())
        await self.redis.ltrim(f"{self.redis_key}:successes", 0, self.config.success_threshold * 2)
        await self.redis.expire(f"{self.redis_key}:successes", self.config.rolling_window_seconds)

        # Lokaler Counter (Fallback)
        self._local_successes.append(now)

        status = await self.get_status()

        if status.state == CircuitBreakerState.HALF_OPEN:
            # In Half-Open: Zähle Erfolge
            success_count = await self._count_recent_successes()

            if success_count >= self.config.success_threshold:
                logger.info(
                    f"Circuit breaker {self.config.name} closing after {success_count} successes"
                )
                await self._set_state(CircuitBreakerState.CLOSED)
                await self._reset_counts()

    async def record_failure(self):
        """Recordet einen fehlgeschlagenen Call"""
        now = datetime.utcnow()

        # Redis-basierter Counter
        await self.redis.lpush(f"{self.redis_key}:failures", now.timestamp())
        await self.redis.ltrim(f"{self.redis_key}:failures", 0, self.config.failure_threshold * 2)
        await self.redis.expire(f"{self.redis_key}:failures", self.config.rolling_window_seconds)

        # Lokaler Counter
        self._local_failures.append(now)

        status = await self.get_status()

        if status.state == CircuitBreakerState.CLOSED:
            failure_count = await self._count_recent_failures()

            if failure_count >= self.config.failure_threshold:
                logger.warning(
                    f"Circuit breaker {self.config.name} opening after {failure_count} failures"
                )
                await self._set_state(CircuitBreakerState.OPEN)
                await self._set_open_until(
                    datetime.utcnow() + timedelta(seconds=self.config.timeout_seconds)
                )

        elif status.state == CircuitBreakerState.HALF_OPEN:
            # Ein Fehler in Half-Open öffnet den Circuit sofort
            logger.warning(
                f"Circuit breaker {self.config.name} reopening after failure in HALF_OPEN"
            )
            await self._set_state(CircuitBreakerState.OPEN)
            await self._set_open_until(
                datetime.utcnow() + timedelta(seconds=self.config.timeout_seconds)
            )

    async def get_status(self) -> CircuitBreakerStatus:
        """Holt aktuellen Status"""
        # Lade State aus Redis
        state_str = await self.redis.get(f"{self.redis_key}:state")
        state = CircuitBreakerState(state_str.decode()) if state_str else CircuitBreakerState.CLOSED

        open_until = None
        open_until_str = await self.redis.get(f"{self.redis_key}:open_until")
        if open_until_str:
            open_until = datetime.fromtimestamp(float(open_until_str.decode()))

        failure_count = await self._count_recent_failures()
        success_count = await self._count_recent_successes()

        last_failure = await self._get_last_failure()
        last_success = await self._get_last_success()

        total_failures = await self.redis.llen(f"{self.redis_key}:failures")
        total_successes = await self.redis.llen(f"{self.redis_key}:successes")

        return CircuitBreakerStatus(
            state=state,
            failure_count=failure_count,
            success_count=success_count,
            last_failure_at=last_failure,
            last_success_at=last_success,
            open_until=open_until,
            total_failures=total_failures,
            total_successes=total_successes,
        )

    async def force_open(self):
        """Erzwingt Open State (manuelle Intervention)"""
        logger.warning(f"Circuit breaker {self.config.name} manually forced to OPEN")
        await self._set_state(CircuitBreakerState.FORCED_OPEN)

    async def force_close(self):
        """Erzwingt Closed State (manuelle Intervention)"""
        logger.info(f"Circuit breaker {self.config.name} manually forced to CLOSED")
        await self._set_state(CircuitBreakerState.CLOSED)
        await self._reset_counts()

    async def _set_state(self, state: CircuitBreakerState):
        """Setzt Circuit Breaker State in Redis"""
        await self.redis.set(f"{self.redis_key}:state", state.value)
        await self.redis.expire(f"{self.redis_key}:state", 86400)  # 24h TTL

    async def _set_open_until(self, until: datetime):
        """Setzt Open Until Timestamp"""
        await self.redis.set(f"{self.redis_key}:open_until", until.timestamp())
        await self.redis.expire(f"{self.redis_key}:open_until", self.config.timeout_seconds + 60)

    async def _count_recent_failures(self) -> int:
        """Zählt Fehler im Rolling Window"""
        cutoff = datetime.utcnow() - timedelta(seconds=self.config.rolling_window_seconds)
        cutoff_ts = cutoff.timestamp()

        # Versuche Redis zuerst
        failures = await self.redis.lrange(f"{self.redis_key}:failures", 0, -1)
        if failures:
            count = sum(1 for f in failures if float(f) > cutoff_ts)
            return count

        # Fallback zu lokalem Counter
        return sum(1 for f in self._local_failures if f > cutoff)

    async def _count_recent_successes(self) -> int:
        """Zählt Erfolge im Rolling Window"""
        cutoff = datetime.utcnow() - timedelta(seconds=self.config.rolling_window_seconds)
        cutoff_ts = cutoff.timestamp()

        successes = await self.redis.lrange(f"{self.redis_key}:successes", 0, -1)
        if successes:
            count = sum(1 for s in successes if float(s) > cutoff_ts)
            return count

        return sum(1 for s in self._local_successes if s > cutoff)

    async def _get_last_failure(self) -> datetime | None:
        """Holt Zeitpunkt des letzten Fehlers"""
        failures = await self.redis.lrange(f"{self.redis_key}:failures", 0, 0)
        if failures:
            return datetime.fromtimestamp(float(failures[0]))

        if self._local_failures:
            return max(self._local_failures)
        return None

    async def _get_last_success(self) -> datetime | None:
        """Holt Zeitpunkt des letzten Erfolgs"""
        successes = await self.redis.lrange(f"{self.redis_key}:successes", 0, 0)
        if successes:
            return datetime.fromtimestamp(float(successes[0]))

        if self._local_successes:
            return max(self._local_successes)
        return None

    async def _reset_counts(self):
        """Resetet alle Counter"""
        await self.redis.delete(f"{self.redis_key}:failures")
        await self.redis.delete(f"{self.redis_key}:successes")
        await self.redis.delete(f"{self.redis_key}:open_until")
        self._local_failures.clear()
        self._local_successes.clear()


class CircuitBreakerOpenException(Exception):
    """Wird geworfen wenn Circuit Breaker geöffnet ist"""

    pass


class CircuitBreakerRegistry:
    """
    Registry für Circuit Breaker Instanzen
    Verwaltet alle Circuit Breaker zentral
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self, config: CircuitBreakerConfig, instance_id: str = "default"
    ) -> CircuitBreaker:
        """Holt oder erstellt einen Circuit Breaker"""
        key = f"{config.name}:{instance_id}"

        if key not in self._breakers:
            self._breakers[key] = CircuitBreaker(config, self.redis, instance_id)

        return self._breakers[key]

    async def get_all_statuses(self) -> dict[str, CircuitBreakerStatus]:
        """Holt Status aller Circuit Breaker"""
        statuses = {}
        for key, breaker in self._breakers.items():
            statuses[key] = await breaker.get_status()
        return statuses

    async def reset_all(self):
        """Resetet alle Circuit Breaker"""
        for breaker in self._breakers.values():
            await breaker.force_close()
