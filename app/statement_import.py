"""Parse card statement CSV files for reconciliation import."""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from typing import Any


HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "posted_date", "transaction_date", "posting_date", "trans_date"),
    "cardholder": ("cardholder", "cardholder_name", "name", "employee", "cardholder name"),
    "merchant": ("merchant", "description", "vendor", "payee", "narrative", "details"),
    "amount": ("amount", "transaction_amount", "value", "gbp", "charge"),
    "currency": ("currency", "curr", "ccy"),
}


def _normalize_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")


def _map_headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        return {}
    normalized = {_normalize_header(h): h for h in fieldnames if h}
    mapping: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            key = _normalize_header(alias)
            if key in normalized:
                mapping[canonical] = normalized[key]
                break
    return mapping


def _parse_date(raw: str) -> dt.date | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> float | None:
    text = (raw or "").strip().replace("£", "").replace(",", "")
    if not text:
        return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def parse_statement_csv(data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Return parsed statement rows and non-fatal error messages."""
    errors: list[str] = []
    if not data:
        return [], ["Uploaded file is empty."]

    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    mapping = _map_headers(reader.fieldnames)
    missing = [k for k in ("date", "merchant", "amount") if k not in mapping]
    if missing:
        return [], [f"Missing required column(s): {', '.join(missing)}. Expected date, merchant, amount."]

    rows: list[dict[str, Any]] = []
    for line_no, raw_row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in raw_row.values()):
            continue
        posted = _parse_date(raw_row.get(mapping["date"], ""))
        amount = _parse_amount(raw_row.get(mapping["amount"], ""))
        merchant = (raw_row.get(mapping["merchant"], "") or "").strip()
        if posted is None:
            errors.append(f"Line {line_no}: invalid or missing date.")
            continue
        if amount is None:
            errors.append(f"Line {line_no}: invalid or missing amount.")
            continue
        if not merchant:
            errors.append(f"Line {line_no}: missing merchant/description.")
            continue
        cardholder = ""
        if "cardholder" in mapping:
            cardholder = (raw_row.get(mapping["cardholder"], "") or "").strip()
        currency = "GBP"
        if "currency" in mapping:
            currency = (raw_row.get(mapping["currency"], "") or "GBP").strip().upper() or "GBP"
        rows.append(
            {
                "posted_date": posted,
                "year": posted.year,
                "month": posted.month,
                "cardholder_name": cardholder,
                "merchant": merchant,
                "amount": amount,
                "currency": currency,
            }
        )

    if not rows and not errors:
        errors.append("No data rows found in CSV.")
    return rows, errors
