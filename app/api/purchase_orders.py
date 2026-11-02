"""Purchase orders and goods receipts (FR-05, AUD-048, decisions D8/D9).

Module Phase 2:
- a purchase order links to a Supplier record (legacy free-text orders were
  migrated to flagged supplier records);
- goods arrive through Goods Receipt Notes, so a purchase order can be
  received in parts. Each receipt posts its own ledger movements keyed to the
  receipt, exactly once;
- a client may quote the supplier's delivery-note number, unique per order,
  which blocks an accidental duplicate receipt even when the quantities would
  still fit;
- over-receipt is refused against the cumulative received quantity;
- the receipt chooses who owns the stock (HERBANOVA or the manufacturer, D9);
- an order can be cancelled before any goods arrive; the order closes itself
  when every line is fully received.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.pagination import page_params, paginate
from ..core.rbac import is_admin, require
from ..core.rules import PO_RATE_REMARKS
from ..models.core import (Batch, Product, PurchaseOrder, PurchaseOrderLine, Warehouse)
from ..models.suppliers import GoodsReceipt, GoodsReceiptLine, Supplier
from ..services.audit import audit
from ..services.inventory import post_movement

router = APIRouter(prefix="/api/purchase-orders", tags=["purchase-orders"])

OPEN_STATUSES = ("open", "partially_received")


class POLineIn(BaseModel):
    sku: str = Field(min_length=3, max_length=40)
    qty: Decimal = Field(gt=0)
    # A line can leave the cost blank, but then it must say why.
    unit_cost: Decimal | None = Field(default=None, ge=0)
    rate_remark: str | None = Field(default=None, max_length=30)

    @field_validator("sku")
    @classmethod
    def norm(cls, v): return v.strip().upper()

    @field_validator("rate_remark")
    @classmethod
    def known_remark(cls, v):
        if v is None or not str(v).strip():
            return None
        text = " ".join(str(v).split())
        key = text.lower()
        if key in PO_RATE_REMARKS:
            return key
        # Accept the display label too, so a client can post what the dropdown shows.
        for code, label in PO_RATE_REMARKS.items():
            if text.casefold() == label.casefold():
                return code
        raise ValueError("unknown rate remark")

    @model_validator(mode="after")
    def cost_or_remark(self):
        if self.unit_cost is None and not self.rate_remark:
            raise ValueError("enter a unit cost or choose a remark")
        return self


class POIn(BaseModel):
    supplier_id: int
    po_number: str | None = Field(default=None, min_length=3, max_length=40)
    lines: list[POLineIn] = Field(min_length=1)

    @field_validator("lines")
    @classmethod
    def unique_skus(cls, v):
        skus = [ln.sku for ln in v]
        if len(set(skus)) != len(skus):
            raise ValueError("duplicate SKU in lines")
        return v


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class POLineOut(BaseModel):
    id: int
    product_id: int
    sku: str
    qty: Decimal
    unit_cost: Decimal | None
    rate_remark: str | None = None
    rate_remark_label: str | None = None
    received_qty: Decimal = Decimal(0)


class ReceiptLineOut(BaseModel):
    sku: str
    batch_no: str
    qty: Decimal


class ReceiptOut(BaseModel):
    id: int
    grn_number: str
    received_at: datetime | None
    owner: str
    delivery_note: str | None = None
    note: str | None = None
    lines: list[ReceiptLineOut]


class POOut(BaseModel):
    id: int
    po_number: str
    supplier_id: int | None
    supplier: str
    supplier_code: str | None = None
    status: str
    cancel_reason: str | None = None
    created_at: datetime | None = None
    lines: list[POLineOut]
    receipts: list[ReceiptOut] = []


class ReceiveLineIn(BaseModel):
    sku: str = Field(min_length=3, max_length=40)
    batch_no: str = Field(min_length=1, max_length=40)
    qty: Decimal = Field(gt=0)
    expiry: date | None = None

    @field_validator("sku")
    @classmethod
    def norm(cls, v): return v.strip().upper()


class ReceiveIn(BaseModel):
    warehouse_id: int
    owner: Literal["HERBANOVA", "MANUFACTURER"] = "HERBANOVA"
    delivery_note: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=300)
    # Only an Administrator may accept a receipt that takes a measured
    # warehouse over its capacity; the override is audited.
    allow_over_capacity: bool = False
    lines: list[ReceiveLineIn] = Field(min_length=1)

    @field_validator("lines")
    @classmethod
    def unique_batches(cls, v):
        keys = [(ln.sku, ln.batch_no.strip().upper()) for ln in v]
        if len(set(keys)) != len(keys):
            raise ValueError("the same SKU and batch appear more than once in this receipt")
        return v

    @field_validator("delivery_note")
    @classmethod
    def strip_note(cls, v):
        return v.strip() if isinstance(v, str) and v.strip() else None


class ReceivedLine(BaseModel):
    sku: str
    batch_no: str
    qty: Decimal
    batch_on_hand: Decimal


class ReceiveOut(BaseModel):
    po_number: str
    status: str
    grn_number: str
    owner: str
    received: list[ReceivedLine]
    remaining: dict[str, Decimal]


def _sku_map(db: Session, skus: list[str]) -> dict[str, Product]:
    rows = db.scalars(select(Product).where(Product.sku.in_(skus))).all()
    return {p.sku: p for p in rows}


def _received_by_product(db: Session, po_id: int) -> dict[int, Decimal]:
    rows = db.execute(
        select(GoodsReceiptLine.product_id, func.coalesce(func.sum(GoodsReceiptLine.qty), 0))
        .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.grn_id)
        .where(GoodsReceipt.po_id == po_id)
        .group_by(GoodsReceiptLine.product_id)).all()
    return {pid: Decimal(qty) for pid, qty in rows}


def _receipts_by_po(db: Session, po_ids: list[int], sku_by_id: dict[int, str]) -> dict[int, list[ReceiptOut]]:
    """Every goods receipt note for these orders, loaded in two queries (no N+1)."""
    if not po_ids:
        return {}
    grns = db.scalars(select(GoodsReceipt).where(GoodsReceipt.po_id.in_(po_ids))
                      .order_by(GoodsReceipt.id)).all()
    batch_ids = {ln.batch_id for g in grns for ln in g.lines}
    batches = {b.id: b for b in db.scalars(select(Batch).where(Batch.id.in_(batch_ids))).all()} if batch_ids else {}
    out: dict[int, list[ReceiptOut]] = {po_id: [] for po_id in po_ids}
    for g in grns:
        out.setdefault(g.po_id, []).append(ReceiptOut(
            id=g.id, grn_number=g.grn_number, received_at=g.received_at, owner=g.owner,
            delivery_note=g.delivery_note, note=g.note,
            lines=[ReceiptLineOut(sku=sku_by_id.get(ln.product_id, "?"),
                                  batch_no=batches[ln.batch_id].batch_no if ln.batch_id in batches else "?",
                                  qty=ln.qty) for ln in g.lines]))
    return out


def _receipts(db: Session, po_id: int, sku_by_id: dict[int, str]) -> list[ReceiptOut]:
    return _receipts_by_po(db, [po_id], sku_by_id).get(po_id, [])


def _po_out(po: PurchaseOrder, sku_by_id: dict[int, str], received: dict[int, Decimal],
            receipts: list[ReceiptOut] | None = None, supplier_code: str | None = None) -> POOut:
    return POOut(
        id=po.id, po_number=po.po_number, supplier_id=po.supplier_id, supplier=po.supplier,
        supplier_code=supplier_code, status=po.status, cancel_reason=po.cancel_reason,
        created_at=po.created_at,
        lines=[POLineOut(id=ln.id, product_id=ln.product_id,
                         sku=sku_by_id.get(ln.product_id, ""), qty=ln.qty,
                         unit_cost=ln.unit_cost, rate_remark=ln.rate_remark,
                         rate_remark_label=PO_RATE_REMARKS.get(ln.rate_remark) if ln.rate_remark else None,
                         received_qty=received.get(ln.product_id, Decimal(0)))
               for ln in po.lines],
        receipts=receipts or [])


def _sku_by_id(db: Session) -> dict[int, str]:
    return {p.id: p.sku for p in db.scalars(select(Product)).all()}


def _supplier_codes(db: Session) -> dict[int, str]:
    return {s.id: s.code for s in db.scalars(select(Supplier)).all()}


@router.get("", response_model=list[POOut])
def list_pos(response: Response, supplier_id: int | None = None, status: str | None = None,
             paging=Depends(page_params), db: Session = Depends(get_db),
             _=Depends(require("stock:read"))):
    page, page_size = paging
    sku_by_id, codes = _sku_by_id(db), _supplier_codes(db)
    stmt = select(PurchaseOrder)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    pos = paginate(db, stmt.order_by(PurchaseOrder.id.desc()), response, page, page_size)
    receipts = _receipts_by_po(db, [po.id for po in pos], sku_by_id)
    received: dict[int, dict[int, Decimal]] = {}
    for po in pos:
        received[po.id] = _received_by_product(db, po.id)
    return [_po_out(po, sku_by_id, received[po.id], receipts.get(po.id, []),
                    supplier_code=codes.get(po.supplier_id)) for po in pos]


@router.get("/{po_id}", response_model=POOut)
def get_po(po_id: int, db: Session = Depends(get_db), _=Depends(require("stock:read"))):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    sku_by_id = _sku_by_id(db)
    codes = _supplier_codes(db)
    return _po_out(po, sku_by_id, _received_by_product(db, po.id),
                   _receipts(db, po.id, sku_by_id), codes.get(po.supplier_id))


@router.post("", response_model=POOut, status_code=201)
def create_po(body: POIn, db: Session = Depends(get_db), user=Depends(require("stock:write"))):
    supplier = db.get(Supplier, body.supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    if supplier.status == "blocked":
        raise HTTPException(409, "This supplier is blocked; unblock it before raising an order")
    pmap = _sku_map(db, [ln.sku for ln in body.lines])
    unknown = [ln.sku for ln in body.lines if ln.sku not in pmap]
    if unknown:
        raise HTTPException(422, f"Unknown SKU(s): {', '.join(sorted(unknown))}")

    po = PurchaseOrder(
        po_number=body.po_number or f"PO-{datetime.now():%Y%m%d}-{uuid4().hex[:6].upper()}",
        supplier=supplier.name, supplier_id=supplier.id, created_by=user.id,
        lines=[PurchaseOrderLine(product_id=pmap[ln.sku].id, qty=ln.qty,
                                 unit_cost=ln.unit_cost, rate_remark=ln.rate_remark)
               for ln in body.lines],
    )
    db.add(po)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "PO number already exists")
    audit(db, user.id, "po.create", f"po:{po.id}",
          {"po_number": po.po_number, "supplier": supplier.code, "lines": len(body.lines)})
    db.commit()
    return _po_out(po, {p.id: p.sku for p in pmap.values()}, {},
                   supplier_code=supplier.code)


@router.post("/{po_id}/receive", response_model=ReceiveOut, status_code=201)
def receive_po(po_id: int, body: ReceiveIn, db: Session = Depends(get_db),
               user=Depends(require("stock:write"))):
    """Post one goods receipt note against the order (partial receipts allowed)."""
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    if po.status not in OPEN_STATUSES:
        raise HTTPException(409, f"Purchase order is {po.status}; it cannot be received")
    warehouse = db.get(Warehouse, body.warehouse_id)
    if not warehouse:
        raise HTTPException(404, "Warehouse not found")

    skus = [ln.sku for ln in body.lines]
    pmap = _sku_map(db, skus)
    unknown = [s for s in skus if s not in pmap]
    if unknown:
        raise HTTPException(422, f"Unknown SKU(s): {', '.join(sorted(unknown))}")

    # Capacity is checked against the warehouse's measured usage before any row
    # is written. A NULL capacity is "not configured", never zero.
    receipt_units = sum((ln.qty for ln in body.lines), Decimal(0))
    used = db.scalar(select(func.coalesce(func.sum(Batch.on_hand), 0))
                     .where(Batch.warehouse_id == warehouse.id)) or Decimal(0)
    projected = used + receipt_units
    if warehouse.capacity_units is not None and projected > warehouse.capacity_units:
        if not body.allow_over_capacity:
            raise HTTPException(
                409, f"{warehouse.name} holds {used:f} of {warehouse.capacity_units} "
                     f"units; this receipt of {receipt_units:f} would take it to "
                     f"{projected:f}, over the capacity of {warehouse.capacity_units} "
                     f"units. An Administrator can allow the overage.")
        if not is_admin(db, user):
            raise HTTPException(403, "Only an Administrator can receive stock over a "
                                     "warehouse's capacity")

    ordered = {ln.product_id: ln.qty for ln in po.lines}
    po_cost = {ln.product_id: ln.unit_cost for ln in po.lines}
    already = _received_by_product(db, po.id)
    running = dict(already)
    for ln in body.lines:
        prod = pmap[ln.sku]
        if prod.id not in ordered:
            raise HTTPException(409, f"{ln.sku} is not on purchase order {po.po_number}")
        running[prod.id] = running.get(prod.id, Decimal(0)) + ln.qty
        if running[prod.id] > ordered[prod.id]:
            raise HTTPException(
                409, f"Receiving more than ordered for {ln.sku}: "
                     f"ordered {ordered[prod.id]}, already received {already.get(prod.id, 0)}, "
                     f"this receipt {ln.qty}")

    grn = GoodsReceipt(
        grn_number=f"GRN-{datetime.now():%Y%m%d}-{uuid4().hex[:6].upper()}",
        po_id=po.id, warehouse_id=warehouse.id, received_by=user.id, owner=body.owner,
        delivery_note=body.delivery_note, note=body.note)
    db.add(grn)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This delivery note has already been received for this order")

    out_lines: list[ReceivedLine] = []
    for ln in body.lines:
        prod = pmap[ln.sku]
        batch = db.scalar(select(Batch).where(
            Batch.product_id == prod.id,
            Batch.warehouse_id == warehouse.id,
            Batch.batch_no == ln.batch_no))
        if batch:
            if batch.owner != body.owner:
                raise HTTPException(409, f"Batch {ln.batch_no} already exists as "
                                         f"{batch.owner}-owned stock")
        else:
            batch = Batch(product_id=prod.id, warehouse_id=warehouse.id, batch_no=ln.batch_no,
                          expiry=ln.expiry, owner=body.owner)
            db.add(batch)
            db.flush()                       # assign id before posting the movement
        receipt_cost = po_cost.get(prod.id)
        post_movement(db, batch_id=batch.id, qty_delta=ln.qty, movement_type="receipt",
                      ref_type="grn", ref_id=str(grn.id), actor_id=user.id,
                      unit_cost=receipt_cost,
                      cost_source="po_receipt" if receipt_cost is not None else "uncosted")
        db.add(GoodsReceiptLine(grn_id=grn.id, product_id=prod.id, batch_id=batch.id, qty=ln.qty))
        out_lines.append(ReceivedLine(sku=ln.sku, batch_no=ln.batch_no, qty=ln.qty,
                                      batch_on_hand=batch.on_hand))

    received = _received_by_product(db, po.id)
    status = "received" if all(received.get(pid, Decimal(0)) >= qty
                               for pid, qty in ordered.items()) else "partially_received"
    po.status = status
    audit(db, user.id, "po.receive", f"po:{po.id}",
          {"po_number": po.po_number, "grn": grn.grn_number, "warehouse_id": warehouse.id,
           "owner": body.owner, "status": status, "delivery_note": body.delivery_note,
           "lines": [{"sku": r.sku, "batch_no": r.batch_no, "qty": str(r.qty)} for r in out_lines]})
    if (warehouse.capacity_units is not None
            and projected > warehouse.capacity_units and body.allow_over_capacity):
        audit(db, user.id, "warehouse.capacity_override", f"warehouse:{warehouse.id}",
              {"warehouse": warehouse.name, "capacity_units": warehouse.capacity_units,
               "used_units": str(used), "receipt_units": str(receipt_units),
               "projected_units": str(projected), "po_number": po.po_number,
               "grn": grn.grn_number})
    db.commit()
    sku_by_product = {p.id: p.sku for p in pmap.values()}
    remaining = {sku_by_product[pid]: max(ordered[pid] - received.get(pid, Decimal(0)), Decimal(0))
                 for pid in ordered}
    return ReceiveOut(po_number=po.po_number, status=status, grn_number=grn.grn_number,
                      owner=body.owner, received=out_lines, remaining=remaining)


@router.post("/{po_id}/cancel", response_model=POOut)
def cancel_po(po_id: int, body: CancelIn, db: Session = Depends(get_db),
              user=Depends(require("stock:write"))):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    if po.status in ("partially_received", "received"):
        raise HTTPException(409, "Goods have already been received against this order; "
                                 "a cancellation cannot undo stock movements")
    if po.status != "open":
        raise HTTPException(409, f"Purchase order is already {po.status}")
    po.status = "cancelled"
    po.cancel_reason = body.reason.strip()
    audit(db, user.id, "po.cancel", f"po:{po.id}",
          {"po_number": po.po_number, "reason": po.cancel_reason})
    db.commit()
    return _po_out(po, _sku_by_id(db), {}, supplier_code=None)
