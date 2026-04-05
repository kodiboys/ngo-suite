# FILE: src/core/entities/inventory.py
# MODULE: Inventory & Warehouse Management Entities
# Lagerverwaltung mit projektbezogenen Items, Bestandsführung, Seriennummern

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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, validates

from src.core.entities.base import Base

# ==================== Enums ====================

class ItemCategory(str, Enum):
    """Warenkategorien für Lager"""
    FOOD = "food"  # Lebensmittel
    CLOTHING = "clothing"  # Kleidung
    MEDICAL = "medical"  # Medizinische Güter
    HYGIENE = "hygiene"  # Hygieneartikel
    SCHOOL = "school"  # Schulmaterial
    TECH = "tech"  # Technik/Geräte
    FURNITURE = "furniture"  # Möbel
    OTHER = "other"

class ItemCondition(str, Enum):
    """Zustand der Lagerartikel"""
    NEW = "new"  # Neuware
    GOOD = "good"  # Gut erhalten
    USED = "used"  # Gebraucht
    DAMAGED = "damaged"  # Beschädigt
    EXPIRED = "expired"  # Abgelaufen (Lebensmittel)

class StockMovementType(str, Enum):
    """Art der Lagerbewegung"""
    INBOUND = "inbound"  # Zugang (Spende/Einkauf)
    OUTBOUND = "outbound"  # Abgang (Ausgabe an Projekt)
    TRANSFER = "transfer"  # Umbuchung
    ADJUSTMENT = "adjustment"  # Inventur-Korrektur
    RETURN = "return"  # Rückgabe
    LOSS = "loss"  # Verlust/Schwund

class StockStatus(str, Enum):
    """Bestandsstatus"""
    IN_STOCK = "in_stock"  # Auf Lager
    LOW_STOCK = "low_stock"  # Mindestbestand unterschritten
    OUT_OF_STOCK = "out_of_stock"  # Nicht auf Lager
    BACKORDER = "backorder"  # Nachbestellt
    DISCONTINUED = "discontinued"  # Ausgelaufen

# ==================== Inventory Item Model ====================

class InventoryItem(Base):
    """
    Lagerartikel mit projektbezogener Zuordnung
    Unterstützt Seriennummern, Chargen, Verfallsdaten
    """
    __tablename__ = "inventory_items"
    __table_args__ = (
        Index("idx_item_sku", "sku"),
        Index("idx_item_project_category", "project_id", "category"),
        Index("idx_item_location", "warehouse_location"),
        UniqueConstraint("sku", "project_id", name="uq_sku_per_project"),
        CheckConstraint("quantity >= 0", name="ck_non_negative_quantity"),
        CheckConstraint("min_stock_level >= 0", name="ck_min_stock_positive"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Basisinformationen
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    sku = Column(String(50), nullable=False)  # Stock Keeping Unit (eindeutig pro Projekt)
    category = Column(String(50), nullable=False, default=ItemCategory.OTHER)
    condition = Column(String(50), nullable=False, default=ItemCondition.GOOD)

    # Projektzuordnung (SKR42-konform)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    cost_center = Column(String(50), nullable=False)  # Aus Projekt übernommen

    # Bestandsdaten
    quantity = Column(Integer, nullable=False, default=0)
    reserved_quantity = Column(Integer, nullable=False, default=0)  # Für geplante Ausgaben
    min_stock_level = Column(Integer, nullable=False, default=0)  # Mindestbestand
    max_stock_level = Column(Integer, nullable=True)  # Maximalbestand
    reorder_point = Column(Integer, nullable=False, default=0)  # Bestellpunkt

    # Finanzdaten (für SKR42 Buchungen)
    unit_price = Column(Numeric(10, 2), nullable=True)  # Einkaufspreis pro Einheit
    total_value = Column(Numeric(12, 2), nullable=True)  # Gesamtwert (quantity * unit_price)

    # Lagermetadaten
    warehouse_location = Column(String(100), nullable=True)  # Regal/Gang/Fach
    batch_number = Column(String(50), nullable=True)  # Chargennummer
    serial_numbers = Column(JSONB, default=list)  # Liste von Seriennummern
    expiration_date = Column(DateTime, nullable=True)  # Verfallsdatum (für Lebensmittel/Medizin)

    # Status
    status = Column(String(50), nullable=False, default=StockStatus.IN_STOCK)
    is_active = Column(Boolean, default=True)
    is_perishable = Column(Boolean, default=False)  # Verderblich

    # Bilder/Dokumente
    image_url = Column(String(500), nullable=True)
    documents = Column(JSONB, default=list)  # Zertifikate, Sicherheitsdatenblätter

    # Compliance
    requires_special_handling = Column(Boolean, default=False)
    hazardous_goods = Column(Boolean, default=False)  # Gefahrgut
    temperature_controlled = Column(Boolean, default=False)  # Kühlkette

    # Audit
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_inventory_at = Column(DateTime, nullable=True)  # Letzte Inventur

    # Relationships
    project = relationship("Project", back_populates="inventory_items")
    movements = relationship("StockMovement", back_populates="item")
    packinglist_items = relationship("PackingListItem", back_populates="item")

    @hybrid_property
    def available_quantity(self) -> int:
        """Verfügbare Menge (Bestand - reserviert)"""
        return self.quantity - self.reserved_quantity

    @validates('quantity')
    def validate_quantity(self, key, quantity):
        if quantity < 0:
            raise ValueError(f"Menge kann nicht negativ sein: {quantity}")
        return quantity

    @validates('sku')
    def validate_sku(self, key, sku):
        if not sku or len(sku) < 3:
            raise ValueError(f"SKU muss mindestens 3 Zeichen haben: {sku}")
        return sku.upper()

    def update_stock_status(self):
        """Aktualisiert Bestandsstatus basierend auf Menge"""
        if self.available_quantity <= 0:
            self.status = StockStatus.OUT_OF_STOCK
        elif self.available_quantity <= self.reorder_point:
            self.status = StockStatus.LOW_STOCK
        else:
            self.status = StockStatus.IN_STOCK

        # Prüfe Verfallsdatum
        if self.expiration_date and self.expiration_date < datetime.utcnow():
            self.status = StockStatus.DISCONTINUED
            self.is_active = False

    def calculate_total_value(self):
        """Berechnet Gesamtwert des Bestands"""
        if self.unit_price:
            self.total_value = self.quantity * self.unit_price

# ==================== Stock Movement Model ====================

class StockMovement(Base):
    """
    Lagerbewegungen mit Audit-Trail
    Jede Bewegung wird protokolliert (GoBD-konform)
    """
    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("idx_movement_item_date", "item_id", "movement_date"),
        Index("idx_movement_project", "project_id"),
        Index("idx_movement_reference", "reference_type", "reference_id"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Verknüpfungen
    item_id = Column(PGUUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)

    # Bewegungsdaten
    movement_type = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False)
    previous_quantity = Column(Integer, nullable=False)
    new_quantity = Column(Integer, nullable=False)

    # Referenz (z.B. Spende ID, Bestellung ID, Packinglist ID)
    reference_type = Column(String(50), nullable=True)  # donation, order, packinglist
    reference_id = Column(PGUUID(as_uuid=True), nullable=True)

    # Zusätzliche Informationen
    reason = Column(Text, nullable=True)
    destination_location = Column(String(100), nullable=True)  # Für Auslieferungen
    tracking_number = Column(String(100), nullable=True)  # Versandtracking

    # SKR42 Buchung (für Warenwert)
    skr42_booking_id = Column(PGUUID(as_uuid=True), nullable=True)  # Verweis auf Buchung

    # Compliance
    requires_approval = Column(Boolean, default=False)
    approved_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    # Audit
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(45), nullable=True)

    # Relationships
    item = relationship("InventoryItem", back_populates="movements")
    project = relationship("Project")

    def __post_init__(self):
        self.new_quantity = self.previous_quantity + self.quantity if self.movement_type == StockMovementType.INBOUND else self.previous_quantity - self.quantity

# ==================== Packing List Model ====================

class PackingList(Base):
    """
    Packliste für Projektauslieferungen
    Mit PDF-Generierung, QR-Code, Unterschrift
    """
    __tablename__ = "packing_lists"
    __table_args__ = (
        Index("idx_packinglist_project", "project_id"),
        Index("idx_packinglist_status_date", "status", "delivery_date"),
        Index("idx_packinglist_number", "packing_list_number", unique=True),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    packing_list_number = Column(String(50), nullable=False, unique=True)  # PL-2024-00001

    # Projekt
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    project_name = Column(String(200), nullable=False)  # Denormalisiert für PDF

    # Empfänger
    recipient_name = Column(String(200), nullable=False)
    recipient_address = Column(Text, nullable=False)
    recipient_email = Column(String(255), nullable=True)
    recipient_phone = Column(String(50), nullable=True)

    # Versand
    shipping_date = Column(DateTime, nullable=False)
    delivery_date = Column(DateTime, nullable=True)
    shipping_method = Column(String(100), nullable=True)  # DHL, UPS, eigene Logistik
    tracking_number = Column(String(100), nullable=True)

    # Status
    status = Column(String(50), nullable=False, default="draft")  # draft, confirmed, shipped, delivered, cancelled

    # Compliance
    requires_signature = Column(Boolean, default=True)
    signed_by = Column(String(200), nullable=True)
    signed_at = Column(DateTime, nullable=True)
    signature_data = Column(Text, nullable=True)  # Base64 der Unterschrift

    # Dokumente
    pdf_url = Column(String(500), nullable=True)
    qr_code = Column(String(500), nullable=True)  # URL zum QR-Code

    # Metadaten
    notes = Column(Text, nullable=True)
    total_weight_kg = Column(Numeric(8, 2), nullable=True)
    total_volume_m3 = Column(Numeric(8, 2), nullable=True)

    # Audit
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    confirmed_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)

    # Relationships
    project = relationship("Project")
    items = relationship("PackingListItem", back_populates="packing_list")

    def generate_number(self):
        """Generiert eindeutige Packlistennummer"""
        year = datetime.utcnow().year
        # In Production: Mit Redis/Zähler
        self.packing_list_number = f"PL-{year}-{uuid4().hex[:6].upper()}"

class PackingListItem(Base):
    """
    Einzelne Positionen in der Packliste
    """
    __tablename__ = "packing_list_items"
    __table_args__ = (
        Index("idx_packinglist_item", "packing_list_id", "item_id"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    packing_list_id = Column(PGUUID(as_uuid=True), ForeignKey("packing_lists.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(PGUUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False)

    # Artikelinformationen (denormalisiert für PDF)
    item_name = Column(String(200), nullable=False)
    item_sku = Column(String(50), nullable=False)
    item_category = Column(String(50), nullable=False)

    # Menge
    quantity_requested = Column(Integer, nullable=False)
    quantity_shipped = Column(Integer, nullable=False)
    quantity_damaged = Column(Integer, default=0)

    # Seriennummern (für hochwertige Güter)
    serial_numbers_shipped = Column(JSONB, default=list)

    # Zustand bei Versand
    condition_at_shipment = Column(String(50), nullable=False, default=ItemCondition.GOOD)

    # Bemerkungen
    notes = Column(Text, nullable=True)

    # Relationships
    packing_list = relationship("PackingList", back_populates="items")
    item = relationship("InventoryItem", back_populates="packinglist_items")

# ==================== Warehouse Model (Multi-Location) ====================

class Warehouse(Base):
    """
    Mehrere Lagerstandorte verwalten
    """
    __tablename__ = "warehouses"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=False, unique=True)
    address = Column(Text, nullable=False)

    # Kontakt
    manager_name = Column(String(200), nullable=True)
    manager_email = Column(String(255), nullable=True)
    manager_phone = Column(String(50), nullable=True)

    # Kapazität
    total_area_sqm = Column(Numeric(10, 2), nullable=True)
    total_pallets = Column(Integer, nullable=True)

    # Features
    has_temperature_control = Column(Boolean, default=False)
    has_hazardous_storage = Column(Boolean, default=False)

    # Status
    is_active = Column(Boolean, default=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ==================== Pydantic Models für API ====================

class InventoryItemCreate(BaseModel):
    """API Schema für neue Lagerartikel"""
    name: str = Field(..., min_length=3, max_length=200)
    description: str | None = None
    sku: str = Field(..., min_length=3, max_length=50)
    category: ItemCategory = ItemCategory.OTHER
    condition: ItemCondition = ItemCondition.GOOD
    project_id: UUID
    quantity: int = Field(0, ge=0)
    min_stock_level: int = Field(0, ge=0)
    unit_price: Decimal | None = Field(None, ge=0)
    warehouse_location: str | None = None
    batch_number: str | None = None
    expiration_date: datetime | None = None
    requires_special_handling: bool = False

    @validator('sku')
    def validate_sku(cls, v):
        return v.upper()

    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }

class StockMovementCreate(BaseModel):
    """API Schema für Lagerbewegungen"""
    item_id: UUID
    movement_type: StockMovementType
    quantity: int = Field(..., gt=0)
    reason: str | None = None
    destination_location: str | None = None
    reference_type: str | None = None
    reference_id: UUID | None = None

class PackingListCreate(BaseModel):
    """API Schema für Packliste"""
    project_id: UUID
    recipient_name: str = Field(..., min_length=3)
    recipient_address: str = Field(..., min_length=5)
    recipient_email: str | None = None
    shipping_date: datetime
    shipping_method: str | None = None
    items: list[dict[str, Any]]  # [{item_id, quantity}]
    notes: str | None = None

class PackingListResponse(BaseModel):
    """API Response für Packliste"""
    id: UUID
    packing_list_number: str
    project_id: UUID
    recipient_name: str
    status: str
    items: list[dict[str, Any]]
    pdf_url: str | None
    created_at: datetime

    class Config:
        orm_mode = True
