"""admin reset metadata on users

Adds the timestamp, counter and last-reset time used by the
db:reset flow so the secondary password lifecycle and reset
events are auditable.

Revision ID: 2b3c4d5e6f7g
Revises: 1a2b3c4d5e6f
Create Date: 2026-10-23 00:00:01.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '2b3c4d5e6f7g'
down_revision: Union[str, None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'secondary_set_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        'users',
        sa.Column(
            'db_reset_count',
            sa.Integer(),
            nullable=True,
            server_default=sa.text('0'),
        ),
    )
    op.add_column(
        'users',
        sa.Column(
            'db_reset_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'db_reset_at')
    op.drop_column('users', 'db_reset_count')
    op.drop_column('users', 'secondary_set_at')
