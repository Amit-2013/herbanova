"""Product grouping and reorder levels; order promise and approval stamps.

Additive only. Products gain an optional category, brand and reorder level;
sales orders gain the approval timestamp and the promised delivery date. No
existing column changes meaning, and every new column is nullable, so rows
created before this revision stay valid and reports treat the blanks as
"not captured" rather than zero.

Revision ID: 0024_catalog_order_dates
Revises: 0023_foc_samples
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_catalog_order_dates"
down_revision: Union[str, None] = "0023_foc_samples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("category", sa.String(60), nullable=True))
        batch.add_column(sa.Column("brand", sa.String(60), nullable=True))
        batch.add_column(sa.Column("reorder_level", sa.Numeric(14, 3), nullable=True))
        batch.create_check_constraint(
            "ck_products_reorder_nonneg",
            "reorder_level IS NULL OR reorder_level >= 0")
        batch.create_index("ix_products_category", ["category"])
        batch.create_index("ix_products_brand", ["brand"])
    with op.batch_alter_table("sales_orders") as batch:
        batch.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("expected_delivery_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sales_orders") as batch:
        batch.drop_column("expected_delivery_date")
        batch.drop_column("approved_at")
    with op.batch_alter_table("products") as batch:
        batch.drop_index("ix_products_brand")
        batch.drop_index("ix_products_category")
        batch.drop_constraint("ck_products_reorder_nonneg", type_="check")
        batch.drop_column("reorder_level")
        batch.drop_column("brand")
        batch.drop_column("category")
