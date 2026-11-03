"""User management (FR-01, FR-02, AUD-024 to AUD-026).

- Temporary passwords are generated server-side, returned exactly once and
  stored only as an argon2 hash. Every new or reset password forces a change
  at first login.
- The last active administrator cannot be deactivated or demoted, and nobody
  can change their own role or deactivate themselves.
- Deactivation and password reset bump the token version, which revokes every
  open session for that user immediately.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require
from ..core.security import generate_temp_password, hash_password, validate_password
from ..models.core import User
from ..models.users import Employee, Role
from ..services.accounts import get_role, guard_last_admin, validate_username
from ..services.audit import audit

router = APIRouter(prefix="/api/users", tags=["users"])


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    role_id: int | None
    employee_id: int | None
    is_active: bool
    must_change_password: bool
    locked: bool
    password_changed_at: datetime | None = None


class CreateUserIn(BaseModel):
    username: str
    role: str                       # role name or id
    employee_id: int | None = None
    password: str | None = None     # optional; a temporary one is generated when omitted

    @field_validator("username")
    @classmethod
    def strip(cls, v): return v.strip()


class UpdateUserIn(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    employee_id: int | None = None


class UserCreatedOut(UserOut):
    temporary_password: str         # shown exactly once, never retrievable again


def _out(u: User) -> UserOut:
    from ..services.lockout import is_locked
    return UserOut(id=u.id, username=u.username, role=u.role, role_id=u.role_id,
                   employee_id=u.employee_id, is_active=u.is_active,
                   must_change_password=bool(u.must_change_password),
                   locked=is_locked(u), password_changed_at=u.password_changed_at)


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _=Depends(require("user:manage"))):
    return [_out(u) for u in db.scalars(select(User).order_by(User.username)).all()]


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db), _=Depends(require("user:manage"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    return _out(u)


@router.post("", response_model=UserCreatedOut, status_code=201)
def create_user(body: CreateUserIn, db: Session = Depends(get_db),
                actor=Depends(require("user:manage"))):
    key = validate_username(body.username)
    role = get_role(db, body.role)
    if db.scalar(select(User).where(User.username_key == key)):
        raise HTTPException(409, "Username already exists (usernames are case-insensitive)")

    employee = None
    if body.employee_id is not None:
        employee = db.get(Employee, body.employee_id)
        if not employee:
            raise HTTPException(404, "Employee not found")
        if employee.user_id or db.scalar(
                select(User.id).where(User.employee_id == employee.id)):
            raise HTTPException(409, "That employee already has a login")

    password = body.password or generate_temp_password()
    try:
        validate_password(password, key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    user = User(username=body.username.strip(), username_key=key,
                role=role.name, role_id=role.id, employee_id=employee.id if employee else None,
                password_hash=hash_password(password), must_change_password=True)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username already exists")
    if employee:
        employee.user_id = user.id
    audit(db, actor.id, "user.create", f"user:{user.id}",
          {"username": user.username, "role": role.name,
           "employee_id": employee.id if employee else None})
    db.commit()
    return UserCreatedOut(**_out(user).model_dump(), temporary_password=password)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UpdateUserIn, db: Session = Depends(get_db),
                actor=Depends(require("user:manage"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    changes: dict = {}

    if body.role is not None:
        if u.id == actor.id:
            raise HTTPException(403, "You cannot change your own role")
        role = get_role(db, body.role)
        had_admin = "user:manage" in (u.role_rel.permissions if u.role_rel else [])
        if role.name != u.role or role.id != u.role_id:
            changes["role"] = {"old": u.role, "new": role.name}
            guard_last_admin(db, u, losing_admin=had_admin and "user:manage" not in role.permissions)
            u.role, u.role_id = role.name, role.id
            # A role change can add the Administrator role, which requires the
            # authenticator. End the old session so the next sign-in passes the
            # policy that now applies, instead of carrying the old factor set.
            u.token_version = (u.token_version or 1) + 1

    if body.is_active is not None and body.is_active != u.is_active:
        if u.id == actor.id and not body.is_active:
            raise HTTPException(403, "You cannot deactivate your own account")
        guard_last_admin(db, u, losing_admin=u.is_active and not body.is_active)
        u.is_active = body.is_active
        changes["is_active"] = body.is_active
        if not body.is_active:
            u.token_version = (u.token_version or 1) + 1      # revoke every open session
            u.failed_attempts, u.locked_until = 0, None

    if body.employee_id is not None or "employee_id" in body.model_fields_set:
        if body.employee_id is None:
            if u.employee_id:
                emp = db.get(Employee, u.employee_id)
                if emp:
                    emp.user_id = None
                changes["employee_id"] = None
                u.employee_id = None
        else:
            emp = db.get(Employee, body.employee_id)
            if not emp:
                raise HTTPException(404, "Employee not found")
            if emp.user_id and emp.user_id != u.id:
                raise HTTPException(409, "That employee already has a login")
            if db.scalar(select(User.id).where(User.employee_id == emp.id, User.id != u.id)):
                raise HTTPException(409, "That employee already has a login")
            if u.employee_id and u.employee_id != emp.id:
                old = db.get(Employee, u.employee_id)
                if old:
                    old.user_id = None
            emp.user_id = u.id
            u.employee_id = emp.id
            changes["employee_id"] = emp.id

    if changes:
        audit(db, actor.id, "user.update", f"user:{u.id}", changes)
    db.commit()
    return _out(u)


@router.post("/{user_id}/reset-password", response_model=UserCreatedOut)
def reset_password(user_id: int, db: Session = Depends(get_db),
                   actor=Depends(require("user:manage"))):
    """Administrator reset: a new temporary password is shown once, the account
    must change it at first login, and every existing session is revoked."""
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == actor.id:
        raise HTTPException(403, "Use Change password to change your own password")

    password = generate_temp_password()
    u.password_hash = hash_password(password)
    u.must_change_password = True
    u.password_changed_at = datetime.now(timezone.utc)
    u.token_version = (u.token_version or 1) + 1
    u.failed_attempts, u.locked_until = 0, None      # a reset also clears a lockout
    audit(db, actor.id, "user.reset_password", f"user:{u.id}", {"username": u.username})
    db.commit()
    return UserCreatedOut(**_out(u).model_dump(), temporary_password=password)
