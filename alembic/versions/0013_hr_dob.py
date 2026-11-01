"""Employee date of birth, for the HR dashboard birthday card.

One nullable column on the existing employee master. Nothing else changes;
older rows stay valid and are reported as incomplete records until filled.

Revision ID: 0013_hr_dob
Revises: 0012_hr_upgrade
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_hr_dob"
down_revision: Union[str, None] = "0012_hr_upgrade"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("date_of_birth", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "date_of_birth")
