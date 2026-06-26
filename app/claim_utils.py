"""Helpers for claim lifecycle (empty detection, deletion)."""
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Claim, ClaimLine, ClaimStatus

EDITABLE_CLAIM_STATUSES = frozenset({ClaimStatus.draft, ClaimStatus.rejected})


def claim_is_editable_by_owner(claim: Claim) -> bool:
    """Claimant may edit drafts and rejected claims before resubmitting."""
    return claim.status in EDITABLE_CLAIM_STATUSES


def is_claim_empty(claim: Claim) -> bool:
    """True when a draft has no user-entered expense data."""
    if claim.status != ClaimStatus.draft:
        return False
    if not claim.lines:
        return True
    for line in claim.lines:
        if not line_is_blank(line):
            return False
    return True


def line_is_blank(line: ClaimLine) -> bool:
    if line.date is not None:
        return False
    if (line.narrative or "").strip():
        return False
    if (line.receipt_ref or "").strip():
        return False
    if line.amount and float(line.amount) > 0:
        return False
    if line.receipt is not None:
        return False
    if line.reclaim_vat:
        return False
    return True


def delete_claim(db: Session, claim: Claim) -> None:
    for line in list(claim.lines):
        if line.statement_line is not None:
            line.statement_line.claim_line_id = None
        receipt = line.receipt
        if receipt and receipt.file_path:
            path = receipt.file_path.strip()
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
    db.delete(claim)


def purge_empty_drafts(db: Session, user_id: int) -> int:
    """Remove abandoned empty drafts for a user. Returns count removed."""
    drafts = [
        c
        for c in db.scalars(
            select(Claim).where(
                Claim.user_id == user_id,
                Claim.status == ClaimStatus.draft,
            )
        ).all()
        if is_claim_empty(c)
    ]
    for claim in drafts:
        delete_claim(db, claim)
    if drafts:
        db.commit()
    return len(drafts)
