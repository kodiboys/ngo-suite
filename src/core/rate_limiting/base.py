# FILE: src/core/rate_limiting/base.py
# MODULE: Rate Limiting Base Classes & Models
# Enterprise Rate Limiting mit Redis, Sliding Window, Token Bucket, Circuit Breaker

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field

# ==================== Enums ====================


class RateLimitStrategy(str, Enum):
    """Rate Limiting Strategien"""

    FIXED_WINDOW = "fixed_window"  # Feste Zeitfenster
    SLIDING_WINDOW = "sliding_window"  # Gleitendes Zeitfenster
    TOKEN_BUCKET = "token_bucket"  # Token Bucket Algorithmus
    LEAKY_BUCKET = "leaky_bucket"  # Leaky Bucket Algorithmus


class CircuitBreakerState(str, Enum):
    """Circuit Breaker Zustände"""

    CLOSED = "closed"  # Normalbetrieb
    OPEN = "open"  # Service ausgefallen
    HALF_OPEN = "half_open"  # Testbetrieb nach Ausfall
    FORCED_OPEN = "forced_open"  # Manuell geöffnet


class RateLimitScope(str, Enum):
    """Rate Limiting Scope"""

    GLOBAL = "global"  # Global für alle
    USER = "user"  # Pro Benutzer
    IP = "ip"  # Pro IP-Adresse
    API_KEY = "api_key"  # Pro API-Key
    ENDPOINT = "endpoint"  # Pro Endpoint
    TENANT = "tenant"  # Pro Tenant (Multi-Tenant)


# ==================== Data Models ====================


@dataclass
class RateLimitConfig:
    """Rate Limiting Konfiguration"""

    scope: RateLimitScope
    strategy: RateLimitStrategy
    limit: int  # Maximale Anfragen
    window_seconds: int  # Zeitfenster in Sekunden
    block_duration_seconds: int = 0  # Blockierdauer bei Überschreitung
    identifier: str | None = None  # Spezifischer Identifier (z.B. Endpoint)

    # Token Bucket spezifisch
    refill_rate: float | None = None  # Tokens pro Sekunde
    initial_tokens: int | None = None  # Initiale Tokens

    def __post_init__(self):
        if self.strategy == RateLimitStrategy.TOKEN_BUCKET:
            if self.refill_rate is None:
                self.refill_rate = self.limit / self.window_seconds
            if self.initial_tokens is None:
                self.initial_tokens = self.limit


@dataclass
class RateLimitResult:
    """Ergebnis einer Rate Limit Prüfung"""

    allowed: bool
    remaining: int
    reset_at: datetime
    retry_after: int | None = None
    limit: int = 0
    current_count: int = 0

    def to_headers(self) -> dict[str, str]:
        """Konvertiert zu HTTP Headers"""
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(int(self.reset_at.timestamp())),
        }
        if self.retry_after:
            headers["Retry-After"] = str(self.retry_after)
        return headers


@dataclass
class CircuitBreakerConfig:
    """Circuit Breaker Konfiguration"""

    name: str
    failure_threshold: int = 5  # Fehlerschwelle
    success_threshold: int = 2  # Erfolgsschwelle (Half-Open)
    timeout_seconds: int = 60  # Timeout für Open State
    half_open_max_calls: int = 3  # Maximale Calls in Half-Open
    rolling_window_seconds: int = 60  # Rolling Window für Fehlerzählung
    exclude_exceptions: list[str] = field(default_factory=list)  # Ignorierte Exceptions


@dataclass
class CircuitBreakerStatus:
    """Circuit Breaker Status"""

    state: CircuitBreakerState
    failure_count: int
    success_count: int
    last_failure_at: datetime | None
    last_success_at: datetime | None
    open_until: datetime | None
    total_failures: int
    total_successes: int


class RateLimitRule(BaseModel):
    """API Rate Limit Rule für Konfiguration"""

    path_pattern: str = Field(..., description="URL Pattern (z.B. /api/v1/donations)")
    method: str = Field("GET", description="HTTP Method")
    scope: RateLimitScope = RateLimitScope.IP
    strategy: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW
    limit: int = Field(100, ge=1, le=10000)
    window_seconds: int = Field(60, ge=1, le=3600)
    block_duration_seconds: int = Field(0, ge=0, le=86400)

    # Burst Protection
    burst_limit: int | None = Field(None, ge=1, le=1000)

    class Config:
        use_enum_values = True


class CircuitBreakerRule(BaseModel):
    """Circuit Breaker Rule für externe Services"""

    service_name: str
    failure_threshold: int = Field(5, ge=1, le=100)
    success_threshold: int = Field(2, ge=1, le=10)
    timeout_seconds: int = Field(60, ge=5, le=3600)
    half_open_max_calls: int = Field(3, ge=1, le=10)
    enabled: bool = True


# ==================== Rate Limiter Interface ====================


class RateLimiterInterface:
    """Interface für Rate Limiter Implementierungen"""

    async def is_allowed(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Prüft ob Anfrage erlaubt ist"""
        raise NotImplementedError

    async def get_current_count(self, key: str, config: RateLimitConfig) -> int:
        """Holt aktuelle Anzahl der Anfragen"""
        raise NotImplementedError

    async def reset(self, key: str, config: RateLimitConfig):
        """Resetet den Rate Limiter für einen Key"""
        raise NotImplementedError


# ==================== Circuit Breaker Interface ====================


class CircuitBreakerInterface:
    """Interface für Circuit Breaker Implementierungen"""

    async def call(self, func, *args, fallback: Callable | None = None, **kwargs) -> Any:
        """Führt Funktion mit Circuit Breaker Schutz aus"""
        raise NotImplementedError

    async def get_status(self) -> CircuitBreakerStatus:
        """Holt aktuellen Status"""
        raise NotImplementedError

    async def force_open(self):
        """Erzwingt Open State (manuell)"""
        raise NotImplementedError

    async def force_close(self):
        """Erzwingt Closed State (manuell)"""
        raise NotImplementedError

    async def record_success(self):
        """Recordet einen Erfolg"""
        raise NotImplementedError

    async def record_failure(self):
        """Recordet einen Fehler"""
        raise NotImplementedError
