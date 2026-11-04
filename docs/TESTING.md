# Running the test suites

Date: 4 November 2026
Branch: `feature/gap-closure`

The suites run against a **separate PostgreSQL database** and never touch the
development or production data. This page covers the one rule that matters
(two runs must never overlap), the commands, and where the evidence goes.

## 1. The test database

`tests/conftest.py` rewrites `DATABASE_URL` to the database named
`herbanova_bcs_test` before any test imports the app, then **drops and recreates
that database at the start of every run** and applies `alembic upgrade head`.
Nothing persists between runs: rows created by one run are gone in the next.

The reset function refuses any database name that does not end in `_test`.

## 2. Runs are serial

Because every run drops and recreates the same database, two suites running at
once corrupt each other. A session-wide OS file lock enforces this:

- lock file: `var/.pytest-suite.lock` (created on first use, left in place;
  its content is the holder's `pid` and database name);
- Windows: `msvcrt.locking(..., LK_NBLCK, 1)` on the first byte;
- POSIX: `fcntl.flock(..., LOCK_EX | LOCK_NB)`;
- the `database` fixture depends on the `suite_lock` fixture, so the lock is
  taken **before** the drop, and released when the session ends.

A second run does not wait: it fails immediately with

```
RuntimeError: another pytest suite holds var/.pytest-suite.lock. The suite
drops and recreates herbanova_bcs_test, so runs must be serial: wait for the
other run to finish (or stop it) and try again.
```

The kernel releases the lock if the holding process dies, so a leftover lock
file is harmless — only a live process can block a run. To find it, inspect the
`pid=` written in the file. Do not delete the lock file to "fix" contention;
stop the other run.

The lock covers `pytest` only. Do not run anything else against
`herbanova_bcs_test` while a suite is running — stop a probe server such as
`var/probe/serve_test.py` first, or point it at its own scratch database. The
migration rehearsal in §6 uses a different scratch database,
`herbanova_nav_migration_scratch_test`, and drops it itself.

## 3. Python suite

```bash
python -m pytest                                     # whole suite
python -m pytest tests/test_navigation_seed_tool.py  # one module
python -m pytest --junitxml=var/reports/run.xml      # evidence
```

`pytest.ini` sets `testpaths = tests`, deliberately. Several probe servers live
under `var/` and end in `_test.py`; importing them would start `uvicorn.run()`
and block collection instead of running tests.

The suite needs the Node binary: `tests/test_workspace_model.py` runs the Node
workspace suite from pytest and fails if no tests actually pass.

## 4. Node suite

```bash
node --test tests/js/workspace.test.cjs
```

The file under test is `static/js/workspace.js`, loaded by the browser
unchanged. `tests/js/nav_parity.cjs` is a helper invoked by the parity report
(§5), not a standalone suite.

## 5. Navigation catalogue parity

Run from the **repository root** (imports, Node helpers and a relative `--out`
path are resolved against it):

```bash
python scripts/navigation_parity_report.py
python scripts/navigation_parity_report.py --out var/reports/wp4-parity.json
```

It compares the catalogue, the seed literal inside migration 0031, and the
browser menu. Exit code 0 when every check passes, 1 otherwise. Read-only: no
database is opened.

## 6. Migration rehearsal

```bash
python scripts/verify_navigation_migration.py        # print the plan
python scripts/verify_navigation_migration.py --run  # rehearse 0028 → 0031
```

`--run` creates `herbanova_nav_migration_scratch_test`, upgrades, downgrades,
re-upgrades, probes the seeded rows and drops the database. The real
`alembic/versions` tree is not modified; the migration source is copied into a
temporary directory. Evidence lands in
`var/reports/wp4a-migration-rehearsal.json`.

## 7. Seed generator

```bash
python scripts/generate_navigation_seed.py --check
```

`--check` reads the active migration (or its `.py.draft` before activation) and
reports whether the seed block is current. `--write` edits the draft only; it
**refuses to rewrite an active migration** with exit code 2, because Alembic
does not checksum applied revisions and a silent rewrite would go unnoticed. A
seed change after activation belongs in a new migration. Covered by
`tests/test_navigation_seed_tool.py`.

## 8. Browser and UI probes

Browser verification is not part of `pytest`. The walk scripts under `var/`
drive a hidden Chrome against a running stack (backend, frontend and a Chrome
debug port), so they need a live server and are run by hand after the suites.
They are outside `tests/` and outside the commit. The commands, ports and
screenshots for each batch are recorded in
[VERIFICATION_REPORT.md](VERIFICATION_REPORT.md).

## 9. Evidence

Test logs, JUnit XML, screenshots and rehearsal JSON go under `var/`, which is
not tracked. The authoritative counts for a given batch are recorded in
[VERIFICATION_REPORT.md](VERIFICATION_REPORT.md); do not quote a number here
without a dated run to point at.

## 10. Related reading

- [RUNNING_SERVERS.md](RUNNING_SERVERS.md) — backend/frontend split and ports.
- [DB_RESET.md](DB_RESET.md) — what the guarded reset does to a real database.
- [WP4_RELEASE_READINESS.md](WP4_RELEASE_READINESS.md) — the release audit and
  its test evidence.
