"""Overview dashboard (Phase 2): period series, permission scoping, exact
expiry buckets, derivable stock history, search scoping and reconciliation
against the reports.

Every expectation is computed from the database or from another endpoint, never
from a hard-coded production value.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

IST = ZoneInfo("Asia/Kolkata")

KPI_KEYS = {"units_on_hand", "batches_in_stock", "expiring", "po_awaiting",
            "orders_ready", "approvals_waiting", "followups_overdue",
            "active_products"}


def _dash(client, who="admin", **params):
    r = client.as_user(who).get("/api/dashboard", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _dec(value):
    return Decimal(str(value))


def test_period_selector_shapes_every_series(client, world):
    for days in (7, 30, 90):
        body = _dash(client, range=days)
        assert body["range"] == days
        start = date.fromisoformat(body["from"])
        end = date.fromisoformat(body["to"])
        assert (end - start).days + 1 == days
        chart = body["sales_vs_purchases"]
        assert len(chart["series"]) == days
        assert (chart["from"], chart["to"]) == (body["from"], body["to"])

        keys = {tile["key"] for tile in body["kpis"]}
        assert keys == KPI_KEYS
        for tile in body["kpis"]:
            if tile["trend"] is not None:
                assert len(tile["trend"]) == len(tile["trend_points"])
                assert len(tile["trend"]) == min(days, 12)
                assert tile["trend_points"][-1] == body["to"]
            else:
                # No stored history is a stated gap, never a flat invented line.
                assert tile["trend_note"], tile["key"]

    # The unsupported range is refused rather than silently defaulted.
    assert client.as_user("admin").get("/api/dashboard",
                                       params={"range": 365}).status_code == 422


def test_sections_are_null_when_the_role_may_not_read_them(client, world):
    viewer = _dash(client, "viewer")
    assert viewer["stock"] is not None and viewer["expiry_watch"] is not None
    assert viewer["open_pos"] is not None and viewer["stock_by_warehouse"] is not None
    assert viewer["top_products"] is not None
    assert viewer["receivables_ageing"] is None          # no accounts:read
    assert viewer["approvals"] is None                   # no approval:read
    assert viewer["recent_activity"] is None             # no audit:read
    assert viewer["leads"] is None                       # no lead:read
    # Category revenue is grouped from issued invoices, so a viewer with
    # sales:read may see it; products without a category are named as such.
    assert viewer["category_sales"]["available"] is True

    sales = _dash(client, "sales")
    assert sales["receivables_ageing"] is not None       # accounts:read
    assert sales["approvals"] is not None                # approval:read
    assert sales["recent_activity"] is None              # no audit:read

    inventory = _dash(client, "inventory")
    assert inventory["receivables_ageing"] is None       # no accounts:read
    assert inventory["approvals"] is not None
    assert inventory["recent_activity"] is None

    payroll = _dash(client, "payroll")
    assert payroll["stock"] is None
    assert payroll["expiry_watch"] is None
    assert payroll["open_pos"] is None
    assert payroll["stock_by_warehouse"] is None
    assert payroll["sales_vs_purchases"] is None
    assert payroll["top_products"] is None

    for who in ("viewer", "sales", "inventory", "payroll"):
        assert _dash(client, who)["health"]["schema"]["head"]


def _custom_user(client, permissions):
    """A throwaway role and login, so the permission mask is tested on a role
    the seeded set does not happen to include."""
    from app.core.db import SessionLocal
    from app.core.security import make_token
    from app.models.core import User
    from app.models.users import Role

    tag = uuid4().hex[:6]
    with SessionLocal() as db:
        role = Role(name=f"dash_{tag}", display_name="Dashboard test role",
                    is_system=False, permissions=permissions)
        db.add(role)
        db.flush()
        user = User(username=f"dash_{tag}", password_hash="x", role="custom",
                    role_id=role.id)
        db.add(user)
        db.flush()
        token, user_id, role_id = make_token(user.id, 1), user.id, role.id
        db.commit()
    return token, user_id, role_id


def test_chart_masks_the_side_the_role_cannot_read(client, world):
    token, user_id, role_id = _custom_user(client, ["stock:read", "product:read"])
    try:
        client.cookies.set("session", token)
        body = client.get("/api/dashboard").json()
        chart = body["sales_vs_purchases"]
        assert chart is not None
        assert chart["sales_visible"] is False
        assert chart["purchases_visible"] is True
        assert chart["sales_total"] is None and chart["sales_change"] is None
        assert all(point["sales"] is None for point in chart["series"])
        assert any(point["purchases"] is not None for point in chart["series"])
        assert body["top_products"] is None
        assert body["receivables_ageing"] is None
        assert body["approvals"] is None
    finally:
        client.as_user("admin")
        from app.core.db import SessionLocal
        from app.models.core import User
        from app.models.users import Role
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id == user_id))
            db.execute(delete(Role).where(Role.id == role_id))
            db.commit()


def test_search_is_scoped_to_the_readers_permissions(client, world):
    admin = client.as_user("admin")
    body = admin.get("/api/dashboard/search", params={"q": world["sku"]}).json()
    assert body["query"] == world["sku"]
    products = next(g for g in body["groups"] if g["key"] == "products")
    assert any(item["title"] == world["sku"] for item in products["items"])
    assert all(g["shown"] <= 5 for g in body["groups"])

    # The supplier register is invisible to a viewer, visible to inventory.
    viewer = client.as_user("viewer")
    assert "suppliers" not in {g["key"] for g in
                               viewer.get("/api/dashboard/search",
                                          params={"q": "Test supplier"}).json()["groups"]}
    inventory = client.as_user("inventory")
    assert "suppliers" in {g["key"] for g in
                           inventory.get("/api/dashboard/search",
                                         params={"q": "Test supplier"}).json()["groups"]}

    # Leads need lead:read; a viewer does not have it even when the text matches.
    from app.core.db import SessionLocal
    from app.models.core import Lead
    lead_tag = uuid4().hex[:6]
    with SessionLocal() as db:
        db.add(Lead(lead_no=f"DS{lead_tag}", name=f"Dashboard probe {lead_tag}",
                    source="web", status="new", owner_id=client.ids["sales"],
                    created_by=client.ids["sales"], phone=f"99{lead_tag}",
                    phone_key=f"99{lead_tag}"))
        db.commit()
    try:
        sales = client.as_user("sales")
        groups = {g["key"]: g for g in sales.get(
            "/api/dashboard/search", params={"q": lead_tag}).json()["groups"]}
        assert any(item["title"] == f"DS{lead_tag}"
                   for item in groups["leads"]["items"])
        assert "leads" not in {g["key"] for g in client.as_user("viewer").get(
            "/api/dashboard/search", params={"q": lead_tag}).json()["groups"]}
    finally:
        with SessionLocal() as db:
            db.execute(delete(Lead).where(Lead.lead_no == f"DS{lead_tag}"))
            db.commit()

    assert admin.get("/api/dashboard/search", params={"q": "x"}).status_code == 422
    client.cookies.clear()
    assert client.get("/api/dashboard/search", params={"q": "ab"}).status_code == 401
    client.as_user("admin")


def test_expiry_buckets_are_disjoint_and_the_drilldown_agrees(client, world):
    from app.core.db import SessionLocal
    from app.models.core import Batch, Product

    tag = uuid4().hex[:6]
    today = date.today()
    offsets = {"expired": -1, "lt30": 10, "lt90": 60, "outside": 120}
    admin = client.as_user("admin")
    before = admin.get("/api/dashboard").json()["expiry_watch"]
    with SessionLocal() as db:
        product = Product(sku=f"EX{tag}", name=f"Expiry probe {tag}", pack_size="1",
                          mrp=Decimal("10"), hsn="30049099", uqc="NOS", status="active")
        db.add(product)
        db.flush()
        batches = {}
        for name, days in offsets.items():
            batch = Batch(product_id=product.id, warehouse_id=world["warehouse_id"],
                          batch_no=f"EX{tag}{name}", on_hand=Decimal("1"),
                          expiry=today + timedelta(days=days))
            db.add(batch)
            db.flush()
            batches[name] = batch.id
        db.commit()

    try:
        after = admin.get("/api/dashboard").json()["expiry_watch"]
        assert after["expired"] - before["expired"] == 1
        assert after["lt30"] - before["lt30"] == 1
        assert after["lt90"] - before["lt90"] == 1
        assert after["total"] - before["total"] == 3
        assert after["expired"] + after["lt30"] + after["lt90"] == after["total"]
        assert after["shown_of"] == after["total"]
        assert [r["days_left"] for r in after["rows"]] == sorted(
            r["days_left"] for r in after["rows"])

        for bucket in ("expired", "lt30", "lt90", "all"):
            r = admin.get("/api/dashboard/expiry", params={"bucket": bucket,
                                                          "page_size": 100})
            assert r.status_code == 200, r.text
            body = r.json()
            expected = 3 if bucket == "all" else 1
            probe = [row for row in body["rows"]
                     if row["batch_id"] in batches.values()]
            assert len(probe) == expected, (bucket, probe)
            assert body["total"] >= len(probe)
            days = [row["days_left"] for row in body["rows"]]
            assert days == sorted(days)
            for row in probe:
                assert row["value"] is None and row["value_gap"] == "GAP-D04"
                assert row["action"] and row["tone"]

        assert client.as_user("payroll").get(
            "/api/dashboard/expiry").status_code == 403
        assert client.as_user("viewer").get(
            "/api/dashboard/expiry").status_code == 200
    finally:
        client.as_user("admin")
        with SessionLocal() as db:
            db.execute(delete(Batch).where(Batch.id.in_(batches.values())))
            db.execute(delete(Product).where(Product.sku == f"EX{tag}"))
            db.commit()


def test_stock_history_is_exact_for_backdated_movements(client, world):
    from app.core.db import SessionLocal
    from app.models.core import Batch, StockMovement, User

    tag = uuid4().hex[:6]
    today = date.today()
    before_tile = _dash(client, range=7)["kpis"][0]
    before = dict(zip(before_tile["trend_points"], before_tile["trend"]))

    def at_noon(day):
        return datetime.combine(day, datetime.min.time().replace(hour=12),
                                tzinfo=IST).astimezone(timezone.utc)

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "t_admin"))
        batch = Batch(product_id=world["product_id"],
                      warehouse_id=world["warehouse_id"],
                      batch_no=f"SH{tag}", on_hand=Decimal("10"),
                      expiry=today + timedelta(days=400))
        db.add(batch)
        db.flush()
        db.add_all([
            StockMovement(batch_id=batch.id, movement_type="receipt",
                          qty_delta=Decimal("5"), ref_type="test",
                          ref_id=f"{tag}-old", actor_id=admin.id,
                          created_at=at_noon(today - timedelta(days=5))),
            StockMovement(batch_id=batch.id, movement_type="receipt",
                          qty_delta=Decimal("5"), ref_type="test",
                          ref_id=f"{tag}-new", actor_id=admin.id,
                          created_at=at_noon(today)),
        ])
        db.commit()
        batch_id = batch.id

    try:
        tile = _dash(client, range=7)["kpis"][0]
        after = dict(zip(tile["trend_points"], tile["trend"]))
        deltas = [round(after[p] - before[p], 3) for p in tile["trend_points"]]
        # End-of-day position: 0 until the first receipt, 5 after it, 10 today.
        assert deltas == [0, 5, 5, 5, 5, 5, 10]
    finally:
        with SessionLocal() as db:
            db.execute(delete(StockMovement).where(
                StockMovement.batch_id == batch_id))
            db.execute(delete(Batch).where(Batch.id == batch_id))
            db.commit()


def _invoice_for(client, world, qty="1", price="100.00"):
    """Raise, approve (if needed) and dispatch an order; return its invoice."""
    sales = client.as_user("sales")
    order = sales.post("/api/sales-orders", json={
        "distributor_id": world["distributor_id"],
        "lines": [{"sku": world["sku"], "qty": qty, "unit_price": price}]})
    assert order.status_code == 201, order.text
    order = order.json()
    submitted = sales.post(f"/api/sales-orders/{order['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    if submitted.json()["status"] == "pending_approval":
        approval_id = submitted.json()["approval"]["id"]
        assert client.as_user("admin").post(
            f"/api/approvals/{approval_id}/decide",
            json={"decision": "approve", "reason": "dashboard test"}).status_code == 200
    dispatched = client.as_user("admin").post(
        f"/api/sales-orders/{order['id']}/dispatch",
        json={"warehouse_id": world["warehouse_id"]})
    assert dispatched.status_code == 201, dispatched.text
    return next(i for i in client.as_user("admin").get("/api/invoices").json()
                if i["sales_order_id"] == order["id"])


def test_sales_top_products_and_ageing_reconcile_with_the_reports(client, world):
    from app.core.db import SessionLocal
    from app.models.core import Invoice, InvoiceLine

    before = _dash(client, range=30)
    before_sales = _dec(before["sales_vs_purchases"]["sales_total"])
    before_purchases = _dec(before["sales_vs_purchases"]["purchases_total"])

    invoice = _invoice_for(client, world)
    after = _dash(client, range=30)
    grand = _dec(invoice["grand_total"])
    assert _dec(after["sales_vs_purchases"]["sales_total"]) == before_sales + grand
    # A sale is not a purchase: the other series must not move.
    assert _dec(after["sales_vs_purchases"]["purchases_total"]) == before_purchases

    # The invoice register, built independently, must total the same figure.
    report = client.as_user("admin").get(
        "/api/reports/invoices", params={"from": after["from"], "to": after["to"]})
    assert report.status_code == 200, report.text
    register = sum((_dec(row["grand_total"]) for row in report.json()["tables"][0]["rows"]
                    if row["status"] == "issued"), Decimal(0))
    assert register == _dec(after["sales_vs_purchases"]["sales_total"])

    # Top products are the six largest taxable values, straight from the lines.
    with SessionLocal() as db:
        rows = db.execute(
            select(InvoiceLine.product_id, InvoiceLine.sku, InvoiceLine.product_name,
                   func.coalesce(func.sum(InvoiceLine.qty), 0),
                   func.coalesce(func.sum(InvoiceLine.taxable_value), 0))
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(Invoice.status == "issued",
                   Invoice.invoice_date >= date.fromisoformat(after["from"]),
                   Invoice.invoice_date <= date.fromisoformat(after["to"]))
            .group_by(InvoiceLine.product_id, InvoiceLine.sku,
                      InvoiceLine.product_name)
            .order_by(func.sum(InvoiceLine.taxable_value).desc(),
                      InvoiceLine.product_id.asc())
            .limit(6)).all()
    expected = [(pid, sku, name, _dec(qty), _dec(revenue))
                for pid, sku, name, qty, revenue in rows]
    actual = [(row["product_id"], row["sku"], row["name"], _dec(row["qty"]),
               _dec(row["revenue"])) for row in after["top_products"]["rows"]]
    assert actual == expected

    # Ageing on the dashboard is the same bucket table the report shows.
    ageing = _dash(client, "admin")["receivables_ageing"]
    report = client.as_user("admin").get("/api/reports/receivables_ageing").json()
    report_rows = {row["ageing_bucket"]: _dec(row["amount"])
                   for row in report["tables"][0]["rows"]}
    assert {b["key"]: _dec(b["amount"]) for b in ageing["buckets"]} == report_rows
    assert _dec(ageing["total"]) == _dec(report["tables"][0]["totals"]["amount"])
    assert ageing["count"] == sum(row["invoice_count"]
                                  for row in report["tables"][0]["rows"])


def test_open_po_progress_is_by_quantity(client, world):
    admin = client.as_user("admin")
    rows = admin.get("/api/dashboard").json()["open_pos"]["rows"]
    for row in rows:
        ordered = _dec(row["ordered_units"])
        received = _dec(row["received_units"])
        assert _dec(row["remaining_units"]) == max(ordered - received, Decimal(0))
        if ordered:
            assert row["pct_received"] == round(float(received / ordered * 100), 1)
        else:
            assert row["pct_received"] == 0.0


def test_activity_feed_is_permission_checked_and_totalled(client, world):
    admin = client.as_user("admin")
    feed = admin.get("/api/dashboard/activity", params={"limit": 3})
    assert feed.status_code == 200, feed.text
    body = feed.json()
    assert len(body["rows"]) <= 3
    assert body["shown"] == len(body["rows"])
    assert body["total"] >= body["shown"]
    assert client.as_user("sales").get("/api/dashboard/activity").status_code == 403


def test_hr_requests_are_self_scoped_outside_the_hr_roles(client, world):
    from app.core.db import SessionLocal
    from app.models.core import ApprovalRequest

    tag = uuid4().hex[:6]
    with SessionLocal() as db:
        db.add(ApprovalRequest(record_type="hr_leave", record_id=int(tag[:6], 16),
                               reasons=[], status="pending",
                               request_no=f"HRD{tag}", document_number=f"HRD{tag}",
                               subject="Dashboard scope probe",
                               requested_by=client.ids["viewer"],
                               detail={"subject": "Dashboard scope probe"}))
        db.commit()
        request_no = f"HRD{tag}"

    try:
        def count(who):
            body = _dash(client, who)["approvals"]
            return body["count"], {row["request_no"] for row in body["rows"]}

        admin_count, admin_rows = count("admin")
        assert request_no in admin_rows
        manager_count, _ = count("hr_manager")
        assert manager_count >= admin_count
        # A non-HR role that holds approval:read sees the queue, but not
        # somebody else's leave request. Compute the exact expected count.
        with SessionLocal() as db:
            expected = db.scalar(select(func.count()).where(
                ApprovalRequest.status == "pending",
                (~ApprovalRequest.record_type.like("hr\\_%", escape="\\"))
                | (ApprovalRequest.requested_by == client.ids["sales"])))
        sales_count, sales_rows = count("sales")
        assert request_no not in sales_rows
        assert sales_count == expected
        assert sales_count < admin_count
    finally:
        client.as_user("admin")
        with SessionLocal() as db:
            db.execute(delete(ApprovalRequest).where(
                ApprovalRequest.request_no == request_no))
            db.commit()


def test_health_uses_the_module_register_and_the_migration_head(client, world):
    from app.core import module_register

    health = _dash(client)["health"]
    totals = module_register.totals()
    assert health["modules"]["working"] == totals["working"]
    assert health["modules"]["counted"] == totals["counted"]
    assert health["schema"]["at_head"] is True
    assert health["backup"]["status"] == "not_recorded"
    assert health["backup"]["gap"] == "GAP-D09"
    assert isinstance(health["alerts"]["configured"], bool)
