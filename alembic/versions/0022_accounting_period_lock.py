"""Allow an accounting period to be locked, reusing the HR lock pattern.

The ``hr_period_locks`` table already records who locked which month, when, why
and who unlocked it. An accounting month is the same idea with a different
scope, so the only schema change is widening the scope check. No rows are
rewritten.

Revision ID: 0022_accounting_period_lock
Revises: 0021_stock_costs
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0022_accounting_period_lock"
down_revision: Union[str, None] = "0021_stock_costs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_SCOPES = "scope IN ('attendance','payroll')"
NEW_SCOPES = "scope IN ('attendance','payroll','accounting')"


def upgrade() -> None:
    op.drop_constraint("ck_hr_period_lock_scope", "hr_period_locks", type_="check")
    op.create_check_constraint("ck_hr_period_lock_scope", "hr_period_locks", NEW_SCOPES)


def downgrade() -> None:
    # Accounting locks cannot exist before this revision; remove any written
    # after it before narrowing the constraint back, or the ALTER would fail.
    op.execute("DELETE FROM hr_period_locks WHERE scope = 'accounting'")
    op.drop_constraint("ck_hr_period_lock_scope", "hr_period_locks", type_="check")
    op.create_check_constraint("ck_hr_period_lock_scope", "hr_period_locks", OLD_SCOPES)
