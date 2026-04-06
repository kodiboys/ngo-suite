# FILE: src/core/entities/base.py
# MODULE: Core Entities & DB Schema (SKR42 mit Kostenträgern, Event Sourcing, RLS)
# Enterprise Base Entities mit Event Sourcing & Row-Level Security
# Compliance: GoBD §147, DSGVO Art.17, HGB §257
# Version: 3.0 - Erweitert um Transparenz-Features & Bedarfe

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, validator
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, validates

Base = declarative_base()


# ==================== ENUMS (Enterprise) ====================


class TransactionType(str, Enum):
    """GoBD-konforme Buchungstypen"""

    SPENDE = "spende"  # 40000-49999
    ZUSCHUSS = "zuschuss"  # 41000-41999
    SACHSPENDE = "sachspende"  # 42000-42999
    AUSGABE_PROJEKT = "ausgabe_projekt"  # 70000-79999
    VERWALTUNG = "verwaltung"  # 60000-69999
    RÜCKLASTSCHRIFT = "ruecklastschrift"  # 49000-49999


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


# ==================== SKR42 KOSTENTRÄGER (Option B+C) ====================


class SKR42Account(Base):
    """
    SKR42 Kontenrahmen mit Kostenträger-Dimension
    DATEV-Export-kompatibel: Konto 40000 + Kostenträger "PROJ_001"

    Erweiterung v3.0:
    - Transparenz-Flag für öffentliche Berichte
    - Verknüpfung mit Projekten für Bedarfe
    """

    __tablename__ = "skr42_accounts"
    __table_args__ = (
        Index("idx_account_number_costcenter", "account_number", "cost_center"),
        UniqueConstraint("account_number", "cost_center", name="uq_account_costcenter"),
        CheckConstraint("account_number BETWEEN '10000' AND '99999'", name="ck_valid_account"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_number = Column(String(5), nullable=False)  # 40000-49999 für Spenden
    account_name = Column(String(200), nullable=False)
    account_type = Column(String(50), nullable=False)  # ACTIVA, PASIVA, ERTRAEGE, AUFWENDUNGEN

    # Kostenträger (Projektverknüpfung)
    cost_center = Column(String(50), nullable=True)  # PROJ_001, PROJ_002
    project_id = Column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )

    # Hierarchie
    parent_account_number = Column(
        String(5), ForeignKey("skr42_accounts.account_number"), nullable=True
    )
    level = Column(Integer, default=0)  # 0=Hauptkonto, 1=Unterkonto

    # Compliance
    is_active = Column(Boolean, default=True)
    requires_four_eyes = Column(Boolean, default=False)  # >5000€ Buchungen
    tax_code = Column(String(10), nullable=True)  # USt-Identifikation

    # Transparenz (v3.0)
    show_in_transparency = Column(Boolean, default=True)  # Auf Transparenzseite anzeigen
    transparency_description = Column(Text, nullable=True)  # Beschreibung für Spender

    # Merkle-Tree (Manipulationssicherheit)
    previous_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=False)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    projects = relationship("Project", back_populates="skr42_account")
    transactions = relationship("Transaction", back_populates="account")

    @validates("account_number")
    def validate_account_number(self, key, number):
        """GoBD: Korrekte Kontenklasse"""
        if not number.isdigit() or len(number) != 5:
            raise ValueError(f"Ungültige Kontonummer: {number}")
        return number

    def compute_hash(self) -> str:
        """Merkle-Tree Hash für manipulationssichere Buchhaltung"""
        data = f"{self.account_number}|{self.cost_center}|{self.account_name}|{self.updated_at}"
        return hashlib.sha256(data.encode()).hexdigest()


# ==================== SPENDE MIT EVENT SOURCING ====================


class Donation(Base):
    """
    Spenden-Entity mit Event Sourcing & Compliance
    DSGVO: Pseudonymisierbar, GoBD: 10 Jahre Aufbewahrung

    Erweiterung v3.0:
    - consent_transparenz: Opt-in für Transparenzseite
    - transparency_hash: Pseudonymisierter Spender-Code (z.B. SPENDER-A1B2C3)
    - needs_id: Verknüpfung mit spezifischem Bedarf
    """

    __tablename__ = "donations"
    __table_args__ = (
        Index("idx_donor_email_pseudonym", "donor_email_pseudonym"),
        Index("idx_project_status", "project_id", "status"),
        Index("idx_compliance_flag", "compliance_status"),
        Index("idx_transparency_hash", "transparency_hash"),  # v3.0
        Index("idx_consent_transparenz", "consent_transparenz"),  # v3.0
        # PartitionBy("range", "created_at"),  # Monthly partitions für Performance
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Donor (DSGVO-konform)
    donor_email_pseudonym = Column(String(255), nullable=False)  # SHA256(Email)
    donor_name_encrypted = Column(Text, nullable=True)  # Fernet-Verschlüsselung
    donor_address_encrypted = Column(Text, nullable=True)

    # Buchhaltung (SKR42 mit Kostenträger)
    project_id = Column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    skr42_account_id = Column(PGUUID(as_uuid=True), ForeignKey("skr42_accounts.id"), nullable=False)
    cost_center = Column(String(50), nullable=False)  # PROJ_001

    # Verknüpfung mit Bedarf (v3.0)
    need_id = Column(
        PGUUID(as_uuid=True), ForeignKey("project_needs.id", ondelete="SET NULL"), nullable=True
    )

    # Transparenz (v3.0)
    consent_transparenz = Column(
        Boolean, default=False, nullable=False
    )  # Opt-in für Transparenzseite
    transparency_hash = Column(String(20), nullable=True)  # SPENDER-A1B2C3 Format

    # Transaktionsdaten
    amount = Column(Numeric(12, 2), nullable=False)
    transaction_type = Column(String(50), nullable=False, default=TransactionType.SPENDE)
    currency = Column(String(3), default="EUR")

    # Zahlungsabwicklung
    payment_provider = Column(String(20), nullable=False)  # stripe, paypal, klarna
    payment_intent_id = Column(String(255), nullable=False, unique=True)
    payment_status = Column(String(50), default="pending")

    # Compliance
    compliance_status = Column(String(50), default=ComplianceStatus.PENDING)
    four_eyes_approved_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    four_eyes_approved_at = Column(DateTime, nullable=True)
    money_laundering_flag = Column(Boolean, default=False)  # >10.000€

    # Steuer
    tax_deductible = Column(Boolean, default=True)
    tax_id = Column(String(20), nullable=True)  # Steuer-ID für Zuwendungsbescheinigung
    donation_receipt_generated = Column(Boolean, default=False)

    # Merkle-Tree (Manipulationsschutz)
    previous_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=False)
    blockchain_tx_id = Column(String(255), nullable=True)  # Optional: Blockchain-Tracking

    # DSGVO
    is_pseudonymized = Column(Boolean, default=False)
    pseudonymized_at = Column(DateTime, nullable=True)
    deletion_requested_at = Column(DateTime, nullable=True)

    # Audit
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="donations")
    need = relationship("ProjectNeed", back_populates="donations", foreign_keys=[need_id])
    account = relationship("SKR42Account", back_populates="transactions")
    events = relationship("EventStore", back_populates="donation")
    audit_logs = relationship("AuditLog", back_populates="donation")

    @validates("amount")
    def validate_amount(self, key, amount):
        """Validiert Spendenbetrag und setzt Geldwäsche-Flag"""
        if amount <= 0:
            raise ValueError("Spendenbetrag muss positiv sein")
        if amount > 10000 and not self.money_laundering_flag:
            self.money_laundering_flag = True
            self.compliance_status = ComplianceStatus.FLAGGED
        return amount

    def compute_hash(self) -> str:
        """Berechnet manipulationssicheren Hash für GoBD"""
        data = f"{self.id}|{self.amount}|{self.payment_intent_id}|{self.updated_at}|{self.donor_email_pseudonym}"
        return hashlib.sha256(data.encode()).hexdigest()

    def pseudonymize(self):
        """DSGVO Art.17: Pseudonymisierung statt Löschung"""
        self.donor_email_pseudonym = hashlib.sha256(self.donor_email_pseudonym.encode()).hexdigest()
        self.donor_name_encrypted = None
        self.donor_address_encrypted = None
        self.is_pseudonymized = True
        self.pseudonymized_at = datetime.utcnow()

    def generate_transparency_hash(self, salt: str = None) -> str:
        """
        Generiert pseudonymisierten Spender-Hash für Transparenzseite
        Format: SPENDER-{hash[:6].upper()}
        Beispiel: SPENDER-A1B2C3
        """
        if salt is None:
            salt = str(datetime.utcnow().year)

        import hmac

        hash_obj = hmac.new(salt.encode(), self.donor_email_pseudonym.encode(), hashlib.sha256)
        hash_hex = hash_obj.hexdigest()[:6].upper()
        self.transparency_hash = f"SPENDER-{hash_hex}"
        return self.transparency_hash


# ==================== EVENT SOURCING (Greg Young Pattern) ====================


class EventStore(Base):
    """
    Unveränderliches Event-Sourcing für komplettes Audit
    GoBD-konform: Jede Änderung wird als Event gespeichert
    """

    __tablename__ = "event_store"
    __table_args__ = (
        Index("idx_aggregate_version", "aggregate_id", "version"),
        Index("idx_event_timestamp", "timestamp"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    aggregate_id = Column(PGUUID(as_uuid=True), nullable=False)  # Donation ID, Project ID
    aggregate_type = Column(String(50), nullable=False)  # Donation, Project, User
    version = Column(Integer, nullable=False)  # Optimistic Locking
    event_type = Column(String(100), nullable=False)  # DonationCreated, AmountUpdated

    # Event-Daten (JSONB für Flexibilität)
    event_data = Column(JSONB, nullable=False)
    metadata = Column(JSONB, default={})  # User, IP, User-Agent

    # Compliance
    previous_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=False)

    # Audit
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    donation = relationship("Donation", back_populates="events")

    def compute_hash(self) -> str:
        """Merkle-Tree für Event-Integrität"""
        data = f"{self.id}|{self.aggregate_id}|{self.version}|{self.event_type}|{json.dumps(self.event_data)}|{self.timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()


# ==================== COMPLIANCE AUDITLOG (GoBD) ====================


class AuditLog(Base):
    """
    DSGVO/GoBD konformes Audit-Log
    Mit vorher/nachher Werten für Prüfpfade
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_entity_timestamp", "entity_type", "entity_id", "timestamp"),
        Index("idx_user_action", "user_id", "action"),
        # PartitionBy("range", "timestamp"),  # Monatliche Partitionen
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Audit-Daten
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(PGUUID(as_uuid=True), nullable=False)

    # GoBD: Vorher/Nachher Werte
    old_values = Column(JSONB, nullable=True)
    new_values = Column(JSONB, nullable=True)

    # Zusätzlicher Kontext
    ip_address = Column(String(45), nullable=False)  # IPv6-kompatibel
    user_agent = Column(String(500), nullable=True)
    reason = Column(String(500), nullable=True)  # Grund für Änderung (DSGVO)

    # Compliance
    requires_four_eyes = Column(Boolean, default=False)
    four_eyes_approved = Column(Boolean, default=False)
    four_eyes_by = Column(PGUUID(as_uuid=True), nullable=True)

    # Aufbewahrung
    retention_until = Column(DateTime, nullable=False)  # 10 Jahre für Finanzen
    is_archived = Column(Boolean, default=False)
    archived_at = Column(DateTime, nullable=True)

    # Audit
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="audit_logs")
    donation = relationship("Donation", back_populates="audit_logs")


# ==================== PROJEKTE MIT KOSTENTRÄGERN & BEDARFEN ====================


class Project(Base):
    """
    Projekt-Management mit SKR42-Kostenträgern

    Erweiterung v3.0:
    - needs_alert_config für automatische Benachrichtigungen
    - transparency_description für öffentliche Projektbeschreibung
    - image_url für Projektbild auf Transparenzseite
    """

    __tablename__ = "projects"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # Transparenz (v3.0)
    transparency_description = Column(Text, nullable=True)  # Öffentliche Beschreibung
    image_url = Column(String(500), nullable=True)  # Projektbild für Transparenzseite
    show_on_transparency = Column(Boolean, default=True)  # Auf Transparenzseite anzeigen

    # SKR42 Kostenträger
    cost_center = Column(String(50), nullable=False, unique=True)  # PROJ_001
    skr42_account_id = Column(PGUUID(as_uuid=True), ForeignKey("skr42_accounts.id"), nullable=False)

    # Finanz-KPIs
    budget_total = Column(Numeric(12, 2), default=0)
    budget_used = Column(Numeric(12, 2), default=0)
    donations_total = Column(Numeric(12, 2), default=0)

    # Status
    status = Column(String(20), default="active")  # active, completed, suspended
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=True)

    # Compliance
    requires_four_eyes = Column(Boolean, default=True)  # Projekte >10.000€

    # Bedarfs-Alert Konfiguration (v3.0)
    needs_alert_config = Column(
        JSONB,
        default={
            "enabled": True,
            "default_threshold_percent": 20,
            "default_channels": ["email"],
            "notification_email": None,
            "notification_telegram": None,
        },
    )

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    skr42_account = relationship("SKR42Account", back_populates="projects")
    donations = relationship("Donation", back_populates="project")
    inventory_items = relationship("InventoryItem", back_populates="project")
    needs = relationship("ProjectNeed", back_populates="project", cascade="all, delete-orphan")


# ==================== USER MODELL (für Auth) ====================


class User(Base):
    """
    Benutzer-Modell für Authentication & RBAC

    Erweiterung v3.0:
    - telegram_chat_id für Benachrichtigungen
    - notification_preferences für individualisierte Alerts
    """

    __tablename__ = "users"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False)
    email_verified = Column(Boolean, default=False)
    password_hash = Column(String(255), nullable=False)

    # Persönliche Daten (verschlüsselt)
    name_encrypted = Column(Text, nullable=True)
    phone_encrypted = Column(Text, nullable=True)

    # Rollen & Rechte
    role = Column(String(50), nullable=False, default=UserRole.DONOR)
    permissions = Column(JSONB, default=list)  # Feingranulare Rechte

    # MFA
    mfa_enabled = Column(Boolean, default=False)
    mfa_secret = Column(String(255), nullable=True)

    # Benachrichtigungen (v3.0)
    telegram_chat_id = Column(String(100), nullable=True)
    notification_preferences = Column(
        JSONB,
        default={
            "email_alerts": True,
            "telegram_alerts": False,
            "need_alerts": True,
            "donation_alerts": True,
            "report_alerts": False,
        },
    )

    # DSGVO
    consent_given_at = Column(DateTime, nullable=True)
    consent_withdrawn_at = Column(DateTime, nullable=True)
    is_pseudonymized = Column(Boolean, default=False)

    # Audit
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    audit_logs = relationship("AuditLog", back_populates="user")

    def pseudonymize(self):
        """DSGVO Art.17: Pseudonymisierung"""
        self.email = hashlib.sha256(self.email.encode()).hexdigest()
        self.name_encrypted = None
        self.phone_encrypted = None
        self.is_pseudonymized = True


# ==================== TRANSACTION (für SKR42 Buchungen) ====================


class Transaction(Base):
    """
    SKR42 Buchungstransaktionen
    Für detaillierte Buchhaltung
    """

    __tablename__ = "transactions"
    __table_args__ = (
        Index("idx_transaction_date", "booking_date"),
        Index("idx_transaction_account", "debit_account_id", "credit_account_id"),
        Index("idx_transaction_project", "project_id"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Buchungsdaten
    booking_date = Column(DateTime, nullable=False)
    value_date = Column(DateTime, nullable=True)

    # Konten
    debit_account_id = Column(PGUUID(as_uuid=True), ForeignKey("skr42_accounts.id"), nullable=False)
    credit_account_id = Column(
        PGUUID(as_uuid=True), ForeignKey("skr42_accounts.id"), nullable=False
    )

    # Betrag
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="EUR")

    # Referenz
    reference_type = Column(String(50), nullable=True)  # donation, invoice, etc.
    reference_id = Column(PGUUID(as_uuid=True), nullable=True)

    # Projekt (optional)
    project_id = Column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    cost_center = Column(String(50), nullable=True)

    # Beschreibung
    description = Column(Text, nullable=True)
    tax_code = Column(String(10), nullable=True)

    # Compliance
    is_reversed = Column(Boolean, default=False)
    reversed_by_id = Column(PGUUID(as_uuid=True), nullable=True)

    # Audit
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    debit_account = relationship("SKR42Account", foreign_keys=[debit_account_id])
    credit_account = relationship("SKR42Account", foreign_keys=[credit_account_id])
    project = relationship("Project")


# ==================== PYDANTIC MODELS (API-Schema) ====================


class DonationCreate(BaseModel):
    """DSGVO-konformes Donation Schema (v3.0 mit Transparenz-Opt-in)"""

    project_id: UUID
    amount: Decimal = Field(..., gt=0, le=100000)
    donor_email: str = Field(..., regex=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    donor_name: str | None = None
    payment_provider: str = Field(..., regex="^(stripe|paypal|klarna)$")
    payment_intent_id: str
    tax_id: str | None = None
    need_id: UUID | None = None  # v3.0: Spezifischer Bedarf
    consent_transparenz: bool = Field(False, description="Opt-in für Transparenzseite")  # v3.0

    @validator("donor_email")
    def pseudonymize_email(cls, v):
        """Email wird sofort pseudonymisiert (DSGVO)"""
        return hashlib.sha256(v.lower().encode()).hexdigest()

    class Config:
        json_encoders = {Decimal: str, UUID: str}


class DonationResponse(BaseModel):
    """API Response für Spende (v3.0 mit Transparenz-Hash)"""

    id: UUID
    project_id: UUID
    amount: Decimal
    donor_email_pseudonym: str  # Nur Pseudonym
    payment_status: str
    compliance_status: ComplianceStatus
    created_at: datetime
    donation_receipt_generated: bool
    consent_transparenz: bool  # v3.0
    transparency_hash: str | None = None  # v3.0: SPENDER-A1B2C3

    class Config:
        orm_mode = True


class UserCreate(BaseModel):
    """API Request für Benutzererstellung"""

    email: str
    password: str
    name: str | None = None
    role: UserRole = UserRole.DONOR


class UserResponse(BaseModel):
    """API Response für Benutzer"""

    id: UUID
    email: str
    role: UserRole
    email_verified: bool
    created_at: datetime
    telegram_chat_id: str | None = None  # v3.0

    class Config:
        orm_mode = True


# ==================== ROW-LEVEL SECURITY (PostgreSQL) ====================


class RowLevelSecurity:
    """
    PostgreSQL RLS Policies für Multi-Tenant & DSGVO
    Erweitert v3.0: Transparenz-Zugriff für öffentliche API
    """

    @staticmethod
    def get_policies() -> list[str]:
        return [
            """
            -- Donors sehen nur ihre eigenen Spenden (pseudonymisiert)
            CREATE POLICY donor_select_policy ON donations
                FOR SELECT USING (
                    donor_email_pseudonym = current_setting('app.current_donor_email')::text
                    AND is_pseudonymized = true
                );
            """,
            """
            -- Admins sehen alles (für Audit)
            CREATE POLICY admin_all_policy ON donations
                FOR ALL USING (
                    current_setting('app.current_user_role') = 'admin'
                );
            """,
            """
            -- Buchhalter nur Finanzdaten (keine personenbezogenen Daten)
            CREATE POLICY accountant_select_policy ON donations
                FOR SELECT USING (
                    current_setting('app.current_user_role') = 'accountant'
                )
                WITH CHECK (false);  -- Read-only
            """,
            """
            -- 4-Augen-Prinzip für Buchungen >5000€
            CREATE POLICY four_eyes_policy ON donations
                FOR UPDATE USING (
                    amount > 5000
                    AND current_setting('app.four_eyes_approved') = 'true'
                );
            """,
            """
            -- Transparenz-API: Nur Spenden mit Consent (v3.0)
            CREATE POLICY transparency_select_policy ON donations
                FOR SELECT USING (
                    consent_transparenz = true
                    AND payment_status = 'succeeded'
                );
            """,
        ]
