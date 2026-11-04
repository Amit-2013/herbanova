"""Prove the navigation catalogue matches the shipped menu, and emit the evidence.

Reads three sources and compares them without opening a database:

* ``app/services/navigation_catalog.py`` — the canonical 64 nav rows / 14
  feature rows that migration 0031 embeds;
* the literal seed block inside the active ``0031_navigation_registry.py``
  (or its ``.py.draft`` before activation) — the rows the migration inserts;
* ``static/js/workspace.js`` (through ``tests/js/emit_nav_manifest.cjs``) and
  ``static/js/app.js`` — the browser's menu, routes and Accounts sections.

Result is one JSON document. Run from the repository root (imports, Node
helpers and relative ``--out`` paths are resolved against it):

    python scripts/navigation_parity_report.py
    python scripts/navigation_parity_report.py --out var/reports/wp4a-catalogue-parity.json

Exit code 0 when every check passes, 1 otherwise. Read-only: nothing is
migrated, no database is opened.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.features import FEATURE_BY_KEY  # noqa: E402
from app.core.permissions import PERMISSION_KEYS  # noqa: E402
from app.services.navigation_catalog import (  # noqa: E402
    ACCOUNTS_SECTION_COUNT, ALIASES, EXPECTED_COUNTS, HOME_VIEW, NAV,
    VIEWS, build_features, build_nodes, catalog_counts,
)
from app.services.navigation_registry import validate_catalog  # noqa: E402

SOURCE = ROOT / "alembic" / "versions" / "0031_navigation_registry.py"
if not SOURCE.exists():
    SOURCE = SOURCE.with_name(SOURCE.name + ".draft")
APP_JS = ROOT / "static" / "js" / "app.js"
DEFAULT_OUT = ROOT / "var" / "reports" / "wp4a-catalogue-parity.json"


class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check_id: str, ok: bool, detail: str, evidence=None) -> None:
        self.checks.append({"id": check_id, "status": "pass" if ok else "fail",
                            "detail": detail, "evidence": evidence})

    @property
    def failures(self) -> list[dict]:
        return [c for c in self.checks if c["status"] != "pass"]


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _load_seed():
    if not SOURCE.exists():
        raise SystemExit(f"missing migration source: {SOURCE}")
    loader = SourceFileLoader("migration_0031_parity", str(SOURCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.NAV_NODES, module.FEATURE_ROWS


def _manifest() -> dict:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("Node.js is not installed; the frontend parity cannot be checked")
    spec = {"base": {view: list(v.permission_any) for view, v in VIEWS.items()},
            "candidates": sorted(PERMISSION_KEYS)}
    result = subprocess.run([node, "tests/js/emit_nav_manifest.cjs", json.dumps(spec)],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise SystemExit(f"emitter failed:\n{result.stderr}")
    return json.loads(result.stdout)


def _catalogue_nav() -> list[dict]:
    return [{
        "id": module_id, "label": module_label,
        "categories": [{
            "id": category_id, "label": category_label,
            "groups": [{"id": group_id, "label": group_label, "views": list(views)}
                       for group_id, group_label, views in groups],
        } for category_id, category_label, groups in categories],
    } for module_id, module_label, categories in NAV]


def _dupes(values) -> list[str]:
    seen, out = set(), []
    for value in values:
        if value in seen and value not in out:
            out.append(str(value))
        seen.add(value)
    return out


def _acc_sections() -> tuple[list[str], int]:
    text = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"const ACC_SECTIONS = \[(.*?)\n\];", text, re.S)
    line = text[:match.start()].count("\n") + 1 if match else 0
    keys = re.findall(r'\{key:\s*"([^"]+)"', match.group(1)) if match else []
    return keys, line


def build_report() -> dict:
    report = Report()
    nodes = build_nodes()
    features = build_features()
    seed_nodes, seed_features = _load_seed()
    manifest = _manifest()
    screens = [n for n in nodes if n["kind"] == "screen"]

    # ---------------------------------------------------------------- counts
    counts = catalog_counts()
    rows = {"nav_nodes": len(nodes), "feature_registry": len(features),
            "generated_seed_rows": len(seed_nodes) + len(seed_features)}
    report.add("counts", counts == EXPECTED_COUNTS and rows["generated_seed_rows"] == 78,
               f"{counts}; {rows['generated_seed_rows']} generated seed rows",
               {"catalogue": counts, "expected": EXPECTED_COUNTS, "rows": rows})

    report.add("catalogue_valid", validate_catalog(nodes, features) == [],
               "validate_catalog returns no errors",
               validate_catalog(nodes, features))

    # ------------------------------------------------------- seed literal
    same_nodes = seed_nodes == nodes
    same_features = seed_features == features
    report.add("seed_literal_matches_catalogue", same_nodes and same_features,
               "the migration seed literal equals build_nodes()/build_features()",
               {"nodes_equal": same_nodes, "features_equal": same_features,
                "seed_node_keys": [n["node_key"] for n in seed_nodes][:3] + ["..."]})

    # ------------------------------------------------------------ duplicates
    dup_keys = _dupes([n["node_key"] for n in nodes])
    dup_routes = _dupes([n["route"] for n in screens])
    dup_views = _dupes([n["view"] for n in screens])
    dup_features = _dupes([f["feature_key"] for f in features])
    dup_sort = [f"{parent}:{order}" for parent in {n["parent_id"] for n in nodes}
                for order in _dupes([n["sort_order"] for n in nodes
                                     if n["parent_id"] == parent])]
    dup_aliases = _dupes([a for n in nodes for a in n["aliases"]])
    duplicates = {"node_key": dup_keys, "route": dup_routes, "view": dup_views,
                  "feature_key": dup_features, "sort_order": dup_sort,
                  "alias": dup_aliases}
    report.add("no_duplicates", not any(duplicates.values()),
               "no duplicate node_key, route, view, feature_key, sibling "
               "sort_order or alias", duplicates)

    # --------------------------------------------------------------- orphans
    by_id = {n["id"]: n for n in nodes}
    by_key = {n["node_key"]: n for n in nodes}
    orphan_parents = [n["node_key"] for n in nodes
                      if n["parent_id"] is not None and n["parent_id"] not in by_id]
    unknown_features = sorted({n["feature_key"] for n in nodes
                               if n["feature_key"] and n["feature_key"] not in FEATURE_BY_KEY})
    unregistered_features = sorted({n["feature_key"] for n in nodes
                                    if n["feature_key"] and n["feature_key"]
                                    not in {f["feature_key"] for f in features}})
    alias_targets_bad = sorted({a: target for a, target in ALIASES.items()
                                if target not in by_key}.items())
    feature_rows_missing = sorted(set(FEATURE_BY_KEY) - {f["feature_key"] for f in features})
    feature_rows_extra = sorted({f["feature_key"] for f in features} - set(FEATURE_BY_KEY))
    orphans = {"parent_missing": orphan_parents,
               "unknown_feature_on_node": unknown_features,
               "feature_not_registered": unregistered_features,
               "alias_target_missing": [list(x) for x in alias_targets_bad],
               "feature_rows_missing": feature_rows_missing,
               "feature_rows_extra": feature_rows_extra}
    report.add("no_orphans", not any(orphans.values()),
               "every parent, feature reference and alias target resolves",
               orphans)

    # ------------------------------------------------------------ permissions
    used = sorted({key for n in nodes for field in ("permission_any", "menu_any")
                   for key in n[field]})
    unknown_used = sorted(set(used) - PERMISSION_KEYS)
    feature_perms = sorted({key for f in FEATURE_BY_KEY.values() for key in f.permissions})
    unknown_feature_perms = sorted(set(feature_perms) - PERMISSION_KEYS)
    report.add("permissions_known", not unknown_used and not unknown_feature_perms,
               f"{len(used)} nav permission keys and {len(feature_perms)} feature "
               "permission keys all exist in app/core/permissions.py",
               {"used": used, "unknown": unknown_used,
                "feature_permissions": feature_perms,
                "unknown_feature": unknown_feature_perms,
                "backend_key_count": len(PERMISSION_KEYS)})

    # ---------------------------------------------------------------- routes
    route_mismatch = {n["view"]: manifest["routes"].get(n["view"])
                      for n in screens if manifest["routes"].get(n["view"]) != n["view"]}
    missing_title = {n["view"]: n["label"] for n in screens
                     if manifest["titles"].get(n["view"]) != n["label"]}
    frontend_views = {v for module in manifest["nav"] for cat in module["categories"]
                      for group in cat["groups"] for v in group["views"]}
    view_diff = {"missing_in_frontend": sorted({n["view"] for n in screens} - frontend_views),
                 "extra_in_frontend": sorted(frontend_views - {n["view"] for n in screens})}
    nav_equal = manifest["nav"] == _catalogue_nav()
    report.add("routes_and_menu", not route_mismatch and not missing_title
               and not any(view_diff.values()) and nav_equal,
               "every #/view route parses to itself, every label matches and the "
               "5/14/20/25 hierarchy is identical to workspace.js",
               {"route_mismatch": route_mismatch, "label_mismatch": missing_title,
                "view_diff": view_diff, "nav_equal": nav_equal,
                "route_count": len(manifest["routes"])})

    # --------------------------------------------------------------- feature map
    feature_map_bad = {n["view"]: [n["feature_key"], manifest["view_feature"].get(n["view"])]
                       for n in screens
                       if (manifest["view_feature"].get(n["view"]) or None) != n["feature_key"]}

    # viewAllowed has explicit OR rules for these views; the rest read VIEW_PERM.
    special = {"compare", "hr", "accounts", "scheduled", "reports", "settings"}
    perm_map_bad = {}
    allowed_bad = {}
    for node in screens:
        view = node["view"]
        perms = node["permission_any"]
        if view not in special:
            expected = perms[0] if perms else None
            if manifest["view_perm"].get(view) != expected:
                perm_map_bad[view] = [perms, manifest["view_perm"].get(view)]
        allowed = sorted(manifest["view_allowed_single"].get(view, []))
        expected_allowed = sorted(perms) if perms else sorted(PERMISSION_KEYS)
        if allowed != expected_allowed:
            allowed_bad[view] = [expected_allowed, allowed]

    menu_bad = {}
    for node in screens:
        view = node["view"]
        if node["menu_rule"] == "menu_any":
            expected = sorted(node["menu_any"])
            got = sorted(manifest["menu_single"].get(view, []))
            if got != expected:
                menu_bad[view] = [expected, got]
        elif bool(manifest["menu_base"].get(view)) != (node["menu_rule"] != "never"):
            menu_bad[view] = [node["menu_rule"], manifest["menu_base"].get(view)]
    report.add("view_permission_feature_menu_maps",
               not feature_map_bad and not perm_map_bad and not allowed_bad and not menu_bad,
               "VIEW_FEATURE, VIEW_PERM, the viewAllowed OR rules and the menu "
               "narrowing match the catalogue",
               {"feature": feature_map_bad, "permission": perm_map_bad,
                "view_allowed": allowed_bad, "menu": menu_bad})

    # ----------------------------------------------------------------- alias
    alias_ok = (ALIASES == {"distributors": "sales/parties/customer-master/customers"}
                and "distributors" not in {n["view"] for n in screens}
                and manifest["alias_customers"] == "customers"
                and any(n["view"] == "customers" and "distributors" in n["aliases"]
                        for n in screens))
    report.add("distributors_alias", alias_ok,
               "#/distributors resolves to the customers screen and is not a node",
               {"aliases": ALIASES, "frontend_parse": manifest["alias_customers"]})

    # ----------------------------------------------------- accounts sections
    acc_keys, acc_line = _acc_sections()
    acc_unique = len(set(acc_keys)) == len(acc_keys)
    parsed = subprocess.run(
        [shutil.which("node"), "-e",
         "const ws=require('./static/js/workspace.js');"
         "const keys=%s;const out={};"
         "keys.forEach(k=>{const p=ws.parseHash('#/accounts/'+k);"
         "out[k]=[p.view,p.section,p.key];});"
         "process.stdout.write(JSON.stringify(out));" % json.dumps(acc_keys)],
        cwd=ROOT, capture_output=True, text=True)
    acc_routes = json.loads(parsed.stdout) if parsed.returncode == 0 else {
        key: parsed.stderr for key in acc_keys}
    acc_route_bad = {key: val for key, val in acc_routes.items()
                     if not (isinstance(val, list) and val[0] == "accounts" and val[1] == key)}
    app_text = APP_JS.read_text(encoding="utf-8")
    acc_dispatch = 'state.view === "accounts"' in app_text and "ACC_SECTIONS" in app_text
    # A section key may equal a view name (`reports`): routing splits on `/`, so
    # `#/accounts/reports` is the section and `#/reports` is still the screen.
    acc_ok = (len(acc_keys) == ACCOUNTS_SECTION_COUNT == 19 and acc_unique
              and not acc_route_bad and acc_dispatch)
    report.add("accounts_sections", acc_ok,
               "the 19 accounting sub-sections stay code-driven, routable under "
               "#/accounts/<key> and rendered by the accounts route",
               {"count": len(acc_keys), "constant": ACCOUNTS_SECTION_COUNT,
                "app_js_line": acc_line, "keys": acc_keys,
                "bad_routes": acc_route_bad, "dispatched": acc_dispatch,
                "shared_with_view_name": sorted(set(acc_keys) & {n["view"] for n in screens})})

    # --------------------------------------------------------- home invariant
    home = [n for n in nodes if n["is_home"]]
    home_ok = (len(home) == 1 and home[0]["view"] == HOME_VIEW
               and manifest["home_hash"] == "#/" + HOME_VIEW
               and manifest["routes"].get(HOME_VIEW) == HOME_VIEW)
    report.add("home", home_ok, "exactly one Home screen, dashboard, matching workspace.js",
               {"home": [n["node_key"] for n in home], "view": HOME_VIEW,
                "frontend_tab_key": manifest["home"],
                "frontend_hash": manifest["home_hash"]})

    return {
        "report": "wp4a-catalogue-parity",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git": {"branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                "head": _git("rev-parse", "HEAD")},
        "inputs": {"catalogue": "app/services/navigation_catalog.py",
                   "seed_literal": str(SOURCE.relative_to(ROOT)),
                   "frontend": "static/js/workspace.js",
                   "accounts": "static/js/app.js"},
        "counts": rows | {"catalogue": counts, "expected": EXPECTED_COUNTS},
        "checks": report.checks,
        "failures": report.failures,
        "pass": not report.failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    data = build_report()
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")

    for check in data["checks"]:
        print(f"{check['status'].upper():4} {check['id']}: {check['detail']}")
    print(f"{len(data['checks'])} checks, {len(data['failures'])} failed -> {out}")
    return 0 if data["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
