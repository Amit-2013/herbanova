"""The stored ledger and bank reconciliation (A08, A09, A10).

Reading needs `accounts:read`; heads, openings, vouchers and statement matching
need `accounts:write`. Errors keep the rest of Accounts' meaning: a state
conflict is 409, a locked month or a closed year is 423.

Money leaves as a two-decimal string, never a JSON float.
"""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require
from ..models.accounts import LEDGER_TYPES, VOUCHER_STATUSES, VOUCHER_TYPES
from ..services import balance_sheet, bank_rec, journal, periods
from ..services.audit import audit

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _json(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _fail(db: Session, exc: Exception, status: int = 409):
    db.rollback()
    raise HTTPException(status, str(exc))


def _ledger(db: Session, exc: journal.LedgerError):
    _fail(db, exc, exc.status)


# ------------------------------------------------------------------- heads
class AccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    name: str = Field(min_length=1, max_length=80)
    type: str
    note: str | None = Field(None, max_length=300)


class AccountPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    note: str | None = Field(None, max_length=300)
    active: bool | None = None


@router.get("/ledger-accounts")
def list_ledger_accounts(include_inactive: bool = False,
                         db: Session = Depends(get_db),
                         _=Depends(require("accounts:read"))):
    return _json(journal.account_rows(db, include_inactive))


@router.post("/ledger-accounts", status_code=201)
def create_ledger_account(body: AccountIn, db: Session = Depends(get_db),
                          user=Depends(require("accounts:write"))):
    if body.type not in LEDGER_TYPES:
        raise HTTPException(422, f"The account type must be one of "
                                 f"{', '.join(LEDGER_TYPES)}")
    try:
        row = journal.create_account(db, body.code, body.name, body.type,
                                     body.note, user.id)
    except journal.LedgerError as exc:
        _ledger(db, exc)
    audit(db, user.id, "accounts.ledger_account.create",
          f"ledger_account:{row.id}",
          {"code": row.code, "name": row.name, "type": row.type})
    db.commit()
    return _json({"id": row.id, "code": row.code, "name": row.name,
                  "type": row.type, "role": row.role, "active": row.active,
                  "note": row.note, "seeded": False})


@router.patch("/ledger-accounts/{account_id}")
def update_ledger_account(account_id: int, body: AccountPatch,
                          db: Session = Depends(get_db),
                          user=Depends(require("accounts:write"))):
    try:
        row = journal.update_account(db, account_id, body.name, body.note,
                                     body.active)
    except journal.LedgerError as exc:
        _ledger(db, exc)
    audit(db, user.id, "accounts.ledger_account.update", f"ledger_account:{row.id}",
          {"name": row.name, "active": row.active})
    db.commit()
    return _json({"id": row.id, "code": row.code, "name": row.name,
                  "type": row.type, "role": row.role, "active": row.active,
                  "note": row.note, "seeded": row.role is not None})


# ---------------------------------------------------------- opening balances
class OpeningIn(BaseModel):
    account_id: int
    financial_year: str
    debit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                           decimal_places=2)
    credit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                            decimal_places=2)
    note: str | None = Field(None, max_length=300)


@router.get("/opening-balances")
def get_opening_balances(financial_year: str | None = None,
                         db: Session = Depends(get_db),
                         _=Depends(require("accounts:read"))):
    label = financial_year or periods.fy_label(date.today())
    try:
        return _json(journal.opening_rows(db, label))
    except journal.LedgerError as exc:
        _ledger(db, exc)


@router.put("/opening-balances")
def put_opening_balance(body: OpeningIn, db: Session = Depends(get_db),
                        user=Depends(require("accounts:write"))):
    try:
        result = journal.save_opening(db, body.account_id, body.financial_year,
                                      body.debit, body.credit, body.note, user.id)
    except journal.LedgerError as exc:
        _ledger(db, exc)
    audit(db, user.id, "accounts.opening_balance.save",
          f"opening_balance:{body.account_id}:{body.financial_year}",
          {"financial_year": body.financial_year, "debit": str(body.debit),
           "credit": str(body.credit), "cleared": result["cleared"]})
    db.commit()
    return _json(journal.opening_rows(db, body.financial_year))


# ------------------------------------------------------------------ vouchers
class LineIn(BaseModel):
    ledger_account_id: int
    debit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                           decimal_places=2)
    credit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14,
                            decimal_places=2)
    narration: str | None = Field(None, max_length=300)


class VoucherIn(BaseModel):
    date: date
    type: str
    narration: str | None = Field(None, max_length=300)
    lines: list[LineIn]
    post: bool = False


class VoucherPatch(BaseModel):
    date: date
    type: str
    narration: str | None = Field(None, max_length=300)
    lines: list[LineIn]


class ReverseIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


def _lines(body_lines) -> list[dict]:
    return [line.model_dump() for line in body_lines]


@router.get("/vouchers")
def list_vouchers(date_from: date | None = None, date_to: date | None = None,
                  status: str | None = None, db: Session = Depends(get_db),
                  _=Depends(require("accounts:read"))):
    if status is not None and status not in VOUCHER_STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(VOUCHER_STATUSES)}")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date is after the end date")
    return _json(journal.voucher_rows(db, date_from, date_to, status))


@router.post("/vouchers", status_code=201)
def create_voucher(body: VoucherIn, db: Session = Depends(get_db),
                   user=Depends(require("accounts:write"))):
    if body.type not in VOUCHER_TYPES:
        raise HTTPException(422, f"The voucher type must be one of "
                                 f"{', '.join(VOUCHER_TYPES)}")
    try:
        row = journal.create_voucher(db, body.date, body.type, body.narration,
                                     _lines(body.lines), user.id, body.post)
    except journal.LedgerError as exc:
        _ledger(db, exc)
    audit(db, user.id, "accounts.voucher.create", f"voucher:{row.id}",
          {"number": row.number, "date": str(row.voucher_date),
           "type": row.voucher_type, "posted": body.post,
           "debit": str(row.debit_total)})
    db.commit()
    return _json(journal.voucher_detail(db, row.id))


@router.get("/vouchers/{voucher_id}")
def get_voucher(voucher_id: int, db: Session = Depends(get_db),
                _=Depends(require("accounts:read"))):
    try:
        return _json(journal.voucher_detail(db, voucher_id))
    except journal.LedgerError as exc:
        _ledger(db, exc)


@router.put("/vouchers/{voucher_id}")
def edit_voucher(voucher_id: int, body: VoucherPatch,
                 db: Session = Depends(get_db),
                 user=Depends(require("accounts:write"))):
    if body.type not in VOUCHER_TYPES:
        raise HTTPException(422, f"The voucher type must be one of "
                                 f"{', '.join(VOUCHER_TYPES)}")
    try:
        row = journal.update_voucher(db, voucher_id, body.date, body.type,
                                     body.narration, _lines(body.lines))
    except journal.LedgerError as exc:
        _ledger(db, exc)
    audit(db, user.id, "accounts.voucher.update", f"voucher:{row.id}",
          {"number": row.number, "date": str(row.voucher_date)})
    db.commit()
    return _json(journal.voucher_detail(db, row.id))


@router.delete("/vouchers/{voucher_id}")
def remove_voucher(voucher_id: int, db: Session = Depends(get_db),
                   user=Depends(require("accounts:write"))):
    try:
        journal.delete_voucher(db, voucher_id)
    except journal.LedgerError as exc:
        _ledger(db, exc)
    audit(db, user.id, "accounts.voucher.delete", f"voucher:{voucher_id}", {})
    db.commit()
    return {"deleted": voucher_id}


@router.post("/vouchers/{voucher_id}/post")
def post_voucher(voucher_id: int, db: Session = Depends(get_db),
                 user=Depends(require("accounts:write"))):
    try:
        row = journal.post_voucher(db, voucher_id, user.id)
    except journal.LedgerError as exc:
        _ledger(db, exc)
    audit(db, user.id, "accounts.voucher.post", f"voucher:{row.id}",
          {"number": row.number, "debit": str(row.debit_total)})
    db.commit()
    return _json(journal.voucher_detail(db, row.id))


@router.post("/vouchers/{voucher_id}/reverse", status_code=201)
def reverse_voucher(voucher_id: int, body: ReverseIn,
                    db: Session = Depends(get_db),
                    user=Depends(require("accounts:write"))):
    try:
        mirror = journal.reverse_voucher(db, voucher_id, body.reason, user.id)
    except journal.LedgerError as exc:
        _ledger(db, exc)
    audit(db, user.id, "accounts.voucher.reverse", f"voucher:{voucher_id}",
          {"mirror": mirror.number, "reason": body.reason})
    db.commit()
    return _json(journal.voucher_detail(db, mirror.id))


# ------------------------------------------------------------------ day book
@router.get("/day-book")
def get_day_book(date_from: date | None = None, date_to: date | None = None,
                 db: Session = Depends(get_db),
                 _=Depends(require("accounts:read"))):
    today = date.today()
    start = date_from or today.replace(day=1)
    end = date_to or today
    try:
        return _json(journal.day_book(db, start, end))
    except journal.LedgerError as exc:
        _ledger(db, exc)


# ------------------------------------------------------------- balance sheet
@router.get("/balance-sheet")
def get_balance_sheet(as_of: date | None = None, db: Session = Depends(get_db),
                      _=Depends(require("accounts:read"))):
    return _json(balance_sheet.balance_sheet(db, as_of))


@router.get("/ledger-accounts/{account_id}/balance")
def get_account_balance(account_id: int, as_of: date | None = None,
                        db: Session = Depends(get_db),
                        _=Depends(require("accounts:read"))):
    try:
        return _json(balance_sheet.account_balance(db, account_id, as_of))
    except journal.LedgerError as exc:
        _ledger(db, exc)


# ------------------------------------------------------------ bank statements
class StatementIn(BaseModel):
    account_id: int
    period_from: date
    period_to: date
    opening_balance: Decimal = Field(max_digits=14, decimal_places=2)
    closing_balance: Decimal = Field(max_digits=14, decimal_places=2)
    note: str | None = Field(None, max_length=300)


class StatementPatch(BaseModel):
    opening_balance: Decimal | None = Field(None, max_digits=14,
                                           decimal_places=2)
    closing_balance: Decimal | None = Field(None, max_digits=14,
                                           decimal_places=2)
    note: str | None = Field(None, max_length=300)


class StatementLineIn(BaseModel):
    date: date
    description: str = Field(min_length=1, max_length=200)
    reference: str | None = Field(None, max_length=60)
    amount: Decimal = Field(max_digits=14, decimal_places=2)


class StatementLinesIn(BaseModel):
    lines: list[StatementLineIn]


class MatchIn(BaseModel):
    kind: str
    ref_id: int


def _rec(db: Session, exc: bank_rec.RecError, status: int = 409):
    _fail(db, exc, status)


@router.get("/bank-statements")
def list_bank_statements(db: Session = Depends(get_db),
                         _=Depends(require("accounts:read"))):
    return _json(bank_rec.statement_rows(db))


@router.post("/bank-statements", status_code=201)
def create_bank_statement(body: StatementIn, db: Session = Depends(get_db),
                          user=Depends(require("accounts:write"))):
    try:
        row = bank_rec.create_statement(db, body.account_id, body.period_from,
                                        body.period_to, body.opening_balance,
                                        body.closing_balance, body.note, user.id)
    except bank_rec.RecError as exc:
        _rec(db, exc)
    audit(db, user.id, "accounts.bank_statement.create",
          f"bank_statement:{row.id}",
          {"account_id": row.ledger_account_id, "from": str(row.period_from),
           "to": str(row.period_to), "closing": str(row.closing_balance)})
    db.commit()
    return _json(bank_rec.statement_detail(db, row.id))


@router.get("/bank-statements/{statement_id}")
def get_bank_statement(statement_id: int, db: Session = Depends(get_db),
                       _=Depends(require("accounts:read"))):
    try:
        return _json(bank_rec.statement_detail(db, statement_id))
    except bank_rec.RecError as exc:
        _rec(db, exc, 404)


@router.patch("/bank-statements/{statement_id}")
def patch_bank_statement(statement_id: int, body: StatementPatch,
                         db: Session = Depends(get_db),
                         user=Depends(require("accounts:write"))):
    try:
        row = bank_rec.update_statement(db, statement_id, body.opening_balance,
                                        body.closing_balance, body.note)
    except bank_rec.RecError as exc:
        _rec(db, exc)
    audit(db, user.id, "accounts.bank_statement.update",
          f"bank_statement:{row.id}", {"closing": str(row.closing_balance)})
    db.commit()
    return _json(bank_rec.statement_detail(db, row.id))


@router.delete("/bank-statements/{statement_id}")
def remove_bank_statement(statement_id: int, db: Session = Depends(get_db),
                          user=Depends(require("accounts:write"))):
    try:
        bank_rec.delete_statement(db, statement_id)
    except bank_rec.RecError as exc:
        _rec(db, exc)
    audit(db, user.id, "accounts.bank_statement.delete",
          f"bank_statement:{statement_id}", {})
    db.commit()
    return {"deleted": statement_id}


@router.post("/bank-statements/{statement_id}/lines", status_code=201)
def add_bank_lines(statement_id: int, body: StatementLinesIn,
                   db: Session = Depends(get_db),
                   user=Depends(require("accounts:write"))):
    try:
        detail = bank_rec.add_lines(db, statement_id,
                                    [line.model_dump() for line in body.lines])
    except bank_rec.RecError as exc:
        _rec(db, exc)
    audit(db, user.id, "accounts.bank_statement.lines", f"bank_statement:{statement_id}",
          {"added": len(body.lines)})
    db.commit()
    return _json(detail)


@router.delete("/bank-lines/{line_id}")
def remove_bank_line(line_id: int, db: Session = Depends(get_db),
                     user=Depends(require("accounts:write"))):
    try:
        bank_rec.delete_line(db, line_id)
    except bank_rec.RecError as exc:
        _rec(db, exc)
    audit(db, user.id, "accounts.bank_statement.line_delete", f"bank_line:{line_id}", {})
    db.commit()
    return {"deleted": line_id}


@router.post("/bank-lines/{line_id}/match")
def match_bank_line(line_id: int, body: MatchIn, db: Session = Depends(get_db),
                    user=Depends(require("accounts:write"))):
    try:
        line = bank_rec.match_line(db, line_id, body.kind, body.ref_id, user.id)
    except bank_rec.RecError as exc:
        _rec(db, exc)
    audit(db, user.id, "accounts.bank_statement.match", f"bank_line:{line_id}",
          {"kind": body.kind, "ref_id": body.ref_id, "amount": str(line["amount"])})
    db.commit()
    return _json(line)


@router.post("/bank-lines/{line_id}/unmatch")
def unmatch_bank_line(line_id: int, db: Session = Depends(get_db),
                      user=Depends(require("accounts:write"))):
    try:
        line = bank_rec.unmatch_line(db, line_id)
    except bank_rec.RecError as exc:
        _rec(db, exc)
    audit(db, user.id, "accounts.bank_statement.unmatch", f"bank_line:{line_id}", {})
    db.commit()
    return _json(line)


@router.get("/bank-statements/{statement_id}/candidates")
def bank_candidates(statement_id: int, db: Session = Depends(get_db),
                    _=Depends(require("accounts:read"))):
    try:
        return _json(bank_rec.candidates(db, statement_id))
    except bank_rec.RecError as exc:
        _rec(db, exc, 404)


@router.get("/bank-statements/{statement_id}/reconciliation")
def bank_reconciliation(statement_id: int, db: Session = Depends(get_db),
                        _=Depends(require("accounts:read"))):
    try:
        return _json(bank_rec.reconciliation(db, statement_id))
    except bank_rec.RecError as exc:
        _rec(db, exc, 404)
