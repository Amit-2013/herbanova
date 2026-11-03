"""Settling receipts and payments, and the advances left over.

Money can arrive before the invoice it pays for, and a distributor can pay more
than is open. Both cases are recorded on the payment itself: the part that
settles a document is a `PaymentAllocation`, and the remainder stays
unallocated on the payment as an advance. Allocating later only adds rows; the
payment is never edited, so the audit trail stays append-only.

The rules:

- A settlement never exceeds what is still outstanding on the document. Credit
  and debit notes are already in the outstanding figure, because it comes from
  `ledger.receivable_rows()`.
- Pending documents are settled oldest first. A caller may name one document to
  settle first; the rest of the money then goes to the older ones.
- Whatever is left is the advance. A receipt with nothing to settle is an
  advance in full, and so is a payment to a supplier whose goods have not
  arrived.
- An advance is applied to a document issued later only when that document
  exists, dated on the document's own day. It is never assumed against a
  document that does not exist, and it is never netted into sales or purchases.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.accounts import PAYMENT, RECEIPT, Payment, PaymentAllocation
from ..models.core import Invoice, PurchaseOrder
from . import ledger

ZERO = ledger.ZERO
money = ledger.money


# ------------------------------------------------------------------ queries
def allocated_by_payment(db: Session) -> dict[int, Decimal]:
    rows = db.execute(
        select(PaymentAllocation.payment_id,
               func.coalesce(func.sum(PaymentAllocation.amount), 0))
        .group_by(PaymentAllocation.payment_id)).all()
    return {payment_id: money(value) for payment_id, value in rows}


def allocation_rows(db: Session, payment_id: int) -> list[dict]:
    out = []
    for row in db.scalars(select(PaymentAllocation)
                          .where(PaymentAllocation.payment_id == payment_id)
                          .order_by(PaymentAllocation.applied_on, PaymentAllocation.id)).all():
        target = row.invoice.invoice_number if row.invoice_id else (
            row.purchase_order.po_number if row.purchase_order else None)
        out.append({"id": row.id, "invoice_id": row.invoice_id,
                    "purchase_order_id": row.purchase_order_id,
                    "number": target, "amount": money(row.amount),
                    "applied_on": row.applied_on})
    return out


def legacy_allocated(payment: Payment) -> Decimal:
    """A payment recorded against one document before allocations existed."""
    if payment.invoice_id is not None or payment.purchase_order_id is not None:
        return money(payment.amount)
    return ZERO


def payment_advance(payment: Payment, used: Decimal) -> Decimal:
    """What is left of the payment after what it settled; an advance, not a loss."""
    return max(money(money(payment.amount) - money(used)), ZERO)


def _party_payments(db: Session, kind: str, party_id: int,
                    on_or_before: date | None = None) -> list[Payment]:
    party = Payment.distributor_id if kind == RECEIPT else Payment.supplier_id
    stmt = (select(Payment).where(Payment.kind == kind, party == party_id)
            .order_by(Payment.paid_on, Payment.id))
    if on_or_before is not None:
        stmt = stmt.where(Payment.paid_on <= on_or_before)
    return list(db.scalars(stmt).all())


def available_entries(db: Session, kind: str, party_id: int,
                      on_or_before: date | None = None) -> list[dict]:
    """Advances still open, oldest first, as they stand at `on_or_before`."""
    allocated = allocated_by_payment(db)
    out = []
    for pay in _party_payments(db, kind, party_id, on_or_before):
        used = legacy_allocated(pay) + allocated.get(pay.id, ZERO)
        left = payment_advance(pay, used)
        if left <= 0:
            continue
        out.append({"payment": pay, "available": left})
    return out


def available(db: Session, kind: str, party_id: int) -> dict:
    entries = available_entries(db, kind, party_id)
    return {
        "kind": kind, "party_id": party_id,
        "available": money(sum((e["available"] for e in entries), ZERO)),
        "entries": [{"id": e["payment"].id, "number": e["payment"].number,
                     "paid_on": e["payment"].paid_on,
                     "amount": money(e["payment"].amount),
                     "available": e["available"],
                     "reference": e["payment"].reference}
                    for e in entries],
    }


# ------------------------------------------------------------------ settling
def _allocate(db: Session, payment: Payment, amount: Decimal, applied_on: date,
              invoice_id: int | None = None, purchase_order_id: int | None = None,
              actor_id: int | None = None) -> None:
    db.add(PaymentAllocation(
        payment_id=payment.id, invoice_id=invoice_id,
        purchase_order_id=purchase_order_id, amount=money(amount),
        applied_on=applied_on, created_by=actor_id))


def settle_receipt(db: Session, entry: Payment, preferred_invoice_id: int | None = None,
                   actor_id: int | None = None) -> dict:
    """Settle a receipt against the distributor's open invoices, oldest first.

    Only invoices issued on or before the receipt date can be settled: money
    received today cannot pay a bill that does not exist until next week. An
    advance settles such an invoice later, when it is issued.
    """
    rows = [r for r in ledger.receivable_rows(db)
            if r["distributor_id"] == entry.distributor_id
            and money(r["outstanding"]) > 0 and r["date"] <= entry.paid_on]
    if preferred_invoice_id is not None:
        rows.sort(key=lambda r: (r["invoice_id"] != preferred_invoice_id, r["date"],
                                 r["invoice_id"]))
    else:
        rows.sort(key=lambda r: (r["date"], r["invoice_id"]))

    remaining = money(entry.amount)
    settled = []
    for row in rows:
        if remaining <= 0:
            break
        amount = min(remaining, money(row["outstanding"]))
        if amount <= 0:
            continue
        _allocate(db, entry, amount, entry.paid_on, invoice_id=row["invoice_id"],
                  actor_id=actor_id)
        settled.append({"invoice_id": row["invoice_id"], "number": row["number"],
                        "amount": money(amount)})
        remaining = money(remaining - amount)
    db.flush()
    return {"allocations": settled, "advance": remaining}


def settle_payment(db: Session, entry: Payment, preferred_order_id: int | None = None,
                   actor_id: int | None = None) -> dict:
    """Settle a payment against the supplier's open orders, oldest first.

    Only orders whose goods were received on or before the payment date can be
    settled; an advance pays for goods received later, when the receipt exists.
    """
    rows = [r for r in ledger.payable_rows(db)
            if r["supplier_id"] == entry.supplier_id and money(r["outstanding"]) > 0
            and (r.get("received_on") is None or r["received_on"] <= entry.paid_on)]
    rows.sort(key=lambda r: (preferred_order_id is not None
                             and r["purchase_order_id"] != preferred_order_id,
                             r["purchase_order_id"]))

    remaining = money(entry.amount)
    settled = []
    for row in rows:
        if remaining <= 0:
            break
        amount = min(remaining, money(row["outstanding"]))
        if amount <= 0:
            continue
        _allocate(db, entry, amount, entry.paid_on,
                  purchase_order_id=row["purchase_order_id"], actor_id=actor_id)
        settled.append({"purchase_order_id": row["purchase_order_id"],
                        "number": row["number"], "amount": money(amount)})
        remaining = money(remaining - amount)
    db.flush()
    return {"allocations": settled, "advance": remaining}


# ------------------------------------------------- future documents
def apply_to_invoice(db: Session, invoice: Invoice, actor_id: int | None = None) -> list[dict]:
    """Use whatever advance the distributor has left against a newly issued invoice."""
    if invoice.status != "issued" or invoice.distributor_id is None:
        return []
    already = money(db.scalar(
        select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
        .where(PaymentAllocation.invoice_id == invoice.id)) or 0)
    outstanding = money(ledger.money(invoice.grand_total) - already)
    return _apply(db, RECEIPT, invoice.distributor_id, outstanding, invoice.invoice_date,
                  invoice_id=invoice.id, actor_id=actor_id)


def apply_to_purchase_order(db: Session, po: PurchaseOrder, on_date: date | None = None,
                            actor_id: int | None = None) -> list[dict]:
    """Use whatever advance the supplier holds against goods just received."""
    if po.supplier_id is None:
        return []
    value = ledger.received_value_by_po(db).get(po.id, ZERO)
    if value <= 0:
        return []
    paid = ledger.paid_by_po(db).get(po.id, ZERO)
    outstanding = money(value - paid)
    return _apply(db, PAYMENT, po.supplier_id, outstanding, on_date or date.today(),
                  purchase_order_id=po.id, actor_id=actor_id)


def _apply(db: Session, kind: str, party_id: int, outstanding: Decimal, applied_on: date,
           invoice_id: int | None = None, purchase_order_id: int | None = None,
           actor_id: int | None = None) -> list[dict]:
    left = money(outstanding)
    applied = []
    for entry in available_entries(db, kind, party_id, on_or_before=applied_on):
        if left <= 0:
            break
        amount = min(left, entry["available"])
        if amount <= 0:
            continue
        _allocate(db, entry["payment"], amount, applied_on, invoice_id=invoice_id,
                  purchase_order_id=purchase_order_id, actor_id=actor_id)
        applied.append({"payment_id": entry["payment"].id,
                        "number": entry["payment"].number, "amount": money(amount)})
        left = money(left - amount)
    if applied:
        db.flush()
    return applied
