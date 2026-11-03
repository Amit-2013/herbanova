# Dashboard audit — Phase 1

**Date:** 1 November 2026
**Scope:** read-only audit of what the system does today, what the Overview can honestly show, and what must be captured before a card can show a number.
**Status:** audit complete; no code, schema or data was changed by the audit itself. Phase 2 starts only after owner approval.

**Gap-closure update (3 November 2026):** migration `0024_catalog_order_dates` closes GAP-D01 and GAP-D02 and the sales-order part of GAP-D05 (see the status column in §5). Rows below keep their original finding and are marked with the revision that resolved them; the purchase-order expected date remains open.

Evidence markers: **VERIFIED** (read in code), **MEASURED** (run and timed), **PARTIAL** (some data exists, some does not), **MISSING** (no data or no code), **PLANNED** (Phase 2/3 work).

---

## 0. Sources read

**Documents.** There is no `BRD`, `Feature Inventory`, `Requirements Traceability Matrix` or README by those names. The documents that exist and were read are:

- `docs/STAGE1_AUDIT_BASELINE.md`, `docs/STAGE1_REAUDIT.md`, `docs/STAGE4_REMEDIATION.md`
- `docs/DATABASE_TABLE_COLUMN_REGISTER.md`, `docs/FORMULA_AND_BUSINESS_RULE_REGISTER.md`
- `docs/FRONTEND_BACKEND_FIELD_MAPPING.md`, `docs/permissions-matrix.md`
- `docs/FORMULA_RECONCILIATION_TESTS.md`, `docs/user-manual/`

**Code.** All routers in `app/api/`, all models in `app/models/`, the reporting, ledger, sales, invoice, notes, inventory and Telegram services, `app/core/module_register.py`, and the SPA (`static/index.html`, `static/css/styles.css`, `static/js/app.js`).

**Executed evidence.**

- `pytest tests/test_dashboard.py` — 4 tests pass; the suite as a whole was last run at 62 passed.
- `GET /api/dashboard` called directly against the configured database (read-only) and against a synthetic load in `herbanova_bcs_test`, rolled back.
- Row counts read with `SELECT count(*)` only; `alembic current` read-only (`e4f5a6b7c8d9`, equal to head).

---

## 1. Module inventory

| Module | What exists today | Endpoints | Tables | Missing or half-built |
|---|---|---|---|---|
| **Products** | Create, list/search, edit; SKU unique; HSN/UQC; MRP; category, brand and reorder level (`0024`); status active/inactive | `GET/POST /api/products`, `PATCH /api/products/{id}`, `GET /api/products/options`, `GET /api/products/catalog` | `products` | No created/updated timestamp; no batch-level cost |
| **Stock and batches** | Warehouses, batches with expiry/owner, append-only movement ledger, exact on-hand, FEFO allocation at dispatch, receipt via GRN; each stock row carries the product's reorder level | `GET/POST /api/warehouses`, `GET /api/inventory/batches`, `GET /api/inventory/movements` | `warehouses`, `batches`, `stock_movements` | No warehouse capacity; no batch cost or valuation; no batch `created_at`; no write-off/shrinkage reason; no QC status; no recall view |
| **Purchase orders** | Create, list, receive in parts (GRN), cancel; duplicate-delivery guard; receipt posts stock once | `GET/POST /api/purchase-orders`, `GET /{id}`, `POST /{id}/receive`, `POST /{id}/cancel` | `purchase_orders`, `purchase_order_lines`, `goods_receipts`, `goods_receipt_lines` | No expected delivery date; no purchase invoice or input tax; no supplier price history view |
| **Sales orders** | Draft → pending approval → approved → dispatched / rejected / cancelled; credit and stock checked at submit and dispatch; warehouse chosen at dispatch; promised delivery date and approval timestamp (`0024`) | `GET/POST /api/sales-orders`, `GET /{id}`, `GET /{id}/tax-preview`, `PATCH /{id}/delivery-date`, `POST /{id}/submit`, `/cancel`, `/dispatch` | `sales_orders`, `sales_order_lines`, `batches`, `stock_movements`, `approval_requests`, `invoices` | No pipeline view inside the order screen (the Overview shows it); promises recorded before `0024` are null and excluded from lateness |
| **Approvals** | Central queue; sales-order, post-billing and HR categories; segregation of duties; reason required on decision; audit-logged | `GET /api/approvals`, `POST /api/approvals/{id}/decide`, `POST /api/approvals/post-billing/{invoice_id}`, supplier bank changes | `approval_requests` | No SLA/ageing policy; no notification to approvers (Telegram only mirrors audit events) |
| **Billing** | Tax invoices at dispatch, immutable; credit/debit notes; cancellation with reason; post-billing amendment via approval; secure PDF, print log, verification | `GET/POST` under `/api/invoices`, `/api/credit-notes`, `/api/debit-notes`, `/api/printing` | `invoices`, `invoice_lines`, `credit_notes`, `debit_notes`, `document_sequences`, `print_logs` | Invoice freezes its payment terms and due date at issue (`0025`); ageing shows the due-date split. No input tax; no e-invoice/e-way integration (MOD-15 conditional) |
| **Accounts** | Receipts and payments, outstanding, party ledgers, ageing, outward GST register, input GST, trial balance, chart of accounts, opening balances, vouchers, day book, balance sheet and bank reconciliation | `GET/POST /api/payments`, `/outstanding`, `/ledger/...`, `/ageing`, `/gst-register`, `/trial-balance`, `/ledger-accounts`, `/opening-balances`, `/vouchers`, `/day-book`, `/balance-sheet`, `/bank-statements` | `payments`, `ledger_accounts`, `opening_balances`, `vouchers`, `voucher_lines`, `bank_statements`, `bank_statement_lines`, plus documents above | Documents are not posted as vouchers automatically; the balance sheet merges both layers and names what the document layer does not cover (expenses, payroll, stock cost) |
| **Leads and follow-ups** | Create, owner, status, next follow-up, append-only activity history, overdue flags | `GET/POST /api/leads`, `/{id}`, `/activities`, `/status`, `/follow-up`, `/owner`, `GET /api/leads/owners` | `leads`, `lead_activities` | No configurable SLA; status history is prose in `lead_activities.summary`, not structured; **0 lead rows in the live database** |
| **HR** | Employee master, offices/geofence attendance, manual attendance, leave, OD, approvals, salary structures, payroll, HR reports and dashboard | `/api/hr/*` (≈45 routes), `/api/employees` | `employees`, `hr_*` (18 tables) | No licence/certificate expiry; HR figures are intentionally permission-scoped |
| **Reports** | 27 catalog reports including stock, sales, invoices, leads, purchases, receivables, ageing, GST, trial balance and 12 HR reports; CSV/XLSX/PDF export; reconciliation checks | `GET /api/reports`, `GET /api/reports/{key}`, `GET /api/reports/{key}/export` | read-only across all | No scheduled delivery; no dashboard-card export |
| **Alerts / Telegram** | Audit events queue a Telegram message after commit; login notices optional | none (config only) | none | No delivery status, retry log or health check; only "configured / not configured" can be known |
| **Backups / restore test** | CLI `backup_restore_test.py` dumps, restores into a scratch DB, compares row counts, Alembic revision and report checks | none | none | Result is printed, never stored; no schedule, no "last backup" record |
| **Users, roles, audit** | Seeded and custom roles, permission edits take effect immediately, forced password change, lockout, audit viewer and export | `/api/auth/*`, `/api/users`, `/api/roles`, `/api/audit` | `users`, `roles`, `audit_log` | No user preferences (saved filters, pinned cards, default dashboard) |
| **Dashboard** | 8 aggregate figures, expiring list, open POs, module register | `GET /api/dashboard`, `GET /api/modules` | read-only across all | No period, no cache, no charts, no drill-downs, no trends, no health detail (section 3) |

---

## 2. What data actually exists

Read-only counts on the configured database, 1 November 2026:

| Table | Rows | Table | Rows |
|---|---:|---|---:|
| products | 3 | invoices | 1 |
| warehouses | 4 | invoice_lines | 1 |
| batches | 3 | credit_notes / debit_notes | 0 / 0 |
| stock_movements | 6 | payments | 1 |
| purchase_orders | 4 | leads / lead_activities | 0 / 0 |
| purchase_order_lines | 5 | audit_log | 318 |
| goods_receipts | 4 | print_logs | 7 |
| suppliers | 2 | users / roles / employees | 6 / 8 / 5 |
| distributors | 4 | sales_orders / lines | 2 / 2 |
| approval_requests | 4 | Alembic revision | `e4f5a6b7c8d9` (head) |

Consequences:

- The dashboard will legitimately show small numbers and many empty states. Empty is not a defect.
- Cards that depend on leads, notes, multiple months of sales or HR activity will show **"No data yet"** until the business records them.
- The live database is demo-scale, so performance at production volume is measured on synthetic data only (section 3.4).

---

## 3. The existing `/api/dashboard`

### 3.1 What it returns

Called read-only today (live database):

```json
{
  "as_of": "2026-11-01",
  "stock": {"units_on_hand": "35002.000", "batches_in_stock": 3,
            "expiring_count": 0, "expiring": []},
  "purchase_orders": {"open_count": 0, "open": []},
  "active_products": 3, "orders_ready": 0,
  "approvals_waiting": 1,
  "leads": {"overdue": 0, "due_today": 0},
  "warehouse_count": 4
}
```

Function: `app/api/dashboard.py:103`. Every figure is a SQL aggregate over the whole table, never a filtered 200-row page — this closed audit item D-05 and is enforced by `tests/test_dashboard.py:38`.

### 3.2 Is it permission-aware?

**Yes, on the server** (`app/api/dashboard.py:110-132`):

| Section | Gate |
|---|---|
| stock, purchase orders, warehouse count | `stock:read` |
| active products | `product:read` |
| orders ready | `sales:read` |
| approvals waiting | `approval:read`; a non-admin without HR manager rights counts only the HR requests they raised, matching the queue |
| leads | `lead:read` |

A section the caller may not see is `null`, never `0`, so "none" and "not allowed" are distinguishable. Tested at `tests/test_dashboard.py:20`.

### 3.3 What it does **not** do

- No `range` / period parameter; every figure is as-of today.
- No `generated_at`/updated-at, no cache, no per-section timing.
- No drill-down endpoints. The two lists are capped at 6 (`LIST_LIMIT`, `dashboard.py:26`) and only the expiry list tells the user "Showing 6 of N"; the open-PO list silently shows 6 of N.
- Expired batches are folded into "expiring within 90 days"; there is no expired count, no `<30` / `<90` split, no value.
- No money, no ageing, no sales/purchases, no activity feed, no health detail.
- No trends; no source of historical batches/products (see 4.3).

### 3.4 Speed

| Scenario | Where | Result |
|---|---|---|
| Live database (3 products, 2.5k audit rows) | configured DB, read-only | **70.7 ms** |
| Synthetic 12,000 batches, 6,000 leads, 2,500 POs with lines | `herbanova_bcs_test`, transaction rolled back | **63.9 ms** total; stock 38.8 ms, POs 14.0 ms, leads 6.7 ms |

Measured on the development machine with a warm local PostgreSQL, one session per call. The target of <500 ms is met with room to spare, but the current queries scan `batches` and `leads` without indexes on `on_hand`, `expiry` or follow-up dates; Phase 2 should add indexes only if the measured cost at real volume justifies a migration.

---

## 4. Metric-by-metric computability

### 4.1 The eight KPI tiles

| Tile | Computable today | Source | Trend line | Gap |
|---|---|---|---|---|
| Units on hand | **Yes** | `SUM(batches.on_hand) WHERE on_hand > 0` | **Yes** — cumulative `stock_movements.qty_delta` | — |
| Batches in stock | **Yes** | `COUNT(batches) WHERE on_hand > 0` | **No** — batch has no `created_at` | Needs 7/30/90 history; show "No history yet" |
| Expiring ≤90 days **and expired** | **PARTIAL** — total is counted, expired split is not | `batches.expiry`, `on_hand > 0` | **Yes** — expiry is a fixed date, so any as-of date is exact | New query for expired / ≤30 / ≤90; batch value needs cost |
| POs awaiting goods | **Yes** | `purchase_orders.status IN ('open','partially_received')` | **PARTIAL** — reconstructable from PO `created_at` and GRN `received_at` | — |
| Orders ready to dispatch | **Yes** | `sales_orders.status = 'approved'` | **PARTIAL** — no `approved_at`; derive from approval decisions or audit | — |
| Approvals waiting | **Yes** | `approval_requests.status = 'pending'` | **Yes** — `requested_at` / `decided_at` | — |
| Overdue follow-ups | **Yes** | open leads with `next_follow_up < today` | **No** — only the current date is stored; activity text is unstructured | Show "No history yet" |
| Active products | **Yes** | `products.status = 'active'` | **No** — no `created_at`; creations exist in `audit_log` but status changes are not reconstructable | Show "No history yet" |

### 4.2 Needs-attention strip

| Rule | Computable today | Source | Gap |
|---|---|---|---|
| Expired batches with stock | **Yes** (new query) | `batches.expiry < today AND on_hand > 0` | Value needs cost |
| Warehouse over capacity | **No** | — | No capacity field; **needs capture** |
| Receivables over 60 days | **Yes** | `ledger.ageing_rows()` buckets 61-90 + 90+ | — |
| Approvals needing the Administrator | **Yes** | `approval_requests.reasons` contains `credit_limit`, or post-billing edits | JSON filtering |
| Low stock vs reorder level | **Yes** (`0024`) | `products.reorder_level` compared with `SUM(batches.on_hand)`; products with no level are excluded, not treated as zero | — |

### 4.3 Charts and lists

| Card | Computable today | Source / method | Gap |
|---|---|---|---|
| Sales vs purchases trend | **Yes** | Sales: issued invoices by `invoice_date`; purchases: GRN lines × PO unit cost by `received_at` | Purchase value is at order cost, not invoiced cost — label it |
| Receivables ageing | **Yes** | `ledger.ageing_rows()` — same function the Ageing report uses | Already reconciled by `reports._source_receivables` |
| Stock by warehouse + capacity share | **PARTIAL** | Units and batches per warehouse | No capacity; show units now, capacity as gap |
| Expiry watch with filters and detail | **Yes** (filters/counts new) | `batches` + product + warehouse | Batch value needs cost; suggested action is a rule, not stored |
| Open POs with % received | **Yes** | ordered vs received per PO line | — |
| Approvals with approve/reject | **Yes** | `POST /api/approvals/{id}/decide`; permission-checked, reason required, audit-logged (`approvals.py:147`) | — |
| Sales by category | **Yes** (`0024`) | `invoice_lines` taxable value joined to `products.category`, uncategorised named separately | Margin by category still needs cost per category |
| Top products with change | **Yes** | `invoice_lines` grouped by product for current and previous period | — |
| Recent activity | **Yes** | `audit_log` (`audit.py:67`) | Visible only with `audit:read` (Administrator). Others get "Not permitted" |
| System health | **PARTIAL** | Modules: `module_register`; Alembic: `alembic_version` | Last backup and restore result are **not stored**; alert channel can only show configured/not configured |

### 4.4 Global search, period selector, command palette, theme

| Item | Status |
|---|---|
| Global search | **MISSING** as one endpoint; per-list `q` search exists for products, leads, approvals, POs, suppliers and others, but no cross-entity search |
| Period selector 7/30/90 | **MISSING** — new query parameter and period filters |
| Command palette | **MISSING** — UI only |
| Theme toggle / dark theme | **MISSING** — single palette in `static/css/styles.css:5`; no dark variables |
| Drill-down lists | **PARTIAL** — list screens exist, but stock and batches have no expiry/warehouse filter with totals; no filtered "approved orders" deep link |

---

## 5. Gap list

### Data-capture gaps (a card cannot be correct until these exist)

| ID | Gap | Blocks | Proposed capture |
|---|---|---|---|
| GAP-D01 | No product category or brand | Sales by category, margin by category | **Resolved in `0024`**: `products.category`, `products.brand`, the product form, search and the catalog facets. Margin by category still needs cost per category |
| GAP-D02 | No reorder level / minimum stock | Low-stock alert, stock cover alert | **Resolved in `0024`**: nullable `products.reorder_level`, low-stock attention, stock-report flag. Stock cover (days) still needs a consumption rate |
| GAP-D03 | No warehouse capacity | Warehouse over-capacity alert, capacity share | Add `warehouses.capacity_units` — **resolved in v2** (nullable units + note, migration `0009`) |
| GAP-D04 | No batch cost or valuation policy | Expiry value, stock value by warehouse, accurate gross margin | Add batch cost at receipt (from GRN) or a documented valuation policy |
| GAP-D05 | No expected delivery date on POs | Supplier on-time delivery, PO ageing vs promise, "due this week" | **Sales-order part resolved in `0024`**: `sales_orders.expected_delivery_date`, approval stamp and promise lateness. Purchase-order part still open: add `purchase_orders.expected_date` |
| GAP-D06 | No due date on invoices | Ageing by due date (today it is by invoice date) | **Closed 3 Nov 2026:** `invoices.due_date` and `payment_terms_days` frozen at issue (migration `0025`); ageing reports the due-date split |
| GAP-D07 | No input tax on purchases | GST output vs input summary | Purchase invoice capture with tax |
| GAP-D08 | No structured lead status history | Lead funnel by status over time, conversion SLA | Write status changes to a structured column/table (activity text is not queryable) |
| GAP-D09 | No persisted backup/restore result | "Last backup" and "Restore test" health cards | Write a run record (time, revision, outcome) from `backup_restore_test.py` |
| GAP-D10 | No batch QC status / licence expiry | QC and compliance cards | New fields/tables |
| GAP-D11 | No cash/bank opening balances | Cash position | **Closed 3 Nov 2026:** `opening_balances` and `ledger_accounts` (migration `0027`); the balance sheet shows each cash and bank head's closing balance and a total |

### Engineering gaps (data exists; work is code)

| ID | Gap | Where |
|---|---|---|
| GAP-E01 | Dashboard has no period, generated-at, cache or drill-downs | `dashboard.py` |
| GAP-E02 | No expired / ≤30 / ≤90 split and no total for the open-PO list ("Showing X of Y") | `dashboard.py`, `app.js:398` |
| GAP-E03 | No health detail: Alembic head comparison, backup status, alert channel | `/api/health` only returns status/env (`main.py:75`) |
| GAP-E04 | No cross-entity search endpoint | new endpoint |
| GAP-E05 | No chart rendering at all | SPA is table-driven |
| GAP-E06 | No theme switch and no dark palette | `styles.css` |
| GAP-E07 | Dashboard lists capped at 6 but counts are exact — fine, but only one list admits the cap | UI |
| GAP-E08 | No reconciliation test tying dashboard ageing and sales to the report service | `tests/` |
| GAP-E09 | No trend history for batches/products/follow-ups | data model (GAP-D01..D09 partly) |

---

## 6. Design-reference delta

| Reference | Today | Proposed handling |
|---|---|---|
| Inter font | Fraunces (titles) + Public Sans (text) | Adopt Inter for UI text; keep the serif only where it already appears outside Overview, unless the owner prefers a full switch |
| Accent `#1F6B4A` | `--moss #2a6a49` | Retune the accent variable; no functional change |
| Dark green sidebar, off-white page, white cards, amber/red for warnings only | Already the pattern | Keep; formalise warning semantics (amber = soon, red = breached) and never use colour alone |
| Buttons ≥44 px | 38 px default, 32 px compact | Dashboard controls 44 px; keep compact buttons inside dense tables |
| Light and dark themes | Light only | Add `data-theme` variables, persisted, following `prefers-color-scheme` |
| Mobile responsive | Grid shell; tables scroll | Dashboard stacks to one column; cards remain keyboard reachable |

These are visual changes to the Overview and shared tokens; no route, permission or data behaviour changes.

---

## 7. What Phase 2 can build with **no schema change**

Every card below can be correct today; where data is absent the card shows **"No data yet"** and names the gap (GAP-Dxx) instead of inventing a figure.

- 8 KPI tiles with exact server counts, plus trend lines only for units on hand, expiry buckets, approvals and (partially) POs and orders.
- Needs-attention rules for expired batches, receivables >60 days and Administrator approvals. Capacity and reorder rules are shown as "Not configured" with the gap ID. *(Reorder became live in `0024`; capacity became configurable in v2 migration `0009`.)*
- Sales vs purchases trend, receivables ageing (reconciled to the report), stock by warehouse (units; capacity share marked unavailable), expiry watch with filters and drill-down, open POs with % received, approvals with decide actions, top products with period comparison, recent activity (permission-gated), module health and Alembic head.
- "Sales by category" renders as "No data yet — no product category is captured (GAP-D01)". *(Superseded by `0024`: the panel groups issued invoices by the captured category.)*
- Global search: a new read-only endpoint that reuses existing indexed columns.
- Period selector, generated-at timestamp, 30–60 s in-process cache.
- Theme toggle, skeletons, empty/error states, keyboard navigation, command palette for navigation and "New sales order".

## 8. Recommended Phase 2 shape (for approval, no code yet)

1. One aggregated endpoint `GET /api/dashboard?range=7|30|90` returning permission-scoped sections, `generated_at`, `as_of`, and per-section `null` for not-permitted. Cache the composed payload per (role, permissions, range) for 45 seconds; invalidate by time only.
2. Small drill-down endpoints: expiry buckets, approvals needing admin, low-stock (returns "not configured"), activity. Lists return `total` and cap at 10 with "Showing X of Y".
3. Reuse `ledger.ageing_rows()`, `ledger.gst_register()` and invoice lines so dashboard figures equal report figures; add a reconciliation test that compares them.
4. Frontend: extend the existing SPA — inline SVG charts, no new runtime dependency; Overview becomes the landing view it already is (`#/dash`).
5. Tests: seeded correctness, permission per role, reconciliation, empty and not-configured states.

**No migration is required for Phase 2.** Migrations appear only in Phase 3 for approved capture fields (category, reorder level, capacity, expected date, due date), each with a rollback. *(Delivered: capacity in `0009`; category, brand, reorder level, sales-order expected date and approval stamp in `0024`; invoice due date, payment terms and the financial-year close in `0025`.)*

---

# Dashboard v2 audit — date filter, approvals, capacity, MoM/YoY and geography

**Date:** 1 November 2026
**Scope:** the additional requirements A–I. Read-only audit of what the system already holds and what must be captured. No schema, code or data was changed while auditing.
**Evidence markers:** **VERIFIED** (read in code), **MEASURED** (queried read-only), **PARTIAL**, **MISSING**.

## A1. Date filtering on `/api/dashboard`

| Item | Today | Gap |
|---|---|---|
| Period parameter | `GET /api/dashboard?range=7|30|90` only; the window always ends today | **GAP-V01** `from_date`/`to_date` are not accepted |
| Per-card periods | Sales vs purchases, top products and corrections take `start,end`; ageing, stock, expiry, POs, approvals, activity are as-of today | Cards must be labelled either "selected range" or "as of today" |
| Validation | Range is a fixed choice | **GAP-V02** no check that from ≤ to, or that a date is not in the future |
| Persistence | `hb.dashRange` in localStorage | **GAP-V03** selected dates are not kept between dashboards |
| Reconciliation | `tests/test_dashboard_phase2.py` compares ageing and sales with the report service | Extend to every date-based card |

## A2. Approvals workflow and roles

**VERIFIED.** `approval_requests` stores request type, record, reasons, requester, timestamps, decision and reason. `POST /api/approvals/{id}/decide` enforces: `approval:read` to open, administrator-only credit-limit and post-billing decisions, a different person from the requester (and order creator), one decision per request, reason of at least 3 characters, and an audit entry.

**MEASURED today:** 1 pending request in the live database (demo seed), 4 sales orders.

| Requirement | Today | Gap |
|---|---|---|
| Row shows type, reference, requester, amount/days, who may decide, age | Type, reference, requester, subject and amount are returned; age and "who may decide" are not explicit fields | **GAP-V04** add `age_days` and `deciders` (role words) to `ApprovalOut` |
| Inline Approve/Reject | The Overview opens the shared approval drawer, which posts the decision | **GAP-V05** rows have no inline decision controls; rejection reason is captured in the drawer |
| Decision refreshes badge, KPI and attention strip | The drawer reload then refetches the dashboard | **GAP-V05** no targeted refresh before the next reload |
| Request types with no handler | `hr_overtime`, `hr_salary_revision`, `hr_reimbursement` have no decision handler | Correctly report `can_decide: false`; shown as "No decision handler yet" |

## A3. Sales and purchase aggregation

| Metric | Source today | Quality |
|---|---|---|
| Sales | Issued `invoices.grand_total` by `invoice_date` (includes GST) | **VERIFIED**; matches the Sales Invoice Register |
| Purchases | GRN lines × `purchase_order_lines.unit_cost` by receipt day | **PARTIAL** — valued at order cost, not invoiced cost; a line with no cost counts as zero |
| Returns | Issued `credit_notes.grand_total` by `note_date` | **VERIFIED** |
| Receipts | `payments.kind='receipt'` by `paid_on` | **VERIFIED** |
| Gross margin | Invoice revenue minus cost | **MISSING** — invoice lines and batches carry no cost (GAP-D04), so margin cannot be computed without inventing it |
| Orders | `sales_orders` by `created_at` | **VERIFIED** |
| New leads / customers | `leads.created_at`; `distributors` has **no** `created_at` | **PARTIAL** — new customers per period cannot be measured |

**Built in v2.** `GET /api/dashboard/compare?mode=full_month|mtd&month=YYYY-MM` reuses these sources unchanged: sales from issued invoices, purchases from the goods-receipt register at order cost, returns from issued credit notes, receipts from receipt payments, orders from `sales_orders.created_at` and new leads from `leads.created_at`, each in the explicit current, previous and same-month-last-year windows. Gross margin and new customers stay "No data yet" (GAP-D04, GAP-V16). Every card and table is filtered by the caller's permissions before it is returned, so a viewer never receives a figure it may not read. The date columns these queries group and filter on (`sales_orders.created_at`, `credit_notes.note_date`, `goods_receipts.received_at`, `leads.created_at`) are indexed by migration `0010`, which has a downgrade.

## A4. Warehouse capacity

**MISSING.** `warehouses` has only `id` and `name`; no capacity, unit or location. `batches.on_hand` gives live units per warehouse, so used/percentage needs only a capacity column. No transfer endpoint exists (`StockMovement.movement_type='transfer'` is modelled but no route posts it). Receiving (`POST /api/purchase-orders/{id}/receive`) and dispatch (`POST /api/sales-orders/{id}/dispatch`) do not check capacity.

Gaps: **GAP-V06** capacity column; **GAP-V07** capacity checks at receipt and dispatch; **GAP-V08** utilisation report; **GAP-V09** transfer check (blocked by no transfer feature).

**Built in v2.** Nullable `warehouses.capacity_units` and `capacity_note` (migration `0009`, with a downgrade). A goods receipt that would exceed capacity is refused unless an Administrator sends the audited override; dispatch is not capped but reports the source warehouse's position. `warehouse_utilisation` is a read-only report from the same query as the dashboard. GAP-V09 stays open because there is still no transfer endpoint.

## A5. Returns and credit note data

**VERIFIED.** `credit_notes` links invoice, sales order, distributor, reason, `return_warehouse_id`, money totals; `credit_note_lines` carries product, qty and tax. A return restores stock to the same batches when a warehouse is given. There is no structured return-reason code — `reason` is free text (up to 300 characters). **GAP-V10** return reasons cannot be grouped reliably; the geography section will show the free-text reason as recorded, without invented categories.

## A6. Location data

| Place | Fields today | Usable for geography? |
|---|---|---|
| Invoice (frozen snapshot) | `buyer_state_code`, buyer name, address lines 1–2; **no city, district or pincode** | State yes; district/city no |
| Distributor master | `state_code`, `territory` (free text), billing/shipping address (free text) | State yes; territory inconsistent |
| Warehouse | name only | No |
| GST | invoice `place_of_supply_state_code`, `place_of_supply_kind`, seller state | State yes |

**MEASURED today:** 2 invoices, both state `07` (Delhi); 0 invoices without a state code; 6 distributors all with a state code; territories read `EAST DELHI`, `NARELA`, `SAHIBABAD`, `GURGAON`, `North`, `West` — a mix of city and region names, so they cannot be treated as one vocabulary.

Gaps: **GAP-V11** no district/city/pincode capture; **GAP-V12** territory is free text with no standard list; **GAP-V13** warehouse has no city/state; **GAP-V14** sales orders do not record a dispatch region separate from the buyer state.

**Built in v2.** `GET /api/dashboard/geo` groups issued invoices by `coalesce(buyer_state_code, distributor.state_code)` for the selected window and returns sales, taxable value, invoice count, customer count, tax split, returns and the 37-code map list. Invoices with no state at all stay in a "Location not recorded" row so the window total still reconciles. Tax and return fields are omitted without `tax:read` / `accounts:read`. The UI renders a fixed tile grid (labelled "State tile map — not a geographic outline"), ranked top/bottom lists and a sortable table with CSV export. District, city and pincode remain "No data yet" (GAP-V11); territory is not used as a key (GAP-V12); no user is territory-scoped (D-14).

## A7. New gap register

| ID | Gap | Blocks | Proposed handling in v2 |
|---|---|---|---|
| GAP-V01 | No `from_date`/`to_date` | Date filter | Add parameters with defaults and validation |
| GAP-V02 | No date validation | Date filter | 422 when from > to or a date is in the future |
| GAP-V03 | Dates not remembered | Date filter | Keep in `state` and localStorage |
| GAP-V04 | Approval age / deciders / amount not explicit | Approvals card | Derive age from `requested_at`; name the role rule in words |
| GAP-V05 | No inline approval actions | Approvals card | Inline Approve/Reject with reason; refresh the card after a decision |
| GAP-V06 | No warehouse capacity | Capacity, alerts | Add `warehouses.capacity_units` (migration + rollback) |
| GAP-V07 | No capacity check at receipt/dispatch | Capacity | Warn with an explicit administrator override (audit-logged); dispatch checks the source warehouse's stock only |
| GAP-V08 | No utilisation report | Reports | Add a read-only report built from the same query as the dashboard |
| GAP-V09 | No transfer endpoint | Transfers | Not built; no warning can be attached to a feature that does not exist |
| GAP-V10 | Free-text return reason | Returns by region | Show as recorded; no invented categories |
| GAP-V11 | No district/city/pincode | Geography drill-down | Show state only; "Location not recorded" row |
| GAP-V12 | Territory not standardised | Regional reports | Not used as a geographic key; state code is |
| GAP-V13 | Warehouse has no location | Warehouse map | Not shown geographically |
| GAP-V14 | No dispatch region | Dispatch geography | Dispatch region = buyer state, labelled as such |
| GAP-V15 | No cost on stock or invoice lines | Gross margin, MoM margin card | Show "No data yet — cost is not captured (GAP-D04)" |
| GAP-V16 | No `distributors.created_at` | New customers | Show "No data yet" for new customers; active customers is computable |
| GAP-V17 | No last-year data | YoY | Show "No data yet" until the comparison year exists |

## A8. What v2 can build honestly, in the requested order

1. **Date filter** — backend parameters, presets, validation, persistence; every date card states its range.
2. **Approvals** — inline decisions, age, decider rule, immediate refresh.
3. **Sales vs purchases** — pills, line keys, area fill, hover readout, reconciled to the invoice register.
4. **Warehouse capacity** — migration with rollback, editor for Administrators, dashboard bars, receipt warning with override, utilisation report.
5. **MoM/YoY** — new page and endpoint, full-month and month-to-date, prior-year comparisons where data exists, "No data yet" where it does not.
6. **Geography** — state-level table and ranked lists from invoice snapshots, a locally drawn state tile map (no external map service), "Location not recorded" row; district/city drill-down is not possible without GAP-V11.

No figure in v2 will be invented. Missing inputs are returned as `null` with a gap code and rendered as "No data yet".

---

# Part B — Scheduled email reports and Accounts reporting (audit before build)

**Audited:** 1 November 2026, branch `feature/scheduled-reports`, Alembic head `0010_comparison_indexes`.
**Rule:** the same rule as Part A — a figure is either read from a table or shown as "No data yet" with a gap code. Nothing is estimated, typed in by hand or copied from the sample email.

## B1. Email, scheduler and alerting — what exists

| Area | State today | Evidence |
|---|---|---|
| Outbound email | **MISSING** | `grep -ri "smtp\|sendmail\|email" app` finds no mail client. No library in the dependency list. |
| Email settings | **MISSING** | `app/core/config.py` has Telegram only. There is no `SMTP_*` setting, no sender address and no test recipient. |
| Scheduler / background jobs | **MISSING** | The app starts no background task; `app/main.py` registers routers and static files only. No cron, Celery, APScheduler or worker process. |
| Stored schedules | **MISSING** | No schedule, recipient or delivery table. |
| Delivery log / retries | **MISSING** | Nothing records an attempted send, its recipients, size, outcome or error. |
| Report generation | **VERIFIED** | `app/services/reports.py` (`CATALOG`, `build()`), `exports.to_csv/to_xlsx`, `reports_pdf.to_pdf`. Tables carry columns, totals, reconciliation checks and limitations. |
| Dashboard aggregates | **VERIFIED** | `app/api/dashboard.py` provides `_period_stats`, `_sales_by_day`, `_purchases_by_day`, `_top_products`, `_geo_states`, `_customers`, `ageing_rows`, `trial_balance`. |
| Audit trail | **VERIFIED** | `audit()` writes `audit_logs` and strips secret keys; every existing module uses it. |
| Alert channel | **PARTIAL** | `services/telegram.py` queues after commit and never raises. It has **no retry, no delivery record and no per-message history**; it is not an email channel. |
| Holidays | **VERIFIED** | `hr_holidays` stores a date, name, branch and location — reusable for "first working day" and holiday shifting. |
| Image/PDF generation | **VERIFIED** | Pillow 12.3 and ReportLab (including `renderPM`) import successfully, so PNG charts can be drawn without a new dependency. |
| User email address | **PARTIAL** | `User` has **no** email column. `Employee.email` exists (120 chars, optional). Recipients therefore need their own verified list; a login is not an email address. |
| Recipient consent / unsubscribe | **MISSING** | No token, no opt-out record. |

**Consequence.** Scheduled email needs four additive tables, a worker process and a mail client. It cannot reuse a scheduler or a mailer because neither exists. It can and must reuse the report, export, PDF, ledger, audit and holiday services so the numbers are the same numbers.

## B2. What a report pack can honestly contain

**Status 2 November 2026.** This section records the Phase 1 position. Expense, cost and payroll capture now exist (migrations `0020`–`0022`), so the pack statements below are updated to the current behaviour; the audit history above is unchanged.

| Pack | Sources that exist | What must be shown as a gap |
|---|---|---|
| Daily Business Summary | Orders, invoices, receipts, GRNs, leads, approvals, expiry, audit — all dated; gross profit from captured issue cost | Gross profit is labelled partial when invoices are not costed (GAP-P01); expenses before `tracked_from` are shown as a partial total marked Partial (GAP-P02); payroll counts approved months, allocating a month the window cuts short by working days, and names a month with no approved payroll (GAP-P03) |
| Weekly Management Report | The above plus ageing, top products, credit use, PO ageing; expenses and payroll by month | The same three P&L gaps; net profit is withheld until all three are complete |
| Monthly MD Report | Month windows from `_compare_windows`, 12-month trend, top 5 products/customers/states, Accounts block | The same three P&L gaps, plus new customers (GAP-V16) |
| Alerts digest | Expiry, capacity, approvals, overdue follow-ups, >60-day receivables | Nothing new |
| Accounts pack | Revenue, collections, outstanding/ageing with due-date split, payables outstanding, output GST, input GST and net GST payable, filed-return reconciliation, TDS/statutory dues, trial balance, credit exposure, P&L with reconciliation and notes; a balance-sheet block (total assets, liabilities/equity/earnings, difference) added in Batch 5 | The balance sheet is read from `balance_sheet.balance_sheet()` at the pack's end date, so it cannot drift from the screen; the cash note says sitting balances are on the balance sheet. Vouchers and bank reconciliation have screens and APIs but no pack tile. P&L gaps appear only when an input is missing. A closed financial year and invoice due dates are enforced since Batch 3; input GST, reconciliation and statutory dues since Batch 4; vouchers, openings, the balance sheet and bank reconciliation since Batch 5. |
| Custom pack | Any existing report in the catalog, by key | Whichever report already declares |

`tests/test_email_reports.py` compares the pack's sales, purchases, returns, receipts and outstanding against the same dashboard service and the same ledger function, so a pack cannot drift from the screens.

## B3. Accounts module — what exists and what does not

| Capability | State | Detail |
|---|---|---|
| Money in and out | **VERIFIED** | `payments` (receipt/payment, cash/bank/upi/cheque/neft/other, date, party, optional invoice/PO). Append-only. |
| Receivables | **VERIFIED** | Derived from issued invoices minus notes and receipts (`ledger.receivable_rows`). |
| Ageing | **VERIFIED** | Four buckets as of a selected date (`ledger.ageing_rows`), plus a due-date split (overdue, due within 7 days, later, no due date) read from the invoice snapshot. |
| Payables | **PARTIAL** | Derived from received goods at order cost minus payments. **No invoice, no due date, no supplier terms.** |
| Party ledgers | **VERIFIED** | `distributor_ledger`, `supplier_ledger`. |
| Credit/debit notes | **VERIFIED** | Issued notes with reason, tax and stock return. |
| GST outward | **VERIFIED** | Invoice and note tax split; `gst_register`. |
| GST inward / net payable | **CLOSED 3 Nov 2026** | `purchase_invoices` and `statutory_challans` (migration `0026`) plus `app/services/gst.py`. Input tax is captured head by head on a supplier bill; eligible input is netted, blocked input is shown separately, expense ITC is a memo. With no posted bill the figure reads **No data yet**, not zero. |
| Trial balance | **PARTIAL** | Derived double-entry summary from documents (`ledger.trial_balance`), balanced check included. It stays document-derived: openings, expense and TDS accounts are not in it. The balance sheet (GAP-A10, closed) is the statement that merges openings and vouchers with it. |
| Chart of accounts / vouchers / journal | **CLOSED 3 Nov 2026** | `ledger_accounts`, `opening_balances`, `vouchers` and `voucher_lines` (migration `0027`) plus `app/services/journal.py`. Nine heads are seeded; a voucher is drafted, refused while unbalanced, posted, reversed by a mirror dated today and listed in the day book. |
| Day book / cash book / bank book | **CLOSED 3 Nov 2026 (day book); cash and bank books remain document views** | The day book lists posted and reversed vouchers with debit and credit totals. A cash or bank book is the payments view by mode; its closing balance is the balance sheet's cash and bank total. |
| Expenses / expense heads | **CLOSED 2 Nov 2026** | `expenses`, `expense_heads` and `expense_settings` (migration `0020`); approval threshold with an on/off switch, non-creditable GST flag, audited reversal and receipts. |
| P&L / balance sheet | **CLOSED 3 Nov 2026** | `profit_loss.statement()` builds revenue, returns, COGS, expenses, payroll, gross profit and net profit, with GAP-P01/P02/P03 when an input is missing; partial inputs are marked **Partial** with a fix link, and a month a window cuts short is allocated by working days (D-36). `balance_sheet.balance_sheet()` (migration `0027`) merges the latest captured opening, posted vouchers and the document trial balance by head, with section totals, retained earnings, cash and bank, and a named difference. It warns that its document layer has no expense, payroll or stock-cost postings rather than guessing them; closing stock is still not valued in it. |
| Financial-year / period locks | **CLOSED 3 Nov 2026** | `financial_year_closes` (migration `0025`) and `app/services/periods.py`. The Administrator closes a completed year with a reason; every dated document (dispatch and invoice, receipts and payments, credit/debit notes, invoice cancellation, expenses, cost corrections, free-sample notes) is refused with HTTP 423 until the year is reopened. Accounting-month locks remain the narrower gate for cost corrections and expenses. |
| TDS / statutory dues | **CLOSED 3 Nov 2026** | Vendor TDS is captured on the supplier bill (`tds_section`, `tds_rate`, `tds_amount`); payroll statutory heads come only from approved or later periods; challans record deposits. Outstanding is cumulative withheld minus deposited, per head. |
| Bank reconciliation / unposted vouchers | **CLOSED 3 Nov 2026** | `bank_statements` and `bank_statement_lines` (migration `0027`) plus `app/services/bank_rec.py`. A statement is captured per bank head and period; a line is matched only to a payment or voucher line whose amount and direction agree; the proof shows adjusted book, adjusted statement and the remaining difference. Vouchers carry a draft/posted/reversed state, so "unposted" is the draft list. |
| Invoice due dates | **CLOSED 3 Nov 2026** | `invoices.payment_terms_days` and `invoices.due_date`, frozen from the distributor's terms at issue (migration `0025`); NULL when no terms were captured. Ageing reports the due-date split. Supplier payables still estimate their due date from current terms. |
| Discounts | **PARTIAL** | Invoice/discount fields exist on documents and the discount-slab master; a period discount total is computable only from stored fields, not from free text. |
| Post-billing changes | **VERIFIED** | Audit log records issued-invoice amendments and approval decisions. |
| Accounts permission | **CLOSED 2 Nov 2026** | The additive `accounts:reports` key gates the dashboard, P&L report and Accounts email block; `accounts:read` is unchanged for the statements and the sales desk. `expense:read`/`expense:write` gate the Expenses screen and API. |

**Measured today (development database):** 2 issued invoices, ₹ 70,00,000.00 outstanding (both inside 0–30 days), 0 payments recorded in the current month, 0 credit notes in October, trial balance balanced. The sample email's figures (₹ 96.2 L sales, 31.8% margin, ₹ 14.6 L net profit) are **sample data only** and must not appear in a real email.

## B4. New gap register

| ID | Gap | Blocks | Handling |
|---|---|---|---|
| GAP-E01 | No SMTP client or settings | Any email | Add `app/services/mailer.py`; secrets from environment only |
| GAP-E02 | No scheduler or worker | Scheduled runs | DB-backed worker with unique run key; separate process |
| GAP-E03 | No schedule/recipient/delivery tables | Admin screens, log | Migration `0011` with rollback |
| GAP-E04 | No email address on `User` | Test recipient | Recipient list; test mode also reads `Employee.email` of active Administrators |
| GAP-E05 | No tokenised public dashboard link | Expiring secure link | "View full dashboard" points at the login page; link expiry not built |
| GAP-E06 | No attachment encryption | Oversized packs | Hard 9.5 MB budget, drop detail files, never email a password |
| GAP-E07 | No unsubscribe endpoint | Extras opt-out | Token stored per recipient; mandatory groups are removed only by an Administrator |
| GAP-E08 | No per-message Telegram history | Failure alert | Worker writes the failure to the delivery log **and** sends one Telegram alert |
| GAP-E09 | No email delivery provider/reputation handling | Rate limits | Send in batches of 20 with a pause; provider-specific APIs not integrated |
| GAP-A01 | No expense table or heads | Expenses, P&L, net profit | **Closed 2 Nov 2026:** migration `0020` adds expenses, heads, settings, approval and reversal; the P&L reads approved entries by head |
| GAP-A02 | No cost on stock or invoice lines | COGS, gross profit, margin | **Closed 2 Nov 2026:** migration `0021` captures cost on the movement ledger; COGS is proved per invoice, partial/NULL when cost is unknown |
| GAP-A03 | No closed-period lock | Locked-period enforcement | **Closed 3 Nov 2026:** a completed financial year can be closed (migration `0025`); dated documents are refused with HTTP 423 until an Administrator reopens the year with a reason. Accounting-month locks (migration `0022`) remain the narrower gate |
| GAP-A04 | No invoice due date | Payables/receivables due this week | **Closed 3 Nov 2026:** terms and due date are frozen on the invoice at issue; ageing shows overdue, due within 7 days, later and no due date |
| GAP-A05 | No purchase-side tax | Input GST, net GST, GSTR-3B | **Closed 3 Nov 2026:** a supplier bill records tax head by head (migration `0026`); net payable = output less eligible input, blocked input shown separately |
| GAP-A06 | No GSTR-1/3B filings | Reconciliation | **Closed 3 Nov 2026:** filed figures are captured per month and form; each line is compared with the register and a difference is shown |
| GAP-A07 | No TDS records | TDS/statutory dues | **Closed 3 Nov 2026:** vendor TDS on the bill, approved payroll heads, challan deposits and the outstanding remainder per head |
| GAP-A08 | No vouchers/journal/day book posting | Day book, unposted vouchers | **Closed 3 Nov 2026:** `vouchers`/`voucher_lines` (migration `0027`); draft, posted and reversed state; a day book with a balanced check |
| GAP-A09 | No bank statement/reconciliation | Bank reconciliation status | **Closed 3 Nov 2026:** a statement per bank head and period, line matching to payments or voucher lines, and a proof that names the difference |
| GAP-A10 | No opening balances | Cash/bank balance, balance sheet | **Closed 3 Nov 2026:** `ledger_accounts` and `opening_balances` (migration `0027`); the balance sheet merges openings, vouchers and documents and names what the document layer does not cover |
| GAP-A11 | No balance-sheet asset/liability capture | Balance sheet | **Closed 3 Nov 2026 by GAP-A10:** asset and liability heads can be added and their balances captured as openings or posted as vouchers. There is no depreciation or stock-valuation automation. |
| GAP-A12 | No MD login role | MD dashboard access | MD receives email; the Administrator can grant `accounts:reports` to a role |

## B5. Build order for Part B

1. Audit and decisions (this document and `DASHBOARD_DECISIONS.md`).
2. Migration `0011` — schedules, recipients, schedule recipients, delivery log; downgrade.
3. Schedule maths (timezone, slots, monthly rules, holidays) with unit tests.
4. Accounts service with honest gaps, then the Accounts dashboard and Overview section.
5. Pack builder, HTML/text renderer, PNG charts, PDF/XLSX attachments.
6. Mailer with test mode, worker with retries and duplicate protection.
7. Administrator screens (scheduled reports, recipients, delivery log) and API.
8. Reconciliation, permission, failure and schedule tests; docs and samples.

Anything blocked by a missing input stays a gap; the email and the screen say so rather than showing a zero.
