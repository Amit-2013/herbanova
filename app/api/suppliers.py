"""Supplier master (FR-04, AUD-028, AUD-029).

- GSTIN and PAN are format- and check-digit validated; for a registered
  supplier the state code is derived from the GSTIN and must not contradict
  the entered state. Unregistered suppliers carry no GSTIN but still need a
  state (place of supply later).
- Bank details are never changed by a plain edit. A change is requested with
  `supplier:bank`, stored as an approval request, and applied only when a
  different user with `approval:decide` approves it. Account numbers are
  masked in responses, audit rows and notifications; only the last four digits
  are ever shown.
- Records are blocked, not deleted, so purchase history stays intact.
"""
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.india_states import state_name
from ..core.pagination import page_params, paginate
from ..core.rbac import require, role_permissions
from ..models.core import ApprovalRequest, PurchaseOrder, User
from ..models.suppliers import Supplier
from ..services.audit import audit
from ..services.tax_ids import normalize_identity

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def _mask_account(no: str | None) -> str:
    if not no:
        return ""
    return "****" + no[-4:] if len(no) > 4 else "****"


class SupplierIn(BaseModel):
    code: str = Field(min_length=3, max_length=30)
    name: str = Field(min_length=2, max_length=150)
    kind: str = "supplier"                  # supplier | manufacturer | both
    registration_type: str = "regular"      # regular | composition | unregistered
    gstin: str | None = None
    pan: str | None = None
    state_code: str | None = None
    payment_terms_days: int = Field(default=30, ge=0, le=365)

    @field_validator("code")
    @classmethod
    def norm_code(cls, v): return v.strip().upper()

    @field_validator("gstin", "pan", "state_code")
    @classmethod
    def norm(cls, v): return v.strip().upper() if isinstance(v, str) and v.strip() else None


class SupplierPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    kind: str | None = None
    registration_type: str | None = None
    gstin: str | None = None
    pan: str | None = None
    state_code: str | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    status: str | None = None


class SupplierOut(BaseModel):
    id: int
    code: str
    name: str
    kind: str
    registration_type: str
    gstin: str | None
    pan: str | None
    state_code: str | None      # null on a migrated record that is still incomplete
    state: str | None
    payment_terms_days: int
    status: str
    needs_completion: bool
    bank_name: str | None = None
    bank_ifsc: str | None = None
    bank_holder: str | None = None
    bank_account_masked: str | None = None
    bank_approved_at: datetime | None = None
    purchase_orders: int = 0


class BankIn(BaseModel):
    bank_name: str = Field(min_length=2, max_length=120)
    bank_account_no: str = Field(min_length=6, max_length=30)
    bank_ifsc: str = Field(min_length=11, max_length=11)
    bank_holder: str = Field(min_length=2, max_length=120)

    @field_validator("bank_account_no")
    @classmethod
    def digits(cls, v):
        if not v.strip().isdigit():
            raise ValueError("account number may contain only digits")
        return v.strip()

    @field_validator("bank_ifsc")
    @classmethod
    def ifsc(cls, v):
        if not IFSC_RE.match(v.strip().upper()):
            raise ValueError("IFSC must be 11 characters: 4 letters, 0, then 6 letters/digits")
        return v.strip().upper()


class BankDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=3, max_length=300)


class BankChangeOut(BaseModel):
    id: int
    supplier_id: int
    supplier_code: str
    supplier_name: str
    status: str
    requested_by: str
    requested_at: datetime | None
    decided_by: str | None
    decided_at: datetime | None
    decision_reason: str | None
    pending: dict


def _tax_identity(registration_type: str, gstin: str | None, pan: str | None,
                  state_code: str | None) -> dict:
    """Validate and normalize GSTIN/PAN/state; returns the values to store.
    The rules themselves live in `services.tax_ids` so the company profile and
    the distributor master enforce exactly the same ones."""
    try:
        return normalize_identity(registration_type, gstin, pan, state_code)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


def _out(s: Supplier, can_bank: bool, po_count: int = 0) -> SupplierOut:
    return SupplierOut(
        id=s.id, code=s.code, name=s.name, kind=s.kind,
        registration_type=s.registration_type, gstin=s.gstin, pan=s.pan,
        state_code=s.state_code, state=state_name(s.state_code),
        payment_terms_days=s.payment_terms_days, status=s.status,
        needs_completion=s.needs_completion,
        bank_name=s.bank_name if can_bank else None,
        bank_ifsc=s.bank_ifsc if can_bank else None,
        bank_holder=s.bank_holder if can_bank else None,
        bank_account_masked=_mask_account(s.bank_account_no) if can_bank else None,
        bank_approved_at=s.bank_approved_at if can_bank else None,
        purchase_orders=po_count)


def _can_bank(db: Session, user) -> bool:
    return "supplier:bank" in role_permissions(db, user)


@router.get("", response_model=list[SupplierOut])
def list_suppliers(response: Response, status: str | None = None, q: str | None = None,
                   paging=Depends(page_params), db: Session = Depends(get_db),
                   user=Depends(require("supplier:read"))):
    page, page_size = paging
    stmt = select(Supplier)
    if status:
        stmt = stmt.where(Supplier.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Supplier.code.ilike(like) | Supplier.name.ilike(like)
                          | Supplier.gstin.ilike(like))
    rows = paginate(db, stmt.order_by(Supplier.code), response, page, page_size)
    counts = dict(db.execute(select(PurchaseOrder.supplier_id, func.count())
                             .where(PurchaseOrder.supplier_id.is_not(None))
                             .group_by(PurchaseOrder.supplier_id)).all())
    bank = _can_bank(db, user)
    return [_out(s, bank, counts.get(s.id, 0)) for s in rows]


# ---- bank-change requests are declared before /{supplier_id} so the static path wins
@router.get("/bank-changes", response_model=list[BankChangeOut])
def list_bank_changes(status: str | None = None, db: Session = Depends(get_db),
                      _=Depends(require("supplier:read"))):
    q = select(ApprovalRequest).where(ApprovalRequest.record_type == "supplier_bank")
    if status in ("pending", "approved", "rejected"):
        q = q.where(ApprovalRequest.status == status)
    reqs = db.scalars(q.order_by(ApprovalRequest.id.desc())).all()
    suppliers = {s.id: s for s in db.scalars(select(Supplier)).all()}
    uids = {r.requested_by for r in reqs} | {r.decided_by for r in reqs if r.decided_by}
    users = {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(uids))).all()} if uids else {}
    out = []
    for r in reqs:
        s = suppliers.get(r.record_id)
        pending = dict((r.detail or {}).get("pending") or {})
        if "bank_account_no" in pending:
            pending["bank_account_no"] = _mask_account(pending["bank_account_no"])
        out.append(BankChangeOut(
            id=r.id, supplier_id=r.record_id,
            supplier_code=s.code if s else "?", supplier_name=s.name if s else "?",
            status=r.status, requested_by=users.get(r.requested_by, "?"),
            requested_at=r.requested_at, decided_by=users.get(r.decided_by) if r.decided_by else None,
            decided_at=r.decided_at, decision_reason=r.decision_reason, pending=pending))
    return out


@router.post("/bank-changes/{approval_id}/decide", response_model=BankChangeOut)
def decide_bank_change(approval_id: int, body: BankDecisionIn, db: Session = Depends(get_db),
                       user=Depends(require("approval:decide"))):
    ar = db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.id == approval_id,
        ApprovalRequest.record_type == "supplier_bank").with_for_update())
    if not ar:
        raise HTTPException(404, "Bank-change request not found")
    if ar.status != "pending":
        raise HTTPException(409, f"Request is already {ar.status}")
    if ar.requested_by == user.id:
        raise HTTPException(403, "Segregation of duties: a bank-detail change needs a "
                                 "different person to approve it")
    supplier = db.get(Supplier, ar.record_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    ar.status = "approved" if body.decision == "approve" else "rejected"
    ar.decided_by, ar.decided_at = user.id, datetime.now(timezone.utc)
    ar.decision_reason = body.reason.strip()
    pending = dict((ar.detail or {}).get("pending") or {})
    if body.decision == "approve":
        for k in ("bank_name", "bank_account_no", "bank_ifsc", "bank_holder"):
            if k in pending:
                setattr(supplier, k, pending[k])
        supplier.bank_approved_by = user.id
        supplier.bank_approved_at = datetime.now(timezone.utc)
    audit(db, user.id, "supplier.bank_decision", f"supplier:{supplier.id}",
          {"supplier": supplier.code, "decision": body.decision,
           "bank_account_last4": str(pending.get("bank_account_no", ""))[-4:],
           "reason": ar.decision_reason})
    db.commit()
    return next(x for x in list_bank_changes(status=None, db=db) if x.id == ar.id)


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: int, db: Session = Depends(get_db),
                 user=Depends(require("supplier:read"))):
    s = db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(404, "Supplier not found")
    count = db.query(PurchaseOrder).filter(PurchaseOrder.supplier_id == s.id).count()
    return _out(s, _can_bank(db, user), count)


@router.post("", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierIn, db: Session = Depends(get_db),
                    user=Depends(require("supplier:write"))):
    if body.kind not in ("supplier", "manufacturer", "both"):
        raise HTTPException(422, "kind must be supplier, manufacturer or both")
    ident = _tax_identity(body.registration_type, body.gstin, body.pan, body.state_code)
    s = Supplier(code=body.code, name=body.name.strip(), kind=body.kind,
                 registration_type=body.registration_type, payment_terms_days=body.payment_terms_days,
                 **ident)
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Supplier code or GSTIN already exists")
    audit(db, user.id, "supplier.create", f"supplier:{s.id}",
          {"code": s.code, "name": s.name, "gstin": s.gstin,
           "registration_type": s.registration_type})
    db.commit()
    return _out(s, _can_bank(db, user))


@router.patch("/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: int, body: SupplierPatch, db: Session = Depends(get_db),
                    user=Depends(require("supplier:write"))):
    s = db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(404, "Supplier not found")
    data = body.model_dump(exclude_unset=True)
    # Tax identity is validated only when it is being changed. A supplier
    # migrated from a legacy free-text order has no GSTIN or state yet; its
    # name and status must still be editable, and the moment tax details are
    # supplied they are checked in full (needs_completion then clears).
    tax_fields = {"registration_type", "gstin", "pan", "state_code"}
    ident = {}
    if tax_fields & data.keys():
        ident = _tax_identity(data.get("registration_type", s.registration_type),
                              data.get("gstin", s.gstin),
                              data.get("pan", s.pan),
                              data.get("state_code", s.state_code))

    changes = {}
    for k in ("name", "kind", "status"):
        if k in data and data[k] is not None and data[k] != getattr(s, k):
            if k == "kind" and data[k] not in ("supplier", "manufacturer", "both"):
                raise HTTPException(422, "kind must be supplier, manufacturer or both")
            if k == "status" and data[k] not in ("active", "blocked"):
                raise HTTPException(422, "status must be active or blocked")
            changes[k] = {"old": getattr(s, k), "new": data[k]}
            setattr(s, k, data[k])
    for k in ("registration_type", "payment_terms_days"):
        if k in data and data[k] is not None and data[k] != getattr(s, k):
            changes[k] = {"old": getattr(s, k), "new": data[k]}
            setattr(s, k, data[k])
    for k, v in ident.items():
        if v != getattr(s, k):
            changes[k] = {"old": getattr(s, k), "new": v}
            setattr(s, k, v)
    if s.needs_completion and s.gstin:
        s.needs_completion = False      # tax details have now been supplied
    if changes:
        audit(db, user.id, "supplier.update", f"supplier:{s.id}", {"code": s.code, **changes})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "GSTIN already belongs to another supplier")
    count = db.query(PurchaseOrder).filter(PurchaseOrder.supplier_id == s.id).count()
    return _out(s, _can_bank(db, user), count)


@router.post("/{supplier_id}/bank", response_model=BankChangeOut, status_code=201)
def request_bank_change(supplier_id: int, body: BankIn, db: Session = Depends(get_db),
                        user=Depends(require("supplier:bank"))):
    """Bank details change only through approval by a different person (FR-04)."""
    s = db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(404, "Supplier not found")
    pending = db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.record_type == "supplier_bank",
        ApprovalRequest.record_id == s.id,
        ApprovalRequest.status == "pending"))
    if pending:
        raise HTTPException(409, "A bank-detail change for this supplier is already "
                                 "awaiting approval")
    detail = {"pending": body.model_dump(),
              "current_last4": _mask_account(s.bank_account_no)}
    ar = ApprovalRequest(record_type="supplier_bank", record_id=s.id,
                         reasons=["supplier_bank"], requested_by=user.id, detail=detail)
    db.add(ar)
    db.flush()
    audit(db, user.id, "supplier.bank_request", f"supplier:{s.id}",
          {"supplier": s.code, "bank_account_last4": body.bank_account_no[-4:]})
    db.commit()
    return next(x for x in list_bank_changes(status=None, db=db) if x.id == ar.id)
