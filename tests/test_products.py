from uuid import uuid4


def _valid(**over):
    sku = over.pop("sku", f"TP-{uuid4().hex[:6].upper()}")
    body = {"sku": sku, "name": "New product", "pack_size": "1 strip",
            "mrp": "120.00", "hsn": "30049099", "uqc": "STR"}
    body.update(over)
    return sku, body


def test_hsn_is_required_and_digits_only(client):
    _, body = _valid()
    body.pop("hsn")
    assert client.post("/api/products", json=body).status_code == 422
    body["hsn"] = "ABC12"
    assert client.post("/api/products", json=body).status_code == 422


def test_create_read_edit_product_keeps_hsn(client, world):
    sku, body = _valid()
    created = client.post("/api/products", json=body)
    assert created.status_code == 201, created.text
    product = created.json()
    assert product["hsn"] == "30049099"
    assert product["uqc"] == "STR"

    found = client.get("/api/products", params={"q": body["hsn"], "page": 1, "page_size": 50})
    assert found.status_code == 200
    assert found.headers["X-Total-Count"].isdigit()
    row = next(p for p in found.json() if p["id"] == product["id"])
    assert row["hsn"] == body["hsn"]

    edited = client.patch(f"/api/products/{product['id']}",
                          json={"hsn": "30041010", "pack_size": "2 strips"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["hsn"] == "30041010"

    reopened = client.get("/api/products", params={"q": sku}).json()
    assert reopened[0]["hsn"] == "30041010"


def test_product_list_is_paginated(client):
    for _ in range(3):
        _, body = _valid()
        assert client.post("/api/products", json=body).status_code == 201
    r = client.get("/api/products", params={"page": 1, "page_size": 1})
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert int(r.headers["X-Total-Count"]) >= 3


def test_product_write_needs_permission(client, world):
    sales = client.as_user("sales")
    _, body = _valid()
    assert sales.post("/api/products", json=body).status_code == 403
    client.as_user("admin")
