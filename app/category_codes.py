"""GL / nominal posting codes per expense Category (Item 6a).

Codes are Aimia chart-of-accounts values, populated by Finance. This module
provides resolution (category -> gl_code) and the maintenance helpers used by
the admin screen. It deliberately holds NO real codes — those are entered by
Finance and stored in the `category_codes` table.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category, CategoryCode, utc_now


def ensure_category_rows(db: Session) -> None:
    """Create an (empty) row for every Category so Finance can fill codes in."""
    existing = {row.category for row in db.scalars(select(CategoryCode)).all()}
    created = False
    for category in Category:
        if category not in existing:
            db.add(CategoryCode(category=category, gl_code="", active=True))
            created = True
    if created:
        db.commit()


def gl_code_map(db: Session) -> dict[Category, str]:
    """Return {Category: gl_code} for active rows with a non-empty code."""
    rows = db.scalars(select(CategoryCode).where(CategoryCode.active == True)).all()  # noqa: E712
    return {r.category: r.gl_code for r in rows if (r.gl_code or "").strip()}


def gl_code_for(db: Session, category: Category | None) -> str:
    if category is None:
        return ""
    return gl_code_map(db).get(category, "")


def serialize_category_codes(db: Session) -> list[dict]:
    ensure_category_rows(db)
    rows = db.scalars(select(CategoryCode)).all()
    by_cat = {r.category: r for r in rows}
    out = []
    for category in Category:
        row = by_cat.get(category)
        out.append(
            {
                "category": category.value,
                "label": category.value.replace("_", " ").title(),
                "gl_code": (row.gl_code if row else "") or "",
                "description": (row.description if row else "") or "",
                "active": bool(row.active) if row else True,
            }
        )
    return out


def update_category_code(
    db: Session,
    category_value: str,
    gl_code: str,
    description: str = "",
    active: bool = True,
) -> CategoryCode:
    try:
        category = Category(category_value)
    except ValueError as exc:
        raise ValueError(f"Unknown category: {category_value}") from exc

    row = db.scalar(select(CategoryCode).where(CategoryCode.category == category))
    if not row:
        row = CategoryCode(category=category)
        db.add(row)
    row.gl_code = (gl_code or "").strip()
    row.description = (description or "").strip()
    row.active = bool(active)
    row.updated_at = utc_now()
    db.commit()
    return row
