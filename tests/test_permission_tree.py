"""Parent-child permission rules, enforced in the catalogue and on the server.

The rules under test:

* every catalogue key has an explicit parent (or is a top-level module gate);
* a child is unusable without its parent, including through /api/auth/me;
* a role save drops a child whose parent was not selected;
* an Administrator-only key can never be stored on another role;
* the route gate follows the same effective set the browser is given.
"""
from uuid import uuid4

from sqlalchemy import select

from app.core.permissions import (ADMIN_ONLY_PERMISSIONS, PERMISSION_KEYS,
                                  PERMISSION_PARENT, PERMISSIONS,
                                  effective_permissions, sanitized_permissions)


def test_every_catalogue_key_declares_a_parent():
    assert set(PERMISSION_PARENT) == set(PERMISSIONS)
    assert not (PERMISSION_PARENT.keys() - PERMISSION_KEYS)
    for key, parent in PERMISSION_PARENT.items():
        assert parent is None or parent in PERMISSION_KEYS, (key, parent)


def test_parent_links_have_no_cycle():
    for key in PERMISSION_PARENT:
        seen, node = {key}, PERMISSION_PARENT[key]
        while node:
            assert node not in seen, f"cycle at {key}"
            seen.add(node)
            node = PERMISSION_PARENT[node]


def test_admin_only_keys_are_real_catalogue_keys():
    assert ADMIN_ONLY_PERMISSIONS <= PERMISSION_KEYS


def test_effective_permissions_drop_an_orphan_child():
    assert effective_permissions({"product:write"}) == set()
    assert effective_permissions({"product:read"}) == {"product:read"}
    assert effective_permissions({"product:read", "product:write"}) == {
        "product:read", "product:write"}


def test_sanitize_keeps_only_explicitly_selected_keys_with_parents():
    kept, dropped = sanitized_permissions(
        {"product:read", "product:write", "sales:write", "not:a:key"})
    assert kept == ["product:read", "product:write"]
    assert dropped == ["sales:write"]
    # Selecting a parent never grants its children.
    kept, dropped = sanitized_permissions({"product:read"})
    assert kept == ["product:read"] and dropped == []


def test_catalog_exposes_parent_and_admin_only(client):
    body = client.get("/api/roles/permissions").json()
    items = {item["key"]: item for group in body for item in group["items"]}
    assert items["product:write"]["parent"] == "product:read"
    assert items["product:read"]["parent"] is None
    assert items["db:reset"]["admin_only"] is True
    assert items["sales:write"]["admin_only"] is False


def test_role_save_drops_child_when_parent_is_not_selected(client):
    name = f"tree_{uuid4().hex[:8]}"
    res = client.post("/api/roles", json={
        "name": name, "display_name": "Tree test",
        "permissions": ["product:write", "sales:write"]})
    assert res.status_code == 201, res.text
    assert res.json()["permissions"] == []
    assert res.json()["effective_permissions"] == []


def test_non_admin_role_cannot_hold_an_admin_only_key(client):
    res = client.post("/api/roles", json={
        "name": f"money_{uuid4().hex[:8]}", "display_name": "Money test",
        "permissions": ["approval:read", "approval:credit_limit"]})
    assert res.status_code == 422
    assert "Administrator" in res.json()["detail"]


def test_administrator_role_cannot_drop_an_admin_only_key(client):
    roles = {r["name"]: r for r in client.get("/api/roles").json()}
    admin = roles["admin"]
    kept = [p for p in admin["permissions"] if p != "email:manage"]
    res = client.patch(f"/api/roles/{admin['id']}", json={"permissions": kept})
    assert res.status_code == 422
    assert "email:manage" in res.json()["detail"]


def test_route_gate_honours_the_parent(client):
    """A role granted only the child is refused; adding the parent opens it."""
    suffix = uuid4().hex[:8]
    role = client.post("/api/roles", json={
        "name": f"prod_{suffix}", "display_name": "Product viewer",
        "permissions": ["product:read", "product:write"]}).json()
    user = client.post("/api/users", json={
        "username": f"p_{suffix}", "role": str(role["id"])})
    assert user.status_code == 201, user.text
    username = user.json()["username"]
    password = user.json()["temporary_password"]

    # A fresh client: the shared fixture's manual cookie would shadow the
    # cookie the login response sets.
    from fastapi.testclient import TestClient
    from app.main import app
    as_new = TestClient(app, base_url="https://testserver")
    login = as_new.post("/api/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    assert "product:read" in login.json()["permissions"]
    assert as_new.get("/api/auth/me").json()["username"] == username
    changed = as_new.post("/api/auth/change-password", json={
        "current_password": password, "new_password": "TreePass!12345"})
    assert changed.status_code == 200, changed.text
    assert as_new.get("/api/products").status_code == 200

    client.cookies.clear()
    client.as_user("admin")
    res = client.patch(f"/api/roles/{role['id']}", json={
        "permissions": ["product:write"]})
    assert res.status_code == 200, res.text
    assert res.json()["permissions"] == []

    as_new.cookies.clear()
    login = as_new.post("/api/auth/login", json={
        "username": username, "password": "TreePass!12345"})
    assert login.status_code == 200, login.text
    assert login.json()["permissions"] == []
    assert as_new.get("/api/products").status_code == 403


def test_me_reports_the_effective_set_not_the_stored_orphan(client):
    from app.core.db import SessionLocal
    from app.core.security import make_token
    from app.models.core import User
    from app.models.users import Role
    from app.models.users import Employee

    name = f"orphan_{uuid4().hex[:8]}"
    with SessionLocal() as db:
        role = Role(name=name, display_name="Orphan", is_system=False,
                    permissions=["sales:write"])
        db.add(role)
        db.flush()
        employee = Employee(code=f"OR_{uuid4().hex[:6].upper()}", full_name="Orphan Test",
                            status="active")
        db.add(employee)
        db.flush()
        user = User(username=name, username_key=name, password_hash="x",
                    role=name, role_id=role.id, employee_id=employee.id)
        db.add(user)
        db.commit()
        token = make_token(user.id, user.token_version or 1)

    client.cookies.set("session", token)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["permissions"] == []
    assert client.get("/api/sales-orders").status_code == 403
