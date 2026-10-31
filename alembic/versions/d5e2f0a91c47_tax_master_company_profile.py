"""company tax profile, GST rate master, discount slabs and the tax fields

Module Phase 3 (FR-13, FR-03, FR-07):

- `company_profile` is the seller's own tax identity: one row, GSTIN validated
  in full, the state taken from the GSTIN, and the bank details the invoice
  prints.
- `tax_rates` is the rate master, keyed by HSN and effective-dated. No rate is
  hard-coded anywhere in the application: a rate change is a new row, and the
  row in force on the document date is the one used. `cgst + sgst = igst` and
  the date window are enforced by the database, not only by the API.
- `discount_slabs` is the discount policy as data: a quantity or value band,
  for all products, one product or one distributor group, with an approval
  threshold.
- `products` gains the HSN and UQC that the rate master is keyed by, and
  `distributors` gains their tax identity, addresses, contact details, group
  and payment terms (FR-07, G-07).

The columns are added nullable so existing rows stay valid: no HSN, rate or
GSTIN is invented for a product, a distributor or the company (FR-13).

Revision ID: d5e2f0a91c47
Revises: b7d1c29a4f10
Create Date: 2026-10-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e2f0a91c47"
down_revision: Union[str, None] = "b7d1c29a4f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------- company tax profile
    op.create_table(
        "company_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column("trade_name", sa.String(length=200), nullable=True),
        sa.Column("gstin", sa.String(length=15), nullable=True),
        sa.Column("pan", sa.String(length=10), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("registration_type", sa.String(length=20), server_default="regular", nullable=False),
        sa.Column("address_line1", sa.String(length=200), nullable=True),
        sa.Column("address_line2", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("pincode", sa.String(length=6), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=150), nullable=True),
        sa.Column("invoice_prefix", sa.String(length=10), nullable=True),
        sa.Column("bank_name", sa.String(length=120), nullable=True),
        sa.Column("bank_account_name", sa.String(length=150), nullable=True),
        sa.Column("bank_account_number", sa.String(length=40), nullable=True),
        sa.Column("bank_ifsc", sa.String(length=20), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("state_code IS NULL OR length(state_code) = 2",
                           name="ck_company_state_code"),
        sa.CheckConstraint("registration_type IN ('regular','composition','unregistered')",
                           name="ck_company_registration_type"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gstin", name="uq_company_profile_gstin"),
    )

    # ------------------------------------------------------------- GST rate master
    op.create_table(
        "tax_rates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hsn", sa.String(length=8), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("cgst_rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("sgst_rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("igst_rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("cess_rate", sa.Numeric(precision=5, scale=2), server_default="0", nullable=False),
        sa.Column("is_reverse_charge", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(hsn) BETWEEN 4 AND 8", name="ck_tax_rate_hsn_digits"),
        sa.CheckConstraint("cgst_rate >= 0 AND sgst_rate >= 0 AND igst_rate >= 0 AND cess_rate >= 0",
                           name="ck_tax_rate_nonneg"),
        sa.CheckConstraint("cgst_rate + sgst_rate = igst_rate", name="ck_tax_rate_split"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                           name="ck_tax_rate_window"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_tax_rates_created_by"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tax_rates_hsn_from", "tax_rates", ["hsn", "effective_from"], unique=False)

    # ----------------------------------------------------------- discount slabs
    op.create_table(
        "discount_slabs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=20), server_default="all", nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("group_name", sa.String(length=60), nullable=True),
        sa.Column("min_qty", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("max_qty", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("min_value", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("max_value", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("discount_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("approval_above", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("scope IN ('all','product','group')", name="ck_discount_slab_scope"),
        sa.CheckConstraint("discount_percent >= 0 AND discount_percent <= 100",
                           name="ck_discount_slab_percent"),
        sa.CheckConstraint("approval_above IS NULL OR (approval_above >= 0 AND approval_above <= 100)",
                           name="ck_discount_slab_approval"),
        sa.CheckConstraint("min_qty IS NOT NULL OR min_value IS NOT NULL", name="ck_discount_slab_bound"),
        sa.CheckConstraint("min_qty IS NULL OR min_qty > 0", name="ck_discount_slab_min_qty"),
        sa.CheckConstraint("min_value IS NULL OR min_value > 0", name="ck_discount_slab_min_value"),
        sa.CheckConstraint("max_qty IS NULL OR min_qty IS NULL OR max_qty >= min_qty",
                           name="ck_discount_slab_qty_band"),
        sa.CheckConstraint("max_value IS NULL OR min_value IS NULL OR max_value >= min_value",
                           name="ck_discount_slab_value_band"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                           name="ck_discount_slab_window"),
        sa.CheckConstraint("(scope <> 'product' OR product_id IS NOT NULL)",
                           name="ck_discount_slab_product"),
        sa.CheckConstraint("(scope <> 'group' OR group_name IS NOT NULL)",
                           name="ck_discount_slab_group"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_discount_slabs_created_by"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_discount_slabs_product"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------- product and distributor tax fields
    op.add_column("products", sa.Column("hsn", sa.String(length=8), nullable=True))
    op.add_column("products", sa.Column("uqc", sa.String(length=3), nullable=True))
    op.create_check_constraint("ck_product_hsn", "products",
                                "hsn IS NULL OR length(hsn) BETWEEN 4 AND 8")

    op.add_column("distributors", sa.Column("gstin", sa.String(length=15), nullable=True))
    op.add_column("distributors", sa.Column("pan", sa.String(length=10), nullable=True))
    op.add_column("distributors", sa.Column("state_code", sa.String(length=2), nullable=True))
    op.add_column("distributors", sa.Column("registration_type", sa.String(length=20),
                                             server_default="unregistered", nullable=False))
    op.add_column("distributors", sa.Column("billing_address", sa.String(length=300), nullable=True))
    op.add_column("distributors", sa.Column("shipping_address", sa.String(length=300), nullable=True))
    op.add_column("distributors", sa.Column("contact_person", sa.String(length=120), nullable=True))
    op.add_column("distributors", sa.Column("phone", sa.String(length=40), nullable=True))
    op.add_column("distributors", sa.Column("email", sa.String(length=150), nullable=True))
    op.add_column("distributors", sa.Column("group_name", sa.String(length=60), nullable=True))
    op.add_column("distributors", sa.Column("payment_terms_days", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_distributor_registration_type", "distributors",
                                "registration_type IN ('regular','composition','unregistered')")
    op.create_check_constraint("ck_distributor_state_code", "distributors",
                                "state_code IS NULL OR length(state_code) = 2")
    op.create_check_constraint("ck_distributor_payment_terms", "distributors",
                                "payment_terms_days IS NULL OR payment_terms_days >= 0")
    op.create_unique_constraint("uq_distributors_gstin", "distributors", ["gstin"])

    # ------------------------------------------------------- seeded role rights
    # The roles were seeded by the Phase 1 migration and extended by Phase 2;
    # give them the tax rights this module adds, without touching any other
    # permission.
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb || '["tax:read","tax:write"]'::jsonb)::json
         WHERE name = 'admin'
           AND NOT permissions::jsonb @> '["tax:write"]'::jsonb
        """
    )
    for role_name in ("sales", "inventory"):
        op.execute(
            f"""
            UPDATE roles
               SET permissions = (permissions::jsonb || '["tax:read"]'::jsonb)::json
             WHERE name = '{role_name}'
               AND NOT permissions::jsonb @> '["tax:read"]'::jsonb
            """
        )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb - 'tax:read' - 'tax:write')::json
         WHERE name = 'admin'
        """
    )
    for role_name in ("sales", "inventory"):
        op.execute(
            f"""
            UPDATE roles
               SET permissions = (permissions::jsonb - 'tax:read')::json
             WHERE name = '{role_name}'
            """
        )

    op.drop_constraint("uq_distributors_gstin", "distributors", type_="unique")
    op.drop_constraint("ck_distributor_payment_terms", "distributors", type_="check")
    op.drop_constraint("ck_distributor_state_code", "distributors", type_="check")
    op.drop_constraint("ck_distributor_registration_type", "distributors", type_="check")
    for column in ("payment_terms_days", "group_name", "email", "phone", "contact_person",
                   "shipping_address", "billing_address", "registration_type", "state_code",
                   "pan", "gstin"):
        op.drop_column("distributors", column)

    op.drop_constraint("ck_product_hsn", "products", type_="check")
    op.drop_column("products", "uqc")
    op.drop_column("products", "hsn")

    op.drop_table("discount_slabs")
    op.drop_index("ix_tax_rates_hsn_from", table_name="tax_rates")
    op.drop_table("tax_rates")
    op.drop_table("company_profile")
