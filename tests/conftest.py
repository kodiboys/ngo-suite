# FILE: tests/conftest.py
# MODULE: Pytest Konfiguration & Shared Fixtures
# Enterprise Test Setup mit Fixtures, Mocks, Test-Datenbanken

import asyncio
import pytest
from typing import AsyncGenerator, Generator
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
import hashlib

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
import redis.asyncio as redis
import fakeredis.aioredis

from src.adapters.api import app
from src.core.entities.base import Base, User, Donation, Project, SKR42Account
from src.core.entities.inventory import InventoryItem, StockMovement, PackingList
from src.core.compliance.base import FourEyesApproval, MoneyLaunderingCheck
from src.core.events.event_store import EventStoreDB
from src.services.auth import get_password_hash


# ==================== Test Database ====================


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    """Create test database engine"""
    # In-memory SQLite für schnelle Tests (oder PostgreSQL für Integration)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False, poolclass=NullPool)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session"""
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session
        await session.rollback()


# ==================== Redis Fixtures ====================


@pytest.fixture
async def redis_client():
    """Create fake Redis client for testing"""
    client = await fakeredis.aioredis.create_redis_pool()
    yield client
    client.close()
    await client.wait_closed()


# ==================== FastAPI Client ====================


@pytest.fixture
def client() -> Generator:
    """Create FastAPI test client"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def async_client():
    """Async HTTP client for testing"""
    from httpx import AsyncClient

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


# ==================== Test Data Fixtures ====================


@pytest.fixture
async def test_user(db_session) -> User:
    """Create test user"""
    user = User(
        email="test@trueangels.de",
        password_hash=get_password_hash("test123"),
        role="admin",
        email_verified=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_project(db_session, test_user) -> Project:
    """Create test project"""
    # Create SKR42 account first
    skr42_account = SKR42Account(
        account_number="40000",
        account_name="Test Spenden",
        account_type="ERTRAEGE",
        current_hash="test",
    )
    db_session.add(skr42_account)
    await db_session.flush()

    project = Project(
        name="Test Project",
        description="Test Description",
        cost_center="TEST_001",
        skr42_account_id=skr42_account.id,
        budget_total=Decimal("10000"),
        start_date=datetime.utcnow(),
        status="active",
        created_by=test_user.id,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def test_donation(db_session, test_user, test_project) -> Donation:
    """Create test donation"""
    donor_email_hash = hashlib.sha256("donor@example.com".encode()).hexdigest()

    donation = Donation(
        donor_email_pseudonym=donor_email_hash,
        donor_name_encrypted="Test Donor",
        project_id=test_project.id,
        skr42_account_id=test_project.skr42_account_id,
        cost_center=test_project.cost_center,
        amount=Decimal("100.00"),
        transaction_type="spende",
        payment_provider="stripe",
        payment_intent_id=f"pi_{uuid4().hex[:12]}",
        payment_status="succeeded",
        created_by=test_user.id,
        current_hash="test",
    )
    db_session.add(donation)
    await db_session.commit()
    await db_session.refresh(donation)
    return donation


@pytest.fixture
async def test_inventory_item(db_session, test_project, test_user) -> InventoryItem:
    """Create test inventory item"""
    item = InventoryItem(
        name="Test Item",
        sku="TEST-001",
        category="food",
        condition="new",
        project_id=test_project.id,
        cost_center=test_project.cost_center,
        quantity=100,
        min_stock_level=10,
        unit_price=Decimal("5.99"),
        created_by=test_user.id,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


# ==================== Auth Token Fixture ====================


@pytest.fixture
async def auth_token(client, test_user) -> str:
    """Get authentication token for test user"""
    response = client.post(
        "/api/v1/auth/login", json={"email": "test@trueangels.de", "password": "test123"}
    )
    return response.json().get("access_token")


@pytest.fixture
def auth_headers(auth_token) -> dict:
    """Get authentication headers"""
    return {"Authorization": f"Bearer {auth_token}"}


# ==================== Mock Fixtures ====================


@pytest.fixture
def mock_stripe():
    """Mock Stripe API calls"""
    with patch("stripe.PaymentIntent.create") as mock:
        mock.return_value.id = "pi_mock_123"
        mock.return_value.client_secret = "secret_mock"
        mock.return_value.amount = 10000
        mock.return_value.status = "requires_payment_method"
        yield mock


@pytest.fixture
def mock_paypal():
    """Mock PayPal API calls"""
    with patch("httpx.AsyncClient.post") as mock:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "pay_mock_123"}
        mock.return_value = mock_response
        yield mock


# ==================== Cleanup ====================


@pytest.fixture(autouse=True)
async def cleanup_db(db_session):
    """Clean database after each test"""
    yield
    # Rollback happens automatically in db_session fixture
