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

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
                        Integer, Numeric, String, UniqueConstraint, func, text)
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


class PaymentAllocation(Base):
    """How much of one receipt or payment settled one invoice or purchase order.

    A receipt may settle several invoices and an advance may settle an invoice
    issued later, so the link cannot live on the payment row. The payment's
    amount minus its allocations is the advance still available to the party;
    the allocations are dated so a statement can tell an advance from a
    settlement at any point in time. Rows are append-only, like the payment
    they belong to.
    """

    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint(
            "(invoice_id IS NOT NULL AND purchase_order_id IS NULL) "
            "OR (invoice_id IS NULL AND purchase_order_id IS NOT NULL)",
            name="ck_payment_allocation_target"),
        CheckConstraint("amount > 0", name="ck_payment_allocation_amount"),
        Index("uq_payment_allocation_invoice", "payment_id", "invoice_id",
              unique=True, postgresql_where=text("invoice_id IS NOT NULL")),
        Index("uq_payment_allocation_order", "payment_id", "purchase_order_id",
              unique=True, postgresql_where="purchase_order_id IS NOT NULL"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    purchase_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    # The day the money stopped being an advance and started settling this
    # document: the payment day for a settlement, the document's own date when
    # an earlier advance is applied to a later invoice.
    applied_on: Mapped[date] = mapped_column(Date, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    payment = relationship("Payment", lazy="selectin")
    invoice = relationship("Invoice", lazy="selectin")
    purchase_order = relationship("PurchaseOrder", lazy="selectin")


class FinancialYearClose(Base):
    """A closed financial year (April to March), with who closed it and why.

    Closing is a statement about the books, not a deletion: every document stays
    and every report still reads it. What changes is that a document dated inside
    the year can no longer be created, cancelled or amended until an
    Administrator reopens the year with a reason. A close is separate from the
    accounting month locks in `hr_period_locks`: those freeze one month for cost
    and expense work, this freezes a whole year for every dated accounting
    document.
    """
    __tablename__ = "financial_year_closes"
    __table_args__ = (
        CheckConstraint("length(financial_year) = 7", name="ck_fy_close_label"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    financial_year: Mapped[str] = mapped_column(String(9), unique=True)  # 2025-26
    active: Mapped[bool] = mapped_column(default=True)
    reason: Mapped[str] = mapped_column(String(300))
    closed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                server_default=func.now())
    reopened_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopen_reason: Mapped[str | None] = mapped_column(String(300))


class PurchaseInvoice(Base):
    """A supplier's tax invoice, captured for input GST (GAP-A05).

    It is deliberately not a payable: payables stay the cost of goods received
    minus payments, so capturing a bill never moves an outstanding balance. It
    records the tax the supplier actually charged, which is the only honest
    source of input tax - a purchase order carries a cost, not a tax split.
    A wrong entry is reversed with a reason and excluded from the register; it is
    never edited or deleted.
    """
    __tablename__ = "purchase_invoices"
    __table_args__ = (
        CheckConstraint("taxable_value >= 0 AND cgst_amount >= 0 AND sgst_amount >= 0 "
                        "AND igst_amount >= 0 AND cess_amount >= 0 AND tds_amount >= 0",
                        name="ck_purchase_invoice_amounts"),
        CheckConstraint("tds_rate IS NULL OR (tds_rate >= 0 AND tds_rate <= 100)",
                        name="ck_purchase_invoice_tds_rate"),
        CheckConstraint("status IN ('posted','reversed')", name="ck_purchase_invoice_status"),
        CheckConstraint("status = 'posted' OR reversal_reason IS NOT NULL",
                        name="ck_purchase_invoice_reversal_reason"),
        # A bill number is unique per supplier while it is posted; a reversed
        # entry may be corrected by posting the same number again.
        Index("uq_purchase_invoice_number", "supplier_id", "supplier_invoice_number",
              unique=True, postgresql_where=text("status = 'posted'")),
        Index("ix_purchase_invoices_date", "invoice_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))
    supplier_invoice_number: Mapped[str] = mapped_column(String(40))
    invoice_date: Mapped[date] = mapped_column(Date)
    taxable_value: Mapped[Decimal] = mapped_column(MONEY)
    cgst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    igst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    cess_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    # A signed rounding line, exactly like a sales invoice, so the bill total
    # can be reproduced without an assumed paisa.
    round_off: Mapped[Decimal] = mapped_column(MONEY, default=0)
    itc_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    tds_section: Mapped[str | None] = mapped_column(String(10))
    tds_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    tds_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    status: Mapped[str] = mapped_column(String(10), default="posted")
    reversal_reason: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    supplier = relationship("Supplier", lazy="selectin")

    @property
    def number(self) -> str:
        """A stable, human-readable reference; derived, never stored."""
        return f"PUR-{self.id:06d}"

    @property
    def tax_total(self) -> Decimal:
        return (Decimal(self.cgst_amount or 0) + Decimal(self.sgst_amount or 0)
                + Decimal(self.igst_amount or 0) + Decimal(self.cess_amount or 0))

    @property
    def total(self) -> Decimal:
        return (Decimal(self.taxable_value or 0) + self.tax_total
                + Decimal(self.round_off or 0))


class GstReturn(Base):
    """Figures as filed on the GST portal, for one month and one form (GAP-A06).

    The application never files and never guesses what was filed: this table
    holds what the practitioner reports was filed, so the registers can be
    compared with it. A figure can be replaced with the correction trail kept in
    the audit log; there is no second return for the same month and form.
    """
    __tablename__ = "gst_returns"
    __table_args__ = (
        UniqueConstraint("form", "year", "month", name="uq_gst_return_period"),
        CheckConstraint("form IN ('GSTR-1','GSTR-3B')", name="ck_gst_return_form"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_gst_return_month"),
        CheckConstraint(
            "outward_taxable >= 0 AND outward_cgst >= 0 AND outward_sgst >= 0 "
            "AND outward_igst >= 0 AND outward_cess >= 0 AND itc_cgst >= 0 "
            "AND itc_sgst >= 0 AND itc_igst >= 0 AND itc_cess >= 0",
            name="ck_gst_return_amounts"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    form: Mapped[str] = mapped_column(String(10))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    filed_on: Mapped[date] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(String(40))   # ARN or acknowledgement
    outward_taxable: Mapped[Decimal] = mapped_column(MONEY, default=0)
    outward_cgst: Mapped[Decimal] = mapped_column(MONEY, default=0)
    outward_sgst: Mapped[Decimal] = mapped_column(MONEY, default=0)
    outward_igst: Mapped[Decimal] = mapped_column(MONEY, default=0)
    outward_cess: Mapped[Decimal] = mapped_column(MONEY, default=0)
    itc_cgst: Mapped[Decimal] = mapped_column(MONEY, default=0)
    itc_sgst: Mapped[Decimal] = mapped_column(MONEY, default=0)
    itc_igst: Mapped[Decimal] = mapped_column(MONEY, default=0)
    itc_cess: Mapped[Decimal] = mapped_column(MONEY, default=0)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StatutoryChallan(Base):
    """One deposit of deducted tax or payroll statutory dues (GAP-A07).

    A challan is evidence of money paid to the government, recorded by the
    accounts desk. It is append-only: nothing is edited, and the dues report
    subtracts what is recorded from what was deducted, naming any shortfall
    rather than assuming it was paid.
    """
    __tablename__ = "statutory_challans"
    __table_args__ = (
        CheckConstraint("kind IN ('tds','pf','esi','pt')", name="ck_challan_kind"),
        CheckConstraint("amount > 0", name="ck_challan_amount"),
        CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_challan_month"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)
    bsr_code: Mapped[str | None] = mapped_column(String(10))
    challan_number: Mapped[str] = mapped_column(String(30))
    paid_on: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    period_year: Mapped[int] = mapped_column(Integer)
    period_month: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())


# ---------------------------------------------------------------- ledger (A08-A10)
# The voucher ledger is the one stored set of postings. It stays separate from
# the document-derived trial balance: a document remains the source for its own
# figures, and a voucher only changes what a person posted. The balance sheet
# merges the two by ledger head, so nothing is counted twice.
LEDGER_TYPES = ("asset", "liability", "equity", "income", "expense")
# `role` ties a head to a document bucket. The seeded heads carry the roles the
# derived trial balance already uses; a head without a role receives vouchers
# and opening balances only.
LEDGER_ROLES = ("cash", "bank", "receivables", "payables", "output_gst",
                "capital", "sales", "purchases", "round_off")
VOUCHER_TYPES = ("journal", "receipt", "payment", "contra")
VOUCHER_STATUSES = ("draft", "posted", "reversed")


class LedgerAccount(Base):
    """One head in the chart of accounts.

    The seeded heads mirror the buckets the documents already produce, so the
    balance sheet can add document postings to the same rows. Extra heads
    (loans, fixed assets and so on) are created by an Administrator and receive
    only opening balances and vouchers. A head is deactivated, never deleted,
    so a voucher can always name the account it posted to.
    """
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        CheckConstraint("type IN ('asset','liability','equity','income','expense')",
                        name="ck_ledger_account_type"),
        CheckConstraint("role IS NULL OR role IN ('cash','bank','receivables',"
                        "'payables','output_gst','capital','sales','purchases',"
                        "'round_off')", name="ck_ledger_account_role"),
        Index("uq_ledger_account_code", "code", unique=True),
        Index("uq_ledger_account_name", "name", unique=True),
        Index("uq_ledger_account_role", "role", unique=True,
              postgresql_where=text("role IS NOT NULL")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(12))
    role: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())


class OpeningBalance(Base):
    """The position carried into a financial year, one row per head.

    This is captured, never derived: a closing balance cannot be produced from
    documents that start after the books do. Debit and credit are stored as
    entered, so an unbalanced opening trial balance is shown as a difference
    rather than silently plugged.
    """
    __tablename__ = "opening_balances"
    __table_args__ = (
        UniqueConstraint("ledger_account_id", "financial_year",
                         name="uq_opening_balance_year"),
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_opening_amounts"),
        CheckConstraint("(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
                        name="ck_opening_one_side"),
        CheckConstraint("length(financial_year) = 7", name="ck_opening_fy_label"),
        Index("ix_opening_balances_account", "ledger_account_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ledger_account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"))
    financial_year: Mapped[str] = mapped_column(String(9))
    debit: Mapped[Decimal] = mapped_column(MONEY, default=0)
    credit: Mapped[Decimal] = mapped_column(MONEY, default=0)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account = relationship("LedgerAccount", lazy="selectin")


class Voucher(Base):
    """A journal, receipt, payment or contra voucher with a posting state (A08).

    A draft may be edited or deleted. Posting freezes it: every line is part of
    the books from then on. A mistake is reversed, which writes the mirror
    voucher and marks the original reversed, so the day book keeps the trail.
    Numbering is derived from the id, like receipts and supplier bills.
    """
    __tablename__ = "vouchers"
    __table_args__ = (
        CheckConstraint("voucher_type IN ('journal','receipt','payment','contra')",
                        name="ck_voucher_type"),
        CheckConstraint("status IN ('draft','posted','reversed')",
                        name="ck_voucher_status"),
        CheckConstraint("status <> 'reversed' OR reversal_reason IS NOT NULL",
                        name="ck_voucher_reversal_reason"),
        CheckConstraint("status <> 'posted' OR posted_at IS NOT NULL",
                        name="ck_voucher_posted_at"),
        Index("ix_vouchers_date", "voucher_date"),
        Index("ix_vouchers_status", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    voucher_date: Mapped[date] = mapped_column(Date)
    voucher_type: Mapped[str] = mapped_column(String(10))
    narration: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="draft")
    reversal_of_id: Mapped[int | None] = mapped_column(ForeignKey("vouchers.id"))
    reversal_reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    posted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines = relationship("VoucherLine", lazy="selectin", cascade="all, delete-orphan",
                         order_by="VoucherLine.id")

    @property
    def number(self) -> str:
        """A stable, human-readable reference; derived, never stored."""
        return f"VCH-{self.id:06d}"

    @property
    def debit_total(self) -> Decimal:
        return sum((Decimal(line.debit or 0) for line in self.lines), Decimal("0"))

    @property
    def credit_total(self) -> Decimal:
        return sum((Decimal(line.credit or 0) for line in self.lines), Decimal("0"))


class VoucherLine(Base):
    """One side of a voucher. Exactly one of debit and credit is positive."""
    __tablename__ = "voucher_lines"
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_voucher_line_amounts"),
        CheckConstraint("(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
                        name="ck_voucher_line_one_side"),
        Index("ix_voucher_lines_voucher", "voucher_id"),
        Index("ix_voucher_lines_account", "ledger_account_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    voucher_id: Mapped[int] = mapped_column(ForeignKey("vouchers.id"))
    ledger_account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"))
    narration: Mapped[str | None] = mapped_column(String(300))
    debit: Mapped[Decimal] = mapped_column(MONEY, default=0)
    credit: Mapped[Decimal] = mapped_column(MONEY, default=0)

    account = relationship("LedgerAccount", lazy="selectin")


class BankStatement(Base):
    """One bank statement period and the balances the bank printed.

    The opening and closing balances are entered from the statement, never
    computed. A line list alone cannot prove the bank's closing figure, so the
    difference between the printed closing and the lines' movement is shown.
    """
    __tablename__ = "bank_statements"
    __table_args__ = (
        CheckConstraint("period_from <= period_to", name="ck_bank_statement_period"),
        UniqueConstraint("ledger_account_id", "period_from", "period_to",
                         name="uq_bank_statement_period"),
        Index("ix_bank_statements_account", "ledger_account_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ledger_account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"))
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    opening_balance: Mapped[Decimal] = mapped_column(MONEY)
    closing_balance: Mapped[Decimal] = mapped_column(MONEY)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    account = relationship("LedgerAccount", lazy="selectin")
    lines = relationship("BankStatementLine", lazy="selectin",
                         cascade="all, delete-orphan",
                         order_by="BankStatementLine.line_date")


class BankStatementLine(Base):
    """One line printed by the bank, matched to at most one book entry.

    `amount` is signed from the business's point of view: a deposit into the
    account is positive, a withdrawal negative. A line matches either a receipt
    or payment, or a voucher line that touches the same bank head.
    """
    __tablename__ = "bank_statement_lines"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="ck_bank_line_amount"),
        CheckConstraint("NOT (matched_payment_id IS NOT NULL AND "
                        "matched_voucher_line_id IS NOT NULL)",
                        name="ck_bank_line_one_match"),
        Index("uq_bank_line_payment", "matched_payment_id", unique=True,
              postgresql_where=text("matched_payment_id IS NOT NULL")),
        Index("uq_bank_line_voucher_line", "matched_voucher_line_id", unique=True,
              postgresql_where=text("matched_voucher_line_id IS NOT NULL")),
        Index("ix_bank_statement_lines_statement", "statement_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("bank_statements.id"))
    line_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(200))
    reference: Mapped[str | None] = mapped_column(String(60))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    matched_payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"))
    matched_voucher_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("voucher_lines.id"))
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matched_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
