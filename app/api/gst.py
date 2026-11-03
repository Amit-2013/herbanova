"""Input GST and statutory dues: supplier bills, filed returns and challans.

Reading needs `accounts:read`; capturing a bill, a filed return or a challan needs
`accounts:write`. A supplier bill is never edited: a wrong one is reversed with a
reason and excluded from the register. Filed-return figures can be replaced when
the portal is amended, with the previous values kept in the audit log.

Every dated write passes the same two gates as the rest of Accounts: a locked
accounting month and a closed financial year both refuse it (HTTP 423).
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require
from ..models.accounts import GstReturn, PurchaseInvoice, StatutoryChallan
from ..models.core import PurchaseOrder
from ..models.suppliers import Supplier
from ..services import gst, periods, statutory
from ..services.audit import audit

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

FORMS = ("GSTR-1", "GSTR-3B")


def _day(day: date, what: str) -> None:
    if day > date.today():
        raise HTTPException(422, f"The {what} cannot be in the future")
    if day < date.today() - timedelta(days=3650):
        raise HTTPException(422, f"The {what} is more than ten years ago")


def _gate(db: Session, day: date, action: str) -> None:
    try:
        periods.refuse_if_closed(db, day, action)
    except periods.PeriodClosed as exc:
        raise HTTPException(423, str(exc))


def _json(value):
    """Money leaves as a two-decimal string, never a JSON float.

    A float would lose paisa on the way out and disagree with the accounts API,
    which already serialises every amount as a string.
    """
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


# ------------------------------------------------------------------ models in
class PurchaseInvoiceIn(BaseModel):
    supplier_id: int
    purchase_order_id: int | None = None
    supplier_invoice_number: str = Field(min_length=1, max_length=40)
    invoice_date: date
    taxable_value: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    cgst_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                 decimal_places=2)
    sgst_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                 decimal_places=2)
    igst_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                 decimal_places=2)
    cess_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                 decimal_places=2)
    round_off: Decimal = Field(default=Decimal("0"), ge=-10, le=10,
                               max_digits=4, decimal_places=2)
    itc_eligible: bool = True
    tds_section: str | None = Field(default=None, max_length=10)
    tds_rate: Decimal | None = Field(default=None, ge=0, le=100,
                                     max_digits=5, decimal_places=2)
    tds_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                decimal_places=2)
    note: str | None = Field(default=None, max_length=300)

    @field_validator("supplier_invoice_number")
    @classmethod
    def strip_number(cls, v):
        return v.strip()

    @field_validator("note")
    @classmethod
    def strip_note(cls, v):
        return v.strip() if isinstance(v, str) and v.strip() else None

    @field_validator("tds_section")
    @classmethod
    def upper_section(cls, v):
        if isinstance(v, str) and v.strip():
            return v.strip().upper()
        return None

    @model_validator(mode="after")
    def tds_is_whole(self):
        # A section with no deduction, or a deduction with no section, is an
        # incomplete record rather than a figure to be guessed at.
        if self.tds_section and self.tds_amount <= 0:
            raise ValueError("a TDS section needs a deduction amount")
        if self.tds_amount > 0 and not self.tds_section:
            raise ValueError("a TDS deduction needs a section")
        if self.tds_rate is not None and not self.tds_section:
            raise ValueError("a TDS rate needs a section")
        return self


class ReverseIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)

    @field_validator("reason")
    @classmethod
    def strip(cls, v):
        return v.strip()


class GstReturnIn(BaseModel):
    form: str
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    filed_on: date
    reference: str | None = Field(default=None, max_length=40)
    outward_taxable: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                     decimal_places=2)
    outward_cgst: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                  decimal_places=2)
    outward_sgst: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                  decimal_places=2)
    outward_igst: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                  decimal_places=2)
    outward_cess: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                                  decimal_places=2)
    itc_cgst: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                              decimal_places=2)
    itc_sgst: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                              decimal_places=2)
    itc_igst: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                              decimal_places=2)
    itc_cess: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                              decimal_places=2)
    note: str | None = Field(default=None, max_length=300)

    @field_validator("reference", "note")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) and v.strip() else None

    @model_validator(mode="after")
    def check_form(self):
        if self.form not in FORMS:
            raise ValueError(f"form must be one of {', '.join(FORMS)}")
        if self.form == "GSTR-1" and any(
                v > 0 for v in (self.itc_cgst, self.itc_sgst, self.itc_igst,
                                self.itc_cess)):
            raise ValueError("GSTR-1 reports outward supplies; input credit belongs on GSTR-3B")
        return self


class ChallanIn(BaseModel):
    kind: str
    bsr_code: str | None = Field(default=None, max_length=10)
    challan_number: str = Field(min_length=1, max_length=30)
    paid_on: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    period_year: int = Field(ge=2000, le=2100)
    period_month: int = Field(ge=1, le=12)
    section: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=300)

    @field_validator("bsr_code", "challan_number", "section", "note")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) and v.strip() else None

    @model_validator(mode="after")
    def check_kind(self):
        if self.kind not in statutory.KINDS:
            raise ValueError(f"kind must be one of {', '.join(statutory.KINDS)}")
        return self


# --------------------------------------------------------------- supplier bills
@router.get("/purchase-invoices")
def purchase_invoices(date_from: date | None = None, date_to: date | None = None,
                      include_reversed: bool = False,
                      db: Session = Depends(get_db),
                      _=Depends(require("accounts:read"))):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date is after the end date")
    return _json(gst.register(db, date_from, date_to, include_reversed))


@router.post("/purchase-invoices", status_code=201)
def add_purchase_invoice(body: PurchaseInvoiceIn, db: Session = Depends(get_db),
                         user=Depends(require("accounts:write"))):
    _day(body.invoice_date, "invoice date")
    supplier = db.get(Supplier, body.supplier_id)
    if supplier is None:
        raise HTTPException(404, "Supplier not found")
    if body.purchase_order_id is not None:
        po = db.get(PurchaseOrder, body.purchase_order_id)
        if po is None:
            raise HTTPException(404, "Purchase order not found")
        if po.supplier_id is not None and po.supplier_id != body.supplier_id:
            raise HTTPException(422, "The purchase order belongs to a different supplier")
    taken = db.scalar(select(PurchaseInvoice).where(
        PurchaseInvoice.supplier_id == body.supplier_id,
        PurchaseInvoice.supplier_invoice_number == body.supplier_invoice_number,
        PurchaseInvoice.status == "posted"))
    if taken is not None:
        raise HTTPException(
            409, f"{body.supplier_invoice_number} is already captured for this supplier")
    _gate(db, body.invoice_date, "a purchase invoice")

    row = PurchaseInvoice(
        supplier_id=body.supplier_id, purchase_order_id=body.purchase_order_id,
        supplier_invoice_number=body.supplier_invoice_number,
        invoice_date=body.invoice_date, taxable_value=gst.money(body.taxable_value),
        cgst_amount=gst.money(body.cgst_amount), sgst_amount=gst.money(body.sgst_amount),
        igst_amount=gst.money(body.igst_amount), cess_amount=gst.money(body.cess_amount),
        round_off=gst.money(body.round_off), itc_eligible=body.itc_eligible,
        tds_section=body.tds_section, tds_rate=body.tds_rate,
        tds_amount=gst.money(body.tds_amount), note=body.note, created_by=user.id)
    db.add(row)
    db.flush()
    audit(db, user.id, "accounts.purchase_invoice.create", f"purchase_invoice:{row.id}",
          {"supplier_id": row.supplier_id,
           "supplier_invoice_number": row.supplier_invoice_number,
           "invoice_date": row.invoice_date.isoformat(),
           "taxable": str(row.taxable_value), "tax": str(row.tax_total),
           "itc_eligible": row.itc_eligible,
           "tds_section": row.tds_section, "tds_amount": str(row.tds_amount)})
    db.commit()
    db.refresh(row)
    out = gst.register(db, None, None, True)
    return _json(next(r for r in out["rows"] if r["id"] == row.id))


@router.post("/purchase-invoices/{invoice_id}/reverse")
def reverse_purchase_invoice(invoice_id: int, body: ReverseIn,
                             db: Session = Depends(get_db),
                             user=Depends(require("accounts:write"))):
    row = db.get(PurchaseInvoice, invoice_id, with_for_update=True)
    if row is None:
        raise HTTPException(404, "Purchase invoice not found")
    if row.status == "reversed":
        raise HTTPException(409, "This purchase invoice is already reversed")
    _gate(db, row.invoice_date, "reversed")
    row.status = "reversed"
    row.reversal_reason = body.reason
    audit(db, user.id, "accounts.purchase_invoice.reverse",
          f"purchase_invoice:{row.id}",
          {"supplier_invoice_number": row.supplier_invoice_number,
           "reason": body.reason})
    db.commit()
    return _json(gst.register(db, None, None, True))


@router.get("/input-gst")
def input_gst(date_from: date | None = None, date_to: date | None = None,
              db: Session = Depends(get_db), _=Depends(require("accounts:read"))):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date is after the end date")
    return _json(gst.register(db, date_from, date_to))


@router.get("/gst-net")
def gst_net(date_from: date | None = None, date_to: date | None = None,
            db: Session = Depends(get_db), _=Depends(require("accounts:read"))):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date is after the end date")
    return _json(gst.net(db, date_from, date_to))


# ------------------------------------------------------------- filed returns
@router.get("/gst-returns")
def gst_returns(year: int | None = None, db: Session = Depends(get_db),
                _=Depends(require("accounts:read"))):
    stmt = select(GstReturn).order_by(GstReturn.year, GstReturn.month, GstReturn.form)
    if year is not None:
        stmt = stmt.where(GstReturn.year == year)
    rows = db.scalars(stmt).all()
    return _json({"year": year, "rows": [{
        "id": r.id, "form": r.form, "year": r.year, "month": r.month,
        "filed_on": r.filed_on, "reference": r.reference,
        "outward_taxable": gst.money(r.outward_taxable),
        "outward": {h: gst.money(getattr(r, f"outward_{h}"))
                    for h in gst.HEADS},
        "itc": {h: gst.money(getattr(r, f"itc_{h}")) for h in gst.HEADS},
        "note": r.note,
    } for r in rows]})


@router.post("/gst-returns")
def save_gst_return(body: GstReturnIn, db: Session = Depends(get_db),
                    user=Depends(require("accounts:write"))):
    _day(body.filed_on, "filing date")
    if (body.year, body.month) > (date.today().year, date.today().month):
        raise HTTPException(422, "A return cannot be filed for a month in the future")
    values = {key: gst.money(getattr(body, key)) for key in (
        "outward_taxable", "outward_cgst", "outward_sgst", "outward_igst",
        "outward_cess", "itc_cgst", "itc_sgst", "itc_igst", "itc_cess")}
    row = db.scalar(select(GstReturn).where(
        GstReturn.form == body.form, GstReturn.year == body.year,
        GstReturn.month == body.month))
    if row is None:
        row = GstReturn(form=body.form, year=body.year, month=body.month,
                        created_by=user.id)
        db.add(row)
        action = "accounts.gst_return.create"
    else:
        action = "accounts.gst_return.update"
    old = ({key: str(getattr(row, key) or 0) for key in values}
           if row.id is not None else None)
    for key, value in values.items():
        setattr(row, key, value)
    row.filed_on = body.filed_on
    row.reference = body.reference
    row.note = body.note
    if row.id is not None:
        row.updated_by = user.id
        row.updated_at = datetime.now(timezone.utc)
    db.flush()
    changes = {"form": body.form, "year": body.year, "month": body.month,
               "reference": body.reference}
    if old is not None:
        changes["previous"] = old
    audit(db, user.id, action, f"gst_return:{row.id}", changes)
    db.commit()
    return _json(gst.reconciliation(db, body.year, body.month))


@router.get("/gst-reconciliation")
def gst_reconciliation(year: int | None = None, month: int | None = None,
                       db: Session = Depends(get_db),
                       _=Depends(require("accounts:read"))):
    today = date.today()
    year = year or today.year
    month = month or today.month
    if not 1 <= month <= 12:
        raise HTTPException(422, "month must be between 1 and 12")
    return _json(gst.reconciliation(db, year, month))


# ------------------------------------------------------------------ statutory
@router.get("/statutory-dues")
def statutory_dues(date_from: date | None = None, date_to: date | None = None,
                   db: Session = Depends(get_db),
                   _=Depends(require("accounts:read"))):
    today = date.today()
    start = date_from or today.replace(day=1)
    end = date_to or today
    if start > end:
        raise HTTPException(422, "The start date is after the end date")
    if end > today:
        raise HTTPException(422, "The end date cannot be in the future")
    return _json(statutory.dues(db, start, end))


@router.get("/statutory-challans")
def statutory_challans(kind: str | None = None, date_from: date | None = None,
                       date_to: date | None = None,
                       db: Session = Depends(get_db),
                       _=Depends(require("accounts:read"))):
    if kind is not None and kind not in statutory.KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(statutory.KINDS)}")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date is after the end date")
    rows = statutory.challan_rows(db, kind, date_from, date_to)
    return _json({"rows": rows,
                  "total": statutory.money(sum((r["amount"] for r in rows),
                                              statutory.ZERO))})


@router.post("/statutory-challans", status_code=201)
def add_statutory_challan(body: ChallanIn, db: Session = Depends(get_db),
                          user=Depends(require("accounts:write"))):
    _day(body.paid_on, "payment date")
    if (body.period_year, body.period_month) > (date.today().year, date.today().month):
        raise HTTPException(422, "A challan cannot settle a month in the future")
    _gate(db, body.paid_on, "a statutory challan")
    row = StatutoryChallan(
        kind=body.kind, bsr_code=body.bsr_code, challan_number=body.challan_number,
        paid_on=body.paid_on, amount=gst.money(body.amount),
        period_year=body.period_year, period_month=body.period_month,
        section=body.section, note=body.note, created_by=user.id)
    db.add(row)
    db.flush()
    audit(db, user.id, "accounts.challan.create", f"statutory_challan:{row.id}",
          {"kind": row.kind, "challan_number": row.challan_number,
           "paid_on": row.paid_on.isoformat(), "amount": str(row.amount),
           "period": f"{row.period_year}-{row.period_month:02d}"})
    db.commit()
    return _json(next(r for r in statutory.challan_rows(db) if r["id"] == row.id))
