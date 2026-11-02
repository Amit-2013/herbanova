from datetime import datetime
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..models.core import Batch, StockMovement

def post_movement(db: Session, *, batch_id: int, qty_delta: Decimal, movement_type: str,
                  ref_type: str, ref_id: str, actor_id: int,
                  unit_cost: Decimal | None = None, cost_source: str | None = None,
                  invoice_id: int | None = None,
                  created_at: datetime | None = None) -> StockMovement:
    """Row-lock the batch, reject negative stock, write ledger row + update balance atomically.
    Duplicate (batch, type, ref) is rejected by the unique constraint.

    Cost is optional and captured at write time; NULL means "not known", never
    zero. Callers that know the cost pass it (purchase rate, weighted average,
    return cost) so a report does not have to reconstruct history."""
    qty_delta = Decimal(qty_delta)
    if qty_delta == 0:
        raise HTTPException(422, "Quantity must be non-zero")
    batch = db.execute(select(Batch).where(Batch.id == batch_id).with_for_update()).scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Batch not found")
    if batch.on_hand + qty_delta < 0:
        raise HTTPException(409, "Insufficient stock")
    mv = StockMovement(batch_id=batch_id, movement_type=movement_type, qty_delta=qty_delta,
                       ref_type=ref_type, ref_id=ref_id, actor_id=actor_id,
                       unit_cost=unit_cost, cost_source=cost_source,
                       invoice_id=invoice_id)
    if created_at is not None:
        mv.created_at = created_at
    batch.on_hand += qty_delta
    db.add(mv)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate posting rejected")
    return mv
