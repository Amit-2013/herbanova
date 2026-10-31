"""Phase 1: admin approvals, post-billing edits, PO rate remarks, indexes

Revision ID: b1c2d3e4f5a6
Revises: aa11bb22cc33
Create Date: 2026-10-30 10:00:00.000000

Additive only. Existing purchase-order lines keep their stored unit cost; new
lines may leave the cost blank only when a rate remark explains why. The
approval table gains the generic columns the central queue needs for HR later.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "aa11bb22cc33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ADMIN_PERMS = [
    "approval:read", "approval:credit_limit", "invoice:edit_post_billing",
    "hr:read", "hr:write", "hr:attendance_self", "hr:attendance_manage",
    "hr:leave_approve", "hr:payroll_prepare", "hr:payroll_approve",
    "hr:confidential", "hr:reports",
]
OTHER_GRANTS = {"sales": ["approval:read"], "inventory": ["approval:read"]}


def _rewrite_roles(add: bool) -> None:
    bind = op.get_bind()
    roles = sa.table("roles", sa.column("name", sa.String), sa.column("permissions", sa.JSON))
    grants = {"admin": ADMIN_PERMS, **OTHER_GRANTS}
    for name, keys in grants.items():
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
    # ---- purchase order lines: blank cost needs a remark
    op.add_column("purchase_order_lines", sa.Column("rate_remark", sa.String(30), nullable=True))
    op.alter_column("purchase_order_lines", "unit_cost", existing_type=sa.Numeric(14, 2),
                    nullable=True)
    op.drop_constraint("ck_po_line_cost_nonneg", "purchase_order_lines", type_="check")
    op.create_check_constraint("ck_po_line_cost_nonneg", "purchase_order_lines",
                               "unit_cost IS NULL OR unit_cost >= 0")
    op.create_check_constraint("ck_po_line_cost_or_remark", "purchase_order_lines",
                               "unit_cost IS NOT NULL OR rate_remark IS NOT NULL")

    # ---- generic approval queue columns (existing sales-order rows stay valid)
    op.add_column("approval_requests", sa.Column("request_no", sa.String(40), nullable=True))
    op.add_column("approval_requests", sa.Column("document_number", sa.String(40), nullable=True))
    op.add_column("approval_requests", sa.Column("subject", sa.String(200), nullable=True))
    op.add_column("approval_requests", sa.Column("requested_dates", sa.String(80), nullable=True))
    op.add_column("approval_requests", sa.Column("pending_approver_role", sa.String(40),
                                                 nullable=True))
    op.create_index("ix_approval_requests_request_no", "approval_requests", ["request_no"],
                    if_not_exists=True)
    op.execute(
        "UPDATE approval_requests SET document_number = "
        "(SELECT so_number FROM sales_orders WHERE sales_orders.id = approval_requests.record_id) "
        "WHERE record_type = 'sales_order' AND document_number IS NULL"
    )

    # ---- indexes for the list/report queries
    for name, table, cols in [
        ("ix_products_hsn", "products", ["hsn"]),
        ("ix_products_status", "products", ["status"]),
        ("ix_leads_status_followup", "leads", ["status", "next_follow_up"]),
        ("ix_sales_orders_status_created", "sales_orders", ["status", "created_at"]),
        ("ix_purchase_orders_status_created", "purchase_orders", ["status", "created_at"]),
        ("ix_invoices_invoice_date", "invoices", ["invoice_date"]),
        ("ix_approval_status_type", "approval_requests", ["status", "record_type"]),
        ("ix_lead_activities_lead_created", "lead_activities", ["lead_id", "created_at"]),
        ("ix_stock_movements_batch_created", "stock_movements", ["batch_id", "created_at"]),
    ]:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({', '.join(cols)})")

    _rewrite_roles(add=True)


def downgrade() -> None:
    _rewrite_roles(add=False)
    for name in ("ix_stock_movements_batch_created", "ix_lead_activities_lead_created",
                 "ix_approval_status_type", "ix_invoices_invoice_date",
                 "ix_purchase_orders_status_created", "ix_sales_orders_status_created",
                 "ix_leads_status_followup", "ix_products_status", "ix_products_hsn"):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.drop_index("ix_approval_requests_request_no", table_name="approval_requests")
    for col in ("pending_approver_role", "requested_dates", "subject", "document_number",
                "request_no"):
        op.drop_column("approval_requests", col)
    op.drop_constraint("ck_po_line_cost_or_remark", "purchase_order_lines", type_="check")
    op.drop_constraint("ck_po_line_cost_nonneg", "purchase_order_lines", type_="check")
    op.execute("UPDATE purchase_order_lines SET unit_cost = 0 WHERE unit_cost IS NULL")
    op.alter_column("purchase_order_lines", "unit_cost", existing_type=sa.Numeric(14, 2),
                    nullable=False)
    op.create_check_constraint("ck_po_line_cost_nonneg", "purchase_order_lines",
                               "unit_cost >= 0")
    op.drop_column("purchase_order_lines", "rate_remark")
