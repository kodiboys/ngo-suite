# FILE: tests/test_unit/test_models.py
# MODULE: Unit Tests für Datenbankmodelle
# Testet Validierung, Beziehungen, Geschäftslogik

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from src.core.compliance.base import FourEyesApproval, MoneyLaunderingCheck
from src.core.entities.base import Donation
from src.core.entities.inventory import InventoryItem


class TestDonationModel:
    """Tests für Donation Model"""

    def test_donation_creation(self, test_user, test_project):
        """Test Donation Erstellung"""
        donor_hash = hashlib.sha256(b"test@example.com").hexdigest()

        donation = Donation(
            donor_email_pseudonym=donor_hash,
            project_id=test_project.id,
            skr42_account_id=test_project.skr42_account_id,
            cost_center=test_project.cost_center,
            amount=Decimal("100.00"),
            payment_provider="stripe",
            payment_intent_id="pi_123",
            created_by=test_user.id
        )

        assert donation.amount == Decimal("100.00")
        assert donation.payment_status == "pending"
        assert donation.donation_receipt_generated is False

    def test_donation_amount_validation(self, test_user, test_project):
        """Test Betragsvalidierung"""
        with pytest.raises(ValueError):
            donation = Donation(
                donor_email_pseudonym="hash",
                project_id=test_project.id,
                skr42_account_id=test_project.skr42_account_id,
                cost_center=test_project.cost_center,
                amount=Decimal("-10.00"),  # Negativer Betrag
                payment_provider="stripe",
                payment_intent_id="pi_123",
                created_by=test_user.id
            )

    def test_donation_money_laundering_flag(self, test_user, test_project):
        """Test Geldwäsche-Flag bei hohen Beträgen"""
        donation = Donation(
            donor_email_pseudonym="hash",
            project_id=test_project.id,
            skr42_account_id=test_project.skr42_account_id,
            cost_center=test_project.cost_center,
            amount=Decimal("15000.00"),  # > 10.000€
            payment_provider="stripe",
            payment_intent_id="pi_123",
            created_by=test_user.id
        )

        assert donation.money_laundering_flag is True
        assert donation.compliance_status == "flagged_money_laundering"

    def test_donation_hash_computation(self, test_user, test_project):
        """Test Merkle-Hash Berechnung"""
        donation = Donation(
            donor_email_pseudonym="hash",
            project_id=test_project.id,
            skr42_account_id=test_project.skr42_account_id,
            cost_center=test_project.cost_center,
            amount=Decimal("100.00"),
            payment_provider="stripe",
            payment_intent_id="pi_123",
            created_by=test_user.id
        )

        hash1 = donation.compute_hash()
        donation.amount = Decimal("200.00")
        hash2 = donation.compute_hash()

        assert hash1 != hash2
        assert len(hash1) == 64  # SHA256


class TestInventoryModel:
    """Tests für Inventory Model"""

    def test_inventory_item_creation(self, test_project, test_user):
        """Test Inventory Item Erstellung"""
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
            created_by=test_user.id
        )

        assert item.available_quantity == 100
        assert item.status == "in_stock"

    def test_inventory_item_low_stock(self, test_project, test_user):
        """Test Niedrigbestandserkennung"""
        item = InventoryItem(
            name="Test Item",
            sku="TEST-001",
            category="food",
            project_id=test_project.id,
            cost_center=test_project.cost_center,
            quantity=5,
            min_stock_level=10,
            created_by=test_user.id
        )

        item.update_stock_status()
        assert item.status == "low_stock"

    def test_inventory_item_out_of_stock(self, test_project, test_user):
        """Test Out-of-Stock Erkennung"""
        item = InventoryItem(
            name="Test Item",
            sku="TEST-001",
            category="food",
            project_id=test_project.id,
            cost_center=test_project.cost_center,
            quantity=0,
            min_stock_level=10,
            created_by=test_user.id
        )

        item.update_stock_status()
        assert item.status == "out_of_stock"

    def test_inventory_item_reserved_quantity(self, test_project, test_user):
        """Test Reservierte Menge"""
        item = InventoryItem(
            name="Test Item",
            sku="TEST-001",
            category="food",
            project_id=test_project.id,
            cost_center=test_project.cost_center,
            quantity=100,
            reserved_quantity=30,
            created_by=test_user.id
        )

        assert item.available_quantity == 70


class TestComplianceModel:
    """Tests für Compliance Model"""

    def test_four_eyes_approval_creation(self, test_user):
        """Test 4-Augen-Freigabe"""
        approval = FourEyesApproval(
            entity_type="donation",
            entity_id=uuid4(),
            amount=Decimal("7500.00"),
            reason="Test transaction",
            initiator_id=test_user.id,
            approver_1_id=uuid4(),
            expires_at=datetime.utcnow() + timedelta(hours=48)
        )

        assert approval.status == "pending"
        assert approval.days_pending == 0
        assert approval.is_fully_approved is False

    def test_money_laundering_risk_calculation(self):
        """Test Geldwäsche-Risikoberechnung"""
        ml_check = MoneyLaunderingCheck(
            entity_type="donation",
            entity_id=uuid4(),
            amount=Decimal("25000.00"),
            donor_country="RU",
            payment_method="crypto"
        )

        risk_score = ml_check.calculate_risk_score()

        assert risk_score >= 60
        assert ml_check.risk_level in ["high", "critical"]
