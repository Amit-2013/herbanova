"""Invoice payment terms and due dates; closed financial years.

Additive only. An invoice now carries the payment terms it was issued under and
the resulting due date, both nullable so an invoice issued before a term was
captured stays honest and is reported as having no due date. A new
`financial_year_closes` table records which financial years are closed, by whom
and why, with the reopen trail; no existing table or column changes meaning.

Revision ID: 0025_due_dates_and_year_close
Revises: 0024_catalog_order_dates
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_due_dates_and_year_close"
down_revision: Union[str, None] = "0024_catalog_order_dates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("invoices") as batch:
        batch.add_column(sa.Column("payment_terms_days", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("due_date", sa.Date(), nullable=True))
        batch.create_check_constraint(
            "ck_invoice_payment_terms",
            "payment_terms_days IS NULL OR payment_terms_days >= 0")
        batch.create_index("ix_invoices_due_date", ["due_date"])
    op.create_table(
        "financial_year_closes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("financial_year", sa.String(9), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("reopened_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopen_reason", sa.String(300), nullable=True),
        sa.CheckConstraint("length(financial_year) = 7", name="ck_fy_close_label"),
    )


def downgrade() -> None:
    op.drop_table("financial_year_closes")
    with op.batch_alter_table("invoices") as batch:
        batch.drop_index("ix_invoices_due_date")
        batch.drop_constraint("ck_invoice_payment_terms", type_="check")
        batch.drop_column("due_date")
        batch.drop_column("payment_terms_days")
