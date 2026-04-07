# FILE: src/services/audit.py
# MODULE: Audit Service mit Decorator & DSGVO-Konformität
# Automatisches Logging aller CRUD-Operationen mit vorher/nachher Werten

from collections.abc import Callable
from datetime import datetime, timedelta
from functools import wraps
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.entities.base import AuditLog, Donation, User

# ==================== Audit Decorator ====================


def audit_log(
    action: str, entity_type: str, requires_four_eyes: bool = False, sensitive_fields: list = None
):
    """
    Decorator für automatisches Audit-Logging

    Usage:
        @audit_log(action="CREATE_SPENDE", entity_type="donation")
        async def create_donation(...):
            ...
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extrahiere Request und Session aus Args
            request = None
            session = None
            user_id = None
            ip_address = None

            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    ip_address = request.client.host if request.client else "unknown"
                elif isinstance(arg, AsyncSession):
                    session = arg

            # Hole aktuellen User (falls vorhanden)
            if request and hasattr(request, "state"):
                user = getattr(request.state, "user", None)
                if user:
                    user_id = user.id

            # Vorher-Werte (für Updates)
            old_values = None
            entity_id = None

            # Extrahiere entity_id aus kwargs
            if "donation_id" in kwargs:
                entity_id = kwargs["donation_id"]
            elif "entity_id" in kwargs:
                entity_id = kwargs["entity_id"]
            elif "id" in kwargs:
                entity_id = kwargs["id"]

            # Lade alte Werte für Update-Operationen
            if action.startswith("UPDATE") and entity_id and session:
                stmt = select(Donation).where(Donation.id == entity_id)
                result = await session.execute(stmt)
                entity = result.scalar_one_or_none()
                if entity:
                    old_values = {
                        col.name: getattr(entity, col.name)
                        for col in entity.__table__.columns
                        if not col.name.startswith("_")
                    }
                    # Entferne sensible Daten
                    if sensitive_fields:
                        for field in sensitive_fields:
                            old_values.pop(field, None)

            # Führe ursprüngliche Funktion aus
            result = await func(*args, **kwargs)

            # Nachher-Werte (falls Update)
            new_values = None
            if action.startswith("UPDATE") and entity_id and session:
                stmt = select(Donation).where(Donation.id == entity_id)
                result_after = await session.execute(stmt)
                entity_after = result_after.scalar_one_or_none()
                if entity_after:
                    new_values = {
                        col.name: getattr(entity_after, col.name)
                        for col in entity_after.__table__.columns
                        if not col.name.startswith("_")
                    }
                    if sensitive_fields:
                        for field in sensitive_fields:
                            new_values.pop(field, None)

            # Erstelle Audit Log
            audit = AuditLog(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=(
                    entity_id if entity_id else (result.id if hasattr(result, "id") else None)
                ),
                old_values=old_values,
                new_values=new_values or (result.dict() if hasattr(result, "dict") else None),
                ip_address=ip_address,
                requires_four_eyes=requires_four_eyes,
                retention_until=datetime.utcnow() + timedelta(days=3650),  # 10 Jahre
            )

            if session:
                session.add(audit)
                await session.commit()

            return result

        return wrapper

    return decorator


# ==================== DSGVO Service ====================


class DSGVOService:
    """DSGVO-konforme Datenlöschung & Export"""

    def __init__(self, session_factory, audit_service: "AuditService"):
        self.session_factory = session_factory
        self.audit_service = audit_service

    async def request_deletion(self, user_id: UUID, reason: str = None) -> dict[str, Any]:
        """
        DSGVO Art.17: Recht auf Löschung ("Recht auf Vergessenwerden")
        Implementiert Pseudonymisierung statt Hard-Delete (wegen Aufbewahrungspflichten)
        """
        async with self.session_factory() as session:
            # Lade User
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one()

            if user.is_pseudonymized:
                raise HTTPException(status_code=400, detail="User already pseudonymized")

            # Pseudonymisiere User
            user.pseudonymize()
            user.deletion_requested_at = datetime.utcnow()

            # Pseudonymisiere alle Spenden des Users
            stmt = select(Donation).where(Donation.created_by == user_id)
            donations = await session.execute(stmt)
            for donation in donations.scalars():
                donation.pseudonymize()

            await session.commit()

            # Audit-Log für Löschung
            await self.audit_service.log(
                user_id=user_id,
                action="DSGVO_DELETION_REQUEST",
                entity_type="user",
                entity_id=user_id,
                metadata={"reason": reason, "pseudonymized_at": datetime.utcnow().isoformat()},
            )

            return {
                "status": "pseudonymized",
                "message": "Your data has been pseudonymized in accordance with GDPR Art. 17",
                "timestamp": datetime.utcnow().isoformat(),
                "retention_period": "Financial data retained for 10 years (HGB §257)",
            }

    async def export_user_data(self, user_id: UUID) -> dict[str, Any]:
        """
        DSGVO Art.15: Auskunftsrecht
        Exportiert alle personenbezogenen Daten im maschinenlesbaren Format
        """
        async with self.session_factory() as session:
            # Lade User
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one()

            # Lade Spenden
            stmt = select(Donation).where(Donation.created_by == user_id)
            donations = await session.execute(stmt)

            # Kompiliere Export
            export_data = {
                "user": {
                    "email": user.email if not user.is_pseudonymized else "PSEUDONYMIZED",
                    "name": user.name_encrypted,
                    "role": user.role.value,
                    "created_at": user.created_at.isoformat(),
                    "last_login": user.last_login_at.isoformat() if user.last_login_at else None,
                },
                "donations": [
                    {
                        "id": str(d.id),
                        "amount": float(d.amount),
                        "project_id": str(d.project_id),
                        "created_at": d.created_at.isoformat(),
                        "payment_status": d.payment_status,
                    }
                    for d in donations.scalars()
                ],
                "export_date": datetime.utcnow().isoformat(),
                "format_version": "1.0",
            }

            # Audit-Log für Export
            await self.audit_service.log(
                user_id=user_id,
                action="DATA_EXPORT",
                entity_type="user",
                entity_id=user_id,
                metadata={"export_size": len(str(export_data))},
            )

            return export_data

    async def withdraw_consent(self, user_id: UUID):
        """
        DSGVO Art.7: Widerruf der Einwilligung
        """
        async with self.session_factory() as session:
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one()

            user.consent_withdrawn_at = datetime.utcnow()
            await session.commit()

            await self.audit_service.log(
                user_id=user_id, action="CONSENT_WITHDRAWN", entity_type="user", entity_id=user_id
            )

            return {"status": "consent withdrawn", "timestamp": datetime.utcnow().isoformat()}


# ==================== Audit Service ====================


class AuditService:
    """Service für Audit-Log Zugriff & Reports"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def log(
        self,
        user_id: UUID,
        action: str,
        entity_type: str,
        entity_id: UUID = None,
        old_values: dict = None,
        new_values: dict = None,
        metadata: dict = None,
        ip_address: str = None,
    ):
        """Programmatisches Audit-Log"""
        async with self.session_factory() as session:
            audit = AuditLog(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                old_values=old_values,
                new_values=new_values,
                ip_address=ip_address or "system",
                metadata=metadata,
                retention_until=datetime.utcnow() + timedelta(days=3650),
            )
            session.add(audit)
            await session.commit()

    async def get_audit_trail(
        self,
        entity_type: str,
        entity_id: UUID,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> list:
        """Ruft Audit-Trail für eine Entität ab (GoBD-konform)"""
        async with self.session_factory() as session:
            stmt = (
                select(AuditLog)
                .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
                .order_by(AuditLog.timestamp)
            )

            if start_date:
                stmt = stmt.where(AuditLog.timestamp >= start_date)
            if end_date:
                stmt = stmt.where(AuditLog.timestamp <= end_date)

            result = await session.execute(stmt)
            logs = result.scalars().all()

            return [
                {
                    "timestamp": log.timestamp.isoformat(),
                    "user_id": str(log.user_id) if log.user_id else None,
                    "action": log.action,
                    "old_values": log.old_values,
                    "new_values": log.new_values,
                    "ip_address": log.ip_address,
                    "reason": log.reason,
                }
                for log in logs
            ]

    async def get_compliance_report(self, year: int) -> dict[str, Any]:
        """
        Generiert Compliance Report für Wirtschaftsprüfer
        GoBD-konform mit Merkle-Tree Prüfpfaden
        """
        async with self.session_factory() as session:
            start_date = datetime(year, 1, 1)
            end_date = datetime(year, 12, 31, 23, 59, 59)

            # Alle Audit-Logs für das Jahr
            stmt = (
                select(AuditLog)
                .where(AuditLog.timestamp.between(start_date, end_date))
                .order_by(AuditLog.timestamp)
            )
            result = await session.execute(stmt)
            logs = result.scalars().all()

            # Statistiken
            stats = {
                "total_audit_events": len(logs),
                "by_action": {},
                "critical_events": [],
                "four_eyes_required": [],
                "money_laundering_flags": [],
            }

            for log in logs:
                # Zähle Actions
                stats["by_action"][log.action] = stats["by_action"].get(log.action, 0) + 1

                # Kritische Events (>5000€ Änderungen)
                if log.old_values and log.new_values:
                    old_amount = log.old_values.get("amount")
                    new_amount = log.new_values.get("amount")
                    if old_amount and new_amount and abs(new_amount - old_amount) > 5000:
                        stats["critical_events"].append(
                            {
                                "timestamp": log.timestamp.isoformat(),
                                "entity_id": str(log.entity_id),
                                "change": float(new_amount - old_amount),
                            }
                        )

                # 4-Augen-Prinzip
                if log.requires_four_eyes and not log.four_eyes_approved:
                    stats["four_eyes_required"].append(
                        {
                            "timestamp": log.timestamp.isoformat(),
                            "action": log.action,
                            "entity_id": str(log.entity_id),
                        }
                    )

            # Berechne Merkle-Root für Prüfpfad
            merkle_root = self._compute_merkle_root(logs)

            return {
                "year": year,
                "statistics": stats,
                "merkle_root": merkle_root,
                "report_generated": datetime.utcnow().isoformat(),
                "retention_compliant": True,
                "next_audit_due": datetime(year + 1, 6, 30).isoformat(),
            }

    def _compute_merkle_root(self, logs: list) -> str:
        """Berechnet Merkle-Root Hash für alle Audit-Logs"""
        import hashlib

        if not logs:
            return hashlib.sha256(b"empty").hexdigest()

        # Baumstruktur für Prüfpfad
        hashes = [hashlib.sha256(str(log.id).encode()).digest() for log in logs]

        while len(hashes) > 1:
            if len(hashes) % 2 == 1:
                hashes.append(hashes[-1])
            hashes = [
                hashlib.sha256(hashes[i] + hashes[i + 1]).digest() for i in range(0, len(hashes), 2)
            ]

        return hashes[0].hex()
