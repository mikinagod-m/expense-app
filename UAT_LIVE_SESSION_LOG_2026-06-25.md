# Live UAT Session Log - 2026-06-25

- Environment URL: `http://localhost:8000`
- Flow covered: Claimant -> Manager -> Finance -> Security guardrails
- Tester: AI-assisted live API walk-through against running app

## Results

| Script Step | Result | Notes |
|---|---|---|
| A1 Login and landing | PASS | HTTP 200 |
| A2 Create claim | PASS | HTTP 200; claim_id=16 |
| A3 Add and save line | PASS | HTTP 200 |
| A4 Validation negative case | PASS | HTTP 400 |
| A5 Upload receipt + OCR | PASS | HTTP 200; confidence=low |
| A6 Duplicate guardrail | PASS | HTTP 200; duplicate=True |
| A7 Submit claim | PASS | HTTP 200; ref=2026060016 |
| B1 Access manager approvals | PASS | HTTP 200 |
| B2 Review queue scope | PASS | HTTP 200; queue_count=2 |
| B3 Approve flow | PASS | HTTP 200 |
| B4 Reject flow | PASS | HTTP 200 |
| C1 Access finance processing page | PASS | HTTP 200 |
| C2 Process approved claim | PASS | HTTP 200 |
| C3 Export CSV | PASS | HTTP 200 |
| C4 Export XLSX | PASS | HTTP 200 |
| C5 Reconciliation | PASS | match_http=200; matched=True |
| D1 Unauthorized API access | PASS | HTTP 401 |
| D2 Wrong-role access | PASS | manager_http=403; finance_http=403 |
| D3 Audit visibility | PASS | HTTP 200; actions=claim.create,claim.submit,claim_line.update,receipt.upload |

## Defect / Update Log

- No blocking fixes required from this live UAT run.
- Optional: improve timestamp formatting in claim history (currently raw ISO) for non-technical users.
- Optional: add comment character counter in manager queue for long decision notes.

## UAT Decision

- Decision: **ACCEPTED**
- Critical blockers: **0**
- Partial issues: **0**