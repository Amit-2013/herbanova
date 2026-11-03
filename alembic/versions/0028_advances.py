"""Receipt and payment advances, and the two heads they post to.

Additive only: one new table, two new chart heads and a wider role check.

- `payment_allocations` records how much of one receipt or payment settled one
  invoice or purchase order. A receipt may settle several invoices, and an
  advance may settle an invoice issued later, so the link cannot live on the
  payment row. The payment amount minus its allocations is the advance still
  available to the party, and `applied_on` dates the settlement so a statement
  can tell an advance from a settlement at any point in time.
- Two chart heads are added because an advance is not a receivable or a
  payable: money received before an invoice is a liability to the distributor,
  and money paid before goods arrive is an asset with the supplier. Posting
  either to Receivables or Payables would distort both balances.
- The role check is widened (never narrowed) to accept the two new roles.

No existing row, column or meaning changes. The downgrade drops the table, the
two heads and the widened check.

Revision ID: 0028_advances
Revises: 0027_ledger_and_bank_rec
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_advances"
down_revision: Union[str, None] = "0027_ledger_and_bank_rec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(14, 2)

OLD_ROLES = ("cash", "bank", "receivables", "payables", "output_gst", "capital",
             "sales", "purchases", "round_off")
NEW_ROLES = OLD_ROLES + ("supplier_advance", "distributor_advance")
OLD_CHECK = "role IS NULL OR role IN (" + ",".join(f"'{r}'" for r in OLD_ROLES) + ")"
NEW_CHECK = "role IS NULL OR role IN (" + ",".join(f"'{r}'" for r in NEW_ROLES) + ")"

HEADS = (
    ("1110", "Advances to suppliers", "asset", "supplier_advance"),
    ("2110", "Advances from distributors", "liability", "distributor_advance"),
)


def upgrade() -> None:
    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("purchase_order_id", sa.Integer(),
                  sa.ForeignKey("purchase_orders.id"), nullable=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("applied_on", sa.Date(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "(invoice_id IS NOT NULL AND purchase_order_id IS NULL) "
            "OR (invoice_id IS NULL AND purchase_order_id IS NOT NULL)",
            name="ck_payment_allocation_target"),
        sa.CheckConstraint("amount > 0", name="ck_payment_allocation_amount"),
    )
    op.create_index("ix_payment_allocations_payment_id", "payment_allocations",
                    ["payment_id"])
    op.create_index("ix_payment_allocations_invoice_id", "payment_allocations",
                    ["invoice_id"])
    op.create_index("ix_payment_allocations_purchase_order_id", "payment_allocations",
                    ["purchase_order_id"])
    op.create_index("ix_payment_allocations_applied_on", "payment_allocations",
                    ["applied_on"])
    op.create_index("uq_payment_allocation_invoice", "payment_allocations",
                    ["payment_id", "invoice_id"], unique=True,
                    postgresql_where=sa.text("invoice_id IS NOT NULL"))
    op.create_index("uq_payment_allocation_order", "payment_allocations",
                    ["payment_id", "purchase_order_id"], unique=True,
                    postgresql_where=sa.text("purchase_order_id IS NOT NULL"))

    op.drop_constraint("ck_ledger_account_role", "ledger_accounts", type_="check")
    op.create_check_constraint("ck_ledger_account_role", "ledger_accounts", NEW_CHECK)

    table = sa.table("ledger_accounts",
                     sa.column("code", sa.String), sa.column("name", sa.String),
                     sa.column("type", sa.String), sa.column("role", sa.String),
                     sa.column("active", sa.Boolean))
    op.bulk_insert(table, [{"code": c, "name": n, "type": t, "role": r, "active": True}
                           for c, n, t, r in HEADS])


def downgrade() -> None:
    # Only unused heads can be removed: a posted voucher or opening balance that
    # names one would otherwise lose its account. The downgrade refuses with a
    # clear message rather than deleting a used account.
    bind = op.get_bind()
    used = bind.execute(sa.text("""
        SELECT count(*) FROM ledger_accounts a
        WHERE a.role IN ('supplier_advance', 'distributor_advance')
          AND (EXISTS (SELECT 1 FROM opening_balances o
                       WHERE o.ledger_account_id = a.id)
               OR EXISTS (SELECT 1 FROM voucher_lines v
                          WHERE v.ledger_account_id = a.id))
    """)).scalar()
    if used:
        raise RuntimeError(
            "Cannot downgrade 0028_advances: an advances head is used by an "
            "opening balance or a voucher line. Reverse those entries first.")
    bind.execute(sa.text("DELETE FROM ledger_accounts "
                         "WHERE role IN ('supplier_advance', 'distributor_advance')"))
    op.drop_constraint("ck_ledger_account_role", "ledger_accounts", type_="check")
    op.create_check_constraint("ck_ledger_account_role", "ledger_accounts", OLD_CHECK)
    op.drop_table("payment_allocations")
