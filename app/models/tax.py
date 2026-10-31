"""Module Phase 3: the company's own tax identity, the GST rate master and
discount slabs (FR-13).

- `CompanyProfile` is a single row (id = 1, enforced by the API). It carries the
  seller's GSTIN, state and invoice-series prefix, which every later tax
  document needs.
- `TaxRate` is keyed by HSN and effective-dated. No slab is hard-coded: a rate
  change is a new row, and the row in force on the document date is the one
  used. Windows for one HSN may not overlap (checked by the service and, for
  the open-ended case, by a partial unique index).
- `DiscountSlab` holds the discount policy as data: a quantity or value band,
  optionally limited to one product or one territory, with the discount
  percentage and the percentage above which a second person must approve.

Rates and slabs are data, not tax advice. The business's tax adviser confirms
HSN codes and rates before go-live (BRD Appendix B, evidence E-022).
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric,
                        String, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base

RATE = Numeric(5, 2)      # a percentage, two decimals is plenty (2.50, 0.25, 18.00)
MONEY = Numeric(14, 2)
QTY = Numeric(14, 3)


class CompanyProfile(Base):
    """The seller. One row, because there is one legal entity issuing documents."""
    __tablename__ = "company_profile"
    __table_args__ = (
        CheckConstraint("state_code IS NULL OR length(state_code) = 2", name="ck_company_state_code"),
        CheckConstraint("registration_type IN ('regular','composition','unregistered')",
                        name="ck_company_registration_type"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15), unique=True)
    pan: Mapped[str | None] = mapped_column(String(10))
    state_code: Mapped[str | None] = mapped_column(String(2))
    registration_type: Mapped[str] = mapped_column(String(20), default="regular")
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    pincode: Mapped[str | None] = mapped_column(String(6))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(150))
    invoice_prefix: Mapped[str | None] = mapped_column(String(10))
    # Bank details for the invoice. Account numbers are sensitive: they are
    # written here for the invoice to print, and are never put in a log or an
    # export (FR-13, and the audit rules in FR-12).
    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_account_name: Mapped[str | None] = mapped_column(String(150))
    bank_account_number: Mapped[str | None] = mapped_column(String(40))
    bank_ifsc: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class TaxRate(Base):
    """One GST rate for one HSN, in force from a date (FR-13).

    The split is stored explicitly rather than derived so that unusual
    combinations (an uneven CGST/SGST split, or an item that is IGST-only) are
    data, not a code change. `cgst + sgst = igst` is enforced by the database.
    """
    __tablename__ = "tax_rates"
    __table_args__ = (
        # the digits-only rule is enforced by the API; the database check stays
        # portable (the same model is also created in SQLite by the tests)
        CheckConstraint("length(hsn) BETWEEN 4 AND 8", name="ck_tax_rate_hsn_digits"),
        CheckConstraint("cgst_rate >= 0 AND sgst_rate >= 0 AND igst_rate >= 0 AND cess_rate >= 0",
                        name="ck_tax_rate_nonneg"),
        CheckConstraint("cgst_rate + sgst_rate = igst_rate", name="ck_tax_rate_split"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                        name="ck_tax_rate_window"),
        Index("ix_tax_rates_hsn_from", "hsn", "effective_from"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    hsn: Mapped[str] = mapped_column(String(8))
    description: Mapped[str | None] = mapped_column(String(200))
    cgst_rate: Mapped[Decimal] = mapped_column(RATE)
    sgst_rate: Mapped[Decimal] = mapped_column(RATE)
    igst_rate: Mapped[Decimal] = mapped_column(RATE)
    cess_rate: Mapped[Decimal] = mapped_column(RATE, default=0)
    # reverse charge: the buyer pays the tax, so the seller does not collect it
    is_reverse_charge: Mapped[bool] = mapped_column(Boolean, default=False)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)      # NULL = still in force
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DiscountSlab(Base):
    """Discount policy as data (FR-13): a band of quantity or value, an optional
    product or distributor group, the discount, and the percentage above which a
    second person must approve it."""
    __tablename__ = "discount_slabs"
    __table_args__ = (
        CheckConstraint("scope IN ('all','product','group')", name="ck_discount_slab_scope"),
        CheckConstraint("discount_percent >= 0 AND discount_percent <= 100",
                        name="ck_discount_slab_percent"),
        CheckConstraint("approval_above IS NULL OR (approval_above >= 0 AND approval_above <= 100)",
                        name="ck_discount_slab_approval"),
        CheckConstraint("min_qty IS NOT NULL OR min_value IS NOT NULL", name="ck_discount_slab_bound"),
        CheckConstraint("min_qty IS NULL OR min_qty > 0", name="ck_discount_slab_min_qty"),
        CheckConstraint("min_value IS NULL OR min_value > 0", name="ck_discount_slab_min_value"),
        CheckConstraint("max_qty IS NULL OR min_qty IS NULL OR max_qty >= min_qty",
                        name="ck_discount_slab_qty_band"),
        CheckConstraint("max_value IS NULL OR min_value IS NULL OR max_value >= min_value",
                        name="ck_discount_slab_value_band"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                        name="ck_discount_slab_window"),
        CheckConstraint("(scope <> 'product' OR product_id IS NOT NULL)", name="ck_discount_slab_product"),
        CheckConstraint("(scope <> 'group' OR group_name IS NOT NULL)", name="ck_discount_slab_group"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(20), default="all")     # all | product | group
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    group_name: Mapped[str | None] = mapped_column(String(60))       # distributor group
    min_qty: Mapped[Decimal | None] = mapped_column(QTY)
    max_qty: Mapped[Decimal | None] = mapped_column(QTY)
    min_value: Mapped[Decimal | None] = mapped_column(MONEY)
    max_value: Mapped[Decimal | None] = mapped_column(MONEY)
    discount_percent: Mapped[Decimal] = mapped_column(RATE)
    approval_above: Mapped[Decimal | None] = mapped_column(RATE)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    product = relationship("Product", lazy="selectin")
