"""Backend-enforced permissions. Single source of truth -> docs/permissions-matrix.md

Module Phase 1 (AUD-024): permissions resolve from the database role
(user.role_id -> Role.permissions), so a permission edit takes effect on the
very next request and no stale JWT can keep old rights. The fixed baseline
sets remain as the fallback for users without a role_id and as the frozen
parity constant used by seeding and tests.

Session revocation (AUD-027): every JWT carries the user's token_version.
A mismatch (password change, admin reset, deactivation) means the session is
revoked and is rejected with 401, whatever the cookie's expiry.

Forced password change (AUD-026): a user with must_change_password may only
reach /api/auth/me, /api/auth/logout and /api/auth/change-password until the
password is changed.
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .permissions import BASELINE_ROLE_PERMS
from .security import read_token_full

# Backwards-compatible name: the frozen baseline sets (also used by seeding).
ROLE_PERMS: dict[str, set[str]] = BASELINE_ROLE_PERMS

ALLOW_WHILE_MUST_CHANGE = {
    "/api/auth/me", "/api/auth/logout", "/api/auth/change-password",
}


def role_permissions(db: Session, user) -> set[str]:
    """The user's effective permissions: database role first, baseline fallback."""
    role = getattr(user, "role_rel", None)
    if role is None and getattr(user, "role_id", None):
        from ..models.users import Role
        role = db.get(Role, user.role_id)
    if role is not None and role.permissions:
        return set(role.permissions)
    return set(ROLE_PERMS.get(user.role, set()))


def current_user(request: Request, db: Session = Depends(get_db)):
    from ..models.core import User
    parsed = read_token_full(request.cookies.get("session", ""))
    if not parsed:
        raise HTTPException(401, "Not authenticated")
    uid, token_version = parsed
    user = db.get(User, uid)
    if not user or not user.is_active:
        raise HTTPException(401, "Not authenticated")
    if token_version != (user.token_version or 1):
        raise HTTPException(401, "Session expired")     # revoked (password change / reset / offboarding)
    return user


def is_admin(db: Session, user) -> bool:
    """True only for the seeded system administrator role.

    The requirement restricts credit-limit decisions and post-billing edits to
    the Administrator. A custom role must not be able to acquire that status by
    being granted the matching permission, so this checks the role itself.
    """
    role = getattr(user, "role_rel", None)
    if role is None and getattr(user, "role_id", None):
        from ..models.users import Role
        role = db.get(Role, user.role_id)
    if role is not None:
        return (role.name or "").strip().lower() == "admin"
    return (getattr(user, "role", "") or "").strip().lower() == "admin"


def require_admin(perm: str):
    """Permission plus the administrator role; enforced on the server, never the UI."""
    def dep(request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
        if user.must_change_password and request.url.path not in ALLOW_WHILE_MUST_CHANGE:
            raise HTTPException(403, "You must change your password before using the application")
        if perm not in role_permissions(db, user) or not is_admin(db, user):
            raise HTTPException(403, "Only an Administrator can do this")
        return user
    return dep


def require(perm: str):
    def dep(request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
        if user.must_change_password and request.url.path not in ALLOW_WHILE_MUST_CHANGE:
            raise HTTPException(403, "You must change your password before using the application")
        if perm not in role_permissions(db, user):
            raise HTTPException(403, "Permission denied")
        return user
    return dep


def require_login(request: Request, user=Depends(current_user)):
    """Plain 'logged in' gate that still honours the forced password change."""
    if user.must_change_password and request.url.path not in ALLOW_WHILE_MUST_CHANGE:
        raise HTTPException(403, "You must change your password before using the application")
    return user
