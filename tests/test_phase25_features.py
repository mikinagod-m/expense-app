"""Smoke tests for Phase 2.5 features:
- Item 1: Finance re-codes a submitted line (coding/description only)
- Item 2: Days working from home (Sales only; excluded from claim total)
- Item 6a: Category GL/nominal codes (admin + export column)
"""
import datetime as dt
import os
import unittest
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

TEST_DB_PATH = Path(f"data/test_p25_{uuid4().hex}.db")
TEST_RECEIPTS_DIR = Path("receipts/test_p25")

os.environ["DEV_LOGIN"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["RECEIPTS_DIR"] = str(TEST_RECEIPTS_DIR)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Category, CategoryCode, Claim, ClaimLine, ClaimStatus, ClaimType, Period, User,
)


def _open_period(db, claim_type=ClaimType.cash):
    period = db.scalar(
        select(Period).where(Period.is_open == True, Period.type == claim_type)  # noqa: E712
    )
    if not period:
        today = dt.date.today()
        period = Period(
            year=today.year, month=today.month, type=claim_type,
            deadline=today + dt.timedelta(days=10), is_open=True,
        )
        db.add(period)
        db.commit()
        db.refresh(period)
    return period


class Phase25Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        TEST_RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- Item 1: finance re-coding ----------
    def test_finance_amends_submitted_line_coding(self):
        with SessionLocal() as db:
            finance = User(name="Fin One", email=f"fin_{uuid4().hex}@ex.com", is_finance=True)
            claimant = User(name="Claim One", email=f"cl_{uuid4().hex}@ex.com")
            db.add_all([finance, claimant])
            db.commit()
            period = _open_period(db)
            claim = Claim(user_id=claimant.id, period_id=period.id,
                          type=ClaimType.cash, status=ClaimStatus.submitted,
                          unique_ref="REF-AMEND-1")
            db.add(claim)
            db.commit()
            line = ClaimLine(claim_id=claim.id, date=dt.date.today(),
                             narrative="Exhibition products F31-290",
                             category=Category.other, amount=22.50, receipt_ref="2")
            db.add(line)
            db.commit()
            finance_id, claimant_id, line_id, claim_id = finance.id, claimant.id, line.id, claim.id
            gross_before = claim.gross_total

        fin = TestClient(app)
        fin.get(f"/login?as={finance_id}")
        resp = fin.post(f"/lines/{line_id}/amend",
                        data={"category": "staff_entertaining",
                              "narrative": "Exhibition products (re-coded)"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["changed"])

        with SessionLocal() as db:
            line = db.get(ClaimLine, line_id)
            self.assertEqual(line.category, Category.staff_entertaining)
            self.assertEqual(line.narrative, "Exhibition products (re-coded)")
            claim = db.get(Claim, claim_id)
            # Re-coding must NOT change the money.
            self.assertEqual(claim.gross_total, gross_before)

        # Audit trail records the amend with from/to.
        audit = fin.get(f"/claims/{claim_id}/audit")
        self.assertEqual(audit.status_code, 200)
        self.assertIn("amend", audit.text.lower() + str(audit.json()).lower())

        # Owner cannot use the finance amend path.
        owner = TestClient(app)
        owner.get(f"/login?as={claimant_id}")
        denied = owner.post(f"/lines/{line_id}/amend", data={"category": "travel"})
        self.assertEqual(denied.status_code, 403)

    def test_finance_amend_cannot_change_amount_or_date(self):
        # The endpoint accepts only narrative/category; amount/date params are ignored.
        with SessionLocal() as db:
            finance = User(name="Fin Two", email=f"fin2_{uuid4().hex}@ex.com", is_finance=True)
            claimant = User(name="Claim Two", email=f"cl2_{uuid4().hex}@ex.com")
            db.add_all([finance, claimant])
            db.commit()
            period = _open_period(db)
            claim = Claim(user_id=claimant.id, period_id=period.id,
                          type=ClaimType.cash, status=ClaimStatus.submitted, unique_ref="REF-AMEND-2")
            db.add(claim)
            db.commit()
            line = ClaimLine(claim_id=claim.id, date=dt.date(2026, 2, 9),
                             narrative="Dinner", category=Category.subsistence, amount=24.30)
            db.add(line)
            db.commit()
            finance_id, line_id = finance.id, line.id

        fin = TestClient(app)
        fin.get(f"/login?as={finance_id}")
        fin.post(f"/lines/{line_id}/amend",
                 data={"category": "travel", "amount": "999.99", "date": "2099-01-01"})
        with SessionLocal() as db:
            line = db.get(ClaimLine, line_id)
            self.assertEqual(line.amount, 24.30)
            self.assertEqual(line.date, dt.date(2026, 2, 9))
            self.assertEqual(line.category, Category.travel)

    def test_finance_cannot_amend_processed_claim(self):
        with SessionLocal() as db:
            finance = User(name="Fin Three", email=f"fin3_{uuid4().hex}@ex.com", is_finance=True)
            claimant = User(name="Claim Three", email=f"cl3_{uuid4().hex}@ex.com")
            db.add_all([finance, claimant])
            db.commit()
            period = _open_period(db)
            claim = Claim(user_id=claimant.id, period_id=period.id,
                          type=ClaimType.cash, status=ClaimStatus.processed, unique_ref="REF-AMEND-3")
            db.add(claim)
            db.commit()
            line = ClaimLine(claim_id=claim.id, narrative="x", category=Category.other, amount=5.0)
            db.add(line)
            db.commit()
            finance_id, line_id = finance.id, line.id

        fin = TestClient(app)
        fin.get(f"/login?as={finance_id}")
        resp = fin.post(f"/lines/{line_id}/amend", data={"category": "travel"})
        self.assertEqual(resp.status_code, 400)

    # ---------- Item 2: WFH days excluded from total ----------
    def test_wfh_days_recorded_but_excluded_from_total(self):
        with SessionLocal() as db:
            sales = User(name="Toni Sales", email=f"sales_{uuid4().hex}@ex.com", is_sales_team=True)
            db.add(sales)
            db.commit()
            period = _open_period(db)
            sales_id, period_id = sales.id, period.id

        cli = TestClient(app)
        cli.get(f"/login?as={sales_id}")
        new = cli.post("/claims/new", data={"period_id": period_id})
        self.assertIn(new.status_code, (200, 302))
        with SessionLocal() as db:
            claim = db.scalars(
                select(Claim).where(Claim.user_id == sales_id).order_by(Claim.id.desc())
            ).first()
            claim_id = claim.id
            # add a real expense line so there is a non-zero gross
            line = ClaimLine(claim_id=claim_id, date=dt.date.today(),
                             narrative="Dinner", category=Category.subsistence, amount=24.30)
            db.add(line)
            db.commit()

        resp = cli.post(f"/claims/{claim_id}/wfh", data={"wfh_days": "25"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["wfh_days"], 25)
        self.assertAlmostEqual(body["wfh_amount"], round(25 * body["wfh_rate"], 2))
        # The crucial rule: gross_total excludes WFH.
        self.assertEqual(body["gross_total"], 24.30)
        with SessionLocal() as db:
            claim = db.get(Claim, claim_id)
            self.assertEqual(claim.wfh_days, 25)
            self.assertEqual(claim.gross_total, 24.30)  # unchanged by WFH

    def test_wfh_blocked_for_non_sales_user(self):
        with SessionLocal() as db:
            normal = User(name="Not Sales", email=f"ns_{uuid4().hex}@ex.com", is_sales_team=False)
            db.add(normal)
            db.commit()
            period = _open_period(db)
            normal_id, period_id = normal.id, period.id

        cli = TestClient(app)
        cli.get(f"/login?as={normal_id}")
        new = cli.post("/claims/new", data={"period_id": period_id})
        with SessionLocal() as db:
            claim = db.scalars(
                select(Claim).where(Claim.user_id == normal_id).order_by(Claim.id.desc())
            ).first()
            claim_id = claim.id
        resp = cli.post(f"/claims/{claim_id}/wfh", data={"wfh_days": "10"})
        self.assertEqual(resp.status_code, 403)

    # ---------- Item 6a: GL codes ----------
    def test_category_codes_admin_and_export_column(self):
        with SessionLocal() as db:
            finance = User(name="Fin GL", email=f"fingl_{uuid4().hex}@ex.com", is_finance=True)
            claimant = User(name="GL Claim", email=f"glc_{uuid4().hex}@ex.com")
            db.add_all([finance, claimant])
            db.commit()
            period = _open_period(db)
            claim = Claim(user_id=claimant.id, period_id=period.id,
                          type=ClaimType.cash, status=ClaimStatus.submitted, unique_ref="REF-GL-1")
            db.add(claim)
            db.commit()
            line = ClaimLine(claim_id=claim.id, date=dt.date.today(),
                             narrative="Hotel night", category=Category.hotel, amount=100.0)
            db.add(line)
            db.commit()
            finance_id = finance.id

        fin = TestClient(app)
        fin.get(f"/login?as={finance_id}")

        # Data endpoint returns a row per category.
        data = fin.get("/admin/category-codes/data")
        self.assertEqual(data.status_code, 200)
        cats = {c["category"] for c in data.json()["codes"]}
        self.assertIn("hotel", cats)

        # Set a GL code for hotel.
        save = fin.post("/admin/category-codes",
                        data={"category": "hotel", "gl_code": "7400",
                              "description": "Hotel accommodation", "active": "true"})
        self.assertEqual(save.status_code, 200)
        self.assertEqual(save.json()["code"]["gl_code"], "7400")

        # Export now carries the gl_code column populated for hotel lines.
        csv_resp = fin.get("/finance/exports/lines.csv?status=all&type=all&period=all")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("gl_code", csv_resp.text.splitlines()[0])
        self.assertIn("7400", csv_resp.text)

    def test_category_codes_require_finance(self):
        with SessionLocal() as db:
            normal = User(name="No Fin", email=f"nofin_{uuid4().hex}@ex.com")
            db.add(normal)
            db.commit()
            normal_id = normal.id
        cli = TestClient(app)
        cli.get(f"/login?as={normal_id}")
        self.assertEqual(cli.get("/admin/category-codes/data").status_code, 403)
        self.assertEqual(
            cli.post("/admin/category-codes", data={"category": "hotel", "gl_code": "1"}).status_code,
            403,
        )

    def test_finance_processing_page_has_inline_recoding(self):
        with SessionLocal() as db:
            finance = User(name="Fin UI", email=f"finui_{uuid4().hex}@ex.com", is_finance=True)
            claimant = User(name="Claim UI", email=f"clui_{uuid4().hex}@ex.com")
            db.add_all([finance, claimant])
            db.commit()
            period = _open_period(db)
            claim = Claim(
                user_id=claimant.id,
                period_id=period.id,
                type=ClaimType.cash,
                status=ClaimStatus.approved,
                unique_ref="REF-UI-1",
            )
            db.add(claim)
            db.commit()
            line = ClaimLine(
                claim_id=claim.id,
                date=dt.date.today(),
                narrative="Exhibition products",
                category=Category.other,
                amount=22.50,
            )
            db.add(line)
            db.commit()
            finance_id, line_id = finance.id, line.id

        fin = TestClient(app)
        fin.get(f"/login?as={finance_id}")
        page = fin.get("/finance/processing")
        self.assertEqual(page.status_code, 200)
        self.assertIn("claim-record-table.js", page.text)
        self.assertIn("showFinanceAmend: true", page.text)
        self.assertIn("amendLine", page.text)

        amend = fin.post(
            f"/lines/{line_id}/amend",
            data={"category": "staff_entertaining", "narrative": "Exhibition (re-coded)"},
        )
        self.assertEqual(amend.status_code, 200)
        self.assertTrue(amend.json()["changed"])
        self.assertEqual(amend.json()["line"]["category_key"], "staff_entertaining")


if __name__ == "__main__":
    unittest.main()
