"""Module Phase 2: suppliers, goods receipt notes and partial receipts (FR-04, D8, D9).

- `Supplier` is the party master. Its `kind` says whether the party is a
  supplier, a manufacturer or both (decision D9). A supplier that was created
  from a legacy free-text purchase-order name is flagged `needs_completion`
  so somebody fills in its tax details.
- Bank details never change through a plain edit: a change is requested with
  `supplier:bank`, stored as an approval request, and applied only when a
  different person approves it (FR-04, FR-10).
- `GoodsReceipt` is one delivery against a purchase order; `GoodsReceiptLine`
  records what arrived, in which batch. A purchase order can therefore be
  received in parts (decision D8), and each receipt posts its own ledger
  movements exactly once.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric,
                        String, UniqueConstraint, func, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base

MONEY = Numeric(14, 2)
QTY = Numeric(14, 3)


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint("registration_type IN ('regular','composition','unregistered')",
                        name="ck_supplier_registration_type"),
        CheckConstraint("kind IN ('supplier','manufacturer','both')", name="ck_supplier_kind"),
        CheckConstraint("status IN ('active','blocked')", name="ck_supplier_status"),
        CheckConstraint("payment_terms_days >= 0", name="ck_supplier_terms_nonneg"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    kind: Mapped[str] = mapped_column(String(20), default="supplier")
    registration_type: Mapped[str] = mapped_column(String(20), default="regular")
    gstin: Mapped[str | None] = mapped_column(String(15), unique=True)
    pan: Mapped[str | None] = mapped_column(String(10))
    # nullable: a supplier migrated from a legacy free-text order has no known
    # state yet and carries needs_completion=true until somebody supplies it
    state_code: Mapped[str | None] = mapped_column(String(2))
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(20), default="active")
    needs_completion: Mapped[bool] = mapped_column(Boolean, default=False)
    # bank details are permission-restricted and only change through the approval flow
    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_account_no: Mapped[str | None] = mapped_column(String(30))
    bank_ifsc: Mapped[str | None] = mapped_column(String(11))
    bank_holder: Mapped[str | None] = mapped_column(String(120))
    bank_approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    bank_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="supplier_rel")


class GoodsReceipt(Base):
    """One delivery against a purchase order (D8). Posts one ledger movement per
    line with ref_type 'grn' and ref_id = this receipt's id.

    A client may quote the supplier's delivery-note number; it is unique per
    purchase order, so a retried delivery cannot be received twice even when
    the quantities alone would still fit inside the ordered quantity."""
    __tablename__ = "goods_receipts"
    __table_args__ = (
        Index("uq_grn_delivery_note", "po_id", "delivery_note", unique=True,
              postgresql_where=text("delivery_note IS NOT NULL")),
        CheckConstraint("owner IN ('HERBANOVA','MANUFACTURER')", name="ck_grn_owner"),
        Index("ix_goods_receipts_received_at", "received_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    grn_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    received_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    owner: Mapped[str] = mapped_column(String(20), default="HERBANOVA")   # HERBANOVA | MANUFACTURER
    delivery_note: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(String(300))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lines: Mapped[list["GoodsReceiptLine"]] = relationship(
        back_populates="receipt", lazy="selectin", cascade="all, delete-orphan")


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"
    __table_args__ = (
        UniqueConstraint("grn_id", "batch_id", name="uq_grn_line_batch"),
        CheckConstraint("qty > 0", name="ck_grn_line_qty_positive"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    grn_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    receipt: Mapped[GoodsReceipt] = relationship(back_populates="lines")
