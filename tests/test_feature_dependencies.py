"""WP-4c: one availability answer for the gate, permissions and the menu.

The registry remembers which features depend on which (`feature_registry
.depends_on`). Before Batch 4c only the navigation API applied that closure:
the route gate, `/api/auth/me` and the effective permissions read each
feature's own switch. A dependent module could therefore disappear from the
menu while its API stayed reachable. These tests pin the shared answer:

* a dependent feature is unavailable when its dependency is switched off,
  whatever its own switch says;
* the route gate, the effective permissions, the identity payload and
  `/api/navigation` all agree;
* a feature whose registry status is not `active` is unavailable even with its
  switch on;
* a dependency cycle fails closed;
* an installation without the registry table (before 0031) keeps the old answer:
  the stored switches alone.
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.core.features import FEATURE_KEYS
from app.models.navigation import FeatureRegistry
from app.models.settings import FeatureFlag
from app.services.feature_store import (available_keys, disabled_permissions,
                                        enabled_keys, is_enabled)
from app.services.navigation_store import feature_available


@pytest.fixture()
def registry():
    """Restore the registry rows and clear the switches after each test."""
    with SessionLocal() as db:
        saved = {row.feature_key: (row.status, list(row.depends_on or []))
                 for row in db.scalars(select(FeatureRegistry)).all()}
        db.execute(delete(FeatureFlag))
        db.commit()

    def set_row(key: str, **fields):
        with SessionLocal() as db:
            row = db.get(FeatureRegistry, key)
            for field, value in fields.items():
                setattr(row, field, value)
            db.commit()

    def switch(key: str, enabled: bool):
        with SessionLocal() as db:
            row = db.get(FeatureFlag, key)
            if row is None:
                db.add(FeatureFlag(key=key, enabled=enabled))
            else:
                row.enabled = enabled
            db.commit()

    set_row.switch = switch
    yield set_row

    with SessionLocal() as db:
        for key, (status, deps) in saved.items():
            row = db.get(FeatureRegistry, key)
            row.status = status
            row.depends_on = deps
        db.execute(delete(FeatureFlag))
        db.commit()


def _nav_views(client) -> set[str]:
    body = client.get("/api/navigation").json()
    return {screen["view"]
            for module in body["modules"]
            for category in module["categories"]
            for group in category["groups"]
            for screen in group["screens"]}


def test_a_dependency_switch_closes_the_dependent_module(client, registry):
    registry("foc", depends_on=["stock"])
    assert client.get("/api/foc/notes").status_code == 200
    assert client.get("/api/navigation").status_code == 200

    assert client.patch("/api/features/stock", json={"enabled": False}).status_code == 200

    # The dependent module's own switch is still ON; its dependency is not.
    rows = {row["key"]: row for row in client.get("/api/features").json()}
    assert rows["foc"]["enabled"] is True
    assert client.get("/api/foc/notes").status_code == 403

    me = client.get("/api/auth/me").json()
    assert "foc" not in me["features"]
    assert {"foc:read", "foc:write", "foc:approve"}.isdisjoint(me["permissions"])
    assert "foc" not in _nav_views(client)

    # Restoring the dependency restores the dependent module everywhere.
    assert client.patch("/api/features/stock", json={"enabled": True}).status_code == 200
    assert client.get("/api/foc/notes").status_code == 200
    assert "foc" in client.get("/api/auth/me").json()["features"]
    assert "foc" in _nav_views(client)


def test_inactive_registry_row_is_unavailable_whatever_the_switch_says(client, registry):
    registry("foc", status="planned")

    assert client.get("/api/foc/notes").status_code == 403
    me = client.get("/api/auth/me").json()
    assert "foc" not in me["features"]
    assert "foc:read" not in me["permissions"]
    assert "foc" not in _nav_views(client)
    admin = client.get("/api/admin/navigation").json()
    foc_row = next(row for row in admin["features"] if row["feature_key"] == "foc")
    assert foc_row["status"] == "planned"


def test_the_same_answer_serves_every_reader(registry):
    registry("foc", depends_on=["stock"])
    registry.switch("stock", False)
    with SessionLocal() as db:
        available = available_keys(db)
        assert "stock" not in available
        assert "foc" not in available
        assert "products" in available
        assert enabled_keys(db) == available
        assert is_enabled(db, "foc") is False
        assert is_enabled(db, "stock") is False
        assert is_enabled(db, "products") is True
        assert is_enabled(db, "not-a-feature") is True
        assert {"foc:read", "foc:write", "foc:approve"}.issubset(disabled_permissions(db))
        assert "stock:read" in disabled_permissions(db)


def test_a_dependency_cycle_fails_closed():
    rows = [
        {"feature_key": "a", "status": "active", "locked": False, "depends_on": ["b"]},
        {"feature_key": "b", "status": "active", "locked": False, "depends_on": ["a"]},
        {"feature_key": "c", "status": "active", "locked": False, "depends_on": []},
    ]
    assert feature_available(rows, {}) == {"c"}
    assert feature_available(rows, {"a": True}) == {"c"}, "a cycle stays closed"


def test_without_the_registry_the_stored_switches_alone_decide(registry, monkeypatch):
    from app.services import navigation_store

    registry.switch("products", False)
    monkeypatch.setattr(navigation_store, "load_features", lambda db: None)
    with SessionLocal() as db:
        available = available_keys(db)
        assert available == FEATURE_KEYS - {"products"}
        assert is_enabled(db, "products") is False
        assert is_enabled(db, "foc") is True
        assert "product:read" in disabled_permissions(db)
