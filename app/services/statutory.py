"""Deducted tax and other statutory dues, and what has been deposited.

Two sources of a deduction are read, never guessed:

- vendor TDS on captured supplier bills (`purchase_invoices.tds_section`,
  `tds_rate`, `tds_amount`); and
- payroll deductions whose salary component carries a statutory head (pf, esi,
  pt, tds), taken only from payroll periods that reached `approved` or beyond.
  A draft payroll is not a liability.

A challan is recorded money paid to the government. The report subtracts what is
recorded from what was withheld and names the remainder. With no approved
payroll in the window there is no payroll figure at all (`available: false`,
amount `None`) rather than a zero that would read as "nothing is due".
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.accounts import PurchaseInvoice, StatutoryChallan
from ..models.hr import (PayrollEntry, PayrollEntryLine, PayrollPeriod,
                         SalaryComponent)
from ..models.suppliers import Supplier

ZERO = Decimal("0.00")
HEADS = (("pf", "Provident fund"), ("esi", "Employee state insurance"),
         ("pt", "Professional tax"), ("tds", "Tax deducted at source"))
KINDS = tuple(key for key, _ in HEADS)
PAYROLL_STATUSES = ("approved", "processed", "paid")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"), ROUND_HALF_UP)


def month_key(day: date) -> tuple[int, int]:
    return day.year, day.month


# ------------------------------------------------------------------ vendor TDS
def vendor_tds(db: Session, date_from: date | None = None,
               date_to: date | None = None) -> dict:
    stmt = (select(PurchaseInvoice)
            .where(PurchaseInvoice.status == "posted",
                   PurchaseInvoice.tds_amount > 0)
            .order_by(PurchaseInvoice.invoice_date, PurchaseInvoice.id))
    if date_from is not None:
        stmt = stmt.where(PurchaseInvoice.invoice_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(PurchaseInvoice.invoice_date <= date_to)
    names = dict(db.execute(select(Supplier.id, Supplier.name)).all())
    rows = [{
        "id": pi.id, "number": pi.number,
        "supplier_invoice_number": pi.supplier_invoice_number,
        "invoice_date": pi.invoice_date,
        "supplier_id": pi.supplier_id, "supplier": names.get(pi.supplier_id),
        "section": pi.tds_section, "rate": pi.tds_rate,
        "tds_amount": money(pi.tds_amount),
    } for pi in db.scalars(stmt).all()]
    sections: dict[str | None, dict] = {}
    for row in rows:
        entry = sections.setdefault(row["section"] or "unspecified",
                                    {"section": row["section"],
                                     "amount": ZERO, "count": 0})
        entry["amount"] = money(entry["amount"] + row["tds_amount"])
        entry["count"] += 1
    total = money(sum((r["tds_amount"] for r in rows), ZERO))
    return {"rows": rows, "count": len(rows), "total": total,
            "sections": sorted(sections.values(),
                               key=lambda s: (-s["amount"], s["section"] or "")),
            "note": ("Deductions recorded on supplier bills. Whether a deduction "
                     "was required for a section is decided by the accounts desk; "
                     "the application does not judge it.")}


# --------------------------------------------------------------- payroll dues
def _components(db: Session) -> dict[int, SalaryComponent]:
    return {c.id: c for c in db.scalars(select(SalaryComponent)).all()}


def _periods(db: Session, date_from: date | None, date_to: date | None,
             as_of: date | None) -> list[PayrollPeriod]:
    stmt = select(PayrollPeriod).where(PayrollPeriod.status.in_(PAYROLL_STATUSES))
    if as_of is not None:
        stmt = stmt.where(PayrollPeriod.year * 100 + PayrollPeriod.month
                          <= as_of.year * 100 + as_of.month)
    elif date_to is not None:
        stmt = stmt.where(PayrollPeriod.year * 100 + PayrollPeriod.month
                          <= date_to.year * 100 + date_to.month)
    if date_from is not None:
        stmt = stmt.where(PayrollPeriod.year * 100 + PayrollPeriod.month
                          >= date_from.year * 100 + date_from.month)
    return db.scalars(stmt.order_by(PayrollPeriod.year, PayrollPeriod.month)).all()


def payroll_dues(db: Session, date_from: date | None = None,
                 date_to: date | None = None, as_of: date | None = None) -> dict:
    periods = _periods(db, date_from, date_to, as_of)
    comps = _components(db)
    grouped: dict[str, list[dict]] = {key: [] for key in KINDS}
    unmapped: list[dict] = []
    for period in periods:
        for entry in db.scalars(select(PayrollEntry)
                                .where(PayrollEntry.period_id == period.id)).all():
            for line in db.scalars(select(PayrollEntryLine)
                                   .where(PayrollEntryLine.entry_id == entry.id)).all():
                if line.kind != "deduction":
                    continue
                comp = comps.get(line.component_id) if line.component_id else None
                if comp is None or not comp.statutory:
                    continue
                row = {"period_year": period.year, "period_month": period.month,
                       "component_code": comp.code, "component": comp.name,
                       "amount": money(line.amount)}
                if comp.statutory_head in grouped:
                    grouped[comp.statutory_head].append(row)
                else:
                    unmapped.append(row)

    heads = []
    for key, label in HEADS:
        configured = [c.code for c in comps.values()
                      if c.statutory and c.statutory_head == key and c.active]
        lines = grouped[key]
        heads.append({
            "head": key, "label": label,
            "available": bool(periods),
            "amount": money(sum((r["amount"] for r in lines), ZERO)) if periods else None,
            "components": configured,
            "count": len(lines),
            "reason": (None if periods else
                       "No approved payroll period falls in this window."),
        })
    if unmapped:
        codes = sorted({r["component_code"] for r in unmapped})
        reason = ("Statutory component(s) with no statutory head: " + ", ".join(codes)
                  + ". Their amounts are excluded from every head.")
    else:
        reason = None
    return {
        "available": bool(periods),
        "periods": [{"year": p.year, "month": p.month, "status": p.status}
                    for p in periods],
        "heads": heads,
        "unmapped": unmapped,
        "reason": (None if periods else
                   "No approved payroll period falls in this window, so payroll "
                   "statutory dues cannot be reported."),
        "unmapped_reason": reason,
        "note": ("Only approved, processed or paid payroll is read. A head with no "
                 "component configured still shows its amount, which is zero because "
                 "payroll withheld nothing under it."),
    }


# ------------------------------------------------------------------- challans
def challan_rows(db: Session, kind: str | None = None,
                 date_from: date | None = None, date_to: date | None = None,
                 as_of: date | None = None) -> list[dict]:
    stmt = select(StatutoryChallan).order_by(StatutoryChallan.paid_on.desc(),
                                             StatutoryChallan.id.desc())
    if kind is not None:
        stmt = stmt.where(StatutoryChallan.kind == kind)
    if date_from is not None:
        stmt = stmt.where(StatutoryChallan.paid_on >= date_from)
    if date_to is not None:
        stmt = stmt.where(StatutoryChallan.paid_on <= date_to)
    if as_of is not None:
        stmt = stmt.where(StatutoryChallan.paid_on <= as_of)
    return [{
        "id": c.id, "kind": c.kind,
        "label": dict(HEADS).get(c.kind, c.kind),
        "bsr_code": c.bsr_code, "challan_number": c.challan_number,
        "paid_on": c.paid_on, "amount": money(c.amount),
        "period_year": c.period_year, "period_month": c.period_month,
        "section": c.section, "note": c.note,
    } for c in db.scalars(stmt).all()]


def _cumulative(db: Session, as_of: date, kind: str) -> Decimal | None:
    """Everything withheld under one head up to a date; None when no source exists."""
    vendor = money(sum((r["tds_amount"] for r in vendor_tds(db, None, as_of)["rows"]),
                       ZERO))
    payroll = payroll_dues(db, None, None, as_of=as_of)
    if kind == "tds":
        payroll_amount = next((h["amount"] for h in payroll["heads"]
                               if h["head"] == "tds"), None)
        if payroll_amount is None and not vendor:
            return None
        return money(vendor + (payroll_amount or ZERO))
    head = next((h for h in payroll["heads"] if h["head"] == kind), None)
    return None if head is None or head["amount"] is None else money(head["amount"])


def dues(db: Session, date_from: date, date_to: date) -> dict:
    """Withheld, deposited and outstanding, per head, at the window end."""
    vendor = vendor_tds(db, date_from, date_to)
    payroll = payroll_dues(db, date_from, date_to)
    in_window = challan_rows(db, date_from=date_from, date_to=date_to)
    deposited_window: dict[str, Decimal] = {key: ZERO for key in KINDS}
    for row in in_window:
        deposited_window[row["kind"]] = money(deposited_window[row["kind"]] + row["amount"])
    deposited_to_date: dict[str, Decimal] = {key: ZERO for key in KINDS}
    for row in challan_rows(db, as_of=date_to):
        deposited_to_date[row["kind"]] = money(deposited_to_date[row["kind"]]
                                               + row["amount"])

    summary = []
    for key, label in HEADS:
        withheld = _cumulative(db, date_to, key)
        outstanding = (None if withheld is None
                       else money(withheld - deposited_to_date[key]))
        summary.append({
            "kind": key, "label": label,
            "withheld_to_date": withheld,
            "deposited_to_date": deposited_to_date[key],
            "deposited_in_window": deposited_window[key],
            "outstanding": outstanding,
            "available": withheld is not None,
            "reason": (None if withheld is not None else
                       "No deduction is recorded for this head up to the window end."),
        })
    available = any(row["available"] for row in summary)
    return {
        "from": date_from, "to": date_to, "as_of": date_to,
        "vendor_tds": vendor,
        "payroll": payroll,
        "challans": {"rows": challan_rows(db, date_from=date_from, date_to=date_to),
                     "deposited_in_window": deposited_window,
                     "deposited_to_date": deposited_to_date},
        "summary": summary,
        "available": available,
        "reason": (None if available else
                   "No TDS, PF, ESI or PT deduction is recorded up to the window "
                   "end, so statutory dues cannot be reported."),
        "notes": [
            "Withheld and deposited are cumulative up to the window end; the window "
            "itself is shown for the challans paid in it.",
            "A deduction is a liability from the month it was withheld, whether or "
            "not a challan exists; the outstanding line is what no challan covers.",
            "PF, ESI and PT come only from approved payroll; vendor TDS comes only "
            "from captured supplier bills.",
        ],
    }
