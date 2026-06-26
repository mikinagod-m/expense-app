# Live UAT Session Log - 2026-06-25 (Full role coverage)

- Environment URL: `http://localhost:8000`
- Flow covered: Claimant (id=2) -> Manager (id=1) -> Finance -> Security
- Tester: automated live API walkthrough against running app

## Results

| Script Step | Result | Notes |
|---|---|---|
| A1 Claimant login and landing | PASS |  |
| A1b Claimant blocked from manager page | PASS |  |
| A2 Create claim | PASS | claim_id=23 |
| A3 Add and save line | PASS |  |
| A4 Validation negative case | PASS |  |
| A5 Upload receipt + OCR | PASS | confidence=low |
| A6 Duplicate guardrail | PASS |  |
| A7 Submit claim | PASS | ref=2026060023 |
| B1 Access manager approvals | PASS |  |
| B2 Review queue scope | PASS | queue_count=4 |
| B4b Reject requires comment | PASS |  |
| B3 Approve flow | PASS |  |
| B4 Reject flow | PASS |  |
| C1 Access finance processing page | PASS |  |
| C2 Process approved claim | PASS |  |
| C3 Export CSV | PASS |  |
| C4 Export XLSX | PASS |  |
| C5 Reconciliation | PASS | match_http=200; matched=True |
| D3 Audit visibility | PASS | actions=claim.approve,claim.create,claim.process,claim.submit,claim_line.update,receipt.upload,reconciliation.match |
| D1 Unauthorized API access | PASS |  |
| D2 Wrong-role access | PASS | manager_http=403; finance_http=403 |

## UAT Decision

- Decision: **ACCEPTED**
- Critical blockers: **0**
- Partial issues: **0**
