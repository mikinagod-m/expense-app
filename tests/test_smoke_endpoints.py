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
from app.models import AuditLog, Category, Claim, ClaimLine, ClaimStatus, ClaimType, Period, Receipt, StatementLine, User  # noqa: E402


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

    def test_discard_empty_draft_on_leave(self):
        with SessionLocal() as db:
            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            user = db.scalar(select(User).order_by(User.id))
            claim = Claim(user_id=user.id, period_id=period.id, type=period.type)
            db.add(claim)
            db.flush()
            db.add(ClaimLine(claim_id=claim.id))
            db.commit()
            claim_id = claim.id
            user_id = user.id

        self.client.get(f"/login?as={user_id}", follow_redirects=False)
        discard = self.client.post(f"/claims/{claim_id}/discard")
        self.assertEqual(discard.status_code, 200)
        self.assertTrue(discard.json()["discarded"])

        with SessionLocal() as db:
            self.assertIsNone(db.get(Claim, claim_id))

        home = self.client.get("/?view=claims")
        self.assertEqual(home.status_code, 200)
        self.assertNotIn(f"/claims/{claim_id}", home.text)

    def test_discard_does_not_remove_draft_with_data(self):
        with SessionLocal() as db:
            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712

        create = self.client.post("/claims/new", data={"period_id": period.id}, follow_redirects=False)
        claim_id = int(create.headers["location"].split("/")[-1])
        with SessionLocal() as db:
            line = db.scalar(select(ClaimLine).where(ClaimLine.claim_id == claim_id))

        save = self.client.post(
            f"/lines/{line.id}",
            data={
                "date": dt.date.today().isoformat(),
                "narrative": "Client lunch",
                "receipt_ref": "",
                "category": "subsistence",
                "amount": "12.50",
                "reclaim_vat": "false",
            },
        )
        self.assertEqual(save.status_code, 200)

        discard = self.client.post(f"/claims/{claim_id}/discard")
        self.assertEqual(discard.status_code, 200)
        self.assertFalse(discard.json()["discarded"])

        with SessionLocal() as db:
            self.assertIsNotNone(db.get(Claim, claim_id))

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
            report_name = report.name

        approvals_page = self.client.get("/manager/approvals")
        self.assertEqual(approvals_page.status_code, 200)
        self.assertIn("Approvals", approvals_page.text)
        self.assertIn("aimia-shell.css", approvals_page.text)

        pending = self.client.get("/manager/claims/pending")
        self.assertEqual(pending.status_code, 200)
        payload = pending.json()
        self.assertTrue(payload["ok"])
        match = next(c for c in payload["claims"] if c["id"] == claim_id)
        self.assertEqual(match["claimant_name"], report_name)
        self.assertEqual(len(match["lines"]), 1)
        self.assertEqual(match["lines"][0]["narrative"], "Manager review test")
        self.assertEqual(match["lines"][0]["amount"], 22.10)

        decision = self.client.post(
            f"/manager/claims/{claim_id}/decision",
            data={"decision": "approved", "comment": "Looks good"},
        )
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(decision.json()["status"], "approved")

    def test_manager_can_view_receipt_on_pending_claim(self):
        receipt_path = TEST_RECEIPTS_DIR / "manager-view.png"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-for-test")

        with SessionLocal() as db:
            manager = db.scalar(select(User).order_by(User.id))
            manager.is_finance = True

            report = db.scalar(select(User).where(User.manager_id == manager.id))
            if not report:
                report = User(
                    name="Receipt Report",
                    email=f"receipt-report-{uuid4().hex[:8]}@example.com",
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
                narrative="Receipt review",
                category=Category.travel,
                amount=50.0,
            )
            db.add(line)
            db.flush()
            receipt = Receipt(claim_line_id=line.id, file_path=str(receipt_path))
            db.add(receipt)
            db.commit()
            receipt_id = receipt.id

        pending = self.client.get("/manager/claims/pending")
        self.assertEqual(pending.status_code, 200)
        claim_payload = next(c for c in pending.json()["claims"] if c["lines"][0]["narrative"] == "Receipt review")
        self.assertIsNotNone(claim_payload["lines"][0]["receipt"])
        self.assertTrue(claim_payload["lines"][0]["receipt"]["is_image"])

        view = self.client.get(f"/receipts/{receipt_id}")
        self.assertEqual(view.status_code, 200)
        self.assertIn("image/png", view.headers.get("content-type", ""))

        anon = TestClient(app)
        denied = anon.get(f"/receipts/{receipt_id}")
        self.assertEqual(denied.status_code, 401)

    def test_manager_reject_requires_comment(self):
        with SessionLocal() as db:
            reviewer = db.scalar(select(User).order_by(User.id))
            reviewer.is_finance = True

            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            claim = Claim(
                user_id=reviewer.id,
                period_id=period.id,
                type=period.type,
                status=ClaimStatus.submitted,
            )
            db.add(claim)
            db.flush()
            db.add(
                ClaimLine(
                    claim_id=claim.id,
                    date=dt.date.today(),
                    narrative="Reject comment test",
                    category=Category.travel,
                    amount=14.25,
                )
            )
            db.commit()
            claim_id = claim.id

        missing_comment = self.client.post(
            f"/manager/claims/{claim_id}/decision",
            data={"decision": "rejected", "comment": ""},
        )
        self.assertEqual(missing_comment.status_code, 400)
        self.assertIn("Rejection comment is required", missing_comment.json().get("detail", ""))

        with_comment = self.client.post(
            f"/manager/claims/{claim_id}/decision",
            data={"decision": "rejected", "comment": "Policy mismatch"},
        )
        self.assertEqual(with_comment.status_code, 200)
        self.assertEqual(with_comment.json()["status"], "rejected")

    def test_manager_rejection_aggregates_line_comments(self):
        with SessionLocal() as db:
            manager = db.scalar(select(User).order_by(User.id))
            manager.is_finance = True
            claimant = db.scalar(select(User).where(User.id != manager.id).order_by(User.id))
            self.assertIsNotNone(claimant)
            claimant.manager_id = manager.id

            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            claim = Claim(
                user_id=claimant.id,
                period_id=period.id,
                type=period.type,
                status=ClaimStatus.submitted,
            )
            db.add(claim)
            db.flush()
            db.add_all([
                ClaimLine(
                    claim_id=claim.id,
                    date=dt.date.today(),
                    narrative="Customer visit",
                    receipt_ref="1234",
                    category=Category.subsistence,
                    amount=250.0,
                ),
                ClaimLine(
                    claim_id=claim.id,
                    date=dt.date.today(),
                    narrative="Customer visit",
                    receipt_ref="43637",
                    category=Category.hotel,
                    amount=100.0,
                ),
            ])
            db.commit()
            claim_id = claim.id

        pending = self.client.get("/manager/claims/pending")
        match = next(c for c in pending.json()["claims"] if c["id"] == claim_id)
        self.assertEqual(len(match["lines"]), 2)

        reject = self.client.post(
            f"/manager/claims/{claim_id}/decision",
            data={
                "decision": "rejected",
                "comment": "subsistence · Customer visit: Fix receipt ref | hotel · Customer visit: Amount looks high",
            },
        )
        self.assertEqual(reject.status_code, 200)
        self.assertEqual(reject.json()["status"], "rejected")

        with SessionLocal() as db:
            row = db.scalar(
                select(AuditLog)
                .where(AuditLog.action == "claim.reject", AuditLog.detail.contains(f"claim_id={claim_id}"))
                .order_by(AuditLog.id.desc())
            )
            self.assertIsNotNone(row)
            self.assertIn("Fix receipt ref", row.detail)
            self.assertIn("Amount looks high", row.detail)

    def test_rejected_claim_editable_and_resubmit(self):
        with SessionLocal() as db:
            manager = db.scalar(select(User).order_by(User.id))
            manager.is_finance = True
            claimant = db.scalar(select(User).where(User.id != manager.id).order_by(User.id))
            self.assertIsNotNone(claimant)
            claimant.manager_id = manager.id

            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            claim = Claim(
                user_id=claimant.id,
                period_id=period.id,
                type=period.type,
                status=ClaimStatus.submitted,
                unique_ref=f"TEST{claimant.id:04d}",
            )
            db.add(claim)
            db.flush()
            line = ClaimLine(
                claim_id=claim.id,
                date=dt.date.today(),
                narrative="Needs receipt ref",
                category=Category.travel,
                amount=22.50,
                receipt_ref="R-OLD",
            )
            db.add(line)
            db.commit()
            claim_id = claim.id
            line_id = line.id
            manager_id = manager.id
            claimant_email = claimant.email

        mgr_client = TestClient(app)
        mgr_client.get(f"/login?as={manager_id}")
        reject = mgr_client.post(
            f"/manager/claims/{claim_id}/decision",
            data={"decision": "rejected", "comment": "Add missing receipt refs"},
        )
        self.assertEqual(reject.status_code, 200)
        self.assertEqual(reject.json()["status"], "rejected")

        claimant_client = TestClient(app)
        claimant_client.get(f"/login?as={claimant_email}")
        page = claimant_client.get(f"/claims/{claim_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Resubmit claim", page.text)
        self.assertIn("Returned for changes", page.text)
        self.assertIn("Add missing receipt refs", page.text)
        self.assertIn('name="narrative"', page.text)

        save = claimant_client.post(
            f"/lines/{line_id}",
            data={
                "date": dt.date.today().isoformat(),
                "narrative": "Updated taxi with receipt",
                "receipt_ref": "R-NEW-99",
                "category": "travel",
                "amount": "22.50",
                "reclaim_vat": "false",
            },
        )
        self.assertEqual(save.status_code, 200)
        self.assertTrue(save.json()["ok"])

        resubmit = claimant_client.post(f"/claims/{claim_id}/submit")
        self.assertEqual(resubmit.status_code, 200)
        self.assertTrue(resubmit.json()["ok"])

        with SessionLocal() as db:
            claim = db.get(Claim, claim_id)
            self.assertEqual(claim.status, ClaimStatus.submitted)
            line = db.get(ClaimLine, line_id)
            self.assertEqual(line.receipt_ref, "R-NEW-99")

        blocked = claimant_client.post(
            f"/lines/{line_id}",
            data={
                "date": dt.date.today().isoformat(),
                "narrative": "Edit after resubmit",
                "receipt_ref": "R-BLOCK",
                "category": "travel",
                "amount": "1.00",
                "reclaim_vat": "false",
            },
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("can no longer be edited", blocked.json().get("detail", ""))

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
        self.assertIn("Processing queue", processing_page.text)
        self.assertIn("aimia-shell.css", processing_page.text)

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
            approved_id = approved_claim.id
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

        pdf_resp = self.client.get("/finance/exports/lines.pdf?status=approved&type=all&period=all")
        self.assertEqual(pdf_resp.status_code, 200)
        self.assertIn("application/pdf", pdf_resp.headers.get("content-type", ""))
        self.assertTrue(pdf_resp.content.startswith(b"%PDF"))

        claim_pdf = self.client.get(f"/finance/exports/claims/{approved_id}.pdf")
        self.assertEqual(claim_pdf.status_code, 200)
        self.assertIn("application/pdf", claim_pdf.headers.get("content-type", ""))
        self.assertTrue(claim_pdf.content.startswith(b"%PDF"))

    def test_backup_run(self):
        import tempfile
        from pathlib import Path

        from app.backup_utils import run_backup

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "test.db"
            db_path.write_bytes(b"sqlite-test")
            receipts = root / "receipts"
            receipts.mkdir()
            (receipts / "sample.txt").write_text("receipt", encoding="utf-8")
            backup_root = root / "backups"

            result = run_backup(
                database_url=f"sqlite:///{db_path.as_posix()}",
                receipts_dir=str(receipts),
                backup_dir=str(backup_root),
                retention_days=14,
            )
            self.assertTrue(result["ok"])
            destination = Path(result["destination"])
            self.assertTrue((destination / "test.db").is_file())
            self.assertTrue((destination / "receipts" / "sample.txt").is_file())
            self.assertTrue((destination / "manifest.json").is_file())

    def test_nav_badges(self):
        with SessionLocal() as db:
            manager = db.scalar(select(User).order_by(User.id))
            manager.is_finance = False
            manager.is_admin = False

            report = db.scalar(select(User).where(User.manager_id == manager.id))
            if not report:
                report = User(
                    name="Badge Report",
                    email=f"badge.report.{uuid4().hex[:8]}@example.com",
                    manager_id=manager.id,
                )
                db.add(report)
                db.flush()

            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            pending = Claim(
                user_id=report.id,
                period_id=period.id,
                type=period.type,
                status=ClaimStatus.submitted,
                unique_ref=f"BADGE-{uuid4().hex[:8]}",
            )
            db.add(pending)
            db.commit()
            manager_id = manager.id

        self.client.get(f"/login?as={manager_id}", follow_redirects=False)
        badges = self.client.get("/nav/badges")
        self.assertEqual(badges.status_code, 200)
        body = badges.json()
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(body["pending_approvals"], 1)

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
        self.assertIn("Reconciliation", recon_page.text)
        self.assertIn("aimia-shell.css", recon_page.text)

        data_before = self.client.get(f"/finance/reconciliation/data?period={period_filter}&show=all")
        self.assertEqual(data_before.status_code, 200)
        body_before = data_before.json()
        self.assertTrue(body_before["ok"])
        self.assertTrue(any(r["statement_line_id"] == statement_id and r["status"] == "unmatched_statement" for r in body_before["statement_rows"]))
        unmatched_row = next(r for r in body_before["statement_rows"] if r["statement_line_id"] == statement_id)
        self.assertIsNotNone(unmatched_row.get("suggested_match"))
        self.assertEqual(unmatched_row["suggested_match"]["claim_line_id"], claim_line_id)
        self.assertTrue(any(r["claim_line_id"] == claim_line_id and r["status"] == "missing_statement" for r in body_before["missing_claim_rows"]))

        accept = self.client.post(
            f"/finance/reconciliation/statement-lines/{statement_id}/match",
            data={"claim_line_id": unmatched_row["suggested_match"]["claim_line_id"]},
        )
        self.assertEqual(accept.status_code, 200)
        self.assertTrue(accept.json()["ok"])

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

    def test_statement_csv_import(self):
        with SessionLocal() as db:
            finance_user = db.scalar(select(User).order_by(User.id))
            finance_user.is_finance = True
            db.commit()

        csv_body = (
            "date,merchant,amount,cardholder\n"
            "2026-06-10,Coffee Shop,4.50,Jordan Blake\n"
            "2026-06-11,Stationery,12.00,Jordan Blake\n"
        )
        resp = self.client.post(
            "/finance/reconciliation/import",
            files={"file": ("statement.csv", BytesIO(csv_body.encode("utf-8")), "text/csv")},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["imported"], 2)

        data = self.client.get("/finance/reconciliation/data?period=2026-06")
        self.assertEqual(data.status_code, 200)
        rows = data.json()["statement_rows"]
        self.assertGreaterEqual(len(rows), 2)

    def test_finance_period_toggle(self):
        with SessionLocal() as db:
            finance_user = db.scalar(select(User).order_by(User.id))
            finance_user.is_finance = True
            period = db.scalar(select(Period).order_by(Period.id))
            period_id = period.id
            was_open = period.is_open
            db.commit()

        listed = self.client.get("/finance/periods/data")
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(p["id"] == period_id for p in listed.json()["periods"]))

        toggled = self.client.post(f"/finance/periods/{period_id}/toggle")
        self.assertEqual(toggled.status_code, 200)
        self.assertEqual(toggled.json()["is_open"], not was_open)

        # restore original state
        self.client.post(f"/finance/periods/{period_id}/toggle")

    def test_submit_still_works_with_notifications_module(self):
        with SessionLocal() as db:
            period = db.scalar(select(Period).where(Period.is_open == True).order_by(Period.id))  # noqa: E712
            user = db.scalar(select(User).where(User.manager_id.is_not(None)).order_by(User.id))
            claim = Claim(
                user_id=user.id,
                period_id=period.id,
                type=period.type,
                status=ClaimStatus.draft,
            )
            db.add(claim)
            db.flush()
            db.add(
                ClaimLine(
                    claim_id=claim.id,
                    date=dt.date.today(),
                    narrative="Notify smoke",
                    category=Category.travel,
                    amount=9.99,
                    receipt_ref="R-NOTIFY",
                )
            )
            db.commit()
            claim_id = claim.id
            user_id = user.id

        self.client.get(f"/login?as={user_id}", follow_redirects=False)
        submit = self.client.post(f"/claims/{claim_id}/submit")
        self.assertEqual(submit.status_code, 200)
        self.assertTrue(submit.json()["ok"])

    def test_admin_user_privileges(self):
        with SessionLocal() as db:
            admin = db.scalar(select(User).order_by(User.id))
            admin.is_admin = True
            admin.is_finance = True
            target = User(
                name="Privilege Target",
                email=f"priv.target.{uuid4().hex[:8]}@example.com",
                can_claim_cash=True,
                has_credit_card=False,
            )
            db.add(target)
            db.commit()
            admin_id = admin.id
            target_id = target.id

        self.client.get(f"/login?as={admin_id}", follow_redirects=False)
        page = self.client.get("/admin/users")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Users &amp; roles", page.text)

        data = self.client.get("/admin/users/data")
        self.assertEqual(data.status_code, 200)
        body = data.json()
        self.assertTrue(body["ok"])
        row = next(u for u in body["users"] if u["id"] == target_id)
        self.assertNotIn("manager", row["roles"])

        update = self.client.post(
            f"/admin/users/{target_id}",
            data={
                "manager_id": str(admin_id),
                "is_finance": "",
                "is_admin": "",
                "has_credit_card": "1",
                "can_claim_cash": "1",
            },
        )
        self.assertEqual(update.status_code, 200)
        updated = update.json()["user"]
        self.assertTrue(updated["has_credit_card"])
        self.assertEqual(updated["manager_id"], admin_id)

        admin_row = next(u for u in body["users"] if u["id"] == admin_id)
        refreshed = self.client.get("/admin/users/data").json()
        admin_row = next(u for u in refreshed["users"] if u["id"] == admin_id)
        self.assertIn("manager", admin_row["roles"])

        self.client.get(f"/login?as={target_id}", follow_redirects=False)
        forbidden = self.client.get("/admin/users/data")
        self.assertEqual(forbidden.status_code, 403)

        self.client.get(f"/login?as={admin_id}", follow_redirects=False)


if __name__ == "__main__":
    unittest.main()
