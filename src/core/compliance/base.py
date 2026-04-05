# FILE: src/core/compliance/base.py
# MODULE: Compliance Base Classes & Models
# Enterprise Compliance mit 4-Augen-Prinzip, Geldwäscheprävention, GoBD

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, validator
from sqlalchemy import (
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from src.core.entities.base import Base

# ==================== Enums ====================

class ApprovalStatus(str, Enum):
    """Status für 4-Augen-Prinzip"""
    PENDING = "pending"          # Wartet auf Freigabe
    APPROVED = "approved"        # Freigegeben
    REJECTED = "rejected"        # Abgelehnt
    ESCALATED = "escalated"      # Eskaliert an höhere Instanz
    EXPIRED = "expired"          # Freigabe abgelaufen

class MoneyLaunderingRisk(str, Enum):
    """Geldwäscherisiko-Stufen"""
    LOW = "low"                  # < 1.000€
    MEDIUM = "medium"            # 1.000€ - 10.000€
    HIGH = "high"                # 10.000€ - 50.000€
    CRITICAL = "critical"        # > 50.000€
    SUSPICIOUS = "suspicious"    # Verdachtsfall

class ComplianceCheckType(str, Enum):
    """Arten von Compliance-Prüfungen"""
    FOUR_EYES = "four_eyes"              # 4-Augen-Prinzip
    MONEY_LAUNDERING = "money_laundering" # Geldwäsche
    TAX_VALIDATION = "tax_validation"     # Steuerprüfung
    SANCTIONS_LIST = "sanctions_list"     # Sanktionslisten
    PEP_CHECK = "pep_check"              # Politically Exposed Persons
    GOBD_COMPLIANCE = "gobd_compliance"   # GoBD-Konformität
    BUDGET_LIMIT = "budget_limit"         # Budgetüberschreitung

class ComplianceResult(str, Enum):
    """Ergebnis einer Compliance-Prüfung"""
    PASSED = "passed"
    FAILED = "failed"
    REQUIRES_REVIEW = "requires_review"
    BLOCKED = "blocked"
    REPORTED = "reported"  # An Behörde gemeldet

# ==================== 4-Augen-Prinzip Model ====================

class FourEyesApproval(Base):
    """
    4-Augen-Prinzip: Transaktionen > 5.000€ benötigen zwei Freigaben
    GoBD-konforme Dokumentation von Freigabeprozessen
    """
    __tablename__ = "four_eyes_approvals"
    __table_args__ = (
        Index("idx_foureyes_entity", "entity_type", "entity_id"),
        Index("idx_foureyes_status", "status"),
        Index("idx_foureyes_approvers", "approver_1_id", "approver_2_id"),
        CheckConstraint("approver_1_id != approver_2_id", name="ck_different_approvers"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Verknüpfung zur zu prüfenden Entität
    entity_type = Column(String(50), nullable=False)  # donation, payment, project, expense
    entity_id = Column(PGUUID(as_uuid=True), nullable=False)

    # Transaktionsdaten
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="EUR")
    reason = Column(Text, nullable=False)  # Grund für Transaktion

    # Erster Prüfer (initiiert)
    initiator_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    initiated_at = Column(DateTime, default=datetime.utcnow)

    # Zweiter Prüfer (muss freigeben)
    approver_1_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approver_1_approved_at = Column(DateTime, nullable=True)
    approver_1_comment = Column(Text, nullable=True)
    approver_1_ip = Column(String(45), nullable=True)

    # Dritter Prüfer (optional, bei hohen Beträgen)
    approver_2_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approver_2_approved_at = Column(DateTime, nullable=True)
    approver_2_comment = Column(Text, nullable=True)
    approver_2_ip = Column(String(45), nullable=True)

    # Status
    status = Column(String(50), nullable=False, default=ApprovalStatus.PENDING)
    rejection_reason = Column(Text, nullable=True)

    # Eskalation
    escalated_to = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    escalation_reason = Column(Text, nullable=True)

    # Fristen
    expires_at = Column(DateTime, nullable=False)  # 48h Standard
    reminded_at = Column(DateTime, nullable=True)  # Letzte Erinnerung

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    initiator = relationship("User", foreign_keys=[initiator_id])
    approver_1 = relationship("User", foreign_keys=[approver_1_id])
    approver_2 = relationship("User", foreign_keys=[approver_2_id])

    @property
    def is_fully_approved(self) -> bool:
        """Prüft ob alle erforderlichen Freigaben vorliegen"""
        if self.approver_2_id:
            return self.approver_1_approved_at and self.approver_2_approved_at
        return bool(self.approver_1_approved_at)

    @property
    def days_pending(self) -> int:
        """Tage in Wartestatus"""
        if self.status == ApprovalStatus.PENDING:
            return (datetime.utcnow() - self.initiated_at).days
        return 0

# ==================== Money Laundering Check Model ====================

class MoneyLaunderingCheck(Base):
    """
    Geldwäscheprüfung nach GwG (Geldwäschegesetz)
    Automatische Erkennung und Meldung verdächtiger Transaktionen
    """
    __tablename__ = "money_laundering_checks"
    __table_args__ = (
        Index("idx_ml_entity", "entity_type", "entity_id"),
        Index("idx_ml_risk_level", "risk_level"),
        Index("idx_ml_reported", "reported_to_fiu"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Verknüpfung
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(PGUUID(as_uuid=True), nullable=False)

    # Transaktionsdaten
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="EUR")
    donor_name = Column(String(200), nullable=True)
    donor_email = Column(String(255), nullable=True)
    donor_country = Column(String(2), nullable=True)  # ISO-Ländercode

    # Zahlungsdetails
    payment_method = Column(String(50), nullable=True)
    ip_address = Column(String(45), nullable=True)
    device_fingerprint = Column(String(255), nullable=True)

    # Risikobewertung
    risk_level = Column(String(50), nullable=False, default=MoneyLaunderingRisk.LOW)
    risk_score = Column(Integer, nullable=False, default=0)  # 0-100

    # Prüfungsergebnisse
    checks_performed = Column(JSONB, default=list)  # Liste der durchgeführten Prüfungen
    flags = Column(JSONB, default=list)  # Gefundene Red Flags

    # Sanktionslisten
    sanctions_list_hit = Column(Boolean, default=False)
    sanctions_list_name = Column(String(200), nullable=True)
    pep_check_passed = Column(Boolean, default=True)  # Politically Exposed Person
    adverse_media_found = Column(Boolean, default=False)

    # Meldewesen
    reported_to_fiu = Column(Boolean, default=False)  # Financial Intelligence Unit
    reported_at = Column(DateTime, nullable=True)
    report_reference = Column(String(100), nullable=True)  # Aktenzeichen
    report_data = Column(JSONB, nullable=True)  # Gespeicherter Report

    # Compliance
    compliance_result = Column(String(50), nullable=False, default=ComplianceResult.PASSED)
    reviewed_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def calculate_risk_score(self) -> int:
        """Berechnet Risikoscore basierend auf verschiedenen Faktoren"""
        score = 0

        # Betrag (0-40 Punkte)
        if self.amount > 50000:
            score += 40
        elif self.amount > 10000:
            score += 30
        elif self.amount > 5000:
            score += 20
        elif self.amount > 1000:
            score += 10

        # Hochrisikoländer (0-20 Punkte)
        high_risk_countries = ['RU', 'CN', 'IR', 'KP', 'SY']
        if self.donor_country in high_risk_countries:
            score += 20

        # Anonyme Zahlungsmethoden (0-20 Punkte)
        anonymous_methods = ['crypto', 'prepaid_card', 'cash']
        if self.payment_method in anonymous_methods:
            score += 20

        # Verdächtige Muster (0-20 Punkte)
        if self.flags:
            score += min(len(self.flags) * 5, 20)

        self.risk_score = min(score, 100)

        # Risikostufe zuweisen
        if self.risk_score >= 80:
            self.risk_level = MoneyLaunderingRisk.CRITICAL
        elif self.risk_score >= 60:
            self.risk_level = MoneyLaunderingRisk.HIGH
        elif self.risk_score >= 30:
            self.risk_level = MoneyLaunderingRisk.MEDIUM
        else:
            self.risk_level = MoneyLaunderingRisk.LOW

        return self.risk_score

# ==================== Tax Compliance Model ====================

class TaxComplianceCheck(Base):
    """
    Steuerliche Compliance-Prüfungen
    USt-IdNr. Validierung, Steuerabzug, Meldepflichten
    """
    __tablename__ = "tax_compliance_checks"
    __table_args__ = (
        Index("idx_tax_vat_id", "vat_id"),
        Index("idx_tax_status", "validation_status"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Steuerpflichtiger
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(PGUUID(as_uuid=True), nullable=False)

    # Steueridentifikation
    vat_id = Column(String(20), nullable=True)  # Umsatzsteuer-ID
    tax_id = Column(String(20), nullable=True)   # Steuer-ID (Deutschland)
    country_code = Column(String(2), nullable=True)

    # Validierung
    validation_status = Column(String(50), nullable=False, default="pending")
    validated_at = Column(DateTime, nullable=True)
    validated_by = Column(String(100), nullable=True)  # System oder User
    validation_response = Column(JSONB, nullable=True)  # API Response

    # Steuerabzug
    tax_rate = Column(Numeric(5, 2), nullable=True)  # z.B. 19.00
    tax_amount = Column(Numeric(12, 2), nullable=True)
    tax_deductible = Column(Boolean, default=True)

    # Zuwendungsbescheinigung
    receipt_generated = Column(Boolean, default=False)
    receipt_number = Column(String(50), nullable=True)
    receipt_generated_at = Column(DateTime, nullable=True)

    # Meldepflichten
    reported_to_tax_office = Column(Boolean, default=False)
    report_date = Column(DateTime, nullable=True)
    report_reference = Column(String(100), nullable=True)

    # Compliance
    is_compliant = Column(Boolean, default=True)
    compliance_notes = Column(Text, nullable=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @validator('vat_id')
    def validate_vat_id(cls, v):
        """Einfache VAT-ID Validierung (erweiterte Prüfung via API)"""
        if v and not v.startswith(('DE', 'AT', 'CH', 'LU', 'NL', 'BE', 'FR', 'IT', 'ES', 'PT')):
            raise ValueError(f"Invalid VAT ID format: {v}")
        return v.upper() if v else None

# ==================== GoBD Compliance Model ====================

class GoBDComplianceRecord(Base):
    """
    GoBD-Compliance Record (Grundsätze zur ordnungsmäßigen Führung und Aufbewahrung von Büchern)
    Stellt revisionssichere Dokumentation sicher
    """
    __tablename__ = "gobd_compliance_records"
    __table_args__ = (
        Index("idx_gobd_record_type", "record_type", "record_id"),
        Index("idx_gobd_retention_date", "retention_until"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Rekord-Informationen
    record_type = Column(String(50), nullable=False)  # invoice, receipt, contract, audit_log
    record_id = Column(PGUUID(as_uuid=True), nullable=False)
    record_hash = Column(String(64), nullable=False)  # SHA-256 für Manipulationsschutz

    # Aufbewahrung
    retention_period_years = Column(Integer, nullable=False, default=10)  # GoBD: 10 Jahre
    retention_until = Column(DateTime, nullable=False)
    storage_location = Column(String(500), nullable=True)  # S3 Pfad oder Archivbox

    # Dokumentenmanagement
    original_filename = Column(String(255), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)

    # Verschlüsselung
    encrypted = Column(Boolean, default=True)
    encryption_key_id = Column(String(100), nullable=True)  # Referenz zu Vault

    # Zugriffsprotokoll
    access_log = Column(JSONB, default=list)  # Wer hat wann zugegriffen

    # Löschschutz
    deletion_protected_until = Column(DateTime, nullable=False)
    deletion_requested = Column(Boolean, default=False)
    deletion_requested_at = Column(DateTime, nullable=True)
    deletion_approved_by = Column(PGUUID(as_uuid=True), nullable=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    def extend_retention(self, additional_years: int):
        """Verlängert Aufbewahrungsfrist"""
        from dateutil.relativedelta import relativedelta
        self.retention_until += relativedelta(years=additional_years)

# ==================== Compliance Alert Model ====================

class ComplianceAlert(Base):
    """
    Compliance-Alerts für automatische Benachrichtigungen
    Bei Verdachtsfällen, abgelaufenen Fristen, fehlenden Freigaben
    """
    __tablename__ = "compliance_alerts"
    __table_args__ = (
        Index("idx_alert_status", "status"),
        Index("idx_alert_priority", "priority"),
        Index("idx_alert_assignee", "assigned_to"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Alert-Daten
    alert_type = Column(String(50), nullable=False)  # four_eyes_expiring, ml_suspicious, etc.
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)

    # Priorität
    priority = Column(String(20), nullable=False, default="medium")  # low, medium, high, critical
    severity_score = Column(Integer, nullable=False, default=0)  # 0-100

    # Verknüpfung
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(PGUUID(as_uuid=True), nullable=True)

    # Zuständigkeit
    assigned_to = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    assigned_at = Column(DateTime, nullable=True)

    # Status
    status = Column(String(20), nullable=False, default="open")  # open, acknowledged, resolved, false_positive
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(PGUUID(as_uuid=True), nullable=True)
    resolution_note = Column(Text, nullable=True)

    # Eskalation
    escalated_at = Column(DateTime, nullable=True)
    escalation_level = Column(Integer, default=0)  # 0=keine, 1=Vorgesetzter, 2=Compliance Officer

    # Benachrichtigungen
    notified_users = Column(JSONB, default=list)
    last_notification_at = Column(DateTime, nullable=True)

    # Fristen
    response_deadline = Column(DateTime, nullable=False)
    reminded_at = Column(DateTime, nullable=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ==================== Pydantic Models ====================

class FourEyesRequest(BaseModel):
    """API Request für 4-Augen-Freigabe"""
    entity_type: str
    entity_id: UUID
    amount: Decimal = Field(..., gt=0)
    reason: str = Field(..., min_length=10, max_length=500)
    approver_1_id: UUID
    approver_2_id: UUID | None = None

    @validator('amount')
    def validate_amount_threshold(cls, v):
        if v < 5000:
            raise ValueError(f"4-Augen-Prinzip nur für Beträge > 5.000€, aktuell: {v}€")
        return v

class MoneyLaunderingReport(BaseModel):
    """Report für Geldwäscheverdacht"""
    entity_type: str
    entity_id: UUID
    amount: Decimal
    donor_name: str | None
    donor_email: str | None
    risk_factors: list[str]
    recommendation: str

class ComplianceCheckResult(BaseModel):
    """Ergebnis einer Compliance-Prüfung"""
    check_type: ComplianceCheckType
    passed: bool
    risk_score: int | None = None
    details: dict[str, Any] = {}
    requires_human_review: bool = False
    message: str
