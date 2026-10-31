from datetime import datetime  # noqa: F401
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.india_states import state_name
from ..core.pagination import page_params, paginate
from ..core.rbac import require, role_permissions
from ..models.core import Distributor, SalesOrder
from ..services.audit import audit
from ..services.sales import EXPOSURE_STATUSES, credit_exposure
from ..services.tax_ids import normalize_identity

router = APIRouter(prefix="/api/distributors", tags=["distributors"])

# One status vocabulary for every layer (COR-001): the Overview screen's filter
# offers exactly these values and its status chip knows exactly these values, so
# a stored record can never render as an unknown state. "Blocked" is the same
# word the supplier master uses, so the two masters no longer disagree.
DISTRIBUTOR_STATUSES = ("active", "blocked", "draft", "pending verification", "inactive")


class DistributorIn(BaseModel):
    code: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=2, max_length=150)
    territory: str = Field(min_length=2, max_length=60)
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    # Module Phase 3 (FR-13): the buyer's tax identity, place of supply and
    # addresses. An unregistered buyer carries a state code but no GSTIN.
    registration_type: str = "unregistered"
    gstin: str | None = None
    pan: str | None = None
    state_code: str | None = None
    billing_address: str | None = Field(default=None, max_length=300)
    shipping_address: str | None = Field(default=None, max_length=300)
    # FR-07 (G-07): contact details, the distributor group a discount slab can
    # target, and the agreed payment terms.
    contact_person: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=150)
    group_name: str | None = Field(default=None, max_length=60)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    # The screen offers the same values, so a record can be onboarded in the
    # state it is actually in rather than created active and blocked afterwards.
    status: str = "active"

    @field_validator("code")
    @classmethod
    def norm(cls, v): return v.strip().upper()

    @field_validator("status")
    @classmethod
    def check_status(cls, v):
        if v not in DISTRIBUTOR_STATUSES:
            raise ValueError(f"status must be {' or '.join(DISTRIBUTOR_STATUSES)}")
        return v

    @field_validator("gstin", "pan", "state_code")
    @classmethod
    def tax_norm(cls, v): return v.strip().upper() if isinstance(v, str) and v.strip() else None


class DistributorPatch(BaseModel):
    """Everything about a distributor except its code and its credit limit.

    The credit limit has its own restricted endpoint, and every change here is
    audited with the old and the new value.
    """
    name: str | None = Field(default=None, min_length=2, max_length=150)
    territory: str | None = Field(default=None, min_length=2, max_length=60)
    registration_type: str | None = None
    gstin: str | None = None
    pan: str | None = None
    state_code: str | None = None
    billing_address: str | None = Field(default=None, max_length=300)
    shipping_address: str | None = Field(default=None, max_length=300)
    contact_person: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=150)
    group_name: str | None = Field(default=None, max_length=60)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    status: str | None = None

    @field_validator("gstin", "pan", "state_code")
    @classmethod
    def tax_norm(cls, v): return v.strip().upper() if isinstance(v, str) and v.strip() else None


class CreditLimitIn(BaseModel):
    credit_limit: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    reason: str = Field(min_length=3, max_length=300)


class DistributorOut(BaseModel):
    id: int
    code: str
    name: str
    territory: str
    status: str
    credit_limit: Decimal
    exposure: Decimal      # pending + approved + dispatched orders (payments are not tracked yet)
    available: Decimal     # credit_limit - exposure, never below zero
    registration_type: str
    gstin: str | None
    pan: str | None
    state_code: str | None
    state: str | None
    billing_address: str | None
    shipping_address: str | None
    contact_person: str | None
    phone: str | None
    email: str | None
    group_name: str | None
    payment_terms_days: int | None
    # COR-003: what the record still needs before it can appear on a GST
    # document. Computed, never stored, so it cannot drift from the fields.
    # Vocabulary: "active", "blocked", "draft", "pending verification", "inactive"
    needs_completion: bool
    completion_missing: list[str]


def _completion(d: Distributor) -> list[str]:
    """The gaps that stop this distributor supporting a GST document.

    A registered party's PAN and state are derived from its GSTIN, and the API
    refuses a registered party without one, so in practice only an unregistered
    record can be missing its place of supply. The GSTIN branch stays because a
    row migrated from older data must still be reported honestly rather than
    looking complete. Nothing is invented here: a missing state stays missing
    until someone records it.
    """
    missing = []
    if not d.state_code:
        missing.append("state_code")
    if d.registration_type in ("regular", "composition") and not d.gstin:
        missing.append("gstin")
    return missing


def _out(d: Distributor, exposure: Decimal) -> DistributorOut:
    missing = _completion(d)
    return DistributorOut(id=d.id, code=d.code, name=d.name, territory=d.territory, status=d.status,
                          credit_limit=d.credit_limit, exposure=exposure,
                          available=max(d.credit_limit - exposure, Decimal(0)),
                          registration_type=d.registration_type, gstin=d.gstin, pan=d.pan,
                          state_code=d.state_code, state=state_name(d.state_code),
                          billing_address=d.billing_address, shipping_address=d.shipping_address,
                          contact_person=d.contact_person, phone=d.phone, email=d.email,
                          group_name=d.group_name, payment_terms_days=d.payment_terms_days,
                          needs_completion=bool(missing), completion_missing=missing)


def _identity(registration_type, gstin, pan, state_code) -> dict:
    """Validate a buyer's tax identity with the shared rules (FR-13).

    A distributor that is not registered may simply not have its place of
    supply recorded yet: the record stays honestly incomplete rather than
    inventing a state, and the tax engine refuses to quote without one.
    """
    try:
        return normalize_identity(registration_type, gstin, pan, state_code, require_state=False)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("", response_model=list[DistributorOut])
def list_distributors(response: Response, q: str | None = None, status: str | None = None,
                       paging=Depends(page_params), db: Session = Depends(get_db),
                       _=Depends(require("sales:read"))):
    page, page_size = paging
    exp = dict(db.execute(select(SalesOrder.distributor_id, func.sum(SalesOrder.total))
                          .where(SalesOrder.status.in_(EXPOSURE_STATUSES))
                          .group_by(SalesOrder.distributor_id)).all())
    stmt = select(Distributor)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Distributor.code.ilike(like) | Distributor.name.ilike(like)
                          | Distributor.gstin.ilike(like) | Distributor.territory.ilike(like))
    if status:
        stmt = stmt.where(Distributor.status == status)
    rows = paginate(db, stmt.order_by(Distributor.code), response, page, page_size)
    return [_out(d, Decimal(exp.get(d.id) or 0)) for d in rows]


@router.post("", response_model=DistributorOut, status_code=201)
def create_distributor(body: DistributorIn, db: Session = Depends(get_db),
                       user=Depends(require("distributor:write"))):
    limit = body.credit_limit or Decimal(0)
    if limit > 0 and "credit:manage" not in role_permissions(db, user):
        raise HTTPException(403, "Only an administrator can set a credit limit")
    ident = _identity(body.registration_type, body.gstin, body.pan, body.state_code)
    d = Distributor(code=body.code, name=body.name.strip(), territory=body.territory.strip(),
                    credit_limit=limit, billing_address=body.billing_address,
                    shipping_address=body.shipping_address,                    contact_person=body.contact_person, phone=body.phone, email=body.email,
                    group_name=body.group_name, status=body.status,
                    payment_terms_days=body.payment_terms_days, **ident)
    db.add(d)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Distributor code already exists")
    audit(db, user.id, "distributor.create", f"distributor:{d.id}",
          {"code": d.code, "name": d.name, "credit_limit": str(limit),
           "gstin": d.gstin, "state_code": d.state_code, "group_name": d.group_name,
           "status": d.status})
    db.commit()
    return _out(d, Decimal(0))


@router.patch("/{dist_id}", response_model=DistributorOut)
def update_distributor(dist_id: int, body: DistributorPatch, db: Session = Depends(get_db),
                       user=Depends(require("distributor:write"))):
    """Maintain the distributor's details (FR-07, FR-13).

    The credit limit is not here on purpose: it has its own restricted
    endpoint, and a change to the tax identity is audited like any other.
    """
    d = db.scalars(select(Distributor).where(Distributor.id == dist_id).with_for_update()).first()
    if not d:
        raise HTTPException(404, "Distributor not found")
    data = body.model_dump(exclude_unset=True)
    status = data.pop("status", None)
    if status is not None and status not in DISTRIBUTOR_STATUSES:
        raise HTTPException(422, f"status must be {' or '.join(DISTRIBUTOR_STATUSES)}")
    changes = {}
    if data:
        identity_fields = {"registration_type", "gstin", "pan", "state_code"}
        if identity_fields & set(data):
            ident = _identity(data.get("registration_type", d.registration_type),
                              data.get("gstin", d.gstin), data.get("pan", d.pan),
                              data.get("state_code", d.state_code))
            data.update(ident)
        for key, value in data.items():
            current = getattr(d, key)
            if current != value:
                changes[key] = {"old": str(current) if current is not None else None,
                                "new": str(value) if value is not None else None}
                setattr(d, key, value)
    if status is not None and status != d.status:
        changes["status"] = {"old": d.status, "new": status}
        d.status = status
    if not changes:
        raise HTTPException(422, "Nothing to change")
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That GSTIN already belongs to another distributor")
    audit(db, user.id, "distributor.update", f"distributor:{d.id}", changes)
    db.commit()
    return _out(d, credit_exposure(db, d.id))


@router.patch("/{dist_id}/credit-limit", response_model=DistributorOut)
def change_credit_limit(dist_id: int, body: CreditLimitIn, db: Session = Depends(get_db),
                        user=Depends(require("credit:manage"))):
    d = db.scalars(select(Distributor).where(Distributor.id == dist_id).with_for_update()).first()
    if not d:
        raise HTTPException(404, "Distributor not found")
    old = d.credit_limit
    d.credit_limit = body.credit_limit
    audit(db, user.id, "distributor.credit_limit", f"distributor:{d.id}",
          {"old": str(old), "new": str(body.credit_limit), "reason": body.reason.strip()})
    db.commit()
    return _out(d, credit_exposure(db, d.id))