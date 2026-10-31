"""Company tax profile, GST rate master and discount slabs (FR-13).

- The company profile is one row: it is what every later invoice prints as the
  seller, so its GSTIN is validated in full and its state comes from the GSTIN.
- Rates are keyed by HSN and effective-dated. Adding a rate that starts after an
  open window closes that window the day before, so "the rate in force on the
  document date" is always a single answer. An overlapping window is refused
  rather than silently preferred.
- Discount slabs are the discount policy as data, with the percentage above
  which a second person must approve.
- `/api/tax/quote` shows the arithmetic the invoice will use: discount reduces
  the taxable value, the place of supply decides CGST+SGST (or UTGST) versus
  IGST, and the total is rounded to the rupee with the round-off shown.

Nothing here assumes a GST rate for any product: an HSN with no rate in force
is reported as missing, never defaulted.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.india_states import STATE_CODES, state_name
from ..core.rbac import require
from ..models.core import Distributor, Product
from ..models.tax import CompanyProfile, DiscountSlab, TaxRate
from ..services import discounts
from ..services.audit import audit
from ..services.tax import (line_tax, place_of_supply, resolve_rate)
from ..services.tax_ids import normalize_identity

router = APIRouter(prefix="/api", tags=["tax"])

ZERO = Decimal(0)


def _clean(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _mask(value: str | None) -> str | None:
    """Mask a bank account number for the audit trail (FR-12: no secrets in logs)."""
    if not value:
        return value
    tail = value[-4:]
    return f"****{tail}" if len(value) > 4 else "****"


def _check_tax_identity(gstin: str | None, pan: str | None, state_code: str | None,
                        registration_type: str) -> dict:
    """Validate a seller/buyer tax identity and return the values to store.

    The rules live in `services.tax_ids` so the company profile, the supplier
    master and the distributor master enforce exactly the same ones.
    """
    try:
        return normalize_identity(registration_type, gstin, pan, state_code)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# ---------------------------------------------------------------- company profile
class CompanyIn(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    registration_type: Literal["regular", "composition", "unregistered"] = "regular"
    gstin: str | None = None
    pan: str | None = None
    state_code: str | None = None
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    pincode: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=150)
    invoice_prefix: str | None = Field(default=None, max_length=10)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_account_name: str | None = Field(default=None, max_length=150)
    bank_account_number: str | None = Field(default=None, max_length=40)
    bank_ifsc: str | None = Field(default=None, max_length=20)

    @field_validator("gstin", "pan", "state_code", "bank_ifsc")
    @classmethod
    def norm(cls, v): return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @field_validator("invoice_prefix")
    @classmethod
    def prefix(cls, v):
        p = _clean(v)
        if p and not p.replace("/", "").replace("-", "").isalnum():
            raise ValueError("the invoice prefix may contain letters, digits, - and / only")
        return p

    @field_validator("bank_account_number")
    @classmethod
    def account(cls, v):
        p = _clean(v)
        if p and not p.replace(" ", "").isalnum():
            raise ValueError("a bank account number may contain letters and digits only")
        return p


class CompanyOut(BaseModel):
    id: int
    legal_name: str
    trade_name: str | None
    registration_type: str
    gstin: str | None
    pan: str | None
    state_code: str | None
    state: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    pincode: str | None
    phone: str | None
    email: str | None
    invoice_prefix: str | None
    bank_name: str | None
    bank_account_name: str | None
    bank_account_masked: str | None
    bank_ifsc: str | None


def _company_out(c: CompanyProfile) -> CompanyOut:
    return CompanyOut(
        id=c.id, legal_name=c.legal_name, trade_name=c.trade_name,
        registration_type=c.registration_type,
        gstin=c.gstin, pan=c.pan, state_code=c.state_code, state=state_name(c.state_code),
        address_line1=c.address_line1, address_line2=c.address_line2, city=c.city,
        pincode=c.pincode, phone=c.phone, email=c.email, invoice_prefix=c.invoice_prefix,
        bank_name=c.bank_name, bank_account_name=c.bank_account_name,
        bank_account_masked=_mask(c.bank_account_number), bank_ifsc=c.bank_ifsc)


def company_row(db: Session) -> CompanyProfile | None:
    return db.scalars(select(CompanyProfile).order_by(CompanyProfile.id)).first()


@router.get("/company", response_model=CompanyOut | None)
def get_company(db: Session = Depends(get_db), _=Depends(require("tax:read"))):
    row = company_row(db)
    return _company_out(row) if row else None


@router.put("/company", response_model=CompanyOut)
def save_company(body: CompanyIn, db: Session = Depends(get_db),
                 user=Depends(require("tax:write"))):
    ident = _check_tax_identity(body.gstin, body.pan, body.state_code, body.registration_type)
    row = company_row(db)
    values = body.model_dump()
    values.update(ident)
    if not values.get("bank_account_number") and row is not None and row.bank_account_number:
        # an empty account number means "leave the one on file": the number is
        # only ever shown masked, so the form cannot echo it back.
        values["bank_account_number"] = row.bank_account_number
    changes = {}
    if row is None:
        row = CompanyProfile(legal_name=body.legal_name.strip())
        db.add(row)
        changes["created"] = row.legal_name
    for key, value in values.items():
        if key == "legal_name":
            value = value.strip()
        current = getattr(row, key)
        if current != value:
            if key == "bank_account_number":
                current, value = _mask(current), _mask(value)
            changes[key] = {"old": str(current) if current is not None else None,
                            "new": str(value) if value is not None else None}
            setattr(row, key, values[key])
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That GSTIN already belongs to another company record")
    if changes:
        audit(db, user.id, "company.save", f"company:{row.id}", changes)
    db.commit()
    return _company_out(row)


# ---------------------------------------------------------------- GST rate master
class RateIn(BaseModel):
    hsn: str = Field(min_length=4, max_length=8)
    description: str | None = Field(default=None, max_length=200)
    cgst_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    sgst_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    igst_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    cess_rate: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2)
    is_reverse_charge: bool = False
    effective_from: date

    @field_validator("hsn")
    @classmethod
    def digits(cls, v):
        v = v.strip()
        if not v.isdigit():
            raise ValueError("an HSN code is 4 to 8 digits")
        return v

    @field_validator("effective_from")
    @classmethod
    def not_before_2000(cls, v):
        if v < date(2000, 1, 1):
            raise ValueError("effective_from looks wrong (before 2000)")
        return v


class RateOut(BaseModel):
    id: int
    hsn: str
    description: str | None
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    cess_rate: Decimal
    total_rate: Decimal
    is_reverse_charge: bool
    effective_from: date
    effective_to: date | None
    in_force: bool


class CloseIn(BaseModel):
    effective_to: date
    reason: str = Field(min_length=3, max_length=300)


def _rate_out(r: TaxRate, on: date | None = None) -> RateOut:
    from ..services.tax import pct
    in_force = (r.effective_from <= (on or date.today()) and
                (r.effective_to is None or r.effective_to >= (on or date.today())))
    return RateOut(id=r.id, hsn=r.hsn, description=r.description,
                   cgst_rate=pct(r.cgst_rate), sgst_rate=pct(r.sgst_rate),
                   igst_rate=pct(r.igst_rate), cess_rate=pct(r.cess_rate),
                   total_rate=pct(Decimal(r.cgst_rate) + Decimal(r.sgst_rate)),
                   is_reverse_charge=bool(r.is_reverse_charge),
                   effective_from=r.effective_from, effective_to=r.effective_to,
                   in_force=in_force)


@router.get("/tax/rates", response_model=list[RateOut])
def list_rates(hsn: str | None = None, on: date | None = None, current: bool = False,
               db: Session = Depends(get_db), _=Depends(require("tax:read"))):
    q = select(TaxRate).order_by(TaxRate.hsn, TaxRate.effective_from.desc())
    if hsn:
        q = q.where(TaxRate.hsn == hsn.strip())
    if on:
        q = q.where(TaxRate.effective_from <= on,
                    or_(TaxRate.effective_to.is_(None), TaxRate.effective_to >= on))
    rows = db.scalars(q).all()
    if current:
        today = date.today()
        rows = [r for r in rows if r.effective_from <= today and
                (r.effective_to is None or r.effective_to >= today)]
    return [_rate_out(r, on) for r in rows]


@router.post("/tax/rates", response_model=RateOut, status_code=201)
def add_rate(body: RateIn, db: Session = Depends(get_db), user=Depends(require("tax:write"))):
    if Decimal(body.cgst_rate) + Decimal(body.sgst_rate) != Decimal(body.igst_rate):
        raise HTTPException(422, "CGST + SGST must equal IGST for the same supply")
    # An HSN may have several windows, but never two that cover the same day.
    # A new rate that starts later closes the open window the day before it
    # starts; a window that genuinely overlaps is refused.
    previous = db.scalars(select(TaxRate).where(TaxRate.hsn == body.hsn)).all()
    closed = []
    for old in previous:
        if old.effective_from >= body.effective_from:
            raise HTTPException(
                409, f"HSN {body.hsn} already has a rate from {old.effective_from}"
                     f"{' to ' + old.effective_to.isoformat() if old.effective_to else ''}")
        if old.effective_to is None:
            old.effective_to = body.effective_from - timedelta(days=1)
            closed.append({"id": old.id, "until": old.effective_to.isoformat()})
        elif old.effective_to >= body.effective_from:
            raise HTTPException(
                409, f"HSN {body.hsn} already has a rate from {old.effective_from} "
                     f"to {old.effective_to}; close it before starting a new one")
    rate = TaxRate(hsn=body.hsn, description=_clean(body.description),
                   cgst_rate=body.cgst_rate, sgst_rate=body.sgst_rate, igst_rate=body.igst_rate,
                   cess_rate=body.cess_rate, is_reverse_charge=body.is_reverse_charge,
                   effective_from=body.effective_from, created_by=user.id)
    db.add(rate)
    db.flush()
    audit(db, user.id, "tax.rate_add", f"tax_rate:{rate.id}",
          {"hsn": rate.hsn, "cgst": str(rate.cgst_rate), "sgst": str(rate.sgst_rate),
           "igst": str(rate.igst_rate), "cess": str(rate.cess_rate),
           "reverse_charge": bool(rate.is_reverse_charge),
           "effective_from": rate.effective_from.isoformat(), "closed_previous": closed})
    db.commit()
    return _rate_out(rate)


@router.post("/tax/rates/{rate_id}/close", response_model=RateOut)
def close_rate(rate_id: int, body: CloseIn, db: Session = Depends(get_db),
               user=Depends(require("tax:write"))):
    rate = db.get(TaxRate, rate_id)
    if not rate:
        raise HTTPException(404, "Rate not found")
    if body.effective_to < rate.effective_from:
        raise HTTPException(422, "A rate cannot end before it starts")
    if rate.effective_to is not None and rate.effective_to <= body.effective_to:
        raise HTTPException(409, f"This rate already ends on {rate.effective_to}")
    rate.effective_to = body.effective_to
    audit(db, user.id, "tax.rate_close", f"tax_rate:{rate.id}",
          {"hsn": rate.hsn, "effective_to": rate.effective_to.isoformat(),
           "reason": body.reason.strip()})
    db.commit()
    return _rate_out(rate)


# ---------------------------------------------------------------- discount slabs
class SlabIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    scope: Literal["all", "product", "group"] = "all"
    product_id: int | None = None
    group_name: str | None = Field(default=None, max_length=60)
    min_qty: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    max_qty: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    min_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    max_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    discount_percent: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    approval_above: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    effective_from: date
    effective_to: date | None = None


class SlabPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    min_qty: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    max_qty: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    min_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    max_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    discount_percent: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    approval_above: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    effective_to: date | None = None
    is_active: bool | None = None


class SlabOut(BaseModel):
    id: int
    name: str
    scope: str
    product_id: int | None
    product_sku: str | None
    group_name: str | None
    min_qty: Decimal | None
    max_qty: Decimal | None
    min_value: Decimal | None
    max_value: Decimal | None
    discount_percent: Decimal
    approval_above: Decimal | None
    effective_from: date
    effective_to: date | None
    is_active: bool
    band: str
    in_force: bool


def _band(s: DiscountSlab) -> str:
    parts = []
    if s.min_qty is not None or s.max_qty is not None:
        lo = f"{Decimal(s.min_qty):.0f}" if s.min_qty is not None else "0"
        hi = f"{Decimal(s.max_qty):.0f}" if s.max_qty is not None else "any"
        parts.append(f"{lo}-{hi} units")
    if s.min_value is not None or s.max_value is not None:
        lo = f"{Decimal(s.min_value):.2f}" if s.min_value is not None else "0.00"
        hi = f"{Decimal(s.max_value):.2f}" if s.max_value is not None else "any"
        parts.append(f"₹{lo}-{hi} value")
    return ", ".join(parts)


def _slab_out(s: DiscountSlab, skus: dict[int, str]) -> SlabOut:
    today = date.today()
    return SlabOut(id=s.id, name=s.name, scope=s.scope, product_id=s.product_id,
                   product_sku=skus.get(s.product_id), group_name=s.group_name,
                   min_qty=s.min_qty, max_qty=s.max_qty, min_value=s.min_value,
                   max_value=s.max_value, discount_percent=s.discount_percent,
                   approval_above=s.approval_above, effective_from=s.effective_from,
                   effective_to=s.effective_to, is_active=s.is_active, band=_band(s),
                   in_force=(s.is_active and s.effective_from <= today and
                             (s.effective_to is None or s.effective_to >= today)))


def _sku_map(db: Session) -> dict[int, str]:
    return {p.id: p.sku for p in db.scalars(select(Product)).all()}


@router.get("/discount-slabs", response_model=list[SlabOut])
def list_slabs(db: Session = Depends(get_db), _=Depends(require("tax:read"))):
    rows = db.scalars(select(DiscountSlab).order_by(DiscountSlab.scope, DiscountSlab.id)).all()
    skus = _sku_map(db)
    return [_slab_out(s, skus) for s in rows]


@router.post("/discount-slabs", response_model=SlabOut, status_code=201)
def add_slab(body: SlabIn, db: Session = Depends(get_db), user=Depends(require("tax:write"))):
    if body.min_qty is None and body.min_value is None:
        raise HTTPException(422, "A slab needs a quantity band or a value band")
    if body.max_qty is not None and body.min_qty is not None and body.max_qty < body.min_qty:
        raise HTTPException(422, "The quantity band ends before it starts")
    if body.max_value is not None and body.min_value is not None and body.max_value < body.min_value:
        raise HTTPException(422, "The value band ends before it starts")
    if body.effective_to is not None and body.effective_to < body.effective_from:
        raise HTTPException(422, "The slab ends before it starts")
    if body.scope == "product":
        if body.product_id is None:
            raise HTTPException(422, "Choose the product this slab applies to")
        if not db.get(Product, body.product_id):
            raise HTTPException(404, "Product not found")
    if body.scope == "group" and not _clean(body.group_name):
        raise HTTPException(422, "Name the distributor group this slab applies to")

    slab = DiscountSlab(name=body.name.strip(), scope=body.scope, product_id=body.product_id,
                        group_name=_clean(body.group_name), min_qty=body.min_qty,
                        max_qty=body.max_qty, min_value=body.min_value, max_value=body.max_value,
                        discount_percent=body.discount_percent,
                        approval_above=body.approval_above, effective_from=body.effective_from,
                        effective_to=body.effective_to, created_by=user.id)
    clash = discounts.overlaps(db, slab, slab.effective_from, slab.effective_to)
    if clash:
        raise HTTPException(409, f"Slab '{clash.name}' already covers this scope, band and period")
    db.add(slab)
    db.flush()
    audit(db, user.id, "discount.slab_add", f"discount_slab:{slab.id}",
          {"name": slab.name, "scope": slab.scope, "band": _band(slab),
           "discount_percent": str(slab.discount_percent),
           "approval_above": str(slab.approval_above) if slab.approval_above is not None else None,
           "effective_from": slab.effective_from.isoformat()})
    db.commit()
    return _slab_out(slab, _sku_map(db))


@router.patch("/discount-slabs/{slab_id}", response_model=SlabOut)
def update_slab(slab_id: int, body: SlabPatch, db: Session = Depends(get_db),
                user=Depends(require("tax:write"))):
    slab = db.get(DiscountSlab, slab_id)
    if not slab:
        raise HTTPException(404, "Discount slab not found")
    data = body.model_dump(exclude_unset=True)
    changes = {}
    for key, value in data.items():
        current = getattr(slab, key)
        if current != value:
            changes[key] = {"old": str(current) if current is not None else None,
                            "new": str(value) if value is not None else None}
            setattr(slab, key, value)
    if changes:
        audit(db, user.id, "discount.slab_update", f"discount_slab:{slab.id}",
              {"name": slab.name, **changes})
    db.commit()
    return _slab_out(slab, _sku_map(db))


# ---------------------------------------------------------------- the calculator
class QuoteOut(BaseModel):
    hsn: str | None
    rate_found: bool
    message: str | None = None
    computed: dict | None = None
    discount_slab: str | None = None
    slab_discount_percent: Decimal | None = None
    approval_needed: bool = False


@router.get("/tax/quote", response_model=QuoteOut)
def quote(hsn: str = Query(min_length=4, max_length=8), qty: Decimal = Query(gt=0),
          unit_price: Decimal = Query(ge=0),
          discount_percent: Decimal = Query(default=Decimal(0), ge=0, le=100),
          buyer_state: str | None = None, product_id: int | None = None,
          distributor_id: int | None = None, group_name: str | None = None,
          on: date | None = None, db: Session = Depends(get_db),
          _=Depends(require("tax:read"))):
    """What an invoice line would look like: rates, split, tax and round-off."""
    when = on or date.today()
    company = company_row(db)
    if not company or not company.state_code:
        raise HTTPException(409, "Save the company tax profile (with its state) before quoting tax")
    if not buyer_state:
        raise HTTPException(422, "buyer_state is required (the place of supply)")
    rate = resolve_rate(db, hsn, when)
    if not rate:
        return QuoteOut(hsn=hsn, rate_found=False,
                        message=f"No rate is in force for HSN {hsn} on {when}. "
                                f"Add one in the GST rate master; none is assumed.")
    try:
        computed = line_tax(qty=qty, unit_price=unit_price, discount_percent=discount_percent,
                            rate=rate, seller_state=company.state_code, buyer_state=buyer_state)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    computed = {k: (str(v) if not isinstance(v, (dict, int, bool)) else v)
                for k, v in computed.items()}
    if distributor_id and not group_name:
        dist = db.get(Distributor, distributor_id)
        if not dist:
            raise HTTPException(404, "Distributor not found")
        group_name = dist.group_name
    slab = discounts.best_slab(db, on=when, product_id=product_id, group_name=group_name,
                               qty=qty, value=Decimal(qty) * Decimal(unit_price))
    return QuoteOut(hsn=hsn, rate_found=True, computed=computed,
                    discount_slab=slab.name if slab else None,
                    slab_discount_percent=slab.discount_percent if slab else None,
                    approval_needed=discounts.approval_needed(discount_percent, slab))


@router.get("/tax/states")
def states(_=Depends(require("tax:read"))):
    """The state and union-territory codes, so the front end never hard-codes them."""
    return [{"code": code, "name": name, "is_union_territory": ut}
            for code, (name, ut) in sorted(STATE_CODES.items())]


@router.get("/tax/place-of-supply")
def classify(seller_state: str, buyer_state: str, _=Depends(require("tax:read"))):
    try:
        return place_of_supply(seller_state, buyer_state)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
