"""Capture stock cost on the movement ledger and record audited rate corrections.

Additive only. ``stock_movements`` gains two nullable cost columns and an
``invoice_id`` attribution; existing rows keep NULL, which means "cost not
captured" rather than zero. The backfill tool reports what it would fill and
does not write. ``cost_corrections`` records each applied rate correction with
its before/after result.

Revision ID: 0021_stock_costs
Revises: 0020_expenses
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_stock_costs"
down_revision: Union[str, None] = "0020_expenses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COST_SOURCES = ("po_receipt", "weighted_average", "partial", "return", "uncosted")


def upgrade() -> None:
    op.add_column("stock_movements", sa.Column("unit_cost", sa.Numeric(14, 2), nullable=True))
    op.add_column("stock_movements", sa.Column("cost_source", sa.String(20), nullable=True))
    op.add_column("stock_movements",
                  sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"),
                            nullable=True))
    op.create_check_constraint(
        "ck_stock_movement_cost_source",
        "stock_movements",
        "cost_source IS NULL OR cost_source IN "
        "('po_receipt','weighted_average','partial','return','uncosted')")
    op.create_index("ix_stock_movements_invoice", "stock_movements", ["invoice_id"])

    op.create_table(
        "cost_corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("po_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("po_line_id", sa.Integer(), sa.ForeignKey("purchase_order_lines.id"),
                  nullable=False),
        sa.Column("old_unit_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("new_unit_cost", sa.Numeric(14, 2), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.CheckConstraint("new_unit_cost >= 0", name="ck_cost_correction_nonneg"),
        sa.CheckConstraint("length(btrim(reason)) >= 3", name="ck_cost_correction_reason"),
    )
    op.create_index("ix_cost_corrections_product", "cost_corrections", ["product_id"])
    op.create_index("ix_cost_corrections_created", "cost_corrections", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_cost_corrections_created", table_name="cost_corrections")
    op.drop_index("ix_cost_corrections_product", table_name="cost_corrections")
    op.drop_table("cost_corrections")
    op.drop_index("ix_stock_movements_invoice", table_name="stock_movements")
    op.drop_constraint("ck_stock_movement_cost_source", "stock_movements", type_="check")
    op.drop_column("stock_movements", "invoice_id")
    op.drop_column("stock_movements", "cost_source")
    op.drop_column("stock_movements", "unit_cost")
