"""WP-3 list standard: server filters, paging totals and sorting contracts.

Every list screen now asks the server for one page and prints the server's
X-Total-Count. These tests pin the contract each screen depends on: a filter
changes both rows and total, omitting `page` is the export read, and sorting is
only offered where the endpoint accepts it.
"""
from uuid import uuid4


def _product(client, **over):
    sku = over.pop("sku", f"LS-{uuid4().hex[:6].upper()}")
    body = {"sku": sku, "name": "List standard product", "pack_size": "1 strip",
            "mrp": "150.00", "hsn": "30049099"}
    body.update(over)
    r = client.post("/api/products", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _order(client, world, qty="1"):
    r = client.post("/api/sales-orders", json={
        "distributor_id": world["distributor_id"],
        "lines": [{"sku": world["sku"], "qty": qty, "unit_price": "100.00"}]})
    assert r.status_code == 201, r.text
    return r.json()


def _invoice(client, world):
    sales = client.as_user("sales")
    order = _order(sales, world)
    submitted = sales.post(f"/api/sales-orders/{order['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    if submitted.json()["status"] == "pending_approval":
        admin = client.as_user("admin")
        admin.post(f"/api/approvals/{submitted.json()['approval']['id']}/decide",
                   json={"decision": "approve", "reason": "list standard setup"})
    admin = client.as_user("admin")
    dispatched = admin.post(f"/api/sales-orders/{order['id']}/dispatch",
                            json={"warehouse_id": world["warehouse_id"]})
    assert dispatched.status_code == 201, dispatched.text
    invoices = admin.get("/api/invoices").json()
    return next(i for i in invoices if i["sales_order_id"] == order["id"])


def test_products_sort_and_direction(client):
    high = _product(client, name="LIST sortable high", mrp="900.00")
    low = _product(client, name="LIST sortable low", mrp="100.00")
    base = {"q": "LIST sortable", "sort": "mrp", "page_size": 50}

    asc = client.get("/api/products", params={**base, "direction": "asc"})
    assert asc.status_code == 200, asc.text
    ids = [p["id"] for p in asc.json()]
    assert ids.index(low["id"]) < ids.index(high["id"])

    desc = client.get("/api/products", params={**base, "direction": "desc"})
    assert desc.status_code == 200, desc.text
    ids = [p["id"] for p in desc.json()]
    assert ids.index(high["id"]) < ids.index(low["id"])

    # An unknown column falls back to the default order instead of breaking the page.
    fallback = client.get("/api/products", params={**base, "sort": "not_a_column"})
    assert fallback.status_code == 200
    assert int(fallback.headers["X-Total-Count"]) == 2

    # Direction is a closed vocabulary: anything else is a client error.
    assert client.get("/api/products",
                      params={**base, "direction": "sideways"}).status_code == 422


def test_supplier_incomplete_filter_and_search(client):
    from app.core.db import SessionLocal
    from app.models.suppliers import Supplier

    code = f"INC-{uuid4().hex[:6].upper()}"
    with SessionLocal() as db:
        db.add(Supplier(code=code, name="Incomplete supplier", status="active",
                        needs_completion=True))
        db.commit()

    pending = client.get("/api/suppliers", params={"incomplete": "true", "q": code})
    assert pending.status_code == 200
    assert pending.headers["X-Total-Count"] == "1"
    assert pending.json()[0]["code"] == code
    assert pending.json()[0]["needs_completion"] is True

    done = client.get("/api/suppliers", params={"incomplete": "false", "q": code})
    assert done.status_code == 200
    assert done.json() == []
    assert done.headers["X-Total-Count"] == "0"

    unmatched = client.get("/api/suppliers", params={"q": "NO-SUCH-SUPPLIER"})
    assert unmatched.json() == []
    assert unmatched.headers["X-Total-Count"] == "0"


def test_distributor_incomplete_filter(client):
    code = f"DI-{uuid4().hex[:6].upper()}"
    created = client.post("/api/distributors", json={
        "code": code, "name": "Unplaced buyer", "territory": "Test",
        "registration_type": "unregistered"})
    assert created.status_code == 201, created.text
    assert created.json()["needs_completion"] is True

    pending = client.get("/api/distributors", params={"incomplete": "true", "q": code})
    assert pending.status_code == 200
    assert pending.headers["X-Total-Count"] == "1"
    assert pending.json()[0]["code"] == code

    done = client.get("/api/distributors", params={"incomplete": "false", "q": code})
    assert done.json() == []
    assert done.headers["X-Total-Count"] == "0"


def test_sales_order_search_and_page_total(client, world):
    sales = client.as_user("sales")
    order = _order(sales, world)

    by_number = sales.get("/api/sales-orders",
                          params={"q": order["so_number"], "page": 1, "page_size": 1})
    assert by_number.status_code == 200
    assert by_number.headers["X-Total-Count"] == "1"
    assert [o["so_number"] for o in by_number.json()] == [order["so_number"]]

    by_buyer = sales.get("/api/sales-orders", params={"q": "Test distributor"})
    assert by_buyer.status_code == 200
    assert any(o["id"] == order["id"] for o in by_buyer.json())
    assert len(by_buyer.json()) == int(by_buyer.headers["X-Total-Count"])

    none = sales.get("/api/sales-orders", params={"q": "NO-SUCH-ORDER"})
    assert none.json() == []
    assert none.headers["X-Total-Count"] == "0"


def test_purchase_order_search_and_page_total(client, world):
    created = client.post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"],
        "lines": [{"sku": world["sku"], "qty": "2", "unit_cost": "90.00"}]})
    assert created.status_code == 201, created.text
    po = created.json()

    by_number = client.get("/api/purchase-orders",
                           params={"q": po["po_number"], "page": 1, "page_size": 1})
    assert by_number.status_code == 200
    assert by_number.headers["X-Total-Count"] == "1"
    assert [p["po_number"] for p in by_number.json()] == [po["po_number"]]

    by_supplier = client.get("/api/purchase-orders", params={"q": "Test supplier"})
    assert by_supplier.status_code == 200
    assert any(p["id"] == po["id"] for p in by_supplier.json())
    assert len(by_supplier.json()) == int(by_supplier.headers["X-Total-Count"])


def test_invoice_search_and_page_total(client, world):
    invoice = _invoice(client, world)

    r = client.get("/api/invoices",
                   params={"q": invoice["invoice_number"], "page": 1, "page_size": 1})
    assert r.status_code == 200
    assert r.headers["X-Total-Count"] == "1"
    assert [i["invoice_number"] for i in r.json()] == [invoice["invoice_number"]]

    by_buyer = client.get("/api/invoices", params={"q": invoice["buyer_name"]})
    assert by_buyer.status_code == 200
    assert any(i["id"] == invoice["id"] for i in by_buyer.json())
    assert len(by_buyer.json()) == int(by_buyer.headers["X-Total-Count"])


def test_approvals_decided_filter(client, world):
    sales = client.as_user("sales")
    order = _order(sales, world, qty="100")
    submitted = sales.post(f"/api/sales-orders/{order['id']}/submit").json()
    approval_id = submitted["approval"]["id"]
    admin = client.as_user("admin")
    decided = admin.post(f"/api/approvals/{approval_id}/decide",
                         json={"decision": "approve", "reason": "list standard"})
    assert decided.status_code == 200, decided.text

    done = admin.get("/api/approvals", params={"decided": "true", "page_size": 200})
    assert done.status_code == 200
    assert all(a["status"] != "pending" for a in done.json())
    assert any(a["id"] == approval_id for a in done.json())
    assert len(done.json()) == int(done.headers["X-Total-Count"])

    waiting = admin.get("/api/approvals", params={"decided": "false", "page_size": 200})
    assert all(a["status"] == "pending" for a in waiting.json())
    assert len(waiting.json()) == int(waiting.headers["X-Total-Count"])


def test_approval_total_matches_visible_rows_for_restricted_role(client):
    """X-Total-Count must describe the rows this role may see, not the table.

    A leave request raised by the Administrator is invisible to the sales desk.
    Before this contract the paged total counted it and overstated the list.
    """
    from app.core.db import SessionLocal
    from app.models.core import ApprovalRequest

    with SessionLocal() as db:
        db.add(ApprovalRequest(
            record_type="hr_leave", record_id=uuid4().int % 10**9 + 1_000_000_000,
            reasons=[], status="pending",
            request_no=f"VIS-{uuid4().hex[:6].upper()}", document_number="HR-VIS-1",
            subject="Invisible to sales", requested_by=client.ids["admin"],
            pending_approver_role="hr_manager",
            detail={"employee_id": client.employee_ids["admin"]}))
        db.commit()

    sales = client.as_user("sales")
    everything = sales.get("/api/approvals", params={"page_size": 200})
    assert everything.status_code == 200, everything.text
    assert all(a["request_type"] != "hr_leave" for a in everything.json())

    one = sales.get("/api/approvals", params={"page": 1, "page_size": 1})
    assert one.status_code == 200
    assert len(one.json()) == 1
    assert int(one.headers["X-Total-Count"]) == len(everything.json())


def test_approval_detail_uses_the_list_visibility(client):
    """The pager can open an older request by id; that read must obey the same
    visibility rule as the list, not become a way around it."""
    from app.core.db import SessionLocal
    from app.models.core import ApprovalRequest

    with SessionLocal() as db:
        row = ApprovalRequest(
            record_type="hr_leave", record_id=uuid4().int % 10**9 + 1_000_000_000,
            reasons=[], status="pending",
            request_no=f"VIS-{uuid4().hex[:6].upper()}", document_number="HR-VIS-2",
            subject="Detail visibility", requested_by=client.ids["admin"],
            pending_approver_role="hr_manager",
            detail={"employee_id": client.employee_ids["admin"]})
        db.add(row)
        db.commit()
        approval_id = row.id

    admin = client.as_user("admin")
    mine = admin.get(f"/api/approvals/{approval_id}")
    assert mine.status_code == 200, mine.text
    assert mine.json()["id"] == approval_id

    sales = client.as_user("sales")
    assert sales.get(f"/api/approvals/{approval_id}").status_code == 404
    assert sales.get("/api/approvals/99999999").status_code == 404


def test_export_read_is_unpaged_on_every_list(client, world):
    """Every screen's Export drops `page`; the server must answer with all
    matching rows, and X-Total-Count must agree with what was sent."""
    sales = client.as_user("sales")
    for _ in range(3):
        _order(sales, world)

    first = sales.get("/api/sales-orders", params={"page": 1, "page_size": 1})
    assert len(first.json()) == 1
    every = sales.get("/api/sales-orders")
    assert len(every.json()) == int(every.headers["X-Total-Count"]) >= 3

    admin = client.as_user("admin")
    supplier_page = admin.get("/api/suppliers", params={"page": 1, "page_size": 1})
    assert len(supplier_page.json()) == 1
    suppliers = admin.get("/api/suppliers")
    assert len(suppliers.json()) == int(suppliers.headers["X-Total-Count"]) >= 1


def test_lead_server_filters_match_the_screen(client, world):
    from datetime import date

    sales = client.as_user("sales")
    made = sales.post("/api/leads", json={
        "name": "List standard lead", "company": "List standard co",
        "phone": f"9{uuid4().int % 10**9:09d}", "source": "referral",
        "next_follow_up": date.today().isoformat()})
    assert made.status_code == 201, made.text

    today = sales.get("/api/leads", params={"due": "today", "q": "List standard",
                                            "page": 1, "page_size": 1})
    assert today.status_code == 200
    assert len(today.json()) == 1
    assert today.headers["X-Total-Count"] == "1"

    closed = sales.get("/api/leads", params={"status": "closed", "q": "List standard"})
    assert closed.json() == []
    assert closed.headers["X-Total-Count"] == "0"


LIST_SCREENS = [
    ("/api/suppliers", "admin"),
    ("/api/distributors", "admin"),
    ("/api/sales-orders", "sales"),
    ("/api/purchase-orders", "admin"),
    ("/api/invoices", "admin"),
    ("/api/approvals", "admin"),
    ("/api/leads", "sales"),
]


def test_every_list_pages_on_the_server(client, world):
    """Each batch-2 screen returns one server page with one total.

    The page on screen, the next page and the unpaged export read must agree on
    X-Total-Count, the pages must not overlap, and a size the footer never sends
    must be refused instead of silently accepted.
    """
    from datetime import date

    sales = client.as_user("sales")
    admin = client.as_user("admin")

    sales.post("/api/leads", json={
        "name": "List paging lead", "company": "List paging co",
        "phone": f"8{uuid4().int % 10**9:09d}", "source": "referral",
        "next_follow_up": date.today().isoformat()})
    made_supplier = admin.post("/api/suppliers", json={
        "code": f"LSP-{uuid4().hex[:6].upper()}", "name": "List paging supplier",
        "registration_type": "unregistered", "state_code": "27"})
    assert made_supplier.status_code == 201, made_supplier.text
    made_buyer = admin.post("/api/distributors", json={
        "code": f"LSC-{uuid4().hex[:6].upper()}", "name": "List paging buyer",
        "territory": "Test", "registration_type": "unregistered"})
    assert made_buyer.status_code == 201, made_buyer.text
    made_po = admin.post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"],
        "lines": [{"sku": world["sku"], "qty": "1", "unit_cost": "80.00"}]})
    assert made_po.status_code == 201, made_po.text
    big = _order(sales, world, qty="100")
    submitted = sales.post(f"/api/sales-orders/{big['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "pending_approval"
    _invoice(client, world)

    for url, role in LIST_SCREENS:
        reader = client.as_user(role)
        first = reader.get(url, params={"page": 1, "page_size": 1})
        assert first.status_code == 200, (url, first.text)
        total = int(first.headers["X-Total-Count"])
        assert total >= 1, url
        assert len(first.json()) == 1, url

        every = reader.get(url)
        assert len(every.json()) == total, url
        assert int(every.headers["X-Total-Count"]) == total, url

        second = reader.get(url, params={"page": 2, "page_size": 1})
        assert second.status_code == 200, url
        assert int(second.headers["X-Total-Count"]) == total, url
        if total > 1:
            assert second.json()[0]["id"] != first.json()[0]["id"], url
        else:
            assert second.json() == [], url

        assert reader.get(url, params={"page": 1, "page_size": 200}).status_code == 200
        assert reader.get(url, params={"page": 1, "page_size": 201}).status_code == 422
