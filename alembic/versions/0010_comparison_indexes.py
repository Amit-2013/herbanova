"""Index the date columns the MoM/YoY comparison scans.

Every figure on the comparison page is a range aggregate over one date column.
These four indexes make those ranges cheap without touching a single row.
`invoices.invoice_date` is already indexed by `5df004690f25`.

Revision ID: 0010_comparison_indexes
Revises: 0009_warehouse_capacity
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010_comparison_indexes"
down_revision: Union[str, None] = "0009_warehouse_capacity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = (
    ("ix_sales_orders_created_at", "sales_orders", ["created_at"]),
    ("ix_credit_notes_note_date", "credit_notes", ["note_date"]),
    ("ix_goods_receipts_received_at", "goods_receipts", ["received_at"]),
    ("ix_leads_created_at", "leads", ["created_at"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
