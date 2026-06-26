# Expense App — Scoping for JJ's Feedback (Toni Walker April 2026 form)

Last updated: 2026-06-26  
Status: **Phase 2.5 items 1, 2, and 6a implemented.** Items 3–5 (mileage) remain Phase 4 plan only.

This document scopes the five changes raised in JJ's email (cc Deborah Smith,
Julie Roberts) against the example cash + mileage form. It deliberately goes
deep on the **mileage rates engine (Item 4)**, which is the hard design problem.

---

## The five asks, at a glance

| # | Ask | Size | Phase fit | New data model? |
|---|-----|------|-----------|-----------------|
| 1 | Finance can amend a line's **description / coding** after submission | Small | Phase 2 extension | No (reuses `category`, `narrative`) |
| 2 | **Days working from home** (Sales only, paid via Payroll, excluded from claim total) | Small | Phase 2 extension | Yes (small: 1 user flag + 3 claim fields) |
| 3 | **Mileage claims** as a first-class claim type | Large | New phase (P4) | Yes (new table) |
| 4 | **Mileage rates engine** (HMRC quarterly rates, personal vs company car, mid-month change) | Large | New phase (P4) | Yes (rate tables + vehicle on profile) |
| 5 | **Cumulative monthly mileage per claimant** (10k threshold + energy stats) | Medium | New phase (P4) | Derived + a reading store |
| 6 | **Category coding codes** — GL/nominal code per category now; card MCC as a later non-blocking hint | Small (GL) / Medium (MCC) | Phase 2.5 (GL) / deferred (MCC) | Yes (small: lookup table; later `mcc` on statement_lines) |

**Recommendation:** ship 1 and 2 quickly as a small Phase 2.5 release; treat
3+4+5 as a single new **Phase 4: Mileage**, because they share one data spine.

---

## Item 1 — Finance amends description / coding after submission

**The need (verbatim example).** Transaction #2 on Toni's form — *"Exhibition
products F31-290"* — was put in the **Other** category by Toni because she didn't
know the correct coding. Deb amends it so she can process. Quote from JJ:
*"claimant won't know where to put the coding, however Deb would amend it."*

**What already exists.** `ClaimLine` already has `category` (the cost-column enum:
hotel / subsistence / travel / foreign_travel / postage / staff_entertaining /
customer_entertaining / other / personal) and `narrative`. Finance already has
authority in the workflow and a processing queue. The audit log already records
`claim_line.update`.

**What's missing.** Today, line edits go through `POST /lines/{line_id}`, which is
gated by `claim_is_editable_by_owner` — i.e. only the **owner**, and only while the
claim is in an editable state (draft / rejected). Once submitted, nobody can
re-code a line.

**Proposed change (small, contained):**
- New endpoint `POST /lines/{line_id}/amend` (or a `finance=true` branch on the
  existing line update) that:
  - requires `is_finance`;
  - allows editing **only** `category` and `narrative` (not amount/date — money
    stays as the claimant entered it, which preserves trust in the audit trail);
  - is permitted while the claim is `submitted` or `approved` (not yet `processed`);
  - writes a distinct audit action **`claim_line.amend`** with before/after values,
    e.g. `claim_id=…;line_id=…;field=category;from=other;to=staff_entertaining`.
- UI: in the finance processing drawer, make `category` (and `narrative`) editable
  for finance, with a visible "amended by Finance" marker on the line so the
  claimant and manager can see it was re-coded.

**Why not let them edit amounts too?** Keeps the separation clean: claimant owns
the figures, Finance owns the coding. If Deb needs to change an amount she can use
the existing **deduction / unauthorised** mechanism, which is already on the form
(`unauthorised_amount`, rows 37–41). Worth confirming with Deb.

**Acceptance checks:**
- Finance can re-code a submitted line; owner cannot edit it; manager cannot edit it.
- Amount and date are immutable via this path.
- `claim_line.amend` appears in the claim audit timeline with from/to.
- Re-coding does **not** change `gross_total`.

---

## Item 2 — Days Working From Home (Sales team only, via Payroll)

**The need.** On Toni's form, rows 43–44:

```
DAYS CLAIMED | RATE PER DAY | AMOUNT CLAIMED £
     25      |    £1.35     |     £33.75
DAYS WORKING FROM HOME (SALES TEAM ONLY - WILL BE PAID VIA PAYROLL)
```

The red text is the whole point: **this amount is NOT reimbursed through the
expense claim.** Quote: *"only paid once a month via Payroll (won't be added to a
total claim) and advised by Deb at the month end, before payroll process the
wages."* So we capture it, show it to Deb, but it must **never** enter
`gross_total`, "total claim submitted", or "authorised to pay".

**What's missing.** No concept of a sales-team user; no WFH capture; no payroll-only
amount.

**Proposed change (small):**
- `User.is_sales_team: bool` (new flag, default false; surfaced in `/admin/users`).
- On the claim (cash type only), three fields: `wfh_days: int`, `wfh_rate: float`
  (default 1.35, but store it so a future rate change is captured historically),
  `wfh_amount` as a **derived/display** value = `wfh_days * wfh_rate`.
  - Store `wfh_rate` as an effective-dated config value (see rates pattern below) so
    we're not hardcoding £1.35 forever. Minimum viable: a single setting now.
- UI: WFH section shows **only** if `claim.user.is_sales_team`. Clearly labelled
  "Paid via Payroll — not part of this claim total."
- A **finance/payroll view or export column** so Deb gets the month's WFH totals per
  claimant ahead of payroll. Likely a new column in the finance lines export, or a
  small dedicated "Payroll items" export.
- **Crucially:** `gross_total` and all "to pay" figures exclude `wfh_amount`.
  Add a test that asserts this exclusion explicitly.

**Open question for Deb/Julie:** is the £1.35/day rate fixed, or does it change?
If it changes, it belongs in the effective-dated rate store (Item 4 infra) rather
than as a constant.

---

## Item 6 — Category coding codes (GL now, MCC later)

**The need.** Raised in review: *"hope you added the MCC codes to match with the
category."* The underlying goal is to attach a **finance code** to each expense
category so coding is deterministic and exports drop straight onto Deb's posting
screen — instead of her re-keying it. Note the form itself carries Aimia's
**internal cost categories** (Hotel, Subsistence, Travel, etc.) plus product codes
like `F31-290` typed into the narrative; it does **not** currently carry card-network
MCCs.

There are two different things "MCC" could mean here, and they get **different
treatment**:

### 6a — GL / nominal code per category (BUILD NOW, in Phase 2.5)

Each `Category` maps to an Aimia GL/nominal posting code. Deterministic, helps
**all** claim types (cash, card, mileage), and pairs naturally with Item 1 — when
Finance re-codes a line, its GL code re-points automatically.

**Proposed (small):**
- New lookup table:
  ```
  CategoryCode
    id
    category        (FK/enum value: hotel / subsistence / travel / … / personal)
    gl_code         (Aimia nominal code — TEXT; populated by Finance)
    description     (optional human label)
    active          (bool)
  ```
- Editable by Finance/Admin at `/admin` (a small "Category codes" screen).
- New **`gl_code` export column** in the finance lines export (CSV/XLSX/PDF),
  resolved from the line's current category.
- Because the GL code is derived from `category`, re-coding a line (Item 1)
  changes the GL code with no extra work.
- **Aimia must supply the actual codes** — these are chart-of-accounts values only
  Deb/Julie hold. The build delivers the structure + admin screen; they populate.

**Acceptance checks:**
- Every active category resolves to a GL code (or a clear "unmapped" flag).
- Re-coding a line updates its exported GL code.
- Export carries `gl_code` alongside `category`.

### 6b — Card-network MCC as a non-blocking hint (DEFER; design now)

Merchant Category Codes from the Barclaycard feed (e.g. 5812 restaurants,
7011 hotels, 5541 fuel) can **suggest** a category on card import — but MCC→category
is genuinely fuzzy (5812 could be Subsistence *or* Customer/Staff Entertaining), and
only helps card claims. So treat it exactly like OCR confidence and the
duplicate-receipt guardrail: **a suggestion Finance confirms, never an auto-commit.**

**Deferred design:**
- Add `mcc: str | None` to `statement_lines` (the model currently has `merchant`
  but no MCC). **Depends on Julie's Barclaycard export actually carrying a clean MCC
  column — confirm before building.**
- An MCC→category suggestion map that pre-fills the *likely* category on import,
  flagged as a hint, with Finance confirming.
- Never blocks; never overrides a human coding decision.

**Why defer:** the GL code (6a) is the deterministic win that lands on Deb's posting
screen. MCC stays advisory because the ambiguity lives exactly where a human judgment
is needed.

---

## Items 3–5 — Phase 4: Mileage (the substantial work)

Mileage is **not** a tweak to cash claims. It is a second claim type with its own
line shape, its own rate rules, and its own reporting. The April form proves it:
mileage lives on a *separate* form (rows 48–79) with different columns
(miles × rate, not a gross amount).

### Item 3 — Mileage as a first-class claim type

**Form shape (rows 61–70 on Toni's sheet):**

```
DATE | DETAILS OF JOURNEY | TOTAL MILES | LESS NORMAL TRAVEL-TO-WORK MILEAGE
     | "OUT OF POCKET" MILEAGE CLAIMED | RATE PER MILE £ | TOTAL MILEAGE CLAIM £
```

Toni's example: 9 journeys, 1,284 out-of-pocket miles total, all at **£0.12/mile**,
**£154.08 total**. (Verified: 1,284 × 0.12 = 154.08.) Note she's on the **12p
advisory fuel rate**, i.e. a company-car fuel-only reclaim — which is exactly why
the rate engine has to support more than one regime.

**Model decision (stated assumption — confirm):** `ClaimType` currently has
`cash` and `card`. I propose adding `ClaimType.mileage` and a dedicated
**`MileageLine`** table rather than overloading `ClaimLine`, because the columns
genuinely differ (total miles, commute deduction, out-of-pocket miles, rate, vehicle).
Periods already support a `type`, so a mileage period drops in cleanly with **no
rollover work** — the existing period design pays off here.

```
MileageLine
  id, claim_id (FK)
  date
  journey            (text — "Travel to Leicester for Integra event")
  total_miles
  commute_deduct_miles   (the "less normal travel to work" column; N/A for home-based)
  out_of_pocket_miles    (claimable miles = total - commute)
  rate_per_mile          (resolved from the rates engine at entry/submission time)
  vehicle_id (FK, nullable)  (which car this journey was on — see Item 4)
  amount                 (out_of_pocket_miles * rate_per_mile)
```

**Workflow:** reuses the existing submit → approve → process pipeline unchanged.
The mileage total appears as its own block (Toni's row 34: "MILEAGE CLAIM TO PAY").
On the combined form mileage is added to the cash claim's grand total
(£246.89 cash + £154.08 mileage + £33.75 WFH-but-payroll handling = the £400.97
figure includes mileage; WFH is shown separately). **We must mirror that exactly:**
mileage **does** roll into the authorised-to-pay total; WFH **does not**.

### Item 4 — The mileage rates engine (deep dive)

This is the crux of JJ's questions:
> *"HMRC provide Rates per mile every 3 months and if claimant changed a car and
> engine size changed as well. Can the car information be uploaded to the claimant
> profile? What if half way through the month car changes and rate needs to be
> amended?"*

There are **two distinct rate regimes**, and the engine must handle both:

**Regime A — Personal car, HMRC AMAP rates.**
Standard HMRC Approved Mileage Allowance Payments: a fixed pence-per-mile that
HMRC sets, independent of engine size. (The well-known figures are 45p for the
first 10,000 business miles in the tax year and 25p thereafter, but **we should
not hardcode these** — they are exactly the "every 3 months" values JJ refers to
and must be table-driven and effective-dated.)

**Regime B — Company car, advisory fuel rates (AFR).**
This is what Toni is on. Rate depends on **fuel type (petrol/diesel/…) and engine
size band**, and HMRC republishes these **quarterly**. JJ's screenshot is exactly
this table:

```
Petrol   Up to 1400cc → 14p   |  1401–2000 → 16p  |  Over 2000 → 26p   (advisory fuel rate column)
Diesel   Up to 1600cc → 15p   |  1601–2000 → 17p  |  Over 2000 → 23p
```

JJ also notes the company-car **band split: 55p first 10,000 miles, 25p
thereafter** — note this is a *different* threshold concept layered on top, so the
engine must support **mileage-band-dependent rates** as well as date/engine/fuel.

**Design: an effective-dated rate table keyed by regime.**

```
MileageRate
  id
  regime            ("amap_personal" | "afr_company")
  fuel_type         (nullable; "petrol"/"diesel"/"electric"/… — only for AFR)
  engine_cc_min     (nullable; band floor, e.g. 1401)
  engine_cc_max     (nullable; band ceiling, e.g. 2000)
  band_miles_min    (nullable; e.g. 0 for first-10k band)
  band_miles_max    (nullable; e.g. 10000)
  pence_per_mile
  effective_from    (date)
  effective_to      (date, nullable = current)
  source_note       ("HMRC AFR Q2 2026, published 01/06/2026")
```

**Resolution logic** — given (journey date, vehicle, cumulative miles so far):
1. Filter rows where `effective_from <= journey.date <= effective_to (or open)`.
2. Filter by `regime` from the vehicle.
3. For AFR: match `fuel_type` and engine band.
4. For mileage-band rates: pick the band the cumulative miles fall into.
5. Return `pence_per_mile`; **snapshot it onto the `MileageLine.rate_per_mile`** at
   entry so a later rate-table update never retroactively rewrites a submitted claim.

**This directly answers JJ's three sub-questions:**

- *"Rates every 3 months"* → effective-dated rows; loading the new HMRC quarter is a
  data task (admin screen or a small importer), not a code change. Old claims keep
  their snapshotted rate.
- *"Car / engine size on the claimant profile"* → **yes.** New `Vehicle` table tied
  to the user:
  ```
  Vehicle
    id, user_id (FK)
    label            ("Audi A4 — company")
    ownership        ("personal" | "company")
    fuel_type        (petrol/diesel/electric/hybrid)
    engine_cc        (1995)
    active_from, active_to   (effective-dated — this is the mid-month-change answer)
  ```
- *"What if the car changes half way through the month?"* → because both `Vehicle`
  and `MileageRate` are **effective-dated**, the engine resolves the rate **per
  journey date**, not per month. A journey on 5 March uses the car/rate valid on
  5 March; a journey on 20 March after a car swap uses the new one. No manual
  month-splitting. The claimant picks the vehicle per line (defaulting to whichever
  is active on that date), and Finance can override.

**Edge cases to nail down with Finance:**
- Tax-year vs calendar boundaries for the 10,000-mile band (AMAP is **tax year**:
  6 Apr–5 Apr). The cumulative counter (Item 5) must reset on the right boundary.
- Electric/hybrid AFR rates (separate HMRC figures).
- What happens when no rate matches the journey date (missing quarter loaded) —
  propose a clear "rate not configured for this date" validation rather than a
  silent £0, plus Finance override.

### Item 5 — Cumulative monthly mileage per claimant

**The need.** Deb keeps a running mileage reading by month (the green
"MILEAGE APRIL 2025–MAR 2026" grid: Toni 761 miles Feb, 523 March, 9406 cumulative).
Two uses: (a) the 10,000-mile company-car / AMAP threshold, and (b) **energy-company
statistics** JJ mentions.

**Proposed:**
- Derived aggregation: sum `out_of_pocket_miles` (and/or `total_miles`) per claimant
  per period, exposed as a Finance report + export column.
- A cumulative **tax-year-to-date** counter per claimant, feeding the band logic in
  Item 4. Stored or computed — computed is cleaner if all mileage is in the DB.
- If Deb also records an **odometer reading** (the grid suggests a running total),
  add an optional `odometer_reading` capture per period so her existing process is
  preserved. **Confirm with Deb whether she needs the odometer or just the sum of
  claimed miles** — they're different numbers.

---

## Suggested sequencing

1. **Phase 2.5 (small, quick):** Item 1 (finance re-coding) + Item 2 (WFH/payroll)
   + Item 6a (GL/nominal code per category). All low-risk, reuse existing structures,
   and unblock Deb's day-to-day. 6a pairs naturally with 1 — re-coding a line
   re-points its GL code for free.
2. **Phase 4 (Mileage):** Items 3 + 4 + 5 together, built on the shared
   `Vehicle` + `MileageRate` + `MileageLine` spine.
   - P4-01 Mileage data model + period type
   - P4-02 Vehicle on claimant profile (effective-dated)
   - P4-03 Rates engine + admin/import for quarterly HMRC rates
   - P4-04 Mileage claim UI (entry, per-line rate resolution, vehicle pick)
   - P4-05 Cumulative mileage report + 10k band + energy-stats export
   - P4-06 QA sign-off + smoke tests (mirror the existing P0-06 pattern)
3. **Deferred:** Item 6b (card-network MCC suggestion layer) — design ready, build
   gated on confirming Julie's Barclaycard export carries a clean MCC column.

## Migration notes (fits your existing pattern)

All new columns/tables are **additive** and slot into `schema_upgrade.py`'s
inspect-and-`ALTER TABLE` approach — no Alembic needed, SQLite-safe, Postgres-safe.
New tables come from `Base.metadata.create_all`. Nothing here forces a rewrite of
existing data; old cash/card claims are untouched.

## Open questions to confirm before build (for JJ / Deb / Julie)

1. **Item 1:** Should Finance be able to edit amounts too, or only coding/description?
   (I propose coding/description only; amounts handled via existing deductions.)
2. **Item 2:** Is the £1.35/day WFH rate fixed or does it change? Confirms whether it
   needs the effective-dated store.
3. **Item 4:** For the 10,000-mile band — tax year (6 Apr–5 Apr) confirmed?
4. **Item 4:** Which fuel types/regimes are actually in use (any electric/hybrid)?
5. **Item 5:** Does Deb need a true **odometer reading**, or just the **sum of claimed
   miles** per month?
6. **Combined form:** confirm mileage rolls into "authorised to pay" while WFH stays
   out (matches the April form, but worth a one-line confirmation).
7. **Item 6a:** Deb/Julie to supply the GL/nominal code for each expense category
   (chart-of-accounts values — only Finance holds these).
8. **Item 6b:** Does Julie's Barclaycard statement export include a clean MCC column?
   This single fact decides whether the MCC suggestion layer is buildable.
