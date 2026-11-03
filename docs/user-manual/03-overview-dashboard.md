# Chapter 3 — Overview dashboard

**Audience:** every signed-in user. **Permissions:** `require_login`; each panel additionally needs its own read permission. **UI route:** `#/dash`. **Chapter status:** written and verified against source on 31 October 2026; §1 refreshed for the From/To period strip and the **MoM & YoY dashboard** action on 3 November 2026. **Evidence:** `app/api/dashboard.py`; `tests/test_dashboard.py`, `tests/test_dashboard_phase2.py`, `tests/test_dashboard_phase3.py`, `tests/test_catalog_orders.py`.

The Overview is the landing screen. It never invents a figure: a panel the server cannot compute shows **No data yet**, names the missing input and points at the screen that fixes it. A panel your role may not read is **absent and not zero** — the server returns `null` for it and never sends the number.

## 1. Period selector

The page head shows a greeting and today's date, with the **MoM & YoY dashboard** button on the right. Under it sits the period strip: the **From** and **To** date fields, then six presets in one row.

| Preset | Window |
|---|---|
| **7D** / **30D** / **90D** | The last 7, 30 or 90 days, ending today |
| **This month** | The first day of the current month to today |
| **Last month** | The whole previous calendar month |
| **This FY** | 1 April of the current financial year to today |

**This month** is the default. A preset fills both dates; typing or picking a date applies it when the field changes. The window is remembered in this browser and reused next time, so the Overview opens where you left it.

The line under the strip states exactly what was counted: **Selected period 1 November 2026 to 3 November 2026 (3 days) · snapshot cards are as at 3 November 2026 · updated 14:05**. Snapshot tiles (units, batches, approvals, leads, active products) are measured **today** whatever window is chosen, and the line says so; only the period figures follow the dates.

The window drives the sales-and-purchases chart and its previous-period comparison, receivables ageing (**measured as at the To date**, so it agrees with the Receivables Ageing report for that date), top products, sales by category, the Accounts block and the period-based insight cards.

**Checks on the dates.** The browser refuses a window it can see is impossible and puts the reason under the strip in red, without sending a request:

| Situation | Message |
|---|---|
| One date empty | **Choose both dates, or pick a preset.** |
| From after To | **The From date cannot be after the To date.** |
| To in the future | **The To date cannot be in the future.** |

The server repeats the last two checks and answers **422** (`to_date cannot be in the future`, `from_date cannot be after to_date`); it never replaces an invalid window with a default. A caller using the older `range` parameter instead is limited to **7, 30 or 90**, and any other value is **422**.

An Administrator holding `db:reset` also sees **Reset database** at the end of the strip; the guarded reset, its modes and its recovery procedure are in [`../DB_RESET.md`](../DB_RESET.md).

**VERIFIED (code):** the strip is `#dashFrom`/`#dashTo` and `[data-dash-preset]` in `static/index.html:170-184`; the presets are computed in `dashWindow()` (`static/js/app.js:67-83`), defaulted to the current month at `app.js:84`, restored from `localStorage` at `app.js:85-93` and validated in `applyDashDates()` (`app.js:1502-1525`). The server-side window and its 422s are `_period()` in `app/api/dashboard.py:1650-1666`. The "Selected period …" line is rendered at `app.js:753-757`, and ageing is measured at the To date at `dashboard.py:1701-1703`.

## 2. KPI tiles

Every tile is a link to the records behind it. Trends appear only when the server can reconstruct history from stored movements; otherwise the tile says why there is no line.

| Tile | What it counts | Opens |
|---|---|---|
| Units on hand | Sum of batch balances above zero, all warehouses | Inventory → Stock |
| Batches in stock | Batches with a positive balance | Inventory → Stock |
| Expiring ≤ 90 days | Batches expiring within 90 days (split into already expired and within 30) | Inventory → Stock |
| POs awaiting goods | Open and partly received purchase orders | Purchases |
| Orders ready to dispatch | Approved orders not yet dispatched | Sales orders |
| Approvals waiting | Pending approvals **you are allowed to see** | Approvals |
| Follow-ups overdue | Leads still open whose next follow-up date has passed | Leads |
| Active products | Products with status `active` | Products |

Orders ready to dispatch has **no stored trend**: the tile counts the orders that are approved today, and the note says so rather than drawing a fabricated line.

## 3. Needs attention

Only rules with a non-zero result are listed; healthy rules are omitted.

| Rule | When it fires | Link |
|---|---|---|
| Batches past expiry | Any batch with stock whose expiry date has passed | Inventory → Stock |
| Warehouses above 80% capacity | Configured capacity divided into used units; amber above 80%, red above 95% | Inventory → Warehouses |
| Receivables over 60 days | Ageing buckets 61–90 and 90+ | Accounts |
| Approvals needing an Administrator | Pending credit-limit or post-billing requests you can see | Approvals |
| Low stock against reorder level | A product's balance is below the reorder level **you captured**; the note names up to three as `SKU (balance of level)` | Inventory → Stock |

A product with **no reorder level is not counted at all**. "Not set" is not zero, so switching a level on can only reveal a real shortage.

## 4. Sales and purchases

The chart plots daily sales (issued invoices, including GST) against daily purchases (goods receipts at order cost). Hover or use the arrow keys to read a day. With only `sales:read` the purchase line is removed by the server; with only `stock:read` the sales line is removed. The previous period of equal length is compared underneath, and a zero previous total reads "no prior period to compare" instead of a percentage.

## 5. Receivables ageing, stock to watch and stock by warehouse

- **Receivables ageing** uses the same function as the Receivables Ageing report; the total is stated to match the report.
- **Stock to watch** filters expired, ≤ 30 days and 31–90 days in disjoint buckets. Batch value is not shown because stock carries no valuation policy.
- **Stock by warehouse** shows units and share, plus capacity when configured. A warehouse without capacity says "Capacity not set" rather than showing 0%.

## 6. Top products and sales by category

**Top products** lists up to six products by taxable value before GST, with units, revenue and the previous-period change.

**Sales by category** groups issued-invoice taxable value by the product's **captured category** (see chapter 7). Products with no category are grouped as **Uncategorised** and named as such; the panel states the classified and uncategorised totals separately. Nothing is guessed from the product name or SKU. Because the current product category is used, correcting a mis-categorised product re-groups its history — the panel note says the figure is "as printed on issued invoices".

Requires `sales:read`.

## 7. Approvals, recent activity and system health

- **Approvals waiting** lists up to six requests using the same visibility rule as the approvals queue. Review opens the approvals drawer; the drawer shows the server's decision rules, and a requester cannot decide their own request. Decisions still go through `POST /api/approvals/{id}/decide`, which re-checks role, permission, self-approval and reason, and writes an audit row.
- **Recent activity** shows the latest eight audit entries and the exact total. Requires `audit:read`.
- **System health** reports the module register, the Alembic revision against the code head, backup/restore (not recorded until `backup_restore_test.py` is run and kept), and whether the alert channel is configured. A missing backup result is shown as missing, never as a green tick.

## 8. Insight cards

| Card | What it shows | Gate |
|---|---|---|
| **Pipeline** | Sales orders by status with count and value; order-to-dispatch average; approval wait and after-approval wait measured separately; promise delivery (on time, late, average days late); open orders past their promise; leads by status | `sales:read`; leads need `lead:read` |
| **Customers and credit** | Top customers by issued-invoice value; outstanding per customer reconciled with the ageing total; credit limit, exposure, available and "% used" per distributor | `sales:read`; outstanding needs `accounts:read` |
| **PO ageing** | Open and part-received POs bucketed by days since the order date, with the number never received and part received | `stock:read` |
| **Corrections after billing** | Issued credit/debit notes in the period and post-billing amendment requests | `sales:read` |
| **HR today** | Headcount, attendance marked and not marked, pending leave and on-duty, attendance by status | `hr:read` |

**How the pipeline figures are measured.** Raised to dispatch is dispatch time minus order time. Approval time is approval stamp minus order time. After-approval time is dispatch minus approval. Lateness compares the dispatch date in India time with the promised delivery date. Orders approved before migration `0024` have no approval stamp and orders without a promise have no date, so those orders are **excluded** from the respective average instead of being counted as zero. Purchase-order lateness is still not shown because purchase orders have no expected date.

## 9. What the server enforces

- A section you may not read is `null`, never `0`.
- Counts are exact even when a list is capped at six; the card states the true total.
- The dashboard is read-only. It adds no write path, and every action it offers opens an existing screen or endpoint.
- All permission gates are enforced in `app/api/dashboard.py`, not only hidden in the browser.

## 10. Known limitations

| Limitation | What you see |
|---|---|
| Purchase-order expected date not captured | No supplier on-time or PO-lateness figure |
| Invoice due date captured at issue | The Accounts ageing shows a due-date split (overdue, due within 7 days, later, none); the Overview buckets stay by invoice date for comparability (chapter 24) |
| No batch valuation policy | Expiry rows omit value; stock value by warehouse is not shown |
| No trend history for POs, approvals, follow-ups and active products | A stated reason instead of a sparkline |
