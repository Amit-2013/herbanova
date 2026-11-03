"""Bank statements and reconciliation (GAP-A09).

A statement holds what the bank printed: a period, an opening balance, a closing
balance and the lines. The book side is not copied here - it is read from the
documents and the posted vouchers through `balance_sheet.account_balance`, so a
reconciliation can never show a book figure the books do not hold.

A line matches one receipt, one payment or one posted voucher line touching the
same bank head. The amounts must agree exactly and in the same direction, and a
book entry dated after the statement period cannot be matched into it. Each
book entry matches at most one statement line, enforced by unique partial
indexes as well as by this code.

The proof is the standard one: the book closing less the book items the bank has
not shown equals the statement closing less the statement items the books do not
hold. Any difference is reported, and an opening difference between the printed
balance and the books is named rather than plugged.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.accounts import (PAYMENT, RECEIPT, BankStatement, BankStatementLine,
                               LedgerAccount, Payment, Voucher, VoucherLine)
from . import balance_sheet, journal

ZERO = Decimal("0.00")
money = journal.money


class RecError(Exception):
    """A reconciliation write that cannot be accepted as entered."""


# ----------------------------------------------------------------- statements
def _bank_account(db: Session, account_id: int) -> LedgerAccount:
    account = db.get(LedgerAccount, account_id)
    if account is None:
        raise RecError("Ledger account not found")
    if account.role != "bank" or account.type != "asset":
        raise RecError("A bank statement belongs to an asset head whose role is Bank")
    if not account.active:
        raise RecError(f"The account {account.name} is inactive")
    return account


def _statement(db: Session, statement_id: int,
               lock: bool = False) -> BankStatement:
    row = db.get(BankStatement, statement_id, with_for_update=lock)
    if row is None:
        raise RecError("Bank statement not found")
    return row


def _day(day: date) -> None:
    if day > date.today():
        raise RecError("A bank statement cannot be dated in the future")


def _party_names(db: Session) -> dict[tuple[str, int], str]:
    from ..models.core import Distributor
    from ..models.suppliers import Supplier
    out = {("distributor", d.id): d.name
           for d in db.scalars(select(Distributor)).all()}
    out.update({("supplier", s.id): s.name for s in db.scalars(select(Supplier)).all()})
    return out


def statement_rows(db: Session) -> list[dict]:
    names = {a.id: a for a in db.scalars(select(LedgerAccount)).all()}
    out = []
    for st in db.scalars(select(BankStatement)
                         .order_by(BankStatement.period_to.desc(),
                                   BankStatement.id.desc())).all():
        account = names.get(st.ledger_account_id)
        matched = sum(1 for line in st.lines if _line_matched(line))
        out.append({
            "id": st.id, "account_id": st.ledger_account_id,
            "account": account.name if account else None,
            "period_from": st.period_from, "period_to": st.period_to,
            "opening_balance": money(st.opening_balance),
            "closing_balance": money(st.closing_balance),
            "lines": len(st.lines), "matched": matched,
            "note": st.note,
        })
    return out


def _line_matched(line: BankStatementLine) -> bool:
    return (line.matched_payment_id is not None
            or line.matched_voucher_line_id is not None)


def _line_out(line: BankStatementLine) -> dict:
    return {"id": line.id, "date": line.line_date,
            "description": line.description, "reference": line.reference,
            "amount": money(line.amount), "matched": _line_matched(line),
            "matched_payment_id": line.matched_payment_id,
            "matched_voucher_line_id": line.matched_voucher_line_id,
            "matched_at": line.matched_at}


def statement_detail(db: Session, statement_id: int) -> dict:
    st = _statement(db, statement_id)
    account = db.get(LedgerAccount, st.ledger_account_id)
    return {
        "id": st.id, "account_id": st.ledger_account_id,
        "account": account.name if account else None,
        "period_from": st.period_from, "period_to": st.period_to,
        "opening_balance": money(st.opening_balance),
        "closing_balance": money(st.closing_balance), "note": st.note,
        "lines": [_line_out(line) for line in st.lines],
    }


def create_statement(db: Session, account_id: int, period_from: date,
                     period_to: date, opening_balance, closing_balance,
                     note: str | None, actor_id: int) -> BankStatement:
    account = _bank_account(db, account_id)
    if period_from > period_to:
        raise RecError("The statement start is after its end")
    _day(period_to)
    if db.scalar(select(BankStatement).where(
            BankStatement.ledger_account_id == account.id,
            BankStatement.period_from <= period_to,
            BankStatement.period_to >= period_from)):
        raise RecError("A statement already covers part of this period for this "
                       "account; correct or delete it before adding another")
    row = BankStatement(ledger_account_id=account.id, period_from=period_from,
                        period_to=period_to,
                        opening_balance=money(opening_balance),
                        closing_balance=money(closing_balance),
                        note=(note or "").strip() or None, created_by=actor_id)
    db.add(row)
    db.flush()
    return row


def update_statement(db: Session, statement_id: int, opening_balance=None,
                     closing_balance=None, note: str | None = None) -> BankStatement:
    """Correct the printed balances or the note; the period stays fixed.

    The period is what every line and match is judged against, so changing it
    after lines exist is a new statement, not an edit.
    """
    st = _statement(db, statement_id, lock=True)
    if opening_balance is not None:
        st.opening_balance = money(opening_balance)
    if closing_balance is not None:
        st.closing_balance = money(closing_balance)
    if note is not None:
        st.note = note.strip() or None
    db.flush()
    return st


def delete_statement(db: Session, statement_id: int) -> None:
    st = _statement(db, statement_id, lock=True)
    if any(_line_matched(line) for line in st.lines):
        raise RecError("Unmatch every line before deleting the statement; the "
                       "match trail is evidence of what was agreed")
    db.delete(st)
    db.flush()


# ---------------------------------------------------------------------- lines
def _line_values(lines) -> list[dict]:
    if not isinstance(lines, list) or not lines:
        raise RecError("Add at least one statement line")
    out = []
    for index, line in enumerate(lines, start=1):
        day = line.get("date")
        if not isinstance(day, date):
            raise RecError(f"Line {index}: the date is required")
        description = (line.get("description") or "").strip()
        if not description:
            raise RecError(f"Line {index}: a description is required")
        amount = money(line.get("amount"))
        if amount == ZERO:
            raise RecError(f"Line {index}: the amount cannot be zero")
        out.append({"line_date": day, "description": description[:200],
                    "reference": (line.get("reference") or "").strip()[:60] or None,
                    "amount": amount})
    return out


def add_lines(db: Session, statement_id: int, lines) -> dict:
    st = _statement(db, statement_id, lock=True)
    values = _line_values(lines)
    outside = [f"{line['line_date']} {line['description']}"
               for line in values
               if not (st.period_from <= line["line_date"] <= st.period_to)]
    if outside:
        raise RecError("These lines fall outside the statement period "
                       f"{st.period_from} to {st.period_to}: " + "; ".join(outside))
    st.lines.extend(BankStatementLine(**line) for line in values)
    db.flush()
    return statement_detail(db, statement_id)


def delete_line(db: Session, line_id: int) -> None:
    line = db.get(BankStatementLine, line_id, with_for_update=True)
    if line is None:
        raise RecError("Statement line not found")
    if _line_matched(line):
        raise RecError("Unmatch the line before deleting it")
    db.delete(line)
    db.flush()


# -------------------------------------------------------------------- matching
def _matched_payment_ids(db: Session) -> set[int]:
    return {row for row in db.scalars(
        select(BankStatementLine.matched_payment_id)
        .where(BankStatementLine.matched_payment_id.is_not(None))).all()}


def _matched_voucher_line_ids(db: Session) -> set[int]:
    return {row for row in db.scalars(
        select(BankStatementLine.matched_voucher_line_id)
        .where(BankStatementLine.matched_voucher_line_id.is_not(None))).all()}


def _bank_heads(db: Session) -> list[LedgerAccount]:
    return list(db.scalars(select(LedgerAccount)
                           .where(LedgerAccount.role == "bank",
                                  LedgerAccount.active.is_(True))).all())


def _book_items(db: Session, account: LedgerAccount, until: date,
                matched_payments: set[int] | None = None,
                matched_lines: set[int] | None = None) -> dict:
    """Unmatched book movements through `until`, split by direction."""
    matched_payments = matched_payments if matched_payments is not None else _matched_payment_ids(db)
    matched_lines = matched_lines if matched_lines is not None else _matched_voucher_line_ids(db)
    names = _party_names(db)
    receipts, payments = [], []
    if len(_bank_heads(db)) == 1:
        for pay in db.scalars(select(Payment)
                              .where(Payment.mode != "cash",
                                     Payment.paid_on <= until,
                                     Payment.id.not_in(matched_payments))
                              .order_by(Payment.paid_on, Payment.id)).all():
            party = (names.get(("distributor", pay.distributor_id))
                     if pay.distributor_id else
                     names.get(("supplier", pay.supplier_id)))
            item = {"kind": pay.kind, "id": pay.id, "date": pay.paid_on,
                    "amount": money(pay.amount), "mode": pay.mode,
                    "reference": pay.reference, "party": party}
            (receipts if pay.kind == RECEIPT else payments).append(item)
    vouchers = []
    rows = db.execute(
        select(VoucherLine, Voucher)
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .where(Voucher.status == "posted", Voucher.voucher_date <= until,
               VoucherLine.ledger_account_id == account.id)
        .order_by(Voucher.voucher_date, Voucher.id, VoucherLine.id)).all()
    for line, voucher in rows:
        if line.id in matched_lines:
            continue
        signed = money(Decimal(line.debit or 0) - Decimal(line.credit or 0))
        if signed == ZERO:
            continue
        vouchers.append({"kind": "voucher_line", "id": line.id,
                         "date": voucher.voucher_date, "amount": signed,
                         "voucher": voucher.number, "narration": voucher.narration})
    return {"receipts": receipts, "payments": payments, "vouchers": vouchers}


def match_line(db: Session, line_id: int, kind: str, ref_id: int,
               actor_id: int) -> dict:
    """Match one statement line to one book entry, direction and amount exact."""
    line = db.get(BankStatementLine, line_id, with_for_update=True)
    if line is None:
        raise RecError("Statement line not found")
    if _line_matched(line):
        raise RecError("This line is already matched; unmatch it first")
    st = _statement(db, line.statement_id)
    account = _bank_account(db, st.ledger_account_id)
    amount = money(line.amount)

    if kind == "payment":
        pay = db.get(Payment, ref_id)
        if pay is None:
            raise RecError("Receipt or payment not found")
        if pay.mode == "cash":
            raise RecError("A cash entry never appears on a bank statement")
        heads = _bank_heads(db)
        if len(heads) != 1:
            raise RecError(
                "There is more than one bank head, so a receipt or payment does "
                "not name the bank it moved through. Match a voucher line "
                "instead, or keep a single bank head.")
        if heads[0].id != account.id:
            raise RecError("This receipt or payment does not belong to this account")
        if pay.paid_on > st.period_to:
            raise RecError(
                f"That entry is dated {pay.paid_on}, after the statement ends on "
                f"{st.period_to}; it cannot appear on this statement")
        if pay.id in _matched_payment_ids(db):
            raise RecError("That entry is already matched to a statement line")
        signed = money(pay.amount) if pay.kind == RECEIPT else money(-pay.amount)
        if signed != amount:
            raise RecError(
                f"The amounts do not agree: statement {amount:.2f}, book "
                f"{signed:.2f}")
        line.matched_payment_id = pay.id
    elif kind == "voucher_line":
        entry = db.get(VoucherLine, ref_id)
        if entry is None:
            raise RecError("Voucher line not found")
        voucher = db.get(Voucher, entry.voucher_id)
        if voucher is None or voucher.status != "posted":
            raise RecError("Only a posted voucher can be matched; a draft is not "
                           "in the books and a reversed one has a mirror entry")
        if entry.ledger_account_id != account.id:
            raise RecError("That voucher line does not touch this bank head")
        if voucher.voucher_date > st.period_to:
            raise RecError(
                f"That voucher is dated {voucher.voucher_date}, after the "
                f"statement ends on {st.period_to}")
        if entry.id in _matched_voucher_line_ids(db):
            raise RecError("That voucher line is already matched to a statement line")
        signed = money(Decimal(entry.debit or 0) - Decimal(entry.credit or 0))
        if signed != amount:
            raise RecError(
                f"The amounts do not agree: statement {amount:.2f}, book "
                f"{signed:.2f}")
        line.matched_voucher_line_id = entry.id
    else:
        raise RecError("Match a payment or a voucher line")

    from datetime import datetime, timezone
    line.matched_at = datetime.now(timezone.utc)
    line.matched_by = actor_id
    db.flush()
    return _line_out(line)


def unmatch_line(db: Session, line_id: int) -> dict:
    line = db.get(BankStatementLine, line_id, with_for_update=True)
    if line is None:
        raise RecError("Statement line not found")
    if not _line_matched(line):
        raise RecError("This line is not matched")
    line.matched_payment_id = line.matched_voucher_line_id = None
    line.matched_at = line.matched_by = None
    db.flush()
    return _line_out(line)


def candidates(db: Session, statement_id: int) -> dict:
    st = _statement(db, statement_id)
    account = _bank_account(db, st.ledger_account_id)
    items = _book_items(db, account, st.period_to)
    warnings = []
    if len(_bank_heads(db)) != 1:
        warnings.append(
            "More than one bank head exists, so receipts and payments are not "
            "offered: the documents do not say which bank the money moved through.")
    return {"statement_id": statement_id, **items, "warnings": warnings}


# --------------------------------------------------------------- reconciliation
def reconciliation(db: Session, statement_id: int) -> dict:
    st = _statement(db, statement_id)
    account = _bank_account(db, st.ledger_account_id)
    lines = st.lines

    matched_payments = _matched_payment_ids(db)
    matched_lines = _matched_voucher_line_ids(db)
    items = _book_items(db, account, st.period_to, matched_payments, matched_lines)

    unmatched_lines = [_line_out(line) for line in lines if not _line_matched(line)]
    matched_count = len(lines) - len(unmatched_lines)

    matched_debit = matched_credit = ZERO
    statement_matched_net = ZERO
    for line in lines:
        if not _line_matched(line):
            continue
        amount = money(line.amount)
        statement_matched_net += amount
        if amount > 0:
            matched_debit += amount
        else:
            matched_credit += -amount

    def net(rows) -> Decimal:
        return money(sum((row["amount"] for row in rows), ZERO))

    unmatched_book = [*items["receipts"], *items["payments"], *items["vouchers"]]
    unmatched_book_net = net(unmatched_book)
    unmatched_statement_net = net(unmatched_lines)

    book_open = balance_sheet.account_balance(
        db, account.id, st.period_from - timedelta(days=1))
    book_close = balance_sheet.account_balance(db, account.id, st.period_to)

    adjusted_book = money(book_close["balance"] - unmatched_book_net)
    adjusted_statement = money(money(st.closing_balance) - unmatched_statement_net)
    difference = money(adjusted_book - adjusted_statement)
    opening_difference = money(money(st.opening_balance) - book_open["balance"])
    lines_check = money(money(st.opening_balance)
                        + sum((money(line.amount) for line in lines), ZERO)
                        - money(st.closing_balance))

    warnings = []
    if not lines:
        warnings.append("No statement lines are captured, so only the printed "
                        "balances are compared with the books.")
    if len(_bank_heads(db)) != 1:
        warnings.append(
            "More than one bank head exists, so receipts and payments cannot be "
            "matched; only voucher lines that name this bank are offered.")
    if lines_check != ZERO:
        warnings.append(
            f"The statement's own lines do not reach its printed closing "
            f"balance: the difference is {lines_check:.2f}. Correct the lines "
            f"or the printed closing before relying on this reconciliation.")
    if difference != ZERO and money(difference + opening_difference) == ZERO:
        warnings.append(
            f"The adjusted balances differ by {difference:.2f}, which is exactly "
            f"the opening difference: the printed opening is "
            f"{opening_difference:.2f} away from the books at "
            f"{st.period_from - timedelta(days=1)}.")
    elif difference != ZERO:
        warnings.append(
            f"The adjusted balances differ by {difference:.2f} and the opening "
            f"difference ({opening_difference:.2f}) does not explain it. An "
            f"unrecorded book entry or a statement line entered twice is likely.")

    return {
        "statement": {"id": st.id, "account": account.name,
                      "period_from": st.period_from, "period_to": st.period_to,
                      "opening_balance": money(st.opening_balance),
                      "closing_balance": money(st.closing_balance)},
        "lines": [_line_out(line) for line in lines],
        "book": {"opening": book_open["balance"],
                 "closing": book_close["balance"]},
        "matched": {"count": matched_count, "debit": money(matched_debit),
                    "credit": money(matched_credit),
                    "net": money(statement_matched_net)},
        "unmatched_book": items,
        "unmatched_statement": unmatched_lines,
        "proof": {
            "book_closing": book_close["balance"],
            "unmatched_book_net": unmatched_book_net,
            "adjusted_book": adjusted_book,
            "statement_closing": money(st.closing_balance),
            "unmatched_statement_net": unmatched_statement_net,
            "adjusted_statement": adjusted_statement,
            "opening_difference": opening_difference,
            "lines_check": lines_check,
            "difference": difference,
            "balanced": difference == ZERO,
        },
        "warnings": warnings,
    }
