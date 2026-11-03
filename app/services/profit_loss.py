"""Profit and loss built from documents the system actually holds.

Revenue and returns are taxable value: GST is collected for the government, not
earned, so it never enters profit. Cost of goods comes from the captured stock
ledger (`costing.invoice_cogs`), so an invoice whose issues are not fully costed
makes gross profit partial rather than silently complete. Expenses are approved,
non-reversed entries in the window, with non-creditable GST added to cost.
Payroll is the gross salary of approved, processed or paid monthly periods, and
never both expenses and payroll for the same money: the system payroll head
refuses manual entries.

A month of payroll counts in full when the whole month lies inside the window
and its period is approved or later. When the window cuts a month short, the
approved month's gross is allocated by each employee's working-day share of
that month; the allocation is labelled and never applied to a month with no
approved payroll. The same rule applies to expense tracking: a window that
starts before `expense_settings.tracked_from` has a gap, not a zero.

Net profit is reported only when every invoice is costed, expenses are tracked
for the whole window and payroll is complete. Until then the statement shows the
figures it can prove, labels gross profit partial, and lists what is missing.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.core import CreditNote, DebitNote, Invoice
from ..models.expenses import APPROVED, Expense, ExpenseHead, ExpenseSettings
from ..models.hr import PayrollEntry, PayrollPeriod
from ..models.users import Employee
from . import costing
from . import hr as hr_svc

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
PAYROLL_GOOD = ("approved", "processed", "paid")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def financial_year(today: date) -> tuple[date, date]:
    """The Indian financial year (1 April to 31 March) containing `today`."""
    first = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    return first, date(first.year + 1, 3, 31)


def defaults(today: date) -> tuple[date, date]:
    """The window a report uses when the caller gives none: this financial year
    up to today, so a report never silently spans all history."""
    start, _end = financial_year(today)
    return start, today


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _months(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month, *_month_bounds(year, month)
        month += 1
        if month == 13:
            year, month = year + 1, 1


def _expenses(db: Session, start: date, end: date) -> dict:
    settings = db.get(ExpenseSettings, 1)
    tracked_from = settings.tracked_from if settings else None
    grouped: dict[int, dict] = {}
    for head_id, head, amount, gst, creditable in db.execute(
            select(Expense.head_id, ExpenseHead.name, Expense.amount,
                   Expense.gst_amount, Expense.gst_creditable)
            .join(ExpenseHead, ExpenseHead.id == Expense.head_id)
            .where(Expense.status == APPROVED, Expense.entry_date >= start,
                   Expense.entry_date <= end)).all():
        item = grouped.setdefault(head_id, {
            "head_id": head_id, "head": head, "net": ZERO,
            "gst_noncreditable": ZERO, "count": 0})
        item["net"] += Decimal(amount)
        if not creditable:
            item["gst_noncreditable"] += Decimal(gst)
        item["count"] += 1
    for item in grouped.values():
        # Creditable GST is reclaimed, so it is not a cost. Non-creditable GST
        # cannot be reclaimed and is part of what the expense cost the business.
        item["amount"] = item["net"] + item["gst_noncreditable"]
    rows = sorted(grouped.values(), key=lambda r: (-r["amount"], r["head"]))
    total = sum((r["amount"] for r in rows), ZERO)
    net = sum((r["net"] for r in rows), ZERO)
    noncreditable = sum((r["gst_noncreditable"] for r in rows), ZERO)
    complete = tracked_from is not None and start >= tracked_from
    return {
        "total": money(total),
        "net": money(net),
        "gst_noncreditable": money(noncreditable),
        "count": sum(r["count"] for r in rows),
        "by_head": [{**r, "amount": money(r["amount"]), "net": money(r["net"]),
                     "gst_noncreditable": money(r["gst_noncreditable"])}
                    for r in rows],
        "tracked_from": tracked_from.isoformat() if tracked_from else None,
        "complete": complete,
        "missing_from": (tracked_from.isoformat()
                         if tracked_from and start < tracked_from else None),
    }


def _period_gross(db: Session, period: PayrollPeriod) -> Decimal:
    return Decimal(db.scalar(
        select(func.coalesce(func.sum(PayrollEntry.gross), 0))
        .where(PayrollEntry.period_id == period.id)) or 0)


def _allocate(db: Session, period: PayrollPeriod, wstart: date, wend: date,
              calendars: dict) -> Decimal:
    """The part of an approved month that falls inside the window.

    Each employee's own working-day calendar is the basis: payroll already
    spreads fixed components over those days, so the share is of a recorded
    gross, not a re-estimate of one. A month with no approved payroll is never
    allocated and is reported as a gap instead.
    """
    total = ZERO
    for entry in period.entries:
        month_days = calendars.get((entry.employee_id, period.year, period.month))
        if month_days is None:
            employee = db.get(Employee, entry.employee_id)
            month_days = (hr_svc.working_days(db, employee, period.year, period.month)
                          if employee is not None else [])
            calendars[(entry.employee_id, period.year, period.month)] = month_days
        if not month_days:
            continue
        inside = sum(1 for day in month_days if wstart <= day <= wend)
        total += Decimal(entry.gross) * Decimal(inside) / Decimal(len(month_days))
    return money(total)


def _payroll(db: Session, start: date, end: date) -> dict:
    periods = {(p.year, p.month): p for p in db.scalars(select(PayrollPeriod)).all()}
    included, missing, partial = [], [], []
    total = ZERO
    calendars: dict = {}
    for year, month, first, last in _months(start, end):
        period = periods.get((year, month))
        status = period.status if period else None
        whole = first >= start and last <= end
        item = {"year": year, "month": month, "status": status}
        if whole:
            value = _period_gross(db, period) if period else ZERO
            item["gross"] = money(value)
            if status in PAYROLL_GOOD:
                item["included"] = True
                included.append(item)
                total += value
            else:
                item["included"] = False
                missing.append(item)
            continue
        wstart, wend = max(start, first), min(end, last)
        if status in PAYROLL_GOOD and period is not None:
            allocated = _allocate(db, period, wstart, wend, calendars)
            item.update(gross=money(_period_gross(db, period)), included=True,
                        prorated=True, allocated=allocated,
                        portion=f"{wstart.isoformat()} to {wend.isoformat()}")
            included.append(item)
            total += allocated
        else:
            # No approved payroll for this month: a share of it would be a guess,
            # so the month is named as a gap and left out.
            item["gross"] = money(_period_gross(db, period) if period else ZERO)
            item["included"] = False
            partial.append(item)
    return {
        "total": money(total),
        "periods": included,
        "missing_months": missing,
        "partial_months": partial,
        "complete": not missing and not partial,
        "method": ("A month wholly inside the window counts in full. A month cut by "
                   "the window counts its approved gross allocated by each "
                   "employee's working-day share of that month."),
    }


def _gap(code: str, label: str, detail: str, fix: str, fix_label: str) -> dict:
    return {"code": code, "label": label, "detail": detail,
            "fix": fix, "fix_label": fix_label}


def statement(db: Session, start: date, end: date) -> dict:
    """The profit and loss for `start`..`end`, with explicit gaps."""
    if start > end:
        raise ValueError("'from' must not be after 'to'")

    invoices = db.execute(
        select(Invoice.id, Invoice.taxable_value)
        .where(Invoice.status == "issued", Invoice.invoice_date >= start,
               Invoice.invoice_date <= end)).all()
    invoice_ids = [row[0] for row in invoices]
    revenue = sum((Decimal(row[1]) for row in invoices), ZERO)

    returns = db.execute(
        select(func.count(CreditNote.id),
               func.coalesce(func.sum(CreditNote.taxable_value), 0))
        .where(CreditNote.status == "issued", CreditNote.note_date >= start,
               CreditNote.note_date <= end)).one()
    returns_count, returns_value = int(returns[0]), Decimal(returns[1])

    debits = db.execute(
        select(func.count(DebitNote.id),
               func.coalesce(func.sum(DebitNote.taxable_value), 0))
        .where(DebitNote.status == "issued", DebitNote.note_date >= start,
               DebitNote.note_date <= end)).one()
    debit_count, debit_value = int(debits[0]), Decimal(debits[1])

    net_revenue = revenue - returns_value + debit_value

    costs = costing.invoice_cogs(db, invoice_ids) if invoice_ids else {}
    cogs_value = money(sum((item["cogs"] for item in costs.values()), ZERO))
    costed = [item for item in costs.values() if item["costed"]]
    uncosted = [item for item in costs.values() if not item["costed"]]
    total_invoices = len(invoice_ids)
    invoices_costed = len(costed)
    gross_profit = money(net_revenue - cogs_value)
    all_costed = total_invoices == invoices_costed
    if all_costed:
        gross_label = "Gross profit"
    else:
        gross_label = (f"Gross profit (partial, {invoices_costed} of "
                       f"{total_invoices} invoices costed)")

    expenses = _expenses(db, start, end)
    payroll = _payroll(db, start, end)

    available = all_costed and expenses["complete"] and payroll["complete"]
    net_profit = (money(gross_profit - expenses["total"] - payroll["total"])
                  if available else None)

    gaps = []
    if not all_costed:
        reasons: dict[str, int] = {}
        for item in uncosted:
            reasons[item["partial_reason"] or "no cost"] = \
                reasons.get(item["partial_reason"] or "no cost", 0) + 1
        top = "; ".join(f"{count} × {reason}" for reason, count in
                        sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))
        gaps.append(_gap(
            "GAP-P01", "Invoice costs are incomplete",
            f"{len(uncosted)} of {total_invoices} invoices in this window are not "
            f"fully costed ({top}). Gross profit covers only the costed invoices.",
            "#/inventory/ledger", "Open the stock ledger"))
    if not expenses["complete"]:
        if expenses["missing_from"]:
            detail = (f"Expenses are recorded from {expenses['missing_from']}, and this "
                      "window starts before that. Months before the start date have no "
                      "expense records to report.")
        else:
            detail = ("No expense tracking start date is configured, so expenses for "
                      "this window cannot be shown.")
        gaps.append(_gap("GAP-P02", "Expenses are not tracked for the whole window",
                         detail, "#/expenses", "Open Expenses"))
    if not payroll["complete"]:
        absent = [f"{i['year']}-{i['month']:02d} ({i['status'] or 'no period'})"
                  for i in payroll["missing_months"]]
        partly = [f"{i['year']}-{i['month']:02d}" for i in payroll["partial_months"]]
        detail = []
        if absent:
            detail.append("Payroll is not approved for " + ", ".join(absent))
        if partly:
            detail.append("Payroll is not approved for " + ", ".join(partly)
                          + ", which the window only partly covers")
        gaps.append(_gap(
            "GAP-P03", "Payroll is incomplete for the window",
            ". ".join(detail) + ". Only an approved month is counted, whole or "
            "allocated by working days; nothing is estimated.",
            "#/hr/payroll", "Open HR payroll"))

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": (end - start).days + 1,
        "revenue": {
            "taxable": money(revenue), "invoices": total_invoices,
            "debit_notes": money(debit_value), "debit_notes_count": debit_count,
        },
        "returns": {"taxable": money(returns_value), "count": returns_count},
        "net_revenue": money(net_revenue),
        "cogs": {
            "value": cogs_value,
            "invoices_total": total_invoices,
            "invoices_costed": invoices_costed,
            "invoices_partial": len(uncosted),
            "costed": all_costed,
            "label": gross_label,
        },
        "gross_profit": {
            "value": gross_profit, "available": True, "partial": not all_costed,
            "label": gross_label,
        },
        "expenses": expenses,
        "payroll": payroll,
        "net_profit": {
            "value": net_profit, "available": available,
            "label": ("Net profit" if available
                      else "Net profit (not available until cost, expenses and "
                           "payroll are complete)"),
        },
        "gaps": gaps,
        "notes": [
            "Revenue and returns are taxable value, before GST. GST is collected on "
            "behalf of the government, so it does not change profit.",
            "Cost of goods sold is the captured issue cost, less the cost of stock "
            "actually returned. A price-only credit note reduces revenue only.",
            "Cost of goods uses the purchase-order rate without freight or discounts, "
            "because neither is recorded.",
            "Costing method: weighted average per product, company-wide, captured when "
            "stock is issued.",
            "Payroll cost is gross salary from approved, processed or paid periods, "
            "without employer contributions. A month the window cuts short is counted "
            "by its working-day share and marked as allocated.",
            "Expenses are approved, non-reversed entries; non-creditable GST is added "
            "to cost and creditable GST is not.",
        ] + ([f"Expenses are recorded from {expenses['tracked_from']}."]
             if expenses["tracked_from"] else []),
    }
