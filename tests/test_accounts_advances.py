"""Receipts and payments against open documents, and the advances left over.

Every expectation is read back from the API or the database. An advance must
never read as revenue or as a purchase, and a settlement must never touch a
document that did not exist on the day the money moved.

Each test uses its own distributor and supplier: the test database is shared
and keeps rows between runs, so a party from another test must not leak into a
balance here.
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import Invoice, InvoiceLine, SalesOrder, User

from test_catalog_orders import _raise_order, _submit_and_dispatch

TODAY = date.today()


def _dec(value):
    return Decimal(str(value))


def _suffix():
    return uuid4().hex[:6].upper()


def _distributor(client):
    code = f"AV-{_suffix()}"
    res = client.as_user("admin").post("/api/distributors", json={
        "code": code, "name": f"Advance buyer {code}", "territory": "Test",
        "credit_limit": "100000.00", "state_code": "27"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _supplier(client):
    code = f"AS-{_suffix()}"
    res = client.as_user("admin").post("/api/suppliers", json={
        "code": code, "name": f"Advance supplier {code}", "kind": "supplier",
        "registration_type": "unregistered", "state_code": "27"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _invoice(world, distributor_id: int, invoice_date: date, grand: Decimal):
    """A synthetic issued invoice for a party, in the isolated test DB."""
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.username == "admin"))
        suffix = _suffix()
        order = SalesOrder(so_number=f"T-ADV-{suffix}", distributor_id=distributor_id,
                           status="dispatched", total=grand, created_by=actor.id)
        db.add(order)
        db.flush()
        invoice = Invoice(
            invoice_number=f"V{suffix}"[:16], financial_year="2026-27",
            sales_order_id=order.id, distributor_id=distributor_id,
            status="issued", invoice_date=invoice_date,
            place_of_supply_state_code="27", place_of_supply_kind="intra",
            seller_legal_name="Herbanova Test Co", buyer_name="Advance buyer",
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


def _tb_row(body, account):
    return next((r for r in body["rows"] if r["account"] == account), None)


def _post(client, **body):
    return client.as_user("admin").post("/api/accounts/payments", json=body)


def _advances(client, kind, party_id):
    res = client.as_user("admin").get(
        "/api/accounts/advances", params={"kind": kind, "party_id": party_id})
    assert res.status_code == 200, res.text
    return res.json()


def test_receipt_settles_oldest_invoices_and_holds_the_excess(client, world):
    party = _distributor(client)
    first_day = TODAY - timedelta(days=3)
    first_id, first_no = _invoice(world, party, first_day, Decimal("100.00"))
    second_id, second_no = _invoice(world, party, first_day + timedelta(days=1),
                                    Decimal("150.00"))

    res = _post(client, kind="receipt", purpose="outstanding",
                distributor_id=party, amount="300.00",
                paid_on=(first_day + timedelta(days=2)).isoformat(), mode="bank")
    assert res.status_code == 201, res.text
    body = res.json()

    assert [(a["invoice_id"], _dec(a["amount"])) for a in body["allocations"]] == [
        (first_id, Decimal("100.00")), (second_id, Decimal("150.00"))]
    assert _dec(body["allocated"]) == Decimal("250.00")
    assert _dec(body["advance"]) == Decimal("50.00")
    assert body["purpose"] == "outstanding"

    outstanding = client.as_user("admin").get("/api/accounts/outstanding").json()
    for invoice_id in (first_id, second_id):
        row = next(r for r in outstanding["receivables"] if r["invoice_id"] == invoice_id)
        assert _dec(row["outstanding"]) == 0

    held = _advances(client, "receipt", party)
    assert _dec(held["available"]) == Decimal("50.00")

    ledger = client.as_user("admin").get(
        f"/api/accounts/ledger/distributors/{party}").json()
    assert _dec(ledger["available_advance"]) == Decimal("50.00")
    receipt = next(e for e in ledger["entries"] if e["kind"] == "receipt")
    assert first_no in receipt["note"] and second_no in receipt["note"]
    assert "50.00" in receipt["note"] and "advance" in receipt["note"]
    assert _dec(ledger["closing_balance"]) == Decimal("-50.00")


def test_a_receipt_cannot_settle_an_invoice_issued_later(client, world):
    party = _distributor(client)
    day = TODAY - timedelta(days=2)
    future_id, _ = _invoice(world, party, TODAY - timedelta(days=1), Decimal("80.00"))

    res = _post(client, kind="receipt", purpose="outstanding",
                distributor_id=party, amount="80.00",
                paid_on=day.isoformat(), mode="cash")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["allocations"] == []
    assert _dec(body["advance"]) == Decimal("80.00")

    # The bill that did not exist on the receipt day keeps its own balance; the
    # money waits as an advance instead of being assumed against it.
    outstanding = client.as_user("admin").get("/api/accounts/outstanding").json()
    row = next(r for r in outstanding["receivables"] if r["invoice_id"] == future_id)
    assert _dec(row["outstanding"]) == Decimal("80.00")
    assert _dec(_advances(client, "receipt", party)["available"]) == Decimal("80.00")


def test_advance_is_not_revenue_or_a_purchase(client, world):
    party = _distributor(client)
    supplier = _supplier(client)
    before = client.as_user("admin").get("/api/accounts/trial-balance").json()
    before_sales = _tb_row(before, "Sales")
    before_purchases = _tb_row(before, "Purchases")

    receipt = _post(client, kind="receipt", purpose="advance",
                    distributor_id=party, amount="400.00",
                    paid_on=TODAY.isoformat(), mode="bank")
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["purpose"] == "advance"
    assert receipt.json()["allocations"] == []

    payment = _post(client, kind="payment", purpose="advance",
                    supplier_id=supplier, amount="250.00",
                    paid_on=TODAY.isoformat(), mode="bank")
    assert payment.status_code == 201, payment.text

    after = client.as_user("admin").get("/api/accounts/trial-balance").json()
    assert after["balanced"] is True
    assert _tb_row(after, "Sales") == before_sales
    assert _tb_row(after, "Purchases") == before_purchases
    from_customers = _tb_row(after, "Advances from distributors")
    to_suppliers = _tb_row(after, "Advances to suppliers")
    assert _dec(from_customers["credit"]) >= Decimal("400.00")
    assert _dec(to_suppliers["debit"]) >= Decimal("250.00")


def test_advance_is_drawn_down_by_a_later_invoice(client, world):
    party = _distributor(client)
    held = Decimal("500.00")
    posted = _post(client, kind="receipt", purpose="advance",
                   distributor_id=party, amount=str(held),
                   paid_on=TODAY.isoformat(), mode="bank")
    assert posted.status_code == 201, posted.text

    order = _raise_order(client, world, party, qty="1", price="100.00")
    _submit_and_dispatch(client, world, order)
    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice)
                            .where(Invoice.sales_order_id == order["id"]))
        invoice_id, invoice_no, grand = invoice.id, invoice.invoice_number, _dec(invoice.grand_total)

    assert grand > 0
    remaining = _advances(client, "receipt", party)
    assert _dec(remaining["available"]) == held - min(held, grand)

    outstanding = client.as_user("admin").get("/api/accounts/outstanding").json()
    row = next(r for r in outstanding["receivables"] if r["invoice_id"] == invoice_id)
    assert _dec(row["outstanding"]) == max(grand - held, Decimal("0.00"))

    ledger = client.as_user("admin").get(
        f"/api/accounts/ledger/distributors/{party}").json()
    receipt = next(e for e in ledger["entries"] if e["kind"] == "receipt")
    assert invoice_no in receipt["note"]
    assert f"{min(held, grand):.2f}" in receipt["note"]
    assert _dec(ledger["available_advance"]) == held - min(held, grand)


def test_supplier_advance_settles_goods_received_later(client, world):
    supplier = _supplier(client)
    held = Decimal("500.00")
    posted = _post(client, kind="payment", purpose="advance",
                   supplier_id=supplier, amount=str(held),
                   paid_on=TODAY.isoformat(), mode="bank")
    assert posted.status_code == 201, posted.text

    po = client.as_user("admin").post("/api/purchase-orders", json={
        "supplier_id": supplier,
        "lines": [{"sku": world["sku"], "qty": "10", "unit_cost": "30.00"}]})
    assert po.status_code == 201, po.text
    po_id = po.json()["id"]

    receipt = client.as_user("inventory").post(
        f"/api/purchase-orders/{po_id}/receive", json={
            "warehouse_id": world["warehouse_id"],
            "lines": [{"sku": world["sku"], "batch_no": f"A-{_suffix()}",
                       "qty": "10"}]})
    assert receipt.status_code == 201, receipt.text

    outstanding = client.as_user("admin").get("/api/accounts/outstanding").json()
    row = next(r for r in outstanding["payables"] if r["purchase_order_id"] == po_id)
    assert _dec(row["outstanding"]) == 0

    left = _advances(client, "payment", supplier)
    assert _dec(left["available"]) == held - Decimal("300.00")

    ledger = client.as_user("admin").get(
        f"/api/accounts/ledger/suppliers/{supplier}").json()
    payment = next(e for e in ledger["entries"] if e["kind"] == "payment")
    assert po.json()["po_number"] in payment["note"]
    assert "300.00" in payment["note"] and "advance" in payment["note"]
    assert _dec(ledger["available_advance"]) == held - Decimal("300.00")


def test_receivables_window_counts_the_draw_down(client, world):
    party = _distributor(client)
    day = TODAY - timedelta(days=4)
    invoice_id, _ = _invoice(world, party, day, Decimal("120.00"))
    posted = _post(client, kind="receipt", purpose="outstanding",
                   distributor_id=party, amount="120.00",
                   paid_on=(day + timedelta(days=1)).isoformat(), mode="bank")
    assert posted.status_code == 201, posted.text

    body = client.as_user("admin").get(
        "/api/accounts/receivables-by-distributor", params={
            "from_date": day.isoformat(), "to_date": TODAY.isoformat()}).json()
    row = next(r for r in body["rows"] if r["distributor_id"] == party)
    assert _dec(row["invoiced"]) == Decimal("120.00")
    assert _dec(row["received"]) == Decimal("120.00")
    assert _dec(row["closing"]) == 0
    outstanding = client.as_user("admin").get("/api/accounts/outstanding").json()
    assert invoice_id in {r["invoice_id"] for r in outstanding["receivables"]}


def test_advances_need_accounts_rights(client, world):
    party = _distributor(client)
    body = {"kind": "receipt", "purpose": "advance", "distributor_id": party,
            "amount": "10.00", "paid_on": TODAY.isoformat(), "mode": "cash"}

    sales = client.as_user("sales")       # accounts:read, no accounts:write
    assert sales.get("/api/accounts/advances", params={
        "kind": "receipt", "party_id": party}).status_code == 200
    assert sales.post("/api/accounts/payments", json=body).status_code == 403

    viewer = client.as_user("viewer")     # no accounts right at all
    assert viewer.get("/api/accounts/advances", params={
        "kind": "receipt", "party_id": party}).status_code == 403
    assert viewer.post("/api/accounts/payments", json=body).status_code == 403

    client.as_user("admin")
    assert _dec(_advances(client, "receipt", party)["available"]) == 0


def test_an_advance_cannot_name_a_document(client, world):
    party = _distributor(client)
    res = _post(client, kind="receipt", purpose="advance",
                distributor_id=party, invoice_id=1,
                amount="10.00", paid_on=TODAY.isoformat(), mode="cash")
    assert res.status_code == 422
    assert "advance" in res.text.lower()

    bad = _post(client, kind="receipt", purpose="something",
                distributor_id=party, amount="10.00",
                paid_on=TODAY.isoformat(), mode="cash")
    assert bad.status_code == 422
