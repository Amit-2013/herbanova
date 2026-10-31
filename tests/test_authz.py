"""Server-side authorisation and session tests.

The browser hides controls, but only the server decides. These tests exercise
the actual gates: authentication, permission denial, the Administrator role
check that a permission cannot buy, database-backed role edits without a new
token, the baseline fallback, deactivation, and the forced password change with
its session revocation.
"""
from uuid import uuid4


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _make_user(*, role_name: str, permissions: list[str] | None = None,
               with_role_id: bool = True, password: str = "TempPass!123",
               must_change: bool = False, active: bool = True):
    """Create a login directly in the test database and return (username, token, id)."""
    from app.core.db import SessionLocal
    from app.core.security import hash_password, make_token
    from app.models.core import User
    from app.models.users import Employee, Role
    from sqlalchemy import select

    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == role_name))
        role_id = None
        if with_role_id:
            if role is None:
                role = Role(name=role_name, display_name=role_name,
                            is_system=False, permissions=list(permissions or []))
                db.add(role)
                db.flush()
            elif permissions is not None:
                role.permissions = list(permissions)
            role_id = role.id
        employee = Employee(code=_unique("AZ").upper()[:30], full_name="Authorisation test",
                            status="active")
        db.add(employee)
        db.flush()
        username = _unique("az")
        user = User(username=username, username_key=username,
                    password_hash=hash_password(password), role=role_name,
                    role_id=role_id, employee_id=employee.id,
                    must_change_password=must_change, is_active=active)
        db.add(user)
        db.flush()
        token = make_token(user.id, user.token_version or 1)
        user_id = user.id
        db.commit()
    return username, token, user_id


def test_every_business_route_requires_authentication():
    from fastapi.testclient import TestClient
    from app.main import app
    anonymous = TestClient(app)
    for path in ("/api/products", "/api/users", "/api/audit", "/api/dashboard"):
        assert anonymous.get(path).status_code == 401, path


def test_permission_denial_is_403(client):
    viewer = client.as_user("viewer")
    assert viewer.get("/api/products").status_code == 200
    denied = viewer.post("/api/products", json={
        "sku": _unique("DENY").upper(), "name": "Denied product", "pack_size": "1",
        "mrp": "10.00", "hsn": "30049099", "uqc": "NOS"})
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Permission denied"
    assert viewer.get("/api/users").status_code == 403


def test_permission_does_not_confer_the_administrator_role(client):
    # A custom role can hold the same permission key as the Administrator...
    _, token, _ = _make_user(role_name="billing_clerk",
                             permissions=["invoice:cancel", "invoice:edit_post_billing"])
    client.cookies.set("session", token)
    # ...and passes a plain permission gate (the route answers 405, its own rule).
    assert client.delete("/api/invoices/1").status_code == 405
    # ...but the Administrator gate still refuses the post-billing edit.
    refused = client.patch("/api/invoices/1/movement",
                           json={"delivery_challan_number": "DC-TEST", "reason": "test"})
    assert refused.status_code == 403
    assert "Administrator" in refused.json()["detail"]


def test_database_role_edits_take_effect_without_a_new_token(client):
    role_name = _unique("flip")
    _, token, _ = _make_user(role_name=role_name, permissions=["product:read"])
    client.cookies.set("session", token)
    assert client.get("/api/products").status_code == 200

    from app.core.db import SessionLocal
    from app.models.users import Role
    from sqlalchemy import select
    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == role_name))
        role.permissions = []
        db.commit()
    assert client.get("/api/products").status_code == 403

    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == role_name))
        role.permissions = ["product:read"]
        db.commit()
    assert client.get("/api/products").status_code == 200


def test_user_without_a_role_id_uses_the_frozen_baseline(client):
    _, token, _ = _make_user(role_name="viewer", with_role_id=False)
    client.cookies.set("session", token)
    assert client.get("/api/products").status_code == 200     # viewer baseline
    assert client.get("/api/users").status_code == 403

    _, token, _ = _make_user(role_name="no_such_role", with_role_id=False)
    client.cookies.set("session", token)
    assert client.get("/api/products").status_code == 403     # unknown role fails closed


def test_deactivated_account_loses_its_session(client):
    _, token, user_id = _make_user(role_name="viewer")
    client.cookies.set("session", token)
    assert client.get("/api/auth/me").status_code == 200

    from app.core.db import SessionLocal
    from app.models.core import User
    with SessionLocal() as db:
        db.get(User, user_id).is_active = False
        db.commit()
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/products").status_code == 401


def test_forced_password_change_gates_data_and_revokes_the_old_token():
    # HTTPS so the production Secure cookie flag is exercised, not bypassed.
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, base_url="https://testserver")
    username, _, _ = _make_user(role_name="viewer", must_change=True)
    password = "TempPass!123"

    logged_in = c.post("/api/auth/login",
                       json={"username": username, "password": password})
    assert logged_in.status_code == 200, logged_in.text
    assert logged_in.json()["must_change_password"] is True
    old_token = c.cookies.get("session")

    # Only the three allowed endpoints answer while the temporary password stands.
    assert c.get("/api/auth/me").status_code == 200
    blocked = c.get("/api/products")
    assert blocked.status_code == 403
    assert "change your password" in blocked.json()["detail"].lower()

    # Policy and current-password checks are server-side.
    assert c.post("/api/auth/change-password", json={
        "current_password": "wrong-password", "new_password": "NewPass!1234"}).status_code == 400
    assert c.post("/api/auth/change-password", json={
        "current_password": password, "new_password": "too-short"}).status_code == 422
    assert c.post("/api/auth/change-password", json={
        "current_password": password, "new_password": password}).status_code == 400

    changed = c.post("/api/auth/change-password", json={
        "current_password": password, "new_password": "NewPass!1234"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["must_change_password"] is False
    assert "product:read" in changed.json()["permissions"]
    assert c.get("/api/products").status_code == 200

    # The session held before the change is revoked by the token_version bump.
    c.cookies.clear()
    c.cookies.set("session", old_token)
    assert c.get("/api/auth/me").status_code == 401

    # The new password is the one that now works.
    c.cookies.clear()
    relogin = c.post("/api/auth/login",
                     json={"username": username, "password": "NewPass!1234"})
    assert relogin.status_code == 200
    assert relogin.json()["must_change_password"] is False
