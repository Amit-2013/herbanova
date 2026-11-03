# Guarded database reset

The **Reset Database** screen (Settings & Administration → Reset database, and the
block of the same name in Settings) lets an Administrator rebuild the database. It
is deliberately slow, asks for three separate proofs and refuses to run if either
backup cannot be proven good.

The feature is **off by default**. Nothing in this document enables it; that is a
deliberate server configuration step.

## 1. Engine and backup format

| Item | Value |
|---|---|
| Database | PostgreSQL 17, reached through `DATABASE_URL` (`postgresql+psycopg://…`) |
| Dump | `pg_dump -Fc` (custom archive), streamed to a temporary directory |
| Encryption | Fernet (AES-128-CBC + HMAC-SHA256, authenticated) with `DB_RESET_ENCRYPTION_KEY` |
| Copies | Two: `DB_RESET_BACKUP_DIR` and `DB_RESET_BACKUP_MIRROR_DIR`, which must resolve to **different devices** (checked with `os.stat().st_dev`, with a drive-letter fallback on Windows) |
| Manifest | `<stem>.manifest.json` beside each copy: SHA-256 of the ciphertext, plain/encrypted sizes, Alembic revision, per-table row counts |
| Verify | On **each** copy: file exists → SHA-256 matches → decrypts → `pg_restore --list` reads the archive → `pg_restore` into a scratch database → `alembic_version` and every table's row count match the manifest |
| Scratch database | `<database>_resetcheck_<run suffix>`, created and dropped by the service; never the live database |

A run is abandoned before any data is touched if **one** check fails on **either**
copy. The scratch database is dropped in a `finally` block.

## 2. Configuration

Set these in `.env` on the server (see `.env.example`).

```ini
DB_RESET_ENABLED=false                 # must be true for the screen and the API
DB_RESET_BACKUP_DIR=                   # e.g. D:\backups\herbanova
DB_RESET_BACKUP_MIRROR_DIR=            # e.g. E:\backups\herbanova or \\nas\herbanova
DB_RESET_ENCRYPTION_KEY=               # Fernet key, never committed
DB_RESET_STATE_DIR=var/db-reset
DB_RESET_CONFIRM_MINUTES=10            # life of the step-4 token
DB_RESET_TOKEN_MINUTES=30              # life of the step-2 and step-3 tokens
DB_RESET_MAX_ATTEMPTS=3
DB_RESET_LOCKOUT_MINUTES=60
DB_RESET_PG_BIN=                       # optional: directory holding pg_dump/pg_restore
```

Generate the key once and **store it outside the backup targets**:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`pg_dump` and `pg_restore` must be available. If they are not on `PATH`, point
`DB_RESET_PG_BIN` at the `bin` directory of the PostgreSQL client installation.

The screen reports each prerequisite as a pass/fail chip; the server re-checks the
same list before the run starts and again before the backup is taken. The service
never prints the key, a password or a connection string.

## 3. The four steps (all enforced on the server)

Every step is its own endpoint. Each one validates — independently of the browser —
the signed step token **and** the run journal on disk, so calling the endpoints out
of order, or with a token minted for an earlier stage, is rejected.

| # | Endpoint | Requires | Produces |
|---|---|---|---|
| 1 | `POST /api/db-reset/begin` | Administrator with `db:reset`; own login password; the exact phrase `RESET <database>`; feature enabled; not locked | run id, backup-stage token |
| 2 | `POST /api/db-reset/backup` | backup-stage token; journal still at `awaiting_backup`; prerequisites still pass; devices differ | two encrypted copies + manifests, maintenance mode **on**, verify-stage token |
| 3 | `POST /api/db-reset/verify` | verify-stage token; journal at `awaiting_verification`; all seven checks on both copies | execute-stage token, valid for `DB_RESET_CONFIRM_MINUTES` |
| 4 | `POST /api/db-reset/execute` | execute-stage token (expired → 410); journal at `verified`; verification recorded as `ok`; **separate reset key**; maintenance active for this run | the reset, a result file, `sign_in_again` for full mode |
| — | `POST /api/db-reset/cancel` | feature access | run marked `cancelled`, maintenance lifted, audited |

Rejections: `403` wrong secret or wrong stage token, `409` wrong journal stage or a
failed prerequisite/verification, `410` expired token, `423` the feature is locked.

The reset key is a third secret, distinct from the login password. An Administrator
sets or changes it with `POST /api/admin/reset-key` (minimum 16 characters). The
request must also carry the Administrator's **current login password**: knowing the
reset key alone, or borrowing an open browser session, is not enough to replace it.
The server refuses a key that equals the login password or the secondary password.
Only an argon2 hash is stored. The key is never displayed again.
`test_changing_the_reset_key_requires_the_current_login_password` covers the
missing password (`422`), a wrong password (`403`, stored hash unchanged) and the
correct password (`204`, new key verifies).

Step 4 is a *second* confirmation of an already verified run: its token expires
after ten minutes, so verifying a backup and pressing reset tomorrow does not work.

## 4. The two modes

### 4.1 Every table is classified

The database has 88 tables in schema `public` at migration `0030_sign_in_content`. Each one is in exactly one list:
**CLEAR** (emptied by a business reset), **KEEP** (must survive it) or **SCHEMA**
(Alembic bookkeeping, never touched). The lists live in
`app/services/db_reset.py` (`BUSINESS_TABLES`, `KEPT_TABLES`, `SCHEMA_TABLES`).
`test_every_table_is_classified_clear_keep_or_schema` fails if a migration adds a
table that appears in none of them, so a new table cannot silently escape the
decision.

**Business reset — CLEAR (46 tables, `TRUNCATE … RESTART IDENTITY CASCADE`)**

| Table | What it holds |
|---|---|
| `approval_requests` | approval workflow state |
| `bank_statements`, `bank_statement_lines` | captured bank statements and the lines matched to book entries |
| `batches` | stock batches |
| `cost_corrections` | audited cost corrections and backfills |
| `credit_notes`, `credit_note_lines` | customer credit notes |
| `debit_notes`, `debit_note_lines` | supplier debit notes |
| `email_deliveries` | queued/sent report emails |
| `email_test_messages` | test-email composer history |
| `expenses` | expense entries (heads and settings are masters and are kept) |
| `foc_notes`, `foc_note_lines` | free-sample (FOC) notes and lines |
| `goods_receipts`, `goods_receipt_lines` | inward receipts |
| `gst_returns` | figures reported as filed for GSTR-1/GSTR-3B |
| `hr_announcements` | published notices |
| `hr_attendance`, `hr_attendance_corrections` | attendance events and corrections |
| `hr_import_batches` | bulk-import runs |
| `hr_leave_applications`, `hr_leave_balances` | leave requests and balances |
| `hr_notifications` | in-app notifications |
| `hr_od_requests` | on-duty requests |
| `hr_payroll_periods`, `hr_payroll_entries`, `hr_payroll_entry_lines`, `hr_payroll_corrections` | payroll runs and corrections |
| `invoices`, `invoice_lines` | sales invoices |
| `leads`, `lead_activities` | CRM pipeline |
| `opening_balances` | the position carried into a financial year, per ledger head |
| `payment_allocations` | the settled part of each receipt or payment; the unallocated remainder is the party's advance |
| `payments` | receipts and payments |
| `print_logs` | print/PDF history |
| `purchase_invoices` | supplier tax invoices captured for input GST and vendor TDS |
| `purchase_orders`, `purchase_order_lines` | purchase orders |
| `sales_orders`, `sales_order_lines` | sales orders |
| `statutory_challans` | deposits of deducted TDS and payroll statutory dues |
| `stock_movements` | stock ledger |
| `vouchers`, `voucher_lines` | manual journal vouchers and their lines |

**Business reset — KEEP (41 tables)**

| Table | What survives |
|---|---|
| `users` | login accounts (password hashes, flags) |
| `roles` | roles **and their permission lists** (`roles.permissions` JSON) |
| `employees` | employee master, including salary/bank/ID fields |
| `company_profile` | legal entity and invoice identity |
| `products`, `suppliers`, `distributors`, `warehouses` | trading masters |
| `tax_rates` | GST/HSN rate master |
| `discount_slabs` | discount policy |
| `document_sequences` | invoice/order numbering counters |
| `feature_flags` | module switches |
| `email_settings`, `email_recipients`, `email_schedules`, `email_schedule_recipients` | SMTP settings, recipient list, schedules |
| `expense_heads`, `expense_settings` | expense head master and the tracked-from / approval-threshold settings |
| `financial_year_closes` | closed financial years, with who closed or reopened them and why; kept so a reset cannot silently reopen a closed year |
| `ledger_accounts` | the chart of accounts (seeded with the document roles and extended by hand); kept so booked vouchers never point at a head a reset deleted |
| `sign_in_banners`, `sign_in_notices`, `sign_in_contacts`, `legal_documents` | the Administrator-written sign-in page content and the two legal documents; kept so a data reset never empties the public page or republishes invented text |
| `hr_branches`, `hr_departments`, `hr_work_locations`, `hr_shifts`, `hr_holidays`, `hr_leave_types` | HR location and calendar masters |
| `hr_salary_components`, `hr_salary_structures`, `hr_salary_structure_lines` | salary configuration |
| `hr_attendance_rules`, `hr_approval_workflows`, `hr_letter_templates`, `hr_saved_filters`, `hr_period_locks` | HR policy and configuration |
| `hr_employee_documents`, `hr_employee_assets` | employee records that are not transactions |
| `audit_log` | the in-database audit trail |

**SCHEMA (1 table)** — `alembic_version` keeps its revision so the application
still knows which migration is installed.

**The CASCADE guarantee.** PostgreSQL's `TRUNCATE … CASCADE` also empties tables
that hold a foreign key *into* a truncated table, transitively. Before deleting
anything, `_reset_business_data` reads the real constraint graph from
`pg_constraint` and computes everything the statement would reach
(`_cascade_reaches`). If any reached table is not on the CLEAR list, the reset is
refused with a `500` and **nothing is truncated**. Two tests pin this down:
`test_the_truncate_cannot_reach_a_kept_table` (the shipped schema reaches only
CLEAR tables) and `test_the_reset_refuses_when_cascade_reaches_a_kept_table`
(adds a foreign key from a KEEP table to a CLEAR table and proves the run stops
before data is lost).

`test_business_mode_leaves_every_kept_table_untouched` seeds at least one row in
all 37 KEEP tables, snapshots every count plus the role permission lists, feature
flags and company profile, runs a real business reset, and asserts every KEEP
count and setting is unchanged while every CLEAR table is at zero.

### 4.2 Full reset

**Full reset** — snapshots the acting Administrator's username and password hash,
drops and recreates schema `public`, runs `alembic upgrade head`, and inserts one
`Employee` (`ADMIN`) and one `User` (`admin`) carrying the **same password hash** with
`must_change_password = true`. Nobody's password is generated, printed or logged.
Every other session is invalid because the table is new.

If the migration fails after the schema has been dropped:

- the run journal is written with `stage: "failed"` and the Alembic error text;
- **maintenance stays on** — writes keep returning `503` instead of reaching a
  half-built database;
- `db.reset_failed` is appended to `audit/reset-audit.jsonl` with
  `maintenance: "still on"` and both backup paths;
- the API answers `500` with "The reset failed and writes remain paused. The
  backups were kept: …".

The operator then restores a backup (§8) or, if the empty schema is intended,
cancels the run (`POST /api/db-reset/cancel`) to lift the pause.
`test_a_failed_migration_after_the_drop_keeps_writes_paused` simulates the failed
`alembic` call and asserts all four points, including that the schema really is
empty and the two backup files still exist.

## 5. Maintenance mode while the reset runs

Writes pause from the moment **before** the dump is taken (so the manifest's row
counts describe the same state the dump contains) until the run completes, fails or
is cancelled. A middleware answers `503` with `Retry-After: 60` on any non-`GET`
request under `/api/*`, except:

- `/api/db-reset/*` (the four steps themselves)
- `/api/health`
- `/api/auth/logout`

Reads (`GET`) keep working. The pause is a file, not in-memory state, so a crash
cannot leave half-held state behind, and it expires on its own after
`DB_RESET_LOCKOUT_MINUTES` (default 60 minutes) — an abandoned run cannot freeze
the application for ever.

**Background work also pauses.** The scheduled-report worker
(`app/services/email_worker.py`) opens no database work and no mail while the
maintenance file is active: `run_once` returns `{"paused": true, …}` before
enqueuing, recovering or sending anything. `test_the_email_worker_pauses_during_maintenance`
stubs all three steps and proves they are not called, then proves they resume when
the pause is lifted. There is no separate in-process scheduler: the worker's
`enqueue_due` step is the only scheduler, so pausing the worker pauses scheduling
as well.

**After a crash: clearing a stuck maintenance flag.** If the server died mid-run
and the file is still present, either:

1. Wait for the window to expire (`expires_at` in
   `<DB_RESET_STATE_DIR>/maintenance.json`, at most `DB_RESET_LOCKOUT_MINUTES`
   after it started), or
2. Stop the application and delete the file:

   ```bash
   rm var/db-reset/maintenance.json          # DB_RESET_STATE_DIR/maintenance.json
   ```

   Restarting is enough; the file is re-read on every request. Deleting it does
   **not** roll back a partial reset — inspect `runs/<run-id>.json` and the audit
   file first, and restore a backup if the schema is incomplete. Every reset
   endpoint except `/status` is refused while the feature is off, so delete the
   file only with the feature disabled or an operator present.

## 6. Lockout

Three wrong secrets (password, phrase or reset key) by the same Administrator lock
the feature for that account for `DB_RESET_LOCKOUT_MINUTES` (default 60 minutes)
and write a `db.reset_locked` audit event. Every later call returns `423` with the
remaining minutes. The counter lives in `<DB_RESET_STATE_DIR>/attempts.json`, not
in the database.

To unlock before the window expires:

1. Preferred: wait until `locked_until` in `attempts.json` passes; the next call
   succeeds and the lock record is cleared automatically.
2. Stop the application and delete the entry (or the whole file):

   ```bash
   rm var/db-reset/attempts.json            # all accounts
   ```

   Editing the file to remove only the affected administrator's entry is also
   possible; keep the JSON valid. Deleting is audited the next time a reset is used
   only indirectly — record the reason in your own operations log.

A successful reset key entry clears the counter (`clear_failures`). Lockout is per
administrator, so one person's mistakes do not block another administrator.

## 7. Audit and run journal, outside the database

All of it lives under `DB_RESET_STATE_DIR` (default `var/db-reset`), so it survives a
full reset:

```
runs/<run-id>.json          stage, actor, mode, backup paths, verification, result
attempts.json               per-administrator failure counter and lock time
maintenance.json            active run id and expiry
audit/reset-audit.jsonl     append-only one-line JSON events
```

Audited events: `db.reset_started`, `db.reset_backups_created`,
`db.reset_backups_verified`, `db.reset_completed`, `db.reset_failed`,
`db.reset_cancelled`, `db.reset_locked`, plus maintenance on/off and failed
authentication. Each event carries a timestamp, run id, actor id/username, mode and
— for backups — both paths and the ciphertext SHA-256. No secret, token or
connection string is ever written.

A full reset drops the database schema, but not this directory: the events from
that run, including `db.reset_completed`, are still there afterwards.
`test_the_audit_file_survives_a_full_reset` asserts the four run events, the run
id, the mode and that both backup files named in the completion record still
exist.

## 8. Encryption key custody and restoring a backup

### 8.1 Keep an offline copy of the key

`DB_RESET_ENCRYPTION_KEY` is the only thing that can decrypt either backup copy. Store
at least two copies **outside** the backup targets and outside the database:

- a sealed copy in the organisation's password vault, and
- a second copy in a physically separate, access-controlled place (for example a
  sealed envelope in the safe, or an offline password manager on a machine that is
  not the database host).

Never commit it, never email it, never store it in `DB_RESET_BACKUP_DIR` or
`DB_RESET_BACKUP_MIRROR_DIR` — a thief who takes both the disks and the key turns
the reset backups into a data-exfiltration source.

**If the key is lost** the encrypted backups can no longer be decrypted by anyone,
including this application. The reset flow still works going forward (after a new
key is generated), but the copies made before the loss are unrecoverable; the
manifest's SHA-256 values can still prove the files are intact, not what they
contained. Recovery then has to rely on database-level backups kept outside this
feature. Rotating the key means: take a fresh backup **before** changing it; after
rotation only new backups can be opened.

### 8.2 Restoring a backup by hand

If the reset itself has to be undone (or a full reset failed after the drop),
both copies are on disk and independent. The procedure below is the one exercised
by `test_a_backup_from_the_flow_restores_into_a_clean_database`: it backs up a
seeded database through the real flow, decrypts the primary copy, restores it into
an **empty** database, compares every table's row count with the manifest, checks
the Alembic revision and runs `alembic check` against the restored copy.

```bash
# 1. Decrypt one copy (the key is read from the environment; it is never echoed)
python - <<'PY'
import os, pathlib
from cryptography.fernet import Fernet
blob = pathlib.Path(os.environ["BACKUP_FILE"]).read_bytes()
pathlib.Path("restore.dump").write_bytes(
    Fernet(os.environ["DB_RESET_ENCRYPTION_KEY"].encode()).decrypt(blob))
PY

# 2. Prove the archive is readable, then restore into an empty database
pg_restore --list restore.dump
createdb herbanova_restore
pg_restore --no-owner -d herbanova_restore restore.dump

# 3. Compare counts with the manifest and prove the schema matches the code
psql -d herbanova_restore -c "SELECT version_num FROM alembic_version"
DATABASE_URL=postgresql+psycopg://…/herbanova_restore python -m alembic check
```

`alembic check` exits 0 when the restored schema matches the models at the
current head; a non-zero exit means the copy or the code has drifted and must not
be promoted. Compare every table count in `<stem>.manifest.json` before letting
users back in. The 503 pause is lifted with `POST /api/db-reset/cancel` (or by
deleting `maintenance.json`, §5) once the restore is confirmed.

## 9. Status of the implementation

- Four-step flow, backup, verification, both modes, the CASCADE guard, maintenance
  mode (including worker pause), lockout, audit trail, reset-key endpoint and the
  Settings screen are implemented.
- `tests/test_db_reset.py` covers 24 cases against isolated `_test` databases,
  including a business reset that leaves all 37 KEEP tables untouched, a full
  reset, a failed migration after the drop, a real restore into a clean database
  followed by `alembic check`, and the audit trail surviving a full reset.
  The whole project suite was 446 passed / 0 failed when last run (3 Nov 2026).
- The feature is **not enabled** in this checkout; `DB_RESET_ENABLED` is unset in
  `.env` and false in `.env.example`.
- Not exercised end to end: a real click-through in a browser with the feature
  enabled on a server that owns two physical disks. The two-copy rule was proven
  with the real device check on one disk-pair and with the device predicate
  stubbed for the happy paths.
- Not simulated: a machine power-loss during `TRUNCATE`/`DROP SCHEMA` (PostgreSQL
  transactions make each of those atomic; the documented recovery is the
  maintenance-file deletion in §5 and the restore in §8).
