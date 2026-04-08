# FILE: src/core/entities/transaction.py
# MODULE: Transaction Entity für SKR42 Buchungen

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Column, String, DateTime, Numeric, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from src.core.entities.base import Base


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
        Index("idx_transaction_reference", "reference_type", "reference_id"),
    )
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=UUID)
    
    # Buchungsdaten
    booking_date = Column(DateTime, nullable=False)
    value_date = Column(DateTime, nullable=True)
    
    # Konten
    debit_account_id = Column(PGUUID(as_uuid=True), ForeignKey("skr42_accounts.id"), nullable=False)
    credit_account_id = Column(PGUUID(as_uuid=True), ForeignKey("skr42_accounts.id"), nullable=False)
    
    # Betrag
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="EUR")
    
    # Referenz
    reference_type = Column(String(50), nullable=True)  # donation, invoice, etc.
    reference_id = Column(PGUUID(as_uuid=True), nullable=True)
    
    # Projekt (optional)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    cost_center = Column(String(50), nullable=True)
    
    # Beschreibung
    description = Column(String(500), nullable=True)
    tax_code = Column(String(10), nullable=True)
    
    # Compliance
    is_reversed = Column(Boolean, default=False)
    reversed_by_id = Column(PGUUID(as_uuid=True), nullable=True)
    
    # Audit
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)