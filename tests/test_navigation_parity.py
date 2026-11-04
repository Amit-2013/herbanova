"""WP-4d: the built-in menu and the API menu describe the same screens.

Batch 4d makes `GET /api/navigation` the default renderer. Before that flip the
two must agree for every role and every permission/feature combination that can
change the menu, or the same user sees a different menu depending on whether the
server answered. These tests drive the real `static/js/workspace.js` under Node
(through `tests/js/nav_parity.cjs`) and compare it with the real endpoint or
with the same catalogue functions the endpoint calls.

Covered here:
* every seeded database role, through the HTTP endpoint;
* every single navigation permission, every pair, and all together (with
  parent keys, as `effective_permissions` would produce them);
* each feature switched off, including the registry dependency closure;
* the Administrator-only `scheduled` screen, in both directions;
* Home, the `distributors` alias, the hidden routes and the accounting sections;
* no duplicate, unknown or missing screen in either representation.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from itertools import combinations
from pathlib import Path

import pytest
from sqlalchemy import select

from app.api.navigation import _build_tree, _screen
from app.core.features import FEATURE_KEYS
from app.core.permissions import PERMISSION_PARENT
from app.services.navigation_catalog import (ACCOUNTS_SECTION_COUNT,
                                             ADMIN_ONLY_VIEWS, VIEWS,
                                             build_features, build_nodes)
from app.services.navigation_registry import (narrow_admin_only,
                                              visible_keys)
from app.services.navigation_store import feature_available

ROOT = Path(__file__).resolve().parent.parent

ROLE_USERS = {
    "admin": "admin",
    "sales": "sales",
    "inventory": "inventory",
    "viewer": "viewer",
    "hr_manager": "hr_manager",
    "payroll": "payroll_officer",
    "manager": "reporting_manager",
    "staff": "employee",
}

# Union of every permission named by a screen's route gate or menu rule. These
# are the only keys that can change what the menu shows.
GATE_KEYS = sorted({key for spec in VIEWS.values()
                    for key in (*spec.permission_any, *spec.menu_any)})


def _screens(body: dict) -> list[dict]:
    return [screen
            for module in body["modules"]
            for category in module["categories"]
            for group in category["groups"]
            for screen in group["screens"]]


def _views(body: dict) -> list[str]:
    return [screen["view"] for screen in _screens(body)]


def _with_parents(keys) -> set[str]:
    """The stored keys that survive `effective_permissions` (child needs parent)."""
    out: set[str] = set()
    for key in keys:
        while key and key not in out:
            out.add(key)
            key = PERMISSION_PARENT.get(key)
    return out


def _body(permissions: set[str], available: set[str], *, admin: bool) -> dict:
    """The JSON body `get_navigation` builds, from the catalogue rather than a DB."""
    nodes, features = build_nodes(), build_features()
    visible = narrow_admin_only(
        visible_keys(nodes, permissions, lambda key: key in available),
        nodes, admin=admin)
    home = next(node for node in nodes if node["is_home"])
    return {
        "modules": _build_tree(nodes, visible, permissions),
        "home": _screen(home, permissions),
        "features": sorted(available),
        "permissions": sorted(permissions),
        "favourites": [],
        "recent": [],
    }


def _run_node(cases: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    result = subprocess.run([node, "tests/js/nav_parity.cjs"], cwd=ROOT,
                            input=json.dumps({"cases": cases}),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _compare(results: list[dict]) -> None:
    assert results, "the parity harness produced no results"
    for row in results:
        assert row["ok"], f"{row['name']}: converter refused the body ({row['error']})"
        assert row["raw_duplicates"] == [], f"{row['name']}: duplicate screen"
        assert row["raw_unknown"] == [], f"{row['name']}: unknown screen"
        assert row["builtin_visible"] == row["api_visible"], (
            f"{row['name']}: screen sets differ; "
            f"builtin only {sorted(set(row['builtin_visible']) - set(row['api_visible']))}, "
            f"api only {sorted(set(row['api_visible']) - set(row['builtin_visible']))}")
        assert row["builtin_menu"] == row["api_menu"], (
            f"{row['name']}: menu rows differ; "
            f"builtin only {sorted(set(row['builtin_menu']) - set(row['api_menu']))}, "
            f"api only {sorted(set(row['api_menu']) - set(row['builtin_menu']))}")


# ------------------------------------------------------------------ seeded roles
def test_builtin_and_api_agree_for_every_seeded_role(client):
    cases = []
    for user, role_name in ROLE_USERS.items():
        client.as_user(user)
        res = client.get("/api/navigation")
        assert res.status_code == 200, (role_name, res.text)
        body = res.json()
        # The browser's `can()` reads /api/auth/me; prove the two agree first.
        me = client.get("/api/auth/me").json()
        assert body["permissions"] == sorted(me["permissions"]), role_name
        assert set(body["features"]) <= set(me["features"]), role_name
        cases.append({
            "name": role_name,
            "permissions": body["permissions"],
            "features": body["features"],
            "admin": role_name == "admin",
            "body": body,
        })
    _compare(_run_node(cases))


def test_every_role_keeps_home_and_the_alias(client):
    for user, role_name in ROLE_USERS.items():
        client.as_user(user)
        body = client.get("/api/navigation").json()
        assert body["home"]["view"] == "dash", role_name
        assert body["home"]["is_home"] is True, role_name
        assert "dash" in _views(body), role_name
        customers = [s for s in _screens(body) if s["view"] == "customers"]
        if customers:
            assert customers[0]["aliases"] == ["distributors"], role_name
        # The 19 accounting sub-sections stay inside one screen, never nodes.
        assert ACCOUNTS_SECTION_COUNT == 19
        accounts = [s for s in _screens(body) if s["view"] == "accounts"]
        for screen in accounts:
            assert screen["node_key"] == "finance/books/ledgers/accounts", role_name
        assert [s["view"] for s in _screens(body)].count("accounts") <= 1, role_name


def test_hidden_routes_stay_out_of_the_menu_but_are_still_reachable(client):
    client.as_user("admin")
    body = client.get("/api/navigation").json()
    menu = {s["view"] for s in _screens(body) if s["in_menu"]}
    for view in ("compare", "tax", "users", "audit"):
        assert view in _views(body), f"{view} must stay addressable by hash"
        assert view not in menu, f"{view} must not be a menu row"


def test_api_never_offers_a_screen_the_permissions_do_not_cover(client):
    offered = {view: spec for view, spec in VIEWS.items()}
    for user, role_name in ROLE_USERS.items():
        client.as_user(user)
        body = client.get("/api/navigation").json()
        permissions, features = set(body["permissions"]), set(body["features"])
        for view in _views(body):
            spec = offered[view]
            assert not spec.permission_any or permissions & set(spec.permission_any), (
                f"{role_name} is offered {view} without {spec.permission_any}")
            assert spec.feature is None or spec.feature in features, (
                f"{role_name} is offered {view} while {spec.feature} is off")


# ------------------------------------------------- permission/feature combinations
def _catalogue_cases() -> list[dict]:
    all_features = feature_available(build_features(), {})
    assert all_features == set(FEATURE_KEYS)

    combinations_under_test: list[tuple[str, set[str], bool]] = [
        ("no permissions", set(), False),
        ("all gate permissions", _with_parents(GATE_KEYS), False),
        ("all gate permissions as Administrator", _with_parents(GATE_KEYS), True),
        ("email:manage outside the Administrator role",
         _with_parents({"email:manage"}), False),
        ("email:manage as Administrator",
         _with_parents({"email:manage"}), True),
    ]
    for key in GATE_KEYS:
        combinations_under_test.append((f"only {key}", _with_parents({key}), False))
    for left, right in combinations(GATE_KEYS, 2):
        combinations_under_test.append(
            (f"{left} + {right}", _with_parents({left, right}), False))

    cases = [{"name": name, "permissions": sorted(permissions),
              "features": sorted(all_features), "admin": admin,
              "body": _body(permissions, all_features, admin=admin)}
             for name, permissions, admin in combinations_under_test]

    every_permission = _with_parents(GATE_KEYS)
    declared_permissions = {row["feature_key"]: set(row["permissions"])
                            for row in build_features()}
    for feature in sorted(FEATURE_KEYS):
        available = feature_available(build_features(), {feature: False})
        # Production removes a switched-off feature's keys from role_permissions.
        permissions = every_permission - declared_permissions[feature]
        cases.append({
            "name": f"feature {feature} off",
            "permissions": sorted(permissions),
            "features": sorted(available),
            "admin": True,
            "body": _body(permissions, available, admin=True),
        })
    nothing = feature_available(build_features(), {key: False for key in FEATURE_KEYS})
    assert nothing == {"users"}
    users_only = every_permission & {"user:manage"}
    cases.append({
        "name": "every feature off but users (locked)",
        "permissions": sorted(users_only),
        "features": sorted(nothing),
        "admin": True,
        "body": _body(users_only, nothing, admin=True),
    })
    return cases


def test_builtin_and_api_agree_for_every_gate_combination():
    cases = _catalogue_cases()
    assert len(cases) == 5 + len(GATE_KEYS) + len(GATE_KEYS) * (len(GATE_KEYS) - 1) // 2 \
        + len(FEATURE_KEYS) + 1
    _compare(_run_node(cases))


def test_a_feature_switch_removes_its_screen_and_permissions():
    every_permission = _with_parents(GATE_KEYS)
    for row in build_features():
        feature = row["feature_key"]
        if row["locked"] or feature == "users":
            continue
        available = feature_available(build_features(), {feature: False})
        assert feature not in available
        permissions = every_permission - set(row["permissions"])
        body = _body(permissions, available, admin=True)
        for screen in _screens(body):
            assert screen["feature_key"] != feature, feature
        for permission in set(row["permissions"]) & set(GATE_KEYS):
            assert permission not in body["permissions"], (feature, permission)


def test_dependencies_close_a_dependent_feature():
    features = build_features()
    for row in features:
        row["depends_on"] = ["stock"] if row["feature_key"] == "foc" else []
    available = feature_available(features, {"stock": False})
    assert "stock" not in available and "foc" not in available
    body = _body(_with_parents(GATE_KEYS), available, admin=True)
    assert "foc" not in _views(body) and "inventory" not in _views(body)


def test_admin_only_screens_are_admin_only():
    """The registry's route is require_admin; the menu must follow it."""
    assert ADMIN_ONLY_VIEWS == {"scheduled"}
    every_permission = _with_parents(GATE_KEYS)
    available = feature_available(build_features(), {})
    admin_body = _body(every_permission, available, admin=True)
    other_body = _body(every_permission, available, admin=False)
    assert "scheduled" in _views(admin_body)
    assert "scheduled" not in _views(other_body)
    assert "email:manage" in other_body["permissions"], (
        "the screen is hidden; the permission itself is not rewritten")
    _compare(_run_node([
        {"name": "admin", "permissions": sorted(every_permission),
         "features": sorted(available), "admin": True, "body": admin_body},
        {"name": "non-admin carrying email:manage",
         "permissions": sorted(every_permission), "features": sorted(available),
         "admin": False, "body": other_body},
    ]))


# ---------------------------------------------------------------- live endpoint
def test_a_stored_role_with_email_manage_cannot_reach_scheduled(client):
    """A role row written outside the Roles API still cannot be offered it."""
    from uuid import uuid4

    from app.core.db import SessionLocal
    from app.core.security import make_token
    from app.models.core import User
    from app.models.users import Employee, Role

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        role = Role(name=f"mail_{suffix}", display_name="Mail test",
                    is_system=False, permissions=["email:manage"])
        db.add(role)
        db.flush()
        employee = Employee(code=f"MAIL_{suffix.upper()}", full_name="Mail Test",
                            status="active")
        db.add(employee)
        db.flush()
        user = User(username=f"mail_{suffix}", username_key=f"mail_{suffix}",
                    password_hash="x", role=role.name, role_id=role.id,
                    employee_id=employee.id)
        db.add(user)
        db.commit()
        token = make_token(user.id, user.token_version or 1)

    client.cookies.set("session", token)
    body = client.get("/api/navigation").json()
    assert "email:manage" in body["permissions"]
    assert "scheduled" not in _views(body)

    client.as_user("admin")
    assert "scheduled" in _views(client.get("/api/navigation").json())


def test_etag_separates_the_admin_role_when_bodies_match(client):
    """The same user promoted to Administrator must not get a stale 304.

    With `scheduled` off, the promoted menu body is byte-identical, so only the
    admin flag in the ETag identity can tell the two states apart.
    """
    from uuid import uuid4

    from app.core.db import SessionLocal
    from app.core.security import make_token
    from app.models.core import User
    from app.models.users import Employee, Role

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        admin_role = db.scalar(select(Role).where(Role.name == "admin"))
        role = Role(name=f"almost_{suffix}", display_name="Almost admin",
                    is_system=False, permissions=list(admin_role.permissions))
        db.add(role)
        db.flush()
        employee = Employee(code=f"ALM_{suffix.upper()}", full_name="Almost Admin",
                            status="active")
        db.add(employee)
        db.flush()
        user = User(username=f"alm_{suffix}", username_key=f"alm_{suffix}",
                    password_hash="x", role=role.name, role_id=role.id,
                    employee_id=employee.id)
        db.add(user)
        db.commit()
        user_id, role_id = user.id, admin_role.id
        token = make_token(user_id, user.token_version or 1)

    client.as_user("admin")
    assert client.patch("/api/features/scheduled",
                        json={"enabled": False}).status_code == 200
    try:
        client.cookies.set("session", token)
        first = client.get("/api/navigation")
        assert first.status_code == 200

        with SessionLocal() as db:
            user = db.get(User, user_id)
            user.role_id = role_id
            user.role = "admin"
            db.commit()

        second = client.get("/api/navigation",
                            headers={"If-None-Match": first.headers["etag"]})
        assert second.status_code == 200, "a role promotion must not return 304"
        assert first.content == second.content
        assert first.headers["etag"] != second.headers["etag"]
    finally:
        client.as_user("admin")
        assert client.patch("/api/features/scheduled",
                            json={"enabled": True}).status_code == 200
