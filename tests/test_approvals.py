def _order(client, world, qty="100"):
    r = client.post("/api/sales-orders", json={
        "distributor_id": world["distributor_id"],
        "lines": [{"sku": world["sku"], "qty": qty, "unit_price": "100.00"}]})
    assert r.status_code == 201, r.text
    return r.json()


def _invoice_for(client, world):
    # The sales desk raises the order; the administrator approves and dispatches it.
    # Raising it as admin would make a credit-limit approval impossible, because
    # nobody may decide a request they raised.
    sales = client.as_user("sales")
    order = _order(sales, world, qty="1")
    submitted = sales.post(f"/api/sales-orders/{order['id']}/submit")
    assert submitted.status_code == 200
    if submitted.json()["status"] == "pending_approval":
        admin = client.as_user("admin")
        approval_id = submitted.json()["approval"]["id"]
        assert admin.post(f"/api/approvals/{approval_id}/decide",
                          json={"decision": "approve", "reason": "test setup"}).status_code == 200
    admin = client.as_user("admin")
    dispatched = admin.post(f"/api/sales-orders/{order['id']}/dispatch",
                            json={"warehouse_id": world["warehouse_id"]})
    assert dispatched.status_code == 201, dispatched.text
    invoice = admin.get("/api/invoices").json()
    return next(i for i in invoice if i["sales_order_id"] == order["id"])


def test_credit_limit_approval_is_admin_only(client, world):
    sales = client.as_user("sales")
    order = _order(sales, world)
    submitted = sales.post(f"/api/sales-orders/{order['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["status"] == "pending_approval"
    assert "credit_limit" in body["approval"]["reasons"]
    approval_id = body["approval"]["id"]

    # The sales desk can see the queue but cannot decide.
    queue = sales.get("/api/approvals", params={"status": "pending"})
    assert queue.status_code == 200
    sales_row = next(a for a in queue.json() if a["id"] == approval_id)
    assert sales_row["pending_approver_role"] == "admin"
    assert sales.post(f"/api/approvals/{approval_id}/decide",
                      json={"decision": "approve", "reason": "denied"}).status_code == 403

    # Another non-admin role is refused too, even with approval:read.
    inventory = client.as_user("inventory")
    assert inventory.post(f"/api/approvals/{approval_id}/decide",
                          json={"decision": "approve", "reason": "denied"}).status_code == 403

    admin = client.as_user("admin")
    decided = admin.post(f"/api/approvals/{approval_id}/decide",
                         json={"decision": "approve", "reason": "Limit temporarily raised"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"
    assert decided.json()["decided_by"] == "t_admin"
    assert admin.get(f"/api/sales-orders/{order['id']}").json()["status"] == "approved"

    # A request can be decided only once.
    again = admin.post(f"/api/approvals/{approval_id}/decide",
                       json={"decision": "reject", "reason": "changed my mind"})
    assert again.status_code == 409


def test_admin_cannot_decide_their_own_credit_request(client, world):
    admin = client.as_user("admin")
    order = _order(admin, world)
    submitted = admin.post(f"/api/sales-orders/{order['id']}/submit").json()
    approval_id = submitted["approval"]["id"]
    r = admin.post(f"/api/approvals/{approval_id}/decide",
                   json={"decision": "approve", "reason": "self approval"})
    assert r.status_code == 403
    assert "cannot decide" in r.json()["detail"]


def test_post_billing_edit_is_admin_only(client, world):
    sales = client.as_user("sales")
    invoice = _invoice_for(sales, world)
    sales = client.as_user("sales")

    requested = sales.post(f"/api/approvals/post-billing/{invoice['id']}", json={
        "reason": "Transporter corrected the challan number",
        "changes": {"delivery_challan_number": "DC-CORRECTED", "grand_total": "1"}})
    assert requested.status_code == 201, requested.text
    approval = requested.json()
    assert approval["request_type"] == "invoice_post_billing"
    assert approval["pending_approver_role"] == "admin"
    # Only permitted fields are carried into the request.
    assert "grand_total" not in approval["detail"]["changes"]

    assert sales.post(f"/api/approvals/{approval['id']}/decide",
                      json={"decision": "approve", "reason": "fine"}).status_code == 403

    admin = client.as_user("admin")
    decided = admin.post(f"/api/approvals/{approval['id']}/decide",
                         json={"decision": "approve", "reason": "Checked with transporter"})
    assert decided.status_code == 200, decided.text
    updated = next(i for i in admin.get("/api/invoices").json() if i["id"] == invoice["id"])
    assert updated["delivery_challan_number"] == "DC-CORRECTED"
    assert updated["grand_total"] == invoice["grand_total"]
