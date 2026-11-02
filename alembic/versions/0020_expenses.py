"""Expense heads, entries, receipts metadata and the approval setting.

Additive only: three new tables and the two permission keys on the seeded
Administrator role. No existing table changes. The payroll head is seeded
because it must exist before the P&L can separate HR payroll from manual
expenses; it is marked system and refuses manual entries.

Revision ID: 0020_expenses
Revises: 0019_db_reset_key
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_expenses"
down_revision: Union[str, None] = "0019_db_reset_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SYSTEM_PAYROLL_HEAD = "Payroll (from HR)"
NEW_PERMISSIONS = ("expense:read", "expense:write")


def _grant_admin(add: bool) -> None:
    bind = op.get_bind()
    roles = sa.table("roles", sa.column("name", sa.String), sa.column("permissions", sa.JSON))
    row = bind.execute(sa.select(roles.c.permissions).where(roles.c.name == "admin")).first()
    if row is None:
        return
    current = list(row[0] or [])
    if add:
        for key in NEW_PERMISSIONS:
            if key not in current:
                current.append(key)
    else:
        current = [key for key in current if key not in NEW_PERMISSIONS]
    bind.execute(roles.update().where(roles.c.name == "admin").values(permissions=current))


def upgrade() -> None:
    op.create_table(
        "expense_heads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_expense_heads_name"),
    )

    op.create_table(
        "expense_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("approval_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("approval_threshold", sa.Numeric(14, 2), nullable=False,
                  server_default="0"),
        sa.Column("tracked_from", sa.Date(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_expense_settings_single"),
        sa.CheckConstraint("approval_threshold >= 0", name="ck_expense_threshold_nonneg"),
    )

    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("head_id", sa.Integer(), sa.ForeignKey("expense_heads.id"), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("gst_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("gst_creditable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("mode", sa.String(10), nullable=False, server_default="bank"),
        sa.Column("reference", sa.String(60), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("attachment_path", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="approved"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversal_reason", sa.String(300), nullable=True),
        sa.Column("approval_request_id", sa.Integer(),
                  sa.ForeignKey("approval_requests.id"), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_expense_amount_positive"),
        sa.CheckConstraint("gst_amount >= 0", name="ck_expense_gst_nonneg"),
        sa.CheckConstraint("mode IN ('cash','bank','upi','cheque','neft','other')",
                           name="ck_expense_mode"),
        sa.CheckConstraint("status IN ('pending_approval','approved','rejected','reversed')",
                           name="ck_expense_status"),
        sa.CheckConstraint(
            "status <> 'reversed' OR (reversed_at IS NOT NULL "
            "AND reversal_reason IS NOT NULL)", name="ck_expense_reversal_fields"),
    )
    op.create_index("ix_expenses_entry_date", "expenses", ["entry_date"])
    op.create_index("ix_expenses_status_date", "expenses", ["status", "entry_date"])
    op.create_index("ix_expenses_head", "expenses", ["head_id"])

    op.execute(sa.text(
        "INSERT INTO expense_heads (name, is_active, is_system) "
        "VALUES (:name, true, true)").bindparams(name=SYSTEM_PAYROLL_HEAD))
    # The module starts recording today. A window before this date is reported as
    # a gap, not as zero spending.
    op.execute(sa.text(
        "INSERT INTO expense_settings (id, approval_enabled, approval_threshold, "
        "tracked_from) VALUES (1, false, 0, CURRENT_DATE)"))

    _grant_admin(True)


def downgrade() -> None:
    _grant_admin(False)
    op.drop_table("expenses")
    op.drop_table("expense_settings")
    op.drop_table("expense_heads")
