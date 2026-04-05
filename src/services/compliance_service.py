# FILE: src/services/compliance_service.py
# MODULE: Compliance Service - Core Business Logic
# Implementiert 4-Augen-Prinzip, Geldwäscheprüfungen, Steuer-Compliance

import hashlib
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.compliance.base import (
    ApprovalStatus,
    ComplianceAlert,
    ComplianceResult,
    FourEyesApproval,
    FourEyesRequest,
    GoBDComplianceRecord,
    MoneyLaunderingCheck,
    MoneyLaunderingRisk,
    TaxComplianceCheck,
)
from src.core.entities.base import AuditLog, Donation
from src.core.events.event_bus import Event, EventBus

logger = logging.getLogger(__name__)


class ComplianceService:
    """
    Compliance Service mit:
    - 4-Augen-Prinzip für Transaktionen > 5.000€
    - Geldwäscheprüfung nach GwG
    - Steuer-Compliance (USt-IdNr., Zuwendungsbescheinigungen)
    - GoBD-revisionssichere Aufbewahrung
    - Automatische Alerts und Eskalationen
    """

    def __init__(self, session_factory, redis_client, event_bus: EventBus):
        self.session_factory = session_factory
        self.redis = redis_client
        self.event_bus = event_bus

        # Schwellwerte für Compliance (aus Config)
        self.FOUR_EYES_THRESHOLD = Decimal("5000.00")  # 5.000€
        self.ML_THRESHOLD = Decimal("10000.00")  # 10.000€ (Meldepflicht)
        self.HIGH_RISK_THRESHOLD = Decimal("50000.00")  # 50.000€

    # ==================== 4-Augen-Prinzip ====================

    async def request_four_eyes_approval(
        self,
        request: FourEyesRequest,
        initiator_id: UUID,
        ip_address: str
    ) -> FourEyesApproval:
        """
        Fordert 4-Augen-Freigabe für Transaktion an
        """
        async with self.session_factory() as session:
            # Prüfe ob bereits eine Freigabe existiert
            stmt = select(FourEyesApproval).where(
                FourEyesApproval.entity_type == request.entity_type,
                FourEyesApproval.entity_id == request.entity_id,
                FourEyesApproval.status == ApprovalStatus.PENDING
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                raise HTTPException(
                    status_code=409,
                    detail="Approval request already exists for this entity"
                )

            # Erstelle Freigabeanfrage
            approval = FourEyesApproval(
                entity_type=request.entity_type,
                entity_id=request.entity_id,
                amount=request.amount,
                reason=request.reason,
                initiator_id=initiator_id,
                approver_1_id=request.approver_1_id,
                approver_2_id=request.approver_2_id,
                expires_at=datetime.utcnow() + timedelta(hours=48),  # 48h Frist
                status=ApprovalStatus.PENDING
            )

            session.add(approval)
            await session.commit()
            await session.refresh(approval)

            # Audit Log
            audit = AuditLog(
                user_id=initiator_id,
                action="FOUR_EYES_REQUESTED",
                entity_type="four_eyes_approval",
                entity_id=approval.id,
                new_values={
                    "entity_type": request.entity_type,
                    "entity_id": str(request.entity_id),
                    "amount": str(request.amount),
                    "approver_1": str(request.approver_1_id)
                },
                ip_address=ip_address,
                retention_until=datetime.utcnow() + timedelta(days=3650)
            )
            session.add(audit)
            await session.commit()

            # Publish Event
            await self.event_bus.publish(Event(
                aggregate_id=approval.id,
                aggregate_type="FourEyesApproval",
                event_type="ApprovalRequested",
                data={
                    "entity_type": request.entity_type,
                    "entity_id": str(request.entity_id),
                    "amount": str(request.amount),
                    "expires_at": approval.expires_at.isoformat()
                },
                user_id=initiator_id,
                metadata={"ip": ip_address}
            ))

            # Erstelle Alert für Prüfer
            await self._create_approval_alert(approval)

            logger.info(f"Four-eyes approval requested for {request.entity_type}/{request.entity_id}")
            return approval

    async def approve_transaction(
        self,
        approval_id: UUID,
        approver_id: UUID,
        comment: str | None,
        ip_address: str
    ) -> FourEyesApproval:
        """
        Gibt eine Transaktion frei (2. oder 3. Prüfer)
        """
        async with self.session_factory() as session:
            stmt = select(FourEyesApproval).where(FourEyesApproval.id == approval_id)
            result = await session.execute(stmt)
            approval = result.scalar_one()

            if approval.status != ApprovalStatus.PENDING:
                raise HTTPException(
                    status_code=400,
                    detail=f"Approval is already {approval.status}"
                )

            if approval.expires_at < datetime.utcnow():
                approval.status = ApprovalStatus.EXPIRED
                await session.commit()
                raise HTTPException(status_code=400, detail="Approval request has expired")

            # Prüfe ob Approver berechtigt ist
            if approval.approver_1_id == approver_id:
                approval.approver_1_approved_at = datetime.utcnow()
                approval.approver_1_comment = comment
                approval.approver_1_ip = ip_address
            elif approval.approver_2_id == approver_id:
                approval.approver_2_approved_at = datetime.utcnow()
                approval.approver_2_comment = comment
                approval.approver_2_ip = ip_address
            else:
                raise HTTPException(status_code=403, detail="Not authorized to approve this transaction")

            # Prüfe ob alle Freigaben vorliegen
            if approval.is_fully_approved:
                approval.status = ApprovalStatus.APPROVED

                # Führe die ursprüngliche Transaktion aus
                await self._execute_approved_transaction(approval, session)

            await session.commit()
            await session.refresh(approval)

            # Audit Log
            audit = AuditLog(
                user_id=approver_id,
                action="FOUR_EYES_APPROVED",
                entity_type="four_eyes_approval",
                entity_id=approval.id,
                new_values={"status": approval.status.value},
                ip_address=ip_address,
                retention_until=datetime.utcnow() + timedelta(days=3650)
            )
            session.add(audit)
            await session.commit()

            # Publish Event
            await self.event_bus.publish(Event(
                aggregate_id=approval.id,
                aggregate_type="FourEyesApproval",
                event_type="ApprovalGranted",
                data={
                    "approver_id": str(approver_id),
                    "fully_approved": approval.is_fully_approved,
                    "status": approval.status.value
                },
                user_id=approver_id,
                metadata={"ip": ip_address}
            ))

            logger.info(f"Transaction {approval.entity_id} approved by {approver_id}")
            return approval

    async def reject_transaction(
        self,
        approval_id: UUID,
        approver_id: UUID,
        reason: str,
        ip_address: str
    ) -> FourEyesApproval:
        """
        Lehnt eine Transaktion ab
        """
        async with self.session_factory() as session:
            stmt = select(FourEyesApproval).where(FourEyesApproval.id == approval_id)
            result = await session.execute(stmt)
            approval = result.scalar_one()

            approval.status = ApprovalStatus.REJECTED
            approval.rejection_reason = reason

            await session.commit()
            await session.refresh(approval)

            # Audit Log
            audit = AuditLog(
                user_id=approver_id,
                action="FOUR_EYES_REJECTED",
                entity_type="four_eyes_approval",
                entity_id=approval.id,
                new_values={"status": approval.status.value, "reason": reason},
                ip_address=ip_address,
                retention_until=datetime.utcnow() + timedelta(days=3650)
            )
            session.add(audit)
            await session.commit()

            # Publish Event
            await self.event_bus.publish(Event(
                aggregate_id=approval.id,
                aggregate_type="FourEyesApproval",
                event_type="ApprovalRejected",
                data={"reason": reason},
                user_id=approver_id,
                metadata={"ip": ip_address}
            ))

            logger.warning(f"Transaction {approval.entity_id} rejected by {approver_id}: {reason}")
            return approval

    async def _execute_approved_transaction(self, approval: FourEyesApproval, session: AsyncSession):
        """Führt die freigegebene Transaktion aus"""
        # Hier wird die ursprüngliche Transaktion ausgeführt
        # z.B. Spende buchen, Ausgabe freigeben, etc.

        if approval.entity_type == "donation":
            stmt = select(Donation).where(Donation.id == approval.entity_id)
            result = await session.execute(stmt)
            donation = result.scalar_one()

            # Markiere als compliance-geprüft
            donation.compliance_status = "approved"
            donation.four_eyes_approved_by = approval.approver_1_id
            donation.four_eyes_approved_at = datetime.utcnow()
            donation.current_hash = donation.compute_hash()

            session.add(donation)
            await session.commit()

            logger.info(f"Donation {donation.id} executed after four-eyes approval")

    # ==================== Geldwäscheprüfung ====================

    async def check_money_laundering(
        self,
        entity_type: str,
        entity_id: UUID,
        amount: Decimal,
        donor_name: str | None,
        donor_email: str | None,
        donor_country: str | None,
        payment_method: str | None,
        ip_address: str | None
    ) -> MoneyLaunderingCheck:
        """
        Führt Geldwäscheprüfung nach GwG durch
        """
        async with self.session_factory() as session:
            # Erstelle Prüfrecord
            ml_check = MoneyLaunderingCheck(
                entity_type=entity_type,
                entity_id=entity_id,
                amount=amount,
                donor_name=donor_name,
                donor_email=donor_email,
                donor_country=donor_country,
                payment_method=payment_method,
                ip_address=ip_address
            )

            # Führe verschiedene Prüfungen durch
            flags = []
            checks_performed = []

            # 1. Betragsprüfung
            if amount >= self.ML_THRESHOLD:
                flags.append({
                    "type": "high_amount",
                    "threshold": float(self.ML_THRESHOLD),
                    "actual": float(amount),
                    "severity": "high"
                })
                checks_performed.append("amount_threshold_check")

            # 2. Hochrisikoländer
            high_risk_countries = ['RU', 'CN', 'IR', 'KP', 'SY', 'VE', 'UA']
            if donor_country in high_risk_countries:
                flags.append({
                    "type": "high_risk_country",
                    "country": donor_country,
                    "severity": "critical"
                })
                checks_performed.append("country_risk_check")

            # 3. Anonyme Zahlungsmethoden
            anonymous_methods = ['crypto', 'prepaid_card', 'cash']
            if payment_method and payment_method in anonymous_methods:
                flags.append({
                    "type": "anonymous_payment",
                    "method": payment_method,
                    "severity": "high"
                })
                checks_performed.append("payment_method_check")

            # 4. Strukturierungserkennung (Smurfing)
            # Prüfe ob mehrere kleine Transaktionen kurz hintereinander
            smurfing_check = await self._check_smurfing(session, donor_email, amount)
            if smurfing_check:
                flags.append({
                    "type": "smurfing_suspected",
                    "details": smurfing_check,
                    "severity": "critical"
                })
                checks_performed.append("smurfing_check")

            # 5. PEP-Check (Politically Exposed Persons)
            # In Production: API-Aufruf zu externem Dienst
            pep_result = await self._check_pep(donor_name, donor_email)
            if pep_result:
                flags.append({
                    "type": "politically_exposed_person",
                    "details": pep_result,
                    "severity": "critical"
                })
                ml_check.pep_check_passed = False
                checks_performed.append("pep_check")

            # 6. Sanktionslisten-Check
            sanctions_result = await self._check_sanctions_list(donor_name, donor_email)
            if sanctions_result:
                flags.append({
                    "type": "sanctions_list_hit",
                    "details": sanctions_result,
                    "severity": "critical"
                })
                ml_check.sanctions_list_hit = True
                ml_check.sanctions_list_name = sanctions_result.get("list_name")
                checks_performed.append("sanctions_check")

            ml_check.flags = flags
            ml_check.checks_performed = checks_performed

            # Berechne Risikoscore
            ml_check.calculate_risk_score()

            # Entscheide über Compliance-Ergebnis
            if ml_check.risk_level in [MoneyLaunderingRisk.CRITICAL, MoneyLaunderingRisk.HIGH]:
                ml_check.compliance_result = ComplianceResult.REQUIRES_REVIEW

                # Bei kritischen Fällen: Alert erstellen
                if ml_check.risk_level == MoneyLaunderingRisk.CRITICAL:
                    ml_check.compliance_result = ComplianceResult.BLOCKED
                    await self._create_money_laundering_alert(ml_check)

                    # Bei > 50.000€: Meldepflicht prüfen
                    if amount >= self.HIGH_RISK_THRESHOLD:
                        await self._report_to_fiu(ml_check, session)
                        ml_check.reported_to_fiu = True
                        ml_check.reported_at = datetime.utcnow()
            else:
                ml_check.compliance_result = ComplianceResult.PASSED

            session.add(ml_check)
            await session.commit()
            await session.refresh(ml_check)

            # Audit Log
            audit = AuditLog(
                user_id=None,  # System-Prüfung
                action="MONEY_LAUNDERING_CHECK",
                entity_type=entity_type,
                entity_id=entity_id,
                new_values={
                    "risk_score": ml_check.risk_score,
                    "risk_level": ml_check.risk_level.value,
                    "flags_count": len(flags),
                    "result": ml_check.compliance_result.value
                },
                ip_address="system",
                retention_until=datetime.utcnow() + timedelta(days=3650)
            )
            session.add(audit)
            await session.commit()

            logger.info(f"Money laundering check for {entity_type}/{entity_id}: risk={ml_check.risk_level.value}, score={ml_check.risk_score}")
            return ml_check

    async def _check_smurfing(self, session: AsyncSession, donor_email: str, current_amount: Decimal) -> dict | None:
        """Prüft auf Strukturierung (Smurfing) - viele kleine Transaktionen"""
        from datetime import timedelta

        # Suche Transaktionen der letzten 24 Stunden
        cutoff = datetime.utcnow() - timedelta(hours=24)

        stmt = select(MoneyLaunderingCheck).where(
            MoneyLaunderingCheck.donor_email == donor_email,
            MoneyLaunderingCheck.created_at >= cutoff
        )
        result = await session.execute(stmt)
        recent_checks = result.scalars().all()

        total_amount = sum(c.amount for c in recent_checks) + current_amount
        transaction_count = len(recent_checks) + 1

        # Verdacht bei > 10 Transaktionen oder > 10.000€ in 24h
        if transaction_count > 10 or total_amount > 10000:
            return {
                "transaction_count": transaction_count,
                "total_amount": float(total_amount),
                "timeframe_hours": 24,
                "reason": "unusual_transaction_pattern"
            }
        return None

    async def _check_pep(self, name: str | None, email: str | None) -> dict | None:
        """Prüft auf Politically Exposed Persons (externer Dienst)"""
        # In Production: Integration mit Compliance-API (z.B. ComplyAdvantage, Refinitiv)
        # Mock für Demo
        return None

    async def _check_sanctions_list(self, name: str | None, email: str | None) -> dict | None:
        """Prüft gegen internationale Sanktionslisten"""
        # In Production: OFAC, EU Sanctions, UN Sanctions
        # Mock für Demo
        return None

    async def _report_to_fiu(self, ml_check: MoneyLaunderingCheck, session: AsyncSession):
        """Meldet Verdachtsfall an Financial Intelligence Unit (FIU)"""
        # In Production: Automatischer Report im XML-Format an FIU
        report_data = {
            "case_id": str(ml_check.id),
            "transaction_date": ml_check.created_at.isoformat(),
            "amount": float(ml_check.amount),
            "currency": ml_check.currency,
            "donor_name": ml_check.donor_name,
            "donor_country": ml_check.donor_country,
            "risk_factors": ml_check.flags,
            "reporting_entity": "TrueAngels e.V.",
            "contact": "compliance@trueangels.de"
        }

        ml_check.report_data = report_data
        ml_check.report_reference = f"FIU-{datetime.utcnow().strftime('%Y%m%d')}-{ml_check.id.hex[:8]}"

        logger.warning(f"Suspicious transaction reported to FIU: {ml_check.report_reference}")

        # Publish Event für Compliance Officer
        await self.event_bus.publish(Event(
            aggregate_id=ml_check.id,
            aggregate_type="MoneyLaunderingCheck",
            event_type="ReportedToFIU",
            data=report_data,
            user_id=None,
            metadata={}
        ))

    # ==================== Steuer-Compliance ====================

    async def validate_vat_id(self, vat_id: str, country_code: str) -> dict[str, Any]:
        """
        Validiert Umsatzsteuer-ID über VIES API (EU-weit)
        """
        import httpx

        # VIES SOAP API (vereinfacht)
        vies_url = f"https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat/{country_code}/{vat_id[2:]}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(vies_url)

                if response.status_code == 200:
                    data = response.json()
                    return {
                        "valid": data.get("valid", False),
                        "name": data.get("name"),
                        "address": data.get("address"),
                        "request_date": datetime.utcnow().isoformat()
                    }
                else:
                    return {"valid": False, "error": "VIES service unavailable"}

        except Exception as e:
            logger.error(f"VAT validation failed: {e}")
            return {"valid": False, "error": str(e)}

    async def generate_tax_receipt(self, donation_id: UUID) -> dict[str, Any]:
        """
        Generiert steuerliche Zuwendungsbescheinigung
        """
        async with self.session_factory() as session:
            stmt = select(Donation).where(Donation.id == donation_id)
            result = await session.execute(stmt)
            donation = result.scalar_one()

            # Prüfe ob bereits generiert
            if donation.donation_receipt_generated:
                raise HTTPException(status_code=400, detail="Receipt already generated")

            # Erstelle Tax Compliance Record
            tax_check = TaxComplianceCheck(
                entity_type="donation",
                entity_id=donation.id,
                tax_deductible=True,
                receipt_generated=True,
                receipt_number=f"TA-{donation.created_at.year}-{donation.id.hex[:8].upper()}",
                receipt_generated_at=datetime.utcnow()
            )

            session.add(tax_check)

            # Update Donation
            donation.donation_receipt_generated = True
            donation.current_hash = donation.compute_hash()

            await session.commit()

            # Trigger PDF Generation
            from src.services.pdf_generator import DonationReceiptGenerator
            receipt_gen = DonationReceiptGenerator(session)
            pdf_bytes = await receipt_gen.generate_donation_receipt(donation_id)

            # In Production: Upload zu S3/Wasabi
            # s3_url = await upload_to_s3(pdf_bytes, f"receipts/{tax_check.receipt_number}.pdf")

            return {
                "receipt_number": tax_check.receipt_number,
                "generated_at": tax_check.receipt_generated_at.isoformat(),
                "tax_deductible": True,
                "amount": float(donation.amount)
            }

    # ==================== GoBD-Compliance ====================

    async def archive_for_gobd(
        self,
        record_type: str,
        record_id: UUID,
        content: bytes,
        filename: str,
        created_by: UUID
    ) -> GoBDComplianceRecord:
        """
        Archiviert Dokumente GoBD-konform (revisionssicher, manipulationsgeschützt)
        """
        async with self.session_factory() as session:
            # Berechne Hash für Manipulationsschutz
            file_hash = hashlib.sha256(content).hexdigest()

            # Bestimme Aufbewahrungsdauer (10 Jahre für Finanzdokumente)
            retention_years = 10
            if record_type in ["audit_log", "system_log"]:
                retention_years = 3  # Zugriffslogs nur 3 Jahre

            # Speichere in Wasabi S3 (verschlüsselt)
            # s3_key = f"gobd/{record_type}/{record_id}/{filename}"
            # await upload_to_s3_encrypted(content, s3_key)

            gobd_record = GoBDComplianceRecord(
                record_type=record_type,
                record_id=record_id,
                record_hash=file_hash,
                retention_period_years=retention_years,
                retention_until=datetime.utcnow() + timedelta(days=365 * retention_years),
                original_filename=filename,
                file_size_bytes=len(content),
                mime_type="application/pdf",
                encrypted=True,
                deletion_protected_until=datetime.utcnow() + timedelta(days=365 * retention_years),
                created_by=created_by
            )

            session.add(gobd_record)
            await session.commit()
            await session.refresh(gobd_record)

            logger.info(f"GoBD archive created: {record_type}/{record_id} - {file_hash[:16]}...")
            return gobd_record

    # ==================== Alert Management ====================

    async def _create_approval_alert(self, approval: FourEyesApproval):
        """Erstellt Alert für ausstehende Freigabe"""
        alert = ComplianceAlert(
            alert_type="four_eyes_pending",
            title="4-Augen-Freigabe erforderlich",
            description=f"Transaktion über {approval.amount:,.2f}€ wartet auf Freigabe durch {approval.approver_1_id}",
            priority="high",
            severity_score=70,
            entity_type=approval.entity_type,
            entity_id=approval.entity_id,
            assigned_to=approval.approver_1_id,
            response_deadline=approval.expires_at,
            created_by=approval.initiator_id
        )

        async with self.session_factory() as session:
            session.add(alert)
            await session.commit()

    async def _create_money_laundering_alert(self, ml_check: MoneyLaunderingCheck):
        """Erstellt Alert für Geldwäscheverdacht"""
        alert = ComplianceAlert(
            alert_type="money_laundering_suspected",
            title=f"Geldwäscheverdacht - {ml_check.risk_level.value}",
            description=f"Transaktion über {ml_check.amount:,.2f}€ mit Risikoscore {ml_check.risk_score}",
            priority="critical",
            severity_score=ml_check.risk_score,
            entity_type=ml_check.entity_type,
            entity_id=ml_check.entity_id,
            assigned_to=None,  # Compliance Officer
            response_deadline=datetime.utcnow() + timedelta(hours=24),
            created_by=None
        )

        async with self.session_factory() as session:
            session.add(alert)
            await session.commit()

            # Publish Event für Compliance Officer
            await self.event_bus.publish(Event(
                aggregate_id=alert.id,
                aggregate_type="ComplianceAlert",
                event_type="MoneyLaunderingAlert",
                data={
                    "risk_level": ml_check.risk_level.value,
                    "amount": float(ml_check.amount),
                    "flags": ml_check.flags
                },
                user_id=None,
                metadata={"priority": "critical"}
            ))

    async def get_pending_approvals(self, user_id: UUID) -> list[FourEyesApproval]:
        """Holt ausstehende Freigaben für einen Benutzer"""
        async with self.session_factory() as session:
            stmt = select(FourEyesApproval).where(
                or_(
                    FourEyesApproval.approver_1_id == user_id,
                    FourEyesApproval.approver_2_id == user_id
                ),
                FourEyesApproval.status == ApprovalStatus.PENDING,
                FourEyesApproval.expires_at > datetime.utcnow()
            ).order_by(FourEyesApproval.expires_at)

            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_compliance_dashboard(self) -> dict[str, Any]:
        """Liefert Compliance Dashboard Daten"""
        async with self.session_factory() as session:
            # Statistik: Ausstehende Freigaben
            pending_count = await session.execute(
                select(func.count()).select_from(FourEyesApproval).where(
                    FourEyesApproval.status == ApprovalStatus.PENDING
                )
            )

            # Statistik: Geldwäsche-Verdachtsfälle
            ml_count = await session.execute(
                select(func.count()).select_from(MoneyLaunderingCheck).where(
                    MoneyLaunderingCheck.compliance_result == ComplianceResult.REQUIRES_REVIEW
                )
            )

            # Statistik: Offene Alerts
            alert_count = await session.execute(
                select(func.count()).select_from(ComplianceAlert).where(
                    ComplianceAlert.status == "open"
                )
            )

            # Statistik: GoBD-konforme Archive
            archive_count = await session.execute(
                select(func.count()).select_from(GoBDComplianceRecord)
            )

            return {
                "pending_four_eyes": pending_count.scalar() or 0,
                "money_laundering_cases": ml_count.scalar() or 0,
                "open_alerts": alert_count.scalar() or 0,
                "gobd_archived_documents": archive_count.scalar() or 0,
                "compliance_score": self._calculate_compliance_score()
            }

    def _calculate_compliance_score(self) -> int:
        """Berechnet Gesamt-Compliance-Score (0-100)"""
        # In Production: Basierend auf verschiedenen Metriken
        return 95
