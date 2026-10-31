"""Accounts reporting: what the documents can prove, and what they cannot.

There is no chart of accounts, no expense table, no purchase-side tax, no due
date on an invoice and no period lock. This module therefore computes revenue,
collections, returns, outstanding and ageing, payables, output GST, credit use,
cash/bank movement and the derived trial balance. Everything else is returned as
an unavailable metric with a gap code, so a screen or an email can say
"No data yet" instead of inventing a figure.

Payables are measured as at a date: the cost of goods received on or before it,
minus payments made on or before it. A supplier's `payment_terms_days` is used
to estimate when an outstanding balance falls due; the terms are today's master
value, not a snapshot on the purchase order, and the note says so.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.orm import Session

from ..core.rules import REPORT_TZ
from ..models.accounts import Payment
from ..models.core import (CreditNote, DebitNote, Distributor, Invoice, PurchaseOrder,
                           PurchaseOrderLine, SalesOrder)
from ..models.suppliers import GoodsReceipt, GoodsReceiptLine, Supplier
from . import ledger
from .sales import EXPOSURE_STATUSES

ZERO = Decimal("0.00")

GAPS = (
    ("GAP-A01", "Expenses and expense heads",
     "No expense table or head exists, so expenses and an expense-by-head breakdown cannot be reported."),
    ("GAP-A02", "Cost of goods, gross profit and net profit",
     "Stock and invoice lines carry no cost, and expenses are not captured. Gross and net profit are not computed."),
    ("GAP-A03", "Financial-year and period locks",
     "No lock date is stored on any document. Every dated record is reported as recorded; no period is treated as locked."),
    ("GAP-A04", "Invoice due dates",
     "An invoice carries no due date. Payables due dates are estimated from the supplier's current payment terms and the latest receipt."),
    ("GAP-A05", "Input GST and net GST payable",
     "Purchase-side tax is not captured. Only output GST is reported; a net payable figure would be incomplete."),
    ("GAP-A06", "GSTR-1 / GSTR-3B reconciliation",
     "No filed return is stored, so no reconciliation with a return can be shown."),
    ("GAP-A07", "TDS and other statutory dues",
     "No TDS section, deduction or challan is recorded."),
    ("GAP-A08", "Vouchers, journal and day book",
     "Money movements are recorded as receipts and payments only; there is no voucher or posting state."),
    ("GAP-A09", "Bank reconciliation",
     "No bank statement or reconciliation record exists."),
    ("GAP-A10", "Opening balances and balance sheet",
     "Opening cash, bank and capital balances are not captured, so a balance sheet and a closing cash balance cannot be produced."),
)

UNAVAILABLE = (
    ("expenses", "Expenses", "GAP-A01", "No expense record exists."),
    ("gross_profit", "Gross profit", "GAP-A02", "Cost of goods is not captured."),
    ("net_profit", "Net profit", "GAP-A02", "Cost and expenses are not captured."),
    ("balance_sheet", "Balance sheet", "GAP-A10", "Opening balances and assets are not captured."),
    ("input_gst", "Input GST / net payable", "GAP-A05", "Purchase-side tax is not captured."),
    ("tds", "TDS and statutory dues", "GAP-A07", "No TDS record exists."),
    ("bank_reconciliation", "Bank reconciliation", "GAP-A09", "No bank statement is recorded."),
)


def _s(value) -> str:
    return str((Decimal(value or 0)).quantize(Decimal("0.01")))


def _business_day(column):
    return cast(func.timezone(REPORT_TZ, column), Date)


def _change(current, previous) -> float | None:
    current, previous = Decimal(current or 0), Decimal(previous or 0)
    if previous == 0:
        return None
    return round(float((current - previous) / previous * 100), 1)


def window(db: Session, start: date, end: date, as_of: date | None = None) -> dict:
    """Every Accounts figure for one window. Snapshot figures use `as_of`."""
    as_of = as_of or end
    empty = start > end
    revenue = {"taxable": ZERO, "gross": ZERO, "discount": ZERO, "invoices": 0}
    returns = {"value": ZERO, "count": 0}
    debits = {"value": ZERO, "count": 0}
    gst = {"cgst": ZERO, "sgst": ZERO, "igst": ZERO, "cess": ZERO, "total": ZERO}
    collections = {"total": ZERO, "cash": ZERO, "bank": ZERO, "count": 0}
    paid_out = {"total": ZERO, "cash": ZERO, "bank": ZERO, "count": 0}

    if not empty:
        row = db.execute(
            select(func.count(Invoice.id),
                   func.coalesce(func.sum(Invoice.taxable_value), 0),
                   func.coalesce(func.sum(Invoice.grand_total), 0),
                   func.coalesce(func.sum(Invoice.discount_total), 0),
                   func.coalesce(func.sum(Invoice.cgst_total), 0),
                   func.coalesce(func.sum(Invoice.sgst_total), 0),
                   func.coalesce(func.sum(Invoice.igst_total), 0),
                   func.coalesce(func.sum(Invoice.cess_total), 0),
                   func.coalesce(func.sum(Invoice.tax_total), 0))
            .where(Invoice.status == "issued", Invoice.invoice_date >= start,
                   Invoice.invoice_date <= end)).one()
        revenue = {"taxable": Decimal(row[1]), "gross": Decimal(row[2]),
                   "discount": Decimal(row[3]), "invoices": int(row[0])}
        gst = {"cgst": Decimal(row[4]), "sgst": Decimal(row[5]),
               "igst": Decimal(row[6]), "cess": Decimal(row[7]),
               "total": Decimal(row[8])}

        r = db.execute(select(func.count(CreditNote.id),
                              func.coalesce(func.sum(CreditNote.grand_total), 0))
                       .where(CreditNote.status == "issued",
                              CreditNote.note_date >= start,
                              CreditNote.note_date <= end)).one()
        returns = {"value": Decimal(r[1]), "count": int(r[0])}
        d = db.execute(select(func.count(DebitNote.id),
                              func.coalesce(func.sum(DebitNote.grand_total), 0))
                       .where(DebitNote.status == "issued",
                              DebitNote.note_date >= start,
                              DebitNote.note_date <= end)).one()
        debits = {"value": Decimal(d[1]), "count": int(d[0])}

        pay = db.execute(
            select(func.count(), func.coalesce(func.sum(Payment.amount), 0),
                   func.coalesce(func.sum(case(
                       (Payment.mode == "cash", Payment.amount), else_=0)), 0))
            .where(Payment.kind == "receipt", Payment.paid_on >= start,
                   Payment.paid_on <= end)).one()
        collections = {"total": Decimal(pay[1]), "cash": Decimal(pay[2]),
                       "bank": Decimal(pay[1]) - Decimal(pay[2]), "count": int(pay[0])}
        out = db.execute(
            select(func.count(), func.coalesce(func.sum(Payment.amount), 0),
                   func.coalesce(func.sum(case(
                       (Payment.mode == "cash", Payment.amount), else_=0)), 0))
            .where(Payment.kind == "payment", Payment.paid_on >= start,
                   Payment.paid_on <= end)).one()
        paid_out = {"total": Decimal(out[1]), "cash": Decimal(out[2]),
                    "bank": Decimal(out[1]) - Decimal(out[2]), "count": int(out[0])}

    ageing = ledger.ageing_rows(db, as_of)
    buckets = [{"key": b["key"], "label": b["label"], "total": _s(b["total"]),
                "count": b["count"],
                "share": round(float(b["total"] / ageing["total"] * 100), 1)
                if ageing["total"] > 0 else 0.0}
               for b in ageing["buckets"]]
    overdue_60 = sum((b["total"] for b in ageing["buckets"]
                      if b["key"] in ("61-90", "90+")), ZERO)

    payables = payables_as_of(db, as_of)
    credit = credit_exposure(db)
    days = (end - start).days + 1 if end >= start else 0
    dso = (round(float(ageing["total"] / revenue["taxable"] * days), 1)
           if revenue["taxable"] > 0 and days > 0 else None)
    efficiency = (round(float(collections["total"] / revenue["gross"] * 100), 1)
                  if revenue["gross"] > 0 else None)

    return {
        "from": start.isoformat(), "to": end.isoformat(), "as_of": as_of.isoformat(),
        "days": days,
        "revenue": {"taxable": _s(revenue["taxable"]), "gross": _s(revenue["gross"]),
                    "discount": _s(revenue["discount"]), "invoices": revenue["invoices"]},
        "returns": {"value": _s(returns["value"]), "count": returns["count"]},
        "debit_notes": {"value": _s(debits["value"]), "count": debits["count"]},
        "output_gst": {k: _s(v) for k, v in gst.items()},
        "collections": {k: (_s(v) if k != "count" else v) for k, v in collections.items()},
        "supplier_payments": {k: (_s(v) if k != "count" else v)
                              for k, v in paid_out.items()},
        "outstanding": {"total": _s(ageing["total"]), "count": ageing["count"],
                        "overdue_60": _s(overdue_60), "buckets": buckets},
        "payables": payables,
        "credit": credit,
        "cash_bank_net": _s(collections["total"] - paid_out["total"]),
        "dso_days": dso,
        "collection_efficiency": efficiency,
        "trial_balance": trial_balance(db, as_of),
        "gaps": [{"code": code, "label": label, "detail": detail}
                 for code, label, detail in GAPS],
        "unavailable": [{"key": key, "label": label, "gap": gap, "detail": detail}
                        for key, label, gap, detail in UNAVAILABLE],
        "notes": [
            f"Revenue is taxable value of issued invoices; gross includes GST. {days} days in the window.",
            "Outstanding is as at the window end and is net of credit/debit notes and receipts.",
            "Payables are the cost of goods received on or before the date minus payments made by then.",
            "Cash and bank is the net movement recorded in the window; opening balances are not captured (GAP-A10).",
            "Output GST only: purchase-side tax is not captured (GAP-A05).",
            "No financial-year or period lock is configured (GAP-A03).",
        ],
    }


def payables_as_of(db: Session, as_of: date) -> dict:
    """Supplier balances and an estimated due date from current terms."""
    day = _business_day(GoodsReceipt.received_at)
    grn_rows = db.execute(
        select(GoodsReceipt.id, GoodsReceipt.po_id, day,
               GoodsReceiptLine.product_id, GoodsReceiptLine.qty)
        .join(GoodsReceiptLine, GoodsReceiptLine.grn_id == GoodsReceipt.id)
        .where(day <= as_of)).all()
    costs = {(line.po_id, line.product_id): Decimal(line.unit_cost or 0)
             for line in db.scalars(select(PurchaseOrderLine)).all()}
    received: dict[int, Decimal] = {}
    last_receipt: dict[int, date] = {}
    for _grn_id, po_id, received_on, product_id, qty in grn_rows:
        unit = costs.get((po_id, product_id))
        if unit is None:
            continue
        received[po_id] = received.get(po_id, ZERO) + Decimal(qty) * unit
        if po_id not in last_receipt or received_on > last_receipt[po_id]:
            last_receipt[po_id] = received_on

    paid: dict[int, Decimal] = {}
    for po_id, amount in db.execute(
            select(Payment.purchase_order_id, func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.kind == "payment", Payment.paid_on <= as_of,
                   Payment.purchase_order_id.is_not(None))
            .group_by(Payment.purchase_order_id)).all():
        paid[po_id] = Decimal(amount)

    pos = {po.id: po for po in db.scalars(select(PurchaseOrder)).all()}
    terms = dict(db.execute(select(Supplier.id, Supplier.payment_terms_days)).all())
    rows = []
    total = ZERO
    due_week = ZERO
    advance = ZERO
    for po_id, value in received.items():
        if value <= 0:
            continue
        outstanding = value - paid.get(po_id, ZERO)
        if outstanding <= 0:
            advance += -outstanding
            continue
        po = pos.get(po_id)
        supplier_id = po.supplier_id if po else None
        term_days = int(terms.get(supplier_id, 30) or 0)
        due_on = last_receipt.get(po_id, as_of) + timedelta(days=term_days)
        total += outstanding
        if as_of <= due_on <= as_of + timedelta(days=7):
            due_week += outstanding
        rows.append({
            "purchase_order_id": po_id,
            "number": po.po_number if po else str(po_id),
            "supplier": po.supplier if po else "",
            "received_value": _s(value),
            "paid": _s(paid.get(po_id, ZERO)),
            "outstanding": _s(outstanding),
            "last_received_on": last_receipt.get(po_id).isoformat()
            if last_receipt.get(po_id) else None,
            "terms_days": term_days,
            "due_on": due_on.isoformat(),
        })
    rows.sort(key=lambda r: (-Decimal(r["outstanding"]), r["purchase_order_id"]))
    return {"total": _s(total), "count": len(rows), "advance": _s(advance),
            "due_this_week": _s(due_week), "rows": rows[:50],
            "note": ("Due dates are estimated from each supplier's current payment "
                     "terms and the latest receipt, because a purchase order stores no due date.")}


def credit_exposure(db: Session) -> dict:
    exposure = {did: Decimal(value) for did, value in db.execute(
        select(SalesOrder.distributor_id,
               func.coalesce(func.sum(SalesOrder.total), 0))
        .where(SalesOrder.status.in_(EXPOSURE_STATUSES))
        .group_by(SalesOrder.distributor_id)).all()}
    limits = db.execute(select(Distributor.id, Distributor.name,
                               Distributor.credit_limit)
                        .where(Distributor.credit_limit > 0)).all()
    rows = []
    over_count = 0
    over_amount = ZERO
    for did, name, limit in limits:
        limit = Decimal(limit)
        used = exposure.get(did, ZERO)
        if used > limit:
            over_count += 1
            over_amount += used - limit
        rows.append({"distributor_id": did, "name": name,
                     "limit": _s(limit), "exposure": _s(used),
                     "available": _s(max(limit - used, ZERO)),
                     "pct_used": round(float(used / limit * 100), 1) if limit else None})
    rows.sort(key=lambda r: (-(r["pct_used"] or 0), r["distributor_id"]))
    return {"over_limit_count": over_count, "over_limit_amount": _s(over_amount),
            "distributors": rows[:6],
            "note": "Exposure counts pending, approved and dispatched orders; payments are not netted."}


def trial_balance(db: Session, as_of: date) -> dict:
    tb = ledger.trial_balance(db, as_of)
    return {"as_of": as_of.isoformat(),
            "rows": [{"account": r["account"], "debit": _s(r["debit"]),
                      "credit": _s(r["credit"])} for r in tb["rows"]],
            "debit_total": _s(tb["debit_total"]), "credit_total": _s(tb["credit_total"]),
            "balanced": bool(tb["balanced"]),
            "note": "Derived from the documents; opening balances and expense accounts are not captured."}


def monthly_series(db: Session, first: date, months: int = 12) -> list[dict]:
    """Revenue, collections and returns by calendar month, oldest first."""
    start = first
    # Move to the first month in the range.
    for _ in range(months - 1):
        start = _shift_month(start, -1)
    rows: dict[tuple[int, int], dict] = {}
    cursor = start
    for _ in range(months):
        rows[(cursor.year, cursor.month)] = {"year": cursor.year, "month": cursor.month,
                                             "label": cursor.strftime("%b %Y"),
                                             "revenue": ZERO, "collections": ZERO,
                                             "returns": ZERO}
        cursor = _shift_month(cursor, 1)
    if True:
        for day, value in db.execute(
                select(Invoice.invoice_date, Invoice.taxable_value)
                .where(Invoice.status == "issued", Invoice.invoice_date >= start,
                       Invoice.invoice_date <= _month_end(first))).all():
            key = (day.year, day.month)
            if key in rows:
                rows[key]["revenue"] += Decimal(value)
        for day, value in db.execute(
                select(Payment.paid_on, Payment.amount)
                .where(Payment.kind == "receipt", Payment.paid_on >= start,
                       Payment.paid_on <= _month_end(first))).all():
            key = (day.year, day.month)
            if key in rows:
                rows[key]["collections"] += Decimal(value)
        for day, value in db.execute(
                select(CreditNote.note_date, CreditNote.grand_total)
                .where(CreditNote.status == "issued", CreditNote.note_date >= start,
                       CreditNote.note_date <= _month_end(first))).all():
            key = (day.year, day.month)
            if key in rows:
                rows[key]["returns"] += Decimal(value)
    return [{**r, "revenue": _s(r["revenue"]), "collections": _s(r["collections"]),
             "returns": _s(r["returns"])} for r in rows.values()]


def compare(db: Session, mode: str, first: date, today: date) -> dict:
    """Full-month or month-to-date Accounts comparison, same windows as MoM/YoY."""
    from ..api.dashboard import _compare_windows, _shift_month  # same window maths

    windows = _compare_windows(mode, first, today)
    summaries = {}
    for name in ("current", "previous", "last_year"):
        w = windows[name]
        start, end = date.fromisoformat(w["from"]), date.fromisoformat(w["to"])
        summaries[name] = window(db, start, end) if start <= end else None

    def metric(key, label, unit, read, note=""):
        values = [read(summaries[n]) if summaries[n] else None for n in
                  ("current", "previous", "last_year")]
        return {"key": key, "label": label, "unit": unit,
                "current": values[0], "previous": values[1], "last_year": values[2],
                "previous_change": _change(values[0], values[1])
                if values[0] is not None and values[1] is not None else None,
                "last_year_change": _change(values[0], values[2])
                if values[0] is not None and values[2] is not None else None,
                "available": values[0] is not None, "note": note}

    metrics = [
        metric("revenue", "Revenue (taxable)", "amount",
               lambda s: s["revenue"]["taxable"], "Issued invoices, before GST."),
        metric("invoiced", "Invoiced (with GST)", "amount",
               lambda s: s["revenue"]["gross"]),
        metric("collections", "Collections", "amount",
               lambda s: s["collections"]["total"], "Receipts dated in the window."),
        metric("returns", "Returns", "amount", lambda s: s["returns"]["value"],
               "Issued credit notes."),
        metric("output_gst", "Output GST", "amount",
               lambda s: s["output_gst"]["total"], "Output only; input tax is not captured."),
        metric("outstanding", "Receivables outstanding", "amount",
               lambda s: s["outstanding"]["total"], "As at the window end."),
        metric("overdue_60", "Receivables over 60 days", "amount",
               lambda s: s["outstanding"]["overdue_60"], "As at the window end."),
        metric("payables", "Payables outstanding", "amount",
               lambda s: s["payables"]["total"],
               "As at the window end, estimated due dates."),
        metric("cash_bank", "Cash and bank (net movement)", "amount",
               lambda s: s["cash_bank_net"], "Receipts minus payments in the window."),
    ]
    month_state = windows["state"]
    if month_state == "future":
        for m in metrics:
            m.update(current=None, previous=None, last_year=None,
                     previous_change=None, last_year_change=None, available=False)
    label = (f"{first.strftime('%B %Y')}"
             + (" (current month, incomplete)" if month_state == "current" else "")
             + (" (not started)" if month_state == "future" else ""))
    return {
        "mode": mode, "month": first.strftime("%Y-%m"), "month_label": label,
        "month_state": month_state,
        "ranges": {k: windows[k] for k in ("current", "previous", "last_year")},
        "metrics": metrics,
        "current": summaries["current"],
        "previous": summaries["previous"],
        "last_year": summaries["last_year"],
        "trend": monthly_series(db, first),
        "unavailable": [{"key": key, "label": label, "gap": gap, "detail": detail}
                        for key, label, gap, detail in UNAVAILABLE],
        "gaps": [{"code": code, "label": label, "detail": detail}
                 for code, label, detail in GAPS],
        "notes": [
            "Snapshot figures (outstanding, payables) are as at each window's last day.",
            "Flows cover each window exactly. A comparison against zero has no percentage.",
            "No financial-year or period lock is configured (GAP-A03).",
        ],
    }


def _month_end(day: date) -> date:
    from ..api.dashboard import _month_bounds
    return _month_bounds(day.replace(day=1))[1]


def _shift_month(first: date, months: int) -> date:
    from ..api.dashboard import _shift_month as shift
    return shift(first, months)
