"""Audited cost corrections for a late purchase rate.

Only the Administrator's accounting permission may run a correction. The
quantity ledger is untouched: the purchase rate and the captured costs on that
product's movements are replaced, the product is replayed, and the before/after
cost of goods is stored and audited.

An accounting month can be locked through the same period-lock table HR uses
(scope `accounting`). A correction that would move cost of goods in a locked
month is refused before anything is written; only the Administrator can unlock.
"""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require, require_admin
from ..models.core import PurchaseOrderLine, User
from ..models.hr import PeriodLock
from ..services import costing
from ..services.audit import audit

router = APIRouter(prefix="/api/accounts/costs", tags=["costs"])
lock_router = APIRouter(prefix="/api/accounts/period-locks", tags=["period-locks"])


class CorrectionIn(BaseModel):
    po_line_id: int
    new_unit_cost: Decimal = Field(ge=0)
    reason: str = Field(min_length=3, max_length=300)


class LockIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    reason: str = Field(min_length=5, max_length=300)


class UnlockIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


def _text(value):
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01")))
    if isinstance(value, list):
        return [_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _text(item) for key, item in value.items()}
    return value


@router.post("/correction")
def correct_cost(body: CorrectionIn, db: Session = Depends(get_db),
                 user=Depends(require("accounts:write"))):
    line = db.get(PurchaseOrderLine, body.po_line_id)
    if line is None:
        raise HTTPException(404, "Purchase order line not found")
    try:
        result = costing.correct_po_cost(
            db, po_line_id=line.id, new_unit_cost=body.new_unit_cost,
            reason=body.reason, actor_id=user.id)
    except costing.LockedPeriodError as exc:
        raise HTTPException(423, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit(db, user.id, "accounts.cost_correction",
          f"purchase_order_line:{line.id}",
          {"po_number": result["po_number"], "sku": result["sku"],
           "old_rate": _text(result["old_po_rate"]),
           "new_rate": _text(result["new_po_rate"]),
           "movements_changed": result["movements_changed"],
           "before_total": _text(result["before_total"]),
           "after_total": _text(result["after_total"]),
           "reason": body.reason.strip()})
    db.commit()
    return _text(result)


# ------------------------------------------------------- accounting period locks
def _lock_out(lock: PeriodLock, users: dict) -> dict:
    def who(user_id):
        user = users.get(user_id) if user_id else None
        return user.username if user else user_id

    return {"id": lock.id, "scope": lock.scope, "year": lock.year,
            "month": lock.month, "active": lock.active, "reason": lock.reason,
            "locked_by": who(lock.locked_by), "locked_at": lock.locked_at,
            "unlocked_by": who(lock.unlocked_by),
            "unlocked_at": lock.unlocked_at, "unlock_reason": lock.unlock_reason}


@lock_router.get("")
def list_accounting_locks(year: int | None = None, db: Session = Depends(get_db),
                          _=Depends(require("accounts:read"))):
    stmt = select(PeriodLock).where(PeriodLock.scope == "accounting")
    if year:
        stmt = stmt.where(PeriodLock.year == year)
    locks = db.scalars(stmt.order_by(PeriodLock.year.desc(),
                                     PeriodLock.month.desc())).all()
    users = {u.id: u for u in db.scalars(select(User)).all()}
    return [_lock_out(lock, users) for lock in locks]


@lock_router.post("", status_code=201)
def lock_accounting_period(body: LockIn, db: Session = Depends(get_db),
                           user=Depends(require("accounts:write"))):
    lock = db.scalar(select(PeriodLock).where(
        PeriodLock.scope == "accounting", PeriodLock.year == body.year,
        PeriodLock.month == body.month).with_for_update())
    if lock and lock.active:
        raise HTTPException(409, f"That accounting month is already locked")
    reason = body.reason.strip()
    if lock:
        lock.active = True
        lock.locked_by = user.id
        lock.locked_at = datetime.now(timezone.utc)
        lock.reason = reason
        lock.unlocked_by = lock.unlocked_at = lock.unlock_reason = None
    else:
        lock = PeriodLock(scope="accounting", year=body.year, month=body.month,
                          active=True, locked_by=user.id, reason=reason)
        db.add(lock)
    db.flush()
    audit(db, user.id, "accounts.period_lock.lock", f"period_lock:{lock.id}",
          {"year": lock.year, "month": lock.month, "reason": reason})
    db.commit()
    users = {u.id: u for u in db.scalars(select(User)).all()}
    return _lock_out(lock, users)


@lock_router.post("/{lock_id}/unlock")
def unlock_accounting_period(lock_id: int, body: UnlockIn,
                             db: Session = Depends(get_db),
                             user=Depends(require_admin("accounts:write"))):
    lock = db.get(PeriodLock, lock_id, with_for_update=True)
    if lock is None or lock.scope != "accounting":
        raise HTTPException(404, "Accounting period lock not found")
    if not lock.active:
        raise HTTPException(409, "That accounting month is not locked")
    lock.active = False
    lock.unlocked_by = user.id
    lock.unlocked_at = datetime.now(timezone.utc)
    lock.unlock_reason = body.reason.strip()
    audit(db, user.id, "accounts.period_lock.unlock", f"period_lock:{lock.id}",
          {"year": lock.year, "month": lock.month, "reason": lock.unlock_reason})
    db.commit()
    users = {u.id: u for u in db.scalars(select(User)).all()}
    return _lock_out(lock, users)
