"""Input GST, net GST payable and reconciliation with filed returns.

Input tax can only come from a supplier's bill: a purchase order carries a cost,
not a tax split. `PurchaseInvoice` therefore records the tax the supplier
charged, head by head, and is the sole source of the input register. Payables are
untouched by this module - they stay the cost of goods received minus payments -
so capturing a bill never changes what is owed.

Two honest limits are part of the result rather than hidden:

- With no posted purchase invoice at all, there is no input data. The response
  says so (`available: false`) instead of reporting zero ITC, which would
  overstate what is payable.
- Creditable GST on approved expenses is recorded in the expense register as a
  single amount with no head split, so it cannot be placed in a CGST/SGST/IGST
  column. It is returned as a memo (`expense_itc`) and is not netted here; the
  note says so.

Reconciliation compares the registers with what was *reported as filed*. It does
not file, does not read the portal, and does not decide which side is right: a
difference is shown with both figures, because amendments and blocked credits are
outside the application's knowledge.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.accounts import GstReturn, PurchaseInvoice
from ..models.expenses import APPROVED, Expense
from ..models.suppliers import Supplier
from . import ledger

ZERO = Decimal("0.00")
HEADS = ("cgst", "sgst", "igst", "cess")


def money(value) -> Decimal:
    # Half-up, the same rule as the rest of accounting (F-01).
    return Decimal(value or 0).quantize(Decimal("0.01"), ROUND_HALF_UP)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def captured_any(db: Session) -> bool:
    """Whether any purchase invoice has ever been posted."""
    return bool(db.scalar(select(PurchaseInvoice.id)
                          .where(PurchaseInvoice.status == "posted").limit(1)))


def _row(pi: PurchaseInvoice, names: dict[int, str]) -> dict:
    return {
        "id": pi.id, "number": pi.number,
        "supplier_invoice_number": pi.supplier_invoice_number,
        "invoice_date": pi.invoice_date,
        "supplier_id": pi.supplier_id, "supplier": names.get(pi.supplier_id),
        "purchase_order_id": pi.purchase_order_id,
        "taxable": money(pi.taxable_value),
        "cgst": money(pi.cgst_amount), "sgst": money(pi.sgst_amount),
        "igst": money(pi.igst_amount), "cess": money(pi.cess_amount),
        "round_off": money(pi.round_off),
        "tax_total": money(pi.tax_total), "total": money(pi.total),
        "itc_eligible": bool(pi.itc_eligible),
        "tds_section": pi.tds_section, "tds_rate": pi.tds_rate,
        "tds_amount": money(pi.tds_amount),
        "status": pi.status, "reversal_reason": pi.reversal_reason,
        "note": pi.note,
    }


def _totals(rows: list[dict]) -> dict:
    taxable = money(sum((r["taxable"] for r in rows), ZERO))
    heads = {h: money(sum((r[h] for r in rows), ZERO)) for h in HEADS}
    tax = money(sum(heads.values(), ZERO))
    round_off = money(sum((r["round_off"] for r in rows), ZERO))
    return {"taxable": taxable, **heads, "tax": tax, "round_off": round_off,
            "total": money(taxable + tax + round_off)}


def register(db: Session, date_from: date | None = None, date_to: date | None = None,
             include_reversed: bool = False) -> dict:
    """The input register: tax captured on supplier bills, head by head.

    Reversed invoices are excluded unless asked for, and are always flagged.
    Eligibility is whatever the person who captured the bill recorded; the
    application does not judge whether a credit is blocked.
    """
    stmt = select(PurchaseInvoice).order_by(PurchaseInvoice.invoice_date,
                                            PurchaseInvoice.id)
    if not include_reversed:
        stmt = stmt.where(PurchaseInvoice.status == "posted")
    if date_from is not None:
        stmt = stmt.where(PurchaseInvoice.invoice_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(PurchaseInvoice.invoice_date <= date_to)
    names = dict(db.execute(select(Supplier.id, Supplier.name)).all())
    rows = [_row(pi, names) for pi in db.scalars(stmt).all()]
    posted = [r for r in rows if r["status"] == "posted"]
    eligible_rows = [r for r in posted if r["itc_eligible"]]
    blocked_rows = [r for r in posted if not r["itc_eligible"]]
    return {
        "from": date_from, "to": date_to,
        "rows": rows,
        "count": len(rows),
        "posted_count": len(posted),
        "totals": _totals(posted),
        "eligible": _totals(eligible_rows),
        "blocked": _totals(blocked_rows),
        "blocked_count": len(blocked_rows),
        "available": captured_any(db),
        "note": ("Tax as captured on supplier bills. A reversed bill is kept and "
                 "flagged but excluded from the totals. Whether a credit is "
                 "eligible is recorded on the bill; the application does not judge it."),
    }


def expense_itc(db: Session, date_from: date | None = None,
                date_to: date | None = None) -> dict:
    """Creditable GST on approved expenses, as a memo - one amount, no head split.

    An expense stores a single GST amount, so it cannot be placed in a CGST,
    SGST or IGST column and is not netted into the payable figure.
    """
    stmt = select(func.count(Expense.id), func.coalesce(func.sum(Expense.gst_amount), 0)) \
        .where(Expense.status == APPROVED, Expense.gst_creditable.is_(True))
    if date_from is not None:
        stmt = stmt.where(Expense.entry_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Expense.entry_date <= date_to)
    count, amount = db.execute(stmt).one()
    return {"count": int(count), "amount": money(amount), "included_in_net": False,
            "note": ("Creditable GST on approved expenses. It is not netted into "
                     "the payable figure because an expense records one GST amount "
                     "with no head split.")}


def net(db: Session, date_from: date | None = None, date_to: date | None = None) -> dict:
    """Output tax minus eligible input tax, head by head.

    `available` is false until at least one purchase invoice has been posted:
    reporting zero ITC with no input data would overstate the payable.
    """
    outward = ledger.gst_register(db, date_from, date_to)["totals"]
    inp = register(db, date_from, date_to)
    eligible = inp["eligible"]
    by_head = {h: money(Decimal(outward[h]) - Decimal(eligible[h])) for h in HEADS}
    blocked = {h: money(Decimal(inp["totals"][h]) - Decimal(eligible[h])) for h in HEADS}
    return {
        "from": date_from, "to": date_to,
        "output": {h: money(outward[h]) for h in HEADS},
        "output_total": money(sum((Decimal(outward[h]) for h in HEADS), ZERO)),
        "input": {h: money(eligible[h]) for h in HEADS},
        "input_total": money(sum((Decimal(eligible[h]) for h in HEADS), ZERO)),
        "blocked_input": blocked,
        "blocked_total": money(sum(blocked.values(), ZERO)),
        "net": by_head,
        "net_total": money(sum(by_head.values(), ZERO)),
        "expense_itc": expense_itc(db, date_from, date_to),
        "available": inp["available"],
        "reason": (None if inp["available"] else
                   "No purchase invoice has been posted, so input GST and net "
                   "payable cannot be reported. Capture a supplier bill first."),
        "note": ("Net is output GST from issued documents minus eligible input GST "
                 "captured on supplier bills; a negative figure is a credit. "
                 "Blocked input is shown separately and never netted."),
    }


# --------------------------------------------------------------- reconciliation
def _check(key: str, label: str, filed, computed, form: str,
           reason: str | None = None) -> dict:
    if computed is None:
        return {"key": key, "label": label, "form": form, "filed": money(filed),
                "computed": None, "difference": None, "ok": None, "reason": reason}
    filed, computed = money(filed), money(computed)
    difference = money(filed - computed)
    return {"key": key, "label": label, "form": form, "filed": filed,
            "computed": computed, "difference": difference,
            "ok": abs(difference) < Decimal("0.005"), "reason": reason}


def reconciliation(db: Session, year: int, month: int) -> dict:
    """Compare the registers with what was reported as filed for one month."""
    start, end = month_bounds(year, month)
    outward = ledger.gst_register(db, start, end)["totals"]
    inp = register(db, start, end)
    eligible = inp["eligible"]
    input_reason = (None if inp["available"] else
                    "No purchase invoice has been posted, so input tax cannot be compared.")
    filed = {r.form: r for r in db.scalars(
        select(GstReturn).where(GstReturn.year == year, GstReturn.month == month)).all()}

    forms = []
    for form in ("GSTR-1", "GSTR-3B"):
        row = filed.get(form)
        if row is None:
            forms.append({"form": form, "filed": None, "checks": [], "ok": None})
            continue
        checks = [
            _check(f"outward_{h}", f"Outward {h.upper()}", getattr(row, f"outward_{h}"),
                   outward[h], form) for h in HEADS
        ] + [_check("outward_taxable", "Outward taxable value", row.outward_taxable,
                    outward["taxable"], form)]
        if form == "GSTR-3B":
            checks += [
                _check(f"itc_{h}", f"Input {h.upper()}", getattr(row, f"itc_{h}"),
                       eligible[h] if inp["available"] else None, form,
                       reason=input_reason) for h in HEADS
            ]
            filed_payable = money(sum((Decimal(getattr(row, f"outward_{h}"))
                                       - Decimal(getattr(row, f"itc_{h}"))
                                       for h in HEADS), ZERO))
            computed_payable = None
            if inp["available"]:
                computed_payable = money(sum((Decimal(outward[h]) - Decimal(eligible[h])
                                              for h in HEADS), ZERO))
            checks.append(_check("tax_payable", "Tax payable after ITC", filed_payable,
                                 computed_payable, form, reason=input_reason))
        forms.append({
            "form": form, "filed": {
                "filed_on": row.filed_on, "reference": row.reference,
                "outward_taxable": money(row.outward_taxable),
                "outward": {h: money(getattr(row, f"outward_{h}")) for h in HEADS},
                "itc": {h: money(getattr(row, f"itc_{h}")) for h in HEADS},
                "note": row.note,
            },
            "checks": checks,
            "ok": all(c["ok"] is not False for c in checks),
            "differences": [c["key"] for c in checks if c["ok"] is False],
        })

    return {
        "year": year, "month": month, "from": start, "to": end,
        "computed": {
            "outward": {h: money(outward[h]) for h in HEADS},
            "outward_taxable": money(outward["taxable"]),
            "input": {h: money(eligible[h]) for h in HEADS},
            "input_available": inp["available"],
            "input_reason": input_reason,
            "tax_payable": (money(sum((Decimal(outward[h]) - Decimal(eligible[h])
                                       for h in HEADS), ZERO))
                            if inp["available"] else None),
        },
        "forms": forms,
        "available": bool(filed),
        "reason": (None if filed else
                   "No filed return is recorded for this month. Record the figures "
                   "reported as filed to compare them with the registers."),
        "note": ("Filed figures are what the practitioner reported; the application "
                 "does not file and does not read the portal. A difference is shown, "
                 "not resolved."),
    }
