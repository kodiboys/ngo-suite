# FILE: tests/test_inventory.py
# MODULE: Inventory Tests
# Unit, Integration & Property-Based Tests für Lagerverwaltung

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from hypothesis import given
from hypothesis import strategies as st

import pytest

from src.core.entities.inventory import (
    InventoryItem,
    InventoryItemCreate,
    ItemCategory,
    ItemCondition,
    StockMovementCreate,
    StockMovementType,
    StockStatus,
)
from src.services.inventory_service import InventoryService

# ==================== Unit Tests ====================


@pytest.mark.asyncio
async def test_create_inventory_item():
    """Test Erstellung eines Lagerartikels"""

    item_data = InventoryItemCreate(
        name="Test Item",
        sku="TEST-001",
        category=ItemCategory.FOOD,
        condition=ItemCondition.NEW,
        project_id=uuid4(),
        quantity=100,
        min_stock_level=10,
        unit_price=Decimal("5.99"),
    )

    # Mock Session
    mock_session = AsyncMock()
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    service = InventoryService(mock_session, None, None)

    with patch.object(service, "_create_skr42_booking_for_movement", AsyncMock()):
        item = await service.create_item(item_data, uuid4())

        assert item.name == "Test Item"
        assert item.sku == "TEST-001"
        assert item.quantity == 100
        assert item.total_value == Decimal("599.00")  # 100 * 5.99


@pytest.mark.asyncio
async def test_stock_movement_inbound():
    """Test Lagerzugang"""

    # Create Item
    item = InventoryItem(
        id=uuid4(), name="Test", sku="TEST", quantity=50, project_id=uuid4(), cost_center="PROJ_001"
    )

    movement = StockMovementCreate(
        item_id=item.id, movement_type=StockMovementType.INBOUND, quantity=25, reason="Test inbound"
    )

    # Mock Session mit Lock
    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalar_one.return_value = item
    mock_session.execute.return_value = mock_result

    service = InventoryService(mock_session, None, None)

    with patch.object(service, "_create_skr42_booking_for_movement", AsyncMock()):
        result = await service.update_stock(movement, uuid4(), "127.0.0.1")

        assert result.quantity == 25
        assert result.previous_quantity == 50
        assert result.new_quantity == 75
        assert item.quantity == 75


@pytest.mark.asyncio
async def test_stock_movement_outbound_insufficient():
    """Test Lagerabgang mit unzureichendem Bestand"""

    item = InventoryItem(
        id=uuid4(),
        name="Test",
        sku="TEST",
        quantity=10,
        reserved_quantity=5,  # 5 verfügbar
        project_id=uuid4(),
        cost_center="PROJ_001",
    )

    movement = StockMovementCreate(
        item_id=item.id,
        movement_type=StockMovementType.OUTBOUND,
        quantity=10,  # Zu viel
        reason="Test outbound",
    )

    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalar_one.return_value = item
    mock_session.execute.return_value = mock_result

    service = InventoryService(mock_session, None, None)

    with pytest.raises(Exception) as exc_info:
        await service.update_stock(movement, uuid4(), "127.0.0.1")

    assert "Nicht genügend Bestand" in str(exc_info.value)


# ==================== Packing List Tests ====================


@pytest.mark.asyncio
async def test_create_packing_list():
    """Test Packlistenerstellung"""

    packing_data = Mock(
        project_id=uuid4(),
        recipient_name="Test Recipient",
        recipient_address="Test Street 123, 12345 Berlin",
        shipping_date=datetime.utcnow(),
        items=[{"item_id": uuid4(), "quantity": 10, "notes": "Test"}],
    )

    mock_session = AsyncMock()
    mock_project = Mock(id=packing_data.project_id, name="Test Project")
    mock_project_result = AsyncMock()
    mock_project_result.scalar_one.return_value = mock_project
    mock_session.execute.return_value = mock_project_result

    mock_item = Mock(
        id=packing_data.items[0]["item_id"],
        name="Test Item",
        sku="TEST-001",
        category=ItemCategory.OTHER,
        condition=ItemCondition.GOOD,
        available_quantity=100,
        reserved_quantity=0,
    )
    mock_item_result = AsyncMock()
    mock_item_result.scalar_one.return_value = mock_item
    mock_session.execute.return_value = mock_item_result

    service = InventoryService(mock_session, None, None)

    with patch(
        "src.services.pdf_generator.generate_packing_list_pdf",
        AsyncMock(return_value="/tmp/test.pdf"),
    ):
        result = await service.create_packing_list(packing_data, uuid4())

        assert result.recipient_name == "Test Recipient"
        assert result.status == "draft"
        assert result.packing_list_number.startswith("PL-")


# ==================== Property-Based Tests ====================

@given(
    quantity=st.integers(min_value=0, max_value=10000),
    reserved=st.integers(min_value=0, max_value=10000),
)
def test_available_quantity_property(quantity, reserved):
    """Test: Verfügbare Menge ist immer Bestand minus Reservierung"""
    if reserved <= quantity:
        item = InventoryItem(quantity=quantity, reserved_quantity=reserved)
        assert item.available_quantity == quantity - reserved
        assert item.available_quantity >= 0


@given(
    quantity=st.integers(min_value=0, max_value=100),
    reorder_point=st.integers(min_value=1, max_value=50),
)
def test_stock_status_property(quantity, reorder_point):
    """Test: Bestandsstatus korrekt basierend auf Menge"""
    item = InventoryItem(quantity=quantity, reorder_point=reorder_point, reserved_quantity=0)
    item.update_stock_status()

    if quantity <= 0:
        assert item.status == StockStatus.OUT_OF_STOCK
    elif quantity <= reorder_point:
        assert item.status == StockStatus.LOW_STOCK
    else:
        assert item.status == StockStatus.IN_STOCK


# ==================== Integration Tests ====================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_inventory_flow(db_session, redis_client):
    """Test vollständigen Inventory Flow"""

    service = InventoryService(db_session, redis_client, Mock())

    # 1. Create Item
    item_data = InventoryItemCreate(
        name="Integration Test Item",
        sku="INT-TEST-001",
        category=ItemCategory.MEDICAL,
        condition=ItemCondition.NEW,
        project_id=uuid4(),
        quantity=100,
        min_stock_level=20,
        unit_price=Decimal("10.00"),
    )

    item = await service.create_item(item_data, uuid4())
    assert item.id is not None
    assert item.quantity == 100

    # 2. Stock Inbound
    inbound = StockMovementCreate(
        item_id=item.id, movement_type=StockMovementType.INBOUND, quantity=50, reason="Test inbound"
    )
    movement = await service.update_stock(inbound, uuid4(), "127.0.0.1")
    assert movement.new_quantity == 150

    # 3. Create Packing List
    packing_data = Mock(
        project_id=item.project_id,
        recipient_name="Test Hospital",
        recipient_address="Medical Street 1, 10115 Berlin",
        shipping_date=datetime.utcnow() + timedelta(days=1),
        items=[{"item_id": item.id, "quantity": 30}],
        notes="Test delivery",
    )

    packing_list = await service.create_packing_list(packing_data, uuid4())
    assert packing_list.status == "draft"

    # 4. Confirm Packing List (reserved stock)
    confirmed = await service.confirm_packing_list(packing_list.id, uuid4())
    assert confirmed.status == "confirmed"

    # 5. Check stock after confirmation
    assert item.reserved_quantity == 30  # Reserviert
    # (In Production: Auch quantity reduziert)

    # 6. Mark as delivered
    delivered = await service.mark_as_delivered(packing_list.id)
    assert delivered.status == "delivered"
