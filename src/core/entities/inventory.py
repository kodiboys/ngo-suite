# FILE: src/core/entities/inventory.py
# MODULE: Inventory & Warehouse Management Entities
# Lagerverwaltung mit projektbezogenen Items, Bestandsführung, Seriennummern
# Version: 3.0 - Erweitert um Bedarfsverknüpfung & Transparenz-Features

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Column, String, DateTime, Numeric, Boolean, JSON, 
    ForeignKey, Index, CheckConstraint, UniqueConstraint,
    Text, Integer, Float
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property
from pydantic import BaseModel, Field, validator

from src.core.entities.base import Base, Project


# ==================== Enums ====================

class ItemCategory(str, Enum):
    """Warenkategorien für Lager"""
    FOOD = "food"           # Lebensmittel
    CLOTHING = "clothing"   # Kleidung
    MEDICAL = "medical"     # Medizinische Güter
    HYGIENE = "hygiene"     # Hygieneartikel
    SCHOOL = "school"       # Schulmaterial
    TECH = "tech"           # Technik/Geräte
    FURNITURE = "furniture" # Möbel
    SHELTER = "shelter"     # Unterkünfte/Zelte
    TOOLS = "tools"         # Werkzeuge
    OTHER = "other"


class ItemCondition(str, Enum):
    """Zustand der Lagerartikel"""
    NEW = "new"             # Neuware
    GOOD = "good"           # Gut erhalten
    USED = "used"           # Gebraucht
    DAMAGED = "damaged"     # Beschädigt
    EXPIRED = "expired"     # Abgelaufen (Lebensmittel)


class StockMovementType(str, Enum):
    """Art der Lagerbewegung"""
    INBOUND = "inbound"         # Zugang (Spende/Einkauf)
    OUTBOUND = "outbound"       # Abgang (Ausgabe an Projekt)
    TRANSFER = "transfer"       # Umbuchung
    ADJUSTMENT = "adjustment"   # Inventur-Korrektur
    RETURN = "return"           # Rückgabe
    LOSS = "loss"               # Verlust/Schwund
    NEED_FULFILLMENT = "need_fulfillment"  # Erfüllung eines Bedarfs (v3.0)


class StockStatus(str, Enum):
    """Bestandsstatus"""
    IN_STOCK = "in_stock"           # Auf Lager
    LOW_STOCK = "low_stock"         # Mindestbestand unterschritten
    OUT_OF_STOCK = "out_of_stock"   # Nicht auf Lager
    BACKORDER = "backorder"         # Nachbestellt
    DISCONTINUED = "discontinued"   # Ausgelaufen
    RESERVED = "reserved"           # Für Bedarf reserviert (v3.0)


# ==================== Inventory Item Model ====================

class InventoryItem(Base):
    """
    Lagerartikel mit projektbezogener Zuordnung
    Unterstützt Seriennummern, Chargen, Verfallsdaten
    
    Erweiterung v3.0:
    - need_id: Verknüpfung mit spezifischem Bedarf
    - reserved_for_need: Für Bedarf reservierte Menge
    - last_need_fulfillment_at: Letzte Bedarfserfüllung
    """
    __tablename__ = "inventory_items"
    __table_args__ = (
        Index("idx_item_sku", "sku"),
        Index("idx_item_project_category", "project_id", "category"),
        Index("idx_item_location", "warehouse_location"),
        Index("idx_item_need", "need_id"),  # v3.0
        UniqueConstraint("sku", "project_id", name="uq_sku_per_project"),
        CheckConstraint("quantity >= 0", name="ck_non_negative_quantity"),
        CheckConstraint("reserved_quantity >= 0", name="ck_non_negative_reserved"),
        CheckConstraint("reserved_for_need >= 0", name="ck_non_negative_need_reserved"),  # v3.0
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
    
    # Verknüpfung mit Bedarf (v3.0)
    need_id = Column(PGUUID(as_uuid=True), ForeignKey("project_needs.id", ondelete="SET NULL"), nullable=True)
    
    # Bestandsdaten
    quantity = Column(Integer, nullable=False, default=0)
    reserved_quantity = Column(Integer, nullable=False, default=0)  # Für geplante Ausgaben
    reserved_for_need = Column(Integer, nullable=False, default=0)  # Für Bedarf reserviert (v3.0)
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
    
    # Transparenz (v3.0)
    show_on_transparency = Column(Boolean, default=True)  # Auf Transparenzseite anzeigen
    
    # Bedarfserfüllung (v3.0)
    last_need_fulfillment_at = Column(DateTime, nullable=True)  # Letzte Bedarfserfüllung
    need_fulfillment_count = Column(Integer, default=0)  # Anzahl Bedarfserfüllungen
    
    # Audit
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_inventory_at = Column(DateTime, nullable=True)  # Letzte Inventur
    
    # Relationships
    project = relationship("Project", back_populates="inventory_items")
    need = relationship("ProjectNeed", back_populates="inventory_item", foreign_keys=[need_id])
    movements = relationship("StockMovement", back_populates="item")
    packinglist_items = relationship("PackingListItem", back_populates="item")
    
    @hybrid_property
    def available_quantity(self) -> int:
        """Verfügbare Menge (Bestand - reserviert)"""
        return self.quantity - self.reserved_quantity - self.reserved_for_need
    
    @hybrid_property
    def need_reserved_quantity(self) -> int:
        """Für Bedarf reservierte Menge (v3.0)"""
        return self.reserved_for_need
    
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
            if self.reserved_for_need > 0:
                self.status = StockStatus.RESERVED
            else:
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
    
    def reserve_for_need(self, quantity: int) -> bool:
        """
        Reserviert Menge für einen Bedarf (v3.0)
        
        Args:
            quantity: Zu reservierende Menge
            
        Returns:
            bool: True wenn Reservierung erfolgreich
        """
        if quantity <= self.available_quantity:
            self.reserved_for_need += quantity
            self.update_stock_status()
            return True
        return False
    
    def fulfill_need(self, quantity: int) -> bool:
        """
        Erfüllt einen Bedarf aus dem Lagerbestand (v3.0)
        
        Args:
            quantity: Zu liefernde Menge
            
        Returns:
            bool: True wenn Lieferung erfolgreich
        """
        if quantity <= self.reserved_for_need:
            self.reserved_for_need -= quantity
            self.quantity -= quantity
            self.last_need_fulfillment_at = datetime.utcnow()
            self.need_fulfillment_count += 1
            self.update_stock_status()
            self.calculate_total_value()
            return True
        return False


# ==================== Stock Movement Model ====================

class StockMovement(Base):
    """
    Lagerbewegungen mit Audit-Trail
    Jede Bewegung wird protokolliert (GoBD-konform)
    
    Erweiterung v3.0:
    - need_id: Verknüpfung mit Bedarf
    - need_fulfillment_id: Referenz zur Bedarfserfüllung
    """
    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("idx_movement_item_date", "item_id", "movement_date"),
        Index("idx_movement_project", "project_id"),
        Index("idx_movement_reference", "reference_type", "reference_id"),
        Index("idx_movement_need", "need_id"),  # v3.0
    )
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Verknüpfungen
    item_id = Column(PGUUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    
    # Bedarfsverknüpfung (v3.0)
    need_id = Column(PGUUID(as_uuid=True), ForeignKey("project_needs.id", ondelete="SET NULL"), nullable=True)
    need_fulfillment_id = Column(PGUUID(as_uuid=True), nullable=True)  # Referenz zur Bedarfserfüllung
    
    # Bewegungsdaten
    movement_type = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False)
    previous_quantity = Column(Integer, nullable=False)
    new_quantity = Column(Integer, nullable=False)
    
    # Referenz (z.B. Spende ID, Bestellung ID, Packinglist ID)
    reference_type = Column(String(50), nullable=True)  # donation, order, packinglist, need_fulfillment
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
    movement_date = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    item = relationship("InventoryItem", back_populates="movements")
    project = relationship("Project")
    need = relationship("ProjectNeed", foreign_keys=[need_id])
    
    def __post_init__(self):
        self.new_quantity = self.previous_quantity + self.quantity if self.movement_type == StockMovementType.INBOUND else self.previous_quantity - self.quantity


# ==================== Packing List Model ====================

class PackingList(Base):
    """
    Packliste für Projektauslieferungen
    Mit PDF-Generierung, QR-Code, Unterschrift
    
    Erweiterung v3.0:
    - need_ids: Verknüpfung mit Bedarfen
    - transparency_hash: Für öffentliche Sendungsverfolgung
    """
    __tablename__ = "packing_lists"
    __table_args__ = (
        Index("idx_packinglist_project", "project_id"),
        Index("idx_packinglist_status_date", "status", "delivery_date"),
        Index("idx_packinglist_number", "packing_list_number", unique=True),
        Index("idx_packinglist_transparency", "transparency_hash"),  # v3.0
    )
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    packing_list_number = Column(String(50), nullable=False, unique=True)  # PL-2024-00001
    
    # Projekt
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    project_name = Column(String(200), nullable=False)  # Denormalisiert für PDF
    
    # Bedarfe (v3.0)
    need_ids = Column(JSONB, default=list)  # Liste der erfüllten Bedarfe
    
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
    
    # Transparenz (v3.0)
    transparency_hash = Column(String(50), nullable=True)  # Für öffentliche Sendungsverfolgung
    show_on_transparency = Column(Boolean, default=True)  # Auf Transparenzseite anzeigen
    
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
    
    def generate_transparency_hash(self):
        """Generiert Hash für öffentliche Sendungsverfolgung (v3.0)"""
        import hashlib
        data = f"{self.packing_list_number}|{self.recipient_email}|{self.created_at}"
        self.transparency_hash = hashlib.sha256(data.encode()).hexdigest()[:16].upper()


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
    
    # Bedarfsverknüpfung (v3.0)
    need_id = Column(PGUUID(as_uuid=True), ForeignKey("project_needs.id", ondelete="SET NULL"), nullable=True)
    
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
    need = relationship("ProjectNeed", foreign_keys=[need_id])


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
    """API Schema für neue Lagerartikel (v3.0 mit need_id)"""
    name: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = None
    sku: str = Field(..., min_length=3, max_length=50)
    category: ItemCategory = ItemCategory.OTHER
    condition: ItemCondition = ItemCondition.GOOD
    project_id: UUID
    need_id: Optional[UUID] = None  # v3.0: Verknüpfung mit Bedarf
    quantity: int = Field(0, ge=0)
    min_stock_level: int = Field(0, ge=0)
    unit_price: Optional[Decimal] = Field(None, ge=0)
    warehouse_location: Optional[str] = None
    batch_number: Optional[str] = None
    expiration_date: Optional[datetime] = None
    requires_special_handling: bool = False
    show_on_transparency: bool = True  # v3.0
    
    @validator('sku')
    def validate_sku(cls, v):
        return v.upper()
    
    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }


class StockMovementCreate(BaseModel):
    """API Schema für Lagerbewegungen (v3.0 mit need_id)"""
    item_id: UUID
    movement_type: StockMovementType
    quantity: int = Field(..., gt=0)
    reason: Optional[str] = None
    destination_location: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[UUID] = None
    need_id: Optional[UUID] = None  # v3.0: Verknüpfung mit Bedarf


class PackingListCreate(BaseModel):
    """API Schema für Packliste (v3.0 mit need_ids)"""
    project_id: UUID
    recipient_name: str = Field(..., min_length=3)
    recipient_address: str = Field(..., min_length=5)
    recipient_email: Optional[str] = None
    shipping_date: datetime
    shipping_method: Optional[str] = None
    items: List[Dict[str, Any]]  # [{item_id, quantity, need_id?}]
    need_ids: List[UUID] = []  # v3.0: Erfüllte Bedarfe
    notes: Optional[str] = None
    show_on_transparency: bool = True  # v3.0


class PackingListResponse(BaseModel):
    """API Response für Packliste (v3.0 mit transparency_hash)"""
    id: UUID
    packing_list_number: str
    project_id: UUID
    recipient_name: str
    status: str
    items: List[Dict[str, Any]]
    pdf_url: Optional[str]
    transparency_hash: Optional[str] = None  # v3.0
    created_at: datetime
    
    class Config:
        orm_mode = True


class NeedFulfillmentRequest(BaseModel):
    """v3.0: Anfrage zur Bedarfserfüllung"""
    need_id: UUID
    quantity: int = Field(..., gt=0)
    item_id: UUID  # Aus welchem Lager wird entnommen
    shipping_method: Optional[str] = None
    notes: Optional[str] = None