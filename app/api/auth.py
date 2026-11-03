"""Authentication (FR-01).

Module Phase 1 hardening: login is rate limited per IP (slowapi), the account
locks after repeated failures (counted per user record, so letter-case changes
cannot bypass it), usernames are matched case-insensitively through
users.username_key, and a user whose temporary password has not been changed
yet may only reach the change-password endpoint. Changing the password bumps
the token version, which revokes every other session immediately.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..core.limiter import limiter
from ..core.permissions import PERMISSIONS
from ..core.rbac import current_user, require_login, role_permissions
from ..core.security import (hash_password, make_token, validate_password,
                             verify_password)
from ..models.core import User
from ..services import totp
from ..services.audit import audit
from ..services.feature_store import enabled_keys
from ..services.lockout import LOCK_MINUTES, clear_failures, is_locked, register_failure

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_RATE = "20/minute"      # per IP; the per-account lockout does the fine-grained work
OTP_RATE = "10/minute"


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


class TotpCode(BaseModel):
    code: str = ""


class TotpVerify(BaseModel):
    code: str = ""
    recovery_code: str = ""


def _identity(user: User, db: Session) -> dict:
    return {"username": user.username, "role": user.role,
            "permissions": sorted(role_permissions(db, user)),
            "features": sorted(enabled_keys(db)),
            "must_change_password": bool(user.must_change_password),
            "totp": {"required": totp.requires_totp(user),
                     "enabled": bool(user.totp_enabled)}}


def _set_session(resp: Response, user: User) -> None:
    """Issue the session cookie. Only an accepted second factor sets the `otp`
    claim for an enrolled account, so the claim cannot be obtained from the
    password step alone."""
    resp.set_cookie("session",
                    make_token(user.id, user.token_version or 1,
                               otp=bool(user.totp_enabled)),
                    httponly=True, samesite="lax", secure=settings.app_env != "local",
                    max_age=3600)


def _set_challenge(resp: Response, user: User, mode: str) -> None:
    resp.set_cookie(totp.CHALLENGE_COOKIE,
                    totp.make_challenge(user.id, user.token_version or 1, mode),
                    httponly=True, samesite="lax", secure=settings.app_env != "local",
                    max_age=totp.CHALLENGE_MINUTES * 60, path="/api/auth")


def _clear_challenge(resp: Response) -> None:
    resp.delete_cookie(totp.CHALLENGE_COOKIE, path="/api/auth")


def _challenge_user(request: Request, db: Session, mode: str) -> User:
    """The account behind a valid password-step ticket, for this mode only."""
    ticket = totp.read_challenge(request.cookies.get(totp.CHALLENGE_COOKIE, ""), mode)
    if not ticket:
        raise HTTPException(401, "Start signing in again")
    user = db.get(User, ticket[0])
    if not user or not user.is_active:
        raise HTTPException(401, "Not authenticated")
    if ticket[1] != (user.token_version or 1):
        raise HTTPException(401, "Start signing in again")
    return user


def _otp_failure(db: Session, user: User, resp: Response) -> None:
    """Count a wrong code; five in a row pause code entry for 15 minutes."""
    user.totp_failed_attempts = (user.totp_failed_attempts or 0) + 1
    if user.totp_failed_attempts >= totp.MAX_OTP_FAILURES:
        user.totp_locked_until = datetime.now(timezone.utc) + timedelta(
            minutes=totp.OTP_LOCK_MINUTES)
        user.totp_failed_attempts = 0
        _clear_challenge(resp)
        audit(db, user.id, "auth.totp_lockout", f"user:{user.id}",
              {"minutes": totp.OTP_LOCK_MINUTES}, notify=False)
    db.commit()


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
    db.commit()

    if totp.requires_totp(u):
        # Password alone never produces a session for these roles. An account
        # with a readable secret gets the code screen; an account without one
        # is sent through enrollment. No cookie here can read data.
        secret = totp.unseal(u.totp_secret)
        mode = "verify" if (u.totp_enabled and secret) else "setup"
        _set_challenge(resp, u, mode)
        audit(db, u.id, "auth.password_ok", f"user:{u.id}", {"mode": mode},
              notify=False)
        db.commit()
        return {"status": "otp_required" if mode == "verify" else "setup_required",
                "username": u.username}

    _set_session(resp, u)
    audit(db, u.id, "auth.login", f"user:{u.id}")
    db.commit()
    return {"status": "ok", **_identity(u, db)}


@router.get("/2fa/setup")
@limiter.limit(OTP_RATE)
def totp_setup(request: Request, resp: Response, db: Session = Depends(get_db)):
    """Start enrollment: a new secret for the authenticated password step."""
    user = _challenge_user(request, db, "setup")
    if user.totp_enabled and totp.unseal(user.totp_secret):
        raise HTTPException(409, "Two-factor is already enabled. Sign in with a code.")
    secret = totp.generate_secret()
    user.totp_secret = totp.seal(secret)
    user.totp_enabled = False
    user.totp_confirmed_at = None
    user.totp_last_counter = None
    db.commit()
    return {"secret": secret,
            "otpauth_uri": totp.provisioning_uri(secret, user.username),
            "issuer": totp.ISSUER, "account": user.username,
            "digits": totp.DIGITS, "period": totp.STEP_SECONDS}


@router.post("/2fa/confirm")
@limiter.limit(OTP_RATE)
def totp_confirm(body: TotpCode, request: Request, resp: Response,
                 db: Session = Depends(get_db)):
    """Finish enrollment with a code from the app, then sign in."""
    user = _challenge_user(request, db, "setup")
    secret = totp.unseal(user.totp_secret)
    if not secret:
        raise HTTPException(409, "Start two-factor setup again")
    step = totp.verify_code(secret, body.code, after_counter=user.totp_last_counter)
    if step is None:
        _otp_failure(db, user, resp)
        raise HTTPException(401, "That code was not accepted. Try the current code.")
    codes = totp.generate_recovery_codes()
    user.totp_enabled = True
    user.totp_confirmed_at = datetime.now(timezone.utc)
    user.totp_last_counter = step
    user.totp_failed_attempts = 0
    user.totp_locked_until = None
    user.totp_recovery_hashes = totp.hash_recovery_codes(codes)
    user.token_version = (user.token_version or 1) + 1   # end any pre-enrollment session
    audit(db, user.id, "auth.totp_enabled", f"user:{user.id}",
          {"recovery_codes": len(codes)}, notify=False)
    db.commit()
    _set_session(resp, user)
    _clear_challenge(resp)
    return {"status": "ok", "recovery_codes": codes, **_identity(user, db)}


@router.post("/2fa/verify")
@limiter.limit(OTP_RATE)
def totp_verify(body: TotpVerify, request: Request, resp: Response,
                db: Session = Depends(get_db)):
    """Second step of an enrolled Administrator's sign-in."""
    user = _challenge_user(request, db, "verify")
    remaining = totp.lock_remaining(user)
    if remaining:
        raise HTTPException(423, "Too many wrong codes. Try again in "
                                 f"{(remaining + 59) // 60} minute(s).")
    secret = totp.unseal(user.totp_secret)
    if not user.totp_enabled or not secret:
        raise HTTPException(409, "Two-factor setup is required")

    method = None
    if body.recovery_code.strip():
        matched, left = totp.take_recovery_code(user.totp_recovery_hashes,
                                                body.recovery_code)
        if matched:
            user.totp_recovery_hashes = left
            method = "recovery"
    else:
        step = totp.verify_code(secret, body.code, after_counter=user.totp_last_counter)
        if step is not None:
            user.totp_last_counter = step
            method = "totp"
    if method is None:
        _otp_failure(db, user, resp)
        raise HTTPException(401, "That code was not accepted.")

    user.totp_failed_attempts = 0
    user.totp_locked_until = None
    clear_failures(db, user)
    audit(db, user.id, "auth.totp_login", f"user:{user.id}", {"method": method},
          notify=False)
    db.commit()
    _set_session(resp, user)
    _clear_challenge(resp)
    return {"status": "ok", "method": method, **_identity(user, db)}


@router.get("/2fa/status")
def totp_status(user=Depends(require_login), db: Session = Depends(get_db)):
    """The signed-in account's own second-factor state; never the secret."""
    return {"required": totp.requires_totp(user),
            "enabled": bool(user.totp_enabled),
            "confirmed_at": (user.totp_confirmed_at.isoformat()
                             if user.totp_confirmed_at else None),
            "recovery_codes_left": len(user.totp_recovery_hashes or [])}


@router.post("/logout")
def logout(resp: Response):
    resp.delete_cookie("session")
    _clear_challenge(resp)
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
    _set_session(resp, user)
    return _identity(user, db)
