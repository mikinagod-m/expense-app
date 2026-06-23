import datetime as dt
import os
import uuid

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, engine
from .models import (Base, User, Period, Claim, ClaimLine, Receipt, AuditLog,
                     ClaimType, ClaimStatus, Category)
from .auth import current_user, require_user
from .ocr import parse_receipt

Base.metadata.create_all(engine)

app = FastAPI(title="Aimia Expense App")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
os.makedirs(settings.receipts_dir, exist_ok=True)


def log(db: Session, user_id, action, detail=""):
    db.add(AuditLog(user_id=user_id, action=action, detail=detail))
    db.commit()


# ---------------- Auth ----------------
@app.get("/login")
async def login(request: Request):
    if settings.dev_login:
        with next(get_db()) as db:
            user = db.scalar(select(User).order_by(User.id))
            if user:
                request.session["uid"] = user.id
        return RedirectResponse("/", status_code=302)
    oauth = request.app.state.oauth
    return await oauth.aad.authorize_redirect(request, settings.aad_redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    from .auth import upsert_user_from_claims
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
    app.state.oauth = build_oauth()


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
    return templates.TemplateResponse(request, "home.html", {
        "user": user, "claims": claims, "open_periods": open_periods,
    })


# ---------------- Claims ----------------
@app.post("/claims/new")
def new_claim(request: Request, period_id: int = Form(...),
              db: Session = Depends(get_db)):
    user = require_user(request)
    period = db.get(Period, period_id)
    if not period or not period.is_open:
        raise HTTPException(400, "Period not open")
    claim = Claim(user_id=user.id, period_id=period.id, type=period.type)
    db.add(claim)
    db.commit()
    log(db, user.id, "claim.create", f"claim {claim.id} period {period.id}")
    return RedirectResponse(f"/claims/{claim.id}", status_code=302)


@app.get("/claims/{claim_id}", response_class=HTMLResponse)
def view_claim(claim_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    claim = db.get(Claim, claim_id)
    if not claim or claim.user_id != user.id:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "claim.html", {
        "user": user, "claim": claim, "categories": list(Category),
    })


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
    line.date = dt.date.fromisoformat(date) if date else None
    line.narrative = narrative
    line.receipt_ref = receipt_ref
    line.category = Category(category)
    line.amount = amount
    line.reclaim_vat = reclaim_vat
    db.commit()
    return {"ok": True, "gross_total": line.claim.gross_total}


@app.post("/lines/{line_id}/receipt")
async def upload_receipt(line_id: int, request: Request,
                         file: UploadFile = File(...),
                         db: Session = Depends(get_db)):
    """Upload a receipt, run local OCR, return pre-filled fields for confirmation."""
    user = require_user(request)
    line = db.get(ClaimLine, line_id)
    if not line or line.claim.user_id != user.id:
        raise HTTPException(404)

    data = await file.read()
    ext = os.path.splitext(file.filename)[1] or ".bin"
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.receipts_dir, fname)
    with open(path, "wb") as f:
        f.write(data)

    parsed = parse_receipt(data, file.filename)
    receipt = line.receipt or Receipt(claim_line_id=line.id)
    receipt.file_path = path
    receipt.ocr_date = parsed.get("ocr_date")
    receipt.ocr_merchant = parsed.get("ocr_merchant")
    receipt.ocr_amount = parsed.get("ocr_amount")
    db.add(receipt)
    db.commit()
    log(db, user.id, "receipt.upload", f"line {line.id}")

    # The UI uses these to pre-fill the row; the user confirms before saving.
    return {
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
    claim.signed_at = dt.datetime.utcnow()
    claim.submitted_at = dt.datetime.utcnow()
    # Unique ref = period + zero-padded claim id (replaces the VBA number).
    claim.unique_ref = f"{claim.period.year}{claim.period.month:02d}{claim.id:04d}"
    db.commit()
    log(db, user.id, "claim.submit", claim.unique_ref)
    # TODO Phase 2: notify manager (claim.user.manager) for approval.
    return {"ok": True, "ref": claim.unique_ref}
