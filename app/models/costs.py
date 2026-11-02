"""Audited corrections to a purchase rate after stock has already moved.

A correction never changes a quantity. It replaces the captured unit cost on the
receipt movements of one purchase order line, replays that product's movements
through the weighted-average rule, and stores what changed so the correction can
be reviewed later.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base
from .core import MONEY


class CostCorrection(Base):
    __tablename__ = "cost_corrections"
    __table_args__ = (
        CheckConstraint("new_unit_cost >= 0", name="ck_cost_correction_nonneg"),
        CheckConstraint("length(btrim(reason)) >= 3", name="ck_cost_correction_reason"),
        Index("ix_cost_corrections_product", "product_id"),
        Index("ix_cost_corrections_created", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    po_line_id: Mapped[int] = mapped_column(ForeignKey("purchase_order_lines.id"))
    old_unit_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    new_unit_cost: Mapped[Decimal] = mapped_column(MONEY)
    reason: Mapped[str] = mapped_column(String(300))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
