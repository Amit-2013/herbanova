"""Navigation as the server sees it (WP-4b).

`GET /api/navigation` is the read-only contract in
docs/FEATURE_REGISTRY_DESIGN.md §6.1. It returns the part of the registered
menu the caller may open, already narrowed by the effective permissions and by
the feature switches, plus the protected Home screen, the available feature
keys and the caller's permissions.

The browser reads this endpoint by default since WP-4d; `workspace.js` keeps the
built-in hierarchy as the fallback and the failure path. The endpoint writes no
audit row and no business row: opening a screen is not a security event
(design D12).

`GET /api/admin/navigation` (§6.3) is the read-only administrative view of the
same two tables. Editing waits for WP-5.

Cache identity follows §6.1: the registry fingerprint, the user, the effective
permissions, the available features, favourites and recents. The ETag is
therefore per user, and `Cache-Control: private, no-cache` plus `Vary: Cookie`
keeps a shared cache from serving one user's menu to another.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import (is_admin, require_admin, require_login,
                         role_permissions)
from ..services.navigation_registry import (in_menu, narrow_admin_only,
                                            navigation_etag, registry_fingerprint,
                                            validate_catalog, visible_keys)
from ..services.navigation_store import feature_available, load_registry

router = APIRouter(tags=["navigation"])

UNAVAILABLE = "Navigation registry unavailable"

SCREEN_FIELDS = ("node_key", "label", "view", "route", "component_key",
                 "feature_key", "is_home", "aliases")


def _screen(node: dict, permissions: set[str]) -> dict:
    screen = {field: node[field] for field in SCREEN_FIELDS}
    screen["in_menu"] = in_menu(node, permissions)
    return screen


def _build_tree(nodes: list[dict], visible: set[str], permissions: set[str]) -> list[dict]:
    """Modules → categories → groups → screens, empty branches removed.

    A container is kept only when a screen the caller may open sits under it,
    so the response cannot disclose the name of a branch that is closed to them.
    """
    children: dict[int | None, list[dict]] = {}
    for node in nodes:
        if node["node_key"] in visible:
            children.setdefault(node["parent_id"], []).append(node)
    for rows in children.values():
        rows.sort(key=lambda n: (n["sort_order"], n["id"]))

    def of_kind(node: dict, kind: str) -> list[dict]:
        return [child for child in children.get(node["id"], []) if child["kind"] == kind]

    def group(node: dict) -> dict:
        return {"node_key": node["node_key"], "label": node["label"],
                "screens": [_screen(s, permissions) for s in of_kind(node, "screen")]}

    def category(node: dict) -> dict:
        groups = [group(g) for g in of_kind(node, "group")]
        return {"node_key": node["node_key"], "label": node["label"],
                "groups": [g for g in groups if g["screens"]]}

    def module(node: dict) -> dict:
        categories = [category(c) for c in of_kind(node, "category")]
        return {"node_key": node["node_key"], "label": node["label"],
                "categories": [c for c in categories if c["groups"]]}

    modules = [module(m) for m in (children.get(None) or []) if m["kind"] == "module"]
    return [m for m in modules if m["categories"]]


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    for candidate in if_none_match.split(","):
        candidate = candidate.strip()
        if candidate.startswith("W/"):
            candidate = candidate[2:].strip()
        if candidate == "*" or candidate == etag:
            return True
    return False


def _load_or_503(db: Session):
    loaded = load_registry(db)
    if loaded is None:
        raise HTTPException(503, UNAVAILABLE)
    nodes, features, flags = loaded
    if validate_catalog(nodes, features):
        raise HTTPException(503, UNAVAILABLE)
    return nodes, features, flags


@router.get("/api/navigation")
def get_navigation(request: Request, db: Session = Depends(get_db),
                   user=Depends(require_login)):
    nodes, features, flags = _load_or_503(db)
    available = feature_available(features, flags)
    permissions = role_permissions(db, user)
    admin = is_admin(db, user)
    visible = narrow_admin_only(
        visible_keys(nodes, permissions, lambda key: key in available),
        nodes, admin=admin)

    home_node = next(node for node in nodes if node["is_home"])
    body = {
        "modules": _build_tree(nodes, visible, permissions),
        "home": _screen(home_node, permissions),
        "features": sorted(available),
        "permissions": sorted(permissions),
        # Device-local favourites (D8) and recents (D13) are not stored on the
        # server yet; the keys are present so the shape is stable for WP-4c.
        "favourites": [],
        "recent": [],
    }
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    etag = navigation_etag(
        user_id=user.id, permissions=permissions, enabled_features=available,
        favourites=[], recent=[],
        fingerprint=registry_fingerprint(nodes, features), admin=admin)
    headers = {"ETag": etag, "Cache-Control": "private, no-cache", "Vary": "Cookie"}
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="application/json", headers=headers)


@router.get("/api/admin/navigation")
def get_navigation_registry(db: Session = Depends(get_db),
                            _=Depends(require_admin("user:manage"))):
    """Raw registry rows plus the validation result, for the Administrator.

    An invalid registry is returned with `errors` rather than a 503: this is
    the screen an administrator would use to see what is wrong. The public
    endpoint still refuses to render half a menu.
    """
    loaded = load_registry(db)
    if loaded is None:
        raise HTTPException(503, UNAVAILABLE)
    nodes, features, flags = loaded
    counts = {
        name: sum(1 for node in nodes if node["kind"] == kind)
        for name, kind in (("modules", "module"), ("categories", "category"),
                           ("groups", "group"), ("screens", "screen"))
    }
    counts["features"] = len(features)
    body = {
        "nodes": nodes,
        "features": [{**row,
                      "enabled": True if row["locked"]
                      else flags.get(row["feature_key"], True)}
                     for row in features],
        "counts": counts,
        "fingerprint": registry_fingerprint(nodes, features),
        "errors": validate_catalog(nodes, features),
    }
    return Response(content=json.dumps(body, ensure_ascii=False,
                                       separators=(",", ":")).encode("utf-8"),
                    media_type="application/json",
                    headers={"Cache-Control": "no-store"})
