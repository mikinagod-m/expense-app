# Deployment Checklist (Phase 2+ / Pilot)

Use this checklist before promoting `expense-app` to pilot users.

Last reviewed: 2026-06-26

## 1) Pre-Deploy Readiness

- [ ] `PHASE1_TASK_BOARD.md`, `PHASE2_TASK_BOARD.md`, and `PHASE3_TASK_BOARD.md` target items marked done (except `P3-04` if still on dev login).
- [ ] `PROJECT_PROGRESS_TRACKER.md` updated with current release scope.
- [ ] CI smoke workflow green on latest commit (`Smoke Tests`).
- [ ] Local smoke run passes (21 tests):
  - [ ] `python -m unittest discover -s tests -p "test_*.py" -v`

## 2) Environment and Config

- [ ] Python version is supported (`3.11`-`3.13`).
- [ ] Virtual environment is healthy:
  - [ ] `.\scripts\setup-dev.ps1` completed without errors.
- [ ] `.env` values verified:
  - [ ] `DEV_LOGIN` intentionally set for target environment
  - [ ] `DATABASE_URL` points to intended DB
  - [ ] `RECEIPTS_DIR` exists and is writable
  - [ ] `RECEIPT_MAX_BYTES` set to approved limit
  - [ ] Azure values set if `DEV_LOGIN=0`:
    - [ ] `AAD_TENANT_ID`
    - [ ] `AAD_CLIENT_ID`
    - [ ] `AAD_CLIENT_SECRET`
    - [ ] `AAD_REDIRECT_URI`

## 3) Data and Backup

- [ ] Backup created for DB file (or DB snapshot if external DB).
- [ ] If demo reset is intended, reset executed intentionally and documented.
- [ ] Historical receipts folder retained or archived per policy.

## 4) Runtime and Access

- [ ] Start mode chosen and documented:
  - [ ] Hidden background mode (`.\scripts\start-hidden.ps1 -Lan`)
  - [ ] Foreground mode (`.\scripts\run-dev.ps1 -Lan`)
- [ ] Health check returns `200`:
  - [ ] `Invoke-WebRequest http://localhost:8000`
- [ ] LAN access validated from second machine:
  - [ ] `http://<host-local-ip>:8000`
- [ ] Windows firewall inbound rule for TCP 8000 confirmed.

## 5) Security and Roles

- [ ] Non-privileged user cannot access manager/finance routes.
- [ ] Manager can review direct-report claims only.
- [ ] Finance can process approved claims and access exports/reconciliation.
- [ ] Access-denied pages show clear user guidance.

## 6) Functional Smoke (Pilot Critical)

- [ ] Claimant flow:
  - [ ] create claim
  - [ ] add/edit line
  - [ ] upload receipt
  - [ ] submit claim
- [ ] Manager flow:
  - [ ] view pending queue
  - [ ] approve claim
  - [ ] reject claim (per-line comment on at least one line)
  - [ ] verify aggregated rejection reason reaches claimant
- [ ] Claimant reject/resubmit flow:
  - [ ] open rejected claim — lines editable, rejection banner visible
  - [ ] edit line(s) and resubmit
  - [ ] claim returns to manager pending queue
- [ ] Finance flow:
  - [ ] view approved queue
  - [ ] mark processed
  - [ ] export CSV
  - [ ] export XLSX
  - [ ] export PDF (optional)
  - [ ] open reconciliation page and execute manual match
  - [ ] run backup script (`.\scripts\backup.ps1`)

## 7) Audit and Observability

- [ ] Claim history/audit timeline visible for tested claim.
- [ ] Required actions present in audit:
  - [ ] `claim.submit`
  - [ ] `claim.approve` / `claim.reject`
  - [ ] `claim.process`
  - [ ] `reconciliation.match` (if reconciliation tested)
- [ ] `.runtime\uvicorn.err.log` reviewed for errors.

## 8) Rollback Plan

- [ ] Rollback owner assigned.
- [ ] Rollback command path tested:
  - [ ] stop app (`.\scripts\stop-hidden.ps1` or Task Manager)
  - [ ] restore DB backup / snapshot
  - [ ] restart app
- [ ] Rollback decision threshold defined (e.g., auth failures, data corruption, major role bug).

## 9) Go/No-Go Sign-Off

- [ ] Product Lead sign-off
- [ ] QA sign-off
- [ ] Security/Role controls sign-off
- [ ] Operations readiness sign-off

Release Decision:

- [ ] GO
- [ ] NO-GO

Date:
Owner:
Notes:
