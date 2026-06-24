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

1. **Python 3.11 - 3.13** — https://www.python.org/downloads/
   - Python 3.14 is not supported by this project yet because pinned
     dependencies (notably Pillow) are not guaranteed to have Windows wheels.
2. **Tesseract OCR for Windows** — https://github.com/UB-Mannheim/tesseract/wiki
   Install it, then note the path (usually
   `C:\Program Files\Tesseract-OCR\tesseract.exe`) and put it in `.env`.
3. A database. PostgreSQL if you have it; otherwise SQLite is used
   automatically (no install needed).

## Setup

```powershell
cd expense-app
.\scripts\setup-dev.ps1     # uses Python 3.13 by default
# edit .env — at minimum set DEV_LOGIN=1 to try it without Azure
.\scripts\run-dev.ps1
```

For LAN access from other PCs on the same network:

```powershell
.\scripts\run-dev.ps1 -Lan
```

If you need to choose a different supported interpreter:

```powershell
.\scripts\setup-dev.ps1 -PythonVersion 3.11
```

## Smoke tests (P1-03)

Run the endpoint smoke suite:

```powershell
.\scripts\run-smoke-tests.ps1
```

CI smoke gate:

- GitHub Actions workflow: `.github/workflows/smoke-tests.yml`
- Runs on every push and pull request
- Executes the same smoke suite via `python -m unittest discover -s tests -p "test_*.py" -v`

## Operations runbook (P2-02)

For support/debug/recovery procedures, see:

- `OPERATIONS_RUNBOOK.md`
- `DEPLOYMENT_CHECKLIST.md`
- `UAT_SCRIPT_PACK.md`
- `RELEASE_READINESS_SUMMARY.md`

## Finance exports (P2-06)

Finance-only export endpoints (live DB data):

- `GET /finance/exports/lines.csv`
- `GET /finance/exports/lines.xlsx`

Supported query filters (applied consistently across both formats):

- `period`: `all` or `YYYY-MM` (example `2026-06`)
- `type`: `all`, `cash`, `card`
- `status`: `all`, `draft`, `submitted`, `approved`, `rejected`, `processed`

Export columns:

- `date`
- `claimant`
- `reference`
- `type`
- `period`
- `status`
- `detail`
- `category`
- `receipt_ref`
- `net_gbp`
- `vat_gbp`
- `gross_gbp`

## Reconciliation scaffold (P2-07)

Finance reconciliation UI:

- `GET /finance/reconciliation`

Finance reconciliation APIs:

- `GET /finance/reconciliation/data` (statuses: `matched`, `unmatched_statement`, `missing_statement`)
- `POST /finance/reconciliation/statement-lines/{statement_line_id}/match`

## One-click background start (Windows)

After initial setup, you can launch the app hidden in the background:

1. Double-click `Start Expense App.vbs`
2. Open `http://localhost:8000` on this machine
3. On another PC (same network), open `http://<this-pc-local-ip>:8000`

To stop it:
- Use Task Manager, or
- Double-click `Stop Expense App.vbs`

If LAN clients cannot connect, allow inbound TCP `8000` in Windows Firewall.

### Create a desktop icon

1. Right-click `Start Expense App.vbs`
2. Click **Send to > Desktop (create shortcut)**
3. Rename the shortcut (for example, `Aimia Expenses`)

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
