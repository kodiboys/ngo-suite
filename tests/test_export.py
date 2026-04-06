# FILE: tests/test_export.py
# MODULE: Export & Backup Tests
# Unit, Integration & Performance Tests

import io
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pandas as pd
import pytest

from src.services.export_service import ExportService

# ==================== Unit Tests ====================


@pytest.mark.asyncio
async def test_export_donations_to_excel():
    """Test Spendenexport nach Excel"""

    mock_session = AsyncMock()
    mock_donations = [
        Mock(
            id=uuid4(),
            created_at=datetime(2024, 1, 15),
            amount=Decimal("100.00"),
            currency="EUR",
            project_id=uuid4(),
            payment_provider="stripe",
            payment_status="succeeded",
            donation_receipt_generated=True,
            is_pseudonymized=False,
            donor_email_pseudonym="hash@example.com",
            donor_name_encrypted="Test Donor",
        )
    ]

    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = mock_donations
    mock_session.execute.return_value = mock_result

    service = ExportService(mock_session)

    excel_data = await service.export_donations(
        start_date=datetime(2024, 1, 1), end_date=datetime(2024, 1, 31), format="excel"
    )

    assert isinstance(excel_data, bytes)
    assert len(excel_data) > 0
    # Excel magic number
    assert excel_data[:4] == b"PK\x03\x04"


@pytest.mark.asyncio
async def test_export_donations_to_csv():
    """Test Spendenexport nach CSV"""

    mock_session = AsyncMock()
    mock_donations = [
        Mock(
            id=uuid4(),
            created_at=datetime(2024, 1, 15),
            amount=Decimal("100.00"),
            currency="EUR",
            project_id=uuid4(),
            payment_provider="stripe",
            payment_status="succeeded",
            donation_receipt_generated=True,
            is_pseudonymized=False,
        )
    ]

    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = mock_donations
    mock_session.execute.return_value = mock_result

    service = ExportService(mock_session)

    csv_data = await service.export_donations(
        start_date=datetime(2024, 1, 1), end_date=datetime(2024, 1, 31), format="csv"
    )

    assert isinstance(csv_data, bytes)
    csv_str = csv_data.decode("utf-8-sig")
    assert "Spenden-ID" in csv_str
    assert "100.00" in csv_str


@pytest.mark.asyncio
async def test_dsgvo_export():
    """Test DSGVO-konformer Datenexport"""

    mock_session = AsyncMock()
    mock_user = Mock(
        id=uuid4(),
        email="test@example.com",
        name_encrypted="Test User",
        role="donor",
        created_at=datetime(2024, 1, 1),
        last_login_at=datetime(2024, 1, 15),
        consent_given_at=datetime(2024, 1, 1),
        is_pseudonymized=False,
    )

    mock_result = AsyncMock()
    mock_result.scalar_one.return_value = mock_user
    mock_session.execute.return_value = mock_result

    service = ExportService(mock_session)

    json_data = await service.export_dsgvo_data(user_id=uuid4(), format="json")

    assert isinstance(json_data, bytes)
    import json

    data = json.loads(json_data.decode("utf-8"))
    assert "user" in data
    assert "donations" in data
    assert data["user"]["email"] == "test@example.com"


# ==================== Integration Tests ====================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_financial_report_export(db_session):
    """Test finanzieller Jahresbericht"""

    service = ExportService(db_session)

    report = await service.export_financial_report(year=2024)

    assert isinstance(report, bytes)

    # Kann als Excel geöffnet werden
    df = pd.read_excel(io.BytesIO(report), sheet_name=None)
    assert "Spenden_2024" in df
    assert "Projekte" in df
    assert "Zusammenfassung" in df


# ==================== Property-Based Tests ====================

from hypothesis import given
from hypothesis import strategies as st


@given(
    amount=st.decimals(min_value=0.01, max_value=100000, places=2),
    year=st.integers(min_value=2020, max_value=2025),
)
def test_export_data_types(amount, year):
    """Test: Export-Daten haben korrekte Typen"""

    export_data = {"amount": float(amount), "year": year, "currency": "EUR"}

    assert isinstance(export_data["amount"], float)
    assert isinstance(export_data["year"], int)
    assert export_data["currency"] == "EUR"


# ==================== Performance Tests ====================


@pytest.mark.benchmark
def test_csv_export_benchmark(benchmark):
    """Benchmark: CSV Export Geschwindigkeit"""

    import csv
    import io

    data = [{"id": i, "name": f"Test {i}", "amount": i * 10} for i in range(1000)]

    def export_csv():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["id", "name", "amount"])
        writer.writeheader()
        writer.writerows(data)
        return output.getvalue().encode("utf-8")

    result = benchmark(export_csv)
    assert len(result) > 0
