# Aimia Expense App

Internal web app to replace the manual cash + credit-card expense process.
FastAPI + HTMX + SQLAlchemy. Runs behind your VPN on the Windows server.

## What this v1 skeleton includes

- **Auth**: Microsoft 365 / Azure AD login (OIDC). Stubbed so you can run
  locally without Azure first — set `DEV_LOGIN=1` to skip real auth.
- **Data model**: users, periods, claims, claim_lines, receipts, audit_log
  (SQLAlchemy). Monthly rollover disappears — claims belong to a period.
- **Receipt capture + OCR**: upload a receipt, Tesseract pre-fills
  date/merchant/amount for the user to confirm. Fully local, nothing leaves
  the VPN.
- **HTMX UI**: server-rendered, no build step.

This is Phase 1 (capture / data entry — your #1 pain). Approvals,
reconciliation, and Excel export are stubbed as TODOs for later phases.

## Prerequisites (Windows server)

1. **Python 3.11+** — https://www.python.org/downloads/
2. **Tesseract OCR for Windows** — https://github.com/UB-Mannheim/tesseract/wiki
   Install it, then note the path (usually
   `C:\Program Files\Tesseract-OCR\tesseract.exe`) and put it in `.env`.
3. A database. PostgreSQL if you have it; otherwise SQLite is used
   automatically (no install needed).

## Setup

```powershell
cd expense-app
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# edit .env — at minimum set DEV_LOGIN=1 to try it without Azure
python -m app.seed          # creates tables + a few demo users/periods
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 — with `DEV_LOGIN=1` you'll be logged in as a
demo user and can create a claim, add lines, and upload a receipt to see
OCR pre-fill in action.

## Switching from SQLite to PostgreSQL later

Change `DATABASE_URL` in `.env`. Nothing else changes — SQLAlchemy handles it.

## Wiring up real Azure AD login

1. Register an app in Azure Portal → App registrations.
2. Redirect URI: `https://<your-vpn-host>/auth/callback`
3. Put CLIENT_ID / CLIENT_SECRET / TENANT_ID in `.env`, set `DEV_LOGIN=0`.
4. The callback already maps the AAD profile (name, email, manager) onto the
   `users` table — replacing the old "Employee Database" tab.
