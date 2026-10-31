"""Credit exposure and stock allocation helpers for sales orders."""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models.core import Batch, SalesOrder

# Orders that count against a distributor's credit limit. Pending orders count too,
# so several pending orders cannot be used to slip past the limit.
EXPOSURE_STATUSES = ("pending_approval", "approved", "dispatched")


def credit_exposure(db: Session, distributor_id: int, exclude_order_id: int | None = None,
                    statuses: tuple[str, ...] = EXPOSURE_STATUSES) -> Decimal:
    """Credit in use. Submit counts pending + approved + dispatched orders (commitments);
    dispatch counts only goods already delivered, so an exception approved for one order
    cannot block a different, in-limit order. Payments are not tracked yet."""
    q = select(func.coalesce(func.sum(SalesOrder.total), 0)).where(
        SalesOrder.distributor_id == distributor_id,
        SalesOrder.status.in_(statuses))
    if exclude_order_id is not None:
        q = q.where(SalesOrder.id != exclude_order_id)
    return Decimal(db.scalar(q))


def _eligible(product_id: int, warehouse_id: int | None):
    """Sellable batches: HERBANOVA-owned, in stock, not expired."""
    conds = [Batch.product_id == product_id, Batch.on_hand > 0, Batch.owner == "HERBANOVA",
             or_(Batch.expiry.is_(None), Batch.expiry > date.today())]
    if warehouse_id is not None:
        conds.append(Batch.warehouse_id == warehouse_id)
    return conds


def available_stock(db: Session, product_id: int, warehouse_id: int | None = None) -> Decimal:
    return Decimal(db.scalar(select(func.coalesce(func.sum(Batch.on_hand), 0))
                             .where(*_eligible(product_id, warehouse_id))))


def allocate_fefo(db: Session, product_id: int, qty: Decimal, warehouse_id: int):
    """Lock eligible batches and take stock first-expiry-first-out.
    Returns (allocations [(batch, take)], shortfall)."""
    batches = db.scalars(select(Batch).where(*_eligible(product_id, warehouse_id))
                         .order_by(Batch.expiry.asc().nulls_last(), Batch.id)
                         .with_for_update()).all()
    left, out = Decimal(qty), []
    for b in batches:
        if left <= 0:
            break
        take = min(b.on_hand, left)
        out.append((b, take))
        left -= take
    return out, max(left, Decimal(0))