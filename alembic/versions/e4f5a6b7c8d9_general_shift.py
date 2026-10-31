"""Place employees on the general office shift.

Late arrival and early departure are calculated from the employee's shift, but
no shift had been seeded, so every employee had `shift_id` NULL and both figures
stayed at zero. This adds one General shift with the office timings (09:30 to
18:30, ten minutes' grace, Monday to Friday) and assigns it to employees who
have no shift. An employee already on another shift is left alone.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHIFT = "General"


def upgrade() -> None:
    op.execute(sa.text("""
        INSERT INTO hr_shifts (name, start_time, end_time, grace_minutes,
                               full_day_hours, half_day_hours, weekly_offs, status)
        SELECT :name, TIME '09:30', TIME '18:30', 10, 8, 4, '[5, 6]'::json, 'active'
         WHERE NOT EXISTS (SELECT 1 FROM hr_shifts WHERE name = :name)
    """).bindparams(name=SHIFT))
    op.execute(sa.text("""
        UPDATE employees
           SET shift_id = (SELECT id FROM hr_shifts WHERE name = :name)
         WHERE shift_id IS NULL
    """).bindparams(name=SHIFT))


def downgrade() -> None:
    op.execute(sa.text("""
        UPDATE employees
           SET shift_id = NULL
         WHERE shift_id = (SELECT id FROM hr_shifts WHERE name = :name)
    """).bindparams(name=SHIFT))
    op.execute(sa.text("DELETE FROM hr_shifts WHERE name = :name").bindparams(name=SHIFT))
