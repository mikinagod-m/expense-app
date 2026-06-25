# Expense App - Phase 2 Task Board

This board moves the app from Phase 1 capture/validation into a complete manager + finance workflow with production-ready operations.

## Priority Scale
- `P0`: must-have for usable approvals + processing workflow
- `P1`: high-value improvements and release hardening
- `P2`: quality/efficiency enhancements

## Board

| ID | Priority | Task | Owner Role | Status | Depends On |
|---|---|---|---|---|---|
| P2-01 | P0 | Build manager approvals UI backed by real manager endpoints | Frontend + Backend Engineer | Done | - |
| P2-02 | P0 | Build finance processing UI backed by real finance endpoints | Frontend + Backend Engineer | Done | P2-01 |
| P2-03 | P0 | Implement claim decision audit visibility in UI/history | Backend Engineer + QA Engineer | Done | P2-01 |
| P2-04 | P0 | Add role-aware navigation and route guards in UI | Frontend Engineer + Security Reviewer | Done | P2-01 |
| P2-05 | P0 | End-to-end QA for submit -> approve/reject -> process flows | QA Engineer | Done | P2-02 |
| P2-06 | P1 | Implement live CSV/Excel exports from DB (no demo fixtures) | Backend Engineer | Done | P2-02 |
| P2-07 | P1 | Add reconciliation workflow scaffolding for card statement matching | Backend Engineer + Frontend Engineer | Done | P2-02 |
| P2-08 | P1 | Replace `datetime.utcnow()` with timezone-aware UTC usage | Backend Engineer | Done | - |
| P2-09 | P1 | Extend automated tests for manager/finance positive-role paths | QA Engineer + Backend Engineer | Done | P2-05 |
| P2-10 | P1 | Add CI job to run smoke tests on every push/PR | DevOps/Backend Engineer | Done | P2-09 |
| P2-11 | P2 | Add approval/rejection comment UX and timeline view polish | Frontend Engineer | Done | P2-03 |
| P2-12 | P2 | Add deployment checklist and UAT script pack for pilot rollout | Product Lead + QA Engineer | Done | P2-10 |

## Task Details and Acceptance Criteria

### P2-01 - Manager approvals UI
**Owner:** Frontend + Backend Engineer  
**Acceptance Criteria:**
- UI calls `GET /manager/claims/pending` and lists only permitted claims.
- Manager can approve/reject from UI using `POST /manager/claims/{claim_id}/decision`.
- Authorization failures are handled with clear user messaging (not silent failures).

### P2-02 - Finance processing UI
**Owner:** Frontend + Backend Engineer  
**Acceptance Criteria:**
- UI calls `GET /finance/claims/approved` and displays processing queue.
- Finance can mark approved claims as processed via `POST /finance/claims/{claim_id}/process`.
- Processed claims disappear from "approved queue" without full-page instability.

### P2-03 - Decision audit visibility
**Owner:** Backend Engineer + QA Engineer  
**Acceptance Criteria:**
- Approve/reject/process actions are visible in claim history context.
- Timeline/audit data excludes sensitive values.
- QA confirms audit view reflects actual backend state transitions.

### P2-04 - Role-aware nav and guards
**Owner:** Frontend Engineer + Security Reviewer  
**Acceptance Criteria:**
- Non-manager/non-finance users do not see privileged actions.
- Direct URL access to restricted routes fails safely with clear messaging.
- Behavior aligns with backend `401/403` responses.

### P2-05 - End-to-end workflow QA
**Owner:** QA Engineer  
**Acceptance Criteria:**
- QA checklist covers submit -> approve/reject -> process happy and unhappy paths.
- Includes unauthorized and wrong-role scenarios.
- Sign-off report saved in repo with pass/fail evidence.

### P2-06 - Live exports
**Owner:** Backend Engineer  
**Acceptance Criteria:**
- CSV and Excel exports generated from live DB rows (claims + lines + categories).
- Filters (period/type/status) are applied consistently.
- Export columns align with finance needs and are documented.

### P2-07 - Reconciliation scaffold
**Owner:** Backend Engineer + Frontend Engineer  
**Acceptance Criteria:**
- Baseline model/API/UX path exists for statement-vs-claim matching.
- Unmatched/missing states are clearly represented.
- Leaves room for future auto-matching logic.

### P2-08 - UTC deprecation cleanup
**Owner:** Backend Engineer  
**Acceptance Criteria:**
- Replace `datetime.utcnow()` usage in app/model write paths.
- No `utcnow()` deprecation warnings during smoke test run.
- Existing timestamp semantics remain correct.

### P2-09 - Role-path automated tests
**Owner:** QA Engineer + Backend Engineer  
**Acceptance Criteria:**
- Add positive manager and finance role-path tests.
- Keep unauthorized/non-privileged tests passing.
- Test suite remains runnable via existing script.

### P2-10 - CI smoke gate
**Owner:** DevOps/Backend Engineer  
**Acceptance Criteria:**
- CI runs smoke tests on push/PR.
- Failing tests block merge-ready status.
- Basic run instructions documented.

## Suggested Execution Plan

1. Deliver workflow UI core first (`P2-01`, `P2-02`, `P2-04`).
2. Validate complete business flow (`P2-05`) before export/reconciliation expansion.
3. Add reliability and release hardening (`P2-08`, `P2-09`, `P2-10`).
4. Complete operational and pilot readiness (`P2-12`).

## Ship Gate for Phase 2

Phase 2 is ship-ready when all Phase 2 `P0` items are `Done`, QA workflow sign-off is complete, and no open high-severity auth/role/processing defects remain.
