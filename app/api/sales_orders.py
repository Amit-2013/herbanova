from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.pagination import page_params, paginate
from ..core.rbac import require
from ..core.rules import DISCOUNT_APPROVAL_PCT
from ..models.core import (ApprovalRequest, Distributor, Product, SalesOrder, SalesOrderLine,
                           User, Warehouse)
from ..services.audit import audit
from ..services.discounts import best_slab
from ..services.inventory import post_movement
from ..services.order_tax import CannotQuote, discount_pct, order_preview
from ..services.invoice import create_invoice_for_order
from ..services.sales import allocate_fefo, available_stock, credit_exposure

router = APIRouter(prefix="/api/sales-orders", tags=["sales-orders"])
CENT = Decimal("0.01")


def _money(d: Decimal) -> Decimal:
    return d.quantize(CENT, ROUND_HALF_UP)


# ---------------------------------------------------------------- schemas
class SOLineIn(BaseModel):
    sku: str = Field(min_length=3, max_length=40)
    qty: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)

    @field_validator("sku")
    @classmethod
    def norm(cls, v): return v.strip().upper()

    @field_validator("qty")
    @classmethod
    def whole(cls, v):
        if v != v.to_integral_value():
            raise ValueError("quantity must be a whole number of packs")
        return v


class SOIn(BaseModel):
    distributor_id: int
    lines: list[SOLineIn] = Field(min_length=1)

    @field_validator("lines")
    @classmethod
    def unique_skus(cls, v):
        skus = [ln.sku for ln in v]
        if len(set(skus)) != len(skus):
            raise ValueError("duplicate SKU in lines")
        return v


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class DispatchIn(BaseModel):
    warehouse_id: int


class SOLineOut(BaseModel):
    sku: str
    product_name: str
    qty: Decimal
    unit_price: Decimal
    mrp: Decimal
    discount_pct: Decimal
    line_total: Decimal


class ApprovalBrief(BaseModel):
    id: int
    status: str
    reasons: list[str]


class SOOut(BaseModel):
    id: int
    so_number: str
    distributor_id: int
    distributor_code: str
    distributor_name: str
    status: str
    total: Decimal
    needs_approval: bool
    created_by: str
    created_at: datetime | None = None
    dispatched_at: datetime | None = None
    cancel_reason: str | None = None
    lines: list[SOLineOut]
    approval: ApprovalBrief | None = None


class AllocOut(BaseModel):
    sku: str
    batch_no: str
    expiry: date | None
    qty: Decimal


class DispatchOut(BaseModel):
    order: SOOut
    allocations: list[AllocOut]


# ---------------------------------------------------------------- helpers
def _build(db: Session, orders: list[SalesOrder]) -> list[SOOut]:
    if not orders:
        return []
    dists = {d.id: d for d in db.scalars(select(Distributor).where(
        Distributor.id.in_({o.distributor_id for o in orders}))).all()}
    users = {u.id: u.username for u in db.scalars(select(User).where(
        User.id.in_({o.created_by for o in orders}))).all()}
    pids = {ln.product_id for o in orders for ln in o.lines}
    prods = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(pids))).all()} if pids else {}
    apps = {a.record_id: a for a in db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.record_type == "sales_order",
        ApprovalRequest.record_id.in_([o.id for o in orders]))).all()}
    out = []
    for o in orders:
        d, a = dists[o.distributor_id], apps.get(o.id)
        out.append(SOOut(
            id=o.id, so_number=o.so_number, distributor_id=d.id, distributor_code=d.code,
            distributor_name=d.name, status=o.status, total=o.total, needs_approval=o.needs_approval,
            created_by=users.get(o.created_by, "?"), created_at=o.created_at,
            dispatched_at=o.dispatched_at, cancel_reason=o.cancel_reason,
            lines=[SOLineOut(sku=prods[ln.product_id].sku, product_name=prods[ln.product_id].name,
                             qty=ln.qty, unit_price=ln.unit_price, mrp=prods[ln.product_id].mrp,
                             discount_pct=discount_pct(prods[ln.product_id].mrp, ln.unit_price),
                             line_total=ln.line_total) for ln in o.lines],
            approval=ApprovalBrief(id=a.id, status=a.status, reasons=a.reasons) if a else None))
    return out


def _lock_order(db: Session, order_id: int) -> SalesOrder:
    so = db.scalars(select(SalesOrder).where(SalesOrder.id == order_id).with_for_update()).first()
    if not so:
        raise HTTPException(404, "Sales order not found")
    return so


def _lock_distributor(db: Session, dist_id: int) -> Distributor:
    return db.scalars(select(Distributor).where(Distributor.id == dist_id).with_for_update()).one()


# ---------------------------------------------------------------- reads
@router.get("", response_model=list[SOOut])
def list_orders(response: Response, distributor_id: int | None = None,
                status: str | None = None, paging=Depends(page_params),
                db: Session = Depends(get_db), _=Depends(require("sales:read"))):
    page, page_size = paging
    stmt = select(SalesOrder)
    if distributor_id:
        stmt = stmt.where(SalesOrder.distributor_id == distributor_id)
    if status:
        stmt = stmt.where(SalesOrder.status == status)
    return _build(db, paginate(db, stmt.order_by(SalesOrder.id.desc()),
                               response, page, page_size))


@router.get("/{order_id}", response_model=SOOut)
def get_order(order_id: int, db: Session = Depends(get_db), _=Depends(require("sales:read"))):
    so = db.get(SalesOrder, order_id)
    if not so:
        raise HTTPException(404, "Sales order not found")
    return _build(db, [so])[0]


# ---------------------------------------------------------------- tax preview (FR-13)
@router.get("/{order_id}/tax-preview")
def tax_preview(order_id: int, db: Session = Depends(get_db), _=Depends(require("sales:read"))):
    """The discount slab and the GST the invoice will charge, before dispatch.

    Read-only, and the same `sales:read` permission as the order list. The
    numbers do not change when the order is submitted or dispatched.
    """
    so = db.get(SalesOrder, order_id)
    if not so:
        raise HTTPException(404, "Sales order not found")
    try:
        # Decimals go out as exact strings ("118.00"), never as floats
        return jsonable_encoder(order_preview(db, so), custom_encoder={Decimal: str})
    except CannotQuote as exc:
        raise HTTPException(409, str(exc))


# ---------------------------------------------------------------- create (draft)
@router.post("", response_model=SOOut, status_code=201)
def create_order(body: SOIn, db: Session = Depends(get_db), user=Depends(require("sales:write"))):
    dist = db.get(Distributor, body.distributor_id)
    if not dist:
        raise HTTPException(404, "Distributor not found")
    if dist.status != "active":
        raise HTTPException(409, f"Distributor {dist.code} is {dist.status}; orders cannot be created")
    skus = [ln.sku for ln in body.lines]
    pmap = {p.sku: p for p in db.scalars(select(Product).where(Product.sku.in_(skus))).all()}
    unknown = sorted(s for s in skus if s not in pmap)
    if unknown:
        raise HTTPException(422, f"Unknown SKU(s): {', '.join(unknown)}")
    lines, total = [], Decimal(0)
    for ln in body.lines:
        p = pmap[ln.sku]
        if p.status != "active":
            raise HTTPException(422, f"{p.sku} is not an active product")
        price = ln.unit_price if ln.unit_price is not None else p.mrp
        if price > p.mrp:
            raise HTTPException(422, f"{p.sku}: price {price} is above MRP {p.mrp}")
        lt = _money(ln.qty * price)
        total += lt
        lines.append(SalesOrderLine(product_id=p.id, qty=ln.qty, unit_price=price, line_total=lt))
    so = SalesOrder(so_number=f"SO-{datetime.now():%Y%m%d}-{uuid4().hex[:6].upper()}",
                    distributor_id=dist.id, status="draft", total=total, created_by=user.id, lines=lines)
    db.add(so)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Order number clash - please retry")
    audit(db, user.id, "so.create", f"so:{so.id}",
          {"so_number": so.so_number, "distributor": dist.code, "total": str(total), "lines": len(lines)})
    db.commit()
    return _build(db, [so])[0]


# ---------------------------------------------------------------- submit: stock + credit + discount checks
@router.post("/{order_id}/submit", response_model=SOOut)
def submit_order(order_id: int, db: Session = Depends(get_db), user=Depends(require("sales:write"))):
    so = _lock_order(db, order_id)
    if so.status != "draft":
        raise HTTPException(409, f"Order is {so.status}; only a draft can be submitted")
    dist = _lock_distributor(db, so.distributor_id)     # serialises credit checks per distributor
    if dist.status != "active":
        raise HTTPException(409, f"Distributor {dist.code} is {dist.status}")
    prods = {p.id: p for p in db.scalars(select(Product).where(
        Product.id.in_([ln.product_id for ln in so.lines]))).all()}

    short = []
    for ln in sorted(so.lines, key=lambda x: x.product_id):
        have = available_stock(db, ln.product_id)
        if have < ln.qty:
            short.append(f"{prods[ln.product_id].sku}: need {ln.qty:f}, available {have:f}")
    if short:
        raise HTTPException(409, "Insufficient stock - " + "; ".join(short))

    exposure = credit_exposure(db, dist.id, exclude_order_id=so.id)
    reasons = []
    if exposure + so.total > dist.credit_limit:
        reasons.append("credit_limit")
    # FR-13: the approval threshold comes from the discount slab that applies to
    # the line (its band, product or distributor group). With no slab, the
    # baseline percentage in core/rules.py applies.
    max_disc, disc_threshold = Decimal(0), DISCOUNT_APPROVAL_PCT
    for ln in so.lines:
        line_disc = discount_pct(prods[ln.product_id].mrp, ln.unit_price)
        slab = best_slab(db, on=date.today(), product_id=ln.product_id,
                         group_name=dist.group_name, qty=ln.qty, value=so.total)
        threshold = (Decimal(slab.approval_above)
                     if slab is not None and slab.approval_above is not None
                     else DISCOUNT_APPROVAL_PCT)
        if line_disc > max_disc:
            max_disc, disc_threshold = line_disc, threshold
        if line_disc > threshold:
            reasons.append("discount")

    so.submitted_by = user.id
    if reasons:
        db.add(ApprovalRequest(
            record_type="sales_order", record_id=so.id, reasons=reasons, requested_by=user.id,
            request_no=f"AP-{datetime.now():%Y%m%d}-{so.id:04d}"[:40],
            document_number=so.so_number,
            subject=f"{dist.name} · ₹ {so.total}"[:200],
            pending_approver_role="admin" if "credit_limit" in reasons else None,
            detail={"credit_limit": str(dist.credit_limit), "current_exposure": str(exposure),
                    "order_total": str(so.total), "projected_exposure": str(exposure + so.total),
                    "max_discount_pct": str(max_disc), "discount_threshold_pct": str(disc_threshold)}))
        so.status, so.needs_approval = "pending_approval", True
    else:
        so.status = "approved"
    audit(db, user.id, "so.submit", f"so:{so.id}",
          {"status": so.status, "reasons": reasons, "exposure": str(exposure), "limit": str(dist.credit_limit)})
    db.commit()
    return _build(db, [so])[0]


# ---------------------------------------------------------------- cancel
@router.post("/{order_id}/cancel", response_model=SOOut)
def cancel_order(order_id: int, body: ReasonIn, db: Session = Depends(get_db),
                 user=Depends(require("sales:write"))):
    so = _lock_order(db, order_id)
    if so.status == "dispatched":
        raise HTTPException(409, "Dispatched orders cannot be cancelled; a return is needed (not built yet)")
    if so.status not in ("draft", "pending_approval", "approved"):
        raise HTTPException(409, f"Order is already {so.status}")
    ar = db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.record_type == "sales_order", ApprovalRequest.record_id == so.id)
        .with_for_update()).first()
    if ar and ar.status == "pending":
        ar.status = "withdrawn"
    prev = so.status
    so.status, so.cancel_reason = "cancelled", body.reason.strip()
    audit(db, user.id, "so.cancel", f"so:{so.id}", {"from": prev, "reason": so.cancel_reason})
    db.commit()
    return _build(db, [so])[0]


# ---------------------------------------------------------------- dispatch
@router.post("/{order_id}/dispatch", response_model=DispatchOut, status_code=201)
def dispatch_order(order_id: int, body: DispatchIn, db: Session = Depends(get_db),
                   user=Depends(require("dispatch:write"))):
    so = _lock_order(db, order_id)
    if so.status == "dispatched":
        raise HTTPException(409, "Order already dispatched - duplicate dispatch rejected")
    if so.status != "approved":
        raise HTTPException(409, f"Order is {so.status}; only an approved order can be dispatched")
    wh = db.get(Warehouse, body.warehouse_id)
    if not wh:
        raise HTTPException(404, "Warehouse not found")
    dist = _lock_distributor(db, so.distributor_id)
    if dist.status != "active":
        raise HTTPException(409, f"Distributor {dist.code} is {dist.status}")

    ar = db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.record_type == "sales_order", ApprovalRequest.record_id == so.id)).first()
    credit_waived = bool(ar and ar.status == "approved" and "credit_limit" in ar.reasons)
    if not credit_waived:
        delivered = credit_exposure(db, dist.id, exclude_order_id=so.id, statuses=("dispatched",))
        if delivered + so.total > dist.credit_limit:
            raise HTTPException(409, f"Credit limit exceeded: {delivered:f} already delivered plus this order "
                                     f"{so.total:f} is over the limit of {dist.credit_limit:f}; "
                                     f"cancel and re-submit the order for approval")

    prods = {p.id: p for p in db.scalars(select(Product).where(
        Product.id.in_([ln.product_id for ln in so.lines]))).all()}
    plan, short = [], []
    for ln in sorted(so.lines, key=lambda x: x.product_id):      # fixed lock order avoids deadlocks
        alloc, shortfall = allocate_fefo(db, ln.product_id, ln.qty, wh.id)
        if shortfall > 0:
            short.append(f"{prods[ln.product_id].sku}: short by {shortfall:f} in {wh.name}")
        plan.append((ln, alloc))
    if short:
        raise HTTPException(409, "Insufficient stock - " + "; ".join(short))

    out = []
    for ln, alloc in plan:
        for batch, take in alloc:
            post_movement(db, batch_id=batch.id, qty_delta=-take, movement_type="issue",
                          ref_type="so", ref_id=str(so.id), actor_id=user.id)
            out.append(AllocOut(sku=prods[ln.product_id].sku, batch_no=batch.batch_no,
                                expiry=batch.expiry, qty=take))
    so.status, so.dispatched_by = "dispatched", user.id
    so.dispatched_at = datetime.now(timezone.utc)
    try:
        invoice = create_invoice_for_order(db, so, issued_by=user.id)
        # Store expiry from each allocation onto the matching invoice line
        for alloc in out:
            line = next((l for l in invoice.lines if l.sku == alloc.sku), None)
            # one line can be filled from several batches: keep the earliest expiry
            if line is not None and alloc.expiry is not None and (
                    line.expiry is None or alloc.expiry < line.expiry):
                line.expiry = alloc.expiry
    except ValueError as exc:
        # the stock issue above is in this same uncommitted transaction, so a
        # failure here gives both the movement and the number back
        db.rollback()
        raise HTTPException(409, f"Invoice could not be issued: {exc}")
    # Log expiry changes from batch allocations to invoice lines
    expiry_changes = []
    for alloc in out:
        line = next((l for l in invoice.lines if l.sku == alloc.sku), None)
        if line is not None and line.expiry is not None:
            expiry_changes.append({
                "sku": alloc.sku,
                "batch_expiry": str(alloc.expiry) if alloc.expiry else None,
                "invoice_line_expiry": str(line.expiry)
            })
    audit_kw = {"warehouse_id": wh.id, "allocations": [a.model_dump(mode="json") for a in out]}
    if expiry_changes:
        audit_kw["expiry_changes"] = expiry_changes
    audit(db, user.id, "so.dispatch", f"so:{so.id}", audit_kw)
    db.commit()
    return DispatchOut(order=_build(db, [so])[0], allocations=out)