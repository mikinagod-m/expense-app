# Expense App - Phase 3 Task Board

Phase 3 moves the pilot-ready app into **production operations**: notifications, statement ingestion, period governance, and deployment hardening.

## Priority Scale
- `P0`: must-have for real pilot/production use
- `P1`: high-value operational improvements
- `P2`: polish and efficiency

## Board

| ID | Priority | Task | Owner Role | Status | Depends On |
|---|---|---|---|---|---|
| P3-01 | P0 | Email notifications (submit → manager, decision → claimant) | Backend Engineer | Done | - |
| P3-02 | P0 | Statement CSV import for card reconciliation | Backend + Frontend Engineer | Done | - |
| P3-03 | P0 | Finance period management (open/close claim windows) | Backend + Frontend Engineer | Done | - |
| P3-04 | P1 | Azure AD production auth validation + login UX | Backend Engineer + Security Reviewer | Pending | - |
| P3-05 | P1 | Reconciliation auto-match suggestions | Backend Engineer | Done | P3-02 |
| RP-01 | P0 | Roles & privileges admin UI | Backend + Frontend Engineer | Done | - |
| P3-06 | P1 | Scheduled DB + receipts backup script | DevOps Engineer | Done | - |
| P3-07 | P2 | PDF claim/period export for finance archive | Backend Engineer | Done | - |
| P3-08 | P2 | Nav badge counts for pending approvals | Frontend Engineer | Done | P3-01 |
| W-01 | P0 | Rejected-claim edit + resubmit for claimants | Backend + Frontend Engineer | Done | P2-11 |
| W-02 | P0 | Per-line manager approval comments | Frontend Engineer | Done | P2-11 |

## Post-board workflow (2026-06-26)

| ID | Task | Status |
|---|---|---|
| W-01 | Claimants edit rejected claims and resubmit; rejection banner + backend edit guards | Done |
| W-02 | Manager approvals: comment field per line item; aggregated rejection feedback | Done |

## Task Details and Acceptance Criteria

### P3-01 - Email notifications
**Acceptance Criteria:**
- On claim submit, manager receives notification (email when SMTP configured, audit log otherwise).
- On approve/reject/process, claimant receives notification with approver name where relevant.
- SMTP is optional; dev mode logs notifications without failing the workflow.

### P3-02 - Statement CSV import
**Acceptance Criteria:**
- Finance can upload a CSV of card statement lines for a given period.
- Rows appear in reconciliation view as unmatched statement lines.
- Import validates required columns and reports row count/errors.

### P3-03 - Finance period management
**Acceptance Criteria:**
- Finance can view all periods and open/close them.
- Closed periods cannot accept new claims (existing guardrails enforced).
- Open periods appear in claimant nav immediately after change.

### P3-04 - Azure AD production readiness
**Acceptance Criteria:**
- `DEV_LOGIN=0` login flow documented and smoke-tested against configured tenant.
- Missing/misconfigured Azure env vars produce clear operator guidance.

### P3-05 - Reconciliation auto-match suggestions
**Acceptance Criteria:**
- Unmatched statement lines show suggested claim_line_id matches by date+amount.
- Finance can accept suggestion in one click.

### RP-01 - Roles & privileges
**Acceptance Criteria:**
- Admin can list users and edit manager, finance, admin, card, and cash flags.
- Non-admins receive `403` on admin routes.
- Cash/card period visibility and claim creation respect entitlements.
- See `ROLES_PRIVILEGES.md` for the role model.

### P3-06 - Scheduled DB + receipts backup
**Acceptance Criteria:**
- `.\scripts\backup.ps1` copies SQLite DB and receipts into timestamped folders.
- Retention prunes backups older than `BACKUP_RETENTION_DAYS`.
- Runbook documents Task Scheduler setup.

### P3-07 - PDF finance archive export
**Acceptance Criteria:**
- Finance can download filtered period export as PDF.
- Finance can download a single claim PDF for filing.

### P3-08 - Nav badge counts
**Acceptance Criteria:**
- Managers see pending approval count on Approvals nav.
- Finance sees approved queue count on Processing nav.

### W-01 - Rejected-claim edit and resubmit
**Acceptance Criteria:**
- Claimants can edit lines and receipts on `rejected` claims.
- Rejection reason visible while editing; resubmit returns claim to `submitted`.
- Submitted/approved/processed claims cannot be edited by claimant.

### W-02 - Per-line manager approval comments
**Acceptance Criteria:**
- Each line in the manager approvals queue has its own comment field.
- Reject requires at least one line comment; comments aggregate into claimant feedback.
- Approve/reject remains at claim level.

## Suggested Execution Plan

1. Ship operational core (`P3-01`, `P3-02`, `P3-03`).
2. Harden production auth (`P3-04`).
3. Improve reconciliation efficiency (`P3-05`).
4. Add backup/export polish (`P3-06`, `P3-07`).

## Ship Gate for Phase 3

Phase 3 pilot-ready when P0 items are done, notifications do not block claim workflow, and finance can import statements + manage periods without DB edits.

**Status (2026-06-26):** Ship gate met for `DEV_LOGIN=1` pilot. Remaining for production: `P3-04` Azure AD.
