"""suppliers, goods receipt notes and purchase-order supplier linkage

Module Phase 2 (FR-04, FR-05, decisions D8/D9):

- `suppliers` becomes the party master; `purchase_orders.supplier_id` links an
  order to it. Orders that only had a free-text supplier name are migrated:
  each distinct name becomes a supplier record flagged `needs_completion`, so
  no purchase order loses its supplier (AUD-029) and somebody is prompted to
  fill the tax details in.
- `goods_receipts` / `goods_receipt_lines` let an order be received in parts.
  Each receipt posts its own ledger movements (`ref_type = 'grn'`).
- A supplier's state code is nullable so a migrated record can stay honestly
  incomplete; the API refuses tax edits until it is filled in.
- Approval requests may now have history: the old single unique constraint on
  (record_type, record_id) becomes a partial unique index over pending rows
  only, so a decided request no longer blocks a later one.

Revision ID: b7d1c29a4f10
Revises: fef3eeb03094
Create Date: 2026-10-20 00:54:49.099597
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d1c29a4f10"
down_revision: Union[str, None] = "fef3eeb03094"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The data migration is kept as named statements so tests/test_phase2_migration.py
# can run them against legacy-shaped rows and roll the whole thing back.
LEGACY_SUPPLIERS_INSERT = """
    INSERT INTO suppliers (code, name, kind, registration_type, state_code,
                           payment_terms_days, status, needs_completion)
    SELECT 'SUP-' || lpad((row_number() OVER (ORDER BY lower(name)))::text, 3, '0'),
           name, 'supplier', 'unregistered', NULL, 30, 'active', true
      FROM (SELECT DISTINCT trim(supplier) AS name
              FROM purchase_orders
             WHERE supplier_id IS NULL
               AND supplier IS NOT NULL
               AND trim(supplier) <> '') AS legacy
"""

LEGACY_SUPPLIERS_LINK = """
    UPDATE purchase_orders po
       SET supplier_id = s.id
      FROM suppliers s
     WHERE po.supplier_id IS NULL
       AND s.name = trim(po.supplier)
       AND s.needs_completion = true
"""

# Old behaviour closed an order on its FIRST receipt, whatever arrived.
LEGACY_STATUS_FIX = """
    WITH ord AS (
        SELECT po_id, product_id, qty FROM purchase_order_lines
    ), rec AS (
        SELECT po.id AS po_id, b.product_id, sum(sm.qty_delta) AS qty
          FROM purchase_orders po
          JOIN stock_movements sm
            ON sm.ref_type = 'po' AND sm.ref_id = po.id::text
           AND sm.movement_type = 'receipt'
          JOIN batches b ON b.id = sm.batch_id
         GROUP BY po.id, b.product_id
    )
    UPDATE purchase_orders po
       SET status = 'partially_received'
     WHERE po.status = 'received'
       AND EXISTS (SELECT 1 FROM ord o
                    WHERE o.po_id = po.id
                      AND coalesce((SELECT r.qty FROM rec r
                                     WHERE r.po_id = o.po_id
                                       AND r.product_id = o.product_id), 0) < o.qty)
"""


def upgrade() -> None:
    # ---------------------------------------------------------- suppliers master
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("kind", sa.String(length=20), server_default="supplier", nullable=False),
        sa.Column("registration_type", sa.String(length=20), server_default="regular", nullable=False),
        sa.Column("gstin", sa.String(length=15), nullable=True),
        sa.Column("pan", sa.String(length=10), nullable=True),
        # nullable on purpose: a migrated free-text supplier has no known state yet
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("needs_completion", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("bank_name", sa.String(length=120), nullable=True),
        sa.Column("bank_account_no", sa.String(length=30), nullable=True),
        sa.Column("bank_ifsc", sa.String(length=11), nullable=True),
        sa.Column("bank_holder", sa.String(length=120), nullable=True),
        sa.Column("bank_approved_by", sa.Integer(), nullable=True),
        sa.Column("bank_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('supplier','manufacturer','both')", name="ck_supplier_kind"),
        sa.CheckConstraint("registration_type IN ('regular','composition','unregistered')",
                           name="ck_supplier_registration_type"),
        sa.CheckConstraint("status IN ('active','blocked')", name="ck_supplier_status"),
        sa.CheckConstraint("payment_terms_days >= 0", name="ck_supplier_terms_nonneg"),
        sa.ForeignKeyConstraint(["bank_approved_by"], ["users.id"], name="fk_suppliers_bank_approved_by"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gstin", name="uq_suppliers_gstin"),
    )
    op.create_index(op.f("ix_suppliers_code"), "suppliers", ["code"], unique=True)

    # ---------------------------------------------------------- goods receipts
    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grn_number", sa.String(length=40), nullable=False),
        sa.Column("po_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("received_by", sa.Integer(), nullable=False),
        sa.Column("owner", sa.String(length=20), server_default="HERBANOVA", nullable=False),
        sa.Column("delivery_note", sa.String(length=60), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("owner IN ('HERBANOVA','MANUFACTURER')", name="ck_grn_owner"),
        sa.ForeignKeyConstraint(["po_id"], ["purchase_orders.id"], name="fk_goods_receipts_po"),
        sa.ForeignKeyConstraint(["received_by"], ["users.id"], name="fk_goods_receipts_received_by"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], name="fk_goods_receipts_warehouse"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_goods_receipts_grn_number"), "goods_receipts", ["grn_number"], unique=True)
    op.create_index(op.f("ix_goods_receipts_po_id"), "goods_receipts", ["po_id"], unique=False)
    op.create_index("uq_grn_delivery_note", "goods_receipts", ["po_id", "delivery_note"], unique=True,
                    postgresql_where=sa.text("delivery_note IS NOT NULL"))

    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grn_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.CheckConstraint("qty > 0", name="ck_grn_line_qty_positive"),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], name="fk_goods_receipt_lines_batch"),
        sa.ForeignKeyConstraint(["grn_id"], ["goods_receipts.id"], name="fk_goods_receipt_lines_grn"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_goods_receipt_lines_product"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grn_id", "batch_id", name="uq_grn_line_batch"),
    )

    # ---------------------------------------------------------- approvals history
    op.drop_constraint(op.f("uq_approval_record"), "approval_requests", type_="unique")
    op.create_index("uq_approval_pending", "approval_requests", ["record_type", "record_id"], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))

    # ---------------------------------------------------------- purchase orders
    op.add_column("purchase_orders", sa.Column("supplier_id", sa.Integer(), nullable=True))
    op.add_column("purchase_orders", sa.Column("cancel_reason", sa.String(length=300), nullable=True))
    op.create_foreign_key("fk_purchase_orders_supplier", "purchase_orders", "suppliers",
                          ["supplier_id"], ["id"])
    op.alter_column("purchase_orders", "status", server_default="open")

    # ------------------------------------------------------- seeded role rights
    # The roles were seeded by the Phase 1 migration; give them the supplier
    # rights this module adds, without touching any other permission.
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb || '["supplier:read","supplier:write","supplier:bank"]'::jsonb)::json
         WHERE name = 'admin'
           AND NOT permissions::jsonb @> '["supplier:write"]'::jsonb
        """
    )
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb || '["supplier:read"]'::jsonb)::json
         WHERE name = 'inventory'
           AND NOT permissions::jsonb @> '["supplier:read"]'::jsonb
        """
    )

    # ------------------------------------------- migrate the free-text suppliers
    # Every distinct name on an existing order becomes a real supplier record,
    # flagged for completion, and the order is linked to it (AUD-029). A partly
    # delivered legacy order then stops claiming to be fully received.
    op.execute(LEGACY_SUPPLIERS_INSERT)
    op.execute(LEGACY_SUPPLIERS_LINK)
    op.execute(LEGACY_STATUS_FIX)


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb - 'supplier:read' - 'supplier:write' - 'supplier:bank')::json
         WHERE name = 'admin'
        """
    )
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb - 'supplier:read')::json
         WHERE name = 'inventory'
        """
    )
    op.alter_column("purchase_orders", "status", server_default=None)
    op.drop_constraint("fk_purchase_orders_supplier", "purchase_orders", type_="foreignkey")
    op.drop_column("purchase_orders", "cancel_reason")
    op.drop_column("purchase_orders", "supplier_id")

    op.drop_index("uq_approval_pending", table_name="approval_requests",
                  postgresql_where=sa.text("status = 'pending'"))
    op.create_unique_constraint(op.f("uq_approval_record"), "approval_requests",
                                ["record_type", "record_id"])

    op.drop_table("goods_receipt_lines")
    op.drop_index("uq_grn_delivery_note", table_name="goods_receipts",
                  postgresql_where=sa.text("delivery_note IS NOT NULL"))
    op.drop_index(op.f("ix_goods_receipts_po_id"), table_name="goods_receipts")
    op.drop_index(op.f("ix_goods_receipts_grn_number"), table_name="goods_receipts")
    op.drop_table("goods_receipts")
    op.drop_index(op.f("ix_suppliers_code"), table_name="suppliers")
    op.drop_table("suppliers")
