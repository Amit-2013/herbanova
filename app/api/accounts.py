"""Accounts (Module Phase 6): receipts, payments and the statements built from them.

Reading needs `accounts:read`; recording money needs `accounts:write`. Nothing in
this router edits or deletes a record: a wrong entry is corrected by recording the
opposite one, so the statements stay rebuildable from the documents.

The rules enforced here:

- Money is recorded against a party, never against a bare account name.
- A receipt or payment is either allocated to what is open (the named document
  first, then the party's oldest documents) or held as an advance to the party.
  The part that settles a document never exceeds what is still outstanding on
  it; the rest is an advance and never becomes revenue or a purchase.
- A cancelled invoice cannot receive money, and a purchase order with nothing
  received owes nothing.
- Every entry is audited with its party, kind, purpose, allocations and advance.
"""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require
from ..models.accounts import MODES, PAYMENT, RECEIPT, Payment, PaymentAllocation
from ..models.core import Distributor, Invoice, PurchaseOrder
from ..models.suppliers import Supplier
from ..services import accounting, advances, periods
from ..services import ledger as svc
from ..services.audit import audit

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

# How a receipt or payment is meant: settle what is already open, or stand as an
# advance. An outstanding entry with nothing open is recorded as an advance too.
PURPOSES = ("outstanding", "advance")


class EntryIn(BaseModel):
    kind: str
    purpose: str | None = None
    distributor_id: int | None = None
    supplier_id: int | None = None
    invoice_id: int | None = None
    purchase_order_id: int | None = None
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    paid_on: date
    mode: str = "bank"
    reference: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=300)

    @field_validator("kind")
    @classmethod
    def check_kind(cls, v):
        if v not in (RECEIPT, PAYMENT):
            raise ValueError("kind must be receipt or payment")
        return v

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v):
        if v not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        return v

    @field_validator("purpose")
    @classmethod
    def check_purpose(cls, v):
        if v is not None and v not in PURPOSES:
            raise ValueError(f"purpose must be one of {', '.join(PURPOSES)}")
        return v

    @field_validator("reference", "notes")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) and v.strip() else None


class AllocationOut(BaseModel):
    invoice_id: int | None = None
    purchase_order_id: int | None = None
    number: str | None
    amount: Decimal
    applied_on: date


class EntryOut(BaseModel):
    id: int
    number: str
    kind: str
    party: str | None
    purpose: str
    distributor_id: int | None
    supplier_id: int | None
    invoice_id: int | None
    invoice_number: str | None
    purchase_order_id: int | None
    purchase_order_number: str | None
    amount: Decimal
    allocated: Decimal
    advance: Decimal
    allocations: list[AllocationOut]
    paid_on: date
    mode: str
    reference: str | None
    notes: str | None


def _entry_facts(db: Session, payment: Payment,
                 grouped: dict[int, list[dict]] | None = None) -> tuple[list[dict], Decimal, Decimal]:
    rows = grouped.get(payment.id, []) if grouped is not None else \
        advances.allocation_rows(db, payment.id)
    amount = svc.money(payment.amount)
    if payment.invoice_id is not None or payment.purchase_order_id is not None:
        return rows, amount, svc.money(0)
    allocated = svc.money(sum((r["amount"] for r in rows), Decimal("0.00")))
    return rows, allocated, svc.money(amount - allocated)


def _out(p: Payment, names: dict, invoices: dict, orders: dict,
         grouped: dict[int, list[dict]] | None = None) -> EntryOut:
    party = names.get(("distributor", p.distributor_id)) if p.distributor_id else \
        names.get(("supplier", p.supplier_id))
    rows, allocated, advance = _entry_facts(None, p, grouped)
    legacy = p.invoice_id is not None or p.purchase_order_id is not None
    purpose = "outstanding" if (legacy or rows) else "advance"
    return EntryOut(
        id=p.id, number=p.number, kind=p.kind, party=party, purpose=purpose,
        distributor_id=p.distributor_id, supplier_id=p.supplier_id,
        invoice_id=p.invoice_id, invoice_number=invoices.get(p.invoice_id),
        purchase_order_id=p.purchase_order_id,
        purchase_order_number=orders.get(p.purchase_order_id),
        amount=svc.money(p.amount), allocated=allocated, advance=advance,
        allocations=[AllocationOut(**row) for row in rows],
        paid_on=p.paid_on, mode=p.mode,
        reference=p.reference, notes=p.notes)


def _names(db: Session) -> dict:
    found = {("distributor", i): n for i, n in
             db.execute(select(Distributor.id, Distributor.name)).all()}
    found.update({("supplier", i): n for i, n in
                  db.execute(select(Supplier.id, Supplier.name)).all()})
    return found


def _grouped_allocations(db: Session, payment_ids: list[int]) -> dict[int, list[dict]]:
    if not payment_ids:
        return {}
    out: dict[int, list[dict]] = {}
    for row in db.scalars(select(PaymentAllocation)
                          .where(PaymentAllocation.payment_id.in_(payment_ids))
                          .order_by(PaymentAllocation.applied_on,
                                    PaymentAllocation.id)).all():
        target = row.invoice.invoice_number if row.invoice_id else (
            row.purchase_order.po_number if row.purchase_order else None)
        out.setdefault(row.payment_id, []).append(
            {"invoice_id": row.invoice_id, "purchase_order_id": row.purchase_order_id,
             "number": target, "amount": svc.money(row.amount),
             "applied_on": row.applied_on})
    return out


@router.get("/payments", response_model=list[EntryOut])
def list_entries(kind: str | None = None, date_from: date | None = None,
                 date_to: date | None = None, db: Session = Depends(get_db),
                 _=Depends(require("accounts:read"))):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date is after the end date")
    stmt = select(Payment).order_by(Payment.paid_on.desc(), Payment.id.desc())
    if kind in (RECEIPT, PAYMENT):
        stmt = stmt.where(Payment.kind == kind)
    if date_from is not None:
        stmt = stmt.where(Payment.paid_on >= date_from)
    if date_to is not None:
        stmt = stmt.where(Payment.paid_on <= date_to)
    rows = db.scalars(stmt.limit(500)).all()
    names = _names(db)
    invoices = dict(db.execute(select(Invoice.id, Invoice.invoice_number)).all())
    orders = dict(db.execute(select(PurchaseOrder.id, PurchaseOrder.po_number)).all())
    grouped = _grouped_allocations(db, [p.id for p in rows])
    return [_out(p, names, invoices, orders, grouped) for p in rows]


@router.post("/payments", response_model=EntryOut, status_code=201)
def record_entry(body: EntryIn, db: Session = Depends(get_db),
                 user=Depends(require("accounts:write"))):
    """Record a receipt or a payment, settling what is open or holding an advance.

    An outstanding entry settles the named document first and then the party's
    oldest open documents; any remainder is an advance. An advance entry settles
    nothing and stays available on the party's ledger for a later invoice or bill.
    """
    if body.paid_on > date.today():
        raise HTTPException(422, "The date cannot be in the future")
    if body.paid_on < date.today() - timedelta(days=3650):
        raise HTTPException(422, "The date is more than ten years ago")
    try:
        periods.refuse_if_closed(db, body.paid_on,
                                 "a receipt" if body.kind == RECEIPT else "a payment")
    except periods.PeriodClosed as exc:
        raise HTTPException(423, str(exc))

    named = body.invoice_id is not None if body.kind == RECEIPT \
        else body.purchase_order_id is not None
    purpose = body.purpose or ("outstanding" if named else "advance")
    if purpose == "advance" and named:
        raise HTTPException(
            422, "An advance is not tied to an invoice or order; record it against the party")

    if body.kind == RECEIPT:
        if body.supplier_id is not None or body.purchase_order_id is not None:
            raise HTTPException(422, "A receipt is recorded against a distributor, not a supplier")
        distributor_id = body.distributor_id
        if body.invoice_id is not None:
            inv = db.get(Invoice, body.invoice_id)
            if inv is None:
                raise HTTPException(404, "Invoice not found")
            if inv.status != "issued":
                raise HTTPException(422, "That invoice was cancelled; it cannot receive money")
            if distributor_id is not None and distributor_id != inv.distributor_id:
                raise HTTPException(422, "The invoice belongs to a different distributor")
            distributor_id = inv.distributor_id
            outstanding = next(r["outstanding"] for r in svc.receivable_rows(db)
                               if r["invoice_id"] == inv.id)
            if outstanding <= 0:
                raise HTTPException(
                    422, f"Nothing is outstanding on {inv.invoice_number}: it is settled, "
                         "or its credit notes have cancelled the balance")
        if distributor_id is None:
            raise HTTPException(422, "A receipt needs a distributor, or an invoice to derive one")
        if db.get(Distributor, distributor_id) is None:
            raise HTTPException(404, "Distributor not found")
    else:
        if body.distributor_id is not None or body.invoice_id is not None:
            raise HTTPException(422, "A payment is recorded against a supplier, not a distributor")
        supplier_id = body.supplier_id
        if body.purchase_order_id is not None:
            po = db.get(PurchaseOrder, body.purchase_order_id)
            if po is None:
                raise HTTPException(404, "Purchase order not found")
            if po.supplier_id is None:
                raise HTTPException(422, "That purchase order has no supplier record")
            if supplier_id is not None and supplier_id != po.supplier_id:
                raise HTTPException(422, "The purchase order belongs to a different supplier")
            supplier_id = po.supplier_id
            payable = next((r for r in svc.payable_rows(db)
                            if r["purchase_order_id"] == po.id), None)
            if payable is None:
                raise HTTPException(422, "Nothing has been received against that order")
        if supplier_id is None:
            raise HTTPException(422, "A payment needs a supplier, or an order to derive one")
        if db.get(Supplier, supplier_id) is None:
            raise HTTPException(404, "Supplier not found")

    # New entries are settled through allocation rows, never the legacy link, so
    # an advance drawn down later can be dated and never rewrites the receipt.
    entry = Payment(
        kind=body.kind,
        distributor_id=distributor_id if body.kind == RECEIPT else None,
        supplier_id=supplier_id if body.kind == PAYMENT else None,
        invoice_id=None, purchase_order_id=None,
        amount=svc.money(body.amount), paid_on=body.paid_on, mode=body.mode,
        reference=body.reference, notes=body.notes, created_by=user.id)
    db.add(entry)
    db.flush()

    if purpose == "advance":
        result = {"allocations": [], "advance": svc.money(entry.amount)}
    elif body.kind == RECEIPT:
        result = advances.settle_receipt(db, entry, body.invoice_id, user.id)
    else:
        result = advances.settle_payment(db, entry, body.purchase_order_id, user.id)

    audit(db, user.id, f"accounts.{body.kind}", f"payment:{entry.id}",
          {"kind": body.kind, "purpose": purpose,
           "amount": str(svc.money(body.amount)),
           "distributor_id": entry.distributor_id, "supplier_id": entry.supplier_id,
           "mode": body.mode, "paid_on": body.paid_on.isoformat(),
           "allocations": [{"invoice_id": a.get("invoice_id"),
                            "purchase_order_id": a.get("purchase_order_id"),
                            "amount": str(a["amount"])} for a in result["allocations"]],
           "advance": str(svc.money(result["advance"]))})
    db.commit()
    names = _names(db)
    invoices = dict(db.execute(select(Invoice.id, Invoice.invoice_number)).all())
    orders = dict(db.execute(select(PurchaseOrder.id, PurchaseOrder.po_number)).all())
    grouped = _grouped_allocations(db, [entry.id])
    return _out(entry, names, invoices, orders, grouped)


@router.get("/advances")
def party_advances(kind: str = Query(default=RECEIPT), party_id: int = Query(...),
                   db: Session = Depends(get_db),
                   _=Depends(require("accounts:read"))):
    """The unapplied money a distributor or supplier is holding, oldest first."""
    if kind not in (RECEIPT, PAYMENT):
        raise HTTPException(422, "kind must be receipt or payment")
    if kind == RECEIPT and db.get(Distributor, party_id) is None:
        raise HTTPException(404, "Distributor not found")
    if kind == PAYMENT and db.get(Supplier, party_id) is None:
        raise HTTPException(404, "Supplier not found")
    return advances.available(db, kind, party_id)


@router.get("/outstanding")
def outstanding(db: Session = Depends(get_db), _=Depends(require("accounts:read"))):
    """What distributors owe and what the business owes suppliers, invoice by invoice."""
    recv = svc.receivable_rows(db)
    pay_ = svc.payable_rows(db)
    return {
        "receivables": recv,
        "payables": pay_,
        "receivable_total": sum((r["outstanding"] for r in recv), Decimal("0.00")),
        "payable_total": sum((r["outstanding"] for r in pay_), Decimal("0.00")),
    }


@router.get("/ledger/distributors/{distributor_id}")
def distributor_ledger(distributor_id: int, db: Session = Depends(get_db),
                       _=Depends(require("accounts:read"))):
    ledger = svc.distributor_ledger(db, distributor_id)
    if ledger["party"] is None:
        raise HTTPException(404, "Distributor not found")
    return ledger


@router.get("/ledger/suppliers/{supplier_id}")
def supplier_ledger(supplier_id: int, db: Session = Depends(get_db),
                    _=Depends(require("accounts:read"))):
    ledger = svc.supplier_ledger(db, supplier_id)
    if ledger["party"] is None:
        raise HTTPException(404, "Supplier not found")
    return ledger


@router.get("/ageing")
def ageing(as_of: date | None = Query(default=None), db: Session = Depends(get_db),
           _=Depends(require("accounts:read"))):
    """Outstanding invoices in four buckets: 0-30, 31-60, 61-90 and 90+ days
    since the invoice date, measured at `as_of` (today by default)."""
    return svc.ageing_rows(db, as_of)


@router.get("/receivables-by-distributor")
def receivables_by_distributor(from_date: date | None = None,
                               to_date: date | None = None,
                               db: Session = Depends(get_db),
                               _=Depends(require("accounts:read"))):
    """What each distributor owed across a window: opening, movements, closing.

    The full statements are on accounts:read, and this report is built from the
    same issued invoices, notes and allocated receipts, so it reconciles with
    the outstanding list and the ageing instead of keeping a second set of
    figures. `to_date` is the as-at day; `from_date` starts the movement window.
    """
    start, end = _window(from_date, to_date)
    return accounting.receivables_by_distributor_window(db, start, end)


@router.get("/gst-register")
def gst_register(date_from: date | None = Query(default=None),
                 date_to: date | None = Query(default=None),
                 db: Session = Depends(get_db), _=Depends(require("accounts:read"))):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date is after the end date")
    return svc.gst_register(db, date_from, date_to)


@router.get("/trial-balance")
def trial_balance(as_of: date | None = Query(default=None),
                  db: Session = Depends(get_db), _=Depends(require("accounts:read"))):
    return svc.trial_balance(db, as_of)


# ------------------------------------------------- accounts dashboard (D-39)
def _window(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    today = date.today()
    end = to_date or today
    start = from_date or end.replace(day=1)
    if end > today:
        raise HTTPException(422, "to_date cannot be in the future")
    if start > end:
        raise HTTPException(422, "from_date cannot be after to_date")
    return start, end


@router.get("/report")
def account_report(from_date: date | None = None, to_date: date | None = None,
                   state: str | None = Query(default=None, min_length=2, max_length=2),
                   db: Session = Depends(get_db),
                   _=Depends(require("accounts:reports"))):
    """The Accounts dashboard for one window, with the monthly trend and regions.

    The full statements stay on `accounts:read`; this report is the narrower
    right the Administrator grants to the MD or an Accounts head (D-39).
    """
    if state is not None and not state.isdigit():
        raise HTTPException(422, "state must be a two-digit GST state code")
    start, end = _window(from_date, to_date)
    return accounting.report(db, start, end, state=state)


@router.get("/report/compare")
def account_compare(mode: str = "full_month", month: str | None = None,
                    db: Session = Depends(get_db),
                    _=Depends(require("accounts:reports"))):
    """Month-on-month and year-on-year Accounts figures, full month or month to date."""
    if mode not in ("full_month", "mtd"):
        raise HTTPException(422, "mode must be full_month or mtd")
    from ..api.dashboard import _parse_month

    return accounting.compare(db, mode, _parse_month(month, date.today()), date.today())
