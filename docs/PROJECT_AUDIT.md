# Herbanova — Whole-Project Audit (Phase 1)

Date: 1 November 2026
Branch: `feature/hr-upgrade` (from `45306c2`)
Auditor: implementation agent, working only from the running code, the live development
database (read-only queries), the test suite and the existing documents.

**Baseline taken before any change**

| Item | Evidence |
|---|---|
| Database backup | `archive/herbanova_pre_hr_20261101_071046.dump` (custom format, `herbanova_bcs_dev`, 247,438 bytes) |
| Working tree | clean at `45306c2` before the branch was created |
| Test suite | `python -m pytest -q` → **169 passed, 0 failed, 0 skipped in 29.74s** |
| Routes | 184 routes under `/api` (189 HTTP routes including `/`, `/docs`, `/redoc`, `/openapi.json`) |
| Tables | 54 ORM tables under `app/models/` |
| Screens | 23 SPA views in `static/index.html` |
| Report catalogue | 26 report keys in `app/services/reports.py` (`CATALOG`) |
| Permission keys | 44 in `app/core/permissions.py` (`PERMISSIONS`) |
| Tests by module | see §4; 8 tests for all of HR, none dedicated to leads, suppliers, billing, notes, payments, distributors, customers or tax configuration |

Nothing in this document is inferred from a screen I did not run. Items I did not execute
are marked **Not verified** and the reason is given.

---

## 1. How this audit was produced

1. Enumerated every route from the FastAPI app object (`app.routes`) and every guarded
   route's permission dependency by walking `dependant.dependencies` and the dependency
   closures. This is the same data the server uses, not a grep of decorators.
2. Enumerated every table from `Base.metadata.tables` and compared it with the live
   development database (read-only `COUNT(*)` and null-count queries; no rows returned
   beyond aggregates).
3. Read the HR API/service/model code in full (`app/api/hr.py`, `app/services/hr.py`,
   `app/services/payroll.py`, `app/services/hr_approvals.py`, `app/models/hr.py`,
   `app/services/salary_slip.py`) and the relevant parts of approvals, RBAC and employees.
4. Compared the code with every document in `docs/` and the root `INSTALL.txt`.
5. Searched for `TODO`, `FIXME`, `XXX`, `HACK`, sample/demo/fixture data in application
   code, endpoints never referenced by the SPA, duplicated logic and unimplemented
   approval types.
6. Ran the full suite on the untouched branch to establish the baseline above.

---

## 2. Module-by-module inventory

Status words used below:

- **Working** — the stated capability exists, is server-guarded and has passing tests.
- **Working, gaps** — the core works, but named parts of the module are absent or
  half-built.
- **Partial** — a meaningful part of the expected module is missing.
- **Conditional** — deliberately not built unless the business requires it.

| Module | Status | Routes | Tables | Screens | Tests | Main gap |
|---|---|---:|---|---|---|---|
| Products | Working | 4 | `products` | `#/products` | 4 | No bulk import, no category master, no product detail view |
| Stock, batches, warehouses | Working | 9 (inventory 2, warehouses 3, POs 5 covers purchasing) | `batches`, `stock_movements`, `warehouses`, `goods_receipts`, `goods_receipt_lines` | `#/inventory` (three tabs) | 5 capacity + 4 PO | No stock transfer/adjustment, no GRN PDF |
| Warehouses and capacity | Working | 3 | `warehouses` | `#/inventory/warehouses` | 5 | Capacity is a number only; no per-batch bin location |
| Purchasing | Working, gaps | 5 | `purchase_orders`, `purchase_order_lines`, `goods_receipts`, `goods_receipt_lines` | `#/purchasing` | 4 | No PO edit, no PO print, no supplier-invoice match |
| Sales orders | Working | 7 | `sales_orders`, `sales_order_lines` | `#/sales` | Covered indirectly in approvals/dashboard tests | No order edit, no partial dispatch |
| Billing | Working, gaps | 8 invoices + 5 credit + 5 debit + 6 print | `invoices`, `invoice_lines`, `credit_notes`, `credit_note_lines`, `debit_notes`, `debit_note_lines`, `print_logs` | `#/billing` | None dedicated | No invoice e-mail, no e-invoice/e-way bill (MOD-15 conditional), notes only tested through other suites |
| Approvals | Working, gaps | 3 | `approval_requests` | `#/approvals`, Overview "Approvals waiting" | 3 + HR decision tests | Three approval labels have no handler; no escalation or multi-level flow |
| Accounts | Working, gaps | 10 | `payments` (+ invoices/notes) | `#/accounts` | 21 (accounts reports + reconciliation) | No accounting-period lock, no journal/expense/bank reconciliation, unallocated receipts still open (M-02) |
| Leads and follow-ups | Working | 9 | `leads`, `lead_activities` | `#/leads`, `#/lost`, `#/followups` | **None dedicated** | No lead import/export, no dedicated tests |
| HR | Working, many gaps | 44 | 20 `hr_*` tables + `employees` | `#/hr` only | 8 | See `docs/HR_AUDIT.md` |
| Reports | Working | 3 | reads all | `#/reports` | 20 (reports + reconciliation) | No saved report views; HR reports are API-complete but not surfaced individually |
| Alerts | Partial | Derived only (`/api/dashboard`, `/api/dashboard/expiry`) | — | Overview panels | Dashboard tests | No alert centre, acknowledgement, or per-user notifications |
| Scheduled e-mails | Working | 18 | `email_recipients`, `email_schedules`, `email_schedule_recipients`, `email_deliveries` | `#/scheduled` | 53 | Test mode only (required); no HR pack yet |
| Backups and restore | Working (manual) | — | — | — | 2 | Script and test only; no UI, no schedule |
| Users and roles | Working | 10 | `users`, `roles` | `#/users`, `#/settings` | 7 authz + 7 parity | No MFA, no active-session list |
| Settings | Working, gaps | 6 tax/company + HR config through HR routes | `company_profile`, `tax_rates`, `discount_slabs`, `hr_branches`, `hr_work_locations`, `hr_shifts`, `hr_departments`, `hr_holidays` | `#/settings`, HR shift button | Tax config tests only | Branches, offices, departments, holidays and leave types have no screen |

"Alerts" is not a module in code: the Overview computes "needs attention" and the expiry
list. There is no `alerts` table, route or screen, and no acknowledgement state.

### 2.1 HR surface measured

| Area | Routes | What exists | What is missing |
|---|---|---|---|
| Dashboard | 1 | today's counts, pending requests, payroll status, department/branch headcount | date range, trend, joiners/exits, attrition, probation, expiring documents, birthdays/anniversaries, holidays, "needs attention" details, click-through filters |
| Employees | 4 | list/search/department/branch/status/page, create/edit, self or `hr:write` profile read | manager/location/type filters, sort, saved filters, bulk import/export, documents, assets, history, masking of bank/PAN/UAN/ESI, probation fields |
| HR configuration | 12 | branches, offices, shifts (create/edit), departments, holidays, leave types | no screens for branches/offices/departments/holidays/leave types; no delete/deactivate |
| Attendance | 6 | self check-in/out with geofence, manual mark, corrections request/list/decide | bulk mark, monthly calendar/heat map, overtime, lock, monthly summary, shift roster |
| Leave and OD | 8 | types, applications, balances, cancel, OD create/list, approval handlers | half-day, working-day count that excludes holidays/weekly offs, team calendar, carry-forward/encashment, admin balance adjustment |
| Salary and payroll | 12 | components, structures, periods, prepare, submit, approve, process, pay, register, PDF slip, correction request (audit-only) | confidential-field enforcement is inconsistent, PF/ESI/PT/TDS configuration and summaries, bank transfer file, Accounts reconciliation, period lock, correction workflow (`hr_payroll_corrections` is never written), payslip for self-service |
| Outputs and letters | 1 | salary slip PDF | appointment/offer/experience letters, ID card, leave statement, attendance sheet, editable templates |
| Reports | 0 HR-specific routes | 12 HR report keys in the central catalogue | headcount/attrition, department cost and document-expiry reports; no HR report pack |
| Notifications | 0 | — | in-app notifications, birthday/expiry reminders, e-mail in test mode |

---

## 3. Documented versus coded

### 3.1 Documented but not coded

| Claim | Source | Reality |
|---|---|---|
| Business Requirements Document (BRD) | task brief | **No BRD exists in the repository.** `docs/` has stage audits, registers and manuals only. Recorded as a gap; a requirement traceability matrix cannot cite a BRD that is absent. |
| Feature Inventory | task brief | **No such file exists.** `docs/DASHBOARD_FEATURES.md` covers the dashboard and Accounts/email additions only. |
| Requirements Traceability Matrix | task brief | **No such file exists.** `docs/FORMULA_AND_BUSINESS_RULE_REGISTER.md` traces formulas, not requirements. |
| HR chapters 19–20 | `docs/user-manual/README.md:77-78` | Marked **PLANNED** while the HR module has 44 routes, 20 tables and passing tests. The manual is stale, not the code absent. |
| `app/api/customers.py` | `docs/user-manual/README.md:63` | The file does not exist. Customers are read through distributor/invoice routes and `#/customers` calls the sales read surface. |
| 42 permission keys | `docs/permissions-matrix.md:186` | The catalogue now has **44**. `accounts:reports` and `email:manage` are absent from the role tables in that document. |
| Financial-year / period locks for Accounts | previous Accounts brief, echoed in the Phase 3 checklist | No lock table, column, route or service exists in `app/` (searched `lock`, `period`, `financial`). **Not implemented.** |
| HR approval for overtime, salary revision, reimbursement | `app/core/rules.py:31-34` | The labels exist, but no endpoint raises these requests and `decide_hr_request` has no handler; the queue itself says "No decision handler yet". |
| Multi-level approval workflow | `hr_approval_workflows` table | The table is never read or written by application code. No multi-level routing exists. |

### 3.2 Coded but not documented (or under-documented)

| Capability | Code | Documentation gap |
|---|---|---|
| Accounts dashboard, comparison and report pack | `app/api/accounts.py` (`/report`, `/report/compare`), `accounts:reports` | Described only in `docs/DASHBOARD_FEATURES.md` §14–15; absent from the manual and permissions matrix role tables |
| Scheduled e-mail reports | `app/api/email_reports.py` (18 routes), 4 tables, worker | `docs/EMAIL_REPORTS.md` exists; absent from the module register and manual |
| Invoice-line expiry history | `GET /api/invoices/expiry` | Not found in the documents searched |
| Print verification (QR, digest, verification page) | `app/api/printing.py` | Mentioned only in the module register summary, not in the manual |
| Product options endpoint | `GET /api/products/options` | Not in the field-mapping document |
| Dashboard activity feed | `GET /api/dashboard/activity` | Not referenced by the SPA; documented only in the metric register |
| HR reports (12 keys) | `app/services/reports.py` | No HR report screen entry and no manual chapter |
| Payslip PDF | `GET /api/hr/payroll/entries/{id}/slip` | No manual chapter |
| Module register | `app/core/module_register.py` | 16 modules; does not include Accounts reporting or scheduled e-mails; asserts MOD-16 HR "Working" without the gaps in this audit. **Closed after this audit:** the register now has MOD-17 Accounts reporting and MOD-18 Scheduled e-mail, 17 counted modules. |

### 3.3 Stale or contradictory claims

- `docs/permissions-matrix.md` route-guard counts ("regenerated on 1 November 2026") do not
  match the current app: 44 keys versus the stated 42, and `accounts:reports` /
  `email:manage` are missing from the role grids.
- `docs/user-manual/README.md` lists Reports (18) and both HR chapters (19, 20) as
  **PLANNED** although the routes, screens and tests exist.
- The module register says HR is "Working" with no qualification. The core works, but
  salary masking, self-service payslips, documents, letters, notifications, locks and
  statutory payroll do not exist. This audit records HR as **Working, many gaps**.
- The module register's "Built modules" group omits the two newest deliveries (Accounts
  reporting, scheduled e-mails), so the Overview's 100% figure is computed over 15 counted
  modules that no longer describe the whole product.

---

## 4. Tests

| Test file | Tests | Covers |
|---|---:|---|
| `test_email_schedules.py` | 24 | schedule arithmetic, worker, retries, duplicates |
| `test_email_reports.py` | 17 | renderer, packs, figures |
| `test_report_reconciliation.py` | 12 | dashboards versus reports |
| `test_email_api.py` | 12 | recipients, schedules, test mode |
| `test_dashboard_phase2.py` | 11 | dashboard aggregates and drill-downs |
| `test_dashboard_compare.py` | 9 | MoM/YoY |
| `test_accounts_reports.py` | 9 | Accounts totals, permission gate |
| `test_reports.py` | 8 | report catalogue and exports |
| `test_hr.py` | 8 | all of HR |
| `test_roles_parity.py` | 7 | catalogue and seeded roles |
| `test_dashboard_phase3.py` | 7 | insight cards |
| `test_authz.py` | 7 | authentication and permission denial |
| `test_dashboard_v2.py` | 6 | v2 dashboard |
| `test_capacity.py` | 5 | warehouse capacity |
| `test_purchase_orders.py` | 4 | PO lifecycle |
| `test_products.py` | 4 | product master |
| `test_module_status.py` | 4 | module register rules |
| `test_dashboard_geo.py` | 4 | geography |
| `test_dashboard.py` | 4 | baseline dashboard |
| `test_approvals.py` | 3 | sales-order decisions |
| `test_backup_restore.py` | 2 | dump and restore reconciliation |
| `test_smoke.py`, `test_document_layout.py` | 1 each | smoke, PDF layout |
| **Total** | **169** | |

**No dedicated test file exists for:** leads, lead follow-ups, distributors, customers,
suppliers, purchase receipts beyond PO tests, invoices, credit/debit notes, printing,
payments/ledgers, tax configuration, warehouse CRUD, user administration, audit export,
HR documents/letters (not implemented), HR dashboard, HR reports, HR self-service.
Coverage was not measured in this baseline because no coverage tool is installed; Phase 3
will install/use one or record it as unavailable.

---

## 5. Code hygiene

| Check | Result |
|---|---|
| `TODO` / `FIXME` / `XXX` / `HACK` in `app/`, `static/`, `tests/`, `seed.py` | **None found.** |
| Hard-coded sample/demo data in production code | No invented business figures. The only "sample" names are `_sample_days` (a date sampler in the dashboard) and `sample` as a product unit label (`app/core/rules.py:15`). Demo seeds live in `seed_demo.py` and are guarded by `demo_mode`. |
| Secrets in code | None found; settings read from environment/`.env`. This audit did not print or copy `.env`. |
| Duplicated logic | Two employee masters: `/api/employees` (`employee:read/write`) and `/api/hr/employees` (`hr:read/write`), with two schemas and two audit paths. The SPA uses `/api/employees` for the user-link dropdown and `/api/hr/employees` for HR. They share the same table, so they cannot diverge in data, but validation, returned fields and audit differ. |
| Dead or unreachable capability | `hr_approval_workflows` (never read/written); `hr_payroll_corrections` (never written); approval labels with no handler; `GET /api/hr/payroll/periods/{id}/register` not called by the SPA; `POST /api/hr/attendance/{id}/correction` and the corrections list have no screen; salary components/structures have no screen. |
| Routes never referenced by the SPA | 33 candidates from a path scan. Some are false positives because the SPA builds paths dynamically (payroll actions, notes). Confirmed unused by any UI path: holidays, departments, salary components/structures, attendance corrections, leave cancellation, payroll register, `/api/employees/{id}` read/edit, `/api/products/options`, `/api/dashboard/activity`, `/api/invoices/expiry`, `/api/tax/place-of-supply`, supplier ledger. |
| Unhandled approval types | `hr_overtime`, `hr_salary_revision`, `hr_reimbursement` carry UI labels but can neither be raised nor decided. |
| Warning noise | 371 deprecation warnings per suite run (FastAPI/Starlette/slowapi on Python 3.14). Not a defect, but it will hide new warnings. |

---

## 6. Security and confidentiality review (server-side)

The route audit confirms **every `/api` route has a server-side dependency** except the six
intentional public ones: `POST /api/auth/login`, `POST /api/auth/logout`,
`GET|POST /api/email-reports/unsubscribe/{token}` (token in the URL),
`GET /api/health`, and the root page. No route relies on the browser to hide data.

Findings that contradict the current confidentiality rule ("salary, bank, ID and other
personal data are visible only to the Administrator, the MD and the HR roles the
Administrator allows"):

| # | Severity | Finding | Evidence |
|---|---|---|---|
| S-01 | High | `GET /api/hr/employees` returns `bank_name`, `bank_account_no`, `bank_ifsc`, `pan`, `uan`, `esi_no`, `address`, `emergency_phone` to **every holder of `hr:read`**, including the live `employee` role (all staff) and `reporting_manager`. | `app/api/hr.py:163-178, 222-244`; live `roles` query: `employee` and `reporting_manager` hold `hr:read` |
| S-02 | High | Salary structures can be created with `hr:write` alone, without `hr:confidential` or `hr:payroll_prepare`; reading them needs `hr:payroll_prepare` but not `hr:confidential`, so the `hr:confidential` key does not actually gate salary data. | `app/api/hr.py:995-1060` (component/structure routes), `app/core/permissions.py:59` |
| S-03 | Medium | An approver with `hr:leave_approve` (live `reporting_manager`) sees **all** HR approvals, including `hr_payroll` with its net-pay total, because the list filter admits every HR row for any HR decision permission. | `app/api/approvals.py:196-203`; live role `reporting_manager` holds `approval:read` + `hr:leave_approve` |
| S-04 | Medium | Employee-update audit entries store old and new bank account / PAN / UAN / ESI values in clear text. `audit:read` is currently Administrator-only, but the values persist in the audit table. | `app/api/hr.py:286-294` |
| S-05 | Low | `GET /api/hr/employees/{id}` allows only self or `hr:write`, so an `hr:read` manager without write cannot open a team member's profile, while the list already returns their full record. The two rules disagree. | `app/api/hr.py:299-308` |
| S-06 | Low | Payroll register and period detail need `hr:payroll_prepare`; the payslip needs `hr:confidential`. A payroll officer can read the register but cannot download the slips they prepared. | `app/api/hr.py:1103-1260` |
| S-07 | Informational | Segregation of duties is enforced for leave/OD/corrections/payroll (requester cannot decide; preparer cannot approve) with tests. | `app/services/hr_approvals.py:37-63, 138-149`; `tests/test_hr.py:11-109` |

These are recorded as Phase 2 work, not changed in Phase 1. Until they are fixed, the
application should not be treated as meeting the confidentiality rule.

---

## 7. Data-quality snapshot (development database, 1 November 2026)

Read-only aggregates only; no row content was printed.

| Check | Count |
|---|---:|
| Employees total / active | 7 / 7 |
| Employees missing department | 0 |
| Employees missing office | 2 |
| Employees missing shift | 0 |
| Employees missing manager | 7 |
| Employees missing joining date | 5 |
| Employees missing e-mail | 5 |
| Employees missing phone | 7 |
| Attendance rows | 5 |
| Leave applications | 1 |
| Payroll periods | 1 |
| Salary structures | 1 |
| Warehouses | 4 |
| Warehouses without capacity | not measurable with the assumed column name; the exact column will be checked in Phase 3 |

This is demonstration data, not production evidence. **No data yet** for: leave balances in
use, documents, assets, notifications, letters, statutory payroll, bank transfer files,
employee history. Those modules' reports must say "No data yet" until real rows exist.

---

## 8. Gaps carried into Phase 2 and Phase 3

### 8.1 Security (fix first)

1. Mask bank/PAN/UAN/ESI in HR employee responses unless the caller holds
   `hr:confidential`, the caller is the employee themself, or the caller is the
   Administrator. Return a masked display value and a `confidential` flag instead of
   silently omitting fields.
2. Require `hr:confidential` (or `hr:payroll_prepare`) to create salary structures and read
   salary data; keep `hr:write` for non-salary employee fields.
3. Restrict `hr_payroll`, `hr_salary_revision` and `hr_reimbursement` approvals to payroll /
   confidential roles; never show net payroll to a leave approver.
4. Mask sensitive values in audit entries and add a test that reads the audit row.
5. Align the profile read rule with the list rule and document it in `docs/HR_ROLES.md`.

### 8.2 HR capability (Phase 2)

Dashboard tiles and cards with drill-through; employee list filters/sort/saved views/bulk
import/export; profile tabs with documents, assets and history; attendance bulk marking,
monthly heat and locks; leave half-day, working-day counting, team calendar, carry-forward
and encashment; payslip self-service; letters and templates; ID card; attendance sheet;
leave statement; HR report pack; notifications; period locks with Administrator override
and reason; statutory configuration **only where configured** (no invented rates).

### 8.3 Verification (Phase 3)

Install/run coverage, lint/type/build checks where tooling exists; migration round-trip and
head check; role matrix per endpoint; dashboard/report reconciliation at month ends, leap
year, short previous month, zero/missing previous month and an empty database; desktop and
phone, light and dark; e-mail test-mode delivery and figures; backup/restore; data-quality
counts. Anything that cannot be run will be marked **Not verified** with the reason.

**Result:** executed and recorded in [`docs/VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md).
The suite passes 230/230, the migrations round-trip to `0015_statutory_heads`, the live role
matrix refuses confidential data to non-HR roles, backup/restore matches the live database,
and the remaining unrun items (empty database, live test-mode send, physical-phone and
external-bank checks) are listed there as **Not verified** with their reasons.

---

## 9. Decisions and assumptions

Recorded here because the task brief asks for `docs/DECISIONS.md` and no such file existed.
A running decision log is created in `docs/DECISIONS.md`; this section records the audit's
own assumptions.

| # | Assumption | Reason |
|---|---|---|
| A-01 | "MD" is not a distinct technical role in the live data. The Administrator and any custom role the Administrator grants `hr:confidential` are treated as the allowed audience. | No `md` role exists in `roles`; inventing one would change access without authorisation. |
| A-02 | The development database is demonstration data; no production database is connected to this workspace. | `.env` points at `herbanova_bcs_dev`; no production host is configured. |
| A-03 | Existing route paths, permission keys and response fields stay backward compatible. New fields are added, never removed; masking adds a value rather than deleting a field where possible. | Additive-change rule and existing screens. |
| A-04 | "No data yet" is a UI and report state, not a zero. Where a figure cannot be computed, the API returns `null`/`available: false` and the UI says "No data yet". | Never invent numbers. |
| A-05 | HR period locks will be additive and default to unlocked, so existing payroll and attendance rows continue to behave exactly as now. | Existing data must not be sacrificed. |
| A-06 | Real e-mail remains disabled. Notification e-mails, if added, go through the existing test-mode mailer and are verified by inspecting the delivery record, not an inbox. | Standing instruction. |

---

## 10. Bottom line

The baseline is healthy: the suite passes, the test database is built from Alembic head,
every API route is guarded, and no TODO/FIXME or fabricated business data sits in
production code. Schema parity between the live database and the models (Alembic
`check`) has **not** been verified in Phase 1 and is a Phase 3 checklist item. The
product is nevertheless **not ready** to be called complete against the brief:

1. HR is broad but shallow in exactly the areas the brief names: dashboard, self-service,
   bulk operations, documents, letters, notifications, locks, statutory payroll and
   confidentiality enforcement.
2. Three high/medium confidentiality defects (S-01 to S-03) let non-HR roles read bank/ID
   data, salary structures and net payroll totals.
3. The documents the brief asks for as deliverables (BRD, feature inventory, traceability
   matrix, HR role matrix, verification report) do not exist yet.
4. Several modules (leads, billing, notes, suppliers, payments) have no dedicated tests,
   which is why Phase 3 must exercise every endpoint rather than trust the 169-test total.

Phase 2 starts with the security fixes, then the HR schema (migration with a tested
downgrade), then dashboard/list/profile/attendance/leave/payroll/outputs, each with tests
and a commit. Phase 3 re-runs everything above and records evidence per checklist item.
