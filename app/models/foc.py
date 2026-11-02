"""Free-of-cost (FOC) stock: receipts are marked with `cost_source = 'foc'` on
the existing ledger, and a giveaway is a separate, approved note — never an
invoice. A note has one recipient so the trail names who received the goods;
split a distribution across several notes rather than hiding recipients in
free text.

Nothing here is edited after approval. A mistake is reversed with a reason and
a positive movement back into the same batch; the original rows stay intact.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
                        String, UniqueConstraint, func, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base
from .core import MONEY, QTY

DRAFT = "draft"
APPROVED = "approved"
REJECTED = "rejected"
REVERSED = "reversed"
STATUSES = (DRAFT, APPROVED, REJECTED, REVERSED)

REASONS = ("sample", "promotional", "replacement", "donation", "other")


class FocNote(Base):
    __tablename__ = "foc_notes"
    __table_args__ = (
        CheckConstraint("status IN ('draft','approved','rejected','reversed')",
                        name="ck_foc_note_status"),
        CheckConstraint("reason IN ('sample','promotional','replacement','donation','other')",
                        name="ck_foc_note_reason"),
        CheckConstraint("notional_value IS NULL OR notional_value >= 0",
                        name="ck_foc_note_notional_nonneg"),
        CheckConstraint(
            "status <> 'approved' OR (approved_at IS NOT NULL AND approved_by IS NOT NULL)",
            name="ck_foc_note_approved_fields"),
        CheckConstraint(
            "status <> 'reversed' OR (reversed_at IS NOT NULL "
            "AND reversed_by IS NOT NULL AND reversal_reason IS NOT NULL)",
            name="ck_foc_note_reversed_fields"),
        Index("ix_foc_notes_date", "note_date"),
        Index("ix_foc_notes_status_date", "status", "note_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    note_number: Mapped[str] = mapped_column(String(16), unique=True)
    financial_year: Mapped[str] = mapped_column(String(9))
    note_date: Mapped[date] = mapped_column(Date)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    distributor_id: Mapped[int | None] = mapped_column(ForeignKey("distributors.id"))
    recipient_name: Mapped[str] = mapped_column(String(150))
    recipient_address: Mapped[str | None] = mapped_column(String(300))
    recipient_contact: Mapped[str | None] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(String(20), default="sample")
    reason_note: Mapped[str | None] = mapped_column(String(300))
    # Memo only. It never reaches the profit and loss unless finance books a
    # separate expense, and it never changes the stock cost of the units.
    notional_value: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=DRAFT,
                                        server_default=text("'draft'"))
    # True only for a note written by the audited historical-correction tool.
    correction: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False,
                                             server_default=text("false"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(300))
    reversed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_reason: Mapped[str | None] = mapped_column(String(300))

    lines = relationship("FocNoteLine", back_populates="note", lazy="selectin",
                         order_by="FocNoteLine.id")


class FocNoteLine(Base):
    __tablename__ = "foc_note_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_foc_line_qty_positive"),
        CheckConstraint("unit_notional_value IS NULL OR unit_notional_value >= 0",
                        name="ck_foc_line_notional_nonneg"),
        UniqueConstraint("movement_id", name="uq_foc_line_movement"),
        Index("ix_foc_lines_note", "note_id"),
        Index("ix_foc_lines_batch", "batch_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("foc_notes.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_notional_value: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    line_notional_value: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    movement_id: Mapped[int | None] = mapped_column(ForeignKey("stock_movements.id"))

    note = relationship("FocNote", back_populates="lines")
