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
