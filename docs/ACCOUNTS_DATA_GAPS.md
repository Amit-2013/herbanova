# Accounts data gaps: verified register

**First verified:** 2 November 2026, branch `feature/accounting-expenses` at `dc394a2`.
**Updated:** 3 November 2026 (Batch 5). GAP-A08, GAP-A09 and GAP-A10 are
implemented; their sections below record what is enforced, the screen and the
test and browser evidence. Batch 4 closed GAP-A05 to GAP-A07, and Batch 3 closed
GAP-A03 and GAP-A04.
**Method:** the original register was a read-only review of the models,
services, routes and screens. Each later closure is recorded with the tests and
a browser probe against a disposable test database; the closures of 3 November
2026 wrote rows only in that test database, never in the development or
production database.
**Source of the claims:** the "Data gaps" panel on the Accounting & Finance
screen and the text pasted for review.

Every A-series gap below is now closed, and `accounting.GAPS` is empty, so the
screen's Data gaps panel raises none of them. The P&L gaps (GAP-P01, GAP-P02,
GAP-P03) still come from `profit_loss.statement()` and `renderAccGaps`
(`static/js/app.js`) prints whatever the payload carries.

## Verdict summary

| Code | Claim | Verdict |
|---|---|---|
| GAP-A03 | Financial-year close | **Closed 3 Nov 2026.** A completed financial year can be closed; every dated document is refused with HTTP 423 until the Administrator reopens it with a reason. Accounting-month locks remain the narrower gate. |
| GAP-A04 | Invoice due dates | **Closed 3 Nov 2026.** The invoice freezes the distributor's payment terms and due date at issue; ageing reports overdue, due within 7 days, later and no-due-date from that snapshot. |
| GAP-A05 | Input GST and net GST payable | **Closed 3 Nov 2026.** A supplier bill records the tax charged head by head; the input register, eligible and blocked totals and the net payable are reported. With no posted bill the figure stays "No data yet" rather than zero. |
| GAP-A06 | GSTR-1 / GSTR-3B reconciliation | **Closed 3 Nov 2026.** The figures reported as filed are captured per month and form, and each line is compared with the computed register; a difference is shown, not resolved. |
| GAP-A07 | TDS and other statutory dues | **Closed 3 Nov 2026.** Vendor TDS is captured on the supplier bill, payroll statutory heads come only from approved or later payroll, and challans record what was deposited; the outstanding line is what no challan covers. |
| GAP-A08 | Vouchers, journal and day book | **Closed 3 Nov 2026.** A voucher carries its own lines, a draft, posted and reversed state, and a day book; posted vouchers merge with the documents on the balance sheet. |
| GAP-A09 | Bank reconciliation | **Closed 3 Nov 2026.** A statement is captured per bank head and period, its lines are matched to receipts, payments or voucher lines, and a proof shows book against statement with the difference stated, not plugged. |
| GAP-A10 | Opening balances and balance sheet | **Closed 3 Nov 2026.** Opening balances are captured per head and year, a seeded chart of accounts exists, and a balance sheet merges openings, posted vouchers and the document trial balance. Expense, payroll, stock and fixed-asset postings remain outside the document layer and are named as limits, not guessed. |
| Panel intro | "Each gap links to the screen that fixes it" | **Fixed 3 Nov 2026.** The intro now says each gap names the missing input; no panel promises a link it does not render. |

## Per-gap evidence

### GAP-A03: Financial-year close — closed 3 November 2026

**Was:** accounting months could be locked; invoice changes, credit notes,
receipts, payments and a year-end close were not covered.

**Now enforced.**
- New table `financial_year_closes` in `app/models/accounts.py`; migration
  `alembic/versions/0025_due_dates_and_year_close.py`. One row per full label
  (`2024-25`), unique, with `active`, reason, closing and reopening audit
  fields, and a check constraint on the label shape.
- `app/services/periods.py` owns the calendar and the gate: `fy_start`,
  `fy_end`, `fy_label`, `label_bounds`, `refuse_if_closed`, `close_year`,
  `reopen_year`, `year_rows`. `refuse_if_closed` checks the active
  accounting-month lock first, then a closed financial year, and raises
  `PeriodClosed`.
- Only a completed year can be closed, and not one before the first document
  in the book. A reason of at least five characters is required, and closing an
  already-closed year is refused.
- Routes under `/api/accounts/financial-years`: GET (`accounts:read`), POST
  `/{label}/close` (`accounts:write`, audit `accounts.financial_year.close`),
  POST `/{label}/reopen` (`require_admin`, audit
  `accounts.financial_year.reopen`).
- Refused with HTTP 423:
  - dispatch and the invoice it creates — `app/api/sales_orders.py`;
  - receipts and payments — `app/api/accounts.py`;
  - credit notes and debit notes — `app/api/credit_notes.py`,
    `app/api/debit_notes.py`;
  - invoice cancellation — `app/api/invoices.py`;
  - expense create and reversal — `app/api/expenses.py`;
  - purchase-cost correction, backfill and PO cost correction —
    `app/services/costing.py`;
  - free-sample notes — `app/services/foc.py`.
- Screen: Accounting & Finance shows a "Financial years" panel and an
  "Accounting month locks" panel. The Administrator closes or reopens a year
  and locks or unlocks a month, each with a typed reason.
- Evidence: `tests/test_periods.py` (9 tests). A closed 2024-25 year refuses a
  backdated receipt (423); the sales role cannot close (403) or reopen; the
  Administrator reopens with a reason and the receipt then posts (201). Month
  locks block receipts, credit notes and dispatch, and unlocking restores them.
- Not covered: there is no posting engine, so a close freezes dated documents
  rather than writing closing entries. Stock valuation and closing journals
  remain with GAP-A08 and GAP-A10.

### GAP-A04: Invoice due dates — closed 3 November 2026

**Was:** an invoice carried no due date; payables due dates were estimated from
the supplier's current payment terms and the latest receipt.

**Now enforced.**
- `Invoice` stores `payment_terms_days` and `due_date` (`app/models/core.py`),
  with constraint `ck_invoice_payment_terms` and index `ix_invoices_due_date`;
  migration `0025_due_dates_and_year_close`.
- `app/services/invoice.py` copies the distributor's terms at issue and
  computes `due_date = invoice_date + terms`. A distributor with no terms
  stores NULL rather than a guessed date.
- `/api/invoices` returns both fields. The invoice drawer shows the terms and
  says "Not captured when this invoice was issued" when the snapshot is NULL.
- Ageing (`app/services/ledger.py`) returns `due_date` and `days_overdue` per
  row and a `due` split: `overdue`, `due_this_week` (7 days), `not_yet_due`
  and `no_due_date`. Buckets by invoice date stay for comparability, and the
  screen prints the due split under the table.
- Evidence: `tests/test_periods.py`. Terms of 30 freeze on issue and survive a
  master PATCH to 90; no terms gives both fields NULL; the due split totals and
  counts equal the outstanding totals.
- Still estimated: supplier payables use today's `Supplier.payment_terms_days`
  and the latest receipt. The report note says so.

### GAP-A05: Input GST and net GST payable — closed 3 November 2026

**Was:** purchases carried only a cost; output GST was reported alone and no
input register or net payable existed. Expense GST was captured but never
netted.

**Now enforced.**
- New table `purchase_invoices` in `app/models/accounts.py`; migration
  `alembic/versions/0026_gst_and_statutory.py`. It stores the supplier invoice
  number, the linked purchase order, `taxable_value`, `cgst_amount`,
  `sgst_amount`, `igst_amount`, `cess_amount`, `round_off`, `tax_total`,
  `total`, an `itc_eligible` flag, the TDS columns, `status`
  (`posted`/`reversed`) and reversal audit fields. The bill number is unique
  per supplier only.
- `app/services/gst.py` owns three readings: `register` (the input register:
  per-bill rows, totals, eligible and blocked), `net` (output minus eligible
  input, head by head, with blocked input shown separately and never netted)
  and `expense_itc` (creditable expense GST as a memo, one amount, no head
  split).
- Honest limits are in the payload: with no posted bill, `available` is false
  and the reason says so instead of reporting zero ITC. Payables are untouched,
  because a bill records tax, not a change in what is owed.
- Routes under `/api/accounts`: GET/POST `purchase-invoices`, POST
  `purchase-invoices/{id}/reverse`, GET `input-gst`, GET `gst-net`. Money
  leaves as two-decimal strings. Duplicate bill numbers return 409; a reversal
  reason shorter than five characters returns 422; reversing twice returns 409.
  Draft, month-locked and year-closed dates return 423.
- Screen: Accounting & Finance has an "Input GST — supplier bills" panel with
  the tax columns, each bill's ITC flag, a New bill drawer and a reverse
  action; the net line and the expense-ITC memo print under the table. The
  Output GST card note now points to the input register instead of claiming
  the tax is not captured, and the email and report pack carry a "Net GST
  payable" figure that reads "No data yet" until a bill is posted.
- Evidence: `tests/test_gst_statutory.py`. Captured tax totals 180.00 on a
  1,000.00 bill; a reversed bill stays visible and is excluded from the totals;
  net payable subtracts eligible input only (blocked input 20.00 stays
  separate); the expense ITC memo is flagged `included_in_net: false`.
- Browser probe (3 Nov 2026, test database on a temp server): captured
  PUR-000001 (₹1,180, net −180.00 credit), reversed it (register empty, net
  back to "No data yet"), then captured PUR-000002 with vendor TDS 194C ₹20.
- Not covered: eligibility is whatever the person capturing the bill recorded;
  the application does not judge whether a credit is blocked. Expense GST has
  no head split, so it is a memo, not a CGST/SGST/IGST column.

### GAP-A06: GSTR-1 / GSTR-3B reconciliation — closed 3 November 2026

**Was:** no filed return was stored, so the computed register could not be
compared with what was reported.

**Now enforced.**
- New table `gst_returns` in `app/models/accounts.py`; migration
  `0026_gst_and_statutory`. One row per year and month and form
  (`GSTR-1`, `GSTR-3B`), unique on the three, holding the outward taxable
  value, the four outward heads, the four ITC heads, the filed date, the
  reference and a note.
- `app/services/gst.py:reconciliation` compares each filed line with the
  register for the month: outward heads and taxable value for both forms, ITC
  heads and tax payable after ITC for GSTR-3B. A difference under half a paisa
  matches; anything else is listed as a difference with both figures.
- ITC is only compared once a purchase bill exists; before that the lines say
  why they cannot be compared rather than treating missing input as zero.
- Routes: GET/POST `/api/accounts/gst-returns` (`accounts:read` /
  `accounts:write`, audit `accounts.gst_return.record`) and GET
  `/api/accounts/gst-reconciliation?year=&month=`. An ITC figure saved against
  GSTR-1, an unknown form and a month later than today all return 422.
- Screen: "GST returns and reconciliation" panel with year and month, a
  Form/Check/Filed/Computed/Difference/Result table and a New return drawer.
- Evidence: `tests/test_gst_statutory.py`. A saved GSTR-3B matches the
  computed register; an amendment of 5.00 in filed CGST shows a difference of
  the same amount; saving again replaces the month's row rather than adding a
  second.
- Browser probe (3 Nov 2026): filed GSTR-3B Nov 2026 with zeros and ITC
  90/90. The head, ITC and tax-payable checks read "Matches"; outward taxable
  showed a difference of the computed 14,821.00 from other test invoices,
  which is the comparison working as intended.
- Not covered: the application does not file and does not read the portal.
  Filed figures are what the practitioner reported, typed in by hand.

### GAP-A07: TDS and other statutory dues — closed 3 November 2026

**Was:** salary TDS existed as a payroll deduction, but vendor TDS (section,
deduction and challan) and a deposition register were missing.

**Now enforced.**
- Vendor TDS is captured on the supplier bill: `tds_section`, `tds_rate` and
  `tds_amount` on `purchase_invoices` (migration `0026_gst_and_statutory`).
  Only posted bills count; a reversed bill is kept but excluded.
- New table `statutory_challans` for what was actually deposited, with kind
  (`pf`, `esi`, `pt`, `tds`), BSR code, challan number, paid-on date, amount
  and the period it relates to.
- `app/services/statutory.py` reads two sources and never guesses: vendor TDS
  from posted bills and payroll statutory deductions only from periods that
  reached `approved`, `processed` or `paid`. A draft payroll is not a
  liability. `dues` reports withheld-to-date, deposited-to-date, deposited in
  the window and the outstanding remainder per head; a head with no source
  reads `available: false` with a reason, not zero.
- Routes under `/api/accounts`: GET `statutory-dues?from=&to=`, GET/POST
  `statutory-challans` (`accounts:read` / `accounts:write`, audit
  `accounts.challan.record`). An unknown kind and a future period return 422.
- Screen: "TDS and statutory dues" panel with the four heads, a challan table
  and a New challan drawer, showing the vendor-TDS and payroll detail lines
  under the tables.
- Evidence: `tests/test_gst_statutory.py`. Approved payroll PF 500 plus vendor
  TDS 20 with a 300 challan gives PF outstanding 200 and TDS outstanding 20; a
  draft payroll contributes nothing.
- Browser probe (3 Nov 2026): with a bill carrying TDS 194C ₹20, the dues
  panel showed ₹20 withheld and outstanding, detail "Vendor TDS 20.00 across 1
  bill"; challan UI-CH-001 ₹20 took the outstanding to ₹0.
- Not covered: the application does not decide whether a deduction was
  required. Challans are typed in; there is no portal import.

### GAP-A08: Vouchers, journal and day book — closed 3 November 2026

**Was:** money movements were recorded as receipts and payments only; there was
no voucher, no posting state and no day book.

**Now enforced.**
- Migration `alembic/versions/0027_ledger_and_bank_rec.py` adds `vouchers` and
  `voucher_lines` (additive only, with a `downgrade`). A voucher stores its
  date, type (`journal`, `receipt`, `payment`, `contra`), narration, status
  (`draft`, `posted`, `reversed`), the posting audit fields and, for a reversal,
  `reversal_of_id` and a reason. Check constraints keep a line one-sided and
  non-negative and require a reason once reversed and a timestamp once posted.
- `app/services/journal.py` is the writing side of the ledger: `create_voucher`,
  `update_voucher`, `delete_voucher`, `post_voucher`, `reverse_voucher`,
  `voucher_rows`, `voucher_detail`, `day_book` and `posted_movements`. A draft
  may be saved unbalanced; posting refuses it until debit equals credit. A
  posted voucher cannot be edited or deleted, only reversed. The reversal is a
  mirror voucher dated today (so a locked original month does not block it),
  posted immediately, and the original is marked reversed with its reason.
- `app/services/balance_sheet.py:balance_sheet` merges posted and reversed
  vouchers (a pair nets to zero) with opening balances and the document trial
  balance by ledger head.
- Routes under `/api/accounts` in `app/api/ledger.py`: GET/POST `/vouchers`,
  GET/PUT/DELETE `/vouchers/{id}`, POST `/vouchers/{id}/post`,
  POST `/vouchers/{id}/reverse`, GET `/day-book` (`accounts:read` to read,
  `accounts:write` to write; audit on create, post, reverse). A locked accounting
  month or a closed financial year returns 423; unbalanced posting, editing a
  posted voucher, reversing twice and a missing voucher return 409; a future
  date, fewer than two lines and a reason under five characters are refused.
- Screen: Accounting & Finance has a "Journals and vouchers" panel (date range,
  status filter, New voucher drawer with add/remove lines), a post, delete and
  reverse action per row, and a "Day book" panel showing posted and reversed
  vouchers for a period with debit and credit totals and a balanced indicator.
- Evidence: `tests/test_ledger_and_bank_rec.py` (14 tests). A draft of 10 debit
  against 5 credit is saved, refused at posting, edited to balance, posted,
  then refused an edit; the cash balance falls by 50 and returns after the
  reversal; both vouchers appear in the day book and it balances. A locked month
  refuses a posted voucher with 423, a future date is refused, and the API
  lifecycle is proven end to end (201 draft, 409 post, 200 post, 409 edit,
  201 reversal). The sales role reads vouchers but cannot post one (403); the
  viewer role cannot read the ledger at all (403).
- Browser probe (3 Nov 2026, test database on a temp server): posted a journal
  of Bank 250 against Capital 250 (toast "Voucher posted"), saw it in the day
  book (balanced) and a bank balance of 250 on the balance sheet; an unbalanced
  draft was refused at posting with the server message "The voucher does not
  balance: debit 50.00, credit 40.00"; the draft was then deleted.
- Not covered: a document is **not** posted as a voucher automatically, so the
  voucher trail and the document trail are separate readings. The day book
  covers vouchers only; receipts, payments and invoices stay in their own
  panels.

### GAP-A09: Bank reconciliation — closed 3 November 2026

**Was:** payments recorded a mode and reference, but no bank statement was
stored and nothing was compared with the books.

**Now enforced.**
- Migration `0027_ledger_and_bank_rec` adds `bank_statements` (bank head,
  period, opening and closing balance, note; unique per head and period) and
  `bank_statement_lines` (date, description, reference, signed amount, and one
  optional match to a payment or a voucher line). Constraints keep the period
  ordered, the amount non-zero, at most one match per line and each payment or
  voucher line matched at most once.
- `app/services/bank_rec.py` owns the reading and writing: `create_statement`
  refuses an overlapping period for the same head, `add_lines` refuses a date
  outside the period and a zero amount, `match_line` refuses a type or an amount
  that disagrees with the line, `unmatch_line` clears a match, and
  `reconciliation` returns the book opening and closing (from the balance-sheet
  layer), matched count and totals, unmatched book items, unmatched statement
  lines and a proof: adjusted book, adjusted statement, the opening difference
  and the remaining difference, with `balanced` only when it is zero. A warning
  explains each difference rather than hiding it. A statement cannot be deleted
  while a line is matched, and a matched line cannot be deleted.
- Routes under `/api/accounts` in `app/api/ledger.py`: GET/POST
  `/bank-statements`, GET/PATCH/DELETE `/bank-statements/{id}`, POST
  `/bank-statements/{id}/lines`, DELETE `/bank-lines/{id}`, POST
  `/bank-lines/{id}/match|unmatch`, GET `/bank-statements/{id}/candidates|reconciliation`
  (`accounts:read` / `accounts:write`; audit on create and match).
- Screen: Accounting & Finance has a "Bank reconciliation" panel listing
  statements; opening one shows the proof, the statement lines with Match,
  Unmatch and Delete, the book items still unmatched, and the match drawer.
  The drawer lists exact-amount candidates first and labels an amount mismatch
  as such instead of offering it silently.
- Evidence: `tests/test_ledger_and_bank_rec.py`. A 10,000 receipt and a 4,000
  payment are matched to a statement with a further 250 bank charge: matched
  count 2, one unmatched statement line, difference 0.00 and `balanced` true;
  matching a 4,000 line to a 10,000 receipt is refused; deleting a matched
  statement and a matched line are both refused. The overlapping period, a line
  outside the period and a zero line are refused.
- Browser probe (3 Nov 2026): created a statement for 1–3 Nov 2026 on the bank
  head, added a +250 line, matched it to the posted voucher line, and the proof
  read "1 of 1", Difference 0.00, Balanced.
- Not covered: there is no bank-file (CSV/OFX) import; lines are typed in. With
  more than one bank head, document money is not split between heads, so only
  the voucher lines that name a head can be matched; the statement reports that
  limit as a warning.

### GAP-A10: Opening balances and balance sheet — closed 3 November 2026

**Was:** opening cash, bank and capital balances were not captured, so a
balance sheet and a closing cash balance could not be produced. The stated
reason was also incomplete: there was no chart of accounts.

**Now enforced.**
- Migration `0027_ledger_and_bank_rec` adds `ledger_accounts`, seeded with nine
  heads that match the document buckets (Cash, Bank, Receivables, Payables,
  Output GST, Sales, Purchases, Round off) plus Capital, and
  `opening_balances` (head, financial year, debit or credit, note; unique per
  head and year). No amount is seeded.
- `app/services/journal.py` adds and edits heads (`create_account`,
  `update_account`; a code and a name are unique, a seeded role cannot be
  duplicated) and saves one head's opening (`save_opening`). Zero on both sides
  clears the row. An opening balance is refused only for a closed financial
  year (423), because it is a statement about the year rather than a document
  inside a month.
- `app/services/balance_sheet.py` produces the sheet at a date from three
  layers kept apart and labelled in the response: the opening trial balance,
  posted (and reversed) vouchers, and the document trial balance mapped to heads
  by `role`. The opening year is the latest captured year at or before the date,
  and movements are summed from that year's first day so a carried-forward
  opening is never added to the same year's documents twice. Totals give each
  section, retained earnings, the difference and `balanced`. A "cash and bank"
  summary gives each head's balance and the total. The warnings state what is
  partial: no opening captured, an earlier year's opening carried forward, an
  opening trial balance that does not balance, document buckets with no matching
  head, and the fact that the document layer covers sales, receipts, payments
  and goods received only. An opening that does not balance is reported as a
  difference, never plugged.
- Routes under `/api/accounts` in `app/api/ledger.py`: GET/POST/PATCH
  `/ledger-accounts`, GET `/ledger-accounts/{id}/balance`,
  GET/PUT `/opening-balances?financial_year=`, GET `/balance-sheet?as_of=`
  (`accounts:read` / `accounts:write`).
- Screen: "Ledger heads" (add, rename, activate/deactivate), "Opening balances"
  (per year, debit or credit per head, totals and difference),
  "Balance sheet" (as-of date, sections, retained earnings, difference, cash and
  bank, warnings), and each head's balance is available from the API. The
  Profit and loss panel is unchanged and remains the reading for earnings.
- Evidence: `tests/test_ledger_and_bank_rec.py`. Opening Cash 1,000 against
  Capital 900 reports a difference of 100 and `balanced` false; saving Capital
  1,000 balances it, and zeroing the row clears it. A closed 2017-18 year
  refuses an opening (423). A 2018-19 opening moves the balance sheet's cash by
  1,000 and its equity by 1,000 without changing the document-layer difference,
  and a 2025-26 sheet names the 2018-19 opening and its window start. The nine
  seeded roles are present, and an extra head can be created and deactivated.
- Browser probe (3 Nov 2026): entered Cash 1,000 and Capital 1,000 (difference
  went from 1,000.00 to balanced), the balance sheet showed both; created head
  5200 "Freight inward" and deactivated it.
- Not covered: the document layer does not post approved expenses, payroll,
  stock cost or fixed assets, so earnings and the difference are partial; the
  warnings say so. Opening balances themselves are typed in per head; there is
  no file import and no automatic carry-forward write.

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

### 2. The panel intro promised links that do not exist — fixed 3 November 2026

The intro at `static/index.html` now says "Each gap names the missing input, so
no figure is guessed." The gap objects still carry only `code`, `label` and
`detail`; `renderAccGaps` keeps its optional `fix` support for future use.

### 3. Trial balance and profit and loss do not use the same expense data

The trial balance excludes approved expenses (`app/services/ledger.py:320-414`)
while the profit and loss includes them (`app/services/accounting.py:497-511`).
This is consistent with the trial-balance note, but it means the two statements
cannot be tied together today. It is also why the balance sheet (GAP-A10, now
closed) carries a warning that its document layer has no expense, payroll or
stock-cost postings: a voucher can post any of them by hand, but they are not in
the document layer.

## Not verified

- No browser session was opened for this register.
- No database write or HTTP call was made for the original register; "not
  captured" conclusions are from schema and code review, not from attempting
  the operation.
- A03 and A04 were re-verified on 3 November 2026 against the implementation
  and `tests/test_periods.py`. The browser walk-through of the new Financial
  years and month-lock panels is **not verified**.
- A05, A06 and A07 were verified on 3 November 2026 by
  `tests/test_gst_statutory.py` (9 tests) and by a browser probe against a
  test database on a temp server: bill capture and reversal, net GST, a filed
  GSTR-3B compared with the register, and a challan clearing the statutory
  outstanding. The probe used the real login endpoint; no console errors or
  warnings were logged. Migration `0026_gst_and_statutory` was applied to the
  development database on 3 November 2026 after a fresh backup
  (`var/backups/pre-migrations-0024-0026-20261103T082237.dump`); the dev
  database is now at head `0026_gst_and_statutory` with 77 tables.
- A08, A09 and A10 were verified on 3 November 2026 by
  `tests/test_ledger_and_bank_rec.py` (14 tests) and by a browser probe against
  a test database on a temp server: opening balances balanced, a 250 journal
  posted and seen in the day book, an unbalanced draft refused at posting,
  a bank statement line matched with a zero difference, a new head created and
  deactivated. The only console entries were the expected pre-login 401 and the
  deliberate 409 from the refused posting.
- The whole project suite was run on 3 November 2026 after these changes:
  **419 passed, 0 failed** at that point; the suite is at **446 passed** after the
  later gap-closure work (3 November 2026). The six new tables are also classified for the
  database reset: `ledger_accounts` is kept, while `opening_balances`,
  `vouchers`, `voucher_lines`, `bank_statements` and `bank_statement_lines` are
  cleared by a business reset — `tests/test_db_reset.py` passes against a schema
  at head `0027` (83 tables).
- Migration `0027_ledger_and_bank_rec` was applied to the development database on
  3 November 2026 with approval (`apply 8411462b33df`), after a fresh backup:
  `var/backups/pre-migration-0027-20261103T093759.dump` (355,623 bytes; 77
  tables with data checked with `pg_restore -l`). `alembic current` now reads
  `0027_ledger_and_bank_rec`; the dev database has **83 tables** and the nine
  seeded heads, with every new table at 0 rows. `alembic check` reports no new
  upgrade operations. Three uvicorn instances were found bound to `:8000` (the
  §19 defect again); they were stopped and one server was started from this
  checkout, where the six new endpoints answer `401` without a session and the
  balance-sheet and day-book services read the dev data (sheet difference
  `0.00`, no opening captured, warnings naming the partial document layer).
  The signed-in walk-through on the dev database was **not** repeated: the probe
  browser holds its token in memory for the stopped `:8001` server and the reload
  showed the sign-in screen, so the UI evidence for these panels remains the
  test-database probe above.
- The original checks were against `feature/accounting-expenses` at `dc394a2`;
  `master` may differ.
