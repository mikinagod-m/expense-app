# Expense App - Phase 1 Task Board

This board is aligned to the agency team in `AGENCY_TEAM.md` and focused on Phase 1 outcomes: fast, reliable expense capture and receipt OCR-assisted data entry.

## Priority Scale
- `P0`: must ship for safe pilot use
- `P1`: high impact, can follow immediately after P0
- `P2`: nice-to-have polish

## Board

| ID | Priority | Task | Owner Role | Status | Depends On |
|---|---|---|---|---|---|
| P0-01 | P0 | Stabilize local/dev auth and Azure toggle behavior (`DEV_LOGIN`) | Backend Engineer | Done | - |
| P0-02 | P0 | Enforce claim period validation and prevent invalid claim creation | Backend Engineer | Done | P0-01 |
| P0-03 | P0 | Harden claim line validation (date/amount/category required rules) | Backend Engineer | Done | P0-02 |
| P0-04 | P0 | Improve receipt upload reliability and OCR fallback messaging | Backend + Frontend Engineer | Done | P0-03 |
| P0-05 | P0 | Verify audit log events for create/update/upload actions | Security Reviewer + Backend Engineer | Done | P0-04 |
| P0-06 | P0 | End-to-end manual QA pass for critical flow | QA Engineer | Done | P0-05 |
| P1-01 | P1 | Add duplicate receipt guardrails (name/hash/date-amount heuristic) | Backend Engineer | Done | P0-04 |
| P1-02 | P1 | Improve HTMX UX for line item entry (fewer clicks, clearer errors) | Frontend Engineer | Done | P0-03 |
| P1-03 | P1 | Add smoke tests for claim + receipt endpoints | QA Engineer + Backend Engineer | Done | P0-06 |
| P1-04 | P1 | Add basic role/permission checks for manager/admin routes | Security Reviewer + Backend Engineer | Done | P0-01 |
| P2-01 | P2 | Add in-app OCR confidence hint to guide user confirmation | Frontend Engineer | Done | P1-02 |
| P2-02 | P2 | Add operational runbook for support/debug on Windows server | Product Lead + QA Engineer | Done | P1-03 |

## Task Details and Acceptance Criteria

### P0-01 - Auth mode stability
**Owner:** Backend Engineer  
**Acceptance Criteria:**
- `DEV_LOGIN=1` logs into a deterministic demo identity without Azure calls.
- `DEV_LOGIN=0` follows Azure OIDC flow and fails gracefully if env vars are missing.
- Login/logout paths do not leave inconsistent session state.

### P0-02 - Claim period integrity
**Owner:** Backend Engineer  
**Acceptance Criteria:**
- Claim cannot be created outside valid period boundaries.
- Invalid period submissions return clear user-facing error messages.
- Existing valid claim creation behavior remains unchanged.

### P0-03 - Claim line validation hardening
**Owner:** Backend Engineer  
**Acceptance Criteria:**
- Invalid amount/date/category input is rejected consistently server-side.
- Validation errors are surfaced in HTMX responses without full page failure.
- Data saved in `claim_lines` is normalized and query-safe.

### P0-04 - Receipt upload + OCR resilience
**Owner:** Backend + Frontend Engineer  
**Acceptance Criteria:**
- Unsupported file types and oversized files are rejected with actionable feedback.
- OCR failures do not block submission; user can still enter fields manually.
- Upload success/failure states are visible and recoverable from the claim screen.

### P0-05 - Audit log verification
**Owner:** Security Reviewer + Backend Engineer  
**Acceptance Criteria:**
- Create claim, update claim line, upload receipt each produce audit events.
- Audit entries include actor, action, target, and timestamp.
- No sensitive secrets are leaked into audit payloads.

### P0-06 - Critical path QA sign-off
**Owner:** QA Engineer  
**Acceptance Criteria:**
- QA checklist executed for create claim -> add lines -> upload receipt -> OCR confirm.
- Negative test cases executed (bad file, bad amount/date, unauthorized access path).
- Sign-off report includes pass/fail and reproducible steps for failures.

## Suggested Execution Plan (Agency Flow)

1. Product Lead confirms exact pilot scope and marks non-goals.
2. Backend Engineer executes `P0-01` to `P0-03`.
3. Frontend + Backend pair on `P0-04`.
4. Security Reviewer validates `P0-05`.
5. QA Engineer runs `P0-06` and reports release readiness.
6. Move immediately to P1 items if P0 passes without blockers.

## Standup Template (Copy/Paste)

- Yesterday: completed tasks and test outcomes
- Today: task IDs in progress
- Blockers: dependency or environment issues
- Risk: potential release risk and mitigation owner

## Ship Gate for Phase 1

Phase 1 is ship-ready only when all P0 tasks are marked `Done`, QA sign-off is complete, and no open high-severity security or data-integrity issues remain.
