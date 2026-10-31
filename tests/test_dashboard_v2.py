"""Dashboard v2: the date window is applied in the query, not in the browser,
and the approvals card decides from the same rules as the queue."""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import AuditLog, Invoice, InvoiceLine, SalesOrder, User

TODAY = date.today()


def _dash(client, **params):
    r = client.as_user("admin").get("/api/dashboard", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _dash_as(client, user, **params):
    r = client.as_user(user).get("/api/dashboard", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _kpi(body, key):
    return next(k for k in body["kpis"] if k["key"] == key)["value"]


def _dec(value):
    return Decimal(str(value))


def _invoice(world, invoice_date: date, grand: Decimal) -> tuple[int, str]:
    """A synthetic issued invoice on a chosen date, in the isolated test DB."""
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.username == "admin"))
        suffix = uuid4().hex[:6].upper()
        order = SalesOrder(so_number=f"T-DATE-{suffix}", distributor_id=world["distributor_id"],
                           status="dispatched", total=grand, created_by=actor.id)
        db.add(order)
        db.flush()
        invoice = Invoice(
            invoice_number=f"T{suffix}"[:16], financial_year="2026-27",
            sales_order_id=order.id, distributor_id=world["distributor_id"],
            status="issued", invoice_date=invoice_date,
            place_of_supply_state_code="27", place_of_supply_kind="intra",
            seller_legal_name="Herbanova Test Co", buyer_name="Test distributor",
            taxable_value=grand, grand_total=grand, issued_by=actor.id)
        db.add(invoice)
        db.flush()
        db.add(InvoiceLine(
            invoice_id=invoice.id, product_id=world["product_id"], sku=world["sku"],
            product_name="Test product", qty=Decimal("1"), unit_price=grand,
            mrp=grand, discount_percent=Decimal("0"), discount_amount=Decimal("0"),
            taxable_value=grand, line_total=grand))
        db.commit()
        return invoice.id, invoice.invoice_number


def test_default_window_is_the_current_month(client, world):
    body = _dash(client)
    assert body["from"] == TODAY.replace(day=1).isoformat()
    assert body["to"] == TODAY.isoformat()
    assert body["range"] == TODAY.day


def test_invalid_windows_are_refused(client, world):
    admin = client.as_user("admin")
    assert admin.get("/api/dashboard", params={
        "from_date": "2026-01-10", "to_date": "2026-01-01"}).status_code == 422
    assert admin.get("/api/dashboard", params={
        "to_date": (TODAY + timedelta(days=1)).isoformat()}).status_code == 422


def test_dates_filter_the_query_and_reconcile_with_the_register(client, world):
    old_day = TODAY - timedelta(days=400)
    grand = Decimal("1234.50")
    _, number = _invoice(world, old_day, grand)

    # A window that contains the invoice counts it exactly once.
    inside = _dash(client, from_date=old_day.isoformat(), to_date=old_day.isoformat())
    assert _dec(inside["sales_vs_purchases"]["sales_total"]) == grand
    assert inside["range"] == 1
    assert inside["sales_vs_purchases"]["series"][0]["date"] == old_day.isoformat()

    # The current-month window must not contain it: the filter is in the query.
    recent = _dash(client, from_date=TODAY.replace(day=1).isoformat(),
                   to_date=TODAY.isoformat())
    register = client.as_user("admin").get(
        "/api/reports/invoices", params={"from": recent["from"],
                                         "to": recent["to"]}).json()
    rows = register["tables"][0]["rows"]
    assert number not in {row["invoice_number"] for row in rows}
    issued = sum((_dec(row["grand_total"]) for row in rows if row["status"] == "issued"),
                 Decimal(0))
    assert issued == _dec(recent["sales_vs_purchases"]["sales_total"])

    # The invoice register for the old day, built independently, agrees.
    old_report = client.as_user("admin").get(
        "/api/reports/invoices", params={"from": old_day.isoformat(),
                                         "to": old_day.isoformat()}).json()
    old_issued = sum((_dec(row["grand_total"])
                      for row in old_report["tables"][0]["rows"]
                      if row["status"] == "issued"), Decimal(0))
    assert old_issued == _dec(inside["sales_vs_purchases"]["sales_total"])


def _pending_order(client, world):
    """The sales desk raises an order over the credit limit; it needs the Admin."""
    sales = client.as_user("sales")
    order = sales.post("/api/sales-orders", json={
        "distributor_id": world["distributor_id"],
        "lines": [{"sku": world["sku"], "qty": "100", "unit_price": "100.00"}]})
    assert order.status_code == 201, order.text
    submitted = sales.post(f"/api/sales-orders/{order.json()['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["status"] == "pending_approval"
    return body["approval"]["id"]


def test_approvals_card_states_age_and_who_may_decide(client, world):
    approval_id = _pending_order(client, world)

    sales = _dash_as(client, "sales")
    row = next(r for r in sales["approvals"]["rows"] if r["id"] == approval_id)
    assert row["age_days"] == 0
    assert row["deciders"] == ["Administrator"]
    assert row["can_decide"] is False
    assert row["order_total"] is not None
    assert row["requested_by"] == "t_sales"

    admin = _dash(client)
    arow = next(r for r in admin["approvals"]["rows"] if r["id"] == approval_id)
    assert arow["can_decide"] is True
    assert arow["deciders"] == ["Administrator"]


def test_inline_decision_refreshes_card_kpi_and_writes_audit(client, world):
    approval_id = _pending_order(client, world)
    before = _dash(client)
    count_before = before["approvals"]["count"]
    kpi_before = _kpi(before, "approvals_waiting")
    assert approval_id in {r["id"] for r in before["approvals"]["rows"]}

    admin = client.as_user("admin")
    # A rejection without a real reason is refused by the same server rule the
    # inline form uses; nothing is written.
    assert admin.post(f"/api/approvals/{approval_id}/decide", json={
        "decision": "reject", "reason": "no"}).status_code == 422

    decided = admin.post(f"/api/approvals/{approval_id}/decide", json={
        "decision": "approve", "reason": "Approved from the dashboard"})
    assert decided.status_code == 200, decided.text

    after = _dash(client)
    assert after["approvals"]["count"] == count_before - 1
    assert _kpi(after, "approvals_waiting") == kpi_before - 1
    assert approval_id not in {r["id"] for r in after["approvals"]["rows"]}

    with SessionLocal() as db:
        entry = db.scalar(select(AuditLog).where(AuditLog.action == "approval.decide",
                                                 AuditLog.record == f"approval:{approval_id}"))
        assert entry is not None
        assert entry.actor_id is not None
