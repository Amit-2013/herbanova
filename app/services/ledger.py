"""Statements derived from the documents (Module Phase 6, Accounts).

Nothing here keeps a second set of figures. Every number is computed from the
issued tax invoices, credit and debit notes, the goods actually received against
purchase orders, and the receipts and payments recorded in `payments`. If the
documents are right, the statements are right; if a document is corrected by a
credit note, the statements follow it.

Named `ledger` and not `accounts` because `app/services/accounts.py` already
holds the user/role helpers from Module Phase 1 - the two must not collide.

What this module does **not** claim:

- Input tax. This function reports outward supplies only. Input tax comes from
  supplier bills captured in `purchase_invoices`; `app/services/gst.py` composes
  the input register, the net payable and the comparison with a filed return.
- Statutory return formats. The register is a reconciliation aid in the shape of
  the GSTR-1 sections, not a filing file. A GST practitioner must review it
  before anything is filed (E-022 is still outstanding).
"""
from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.accounts import PAYMENT, RECEIPT, Payment, PaymentAllocation
from ..models.core import (CreditNote, DebitNote, Distributor, Invoice, PurchaseOrder,
                           PurchaseOrderLine)
from ..models.suppliers import GoodsReceipt, GoodsReceiptLine, Supplier

ZERO = Decimal("0.00")


def money(value) -> Decimal:
    # Half-up, the same rule as the tax/payroll quantisers (F-01); the default
    # Decimal context rounds half-even, which would disagree on an exact half paisa.
    return Decimal(value or 0).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _grand(document) -> Decimal:
    return money(document.grand_total)


# --------------------------------------------------------------- outstanding
def _allocated(db: Session, column, until: date | None = None) -> dict[int, Decimal]:
    stmt = (select(column, func.coalesce(func.sum(PaymentAllocation.amount), 0))
            .where(column.is_not(None)))
    if until is not None:
        stmt = stmt.where(PaymentAllocation.applied_on <= until)
    return {i: money(v) for i, v in db.execute(stmt.group_by(column)).all()}


def allocated_by_payment(db: Session, until: date | None = None) -> dict[int, Decimal]:
    """How much of each receipt or payment has been settled against a document."""
    return _allocated(db, PaymentAllocation.payment_id, until)


def received_by_invoice(db: Session) -> dict[int, Decimal]:
    """Money settled against each invoice, from direct payments and allocations."""
    out = {i: money(v) for i, v in db.execute(
        select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.kind == RECEIPT, Payment.invoice_id.is_not(None))
        .group_by(Payment.invoice_id)).all()}
    for invoice_id, amount in _allocated(db, PaymentAllocation.invoice_id).items():
        out[invoice_id] = money(out.get(invoice_id, ZERO) + amount)
    return out


def receipt_movements(db: Session, until: date | None = None) -> dict[int, list[tuple[date, Decimal]]]:
    """When each invoice was paid, for a windowed statement.

    A receipt recorded directly against an invoice counts on its payment day; a
    settlement added later counts on the day it was applied, which is what makes
    an advance and a settlement separable at any date.
    """
    out: dict[int, list[tuple[date, Decimal]]] = {}
    stmt = select(Payment).where(Payment.kind == RECEIPT, Payment.invoice_id.is_not(None))
    if until is not None:
        stmt = stmt.where(Payment.paid_on <= until)
    for pay in db.scalars(stmt).all():
        out.setdefault(pay.invoice_id, []).append((pay.paid_on, money(pay.amount)))
    stmt = (select(PaymentAllocation).where(PaymentAllocation.invoice_id.is_not(None)))
    if until is not None:
        stmt = stmt.where(PaymentAllocation.applied_on <= until)
    for row in db.scalars(stmt).all():
        out.setdefault(row.invoice_id, []).append((row.applied_on, money(row.amount)))
    return out


def noted_by_invoice(db: Session) -> dict[int, Decimal]:
    """Issued notes tied to an invoice, as a signed adjustment to what it owes.

    A credit note cancels part of the bill, whether the goods came back or the
    value was corrected, so it reduces the receivable by exactly what the
    distributor ledger and the trial balance already deduct. A debit note raises
    it. Leaving the notes out here made the outstanding list disagree with both
    statements - and let a receipt be recorded against money that was no longer
    owed (COR-012).
    """
    out: dict[int, Decimal] = {}
    for cn in db.scalars(select(CreditNote).where(CreditNote.status == "issued",
                                                  CreditNote.invoice_id.is_not(None))).all():
        out[cn.invoice_id] = money(out.get(cn.invoice_id, ZERO) - _grand(cn))
    for dn in db.scalars(select(DebitNote).where(DebitNote.status == "issued",
                                                 DebitNote.invoice_id.is_not(None))).all():
        out[dn.invoice_id] = money(out.get(dn.invoice_id, ZERO) + _grand(dn))
    return out


def receivable_rows(db: Session) -> list[dict]:
    """Every issued invoice with what has been received and noted against it."""
    received = received_by_invoice(db)
    noted = noted_by_invoice(db)
    names = dict(db.execute(select(Distributor.id, Distributor.name)).all())
    rows = []
    for inv in db.scalars(select(Invoice).where(Invoice.status == "issued")
                          .order_by(Invoice.invoice_date, Invoice.id)).all():
        got = received.get(inv.id, ZERO)
        adjusted = noted.get(inv.id, ZERO)
        rows.append({
            "invoice_id": inv.id,
            "number": inv.invoice_number,
            "date": inv.invoice_date,
            "distributor_id": inv.distributor_id,
            "distributor": names.get(inv.distributor_id),
            "grand_total": _grand(inv),
            "adjusted": adjusted,
            "received": got,
            "outstanding": money(_grand(inv) + adjusted - got),
            "payment_terms_days": inv.payment_terms_days,
            "due_date": inv.due_date,
        })
    return rows


def received_value_by_po(db: Session) -> dict[int, Decimal]:
    """The cost of the goods actually received against each purchase order.

    Goods receipts record quantities, not prices, so the value comes from the
    order line's unit cost. Each receipt line is counted once, and a receipt can
    never exceed the ordered quantity (the receipt endpoint refuses it).
    """
    rows = db.execute(
        select(GoodsReceipt.po_id, GoodsReceiptLine.product_id,
               func.coalesce(func.sum(GoodsReceiptLine.qty), 0))
        .join(GoodsReceiptLine, GoodsReceiptLine.grn_id == GoodsReceipt.id)
        .group_by(GoodsReceipt.po_id, GoodsReceiptLine.product_id)).all()
    costs = {(line.po_id, line.product_id): money(line.unit_cost)
             for line in db.scalars(select(PurchaseOrderLine)).all()}
    out: dict[int, Decimal] = {}
    for po_id, product_id, qty in rows:
        unit = costs.get((po_id, product_id))
        if unit is None:
            continue
        out[po_id] = out.get(po_id, ZERO) + money(qty * unit)
    return out


def paid_by_po(db: Session) -> dict[int, Decimal]:
    out = {i: money(v) for i, v in db.execute(
        select(Payment.purchase_order_id, func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.kind == PAYMENT, Payment.purchase_order_id.is_not(None))
        .group_by(Payment.purchase_order_id)).all()}
    for po_id, amount in _allocated(db, PaymentAllocation.purchase_order_id).items():
        out[po_id] = money(out.get(po_id, ZERO) + amount)
    return out


def payable_rows(db: Session) -> list[dict]:
    received = received_value_by_po(db)
    paid = paid_by_po(db)
    names = dict(db.execute(select(Supplier.id, Supplier.name)).all())
    terms = dict(db.execute(select(Supplier.id, Supplier.payment_terms_days)).all())
    last_receipt = {
        po_id: (stamp.date() if hasattr(stamp, "date") else stamp)
        for po_id, stamp in db.execute(
            select(GoodsReceipt.po_id, func.max(GoodsReceipt.received_at))
            .group_by(GoodsReceipt.po_id)).all()}
    rows = []
    for po in db.scalars(select(PurchaseOrder).order_by(PurchaseOrder.id)).all():
        value = received.get(po.id, ZERO)
        if value <= 0:
            continue                      # nothing has arrived, so nothing is owed
        got = paid.get(po.id, ZERO)
        received_on = last_receipt.get(po.id)
        term_days = int(terms.get(po.supplier_id, 30) or 0)
        due_on = (received_on + timedelta(days=term_days)) if received_on else None
        rows.append({
            "purchase_order_id": po.id,
            "number": po.po_number,
            "supplier_id": po.supplier_id,
            "supplier": names.get(po.supplier_id) or po.supplier,
            "received_value": value,
            "paid": got,
            "outstanding": money(value - got),
            "received_on": received_on,
            "terms_days": term_days,
            "due_on": due_on,
        })
    return rows


# --------------------------------------------------------------- ageing
BUCKETS: tuple[tuple[str, str, int, int | None], ...] = (
    # key, label, first day, last day (None = open-ended)
    ("0-30", "0-30 days", 0, 30),
    ("31-60", "31-60 days", 31, 60),
    ("61-90", "61-90 days", 61, 90),
    ("90+", "90+ days", 91, None),
)


# How far ahead "due this week" reaches, counted from the as-at day inclusive.
DUE_SOON_DAYS = 7


def ageing_rows(db: Session, as_of: date | None = None) -> dict:
    """Outstanding invoices grouped by age, with their due dates alongside.

    The four buckets still age from the invoice date, so a figure can be
    compared with earlier statements; the due date is a second measure, not a
    replacement. Each row carries the invoice's due date (captured from the
    distributor's terms at issue, GAP-A04), how many days overdue it is, and a
    `due` summary splits the outstanding total into overdue, due within a week,
    later, and no due date at all. An invoice issued before a term was captured
    has no due date and is counted as such rather than being given an assumed
    one.

    Amounts come from `receivable_rows()`, so they are net of credit notes and
    debit notes: a return moves the invoice into the bucket its remaining
    balance belongs to, exactly as the outstanding list, the ledger and the
    trial balance show it (COR-012). Settled invoices are left out entirely.
    """
    day = as_of or date.today()
    buckets = [{"key": key, "label": label, "first": first, "last": last,
                "total": ZERO, "count": 0, "rows": []}
               for key, label, first, last in BUCKETS]
    due = {key: {"total": ZERO, "count": 0}
           for key in ("overdue", "due_this_week", "not_yet_due", "no_due_date")}
    soon = day + timedelta(days=DUE_SOON_DAYS)

    for row in receivable_rows(db):
        outstanding = money(row["outstanding"])
        if outstanding <= 0:
            continue
        days = max(0, (day - row["date"]).days)
        bucket = next(b for b in buckets if b["last"] is None or days <= b["last"])
        due_date = row.get("due_date")
        overdue_by = (day - due_date).days if due_date is not None and due_date < day else 0
        bucket["rows"].append({
            "invoice_id": row["invoice_id"],
            "number": row["number"],
            "date": row["date"],
            "distributor_id": row["distributor_id"],
            "distributor": row["distributor"],
            "days": days,
            "due_date": due_date,
            "days_overdue": overdue_by,
            "outstanding": outstanding,
        })
        bucket["total"] = money(bucket["total"] + outstanding)
        bucket["count"] += 1
        if due_date is None:
            key = "no_due_date"
        elif due_date < day:
            key = "overdue"
        elif due_date <= soon:
            key = "due_this_week"
        else:
            key = "not_yet_due"
        due[key]["total"] = money(due[key]["total"] + outstanding)
        due[key]["count"] += 1

    for bucket in buckets:
        bucket["rows"].sort(key=lambda r: (-r["days"], r["number"]))
    return {
        "as_of": day,
        "buckets": buckets,
        "total": money(sum((b["total"] for b in buckets), ZERO)),
        "count": sum(b["count"] for b in buckets),
        "due": due,
    }


def advance_balance(db: Session, kind: str, party_id: int) -> Decimal:
    """Money received or paid that is still unapplied for this party.

    A receipt or payment recorded before allocations existed named its invoice
    or order outright, so it counts as fully settled; only the remainder of a
    general entry stays available.
    """
    settled = allocated_by_payment(db)
    column = Payment.distributor_id if kind == RECEIPT else Payment.supplier_id
    total = ZERO
    for pay in db.scalars(select(Payment).where(Payment.kind == kind,
                                                column == party_id)).all():
        if pay.invoice_id is not None or pay.purchase_order_id is not None:
            continue
        amount = money(pay.amount)
        total = money(total + max(amount - settled.get(pay.id, ZERO), ZERO))
    return total


# ------------------------------------------------------------------ ledgers
def distributor_ledger(db: Session, distributor_id: int) -> dict:
    name = db.scalar(select(Distributor.name).where(Distributor.id == distributor_id))
    entries = []
    for inv in db.scalars(select(Invoice).where(Invoice.distributor_id == distributor_id,
                                                Invoice.status == "issued")).all():
        entries.append({"date": inv.invoice_date, "document": inv.invoice_number,
                        "kind": "invoice", "debit": _grand(inv), "credit": ZERO,
                        "note": None, "ref_id": inv.id})
    for cn in db.scalars(select(CreditNote).where(CreditNote.distributor_id == distributor_id,
                                                  CreditNote.status == "issued")).all():
        entries.append({"date": cn.note_date, "document": cn.credit_note_number,
                        "kind": "credit_note", "debit": ZERO, "credit": _grand(cn),
                        "note": cn.reason, "ref_id": cn.id})
    for dn in db.scalars(select(DebitNote).where(DebitNote.distributor_id == distributor_id,
                                                 DebitNote.status == "issued")).all():
        entries.append({"date": dn.note_date, "document": dn.debit_note_number,
                        "kind": "debit_note", "debit": _grand(dn), "credit": ZERO,
                        "note": dn.reason, "ref_id": dn.id})
    # The receipt row already credits the whole amount against the invoices
    # above, so a settlement is shown in its note rather than as a second
    # debit that would count the money twice.
    settled: dict[int, list[tuple[str, Decimal]]] = {}
    for pay_id, number, applied in db.execute(
            select(PaymentAllocation.payment_id, Invoice.invoice_number,
                   PaymentAllocation.amount)
            .join(Invoice, Invoice.id == PaymentAllocation.invoice_id)
            .where(PaymentAllocation.invoice_id.is_not(None))).all():
        settled.setdefault(pay_id, []).append((number, money(applied)))
    for pay in db.scalars(select(Payment).where(Payment.kind == RECEIPT,
                                                Payment.distributor_id == distributor_id)).all():
        amount = money(pay.amount)
        parts = [pay.reference or pay.mode]
        rows = settled.get(pay.id, [])
        if rows:
            parts.append("settled " + ", ".join(f"{n} ₹{money(a)}" for n, a in rows))
            excess = money(amount - sum((a for _, a in rows), ZERO))
            if excess > 0:
                parts.append(f"₹{money(excess)} held as advance")
        entries.append({"date": pay.paid_on, "document": pay.number, "kind": "receipt",
                        "debit": ZERO, "credit": amount,
                        "note": " · ".join(p for p in parts if p), "ref_id": pay.id})
    entries.sort(key=lambda e: (e["date"], e["document"]))
    balance = ZERO
    for entry in entries:
        balance = money(balance + entry["debit"] - entry["credit"])
        entry["balance"] = balance
    return {"party": name, "party_id": distributor_id, "entries": entries,
            "closing_balance": balance,
            "available_advance": advance_balance(db, RECEIPT, distributor_id)}


def supplier_ledger(db: Session, supplier_id: int) -> dict:
    name = db.scalar(select(Supplier.name).where(Supplier.id == supplier_id))
    received = received_value_by_po(db)
    entries = []
    for po in db.scalars(select(PurchaseOrder)
                         .where(PurchaseOrder.supplier_id == supplier_id)).all():
        value = received.get(po.id, ZERO)
        if value <= 0:
            continue
        entries.append({"date": po.created_at.date() if po.created_at else None,
                        "document": po.po_number, "kind": "goods_received",
                        "debit": ZERO, "credit": value, "note": "at order cost",
                        "ref_id": po.id})
    settled: dict[int, list[tuple[str, Decimal]]] = {}
    for pay_id, number, applied in db.execute(
            select(PaymentAllocation.payment_id, PurchaseOrder.po_number,
                   PaymentAllocation.amount)
            .join(PurchaseOrder, PurchaseOrder.id == PaymentAllocation.purchase_order_id)
            .where(PaymentAllocation.purchase_order_id.is_not(None))).all():
        settled.setdefault(pay_id, []).append((number, money(applied)))
    for pay in db.scalars(select(Payment).where(Payment.kind == "payment",
                                                Payment.supplier_id == supplier_id)).all():
        amount = money(pay.amount)
        parts = [pay.reference or pay.mode]
        rows = settled.get(pay.id, [])
        if rows:
            parts.append("settled " + ", ".join(f"{n} ₹{money(a)}" for n, a in rows))
            excess = money(amount - sum((a for _, a in rows), ZERO))
            if excess > 0:
                parts.append(f"₹{money(excess)} still held as advance")
        entries.append({"date": pay.paid_on, "document": pay.number, "kind": "payment",
                        "debit": amount, "credit": ZERO,
                        "note": " · ".join(p for p in parts if p), "ref_id": pay.id})
    entries.sort(key=lambda e: (e["date"] or date.min, e["document"]))
    balance = ZERO
    for entry in entries:
        balance = money(balance + entry["credit"] - entry["debit"])
        entry["balance"] = balance
    return {"party": name, "party_id": supplier_id, "entries": entries,
            "closing_balance": balance,
            "available_advance": advance_balance(db, PAYMENT, supplier_id)}


# ------------------------------------------------------------ GST registers
def gst_register(db: Session, date_from: date | None = None,
                 date_to: date | None = None) -> dict:
    """Outward supplies in the shape of the GSTR-1 sections, from the documents."""

    def within(day) -> bool:
        return (date_from is None or day >= date_from) and (date_to is None or day <= date_to)

    b2b, credit, debit = [], [], []
    for inv in db.scalars(select(Invoice).where(Invoice.status == "issued")).all():
        if not within(inv.invoice_date):
            continue
        b2b.append({"number": inv.invoice_number, "date": inv.invoice_date,
                    "party": inv.buyer_name, "gstin": inv.buyer_gstin,
                    "place_of_supply": inv.place_of_supply_state_code,
                    "kind": inv.place_of_supply_kind,
                    "taxable": money(inv.taxable_value), "cgst": money(inv.cgst_total),
                    "sgst": money(inv.sgst_total), "igst": money(inv.igst_total),
                    "cess": money(inv.cess_total), "total": _grand(inv)})
    for cn in db.scalars(select(CreditNote).where(CreditNote.status == "issued")).all():
        if not within(cn.note_date):
            continue
        credit.append({"number": cn.credit_note_number, "date": cn.note_date,
                       "taxable": money(cn.taxable_value), "cgst": money(cn.cgst_total),
                       "sgst": money(cn.sgst_total), "igst": money(cn.igst_total),
                       "cess": money(cn.cess_total), "total": _grand(cn)})
    for dn in db.scalars(select(DebitNote).where(DebitNote.status == "issued")).all():
        if not within(dn.note_date):
            continue
        debit.append({"number": dn.debit_note_number, "date": dn.note_date,
                      "taxable": money(dn.taxable_value), "cgst": money(dn.cgst_total),
                      "sgst": money(dn.sgst_total), "igst": money(dn.igst_total),
                      "cess": money(dn.cess_total), "total": _grand(dn)})

    def total(rows, key, sign=1) -> Decimal:
        return money(sum((r[key] for r in rows), ZERO) * sign)

    keys = ("taxable", "cgst", "sgst", "igst", "cess", "total")
    totals = {k: money(total(b2b, k) + total(debit, k) - total(credit, k)) for k in keys}
    return {
        "from": date_from, "to": date_to,
        "b2b": b2b, "credit_notes": credit, "debit_notes": debit,
        "totals": totals,
        "input_register": None,
        "note": ("Outward supplies only. Input GST, net payable and the comparison "
                 "with a filed return are built from captured supplier bills by "
                 "`app/services/gst.py`. This is a reconciliation aid, not a filing file."),
    }


# ------------------------------------------------------------ trial balance
def trial_balance(db: Session, as_of: date | None = None) -> dict:
    """A double-entry summary built from the documents, and a balance check.

    Every document contributes both sides, so the totals must agree. A mismatch
    is reported rather than hidden: it would mean a document stores figures that
    do not add up.
    """
    post: dict[str, dict[str, Decimal]] = OrderedDict()

    def add(account: str, debit=ZERO, credit=ZERO) -> None:
        row = post.setdefault(account, {"debit": ZERO, "credit": ZERO})
        row["debit"] = money(row["debit"] + money(debit))
        row["credit"] = money(row["credit"] + money(credit))

    def dated(day) -> bool:
        return as_of is None or day <= as_of

    def round_off_of(document) -> Decimal:
        return money(_grand(document) - (money(document.taxable_value)
                                         + money(document.tax_total)))

    for inv in db.scalars(select(Invoice).where(Invoice.status == "issued")).all():
        if not dated(inv.invoice_date):
            continue
        add("Receivables", debit=_grand(inv))
        add("Sales", credit=money(inv.taxable_value))
        add("Output CGST", credit=money(inv.cgst_total))
        add("Output SGST", credit=money(inv.sgst_total))
        add("Output IGST", credit=money(inv.igst_total))
        adjustment = round_off_of(inv)
        if adjustment > 0:
            add("Round off", credit=adjustment)
        elif adjustment < 0:
            add("Round off", debit=abs(adjustment))

    for cn in db.scalars(select(CreditNote).where(CreditNote.status == "issued")).all():
        if not dated(cn.note_date):
            continue
        add("Receivables", credit=_grand(cn))
        add("Sales", debit=money(cn.taxable_value))
        add("Output CGST", debit=money(cn.cgst_total))
        add("Output SGST", debit=money(cn.sgst_total))
        add("Output IGST", debit=money(cn.igst_total))
        adjustment = round_off_of(cn)
        if adjustment > 0:
            add("Round off", debit=adjustment)
        elif adjustment < 0:
            add("Round off", credit=abs(adjustment))

    for dn in db.scalars(select(DebitNote).where(DebitNote.status == "issued")).all():
        if not dated(dn.note_date):
            continue
        add("Receivables", debit=_grand(dn))
        add("Sales", credit=money(dn.taxable_value))
        add("Output CGST", credit=money(dn.cgst_total))
        add("Output SGST", credit=money(dn.sgst_total))
        add("Output IGST", credit=money(dn.igst_total))
        adjustment = round_off_of(dn)
        if adjustment > 0:
            add("Round off", credit=adjustment)
        elif adjustment < 0:
            add("Round off", debit=abs(adjustment))

    # Money in and out; the mode decides which account it moved through. The part
    # settled against an invoice or bill clears the receivable/payable; the rest
    # is an advance, carried on its own head so it never reads as sales or
    # purchases. A payment recorded before allocations existed was fully settled
    # by definition (it named its invoice or order outright).
    settled = allocated_by_payment(db, as_of)
    stmt = select(Payment)
    if as_of is not None:
        stmt = stmt.where(Payment.paid_on <= as_of)
    for pay in db.scalars(stmt).all():
        amount = money(pay.amount)
        account = "Cash" if pay.mode == "cash" else "Bank"
        legacy = pay.invoice_id is not None or pay.purchase_order_id is not None
        allocated = amount if legacy else min(settled.get(pay.id, ZERO), amount)
        advance = money(amount - allocated)
        if pay.kind == RECEIPT:
            add(account, debit=amount)
            add("Receivables", credit=allocated)
            if advance > 0:
                add("Advances from distributors", credit=advance)
        else:
            add("Payables", debit=allocated)
            if advance > 0:
                add("Advances to suppliers", debit=advance)
            add(account, credit=amount)

    # Goods received: a purchase, owed to the supplier until paid.
    received = received_value_by_po(db)
    for po in db.scalars(select(PurchaseOrder)).all():
        value = received.get(po.id, ZERO)
        if value <= 0:
            continue
        add("Purchases", debit=value)
        add("Payables", credit=value)

    rows, debit_total, credit_total = [], ZERO, ZERO
    for account, amounts in post.items():
        net = money(amounts["debit"] - amounts["credit"])
        debit, credit = (net, ZERO) if net > 0 else (ZERO, -net)
        debit_total = money(debit_total + debit)
        credit_total = money(credit_total + credit)
        rows.append({"account": account, "debit": debit, "credit": credit})
    rows.sort(key=lambda r: r["account"])
    return {"as_of": as_of, "rows": rows, "debit_total": debit_total,
            "credit_total": credit_total, "balanced": debit_total == credit_total}
