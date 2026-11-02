"""Expenses: heads, entries, approvals, reversals and receipts.

Recording needs `expense:write`; reading needs `expense:read`. The approval
threshold is a single Administrator-owned setting. An entry above it waits as
`pending_approval` and reaches the profit and loss only after someone other than
its creator decides it in the central Approvals queue.

An entry is never edited or deleted. A mistake is reversed with a reason; the
reversed row keeps its amount and is excluded from reports downstream. The
attachment is private: a generated filename under `var/expense_receipts`, served
only through an authenticated endpoint.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require, require_admin
from ..models.accounts import MODES
from ..models.core import ApprovalRequest
from ..models.expenses import (APPROVED, PENDING, REJECTED, REVERSED, STATUSES,
                               Expense, ExpenseHead, ExpenseSettings,
                               SYSTEM_PAYROLL_HEAD)
from ..services.audit import audit

router = APIRouter(prefix="/api/expenses", tags=["expenses"])

ATTACHMENT_DIR = Path(__file__).resolve().parents[2] / "var" / "expense_receipts"
ATTACHMENT_MAX = 5_000_000
IMAGE_TYPES = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"),
               "WEBP": ("webp", "image/webp")}
MEDIA_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
               ".pdf": "application/pdf"}


def _money(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


class HeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)

    @field_validator("name")
    @classmethod
    def clean(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("the name cannot be blank")
        return cleaned


class HeadPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def clean(cls, v):
        if v is None:
            return v
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("the name cannot be blank")
        return cleaned


class HeadOut(BaseModel):
    id: int
    name: str
    is_active: bool
    is_system: bool


class SettingsIn(BaseModel):
    approval_enabled: bool
    approval_threshold: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    tracked_from: date


class SettingsOut(BaseModel):
    approval_enabled: bool
    approval_threshold: Decimal
    tracked_from: date


class ExpenseIn(BaseModel):
    head_id: int
    entry_date: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    gst_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                decimal_places=2)
    gst_creditable: bool = True
    mode: str = "bank"
    reference: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=300)

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v):
        if v not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        return v

    @field_validator("reference", "note")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) and v.strip() else None


class ExpenseOut(BaseModel):
    id: int
    number: str
    head_id: int
    head: str
    entry_date: date
    amount: Decimal
    gst_amount: Decimal
    gst_creditable: bool
    total: Decimal
    deductible_amount: Decimal
    mode: str
    reference: str | None
    note: str | None
    attachment: bool
    attachment_url: str | None
    status: str
    created_by: int
    created_at: datetime | None
    approved_by: int | None
    approved_at: datetime | None
    reversed_by: int | None
    reversed_at: datetime | None
    reversal_reason: str | None
    approval_request_id: int | None


class ReverseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)

    @field_validator("reason")
    @classmethod
    def clean(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("the reason cannot be blank")
        return cleaned


def _out(e: Expense) -> ExpenseOut:
    return ExpenseOut(
        id=e.id, number=e.number, head_id=e.head_id,
        head=e.head.name if e.head else "", entry_date=e.entry_date,
        amount=_money(e.amount), gst_amount=_money(e.gst_amount),
        gst_creditable=e.gst_creditable, total=e.total,
        deductible_amount=e.deductible_amount, mode=e.mode,
        reference=e.reference, note=e.note,
        attachment=bool(e.attachment_path),
        attachment_url=f"/api/expenses/{e.id}/attachment" if e.attachment_path else None,
        status=e.status, created_by=e.created_by, created_at=e.created_at,
        approved_by=e.approved_by, approved_at=e.approved_at,
        reversed_by=e.reversed_by, reversed_at=e.reversed_at,
        reversal_reason=e.reversal_reason,
        approval_request_id=e.approval_request_id)


def _settings(db: Session) -> ExpenseSettings:
    row = db.get(ExpenseSettings, 1)
    if row is None:
        # The migration seeds the row; this keeps an older database working.
        row = ExpenseSettings(id=1, approval_enabled=False,
                              approval_threshold=Decimal("0"),
                              tracked_from=date.today())
        db.add(row)
        db.flush()
    return row


def _head(db: Session, head_id: int) -> ExpenseHead:
    head = db.get(ExpenseHead, head_id)
    if head is None:
        raise HTTPException(404, "Expense head not found")
    return head


def _check_name_taken(db: Session, name: str, exclude: int | None = None) -> None:
    stmt = select(ExpenseHead.id).where(func.lower(ExpenseHead.name) == name.lower())
    if exclude is not None:
        stmt = stmt.where(ExpenseHead.id != exclude)
    if db.scalar(stmt):
        raise HTTPException(409, "An expense head with that name already exists")


# ------------------------------------------------------------------ heads
@router.get("/heads", response_model=list[HeadOut])
def list_heads(include_inactive: bool = False, db: Session = Depends(get_db),
               _=Depends(require("expense:read"))):
    stmt = select(ExpenseHead).order_by(ExpenseHead.is_system.desc(), ExpenseHead.name)
    if not include_inactive:
        stmt = stmt.where(ExpenseHead.is_active.is_(True))
    return [HeadOut(id=h.id, name=h.name, is_active=h.is_active, is_system=h.is_system)
            for h in db.scalars(stmt).all()]


@router.post("/heads", response_model=HeadOut, status_code=201)
def create_head(body: HeadIn, db: Session = Depends(get_db),
                user=Depends(require("expense:write"))):
    _check_name_taken(db, body.name)
    head = ExpenseHead(name=body.name, is_active=True, is_system=False,
                       created_by=user.id)
    db.add(head)
    db.flush()
    audit(db, user.id, "expense.head", f"expense_head:{head.id}", {"name": head.name})
    db.commit()
    return HeadOut(id=head.id, name=head.name, is_active=head.is_active,
                   is_system=head.is_system)


@router.patch("/heads/{head_id}", response_model=HeadOut)
def update_head(head_id: int, body: HeadPatch, db: Session = Depends(get_db),
                user=Depends(require("expense:write"))):
    head = _head(db, head_id)
    if head.is_system:
        raise HTTPException(409, "The payroll head is maintained by HR and cannot be changed")
    changes = {}
    if body.name is not None and body.name != head.name:
        _check_name_taken(db, body.name, exclude=head.id)
        changes["name"] = [head.name, body.name]
        head.name = body.name
    if body.is_active is not None and body.is_active != head.is_active:
        changes["is_active"] = [head.is_active, body.is_active]
        head.is_active = body.is_active
    if not changes:
        raise HTTPException(422, "Nothing to change")
    audit(db, user.id, "expense.head", f"expense_head:{head.id}", changes)
    db.commit()
    return HeadOut(id=head.id, name=head.name, is_active=head.is_active,
                   is_system=head.is_system)


# --------------------------------------------------------------- settings
@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db), _=Depends(require("expense:read"))):
    row = _settings(db)
    return SettingsOut(approval_enabled=row.approval_enabled,
                       approval_threshold=_money(row.approval_threshold),
                       tracked_from=row.tracked_from)


@router.put("/settings", response_model=SettingsOut)
def update_settings(body: SettingsIn, db: Session = Depends(get_db),
                    user=Depends(require_admin("expense:write"))):
    row = _settings(db)
    if body.tracked_from > date.today():
        raise HTTPException(422, "Expenses cannot start being tracked in the future")
    earliest = db.scalar(select(func.min(Expense.entry_date)))
    if earliest is not None and body.tracked_from > earliest:
        raise HTTPException(
            422, f"An expense is recorded on {earliest.isoformat()}; tracking cannot "
                 "start after it")
    old = {"approval_enabled": row.approval_enabled,
           "approval_threshold": str(_money(row.approval_threshold)),
           "tracked_from": row.tracked_from.isoformat()}
    row.approval_enabled = body.approval_enabled
    row.approval_threshold = _money(body.approval_threshold)
    row.tracked_from = body.tracked_from
    row.updated_by = user.id
    audit(db, user.id, "expense.settings", "expense_settings:1",
          {"from": old, "to": {"approval_enabled": row.approval_enabled,
                               "approval_threshold": str(row.approval_threshold),
                               "tracked_from": row.tracked_from.isoformat()}})
    db.commit()
    return SettingsOut(approval_enabled=row.approval_enabled,
                       approval_threshold=_money(row.approval_threshold),
                       tracked_from=row.tracked_from)


# ---------------------------------------------------------------- entries
@router.get("", response_model=list[ExpenseOut])
def list_expenses(status: str | None = None, head_id: int | None = None,
                  date_from: date | None = None, date_to: date | None = None,
                  q: str | None = None, limit: int = Query(default=500, ge=1, le=500),
                  db: Session = Depends(get_db), _=Depends(require("expense:read"))):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date is after the end date")
    stmt = select(Expense).order_by(Expense.entry_date.desc(), Expense.id.desc())
    if status is not None:
        if status not in STATUSES:
            raise HTTPException(422, "Unknown expense status")
        stmt = stmt.where(Expense.status == status)
    if head_id is not None:
        stmt = stmt.where(Expense.head_id == head_id)
    if date_from is not None:
        stmt = stmt.where(Expense.entry_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Expense.entry_date <= date_to)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Expense.reference.ilike(like) | Expense.note.ilike(like))
    return [_out(e) for e in db.scalars(stmt.limit(limit)).all()]


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, db: Session = Depends(get_db),
                _=Depends(require("expense:read"))):
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(404, "Expense not found")
    return _out(expense)


@router.post("", response_model=ExpenseOut, status_code=201)
def create_expense(body: ExpenseIn, db: Session = Depends(get_db),
                   user=Depends(require("expense:write"))):
    if body.entry_date > date.today():
        raise HTTPException(422, "The date cannot be in the future")
    if body.entry_date < date.today() - timedelta(days=3650):
        raise HTTPException(422, "The date is more than ten years ago")
    head = _head(db, body.head_id)
    if not head.is_active:
        raise HTTPException(422, "That expense head is inactive")
    if head.is_system:
        raise HTTPException(
            422, "The payroll head is filled from the HR payroll register; "
                 "a manual entry is not allowed")

    amount, gst = _money(body.amount), _money(body.gst_amount)
    total = amount + gst
    settings = _settings(db)
    needs_approval = bool(settings.approval_enabled
                          and total > _money(settings.approval_threshold))
    expense = Expense(
        head_id=head.id, entry_date=body.entry_date, amount=amount, gst_amount=gst,
        gst_creditable=body.gst_creditable, mode=body.mode,
        reference=body.reference, note=body.note,
        status=PENDING if needs_approval else APPROVED,
        created_by=user.id,
        approved_by=None if needs_approval else user.id,
        approved_at=None if needs_approval else datetime.now(timezone.utc))
    db.add(expense)
    db.flush()

    if needs_approval:
        approval = ApprovalRequest(
            record_type="expense", record_id=expense.id,
            reasons=["expense_approval"], requested_by=user.id,
            request_no=f"AP-{date.today():%Y%m%d}-E{expense.id:05d}"[:40],
            document_number=expense.number,
            subject=f"{head.name} · ₹ {total}",
            pending_approver_role="approver",
            detail={"expense_id": expense.id, "head": head.name,
                    "entry_date": body.entry_date.isoformat(),
                    "amount": str(amount), "gst_amount": str(gst),
                    "gst_creditable": body.gst_creditable, "total": str(total),
                    "mode": body.mode, "note": body.note})
        db.add(approval)
        db.flush()
        expense.approval_request_id = approval.id

    audit(db, user.id, "expense.create", f"expense:{expense.id}",
          {"head": head.name, "amount": str(amount), "gst_amount": str(gst),
           "gst_creditable": body.gst_creditable, "total": str(total),
           "status": expense.status, "entry_date": body.entry_date.isoformat(),
           "mode": body.mode, "approval_request_id": expense.approval_request_id})
    db.commit()
    db.refresh(expense)
    return _out(expense)


@router.post("/{expense_id}/reverse", response_model=ExpenseOut)
def reverse_expense(expense_id: int, body: ReverseIn, db: Session = Depends(get_db),
                    user=Depends(require("expense:write"))):
    """Mark an approved entry reversed. The amount stays; reports exclude it."""
    expense = db.get(Expense, expense_id, with_for_update=True)
    if expense is None:
        raise HTTPException(404, "Expense not found")
    if expense.status == REVERSED:
        raise HTTPException(409, "This expense is already reversed")
    if expense.status != APPROVED:
        raise HTTPException(409, f"Only an approved expense can be reversed; it is {expense.status}")
    expense.status = REVERSED
    expense.reversed_by = user.id
    expense.reversed_at = datetime.now(timezone.utc)
    expense.reversal_reason = body.reason
    audit(db, user.id, "expense.reverse", f"expense:{expense.id}",
          {"reason": body.reason, "amount": str(expense.amount),
           "number": expense.number})
    db.commit()
    db.refresh(expense)
    return _out(expense)


# --------------------------------------------------------------- receipts
def _receipt_extension(data: bytes) -> tuple[str, str]:
    """Validate the bytes themselves; the browser's filename is not trusted."""
    if data.startswith(b"%PDF-") and len(data) > 16:
        return "pdf", "application/pdf"
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            fmt = image.format
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError,
            ValueError):
        raise HTTPException(422, "Upload a JPEG, PNG or WebP image, or a PDF receipt")
    if fmt not in IMAGE_TYPES:
        raise HTTPException(422, "Upload a JPEG, PNG or WebP image, or a PDF receipt")
    ext, media = IMAGE_TYPES[fmt]
    return ext, media


@router.post("/{expense_id}/attachment", response_model=ExpenseOut)
async def upload_attachment(expense_id: int, file: UploadFile = File(...),
                            db: Session = Depends(get_db),
                            user=Depends(require("expense:write"))):
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(404, "Expense not found")
    if expense.status in (REJECTED, REVERSED):
        raise HTTPException(409, "A rejected or reversed expense cannot take a receipt")
    data = await file.read(ATTACHMENT_MAX + 1)
    if len(data) > ATTACHMENT_MAX:
        raise HTTPException(413, "The receipt must be 5 MB or smaller")
    if not data:
        raise HTTPException(422, "The receipt file is empty")
    ext, _media = _receipt_extension(data)
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    for old in ATTACHMENT_DIR.glob(f"expense_{expense.id}_*"):
        old.unlink(missing_ok=True)
    target = ATTACHMENT_DIR / f"expense_{expense.id}_{uuid4().hex[:12]}.{ext}"
    target.write_bytes(data)
    expense.attachment_path = f"expense_receipts/{target.name}"
    audit(db, user.id, "expense.attachment", f"expense:{expense.id}",
          {"format": ext, "bytes": len(data), "number": expense.number})
    db.commit()
    db.refresh(expense)
    return _out(expense)


@router.get("/{expense_id}/attachment")
def get_attachment(expense_id: int, db: Session = Depends(get_db),
                   _=Depends(require("expense:read"))):
    expense = db.get(Expense, expense_id)
    if expense is None or not expense.attachment_path:
        raise HTTPException(404, "No receipt on file")
    path = ATTACHMENT_DIR / Path(expense.attachment_path).name
    if not path.exists():
        raise HTTPException(404, "The receipt file is missing")
    media = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media,
                        filename=f"{expense.number}{path.suffix}",
                        content_disposition_type="attachment",
                        headers={"Cache-Control": "no-store"})
