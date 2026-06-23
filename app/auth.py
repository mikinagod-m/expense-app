"""
Auth: Microsoft 365 / Azure AD via OIDC (Authlib), with a DEV_LOGIN bypass
so you can run the whole app locally before wiring up Azure.

On real login, the Azure AD profile (name, email, oid) is upserted into the
`users` table — this is what replaces the old 'Employee Database' tab.
"""
from fastapi import Request, HTTPException
from sqlalchemy import select

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


# --- Azure AD OIDC (used when DEV_LOGIN=0) ---
def build_oauth():
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
