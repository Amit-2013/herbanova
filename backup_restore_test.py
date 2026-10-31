"""Backup and restore test (MOD-09).

Dumps the live database, restores the dump into a scratch database and proves the
copy is the same: every table's row count, the Alembic revision, and the outcome
of every report's reconciliation checks. The live database is only read.

    python backup_restore_test.py            # exit 0 = restore verified
    python backup_restore_test.py --keep     # keep the scratch database for inspection

Needs the PostgreSQL client tools (pg_dump, pg_restore) on PATH. Run it on the
server that holds the database, and keep its output as audit evidence before any
risky change. A backup that has never been restored is not yet a backup.
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _tool(name: str) -> str:
    from shutil import which
    found = which(name)
    if not found:
        sys.exit(f"FAIL: '{name}' was not found on PATH. Install the PostgreSQL client tools.")
    return found


def _env(url) -> dict:
    return {**os.environ, "PGPASSWORD": url.password or ""}


def _conn_args(url) -> list[str]:
    return ["-h", url.host or "localhost", "-p", str(url.port or 5432),
            "-U", url.username or "postgres"]


def _admin(url, autocommit=True):
    return psycopg.connect(host=url.host or "localhost", port=url.port or 5432,
                           user=url.username, password=url.password,
                           dbname="postgres", autocommit=autocommit)


def _row_counts(engine) -> dict[str, int]:
    with engine.connect() as c:
        names = [r[0] for r in c.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"))]
        return {n: c.execute(text(f'SELECT count(*) FROM "{n}"')).scalar() for n in names}


def _report_outcomes(engine) -> dict:
    """Every report's reconciliation outcome and totals, built from one database."""
    from app.services import reports
    out = {}
    with sessionmaker(bind=engine)() as db:
        for key in sorted(reports.CATALOG):
            try:
                rep = reports.build(db, key, None, None)
            except Exception as exc:                      # same failure on both sides is fine
                out[key] = ("error", type(exc).__name__)
                continue
            tables = [(t.get("key"), t.get("total_rows", len(t.get("rows", []))),
                       str(t.get("totals"))) for t in rep.get("tables", [])]
            checks = [(c.get("key"), bool(c.get("ok")), str(c.get("report_value")),
                       str(c.get("source_value"))) for c in rep.get("checks", [])]
            out[key] = (bool(rep.get("reconciled")), tables, checks)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--keep", action="store_true", help="keep the scratch database")
    args = parser.parse_args()

    live_url = make_url(settings.database_url)
    live_name = live_url.database
    scratch_name = f"{live_name}_restore_scratch"
    if not scratch_name.endswith("_scratch"):          # the drop below is guarded by name
        sys.exit("FAIL: refusing to continue; scratch database name is not recognisable.")
    scratch_url = live_url.set(database=scratch_name)

    pg_dump, pg_restore = _tool("pg_dump"), _tool("pg_restore")
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / "backup.dump"
        print(f"1. Dumping {live_name} ...")
        subprocess.run([pg_dump, *_conn_args(live_url), "-Fc", "-f", str(dump), live_name],
                       env=_env(live_url), check=True)
        print(f"   backup file: {dump.stat().st_size:,} bytes")

        print(f"2. Restoring into scratch database {scratch_name} ...")
        with _admin(live_url) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{scratch_name}"')
            admin.execute(f'CREATE DATABASE "{scratch_name}"')
        restore = subprocess.run(
            [pg_restore, *_conn_args(live_url), "--no-owner", "-d", scratch_name, str(dump)],
            env=_env(live_url), capture_output=True, text=True)
        if restore.returncode != 0:
            failures.append(f"pg_restore reported errors: {restore.stderr.strip()[:500]}")

        live = create_engine(live_url.render_as_string(hide_password=False))
        copy = create_engine(scratch_url.render_as_string(hide_password=False))
        try:
            print("3. Comparing row counts ...")
            a, b = _row_counts(live), _row_counts(copy)
            for table in sorted(set(a) | set(b)):
                if a.get(table) != b.get(table):
                    failures.append(f"table {table}: live={a.get(table)} restored={b.get(table)}")
            print(f"   {len(a)} tables, {sum(a.values()):,} rows in the live database")

            print("4. Comparing the Alembic revision ...")
            rev = []
            for engine in (live, copy):
                with engine.connect() as c:
                    rev.append(c.execute(text("SELECT version_num FROM alembic_version")).scalar())
            if rev[0] != rev[1]:
                failures.append(f"alembic revision: live={rev[0]} restored={rev[1]}")
            print(f"   live={rev[0]} restored={rev[1]}")

            print("5. Comparing every report's reconciliation ...")
            ra, rb = _report_outcomes(live), _report_outcomes(copy)
            for key in sorted(set(ra) | set(rb)):
                if ra.get(key) != rb.get(key):
                    failures.append(f"report {key}: live and restored copies differ")
            unreconciled = [k for k, v in ra.items() if v[0] is False]
            print(f"   {len(ra)} reports compared; "
                  f"{len(unreconciled)} not reconciled in the live data")
            if unreconciled:
                failures.append("live data does not reconcile in: " + ", ".join(unreconciled))
        finally:
            live.dispose()
            copy.dispose()
            if not args.keep:
                with _admin(live_url) as admin:
                    admin.execute(f'DROP DATABASE IF EXISTS "{scratch_name}"')

    print()
    if failures:
        print("RESTORE TEST FAILED")
        for line in failures:
            print(" -", line)
        return 1
    print("RESTORE TEST PASSED: the restored copy matches the live database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
