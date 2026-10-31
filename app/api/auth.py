"""Authentication (FR-01).

Module Phase 1 hardening: login is rate limited per IP (slowapi), the account
locks after repeated failures (counted per user record, so letter-case changes
cannot bypass it), usernames are matched case-insensitively through
users.username_key, and a user whose temporary password has not been changed
yet may only reach the change-password endpoint. Changing the password bumps
the token version, which revokes every other session immediately.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..core.limiter import limiter
from ..core.permissions import PERMISSIONS
from ..core.rbac import current_user, require_login, role_permissions
from ..core.security import (hash_password, make_token, read_token_full,
                             validate_password, verify_password)
from ..models.core import User
from ..services.audit import audit
from ..services.lockout import LOCK_MINUTES, clear_failures, is_locked, register_failure

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_RATE = "20/minute"      # per IP; the per-account lockout does the fine-grained work


class Login(BaseModel):
    username: str
    password: str


class ChangePassword(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def policy(cls, v):
        validate_password(v)
        return v


def _identity(user: User, db: Session) -> dict:
    return {"username": user.username, "role": user.role,
            "permissions": sorted(role_permissions(db, user)),
            "must_change_password": bool(user.must_change_password)}


@router.post("/login")
@limiter.limit(LOGIN_RATE)
def login(body: Login, request: Request, resp: Response, db: Session = Depends(get_db)):
    key = body.username.strip().lower()
    u = db.scalar(select(User).where(User.username_key == key))
    if not u or not u.is_active or not verify_password(body.password, u.password_hash):
        if u is not None and u.is_active:
            locked_now = register_failure(db, u)
            db.commit()                              # persist the attempt count
            if locked_now:
                audit(db, u.id, "auth.lockout", f"user:{u.id}", {"minutes": LOCK_MINUTES})
                db.commit()
        raise HTTPException(401, "Invalid credentials")
    if is_locked(u):
        raise HTTPException(423, "Account temporarily locked after too many failed "
                                 f"attempts. Try again in {LOCK_MINUTES} minutes.")
    clear_failures(db, u)
    resp.set_cookie("session", make_token(u.id, u.token_version or 1), httponly=True,
                    samesite="lax", secure=settings.app_env != "local", max_age=3600)
    audit(db, u.id, "auth.login", f"user:{u.id}")
    db.commit()
    return _identity(u, db)


@router.post("/logout")
def logout(resp: Response):
    resp.delete_cookie("session")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(require_login), db: Session = Depends(get_db)):
    """Who the session cookie belongs to - lets the UI restore a session after reload."""
    return _identity(user, db)


@router.post("/change-password")
@limiter.limit("10/minute")
def change_password(body: ChangePassword, request: Request, resp: Response,
                    user=Depends(current_user), db: Session = Depends(get_db)):
    """Self-service password change (FR-01). Revokes every other session by
    bumping the token version, then issues a fresh cookie for this one."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(400, "New password must differ from the current password")
    try:
        validate_password(body.new_password, user.username)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc)
    user.token_version = (user.token_version or 1) + 1
    audit(db, user.id, "auth.password_change", f"user:{user.id}")
    db.commit()
    resp.set_cookie("session", make_token(user.id, user.token_version), httponly=True,
                    samesite="lax", secure=settings.app_env != "local", max_age=3600)
    return _identity(user, db)
