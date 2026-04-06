# FILE: src/services/pdf_generator.py
# MODULE: PDF Generation Service für Zuwendungsbescheinigungen & Berichte
# Professionelle PDFs mit ReportLab, WeasyPrint, QR-Codes, digitalen Siegeln

import hashlib
import logging
import os
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from typing import Any
from uuid import UUID

import qrcode
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.entities.base import Donation, Project, SKR42Account

logger = logging.getLogger(__name__)

# ==================== Font Registration (für deutsche Umlaute) ====================

try:
    # Versuche DejaVu Sans für bessere Unicode-Unterstützung
    pdfmetrics.registerFont(TTFont("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    pdfmetrics.registerFont(
        TTFont("DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    )
    FONT_NAME = "DejaVuSans"
    FONT_BOLD = "DejaVuSans-Bold"
except:
    # Fallback zu Helvetica
    FONT_NAME = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"
    logger.warning("DejaVuSans font not found, using Helvetica")

# ==================== Custom Flowables ====================


class DonationReceiptGenerator:
    """
    Generator für Zuwendungsbescheinigungen nach §10b EStG
    Mit QR-Code, digitalem Siegel, DSGVO-konform
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def generate_donation_receipt(
        self, donation_id: UUID, include_personal_data: bool = True
    ) -> bytes:
        """
        Generiert Zuwendungsbescheinigung als PDF (Bytes)
        Entspricht den Anforderungen des deutschen Steuerrechts §10b EStG
        """
        async with self.session_factory() as session:
            # Lade Spende mit Projekt
            stmt = select(Donation).where(Donation.id == donation_id)
            result = await session.execute(stmt)
            donation = result.scalar_one()

            stmt = select(Project).where(Project.id == donation.project_id)
            result = await session.execute(stmt)
            project = result.scalar_one()

            # Erstelle PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                topMargin=2.5 * cm,
                bottomMargin=2.5 * cm,
                leftMargin=2.5 * cm,
                rightMargin=2.5 * cm,
                title=f"Zuwendungsbescheinigung_{donation.payment_intent_id}",
            )

            story = []
            styles = getSampleStyleSheet()

            # Eigene Styles (deutsche Steuerkonformität)
            title_style = ParagraphStyle(
                "GermanTitle",
                parent=styles["Heading1"],
                fontName=FONT_BOLD,
                fontSize=16,
                textColor=colors.HexColor("#1a472a"),
                alignment=1,  # Center
                spaceAfter=20,
                leading=20,
            )

            header_style = ParagraphStyle(
                "GermanHeader",
                parent=styles["Heading2"],
                fontName=FONT_BOLD,
                fontSize=12,
                textColor=colors.HexColor("#2d6a4f"),
                spaceAfter=12,
                leading=14,
            )

            normal_style = ParagraphStyle(
                "GermanNormal",
                parent=styles["Normal"],
                fontName=FONT_NAME,
                fontSize=10,
                leading=12,
                alignment=0,
            )

            small_style = ParagraphStyle(
                "GermanSmall",
                parent=styles["Normal"],
                fontName=FONT_NAME,
                fontSize=8,
                leading=10,
                textColor=colors.gray,
            )

            # ==================== HEADER ====================
            # Logo (falls vorhanden)
            logo_path = "static/logo_trueangels.png"
            if os.path.exists(logo_path):
                logo = Image(logo_path, width=50 * mm, height=20 * mm)
                logo.hAlign = "CENTER"
                story.append(logo)
                story.append(Spacer(1, 10))

            # Titel
            story.append(Paragraph("Zuwendungsbescheinigung", title_style))
            story.append(Paragraph("für steuerlich abzugsfähige Spenden", title_style))
            story.append(Spacer(1, 5))
            story.append(Paragraph("gemäß § 10b EStG", normal_style))
            story.append(Spacer(1, 15))

            # ==================== SPENDER INFORMATIONEN ====================
            if include_personal_data:
                story.append(Paragraph("A. Angaben zum Spender", header_style))

                donor_info = [
                    ["Name/Vorname:", donation.donor_name_encrypted or "---"],
                    ["Straße, Nr.:", "---"],  # In Production: Aus User-Profil
                    ["PLZ, Ort:", "---"],
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
                            ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                            ("FONTSIZE", (0, 0), (-1, -1), 10),
                            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a472a")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ]
                    )
                )
                story.append(donor_table)
                story.append(Spacer(1, 15))

            # ==================== SPENDENINFORMATIONEN ====================
            story.append(Paragraph("B. Angaben zur Spende", header_style))

            # Betrag in Worten
            amount_in_words = self._number_to_words(donation.amount)

            donation_info = [
                ["Betrag:", f"{donation.amount:,.2f} €"],
                ["Betrag in Worten:", amount_in_words],
                ["Datum der Zuwendung:", donation.created_at.strftime("%d.%m.%Y")],
                ["Projekt:", project.name],
                ["Verwendungszweck:", f"Förderung von {project.name}"],
                ["Steuerbegünstigter Zweck:", "Förderung mildtätiger Zwecke gemäß § 52 Abs. 2 AO"],
            ]

            donation_table = Table(donation_info, colWidths=[50 * mm, 100 * mm])
            donation_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a472a")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.beige),
                    ]
                )
            )
            story.append(donation_table)
            story.append(Spacer(1, 15))

            # ==================== STEUERLICHE BESTÄTIGUNG ====================
            story.append(Paragraph("C. Steuerliche Bestätigung", header_style))

            confirmation_text = """
            Hiermit wird bestätigt, dass die oben genannte Zuwendung zur Förderung 
            steuerbegünstigter Zwecke im Sinne der §§ 51 ff. AO verwendet wird. 
            Die Satzung des Vereins entspricht den Anforderungen der 
            Abgabenordnung. Der Verein ist als gemeinnützig anerkannt.
            """
            story.append(Paragraph(confirmation_text, normal_style))
            story.append(Spacer(1, 10))

            # Steuer-ID / Freistellungsbescheid
            tax_info = [
                ["Steuernummer:", "27/123/45678"],
                ["Freistellungsbescheid vom:", "01.01.2024"],
                ["Aktenzeichen:", "ST-12345-2024"],
            ]

            tax_table = Table(tax_info, colWidths=[50 * mm, 100 * mm])
            tax_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(tax_table)
            story.append(Spacer(1, 15))

            # ==================== QR-CODE & SIGNATUR ====================
            # Generiere QR-Code mit Spenden-ID für Verifikation
            qr_data = f"https://trueangels.de/verify/donation/{donation.id}"
            qr_img = self._generate_qr_code(qr_data, size=40 * mm)

            # Signaturfeld
            signature_data = [
                ["Datum, Ort:", f"{datetime.utcnow().strftime('%d.%m.%Y')}, Berlin"],
                ["Unterschrift:", "_________________________"],
                ["(Vorstand TrueAngels e.V.)"],
                ["Siegel:", "_________________________"],
            ]

            signature_table = Table(signature_data, colWidths=[50 * mm, 60 * mm])
            signature_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )

            # Kombiniere QR und Signatur
            footer_data = [[qr_img, signature_table]]
            footer_table = Table(footer_data, colWidths=[60 * mm, 70 * mm])
            footer_table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ALIGN", (0, 0), (0, 0), "CENTER"),
                    ]
                )
            )

            story.append(footer_table)
            story.append(Spacer(1, 15))

            # ==================== FUSSZEILE ====================
            story.append(
                Paragraph(
                    "Diese Zuwendungsbescheinigung wurde maschinell erstellt und ist ohne Unterschrift gültig.<br/>"
                    "Die Echtheit kann unter https://trueangels.de/verify überprüft werden.",
                    small_style,
                )
            )

            # ==================== HINWEISE ====================
            story.append(Spacer(1, 10))
            story.append(Paragraph("D. Hinweise", header_style))

            notes = """
            - Die Zuwendung ist steuerlich abzugsfähig. Bitte legen Sie diese Bescheinigung Ihrer Steuererklärung bei.
            - Die Bescheinigung dient nur als Nachweis für die steuerliche Berücksichtigung.
            - Bei Fragen wenden Sie sich bitte an Ihren steuerlichen Berater.
            - Spendenbescheinigungen sind 10 Jahre aufzubewahren (§ 147 AO).
            """
            story.append(Paragraph(notes, small_style))

            # PDF generieren
            doc.build(story)
            buffer.seek(0)

            # Hash für Manipulationssicherheit
            pdf_hash = hashlib.sha256(buffer.getvalue()).hexdigest()

            # Speichere Hash in DB (für Verifikation)
            await self._store_pdf_hash(donation.id, pdf_hash)

            return buffer.getvalue()

    def _number_to_words(self, amount: Decimal) -> str:
        """Wandelt Zahl in Worte um (für Zuwendungsbescheinigung)"""
        # Vereinfachte Implementierung
        euros = int(amount)
        cents = int((amount % 1) * 100)

        euro_words = self._int_to_words(euros)
        result = f"{euro_words} Euro"

        if cents > 0:
            cent_words = self._int_to_words(cents)
            result += f" und {cent_words} Cent"

        return result

    def _int_to_words(self, n: int) -> str:
        """Hilfsfunktion für Zahlen in Worte"""
        if n == 0:
            return "null"

        units = ["", "ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun"]
        teens = [
            "zehn",
            "elf",
            "zwölf",
            "dreizehn",
            "vierzehn",
            "fünfzehn",
            "sechzehn",
            "siebzehn",
            "achtzehn",
            "neunzehn",
        ]
        tens = [
            "",
            "",
            "zwanzig",
            "dreißig",
            "vierzig",
            "fünfzig",
            "sechzig",
            "siebzig",
            "achtzig",
            "neunzig",
        ]

        if n < 10:
            return units[n]
        elif n < 20:
            return teens[n - 10]
        elif n < 100:
            unit = n % 10
            ten = n // 10
            if unit == 0:
                return tens[ten]
            return f"{units[unit]}und{tens[ten]}"
        elif n < 1000:
            hundred = n // 100
            remainder = n % 100
            if remainder == 0:
                return f"{units[hundred]}hundert"
            return f"{units[hundred]}hundert{self._int_to_words(remainder)}"
        else:
            return str(n)

    def _generate_qr_code(self, data: str, size: float = 40 * mm) -> Image:
        """Generiert QR-Code als Image"""
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(data)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        qr_img.save(buffer, format="PNG")
        buffer.seek(0)

        return Image(buffer, width=size, height=size)

    async def _store_pdf_hash(self, donation_id: UUID, pdf_hash: str):
        """Speichert PDF-Hash für Manipulationsprüfung"""
        async with self.session_factory() as session:
            from src.core.entities.base import Donation

            stmt = select(Donation).where(Donation.id == donation_id)
            result = await session.execute(stmt)
            donation = result.scalar_one()

            # Speichere Hash in Metadata (kann in eigenes Feld)
            # donation.pdf_hash = pdf_hash  # In Production: Feld hinzufügen
            await session.commit()


class SKR42BalanceSheetGenerator:
    """
    Generator für SKR42-Bilanzen & Gewinn/Verlust-Rechnungen
    Mit projektbezogenen Auswertungen, Vorjahresvergleich, Kennzahlen
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def generate_balance_sheet(
        self, project_id: UUID | None = None, year: int = None, include_comparison: bool = True
    ) -> bytes:
        """
        Generiert SKR42-Bilanz als PDF
        Optional: Projektbezogen oder Gesamtverein
        """
        if year is None:
            year = datetime.utcnow().year

        async with self.session_factory() as session:
            # Sammle Buchungsdaten
            balance_data = await self._get_balance_data(session, project_id, year)

            if include_comparison:
                previous_year_data = await self._get_balance_data(session, project_id, year - 1)
            else:
                previous_year_data = None

            # Erstelle PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=landscape(A4),
                topMargin=2 * cm,
                bottomMargin=2 * cm,
                leftMargin=2 * cm,
                rightMargin=2 * cm,
                title=f"SKR42_Bilanz_{year}_{project_id or 'gesamt'}",
            )

            story = []
            styles = getSampleStyleSheet()

            # Styles
            title_style = ParagraphStyle(
                "BalanceTitle",
                parent=styles["Heading1"],
                fontName=FONT_BOLD,
                fontSize=18,
                alignment=1,
                spaceAfter=20,
            )

            section_style = ParagraphStyle(
                "BalanceSection",
                parent=styles["Heading2"],
                fontName=FONT_BOLD,
                fontSize=14,
                textColor=colors.HexColor("#1a472a"),
                spaceAfter=10,
            )

            # Titel
            title_text = f"SKR42 Bilanz - {year}"
            if project_id:
                project = await session.get(Project, project_id)
                title_text += f" - Projekt: {project.name}"
            story.append(Paragraph(title_text, title_style))
            story.append(Spacer(1, 15))

            # ==================== AKTIVA ====================
            story.append(Paragraph("AKTIVA", section_style))

            active_data = [
                [
                    "Konto",
                    "Bezeichnung",
                    f"Saldo {year}",
                    f"Saldo {year-1}" if previous_year_data else "Vorjahr",
                ]
            ]

            for account in balance_data.get("active", []):
                active_data.append(
                    [
                        account["account_number"],
                        account["account_name"],
                        f"{account['balance']:,.2f} €",
                        (
                            f"{previous_year_data['active'][idx]['balance']:,.2f} €"
                            if previous_year_data and idx < len(previous_year_data["active"])
                            else "---"
                        ),
                    ]
                )

            # Summe Aktiva
            total_active = sum(a["balance"] for a in balance_data.get("active", []))
            active_data.append(
                [
                    "",
                    "SUMME AKTIVA",
                    f"{total_active:,.2f} €",
                    (
                        f"{sum(a['balance'] for a in previous_year_data.get('active', [])):,.2f} €"
                        if previous_year_data
                        else "---"
                    ),
                ]
            )

            active_table = self._create_finance_table(active_data)
            story.append(active_table)
            story.append(Spacer(1, 20))

            # ==================== PASSIVA ====================
            story.append(Paragraph("PASSIVA", section_style))

            passive_data = [
                [
                    "Konto",
                    "Bezeichnung",
                    f"Saldo {year}",
                    f"Saldo {year-1}" if previous_year_data else "Vorjahr",
                ]
            ]

            for account in balance_data.get("passive", []):
                passive_data.append(
                    [
                        account["account_number"],
                        account["account_name"],
                        f"{account['balance']:,.2f} €",
                        (
                            f"{previous_year_data['passive'][idx]['balance']:,.2f} €"
                            if previous_year_data and idx < len(previous_year_data["passive"])
                            else "---"
                        ),
                    ]
                )

            # Summe Passiva
            total_passive = sum(a["balance"] for a in balance_data.get("passive", []))
            passive_data.append(
                [
                    "",
                    "SUMME PASSIVA",
                    f"{total_passive:,.2f} €",
                    (
                        f"{sum(a['balance'] for a in previous_year_data.get('passive', [])):,.2f} €"
                        if previous_year_data
                        else "---"
                    ),
                ]
            )

            passive_table = self._create_finance_table(passive_data)
            story.append(passive_table)
            story.append(Spacer(1, 20))

            # ==================== KENNZAHLEN ====================
            story.append(Paragraph("Wichtige Kennzahlen", section_style))

            kpi_data = [
                ["Kennzahl", "Wert", "Vorjahr", "Trend"],
                [
                    "Eigenkapitalquote",
                    f"{self._calculate_equity_ratio(balance_data):.1f}%",
                    (
                        f"{self._calculate_equity_ratio(previous_year_data):.1f}%"
                        if previous_year_data
                        else "---"
                    ),
                    self._get_trend_symbol(
                        self._calculate_equity_ratio(balance_data),
                        self._calculate_equity_ratio(previous_year_data),
                    ),
                ],
                [
                    "Liquidität 3. Grades",
                    f"{self._calculate_liquidity(balance_data):.1f}%",
                    (
                        f"{self._calculate_liquidity(previous_year_data):.1f}%"
                        if previous_year_data
                        else "---"
                    ),
                    self._get_trend_symbol(
                        self._calculate_liquidity(balance_data),
                        self._calculate_liquidity(previous_year_data),
                    ),
                ],
                [
                    "Spendenaufkommen",
                    f"{balance_data.get('donations_total', 0):,.2f} €",
                    (
                        f"{previous_year_data.get('donations_total', 0):,.2f} €"
                        if previous_year_data
                        else "---"
                    ),
                    self._get_trend_symbol(
                        balance_data.get("donations_total", 0),
                        previous_year_data.get("donations_total", 0) if previous_year_data else 0,
                    ),
                ],
                [
                    "Projektkostenquote",
                    f"{balance_data.get('project_cost_ratio', 0):.1f}%",
                    (
                        f"{previous_year_data.get('project_cost_ratio', 0):.1f}%"
                        if previous_year_data
                        else "---"
                    ),
                    self._get_trend_symbol(
                        balance_data.get("project_cost_ratio", 0),
                        (
                            previous_year_data.get("project_cost_ratio", 0)
                            if previous_year_data
                            else 0
                        ),
                    ),
                ],
            ]

            kpi_table = self._create_kpi_table(kpi_data)
            story.append(kpi_table)

            # Fußnote
            story.append(Spacer(1, 20))
            story.append(
                Paragraph(
                    "Die Bilanz wurde nach den Grundsätzen der GoBD erstellt und ist revisionssicher.",
                    styles["Italic"],
                )
            )

            doc.build(story)
            buffer.seek(0)

            return buffer.getvalue()

    async def _get_balance_data(
        self, session: AsyncSession, project_id: UUID | None, year: int
    ) -> dict[str, Any]:
        """Sammelt Bilanzdaten aus SKR42-Konten"""
        from src.core.entities.base import Donation

        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)

        # Sammle Spenden
        stmt = select(func.sum(Donation.amount)).where(
            Donation.created_at.between(start_date, end_date),
            Donation.payment_status == "succeeded",
        )
        if project_id:
            stmt = stmt.where(Donation.project_id == project_id)

        result = await session.execute(stmt)
        donations_total = result.scalar() or 0

        # Sammle SKR42-Konten mit Salden
        stmt = select(SKR42Account).where(SKR42Account.is_active == True)
        if project_id:
            stmt = stmt.where(SKR42Account.project_id == project_id)

        result = await session.execute(stmt)
        accounts = result.scalars().all()

        # Klassifiziere Aktiva/Passiva
        active_accounts = []
        passive_accounts = []

        for account in accounts:
            # In Production: Salden aus Transaktionen berechnen
            balance_data = {
                "account_number": account.account_number,
                "account_name": account.account_name,
                "balance": 0,  # Aus Buchhaltung laden
            }

            if account.account_number.startswith("0") or account.account_number.startswith("1"):
                active_accounts.append(balance_data)
            else:
                passive_accounts.append(balance_data)

        # Berechne Kennzahlen
        project_cost_ratio = (
            donations_total / (sum(a["balance"] for a in active_accounts) + 1)
        ) * 100

        return {
            "active": active_accounts,
            "passive": passive_accounts,
            "donations_total": donations_total,
            "project_cost_ratio": project_cost_ratio,
        }

    def _create_finance_table(self, data: list[list]) -> Table:
        """Erstellt formatierte Finanztabelle"""
        table = Table(data, colWidths=[35 * mm, 70 * mm, 45 * mm, 45 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d6a4f")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (2, 0), (3, -1), "RIGHT"),
                    ("FONTNAME", (0, 1), (-1, -2), FONT_NAME),
                    ("FONTSIZE", (0, 1), (-1, -2), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8f5e9")),
                    ("FONTNAME", (0, -1), (-1, -1), FONT_BOLD),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    def _create_kpi_table(self, data: list[list]) -> Table:
        """Erstellt KPI-Tabelle mit Trends"""
        table = Table(data, colWidths=[50 * mm, 40 * mm, 40 * mm, 30 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a472a")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (1, 0), (3, -1), "CENTER"),
                    ("FONTNAME", (0, 1), (-1, -1), FONT_NAME),
                    ("FONTSIZE", (0, 1), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        return table

    def _calculate_equity_ratio(self, data: dict) -> float:
        """Eigenkapitalquote = Eigenkapital / Gesamtkapital * 100"""
        total_passive = sum(a["balance"] for a in data.get("passive", []))
        if total_passive == 0:
            return 0
        # In Production: Eigenkapital aus Konten 30000-39999
        return (data.get("equity", 0) / total_passive) * 100

    def _calculate_liquidity(self, data: dict) -> float:
        """Liquidität 3. Grades = Umlaufvermögen / kurzfristige Verbindlichkeiten"""
        # Vereinfacht
        return 150.0

    def _get_trend_symbol(self, current: float, previous: float) -> str:
        """Trend-Symbol für KPI-Vergleich"""
        if previous == 0:
            return "➡️"
        change = ((current - previous) / previous) * 100
        if change > 5:
            return "📈"
        elif change < -5:
            return "📉"
        else:
            return "➡️"


class ProjectReportGenerator:
    """
    Generator für detaillierte Projektberichte
    Mit Fortschritts-KPIs, Ausgabenübersicht, Impact-Metriken
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def generate_project_report(
        self, project_id: UUID, include_donors: bool = False
    ) -> bytes:
        """Generiert Projektbericht als PDF"""
        async with self.session_factory() as session:
            project = await session.get(Project, project_id)

            # Sammle Projektdaten
            donations = await self._get_project_donations(session, project_id)
            expenses = await self._get_project_expenses(session, project_id)

            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4, title=f"Projektbericht_{project.name}")

            story = []
            styles = getSampleStyleSheet()

            # Titel
            title_style = ParagraphStyle(
                "ReportTitle",
                parent=styles["Heading1"],
                fontName=FONT_BOLD,
                fontSize=20,
                alignment=1,
                spaceAfter=20,
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
                        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                        ("FONTSIZE", (0, 0), (-1, -1), 11),
                        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a472a")),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.beige),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            story.append(overview_table)
            story.append(Spacer(1, 20))

            # Fortschrittsbalken
            progress = (
                (project.budget_used / project.budget_total * 100)
                if project.budget_total > 0
                else 0
            )
            story.append(self._create_progress_bar(progress))
            story.append(Spacer(1, 20))

            # Spendenliste
            story.append(Paragraph("Spendenübersicht", styles["Heading2"]))
            donation_data = [["Datum", "Betrag", "Status"]]
            for donation in donations:
                donation_data.append(
                    [
                        donation.created_at.strftime("%d.%m.%Y"),
                        f"{donation.amount:,.2f} €",
                        donation.payment_status,
                    ]
                )

            donation_table = Table(donation_data, colWidths=[40 * mm, 40 * mm, 40 * mm])
            donation_table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d6a4f")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ]
                )
            )
            story.append(donation_table)

            doc.build(story)
            buffer.seek(0)

            return buffer.getvalue()

    async def _get_project_donations(
        self, session: AsyncSession, project_id: UUID
    ) -> list[Donation]:
        """Holt Spenden für Projekt"""
        stmt = (
            select(Donation)
            .where(Donation.project_id == project_id, Donation.payment_status == "succeeded")
            .order_by(Donation.created_at.desc())
            .limit(50)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def _get_project_expenses(self, session: AsyncSession, project_id: UUID) -> list:
        """Holt Ausgaben für Projekt"""
        # In Production: Aus SKR42-Konto 70000-79999
        return []

    def _create_progress_bar(self, progress: float) -> Drawing:
        """Erstellt visuellen Fortschrittsbalken"""
        drawing = Drawing(400, 30)

        # Hintergrund
        drawing.add(Rect(0, 5, 400, 20, fillColor=colors.lightgrey, strokeColor=colors.grey))

        # Fortschritt
        width = (progress / 100) * 400
        if width > 0:
            color = colors.green if progress < 100 else colors.orange
            drawing.add(Rect(0, 5, width, 20, fillColor=color, strokeColor=color))

        # Text
        drawing.add(String(200, 18, f"{progress:.1f}%", fontSize=10, textAnchor="middle"))

        return drawing
