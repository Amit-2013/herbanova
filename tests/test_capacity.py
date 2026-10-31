"""Warehouse capacity: measured usage, an optional limit, and the audited
Administrator override on a goods receipt that would exceed it."""
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models.core import AuditLog, Batch, Warehouse


def _dec(value):
    return Decimal(str(value))


def _new_warehouse(client, capacity=None, note=None):
    body = {"name": f"Cap test {uuid4().hex[:6]}"}
    if capacity is not None:
        body["capacity_units"] = capacity
    if note:
        body["capacity_note"] = note
    r = client.as_user("admin").post("/api/warehouses", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _row(client, warehouse_id):
    r = client.as_user("admin").get("/api/warehouses")
    assert r.status_code == 200, r.text
    return next(w for w in r.json() if w["id"] == warehouse_id)


def _po(client, world, qty):
    r = client.as_user("admin").post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"],
        "lines": [{"sku": world["sku"], "qty": str(qty), "unit_cost": "10"}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _receive(client, world, po_id, warehouse_id, qty, **extra):
    return client.post(f"/api/purchase-orders/{po_id}/receive", json={
        "warehouse_id": warehouse_id,
        "lines": [{"sku": world["sku"],
                   "batch_no": f"CAP-{uuid4().hex[:6].upper()}", "qty": str(qty)}],
        **extra})


def test_capacity_is_optional_explicit_and_audited(client):
    created = _new_warehouse(client, capacity=10, note="rack A")
    wid = created["id"]
    assert created["capacity_units"] == 10
    assert created["used_units"] == "0"
    assert created["free_units"] == "10"
    assert created["utilisation_pct"] == 0.0
    assert created["capacity_state"] == "ok"
    assert created["capacity_note"] == "rack A"

    # A role without stock:write may read the figures but not change them.
    denied = client.as_user("sales").put(f"/api/warehouses/{wid}/capacity",
                                         json={"capacity_units": 5})
    assert denied.status_code == 403

    invalid = client.as_user("admin").put(f"/api/warehouses/{wid}/capacity",
                                          json={"capacity_units": -1})
    assert invalid.status_code == 422

    updated = client.as_user("admin").put(f"/api/warehouses/{wid}/capacity",
                                          json={"capacity_units": 8, "capacity_note": "re-measured"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["capacity_units"] == 8
    assert updated.json()["capacity_note"] == "re-measured"

    # Clearing the limit is explicit: the API reports "not configured", and no
    # percentage or free space is invented for it.
    cleared = client.as_user("admin").put(f"/api/warehouses/{wid}/capacity",
                                          json={"capacity_units": None})
    assert cleared.status_code == 200, cleared.text
    body = cleared.json()
    assert body["capacity_units"] is None
    assert body["free_units"] is None
    assert body["utilisation_pct"] is None
    assert body["capacity_state"] == "not_configured"

    with SessionLocal() as db:
        actions = {a.action for a in db.scalars(
            select(AuditLog).where(AuditLog.record == f"warehouse:{wid}"))}
    assert {"warehouse.create", "warehouse.capacity"} <= actions


def test_grn_over_capacity_is_blocked_then_admin_override_is_audited(client, world):
    wid = _new_warehouse(client, capacity=5)["id"]
    po_id = _po(client, world, 10)

    blocked = _receive(client.as_user("inventory"), world, po_id, wid, 10)
    assert blocked.status_code == 409, blocked.text
    assert "capacity" in blocked.text.lower()
    with SessionLocal() as db:
        assert (db.scalar(select(func.coalesce(func.sum(Batch.on_hand), 0))
                          .where(Batch.warehouse_id == wid)) or 0) == 0

    refused = _receive(client.as_user("inventory"), world, po_id, wid, 10,
                       allow_over_capacity=True)
    assert refused.status_code == 403, refused.text

    accepted = _receive(client.as_user("admin"), world, po_id, wid, 10,
                        allow_over_capacity=True)
    assert accepted.status_code == 201, accepted.text

    row = _row(client, wid)
    assert _dec(row["used_units"]) == Decimal("10")
    assert _dec(row["free_units"]) == Decimal("-5")
    assert row["utilisation_pct"] == 200.0
    assert row["capacity_state"] == "over"

    with SessionLocal() as db:
        entry = db.scalar(select(AuditLog).where(
            AuditLog.action == "warehouse.capacity_override",
            AuditLog.record == f"warehouse:{wid}"))
        assert entry is not None
        assert entry.actor_id is not None


def test_dispatch_reports_the_source_warehouse_position(client, world):
    wid = _new_warehouse(client, capacity=100)["id"]
    po_id = _po(client, world, 10)
    received = _receive(client.as_user("inventory"), world, po_id, wid, 10)
    assert received.status_code == 201, received.text

    sales = client.as_user("sales")
    order = sales.post("/api/sales-orders", json={
        "distributor_id": world["distributor_id"],
        "lines": [{"sku": world["sku"], "qty": "1", "unit_price": "100.00"}]})
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    submitted = sales.post(f"/api/sales-orders/{order_id}/submit")
    assert submitted.status_code == 200, submitted.text
    if submitted.json()["status"] == "pending_approval":
        approval_id = submitted.json()["approval"]["id"]
        assert client.as_user("admin").post(
            f"/api/approvals/{approval_id}/decide",
            json={"decision": "approve", "reason": "test setup"}).status_code == 200

    dispatched = client.as_user("admin").post(
        f"/api/sales-orders/{order_id}/dispatch", json={"warehouse_id": wid})
    assert dispatched.status_code == 201, dispatched.text
    source = dispatched.json()["source_warehouse"]
    assert source["id"] == wid
    assert _dec(source["used_units"]) == Decimal("9")
    assert source["capacity_units"] == 100
    assert _dec(source["free_units"]) == Decimal("91")
    assert source["utilisation_pct"] == 9.0
    assert source["capacity_state"] == "ok"


def test_utilisation_report_reconciles_with_the_batch_table(client, world):
    created = _new_warehouse(client, capacity=10)
    wid, name = created["id"], created["name"]
    po_id = _po(client, world, 4)
    assert _receive(client.as_user("inventory"), world, po_id, wid, 4).status_code == 201

    report = client.as_user("admin").get("/api/reports/warehouse_utilisation")
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["reconciled"] is True
    assert all(c["ok"] for c in body["checks"])

    rows = body["tables"][0]["rows"]
    row = next(r for r in rows if r["name"] == name)
    assert _dec(row["used_units"]) == Decimal("4")
    assert _dec(row["free_units"]) == Decimal("6")
    assert row["utilisation_pct"] == 40.0
    assert row["capacity_state"] == "Within capacity"

    with SessionLocal() as db:
        independent = db.scalar(select(func.coalesce(func.sum(Batch.on_hand), 0)))
        warehouses = db.scalar(select(func.count()).select_from(Warehouse))
    total = sum((Decimal(r["used_units"]) for r in rows), Decimal(0))
    assert total == Decimal(str(independent))
    assert len(rows) == warehouses


def test_dashboard_shows_capacity_and_flags_a_tight_warehouse(client, world):
    wid = _new_warehouse(client, capacity=10)["id"]
    po_id = _po(client, world, 9)
    assert _receive(client.as_user("inventory"), world, po_id, wid, 9).status_code == 201

    dash = client.as_user("admin").get("/api/dashboard")
    assert dash.status_code == 200, dash.text
    body = dash.json()

    row = next(w for w in body["stock_by_warehouse"] if w["id"] == wid)
    assert row["capacity_units"] == 10
    assert _dec(row["used_units"]) == Decimal("9")
    assert _dec(row["free_units"]) == Decimal("1")
    assert row["utilisation_pct"] == 90.0
    assert row["capacity_state"] == "high"

    alert = next(a for a in body["attention"] if a["key"] == "warehouse_capacity")
    assert alert["available"] is True
    assert alert["count"] >= 1
    assert alert["severity"] in ("warn", "bad")
