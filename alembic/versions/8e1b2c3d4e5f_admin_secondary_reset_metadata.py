"""Admin secondary password + reset metadata on users.

Adds the columns the database-reset recovery flow needs:

* ``reset_password_secondary_hash`` — argon2 hash of the *secondary*
  password an administrator must present to POST ``/api/db/reset``.
* ``secondary_set_at`` — when the secondary password was last set.
* ``db_reset_count`` / ``db_reset_at`` — metadata about every successful wipe.

The reset endpoint is only reachable when both the role permission
``db:reset`` and the secondary password are present.

This revision is on the main line (it revises ``fef3eeb03094``). The two
previous independent heads that added subsets of these columns (``1a2b3c4d5e6f``
and ``2b3c4d5e6f7g``) are no longer referenced by the application; this file
is the canonical place the column set is described in the migration history.
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "8e1b2c3d4e5f"
down_revision: Union[str, None] = "fef3eeb03094"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("reset_password_secondary_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("secondary_set_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("db_reset_count", sa.Integer(), nullable=True, server_default=sa.text("0")),
    )
    op.add_column(
        "users",
        sa.Column("db_reset_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "db_reset_at")
    op.drop_column("users", "db_reset_count")
    op.drop_column("users", "secondary_set_at")
    op.drop_column("users", "reset_password_secondary_hash")
