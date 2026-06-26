"""
Auth: Microsoft 365 / Azure AD via OIDC (Authlib), with a DEV_LOGIN bypass
so you can run the whole app locally before wiring up Azure.

On real login, the Azure AD profile (name, email, oid) is upserted into the
`users` table — this is what replaces the old 'Employee Database' tab.
"""
from fastapi import Request, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import User


def current_user(request: Request) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    with SessionLocal() as db:
        return db.get(User, uid)


def require_user(request: Request) -> User:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


def user_is_manager(db: Session, user: User) -> bool:
    """A user is treated as manager when at least one user reports to them."""
    return db.scalar(select(User.id).where(User.manager_id == user.id).limit(1)) is not None


def require_manager_or_finance(request: Request, db: Session) -> User:
    user = require_user(request)
    if user.is_finance or user_is_manager(db, user):
        return user
    raise HTTPException(status_code=403, detail="Manager or finance role required")


def require_finance(request: Request) -> User:
    user = require_user(request)
    if user.is_finance:
        return user
    raise HTTPException(status_code=403, detail="Finance role required")


def require_admin(request: Request) -> User:
    user = require_user(request)
    if user.is_admin:
        return user
    raise HTTPException(status_code=403, detail="Admin role required")


# --- Azure AD OIDC (used when DEV_LOGIN=0) ---
def missing_aad_settings() -> list[str]:
    missing = []
    if not settings.aad_tenant_id.strip():
        missing.append("AAD_TENANT_ID")
    if not settings.aad_client_id.strip():
        missing.append("AAD_CLIENT_ID")
    if not settings.aad_client_secret.strip():
        missing.append("AAD_CLIENT_SECRET")
    if not settings.aad_redirect_uri.strip():
        missing.append("AAD_REDIRECT_URI")
    return missing


def build_oauth():
    missing = missing_aad_settings()
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Azure AD auth is not configured. Missing: {joined}")

    from authlib.integrations.starlette_client import OAuth
    oauth = OAuth()
    oauth.register(
        name="aad",
        client_id=settings.aad_client_id,
        client_secret=settings.aad_client_secret,
        server_metadata_url=(
            f"https://login.microsoftonline.com/{settings.aad_tenant_id}"
            "/v2.0/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid email profile User.Read"},
    )
    return oauth


def upsert_user_from_claims(claims: dict) -> int:
    """Map AAD token claims onto a User row, return user id."""
    oid = claims.get("oid") or claims.get("sub")
    email = claims.get("email") or claims.get("preferred_username", "")
    name = claims.get("name", email)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.aad_oid == oid))
        if not user:
            user = db.scalar(select(User).where(User.email == email))
        if not user:
            user = User(name=name, email=email)
            db.add(user)
        user.aad_oid = oid
        user.name = name
        user.email = email
        db.commit()
        return user.id
