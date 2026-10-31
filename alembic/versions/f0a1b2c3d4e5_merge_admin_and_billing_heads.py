"""merge admin reset and billing heads

Revision ID: f0a1b2c3d4e5
Revises: 8e1b2c3d4e5f, 9cb3f04c3ba6
Create Date: 2026-10-24 00:00:00.000000

The admin-reset feature and the billing/print/expiry chain were developed on
separate branches. Both add their own columns and neither is a replacement for
the other, so a merge revision is the correct single head.

The duplicate admin-reset drafts (1a2b3c4d5e6f and 2b3c4d5e6f7g) added subsets
of the same columns. They are preserved under alembic/retired_versions and are
deliberately not part of this graph: they were never applied to the configured
database and replaying either of them alongside 8e1b2c3d4e5f would add the same
columns twice.
"""
from typing import Sequence, Union

revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = ("8e1b2c3d4e5f", "9cb3f04c3ba6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Both branches already carry their schema; the merge adds no objects."""


def downgrade() -> None:
    """Removing the merge returns to the two independent heads."""
