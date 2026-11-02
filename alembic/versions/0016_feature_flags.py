"""Central feature availability switches.

One row per module the Administrator can switch off. The rows are seeded as
enabled, so applying this migration changes no behaviour: every module that
worked before still works. A missing row also means enabled, so the table never
has to be complete.

Rollback drops the table; the application then treats every module as enabled,
which is exactly the pre-migration state.

Revision ID: 0016_feature_flags
Revises: 0015_statutory_heads
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_feature_flags"
down_revision: Union[str, None] = "0015_statutory_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FEATURE_KEYS = (
    "products", "stock", "suppliers", "sales", "approvals", "leads", "accounts",
    "tax", "reports", "hr", "audit", "scheduled", "users",
)


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column("key", sa.String(length=40), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=True),
    )
    table = sa.table("feature_flags",
                     sa.column("key", sa.String), sa.column("enabled", sa.Boolean))
    op.bulk_insert(table, [{"key": key, "enabled": True} for key in FEATURE_KEYS])


def downgrade() -> None:
    op.drop_table("feature_flags")
