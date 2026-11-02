# Accounts data gaps: verified register

**Verified:** 2 November 2026, branch `feature/accounting-expenses` at `dc394a2`.
**Method:** read-only review of the models, services, routes and screens. No
database writes and no HTTP requests were made for this register.
**Source of the claims:** the "Data gaps" panel on the Accounting & Finance
screen and the text pasted for review.

The gap codes are defined once in `app/services/accounting.py:35-54` and are
returned by `/api/accounts/report` (`app/services/accounting.py:210-211`). The
screen renders them in `renderAccGaps` (`static/js/app.js:2356-2363`).

## Verdict summary

| Code | Claim | Verdict |
|---|---|---|
| GAP-A03 | Financial-year close | Accurate. The lock also blocks free-sample notes, which the wording does not mention. |
| GAP-A04 | Invoice due dates | Accurate. |
| GAP-A05 | Input GST and net GST payable | Accurate for purchases. The absolute wording "purchase-side tax is not captured" is too broad: expense GST and its creditable flag are captured. |
| GAP-A06 | GSTR-1 / GSTR-3B reconciliation | Accurate. |
| GAP-A07 | TDS and other statutory dues | **Partly inaccurate.** Employee payroll TDS is recorded as a statutory deduction head. Vendor TDS (section, deduction, challan) is not recorded. |
| GAP-A08 | Vouchers, journal and day book | Accurate. |
| GAP-A09 | Bank reconciliation | Accurate. |
| GAP-A10 | Opening balances and balance sheet | Accurate, but the stated reason is incomplete. A balance sheet also lacks expense postings, inventory, fixed assets and capital accounts. |
| Panel intro | "Each gap links to the screen that fixes it" | **Not true today.** None of the GAP-A03 to GAP-A10 entries carries a `fix` link, so the panel renders no link for them. |

## Per-gap evidence

### GAP-A03: Financial-year close

**Claim:** accounting months can be locked; a locked month refuses cost
corrections and expense creation or reversal; invoice changes, credit notes,
receipts, payments and a year-end close are not covered.

**Verified.**
- The period-lock table already accepts the `accounting` scope:
  `app/models/hr.py:520-527`. The resolver is
  `active_period_lock` in `app/services/hr.py:489-494`.
- Lock, list and unlock routes exist at `/api/accounts/period-locks`:
  `app/api/costs.py:28` and `app/api/costs.py:97-153`. Unlock is
  Administrator-only (`require_admin` at `app/api/costs.py:139`).
- Enforcement:
  - purchase-cost correction and cost backfill: `app/services/costing.py:659-671`
    and `app/services/costing.py:968-980`;
  - expense create and reverse: `app/api/expenses.py:187-194`;
  - free-sample note create, approve and historical correction:
    `app/services/foc.py:75-82`, called at lines 188, 226 and 510.
- No lock check exists in the invoice, credit-note, receipt or payment flows:
  a search for `active_period_lock` finds no use in `app/api/invoices.py`,
  `app/api/credit_notes.py`, `app/api/accounts.py`, `app/api/purchase_orders.py`
  or `app/api/sales_orders.py`.
- There is no year-end close object or route; the lock table is monthly only.

**Addition:** the claim does not mention free samples, but the lock already
blocks them.

**Screen/route that closes it:** the route exists; the UI does not. The HR
"Period locks" drawer only offers `attendance` and `payroll`
(`static/js/app.js:4490-4504`). An accounting lock can only be created through
the API today. Closing it needs an Accounting period-lock panel (or an
`accounting` option in that drawer) calling the existing
`/api/accounts/period-locks` routes. Extending the lock to credit notes,
receipts and payments is a separate change in those services.

### GAP-A04: Invoice due dates

**Claim:** an invoice carries no due date; payables due dates are estimated from
the supplier's current payment terms and the latest receipt.

**Verified.**
- `Invoice` stores `invoice_date` (`app/models/core.py:341`) but no due date or
  payment-terms snapshot; the class runs from `app/models/core.py:324` to 390.
- The ageing code says the same: `app/services/ledger.py:163-169`.
- Payables are estimated from `Supplier.payment_terms_days`
  (`app/models/suppliers.py:28-47`) and the latest receipt, as documented in
  `app/services/accounting.py:229-293` (see the note at line 293).
- Distributor terms exist at `app/models/core.py:208`, but they are master
  values, not frozen on the invoice.

**Screen/route that closes it:** Billing (`#/billing`) creates the invoice and
Customers & distributors (`#/customers`) / Suppliers (`#/suppliers`) hold the
terms. Closing the gap needs a due-date column on `invoices` (Alembic
migration), a field on the invoice payload and PDF, and their display on the
receivables/ageing tables.

### GAP-A05: Input GST and net GST payable

**Claim:** purchase-side tax is not captured; only output GST is reported.

**Verified for purchases.**
- A purchase-order line stores only `unit_cost` and `rate_remark`; there is no
  tax split: `app/models/core.py:145-162`.
- The GST register returns `input_register: None` and says why:
  `app/services/ledger.py:308-316`. The module docstring repeats the
  limitation at `app/services/ledger.py:12-20`.
- The register route is `/api/accounts/gst-register`
  (`app/api/accounts.py:241-247`).

**Too broad as worded.** Expenses do capture a GST amount and a creditable
flag: `gst_amount` and `gst_creditable` in `app/models/expenses.py:75-98`.
Those figures feed expense cost in the profit and loss, but they are not
reported in any input-GST register and do not reduce a net payable figure.
Recommended wording: "Purchase-order tax is not captured; expense GST is
captured but not reported as input tax or netted against output tax."

**Screen/route that closes it:** Purchases (`#/purchasing`) would need a tax
split per PO line (new columns and migration), using the rates managed on the
Tax screen (`#/tax`, `/api/tax/*`); the GST register
(`/api/accounts/gst-register`) would then add an input section and a net
payable line.

### GAP-A06: GSTR-1 / GSTR-3B reconciliation

**Claim:** no filed return is stored, so no reconciliation with a return can be
shown.

**Verified.**
- There is no return, filing or GSTR table in `app/models/`; a search for such
  classes returns nothing.
- The outward register is explicitly a reconciliation aid, not a filing file:
  `app/services/ledger.py:18-20` and `app/services/ledger.py:315`.
- The register follows GSTR-1 sections from issued documents but has no
  counterpart return to compare against: `app/services/ledger.py:269-271`.

**Screen/route that closes it:** Reports (`#/reports`) already exposes the GST
outward register. Closing the gap needs a filed-return record (new table and
migration for GSTR-1/GSTR-3B totals) and a comparison view against the
computed register.

### GAP-A07: TDS and other statutory dues

**Claim:** no TDS section, deduction or challan is recorded.

**Partly inaccurate.** Two different things are being conflated:
- **Employee payroll TDS is recorded.** `statutory_head` supports `tds` on a
  salary component (`app/models/hr.py:326`), the allowed heads are
  `pf`, `esi`, `pt`, `tds` (`app/api/hr.py:2797-2799`), and payroll aggregates
  statutory deductions by head (`app/api/hr.py:3217-3235`). The HR Payroll
  screen therefore already reports salary TDS.
- **Vendor TDS is not recorded.** No section, deduction-at-source entry or
  challan exists on supplier bills or payments; no such table or field was
  found in `app/models/`.

Recommended wording: "Salary TDS is recorded as a payroll statutory deduction.
Vendor TDS (section, deduction and challan) is not recorded."

**Screen/route that closes it:** HR (`#/hr`) already shows payroll statutory
deductions. Vendor TDS needs a section/deduction on the supplier payment or
bill (new columns/table and migration) and a challan register, surfaced from
Accounting & Finance (`#/accounts`) or Purchases (`#/purchasing`).

### GAP-A08: Vouchers, journal and day book

**Claim:** money movements are recorded as receipts and payments only; there is
no voucher or posting state.

**Verified.**
- `Payment` is the only money-movement record, append-only, with receipt and
  payment kinds: `app/models/accounts.py:1-13` and
  `app/models/accounts.py:27-60`.
- The ledger and trial balance are derived from documents, not posted:
  `app/services/ledger.py:1-11`.
- No voucher, journal, day-book or posting-state table exists in `app/models/`.

**Screen/route that closes it:** Accounting & Finance (`#/accounts`) records
receipts and payments (buttons at `static/js/app.js:478-479`). A voucher and
day book need a new schema (voucher header/lines, posting state, migration) and
a posting screen; deriving them from the current documents without that schema
would still not give a journal.

### GAP-A09: Bank reconciliation

**Claim:** no bank statement or reconciliation record exists.

**Verified.**
- Payments record `mode`, `reference` and notes only:
  `app/models/accounts.py:43-60`. The modes are cash, bank, upi, cheque, neft
  and other (`app/models/accounts.py:28-30`).
- No bank-statement, import or reconciliation table exists in `app/models/`.
- The trial balance derives Cash and Bank balances from payment modes
  (`app/services/ledger.py:383-395`), but does not compare them with a
  statement.

**Screen/route that closes it:** Accounting & Finance (`#/accounts`) records
the payments. Reconciliation needs a bank-statement import (new table and
migration), a matching UI and a reconciled/unreconciled state.

### GAP-A10: Opening balances and balance sheet

**Claim:** opening cash, bank and capital balances are not captured, so a
balance sheet and a closing cash balance cannot be produced.

**Verified, but incomplete as a reason.**
- The module states there is no opening balance and no chart of accounts:
  `app/services/accounting.py:3-4`.
- The report says opening balances are not captured:
  `app/services/accounting.py:218`.
- The trial balance says "opening balances and expense accounts are not
  captured": `app/services/accounting.py:324-331`.
- `UNAVAILABLE` marks the balance sheet with GAP-A10:
  `app/services/accounting.py:56-61`.

The balance sheet is blocked by more than opening balances. The derived trial
balance (`app/services/ledger.py:320-414`) contains Sales, Purchases,
Receivables, Payables, Cash/Bank, output taxes and round-off. It does **not**
post approved expenses, payroll, inventory, fixed assets or capital. A balance
sheet would need those postings and a chart of accounts as well as opening
balances.

**Screen/route that closes it:** Accounting & Finance (`#/accounts`) and its
`/api/accounts/report` payload. Closing it needs an opening-balance import or
entry screen, a chart of accounts, and postings for expenses, payroll, stock,
fixed assets and capital, plus a balance-sheet report and export.

## Findings outside the listed gaps

### 1. Model and migration disagree on the `cost_source` check

- Migration `0023_foc_samples.py` widens `ck_stock_movement_cost_source` to
  include `'foc'` (`alembic/versions/0023_foc_samples.py:52-53`).
- The model still lists only
  `'po_receipt','weighted_average','partial','return','uncosted'`
  (`app/models/core.py:109-112`).

The migrated database is correct and the tests use Alembic. A schema built with
`Base.metadata.create_all` would reject a free-of-cost movement. This is drift,
not a live-data defect, but it should be fixed so the model matches
migration 0023.

### 2. The panel intro promises links that do not exist

`static/index.html:648` says "Each gap links to the screen that fixes it."
The GAP-A03 to GAP-A10 objects contain only `code`, `label` and `detail`
(`app/services/accounting.py:210-211`), and `renderAccGaps` only emits a link
when `g.fix` is present (`static/js/app.js:2356-2363`). None is present, so no
gap in that panel links anywhere. The links that do exist are on the separate
performance tiles, which point to `#/accounts`, `#/expenses` and `#/hr`
(`static/js/app.js:2168-2189`).

Either add `fix`/`fix_label` to each gap or change the intro sentence.

### 3. Trial balance and profit and loss do not use the same expense data

The trial balance excludes approved expenses (`app/services/ledger.py:320-414`)
while the profit and loss includes them (`app/services/accounting.py:497-511`).
This is consistent with the trial-balance note, but it means the two statements
cannot be tied together today. It matters for GAP-A10: a balance sheet needs
expense postings, not only opening balances.

## Not verified

- No browser session was opened for this register.
- No database write or HTTP call was made; "not captured" conclusions are from
  schema and code review, not from attempting the operation.
- The checks above are against `feature/accounting-expenses` at `dc394a2`;
  `master` may differ.
