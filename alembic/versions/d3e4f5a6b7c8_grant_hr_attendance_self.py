"""Grant non-HR staff the right to record their own attendance.

Sales, inventory and viewer are the logins held by staff who work from an office,
but only the HR roles carried `hr:attendance_self`, so those users could not check
in or out at their branch. The permission is self-scoped: it allows their own
attendance only, not the team's, and it does not open the employee master.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLES = ("sales", "inventory", "viewer")
PERMISSION = "hr:attendance_self"


def _rewrite(add: bool) -> None:
    bind = op.get_bind()
    roles = sa.table("roles", sa.column("name", sa.String), sa.column("permissions", sa.JSON))
    for name in ROLES:
        row = bind.execute(sa.select(roles.c.permissions).where(roles.c.name == name)).first()
        if row is None:
            continue
        current = list(row[0] or [])
        if add:
            if PERMISSION not in current:
                current.append(PERMISSION)
        else:
            current = [k for k in current if k != PERMISSION]
        bind.execute(roles.update().where(roles.c.name == name).values(permissions=current))


def upgrade() -> None:
    _rewrite(True)


def downgrade() -> None:
    _rewrite(False)
