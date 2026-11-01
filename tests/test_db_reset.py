"""Guarded database reset: gating, step order, backups, verification and execution.

The destructive tests run against throwaway databases of their own, never the
shared test database and never the development database.
"""
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import (hash_password, hash_secondary_password,
                               verify_password, verify_secondary_password)
from app.models.core import User
from app.services import db_reset

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "ResetPass!12345"
RESET_KEY = "reset-key-0123456789"

pytestmark = pytest.mark.skipif(
    subprocess.run(["which", "pg_dump"], capture_output=True).returncode != 0,
    reason="PostgreSQL client tools are not installed")


@pytest.fixture()
def reset_env(tmp_path, monkeypatch, client):
    # `client` seeds the test users, including the t_admin this fixture arms.
    state = tmp_path / "state"
    primary = tmp_path / "backup-a"
    mirror = tmp_path / "backup-b"
    monkeypatch.setattr(settings, "db_reset_enabled", True)
    monkeypatch.setattr(settings, "db_reset_backup_dir", str(primary))
    monkeypatch.setattr(settings, "db_reset_backup_mirror_dir", str(mirror))
    monkeypatch.setattr(settings, "db_reset_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "db_reset_state_dir", str(state))
    monkeypatch.setattr(settings, "db_reset_confirm_minutes", 10)
    monkeypatch.setattr(settings, "db_reset_token_minutes", 30)
    monkeypatch.setattr(settings, "db_reset_max_attempts", 3)
    monkeypatch.setattr(settings, "db_reset_lockout_minutes", 60)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "t_admin"))
        admin.password_hash = hash_password(PASSWORD)
        admin.reset_key_hash = hash_secondary_password(RESET_KEY)
        db.commit()
        admin_id = admin.id
    return {"state": state, "primary": primary, "mirror": mirror, "admin_id": admin_id}


@pytest.fixture()
def separate_devices(monkeypatch):
    """The hint that backup directories are on different disks.

    The real predicate is tested below; a workstation with one disk cannot
    produce two devices, so the happy paths override it explicitly.
    """
    monkeypatch.setattr(db_reset, "same_device", lambda first, second: False)


def _begin(client, mode: str = "business", password: str = PASSWORD, phrase: str | None = None):
    return client.post("/api/db-reset/begin", json={
        "mode": mode, "password": password,
        "phrase": phrase if phrase is not None else f"RESET {db_reset.database_name()}"})


def _audit_events(reset_env) -> list[str]:
    return [record["event"] for record in _audit_records(reset_env)]


def _audit_records(reset_env) -> list[dict]:
    path = Path(reset_env["state"]) / "audit" / "reset-audit.jsonl"
    if not path.exists():
        return []
    import json
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------- gating
def test_switched_off_by_default(client, monkeypatch, reset_env):
    monkeypatch.setattr(settings, "db_reset_enabled", False)
    status = client.get("/api/db-reset/status")
    assert status.status_code == 200 and status.json()["enabled"] is False
    assert _begin(client).status_code == 403


def test_only_an_administrator_may_open_or_start(client, reset_env):
    client.as_user("sales")
    assert client.get("/api/db-reset/status").status_code == 403
    assert _begin(client).status_code == 403
    client.as_user("hr_manager")
    assert _begin(client).status_code == 403


def test_three_wrong_passwords_lock_the_feature(client, reset_env):
    assert _begin(client, password="not-the-password").status_code == 403
    assert _begin(client, password="not-the-password").status_code == 403
    locked = _begin(client, password="not-the-password")
    assert locked.status_code == 423
    assert _begin(client).status_code == 423              # correct password, still locked
    assert "db.reset_locked" in _audit_events(reset_env)


def test_wrong_phrase_is_refused_and_creates_no_run(client, reset_env):
    res = _begin(client, phrase="RESET wrong_database")
    assert res.status_code == 403
    runs = Path(reset_env["state"]) / "runs"
    assert not runs.exists() or not list(runs.iterdir())


def test_same_disk_backups_are_refused(client, reset_env):
    # No device override here: both directories are on this machine's disk.
    res = _begin(client)
    assert res.status_code == 409
    assert "same device" in res.json()["detail"]


# ---------------------------------------------------------------- classification
def test_every_table_is_classified_clear_keep_or_schema(client):
    with SessionLocal() as db:
        tables = set(db.scalars(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")))
    groups = db_reset.table_classification()
    clear, keep, schema = set(groups["clear"]), set(groups["keep"]), set(groups["schema"])
    assert not (clear & keep), f"in both lists: {sorted(clear & keep)}"
    assert not (clear & schema) and not (keep & schema)
    missing = sorted(tables - clear - keep - schema)
    assert not missing, ("These tables are in neither list, so a business reset would "
                         f"silently ignore them: {missing}")


def test_the_truncate_cannot_reach_a_kept_table(client):
    with SessionLocal() as db:
        raw = db.connection().connection
        reached = db_reset._cascade_reaches(raw, db_reset.BUSINESS_TABLES)
    leaked = sorted(reached - set(db_reset.BUSINESS_TABLES))
    assert not leaked, ("TRUNCATE CASCADE would also clear kept tables: "
                        f"{leaked}. Change the business reset to delete in order.")


def test_the_reset_refuses_when_cascade_reaches_a_kept_table(reset_env, separate_devices,
                                                            monkeypatch):
    scratch = _scratch_database("herbanova_bcs_cascade_test")
    monkeypatch.setattr(settings, "database_url",
                        scratch.render_as_string(hide_password=False))
    actor = _actor(scratch)
    try:
        with psycopg.connect(host=scratch.host, port=scratch.port,
                             user=scratch.username, password=scratch.password,
                             dbname=scratch.database) as conn:
            # A kept table that points at a cleared one makes CASCADE leak.
            conn.execute("ALTER TABLE hr_branches ADD COLUMN demo_clear_ref integer "
                         "REFERENCES hr_announcements(id)")
            conn.execute("INSERT INTO hr_announcements (title, body, published_by) "
                         "VALUES ('must survive', 'x', %s)", (actor.id,))
        started = db_reset.begin(actor, "business", PASSWORD,
                                 f"RESET {db_reset.database_name()}")
        made = db_reset.create_backups(actor, started["run_id"], started["token"])
        checked = db_reset.verify_backups(actor, started["run_id"], made["token"])
        with pytest.raises(HTTPException) as stopped:
            db_reset.execute(actor, started["run_id"], checked["token"], RESET_KEY)
        assert stopped.value.status_code == 500
        assert "kept table" in stopped.value.detail
        with psycopg.connect(host=scratch.host, port=scratch.port,
                             user=scratch.username, password=scratch.password,
                             dbname=scratch.database) as conn:
            remaining = conn.execute("SELECT count(*) FROM hr_announcements").fetchone()[0]
        assert remaining == 2, "the refusal must happen before anything is deleted"
        assert db_reset.current_maintenance() is not None
        db_reset.clear_maintenance(started["run_id"])
    finally:
        _drop_scratch("herbanova_bcs_cascade_test")


# ---------------------------------------------------------------- step order
def test_steps_cannot_be_skipped(client, reset_env, separate_devices):
    begin = _begin(client)
    assert begin.status_code == 200
    run = begin.json()

    # A token minted for the right admin and run but the wrong stage is refused.
    wrong_stage = db_reset._token(reset_env["admin_id"], run["run_id"], "execute", 5)
    assert client.post("/api/db-reset/backup", json={
        "run_id": run["run_id"], "token": wrong_stage}).status_code == 403
    assert client.post("/api/db-reset/execute", json={
        "run_id": run["run_id"], "token": run["token"],
        "reset_key": RESET_KEY}).status_code == 403        # a "backup" token cannot execute

    # Even a correctly signed verify token cannot jump the journal's stage.
    forged = db_reset._token(reset_env["admin_id"], run["run_id"], "verify", 5)
    skipped = client.post("/api/db-reset/verify", json={
        "run_id": run["run_id"], "token": forged})
    assert skipped.status_code == 409
    assert "awaiting_backup" in skipped.json()["detail"]

    # Nor can an execute-stage token run before the backup exists.
    early = db_reset._token(reset_env["admin_id"], run["run_id"], "execute", 5)
    early_res = client.post("/api/db-reset/execute", json={
        "run_id": run["run_id"], "token": early, "reset_key": RESET_KEY})
    assert early_res.status_code == 409
    assert "awaiting_backup" in early_res.json()["detail"]


# ---------------------------------------------------------------- backups
def test_backup_verify_and_cancel(client, reset_env, separate_devices):
    begin = _begin(client).json()
    made = client.post("/api/db-reset/backup", json={
        "run_id": begin["run_id"], "token": begin["token"]})
    assert made.status_code == 200, made.text
    body = made.json()
    assert set(body["backups"]) == {"primary", "mirror"}
    for item in body["backups"].values():
        path = Path(item["path"])
        assert path.exists() and path.suffix == ".enc"
        assert path.read_bytes()[:5] != b"PGDMP"          # encrypted on disk
        assert Path(item["manifest"]).exists()

    # The ciphertext decrypts with the configured key into a pg_dump archive.
    fernet = Fernet(settings.db_reset_encryption_key.encode())
    plain = fernet.decrypt(Path(body["backups"]["primary"]["path"]).read_bytes())
    assert plain[:5] == b"PGDMP"

    maintenance = db_reset.current_maintenance()
    assert maintenance and maintenance["run_id"] == begin["run_id"]

    checked = client.post("/api/db-reset/verify", json={
        "run_id": begin["run_id"], "token": body["token"]})
    assert checked.status_code == 200, checked.text
    keys = {(c["backup"], c["key"]) for c in checked.json()["checks"]}
    for label in ("primary", "mirror"):
        for key in ("exists", "checksum", "decrypt", "archive", "restore",
                    "row_counts", "revision"):
            assert (label, key) in keys

    cancelled = client.post("/api/db-reset/cancel", json={"run_id": begin["run_id"]})
    assert cancelled.status_code == 200
    assert db_reset.current_maintenance() is None
    assert {"db.reset_started", "db.reset_backups_created",
            "db.reset_backups_verified", "db.reset_cancelled"} <= set(_audit_events(reset_env))


def test_a_tampered_backup_stops_the_reset(client, reset_env, separate_devices):
    begin = _begin(client).json()
    made = client.post("/api/db-reset/backup", json={
        "run_id": begin["run_id"], "token": begin["token"]}).json()
    target = Path(made["backups"]["mirror"]["path"])
    blob = bytearray(target.read_bytes())
    blob[-1] ^= 0xFF
    target.write_bytes(bytes(blob))

    res = client.post("/api/db-reset/verify", json={
        "run_id": begin["run_id"], "token": made["token"]})
    assert res.status_code == 409
    assert "checksum" in res.json()["detail"]
    run = db_reset.load_run(begin["run_id"])
    assert run["stage"] == "failed"
    assert db_reset.current_maintenance() is None
    assert "db.reset_failed" in _audit_events(reset_env)


# ---------------------------------------------------------------- final step
def _prepare_verified(client):
    begin = _begin(client).json()
    made = client.post("/api/db-reset/backup", json={
        "run_id": begin["run_id"], "token": begin["token"]}).json()
    checked = client.post("/api/db-reset/verify", json={
        "run_id": begin["run_id"], "token": made["token"]})
    assert checked.status_code == 200, checked.text
    return begin["run_id"], checked.json()["token"]


def test_the_reset_key_is_required_and_checked(client, reset_env, separate_devices):
    run_id, token = _prepare_verified(client)
    with SessionLocal() as db:
        before = db.scalar(text("SELECT count(*) FROM products"))
    res = client.post("/api/db-reset/execute", json={
        "run_id": run_id, "token": token, "reset_key": "wrong-reset-key"})
    assert res.status_code == 403
    with SessionLocal() as db:
        assert db.scalar(text("SELECT count(*) FROM products")) == before
    client.post("/api/db-reset/cancel", json={"run_id": run_id})


def test_final_confirmation_expires(client, reset_env, separate_devices, monkeypatch):
    # A negative window puts the expiry strictly in the past; zero relies on the
    # clock having moved between minting and reading, which is not guaranteed.
    monkeypatch.setattr(settings, "db_reset_confirm_minutes", -1)
    run_id, token = _prepare_verified(client)
    res = client.post("/api/db-reset/execute", json={
        "run_id": run_id, "token": token, "reset_key": RESET_KEY})
    assert res.status_code == 410
    client.post("/api/db-reset/cancel", json={"run_id": run_id})


def test_the_old_single_step_wipe_is_gone(client, reset_env):
    assert client.post("/api/db/reset", json={"secondary_password": "x"}).status_code == 410


def test_reset_key_must_differ_from_the_login_password(client, reset_env):
    reuse = client.post("/api/admin/reset-key", json={
        "reset_key": PASSWORD, "current_password": PASSWORD})
    assert reuse.status_code == 422
    fresh = client.post("/api/admin/reset-key", json={
        "reset_key": "another-secret-123", "current_password": PASSWORD})
    assert fresh.status_code == 204
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "t_admin"))
        assert verify_secondary_password(admin.reset_key_hash, "another-secret-123")


def test_changing_the_reset_key_requires_the_current_login_password(client, reset_env):
    with SessionLocal() as db:
        before = db.scalar(select(User).where(User.username == "t_admin")).reset_key_hash

    missing = client.post("/api/admin/reset-key", json={"reset_key": "replacement-key-123"})
    assert missing.status_code == 422                     # the field is required

    wrong = client.post("/api/admin/reset-key", json={
        "reset_key": "replacement-key-123", "current_password": "not-the-password"})
    assert wrong.status_code == 403
    with SessionLocal() as db:
        after = db.scalar(select(User).where(User.username == "t_admin")).reset_key_hash
    assert after == before                                # nothing changed

    good = client.post("/api/admin/reset-key", json={
        "reset_key": "replacement-key-123", "current_password": PASSWORD})
    assert good.status_code == 204
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "t_admin"))
        assert verify_secondary_password(admin.reset_key_hash, "replacement-key-123")


# ---------------------------------------------------------------- maintenance
def test_writes_are_paused_while_a_reset_runs(client, reset_env):
    db_reset.start_maintenance("run-under-test")
    try:
        assert client.get("/api/products").status_code == 200      # reads continue
        assert client.get("/api/db-reset/status").status_code == 200
        blocked = client.post("/api/products", json={})
        assert blocked.status_code == 503
        assert "reset is in progress" in blocked.json()["detail"]
    finally:
        db_reset.clear_maintenance("run-under-test")


def test_the_email_worker_pauses_during_maintenance(reset_env, monkeypatch):
    """The worker is the only background loop; it must not enqueue or send."""
    from app.services import email_worker
    calls: list[str] = []
    monkeypatch.setattr(email_worker, "enqueue_due",
                        lambda *a, **k: calls.append("enqueue") or 1)
    monkeypatch.setattr(email_worker, "recover_stale",
                        lambda *a, **k: calls.append("recover") or 2)
    monkeypatch.setattr(email_worker, "process_due",
                        lambda *a, **k: calls.append("process") or ["delivery"])

    db_reset.start_maintenance("run-worker-test")
    try:
        paused = email_worker.run_once(db=None)
        assert paused["paused"] is True
        assert paused["maintenance_run"] == "run-worker-test"
        assert calls == [], "no schedule is queued and no message is sent while paused"
    finally:
        db_reset.clear_maintenance("run-worker-test")

    resumed = email_worker.run_once(db=None)
    assert resumed["paused"] is False
    assert calls == ["enqueue", "recover", "process"]


# ---------------------------------------------------------------- execution
def _scratch_database(name: str):
    if not name.endswith("_test"):
        raise RuntimeError("refusing to create a scratch database without the _test suffix")
    url = make_url(settings.database_url)
    with psycopg.connect(host=url.host or "localhost", port=url.port or 5432,
                         user=url.username, password=url.password,
                         dbname="postgres", autocommit=True) as conn:
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                     "WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        conn.execute(f'CREATE DATABASE "{name}"')
    scratch = url.set(database=name)
    done = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                          cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "DATABASE_URL":
                               scratch.render_as_string(hide_password=False)})
    if done.returncode != 0:
        raise RuntimeError(done.stderr)
    return scratch


def _drop_scratch(name: str) -> None:
    url = make_url(settings.database_url)
    with psycopg.connect(host=url.host or "localhost", port=url.port or 5432,
                         user=url.username, password=url.password,
                         dbname="postgres", autocommit=True) as conn:
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                     "WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


def _create_empty_database(name: str):
    """A database with no schema at all, the state pg_restore expects."""
    if not name.endswith("_test"):
        raise RuntimeError("refusing to create a scratch database without the _test suffix")
    url = make_url(settings.database_url)
    with psycopg.connect(host=url.host or "localhost", port=url.port or 5432,
                         user=url.username, password=url.password,
                         dbname="postgres", autocommit=True) as conn:
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                     "WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        conn.execute(f'CREATE DATABASE "{name}"')
    return url.set(database=name)


def _actor(scratch) -> types.SimpleNamespace:
    with psycopg.connect(host=scratch.host or "localhost", port=scratch.port or 5432,
                         user=scratch.username, password=scratch.password,
                         dbname=scratch.database) as conn:
        row = conn.execute(
            "INSERT INTO users (username, username_key, password_hash, role, is_active, "
            "must_change_password, failed_attempts, token_version) "
            "VALUES ('actor', 'actor', %s, 'admin', true, false, 0, 1) RETURNING id",
            (hash_password(PASSWORD),)).fetchone()
        conn.execute("INSERT INTO products (sku, name, pack_size, mrp, status) "
                     "VALUES ('KEEP-1', 'Kept product', '1', 10, 'active')")
        conn.execute("INSERT INTO suppliers (code, name, status) "
                     "VALUES ('SUP-1', 'Kept supplier', 'active')")
        conn.execute("INSERT INTO hr_announcements (title, body, published_by) "
                     "VALUES ('Notice', 'Body', %s)", (row[0],))
    return types.SimpleNamespace(id=row[0], username="actor",
                                 password_hash=hash_password(PASSWORD),
                                 reset_key_hash=hash_secondary_password(RESET_KEY))


def _run_flow(actor, mode: str) -> dict:
    started = db_reset.begin(actor, mode, PASSWORD, f"RESET {db_reset.database_name()}")
    made = db_reset.create_backups(actor, started["run_id"], started["token"])
    verified = db_reset.verify_backups(actor, started["run_id"], made["token"])
    assert verified["ok"] is True
    return db_reset.execute(actor, started["run_id"], verified["token"], RESET_KEY)


def _connect_scratch(scratch):
    return psycopg.connect(host=scratch.host or "localhost", port=scratch.port or 5432,
                           user=scratch.username, password=scratch.password,
                           dbname=scratch.database)


def _seed_kept_rows(conn, actor_id: int) -> None:
    """Give every kept table at least one row, so a surviving count means data.

    A freshly migrated database seeds roles, leave types, salary components,
    approval workflows, letter templates and feature flags. The inserts below
    cover the rest; the master tables named in the reset rules (users, employees,
    tax, products, suppliers, company profile) are included.
    """
    conn.execute(
        "INSERT INTO users (username, username_key, password_hash, role, is_active, "
        "must_change_password, failed_attempts, token_version) "
        "VALUES ('keeper', 'keeper', %s, 'viewer', true, false, 0, 1)",
        (hash_password(PASSWORD),))
    employee_id = conn.execute(
        "INSERT INTO employees (code, full_name) VALUES ('KEEP-EMP', 'Kept employee') "
        "RETURNING id").fetchone()[0]
    conn.execute("INSERT INTO warehouses (name) VALUES ('Kept warehouse')")
    conn.execute("INSERT INTO company_profile (legal_name) VALUES ('Kept Company Pvt Ltd')")
    conn.execute("INSERT INTO products (sku, name, pack_size, mrp, status) "
                 "VALUES ('KEEP-2', 'Second kept product', '1', 20, 'active')")
    conn.execute("INSERT INTO suppliers (code, name) VALUES ('SUP-2', 'Second kept supplier')")
    conn.execute("INSERT INTO distributors (code, name, territory, status, credit_limit) "
                 "VALUES ('DIST-T', 'Kept distributor', 'North', 'active', 1000)")
    conn.execute("INSERT INTO tax_rates (hsn, cgst_rate, sgst_rate, igst_rate, "
                 "effective_from, created_by) "
                 "VALUES ('TEST9999', 9, 9, 18, '2026-01-01', %s)", (actor_id,))
    conn.execute("INSERT INTO discount_slabs (name, discount_percent, effective_from, "
                 "created_by, min_qty) VALUES ('Kept slab', 5, '2026-01-01', %s, 10)",
                 (actor_id,))
    conn.execute("INSERT INTO document_sequences (doc_type, financial_year, last_number) "
                 "VALUES ('KEEP-TEST', '2026-27', 1)")
    conn.execute("INSERT INTO feature_flags (key, enabled) VALUES ('keep.test', true)")
    conn.execute("INSERT INTO email_settings DEFAULT VALUES")
    conn.execute("INSERT INTO hr_branches (code, name) VALUES ('KEEP-BR', 'Kept branch')")
    conn.execute("INSERT INTO hr_departments (code, name) "
                 "VALUES ('KEEP-DEPT', 'Kept department')")
    conn.execute("INSERT INTO hr_work_locations (code, name) "
                 "VALUES ('KEEP-OFF', 'Kept office')")
    conn.execute("INSERT INTO hr_holidays (date, name) VALUES ('2026-12-31', 'Kept holiday')")
    conn.execute("INSERT INTO hr_period_locks (scope, year, month, locked_by, reason) "
                 "VALUES ('payroll', 2025, 12, %s, 'Kept lock')", (actor_id,))
    conn.execute("INSERT INTO hr_saved_filters (user_id, view, name) "
                 "VALUES (%s, 'leads', 'Kept filter')", (actor_id,))
    conn.execute("INSERT INTO hr_attendance_rules (created_by) VALUES (%s)", (actor_id,))
    conn.execute("INSERT INTO hr_employee_assets (employee_id, asset_type, name, "
                 "issued_on, created_by) "
                 "VALUES (%s, 'laptop', 'Kept laptop', '2026-01-01', %s)",
                 (employee_id, actor_id))
    conn.execute("INSERT INTO hr_employee_documents (employee_id, doc_type, title, "
                 "uploaded_by) VALUES (%s, 'contract', 'Kept contract', %s)",
                 (employee_id, actor_id))
    structure_id = conn.execute(
        "INSERT INTO hr_salary_structures (employee_id, effective_from, created_by) "
        "VALUES (%s, '2026-01-01', %s) RETURNING id", (employee_id, actor_id)).fetchone()[0]
    component_id = conn.execute(
        "SELECT id FROM hr_salary_components ORDER BY id LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO hr_salary_structure_lines (structure_id, component_id) "
                 "VALUES (%s, %s)", (structure_id, component_id))
    recipient_id = conn.execute(
        "INSERT INTO email_recipients (email, name, unsubscribe_token) "
        "VALUES ('keeper@example.invalid', 'Keeper', 'keeper-token-0001') RETURNING id"
    ).fetchone()[0]
    schedule_id = conn.execute(
        "INSERT INTO email_schedules (name, pack_key, frequency, created_by) "
        "VALUES ('Kept schedule', 'sales', 'weekly', %s) RETURNING id", (actor_id,)
    ).fetchone()[0]
    conn.execute("INSERT INTO email_schedule_recipients (schedule_id, recipient_id, field) "
                 "VALUES (%s, %s, 'to')", (schedule_id, recipient_id))
    conn.execute("INSERT INTO audit_log (action, record) "
                 "VALUES ('reset.test', 'row that must survive')")


def _kept_snapshot(conn) -> dict:
    """Row counts for every KEEP table plus the settings that live inside them."""
    return {
        "counts": {name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                   for name in db_reset.KEPT_TABLES},
        "roles": sorted((row[0], json.dumps(row[1], sort_keys=True)) for row in
                        conn.execute("SELECT name, permissions FROM roles").fetchall()),
        "flags": dict(conn.execute("SELECT key, enabled FROM feature_flags").fetchall()),
        "company": conn.execute(
            "SELECT legal_name FROM company_profile ORDER BY id").fetchall(),
    }


def test_business_mode_leaves_every_kept_table_untouched(reset_env, separate_devices,
                                                        monkeypatch):
    scratch = _scratch_database("herbanova_bcs_resetkeep_test")
    monkeypatch.setattr(settings, "database_url",
                        scratch.render_as_string(hide_password=False))
    actor = _actor(scratch)
    try:
        with _connect_scratch(scratch) as conn:
            _seed_kept_rows(conn, actor.id)
            before = _kept_snapshot(conn)
            announcements_before = conn.execute(
                "SELECT count(*) FROM hr_announcements").fetchone()[0]

        named = ("users", "roles", "products", "suppliers", "employees", "tax_rates",
                 "discount_slabs", "document_sequences", "feature_flags",
                 "company_profile", "hr_leave_types")
        assert all(before["counts"].values()), {
            name: count for name, count in before["counts"].items() if not count}
        assert all(before["counts"][name] > 0 for name in named), before["counts"]
        assert any(permissions != "[]" for _, permissions in before["roles"])
        assert announcements_before > 0              # a CLEAR table has something to lose

        _run_flow(actor, "business")

        with _connect_scratch(scratch) as conn:
            after = _kept_snapshot(conn)
            cleared = {name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                       for name in db_reset.BUSINESS_TABLES}
            revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]

        assert after["counts"] == before["counts"], {
            name: (before["counts"][name], after["counts"][name])
            for name in before["counts"] if before["counts"][name] != after["counts"][name]}
        assert after["roles"] == before["roles"]        # role-permission links intact
        assert after["flags"] == before["flags"]
        assert after["company"] == before["company"]
        assert cleared == {name: 0 for name in db_reset.BUSINESS_TABLES}, cleared
        assert revision is not None                    # schema bookkeeping kept
    finally:
        _drop_scratch("herbanova_bcs_resetkeep_test")


def test_business_mode_clears_transactions_and_keeps_settings(reset_env, separate_devices,
                                                              monkeypatch, tmp_path):
    scratch = _scratch_database("herbanova_bcs_resetbiz_test")
    monkeypatch.setattr(settings, "database_url",
                        scratch.render_as_string(hide_password=False))
    actor = _actor(scratch)
    try:
        result = _run_flow(actor, "business")
        assert result["mode"] == "business"
        with psycopg.connect(host=scratch.host or "localhost", port=scratch.port or 5432,
                             user=scratch.username, password=scratch.password,
                             dbname=scratch.database) as conn:
            counts = {name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                      for name in ("products", "suppliers", "users",
                                   "hr_announcements", "hr_leave_types")}
            roles = {row[0] for row in conn.execute("SELECT name FROM roles").fetchall()}
        assert counts["hr_announcements"] == 0          # transaction removed
        assert counts["products"] == 1                  # master kept
        assert counts["suppliers"] == 1
        assert counts["users"] >= 1 and {"admin", "sales"} <= roles
        assert db_reset.current_maintenance() is None
        events = _audit_events(reset_env)
        assert "db.reset_completed" in events
        manifests = list(Path(reset_env["primary"]).glob("*.result.json"))
        assert manifests and "completed" in manifests[0].read_text(encoding="utf-8")
    finally:
        _drop_scratch("herbanova_bcs_resetbiz_test")


def test_full_mode_rebuilds_the_schema_and_the_base_admin(reset_env, separate_devices,
                                                          monkeypatch):
    scratch = _scratch_database("herbanova_bcs_resetfull_test")
    monkeypatch.setattr(settings, "database_url",
                        scratch.render_as_string(hide_password=False))
    actor = _actor(scratch)
    try:
        result = _run_flow(actor, "full")
        assert result["mode"] == "full" and result["sign_in_again"] is True
        with psycopg.connect(host=scratch.host or "localhost", port=scratch.port or 5432,
                             user=scratch.username, password=scratch.password,
                             dbname=scratch.database) as conn:
            revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            users = conn.execute(
                "SELECT username, password_hash, must_change_password FROM users").fetchall()
            products = conn.execute("SELECT count(*) FROM products").fetchone()[0]
            roles = {row[0] for row in conn.execute("SELECT name FROM roles").fetchall()}
            employees = conn.execute("SELECT code FROM employees").fetchall()
        assert revision == "0019_db_reset_key"
        assert len(users) == 1 and users[0][0] == "admin"
        assert users[0][2] is True                       # must change on next sign-in
        assert verify_password(PASSWORD, users[0][1])    # the operator's own password
        assert products == 0 and employees == [("ADMIN",)]
        assert {"admin", "sales", "inventory", "viewer"} <= roles
        assert db_reset.current_maintenance() is None
        # The audit file lives outside the database, so a full reset cannot
        # erase the trail of the run that caused it.
        events = _audit_events(reset_env)
        assert {"db.reset_started", "db.reset_backups_created",
                "db.reset_backups_verified", "db.reset_completed"} <= set(events), events
    finally:
        _drop_scratch("herbanova_bcs_resetfull_test")


def test_the_audit_file_survives_a_full_reset(reset_env, separate_devices, monkeypatch):
    scratch = _scratch_database("herbanova_bcs_resetaudit_test")
    monkeypatch.setattr(settings, "database_url",
                        scratch.render_as_string(hide_password=False))
    actor = _actor(scratch)
    try:
        result = _run_flow(actor, "full")
        records = _audit_records(reset_env)
        names = [r["event"] for r in records]
        assert {"db.reset_started", "db.reset_backups_created",
                "db.reset_backups_verified", "db.reset_completed"} <= set(names), names
        completed = next(r for r in records if r["event"] == "db.reset_completed")
        assert completed["run_id"] == result["run_id"]
        assert completed["mode"] == "full"
        # The backups are still on disk and named in the completion record.
        for label in ("primary", "mirror"):
            assert Path(completed["backups"][label]["path"]).exists()
    finally:
        _drop_scratch("herbanova_bcs_resetaudit_test")


def test_a_failed_migration_after_the_drop_keeps_writes_paused(reset_env, separate_devices,
                                                               monkeypatch):
    """Full mode: the schema is gone and the replay fails. Nothing may resume."""
    scratch = _scratch_database("herbanova_bcs_resetfail_test")
    monkeypatch.setattr(settings, "database_url",
                        scratch.render_as_string(hide_password=False))
    actor = _actor(scratch)
    real_run = db_reset.subprocess.run
    try:
        started = db_reset.begin(actor, "full", PASSWORD,
                                 f"RESET {db_reset.database_name()}")
        made = db_reset.create_backups(actor, started["run_id"], started["token"])
        verified = db_reset.verify_backups(actor, started["run_id"], made["token"])
        assert verified["ok"] is True

        def failing_alembic(command, *args, **kwargs):
            if any("alembic" in str(part) for part in command):
                return subprocess.CompletedProcess(command, 1, "",
                                                   "simulated migration failure")
            return real_run(command, *args, **kwargs)

        monkeypatch.setattr(db_reset.subprocess, "run", failing_alembic)
        with pytest.raises(HTTPException) as caught:
            db_reset.execute(actor, started["run_id"], verified["token"], RESET_KEY)
        assert caught.value.status_code == 500
        assert "writes remain paused" in caught.value.detail

        run = db_reset.load_run(started["run_id"])
        assert run["stage"] == "failed"
        assert "alembic upgrade head failed" in run["error"]
        assert "simulated migration failure" in run["error"]
        assert db_reset.current_maintenance() is not None      # still paused

        records = _audit_records(reset_env)
        failure = next(r for r in records if r["event"] == "db.reset_failed")
        assert failure["run_id"] == started["run_id"]
        assert failure["maintenance"] == "still on"
        assert "alembic" in failure["reason"]
        assert {Path(failure["backups"][label]["path"]).exists()
                for label in ("primary", "mirror")} == {True}

        with _connect_scratch(scratch) as conn:
            left = conn.execute("SELECT count(*) FROM pg_tables "
                                "WHERE schemaname = 'public'").fetchone()[0]
        assert left == 0                    # the schema really was dropped
    finally:
        db_reset.clear_maintenance()
        _drop_scratch("herbanova_bcs_resetfail_test")


def test_a_backup_from_the_flow_restores_into_a_clean_database(reset_env, separate_devices,
                                                               monkeypatch):
    """The backup is only useful if it can be put back: restore for real."""
    source_name = "herbanova_bcs_restoresrc_test"
    target_name = "herbanova_bcs_restoretgt_test"
    source = _scratch_database(source_name)
    monkeypatch.setattr(settings, "database_url",
                        source.render_as_string(hide_password=False))
    actor = _actor(source)
    try:
        with _connect_scratch(source) as conn:
            _seed_kept_rows(conn, actor.id)
        started = db_reset.begin(actor, "business", PASSWORD,
                                 f"RESET {db_reset.database_name()}")
        made = db_reset.create_backups(actor, started["run_id"], started["token"])
        verified = db_reset.verify_backups(actor, started["run_id"], made["token"])
        assert verified["ok"] is True
        db_reset.cancel(actor, started["run_id"])          # lift the pause, keep the files

        primary = made["backups"]["primary"]
        manifest = json.loads(Path(primary["manifest"]).read_text(encoding="utf-8"))
        plain = db_reset._fernet().decrypt(Path(primary["path"]).read_bytes())
        target = _create_empty_database(target_name)
        dump = Path(reset_env["state"]) / "restore-test.dump"
        dump.write_bytes(plain)

        restored = subprocess.run(
            [db_reset._pg_tool("pg_restore"), *db_reset._conn_args(target),
             "--no-password", "--no-owner", "-d", target.database, str(dump)],
            env=db_reset._pg_env(target), capture_output=True, text=True, timeout=900,
            stdin=subprocess.DEVNULL)
        assert restored.returncode == 0, (restored.stderr or "")[-500:]

        with psycopg.connect(host=target.host or "localhost", port=target.port or 5432,
                             user=target.username, password=target.password,
                             dbname=target.database) as conn:
            counts = db_reset._row_counts(conn)
            revision = db_reset._revision(conn)
        assert counts == manifest["row_counts"], {
            name: (manifest["row_counts"].get(name), counts.get(name))
            for name in set(counts) | set(manifest["row_counts"])
            if counts.get(name) != manifest["row_counts"].get(name)}
        assert revision == manifest["alembic_revision"]

        check = subprocess.run(
            [sys.executable, "-m", "alembic", "check"], cwd=ROOT,
            env={**os.environ,
                 "DATABASE_URL": target.render_as_string(hide_password=False)},
            capture_output=True, text=True)
        assert check.returncode == 0, (check.stdout + check.stderr)[-1000:]
    finally:
        _drop_scratch(target_name)
        _drop_scratch(source_name)
