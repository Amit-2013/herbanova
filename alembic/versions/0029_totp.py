"""Administrator two-factor authentication (Google Authenticator / TOTP).

Additive only: new columns on `users`, no value on an existing row changes.

- `totp_secret` holds the shared secret sealed with a key derived from
  `APP_SECRET`, so a database dump alone cannot produce codes.
- `totp_enabled` is the switch the backend checks. Until it is true the
  Administrator is sent through enrollment at the next password login; there
  is no password-only session for an enrolled account.
- `totp_last_counter` records the accepted 30-second step, so a code cannot be
  replayed inside its window.
- `totp_failed_attempts` / `totp_locked_until` limit code guessing without
  touching the password lockout.
- `totp_recovery_hashes` stores argon2 hashes of single-use recovery codes.

The upgrade also bumps `token_version` for the Administrator roles, so every
session issued before this release ends and must pass the second factor.

Revision ID: 0029_totp
Revises: 0028_advances
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_totp"
down_revision: Union[str, None] = "0028_advances"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TOTP_ROLES = ("admin", "super_admin")


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(length=512), nullable=True))
    op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    op.add_column("users", sa.Column("totp_confirmed_at",
                                     sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_last_counter", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("totp_failed_attempts", sa.Integer(), nullable=False,
                                     server_default="0"))
    op.add_column("users", sa.Column("totp_locked_until",
                                     sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_recovery_hashes", sa.JSON(), nullable=True))
    roles = ",".join(f"'{name}'" for name in TOTP_ROLES)
    op.execute(
        "UPDATE users SET token_version = COALESCE(token_version, 1) + 1 "
        f"WHERE lower(role) IN ({roles}) "
        "OR role_id IN (SELECT id FROM roles WHERE lower(name) IN "
        f"({roles}))")


def downgrade() -> None:
    # Sessions stay revoked by design: the bump cannot be reversed without
    # reviving the tokens this release was meant to end.
    op.drop_column("users", "totp_recovery_hashes")
    op.drop_column("users", "totp_locked_until")
    op.drop_column("users", "totp_failed_attempts")
    op.drop_column("users", "totp_last_counter")
    op.drop_column("users", "totp_confirmed_at")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
