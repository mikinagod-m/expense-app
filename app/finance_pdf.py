"""PDF exports for finance archive."""
from __future__ import annotations

from fpdf import FPDF
from fpdf.enums import XPos, YPos


PERIOD_PDF_HEADERS = [
    "Date",
    "Claimant",
    "Reference",
    "Detail",
    "Category",
    "Gross",
]
PERIOD_PDF_INDICES = [0, 1, 2, 6, 7, 16]


def _safe_text(value) -> str:
    text = str(value or "")
    return text.encode("latin-1", errors="replace").decode("latin-1")


class ExportPDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, _safe_text(f"Page {self.page_no()}"), align="R")


def build_period_export_pdf(
    headers: list[str],
    rows: list[list],
    *,
    title: str,
    subtitle: str,
) -> bytes:
    pdf = ExportPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, _safe_text(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _safe_text(subtitle), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    col_headers = [headers[i] for i in PERIOD_PDF_INDICES]
    widths = [24, 34, 28, 72, 28, 22]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(242, 242, 238)
    for header, width in zip(col_headers, widths):
        pdf.cell(width, 7, _safe_text(header), border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for row in rows:
        values = [_safe_text(row[i]) for i in PERIOD_PDF_INDICES]
        if pdf.get_y() > 185:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 8)
            for header, width in zip(col_headers, widths):
                pdf.cell(width, 7, _safe_text(header), border=1, fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
        for value, width in zip(values, widths):
            pdf.cell(width, 6, value[:48], border=1)
        pdf.ln()

    return pdf.output()


def build_claim_export_pdf(claim: dict) -> bytes:
    pdf = ExportPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _safe_text("Expense claim"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _safe_text(f"Reference: {claim.get('ref') or '-'}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 6, _safe_text(f"Claimant: {claim.get('claimant_name') or '-'}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(
        0,
        6,
        _safe_text(
            f"Period: {claim.get('period_label') or '-'} | "
            f"Type: {claim.get('type') or '-'} | Status: {claim.get('status') or '-'}"
        ),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.cell(0, 6, _safe_text(f"Submitted: {claim.get('posted_label') or '-'}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if claim.get("approved_by_name"):
        pdf.cell(
            0,
            6,
            _safe_text(
                f"Approved by: {claim['approved_by_name']} "
                f"({claim.get('approved_at') or '-'})"
            ),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    pdf.ln(3)

    widths = [24, 70, 30, 30, 24]
    headers = ["Date", "Detail", "Category", "Receipt ref", "Gross"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(242, 242, 238)
    for header, width in zip(headers, widths):
        pdf.cell(width, 7, _safe_text(header), border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    gross_total = 0.0
    for line in claim.get("lines") or []:
        gross = float(line.get("amount") or 0.0)
        gross_total += gross
        values = [
            line.get("date") or "",
            (line.get("narrative") or "")[:46],
            (line.get("category") or ""),
            line.get("receipt_ref") or "",
            f"{gross:.2f}",
        ]
        for value, width in zip(values, widths):
            pdf.cell(width, 7, _safe_text(value), border=1)
        pdf.ln()

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 8, _safe_text(f"Claim total: GBP {gross_total:.2f}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return pdf.output()
