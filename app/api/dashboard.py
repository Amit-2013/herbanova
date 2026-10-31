"""Overview dashboard figures, counted in the database.

The browser used to work these out by filtering lists it had loaded with
page_size=200, so once any list passed 200 records the tiles silently
understated the truth (audit D-05). Every figure here is a SQL aggregate over
the whole table, and each section is returned only when the caller holds the
permission that the matching list endpoint requires. A section the caller may
not see is `null`, never zero, so the screen can tell "none" from "not allowed".

Phase 2 adds the period selector, attention rules, ageing, charts, expiry
buckets, open-PO progress, the approvals list, top products, recent activity
and a system-health section. Lists are capped and always carry their true
total, and no figure is taken from a capped list. Where the database does not
hold the input (product category, warehouse capacity, batch cost, a stored
backup result), the section says so and names the gap instead of showing a
figure that cannot be sourced.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Date, cast, func, or_, select, text
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..core.india_states import STATE_CODES, state_name
from ..core import module_register
from ..core.rbac import is_admin, require, require_login, role_permissions
from ..core.rules import REPORT_TZ
from ..models.core import (ApprovalRequest, AuditLog, Batch, CreditNote, DebitNote,
                           Distributor, Invoice, InvoiceLine, Lead, Product,
                           PurchaseOrder, PurchaseOrderLine, SalesOrder,
                           StockMovement, User, Warehouse)
from ..models.hr import Attendance, LeaveApplication, ODRequest
from ..models.suppliers import GoodsReceipt, GoodsReceiptLine
from ..models.users import Employee
from ..services import capacity, ledger, telegram
from ..services.sales import EXPOSURE_STATUSES

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

EXPIRY_WINDOW_DAYS = 90
LIST_LIMIT = 6
OPEN_PO = ("open", "partially_received")
LEAD_CLOSED = ("won", "lost")
RANGE_CHOICES = (7, 30, 90)
TREND_POINTS = 12
DASHBOARD_TTL_SECONDS = 45
HR_MANAGER_PERMS = {"hr:write", "hr:attendance_manage", "hr:leave_approve",
                    "hr:payroll_prepare"}

# In-process cache. Disabled for tests and for any database whose name ends in
# _test, so a test never reads a payload seeded by the previous test.
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_GENERATION = 0


def invalidate_dashboard_cache() -> None:
    """Retire every cached payload after a write that changes a dashboard figure.

    The cache is keyed by generation rather than cleared, so a request already
    inside the route cannot have its own payload evicted mid-flight.
    """
    global _CACHE_GENERATION
    _CACHE_GENERATION += 1


def _money(value) -> str:
    return str((Decimal(value or 0)).quantize(Decimal("0.01")))


def _business_day(column):
    """The calendar day a timestamp falls on, in the business time zone.

    A timestamp is stored in UTC; grouping it by the database server's own
    day would put a receipt after midnight IST in the previous day's column.
    """
    return cast(func.timezone(REPORT_TZ, column), Date)


def _cache_enabled(db: Session) -> bool:
    name = (db.get_bind().url.database or "")
    return settings.app_env == "production" and not name.endswith("_test")


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


def _purchase_orders(db: Session, start: date, end: date) -> dict:
    open_filter = (PurchaseOrder.status.in_(OPEN_PO),)
    total = db.scalar(select(func.count()).where(*open_filter)) or 0
    created_day = _business_day(PurchaseOrder.created_at)
    in_range = open_filter + (created_day >= start, created_day <= end)
    in_range_count = db.scalar(select(func.count()).where(*in_range)) or 0
    pos = db.scalars(select(PurchaseOrder).where(*in_range)
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
        ordered_qty = sum((q for k, q in ordered.items() if k[0] == p.id), Decimal(0))
        received_qty = sum((received.get(k, Decimal(0))
                            for k in ordered if k[0] == p.id), Decimal(0))
        pct = (float(received_qty) / float(ordered_qty) * 100
               if ordered_qty else 0.0)
        out.append({"id": p.id, "po_number": p.po_number, "supplier": p.supplier,
                    "status": p.status, "value": _money(value.get(p.id)),
                    "remaining_units": str(remaining),
                    "ordered_units": str(ordered_qty),
                    "received_units": str(received_qty),
                    "pct_received": round(pct, 1),
                    "receipt_count": receipts.get(p.id, 0)})
    return {"open_count": total, "in_range_count": in_range_count,
            "from": start.isoformat(), "to": end.isoformat(), "open": out}


def _leads(db: Session, today: date) -> dict:
    live = Lead.status.not_in(LEAD_CLOSED)
    overdue, due_today = db.execute(select(
        func.count().filter(live, Lead.next_follow_up < today),
        func.count().filter(live, Lead.next_follow_up == today))).one()
    return {"overdue": overdue, "due_today": due_today}


# ------------------------------------------------------------ period figures
def _change(current: Decimal, previous: Decimal) -> float | None:
    if previous is None or Decimal(previous) == 0:
        return None
    return round(float((Decimal(current) - Decimal(previous))
                       / Decimal(previous) * 100), 1)


def _sales_by_day(db: Session, start: date, end: date) -> dict[date, Decimal]:
    rows = db.execute(
        select(Invoice.invoice_date, func.coalesce(func.sum(Invoice.grand_total), 0))
        .where(Invoice.status == "issued", Invoice.invoice_date >= start,
               Invoice.invoice_date <= end)
        .group_by(Invoice.invoice_date)).all()
    return {day: ledger.money(total) for day, total in rows}


def _purchases_by_day(db: Session, start: date, end: date) -> dict[date, Decimal]:
    day = _business_day(GoodsReceipt.received_at)
    rows = db.execute(
        select(day, func.coalesce(func.sum(GoodsReceiptLine.qty
                                           * func.coalesce(PurchaseOrderLine.unit_cost, 0)), 0))
        .select_from(GoodsReceiptLine)
        .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.grn_id)
        .join(PurchaseOrderLine,
              (PurchaseOrderLine.po_id == GoodsReceipt.po_id)
              & (PurchaseOrderLine.product_id == GoodsReceiptLine.product_id))
        .where(day >= start, day <= end)
        .group_by(day)).all()
    return {d: ledger.money(total) for d, total in rows}


def _sales_purchases(db: Session, start: date, end: date) -> dict:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    sales = _sales_by_day(db, start, end)
    purchases = _purchases_by_day(db, start, end)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=(end - start).days)
    prev_sales = sum(_sales_by_day(db, prev_start, prev_end).values(), Decimal(0))
    prev_purchases = sum(_purchases_by_day(db, prev_start, prev_end).values(), Decimal(0))
    current_sales = sum(sales.values(), Decimal(0))
    current_purchases = sum(purchases.values(), Decimal(0))
    return {
        "from": start.isoformat(), "to": end.isoformat(),
        "series": [{"date": d.isoformat(),
                    "sales": float(sales.get(d, Decimal(0))),
                    "purchases": float(purchases.get(d, Decimal(0)))} for d in days],
        "sales_total": _money(current_sales),
        "purchases_total": _money(current_purchases),
        "sales_change": _change(current_sales, prev_sales),
        "purchases_change": _change(current_purchases, prev_purchases),
        "previous_from": prev_start.isoformat(), "previous_to": prev_end.isoformat(),
        "note": ("Sales are issued tax invoices (including GST) and total the Sales "
                 "Invoice Register. Purchases are goods received against purchase "
                 "orders, valued at the order cost, and total the Goods Receipt "
                 "Register's receipts; a line without a price counts as zero."),
    }


def _top_products(db: Session, start: date, end: date) -> dict:
    def top(a: date, b: date, limit: int | None = None) -> list[dict]:
        stmt = (select(InvoiceLine.product_id, InvoiceLine.sku,
                       InvoiceLine.product_name,
                       func.coalesce(func.sum(InvoiceLine.qty), 0),
                       func.coalesce(func.sum(InvoiceLine.taxable_value), 0))
                .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                .where(Invoice.status == "issued", Invoice.invoice_date >= a,
                       Invoice.invoice_date <= b)
                .group_by(InvoiceLine.product_id, InvoiceLine.sku,
                          InvoiceLine.product_name)
                .order_by(func.sum(InvoiceLine.taxable_value).desc(),
                          InvoiceLine.product_id.asc()))
        if limit:
            stmt = stmt.limit(limit)
        return [{"product_id": pid, "sku": sku, "name": name,
                 "qty": str(qty), "revenue": _money(revenue)}
                for pid, sku, name, qty, revenue in db.execute(stmt).all()]

    current = top(start, end, LIST_LIMIT)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=(end - start).days)
    previous = {r["product_id"]: Decimal(r["revenue"])
                for r in top(prev_start, prev_end)}
    for row in current:
        row["previous_revenue"] = _money(previous.get(row["product_id"], Decimal(0)))
        row["change"] = _change(Decimal(row["revenue"]),
                                previous.get(row["product_id"], Decimal(0)))
    return {"rows": current, "previous_from": prev_start.isoformat(),
            "previous_to": prev_end.isoformat(),
            "note": "Revenue is taxable value (before GST)."}


def _stock_by_warehouse(db: Session) -> list[dict]:
    rows = capacity.warehouse_positions(db)
    total = sum((Decimal(r["used_units"]) for r in rows), Decimal(0))
    for r in rows:
        used = Decimal(r["used_units"])
        r["units"] = r["used_units"]
        r["share"] = round(float(used / total * 100), 1) if total > 0 else 0.0
        r["gap"] = "GAP-D03" if r["capacity_units"] is None else None
    return rows


def _capacity_alert(db: Session) -> dict | None:
    """Warehouses at or above the 80% attention line, from the same figures."""
    rows = capacity.warehouse_positions(db)
    tight = [r for r in rows if r["capacity_state"] in ("high", "over", "full")]
    if not tight:
        return None
    return {"count": len(tight),
            "names": [r["name"] for r in tight],
            "over": any(r["capacity_state"] == "over" for r in tight)}


def _expiry_counts(db: Session, today: date) -> dict:
    horizon_90 = today + timedelta(days=EXPIRY_WINDOW_DAYS)
    horizon_30 = today + timedelta(days=30)
    in_stock = Batch.on_hand > 0
    expired, soon, later = db.execute(select(
        func.count().filter(in_stock, Batch.expiry.is_not(None), Batch.expiry < today),
        func.count().filter(in_stock, Batch.expiry.is_not(None),
                            Batch.expiry >= today, Batch.expiry <= horizon_30),
        func.count().filter(in_stock, Batch.expiry.is_not(None),
                            Batch.expiry > horizon_30, Batch.expiry <= horizon_90))).one()
    return {"expired": expired, "lt30": soon, "lt90": later,
            "total": expired + soon + later}


def _suggested_action(days_left: int) -> tuple[str, str]:
    if days_left < 0:
        return ("Write off or seek clearance approval", "bad")
    if days_left <= 30:
        return ("Dispatch first (FEFO)", "warn")
    return ("Plan FEFO dispatch", "off")


def _expiry_rows(db: Session, today: date, bucket: str,
                 limit: int, offset: int) -> tuple[int, list[dict]]:
    """Batches on hand in one expiry bucket. The three buckets are disjoint,
    so their counts add up to the "all" total the watch panel shows."""
    horizon_90 = today + timedelta(days=EXPIRY_WINDOW_DAYS)
    horizon_30 = today + timedelta(days=30)
    base = (Batch.on_hand > 0, Batch.expiry.is_not(None))
    if bucket == "expired":
        cond = (Batch.expiry < today,)
    elif bucket == "lt30":
        cond = (Batch.expiry >= today, Batch.expiry <= horizon_30)
    elif bucket == "lt90":
        cond = (Batch.expiry > horizon_30, Batch.expiry <= horizon_90)
    else:
        cond = (Batch.expiry <= horizon_90,)
    where = base + cond
    total = db.scalar(select(func.count()).where(*where)) or 0
    rows = db.execute(
        select(Batch, Product.name, Product.sku, Warehouse.name)
        .join(Product, Product.id == Batch.product_id)
        .join(Warehouse, Warehouse.id == Batch.warehouse_id)
        .where(*where).order_by(Batch.expiry.asc(), Batch.id.asc())
        .limit(limit).offset(offset)).all()
    out = []
    for batch, product_name, sku, warehouse in rows:
        days = (batch.expiry - today).days
        action, tone = _suggested_action(days)
        out.append({"batch_id": batch.id, "product_id": batch.product_id,
                    "sku": sku, "product_name": product_name,
                    "batch_no": batch.batch_no, "warehouse": warehouse,
                    "warehouse_id": batch.warehouse_id,
                    "on_hand": str(batch.on_hand), "expiry": batch.expiry.isoformat(),
                    "days_left": days, "action": action, "tone": tone,
                    "value": None, "value_gap": "GAP-D04"})
    return total, out


def _expiry_watch(db: Session, today: date) -> dict:
    counts = _expiry_counts(db, today)
    total, rows = _expiry_rows(db, today, "all", LIST_LIMIT + 4, 0)
    return {**counts, "rows": rows, "shown": len(rows), "shown_of": total,
            "buckets": [{"key": "expired", "label": "Expired", "count": counts["expired"]},
                        {"key": "lt30", "label": "Expires within 30 days",
                         "count": counts["lt30"]},
                        {"key": "lt90", "label": "Expires in 31–90 days",
                         "count": counts["lt90"]}],
            "note": ("The three buckets are disjoint and add up to the total. "
                     "Batch value is not shown because stock carries no cost "
                     "(GAP-D04).")}


def _attention(db: Session, user, perms: set[str], today: date,
               stock: dict | None, ageing: dict | None) -> list[dict]:
    items: list[dict] = []
    if stock is not None:
        counts = _expiry_counts(db, today)
        units = db.scalar(select(func.coalesce(func.sum(Batch.on_hand), 0))
                          .where(Batch.on_hand > 0, Batch.expiry.is_not(None),
                                 Batch.expiry < today)) or 0
        items.append({"key": "expired_batches", "label": "Batches past expiry",
                      "count": counts["expired"], "units": str(units),
                      "severity": "bad" if counts["expired"] else "ok",
                      "href": "#/inventory/stock", "available": True})
        alert = _capacity_alert(db)
        configured = (db.scalar(select(func.count())
                                .where(Warehouse.capacity_units.is_not(None))) or 0) > 0
        items.append({"key": "warehouse_capacity",
                      "label": "Warehouses above 80% capacity",
                      "count": alert["count"] if alert else 0,
                      "severity": ("bad" if alert and alert["over"]
                                   else "warn" if alert else "ok"),
                      "href": "#/inventory/warehouses", "available": True,
                      "note": (", ".join(alert["names"][:3]) if alert
                               else "" if configured
                               else "Capacity is not set for any warehouse.")})
    if ageing is not None:
        old = [b for b in ageing["buckets"] if b["key"] in ("61-90", "90+")]
        amount = sum((b["total"] for b in old), Decimal(0))
        count = sum(b["count"] for b in old)
        items.append({"key": "receivables_60", "label": "Receivables over 60 days",
                      "count": count, "amount": _money(amount),
                      "severity": "warn" if count else "ok",
                      "href": "#/accounts", "available": True})
    if "approval:read" in perms:
        rows = _visible_pending(db, user, perms)
        admin_items = [a for a in rows
                       if "credit_limit" in (a.reasons or [])
                       or a.record_type == "invoice_post_billing"]
        items.append({"key": "approvals_admin",
                      "label": "Approvals needing an Administrator",
                      "count": len(admin_items),
                      "severity": "warn" if admin_items else "ok",
                      "href": "#/approvals", "available": True})
    if stock is not None:
        items.append({"key": "low_stock", "label": "Low stock against reorder level",
                      "severity": "off", "count": None, "available": False,
                      "gap": "GAP-D02",
                      "note": "No reorder level is captured."})
    return items


def _visible_pending(db: Session, user, perms: set[str]) -> list[ApprovalRequest]:
    stmt = select(ApprovalRequest).where(ApprovalRequest.status == "pending")
    if not is_admin(db, user) and not (HR_MANAGER_PERMS & perms):
        # Same rule as the approvals queue and the waiting tile: an employee
        # sees only the HR requests they raised.
        from sqlalchemy import case
        stmt = stmt.where(case(
            (ApprovalRequest.record_type.like("hr\\_%", escape="\\"),
             ApprovalRequest.requested_by == user.id), else_=True))
    return db.scalars(stmt).all()


def _approvals_section(db: Session, user, perms: set[str]) -> dict:
    from .approvals import _build
    rows = _visible_pending(db, user, perms)
    pending = sorted(rows, key=lambda a: (a.requested_at or datetime.min,
                                          a.id))
    built = _build(db, pending[:LIST_LIMIT], user)
    return {"count": len(pending), "rows": [a.model_dump() for a in built],
            "shown": len(built),
            "note": "Only a different person from the requester can decide."}


def _activity(db: Session, limit: int = 8,
              start: date | None = None, end: date | None = None) -> dict:
    day = _business_day(AuditLog.at)
    where = ()
    if start is not None and end is not None:
        where = (day >= start, day <= end)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*where)) or 0
    rows = db.execute(
        select(AuditLog, User.username)
        .join(User, User.id == AuditLog.actor_id, isouter=True)
        .where(*where)
        .order_by(AuditLog.id.desc()).limit(limit)).all()
    return {"rows": [{"id": log.id, "at": log.at.isoformat() if log.at else None,
                      "actor": actor or "system", "action": log.action,
                      "record": log.record, "changes": log.changes or {}}
                     for log, actor in rows],
            "shown": len(rows), "total": total}


@lru_cache(maxsize=1)
def _alembic_head() -> str | None:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:
        return None


def _health(db: Session) -> dict:
    current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    head = _alembic_head()
    totals = module_register.totals()
    return {
        "modules": {"working": totals["working"], "counted": totals["counted"],
                    "percent": totals["percent"]},
        "schema": {"current": current, "head": head,
                   "at_head": bool(current and head and current == head)},
        "backup": {"status": "not_recorded", "gap": "GAP-D09",
                   "note": "Run python backup_restore_test.py and keep its output."},
        "alerts": {"configured": telegram.enabled(),
                   "note": ("Telegram is configured; delivery is not probed."
                            if telegram.enabled() else
                            "Telegram is not configured.")},
    }


# ------------------------------------------------------------ stock history
def _sample_days(start: date, end: date) -> list[date]:
    span = (end - start).days
    if span + 1 <= TREND_POINTS:
        return [start + timedelta(days=i) for i in range(span + 1)]
    step = span / (TREND_POINTS - 1)
    days = sorted({start + timedelta(days=round(i * step))
                   for i in range(TREND_POINTS)})
    if days[-1] != end:
        days[-1] = end
    return days


def _stock_history(db: Session, start: date, end: date) -> dict:
    """Units, batches and expiring counts at the end of each sample day.

    On-hand now minus the movements posted after a day is exactly what was on
    hand at the end of that day, so this needs no stored daily snapshot.
    """
    batches = db.execute(select(Batch.id, Batch.on_hand, Batch.expiry)).all()
    day = _business_day(StockMovement.created_at)
    deltas = db.execute(
        select(day, StockMovement.batch_id,
               func.sum(StockMovement.qty_delta))
        .where(day >= start)
        .group_by(day, StockMovement.batch_id)).all()
    by_day: dict[date, list[tuple[int, Decimal]]] = {}
    for day, batch_id, delta in deltas:
        by_day.setdefault(day, []).append((batch_id, Decimal(delta)))
    delta_dates = sorted(by_day, reverse=True)
    days = _sample_days(start, end)
    later: dict[int, Decimal] = {}
    pointer = 0
    units_by_day, batches_by_day, expiring_by_day = {}, {}, {}
    for day in sorted(days, reverse=True):
        while pointer < len(delta_dates) and delta_dates[pointer] > day:
            for batch_id, delta in by_day[delta_dates[pointer]]:
                later[batch_id] = later.get(batch_id, Decimal(0)) + delta
            pointer += 1
        on_hand = 0
        in_stock = 0
        expiring = 0
        horizon = day + timedelta(days=EXPIRY_WINDOW_DAYS)
        for batch_id, current, expiry in batches:
            value = Decimal(current or 0) - later.get(batch_id, Decimal(0))
            if value <= 0:
                continue
            on_hand += value
            in_stock += 1
            if expiry is not None and expiry <= horizon:
                expiring += 1
        units_by_day[day] = float(on_hand)
        batches_by_day[day] = in_stock
        expiring_by_day[day] = expiring
    ordered = sorted(days)
    return {"points": [d.isoformat() for d in ordered],
            "units": [units_by_day[d] for d in ordered],
            "batches": [batches_by_day[d] for d in ordered],
            "expiring": [expiring_by_day[d] for d in ordered]}


# ------------------------------------------------------------ search
SEARCH_LIMIT = 5


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=80),
           db: Session = Depends(get_db), user=Depends(require_login)):
    """One search across the records the caller may see. Read-only."""
    term = q.strip()
    if len(term) < 2:
        raise HTTPException(422, "Enter at least two characters")
    perms = role_permissions(db, user)
    like = f"%{term}%"
    groups = []

    def group(key: str, label: str, rows: list[dict]):
        if rows:
            groups.append({"key": key, "label": label, "items": rows,
                           "shown": len(rows)})

    if "product:read" in perms:
        rows = db.scalars(select(Product).where(
            or_(Product.sku.ilike(like), Product.name.ilike(like)))
            .order_by(Product.sku).limit(SEARCH_LIMIT)).all()
        group("products", "Products", [
            {"id": p.id, "title": p.sku, "subtitle": p.name, "href": "#/products"}
            for p in rows])
    if "sales:read" in perms:
        rows = db.scalars(select(Distributor).where(
            or_(Distributor.code.ilike(like), Distributor.name.ilike(like)))
            .order_by(Distributor.code).limit(SEARCH_LIMIT)).all()
        group("distributors", "Customers", [
            {"id": d.id, "title": d.code, "subtitle": d.name, "href": "#/distributors"}
            for d in rows])
        rows = db.scalars(select(SalesOrder).where(SalesOrder.so_number.ilike(like))
                          .order_by(SalesOrder.id.desc()).limit(SEARCH_LIMIT)).all()
        group("sales_orders", "Sales orders", [
            {"id": s.id, "title": s.so_number,
             "subtitle": f"{s.status.replace('_', ' ')} · ₹ {money(s.total)}",
             "href": "#/sales"} for s in rows])
        rows = db.scalars(select(Invoice).where(
            or_(Invoice.invoice_number.ilike(like), Invoice.buyer_name.ilike(like)))
            .order_by(Invoice.id.desc()).limit(SEARCH_LIMIT)).all()
        group("invoices", "Invoices", [
            {"id": i.id, "title": i.invoice_number,
             "subtitle": f"{i.buyer_name} · ₹ {money(i.grand_total)}",
             "href": "#/billing"} for i in rows])
    if "stock:read" in perms:
        rows = db.scalars(select(PurchaseOrder).where(
            or_(PurchaseOrder.po_number.ilike(like), PurchaseOrder.supplier.ilike(like)))
            .order_by(PurchaseOrder.id.desc()).limit(SEARCH_LIMIT)).all()
        group("purchase_orders", "Purchase orders", [
            {"id": p.id, "title": p.po_number,
             "subtitle": f"{p.status.replace('_', ' ')} · {p.supplier}",
             "href": "#/purchasing"} for p in rows])
    if "supplier:read" in perms:
        from ..models.suppliers import Supplier
        rows = db.scalars(select(Supplier).where(
            or_(Supplier.code.ilike(like), Supplier.name.ilike(like)))
            .order_by(Supplier.code).limit(SEARCH_LIMIT)).all()
        group("suppliers", "Suppliers", [
            {"id": s.id, "title": s.code, "subtitle": s.name, "href": "#/suppliers"}
            for s in rows])
    if "lead:read" in perms:
        rows = db.scalars(select(Lead).where(
            or_(Lead.lead_no.ilike(like), Lead.name.ilike(like),
                Lead.company.ilike(like)))
            .order_by(Lead.id.desc()).limit(SEARCH_LIMIT)).all()
        group("leads", "Leads", [
            {"id": l.id, "title": l.lead_no,
             "subtitle": f"{l.name}{' · ' + l.company if l.company else ''}",
             "href": "#/leads"} for l in rows])
    return {"query": term, "groups": groups}


def money(value) -> str:
    return _money(value)


# ------------------------------------------------------------ phase 3 insights
SALES_STATUS_LABELS = {"draft": "Draft", "pending_approval": "Pending approval",
                       "approved": "Approved", "dispatched": "Dispatched",
                       "cancelled": "Cancelled", "rejected": "Rejected"}
LEAD_STATUS_LABELS = {"new": "New", "contacted": "Contacted",
                      "qualified": "Qualified", "won": "Won", "lost": "Lost"}
PO_AGE_BUCKETS = (("0-7", "0–7 days", None, 7),
                  ("8-14", "8–14 days", 8, 14),
                  ("15-30", "15–30 days", 15, 30),
                  ("31+", "31+ days", 31, None))
ATTENDANCE_LABELS = {"present": "Present", "late": "Late", "half_day": "Half day",
                     "absent": "Absent", "paid_leave": "Paid leave",
                     "unpaid_leave": "Unpaid leave", "od": "On duty",
                     "weekly_off": "Weekly off", "holiday": "Holiday",
                     "early_departure": "Early departure",
                     "correction_pending": "Correction pending"}


def _pipeline(db: Session, perms: set[str]) -> dict:
    out = {"sales": None, "leads": None}
    if "sales:read" in perms:
        counts = {status: (count, value) for status, count, value in db.execute(
            select(SalesOrder.status, func.count(),
                   func.coalesce(func.sum(SalesOrder.total), 0))
            .group_by(SalesOrder.status)).all()}
        rows = [{"status": key, "label": label,
                 "count": int(counts.get(key, (0, 0))[0]),
                 "value": _money(counts.get(key, (0, 0))[1])}
                for key, label in SALES_STATUS_LABELS.items()]
        dispatched = db.execute(
            select(SalesOrder.created_at, SalesOrder.dispatched_at)
            .where(SalesOrder.status == "dispatched",
                   SalesOrder.dispatched_at.is_not(None))).all()
        days = [(done - raised).total_seconds() / 86400
                for raised, done in dispatched
                if raised is not None and done is not None and done >= raised]
        out["sales"] = {
            "rows": rows, "total": sum(r["count"] for r in rows),
            "dispatch": {
                "measured": len(days),
                "average_days": round(sum(days) / len(days), 1) if days else None,
                "note": ("From the order being raised to dispatch. Approval time is "
                         "not stored separately, so it is included.")}}
    if "lead:read" in perms:
        counts = dict(db.execute(select(Lead.status, func.count())
                                 .group_by(Lead.status)).all())
        rows = [{"status": key, "label": label, "count": int(counts.get(key, 0))}
                for key, label in LEAD_STATUS_LABELS.items()]
        out["leads"] = {"rows": rows, "total": sum(r["count"] for r in rows)}
    return out


def _customers(db: Session, start: date, end: date, perms: set[str]) -> dict | None:
    if "sales:read" not in perms and "accounts:read" not in perms:
        return None
    out = {"from": start.isoformat(), "to": end.isoformat(),
           "top": None, "outstanding": None, "credit": None,
           "outstanding_total": None,
           "note": ("Top customers are issued-invoice value in the period. Outstanding "
                    "is today's unpaid balance. Credit in use counts pending, approved "
                    "and dispatched orders; payments are not tracked.")}
    if "sales:read" in perms:
        top = db.execute(
            select(Distributor.id, Distributor.name, func.count(Invoice.id),
                   func.coalesce(func.sum(Invoice.grand_total), 0))
            .join(Invoice, Invoice.distributor_id == Distributor.id)
            .where(Invoice.status == "issued", Invoice.invoice_date >= start,
                   Invoice.invoice_date <= end)
            .group_by(Distributor.id, Distributor.name)
            .order_by(func.sum(Invoice.grand_total).desc(), Distributor.id.asc())
            .limit(LIST_LIMIT)).all()
        out["top"] = [{"distributor_id": did, "name": name,
                       "invoices": int(count), "revenue": _money(revenue)}
                      for did, name, count, revenue in top]

        exposure = {did: Decimal(value) for did, value in db.execute(
            select(SalesOrder.distributor_id,
                   func.coalesce(func.sum(SalesOrder.total), 0))
            .where(SalesOrder.status.in_(EXPOSURE_STATUSES))
            .group_by(SalesOrder.distributor_id)).all()}
        limits = db.execute(
            select(Distributor.id, Distributor.name, Distributor.credit_limit)
            .where(Distributor.credit_limit > 0)).all()
        usage = []
        for did, name, limit in limits:
            used = exposure.get(did, Decimal(0))
            pct = float(used / limit * 100) if limit else None
            usage.append({"distributor_id": did, "name": name,
                          "credit_limit": _money(limit), "exposure": _money(used),
                          "available": _money(max(Decimal(limit) - used, Decimal(0))),
                          "pct_used": round(pct, 1) if pct is not None else None})
        usage.sort(key=lambda r: (-(r["pct_used"] or 0), r["distributor_id"]))
        out["credit"] = usage[:LIST_LIMIT]
    if "accounts:read" in perms:
        totals: dict[int, list] = {}
        for row in ledger.receivable_rows(db):
            if row["outstanding"] <= 0:
                continue
            entry = totals.setdefault(row["distributor_id"],
                                      [row["distributor"], Decimal(0), 0])
            entry[1] += row["outstanding"]
            entry[2] += 1
        rows = sorted(totals.items(),
                      key=lambda item: (-item[1][1], item[0]))[:LIST_LIMIT]
        out["outstanding"] = [{"distributor_id": did, "name": name,
                               "outstanding": _money(amount), "invoices": count}
                              for did, (name, amount, count) in rows]
        out["outstanding_total"] = _money(
            sum((entry[1] for entry in totals.values()), Decimal(0)))
    return out


def _purchasing(db: Session, today: date) -> dict:
    pos = db.execute(select(PurchaseOrder.id,
                            _business_day(PurchaseOrder.created_at))
                     .where(PurchaseOrder.status.in_(OPEN_PO))).all()
    ids = [po_id for po_id, _ in pos]
    values, ordered = {}, {}
    received = {}
    if ids:
        for po_id, qty, cost in db.execute(
                select(PurchaseOrderLine.po_id, PurchaseOrderLine.qty,
                       PurchaseOrderLine.unit_cost)
                .where(PurchaseOrderLine.po_id.in_(ids))).all():
            ordered[po_id] = ordered.get(po_id, Decimal(0)) + Decimal(qty)
            values[po_id] = values.get(po_id, Decimal(0)) + Decimal(qty) * (cost or 0)
        received = {po_id: Decimal(qty) for po_id, qty in db.execute(
            select(GoodsReceipt.po_id, func.coalesce(func.sum(GoodsReceiptLine.qty), 0))
            .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.grn_id)
            .where(GoodsReceipt.po_id.in_(ids))
            .group_by(GoodsReceipt.po_id)).all()}
    buckets = [{"key": key, "label": label, "count": 0, "value": Decimal(0)}
               for key, label, _, _ in PO_AGE_BUCKETS]
    no_receipt = partial = 0
    for po_id, created in pos:
        age = max((today - created).days, 0)
        got = received.get(po_id, Decimal(0))
        if got <= 0:
            no_receipt += 1
        elif got < ordered.get(po_id, Decimal(0)):
            partial += 1
        for bucket, (_, _, first, last) in zip(buckets, PO_AGE_BUCKETS):
            if (first is None or age >= first) and (last is None or age <= last):
                bucket["count"] += 1
                bucket["value"] += values.get(po_id, Decimal(0))
                break
    return {"as_of": today.isoformat(), "open_count": len(pos),
            "no_receipt": no_receipt, "partial": partial,
            "rows": [{"key": b["key"], "label": b["label"], "count": b["count"],
                      "value": _money(b["value"])} for b in buckets],
            "note": ("Age is measured from the order date. No expected delivery date "
                     "is captured (GAP-D05), so lateness against a promise cannot be "
                     "shown.")}


def _corrections(db: Session, start: date, end: date) -> dict:
    def notes(model, label):
        rows = db.execute(
            select(model, Distributor.name, Invoice.invoice_number)
            .join(Distributor, Distributor.id == model.distributor_id)
            .join(Invoice, Invoice.id == model.invoice_id)
            .where(model.status == "issued", model.note_date >= start,
                   model.note_date <= end)
            .order_by(model.note_date.desc(), model.id.desc())).all()
        total = sum((row[0].grand_total or Decimal(0) for row in rows), Decimal(0))
        return {"label": label, "count": len(rows), "value": _money(total),
                "shown": min(len(rows), LIST_LIMIT),
                "rows": [{"number": note.credit_note_number
                          if isinstance(note, CreditNote) else note.debit_note_number,
                          "date": note.note_date.isoformat(),
                          "invoice": invoice_number,
                          "distributor": distributor_name,
                          "reason": note.reason,
                          "total": _money(note.grand_total)}
                         for note, distributor_name, invoice_number
                         in rows[:LIST_LIMIT]]}

    day = _business_day(ApprovalRequest.requested_at)
    rows = db.execute(
        select(ApprovalRequest).where(ApprovalRequest.record_type == "invoice_post_billing",
                                      day >= start, day <= end)
        .order_by(ApprovalRequest.id.desc())).scalars().all()
    statuses = {}
    for row in rows:
        statuses[row.status] = statuses.get(row.status, 0) + 1
    return {"from": start.isoformat(), "to": end.isoformat(),
            "credit_notes": notes(CreditNote, "Credit notes"),
            "debit_notes": notes(DebitNote, "Debit notes"),
            "post_billing": {"count": len(rows),
                             "pending": statuses.get("pending", 0),
                             "shown": min(len(rows), LIST_LIMIT),
                             "rows": [{"request_no": r.request_no,
                                       "document": r.document_number,
                                       "subject": r.subject,
                                       "status": r.status,
                                       "requested_at": (r.requested_at.isoformat()
                                                        if r.requested_at else None),
                                       "decided_at": (r.decided_at.isoformat()
                                                      if r.decided_at else None)}
                                      for r in rows[:LIST_LIMIT]]},
            "note": ("Credit and debit notes are issued money documents. Post-billing "
                     "rows are amendment requests; an issued invoice is never edited.")}


def _hr_today(db: Session, today: date) -> dict:
    counts = dict(db.execute(select(Attendance.status, func.count())
                             .where(Attendance.date == today)
                             .group_by(Attendance.status)).all())
    headcount = db.scalar(select(func.count()).where(Employee.status == "active")) or 0
    marked = sum(int(n) for n in counts.values())
    pending_leave = db.scalar(
        select(func.count()).where(LeaveApplication.status == "pending")) or 0
    pending_od = db.scalar(
        select(func.count()).where(ODRequest.status == "pending")) or 0
    return {"date": today.isoformat(), "headcount": headcount, "marked": marked,
            "not_marked": max(headcount - marked, 0),
            "attendance": [{"status": key, "label": label,
                            "count": int(counts.get(key, 0))}
                           for key, label in ATTENDANCE_LABELS.items()],
            "leave_pending": pending_leave, "od_pending": pending_od,
            "note": ("Attendance is for today. Leave and on-duty counts are "
                     "applications still pending a decision.")}


# ------------------------------------------------------------ drill-down
@router.get("/expiry")
def expiry_list(bucket: Literal["expired", "lt30", "lt90", "all"] = "all",
                page: int = Query(1, ge=1),
                page_size: int = Query(25, ge=1, le=100),
                db: Session = Depends(get_db),
                _=Depends(require("stock:read"))):
    today = date.today()
    total, rows = _expiry_rows(db, today, bucket, page_size,
                               (page - 1) * page_size)
    return {"bucket": bucket, "as_of": today.isoformat(), "total": total,
            "page": page, "page_size": page_size, "rows": rows}


@router.get("/activity")
def activity_feed(limit: int = Query(20, ge=1, le=100),
                  db: Session = Depends(get_db),
                  _=Depends(require("audit:read"))):
    return _activity(db, limit)


# ------------------------------------------------------------ comparison
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December")
COMPARE_MODES = ("full_month", "mtd")


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _shift_month(first: date, months: int) -> date:
    """The first day of a month offset from another month's first day."""
    index = first.year * 12 + (first.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _month_bounds(first: date) -> tuple[date, date]:
    return first, _shift_month(first, 1) - timedelta(days=1)


def _parse_month(month: str | None, today: date) -> date:
    if not month:
        return _month_start(today)
    try:
        parsed = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(422, "month must be written as YYYY-MM")
    if not 2000 <= parsed.year <= 2100:
        raise HTTPException(422, "month is outside the supported range")
    return parsed


def _window_label(start: date, end: date) -> str:
    if start > end:
        return "No days in this window yet"
    if start == end:
        return f"{start.day} {MONTH_NAMES[start.month - 1]} {start.year}"
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.day} {MONTH_NAMES[start.month - 1]} {start.year}"
    return (f"{start.day} {MONTH_NAMES[start.month - 1]} {start.year} – "
            f"{end.day} {MONTH_NAMES[end.month - 1]} {end.year}")


def _compare_windows(mode: str, first: date, today: date) -> dict:
    """The current, previous-month and same-month-last-year windows.

    Full-month compares whole calendar months. Month-to-date compares day 1 to
    the same day number in each comparison month, capped at that month's end.
    """
    month_end = _month_bounds(first)[1]
    prev_first = _shift_month(first, -1)
    prev_end = _month_bounds(prev_first)[1]
    last_first = _shift_month(first, -12)
    last_end = _month_bounds(last_first)[1]
    state = ("future" if first > today else
             "current" if today <= month_end else "past")

    if mode == "full_month":
        current, previous, last_year = ((first, month_end),
                                        (prev_first, prev_end),
                                        (last_first, last_end))
    else:
        if state == "future":
            current = (first, first - timedelta(days=1))
        else:
            current = (first, min(today, month_end))
        elapsed = (current[1].day if current[1] >= current[0] else 0)
        if elapsed == 0:
            previous = (prev_first, prev_first - timedelta(days=1))
            last_year = (last_first, last_first - timedelta(days=1))
        else:
            previous = (prev_first,
                        min(prev_first + timedelta(days=elapsed - 1), prev_end))
            last_year = (last_first,
                         min(last_first + timedelta(days=elapsed - 1), last_end))

    def describe(window: tuple[date, date]) -> dict:
        start, end = window
        return {"from": start.isoformat(), "to": end.isoformat(),
                "days": (end - start).days + 1 if end >= start else 0,
                "label": _window_label(start, end)}

    # Days of the selected month that have actually happened. A full-month window
    # still covers the whole calendar in the figures, but the run rate may only
    # divide by the days elapsed so far.
    elapsed_days = (0 if state == "future" else
                    today.day if state == "current" else month_end.day)
    return {"current": describe(current), "previous": describe(previous),
            "last_year": describe(last_year), "state": state,
            "elapsed_days": elapsed_days, "days_in_month": month_end.day}


def _period_stats(db: Session, start: date, end: date, perms: set[str]) -> dict:
    """Every comparison figure for one window, from the source tables."""
    out = {"sales": Decimal(0), "purchases": Decimal(0), "orders": 0,
           "receipts": 0, "returns": Decimal(0), "return_count": 0, "leads": 0}
    if start > end:
        return out
    if "sales:read" in perms:
        issued = (Invoice.status == "issued", Invoice.invoice_date >= start,
                  Invoice.invoice_date <= end)
        out["sales"] = (db.scalar(select(func.coalesce(func.sum(Invoice.grand_total), 0))
                                  .where(*issued)) or Decimal(0))
        order_day = _business_day(SalesOrder.created_at)
        out["orders"] = db.scalar(select(func.count())
                                  .where(order_day >= start, order_day <= end)) or 0
        returned = (CreditNote.status == "issued", CreditNote.note_date >= start,
                    CreditNote.note_date <= end)
        out["returns"] = (db.scalar(select(func.coalesce(func.sum(CreditNote.grand_total), 0))
                                    .where(*returned)) or Decimal(0))
        out["return_count"] = db.scalar(select(func.count()).where(*returned)) or 0
    if "stock:read" in perms:
        out["purchases"] = sum(_purchases_by_day(db, start, end).values(), Decimal(0))
        receipt_day = _business_day(GoodsReceipt.received_at)
        out["receipts"] = db.scalar(select(func.count())
                                    .where(receipt_day >= start,
                                           receipt_day <= end)) or 0
    if "lead:read" in perms:
        lead_day = _business_day(Lead.created_at)
        out["leads"] = db.scalar(select(func.count())
                                 .where(lead_day >= start, lead_day <= end)) or 0
    return out


def _card(key: str, label: str, unit: str, current, previous, last_year,
          href: str, note: str = "") -> dict:
    return {"key": key, "label": label, "unit": unit,
            "current": current, "previous": previous, "last_year": last_year,
            "previous_change": _change(current, previous),
            "last_year_change": _change(current, last_year),
            "available": True, "gap": None, "href": href, "note": note}


def _unavailable(key: str, label: str, gap: str, note: str) -> dict:
    return {"key": key, "label": label, "unit": "amount",
            "current": None, "previous": None, "last_year": None,
            "previous_change": None, "last_year_change": None,
            "available": False, "gap": gap, "href": "", "note": note}


def _monthly_totals(daily: dict[date, Decimal]) -> dict[tuple[int, int], Decimal]:
    out: dict[tuple[int, int], Decimal] = {}
    for day, value in daily.items():
        key = (day.year, day.month)
        out[key] = out.get(key, Decimal(0)) + Decimal(value)
    return out


def _trend(db: Session, first: date, perms: set[str]) -> dict:
    """Twelve selected months, each beside the same month a year earlier."""
    months = [_shift_month(first, offset - 11) for offset in range(12)]
    window_start = _shift_month(first, -23)
    window_end = _month_bounds(first)[1]
    sales_visible = "sales:read" in perms
    purchases_visible = "stock:read" in perms
    monthly_sales = (_monthly_totals(_sales_by_day(db, window_start, window_end))
                     if sales_visible else {})
    monthly_purchases = (_monthly_totals(_purchases_by_day(db, window_start, window_end))
                         if purchases_visible else {})

    def month_key(day: date) -> tuple[int, int]:
        return day.year, day.month

    rows = []
    for index, month in enumerate(months):
        prior = _shift_month(month, -12)
        current_sales = monthly_sales.get(month_key(month), Decimal(0)) if sales_visible else None
        prior_sales = monthly_sales.get(month_key(prior), Decimal(0)) if sales_visible else None
        moving = None
        if sales_visible:
            span = months[max(0, index - 2):index + 1]
            values = [monthly_sales.get(month_key(m), Decimal(0)) for m in span]
            moving = _money(sum(values, Decimal(0)) / len(values))
        rows.append({
            "month": f"{month:%Y-%m}", "label": f"{month:%b %Y}",
            "sales": (_money(current_sales) if sales_visible else None),
            "purchases": (_money(monthly_purchases.get(month_key(month), Decimal(0)))
                          if purchases_visible else None),
            "prior_sales": (_money(prior_sales) if sales_visible else None),
            "prior_purchases": (_money(monthly_purchases.get(month_key(prior), Decimal(0)))
                                if purchases_visible else None),
            "moving_average": moving,
            "yoy_change": (_change(current_sales, prior_sales) if sales_visible else None),
        })

    def extreme(pick) -> dict | None:
        if not sales_visible:
            return None
        measured = [r for r in rows if Decimal(r["sales"] or 0) > 0]
        if not measured:
            return None
        row = pick(measured, key=lambda r: Decimal(r["sales"]))
        return {"month": row["month"], "label": row["label"], "sales": row["sales"]}

    selected_sales = monthly_sales.get(month_key(first), Decimal(0)) if sales_visible else Decimal(0)
    previous_sales = (monthly_sales.get(month_key(_shift_month(first, -1)), Decimal(0))
                      if sales_visible else Decimal(0))
    last_year_sales = (monthly_sales.get(month_key(_shift_month(first, -12)), Decimal(0))
                       if sales_visible else Decimal(0))
    selected_purchases = (monthly_purchases.get(month_key(first), Decimal(0))
                          if purchases_visible else Decimal(0))
    previous_purchases = (monthly_purchases.get(month_key(_shift_month(first, -1)), Decimal(0))
                          if purchases_visible else Decimal(0))
    last_year_purchases = (monthly_purchases.get(month_key(_shift_month(first, -12)), Decimal(0))
                           if purchases_visible else Decimal(0))

    seasons = []
    if sales_visible:
        for row in rows:
            current = Decimal(row["sales"] or 0)
            prior = Decimal(row["prior_sales"] or 0)
            seasons.append({
                "month": row["month"], "label": row["label"][:3],
                "current": row["sales"], "prior_year": row["prior_sales"],
                "index": (round(float(current / prior), 2) if prior > 0 else None)})

    return {
        "months": rows,
        "sales_visible": sales_visible, "purchases_visible": purchases_visible,
        "best": extreme(max), "worst": extreme(min),
        "growth": {
            "sales": {"current": _money(selected_sales),
                      "previous": _money(previous_sales),
                      "last_year": _money(last_year_sales),
                      "mom": _change(selected_sales, previous_sales),
                      "yoy": _change(selected_sales, last_year_sales)},
            "purchases": {"current": _money(selected_purchases),
                          "previous": _money(previous_purchases),
                          "last_year": _money(last_year_purchases),
                          "mom": _change(selected_purchases, previous_purchases),
                          "yoy": _change(selected_purchases, last_year_purchases)},
        },
        "seasonality": seasons,
        "note": ("A three-month moving average smooths one-off months. The "
                 "seasonality index is this year divided by the same calendar "
                 "month last year; with one prior year it is a comparison, not a "
                 "fitted seasonal model."),
    }


def _projection(stats: dict, windows: dict, perms: set[str]) -> dict:
    sales = Decimal(stats["sales"])
    purchases = Decimal(stats["purchases"])
    month_days = windows["days_in_month"]
    state = windows["state"]

    def pack(s, p, **rest) -> dict:
        return {"sales": _money(s) if "sales:read" in perms else None,
                "purchases": _money(p) if "stock:read" in perms else None, **rest}

    if state == "future":
        return pack(Decimal(0), Decimal(0), is_estimate=False, complete=False,
                    state=state, elapsed_days=0, days_in_month=month_days,
                    label="Not started",
                    note="The month has not started yet, so there is nothing to project.")
    if state == "past":
        return pack(sales, purchases, is_estimate=False, complete=True,
                    state=state, elapsed_days=month_days,
                    days_in_month=month_days, label="Complete month",
                    note="The month is complete, so the projection is the recorded total.")
    elapsed = max(windows["elapsed_days"], 1)
    factor = Decimal(month_days) / Decimal(elapsed)
    return pack(sales * factor, purchases * factor, is_estimate=True, complete=False,
                state=state, elapsed_days=elapsed, days_in_month=month_days,
                label="Run-rate estimate (not a forecast)",
                note=(f"The month-to-date total projected from {elapsed} of "
                      f"{month_days} days at the current run rate. Actual trading "
                      "may differ; this is an estimate, not a forecast."))


def _grouped_sales(db: Session, start: date, end: date,
                   group_column, label_column, label_join=None) -> dict:
    if start > end:
        return {}
    stmt = (select(group_column, label_column,
                   func.coalesce(func.sum(InvoiceLine.taxable_value), 0))
            .select_from(InvoiceLine)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(Invoice.status == "issued", Invoice.invoice_date >= start,
                   Invoice.invoice_date <= end)
            .group_by(group_column, label_column))
    if label_join is not None:
        stmt = stmt.join(*label_join)
    return {row[0]: (row[1], Decimal(row[2])) for row in db.execute(stmt).all()}


def _breakdowns(db: Session, current: dict, previous: dict,
                perms: set[str]) -> dict | None:
    if "sales:read" not in perms:
        return None
    start, end = date.fromisoformat(current["from"]), date.fromisoformat(current["to"])
    prev_start, prev_end = (date.fromisoformat(previous["from"]),
                            date.fromisoformat(previous["to"]))

    def build(group_column, label_column, combine, label_join=None) -> dict:
        now = _grouped_sales(db, start, end, group_column, label_column, label_join)
        before = _grouped_sales(db, prev_start, prev_end, group_column,
                                label_column, label_join)
        ranked = sorted(now.items(), key=lambda item: item[1][1], reverse=True)[:5]
        total = sum((value for _, value in now.values()), Decimal(0))
        return {"rows": [{
            "key": str(key), "label": combine(label),
            "current": _money(value),
            "previous": _money(before.get(key, (None, Decimal(0)))[1]),
            "change": _change(value, before.get(key, (None, Decimal(0)))[1]),
            "share": round(float(value / total * 100), 1) if total > 0 else None,
        } for key, (label, value) in ranked],
            "previous_from": previous["from"], "previous_to": previous["to"]}

    return {
        "sales_by_product": {
            **build(InvoiceLine.product_id,
                   func.concat(InvoiceLine.sku, " · ", InvoiceLine.product_name),
                   lambda label: label or "Unnamed product"),
            "note": ("Top 5 products by taxable value (before GST) in the selected "
                     "window; the previous column uses the comparable window.")},
        "sales_by_distributor": {
            **build(Invoice.distributor_id, Distributor.name,
                   lambda label: label or "Unnamed distributor",
                   (Distributor, Distributor.id == Invoice.distributor_id)),
            "note": ("Top 5 distributors by taxable value (before GST) in the "
                     "selected window; the previous column uses the comparable "
                     "window.")},
    }


@router.get("/compare")
def compare(mode: str = "full_month", month: str | None = None,
            db: Session = Depends(get_db), user=Depends(require_login)):
    """Month-on-month and year-on-year figures for one explicit mode."""
    if mode not in COMPARE_MODES:
        raise HTTPException(422, "mode must be full_month or mtd")
    perms = role_permissions(db, user)
    today = date.today()
    first = _parse_month(month, today)
    windows = _compare_windows(mode, first, today)

    key = (user.id, tuple(sorted(perms)), "compare", mode, first.isoformat(),
           _CACHE_GENERATION)
    now = datetime.now(timezone.utc).timestamp()
    if _cache_enabled(db):
        hit = _CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]

    stats = {name: _period_stats(db, date.fromisoformat(window["from"]),
                                 date.fromisoformat(window["to"]), perms)
             for name, window in (("current", windows["current"]),
                                  ("previous", windows["previous"]),
                                  ("last_year", windows["last_year"]))}
    cur, prev, last = stats["current"], stats["previous"], stats["last_year"]

    cards = []
    if "sales:read" in perms:
        cards.append(_card(
            "sales", "Sales (issued invoices)", "amount",
            _money(cur["sales"]), _money(prev["sales"]), _money(last["sales"]),
            "#/billing", "Issued tax invoices, including GST."))
    if "stock:read" in perms:
        cards.append(_card(
            "purchases", "Purchases (goods received)", "amount",
            _money(cur["purchases"]), _money(prev["purchases"]),
            _money(last["purchases"]), "#/purchasing",
            "Goods receipts valued at the purchase-order cost; a line without a "
            "price counts as zero."))
    if "sales:read" in perms:
        cards.append(_card(
            "orders", "Sales orders raised", "count",
            cur["orders"], prev["orders"], last["orders"], "#/sales",
            "Every order created in the window, whatever its status today."))
        cards.append(_unavailable(
            "gross_margin", "Gross margin", "GAP-D04",
            "No batch cost or invoice-line cost is stored, so margin cannot be "
            "computed without inventing a cost."))
    if "stock:read" in perms:
        cards.append(_card(
            "receipts", "Goods receipts posted", "count",
            cur["receipts"], prev["receipts"], last["receipts"], "#/purchasing",
            "Goods receipt notes posted in the window."))
    if "sales:read" in perms:
        cards.append(_card(
            "returns", "Returns (credit notes)", "amount",
            _money(cur["returns"]), _money(prev["returns"]),
            _money(last["returns"]), "#/billing",
            f"{cur['return_count']} issued credit note"
            f"{'' if cur['return_count'] == 1 else 's'} in the selected window."))
    if "lead:read" in perms:
        cards.append(_card(
            "new_leads", "New leads", "count",
            cur["leads"], prev["leads"], last["leads"], "#/leads",
            "Leads created in the window."))
    if "sales:read" in perms:
        cards.append(_unavailable(
            "new_customers", "New customers", "GAP-V16",
            "Distributors carry no creation timestamp, so a customer cannot be "
            "dated as new in a period."))

    out = {
        "mode": mode, "month": f"{first:%Y-%m}",
        "month_label": f"{MONTH_NAMES[first.month - 1]} {first.year}",
        "month_state": windows["state"],
        "ranges": {"current": windows["current"],
                   "previous": windows["previous"],
                   "last_year": windows["last_year"],
                   "mode": mode, "state": windows["state"],
                   "elapsed_days": windows["elapsed_days"],
                   "days_in_month": windows["days_in_month"]},
        "cards": cards,
        "trend": _trend(db, first, perms),
        "projection": _projection(cur, windows, perms),
        "breakdowns": _breakdowns(db, windows["current"], windows["previous"], perms),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notes": [
            ("Each card compares the selected window with the previous calendar "
             "month and with the same month last year."),
            ("Month-to-date windows end on the same day number in each comparison "
             "month, capped at that month's last day."),
            ("Gross margin and new customers are shown as gaps because the "
             "database holds no cost and no customer creation date."),
        ],
    }
    if _cache_enabled(db):
        _CACHE[key] = (now + DASHBOARD_TTL_SECONDS, out)
    return out


# --------------------------------------------------------------- geography
GEO_REASON_CAP = 5


def _geo_state_column():
    """The invoice's frozen buyer state, with the master as a last resort.

    Issued invoices always store the state snapshot at issue time. The
    distributor's current state is used only for a row that predates the
    snapshot, which is why it is a coalesce and not the primary source.
    """
    return func.coalesce(Invoice.buyer_state_code, Distributor.state_code)


def _geo_states(db: Session, start: date, end: date) -> list[dict]:
    if start > end:
        return []
    code = _geo_state_column()
    rows = db.execute(
        select(code.label("code"),
               func.count(Invoice.id),
               func.count(func.distinct(Invoice.distributor_id)),
               func.coalesce(func.sum(Invoice.grand_total), 0),
               func.coalesce(func.sum(Invoice.taxable_value), 0),
               func.coalesce(func.sum(Invoice.cgst_total), 0),
               func.coalesce(func.sum(Invoice.sgst_total), 0),
               func.coalesce(func.sum(Invoice.igst_total), 0),
               func.coalesce(func.sum(Invoice.cess_total), 0),
               func.coalesce(func.sum(Invoice.tax_total), 0))
        .select_from(Invoice)
        .join(Distributor, Distributor.id == Invoice.distributor_id)
        .where(Invoice.status == "issued", Invoice.invoice_date >= start,
               Invoice.invoice_date <= end)
        .group_by(code)).all()
    out = []
    for row in rows:
        raw_code = row[0]
        state_code = str(raw_code).zfill(2) if raw_code else None
        name = state_name(state_code) if state_code else None
        out.append({
            "code": state_code,
            "key": state_code or "unrecorded",
            "name": name or ("Location not recorded" if not state_code
                             else f"Unknown state ({state_code})"),
            "known": bool(name),
            "recorded": bool(state_code),
            "invoice_count": int(row[1]),
            "customers": int(row[2]),
            "_sales": Decimal(row[3]),
            "_taxable": Decimal(row[4]),
            "_cgst": Decimal(row[5]),
            "_sgst": Decimal(row[6]),
            "_igst": Decimal(row[7]),
            "_cess": Decimal(row[8]),
            "_tax": Decimal(row[9]),
        })
    return out


def _geo_returns(db: Session, start: date, end: date) -> dict[str, dict]:
    """Issued credit notes in the window, grouped by the invoice's buyer state."""
    if start > end:
        return {}
    code = _geo_state_column()
    rows = db.execute(
        select(code, CreditNote.grand_total, CreditNote.reason)
        .select_from(CreditNote)
        .join(Invoice, Invoice.id == CreditNote.invoice_id)
        .join(Distributor, Distributor.id == Invoice.distributor_id)
        .where(CreditNote.status == "issued", CreditNote.note_date >= start,
               CreditNote.note_date <= end)).all()
    grouped: dict[str, dict] = {}
    for raw_code, total, reason in rows:
        state_code = str(raw_code).zfill(2) if raw_code else "unrecorded"
        entry = grouped.setdefault(state_code, {"value": Decimal(0), "count": 0,
                                                "reasons": {}})
        entry["value"] += Decimal(total or 0)
        entry["count"] += 1
        text = (reason or "").strip()
        if text:
            entry["reasons"][text] = entry["reasons"].get(text, 0) + 1
    return grouped


def _geo_count_snapshot(db: Session, start: date, end: date) -> tuple[int, int]:
    if start > end:
        return 0, 0
    base = (Invoice.status == "issued", Invoice.invoice_date >= start,
            Invoice.invoice_date <= end)
    snapshot = db.scalar(select(func.count()).select_from(Invoice)
                         .where(*base, Invoice.buyer_state_code.is_not(None))) or 0
    missing = db.scalar(select(func.count()).select_from(Invoice)
                        .where(*base, Invoice.buyer_state_code.is_(None))) or 0
    return int(snapshot), int(missing)


def _geo_row(row: dict, total_sales: Decimal, with_tax: bool,
             returns: dict | None) -> dict:
    out = {
        "code": row["code"], "key": row["key"], "name": row["name"],
        "known": row["known"], "recorded": row["recorded"],
        "invoice_count": row["invoice_count"], "customers": row["customers"],
        "sales": _money(row["_sales"]),
        "share": (round(float(row["_sales"] / total_sales * 100), 2)
                  if total_sales > 0 else None),
    }
    if with_tax:
        out.update({
            "taxable": _money(row["_taxable"]), "cgst": _money(row["_cgst"]),
            "sgst": _money(row["_sgst"]), "igst": _money(row["_igst"]),
            "cess": _money(row["_cess"]), "tax": _money(row["_tax"]),
        })
    if returns is not None:
        entry = returns.get(row["key"], {"value": Decimal(0), "count": 0,
                                         "reasons": {}})
        reasons = sorted(entry["reasons"].items(), key=lambda item: (-item[1], item[0]))
        out["return_value"] = _money(entry["value"])
        out["return_count"] = entry["count"]
        out["reasons"] = [text for text, _ in reasons[:GEO_REASON_CAP]]
        out["reasons_total"] = len(reasons)
    return out


def _geo_rank(rows: list[dict]) -> list[dict]:
    return [{
        "code": r["code"], "key": r["key"], "name": r["name"],
        "sales": r["sales"], "invoice_count": r["invoice_count"],
        "share": r["share"],
    } for r in rows]


@router.get("/geo")
def geography(from_date: date | None = None, to_date: date | None = None,
              db: Session = Depends(get_db), user=Depends(require("sales:read"))):
    """Sales, returns and GST by the invoice's frozen buyer state."""
    perms = role_permissions(db, user)
    today = date.today()
    start, end, days = _period(from_date, to_date, None, today)

    key = (user.id, tuple(sorted(perms)), "geo", start, end, _CACHE_GENERATION)
    now = datetime.now(timezone.utc).timestamp()
    if _cache_enabled(db):
        hit = _CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]

    with_tax = "tax:read" in perms
    returns = _geo_returns(db, start, end) if "accounts:read" in perms else None
    rows = _geo_states(db, start, end)
    total_sales = sum((r["_sales"] for r in rows), Decimal(0))
    total_taxable = sum((r["_taxable"] for r in rows), Decimal(0))
    total_tax = sum((r["_tax"] for r in rows), Decimal(0))
    total_invoices = sum(r["invoice_count"] for r in rows)

    ordered = sorted(rows, key=lambda r: (r["_sales"], r["name"]), reverse=True)
    serialized = [_geo_row(r, total_sales, with_tax, returns) for r in ordered]
    recorded = [r for r in serialized if r["recorded"]]
    positive = [r for r in serialized if Decimal(r["sales"]) > 0]
    bottom = list(reversed(positive))[:5]
    unrecorded_row = next((r for r in serialized if not r["recorded"]), None)
    snapshot, missing = _geo_count_snapshot(db, start, end)

    mapped = []
    for state_code in sorted(STATE_CODES):
        found = next((r for r in serialized if r["code"] == state_code), None)
        mapped.append({
            "code": state_code, "name": state_name(state_code),
            "recorded": bool(found),
            "sales": found["sales"] if found else "0.00",
            "share": found["share"] if found else None,
        })

    returns_out = None
    if returns is not None:
        entries = []
        for r in serialized:
            entry = returns.get(r["key"])
            if not entry:
                continue
            reasons = sorted(entry["reasons"].items(),
                             key=lambda item: (-item[1], item[0]))
            entries.append({
                "code": r["code"], "key": r["key"], "name": r["name"],
                "value": _money(entry["value"]), "count": entry["count"],
                "reasons": [text for text, _ in reasons[:GEO_REASON_CAP]],
                "reasons_total": len(reasons),
            })
        total_return_value = sum((returns[r["key"]]["value"] for r in serialized
                                  if r["key"] in returns), Decimal(0))
        returns_out = {
            "available": True,
            "rows": entries,
            "value": _money(total_return_value),
            "count": sum(e["count"] for e in entries),
            "reason_cap": GEO_REASON_CAP,
            "gap": "GAP-V10",
            "note": ("Return value and count come from issued credit notes grouped "
                     "by the invoice's buyer state. Reasons are the free text "
                     "recorded on each note; no categories are invented."),
        }
    else:
        returns_out = {
            "available": False, "gap": "accounts:read",
            "note": ("Returns are read from credit notes, so they need "
                     "accounts:read. Your role does not have it."),
        }

    if with_tax:
        gst_out = {
            "available": True,
            "rows": [{"code": r["code"], "key": r["key"], "name": r["name"],
                      "taxable": r["taxable"], "cgst": r["cgst"],
                      "sgst": r["sgst"], "igst": r["igst"], "cess": r["cess"],
                      "tax": r["tax"]} for r in serialized if r["recorded"]],
            "taxable": _money(total_taxable), "tax": _money(total_tax),
            "note": ("Amounts as printed on issued invoices: taxable value before "
                     "GST and the tax split actually charged. This is not a "
                     "statutory filing export."),
        }
    else:
        gst_out = {
            "available": False, "gap": "tax:read",
            "note": ("The GST split comes from invoice tax snapshots and needs "
                     "tax:read. Your role does not have it."),
        }

    notes = [
        ("State is the buyer state frozen on the issued invoice, so a later "
         "change to the distributor master cannot move a past sale."),
        (f"Invoices carrying a state snapshot: {snapshot}. "
         f"Falling back to the distributor master: {missing}."),
        ("District, city and pincode are not captured on invoices or distributors "
         "(GAP-V11), so this page stops at state and does not guess."),
        ("The free-text distributor territory is not used as a geographic key "
         "(GAP-V12); the GST state code is."),
        ("There is no territory-scoped user model, so every user with sales:read "
         "sees every state in their permitted figures (D-14)."),
    ]
    out = {
        "from": start.isoformat(), "to": end.isoformat(), "days": days,
        "range_label": _window_label(start, end),
        "basis": {
            "snapshot": snapshot,
            "fallback": max(missing - (unrecorded_row["invoice_count"]
                                       if unrecorded_row else 0), 0),
            "unrecorded": unrecorded_row["invoice_count"] if unrecorded_row else 0,
            "invoices": total_invoices,
        },
        "totals": {
            "sales": _money(total_sales), "invoice_count": total_invoices,
            "states": len(recorded),
            "taxable": _money(total_taxable) if with_tax else None,
            "tax": _money(total_tax) if with_tax else None,
            "returns": returns_out.get("value") if returns is not None else None,
            "return_count": returns_out.get("count") if returns is not None else None,
        },
        "levels": [
            {"level": "state", "available": True, "gap": None,
             "note": "Sold by the buyer state on the invoice."},
            {"level": "district", "available": False, "gap": "GAP-V11",
             "note": "Not recorded on invoices or distributors."},
            {"level": "city", "available": False, "gap": "GAP-V11",
             "note": "Not recorded on invoices or distributors."},
            {"level": "pincode", "available": False, "gap": "GAP-V11",
             "note": "Not recorded on invoices or distributors."},
        ],
        "states": serialized,
        "top": _geo_rank(serialized[:5]),
        "bottom": _geo_rank(bottom),
        "map": mapped,
        "unrecorded": unrecorded_row,
        "returns": returns_out,
        "gst": gst_out,
        "notes": notes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if _cache_enabled(db):
        _CACHE[key] = (now + DASHBOARD_TTL_SECONDS, out)
    return out


# ------------------------------------------------------------ dashboard
def _period(from_date: date | None, to_date: date | None,
            range_days: int | None, today: date) -> tuple[date, date, int]:
    """The selected window. Dates win over the legacy range parameter."""
    if from_date or to_date:
        end = to_date or today
        start = from_date or end.replace(day=1)
        if end > today:
            raise HTTPException(422, "to_date cannot be in the future")
        if start > end:
            raise HTTPException(422, "from_date cannot be after to_date")
        return start, end, (end - start).days + 1
    if range_days is None:
        # No dates and no legacy range: the current month is the default.
        return today.replace(day=1), today, today.day
    if range_days not in RANGE_CHOICES:
        raise HTTPException(422, "range must be one of 7, 30 or 90")
    return today - timedelta(days=range_days - 1), today, range_days


@router.get("")
def dashboard(from_date: date | None = None, to_date: date | None = None,
              range_days: int | None = Query(None, alias="range"),
              db: Session = Depends(get_db), user=Depends(require_login)):
    perms = role_permissions(db, user)
    today = date.today()
    start, end, days = _period(from_date, to_date, range_days, today)
    admin = is_admin(db, user)

    key = (user.id, tuple(sorted(perms)), start, end, admin, _CACHE_GENERATION)
    now = datetime.now(timezone.utc).timestamp()
    if _cache_enabled(db):
        hit = _CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]

    out = {"as_of": today.isoformat(), "range": days,
           "from": start.isoformat(), "to": end.isoformat(),
           "generated_at": datetime.now(timezone.utc).isoformat(),
           # legacy sections, unchanged for existing callers
           "stock": None, "purchase_orders": None, "active_products": None,
           "orders_ready": None, "approvals_waiting": None, "leads": None,
           "warehouse_count": None,
           # phase 2 sections
           "kpis": [], "attention": [], "sales_vs_purchases": None,
           "receivables_ageing": None, "stock_by_warehouse": None,
           "expiry_watch": None, "open_pos": None, "approvals": None,
           "top_products": None, "category_sales": None,
           "recent_activity": None, "health": _health(db)}

    stock = _stock(db, today) if "stock:read" in perms else None
    pos = _purchase_orders(db, start, end) if "stock:read" in perms else None
    # Ageing is measured at the end of the selected window, so it agrees with
    # the Receivables Ageing report asked for the same date.
    ageing = ledger.ageing_rows(db, end) if "accounts:read" in perms else None
    if stock is not None:
        out["stock"] = stock
        out["purchase_orders"] = pos
        out["warehouse_count"] = db.scalar(select(func.count()).select_from(Warehouse)) or 0
    if "product:read" in perms:
        out["active_products"] = db.scalar(
            select(func.count()).where(Product.status == "active")) or 0
    if "sales:read" in perms:
        out["orders_ready"] = db.scalar(
            select(func.count()).where(SalesOrder.status == "approved")) or 0
    if "approval:read" in perms:
        out["approvals_waiting"] = len(_visible_pending(db, user, perms))
    if "lead:read" in perms:
        out["leads"] = _leads(db, today)

    # ---- KPI tiles, with a trend only where history is derivable
    history = _stock_history(db, start, end) if stock is not None else None
    counts = _expiry_counts(db, today) if stock is not None else None

    def tile(key_: str, label: str, value, href: str, note: str = "",
             trend: list | None = None, trend_points: list | None = None,
             trend_note: str | None = None):
        out["kpis"].append({"key": key_, "label": label, "value": value,
                            "href": href, "note": note, "trend": trend,
                            "trend_points": trend_points,
                            "trend_note": trend_note})

    if stock is not None:
        tile("units_on_hand", "Units on hand", stock["units_on_hand"],
             "#/inventory/stock", "Across every warehouse, as of today.",
             history["units"], history["points"],
             f"Daily position, {start:%d %b} to {end:%d %b}.")
        tile("batches_in_stock", "Batches in stock", stock["batches_in_stock"],
             "#/inventory/stock", "Batches with a positive balance, as of today.",
             history["batches"], history["points"],
             f"Batches on hand, {start:%d %b} to {end:%d %b}.")
        tile("expiring", "Expiring ≤90 days", stock["expiring_count"],
             "#/inventory/stock",
             f"{counts['expired']} already expired · {counts['lt30']} within 30 days",
             history["expiring"], history["points"],
             "Batches on hand whose expiry falls within 90 days.")
    if pos is not None:
        tile("po_awaiting", "POs awaiting goods", pos["open_count"],
             "#/purchasing", "Open or part received, as of today.",
             trend_note="No history yet: order status has no stored timeline.")
    if out["orders_ready"] is not None:
        tile("orders_ready", "Orders ready to dispatch", out["orders_ready"],
             "#/sales", "Approved and not yet dispatched, as of today.",
             trend_note="No history yet: approval time is not stored on the order.")
    if out["approvals_waiting"] is not None:
        tile("approvals_waiting", "Approvals waiting", out["approvals_waiting"],
             "#/approvals", "Requests still pending a decision, as of today.",
             trend_note="No history yet: withdrawals have no decision timestamp.")
    if out["leads"] is not None:
        tile("followups_overdue", "Follow-ups overdue", out["leads"]["overdue"],
             "#/followups", f"{out['leads']['due_today']} due today.",
             trend_note="No history yet: only the current follow-up date is stored.")
    if out["active_products"] is not None:
        tile("active_products", "Active products", out["active_products"],
             "#/products", "Status active, as of today.",
             trend_note="No history yet: products carry no creation timestamp.")

    out["attention"] = _attention(db, user, perms, today, stock, ageing)

    if "sales:read" in perms or "stock:read" in perms:
        chart = _sales_purchases(db, start, end)
        sales_visible = "sales:read" in perms
        purchases_visible = "stock:read" in perms
        # One chart serves two permissions. Mask the side the caller cannot see
        # rather than trusting the browser to hide a value it was sent.
        if not sales_visible:
            chart["sales_total"] = chart["sales_change"] = None
            for point in chart["series"]:
                point["sales"] = None
        if not purchases_visible:
            chart["purchases_total"] = chart["purchases_change"] = None
            for point in chart["series"]:
                point["purchases"] = None
        chart["sales_visible"] = sales_visible
        chart["purchases_visible"] = purchases_visible
        out["sales_vs_purchases"] = chart
    if ageing is not None:
        out["receivables_ageing"] = {
            "as_of": ageing["as_of"].isoformat(),
            "buckets": [{"key": b["key"], "label": b["label"],
                         "amount": _money(b["total"]), "count": b["count"]}
                        for b in ageing["buckets"]],
            "total": _money(ageing["total"]), "count": ageing["count"],
            "note": "Same figures as the Receivables Ageing report."}
    if stock is not None:
        out["stock_by_warehouse"] = _stock_by_warehouse(db)
        out["expiry_watch"] = _expiry_watch(db, today)
        out["open_pos"] = {"count": pos["in_range_count"],
                           "open_total": pos["open_count"],
                           "from": pos["from"], "to": pos["to"],
                           "rows": pos["open"],
                           "shown": len(pos["open"]),
                           "note": ("Open orders raised in the selected period. "
                                    "Progress is by quantity received.")}
    if "approval:read" in perms:
        out["approvals"] = _approvals_section(db, user, perms)
    if "sales:read" in perms:
        out["top_products"] = _top_products(db, start, end)
        out["category_sales"] = {
            "available": False, "gap": "GAP-D01",
            "note": "No product category or brand is captured, so sales cannot be "
                    "grouped by category without inventing one."}
    if "audit:read" in perms:
        out["recent_activity"] = _activity(db, start=start, end=end)

    out["insights"] = {
        "pipeline": _pipeline(db, perms),
        "customers": _customers(db, start, end, perms),
        "purchasing": _purchasing(db, today) if stock is not None else None,
        "corrections": _corrections(db, start, end) if "sales:read" in perms else None,
        "hr": _hr_today(db, today) if "hr:read" in perms else None,
    }

    if _cache_enabled(db):
        _CACHE[key] = (now + DASHBOARD_TTL_SECONDS, out)
    return out
