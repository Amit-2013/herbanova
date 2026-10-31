"""Discount slabs (FR-13): the policy is data, the approval rule is code.

A slab applies when the order date is inside its window, its scope matches
(all products, one product, or one distributor group) and the quantity or value
is inside the band. Several slabs can match one order; the highest discount
wins, and a tie goes to the narrower scope and then to the later start date, so
the answer never depends on insertion order.

`approval_needed` answers the question the sales flow asks: does this discount
need a second person? A slab's own `approval_above` wins; with no slab the
baseline rule in `app/core/rules.py` applies.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.rules import DISCOUNT_APPROVAL_PCT
from ..models.tax import DiscountSlab

SCOPE_WEIGHT = {"product": 3, "group": 2, "all": 1}


def _in_band(value, low, high) -> bool:
    if value is None:
        return low is None and high is None
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True


def applicable_slabs(db: Session, *, on: date, product_id: int | None = None,
                     group_name: str | None = None, qty: Decimal | None = None,
                     value: Decimal | None = None) -> list[DiscountSlab]:
    rows = db.scalars(
        select(DiscountSlab)
        .where(DiscountSlab.is_active.is_(True),
               DiscountSlab.effective_from <= on,
               or_(DiscountSlab.effective_to.is_(None), DiscountSlab.effective_to >= on))
        .order_by(DiscountSlab.id)).all()
    out = []
    for slab in rows:
        if slab.scope == "product" and slab.product_id != product_id:
            continue
        if slab.scope == "group" and (slab.group_name or "").lower() != (group_name or "").lower():
            continue
        # a band set on quantity must contain the quantity, likewise for value
        if slab.min_qty is not None or slab.max_qty is not None:
            if not _in_band(qty, slab.min_qty, slab.max_qty):
                continue
        if slab.min_value is not None or slab.max_value is not None:
            if not _in_band(value, slab.min_value, slab.max_value):
                continue
        out.append(slab)
    return out


def best_slab(db: Session, **kwargs) -> DiscountSlab | None:
    candidates = applicable_slabs(db, **kwargs)
    if not candidates:
        return None
    return sorted(candidates, key=lambda s: (Decimal(s.discount_percent),
                                            SCOPE_WEIGHT.get(s.scope, 0),
                                            s.effective_from))[-1]


def discount_for(db: Session, **kwargs) -> tuple[Decimal, DiscountSlab | None]:
    slab = best_slab(db, **kwargs)
    return (Decimal(slab.discount_percent) if slab else Decimal(0)), slab


def approval_needed(discount_percent: Decimal, slab: DiscountSlab | None = None) -> bool:
    """A discount above the slab's threshold (or the baseline 10%) needs approval."""
    threshold = (Decimal(slab.approval_above) if slab is not None and slab.approval_above is not None
                 else Decimal(DISCOUNT_APPROVAL_PCT))
    return Decimal(discount_percent) > threshold


def overlaps(db: Session, slab: DiscountSlab, start: date, end: date | None) -> DiscountSlab | None:
    """Another slab with the same scope target and an overlapping window.

    Two slabs may coexist when they cover different bands; identical scope and
    overlapping dates are refused because the "best" answer would become
    ambiguous.
    """
    conds = [DiscountSlab.scope == slab.scope,
             DiscountSlab.min_qty == slab.min_qty, DiscountSlab.max_qty == slab.max_qty,
             DiscountSlab.min_value == slab.min_value, DiscountSlab.max_value == slab.max_value,
             DiscountSlab.effective_from <= (end or date.max),
             or_(DiscountSlab.effective_to.is_(None), DiscountSlab.effective_to >= start)]
    if slab.scope == "product":
        conds.append(DiscountSlab.product_id == slab.product_id)
    if slab.scope == "group":
        conds.append(DiscountSlab.group_name == slab.group_name)
    q = select(DiscountSlab).where(*conds)
    if slab.id:
        q = q.where(DiscountSlab.id != slab.id)
    return db.scalars(q).first()
