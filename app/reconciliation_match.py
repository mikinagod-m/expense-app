"""Suggest statement-to-claim-line matches for finance reconciliation."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .models import ClaimLine, StatementLine


def _amount_key(amount: float) -> float:
    return round(float(amount or 0.0), 2)


def index_unmatched_card_lines(lines: list[ClaimLine]) -> dict[tuple[dt.date, float], list[ClaimLine]]:
    """Group unmatched card claim lines by expense date and amount."""
    index: dict[tuple[dt.date, float], list[ClaimLine]] = defaultdict(list)
    for line in lines:
        if line.statement_line is not None or line.date is None:
            continue
        index[(line.date, _amount_key(line.amount))].append(line)
    return index


def pick_best_candidate(statement: StatementLine, candidates: list[ClaimLine]) -> ClaimLine | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    holder = (statement.cardholder_name or "").strip().lower()
    if holder:
        by_name = [
            line
            for line in candidates
            if holder in (line.claim.user.name or "").lower()
        ]
        if len(by_name) == 1:
            return by_name[0]

    return max(candidates, key=lambda line: line.id)


def suggest_match_for_statement(
    statement: StatementLine,
    unmatched_index: dict[tuple[dt.date, float], list[ClaimLine]],
) -> dict | None:
    """Return a suggested claim line when date and amount align exactly."""
    if statement.claim_line_id or not statement.posted_date:
        return None

    key = (statement.posted_date, _amount_key(statement.amount))
    candidates = list(unmatched_index.get(key, []))
    if not candidates:
        return None

    chosen = pick_best_candidate(statement, candidates)
    if not chosen:
        return None

    claim = chosen.claim
    return {
        "claim_line_id": chosen.id,
        "claim_id": claim.id,
        "claim_ref": claim.unique_ref or "",
        "claimant": claim.user.name,
        "date": chosen.date.isoformat() if chosen.date else "",
        "detail": chosen.narrative or "",
        "amount": chosen.amount,
        "match_count": len(candidates),
    }
