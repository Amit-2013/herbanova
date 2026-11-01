"""Map the seeded statutory salary components to a statutory head.

The payroll migration already seeded PF, ESI, TDS and PROF_TAX as statutory
deductions. Only the summary each one belongs to is filled in here, so the
PF/ESI/PT/TDS summaries have something to group by without anyone editing the
master first. No rate or amount is written: the rate stays whatever the
structure line or the component's configured default already is.

An Administrator can change or clear the mapping through the salary-component
endpoint. Components with no head are reported as a configuration gap rather
than being forced into a summary.

Revision ID: 0015_statutory_heads
Revises: 0014_hr_leave_portion
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0015_statutory_heads"
down_revision: Union[str, None] = "0014_hr_leave_portion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MAPPING = (("PF", "pf"), ("ESI", "esi"), ("TDS", "tds"), ("PROF_TAX", "pt"))


def upgrade() -> None:
    for code, head in MAPPING:
        op.execute(
            "UPDATE hr_salary_components SET statutory_head = "
            f"'{head}' WHERE code = '{code}' AND statutory IS TRUE "
            "AND statutory_head IS NULL")


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _ in MAPPING)
    op.execute(f"UPDATE hr_salary_components SET statutory_head = NULL WHERE code IN ({codes})")
