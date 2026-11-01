"""Central feature availability switches (Roles & Permissions).

Rules under test:

* every permission and every navigation view belongs to exactly one feature, so
  a new module cannot be added without deciding where its switch lives;
* every feature starts ON, and a missing row means ON;
* only the Administrator role may read or change the switches;
* switching a feature off removes its permissions from every role, blocks its
  API, and empties its Overview sections;
* the switch is auditable and reversible;
* `users` can never be switched off, and the public unsubscribe link keeps
  working whatever the scheduled-reports switch says.
"""
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.features import (FEATURES, FEATURE_KEYS, PUBLIC_EXCEPTIONS,
                               feature_for_path)
from app.core.permissions import PERMISSION_KEYS


@pytest.fixture()
def restore_flags():
    """Every flag row is deleted after the test, which means ON again."""
    yield
    from app.core.db import SessionLocal
    from app.models.settings import FeatureFlag
    with SessionLocal() as db:
        db.execute(delete(FeatureFlag))
        db.commit()


def test_registry_owns_every_permission_exactly_once():
    owned = [key for f in FEATURES for key in f.permissions]
    assert len(owned) == len(set(owned)), "a permission is owned by two features"
    assert set(owned) == PERMISSION_KEYS


def test_registry_views_and_prefixes_are_not_shared():
    views = [v for f in FEATURES for v in f.views]
    assert len(views) == len(set(views)), "a navigation view is owned by two features"
    prefixes = [p for f in FEATURES for p in f.api_prefixes]
    assert len(prefixes) == len(set(prefixes)), "an API prefix is owned by two features"
    assert FEATURE_KEYS == {f.key for f in FEATURES}


def test_path_lookup_uses_the_longest_prefix():
    assert feature_for_path("/api/products") == "products"
    assert feature_for_path("/api/products/12") == "products"
    assert feature_for_path("/api/productsearch") is None
    assert feature_for_path("/api/dashboard/expiry") == "stock"
    assert feature_for_path("/api/dashboard/compare") == "reports"
    assert feature_for_path("/api/dashboard") is None
    assert feature_for_path("/api/health") is None
    assert all(path.startswith("/api/") for path in PUBLIC_EXCEPTIONS)


def test_every_feature_is_on_by_default(client, restore_flags):
    res = client.get("/api/features")
    assert res.status_code == 200, res.text
    rows = {row["key"]: row for row in res.json()}
    assert set(rows) == FEATURE_KEYS
    assert all(row["enabled"] for row in rows.values())
    assert rows["users"]["locked"] is True
    assert rows["products"]["permissions"] == ["product:read", "product:write"]

    me = client.get("/api/auth/me").json()
    assert set(me["features"]) == FEATURE_KEYS


def test_only_the_administrator_may_manage_features(client):
    """A custom role carrying user:manage is still refused: this is a system switch."""
    from app.core.db import SessionLocal
    from app.core.security import make_token
    from app.models.core import User
    from app.models.users import Employee, Role

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        role = Role(name=f"mgr_{suffix}", display_name="Manager", is_system=False,
                    permissions=["user:manage", "employee:read"])
        db.add(role)
        db.flush()
        employee = Employee(code=f"MG_{suffix.upper()}", full_name="Manager Test",
                            status="active")
        db.add(employee)
        db.flush()
        user = User(username=f"mgr_{suffix}", username_key=f"mgr_{suffix}",
                    password_hash="x", role=role.name, role_id=role.id,
                    employee_id=employee.id)
        db.add(user)
        db.commit()
        token = make_token(user.id, user.token_version or 1)

    client.cookies.set("session", token)
    assert client.get("/api/features").status_code == 403
    assert client.patch("/api/features/products",
                        json={"enabled": False}).status_code == 403

    client.as_user("admin")
    assert client.get("/api/features").status_code == 200


def test_switching_a_feature_off_is_enforced_and_reversible(client, restore_flags):
    off = client.patch("/api/features/products", json={"enabled": False})
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False

    me = client.get("/api/auth/me").json()
    assert "product:read" not in me["permissions"]
    assert "product:write" not in me["permissions"]
    assert "products" not in me["features"]
    assert client.get("/api/products").status_code == 403
    # The management endpoint itself is never gated.
    assert client.get("/api/features").status_code == 200

    from app.core.db import SessionLocal
    from app.models.core import AuditLog
    with SessionLocal() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "feature.update")
                        .order_by(AuditLog.id.desc()))
        assert row is not None and row.record == "feature:products"

    on = client.patch("/api/features/products", json={"enabled": True})
    assert on.status_code == 200 and on.json()["enabled"] is True
    assert client.get("/api/products").status_code == 200
    assert "product:read" in client.get("/api/auth/me").json()["permissions"]


def test_switch_applies_to_every_role_not_just_the_administrator(client, restore_flags):
    assert client.patch("/api/features/sales", json={"enabled": False}).status_code == 200
    client.as_user("sales")
    me = client.get("/api/auth/me").json()
    assert "sales:read" not in me["permissions"]
    assert "sales" not in me["features"]
    assert client.get("/api/sales-orders").status_code == 403
    client.as_user("admin")


def test_overview_sections_follow_the_switches(client, restore_flags):
    before = client.get("/api/dashboard").json()
    assert before["stock"] is not None

    assert client.patch("/api/features/stock", json={"enabled": False}).status_code == 200
    after = client.get("/api/dashboard").json()
    assert after["stock"] is None
    assert all(kpi["key"] != "units_on_hand" for kpi in after["kpis"])
    assert client.get("/api/inventory/batches").status_code == 403
    assert client.get("/api/dashboard/expiry?bucket=all").status_code == 403


def test_locked_and_unknown_features(client, restore_flags):
    locked = client.patch("/api/features/users", json={"enabled": False})
    assert locked.status_code == 409
    assert "cannot be switched off" in locked.json()["detail"]
    assert client.patch("/api/features/nope", json={"enabled": False}).status_code == 404


def test_public_unsubscribe_link_is_exempt(client, restore_flags):
    assert client.patch("/api/features/scheduled", json={"enabled": False}).status_code == 200
    res = client.get("/api/email-reports/unsubscribe/not-a-real-token")
    assert res.status_code == 404, res.text       # the page ran; the token was unknown
    assert client.get("/api/email-reports/status").status_code == 403
