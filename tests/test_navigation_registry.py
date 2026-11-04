"""WP-4a: catalogue, validation, R-01 and workspace parity.

These are pure tests over `navigation_catalog` / `navigation_registry`, plus one
Node call that reads `static/js/workspace.js`. They run before migration 0031 is
activated; the two database tests at the end skip while the migration is still
a `.py.draft`.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.core.features import FEATURE_BY_KEY, FEATURES
from app.core.permissions import PERMISSION_KEYS
from app.models.navigation import FeatureRegistry, NavNode
from app.services import feature_store
from app.services.navigation_catalog import (ACCOUNTS_SECTION_COUNT, ALIASES,
                                             EXPECTED_COUNTS, HOME_VIEW, NAV,
                                             VIEWS, build_features, build_nodes,
                                             catalog_counts, iter_nav)
from app.services.navigation_registry import (narrow_admin_only, navigation_etag,
                                              registry_fingerprint, validate_catalog,
                                              visible_keys)

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ helpers
class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _StubDB:
    """The only surface feature_store uses: scalars(select(Model)).all()."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.rolled_back = False

    def scalars(self, statement):
        # Only switch rows exist here; the registry tables are absent, which is
        # what the pre-0031 fallback in available_keys() expects.
        entity = statement.column_descriptions[0].get("entity")
        rows = self.rows if getattr(entity, "__name__", "") == "FeatureFlag" else []
        return _Result(rows)

    def rollback(self):
        self.rolled_back = True


class _Flag:
    def __init__(self, key, enabled):
        self.key, self.enabled = key, bool(enabled)


def _manifest():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    spec = {"base": {view: list(spec.permission_any) for view, spec in VIEWS.items()},
            "candidates": sorted(PERMISSION_KEYS)}
    result = subprocess.run([node, "tests/js/emit_nav_manifest.cjs", json.dumps(spec)],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _expected_nav():
    return [{
        "id": module_id, "label": module_label,
        "categories": [{
            "id": category_id, "label": category_label,
            "groups": [{"id": group_id, "label": group_label, "views": list(views)}
                       for group_id, group_label, views in groups],
        } for category_id, category_label, groups in categories],
    } for module_id, module_label, categories in NAV]


def _errors(nodes, features=None):
    return validate_catalog(nodes, features if features is not None else build_features())


# ------------------------------------------------------------------ catalogue
def test_catalogue_counts_are_the_shipped_counts():
    assert catalog_counts() == EXPECTED_COUNTS
    nodes = build_nodes()
    assert len(nodes) == 64
    assert len({n["node_key"] for n in nodes}) == 64
    assert len({n["view"] for n in nodes if n["kind"] == "screen"}) == 25
    assert len(build_features()) == 14


def test_catalogue_validates_with_no_errors():
    assert _errors(build_nodes()) == []


def test_one_protected_home_and_one_alias():
    nodes = build_nodes()
    homes = [n for n in nodes if n["is_home"]]
    assert len(homes) == 1
    assert homes[0]["view"] == HOME_VIEW
    assert homes[0]["feature_key"] is None and homes[0]["permission_any"] == []
    assert homes[0]["active"] is True
    assert ALIASES == {"distributors": "sales/parties/customer-master/customers"}


def test_seed_literal_matches_the_catalogue():
    source = ROOT / "alembic" / "versions" / "0031_navigation_registry.py"
    if not source.exists():
        source = source.with_name(source.name + ".draft")
    assert source.exists(), "migration 0031 is missing"
    loader = SourceFileLoader("migration_0031", str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    migration = importlib.util.module_from_spec(spec)
    loader.exec_module(migration)
    assert migration.revision == "0031_navigation_registry"
    assert migration.down_revision == "0030_sign_in_content"
    assert migration.NAV_NODES == build_nodes()
    assert migration.FEATURE_ROWS == build_features()


def test_accounts_sections_stay_code_driven():
    source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    block = re.search(r"const ACC_SECTIONS = \[(.*?)\];", source, re.S)
    assert block, "ACC_SECTIONS moved; update this test with it"
    sections = re.findall(r'key: "([^"]+)"', block.group(1))
    assert len(sections) == ACCOUNTS_SECTION_COUNT == 19
    views = {n["view"] for n in build_nodes() if n["kind"] == "screen"}
    collisions = sorted(set(sections) & views)
    # `reports` is both a top-level screen and an accounts section name; every
    # other section is internal to the one `accounts` screen.
    assert collisions == ["reports"]
    workspace = (ROOT / "static" / "js" / "workspace.js").read_text(encoding="utf-8")
    assert "const SECTION_VIEWS = {accounts: true};" in workspace


# ---------------------------------------------------------- workspace parity
def test_navigation_matches_workspace_js_exactly():
    manifest = _manifest()
    assert manifest["nav"] == _expected_nav()
    assert manifest["titles"] == {view: spec.label for view, spec in VIEWS.items()}
    assert manifest["view_feature"] == {view: spec.feature for view, spec in VIEWS.items()
                                        if spec.feature}

    expected_flat = []
    path_labels = {path: label for _depth, _kind, path, label, _view in iter_nav()}
    for depth, kind, path, label, view in iter_nav():
        if kind != "screen":
            continue
        expected_flat.append({
            "view": view, "label": VIEWS[view].label,
            "module": path_labels[(path[0],)], "category": path_labels[path[:2]],
            "group": path_labels[path[:3]], "menu": VIEWS[view].menu_rule != "never",
        })
    assert manifest["flat"] == expected_flat
    # `home` is the permanent tab key; its screen is `dash` and its address
    # is `#/dash`, which is what the Home nav node stores.
    assert manifest["home"] == "home"
    assert manifest["home_hash"] == "#/" + HOME_VIEW
    assert manifest["alias_customers"] == "customers"
    assert all(manifest["routes"][view] == view for view in VIEWS)


def test_browser_access_rules_match_the_catalogue():
    manifest = _manifest()
    candidates = sorted(PERMISSION_KEYS)
    for view, spec in VIEWS.items():
        allowed = set(manifest["view_allowed_single"][view])
        if spec.permission_any:
            assert allowed == set(spec.permission_any), view
        else:
            assert allowed == set(candidates), f"{view} should need no permission"
        assert manifest["view_allowed_base"][view] is True, view
        assert manifest["feature_off"][view] is (spec.feature is None), view

        menu_with_one = set(manifest["menu_single"][view])
        if spec.menu_rule == "never":
            assert manifest["menu_base"][view] is False
            assert menu_with_one == set()
        elif spec.menu_rule == "menu_any":
            assert manifest["menu_base"][view] is False
            assert menu_with_one == set(spec.menu_any), view
        else:
            assert manifest["menu_base"][view] is True
            assert menu_with_one == set(candidates), view


# ------------------------------------------------------------------ R-01
def test_registered_feature_without_a_switch_row_is_on():
    assert "hr" in {row["feature_key"] for row in build_features()}
    assert FEATURE_BY_KEY["hr"].locked is False
    db = _StubDB([])                      # no feature_flags row at all
    assert feature_store.is_enabled(db, "hr") is True


def test_disabled_switch_row_hides_nodes_but_keeps_the_registry_row():
    db = _StubDB([_Flag("hr", False)])
    assert feature_store.is_enabled(db, "hr") is False
    enabled = lambda key: feature_store.is_enabled(db, key)  # noqa: E731
    nodes = build_nodes()
    visible = visible_keys(nodes, {"hr:read"}, enabled)
    hr_keys = {n["node_key"] for n in nodes if n["feature_key"] == "hr"}
    assert hr_keys and not (visible & hr_keys)
    assert "hr" in {row["feature_key"] for row in build_features()}


def test_registry_has_no_foreign_key_to_feature_flags():
    assert {fk.target_fullname for fk in FeatureRegistry.__table__.foreign_keys} == set()
    assert {fk.target_fullname for fk in NavNode.__table__.foreign_keys} == {"nav_nodes.id"}
    assert "enabled" not in FeatureRegistry.__table__.columns


def test_unknown_feature_key_is_rejected():
    nodes = build_nodes()
    node = next(n for n in nodes if n["view"] == "products")
    node["feature_key"] = "ghost"
    errors = _errors(nodes)
    assert any("unknown feature 'ghost'" in error for error in errors), errors


def test_registry_membership_does_not_enable_or_disable_a_switch():
    # A registry row with every feature present changes nothing about switches.
    assert all(row["feature_key"] in FEATURE_BY_KEY for row in build_features())
    assert feature_store.is_enabled(_StubDB([]), "accounts") is True
    assert feature_store.is_enabled(_StubDB([_Flag("accounts", False)]), "accounts") is False
    # The switch table is the only state: the registry model has no `enabled`.
    assert "enabled" not in FeatureRegistry.__table__.columns
    assert "enabled" not in NavNode.__table__.columns


# ------------------------------------------------------------------ validation
def test_duplicate_node_key_is_rejected():
    nodes = build_nodes()
    nodes[1]["node_key"] = nodes[0]["node_key"]
    assert any("duplicate node_key" in e for e in _errors(nodes))


def test_unknown_permission_is_rejected():
    nodes = build_nodes()
    screen = next(n for n in nodes if n["view"] == "products")
    screen["permission_any"] = ["ghost:read"]
    assert any("unknown permission_any key 'ghost:read'" in e for e in _errors(nodes))


def test_invalid_hierarchy_is_rejected():
    nodes = build_nodes()
    nodes[1]["depth"] = 4                       # category pretending to be a screen
    nodes[2]["parent_id"] = 999                 # orphan
    errors = _errors(nodes)
    assert any("depth" in e for e in errors)
    assert any("parent does not exist" in e for e in errors)


def test_parent_cycle_is_rejected():
    nodes = build_nodes()
    nodes[0]["parent_id"] = nodes[1]["id"]      # module under its own category
    errors = _errors(nodes)
    assert any("cycle" in e or "must have no parent" in e for e in errors)


def test_duplicate_view_and_route_are_rejected():
    nodes = build_nodes()
    screens = [n for n in nodes if n["kind"] == "screen"]
    screens[1]["route"] = screens[0]["route"]
    assert any("duplicate route" in e for e in _errors(nodes))
    screens[1]["view"] = screens[0]["view"]
    assert any("duplicate screen view" in e for e in _errors(nodes))


def test_home_cannot_be_disabled_moved_or_given_a_permission():
    nodes = build_nodes()
    home = next(n for n in nodes if n["is_home"])
    home["is_home"] = False
    assert any("exactly one Home" in e for e in _errors(nodes))

    nodes = build_nodes()
    home = next(n for n in nodes if n["is_home"])
    home["permission_any"] = ["product:read"]
    assert any("Home must be" in e for e in _errors(nodes))

    nodes = build_nodes()
    second = next(n for n in nodes if n["view"] == "compare")
    second["is_home"] = True
    assert any("exactly one Home" in e for e in _errors(nodes))


def test_alias_must_be_unique_and_not_collide_with_a_key_or_view():
    nodes = build_nodes()
    customers = next(n for n in nodes if n["view"] == "customers")
    customers["aliases"].append("sales")
    assert any("collides" in e for e in _errors(nodes))

    nodes = build_nodes()
    another = next(n for n in nodes if n["view"] == "leads")
    another["aliases"] = ["distributors"]
    assert any("used twice" in e for e in _errors(nodes))


def test_duplicate_sort_order_is_rejected():
    nodes = build_nodes()
    siblings = [n for n in nodes if n["parent_id"] == nodes[2]["id"]]
    siblings[1]["sort_order"] = siblings[0]["sort_order"]
    assert any("duplicate sort_order" in e for e in _errors(nodes))


def test_component_key_must_equal_view():
    nodes = build_nodes()
    screen = next(n for n in nodes if n["view"] == "billing")
    screen["component_key"] = "invoice-billing"
    assert any("component_key must equal view" in e for e in _errors(nodes))


def test_feature_rows_must_match_features_py():
    features = build_features()
    features[0]["permissions"] = ["product:read"]
    assert any("permissions differ" in e for e in _errors(build_nodes(), features))

    features = build_features()
    features[1]["locked"] = True
    assert any("locked differs" in e for e in _errors(build_nodes(), features))

    features = build_features()
    features[2]["api_prefixes"] = ["/api/not-a-feature"]
    assert any("api_prefixes differ" in e for e in _errors(build_nodes(), features))


def test_feature_references_are_checked_everywhere():
    features = build_features()
    features[0]["depends_on"] = ["ghost"]
    assert any("unknown feature 'ghost'" in e for e in _errors(build_nodes(), features))

    features = build_features()
    features[0]["depends_on"] = ["stock"]
    features[1]["depends_on"] = ["products"]
    assert any("dependency cycle" in e for e in _errors(build_nodes(), features))


def test_undeclared_screen_feature_mapping_is_rejected():
    nodes = build_nodes()
    screen = next(n for n in nodes if n["view"] == "products")
    screen["feature_key"] = "stock"
    errors = _errors(nodes)
    assert any("undeclared feature mapping" in e for e in errors), errors


def test_missing_switch_row_and_registry_row_are_independent():
    # Deleting the registry row is refused; deleting a switch row is not even
    # visible to the registry validator because the two are not linked.
    features = build_features()
    features = features[1:]                     # drop `products`
    errors = _errors(build_nodes(), features)
    assert any("feature rows differ" in e for e in errors)
    assert any("feature not registered" in e for e in errors)


# ------------------------------------------------------------------ visibility
def test_permission_and_feature_filtering():
    nodes = build_nodes()
    none = visible_keys(nodes, set(), lambda key: True)
    assert {n["node_key"] for n in nodes if n["kind"] == "screen"} & none == {
        next(n["node_key"] for n in nodes if n["view"] == "dash"),
        next(n["node_key"] for n in nodes if n["view"] == "settings"),
        next(n["node_key"] for n in nodes if n["view"] == "reports"),
    }
    admin = visible_keys(nodes, {"user:manage", "sales:read", "hr:read"}, lambda key: True)
    assert next(n["node_key"] for n in nodes if n["view"] == "users") in admin
    assert next(n["node_key"] for n in nodes if n["view"] == "leads") not in admin


def test_inactive_parent_hides_its_children():
    nodes = build_nodes()
    module = next(n for n in nodes if n["node_key"] == "sales")
    module["active"] = False
    visible = visible_keys(nodes, {"sales:read"}, lambda key: True)
    assert not any(key == "sales" or key.startswith("sales/") for key in visible)


# ------------------------------------------------------------------ cache identity
def test_fingerprint_and_etag_include_registry_user_and_switches():
    nodes, features = build_nodes(), build_features()
    base = registry_fingerprint(nodes, features)
    changed = copy.deepcopy(nodes)
    changed[0]["label"] = "Overview and more"
    assert registry_fingerprint(changed, features) != base

    etag = dict(user_id=1, permissions={"sales:read"}, enabled_features={"sales"},
                favourites=[], recent=[], fingerprint=base)
    first = navigation_etag(**etag)
    assert navigation_etag(**{**etag, "enabled_features": {"sales", "hr"}}) != first
    assert navigation_etag(**{**etag, "permissions": {"sales:read", "hr:read"}}) != first
    assert navigation_etag(**{**etag, "user_id": 2}) != first
    assert navigation_etag(**{**etag, "admin": True}) != first
    assert navigation_etag(**etag) == first


def test_admin_only_screens_are_removed_for_every_other_role():
    nodes = build_nodes()
    visible = {n["node_key"] for n in nodes}
    admin_view = narrow_admin_only(visible, nodes, admin=True)
    other_view = narrow_admin_only(visible, nodes, admin=False)
    assert other_view == admin_view - {"finance/insight/reports/scheduled"}
    assert admin_view == visible


def test_admin_only_narrowing_keeps_home_and_the_alias():
    nodes = build_nodes()
    visible = {n["node_key"] for n in nodes}
    narrowed = narrow_admin_only(visible, nodes, admin=False)
    home = next(n for n in nodes if n["is_home"])
    assert home["node_key"] in narrowed
    customers = next(n for n in nodes if n["view"] == "customers")
    assert customers["node_key"] in narrowed


# ------------------------------------------------------------------ gated DB tests
ACTIVE = (ROOT / "alembic" / "versions" / "0031_navigation_registry.py").exists()
needs_migration = pytest.mark.skipif(
    not ACTIVE, reason="0031 is an inactive .py.draft; activate it only after approval")


@needs_migration
def test_migration_seed_matches_the_catalogue(database):
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        nodes = [dict(row) for row in db.execute(text(
            "SELECT id, parent_id, depth, node_key, label, kind, view, route, "
            "component_key, feature_key, permission_any, menu_rule, menu_any, "
            "aliases, is_home, sort_order, active FROM nav_nodes ORDER BY id")).mappings()]
        features = [dict(row) for row in db.execute(text(
            "SELECT feature_key, label, description, status, locked, api_prefixes, "
            "tables, permissions, depends_on FROM feature_registry "
            "ORDER BY feature_key")).mappings()]
    assert [n["node_key"] for n in nodes] == [n["node_key"] for n in build_nodes()]
    assert validate_catalog(nodes, features) == []


@needs_migration
def test_deleting_every_switch_row_leaves_the_registry_intact(database):
    from app.core.db import SessionLocal
    from app.models.settings import FeatureFlag
    with SessionLocal() as db:
        db.execute(text("DELETE FROM feature_flags"))
        db.flush()
        assert db.scalar(select(func.count()).select_from(FeatureRegistry)) == 14
        assert db.scalar(select(func.count()).select_from(NavNode)) == 64
        fks = db.execute(text(
            "SELECT parent.relname FROM pg_constraint k "
            "JOIN pg_class child ON child.oid = k.conrelid "
            "JOIN pg_class parent ON parent.oid = k.confrelid "
            "WHERE k.contype = 'f' AND child.relname IN "
            "('nav_nodes', 'feature_registry')")).scalars().all()
        assert "feature_flags" not in fks
        db.rollback()


@needs_migration
def test_downgrade_and_reupgrade_are_covered_by_the_verify_script():
    script = (ROOT / "scripts" / "verify_navigation_migration.py").read_text(encoding="utf-8")
    assert "0031_navigation_registry" in script
    assert '"downgrade", "0030_sign_in_content"' in script
    assert "herbanova_nav_migration_scratch_test" in script
