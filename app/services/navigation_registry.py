"""Validation, visibility and cache identity for the navigation registry.

Pure functions over the row dictionaries produced by `navigation_catalog` (or
read from the two tables). Both navigation endpoints use this at runtime:
`GET /api/navigation` calls `visible_keys`, `narrow_admin_only` and
`navigation_etag`; the admin read uses `validate_catalog`.

Registration and switch state are independent by design (R-01). Visibility
asks `is_feature_enabled`, which is `feature_store.is_enabled` in production and
a plain callable in tests. Nothing here enables, disables, or writes a flag.
"""
from __future__ import annotations

import hashlib
import json

from ..core.features import FEATURE_BY_KEY, FEATURES
from ..core.permissions import PERMISSION_KEYS
from .navigation_catalog import (ADMIN_ONLY_VIEWS, EXPECTED_COUNTS, HOME_VIEW,
                                 build_features, build_nodes)

# Views the browser maps to a feature but `Feature.views` does not declare
# (design D-01). Kept explicit so a new silent mapping fails validation.
DOCUMENTED_VIEW_ADDITIONS = {"expenses": "accounts", "roles": "users"}


def _dupes(values) -> list[str]:
    seen, out = set(), []
    for value in values:
        if value in seen and value not in out:
            out.append(value)
        seen.add(value)
    return out


def validate_catalog(nodes: list[dict], features: list[dict],
                     *, strict_counts: bool = True) -> list[str]:
    """Every rule the design promises, as a list of human-readable errors."""
    errors: list[str] = []
    by_id = {n["id"]: n for n in nodes}
    by_key = {n["node_key"]: n for n in nodes}

    # --- identity and shape -------------------------------------------------
    if len(by_id) != len(nodes):
        errors.append("duplicate nav node id")
    for key in _dupes([n["node_key"] for n in nodes]):
        errors.append(f"duplicate node_key: {key}")
    for node in nodes:
        if node["kind"] not in ("module", "category", "group", "screen"):
            errors.append(f"{node['node_key']}: unknown kind {node['kind']!r}")
        if node["depth"] not in (1, 2, 3, 4):
            errors.append(f"{node['node_key']}: depth outside 1..4")
        if node["menu_rule"] not in ("always", "never", "menu_any"):
            errors.append(f"{node['node_key']}: unknown menu_rule")
        if node["sort_order"] < 0:
            errors.append(f"{node['node_key']}: negative sort_order")
        for field in ("permission_any", "menu_any", "aliases"):
            if not isinstance(node[field], list):
                errors.append(f"{node['node_key']}: {field} must be a list")

    if strict_counts:
        counts = {
            "modules": sum(1 for n in nodes if n["kind"] == "module"),
            "categories": sum(1 for n in nodes if n["kind"] == "category"),
            "groups": sum(1 for n in nodes if n["kind"] == "group"),
            "screens": sum(1 for n in nodes if n["kind"] == "screen"),
            "features": len(features),
        }
        for name, expected in EXPECTED_COUNTS.items():
            if counts[name] != expected:
                errors.append(f"{name}: {counts[name]} rows, expected {expected}")

    # --- hierarchy ----------------------------------------------------------
    for node in nodes:
        parent = by_id.get(node["parent_id"]) if node["parent_id"] is not None else None
        if node["depth"] == 1:
            if node["parent_id"] is not None:
                errors.append(f"{node['node_key']}: a module must have no parent")
            continue
        if parent is None:
            errors.append(f"{node['node_key']}: parent does not exist")
            continue
        if parent["id"] == node["id"]:
            errors.append(f"{node['node_key']}: node is its own parent")
            continue
        if parent["depth"] + 1 != node["depth"]:
            errors.append(f"{node['node_key']}: depth {node['depth']} under "
                          f"depth {parent['depth']}")
        if node["node_key"].rsplit("/", 1)[0] != parent["node_key"]:
            errors.append(f"{node['node_key']}: key is not under {parent['node_key']}")

    for node in nodes:                       # cycles and unreachable parents
        seen, current = set(), node
        while current is not None:
            if current["id"] in seen:
                errors.append(f"{node['node_key']}: parent cycle")
                break
            seen.add(current["id"])
            current = by_id.get(current["parent_id"]) if current["parent_id"] else None

    for parent_key in {n["parent_id"] for n in nodes}:
        siblings = [n["sort_order"] for n in nodes if n["parent_id"] == parent_key]
        for order in _dupes(siblings):
            errors.append(f"duplicate sort_order {order} under parent {parent_key}")

    # --- screens, routes, aliases ------------------------------------------
    screens = [n for n in nodes if n["kind"] == "screen"]
    for key in _dupes([n["view"] for n in screens]):
        errors.append(f"duplicate screen view: {key}")
    for key in _dupes([n["route"] for n in screens]):
        errors.append(f"duplicate route: {key}")

    aliases: dict[str, str] = {}
    for node in nodes:
        if node["kind"] == "screen":
            if not node["view"] or not node["component_key"] or not node["route"]:
                errors.append(f"{node['node_key']}: screen fields incomplete")
                continue
            if node["route"] != "#/" + node["view"]:
                errors.append(f"{node['node_key']}: route must be #/{node['view']}")
            if node["component_key"] != node["view"]:
                errors.append(f"{node['node_key']}: component_key must equal view")
        elif any(node[f] is not None for f in ("view", "component_key", "route")):
            errors.append(f"{node['node_key']}: non-screen carries screen fields")
        for alias in node["aliases"]:
            if not isinstance(alias, str) or not alias.strip():
                errors.append(f"{node['node_key']}: empty alias")
            elif alias in aliases:
                errors.append(f"alias {alias!r} used twice")
            else:
                aliases[alias] = node["node_key"]

    reserved = {n["node_key"] for n in nodes} | {n["view"] for n in screens if n["view"]}
    for alias in aliases:
        if alias in reserved:
            errors.append(f"alias {alias!r} collides with a node key or view")
    for node in nodes:
        if any(segment in aliases for segment in node["node_key"].split("/")):
            errors.append(f"{node['node_key']}: alias used as a key segment")

    # --- permissions and feature references --------------------------------
    for node in nodes:
        for field in ("permission_any", "menu_any"):
            for key in node[field]:
                if key not in PERMISSION_KEYS:
                    errors.append(f"{node['node_key']}: unknown {field} key {key!r}")
            for key in _dupes(node[field]):
                errors.append(f"{node['node_key']}: duplicate {field} key {key!r}")
        if node["menu_rule"] == "menu_any" and not node["menu_any"]:
            errors.append(f"{node['node_key']}: menu_any needs at least one key")
        if node["menu_rule"] != "menu_any" and node["menu_any"]:
            errors.append(f"{node['node_key']}: menu_any set but rule is {node['menu_rule']}")
        if node["feature_key"] is not None and node["feature_key"] not in FEATURE_BY_KEY:
            errors.append(f"{node['node_key']}: unknown feature {node['feature_key']!r}")

    # --- protected Home -----------------------------------------------------
    homes = [n for n in nodes if n["is_home"]]
    if len(homes) != 1:
        errors.append(f"exactly one Home node is required, found {len(homes)}")
    for home in homes:
        if (home["view"] != HOME_VIEW or home["depth"] != 4
                or not home["active"] or home["feature_key"] is not None
                or home["permission_any"] or home["menu_rule"] != "always"):
            errors.append("Home must be one active, featureless, permissionless "
                          "screen in the rail")

    errors.extend(_validate_features(features))
    errors.extend(_validate_feature_views(nodes, features))
    return errors


def _validate_features(features: list[dict]) -> list[str]:
    errors: list[str] = []
    keys = [row["feature_key"] for row in features]
    for key in _dupes(keys):
        errors.append(f"duplicate feature_key: {key}")
    if set(keys) != set(FEATURE_BY_KEY):
        missing = sorted(set(FEATURE_BY_KEY) - set(keys))
        extra = sorted(set(keys) - set(FEATURE_BY_KEY))
        errors.append(f"feature rows differ from the catalogue: missing {missing}, extra {extra}")

    owners: dict[str, list[str]] = {}
    for row in features:
        key = row["feature_key"]
        feature = FEATURE_BY_KEY.get(key)
        if feature is None:
            continue                    # reported above
        if row["label"] != feature.label or row["description"] != feature.description:
            errors.append(f"{key}: label or description differs from features.py")
        if bool(row["locked"]) != feature.locked:
            errors.append(f"{key}: locked differs from features.py")
        if sorted(row["permissions"]) != sorted(feature.permissions):
            errors.append(f"{key}: permissions differ from features.py")
        if list(row["api_prefixes"]) != list(feature.api_prefixes):
            errors.append(f"{key}: api_prefixes differ from features.py")
        if row["status"] not in ("active", "planned", "retired"):
            errors.append(f"{key}: unknown status {row['status']!r}")
        if not isinstance(row["tables"], list) or not isinstance(row["depends_on"], list):
            errors.append(f"{key}: tables and depends_on must be lists")
        for prefix in row["api_prefixes"]:
            owners.setdefault(prefix, []).append(key)
        for dep in row["depends_on"]:
            if dep not in FEATURE_BY_KEY:
                errors.append(f"{key}: depends on unknown feature {dep!r}")
            if dep == key:
                errors.append(f"{key}: depends on itself")

    for prefix, keys in owners.items():
        if len(keys) > 1:
            errors.append(f"api prefix {prefix} owned by {sorted(set(keys))}")
    catalogue_prefixes = {p for f in FEATURES for p in f.api_prefixes}
    for prefix in sorted(set(owners) - catalogue_prefixes):
        errors.append(f"api prefix {prefix} is not in features.py")

    deps_by_key = {row["feature_key"]: list(row["depends_on"]) for row in features}
    done: set[str] = set()

    def has_cycle(key: str, path: set[str]) -> bool:
        if key in path:
            return True
        if key in done:
            return False
        for dep in deps_by_key.get(key, []):
            if has_cycle(dep, path | {key}):
                return True
        done.add(key)
        return False

    for row in features:
        if has_cycle(row["feature_key"], set()):
            errors.append(f"{row['feature_key']}: dependency cycle")
    return errors


def _validate_feature_views(nodes: list[dict], features: list[dict]) -> list[str]:
    """Every declared Feature.views entry maps to one node, and vice versa."""
    errors: list[str] = []
    screens = {n["view"]: n for n in nodes if n["kind"] == "screen"}
    by_key = {n["node_key"]: n for n in nodes}
    alias_target = {alias: n["node_key"] for n in nodes for alias in n["aliases"]}
    registry_keys = {row["feature_key"] for row in features}

    for feature in FEATURES:
        for view in feature.views:
            node = screens.get(view)
            if node is None and view in alias_target:
                node = by_key.get(alias_target[view])
            if node is None:
                errors.append(f"{feature.key}: declared view {view!r} has no node")
            elif node["feature_key"] != feature.key:
                errors.append(f"{feature.key}: view {view!r} is owned by "
                              f"{node['feature_key']!r}")

    for node in nodes:
        if node["kind"] != "screen" or not node["feature_key"]:
            continue
        if node["feature_key"] not in registry_keys:
            errors.append(f"{node['node_key']}: feature not registered")
        feature = FEATURE_BY_KEY.get(node["feature_key"])
        if feature is None:
            continue                     # unknown key is already reported
        declared = node["view"] in feature.views
        documented = DOCUMENTED_VIEW_ADDITIONS.get(node["view"]) == node["feature_key"]
        if not declared and not documented:
            errors.append(f"{node['node_key']}: undeclared feature mapping "
                          f"{node['view']} → {node['feature_key']}")
    return errors


def assert_valid(nodes: list[dict] | None = None, features: list[dict] | None = None) -> None:
    errors = validate_catalog(nodes or build_nodes(), features or build_features())
    if errors:
        raise ValueError("invalid navigation registry:\n- " + "\n- ".join(errors))


# ---------------------------------------------------------------- visibility
def visible_keys(nodes: list[dict], permissions: set[str],
                 is_feature_enabled) -> set[str]:
    """Keys of nodes the caller may open: active, ancestor-active, allowed."""
    by_id = {n["id"]: n for n in nodes}

    def active_chain(node) -> bool:
        seen = set()
        while node is not None and node["id"] not in seen:
            if not node["active"]:
                return False
            seen.add(node["id"])
            node = by_id.get(node["parent_id"]) if node["parent_id"] else None
        return True

    out = set()
    for node in nodes:
        if not active_chain(node):
            continue
        if node["feature_key"] and not is_feature_enabled(node["feature_key"]):
            continue
        if node["permission_any"] and not (set(node["permission_any"]) & permissions):
            continue
        out.add(node["node_key"])
    return out


def narrow_admin_only(visible: set[str], nodes: list[dict], *, admin: bool) -> set[str]:
    """Remove screens whose routes demand the Administrator role (design §6.5).

    The registry can record a permission but not a role. `scheduled` is guarded
    by `require_admin("email:manage")`, so a menu built from the permission
    alone could offer a screen the server refuses. The Administrator keeps it.
    """
    if admin:
        return visible
    view_of = {node["node_key"]: node["view"] for node in nodes}
    return {key for key in visible if view_of.get(key) not in ADMIN_ONLY_VIEWS}


def in_menu(node: dict, permissions: set[str]) -> bool:
    if node["menu_rule"] == "never":
        return False
    if node["menu_rule"] == "menu_any":
        return bool(set(node["menu_any"]) & permissions)
    return True


# ---------------------------------------------------------- cache identity
def registry_fingerprint(nodes: list[dict], features: list[dict]) -> str:
    """Deterministic hash of everything that changes the rendered registry.

    Used instead of a hand-bumped version column: an edit to a label, order,
    permission or switch mapping changes the hash by construction.
    """
    payload = {
        "nodes": [{k: n[k] for k in (
            "id", "parent_id", "depth", "node_key", "label", "kind", "view",
            "route", "component_key", "feature_key", "permission_any",
            "menu_rule", "menu_any", "aliases", "is_home", "sort_order",
            "active")} for n in nodes],
        "features": [{k: f[k] for k in (
            "feature_key", "label", "description", "status", "locked",
            "api_prefixes", "tables", "permissions", "depends_on")} for f in features],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def navigation_etag(*, user_id: int, permissions: set[str], enabled_features: set[str],
                    favourites: list[str], recent: list[str], fingerprint: str,
                    admin: bool = False) -> str:
    """ETag input: registry + user + switches + role class + preference state.

    A feature switch changes `enabled_features`, so a stale 304 is impossible.
    `admin` is part of the identity because the Administrator is the only role
    offered the admin-only screens; a role gaining or losing that status must
    not keep a cached body.
    """
    payload = {
        "registry": fingerprint,
        "user": user_id,
        "permissions": sorted(permissions),
        "features": sorted(enabled_features),
        "admin": bool(admin),
        "favourites": list(favourites),
        "recent": list(recent),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return '"' + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32] + '"'
