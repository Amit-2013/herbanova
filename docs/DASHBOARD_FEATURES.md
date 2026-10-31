# Overview Dashboard — Metric Register

**Project:** Herbanova Business Control
**Phase:** 2 — Overview dashboard
**Date:** 1 November 2026
**Source of truth:** `app/api/dashboard.py`, `static/js/app.js`, `static/index.html`, `static/css/styles.css`
**Rule:** every figure on the screen is a SQL aggregate over the whole database. Nothing is computed by filtering a capped browser list, and no figure is invented. When the input is not stored, the screen says **No data yet**, names the gap (GAP-Dxx) and the section is listed in §8.

---

## 1. Endpoints

| Endpoint | Purpose | Permission | Notes |
|---|---|---|---|
| `GET /api/dashboard?range=7\|30\|90` | One aggregated payload for the whole page | signed in; each section additionally gated (see §7) | `range` outside 7/30/90 → **422**. Default 30. |
| `GET /api/dashboard/expiry?bucket=expired\|lt30\|lt90\|all&page&page_size` | Paged expiry drill-down | `stock:read` | `page_size` 1..100 (default 25); rows sorted by expiry, then batch id. |
| `GET /api/dashboard/search?q=` | Global search (palette) | signed in; each group gated | Minimum 2 characters; returns at most 5 rows per group. |
| `GET /api/dashboard/activity?limit=1..50` | Recent audit entries | `audit:read` | Used by the activity feed and the palette. |

The payload defaults every Phase-2 section to `null` and fills only what the caller may see. A section the role cannot read is **`null`, never `0`**, so the browser can distinguish "none" from "not permitted".

**Legacy keys are unchanged** (`stock`, `purchase_orders`, `active_products`, `orders_ready`, `approvals_waiting`, `leads`, `warehouse_count`) so any existing consumer keeps working.

---

## 2. Refresh, cache and performance

| Item | Rule |
|---|---|
| Cache | In-process, key = `(user id, sorted permissions, range, administrator flag)`, TTL **45 s** (`DASHBOARD_TTL_SECONDS`). A different role or range never reuses another caller's payload. |
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
| Period 7D / 30D / 90D | Reloads the dashboard with the chosen range; the choice survives reload (`localStorage hb.dashRange`); the pressed button is `aria-pressed` | `setDashRange()` |
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
| Warehouse capacity | not stored (GAP-D03) | "No data" | — |
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

Warehouses from `warehouses` (including empty ones), with batches and units in stock and the unit share of total stock. A non-zero tiny share shows **<1%** rather than rounding to 0%. Capacity is not stored (GAP-D03), so no fill-level bar is drawn and the panel says so.

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
| Modules | Server module register (`module_register.totals()`) | "15 of 15 modules working" + expandable list of every module |
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
| Health, search, greeting | signed in | Visible to every signed-in user; search groups still gated |

All gates are enforced in `app/api/dashboard.py` and are covered by `tests/test_dashboard_phase2.py` (null sections per role, chart masking, search scoping, activity permission, HR self-scoping).

---

## 8. Data gaps shown on the dashboard

| Gap | Missing input | What the screen does |
|---|---|---|
| GAP-D01 | Product category or brand | "Sales by category" → No data yet |
| GAP-D02 | Reorder level | "Low stock against reorder level" → No data |
| GAP-D03 | Warehouse capacity | Capacity rule and fill bars omitted; "Capacity is not captured" |
| GAP-D04 | Batch cost / valuation policy | Expiry rows omit value; footer names the gap |
| GAP-D09 | Persisted backup/restore result | Health card "Not recorded" |

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

**Browser verification (1 November 2026):** signed in as the Administrator against the development database at `http://127.0.0.1:8000/ui/`. Confirmed: greeting/date/updated line; 8 KPI tiles with values from the database; attention list with two named gaps; chart totals and hover tooltip; ageing total "₹ 70,00,000.00" in Indian grouping with the report-matching note; expiry filter counts and empty state; warehouse shares; open-PO empty state; approval review drawer showing the server's self-approval restriction; top products; category "No data yet (GAP-D01)"; "Latest 8 of 323 entries."; health cards ("15 of 15", schema at head, backup not recorded, alerts configured); range 7D switched the window and reloaded; palette opened with Ctrl+K, searched, highlighted with arrows and closed with Esc; dark theme toggled the tokens; Inventory, Approvals, Reports, Sales orders, HR and Settings all still rendered; **no console messages or errors**. The Phase 3 cards were then checked in the same session: pipeline (2 sales orders, 0.5-day average to dispatch across 1 dispatched order), customers and credit (outstanding ₹ 70,00,000.00 reconciling with the ageing panel; 6,250% credit use shown as "over limit"), PO ageing (0 open), corrections (0 notes, 0 post-billing requests) and HR today (5 active, 0 marked, 5 not marked); Customers, Sales orders, Purchases, HR and Overview screens still rendered; dark theme applied to the new cards; no console errors. A duplicate function name (`renderCustomers`) initially hid the customers card and was renamed to `renderInsightCustomers`.

**Limitation:** the in-app browser had no visible surface, so the check was DOM- and interaction-based (computed styles, text, element state) rather than pixel screenshots. The responsive breakpoints (1180/980/820/560 px) were authored and inspected in CSS but not visually exercised at those widths.

---

## 10. Deliberately not built

**Delivered in Phase 3** (all from stored data, no new schema): pipeline by status and order-to-dispatch time, top customers, receivables by customer with credit usage, returns and credit/debit notes, PO ageing and pending-receipt counts, post-billing amendment view, HR attendance and pending leave/on-duty, and FEFO suggestions in the expiry detail. The cards are described in §5.12.

| Not built | Reason | What would unblock it |
|---|---|---|
| Sales by category / margin by category | GAP-D01 | `products.category` (migration + backfill) |
| Low-stock and stock-cover alerts | GAP-D02 | `products.reorder_level` |
| Warehouse capacity alerts / fill level | GAP-D03 | `warehouses.capacity_units` |
| Expiry value and stock value | GAP-D04 | Batch cost at receipt or a valuation policy |
| PO due-date and supplier on-time | GAP-D05 | `purchase_orders.expected_date` |
| Ageing by due date | GAP-D06 | `invoices.due_date` |
| GST input/output summary | GAP-D07 | Purchase tax capture |
| Lead funnel over time | GAP-D08 | Structured status history |
| Last backup / restore test card | GAP-D09 | A persisted run record from `backup_restore_test.py` |
| Trend lines for POs, orders, approvals, follow-ups, products | No stored status timeline | Event/status history tables |

No sample or placeholder data is used anywhere in production code; the gaps are surfaced as gaps.
