# Requirements Traceability Matrix

Date: 1 November 2026
Branch: `feature/scheduled-reports`
Baseline: Alembic `0015_statutory_heads`, 232 API path/method pairs, 230 passing tests.

## 1. Why this matrix is reconstructed

There is no Business Requirements Document, user-story backlog or signed scope
list in the repository. The requirements below are reconstructed from four
sources so that every implemented capability has a stated origin and a proof:

| Source code | Where it comes from |
|---|---|
| **BRIEF** | The task brief: audit the whole project, upgrade HR, then verify everything, with the five rules quoted in §3. |
| **AUDIT** | Findings in [`PROJECT_AUDIT.md`](PROJECT_AUDIT.md) and [`STAGE1_REAUDIT.md`](STAGE1_REAUDIT.md). |
| **HR** | [`HR_AUDIT.md`](HR_AUDIT.md): target HR behaviour and the defects found. |
| **REG** | The 18-module register in `app/core/module_register.py`, served at `GET /api/modules`. |
| **IMPL** | A capability that shipped and is visible in the UI/API; traced so it is not orphaned. |

An item marked **MET** has a passing test or an executed live check named in the
evidence column. Reading the code is not sufficient: items proven only by code
are **PARTIAL** and say so. Every requirement that is not met is listed in §5.

## 2. Status summary

| Status | Count | Meaning |
|---|---:|---|
| MET | 70 | Exercised by a test or a live check, as cited. |
| MET (test mode) | 1 | Works end-to-end but delivery is deliberately redirected. |
| PARTIAL | 9 | Works with the stated limitation; no dedicated test or an unrun path. |
| NOT VERIFIED | 2 | Exists but was not executed (destructive or environment-bound). |
| NOT BUILT | 3 | In scope of the audit, not implemented. |
| **Total requirements** | **85** | 12 governing + 73 functional. |

A feature can be MET while a related capability is NOT BUILT; for example
payroll preparation is MET while payroll posting to the ledger is not built
(G-01). The two statements are not in conflict.

## 3. Governing requirements (from the brief and standing rules)

| ID | Requirement | Source | Implementation / evidence | Status |
|---|---|---|---|---|
| R-01 | Audit the whole project before changing it | BRIEF | `docs/PROJECT_AUDIT.md`, `docs/STAGE1_REAUDIT.md`, `HR_AUDIT.md` | MET |
| R-02 | Upgrade HR: dashboard, easy operation, presentable output, server-side controls, audit, locks, masking | BRIEF | `app/api/hr.py`, `app/services/hr*.py`, `static/js/app.js`; 69 HR test functions; §4.7 | MET |
| R-03 | Verify the whole project with real commands and outputs | BRIEF | `docs/VERIFICATION_REPORT.md`; 230/230 tests; 75-route live smoke | MET |
| R-04 | Never invent data or numbers; show "No data yet" and list it as a gap | BRIEF | D-12; `test_reports_say_no_data_yet_instead_of_zeroes`, `test_missing_expenses_and_profit_are_gaps_not_zeroes`, `test_dashboard_defaults_to_this_month_and_reports_no_data_as_null` | MET |
| R-05 | Additive changes; every schema change has a migration and rollback; no broken screens, routes, permissions or reports | BRIEF | `alembic/versions/0001`–`0015`; upgrade→downgrade→upgrade round-trip; full suite | MET |
| R-06 | Work on a new branch and take a database backup first | BRIEF | `feature/scheduled-reports`; `backup_restore_test.py` run 1 Nov 2026 | MET |
| R-07 | Check roles on the server; salary, bank, ID visible only to Administrator, MD and allowed HR roles | BRIEF | [`HR_ROLES.md`](HR_ROLES.md); `test_hr_security.py`; live role matrix | MET |
| R-08 | No real e-mail; never print passwords or keys | BRIEF | test-mode mailer (`mode: test`, `send_enabled: false`); secret scan §13 of the verification report | MET |
| R-09 | Do not mark anything done unless it was run; otherwise write "Not verified" and why | BRIEF | `VERIFICATION_REPORT.md` §14 | MET |
| R-10 | Provide a feature inventory and a requirements traceability matrix | BRIEF | [`FEATURE_INVENTORY.md`](FEATURE_INVENTORY.md) and this file | MET |
| R-11 | Record decisions and assumptions | BRIEF | [`DECISIONS.md`](DECISIONS.md) D-01–D-24, Q-01–Q-06 | MET |
| R-12 | Update the module register, permission matrix and stale user manual | BRIEF | `module_register.py` (17 counted/17 working); [`permissions-matrix.md`](permissions-matrix.md); [`user-manual/`](user-manual/) | MET |

## 4. Functional requirements

### 4.1 Access and administration

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-13 | Sign in, sign out, session revocation | REG MOD-01 | `/api/auth/*`; `app/core/rbac.py` | `test_smoke.py`, `test_authz.py` | MET |
| R-14 | Force a password change before any data access | AUDIT | blocking screen; `ALLOW_WHILE_MUST_CHANGE` | `test_authz.py::test_forced_password_change_gates_data_and_revokes_the_old_token` | MET |
| R-15 | Lock an account after repeated failures | AUDIT | `app/services/lockout.py` | code read; no automated test | PARTIAL |
| R-16 | 44-key permission catalogue, database-resolved per request, custom roles | REG MOD-01/MOD-10 | `app/core/permissions.py`, `app/api/roles.py` | `test_authz.py`, `test_roles_parity.py` | MET |
| R-17 | Administrator-only actions by role, not by key alone | AUDIT | `require_admin`, `is_admin` | `test_approvals.py`, `test_authz.py` | MET |
| R-18 | Audit trail with actor, action, record and changes | REG MOD-10 | `/api/audit`; `app/services/audit.py` | live smoke; audit assertions in HR/approval tests | MET |
| R-19 | User create/disable/reset and secondary password | REG MOD-10 | `/api/users`, `/api/admin` | `test_authz.py` (deactivation, gate) | PARTIAL — reset not run |
| R-20 | Employee ↔ login link, one login per employee | REG MOD-10 | `/api/users`, `/api/hr/employees` | `test_hr.py::test_employee_login_link_is_visible_to_both_screens` | MET |
| R-21 | Database reset behind a secondary password | AUDIT | `/api/db/reset` | code read; destructive, not run | NOT VERIFIED |

### 4.2 Masters

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-22 | Products with unique SKU, valid prices, HSN | REG MOD-02 | `/api/products` | `test_products.py` | MET |
| R-23 | GST rates, union-territory handling, discount slabs | REG MOD-12 | `/api/tax`, `/api/discount-slabs` | live smoke; `test_products.py` (HSN) | MET |
| R-24 | Supplier master with GSTIN/PAN checks and second-person bank change | REG MOD-11 | `/api/suppliers` | live smoke; no dedicated test | PARTIAL |
| R-25 | Distributors, credit limits, block/unblock | REG MOD-06 | `/api/distributors` | `test_approvals.py`; live | MET |
| R-26 | Customer records used by sales orders | IMPL | sales-order drawer | live smoke | MET |
| R-27 | Warehouses and capacity | REG MOD-05 | `/api/warehouses` | `test_capacity.py` | MET |

### 4.3 Purchasing and inventory

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-28 | Purchase orders, cost-less lines need a remark | REG MOD-04 | `/api/purchase-orders` | `test_purchase_orders.py` | MET |
| R-29 | Goods receipts and part receipts | REG MOD-04 | `/api/purchase-orders/*/receipts` | `test_capacity.py`; live | MET |
| R-30 | Capacity check and audited Administrator override | AUDIT | GRN path | `test_capacity.py` | MET |
| R-31 | Stock ledger; negative stock refused; batch/FEFO | REG MOD-03 | `app/services/inventory.py` | `test_report_reconciliation.py`; `test_capacity.py` | MET |
| R-32 | Warehouse utilisation reconciles with batches | AUDIT | inventory report | `test_capacity.py` | MET |

### 4.4 Sales, billing and printing

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-33 | Leads, one owner, follow-ups, overdue flags | REG MOD-07 | `/api/leads` | live smoke | PARTIAL — no dedicated test |
| R-34 | Sales orders with stock and credit checks | REG MOD-05 | `/api/sales-orders` | live smoke; dashboard reconciliation | PARTIAL — no dedicated test |
| R-35 | Credit-limit request decided by the Administrator, never self | REG MOD-06 | `/api/approvals` | `test_approvals.py` | MET |
| R-36 | Dispatch chooses the warehouse and reports stock | REG MOD-05 | `/api/sales-orders/*/dispatch` | `test_capacity.py` | MET |
| R-37 | Tax invoices from dispatch, consecutive numbers | REG MOD-13 | `/api/invoices` | live smoke; PDF extraction | PARTIAL — no dedicated test |
| R-38 | Credit and debit notes | REG MOD-13 | `/api/credit-notes`, `/api/debit-notes` | live smoke | PARTIAL — no dedicated test |
| R-39 | Post-billing change needs a second Administrator | AUDIT | `/api/invoices/{id}/movement` | `test_approvals.py` | MET |
| R-40 | Secure PDFs with hash, print log, verification, pagination | REG MOD-13 | `/api/print`, `app/services/document_pdf.py` | `test_document_layout.py`; live PDFs | MET |
| R-41 | No edit after issue | REG MOD-13 | invoice/note services; only the movement patch is allowed | live smoke; `test_approvals.py` covers the movement gate, not immutability itself | PARTIAL — code-enforced, no dedicated test |

### 4.5 Accounts

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-42 | Distributor and supplier ledgers | REG MOD-14 | `/api/accounts/ledger` | `test_report_reconciliation.py` | MET |
| R-43 | Receipts and payments allocated to a document | REG MOD-14 | `/api/accounts` | live smoke; M-02 documents the required link | PARTIAL — no dedicated test |
| R-44 | Outstanding and four-bucket ageing | REG MOD-14 | `/api/accounts/receivables` | `test_report_reconciliation.py` | MET |
| R-45 | GST register and trial balance | REG MOD-14 | `/api/accounts/gst-register`, `/trial-balance` | `test_report_reconciliation.py` | MET |
| R-46 | Accounts dashboard, month/region comparison, report pack | REG MOD-17 | `/api/accounts/report`, `/compare` | `test_accounts_reports.py` | MET |
| R-47 | Accounts block in scheduled e-mail | REG MOD-17 | `app/services/report_packs.py` | `test_accounts_reports.py` | MET |
| R-48 | Period lock, journals, expenses, bank reconciliation | AUDIT | — | not implemented | NOT BUILT |

### 4.6 Reports and dashboard

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-49 | Report catalogue, per-report permission, paging/sorting | REG MOD-08 | `/api/reports` | `test_reports.py` | MET |
| R-50 | CSV/PDF export gated by `report:export` and audited | REG MOD-08 | `/api/reports/{key}/export` | `test_reports.py` | MET |
| R-51 | Reconciliation checks on financial reports | REG MOD-08 | `app/services/reports.py` | `test_report_reconciliation.py` | MET |
| R-52 | Overview KPIs, search, activity, system health | REG MOD-08 | `/api/dashboard` | `test_dashboard.py`, `test_dashboard_phase2.py` | MET |
| R-53 | Period selector, permission-masked sections, drill-downs | AUDIT | `/api/dashboard`, `/expiry`, `/activity` | `test_dashboard_phase2.py` | MET |
| R-54 | Sales/purchase series and approvals card | AUDIT | `/api/dashboard` | `test_dashboard_v2.py` | MET |
| R-55 | Month-to-date, projection, 12-month trend, breakdowns | AUDIT | `/api/dashboard/compare` | `test_dashboard_compare.py` | MET |
| R-56 | State geography from frozen invoice snapshots | AUDIT | `/api/dashboard/geo` | `test_dashboard_geo.py` | MET |
| R-57 | Phase 3 insight cards reconcile with their registers | AUDIT | `/api/dashboard` | `test_dashboard_phase3.py` | MET |
| R-58 | Module register and migration-head health | AUDIT | `module_register.py`, `_health` | `test_module_status.py`, `test_dashboard_phase2.py` | MET |

### 4.7 HR

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-59 | HR dashboard with scoped figures and honest gaps | HR | `/api/hr/dashboard` | `test_hr_dashboard.py` | MET |
| R-60 | Directory, filters, saved views, bulk CSV import/undo | HR | `/api/hr/employees*` | `test_hr_directory.py` | MET |
| R-61 | Profile tabs, photo, documents, assets, history | HR | `/api/hr/employees/{id}/*` | `test_hr_profile.py` | MET |
| R-62 | Bank/ID masking and refusal of unauthorised writes | BRIEF/HR | `_employee_dict`, `_refuse_confidential_write` | `test_hr_security.py`, `test_hr_directory.py` | MET |
| R-63 | Team scope: manager chain, staff self, unlinked sees nothing | HR | `scoped_employee_ids`, `_employee_or_403` | 5 tests across security/leave/attendance/dashboard | MET |
| R-64 | Check-in/out, geofence, manual and bulk attendance, monthly calendar | HR | `/api/hr/attendance*` | `test_hr.py`, `test_hr_attendance.py` | MET |
| R-65 | Attendance and payroll period locks with Administrator override | HR | `/api/hr/period-locks` | `test_hr_attendance.py` | MET |
| R-66 | Leave types, working-day counting, balances, carry-forward, approvals | HR | `/api/hr/leave*` | `test_hr_leave.py`, `test_hr.py` | MET |
| R-67 | On-duty requests and approvals | HR | `/api/hr/od` | `test_hr.py` | MET |
| R-68 | Salary components and structures | HR | `/api/hr/salary/*` | `test_hr.py` | MET |
| R-69 | Payroll prepare, submit, process, pay; no self-approval | HR | `/api/hr/payroll/periods/*` | `test_hr.py` | MET |
| R-70 | Statutory summary from configured heads only | HR | `/api/hr/payroll/periods/{id}/statutory` | `test_hr_payroll_outputs.py` | MET |
| R-71 | Bank file with two rights, released periods, masked preview | HR | `/api/hr/payroll/periods/{id}/bank-file` | `test_hr_payroll_outputs.py` | MET |
| R-72 | Payslips: own after release, any with the right | HR | `/api/hr/me/payslips`, `/entries/{id}/slip` | `test_hr_payroll_outputs.py` | MET |
| R-73 | Letters, ID cards, attendance sheet, leave statement | HR | `/api/hr/outputs/*` | `test_hr_documents.py` | MET |
| R-74 | HR reports including confidential cost | HR | `/api/hr/reports`, `/api/reports/hr_*` | `test_hr_reports.py`, `test_reports.py` | MET |
| R-75 | In-app notifications, announcements, once-a-day digest | HR | `/api/hr/notifications`, `/announcements` | `test_hr_notifications.py` | MET |
| R-76 | Scheduled HR pack without salary amounts | HR | `app/services/hr_pack.py` | `test_hr_pack.py` | MET (test mode) |
| R-77 | Overtime, salary revision and reimbursement approvals | HR | labels only | no handler | NOT BUILT |
| R-78 | Payroll posted to the accounting ledger | IMPL | — | D-17; no posting code | NOT BUILT |

### 4.8 Scheduled e-mail and platform

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-79 | Recipients, groups, schedule maths with holidays/cron | REG MOD-18 | `/api/email-reports/*`; `app/services/schedule.py` | `test_email_api.py`, `test_email_schedules.py` | MET |
| R-80 | HTML/text packs, attachments, preview | REG MOD-18 | `app/services/report_packs.py` | `test_email_reports.py` | MET |
| R-81 | DB-backed worker with claims, retries and delivery log | REG MOD-18 | `app/services/email_worker.py` | `test_email_reports.py` | MET |
| R-82 | Test mode redirects every message; live mode fails closed without approval | BRIEF | mailer guardrails | `test_email_api.py`, `test_email_reports.py` | MET |
| R-83 | Live delivery to a real inbox | BRIEF | — | no SMTP/recipient approval | NOT VERIFIED |
| R-84 | Backup, restore into scratch DB and reconcile | REG MOD-09 | `backup_restore_test.py` | executed: 63 tables/575 rows, 26 reports, 0 unreconciled | MET |
| R-85 | Health endpoint and honest module register | REG | `/api/health`, `/api/modules` | `test_dashboard_phase2.py`, `test_module_status.py` | MET |

## 5. Gaps, blockers and open items

| ID | Item | Effect | Owner / next step |
|---|---|---|---|
| G-01 | Payroll is not posted to the ledger (R-78) | Salary cost does not appear in the trial balance or ledgers | Product owner to approve a salary-to-ledger mapping (D-17). |
| G-02 | Accounts period lock, journals, expenses, bank reconciliation (R-48) | Accounts is ledger + ageing + GST + TB, not a full accounting suite | Scope decision; not attempted without authorisation. |
| G-03 | Overtime / salary-revision / reimbursement approvals (R-77) | Labels exist; requests are not raised or decided | Phase 1 gap; needs workflow design. |
| G-04 | Multi-level approval workflows | The table exists; no application code reads it | Design + implementation. |
| G-05 | Purchase-order printing | POs cannot be printed as a secure document | Add a PDF builder only if required. |
| G-06 | E-invoice / e-way bill portal (MOD-15) | Conditional on turnover; not built | Keep conditional. |
| G-07 | No dedicated test file for Billing and Leads | Live smoke only; regressions could slip through | Add tests before the next billing change. |
| G-08 | Lockout has no automated test | Behaviour read in code only | Add a login-failure test. |
| G-09 | No live e-mail delivery | Test mode only; SMTP/recipients not approved | Approve SMTP and recipient list (D-09/D-19). |
| G-10 | Physical device, screen reader, load and deployment not verified | Only headless Chrome and local `127.0.0.1` | Run on the target environment when one exists. |
| G-11 | `APP_ENV=production` while using the development database | Secure-cookie and db-reset guard behaviour depends on the label | Correct the environment file before deployment. |
| G-12 | UI/API mismatches M-02–M-11 remain open | Some server features lack a browser control, e.g. unallocated receipt option | Tracked in `FRONTEND_BACKEND_FIELD_MAPPING.md`. |
| G-13 | Supplier bank-change flow has no dedicated test | Live smoke only | Add a two-person approval test. |
| G-14 | Database reset and secondary password were not executed | Destructive by design; only the gate was read | Test against a disposable database with explicit approval. |

## 6. How this matrix was checked

| Check | Command / source | Result |
|---|---|---|
| Route count | FastAPI `app.routes` | 232 API pairs; 92 HR + 4 legacy employee |
| Test count | `python -m pytest -q` | 230 passed |
| Schema | `alembic current` / `heads` | `0015_statutory_heads` |
| Migration round-trip | upgrade → downgrade base → upgrade | pass (verification report §3) |
| Live smoke | 75 GET routes as Administrator | all 200 |
| Roles | read-only `roles` query + live matrix | 44 keys for Administrator; HR role sets as documented |
| Backup/restore | `python backup_restore_test.py` | PASS, 26 reports, 0 unreconciled |
| Secret scan | repository scan reported in §13 of the verification report | no live credential or key found |

## 7. Maintenance rule

A change to a route, screen, permission, report or workflow must update the
matching row here and in [`FEATURE_INVENTORY.md`](FEATURE_INVENTORY.md) in the
same commit. A requirement may move to **MET** only with a named test or an
executed command in the evidence column. If a feature is removed, mark the row
**WITHDRAWN** and keep the history rather than deleting it.
