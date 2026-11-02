"""Free-of-cost stock: an explicit cost source and an approved distribution note.

Additive only. Existing movements keep their cost and source; the check
constraint merely learns the new ``foc`` value. ``foc_notes`` and
``foc_note_lines`` record a giveaway with one named recipient per note, no
invoice and no revenue. Roles receive the new keys, so no existing screen,
route or report changes meaning.

Revision ID: 0023_foc_samples
Revises: 0022_accounting_period_lock
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_foc_samples"
down_revision: Union[str, None] = "0022_accounting_period_lock"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_SOURCES = ("po_receipt", "weighted_average", "partial", "return", "uncosted")
NEW_SOURCES = OLD_SOURCES + ("foc",)
GRANTS = {
    "admin": ("foc:read", "foc:write", "foc:approve"),
    "inventory": ("foc:read", "foc:write"),
    "viewer": ("foc:read",),
}


def _check(sources) -> str:
    return ("cost_source IS NULL OR cost_source IN ("
            + ",".join(f"'{s}'" for s in sources) + ")")


def _grant(add: bool) -> None:
    bind = op.get_bind()
    roles = sa.table("roles", sa.column("name", sa.String), sa.column("permissions", sa.JSON))
    for name, keys in GRANTS.items():
        row = bind.execute(sa.select(roles.c.permissions).where(roles.c.name == name)).first()
        if row is None:
            continue
        current = list(row[0] or [])
        if add:
            current.extend(k for k in keys if k not in current)
        else:
            current = [k for k in current if k not in keys]
        bind.execute(roles.update().where(roles.c.name == name).values(permissions=current))


def upgrade() -> None:
    op.drop_constraint("ck_stock_movement_cost_source", "stock_movements", type_="check")
    op.create_check_constraint("ck_stock_movement_cost_source", "stock_movements",
                               _check(NEW_SOURCES))

    op.create_table(
        "foc_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("note_number", sa.String(16), nullable=False, unique=True),
        sa.Column("financial_year", sa.String(9), nullable=False),
        sa.Column("note_date", sa.Date(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("distributor_id", sa.Integer(), sa.ForeignKey("distributors.id"),
                  nullable=True),
        sa.Column("recipient_name", sa.String(150), nullable=False),
        sa.Column("recipient_address", sa.String(300), nullable=True),
        sa.Column("recipient_contact", sa.String(120), nullable=True),
        sa.Column("reason", sa.String(20), nullable=False, server_default="sample"),
        sa.Column("reason_note", sa.String(300), nullable=True),
        sa.Column("notional_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("correction", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(300), nullable=True),
        sa.Column("reversed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversal_reason", sa.String(300), nullable=True),
        sa.CheckConstraint("status IN ('draft','approved','rejected','reversed')",
                           name="ck_foc_note_status"),
        sa.CheckConstraint(
            "reason IN ('sample','promotional','replacement','donation','other')",
            name="ck_foc_note_reason"),
        sa.CheckConstraint("notional_value IS NULL OR notional_value >= 0",
                           name="ck_foc_note_notional_nonneg"),
        sa.CheckConstraint(
            "status <> 'approved' OR (approved_at IS NOT NULL AND approved_by IS NOT NULL)",
            name="ck_foc_note_approved_fields"),
        sa.CheckConstraint(
            "status <> 'reversed' OR (reversed_at IS NOT NULL "
            "AND reversed_by IS NOT NULL AND reversal_reason IS NOT NULL)",
            name="ck_foc_note_reversed_fields"),
    )
    op.create_index("ix_foc_notes_date", "foc_notes", ["note_date"])
    op.create_index("ix_foc_notes_status_date", "foc_notes", ["status", "note_date"])

    op.create_table(
        "foc_note_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("note_id", sa.Integer(), sa.ForeignKey("foc_notes.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("batches.id"), nullable=False),
        sa.Column("qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_notional_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("line_notional_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("movement_id", sa.Integer(), sa.ForeignKey("stock_movements.id"),
                  nullable=True),
        sa.CheckConstraint("qty > 0", name="ck_foc_line_qty_positive"),
        sa.CheckConstraint("unit_notional_value IS NULL OR unit_notional_value >= 0",
                           name="ck_foc_line_notional_nonneg"),
        sa.UniqueConstraint("movement_id", name="uq_foc_line_movement"),
    )
    op.create_index("ix_foc_lines_note", "foc_note_lines", ["note_id"])
    op.create_index("ix_foc_lines_batch", "foc_note_lines", ["batch_id"])

    _grant(True)


def downgrade() -> None:
    # A rollback must not erase an approved giveaway or a corrected cost. If any
    # FOC row exists, restore the pre-0023 dump instead of narrowing the schema
    # under live data.
    bind = op.get_bind()
    notes = bind.execute(sa.text("SELECT count(*) FROM foc_notes")).scalar() or 0
    movements = bind.execute(sa.text(
        "SELECT count(*) FROM stock_movements WHERE cost_source = 'foc'")).scalar() or 0
    if notes or movements:
        raise RuntimeError(
            "REFUSED: FOC notes or 'foc' movements exist; restore the pre-0023 dump "
            "instead of a schema-only downgrade")

    op.drop_index("ix_foc_lines_batch", table_name="foc_note_lines")
    op.drop_index("ix_foc_lines_note", table_name="foc_note_lines")
    op.drop_table("foc_note_lines")
    op.drop_index("ix_foc_notes_status_date", table_name="foc_notes")
    op.drop_index("ix_foc_notes_date", table_name="foc_notes")
    op.drop_table("foc_notes")

    op.drop_constraint("ck_stock_movement_cost_source", "stock_movements", type_="check")
    op.create_check_constraint("ck_stock_movement_cost_source", "stock_movements",
                               _check(OLD_SOURCES))

    _grant(False)
