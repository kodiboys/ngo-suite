# FILE: src/core/entities/needs.py
# MODULE: Project Needs Entity - Bedarfe für Projekte
# Erweiterung zu Modul 4 (Inventory) für Transparenz & Bedarfsmanagement
# Features: Kategorien, Prioritäten, automatische Benachrichtigungen, Fortschrittsverfolgung

from datetime import datetime
from decimal import Decimal
from enum import Enum
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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship, validates

from src.core.entities.base import Base

# ==================== Enums ====================


class NeedCategory(str, Enum):
    """Bedarfs-Kategorien für Projekte"""

    HOUSING = "wohnen"  # Wohnraum / Unterkunft
    FOOD = "nahrung"  # Nahrungsmittel
    MEDICAL = "medizin"  # Medizinische Versorgung
    CLOTHING = "kleidung"  # Kleidung
    TRANSPORT = "transport"  # Transport / Logistik
    ENERGY = "energie"  # Energie (Strom, Heizung)
    HYGIENE = "hygiene"  # Hygieneartikel
    EDUCATION = "bildung"  # Bildung / Schulmaterial
    TOOLS = "werkzeuge"  # Werkzeuge / Ausrüstung
    OTHER = "sonstige"  # Sonstige Bedarfe


class NeedPriority(str, Enum):
    """Prioritäten für Bedarfe"""

    CRITICAL = "critical"  # Kritisch - sofortige Aktion nötig
    HIGH = "high"  # Hoch - dringend
    MEDIUM = "medium"  # Mittel - normal
    LOW = "low"  # Niedrig - kann warten


class NeedStatus(str, Enum):
    """Status eines Bedarfs"""

    ACTIVE = "active"  # Aktiv - wird benötigt
    PARTIALLY_FULFILLED = "partial"  # Teilweise erfüllt
    FULFILLED = "fulfilled"  # Vollständig erfüllt
    EXPIRED = "expired"  # Abgelaufen (z.B. zeitkritisch)
    CANCELLED = "cancelled"  # Storniert


class AlertChannel(str, Enum):
    """Benachrichtigungskanäle für Bedarfs-Alerts"""

    EMAIL = "email"
    TELEGRAM = "telegram"
    SLACK = "slack"
    WEBHOOK = "webhook"


# ==================== SQLAlchemy Model ====================


class ProjectNeed(Base):
    """
    Bedarfe für Projekte
    Erweitert Modul 4 (Inventory) um transparente Bedarfsverwaltung

    Features:
    - Kategorisierung für bessere Übersicht
    - Prioritäten für Dringlichkeit
    - Fortschrittsverfolgung (aktuell vs Ziel)
    - Automatische Alerts bei kritischen Beständen
    - Verknüpfung mit Lagerbeständen (Modul 4)
    """

    __tablename__ = "project_needs"
    __table_args__ = (
        Index("idx_needs_project", "project_id"),
        Index("idx_needs_category", "category"),
        Index("idx_needs_priority", "priority"),
        Index("idx_needs_status", "status"),
        Index("idx_needs_fulfillment", "fulfillment_percentage"),
        UniqueConstraint("project_id", "name", name="uq_need_per_project"),
        CheckConstraint("quantity_target > 0", name="ck_positive_target"),
        CheckConstraint("quantity_current >= 0", name="ck_non_negative_current"),
        CheckConstraint("fulfillment_percentage BETWEEN 0 AND 100", name="ck_valid_percentage"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Projektzuordnung
    project_id = Column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    # Basisinformationen
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, default=NeedCategory.OTHER)
    priority = Column(String(20), nullable=False, default=NeedPriority.MEDIUM)

    # Mengen & Fortschritt
    quantity_target = Column(Integer, nullable=False)
    quantity_current = Column(Integer, nullable=False, default=0)
    unit = Column(String(20), nullable=True, default="Stück")  # Stück, kg, Liter, Paar, etc.

    # Finanzen (optional)
    unit_price_eur = Column(Numeric(10, 2), nullable=True)
    total_value_eur = Column(Numeric(12, 2), nullable=True)  # quantity_target * unit_price_eur

    # Verknüpfung mit Lager (Modul 4)
    inventory_item_id = Column(
        PGUUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="SET NULL"), nullable=True
    )

    # Status & Metadaten
    status = Column(String(20), nullable=False, default=NeedStatus.ACTIVE)
    fulfillment_percentage = Column(Integer, nullable=False, default=0)

    # Zeitliche Gültigkeit (z.B. für saisonale Bedarfe)
    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)

    # Automatische Benachrichtigungen
    alert_enabled = Column(Boolean, default=True)
    alert_threshold_percent = Column(Integer, default=20)  # Alert bei <20% Bestand
    alert_channels = Column(JSONB, default=["email"])  # Liste von AlertChannel
    last_alert_sent_at = Column(DateTime, nullable=True)

    # Zusätzliche Metadaten
    images = Column(JSONB, default=list)  # URLs zu Bildern des Bedarfs
    documents = Column(JSONB, default=list)  # URLs zu Dokumenten (z.B. Spezifikationen)
    tags = Column(JSONB, default=list)  # Tags für bessere Filterung
    custom_fields = Column(JSONB, default=dict)  # Projekt-spezifische Felder

    # Audit
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    fulfilled_at = Column(DateTime, nullable=True)

    # Relationships
    project = relationship("Project", back_populates="needs")
    inventory_item = relationship("InventoryItem", back_populates="need")

    @validates("quantity_target")
    def validate_target(self, key, value):
        """Validiert Zielmenge"""
        if value <= 0:
            raise ValueError(f"Zielmenge muss positiv sein: {value}")
        return value

    @validates("quantity_current")
    def validate_current(self, key, value):
        """Validiert aktuelle Menge"""
        if value < 0:
            raise ValueError(f"Aktuelle Menge kann nicht negativ sein: {value}")
        return value

    def update_fulfillment(self):
        """Aktualisiert Erfüllungsgrad basierend auf aktueller Menge"""
        if self.quantity_target > 0:
            self.fulfillment_percentage = int((self.quantity_current / self.quantity_target) * 100)

        # Status automatisch aktualisieren
        if self.fulfillment_percentage >= 100:
            self.status = NeedStatus.FULFILLED
            self.fulfilled_at = datetime.utcnow()
        elif self.fulfillment_percentage > 0:
            self.status = NeedStatus.PARTIALLY_FULFILLED
        else:
            self.status = NeedStatus.ACTIVE

        # Prüfe ob Alert nötig
        remaining_percent = 100 - self.fulfillment_percentage
        if self.alert_enabled and remaining_percent <= self.alert_threshold_percent:
            self._needs_alert = True

    def calculate_total_value(self):
        """Berechnet Gesamtwert des Bedarfs"""
        if self.unit_price_eur:
            self.total_value_eur = self.quantity_target * self.unit_price_eur

    def add_quantity(self, amount: int, user_id: UUID):
        """
        Fügt Menge hinzu (z.B. durch Spende)
        Aktualisiert Fortschritt und prüft auf Alerts
        """
        self.quantity_current = min(self.quantity_current + amount, self.quantity_target)
        self.update_fulfillment()
        self.updated_at = datetime.utcnow()

        # Verknüpftes Lager-Item aktualisieren (falls vorhanden)
        if self.inventory_item_id:
            pass

            # Async call - wird im Service behandelt

    def needs_alert(self) -> bool:
        """Prüft ob ein Alert gesendet werden soll"""
        if not self.alert_enabled:
            return False

        remaining_percent = 100 - self.fulfillment_percentage
        should_alert = remaining_percent <= self.alert_threshold_percent

        # Verhindere wiederholte Alerts innerhalb von 24h
        if should_alert and self.last_alert_sent_at:
            hours_since_last = (datetime.utcnow() - self.last_alert_sent_at).total_seconds() / 3600
            if hours_since_last < 24:
                return False

        return should_alert

    def mark_alert_sent(self):
        """Markiert dass ein Alert gesendet wurde"""
        self.last_alert_sent_at = datetime.utcnow()

    @property
    def remaining_quantity(self) -> int:
        """Noch benötigte Menge"""
        return max(0, self.quantity_target - self.quantity_current)

    @property
    def is_urgent(self) -> bool:
        """Prüft ob Bedarf dringend ist"""
        return (
            self.priority in [NeedPriority.CRITICAL, NeedPriority.HIGH]
            and self.remaining_quantity > 0
        )

    @property
    def is_expired(self) -> bool:
        """Prüft ob Bedarf abgelaufen ist"""
        if self.valid_until:
            return datetime.utcnow() > self.valid_until
        return False


# ==================== Need History (für Audit) ====================


class NeedHistory(Base):
    """
    Historie der Bedarfs-Änderungen
    Für Compliance und Nachvollziehbarkeit
    """

    __tablename__ = "need_history"
    __table_args__ = (
        Index("idx_need_history_need", "need_id"),
        Index("idx_need_history_timestamp", "timestamp"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    need_id = Column(
        PGUUID(as_uuid=True), ForeignKey("project_needs.id", ondelete="CASCADE"), nullable=False
    )

    # Änderungsdaten
    action = Column(String(50), nullable=False)  # CREATE, UPDATE, FULFILL, ALERT
    old_values = Column(JSONB, nullable=True)
    new_values = Column(JSONB, nullable=True)
    change_reason = Column(Text, nullable=True)

    # Quelle der Änderung
    changed_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    source_type = Column(String(50), default="manual")  # manual, donation, system, cron
    source_id = Column(PGUUID(as_uuid=True), nullable=True)  # z.B. donation_id

    # Metadaten
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Relationships
    need = relationship("ProjectNeed")


# ==================== Need Alert Log ====================


class NeedAlertLog(Base):
    """
    Log der gesendeten Benachrichtigungen
    Für Monitoring und Nachverfolgung
    """

    __tablename__ = "need_alert_logs"
    __table_args__ = (
        Index("idx_alert_need", "need_id"),
        Index("idx_alert_channel", "channel"),
        Index("idx_alert_sent_at", "sent_at"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    need_id = Column(
        PGUUID(as_uuid=True), ForeignKey("project_needs.id", ondelete="CASCADE"), nullable=False
    )

    # Alert-Daten
    channel = Column(String(50), nullable=False)  # email, telegram, slack
    recipient = Column(String(500), nullable=False)
    subject = Column(String(500), nullable=True)
    message = Column(Text, nullable=False)

    # Status
    status = Column(String(20), default="sent")  # sent, failed, pending
    error_message = Column(Text, nullable=True)

    # Metadaten
    sent_at = Column(DateTime, default=datetime.utcnow)
    retry_count = Column(Integer, default=0)

    # Relationships
    need = relationship("ProjectNeed")


# ==================== Pydantic Models für API ====================


class NeedCreate(BaseModel):
    """API Request für neuen Bedarf"""

    project_id: UUID
    name: str = Field(..., min_length=3, max_length=200)
    description: str | None = None
    category: NeedCategory = NeedCategory.OTHER
    priority: NeedPriority = NeedPriority.MEDIUM
    quantity_target: int = Field(..., gt=0, le=1000000)
    unit: str | None = Field("Stück", max_length=20)
    unit_price_eur: Decimal | None = Field(None, ge=0)
    inventory_item_id: UUID | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    alert_enabled: bool = True
    alert_threshold_percent: int = Field(20, ge=1, le=100)
    alert_channels: list[str] = ["email"]
    tags: list[str] = []

    @validator("valid_until")
    def validate_dates(cls, v, values):
        """Validiert dass valid_until nach valid_from liegt"""
        if v and values.get("valid_from") and v <= values["valid_from"]:
            raise ValueError("valid_until must be after valid_from")
        return v

    class Config:
        json_encoders = {Decimal: str, UUID: str, datetime: lambda v: v.isoformat()}


class NeedUpdate(BaseModel):
    """API Request für Bedarfs-Update"""

    name: str | None = Field(None, min_length=3, max_length=200)
    description: str | None = None
    category: NeedCategory | None = None
    priority: NeedPriority | None = None
    quantity_target: int | None = Field(None, gt=0, le=1000000)
    unit: str | None = Field(None, max_length=20)
    unit_price_eur: Decimal | None = Field(None, ge=0)
    status: NeedStatus | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    alert_enabled: bool | None = None
    alert_threshold_percent: int | None = Field(None, ge=1, le=100)
    tags: list[str] | None = None


class NeedResponse(BaseModel):
    """API Response für Bedarf"""

    id: UUID
    project_id: UUID
    project_name: str | None = None
    name: str
    description: str | None
    category: str
    priority: str
    quantity_target: int
    quantity_current: int
    remaining_quantity: int
    fulfillment_percentage: int
    unit: str | None
    unit_price_eur: float | None
    total_value_eur: float | None
    status: str
    is_urgent: bool
    inventory_item_id: UUID | None
    alert_enabled: bool
    alert_threshold_percent: int
    created_at: datetime
    updated_at: datetime
    fulfilled_at: datetime | None
    tags: list[str]

    class Config:
        # orm_mode = True      # Pydantic V1 (veraltet)
        from_attributes = True  # Pydantic V2 (korrekt)


class NeedAlertConfig(BaseModel):
    """Konfiguration für Bedarfs-Benachrichtigungen"""

    enabled: bool = True
    threshold_percent: int = 20
    channels: list[AlertChannel] = [AlertChannel.EMAIL]
    email_recipients: list[str] = []
    telegram_chat_ids: list[str] = []
    slack_webhook_url: str | None = None
    cooldown_hours: int = 24
