import datetime as dt
import csv
import hashlib
import io
import math
import os
import uuid

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, engine
import calendar

from .models import (Base, User, Period, Claim, ClaimLine, Receipt, AuditLog,
                     ClaimType, ClaimStatus, Category, StatementLine, utc_now)
from .auth import (
    current_user,
    require_user,
    require_manager_or_finance,
    require_finance,
    require_admin,
    user_is_manager,
)
from .claim_utils import (
    claim_is_editable_by_owner,
    delete_claim,
    is_claim_empty,
    line_is_blank,
    purge_empty_drafts,
)
from .notifications import (
    notify_claimant_decision,
    notify_claimant_processed,
    notify_manager_claim_submitted,
)
from .statement_import import parse_statement_csv
from .reconciliation_match import index_unmatched_card_lines, suggest_match_for_statement
from .finance_pdf import build_claim_export_pdf, build_period_export_pdf
from .schema_upgrade import upgrade_schema
from .user_admin import (
    parse_bool,
    serialize_user_row,
    user_can_claim_period,
    validate_manager_id,
    validate_new_user,
)
from .ocr import parse_receipt

Base.metadata.create_all(engine)
upgrade_schema(engine)

app = FastAPI(title="Aimia Expense App")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
os.makedirs(settings.receipts_dir, exist_ok=True)
app.state.auth_init_error = None
ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".webp"}
RECEIPT_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}
IMAGE_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def log(db: Session, user_id, action, detail=""):
    # Keep audit detail compact and non-sensitive (IDs and state only).
    safe_detail = (detail or "")[:500]
    db.add(AuditLog(user_id=user_id, action=action, detail=safe_detail))
    db.commit()


def can_view_claim(user: User, claim: Claim) -> bool:
    return (
        claim.user_id == user.id
        or user.is_finance
        or claim.user.manager_id == user.id
    )


def serialize_line_for_review(line: ClaimLine) -> dict:
    receipt = line.receipt
    receipt_info = None
    if receipt and receipt.file_path and os.path.isfile(receipt.file_path):
        ext = os.path.splitext(receipt.file_path)[1].lower()
        receipt_info = {
            "id": receipt.id,
            "url": f"/receipts/{receipt.id}",
            "is_image": ext in IMAGE_RECEIPT_EXTENSIONS,
            "filename": os.path.basename(receipt.file_path),
        }
    return {
        "id": line.id,
        "date": line.date.isoformat() if line.date else None,
        "narrative": line.narrative or "",
        "receipt_ref": line.receipt_ref or "",
        "category": line.category.value.replace("_", " "),
        "amount": line.amount,
        "reclaim_vat": line.reclaim_vat,
        "receipt": receipt_info,
    }


def serialize_claim_for_review(claim: Claim) -> dict:
    """Backward-compatible alias; prefer serialize_claim_record with db session."""
    lines = [
        serialize_line_for_review(line)
        for line in claim.lines
        if not line_is_blank(line)
    ]
    return {
        "id": claim.id,
        "ref": claim.unique_ref,
        "user_id": claim.user_id,
        "claimant_name": claim.user.name,
        "period_id": claim.period_id,
        "period_label": f"{claim.period.month:02d}/{claim.period.year}",
        "type": claim.type.value,
        "status": claim.status.value,
        "gross_total": claim.gross_total,
        "submitted_at": claim.submitted_at.isoformat() if claim.submitted_at else None,
        "lines": lines,
    }


def claim_approver_name(db: Session, claim: Claim) -> str | None:
    if claim.approver:
        return claim.approver.name
    if claim.approved_by:
        approver = db.get(User, claim.approved_by)
        return approver.name if approver else None
    return None


def serialize_claim_record(db: Session, claim: Claim) -> dict:
    """Full claim payload for queues, history, and reports."""
    _ = claim.user
    _ = claim.period
    if claim.approved_by:
        _ = claim.approver
    posted_label, _ = claim_posted_label(claim)
    lines = [
        serialize_line_for_review(line)
        for line in claim.lines
        if not line_is_blank(line)
    ]
    return {
        "id": claim.id,
        "ref": claim.unique_ref,
        "user_id": claim.user_id,
        "claimant_name": claim.user.name,
        "period_id": claim.period_id,
        "period_label": f"{claim.period.month:02d}/{claim.period.year}",
        "type": claim.type.value,
        "status": claim.status.value,
        "gross_total": claim.gross_total,
        "submitted_at": claim.submitted_at.isoformat() if claim.submitted_at else None,
        "posted_label": posted_label,
        "approved_by_id": claim.approved_by,
        "approved_by_name": claim_approver_name(db, claim),
        "approved_at": claim.approved_at.isoformat() if claim.approved_at else None,
        "lines": lines,
    }


def claim_audit_events(db: Session, claim: Claim) -> list[dict]:
    """Return audit timeline entries for a claim, newest first."""
    claim_token = f"claim_id={claim.id}"
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.detail.contains(claim_token))
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
    ).all()

    # Backward compatibility for older claim.submit entries that only stored ref.
    if claim.unique_ref:
        legacy_submit_rows = db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "claim.submit", AuditLog.detail == claim.unique_ref)
            .order_by(AuditLog.at.desc(), AuditLog.id.desc())
        ).all()
        seen = {r.id for r in rows}
        for row in legacy_submit_rows:
            if row.id not in seen:
                rows.append(row)

    rows.sort(key=lambda r: (r.at, r.id), reverse=True)
    return _format_audit_rows(db, rows)


CLAIM_TIMELINE_ACTIONS = frozenset({
    "claim.create",
    "claim.submit",
    "claim.approve",
    "claim.reject",
    "claim.process",
})

TIMELINE_DETAIL_LABELS = {
    "ref": "Reference",
    "decision": "Decision",
    "comment": "Comment",
}

TIMELINE_HIDDEN_KEYS = frozenset({
    "claim_id",
    "line_id",
    "receipt_id",
    "filename",
    "period_id",
    "statement_line_id",
    "category",
    "amount",
})


def _format_audit_rows(db: Session, rows: list[AuditLog]) -> list[dict]:
    action_labels = {
        "claim.create": "Claim created",
        "claim.submit": "Submitted for approval",
        "claim.approve": "Approved",
        "claim.reject": "Rejected",
        "claim.process": "Processed for payment",
        "claim_line.update": "Line updated",
        "receipt.upload": "Receipt uploaded",
        "reconciliation.match": "Statement matched",
    }

    events = []
    for r in rows:
        actor = db.get(User, r.user_id) if r.user_id else None
        detail_items: list[dict] = []
        detail_raw = (r.detail or "").strip()
        detail_map: dict[str, str] = {}
        if detail_raw:
            for token in detail_raw.split(";"):
                if "=" not in token:
                    continue
                key, value = token.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key or not value:
                    continue
                detail_map[key] = value
                if key not in TIMELINE_HIDDEN_KEYS:
                    label = TIMELINE_DETAIL_LABELS.get(key, key.replace("_", " ").title())
                    detail_items.append({"key": label, "value": value})
        events.append(
            {
                "id": r.id,
                "at": r.at.isoformat() if r.at else "",
                "action": r.action,
                "action_label": action_labels.get(r.action, r.action.replace(".", " ").title()),
                "detail": r.detail or "",
                "detail_items": detail_items,
                "detail_map": detail_map,
                "actor_name": actor.name if actor else "System",
                "actor_id": r.user_id,
            }
        )
    return events


def claim_timeline_summary(event: dict, claim: Claim, db: Session) -> str:
    action = event["action"]
    detail = event.get("detail_map") or {}
    if action == "claim.create":
        return f"Opened for {period_label(claim.period)} ({claim.type.value} claim)."
    if action == "claim.submit":
        ref = detail.get("ref") or claim.unique_ref or "this claim"
        return f"Sent to your manager for approval. Reference {ref}."
    if action == "claim.approve":
        actor = event.get("actor_name") or "Manager"
        comment = detail.get("comment", "").strip()
        if comment:
            return f"Approved by {actor}. Comment: {comment}"
        return f"Approved by {actor}."
    if action == "claim.reject":
        actor = event.get("actor_name") or "Manager"
        comment = detail.get("comment", "").strip()
        if comment:
            return f"Rejected by {actor}. Reason: {comment}"
        return f"Rejected by {actor}."
    if action == "claim.process":
        actor = event.get("actor_name") or "Finance"
        return f"Marked processed by {actor}."
    return event.get("detail") or ""


def claim_timeline_events(db: Session, claim: Claim) -> list[dict]:
    """Milestone-only timeline for the claim detail page, oldest first."""
    rows = claim_audit_events(db, claim)
    timeline = [r for r in rows if r["action"] in CLAIM_TIMELINE_ACTIONS]
    for event in timeline:
        event["summary"] = claim_timeline_summary(event, claim, db)
    timeline.reverse()
    return timeline


def latest_rejection_event(events: list[dict]) -> dict | None:
    """Return the most recent rejection milestone, if any."""
    for event in reversed(events):
        if event.get("action") == "claim.reject":
            return event
    return None


def require_editable_claim(claim: Claim) -> None:
    if not claim_is_editable_by_owner(claim):
        raise HTTPException(400, "This claim can no longer be edited.")


def claim_posted_label(claim: Claim) -> tuple[str, str | None]:
    """Return display label and ISO timestamp for when the claim was posted."""
    if claim.submitted_at:
        label = claim.submitted_at.strftime("%d %b %Y · %H:%M").replace(" 0", " ")
        return label, claim.submitted_at.isoformat()
    return "Not posted", None


def nav_flags(db: Session, user: User) -> dict:
    is_manager = user_is_manager(db, user)
    return {
        "nav_can_manager": is_manager or user.is_finance,
        "nav_can_finance": user.is_finance,
        "nav_can_admin": user.is_admin,
    }


def nav_badge_counts(db: Session, user: User) -> dict:
    pending_approvals = 0
    finance_approved = 0
    if user.is_finance or user_is_manager(db, user):
        pending_query = select(func.count()).select_from(Claim).where(Claim.status == ClaimStatus.submitted)
        if not user.is_finance:
            pending_query = pending_query.where(
                Claim.user_id.in_(select(User.id).where(User.manager_id == user.id))
            )
        pending_approvals = db.scalar(pending_query) or 0
    if user.is_finance:
        finance_approved = db.scalar(
            select(func.count()).select_from(Claim).where(Claim.status == ClaimStatus.approved)
        ) or 0
    return {
        "pending_approvals": pending_approvals,
        "finance_approved": finance_approved,
    }


def open_periods_for_nav(db: Session, user: User) -> list[dict]:
    periods = db.scalars(
        select(Period).where(Period.is_open == True).order_by(Period.type)  # noqa: E712
    ).all()
    return [
        {
            "id": p.id,
            "type": p.type,
            "nav_label": (
                f"{'Card' if p.type == ClaimType.card else 'Cash'} · "
                f"{calendar.month_abbr[p.month]} {p.year}"
            ),
        }
        for p in periods
        if user_can_claim_period(user, p)
    ]


def _dashboard_open_periods(db: Session, user: User) -> list[dict]:
    periods = db.scalars(
        select(Period).where(Period.is_open == True).order_by(Period.type)  # noqa: E712
    ).all()
    return [
        {
            "id": p.id,
            "type": p.type.value,
            "label": period_label(p),
            "deadline": p.deadline.isoformat(),
            "deadlineLabel": p.deadline.strftime("%d %b %Y").lstrip("0"),
            "navLabel": (
                f"{'Card' if p.type == ClaimType.card else 'Cash'} · "
                f"{calendar.month_abbr[p.month]} {p.year}"
            ),
            "startTitle": period_label(p),
            "startSubtitle": (
                "Credit card · Barclaycard" if p.type == ClaimType.card else "Cash expenses"
            ),
        }
        for p in periods
        if user_can_claim_period(user, p)
    ]


def page_context(db: Session, user: User, active_nav: str) -> dict:
    ctx = {
        "user": user,
        "user_initials": user_initials(user.name),
        "active_nav": active_nav,
        "open_periods": open_periods_for_nav(db, user),
    }
    ctx.update(nav_flags(db, user))
    return ctx


def access_denied_response(
    request: Request,
    db: Session,
    *,
    title: str,
    message: str,
    status_code: int,
):
    user = current_user(request)
    if not user:
        return HTMLResponse(
            f"<h1>{title}</h1><p>{message}</p><p><a href='/login'>Sign in</a></p>",
            status_code=status_code,
        )
    return templates.TemplateResponse(
        request,
        "access_denied.html",
        {
            **page_context(db, user, "dash"),
            "title": title,
            "message": message,
            "status_code": status_code,
        },
        status_code=status_code,
    )


def apply_claim_filters(
    base_query,
    period: str = "all",
    claim_type: str = "all",
    status: str = "all",
):
    q = base_query
    if period != "all":
        try:
            year_str, month_str = period.split("-", 1)
            year = int(year_str)
            month = int(month_str)
            if month < 1 or month > 12:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "Invalid period filter. Use all or YYYY-MM.")
        q = q.join(Period, Claim.period_id == Period.id).where(Period.year == year, Period.month == month)

    if claim_type != "all":
        try:
            mapped_type = ClaimType(claim_type)
        except ValueError:
            raise HTTPException(400, "Invalid type filter. Use all, cash, or card.")
        q = q.where(Claim.type == mapped_type)

    if status != "all":
        try:
            mapped_status = ClaimStatus(status)
        except ValueError:
            raise HTTPException(400, "Invalid status filter.")
        q = q.where(Claim.status == mapped_status)

    return q


def build_finance_export_rows(db: Session, claims: list[Claim]) -> list[list]:
    rows: list[list] = []
    for c in claims:
        period_label = f"{c.period.month:02d}/{c.period.year}"
        approver = claim_approver_name(db, c)
        submitted = c.submitted_at.isoformat() if c.submitted_at else ""
        approved = c.approved_at.isoformat() if c.approved_at else ""
        for line in c.lines:
            if line_is_blank(line):
                continue
            gross = round(float(line.amount or 0.0), 2)
            vat = round(float(line.vat_amount or 0.0), 2)
            net = round(gross - vat, 2)
            has_receipt = "yes" if line.receipt else "no"
            rows.append(
                [
                    line.date.isoformat() if line.date else "",
                    c.user.name,
                    c.unique_ref or "",
                    c.type.value,
                    period_label,
                    c.status.value,
                    line.narrative or "",
                    line.category.value.replace("_", " ") if line.category else "",
                    line.receipt_ref or "",
                    "yes" if line.reclaim_vat else "no",
                    has_receipt,
                    submitted,
                    approver or "",
                    approved,
                    net,
                    vat,
                    gross,
                ]
            )
    return rows


FINANCE_EXPORT_HEADERS = [
    "expense_date",
    "claimant",
    "reference",
    "type",
    "period",
    "status",
    "detail",
    "category",
    "receipt_ref",
    "vat_reclaim",
    "has_receipt",
    "submitted_at",
    "approved_by",
    "approved_at",
    "net_gbp",
    "vat_gbp",
    "gross_gbp",
]


def parse_period_filter(period: str) -> tuple[int, int] | None:
    if period == "all":
        return None
    try:
        year_str, month_str = period.split("-", 1)
        year = int(year_str)
        month = int(month_str)
        if month < 1 or month > 12:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "Invalid period filter. Use all or YYYY-MM.")
    return year, month


def validate_period_for_claim_creation(period: Period | None) -> str | None:
    """Return a user-facing error when period is not valid for claim creation."""
    if not period:
        return "The selected period was not found."
    if not period.is_open:
        return "The selected period is closed."

    try:
        period_start = dt.date(period.year, period.month, 1)
    except ValueError:
        return "The selected period is invalid."

    today = dt.date.today()
    label = f"{period.month:02d}/{period.year}"
    if today < period_start:
        return f"Claims for period {label} are not open yet."
    if today > period.deadline:
        return f"The deadline for period {label} passed on {period.deadline.isoformat()}."
    return None


def validate_claim_line_input(
    date_raw: str,
    category_raw: str,
    amount_raw: float,
) -> tuple[list[str], dt.date | None, Category | None, float | None]:
    errors: list[str] = []
    normalized_date: dt.date | None = None
    normalized_category: Category | None = None
    normalized_amount: float | None = None

    if not date_raw.strip():
        errors.append("Date is required.")
    else:
        try:
            normalized_date = dt.date.fromisoformat(date_raw.strip())
        except ValueError:
            errors.append("Date must be a valid ISO date (YYYY-MM-DD).")

    if not category_raw.strip():
        errors.append("Category is required.")
    else:
        try:
            normalized_category = Category(category_raw.strip())
        except ValueError:
            errors.append("Category is invalid.")

    if amount_raw is None:
        errors.append("Amount is required.")
    elif not math.isfinite(amount_raw):
        errors.append("Amount must be a finite number.")
    elif amount_raw <= 0:
        errors.append("Amount must be greater than 0.")
    else:
        normalized_amount = round(amount_raw, 2)

    return errors, normalized_date, normalized_category, normalized_amount


def sanitize_filename(filename: str) -> str:
    base = os.path.basename(filename or "").strip().lower()
    safe = "".join(ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in base)
    return safe[:120] if safe else "unknown"


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_duplicate_receipt_reasons(
    db: Session,
    user_id: int,
    uploaded_filename: str,
    uploaded_data: bytes,
    parsed_receipt: dict,
    current_line_id: int,
) -> list[str]:
    reasons: list[str] = []
    file_hash = compute_sha256(uploaded_data)

    existing_receipts = db.scalars(
        select(Receipt)
        .join(ClaimLine, Receipt.claim_line_id == ClaimLine.id)
        .join(Claim, ClaimLine.claim_id == Claim.id)
        .where(Claim.user_id == user_id, ClaimLine.id != current_line_id)
        .order_by(Receipt.id.desc())
    ).all()

    # Exact duplicate guardrail: same binary content hash as an existing receipt file.
    for existing in existing_receipts:
        path = (existing.file_path or "").strip()
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, "rb") as f:
                existing_hash = compute_sha256(f.read())
        except OSError:
            continue
        if existing_hash == file_hash:
            reasons.append("This file matches a previously uploaded receipt (same file hash).")
            break

    # Heuristic guardrail: same OCR date + amount used before.
    new_date = parsed_receipt.get("ocr_date")
    new_amount = parsed_receipt.get("ocr_amount")
    if new_date and new_amount is not None:
        for existing in existing_receipts:
            if existing.ocr_date == new_date and existing.ocr_amount is not None:
                if abs(float(existing.ocr_amount) - float(new_amount)) < 0.01:
                    reasons.append("A receipt with the same OCR date and amount already exists.")
                    break

    # Heuristic guardrail: filename recently reused by same user.
    safe_name = sanitize_filename(uploaded_filename)
    recent_upload_audits = db.scalars(
        select(AuditLog)
        .where(AuditLog.user_id == user_id, AuditLog.action == "receipt.upload")
        .order_by(AuditLog.id.desc())
        .limit(100)
    ).all()
    filename_token = f"filename={safe_name}"
    if any(filename_token in (a.detail or "") for a in recent_upload_audits):
        reasons.append("A receipt with the same filename was uploaded recently.")

    return reasons


# ---------------- Auth ----------------
@app.get("/login")
async def login(request: Request, as_user: str | None = Query(default=None, alias="as")):
    if settings.dev_login:
        with next(get_db()) as db:
            user = None
            if as_user:
                token = as_user.strip()
                if token.isdigit():
                    user = db.get(User, int(token))
                else:
                    user = db.scalar(select(User).where(User.email == token))
                    if not user:
                        user = db.scalar(
                            select(User).where(User.email.ilike(f"%{token}%")).limit(1)
                        )
            if not user:
                user = db.scalar(select(User).order_by(User.id))
            if not user:
                # Keep dev login deterministic even before seed data exists.
                user = User(name="Local Demo User", email="local.demo@example.com")
                db.add(user)
                db.commit()
                db.refresh(user)
            request.session["uid"] = user.id
        return RedirectResponse("/", status_code=302)

    if request.app.state.auth_init_error:
        return HTMLResponse(
            f"<h1>Authentication is not configured</h1>"
            f"<p>{request.app.state.auth_init_error}</p>"
            f"<p>Set the Azure AD env vars or set DEV_LOGIN=1 for local development.</p>",
            status_code=503,
        )

    oauth = request.app.state.oauth
    return await oauth.aad.authorize_redirect(request, settings.aad_redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    from .auth import upsert_user_from_claims
    if request.app.state.auth_init_error:
        return HTMLResponse(
            f"<h1>Authentication callback unavailable</h1>"
            f"<p>{request.app.state.auth_init_error}</p>",
            status_code=503,
        )
    oauth = request.app.state.oauth
    token = await oauth.aad.authorize_access_token(request)
    uid = upsert_user_from_claims(token["userinfo"])
    request.session["uid"] = uid
    return RedirectResponse("/", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


if not settings.dev_login:
    from .auth import build_oauth
    try:
        app.state.oauth = build_oauth()
    except ValueError as exc:
        app.state.oauth = None
        app.state.auth_init_error = str(exc)


CATEGORY_LABELS = {
    Category.hotel: "Hotel",
    Category.subsistence: "Subsistence",
    Category.travel: "Travel",
    Category.foreign_travel: "Foreign travel",
    Category.postage: "Postage",
    Category.staff_entertaining: "Staff entertaining",
    Category.customer_entertaining: "Customer entertaining",
    Category.other: "Other",
    Category.personal: "Personal",
}


def user_initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper() if name else "??"


def period_label(period: Period) -> str:
    return f"{calendar.month_name[period.month]} {period.year}"


def build_dashboard_payload(db: Session, user: User) -> dict:
    """Serialize live claimant dashboard data for dashboard.html."""
    claims = db.scalars(
        select(Claim).where(Claim.user_id == user.id).order_by(Claim.id.desc())
    ).all()
    for claim in claims:
        _ = claim.lines
        _ = claim.period

    today = dt.date.today()
    manager = db.get(User, user.manager_id) if user.manager_id else None
    open_periods = _dashboard_open_periods(db, user)

    claimed_month = 0.0
    claims_month_count = 0
    awaiting_total = 0.0
    awaiting_count = 0
    paid_ytd = 0.0
    paid_ytd_count = 0
    cat_totals: dict[str, float] = {}
    status_counts = {s.value: 0 for s in ClaimStatus}

    for claim in claims:
        status_counts[claim.status.value] += 1
        if claim.period.year == today.year and claim.period.month == today.month:
            claimed_month += claim.gross_total
            claims_month_count += 1
        if claim.status == ClaimStatus.submitted:
            awaiting_total += claim.gross_total
            awaiting_count += 1
        if claim.status == ClaimStatus.processed and claim.period.year == today.year:
            paid_ytd += claim.gross_total
            paid_ytd_count += 1
        if claim.period.year == today.year:
            for line in claim.lines:
                label = CATEGORY_LABELS.get(line.category, line.category.value.replace("_", " ").title())
                cat_totals[label] = cat_totals.get(label, 0.0) + float(line.amount)

    cat_spend = sorted(cat_totals.items(), key=lambda item: item[1], reverse=True)[:6]
    next_deadline = min(
        (dt.date.fromisoformat(p["deadline"]) for p in open_periods),
        default=None,
    )
    first_name = user.name.split()[0] if user.name else "there"
    hour = dt.datetime.now().hour
    if hour < 12:
        greeting = f"Good morning, {first_name}."
    elif hour < 17:
        greeting = f"Good afternoon, {first_name}."
    else:
        greeting = f"Good evening, {first_name}."

    open_count = len(open_periods)
    if open_count == 0:
        lede = "No expense periods are open right now."
    elif open_count == 1:
        lede = "Here's where your expenses stand. One period is open for new claims."
    else:
        lede = f"Here's where your expenses stand. {open_count} periods are open for new claims."

    if awaiting_count and manager:
        awaiting_sub = f"{awaiting_count} claim{'s' if awaiting_count != 1 else ''} with {manager.name.split()[0]}"
    elif awaiting_count:
        awaiting_sub = f"{awaiting_count} claim{'s' if awaiting_count != 1 else ''} pending"
    else:
        awaiting_sub = "Nothing waiting on approval"

    if next_deadline:
        days = (next_deadline - today).days
        deadline_main = next_deadline.strftime("%d %b").lstrip("0")
        deadline_sub = f"{days} day{'s' if days != 1 else ''} away" if days >= 0 else "Passed"
    else:
        deadline_main = "—"
        deadline_sub = "No open periods"

    claim_rows = []
    history_lines = []
    for c in claims:
        if c.status == ClaimStatus.draft and is_claim_empty(c):
            continue
        posted_label, posted_at = claim_posted_label(c)
        record = serialize_claim_record(db, c)
        claim_rows.append(
            {
                "id": c.id,
                "ref": c.unique_ref or "draft",
                "type": c.type.value.capitalize(),
                "period": f"{c.period.year}-{c.period.month:02d}",
                "pl": period_label(c.period),
                "postedLabel": posted_label,
                "postedAt": posted_at,
                "status": c.status.value,
                "total": c.gross_total,
                "approvedBy": record["approved_by_name"],
            }
        )
        for line in record["lines"]:
            history_lines.append(
                {
                    "claimId": c.id,
                    "ref": record["ref"] or "draft",
                    "detail": line["narrative"],
                    "receiptRef": line["receipt_ref"],
                    "category": line["category"],
                    "type": record["type"],
                    "amount": line["amount"],
                    "postedLabel": record["posted_label"],
                    "submittedAt": record["submitted_at"],
                    "status": record["status"],
                    "approvedBy": record["approved_by_name"],
                    "receipt": line["receipt"],
                    "expenseDate": line["date"],
                }
            )

    return {
        "user": {
            "name": user.name,
            "email": user.email,
            "initials": user_initials(user.name),
        },
        "greeting": greeting,
        "lede": lede,
        "stats": {
            "claimedMonth": round(claimed_month, 2),
            "claimsMonthCount": claims_month_count,
            "awaitingTotal": round(awaiting_total, 2),
            "awaitingCount": awaiting_count,
            "awaitingSub": awaiting_sub,
            "paidYtd": round(paid_ytd, 2),
            "paidYtdCount": paid_ytd_count,
            "deadlineMain": deadline_main,
            "deadlineSub": deadline_sub,
        },
        "claims": claim_rows,
        "historyLines": history_lines,
        "catSpend": [[label, round(amount, 2)] for label, amount in cat_spend],
        "statusCounts": status_counts,
        "openPeriods": open_periods,
    }


# ---------------- Dashboard ----------------
@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    view: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    purge_empty_drafts(db, user.id)
    dashboard = build_dashboard_payload(db, user)
    active_nav = "claims" if view == "claims" else "dash"
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            **page_context(db, user, active_nav),
            "dashboard_json": dashboard,
        },
    )


# ---------------- Manager UI ----------------
@app.get("/manager/approvals", response_class=HTMLResponse)
def manager_approvals_page(request: Request, db: Session = Depends(get_db)):
    try:
        reviewer = require_manager_or_finance(request, db)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            return access_denied_response(
                request,
                db,
                title="Manager approvals access denied",
                message="You need a manager or finance role to use this page.",
                status_code=exc.status_code,
            )
        raise
    return templates.TemplateResponse(
        request,
        "manager_approvals.html",
        page_context(db, reviewer, "manager"),
    )


# ---------------- Finance UI ----------------
@app.get("/finance/processing", response_class=HTMLResponse)
def finance_processing_page(request: Request, db: Session = Depends(get_db)):
    try:
        finance_user = require_finance(request)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            return access_denied_response(
                request,
                db,
                title="Finance processing access denied",
                message="You need a finance role to use this page.",
                status_code=exc.status_code,
            )
        raise
    return templates.TemplateResponse(
        request,
        "finance_processing.html",
        page_context(db, finance_user, "finance_processing"),
    )


@app.get("/finance/reconciliation", response_class=HTMLResponse)
def finance_reconciliation_page(request: Request, db: Session = Depends(get_db)):
    try:
        finance_user = require_finance(request)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            return access_denied_response(
                request,
                db,
                title="Finance reconciliation access denied",
                message="You need a finance role to use this page.",
                status_code=exc.status_code,
            )
        raise
    return templates.TemplateResponse(
        request,
        "finance_reconciliation.html",
        page_context(db, finance_user, "finance_recon"),
    )


@app.get("/nav/badges")
def nav_badges(request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    counts = nav_badge_counts(db, user)
    return {"ok": True, **counts}


@app.get("/finance/periods", response_class=HTMLResponse)
def finance_periods_page(request: Request, db: Session = Depends(get_db)):
    try:
        finance_user = require_finance(request)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            return access_denied_response(
                request,
                db,
                title="Finance periods access denied",
                message="You need a finance role to manage claim periods.",
                status_code=exc.status_code,
            )
        raise
    return templates.TemplateResponse(
        request,
        "finance_periods.html",
        page_context(db, finance_user, "finance_periods"),
    )


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request, db: Session = Depends(get_db)):
    try:
        admin_user = require_admin(request)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            return access_denied_response(
                request,
                db,
                title="Admin access denied",
                message="You need admin permissions to manage users and roles.",
                status_code=exc.status_code,
            )
        raise
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        page_context(db, admin_user, "admin_users"),
    )


@app.get("/admin/users/data")
def admin_users_data(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    users = db.scalars(select(User).order_by(User.name, User.id)).all()
    for user in users:
        if user.manager_id:
            _ = user.manager
    manager_options = [{"id": u.id, "name": u.name} for u in users]
    return {
        "ok": True,
        "users": [serialize_user_row(db, u) for u in users],
        "manager_options": manager_options,
    }


@app.post("/admin/users")
def admin_create_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    manager_id: str = Form(""),
    is_finance: str = Form(""),
    is_admin: str = Form(""),
    has_credit_card: str = Form(""),
    can_claim_cash: str = Form(""),
    db: Session = Depends(get_db),
):
    admin_user = require_admin(request)
    try:
        clean_name, clean_email = validate_new_user(name, email, db)
        parsed_manager_id = int(manager_id) if manager_id.strip() else None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    user = User(
        name=clean_name,
        email=clean_email,
        manager_id=None,
        is_finance=parse_bool(is_finance),
        is_admin=parse_bool(is_admin),
        has_credit_card=parse_bool(has_credit_card),
        can_claim_cash=parse_bool(can_claim_cash) if can_claim_cash else True,
    )
    db.add(user)
    db.flush()
    try:
        user.manager_id = validate_manager_id(user, parsed_manager_id, db)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    db.refresh(user)
    log(
        db,
        admin_user.id,
        "user.create",
        f"user_id={user.id};email={user.email}",
    )
    return {"ok": True, "user": serialize_user_row(db, user)}


@app.post("/admin/users/{user_id}")
def admin_update_user(
    user_id: int,
    request: Request,
    manager_id: str = Form(""),
    is_finance: str = Form(""),
    is_admin: str = Form(""),
    has_credit_card: str = Form(""),
    can_claim_cash: str = Form(""),
    db: Session = Depends(get_db),
):
    admin_user = require_admin(request)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    parsed_manager_id = int(manager_id) if manager_id.strip() else None
    try:
        user.manager_id = validate_manager_id(user, parsed_manager_id, db)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    removing_own_admin = user.id == admin_user.id and user.is_admin and not parse_bool(is_admin)
    if removing_own_admin:
        other_admins = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_admin == True, User.id != admin_user.id)  # noqa: E712
        )
        if not other_admins:
            raise HTTPException(400, "You cannot remove your own admin access while you are the only admin.")

    user.is_finance = parse_bool(is_finance)
    user.is_admin = parse_bool(is_admin)
    user.has_credit_card = parse_bool(has_credit_card)
    user.can_claim_cash = parse_bool(can_claim_cash)
    db.commit()
    db.refresh(user)
    log(
        db,
        admin_user.id,
        "user.update",
        (
            f"user_id={user.id};manager_id={user.manager_id or ''};"
            f"finance={int(user.is_finance)};admin={int(user.is_admin)};"
            f"card={int(user.has_credit_card)};cash={int(user.can_claim_cash)}"
        ),
    )
    return {"ok": True, "user": serialize_user_row(db, user)}


# ---------------- Claims ----------------
@app.post("/claims/new")
def new_claim(request: Request, period_id: int = Form(...),
              db: Session = Depends(get_db)):
    user = require_user(request)
    period = db.get(Period, period_id)
    period_error = validate_period_for_claim_creation(period)
    if period_error:
        return HTMLResponse(
            f"<h1>Cannot create claim</h1><p>{period_error}</p>"
            f"<p><a href='/'>Return to dashboard</a></p>",
            status_code=400,
        )
    if not user_can_claim_period(user, period):
        return HTMLResponse(
            "<h1>Cannot create claim</h1>"
            f"<p>You do not have access to start a {period.type.value} claim.</p>"
            f"<p><a href='/'>Return to dashboard</a></p>",
            status_code=403,
        )

    existing = db.scalar(
        select(Claim)
        .where(
            Claim.user_id == user.id,
            Claim.period_id == period.id,
            Claim.status.in_([ClaimStatus.draft, ClaimStatus.rejected]),
        )
        .order_by(Claim.id.desc())
    )
    if existing:
        if is_claim_empty(existing) and not existing.lines:
            db.add(ClaimLine(claim_id=existing.id))
            db.commit()
        return RedirectResponse(f"/claims/{existing.id}", status_code=302)

    claim = Claim(user_id=user.id, period_id=period.id, type=period.type)
    db.add(claim)
    db.flush()
    db.add(ClaimLine(claim_id=claim.id))
    db.commit()
    log(db, user.id, "claim.create", f"claim_id={claim.id};period_id={period.id}")
    return RedirectResponse(f"/claims/{claim.id}", status_code=302)


@app.post("/claims/{claim_id}/discard")
def discard_claim(claim_id: int, request: Request, db: Session = Depends(get_db)):
    """Drop an abandoned empty draft (e.g. user opened claim and left without entering data)."""
    user = require_user(request)
    claim = db.get(Claim, claim_id)
    if not claim or claim.user_id != user.id:
        raise HTTPException(404)
    if not is_claim_empty(claim):
        return {"ok": True, "discarded": False}
    delete_claim(db, claim)
    db.commit()
    return {"ok": True, "discarded": True}


@app.get("/claims/{claim_id}", response_class=HTMLResponse)
def view_claim(claim_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    claim = db.get(Claim, claim_id)
    if not claim or claim.user_id != user.id:
        raise HTTPException(404)
    if claim.status == ClaimStatus.draft and not claim.lines:
        db.add(ClaimLine(claim_id=claim.id))
        db.commit()
        db.refresh(claim)
    events = claim_timeline_events(db, claim)
    today = dt.date.today()
    period = claim.period
    approver_name = claim_approver_name(db, claim)
    approved_at_label = None
    if claim.approved_at:
        approved_at_label = claim.approved_at.strftime("%d %b %Y · %H:%M").replace(" 0", " ")
    submitted_label = None
    if claim.submitted_at:
        submitted_label = claim.submitted_at.strftime("%d %b %Y · %H:%M").replace(" 0", " ")
    display_lines = [line for line in claim.lines if not line_is_blank(line)]
    for line in display_lines:
        _ = line.receipt
    return templates.TemplateResponse(
        request,
        "claim.html",
        {
            **page_context(db, user, "claims"),
            "claim": claim,
            "display_lines": display_lines,
            "categories": list(Category),
            "events": events,
            "claim_period_label": period_label(period),
            "today_day": today.strftime("%A"),
            "today_date": f"{today.day} {calendar.month_name[today.month]} {today.year}",
            "deadline_label": period.deadline.strftime("%d %b %Y").lstrip("0"),
            "is_editable": claim_is_editable_by_owner(claim),
            "is_resubmit": claim.status == ClaimStatus.rejected,
            "rejection_event": latest_rejection_event(events) if claim.status == ClaimStatus.rejected else None,
            "approver_name": approver_name,
            "approved_at_label": approved_at_label,
            "submitted_label": submitted_label,
        },
    )


@app.get("/claims/{claim_id}/audit")
def claim_audit(claim_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404)

    can_view = can_view_claim(user, claim)
    if not can_view:
        raise HTTPException(403, "Not allowed to view this claim audit")

    return {"ok": True, "claim_id": claim.id, "events": claim_audit_events(db, claim)}


@app.post("/claims/{claim_id}/lines", response_class=HTMLResponse)
def add_line(claim_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    claim = db.get(Claim, claim_id)
    if not claim or claim.user_id != user.id:
        raise HTTPException(404)
    require_editable_claim(claim)
    line = ClaimLine(claim_id=claim.id)
    db.add(line)
    db.commit()
    return templates.TemplateResponse(request, "_line_row.html", {
        "line": line, "categories": list(Category),
    })


@app.post("/lines/{line_id}")
def save_line(line_id: int, request: Request,
              date: str = Form(""), narrative: str = Form(""),
              receipt_ref: str = Form(""), category: str = Form("other"),
              amount: float = Form(0.0), reclaim_vat: bool = Form(False),
              db: Session = Depends(get_db)):
    user = require_user(request)
    line = db.get(ClaimLine, line_id)
    if not line or line.claim.user_id != user.id:
        raise HTTPException(404)
    require_editable_claim(line.claim)

    errors, normalized_date, normalized_category, normalized_amount = (
        validate_claim_line_input(date, category, amount)
    )
    if errors:
        return JSONResponse(
            content={"ok": False, "errors": errors},
            status_code=400,
        )

    line.date = normalized_date
    line.narrative = narrative.strip()
    line.receipt_ref = receipt_ref.strip()
    line.category = normalized_category
    line.amount = normalized_amount
    line.reclaim_vat = reclaim_vat
    db.commit()
    log(
        db,
        user.id,
        "claim_line.update",
        f"claim_id={line.claim_id};line_id={line.id};category={line.category.value};amount={line.amount:.2f}",
    )
    return {"ok": True, "errors": [], "gross_total": line.claim.gross_total}


@app.post("/lines/{line_id}/receipt")
async def upload_receipt(line_id: int, request: Request,
                         file: UploadFile = File(...),
                         db: Session = Depends(get_db)):
    """Upload a receipt, run local OCR, return pre-filled fields for confirmation."""
    user = require_user(request)
    line = db.get(ClaimLine, line_id)
    if not line or line.claim.user_id != user.id:
        raise HTTPException(404)
    require_editable_claim(line.claim)

    if not file.filename:
        return JSONResponse(
            {"ok": False, "message": "No file selected. Upload a JPG, PNG, WEBP, or PDF receipt."},
            status_code=400,
        )

    data = await file.read()
    ext = os.path.splitext(file.filename)[1].lower() or ".bin"
    if ext not in ALLOWED_RECEIPT_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_RECEIPT_EXTENSIONS))
        return JSONResponse(
            {"ok": False, "message": f"Unsupported file type '{ext}'. Allowed types: {allowed}."},
            status_code=400,
        )
    if not data:
        return JSONResponse(
            {"ok": False, "message": "Uploaded file is empty. Please choose a valid receipt file."},
            status_code=400,
        )
    if len(data) > settings.receipt_max_bytes:
        max_mb = round(settings.receipt_max_bytes / (1024 * 1024), 1)
        return JSONResponse(
            {"ok": False, "message": f"File is too large. Maximum size is {max_mb} MB."},
            status_code=413,
        )

    parsed = parse_receipt(data, file.filename)
    duplicate_reasons = find_duplicate_receipt_reasons(
        db=db,
        user_id=user.id,
        uploaded_filename=file.filename,
        uploaded_data=data,
        parsed_receipt=parsed,
        current_line_id=line.id,
    )

    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.receipts_dir, fname)
    with open(path, "wb") as f:
        f.write(data)

    receipt = line.receipt or Receipt(claim_line_id=line.id)
    receipt.file_path = path
    receipt.ocr_date = parsed.get("ocr_date")
    receipt.ocr_merchant = parsed.get("ocr_merchant")
    receipt.ocr_amount = parsed.get("ocr_amount")
    db.add(receipt)
    db.commit()
    safe_name = sanitize_filename(file.filename)
    log(
        db,
        user.id,
        "receipt.upload",
        f"claim_id={line.claim_id};line_id={line.id};receipt_id={receipt.id};filename={safe_name}",
    )

    ocr_error = parsed.get("error")
    if ocr_error:
        message = (
            "Receipt uploaded, but OCR could not extract fields. "
            "You can continue by entering details manually."
        )
    else:
        message = "Receipt uploaded. Pre-filled fields are ready to review and save."

    # The UI uses these to pre-fill the row; the user confirms before saving.
    return {
        "ok": True,
        "message": message,
        "possible_duplicate": len(duplicate_reasons) > 0,
        "duplicate_reasons": duplicate_reasons,
        "ocr_confidence_score": parsed.get("ocr_confidence_score"),
        "ocr_confidence_label": parsed.get("ocr_confidence_label"),
        "suggest_date": parsed.get("ocr_date"),
        "suggest_merchant": parsed.get("ocr_merchant"),
        "suggest_amount": parsed.get("ocr_amount"),
    }


@app.post("/claims/{claim_id}/submit")
def submit_claim(claim_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    claim = db.get(Claim, claim_id)
    if not claim or claim.user_id != user.id:
        raise HTTPException(404)
    require_editable_claim(claim)

    # Validation that the old SOP handled by hand:
    problems = []
    if not claim.lines:
        problems.append("No claim lines.")
    for i, l in enumerate(claim.lines, 1):
        if l.amount and not l.receipt_ref and not l.receipt:
            problems.append(f"Line {i}: no receipt or receipt reference.")
    if problems:
        return {"ok": False, "problems": problems}

    claim.status = ClaimStatus.submitted
    claim.signed_at = utc_now()
    claim.submitted_at = utc_now()
    # Unique ref = period + zero-padded claim id (replaces the VBA number).
    claim.unique_ref = f"{claim.period.year}{claim.period.month:02d}{claim.id:04d}"
    db.commit()
    log(db, user.id, "claim.submit", f"claim_id={claim.id};ref={claim.unique_ref}")
    db.refresh(claim)
    try:
        notify_manager_claim_submitted(db, claim)
    except Exception:
        pass  # notifications must not block submit
    return {"ok": True, "ref": claim.unique_ref}


# ---------------- Manager / Finance ----------------
@app.get("/receipts/{receipt_id}")
def view_receipt(receipt_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    receipt = db.get(Receipt, receipt_id)
    if not receipt or not receipt.line:
        raise HTTPException(404, "Receipt not found")
    claim = receipt.line.claim
    if not can_view_claim(user, claim):
        raise HTTPException(403, "Not allowed to view this receipt")
    path = (receipt.file_path or "").strip()
    if not path or not os.path.isfile(path):
        raise HTTPException(404, "Receipt file not found")
    ext = os.path.splitext(path)[1].lower()
    media_type = RECEIPT_MEDIA_TYPES.get(ext, "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        filename=os.path.basename(path),
        content_disposition_type="inline",
    )


@app.get("/manager/claims/pending")
def manager_pending_claims(request: Request, db: Session = Depends(get_db)):
    reviewer = require_manager_or_finance(request, db)
    q = select(Claim).where(Claim.status == ClaimStatus.submitted).order_by(Claim.id.desc())
    if not reviewer.is_finance:
        q = q.where(Claim.user_id.in_(select(User.id).where(User.manager_id == reviewer.id)))
    claims = db.scalars(q).all()
    return {
        "ok": True,
        "reviewer_id": reviewer.id,
        "is_finance": reviewer.is_finance,
        "count": len(claims),
        "claims": [serialize_claim_record(db, c) for c in claims],
    }


@app.post("/manager/claims/{claim_id}/decision")
def manager_claim_decision(
    claim_id: int,
    request: Request,
    decision: str = Form(...),
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    reviewer = require_manager_or_finance(request, db)
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")

    if not reviewer.is_finance and claim.user.manager_id != reviewer.id:
        raise HTTPException(403, "You can only decide claims for your direct reports")

    normalized = decision.strip().lower()
    if normalized not in {"approved", "rejected"}:
        raise HTTPException(400, "Decision must be 'approved' or 'rejected'")

    if claim.status != ClaimStatus.submitted:
        raise HTTPException(400, "Only submitted claims can be decided")

    trimmed_comment = comment.strip()
    if normalized == "rejected" and not trimmed_comment:
        raise HTTPException(400, "Rejection comment is required")

    if normalized == "approved":
        claim.status = ClaimStatus.approved
        claim.approved_by = reviewer.id
        claim.approved_at = utc_now()
        action = "claim.approve"
    else:
        claim.status = ClaimStatus.rejected
        claim.approved_by = None
        claim.approved_at = None
        action = "claim.reject"

    db.commit()
    detail = f"claim_id={claim.id};decision={normalized};comment={trimmed_comment[:400]}"
    log(db, reviewer.id, action, detail)
    db.refresh(claim)
    try:
        notify_claimant_decision(db, claim, reviewer, normalized, trimmed_comment)
    except Exception:
        pass
    return {"ok": True, "claim_id": claim.id, "status": claim.status.value, "comment": trimmed_comment}


@app.get("/finance/claims/approved")
def finance_approved_claims(
    request: Request,
    period: str = Query("all"),
    claim_type: str = Query("all", alias="type"),
    db: Session = Depends(get_db),
):
    finance_user = require_finance(request)
    q = select(Claim).where(Claim.status == ClaimStatus.approved).order_by(Claim.id.desc())
    q = apply_claim_filters(q, period=period, claim_type=claim_type, status="approved")
    claims = db.scalars(q).all()
    return {
        "ok": True,
        "count": len(claims),
        "claims": [serialize_claim_record(db, c) for c in claims],
        "reviewed_by": finance_user.id,
    }


@app.get("/finance/reconciliation/data")
def finance_reconciliation_data(
    request: Request,
    period: str = Query("all"),
    show: str = Query("all"),
    db: Session = Depends(get_db),
):
    require_finance(request)
    period_filter = parse_period_filter(period)

    statement_query = select(StatementLine).order_by(StatementLine.id.desc())
    if period_filter:
        year, month = period_filter
        statement_query = statement_query.where(StatementLine.year == year, StatementLine.month == month)
    statement_lines = db.scalars(statement_query).all()

    card_line_query = (
        select(ClaimLine)
        .join(Claim, ClaimLine.claim_id == Claim.id)
        .join(Period, Claim.period_id == Period.id)
        .where(Claim.type == ClaimType.card, Claim.status.in_([ClaimStatus.approved, ClaimStatus.processed]))
        .order_by(ClaimLine.id.desc())
    )
    if period_filter:
        year, month = period_filter
        card_line_query = card_line_query.where(Period.year == year, Period.month == month)
    card_lines = db.scalars(card_line_query).all()
    for line in card_lines:
        _ = line.claim.user

    unmatched_index = index_unmatched_card_lines(card_lines)

    statement_rows = []
    for s in statement_lines:
        if s.claim_line:
            c = s.claim_line.claim
            row_status = "matched"
            row = {
                "statement_line_id": s.id,
                "date": s.posted_date.isoformat() if s.posted_date else "",
                "cardholder": s.cardholder_name,
                "merchant": s.merchant,
                "statement_amount": s.amount,
                "currency": s.currency,
                "status": row_status,
                "claim_line_id": s.claim_line_id,
                "claim_id": c.id,
                "claim_ref": c.unique_ref or "",
                "claimant": c.user.name,
                "claim_amount": s.claim_line.amount,
                "suggested_match": None,
            }
        else:
            row_status = "unmatched_statement"
            suggestion = suggest_match_for_statement(s, unmatched_index)
            row = {
                "statement_line_id": s.id,
                "date": s.posted_date.isoformat() if s.posted_date else "",
                "cardholder": s.cardholder_name,
                "merchant": s.merchant,
                "statement_amount": s.amount,
                "currency": s.currency,
                "status": row_status,
                "claim_line_id": None,
                "claim_id": None,
                "claim_ref": "",
                "claimant": "",
                "claim_amount": None,
                "suggested_match": suggestion,
            }
        statement_rows.append(row)

    missing_rows = []
    for l in card_lines:
        if l.statement_line is not None:
            continue
        claim = l.claim
        missing_rows.append(
            {
                "status": "missing_statement",
                "claim_line_id": l.id,
                "claim_id": claim.id,
                "claim_ref": claim.unique_ref or "",
                "claimant": claim.user.name,
                "date": l.date.isoformat() if l.date else "",
                "merchant_hint": l.narrative or "",
                "claim_amount": l.amount,
            }
        )

    if show == "attention":
        statement_rows = [r for r in statement_rows if r["status"] == "unmatched_statement"]
    elif show != "all":
        raise HTTPException(400, "Invalid show filter. Use all or attention.")

    return {
        "ok": True,
        "summary": {
            "matched": sum(1 for r in statement_rows if r["status"] == "matched"),
            "unmatched_statement": sum(1 for r in statement_rows if r["status"] == "unmatched_statement"),
            "missing_statement": len(missing_rows),
        },
        "statement_rows": statement_rows,
        "missing_claim_rows": missing_rows,
    }


def serialize_period_row(period: Period) -> dict:
    return {
        "id": period.id,
        "year": period.year,
        "month": period.month,
        "type": period.type.value,
        "label": period_label(period),
        "deadline": period.deadline.isoformat(),
        "is_open": period.is_open,
    }


@app.get("/finance/periods/data")
def finance_periods_data(request: Request, db: Session = Depends(get_db)):
    require_finance(request)
    periods = db.scalars(
        select(Period).order_by(Period.year.desc(), Period.month.desc(), Period.type)
    ).all()
    return {"ok": True, "periods": [serialize_period_row(p) for p in periods]}


@app.post("/finance/periods")
def finance_create_period(
    request: Request,
    year: int = Form(...),
    month: int = Form(...),
    claim_type: str = Form(...),
    deadline: str = Form(...),
    db: Session = Depends(get_db),
):
    require_finance(request)
    if month < 1 or month > 12:
        raise HTTPException(400, "Month must be between 1 and 12.")
    try:
        mapped_type = ClaimType(claim_type.strip().lower())
    except ValueError:
        raise HTTPException(400, "Type must be cash or card.")
    try:
        deadline_date = dt.date.fromisoformat(deadline.strip())
    except ValueError:
        raise HTTPException(400, "Deadline must be YYYY-MM-DD.")

    existing = db.scalar(
        select(Period).where(
            Period.year == year,
            Period.month == month,
            Period.type == mapped_type,
        )
    )
    if existing:
        raise HTTPException(400, "A period with that year, month, and type already exists.")

    period = Period(
        year=year,
        month=month,
        type=mapped_type,
        deadline=deadline_date,
        is_open=True,
    )
    db.add(period)
    db.commit()
    db.refresh(period)
    return {"ok": True, "period": serialize_period_row(period)}


@app.post("/finance/periods/{period_id}/toggle")
def finance_toggle_period(period_id: int, request: Request, db: Session = Depends(get_db)):
    require_finance(request)
    period = db.get(Period, period_id)
    if not period:
        raise HTTPException(404, "Period not found")
    period.is_open = not period.is_open
    db.commit()
    return {"ok": True, "period_id": period.id, "is_open": period.is_open}


@app.post("/finance/reconciliation/import")
async def finance_import_statement_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    finance_user = require_finance(request)
    if not file.filename:
        raise HTTPException(400, "No file selected.")
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Upload a .csv statement file.")

    data = await file.read()
    parsed_rows, errors = parse_statement_csv(data)
    if not parsed_rows:
        detail = errors[0] if errors else "No rows imported."
        raise HTTPException(400, detail)

    created = 0
    for row in parsed_rows:
        db.add(
            StatementLine(
                year=row["year"],
                month=row["month"],
                posted_date=row["posted_date"],
                cardholder_name=row["cardholder_name"],
                merchant=row["merchant"],
                amount=row["amount"],
                currency=row["currency"],
            )
        )
        created += 1
    db.commit()
    log(
        db,
        finance_user.id,
        "statement.import",
        f"rows={created};filename={file.filename[:120]}",
    )
    return {"ok": True, "imported": created, "warnings": errors[:20]}


@app.post("/finance/reconciliation/statement-lines/{statement_line_id}/match")
def finance_reconciliation_match(
    statement_line_id: int,
    request: Request,
    claim_line_id: int = Form(...),
    db: Session = Depends(get_db),
):
    finance_user = require_finance(request)
    statement_line = db.get(StatementLine, statement_line_id)
    if not statement_line:
        raise HTTPException(404, "Statement line not found")

    claim_line = db.get(ClaimLine, claim_line_id)
    if not claim_line:
        raise HTTPException(404, "Claim line not found")
    if claim_line.claim.type != ClaimType.card:
        raise HTTPException(400, "Only card claim lines can be matched to statement lines")

    if statement_line.claim_line_id and statement_line.claim_line_id != claim_line.id:
        raise HTTPException(400, "Statement line is already matched to another claim line")

    if claim_line.statement_line and claim_line.statement_line.id != statement_line.id:
        raise HTTPException(400, "Claim line is already matched to another statement line")

    statement_line.claim_line_id = claim_line.id
    db.commit()
    log(
        db,
        finance_user.id,
        "reconciliation.match",
        f"statement_line_id={statement_line.id};claim_line_id={claim_line.id};claim_id={claim_line.claim_id}",
    )
    return {"ok": True, "statement_line_id": statement_line.id, "claim_line_id": claim_line.id}


@app.get("/finance/exports/lines.csv")
def finance_export_csv(
    request: Request,
    period: str = Query("all"),
    claim_type: str = Query("all", alias="type"),
    status: str = Query("all"),
    db: Session = Depends(get_db),
):
    require_finance(request)
    q = select(Claim).order_by(Claim.id.desc())
    q = apply_claim_filters(q, period=period, claim_type=claim_type, status=status)
    claims = db.scalars(q).all()
    rows = build_finance_export_rows(db, claims)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(FINANCE_EXPORT_HEADERS)
    writer.writerows(rows)
    data = out.getvalue()
    out.close()

    filename = f"finance-lines-{period}-{claim_type}-{status}.csv".replace("/", "-")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=data, media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/finance/exports/lines.xlsx")
def finance_export_xlsx(
    request: Request,
    period: str = Query("all"),
    claim_type: str = Query("all", alias="type"),
    status: str = Query("all"),
    db: Session = Depends(get_db),
):
    require_finance(request)
    q = select(Claim).order_by(Claim.id.desc())
    q = apply_claim_filters(q, period=period, claim_type=claim_type, status=status)
    claims = db.scalars(q).all()
    rows = build_finance_export_rows(db, claims)

    wb = Workbook()
    ws = wb.active
    ws.title = "finance_lines"
    ws.append(FINANCE_EXPORT_HEADERS)
    for row in rows:
        ws.append(row)

    stream = io.BytesIO()
    wb.save(stream)
    payload = stream.getvalue()
    stream.close()

    filename = f"finance-lines-{period}-{claim_type}-{status}.xlsx".replace("/", "-")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@app.get("/finance/exports/lines.pdf")
def finance_export_pdf(
    request: Request,
    period: str = Query("all"),
    claim_type: str = Query("all", alias="type"),
    status: str = Query("all"),
    db: Session = Depends(get_db),
):
    require_finance(request)
    q = select(Claim).order_by(Claim.id.desc())
    q = apply_claim_filters(q, period=period, claim_type=claim_type, status=status)
    claims = db.scalars(q).all()
    rows = build_finance_export_rows(db, claims)
    subtitle = f"Period: {period} · Type: {claim_type} · Status: {status} · Rows: {len(rows)}"
    payload = build_period_export_pdf(
        FINANCE_EXPORT_HEADERS,
        rows,
        title="Aimia expense export",
        subtitle=subtitle,
    )
    filename = f"finance-lines-{period}-{claim_type}-{status}.pdf".replace("/", "-")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=bytes(payload), media_type="application/pdf", headers=headers)


@app.get("/finance/exports/claims/{claim_id}.pdf")
def finance_export_claim_pdf(claim_id: int, request: Request, db: Session = Depends(get_db)):
    require_finance(request)
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")
    record = serialize_claim_record(db, claim)
    payload = build_claim_export_pdf(record)
    ref = (record.get("ref") or f"claim-{claim_id}").replace("/", "-")
    filename = f"claim-{ref}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=bytes(payload), media_type="application/pdf", headers=headers)


@app.post("/finance/claims/{claim_id}/process")
def finance_process_claim(claim_id: int, request: Request, db: Session = Depends(get_db)):
    finance_user = require_finance(request)
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")
    if claim.status != ClaimStatus.approved:
        raise HTTPException(400, "Only approved claims can be processed")

    claim.status = ClaimStatus.processed
    db.commit()
    log(db, finance_user.id, "claim.process", f"claim_id={claim.id}")
    db.refresh(claim)
    try:
        notify_claimant_processed(db, claim, finance_user)
    except Exception:
        pass
    return {"ok": True, "claim_id": claim.id, "status": claim.status.value}
