# Release Readiness Summary

Date: 2026-06-26  
Scope: Expense App pilot readiness snapshot

## 1) Current Status

- Phase 1 board: complete
- Phase 2 board: complete
- Phase 3 board: complete except `P3-04` (Azure AD production auth)
- Post-board workflow items `W-01` (reject → edit → resubmit) and `W-02` (per-line manager comments): complete
- Phase 2.5 (JJ feedback): finance line re-coding, Sales WFH (Payroll), category GL codes, **inline re-coding on finance processing page** — complete
- Test suite: **29 tests** (21 smoke + 8 Phase 2.5), passing
- CI smoke gate: configured on push + PR
- Ops/UAT docs: present
- Pilot-ready on `DEV_LOGIN=1`; production M365 login pending `P3-04`

## 2) What Is Ready

### Claimant
- Claim capture flow (create, edit, validate, submit)
- Receipt upload with OCR suggestions + confidence hint
- Duplicate receipt warning guardrails (non-blocking)
- Rejected claims editable with resubmit (manager feedback banner + timeline)
- Days working from home (Sales team, cash claims only — excluded from claim total; paid via Payroll)

### Manager
- Approval queue with receipt preview
- Per-line comment fields (aggregate into rejection reason)
- Approve/reject with required rejection comment(s)
- Nav badge for pending approval count

### Finance
- Processing flow (approved queue + process)
- Line re-coding on processing queue (editable detail + category per line, **Save coding**)
- Category GL/nominal codes admin + `gl_code` on exports
- Period open/close management
- Exports: CSV, XLSX, PDF (filtered)
- Reconciliation: CSV import, manual match, auto-match suggestions
- Nav badge for approved queue count

### Admin / platform
- Roles & privileges UI (`/admin/users`)
- Email notifications (SMTP optional; log-only fallback)
- Audit timeline on claims
- Role-aware navigation and access-denied UX
- Backup script (`scripts/backup.ps1`)
- Agency team workflow (`.cursor/rules/agency-team.mdc`, `AGENCY_TEAM.md`)

## 3) Pilot Day Commands

From project root:

```powershell
cd "C:\Users\Michaelm1\Documents\AI-Projects\expense-app"
```

### Start app (hidden, LAN)

```powershell
.\scripts\start-hidden.ps1 -Lan
```

### Verify app health

```powershell
(Invoke-WebRequest -UseBasicParsing http://localhost:8000).StatusCode
netstat -ano | rg "8000"
```

### Run smoke suite

```powershell
.\scripts\run-smoke-tests.ps1
```

### Backup before pilot

```powershell
.\scripts\backup.ps1
```

### Stop app

```powershell
.\scripts\stop-hidden.ps1
```

## 4) Pilot Go/No-Go Checks

- [x] Smoke tests green (29 tests)
- [x] Role checks validated (claimant, manager, finance, admin)
- [x] Exports open correctly (CSV + XLSX + PDF)
- [x] Reconciliation page loads and match action works
- [x] Audit timeline visible for tested claims
- [x] Reject → edit → resubmit flow validated
- [x] Per-line manager rejection comments validated
- [ ] Backup created for DB (`data/expenses.db`) — run `.\scripts\backup.ps1` before go-live
- [ ] Azure AD login validated (`P3-04`) — **last item before production**; required before `DEV_LOGIN=0`

## 5) Key Documents

- `PROJECT_PROGRESS_TRACKER.md`
- `PHASE1_TASK_BOARD.md`
- `PHASE2_TASK_BOARD.md`
- `PHASE3_TASK_BOARD.md`
- `PHASE4_TASK_BOARD.md`
- `OPERATIONS_RUNBOOK.md`
- `DEPLOYMENT_CHECKLIST.md`
- `UAT_SCRIPT_PACK.md`
- `ROLES_PRIVILEGES.md`
- `P0-06_QA_SIGNOFF.md`
- `P2-05_QA_SIGNOFF.md`

## 6) Pending (Not Blocking Dev-Login Pilot)

| Item | Priority |
|---|---|
| **`P3-04` Azure AD production auth** | **Last — required for production** |
| **Phase 4 mileage** (P4-01–P4-04) | Pending — see `PHASE4_TASK_BOARD.md` |
| Pre-pilot backup verification | Recommended before go-live |
