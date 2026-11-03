"""Input GST, filed GST returns and statutory challans.

Additive only: three new tables and no change to an existing column or meaning.

- `purchase_invoices` records the tax a supplier actually charged, which is the
  only honest source of input tax; payables are untouched, so capturing a bill
  never moves an outstanding balance.
- `gst_returns` holds the figures reported as filed on the portal, so the
  registers can be compared with them without the application pretending to
  file or to know what was filed.
- `statutory_challans` records tax and payroll dues deposited with the
  government, append-only, so a shortfall is named rather than assumed paid.

Revision ID: 0026_gst_and_statutory
Revises: 0025_due_dates_and_year_close
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_gst_and_statutory"
down_revision: Union[str, None] = "0025_due_dates_and_year_close"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(14, 2)


def upgrade() -> None:
    op.create_table(
        "purchase_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(),
                  sa.ForeignKey("purchase_orders.id"), nullable=True),
        sa.Column("supplier_invoice_number", sa.String(40), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("taxable_value", MONEY, nullable=False, server_default="0"),
        sa.Column("cgst_amount", MONEY, nullable=False, server_default="0"),
        sa.Column("sgst_amount", MONEY, nullable=False, server_default="0"),
        sa.Column("igst_amount", MONEY, nullable=False, server_default="0"),
        sa.Column("cess_amount", MONEY, nullable=False, server_default="0"),
        sa.Column("round_off", MONEY, nullable=False, server_default="0"),
        sa.Column("itc_eligible", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("tds_section", sa.String(10), nullable=True),
        sa.Column("tds_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("tds_amount", MONEY, nullable=False, server_default="0"),
        sa.Column("status", sa.String(10), nullable=False, server_default="posted"),
        sa.Column("reversal_reason", sa.String(300), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "taxable_value >= 0 AND cgst_amount >= 0 AND sgst_amount >= 0 "
            "AND igst_amount >= 0 AND cess_amount >= 0 AND tds_amount >= 0",
            name="ck_purchase_invoice_amounts"),
        sa.CheckConstraint("tds_rate IS NULL OR (tds_rate >= 0 AND tds_rate <= 100)",
                           name="ck_purchase_invoice_tds_rate"),
        sa.CheckConstraint("status IN ('posted','reversed')",
                           name="ck_purchase_invoice_status"),
        sa.CheckConstraint("status = 'posted' OR reversal_reason IS NOT NULL",
                           name="ck_purchase_invoice_reversal_reason"),
    )
    op.create_index("ix_purchase_invoices_supplier_id", "purchase_invoices",
                    ["supplier_id"])
    op.create_index("ix_purchase_invoices_date", "purchase_invoices", ["invoice_date"])
    op.create_index("uq_purchase_invoice_number", "purchase_invoices",
                    ["supplier_id", "supplier_invoice_number"], unique=True,
                    postgresql_where=sa.text("status = 'posted'"))

    op.create_table(
        "gst_returns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("form", sa.String(10), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("filed_on", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(40), nullable=True),
        sa.Column("outward_taxable", MONEY, nullable=False, server_default="0"),
        sa.Column("outward_cgst", MONEY, nullable=False, server_default="0"),
        sa.Column("outward_sgst", MONEY, nullable=False, server_default="0"),
        sa.Column("outward_igst", MONEY, nullable=False, server_default="0"),
        sa.Column("outward_cess", MONEY, nullable=False, server_default="0"),
        sa.Column("itc_cgst", MONEY, nullable=False, server_default="0"),
        sa.Column("itc_sgst", MONEY, nullable=False, server_default="0"),
        sa.Column("itc_igst", MONEY, nullable=False, server_default="0"),
        sa.Column("itc_cess", MONEY, nullable=False, server_default="0"),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("form", "year", "month", name="uq_gst_return_period"),
        sa.CheckConstraint("form IN ('GSTR-1','GSTR-3B')", name="ck_gst_return_form"),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_gst_return_month"),
        sa.CheckConstraint(
            "outward_taxable >= 0 AND outward_cgst >= 0 AND outward_sgst >= 0 "
            "AND outward_igst >= 0 AND outward_cess >= 0 AND itc_cgst >= 0 "
            "AND itc_sgst >= 0 AND itc_igst >= 0 AND itc_cess >= 0",
            name="ck_gst_return_amounts"),
    )

    op.create_table(
        "statutory_challans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("bsr_code", sa.String(10), nullable=True),
        sa.Column("challan_number", sa.String(30), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(10), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('tds','pf','esi','pt')", name="ck_challan_kind"),
        sa.CheckConstraint("amount > 0", name="ck_challan_amount"),
        sa.CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_challan_month"),
    )
    op.create_index("ix_statutory_challans_kind", "statutory_challans", ["kind"])
    op.create_index("ix_statutory_challans_paid_on", "statutory_challans", ["paid_on"])


def downgrade() -> None:
    op.drop_index("ix_statutory_challans_paid_on", table_name="statutory_challans")
    op.drop_index("ix_statutory_challans_kind", table_name="statutory_challans")
    op.drop_table("statutory_challans")
    op.drop_table("gst_returns")
    op.drop_index("uq_purchase_invoice_number", table_name="purchase_invoices")
    op.drop_index("ix_purchase_invoices_date", table_name="purchase_invoices")
    op.drop_index("ix_purchase_invoices_supplier_id", table_name="purchase_invoices")
    op.drop_table("purchase_invoices")
