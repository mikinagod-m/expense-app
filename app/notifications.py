"""Optional SMTP notifications for claim workflow events."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from .config import settings
from .models import Claim, User

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool(settings.smtp_host.strip() and settings.smtp_from.strip())


def send_email(to_email: str, subject: str, body: str) -> bool:
    if not to_email:
        return False
    if not smtp_configured():
        logger.info("Notification (SMTP not configured): to=%s subject=%s", to_email, subject)
        logger.debug("Notification body: %s", body)
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
    logger.info("Notification sent: to=%s subject=%s", to_email, subject)
    return True


def _app_url(path: str) -> str:
    base = settings.app_base_url.rstrip("/")
    return f"{base}{path}"


def notify_manager_claim_submitted(db: Session, claim: Claim) -> bool:
    manager = db.get(User, claim.user.manager_id) if claim.user.manager_id else None
    if not manager or not manager.email:
        logger.info("No manager email for claim_id=%s; skip submit notification", claim.id)
        return False
    subject = f"Expense claim awaiting approval — {claim.unique_ref or claim.id}"
    body = (
        f"{claim.user.name} submitted a {claim.type.value} expense claim.\n\n"
        f"Reference: {claim.unique_ref}\n"
        f"Period: {claim.period.month:02d}/{claim.period.year}\n"
        f"Total: £{claim.gross_total:.2f}\n\n"
        f"Review in Aimia Expenses:\n{_app_url('/manager/approvals')}\n"
    )
    return send_email(manager.email, subject, body)


def notify_claimant_decision(
    db: Session,
    claim: Claim,
    reviewer: User,
    decision: str,
    comment: str,
) -> bool:
    claimant = claim.user
    if not claimant.email:
        return False
    ref = claim.unique_ref or str(claim.id)
    if decision == "approved":
        subject = f"Expense claim approved — {ref}"
        body = (
            f"Your expense claim was approved by {reviewer.name}.\n\n"
            f"Reference: {ref}\n"
            f"Total: £{claim.gross_total:.2f}\n"
        )
        if comment:
            body += f"\nComment: {comment}\n"
    else:
        subject = f"Expense claim rejected — {ref}"
        body = (
            f"Your expense claim was rejected by {reviewer.name}.\n\n"
            f"Reference: {ref}\n"
            f"Reason: {comment or 'No comment provided.'}\n"
        )
    body += f"\nView claim:\n{_app_url(f'/claims/{claim.id}')}\n"
    return send_email(claimant.email, subject, body)


def notify_claimant_processed(db: Session, claim: Claim, finance_user: User) -> bool:
    claimant = claim.user
    if not claimant.email:
        return False
    ref = claim.unique_ref or str(claim.id)
    subject = f"Expense claim processed — {ref}"
    body = (
        f"Your expense claim has been marked processed by finance ({finance_user.name}).\n\n"
        f"Reference: {ref}\n"
        f"Total: £{claim.gross_total:.2f}\n\n"
        f"View claim:\n{_app_url(f'/claims/{claim.id}')}\n"
    )
    return send_email(claimant.email, subject, body)
