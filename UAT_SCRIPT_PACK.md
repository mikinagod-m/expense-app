# UAT Script Pack (Phase 2 Pilot)

Use this script pack for structured user acceptance testing with pilot participants.

## Test Session Setup

- Environment URL:
- Tester name:
- Tester role: Claimant / Manager / Finance
- Browser:
- Date/time:
- Build or commit:

Pass criteria scale:
- `PASS` = works as expected
- `FAIL` = broken or blocked
- `PARTIAL` = works with notable issue

---

## Script A - Claimant Journey

### A1. Login and landing
- Step: Open app URL and sign in.
- Expected: Dashboard loads; claimant sees own role-appropriate nav only.
- Result: PASS / FAIL / PARTIAL
- Notes:

### A2. Create claim
- Step: Start a new claim from an open period.
- Expected: Claim draft opens successfully.
- Result: PASS / FAIL / PARTIAL
- Notes:

### A3. Add and save line
- Step: Enter date, narrative, category, amount.
- Expected: Auto-save or save completes; row shows saved state.
- Result: PASS / FAIL / PARTIAL
- Notes:

### A4. Validation negative case
- Step: Try invalid line (bad date or amount <= 0).
- Expected: Clear inline error shown; invalid data not accepted.
- Result: PASS / FAIL / PARTIAL
- Notes:

### A5. Upload receipt + OCR
- Step: Upload supported receipt file.
- Expected: Upload succeeds; OCR suggestions and confidence hint displayed.
- Result: PASS / FAIL / PARTIAL
- Notes:

### A6. Duplicate guardrail
- Step: Re-upload a likely duplicate receipt.
- Expected: Non-blocking duplicate warning appears.
- Result: PASS / FAIL / PARTIAL
- Notes:

### A7. Submit claim
- Step: Submit claim after fixing validation issues.
- Expected: Submit succeeds; reference generated and status updated.
- Result: PASS / FAIL / PARTIAL
- Notes:

---

## Script B - Manager Journey

### B1. Access manager approvals
- Step: Open manager approvals page.
- Expected: Page loads only for manager/finance role.
- Result: PASS / FAIL / PARTIAL
- Notes:

### B2. Review queue scope
- Step: Inspect pending claims list.
- Expected: Manager sees only direct-report claims (unless finance override).
- Result: PASS / FAIL / PARTIAL
- Notes:

### B3. Approve flow
- Step: Approve one submitted claim.
- Expected: Claim status transitions to approved and leaves pending queue.
- Result: PASS / FAIL / PARTIAL
- Notes:

### B4. Reject flow
- Step: Reject one submitted claim.
- Expected: Claim status transitions to rejected and leaves pending queue.
- Result: PASS / FAIL / PARTIAL
- Notes:

---

## Script C - Finance Journey

### C1. Access finance processing page
- Step: Open finance processing page.
- Expected: Accessible only for finance role.
- Result: PASS / FAIL / PARTIAL
- Notes:

### C2. Process approved claim
- Step: Mark approved claim as processed.
- Expected: Status becomes processed; claim removed from approved queue.
- Result: PASS / FAIL / PARTIAL
- Notes:

### C3. Export CSV
- Step: Export finance lines as CSV with filters.
- Expected: File downloads; rows match filter criteria.
- Result: PASS / FAIL / PARTIAL
- Notes:

### C4. Export XLSX
- Step: Export finance lines as XLSX with filters.
- Expected: File downloads and opens; columns are present/valid.
- Result: PASS / FAIL / PARTIAL
- Notes:

### C5. Reconciliation
- Step: Open reconciliation page and manually match one statement line.
- Expected: Status changes unmatched->matched; missing claim row updates.
- Result: PASS / FAIL / PARTIAL
- Notes:

---

## Script D - Security and Guardrails

### D1. Unauthorized API access
- Step: Call restricted routes while not logged in.
- Expected: `401` responses.
- Result: PASS / FAIL / PARTIAL
- Notes:

### D2. Wrong-role access
- Step: Try manager/finance pages as non-privileged user.
- Expected: Access denied with clear message.
- Result: PASS / FAIL / PARTIAL
- Notes:

### D3. Audit visibility
- Step: Open claim history/audit timeline for tested claims.
- Expected: submit/approve/reject/process actions visible and attributable.
- Result: PASS / FAIL / PARTIAL
- Notes:

---

## Defect Log Template

For each issue:
- ID:
- Severity: High / Medium / Low
- Area: Claimant / Manager / Finance / Export / Reconciliation / Auth
- Steps to reproduce:
- Expected behavior:
- Actual behavior:
- Screenshot/log reference:
- Owner:
- Status:

---

## UAT Sign-Off

- Critical blockers count:
- High severity open count:
- Medium severity open count:
- Low severity open count:

Decision:
- [ ] ACCEPTED
- [ ] ACCEPTED WITH CONDITIONS
- [ ] REJECTED

Sign-off names:
- Product Lead:
- QA Lead:
- Operations Lead:

Date:
Final notes:
