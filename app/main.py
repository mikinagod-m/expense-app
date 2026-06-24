import datetime as dt
import csv
import hashlib
import io
import math
import os
import uuid

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, engine
from .models import (Base, User, Period, Claim, ClaimLine, Receipt, AuditLog,
                     ClaimType, ClaimStatus, Category, StatementLine, utc_now)
from .auth import (
    current_user,
    require_user,
    require_manager_or_finance,
    require_finance,
    user_is_manager,
)
from .ocr import parse_receipt

Base.metadata.create_all(engine)

app = FastAPI(title="Aimia Expense App")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
os.makedirs(settings.receipts_dir, exist_ok=True)
app.state.auth_init_error = None
ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".webp"}


def log(db: Session, user_id, action, detail=""):
    # Keep audit detail compact and non-sensitive (IDs and state only).
    safe_detail = (detail or "")[:500]
    db.add(AuditLog(user_id=user_id, action=action, detail=safe_detail))
    db.commit()


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
    events = []
    for r in rows:
        actor = db.get(User, r.user_id) if r.user_id else None
        events.append(
            {
                "id": r.id,
                "at": r.at.isoformat() if r.at else "",
                "action": r.action,
                "detail": r.detail or "",
                "actor_name": actor.name if actor else "System",
                "actor_id": r.user_id,
            }
        )
    return events


def nav_flags(db: Session, user: User) -> dict:
    is_manager = user_is_manager(db, user)
    return {
        "nav_can_manager": is_manager or user.is_finance,
        "nav_can_finance": user.is_finance,
    }


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


def build_finance_export_rows(claims: list[Claim]) -> list[list]:
    rows: list[list] = []
    for c in claims:
        period_label = f"{c.period.month:02d}/{c.period.year}"
        for line in c.lines:
            gross = round(float(line.amount or 0.0), 2)
            vat = round(float(line.vat_amount or 0.0), 2)
            net = round(gross - vat, 2)
            rows.append(
                [
                    line.date.isoformat() if line.date else "",
                    c.user.name,
                    c.unique_ref or "",
                    c.type.value,
                    period_label,
                    c.status.value,
                    line.narrative or "",
                    line.category.value if line.category else "",
                    line.receipt_ref or "",
                    net,
                    vat,
                    gross,
                ]
            )
    return rows


FINANCE_EXPORT_HEADERS = [
    "date",
    "claimant",
    "reference",
    "type",
    "period",
    "status",
    "detail",
    "category",
    "receipt_ref",
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
async def login(request: Request):
    if settings.dev_login:
        with next(get_db()) as db:
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


# ---------------- Dashboard ----------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    claims = db.scalars(
        select(Claim).where(Claim.user_id == user.id).order_by(Claim.id.desc())
    ).all()
    open_periods = db.scalars(select(Period).where(Period.is_open == True)).all()  # noqa: E712
    return templates.TemplateResponse(request, "aimia-expenses.html", {
        "user": user, "claims": claims, "open_periods": open_periods,
    })


# ---------------- Manager UI ----------------
@app.get("/manager/approvals", response_class=HTMLResponse)
def manager_approvals_page(request: Request, db: Session = Depends(get_db)):
    try:
        reviewer = require_manager_or_finance(request, db)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            return templates.TemplateResponse(
                request,
                "access_denied.html",
                {
                    "user": current_user(request),
                    "title": "Manager approvals access denied",
                    "message": "You need a manager or finance role to use this page.",
                    "status_code": exc.status_code,
                },
                status_code=exc.status_code,
            )
        raise
    context = {"user": reviewer}
    context.update(nav_flags(db, reviewer))
    return templates.TemplateResponse(request, "manager_approvals.html", context)


# ---------------- Finance UI ----------------
@app.get("/finance/processing", response_class=HTMLResponse)
def finance_processing_page(request: Request, db: Session = Depends(get_db)):
    try:
        finance_user = require_finance(request)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            return templates.TemplateResponse(
                request,
                "access_denied.html",
                {
                    "user": current_user(request),
                    "title": "Finance processing access denied",
                    "message": "You need a finance role to use this page.",
                    "status_code": exc.status_code,
                },
                status_code=exc.status_code,
            )
        raise
    context = {"user": finance_user}
    context.update(nav_flags(db, finance_user))
    return templates.TemplateResponse(request, "finance_processing.html", context)


@app.get("/finance/reconciliation", response_class=HTMLResponse)
def finance_reconciliation_page(request: Request, db: Session = Depends(get_db)):
    try:
        finance_user = require_finance(request)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            return templates.TemplateResponse(
                request,
                "access_denied.html",
                {
                    "user": current_user(request),
                    "title": "Finance reconciliation access denied",
                    "message": "You need a finance role to use this page.",
                    "status_code": exc.status_code,
                },
                status_code=exc.status_code,
            )
        raise
    context = {"user": finance_user}
    context.update(nav_flags(db, finance_user))
    return templates.TemplateResponse(request, "finance_reconciliation.html", context)


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
    claim = Claim(user_id=user.id, period_id=period.id, type=period.type)
    db.add(claim)
    db.commit()
    log(db, user.id, "claim.create", f"claim_id={claim.id};period_id={period.id}")
    return RedirectResponse(f"/claims/{claim.id}", status_code=302)


@app.get("/claims/{claim_id}", response_class=HTMLResponse)
def view_claim(claim_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    claim = db.get(Claim, claim_id)
    if not claim or claim.user_id != user.id:
        raise HTTPException(404)
    events = claim_audit_events(db, claim)
    context = {
        "user": user,
        "claim": claim,
        "categories": list(Category),
        "events": events,
    }
    context.update(nav_flags(db, user))
    return templates.TemplateResponse(request, "claim.html", context)


@app.get("/claims/{claim_id}/audit")
def claim_audit(claim_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404)

    can_view = (
        claim.user_id == user.id
        or user.is_finance
        or claim.user.manager_id == user.id
    )
    if not can_view:
        raise HTTPException(403, "Not allowed to view this claim audit")

    return {"ok": True, "claim_id": claim.id, "events": claim_audit_events(db, claim)}


@app.post("/claims/{claim_id}/lines", response_class=HTMLResponse)
def add_line(claim_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    claim = db.get(Claim, claim_id)
    if not claim or claim.user_id != user.id:
        raise HTTPException(404)
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
    # TODO Phase 2: notify manager (claim.user.manager) for approval.
    return {"ok": True, "ref": claim.unique_ref}


# ---------------- Manager / Finance ----------------
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
        "claims": [
            {
                "id": c.id,
                "ref": c.unique_ref,
                "user_id": c.user_id,
                "claimant_name": c.user.name,
                "period_id": c.period_id,
                "period_label": f"{c.period.month:02d}/{c.period.year}",
                "type": c.type.value,
                "status": c.status.value,
                "gross_total": c.gross_total,
            }
            for c in claims
        ],
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
    detail = f"claim_id={claim.id};decision={normalized};comment={comment.strip()[:120]}"
    log(db, reviewer.id, action, detail)
    return {"ok": True, "claim_id": claim.id, "status": claim.status.value}


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
        "claims": [
            {
                "id": c.id,
                "ref": c.unique_ref,
                "user_id": c.user_id,
                "claimant_name": c.user.name,
                "period_id": c.period_id,
                "period_label": f"{c.period.month:02d}/{c.period.year}",
                "type": c.type.value,
                "status": c.status.value,
                "gross_total": c.gross_total,
            }
            for c in claims
        ],
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
            }
        else:
            row_status = "unmatched_statement"
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
            }
        statement_rows.append(row)

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
    rows = build_finance_export_rows(claims)

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
    rows = build_finance_export_rows(claims)

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
    return {"ok": True, "claim_id": claim.id, "status": claim.status.value}
