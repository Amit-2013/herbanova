# Herbanova — product map and decision guide

**Date:** 3 November 2026
**Branch:** `feature/gap-closure`
**Purpose:** one page-set that shows what the application contains, how a
record moves through it, and what is still open — so the owner can decide what
to keep, what to switch off and what to build next.

**Sources:** `static/index.html` (navigation and panels), `static/js/app.js`
(routes and permissions), `app/main.py` (37 router inclusions, 343 operations on 4 November 2026),
`app/services/reports.py` (27 reports), `app/services/report_packs.py`
(7 e-mail packs), `app/core/permissions.py` (49 keys), the live database at
migration `0030_sign_in_content` on the development and test databases (88 tables; `0030_sign_in_content` adds four tables), and
[`FEATURE_INVENTORY.md`](FEATURE_INVENTORY.md), which remains the row-level
evidence register. Every status below is copied from that register; nothing is
promoted here.

**Status words**

| Status | Meaning |
|---|---|
| **Verified** | An automated test or a recorded live probe exercises it and passed. |
| **Verified (API)** | API and tests pass; the screen was not exercised in a browser. |
| **Partial** | Works with the stated limitation. |
| **Not run** | Deliberate gap, with the reason stated. |
| **Not built** | No code; a decision is needed before anyone builds it. |
| **Not verified** | Nothing has exercised it. |

---

## 1. The shape of the application

Herbanova is a single-page browser application over a FastAPI/PostgreSQL
server. One sign-in gives a role-dependent menu; every API route repeats the
permission check, so hiding a menu item is convenience only.

| Measure | Current value |
|---|---|
| API operations / paths | 327 / 255 |
| HR and employee operations | 105 (including 4 legacy `/api/employees` endpoints) |
| Modules in the register | 18 (17 working, MOD-15 conditional and not built) |
| Database tables | 88 at head `0030_sign_in_content` |
| Permission keys / groups | 49 / 12 |
| Built-in and live roles | 8 |
| Reports in the catalogue | 27 |
| Scheduled e-mail packs | 7 |
| Automated tests | 446 passed, 0 failed (3 November 2026) |

The menu has five groups: Overview; Sales and customers; Stock and supply;
Finance and insight; People and admin. The next section maps each menu entry to
its screen and its gate.

---

## 2. Screen layout

### 2.1 Entry and shell

| Area | What the user sees | Notes |
|---|---|---|
| Sign-in | `/ui` sign-in card, error line | Session cookie; forced password-change screen blocks everything else until changed |
| Sidebar | Module groups, user name, role pill, dark-theme toggle, sign out, environment badge ("Demo build") | A link is hidden when its read permission or feature switch is absent |
| Page head | Screen title, one-line subtitle, screen actions | Actions are permission-gated too |
| Drawers | Every create/edit/detail panel slides in from the right over the list: 62% wide at ≥1440 px, 68% at 1024–1439, 82% at 768–1023 and the whole screen below 768. The page behind is dimmed and scroll-locked; the drawer body scrolls on its own under a fixed title and ×, table headers stay pinned, and only a table too wide for the panel scrolls sideways inside its own box. ×, Escape and an outside click close it (outside click on desktop and tablet). One shared container, so invoice, customer, supplier, distributor-ledger, purchasing, expense, HR and Accounts drawers behave the same | Same server checks as the list; actions and payloads unchanged |
| Overview tools | "Search everything" (Ctrl/Cmd-K), From/To dates, presets 7D / 30D / 90D / This month / Last month / This FY, dark theme, Reset database (Administrator), MoM & YoY link | Search and reset are separately gated |

### 2.2 Navigation tree

```
Overview                      #/dash
Sales and customers
  Leads                       #/leads
  Lost leads                  #/lost
  Today's follow-ups          #/followups
  Customers & distributors    #/customers      (#/distributors is an alias)
  Sales orders                #/sales
  Billing                     #/billing        (hidden without invoice/billing rights)
  Approvals                   #/approvals
Stock and supply
  Purchases                   #/purchasing
  Products                    #/products
  Inventory                   #/inventory      (stock | ledger | warehouses)
  Free samples                #/foc
  Suppliers                   #/suppliers      (hidden without supplier:read)
Finance and insight
  Accounting & Finance        #/accounts       (hidden without accounts:read or accounts:reports)
    Section bar adds one address per panel:
      Performance             #/accounts/reports
      Receivables             #/accounts/receivables
      Receivables by distributor  #/accounts/receivables-by-distributor
      Ageing                  #/accounts/ageing
      Payables                #/accounts/payables
      Receipts and payments   #/accounts/cash
      GST outward             #/accounts/gst-out
      Input GST               #/accounts/gst-in
      GST returns             #/accounts/gst-returns
      TDS and statutory       #/accounts/statutory
      Trial balance           #/accounts/trial-balance
      Ledger heads            #/accounts/ledger-heads
      Opening balances        #/accounts/openings
      Balance sheet           #/accounts/balance-sheet
      Vouchers                #/accounts/vouchers
      Day book                #/accounts/day-book
      Bank reconciliation     #/accounts/bank
      Financial years         #/accounts/years
      Month locks             #/accounts/locks
  Expenses                    #/expenses       (hidden without expense:read)
  Reports                     #/reports
  Geography                   #/geo            (hidden without sales:read)
People and admin
  HR Management               #/hr             (also open to self-service attendance holders)
  Roles & Permissions         #/roles          (hidden without user:manage)
  Settings & Administration   #/settings       (hidden without user:manage)
  Scheduled reports           #/scheduled      (hidden without email:manage)
Linked, not in the sidebar
  MoM & YoY dashboard         #/compare        (Overview link)
  Logins and employees        #/users          (Settings link)
  Tax, discounts and profile  #/tax            (Settings link)
  Audit trail                 #/audit          (Settings and Overview links)
```

### 2.3 What each screen contains

| Screen | Gate | Panels and controls |
|---|---|---|
| **Overview** | signed in; each card also needs its section key | Needs attention, Accounts, Receivables ageing, Stock to watch, Stock by warehouse, Waiting to be received, Approvals waiting, Top products, Sales by category, Pipeline, Customers and credit, PO ageing, Corrections after billing, HR today, Recent activity, System health (module register and migration head) |
| **Leads / Lost / Follow-ups** | `lead:read`; write `lead:write`; assign `lead:assign` | Lead list with owner, status, next follow-up; lost list; today's follow-ups; create/edit drawer |
| **Customers & distributors** | `sales:read`; act with `distributor:write`, `credit:manage` | One party master: search, status filter, credit limit, terms, group, contacts, blocked status |
| **Sales orders** | `sales:read`; write `sales:write`; dispatch `dispatch:write` | Order list, create/edit, submit, cancel, dispatch with warehouse choice, tax preview, promised delivery date |
| **Billing** | `sales:read`; invoice rights for actions | Issued invoices, invoice drawer (due date, terms, place of supply, challan/e-way fields), credit and debit notes, cancellation, PDF print/verify |
| **Approvals** | `approval:read` | Generic queue: Waiting / Decided / All, with request number, type, document, requester, status, remarks |
| **Purchases** | `stock:read`; write `stock:write` | Purchase orders, part receipts, goods receipts, capacity check and Administrator override, cost-less line remark |
| **Products** | `product:read`; write `product:write` | Product list, paging/search, SKU, HSN, GST rate, category, brand, reorder level, MRP and price |
| **Inventory** | `stock:read`; write `stock:write` | Stock on hand, stock ledger/movements, warehouses and capacity (three tabs) |
| **Free samples (FOC)** | `foc:read`; write `foc:write`; approve `foc:approve` + Administrator | FOC on hand, free-sample notes, approval/reversal, audited historical correction |
| **Suppliers** | `supplier:read`; write `supplier:write`; bank change `supplier:bank` | Supplier records (blocked, never deleted), GSTIN/PAN checks, bank-detail changes needing a second person |
| **Accounting & Finance** | `accounts:read`; write `accounts:write`; reports `accounts:reports` | A section bar across the top shows one entry per panel and only the chosen panel below it; opening `#/accounts` shows Performance for `accounts:reports` holders and Receivables otherwise. Panels: Performance, profit and loss, MoM/YoY, trend, by state, receivables drill-down, data gaps, receivables, ageing with due dates, payables, receipts and payments, outward GST register, input GST — supplier bills, filed GST returns and reconciliation, TDS and statutory dues, trial balance, ledger heads, opening balances, balance sheet, vouchers and journal, day book, bank reconciliation, financial years, accounting month locks |
| **Expenses** | `expense:read`; write `expense:write`; approval switch and threshold Administrator | Expense heads, entries, approval threshold, reversal, receipt attachment, "how an expense reaches profit" note |
| **Reports** | per-report view key; export `report:export` | Search and category filter, 27 reports, filters, paging, sorting, CSV/PDF export, reconciliation checks, "No data yet" empty state |
| **Geography** | `sales:read` | State tile map, top/bottom states, sales by state, returns by state, GST state split — state only, because district/city are not captured |
| **MoM & YoY** | `sales:read` or `stock:read` | Twelve-month trend, movement, best/worst/seasonality, top products, top distributors, run-rate |
| **HR Management** | `hr:read`, or `hr:attendance_self` for the self view | Dashboard (needs attention, attendance trend, celebrations and holidays, team shape), People directory, HR tasks, My workspace; drawers for attendance, monthly register, leave, leave calendar, on duty, payroll, shifts, branches and locations, HR masters, HR reports, announcements, period locks, letter templates, notifications |
| **Roles & Permissions** | `user:manage` | Roles, tree editor, Feature availability switches (Administrator), Access control catalogue |
| **Settings & Administration** | `user:manage` (each panel repeats its own check) | Links to roles, logins/employees, tax and company profile, audit, scheduled reports, HR policies; Database reset (Administrator, secondary password); Email and SMTP (Administrator); Employees list |
| **Scheduled reports** | `email:manage` | Schedules, recipients and groups, delivery log, preview, test-mode status |
| **Tax, discounts and profile** | `tax:read`; write `tax:write` | Company tax profile, GST rate master by HSN and date, discount slabs with approval threshold, tax quote |

---

## 3. Feature list by area

Each row is a capability cluster; the evidence and exact test names stay in
[`FEATURE_INVENTORY.md`](FEATURE_INVENTORY.md). "Screen not browser-verified"
means the API and tests pass but the new panel has not been driven in a browser
since it was built.

### 3.1 Identity, access and administration

| Capability | Status | Gate / note |
|---|---|---|
| Sign in, sign out, session cookie | Verified | credentials |
| Forced first-password change | Verified | blocks every other route |
| Lockout after five failures for 15 minutes | Partial — code read, not exercised | `app/services/lockout.py` |
| Server-side permission checks on every API route | Verified | 49-key catalogue |
| Role editor, custom roles, parent-child rules, Administrator-only keys | Verified | `user:manage` |
| User create, disable, password reset; employee ↔ login link | Verified | `user:manage` |
| Audit trail viewer and export | Verified (live) | `audit:read` |
| Secondary password on user management | Partial — gate tested, destructive reset not run | `user:manage` + secondary |
| Database reset (guarded, backup, classification, maintenance pause) | Not run by design | `db:reset` + secondary password |
| Logins kept separate from the employee master | Verified | `user:manage` / `employee:*` |
| Central module On/Off switches | Verified | Administrator role only |

### 3.2 Masters

| Capability | Status | Gate / note |
|---|---|---|
| Products, SKUs, HSN validation, paging and search | Verified | `product:read/write` |
| Product category, brand, reorder level with suggestions | Verified (API) | `0024`; screen not browser-verified |
| GST rate master and discount slabs | Verified (live) | `tax:read/write` |
| Company tax profile and tax quote | Verified (live) | `tax:read/write` |
| Suppliers, GSTIN/PAN checks, block instead of delete | Verified (live) | `supplier:read/write` |
| Supplier bank change with a second person | Partial — live smoke, no dedicated test | `supplier:bank` + approval |
| Customers and distributors as one master, credit limit, terms, group | Verified | `sales:read`; write gates |
| Party search and status filter; legacy `#/distributors` opens the same screen | Verified | `sales:read` |
| Warehouses and capacity | Verified | `stock:read/write` |

### 3.3 Buying, stock and costing

| Capability | Status | Gate / note |
|---|---|---|
| Purchase orders, part receipts, goods receipts | Verified | `stock:read/write` |
| Cost-less line needs a remark | Verified | PO drawer |
| Warehouse capacity check and Administrator override | Verified | GRN |
| Stock ledger, movements, FEFO batches and expiry | Verified | `stock:read/write` |
| Warehouse utilisation | Verified | `stock:read` |
| Free-of-cost receipts, approved sample notes, audited correction | Verified (API) | `foc:*`; screen not browser-verified |
| Weighted-average issue cost, invoice attribution, audited cost corrections | Verified | `accounts:write` for correction |
| Stock corrections respect month locks and year close | Verified (API) | `423` refusal |

### 3.4 Selling, billing and printing

| Capability | Status | Gate / note |
|---|---|---|
| Leads, owners, follow-ups, lost reasons, reassignment | Verified (live) | `lead:*` |
| Sales orders, promised delivery date, approval timestamp | Partial — promise/approval/dispatch covered; every transition is not | `sales:read/write` |
| Credit check at submit and dispatch; discount-threshold approval | Verified | Administrator for credit-limit decisions |
| Dispatch with warehouse choice, FEFO allocation, invoice issue | Verified | `dispatch:write` |
| Tax invoices, place of supply, seller/buyer snapshots | Verified (live) | `invoice:write` |
| Invoice due date frozen from the distributor's terms | Verified (API) | `0025`; screen not browser-verified |
| Credit and debit notes, linked and capped to the invoice, optional stock return | Partial — live smoke, no dedicated test file | `note:write` |
| Post-billing invoice edit (movement/challan/e-way fields) | Verified | `invoice:edit_post_billing` + Administrator |
| Invoice cancellation | Verified (live) | `invoice:cancel` |
| Secure PDFs, SHA-256, print log, verification, signatory alignment | Verified | `print:document` |

### 3.5 Accounts

| Capability | Status | Gate / note |
|---|---|---|
| Distributor and supplier ledgers; receivables and payables | Verified | `accounts:read` |
| Receipts and payments (never edited; corrected by an opposite entry), two-mode settlement and advances with automatic draw-down | Verified | `accounts:write`; `tests/test_accounts_advances.py`; browser walk 3 Nov 2026 |
| Outstanding and ageing in four buckets | Verified | `accounts:read` |
| Ageing split by due date: overdue, due within 7 days, later, no due date | Verified (API) | `0025`; screen not browser-verified |
| Outward GST register from invoices and notes | Verified | `accounts:read` |
| Trial balance from the documents | Verified | `accounts:read` |
| Accounts dashboard, report, month/region comparison, accounts e-mail block | Verified | `accounts:reports` |
| Expenses: heads, entries, approval, reversal, receipts; P&L inclusion | Verified | `expense:*` |
| Profit and loss, with named gaps | Verified | `accounts:reports` |
| Payroll in P&L: approved months; cut month allocated by working days, never estimated | Verified (API) | screen not browser-verified |
| Financial-year close and reopen (`423` on documents inside a closed year) | Verified (API) | reopen Administrator only; screen not browser-verified |
| Accounting month locks (`423` on receipts, notes, dispatch, costs, expenses) | Verified (API) | unlock Administrator only; screen not browser-verified |
| Input GST from captured supplier bills; eligible vs blocked; net GST | Verified | `accounts:read/write`; browser probe 3 Nov |
| Filed GSTR-1 / GSTR-3B figures compared line by line with the register | Verified | `accounts:read/write`; browser probe |
| TDS and statutory dues from posted bills and approved payroll, less challans | Verified | `accounts:read/write`; browser probe |
| Chart of accounts: nine seeded heads plus extra heads, rename, deactivate | Verified | `accounts:read/write` |
| Opening balances per head and financial year, imbalance reported | Verified | `accounts:read/write` |
| Journals and vouchers: draft, post, reverse; unbalanced posting refused | Verified | `accounts:read/write` |
| Day book with debit/credit totals and balanced check | Verified | `accounts:read` |
| Balance sheet merging openings, posted vouchers and document trial balance | Verified | `accounts:read` |
| Bank reconciliation: statement, lines, match/unmatch, named difference | Verified | `accounts:read/write` |

### 3.6 Reports and dashboard

| Capability | Status | Gate / note |
|---|---|---|
| 27-report catalogue filtered by permission | Verified | per-report view key |
| Paging, sorting, filters | Verified | per-report key |
| CSV/PDF export with audit | Verified | `report:export` |
| Reconciliation checks on reports | Verified | per-report key |
| "No data yet" empty state | Verified | per-report key |
| Overview KPIs, search, activity, system health | Verified | section keys |
| Period selector and permission masking | Verified | section keys |
| Sales/purchase series and approvals card | Verified | `sales:read`, `stock:read` |
| Month-to-date, projection, trend, breakdowns | Verified | `sales:read` |
| State geography from invoice snapshots | Verified | `sales:read` |
| Phase 3 insight cards | Verified | section keys |
| Module register and migration-head health | Verified | signed in |

### 3.7 HR

| Capability | Status | Gate / note |
|---|---|---|
| HR dashboard | Verified | `hr:read` |
| Employee directory, filters, saved views | Verified | `hr:read` |
| Employee create/edit, bulk CSV import with preview and undo | Verified | `hr:write` |
| Profile tabs, history, photo, documents and assets | Verified | `hr:read/write` (+ self) |
| Bank/ID masking and write refusal | Verified | `hr:confidential` / payroll / self |
| Team scoping (manager chain, self) | Verified | scope helpers |
| Check-in/out with geofence; manual and bulk attendance | Verified | self / manage keys |
| Monthly calendar, missing-day gaps, "not required" exempt days | Verified | `hr:read` / self |
| Attendance and payroll period locks | Verified | `hr:write` / payroll |
| Leave types, balances, carry-forward; leave applications and approvals | Verified | `hr:read/write`, `hr:leave_approve` |
| On-duty requests | Verified | `hr:attendance_self` |
| Branch and office masters, geofence centre/radius, attendance mode | Verified | `hr:read/write` |
| Employee branch/office assignment; office must belong to the branch | Verified | `hr:write` |
| Attendance rules by branch, office, designation and employee, effective-dated | Verified | `hr:write` |
| Server-side gating of attendance the policy exempts, naming the source | Verified | manage / self |
| Branch and office filters across HR screens, dashboard and reports | Verified | `hr:read` |
| Department, holiday, leave-type and salary-component masters | Department and holiday verified; leave type and salary component partial (list renders; create form not exercised; no write tests) | `hr:write` |
| Salary structures, effective-dated, closing the previous one | Verified | `hr:payroll_prepare` + `hr:write` |
| Payroll prepare → submit → process → pay | Verified | prepare / approve split |
| Skipped employees listed with the reason | Verified (API) | screen not browser-verified |
| Statutory summary, bank file with masked preview, reconciliation | Verified | payroll + confidential |
| Payslips (own after release; any with the right) | Verified | `hr:confidential` / own |
| Letters, ID cards, attendance sheet, leave statement PDFs | Verified | `hr:read` / self |
| HR reports (headcount, attendance, leave, cost) | Verified | `hr:reports` |
| Notifications, announcements, digest | Verified | `hr:write` to send |
| Scheduled HR pack (no salary) | Verified (test mode) | `email:manage` |
| Overtime, salary revision and reimbursement approvals | Not built | labels only |
| Payroll posted to the accounting ledger | Not built | no authorised mapping |

### 3.8 Scheduled e-mail and platform

| Capability | Status | Gate / note |
|---|---|---|
| Recipients and groups; schedule maths (daily, weekly, monthly, holidays, cron) | Verified | `email:manage` |
| HTML/text packs and attachments; preview | Verified | `email:manage` |
| DB-backed worker with retries, claims and delivery log | Verified | background |
| Test-mode guardrails | Verified | no real address can be reached |
| SMTP settings and test composer (encrypted password, To/CC, dry run, outbox) | Verified | `email:manage` |
| Live e-mail delivery | Not verified | no SMTP or recipient approved |
| Backup, restore and reconciliation | Verified — 1 Nov 2026: 63 tables, 575 rows, 26 reports, 0 unreconciled | operator |
| Health endpoint | Verified | public |

---

## 4. End-to-end flows

Each flow names the screen, the server gate and the hard stops. A hard stop is
a rule the server enforces even if the browser offers the button.

### 4.1 Sign in and reach a screen

1. Open `/ui`, sign in; the server sets the session cookie.
2. If `must_change_password` is set, only change-password and sign-out work.
3. The browser reads the effective permission set and hides links it cannot use.
4. Every API call re-checks the permission, the feature switch and the token
   version; role edits apply on the next request without a new sign-in.

### 4.2 Lead to cash

1. **Lead** — create or import a lead with an owner and next follow-up
   (`lead:write`). Status moves new → contacted → qualified → won/lost.
2. **Customer** — the won lead becomes a distributor/customer with a credit
   limit, payment terms and group (`distributor:write`).
3. **Sales order** — draft with lines, price, discount and promised delivery
   date (`sales:write`). The drawer previews tax.
4. **Submit** — the server checks stock and credit exposure.
   - Stock short → `409` with the shortage.
   - Exposure over the limit → approval `credit_limit` (Administrator decides).
   - Discount over the applicable slab threshold → approval `discount`.
   - Nothing over the line → status `approved` with `approved_at` stamped.
5. **Dispatch** — choose the warehouse (`dispatch:write`). The server refuses a
   closed financial year or locked month (`423`), re-checks delivered exposure,
   allocates FEFO batches, snapshots the issue cost, **issues the invoice**, and
   posts the stock movements.
6. **Invoice** — numbered per financial year, seller and buyer snapshots frozen,
   due date computed from the distributor's terms. PDF print is logged and
   hashed (`print:document`).
7. **Receipt** — two modes (`accounts:write`): settle open invoices for the
   distributor oldest-first and hold any excess as an advance, or record the
   whole amount as an advance with no invoice. A later invoice draws the
   advance down automatically. A mistake is corrected by an opposite entry,
   not an edit.
8. **Credit / debit note** — linked to the invoice, capped at its value; a
   credit note can return goods to the same batches and warehouse.
9. **Reporting** — receivables, ageing by due date, outward GST register,
   trial balance, P&L and the Overview cards all read the same records.

### 4.3 Purchase to input tax

1. **Purchase order** — supplier, lines, rate, warehouse and expected receipt
   (`stock:write`). A line with no cost needs a remark.
2. **Goods receipt (GRN)** — full or part receipt. The capacity check refuses
   an over-filled warehouse unless an Administrator overrides.
3. **Stock** — batch, expiry and cost land in the stock ledger; weighted average
   drives issue cost later.
4. **Supplier bill** — capture the supplier's invoice number, taxable value,
   CGST/SGST/IGST/cess, round-off, total, ITC eligibility and TDS
   (`accounts:write`). One bill number per supplier; a wrong bill is reversed
   with a reason, never edited.
5. **Payables** — remain *goods received less payments*. Capturing a supplier
   bill does **not** create a payable — a deliberate separation. A supplier
   payment settles received bills oldest-first; any excess, or a payment with
   no bill, is held as an advance and drawn down by a later goods receipt.
6. **Input GST** — the only source of input credit. Eligible and blocked input
   are shown separately; blocked is never netted.
7. **Net GST** — output tax from invoices and notes less eligible input.
8. **Filed returns** — record the GSTR-1 and GSTR-3B figures as filed; the
   screen compares each line with the computed register and names differences.
9. **Challans** — record deposits against TDS and statutory dues; the
   outstanding remainder per head is what is left.

### 4.4 Free samples (FOC)

1. Receive free stock against a purchase order or as a known free position
   (`foc:write`); it stays separate from costed stock.
2. Draft a free-sample note for one recipient; no invoice, revenue or GST.
3. Approve or reject the note (`foc:approve` **and** Administrator); a posted
   note is reversed rather than edited.
4. Historical corrections run as a fingerprint-guarded plan/apply pair.

### 4.5 Expense to profit

1. Create or edit expense heads (`expense:write`).
2. Record an expense with date, head, amount, tax and receipt attachment. If an
   approval switch and threshold are configured, crossing it creates an
   `expense` approval request.
3. Approve or reject in the Approvals queue; an approved expense is reversed
   with a reason if wrong.
4. Only approved, non-reversed, dated entries in the window reach the profit and
   loss; the month lock and year close refuse out-of-period writes.

### 4.6 Books, close and reconcile

1. **Opening balances** — entered per head and financial year; an unbalanced
   opening is reported, never plugged (`accounts:write`).
2. **Vouchers** — journal, receipt, payment or contra; at least two one-sided
   lines. A draft may be unbalanced; **posting refuses an unbalanced voucher**.
3. **Posting** — freezes the lines. A mistake is reversed by a dated mirror,
   and both stay in the day book.
4. **Balances** — the balance sheet merges three layers per head: opening
   balances, posted vouchers and the document trial balance. Limits and the
   retained-earnings treatment are named on the screen.
5. **Bank reconciliation** — capture a statement per bank head and period with
   its printed opening and closing balances; add lines; match each line to one
   receipt, payment or posted voucher line when amount and direction agree;
   unmatch when wrong. A matched line cannot be deleted. The proof keeps the
   opening difference apart from the closing difference.
6. **Month lock** — lock a month with a reason (`accounts:write`); receipts,
   payments, notes, dispatch, cost corrections and expenses dated in it are
   refused (`423`). Only an Administrator unlocks.
7. **Financial-year close** — close April–March with a reason; every dated
   document inside the year is refused (`423`) until an Administrator reopens it
   with a reason. Both actions are audited.
8. **Reporting** — day book, trial balance, P&L, balance sheet and the GST and
   statutory panels all read the same stores.

### 4.7 Hire to payslip

1. **Branch and office** — create the site, its address, geofence centre/radius
   and attendance mode (`hr:write`).
2. **Attendance rules** — optional rules by branch, office, designation or
   employee, effective-dated with priority; the resolved policy and its source
   show on the employee form and profile (`hr:read`).
3. **Employee** — create the employee, assign office (the branch follows) and
   department; link a login only with `user:manage`.
4. **Attendance** — self check-in/out inside the geofence, or manual/bulk entry
   (`hr:attendance_manage`). Exempt days are marked "not required", not as gaps.
5. **Leave and on duty** — balances accrue and carry forward; an application
   creates `hr_leave` / `hr_od` approval requests decided with
   `hr:leave_approve`.
6. **Salary set-up** — components (earning/deduction; statutory head only on a
   deduction), then an effective-dated structure that closes the previous one.
7. **Payroll prepare** — the run takes employees with an active structure for
   the month; employees without one are listed with the reason. A locked period
   or closed year refuses the run.
8. **Approve → process → pay** — approval is a separate right
   (`hr:payroll_approve`, currently Administrator only). Processing and marking
   paid follow; the bank file and statutory summary come from the same run.
9. **Outputs** — payslips after release (own or `hr:confidential`), letters, ID
   cards, attendance sheet and leave statement PDFs.
10. **Reporting** — HR reports and the P&L read approved payroll. Payroll is
    **not posted to the ledger** (see §5).

### 4.8 Reports and scheduled e-mail

1. Open **Reports**; the catalogue shows only reports the role may view.
2. Filter, page and sort; export CSV/PDF (adds `report:export` and an audit row).
3. Empty windows say "No data yet"; reconciliation checks run with the report.
4. **Scheduled reports** — choose a pack (Daily, Weekly, Monthly MD, Alerts,
   Accounts, Custom, HR), recipients/groups, schedule (daily, weekly, monthly,
   holiday-aware, cron) and preview.
5. A database worker claims due runs, retries failures, writes a delivery-log
   row and respects test mode; no real address is reachable until SMTP and
   recipients are approved.

### 4.9 Administration and recovery

1. **Roles** — edit a role's permission tree; parent-child and Administrator-only
   rules are enforced on save and on every request.
2. **Feature availability** — switch a module off; its API prefix and
   permissions are denied for every role.
3. **Logins** — create/disable a user, reset a password, link to an employee.
4. **Audit** — read and export the trail.
5. **Backup / restore** — the operator script backs up, restores and reconciles.
6. **Reset** — Administrator, secondary password and reset key; the reset pauses
   writes, keeps the audit trail and the master tables it classifies as KEEP.

---

## 5. What is not built, not verified or limited

These are the honest edges. They are also the decision list.

| Area | State | Consequence |
|---|---|---|
| PO printing | Not built | Purchase orders cannot be printed as a PDF |
| E-invoice / e-way bill portal | Not built (MOD-15 conditional) | Invoice fields can carry challan/e-way details, but nothing talks to the portal |
| Excel import | Not built | CSV only, and only for HR bulk employee import |
| Real e-mail delivery | Not verified | Scheduler, SMTP and preview are built and tested in test mode only |
| Payroll → ledger posting | Not built | P&L reads approved payroll, but the balance sheet has no salary/journal posting |
| Multi-level approval chains | Not built | One decision per request; no sequential approver ladder |
| Overtime, salary revision, reimbursement approvals | Not built | Labels exist, no handler |
| Physical-device and screen-reader verification | Not verified | No device or tooling available |
| Recent Accounts screens (financial years, month locks, due-date ageing, payroll-in-P&L, skipped employees) | Verified at API/test level | Not driven in a browser after the change |
| Leave-type and salary-component create/edit | Partial | List renders; the create form was not exercised and there is no write test |
| Credit/debit notes, supplier bank change, lockout | Partial | Live smoke or code read, no dedicated test |
| Database reset | Not run | Destructive by design; only backup/restore was exercised |
| Sales-order status coverage | Partial | Promise, approval and dispatch are covered; not every transition |

**Deliberate design limits worth knowing before deciding:**
supplier bills are not payables (payables stay goods received minus payments);
GST returns are recorded and compared, never filed; geography stops at state
because district/city are not captured; a payroll month the P&L window cuts
short is allocated by working days, never estimated; a figure the records cannot
prove says so instead of showing zero.

---

## 6. Decision checklist

Mark one line per area. "Switch off" is cheap: every module has an
Administrator-only feature switch and its permissions are removed for all roles,
so a module can be retired without deleting code. Deleting code is a separate,
larger decision.

### 6.1 Core — needed to trade

| Area | Why it is core | Suggested default |
|---|---|---|
| Identity, roles, audit | Every action depends on it | Keep |
| Products, stock, warehouses | Nothing moves without them | Keep |
| Purchase orders, receipts, costing | Stock and cost of goods | Keep |
| Sales orders, dispatch, invoices, PDFs | Revenue and the legal document | Keep |
| Receivables, payables, receipts/payments | Money in and out | Keep |
| Reports and Overview | The operating picture | Keep |
| Backup, restore and health | Recovery and uptime | Keep |

### 6.2 Built, but confirm whether this business uses it

| Area | What it adds | Suggested default |
|---|---|---|
| Leads and follow-ups | Pre-sales pipeline | Confirm |
| Credit control and approvals | Limit and discount discipline | Confirm |
| Free samples (FOC) | Sample stock outside revenue | Confirm |
| Expenses | Expense heads, approval, P&L | Confirm |
| Full Accounts suite (GST, TDS, vouchers, bank rec, balance sheet) | Statutory and bookkeeping depth | Confirm; switch off parts not used |
| HR suite (people, attendance, leave, payroll, outputs) | A separate product surface | Confirm |
| Scheduled e-mail | Recurring packs | Confirm; keep in test mode until SMTP is approved |
| Geography and MoM/YoY | Extra insight views | Confirm |
| HR masters (departments, holidays, leave types, salary components) | Configuration depth | Keep if HR stays |

### 6.3 Not built — choose whether to fund

| Item | Decision to make | Note |
|---|---|---|
| PO printing | Needed for supplier paperwork? | Small, isolated PDF builder |
| E-invoice / e-way bill | Does turnover or customer demand require it? | MOD-15 was made conditional on turnover |
| Excel import | Are CSV imports enough? | HR bulk import is CSV today |
| Real e-mail | Which SMTP, sender and recipients? | Test mode is deliberate until approved |
| Payroll → ledger posting | Must salary appear in the balance sheet? | Needs an authorised mapping |
| Multi-level approvals | Is one approver enough? | The table exists; no chain logic |
| Overtime / revision / reimbursement | Are these handled outside the app? | Labels only |
| Device and screen-reader testing | Is accessibility a requirement? | No tooling available |

### 6.4 Before calling it production-ready

1. Browser-verify the HR payroll/skipped screens; the Accounts section bar and
   the balance-sheet, bank, GST-outward and trial-balance panels were walked on
   3 November 2026.
2. Exercise the leave-type and salary-component write forms and add tests.
3. Decide SMTP and run one live delivery test if e-mail is kept.
4. Exercise the guarded reset on a copy, not on live data.
5. Run the full suite and `alembic check` against the release database.
6. Confirm the backup schedule and where dumps are stored.
7. Confirm every role's effective permissions with the business owners.

---

## 7. Where the evidence lives

| Document | What it answers |
|---|---|
| [`FEATURE_INVENTORY.md`](FEATURE_INVENTORY.md) | Row-level feature, gate, evidence and status |
| [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) | Type scale, palette with measured contrast, spacing, components, states, motion and breakpoints |
| [`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) | What was run, when, and what was not |
| [`REQUIREMENTS_TRACEABILITY_MATRIX.md`](REQUIREMENTS_TRACEABILITY_MATRIX.md) | Requirement → route → test |
| [`permissions-matrix.md`](permissions-matrix.md) | Every key, every role, every guarded route group |
| [`DATABASE_TABLE_COLUMN_REGISTER.md`](DATABASE_TABLE_COLUMN_REGISTER.md) | Every table and column at head `0028` |
| [`ACCOUNTS_DATA_GAPS.md`](ACCOUNTS_DATA_GAPS.md) | Accounting gaps A01–A10 and their closure |
| [`DB_RESET.md`](DB_RESET.md) | Reset modes, table classes and recovery |
| [`user-manual/`](user-manual/README.md) | Task-by-task operator instructions |
