# Release Readiness Summary

Date: 2026-06-24  
Scope: Expense App pilot readiness snapshot

## 1) Current Status

- Phase 1 board: complete
- Phase 2 board: complete
- Smoke suite: passing
- CI smoke gate: configured on push + PR
- Ops/UAT docs: present

## 2) What Is Ready

- Claim capture flow (create, edit, validate, submit)
- Receipt upload with OCR suggestions + confidence hint
- Duplicate receipt warning guardrails (non-blocking)
- Manager approval flow (queue + approve/reject)
- Finance processing flow (approved queue + process)
- Audit timeline visibility on claims
- Finance exports (CSV/XLSX) with shared filters
- Reconciliation scaffold (matched/unmatched/missing + manual match)
- Role-aware navigation and access-denied UX

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

### Stop app

```powershell
.\scripts\stop-hidden.ps1
```

## 4) Pilot Go/No-Go Checks

- [ ] Smoke tests green
- [ ] LAN access verified from second machine
- [ ] Role checks validated (claimant, manager, finance)
- [ ] Exports open correctly (CSV + XLSX)
- [ ] Reconciliation page loads and match action works
- [ ] Audit timeline visible for tested claims
- [ ] Backup created for DB (`data/expenses.db`)

## 5) Key Documents

- `PROJECT_PROGRESS_TRACKER.md`
- `PHASE1_TASK_BOARD.md`
- `PHASE2_TASK_BOARD.md`
- `OPERATIONS_RUNBOOK.md`
- `DEPLOYMENT_CHECKLIST.md`
- `UAT_SCRIPT_PACK.md`
- `P0-06_QA_SIGNOFF.md`
- `P2-05_QA_SIGNOFF.md`

## 6) Optional Follow-Ups (Not Blocking Pilot)

- Add branch protection rule requiring `Smoke Tests` status
- Add richer reconciliation auto-suggestions
- Add UI polish for audit timeline and manager/finance detail views
