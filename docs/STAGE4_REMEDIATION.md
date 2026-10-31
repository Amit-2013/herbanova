# Stage 4 remediation record

Verified on PostgreSQL 16 (sandbox), Python 3.12: `pytest` 48 passed (twice in a row),
`alembic check` clean, single head `e4f5a6b7c8d9`, `backup_restore_test.py` passed.
Not verified: a real browser session, concurrency, a load test, PDF/QR appearance,
and your production data volume.

| Audit item | Outcome |
|---|---|
| D-01 GST register empty | Fixed; content tests compare the report with `/api/accounts/gst-register` |
| D-02 Ageing shows internal keys | Fixed; one row per bucket, totals cross-checked |
| D-03 Self-comparing "reconciled" | Fixed for GST, ageing, payables, trial balance, invoice and sales-order registers; each check compares with an independent query |
| D-04 Alembic would drop `payments` | Fixed: every model module imported in `alembic/env.py`; index names aligned with migrations; `alembic check` is clean |
| D-05 Dashboard computed in the browser from 200-row lists | Fixed: `GET /api/dashboard` counts in SQL; a failed load is shown as an error, never as zeros; sections the user may not see are `null` |
| D-06 Reports in memory / stock N+1 | Stock report already uses one grouped query; measured 0.25 s for 20,000 products. Reports still build fully in memory and paginate in the API; acceptable at this scale, revisit if a single report passes ~100k rows |
| D-07 No content-level tests | 22 new tests (reports, dashboard, restore, module register) |
| D-08 No version control / patch debris | Git history, `.gitattributes`, debris in `archive/` (git-ignored) |
| D-09 Dead RuntimeError branch | Already removed |
| MOD-09 tool missing | `backup_restore_test.py` written and tested, including a failing case |

Other defects found and fixed while verifying:
- SQLAlchemy 2 rejected `db.scalar(query)` in three report cross-checks (invoice register and sales-order report crashed).
- `tests/conftest.py` used `User` without importing it.
- Test helper raised orders as admin, so approvals failed once the credit limit was used.
- `Mapped[date | None]` inside `ODRequest` was evaluated against the column named `date` (SQLAlchemy deprecation, future error).
- Two route functions in `app/api/hr.py` shared the name `request_correction`; one also ran a dead query.
- `module_register.py` referred to a test and a document that did not exist.

Open decisions for the owner:
- `herbanova_before_reset.dump` is still inside the first git commit. Purge history before sharing the repo.
- Rotate the Telegram bot token and `APP_SECRET` if the original zip was shared.
