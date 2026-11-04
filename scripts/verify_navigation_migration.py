"""Rehearse 0028 → 0029 → 0030 → 0031 on a disposable scratch database.

Dry-run by default; `--run` is required to touch a database. The scratch
database name always ends in `_test`, is created by this script and dropped by
it after every piece of evidence has been collected. Nothing in the `.env`
database, development or production is opened, and the real `alembic/versions`
tree is not modified: the migration source is copied into a temporary script
directory and activated only there.

    python scripts/verify_navigation_migration.py            # print the plan
    python scripts/verify_navigation_migration.py --run      # rehearse

The run performs the 13 steps of the WP-4 Batch 4a rehearsal:

 1 create the scratch database
 2 upgrade to 0028        3 upgrade to 0029
 4 upgrade to 0030        5 upgrade to 0031 (temp tree only)
 6 verify both tables and every seeded row
 7 verify indexes, constraints, uniqueness and the self-referencing parent
 8 downgrade to 0030
 9 verify both new tables are gone and every earlier table is intact
10 re-upgrade to 0031
11 verify all 78 rows and the final Alembic version
12 five R-01 feature-switch behaviours against the live scratch database
13 drop the scratch database after the evidence JSON is written

Evidence: var/reports/wp4a-migration-rehearsal.json plus the console log.
Exit status is non-zero when any check fails.
"""
from __future__ import annotations

import argparse
import configparser
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.core.features import FEATURES  # noqa: E402
from app.models.navigation import FeatureRegistry, NavNode  # noqa: E402
from app.models.settings import FeatureFlag  # noqa: E402
from app.services import feature_store  # noqa: E402
from app.services.db_reset import (  # noqa: E402
    BUSINESS_TABLES, KEPT_TABLES, SCHEMA_TABLES,
)
from app.services.navigation_catalog import build_features, build_nodes  # noqa: E402
from app.services.navigation_registry import validate_catalog, visible_keys  # noqa: E402

SCRATCH_DB = "herbanova_nav_migration_scratch_test"
ACTIVE = ROOT / "alembic" / "versions" / "0031_navigation_registry.py"
SOURCE = ACTIVE if ACTIVE.exists() else ACTIVE.with_name(ACTIVE.name + ".draft")
DEFAULT_OUT = ROOT / "var" / "reports" / "wp4a-migration-rehearsal.json"
CHAIN = ("0028_advances", "0029_totp", "0030_sign_in_content",
         "0031_navigation_registry")
SAFE_IDENTIFIER = re.compile(r"^[a-z0-9_]+$")
EXPECTED_COUNTS = {"nav_nodes": 64, "feature_registry": 14, "home": 1,
                   "alias_rows": 1, "seed_rows": 78}

EXPECTED_INDEXES = {
    "nav_nodes": {"nav_nodes_pkey", "uq_nav_nodes_key", "ix_nav_nodes_parent_order",
                  "ix_nav_nodes_feature", "ix_nav_nodes_active", "ux_nav_nodes_home"},
    "feature_registry": {"feature_registry_pkey"},
}
EXPECTED_CONSTRAINTS = {
    "nav_nodes": {
        "nav_nodes_pkey", "nav_nodes_parent_id_fkey", "uq_nav_nodes_key",
        "ck_nav_nodes_depth", "ck_nav_nodes_kind_depth", "ck_nav_nodes_screen_view",
        "ck_nav_nodes_screen_route", "ck_nav_nodes_screen_component",
        "ck_nav_nodes_menu_rule", "ck_nav_nodes_sort", "ck_nav_nodes_home",
    },
    "feature_registry": {"feature_registry_pkey", "ck_feature_registry_status"},
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


class Rehearsal:
    def __init__(self) -> None:
        self.started_at = _now()
        self.steps: list[dict] = []
        self.data: dict = {}

    def step(self, step_id: str, detail: str, ok: bool = True, **extra) -> None:
        entry = {"n": len(self.steps) + 1, "id": step_id, "at": _now(),
                 "status": "pass" if ok else "fail", "detail": detail, **extra}
        self.steps.append(entry)
        print(f"[{entry['n']:02d}] {entry['status'].upper():4} {step_id}: {detail}")
        if not ok:
            raise RuntimeError(f"step {step_id} failed: {detail}")

    @property
    def failures(self) -> list[dict]:
        return [s for s in self.steps if s["status"] != "pass"]

    def result(self, **extra) -> dict:
        return {
            "report": "wp4a-migration-rehearsal",
            "started_at": self.started_at,
            "finished_at": _now(),
            "git": {"branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                    "head": _git("rev-parse", "HEAD")},
            "source": {"path": str(SOURCE.relative_to(ROOT)),
                       "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                       "active_py_exists_before": ACTIVE.exists(),
                       "active_py_exists_after": ACTIVE.exists()},
            "steps": self.steps,
            "failures": self.failures,
            "pass": not self.failures,
            **self.data,
            **extra,
        }


def _plan() -> None:
    print("target scratch database:", SCRATCH_DB)
    print("alembic chain:", " -> ".join(CHAIN))
    print("steps: create, 0028, 0029, 0030, 0031, seed, schema, downgrade, "
          "intact, re-upgrade, final version, R-01, drop")
    print("writes evidence to", DEFAULT_OUT.relative_to(ROOT))
    print("dry run; pass --run to execute")


def _scratch_url():
    url = make_url(settings.database_url).set(database=SCRATCH_DB)
    if not SAFE_IDENTIFIER.match(SCRATCH_DB):
        raise SystemExit("unsafe scratch database name")
    return url


def _admin_engine(scratch_url):
    return sa.create_engine(scratch_url.set(database="postgres"), isolation_level="AUTOCOMMIT")


def _create_database(scratch_url) -> dict:
    engine = _admin_engine(scratch_url)
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"),
                              {"name": SCRATCH_DB}).first()
        if exists:
            raise SystemExit(f"{SCRATCH_DB} already exists; refusing to overwrite it")
        conn.execute(text(f'CREATE DATABASE "{SCRATCH_DB}"'))
        version = conn.execute(text("SHOW server_version")).scalar_one()
    engine.dispose()
    return {"name": SCRATCH_DB, "created_at": _now(), "server_version": version}


def _drop_database(scratch_url) -> bool:
    engine = _admin_engine(scratch_url)
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)'))
        remaining = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"),
                                 {"name": SCRATCH_DB}).first()
    engine.dispose()
    return remaining is None


def _temp_alembic(tmp: Path) -> Path:
    script_dir = tmp / "alembic"
    shutil.copytree(ROOT / "alembic", script_dir)
    for stale in (script_dir / "versions").glob("*.draft"):
        stale.unlink()
    shutil.copy(SOURCE, script_dir / "versions" / "0031_navigation_registry.py")

    parser = configparser.ConfigParser()
    parser.read(ROOT / "alembic.ini", encoding="utf-8")
    parser.set("alembic", "script_location", str(script_dir))
    parser.set("alembic", "prepend_sys_path", str(ROOT))
    ini = tmp / "alembic.ini"
    with ini.open("w", encoding="utf-8") as handle:
        parser.write(handle)
    return ini


def _alembic(ini: Path, scratch_url, *args: str) -> tuple[int, str, float]:
    env = os.environ.copy()
    env["DATABASE_URL"] = scratch_url.render_as_string(hide_password=False)
    began = time.perf_counter()
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ini), *args],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    elapsed = round(time.perf_counter() - began, 3)
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stderr[-4000:]}")
    return result.returncode, result.stdout.strip(), elapsed


def _revision(conn) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _tables(conn) -> list[str]:
    return conn.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "ORDER BY tablename")).scalars().all()


def _row_counts(conn, tables: list[str]) -> dict[str, int]:
    return {name: conn.execute(text(f'SELECT count(*) FROM "{name}"')).scalar_one()
            for name in tables}


def _columns(conn) -> dict[str, list[list]]:
    rows = conn.execute(text(
        "SELECT table_name, ordinal_position, column_name, data_type, is_nullable, "
        "column_default FROM information_schema.columns WHERE table_schema = 'public' "
        "ORDER BY table_name, ordinal_position")).all()
    out: dict[str, list[list]] = {}
    for table, pos, column, data_type, nullable, default in rows:
        out.setdefault(table, []).append([pos, column, data_type, nullable, default])
    return out


def _db_size(conn) -> int:
    return conn.execute(text("SELECT pg_database_size(current_database())")).scalar_one()


def _indexes(conn) -> dict[str, set[str]]:
    rows = conn.execute(text(
        "SELECT tablename, indexname FROM pg_indexes WHERE schemaname = 'public' "
        "AND tablename IN ('nav_nodes', 'feature_registry')")).all()
    out: dict[str, set[str]] = {"nav_nodes": set(), "feature_registry": set()}
    for table, index in rows:
        out[table].add(index)
    return out


def _constraints(conn) -> dict[str, set[str]]:
    rows = conn.execute(text(
        "SELECT child.relname, k.conname FROM pg_constraint k "
        "JOIN pg_class child ON child.oid = k.conrelid "
        "WHERE child.relname IN ('nav_nodes', 'feature_registry')")).all()
    out: dict[str, set[str]] = {"nav_nodes": set(), "feature_registry": set()}
    for table, name in rows:
        out[table].add(name)
    return out


def _foreign_keys(conn) -> list[dict]:
    rows = conn.execute(text(
        "SELECT child.relname AS child, k.conname, parent.relname AS parent, "
        "k.confdeltype FROM pg_constraint k "
        "JOIN pg_class child ON child.oid = k.conrelid "
        "JOIN pg_class parent ON parent.oid = k.confrelid "
        "WHERE k.contype = 'f' AND child.relname IN ('nav_nodes', 'feature_registry') "
        "ORDER BY child.relname, k.conname")).all()
    return [{"child": c, "constraint": n, "parent": p, "on_delete": d}
            for c, n, p, d in rows]


def _seed_rows(conn) -> list[dict]:
    rows = conn.execute(text(
        "SELECT id, parent_id, depth, node_key, label, kind, view, route, "
        "component_key, feature_key, permission_any, menu_rule, menu_any, aliases, "
        "is_home, sort_order, active FROM nav_nodes ORDER BY id")).mappings().all()
    return [dict(row) for row in rows]


def _feature_rows(conn) -> list[dict]:
    rows = conn.execute(text(
        "SELECT feature_key, label, description, status, locked, api_prefixes, "
        "tables, permissions, depends_on FROM feature_registry "
        "ORDER BY feature_key")).mappings().all()
    return [dict(row) for row in rows]


def _seed_evidence(conn) -> dict:
    nodes = _seed_rows(conn)
    features = _feature_rows(conn)
    kinds: dict[str, int] = {}
    for node in nodes:
        kinds[node["kind"]] = kinds.get(node["kind"], 0) + 1
    homes = [n["node_key"] for n in nodes if n["is_home"]]
    aliases = [n["node_key"] for n in nodes if n["aliases"]]
    counts = {"nav_nodes": len(nodes), "feature_registry": len(features),
              "home": len(homes), "alias_rows": len(aliases),
              "seed_rows": len(nodes) + len(features)}
    expected_nodes = build_nodes()
    expected_features = sorted(build_features(), key=lambda row: row["feature_key"])
    return {
        "counts": counts,
        "expected": EXPECTED_COUNTS,
        "counts_ok": counts == EXPECTED_COUNTS,
        "kinds": kinds,
        "home": homes,
        "alias_nodes": aliases,
        "aliases": {alias: n["node_key"] for n in nodes for alias in n["aliases"]},
        "catalogue_rows_equal": nodes == expected_nodes,
        "catalogue_features_equal": features == expected_features,
        "first_mismatch": next((f"nav {a['id']} != {b['id']}" for a, b in
                                zip(nodes, expected_nodes) if a != b), None),
        "validate_errors": validate_catalog(nodes, features),
    }


def _integrity_probes(scratch_url) -> list[dict]:
    """Attempt the writes the constraints must refuse, and one they must allow."""
    engine = sa.create_engine(scratch_url)
    probes = [
        ("duplicate node_key is refused",
         "INSERT INTO nav_nodes (id, depth, node_key, label, kind, sort_order) "
         "VALUES (9001, 1, 'sales', 'duplicate', 'module', 9)"),
        ("a second Home row is refused",
         "INSERT INTO nav_nodes (id, depth, node_key, label, kind, view, route, "
         "component_key, is_home, sort_order) VALUES (9002, 4, 'extra/home', 'Home', "
         "'screen', 'home', '#/home', 'home', TRUE, 9)"),
        ("a depth/kind mismatch is refused",
         "INSERT INTO nav_nodes (id, depth, node_key, label, kind, sort_order) "
         "VALUES (9003, 2, 'bad/kind', 'bad', 'module', 9)"),
        ("a child with a missing parent is refused",
         "INSERT INTO nav_nodes (id, parent_id, depth, node_key, label, kind, "
         "sort_order) VALUES (9004, 9999, 2, 'bad/parent', 'bad', 'category', 9)"),
        ("a non-screen carrying a view is refused",
         "INSERT INTO nav_nodes (id, depth, node_key, label, kind, view, sort_order) "
         "VALUES (9005, 1, 'bad/view', 'bad', 'module', 'dash', 9)"),
    ]
    results = []
    for label, sql in probes:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(text(sql))
                results.append({"probe": label, "refused": False})
            except IntegrityError as exc:
                results.append({"probe": label, "refused": True,
                                "constraint": exc.orig.diag.constraint_name
                                if getattr(exc.orig, "diag", None) else None})
            finally:
                trans.rollback()
    # A valid child under an existing group must be accepted (then rolled back).
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(
                "INSERT INTO nav_nodes (id, parent_id, depth, node_key, label, kind, "
                "view, route, component_key, sort_order) VALUES "
                "(9006, 3, 4, 'overview/dashboard/workspace/probe', 'Probe', 'screen', "
                "'probe', '#/probe', 'probe', 9)"))
            accepted = True
        except IntegrityError:
            accepted = False
        finally:
            trans.rollback()
    results.append({"probe": "a valid child of an existing group is accepted",
                    "accepted": accepted})
    engine.dispose()
    return results


def _orphans_and_duplicates(conn) -> dict:
    def one(sql):
        return int(conn.execute(text(sql)).scalar_one())

    return {
        "duplicate_node_keys": one(
            "SELECT count(*) - count(DISTINCT node_key) FROM nav_nodes"),
        "duplicate_screen_routes": one(
            "SELECT count(*) - count(DISTINCT route) FROM nav_nodes WHERE kind = 'screen'"),
        "duplicate_sibling_sort": one(
            "SELECT coalesce(sum(n), 0) FROM (SELECT count(*) - 1 AS n FROM nav_nodes "
            "GROUP BY coalesce(parent_id, -1), sort_order HAVING count(*) > 1) d"),
        "orphan_parents": one(
            "SELECT count(*) FROM nav_nodes n LEFT JOIN nav_nodes p ON p.id = n.parent_id "
            "WHERE n.parent_id IS NOT NULL AND p.id IS NULL"),
        "orphan_features": one(
            "SELECT count(*) FROM nav_nodes n LEFT JOIN feature_registry f "
            "ON f.feature_key = n.feature_key WHERE n.feature_key IS NOT NULL "
            "AND f.feature_key IS NULL"),
        "home_rows": one("SELECT count(*) FROM nav_nodes WHERE is_home"),
    }


def _r01(scratch_url) -> list[dict]:
    """The five R-01 behaviours against the migrated scratch database.

    The factory migrations seed some switch rows, so the "no row means ON"
    behaviour is proved after deleting every row (which is also R-01 check 3).
    """
    from sqlalchemy.orm import sessionmaker

    engine = sa.create_engine(scratch_url)
    Session = sessionmaker(bind=engine)
    found: dict[str, dict] = {}

    with Session() as db:
        initial_rows = db.query(FeatureFlag).count()
        initial_keys = sorted(row[0] for row in db.execute(text(
            "SELECT key FROM feature_flags ORDER BY key")).all())

        db.execute(text("DELETE FROM feature_flags"))
        db.commit()
        counts = db.execute(text(
            "SELECT (SELECT count(*) FROM nav_nodes), "
            "(SELECT count(*) FROM feature_registry), "
            "(SELECT count(*) FROM feature_flags)")).one()
        all_on = {f.key: feature_store.is_enabled(db, f.key) for f in FEATURES}
        found["deleting_every_switch_row_leaves_the_registry_intact"] = {
            "pass": tuple(counts) == (64, 14, 0) and all(all_on.values()),
            "evidence": {"initial_switch_rows": initial_rows,
                         "initial_switch_keys": initial_keys,
                         "counts": list(counts),
                         "every_feature_on": all(all_on.values())}}

        no_row = db.query(FeatureFlag).count()
        found["registered_feature_without_switch_row_is_on"] = {
            "pass": no_row == 0 and feature_store.is_enabled(db, "hr") is True,
            "evidence": {"feature_flags_rows": no_row, "hr_enabled": True}}

        db.add(FeatureFlag(key="hr", enabled=False, updated_by=None))
        db.commit()
        flag = feature_store.stored_flags(db)
        registry_hr = db.execute(text(
            "SELECT count(*) FROM feature_registry WHERE feature_key = 'hr'")).scalar_one()
        nodes = _seed_rows(db.connection())
        disabled = feature_store.is_enabled(db, "hr")
        visible = visible_keys(nodes, {"hr:read"},
                               lambda key: feature_store.is_enabled(db, key))
        hr_keys = {n["node_key"] for n in nodes if n["feature_key"] == "hr"}
        found["disabled_switch_hides_nodes_but_keeps_the_registry_row"] = {
            "pass": (flag == {"hr": False} and disabled is False and registry_hr == 1
                     and bool(hr_keys) and not (visible & hr_keys)
                     and len(nodes) == 64),
            "evidence": {"stored": flag, "hr_enabled": disabled,
                         "registry_rows_for_hr": registry_hr,
                         "visible_hr_nodes": sorted(visible & hr_keys),
                         "nav_rows_still": len(nodes)}}

        db.execute(text("DELETE FROM feature_flags"))
        db.commit()
        fks = _foreign_keys(db.connection())
        model_fks = {
            "feature_registry": sorted(fk.target_fullname
                                       for fk in FeatureRegistry.__table__.foreign_keys),
            "nav_nodes": sorted(fk.target_fullname
                                for fk in NavNode.__table__.foreign_keys),
        }
        ghost_nodes = build_nodes()
        next(n for n in ghost_nodes if n["view"] == "products")["feature_key"] = "ghost"
        ghost_errors = [e for e in validate_catalog(ghost_nodes, build_features())
                        if "unknown feature 'ghost'" in e]
        found["unknown_feature_key_is_rejected"] = {
            "pass": bool(ghost_errors) and not any(fk["parent"] == "feature_flags"
                                                   for fk in fks),
            "evidence": {"catalogue_error": ghost_errors,
                         "database_foreign_keys": fks,
                         "model_foreign_keys": model_fks}}

        columns = db.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name IN "
            "('nav_nodes', 'feature_registry') AND column_name = 'enabled'")).all()
        registry_rows = db.execute(text(
            "SELECT count(*) FROM feature_registry")).scalar_one()
        enabled_without_row = feature_store.is_enabled(db, "accounts")
        db.add(FeatureFlag(key="accounts", enabled=False, updated_by=None))
        db.commit()
        enabled_with_row = feature_store.is_enabled(db, "accounts")
        registry_after = db.execute(text(
            "SELECT count(*) FROM feature_registry")).scalar_one()
        db.execute(text("DELETE FROM feature_flags"))
        db.commit()
        found["registry_membership_does_not_enable_or_disable_a_switch"] = {
            "pass": (not columns and registry_rows == registry_after == 14
                     and enabled_without_row is True and enabled_with_row is False),
            "evidence": {"enabled_columns": [list(c) for c in columns],
                         "registry_rows": registry_rows,
                         "registry_rows_after_switch": registry_after,
                         "enabled_without_row": enabled_without_row,
                         "enabled_with_disabled_row": enabled_with_row}}

    engine.dispose()
    order = ["registered_feature_without_switch_row_is_on",
             "disabled_switch_hides_nodes_but_keeps_the_registry_row",
             "deleting_every_switch_row_leaves_the_registry_intact",
             "unknown_feature_key_is_rejected",
             "registry_membership_does_not_enable_or_disable_a_switch"]
    return [{"id": key, **found[key]} for key in order]


def _run(scratch_url, out: Path) -> int:
    rehearsal = Rehearsal()
    created = False
    drop_ok = False
    try:
        info = _create_database(scratch_url)
        created = True
        rehearsal.data["scratch_database"] = info
        rehearsal.step("create_database", f"created {SCRATCH_DB} "
                      f"(server {info['server_version']})")

        engine = sa.create_engine(scratch_url)
        sizes: dict[str, int] = {}
        with tempfile.TemporaryDirectory() as tmp:
            ini = _temp_alembic(Path(tmp))
            rehearsal.step("temp_alembic", "migration source copied into a temporary "
                          "script directory",
                          source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest())
            revisions: dict[str, str] = {}
            for target in CHAIN:
                _, stdout, elapsed = _alembic(ini, scratch_url, "upgrade", target)
                with engine.connect() as conn:
                    revisions[target] = _revision(conn)
                    sizes[target] = _db_size(conn)
                rehearsal.step(f"upgrade_{target}", f"{revisions[target]} in {elapsed}s",
                               stdout_tail=stdout.splitlines()[-1] if stdout else "",
                               database_size_bytes=sizes[target])

            with engine.connect() as conn:
                sizes["0031"] = _db_size(conn)
                seed = _seed_evidence(conn)
                indexes = _indexes(conn)
                constraints = _constraints(conn)
                fks = _foreign_keys(conn)
                sequence = dict(conn.execute(text(
                    "SELECT last_value, is_called FROM nav_nodes_id_seq")).one()._mapping)
                integrity = _integrity_probes(scratch_url)
                orphans_dupes = _orphans_and_duplicates(conn)

            rehearsal.data["revisions"] = {
                "chain": list(CHAIN), "installed": revisions,
                "final": revisions["0031_navigation_registry"]}
            rehearsal.data["seed"] = seed
            rehearsal.data["schema"] = {
                "indexes": {k: sorted(v) for k, v in indexes.items()},
                "indexes_match": indexes == EXPECTED_INDEXES,
                "constraints": {k: sorted(v) for k, v in constraints.items()},
                "constraints_match": constraints == EXPECTED_CONSTRAINTS,
                "foreign_keys": fks,
                "nav_sequence": sequence,
                "integrity_probes": integrity,
            }
            rehearsal.data["orphans_and_duplicates"] = orphans_dupes

            seed_ok = (seed["counts_ok"] and seed["catalogue_rows_equal"]
                       and seed["catalogue_features_equal"] and not seed["validate_errors"])
            rehearsal.step("verify_seed", f"{seed['counts']} match the catalogue"
                          if seed_ok else f"seed mismatch: {seed['first_mismatch']} "
                          f"{seed['validate_errors']}", ok=seed_ok, counts=seed["counts"])
            schema_ok = (indexes == EXPECTED_INDEXES
                         and constraints == EXPECTED_CONSTRAINTS
                         and all(p.get("refused", p.get("accepted")) for p in integrity))
            rehearsal.step("verify_schema", "indexes, constraints, FK, sequence and "
                          "write probes all match" if schema_ok else
                          "schema differs from the migration", ok=schema_ok,
                          probes=len(integrity))

            # ------------------------------------------------ business snapshot
            with engine.connect() as conn:
                tables_0031 = _tables(conn)
                counts_0031 = _row_counts(conn, tables_0031)
                columns_0031 = _columns(conn)
            rehearsal.data["business_data"] = {"after_0031": {
                "revision": revisions["0031_navigation_registry"],
                "tables": tables_0031, "row_counts": counts_0031,
                "database_size_bytes": sizes["0031"]}}

            # ------------------------------------------------------- downgrade
            _, _, elapsed = _alembic(ini, scratch_url, "downgrade", "0030_sign_in_content")
            with engine.connect() as conn:
                tables_0030 = _tables(conn)
                counts_0030 = _row_counts(conn, tables_0030)
                columns_0030 = _columns(conn)
                revision_0030 = _revision(conn)
                size_0030 = _db_size(conn)
            rehearsal.data["business_data"]["before_0031"] = {
                "revision": revision_0030, "tables": tables_0030,
                "row_counts": counts_0030, "database_size_bytes": size_0030}
            removed = sorted(set(tables_0031) - set(tables_0030))
            added = sorted(set(tables_0030) - set(tables_0031))
            intact = all(counts_0030.get(t) == counts_0031.get(t) for t in tables_0030)
            columns_same = all(columns_0030.get(t) == columns_0031.get(t) for t in tables_0030)
            previous = {"legal_documents", "sign_in_banners", "sign_in_contacts",
                        "sign_in_notices"}
            downgrade_ok = (revision_0030 == "0030_sign_in_content"
                            and removed == ["feature_registry", "nav_nodes"] and not added
                            and intact and columns_same and previous <= set(tables_0030))
            rehearsal.step("downgrade_0030", f"{revision_0030} in {elapsed}s; removed "
                          f"{removed}" if downgrade_ok else
                          f"downgrade mismatch: version={revision_0030} -{removed} "
                          f"+{added}", ok=downgrade_ok, removed=removed, added=added,
                          earlier_tables_intact=intact, columns_unchanged=columns_same)

            # ------------------------------------------------------ re-upgrade
            _, _, elapsed = _alembic(ini, scratch_url, "upgrade", "0031_navigation_registry")
            with engine.connect() as conn:
                revision_final = _revision(conn)
                seed_again = _seed_evidence(conn)
                orphans_dupes_again = _orphans_and_duplicates(conn)
                size_final = _db_size(conn)
            rehearsal.data["rollback"] = {
                "downgrade_ok": True, "removed": removed, "added": added,
                "earlier_tables_intact": intact, "columns_unchanged": columns_same,
                "reupgrade_ok": revision_final == "0031_navigation_registry",
                "elapsed_seconds": elapsed,
                "final_seed": seed_again["counts"],
                "final_revision": revision_final,
                "orphans_and_duplicates": orphans_dupes_again,
                "database_size_bytes": size_final}
            noise = {k: v for k, v in orphans_dupes_again.items() if k != "home_rows"}
            reupgrade_ok = (revision_final == "0031_navigation_registry"
                            and seed_again["counts"] == seed["counts"]
                            and seed_again["catalogue_rows_equal"]
                            and seed_again["catalogue_features_equal"]
                            and not any(noise.values())
                            and orphans_dupes_again["home_rows"] == 1)
            rehearsal.step("reupgrade_0031", f"{revision_final}; {seed_again['counts']}"
                          if reupgrade_ok else "re-upgrade mismatch: "
                          f"{revision_final} {seed_again['counts']} "
                          f"{orphans_dupes_again}", ok=reupgrade_ok,
                          final_revision=revision_final)

            # ------------------------------------------------------- business diff
            changed_rows = {t: [counts_0030[t], counts_0031[t]] for t in tables_0030
                            if counts_0030.get(t) != counts_0031.get(t)}
            changed_columns = sorted(t for t in tables_0030
                                     if columns_0030.get(t) != columns_0031.get(t))
            unclassified_0030 = sorted(set(tables_0030) - set(BUSINESS_TABLES)
                                       - set(KEPT_TABLES) - set(SCHEMA_TABLES))
            unclassified_0031 = sorted(set(tables_0031) - set(BUSINESS_TABLES)
                                       - set(KEPT_TABLES) - set(SCHEMA_TABLES))
            rehearsal.data["classification"] = {
                "counts": {"clear": len(BUSINESS_TABLES), "keep": len(KEPT_TABLES),
                           "schema": len(SCHEMA_TABLES)},
                "unclassified_at_0030": unclassified_0030,
                "unclassified_at_0031": unclassified_0031,
                "new_tables_at_0031": unclassified_0031,
                "activation_would_add_to_keep": ["feature_registry", "nav_nodes"]}
            new_tables = sorted(set(tables_0031) - set(tables_0030))
            data_ok = (not changed_rows and not changed_columns and not added)
            rehearsal.data["business_data"].update({
                "tables_added_by_0031": new_tables,
                "tables_removed_by_0031": added,
                "other_tables_unchanged": data_ok,
                "row_count_changes": changed_rows,
                "columns_changed": changed_columns})
            rehearsal.step("business_data_unchanged",
                          f"{len(tables_0030)} pre-existing tables unchanged; "
                          f"0031 adds {new_tables}" if data_ok else
                          "a pre-existing table changed", ok=data_ok,
                          row_changes=changed_rows, column_changes=changed_columns,
                          unclassified=unclassified_0031)

            # ------------------------------------------------------------ R-01
            r01 = _r01(scratch_url)
            rehearsal.data["r01"] = r01
            failed = [c for c in r01 if not c["pass"]]
            rehearsal.step("r01_five_behaviours", f"{len(r01)} checks against the "
                          "scratch database" if not failed else
                          f"failed: {[c['id'] for c in failed]}",
                          ok=not failed, checks=r01)
        engine.dispose()
        return 0
    except Exception as error:                      # noqa: BLE001 - recorded, not hidden
        rehearsal.data["error"] = str(error)
        print(f"REHEARSAL FAILED: {error}")
        return 1
    finally:
        if created:
            try:
                drop_ok = _drop_database(scratch_url)
            except Exception as error:              # noqa: BLE001
                print(f"scratch database drop failed: {error}")
            rehearsal.data["scratch_database"] = {
                **rehearsal.data.get("scratch_database", {}),
                "dropped_at": _now(), "exists_after_drop": not drop_ok}
            entry = {"n": len(rehearsal.steps) + 1, "id": "drop_database", "at": _now(),
                     "status": "pass" if drop_ok else "fail",
                     "detail": f"{SCRATCH_DB} removed" if drop_ok
                     else f"{SCRATCH_DB} still exists"}
            rehearsal.steps.append(entry)
            print(f"[{entry['n']:02d}] {entry['status'].upper():4} drop_database: "
                  f"{entry['detail']}")
        out.parent.mkdir(parents=True, exist_ok=True)
        result = rehearsal.result()
        out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(f"evidence -> {out}")
        print(f"{len(result['steps'])} steps, {len(result['failures'])} failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true",
                        help="execute against a scratch *_test database")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    scratch_url = _scratch_url()
    if args.run:
        return _run(scratch_url, Path(args.out))
    _plan()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
