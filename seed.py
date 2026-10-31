"""Create the four role accounts with random passwords (printed once).

Usage:
    python seed.py             # create missing accounts, print their passwords once
    python seed.py --reset     # rotate passwords of existing accounts and print them

Module Phase 1 additions:
- the four roles are seeded into the `roles` table with the frozen baseline
  permission sets, and every role account is linked to its role;
- each account gets an Employee record (code = the username) if it has none;
- existing accounts get their lower-case username_key filled in.

Passwords are shown only at creation/rotation - they are argon2-hashed on
storage and cannot be recovered afterwards.
"""
import argparse
import secrets
import sys

from sqlalchemy import inspect, select

from app.core.db import engine, SessionLocal
from app.core.permissions import BASELINE_ROLE_PERMS
from app.core.security import hash_password
from app.models.core import User
from app.models.users import Employee, Role

ROLES = ("admin", "sales", "inventory", "viewer")

DESIGNATIONS = {"admin": "Administrator", "sales": "Sales executive",
                "inventory": "Inventory manager", "viewer": "Viewer"}


def new_password() -> str:
    return secrets.token_urlsafe(12)


def ensure_roles(db) -> dict[str, Role]:
    roles = {}
    for name, perms in BASELINE_ROLE_PERMS.items():
        role = db.scalar(select(Role).where(Role.name == name))
        if role is None:
            role = Role(name=name, display_name=name.capitalize(), is_system=True,
                        permissions=sorted(perms))
            db.add(role)
            db.flush()
        roles[name] = role
    return roles


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed the four role accounts")
    ap.add_argument("--reset", action="store_true",
                    help="rotate passwords for accounts that already exist")
    args = ap.parse_args()

    if not inspect(engine).has_table("users"):
        sys.exit("REFUSED: 'users' table missing - run: alembic upgrade head first")

    printed = 0
    with SessionLocal() as db:
        roles = ensure_roles(db)
        for role_name in ROLES:
            role = roles[role_name]
            user = db.scalars(select(User).where(User.username == role_name)).first()
            if user is None:
                pw = new_password()
                user = User(username=role_name, username_key=role_name,
                            password_hash=hash_password(pw), role=role_name, role_id=role.id)
                db.add(user)
                db.flush()
                print(f"{role_name:<10} role={role_name:<9} password: {pw}")
                printed += 1
            else:
                if args.reset:
                    pw = new_password()
                    user.password_hash = hash_password(pw)
                    print(f"{role_name:<10} role={role_name:<9} password: {pw} (rotated)")
                    printed += 1
                else:
                    note = "" if user.role == role_name else f" [WARNING: role is '{user.role}']"
                    print(f"{role_name:<10} role={role_name:<9} already exists - "
                          f"password not reprinted{note}")
                if user.role_id is None:                 # link pre-Phase-1 accounts
                    user.role, user.role_id = role_name, role.id
                if user.username_key is None:
                    user.username_key = user.username.lower()
            if user.employee_id is None:                 # one Employee per role account
                emp = Employee(code=role_name.upper()[:30], full_name=role_name.capitalize(),
                               designation=DESIGNATIONS.get(role_name), user_id=user.id)
                db.add(emp)
                db.flush()
                user.employee_id = emp.id
        db.commit()

    print(f"\n{printed} password(s) printed once above - store them now, they are not recoverable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
