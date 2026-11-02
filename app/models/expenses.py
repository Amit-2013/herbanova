"""Expenses: heads, recorded entries, their approval settings and receipts.

An expense is money spent that is not a supplier payment for stock. It carries a
net amount and, separately, the GST paid on it: creditable GST is not a cost,
non-creditable GST is. Entries are never edited or deleted. A recorded entry is
corrected by reversing it with a reason; the reversed row stays with its amount
intact so the audit trail can be rebuilt.

An entry above the configured threshold waits as `pending_approval` and is not
expenses in any report until an approver other than the person who raised it
decides it. The threshold switch and amount live in the single `expense_settings`
row, editable by the Administrator only.

`tracked_from` is the date the business started recording expenses. A report
window before it has a gap, not a zero, because "no rows" then means "not
recorded" rather than "nothing spent".
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
                        String, func, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base
from .accounts import MODES
from .core import MONEY

PENDING = "pending_approval"
APPROVED = "approved"
REJECTED = "rejected"
REVERSED = "reversed"
STATUSES = (PENDING, APPROVED, REJECTED, REVERSED)

SYSTEM_PAYROLL_HEAD = "Payroll (from HR)"


class ExpenseHead(Base):
    """A heading an expense is booked to. The payroll head is created by the
    migration, is read-only, and refuses manual entries: payroll reaches the
    profit and loss only from the HR payroll register."""
    __tablename__ = "expense_heads"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False,
                                            server_default=text("true"))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False,
                                            server_default=text("false"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())


class ExpenseSettings(Base):
    """One row: the approval switch and amount, and when expenses started being
    recorded. Never inferred from the entries themselves."""
    __tablename__ = "expense_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_expense_settings_single"),
        CheckConstraint("approval_threshold >= 0", name="ck_expense_threshold_nonneg"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    approval_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False,
                                                   server_default=text("false"))
    approval_threshold: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False,
                                                        server_default="0")
    tracked_from: Mapped[date] = mapped_column(Date, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(),
                                                 onupdate=func.now())


class Expense(Base):
    """One recorded expense. `amount` excludes GST; `gst_amount` is stored
    separately and only becomes cost when it is not creditable."""
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expense_amount_positive"),
        CheckConstraint("gst_amount >= 0", name="ck_expense_gst_nonneg"),
        CheckConstraint("mode IN ('cash','bank','upi','cheque','neft','other')",
                        name="ck_expense_mode"),
        CheckConstraint("status IN ('pending_approval','approved','rejected','reversed')",
                        name="ck_expense_status"),
        CheckConstraint(
            "status <> 'reversed' OR (reversed_at IS NOT NULL "
            "AND reversal_reason IS NOT NULL)", name="ck_expense_reversal_fields"),
        Index("ix_expenses_entry_date", "entry_date"),
        Index("ix_expenses_status_date", "status", "entry_date"),
        Index("ix_expenses_head", "head_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    head_id: Mapped[int] = mapped_column(ForeignKey("expense_heads.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    gst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False,
                                                server_default="0")
    gst_creditable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False,
                                                 server_default=text("true"))
    mode: Mapped[str] = mapped_column(String(10), default="bank")
    reference: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(String(300))
    attachment_path: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default=APPROVED,
                                        server_default=text("'approved'"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_reason: Mapped[str | None] = mapped_column(String(300))
    approval_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("approval_requests.id"))

    head = relationship("ExpenseHead", lazy="selectin")

    @property
    def number(self) -> str:
        """A stable, human-readable reference; derived, never stored."""
        return f"EXP-{self.id:06d}"

    @property
    def total(self) -> Decimal:
        """Cash value: net amount plus the GST paid."""
        return (Decimal(self.amount or 0) + Decimal(self.gst_amount or 0)).quantize(
            Decimal("0.01"))

    @property
    def deductible_amount(self) -> Decimal:
        """What the profit and loss carries: net plus GST only when not creditable."""
        gst = Decimal(self.gst_amount or 0)
        return (Decimal(self.amount or 0)
                + (Decimal("0") if self.gst_creditable else gst)).quantize(
            Decimal("0.01"))
