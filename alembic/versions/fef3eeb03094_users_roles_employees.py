"""users roles employees

Module Phase 1 (AUD-024 to AUD-027, AUD-044).

- Creates `roles` (database permission matrix) and `employees` (employee
  master, at most one login per employee).
- Extends `users` with the session-revocation token version, password-lifecycle
  and lockout columns plus the case-insensitive `username_key`.
- Backfills `username_key` from the existing usernames and links every existing
  account to its role by name.
- Seeds the four system roles with the frozen baseline permission sets, so the
  seeded roles behave exactly like the previous fixed roles (parity test:
  tests/test_roles_parity.py).

The role sets are embedded here on purpose: a migration must keep working even
if the application's constants change later.

Revision ID: fef3eeb03094
Revises: 0cc7001056e6
Create Date: 2026-10-20 00:42:29.799710

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'fef3eeb03094'
down_revision: Union[str, None] = '0cc7001056e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen baseline sets (see app/core/permissions.py). Do not edit here without a
# documented role-permission change and a parity-test update.
BASELINE_ROLES = {
    "admin": ["approval:decide", "audit:read", "credit:manage", "db:reset", "dispatch:write",
              "distributor:write", "employee:read", "employee:write", "lead:assign",
              "lead:read", "lead:write", "product:read", "product:write",
              "report:export", "sales:read", "sales:write", "stock:read",
              "stock:write", "user:manage"],
    "inventory": ["dispatch:write", "product:read", "product:write", "sales:read",
                  "stock:read", "stock:write"],
    "sales": ["distributor:write", "lead:read", "lead:write", "product:read",
              "report:export", "sales:read", "sales:write", "stock:read"],
    "viewer": ["product:read", "sales:read", "stock:read"],
}


def upgrade() -> None:
    op.create_table(
        'employees',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('full_name', sa.String(length=120), nullable=False),
        sa.Column('department', sa.String(length=60), nullable=True),
        sa.Column('designation', sa.String(length=80), nullable=True),
        sa.Column('phone', sa.String(length=40), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('joining_date', sa.Date(), nullable=True),
        sa.Column('manager_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['manager_id'], ['employees.id'], name='fk_employees_manager'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_employees_user'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_employees_user'),
    )
    op.create_index(op.f('ix_employees_code'), 'employees', ['code'], unique=True)

    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('display_name', sa.String(length=80), nullable=False),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('permissions', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_roles_name'), 'roles', ['name'], unique=True)

    op.add_column('users', sa.Column('username_key', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('role_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('employee_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    op.add_column('users', sa.Column('failed_attempts', sa.Integer(), nullable=False,
                                     server_default=sa.text('0')))
    op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False,
                                     server_default=sa.text('1')))
    op.add_column('users', sa.Column('password_changed_at', sa.DateTime(timezone=True),
                                     nullable=True))
    op.create_unique_constraint('uq_users_username_key', 'users', ['username_key'])
    op.create_unique_constraint('uq_users_employee_id', 'users', ['employee_id'])
    op.create_foreign_key('fk_users_employee', 'users', 'employees', ['employee_id'], ['id'])
    op.create_foreign_key('fk_users_role', 'users', 'roles', ['role_id'], ['id'])

    # --- data backfill -------------------------------------------------------
    op.execute("UPDATE users SET username_key = lower(username) WHERE username_key IS NULL")

    roles_table = sa.table(
        'roles',
        sa.column('name', sa.String),
        sa.column('display_name', sa.String),
        sa.column('is_system', sa.Boolean),
        sa.column('permissions', sa.JSON),
    )
    op.bulk_insert(roles_table, [
        {"name": name, "display_name": name.capitalize(), "is_system": True,
         "permissions": perms}
        for name, perms in BASELINE_ROLES.items()
    ])

    # link existing accounts to their role by name (accounts with an unknown
    # role keep role_id NULL; the API falls back to the baseline sets)
    op.execute(
        "UPDATE users u SET role_id = r.id FROM roles r WHERE r.name = u.role "
        "AND u.role_id IS NULL")


def downgrade() -> None:
    op.drop_constraint('fk_users_role', 'users', type_='foreignkey')
    op.drop_constraint('fk_users_employee', 'users', type_='foreignkey')
    op.drop_constraint('uq_users_employee_id', 'users', type_='unique')
    op.drop_constraint('uq_users_username_key', 'users', type_='unique')
    op.drop_column('users', 'password_changed_at')
    op.drop_column('users', 'token_version')
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_attempts')
    op.drop_column('users', 'must_change_password')
    op.drop_column('users', 'employee_id')
    op.drop_column('users', 'role_id')
    op.drop_column('users', 'username_key')
    op.drop_index(op.f('ix_roles_name'), table_name='roles')
    op.drop_table('roles')
    op.drop_index(op.f('ix_employees_code'), table_name='employees')
    op.drop_table('employees')
