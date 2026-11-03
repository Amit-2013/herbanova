"""Vouchers, opening balances, the balance sheet and bank reconciliation.

A08, A09 and A10 are closed against real rows: a voucher is drafted, refused
while unbalanced, posted, reversed and seen in the day book; an opening trial
balance is saved and its difference reported rather than plugged; the balance
sheet merges the opening, the vouchers and the documents; and a statement line
is matched to a receipt or payment only when the amount and direction agree.

The tests also prove the gates: a locked month and a closed year refuse the
write with 423, and the roles keep read and write apart.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.models.accounts import (BankStatement, FinancialYearClose, LedgerAccount,
                                 OpeningBalance, Payment, Voucher)
from app.models.core import User
from app.models.hr import PeriodLock
from app.services import balance_sheet, bank_rec, journal, periods

TODAY = date.today()
OLD_DAY = date(2018, 6, 15)


def _dec(value) -> Decimal:
    return Decimal(str(value))


def _admin(db) -> User:
    return db.scalar(select(User).where(User.username == "admin"))


def _account(db, role: str) -> LedgerAccount:
    row = db.scalar(select(LedgerAccount).where(LedgerAccount.role == role))
    assert row is not None, f"seeded head {role} is missing"
    return row


def _lines(db, debit_role: str, credit_role: str, amount: str) -> list[dict]:
    return [{"ledger_account_id": _account(db, debit_role).id,
             "debit": _dec(amount), "credit": _dec(0)},
            {"ledger_account_id": _account(db, credit_role).id,
             "debit": _dec(0), "credit": _dec(amount)}]


def _clear_openings(db, *labels: str) -> None:
    for label in labels:
        journal.delete_opening_rows(db, label)
    db.commit()


# ------------------------------------------------------------------- heads
def test_chart_is_seeded_with_the_document_roles():
    with SessionLocal() as db:
        rows = journal.account_rows(db)
        roles = {row["role"] for row in rows}
        assert {"cash", "bank", "receivables", "payables", "output_gst",
                "capital", "sales", "purchases", "round_off"} <= roles
        assert all(row["seeded"] for row in rows if row["role"])


def test_extra_head_can_be_created_and_deactivated():
    with SessionLocal() as db:
        actor = _admin(db)
        row = journal.create_account(db, "1200", "Fixed assets", "asset",
                                     "Office equipment", actor.id)
        db.commit()
        account_id = row.id
        assert journal.update_account(db, account_id, active=False).active is False
        db.commit()
        db.delete(db.get(LedgerAccount, account_id))
        db.commit()


# --------------------------------------------------------- opening balances
def test_opening_trial_balance_reports_an_imbalance():
    label = "2018-19"
    with SessionLocal() as db:
        actor = _admin(db)
        _clear_openings(db, label)
        journal.save_opening(db, _account(db, "cash").id, label,
                             _dec(1000), _dec(0), None, actor.id)
        journal.save_opening(db, _account(db, "capital").id, label,
                             _dec(0), _dec(900), None, actor.id)
        db.commit()
        out = journal.opening_rows(db, label)
        assert out["debit_total"] == _dec(1000)
        assert out["credit_total"] == _dec(900)
        assert out["difference"] == _dec(100)
        assert out["balanced"] is False

        journal.save_opening(db, _account(db, "capital").id, label,
                             _dec(0), _dec(1000), None, actor.id)
        db.commit()
        out = journal.opening_rows(db, label)
        assert out["difference"] == _dec(0)
        assert out["balanced"] is True

        journal.save_opening(db, _account(db, "capital").id, label,
                             _dec(0), _dec(0), None, actor.id)
        db.commit()
        capital = next(r for r in journal.opening_rows(db, label)["rows"]
                       if r["role"] == "capital")
        assert capital["credit"] == _dec(0)
        _clear_openings(db, label)


def test_opening_balance_refuses_a_closed_year():
    label = "2017-18"
    with SessionLocal() as db:
        actor = _admin(db)
        close = FinancialYearClose(financial_year=label, active=True,
                                   reason="test close", closed_by=actor.id)
        db.add(close)
        db.commit()
        close_id = close.id
        try:
            with pytest.raises(journal.LedgerError) as exc:
                journal.save_opening(db, _account(db, "cash").id, label,
                                     _dec(10), _dec(0), None, actor.id)
            assert exc.value.status == 423
            db.rollback()
        finally:
            db.execute(delete(FinancialYearClose).where(
                FinancialYearClose.id == close_id))
            db.commit()


# ---------------------------------------------------------------- vouchers
def test_voucher_draft_post_and_reverse():
    with SessionLocal() as db:
        actor = _admin(db)
        cash = _account(db, "cash")
        before = balance_sheet.account_balance(db, cash.id, TODAY)["balance"]

        draft = journal.create_voucher(
            db, OLD_DAY, "journal", "Unbalanced draft",
            [{"ledger_account_id": _account(db, "purchases").id,
              "debit": _dec(10), "credit": _dec(0)},
             {"ledger_account_id": cash.id, "debit": _dec(0), "credit": _dec(5)}],
            actor.id)
        db.commit()
        assert draft.status == "draft"
        with pytest.raises(journal.LedgerError, match="does not balance"):
            journal.post_voucher(db, draft.id, actor.id)
        db.rollback()

        journal.update_voucher(db, draft.id, OLD_DAY, "payment", "Balanced",
                               _lines(db, "purchases", "cash", "50"))
        db.commit()
        posted = journal.post_voucher(db, draft.id, actor.id)
        db.commit()
        assert posted.status == "posted"

        with pytest.raises(journal.LedgerError, match="reversed instead"):
            journal.update_voucher(db, draft.id, OLD_DAY, "payment", "edit",
                                   _lines(db, "purchases", "cash", "50"))

        after_post = balance_sheet.account_balance(db, cash.id, TODAY)["balance"]
        assert after_post == before - _dec(50)

        mirror = journal.reverse_voucher(db, draft.id, "wrong head", actor.id)
        db.commit()
        assert mirror.reversal_of_id == draft.id
        assert journal.voucher_detail(db, draft.id)["status"] == "reversed"

        after_reverse = balance_sheet.account_balance(db, cash.id, TODAY)["balance"]
        assert after_reverse == before

        book = journal.day_book(db, OLD_DAY, TODAY)
        numbers = {row["number"] for row in book["rows"]}
        assert journal.voucher_detail(db, draft.id)["number"] in numbers
        assert mirror.number in numbers
        assert book["balanced"] is True


def test_locked_month_refuses_a_voucher():
    with SessionLocal() as db:
        actor = _admin(db)
        # A closed month is a row per (scope, year, month) that an unlock keeps
        # with active=False, so a lingering row from another test is reactivated
        # rather than inserted again.
        lock = db.scalar(select(PeriodLock).where(
            PeriodLock.scope == "accounting", PeriodLock.year == TODAY.year,
            PeriodLock.month == TODAY.month))
        prior_active = lock.active if lock is not None else False
        if lock is None:
            lock = PeriodLock(scope="accounting", year=TODAY.year,
                              month=TODAY.month, locked_by=actor.id)
            db.add(lock)
        lock.active = True
        lock.reason = "test lock"
        db.flush()
        lock_id = lock.id
        db.commit()
        try:
            with SessionLocal() as inner:
                inner_actor = _admin(inner)
                with pytest.raises(journal.LedgerError) as exc:
                    journal.create_voucher(
                        inner, TODAY, "journal", "Lock probe",
                        _lines(inner, "purchases", "cash", "5"),
                        inner_actor.id, post=True)
                assert exc.value.status == 423
                inner.rollback()
        finally:
            with SessionLocal() as cleanup:
                row = cleanup.get(PeriodLock, lock_id)
                row.active = prior_active
                cleanup.commit()


def test_future_voucher_is_refused():
    with SessionLocal() as db:
        actor = _admin(db)
        with pytest.raises(journal.LedgerError, match="future"):
            journal.create_voucher(db, TODAY + timedelta(days=1), "journal",
                                   "Tomorrow", _lines(db, "purchases", "cash", "1"),
                                   actor.id)
        db.rollback()


# ------------------------------------------------------------ balance sheet
def test_balance_sheet_merges_opening_voucher_and_documents():
    label = "2018-19"
    as_of = date(2019, 3, 31)
    with SessionLocal() as db:
        actor = _admin(db)
        _clear_openings(db, label)
        before = balance_sheet.balance_sheet(db, as_of)

        journal.save_opening(db, _account(db, "cash").id, label,
                             _dec(1000), _dec(0), "cash in hand", actor.id)
        journal.save_opening(db, _account(db, "capital").id, label,
                             _dec(0), _dec(1000), "owner capital", actor.id)
        db.commit()

        after = balance_sheet.balance_sheet(db, as_of)
        cash_row = next(row for row in after["cash_bank"]["rows"]
                        if row["role"] == "cash")
        before_cash = next(row for row in before["cash_bank"]["rows"]
                           if row["role"] == "cash")
        assert cash_row["balance"] - before_cash["balance"] == _dec(1000)
        assert (after["totals"]["equity"] - before["totals"]["equity"]
                == _dec(1000))
        assert after["totals"]["difference"] == before["totals"]["difference"]
        assert after["opening"]["financial_year"] == label
        assert after["opening"]["balanced"] is True
        assert any(w.startswith("The document layer covers")
                   for w in after["warnings"])
        _clear_openings(db, label)


def test_balance_sheet_names_a_carried_forward_opening():
    with SessionLocal() as db:
        actor = _admin(db)
        _clear_openings(db, "2018-19", "2025-26")
        journal.save_opening(db, _account(db, "cash").id, "2018-19",
                             _dec(500), _dec(0), None, actor.id)
        journal.save_opening(db, _account(db, "capital").id, "2018-19",
                             _dec(0), _dec(500), None, actor.id)
        db.commit()
        out = balance_sheet.balance_sheet(db, date(2025, 6, 30))
        assert out["opening_fy"] == "2018-19"
        assert out["window_start"] == date(2018, 4, 1)
        assert any("No opening balance is captured for 2025-26" in w
                   for w in out["warnings"])
        _clear_openings(db, "2018-19", "2025-26")


# --------------------------------------------------------- bank reconciliation
def _payment(db, world, kind: str, amount: str, day: date, reference: str) -> int:
    actor = _admin(db)
    pay = Payment(kind=kind,
                  distributor_id=world["distributor_id"] if kind == "receipt" else None,
                  supplier_id=world["supplier_id"] if kind == "payment" else None,
                  amount=_dec(amount), paid_on=day, mode="bank",
                  reference=reference, created_by=actor.id)
    db.add(pay)
    db.flush()
    return pay.id


def test_bank_statement_match_and_proof(world):
    start, end = date(2019, 4, 1), date(2019, 4, 30)
    with SessionLocal() as db:
        actor = _admin(db)
        bank = _account(db, "bank")
        receipt_id = _payment(db, world, "receipt", "10000", date(2019, 4, 5),
                              "T-REC-1")
        payment_id = _payment(db, world, "payment", "4000", date(2019, 4, 12),
                              "T-PAY-1")
        db.commit()

        opening = balance_sheet.account_balance(
            db, bank.id, start - timedelta(days=1))["balance"]
        closing = opening + _dec(10000) - _dec(4000) - _dec(250)
        statement = bank_rec.create_statement(db, bank.id, start, end, opening,
                                              closing, "test period", actor.id)
        db.commit()
        detail = bank_rec.add_lines(db, statement.id, [
            {"date": date(2019, 4, 5), "description": "Deposit from distributor",
             "reference": "T-REC-1", "amount": _dec(10000)},
            {"date": date(2019, 4, 12), "description": "Payment to supplier",
             "reference": "T-PAY-1", "amount": _dec(-4000)},
            {"date": date(2019, 4, 25), "description": "Bank charges",
             "reference": None, "amount": _dec(-250)},
        ])
        db.commit()
        lines = {line["description"]: line for line in detail["lines"]}

        with pytest.raises(bank_rec.RecError, match="amounts do not agree"):
            bank_rec.match_line(db, lines["Payment to supplier"]["id"], "payment",
                                receipt_id, actor.id)
        db.rollback()

        bank_rec.match_line(db, lines["Deposit from distributor"]["id"], "payment",
                            receipt_id, actor.id)
        bank_rec.match_line(db, lines["Payment to supplier"]["id"], "payment",
                            payment_id, actor.id)
        db.commit()

        proof = bank_rec.reconciliation(db, statement.id)
        assert proof["matched"]["count"] == 2
        assert len(proof["unmatched_statement"]) == 1
        assert proof["unmatched_statement"][0]["description"] == "Bank charges"
        assert proof["proof"]["balanced"] is True
        assert proof["proof"]["difference"] == _dec(0)
        assert proof["proof"]["lines_check"] == _dec(0)
        assert proof["warnings"] == []

        with pytest.raises(bank_rec.RecError, match="Unmatch every line"):
            bank_rec.delete_statement(db, statement.id)
        db.rollback()
        with pytest.raises(bank_rec.RecError, match="Unmatch the line"):
            bank_rec.delete_line(db, lines["Deposit from distributor"]["id"])
        db.rollback()

        for line in proof["lines"]:
            if line["matched"]:
                bank_rec.unmatch_line(db, line["id"])
        db.commit()
        bank_rec.delete_statement(db, statement.id)
        db.commit()
        db.execute(delete(Payment).where(Payment.id.in_([receipt_id, payment_id])))
        db.commit()


def test_bank_statement_refuses_an_overlap_and_a_bad_line(world):
    start, end = date(2020, 1, 1), date(2020, 1, 31)
    with SessionLocal() as db:
        actor = _admin(db)
        bank = _account(db, "bank")
        first = bank_rec.create_statement(db, bank.id, start, end, _dec(0),
                                          _dec(0), None, actor.id)
        db.commit()
        first_id = first.id
        with pytest.raises(bank_rec.RecError, match="already covers"):
            bank_rec.create_statement(db, bank.id, date(2020, 1, 15),
                                      date(2020, 2, 15), _dec(0), _dec(0), None,
                                      actor.id)
        db.rollback()
        with pytest.raises(bank_rec.RecError, match="outside the statement period"):
            bank_rec.add_lines(db, first_id, [
                {"date": date(2020, 2, 3), "description": "Late line",
                 "reference": None, "amount": _dec(10)}])
        db.rollback()
        with pytest.raises(bank_rec.RecError, match="cannot be zero"):
            bank_rec.add_lines(db, first_id, [
                {"date": date(2020, 1, 3), "description": "Zero line",
                 "reference": None, "amount": _dec(0)}])
        db.rollback()
        bank_rec.delete_statement(db, first_id)
        db.commit()


# ---------------------------------------------------------------------- API
def _voucher_body(db, debit: str, credit: str, post: bool = False) -> dict:
    return {"date": TODAY.isoformat(), "type": "journal",
            "narration": "API test voucher", "post": post,
            "lines": [{"ledger_account_id": _account(db, "purchases").id,
                       "debit": debit, "credit": "0"},
                      {"ledger_account_id": _account(db, "cash").id,
                       "debit": "0", "credit": credit}]}


def test_api_keeps_read_and_write_apart(client):
    with SessionLocal() as db:
        body = _voucher_body(db, "10", "10")
    sales = client.as_user("sales")
    assert sales.get("/api/accounts/ledger-accounts").status_code == 200
    assert sales.get("/api/accounts/balance-sheet").status_code == 200
    assert sales.post("/api/accounts/ledger-accounts",
                      json={"code": "1999", "name": "Nope", "type": "asset"}
                      ).status_code == 403
    assert sales.post("/api/accounts/vouchers", json=body).status_code == 403
    assert client.as_user("viewer").get(
        "/api/accounts/ledger-accounts").status_code == 403
    client.as_user("admin")


def test_api_voucher_lifecycle_and_day_book(client):
    with SessionLocal() as db:
        unbalanced = _voucher_body(db, "10", "5")
        balanced = _voucher_body(db, "10", "10")

    admin = client.as_user("admin")
    draft = admin.post("/api/accounts/vouchers", json=unbalanced)
    assert draft.status_code == 201, draft.text
    assert draft.json()["status"] == "draft"
    voucher_id = draft.json()["id"]

    assert admin.post(f"/api/accounts/vouchers/{voucher_id}/post").status_code == 409

    fixed = admin.put(f"/api/accounts/vouchers/{voucher_id}", json=balanced)
    assert fixed.status_code == 200, fixed.text
    assert admin.post(f"/api/accounts/vouchers/{voucher_id}/post").status_code == 200

    edit_posted = admin.put(f"/api/accounts/vouchers/{voucher_id}", json=balanced)
    assert edit_posted.status_code == 409

    reversed_ = admin.post(f"/api/accounts/vouchers/{voucher_id}/reverse",
                           json={"reason": "test reversal"})
    assert reversed_.status_code == 201, reversed_.text
    assert reversed_.json()["reverse_of"] == voucher_id

    day = admin.get("/api/accounts/day-book").json()
    assert any(row["id"] == voucher_id for row in day["rows"])
    assert day["balanced"] is True

    sheet = admin.get("/api/accounts/balance-sheet").json()
    assert set(sheet["sections"]) == {"asset", "liability", "equity", "income",
                                      "expense"}
    assert isinstance(sheet["cash_bank"]["cash"], str)


def test_api_opening_balance_and_validation(client):
    with SessionLocal() as db:
        cash = _account(db, "cash")
    admin = client.as_user("admin")
    label = periods.fy_label(TODAY)
    body = {"account_id": cash.id, "financial_year": label,
            "debit": "100.00", "credit": "0.00", "note": "API opening"}
    saved = admin.put("/api/accounts/opening-balances", json=body)
    assert saved.status_code == 200, saved.text
    row = next(r for r in saved.json()["rows"] if r["account_id"] == cash.id)
    assert row["debit"] == "100.00"

    cleared = admin.put("/api/accounts/opening-balances",
                        json={**body, "debit": "0.00", "credit": "0.00"})
    assert cleared.status_code == 200
    row = next(r for r in cleared.json()["rows"] if r["account_id"] == cash.id)
    assert row["debit"] == "0.00"

    bad = admin.get("/api/accounts/opening-balances",
                    params={"financial_year": "2025/26"})
    assert bad.status_code == 409
