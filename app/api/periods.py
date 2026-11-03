"""Financial-year close (GAP-A03).

Closing a year is a gateway, not a posting: the year's documents stop being
changeable, and a dated document inside it is refused with 423 until the year
is reopened. Closing needs `accounts:write`; reopening needs the Administrator,
the same rule as unlocking an accounting month. Both write an audit entry with
the reason, and the reopen trail stays on the row.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require, require_admin
from ..models.core import User
from ..services import periods
from ..services.audit import audit

router = APIRouter(prefix="/api/accounts/financial-years", tags=["financial-years"])


class ReasonIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


def _users(db: Session) -> dict:
    return {u.id: u for u in db.scalars(select(User)).all()}


def _out(row, users: dict, action: str) -> dict:
    return {"financial_year": row.financial_year,
            **periods.close_out(row, users), "action": action}


@router.get("")
def list_financial_years(db: Session = Depends(get_db),
                         _=Depends(require("accounts:read"))):
    return periods.year_rows(db, _users(db))


@router.post("/{label}/close", status_code=201)
def close_financial_year(label: str, body: ReasonIn, db: Session = Depends(get_db),
                         user=Depends(require("accounts:write"))):
    try:
        row = periods.close_year(db, label, body.reason, user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    audit(db, user.id, "accounts.financial_year.close", f"financial_year:{row.financial_year}",
          {"financial_year": row.financial_year, "reason": row.reason})
    db.commit()
    return _out(row, _users(db), "closed")


@router.post("/{label}/reopen")
def reopen_financial_year(label: str, body: ReasonIn, db: Session = Depends(get_db),
                          user=Depends(require_admin("accounts:write"))):
    try:
        row = periods.reopen_year(db, label, body.reason, user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    audit(db, user.id, "accounts.financial_year.reopen", f"financial_year:{row.financial_year}",
          {"financial_year": row.financial_year, "reason": row.reopen_reason})
    db.commit()
    return _out(row, _users(db), "reopened")
