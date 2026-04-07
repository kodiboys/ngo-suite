# FILE: tests/test_reports.py
# MODULE: Report Generation Tests
# Testet PDF-Generierung, Exporte, Bilanzierung

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from reportlab.lib.pagesizes import A4

from src.services.accounting import AccountingService, ExportService
from src.services.pdf_generator import (
    DonationReceiptGenerator,
    SKR42BalanceSheetGenerator,
)


@pytest.mark.asyncio
async def test_donation_receipt_generation():
    """Test Zuwendungsbescheinigung PDF-Generierung"""

    mock_session = AsyncMock()
    mock_donation = Mock(
        id=uuid4(),
        amount=Decimal("100.00"),
        created_at=datetime(2024, 1, 15),
        payment_intent_id="pi_123",
        donor_name_encrypted="Max Mustermann",
        donor_email_pseudonym="hash@example.com",
    )
    mock_project = Mock(name="Testprojekt")

    mock_session.execute.return_value.scalar_one.return_value = mock_donation
    mock_session.get.return_value = mock_project

    generator = DonationReceiptGenerator(mock_session)

    with patch.object(generator, "_generate_qr_code", return_value=Mock()):
        pdf_bytes = await generator.generate_donation_receipt(uuid4())

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0
        # PDF Header
        assert pdf_bytes[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_balance_sheet_generation():
    """Test SKR42 Bilanz-Generierung"""

    mock_session = AsyncMock()

    # Mock SKR42 Accounts
    mock_accounts = [
        Mock(account_number="10000", account_name="Kasse", is_active=True, level=0),
        Mock(account_number="12000", account_name="Bank", is_active=True, level=0),
        Mock(account_number="40000", account_name="Spenden", is_active=True, level=0),
    ]
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = mock_accounts
    mock_session.execute.return_value = mock_result

    generator = SKR42BalanceSheetGenerator(mock_session)

    with patch.object(
        generator,
        "_get_balance_data",
        return_value={
            "active": [{"account_number": "10000", "account_name": "Kasse", "balance": 5000}],
            "passive": [{"account_number": "40000", "account_name": "Spenden", "balance": 5000}],
            "donations_total": 5000,
            "project_cost_ratio": 75.0,
        },
    ):
        pdf_bytes = await generator.generate_balance_sheet()

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0


@pytest.mark.asyncio
async def test_datev_export():
    """Test DATEV CSV-Export"""

    mock_session = AsyncMock()
    mock_donations = [
        Mock(
            amount=Decimal("100.00"),
            created_at=datetime(2024, 1, 15),
            payment_intent_id="pi_123",
            skr42_account_id="40000",
            cost_center="PROJ_001",
        )
    ]
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = mock_donations
    mock_session.execute.return_value = mock_result

    service = AccountingService(mock_session, Mock())

    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 31)

    csv_bytes = await service.export_datev_csv(start_date, end_date)

    assert isinstance(csv_bytes, bytes)
    csv_content = csv_bytes.decode("utf-8-sig")
    assert "Umsatz (ohne Soll/Haben-Kz)" in csv_content
    assert "100,00" in csv_content


@pytest.mark.asyncio
async def test_excel_export():
    """Test Excel-Export"""

    service = ExportService(None)

    test_data = [{"Name": "Test", "Betrag": 100.00, "Datum": "2024-01-15"}]

    excel_bytes = await service.export_to_excel(test_data, "Test Sheet")

    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 0
    # Excel Magic Number
    assert excel_bytes[:4] == b"PK\x03\x04"


@pytest.mark.asyncio
async def test_number_to_words():
    """Test Zahlen-in-Worte Konvertierung"""

    generator = DonationReceiptGenerator(None)

    assert generator._int_to_words(1) == "ein"
    assert generator._int_to_words(15) == "fünfzehn"
    assert generator._int_to_words(23) == "dreiundzwanzig"
    assert generator._int_to_words(100) == "einhundert"
    assert generator._int_to_words(123) == "einhundertdreiundzwanzig"


def test_skr42_account_validation():
    """Test SKR42 Konto-Validierung"""
    from src.core.entities.base import SKR42Account

    account = SKR42Account(
        account_number="40000", account_name="Spenden", account_type="ERTRAEGE", current_hash="test"
    )

    assert account.account_number == "40000"

    with pytest.raises(ValueError):
        account.account_number = "123"  # Zu kurz


# ==================== Performance Tests ====================


@pytest.mark.benchmark
def test_pdf_generation_benchmark(benchmark):
    """Benchmark: PDF-Generierungsgeschwindigkeit"""

    def generate_pdf():
        # Simuliere PDF-Generierung
        from io import BytesIO

        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        story = [Paragraph("Test", getSampleStyleSheet()["Normal"])]
        doc.build(story)
        return buffer.getvalue()

    result = benchmark(generate_pdf)
    assert len(result) > 0
