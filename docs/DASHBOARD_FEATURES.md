# Overview Dashboard — Metric Register

**Project:** Herbanova Business Control
**Phase:** 2 — Overview dashboard, extended by Dashboard v2 (November 2026)
**Date:** 1 November 2026
**Source of truth:** `app/api/dashboard.py`, `static/js/app.js`, `static/index.html`, `static/css/styles.css`
**Rule:** every figure on the screen is a SQL aggregate over the whole database. Nothing is computed by filtering a capped browser list, and no figure is invented. When the input is not stored, the screen says **No data yet**, names the gap (GAP-Dxx / GAP-Vxx) and the section is listed in §8.

> **v2 in one line.** The Overview now has an explicit date window, inline approvals, a reconciled sales-vs-purchases card and warehouse capacity; two new pages add MoM/YoY comparison and state-level geography. The six v2 steps and their tests are in §11; what remains open is in §12. Sections §1–§10 describe the Phase 2 register and are updated where v2 changed them.

---

## 1. Endpoints

| Endpoint | Purpose | Permission | Notes |
|---|---|---|---|
| `GET /api/dashboard?from_date=&to_date=` | One aggregated payload for the whole page | signed in; each section additionally gated (see §7) | Defaults to the current month. `from_date > to_date` or a future `to_date` → **422**. Legacy `range=7\|30\|90` still accepted. |
| `GET /api/dashboard/expiry?bucket=expired\|lt30\|lt90\|all&page&page_size` | Paged expiry drill-down | `stock:read` | `page_size` 1..100 (default 25); rows sorted by expiry, then batch id. |
| `GET /api/dashboard/search?q=` | Global search (palette) | signed in; each group gated | Minimum 2 characters; returns at most 5 rows per group. |
| `GET /api/dashboard/activity?limit=1..50` | Recent audit entries | `audit:read` | Used by the activity feed and the palette. |
| `GET /api/dashboard/compare?mode=full_month\|mtd&month=YYYY-MM` | MoM/YoY comparison, 12-month trend, run rate and breakdowns | `sales:read`; each card/column additionally gated | `mode` and `month` validated → **422**. Defaults: `full_month`, current month. |
| `GET /api/dashboard/geo?from_date=&to_date=` | State-level sales, returns and GST split | `sales:read`; tax fields need `tax:read`, returns need `accounts:read` | Same date validation as `/api/dashboard`; defaults to the current month. |

The payload defaults every Phase-2 section to `null` and fills only what the caller may see. A section the role cannot read is **`null`, never `0`**, so the browser can distinguish "none" from "not permitted".

**Legacy keys are unchanged** (`stock`, `purchase_orders`, `active_products`, `orders_ready`, `approvals_waiting`, `leads`, `warehouse_count`) so any existing consumer keeps working.

---

## 2. Refresh, cache and performance

| Item | Rule |
|---|---|
| Cache | In-process, key = `(user id, sorted permissions, range or explicit window, administrator flag)`, TTL **45 s** (`DASHBOARD_TTL_SECONDS`). Comparison adds `mode` and `month`, geography adds the explicit window. A different role or window never reuses another caller's payload. Approving or rejecting a request retires the cached dashboard. |
| Cache scope | Only when `APP_ENV=production` **and** the database name does not end in `_test`. Tests always read fresh data. |
| Updated line | `generated_at` is UTC; the page renders it in the browser's local time ("updated 01 Nov 2026, 12:31 am"). Cached payloads keep the time they were built. |
| Cost | One request per range change; all figures are indexed aggregates. Measured on the development database: **7–8 ms** median for the full payload. |
| Business day | Purchase receipts are grouped by the **Asia/Kolkata** calendar day (`_business_day`), not the database server's day. |
| Trend sampling | Stock-history series are reduced to at most **12 points** (`TREND_POINTS`); a short range shows every day. |

---

## 3. Header and controls

| Control | Behaviour | Source |
|---|---|---|
| Greeting and date | "Good morning/afternoon/evening, {username}" plus the long local date (en-IN) | `greeting()`, `renderDash()` |
| Search button | Opens the palette; shows the platform shortcut (`Ctrl/⌘ K`) | `openPalette()` |
| Period presets | 7D, 30D, 90D, This month, Last month, This FY, plus explicit From/To dates; the window survives reload (`hb.dashFrom`/`hb.dashTo`/`hb.dashPreset`); the pressed preset is `aria-pressed`; invalid dates show the server's rule in place | `setDashPreset()`, `applyDashDates()` |
| MoM & YoY | Replaces the old top-bar "New sales order" action and opens the comparison page; "New sales order" remains on the Sales screen and in the command palette | `#compare` |
| New sales order | Only rendered when the role holds `sales:write`; opens the existing sales-order form | `dashNewSo` |
| Updated line | "As at {date} · {n}-day period, {from} to {to} · updated {time}" | `renderDash()` |
| Theme | Light/dark toggle in the sidebar, stored in `hb.theme`; defaults to the OS preference | `applyTheme()`, `toggleTheme()` |
| Skeleton | Eight KPI placeholders and two chart placeholders while the first payload loads | `#dashSkeleton` |
| Error | A retained last-good payload is shown; on first-load failure an error card offers **Try again** | `renderDash()` |

---

## 4. KPI tiles

Every tile is a link to the records behind it. Value, note and trend are counted by the server.

| # | Key | Metric | Definition | Source | Trend |
|---|---|---|---|---|---|
| 1 | `units_on_hand` | Units on hand | `SUM(batches.on_hand)` where `on_hand > 0`, all warehouses | `batches` | Daily units reconstructed by subtracting later stock movements from the current balance (`_stock_history`), max 12 points |
| 2 | `batches_in_stock` | Batches in stock | `COUNT(batches)` where `on_hand > 0` | `batches` | Daily batch count, same reconstruction |
| 3 | `expiring` | Expiring ≤ 90 days | Batches with `on_hand > 0`, expiry not null and `expiry <= today + 90`; note splits "already expired" and "within 30 days" | `batches` | Daily count within the same 90-day window |
| 4 | `po_awaiting` | POs awaiting goods | `COUNT(purchase_orders)` with status `open` or `partially_received` | `purchase_orders` | **No history**: PO status has no stored timeline → text note, no line |
| 5 | `orders_ready` | Orders ready to dispatch | `COUNT(sales_orders)` with status `approved` | `sales_orders` | **No history**: approval time is not stored → text note |
| 6 | `approvals_waiting` | Approvals waiting | Pending approvals **visible to this user** (HR self-scoping applies) | `approval_requests` | **No history**: no decision timestamp → text note |
| 7 | `followups_overdue` | Follow-ups overdue | Leads not `won`/`lost` with `next_follow_up < today`; note gives due-today | `leads` | **No history**: only the current follow-up date is stored → text note |
| 8 | `active_products` | Active products | `COUNT(products)` with status `active` | `products` | **No history**: no creation timestamp → text note |

Trends are shown as inline SVG sparklines only when at least two finite points exist. A tile without history states why instead of drawing a fabricated line.

---

## 5. Sections

### 5.1 Needs attention

| Rule | Threshold | Severity | Link |
|---|---|---|---|
| Batches past expiry | `expiry < today`, `on_hand > 0` | red when > 0 | Inventory |
| Warehouse above 80% capacity | `used_units / capacity_units` from the capacity service; amber above 80%, red above 95% / over | amber/red when > 0; "Capacity is not set for any warehouse" when none is configured | Inventory → Warehouses |
| Receivables over 60 days | ageing buckets `61-90` + `90+` | amber when > 0 | Accounts |
| Approvals needing an Administrator | pending credit-limit or post-billing requests visible to the caller | amber when > 0 | Approvals |
| Low stock vs reorder level | not stored (GAP-D02) | "No data" | — |

The header states the exact number of rows shown and, when present, how many are data gaps ("3 items · 2 data gaps"). Healthy rules (count 0) are omitted.

### 5.2 Sales and purchases

| Field | Definition |
|---|---|
| Sales | `SUM(invoices.grand_total)` for **issued** invoices, grouped by `invoice_date`; includes GST |
| Purchases | `SUM(goods_receipt_lines.qty × purchase_order_lines.unit_cost)` joined through the receipt and its PO line; a line without a price counts as zero; grouped by the **IST** day of `received_at` |
| Previous period | The equally long window ending the day before `from` |
| Change | `(current − previous) / previous × 100`, one decimal; **null** when the previous total is 0, rendered "no prior period to compare" |
| Permission mask | With only `sales:read` the purchase values are removed **server-side** (and vice versa); the legend hides the missing series |
| Interaction | Pointer hover and ←/→ keyboard moves a focus ring across the days; the tooltip and `aria-label` read the date and both totals |

The window is stated under the heading, and both totals and deltas are repeated below the chart.

### 5.3 Receivables ageing

Buckets `0-30`, `31-60`, `61-90`, `90+` come from `ledger.ageing_rows(db, today)` — the **same function** the Receivables Ageing report uses. Outstanding = invoice value minus receipts/credits already applied, per the ledger rules. The section states the as-of date, invoice count and total, and that the figures match the report. Bars use amber for 61–90 and red for 90+; the amount is always printed as text, so colour is never the only signal.

### 5.4 Stock to watch (expiry)

| Element | Rule |
|---|---|
| Filters | All / Expired / ≤ 30 days / 31–90 days; disjoint buckets whose counts add to the total |
| Rows | Product, batch number, warehouse, units on hand, chip with days left ("Expired 2 days ago", "Expires today", "14 days left") |
| Count line | "N batches expiring within …"; when a list is capped: "Showing X of Y." |
| Detail | Opens a drawer with batch, SKU, warehouse, on-hand, expiry, days left and a suggested action: expired → write off or seek clearance; ≤ 30 days → dispatch first (FEFO); otherwise plan FEFO dispatch |
| Value | Not shown: stock carries no batch cost (GAP-D04) — stated in the panel footer |

### 5.5 Stock by warehouse

Warehouses from `warehouses` (including empty ones), with batches and units in stock and the unit share of total stock. A non-zero tiny share shows **<1%** rather than rounding to 0%. When `capacity_units` is configured, each row shows used, free and % of capacity with a bar (green, amber above 80%, red above 95%); a warehouse without capacity says "Capacity not set" (GAP-D03 remains for that row). Administrators can set capacity and the unit word inline; the editor requires `stock:write` and is audited.

### 5.6 Waiting to be received (open POs)

Open or part-received purchase orders (max 6 rows) with supplier, value, received/ordered units and **% received** by quantity, plus the number of receipts so far. The exact open count comes from a separate aggregate, not from the capped list.

### 5.7 Approvals waiting

Up to 6 pending approvals visible to the caller, using the same visibility rule as the approvals queue. **Review** opens the existing approvals drawer, which shows the reasons, the server's decision rules and only the actions the server will accept. A requester cannot decide their own request; the drawer says so. Decisions are made by the existing `POST /api/approvals/{id}/decide`, which re-checks role, permission, self-approval and reason on reject, and writes an audit row. The dashboard adds no new write path.

### 5.8 Top products

Up to 6 products by taxable value (before GST) on issued invoices in the period, with units, revenue, the same product's previous-period revenue and the % change (or "new this period" when there was none). Ordering is deterministic: revenue descending, then product id.

### 5.9 Sales by category

Not available: `products` has no category or brand (GAP-D01). The panel shows **No data yet**, names the gap and explains that grouping would require inventing a category — it does not reuse the product name as a pseudo-category.

### 5.10 Recent activity

Latest 8 audit entries (id, time, actor, action, record, changed fields) from `audit_logs`, with the exact total ("Latest 8 of 323 entries."). Requires `audit:read`; the panel links to the full Audit trail.

### 5.11 System health

| Card | Source | States |
|---|---|---|
| Modules | Server module register (`module_register.totals()`) | "17 of 17 modules working" + expandable list of every module |
| Schema migration | `alembic_version` compared with `ScriptDirectory.get_current_head()` | "At head" / "Behind head" with both revisions |
| Backup and restore | Not persisted (GAP-D09) | "Not recorded" with the instruction to run `python backup_restore_test.py` and keep its output |
| Alert channel | `telegram.enabled()` | "Configured" / "Not configured"; delivery is not probed and the card says so |

Health is deliberately factual: a missing backup result is shown as missing, not as a green tick.

### 5.12 Phase 3 insight cards

Five additional cards appear below the Phase 2 panels. Each is `null` without the
permission that its matching list endpoint requires, and a card with no data says so.

| Card | What it shows | Source | Gate |
|---|---|---|---|
| **Pipeline** | Sales orders by every status (count and value) with the order-to-dispatch average; leads by every status | `sales_orders`, `leads`; dispatch time is `dispatched_at − created_at` for dispatched orders (approval wait included, stated in the note) | `sales:read` for the sales column, `lead:read` for leads |
| **Customers and credit** | Top customers by issued-invoice value in the period; all-date outstanding per customer with a reconciled total; credit in use per distributor (limit, exposure, available, % used, "over limit" above 100%) | `invoices`, `ledger.receivable_rows`, `sales_orders` exposure statuses, `distributors.credit_limit` | `sales:read` for top/credit, `accounts:read` for outstanding |
| **PO ageing** | Open and part-received POs bucketed 0–7, 8–14, 15–30, 31+ days since the order date, with count and ordered value; how many have no goods received and how many are part received | `purchase_orders`, `purchase_order_lines`, goods receipts | `stock:read` |
| **Corrections after billing** | Issued credit- and debit-note counts and values in the period, the latest notes with invoice and reason, and post-billing amendment requests with status | `credit_notes`, `debit_notes`, `approval_requests` (`invoice_post_billing`) | `sales:read` |
| **HR today** | Active headcount, attendance marked and not marked, pending leave and on-duty applications, attendance by status | `employees`, `hr_attendance`, `hr_leave_applications`, `hr_od_requests` | `hr:read` |

Every card states the period or date it covers. Counts are exact; the note lists
are capped at six with the true total in the card. PO lateness against a promise
is not shown because no expected-delivery date is stored (GAP-D05).

---

## 6. Global search and keyboard

| Behaviour | Detail |
|---|---|
| Open | Search button, or **Ctrl/⌘ K** from anywhere in the shell |
| Query | Minimum 2 characters, 180 ms debounce; results grouped by Products, Customers (distributors), Sales orders, Invoices, Purchase orders, Suppliers, Leads |
| Permission scoping | A group is omitted unless the caller holds the matching read permission; the server builds it, the browser cannot request a hidden group |
| Navigation | ↑ ↓ move the active option, **Enter** opens it, **Esc** closes; focus returns to the page and `aria-expanded`/`aria-selected` track state |
| Landing | Selecting a result navigates to its module and, where the module supports it, opens the same record drawer the list would open |
| Capped groups | At most 5 rows per group, labelled with the group name; the note states how many results and sections were found |

---

## 7. Permissions by section

| Section | Required permission | Behaviour without it |
|---|---|---|
| Stock KPIs, expiry, warehouses, open POs | `stock:read` | Sections `null`; tiles absent |
| Sales KPIs, top products, category, orders ready | `sales:read` | Sections/tiles absent |
| Sales series on the chart | `sales:read` | Sales values removed server-side |
| Purchase series on the chart | `stock:read` | Purchase values removed server-side |
| Receivables ageing and the >60-day attention rule | `accounts:read` | Section absent; rule omitted |
| Approvals tile, list and attention rule | `approval:read` | Sections absent; HR requests further limited to the caller's own |
| Follow-ups tile | `lead:read` | Tile absent |
| Active products tile | `product:read` | Tile absent |
| Recent activity | `audit:read` | Section absent |
| Pipeline sales column, top customers, credit in use, corrections | `sales:read` | Card/column absent |
| Pipeline leads column | `lead:read` | Column absent |
| Customers outstanding column | `accounts:read` | Column absent; other customer columns still shown |
| PO ageing | `stock:read` | Card absent |
| HR today | `hr:read` | Card absent |
| New sales order button | `sales:write` | Button not rendered |
| MoM/YoY page and `/api/dashboard/compare` | `sales:read` | Page and nav entry hidden; endpoint 403 |
| Comparison cards | each card's own read permission | Card omitted from the payload, not zero |
| Geography page and `/api/dashboard/geo` | `sales:read` | Page hidden; endpoint 403 |
| Geography tax split | `tax:read` | Column and GST panel replaced by a "needs tax:read" gap |
| Geography returns | `accounts:read` | Returns column and panel replaced by a "needs accounts:read" gap |
| Warehouse capacity editor | `stock:write` | Fields read-only |
| Capacity override on receipt | Administrator role | Override refused server-side (403) even if the flag is sent |
| Health, search, greeting | signed in | Visible to every signed-in user; search groups still gated |

All gates are enforced in `app/api/dashboard.py` and are covered by `tests/test_dashboard_phase2.py` (null sections per role, chart masking, search scoping, activity permission, HR self-scoping).

---

## 8. Data gaps shown on the dashboard

| Gap | Missing input | What the screen does |
|---|---|---|
| GAP-D01 | Product category or brand | "Sales by category" → No data yet |
| GAP-D02 | Reorder level | "Low stock against reorder level" → No data |
| GAP-D03 | Warehouse capacity | **Resolved for configured warehouses in v2** (migration `0009`); a warehouse with no capacity still says "Capacity not set" |
| GAP-D04 | Batch cost / valuation policy | Expiry rows omit value; footer names the gap; comparison gross-margin card says "No data yet" |
| GAP-D09 | Persisted backup/restore result | Health card "Not recorded" |
| GAP-V09 | No stock transfer endpoint | No transfer capacity warning is claimed |
| GAP-V10 | Free-text return reason | Geography shows the reason as recorded; no categories |
| GAP-V11 | No district / city / pincode | Geography stops at state and says so |
| GAP-V12 | Territory is free text | Not used as a geographic key |
| GAP-V16 | No `distributors.created_at` | Comparison "new customers" card says "No data yet" |
| GAP-V17 | No prior-year data yet | MoM/YoY prior-year figures read zero with "No data yet", never invented |

`GAP-D05..D08` (PO expected date, invoice due date, input tax, structured lead-status history) do not appear as dashboard figures in this phase; they are recorded in `docs/DASHBOARD_AUDIT.md`.

---

## 9. Reconciliation and verification

| Check | Evidence |
|---|---|
| Receivables ageing equals the report | `tests/test_dashboard_phase2.py::test_receivables_ageing_matches_the_report` calls `ledger.ageing_rows` and the dashboard together |
| Expiry buckets are disjoint and add up | `test_expiry_buckets_are_disjoint_and_add_up` |
| Stock history is backdated from movements | `test_stock_history_is_reconstructed_from_movements` |
| Open-PO progress uses ordered vs received quantities | `test_open_po_progress_matches_receipts` |
| Counts are exact beyond any list cap | `tests/test_dashboard.py` seeds more than 200 rows and asserts the true totals |
| Permissions | `test_sections_are_null_without_permission`, `test_chart_masks_a_series_the_role_cannot_read`, `test_search_respects_permissions`, `test_activity_requires_audit_read`, `test_hr_requester_sees_only_their_own_requests` |
| Periods | `test_period_bounds_and_previous_window` |
| Health | `test_health_reports_the_module_register` |
| Phase 3 pipeline and order-to-dispatch | `tests/test_dashboard_phase3.py::test_pipeline_counts_match_the_database` |
| Phase 3 customers, credit and outstanding | `test_customer_cards_reconcile_with_receivables_and_credit` (outstanding total equals the ageing report total) |
| Phase 3 PO ageing | `test_po_ageing_adds_up_to_the_open_orders` |
| Phase 3 corrections | `test_corrections_reconcile_with_issued_notes` |
| Phase 3 HR today | `test_hr_today_reconciles_with_attendance_and_requests` |
| Phase 3 permission scoping and shapes | `test_insights_are_present_and_scoped_by_permission`, `test_insight_card_shapes_are_stable` |

**Browser verification (1 November 2026):** signed in as the Administrator against the development database at `http://127.0.0.1:8000/ui/`. Confirmed: greeting/date/updated line; 8 KPI tiles with values from the database; attention list with two named gaps; chart totals and hover tooltip; ageing total "₹ 70,00,000.00" in Indian grouping with the report-matching note; expiry filter counts and empty state; warehouse shares; open-PO empty state; approval review drawer showing the server's self-approval restriction; top products; category "No data yet (GAP-D01)"; "Latest 8 of 323 entries."; health cards ("15 of 15" at that time; the register now has 17 counted modules after MOD-17 Accounts reporting and MOD-18 Scheduled e-mail were added, so the card reads "17 of 17"), schema at head, backup not recorded, alerts configured); range 7D switched the window and reloaded; palette opened with Ctrl+K, searched, highlighted with arrows and closed with Esc; dark theme toggled the tokens; Inventory, Approvals, Reports, Sales orders, HR and Settings all still rendered; **no console messages or errors**. The Phase 3 cards were then checked in the same session: pipeline (2 sales orders, 0.5-day average to dispatch across 1 dispatched order), customers and credit (outstanding ₹ 70,00,000.00 reconciling with the ageing panel; 6,250% credit use shown as "over limit"), PO ageing (0 open), corrections (0 notes, 0 post-billing requests) and HR today (5 active, 0 marked, 5 not marked); Customers, Sales orders, Purchases, HR and Overview screens still rendered; dark theme applied to the new cards; no console errors. A duplicate function name (`renderCustomers`) initially hid the customers card and was renamed to `renderInsightCustomers`.

**Limitation:** the in-app browser had no visible surface, so the check was DOM- and interaction-based (computed styles, text, element state) rather than pixel screenshots. The responsive breakpoints (1180/980/820/560 px) were authored and inspected in CSS. On 1 November 2026 Phase 3 additionally captured and reviewed the Overview, HR and main module screens in headless Chrome at 1400×1000 and 390×844, in light and dark themes (`docs/VERIFICATION_REPORT.md` §10); those screenshots were not committed because they show demo business records.

---

## 10. Deliberately not built

**Delivered in Phase 3** (all from stored data, no new schema): pipeline by status and order-to-dispatch time, top customers, receivables by customer with credit usage, returns and credit/debit notes, PO ageing and pending-receipt counts, post-billing amendment view, HR attendance and pending leave/on-duty, and FEFO suggestions in the expiry detail. The cards are described in §5.12.

| Not built | Reason | What would unblock it |
|---|---|---|
| Sales by category / margin by category | GAP-D01 | `products.category` (migration + backfill) |
| Low-stock and stock-cover alerts | GAP-D02 | `products.reorder_level` |
| Expiry value and stock value | GAP-D04 | Batch cost at receipt or a valuation policy |
| PO due-date and supplier on-time | GAP-D05 | `purchase_orders.expected_date` |
| Ageing by due date | GAP-D06 | `invoices.due_date` |
| GST input/output summary | GAP-D07 | Purchase tax capture |
| Lead funnel over time | GAP-D08 | Structured status history |
| Last backup / restore test card | GAP-D09 | A persisted run record from `backup_restore_test.py` |
| Trend lines for POs, orders, approvals, follow-ups, products | No stored status timeline | Event/status history tables |

No sample or placeholder data is used anywhere in production code; the gaps are surfaced as gaps.

---

# Dashboard v2 — what was built

**Branch:** `feature/dashboard-v2` (one commit per step, baseline commit first)
**Decisions and reasoning:** `docs/DASHBOARD_DECISIONS.md` (D-01 … D-20)
**Data-safety:** additive only. Two nullable/index-only migrations, both with `downgrade()`; no row, table, permission or existing report was changed.

The repository has no separate Feature Inventory or Requirements Traceability Matrix (`docs/DASHBOARD_AUDIT.md` §0); this register is the feature inventory and the audit/decision files carry the traceability.

## 11. The six v2 steps

### 11.1 Explicit date window (Step 1)

| Item | Behaviour |
|---|---|
| Controls | 7D, 30D, 90D, This month, Last month, This FY, plus explicit From/To date inputs |
| Default | First day of the current month to today (D-02) |
| Validation | `from_date > to_date` or a future `to_date` → 422; mirrored in the UI (D-03) |
| Persistence | `hb.dashFrom`, `hb.dashTo`, `hb.dashPreset`; restored only when valid and `from ≤ to` |
| Scope labels | Range-driven cards state the window; "as of today" snapshots (stock, capacity, open POs) say so (D-04); ageing uses the selected end date (D-05) |
| Legacy callers | `range=7\|30\|90` still accepted and translated to the same window |
| Tests | `tests/test_dashboard_v2.py` — window bounds, defaults, validation, persistence of server figures |

The top-bar "New sales order" button was replaced by **MoM & YoY**; the sales-order action remains on the Sales screen and in the command palette.

### 11.2 Approvals decided inline (Step 2)

Rows on the Overview show **Approve** and **Reject**. Approve posts the existing `POST /api/approvals/{id}/decide` with the visible default reason "Approved from the dashboard"; Reject reveals an inline reason field requiring at least 3 characters. After a decision the card, KPI and sidebar badge reload from one `loadAll()`, and the server retires the cached dashboard so a stale count cannot return. Self-approval, role rules and the audit row stay in the existing endpoint (D-06). The response names *who may decide* in role words and the age in whole `Asia/Kolkata` days (D-07).

### 11.3 Sales vs purchases card (Step 3)

Sales (issued invoices, including GST) and purchases (received goods at PO cost, excluding tax) are drawn as a solid green line with area fill and a dashed amber line. Each legend entry is a pill that shows or hides its series; the last visible series cannot be hidden. Hover and ←/→ move a focus ring with a readout of the day and both totals. The permission mask removes a series the role cannot read, server-side. Totals reconcile with the Sales Invoice Register and the Goods Receipt Register over the same dates; both are tested independently (D-08).

### 11.4 Warehouse capacity (Step 4)

- Migration `0009_warehouse_capacity` adds nullable `warehouses.capacity_units` and `capacity_note`; `downgrade()` drops them (D-09).
- The Overview warehouse panel shows used, free and % of capacity with a bar: green, amber above 80%, red above 95% / over. Unconfigured warehouses say "Capacity not set".
- The attention list gains "Warehouses above 80% capacity".
- The capacity editor requires `stock:write` and is audited.
- A goods receipt that would exceed capacity returns 409; an Administrator may resend with `allow_over_capacity=true`, audited as `warehouse.capacity_override` with before/after totals. Non-administrators get 403 (D-10).
- Dispatch is not capped (it only reduces stock) but reports the source warehouse's position.
- `warehouse_utilisation` is a read-only report (`stock:read`) built from the same service as the dashboard (D-11).
- Transfers do not exist, so no transfer check exists (GAP-V09).

### 11.5 MoM/YoY comparison (Step 5)

`GET /api/dashboard/compare` with one explicit mode (`full_month` or `mtd`) and a month. It returns:

- three labelled windows (current, previous month, same month last year) with the exact dates and states (`future`, `current`, `past`);
- eight cards (sales, purchases, orders, gross margin, receipts, returns, new leads, new customers), each with current, prior-month, prior-year, change and availability; unreadable cards are omitted from the payload; gross margin (GAP-D04) and new customers (GAP-V16) are explicit gaps;
- a 12-month trend with prior-year overlay, 3-month moving average, best/worst positive month and seasonality;
- a run-rate projection labelled **"Run-rate estimate (not a forecast)"** for the current month, "Complete month" for a past month, "Not started" for a future month (D-12);
- top-five products and distributors by taxable value before GST.

Migration `0010_comparison_indexes` adds four date indexes (`sales_orders.created_at`, `credit_notes.note_date`, `goods_receipts.received_at`, `leads.created_at`) with a matching downgrade. The page exports CSV with the compared dates in the header (D-16) and uses the existing 45-second cache (D-17).

### 11.6 Geography (Step 6)

`GET /api/dashboard/geo` groups issued invoices by `coalesce(buyer_state_code, distributor.state_code)` over the selected window. The invoice's frozen buyer state wins; the distributor master is only a fallback for rows without a snapshot. Invoices with neither code stay in an explicit **"Location not recorded"** row so the window total reconciles.

| Element | Behaviour |
|---|---|
| KPIs | Sales (incl. GST), invoices, states with a sale, then taxable value, returns or "location not recorded" depending on permission |
| Map | 37 fixed tiles from `app/core/india_states.py`, shaded by sales share, labelled **"State tile map — not a geographic outline"**; no external map service |
| Ranked lists | Top five and bottom five, where "bottom" ranks only states with a positive sale |
| Table | State, sales, share, invoices, customers, taxable (with `tax:read`), returns (with `accounts:read`); client-side sorting with `aria-sort` |
| Returns | Issued credit notes grouped by the invoice's buyer state; the free-text reason shown as recorded, capped at five with a true total (GAP-V10) |
| GST | Taxable, CGST, SGST, IGST, cess and tax as printed on issued invoices; labelled "not a statutory filing export" |
| Permissions | `sales:read` gates the page; tax/returns fields are omitted without their permissions and the page names the missing permission |
| Export | CSV of the rendered table, with the window and permission-appropriate columns |
| Gaps | District/city/pincode say "No data yet · GAP-V11"; territory is not used (GAP-V12); no territory-scoped user model (D-14) |

## 12. Verification

| Check | Result |
|---|---|
| Full suite | **107 passed** (last run 1 November 2026), isolated `herbanova_bcs_test` database |
| Geography tests | 4 tests: grouping/reconciliation/share; snapshot fallback + unrecorded row; window validation; returns/GST availability and viewer/payroll scoping |
| Comparison tests | 9 tests: window rules, validation, sales reconciliation with the invoice register, projection labels, 12-month trend, breakdowns, gaps/masking, zero bases |
| Capacity tests | migration, editor permissions, receipt block and administrator override, utilisation report reconciliation |
| Approvals tests | inline decision reuses the existing endpoint, self-approval refused, cache invalidated |
| Browser check (v2 pages) | Isolated verification database and a server on port 8001 (never the development database). As Administrator: map rendered 37 tiles with the Delhi tile active, KPI and table figures matched the seeded invoice, sorting changed `aria-sort`, tile selection highlighted the row, From > To showed the validation message, CSV download produced a file, and the console had no errors after sign-in. As Viewer: navigating to `#/geo` worked, taxable/returns columns disappeared, and the GST and returns panels named the missing permissions. Desktop screenshot at 1440 px: no horizontal overflow; mobile-width layout stacked cleanly. The throwaway database, server and helper files were deleted afterwards. |
| Limits of the check | The verification data was the marked demo seed (one issued invoice, one credit note), so top/bottom lists each show one state; multi-state ranking and prior-year trends are covered by the synthetic tests, not by that dataset. |

## 13. What I need you to review or decide

These are the choices that were safe to make autonomously but are business or policy decisions:

1. **Capacity thresholds.** Attention starts at 80%, red at 95% / over. Change the thresholds if your operation wants earlier warning.
2. **Capacity override.** Only an Administrator may override a capacity block, and every override is audited. Confirm this is the right authority level.
3. **Receipt vs purchase order.** Capacity is checked when goods arrive, because a PO has no warehouse. If you want a raise-time warning, a warehouse field must be added to POs.
4. **Approvals default reason.** Inline Approve records "Approved from the dashboard" unless the interface later grows a reason field. Confirm that wording is acceptable for audit.
5. **Date default.** The dashboard defaults to the current month; older bookmarks using `range=30` still work. Say if you prefer a rolling 30 days.
6. **Comparison gaps.** Gross margin stays "No data yet" until stock or invoice lines carry a cost; new customers stays "No data yet" until distributors have a creation timestamp. Adding those fields is a schema decision.
7. **Run rate wording.** The current-month projection is labelled an estimate, not a forecast. If you need a real forecast, that is a separate model with its own error statement.
8. **Geography depth.** The page stops at state because district/city/pincode are not captured. Adding them to invoices and distributors would unblock the drill-down (GAP-V11).
9. **Territory scoping.** There is no user-to-territory model, so every `sales:read` user sees every state. If regional users must be restricted, that needs a new scope field and a permission change — both out of scope here.
10. **Export format.** The two new tables export CSV, not PDF. The existing report catalog still produces PDFs for its own reports.
11. **Deployment.** Apply migrations `0009_warehouse_capacity` and `0010_comparison_indexes` before starting the new code. Neither rewrites data, and both have downgrades. Set capacity for each warehouse after deployment if you want fill bars.

**Skipped, with reasons:** stock transfers (no endpoint — GAP-V09); district/city/pincode (not captured — GAP-V11); gross margin (no cost — GAP-D04); new customers (no creation date — GAP-V16); territory-scoped geography (no scope model); PDF export of the new tables (would duplicate the document pipeline); prior-year comparison values (no data in the prior year yet — GAP-V17).

---

# Accounts dashboards and scheduled emails (November 2026)

This register covers the Accounts dashboard, its comparisons and the scheduled report emails. The repository has **no Feature Inventory and no Requirements Traceability Matrix**; this file, `docs/DASHBOARD_AUDIT.md` and `docs/DASHBOARD_DECISIONS.md` are the substitute, with each requirement mapped to the screen, endpoint, service and test that implements it.

## 14. Accounts endpoints and screens

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET /api/accounts/report?from_date&to_date&state` | `accounts:reports` | Window figures, 12-month trend, by-state table, receivables by distributor, gaps |
| `GET /api/accounts/report/compare?mode=full_month\|mtd&month=YYYY-MM` | `accounts:reports` | Current window vs previous month vs same month last year |
| `GET /api/accounts/outstanding`, `/ageing`, `/trial-balance`, `/gst-register`, `/payments`, ledgers | `accounts:read` | Existing statements, unchanged |
| `GET /api/reports/profit_and_loss?from&to` | `accounts:reports` | P&L statement, eight reconciliation checks (nine when net profit is available) and notes; export also needs `report:export` |
| `GET /api/reports/profit_and_loss/export?format=csv\|xlsx\|pdf&table=` | `accounts:reports` + `report:export` | The P&L statement, reconciliation table or checks as a file |
| `GET/POST/PATCH /api/expenses`, `/heads`, `/settings` | `expense:read` / `expense:write` | Expense entries, heads, approval, reversal, receipts and tracking settings |
| Overview `GET /api/dashboard` → `accounts` | `accounts:reports` | Receivables, payables, cash and bank, output GST, gross profit (partial when needed), expenses and net profit for the selected dates |

**Overview section.** Seven tiles (Receivables, Payables, Cash and bank (net), Output GST, Gross profit, Expenses, Net profit) under the KPI row. Gross profit is live and labelled "partial, X of Y invoices costed" when some invoices lack a captured cost. Net profit is live only when every invoice is costed, expenses are tracked for the whole window and payroll is complete; otherwise it shows its first gap code and opens the fix link. The section is absent for any role without `accounts:reports`.

**Accounting & Finance screen.** Above the existing statements when the role holds `accounts:reports`:

| Section | What it shows | Source |
|---|---|---|
| Accounts performance | Date window, region filter, eight KPI tiles, notes | `accounting.window()` |
| Profit and loss | Revenue and returns on taxable value; COGS from the stock ledger; approved expenses by head; payroll gross by month; gross profit labelled partial when needed; net profit only when complete | `profit_loss.statement()` via `accounting.report()` |
| Month on month and year on year | Both modes; current / previous / last year / change; no percentage against zero | `accounting.compare()` |
| Monthly trend | Revenue, collections, payments, net cash, output GST, returns for 12 months | `accounting.monthly_series()` |
| By state | Invoices, revenue, share, output GST, returns, outstanding; Filter button | `accounting.state_breakdown()` |
| Receivables by distributor | Outstanding per party, opening the append-only party ledger | `accounting.receivables_by_distributor()` + `/api/accounts/ledger/distributors/{id}` |
| Data gaps | GAP-A03 to GAP-A10 for what is still not captured, plus GAP-P01/P02/P03 when cost, expenses or payroll are incomplete, each with a fix link | `accounting.GAPS` + `profit_loss.statement()` |

## 15. Accounts metric definitions

| Metric | Definition | Window behaviour |
|---|---|---|
| Revenue (taxable) | Sum of `taxable_value` on issued invoices | Flow, exact window |
| Invoiced (with GST) | Sum of `grand_total` on issued invoices | Flow |
| Collections | Receipts dated in the window | Flow |
| Returns | Issued credit notes dated in the window | Flow |
| Output GST | `tax_total` printed on issued invoices | Flow; input tax not captured (GAP-A05) |
| Receivables outstanding | Issued invoices less receipts and credit/debit notes | Snapshot as at window end |
| Over 60 days | Ageing buckets 61-90 and 90+ | Snapshot |
| Payables outstanding | Goods received at order cost less payments | Snapshot; due dates estimated from current supplier terms |
| Payable within 7 days | Outstanding whose estimated due date falls in the next seven days | Snapshot |
| Cash and bank (net) | Receipts minus supplier payments | Flow; opening balances not captured (GAP-A10) |
| Cost of goods sold | Captured issue cost from `costing.invoice_cogs()`, less the cost of stock actually returned; a price-only credit note does not reduce it | Flow; an invoice with no attributed issue is not costed |
| Gross profit | Net revenue (revenue less returns plus debit notes) minus COGS | Always shown; labelled "partial, X of Y invoices costed" when any invoice is not costed |
| Expenses | Approved, non-reversed entries by head, dated in the window; non-creditable GST is added to cost, creditable GST is not | Flow; incomplete before `expense_settings.tracked_from` (GAP-P02) |
| Payroll cost | Gross salary of approved, processed or paid payroll periods for whole calendar months; employer contributions are not included | Whole months only, never prorated (GAP-P03) |
| Net profit | Gross profit minus expenses and payroll | Shown only when every invoice is costed, expenses cover the window and payroll is complete; otherwise the first gap is shown (GAP-P01/P02/P03) |
| Region filter | Narrows revenue, returns, output GST and distributor receipts by buyer state | Balances and trial balance stay company-wide |

## 16. Permissions

| Right | Who has it by default | Effect |
|---|---|---|
| `accounts:read` | Administrator, sales desk | Statements, ledgers, ageing, GST register, trial balance |
| `accounts:reports` | Administrator only (grantable) | Accounts performance section, Overview Accounts tiles, P&L report and exports, Accounts email block |
| `accounts:write` | Administrator | Record receipts and payments |
| `expense:read` / `expense:write` | Administrator | Expenses screen, entries, heads, settings, approval and reversal; the Expenses sidebar entry is shown under the Accounting feature switch only when `expense:read` is held |

Both checks are server-side (`require("accounts:reports")` and `require("accounts:read")`). The screen hides what the API would refuse; it never substitutes for the API check.

## 17. Data gaps

**Captured now (no longer gaps):** GAP-A01 expenses and heads (expense table, heads, approval, reversal, receipts, settings) and GAP-A02 cost of goods (append-only stock cost, weighted average per product, invoice attribution and audited corrections).

**Still not captured:** GAP-A03 year-end close and whole-book period locks (a locked accounting month refuses cost corrections and expense creation or reversal; invoice changes, credit notes, receipts, payments and year-end close are not covered) · GAP-A04 invoice due dates · GAP-A05 input GST and net payable · GAP-A06 GSTR-1/3B reconciliation · GAP-A07 TDS and statutory dues · GAP-A08 vouchers and day book · GAP-A09 bank reconciliation · GAP-A10 opening balances and balance sheet.

**Gaps raised only when the data is missing for the selected window:**

| Code | Meaning | Fix link |
|---|---|---|
| GAP-P01 | One or more invoices are not fully costed (no attributed stock issue, uncosted units, or a partial issue) | `#/inventory/ledger` |
| GAP-P02 | Expenses are not tracked for the whole window (window starts before `tracked_from`, or no start date is configured) | `#/expenses` |
| GAP-P03 | A payroll month in the window is absent, draft or only partly inside the window | `#/hr` |

Every remaining gap appears in the screen's Data gaps panel and in the email accounts block; none is drawn as zero. A figure that can be proved is shown even when another input is missing; gross profit is labelled partial and net profit is withheld.

## 18. Verification

| Check | Result |
|---|---|
| Accounts report tests | 9 tests in `tests/test_accounts_reports.py`: role gate (`accounts:read` is refused), dates and state validation, ageing and trial-balance reconciliation, Overview tiles equal the report, region filter scope, state and trend sums, gap semantics, both comparison modes with a zero base, email accounts block equal to the report. `test_missing_expenses_and_profit_are_gaps_not_zeroes` asserts GAP-A01/A02 are gone and GAP-P02/P03 are raised instead. |
| Profit and loss tests | 11 tests in `tests/test_profit_loss.py`: the hand-calculated month (revenue 1,000, returns 100, COGS 400, expenses 150, payroll 200, net profit 150) with GST present and proved not to change profit; non-creditable GST added to expense cost; GAP-P01, GAP-P02 and GAP-P03 cases; CSV, reconciliation CSV, XLSX and PDF opened and parsed; server-side 403s for sales, viewer and employee; sidebar mapping and role visibility |
| Costing tests | 18 tests in `tests/test_costing.py`: PO rate on receipt, company-wide weighted average, two invoices on one order, partial dispatch, price-only and stock-return credit notes, partial/NULL cost when no cost exists (never zero), product-row lock and concurrency, transfer/adjustment rows store NULL, audited correction with period lock (HTTP 423), dry-run backfill |
| Expense tests | 8 tests in `tests/test_expenses.py`: heads, entries, approval threshold switch and amount, non-creditable GST flag, creator cannot decide, reversal, receipts and settings |
| Reconciliation | The report's nine checks compare the statement with independent SQL over invoices, notes, expenses and payroll; `reconciled` is the conjunction, not a self-comparison |
| Trial balance | Debits equal credits on every report; the equality is asserted, not hidden |
| Email figures | `report_packs.build` and `/api/accounts/report` call the same `accounting.window()` and `profit_loss.statement()`; the tests compare revenue, outstanding, output GST, gross profit, expenses and net profit |
| Browser check | **Re-run 2 Nov 2026** on a temp server (127.0.0.1:8011) against `herbanova_bcs_test`, never the production server. Admin: Overview showed live gross profit "partial, 9 of 38 invoices costed", live expenses and net profit withheld with GAP-P01; the Expenses screen rendered with heads, settings and non-creditable GST shown as cost; P&L report returned eight agreeing checks and CSV (2,743 bytes), XLSX (9,205) and PDF (32,176) downloads. Sales, viewer and employee: no Expenses menu, and `/api/expenses`, `/api/expenses/settings`, the P&L report and its export all returned 403; forcing `#/expenses` did not render the screen. |

## 19. What is skipped or needs your decision

1. **Role for the MD.** There is no seeded MD login. Create an `md` role, grant `accounts:reports` (and `accounts:read` if the statements should be visible), and assign it to the MD user.
2. **Region scope.** Only flows that carry a buyer state can be filtered. A state filter does not narrow balances or cash; the screen says so. If you need a balance split by state, outstanding must be grouped on the distributor state at invoice time, which needs a stored snapshot.
3. **Expense tracking start.** Expenses count only from `expense_settings.tracked_from`; a window that starts earlier raises GAP-P02 rather than treating untracked months as zero. Payroll likewise counts whole approved months only and is never prorated.
4. **Year-end close.** Accounting months can be locked (the HR period-lock pattern, scope `accounting`). A locked month refuses purchase-cost corrections and expense creation or reversal. Invoice changes, credit notes, receipts, payments and a year-end close that freezes every document are not covered (GAP-A03).
5. **Vouchers** remain receipts and payments; the party ledger is the drill-down, and it links the document rather than a voucher (GAP-A08).
6. **Exports.** The Accounts screen exports CSV; the P&L report exports CSV, XLSX and PDF with its reconciliation table and notes; the email pack uses the same attachment builder.

## 20. Scheduled email reports

A separate section of this register; the operator guide is [docs/EMAIL_REPORTS.md](EMAIL_REPORTS.md).

| Area | What exists |
|---|---|
| Packs | Daily Business Summary, Weekly Management Report, Monthly MD Report, Alerts Digest, Accounts Report, Custom |
| Timing | Daily, Monday–Friday, chosen weekdays, monthly (day / last day / first working day), five-field cron; several slots; `Asia/Kolkata` default; holidays shift or skip; month-end and leap years handled |
| Recipients | Managed list with MD, Administrators and extras; To/CC/BCC; groups expanded at send time; unsubscribe only for extras |
| Content | Table HTML at 640 px, inline CSS, CID charts with alt text and data tables, plain-text alternative, comparison table, top lists, footer, test/preview banners |
| Attachments | Summary PDF, detail XLSX, up to two register XLSX; named, listed with rows and size; 9.5 MB budget with the dropped files named |
| Delivery | Separate DB-backed worker, unique run key, `SKIP LOCKED`, 30-minute stale release, 4 attempts with 5/15/45-minute backoff, Telegram alert on final failure |
| Screens | Administrator-only `#/scheduled`: Schedules, Recipients, Delivery log with Preview, Send test, Run now, Edit, Pause/Resume, Duplicate, Delete, Resend |
| Guardrails | `EMAIL_MODE=test` and `EMAIL_SEND_ENABLED=false` by default; test mode redirects to one Administrator; no real email until the owner approves the SMTP settings and recipient list |
| Audit | Every schedule and recipient change, every queue, every send and every final failure writes an audit row |
| Worker | `python -m app.email_worker` (loop) or `--once` (one cycle) |
| Samples | [docs/samples/](samples/) — rendered HTML and plain text from synthetic test data only |

The repository still has no Feature Inventory or Requirements Traceability Matrix;
sections 14–20 are the substitute, with each requirement tied to its screen,
endpoint, service and test. The email requirements map to `app/services/schedule.py`
(timing), `report_packs.py` (figures), `email_render.py` (content),
`mailer.py` (test/live gate), `email_worker.py` (delivery), `app/api/email_reports.py`
(Administrator API) and the two test files named in EMAIL_REPORTS.md §11.

**Needs your decision before go-live:** SMTP settings, sender address, recipient
list and who may receive the Accounts block. The checklist is in
[docs/EMAIL_REPORTS.md](EMAIL_REPORTS.md) §12.
