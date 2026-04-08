# FILE: src/services/accounting.py
# MODULE: Accounting Service für SKR42-Buchungen & DATEV-Export
# GoBD-konforme Buchhaltung mit automatischen Kontierungen

import csv
import io
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, List, Tuple
from uuid import UUID

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.entities.base import Donation, Project, SKR42Account, Transaction, AuditLog
from src.core.events.event_bus import EventBus, Event

logger = logging.getLogger(__name__)


class AccountingService:
    """
    Buchhaltungsservice mit:
    - SKR42 Kontierungen
    - Automatische Buchung von Spenden
    - DATEV-Export (CSV, FUXT)
    - GoBD-konforme Belegverwaltung
    - Jahresabschlüsse
    """
    
    def __init__(self, session_factory, event_bus: EventBus):
        self.session_factory = session_factory
        self.event_bus = event_bus
    
    # ==================== SKR42 Buchungen ====================
    
    async def book_donation(self, donation_id: UUID, user_id: UUID) -> Dict[str, Any]:
        """
        Bucht eine Spende nach SKR42
        - Spendenkonto: 40000-49999 (abhängig vom Projekt)
        - Bankkonto: 12000 (oder 18000 für PayPal)
        """
        async with self.session_factory() as session:
            # Lade Spende
            stmt = select(Donation).where(Donation.id == donation_id)
            result = await session.execute(stmt)
            donation = result.scalar_one()
            
            # Bestimme Konten basierend auf Payment Provider
            if donation.payment_provider == "stripe":
                bank_account = "12000"  # Bankkonto
            elif donation.payment_provider == "paypal":
                bank_account = "18000"  # PayPal-Konto
            else:
                bank_account = "12000"  # Default
            
            # SKR42 Buchung erstellen
            booking = {
                "date": donation.created_at,
                "debit_account": bank_account,  # Soll (Bank)
                "credit_account": donation.skr42_account_id,  # Haben (Spenden)
                "amount": donation.amount,
                "reference": donation.payment_intent_id,
                "description": f"Spende für Projekt {donation.project_id}",
                "cost_center": donation.cost_center,
                "tax_code": "0"  # Spenden sind steuerfrei
            }
            
            # Speichere Buchung
            transaction = await self._save_booking(session, booking, user_id, donation.id)
            
            # Publish Event
            await self.event_bus.publish(Event(
                aggregate_id=donation.id,
                aggregate_type="Donation",
                event_type="DonationBooked",
                data=booking,
                user_id=user_id,
                metadata={}
            ))
            
            return {
                "booking_id": str(transaction.id),
                "booking": booking,
                "status": "completed"
            }
    
    async def _save_booking(
        self,
        session: AsyncSession,
        booking: Dict[str, Any],
        user_id: UUID,
        donation_id: UUID
    ) -> Transaction:
        """Speichert Buchung in der Datenbank"""
        
        # Hole Konten-IDs
        debit_stmt = select(SKR42Account).where(SKR42Account.account_number == booking["debit_account"])
        debit_result = await session.execute(debit_stmt)
        debit_account = debit_result.scalar_one()
        
        credit_stmt = select(SKR42Account).where(SKR42Account.account_number == booking["credit_account"])
        credit_result = await session.execute(credit_stmt)
        credit_account = credit_result.scalar_one()
        
        # Erstelle Transaction
        transaction = Transaction(
            booking_date=booking["date"],
            value_date=booking["date"],
            debit_account_id=debit_account.id,
            credit_account_id=credit_account.id,
            amount=booking["amount"],
            reference_type="donation",
            reference_id=donation_id,
            description=booking["description"],
            cost_center=booking["cost_center"],
            tax_code=booking["tax_code"],
            created_by=user_id
        )
        
        session.add(transaction)
        await session.commit()
        await session.refresh(transaction)
        
        # Audit Log
        audit = AuditLog(
            user_id=user_id,
            action="SKR42_BOOKING",
            entity_type="transaction",
            entity_id=transaction.id,
            new_values=booking,
            ip_address="system",
            retention_until=datetime.utcnow() + timedelta(days=3650)
        )
        session.add(audit)
        await session.commit()
        
        return transaction
    
    # ==================== DATEV Export ====================
    
    async def export_datev_csv(
        self,
        start_date: datetime,
        end_date: datetime,
        project_id: Optional[UUID] = None
    ) -> bytes:
        """
        Exportiert Buchungen im DATEV-Format (CSV)
        Kompatibel mit DATEV UNICO, DATEV Rechnungswesen
        """
        async with self.session_factory() as session:
            # Sammle Buchungen
            stmt = select(Transaction).where(
                Transaction.booking_date.between(start_date, end_date)
            ).order_by(Transaction.booking_date)
            
            if project_id:
                stmt = stmt.join(Transaction.project).where(Project.id == project_id)
            
            result = await session.execute(stmt)
            transactions = result.scalars().all()
            
            # DATEV-Format: UTF-8 mit Semikolon als Trennzeichen
            output = io.StringIO()
            writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
            
            # Kopfzeile (DATEV-spezifisch)
            writer.writerow([
                "Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen",
                "Konto", "Gegenkonto", "Belegdatum", "Belegfeld 1",
                "Buchungstext", "Kostenträger", "Steuer-Code"
            ])
            
            for transaction in transactions:
                # Hole Kontonummern
                debit_stmt = select(SKR42Account).where(SKR42Account.id == transaction.debit_account_id)
                debit_result = await session.execute(debit_stmt)
                debit_account = debit_result.scalar_one()
                
                credit_stmt = select(SKR42Account).where(SKR42Account.id == transaction.credit_account_id)
                credit_result = await session.execute(credit_stmt)
                credit_account = credit_result.scalar_one()
                
                writer.writerow([
                    f"{transaction.amount:.2f}".replace('.', ','),  # Deutsche Dezimaltrennung
                    "S",  # Soll
                    debit_account.account_number,
                    credit_account.account_number,
                    transaction.booking_date.strftime("%d%m%Y"),
                    str(transaction.reference_id)[:20] if transaction.reference_id else "",
                    transaction.description[:60],
                    transaction.cost_center or "",
                    transaction.tax_code or "0"
                ])
            
            return output.getvalue().encode('utf-8-sig')
    
    async def export_datev_fuxt(self, start_date: datetime, end_date: datetime) -> bytes:
        """
        Exportiert Buchungen im DATEV FUXT-Format
        Für professionelle Buchhaltungssoftware
        """
        async with self.session_factory() as session:
            stmt = select(Transaction).where(
                Transaction.booking_date.between(start_date, end_date)
            ).order_by(Transaction.booking_date)
            
            result = await session.execute(stmt)
            transactions = result.scalars().all()
            
            # FUXT ist ein XML-basiertes Format
            xml_lines = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<datev:export xmlns:datev="http://www.datev.de/datev-xml/export">',
                '    <datev:header>',
                f'        <datev:export_date>{datetime.utcnow().strftime("%Y-%m-%d")}</datev:export_date>',
                f'        <datev:start_date>{start_date.strftime("%Y-%m-%d")}</datev:start_date>',
                f'        <datev:end_date>{end_date.strftime("%Y-%m-%d")}</datev:end_date>',
                '        <datev:software>TrueAngels NGO Suite v3.0</datev:software>',
                '    </datev:header>',
                '    <datev:transactions>'
            ]
            
            for transaction in transactions:
                # Hole Kontonummern
                debit_stmt = select(SKR42Account).where(SKR42Account.id == transaction.debit_account_id)
                debit_result = await session.execute(debit_stmt)
                debit_account = debit_result.scalar_one()
                
                credit_stmt = select(SKR42Account).where(SKR42Account.id == transaction.credit_account_id)
                credit_result = await session.execute(credit_stmt)
                credit_account = credit_result.scalar_one()
                
                xml_lines.append('        <datev:transaction>')
                xml_lines.append(f'            <datev:date>{transaction.booking_date.strftime("%Y-%m-%d")}</datev:date>')
                xml_lines.append(f'            <datev:debit_account>{debit_account.account_number}</datev:debit_account>')
                xml_lines.append(f'            <datev:credit_account>{credit_account.account_number}</datev:credit_account>')
                xml_lines.append(f'            <datev:amount>{transaction.amount:.2f}</datev:amount>')
                xml_lines.append(f'            <datev:description>{self._escape_xml(transaction.description)}</datev:description>')
                if transaction.cost_center:
                    xml_lines.append(f'            <datev:cost_center>{transaction.cost_center}</datev:cost_center>')
                xml_lines.append('        </datev:transaction>')
            
            xml_lines.append('    </datev:transactions>')
            xml_lines.append('</datev:export>')
            
            return '\n'.join(xml_lines).encode('utf-8')
    
    def _escape_xml(self, text: str) -> str:
        """Escape XML Sonderzeichen"""
        replacements = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&apos;"
        }
        for char, escape in replacements.items():
            text = text.replace(char, escape)
        return text
    
    # ==================== SKR42 Kontenrahmen ====================
    
    async def get_skr42_hierarchy(self) -> Dict[str, Any]:
        """Liefert die SKR42-Kontenhierarchie für Berichte"""
        async with self.session_factory() as session:
            stmt = select(SKR42Account).where(
                SKR42Account.is_active == True
            ).order_by(SKR42Account.account_number)
            
            result = await session.execute(stmt)
            accounts = result.scalars().all()
            
            # Baue Baumstruktur
            hierarchy = {}
            for account in accounts:
                if account.level == 0:
                    hierarchy[account.account_number] = {
                        "id": str(account.id),
                        "name": account.account_name,
                        "type": account.account_type,
                        "children": []
                    }
            
            for account in accounts:
                if account.parent_account_number and account.parent_account_number in hierarchy:
                    hierarchy[account.parent_account_number]["children"].append({
                        "number": account.account_number,
                        "name": account.account_name,
                        "type": account.account_type,
                        "cost_center": account.cost_center,
                        "id": str(account.id)
                    })
            
            return hierarchy
    
    async def get_account_balance(
        self,
        account_number: str,
        year: int,
        project_id: Optional[UUID] = None
    ) -> Decimal:
        """Berechnet den Saldo eines Kontos für ein Jahr"""
        async with self.session_factory() as session:
            start_date = datetime(year, 1, 1)
            end_date = datetime(year, 12, 31, 23, 59, 59)
            
            # Hole Konto
            stmt = select(SKR42Account).where(SKR42Account.account_number == account_number)
            result = await session.execute(stmt)
            account = result.scalar_one()
            
            # Summiere Soll-Buchungen
            debit_stmt = select(func.sum(Transaction.amount)).where(
                Transaction.debit_account_id == account.id,
                Transaction.booking_date.between(start_date, end_date)
            )
            if project_id:
                debit_stmt = debit_stmt.where(Transaction.project_id == project_id)
            debit_result = await session.execute(debit_stmt)
            debit_total = debit_result.scalar() or Decimal(0)
            
            # Summiere Haben-Buchungen
            credit_stmt = select(func.sum(Transaction.amount)).where(
                Transaction.credit_account_id == account.id,
                Transaction.booking_date.between(start_date, end_date)
            )
            if project_id:
                credit_stmt = credit_stmt.where(Transaction.project_id == project_id)
            credit_result = await session.execute(credit_stmt)
            credit_total = credit_result.scalar() or Decimal(0)
            
            # Saldo = Soll - Haben (für Aktivkonten)
            if account.account_type == "AKTIVA":
                return debit_total - credit_total
            else:
                return credit_total - debit_total
    
    # ==================== Jahresabschluss ====================
    
    async def create_yearly_closing(self, year: int, user_id: UUID) -> Dict[str, Any]:
        """
        Erstellt Jahresabschlussbuchungen
        - Abschluss der Erfolgskonten (ERTRAEGE, AUFWENDUNGEN)
        - Ermittlung des Jahresüberschusses
        """
        async with self.session_factory() as session:
            # Sammle alle Erfolgskonten
            stmt = select(SKR42Account).where(
                SKR42Account.account_type.in_(["ERTRAEGE", "AUFWENDUNGEN"]),
                SKR42Account.is_active == True
            )
            result = await session.execute(stmt)
            accounts = result.scalars().all()
            
            closing_entries = []
            total_profit = Decimal(0)
            
            for account in accounts:
                balance = await self.get_account_balance(account.account_number, year)
                
                if balance != 0:
                    if account.account_type == "ERTRAEGE":
                        # Erträge werden auf Gewinnvortrag gebucht
                        booking = {
                            "date": datetime(year, 12, 31),
                            "debit_account": account.account_number,
                            "credit_account": "90000",  # Gewinnvortrag
                            "amount": abs(balance),
                            "description": f"Jahresabschluss {year} - Abschluss {account.account_name}",
                            "cost_center": None,
                            "tax_code": "0"
                        }
                        total_profit += balance
                    else:
                        # Aufwendungen werden auf Gewinnvortrag gebucht
                        booking = {
                            "date": datetime(year, 12, 31),
                            "debit_account": "90000",  # Gewinnvortrag
                            "credit_account": account.account_number,
                            "amount": abs(balance),
                            "description": f"Jahresabschluss {year} - Abschluss {account.account_name}",
                            "cost_center": None,
                            "tax_code": "0"
                        }
                        total_profit -= balance
                    
                    # Speichere Buchung
                    transaction = await self._save_booking(session, booking, user_id, None)
                    closing_entries.append({
                        "account": account.account_number,
                        "account_name": account.account_name,
                        "balance": float(balance),
                        "booking_id": str(transaction.id)
                    })
            
            await session.commit()
            
            return {
                "year": year,
                "closing_entries": closing_entries,
                "total_profit": float(total_profit),
                "created_at": datetime.utcnow().isoformat()
            }
    
    # ==================== Reports ====================
    
    async def get_profit_and_loss(
        self,
        year: int,
        project_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Ermittelt Gewinn und Verlust für ein Jahr
        """
        async with self.session_factory() as session:
            # Erträge (40000-49999)
            revenue_stmt = select(SKR42Account).where(
                SKR42Account.account_number.between("40000", "49999"),
                SKR42Account.is_active == True
            )
            revenue_result = await session.execute(revenue_stmt)
            revenue_accounts = revenue_result.scalars().all()
            
            total_revenue = Decimal(0)
            revenues = []
            
            for account in revenue_accounts:
                balance = await self.get_account_balance(account.account_number, year, project_id)
                if balance != 0:
                    total_revenue += balance
                    revenues.append({
                        "account": account.account_number,
                        "name": account.account_name,
                        "balance": float(balance)
                    })
            
            # Aufwendungen (60000-79999)
            expense_stmt = select(SKR42Account).where(
                SKR42Account.account_number.between("60000", "79999"),
                SKR42Account.is_active == True
            )
            expense_result = await session.execute(expense_stmt)
            expense_accounts = expense_result.scalars().all()
            
            total_expenses = Decimal(0)
            expenses = []
            
            for account in expense_accounts:
                balance = await self.get_account_balance(account.account_number, year, project_id)
                if balance != 0:
                    total_expenses += abs(balance)
                    expenses.append({
                        "account": account.account_number,
                        "name": account.account_name,
                        "balance": float(abs(balance))
                    })
            
            profit = total_revenue - total_expenses
            
            return {
                "year": year,
                "project_id": str(project_id) if project_id else None,
                "total_revenue": float(total_revenue),
                "total_expenses": float(total_expenses),
                "profit": float(profit),
                "revenues": revenues,
                "expenses": expenses
            }
    
    async def get_balance_sheet(
        self,
        year: int,
        project_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Ermittelt Bilanz (Aktiva / Passiva) für ein Jahr
        """
        async with self.session_factory() as session:
            # Aktiva (00000-39999)
            active_stmt = select(SKR42Account).where(
                SKR42Account.account_number.between("00000", "39999"),
                SKR42Account.is_active == True
            )
            active_result = await session.execute(active_stmt)
            active_accounts = active_result.scalars().all()
            
            total_active = Decimal(0)
            active_items = []
            
            for account in active_accounts:
                balance = await self.get_account_balance(account.account_number, year, project_id)
                if balance != 0:
                    total_active += balance
                    active_items.append({
                        "account": account.account_number,
                        "name": account.account_name,
                        "balance": float(balance)
                    })
            
            # Passiva (40000-99999)
            passive_stmt = select(SKR42Account).where(
                SKR42Account.account_number.between("40000", "99999"),
                SKR42Account.is_active == True
            )
            passive_result = await session.execute(passive_stmt)
            passive_accounts = passive_result.scalars().all()
            
            total_passive = Decimal(0)
            passive_items = []
            
            for account in passive_accounts:
                balance = await self.get_account_balance(account.account_number, year, project_id)
                if balance != 0:
                    total_passive += balance
                    passive_items.append({
                        "account": account.account_number,
                        "name": account.account_name,
                        "balance": float(balance)
                    })
            
            return {
                "year": year,
                "project_id": str(project_id) if project_id else None,
                "total_active": float(total_active),
                "total_passive": float(total_passive),
                "active_items": active_items,
                "passive_items": passive_items,
                "is_balanced": abs(total_active - total_passive) < Decimal("0.01")
            }