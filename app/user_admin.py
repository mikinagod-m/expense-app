"""Serialize and validate user role / privilege updates."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import user_is_manager
from .models import User


def user_can_claim_period(user: User, period) -> bool:
    from .models import ClaimType

    if period.type == ClaimType.card:
        return user.has_credit_card
    return user.can_claim_cash


def user_roles(db: Session, user: User) -> list[str]:
    roles = ["claimant"]
    if user_is_manager(db, user):
        roles.append("manager")
    if user.is_finance:
        roles.append("finance")
    if user.is_admin:
        roles.append("admin")
    return roles


def serialize_user_row(db: Session, user: User) -> dict:
    manager = user.manager
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "manager_id": user.manager_id,
        "manager_name": manager.name if manager else "",
        "is_finance": user.is_finance,
        "is_admin": user.is_admin,
        "has_credit_card": user.has_credit_card,
        "can_claim_cash": user.can_claim_cash,
        "is_sales_team": user.is_sales_team,
        "roles": user_roles(db, user),
        "direct_reports": db.scalar(
            select(func.count()).select_from(User).where(User.manager_id == user.id)
        )
        or 0,
    }


def parse_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def validate_manager_id(user: User, manager_id: int | None, db: Session) -> int | None:
    if manager_id is None:
        return None
    if manager_id == user.id:
        raise ValueError("A user cannot be their own manager.")
    manager = db.get(User, manager_id)
    if not manager:
        raise ValueError("Selected manager was not found.")
    return manager_id


def validate_new_user(name: str, email: str, db: Session) -> tuple[str, str]:
    clean_name = name.strip()
    clean_email = email.strip().lower()
    if not clean_name:
        raise ValueError("Name is required.")
    if not clean_email or "@" not in clean_email:
        raise ValueError("Enter a valid email address.")
    existing = db.scalar(select(User).where(User.email == clean_email))
    if existing:
        raise ValueError("A user with that email already exists.")
    return clean_name, clean_email
