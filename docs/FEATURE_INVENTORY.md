# Feature Inventory

Date: 1 November 2026
Branch: `feature/scheduled-reports`
Purpose: the single list of what the application does, where it does it, who may
use it, and what proves it works. It complements the module register served at
`GET /api/modules` (`app/core/module_register.py`) and the evidence in
[`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md).

**Status vocabulary**

| Status | Meaning |
|---|---|
| **VERIFIED** | An automated test exercises the feature and passes; where marked *(live)* a read-only live check also passed. |
| **VERIFIED (live)** | Exercised against the running application; no dedicated automated test file. |
| **PARTIAL** | Works, with the limitation stated. |
| **MISSING** | The server supports it but the browser offers no control. |
| **NOT VERIFIED** | Not run, with the reason stated. |
| **NOT BUILT** | Planned or conditional; nothing to exercise. |

Route counts are from the running app: **232 API path/method pairs**, of which
92 are HR and 4 are the legacy employee endpoints.

## 1. Module register

`GET /api/modules` serves 18 entries: 17 counted, 17 working, 1 conditional
(MOD-15). The Overview "System health" card renders this live; it is not a
hand-typed number.

| ID | Module | Status |
|---|---|---|
| MOD-01 | Sign-in and roles | Working |
| MOD-02 | Products and SKUs | Working |
| MOD-03 | Stock ledger | Working |
| MOD-04 | Purchase orders and receipts | Working |
| MOD-05 | Sales orders and dispatch | Working |
| MOD-06 | Credit control and approvals | Working |
| MOD-07 | Leads and follow-ups | Working |
| MOD-08 | Reports and exports | Working |
| MOD-09 | Backup and restore test | Working |
| MOD-10 | Users, rights and employees | Working |
| MOD-11 | Supplier management | Working |
| MOD-12 | GST tax and discount slabs | Working |
| MOD-13 | Billing and document printing | Working |
| MOD-14 | Accounts | Working |
| MOD-15 | E-invoice and e-way bill | Conditional — not built |
| MOD-16 | HR management, attendance and payroll | Working |
| MOD-17 | Accounts reporting and comparison | Working |
| MOD-18 | Scheduled e-mail reports | Working (test mode) |

## 2. Identity, access and administration

| # | Feature | Screen / API | Gate | Evidence | Status |
|---|---|---|---|---|---|
| F-01 | Sign in, sign out, session cookie | `/ui` sign-in; `/api/auth/login`, `/logout` | credentials | `test_smoke.py`; live | VERIFIED |
| F-02 | Forced first-password change | Blocking screen in `app.js` | `must_change_password` | `test_authz.py` | VERIFIED |
| F-03 | Lockout after repeated failures | `/api/auth/login` | 5 failures → 15 minutes | code read (`app/services/lockout.py`); no dedicated test | PARTIAL — not exercised |
| F-04 | Server-side permission checks | every `/api` route | 44-key catalogue | `test_authz.py`, `test_roles_parity.py` | VERIFIED |
| F-05 | Role editor and custom roles | Settings → Users and rights; `/api/roles` | `user:manage` | `test_roles_parity.py`; live | VERIFIED |
| F-06 | User create, disable, password reset | Settings → Users; `/api/users` | `user:manage` | `test_authz.py` (deactivation) | VERIFIED |
| F-07 | Employee ↔ login link | Users and HR profile | `user:manage`, `hr:read` | `test_hr.py` | VERIFIED |
| F-08 | Audit trail viewer and export | Settings → Audit; `/api/audit` | `audit:read` | live smoke | VERIFIED (live) |
| F-09 | Secondary password on user management | `/api/admin` | `user:manage` + secondary | `test_authz.py` (gate), code | PARTIAL — destructive reset not run |
| F-10 | Database reset | Settings → Database; `/api/db/reset` | `db:reset` + secondary password | `backup_restore_test.py` exercises backup/restore, not reset | NOT RUN — destructive by design |

## 3. Masters

| # | Feature | Screen / API | Gate | Evidence | Status |
|---|---|---|---|---|---|
| F-11 | Products and SKUs | Products; `/api/products` | `product:read/write` | `test_products.py` | VERIFIED |
| F-12 | Product list paging and search | Products | `product:read` | `test_products.py` | VERIFIED |
| F-13 | HSN validation | Products | `product:write` | `test_products.py` | VERIFIED |
| F-14 | GST rate master and slabs | Settings → Taxes; `/api/tax` | `tax:read/write` | live smoke | VERIFIED (live) |
| F-15 | Discount slabs | Settings → Discounts; `/api/discount-slabs` | `tax:read/write` | live smoke | VERIFIED (live) |
| F-16 | Suppliers, GSTIN/PAN checks | Suppliers; `/api/suppliers` | `supplier:read/write` | live smoke | VERIFIED (live) |
| F-17 | Supplier bank change, second person | Supplier drawer; `/api/suppliers/*/bank-change` | `supplier:bank`, approval | live smoke; no dedicated test | PARTIAL |
| F-18 | Distributors and credit limits | Distributors; `/api/distributors` | `distributor:write`, `credit:manage` | `test_approvals.py` (credit decision); live | VERIFIED |
| F-19 | Customers | Customers; sales-order drawer | `sales:read` | live smoke | VERIFIED (live) |
| F-20 | Warehouses and capacity | Inventory; `/api/warehouses` | `stock:read/write` | `test_capacity.py` | VERIFIED |

## 4. Purchasing and inventory

| # | Feature | Screen / API | Gate | Evidence | Status |
|---|---|---|---|---|---|
| F-21 | Purchase orders | Purchases; `/api/purchase-orders` | `stock:read/write` | `test_purchase_orders.py` | VERIFIED |
| F-22 | Cost-less line needs a remark | PO drawer | `stock:write` | `test_purchase_orders.py` | VERIFIED |
| F-23 | Goods receipts, part receipts | Purchases → receive | `stock:write` | `test_capacity.py`; live | VERIFIED |
| F-24 | Capacity check and Administrator override | GRN | `stock:write`, admin override | `test_capacity.py` | VERIFIED |
| F-25 | Stock ledger and movements | Inventory | `stock:read` | `test_report_reconciliation.py` | VERIFIED |
| F-26 | FEFO batch movements and expiry | Inventory, dispatch | `stock:read/write` | `test_dashboard.py`, `test_capacity.py` | VERIFIED |
| F-27 | Warehouse utilisation report | Inventory, dashboard | `stock:read` | `test_capacity.py` | VERIFIED |

## 5. Sales, billing and printing

| # | Feature | Screen / API | Gate | Evidence | Status |
|---|---|---|---|---|---|
| F-28 | Leads, owners, follow-ups | Leads; `/api/leads` | `lead:read/write/assign` | live smoke | VERIFIED (live) |
| F-29 | Sales orders | Sales orders; `/api/sales-orders` | `sales:read/write` | live smoke; dashboard reconciliation tests | PARTIAL — no dedicated test file |
| F-30 | Credit check at submit and dispatch | Sales order drawer | `sales:write`, approval | `test_approvals.py` | VERIFIED |
| F-31 | Dispatch, warehouse chosen at dispatch | Dispatch | `dispatch:write` | `test_capacity.py`; live | VERIFIED |
| F-32 | Tax invoices from dispatch | Billing; `/api/invoices` | `sales:read`, `invoice:write` | live smoke; PDF check | VERIFIED (live) |
| F-33 | Credit and debit notes | Billing; `/api/credit-notes`, `/api/debit-notes` | `note:write` | live smoke | PARTIAL — no dedicated test file |
| F-34 | Post-billing invoice edit | `/api/invoices/{id}/movement` | `invoice:edit_post_billing` + admin | `test_approvals.py` | VERIFIED |
| F-35 | Invoice cancellation | Billing | `invoice:cancel` | live smoke | VERIFIED (live) |
| F-36 | Secure PDFs, SHA-256, print log, verify | Print; `/api/print` | `print:document` | live PDF extraction; `test_document_layout.py` | VERIFIED |
| F-37 | Signatory alignment on PDFs | Invoice PDF | — | `test_document_layout.py` | VERIFIED |

## 6. Accounts

| # | Feature | Screen / API | Gate | Evidence | Status |
|---|---|---|---|---|---|
| F-38 | Distributor and supplier ledgers | Accounts; `/api/accounts/ledger` | `accounts:read` | `test_report_reconciliation.py` | VERIFIED |
| F-39 | Receipts and payments | Accounts drawer | `accounts:write` | live smoke | VERIFIED (live) |
| F-40 | Outstanding and ageing (four buckets) | Accounts | `accounts:read` | `test_report_reconciliation.py` | VERIFIED |
| F-41 | GST register | Accounts | `accounts:read` | `test_report_reconciliation.py` | VERIFIED |
| F-42 | Trial balance | Accounts | `accounts:read` | `test_report_reconciliation.py` | VERIFIED |
| F-43 | Accounts dashboard and report | `/api/accounts/report`; Accounts tab | `accounts:reports` | `test_accounts_reports.py` | VERIFIED |
| F-44 | Month and region comparison | Accounts → Compare | `accounts:reports` | `test_accounts_reports.py` | VERIFIED |
| F-45 | Accounts e-mail block | Scheduled reports | `email:manage` | `test_accounts_reports.py` | VERIFIED |
| F-46 | Period lock, journals, expenses, bank reconciliation | — | — | Phase 1 gap | NOT BUILT |

## 7. Reports and dashboard

| # | Feature | Screen / API | Gate | Evidence | Status |
|---|---|---|---|---|---|
| F-47 | Report catalogue and permission filtering | Reports; `/api/reports` | per-report view key | `test_reports.py` | VERIFIED |
| F-48 | Paging, sorting, filters | Reports | per-report key | `test_reports.py` | VERIFIED |
| F-49 | CSV/PDF export and audit | Reports | `report:export` | `test_reports.py` | VERIFIED |
| F-50 | Reconciliation checks on reports | Reports | per-report key | `test_report_reconciliation.py` | VERIFIED |
| F-51 | Empty report says "No data yet" | Reports | per-report key | `test_reports.py` | VERIFIED |
| F-52 | Overview KPIs, search, activity, health | Overview; `/api/dashboard` | `require_login` + section keys | `test_dashboard.py` | VERIFIED |
| F-53 | Period selector and permission masking | Overview | section keys | `test_dashboard_phase2.py` | VERIFIED |
| F-54 | Sales/purchase series, approvals card | Overview | `sales:read`, `stock:read` | `test_dashboard_v2.py` | VERIFIED |
| F-55 | Month-to-date, projection, trend, breakdowns | Overview → Compare | `sales:read` | `test_dashboard_compare.py` | VERIFIED |
| F-56 | State geography from invoice snapshots | Overview → Geography | `sales:read` | `test_dashboard_geo.py` | VERIFIED |
| F-57 | Phase 3 insight cards | Overview | section keys | `test_dashboard_phase3.py` | VERIFIED |
| F-58 | Module register and migration-head health | Overview → System health | logged in (`/api/dashboard`) | `test_dashboard_phase2.py`, `test_module_status.py` | VERIFIED |

## 8. HR

| # | Feature | Screen / API | Gate | Evidence | Status |
|---|---|---|---|---|---|
| F-59 | HR dashboard | HR; `/api/hr/dashboard` | `hr:read` | `test_hr_dashboard.py` | VERIFIED |
| F-60 | Employee directory, filters, saved views | HR → People | `hr:read` | `test_hr_directory.py` | VERIFIED |
| F-61 | Employee create/edit | HR → People | `hr:write` | `test_hr.py` | VERIFIED |
| F-62 | Bulk CSV import, preview, undo | HR → People → Import | `hr:write` | `test_hr_directory.py` | VERIFIED |
| F-63 | Profile tabs, history, photo | HR → Profile | `hr:read` (+ self) | `test_hr_profile.py` | VERIFIED |
| F-64 | Documents and assets | HR → Profile | `hr:read/write` | `test_hr_profile.py` | VERIFIED |
| F-65 | Bank/ID masking and write refusal | all HR reads | `hr:confidential`/payroll/self | `test_hr_security.py`, `test_hr_directory.py` | VERIFIED |
| F-66 | Team scoping (manager chain, self) | all HR data | scope helpers | `test_hr_security.py`, `test_hr_leave.py`, `test_hr_attendance.py` | VERIFIED |
| F-67 | Check-in/out with geofence | HR → Attendance | `hr:attendance_self` | `test_hr.py` | VERIFIED |
| F-68 | Manual and bulk attendance | HR → Attendance | `hr:attendance_manage` | `test_hr_attendance.py` | VERIFIED |
| F-69 | Monthly calendar and missing-day gaps | HR → Attendance | `hr:read`/self | `test_hr_attendance.py` | VERIFIED |
| F-70 | Attendance/payroll period locks | HR → Locks | `hr:write` / payroll | `test_hr_attendance.py` | VERIFIED |
| F-71 | Leave types, balances, carry-forward | HR → Leave | `hr:read`/`hr:write` | `test_hr_leave.py` | VERIFIED |
| F-72 | Leave applications and approvals | HR → Leave | `hr:attendance_self`, `hr:leave_approve` | `test_hr_leave.py`, `test_hr.py` | VERIFIED |
| F-73 | On-duty requests | HR → OD | `hr:attendance_self` | `test_hr.py` (approval flow) | VERIFIED |
| F-74 | Salary components and structures | HR → Payroll | `hr:payroll_prepare` (+`hr:write`) | `test_hr.py` | VERIFIED |
| F-75 | Payroll prepare → submit → process → pay | HR → Payroll | payroll prepare/approve | `test_hr.py` | VERIFIED |
| F-76 | Statutory summary from configured heads | HR → Payroll | `hr:payroll_prepare` | `test_hr_payroll_outputs.py` | VERIFIED |
| F-77 | Bank file, preview masking, reconciliation | HR → Payroll | payroll + confidential | `test_hr_payroll_outputs.py` | VERIFIED |
| F-78 | Payslips (own, after release; any with right) | HR → Payroll / My payslips | `hr:confidential` / own | `test_hr_payroll_outputs.py` | VERIFIED |
| F-79 | Letters, ID cards | HR → Outputs | `hr:read`/self | `test_hr_documents.py` | VERIFIED |
| F-80 | Attendance sheet and leave statement PDFs | HR → Outputs | `hr:read`/self | `test_hr_documents.py` | VERIFIED |
| F-81 | HR reports (headcount, attendance, leave, cost) | Reports → HR | `hr:reports` (+confidential) | `test_hr_reports.py`, `test_reports.py` | VERIFIED |
| F-82 | Notifications, announcements, digest | HR / bell | `hr:write` to send | `test_hr_notifications.py` | VERIFIED |
| F-83 | Scheduled HR pack (no salary) | Scheduled reports | `email:manage` | `test_hr_pack.py` | VERIFIED (test mode) |
| F-84 | Overtime, salary revision, reimbursement approvals | labels only | — | no handler | NOT BUILT |
| F-85 | Payroll posted to the accounting ledger | — | — | no posting code (D-17) | NOT BUILT |

## 9. Scheduled e-mail and platform

| # | Feature | Screen / API | Gate | Evidence | Status |
|---|---|---|---|---|---|
| F-86 | Recipients and groups | Scheduled reports; `/api/email-reports` | `email:manage` | `test_email_api.py` | VERIFIED |
| F-87 | Schedule maths (daily, weekly, monthly, holidays, cron) | Scheduled reports | `email:manage` | `test_email_schedules.py` | VERIFIED |
| F-88 | HTML/text packs and attachments | Scheduled reports → Preview | `email:manage` | `test_email_reports.py` | VERIFIED |
| F-89 | DB-backed worker, retries, claims, delivery log | background worker | `email:manage` | `test_email_reports.py` | VERIFIED |
| F-90 | Test-mode guardrails | status screen | `email:manage` | `test_email_api.py`, `test_email_reports.py` | VERIFIED |
| F-91 | SMTP settings and test composer (encrypted password, To/CC, message types, dry run, outbox) | Settings → Email and SMTP; `/api/email-settings` | `email:manage` | `test_email_settings.py`; local sink run | VERIFIED |
| F-92 | Live e-mail delivery | — | SMTP approval | none configured | NOT VERIFIED |
| F-93 | Backup, restore and reconciliation | `backup_restore_test.py` | operator | executed 1 Nov 2026: 63 tables, 575 rows, 26 reports, 0 unreconciled | VERIFIED |
| F-94 | Health endpoint | `/api/health` | none | `test_dashboard_phase2.py` | VERIFIED |
| F-95 | Roles & Permissions screen (roles, tree editor, access-control summary) | `#/roles`; `/api/roles` | `user:manage` | `test_permission_tree.py`; browser check | VERIFIED |
| F-96 | Parent-child permission rules, browser and server | role tree editor; `effective_permissions` | `user:manage` | `test_permission_tree.py` (11 tests) | VERIFIED |
| F-97 | Central module On/Off switches, Administrator only | `#/roles` → Feature availability; `/api/features` | Administrator role | `test_feature_switches.py` (10 tests) | VERIFIED |
| F-98 | Logins and employee master (separate from roles) | `#/users` | `user:manage` / `employee:*` | `test_authz.py`; browser check | VERIFIED |

## 10. Features that are deliberately absent

| Item | Why | Source |
|---|---|---|
| PO printing | No PDF builder for purchase orders | Phase 1 audit |
| E-invoice / e-way bill portal | MOD-15 conditional on turnover | module register |
| Excel import | CSV only in this phase | D-10 |
| Real e-mail | SMTP and recipients not approved | D-09, D-19 |
| Payroll journal | No authorised salary-to-ledger mapping | D-17 |
| Multi-level approval workflows | Table exists, no application code uses it | Phase 1 audit |
| Physical-device and screen-reader verification | No device or tooling available | `VERIFICATION_REPORT.md` §14 |

## 11. How to keep this current

1. Add a route, screen or report → add a row here and a test name in the
   evidence column in the same change.
2. Change a permission → update `docs/permissions-matrix.md` and the gate in
   this table.
3. Change a status → cite the command or test that proves it; never move a row
   to VERIFIED on the strength of reading the code.
