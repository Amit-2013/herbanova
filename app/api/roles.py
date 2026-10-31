"""Role and permission management (FR-02, AUD-024).

Roles live in the database. The four system roles (admin, sales, inventory,
viewer) are seeded with the frozen baseline sets and keep their names; custom
roles (for example 'Accounts') are created here. Roles are never deleted -
users reference them - and a role edit cannot strip the last active
administrator of user:manage. Every change is audited, so the permission
change is traceable and takes effect on the next request.
"""
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.permissions import PERMISSIONS
from ..core.rbac import require
from ..models.core import User
from ..models.users import Role
from ..services.accounts import guard_last_admin, validate_permissions
from ..services.audit import audit

router = APIRouter(prefix="/api/roles", tags=["roles"])


class RoleOut(BaseModel):
    id: int
    name: str
    display_name: str
    is_system: bool
    permissions: list[str]
    user_count: int


class CreateRoleIn(BaseModel):
    name: str
    display_name: str | None = None
    permissions: list[str] = []

    @field_validator("name")
    @classmethod
    def norm(cls, v): return v.strip().lower()


class UpdateRoleIn(BaseModel):
    display_name: str | None = None
    permissions: list[str] | None = None


def _counts(db: Session) -> dict[int, int]:
    rows = db.execute(select(User.role_id, func.count())
                      .where(User.role_id.is_not(None))
                      .group_by(User.role_id)).all()
    return dict(rows)


def _out(r: Role, counts: dict[int, int]) -> RoleOut:
    return RoleOut(id=r.id, name=r.name, display_name=r.display_name,
                   is_system=r.is_system, permissions=sorted(r.permissions or []),
                   user_count=counts.get(r.id, 0))


@router.get("", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db), _=Depends(require("user:manage"))):
    counts = _counts(db)
    return [_out(r, counts) for r in db.scalars(select(Role).order_by(Role.name)).all()]


@router.get("/permissions")
def permission_catalog(_=Depends(require("user:manage"))):
    """The permission matrix source: every key, grouped by module."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for key, (desc, module) in sorted(PERMISSIONS.items()):
        grouped[module].append({"key": key, "description": desc})
    return [{"module": m, "items": items} for m, items in grouped.items()]


@router.post("", response_model=RoleOut, status_code=201)
def create_role(body: CreateRoleIn, db: Session = Depends(get_db),
                actor=Depends(require("user:manage"))):
    if len(body.name) < 3:
        raise HTTPException(422, "Role name must be at least 3 characters")
    perms = validate_permissions(body.permissions)
    role = Role(name=body.name, display_name=(body.display_name or body.name).strip(),
                is_system=False, permissions=perms)
    db.add(role)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A role with that name already exists")
    audit(db, actor.id, "role.create", f"role:{role.id}",
          {"name": role.name, "permissions": perms})
    db.commit()
    return _out(role, {})


@router.patch("/{role_id}", response_model=RoleOut)
def update_role(role_id: int, body: UpdateRoleIn, db: Session = Depends(get_db),
                actor=Depends(require("user:manage"))):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    changes: dict = {}

    if body.display_name is not None:
        role.display_name = body.display_name.strip()
        changes["display_name"] = role.display_name

    if body.permissions is not None:
        perms = validate_permissions(body.permissions)
        old = sorted(role.permissions or [])
        if perms != old:
            if "user:manage" in old and "user:manage" not in perms:
                admins = db.scalars(select(User).where(
                    User.is_active.is_(True), User.role_id == role.id)).all()
                for u in admins:
                    guard_last_admin(db, u, losing_admin=True)
            role.permissions = perms
            changes["permissions"] = {"added": sorted(set(perms) - set(old)),
                                      "removed": sorted(set(old) - set(perms))}

    if changes:
        audit(db, actor.id, "role.update", f"role:{role.id}",
              {"name": role.name, **changes})
    db.commit()
    return _out(role, _counts(db))
