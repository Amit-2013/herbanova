# Chapter 24 — Accounts dashboard, ledger, reconciliation and period close

**Audience:** Accounts and the Administrator.
**Screen:** `#/accounts` (Accounting & Finance).
**Permissions:** `accounts:read` to see the statements; `accounts:write` to
record receipts and payments, keep the chart of accounts, capture opening
balances, post vouchers, capture bank statements and match them, lock a month
or close a year; only the **Administrator** may unlock a month or reopen a year.
The figures described here use `accounts:reports` where the server gates them.

**Verification:** the API behaviour below is covered by
`tests/test_periods.py`, `tests/test_accounts_reports.py`,
`tests/test_email_reports.py` and `tests/test_ledger_and_bank_rec.py`. The
panels described in sections 7–12 were walked in a browser on 3 November 2026
against the disposable test database: opening balances were balanced, a
journal was posted and appeared in the day book, an unbalanced draft was
refused at posting, a bank line was matched with a zero difference, and a head
was created and deactivated. The section bar, its direct addresses and the
permission split described below were walked the same day, then again after
**Receivables by distributor** joined the bar, when an Administrator saw all
nineteen sections and landed on Performance, an `accounts:read`-only user saw
the eighteen statement sections and landed on Receivables, a direct load of
`#/accounts/bank` opened Bank reconciliation, and GST outward and trial balance
loaded their tables when opened.

The two-mode receipt and payment and the single From–To receivables filter were
walked again on 3 November 2026 on the disposable test database: an advance
receipt and an advance supplier payment showed the held amount in the toast and
the entry row; an outstanding receipt of ₹ 500.00 settled a ₹ 472.00 invoice and
held ₹ 28.00 as an advance; changing a receivables date made no request, Apply
made exactly one request for the chosen range, a From-after-To was refused
without a request, and Export CSV produced the matching file. Service-side
behaviour is covered by `tests/test_accounts_advances.py`.

Also on 3 November 2026, every tile on the Performance panel was followed in
the browser: each opened its own panel or report, the window was carried to GST
outward and Receipts and payments, Ageing opened at the window's last day and
Payables was narrowed by `due=week` (§1). The tile destinations have no
automated test of their own; the reports behind them do.

## Moving around the screen

A section bar sits under the page title with one entry for every panel. The
chosen entry is highlighted with `aria-current="page"` and only that panel is
shown; the others are already loaded, so switching costs no waiting.

Each entry has its own address, so a section can be bookmarked, refreshed or
linked from elsewhere in the application:

| Section | Address |
|---|---|
| Performance and P&L | `#/accounts/reports` |
| Receivables | `#/accounts/receivables` |
| Receivables by distributor | `#/accounts/receivables-by-distributor` |
| Ageing | `#/accounts/ageing` |
| Payables | `#/accounts/payables` |
| Receipts and payments | `#/accounts/cash` |
| GST outward | `#/accounts/gst-out` |
| Input GST | `#/accounts/gst-in` |
| GST returns | `#/accounts/gst-returns` |
| TDS and statutory | `#/accounts/statutory` |
| Trial balance | `#/accounts/trial-balance` |
| Ledger heads | `#/accounts/ledger-heads` |
| Opening balances | `#/accounts/openings` |
| Balance sheet | `#/accounts/balance-sheet` |
| Vouchers | `#/accounts/vouchers` |
| Day book | `#/accounts/day-book` |
| Bank reconciliation | `#/accounts/bank` |
| Financial years | `#/accounts/years` |
| Month locks | `#/accounts/locks` |

The bar lists only what the signed-in role may open:

- **`accounts:reports` and `accounts:read`** — all nineteen sections.
- **`accounts:reports` only** — Performance and P&L alone; it opens there.
- **`accounts:read` only** — the eighteen statement sections, opening on
  Receivables. An address for Performance falls back to Receivables rather
  than showing an empty panel.

Opening plain `#/accounts` — the sidebar entry and the Overview Accounts card —
shows Performance and P&L to an `accounts:reports` holder and Receivables
otherwise. An unknown address falls back the same way. The server still checks
the permission on every request; a hidden entry is convenience, not the gate.

## 1. The window and the tiles

The dashboard reads documents, not stored production figures. A window is
inclusive of both dates; the heading states the exact range. Each tile states
its own measurement:

- **Amounts** are taxable value unless the tile says "with GST".
- A snapshot figure (outstanding, payables) is **as at the window's last day**.
- A flow figure (revenue, receipts, returns, output GST) covers the window
  exactly.
- A comparison against zero has no percentage; the tile says so instead of
  printing "0%" or an infinite change.
- Any input the system does not capture is **"No data yet"** with a gap code —
  never a zero and never an estimate.

The region filter narrows revenue, returns, output GST and distributor
receipts. Supplier balances, the trial balance and net cash movement stay
company-wide, and the page says so when a region is selected.

**Every tile is a link.** Selecting a tile opens the panel or report that
proves it, not a shared page, and carries the current window where that report
has one. The detail and the tile are therefore read over the same dates.

| Tile | Opens | What travels with the link |
|---|---|---|
| Revenue | GST outward | The window's From and To dates |
| Collections | Receipts and payments | The window's From and To dates |
| Receivables | Receivables | Nothing: the list is as at today, so the link does not pretend to travel in time |
| Over 60 days | Ageing | **As at** set to the window's last day |
| Payables | Payables | Nothing: an as-at-today list, as for receivables |
| Payable within 7 days | Payables, narrowed to the seven-day estimate behind the tile | The seven-day filter |
| Output GST | GST outward | The window's From and To dates |
| Cash and bank (net) | Receipts and payments | The window's From and To dates |
| Expenses | Expenses (outside Accounts) | The window's From and To dates |
| Net profit | Performance and P&L, scrolled to and briefly highlighted on the profit statement | Nothing: the statement is already on this panel |

A tile that shows **No data yet** still opens its panel, so the gap and its fix
can be read there. The link only sets the visible filters; the server still
checks the permission on every request. A card whose screen your role may not
open (for example **Expenses** without `expense:read`) lands on the Overview
page, and inside Accounts a section your role may not read falls back to the
default section; the link never grants access.

**VERIFIED:** the destinations and the carried window were walked in a browser
on the disposable test database on 3 November 2026 — ten tiles, ten distinct
destinations, the GST outward and Receipts and payments filters showing the
window, Ageing opening at the window's last day and Payables narrowed by
`due=week`; no console error. The hrefs are built by the server in
`app/services/accounting.py` and applied by `applyAccountsQuery` in
`static/js/app.js`; the walk found and fixed a defect where `due=week` was read
before the payables list had been drawn. There is no automated test asserting
the hrefs themselves; the underlying reports and their filters are covered by
`tests/test_accounts_reports.py`. Evidence: [`../VERIFICATION_REPORT.md`](../VERIFICATION_REPORT.md)
§25.1.

## 2. Profit and loss

The statement shows revenue and returns at taxable value, cost of goods from
the stock ledger, approved expenses by head and payroll gross by month. Gross
profit is labelled partial when some invoices carry no captured cost.

- A payroll month the window cuts short contributes its approved gross
  allocated by each employee's working-day share and is marked **allocated**.
- **Total expenses** and **Payroll (gross)** show a provable partial total
  marked **Partial** with a fix link when part of the window predates the
  captured data.
- **Net profit** stays **No data yet** until every input for the window is
  complete, because a residual built from a partial component would be wrong
  rather than partial.

## 3. Ageing and due dates

The panel **Ageing of outstanding invoices** keeps the four buckets by
**invoice date** — 0-30, 31-60, 61-90 and 90+ — so figures stay comparable
with earlier reports. Since the due-date change it also shows, per invoice:

| Column | Meaning |
|---|---|
| Due date | The date frozen on the invoice at issue; **no due date** when the distributor had no payment terms then |
| Overdue (days) | Days past the due date at the "as at" date; **–** when not yet due |

Under the table one line splits the same outstanding total four ways:
**overdue**, **due within 7 days**, **later** and **with no due date**. The
four amounts add up to the outstanding total, and the four counts add up to the
invoice count; the server proves both in `tests/test_periods.py`.

**How a due date is set.** When an invoice is issued, the distributor's
payment terms in days are copied onto the invoice and the due date is the
invoice date plus those days. Changing the distributor afterwards cannot move
an invoice the buyer already holds. If no terms were captured, both fields stay
empty and the invoice is reported under "no due date" rather than being given
an assumed term.

**Where you see it.** Open an invoice from Billing; the drawer shows
**Payment terms** as "30 days · due 5 Dec 2026", or "Not captured when this
invoice was issued, so it has no due date".

Supplier payables are different: no supplier bill with terms is captured, so a
payable's due date is still an estimate from the supplier's current terms and
the latest receipt. The report note says so.

## 4. Receivables by distributor

The **Receivables by distributor** panel restates what each distributor owed
across a chosen window and proves it with an identity: **opening plus the
window's movements equals closing** for every party. It replaced the old
single-line drill-down on the Performance panel and now has its own section
address, `#/accounts/receivables-by-distributor`.

**Choosing the window.** The panel has one **From date** and one **To date**.
Changing either box does not reload anything: the report changes only when
**Apply** is pressed, so the figures on screen always belong to the range
printed in the heading.

A future end date, an empty box, and a From later than To are refused with a
message and the last good figures are kept. The controls are capped at today.
The heading states the range that was read, for example "01 May 2019 to
31 May 2019 · opening, movements and closing at 31 May 2019".

**What each column means.**

| Column | Formula |
|---|---|
| Opening (₹) | What the party already owed on the day **before** the window: invoices issued earlier, plus debit notes, minus credit notes and receipts allocated to those invoices, up to that day |
| Invoiced (₹) | Taxable value of invoices issued inside the window |
| Credit notes (₹) | Credit notes dated inside the window that are allocated to an invoice |
| Debit notes (₹) | Debit notes dated inside the window that are allocated to an invoice |
| Received (₹) | Receipts whose allocated invoice falls in the party's book and whose paid-on date is inside the window |
| Closing (₹) | What the party owed on the window's last day: opening + invoiced + debit notes − credit notes − received |
| Overdue (₹) | The part of closing whose **due date fell before** the closing date; an invoice with no captured due date is never overdue |
| Open invoices | Invoices with a closing balance above zero |

Rows with nothing to report in the window are omitted; the **Total** row adds
each amount column and the counts. The note under the table states the same
rules, so a printed copy explains itself.

**A party, not a region.** The panel is company-wide; the region filter on the
Performance panel does not narrow it. Open a row's **Open ledger** button to
read the append-only party ledger behind the figure.

**Export CSV.** The button downloads
`HERBANOVA_Receivables_by_distributor_<from>_<to>.csv` for exactly the window
on screen, with the window in the first row, one row per distributor, a
**Total** row and the note. It uses the loaded figures, so press Apply for a
new window before exporting; if nothing is loaded the screen says so instead
of writing a file.

## 5. Financial years

The panel **Financial years** lists the Indian financial years (1 April to
31 March, labelled `2025-26`) with their first and last day, state, who closed
them and why.

- Only a **completed** year can be closed: its last day must have passed, and
  it cannot start before the first document in the book.
- A close needs a **reason** of at least five characters.
- While a year is closed, a document dated inside it is **refused** with
  HTTP 423: dispatch and its invoice, receipts and payments, credit and debit
  notes, invoice cancellation, expenses, cost corrections and free-sample
  notes. Nothing is deleted; every report still reads the year.
- Only the **Administrator** can reopen a year, with a reason. Close and
  reopen are both written to the audit trail.
- The current year's row says **Open**; a reopened year shows the reopening
  date and reason.

Closing a year does not write closing entries. It freezes the dated documents so
a finished year cannot be silently restated. Closing journals can now be typed
as vouchers (section 10) and the balance sheet is produced (section 9); the
system still does not create those entries on its own.

## 6. Accounting month locks

The panel **Accounting month locks** is the narrower, day-to-day gate. Pick a
month and give a reason; the month is locked until an Administrator unlocks it
with a reason. A locked month refuses expenses, receipts, payments, credit and
debit notes, dispatches and cost corrections **dated in that month**. It
refuses by date, so work in another month continues.

Use a month lock while a month is being reconciled, and a year close when the
year's books are final. Every refusal message names the locked month or the
closed year, so the person knows exactly what to fix.

## 7. Ledger heads

The **Ledger heads** panel is the chart of accounts. Nine heads arrive with the
migration, one for each bucket the documents already produce — Cash, Bank,
Receivables, Payables, Output GST, Sales, Purchases and Round off — plus
Capital so an opening position can be recorded. No amount is seeded.

- A **seeded** head carries a **role**. That role is what links it to the
  document trial balance; the role column shows it and it cannot be changed
  from this screen.
- **New head** (needs `accounts:write`) takes a code, a unique name and a type
  (asset, liability, equity, income or expense). A code or name already in use
  is refused.
- A head can be renamed or **deactivated**. A deactivated head stays in the
  history and on past statements but cannot be used on a new voucher line.
- Deleting a head is not offered: a ledger with history is not rewritten.

## 8. Opening balances

The **Opening balances** panel records what the books already held at the start
of a financial year. Type the year (for example `2025-26`) and choose **Load
openings**; every head is listed with its debit and credit.

- Enter **either** a debit **or** a credit for a head, never both.
- Setting both to zero clears that head's opening. The row and its note go.
- An opening trial balance may be saved **unbalanced** while it is being typed.
  The panel reports **Difference** and **Balanced** instead of plugging the
  difference into a suspense figure.
- A month lock does not apply, because an opening balance is a statement about
  the year rather than a document dated inside a month. A **closed** year does
  refuse the change with HTTP 423 until the Administrator reopens it.

Only one year's opening is needed for a balance sheet to work: the sheet uses
the latest captured year at or before the date asked for. A later year with no
opening of its own carries the earlier year forward and says so.

## 9. Balance sheet

The **Balance sheet** panel is built for a date. It merges three layers and
keeps them apart in separate columns per head:

| Column | What it is |
|---|---|
| Opening | The captured opening for the latest opening year at or before the date |
| Vouchers | Posted (and reversed) vouchers dated inside the window; a reversal and its mirror cancel |
| Documents | Sales, receipts, payments and goods received as the document trial balance states them |
| Balance | The head's natural balance: debit-positive for assets and expenses, credit-positive for the rest |

Below the table:

- **Cash and bank closing** gives each cash and bank head's balance and the
  total, which is the closing cash position the records can prove.
- Totals per section, retained earnings (income less expense) and the
  **difference** against assets are printed with the sheet.
- **What this sheet does not claim** lists the limits. In particular the
  document layer covers sales, receipts, payments and goods received only, so
  approved expenses, payroll, stock cost and fixed assets appear only when
  someone posts them as a voucher or captures them as an opening. The sheet
  names that rather than guessing a figure.

An opening trial balance that does not balance is shown as a difference on the
sheet, not corrected behind the scenes.

## 10. Vouchers and journal

The **Vouchers and journal** panel is the stored double-entry ledger. A voucher
has a date, a type (journal, receipt, payment or contra), a narration and at
least two lines; each line names a head and carries a debit or a credit, never
both.

1. **New voucher** (needs `accounts:write`) opens the drawer. Add lines with
   **Add line**; a voucher keeps at least two.
2. **Save draft** stores it even if it does not balance. A draft is not in the
   books and does not move any balance.
3. **Post** checks that debit equals credit. An unbalanced voucher is refused
   with the two totals in the message, and stays a draft.
4. A posted voucher cannot be edited or deleted. **Reverse** it with a reason of
   at least five characters: the system writes a mirror voucher dated **today**
   and marks the original reversed. Today's date is deliberate, because the
   original may sit in a month that is already locked; if today is locked or
   closed the reversal itself is refused.

A future date is refused, as is a date more than ten years old. Posting inside
a locked month or a closed year returns HTTP 423.

## 11. Day book

The **Day book** lists posted and reversed vouchers for a date range in date
order, with debit and credit totals and a **Balanced** check. Drafts are not
listed, because they are not in the books yet. A reversed voucher and its
mirror both stay in the list, so the trail is never erased.

## 12. Bank reconciliation

The **Bank reconciliation** panel compares a captured bank statement with the
book for one bank head and one period.

1. **New statement**: choose the bank head, the period, and the opening and
   closing balance the bank printed. A statement that overlaps an existing one
   for the same head is refused.
2. Open the statement and add its **lines**: date, description, optional
   reference and a signed amount (money in is positive, money out negative).
   A line outside the statement period or with a zero amount is refused.
3. **Match** a line to a receipt, payment or posted voucher line. Only an item
   whose amount and direction agree is accepted. The match drawer lists exact
   amounts first and marks an amount that differs, so a mismatched item is not
   offered silently.
4. The **proof** shows the book opening and closing, matched count and totals,
   the book and statement items still unmatched, and the adjusted book against
   the adjusted statement. **Difference** is zero only when they agree; an
   opening difference is kept apart from a closing difference, and a warning
   explains what each difference suggests.
5. **Unmatch** clears a match. A matched line, and a statement with any matched
   line, cannot be deleted.

**Limits.** There is no bank-file (CSV or OFX) import; lines are typed. With
more than one bank head, document money is not split between heads, so only
voucher lines that name a head can be matched; the statement says so in a
warning.

## 13. Input GST — supplier bills

The **Input GST — supplier bills** panel is the only source of input tax: a
purchase order carries a cost, not a tax split, so input tax must come from the
supplier's own bill.

1. Choose **New bill** (needs `accounts:write`).
2. Pick the supplier, type the supplier's bill number and bill date. The same
   bill number may be used by another supplier, but not twice by the same one
   while the first is live.
3. Enter the taxable value and the tax the supplier charged in the CGST, SGST,
   IGST and cess boxes, plus any round-off printed on the bill. The total is
   computed from those four heads, taxable value and round-off; it is not typed.
4. Leave **ITC eligible** ticked only if the credit is available. The
   application does not decide this for you and never overrides the tick.
5. Add the TDS section, rate and amount if the supplier deducted tax at source.

The table shows each bill's tax heads, whether it is posted or reversed, and the
line under it carries **Net GST payable** (output tax on issued documents less
eligible input) and a memo for creditable GST on expenses. If no supplier bill
has been posted, both read **No data yet** — never zero.

A wrong bill is never edited. **Reverse** it with a reason of at least five
characters: the row stays visible, marked reversed, and every total excludes it.

**Limits.** Blocked input is totalled in the panel but is never subtracted from
the payable. Creditable GST on an expense is a memo only, because an expense
records one GST amount with no head split.

## 14. GST returns and reconciliation

This panel records what was **reported as filed** on the portal and compares it
with the register the application computed. It does not file and does not read
the portal.

1. Pick the month and choose **New return**.
2. Choose GSTR-1 or GSTR-3B, the filed date and the reference (ARN).
3. Type the figures exactly as filed. GSTR-3B also takes the ITC heads and the
   payable after ITC; GSTR-1 has no ITC boxes and refuses an ITC figure.
4. **Build reconciliation** lists each line as Form / Check / Filed / Computed /
   Difference / Result. A difference under half a paisa reads **Matches**;
   anything else is shown with both figures and left alone.

Saving the same month and form again replaces that month's row and records who
changed it in the audit trail. A month later than today is refused.

## 15. TDS and statutory dues

The **TDS and statutory dues** panel reports four heads — provident fund, ESI,
professional tax and TDS — as **withheld**, **deposited to date**, **deposited in
the window** and **outstanding**.

- Vendor TDS is read from posted supplier bills that carry a TDS amount.
- PF, ESI, PT and salary TDS are read only from payroll periods that reached
  approved, processed or paid. A draft payroll is not a liability and is not
  counted.
- **New challan** records a deposit: head, BSR code, challan number, paid-on
  date, amount and the period it relates to. Challans are not matched to a
  single deduction; the outstanding line is simply what no challan covers yet.

A head with no source in the system reads **No data yet** with the reason, not
zero.

## 16. Data gaps

The **Data gaps** panel lists what Accounts still cannot report, with the
missing input named; no figure is guessed. Every gap in the A-series closed on
3 November 2026: expenses (A01), stock cost (A02), the financial-year close
(A03), invoice due dates (A04), input GST and net payable (A05), filed-return
reconciliation (A06), TDS and statutory dues (A07), and — as sections 7–12
describe — vouchers, the day book (A08), bank reconciliation (A09) and opening
balances with the balance sheet (A10).

What remains is not a missing table but a limit of what is posted: a document
does not create its own voucher, so expenses, payroll and stock cost appear on
the balance sheet only when someone posts them or captures them as an opening;
there is no bank-file import; and stock is not valued on the sheet. These
limits are printed on the panels themselves. The P&L gaps (GAP-P01, GAP-P02,
GAP-P03) still appear for a window whose cost, expenses or payroll are
incomplete.

## 17. Permissions enforced on the server

| Action | Permission |
|---|---|
| Read the dashboard, ageing, ledgers, trial balance, balance sheet, day book, bank reconciliation and a party's available advance | `accounts:read` |
| Read the Accounts report and profit and loss endpoints | `accounts:reports` |
| Record a receipt or payment, including an advance; add or change a ledger head; save an opening balance; draft, post or reverse a voucher; capture or reverse a supplier bill; record a filed return or a challan; capture, edit or delete a bank statement and match its lines; lock a month; close a year | `accounts:write` |
| Unlock a month; reopen a year | Administrator only (`require_admin`) |

A role without the permission receives **403** from the API, not merely a
hidden button. The screen result is the same: the control is not rendered.

## 18. Receipts, payments and advances

**Screen:** Accounts → Receipts and payments (`#/accounts/cash`), with the
**Record receipt** and **Record payment** buttons.

A money entry has two modes, chosen in **Record as**:

| Mode | What it does |
|---|---|
| Existing outstanding invoice / bill | Settles open documents for the chosen party, oldest first (or the one you pick under **Settle this invoice/order first**). Any amount left over after every open document is settled is held as an advance. |
| Advance / new payment | Records the whole amount as an advance for the party. It never names an invoice or order, and no invoice is created. |

**Party first.** Choose the distributor (receipt) or supplier (payment) before
anything else. The document list under **Settle this … first** is narrowed to
that party, and the hint line reads the party's available advance from the
server. Changing the mode to **Advance** hides the document list.

**Settling more than is owed.** If the amount is larger than the party's open
documents, every open document is settled and the remainder is stored as an
advance. The confirmation names both figures, for example "₹ 472.00 settled
against 1 invoice, ₹ 28.00 held as advance". The entry row shows the document
numbers and amounts it settled, plus the advance held.

**Only what existed on that day.** A receipt cannot settle an invoice issued
after the day the money moved, and a supplier payment cannot settle goods
received after it. Those documents keep their balance and the money waits as
an advance. This prevents a back-dated entry from silently clearing a document
that did not exist yet.

**Advances drawn down later.** When a new invoice is issued for that
distributor, or goods are received against a supplier order, the oldest
available advance for the party is applied automatically, up to the document
value and dated on the document day. The dispatch or goods-receipt audit row
records `advance_applied`. A remaining advance stays available for the next
document. The **Advance** figure on the entry screen shows what is left.

**What the advance is not.** An advance is not sales revenue and not a
purchase expense:

| Entry | Debit | Credit |
|---|---|---|
| Receipt | Cash or Bank (full amount) | Receivables (settled part) and **Advances from distributors** (remainder) |
| Supplier payment | Payables (settled part) and **Advances to suppliers** (remainder) | Cash or Bank (full amount) |

The two advance heads are seeded ledger roles (`distributor_advance`,
`supplier_advance`) and appear on the balance sheet as a liability and an
asset. Sales and Purchases are untouched by either mode.

**Party ledger.** A receipt is credited in full on its date, and its note names
the invoices it settled and the advance held; a payment is debited in full the
same way. Because the invoice or goods line is already in the ledger, the
settlement is not posted a second time — the closing balance therefore equals
the documents minus the money, and the unapplied remainder is the
**available advance** shown with the ledger.

**Rules kept from before.** An entry is never edited or deleted; a mistake is
corrected by the opposite entry with a note. A locked month and a closed
financial year still refuse the entry, and an advance cannot name a document.
Everything is recorded in the audit log with the party, purpose, allocation
list and advance.

**API.** `POST /api/accounts/payments` accepts
`{kind, purpose, distributor_id | supplier_id, amount, paid_on, mode,
reference, notes}` (no document id in advance mode); the response carries
`purpose`, `allocated`, `advance` and the `allocations` list.
`GET /api/accounts/advances?kind=receipt|payment&party_id=` returns the
available advance and its entries. Reading needs `accounts:read`; recording
needs `accounts:write`.

## 19. Related reading

- Chapter 3 — the Overview's ageing and receivables cards.
- Chapter 13 — billing and invoice detail.
- [`../ACCOUNTS_DATA_GAPS.md`](../ACCOUNTS_DATA_GAPS.md) — the verified gap
  register and what closed on 3 November 2026.
- [`../DASHBOARD_FEATURES.md`](../DASHBOARD_FEATURES.md) — metric definitions
  and the email pack.
