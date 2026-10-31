"""Overview dashboard figures, counted in the database.

The browser used to work these out by filtering lists it had loaded with
page_size=200, so once any list passed 200 records the tiles silently
understated the truth (audit D-05). Every figure here is a SQL aggregate over
the whole table, and each section is returned only when the caller holds the
permission that the matching list endpoint requires. A section the caller may
not see is `null`, never zero, so the screen can tell "none" from "not allowed".
"""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import is_admin, require_login, role_permissions
from ..models.core import (ApprovalRequest, Batch, Lead, Product, PurchaseOrder,
                           PurchaseOrderLine, SalesOrder, Warehouse)
from ..models.suppliers import GoodsReceipt, GoodsReceiptLine

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

EXPIRY_WINDOW_DAYS = 90
LIST_LIMIT = 6
OPEN_PO = ("open", "partially_received")
LEAD_CLOSED = ("won", "lost")


def _money(value) -> str:
    return str((Decimal(value or 0)).quantize(Decimal("0.01")))


def _stock(db: Session, today: date) -> dict:
    in_stock = Batch.on_hand > 0
    units, batches = db.execute(
        select(func.coalesce(func.sum(Batch.on_hand), 0), func.count())
        .where(in_stock)).one()
    horizon = today + timedelta(days=EXPIRY_WINDOW_DAYS)
    watch_filter = (in_stock, Batch.expiry.is_not(None), Batch.expiry <= horizon)
    watch_total = db.scalar(select(func.count()).where(*watch_filter)) or 0
    rows = db.execute(
        select(Batch, Product.name, Warehouse.name)
        .join(Product, Product.id == Batch.product_id)
        .join(Warehouse, Warehouse.id == Batch.warehouse_id)
        .where(*watch_filter).order_by(Batch.expiry.asc(), Batch.id.asc())
        .limit(LIST_LIMIT)).all()
    return {
        "units_on_hand": str(units), "batches_in_stock": batches,
        "expiring_count": watch_total,
        "expiring": [{"batch_id": b.id, "product_name": pname, "batch_no": b.batch_no,
                      "warehouse": wname, "on_hand": str(b.on_hand),
                      "expiry": b.expiry.isoformat(),
                      "days_left": (b.expiry - today).days}
                     for b, pname, wname in rows],
    }


def _purchase_orders(db: Session) -> dict:
    open_filter = PurchaseOrder.status.in_(OPEN_PO)
    total = db.scalar(select(func.count()).where(open_filter)) or 0
    pos = db.scalars(select(PurchaseOrder).where(open_filter)
                     .order_by(PurchaseOrder.id.desc()).limit(LIST_LIMIT)).all()
    ids = [p.id for p in pos]
    value, ordered, received, receipts = {}, {}, {}, {}
    if ids:
        for po_id, product_id, qty, cost in db.execute(
                select(PurchaseOrderLine.po_id, PurchaseOrderLine.product_id,
                       PurchaseOrderLine.qty, PurchaseOrderLine.unit_cost)
                .where(PurchaseOrderLine.po_id.in_(ids))).all():
            ordered[(po_id, product_id)] = qty
            value[po_id] = value.get(po_id, Decimal(0)) + qty * (cost or 0)
        for po_id, product_id, qty in db.execute(
                select(GoodsReceipt.po_id, GoodsReceiptLine.product_id,
                       func.sum(GoodsReceiptLine.qty))
                .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.grn_id)
                .where(GoodsReceipt.po_id.in_(ids))
                .group_by(GoodsReceipt.po_id, GoodsReceiptLine.product_id)).all():
            received[(po_id, product_id)] = qty
        receipts = dict(db.execute(
            select(GoodsReceipt.po_id, func.count()).where(GoodsReceipt.po_id.in_(ids))
            .group_by(GoodsReceipt.po_id)).all())
    out = []
    for p in pos:
        remaining = sum((max(q - received.get(k, Decimal(0)), Decimal(0))
                         for k, q in ordered.items() if k[0] == p.id), Decimal(0))
        out.append({"id": p.id, "po_number": p.po_number, "supplier": p.supplier,
                    "status": p.status, "value": _money(value.get(p.id)),
                    "remaining_units": str(remaining),
                    "receipt_count": receipts.get(p.id, 0)})
    return {"open_count": total, "open": out}


def _leads(db: Session, today: date) -> dict:
    live = Lead.status.not_in(LEAD_CLOSED)
    overdue, due_today = db.execute(select(
        func.count().filter(live, Lead.next_follow_up < today),
        func.count().filter(live, Lead.next_follow_up == today))).one()
    return {"overdue": overdue, "due_today": due_today}


@router.get("")
def dashboard(db: Session = Depends(get_db), user=Depends(require_login)):
    perms = role_permissions(db, user)
    today = date.today()
    out = {"as_of": today.isoformat(), "stock": None, "purchase_orders": None,
           "active_products": None, "orders_ready": None, "approvals_waiting": None,
           "leads": None, "warehouse_count": None}
    if "stock:read" in perms:
        out["stock"] = _stock(db, today)
        out["purchase_orders"] = _purchase_orders(db)
        out["warehouse_count"] = db.scalar(select(func.count()).select_from(Warehouse)) or 0
    if "product:read" in perms:
        out["active_products"] = db.scalar(
            select(func.count()).where(Product.status == "active")) or 0
    if "sales:read" in perms:
        out["orders_ready"] = db.scalar(
            select(func.count()).where(SalesOrder.status == "approved")) or 0
    if "approval:read" in perms:
        stmt = select(func.count()).where(ApprovalRequest.status == "pending")
        if not is_admin(db, user) and not (
                {"hr:write", "hr:attendance_manage", "hr:leave_approve",
                 "hr:payroll_prepare"} & perms):
            # Same rule as the approvals queue: an employee sees only the HR
            # requests they raised.
            stmt = stmt.where(case(
                (ApprovalRequest.record_type.like("hr\\_%", escape="\\"),
                 ApprovalRequest.requested_by == user.id), else_=True))
        out["approvals_waiting"] = db.scalar(stmt) or 0
    if "lead:read" in perms:
        out["leads"] = _leads(db, today)
    return out
