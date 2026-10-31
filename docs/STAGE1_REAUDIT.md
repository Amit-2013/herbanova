# Herbanova — Stage 1 re-audit (current state)

**Date:** 31 October 2026
**Purpose:** Re-establish the Stage 1 baseline for the new remediation brief against the
current source tree and the live development database. This supersedes the figures in
`docs/STAGE1_AUDIT_BASELINE.md` where they differ; that document remains the record of the
original audit and the Stage 4 record shows what was fixed.

**Scope:** Read-only. No application code, migration or database row was changed. The only
file created is this one.

**Method:** every item below was reproduced by a command against the real tree or the live
database (`localhost:5432/herbanova_bcs_dev`). Nothing is inferred from a file merely
existing.

---

## 1. Verified current baseline

| Item | Verified value |
|---|---|
| Runtime | Python 3.14.7 (Windows, Git Bash) |
| Web / ORM | FastAPI, Pydantic v2, SQLAlchemy 2.x, PostgreSQL 17 |
| Router modules | 25 (`app/api/`, plus `__init__`) |
| API route objects | 158 = 158 method/path pairs over 118 unique paths |
| Public route objects | 3 by design: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/health`; every other route carries an authentication/permission dependency in its signature |
| Service modules | 24 (`app/services/`) |
| ORM tables | 50 across 6 model modules |
| Database tables | 51 = 50 application tables + `alembic_version` |
| Alembic | single head `e4f5a6b7c8d9`; 21 files in `alembic/versions`; `alembic check` → **"No new upgrade operations detected"** |
| Frontend | `static/index.html` 627 lines, `static/js/app.js` 3160 lines, `static/css/styles.css` 288 lines; 20 views |
| Module register | 16 entries: 15 counted, 15 working, 1 conditional (MOD-15); 100% of the counted denominator |
| Tests | `python -m pytest -q -ra` → **48 passed, 0 failed/skipped/errors**, 319 third-party warnings, 27.66 s |
| Settings | `APP_ENV=production`, `DEMO_MODE=false`, Telegram login notifications off |
| Git | repository present; 4 commits; 4 modified files uncommitted (the earlier spelling/UI corrections) |

### 1.1 Database schema parity (VERIFIED)

- Tables only in the database: `alembic_version` only. Tables only in the ORM: none.
- Column differences: **0** missing, **0** extra; **0** nullability differences;
  **0** type-class differences.
- Index inventory: 78 secondary indexes, 33 unique constraints, 51 primary keys.
- Row volumes (development dataset, not a load benchmark): users 6, roles 8, products 3,
  invoices 1, payments 1, leads 0, credit/debit notes 0, purchase orders 4, sales orders 2,
  stock movements 6, audit_log 318, hr_attendance 5, hr_payroll_entries 1.

### 1.2 Reports (VERIFIED)

All 25 catalogue reports build against the live database with no exception. GST register and
receivables ageing now return real rows and reconcile against the source invoice:

- GST register: 1 row (INV/2627/000001, taxable 6,250,000.00, CGST 375,000.00,
  SGST 375,000.00, IGST 0.00, total 7,000,000.00) with 6 independent checks, all passing.
- Ageing: four buckets, 0–30 days = 7,000,000.00 (1 invoice), other buckets 0, with 2
  independent checks, both passing.
- 8 reports have at least one independent (source-vs-report) check: stock, sales, invoices,
  receivables, receivables_ageing, payables, gst_register, trial_balance.
- **17 reports still carry only the circular row-count check** (see R-01).

### 1.3 Previously reported defects — current status

| Original item | Status now |
|---|---|
| D-01 GST register empty | Fixed; content verified above |
| D-02 Ageing showed internal keys | Fixed; four buckets verified above |
| D-03 Self-comparing "reconciled" | **Partially fixed** — real for 8 reports, still circular for 17 |
| D-04 Alembic would drop `payments` | Fixed; `alembic/env.py` imports every model module; `alembic check` clean |
| D-05 Dashboard computed from 200-row lists | Fixed; `GET /api/dashboard` aggregates in SQL and returns `null` for forbidden sections |
| D-06 Reports built/paginated in memory | **Open** — see R-02 |
| D-07 No content-level report tests | Fixed; 48 tests, including `test_report_reconciliation.py` (12 tests) |
| D-08 No version control / debris | Fixed; git history exists, debris ignored, no dump in the working tree |
| D-09 Dead `RuntimeError` branch | Fixed; branch removed |
| MOD-09 backup tool missing | Fixed; `backup_restore_test.py` present (not executed in this read-only stage) |

## 2. Remaining defects and gaps (verified)

### R-01 — 17 of 25 reports' "reconciled" flag still proves nothing — MEDIUM

*Where:* `app/services/reports.py::_empty_reconciled` (line 502). When no `source_count` is
passed, the only check compares `len(table["rows"])` with `len(table["rows"])`.

*Affected:* leads, purchases, goods_receipts, suppliers, distributors and all 11 HR reports.

*Impact:* the screen presents "reconciled" as evidence that a report agrees with the
records; for these reports it is a tautology. The brief (§5) requires independent
reconciliation for every report.

### R-02 — Reports materialise every row, then paginate/sort in Python — MEDIUM

*Where:* `app/api/reports.py::get_report` (lines 128–140) calls `reports.build` for the whole
report, then slices and sorts the full row list in memory.

*Impact:* acceptable at the current data volume, but it contradicts the server-side
pagination requirement once reports grow. No N+1 was found in the stock report (single
grouped query), matching the Stage 4 record.

### R-03 — `app/models/__init__.py` does not import every model module — LOW

*Where:* `app/models/__init__.py` imports `core, hr, suppliers, tax, users` but not
`accounts`. Its docstring claims that it registers all tables; importing the package alone
registers **49 of 50** tables (`payments` missing). Alembic is unaffected because
`alembic/env.py` imports `app.models.accounts` explicitly.

*Impact:* latent trap for future code that trusts the package-level guarantee (for example a
metadata-driven safety net). One-line fix; not applied because this stage is read-only.

### R-04 — Stage 3 deliverables do not exist — MEDIUM (documentation)

The brief requires `docs/DATABASE_TABLE_COLUMN_REGISTER.md`,
`docs/FRONTEND_BACKEND_FIELD_MAPPING.md`, `docs/FORMULA_AND_BUSINESS_RULE_REGISTER.md`,
`docs/FORMULA_RECONCILIATION_TESTS.md` and `docs/user-manual/`. None exists. The database
facts needed for the register are verified in §1.1, but the full per-column inventory and
the other registers are not yet written.

### R-05 — Referenced permissions document is missing — LOW

`app/core/rbac.py:1` and `app/core/permissions.py:4` call `docs/permissions-matrix.md` the
single source of truth; the file does not exist.

### R-06 — Original baseline document is materially stale — LOW

`docs/STAGE1_AUDIT_BASELINE.md` records 26 tests, 129 route objects, "not a git
repository", and a missing backup tool. All four are superseded by this document; keep it
as history, do not read it as current.

### R-07 — Install guide version drift — LOW

`INSTALL.txt` requires Python 3.12 or 3.13; the verified runtime is 3.14.7 and the suite
passes on it.

### R-08 — Environment-example drift — LOW

Key names differ between `.env` and `.env.example` (`SENTRY_DSN_PLACEHOLDER` only in
`.env`; `TELEGRAM_NOTIFY_LOGIN` only in the example, which the app defaults to off).
No secret value was read or printed.

## 3. Stage 2 priority list (proposed)

| # | Priority | Item | Files |
|---|---|---|---|
| 1 | Medium | R-01 independent reconciliation checks for the remaining 17 reports | `app/services/reports.py`, `tests/test_report_reconciliation.py` |
| 2 | Medium | R-04 write the four Stage 3 registers and the user manual | `docs/` |
| 3 | Medium | R-02 server-side filtering/sorting/pagination for reports | `app/api/reports.py`, `app/services/reports.py` |
| 4 | Low | R-03 import `accounts` in the model package | `app/models/__init__.py` |
| 5 | Low | R-05 write `docs/permissions-matrix.md` from `permissions.py` and the database roles | `docs/` |
| 6 | Low | R-06/R-07/R-08 documentation corrections | `docs/`, `INSTALL.txt`, `.env.example` |

Items 1 and 4 change application code; 2, 5, 6 are documentation; 3 is a larger change that
should follow regression tests. No high-risk or destructive change is proposed.

## 4. Not verified in this stage (must not be treated as facts)

- Browser/UI interaction; frontend behaviour was verified by reading the files and by the
  API-level tests only.
- Performance or query plans at production data volume; the development dataset is tiny.
- `backup_restore_test.py` execution (it creates and drops a scratch database, so it was
  not run in a read-only stage).
- Concurrency and duplicate-submission behaviour under parallel requests.
- PDF/QR appearance and print verification end to end.
- E-invoice / e-way bill (declared conditional).
- Depth re-verification of password hashing, cookie flags, lockout and forced-password
  change; these passed in the original audit and their tests still pass, but the internals
  were not re-read in this run.

## 5. Commands executed (all read-only)

```
python --version
python -m alembic current / heads / check
python -m pytest -q -ra
python (SQLAlchemy inspector) table/column/nullability/type/index comparison
python (SQLAlchemy) row counts for 14 tables
python (import app.main) route inventory + dependency signature scan
python (import app.models) metadata table count
python (reports.build) all 25 reports; GST and ageing content checks
python (module_register) totals; settings flags (values not printed)
grep/read: main.py, dashboard.py, reports API/service, rbac, models/__init__, env.py,
           conftest.py, backup_restore_test.py, INSTALL.txt, .env key names, docs/
```

No `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `alembic upgrade` or `alembic revision`
was executed against any database.
