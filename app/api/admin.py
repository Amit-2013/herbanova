"""Admin-only secrets used by the guarded database reset.

Two separate secrets exist and neither is the daily login password:

* the **secondary password** (older recovery provisioning helper), and
* the **reset key**, which is the final confirmation in step 4 of the reset.

Both are hashed with argon2 and never returned by the API. The reset key is
refused if it equals the login or secondary password, so "the second secret"
cannot silently be the first one.

These endpoints are reachable at:

* ``POST /api/admin/secondary-password`` — set or replace the secondary password
  (admin only, ``user:manage``).
* ``POST /api/admin/reset-key`` — set or replace the reset key.

They are intentionally plain and unglamorous: this is a recovery tool, not a
feature.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.rbac import require, require_admin
from app.core.security import (hash_secondary_password, verify_password,
                               verify_secondary_password)
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


class SetResetKeyRequest(BaseModel):
    reset_key: str = Field(min_length=16)
    # Re-proving the login password means a borrowed session cannot quietly
    # replace the second secret and then run a reset with it.
    current_password: str = Field(min_length=1)


@router.post("/api/admin/reset-key", status_code=status.HTTP_204_NO_CONTENT)
def set_reset_key(
    req: SetResetKeyRequest,
    db: Session = Depends(get_db),
    actor=Depends(require_admin("user:manage")),
):
    """Store the final-confirmation secret for the guarded database reset.

    It must differ from both the login password and the secondary password, so a
    single compromised secret cannot carry an operator through every step.
    """
    admin = db.get(User, actor.id)
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=403, detail="The acting administrator is not active.")
    if not verify_password(req.current_password, admin.password_hash):
        raise HTTPException(status_code=403,
                            detail="The current login password is incorrect.")

    if verify_password(req.reset_key, admin.password_hash):
        raise HTTPException(status_code=422,
                            detail="The reset key must differ from the login password.")
    if verify_secondary_password(admin.reset_password_secondary_hash, req.reset_key):
        raise HTTPException(status_code=422,
                            detail="The reset key must differ from the secondary password.")

    admin.reset_key_hash = hash_secondary_password(req.reset_key)
    admin.reset_key_set_at = datetime.now(timezone.utc)
    db.add(admin)
    audit(db, actor.id, "admin.reset_key_set", f"admin {admin.username}", {
        "reset_key_set": True,
    })
    db.commit()
