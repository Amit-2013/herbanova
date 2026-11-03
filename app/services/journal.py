"""The stored voucher ledger: heads, opening balances, vouchers and day book (A08, A10).

The document-derived trial balance in `app/services/ledger.py` stays the source
for what invoices, notes, receipts, payments and goods receipts say. This module
adds the one thing documents cannot express: a person's own double-entry
posting, with a draft state, a posted state and a reversal trail. The balance
sheet merges both by ledger head.

Nothing here guesses a figure. A draft may be unbalanced while it is typed;
posting refuses it until debit equals credit. An opening trial balance may be
saved unbalanced, and the balance sheet reports the difference instead of
plugging it.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models.accounts import (LEDGER_TYPES, VOUCHER_TYPES, LedgerAccount,
                               OpeningBalance, Voucher, VoucherLine)
from . import periods

ZERO = Decimal("0.00")


class LedgerError(Exception):
    """A ledger write that cannot be accepted as entered.

    `status` lets the router answer 423 for a period gate and 409 for a state
    conflict, matching the rest of Accounts.
    """

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def money(value) -> Decimal:
    return Decimal(value if value is not None else 0).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


def _day(day: date, what: str = "voucher date") -> None:
    if day > date.today():
        raise LedgerError(f"The {what} cannot be in the future")
    if day < date.today() - timedelta(days=3650):
        raise LedgerError(f"The {what} is more than ten years ago")


# ------------------------------------------------------------------ heads
def account_rows(db: Session, include_inactive: bool = False) -> list[dict]:
    stmt = select(LedgerAccount).order_by(LedgerAccount.code)
    if not include_inactive:
        stmt = stmt.where(LedgerAccount.active.is_(True))
    return [{"id": a.id, "code": a.code, "name": a.name, "type": a.type,
             "role": a.role, "active": a.active, "note": a.note,
             "seeded": a.role is not None}
            for a in db.scalars(stmt).all()]


def active_accounts(db: Session) -> list[LedgerAccount]:
    return list(db.scalars(select(LedgerAccount).where(
        LedgerAccount.active.is_(True)).order_by(LedgerAccount.code)).all())


def create_account(db: Session, code: str, name: str, kind: str,
                   note: str | None, actor_id: int) -> LedgerAccount:
    code, name = code.strip(), name.strip()
    if kind not in LEDGER_TYPES:
        raise LedgerError(f"The account type must be one of {', '.join(LEDGER_TYPES)}")
    if not code or not name:
        raise LedgerError("An account needs a code and a name")
    if db.scalar(select(LedgerAccount).where(LedgerAccount.code == code)):
        raise LedgerError(f"The code {code} is already used")
    if db.scalar(select(LedgerAccount).where(LedgerAccount.name == name)):
        raise LedgerError(f"The name {name} is already used")
    row = LedgerAccount(code=code, name=name, type=kind, role=None, active=True,
                        note=note.strip() if note and note.strip() else None,
                        created_by=actor_id)
    db.add(row)
    db.flush()
    return row


def update_account(db: Session, account_id: int, name: str | None = None,
                   note: str | None = None, active: bool | None = None) -> LedgerAccount:
    row = db.get(LedgerAccount, account_id)
    if row is None:
        raise LedgerError("Ledger account not found")
    if name is not None:
        name = name.strip()
        if not name:
            raise LedgerError("An account needs a name")
        clash = db.scalar(select(LedgerAccount).where(
            LedgerAccount.name == name, LedgerAccount.id != row.id))
        if clash is not None:
            raise LedgerError(f"The name {name} is already used")
        row.name = name
    if note is not None:
        row.note = note.strip() or None
    if active is not None:
        row.active = active
    db.flush()
    return row


# --------------------------------------------------------- opening balances
def opening_rows(db: Session, financial_year: str) -> dict:
    if not periods.is_label(financial_year):
        raise LedgerError("The financial year must look like 2025-26")
    rows = db.scalars(select(OpeningBalance).where(
        OpeningBalance.financial_year == financial_year)).all()
    by_account = {r.ledger_account_id: r for r in rows}
    out, debit_total, credit_total = [], ZERO, ZERO
    for account in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code)).all():
        row = by_account.get(account.id)
        debit = money(row.debit) if row else ZERO
        credit = money(row.credit) if row else ZERO
        debit_total += debit
        credit_total += credit
        out.append({"account_id": account.id, "code": account.code,
                    "name": account.name, "type": account.type,
                    "role": account.role, "active": account.active,
                    "debit": debit, "credit": credit,
                    "note": row.note if row else None,
                    "updated_at": row.updated_at if row else None})
    difference = money(debit_total - credit_total)
    return {"financial_year": financial_year, "rows": out,
            "debit_total": money(debit_total), "credit_total": money(credit_total),
            "difference": difference, "balanced": difference == ZERO}


def save_opening(db: Session, account_id: int, financial_year: str,
                 debit, credit, note: str | None, actor_id: int) -> dict:
    """Upsert one head's opening balance. Zero on both sides clears the row.

    A closed year refuses the write: the opening position is part of what the
    close made final. A month lock is not applied, because an opening balance is
    a statement about the year, not a document dated inside a month.
    """
    if not periods.is_label(financial_year):
        raise LedgerError("The financial year must look like 2025-26")
    account = db.get(LedgerAccount, account_id)
    if account is None:
        raise LedgerError("Ledger account not found")
    debit, credit = money(debit), money(credit)
    if debit < 0 or credit < 0:
        raise LedgerError("Opening debit and credit cannot be negative")
    if debit > 0 and credit > 0:
        raise LedgerError("Enter either a debit or a credit for an opening balance")
    start, _ = periods.label_bounds(financial_year)
    if periods.active_close(db, start) is not None:
        raise LedgerError(
            f"Financial year {financial_year} is closed; the Administrator can "
            "reopen it before its opening balances change", 423)

    row = db.scalar(select(OpeningBalance).where(
        OpeningBalance.ledger_account_id == account_id,
        OpeningBalance.financial_year == financial_year).with_for_update())
    if debit == 0 and credit == 0:
        if row is not None:
            db.delete(row)
            db.flush()
        return {"cleared": True, "account_id": account_id,
                "financial_year": financial_year}
    now = datetime.now(timezone.utc)
    if row is None:
        row = OpeningBalance(ledger_account_id=account_id,
                             financial_year=financial_year, created_by=actor_id,
                             created_at=now)
        db.add(row)
    row.debit, row.credit = debit, credit
    row.note = note.strip() if note and note.strip() else None
    row.updated_by, row.updated_at = actor_id, now
    db.flush()
    return {"cleared": False, "account_id": account_id,
            "financial_year": financial_year, "debit": debit, "credit": credit,
            "note": row.note}


# ------------------------------------------------------------------ vouchers
def _line_values(lines, db: Session) -> list[dict]:
    """Validate and normalise lines. Account existence is checked here."""
    if not isinstance(lines, list) or len(lines) < 2:
        raise LedgerError("A voucher needs at least two lines")
    accounts = {a.id: a for a in db.scalars(select(LedgerAccount)).all()}
    out = []
    for index, line in enumerate(lines, start=1):
        account = accounts.get(line.get("ledger_account_id"))
        if account is None:
            raise LedgerError(f"Line {index}: ledger account not found")
        if not account.active:
            raise LedgerError(f"Line {index}: account {account.name} is inactive")
        debit, credit = money(line.get("debit")), money(line.get("credit"))
        if debit < 0 or credit < 0:
            raise LedgerError(f"Line {index}: debit and credit cannot be negative")
        if (debit > 0) == (credit > 0):
            raise LedgerError(f"Line {index}: enter either a debit or a credit")
        out.append({"ledger_account_id": account.id, "debit": debit,
                    "credit": credit,
                    "narration": (line.get("narration") or "").strip() or None})
    return out


def _validate_balanced(lines: list[dict]) -> None:
    debit = sum((line["debit"] for line in lines), ZERO)
    credit = sum((line["credit"] for line in lines), ZERO)
    if money(debit) != money(credit):
        raise LedgerError(
            f"The voucher does not balance: debit {money(debit):.2f}, "
            f"credit {money(credit):.2f}")


def _write_lines(voucher: Voucher, values: list[dict]) -> None:
    voucher.lines[:] = [VoucherLine(**line) for line in values]


def create_voucher(db: Session, day: date, kind: str, narration: str | None,
                   lines, actor_id: int, post: bool = False) -> Voucher:
    _day(day)
    if kind not in VOUCHER_TYPES:
        raise LedgerError(f"The voucher type must be one of {', '.join(VOUCHER_TYPES)}")
    values = _line_values(lines, db)
    if post:
        _validate_balanced(values)
        try:
            periods.refuse_if_closed(db, day, "a voucher")
        except periods.PeriodClosed as exc:
            raise LedgerError(str(exc), 423) from exc
    row = Voucher(voucher_date=day, voucher_type=kind,
                  narration=(narration or "").strip() or None,
                  status="draft", created_by=actor_id)
    db.add(row)
    db.flush()
    _write_lines(row, values)
    if post:
        now = datetime.now(timezone.utc)
        row.status = "posted"
        row.posted_by, row.posted_at = actor_id, now
    db.flush()
    return row


def update_voucher(db: Session, voucher_id: int, day: date, kind: str,
                   narration: str | None, lines) -> Voucher:
    row = db.get(Voucher, voucher_id)
    if row is None:
        raise LedgerError("Voucher not found")
    if row.status != "draft":
        raise LedgerError("Only a draft voucher can be edited; a posted voucher "
                          "is reversed instead")
    _day(day)
    if kind not in VOUCHER_TYPES:
        raise LedgerError(f"The voucher type must be one of {', '.join(VOUCHER_TYPES)}")
    values = _line_values(lines, db)
    row.voucher_date = day
    row.voucher_type = kind
    row.narration = (narration or "").strip() or None
    _write_lines(row, values)
    db.flush()
    return row


def delete_voucher(db: Session, voucher_id: int) -> None:
    row = db.get(Voucher, voucher_id)
    if row is None:
        raise LedgerError("Voucher not found")
    if row.status != "draft":
        raise LedgerError("Only a draft voucher can be deleted")
    db.delete(row)
    db.flush()


def post_voucher(db: Session, voucher_id: int, actor_id: int) -> Voucher:
    row = db.get(Voucher, voucher_id, with_for_update=True)
    if row is None:
        raise LedgerError("Voucher not found")
    if row.status != "draft":
        raise LedgerError("This voucher is already posted or reversed")
    values = _line_values([{"ledger_account_id": line.ledger_account_id,
                            "debit": line.debit, "credit": line.credit,
                            "narration": line.narration} for line in row.lines], db)
    _validate_balanced(values)
    try:
        periods.refuse_if_closed(db, row.voucher_date, "a voucher")
    except periods.PeriodClosed as exc:
        raise LedgerError(str(exc), 423) from exc
    now = datetime.now(timezone.utc)
    row.status = "posted"
    row.posted_by, row.posted_at = actor_id, now
    db.flush()
    return row


def reverse_voucher(db: Session, voucher_id: int, reason: str,
                    actor_id: int) -> Voucher:
    """Write the mirror voucher, dated today, and mark the original reversed.

    Today's date is deliberate: the original may sit in a month that is already
    locked. If today is locked or closed the reversal is refused rather than
    back-dated.
    """
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise LedgerError("Give a reason of at least 5 characters")
    row = db.get(Voucher, voucher_id, with_for_update=True)
    if row is None:
        raise LedgerError("Voucher not found")
    if row.status == "draft":
        raise LedgerError("A draft is deleted, not reversed")
    if row.status == "reversed":
        raise LedgerError("This voucher is already reversed")
    today = date.today()
    try:
        periods.refuse_if_closed(db, today, "a reversal")
    except periods.PeriodClosed as exc:
        raise LedgerError(str(exc), 423) from exc
    mirror = Voucher(voucher_date=today, voucher_type=row.voucher_type,
                     narration=f"Reversal of {row.number}: {reason}",
                     status="draft", reversal_of_id=row.id, created_by=actor_id)
    db.add(mirror)
    db.flush()
    mirror.lines[:] = [VoucherLine(ledger_account_id=line.ledger_account_id,
                                   debit=line.credit, credit=line.debit,
                                   narration=f"Reversal of {row.number}")
                       for line in row.lines]
    now = datetime.now(timezone.utc)
    mirror.status = "posted"
    mirror.posted_by, mirror.posted_at = actor_id, now
    row.status = "reversed"
    row.reversal_reason = reason
    row.reversed_by, row.reversed_at = actor_id, now
    db.flush()
    return mirror


def voucher_rows(db: Session, date_from: date | None = None,
                 date_to: date | None = None, status: str | None = None) -> list[dict]:
    stmt = select(Voucher).order_by(Voucher.voucher_date, Voucher.id)
    if date_from is not None:
        stmt = stmt.where(Voucher.voucher_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Voucher.voucher_date <= date_to)
    if status is not None:
        stmt = stmt.where(Voucher.status == status)
    return [_voucher_out(v) for v in db.scalars(stmt).all()]


def _voucher_out(row: Voucher) -> dict:
    return {"id": row.id, "number": row.number, "date": row.voucher_date,
            "type": row.voucher_type, "narration": row.narration,
            "status": row.status, "reverse_of": row.reversal_of_id,
            "reversal_reason": row.reversal_reason,
            "debit": money(row.debit_total), "credit": money(row.credit_total),
            "lines": [{"id": line.id, "account_id": line.ledger_account_id,
                       "account": line.account.name if line.account else None,
                       "code": line.account.code if line.account else None,
                       "narration": line.narration,
                       "debit": money(line.debit), "credit": money(line.credit)}
                      for line in row.lines]}


def voucher_detail(db: Session, voucher_id: int) -> dict:
    row = db.get(Voucher, voucher_id)
    if row is None:
        raise LedgerError("Voucher not found")
    return _voucher_out(row)


def day_book(db: Session, date_from: date, date_to: date) -> dict:
    """Posted and reversed vouchers only; drafts are not in the books yet."""
    if date_from > date_to:
        raise LedgerError("The start date is after the end date")
    rows = [v for v in voucher_rows(db, date_from, date_to)
            if v["status"] in ("posted", "reversed")]
    debit = sum((v["debit"] for v in rows), ZERO)
    credit = sum((v["credit"] for v in rows), ZERO)
    return {"date_from": date_from, "date_to": date_to, "rows": rows,
            "count": len(rows), "debit_total": money(debit),
            "credit_total": money(credit),
            "balanced": money(debit) == money(credit)}


def posted_movements(db: Session, as_of: date,
                     date_from: date | None = None) -> dict[int, dict]:
    """Debit/credit totals per account from every non-draft voucher up to `as_of`.

    A reversed voucher stays counted and its mirror voucher cancels it, so the
    pair always nets to zero and the trail remains in the day book. `date_from`
    restricts the window when a later year's opening position is already
    captured, so movements before it are not counted twice.
    """
    out: dict[int, dict] = {}
    stmt = (select(VoucherLine.ledger_account_id, VoucherLine.debit, VoucherLine.credit)
            .join(Voucher, Voucher.id == VoucherLine.voucher_id)
            .where(Voucher.status != "draft", Voucher.voucher_date <= as_of))
    if date_from is not None:
        stmt = stmt.where(Voucher.voucher_date >= date_from)
    rows = db.execute(stmt).all()
    for account_id, debit, credit in rows:
        row = out.setdefault(account_id, {"debit": ZERO, "credit": ZERO})
        row["debit"] += money(debit)
        row["credit"] += money(credit)
    return out


def delete_opening_rows(db: Session, financial_year: str) -> None:
    """Used by tests and by a reset; not exposed as an API action."""
    db.execute(delete(OpeningBalance).where(
        OpeningBalance.financial_year == financial_year))
    db.flush()
