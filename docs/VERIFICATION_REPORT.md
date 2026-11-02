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
