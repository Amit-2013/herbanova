from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import Batch, StockMovement


def test_line_without_cost_needs_a_remark(client, world):
    r = client.post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"],
        "lines": [{"sku": world["sku"], "qty": "5"}]})
    assert r.status_code == 422
    assert "remark" in r.text.lower()


def test_line_with_cost_needs_no_remark(client, world):
    r = client.post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"],
        "lines": [{"sku": world["sku"], "qty": "2", "unit_cost": "45.50"}]})
    assert r.status_code == 201, r.text
    line = r.json()["lines"][0]
    assert line["unit_cost"] == "45.50"
    assert line["rate_remark"] is None


def test_remark_is_saved_and_labelled(client, world):
    r = client.post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"],
        "lines": [{"sku": world["sku"], "qty": "3", "rate_remark": "Free of Cost (FOC)"}]})
    assert r.status_code == 201, r.text
    po = r.json()
    line = po["lines"][0]
    assert line["unit_cost"] is None
    assert line["rate_remark"] == "foc"
    assert line["rate_remark_label"] == "Free of Cost (FOC)"

    fetched = client.get(f"/api/purchase-orders/{po['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["lines"][0]["rate_remark"] == "foc"


def test_unknown_remark_is_refused(client, world):
    r = client.post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"],
        "lines": [{"sku": world["sku"], "qty": "3", "rate_remark": "because I said so"}]})
    assert r.status_code == 422


def test_zero_cost_without_a_remark_is_refused(client, world):
    """An explicit zero is a price: it still has to say why the goods are free."""
    for zero in ("0", "0.00"):
        r = client.post("/api/purchase-orders", json={
            "supplier_id": world["supplier_id"],
            "lines": [{"sku": world["sku"], "qty": "5", "unit_cost": zero}]})
        assert r.status_code == 422, r.text
        assert "rate remark" in r.text.lower()


def test_zero_cost_with_a_remark_is_saved_and_received(client, world):
    r = client.post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"],
        "lines": [{"sku": world["sku"], "qty": "5", "unit_cost": "0.00",
                   "rate_remark": "foc"}]})
    assert r.status_code == 201, r.text
    po = r.json()
    line = po["lines"][0]
    assert Decimal(line["unit_cost"]) == Decimal("0.00")
    assert line["rate_remark"] == "foc"

    batch_no = f"Z-{uuid4().hex[:6].upper()}"
    received = client.as_user("inventory").post(
        f"/api/purchase-orders/{po['id']}/receive", json={
            "warehouse_id": world["warehouse_id"],
            "lines": [{"sku": world["sku"], "batch_no": batch_no, "qty": "5"}]})
    assert received.status_code == 201, received.text

    with SessionLocal() as db:
        batch = db.scalar(select(Batch).where(Batch.batch_no == batch_no))
        movement = db.scalar(select(StockMovement).where(StockMovement.batch_id == batch.id))
        assert Decimal(movement.unit_cost) == Decimal("0.00")
        assert movement.cost_source == "foc"
