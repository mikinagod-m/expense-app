"""Delete all draft claims and related receipt files. Run: python -m app.cleanup_drafts"""
from sqlalchemy import select

from .claim_utils import delete_claim
from .db import SessionLocal
from .models import Claim, ClaimStatus


def delete_all_drafts() -> int:
    removed = 0
    with SessionLocal() as db:
        drafts = db.scalars(select(Claim).where(Claim.status == ClaimStatus.draft)).all()
        for claim in drafts:
            delete_claim(db, claim)
            removed += 1
        db.commit()
    return removed


if __name__ == "__main__":
    count = delete_all_drafts()
    print(f"Removed {count} draft claim(s).")
