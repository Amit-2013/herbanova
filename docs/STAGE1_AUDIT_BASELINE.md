# Herbanova — Stage 1 Read-Only Audit Baseline

**Date:** 31 October 2026
**Scope:** Read-only inspection of the Herbanova project. No application code and no
database data were modified during this stage. The only file created is this document.

**How to read this document:** every item marked **VERIFIED** was reproduced by a command
run against the real source tree or the live development database. Items marked
**UNVERIFIED** were not tested and must not be treated as facts.

---

## 1. Technology stack (VERIFIED)

| Layer | Technology |
|---|---|
| Language | Python 3.14 (Windows, Git Bash shell) |
| Web framework | FastAPI + Uvicorn, Pydantic v2, pydantic-settings |
| ORM / database | SQLAlchemy 2.x over **PostgreSQL 17.11** (`localhost:5432/herbanova_bcs_dev`) |
| Migrations | Alembic — current revision `e4f5a6b7c8d9` (head), one head, 20 revisions in `alembic/versions` |
| Auth | JWT in an `HttpOnly` `session` cookie (HS256), Argon2id password hashing, per-IP login rate limit (slowapi), per-account lockout, `token_version` session revocation |
| Frontend | Single-page vanilla JS application: `static/index.html` (627 lines), `static/js/app.js` (3 149 lines), `static/css/styles.css` (288 lines), served at `/ui` |
| Reporting | CSV / XLSX (openpyxl) / PDF (reportlab) exports, audit-logged |
| Monitoring | Optional Sentry (only enabled when `SENTRY_DSN` is set) |
| Tests | pytest + httpx TestClient, against a **separate** `herbanova_bcs_test` database |

Entry points: `app/main.py` (FastAPI app, 25 routers, 129 API routes + health),
`seed.py`, `seed_admin_secondary.py`, `alembic/`.

`.env` (values not reproduced here): `APP_ENV=production`, `DEMO_MODE=false`,
`CORS_ORIGINS=http://localhost:5173`, Telegram credentials present but
`telegram_notify_login` off by default.

## 2. Architecture and module inventory (VERIFIED)

**API routers** (`app/api/`): auth, users, roles, employees, hr, db_reset, admin, audit,
modules, accounts, products, suppliers, purchase_orders, inventory, distributors, tax,
sales_orders, invoices, credit_notes, debit_notes, printing, approvals, leads, reports.

**Services** (`app/services/`): ledger, reports, exports, reports_pdf, invoice, notes,
sales, inventory, order_tax, tax, tax_ids, discounts, numbering, hr, hr_approvals,
payroll, salary_slip, accounts, lockout, audit, qr, words, document_pdf, telegram.

**Models** (`app/models/`) — 50 tables in 6 modules:

| Model file | Tables |
|---|---|
| `core.py` | 22 — users, products, warehouses, batches, stock_movements, purchase_orders(+lines), audit_log, distributors, sales_orders(+lines), approval_requests, leads(+activities), invoices(+lines), credit_notes(+lines), debit_notes(+lines), document_sequences, print_logs |
| `hr.py` | 19 — hr_branches, hr_work_locations, hr_shifts, hr_holidays, hr_departments, hr_attendance(+corrections), hr_leave_types/balances/applications, hr_od_requests, hr_approval_workflows, hr_salary_components/structures(+lines), hr_payroll_periods/entries(+lines)/corrections |
| `suppliers.py` | suppliers, goods_receipts(+lines) |
| `tax.py` | company_profile, tax_rates, discount_slabs |
| `users.py` | roles, employees |
| `accounts.py` | payments |

**Frontend views** (hash routes): `#/dash` (Overview), leads, lost, followups,
customers, sales, billing, purchasing, products, inventory, suppliers, distributors,
approvals, accounts, reports, hr, settings, users, audit, tax. The sidebar nav in
`static/index.html:47-63` shows: Overview, Leads, Lost leads, Today's follow-ups,
Customers, Sales orders, Billing, Purchases, Products, Inventory, Suppliers,
Distributors, Approvals, Accounting & Finance, Reports, HR Management,
Settings & Administration (Billing/Suppliers/Accounting/HR/Settings are permission-gated
and hidden by default).

**Self-declared module register** (`app/core/module_register.py`, 16 modules): MOD-01 …
MOD-16, all marked *working* except MOD-15 (e-invoice / e-way bill) marked *conditional*.
This register is what the Overview screen displays as "N of M modules working".

## 3. Test baseline (VERIFIED — recorded before any change)

Command: `python -m pytest -q -ra`

```
26 passed, 317 warnings in 13.32s   (exit code 0)
```

- 0 failed, 0 skipped, 0 errors.
- Test files: `test_smoke` (1), `test_approvals` (3), `test_hr` (6), `test_products` (4),
  `test_purchase_orders` (4), `test_reports` (8) — 26 in total.
- `tests/conftest.py` **drops and recreates** the `herbanova_bcs_test` database on every
  session and runs `alembic upgrade head` there. The guard refuses any database name not
  ending in `_test`. Development data is never touched by the test run.
- Warnings are third-party deprecations only (slowapi/starlette/anyio on Python 3.14).

**Coverage assessment (VERIFIED by reading the tests):** the suite exercises permissions,
the credit-limit and post-billing admin rules, HSN validation, PO unit-cost remarks, HR
leave/OD/payroll flows, report building/exporting and report permission filters. It does
**not** assert report *content* (row values) for GST or ageing, and there is no test that
reconciles a report against the source transactions.

## 4. Database audit (VERIFIED)

- **51 tables** in the live database = 50 application tables + `alembic_version`.
- **Model ↔ database comparison:** tables only in DB: `alembic_version` only.
  Tables only in models: none. **Column differences: 0.** Types and nullability of every
  column match the ORM definitions when all six model modules are imported.
- **Alembic state:** `alembic current` → `e4f5a6b7c8d9 (head)`; `alembic heads` → one head.
- **Index coverage:** 129 indexes across 51 tables. Key business indexes verified present:
  `ix_invoices_invoice_date`, `uq_invoice_number_fy`, `ix_sales_orders_status_created`,
  `ix_purchase_orders_status_created`, `ix_stock_movements_batch_created`,
  `uq_movement_idempotency`,  `uq_hr_attendance_employee_date` plus
  `ix_hr_attendance_date` / `ix_hr_attendance_employee`, `uq_hr_payroll_entry` (one payroll entry per employee
  per period), `uq_hr_payroll_period`, `uq_approval_pending` (one pending approval per
  record), `ix_leads_status_followup`, `ix_products_hsn`, `ix_tax_rates_hsn_from`,
  `ix_payments_kind` / `ix_payments_paid_on`.
- **Row volumes (development database, small):** audit_log 313, hr_salary_components 11,
  roles 8, users 6, purchase_order_lines 5, hr_attendance 5, products 3, invoices 1,
  payments 1, leads 0, credit_notes 0. This database is a development/seed dataset —
  **it is not a large-data benchmark**; performance claims at scale are UNVERIFIED.

### 4.1 Migration safety finding

`python -m alembic check` **FAILS** (exit ≠ 0). Alembic autogenerate detects operations
that would be destructive, most importantly:

- `remove_table payments` — because `alembic/env.py` imports only `app.models.core` and
  `app.models.hr`, the `payments` model in `app/models/accounts.py` is never registered on
  `Base.metadata` during migration runs.
- ~15 `remove_index` operations for indexes that exist in the database but are created by
  migration files rather than declared on the model (e.g. `ix_payments_kind`,
  `ix_payments_paid_on`, `ix_approval_status_type`, `ix_products_hsn`,
  `ix_leads_status_followup`, `ix_sales_orders_status_created`), plus index *renames*
  (`ix_hr_attendance_employee` → `..._employee_id`) and one nullability difference
  (`hr_od_requests.end_date`).

**Business impact:** running `alembic revision --autogenerate` in this state would produce
a migration that **drops the payments table** (every receipt and payment record) and
several indexes. This is a latent data-loss risk, not an active fault — normal
`alembic upgrade head` is unaffected.

## 5. Security and permissions baseline (VERIFIED)

- **129 API routes. Every route except the two inherently public ones carries an
  authentication/permission dependency** (verified by parsing every route handler
  signature). `POST /api/auth/login` is public by design and `POST /api/auth/logout` only
clears the cookie; `POST /api/auth/change-password` requires any authenticated session.
  Two handlers (`GET /api/hr/attendance`, `GET /api/reports/{key}`) enforce permissions
  inside the body rather than in the signature; both were read and confirmed to check
  role permissions before returning data.
- Permissions resolve from the database (`users.role_id → roles.permissions`),  falling back to the frozen baseline sets in `app/core/permissions.py` (42 permission keys,
  4 baseline roles: admin, sales, inventory, viewer). A permission edit takes effect on the
  next request.
- **Admin-only rules** (requirements 1 and 2 of the original specification) are enforced
  by `require_admin()` in `app/core/rbac.py`, which requires *both* the permission and the
  literal `admin` role name, so a custom role cannot buy the right. Verified endpoints:
  `PATCH /api/invoices/{id}/amend` and `PATCH /api/invoices/{id}/movement` (post-billing)
  and the credit-limit decision path. Tests: `test_approvals.py::test_credit_limit_approval_is_admin_only`,
  `::test_admin_cannot_decide_their_own_credit_request`, `::test_post_billing_edit_is_admin_only`.
- **Separation of duties:** `app/services/hr_approvals.py` refuses self-decision of any HR
  request and refuses payroll approval by the person who prepared it.
- **Session security:** cookie is `HttpOnly`, `SameSite=Lax`, `Secure` when
  `APP_ENV != local`; JWT expiry 60 minutes; `token_version` bump revokes all older
  sessions on password change/reset/deactivation; forced password change blocks every
  route except `/api/auth/me`, `/logout`, `/change-password`.
- **Login hardening:** 20/min per IP, per-user lockout after repeated failures,
  case-insensitive username matching, 12–128 character password policy (3 character
  classes, not the username), Argon2id.
- **Database reset** (`POST /api/db/reset`): requires `db:reset` permission **and**
  `DEMO_MODE=true` **and** the admin's separate secondary password. `.env` has
  `DEMO_MODE=false`, so the endpoint is currently inert. It preserves users, roles and
  employees.
- **No secret exposure found:** `password_hash`, `app_secret` and session tokens never
  appear in API response builders or in `static/js/app.js`.

## 6. Verified defects (reproduced against live data)

### D-01 — The GST Outward Register report is always empty — **CRITICAL**

*What I found:* `GET /api/reports/gst_register` returns a valid envelope whose table has
**0 rows and 0 columns**, even though the database contains issued invoice
`INV/2627/000001` with taxable ₹6,250,000.00, CGST ₹375,000.00, SGST ₹375,000.00 and
a grand total of ₹7,000,000.00.

*Where it is:* `app/services/reports.py`, `build()` branch `if key == "gst_register"`
(around line 790) does:

```python
result = ledger.gst_register(db, date_from, date_to)
rows = result.get("rows", result.get("items", []))
```

but `app/services/ledger.py::gst_register()` returns
`{"from", "to", "b2b", "credit_notes", "debit_notes", "totals", "input_register", "note"}`
— there is no `"rows"` or `"items"` key, so `rows` is always `[]`.

*Why it matters:* the GST report screen shows an empty register while the tax data
exists. Because `reconciled` is computed from a self-comparison (see D-03), the report
still claims "reconciled: true", so nothing signals the problem.

*Evidence:* `ledger.gst_register(db)` returns `b2b` with 1 row and correct totals;
`reports.build(db, "gst_register", ...)` returns 0 rows.

### D-02 — The Receivables Ageing report shows meaningless rows — **HIGH**

*What I found:* `GET /api/reports/receivables_ageing` returns 4 rows:

```
ageing_bucket='as_of'    amount=0.0
ageing_bucket='buckets'  amount=0.0
ageing_bucket='total'    amount=7000000.00
ageing_bucket='count'    amount=...
```

*Where it is:* `app/services/reports.py`, `if key == "receivables_ageing"` flattens the
wrapper dict returned by `ledger.ageing_rows()` (`{"as_of", "buckets", "total", "count"}`)
into `{"ageing_bucket": key, "amount": value}` pairs. The real buckets are inside the
`"buckets"` list and are never rendered.

*Why it matters:* the ageing buckets are the whole point of the report. The correct data
exists — `ledger.ageing_rows(db)` returns `0-30 days: 7,000,000.00 (1 invoice)`,
`31-60: 0`, `61-90: 0`, `90+: 0` — and the **Accounting screen** shows it correctly
through `GET /api/accounts/ageing`. The Reports screen does not. Two screens therefore
disagree about the same number.

### D-03 — "reconciled: true" is a self-comparison for most reports — **MEDIUM**

*What I found:* most report branches return via `_empty_reconciled()`, whose only check is
`_check("row_count", "Report row count", len(rows), "Table row count", len(table["rows"]))`
— the same list compared with itself. It is always true, including when the report is
wrongly empty (D-01).

*Why it matters:* the reconciliation flag is presented to the user as evidence that the
report agrees with the underlying records. For most reports it proves nothing. Real
reconciliation checks (report total vs. source document total) exist for only a few
reports.

### D-04 — Alembic autogenerate would drop `payments` — **HIGH (latent)**

See §4.1. Cause: `alembic/env.py` does not import `app.models.accounts`.

### D-05 — Overview dashboard figures are computed in the browser from capped lists — **MEDIUM**

*What I found:* `renderDash()` in `static/js/app.js` (line 358) derives every KPI
(units on hand, batches in stock, active products, POs awaiting goods, orders ready to
dispatch, approvals waiting, overdue follow-ups) by filtering `state.*` arrays that were
loaded by list endpoints with `page_size=200` (see the `/api/...?page=1&page_size=200`
calls in `app.js`).

*Why it matters:* as soon as any list exceeds 200 records the dashboard silently
understates the figure, with no indication that it is partial. This is the starting point
for the dashboard work: KPIs must come from server-side aggregations.

### D-06 — Report building is in memory with in-request pagination, plus N+1 queries — **MEDIUM**

*What I found:*
- `app/api/reports.py::get_report` builds the whole report (`reports.build`) and then
  slices rows in Python for the requested page. Filtering, sorting and pagination all
  happen after the full result set has been materialised.
- `reports.build` for the `stock` report runs one `SELECT` per product for its batches
  (N+1). HR reports that fall outside the pre-fetched employee map issue one
  `db.get(Employee, ...)` per row.

*Why it matters:* acceptable at the current data volumes (tens of rows), but it is the
opposite of the "server-side pagination, no full-table loads" requirement once the
database grows.

### D-07 — Thin test suite with no content-level report assertions — **MEDIUM**

26 tests cover permissions and core workflows well, but `test_every_report_builds_and_exports_in_every_format`
only asserts HTTP 200 and a non-empty payload, so D-01 and D-02 pass the suite. There is
no reconciliation test that compares a report's totals with the source documents.

### D-08 — No version control and heavy patch debris — **MEDIUM (operational risk)**

- The project is **not a git repository** (`git status` → "not a git repository"), so
  there is no history, diff or rollback for any change.
- `app/services/` contains **10 backup copies** of `reports.py` (two of them 2 and 8 bytes
  long), plus `_apply_corrected_report_patch.py` at the project root,
  `backup_reports_fix_20261030_*` directories, `reports_diagnostic.txt` (126 KB),
  `reports_service_inspection.txt` and `herbanova_before_reset.dump` (a 136 KB database
  dump).
- This pattern — scripted rewrites of `reports.py` with timestamped backups — is the
  likely origin of D-01/D-02 and makes future reviews harder.

### D-09 — Dead branch that raises an exception — **LOW**

`app/services/reports.py` contains a later `if key == "hr_approvals": raise RuntimeError(...)`
after an earlier branch for the same key has already returned. It is unreachable today,
but it is a trap for anyone editing the dispatch chain.

## 7. Verified-correct behaviour (checked and passing)

| Area | Evidence |
|---|---|
| Invoice header ↔ line reconciliation | `sum(invoice_lines.taxable_value) = invoices.taxable_value = 6,250,000.00`; line CGST/SGST/IGST/cess sums equal header totals; `taxable + tax = grand_total` (7,000,000.00) |
| Trial balance | Debits 22,000,000.00 = credits 22,000,000.00, `balanced=True`; built from the same documents, so it cross-checks sales, purchases, receivables, payables and output tax |
| Stock ledger | For every batch, `batches.on_hand = sum(stock_movements.qty_delta)` (3/3 batches match) |
| Sales orders | `sales_orders.total = sum(sales_order_lines.line_total)` for both orders |
| Reports catalogue | 25 reports, all `build()` without error; permission-filtered catalogue; 14 categories; 11 HR reports accept employee/department/branch filters and reject unsupported filters with 422 |
| Exports | CSV (BOM), XLSX and PDF build for every report; exports require `report:export`, are audited, and carry an explicit "No records for this period." row when empty |
| Auth/permissions | 129/129 routes gated; admin-only credit limit and post-billing rules tested and passing |
| DB reset safety | Disabled by `DEMO_MODE=false`, triple-gated, preserves users/roles/employees |

## 8. Not verified in this stage (UNVERIFIED)

- No browser/UI interaction was performed; frontend behaviour was verified by reading
  `static/js/app.js` and by API calls only.
- Performance at large data volumes (the development database holds at most a few
  hundred rows per table); query plans under load were not measured.
- PDF visual output, QR/scannable code rendering, print verification flow end to end.
- Backup restore procedure (`herbanova_before_reset.dump`, the documented
  `backup_restore_test.py` referenced by `app/api/db_reset.py` **does not exist in this
  tree** — see below).
- E-invoice / e-way bill (declared conditional in the module register).
- Concurrency behaviour (row locks on approval decisions, duplicate submission under
  parallel requests) — the unique indexes exist, but no concurrency test was run.

**Additional observation (VERIFIED):** `app/api/db_reset.py` documents the recovery tool as
``python backup_restore_test.py`` and that file is **not present** in the project. The
backup/restore module claimed as "working" (MOD-09) cannot be run from this tree.

## 9. Priority list for Stage 2 (proposed, not yet actioned)

| # | Priority | Item | Files |
|---|---|---|---|
| 1 | Critical | D-01 GST register always empty | `app/services/reports.py` |
| 2 | High | D-02 Ageing report shows wrapper keys instead of buckets | `app/services/reports.py` |
| 3 | High | D-04 `alembic/env.py` must import all model modules | `alembic/env.py` |
| 4 | Medium | D-03 Replace self-comparison "reconciled" checks with real source-vs-report checks | `app/services/reports.py` |
| 5 | Medium | D-07 Add content-level and reconciliation tests for GST/ageing/trial balance | `tests/test_reports.py` |
| 6 | Medium | D-05 Move dashboard KPIs to server-side aggregations | new endpoint + `static/js/app.js` |
| 7 | Medium | D-06 Server-side pagination/filtering for reports; remove the stock N+1 | `app/api/reports.py`, `app/services/reports.py` |
| 8 | Medium | D-08 Put the project under version control; quarantine backup debris | repository root |
| 9 | Low | D-09 Remove the dead `hr_approvals` branch | `app/services/reports.py` |

## 10. Commands executed in this stage (all read-only)

```
ls / find                                    # structure
python -m pytest -q -ra                      # 26 passed, 13.32s
python -m alembic current / heads / check    # head e4f5a6b7c8d9; check FAILS
python (SQLAlchemy) schema↔model compare     # 0 column differences
python (SQLAlchemy) index inventory          # 129 indexes
python route/permission signature scan       # 129 routes, all gated
python reports.build() over all 25 keys      # 25 ok, 0 failed
python ledger.gst_register / ageing_rows / trial_balance   # root causes isolated
python invoice/stock/SO reconciliation queries             # all invariants hold
grep/read: app/main.py, rbac, permissions, security, auth, db_reset, printing,
           reports API/service, ledger, hr, hr_approvals, payroll, module_register,
           static/index.html, static/js/app.js, tests/*
```

No `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `alembic upgrade` or `alembic revision`
command was run against any database.
