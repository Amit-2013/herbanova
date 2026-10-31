"""Admin-only endpoints that control the admin secondary password.

The database-reset endpoint requires this secondary password, which is a separate
secret from the daily login password. The owner sets it once, then uses it every
time they reset the database. It is hashed with argon2 and never returned by the
API.

These endpoints are reachable at:

* ``POST /api/admin/secondary-password`` — set or replace the admin's secondary
  password (admin only, ``user:manage``).

They are intentionally plain and unglamorous: this is a recovery tool, not a
feature.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.rbac import require
from app.core.security import hash_secondary_password
from app.models.core import User
from app.services.audit import audit

router = APIRouter()


class SetSecondaryPasswordRequest(BaseModel):
    secondary_password: str = Field(min_length=8)


@router.post("/api/admin/secondary-password", status_code=status.HTTP_204_NO_CONTENT)
def set_secondary_password(
    req: SetSecondaryPasswordRequest,
    db: Session = Depends(get_db),
    actor=Depends(require("user:manage")),
):
    """An administrator's secondary password must come from a person who already
    holds ``user:manage``, because that is the group that can reset the database.
    """
    if not req.secondary_password.strip():
        raise HTTPException(
            status_code=422,
            detail="The secondary password must be at least 8 characters.",
        )

    admin = db.get(User, actor.id)
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=403, detail="The acting administrator is not active.")

    admin.reset_password_secondary_hash = hash_secondary_password(req.secondary_password)
    admin.secondary_set_at = datetime.now(timezone.utc)
    db.add(admin)

    audit(db, actor.id, "admin.secondary_password_set", f"admin {admin.username}", {
        "secondary_set": True,
    })
    db.commit()
