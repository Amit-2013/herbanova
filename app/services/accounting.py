"""Accounts reporting: what the documents can prove, and what they cannot.

There is no chart of accounts and no opening balance. Purchase-side tax exists
only as captured supplier bills (`gst`), so input GST and net payable are
available once a bill is posted and unavailable before that. This module
therefore computes revenue, collections, returns, outstanding and ageing,
payables, output GST, input GST, net GST, credit use, cash/bank movement and the
derived trial balance. Profit and loss is built by `profit_loss.statement` from
captured costs, approved expenses and payroll. Everything else is returned as
an unavailable metric with a gap code, so a screen or an email can say
"No data yet" instead of inventing a figure.

Sales invoices freeze the distributor's payment terms at issue, so the due date
and the ageing split are read from the invoice, not from today's master. A
closed financial year (`periods`) and a locked accounting month both refuse
dated documents. Payables are measured as at a date: the cost of goods received
on or before it, minus payments made on or before it. A supplier's
`payment_terms_days` is still used to estimate when an outstanding balance falls
due; that value is today's master value, and the note says so.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.orm import Session

from ..core.india_states import state_name
from ..core.rules import REPORT_TZ
from ..models.accounts import Payment, PaymentAllocation
from ..models.core import (CreditNote, DebitNote, Distributor, Invoice, PurchaseOrder,
                           PurchaseOrderLine, SalesOrder)
from ..models.suppliers import GoodsReceipt, GoodsReceiptLine, Supplier
from . import gst as gst_service, ledger, profit_loss
from .sales import EXPOSURE_STATUSES

ZERO = Decimal("0.00")

# A08, A09 and A10 closed in Batch 5: vouchers and the day book are in
# `services/journal.py`, bank statements and matching in `services/bank_rec.py`,
# and openings and the balance sheet in `services/balance_sheet.py`.
GAPS = ()

UNAVAILABLE = ()


def _s(value) -> str:
    return str((Decimal(value or 0)).quantize(Decimal("0.01")))


def _money(value) -> Decimal:
    return ledger.money(value)


def _grand(document) -> Decimal:
    return ledger.money(document.grand_total)


def _business_day(column):
    return cast(func.timezone(REPORT_TZ, column), Date)


def _change(current, previous) -> float | None:
    current, previous = Decimal(current or 0), Decimal(previous or 0)
    if previous == 0:
        return None
    return round(float((current - previous) / previous * 100), 1)


def _invoice_state():
    """The buyer state frozen on the invoice, with the master as last resort."""
    return func.coalesce(Invoice.buyer_state_code, Distributor.state_code)


def window(db: Session, start: date, end: date, as_of: date | None = None,
           state: str | None = None) -> dict:
    """Every Accounts figure for one window. Snapshot figures use `as_of`.

    `state` narrows the flows that carry a buyer state (revenue, returns,
    output GST and distributor receipts). Balances owed on suppliers, the
    trial balance and the net cash movement are not split by state, and the
    response says so rather than pretending they were filtered.
    """
    as_of = as_of or end
    empty = start > end
    revenue = {"taxable": ZERO, "gross": ZERO, "discount": ZERO, "invoices": 0}
    returns = {"value": ZERO, "count": 0}
    debits = {"value": ZERO, "count": 0}
    gst = {"cgst": ZERO, "sgst": ZERO, "igst": ZERO, "cess": ZERO, "total": ZERO}
    collections = {"total": ZERO, "cash": ZERO, "bank": ZERO, "count": 0}
    paid_out = {"total": ZERO, "cash": ZERO, "bank": ZERO, "count": 0}

    if not empty:
        sales_q = (select(func.count(Invoice.id),
                          func.coalesce(func.sum(Invoice.taxable_value), 0),
                          func.coalesce(func.sum(Invoice.grand_total), 0),
                          func.coalesce(func.sum(Invoice.discount_total), 0),
                          func.coalesce(func.sum(Invoice.cgst_total), 0),
                          func.coalesce(func.sum(Invoice.sgst_total), 0),
                          func.coalesce(func.sum(Invoice.igst_total), 0),
                          func.coalesce(func.sum(Invoice.cess_total), 0),
                          func.coalesce(func.sum(Invoice.tax_total), 0))
                   .where(Invoice.status == "issued", Invoice.invoice_date >= start,
                          Invoice.invoice_date <= end))
        if state:
            sales_q = (sales_q.join(Distributor, Distributor.id == Invoice.distributor_id)
                       .where(_invoice_state() == state))
        row = db.execute(sales_q).one()
        revenue = {"taxable": Decimal(row[1]), "gross": Decimal(row[2]),
                   "discount": Decimal(row[3]), "invoices": int(row[0])}
        gst = {"cgst": Decimal(row[4]), "sgst": Decimal(row[5]),
               "igst": Decimal(row[6]), "cess": Decimal(row[7]),
               "total": Decimal(row[8])}

        note_q = (select(func.count(CreditNote.id),
                         func.coalesce(func.sum(CreditNote.grand_total), 0))
                  .where(CreditNote.status == "issued",
                         CreditNote.note_date >= start,
                         CreditNote.note_date <= end))
        debit_q = (select(func.count(DebitNote.id),
                          func.coalesce(func.sum(DebitNote.grand_total), 0))
                   .where(DebitNote.status == "issued",
                          DebitNote.note_date >= start,
                          DebitNote.note_date <= end))
        if state:
            note_q = (note_q.join(Invoice, Invoice.id == CreditNote.invoice_id)
                      .join(Distributor, Distributor.id == Invoice.distributor_id)
                      .where(_invoice_state() == state))
            debit_q = (debit_q.join(Invoice, Invoice.id == DebitNote.invoice_id)
                       .join(Distributor, Distributor.id == Invoice.distributor_id)
                       .where(_invoice_state() == state))
        r = db.execute(note_q).one()
        returns = {"value": Decimal(r[1]), "count": int(r[0])}
        d = db.execute(debit_q).one()
        debits = {"value": Decimal(d[1]), "count": int(d[0])}

        receipt_q = (
            select(func.count(), func.coalesce(func.sum(Payment.amount), 0),
                   func.coalesce(func.sum(case(
                       (Payment.mode == "cash", Payment.amount), else_=0)), 0))
            .where(Payment.kind == "receipt", Payment.paid_on >= start,
                   Payment.paid_on <= end))
        if state:
            receipt_q = (receipt_q.join(Distributor,
                                        Distributor.id == Payment.distributor_id)
                         .where(Distributor.state_code == state))
        pay = db.execute(receipt_q).one()
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
    net_gst = gst_service.net(db, start, end)
    days = (end - start).days + 1 if end >= start else 0
    dso = (round(float(ageing["total"] / revenue["taxable"] * days), 1)
           if revenue["taxable"] > 0 and days > 0 else None)
    efficiency = (round(float(collections["total"] / revenue["gross"] * 100), 1)
                  if revenue["gross"] > 0 else None)

    return {
        "from": start.isoformat(), "to": end.isoformat(), "as_of": as_of.isoformat(),
        "days": days,
        "region": {"state": state, "name": state_name(state) if state else None,
                   "label": state_name(state) if state else "All states",
                   "applies_to": "Revenue, returns, output GST and distributor receipts.",
                   "not_applied_to": ("Receivables and payables balances, cash and bank "
                                      "totals, and the trial balance stay company-wide."),
                   } if state else None,
        "revenue": {"taxable": _s(revenue["taxable"]), "gross": _s(revenue["gross"]),
                    "discount": _s(revenue["discount"]), "invoices": revenue["invoices"]},
        "returns": {"value": _s(returns["value"]), "count": returns["count"]},
        "debit_notes": {"value": _s(debits["value"]), "count": debits["count"]},
        "output_gst": {k: _s(v) for k, v in gst.items()},
        "net_gst": {
            "available": net_gst["available"],
            "reason": net_gst["reason"],
            "input": {k: _s(v) for k, v in net_gst["input"].items()},
            "input_total": _s(net_gst["input_total"]),
            "blocked_total": _s(net_gst["blocked_total"]),
            "net": {k: _s(v) for k, v in net_gst["net"].items()},
            "net_total": _s(net_gst["net_total"]),
            "expense_itc": {"amount": _s(net_gst["expense_itc"]["amount"]),
                            "count": net_gst["expense_itc"]["count"],
                            "included_in_net": False},
        },
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
            "Cash and bank is the net movement recorded in the window; the "
            "closing position, with opening balances, is on the balance sheet.",
            "Net GST is output tax minus eligible input tax captured on supplier "
            "bills. Blocked input is shown separately and never netted; creditable "
            "GST on expenses is a memo because an expense records one GST amount "
            "with no head split.",
            "A closed financial year refuses dated documents: dispatches, "
            "receipts and payments, credit and debit notes, invoice cancellation, "
            "expenses and cost corrections. Only the Administrator can reopen it, "
            "with a reason. A locked accounting month stays the narrower gate for "
            "day-to-day corrections.",
            "Sales invoices freeze the distributor's payment terms and due date at "
            "issue, so ageing reads the due date from the invoice. Supplier due "
            "dates remain an estimate from the current terms.",
        ] + ([f"Region filter: {state_name(state) or state}. It narrows revenue, returns, "
              "output GST and distributor receipts; balances and cash stay company-wide."]
             if state else []),
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
    # Settlements added later, including an advance drawn down against a bill.
    for po_id, amount in db.execute(
            select(PaymentAllocation.purchase_order_id,
                   func.coalesce(func.sum(PaymentAllocation.amount), 0))
            .where(PaymentAllocation.applied_on <= as_of,
                   PaymentAllocation.purchase_order_id.is_not(None))
            .group_by(PaymentAllocation.purchase_order_id)).all():
        paid[po_id] = paid.get(po_id, ZERO) + Decimal(amount)

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
    """Revenue, collections, payments, output GST and returns by calendar month."""
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
                                             "payments": ZERO, "output_gst": ZERO,
                                             "returns": ZERO}
        cursor = _shift_month(cursor, 1)
    if True:
        for day, taxable, tax in db.execute(
                select(Invoice.invoice_date, Invoice.taxable_value, Invoice.tax_total)
                .where(Invoice.status == "issued", Invoice.invoice_date >= start,
                       Invoice.invoice_date <= _month_end(first))).all():
            key = (day.year, day.month)
            if key in rows:
                rows[key]["revenue"] += Decimal(taxable)
                rows[key]["output_gst"] += Decimal(tax)
        for day, kind, value in db.execute(
                select(Payment.paid_on, Payment.kind, Payment.amount)
                .where(Payment.paid_on >= start,
                       Payment.paid_on <= _month_end(first))).all():
            key = (day.year, day.month)
            if key in rows:
                rows[key]["collections" if kind == "receipt" else "payments"] += Decimal(value)
        for day, value in db.execute(
                select(CreditNote.note_date, CreditNote.grand_total)
                .where(CreditNote.status == "issued", CreditNote.note_date >= start,
                       CreditNote.note_date <= _month_end(first))).all():
            key = (day.year, day.month)
            if key in rows:
                rows[key]["returns"] += Decimal(value)
    return [{**r, "revenue": _s(r["revenue"]), "collections": _s(r["collections"]),
             "payments": _s(r["payments"]), "output_gst": _s(r["output_gst"]),
             "returns": _s(r["returns"]),
             "net_cash": _s(r["collections"] - r["payments"])}
            for r in rows.values()]


def state_breakdown(db: Session, start: date, end: date) -> list[dict]:
    """Revenue, output GST, returns and outstanding, by the invoice's buyer state.

    Revenue and tax come from the issued invoices, returns from the credit notes
    written against them, and outstanding from the same rows the ageing report
    uses. A distributor with no state code is grouped as unrecorded; nothing is
    guessed from a free-text address.
    """
    if start > end:
        return []
    code = _invoice_state()
    flows = {str(row[0]).zfill(2) if row[0] else None: row for row in db.execute(
        select(code, func.count(Invoice.id),
               func.coalesce(func.sum(Invoice.taxable_value), 0),
               func.coalesce(func.sum(Invoice.tax_total), 0),
               func.coalesce(func.sum(Invoice.grand_total), 0))
        .select_from(Invoice)
        .join(Distributor, Distributor.id == Invoice.distributor_id)
        .where(Invoice.status == "issued", Invoice.invoice_date >= start,
               Invoice.invoice_date <= end)
        .group_by(code)).all()}
    returned = {str(row[0]).zfill(2) if row[0] else None: Decimal(row[1])
                for row in db.execute(
                    select(code, func.coalesce(func.sum(CreditNote.grand_total), 0))
                    .select_from(CreditNote)
                    .join(Invoice, Invoice.id == CreditNote.invoice_id)
                    .join(Distributor, Distributor.id == Invoice.distributor_id)
                    .where(CreditNote.status == "issued",
                           CreditNote.note_date >= start,
                           CreditNote.note_date <= end)
                    .group_by(code)).all()}
    states = dict(db.execute(select(Distributor.id, Distributor.state_code)).all())
    outstanding: dict[str | None, Decimal] = {}
    for row in ledger.receivable_rows(db):
        value = Decimal(row["outstanding"])
        if value <= 0:
            continue
        raw = states.get(row["distributor_id"])
        key = str(raw).zfill(2) if raw else None
        outstanding[key] = outstanding.get(key, ZERO) + value

    keys = set(flows) | set(returned) | set(outstanding)
    out = []
    for key in keys:
        flow = flows.get(key)
        name = state_name(key) if key else None
        out.append({
            "key": key or "unrecorded",
            "state": key,
            "name": name or ("State not recorded" if not key else f"Unknown state ({key})"),
            "known": bool(name),
            "invoices": int(flow[1]) if flow else 0,
            "revenue": _s(flow[2]) if flow else _s(ZERO),
            "output_gst": _s(flow[3]) if flow else _s(ZERO),
            "invoiced": _s(flow[4]) if flow else _s(ZERO),
            "returns": _s(returned.get(key, ZERO)),
            "outstanding": _s(outstanding.get(key, ZERO)),
        })
    out.sort(key=lambda r: (-Decimal(r["revenue"]), r["key"]))
    return out


def receivables_by_distributor(db: Session, limit: int = 10) -> dict:
    """Outstanding per distributor, for the total -> party -> ledger drill-down."""
    names = dict(db.execute(select(Distributor.id, Distributor.name)).all())
    states = dict(db.execute(select(Distributor.id, Distributor.state_code)).all())
    grouped: dict[int, dict] = {}
    for row in ledger.receivable_rows(db):
        value = Decimal(row["outstanding"])
        if value <= 0:
            continue
        group = grouped.setdefault(row["distributor_id"], {
            "distributor_id": row["distributor_id"],
            "name": names.get(row["distributor_id"]) or str(row["distributor_id"]),
            "state": states.get(row["distributor_id"]),
            "invoices": 0, "outstanding": ZERO})
        group["invoices"] += 1
        group["outstanding"] += value
    rows = sorted(grouped.values(), key=lambda r: (-r["outstanding"], r["distributor_id"]))
    return {"total": _s(sum((r["outstanding"] for r in rows), ZERO)),
            "count": len(rows),
            "rows": [{**r, "outstanding": _s(r["outstanding"])} for r in rows[:limit]],
            "note": ("Each distributor opens the party ledger, where every invoice, "
                     "credit note and receipt is listed. Receipts and invoices are "
                     "not posted as vouchers automatically; a manual journal or "
                     "opening balance reaches the same heads through the ledger.")}


def receivables_by_distributor_window(db: Session, start: date, end: date) -> dict:
    """What each distributor owed across one window, not just at a point in time.

    Opening is the balance the day before `start`; closing is the balance at
    `end`. Invoiced, credit notes, debit notes and receipts are the movements
    dated inside the window, so opening plus the movements equals closing for
    every party. Documents dated after `end` are excluded, which is what makes
    the report an as-at statement rather than a moving target.

    The amounts are built from the same documents as `receivable_rows()`:
    issued invoices, issued credit and debit notes, and receipts allocated to
    an invoice. An unallocated receipt is not netted against a party here,
    exactly as it is not netted in the outstanding list. Overdue counts only a
    closing balance whose invoice carries a due date before `end`; an invoice
    issued before due dates were captured is left out of overdue rather than
    being given an assumed term.
    """
    parties = {p.id: p for p in db.scalars(select(Distributor)).all()}
    # A receipt recorded directly against an invoice and one applied later both
    # count on the day the money settled that invoice, so an advance that is
    # drawn down in this window shows as received here.
    receipts = ledger.receipt_movements(db, end)
    credits: dict[int, list[tuple[date, Decimal]]] = {}
    for cn in db.scalars(select(CreditNote).where(
            CreditNote.status == "issued", CreditNote.invoice_id.is_not(None),
            CreditNote.note_date <= end)).all():
        credits.setdefault(cn.invoice_id, []).append((cn.note_date, _grand(cn)))
    debits: dict[int, list[tuple[date, Decimal]]] = {}
    for dn in db.scalars(select(DebitNote).where(
            DebitNote.status == "issued", DebitNote.invoice_id.is_not(None),
            DebitNote.note_date <= end)).all():
        debits.setdefault(dn.invoice_id, []).append((dn.note_date, _grand(dn)))

    def blank(party_id: int | None) -> dict:
        party = parties.get(party_id)
        return {
            "distributor_id": party_id,
            "code": party.code if party else None,
            "name": party.name if party else f"Distributor #{party_id}",
            "state": party.state_code if party else None,
            "opening": ZERO, "invoiced": ZERO, "credited": ZERO, "debited": ZERO,
            "received": ZERO, "closing": ZERO, "overdue": ZERO,
            "invoices": 0, "open_invoices": 0, "overdue_invoices": 0,
        }

    groups: dict[int | None, dict] = {}
    for inv in db.scalars(select(Invoice).where(
            Invoice.status == "issued", Invoice.invoice_date <= end)
            .order_by(Invoice.invoice_date, Invoice.id)).all():
        group = groups.setdefault(inv.distributor_id, blank(inv.distributor_id))
        total = _grand(inv)
        got = receipts.get(inv.id, [])
        got_open = sum((a for d, a in got if d < start), ZERO)
        got_all = sum((a for _, a in got), ZERO)
        cr = credits.get(inv.id, [])
        cr_open = sum((a for d, a in cr if d < start), ZERO)
        cr_all = sum((a for _, a in cr), ZERO)
        dr = debits.get(inv.id, [])
        dr_open = sum((a for d, a in dr if d < start), ZERO)
        dr_all = sum((a for _, a in dr), ZERO)

        if inv.invoice_date < start:
            group["opening"] += total + dr_open - cr_open - got_open
        else:
            group["invoiced"] += total
            group["invoices"] += 1
        group["credited"] += cr_all - cr_open
        group["debited"] += dr_all - dr_open
        group["received"] += got_all - got_open

        closing = total + dr_all - cr_all - got_all
        group["closing"] += closing
        if closing > 0:
            group["open_invoices"] += 1
            if inv.due_date is not None and inv.due_date < end:
                group["overdue"] += closing
                group["overdue_invoices"] += 1

    rows = []
    for group in groups.values():
        if not any(group[key] != 0 for key in
                   ("opening", "invoiced", "credited", "debited", "received", "closing")):
            continue
        rows.append(group)
    rows.sort(key=lambda r: (-r["closing"], r["name"] or ""))

    totals = {key: ZERO for key in
              ("opening", "invoiced", "credited", "debited", "received", "closing", "overdue")}
    for row in rows:
        for key in totals:
            totals[key] += row[key]
    for row in rows:
        for key in totals:
            row[key] = _s(row[key])
    return {
        "from": start,
        "to": end,
        "rows": rows,
        "totals": {
            **{key: _s(value) for key, value in totals.items()},
            "invoices": sum(r["invoices"] for r in rows),
            "open_invoices": sum(r["open_invoices"] for r in rows),
            "overdue_invoices": sum(r["overdue_invoices"] for r in rows),
        },
        "count": len(rows),
        "note": ("Opening is the balance the day before the window; closing is the "
                 "balance at its last day. Credit notes reduce and debit notes raise "
                 "what a party owes; only receipts allocated to an invoice are netted. "
                 "Overdue is the part of the closing balance whose due date fell before "
                 "the closing date; invoices with no recorded due date are not counted "
                 "as overdue."),
    }


def report(db: Session, start: date, end: date, state: str | None = None) -> dict:
    """The Accounts dashboard for one window: figures, trend, regions and gaps."""
    out = window(db, start, end, state=state)
    out["trend"] = monthly_series(db, end.replace(day=1))
    out["states"] = state_breakdown(db, start, end)
    out["receivables_by_distributor"] = receivables_by_distributor(db)
    pl = profit_loss.statement(db, start, end)
    net_available = pl["net_profit"]["available"]
    first_gap = pl["gaps"][0] if pl["gaps"] else None

    rows = [
        {"key": "revenue", "label": "Revenue (taxable)",
         "value": _s(pl["revenue"]["taxable"]), "available": True},
        {"key": "returns", "label": "Less returns (taxable)",
         "value": _s(pl["returns"]["taxable"]), "available": True,
         "good_when_up": False},
        {"key": "debit_notes", "label": "Add debit notes (taxable)",
         "value": _s(pl["revenue"]["debit_notes"]), "available": True},
        {"key": "net_revenue", "label": "Net revenue",
         "value": _s(pl["net_revenue"]), "available": True},
        {"key": "cogs", "label": "Cost of goods sold",
         "value": _s(pl["cogs"]["value"]), "available": True,
         "note": (f"{pl['cogs']['invoices_costed']} of "
                  f"{pl['cogs']['invoices_total']} invoices fully costed.")},
        {"key": "gross_profit", "label": pl["gross_profit"]["label"],
         "value": _s(pl["gross_profit"]["value"]), "available": True,
         "partial": pl["gross_profit"]["partial"],
         "note": ("Complete for every invoice in the window."
                  if not pl["gross_profit"]["partial"] else
                  "Costed invoices only; the rest are named in the gaps.")},
    ]
    for head in pl["expenses"]["by_head"]:
        rows.append({"key": f"expense_head_{head['head_id']}",
                     "label": f"Expense · {head['head']}",
                     "value": _s(head["amount"]), "available": True,
                     "note": (f"{head['count']} entry(s); non-creditable GST "
                              f"{_s(head['gst_noncreditable'])} included.")})
    # A figure the records can prove is shown even when the window is incomplete,
    # labelled partial; "No data yet" is reserved for a window with nothing to show.
    expenses_known = pl["expenses"]["complete"] or pl["expenses"]["total"] > 0
    payroll_known = pl["payroll"]["complete"] or bool(pl["payroll"]["periods"])
    payroll_absent = ", ".join(
        f"{i['year']}-{i['month']:02d}" for i in
        pl["payroll"]["missing_months"] + pl["payroll"]["partial_months"])
    if pl["expenses"]["complete"]:
        rows.append({"key": "expenses", "label": "Total expenses",
                     "value": _s(pl["expenses"]["total"]), "available": True,
                     "note": "Approved, non-reversed entries; non-creditable GST included."})
    elif expenses_known:
        rows.append({"key": "expenses", "label": "Total expenses",
                     "value": _s(pl["expenses"]["total"]), "available": True,
                     "partial": True, "gap": "GAP-P02", "fix": "#/expenses",
                     "note": (f"Partial: expenses are recorded from "
                              f"{pl['expenses']['tracked_from'] or 'no configured date'}, "
                              "so earlier months in this window have no expense records.")})
    else:
        rows.append({"key": "expenses", "label": "Total expenses", "value": None,
                     "available": False, "gap": "GAP-P02",
                     "note": "Expenses are not tracked for the whole window.",
                     "fix": "#/expenses"})
    if pl["payroll"]["complete"]:
        rows.append({"key": "payroll", "label": "Payroll (gross)",
                     "value": _s(pl["payroll"]["total"]), "available": True,
                     "note": "Gross salary; employer contributions are not included."})
    elif payroll_known:
        rows.append({"key": "payroll", "label": "Payroll (gross)",
                     "value": _s(pl["payroll"]["total"]), "available": True,
                     "partial": True, "gap": "GAP-P03", "fix": "#/hr/payroll",
                     "note": (f"Partial: approved months only. No approved payroll for "
                              f"{payroll_absent}.")})
    else:
        rows.append({"key": "payroll", "label": "Payroll (gross)", "value": None,
                     "available": False, "gap": "GAP-P03",
                     "note": ("No month in this window has an approved payroll "
                              "period."),
                     "fix": "#/hr/payroll"})
    if net_available:
        rows.append({"key": "net_profit", "label": "Net profit",
                     "value": _s(pl["net_profit"]["value"]), "available": True})
    else:
        rows.append({"key": "net_profit", "label": "Net profit", "value": None,
                     "available": False, "gap": first_gap["code"] if first_gap else "GAP-P02",
                     "note": (first_gap["detail"] if first_gap else
                              "Cost, expenses and payroll are not all complete."),
                     "fix": first_gap["fix"] if first_gap else "#/accounts"})

    out["profit_and_loss"] = {
        "rows": rows,
        "note": ("Revenue and returns are taxable value. Cost of goods comes from the "
                 "captured stock ledger, expenses from approved entries and payroll "
                 "from approved monthly periods. GST never changes profit."),
        "gaps": pl["gaps"],
        "notes": pl["notes"],
        "statement": {
            "from": pl["from"], "to": pl["to"],
            "net_revenue": _s(pl["net_revenue"]),
            "cogs": {k: (_s(v) if isinstance(v, Decimal) else v)
                     for k, v in pl["cogs"].items()},
            "gross_profit": {k: (_s(v) if isinstance(v, Decimal) else v)
                             for k, v in pl["gross_profit"].items()},
            "expenses": {k: (_s(v) if isinstance(v, Decimal) else v)
                         for k, v in pl["expenses"].items() if k != "by_head"},
            "payroll": {k: (_s(v) if isinstance(v, Decimal) else v)
                        for k, v in pl["payroll"].items() if k not in ("periods",)},
            "net_profit": {k: (_s(v) if isinstance(v, Decimal) else v)
                           for k, v in pl["net_profit"].items()},
        },
    }
    # Each card opens the report that proves it, carrying the same window so the
    # detail and the card cannot disagree. A card whose detail has no window
    # (receivables and payables are as-at-today lists) opens its own section
    # unchanged rather than pretending to travel in time.
    window_q = f"?from={start.isoformat()}&to={end.isoformat()}"
    as_of_q = f"?as_of={end.isoformat()}"
    out["cards"] = [
        {"key": "revenue", "label": "Revenue", "value": out["revenue"]["taxable"],
         "href": f"#/accounts/gst-out{window_q}",
         "note": "Issued invoices, taxable value before GST."},
        {"key": "collections", "label": "Collections", "value": out["collections"]["total"],
         "href": f"#/accounts/cash{window_q}",
         "note": "Receipts dated in the window."},
        {"key": "outstanding", "label": "Receivables", "value": out["outstanding"]["total"],
         "href": "#/accounts/receivables",
         "note": "As at the window end, net of notes and receipts."},
        {"key": "overdue_60", "label": "Over 60 days", "value": out["outstanding"]["overdue_60"],
         "href": f"#/accounts/ageing{as_of_q}",
         "note": "The part of receivables ageing past 60 days."},
        {"key": "payables", "label": "Payables", "value": out["payables"]["total"],
         "href": "#/accounts/payables",
         "note": "Goods received, less payments; due dates estimated."},
        {"key": "payable_week", "label": "Payable within 7 days",
         "value": out["payables"]["due_this_week"],
         "href": "#/accounts/payables?due=week",
         "note": "Estimated from each supplier's current payment terms."},
        {"key": "gst", "label": "Output GST", "value": out["output_gst"]["total"],
         "href": f"#/accounts/gst-out{window_q}",
         "note": ("Output tax on issued documents. Input tax and net payable are "
                  "built from supplier bills in the input register.")},
        {"key": "cash_bank", "label": "Cash and bank (net)", "value": out["cash_bank_net"],
         "href": f"#/accounts/cash{window_q}",
         "note": "Receipts minus payments in the window."},
        {"key": "expenses", "label": "Expenses",
         "value": _s(pl["expenses"]["total"]) if expenses_known else None,
         "href": f"#/expenses{window_q}", "available": expenses_known,
         "partial": expenses_known and not pl["expenses"]["complete"],
         "gap": None if pl["expenses"]["complete"] else "GAP-P02",
         "note": ("Approved entries in the window; non-creditable GST is cost."
                  if pl["expenses"]["complete"] else
                  "Partial: expenses are recorded from "
                  f"{pl['expenses']['tracked_from'] or 'no configured date'}.")},
        {"key": "net_profit", "label": "Net profit",
         "value": (_s(pl["net_profit"]["value"]) if net_available else None),
         "href": "#/accounts/reports?focus=pnl", "available": net_available,
         "gap": None if net_available else (first_gap["code"] if first_gap else "GAP-P02"),
         "note": ("Gross profit less expenses and payroll."
                  if net_available else
                  (first_gap["detail"] if first_gap else
                   "Cost, expenses and payroll are not all complete."))},
    ]
    out["net_profit"] = {
        "available": net_available,
        "value": _s(pl["net_profit"]["value"]) if net_available else None,
        "gap": None if net_available else (first_gap["code"] if first_gap else "GAP-P02"),
        "note": ("Gross profit less expenses and payroll." if net_available else
                 (first_gap["detail"] if first_gap else
                  "Cost, expenses and payroll are not all complete.")),
        "gross_partial": pl["gross_profit"]["partial"],
        "invoices_costed": pl["cogs"]["invoices_costed"],
        "invoices_total": pl["cogs"]["invoices_total"],
    }
    return out


def compare(db: Session, mode: str, first: date, today: date) -> dict:
    """Full-month or month-to-date Accounts comparison, same windows as MoM/YoY."""
    from ..api.dashboard import _compare_windows, _shift_month  # same window maths

    windows = _compare_windows(mode, first, today)
    summaries, statements = {}, {}
    for name in ("current", "previous", "last_year"):
        w = windows[name]
        start, end = date.fromisoformat(w["from"]), date.fromisoformat(w["to"])
        if start <= end:
            summaries[name] = window(db, start, end)
            statements[name] = profit_loss.statement(db, start, end)
        else:
            summaries[name] = None
            statements[name] = None

    def metric(key, label, unit, read, note=""):
        values = [read(summaries[n], statements[n]) if summaries[n] else None
                  for n in ("current", "previous", "last_year")]
        return {"key": key, "label": label, "unit": unit,
                "current": values[0], "previous": values[1], "last_year": values[2],
                "previous_change": _change(values[0], values[1])
                if values[0] is not None and values[1] is not None else None,
                "last_year_change": _change(values[0], values[2])
                if values[0] is not None and values[2] is not None else None,
                "available": values[0] is not None, "note": note}

    def pl_value(reader):
        def read(_summary, statement):
            if statement is None:
                return None
            value = reader(statement)
            return float(value) if value is not None else None
        return read

    metrics = [
        metric("revenue", "Revenue (taxable)", "amount",
               lambda s, st: s["revenue"]["taxable"], "Issued invoices, before GST."),
        metric("invoiced", "Invoiced (with GST)", "amount",
               lambda s, st: s["revenue"]["gross"]),
        metric("collections", "Collections", "amount",
               lambda s, st: s["collections"]["total"], "Receipts dated in the window."),
        metric("returns", "Returns", "amount", lambda s, st: s["returns"]["value"],
               "Issued credit notes."),
        metric("output_gst", "Output GST", "amount",
               lambda s, st: s["output_gst"]["total"],
               "Output tax on issued documents; input tax comes from posted supplier bills."),
        metric("outstanding", "Receivables outstanding", "amount",
               lambda s, st: s["outstanding"]["total"], "As at the window end."),
        metric("overdue_60", "Receivables over 60 days", "amount",
               lambda s, st: s["outstanding"]["overdue_60"], "As at the window end."),
        metric("payables", "Payables outstanding", "amount",
               lambda s, st: s["payables"]["total"],
               "As at the window end, estimated due dates."),
        metric("cash_bank", "Cash and bank (net movement)", "amount",
               lambda s, st: s["cash_bank_net"], "Receipts minus payments in the window."),
        metric("gross_profit", "Gross profit", "amount",
               pl_value(lambda st: st["gross_profit"]["value"]),
               "Revenue less returns and cost of goods; partial when invoices are uncosted."),
        metric("expenses", "Expenses", "amount",
               pl_value(lambda st: st["expenses"]["total"]
                        if st["expenses"]["complete"]
                        or st["expenses"]["total"] > 0 else None),
               "Approved entries in the window; non-creditable GST included. "
               "Partial when the window starts before expense tracking."),
        metric("payroll", "Payroll (gross)", "amount",
               pl_value(lambda st: st["payroll"]["total"]
                        if st["payroll"]["complete"]
                        or st["payroll"]["periods"] else None),
               "Gross salary of approved, processed or paid periods. Partial when a "
               "month in the window has no approved payroll."),
        metric("net_profit", "Net profit", "amount",
               pl_value(lambda st: st["net_profit"]["value"]),
               "Gross profit less expenses and payroll."),
    ]
    month_state = windows["state"]
    if month_state == "future":
        for m in metrics:
            m.update(current=None, previous=None, last_year=None,
                     previous_change=None, last_year_change=None, available=False)
    for m in metrics:
        if m["available"]:
            continue
        if m["key"] == "expenses":
            m["gap"] = "GAP-P02"
            m["note"] = ("Expenses are not tracked for the whole window; "
                         "no figure is estimated.")
        elif m["key"] in ("payroll", "net_profit"):
            current = statements.get("current")
            m["gap"] = (current["gaps"][0]["code"]
                        if current and current["gaps"] else "GAP-P02")
            m["note"] = ("The statement is incomplete; no figure is estimated.")
        if m["key"] == "gross_profit" and statements.get("current"):
            st = statements["current"]["gross_profit"]
            if st["partial"]:
                m["note"] = st["label"]
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
            "Profit lines use captured costs, approved expenses and approved payroll; "
            "a gap is shown where any of them is incomplete.",
        ],
    }


def _month_end(day: date) -> date:
    from ..api.dashboard import _month_bounds
    return _month_bounds(day.replace(day=1))[1]


def _shift_month(first: date, months: int) -> date:
    from ..api.dashboard import _shift_month as shift
    return shift(first, months)
