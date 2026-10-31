"""Accounts (Module Phase 6): receipts and supplier payments.

A receipt is money received from a distributor against an issued tax invoice; a
payment is money paid to a supplier against a purchase order whose goods have
been received. Both are append-only: a mistake is corrected by recording the
opposite entry with a note, never by editing or deleting the original, so the
outstanding figures can always be rebuilt from the documents.

The ledger itself is derived, not stored. `app/services/accounts.py` turns the
issued invoices, credit and debit notes, receipts, payments and received purchase
orders into a party statement and a trial balance, so there is no second set of
numbers to keep in step with the documents.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base
from .core import MONEY

RECEIPT = "receipt"
PAYMENT = "payment"
KINDS = (RECEIPT, PAYMENT)

# The modes the screen offers. A mode decides which account the money moved in or
# out of: cash stays in Cash, everything else is Bank.
MODES = ("cash", "bank", "upi", "cheque", "neft", "other")


class Payment(Base):
    """One receipt from a distributor, or one payment to a supplier."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("kind IN ('receipt','payment')", name="ck_payment_kind"),
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        CheckConstraint(
            "(kind = 'receipt' AND distributor_id IS NOT NULL AND supplier_id IS NULL) "
            "OR (kind = 'payment' AND supplier_id IS NOT NULL AND distributor_id IS NULL)",
            name="ck_payment_party"),
        CheckConstraint("mode IN ('cash','bank','upi','cheque','neft','other')",
                        name="ck_payment_mode"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)
    # Exactly one of these is set, decided by `kind`.
    distributor_id: Mapped[int | None] = mapped_column(ForeignKey("distributors.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    # What the money settles. A receipt may arrive before the allocation is
    # known, so both references are nullable: an unallocated entry still moves
    # the bank balance and still shows in the party statement.
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    paid_on: Mapped[date] = mapped_column(Date, index=True)
    mode: Mapped[str] = mapped_column(String(10), default="bank")
    reference: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    distributor = relationship("Distributor", lazy="selectin")
    supplier = relationship("Supplier", lazy="selectin")
    invoice = relationship("Invoice", lazy="selectin")

    @property
    def number(self) -> str:
        """A stable, human-readable reference; derived, never stored."""
        return f"{'RCPT' if self.kind == RECEIPT else 'PAY'}-{self.id:06d}"
