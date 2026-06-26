"""
Data model for the expense app.

The key idea that removes the whole monthly-rollover / VBA-editing pain:
claims belong to a *period* (a row), not to a *file*. Rolling into a new
month is just creating a new `Period` row — no macro edits, no renaming,
no wiping transactions.
"""
import datetime as dt
import enum

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class ClaimType(str, enum.Enum):
    cash = "cash"
    card = "card"


class ClaimStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"
    processed = "processed"


class Category(str, enum.Enum):
    # Mirrors the cost columns on the existing credit-card form.
    hotel = "hotel"
    subsistence = "subsistence"
    travel = "travel"
    foreign_travel = "foreign_travel"
    postage = "postage"
    staff_entertaining = "staff_entertaining"
    customer_entertaining = "customer_entertaining"
    other = "other"
    personal = "personal"  # deduction


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    # `aad_oid` is the stable Azure AD object id — populated on first login.
    aad_oid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    can_claim_cash: Mapped[bool] = mapped_column(Boolean, default=True)
    has_credit_card: Mapped[bool] = mapped_column(Boolean, default=False)
    is_finance: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    manager: Mapped["User"] = relationship(remote_side=[id])
    claims: Mapped[list["Claim"]] = relationship(back_populates="user",
                                                 foreign_keys="Claim.user_id")


class Period(Base):
    __tablename__ = "periods"
    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)  # 1-12, the month claimed FOR
    type: Mapped[ClaimType] = mapped_column(Enum(ClaimType))
    deadline: Mapped[dt.date] = mapped_column(Date)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"))
    type: Mapped[ClaimType] = mapped_column(Enum(ClaimType))
    status: Mapped[ClaimStatus] = mapped_column(Enum(ClaimStatus),
                                                default=ClaimStatus.draft)
    # Replaces the VBA-generated unique form number (period + sequence).
    unique_ref: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    signed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="claims",
                                        foreign_keys=[user_id])
    approver: Mapped["User | None"] = relationship(foreign_keys=[approved_by])
    period: Mapped["Period"] = relationship()
    lines: Mapped[list["ClaimLine"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan")

    @property
    def gross_total(self) -> float:
        return round(sum(l.amount for l in self.lines), 2)


class ClaimLine(Base):
    __tablename__ = "claim_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    narrative: Mapped[str] = mapped_column(Text, default="")
    receipt_ref: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[Category] = mapped_column(Enum(Category), default=Category.other)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    reclaim_vat: Mapped[bool] = mapped_column(Boolean, default=False)
    vat_amount: Mapped[float] = mapped_column(Float, default=0.0)
    unauthorised_amount: Mapped[float] = mapped_column(Float, default=0.0)

    claim: Mapped["Claim"] = relationship(back_populates="lines")
    receipt: Mapped["Receipt"] = relationship(
        back_populates="line", uselist=False, cascade="all, delete-orphan")
    statement_line: Mapped["StatementLine | None"] = relationship(
        back_populates="claim_line", uselist=False)


class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_line_id: Mapped[int] = mapped_column(ForeignKey("claim_lines.id"))
    file_path: Mapped[str] = mapped_column(String(500))
    ocr_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ocr_merchant: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ocr_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    line: Mapped["ClaimLine"] = relationship(back_populates="receipt")


class AuditLog(Base):
    """Replaces the hidden-tab / password-protection 'security' with a real trail."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")


class StatementLine(Base):
    __tablename__ = "statement_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    posted_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    cardholder_name: Mapped[str] = mapped_column(String(200), default="")
    merchant: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="GBP")
    claim_line_id: Mapped[int | None] = mapped_column(ForeignKey("claim_lines.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    claim_line: Mapped["ClaimLine | None"] = relationship(back_populates="statement_line")
