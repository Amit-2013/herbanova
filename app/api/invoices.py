"""Invoices API (Module Phase 4, FR-14).

An issued invoice is immutable: there is no update or delete endpoint. What can
change after issue is limited to things that do not alter the financial
snapshot: the delivery challan and e-way bill details of the movement, and
cancellation with a reason (which keeps the document and its number). Value
corrections go through credit and debit notes.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, exists, func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.pagination import page_params, paginate
from ..core.rbac import require, require_admin
from ..models.core import (Batch, CreditNote, DebitNote, Invoice, InvoiceLine, SalesOrder,
                           StockMovement)
from ..services import periods
from ..services.audit import audit

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


class InvoiceLineOut(BaseModel):
    id: int
    invoice_line_id: int
    sku: str
    product_name: str
    hsn: str | None = None
    uqc: str | None = None
    qty: Decimal
    unit_price: Decimal
    mrp: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    taxable_value: Decimal
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    cess_rate: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    cess_amount: Decimal
    line_total: Decimal
    expiry: date | None = None


class InvoiceOut(BaseModel):
    id: int
    invoice_number: str
    financial_year: str
    sales_order_id: int
    so_number: str | None = None
    distributor_id: int
    status: str
    invoice_date: date
    place_of_supply_state_code: str
    place_of_supply_kind: str
    reverse_charge: bool
    seller_legal_name: str
    seller_gstin: str | None = None
    seller_pan: str | None = None
    seller_state_code: str | None = None
    buyer_name: str
    buyer_gstin: str | None = None
    buyer_state_code: str | None = None
    gross_total: Decimal
    discount_total: Decimal
    taxable_value: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    cess_total: Decimal
    tax_total: Decimal
    round_off: Decimal
    grand_total: Decimal
    amount_in_words: str | None = None
    copy_designation: str
    notes: list | None = None
    delivery_challan_number: str | None = None
    vehicle_number: str | None = None
    transporter_name: str | None = None
    eway_bill_number: str | None = None
    eway_bill_date: date | None = None
    payment_terms_days: int | None = None
    due_date: date | None = None
    cancel_reason: str | None = None
    cancelled_at: datetime | None = None
    credit_note_total: Decimal = Decimal(0)
    debit_note_total: Decimal = Decimal(0)
    lines: list[InvoiceLineOut]


def _build_invoice(inv: Invoice, so_map: dict[int, str]) -> InvoiceOut:
    return InvoiceOut(
        id=inv.id,
        invoice_number=inv.invoice_number,
        financial_year=inv.financial_year,
        sales_order_id=inv.sales_order_id,
        so_number=so_map.get(inv.sales_order_id),
        distributor_id=inv.distributor_id,
        status=inv.status,
        invoice_date=inv.invoice_date,
        place_of_supply_state_code=inv.place_of_supply_state_code,
        place_of_supply_kind=inv.place_of_supply_kind,
        reverse_charge=inv.reverse_charge,
        seller_legal_name=inv.seller_legal_name,
        seller_gstin=inv.seller_gstin,
        seller_pan=inv.seller_pan,
        seller_state_code=inv.seller_state_code,
        buyer_name=inv.buyer_name,
        buyer_gstin=inv.buyer_gstin,
        buyer_state_code=inv.buyer_state_code,
        gross_total=inv.gross_total,
        discount_total=inv.discount_total,
        taxable_value=inv.taxable_value,
        cgst_total=inv.cgst_total,
        sgst_total=inv.sgst_total,
        igst_total=inv.igst_total,
        cess_total=inv.cess_total,
        tax_total=inv.tax_total,
        round_off=inv.round_off,
        grand_total=inv.grand_total,
        amount_in_words=inv.amount_in_words,
        copy_designation=inv.copy_designation,
        notes=inv.notes,
        delivery_challan_number=inv.delivery_challan_number,
        vehicle_number=inv.vehicle_number,
        transporter_name=inv.transporter_name,
        eway_bill_number=inv.eway_bill_number,
        eway_bill_date=inv.eway_bill_date,
        payment_terms_days=inv.payment_terms_days,
        due_date=inv.due_date,
        cancel_reason=inv.cancel_reason,
        cancelled_at=inv.cancelled_at,
        lines=[
            InvoiceLineOut(
                id=ln.id,
                invoice_line_id=ln.id,
                sku=ln.sku,
                product_name=ln.product_name,
                hsn=ln.hsn,
                uqc=ln.uqc,
                qty=ln.qty,
                unit_price=ln.unit_price,
                mrp=ln.mrp,
                discount_percent=ln.discount_percent,
                discount_amount=ln.discount_amount,
                taxable_value=ln.taxable_value,
                cgst_rate=ln.cgst_rate,
                sgst_rate=ln.sgst_rate,
                igst_rate=ln.igst_rate,
                cess_rate=ln.cess_rate,
                cgst_amount=ln.cgst_amount,
                sgst_amount=ln.sgst_amount,
                igst_amount=ln.igst_amount,
                cess_amount=ln.cess_amount,
                line_total=ln.line_total,
                expiry=ln.expiry,
            )
            for ln in inv.lines
        ],
    )


def _notes_totals(db: Session, invoice_ids: list[int]) -> dict[int, tuple[Decimal, Decimal]]:
    """(credit notes, debit notes) per invoice, so a list shows what is left."""
    if not invoice_ids:
        return {}
    credits = {i: Decimal(0) for i in invoice_ids}
    debits = {i: Decimal(0) for i in invoice_ids}
    for model, target in ((CreditNote, credits), (DebitNote, debits)):
        rows = db.execute(
            select(model.invoice_id, func.coalesce(func.sum(model.grand_total), 0))
            .where(model.invoice_id.in_(invoice_ids), model.status == "issued")
            .group_by(model.invoice_id)).all()
        for invoice_id, total in rows:
            target[invoice_id] = Decimal(total)
    return {i: (credits[i], debits[i]) for i in invoice_ids}


@router.get("", response_model=list[InvoiceOut])
def list_invoices(response: Response, distributor_id: int | None = None,
                  status: str | None = None, paging=Depends(page_params),
                  db: Session = Depends(get_db), _=Depends(require("sales:read"))):
    page, page_size = paging
    stmt = select(Invoice)
    if distributor_id:
        stmt = stmt.where(Invoice.distributor_id == distributor_id)
    if status:
        stmt = stmt.where(Invoice.status == status)
    invoices = paginate(db, stmt.order_by(Invoice.id.desc()), response, page, page_size)
    if not invoices:
        return []
    so_ids = {i.sales_order_id for i in invoices}
    sos = {so.id: so.so_number for so in db.scalars(select(SalesOrder).where(SalesOrder.id.in_(so_ids))).all()}
    totals = _notes_totals(db, [i.id for i in invoices])
    out = []
    for inv in invoices:
        built = _build_invoice(inv, sos)
        built.credit_note_total, built.debit_note_total = totals.get(inv.id, (Decimal(0), Decimal(0)))
        out.append(built)
    return out


# Registered before "/{invoice_id}": otherwise the path segment "expiry" is read as an invoice id.
@router.get("/expiry", response_model=list[dict])
def invoice_line_expiry_history(
    db: Session = Depends(get_db),
    _=Depends(require("sales:read")),
    product_id: int | None = None,
    warehouse_id: int | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict]:
    """Expiry date of every invoiced line, newest expiry first.

    Every filter is optional and the ones given all apply (a line must satisfy
    each of them):
    - `product_id`: only lines for this product
    - `warehouse_id`: only lines whose goods were issued from this warehouse
    - `from_date` / `to_date`: only lines with an expiry in this range (inclusive)
    """
    q = (select(InvoiceLine, SalesOrder.dispatched_at)
         .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
         .join(SalesOrder, SalesOrder.id == Invoice.sales_order_id, isouter=True))
    if product_id is not None:
        q = q.where(InvoiceLine.product_id == product_id)
    if warehouse_id is not None:
        # an order carries no warehouse of its own: the dispatch wrote one "issue"
        # movement per batch, and a batch lives in one warehouse
        issued_from = (select(StockMovement.id)
                       .join(Batch, Batch.id == StockMovement.batch_id)
                       .where(StockMovement.movement_type == "issue",
                              StockMovement.ref_type == "so",
                              StockMovement.ref_id == cast(Invoice.sales_order_id, String),
                              Batch.product_id == InvoiceLine.product_id,
                              Batch.warehouse_id == warehouse_id))
        q = q.where(exists(issued_from))
    if from_date is not None:
        q = q.where(InvoiceLine.expiry >= from_date)
    if to_date is not None:
        q = q.where(InvoiceLine.expiry <= to_date)

    rows = db.execute(q.order_by(InvoiceLine.expiry.desc().nulls_last(), InvoiceLine.id)).all()
    return [
        {
            "invoice_id": line.invoice_id,
            "invoice_number": line.invoice.invoice_number if line.invoice else None,
            "line_id": line.id,
            "sku": line.sku,
            "product_id": line.product_id,
            "expiry": line.expiry.isoformat() if line.expiry else None,
            "dispatched_at": dispatched_at.isoformat() if dispatched_at else None,
        }
        for line, dispatched_at in rows
    ]


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db), _=Depends(require("sales:read"))):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    so = db.get(SalesOrder, inv.sales_order_id)
    so_map = {inv.sales_order_id: so.so_number} if so else {}
    built = _build_invoice(inv, so_map)
    built.credit_note_total, built.debit_note_total = _notes_totals(db, [inv.id]).get(
        inv.id, (Decimal(0), Decimal(0)))
    return built


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/{invoice_id}/cancel", response_model=InvoiceOut)
def cancel_invoice(invoice_id: int, body: CancelIn, db: Session = Depends(get_db),
                   user=Depends(require("invoice:cancel"))):
    """Cancel an issued invoice. The document and its number stay, marked CANCELLED."""
    inv = db.get(Invoice, invoice_id, with_for_update=True)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status == "cancelled":
        raise HTTPException(409, f"Invoice {inv.invoice_number} is already cancelled")
    noted = (db.scalar(select(func.count(CreditNote.id)).where(
                 CreditNote.invoice_id == inv.id, CreditNote.status == "issued")) or 0)
    noted += (db.scalar(select(func.count(DebitNote.id)).where(
                  DebitNote.invoice_id == inv.id, DebitNote.status == "issued")) or 0)
    if noted:
        raise HTTPException(409, "Credit or debit notes are linked to this invoice; "
                                 "reverse them before cancelling it")
    # Cancelling removes the invoice from the year's receivable and sales, so it
    # is a change to a closed year like any other.
    try:
        periods.refuse_if_closed(db, inv.invoice_date,
                                 f"invoice {inv.invoice_number}'s cancellation")
    except periods.PeriodClosed as exc:
        raise HTTPException(423, str(exc))
    inv.status = "cancelled"
    inv.cancel_reason = body.reason.strip()
    inv.cancelled_by = user.id
    inv.cancelled_at = datetime.now(timezone.utc)
    inv.copy_designation = "CANCELLED"
    audit(db, user.id, "invoice.cancel", f"invoice:{inv.id}",
          {"number": inv.invoice_number, "reason": inv.cancel_reason})
    db.commit()
    so = db.get(SalesOrder, inv.sales_order_id)
    return _build_invoice(inv, {inv.sales_order_id: so.so_number} if so else {})


class MovementIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
    delivery_challan_number: str | None = Field(default=None, max_length=30)
    vehicle_number: str | None = Field(default=None, max_length=20)
    transporter_name: str | None = Field(default=None, max_length=120)
    eway_bill_number: str | None = Field(default=None, max_length=30)
    eway_bill_date: date | None = None


class AmendIn(BaseModel):
    """A permitted post-billing amendment.

    Only non-financial fields can change here. Quantities, prices and tax stay
    frozen: those are corrected with a credit or debit note, which keeps the
    GST document and the ledgers consistent.
    """
    reason: str = Field(min_length=3, max_length=300)
    delivery_challan_number: str | None = Field(default=None, max_length=30)
    vehicle_number: str | None = Field(default=None, max_length=20)
    transporter_name: str | None = Field(default=None, max_length=120)
    eway_bill_number: str | None = Field(default=None, max_length=30)
    eway_bill_date: date | None = None
    notes: list[str] | None = Field(default=None, max_length=20)


AMENDABLE = ("delivery_challan_number", "vehicle_number", "transporter_name",
             "eway_bill_number", "eway_bill_date", "notes")


def _apply_amendment(inv: Invoice, body: MovementIn | AmendIn) -> dict:
    if getattr(body, "eway_bill_number", None) and not getattr(body, "eway_bill_date", None):
        raise HTTPException(422, "An e-way bill needs the date it was generated")
    if getattr(body, "eway_bill_date", None) and not getattr(body, "eway_bill_number", None):
        raise HTTPException(422, "An e-way bill date needs the bill number")
    changes = {}
    for field in AMENDABLE:
        if field not in body.model_fields_set:
            continue
        value = getattr(body, field)
        if isinstance(value, str):
            value = value.strip() or None
        old = getattr(inv, field)
        if old != value:
            changes[field] = {"old": old, "new": value}
            setattr(inv, field, value)
    if not changes:
        raise HTTPException(422, "Nothing to change")
    return changes


@router.patch("/{invoice_id}/movement", response_model=InvoiceOut)
def record_movement(invoice_id: int, body: MovementIn, db: Session = Depends(get_db),
                    user=Depends(require_admin("invoice:edit_post_billing"))):
    """After billing, only the Administrator may change the movement details."""
    inv = db.get(Invoice, invoice_id, with_for_update=True)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status != "issued":
        raise HTTPException(409, "A cancelled invoice cannot carry movement details")
    changes = _apply_amendment(inv, body)
    audit(db, user.id, "invoice.movement", f"invoice:{inv.id}",
          {"number": inv.invoice_number, "reason": body.reason.strip(), **changes})
    db.commit()
    so = db.get(SalesOrder, inv.sales_order_id)
    return _build_invoice(inv, {inv.sales_order_id: so.so_number} if so else {})


@router.patch("/{invoice_id}/amend", response_model=InvoiceOut)
def amend_invoice(invoice_id: int, body: AmendIn, db: Session = Depends(get_db),
                  user=Depends(require_admin("invoice:edit_post_billing"))):
    """Admin-only post-billing amendment, with a reason and an audit trail."""
    inv = db.get(Invoice, invoice_id, with_for_update=True)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status != "issued":
        raise HTTPException(409, "A cancelled invoice cannot be amended")
    changes = _apply_amendment(inv, body)
    audit(db, user.id, "invoice.amend", f"invoice:{inv.id}",
          {"number": inv.invoice_number, "reason": body.reason.strip(), **changes})
    db.commit()
    so = db.get(SalesOrder, inv.sales_order_id)
    return _build_invoice(inv, {inv.sales_order_id: so.so_number} if so else {})


@router.put("/{invoice_id}", status_code=405)
def update_invoice(invoice_id: int, db: Session = Depends(get_db), _=Depends(require("invoice:write"))):
    raise HTTPException(405, "Invoices are immutable and cannot be edited")


@router.delete("/{invoice_id}", status_code=405)
def delete_invoice(invoice_id: int, db: Session = Depends(get_db), _=Depends(require("invoice:cancel"))):
    raise HTTPException(405, "Invoices are immutable and cannot be deleted")