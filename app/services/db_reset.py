"""Guarded database reset.

A reset is a four-step procedure, and every step is checked by the server; a
browser that skips one gets a 409, not a wipe.

    1. begin    login password + the phrase ``RESET <database>``
    2. backup   pg_dump, encrypted, written to two directories on different devices
    3. verify   checksum, decryption, restore into a scratch database and row counts
    4. execute  a separate reset key, within ten minutes of verification

The run journal, the failure counter and the audit trail are files under
``DB_RESET_STATE_DIR``, never rows in the database being reset. Writes are
paused (503) from the backup until the run finishes or is cancelled.

Two modes:

* ``business`` (default) clears documents, stock, payments and HR transactions
  and keeps users, employees, roles, settings and master data.
* ``full`` drops the schema, replays the migrations and recreates the base
  Administrator. Everyone must sign in again and set new secrets.

This module never logs a password, a key, a token or a connection string. The
dump is encrypted with Fernet (AES-128-CBC + HMAC-SHA256, authenticated); the
key comes from the environment, so a stolen backup directory is not readable.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import psycopg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy.engine import make_url

from ..core.config import settings

ROOT = Path(__file__).resolve().parents[2]
MODES = ("business", "full")

# Tables cleared in business mode. This is the transactional half of the schema:
# documents, stock, money, HR events and delivery logs. It deliberately keeps
# users, roles, employees, settings, master data, document numbering and the
# in-database audit trail.
BUSINESS_TABLES = (
    "approval_requests",
    "batches",
    "credit_note_lines", "credit_notes",
    "debit_note_lines", "debit_notes",
    "email_deliveries", "email_test_messages",
    "expenses",
    "goods_receipt_lines", "goods_receipts",
    "hr_announcements",
    "hr_attendance", "hr_attendance_corrections", "hr_import_batches",
    "hr_leave_applications", "hr_leave_balances",
    "hr_notifications", "hr_od_requests",
    "hr_payroll_corrections", "hr_payroll_entries", "hr_payroll_entry_lines",
    "hr_payroll_periods",
    "invoice_lines", "invoices",
    "lead_activities", "leads",
    "payments",
    "print_logs",
    "purchase_order_lines", "purchase_orders",
    "sales_order_lines", "sales_orders",
    "stock_movements",
)

# Kept by a business reset. Listed so the screen and the documentation can state
# exactly what survives, and so tests can prove it.
KEPT_TABLES = (
    "company_profile", "discount_slabs", "distributors", "document_sequences",
    "email_recipients", "email_schedule_recipients", "email_schedules",
    "email_settings", "feature_flags", "expense_heads", "expense_settings",
    "hr_approval_workflows", "hr_attendance_rules", "hr_branches", "hr_departments",
    "hr_employee_assets", "hr_employee_documents", "hr_holidays", "hr_leave_types",
    "hr_letter_templates", "hr_period_locks", "hr_salary_components",
    "hr_salary_structure_lines", "hr_salary_structures", "hr_saved_filters",
    "hr_shifts", "hr_work_locations",
    "products", "roles", "suppliers",
    "tax_rates", "users", "warehouses", "employees", "audit_log",
)

# Schema bookkeeping, neither business data nor configuration. A business reset
# leaves it alone so Alembic still knows which revision is installed.
SCHEMA_TABLES = ("alembic_version",)


def table_classification() -> dict:
    """Every table the application creates, split into CLEAR and KEEP.

    A test fails if a new table or migration appears in neither list; hiding a
    table from this decision is how a reset accidentally delete something.
    """
    return {"clear": list(BUSINESS_TABLES), "keep": list(KEPT_TABLES),
            "schema": list(SCHEMA_TABLES)}


def _cascade_reaches(conn, roots) -> set[str]:
    """Tables PostgreSQL will truncate for `TRUNCATE roots CASCADE`.

    CASCADE follows incoming foreign keys transitively, so this must be the real
    constraint graph from the database, not a guess from the model file.
    """
    edges = conn.execute(
        "SELECT child.relname, parent.relname FROM pg_constraint k "
        "JOIN pg_class child ON child.oid = k.conrelid "
        "JOIN pg_class parent ON parent.oid = k.confrelid "
        "JOIN pg_namespace n ON n.oid = child.relnamespace "
        "WHERE k.contype = 'f' AND n.nspname = 'public'").fetchall()
    children: dict[str, set[str]] = {}
    for child, parent in edges:
        children.setdefault(parent, set()).add(child)
    reached = set(roots)
    frontier = set(roots)
    while frontier:
        nxt = set()
        for table in frontier:
            for child in children.get(table, ()):
                if child not in reached:
                    reached.add(child)
                    nxt.add(child)
        frontier = nxt
    return reached


# ---------------------------------------------------------------- clock and paths
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _state_dir() -> Path:
    path = Path(settings.db_reset_state_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:                     # Windows has no POSIX bits; ACLs apply
        pass


def audit_dir() -> Path:
    path = _state_dir() / "audit"
    path.mkdir(parents=True, exist_ok=True)
    return path


def audit_event(event: str, **detail) -> dict:
    """Append one line to the out-of-database audit file. Never pass secrets."""
    record = {"at": _iso(_now()), "event": event, **detail}
    path = audit_dir() / "reset-audit.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")
    _chmod_private(path)
    return record


def audit_tail(limit: int = 20) -> list[dict]:
    path = audit_dir() / "reset-audit.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- run journal
def _runs_dir() -> Path:
    path = _state_dir() / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_path(run_id: str) -> Path:
    # The id is used as a file name, so keep it to a conservative character set
    # (the timestamp separator included) and never let it reach another folder.
    if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
        raise HTTPException(404, "Reset run not found")
    return _runs_dir() / f"{run_id}.json"


def save_run(run: dict) -> None:
    run["updated_at"] = _iso(_now())
    path = _run_path(run["run_id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run, indent=2, default=str), encoding="utf-8")
    _chmod_private(tmp)
    tmp.replace(path)


def load_run(run_id: str) -> dict:
    path = _run_path(run_id)
    if not path.exists():
        raise HTTPException(404, "Reset run not found")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- maintenance
def _maintenance_path() -> Path:
    return _state_dir() / "maintenance.json"


def start_maintenance(run_id: str) -> dict:
    until = _now() + timedelta(minutes=settings.db_reset_lockout_minutes)
    record = {"run_id": run_id, "started_at": _iso(_now()), "expires_at": _iso(until)}
    path = _maintenance_path()
    path.write_text(json.dumps(record), encoding="utf-8")
    _chmod_private(path)
    audit_event("db.reset_maintenance_on", run_id=run_id, expires_at=record["expires_at"])
    return record


def clear_maintenance(run_id: str | None = None) -> None:
    path = _maintenance_path()
    if not path.exists():
        return
    if run_id is not None:
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            current = {}
        if current.get("run_id") != run_id:
            return
    path.unlink(missing_ok=True)
    audit_event("db.reset_maintenance_off", run_id=run_id)


def current_maintenance() -> dict | None:
    """The active maintenance record, or None when the window has expired."""
    path = _maintenance_path()
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        expires = datetime.fromisoformat(record["expires_at"])
    except (ValueError, KeyError):
        return None
    if expires <= _now():
        return None
    return record


# ---------------------------------------------------------------- lockout
def _locks_path() -> Path:
    return _state_dir() / "attempts.json"


def _load_locks() -> dict:
    path = _locks_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _save_locks(locks: dict) -> None:
    path = _locks_path()
    path.write_text(json.dumps(locks), encoding="utf-8")
    _chmod_private(path)


def lock_state(admin_id: int) -> dict:
    entry = _load_locks().get(str(admin_id), {})
    until = entry.get("locked_until")
    locked = bool(until) and datetime.fromisoformat(until) > _now()
    return {"failures": int(entry.get("failures", 0)),
            "locked_until": until if locked else None,
            "locked": locked}


def assert_not_locked(admin_id: int) -> None:
    state = lock_state(admin_id)
    if state["locked"]:
        until = datetime.fromisoformat(state["locked_until"])
        minutes = max(1, int((until - _now()).total_seconds() // 60) + 1)
        raise HTTPException(423, f"Database reset is locked after {settings.db_reset_max_attempts} "
                                f"wrong attempts. Try again in {minutes} minute(s).")


def record_failure(admin_id: int, username: str, reason: str) -> dict:
    locks = _load_locks()
    entry = locks.get(str(admin_id), {"failures": 0})
    entry["failures"] = int(entry.get("failures", 0)) + 1
    if entry["failures"] >= settings.db_reset_max_attempts:
        entry["locked_until"] = _iso(_now() + timedelta(minutes=settings.db_reset_lockout_minutes))
        entry["failures"] = 0
        audit_event("db.reset_locked", actor_id=admin_id, actor=username,
                    reason=reason, locked_until=entry["locked_until"])
    locks[str(admin_id)] = entry
    _save_locks(locks)
    audit_event("db.reset_auth_failed", actor_id=admin_id, actor=username,
                reason=reason, failures=entry["failures"])
    return lock_state(admin_id)


def clear_failures(admin_id: int) -> None:
    locks = _load_locks()
    if str(admin_id) in locks:
        locks.pop(str(admin_id))
        _save_locks(locks)


# ---------------------------------------------------------------- step tokens
def _token(admin_id: int, run_id: str, stage: str, minutes: int) -> str:
    now = _now()
    return jwt.encode({"sub": str(admin_id), "run": run_id, "stage": stage,
                       "iat": now, "exp": now + timedelta(minutes=minutes)},
                      settings.app_secret, "HS256")


def _read_token(token: str, admin_id: int, run_id: str, stage: str) -> dict:
    try:
        claims = jwt.decode(token, settings.app_secret, ["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(410, "This step has expired. Start the reset again.")
    except jwt.PyJWTError:
        raise HTTPException(403, "This step token is not valid. Start the reset again.")
    if (str(claims.get("sub")) != str(admin_id) or claims.get("run") != run_id
            or claims.get("stage") != stage):
        raise HTTPException(403, "This token does not belong to this step.")
    return claims


# ---------------------------------------------------------------- prerequisites
def _pg_tool(name: str) -> str:
    base = settings.db_reset_pg_bin.strip()
    if base:
        candidate = Path(base) / name
        for path in (candidate, candidate.with_suffix(".exe")):
            if path.exists():
                return str(path)
    found = shutil.which(name)
    if not found:
        raise HTTPException(409, f"'{name}' is not available on the server. Install the "
                                 "PostgreSQL client tools or set DB_RESET_PG_BIN.")
    return found


def _device_key(path: str | Path) -> tuple:
    """Identify the storage device. Two backup paths on one device are refused."""
    probe = Path(path).resolve()
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return ("dev", os.stat(probe).st_dev)
    except OSError:
        return ("drive", probe.drive.lower())


def same_device(first: str | Path, second: str | Path) -> bool:
    return _device_key(first) == _device_key(second)


def _fernet() -> Fernet:
    key = settings.db_reset_encryption_key.strip()
    if not key:
        raise HTTPException(409, "DB_RESET_ENCRYPTION_KEY is not set, so backups cannot be "
                                 "encrypted. The reset is refused.")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError):
        raise HTTPException(409, "DB_RESET_ENCRYPTION_KEY is not a valid Fernet key.")


def prerequisites() -> dict:
    checks = []

    def add(key: str, ok: bool, detail: str) -> None:
        checks.append({"key": key, "ok": ok, "detail": detail})

    add("enabled", bool(settings.db_reset_enabled),
        "Switched on" if settings.db_reset_enabled else "DB_RESET_ENABLED is false")
    primary = settings.db_reset_backup_dir.strip()
    mirror = settings.db_reset_backup_mirror_dir.strip()
    add("primary_dir", bool(primary), primary or "DB_RESET_BACKUP_DIR is not set")
    add("mirror_dir", bool(mirror), mirror or "DB_RESET_BACKUP_MIRROR_DIR is not set")
    if primary and mirror:
        distinct = not same_device(primary, mirror)
        add("separate_devices", distinct,
            "Backups land on two different devices" if distinct
            else "Both backup directories are on the same device; choose another disk "
                 "or a mounted network share")
    try:
        _fernet()
        add("encryption_key", True, "Encryption key present")
    except HTTPException as exc:
        add("encryption_key", False, str(exc.detail))
    try:
        add("pg_tools", True, f"pg_dump: {_pg_tool('pg_dump')}")
    except HTTPException as exc:
        add("pg_tools", False, str(exc.detail))
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def database_name() -> str:
    return make_url(settings.database_url).database or ""


# ---------------------------------------------------------------- connections
def _url():
    return make_url(settings.database_url)


def _connect(url=None, dbname: str | None = None, autocommit: bool = False):
    url = url or _url()
    return psycopg.connect(host=url.host or "localhost", port=url.port or 5432,
                           user=url.username, password=url.password,
                           dbname=dbname or url.database, autocommit=autocommit,
                           connect_timeout=15)


def _pg_env(url) -> dict:
    return {**os.environ, "PGPASSWORD": url.password or ""}


def _conn_args(url) -> list[str]:
    return ["-h", url.host or "localhost", "-p", str(url.port or 5432),
            "-U", url.username or "postgres"]


def _row_counts(conn) -> dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1").fetchall()]
    counts = {}
    for name in names:
        counts[name] = int(conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])
    return counts


def _revision(conn) -> str | None:
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None
    except psycopg.Error:
        return None


# ---------------------------------------------------------------- step 1
def begin(admin, mode: str, password: str, phrase: str) -> dict:
    from ..core.security import verify_password

    if not settings.db_reset_enabled:
        raise HTTPException(403, "Database reset is switched off on this server. "
                                 "Set DB_RESET_ENABLED=true to allow it.")
    if mode not in MODES:
        raise HTTPException(422, "Choose 'business' or 'full'.")
    if current_maintenance():
        raise HTTPException(409, "A database reset is already in progress.")
    assert_not_locked(admin.id)

    expected = f"RESET {database_name()}".strip()
    password_ok = bool(admin.password_hash) and verify_password(password, admin.password_hash)
    phrase_ok = (phrase or "").strip() == expected
    if not password_ok or not phrase_ok:
        state = record_failure(admin.id, admin.username,
                               "wrong password" if not password_ok else "wrong phrase")
        if state["locked"]:
            raise HTTPException(423, f"Database reset is locked after "
                                     f"{settings.db_reset_max_attempts} wrong attempts.")
        # One message for both, so the screen does not reveal which secret failed.
        raise HTTPException(403, "The password or the confirmation phrase is incorrect.")

    ready = prerequisites()
    if not ready["ok"]:
        failed = "; ".join(c["detail"] for c in ready["checks"] if not c["ok"])
        raise HTTPException(409, f"The reset cannot start: {failed}")

    run_id = f"{_now():%Y%m%d%H%M%S}-{secrets.token_hex(4)}"
    run = {
        "run_id": run_id, "mode": mode, "database": database_name(),
        "actor_id": admin.id, "actor": admin.username,
        "created_at": _iso(_now()), "updated_at": _iso(_now()),
        "stage": "awaiting_backup", "backups": {}, "verification": None,
        "result": None, "error": None,
    }
    save_run(run)
    audit_event("db.reset_started", run_id=run_id, actor_id=admin.id, actor=admin.username,
                mode=mode, database=run["database"])
    expires = _now() + timedelta(minutes=settings.db_reset_token_minutes)
    return {"run_id": run_id, "mode": mode, "database": run["database"],
            "phrase": expected, "token": _token(admin.id, run_id, "backup",
                                                settings.db_reset_token_minutes),
            "expires_at": _iso(expires)}


# ---------------------------------------------------------------- step 2
def create_backups(admin, run_id: str, token: str) -> dict:
    if not settings.db_reset_enabled:
        raise HTTPException(403, "Database reset is switched off on this server.")
    assert_not_locked(admin.id)
    _read_token(token, admin.id, run_id, "backup")
    run = load_run(run_id)
    if run["actor_id"] != admin.id:
        raise HTTPException(403, "This reset run belongs to another administrator.")
    if run["stage"] != "awaiting_backup":
        raise HTTPException(409, f"This run is at stage '{run['stage']}'; backups were already made.")

    ready = prerequisites()
    if not ready["ok"]:
        failed = "; ".join(c["detail"] for c in ready["checks"] if not c["ok"])
        raise HTTPException(409, f"The reset cannot continue: {failed}")
    if current_maintenance():
        raise HTTPException(409, "A database reset is already in progress.")

    primary_dir = Path(settings.db_reset_backup_dir).resolve()
    mirror_dir = Path(settings.db_reset_backup_mirror_dir).resolve()
    if same_device(primary_dir, mirror_dir):
        raise HTTPException(409, "The two backup directories are on the same device. "
                                 "Point one of them at another disk or a network share.")
    primary_dir.mkdir(parents=True, exist_ok=True)
    mirror_dir.mkdir(parents=True, exist_ok=True)

    url = _url()
    pg_dump = _pg_tool("pg_dump")
    fernet = _fernet()
    stamp = f"{_now():%Y%m%dT%H%M%SZ}"
    stem = f"{run['database']}-{stamp}-{run_id[-8:]}"
    created_at = _iso(_now())

    # Writes pause before the dump, so the counts in the manifest describe the
    # same state as the file being verified a minute later.
    maintenance = start_maintenance(run_id)
    try:
        with _connect() as conn:
            counts = _row_counts(conn)
            revision = _revision(conn)

        with tempfile.TemporaryDirectory(dir=_state_dir()) as tmp:
            plain = Path(tmp) / "backup.dump"
            command = [pg_dump, *_conn_args(url), "--no-password", "-Fc",
                       "-f", str(plain), url.database]
            done = subprocess.run(command, env=_pg_env(url), capture_output=True,
                                  text=True, timeout=900, stdin=subprocess.DEVNULL)
            if done.returncode != 0 or not plain.exists():
                raise RuntimeError((done.stderr or "pg_dump produced no file").strip()[:400])
            raw = plain.read_bytes()
    except Exception as exc:
        run.update(stage="failed", error=f"Backup failed: {exc}")
        save_run(run)
        clear_maintenance(run_id)
        audit_event("db.reset_failed", run_id=run_id, actor_id=admin.id,
                    actor=admin.username, reason="backup", detail=str(exc)[:400])
        raise HTTPException(500, f"The backup could not be made: {exc}")

    cipher = fernet.encrypt(raw)
    digest = hashlib.sha256(cipher).hexdigest()
    manifest = {
        "database": run["database"], "created_at": created_at, "run_id": run_id,
        "format": "pg_dump custom (encrypted Fernet)",
        "plain_bytes": len(raw), "encrypted_bytes": len(cipher),
        "sha256": digest, "alembic_revision": revision, "row_counts": counts,
        "tables": len(counts),
    }
    backups = {}
    for label, directory in (("primary", primary_dir), ("mirror", mirror_dir)):
        target = directory / f"{stem}.dump.enc"
        target.write_bytes(cipher)
        _chmod_private(target)
        manifest_path = directory / f"{stem}.manifest.json"
        manifest_path.write_text(json.dumps({**manifest, "location": label},
                                            indent=2), encoding="utf-8")
        _chmod_private(manifest_path)
        backups[label] = {"path": str(target), "manifest": str(manifest_path),
                          "sha256": digest, "bytes": len(cipher),
                          "created_at": created_at}

    run.update(stage="awaiting_verification", backups=backups,
               backup_manifest=manifest)
    save_run(run)
    audit_event("db.reset_backups_created", run_id=run_id, actor_id=admin.id,
                actor=admin.username, mode=run["mode"], backups=backups,
                sha256=digest, tables=manifest["tables"],
                rows=sum(manifest["row_counts"].values()))
    expires = _now() + timedelta(minutes=settings.db_reset_token_minutes)
    return {"run_id": run_id, "stage": run["stage"], "backups": backups,
            "rows": sum(manifest["row_counts"].values()), "tables": manifest["tables"],
            "maintenance": maintenance,
            "token": _token(admin.id, run_id, "verify", settings.db_reset_token_minutes),
            "expires_at": _iso(expires)}


# ---------------------------------------------------------------- step 3
def verify_backups(admin, run_id: str, token: str) -> dict:
    if not settings.db_reset_enabled:
        raise HTTPException(403, "Database reset is switched off on this server.")
    assert_not_locked(admin.id)
    _read_token(token, admin.id, run_id, "verify")
    run = load_run(run_id)
    if run["actor_id"] != admin.id:
        raise HTTPException(403, "This reset run belongs to another administrator.")
    if run["stage"] != "awaiting_verification":
        raise HTTPException(409, f"This run is at stage '{run['stage']}'; "
                                 "the backups are not awaiting verification.")
    manifest = run.get("backup_manifest") or {}
    if not run.get("backups") or not manifest:
        raise HTTPException(409, "No backups are recorded for this run.")

    url = _url()
    pg_restore = _pg_tool("pg_restore")
    fernet = _fernet()
    scratch = f"{run['database']}_resetcheck_{run_id[-6:]}"
    if not scratch.endswith(f"_{run_id[-6:]}"):
        raise HTTPException(409, "The scratch database name is not recognisable.")
    results = []
    failures = []

    def check(label: str, key: str, ok: bool, detail: str) -> None:
        results.append({"backup": label, "key": key, "ok": ok, "detail": detail})
        if not ok:
            failures.append(f"{label}: {detail}")

    try:
        with psycopg.connect(host=url.host or "localhost", port=url.port or 5432,
                             user=url.username, password=url.password,
                             dbname="postgres", autocommit=True) as admin_conn:
            admin_conn.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
            admin_conn.execute(f'CREATE DATABASE "{scratch}"')

        for label, item in run["backups"].items():
            path = Path(item["path"])
            check(label, "exists", path.exists(), str(path))
            if not path.exists():
                continue
            blob = path.read_bytes()
            digest = hashlib.sha256(blob).hexdigest()
            check(label, "checksum", digest == item["sha256"],
                  f"sha256 {digest[:16]}â€¦" if digest == item["sha256"] else "checksum differs")
            try:
                plain = fernet.decrypt(blob)
                check(label, "decrypt", True, f"{len(plain):,} bytes decrypted")
            except InvalidToken:
                check(label, "decrypt", False,
                      "the file cannot be decrypted with DB_RESET_ENCRYPTION_KEY")
                continue
            with tempfile.TemporaryDirectory(dir=_state_dir()) as tmp:
                dump = Path(tmp) / "backup.dump"
                dump.write_bytes(plain)
                listed = subprocess.run([pg_restore, "--list", str(dump)],
                                        capture_output=True, text=True, timeout=300,
                                        stdin=subprocess.DEVNULL)
                check(label, "archive", listed.returncode == 0,
                      "pg_restore can read the archive" if listed.returncode == 0
                      else (listed.stderr or "pg_restore --list failed").strip()[:200])
                if listed.returncode != 0:
                    continue
                restored = subprocess.run(
                    [pg_restore, *_conn_args(url), "--no-password", "--no-owner",
                     "-d", scratch, str(dump)],
                    env=_pg_env(url), capture_output=True, text=True, timeout=900,
                    stdin=subprocess.DEVNULL)
                check(label, "restore", restored.returncode == 0,
                      "restored into a scratch database" if restored.returncode == 0
                      else (restored.stderr or "pg_restore failed").strip()[:300])
                if restored.returncode != 0:
                    continue
            with _connect(dbname=scratch) as conn:
                counts = _row_counts(conn)
                revision = _revision(conn)
            expected = manifest.get("row_counts") or {}
            differences = [name for name in sorted(set(expected) | set(counts))
                           if expected.get(name) != counts.get(name)]
            check(label, "row_counts", not differences,
                  f"{len(counts)} tables match the source" if not differences
                  else f"{len(differences)} table(s) differ: " + ", ".join(differences[:5]))
            check(label, "revision", revision == manifest.get("alembic_revision"),
                  f"alembic {revision}")
            # Each copy is restored in turn; the scratch database is emptied
            # between copies so the second proof is independent.
            with psycopg.connect(host=url.host or "localhost", port=url.port or 5432,
                                 user=url.username, password=url.password,
                                 dbname="postgres", autocommit=True) as admin_conn:
                admin_conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()", (scratch,))
                admin_conn.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
                admin_conn.execute(f'CREATE DATABASE "{scratch}"')
    finally:
        try:
            with psycopg.connect(host=url.host or "localhost", port=url.port or 5432,
                                 user=url.username, password=url.password,
                                 dbname="postgres", autocommit=True) as admin_conn:
                admin_conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()", (scratch,))
                admin_conn.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
        except psycopg.Error:
            pass

    ok = not failures
    verification = {"ok": ok, "checks": results, "at": _iso(_now())}
    if not ok:
        run.update(stage="failed", verification=verification,
                   error="Backup verification failed: " + "; ".join(failures[:3]))
        save_run(run)
        clear_maintenance(run_id)
        audit_event("db.reset_failed", run_id=run_id, actor_id=admin.id,
                    actor=admin.username, reason="backup verification",
                    failures=failures[:10])
        raise HTTPException(409, "A backup failed verification, so the data was not touched: "
                                 + "; ".join(failures[:3]))

    run.update(stage="verified", verification=verification)
    save_run(run)
    audit_event("db.reset_backups_verified", run_id=run_id, actor_id=admin.id,
                actor=admin.username, checks=len(results))
    expires = _now() + timedelta(minutes=settings.db_reset_confirm_minutes)
    return {"run_id": run_id, "stage": "verified", "ok": True, "checks": results,
            "maintenance": current_maintenance(),
            "token": _token(admin.id, run_id, "execute", settings.db_reset_confirm_minutes),
            "expires_at": _iso(expires),
            "confirm_minutes": settings.db_reset_confirm_minutes}


# ---------------------------------------------------------------- step 4
def execute(admin, run_id: str, token: str, reset_key: str) -> dict:
    from ..core.security import verify_secondary_password

    if not settings.db_reset_enabled:
        raise HTTPException(403, "Database reset is switched off on this server.")
    assert_not_locked(admin.id)
    _read_token(token, admin.id, run_id, "execute")
    run = load_run(run_id)
    if run["actor_id"] != admin.id:
        raise HTTPException(403, "This reset run belongs to another administrator.")
    if run["stage"] != "verified":
        raise HTTPException(409, f"This run is at stage '{run['stage']}'; execute requires a "
                                 "verified backup.")
    if not (run.get("verification") or {}).get("ok"):
        raise HTTPException(409, "The backups were not verified. Execute is refused.")
    if not admin.reset_key_hash:
        raise HTTPException(409, "No reset key is set for this administrator. "
                                 "Set one with POST /api/admin/reset-key.")

    if not verify_secondary_password(admin.reset_key_hash, reset_key or ""):
        state = record_failure(admin.id, admin.username, "wrong reset key")
        if state["locked"]:
            raise HTTPException(423, "Database reset is locked after "
                                     f"{settings.db_reset_max_attempts} wrong attempts.")
        raise HTTPException(403, "The reset key is incorrect.")

    maintenance = current_maintenance()
    if not maintenance or maintenance.get("run_id") != run_id:
        raise HTTPException(409, "The maintenance window for this run has expired. "
                                 "Start again so a fresh backup is taken.")

    mode = run["mode"]
    actor_id, actor_name = admin.id, admin.username
    try:
        if mode == "business":
            result = _reset_business_data()
        else:
            result = _reset_full(actor_id)
    except Exception as exc:                       # record, keep writes paused
        run.update(stage="failed", error=f"Reset failed: {exc}")
        save_run(run)
        # Maintenance deliberately stays on. A full reset may have dropped the
        # schema before failing, so letting writes resume would let requests hit
        # a half-built database. An operator restores the backup (or cancels the
        # run, which lifts the pause) once the cause is understood.
        audit_event("db.reset_failed", run_id=run_id, actor_id=actor_id,
                    actor=actor_name, mode=mode, reason=str(exc)[:500],
                    maintenance="still on", backups=run.get("backups"))
        raise HTTPException(500, "The reset failed and writes remain paused. The backups "
                                 "were kept: " + str(exc)[:300])

    run.update(stage="completed", result=result, error=None)
    save_run(run)
    clear_maintenance(run_id)
    clear_failures(actor_id)
    audit_event("db.reset_completed", run_id=run_id, actor_id=actor_id, actor=actor_name,
                mode=mode, backups=run.get("backups"), verification="passed",
                result=result)
    summary = {**run, "audit_file": str(audit_dir() / "reset-audit.jsonl")}
    for item in (run.get("backups") or {}).values():
        try:
            target = Path(item["manifest"]).with_name(
                Path(item["manifest"]).name.replace(".manifest.json", ".result.json"))
            target.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            _chmod_private(target)
        except OSError:
            pass
    return {"run_id": run_id, "mode": mode, "stage": "completed",
            "completed_at": _iso(_now()), "result": result,
            "sign_in_again": mode == "full"}


def cancel(admin, run_id: str) -> dict:
    run = load_run(run_id)
    if run["actor_id"] != admin.id:
        raise HTTPException(403, "This reset run belongs to another administrator.")
    if run["stage"] == "completed":
        raise HTTPException(409, "This run has already completed.")
    run.update(stage="cancelled", error="Cancelled by the administrator")
    save_run(run)
    clear_maintenance(run_id)
    audit_event("db.reset_cancelled", run_id=run_id, actor_id=admin.id, actor=admin.username)
    return {"run_id": run_id, "stage": "cancelled"}


# ---------------------------------------------------------------- execution
def _reset_business_data() -> dict:
    url = _url()
    with _connect() as conn:
        existing = {r[0] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()}
        tables = [t for t in BUSINESS_TABLES if t in existing]
        if not tables:
            raise RuntimeError("No business tables were found; nothing was cleared.")
        # Refuse before deleting anything if a foreign key would drag a KEEP
        # table into the CASCADE. The schema is checked, not assumed.
        reached = _cascade_reaches(conn, tables)
        leaked = sorted(reached - set(tables))
        if leaked:
            raise RuntimeError("TRUNCATE CASCADE would also clear kept table(s): "
                               + ", ".join(leaked) + ". The reset was refused.")
        before = {t: int(conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0])
                  for t in tables}
        statement = "TRUNCATE TABLE " + ", ".join(f'"{t}"' for t in tables) + \
                    " RESTART IDENTITY CASCADE"
        conn.execute(statement)
    return {"mode": "business", "tables_cleared": len(tables),
            "rows_cleared": sum(before.values()), "tables": tables}


def _reset_full(actor_id: int) -> dict:
    """Drop the schema, replay migrations and recreate the base Administrator.

    The base account keeps the acting administrator's password hash (the only
    copy of the credential that survives is the hash, which is never printed)
    and must change it at the next sign-in. The reset key and secondary password
    are deliberately not carried over.
    """
    url = _url()
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, password_hash FROM users WHERE id = %s", (actor_id,)).fetchone()
    if not row:
        raise RuntimeError("The acting administrator no longer exists.")
    original_username, password_hash = row

    with psycopg.connect(host=url.host or "localhost", port=url.port or 5432,
                         user=url.username, password=url.password,
                         dbname="postgres", autocommit=True) as admin_conn:
        admin_conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                           "WHERE datname = %s AND pid <> pg_backend_pid()",
                           (url.database,))
    # Terminating the backends leaves the application pool holding sockets that
    # point at the schema which is about to disappear. Drop the pool so later
    # requests open fresh connections against the rebuilt schema.
    from ..core.db import engine
    engine.dispose()
    with _connect(autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")

    env = {**os.environ, "DATABASE_URL": settings.database_url}
    upgraded = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    if upgraded.returncode != 0:
        raise RuntimeError("alembic upgrade head failed: "
                           + (upgraded.stderr or upgraded.stdout).strip()[-500:])

    with _connect() as conn:
        revision = _revision(conn)
        role_id = conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()
        if not role_id:
            raise RuntimeError("The admin role was not recreated by the migrations.")
        employee_id = conn.execute(
            "INSERT INTO employees (code, full_name, designation, status) "
            "VALUES ('ADMIN', 'Administrator', 'Administrator', 'active') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO users (username, username_key, password_hash, role, role_id, "
            "employee_id, is_active, must_change_password, failed_attempts, token_version) "
            "VALUES ('admin', 'admin', %s, 'admin', %s, %s, true, true, 0, 1)",
            (password_hash, role_id[0], employee_id))
    engine.dispose()
    return {"mode": "full", "schema_rebuilt": True, "alembic_revision": revision,
            "base_admin": "admin", "created_from_account": original_username,
            "roles_restored": True, "must_change_password": True}
