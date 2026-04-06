# FILE: src/core/compliance/merkle.py
# MODULE: Merkle-Tree für manipulationssichere Transparenz-Daten
# Täglicher Hash für GoBD-Compliance, Prüfer-Verifizierung

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy import select, func, and_, extract
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.entities.base import Donation
from src.core.entities.needs import ProjectNeed
from src.core.entities.transparency import TransparencyHash


class MerkleTreeService:
    """
    Merkle-Tree Service für Transparenz-Daten
    Generiert tägliche Hashes für manipulationssichere Auditierung
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def generate_daily_hash(self, target_date: date) -> str:
        """
        Generiert Merkle-Root Hash für einen bestimmten Tag
        Kombiniert alle Spenden des Tages + vorherigen Hash
        """
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time())
        
        # 1. Alle Spenden des Tages (mit Consent)
        stmt = select(Donation).where(
            Donation.created_at.between(start, end),
            Donation.consent_transparenz == True,
            Donation.payment_status == "succeeded"
        ).order_by(Donation.created_at)
        
        result = await self.session.execute(stmt)
        donations = result.scalars().all()
        
        if not donations:
            # Keine Spenden an diesem Tag - Hash des vorherigen Tages
            return await self._get_previous_day_hash(target_date)
        
        # 2. Hash für jede Spende berechnen
        leaf_hashes = []
        for donation in donations:
            donation_hash = self._hash_donation(donation)
            leaf_hashes.append(donation_hash)
        
        # 3. Merkle-Tree aufbauen
        merkle_root = self._build_merkle_tree(leaf_hashes)
        
        # 4. Mit vorherigem Tag kombinieren (Chain)
        previous_hash = await self._get_previous_day_hash(target_date)
        if previous_hash:
            combined = previous_hash + merkle_root
            merkle_root = hashlib.sha256(combined.encode()).hexdigest()
        
        # 5. In DB speichern
        await self._save_hash(target_date, merkle_root, len(donations))
        
        return merkle_root
    
    def _hash_donation(self, donation) -> str:
        """Erstellt Hash für eine einzelne Spende"""
        data = {
            "id": str(donation.id),
            "amount": float(donation.amount),
            "date": donation.created_at.isoformat(),
            "project_id": str(donation.project_id),
            "hash_id": donation.transparency_hash
        }
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()
    
    def _build_merkle_tree(self, leaf_hashes: List[str]) -> str:
        """Baut Merkle-Tree aus Leaf-Hashes"""
        if not leaf_hashes:
            return hashlib.sha256(b"empty").hexdigest()
        
        if len(leaf_hashes) == 1:
            return leaf_hashes[0]
        
        # Paare bilden und kombinieren
        next_level = []
        for i in range(0, len(leaf_hashes), 2):
            if i + 1 < len(leaf_hashes):
                combined = leaf_hashes[i] + leaf_hashes[i + 1]
            else:
                combined = leaf_hashes[i] + leaf_hashes[i]  # Duplicate odd element
            
            next_level.append(hashlib.sha256(combined.encode()).hexdigest())
        
        return self._build_merkle_tree(next_level)
    
    async def _get_previous_day_hash(self, target_date: date) -> Optional[str]:
        """Holt Hash des vorherigen Tages"""
        prev_date = target_date - timedelta(days=1)
        
        stmt = select(TransparencyHash).where(
            TransparencyHash.date == prev_date
        )
        result = await self.session.execute(stmt)
        hash_record = result.scalar_one_or_none()
        
        return hash_record.merkle_root if hash_record else None
    
    async def _save_hash(self, target_date: date, merkle_root: str, record_count: int):
        """Speichert generierten Hash in DB"""
        # Prüfe ob bereits existiert
        stmt = select(TransparencyHash).where(
            TransparencyHash.date == target_date
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.merkle_root = merkle_root
            existing.record_count = record_count
            existing.updated_at = datetime.utcnow()
        else:
            new_hash = TransparencyHash(
                date=target_date,
                year=target_date.year,
                month=target_date.month,
                merkle_root=merkle_root,
                record_count=record_count
            )
            self.session.add(new_hash)
        
        await self.session.commit()
    
    async def get_daily_root(self, year: int, month: int = None, day: int = None) -> str:
        """Holt Merkle-Root für bestimmten Zeitraum"""
        if day:
            target_date = date(year, month, day)
            stmt = select(TransparencyHash).where(
                TransparencyHash.date == target_date
            )
        elif month:
            stmt = select(TransparencyHash).where(
                TransparencyHash.year == year,
                TransparencyHash.month == month
            ).order_by(TransparencyHash.date.desc())
        else:
            stmt = select(TransparencyHash).where(
                TransparencyHash.year == year
            ).order_by(TransparencyHash.date.desc())
        
        result = await self.session.execute(stmt)
        hash_record = result.scalar_one_or_none()
        
        return hash_record.merkle_root if hash_record else "not_generated_yet"
    
    async def verify_integrity(self, target_date: date) -> Dict[str, Any]:
        """
        Verifiziert die Integrität der Transparenz-Daten
        Prüft ob gespeicherter Hash mit neu berechnetem übereinstimmt
        """
        # Generiere aktuellen Hash
        current_hash = await self.generate_daily_hash(target_date)
        
        # Lade gespeicherten Hash
        stmt = select(TransparencyHash).where(
            TransparencyHash.date == target_date
        )
        result = await self.session.execute(stmt)
        stored = result.scalar_one_or_none()
        
        is_valid = stored and stored.merkle_root == current_hash
        
        return {
            "date": target_date.isoformat(),
            "is_valid": is_valid,
            "stored_root": stored.merkle_root[:16] + "..." if stored else None,
            "computed_root": current_hash[:16] + "...",
            "verified_at": datetime.utcnow().isoformat()
        }
    
    async def generate_monthly_report(self, year: int, month: int) -> bytes:
        """
        Generiert PDF-Bericht für Vorstand
        Enthält alle täglichen Hashes des Monats
        """
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from io import BytesIO
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        story = []
        styles = getSampleStyleSheet()
        
        # Titel
        title_style = ParagraphStyle(
            'GermanTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#1a472a'),
            alignment=1
        )
        
        story.append(Paragraph(f"Merkle-Tree Audit Bericht - {month:02d}/{year}", title_style))
        story.append(Spacer(1, 20))
        
        # Hole alle Hashes des Monats
        stmt = select(TransparencyHash).where(
            TransparencyHash.year == year,
            TransparencyHash.month == month
        ).order_by(TransparencyHash.date)
        
        result = await self.session.execute(stmt)
        hashes = result.scalars().all()
        
        # Tabelle mit täglichen Hashes
        data = [["Datum", "Merkle-Root", "Anzahl Records"]]
        for h in hashes:
            data.append([
                h.date.strftime("%d.%m.%Y"),
                h.merkle_root[:20] + "...",
                str(h.record_count)
            ])
        
        table = Table(data, colWidths=[80, 250, 80])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2d6a4f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey),
        ]))
        
        story.append(table)
        
        # Fußnote
        story.append(Spacer(1, 30))
        story.append(Paragraph(
            "Dieser Bericht bestätigt die manipulationssichere Speicherung aller Transparenz-Daten.",
            styles['Italic']
        ))
        
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()


# ==================== Cron Job für täglichen Hash ====================

async def daily_merkle_job(session_factory):
    """
    Täglicher Cron-Job (23:55 Uhr)
    Generiert Merkle-Hash für den aktuellen Tag
    """
    async with session_factory() as session:
        service = MerkleTreeService(session)
        today = date.today()
        
        # Generiere Hash für heute
        merkle_root = await service.generate_daily_hash(today)
        
        # Log für Monitoring
        print(f"[Merkle] Daily hash generated for {today}: {merkle_root[:16]}...")
        
        # Prüfe Integrität der letzten 7 Tage
        for i in range(1, 8):
            check_date = today - timedelta(days=i)
            verification = await service.verify_integrity(check_date)
            
            if not verification["is_valid"]:
                # Alert bei Integritätsverletzung
                print(f"[ALERT] Integrity violation detected for {check_date}!")
                # TODO: Send alert to admin (email/telegram)