# Expense App Agency Team Playbook

This playbook defines a reusable "agency team" for `expense-app` so work stays fast, scoped, and production-safe.

## Team Structure

### 1) Product Lead
- Converts requests into a clear objective.
- Defines acceptance criteria and out-of-scope boundaries.
- Calls out dependencies and release risk.

### 2) Backend Engineer (FastAPI + SQLAlchemy)
- Implements API routes, business logic, auth integration, OCR flow, and DB changes.
- Protects data correctness for `claims`, `claim_lines`, `receipts`, and `audit_log`.
- Keeps migrations/schema changes backward compatible whenever possible.

### 3) Frontend Engineer (HTMX + templates)
- Updates server-rendered templates and HTMX interactions.
- Optimizes data-entry speed for claim and receipt workflows.
- Ensures error states are clear and actionable for internal users.

### 4) QA Engineer
- Builds test cases for happy path + failure path.
- Validates claim lifecycle: create claim -> add/edit lines -> upload receipt -> OCR prefill -> submit.
- Verifies auth paths for `DEV_LOGIN=1` and Azure AD mode.

### 5) Security Reviewer
- Reviews auth/session boundaries and role assumptions.
- Reviews file upload handling and OCR-related input risks.
- Confirms audit logging remains intact for sensitive actions.

## Default Workflow

1. **Intake (Product Lead)**  
   Write: objective, acceptance criteria, constraints, and non-goals.

2. **Plan (Backend + Frontend)**  
   Split work into minimal vertical slices that can be tested independently.

3. **Build (Engineering)**  
   Implement smallest diff that satisfies acceptance criteria.

4. **Verify (QA + Security)**  
   Run automated checks where available and execute manual flow checks.

5. **Ship Note (Product Lead)**  
   Document what changed, what was validated, known risks, and next tasks.

## Reusable Prompt Templates

Use these directly when delegating work to an agent/person.

### Product Lead Prompt
"Turn this request into a concrete implementation brief for `expense-app`: objective, acceptance criteria, non-goals, dependencies, and risk notes."

### Backend Engineer Prompt
"Implement the backend changes for `expense-app` with minimal diffs. Prioritize correctness in claim, receipt, OCR, and audit flows. Include verification steps."

### Frontend Engineer Prompt
"Implement HTMX/template changes for `expense-app` with fast, clear data entry UX. Keep server-rendered patterns and include manual test steps."

### QA Engineer Prompt
"Create and execute a focused test plan for the updated `expense-app` behavior, including edge cases for auth, claim lines, and receipt OCR."

### Security Reviewer Prompt
"Review the current `expense-app` changes for auth/session, file upload, and audit-log risks. Report concrete issues, impact, and fixes."

## Definition of Ready
- Request is specific enough to implement.
- Environment assumptions are known (`DEV_LOGIN`, DB target, OCR availability).
- Success criteria are testable.

## Definition of Done
- Acceptance criteria met.
- Critical expense flow validated.
- Risks and follow-up items documented.
