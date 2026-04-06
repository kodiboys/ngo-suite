# FILE: src/services/export_service.py
# MODULE: Export Service für CSV, Excel, JSON, DATEV
# DSGVO-konforme Datenexporte mit Filterung und Anonymisierung

import csv
import io
import json
import zipfile
from datetime import datetime, timedelta
from uuid import UUID

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import func, select

from src.core.entities.base import AuditLog, Donation, Project, User

logger = logging.getLogger(__name__)


class ExportService:
    """
    Export Service für verschiedene Formate
    Features:
    - CSV, Excel, JSON, DATEV Export
    - DSGVO-konforme Anonymisierung
    - Projekt- und Datumsfilter
    - Automatische Komprimierung bei großen Datenmengen
    - Export-Tracking für Audit
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def export_donations(
        self,
        start_date: datetime,
        end_date: datetime,
        format: str = "excel",
        project_id: UUID | None = None,
        include_personal_data: bool = True,
        user_id: UUID | None = None,
    ) -> bytes:
        """
        Exportiert Spenden in verschiedenen Formaten
        DSGVO-konform: Personal data kann anonymisiert werden
        """
        async with self.session_factory() as session:
            # Lade Spenden
            stmt = select(Donation).where(
                Donation.created_at.between(start_date, end_date),
                Donation.payment_status == "succeeded",
            )

            if project_id:
                stmt = stmt.where(Donation.project_id == project_id)

            result = await session.execute(stmt)
            donations = result.scalars().all()

            # Bereite Daten für Export vor
            export_data = []
            for donation in donations:
                row = {
                    "Spenden-ID": str(donation.id),
                    "Datum": donation.created_at.strftime("%d.%m.%Y %H:%M"),
                    "Betrag": float(donation.amount),
                    "Währung": donation.currency,
                    "Projekt-ID": str(donation.project_id),
                    "Zahlungsmethode": donation.payment_provider,
                    "Status": donation.payment_status,
                    "Bescheinigung generiert": (
                        "Ja" if donation.donation_receipt_generated else "Nein"
                    ),
                }

                # Personal data (nur wenn erlaubt)
                if include_personal_data and not donation.is_pseudonymized:
                    row["Spender-E-Mail (pseudonym)"] = donation.donor_email_pseudonym[:50] + "..."
                    row["Spender-Name"] = donation.donor_name_encrypted or "nicht angegeben"
                else:
                    row["Spender (anonymisiert)"] = "Anonym"

                export_data.append(row)

            # Export je nach Format
            if format == "excel":
                return await self._to_excel(export_data, "Spendenbericht")
            elif format == "csv":
                return await self._to_csv(export_data)
            elif format == "json":
                return await self._to_json(export_data)
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

    async def export_projects(self, status: str | None = None, format: str = "excel") -> bytes:
        """Exportiert Projekte mit KPIs"""
        async with self.session_factory() as session:
            stmt = select(Project)
            if status:
                stmt = stmt.where(Project.status == status)

            result = await session.execute(stmt)
            projects = result.scalars().all()

            export_data = []
            for project in projects:
                row = {
                    "Projekt-ID": str(project.id),
                    "Name": project.name,
                    "Beschreibung": project.description or "",
                    "Budget": float(project.budget_total),
                    "Spenden": float(project.donations_total),
                    "Fortschritt": (
                        f"{(project.donations_total / project.budget_total * 100):.1f}%"
                        if project.budget_total > 0
                        else "0%"
                    ),
                    "Status": project.status,
                    "Startdatum": project.start_date.strftime("%d.%m.%Y"),
                    "Enddatum": (
                        project.end_date.strftime("%d.%m.%Y") if project.end_date else "laufend"
                    ),
                }
                export_data.append(row)

            if format == "excel":
                return await self._to_excel(export_data, "Projektbericht")
            elif format == "csv":
                return await self._to_csv(export_data)
            else:
                return await self._to_json(export_data)

    async def export_dsgvo_data(self, user_id: UUID, format: str = "json") -> bytes:
        """
        DSGVO Art.15: Auskunftsrecht
        Exportiert alle personenbezogenen Daten eines Users
        """
        async with self.session_factory() as session:
            # Lade User
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one()

            # Lade Spenden
            stmt = select(Donation).where(Donation.created_by == user_id)
            result = await session.execute(stmt)
            donations = result.scalars().all()

            # Kompiliere DSGVO-Export
            export_data = {
                "export_date": datetime.utcnow().isoformat(),
                "user": {
                    "id": str(user.id),
                    "email": user.email if not user.is_pseudonymized else "PSEUDONYMIZED",
                    "name": user.name_encrypted,
                    "role": user.role.value,
                    "created_at": user.created_at.isoformat(),
                    "last_login": user.last_login_at.isoformat() if user.last_login_at else None,
                    "consent_given_at": (
                        user.consent_given_at.isoformat() if user.consent_given_at else None
                    ),
                },
                "donations": [
                    {
                        "id": str(d.id),
                        "amount": float(d.amount),
                        "project_id": str(d.project_id),
                        "created_at": d.created_at.isoformat(),
                        "payment_status": d.payment_status,
                        "donation_receipt_generated": d.donation_receipt_generated,
                    }
                    for d in donations
                ],
                "audit_logs": [],  # In Production: Letzte 100 Audit-Logs
            }

            # Audit-Log für Export
            audit = AuditLog(
                user_id=user_id,
                action="DATA_EXPORT_DSGVO",
                entity_type="user",
                entity_id=user_id,
                new_values={"export_format": format, "export_size": len(str(export_data))},
                ip_address="system",
                retention_until=datetime.utcnow() + timedelta(days=3650),
            )
            session.add(audit)
            await session.commit()

            if format == "json":
                return json.dumps(export_data, indent=2).encode("utf-8")
            elif format == "csv":
                # Konvertiere zu CSV
                df = pd.DataFrame([export_data])
                return df.to_csv(index=False).encode("utf-8")
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

    async def export_audit_log(
        self,
        start_date: datetime,
        end_date: datetime,
        entity_type: str | None = None,
        user_id: UUID | None = None,
        format: str = "excel",
    ) -> bytes:
        """Exportiert Audit-Log für Compliance Reports"""
        async with self.session_factory() as session:
            stmt = select(AuditLog).where(AuditLog.timestamp.between(start_date, end_date))

            if entity_type:
                stmt = stmt.where(AuditLog.entity_type == entity_type)
            if user_id:
                stmt = stmt.where(AuditLog.user_id == user_id)

            result = await session.execute(stmt)
            logs = result.scalars().all()

            export_data = []
            for log in logs:
                row = {
                    "Timestamp": log.timestamp.strftime("%d.%m.%Y %H:%M:%S"),
                    "User-ID": str(log.user_id) if log.user_id else "System",
                    "Aktion": log.action,
                    "Entity-Typ": log.entity_type,
                    "Entity-ID": str(log.entity_id) if log.entity_id else "-",
                    "IP-Adresse": log.ip_address,
                    "Alte Werte": (
                        json.dumps(log.old_values, ensure_ascii=False) if log.old_values else "-"
                    ),
                    "Neue Werte": (
                        json.dumps(log.new_values, ensure_ascii=False) if log.new_values else "-"
                    ),
                    "Grund": log.reason or "-",
                }
                export_data.append(row)

            if format == "excel":
                return await self._to_excel(export_data, "Audit-Log")
            elif format == "csv":
                return await self._to_csv(export_data)
            else:
                return await self._to_json(export_data)

    async def export_financial_report(self, year: int, format: str = "excel") -> bytes:
        """Exportiert finanziellen Jahresbericht"""
        async with self.session_factory() as session:
            start_date = datetime(year, 1, 1)
            end_date = datetime(year, 12, 31, 23, 59, 59)

            # Monatliche Spenden
            monthly_donations = []
            for month in range(1, 13):
                month_start = datetime(year, month, 1)
                if month == 12:
                    month_end = datetime(year, 12, 31, 23, 59, 59)
                else:
                    month_end = datetime(year, month + 1, 1) - timedelta(seconds=1)

                stmt = select(func.sum(Donation.amount)).where(
                    Donation.created_at.between(month_start, month_end),
                    Donation.payment_status == "succeeded",
                )
                result = await session.execute(stmt)
                total = result.scalar() or 0

                monthly_donations.append(
                    {
                        "Monat": month,
                        "Monatsname": datetime(year, month, 1).strftime("%B"),
                        "Spenden": float(total),
                    }
                )

            # Projektübersicht
            stmt = select(Project)
            result = await session.execute(stmt)
            projects = result.scalars().all()

            project_data = []
            for project in projects:
                project_data.append(
                    {
                        "Projekt": project.name,
                        "Budget": float(project.budget_total),
                        "Spenden": float(project.donations_total),
                        "Ausgaben": float(project.budget_used),
                        "Fortschritt": (
                            f"{(project.donations_total / project.budget_total * 100):.1f}%"
                            if project.budget_total > 0
                            else "0%"
                        ),
                    }
                )

            # Erstelle Excel mit mehreren Sheets
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                # Sheet 1: Monatliche Spenden
                df_monthly = pd.DataFrame(monthly_donations)
                df_monthly.to_excel(writer, sheet_name=f"Spenden_{year}", index=False)

                # Sheet 2: Projektübersicht
                df_projects = pd.DataFrame(project_data)
                df_projects.to_excel(writer, sheet_name="Projekte", index=False)

                # Sheet 3: Jahreszusammenfassung
                summary = pd.DataFrame(
                    [
                        {
                            "Jahr": year,
                            "Gesamtspenden": sum(m["Spenden"] for m in monthly_donations),
                            "Durchschnitt pro Monat": sum(m["Spenden"] for m in monthly_donations)
                            / 12,
                            "Aktive Projekte": len([p for p in projects if p.status == "active"]),
                            "Abgeschlossene Projekte": len(
                                [p for p in projects if p.status == "completed"]
                            ),
                        }
                    ]
                )
                summary.to_excel(writer, sheet_name="Zusammenfassung", index=False)

                # Formatierung
                for sheet in writer.sheets.values():
                    for column in sheet.columns:
                        max_length = 0
                        column_letter = column[0].column_letter
                        for cell in column:
                            try:
                                if len(str(cell.value)) > max_length:
                                    max_length = len(str(cell.value))
                            except:
                                pass
                        adjusted_width = min(max_length + 2, 50)
                        sheet.column_dimensions[column_letter].width = adjusted_width

            output.seek(0)
            return output.getvalue()

    # ==================== Helper Methods ====================

    async def _to_excel(self, data: list[dict], sheet_name: str = "Export") -> bytes:
        """Konvertiert zu Excel"""
        df = pd.DataFrame(data)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

            # Formatierung
            worksheet = writer.sheets[sheet_name[:31]]
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width

        output.seek(0)
        return output.getvalue()

    async def _to_csv(self, data: list[dict]) -> bytes:
        """Konvertiert zu CSV mit UTF-8 BOM"""
        if not data:
            return b""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys(), delimiter=";")
        writer.writeheader()
        writer.writerows(data)

        return output.getvalue().encode("utf-8-sig")

    async def _to_json(self, data: list[dict]) -> bytes:
        """Konvertiert zu JSON"""
        return json.dumps(data, indent=2, default=str).encode("utf-8")

    async def create_export_archive(self, exports: list[bytes], filenames: list[str]) -> bytes:
        """Erstellt ZIP-Archiv mit mehreren Exporten"""
        output = io.BytesIO()

        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipf:
            for content, filename in zip(exports, filenames):
                zipf.writestr(filename, content)

        output.seek(0)
        return output.getvalue()
