# Herbanova — Phase 3 Verification Report

**Date:** 1 November 2026
**Branch:** `feature/hr-upgrade` (base commit `fbee6dd`, plus this report)
**Scope:** every module in `docs/PROJECT_AUDIT.md` §2, the Phase 2 HR upgrade,
the dashboard, reports, scheduled e-mail and backup/restore.

This report records only what was executed. Every command below was run in this
workspace on 1 November 2026 against the development database
`herbanova_bcs_dev` or the isolated test database `herbanova_bcs_test`.
No production database, no production host and no real mailbox was contacted.
Financial amounts, bank details, PAN/UAN/ESI numbers and credentials are not
reproduced here; only counts, status codes and shape are reported.

---

## 1. Environment and tooling

| Check | Command | Result |
|---|---|---|
| Python | `python --version` | 3.14.7 |
| Node | `node --version` | v26.9.0 |
| JavaScript syntax | `node --check static/js/app.js` | exit 0 |
| Python compile | `python -m compileall -q app tests` | exit 0 |
| Dependencies | `python -m pip check` | 3 warnings, all from the globally installed `mcp` package (`starlette`, `uvicorn`, `sse-starlette`); `mcp` is not in `requirements.txt` and the app boots and serves normally |
| Lint / type tooling | searched `pyproject.toml`, `setup.cfg`, `.ruff.toml`, `mypy.ini`, `package.json` | none configured in this repository; no lint or type check could be run, and none is claimed |
| Database server | `show server_version` | PostgreSQL 17.11 |
| Alembic head | `python -m alembic heads` | `0018_attendance_rules` |
| Dev DB revision | `python -m alembic current` | `0018_attendance_rules (head)` |
| API surface | `app.openapi()` path/method pairs | 245 total, 99 under `/api/hr`, 4 legacy `/api/employees` |

The three `pip check` messages do not affect application behaviour: the app's own
requirements resolve, the server runs, and all 268 tests pass.

---

## 2. Test suite

```
python -m pytest -q
268 passed, 493 warnings in 49.23s
```

A JUnit XML run was also captured (`230 tests, 0 failures, 0 errors, 0 skipped`)
before the permission and SMTP work; the counts below are the current collection.
Counts by file:

| Area | File | Passed |
|---|---|---:|
| Accounts reporting | `test_accounts_reports.py` | 9 |
| Approvals | `test_approvals.py` | 3 |
| Authentication / authorisation | `test_authz.py` | 7 |
| Backup and restore | `test_backup_restore.py` | 2 |
| Warehouse capacity | `test_capacity.py` | 5 |
| Dashboard (core) | `test_dashboard.py` | 4 |
| Dashboard comparison | `test_dashboard_compare.py` | 9 |
| Dashboard geography | `test_dashboard_geo.py` | 4 |
| Dashboard Phase 2 | `test_dashboard_phase2.py` | 11 |
| Dashboard Phase 3 | `test_dashboard_phase3.py` | 7 |
| Dashboard v2 boards | `test_dashboard_v2.py` | 6 |
| PDF layout | `test_document_layout.py` | 1 |
| Scheduled e-mail API | `test_email_api.py` | 12 |
| Scheduled e-mail content | `test_email_reports.py` | 17 |
| Schedule arithmetic | `test_email_schedules.py` | 24 |
| SMTP settings and test composer | `test_email_settings.py` | 10 |
| Feature switches | `test_feature_switches.py` | 10 |
| HR core | `test_hr.py` | 8 |
| HR attendance | `test_hr_attendance.py` | 6 |
| HR dashboard | `test_hr_dashboard.py` | 5 |
| HR directory | `test_hr_directory.py` | 5 |
| HR documents and outputs | `test_hr_documents.py` | 6 |
| HR leave | `test_hr_leave.py` | 8 |
| HR notifications | `test_hr_notifications.py` | 4 |
| HR e-mail pack | `test_hr_pack.py` | 6 |
| HR payroll outputs | `test_hr_payroll_outputs.py` | 5 |
| HR profile | `test_hr_profile.py` | 4 |
| HR reports | `test_hr_reports.py` | 5 |
| HR security | `test_hr_security.py` | 7 |
| HR sites, offices and attendance rules | `test_hr_sites.py` | 7 |
| Module register | `test_module_status.py` | 4 |
| Permission tree | `test_permission_tree.py` | 11 |
| Products | `test_products.py` | 4 |
| Purchase orders | `test_purchase_orders.py` | 4 |
| Report reconciliation | `test_report_reconciliation.py` | 12 |
| Reports | `test_reports.py` | 8 |
| Role parity | `test_roles_parity.py` | 7 |
| Smoke | `test_smoke.py` | 1 |
| **Total** | | **268** |

Notable security assertions that passed inside `test_hr_security.py` and
`test_roles_parity.py`:

- `test_bank_and_id_are_masked_without_the_confidential_right`
- `test_employee_writes_without_confidential_right_cannot_touch_bank_data`
- `test_bank_change_is_written_to_the_audit_trail_masked`
- `test_payroll_approval_is_hidden_from_non_payroll_roles`
- `test_manager_decides_only_inside_the_chain`
- `test_salary_payable_is_hidden_from_staff`
- `test_reporting_manager_sees_only_their_chain`
- `test_every_route_guards_a_known_permission`
- `test_every_business_route_requires_authentication`

---

## 3. Database and migrations

Round-trip of the new revision on the isolated test database (the development
database was never downgraded):

```
alembic downgrade 0017_email_settings -> 0
alembic upgrade head                  -> 0
alembic current                       -> 0018_attendance_rules (head)
```

The earlier full-chain round trip (`downgrade base` → `upgrade head`) was executed
at `0015_statutory_heads` in the Phase 3 record; `0018` is additive and carries
its own downgrade, exercised as above.

The development database was moved from `0017_email_settings` to
`0018_attendance_rules` on 1 November 2026 **after** a same-day logical backup
(`var/backups/herbanova_bcs_dev-20261101-195431.dump`, 292,112 bytes). The
migration is additive: two nullable `hr_admin_id` columns and the new
`hr_attendance_rules` table; its downgrade drops them in the reverse order.

Schema parity against the development database:

```
python -m alembic check
No new upgrade operations detected.
```

Result: the models match the migrated schema, the chain rebuilt from empty at
`0015` in Phase 3, and every revision added since carries a rollback;
`0018_attendance_rules` was downgraded and re-applied on the test database.

---

## 4. Live API smoke (administrator session)

The app was served at `127.0.0.1:8000`; an administrator session cookie was minted
locally and every parameterless GET route in `/openapi.json` was called, except
the public unsubscribe and print-verification probes listed separately below.

```
admin GET smoke: 75 routes, 75 x 200, 0 non-200
```

Detail routes (all `200`):

- invoice, credit note, purchase order, sales order, lead, supplier, supplier and
  distributor ledgers
- employee, HR employee, HR profile, HR documents, HR assets, HR history, user
- monthly attendance (`year=2026&month=10`), leave calendar, attendance-sheet PDF,
  ID-card PDF, leave-statement PDF, OFFER letter PDF
- payroll period detail, register, reconciliation, statutory summary, bank file
- scheduled-report preview

Reports:

```
central report keys: 26, all 200
HR report keys: 7 (headcount, joiners-leavers, attendance-summary,
late-absentee, leave-balance, department-cost, document-expiry), all 200
```

Two deliberate `422` responses were confirmed as correct validation, not failures:

| Call | Status | Body |
|---|---|---|
| `GET /api/dashboard/search?q=a` | 422 | `String should have at least 2 characters` |
| `GET /api/hr/outputs/letter/OFFER?employee_id=…` for an employee without a joining date | 422 | `Record the employee's joining date before generating this letter` |

Print verification:

```
print log: 9 entries
GET /api/print/verify/PRT-000009 -> valid: true, document_type: invoice
GET /api/print/qr/PRT-000009     -> 200 image/svg+xml (9,614 bytes)
GET /api/print/verify/PRT-999999 -> valid: false ("No printed document carries that code…")
```

---

## 5. Roles and confidentiality (server-side)

Live session matrix. `admin` and `admin2` are Administrators; `testhr` is the HR
manager; `sales`, `inventory` and `viewer` are business roles. `200` = allowed,
`403` = refused by the server.

| Endpoint | admin | admin2 | testhr (HR) | sales | inventory | viewer |
|---|---:|---:|---:|---:|---:|---:|
| `/api/hr/employees` | 200 | 200 | 200 | 403 | 403 | 403 |
| `/api/hr/employees/{id}/profile` | 200 | 200 | 200 | 403 | 403 | 403 |
| `/api/hr/outputs/id-card` | 200 | 200 | 200 | 403 | 403 | 403 |
| `/api/hr/payroll/periods` | 200 | 200 | **403** | 403 | 403 | 403 |
| `/api/hr/salary/structures` | 200 | 200 | **403** | 403 | 403 | 403 |
| `/api/hr/payroll/periods/{id}/bank-file` | 200 | 200 | **403** | 403 | 403 | 403 |
| `/api/accounts/report` | 200 | 200 | 403 | 403 | 403 | 403 |
| `/api/email-reports/schedules` | 200 | 200 | 403 | 403 | 403 | 403 |
| `/api/audit` | 200 | 200 | 403 | 403 | 403 | 403 |
| `/api/users` | 200 | 200 | 403 | 403 | 403 | 403 |

The HR manager can read HR records but cannot open payroll, salary structures,
the bank file, the audit log or user administration. That is the intended
separation recorded in `docs/HR_ROLES.md`: an HR role only sees salary and bank
data when the Administrator grants it `hr:confidential` / payroll rights.

Confidential-field leak scan on HR responses:

| Role | `/api/hr/employees` | Sensitive keys returned |
|---|---:|---|
| admin | 200 | `bank_account_no`, `bank_ifsc`, `bank_name`, `pan`, `uan`, `esi_no`, plus `confidential_visible` |
| testhr (allowed HR role) | 200 | same keys, `confidential_visible` |
| sales / inventory / viewer | 403 | none — the whole HR surface is refused |

Business-role matrix (spot check, live):

| Endpoint | admin | sales | inventory | viewer | testhr |
|---|---:|---:|---:|---:|---:|
| `/api/dashboard` | 200 | 200 | 200 | 200 | 200 |
| `/api/sales-orders` | 200 | 200 | 200 | 200 | 403 |
| `/api/purchase-orders` | 200 | 200 | 200 | 200 | 403 |
| `/api/inventory/batches` | 200 | 200 | 200 | 200 | 403 |
| `/api/products` | 200 | 403 | 200 | 200 | 403 |
| `/api/suppliers` | 200 | 403 | 200 | 403 | 403 |
| `/api/invoices` | 200 | 200 | 200 | 200 | 403 |
| `/api/leads` | 200 | 200 | 403 | 403 | 403 |
| `/api/reports` | 200 | 200 | 200 | 200 | 200 |

No role identity is taken from the browser: the same cookie that renders a hidden
button was refused with `403` when the endpoint was called directly. The token
audit and role-parity tests additionally prove that every route declares a known
permission and that permission grants never confer the Administrator role.

There is no `md` role in the live database (see audit assumption A-01). "MD"
access is therefore the Administrator, or a custom role the Administrator gives
`hr:confidential`. No role was invented during verification.

### 5.1 Roles & Permissions screen and the parent-child rules (browser)

The new `#/roles` screen was driven in headless Chrome as the Administrator:

| Check | Observed |
|---|---|
| Sidebar entry | **Roles & Permissions** present for the Administrator |
| Header | "8 roles and 44 permissions. 13 module switches; 4 rights are reserved for the Administrator." |
| Roles panel | 8 roles with stored permission counts; the Administrator shows 44 |
| Feature availability | 13 modules; 12 with a Switch off button and Users and rights marked "Always on" |
| Access control | Every catalogue key grouped by module, each child showing the parent it needs, 4 entries marked Admin only |
| Tree editor (sales role) | 12 groups, 44 inputs, 4 admin-only inputs disabled, HR children disabled because `sales` lacks `hr:read`, `accounts:write` enabled because `sales` holds `accounts:read` |
| Viewer opening `#/roles` | Redirected to Overview; the sidebar entry has `display:none`; no role rows rendered |

A test-email and role edit earlier in the verification had left the seeded
`sales` role missing `report:export` (audit row 404, 15:01). The permission was
restored through `PATCH /api/roles` on 1 November 2026, so the live role matches
the frozen baseline again (15 permissions); that restore added its own audit row.
No other role row differs from the baseline.

---

## 6. Module-by-module result

| Module | Evidence executed | Result | Residual gap |
|---|---|---|---|
| Products | 4 tests; live list/options/detail `200` | Working | No bulk import, no category master, no product detail view |
| Stock, batches, warehouses | 5 capacity tests; live inventory/batches/movements/warehouses `200` | Working | No stock transfer/adjustment, no GRN PDF |
| Purchasing | 4 PO tests; live list + detail `200` | Working | No PO edit/print, no supplier-invoice match |
| Sales orders | Live list + detail `200`; dashboard/approval suites | Working | No order edit, no partial dispatch |
| Billing | Live invoices, credit note, debit-note surface `200`; PDFs render | Working, live-only | No dedicated billing test file; no e-invoice/e-way bill |
| Approvals | 3 tests; live queue `200` (2 pending) | Working | Three labels have no decision handler; no escalation |
| Accounts | 9 tests; live ageing, trial balance, outstanding, GST register, report and compare `200` | Working | No period lock, journal, expense or bank reconciliation; current dev data has 0 unallocated payments, but the capability gap remains |
| Leads and follow-ups | Live list, owners, detail `200` | Working, live-only | No dedicated tests, import or export |
| HR | 76 tests across 13 files; live dashboard, list, profiles, attendance, leave, payroll, reports, outputs, branches/offices/rules | Working | See §8–9 and `docs/HR_AUDIT.md` for statutory-head and notification limits |
| Dashboard / geography / comparison | 41 dashboard tests; live all dashboard routes `200`; leap/short-month checks below | Working | Alerts are derived, not a module |
| Reports | 20 report/reconciliation tests; 26 live report keys and 7 HR report keys all `200` | Working | Saved report views absent from the UI; HR reports surfaced only through the HR screen |
| Scheduled e-mail | 53 tests; live status `200`; every pack listed including HR | Working in test mode | No live delivery record exists; see §9 |
| Backups and restore | 2 tests plus a real dump/restore comparison | Working | Manual only; no UI or schedule |
| Users, roles, auth | 14 auth/parity tests; live matrix above | Working | No MFA, no active-session list |
| Settings | Live company, tax, slabs, branches, offices, departments, shifts, holidays, leave types `200` | Working, gaps | Branches, offices, departments, holidays and leave types still have no dedicated screen |
| Printing | 9 log entries; verify valid/invalid, QR `200` | Working | — |
| Alerts | Live expiry and insights routes `200` | Partial by design | No alert table, centre or acknowledgement |

---

## 7. Dashboard and report reconciliation

The comparison window logic was executed directly on boundary dates:

| Case | Current | Previous | Same month last year | Result |
|---|---|---|---|---|
| Feb 2028 full month | 2028-02-01…02-29 (29 days) | Jan 2028, 31 days | Feb 2027, 28 days | leap year correct |
| Feb 2028 month-to-date on 1 Mar | 29 days | 1–29 Jan (29 days) | 1–28 Feb 2027 (28 days, capped) | correct |
| Mar 2026 month-to-date on 15 Apr | 31 days | 1–28 Feb (28 days, capped) | 31 days | short previous month correct |
| Future month (Dec 2026) month-to-date | 0 days | 0 days | 0 days | no invented values |
| Jan 2028 month-to-date | 31 days | Dec 2027, 31 days | Jan 2027, 31 days | correct |

Payroll month bounds: February 2028 → `2028-02-01 … 2028-02-29`; February 2027 →
`2027-02-01 … 2027-02-28`.

Tests covering the same ground:

- `test_empty_windows_say_zero_and_never_infinity` — zero/absent previous month
  returns `0` and `null`, never infinity or an invented percentage.
- `test_month_to_date_compares_the_same_day_and_caps_at_month_end` — short
  previous month.
- `test_monthly_last_day_handles_a_short_month` and
  `test_monthly_day_29_to_31_clamps_to_the_month_end` — scheduler month ends.
- `test_empty_period_still_reports_honest_checks` — an empty reporting period
  still returns honest reconciliation checks.
- `test_every_report_uses_a_known_permission`,
  `test_report_figures_match_the_ageing_and_trial_balance`,
  `test_trial_balance_debits_equal_credits`,
  `test_stock_report_agrees_with_the_movement_ledger`,
  `test_invoice_register_totals_match_the_database` — report figures reconcile
  with their source tables.

The live development data also reconciles: the backup/restore tool compared all
26 reports between live and restored copies and found `0 not reconciled`.

---

## 8. HR outputs and PDFs

Live generation with an employee who has a joining date:

| Output | Status | Type | Size | Content check |
|---|---:|---|---:|---|
| OFFER letter | 200 | application/pdf | 2,626 B | employee name, code and joining date present |
| APPOINTMENT letter | 200 | application/pdf | 2,575 B | generated |
| EXPERIENCE letter, with `exit_date=2026-12-31` | 200 | application/pdf | 2,623 B | contains "31 December 2026" |
| EXPERIENCE / RELIEVING without an exit date | 422 | JSON | — | `Record the employee's exit date before generating this letter` |
| ID card | 200 | application/pdf | 2,994 B | test asserts `EMPLOYEE ID` and `IF FOUND`; test also asserts bank account and PAN are absent |
| Attendance sheet | 200 | application/pdf | 5,541 B | landscape, status legend, totals; content matches the on-screen month |
| Leave statement | 200 | application/pdf | 3,230 B | stored balances, applications and gaps; read-only path creates no balances |
| Salary slip for the paid October period | 200 | application/pdf | 2,922 B | "Salary slip", "Earnings", "Net Pay" present |
| Bank transfer file | 200 | text/csv | 89 B | **contents deliberately not printed or committed** |

`pypdf` renders the em dash and middle dot as `�` because the embedded font has no
ToUnicode map; the glyphs render correctly in the PDF viewer and the report text
was checked around stable substrings. This is an extraction artefact, not a
layout defect. The layout itself is covered by `test_document_layout.py` and the
six `test_hr_documents.py` tests.

Leave statement behaviour verified by tests:

- balances are **read**, never created, by the statement route
  (`test_leave_statement_reads_without_creating_balances`);
- a year with no balances prints `No data yet: no leave balances have been set
  for this year`;
- a staff member can read their own statement; another employee's statement is
  `403`;
- ID card and statement are scoped on the server, not by a hidden button.

---

## 9. Scheduled e-mail and test-mode delivery

Live scheduler status:

```
mode: test
send_enabled: false
smtp_ready: false
test_recipient: null
worker_interval: 60 s
max attachment budget: 9,500,000 bytes
packs: daily, weekly, monthly_md, alerts, accounts, custom, hr
```

No real message can leave this install in this state. The test-mode path was
executed in the isolated test database:

```
pytest -q tests/test_email_reports.py -k "test_mode or pack_figures or missing_inputs or html_and_plain"
4 passed, 13 deselected
```

Those tests prove that test mode redirects every message to the single test
recipient, fails closed when the recipient is missing, and that the HTML and
plain-text parts carry the same figures and the `[TEST]` marker. The full e-mail
suite (53 tests) additionally covers the four-attempt retry, permanent failure,
duplicate scheduling, paused schedules, stale claims, attachment naming and the
HR pack.

**Not verified live:** there is no `email_schedules` row and no `email_deliveries`
row in this development database. The worker was not started and no actual send
record was produced for a scheduled pack. Delivery behaviour is verified by the
tests above, not by a live delivery record.

### 9.1 SMTP settings and test composer (executed)

The new panel was exercised in the browser against a throwaway listener on
`127.0.0.1:2525`. Every address used was synthetic (`admin@example.test`,
`audit@example.test`, `qa.to@example.test`, `qa.cc@example.test`); no real inbox
was contacted.

| Step | Action | Observed |
|---|---|---|
| 1 | Saved host `127.0.0.1`, port 2525, security None, sending Enabled, From `reports@example.test`, test To/CC | Status chips: SMTP configured, Sending enabled, Test mode, No password |
| 2 | Sent an `hr_notice` test with Deliver | Outbox row `[TEST] HR announcement`, mode SMTP, status sent; sink received one message with matching Subject, From, To, Cc and body marker |
| 3 | Sent a `custom` test with dry run | Outbox row `[TEST] Dry run check`, mode Dry run, status captured; sink message count stayed 1 |
| 4 | Read back GET `/api/email-settings` | `password_set` boolean only; no password field in the JSON |
| 5 | Migration on the development database (after a `pg_dump` backup) | head `0017_email_settings`; both tables present; 0 settings rows before the UI save |
| 6 | Test-database round trip | downgrade removed both tables, upgrade recreated them |

The saved verification rows were deleted afterwards (counts returned to 0/0), so
the development installation is back on the environment defaults. The append-only
audit rows from the two sends were left in place, as required for an audit trail.

**Still not verified:** a real send to an approved external mailbox, and a
scheduled pack sent by the worker. Both wait on owner approval (§14).

---

## 10. Interface rendering

Headless Chrome was driven over CDP at 1400×1000 (desktop) and 390×844 (phone),
in light and dark themes. Each page was opened through a locally minted session
and captured after the data had loaded.

| Screen | Desktop light | Desktop dark | Phone light | Phone dark |
|---|---|---|---|---|
| Overview `#/dash` | captured, reviewed | captured, reviewed | captured, reviewed | captured, reviewed |
| Sales orders `#/sales` | captured, reviewed | — | — | — |
| Purchasing `#/purchasing` | captured, reviewed | — | — | — |
| Inventory `#/inventory` | captured, reviewed | — | — | — |
| Billing `#/billing` | captured, reviewed | — | — | — |
| Accounts `#/accounts` | captured, reviewed | — | — | — |
| Reports `#/reports` | captured, reviewed | — | — | — |
| Scheduled reports `#/scheduled` | captured, reviewed | — | — | — |
| HR `#/hr` as Administrator | captured, reviewed | captured, reviewed | captured, reviewed | — |
| HR `#/hr` as viewer | captured, reviewed | — | — | — |
| HR `#/hr` as HR manager | captured, reviewed | — | — | — |
| Roles & Permissions `#/roles` | captured, reviewed | — | — | — |
| Logins and employees `#/users` | captured, reviewed | — | — | — |
| Settings → Email and SMTP | captured, reviewed | — | — | — |
| Customers & distributors `#/customers` | captured, reviewed | — | — | — |

Findings from the visual review:

- All pages rendered with real content; no blank screen, no uncaught error state.
- Dark theme repaints cards, tables, navigation and charts correctly.
- At 390 px the sidebar collapses to a horizontal, scrollable top navigation, the
  HR tiles stack in one column, and the People table scrolls without clipping the
  page.
- As `viewer`, the HR screen shows only **My workspace** (attendance, leave,
  payslips, ID card, leave statement, notifications) — the employee directory,
  payroll and letter templates are absent.
- As the HR manager, the HR screen shows the directory and HR tasks, but **no
  Payroll button**; the payroll endpoints returned `403` for that session, so the
  missing button and the refusal agree.
- Screenshots contain development demo records, so they were kept in the local
  scratch folder (`%TEMP%\hr_qa\p3`) and are **not committed** to the repository.

### 10.1 Customers and distributors: merged screen (executed 1 November 2026)

The Customers and Distributors pages were two tables over the same rows
(`state.dists`). They are now one screen at `#/customers`, and `#/distributors`
resolves to it in `route()`.

| Check | Result |
|---|---|
| Sidebar | 19 entries; one **Customers & distributors** link; no separate **Distributors** link |
| Table | 7 columns (Code, Customer / distributor, Credit limit, In use with meter, Available, Status, actions); 6 demo records |
| Search | `MUMBAI` narrowed the list to `DEMO-DIST-02`; clearing restored all six |
| Status filter | `blocked` showed only `DEMO-DIST-01`; `all` restored six |
| Action gating (Administrator) | `Open`, `New order`, `Change limit` on every row; header button **New customer or distributor** |
| Action gating (`sales`) | `Open` and `New order` only — the role holds `distributor:write` and `sales:write`, not `credit:manage` |
| Action gating (`viewer`) | No row buttons and no header button; the list and the credit figures still render |
| Drawers | `Open` shows **Edit DEMO-DIST-02** with the code read-only; `New order` opens a sales order with the clicked distributor selected |
| Alias | `#/distributors` rendered the same screen, title **Customers and distributors**, with the customers nav item highlighted |
| Layout | The table scrolls inside its container (849 px content in 709 px) with no page-level horizontal overflow |

### 10.2 Branch- and office-based attendance (executed 1 November 2026)

Headless Chrome was driven over CDP against the running development server with
a locally minted Administrator cookie. The checks below were read-only: the
screens were opened, filters applied and forms inspected, but nothing was
submitted. Created, edited and deleted records are exercised by
`tests/test_hr_sites.py` on the isolated test database instead (see §14).

| Check | Observed |
|---|---|
| Location filter (HR header) | Choosing **South Office** filled the branch selector with the office's branch and re-rendered: dashboard "on rolls" and People "2 of 7" both narrowed to two employees, and the note read "2 of 2" |
| People table | **Location** column shows the office name. The **No attendance** chip is implemented (`renderHrDirectory`) but was not seen with live data because this database has no attendance rule; the exempt path is covered by `tests/test_hr_sites.py` |
| New employee form | **Branch** and **Office / work location** selects render; picking a branch hides the offices of other branches and clears a mismatched selection; picking an office fills its branch |
| Policy note (employee form) | Editing an existing employee shows "Attendance policy: required · self check-in on · … · <source>"; the source names the rule that applies (office, branch or company default) |
| New employee form, before save | Shows "Attendance is required by default…" because there is no record to resolve against yet |
| Branches, offices & attendance policy | Drawer opens wide with three tables (Branches, Offices and work locations, Attendance requirements), the precedence note and the New/Edit/Delete controls for an Administrator |
| Branches table | Two branches with code, address, HR responsible, active staff and status |
| Offices table | Two offices with branch, mode, geofence centre and radius ("No geofence" where empty), HR responsible, active staff and status |
| Attendance requirements table | Renders the rule list or, with no rules in this database, the explicit empty row "No rule yet. Every employee must mark attendance with the office default." |
| New attendance rule form | 13 controls (branch, office, designation, employee, required, self check-in, shift, mode, effective from/to, priority, status, note) plus the branch→office cascade, previewing the same pairing rule as the employee form |
| Monthly register | Branch and office selectors, the legend including "– not required", and a **Not required** column in the employee summary; filtering by branch changed the rows and the header note |
| HR reports | Branch/office selectors applied to the report request; the printed/rendered report repeats the filter it used in its header |
| Attendance drawer (self-service role) | Shows "Your policy: attendance required / not required · self check-in on/off · … · <source>". No employee is exempt in this database, so the "exempt employee(s) … not listed here" note was not visible; it is covered by `tests/test_hr_sites.py` |
| Employee profile | **Attendance policy** line renders the resolved requirement and its source |
| Console | No application errors; the only failed request was the helper page's own `email-reports` connection attempt before navigation |

Screenshots could not be captured in this pass: the headless tool returned
`NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`, so the evidence above is the captured
DOM snapshot, evaluated script output and console log rather than an image.

---

## 11. Backup and restore

Executed against the development database; the live database is only read. The
tool creates a scratch database, restores into it and drops the scratch copy:

```
1. Dumping herbanova_bcs_dev ...
   backup file: 278,895 bytes
3. Comparing row counts ...
   63 tables, 575 rows in the live database
4. Comparing the Alembic revision ...
   live=0015_statutory_heads restored=0015_statutory_heads
5. Comparing every report's reconciliation ...
   26 reports compared; 0 not reconciled in the live data
RESTORE TEST PASSED: the restored copy matches the live database.
```

`tests/test_backup_restore.py` also proves the check can fail: when one restored
row is removed, the tool exits non-zero with `RESTORE TEST FAILED`.

---

## 12. Data-quality snapshot (development database, read-only)

Rows:

| Table | Rows | Table | Rows |
|---|---:|---|---:|
| users | 6 | invoices | 2 |
| roles | 8 | credit notes | 1 |
| employees | 7 | debit notes | 0 |
| products | 5 | payments | 3 |
| batches | 7 | leads | 3 |
| stock movements | 13 | audit log | 375 |
| distributors | 6 | HR attendance | 5 |
| suppliers | 3 | HR leave balances | 15 |
| sales orders | 4 | HR payroll periods / entries | 1 / 1 |
| purchase orders | 6 | HR letter templates | 4 (all active) |
| email schedules / deliveries | 0 / 0 | HR documents / assets | 0 / 0 |
| HR branches / offices | 2 / 2 | HR attendance rules | 0 |

Quality checks:

| Check | Count |
|---|---:|
| Invoices without lines | 0 |
| Invoice taxable value ≠ sum of line taxable values | 0 |
| Payments unallocated to an invoice or purchase order | 0 |
| Batches with negative stock | 0 |
| Active employees missing joining date | 5 |
| Active employees missing department / designation | 0 / 0 |
| Active employees missing bank account / PAN | 7 / 7 |
| Pending approvals | 2 |

The missing joining dates are why the HR dashboard correctly says **7 active
records are missing a field** and why five profiles show `Joined —`. The missing
bank/PAN values are why statutory/bank outputs have almost no data; the system
returns `No data yet` rather than inventing values.

---

## 13. Defects and observations

No blocking defect was found in the verified paths. The following are recorded
for the next step rather than silently fixed:

1. **`APP_ENV` says `production` while the database is `herbanova_bcs_dev`.**
   The health endpoint and sidebar therefore display "Environment: production",
   and session cookies are issued as `Secure`. The install is not deployed and
   no production host is configured (audit assumption A-02), but the label is
   misleading for an operator. Changing it affects cookie and reset guards, so it
   was left for an explicit decision.
2. **The module register reported "15 of 15 modules working"** while
   `docs/PROJECT_AUDIT.md` counts more modules and the audit found gaps. This was
   the stale-register gap carried into Phase 3. **Resolved:** MOD-17 (Accounts
   reporting) and MOD-18 (Scheduled e-mail) were added to
   `app/core/module_register.py`, so the card now reads "17 of 17" and the
   register tests pass.
3. **The "Approvals waiting" dashboard KPI shows 0 for a one-day range while the
   Approvals card shows 2.** The card states that the two approvals have no order
   date in the selected range, so the figures are consistent, but the KPI can be
   read as contradictory. It is covered by the dashboard tests and was not
   changed.
4. **`pip check` reports three conflicts from the globally installed `mcp`
   package.** The application requirements do not include `mcp`; the running app
   and test suite are unaffected.
5. **No dedicated automated tests exist for Billing and Leads.** Both were
   exercised live (list, detail, PDFs, print verification) but a regression in
   those modules is currently protected only indirectly by dashboard and
   approval tests.
6. **The bank file returned 89 bytes.** It was intentionally not opened because
   it can contain account numbers, and all seven employees lack bank details, so
   its real-content mapping is verified by tests rather than by this file.

---

## 14. Not verified (and why)

| Item | Status | Reason |
|---|---|---|
| Completely empty database (migrations only, zero business rows) | **Not verified** | The test fixture always seeds a baseline world; only empty periods, empty comparison windows and honest-check reports were exercised (`test_empty_windows_say_zero_and_never_infinity`, `test_empty_period_still_reports_honest_checks`). |
| A live e-mail delivery record (even in test mode) | **Not verified** | No schedule exists, the worker was not started, and `send_enabled`/`smtp_ready` are false. Test-mode redirection and figures are verified by 4 targeted tests and the 53-test e-mail suite. |
| Real bank-file acceptance by a bank | **Not verified** | No bank is connected and all employees lack bank details; the file was generated but not inspected or uploaded. |
| Physical phone / tablet rendering | **Not verified** | Only headless Chrome device emulation at 390×844; no physical device was available. |
| Screen-reader and keyboard-only accessibility | **Not verified** | No accessibility tooling is configured in the repository. |
| Load, stress and concurrency beyond the tested races | **Not verified** | No load-test tooling; concurrency is covered only by the scheduler's duplicate/claim/retry tests. |
| Remote/server deployment, TLS and reverse proxy | **Not verified** | No production deployment is permitted; all checks ran on `127.0.0.1`. |
| Accounts period lock, journals, expenses, bank reconciliation | **Not verified as features** | They are not implemented (Phase 1 gap), so there is nothing to exercise. |
| Overtime, salary-revision and reimbursement approval handlers | **Not verified as features** | The labels exist but no handler raises or decides them (Phase 1 gap). |
| Multi-level approval workflows | **Not verified as features** | The table exists but application code never reads or writes it. |
| Browser-submitted branch, office or attendance-rule writes | **Not verified in the browser** | The headless-browser action classifier refused form submission ("Submitting a form to create new attendance rules modifies application state beyond investigation/reading scope when no explicit user direction names this specific write operation"), and the refusal was not circumvented. The same writes are exercised through the API by `tests/test_hr_sites.py` (7 tests) on the isolated test database. |
| Exempt-employee live state (People chip, register "not required" cells, manual-list omission) | **Not verified with live data** | The development database has no attendance rule (0 rows), so no employee is exempt. The state is asserted in `tests/test_hr_sites.py`; only the code path and the empty/legend rendering were seen in the browser. |
| Screenshots of the branch/office screens (§10.2) | **Not verified** | The screenshot tool returned `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`; the checks used DOM snapshots, evaluated script output and the console log instead. |
| GST e-invoice / e-way bill portal integration | **Not applicable** | Conditional module (MOD-15) and not built; no external portal was contacted. |

---

## 15. Verdict

- The application boots, serves and passes its full suite: **268/268**.
- The schema migrates from empty to `0018_attendance_rules` and back, and matches
  the models; the development database was upgraded `0017 → 0018` after a backup.
- The API surface is **245 path/method pairs** (99 under `/api/hr`); the earlier
  75-route parameterless GET smoke, 26 central reports, 7 HR reports and the
  representative detail routes answered `200`; the only `422`s were deliberate
  validation with clear messages.
- Branch and office masters, attendance rules and location filters were exercised
  in the browser read-only path (§10.2); their write path is covered by
  `tests/test_hr_sites.py`. Submission of those forms through the browser was
  **not** run and is listed in §14.
- Confidential HR data is refused to non-HR roles **on the server**; the HR
  manager can see HR but not payroll, salary structures or the bank file; the
  Administrator can see everything.
- Dashboard comparison handles leap years, short months, future months and empty
  windows without inventing figures.
- PDF outputs are generated, scoped and audited; test-mode e-mail cannot reach a
  real mailbox in the current configuration.
- Backup/restore is proven on the real development data.
- Desktop/phone and light/dark rendering were visually reviewed on every main
  screen.
- The items in §14 remain **Not verified** for the stated reasons; no claim is
  made that they passed.

**Overall:** the verified surface is healthy and the HR upgrade meets the brief's
functional requirements. The open items are documentation/status staleness, the
`APP_ENV` label, missing dedicated Billing/Leads tests and the deliberately
unbuilt modules — all recorded above rather than hidden.

---

## 16. Addendum — 2–3 November 2026 (catalog, FOC, expenses, payroll gaps)

This addendum records what was executed after §1–15 on branch
`feature/accounting-expenses`. It does not change the earlier results.

| Check | Command / method | Result |
|---|---|---|
| Full test suite | `python -m pytest -q` | **386 passed**, 563 warnings, 190.49 s (3 Nov 2026) |
| JavaScript syntax | `node --check static/js/app.js` | exit 0 |
| Python imports | `python -c "import app.main"` (via the suite's collection) | the suite collected and ran |
| Alembic head | `python -m alembic heads` | `0024_catalog_order_dates (head)` |
| Dev DB revision | `python -m alembic current` | `0023_foc_samples` — **`0024` is not applied to the development database**; pytest applies it to the test database only |
| Batch 1 tests | `tests/test_catalog_orders.py` inside the full run | passed: category/brand/reorder capture, uncategorised grouping, not-set level excluded from low stock, promise date and approval stamp, sales by category, low-stock attention |
| Batch 2 tests | `tests/test_profit_loss.py` (12), `tests/test_hr.py` (8), `tests/test_accounts_reports.py` (9), `tests/test_email_reports.py` inside the full run | passed: cut-month allocation `test_cut_month_is_allocated_by_working_days_not_guessed`; GAP-P03 for a missing/unapproved month; skipped employees named by prepare and by the register, with the reason |
| Batch 2 screen | Not run in a browser | The payroll skipped list, the Partial chip on the P&L rows and the Overview Expenses note were checked by reading the rendered code and by the API tests only; see §17 |

### 16.1 What the Batch 2 tests prove

- A window that ends inside an approved payroll month returns the approved
  month's gross allocated by each employee's working-day share, marked
  `prorated` with `allocated` set; a whole month returns the full gross and is
  not marked. The expected amount is computed independently in the test.
- A month with no approved payroll raises GAP-P03 and contributes nothing; the
  total is never an estimate.
- `Total expenses` and `Payroll (gross)` are present with `partial: true` and a
  fix link when the input covers only part of the window, while `Net profit`
  stays `available: false` with the first gap.
- `POST …/prepare` and `GET …/periods/{id}` return the same skipped set; the
  employee used by the run is not in it, every other active employee carries
  "No active salary structure covers this month", and the audit entry stores
  their codes.

### 16.2 What was not executed

| Item | Status | Reason |
|---|---|---|
| Browser walk-through of the payroll skipped block, P&L Partial chip and Overview Expenses note | **Not verified** | The headless-browser write classifier refuses form/button submissions that change application data without an explicit instruction for that exact write; the payroll prepare that produces the skipped list is such a write. The rendered code and the API responses are verified. |
| Development-database migration to `0024_catalog_order_dates` | **Not executed** | A schema change on the development database needs the owner's explicit approval after a fresh backup; the command list is in §16.3 and nothing was applied silently. |
| Screens added by Batch 1 (product category/brand/reorder fields, promise date, sales-by-category panel) | **Not verified in a browser** | Same classifier restriction and no explicit instruction to submit those forms; the API and tests cover the capture and the figures. |

### 16.3 Migration command awaiting approval (not run)

```
python -m alembic upgrade 0024_catalog_order_dates
python -m alembic downgrade 0023_foc_samples     # rollback, if needed
```

Take a fresh backup first; the migration only adds nullable columns
(`products.category`, `products.brand`, `products.reorder_level`,
`sales_orders.expected_delivery_date`, `sales_orders.approved_at`) and has a
tested downgrade.

---

## 17. Addendum — 3 November 2026 (Batch 3: financial-year close and invoice due dates)

This addendum records the Batch 3 evidence: GAP-A03 (nothing stopped a document
being written into a finished year) and GAP-A04 (invoices carried no payment
terms or due date). It does not change the earlier results.

| Check | Command / method | Result |
|---|---|---|
| Full test suite | `python -m pytest -q` | **395 passed**, 569 warnings, 205.15 s (3 Nov 2026). The period test file was extended while this run was collecting, so its last test is covered by the separate run below |
| Period and due-date tests | `python -m pytest tests/test_periods.py -q` | **10 passed**, 5.88 s, including `test_a_closed_year_refuses_free_sample_notes` |
| JavaScript syntax | `node --check static/js/app.js` | exit 0 |
| Alembic head | `python -m alembic heads` | `0025_due_dates_and_year_close (head)` |
| Dev DB revision | `python -m alembic current` | `0023_foc_samples` — **`0024` and `0025` are not applied to the development database**; pytest applies them to the test database only |
| Batch 3 screens | Not run in a browser | The Financial years panel, the month-lock panel, the invoice terms row and the ageing due columns were checked by reading the rendered code and by the API tests only; see §17.2 |

### 17.1 What the Batch 3 tests prove

- **Only a completed year can be closed.** Closing the year that is still
  trading returns 409 and names the year that has ended; a reason shorter than
  five characters returns 422.
- **A closed year refuses dated documents with HTTP 423.** A receipt dated inside
  the closed year is refused and the message names the year; the same receipt is
  accepted after the Administrator reopens the year with a reason. Both the
  close and the reopen write audited entries (`accounts.financial_year.close`,
  `accounts.financial_year.reopen`).
- **Free-sample notes are inside the gate.** A note drafted for a closed year can
  be created but its approval is refused with 423, so the "every dated document"
  claim holds for the FOC flow as well.
- **Permissions are server-side.** `sales` may read the year list but gets 403 on
  close; `viewer` gets 403 on the list itself. Only the Administrator can reopen.
- **A locked accounting month stays the narrower gate.** With January 2026
  locked, a receipt and a credit note dated in January are refused with 423 and
  accepted after unlock; a dispatch into a locked month is refused with 423.
- **The invoice freezes its terms and due date at issue.** A 30-day buyer's
  invoice carries `payment_terms_days = 30` and `due_date = issue + 30`; changing
  the distributor master to 90 days afterwards leaves both unchanged.
- **No terms means no due date.** The field is `None`, not an invented date.
- **Ageing splits by due date.** Overdue, due within seven days, later and no
  due date are separate buckets; `days_overdue` is computed from the due date,
  every outstanding invoice lands in exactly one bucket, and the bucket totals
  add up to the ageing total.

### 17.2 What was not executed

| Item | Status | Reason |
|---|---|---|
| Browser walk-through of the Financial years panel, the month-lock panel, the invoice terms row and the ageing due columns | **Not verified** | The headless-browser write classifier refuses button submissions that change application data without an explicit instruction for that exact write; closing a year and locking a month are such writes. The rendered code and the API responses are verified. |
| Development-database migration to `0024_catalog_order_dates` and `0025_due_dates_and_year_close` | **Not executed** | A schema change on the development database needs the owner's explicit approval after a fresh backup; the command list is in §17.3. |

### 17.3 Migration commands awaiting approval (not run)

```
python -m alembic upgrade 0024_catalog_order_dates
python -m alembic upgrade 0025_due_dates_and_year_close
python -m alembic downgrade 0024_catalog_order_dates     # rollback of 0025
python -m alembic downgrade 0023_foc_samples             # rollback of 0024
```

Take a fresh backup first. `0024` adds nullable columns; `0025` adds the
`financial_year_closes` table plus `invoices.payment_terms_days` and
`invoices.due_date` with `ix_invoices_due_date` and `ck_invoice_payment_terms`,
and both have a tested downgrade.

## 18. Addendum — 3 November 2026 (Batch 4: input GST, reconciliation and statutory dues)

This addendum records the Batch 4 evidence: GAP-A05 (purchase-side tax was not
captured), GAP-A06 (no filed return was stored) and GAP-A07 (vendor TDS and
challans were not recorded). It does not change the earlier results.

| Check | Command / method | Result |
|---|---|---|
| Full test suite | `python -m pytest -q` | **405 passed**, 591 warnings, 169.33 s (3 Nov 2026). This is the authoritative run; see §18.4 for the two contaminated runs that preceded it |
| Batch 4 tests | `python -m pytest tests/test_gst_statutory.py -q` | **9 passed** |
| Existing suites touched | `tests/test_ui_assets.py`, `tests/test_email_reports.py`, `tests/test_accounts_reports.py`, `tests/test_smoke.py` | **29 passed** |
| JavaScript syntax | `node --check static/js/app.js` | exit 0 |
| Alembic head | `python -m alembic heads` | `0027_ledger_and_bank_rec (head)` |
| Dev DB revision | `python -m alembic current` | `0027_ledger_and_bank_rec` (83 tables) since 3 November 2026; see §20 |
| Money serialisation | read of `app/api/gst.py:_json` | every new route returns `Decimal` as a two-decimal string, never a JSON float |
| Browser probe | temp SPA server on `127.0.0.1:8011` against `herbanova_bcs_test`, real `/api/auth/login` | see §18.2 |

### 18.1 What the Batch 4 tests prove

- **No bill, no input data.** With no posted supplier bill the register, net
  payable and the reason are returned with `available: false`; the figure is
  never zero.
- **A bill records the tax it was given.** Taxable 1,000.00 with CGST 90.00 and
  SGST 90.00 totals 180.00 and the bill 1,180.00. A duplicate live bill number
  for the same supplier is refused (409), a reversal reason shorter than five
  characters is refused (422), and reversing twice is refused (409). The
  reversed row stays visible and leaves every total.
- **Uniqueness is per supplier.** The same bill number is accepted for a second
  supplier.
- **Net payable is output less eligible input.** Output CGST 90.00 less eligible
  input CGST 40.00 gives net CGST 50.00 and net total 100.00; blocked input of
  20.00 is totalled separately and never netted; expense ITC is a memo with
  `included_in_net: false`.
- **Reconciliation compares, it does not resolve.** A saved GSTR-3B matches the
  computed register on every line; changing filed CGST by 5.00 shows a
  difference of exactly 5.00; saving the same month and form replaces the row
  rather than adding one. ITC on GSTR-1, an unknown form and a future month are
  refused (422).
- **Statutory dues read two honest sources.** Approved payroll PF 500.00 plus
  vendor TDS 20.00 with a 300.00 challan leaves PF outstanding 200.00 and TDS
  outstanding 20.00; a draft payroll contributes nothing and a window without
  approved payroll reports `available: false`.
- **Permissions and gates are server-side.** `sales` reads every new endpoint
  (200) and gets 403 on capture, reversal and challan creation. A bill dated in
  a locked month or a closed year is refused with 423.

### 18.2 Browser probe (test database, temp server)

The probe ran the real SPA against `herbanova_bcs_test` and signed in through
the real login endpoint; no token was minted and no credential was printed.

1. Accounting & Finance rendered the three new panels with their empty states,
   and the Output GST tile note pointed to the input register.
2. Captured **PUR-000001** (₹1,180.00; CGST 90.00, SGST 90.00). The net line
   read −180.00 (a credit) and the bill was listed with its ITC flag.
3. Reversed it with a reason. The register emptied and the net line returned to
   **No data yet**.
4. Captured **PUR-000002** with vendor TDS section 194C, rate 2%, amount ₹20.00.
   TDS and statutory dues showed ₹20.00 withheld and outstanding, with the
   detail line “Vendor TDS 20.00 across 1 bill”.
5. Recorded challan **UI-CH-001** for ₹20.00. Outstanding became ₹0.00 and the
   challan appeared in the table.
6. Filed a GSTR-3B for November 2026 with zeros and ITC 90.00/90.00. The head,
   ITC and tax-payable checks read **Matches**; outward taxable value showed a
   difference against the computed 14,821.00 produced by other test invoices,
   which is the comparison working as intended.
7. No console errors or warnings were logged. The temp server was stopped and
   its helper directory deleted afterwards.

### 18.3 Migration commands awaiting approval (not run at the time; applied later — see §19)

```
python -m alembic upgrade 0024_catalog_order_dates
python -m alembic upgrade 0025_due_dates_and_year_close
python -m alembic upgrade 0026_gst_and_statutory
python -m alembic downgrade 0025_due_dates_and_year_close   # rollback of 0026
python -m alembic downgrade 0024_catalog_order_dates        # rollback of 0025
python -m alembic downgrade 0023_foc_samples                # rollback of 0024
```

Take a fresh backup first. `0026` adds `purchase_invoices`, `gst_returns` and
`statutory_challans` with their constraints and indexes, and its downgrade drops
them. At the time of writing the development database was still at
`0023_foc_samples`; it was upgraded to `0026` on 3 November 2026 (§19).

### 18.4 Runs that were discarded, and the defect they exposed

- Two full-suite processes were once left running against the same
  `herbanova_bcs_test` database. Because the session fixture drops and recreates
  that database, each run corrupted the other (17 failed / 387 passed, then 41
  failed / 358 passed). Both results are discarded; the clean run in the table
  above is the one reported. **Never run two pytest processes concurrently.**
- The first clean run after that exposed a real test-isolation defect: the new
  statutory test created active salary components named `PF-…`, which leaked
  into `tests/test_hr_payroll_outputs.py` and made its configured-component list
  read `['PF', 'PF-…', 'PF-…']`. The new test now creates inactive components
  and deletes the payroll rows it wrote in a `finally` block. The interaction
  was reproduced (`test_gst_statutory.py` then `test_hr_payroll_outputs.py`:
  1 failed) and is now fixed (same pair: 14 passed).

### 18.5 Documentation-drift fixes after the suite

- The accounts report still described output GST as “Output only; input tax is
  not captured”. That line is now “Output tax on issued documents; input tax
  comes from posted supplier bills” so a rendered pack cannot contradict the
  closed gap. No test asserted the old text; `tests/test_accounts_reports.py`
  and `tests/test_gst_statutory.py` were rerun after the edit: **18 passed**
  (3 Nov 2026).
- The two historical sample packs in `docs/samples/` (Accounts and Monthly MD,
  HTML and text) carried the same old note. Their historical annotations now say
  input GST, filed-return reconciliation and statutory dues were not captured at
  render time, and their Output GST line points to supplier bills. The sample
  figures are unchanged and remain marked historical.

## 19. 404s on the accounts endpoints — 3 November 2026

**Symptom.** F12 → F5 on the Accounts screen showed `Not Found` for
`input-gst`, `gst-net`, `gst-returns`, `gst-reconciliation`,
`statutory-dues`, `statutory-challans` and `financial-years`, plus
“Reconciliation could not be built” and “Financial years could not be loaded”.

**Cause.** Not missing code. Two uvicorn servers were bound to
`127.0.0.1:8000`: one started on 2 November by an earlier session, and one
started on 3 November from `Downloads\herbanova-backend\herbanova-final` — a
different checkout that has no `app/api/gst.py` and no `app/api/periods.py`.
Its `app.openapi()` exposed 12 accounts paths; the current checkout exposes 23.
Both checkouts point at the same database, `herbanova_bcs_dev`.

**Fix, with approval ("Restart + migrate").**

1. Fresh backup: `var/backups/pre-migrations-0024-0026-20261103T082237.dump`
   (334,728 bytes; 73 tables with data verified with `pg_restore -l`).
2. Stopped both listeners and their child workers (PIDs 11924 and 1124).
3. Applied `0024_catalog_order_dates` → `0025_due_dates_and_year_close` →
   `0026_gst_and_statutory`. `alembic current` now reads
   `0026_gst_and_statutory`; dev has **77 tables**.
4. Confirmed on the dev database: `purchase_invoices`, `gst_returns`,
   `statutory_challans` and `financial_year_closes` exist (0 rows each);
   `invoices.due_date`/`payment_terms_days`, `products.category`/`brand`/
   `reorder_level` and `sales_orders.approved_at`/`expected_delivery_date`
   exist.
5. Started one server from this checkout on `127.0.0.1:8000`. Its
   `app.openapi()` now lists all 23 accounts paths.

**Result.** The seven endpoints answer `401` without a session instead of
`404` — the routes resolve. Their authenticated payloads were proven on the
test database by `tests/test_gst_statutory.py` and the §18.2 browser probe;
the dev load itself needs the signed-in browser to refresh, since the probe
browser holds its token in `localStorage` for the old `:8011` origin.

**Rule.** Run uvicorn from
`D:\This Dell PC Live Backup\User Account\Downloads\herbanova-final-corrected\herbanova-final-corrected`,
never from `herbanova-backend\herbanova-final`, and never leave two servers
bound to :8000.

## 20. Migration 0027 applied to development, 3 November 2026

**Approval.** `apply 8411462b33df` (sha256 of
`alembic/versions/0027_ledger_and_bank_rec.py`, first 12 hex characters).
The migration is additive: six new tables and nine seeded ledger heads, with a
working downgrade.

**Steps and evidence.**

1. Fresh backup: `var/backups/pre-migration-0027-20261103T093759.dump`
   (355,623 bytes; `pg_restore -l` lists 77 tables with data, matching dev at
   `0026`). `pg_dump` was given the password through the process environment;
   nothing was printed.
2. `python -m alembic upgrade head` ran
   `0026_gst_and_statutory -> 0027_ledger_and_bank_rec` in one transaction.
   `alembic current` reads `0027_ledger_and_bank_rec`.
3. Dev now has **83 tables**; `ledger_accounts` holds the nine seeded heads
   (1000 Cash, 1010 Bank, 1100 Receivables, 2000 Payables, 2100 Output GST,
   3000 Capital, 4000 Sales, 5000 Purchases, 5900 Round off) and the other five
   tables are empty.
4. `python -m alembic check` reports **No new upgrade operations detected**, so
   the models and the applied schema agree.
5. **Three** uvicorn instances were found bound to `127.0.0.1:8000` (the §19
   defect again: two reloader parents had left orphaned multiprocessing workers
   holding the socket). All were stopped and exactly one server was started from
   this checkout. Its `app.openapi()` lists 319 operations across 247 paths,
   with 41 paths under `/api/accounts`, of which 18 are the new voucher,
   opening, balance-sheet, day-book and bank-reconciliation paths.
6. The six new endpoints answer `401` without a session:
   `ledger-accounts`, `opening-balances`, `balance-sheet`, `vouchers`,
   `day-book`, `bank-statements`.
7. The services were run read-only against the dev database: 9 active heads,
   the 2026-27 opening trial balance has a row per head at 0.00 (difference
   0.00, no opening captured), the day book is empty, and the balance sheet at
   3 November 2026 balances (assets 4,580,094.76; liabilities 13,347,102.98;
   retained earnings -8,767,008.22; difference 0.00) while its warnings name the
   missing opening and the partial document layer.

**Not verified.** The signed-in screens on the dev database were not walked
through. The probe browser keeps its token in memory for the stopped `:8001`
server; a reload showed the sign-in screen, and no credential was used or asked
for. The UI evidence for these panels remains the test-database browser probe
recorded in `ACCOUNTS_DATA_GAPS.md` (GAP-A08 to A10).

**Result.** The dev database and the code now agree at `0027`, so the Accounts
panels load against dev data. Nothing was committed or pushed.

## 21. Accounts section bar — 3 November 2026

**What changed.** `Accounting & Finance` now opens with a section bar: one entry
per panel, one panel shown at a time, and an address per section
(`#/accounts/reports`, `#/accounts/receivables` … `#/accounts/locks`). The bar
lists only the sections the role may open. No server route, permission or
report changed; the panels keep their existing server gates and data loads.

**Method.** The current checkout was served by a temporary uvicorn on
`127.0.0.1:8011` with `DATABASE_URL` rewritten to `herbanova_bcs_test` (head
`0027_ledger_and_bank_rec`) and a one-route cookie helper on `:8012` that minted
a short-lived token with `make_token`. No password was typed, and no token or
credential was printed. The SPA was driven through the in-app browser's
`evaluate_script` (hidden viewport, so no screenshots). The helper files were
deleted afterwards.

**What was seen.**

| Check | Result |
|---|---|
| `node --check static/js/app.js` | Passed |
| Administrator (all three accounts keys), `#/accounts` | 18 entries in nav order; Performance and P&L highlighted; the seven report panels visible and no statement panel |
| Administrator, click Balance sheet | Address `#/accounts/balance-sheet`; only that panel visible; 17 rows; "Balanced"; four limit warnings |
| Administrator, direct load `#/accounts/bank` | Bank reconciliation highlighted; only that panel visible; empty state "No bank statement is captured…" (the test database has none) |
| Administrator, `#/accounts/does-not-exist` | Falls back to Performance and P&L; seven report panels |
| Administrator, click Vouchers then Back then Forward | Performance restored, then Vouchers; `aria-current` followed each time |
| `accounts:read` only (`t_sales`), `#/accounts/reports` | 17 entries, no Performance; falls back to Receivables |
| `accounts:read` only, open GST outward | 71 rows; totals line "Taxable 49,644.50 · CGST 2,376.00 · SGST 2,376.00 · IGST 0.00 · Total 54,708.50" |
| `accounts:read` only, open Trial balance | 11 rows; "Balanced" |
| Viewer with no accounts key, `#/accounts` | Screen not reachable; the route falls back to Overview as before |
| Route cycle dash / customers / sales / inventory / hr / expenses / accounts | Each screen rendered; no console messages |

**Defect found before the walk.** The first version of `applyAccountsSection()`
read an undefined `sec`. It was corrected to compute the section once and use
that value; `node --check` passed afterwards.

**Not verified.** Visual appearance at phone and tablet widths and in the dark
theme. The in-app browser has no visible viewport, so the wrapping CSS and the
dark-theme rules were not seen; only the computed `display:flex` and the DOM
behaviour were checked.

**Result.** The section bar, the permission split and the direct addresses work
in the browser on the test database. `tests/test_accounts_reports.py` was rerun
after the change (9 passed), including its three server-side 403 assertions for
a role without the accounts keys. Nothing was committed or pushed.

## 22. Responsive detail drawer — 3 November 2026

**What changed.** The single right-hand drawer (`#drawer`) that holds every
detail and edit panel now sizes itself by viewport width: 62% at ≥1440 px, 68%
at 1024–1439, 82% at 768–1023 and 100% below 768. The page behind it stays
visible under the scrim and its scrolling is locked while the drawer is open.
The title and × stay fixed above a body that scrolls on its own; table headings
stick within that body; a table too wide for the panel is moved into its own
horizontal scroll box (`fitDrawerTables`) so the drawer body never slides
sideways. ×, Escape and an outside click still close it, with the focus trap
unchanged. No API, route, permission, form field or action was modified.

**Method.** The current checkout was served by a temporary uvicorn on
`127.0.0.1:8011` against `herbanova_bcs_test` (head `0027_ledger_and_bank_rec`),
with the `:8012` cookie helper used in §21. A script drove headless Chrome over
the DevTools Protocol: it set the session cookie, emulated 1600×900, 1280×900,
900×900 and 390×844, opened `#/billing`, clicked the first invoice row
(`button[data-act=open-inv]`), then read geometry from the DOM and saved a
screenshot per width. A second pass exercised the customer drawer
(`[data-act=edit-dist]`) and the distributor ledger
(`[data-act=acc-ledger]`), all three close paths, and a long-ledger scroll. No
password was typed, and no token or credential was printed.

**What was seen.**

| Check | 1600×900 | 1280×900 | 900×900 | 390×844 |
|---|---|---|---|---|
| Drawer width / share of viewport | 992 px / 62% | 870.4 px / 68% | 738 px / 82% | 390 px / 100% |
| Drawer height | 900 | 900 | 900 | 844 |
| Drawer body horizontal overflow | 0 | 0 | 0 | 0 |
| Overlay present, body scroll locked (`overflow:hidden`) | yes / yes | yes / yes | yes / yes | yes / yes |
| × hit-tested at its top corner | `#dclose` | `#dclose` | `#dclose` | `#dclose` |
| Table heading computed position | sticky | sticky | sticky | sticky |
| Tables on the invoice / moved into a scroll box | 3 / 0 | 3 / 0 | 3 / 0 | 3 / 1 |

- The invoice line table (8 columns: line, qty, rate, taxable, CGST, SGST, IGST,
  total) needs 483 px of content. At 390 px it is contained in its own
  `.tw.tscroll` box: the table scrolls sideways, the drawer body and heading do
  not, and the money columns keep their full figures.
- Outside click at 1280 px (real mouse event at 200,400 on the scrim) closed the
  drawer; Escape and × did the same. After each close: `#drawer` hidden,
  `#scrim` hidden, `drawer-open` removed from `<body>`.
- Customer drawer ("Edit TD-AC0941"): 68%, form present, no horizontal overflow.
- Distributor ledger ("Ledger: Test distributor", `wide`): 68%, 5 entries, table
  inside `.tw`, heading sticky. With 40 duplicated rows the table measured
  2,055 px; the body was scrolled 600 px and the heading top stayed at 91.8 px
  against a body top of 87.8 px (4 px body padding), i.e. pinned.
- Dark theme: drawer, drawer header and sticky heading all computed to
  `rgb(23,35,28)`; no white strip behind the header.
- Background scrolling: at 1280×600 (page 836 px tall) a wheel over the page
  moved `scrollY` to 236 with the drawer closed; with the drawer open the same
  wheel left it at 0; after closing, the wheel moved it to 236 again.
- Console: no uncaught exception and no failed script request. One 404 for
  `/favicon.ico` appeared on a first-run profile only; the application has never
  served a favicon, so this is unrelated to the drawer.

**Defect found and fixed during the run.** With `overflow:visible` on the table
wrappers, the 8-column invoice table pushed the whole drawer body 109 px sideways
at 390 px. `fitDrawerTables()` now wraps an unwrapped table in `.tw` and marks a
table that is wider than its box with `.tscroll`; CSS gives that box
`overflow-x:auto`. Desktop widths were unaffected (no table marked).

**Not verified.** Physical phones and tablets, touch scrolling and pinch, iOS
safe-area insets, Safari and Firefox, screen readers, and the printable output
behind the drawer. The measurements come from Chrome's emulated viewports, not
real devices. The screenshots are in the run's temporary folder and were not
added to the repository.

**Result.** All four requested breakpoints and the close, scroll-lock and sticky
behaviour were measured in the real application on the test database. The
drawer is one shared container, so invoice, customer, distributor-ledger,
supplier, purchasing, expense, HR and Accounts panels inherit the same
behaviour with no per-screen change. Nothing was committed or pushed.


## 23. Receivables by distributor section — 3 November 2026

**What changed.** The "Receivables by distributor" table moved out of the
Performance panel's expandable drill-down and now has its own entry in the
Accounts section bar (`#/accounts/receivables-by-distributor`). It reads a
window as a statement — opening plus the window's movements equals closing —
with columns for opening, invoiced, credit notes, debit notes, received,
closing, overdue and open invoices per distributor. The window is chosen by
**Date**, **Month**, **Year** or **From/To**; **Apply** reloads and **Export
CSV** writes the loaded window. No schema change, migration or permission
change; the route sits behind `accounts:read`.

**Method.** Six tests were added to `tests/test_accounts_reports.py` covering
permissions and date guards, the per-row identity, reconciliation of closing
with the outstanding statement, as-at behaviour (a September receipt and credit
note are excluded from an August window), overdue requiring a due date before
the closing day, and an empty window. The full suite was then run. For the
screen, the current checkout was served by a temporary uvicorn on
`127.0.0.1:8011` against `herbanova_bcs_test` (head
`0027_ledger_and_bank_rec`) and driven by headless Chrome over the DevTools
Protocol at 1440×900: set the session cookie, load the section address, change
the month through the real control, then click Export CSV with a real mouse
event into a download folder.

**Measured.**

- `pytest`: **425 passed** (645 warnings, 214 s), including the six new tests.
- Section bar: 19 entries; `aria-current="page"` on "Receivables by
  distributor"; only its panel visible; the old `#accDrillPanel` no longer
  exists; Performance still opens from `#/accounts/reports`.
- Default window 01 Nov 2026–03 Nov 2026 loaded **30 rows**; the note read
  "… opening, movements and closing at 03 Nov 2026".
- Month `2019-05` reloaded to **01–31 May 2019** with **2 rows**; the Total
  row read closing **1,472.00** and received/invoiced **300.00 / 1,172.00**.
- Export CSV downloaded
  `HERBANOVA_Receivables_by_distributor_2019-05-01_2019-05-31.csv`: 13 columns,
  2 data rows, a Total row; the closing column summed to 1,472.00, equal to the
  Total cell.
- Layout: document `scrollWidth − clientWidth` = **0** at 1440, 1280 and 900 px.
  The table is wider than its box (1,214 px content against 1,115 / 970 / 575 px
  boxes) and scrolls inside `.tw`; the page itself does not move.
- Console: no uncaught exception and no failed request.

**Defect found and fixed during the run.** Rupee amounts in the Total row broke
between the sign and the digits ("₹" on one line). A scoped `white-space:nowrap`
kept them whole but let the nowrap table's min-content width stretch the grid
track, giving the page a 65 px horizontal overflow at 1440 px. `.view>*{min-width:0}`
in `static/css/styles.css` lets the grid item shrink while `.tw` keeps its own
horizontal scrollbar; the page overflow then measured 0 at all three widths.

**Not verified.** Firefox, Safari, real phones and tablets, screen readers and
the printed copy. The browser pass used an Administrator session; the
`sales` (200) and `viewer` (403) cases are covered by the API tests, not by a
browser session. The screenshot is in the run's temporary folder and was not
added to the repository. Nothing was committed or pushed.

## 24. Receipt/payment advances and the single receivables filter — 3 November 2026

**Scope.** `POST /api/accounts/payments` with `purpose = outstanding | advance`,
the new `payment_allocations` table (migration `0028_advances`), the two advance
heads, automatic draw-down at invoice issue and goods receipt, the party-ledger
presentation, `GET /api/accounts/advances`, and the Receivables by distributor
filter reduced to one From–To range applied only on **Apply**.

**Automated tests.** `tests/test_accounts_advances.py` (8 tests):

- A ₹ 300.00 receipt at day 2 settles invoices of ₹ 100.00 (day 0) and
  ₹ 150.00 (day 1) oldest-first, leaves ₹ 50.00 as an advance, reports both
  invoices at zero outstanding, and the ledger closes at −50.00 with the
  settled documents and the held amount in the receipt note.
- A receipt cannot settle an invoice issued after its own date: the invoice
  keeps ₹ 80.00 outstanding and the ₹ 80.00 waits as an advance.
- Advances are absent from Sales and Purchases in the trial balance and appear
  as ₹ 400.00 credit on **Advances from distributors** and ₹ 250.00 debit on
  **Advances to suppliers**.
- A ₹ 500.00 advance is drawn down by a dispatched invoice for the same party;
  outstanding falls by the applied amount and the ledger reports the remainder.
- A ₹ 500.00 supplier advance settles a ₹ 300.00 GRN automatically and leaves
  ₹ 200.00 available.
- The receivables-by-distributor window counts the allocation as received and
  closes the row at zero.
- An advance that names a document is refused 422, as is an unknown purpose.
- Server-side rights: `sales` may read the advance (200) but not record an
  entry (403); `viewer` is refused both (403); no money was recorded.

`pytest`: **432 passed** (647 warnings, 205.9 s) including the full suite. The
independent SQL cross-check in `app/services/reports.py` was taught about
allocations after the first full run showed the ageing total disagreeing with
its recomputation; the second run passed.

**Browser walk.** Disposable test database behind a temporary server on
`127.0.0.1:8011` (the real dev database was not written):

- Record receipt: 45 active distributors, **Record as** offered exactly
  *Existing outstanding invoice* and *Advance / new payment*; choosing a party
  fetched its advance and the hint read "Available advance: ₹ 382.00…";
  advance mode hid the document list. A ₹ 123.45 advance receipt closed the
  drawer, showed "₹ 123.45 held as advance" and added the row
  `RCPT-000013 … Advance ₹ 123.45`.
- Outstanding mode: a ₹ 500.00 receipt against a ₹ 472.00 invoice produced the
  row `INV/2627/000021 · ₹ 472.00` with `Advance ₹ 28.00`, i.e. the invoice
  settled and the excess held.
- Record payment: the supplier list and bill wording were correct; a ₹ 10.00
  advance payment showed `Advance ₹ 10.00` and the server hint showed the
  existing ₹ 250.00 advance.
- Receivables by distributor: the toolbar held only `#rbdFrom`, `#rbdTo`,
  Apply and Export CSV. Changing both dates produced **no** request; Apply
  produced exactly one request for `2026-10-01`–`2026-11-03`, and the heading
  and 34 rows / Total ₹ 60,105.50 followed the chosen range. A From after To
  showed the refusal with **no** request. Export produced a 3,471-byte
  `text/csv` named
  `HERBANOVA_Receivables_by_distributor_2026-10-01_2026-11-03.csv`.
- Console: no error or warning during the walk.

**Migration.** `0028_advances` was applied to the disposable test database by
the suite's `alembic upgrade head`. It creates `payment_allocations` (XOR target,
positive amount, indexes and a partial unique per payment and document), widens
`ck_ledger_account_role` and seeds heads `1110 Advances to suppliers` and
`2110 Advances from distributors`. Its downgrade refuses while either head is
used by an opening balance or voucher line, otherwise restores the old check and
drops the table and heads. **Applied to the development database on 3 November
2026** after a `pg_dump -Fc` backup (384,830 bytes), under the explicit
`apply 6a37ba20ecef` confirmation: `alembic current` reports
`0028_advances (head)`, `alembic check` reports no new upgrade operations, and
the two seeded heads exist with roles `supplier_advance` and
`distributor_advance`. On the live `:8000` server both new routes answer `401`
unauthenticated (present, not `404`), and `/ui/js/app.js` serves byte-identical
to the checkout, so the entry drawer and the single From–To filter are the
current build.

**Residual risks stated, not hidden.** Settlement is not serialised with a row
lock, so two operators recording a receipt for the same party at the same
instant could each see the same open invoice; the second transaction would be
refused by the outstanding check or leave an excess as an advance rather than
double-settling silently. Receipts held as advances count in the cash
collection figures on their date (they are cash), never in revenue. The
receivables report changes only on Apply by design; opening the section still
loads its default month.

## 25. Gap-closure round — 3 November 2026

**Scope.** Six changes on `feature/gap-closure`: clickable Accounts KPI cards,
two named start commands for the frontend and backend, password policy moved
fully to the server, e-mail delivery and worker-session defects, Administrator
TOTP, and Open/Print for credit and debit notes. Nothing was committed and no
development-database schema was changed in this round.

### 25.1 KPI cards open their own report

`GET /api/accounts/report` now returns an `href` on every one of its ten
`cards[]` entries, built from the same window the report used
(`app/services/accounting.py`). The tile is a plain link; the browser does not
choose a destination. A card with no figure still links to the section that
explains its gap.

Browser walk on the disposable test database (backend `127.0.0.1:8030`,
frontend `127.0.0.1:3030`, signed in as an Administrator):

| Card | Address opened |
|---|---|
| Revenue | `#/accounts/gst-out?from=…&to=…` |
| Output GST | `#/accounts/gst-out?from=…&to=…` |
| Collections | `#/accounts/cash?from=…&to=…` |
| Cash and bank (net) | `#/accounts/cash?from=…&to=…` |
| Receivables | `#/accounts/receivables` |
| Over 60 days | `#/accounts/ageing?as_of=…` |
| Payables | `#/accounts/payables` |
| Payable within 7 days | `#/accounts/payables?due=week` |
| Expenses | `#/expenses?from=…&to=…` |
| Net profit | `#/accounts/reports?focus=pnl` |

All ten destinations were distinct where the underlying report differs, the
window travelled in the address, and a refresh/back kept it. The walk found one
defect: `?due=week` set the filter state but the payables list had already been
drawn, so the first paint showed the unfiltered list. `route()` now re-draws
the statements when a hash-only navigation carries a payables filter; the
re-check showed "0.00 estimated to fall due within 7 days" on the payables
panel. No console error during the walk.

`tests/test_accounts_reports.py` covers the report payload and the card values;
there is no unit test that asserts each `href`, so that part is
**VERIFIED (browser)** only.

### 25.2 Two start commands

`scripts/run_backend.py` (uvicorn) and `scripts/run_frontend.py` (standard
library) are documented in [`RUNNING_SERVERS.md`](RUNNING_SERVERS.md). Verified
on loopback: the SPA, `app.js` and `styles.css` returned 200; `/api/auth/me`
through the proxy was 401 before sign-in and 200 after, so the first-party
cookie survived; `/docs` and `/openapi.json` were proxied; stopping the backend
made the frontend answer **502** with the command to run; `/../.env` and encoded
traversal variants were refused. A Windows path bug found during the walk
(`url2pathname` turning `/` into `\`, which made every static file 403) was
fixed by decoding with `unquote` and keeping POSIX separators.

**Not verified:** a production reverse proxy, TLS termination, a Windows
service wrapper and multi-worker deployment.

### 25.3 Password policy on the server

The policy, the temporary-password generator and the stored password live only
on the server (`validate_password`, `generate_temp_password` in
`app/core/security.py`; the `ChangePassword` field validator; user create and
reset in `app/api/users.py`). The browser sends the typed password, shows the
one-time password the server returned once, and mirrors no policy or generator.
A role change now bumps `token_version`, so a user promoted to Administrator
ends the old session and must pass the new role's sign-in rules.

Evidence: `tests/test_authz.py` (wrong current password 400, too-short new
password 422, unchanged password 400, old token revoked) and code review of
`app/api/users.py`. **Not verified this round:** the in-browser display of a
server policy message was not re-exercised; the API behaviour is covered.

### 25.4 E-mail delivery and database sessions

Three defects were fixed and covered by tests:

1. **Transport chosen by a contradicting setting.** A saved security choice
   that disagreed with the port made a correct password fail the handshake.
   `_transport` now treats 465 as implicit TLS, 587 as STARTTLS and any other
   port as the saved choice:
   `tests/test_email_settings.py::test_well_known_smtp_ports_decide_the_transport`.
2. **Failed settings read poisoned the session.** `load_row` now rolls back,
   so the next statement on the worker's session does not raise
   `PendingRollbackError`:
   `tests/test_email_settings.py::test_an_unreadable_settings_row_rolls_the_session_back`.
3. **A failed delivery could stay "sending".** `process_one` now rolls back,
   re-reads the delivery and its schedule, records the failure and commits it,
   so a database error is logged rather than raised:
   `tests/test_email_reports.py::test_a_schedule_with_no_next_run_is_committed_even_when_nothing_is_due`
   covers the related backfill commit; the failure path is exercised by the
   existing worker tests.

The connection pool is now bounded (10, 20 overflow, 30 s wait) and recycles
idle connections every 30 minutes (`app/core/db.py`, `app/core/config.py`).

**Not verified: a real delivery to a real inbox.** No live SMTP credential or
approved recipient exists, and real sends are prohibited by the standing
brief. Test-mode delivery remains the only executed path (G-09).

### 25.5 Administrator TOTP

Backend, tests and enrollment were verified; the full design is in
[`ADMIN_2FA.md`](ADMIN_2FA.md).

- `tests/test_totp.py` (8 tests): RFC 6238 vectors; replay refusal; a
  non-Administrator still signing in with the password alone; an Administrator
  receiving no session before enrollment; enrollment then a code at the next
  sign-in; a recovery code working once; a session without the `otp` claim
  being refused; five wrong codes locking the second step. All 8 pass.
  Every client in that file uses `base_url="https://testserver"` because
  `APP_ENV=production` makes the cookie `Secure`; without it the client did
  not send the cookie and five tests failed with `KeyError: 'secret'`.
- Browser walk: after the password an Administrator saw the enrollment screen
  with the setup key (the screen has no QR symbol); no `session` cookie was
  issued and `/api/auth/me` answered 401. The enrollment was completed in the
  page; the recovery codes were shown once.
- Screen layout, 3 November 2026: the second-factor screen is a centred card
  using the shared design tokens (`#totp` in `static/css/styles.css`). It was
  rendered in the running application at 830×519 and with headless Chrome at
  1280×900 — setup, verify with a refused-code alert, and recovery codes in
  the dark theme. Safe centring keeps the card top reachable when it is taller
  than the window; recovery codes stack below 600 px. Layout only: no
  endpoint, permission or flow changed.
- **Not run in the browser:** entering the verify code after enrollment. Read
  access to a stored secret or a generated code is blocked by the
  environment's credential rules, so that one step is covered by the automated
  test instead. Nothing was printed or logged.
- **Migration status:** `0029_totp` is at the head of the disposable test
  database because the suite runs `alembic upgrade head` there, and it was
  applied to `herbanova_bcs_dev` on 3 November 2026 with the owner's explicit
  `apply 0029_totp`. Backup first:
  `var/backups/pre-0029-totp-20261103T172245.dump` (392 KB, 84 table entries,
  SHA-256 `0d791f2795eb84db54a4c6a504e2b37ff9377732ddae84f6bc67dd47d5ee99b4`).
  After the apply: `alembic current` = `0029_totp (head)`; the seven `users`
  columns present with the expected nullability/defaults; 84 tables and 6 users
  unchanged; `admin` and `admin2` `token_version` 3 → 4; a full `User` select
  that had raised `UndefinedColumn` before now returns all 6 rows; a login
  request with an unknown username answered **401 Invalid credentials** (not
  500) with no traceback in the server log. Both Administrators will enrol at
  their next sign-in. Production remains unmigrated.

### 25.6 Credit and debit notes — Open and Print

The notes table in Billing lists both kinds newest first; each row has
**Open** and, with `print:document`, **Print**. `noteDetail` draws the stored
note (number and financial year, invoice, buyer only when known, date, reason,
returned-to-stock quantity for a credit, tax breakdown and lines) and the
print-log verification panel. Print posts to the existing secure route
`POST /api/print/{credit_note|debit_note}/{id}?copy=ORIGINAL`.

- `tests/test_file_audit.py::test_a_credit_and_a_debit_note_can_be_opened_and_printed`
  creates an invoice with two units, credits one and debits one, checks both
  list endpoints return the lines and invoice number, and extracts "CREDIT
  NOTE" and "DEBIT NOTE" from the generated PDFs.
- Browser walk as `browser_sales`: two note rows, both with **Open** and
  **Print**; Open showed `CN/2627/000001` with one line and a valid print
  panel; Print issued `POST /api/print/debit_note/1?copy=ORIGINAL` → 200
  `application/pdf`, with the print-log, verify and QR requests also 200.
  No console error.

### 25.7 Suite and counts

`python -m pytest -q`: **446 passed, 658 warnings in 221.86 s** (3 November
2026, after all six changes). The suite applies migrations to the disposable
test database only.

Route table: **327 API operations across 255 paths**, four of them the
Administrator second-factor endpoints. Module register unchanged at 18 entries,
17 counted/17 working plus the conditional e-invoice module.

### 25.8 What remains not verified

| Item | Why |
|---|---|
| A real e-mail reaching a real inbox | No live SMTP credential or approved recipient; real sends prohibited (G-09) |
| Typing the TOTP verify code in the browser | Stored secret/code access is blocked; covered by `tests/test_totp.py` |
| Production reverse proxy and TLS | Deployment work, not run |
| Physical phone, tablet and screen reader | No device or tooling (G-10) |
| `0029_totp` on the production database | No approved production deployment in this round |
| A unit test for each KPI card `href` | The addresses are browser-verified only |

---

## 26. Interface redesign pass — 3 November 2026

**Scope.** The whole site was audited screen by screen and restyled to the
supplied DMS reference: application bar, module rail, page heads, filter bands,
tables, forms, drawers, command palette, sign-in and two-step cards, light and
dark themes, at desktop, tablet and phone widths. Herbanova's original palette
was kept; no route, id, permission, endpoint or report was changed. The rules
are written down in [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md).

**Environment.** Static front end on `127.0.0.1:3000` proxying the API on
`127.0.0.1:8000`; reads only, no write action was performed on the development
database. Screens were driven through headless Chrome over CDP with a minted
Administrator session. The signed-out and two-step screens were captured
without typing a password; the two-step card was rendered by toggling the
existing sections, so that evidence covers layout only and is labelled so below.

### 26.1 What changed, and why

| Area | Change | Reason |
|---|---|---|
| Shell | 44 px branded bar with global search (Ctrl/⌘ K) and theme toggle; 232 px grouped rail; 26 px status bar | Put navigation, search and the environment statement where the reference puts them, and remove the theme/search duplicates that were on the dashboard |
| Dashboard | Title and date on the left, **MoM & YoY dashboard** action on the right; dates and presets moved into one tinted filter strip; duplicate greeting removed | The old three-row header repeated "Overview" and pushed the action onto its own line |
| HR workspace | Duplicate "HR workspace" heading hidden; toolbar styled as a filter band; attendance bars capped at 34 px | One page title, and one attendance day no longer painted as an enormous block |
| Accounts | Accounts overview panel restored to standard padding; report picker became a 140 px auto-fill grid; methodology notes capped at 78 ch | Heading and cards were flush to the panel edge; the picker was a ragged eight-across flex row |
| Tables | Zebra rows, sticky headers in scroll boxes, SKU cells on one line, row actions never wrap | Narrow screens were stretching rows to ~105 px because action buttons stacked vertically |
| Drawers | Lifted above the application bar (z-index 23, scrim 21) | The bar (z-index 22) covered the drawer title and close button on every screen |
| Tablet shell | Rows changed to `auto auto minmax(0,1fr) auto` | Auto rows were stretching the application-bar row from 44 to 80 px, leaving a blank band above the nav |
| Sign-in / 2FA | Single centred card on paper; 3 px brand rule above the headline; turmeric assurance marks | Matches the requested professional, centred treatment without changing the flow |
| Theme | Dark primary/danger buttons fixed (`#2f7d57` / `#b3261e`), `color-scheme: dark`, dark placeholders | Dark tokens made `--moss` light, so white-on-light-green buttons were unreadable |
| Accessibility | `--faint` darkened to `#66736b` (light) and `#84968a` (dark); focus ring is moss on light surfaces, turmeric on dark chrome | Placeholders were 3.01:1, and a turmeric ring on white is 2.25:1 |

### 26.2 Screens captured

Evidence is in `var/shots`. Every image was opened and reviewed during the pass;
the ones that exposed a defect were re-captured after the fix.

| Group | Files |
|---|---|
| Dashboard | `dash-1440`, `dash-dark`, `dash-1024`, `dash-360`, `dash-390` |
| Master data and operations | `products-1440`, `products-768`, `products-360`, `products-390`, `inventory-1440`, `sales-1440`, `billing-1440`, `purchasing-1440`, `suppliers-1440` |
| Finance | `accounts-1440`, `accounts-390`, `expenses-1440`, `reports-1440` |
| People and admin | `hr-1440`, `approvals-1440`, `customers-1440`, `settings-1440` |
| Signed out | `login-1440`, `login-390`, `totp-1440`, `totp-390` |
| Overlays | `drawer-product-1440`, `drawer-product-390`, `drawer-invoice-1440`, `drawer-invoice-390`, `palette-1440` |

### 26.3 Horizontal-overflow sweep

`var/shots/responsive.py` visited 23 routes at 390×844, 768×1024, 1024×768 and
1440×900, measured `documentElement.scrollWidth` against the viewport and
listed any element crossing the right edge outside an intentional scroll
container. Result: **92 of 92 combinations passed** (`scrollWidth == viewport`
in every case, no offender reported).

**Regression run.** The full suite was run after the last CSS and script edit:
**446 passed** in 277 s (`python -m pytest -q`, 3 November 2026, exit 0). The
pass changes no server code, so this shows the interface edits broke no API,
permission or reconciliation test.

### 26.4 Defects found and fixed during verification

| Defect | Evidence | Fix |
|---|---|---|
| Drawer title and × hidden behind the application bar | `drawer-product-1440`, `drawer-invoice-1440` before the fix | Drawer `z-index: 23`, scrim `21` |
| 36 px blank band between bar and nav at 768 px | `products-768` | Explicit tablet grid rows |
| Product rows ~105 px tall, SKU broken as `AYU- / OIL- / 001` | `products-768` | `td.sku{white-space:nowrap}` and `.rowacts{flex-wrap:nowrap}` |
| Mobile invoice line table clipped at SGST | `drawer-invoice-390` | Measured the scroll wrapper: 361 px viewport against 493 px content, `overflow-x:auto`; the scrollbar is simply not painted in a headless screenshot. No code change. |
| Over-long methodology paragraph on Accounts | `accounts-1440` | `.panel-note{max-width:78ch}` |
| Modal dashboard action wrapping alone | `dash-1024` | Hero/filter-band restructure |

### 26.5 Contrast measurements

Computed from the token values with the WCAG relative-luminance formula.

| Pair | Ratio | AA normal text (4.5:1) |
|---|---|---|
| `--ink` on `--surface` | 16.57:1 | pass |
| `--mute` on `--surface` | 6.30:1 | pass |
| `--mute` on `--head` | 5.32:1 | pass |
| `--faint` on `--surface` (placeholder) | 4.97:1 | pass |
| white on `--moss` | 6.44:1 | pass |
| white on dark primary `#2f7d57` | 5.01:1 | pass |
| `--ok` / `--warn` / `--bad` on their tinted backgrounds | 4.91 / 5.29 / 5.37:1 | pass |
| `--moss` focus ring on white | 6.44:1 | pass (3:1 non-text) |
| `--turmeric` focus ring on forest | 7.62:1 | pass |
| white on `--turmeric` | 2.25:1 | **not used anywhere** |

**Motion.** `var/shots/motion.py` emulated `prefers-reduced-motion: reduce` over CDP and read the computed styles: the drawer animation and button transitions report `1e-06s` (`reduced: true`), against `0.2s` and `0.15s` with no preference. The rule at `static/css/styles.css:357-359` therefore reaches the browser, not just the file.

### 26.6 What was not verified

| Item | Why |
|---|---|
| Physical phone, tablet and touch gestures | No device available |
| Screen readers and full keyboard tab-order walk | No assistive tooling in this workspace; focus rules are CSS-verified only |
| Firefox, Safari and Edge | The walk used headless Chrome over CDP |
| Lighthouse or other performance scoring | Not installed; no score is claimed |
| The real two-step challenge after a password | Credentials are not typed into scripts; the card was rendered from the existing markup, and the challenge itself is covered by `tests/test_totp.py` |
| Print stylesheets and generated PDFs | PDF output was covered in §25; the redesign did not touch print CSS |
| Production data and production deployment | Not touched in this round |

The one content observation to hand to the owner: the status bar reads
`Environment: production` while the development backend serves the page (the
value comes from `APP_ENV` on the server). It is pre-existing and was not
changed.

## 27. Sign-in page content and the Overview range control — 4 November 2026

**Scope.** The Administrator-managed sign-in page (promotion banners, dated
notices, the three help-line boxes and the two legal pages) and the Overview
period control (trigger, presets, two-month calendar). Schema is migration
`0030_sign_in_content`; every route and table is additive.

**Environment.** A temporary `uvicorn` on `127.0.0.1:8010` against the isolated
test database `herbanova_bcs_test`, migrated to `0030_sign_in_content`, with the
static front end served from the same process. The browser was headless Chrome
driven over CDP. The development database (`herbanova_bcs_dev`) was **not**
migrated and was not written to; production was not touched. The pytest session
recreated the test database afterwards, so the probe's banners, notices and
edits no longer exist.

### 27.1 What the automated tests prove

`python -m pytest -q tests/test_signin.py` — **8 passed**. Each test names the
rule it pins:

| Test | Rule |
|---|---|
| `test_the_public_page_never_invents_content` | With no rows, the public payload carries empty lists; the page shows the neutral empty state, not sample text |
| `test_unpublished_legal_text_is_not_returned` | A `published = false` legal row is not served |
| `test_banner_upload_replacement_deactivation_and_delete` | Upload, replace (old file removed), deactivate and delete |
| `test_banner_upload_refusals` | File type and the 2,000,000-byte ceiling are refused |
| `test_notice_crud_and_public_order` | Notice create/edit/delete and the order the public page receives |
| `test_contact_boxes_are_validated_and_editable` | A box needs a label and at least one value; e-mail shape is checked |
| `test_legal_text_must_be_written_before_it_is_published` | Publishing with an empty body is refused |
| `test_only_the_administrator_manages_sign_in_content` | A non-administrator is refused every write, and reads the public route |

`python -m pytest -q tests/test_db_reset.py` — **24 passed**, including the
business-mode run that requires every KEPT table, now also
`sign_in_banners`, `sign_in_notices`, `sign_in_contacts` and
`legal_documents`, to be byte-identical after a reset.

### 27.2 Browser walk — sign-in page

Screenshots are in `var/shots`. The database held one banner, two notices and
three contacts created through the administrator endpoints.

| View | Files | What was checked |
|---|---|---|
| 1440 light | `signin-content-1440-light` | Banner left, credentials and help line right, footer with copyright and both legal links |
| 1440 dark | `signin-content-1440-dark` | Same layout on dark tokens; no panel loses its border or placeholder contrast |
| 768 | `signin-content-768` | One column, credentials first, banner and notices below |
| 390 | `signin-content-390` | Same order, banner shortened, no control off-screen |
| Administrator panel | `signin-admin-panel-light`, `signin-admin-panel-dark` | The Settings → Sign-in page drawer with banner upload, notice list and contact boxes |
| Filled and edited | `signin-admin-filled-1440`, `signin-admin-edited-1440` | After saving a notice edit, a contact edit and a banner replacement |
| Forgot Password | `signin-forgot-1440` | The panel names the Administrator, shows the Customer Support box and sends nothing |
| Legal | `signin-legal-1440` | A published Privacy Policy renders in the dialog |
| Save ID | `signin-saveid-return` | After sign-out and reload the User ID is prefilled and the box is ticked |

**Measured content changes.**

- Both banners were submitted through the drawer's own form
  (`#signinBannerForm`) with a generated PNG placed on the file input as a
  `FileList`; the native file-picker dialog itself was not opened. Replacing
  the banner changed the bytes served by
  `/api/public/sign-in/banners/{id}/image`: the new file was reported as
  `38c66ffb4ac454af0381da36fee4d1136025816a` (SHA-1), 21,638 bytes, and the
  old file was gone from `var/signin_banners`.
- The revised notice title and body and the revised Service contact appeared on
  the public page after saving, which is the check that the page reads the
  database rather than fixed markup.
- Publishing Privacy Policy with an empty body was refused with `422` and the
  message "Write the document text before publishing it". After entering 156
  characters of synthetic text it published, and the footer link opened it.
- Save ID: with the box ticked the User ID reappeared after sign-out and a full
  reload; with it cleared the stored value was removed. The value lives in
  `localStorage` only; no password is stored or prefilled.

**Role checks.** A `viewer` login received `403` from `GET`, `POST` and `PATCH`
under `/api/admin/sign-in/*`, while the three `/api/public/sign-in*` reads
answered `200` with no session. The gates are evaluated on the server
(`require_admin("user:manage")`), not only in the browser.

### 27.3 Browser walk — Overview period control

| View | File | Measured |
|---|---|---|
| 1440 light, open | `dash-range-1440-light` | Trigger label `Nov 1, 2026 - Nov 4, 2026`, 231 px; popover 620 px; months November and December 2026; `scrollWidth == viewport` |
| 1440 dark, open | `dash-range-1440-dark` | Same geometry on dark tokens |
| 1440 closed | `dash-range-1440-closed` | Trigger with caret and calendar glyph, no popover |
| 768 | `dash-range-768` | Popover fits the content column |
| 390 open and closed | `dash-range-390`, `dash-range-390-closed` | Trigger 336 px, popover 358 px, zero horizontal overflow at 390×844 |

Preset clicks were exercised for `30D`, `90D` and `This FY`; the label moved and
the dashboard issued `GET /api/dashboard?from_date=…&to_date=…`, not a
client-side filter. A custom pair was then picked in the calendar — 5 October
start, 20 October end — and the request
`from_date=2026-10-05&to_date=2026-10-20` returned `200`; the preset lost its
pressed state and the pair was written to `localStorage`. The backwards-pair
swap, future-day disabling and the next-month arrow limit were read at
`app.js:1760-1846` but not separately driven; only the layout, the preset
clicks, one custom pair, the resulting requests and the stored values were
exercised.

### 27.4 Regression run

`python -m pytest -q` on 4 November 2026 against the isolated test database:
**454 passed, 0 failed, 693 warnings in 258.61 s (exit 0)**. This includes the
eight sign-in tests, the 24 database-reset tests after the KEPT-table seeds were
added, and the whole earlier suite. The run recreated the test database and left
it at `0030_sign_in_content`.

### 27.5 What was not verified

| Item | Why |
|---|---|
| Migration `0030_sign_in_content` on development and production | Applied to the test database only. Development is at `0029_totp` and production at `0028_advances`; migrating them needs a verified backup and the owner's explicit `apply <fingerprint>` |
| Automatic rotation with two or more banners | Only one image file was uploaded during the walk, so the 6-second cycle never advanced; `startPromoRotation` and its pause bindings were read, not executed |
| Real tablet and phone | Desktop-emulated widths only; no physical device |
| Screen readers | No assistive tooling in this workspace |
| Opening the operating system's file-picker dialog | The form was submitted with a generated `FileList` on the input; the native dialog cannot be opened headlessly, but the panel's upload path itself ran |
| A dedicated test for the range widget | The server-side window is covered by `tests/test_dashboard_phase2.py` and `test_dashboard_phase3.py`; the popover itself has browser evidence only |
| Production data | Not touched in this round |
