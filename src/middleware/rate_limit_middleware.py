# FILE: src/middleware/rate_limit_middleware.py
# MODULE: FastAPI Rate Limiting Middleware
# Automatische Rate Limiting für API Endpoints

import re
import ipaddress
from typing import Dict, Optional, Tuple
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.rate_limiting.base import (
    RateLimitConfig, RateLimitResult, RateLimitScope, RateLimitStrategy,
    RateLimitRule
)
from src.core.rate_limiting.redis_limiter import (
    SlidingWindowRateLimiter, TokenBucketRateLimiter,
    FixedWindowRateLimiter, LeakyBucketRateLimiter
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate Limiting Middleware für FastAPI
    Unterstützt verschiedene Strategien pro Endpoint
    """
    
    def __init__(
        self,
        app: FastAPI,
        redis_client,
        rules: Optional[Dict[str, RateLimitRule]] = None
    ):
        super().__init__(app)
        self.redis_client = redis_client
        
        # Rate Limiter Instanzen
        self.limiters = {
            RateLimitStrategy.SLIDING_WINDOW: SlidingWindowRateLimiter(redis_client),
            RateLimitStrategy.TOKEN_BUCKET: TokenBucketRateLimiter(redis_client),
            RateLimitStrategy.FIXED_WINDOW: FixedWindowRateLimiter(redis_client),
            RateLimitStrategy.LEAKY_BUCKET: LeakyBucketRateLimiter(redis_client)
        }
        
        # Default Rules mit allen erforderlichen Parametern
        self.rules = rules or self._get_default_rules()
    
    def _get_default_rules(self) -> Dict[str, RateLimitRule]:
        """Default Rate Limiting Regeln mit allen Parametern"""
        return {
            # Öffentliche Endpunkte (strikt)
            "public_donations": RateLimitRule(
                path_pattern="/api/v1/donations",
                method="POST",
                scope=RateLimitScope.IP,
                strategy=RateLimitStrategy.SLIDING_WINDOW,
                limit=10,
                window_seconds=60,
                block_duration_seconds=0,      # ← erforderlich
                burst_limit=3                  # ← erforderlich
            ),
            
            # Authentifizierte Endpunkte (großzügiger)
            "auth_read": RateLimitRule(
                path_pattern="/api/v1/.*",
                method="GET",
                scope=RateLimitScope.USER,
                strategy=RateLimitStrategy.TOKEN_BUCKET,
                limit=500,
                window_seconds=60,
                block_duration_seconds=0,
                burst_limit=50
            ),
            "auth_write": RateLimitRule(
                path_pattern="/api/v1/.*",
                method="POST|PUT|DELETE|PATCH",
                scope=RateLimitScope.USER,
                strategy=RateLimitStrategy.SLIDING_WINDOW,
                limit=100,
                window_seconds=60,
                block_duration_seconds=0,
                burst_limit=0
            ),
            
            # Login Endpunkte (sehr strikt gegen Brute Force)
            "login": RateLimitRule(
                path_pattern="/api/v1/auth/login",
                method="POST",
                scope=RateLimitScope.IP,
                strategy=RateLimitStrategy.FIXED_WINDOW,
                limit=5,
                window_seconds=60,
                block_duration_seconds=300,    # 5 Minuten Block
                burst_limit=0
            ),
            
            # Admin Endpunkte (normal)
            "admin": RateLimitRule(
                path_pattern="/api/v1/admin/.*",
                method=".*",
                scope=RateLimitScope.USER,
                strategy=RateLimitStrategy.SLIDING_WINDOW,
                limit=200,
                window_seconds=60,
                block_duration_seconds=0,
                burst_limit=0
            ),
            
            # Export Endpunkte (limitieren wegen Ressourcen)
            "export": RateLimitRule(
                path_pattern="/api/v1/export/.*",
                method="GET",
                scope=RateLimitScope.USER,
                strategy=RateLimitStrategy.TOKEN_BUCKET,
                limit=20,
                window_seconds=300,            # 5 Minuten
                block_duration_seconds=0,
                burst_limit=5
            ),
            
            # Webhooks (großzügig, aber mit Burst Protection)
            "webhook": RateLimitRule(
                path_pattern="/api/v1/.*/webhook/.*",
                method="POST",
                scope=RateLimitScope.IP,
                strategy=RateLimitStrategy.LEAKY_BUCKET,
                limit=1000,
                window_seconds=60,
                block_duration_seconds=0,
                burst_limit=0
            ),
            
            # Global Default
            "global_default": RateLimitRule(
                path_pattern=".*",
                method=".*",
                scope=RateLimitScope.IP,
                strategy=RateLimitStrategy.SLIDING_WINDOW,
                limit=1000,
                window_seconds=60,
                block_duration_seconds=0,
                burst_limit=0
            )
        }
    
    async def dispatch(self, request: Request, call_next):
        """Main Middleware Logic"""
        
        # Extrahiere Request Informationen
        path = request.url.path
        method = request.method
        client_ip = self._get_client_ip(request)
        
        # Finde passende Rule
        rule = self._find_rule(path, method)
        
        if not rule:
            return await call_next(request)
        
        # Generiere Rate Limit Key
        key = await self._generate_key(request, rule, client_ip)
        
        # Erstelle Config
        config = RateLimitConfig(
            scope=rule.scope,
            strategy=rule.strategy,
            limit=rule.limit,
            window_seconds=rule.window_seconds,
            block_duration_seconds=rule.block_duration_seconds,
            identifier=key
        )
        
        # Füge Burst Protection hinzu (falls konfiguriert)
        if rule.burst_limit and rule.burst_limit > 0:
            burst_config = RateLimitConfig(
                scope=rule.scope,
                strategy=RateLimitStrategy.TOKEN_BUCKET,
                limit=rule.burst_limit,
                window_seconds=rule.window_seconds,
                identifier=f"{key}:burst"
            )
            burst_result = await self.limiters[RateLimitStrategy.TOKEN_BUCKET].is_allowed(
                f"{key}:burst", burst_config
            )
            if not burst_result.allowed:
                return await self._rate_limit_response(burst_result, rule)
        
        # Prüfe Rate Limit
        limiter = self.limiters[rule.strategy]
        result = await limiter.is_allowed(key, config)
        
        if not result.allowed:
            return await self._rate_limit_response(result, rule)
        
        # Führe Request aus
        response = await call_next(request)
        
        # Füge Rate Limit Headers hinzu
        for header, value in result.to_headers().items():
            response.headers[header] = value
        
        return response
    
    def _find_rule(self, path: str, method: str) -> Optional[RateLimitRule]:
        """Findet passende Rule für Path und Method"""
        best_match = None
        best_score = -1
        
        for rule in self.rules.values():
            # Prüfe Path Pattern
            if re.match(rule.path_pattern, path):
                # Prüfe Method Pattern
                if re.match(rule.method, method):
                    # Bewerte Match (längeres Pattern = spezifischer)
                    score = len(rule.path_pattern)
                    if score > best_score:
                        best_score = score
                        best_match = rule
        
        return best_match or self.rules.get("global_default")
    
    def _get_client_ip(self, request: Request) -> str:
        """Extrahiert Client IP aus Request (mit Proxy-Unterstützung)"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        return request.client.host if request.client else "unknown"
    
    async def _generate_key(
        self,
        request: Request,
        rule: RateLimitRule,
        client_ip: str
    ) -> str:
        """Generiert eindeutigen Key für Rate Limiting"""
        parts = []
        
        if rule.scope == RateLimitScope.IP:
            parts.append(f"ip:{client_ip}")
        
        elif rule.scope == RateLimitScope.USER:
            # Extrahiere User ID aus JWT
            user_id = getattr(request.state, "user_id", None)
            if user_id:
                parts.append(f"user:{user_id}")
            else:
                parts.append(f"ip:{client_ip}")
        
        elif rule.scope == RateLimitScope.API_KEY:
            api_key = request.headers.get("X-API-Key")
            if api_key:
                parts.append(f"apikey:{api_key[:16]}")
            else:
                parts.append(f"ip:{client_ip}")
        
        elif rule.scope == RateLimitScope.ENDPOINT:
            parts.append(f"endpoint:{request.url.path}")
        
        parts.append(f"method:{request.method}")
        
        return ":".join(parts)
    
    async def _rate_limit_response(
        self,
        result: RateLimitResult,
        rule: RateLimitRule
    ) -> JSONResponse:
        """Erstellt Rate Limit Error Response"""
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "message": f"Rate limit exceeded. Maximum {rule.limit} requests per {rule.window_seconds} seconds.",
                "retry_after": result.retry_after,
                "limit": rule.limit,
                "remaining": 0,
                "reset_at": result.reset_at.isoformat()
            },
            headers=result.to_headers()
        )


# ==================== Per-User Rate Limiter ====================

class PerUserRateLimiter:
    """
    Benutzer-spezifischer Rate Limiter
    Für unterschiedliche Limits pro User-Rolle
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.base_limiter = SlidingWindowRateLimiter(redis_client)
    
    async def check_user_limit(
        self,
        user_id: str,
        user_role: str,
        endpoint: str,
        method: str
    ) -> RateLimitResult:
        """Prüft Rate Limit basierend auf User-Rolle"""
        
        # Limits pro Rolle
        role_limits = {
            "admin": {"limit": 2000, "window": 60},
            "accountant": {"limit": 1000, "window": 60},
            "project_manager": {"limit": 500, "window": 60},
            "donor": {"limit": 100, "window": 60},
            "anonymous": {"limit": 20, "window": 60}
        }
        
        limits = role_limits.get(user_role, role_limits["anonymous"])
        
        config = RateLimitConfig(
            scope=RateLimitScope.USER,
            strategy=RateLimitStrategy.SLIDING_WINDOW,
            limit=limits["limit"],
            window_seconds=limits["window"],
            identifier=f"user:{user_id}:{endpoint}",
            block_duration_seconds=0
        )
        
        return await self.base_limiter.is_allowed(
            f"user:{user_id}:{endpoint}",
            config
        )


# ==================== API Key Rate Limiter ====================

class APIKeyRateLimiter:
    """
    Rate Limiter für API Keys (Partner-Integrationen)
    Unterschiedliche Limits pro Partner
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.limiters = {
            "stripe": {"limit": 5000, "window": 60},
            "paypal": {"limit": 5000, "window": 60},
            "wordpress": {"limit": 1000, "window": 60},
            "betterplace": {"limit": 100, "window": 60},
            "default": {"limit": 100, "window": 60}
        }
    
    async def check_api_key(
        self,
        api_key: str,
        partner: str
    ) -> RateLimitResult:
        """Prüft Rate Limit für API Key"""
        
        limits = self.limiters.get(partner, self.limiters["default"])
        
        config = RateLimitConfig(
            scope=RateLimitScope.API_KEY,
            strategy=RateLimitStrategy.TOKEN_BUCKET,
            limit=limits["limit"],
            window_seconds=limits["window"],
            identifier=f"apikey:{partner}",
            block_duration_seconds=0
        )
        
        limiter = TokenBucketRateLimiter(self.redis)
        return await limiter.is_allowed(f"apikey:{partner}:{api_key[:16]}", config)