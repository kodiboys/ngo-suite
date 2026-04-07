# FILE: src/adapters/api.py
# MODULE: FastAPI Application Factory

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from src.core.config import settings
from src.middleware.rate_limit_middleware import RateLimitMiddleware
from src.monitoring.metrics import PrometheusMiddleware, metrics_endpoint

# Import all routers
from src.adapters import (
    api_compliance,
    api_events,
    api_export,
    api_inventory,
    api_payments,
    api_rate_limits,
    api_reports,
    api_social,
)
from src.api import transparenz


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan manager for startup/shutdown events"""
    # Startup
    settings.ensure_directories()
    print(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"Environment: {settings.ENVIRONMENT}")
    yield
    # Shutdown
    print(f"Shutting down {settings.APP_NAME}")


def create_application() -> FastAPI:
    """Create and configure FastAPI application"""
    
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Enterprise NGO Plattform für Transparenz, Spendenmanagement und Ukraine-Hilfe",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        lifespan=lifespan,
    )
    
    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Trusted Host Middleware
    if settings.is_production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["api.angels4ukraine.de", "*.angels4ukraine.de"],
        )
    
    # Rate Limiting Middleware
    app.add_middleware(RateLimitMiddleware)
    
    # Prometheus Metrics
    app.add_middleware(PrometheusMiddleware)
    app.add_route("/metrics", metrics_endpoint)
    
    # Health Check
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": settings.APP_VERSION}
    
    # Root endpoint
    @app.get("/")
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "docs": "/docs" if settings.is_development else None,
        }
    
    # Register routers
    app.include_router(api_compliance.router)
    app.include_router(api_events.router)
    app.include_router(api_export.router)
    app.include_router(api_inventory.router)
    app.include_router(api_payments.router)
    app.include_router(api_rate_limits.router)
    app.include_router(api_reports.router)
    app.include_router(api_social.router)
    app.include_router(transparenz.router)
    
    return app


# Create application instance
app = create_application()


def main():
    """Entry point for running the application"""
    import uvicorn
    
    uvicorn.run(
        "src.adapters.api:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        workers=settings.API_WORKERS,
        reload=settings.is_development,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()