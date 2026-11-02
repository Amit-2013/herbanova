"""Free-of-cost stock: approved giveaways and the guarded historical correction.

Reading needs `foc:read`, drafting needs `foc:write`. Approval and reversal need
`foc:approve` and the Administrator role, because a giveaway moves stock out of
the ledger with no invoice. The historical correction is the same administrator
gate: it rewrites the cost source of named legacy receipts and writes the
distribution notes in one transaction.

Nothing here creates revenue, GST or an expense. A note's notional value is a
memo for the file and never reaches the profit and loss.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require, require_admin
from ..models.core import Warehouse
from ..models.foc import REASONS, STATUSES
from ..services import foc

router = APIRouter(prefix="/api/foc", tags=["foc"])


class LineIn(BaseModel):
    product_id: int
    batch_id: int
    qty: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit_notional_value: Decimal | None = Field(default=None, ge=0, max_digits=14,
                                                decimal_places=2)


class NoteIn(BaseModel):
    note_date: date
    warehouse_id: int
    recipient_name: str = Field(min_length=1, max_length=150)
    recipient_address: str | None = Field(default=None, max_length=300)
    recipient_contact: str | None = Field(default=None, max_length=120)
    distributor_id: int | None = None
    reason: str = "sample"
    reason_note: str | None = Field(default=None, max_length=300)
    notional_value: Decimal | None = Field(default=None, ge=0, max_digits=14,
                                           decimal_places=2)
    lines: list[LineIn] = Field(min_length=1)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class RecipientIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    address: str | None = Field(default=None, max_length=300)
    contact: str | None = Field(default=None, max_length=120)
    distributor_id: int | None = None
    qty: Decimal = Field(gt=0, max_digits=14, decimal_places=3)


class CorrectionIn(BaseModel):
    note_date: date
    warehouse_id: int
    reason: str = "sample"
    reason_note: str | None = Field(default=None, max_length=300)
    notional_value: Decimal | None = Field(default=None, ge=0, max_digits=14,
                                           decimal_places=2)
    recipients: list[RecipientIn] = Field(min_length=1)
    flag_po7: bool = False
    base_movement_id: int = 1
    po_line_id: int = 1
    creator_id: int | None = Field(default=None, ge=1)
    expected_fingerprint: str | None = Field(default=None, max_length=64)


def _warehouses(db: Session) -> dict[int, str]:
    return {row.id: row.name for row in db.scalars(select(Warehouse)).all()}


def _refuse(exc: foc.FocError):
    raise HTTPException(exc.status, exc.detail)


def _correction_kwargs(body: CorrectionIn) -> dict:
    return {
        "note_date": body.note_date,
        "warehouse_id": body.warehouse_id,
        "reason": body.reason,
        "reason_note": body.reason_note,
        "notional_value": body.notional_value,
        "recipients": [r.model_dump() for r in body.recipients],
        "flag_po7": body.flag_po7,
        "base_movement_id": body.base_movement_id,
        "po_line_id": body.po_line_id,
    }


@router.get("/notes")
def list_notes(status: str | None = None, date_from: date | None = None,
               date_to: date | None = None, q: str | None = None,
               limit: int = Query(default=200, ge=1, le=500),
               db: Session = Depends(get_db), _=Depends(require("foc:read"))):
    if status is not None and status not in STATUSES:
        raise HTTPException(422, "Unknown free-sample note status")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date is after the end date")
    notes = foc.notes_query(db, status=status, date_from=date_from, date_to=date_to,
                            q=q, limit=limit)
    names = _warehouses(db)
    return [foc.note_out(note, names) for note in notes]


@router.get("/notes/{note_id}")
def get_note(note_id: int, db: Session = Depends(get_db),
             _=Depends(require("foc:read"))):
    from ..models.foc import FocNote
    note = db.get(FocNote, note_id)
    if note is None:
        raise HTTPException(404, "Free-sample note not found")
    return foc.note_out(note, _warehouses(db))


@router.post("/notes", status_code=201)
def create_note(body: NoteIn, db: Session = Depends(get_db),
                user=Depends(require("foc:write"))):
    if body.reason not in REASONS:
        raise HTTPException(422, f"reason must be one of {', '.join(REASONS)}")
    try:
        note = foc.create_note(
            db, actor=user, note_date=body.note_date, warehouse_id=body.warehouse_id,
            recipient_name=body.recipient_name,
            recipient_address=body.recipient_address,
            recipient_contact=body.recipient_contact,
            distributor_id=body.distributor_id, reason=body.reason,
            reason_note=body.reason_note, notional_value=body.notional_value,
            lines=[line.model_dump() for line in body.lines])
    except foc.FocError as exc:
        db.rollback()
        _refuse(exc)
    db.commit()
    db.refresh(note)
    return foc.note_out(note, _warehouses(db))


@router.post("/notes/{note_id}/approve")
def approve_note(note_id: int, db: Session = Depends(get_db),
                 user=Depends(require_admin("foc:approve"))):
    try:
        note = foc.approve_note(db, note_id, user)
    except foc.FocError as exc:
        db.rollback()
        _refuse(exc)
    db.commit()
    db.refresh(note)
    return foc.note_out(note, _warehouses(db))


@router.post("/notes/{note_id}/reject")
def reject_note(note_id: int, body: ReasonIn, db: Session = Depends(get_db),
                user=Depends(require("foc:write"))):
    try:
        note = foc.reject_note(db, note_id, user, body.reason)
    except foc.FocError as exc:
        db.rollback()
        _refuse(exc)
    db.commit()
    db.refresh(note)
    return foc.note_out(note, _warehouses(db))


@router.post("/notes/{note_id}/reverse")
def reverse_note(note_id: int, body: ReasonIn, db: Session = Depends(get_db),
                 user=Depends(require_admin("foc:approve"))):
    try:
        note = foc.reverse_note(db, note_id, user, body.reason)
    except foc.FocError as exc:
        db.rollback()
        _refuse(exc)
    db.commit()
    db.refresh(note)
    return foc.note_out(note, _warehouses(db))


@router.get("/stock")
def foc_stock(db: Session = Depends(get_db), _=Depends(require("foc:read"))):
    return foc.foc_stock(db)


@router.post("/correction/plan")
def correction_plan(body: CorrectionIn, db: Session = Depends(get_db),
                    _=Depends(require_admin("foc:approve"))):
    """Read-only: the rows the apply would write and the fingerprint to approve."""
    try:
        return foc.correction_plan(db, **_correction_kwargs(body))
    except foc.FocError as exc:
        _refuse(exc)


@router.post("/correction/apply")
def apply_correction(body: CorrectionIn, db: Session = Depends(get_db),
                     user=Depends(require_admin("foc:approve"))):
    if not body.expected_fingerprint:
        raise HTTPException(422, "Approve a plan fingerprint before applying")
    if body.creator_id is None:
        raise HTTPException(422, "Name the creator of the free-sample notes")
    try:
        result = foc.apply_correction(db, expected_fingerprint=body.expected_fingerprint,
                                      creator_id=body.creator_id, approver=user,
                                      **_correction_kwargs(body))
    except foc.FocError as exc:
        db.rollback()
        _refuse(exc)
    db.commit()
    return result
