"""Half-day leave on the attendance row.

A half-day application deducts half a day from the balance, so the attendance
day must record which half was leave. Null means a full day, which keeps every
existing row valid.

Revision ID: 0014_hr_leave_portion
Revises: 0013_hr_dob
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_hr_leave_portion"
down_revision: Union[str, None] = "0013_hr_dob"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hr_attendance",
                  sa.Column("leave_portion", sa.String(length=12), nullable=True))
    op.create_check_constraint(
        "ck_hr_attendance_leave_portion",
        "hr_attendance",
        "leave_portion IS NULL OR leave_portion IN ('full','first_half','second_half')")


def downgrade() -> None:
    op.drop_constraint("ck_hr_attendance_leave_portion", "hr_attendance",
                       type_="check")
    op.drop_column("hr_attendance", "leave_portion")
