"""WP-4b: the read-only navigation API.

What this file proves, against the migrated test database:

* `/api/navigation` requires a session and returns only screens the caller may
  open, already narrowed by role permissions and feature switches;
* empty branches are pruned, so a closed module's name is not disclosed;
* Home is always present and is the protected `dash` screen;
* the `distributors` alias travels with the `customers` screen and disappears
  with it;
* the ETag is per user, unchanged input returns 304 with no body, and a
  permission or a feature-switch change invalidates it;
* a GET writes nothing (no navigation, feature or audit row);
* an invalid or missing registry returns 503, never a partial tree;
* the administrative read endpoint is Administrator-only and read-only.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.features import FEATURE_KEYS
from app.core.permissions import BASELINE_ROLE_PERMS
from app.models.core import AuditLog, User
from app.models.navigation import FeatureRegistry, NavNode
from app.models.settings import FeatureFlag
from app.models.users import Employee, Role

HR_MANAGER_PERMS = {"hr:read", "hr:write", "hr:attendance_self",
                    "hr:attendance_manage", "hr:leave_approve", "hr:reports",
                    "hr:confidential", "approval:read"}

ROLE_VIEWS = {
    "admin": ["dash", "compare", "leads", "lost", "followups", "sales", "billing",
              "approvals", "customers", "purchasing", "suppliers", "products",
              "inventory", "foc", "accounts", "expenses", "tax", "reports",
              "scheduled", "geo", "hr", "users", "roles", "audit", "settings"],
    "sales": ["dash", "compare", "leads", "lost", "followups", "sales", "billing",
              "approvals", "customers", "purchasing", "products", "inventory",
              "accounts", "tax", "reports", "geo", "hr", "settings"],
    "inventory": ["dash", "compare", "sales", "billing", "approvals", "customers",
                  "purchasing", "suppliers", "products", "inventory", "foc", "tax",
                  "reports", "geo", "hr", "settings"],
    "viewer": ["dash", "compare", "sales", "billing", "customers", "purchasing",
               "products", "inventory", "foc", "reports", "geo", "hr", "settings"],
    "hr_manager": ["dash", "approvals", "reports", "hr", "settings"],
}

ROLE_MODULES = {
    "admin": ["overview", "sales", "stock", "finance", "people"],
    "sales": ["overview", "sales", "stock", "finance", "people"],
    "inventory": ["overview", "sales", "stock", "finance", "people"],
    "viewer": ["overview", "sales", "stock", "finance", "people"],
    "hr_manager": ["overview", "sales", "finance", "people"],   # stock is empty
}

ROLE_PERMS = {
    "admin": BASELINE_ROLE_PERMS["admin"],
    "sales": BASELINE_ROLE_PERMS["sales"],
    "inventory": BASELINE_ROLE_PERMS["inventory"],
    "viewer": BASELINE_ROLE_PERMS["viewer"],
    "hr_manager": HR_MANAGER_PERMS,
}


def _screens(body: dict) -> list[dict]:
    return [screen
            for module in body["modules"]
            for category in module["categories"]
            for group in category["groups"]
            for screen in group["screens"]]


def _views(body: dict) -> list[str]:
    return [screen["view"] for screen in _screens(body)]


@pytest.fixture()
def restore_flags():
    yield
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        db.execute(delete(FeatureFlag))
        db.commit()


@pytest.fixture()
def restore_dependency():
    yield
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        row = db.get(FeatureRegistry, "foc")
        row.depends_on = []
        db.commit()


def test_requires_authentication():
    from app.main import app
    with TestClient(app) as anonymous:
        res = anonymous.get("/api/navigation")
    assert res.status_code == 401


@pytest.mark.parametrize("role", list(ROLE_VIEWS))
def test_role_sees_exactly_its_authorised_screens(client, role):
    client.as_user(role)
    res = client.get("/api/navigation")
    assert res.status_code == 200, res.text
    body = res.json()

    assert _views(body) == ROLE_VIEWS[role]
    assert [module["node_key"] for module in body["modules"]] == ROLE_MODULES[role]

    assert body["permissions"] == sorted(ROLE_PERMS[role])
    assert set(body["features"]) == FEATURE_KEYS
    assert body["favourites"] == [] and body["recent"] == []

    for screen in _screens(body):
        assert screen["route"] == "#/" + screen["view"]
        assert screen["component_key"] == screen["view"]


@pytest.mark.parametrize("role", list(ROLE_VIEWS))
def test_home_is_always_present_and_protected(client, role):
    client.as_user(role)
    body = client.get("/api/navigation").json()
    home = body["home"]
    assert home["view"] == "dash"
    assert home["node_key"] == "overview/dashboard/workspace/dash"
    assert home["route"] == "#/dash"
    assert home["is_home"] is True
    assert home["feature_key"] is None
    assert home in _screens(body)


def test_empty_branches_are_pruned(client):
    client.as_user("hr_manager")
    modules = {module["node_key"]: module
               for module in client.get("/api/navigation").json()["modules"]}
    assert set(modules) == {"overview", "sales", "finance", "people"}
    sales = {category["node_key"] for category in modules["sales"]["categories"]}
    assert sales == {"sales/sales"}                    # pipeline and parties are empty
    people = {category["node_key"] for category in modules["people"]["categories"]}
    assert people == {"people/people", "people/governance"}


def test_alias_resolution_follows_visibility(client):
    client.as_user("admin")
    body = client.get("/api/navigation").json()
    customers = next(s for s in _screens(body) if s["view"] == "customers")
    assert customers["aliases"] == ["distributors"]

    client.as_user("hr_manager")
    text = client.get("/api/navigation").text
    assert "distributors" not in text


def test_additional_route_is_not_offered_to_a_closed_role(client):
    client.as_user("viewer")
    body = client.get("/api/navigation").json()
    text = client.get("/api/navigation").text
    for view in ("suppliers", "accounts", "expenses", "tax", "scheduled",
                 "users", "roles", "audit", "leads", "lost", "followups"):
        assert f"#/{view}" not in text
        assert view not in _views(body)
    for perm in ("supplier:read", "accounts:read", "expense:read", "tax:read",
                 "email:manage", "user:manage", "audit:read", "lead:read"):
        assert perm not in body["permissions"]


def test_feature_switch_hides_the_module_and_its_permissions(client, restore_flags):
    client.as_user("admin")
    first = client.get("/api/navigation")
    assert first.status_code == 200
    assert "products" in _views(first.json())

    off = client.patch("/api/features/products", json={"enabled": False})
    assert off.status_code == 200, off.text

    res = client.get("/api/navigation", headers={"If-None-Match": first.headers["etag"]})
    assert res.status_code == 200, "a switch change must not return 304"
    body = res.json()
    assert "products" not in _views(body)
    assert "products" not in body["features"]
    assert "product:read" not in body["permissions"]
    assert "product:write" not in body["permissions"]

    client.patch("/api/features/products", json={"enabled": True})
    assert "products" in _views(client.get("/api/navigation").json())


def test_dependency_switch_hides_the_dependent_feature(client, restore_flags,
                                                       restore_dependency):
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        db.get(FeatureRegistry, "foc").depends_on = ["stock"]
        db.commit()

    client.as_user("admin")
    both_on = client.get("/api/navigation").json()
    assert "foc" in both_on["features"] and "stock" in both_on["features"]
    assert "foc" in _views(both_on)

    assert client.patch("/api/features/stock",
                        json={"enabled": False}).status_code == 200
    body = client.get("/api/navigation").json()
    assert "stock" not in body["features"]
    assert "foc" not in body["features"], "foc depends on stock and must follow it"
    assert "foc" not in _views(body)
    assert "inventory" not in _views(body)


def test_inactive_node_hides_itself_and_descendants(client):
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        node = db.scalar(select(NavNode).where(
            NavNode.node_key == "sales/sales/order-desk"))
        node.active = False
        db.commit()
    try:
        client.as_user("admin")
        res = client.get("/api/navigation")
        assert res.status_code == 200, res.text
        views = _views(res.json())
        assert "sales" not in views
        assert "billing" in views and "approvals" in views
    finally:
        with SessionLocal() as db:
            db.scalar(select(NavNode).where(
                NavNode.node_key == "sales/sales/order-desk")).active = True
            db.commit()


def test_invalid_feature_reference_returns_503(client):
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        node = db.scalar(select(NavNode).where(
            NavNode.node_key == "sales/parties/customer-master/customers"))
        node.feature_key = "not_a_feature"
        db.commit()
    try:
        client.as_user("admin")
        res = client.get("/api/navigation")
        assert res.status_code == 503
        assert res.json() == {"detail": "Navigation registry unavailable"}
    finally:
        with SessionLocal() as db:
            db.scalar(select(NavNode).where(
                NavNode.node_key == "sales/parties/customer-master/customers")
            ).feature_key = "sales"
            db.commit()


def test_missing_registry_table_returns_503(client, monkeypatch):
    from app.api import navigation as navigation_api
    monkeypatch.setattr(navigation_api, "load_registry", lambda db: None)
    res = client.get("/api/navigation")
    assert res.status_code == 503
    assert res.json() == {"detail": "Navigation registry unavailable"}


def test_etag_conditional_get(client):
    client.as_user("admin")
    first = client.get("/api/navigation")
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')
    assert first.headers["cache-control"] == "private, no-cache"
    assert "cookie" in first.headers["vary"].lower()

    second = client.get("/api/navigation", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["etag"] == etag
    assert second.headers["cache-control"] == "private, no-cache"

    weak = client.get("/api/navigation", headers={"If-None-Match": f"W/{etag}"})
    assert weak.status_code == 304

    stale = client.get("/api/navigation", headers={"If-None-Match": '"stale"'})
    assert stale.status_code == 200
    assert stale.content == first.content


def test_etag_changes_after_a_permission_change(client):
    """A role edit must invalidate the cached menu on the next request."""
    from app.core.db import SessionLocal
    from app.core.security import make_token

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        role = Role(name=f"nav_{suffix}", display_name="Navigation test",
                    is_system=False, permissions=["sales:read"])
        db.add(role)
        db.flush()
        employee = Employee(code=f"NAV_{suffix.upper()}", full_name="Navigation Test",
                            status="active")
        db.add(employee)
        db.flush()
        user = User(username=f"nav_{suffix}", username_key=f"nav_{suffix}",
                    password_hash="x", role=role.name, role_id=role.id,
                    employee_id=employee.id)
        db.add(user)
        db.commit()
        user_id, token = user.id, make_token(user.id, user.token_version or 1)

    client.cookies.set("session", token)
    first = client.get("/api/navigation")
    assert first.status_code == 200
    assert "products" not in _views(first.json())

    with SessionLocal() as db:
        role = db.query(Role).filter(Role.name == f"nav_{suffix}").one()
        role.permissions = ["sales:read", "product:read"]
        db.commit()

    res = client.get("/api/navigation", headers={"If-None-Match": first.headers["etag"]})
    assert res.status_code == 200, "a permission change must not return 304"
    assert "products" in _views(res.json())
    assert res.headers["etag"] != first.headers["etag"]

    again = client.get("/api/navigation", headers={"If-None-Match": res.headers["etag"]})
    assert again.status_code == 304

    client.as_user("admin")
    assert client.get("/api/navigation").status_code == 200


def test_etag_is_per_user_even_when_the_body_matches(client):
    """Two Administrators see the same menu but must never share a cache entry."""
    from app.core.db import SessionLocal
    from app.core.security import make_token

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == "admin"))
        employee = Employee(code=f"NAV2_{suffix.upper()}", full_name="Second Admin",
                            status="active")
        db.add(employee)
        db.flush()
        user = User(username=f"nav2_{suffix}", username_key=f"nav2_{suffix}",
                    password_hash="x", role="admin", role_id=role.id,
                    employee_id=employee.id)
        db.add(user)
        db.commit()
        token = make_token(user.id, user.token_version or 1)

    client.as_user("admin")
    first = client.get("/api/navigation")
    client.cookies.set("session", token)
    second = client.get("/api/navigation")

    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert first.headers["etag"] != second.headers["etag"]

    crossed = client.get("/api/navigation",
                         headers={"If-None-Match": first.headers["etag"]})
    assert crossed.status_code == 200, "another user's ETag must not yield 304"

    client.as_user("admin")


def test_get_writes_no_navigation_feature_or_audit_row(client):
    from app.core.db import SessionLocal
    tables = (NavNode, FeatureRegistry, FeatureFlag, AuditLog)
    with SessionLocal() as db:
        before = {table.__tablename__: db.scalar(select(func.count()).select_from(table))
                  for table in tables}
        max_audit = db.scalar(select(func.max(AuditLog.id))) or 0

    for role in ("admin", "sales", "viewer"):
        client.as_user(role)
        assert client.get("/api/navigation").status_code == 200

    with SessionLocal() as db:
        after = {table.__tablename__: db.scalar(select(func.count()).select_from(table))
                 for table in tables}
        assert after == before
        assert (db.scalar(select(func.max(AuditLog.id))) or 0) == max_audit


def test_admin_registry_endpoint_is_administrator_only(client):
    from app.main import app

    client.as_user("admin")
    res = client.get("/api/admin/navigation")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["nodes"]) == 64
    assert len(body["features"]) == len(FEATURE_KEYS)
    assert body["counts"] == {"modules": 5, "categories": 14, "groups": 20,
                              "screens": 25, "features": 14}
    assert body["errors"] == []
    assert len(body["fingerprint"]) == 64
    assert body["features"][0]["enabled"] is True

    client.as_user("sales")
    assert client.get("/api/admin/navigation").status_code == 403

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/admin/navigation").status_code == 401


def test_navigation_permissions_match_auth_me(client):
    """The two contracts must agree: no screen is offered that /me denies."""
    for role in ("admin", "sales", "inventory", "viewer", "hr_manager"):
        client.as_user(role)
        me = client.get("/api/auth/me").json()
        nav = client.get("/api/navigation").json()
        assert nav["permissions"] == sorted(me["permissions"])
        assert set(nav["features"]) <= set(me["features"])


def test_response_is_deterministic(client):
    client.as_user("sales")
    first = client.get("/api/navigation")
    second = client.get("/api/navigation")
    assert first.content == second.content
    assert first.headers["etag"] == second.headers["etag"]
