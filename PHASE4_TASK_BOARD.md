# Expense App - Phase 4 Task Board (Mileage)

Phase 4 covers JJ feedback items **3–5** from `MILEAGE_AND_FEEDBACK_SCOPING.md`.  
**Status: Pending** — not started. Complete after Phase 3 `P3-04` (Azure AD).

## Priority Scale
- `P0`: must-have for mileage go-live
- `P1`: high-value operational improvements
- `P2`: polish and efficiency

## Board

| ID | Priority | Task | Owner Role | Status | Depends On |
|---|---|---|---|---|---|
| P4-01 | P0 | Mileage claims as first-class claim type | Backend + Frontend Engineer | Pending | P3-04 |
| P4-02 | P0 | Mileage rates engine (HMRC quarterly, personal vs company car, mid-month change) | Backend Engineer | Pending | P4-01 |
| P4-03 | P1 | Cumulative monthly mileage per claimant (10k threshold + energy stats) | Backend Engineer | Pending | P4-01, P4-02 |
| P4-04 | P2 | Card MCC hints for category coding (non-blocking) | Backend Engineer | Pending | Phase 2.5 GL codes |

## Task summaries

### P4-01 — Mileage claims
- Dedicated mileage capture UI and data model (journeys, distances, vehicles).
- Integrates with existing claim/period workflow without breaking cash/card lines.

### P4-02 — Mileage rates engine
- Configurable HMRC-style rates with effective dates.
- Personal vs company car rules; mid-period rate changes.

### P4-03 — Cumulative monthly mileage
- Per-claimant running totals within a period.
- 10,000-mile threshold handling and reporting for energy/fleet stats.

### P4-04 — MCC hints (deferred from Phase 2.5)
- Optional merchant category code on imported statement lines.
- Suggest (not enforce) category/GL mapping for finance.

## Ship gate

Phase 4 is ship-ready when P4-01 and P4-02 are done, mileage totals reconcile with finance exports, and QA sign-off covers at least one full mileage claim cycle.

## Reference

- Full design notes: `MILEAGE_AND_FEEDBACK_SCOPING.md`
