import datetime as dt
import os
import unittest
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

TEST_DB_PATH = Path(f"data/test_smoke_{uuid4().hex}.db")
TEST_RECEIPTS_DIR = Path("receipts/test_smoke")

# Configure test environment before importing app modules.
os.environ["DEV_LOGIN"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["RECEIPTS_DIR"] = str(TEST_RECEIPTS_DIR)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import AuditLog, Category, Claim, ClaimLine, ClaimStatus, ClaimType, Period, StatementLine, User  # noqa: E402


class SmokeEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        TEST_RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

        cls.client = TestClient(app)
        cls.client.get("/login")

        with SessionLocal() as db:
            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            if not period:
                today = dt.date.today()
                db.add(
                    Period(
                        year=today.year,
                        month=today.month,
                        type=ClaimType.cash,
                        deadline=today + dt.timedelta(days=10),
                        is_open=True,
                    )
                )
                db.commit()

    @classmethod
    def tearDownClass(cls):
        engine.dispose()
        try:
            if TEST_DB_PATH.exists():
                TEST_DB_PATH.unlink()
        except PermissionError:
            # Non-fatal on Windows if a handle is still open momentarily.
            pass

    def test_claim_and_receipt_smoke_flow(self):
        with SessionLocal() as db:
            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712

        claim_resp = self.client.post("/claims/new", data={"period_id": period.id}, follow_redirects=False)
        self.assertEqual(claim_resp.status_code, 302)
        claim_id = int(claim_resp.headers["location"].split("/")[-1])

        add_line_resp = self.client.post(f"/claims/{claim_id}/lines")
        self.assertEqual(add_line_resp.status_code, 200)

        with SessionLocal() as db:
            line = db.scalar(
                select(ClaimLine).join(Claim).where(Claim.id == claim_id).order_by(ClaimLine.id.desc())
            )

        save_line_resp = self.client.post(
            f"/lines/{line.id}",
            data={
                "date": "2026-06-15",
                "narrative": "Taxi",
                "receipt_ref": "R-1",
                "category": "travel",
                "amount": "19.80",
                "reclaim_vat": "false",
            },
        )
        self.assertEqual(save_line_resp.status_code, 200)
        self.assertTrue(save_line_resp.json()["ok"])

        upload_resp = self.client.post(
            f"/lines/{line.id}/receipt",
            files={"file": ("scan.png", BytesIO(b"not-an-image"), "image/png")},
        )
        self.assertEqual(upload_resp.status_code, 200)
        self.assertTrue(upload_resp.json()["ok"])
        self.assertIn("ocr_confidence_label", upload_resp.json())
        self.assertIn("ocr_confidence_score", upload_resp.json())
        self.assertIn(upload_resp.json()["ocr_confidence_label"], {"low", "medium", "high"})

        submit_resp = self.client.post(f"/claims/{claim_id}/submit")
        self.assertEqual(submit_resp.status_code, 200)
        self.assertTrue(submit_resp.json()["ok"])
        self.assertIn("ref", submit_resp.json())

        audit_resp = self.client.get(f"/claims/{claim_id}/audit")
        self.assertEqual(audit_resp.status_code, 200)
        self.assertTrue(audit_resp.json()["ok"])
        audit_actions = {e["action"] for e in audit_resp.json()["events"]}
        self.assertIn("claim.submit", audit_actions)

        with SessionLocal() as db:
            audits = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).all()
            details = [a for a in audits if f"claim_id={claim_id}" in (a.detail or "")]
            actions = {a.action for a in details}

        self.assertTrue({"claim.create", "claim_line.update", "receipt.upload"}.issubset(actions))

    def test_negative_paths(self):
        anon = TestClient(app)
        unauthorized_claim = anon.post("/claims/new", data={"period_id": 1})
        self.assertEqual(unauthorized_claim.status_code, 401)

        unauthorized_line = anon.post(
            "/lines/1", data={"date": "2026-06-15", "category": "travel", "amount": "10"}
        )
        self.assertEqual(unauthorized_line.status_code, 401)

        unauthorized_manager = anon.get("/manager/claims/pending")
        self.assertEqual(unauthorized_manager.status_code, 401)

        unauthorized_finance = anon.get("/finance/claims/approved")
        self.assertEqual(unauthorized_finance.status_code, 401)

        unauthorized_finance_page = anon.get("/finance/processing")
        self.assertEqual(unauthorized_finance_page.status_code, 401)
        unauthorized_recon_page = anon.get("/finance/reconciliation")
        self.assertEqual(unauthorized_recon_page.status_code, 401)

        with SessionLocal() as db:
            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712

        claim_resp = self.client.post("/claims/new", data={"period_id": period.id}, follow_redirects=False)
        claim_id = int(claim_resp.headers["location"].split("/")[-1])
        self.client.post(f"/claims/{claim_id}/lines")

        with SessionLocal() as db:
            line = db.scalar(
                select(ClaimLine).join(Claim).where(Claim.id == claim_id).order_by(ClaimLine.id.desc())
            )

        invalid_line = self.client.post(
            f"/lines/{line.id}",
            data={
                "date": "bad-date",
                "narrative": "bad",
                "receipt_ref": "X",
                "category": "travel",
                "amount": "0",
                "reclaim_vat": "false",
            },
        )
        self.assertEqual(invalid_line.status_code, 400)
        self.assertGreaterEqual(len(invalid_line.json().get("errors", [])), 1)

        bad_file = self.client.post(
            f"/lines/{line.id}/receipt",
            files={"file": ("bad.exe", BytesIO(b"123"), "application/octet-stream")},
        )
        self.assertEqual(bad_file.status_code, 400)
        self.assertFalse(bad_file.json()["ok"])

        # Force logged-in demo user into non-privileged state for this check.
        with SessionLocal() as db:
            demo_user = db.scalar(select(User).order_by(User.id))
            demo_user.is_finance = False
            reports = db.scalars(select(User).where(User.manager_id == demo_user.id)).all()
            for rep in reports:
                rep.manager_id = None
            db.commit()

        # Logged-in demo user is now neither manager nor finance.
        manager_forbidden = self.client.get("/manager/claims/pending")
        self.assertEqual(manager_forbidden.status_code, 403)

        finance_forbidden = self.client.get("/finance/claims/approved")
        self.assertEqual(finance_forbidden.status_code, 403)

        finance_page_forbidden = self.client.get("/finance/processing")
        self.assertEqual(finance_page_forbidden.status_code, 403)
        self.assertIn("access denied", finance_page_forbidden.text.lower())
        recon_page_forbidden = self.client.get("/finance/reconciliation")
        self.assertEqual(recon_page_forbidden.status_code, 403)

    def test_role_aware_navigation_links(self):
        with SessionLocal() as db:
            user = db.scalar(select(User).order_by(User.id))
            user.is_finance = False
            reports = db.scalars(select(User).where(User.manager_id == user.id)).all()
            for rep in reports:
                rep.manager_id = None
            db.commit()

            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            claim = Claim(
                user_id=user.id,
                period_id=period.id,
                type=period.type,
                status=ClaimStatus.draft,
            )
            db.add(claim)
            db.commit()
            claim_id = claim.id

        page = self.client.get(f"/claims/{claim_id}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("/manager/approvals", page.text)
        self.assertNotIn("/finance/processing", page.text)

        with SessionLocal() as db:
            user = db.scalar(select(User).order_by(User.id))
            user.is_finance = True
            db.commit()

        page_finance = self.client.get(f"/claims/{claim_id}")
        self.assertEqual(page_finance.status_code, 200)
        self.assertIn("/manager/approvals", page_finance.text)
        self.assertIn("/finance/processing", page_finance.text)

    def test_duplicate_receipt_guardrail(self):
        with SessionLocal() as db:
            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712

        first_claim = self.client.post("/claims/new", data={"period_id": period.id}, follow_redirects=False)
        first_claim_id = int(first_claim.headers["location"].split("/")[-1])
        self.client.post(f"/claims/{first_claim_id}/lines")
        with SessionLocal() as db:
            first_line = db.scalar(
                select(ClaimLine).join(Claim).where(Claim.id == first_claim_id).order_by(ClaimLine.id.desc())
            )

        second_claim = self.client.post("/claims/new", data={"period_id": period.id}, follow_redirects=False)
        second_claim_id = int(second_claim.headers["location"].split("/")[-1])
        self.client.post(f"/claims/{second_claim_id}/lines")
        with SessionLocal() as db:
            second_line = db.scalar(
                select(ClaimLine).join(Claim).where(Claim.id == second_claim_id).order_by(ClaimLine.id.desc())
            )

        same_content = b"duplicate-receipt-bytes"
        first_upload = self.client.post(
            f"/lines/{first_line.id}/receipt",
            files={"file": ("taxi-receipt.png", BytesIO(same_content), "image/png")},
        )
        self.assertEqual(first_upload.status_code, 200)
        self.assertFalse(first_upload.json().get("possible_duplicate", False))

        second_upload = self.client.post(
            f"/lines/{second_line.id}/receipt",
            files={"file": ("taxi-receipt.png", BytesIO(same_content), "image/png")},
        )
        self.assertEqual(second_upload.status_code, 200)
        self.assertTrue(second_upload.json().get("possible_duplicate"))
        self.assertGreaterEqual(len(second_upload.json().get("duplicate_reasons", [])), 1)

    def test_manager_approvals_ui_and_decision(self):
        with SessionLocal() as db:
            manager = db.scalar(select(User).order_by(User.id))
            manager.is_finance = True
            manager.name = manager.name or "Manager Demo"
            manager.email = manager.email or "manager.demo@example.com"

            report = db.scalar(select(User).where(User.manager_id == manager.id))
            if not report:
                report = User(
                    name="Report User",
                    email=f"report-{uuid4().hex[:8]}@example.com",
                    manager_id=manager.id,
                )
                db.add(report)
                db.flush()

            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            claim = Claim(
                user_id=report.id,
                period_id=period.id,
                type=period.type,
                status=ClaimStatus.submitted,
            )
            db.add(claim)
            db.flush()

            line = ClaimLine(
                claim_id=claim.id,
                date=dt.date.today(),
                narrative="Manager review test",
                category=Category.travel,
                amount=22.10,
            )
            db.add(line)
            db.commit()

            claim_id = claim.id

        approvals_page = self.client.get("/manager/approvals")
        self.assertEqual(approvals_page.status_code, 200)
        self.assertIn("Manager approvals", approvals_page.text)

        pending = self.client.get("/manager/claims/pending")
        self.assertEqual(pending.status_code, 200)
        payload = pending.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(any(c["id"] == claim_id for c in payload["claims"]))

        decision = self.client.post(
            f"/manager/claims/{claim_id}/decision",
            data={"decision": "approved", "comment": "Looks good"},
        )
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(decision.json()["status"], "approved")

    def test_finance_processing_ui_and_action(self):
        with SessionLocal() as db:
            finance_user = db.scalar(select(User).order_by(User.id))
            finance_user.is_finance = True

            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            claim = Claim(
                user_id=finance_user.id,
                period_id=period.id,
                type=period.type,
                status=ClaimStatus.approved,
            )
            db.add(claim)
            db.flush()

            line = ClaimLine(
                claim_id=claim.id,
                date=dt.date.today(),
                narrative="Finance process test",
                category=Category.travel,
                amount=18.40,
            )
            db.add(line)
            db.commit()
            claim_id = claim.id

        processing_page = self.client.get("/finance/processing")
        self.assertEqual(processing_page.status_code, 200)
        self.assertIn("Finance processing queue", processing_page.text)

        approved = self.client.get("/finance/claims/approved")
        self.assertEqual(approved.status_code, 200)
        payload = approved.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(any(c["id"] == claim_id for c in payload["claims"]))

        process = self.client.post(f"/finance/claims/{claim_id}/process")
        self.assertEqual(process.status_code, 200)
        self.assertEqual(process.json()["status"], "processed")

        audit = self.client.get(f"/claims/{claim_id}/audit")
        self.assertEqual(audit.status_code, 200)
        actions = {e["action"] for e in audit.json()["events"]}
        self.assertIn("claim.process", actions)

    def test_finance_exports_formats_and_filters(self):
        with SessionLocal() as db:
            finance_user = db.scalar(select(User).order_by(User.id))
            finance_user.is_finance = True

            base_period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            prev_month = 12 if base_period.month == 1 else base_period.month - 1
            prev_year = base_period.year - 1 if base_period.month == 1 else base_period.year
            alt_period = db.scalar(
                select(Period).where(Period.year == prev_year, Period.month == prev_month).order_by(Period.id)
            )
            if not alt_period:
                alt_period = Period(
                    year=prev_year,
                    month=prev_month,
                    type=ClaimType.card,
                    deadline=dt.date.today(),
                    is_open=False,
                )
                db.add(alt_period)
                db.flush()

            approved_claim = Claim(
                user_id=finance_user.id,
                period_id=base_period.id,
                type=base_period.type,
                status=ClaimStatus.approved,
                unique_ref=f"APPROVED-{uuid4().hex[:8]}",
            )
            submitted_claim = Claim(
                user_id=finance_user.id,
                period_id=alt_period.id,
                type=ClaimType.card,
                status=ClaimStatus.submitted,
                unique_ref=f"SUBMITTED-{uuid4().hex[:8]}",
            )
            db.add_all([approved_claim, submitted_claim])
            db.flush()

            db.add(
                ClaimLine(
                    claim_id=approved_claim.id,
                    date=dt.date.today(),
                    narrative="Approved export row",
                    category=Category.travel,
                    amount=77.7,
                    vat_amount=12.95,
                )
            )
            db.add(
                ClaimLine(
                    claim_id=submitted_claim.id,
                    date=dt.date.today(),
                    narrative="Submitted export row",
                    category=Category.hotel,
                    amount=44.4,
                    vat_amount=7.4,
                )
            )
            db.commit()
            approved_ref = approved_claim.unique_ref
            submitted_ref = submitted_claim.unique_ref
            base_period_filter = f"{base_period.year}-{base_period.month:02d}"

        csv_resp = self.client.get("/finance/exports/lines.csv?status=approved&type=all&period=all")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("text/csv", csv_resp.headers.get("content-type", ""))
        self.assertIn(approved_ref, csv_resp.text)
        self.assertNotIn(submitted_ref, csv_resp.text)

        csv_period_resp = self.client.get(
            f"/finance/exports/lines.csv?status=all&type=all&period={base_period_filter}"
        )
        self.assertEqual(csv_period_resp.status_code, 200)
        self.assertIn(approved_ref, csv_period_resp.text)
        self.assertNotIn(submitted_ref, csv_period_resp.text)

        xlsx_resp = self.client.get("/finance/exports/lines.xlsx?status=approved&type=all&period=all")
        self.assertEqual(xlsx_resp.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            xlsx_resp.headers.get("content-type", ""),
        )
        self.assertTrue(xlsx_resp.content.startswith(b"PK"))

    def test_reconciliation_scaffold_flow(self):
        with SessionLocal() as db:
            finance_user = db.scalar(select(User).order_by(User.id))
            finance_user.is_finance = True

            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712

            claim = Claim(
                user_id=finance_user.id,
                period_id=period.id,
                type=ClaimType.card,
                status=ClaimStatus.approved,
                unique_ref=f"RECON-{uuid4().hex[:8]}",
            )
            db.add(claim)
            db.flush()

            line = ClaimLine(
                claim_id=claim.id,
                date=dt.date.today(),
                narrative="Recon line",
                category=Category.travel,
                amount=99.50,
            )
            db.add(line)
            db.flush()

            stmt = StatementLine(
                year=period.year,
                month=period.month,
                posted_date=dt.date.today(),
                cardholder_name=finance_user.name,
                merchant="Test Merchant",
                amount=99.50,
                currency="GBP",
            )
            db.add(stmt)
            db.commit()
            statement_id = stmt.id
            claim_line_id = line.id
            period_filter = f"{period.year}-{period.month:02d}"

        recon_page = self.client.get("/finance/reconciliation")
        self.assertEqual(recon_page.status_code, 200)
        self.assertIn("Finance reconciliation", recon_page.text)

        data_before = self.client.get(f"/finance/reconciliation/data?period={period_filter}&show=all")
        self.assertEqual(data_before.status_code, 200)
        body_before = data_before.json()
        self.assertTrue(body_before["ok"])
        self.assertTrue(any(r["statement_line_id"] == statement_id and r["status"] == "unmatched_statement" for r in body_before["statement_rows"]))
        self.assertTrue(any(r["claim_line_id"] == claim_line_id and r["status"] == "missing_statement" for r in body_before["missing_claim_rows"]))

        match = self.client.post(
            f"/finance/reconciliation/statement-lines/{statement_id}/match",
            data={"claim_line_id": claim_line_id},
        )
        self.assertEqual(match.status_code, 200)
        self.assertTrue(match.json()["ok"])

        data_after = self.client.get(f"/finance/reconciliation/data?period={period_filter}&show=all")
        self.assertEqual(data_after.status_code, 200)
        body_after = data_after.json()
        self.assertTrue(any(r["statement_line_id"] == statement_id and r["status"] == "matched" for r in body_after["statement_rows"]))
        self.assertFalse(any(r["claim_line_id"] == claim_line_id for r in body_after["missing_claim_rows"]))

    def test_manager_scope_and_finance_override(self):
        with SessionLocal() as db:
            # Use deterministic manager users for scope checks.
            mgr_a = db.scalar(select(User).order_by(User.id))
            mgr_a.is_finance = False
            mgr_a.name = mgr_a.name or "Manager A"

            mgr_b = db.scalar(select(User).where(User.id != mgr_a.id).order_by(User.id))
            if not mgr_b:
                mgr_b = User(name="Manager B", email=f"mgrb-{uuid4().hex[:8]}@example.com")
                db.add(mgr_b)
                db.flush()
            mgr_b.is_finance = False

            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712

            report_a = db.scalar(select(User).where(User.manager_id == mgr_a.id))
            if not report_a:
                report_a = User(
                    name="Report A",
                    email=f"report-a-{uuid4().hex[:8]}@example.com",
                    manager_id=mgr_a.id,
                )
                db.add(report_a)
                db.flush()

            report_b = db.scalar(select(User).where(User.manager_id == mgr_b.id))
            if not report_b:
                report_b = User(
                    name="Report B",
                    email=f"report-b-{uuid4().hex[:8]}@example.com",
                    manager_id=mgr_b.id,
                )
                db.add(report_b)
                db.flush()

            claim_a = Claim(
                user_id=report_a.id,
                period_id=period.id,
                type=period.type,
                status=ClaimStatus.submitted,
            )
            claim_b = Claim(
                user_id=report_b.id,
                period_id=period.id,
                type=period.type,
                status=ClaimStatus.submitted,
            )
            db.add_all([claim_a, claim_b])
            db.flush()
            db.add(ClaimLine(claim_id=claim_a.id, date=dt.date.today(), narrative="Scope A", category=Category.travel, amount=12.0))
            db.add(ClaimLine(claim_id=claim_b.id, date=dt.date.today(), narrative="Scope B", category=Category.travel, amount=13.0))
            db.commit()

            claim_a_id = claim_a.id
            claim_b_id = claim_b.id

        # Logged-in test client user is mgr_a (first user).
        mgr_queue = self.client.get("/manager/claims/pending")
        self.assertEqual(mgr_queue.status_code, 200)
        mgr_claim_ids = {c["id"] for c in mgr_queue.json().get("claims", [])}
        self.assertIn(claim_a_id, mgr_claim_ids)
        self.assertNotIn(claim_b_id, mgr_claim_ids)

        # Manager A cannot decide claim from Manager B's report.
        forbidden_decision = self.client.post(
            f"/manager/claims/{claim_b_id}/decision",
            data={"decision": "approved", "comment": "Cross-scope should fail"},
        )
        self.assertEqual(forbidden_decision.status_code, 403)

        # Finance override can decide both claims.
        with SessionLocal() as db:
            mgr_a = db.scalar(select(User).order_by(User.id))
            mgr_a.is_finance = True
            db.commit()

        finance_decision = self.client.post(
            f"/manager/claims/{claim_b_id}/decision",
            data={"decision": "approved", "comment": "Finance override"},
        )
        self.assertEqual(finance_decision.status_code, 200)
        self.assertEqual(finance_decision.json()["status"], "approved")


if __name__ == "__main__":
    unittest.main()
