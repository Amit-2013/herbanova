"""Add a configured capacity to warehouses.

Capacity is optional: a NULL value means the warehouse has not been measured,
not that it can hold nothing. Both columns are additive and no row is rewritten.

Revision ID: 0009_warehouse_capacity
Revises: e4f5a6b7c8d9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_warehouse_capacity"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("warehouses", sa.Column("capacity_units", sa.Integer(), nullable=True))
    op.add_column("warehouses", sa.Column("capacity_note", sa.String(length=40), nullable=True))
    op.create_check_constraint(
        "ck_warehouse_capacity_nonnegative", "warehouses",
        "capacity_units IS NULL OR capacity_units >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_warehouse_capacity_nonnegative", "warehouses", type_="check")
    op.drop_column("warehouses", "capacity_note")
    op.drop_column("warehouses", "capacity_units")
