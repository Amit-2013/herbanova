"""Product grouping, reorder levels and order promise dates.

Closes GAP-D01 (no category or brand), GAP-D02 (no reorder level) and GAP-D05
(no expected delivery date), and proves the approval stamp that separates
approval time from dispatch time. Every expectation is recomputed from the
database or from the same endpoint, never from a stored production number.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models.core import Batch, Invoice, InvoiceLine, Product, SalesOrder

IST = ZoneInfo("Asia/Kolkata")


def _dec(value):
    return Decimal(str(value))


def _new_distributor(client):
    code = f"CD-{uuid4().hex[:6].upper()}"
    r = client.post("/api/distributors", json={
        "code": code, "name": f"Catalog buyer {code}", "territory": "Test",
        "credit_limit": "100000.00", "state_code": "27"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _new_product(client, **over):
    sku = f"CAT-{uuid4().hex[:6].upper()}"
    body = {"sku": sku, "name": "Catalog test product", "pack_size": "10 tabs",
            "mrp": "100.00", "hsn": "30049099"}
    body.update(over)
    r = client.post("/api/products", json=body)
    assert r.status_code == 201, r.text
    return sku, r.json()


def _raise_order(client, world, distributor_id, promise=None, qty="1", price="100.00"):
    body = {"distributor_id": distributor_id,
            "lines": [{"sku": world["sku"], "qty": qty, "unit_price": price}]}
    if promise is not None:
        body["expected_delivery_date"] = promise.isoformat()
    r = client.as_user("sales").post("/api/sales-orders", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _submit_and_dispatch(client, world, order):
    sales = client.as_user("sales")
    submitted = sales.post(f"/api/sales-orders/{order['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    if body["status"] == "pending_approval":
        admin = client.as_user("admin")
        assert admin.post(f"/api/approvals/{body['approval']['id']}/decide",
                          json={"decision": "approve",
                                "reason": "catalog test"}).status_code == 200
    admin = client.as_user("admin")
    dispatched = admin.post(f"/api/sales-orders/{order['id']}/dispatch",
                            json={"warehouse_id": world["warehouse_id"]})
    assert dispatched.status_code == 201, dispatched.text
    return admin.get(f"/api/sales-orders/{order['id']}").json()


def _invoice_for(client, order_id):
    return next(i for i in client.as_user("admin").get("/api/invoices").json()
                if i["sales_order_id"] == order_id)


def test_product_grouping_and_reorder_level_round_trip(client, world):
    sku, product = _new_product(client, category="  Analgesics ", brand="Herbanova",
                                reorder_level="25.000")
    assert product["category"] == "Analgesics"
    assert product["brand"] == "Herbanova"
    assert _dec(product["reorder_level"]) == Decimal("25")

    # A blank label is "not captured", never an empty-string category.
    _, blank = _new_product(client, category="   ", brand="")
    assert blank["category"] is None and blank["brand"] is None
    assert blank["reorder_level"] is None

    # A negative reorder level is refused before it can reach the database.
    refused = client.post("/api/products", json={
        "sku": f"CAT-{uuid4().hex[:6].upper()}", "name": "Negative reorder",
        "pack_size": "1", "mrp": "10.00", "hsn": "30049099", "reorder_level": "-1"})
    assert refused.status_code == 422

    # Edit sets and clears the values; search and the catalog facets see them.
    edited = client.patch(f"/api/products/{product['id']}",
                          json={"category": "Antibiotics", "reorder_level": "0"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["category"] == "Antibiotics"
    assert _dec(edited.json()["reorder_level"]) == 0

    found = client.get("/api/products", params={"q": "Antibiotics", "page_size": 100}).json()
    assert product["id"] in [row["id"] for row in found]

    catalog = client.get("/api/products/catalog")
    assert catalog.status_code == 200, catalog.text
    assert "Antibiotics" in catalog.json()["categories"]
    assert "Herbanova" in catalog.json()["brands"]

    cleared = client.patch(f"/api/products/{product['id']}", json={"category": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["category"] is None
    # The reorder level is untouched by an unrelated edit.
    assert _dec(cleared.json()["reorder_level"]) == 0


def test_low_stock_attention_uses_the_configured_level(client, world):
    sku, product = _new_product(client, reorder_level="5")
    # No batch exists for this product, so its balance is genuinely zero.

    def expected_low():
        with SessionLocal() as db:
            rows = db.execute(
                select(Product.reorder_level,
                       func.coalesce(func.sum(Batch.on_hand), 0))
                .join(Batch, Batch.product_id == Product.id, isouter=True)
                .where(Product.reorder_level.is_not(None))
                .group_by(Product.id, Product.reorder_level)).all()
        return sum(1 for level, qty in rows if qty < level)

    body = client.get("/api/dashboard").json()
    low = next(a for a in body["attention"] if a["key"] == "low_stock")
    assert low["available"] is True
    assert low["count"] == expected_low()
    assert low["severity"] == "warn"
    assert low["href"] == "#/inventory/stock"
    assert sku in low["note"]

    # At zero the level is still set, but the product is not below it.
    assert client.patch(f"/api/products/{product['id']}",
                        json={"reorder_level": "0"}).status_code == 200
    body = client.get("/api/dashboard").json()
    low = next(a for a in body["attention"] if a["key"] == "low_stock")
    assert low["count"] == expected_low()
    assert sku not in low["note"]


def test_stock_report_exposes_grouping_and_reorder_flag(client, world):
    sku, product = _new_product(client, category="Dermatology", brand="Testbrand",
                                reorder_level="3")

    report = client.as_user("admin").get("/api/reports/stock")
    assert report.status_code == 200, report.text
    rows = {r["sku"]: r for r in report.json()["tables"][0]["rows"]}
    row = rows[sku]
    assert row["category"] == "Dermatology"
    assert row["brand"] == "Testbrand"
    assert _dec(row["reorder_level"]) == 3
    assert row["below_reorder"] is True        # balance 0 is below 3

    assert client.patch(f"/api/products/{product['id']}",
                        json={"reorder_level": "0"}).status_code == 200
    rows = {r["sku"]: r for r in client.as_user("admin")
            .get("/api/reports/stock").json()["tables"][0]["rows"]}
    assert rows[sku]["below_reorder"] is False  # set, and the balance is at it

    _, unset = _new_product(client)
    rows = {r["sku"]: r for r in client.as_user("admin")
            .get("/api/reports/stock").json()["tables"][0]["rows"]}
    assert rows[unset["sku"]]["below_reorder"] is None   # not captured, not false


def test_order_promise_is_stored_editable_and_validated(client, world):
    distributor_id = _new_distributor(client)
    today = date.today()
    promise = today + timedelta(days=5)

    order = _raise_order(client, world, distributor_id, promise=promise)
    assert order["expected_delivery_date"] == promise.isoformat()
    assert order["approved_at"] is None

    # A date in the past is refused rather than silently accepted.
    past = client.as_user("sales").post("/api/sales-orders", json={
        "distributor_id": distributor_id,
        "lines": [{"sku": world["sku"], "qty": "1", "unit_price": "100.00"}],
        "expected_delivery_date": (today - timedelta(days=1)).isoformat()})
    assert past.status_code == 422

    moved = client.as_user("sales").patch(
        f"/api/sales-orders/{order['id']}/delivery-date",
        json={"expected_delivery_date": (today + timedelta(days=9)).isoformat()})
    assert moved.status_code == 200, moved.text
    assert moved.json()["expected_delivery_date"] == (today + timedelta(days=9)).isoformat()

    # Re-sending the same promise is not a change.
    assert client.as_user("sales").patch(
        f"/api/sales-orders/{order['id']}/delivery-date",
        json={"expected_delivery_date": (today + timedelta(days=9)).isoformat()}
    ).status_code == 422
    # Nor is moving it into the past.
    assert client.as_user("sales").patch(
        f"/api/sales-orders/{order['id']}/delivery-date",
        json={"expected_delivery_date": (today - timedelta(days=2)).isoformat()}
    ).status_code == 422

    cleared = client.as_user("sales").patch(
        f"/api/sales-orders/{order['id']}/delivery-date",
        json={"expected_delivery_date": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["expected_delivery_date"] is None

    # Once dispatched the promise is history and can no longer be rewritten.
    done = _submit_and_dispatch(client, world, order)
    assert done["status"] == "dispatched"
    assert done["approved_at"] is not None
    assert client.as_user("sales").patch(
        f"/api/sales-orders/{order['id']}/delivery-date",
        json={"expected_delivery_date": (today + timedelta(days=3)).isoformat()}
    ).status_code == 409


def test_approval_is_stamped_when_the_order_is_approved(client, world):
    distributor_id = _new_distributor(client)
    order = _raise_order(client, world, distributor_id)
    submitted = client.as_user("sales").post(f"/api/sales-orders/{order['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()

    if body["status"] == "approved":            # no reason to ask an approver
        assert body["approved_at"] is not None
    else:
        assert body["approved_at"] is None
        decided = client.as_user("admin").post(
            f"/api/approvals/{body['approval']['id']}/decide",
            json={"decision": "approve", "reason": "catalog test"})
        assert decided.status_code == 200, decided.text
        reloaded = client.get(f"/api/sales-orders/{order['id']}").json()
        assert reloaded["status"] == "approved"
        assert reloaded["approved_at"] is not None


def test_category_sales_come_from_issued_invoices(client, world):
    label = f"Cat {uuid4().hex[:6].upper()}"
    distributor_id = _new_distributor(client)
    before = _dec(client.get("/api/dashboard").json()["category_sales"]["total"])

    with SessionLocal() as db:
        product = db.get(Product, world["product_id"])
        previous = product.category
        product.category = label
        db.commit()
    try:
        order = _raise_order(client, world, distributor_id)
        _submit_and_dispatch(client, world, order)
        invoice = _invoice_for(client, order["id"])

        body = client.get("/api/dashboard").json()
        section = body["category_sales"]
        assert section["available"] is True
        row = next(r for r in section["rows"] if r["category"] == label)

        # The row equals the same invoice lines recomputed from the database.
        with SessionLocal() as db:
            expected = db.scalar(
                select(func.coalesce(func.sum(InvoiceLine.taxable_value), 0))
                .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                .where(Invoice.status == "issued",
                       Invoice.invoice_date >= date.fromisoformat(body["from"]),
                       Invoice.invoice_date <= date.fromisoformat(body["to"]),
                       InvoiceLine.product_id == world["product_id"]))
        assert _dec(row["revenue"]) == _dec(expected)
        # Grouping never invents revenue: the total only rises by the new invoice.
        assert _dec(section["total"]) == before + _dec(invoice["taxable_value"])
        assert _dec(section["classified_total"]) >= _dec(row["revenue"])
        assert invoice["lines"][0]["sku"] == world["sku"]
    finally:
        with SessionLocal() as db:
            product = db.get(Product, world["product_id"])
            product.category = previous
            db.commit()


def test_pipeline_separates_approval_dispatch_and_lateness(client, world):
    distributor_id = _new_distributor(client)
    today = date.today()

    on_time = _raise_order(client, world, distributor_id, promise=today + timedelta(days=5))
    _submit_and_dispatch(client, world, on_time)

    late = _raise_order(client, world, distributor_id, promise=today + timedelta(days=1))
    # A promise made in the past is impossible through the API, so simulate an
    # order promised earlier and dispatched late.
    with SessionLocal() as db:
        so = db.get(SalesOrder, late["id"])
        so.expected_delivery_date = today - timedelta(days=2)
        db.commit()
    _submit_and_dispatch(client, world, late)

    dispatch = client.get("/api/dashboard").json()["insights"]["pipeline"]["sales"]["dispatch"]

    with SessionLocal() as db:
        rows = db.execute(
            select(SalesOrder.created_at, SalesOrder.approved_at,
                   SalesOrder.dispatched_at, SalesOrder.expected_delivery_date)
            .where(SalesOrder.status == "dispatched",
                   SalesOrder.dispatched_at.is_not(None))).all()

    approval_days = [(approved - raised).total_seconds() / 86400
                     for raised, approved, _done, _promise in rows
                     if raised is not None and approved is not None and approved >= raised]
    after_days = [(done - approved).total_seconds() / 86400
                  for _raised, approved, done, _promise in rows
                  if approved is not None and done is not None and done >= approved]
    lateness, on_time_count = [], 0
    for _raised, _approved, done, promise in rows:
        if promise is None:
            continue
        delivered = done.astimezone(IST).date()
        if delivered <= promise:
            on_time_count += 1
        else:
            lateness.append((delivered - promise).days)

    assert dispatch["approval_measured"] == len(approval_days)
    assert dispatch["approval_average_days"] == (
        round(sum(approval_days) / len(approval_days), 1) if approval_days else None)
    assert dispatch["after_approval_measured"] == len(after_days)
    assert dispatch["after_approval_average_days"] == (
        round(sum(after_days) / len(after_days), 1) if after_days else None)
    assert dispatch["delivery"]["measured"] == on_time_count + len(lateness)
    assert dispatch["delivery"]["on_time"] == on_time_count
    assert dispatch["delivery"]["late"] == len(lateness)
    assert dispatch["delivery"]["average_days_late"] == (
        round(sum(lateness) / len(lateness), 1) if lateness else None)
    # The two orders we dispatched here are counted: one met its promise, one did not.
    assert on_time_count >= 1 and len(lateness) >= 1
    assert dispatch["overdue_open"] >= 0
