"""Debit notes (Module Phase 4, FR-14).

A debit note corrects an issued invoice upwards: an undercharge found after
dispatch, a rate revision or a freight charge left out. It is linked to the
original invoice and its lines, cannot exceed what the invoice carried, and is
immutable once issued.
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require
from ..models.core import DebitNote, Invoice
from ..services import periods
from ..services.audit import audit
from ..services.notes import NoteError, create_debit_note

router = APIRouter(prefix="/api/debit-notes", tags=["debit-notes"])


class NoteLineIn(BaseModel):
    invoice_line_id: int
    qty: Decimal = Field(gt=0)


class DebitNoteIn(BaseModel):
    invoice_id: int
    reason: str = Field(min_length=1, max_length=300)
    lines: list[NoteLineIn]
    note_date: date | None = None


class DebitNoteLineOut(BaseModel):
    invoice_line_id: int
    sku: str
    product_name: str
    qty: Decimal
    taxable_value: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    cess_amount: Decimal
    line_total: Decimal


class DebitNoteOut(BaseModel):
    id: int
    debit_note_number: str
    financial_year: str
    invoice_id: int
    invoice_number: str | None = None
    sales_order_id: int
    distributor_id: int
    status: str
    note_date: date
    reason: str
    taxable_value: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    cess_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    lines: list[DebitNoteLineOut]


def _build_debit_note(dn: DebitNote, invoice_number: str | None = None) -> DebitNoteOut:
    return DebitNoteOut(
        id=dn.id,
        debit_note_number=dn.debit_note_number,
        financial_year=dn.financial_year,
        invoice_id=dn.invoice_id,
        invoice_number=invoice_number,
        sales_order_id=dn.sales_order_id,
        distributor_id=dn.distributor_id,
        status=dn.status,
        note_date=dn.note_date,
        reason=dn.reason,
        taxable_value=dn.taxable_value,
        cgst_total=dn.cgst_total,
        sgst_total=dn.sgst_total,
        igst_total=dn.igst_total,
        cess_total=dn.cess_total,
        tax_total=dn.tax_total,
        grand_total=dn.grand_total,
        lines=[
            DebitNoteLineOut(
                invoice_line_id=ln.invoice_line_id,
                sku=ln.sku,
                product_name=ln.product_name,
                qty=ln.qty,
                taxable_value=ln.taxable_value,
                cgst_amount=ln.cgst_amount,
                sgst_amount=ln.sgst_amount,
                igst_amount=ln.igst_amount,
                cess_amount=ln.cess_amount,
                line_total=ln.line_total,
            )
            for ln in dn.lines
        ],
    )


@router.get("", response_model=list[DebitNoteOut])
def list_debit_notes(db: Session = Depends(get_db), _=Depends(require("sales:read"))):
    notes = list(db.scalars(select(DebitNote).order_by(DebitNote.id.desc())).all())
    if not notes:
        return []
    numbers = {i.id: i.invoice_number for i in db.scalars(
        select(Invoice).where(Invoice.id.in_({n.invoice_id for n in notes}))).all()}
    return [_build_debit_note(n, numbers.get(n.invoice_id)) for n in notes]


@router.get("/{dn_id}", response_model=DebitNoteOut)
def get_debit_note(dn_id: int, db: Session = Depends(get_db), _=Depends(require("sales:read"))):
    dn = db.get(DebitNote, dn_id)
    if not dn:
        raise HTTPException(404, "Debit note not found")
    inv = db.get(Invoice, dn.invoice_id)
    return _build_debit_note(dn, inv.invoice_number if inv else None)


@router.post("", response_model=DebitNoteOut, status_code=201)
def issue_debit_note(body: DebitNoteIn, db: Session = Depends(get_db),
                     user=Depends(require("note:write"))):
    try:
        periods.refuse_if_closed(db, body.note_date or date.today(), "a debit note")
    except periods.PeriodClosed as exc:
        raise HTTPException(423, str(exc))
    try:
        note = create_debit_note(db, invoice_id=body.invoice_id, lines=body.lines,
                                 reason=body.reason, issued_by=user.id,
                                 note_date=body.note_date)
    except NoteError as exc:
        db.rollback()
        raise HTTPException(exc.status, str(exc))
    inv = db.get(Invoice, note.invoice_id)
    audit(db, user.id, "debit_note.issue", f"debit_note:{note.id}",
          {"number": note.debit_note_number, "invoice": inv.invoice_number if inv else None,
           "grand_total": str(note.grand_total), "reason": note.reason})
    db.commit()
    return _build_debit_note(note, inv.invoice_number if inv else None)


@router.put("/{dn_id}", status_code=405)
def update_debit_note(dn_id: int, db: Session = Depends(get_db), _=Depends(require("note:write"))):
    raise HTTPException(405, "Debit notes are immutable and cannot be edited")


@router.delete("/{dn_id}", status_code=405)
def delete_debit_note(dn_id: int, db: Session = Depends(get_db), _=Depends(require("note:write"))):
    raise HTTPException(405, "Debit notes are immutable and cannot be deleted")
