"""
Local receipt OCR with Tesseract. Nothing leaves the server.

`parse_receipt` returns best-guess (date, merchant, amount). It is deliberately
conservative — the user always confirms/corrects in the UI. OCR is there to save
typing, not to be trusted blindly.
"""
import io
import re
import datetime as dt

import pytesseract
from PIL import Image

from .config import settings

if settings.tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

# Matches 12.34 / 1,234.56 etc.
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+\.\d{2}")
_DATE_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
_TOTAL_HINT = re.compile(r"(total|amount due|balance|grand total)", re.I)


def _to_image(data: bytes, filename: str) -> Image.Image:
    if filename.lower().endswith(".pdf"):
        # First page only; needs poppler installed (pdf2image).
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(data, first_page=1, last_page=1)
        return pages[0]
    return Image.open(io.BytesIO(data))


def _confidence_hint(ocr_date: str | None, ocr_merchant: str | None, ocr_amount: float | None) -> tuple[float, str]:
    """Simple explainable confidence score for user guidance."""
    score = 0.0
    if ocr_date:
        score += 0.34
    if ocr_merchant:
        score += 0.33
    if ocr_amount is not None:
        score += 0.33

    if score >= 0.85:
        label = "high"
    elif score >= 0.5:
        label = "medium"
    else:
        label = "low"
    return round(score, 2), label


def parse_receipt(data: bytes, filename: str) -> dict:
    try:
        img = _to_image(data, filename)
        text = pytesseract.image_to_string(img)
    except Exception as e:  # OCR is best-effort; never block the upload
        score, label = _confidence_hint(None, None, None)
        return {
            "ocr_date": None,
            "ocr_merchant": None,
            "ocr_amount": None,
            "ocr_confidence_score": score,
            "ocr_confidence_label": label,
            "error": str(e),
        }

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Merchant: first non-numeric line is usually the shop name.
    merchant = next((l for l in lines if not _AMOUNT_RE.fullmatch(l.replace(" ", ""))
                     and len(l) > 2), None)

    # Date: first parseable date in the text.
    date = None
    m = _DATE_RE.search(text)
    if m:
        d, mo, y = m.groups()
        y = int(y) + (2000 if len(y) == 2 else 0)
        try:
            date = dt.date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            date = None

    # Amount: prefer a number on a line mentioning 'total', else the largest.
    amount = None
    total_amounts = [float(a.replace(",", "")) for l in lines if _TOTAL_HINT.search(l)
                     for a in _AMOUNT_RE.findall(l)]
    if total_amounts:
        amount = max(total_amounts)
    else:
        all_amounts = [float(a.replace(",", "")) for a in _AMOUNT_RE.findall(text)]
        amount = max(all_amounts) if all_amounts else None

    ocr_merchant = merchant[:200] if merchant else None
    score, label = _confidence_hint(date, ocr_merchant, amount)
    return {
        "ocr_date": date,
        "ocr_merchant": ocr_merchant,
        "ocr_amount": amount,
        "ocr_confidence_score": score,
        "ocr_confidence_label": label,
    }
