"""Credit notes (Module Phase 4, FR-14).

A credit note corrects an issued invoice downwards: a sales return, a rate
difference or a post-sale rebate. It is linked to the original invoice and its
lines, cannot exceed what the invoice carried, and cannot be edited or deleted
once issued.
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require
from ..models.core import CreditNote, Invoice, Warehouse
from ..services.audit import audit
from ..services.notes import NoteError, create_credit_note

router = APIRouter(prefix="/api/credit-notes", tags=["credit-notes"])


class NoteLineIn(BaseModel):
    invoice_line_id: int
    qty: Decimal = Field(gt=0)


class CreditNoteIn(BaseModel):
    invoice_id: int
    reason: str = Field(min_length=1, max_length=300)
    lines: list[NoteLineIn]
    note_date: date | None = None
    # A sales return: the credited goods go back into stock in this warehouse.
    warehouse_id: int | None = None


class CreditNoteLineOut(BaseModel):
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


class CreditNoteOut(BaseModel):
    id: int
    credit_note_number: str
    financial_year: str
    invoice_id: int
    invoice_number: str | None = None
    sales_order_id: int
    distributor_id: int
    status: str
    note_date: date
    reason: str
    returned_to_stock: bool = False
    warehouse_id: int | None = None
    warehouse: str | None = None
    taxable_value: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    cess_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    lines: list[CreditNoteLineOut]


def _build_credit_note(cn: CreditNote, invoice_number: str | None = None,
                       warehouse_name: str | None = None) -> CreditNoteOut:
    return CreditNoteOut(
        id=cn.id,
        credit_note_number=cn.credit_note_number,
        financial_year=cn.financial_year,
        invoice_id=cn.invoice_id,
        invoice_number=invoice_number,
        sales_order_id=cn.sales_order_id,
        distributor_id=cn.distributor_id,
        status=cn.status,
        note_date=cn.note_date,
        reason=cn.reason,
        returned_to_stock=cn.return_warehouse_id is not None,
        warehouse_id=cn.return_warehouse_id,
        warehouse=warehouse_name,
        taxable_value=cn.taxable_value,
        cgst_total=cn.cgst_total,
        sgst_total=cn.sgst_total,
        igst_total=cn.igst_total,
        cess_total=cn.cess_total,
        tax_total=cn.tax_total,
        grand_total=cn.grand_total,
        lines=[
            CreditNoteLineOut(
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
            for ln in cn.lines
        ],
    )


@router.get("", response_model=list[CreditNoteOut])
def list_credit_notes(db: Session = Depends(get_db), _=Depends(require("sales:read"))):
    notes = list(db.scalars(select(CreditNote).order_by(CreditNote.id.desc())).all())
    if not notes:
        return []
    numbers = {i.id: i.invoice_number for i in db.scalars(
        select(Invoice).where(Invoice.id.in_({n.invoice_id for n in notes}))).all()}
    names = {w.id: w.name for w in db.scalars(
        select(Warehouse).where(Warehouse.id.in_(
            {n.return_warehouse_id for n in notes if n.return_warehouse_id}))).all()}
    return [_build_credit_note(n, numbers.get(n.invoice_id),
                               names.get(n.return_warehouse_id)) for n in notes]


@router.get("/{cn_id}", response_model=CreditNoteOut)
def get_credit_note(cn_id: int, db: Session = Depends(get_db), _=Depends(require("sales:read"))):
    cn = db.get(CreditNote, cn_id)
    if not cn:
        raise HTTPException(404, "Credit note not found")
    inv = db.get(Invoice, cn.invoice_id)
    warehouse = db.get(Warehouse, cn.return_warehouse_id) if cn.return_warehouse_id else None
    return _build_credit_note(cn, inv.invoice_number if inv else None,
                              warehouse.name if warehouse else None)


@router.post("", response_model=CreditNoteOut, status_code=201)
def issue_credit_note(body: CreditNoteIn, db: Session = Depends(get_db),
                      user=Depends(require("note:write"))):
    try:
        note = create_credit_note(db, invoice_id=body.invoice_id, lines=body.lines,
                                  reason=body.reason, issued_by=user.id,
                                  note_date=body.note_date,
                                  return_warehouse_id=body.warehouse_id)
    except NoteError as exc:
        db.rollback()
        raise HTTPException(exc.status, str(exc))
    inv = db.get(Invoice, note.invoice_id)
    warehouse = db.get(Warehouse, note.return_warehouse_id) if note.return_warehouse_id else None
    audit(db, user.id, "credit_note.issue", f"credit_note:{note.id}",
          {"number": note.credit_note_number, "invoice": inv.invoice_number if inv else None,
           "grand_total": str(note.grand_total), "reason": note.reason,
           "returned_to_stock": note.return_warehouse_id is not None,
           **({"warehouse": warehouse.name} if warehouse else {})})
    db.commit()
    return _build_credit_note(note, inv.invoice_number if inv else None,
                              warehouse.name if warehouse else None)


@router.put("/{cn_id}", status_code=405)
def update_credit_note(cn_id: int, db: Session = Depends(get_db), _=Depends(require("note:write"))):
    raise HTTPException(405, "Credit notes are immutable and cannot be edited")


@router.delete("/{cn_id}", status_code=405)
def delete_credit_note(cn_id: int, db: Session = Depends(get_db), _=Depends(require("note:write"))):
    raise HTTPException(405, "Credit notes are immutable and cannot be deleted")
