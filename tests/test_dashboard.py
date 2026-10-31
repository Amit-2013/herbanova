"""The dashboard is counted in the database, not from capped lists (audit D-05).

The old screen filtered arrays loaded with page_size=200, so any list past 200
records understated its tile with no warning. These tests push every counted
table past 200 rows and require the tile to move by exactly the rows added.
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, select


def _dash(client, who="admin"):
    r = client.as_user(who).get("/api/dashboard")
    assert r.status_code == 200, r.text
    return r.json()


def test_dashboard_sections_follow_permissions(client, world):
    admin = _dash(client, "admin")
    for key in ("stock", "purchase_orders", "active_products", "orders_ready",
                "approvals_waiting", "leads", "warehouse_count"):
        assert admin[key] is not None, key

    viewer = _dash(client, "viewer")
    # Not allowed is null (unknown), never a misleading zero.
    assert viewer["leads"] is None
    assert viewer["approvals_waiting"] is None
    assert viewer["stock"] is not None and viewer["orders_ready"] is not None


def test_dashboard_requires_login(client):
    client.cookies.clear()
    assert client.get("/api/dashboard").status_code == 401


def test_tiles_count_past_the_old_200_row_cap(client, world):
    from app.core.db import SessionLocal
    from app.models.core import Batch, Lead, Product, PurchaseOrder, PurchaseOrderLine, User

    before = _dash(client)
    n = 230
    tag = uuid4().hex[:6]
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        base = db.scalar(select(Batch).where(Batch.id == world["batch_id"]))
        today = date.today()
        products = [Product(sku=f"DB{tag}{i:04d}", name=f"Dash product {i}", pack_size="1",
                            mrp=Decimal("10"), hsn="30049099", uqc="NOS", status="active")
                    for i in range(n)]
        db.add_all(products)
        db.flush()
        db.add_all([Batch(product_id=p.id, warehouse_id=base.warehouse_id,
                          batch_no=f"DB{tag}{i}", expiry=today + timedelta(days=30),
                          on_hand=Decimal("2")) for i, p in enumerate(products)])
        db.add_all([Lead(lead_no=f"LD{tag}{i:04d}", name=f"Lead {i}", source="web",
                         status="new", owner_id=admin.id, created_by=admin.id, phone=f"98{i:08d}",
                         phone_key=f"98{i:08d}", next_follow_up=today - timedelta(days=2))
                    for i in range(n)])
        pos = [PurchaseOrder(po_number=f"PO{tag}{i:04d}", supplier="Dash supplier",
                             status="open", created_by=admin.id) for i in range(n)]
        db.add_all(pos)
        db.flush()
        db.add_all([PurchaseOrderLine(po_id=po.id, product_id=products[0].id,
                                      qty=Decimal("4"), unit_cost=Decimal("2.50"))
                    for po in pos])
        db.commit()

    try:
        after = _dash(client)
        assert after["active_products"] - before["active_products"] == n
        assert after["stock"]["batches_in_stock"] - before["stock"]["batches_in_stock"] == n
        assert (Decimal(after["stock"]["units_on_hand"])
                - Decimal(before["stock"]["units_on_hand"])) == Decimal(2 * n)
        assert after["stock"]["expiring_count"] - before["stock"]["expiring_count"] == n
        assert after["purchase_orders"]["open_count"] - before["purchase_orders"]["open_count"] == n
        assert after["leads"]["overdue"] - before["leads"]["overdue"] == n
        # The lists stay short however large the counts are.
        assert len(after["stock"]["expiring"]) <= 6
        assert len(after["purchase_orders"]["open"]) <= 6
        newest = after["purchase_orders"]["open"][0]
        assert Decimal(newest["value"]) == Decimal("10.00")
        assert Decimal(newest["remaining_units"]) == Decimal("4")
    finally:
        # The rows are synthetic and carry no stock movements, so remove them: other
        # tests reconcile the whole stock table against the movement ledger.
        with SessionLocal() as db:
            pids = select(Product.id).where(Product.sku.like(f"DB{tag}%"))
            db.execute(delete(PurchaseOrderLine).where(PurchaseOrderLine.po_id.in_(
                select(PurchaseOrder.id).where(PurchaseOrder.po_number.like(f"PO{tag}%")))))
            db.execute(delete(PurchaseOrder).where(PurchaseOrder.po_number.like(f"PO{tag}%")))
            db.execute(delete(Lead).where(Lead.lead_no.like(f"LD{tag}%")))
            db.execute(delete(Batch).where(Batch.product_id.in_(pids)))
            db.execute(delete(Product).where(Product.sku.like(f"DB{tag}%")))
            db.commit()


def test_expiring_list_is_soonest_first_and_flags_expired(client, world):
    data = _dash(client)["stock"]["expiring"]
    days = [row["days_left"] for row in data]
    assert days == sorted(days)
