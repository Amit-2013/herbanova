"""Set the seeded admin's secondary password.

This is the secret an administrator must present to POST
/api/db/reset. It is independent of the daily login password.

Usage:
    python seed_admin_secondary.py <secondary password>

The password is hashed with the same argon2 parameters the reset endpoint
verifies against, so it can be checked without ever being stored in plain text.
"""
import sys
import argparse

import argon2

from app.core.db import SessionLocal
from app.models.core import User

HASHER = argon2.PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_secondary(secret: str) -> str:
    """Return a canonical argon2 hex hash for *secret*."""
    return HASHER.hash(secret)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Set the admin secondary password used to authorize db/reset"
    )
    ap.add_argument("secondary_password", help="the new secondary password")
    args = ap.parse_args()

    if len(args.secondary_password) < 8:
        print("ERROR: the secondary password must be at least 8 characters", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        admin = db.get(User, 1)
        if admin is None:
            print("ERROR: admin user id=1 not found; run seed.py first", file=sys.stderr)
            return 1
        admin.reset_password_secondary_hash = hash_secondary(args.secondary_password)
        from datetime import datetime, timezone
        admin.secondary_set_at = datetime.now(timezone.utc)
        db.add(admin)
        db.commit()

    print("OK: admin secondary password set (not printed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
