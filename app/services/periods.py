"""Accounting periods: the financial year, its close, and the month locks.

A finance year runs April to March and is labelled "2025-26" on screen (the
document counters keep their shorter "25-26" prefix; `short_label()` converts).
Two gates sit in front of every dated accounting document:

- a month lock, the same `hr_period_locks` row with scope `accounting` that
  expense entries and cost corrections already honour; and
- a closed financial year, recorded in `financial_year_closes`.

Both are gateways, not copies of the balances. Nothing is posted by a close;
it records that the year's documents are final, by whom and why, and refuses a
document dated inside it before anything is written. Reopening records the
reopen trail, and the year can be closed again later.

The two gates are deliberately different in scope. A month lock is a routine
"stop posting into March while we reconcile"; a year close is the annual
"these books are done". A year is therefore only closed after its last day has
passed - closing the year in progress would block the business's own trading -
and reopening needs the Administrator, exactly like unlocking a month.
"""
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.accounts import FinancialYearClose, Payment
from ..models.core import CreditNote, DebitNote, Invoice, PurchaseOrder
from ..models.expenses import Expense
from ..models.hr import PeriodLock
from ..models.suppliers import GoodsReceipt

UNIT = "accounting"


class PeriodClosed(Exception):
    """A dated document fell in a closed year or a locked month."""


# ------------------------------------------------------------------ year maths
def fy_start(day: date) -> date:
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def fy_end(day: date) -> date:
    start = fy_start(day)
    return date(start.year + 1, 3, 31)


def fy_label(day: date) -> str:
    """The full label for the year containing `day`: 2025-26."""
    start = fy_start(day).year
    return f"{start}-{(start + 1) % 100:02d}"


def label_bounds(label: str) -> tuple[date, date]:
    start = int(label[:4])
    return date(start, 4, 1), date(start + 1, 3, 31)


def short_label(label: str) -> str:
    """The counter form of a full label: "2025-26" -> "25-26"."""
    first, second = label.split("-")
    return f"{first[2:]}-{second}"


def is_label(value: str) -> bool:
    if len(value) != 7 or value[4] != "-" or not value.replace("-", "").isdigit():
        return False
    start = int(value[:4])
    return value == f"{start}-{(start + 1) % 100:02d}"


def previous_label(label: str) -> str:
    start = int(label[:4]) - 1
    return f"{start}-{(start + 1) % 100:02d}"


# ------------------------------------------------------------------- gates
def month_lock(db: Session, day: date) -> PeriodLock | None:
    return db.scalar(select(PeriodLock).where(
        PeriodLock.scope == UNIT, PeriodLock.year == day.year,
        PeriodLock.month == day.month, PeriodLock.active.is_(True)))


def active_close(db: Session, day: date) -> FinancialYearClose | None:
    return db.scalar(select(FinancialYearClose).where(
        FinancialYearClose.financial_year == fy_label(day),
        FinancialYearClose.active.is_(True)))


def refuse_if_closed(db: Session, day: date, action: str) -> None:
    """Raise `PeriodClosed` when a document dated `day` may not be written.

    The month is named first because it is the narrower gate and the one a
    clerk can usually get unlocked; the year close is named with the year so
    the reason for the refusal is never a mystery.
    """
    lock = month_lock(db, day)
    if lock is not None:
        raise PeriodClosed(
            f"The accounting month {day:%B %Y} is locked, so {action} cannot be "
            f"recorded in it. Unlock the month first.")
    close = active_close(db, day)
    if close is not None:
        raise PeriodClosed(
            f"Financial year {close.financial_year} is closed, so {action} cannot "
            f"be recorded in it. The Administrator can reopen the year with a reason.")


# ------------------------------------------------------------------- close
def close_year(db: Session, label: str, reason: str, actor_id: int) -> FinancialYearClose:
    if not is_label(label):
        raise ValueError("The financial year must look like 2025-26")
    _, last = label_bounds(label)
    if last >= date.today():
        raise ValueError("Only a financial year that has ended can be closed; "
                         "lock the current month instead")
    reason = reason.strip()
    if len(reason) < 5:
        raise ValueError("A reason of at least 5 characters is required")

    row = db.scalar(select(FinancialYearClose)
                    .where(FinancialYearClose.financial_year == label)
                    .with_for_update())
    now = datetime.now(timezone.utc)
    if row and row.active:
        raise ValueError(f"Financial year {label} is already closed")
    if row:
        row.active = True
        row.reason = reason
        row.closed_by = actor_id
        row.closed_at = now
        row.reopened_by = row.reopened_at = row.reopen_reason = None
    else:
        row = FinancialYearClose(financial_year=label, active=True, reason=reason,
                                 closed_by=actor_id, closed_at=now)
        db.add(row)
    db.flush()
    return row


def reopen_year(db: Session, label: str, reason: str, actor_id: int) -> FinancialYearClose:
    reason = reason.strip()
    if len(reason) < 5:
        raise ValueError("A reason of at least 5 characters is required")
    row = db.scalar(select(FinancialYearClose)
                    .where(FinancialYearClose.financial_year == label)
                    .with_for_update())
    if row is None or not row.active:
        raise ValueError(f"Financial year {label} is not closed")
    row.active = False
    row.reopened_by = actor_id
    row.reopened_at = datetime.now(timezone.utc)
    row.reopen_reason = reason
    db.flush()
    return row


def _earliest_document(db: Session) -> date | None:
    """The first accounting document the books hold, used to offer years to close.

    Money, sales, purchases and expenses all count: a year with only a purchase
    order or a goods receipt in it is still a year the books touch.
    """
    queries = (
        select(func.min(Invoice.invoice_date)),
        select(func.min(CreditNote.note_date)),
        select(func.min(DebitNote.note_date)),
        select(func.min(Payment.paid_on)),
        select(func.min(Expense.entry_date)),
        select(func.min(func.date(PurchaseOrder.created_at))),
        select(func.min(func.date(GoodsReceipt.received_at))),
    )
    found = [db.scalar(q) for q in queries]
    return min((d for d in found if d is not None), default=None)


def close_out(row: FinancialYearClose | None, users: dict) -> dict:
    def who(user_id):
        user = users.get(user_id) if user_id else None
        return user.username if user else user_id

    if row is None:
        return {"active": False, "closed_by": None, "closed_at": None,
                "reason": None, "reopened_by": None, "reopened_at": None,
                "reopen_reason": None}
    return {"active": row.active, "reason": row.reason,
            "closed_by": who(row.closed_by), "closed_at": row.closed_at,
            "reopened_by": who(row.reopened_by), "reopened_at": row.reopened_at,
            "reopen_reason": row.reopen_reason}


def year_rows(db: Session, users: dict) -> dict:
    """Every completed year the books touch, with its close state.

    The span starts at the earliest document and ends at the financial year
    before the one in progress; a year is never offered for closing while it is
    still trading. Years recorded in `financial_year_closes` are always shown,
    even if they predate the remaining documents.
    """
    today = date.today()
    current = fy_label(today)
    last_complete = previous_label(current)
    earliest = _earliest_document(db)
    labels: list[str] = []
    if earliest is not None:
        label = fy_label(earliest)
        while label <= last_complete:
            labels.append(label)
            start = int(label[:4]) + 1
            label = f"{start}-{(start + 1) % 100:02d}"
    rows = {r.financial_year: r for r in db.scalars(select(FinancialYearClose)).all()}
    labels = sorted(set(labels) | set(rows))
    out = []
    for label in labels:
        first, last = label_bounds(label)
        out.append({"financial_year": label, "first": first, "last": last,
                    **close_out(rows.get(label), users)})
    return {"current": current, "today": today, "years": out}
