"""Central feature availability, managed by the Administrator (Roles & Permissions).

This is the only place a module is switched on or off. The Overview screen shows
module status read-only; it carries no controls of its own.

Only the Administrator role may read or change the switches, whatever
`user:manage` a custom role might carry: switching a module off affects every
user at once, so it is a system-level decision.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.features import FEATURE_BY_KEY
from ..core.rbac import require_admin
from ..services.audit import audit
from ..services.feature_store import feature_rows, set_flag

router = APIRouter(prefix="/api/features", tags=["features"])


class FeatureToggle(BaseModel):
    enabled: bool


def _row(db: Session, key: str) -> dict:
    for row in feature_rows(db):
        if row["key"] == key:
            return row
    raise HTTPException(404, "Unknown feature")


@router.get("")
def list_features(db: Session = Depends(get_db),
                  _=Depends(require_admin("user:manage"))):
    """Every module switch with its state and the permissions it owns."""
    return feature_rows(db)


@router.patch("/{key}")
def update_feature(key: str, body: FeatureToggle, db: Session = Depends(get_db),
                   actor=Depends(require_admin("user:manage"))):
    feature = FEATURE_BY_KEY.get(key)
    if feature is None:
        raise HTTPException(404, "Unknown feature")
    if feature.locked and not body.enabled:
        raise HTTPException(409, f"{feature.label} cannot be switched off: it is how the "
                                 "Administrator switches the other modules back on")
    set_flag(db, key, body.enabled, actor.id)
    audit(db, actor.id, "feature.update", f"feature:{key}",
          {"label": feature.label, "enabled": body.enabled})
    db.commit()
    return _row(db, key)
