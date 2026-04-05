# FILE: src/monitoring/metrics.py
# MODULE: Prometheus Metrics & OpenTelemetry Integration
# Enterprise Monitoring mit Metriken, Tracing, Logging

import logging
import time

from fastapi import Request, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# ==================== Prometheus Metrics ====================

# HTTP Request Metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
)

http_requests_in_progress = Gauge(
    'http_requests_in_progress',
    'HTTP requests currently in progress',
    ['method']
)

# Database Metrics
db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query duration in seconds',
    ['query_type'],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
)

db_pool_connections = Gauge(
    'db_pool_connections',
    'Database pool connections',
    ['state']  # active, idle, total
)

# Business Metrics
donations_total = Counter(
    'donations_total',
    'Total number of donations',
    ['status', 'payment_provider']
)

donations_amount_total = Counter(
    'donations_amount_total',
    'Total donation amount in EUR',
    ['currency']
)

projects_active = Gauge(
    'projects_active',
    'Number of active projects'
)

inventory_items_total = Gauge(
    'inventory_items_total',
    'Total number of inventory items',
    ['category']
)

low_stock_items = Gauge(
    'low_stock_items',
    'Number of items with low stock'
)

# Compliance Metrics
four_eyes_pending = Gauge(
    'four_eyes_pending',
    'Number of pending four-eyes approvals'
)

money_laundering_alerts = Counter(
    'money_laundering_alerts',
    'Number of money laundering alerts',
    ['risk_level']
)

# Payment Metrics
payment_success_total = Counter(
    'payment_success_total',
    'Successful payments',
    ['provider']
)

payment_failure_total = Counter(
    'payment_failure_total',
    'Failed payments',
    ['provider', 'error_type']
)

payment_duration_seconds = Histogram(
    'payment_duration_seconds',
    'Payment processing duration',
    ['provider'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

# Rate Limiting Metrics
rate_limit_hits = Counter(
    'rate_limit_hits',
    'Rate limit hits',
    ['scope', 'endpoint']
)

rate_limit_remaining = Gauge(
    'rate_limit_remaining',
    'Remaining rate limit quota',
    ['scope', 'key']
)

# Circuit Breaker Metrics
circuit_breaker_state = Gauge(
    'circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=open, 2=half_open)',
    ['service']
)

circuit_breaker_failures = Counter(
    'circuit_breaker_failures',
    'Circuit breaker failures',
    ['service']
)

# Cache Metrics
cache_hits = Counter(
    'cache_hits_total',
    'Cache hits',
    ['cache_name']
)

cache_misses = Counter(
    'cache_misses_total',
    'Cache misses',
    ['cache_name']
)

# Background Task Metrics
celery_tasks_total = Counter(
    'celery_tasks_total',
    'Celery tasks executed',
    ['task_name', 'status']
)

celery_task_duration_seconds = Histogram(
    'celery_task_duration_seconds',
    'Celery task duration',
    ['task_name'],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0]
)


# ==================== Prometheus Middleware ====================

class PrometheusMiddleware(BaseHTTPMiddleware):
    """Middleware für Prometheus Metriken"""

    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path

        # Increment in-progress counter
        http_requests_in_progress.labels(method=method).inc()

        start_time = time.time()

        try:
            response = await call_next(request)
            status = response.status_code

            # Record metrics
            http_requests_total.labels(
                method=method,
                endpoint=path,
                status=status
            ).inc()

            http_request_duration_seconds.labels(
                method=method,
                endpoint=path
            ).observe(time.time() - start_time)

            return response

        except Exception:
            # Record error
            http_requests_total.labels(
                method=method,
                endpoint=path,
                status=500
            ).inc()
            raise

        finally:
            http_requests_in_progress.labels(method=method).dec()


# ==================== OpenTelemetry Setup ====================

def setup_opentelemetry(app, db_engine, redis_client):
    """Setup OpenTelemetry für Distributed Tracing"""

    # Set up tracer provider
    tracer_provider = TracerProvider()

    # OTLP Exporter (für Jaeger, Tempo, etc.)
    otlp_exporter = OTLPSpanExporter(endpoint="http://tempo:4318/v1/traces")
    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)

    trace.set_tracer_provider(tracer_provider)

    # Instrument FastAPI
    FastAPIInstrumentor.instrument_app(app)

    # Instrument SQLAlchemy
    SQLAlchemyInstrumentor().instrument(
        engine=db_engine,
        tracer_provider=tracer_provider
    )

    # Instrument Redis
    RedisInstrumentor().instrument(
        redis_client=redis_client,
        tracer_provider=tracer_provider
    )

    # Instrument HTTPX
    HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)

    logger.info("OpenTelemetry instrumentation configured")

    return trace.get_tracer("trueangels")


# ==================== Metrics Endpoint ====================

async def metrics_endpoint(request: Request) -> Response:
    """Prometheus Metrics Endpoint"""
    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain"
    )


# ==================== Business Metrics Recording ====================

class MetricsRecorder:
    """Helper für Business Metrics Recording"""

    @staticmethod
    def record_donation(status: str, provider: str, amount: float):
        """Record donation metrics"""
        donations_total.labels(status=status, payment_provider=provider).inc()
        if status == "succeeded":
            donations_amount_total.labels(currency="EUR").inc(amount)

    @staticmethod
    def record_payment(provider: str, success: bool, error_type: str = None, duration: float = None):
        """Record payment metrics"""
        if success:
            payment_success_total.labels(provider=provider).inc()
        else:
            payment_failure_total.labels(provider=provider, error_type=error_type or "unknown").inc()

        if duration:
            payment_duration_seconds.labels(provider=provider).observe(duration)

    @staticmethod
    def record_rate_limit(scope: str, endpoint: str, remaining: int, key: str):
        """Record rate limit metrics"""
        rate_limit_hits.labels(scope=scope, endpoint=endpoint).inc()
        rate_limit_remaining.labels(scope=scope, key=key).set(remaining)

    @staticmethod
    def record_cache(cache_name: str, hit: bool):
        """Record cache metrics"""
        if hit:
            cache_hits.labels(cache_name=cache_name).inc()
        else:
            cache_misses.labels(cache_name=cache_name).inc()

    @staticmethod
    def update_project_gauge(count: int):
        """Update active projects gauge"""
        projects_active.set(count)

    @staticmethod
    def update_inventory_gauge(category: str, count: int):
        """Update inventory items gauge"""
        inventory_items_total.labels(category=category).set(count)

    @staticmethod
    def update_low_stock_gauge(count: int):
        """Update low stock items gauge"""
        low_stock_items.set(count)

    @staticmethod
    def update_four_eyes_pending(count: int):
        """Update pending four-eyes approvals gauge"""
        four_eyes_pending.set(count)

    @staticmethod
    def record_money_laundering_alert(risk_level: str):
        """Record money laundering alert"""
        money_laundering_alerts.labels(risk_level=risk_level).inc()

    @staticmethod
    def update_circuit_breaker(service: str, state: str):
        """Update circuit breaker state"""
        state_map = {"closed": 0, "open": 1, "half_open": 2, "forced_open": 1}
        circuit_breaker_state.labels(service=service).set(state_map.get(state, 0))

    @staticmethod
    def record_celery_task(task_name: str, status: str, duration: float):
        """Record celery task metrics"""
        celery_tasks_total.labels(task_name=task_name, status=status).inc()
        celery_task_duration_seconds.labels(task_name=task_name).observe(duration)
