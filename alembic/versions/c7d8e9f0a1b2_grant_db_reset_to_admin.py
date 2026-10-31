"""grant db:reset to the admin role

Existing installations seeded their roles before ``db:reset`` was added to the
administrator baseline. A fresh database gets the permission from the frozen
role seed, but an already-migrated database needs this data migration or the
reset endpoint (and its dashboard button) stays unreachable.

Revision ID: c7d8e9f0a1b2
Revises: f0a1b2c3d4e5
Create Date: 2026-10-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = (
            COALESCE(permissions, '[]'::json)::jsonb || '["db:reset"]'::jsonb
        )::json
        WHERE name = 'admin'
          AND NOT (
            COALESCE(permissions, '[]'::json)::jsonb @> '["db:reset"]'::jsonb
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = (
            COALESCE(permissions, '[]'::json)::jsonb - 'db:reset'
        )::json
        WHERE name = 'admin'
        """
    )
