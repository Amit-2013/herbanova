"""Add the separate reset key used by the guarded database reset.

Additive only: two nullable columns on ``users``. Existing accounts keep
working; an account without a reset key simply cannot complete a reset until
one is set through ``POST /api/admin/reset-key``.

Revision ID: 0019_db_reset_key
Revises: 0018_attendance_rules
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019_db_reset_key"
down_revision: Union[str, None] = "0018_attendance_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("reset_key_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("reset_key_set_at",
                                     sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "reset_key_set_at")
    op.drop_column("users", "reset_key_hash")
