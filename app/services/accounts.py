"""Account helpers shared by the user, role and employee APIs (FR-01, FR-02)."""
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.permissions import (ADMIN_ONLY_PERMISSIONS, PERMISSION_KEYS,
                                sanitized_permissions)
from ..models.core import User
from ..models.users import Role

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    key = normalize_username(username)
    if not USERNAME_RE.match(key):
        raise HTTPException(422, "Username must be 3-64 characters: letters, digits, "
                                 "dot, underscore or hyphen (case-insensitive, no spaces)")
    return key


def get_role(db: Session, ident) -> Role:
    """A role by id or by name (names are matched case-insensitively)."""
    role = db.get(Role, int(ident)) if isinstance(ident, int) or str(ident).isdigit() else None
    if role is None:
        role = db.scalar(select(Role).where(Role.name == str(ident).strip().lower()))
    if role is None:
        raise HTTPException(404, "Role not found")
    return role


def validate_permissions(perms, *, role_name: str | None = None) -> list[str]:
    """Check, then apply the parent/child rules to a role's stored keys.

    Unknown keys are refused. A child sent without its parent is dropped, which
    is the server-side half of "unchecking a parent removes its children"; the
    caller audits the dropped list. An Administrator-only key on any other role
    is refused outright: silently dropping a money-deciding right would hide a
    mistake in the caller.
    """
    unknown = sorted(set(perms or []) - PERMISSION_KEYS)
    if unknown:
        raise HTTPException(422, f"Unknown permission(s): {', '.join(unknown)}")
    requested = set(perms or [])
    if (role_name or "").strip().lower() != "admin":
        forbidden = sorted(requested & ADMIN_ONLY_PERMISSIONS)
        if forbidden:
            raise HTTPException(
                422, "Only the Administrator role can hold: " + ", ".join(forbidden))
    kept, _dropped = sanitized_permissions(requested)
    return kept


def dropped_permissions(perms) -> list[str]:
    """The children a permission list loses under the parent/child rules."""
    _kept, dropped = sanitized_permissions(perms)
    return dropped


def active_user_manage_ids(db: Session) -> set[int]:
    """Ids of active users whose role still grants user:manage (the administrators)."""
    rows = db.execute(
        select(User.id, Role.permissions)
        .join(Role, Role.id == User.role_id)
        .where(User.is_active.is_(True))).all()
    return {uid for uid, perms in rows if "user:manage" in (perms or [])}


def guard_last_admin(db: Session, target: User, *, losing_admin: bool) -> None:
    """The last active administrator cannot be deactivated or demoted (FR-02)."""
    if not losing_admin:
        return
    others = active_user_manage_ids(db) - {target.id}
    if not others:
        raise HTTPException(403, "This is the last active administrator; "
                                 "promote another user first")
