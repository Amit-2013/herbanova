# Formula Reconciliation and Test Record

**Project:** Herbanova Business Control
**Stage:** 3 — audit registers
**Date:** 31 October 2026
**Purpose:** to state exactly which formulas and report figures are protected by an executable test, which are only read from source, and which are not protected at all — and to set out the work needed to close the gap.

**No application code, configuration, or business data was changed to produce this record.** The suite runs against a separate PostgreSQL database created for the tests, never against the development database.

---

## 1. Principles

The reporting layer in this project is **document-derived**, not a separate double-entry ledger. Each report is rebuilt from issued documents (invoices, credit notes, debit notes, goods receipts, payments) every time it is requested. That design removes a whole class of drift, but it creates a different risk: a report can look plausible while computing the wrong thing.

The tests therefore follow four rules:

1. **Recompute independently.** A financial report is compared with a second implementation — grouped SQL aggregates or a direct model query — not with itself. `_source_receivables()`, `_source_gst()` and `_source_payables()` exist for this reason (`app/services/reports.py:403-500`).
2. **Assert content, not just status 200.** The Stage 1 audit found two reports that returned 200 with wrong or empty content. The reconciliation suite asserts row content, totals and bucket placement (`tests/test_report_reconciliation.py:1-11`).
3. **Refuse a false "reconciled".** Any report that carries only a row-count check is reported as such here. `_empty_reconciled()` always adds a `row_count` check that compares the report's rows with the same list; that check is structural, not evidential.
4. **Be honest when empty.** An empty period must return an empty register whose checks still pass, rather than an error or a stale figure (`test_empty_period_still_reports_honest_checks`).

---

## 2. Test environment and data isolation

| Property | Value | Source |
|---|---|---|
| Database | `herbanova_bcs_test` (separate from the development database) | `tests/conftest.py` |
| Schema | Created by Alembic, then `alembic check` is asserted clean | `tests/conftest.py`; `test_migrations_match_the_models` |
| Data | Synthetic: one product/HSN/rate, one distributor, one supplier, one warehouse and an opening stock movement | `world` fixture, `tests/conftest.py:118-175` |
| Actors | Synthetic users for admin, sales, inventory, viewer, HR roles | session fixture |
| Side effects | Rolled back or confined to the test database; no production table is touched | `tests/conftest.py` |
| Browser | Not used; the suite drives the ASGI app through `TestClient` | `tests/conftest.py` |

The `world` fixture inserts an opening stock movement deliberately: a batch with no movement would make the stock report look unbalanced, and the fixture comment says that difference must not be papered over (`tests/conftest.py:163-171`).

**What this does not cover:** the suite never starts a real browser, never runs a real payroll against live data, and never exercises two concurrent requests. Those gaps are listed in section 8.

---

## 3. How to run

```bash
# from the project root, with the virtual environment active
PYTHONPATH=. python -m pytest -q

# the reconciliation subset only
PYTHONPATH=. python -m pytest -q tests/test_report_reconciliation.py tests/test_reports.py

# one report family
PYTHONPATH=. python -m pytest -q tests/test_reports.py -k hr
```

The suite expects the test database to be reachable with the same credentials as the application. It does not read or print them.

---

## 4. Current result

| Run | Command | Result |
|---|---|---|
| Full suite, 31 October 2026 | `PYTHONPATH=. python -m pytest -q` | **62 passed, 319 warnings in 44.16 s** |
| Targeted report subset, 31 October 2026 | `tests/test_report_reconciliation.py tests/test_reports.py tests/test_dashboard.py tests/test_backup_restore.py tests/test_module_status.py` | **30 passed, 319 warnings in 36.82 s** |

The warnings are third-party deprecations (`anyio`, `fastapi`, `slowapi`) on Python 3.14, not application failures. No test was skipped, xfailed or deselected. The full-suite total includes the 14 authorisation and role-parity tests added with the M-01 fix (`tests/test_authz.py`, `tests/test_roles_parity.py`); those are not part of the 48-row reconciliation matrix below.

---

## 5. Test-to-assertion matrix

### 5.1 Report reconciliation — `tests/test_report_reconciliation.py` (12 tests)

| Test | What it proves |
|---|---|
| `test_gst_register_lists_the_issued_invoice` | An issued invoice appears in the GST register with the buyer and the document number; the register is not empty. |
| `test_gst_register_and_accounts_endpoint_agree` | The GST-register totals agree with the accounts GST endpoint, which is a different code path. |
| `test_receivables_ageing_shows_the_four_buckets` | The four ageing buckets exist with the expected labels, not the wrapper's own keys. |
| `test_receivables_ageing_puts_the_invoice_in_a_bucket` | A fresh invoice lands in the current bucket. |
| `test_receivables_report_honours_the_date_range` | A date range excludes documents outside it. |
| `test_trial_balance_debits_equal_credits` | Total debits equal total credits for the document set. |
| `test_stock_report_agrees_with_the_movement_ledger` | Batch `on_hand` agrees with the net `stock_movements` quantity. |
| `test_invoice_register_totals_match_the_database` | Register row totals equal the database SUMs and every check is `ok`. |
| `test_financial_reports_carry_a_real_cross_check` | For eight financial reports, at least one check is **not** named `row_count` and no check fails. |
| `test_empty_period_still_reports_honest_checks` | An empty period returns rows `[]` and `reconciled: true`. |
| `test_report_filters_are_refused_when_unsupported` | A report refuses a filter it does not implement (422), rather than ignoring it. |
| `test_migrations_match_the_models` | `alembic check` reports "No new upgrade operations detected". |

### 5.2 Report surface — `tests/test_reports.py` (8 tests)

| Test | What it proves |
|---|---|
| `test_catalog_is_categorised_and_permission_filtered` | 25 reports are categorised; a sales user does not receive HR reports and is refused 403. |
| `test_report_supports_paging_sorting_and_reconciliation` | `page`, `page_size`, `sort` and `direction` work; `total_rows` is the full count. |
| `test_each_hr_report_builds_and_reconciles` | Six newer HR reports build for three periods, carry checks, report `reconciled`, and export in CSV/XLSX/PDF. |
| `test_hr_reports_narrow_by_employee_department_and_branch` | The three narrowing filters change the row set correctly. |
| `test_new_hr_reports_are_permission_checked` | A role without `hr:reports` neither sees nor opens them. |
| `test_every_report_builds_and_exports_in_every_format` | Every one of the 25 reports builds and exports in all three formats after a PO is created. |
| `test_empty_register_exports_an_explicit_empty_state` | Empty CSV and XLSX contain "No records for this period." |
| `test_export_is_permission_checked_and_audited` | CSV has a BOM and attachment header; a viewer is refused; the export appears in the audit trail. |

### 5.3 Formulas exercised indirectly (23 tests)

| Module | Tests | Formula areas touched |
|---|---|---|
| `tests/test_approvals.py` (3) | credit-limit and post-billing approvals | F-20–F-27, F-35, segregation of duties (F-66 for HR) |
| `tests/test_hr.py` (6) | leave, payroll, shifts, check-in | F-51–F-66 |
| `tests/test_products.py` (4) | HSN validation, create/edit, pagination, permission | F-02–F-05, F-14 (HSN is the rate key) |
| `tests/test_purchase_orders.py` (4) | cost-or-remark rule | F-41–F-42 (payables basis) |
| `tests/test_dashboard.py` (4) | permissioned tiles, >200 rows, expiry ordering | F-20 exposure, F-30 FEFO expiry |
| `tests/test_module_status.py` (4) | module register consistency | governance, not arithmetic |
| `tests/test_backup_restore.py` (2) | restore comparison | F-75 |
| `tests/test_smoke.py` (1) | boot and login | session |

### 5.4 What the count does **not** mean

62 passing tests is not 62 covered workflows. The full route inventory in `docs/FRONTEND_BACKEND_FIELD_MAPPING.md` lists 158 API routes; the suite directly calls a minority of them. Section 8 names the untested workflows that matter most.

---

## 6. Report reconciliation matrix

### 6.1 Reports with an independent check (8)

Check names were read from a live, read-only build on 31 October 2026.

| Report | Checks returned | Independent evidence |
|---|---|---|
| `stock` | `product_count`, `stock_quantity` | Batch sums vs `stock_movements` net; product count vs `products` |
| `receivables` | `row_count`, `outstanding` | `_source_receivables()` grouped SQL over invoices, notes and receipts |
| `receivables_ageing` | `ageing_total`, `ageing_count` | Recomputed bucket totals from the same documents |
| `payables` | `received_value`, `paid` | GRN quantity × PO line cost and payment SUM, in SQL |
| `trial_balance` | `row_count`, `balanced`, `row_debits`, `row_credits` | Debit/credit postings derived independently for each document |
| `gst_register` | `row_count`, `taxable_total`, `cgst_total`, `sgst_total`, `igst_total`, `total_total` | `_source_gst()` SQL sums over issued invoices and notes |
| `sales` | `row_count`, `source_rows`, `order_value` | Source row count and SUM of `sales_orders.total` in SQL |
| `invoices` | `row_count`, `source_rows`, `taxable_value`, `grand_total` | Source row count and SUMs of `invoices.taxable_value` / `grand_total` |

`test_financial_reports_carry_a_real_cross_check` asserts that each of these eight has at least one check whose name is not `row_count` and that none fails. For `receivables`, `receivables_ageing`, `payables`, `trial_balance`, `gst_register` and `stock`, **every** check is independent — there is no trivial `row_count` at all.

### 6.2 Reports with a row-count-only check (17)

These reports call `_empty_reconciled()` without a `source_count`. Their only check compares `len(table["rows"])` with `len(table["rows"])`, so it can never fail while the report builds. `reconciled: true` on these reports means "the envelope is internally consistent", **not** "the figures are independently verified".

| Report | Why the risk is low or high |
|---|---|
| `hr_employee_master` | Low money risk; a filter bug could still hide employees. |
| `hr_joining_exit` | Date-boundary bug could omit a joiner or leaver. |
| `hr_attendance` | Late/early minutes and status could be mis-mapped. |
| `hr_late_arrival` | Depends on the same attendance mapping. |
| `hr_missing_punch` | A missing punch could be filtered out by the same bug. |
| `hr_leave` | Days and status could disagree with the application row. |
| `hr_od` | Date range and duration could disagree with the request. |
| `hr_payroll` | Gross, deductions and net are financial figures with no independent recomputation. |
| `hr_payroll_deductions` | Component totals are financial and untested. |
| `hr_leave_balance` | Entitled/used/pending/carried could drift from the applications. |
| `hr_approvals` | Status and timestamps could drift from `approval_requests`. |
| `hr_approval_turnaround` | Elapsed hours could be computed from the wrong pair of timestamps. |
| `leads` | Row presence only; no money. |
| `purchases` | Order values are not shown in this register, so the risk is row omission. |
| `goods_receipts` | Receipt lines and quantities are not recomputed. |
| `suppliers` | Master-data completeness only. |
| `distributors` | Credit limit is shown but not reconciled to a second source. |

**Priority for closure:** `hr_payroll`, `hr_payroll_deductions`, `hr_leave_balance` and `distributors` carry financial figures and should move first. The other thirteen are register-presence reports and can follow.

### 6.3 The "reconciled" flag

`reconciled` is true when every check in the list is `ok`. Because `_empty_reconciled()` always inserts the self-comparison `row_count`, the flag is true for the 17 reports by construction. The UI and the export must not present that flag as proof of accuracy until section 8's work is done. This is recorded as an open item in Appendix A of `docs/FORMULA_AND_BUSINESS_RULE_REGISTER.md`.

---

## 7. Formula coverage against the register

| Formula group | Register IDs | Test evidence | Status |
|---|---|---|---|
| Money quantisation and rounding | F-01, F-05–F-06 | Invoice totals asserted in several tests | VERIFIED (code) |
| GST rate resolution, place of supply, split | F-02–F-05, F-15 | Invoice creation in `_invoice_for`; GST report reconciliation | VERIFIED (code) |
| Discount slabs and approval thresholds | F-07–F-11 | Approval triggered by a large discount indirectly | PARTIAL — no slab-specific test |
| Sales order pricing and credit exposure | F-20–F-27 | `test_credit_limit_approval_is_admin_only` | VERIFIED |
| FEFO allocation and stock movements | F-28–F-32 | Dispatch through `_invoice_for`; stock report vs ledger | VERIFIED (code) |
| Invoice numbering and immutability | F-17–F-19, F-33–F-36 | Not directly tested; `alembic check` only | UNVERIFIED |
| Credit/debit note caps and stock return | F-37–F-38 | No note test | UNVERIFIED |
| Payables and receivables | F-39–F-45 | Report reconciliation | VERIFIED |
| Trial balance | F-46 | Direct debit/credit test | VERIFIED |
| Payroll gross/deductions/net | F-51–F-58 | `test_payroll_prepare_submit_approve_process` | VERIFIED (one structure) |
| HR late/early/geofence | F-59–F-62 | `test_general_shift...`, `test_staff_can_check_in...` | VERIFIED |
| Leave and OD attendance effects | F-63–F-66 | `test_leave_approval...` | VERIFIED |
| Tax identity (GSTIN/PAN) | F-67–F-70 | Product HSN tests; identity itself only read | PARTIAL |
| Audit, permissions, backup | F-71–F-75 | Backup test; export audit test | VERIFIED |
| Attendance requirement resolution, gating and exempt days | F-76–F-79 | `tests/test_hr_sites.py` (7 tests) | VERIFIED |

The full expressions and source lines are in `docs/FORMULA_AND_BUSINESS_RULE_REGISTER.md` (F-01–F-79). Section 4 is the 31 October 2026 baseline; the current suite total is recorded in `docs/VERIFICATION_REPORT.md` §2.

---

## 8. Coverage gaps that matter

These are workflows with **no executable test**. They are not known to be broken; they are simply unprotected.

| Gap | Why it matters | Suggested first test |
|---|---|---|
| Accounts receipt/payment entry | The only financial write with no test; M-02 shows the UI path can fail | Post a receipt against an issued invoice, assert the ledger and `payments` row; post an unallocated receipt and assert 422 |
| Credit and debit notes | Caps, tax reversal and return-to-stock are untested | Issue a full-value credit note; assert invoice outstanding becomes zero, stock returns to the original batches, and over-credit is refused |
| Invoice cancellation and movement | Immutability and audit are core controls | Cancel an issued invoice; assert number retained, payments refused, ledger excludes it |
| Goods receipt | Stock affordability downstream depends on it | Receive against a PO; assert batch, movement, GRN and status transition |
| Lead lifecycle | No test at all | Create → assign → status → follow-up; assert audit rows and owner permission |
| Supplier bank change | Segregation-of-duties control | Request as one user, decide as another; assert the supplier bank fields only change on approval |
| User and role management | Privilege escalation risk | Create a role with one permission; assert the server enforces it and the last-admin rule holds |
| Print and verification | Document integrity claim | Print an invoice, verify the code, alter the invoice, assert verification fails |
| Company/tax/slab APIs | Pricing depends on them | Create a rate window, close it, assert the next quote resolves the new rate |
| Payroll without attendance and without structure | Two silent defaults | Assert the no-attendance note is written; assert an employee without a structure is reported, not silently skipped |
| Numbering under concurrency | Duplicate document numbers are a legal defect | Two concurrent creates against the same FY; assert distinct numbers |
| Report paging at volume | In-memory paging (M-10/R-02) | Seed 2,000 rows; assert stable page boundaries and that `total_rows` is correct |

---

## 9. Plan to close the gaps

### P1 — financial correctness (before any production reliance)

1. **Payroll reconciliation.** Add `source_gross`, `source_deductions` and `source_net` checks to `hr_payroll` and `hr_payroll_deductions`, computed by SQL over `hr_payroll_entry_lines`; assert they equal the report. Add a `_source_*` helper rather than reusing the builder.
2. **Leave balance reconciliation.** Recompute entitled/used/pending from applications and approved leave, compare with `hr_leave_balances`.
3. **Distributor exposure reconciliation.** Compare the register's `credit_limit` and the exposure shown on the detail screen with the sales-service recomputation.
4. **Notes tests.** Full credit, partial credit, over-credit refusal, debit note, return-to-stock, cancelled invoice refusal.
5. **Accounts tests.** Allocated and unallocated receipts, over-allocation refusal, cancelled invoice refusal, append-only behaviour.

### P2 — control coverage

6. Invoice cancellation and post-billing movement/amendment tests, including the 405 traps.
7. Goods receipt and purchase-order state transitions.
8. Supplier bank-change segregation.
9. User/role enforcement and the last-administrator rule.
10. Print/verify tamper test.

### P3 — scale and edge cases

11. Replace in-memory paging with SQL ordering and `LIMIT/OFFSET`, or cap the period; then assert page stability at 2,000+ rows.
12. Concurrency test for document numbering.
13. Browser-level smoke test for the login → change-password → first data call path (M-01). A manual run against a throwaway database was completed on 31 October 2026; an automated browser test remains open.

Each item is “done” only when the new test fails on the old behaviour and passes on the fixed behaviour. Item 13 is the exception: its manual run is recorded evidence, not an automated regression.

---

## 10. Known limitations of this record

- **No automated browser suite.** One targeted manual browser session on 31 October 2026 exercised sign-in → forced password change → first data call against a throwaway database (M-01). Every other UI statement is read from source, not driven.
- **No production-volume test.** All tests use a small synthetic world. Performance and paging behaviour at scale are reasoned from code, not measured.
- **One payroll structure.** The payroll test creates one structure for one employee; multi-structure, mid-month revision and percentage-of-gross cases are untested.
- **No concurrency.** Numbering, stock allocation and approval decisions are not tested under simultaneous requests.
- **No external tax validation.** GSTIN and PAN check characters are tested as format rules; no external portal is contacted.
- **Warnings are third-party.** The 319 warnings come from dependencies on Python 3.14, not from application code.

---

## 11. Statement

On 31 October 2026 the full suite passed: **62 tests, 0 failures, 0 skips**. Eight financial reports carry independent reconciliation; seventeen registers carry only a structural row-count; the formula groups listed as VERIFIED above are protected by executable assertions. Everything else in this record is either VERIFIED (code), PARTIAL or UNVERIFIED, and is labelled as such rather than being presented as certified.
