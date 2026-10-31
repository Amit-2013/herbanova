"""Read-only stock views (batches, ledger) plus warehouse master data.

Stock itself only ever changes through services.inventory.post_movement
(goods receipt today), so nothing here writes to batches or movements.
"""
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require
from ..models.core import (Batch, Product, PurchaseOrder, StockMovement, User,
                           Warehouse)
from ..models.suppliers import GoodsReceipt
from ..services import capacity
from ..services.audit import audit

router = APIRouter(prefix="/api", tags=["inventory"])


def _clean_note(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


class WarehouseIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    capacity_units: int | None = Field(default=None, ge=0)
    capacity_note: str | None = Field(default=None, max_length=40)

    @field_validator("name")
    @classmethod
    def strip(cls, v): return v.strip()

    @field_validator("capacity_note")
    @classmethod
    def strip_note(cls, v): return _clean_note(v)


class CapacityIn(BaseModel):
    capacity_units: int | None = Field(default=None, ge=0)
    capacity_note: str | None = Field(default=None, max_length=40)

    @field_validator("capacity_note")
    @classmethod
    def strip_note(cls, v): return _clean_note(v)


class WarehouseOut(BaseModel):
    id: int
    name: str
    capacity_units: int | None = None
    capacity_note: str | None = None
    used_units: Decimal = Decimal(0)
    free_units: Decimal | None = None
    utilisation_pct: float | None = None
    capacity_state: str = "not_configured"
    batches: int = 0


class BatchOut(BaseModel):
    id: int
    product_id: int
    sku: str
    product_name: str
    pack_size: str
    warehouse_id: int
    warehouse: str
    batch_no: str
    expiry: date | None
    owner: str
    on_hand: Decimal


class MovementOut(BaseModel):
    id: int
    created_at: datetime | None
    movement_type: str
    qty_delta: Decimal
    sku: str
    product_name: str
    batch_no: str
    warehouse: str
    ref_type: str
    ref_id: str
    ref_label: str      # human reference, e.g. the PO number for ref_type 'po'
    actor: str


@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(db: Session = Depends(get_db), _=Depends(require("stock:read"))):
    return capacity.warehouse_positions(db)


@router.post("/warehouses", response_model=WarehouseOut, status_code=201)
def create_warehouse(body: WarehouseIn, db: Session = Depends(get_db),
                     user=Depends(require("stock:write"))):
    exists = db.scalar(select(Warehouse).where(Warehouse.name.ilike(body.name)))
    if exists:
        raise HTTPException(409, "Warehouse name already exists")
    w = Warehouse(name=body.name, capacity_units=body.capacity_units,
                  capacity_note=body.capacity_note)
    db.add(w)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Warehouse name already exists")
    audit(db, user.id, "warehouse.create", f"warehouse:{w.id}",
          {"name": w.name, "capacity_units": w.capacity_units,
           "capacity_note": w.capacity_note})
    db.commit()
    return capacity.warehouse_position(db, w.id)


@router.put("/warehouses/{warehouse_id}/capacity", response_model=WarehouseOut)
def set_capacity(warehouse_id: int, body: CapacityIn, db: Session = Depends(get_db),
                 user=Depends(require("stock:write"))):
    """Set or clear a warehouse's capacity. Clearing is explicit and audited."""
    w = db.get(Warehouse, warehouse_id)
    if not w:
        raise HTTPException(404, "Warehouse not found")
    before = {"capacity_units": w.capacity_units, "capacity_note": w.capacity_note}
    w.capacity_units, w.capacity_note = body.capacity_units, body.capacity_note
    audit(db, user.id, "warehouse.capacity", f"warehouse:{w.id}",
          {"name": w.name, "from": before,
           "to": {"capacity_units": w.capacity_units, "capacity_note": w.capacity_note}})
    db.commit()
    return capacity.warehouse_position(db, w.id)


@router.get("/inventory/batches", response_model=list[BatchOut])
def list_batches(warehouse_id: int | None = None, product_id: int | None = None,
                 in_stock_only: bool = False, db: Session = Depends(get_db),
                 _=Depends(require("stock:read"))):
    q = (select(Batch, Product, Warehouse)
         .join(Product, Product.id == Batch.product_id)
         .join(Warehouse, Warehouse.id == Batch.warehouse_id))
    if warehouse_id is not None:
        q = q.where(Batch.warehouse_id == warehouse_id)
    if product_id is not None:
        q = q.where(Batch.product_id == product_id)
    if in_stock_only:
        q = q.where(Batch.on_hand > 0)
    # first-expiry-first-out order; batches without an expiry date go last
    q = q.order_by(Batch.expiry.asc().nulls_last(), Product.sku, Batch.batch_no)
    return [BatchOut(id=b.id, product_id=p.id, sku=p.sku, product_name=p.name,
                     pack_size=p.pack_size, warehouse_id=w.id, warehouse=w.name,
                     batch_no=b.batch_no, expiry=b.expiry, owner=b.owner,
                     on_hand=b.on_hand)
            for b, p, w in db.execute(q).all()]


@router.get("/inventory/movements", response_model=list[MovementOut])
def list_movements(limit: int = Query(200, ge=1, le=500), batch_id: int | None = None,
                   db: Session = Depends(get_db), _=Depends(require("stock:read"))):
    q = (select(StockMovement, Batch, Product, Warehouse, User)
         .join(Batch, Batch.id == StockMovement.batch_id)
         .join(Product, Product.id == Batch.product_id)
         .join(Warehouse, Warehouse.id == Batch.warehouse_id)
         .join(User, User.id == StockMovement.actor_id))
    if batch_id is not None:
        q = q.where(StockMovement.batch_id == batch_id)
    rows = db.execute(q.order_by(StockMovement.id.desc()).limit(limit)).all()

    po_ids = {int(m.ref_id) for m, *_ in rows if m.ref_type == "po" and m.ref_id.isdigit()}
    po_numbers = {}
    if po_ids:
        po_numbers = {po.id: po.po_number for po in
                      db.scalars(select(PurchaseOrder).where(PurchaseOrder.id.in_(po_ids))).all()}
    grn_ids = {int(m.ref_id) for m, *_ in rows if m.ref_type == "grn" and m.ref_id.isdigit()}
    grn_numbers = {}
    if grn_ids:
        grn_numbers = {g.id: g.grn_number for g in
                       db.scalars(select(GoodsReceipt).where(GoodsReceipt.id.in_(grn_ids))).all()}

    def label(m: StockMovement) -> str:
        if m.ref_type == "po" and m.ref_id.isdigit():
            return po_numbers.get(int(m.ref_id), f"PO {m.ref_id}")
        if m.ref_type == "grn" and m.ref_id.isdigit():
            return grn_numbers.get(int(m.ref_id), f"GRN {m.ref_id}")
        return f"{m.ref_type} {m.ref_id}"

    return [MovementOut(id=m.id, created_at=m.created_at, movement_type=m.movement_type,
                        qty_delta=m.qty_delta, sku=p.sku, product_name=p.name,
                        batch_no=b.batch_no, warehouse=w.name, ref_type=m.ref_type,
                        ref_id=m.ref_id, ref_label=label(m), actor=u.username)
            for m, b, p, w, u in rows]