"""Warehouse capacity, calculated once for the API, dashboard and report.

A warehouse's capacity is optional. `None` means it has not been measured; it
never means zero, and no percentage is invented for it.
"""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.core import Batch, Warehouse


def _state(used: Decimal, capacity: int) -> str:
    if used > capacity:
        return "over"
    if capacity == 0 or used == capacity:
        return "full"
    if used > capacity * Decimal("0.8"):
        return "high"
    return "ok"


def position(used, capacity: int | None, note: str | None = None) -> dict:
    used = Decimal(used or 0)
    out = {
        "used_units": str(used),
        "capacity_units": capacity,
        "capacity_note": note,
        "free_units": None,
        "utilisation_pct": None,
        "capacity_state": "not_configured",
    }
    if capacity is None:
        return out
    free = Decimal(capacity) - used
    out["free_units"] = str(free)
    out["utilisation_pct"] = (round(float(used / Decimal(capacity) * 100), 1)
                              if capacity > 0 else (100.0 if used > 0 else 0.0))
    out["capacity_state"] = _state(used, capacity)
    return out


def warehouse_positions(db: Session) -> list[dict]:
    """Every warehouse with its measured usage, in one grouped query."""
    rows = db.execute(
        select(Warehouse.id, Warehouse.name, Warehouse.capacity_units,
               Warehouse.capacity_note,
               func.coalesce(func.sum(Batch.on_hand), 0),
               func.count().filter(Batch.on_hand > 0))
        .outerjoin(Batch, Batch.warehouse_id == Warehouse.id)
        .group_by(Warehouse.id, Warehouse.name, Warehouse.capacity_units,
                  Warehouse.capacity_note)
        .order_by(Warehouse.name)).all()
    out = []
    for wid, name, capacity, note, used, batches in rows:
        row = position(used, capacity, note)
        row.update({"id": wid, "name": name, "batches": int(batches)})
        out.append(row)
    return out


def warehouse_position(db: Session, warehouse_id: int) -> dict | None:
    wh = db.get(Warehouse, warehouse_id)
    if not wh:
        return None
    used = db.scalar(select(func.coalesce(func.sum(Batch.on_hand), 0))
                     .where(Batch.warehouse_id == warehouse_id))
    row = position(used, wh.capacity_units, wh.capacity_note)
    row.update({"id": wh.id, "name": wh.name})
    return row
