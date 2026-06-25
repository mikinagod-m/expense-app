# Expense App - Progress Tracker

Last updated: 2026-06-24

## Current Position

- Project foundation and local runtime workflow are in place.
- New UI shell (`aimia-expenses.html`) is now the default home page.
- Phase 1 P0 is complete: `P0-01` through `P0-06` are done and verified.
- Phase 2 planning board is created: `PHASE2_TASK_BOARD.md`.

## Completed (Done)

- [x] Agency workflow created and saved (`.cursor/rules/agency-team.mdc`, `AGENCY_TEAM.md`).
- [x] Phase 1 planning board created (`PHASE1_TASK_BOARD.md`).
- [x] Local environment fixed for supported Python versions (3.11-3.13).
- [x] One-command setup/start scripts added (`scripts/setup-dev.ps1`, `scripts/run-dev.ps1`).
- [x] Hidden background launcher added (`Start Expense App.vbs`, `scripts/start-hidden.ps1`).
- [x] Hidden stop helper added (`Stop Expense App.vbs`, `scripts/stop-hidden.ps1`).
- [x] LAN mode support added (`-Lan` switch in run/start scripts).
- [x] Main UI route switched to `aimia-expenses.html`.
- [x] Demo personal names replaced with fictional placeholders in code/templates.
- [x] Seed demo identities updated to fictional users in `app/seed.py`.
- [x] `P0-01` completed: auth mode stability for `DEV_LOGIN` and Azure toggle behavior.
  - `DEV_LOGIN=1`: deterministic local login redirect verified.
  - `DEV_LOGIN=0` with missing Azure env vars: clear `503` configuration message (no crash).
  - Callback in misconfigured Azure mode also returns clear `503`.
- [x] `P0-02` completed: claim period integrity validation and invalid-creation prevention.
  - Added explicit period guardrails for: missing period, closed period, invalid period data, future period, and expired deadline.
  - Invalid submissions now return clear user-facing HTML errors with a route back to dashboard.
  - Valid period claim creation behavior preserved (`302` redirect to claim page).
- [x] `P0-03` completed: claim line validation hardening (date/category/amount required).
  - Added server-side validation for required date/category/amount and invalid values.
  - Rejected malformed date, invalid category, non-finite amount, and non-positive amount with `400` + structured error payload.
  - Preserved valid save behavior and gross total update.
  - Added row-level error rendering in claim UI so users see validation feedback immediately.
- [x] `P0-04` completed: receipt upload reliability and OCR fallback messaging.
  - Enforced upload guardrails: allowed extensions only (`.jpg`, `.jpeg`, `.png`, `.pdf`, `.webp`), non-empty file, and max size limit (`RECEIPT_MAX_BYTES`).
  - Added actionable API responses for unsupported file type and oversize uploads.
  - Preserved manual-entry flow when OCR fails: upload succeeds with clear "OCR could not extract" guidance.
  - Improved claim UI upload feedback for success/failure and removed auto-save side effects when no OCR prefill exists.
- [x] `P0-05` completed: audit log coverage for create/update/upload actions.
  - Added explicit `claim_line.update` audit events on line saves.
  - Standardized detail payloads to non-sensitive target identifiers (e.g. `claim_id`, `line_id`, `receipt_id`) and capped detail size.
  - Verified required actions are logged for a claim flow: `claim.create`, `claim_line.update`, `receipt.upload`.
  - Verified audit actor/timestamp presence (`user_id`, `at`) and no secret-like terms in log detail payloads.
- [x] `P0-06` completed: end-to-end QA sign-off.
  - Executed critical-path checks for claim creation, line save, receipt upload/OCR fallback, and submit.
  - Executed negative-path checks for unauthorized access, invalid line input, and unsupported file upload.
  - Saved QA sign-off evidence and outcomes in `P0-06_QA_SIGNOFF.md`.
- [x] `P1-03` completed: smoke tests for claim + receipt endpoints.
  - Added `tests/test_smoke_endpoints.py` with repeatable API smoke coverage for:
    - critical claim lifecycle path
    - receipt upload path
    - key negative paths (unauthorized, invalid line input, unsupported file type)
  - Added `scripts/run-smoke-tests.ps1` for one-command execution.
  - Added README test command documentation.
- [x] `P1-01` completed: duplicate receipt guardrails.
  - Added upload-time duplicate detection using:
    - exact file hash match against existing receipts for the same user
    - OCR date+amount heuristic match
    - recent filename reuse heuristic from audit records
  - Kept behavior non-blocking (warning guardrail, not hard rejection).
  - Surfaced duplicate warnings in claim UI upload note.
  - Added automated test coverage (`test_duplicate_receipt_guardrail`) and verified smoke suite passes.
- [x] `P1-02` completed: line-entry UX improvements (fewer clicks, clearer feedback).
  - Added debounced auto-save while typing (plus immediate save on blur/change) for line fields.
  - Added per-row save state indicators: `Saving…`, `Saved`, and `Needs attention`.
  - Added row-level guidance text and auto-focus on newly added lines.
  - Added keyboard convenience: pressing `Enter` in amount field adds a new line.
  - Preserved validation messaging and smoke-test compatibility.
- [x] `P1-04` completed: basic manager/admin permission checks.
  - Added role guards in `app/auth.py`:
    - `require_manager_or_finance`
    - `require_finance`
    - manager detection based on direct reports
  - Added protected manager/finance routes in `app/main.py` with authorization enforcement:
    - `GET /manager/claims/pending`
    - `POST /manager/claims/{claim_id}/decision`
    - `GET /finance/claims/approved`
    - `POST /finance/claims/{claim_id}/process`
  - Added smoke coverage for permission gates (`401` unauthenticated, `403` non-privileged).
- [x] `P2-01` completed: in-app OCR confidence hints.
  - Added backend confidence scoring (`low` / `medium` / `high`) based on extracted OCR signals (date, merchant, amount).
  - Extended receipt upload API response with `ocr_confidence_label` and `ocr_confidence_score`.
  - Added UI confidence hint text in claim row receipt note (e.g. `OCR confidence: MEDIUM (67%)`).
  - Extended smoke coverage to assert confidence fields are present and valid.
- [x] `P2-02` completed: operational runbook for Windows support/debug.
  - Added `OPERATIONS_RUNBOOK.md` with startup/stop flows, health checks, logs, incident playbooks, backup/reset, and escalation checklist.
  - Linked runbook from `README.md` for quick operator access.
- [x] Phase 2 `P2-01` completed: manager approvals UI backed by real endpoints.
  - Added manager approvals page: `/manager/approvals`.
  - Wired page to live APIs:
    - `GET /manager/claims/pending`
    - `POST /manager/claims/{claim_id}/decision`
  - Added in-page auth/error messaging for restricted access and network/API failures.
  - Extended pending-claims payload with UI-ready fields (`claimant_name`, `period_label`, `type`).
  - Added smoke coverage for manager UI + decision flow (`test_manager_approvals_ui_and_decision`).
- [x] Phase 2 `P2-02` completed: finance processing UI backed by real endpoints.
  - Added finance processing page: `/finance/processing`.
  - Wired page to live APIs:
    - `GET /finance/claims/approved`
    - `POST /finance/claims/{claim_id}/process`
  - Added in-page auth/error messaging for restricted access and network/API failures.
  - Extended approved-claims payload with UI-ready fields (`claimant_name`, `period_label`, `type`).
  - Added smoke coverage for finance UI + process flow (`test_finance_processing_ui_and_action`).
- [x] Phase 2 `P2-03` completed: claim decision audit visibility in UI/history.
  - Added claim audit API endpoint: `GET /claims/{claim_id}/audit` with owner/manager/finance authorization.
  - Added claim history section in `claim.html` rendering audit timeline (when/actor/action/detail).
  - Added shared backend audit timeline resolver with legacy submit-event compatibility.
  - Updated submit audit detail format to include explicit `claim_id` token for consistent filtering.
  - Extended smoke coverage to verify audit endpoint and action visibility for submit/process flows.
- [x] Phase 2 `P2-04` completed: role-aware navigation and route-guard UX.
  - Added role-aware header navigation links in `base.html`:
    - dashboard
    - manager approvals (manager/finance only)
    - finance processing (finance only)
  - Added consistent access-denied page template (`access_denied.html`) for restricted manager/finance UI routes.
  - Wired nav flag context from backend role checks into claim/manager/finance pages.
  - Extended smoke coverage for:
    - denied-page messaging
    - role-based link visibility in rendered pages.
- [x] Phase 2 `P2-05` completed: end-to-end workflow QA sign-off.
  - Executed dedicated QA checklist for:
    - happy path (`submit -> approve -> process`)
    - reject path (`submit -> reject`, and reject not processable)
    - unauthorized and wrong-role scenarios for manager/finance API + UI routes
    - claim audit visibility for approve/reject/process actions
  - Saved sign-off report with evidence:
    - `P2-05_QA_SIGNOFF.md`
- [x] Phase 2 `P2-06` completed: live finance CSV/Excel exports from DB.
  - Added finance-only export endpoints:
    - `GET /finance/exports/lines.csv`
    - `GET /finance/exports/lines.xlsx`
  - Added shared filter logic with consistent behavior across formats:
    - `period` (`all` or `YYYY-MM`)
    - `type` (`all`, `cash`, `card`)
    - `status` (`all`, `draft`, `submitted`, `approved`, `rejected`, `processed`)
  - Added export controls to finance processing UI and wired filter state into downloads.
  - Documented export endpoints, filters, and columns in `README.md`.
  - Added automated coverage for format and filter correctness (`test_finance_exports_formats_and_filters`).
- [x] Phase 2 `P2-07` completed: reconciliation workflow scaffold.
  - Added reconciliation data model: `StatementLine` with optional link to `ClaimLine`.
  - Added finance reconciliation UI page: `GET /finance/reconciliation`.
  - Added reconciliation APIs:
    - `GET /finance/reconciliation/data` (returns `matched`, `unmatched_statement`, `missing_statement`)
    - `POST /finance/reconciliation/statement-lines/{statement_line_id}/match`
  - Added manual match UX in reconciliation page (statement line -> claim line ID).
  - Added audit logging for reconciliation matches (`reconciliation.match`).
  - Added smoke coverage for full scaffold flow (`test_reconciliation_scaffold_flow`).
- [x] Phase 2 `P2-08` completed: timezone-safe UTC cleanup.
  - Replaced `datetime.utcnow()` usage with timezone-aware UTC helper (`utc_now()` based on `datetime.now(datetime.UTC)`).
  - Updated model defaults (`AuditLog.at`, `StatementLine.created_at`) and runtime write paths (`submitted_at`, `signed_at`, `approved_at`).
  - Verified smoke suite executes with no `utcnow()` deprecation warnings.
- [x] Phase 2 `P2-09` completed: extended automated role-path tests.
  - Added manager scope boundary coverage:
    - manager queue includes direct-report claims only
    - manager cannot decide claims outside direct-report scope (`403`)
  - Added finance override coverage:
    - finance user can decide claims outside manager scope via manager decision endpoint.
  - Kept all existing auth/role-path tests passing.
  - Smoke suite now covers 9 tests total and remains green.
- [x] Phase 2 `P2-10` completed: CI smoke gate.
  - Added GitHub Actions workflow: `.github/workflows/smoke-tests.yml`.
  - Workflow runs smoke tests on every push and pull request.
  - Uses supported Python `3.13`, installs dependencies from `requirements.txt`, and executes unittest smoke suite.
  - README updated with CI gate reference and command parity.
- [x] Phase 2 `P2-11` completed: approval/rejection comments and timeline polish.
  - Added in-row comment input in manager approvals queue for both approve/reject actions.
  - Enforced rejection comment requirement in backend decision endpoint with clear `400` detail.
  - Polished claim history rendering with human-readable action labels and structured detail tags.
  - Added smoke coverage for rejection comment validation (`test_manager_reject_requires_comment`).
- [x] Phase 2 `P2-12` completed: deployment checklist + UAT script pack.
  - Added pilot-ready deployment checklist: `DEPLOYMENT_CHECKLIST.md`.
  - Added role-based UAT execution scripts and defect log template: `UAT_SCRIPT_PACK.md`.
  - Linked both docs from `README.md` for operator/tester discovery.

## In Progress

- [ ] Ensure existing local DB rows are also anonymized (if seeded before name changes).
  - Recommended: reset demo DB once to guarantee clean fictional data.

## Next Work (Where to Continue)

Start here, in order:

1. **Data reset checkpoint**
   - Stop app, remove `data/expenses.db`, run `.\scripts\run-dev.ps1`.
2. **Begin Phase 1 P0 implementation**
   - P0 implementation complete.
3. **Then move to**
   - P1 backlog items.

Recommended next items:
- Phase 2 board items are now complete.
- Optional follow-up: tighten branch protection to require `Smoke Tests` status.

## Phase 1 Board Status Snapshot

| Track | Status |
|---|---|
| Project setup and dev UX | Done |
| UI shell replacement | Done |
| GDPR demo-name scrub (code/templates/seed) | Done |
| P0 implementation work | Done (`P0-01` to `P0-06`) |
| P0 QA sign-off | Done |
| P1 smoke coverage | Done (`P1-03`) |
| P1 duplicate receipt guardrails | Done (`P1-01`) |
| P1 line-entry UX | Done (`P1-02`) |
| P1 role/permission checks | Done (`P1-04`) |
| P2 OCR confidence hints | Done (`P2-01`) |
| P2 operations runbook | Done (`P2-02`) |

## Quick Resume Commands

```powershell
cd "C:\Users\Michaelm1\Documents\AI-Projects\expense-app"
.\scripts\run-dev.ps1 -Lan
```

If you want a fully clean demo dataset before continuing:

```powershell
Stop-Process -Name python -Force -ErrorAction SilentlyContinue
Remove-Item ".\data\expenses.db" -Force
.\scripts\run-dev.ps1 -Lan
```
