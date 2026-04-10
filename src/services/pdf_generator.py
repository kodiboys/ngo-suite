# FILE: src/services/pdf_generator.py
# MODULE: PDF Generation Service für Zuwendungsbescheinigungen & Berichte
# Professionelle PDFs mit ReportLab, WeasyPrint, QR-Codes, digitalen Siegeln

import logging
from datetime import datetime
from io import BytesIO
from typing import Any
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select

from src.core.entities.base import Donation, Project, SKR42Account

logger = logging.getLogger(__name__)


class DonationReceiptGenerator:
    """Generator für Zuwendungsbescheinigungen nach §10b EStG"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def generate_donation_receipt(
        self, donation_id: UUID, include_personal_data: bool = True
    ) -> bytes:
        """Generiert Zuwendungsbescheinigung als PDF"""
        async with self.session_factory() as session:
            stmt = select(Donation).where(Donation.id == donation_id)
            result = await session.execute(stmt)
            donation = result.scalar_one()

            stmt = select(Project).where(Project.id == donation.project_id)
            result = await session.execute(stmt)
            project = result.scalar_one()

            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            story = []
            styles = getSampleStyleSheet()

            # Titel
            title_style = ParagraphStyle(
                "GermanTitle",
                parent=styles["Heading1"],
                fontSize=16,
                textColor=colors.HexColor("#1a472a"),
                alignment=1,
                spaceAfter=20,
            )
            story.append(Paragraph("Zuwendungsbescheinigung", title_style))
            story.append(Spacer(1, 15))

            # Spenderinformationen
            story.append(Paragraph("A. Angaben zum Spender", styles["Heading2"]))
            donor_info = [
                ["Name:", donation.donor_name_encrypted or "---"],
                [
                    "E-Mail:",
                    (
                        donation.donor_email_pseudonym[:30] + "..."
                        if donation.donor_email_pseudonym
                        else "---"
                    ),
                ],
            ]
            donor_table = Table(donor_info, colWidths=[50 * mm, 100 * mm])
            donor_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ]
                )
            )
            story.append(donor_table)
            story.append(Spacer(1, 15))

            # Spendeninformationen
            story.append(Paragraph("B. Angaben zur Spende", styles["Heading2"]))
            donation_info = [
                ["Betrag:", f"{donation.amount:,.2f} €"],
                ["Datum:", donation.created_at.strftime("%d.%m.%Y")],
                ["Projekt:", project.name],
            ]
            donation_table = Table(donation_info, colWidths=[50 * mm, 100 * mm])
            donation_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.beige),
                    ]
                )
            )
            story.append(donation_table)

            doc.build(story)
            buffer.seek(0)
            return buffer.getvalue()


class SKR42BalanceSheetGenerator:
    """Generator für SKR42-Bilanzen & Gewinn/Verlust-Rechnungen"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def generate_balance_sheet(
        self, project_id: UUID | None = None, year: int = None, include_comparison: bool = True
    ) -> bytes:
        """Generiert SKR42-Bilanz als PDF"""
        if year is None:
            year = datetime.utcnow().year

        async with self.session_factory() as session:
            balance_data = await self._get_balance_data(session, project_id, year)

            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
            story = []
            styles = getSampleStyleSheet()

            title_style = ParagraphStyle(
                "BalanceTitle", parent=styles["Heading1"], fontSize=18, alignment=1, spaceAfter=20
            )

            title_text = f"SKR42 Bilanz - {year}"
            if project_id:
                project = await session.get(Project, project_id)
                title_text += f" - Projekt: {project.name}"
            story.append(Paragraph(title_text, title_style))
            story.append(Spacer(1, 15))

            # ==================== AKTIVA ====================
            story.append(Paragraph("AKTIVA", styles["Heading2"]))

            active_data = [["Konto", "Bezeichnung", f"Saldo {year}"]]

            for account in balance_data.get("active", []):
                active_data.append(
                    [
                        account["account_number"],
                        account["account_name"],
                        f"{account['balance']:,.2f} €",
                    ]
                )

            total_active = sum(a["balance"] for a in balance_data.get("active", []))
            active_data.append(["", "SUMME AKTIVA", f"{total_active:,.2f} €"])

            active_table = self._create_finance_table(active_data)
            story.append(active_table)
            story.append(Spacer(1, 20))

            # ==================== PASSIVA ====================
            story.append(Paragraph("PASSIVA", styles["Heading2"]))

            passive_data = [["Konto", "Bezeichnung", f"Saldo {year}"]]

            for account in balance_data.get("passive", []):
                passive_data.append(
                    [
                        account["account_number"],
                        account["account_name"],
                        f"{account['balance']:,.2f} €",
                    ]
                )

            total_passive = sum(a["balance"] for a in balance_data.get("passive", []))
            passive_data.append(["", "SUMME PASSIVA", f"{total_passive:,.2f} €"])

            passive_table = self._create_finance_table(passive_data)
            story.append(passive_table)

            doc.build(story)
            buffer.seek(0)
            return buffer.getvalue()

    async def _get_balance_data(
        self, session, project_id: UUID | None, year: int
    ) -> dict[str, Any]:
        """Sammelt Bilanzdaten aus SKR42-Konten"""
        stmt = select(SKR42Account).where(SKR42Account.is_active is True)
        if project_id:
            stmt = stmt.where(SKR42Account.project_id == project_id)

        result = await session.execute(stmt)
        accounts = result.scalars().all()

        active_accounts = []
        passive_accounts = []

        for account in accounts:
            balance_data = {
                "account_number": account.account_number,
                "account_name": account.account_name,
                "balance": 0,
            }

            if account.account_number.startswith("0") or account.account_number.startswith("1"):
                active_accounts.append(balance_data)
            else:
                passive_accounts.append(balance_data)

        return {
            "active": active_accounts,
            "passive": passive_accounts,
            "donations_total": 0,
            "project_cost_ratio": 0,
        }

    def _create_finance_table(self, data: list[list]) -> Table:
        """Erstellt formatierte Finanztabelle"""
        table = Table(data, colWidths=[35 * mm, 70 * mm, 45 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d6a4f")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8f5e9")),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ]
            )
        )
        return table


class ProjectReportGenerator:
    """Generator für detaillierte Projektberichte"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def generate_project_report(
        self, project_id: UUID, include_donors: bool = False
    ) -> bytes:
        """Generiert Projektbericht als PDF"""
        async with self.session_factory() as session:
            project = await session.get(Project, project_id)

            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            story = []
            styles = getSampleStyleSheet()

            title_style = ParagraphStyle(
                "ReportTitle", parent=styles["Heading1"], fontSize=20, alignment=1, spaceAfter=20
            )

            story.append(Paragraph(f"Projektbericht: {project.name}", title_style))
            story.append(Spacer(1, 10))

            # Projekt-Overview
            overview_data = [
                [
                    "Projektzeitraum:",
                    f"{project.start_date.strftime('%d.%m.%Y')} - {project.end_date.strftime('%d.%m.%Y') if project.end_date else 'laufend'}",
                ],
                ["Budget gesamt:", f"{project.budget_total:,.2f} €"],
                ["Ausgaben bisher:", f"{project.budget_used:,.2f} €"],
                ["Spenden insgesamt:", f"{project.donations_total:,.2f} €"],
                [
                    "Fortschritt:",
                    f"{(project.budget_used / project.budget_total * 100) if project.budget_total > 0 else 0:.1f}%",
                ],
            ]

            overview_table = Table(overview_data, colWidths=[60 * mm, 100 * mm])
            overview_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 11),
                        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a472a")),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.beige),
                    ]
                )
            )
            story.append(overview_table)

            doc.build(story)
            buffer.seek(0)
            return buffer.getvalue()
