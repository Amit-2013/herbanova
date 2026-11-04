"""The navigation and feature catalogue, mirroring the shipped menu exactly.

This module is data, not behaviour: it is the single place a WP-4 seed row or a
parity test reads. It imports `app.core.features` (which has no database
dependency) and nothing else, so `scripts/generate_navigation_seed.py` can run
without a live connection.

The rendered menu now comes from `GET /api/navigation` by default (WP-4d);
`static/js/workspace.js` still holds the built-in hierarchy as the fallback and
the pure model both paths render through. `tests/test_navigation_registry.py`
proves this catalogue and that file describe the same 5 modules, 14 categories,
20 groups, 25 screens, 14 features and one alias.

Two corrections are deliberate and reviewed in docs/FEATURE_REGISTRY_DESIGN.md:
`expenses` is owned by `accounts` and `roles` by `users` (the server's
`Feature.views` omits both), and `distributors` is an alias of `customers`, never
a node. No screen, route or feature is added or removed here.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.features import FEATURES


HOME_VIEW = "dash"
EXPECTED_COUNTS = {
    "modules": 5,
    "categories": 14,
    "groups": 20,
    "screens": 25,
    "features": 14,
}


@dataclass(frozen=True)
class View:
    label: str
    feature: str | None
    permission_any: tuple[str, ...] = ()
    menu_rule: str = "always"
    menu_any: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    is_home: bool = False


# Exactly `TITLES`, `VIEW_PERM`, `VIEW_FEATURE`, `MENU_EXTRA` and
# `NOT_IN_MENU` in static/js/workspace.js. `reports` and `settings` have no
# route permission (any signed-in user may open them) and are narrowed only in
# the rail by `menu_any`.
VIEWS: dict[str, View] = {
    "dash": View("Overview", None, is_home=True),
    "compare": View("MoM & YoY dashboard", "reports",
                    ("sales:read", "stock:read"), menu_rule="never"),
    "leads": View("Leads", "leads", ("lead:read",)),
    "lost": View("Lost leads", "leads", ("lead:read",)),
    "followups": View("Today's follow-ups", "leads", ("lead:read",)),
    "sales": View("Sales orders", "sales", ("sales:read",)),
    "billing": View("Billing", "sales", ("sales:read",)),
    "approvals": View("Approvals", "approvals", ("approval:read",)),
    "customers": View("Customers and distributors", "sales", ("sales:read",),
                      aliases=("distributors",)),
    "purchasing": View("Purchases", "stock", ("stock:read",)),
    "suppliers": View("Suppliers", "suppliers", ("supplier:read",)),
    "products": View("Products", "products", ("product:read",)),
    "inventory": View("Inventory", "stock", ("stock:read",)),
    "foc": View("Free samples (FOC)", "foc", ("foc:read",)),
    "accounts": View("Accounting & Finance", "accounts",
                     ("accounts:read", "accounts:reports")),
    "expenses": View("Expenses", "accounts", ("expense:read",)),
    "tax": View("Tax and discounts", "tax", ("tax:read",), menu_rule="never"),
    "reports": View("Reports", "reports", (),
                    menu_rule="menu_any",
                    menu_any=("accounts:read", "hr:reports", "sales:read",
                              "stock:read", "supplier:read", "tax:read")),
    "scheduled": View("Scheduled reports", "scheduled", ("email:manage",)),
    "geo": View("Geography", "sales", ("sales:read",)),
    "hr": View("HR Management", "hr", ("hr:read", "hr:attendance_self")),
    "users": View("Logins and employees", "users", ("user:manage",),
                  menu_rule="never"),
    "roles": View("Roles & Permissions", "users", ("user:manage",)),
    "audit": View("Audit trail", "audit", ("audit:read",), menu_rule="never"),
    "settings": View("Settings & Administration", None, (),
                     menu_rule="menu_any",
                     menu_any=("user:manage", "tax:read", "audit:read", "hr:read")),
}

# Screens whose routes are guarded by `require_admin` rather than a permission
# alone (app/core/rbac.py). The registry can record a permission but not a role,
# and `email:manage` is refused to custom roles — yet a row written outside the
# Roles API (restored dump, direct SQL) could still carry it. The navigation
# endpoint removes these screens for every caller who is not the Administrator,
# so the menu never offers a screen whose requests would all answer 403.
ADMIN_ONLY_VIEWS: frozenset[str] = frozenset({"scheduled"})

# (module id, label) -> (category id, label) -> (group id, label) -> views.
# The empty group label is the shipped one: the breadcrumb omits it.
NAV = (
    ("overview", "Overview", (
        ("dashboard", "Dashboard", (
            ("workspace", "", ("dash", "compare")),
        )),
    )),
    ("sales", "Sales and customers", (
        ("pipeline", "Pipeline", (
            ("lead-desk", "Lead desk", ("leads", "lost", "followups")),
        )),
        ("sales", "Sales", (
            ("order-desk", "Order desk", ("sales",)),
            ("invoicing", "Invoicing", ("billing",)),
            ("approvals", "Approvals", ("approvals",)),
        )),
        ("parties", "Parties", (
            ("customer-master", "Customer master", ("customers",)),
        )),
    )),
    ("stock", "Stock and supply", (
        ("buying", "Buying", (
            ("purchase-desk", "Purchase desk", ("purchasing",)),
        )),
        ("parties", "Parties", (
            ("supplier-master", "Supplier master", ("suppliers",)),
        )),
        ("inventory", "Inventory", (
            ("masters", "Masters", ("products",)),
            ("stock", "Stock", ("inventory", "foc")),
        )),
    )),
    ("finance", "Finance and insight", (
        ("books", "Books", (
            ("ledgers", "Ledgers", ("accounts",)),
        )),
        ("spend", "Spend", (
            ("expenses", "Expenses", ("expenses",)),
        )),
        ("tax", "Tax", (
            ("tax-master", "Tax master", ("tax",)),
        )),
        ("insight", "Insight", (
            ("reports", "Reports", ("reports", "scheduled")),
            ("analytics", "Analytics", ("geo",)),
        )),
    )),
    ("people", "People and admin", (
        ("people", "People", (
            ("hr", "HR", ("hr",)),
        )),
        ("access", "Access", (
            ("logins", "Logins", ("users",)),
            ("permissions", "Permissions", ("roles",)),
        )),
        ("governance", "Governance", (
            ("audit", "Audit", ("audit",)),
            ("settings", "Settings", ("settings",)),
        )),
    )),
)

# The 19 accounting sub-sections are not navigation nodes. They stay in
# static/js/app.js `ACC_SECTIONS`, rendered inside the single `accounts` screen.
# WP-4a does not map them and must not claim to.
ACCOUNTS_SECTION_COUNT = 19


def iter_nav():
    """Yield (depth, kind, path ids, label, view) in menu order."""
    for module_id, module_label, categories in NAV:
        yield 1, "module", (module_id,), module_label, None
        for category_id, category_label, groups in categories:
            yield 2, "category", (module_id, category_id), category_label, None
            for group_id, group_label, views in groups:
                path = (module_id, category_id, group_id)
                yield 3, "group", path, group_label, None
                for view in views:
                    yield 4, "screen", path + (view,), VIEWS[view].label, view


def build_nodes() -> list[dict]:
    """The 64 nav_nodes rows, depth-first, with stable integer ids."""
    rows: list[dict] = []
    ids: dict[tuple[str, ...], int] = {}
    sibling_index: dict[tuple[str, ...], int] = {}
    for depth, kind, path, label, view in iter_nav():
        parent_path = path[:-1]
        node_id = len(rows) + 1
        ids[path] = node_id
        order = sibling_index.get(parent_path, 0) + 1
        sibling_index[parent_path] = order
        spec = VIEWS[view] if view is not None else None
        rows.append({
            "id": node_id,
            "parent_id": ids.get(parent_path) if parent_path else None,
            "depth": depth,
            "node_key": "/".join(path),
            "label": label,
            "kind": kind,
            "view": view,
            "route": ("#/" + view) if view is not None else None,
            "component_key": view,
            "feature_key": spec.feature if spec else None,
            "permission_any": list(spec.permission_any) if spec else [],
            "menu_rule": spec.menu_rule if spec else "always",
            "menu_any": list(spec.menu_any) if spec else [],
            "aliases": list(spec.aliases) if spec else [],
            "is_home": bool(spec and spec.is_home),
            "sort_order": order,
            "active": True,
        })
    return rows


def build_features() -> list[dict]:
    """The 14 feature_registry rows, copied from app/core/features.py.

    `tables` is empty for every row on purpose: the code maps features to API
    prefixes, not model tables, and inventing a table list would be a guess.
    WP-5 fills it from a verified derivation, or the column is dropped then.
    """
    return [{
        "feature_key": feature.key,
        "label": feature.label,
        "description": feature.description,
        "status": "active",
        "locked": feature.locked,
        "api_prefixes": list(feature.api_prefixes),
        "tables": [],
        "permissions": sorted(feature.permissions),
        "depends_on": [],
    } for feature in FEATURES]


def catalog_counts() -> dict:
    nodes = build_nodes()
    return {
        "modules": sum(1 for n in nodes if n["kind"] == "module"),
        "categories": sum(1 for n in nodes if n["kind"] == "category"),
        "groups": sum(1 for n in nodes if n["kind"] == "group"),
        "screens": sum(1 for n in nodes if n["kind"] == "screen"),
        "features": len(build_features()),
    }


# Aliases are inline in nav_nodes.aliases, so the database has one row per
# screen and no fourth table. The registry refuses a collision with a node key
# or a view key.
ALIASES: dict[str, str] = {
    alias: node["node_key"]
    for node in build_nodes() if node["kind"] == "screen"
    for alias in node["aliases"]
}
