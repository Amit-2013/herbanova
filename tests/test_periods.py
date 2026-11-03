"""Financial-year close (GAP-A03) and invoice due dates (GAP-A04).

Every expectation is recomputed from the documents or from the same endpoint,
never from a stored production number. The tests close and reopen a year that
is already over so the shared test database never keeps a gate shut for the
tests that follow.
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import AuditLog, Distributor, Invoice
from app.services import periods

from test_dashboard_v2 import _invoice

TODAY = date.today()


def _dec(value):
    return Decimal(str(value))


# ------------------------------------------------------------------ year maths

def test_financial_year_runs_april_to_march():
    assert periods.fy_label(date(2026, 3, 31)) == "2025-26"
    assert periods.fy_label(date(2026, 4, 1)) == "2026-27"
    assert periods.fy_label(date(2026, 11, 3)) == "2026-27"
    assert periods.fy_start(date(2026, 2, 10)) == date(2025, 4, 1)
    assert periods.fy_end(date(2026, 2, 10)) == date(2026, 3, 31)
    assert periods.label_bounds("2025-26") == (date(2025, 4, 1), date(2026, 3, 31))
    assert periods.short_label("2025-26") == "25-26"
    assert periods.previous_label("2026-27") == "2025-26"
    assert periods.is_label("2025-26")
    assert not periods.is_label("2025-27")


# --------------------------------------------------------------------- close

def test_only_a_completed_year_can_be_closed(client, world):
    admin = client.as_user("admin")
    current = periods.fy_label(TODAY)
    refused = admin.post(f"/api/accounts/financial-years/{current}/close",
                         json={"reason": "closing a year that is still trading"})
    assert refused.status_code == 409
    assert "ended" in refused.json()["detail"]

    # A reason shorter than five characters is refused by the request schema.
    assert admin.post("/api/accounts/financial-years/2024-25/close",
                      json={"reason": "no"}).status_code == 422


def test_closed_year_refuses_documents_until_the_administrator_reopens_it(client, world):
    admin = client.as_user("admin")
    label = "2024-25"
    day = date(2024, 6, 10)

    closed = admin.post(f"/api/accounts/financial-years/{label}/close",
                        json={"reason": "books finalised for the year"})
    assert closed.status_code == 201, closed.text
    assert closed.json()["active"] is True

    listed = admin.get("/api/accounts/financial-years").json()
    row = next(y for y in listed["years"] if y["financial_year"] == label)
    assert row["active"] is True and row["reason"] == "books finalised for the year"

    receipt = {"kind": "receipt", "distributor_id": world["distributor_id"],
               "amount": "10.00", "paid_on": day.isoformat(), "mode": "cash"}
    blocked = admin.post("/api/accounts/payments", json=receipt)
    assert blocked.status_code == 423
    assert label in blocked.json()["detail"]

    # Only the Administrator may reopen; another role with accounts:write may not.
    assert client.as_user("sales").post(
        f"/api/accounts/financial-years/{label}/reopen",
        json={"reason": "sales cannot reopen a year"}).status_code == 403

    reopened = client.as_user("admin").post(
        f"/api/accounts/financial-years/{label}/reopen",
        json={"reason": "supplier invoice arrived late"})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["active"] is False
    assert reopened.json()["reopen_reason"] == "supplier invoice arrived late"

    allowed = client.as_user("admin").post("/api/accounts/payments", json=receipt)
    assert allowed.status_code == 201, allowed.text

    with SessionLocal() as db:
        actions = [a.action for a in db.scalars(
            select(AuditLog).where(AuditLog.record == f"financial_year:{label}")).all()]
    assert "accounts.financial_year.close" in actions
    assert "accounts.financial_year.reopen" in actions


def test_a_closed_year_refuses_free_sample_notes(client, world):
    from test_foc import _new_product

    product = _new_product()
    created = client.as_user("inventory").post("/api/foc/notes", json={
        "note_date": "2024-06-12", "warehouse_id": product["warehouse_id"],
        "recipient_name": "Year-close recipient", "reason": "sample",
        "lines": [{"product_id": product["product_id"],
                   "batch_id": product["batch_id"], "qty": "1"}]})
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]
    label = "2024-25"
    assert client.as_user("admin").post(
        f"/api/accounts/financial-years/{label}/close",
        json={"reason": "free-sample close test"}).status_code == 201
    try:
        blocked = client.as_user("admin").post(f"/api/foc/notes/{note_id}/approve")
        assert blocked.status_code == 423
        assert label in blocked.json()["detail"]
    finally:
        assert client.as_user("admin").post(
            f"/api/accounts/financial-years/{label}/reopen",
            json={"reason": "free-sample test finished"}).status_code == 200


def test_the_years_need_accounts_read_and_a_close_needs_accounts_write(client, world):
    assert client.as_user("sales").get("/api/accounts/financial-years").status_code == 200
    assert client.as_user("sales").post(
        "/api/accounts/financial-years/2024-25/close",
        json={"reason": "sales has no accounts write"}).status_code == 403
    assert client.as_user("viewer").get("/api/accounts/financial-years").status_code == 403


# ------------------------------------------------------------- month locks

def test_a_locked_month_refuses_receipts_and_notes(client, world):
    admin = client.as_user("admin")
    year, month = 2026, 1
    lock = admin.post("/api/accounts/period-locks",
                      json={"year": year, "month": month, "reason": "January reconciled"})
    assert lock.status_code == 201, lock.text
    lock_id = lock.json()["id"]
    try:
        receipt = {"kind": "receipt", "distributor_id": world["distributor_id"],
                   "amount": "10.00", "paid_on": f"{year}-{month:02d}-15", "mode": "bank"}
        blocked = admin.post("/api/accounts/payments", json=receipt)
        assert blocked.status_code == 423
        assert "locked" in blocked.json()["detail"]

        invoice_id, _ = _invoice(world, date(year, month, 5), Decimal("100.00"))
        note = admin.post("/api/credit-notes", json={
            "invoice_id": invoice_id, "reason": "return",
            "note_date": f"{year}-{month:02d}-20",
            "lines": []})
        assert note.status_code == 423
    finally:
        assert admin.post(f"/api/accounts/period-locks/{lock_id}/unlock",
                          json={"reason": "finished reconciling"}).status_code == 200

    assert admin.post("/api/accounts/payments", json=receipt).status_code == 201


def test_dispatch_is_refused_while_its_month_is_locked(client, world):
    from test_catalog_orders import _raise_order

    order = _raise_order(client, world, world["distributor_id"])
    lock = client.as_user("admin").post(
        "/api/accounts/period-locks",
        json={"year": TODAY.year, "month": TODAY.month,
              "reason": "month end reconciliation"})
    assert lock.status_code == 201, lock.text
    lock_id = lock.json()["id"]
    try:
        submitted = client.as_user("sales").post(f"/api/sales-orders/{order['id']}/submit")
        body = submitted.json()
        if body["status"] == "pending_approval":
            assert client.as_user("admin").post(
                f"/api/approvals/{body['approval']['id']}/decide",
                json={"decision": "approve", "reason": "lock test"}).status_code == 200
        blocked = client.as_user("admin").post(
            f"/api/sales-orders/{order['id']}/dispatch",
            json={"warehouse_id": world["warehouse_id"]})
        assert blocked.status_code == 423
        assert "locked" in blocked.json()["detail"]
    finally:
        assert client.as_user("admin").post(
            f"/api/accounts/period-locks/{lock_id}/unlock",
            json={"reason": "test finished"}).status_code == 200


# ---------------------------------------------------------------- due dates

def _new_distributor(client, **over):
    code = f"PD-{uuid4().hex[:6].upper()}"
    body = {"code": code, "name": f"Due-date buyer {code}", "territory": "Test",
            "credit_limit": "100000.00", "state_code": "27"}
    body.update(over)
    r = client.as_user("admin").post("/api/distributors", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _dispatch_for(client, world, distributor_id):
    from test_catalog_orders import _raise_order, _submit_and_dispatch

    order = _raise_order(client, world, distributor_id)
    _submit_and_dispatch(client, world, order)
    return next(i for i in client.as_user("admin").get("/api/invoices").json()
                if i["sales_order_id"] == order["id"])


def test_invoice_snapshots_terms_and_due_date(client, world):
    distributor_id = _new_distributor(client, payment_terms_days=30)
    invoice = _dispatch_for(client, world, distributor_id)
    assert invoice["payment_terms_days"] == 30
    assert invoice["due_date"] == (TODAY + timedelta(days=30)).isoformat()

    # Changing the master afterwards cannot move the due date of a document the
    # buyer already holds.
    changed = client.as_user("admin").patch(f"/api/distributors/{distributor_id}",
                                           json={"payment_terms_days": 90})
    assert changed.status_code == 200, changed.text
    again = client.as_user("admin").get(f"/api/invoices/{invoice['id']}").json()
    assert again["payment_terms_days"] == 30
    assert again["due_date"] == invoice["due_date"]


def test_no_terms_means_no_due_date_not_an_invented_one(client, world):
    distributor_id = _new_distributor(client)
    invoice = _dispatch_for(client, world, distributor_id)
    assert invoice["payment_terms_days"] is None
    assert invoice["due_date"] is None


def test_ageing_splits_outstanding_by_due_date(client, world):
    def with_due(due):
        invoice_id, number = _invoice(world, TODAY - timedelta(days=20), Decimal("100.00"))
        with SessionLocal() as db:
            row = db.get(Invoice, invoice_id)
            row.due_date = due
            db.commit()
        return invoice_id

    overdue = with_due(TODAY - timedelta(days=5))
    soon = with_due(TODAY + timedelta(days=3))
    later = with_due(TODAY + timedelta(days=60))
    none = with_due(None)

    body = client.as_user("admin").get("/api/accounts/ageing",
                                       params={"as_of": TODAY.isoformat()}).json()
    rows = {r["invoice_id"]: r for b in body["buckets"] for r in b["rows"]}
    assert rows[overdue]["days_overdue"] == 5
    assert rows[soon]["days_overdue"] == 0
    assert rows[none]["due_date"] is None
    assert body["due"]["overdue"]["count"] >= 1
    assert body["due"]["no_due_date"]["count"] >= 1
    assert rows[later]["due_date"] == (TODAY + timedelta(days=60)).isoformat()

    # Every outstanding invoice lands in exactly one due bucket.
    split = sum(_dec(v["total"]) for v in body["due"].values())
    assert split == _dec(body["total"])
    assert sum(v["count"] for v in body["due"].values()) == body["count"]
