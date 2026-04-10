# FILE: src/core/entities/base.py
# MODULE: Core Entities & DB Schema (SKR42 mit Kostenträgern, Event Sourcing, RLS)
# Enterprise Base Entities mit Event Sourcing & Row-Level Security
# Compliance: GoBD §147, DSGVO Art.17, HGB §257
# Version: 3.0.0 - Vollständig korrigiert (keine reservierten Namen)

from datetime import datetime
from uuid import uuid4
from enum import Enum

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Numeric,
    Boolean,
    ForeignKey,
    Index,
    CheckConstraint,
    UniqueConstraint,
    Text,
    Integer,
    BigInteger,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, validates
import hashlib

Base = declarative_base()


# ==================== ENUMS (Enterprise) ====================


class TransactionType(str, Enum):
    """GoBD-konforme Buchungstypen"""

    SPENDE = "spende"
    ZUSCHUSS = "zuschuss"
    SACHSPENDE = "sachspende"
    AUSGABE_PROJEKT = "ausgabe_projekt"
    VERWALTUNG = "verwaltung"
    RÜCKLASTSCHRIFT = "ruecklastschrift"


class AuditAction(str, Enum):
    """Audit-Aktionen für Compliance"""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    PSEUDONYMIZE = "PSEUDONYMIZE"
    RESTORE = "RESTORE"
    EXPORT = "EXPORT"
    FOUR_EYES = "FOUR_EYES_APPROVAL"
    TRANSPARENCY_CONSENT = "TRANSPARENCY_CONSENT"


class ComplianceStatus(str, Enum):
    """Compliance-Status für Transaktionen"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged_money_laundering"
    AUDIT_REQUIRED = "audit_required"


class UserRole(str, Enum):
    """Benutzerrollen für RBAC"""

    ADMIN = "admin"
    ACCOUNTANT = "accountant"
    DONOR = "donor"
    PROJECT_MANAGER = "project_manager"
    AUDITOR = "auditor"
    COMPLIANCE_OFFICER = "compliance_officer"


class PaymentStatus(str, Enum):
    """Status einer Zahlung"""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    DISPUTED = "disputed"
    CHARGEBACK = "chargeback"


# ==================== SKR42 KOSTENTRÄGER ====================


class SKR42Account(Base):
    __tablename__ = "skr42_accounts"
    __table_args__ = (
        Index("idx_account_number_costcenter", "account_number", "cost_center"),
        UniqueConstraint("account_number", "cost_center", name="uq_account_costcenter"),
        CheckConstraint("account_number BETWEEN '10000' AND '99999'", name="ck_valid_account"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_number = Column(String(5), nullable=False)
    account_name = Column(String(200), nullable=False)
    account_type = Column(String(50), nullable=False)
    cost_center = Column(String(50), nullable=True)
    project_id = Column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    parent_account_number = Column(
        String(5), ForeignKey("skr42_accounts.account_number"), nullable=True
    )
    level = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    requires_four_eyes = Column(Boolean, default=False)
    tax_code = Column(String(10), nullable=True)
    show_in_transparency = Column(Boolean, default=True)
    transparency_description = Column(Text, nullable=True)
    previous_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    projects = relationship("Project", back_populates="skr42_account")

    @validates("account_number")
    def validate_account_number(self, key, number):
        if not number.isdigit() or len(number) != 5:
            raise ValueError(f"Ungültige Kontonummer: {number}")
        return number

    def compute_hash(self) -> str:
        data = f"{self.account_number}|{self.cost_center}|{self.account_name}|{self.updated_at}"
        return hashlib.sha256(data.encode()).hexdigest()


# ==================== SPENDE MIT EVENT SOURCING ====================


class Donation(Base):
    __tablename__ = "donations"
    __table_args__ = (
        Index("idx_donor_email_pseudonym", "donor_email_pseudonym"),
        Index("idx_project_payment_status", "project_id", "payment_status"),
        Index("idx_compliance_flag", "compliance_status"),
        Index("idx_transparency_hash", "transparency_hash"),
        Index("idx_consent_transparenz", "consent_transparenz"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    status = Column(String(20), default="draft", index=True)  # ← HIER!

    donor_email_pseudonym = Column(String(255), nullable=False)
    donor_name_encrypted = Column(Text, nullable=True)
    donor_address_encrypted = Column(Text, nullable=True)

    project_id = Column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    skr42_account_id = Column(PGUUID(as_uuid=True), ForeignKey("skr42_accounts.id"), nullable=False)
    cost_center = Column(String(50), nullable=False)
    need_id = Column(
        PGUUID(as_uuid=True), ForeignKey("project_needs.id", ondelete="SET NULL"), nullable=True
    )
    consent_transparenz = Column(Boolean, default=False, nullable=False)
    transparency_hash = Column(String(20), nullable=True)

    amount = Column(Numeric(12, 2), nullable=False)
    transaction_type = Column(String(50), nullable=False, default=TransactionType.SPENDE)
    currency = Column(String(3), default="EUR")

    payment_provider = Column(String(20), nullable=False)
    payment_intent_id = Column(String(255), nullable=False, unique=True)
    payment_status = Column(String(50), default=PaymentStatus.PENDING.value)

    compliance_status = Column(String(50), default=ComplianceStatus.PENDING)
    four_eyes_approved_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    four_eyes_approved_at = Column(DateTime, nullable=True)
    money_laundering_flag = Column(Boolean, default=False)

    tax_deductible = Column(Boolean, default=True)
    tax_id = Column(String(20), nullable=True)
    donation_receipt_generated = Column(Boolean, default=False)

    previous_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=False)
    blockchain_tx_id = Column(String(255), nullable=True)

    is_pseudonymized = Column(Boolean, default=False)
    pseudonymized_at = Column(DateTime, nullable=True)
    deletion_requested_at = Column(DateTime, nullable=True)

    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="donations")
    account = relationship("SKR42Account")

    @validates("amount")
    def validate_amount(self, key, amount):
        if amount <= 0:
            raise ValueError("Spendenbetrag muss positiv sein")
        if amount > 10000 and not self.money_laundering_flag:
            self.money_laundering_flag = True
            self.compliance_status = ComplianceStatus.FLAGGED
        return amount

    def compute_hash(self) -> str:
        data = f"{self.id}|{self.amount}|{self.payment_intent_id}|{self.updated_at}|{self.donor_email_pseudonym}"
        return hashlib.sha256(data.encode()).hexdigest()

    def pseudonymize(self):
        self.donor_email_pseudonym = hashlib.sha256(self.donor_email_pseudonym.encode()).hexdigest()
        self.donor_name_encrypted = None
        self.donor_address_encrypted = None
        self.is_pseudonymized = True
        self.pseudonymized_at = datetime.utcnow()

    def generate_transparency_hash(self, salt: str = None) -> str:
        if salt is None:
            salt = str(datetime.utcnow().year)
        import hmac

        hash_obj = hmac.new(salt.encode(), self.donor_email_pseudonym.encode(), hashlib.sha256)
        hash_hex = hash_obj.hexdigest()[:6].upper()
        self.transparency_hash = f"SPENDER-{hash_hex}"
        return self.transparency_hash


# ==================== EVENT SOURCING ====================




# ==================== AUDIT LOG ====================


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_entity_timestamp", "entity_type", "entity_id", "timestamp"),
        Index("idx_user_action", "user_id", "action"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    old_values = Column(JSONB, nullable=True)
    new_values = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=False)
    user_agent = Column(String(500), nullable=True)
    reason = Column(String(500), nullable=True)
    requires_four_eyes = Column(Boolean, default=False)
    four_eyes_approved = Column(Boolean, default=False)
    four_eyes_by = Column(PGUUID(as_uuid=True), nullable=True)
    retention_until = Column(DateTime, nullable=False)
    is_archived = Column(Boolean, default=False)
    archived_at = Column(DateTime, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="audit_logs")


# ==================== PROJEKTE ====================


class Project(Base):
    __tablename__ = "projects"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    transparency_description = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    show_on_transparency = Column(Boolean, default=True)
    cost_center = Column(String(50), nullable=False, unique=True)
    skr42_account_id = Column(PGUUID(as_uuid=True), ForeignKey("skr42_accounts.id"), nullable=False)
    budget_total = Column(Numeric(12, 2), default=0)
    budget_used = Column(Numeric(12, 2), default=0)
    donations_total = Column(Numeric(12, 2), default=0)
    status = Column(String(20), default="active")
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=True)
    requires_four_eyes = Column(Boolean, default=True)
    needs_alert_config = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    skr42_account = relationship("SKR42Account", back_populates="projects")
    donations = relationship("Donation", back_populates="project")
    inventory_items = relationship("InventoryItem", back_populates="project")


# ==================== USER MODELL ====================


class User(Base):
    __tablename__ = "users"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False)
    email_verified = Column(Boolean, default=False)
    password_hash = Column(String(255), nullable=False)
    name_encrypted = Column(Text, nullable=True)
    phone_encrypted = Column(Text, nullable=True)
    role = Column(String(50), nullable=False, default=UserRole.DONOR)
    permissions = Column(JSONB, default=list)
    mfa_enabled = Column(Boolean, default=False)
    mfa_secret = Column(String(255), nullable=True)
    telegram_chat_id = Column(String(100), nullable=True)
    notification_preferences = Column(JSONB, nullable=True)
    consent_given_at = Column(DateTime, nullable=True)
    consent_withdrawn_at = Column(DateTime, nullable=True)
    is_pseudonymized = Column(Boolean, default=False)
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    audit_logs = relationship("AuditLog", back_populates="user")

    def pseudonymize(self):
        self.email = hashlib.sha256(self.email.encode()).hexdigest()
        self.name_encrypted = None
        self.phone_encrypted = None
        self.is_pseudonymized = True
