"""Voucher journal, opening balances and bank reconciliation.

Additive only: six new tables and no change to an existing column or meaning.

- `ledger_accounts` is the chart of accounts. Nine heads are seeded because the
  documents already produce those buckets (Cash, Bank, Receivables, Payables,
  output GST, Sales, Purchases, Round off) and one equity head (Capital) so an
  opening position can be recorded. No amount is seeded.
- `opening_balances` carries the position into a financial year, per head.
- `vouchers` / `voucher_lines` are the stored double-entry postings, with a
  draft, posted and reversed state.
- `bank_statements` / `bank_statement_lines` hold the bank's figures and the
  lines matched to receipts, payments or voucher lines.

Revision ID: 0027_ledger_and_bank_rec
Revises: 0026_gst_and_statutory
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_ledger_and_bank_rec"
down_revision: Union[str, None] = "0026_gst_and_statutory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(14, 2)

SEED = (
    ("1000", "Cash", "asset", "cash"),
    ("1010", "Bank", "asset", "bank"),
    ("1100", "Receivables", "asset", "receivables"),
    ("2000", "Payables", "liability", "payables"),
    ("2100", "Output GST", "liability", "output_gst"),
    ("3000", "Capital", "equity", "capital"),
    ("4000", "Sales", "income", "sales"),
    ("5000", "Purchases", "expense", "purchases"),
    ("5900", "Round off", "expense", "round_off"),
)


def upgrade() -> None:
    op.create_table(
        "ledger_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("type", sa.String(12), nullable=False),
        sa.Column("role", sa.String(20), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("type IN ('asset','liability','equity','income','expense')",
                           name="ck_ledger_account_type"),
        sa.CheckConstraint("role IS NULL OR role IN ('cash','bank','receivables',"
                           "'payables','output_gst','capital','sales','purchases',"
                           "'round_off')", name="ck_ledger_account_role"),
    )
    op.create_index("uq_ledger_account_code", "ledger_accounts", ["code"], unique=True)
    op.create_index("uq_ledger_account_name", "ledger_accounts", ["name"], unique=True)
    op.create_index("uq_ledger_account_role", "ledger_accounts", ["role"], unique=True,
                    postgresql_where=sa.text("role IS NOT NULL"))

    table = sa.table("ledger_accounts",
                     sa.column("code", sa.String), sa.column("name", sa.String),
                     sa.column("type", sa.String), sa.column("role", sa.String),
                     sa.column("active", sa.Boolean))
    op.bulk_insert(table, [{"code": c, "name": n, "type": t, "role": r, "active": True}
                           for c, n, t, r in SEED])

    op.create_table(
        "opening_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ledger_account_id", sa.Integer(),
                  sa.ForeignKey("ledger_accounts.id"), nullable=False),
        sa.Column("financial_year", sa.String(9), nullable=False),
        sa.Column("debit", MONEY, nullable=False, server_default="0"),
        sa.Column("credit", MONEY, nullable=False, server_default="0"),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("ledger_account_id", "financial_year",
                            name="uq_opening_balance_year"),
        sa.CheckConstraint("debit >= 0 AND credit >= 0", name="ck_opening_amounts"),
        sa.CheckConstraint("(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
                           name="ck_opening_one_side"),
        sa.CheckConstraint("length(financial_year) = 7", name="ck_opening_fy_label"),
    )
    op.create_index("ix_opening_balances_account", "opening_balances",
                    ["ledger_account_id"])

    op.create_table(
        "vouchers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("voucher_date", sa.Date(), nullable=False),
        sa.Column("voucher_type", sa.String(10), nullable=False),
        sa.Column("narration", sa.String(300), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("reversal_of_id", sa.Integer(), sa.ForeignKey("vouchers.id"),
                  nullable=True),
        sa.Column("reversal_reason", sa.String(300), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("posted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("voucher_type IN ('journal','receipt','payment','contra')",
                           name="ck_voucher_type"),
        sa.CheckConstraint("status IN ('draft','posted','reversed')",
                           name="ck_voucher_status"),
        sa.CheckConstraint("status <> 'reversed' OR reversal_reason IS NOT NULL",
                           name="ck_voucher_reversal_reason"),
        sa.CheckConstraint("status <> 'posted' OR posted_at IS NOT NULL",
                           name="ck_voucher_posted_at"),
    )
    op.create_index("ix_vouchers_date", "vouchers", ["voucher_date"])
    op.create_index("ix_vouchers_status", "vouchers", ["status"])

    op.create_table(
        "voucher_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("voucher_id", sa.Integer(), sa.ForeignKey("vouchers.id"),
                  nullable=False),
        sa.Column("ledger_account_id", sa.Integer(),
                  sa.ForeignKey("ledger_accounts.id"), nullable=False),
        sa.Column("narration", sa.String(300), nullable=True),
        sa.Column("debit", MONEY, nullable=False, server_default="0"),
        sa.Column("credit", MONEY, nullable=False, server_default="0"),
        sa.CheckConstraint("debit >= 0 AND credit >= 0", name="ck_voucher_line_amounts"),
        sa.CheckConstraint("(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
                           name="ck_voucher_line_one_side"),
    )
    op.create_index("ix_voucher_lines_voucher", "voucher_lines", ["voucher_id"])
    op.create_index("ix_voucher_lines_account", "voucher_lines", ["ledger_account_id"])

    op.create_table(
        "bank_statements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ledger_account_id", sa.Integer(),
                  sa.ForeignKey("ledger_accounts.id"), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("opening_balance", MONEY, nullable=False),
        sa.Column("closing_balance", MONEY, nullable=False),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("period_from <= period_to", name="ck_bank_statement_period"),
        sa.UniqueConstraint("ledger_account_id", "period_from", "period_to",
                            name="uq_bank_statement_period"),
    )
    op.create_index("ix_bank_statements_account", "bank_statements",
                    ["ledger_account_id"])

    op.create_table(
        "bank_statement_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("statement_id", sa.Integer(), sa.ForeignKey("bank_statements.id"),
                  nullable=False),
        sa.Column("line_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("reference", sa.String(60), nullable=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("matched_payment_id", sa.Integer(), sa.ForeignKey("payments.id"),
                  nullable=True),
        sa.Column("matched_voucher_line_id", sa.Integer(),
                  sa.ForeignKey("voucher_lines.id"), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.CheckConstraint("amount <> 0", name="ck_bank_line_amount"),
        sa.CheckConstraint("NOT (matched_payment_id IS NOT NULL AND "
                           "matched_voucher_line_id IS NOT NULL)",
                           name="ck_bank_line_one_match"),
    )
    op.create_index("ix_bank_statement_lines_statement", "bank_statement_lines",
                    ["statement_id"])
    op.create_index("uq_bank_line_payment", "bank_statement_lines",
                    ["matched_payment_id"], unique=True,
                    postgresql_where=sa.text("matched_payment_id IS NOT NULL"))
    op.create_index("uq_bank_line_voucher_line", "bank_statement_lines",
                    ["matched_voucher_line_id"], unique=True,
                    postgresql_where=sa.text("matched_voucher_line_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_bank_line_voucher_line", table_name="bank_statement_lines")
    op.drop_index("uq_bank_line_payment", table_name="bank_statement_lines")
    op.drop_index("ix_bank_statement_lines_statement", table_name="bank_statement_lines")
    op.drop_table("bank_statement_lines")
    op.drop_index("ix_bank_statements_account", table_name="bank_statements")
    op.drop_table("bank_statements")
    op.drop_index("ix_voucher_lines_account", table_name="voucher_lines")
    op.drop_index("ix_voucher_lines_voucher", table_name="voucher_lines")
    op.drop_table("voucher_lines")
    op.drop_index("ix_vouchers_status", table_name="vouchers")
    op.drop_index("ix_vouchers_date", table_name="vouchers")
    op.drop_table("vouchers")
    op.drop_index("ix_opening_balances_account", table_name="opening_balances")
    op.drop_table("opening_balances")
    op.drop_index("uq_ledger_account_role", table_name="ledger_accounts")
    op.drop_index("uq_ledger_account_name", table_name="ledger_accounts")
    op.drop_index("uq_ledger_account_code", table_name="ledger_accounts")
    op.drop_table("ledger_accounts")
