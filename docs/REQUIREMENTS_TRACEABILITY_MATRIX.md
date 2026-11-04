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
| MET | 123 | Exercised by a test or a live check, as cited. Includes the one test-mode delivery row and rows whose status cell qualifies the evidence (API only, browser only). |
| PARTIAL | 8 | Works with the stated limitation; no dedicated test or an unrun path. |
| NOT VERIFIED | 2 | Exists but was not executed (destructive or environment-bound). |
| NOT BUILT | 2 | In scope of the audit, not implemented. |
| **Total requirements** | **135** | 12 governing + 123 functional. |

A feature can be MET while a related capability is NOT BUILT; for example
payroll preparation is MET while payroll posting to the ledger is not built
(G-01). The two statements are not in conflict.

## 3. Governing requirements (from the brief and standing rules)

| ID | Requirement | Source | Implementation / evidence | Status |
|---|---|---|---|---|
| R-01 | Audit the whole project before changing it | BRIEF | `docs/PROJECT_AUDIT.md`, `docs/STAGE1_REAUDIT.md`, `HR_AUDIT.md` | MET |
| R-02 | Upgrade HR: dashboard, easy operation, presentable output, server-side controls, audit, locks, masking | BRIEF | `app/api/hr.py`, `app/services/hr*.py`, `static/js/app.js`; 76 HR test functions in 13 files; §4.7 | MET |
| R-03 | Verify the whole project with real commands and outputs | BRIEF | `docs/VERIFICATION_REPORT.md`; 268/268 tests; 75-route live smoke plus the 245-pair API count | MET |
| R-04 | Never invent data or numbers; show "No data yet" and list it as a gap | BRIEF | D-12; `test_reports_say_no_data_yet_instead_of_zeroes`, `test_missing_expenses_and_profit_are_gaps_not_zeroes`, `test_dashboard_defaults_to_this_month_and_reports_no_data_as_null` | MET |
| R-05 | Additive changes; every schema change has a migration and rollback; no broken screens, routes, permissions or reports | BRIEF | `alembic/versions/0001`–`0028`; upgrade→downgrade→upgrade round-trip; full suite | MET |
| R-06 | Work on a new branch and take a database backup first | BRIEF | `feature/hr-upgrade`; `backup_restore_test.py` run 1 Nov 2026 | MET |
| R-07 | Check roles on the server; salary, bank, ID visible only to Administrator, MD and allowed HR roles | BRIEF | [`HR_ROLES.md`](HR_ROLES.md); `test_hr_security.py`; live role matrix | MET |
| R-08 | No real e-mail; never print passwords or keys | BRIEF | test-mode mailer (`mode: test`, `send_enabled: false`); secret scan §13 of the verification report | MET |
| R-09 | Do not mark anything done unless it was run; otherwise write "Not verified" and why | BRIEF | `VERIFICATION_REPORT.md` §14 | MET |
| R-10 | Provide a feature inventory and a requirements traceability matrix | BRIEF | [`FEATURE_INVENTORY.md`](FEATURE_INVENTORY.md) and this file | MET |
| R-11 | Record decisions and assumptions | BRIEF | [`DECISIONS.md`](DECISIONS.md) D-01–D-32, Q-01–Q-06 | MET |
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
| R-131 | The password policy is enforced and the temporary password is generated on the server; the browser holds no policy, no generator and no password after the one-time display | BRIEF (new) | `validate_password`, `generate_temp_password`; `ChangePassword` validator; `/api/users` | `test_authz.py` (400 wrong current, 422 too-short, 400 unchanged, token revocation); code review of `app/api/users.py` | MET |
| R-132 | Administrator and Super Administrator accounts must present a 6-digit TOTP code (30-second step, no SMS/e-mail/network) after the password; the server issues no session before it, refuses a session without the `otp` claim, seals the secret, blocks replay, issues 10 single-use recovery codes and locks code entry after five failures; every other role is unchanged | BRIEF (new) | `app/services/totp.py`; `/api/auth/login`, `/2fa/setup`, `/2fa/confirm`, `/2fa/verify`, `/2fa/status`; migration `0029_totp` | `tests/test_totp.py` (8 tests); browser enrollment walk 3 Nov 2026; `docs/ADMIN_2FA.md` | MET (API and tests); migration `0029_totp` applied to the test and development databases, not to production |
| R-134 | The sign-in page's promotion banners, dated notices, three help-line boxes and two legal pages are managed by the Administrator from the database, not fixed in the frontend; an empty box shows "No data yet" and an unwritten legal page "Not published yet"; uploaded banner files are type- and size-checked and served only through the public image route; every write is Administrator-only | BRIEF (new) | `app/api/signin.py`; `app/models/signin.py`; Settings → Sign-in page in `app.js`; migration `0030_sign_in_content` | `tests/test_signin.py` (8 tests); browser walk 4 Nov 2026 at 1440/768/390 in both themes; `docs/VERIFICATION_REPORT.md` §27 | MET (API, tests and browser); migration `0030_sign_in_content` applied to the test and development databases (development upgraded 4 November 2026), not to production |
| R-135 | The workspace shell: a pinned Home tab, one tab per open screen with no duplicates, close current, close others, close all except Home, reopen, overflow, active-tab highlighting, unsaved-form warning, refresh and deep-link correctness; breadcrumbs that follow the real menu hierarchy and never bypass permissions; favourites, recent screens, keyboard navigation and palette screen search; no iframes, no duplicate screen implementations, existing hash routes and queries preserved; permissions still enforced by the backend | BRIEF (new) | `static/js/workspace.js`; tab/breadcrumb/favourite rendering in `static/js/app.js`; `static/index.html`; `static/css/styles.css`; `#/view/section?query` unchanged | `tests/js/workspace.test.cjs` 18 tests run by `tests/test_workspace_model.py`; browser walk 42/42, 227 API calls at 200, no page errors, expected 403s only during a deliberate role swap; `docs/VERIFICATION_REPORT.md` §30; screenshots `var/shots/wp2-tabs-*.png` | MET (tests and browser); favourites and recents are device-local until WP-4 |

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
| R-129 | Every credit and debit note can be opened from Billing and printed as a secure PDF; Open shows the note number, financial year, invoice, buyer when known, date, reason, returned-to-stock quantity for a credit, tax breakdown, lines and the print-log verification; Print issues the same logged, verifiable PDF as an invoice | BRIEF (new) | `noteDetail` and the notes table in `static/js/app.js`; `POST /api/print/{credit_note\|debit_note}/{id}`; list endpoints return `lines` and `invoice_number` | `tests/test_file_audit.py::test_a_credit_and_a_debit_note_can_be_opened_and_printed`; browser walk 3 Nov 2026 (open CN/2627/000001; debit-note print 200 `application/pdf`) | MET |

### 4.5 Accounts

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-42 | Distributor and supplier ledgers | REG MOD-14 | `/api/accounts/ledger` | `test_report_reconciliation.py` | MET |
| R-43 | Receipts and payments allocated to a document | REG MOD-14 | `/api/accounts`; `payment_allocations`; `app/services/advances.py` | `tests/test_accounts_advances.py` (8 tests); browser walk 3 Nov 2026 | MET |
| R-44 | Outstanding and four-bucket ageing | REG MOD-14 | `/api/accounts/receivables` | `test_report_reconciliation.py` | MET |
| R-45 | GST register and trial balance | REG MOD-14 | `/api/accounts/gst-register`, `/trial-balance` | `test_report_reconciliation.py` | MET |
| R-46 | Accounts dashboard, month/region comparison, report pack | REG MOD-17 | `/api/accounts/report`, `/compare` | `test_accounts_reports.py` | MET |
| R-47 | Accounts block in scheduled e-mail | REG MOD-17 | `app/services/report_packs.py` | `test_accounts_reports.py` | MET |
| R-48 | Period lock, journals, expenses, bank reconciliation | AUDIT | `hr_period_locks` scope `accounting`, `financial_year_closes`, `/api/expenses`, `/api/reports/profit_and_loss`, `/api/accounts/vouchers`, `/day-book`, `/bank-statements` | `test_expenses.py`, `test_profit_loss.py`, `test_accounts_reports.py`, `test_periods.py`, `test_ledger_and_bank_rec.py` | MET — expenses, P&L, month locks, the year close, vouchers/journal/day book and bank statement matching are built (GAP-A08/A09 closed 3 Nov 2026) |
| R-109 | A payroll month the reporting window cuts short is counted by each employee's working-day share and marked allocated; a month with no approved payroll is a gap, never an estimate | BRIEF (new) | `profit_loss._allocate`; `payroll.periods[].prorated`/`allocated`; D-36 | `test_profit_loss.py::test_cut_month_is_allocated_by_working_days_not_guessed`, `::test_payroll_gap_names_absent_and_unapproved_months` | MET |
| R-110 | Total expenses and Payroll (gross) show a provable partial total marked Partial with a fix link; net profit stays withheld until every input is complete | BRIEF (new) | `accounting.report()` rows; `renderAccPnl`; Overview `accounts.expenses_partial` | `test_accounts_reports.py`; `test_profit_loss.py`; `test_email_reports.py` | MET |
| R-111 | A payroll run names every active employee it skips and why, in the run result, the period screen and the audit entry | BRIEF (new) | `payroll.skipped_employees`; `get_period`/`prepare_payroll`; `hrPayrollOpen` | `test_hr.py` (prepare and register agree) | MET (API and tests); screen not browser-verified |
| R-112 | A completed financial year can be closed with a reason; dated documents (dispatch and invoice, receipts and payments, credit/debit notes, invoice cancellation, expenses, cost corrections, free-sample notes) are refused with HTTP 423; only the Administrator can reopen with a reason, both audited | BRIEF (new) | `financial_year_closes`; `app/services/periods.py`; `/api/accounts/financial-years`; "Financial years" panel on Accounts | `test_periods.py` (close, refusal, role, reopen, audit); screen not browser-verified | MET |
| R-113 | An invoice freezes the distributor's payment terms at issue and computes its due date; missing terms store NULL, not a guess, and a later master change cannot move an issued invoice | BRIEF (new) | `Invoice.payment_terms_days`/`due_date`; `invoice.create_invoice_for_order`; invoice drawer | `test_periods.py::test_invoice_snapshots_terms_and_due_date`, `::test_no_terms_means_no_due_date_not_an_invented_one` | MET |
| R-114 | Ageing reports each invoice's due date and days overdue and splits outstanding into overdue, due within 7 days, later and no due date, with the split summing to the total | BRIEF (new) | `ledger.ageing_rows` `due` block; ageing table columns; `#ageDue` note | `test_periods.py::test_ageing_splits_outstanding_by_due_date`; screen not browser-verified | MET |
| R-115 | Accounting months can be locked and unlocked from the Accounts screen with a reason, Administrator-only for unlock | BRIEF (new) | `/api/accounts/period-locks`; "Accounting month locks" panel | `test_periods.py` (lock blocks receipt, credit note and dispatch); screen not browser-verified | MET |
| R-116 | A supplier bill captures the tax the supplier charged head by head, with round-off and total, linked to a supplier and optionally to a purchase order; the bill number is unique per supplier; a reversal keeps the row, requires a reason and excludes it from every total | BRIEF (new) | `purchase_invoices`; `/api/accounts/purchase-invoices`; "Input GST — supplier bills" panel | `test_gst_statutory.py` (capture, duplicate 409, short reason 422, double reverse 409); browser probe 3 Nov 2026 | MET |
| R-117 | The input register, eligible and blocked totals and net GST payable are reported head by head from posted bills; blocked input is never netted; creditable expense GST is a memo, not a column; no posted bill means "No data yet", never zero | BRIEF (new) | `app/services/gst.py:register/net/expense_itc`; `/api/accounts/input-gst`, `/gst-net`; `accounting.report().net_gst` | `test_gst_statutory.py::test_net_payable_is_output_less_eligible_input`, `::test_with_no_supplier_bill_input_tax_is_unavailable_not_zero`; browser probe (net −180.00, then "No data yet") | MET |
| R-118 | Figures reported as filed on GSTR-1 and GSTR-3B are captured per month and form and compared line by line with the computed register; a difference is shown with both figures and not resolved; ITC is not compared while no input exists | BRIEF (new) | `gst_returns`; `gst.reconciliation`; `/api/accounts/gst-returns`, `/gst-reconciliation`; "GST returns and reconciliation" panel | `test_gst_statutory.py::test_a_filed_return_is_compared_with_the_registers`; browser probe (matches, then a shown difference) | MET |
| R-119 | Statutory dues report withheld, deposited and outstanding per head: vendor TDS from posted bills, payroll statutory heads only from approved, processed or paid periods, challans as recorded deposits; a head with no source is unavailable with a reason | BRIEF (new) | `statutory_challans`; `app/services/statutory.py`; `/api/accounts/statutory-dues`, `/statutory-challans`; "TDS and statutory dues" panel | `test_gst_statutory.py::test_statutory_dues_read_vendor_tds_and_approved_payroll_only`, `::test_a_draft_payroll_is_not_a_statutory_liability`; browser probe (₹20 cleared by a challan) | MET |
| R-120 | Supplier bills, filed returns and challans follow the accounting-month lock and the closed-year gate (HTTP 423); reads need `accounts:read` and writes stay with the Administrator | BRIEF (new) | `periods.refuse_if_closed` in `app/api/gst.py`; RBAC on each route | `test_gst_statutory.py::test_a_locked_month_and_a_closed_year_refuse_a_supplier_bill`, `::test_reads_follow_accounts_read_and_writes_stay_with_the_administrator` | MET |
| R-121 | A voucher stores its own double-entry lines with a draft, posted and reversed state; a draft may be unbalanced but posting refuses it; a posted voucher cannot be edited or deleted, only reversed by a mirror voucher dated today; a day book lists posted and reversed vouchers for a period and checks that debit equals credit | BRIEF (new) | `vouchers`/`voucher_lines`; `app/services/journal.py`; `/api/accounts/vouchers`, `/day-book`; "Journals and vouchers" and "Day book" panels | `test_ledger_and_bank_rec.py` (draft refused, post, reversal, day book, locked month 423, future date, API lifecycle, RBAC); browser probe 3 Nov 2026 | MET |
| R-122 | Opening balances are captured per head and financial year as either a debit or a credit, with a zero on both sides clearing the row; a closed year refuses the write; the opening trial balance reports its difference instead of plugging it | BRIEF (new) | `opening_balances`; `journal.opening_rows/save_opening`; `/api/accounts/opening-balances`; "Opening balances" panel | `test_ledger_and_bank_rec.py::test_opening_trial_balance_reports_an_imbalance`, `::test_opening_balance_refuses_a_closed_year`, `::test_api_opening_balance_and_validation`; browser probe 3 Nov 2026 | MET |
| R-123 | A seeded chart of accounts carries the document buckets and Capital; an extra head can be created, renamed and deactivated but a seeded role cannot be duplicated | BRIEF (new) | `ledger_accounts`; `journal.account_rows/create_account/update_account`; `/api/accounts/ledger-accounts`; "Ledger heads" panel | `test_ledger_and_bank_rec.py::test_chart_is_seeded_with_the_document_roles`, `::test_extra_head_can_be_created_and_deactivated`; browser probe (head 5200 created and deactivated) | MET |
| R-124 | The balance sheet merges the latest captured opening, posted vouchers and the document trial balance by head, with section totals, retained earnings, cash and bank and a named difference; its warnings state what the document layer does not cover rather than guessing | BRIEF (new) | `app/services/balance_sheet.py`; `/api/accounts/balance-sheet`, `/ledger-accounts/{id}/balance`; "Balance sheet" panel | `test_ledger_and_bank_rec.py::test_balance_sheet_merges_opening_voucher_and_documents`, `::test_balance_sheet_names_a_carried_forward_opening`; browser probe 3 Nov 2026 | MET |
| R-125 | A bank statement is captured per bank head and period; its lines are matched only to a payment, receipt or voucher line whose amount and direction agree; the proof reports adjusted book, adjusted statement and the remaining difference, and a matched statement or line cannot be deleted | BRIEF (new) | `bank_statements`/`bank_statement_lines`; `app/services/bank_rec.py`; `/api/accounts/bank-statements`; "Bank reconciliation" panel | `test_ledger_and_bank_rec.py::test_bank_statement_match_and_proof`, `::test_bank_statement_refuses_an_overlap_and_a_bad_line`; browser probe (1 of 1, difference 0.00) | MET |
| R-126 | A receipt or payment is recorded in one of two modes: `outstanding` settles the party's pending documents oldest first (receipts cannot settle an invoice dated after the money, payments cannot settle goods received after it) and holds any excess as an advance; `advance` records the full amount with no document. The advance may later be drawn down by a new invoice or goods receipt, is shown in the party ledger and `GET /api/accounts/advances`, and never counts as sales revenue or purchase expense | BRIEF (new) | `payment_allocations`; `app/services/advances.py`; `app/services/ledger.py`; `/api/accounts/payments`, `/advances`; two-mode entry drawer | `tests/test_accounts_advances.py` (8 tests: settlement, date rule, excess advance, draw-down, supplier side, trial-balance split, role gate); browser walk 3 Nov 2026 (receipt ₹123.45 advance, ₹500 settling ₹472 + ₹28 advance) | MET |
| R-127 | Receivables by distributor replaces the two date inputs with one From–To range and requests nothing until Apply is pressed; every figure, table row and total reflects the applied range, and the CSV export uses the same applied range | BRIEF (new) | `renderReceivablesByDist`; `GET /api/accounts/receivables-by-distributor`; CSV export | `tests/test_accounts_reports.py` (totals, dates, window, permissions) and `test_accounts_advances.py::test_receivables_window_counts_the_draw_down`; browser walk 3 Nov 2026 (0 requests on a date change, 1 on Apply; 34 rows, total ₹60,105.50; CSV 3,471 bytes) | MET |
| R-128 | Every Accounts KPI card is a link to its own report, not a shared page: Revenue and Output GST → GST outward, Collections and Cash and bank → Receipts and payments, Receivables → Receivables, Over 60 days → Ageing as at the window end, Payables → Payables, Payable within 7 days → Payables filtered to the week, Expenses → Expenses, Net profit → Performance and P&L; a windowed card carries `from`/`to` (the ageing card `as_of`) so the detail opens on the same window; the server builds the addresses | BRIEF (new) | `accounting.report()["cards"][].href`; `renderAccPerformance` `#accKpis`; hash query parsing in `route()` | browser walk 3 Nov 2026: ten distinct destinations, window parameters present, `due=week` changed the payables list, no console error | MET (browser); no unit test asserts the `href` values |

### 4.6 Reports and dashboard

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-49 | Report catalogue, per-report permission, paging/sorting | REG MOD-08 | `/api/reports` | `test_reports.py` | MET |
| R-50 | CSV/PDF export gated by `report:export` and audited | REG MOD-08 | `/api/reports/{key}/export` | `test_reports.py` | MET |
| R-51 | Reconciliation checks on financial reports | REG MOD-08 | `app/services/reports.py` | `test_report_reconciliation.py` | MET |
| R-52 | Overview KPIs, search, activity, system health | REG MOD-08 | `/api/dashboard` | `test_dashboard.py`, `test_dashboard_phase2.py` | MET |
| R-53 | Period selector, permission-masked sections, drill-downs | AUDIT | `/api/dashboard`, `/expiry`, `/activity` | `test_dashboard_phase2.py` | MET |
| R-135 | The Overview period is chosen from one trigger showing the current window, presets `1D 7D 30D Month to date Last month 90D This FY` and a two-month calendar (start, then end; a backwards pair swapped); the pair survives a reload, the dates are sent to the server as `from_date`/`to_date`, and an invalid or future window is refused with the server's message | BRIEF (new) | `renderDashRange`, `drawDashCalendar`, `pickDashDay`, `bindDashRange`, `applyDashDates` in `app.js`; `/api/dashboard` | browser walk 4 Nov 2026 at 1440/768/390 in both themes, preset and custom-range requests logged (`docs/VERIFICATION_REPORT.md` §27.3) | MET (browser); the control has no unit test — the server window is covered by `test_dashboard_phase2.py` and `test_dashboard_phase3.py` |
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
| R-86 | SMTP settings editable in the app (host, port, security, sending, mode, username, encrypted password, From, Reply-To, test To/CC), environment as default | BRIEF (new) | `/api/email-settings`; `app/services/email_config.py`; Settings → Email and SMTP | `test_email_settings.py`; local SMTP sink; UI screenshot | MET |
| R-87 | Test e-mail composer with message type, To, CC, subject and body; dry run and one-session delivery, every attempt stored | BRIEF (new) | `POST /api/email-settings/test`; `email_test_messages` | `test_email_settings.py`; live sink run in `VERIFICATION_REPORT.md` | MET |
| R-88 | Test e-mails can never reach a real inbox by accident: `[TEST]` subject, dry run default, live needs saved mode and `EMAIL_MODE=live`, password never read back | BRIEF (new) | `app/api/email_settings.py`; `email_config.effective()` | `test_email_settings.py` | MET |
| R-130 | The frontend and backend start as two named commands; the frontend serves the SPA and proxies `/api`, `/docs`, `/openapi.json` and `/redoc`, so the session cookie stays first-party; a down backend answers 502 with the command to run, and a path outside `static/` is refused | BRIEF (new) | `scripts/run_backend.py`, `scripts/run_frontend.py`; `docs/RUNNING_SERVERS.md` | split run 3 Nov 2026 (SPA/JS/CSS 200, `/api/auth/me` 401→200 through the proxy, `/docs` proxied, 502 when the backend stopped, traversal refused) | MET (loopback); production TLS/reverse proxy not run |
| R-133 | Live e-mail delivery and worker database errors are fixed: 465 means implicit TLS and 587 STARTTLS regardless of the saved choice; a failed settings read rolls back; the worker rolls back and re-reads before recording a failure so a database error does not leave a delivery stuck "sending"; a schedule with no next run is committed even when nothing fires; the connection pool is bounded and recycled | BRIEF (new) | `email_config._transport`/`load_row`; `email_worker.enqueue_due`/`process_one`; `app/core/db.py`; `app/core/config.py` | `test_email_settings.py::test_well_known_smtp_ports_decide_the_transport`, `::test_an_unreadable_settings_row_rolls_the_session_back`; `test_email_reports.py::test_a_schedule_with_no_next_run_is_committed_even_when_nothing_is_due`; full e-mail suite | MET (API and tests); no real inbox delivery (G-09) |

### 4.9 Roles, permissions and feature switches

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-89 | Every permission and access-control option is assignable from Roles & Permissions | BRIEF (new) | `#/roles`; `GET /api/roles/permissions`; role tree editor | `test_permission_tree.py`; browser check (44 inputs, 12 groups) | MET |
| R-90 | Feature-level On/Off controls live only under Roles & Permissions; Overview is read-only status | BRIEF (new) | `#/roles` → Feature availability; `PATCH /api/features/{key}` | `test_feature_switches.py`; `docs/DECISIONS.md` D-29/D-30 | MET |
| R-91 | Parent unchecked denies the module and removes its child assignments | BRIEF (new) | `syncPermissionTree`; `sanitized_permissions`; `effective_permissions` | `test_permission_tree.py` | MET |
| R-92 | Parent checked makes children selectable but grants none of them | BRIEF (new) | Tree editor; `sanitized_permissions` never adds keys | `test_permission_tree.py` | MET |
| R-93 | Only explicitly ticked children are granted; a child cannot work without its parent | BRIEF (new) | `permission_allowed`; `validate_permissions` | `test_permission_tree.py`; `test_authz.py` | MET |
| R-94 | Navigation hides modules without parent access and the API enforces both | BRIEF (new) | `VIEW_PERM`/`showView`; `require` + effective set; feature gate | `test_permission_tree.py`; browser check: viewer sent to Overview | MET |
| R-95 | Administrator-only permissions remain restricted to Administrators | BRIEF (new) | `ADMIN_ONLY_PERMISSIONS`; locked editor inputs; `validate_permissions`; admin keep-check | `test_permission_tree.py`; `test_roles_parity.py` | MET |
| R-96 | The same rules extend to future modules | BRIEF (new) | Catalogue/parent-map completeness tests; feature registration test | `test_permission_tree.py`, `test_feature_switches.py` | MET |

### 4.10 Branch- and office-based attendance

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-100 | Assign an employee to a branch and an office/work location; one office belongs to one branch, the branch is inferred from the office, and a mismatched pair is refused | BRIEF (new) | `_normalise_employee_location`; `Employee.branch_id/office_id`; new-employee form cascade | `test_hr_sites.py::test_sites_crud_and_employee_assignment`; browser check | MET |
| R-101 | Maintain branch and office masters (HR responsible, status, geofence centre/radius, attendance mode); refuse deactivation or a branch move while active staff are assigned | BRIEF (new) | `/api/hr/branches`, `/api/hr/offices`; `_site_counts`; migration `0018` | `test_hr_sites.py::test_sites_crud_and_employee_assignment`; browser check of the policy drawer | MET |
| R-102 | Configure whether attendance is required per branch, office, designation and employee, in any mix, with effective dates, priority, optional shift and attendance-mode override | BRIEF (new) | `AttendanceRule`; `/api/hr/attendance-rules`; rule form | `test_hr_sites.py::test_rule_validation_precedence_and_effective_dates`; browser check (13 fields, cascade) | MET |
| R-103 | Resolve the rule by specificity — employee, office, designation, branch, company default — and show the source that applied | BRIEF (new) | `resolve_attendance_requirement`, `rule_label`; `/api/hr/attendance-rules/resolve` | `test_hr_sites.py`; profile/form show "Office default (…)" | MET |
| R-104 | Record attendance only for employees who must mark it: refuse manual, bulk, correction and self check-in for the exempt, naming the rule | BRIEF (new) | `require_attendance`, `require_self_service`; gating in attendance endpoints | `test_hr_sites.py` tests 3 and 4 | MET |
| R-105 | Exempt working days are "not required" in the monthly register, not gaps or absences | BRIEF (new) | `monthly_attendance`; `not_required_days`; register legend and column | `test_hr_sites.py::test_monthly_register_marks_exempt_days_as_not_required`; browser check of the column and legend | MET |
| R-106 | Payroll infers no absence for an exempt employee; only recorded unpaid leave reduces pay | BRIEF (new) | `app/services/payroll.py` exempt branch | `test_hr_sites.py::test_payroll_does_not_invent_absence_for_exempt_employees` | MET |
| R-107 | Location filters narrow attendance, monthly register, People, dashboard and every HR report, and the report header states the filter applied | BRIEF (new) | `branch_id`/`office_id` on the HR APIs; `hrSiteParams`; `by_office`/`by_branch` | `test_hr_sites.py::test_site_filters_reach_attendance_employees_dashboard_and_reports`; browser check | MET |
| R-108 | The new-employee screen captures branch/office and shows the resolved policy before saving | BRIEF (new) | `employeeForm` in `static/js/app.js` | browser check 1 Nov 2026 (cascade, policy note) | MET |

### 4.11 Screen consolidation

| ID | Requirement | Source | Implementation | Evidence | Status |
|---|---|---|---|---|---|
| R-97 | Customers and Distributors are one screen, not two lists of the same records | BRIEF (new) | `#/customers` → `v-customers` (`static/index.html`, `renderCustomers` in `app.js`); the old list and its duplicate `renderDists` are removed | Browser check 1 Nov 2026: 19 sidebar entries, 7 columns, one action set | MET |
| R-98 | The merged screen keeps every capability of both pages: search, status filter, tax identity, credit figures, open, new order, change limit | BRIEF (new) | Toolbar search + status select; name cell shows territory and GSTIN; credit limit / in use with meter / available; actions gated by `distributor:write`, `sales:write`, `credit:manage` | Browser check as Administrator, `sales` and `viewer`; `#/distributors` alias opens the same view | MET |
| R-99 | Existing links to the old address keep working | BRIEF (new) | `route()` maps `#/distributors` to the customers view | Browser check 1 Nov 2026: hash `#/distributors` renders the merged screen with the correct nav highlight | MET |

## 5. Gaps, blockers and open items

| ID | Item | Effect | Owner / next step |
|---|---|---|---|
| G-01 | Payroll is not posted to the ledger (R-78) | Salary cost does not appear in the trial balance or ledgers | Product owner to approve a salary-to-ledger mapping (D-17). |
| G-02 | Documents are not posted to the voucher ledger automatically (R-48) | The journal and bank reconciliation exist, but an invoice or receipt makes no voucher; the two trails are merged only on the balance sheet | Decide whether documents should post themselves, or keep the voucher as a manual adjustment layer. |
| G-03 | Overtime / salary-revision / reimbursement approvals (R-77) | Labels exist; requests are not raised or decided | Phase 1 gap; needs workflow design. |
| G-04 | Multi-level approval workflows | The table exists; no application code reads it | Design + implementation. |
| G-05 | Purchase-order printing | POs cannot be printed as a secure document | Add a PDF builder only if required. |
| G-06 | E-invoice / e-way bill portal (MOD-15) | Conditional on turnover; not built | Keep conditional. |
| G-07 | No dedicated test file for Billing and Leads | Live smoke only; regressions could slip through | Add tests before the next billing change. |
| G-08 | Lockout has no automated test | Behaviour read in code only | Add a login-failure test. |
| G-09 | No live e-mail delivery | Test mode only; SMTP/recipients not approved | Approve SMTP and recipient list (D-09/D-19). |
| G-10 | Physical device, screen reader, load and deployment not verified | Only headless Chrome and local `127.0.0.1` | Run on the target environment when one exists. |
| G-11 | `APP_ENV=production` while using the development database | Secure-cookie and db-reset guard behaviour depends on the label | Correct the environment file before deployment. |
| G-12 | UI/API mismatches M-03–M-11 remain open | Some server features lack a browser control; M-02 (receipt/payment document link) is closed by the two-mode entry drawer | Tracked in `FRONTEND_BACKEND_FIELD_MAPPING.md`. |
| G-13 | Supplier bank-change flow has no dedicated test | Live smoke only | Add a two-person approval test. |
| G-14 | Database reset and secondary password were not executed | Destructive by design; only the gate was read | Test against a disposable database with explicit approval. |

## 6. How this matrix was checked

| Check | Command / source | Result |
|---|---|---|
| Route count | `app.routes` | 343 API operations across 267 paths (4 Nov 2026, after the sign-in content routes; `APIRoute`s excluding HEAD/OPTIONS) |
| Test count | `python -m pytest -q -rs` | 467 passed, 0 failed, 0 skipped (4 Nov 2026, after WP-3 batch 2; `VERIFICATION_REPORT.md` §29.1) |
| Schema | `alembic current` / `heads` | head `0030_sign_in_content`; the disposable test database is at it (recreated by the 4 November suite), and the development database was upgraded to it on 4 November 2026 (88 tables); production is at `0028_advances` |
| Migration round-trip | upgrade → downgrade 0018 → upgrade head | pass (verification report §3) |
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
