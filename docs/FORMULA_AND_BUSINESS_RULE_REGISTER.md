# Formula and Business-Rule Register

**Project:** Herbanova Business Control (FastAPI + PostgreSQL ERP)
**Stage:** 3 — audit registers
**Date:** 31 October 2026
**Evidence basis:** source code in `app/`, schema metadata on the development database, and the automated tests in `tests/`. No application code or business data was changed to produce this register.

## How to read this register

Each rule records the exact expression the application executes, the file and line that implements it, the conditions that gate it, its rounding behaviour, the test evidence, and a status:

| Status | Meaning |
|---|---|
| **VERIFIED** | Read in source and covered by an executable test that asserts the outcome. |
| **VERIFIED (code)** | Read in source; exercised indirectly, but no test asserts this specific formula. |
| **PARTIAL** | The calculation exists but a known limitation means it cannot be relied on for every case; the limitation is stated. |
| **UNVERIFIED** | Cannot be confirmed from code, tests, or the live schema. Nothing in this register should be treated as certified merely because it appears here. |

Money is held as `Decimal`; percentages and quantities are also `Decimal`. Every monetary result passes through a half-up quantiser to paisa unless a rule says otherwise. Rounding is never performed with binary floating point.

---

## 1. Tax and GST arithmetic

### F-01 — Money quantisation (paisa)
- **Formula:** `money(x) = Decimal(x or 0).quantize(0.01, ROUND_HALF_UP)`
- **Source:** `app/services/tax.py:35-36`; the same quantiser is re-declared in `app/services/ledger.py:37-41`, `app/services/payroll.py:28`, and `app/services/reports.py:195-201`.
- **Conditions:** applied to unit prices, line values, tax heads, totals, outstanding balances and payroll amounts.
- **Rounding:** half-up to two decimal places.
- **Tests:** indirect across every issued invoice assertion in `tests/test_report_reconciliation.py`.
- **Status:** VERIFIED (code). Fixed 2026-11-01: `ledger.money` was using the Decimal default (half-even) and now explicitly uses `ROUND_HALF_UP`, matching the documented rule and the tax/payroll helpers.

### F-02 — GST rate resolution by HSN and date
- **Formula:** select the `TaxRate` where `hsn = requested HSN`, `effective_from <= on`, and `effective_to IS NULL OR effective_to >= on`; order by `effective_from` descending and take the first. No match returns `None`.
- **Source:** `app/services/tax.py:50-59`.
- **Conditions:** HSN is stripped; a blank HSN returns `None`. Overlapping windows are refused when a rate is created or closed (`overlapping_rate`, `app/services/tax.py:62-71`).
- **Tests:** indirect through invoice creation; no dedicated rate-window test file was found.
- **Status:** VERIFIED (code). The absence of a dedicated test is recorded as a gap, not as a defect.

### F-03 — Place of supply and intra/inter classification
- **Formula:** zero-fill both state codes to two characters; both must exist in `STATE_CODES`; `kind = "intra"` when seller state equals buyer state, otherwise `"inter"`. Inside a union territory, the intra-state label is `UTGST`, otherwise `SGST`.
- **Source:** `app/services/tax.py:74-89`; `app/core/india_states.py` supplies the code list and `is_union_territory`.
- **Conditions:** missing seller or buyer state raises `ValueError`; an unknown state code raises `ValueError`. Nothing is guessed.
- **Tests:** indirect through the tax quote endpoint and invoice creation. No dedicated unit test for UTGST labelling was found.
- **Status:** VERIFIED (code).

### F-04 — Tax-head rate split
- **Formula:** intra-state → `{cgst: rate.cgst, sgst: rate.sgst, igst: 0, cess: rate.cess}`; inter-state → `{cgst: 0, sgst: 0, igst: rate.igst, cess: rate.cess}`.
- **Source:** `app/services/tax.py:92-97`.
- **Status:** VERIFIED (code).

### F-05 — Line tax
- **Formula:**
  - `gross = money(qty × unit_price)`
  - `discount_amount = money(gross × discount_percent ÷ 100)`
  - `taxable = money(gross − discount_amount)`
  - `cgst = money(taxable × cgst_rate ÷ 100)`; `sgst`, `igst`, `cess` analogous
  - `tax_total = money(cgst + sgst + igst + cess)`
  - if reverse charge: all four heads and `tax_total` become `0`
  - `total, round_off = round_to_rupee(taxable + tax_total)`
- **Source:** `app/services/tax.py:100-129`.
- **Conditions:** quantity must be > 0; unit price ≥ 0; discount 0–100 percent. Each tax head is rounded separately, then summed; the sum is not re-derived from an unrounded tax figure.
- **Rounding:** half-up to paisa at each step; final total rounded to the rupee with a separate round-off line (`round_to_rupee`, `app/services/tax.py:43-47`).
- **Tests:** the invoice totals and GST register are asserted in `tests/test_report_reconciliation.py:36-58`.
- **Status:** VERIFIED.

### F-06 — Rupee round-off
- **Formula:** `value = money(x)`; `rounded = value.quantize(1, ROUND_HALF_UP)`; `round_off = money(rounded − value)`. Positive means the document total was raised; negative means lowered.
- **Source:** `app/services/tax.py:43-47`.
- **Tests:** invoice/GST total agreement in `tests/test_report_reconciliation.py`.
- **Status:** VERIFIED.

### F-07 — Discount percent implied by price below MRP (sales order)
- **Formula:** `discount_pct = ((mrp − price) ÷ mrp × 100).quantize(0.1, ROUND_HALF_UP)`; zero when MRP is zero.
- **Source:** `app/services/order_tax.py:42-46` — one implementation, imported by `app/api/sales_orders.py:21` (approval check and order output) and `app/services/invoice.py:19` (invoice discount snapshot).
- **Conditions:** price above MRP is refused by order validation; equality yields 0 percent.
- **Tests:** discount approval reasons are exercised in `tests/test_approvals.py`.
- **Status:** VERIFIED (code). Consolidated 2026-11-01: the second implementation in `app/api/sales_orders.py` was removed so the approval check, tax preview and invoice snapshot cannot drift.

### F-08 — Discount slab applicability
- **Formula:** a slab applies when it is active, `effective_from <= on`, `effective_to IS NULL OR effective_to >= on`, its scope matches (`product` by product id, `group` by distributor group, `all`), and the quantity and/or value bands contain the line (a missing bound is open-ended).
- **Source:** `app/services/discounts.py:25-58`.
- **Status:** VERIFIED (code).

### F-09 — Best slab selection
- **Formula:** among applicable slabs choose the greatest tuple `(discount_percent, scope_weight, effective_from)`, where `scope_weight = product 3, group 2, all 1`; ties therefore prefer the more specific scope, then the newest.
- **Source:** `app/services/discounts.py:22`, `61-68`.
- **Status:** VERIFIED (code).

### F-10 — Approval threshold for a discount
- **Formula:** `approval_needed = discount_percent > (slab.approval_above if slab has one else 10%)`.
- **Source:** `app/services/discounts.py:75-79`; default constant `DISCOUNT_APPROVAL_PCT = 10` in `app/core/rules.py:5`.
- **Conditions:** comparison is strict; exactly 10 percent does not need approval when the slab has no override.
- **Tests:** order submission and approval routing in `tests/test_approvals.py`.
- **Status:** VERIFIED (code).

### F-11 — Overlapping slab refusal
- **Formula:** if another slab exists with the same scope/band/window and overlapping effective dates, creation/update is refused.
- **Source:** `app/services/discounts.py:82-99`.
- **Status:** VERIFIED (code); no dedicated test.

### F-12 — Sales-order tax preview
- **Formula:** for each line resolve the rate, compute the implied discount from price vs MRP, apply the best slab, and quote with `line_tax`; missing rate becomes an explicit line message rather than zero tax; order totals sum the quoted lines.
- **Source:** `app/services/order_tax.py:59-120` (preview builder).
- **Conditions:** the preview is read-only and does not persist a tax document.
- **Status:** VERIFIED (code).

### F-13 — Reverse charge
- **Formula:** when the resolved `TaxRate.is_reverse_charge` is true, the document states the taxable value but sets every tax head and the tax total to zero; the recipient accounts for the tax.
- **Source:** `app/services/tax.py:115`, `125-127`.
- **Status:** VERIFIED (code). Whether the tax amount is separately printed as “reverse charge” on the PDF was not verified in this stage.

### F-14 — Missing HSN or rate on an invoice
- **Formula:** an invoice line whose product has no HSN, or whose HSN has no rate in force, is included with zero tax and a note; the invoice is not silently rejected and no rate is invented.
- **Source:** `app/services/invoice.py` (invoice construction).
- **Tests:** product HSN validation is tested in `tests/test_products.py`; the invoice-level zero-tax path has no dedicated test.
- **Status:** PARTIAL — behaviour is intentional, but an invoice can therefore be issued with understated tax. This is disclosed in the report limitations.

### F-15 — GST outward register totals
- **Formula:** B2B invoices add; debit notes add; credit notes subtract. Keys: taxable, CGST, SGST, IGST, total. Cess is carried per row on invoices but is not one of the five reconciled totals.
- **Source:** `app/services/ledger.py:267-314`.
- **Tests:** `tests/test_report_reconciliation.py:36-72`.
- **Status:** VERIFIED. Input tax is explicitly `None` because purchase orders carry a cost, not a tax split.

### F-16 — Annual/period GST limitation
- **Rule:** the register is an outward-supply reconciliation aid, not a statutory GSTR-1 file, and no input-tax register is produced.
- **Source:** `app/services/ledger.py:305-314`; report limitations at `app/services/reports.py:976-982`.
- **Status:** VERIFIED limitation.

---

## 2. Document numbering

### F-17 — Financial year label
- **Formula:** April–March year; a date on or after 1 April belongs to `YYYY-(YYYY+1)`, rendered `"YY-YY"`.
- **Source:** `app/services/numbering.py:30-34`.
- **Status:** VERIFIED (code).

### F-18 — Next document number
- **Formula:** format `"{prefix}/{FY without dash}/{sequence:06d}"`; sequence is taken from a row-locked counter (`SELECT … FOR UPDATE`), initialised from the highest existing serial when missing; result capped at 16 characters.
- **Source:** `app/services/numbering.py:36-95`.
- **Conditions:** consecutive within a document type and financial year; row lock prevents two concurrent users receiving the same number.
- **Tests:** document numbers are exercised by order/invoice tests; concurrency is not directly tested.
- **Status:** VERIFIED (code). Concurrency safety is reasoned from the lock, not load-tested.

### F-19 — Goods-receipt and approval numbers
- **Formula:** `GRN-YYYYMMDD-XXXXXX` (six hex characters) for goods receipts; `AP-YYYYMMDD-NNNNN` for approval requests.
- **Source:** `app/api/purchase_orders.py:341-343`; `app/services/hr.py:153-167`.
- **Status:** VERIFIED (code).

---

## 3. Sales orders, credit and approval

### F-20 — Credit exposure
- **Formula:** sum `SalesOrder.total` for a distributor where status is `pending_approval`, `approved` or `dispatched`, optionally excluding the order being tested.
- **Source:** `app/services/sales.py:12-26`.
- **Conditions:** drafts do not consume credit; cancelled and rejected orders do not; receipts are not netted (the exposure is order value, not invoice balance).
- **Tests:** `tests/test_approvals.py`.
- **Status:** VERIFIED. The limitation “payments are not tracked in exposure” is shown in the UI.

### F-21 — Available credit
- **Formula:** `available = max(credit_limit − exposure, 0)`.
- **Source:** `app/api/distributors.py` (`_out`).
- **Status:** VERIFIED (code).

### F-22 — Submit-order approval reasons
- **Formula:** on submit, compute exposure including the order. Add reason `credit_limit` when `credit_limit > 0` and projected exposure exceeds it. Add reason `discount` when any line's implied discount exceeds the applicable threshold (slab override else 10 percent). Any reason routes the order to `pending_approval`; otherwise it becomes `approved`.
- **Source:** `app/api/sales_orders.py:242-300`.
- **Conditions:** only a draft can be submitted; the distributor must be active; stock availability is checked; a zero credit limit is treated as unlimited.
- **Tests:** `tests/test_approvals.py:30-76`.
- **Status:** VERIFIED.

### F-23 — Approval decision authority
- **Formula:** a `credit_limit` request can only be decided by a literal administrator; ordinary sales-order decisions need `approval:decide` or administrator; the requester and the order creator cannot decide; a request can be decided once. The same rules compute the queue's `can_decide` flag (HR types additionally need their per-type permission — `hr:leave_approve`, `hr:attendance_manage` or `hr:payroll_approve`), so the screen offers a decision only where the server would accept it.
- **Source:** `app/api/approvals.py:192-253`.
- **Tests:** `tests/test_approvals.py:30-76`.
- **Status:** VERIFIED.

### F-24 — Dispatch preconditions
- **Formula:** order must be `approved`; dispatch is refused if already dispatched; credit is re-checked over the `dispatched` status set unless the approval waived the credit limit; stock is allocated FEFO and movements posted; an invoice is created in the same transaction; failure to invoice rolls stock back.
- **Source:** `app/api/sales_orders.py:323-395`.
- **Tests:** dispatch and invoice creation are exercised throughout `tests/test_approvals.py` and `tests/test_report_reconciliation.py`.
- **Status:** VERIFIED. The rollback path on invoice failure was read in code but not fault-injected by a test.

### F-25 — Cancel-order rule
- **Formula:** a dispatched order cannot be cancelled; cancellation requires a reason; status becomes `cancelled`.
- **Source:** `app/api/sales_orders.py:302-321`.
- **Status:** VERIFIED (code).

### F-26 — Distributor completion gaps
- **Formula:** `missing = ["state_code" if absent] + ["gstin" if registered and absent]`; `needs_completion = bool(missing)`.
- **Source:** `app/api/distributors.py:_completion`.
- **Conditions:** registered parties derive PAN and state from the GSTIN, so in practice only an unregistered record can lack a state; the GSTIN branch remains for migrated rows.
- **Status:** VERIFIED (code).

### F-27 — Credit-limit change authority
- **Formula:** creating a distributor with a positive credit limit, or changing a limit, requires `credit:manage`; a reason is required for a change.
- **Source:** `app/api/distributors.py:create_distributor`, `change_credit_limit`.
- **Status:** VERIFIED (code).

---

## 4. Stock

### F-28 — Eligible stock
- **Formula:** a batch is eligible when `owner = "HERBANOVA"`, `on_hand > 0`, and it is not expired on the business date.
- **Source:** `app/services/sales.py:28-40`.
- **Conditions:** manufacturer-owned stock is excluded from saleable availability.
- **Status:** VERIFIED (code).

### F-29 — Available stock
- **Formula:** sum `on_hand` over eligible batches for the product and optional warehouse.
- **Source:** `app/services/sales.py:37-40`.
- **Status:** VERIFIED (code).

### F-30 — FEFO allocation
- **Formula:** lock eligible batches ordered by expiry ascending with null expiries last; take `min(remaining, on_hand)` from each; stop when fulfilled; report any shortfall.
- **Source:** `app/services/sales.py:42-95`.
- **Conditions:** earliest expiry first; a line's allocation is tied to the batch that supplied it.
- **Tests:** dispatch in `tests/test_report_reconciliation.py` creates the invoice this relies on.
- **Status:** VERIFIED (code).

### F-31 — Stock posting
- **Formula:** lock the batch, reject a zero movement, reject a movement that would make `on_hand` negative, write an immutable `StockMovement` row, then increment `on_hand` by `qty_delta`.
- **Source:** `app/services/inventory.py:8-40`.
- **Conditions:** a duplicate `(batch, movement_type, ref)` is refused by a unique index and surfaced as 409.
- **Tests:** stock report agreement in `tests/test_report_reconciliation.py:118-123`.
- **Status:** VERIFIED.

### F-32 — Stock report reconciliation
- **Formula:** reported closing quantity = sum of `Batch.on_hand`; independent record value = sum of `StockMovement.qty_delta`; both must agree. Opening balance is assumed zero because the ledger is append-only from inception.
- **Source:** `app/services/reports.py:799-837`.
- **Tests:** `tests/test_report_reconciliation.py:118-123`.
- **Status:** VERIFIED. If historical data were imported without opening movements, the check would correctly expose the difference rather than hide it.

---

## 5. Invoices and notes

### F-33 — Invoice construction
- **Formula:** for each order line, recompute discount, taxable value and each tax head with `line_tax`; accumulate gross, discount, taxable, CGST, SGST, IGST, cess, tax and round-off; grand total is the sum of line totals; amount in words is generated; `copy_designation` starts as `ORIGINAL`.
- **Source:** `app/services/invoice.py:41-140`.
- **Conditions:** seller and buyer identity are snapshotted onto the invoice so later master changes do not rewrite history.
- **Status:** VERIFIED (code), totals verified by tests.

### F-34 — Invoice immutability
- **Formula:** `PUT` and `DELETE` on an issued invoice return 405. Financial fields cannot be changed by any endpoint.
- **Source:** `app/api/invoices.py:390-395`.
- **Tests:** enforced by design; no test asserts the 405 explicitly.
- **Status:** VERIFIED (code).

### F-35 — Post-billing amendment scope
- **Formula:** only `delivery_challan_number`, `vehicle_number`, `transporter_name`, `eway_bill_number`, `eway_bill_date` and `notes` may change; e-way number and date must be supplied together; at least one field must change; administrator only.
- **Source:** `app/api/invoices.py:330-386`.
- **Tests:** `tests/test_approvals.py:78-102` proves a non-permitted field (`grand_total`) is dropped and a permitted one is applied after approval.
- **Status:** VERIFIED.

### F-36 — Invoice cancellation
- **Formula:** cancellation requires a reason, is refused if any issued credit or debit note is linked, keeps the document number, and marks the copy `CANCELLED`.
- **Source:** `app/api/invoices.py:278-328`.
- **Status:** VERIFIED (code).

### F-37 — Credit/debit note cap
- **Formula:** a note line may not exceed the invoiced quantity; a note total may not exceed the invoice value; notes are linked to the invoice and cannot be edited after issue.
- **Source:** `app/api/credit_notes.py`, `app/api/debit_notes.py`; note totals are folded into receivables and GST.
- **Tests:** note behaviour is exercised indirectly through receivables/GST reconciliation; no dedicated note-cap test was found.
- **Status:** PARTIAL — the rules were read in source, but this stage did not locate a test that asserts the cap on quantity and total independently.

### F-38 — Credit note return to stock
- **Formula:** when a warehouse is chosen, credited quantities are returned to the same batches they were issued from, inside that warehouse; the return cannot exceed what the order issued.
- **Source:** `app/api/credit_notes.py`; UI at `static/js/app.js:1775-1777`.
- **Status:** VERIFIED (code); no dedicated test.

### F-39 — Receivables per invoice
- **Formula:** `outstanding = invoice.grand_total + credit_notes.total − debit_notes.total − receipts`.
- **Source:** `app/services/ledger.py:74-95`.
- **Tests:** `tests/test_report_reconciliation.py:61-72`, `97-104`.
- **Status:** VERIFIED. Only issued invoices are included; cancelled invoices drop out.

### F-40 — Ageing buckets
- **Formula:** `days = max(0, (as_of − invoice_date).days)`; bucket 0–30, 31–60, 61–90, 90+; only rows with `outstanding > 0`; bucket total sums net outstanding.
- **Source:** `app/services/ledger.py:152-203`.
- **Conditions:** bucket age is measured from the invoice date so historical reports stay comparable; the due-date position is a separate split (F-83). The report date can be supplied.
- **Tests:** `tests/test_report_reconciliation.py:74-95`.
- **Status:** VERIFIED.

---

## 6. Payables and accounting

### F-41 — Received purchase value
- **Formula:** for each goods-receipt line, `qty received × purchase-order line unit_cost`; sum by purchase order. Goods receipts record quantity, not price, so the order line supplies the cost.
- **Source:** `app/services/ledger.py:98-118`.
- **Conditions:** a receipt cannot exceed the ordered quantity; only orders with a positive received value appear in payables.
- **Status:** VERIFIED (code).

### F-42 — Payables
- **Formula:** `outstanding = received_value − supplier payments allocated to the purchase order`.
- **Source:** `app/services/ledger.py:121-148`.
- **Tests:** `tests/test_report_reconciliation.py:136-144` requires a real cross-check for the payables report.
- **Status:** VERIFIED.

### F-43 — Receipt/payment allocation and advance
- **Formula:** a receipt (money in) belongs to a distributor; a payment (money out) belongs to a supplier. With `purpose = outstanding`, the amount settles open documents oldest-first (or a named document first) and `advance = amount − Σ allocations` is held when the money exceeds what is open. With `purpose = advance`, `allocations = []` and `advance = amount`; no invoice or order is named. New entries leave the legacy `invoice_id` / `purchase_order_id` columns null so an allocation is counted once. An existing entry recorded before allocations named its document outright and counts as fully settled. Dates cannot be in the future or more than ten years old.
- **Source:** `app/services/advances.py:120-185`, `app/api/accounts.py` (`record_entry`).
- **Conditions:** cross-party allocation is refused; cancelled invoices cannot receive money; an advance that names a document is refused 422; a named settled document keeps the 422 while a general entry with nothing open records the whole amount as an advance.
- **Tests:** `tests/test_accounts_advances.py::test_receipt_settles_oldest_invoices_and_holds_the_excess`, `::test_an_advance_cannot_name_a_document`.
- **Status:** VERIFIED.

### F-43A — Settlement date rule
- **Formula:** a receipt may settle only invoices with `invoice_date <= paid_on`; a supplier payment may settle only orders whose latest goods receipt has `received_on <= paid_on`. Money that cannot settle a document that did not exist on its day stays in the advance.
- **Source:** `app/services/advances.py:120-185`, `app/services/ledger.py` (`payable_rows`, `received_on`).
- **Tests:** `tests/test_accounts_advances.py::test_a_receipt_cannot_settle_an_invoice_issued_later`.
- **Status:** VERIFIED.

### F-43B — Advance draw-down
- **Formula:** at invoice issue and at goods receipt, take the party's unapplied money paid on or before the document date, oldest first; allocate `min(advance, document value)` to the document, dated on the document day; the remainder stays available. The allocation is audited as `advance_applied` on the dispatch or goods-receipt event.
- **Source:** `app/services/advances.py:186-210`; called from `app/services/invoice.py` and `app/api/purchase_orders.py`.
- **Tests:** `tests/test_accounts_advances.py::test_advance_is_drawn_down_by_a_later_invoice`, `::test_supplier_advance_settles_goods_received_later`.
- **Status:** VERIFIED.

### F-44 — Distributor ledger
- **Formula:** invoices debit the distributor; credit notes and receipts credit; debit notes debit. A receipt credits its full amount once and its note names the invoices it settled and the advance held, because the invoice debit is already in the statement; posting the settlement as a second debit would count the money twice. Running balance is the net amount owed; a negative closing balance is an advance held. `available_advance` reports the unapplied remainder.
- **Source:** `app/services/ledger.py:301-350`.
- **Tests:** `tests/test_accounts_advances.py::test_receipt_settles_oldest_invoices_and_holds_the_excess`.
- **Status:** VERIFIED (code).

### F-45 — Supplier ledger
- **Formula:** goods received value credits the supplier account (what the business owes); payments debit it; a payment debits its full amount once and its note names the orders settled and the advance held. Running balance is the net amount owed; a negative closing balance is an advance paid. `available_advance` reports the unapplied remainder.
- **Source:** `app/services/ledger.py:352-384`.
- **Tests:** `tests/test_accounts_advances.py::test_supplier_advance_settles_goods_received_later`.
- **Status:** VERIFIED (code).

### F-46 — Trial balance
- **Formula:** post each issued invoice: debit Receivables by grand total; credit Sales by taxable; credit each output-tax head; post round-off to the credit side when positive and the debit side when negative. Credit notes reverse the entries; debit notes repeat them. For each receipt, debit Cash/Bank by the full amount, credit Receivables by the settled part and **Advances from distributors** by the remainder. For each supplier payment, debit Payables by the settled part and **Advances to suppliers** by the remainder, and credit Cash/Bank by the full amount. A legacy entry that named its document counts as fully settled. The report asserts total debits equal total credits.
- **Source:** `app/services/ledger.py:446-553`.
- **Tests:** `tests/test_report_reconciliation.py`; `tests/test_accounts_advances.py::test_advance_is_not_revenue_or_a_purchase`.
- **Status:** VERIFIED. This is a document-derived summary, not a full double-entry ledger; there are no journal entries attached to a document.

### F-47 — Report period boundary
- **Formula:** `from`/`to` are inclusive; `from > to` raises 422.
- **Source:** `app/api/reports.py:89-92`.
- **Tests:** `tests/test_report_reconciliation.py:97-104`, `155-159`.
- **Status:** VERIFIED.

### F-48 — Unsupported report filter
- **Formula:** a filter not advertised for a report is refused with 422 rather than ignored.
- **Source:** `app/api/reports.py:95-108`; `FILTER_KEYS` at `app/services/reports.py:158-184`.
- **Tests:** `tests/test_report_reconciliation.py:155-159`; `tests/test_reports.py:102-109`.
- **Status:** VERIFIED.

### F-49 — Report reconciliation flag
- **Formula:** `reconciled = all(check.ok)`; the report returns every check with report value, independent record value and a boolean. `row_count` alone is not independent evidence.
- **Source:** `app/services/reports.py:248-277`.
- **Tests:** `tests/test_report_reconciliation.py:136-144` explicitly demands a non-`row_count` check for eight financial reports.
- **Status:** VERIFIED for the eight financial reports; PARTIAL for 17 registers that still supply only `row_count` (see `FORMULA_RECONCILIATION_TESTS.md`).

### F-50 — Report sorting and paging
- **Formula:** sort by a requested column present in the table, nulls last; page with `page_size` 1–500 (default 100); `total_rows` is the full row count before slicing.
- **Source:** `app/api/reports.py:120-141`.
- **Conditions:** sorting and paging happen in memory after the report is built, not in SQL. This is correct for the current data volume but does not scale indefinitely.
- **Tests:** `tests/test_reports.py:27-40`.
- **Status:** PARTIAL — correct, with a scalability limit recorded in the Stage 1 re-audit (R-02).

---

## 7. Payroll

### F-51 — Working days
- **Formula:** every calendar day in the month except the employee's shift weekly offs (default Saturday/Sunday) and holidays that apply to the employee's office or branch.
- **Source:** `app/services/hr.py:136-150`.
- **Tests:** `tests/test_hr.py:49-133`.
- **Status:** VERIFIED.

### F-52 — Payable days and loss of pay
- **Formula:** `payable = min(working_days, present + paid_leave)`; `lop = max(0, working_days − payable)`; a half-day counts 0.5. When no attendance rows exist at all, `present = working_days` and the entry carries a note saying paid days defaulted.
- **Source:** `app/services/payroll.py:60-79`, `137`.
- **Conditions:** `PAID_STATUSES` drives what counts; unpaid leave and absence do not.
- **Tests:** `tests/test_hr.py:49-133`.
- **Status:** VERIFIED. The “no attendance means full pay” default is deliberate but is a policy risk; it is disclosed in the entry note.

### F-53 — Pro-rata ratio
- **Formula:** `ratio = payable_days ÷ working_days` (zero when there are no working days).
- **Source:** `app/services/payroll.py:79`.
- **Status:** VERIFIED.

### F-54 — Basic and earning amounts
- **Formula:** BASIC is computed first as `amount (or component default) × ratio` and accumulates. Then each earning:
  - `percent_basic`: `basic × percent ÷ 100`, not prorated.
  - otherwise: `raw × ratio`, except codes `INCENTIVE`, `OVERTIME`, `BONUS`, `REIMBURSEMENT`, which are paid in full.
- **Source:** `app/services/payroll.py:81-114`; `NON_PRORATED` constant in the same module.
- **Status:** VERIFIED (code).

### F-55 — Deductions
- **Formula:** `percent_basic` → `basic × percent ÷ 100`; `percent_gross` → `gross × percent ÷ 100`; otherwise fixed amount.
- **Source:** `app/services/payroll.py:115-134`.
- **Status:** VERIFIED (code).

### F-56 — Net pay
- **Formula:** `gross = sum(earnings)`; `deductions = sum(deductions)`; `net = gross − deductions`; all quantised to paisa.
- **Source:** `app/services/payroll.py:135-136`.
- **Tests:** `tests/test_hr.py:49-133`.
- **Status:** VERIFIED.

### F-57 — Salary-structure effective dating
- **Formula:** choose the salary structure in force for the employee over the payroll month (effective-from on or before the period, latest first).
- **Source:** `app/services/payroll.py:36-45`.
- **Status:** VERIFIED (code).

### F-58 — Payroll state transition
- **Formula:** `draft → under_review → approved → processed → paid`; prepare/recalculate is allowed in draft and under_review; submit in under_review; process in approved; pay in processed. The preparer cannot approve their own payroll.
- **Source:** `app/api/hr.py` payroll endpoints; `app/services/hr_approvals.py:_payroll`.
- **Tests:** `tests/test_hr.py:49-133`.
- **Status:** VERIFIED.

### F-80 — Employees skipped by a payroll run
- **Rule:** an active employee with no entry is listed, never dropped silently (M-06). The list is returned by `POST /api/hr/payroll/periods/{id}/prepare` and by `GET /api/hr/payroll/periods/{id}` with a reason: *No active salary structure covers this month* (no active structure effective over the month) or *Not in the prepared entries*. An employee who joined after the month or left before it is not reported: they were not employed in the period. The skipped codes are written to the payroll audit entry.
- **Source:** `app/services/payroll.py:skipped_employees`; `app/api/hr.py:prepare_payroll`, `get_period`.
- **Tests:** `tests/test_hr.py::test_payroll_prepare_submit_approve_process`.
- **Status:** VERIFIED.

### F-81 — Payroll in the profit and loss
- **Formula:** a month wholly inside the window counts in full when its period is `approved`, `processed` or `paid`. A month the window cuts short counts that same approved gross allocated by each employee's working-day share of the month:
  `allocated = Σ_employee gross × (working days of the employee inside the window ÷ working days of the employee in the month)`.
  A month with no approved payroll is never allocated; it is named in GAP-P03 and excluded. The allocation is marked `prorated: true` on the period item. Net profit stays unavailable while any month in the window is missing or unapproved.
- **Source:** `app/services/profit_loss.py:_payroll`, `_allocate`.
- **Tests:** `tests/test_profit_loss.py::test_cut_month_is_allocated_by_working_days_not_guessed`, `::test_payroll_gap_names_absent_and_unapproved_months`.
- **Status:** VERIFIED against the service and the reconciliation export. The Payroll (gross) line now prints the provable partial total with a *Partial* marker instead of “No data yet”; net profit is still refused until the window is complete.

### F-82 — Financial-year close
- **Rule:** an Indian financial year runs 1 April to 31 March and is labelled `YYYY-YY` (`2025-26`). Only a year whose last day has passed can be closed, and not one before the earliest document in the book (`min` of invoice, credit-note, debit-note, payment, expense, PO and GRN dates). A close needs a reason of at least five characters. While a year is closed, a document dated inside it is refused with HTTP 423: dispatch and its invoice, receipts and payments, credit and debit notes, invoice cancellation, expense creation/reversal, cost corrections/backfill and free-sample notes. Only the Administrator may reopen, with a reason; both actions are audited on `financial_year:{label}`. An active accounting-month lock is checked first and wins.
- **Source:** `app/services/periods.py:fy_start`, `fy_end`, `fy_label`, `label_bounds`, `refuse_if_closed`, `close_year`, `reopen_year`; `app/api/periods.py`; `app/models/accounts.py:FinancialYearClose`.
- **Tests:** `tests/test_periods.py` (FY maths, completed-year rule, refusal, roles, reopen, audit).
- **Status:** VERIFIED (API and tests). The screen is not browser-verified.

### F-83 — Invoice due date and ageing due split
- **Formula:** at issue the invoice copies the distributor's `payment_terms_days`; `due_date = invoice_date + terms`. No terms stores both fields NULL. Ageing reads the stored due date, never today's master: `days_overdue = max(0, as_of − due_date)`; a row is `overdue` when `due_date < as_of`, `due_this_week` when `as_of ≤ due_date ≤ as_of + 7`, `not_yet_due` after that, and `no_due_date` when NULL. The four bucket totals sum to outstanding and their counts sum to the invoice count. Supplier payables remain an estimate from current terms.
- **Source:** `app/services/invoice.py:create_invoice_for_order`; `app/services/ledger.py:ageing_rows`; `app/models/core.py:Invoice`.
- **Tests:** `tests/test_periods.py::test_invoice_snapshots_terms_and_due_date`, `::test_no_terms_means_no_due_date_not_an_invented_one`, `::test_ageing_splits_outstanding_by_due_date`.
- **Status:** VERIFIED (API and tests). The screen is not browser-verified.

### F-84 — Supplier bill capture
- **Rule:** a supplier bill records the tax the supplier charged head by head (`cgst`, `sgst`, `igst`, `cess`), the taxable value, round-off and total, plus the supplier invoice number, the supplier and an optional purchase order. `tax_total = cgst + sgst + igst + cess`; `total = taxable + tax_total + round_off`, each quantised half-up. The bill number is unique per supplier, not globally. A bill is `posted` or `reversed`; a reversal needs a reason of at least five characters, keeps the row, records who and when, and excludes it from every total. Reversing twice is refused (409), as is a duplicate live bill number.
- **Conditions:** the bill date is refused with HTTP 423 inside a locked accounting month or a closed financial year. Capturing a bill never changes payables: payables stay goods received minus payments.
- **Source:** `app/models/accounts.py:PurchaseInvoice`; `app/api/gst.py`; migration `0026_gst_and_statutory`.
- **Tests:** `tests/test_gst_statutory.py::test_a_supplier_bill_records_its_tax_and_a_wrong_one_is_reversed`, `::test_a_bill_number_is_unique_per_supplier_only`, `::test_a_locked_month_and_a_closed_year_refuse_a_supplier_bill`.
- **Status:** VERIFIED (API, tests and browser probe).

### F-85 — Input register and net GST payable
- **Formula:** the input register totals only `posted` bills. `eligible` is the subset with `itc_eligible = true`; `blocked = posted − eligible`. Net payable is head by head:
  `net[h] = output[h] − eligible_input[h]`; `net_total = Σ net[h]`.
  Blocked input is reported separately and is never subtracted, and creditable expense GST is a memo (`included_in_net: false`) because an expense stores one GST amount with no head split.
- **Conditions:** with no posted bill at all, input, net and the reason are returned with `available: false`; the figure is never reported as zero, which would overstate the payable. A negative net is a credit and is shown as one.
- **Source:** `app/services/gst.py:register`, `net`, `expense_itc`; `app/services/accounting.py:window` (`net_gst`).
- **Tests:** `tests/test_gst_statutory.py::test_net_payable_is_output_less_eligible_input`, `::test_with_no_supplier_bill_input_tax_is_unavailable_not_zero`.
- **Status:** VERIFIED (API, tests and browser probe).

### F-86 — Filed return reconciliation
- **Rule:** one captured return per year, month and form (`GSTR-1`, `GSTR-3B`). For each line, `difference = filed − computed`, quantised half-up; `ok` when `|difference| < 0.005`. Compared lines: outward taxable value and the four outward heads on both forms; the four ITC heads and tax payable after ITC on GSTR-3B. A difference is shown with both figures and both forms' `differences` list, never corrected or hidden. Saving the same month and form replaces that row. An ITC figure on GSTR-1, an unknown form or a future month is refused (422).
- **Conditions:** ITC is compared only when at least one purchase bill exists; before that the line carries the reason and no difference. Filed figures are typed in; the application does not file or read the portal.
- **Source:** `app/services/gst.py:reconciliation`, `_check`; `app/models/accounts.py:GstReturn`.
- **Tests:** `tests/test_gst_statutory.py::test_a_filed_return_is_compared_with_the_registers`.
- **Status:** VERIFIED (API, tests and browser probe).

### F-87 — Statutory dues
- **Formula:** per head (`pf`, `esi`, `pt`, `tds`):
  `withheld_to_date` = vendor TDS from posted bills up to the date (TDS head only) plus payroll statutory deductions from periods with status `approved`, `processed` or `paid` up to the month;
  `deposited_to_date` = sum of challans of that kind paid on or before the window end;
  `outstanding = withheld_to_date − deposited_to_date`.
  `deposited_in_window` counts only challans paid inside the window, so the window and the cumulative position are both visible.
- **Conditions:** a draft payroll is not a liability and contributes nothing. A statutory component with no statutory head is listed with its codes and excluded from every head. A head with no source anywhere reads `available: false` with a reason rather than zero. Challans are not matched to individual deductions; the outstanding line is what no challan covers. An unknown kind or a future period is refused (422).
- **Source:** `app/services/statutory.py:vendor_tds`, `payroll_dues`, `dues`; `app/models/accounts.py:StatutoryChallan`; `app/models/accounts.py:PurchaseInvoice`.
- **Tests:** `tests/test_gst_statutory.py::test_statutory_dues_read_vendor_tds_and_approved_payroll_only`, `::test_a_draft_payroll_is_not_a_statutory_liability`.
- **Status:** VERIFIED (API, tests and browser probe).

---

## 8. HR attendance, leave and geofence

### F-59 — Business date
- **Formula:** today's date in `Asia/Kolkata`, not the server's UTC date.
- **Source:** `app/services/hr.py:26-27`.
- **Status:** VERIFIED (code).

### F-60 — Late arrival
- **Formula:** `late = max(0, floor((check_in_local − shift_start) minutes) − grace_minutes)`; zero when the shift or check-in is missing.
- **Source:** `app/services/hr.py:35-42`.
- **Tests:** `tests/test_hr.py:135-175`.
- **Status:** VERIFIED.

### F-61 — Early departure
- **Formula:** `early = max(0, floor((shift_end − check_out_local) minutes))`; an end time at or before the start is treated as the next day (overnight shift).
- **Source:** `app/services/hr.py:45-56`.
- **Tests:** `tests/test_hr.py:135-175`.
- **Status:** VERIFIED.

### F-62 — Geofence distance
- **Formula:** haversine great-circle distance in metres with earth radius 6 371 000 m; `inside` when distance ≤ `office.geofence_radius_m or 200`; `unavailable` when coordinates are missing; `na` when the office has no coordinates.
- **Source:** `app/services/hr.py:70-86`.
- **Tests:** `tests/test_hr.py:221-253`.
- **Status:** VERIFIED.

### F-63 — Approved leave writes attendance
- **Formula:** for each date in the leave range, create or update attendance to `paid_leave` for a paid leave type, else `unpaid_leave`; an existing `od` status is preserved.
- **Source:** `app/services/hr.py:99-109`.
- **Tests:** `tests/test_hr.py:11-47`.
- **Status:** VERIFIED.

### F-64 — Approved OD writes attendance
- **Formula:** for each date in the OD range, set attendance to `od` unless it is approved paid or unpaid leave.
- **Source:** `app/services/hr.py:112-120`.
- **Status:** VERIFIED (code).

### F-65 — Leave balance default
- **Formula:** when no balance row exists, create one with `entitled = leave_type.default_days`; approval moves days from pending and increments used.
- **Source:** `app/services/hr.py:123-133`; `app/services/hr_approvals.py:_leave`.
- **Tests:** `tests/test_hr.py:11-47`.
- **Status:** VERIFIED.

### F-66 — HR segregation of duties
- **Formula:** nobody may decide their own request; each HR request type checks its own permission (`hr:leave_approve`, `hr:attendance_manage`, `hr:payroll_approve`); the payroll preparer cannot approve.
- **Source:** `app/services/hr_approvals.py:22-160`.
- **Tests:** `tests/test_hr.py:11-47`.
- **Status:** VERIFIED.

### F-76 — Attendance requirement resolution
- **Formula:** consider only active rules whose `effective_from <= day <= effective_to` (open ends allowed) where every non-null target matches the employee. Score = employee 1000, office 100, designation 10, branch 1. Choose the highest score, then the lowest `priority`, then the highest `id`. If nothing matches, the requirement is `required: true, self_service: true`, source `"Company default"`. A rule with only an office target reports `"Office default (<name>)"`.
- **Source:** `app/services/hr.py:resolve_attendance_requirement`, `rule_label`.
- **Tests:** `tests/test_hr_sites.py::test_rule_validation_precedence_and_effective_dates`.
- **Status:** VERIFIED.

### F-77 — Attendance gating
- **Rule:** before a self check-in/out, correction request, manual entry or bulk row, the resolved requirement is applied. `required = false` refuses every attendance write with **409** naming the source; `self_service = false` refuses the employee's own punch. A rule's `shift_id` replaces the employee's shift for that day; its `attendance_mode` replaces the office mode while the rule is in force. An office's own mode is never rewritten.
- **Source:** `app/services/hr.py:require_attendance`, `require_self_service`, `requirement_shift`; `app/api/hr.py` attendance endpoints.
- **Tests:** `tests/test_hr_sites.py::test_exempt_employee_is_blocked_from_manual_bulk_and_correction`, `::test_self_service_check_in_obeys_the_rule`.
- **Status:** VERIFIED.

### F-78 — Exempt day in the monthly register and payroll
- **Rule:** a day the policy does not require is returned as `status: null, not_required: true`, counted in `not_required_days`, and drawn as `–` with the legend “not required”. It is **not** a gap and **not** an absence. Payroll payable days for an exempt employee = `working_days − recorded unpaid days` (paid leave and OD are not deducted); the period note states attendance is not required.
- **Source:** `app/services/hr.py:monthly_attendance`; `app/services/payroll.py` exempt branch.
- **Tests:** `tests/test_hr_sites.py::test_monthly_register_marks_exempt_days_as_not_required`, `::test_payroll_does_not_invent_absence_for_exempt_employees`.
- **Status:** VERIFIED.

### F-79 — Office belongs to one branch
- **Rule:** an employee may name a branch, an office, or both. When both are named and the office’s branch differs, the request is refused with **422**; when only the office is named, the branch is inferred from it. A branch or office with active staff cannot be deactivated, and an office cannot be moved to another branch, until those employees are reassigned (409).
- **Source:** `app/api/hr.py:_normalise_employee_location`, `update_branch`, `update_office`.
- **Tests:** `tests/test_hr_sites.py::test_sites_crud_and_employee_assignment`.
- **Status:** VERIFIED.

---

## 9. Tax identity validation

### F-67 — GSTIN checksum
- **Formula:** 15-character structure validated; the final check character is computed in base 36 as `(36 − (sum of positional values × alternating weights) mod 36) mod 36`, using the GSTIN's character values.
- **Source:** `app/services/tax_ids.py:26-67`.
- **Status:** VERIFIED (code).

### F-68 — PAN checksum
- **Formula:** 10-character structure validated; the tenth character is checked against a mod-26 letter calculation from the first nine.
- **Source:** `app/services/tax_ids.py:69-100`.
- **Status:** VERIFIED (code).

### F-69 — Registered-party identity
- **Formula:** a registered party must have a GSTIN; state is the first two GSTIN characters; PAN defaults to GSTIN characters 3–12; an explicit state or PAN that disagrees with the GSTIN is refused. An unregistered party must not have a GSTIN and must have a state when `require_state` is true.
- **Source:** `app/services/tax_ids.py:103-162`.
- **Status:** VERIFIED (code). `require_state=False` is used for distributor creation so an incomplete buyer stays honestly incomplete.

### F-70 — Identity normalisation contract
- **Formula:** `normalize_identity` returns the exact tuple to store or raises `ValueError`; API layers convert that to HTTP 422.
- **Source:** `app/services/tax_ids.py:147-162`; `app/api/distributors.py:_identity`.
- **Status:** VERIFIED.

---

## 10. Governance, audit and data preservation

### F-71 — Audit trail
- **Rule:** every material create, change, approval, cancellation, export and sign-in writes an `AuditLog` row with actor, action, record reference and a details object. Secrets are stripped before writing.
- **Source:** `app/services/audit.py`; callers throughout `app/api/`.
- **Tests:** `tests/test_reports.py:163-181` checks report export auditing; the broader audit trail is covered by the app’s audit screen.
- **Status:** VERIFIED (code).

### F-72 — Permission enforcement
- **Rule:** access is granted by `require(permission)` / `require_admin(permission)` at the API, independent of which links the UI hides. The UI hiding a link is convenience only.
- **Source:** `app/core/rbac.py`; `static/index.html:529`.
- **Tests:** `tests/test_reports.py:5-25`, `112-118`; `tests/test_hr.py:5-10`; `tests/test_products.py:53-57`.
- **Status:** VERIFIED.

### F-73 — No destructive data endpoint without secondary password
- **Rule:** the database-reset endpoint requires the administrator secondary password; it is the only wipe path exposed by the API.
- **Source:** `app/api/db_reset.py`.
- **Conditions:** this register did not execute a reset. The Stage 3 work does not touch business data.
- **Status:** VERIFIED (code); the endpoint was not exercised in this stage.

### F-74 — Document history is additive
- **Rule:** invoices are never edited or deleted; cancellation is a status change; credit/debit notes correct financial values; stock movements are append-only; payments are never edited.
- **Source:** `app/api/invoices.py`, `app/api/credit_notes.py`, `app/services/inventory.py`, `app/api/accounts.py`.
- **Status:** VERIFIED (code). This is the basis of the “absolute data preservation” requirement; backups must still be taken before any migration.

### F-75 — Backup verification
- **Rule:** the backup/restore tool compares a restored copy with the live database and fails on any difference.
- **Source:** backup tool delivered in Stage 4 (MOD-09); tests in `tests/test_backup_restore.py`.
- **Tests:** `tests/test_backup_restore.py:14-36` — passed in this stage's run.
- **Status:** VERIFIED.

---

## Appendix A — Rules that could not be fully verified

| Item | Why it remains open | What would close it |
|---|---|---|
| Reverse-charge presentation on the printed invoice | The tax arithmetic is verified; the PDF wording was not opened. | Render a reverse-charge invoice and inspect the PDF text. |
| Credit/debit note quantity and total caps | Read in source, no dedicated test found. | Add tests that attempt an over-quantity note and an over-value note. |
| Concurrent document numbering | Reasoned from `FOR UPDATE`; no parallel load test. | Two simultaneous dispatches on a fresh database, assert distinct numbers. |
| Payroll “no attendance = full pay” policy | Deliberate default; not a coding error. | Business sign-off and a test pinning the intended behaviour. |
| In-memory report sorting/paging | Correct at current volume; unbounded growth. | Move sort/page into SQL or cap the report row set (R-02). |
| GST input register / ITC | **Closed 3 Nov 2026.** Supplier bills now capture tax head by head (F-84) and the input register, net payable and blocked-credit split are built (F-85). The remaining limit is judgement: eligibility is recorded, not decided, and expense GST has no head split. | Owner-approved eligibility rules and a head split on expenses. |
| Round-off distribution across tax heads | Round-off is a single document-level line; no per-head allocation. | Confirm with the tax advisor whether the statutory return expects a different split. |

## Appendix B — Source map

| Area | Primary source |
|---|---|
| Tax arithmetic | `app/services/tax.py` |
| Order preview | `app/services/order_tax.py` |
| Discount slabs | `app/services/discounts.py` |
| Numbering | `app/services/numbering.py` |
| Sales/credit/FEFO | `app/services/sales.py`, `app/api/sales_orders.py` |
| Stock posting | `app/services/inventory.py` |
| Invoicing | `app/services/invoice.py`, `app/api/invoices.py` |
| Ledgers and reports | `app/services/ledger.py`, `app/services/reports.py` |
| Payroll | `app/services/payroll.py` |
| HR attendance | `app/services/hr.py` |
| HR decisions | `app/services/hr_approvals.py` |
| Identity validation | `app/services/tax_ids.py` |
| Rules and constants | `app/core/rules.py`, `app/core/permissions.py` |
