# Dashboard audit — Phase 1

**Date:** 1 November 2026
**Scope:** read-only audit of what the system does today, what the Overview can honestly show, and what must be captured before a card can show a number.
**Status:** audit complete; no code, schema or data was changed. Phase 2 starts only after owner approval.

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
| **Products** | Create, list/search, edit; SKU unique; HSN/UQC; MRP; status active/inactive | `GET/POST /api/products`, `PATCH /api/products/{id}`, `GET /api/products/options` | `products` | No category, brand or reorder level; no created/updated timestamp; no batch-level cost |
| **Stock and batches** | Warehouses, batches with expiry/owner, append-only movement ledger, exact on-hand, FEFO allocation at dispatch, receipt via GRN | `GET/POST /api/warehouses`, `GET /api/inventory/batches`, `GET /api/inventory/movements` | `warehouses`, `batches`, `stock_movements` | No warehouse capacity; no batch cost or valuation; no batch `created_at`; no write-off/shrinkage reason; no QC status; no recall view |
| **Purchase orders** | Create, list, receive in parts (GRN), cancel; duplicate-delivery guard; receipt posts stock once | `GET/POST /api/purchase-orders`, `GET /{id}`, `POST /{id}/receive`, `POST /{id}/cancel` | `purchase_orders`, `purchase_order_lines`, `goods_receipts`, `goods_receipt_lines` | No expected delivery date; no purchase invoice or input tax; no supplier price history view |
| **Sales orders** | Draft → pending approval → approved → dispatched / rejected / cancelled; credit and stock checked at submit and dispatch; warehouse chosen at dispatch | `GET/POST /api/sales-orders`, `GET /{id}`, `GET /{id}/tax-preview`, `POST /{id}/submit`, `/cancel`, `/dispatch` | `sales_orders`, `sales_order_lines`, `batches`, `stock_movements`, `approval_requests`, `invoices` | No requested delivery date; no approval timestamp on the order itself; no pipeline view |
| **Approvals** | Central queue; sales-order, post-billing and HR categories; segregation of duties; reason required on decision; audit-logged | `GET /api/approvals`, `POST /api/approvals/{id}/decide`, `POST /api/approvals/post-billing/{invoice_id}`, supplier bank changes | `approval_requests` | No SLA/ageing policy; no notification to approvers (Telegram only mirrors audit events) |
| **Billing** | Tax invoices at dispatch, immutable; credit/debit notes; cancellation with reason; post-billing amendment via approval; secure PDF, print log, verification | `GET/POST` under `/api/invoices`, `/api/credit-notes`, `/api/debit-notes`, `/api/printing` | `invoices`, `invoice_lines`, `credit_notes`, `debit_notes`, `document_sequences`, `print_logs` | Invoice has no due date (ageing is by invoice date); no input tax; no e-invoice/e-way integration (MOD-15 conditional) |
| **Accounts** | Receipts and payments, outstanding, party ledgers, ageing, outward GST register, trial balance; all derived from documents | `GET/POST /api/payments`, `/outstanding`, `/ledger/...`, `/ageing`, `/gst-register`, `/trial-balance` | `payments`, plus documents above | No purchase-side GST; no opening cash/bank balance or bank reconciliation, so "cash position" is not reliable |
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
| Low stock vs reorder level | **No** | — | No reorder level; **needs capture** |

### 4.3 Charts and lists

| Card | Computable today | Source / method | Gap |
|---|---|---|---|
| Sales vs purchases trend | **Yes** | Sales: issued invoices by `invoice_date`; purchases: GRN lines × PO unit cost by `received_at` | Purchase value is at order cost, not invoiced cost — label it |
| Receivables ageing | **Yes** | `ledger.ageing_rows()` — same function the Ageing report uses | Already reconciled by `reports._source_receivables` |
| Stock by warehouse + capacity share | **PARTIAL** | Units and batches per warehouse | No capacity; show units now, capacity as gap |
| Expiry watch with filters and detail | **Yes** (filters/counts new) | `batches` + product + warehouse | Batch value needs cost; suggested action is a rule, not stored |
| Open POs with % received | **Yes** | ordered vs received per PO line | — |
| Approvals with approve/reject | **Yes** | `POST /api/approvals/{id}/decide`; permission-checked, reason required, audit-logged (`approvals.py:147`) | — |
| Sales by category (donut) | **No** | — | No product category; **needs capture** |
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
| GAP-D01 | No product category or brand | Sales by category, margin by category | Add `products.category` (migration + backfill UI) |
| GAP-D02 | No reorder level / minimum stock | Low-stock alert, stock cover alert | Add `products.reorder_level` |
| GAP-D03 | No warehouse capacity | Warehouse over-capacity alert, capacity share | Add `warehouses.capacity_units` — **resolved in v2** (nullable units + note, migration `0009`) |
| GAP-D04 | No batch cost or valuation policy | Expiry value, stock value by warehouse, accurate gross margin | Add batch cost at receipt (from GRN) or a documented valuation policy |
| GAP-D05 | No expected delivery date on POs | Supplier on-time delivery, PO ageing vs promise, "due this week" | Add `purchase_orders.expected_date` |
| GAP-D06 | No due date on invoices | Ageing by due date (today it is by invoice date) | Add `invoices.due_date`, default from distributor terms |
| GAP-D07 | No input tax on purchases | GST output vs input summary | Purchase invoice capture with tax |
| GAP-D08 | No structured lead status history | Lead funnel by status over time, conversion SLA | Write status changes to a structured column/table (activity text is not queryable) |
| GAP-D09 | No persisted backup/restore result | "Last backup" and "Restore test" health cards | Write a run record (time, revision, outcome) from `backup_restore_test.py` |
| GAP-D10 | No batch QC status / licence expiry | QC and compliance cards | New fields/tables |
| GAP-D11 | No cash/bank opening balances | Cash position | Bank reconciliation or opening-balance capture |

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
- Needs-attention rules for expired batches, receivables >60 days and Administrator approvals. Capacity and reorder rules are shown as "Not configured" with the gap ID.
- Sales vs purchases trend, receivables ageing (reconciled to the report), stock by warehouse (units; capacity share marked unavailable), expiry watch with filters and drill-down, open POs with % received, approvals with decide actions, top products with period comparison, recent activity (permission-gated), module health and Alembic head.
- "Sales by category" renders as "No data yet — no product category is captured (GAP-D01)".
- Global search: a new read-only endpoint that reuses existing indexed columns.
- Period selector, generated-at timestamp, 30–60 s in-process cache.
- Theme toggle, skeletons, empty/error states, keyboard navigation, command palette for navigation and "New sales order".

## 8. Recommended Phase 2 shape (for approval, no code yet)

1. One aggregated endpoint `GET /api/dashboard?range=7|30|90` returning permission-scoped sections, `generated_at`, `as_of`, and per-section `null` for not-permitted. Cache the composed payload per (role, permissions, range) for 45 seconds; invalidate by time only.
2. Small drill-down endpoints: expiry buckets, approvals needing admin, low-stock (returns "not configured"), activity. Lists return `total` and cap at 10 with "Showing X of Y".
3. Reuse `ledger.ageing_rows()`, `ledger.gst_register()` and invoice lines so dashboard figures equal report figures; add a reconciliation test that compares them.
4. Frontend: extend the existing SPA — inline SVG charts, no new runtime dependency; Overview becomes the landing view it already is (`#/dash`).
5. Tests: seeded correctness, permission per role, reconciliation, empty and not-configured states.

**No migration is required for Phase 2.** Migrations appear only in Phase 3 for approved capture fields (category, reorder level, capacity, expected date, due date), each with a rollback.

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
