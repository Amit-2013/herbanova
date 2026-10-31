"""admin secondary password for db reset

Adds a nullable `reset_password_secondary_hash` column to `users` so an
administrator can set a separate secondary password that is required to
authorize a full data reset. The hash uses the same argon2 pipeline as
the login password.

Revision ID: 1a2b3c4d5e6f
Revises: fef3eeb03094
Create Date: 2026-10-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = 'fef3eeb03094'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'reset_password_secondary_hash',
            sa.String(length=255),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'reset_password_secondary_hash')
