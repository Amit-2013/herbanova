"""receipts, payments and the Accounts module permissions (Module Phase 6)

Revision ID: aa11bb22cc33
Revises: c7d8e9f0a1b2
Create Date: 2026-10-29 16:40:00.000000

The `payments` table records money in and money out. Nothing else is stored for
accounts: the outstanding list, party statements, GST registers and trial balance
are derived from the tax documents, so there is no second ledger to reconcile.

Two permission keys are added and granted to the seeded roles: `accounts:read` to
administrator and sales, `accounts:write` to administrator only. The JSON column
is rewritten in Python so the order of existing keys is preserved.
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aa11bb22cc33'
down_revision: Union[str, None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GRANTS = {
    "admin": ["accounts:read", "accounts:write"],
    "sales": ["accounts:read"],
}


def _rewrite_roles(add: bool) -> None:
    bind = op.get_bind()
    roles = sa.table("roles", sa.column("name", sa.String), sa.column("permissions", sa.JSON))
    for name, keys in GRANTS.items():
        row = bind.execute(sa.select(roles.c.permissions).where(roles.c.name == name)).first()
        if row is None:
            continue
        current = list(row[0] or [])
        if add:
            for key in keys:
                if key not in current:
                    current.append(key)
        else:
            current = [k for k in current if k not in keys]
        bind.execute(roles.update().where(roles.c.name == name).values(permissions=current))


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("distributor_id", sa.Integer(), sa.ForeignKey("distributors.id"), nullable=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"),
                  nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("reference", sa.String(60), nullable=True),
        sa.Column("notes", sa.String(300), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.CheckConstraint("kind IN ('receipt','payment')", name="ck_payment_kind"),
        sa.CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        sa.CheckConstraint(
            "(kind = 'receipt' AND distributor_id IS NOT NULL AND supplier_id IS NULL) "
            "OR (kind = 'payment' AND supplier_id IS NOT NULL AND distributor_id IS NULL)",
            name="ck_payment_party"),
        sa.CheckConstraint("mode IN ('cash','bank','upi','cheque','neft','other')",
                           name="ck_payment_mode"),
    )
    op.create_index("ix_payments_kind", "payments", ["kind"])
    op.create_index("ix_payments_paid_on", "payments", ["paid_on"])
    _rewrite_roles(add=True)


def downgrade() -> None:
    _rewrite_roles(add=False)
    op.drop_index("ix_payments_paid_on", table_name="payments")
    op.drop_index("ix_payments_kind", table_name="payments")
    op.drop_table("payments")
