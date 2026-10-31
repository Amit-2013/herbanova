# Dashboard v2 — decisions and assumptions

**Date:** 1 November 2026
**Branch:** `feature/dashboard-v2`
**Rule applied throughout:** when the data does not exist, show "No data yet" with the gap code; never invent a figure; never change an existing permission; every schema change gets a migration and a rollback.

This file records every decision taken without the owner present, so each one can be reviewed or reversed.

---

## D-01. Work happens on a new branch with one commit per step

**Decision.** All v2 work is committed to `feature/dashboard-v2`, one commit per requested step, with the verified pre-v2 work as the first (baseline) commit.
**Why.** The owner asked for a branch and per-step commits. A separate baseline keeps the v2 history readable and gives a clean rollback point (`master` is untouched).
**How to reverse.** `git checkout master` and delete the branch; no data or schema on `master` changed.

## D-02. The date filter defaults to the current month, not 30 days

**Decision.** `from_date`/`to_date` default to the first day of the current month and today. `range=7|30|90` stays accepted for older callers and is translated into the same window ending today.
**Why.** The requirement says the default is the current month. Keeping `range` avoids breaking the two existing dashboard tests and any saved bookmark.
**Consequence.** A request with only `range` returns `from`/`to` for that window; a request with dates ignores `range`.

## D-03. Date validation is server-side and strict

**Decision.** Reject `from_date > to_date` and any `to_date` after today with HTTP 422. `from_date` may be any past date.
**Why.** The requirement says no future dates. Validating on the server keeps the truth out of the browser's hands; the UI mirrors the message.
**Exception.** Forecast and projection figures inside the MoM/YoY page are labelled as estimates and are computed from data up to today, never by querying a future date.

## D-04. "As of today" cards do not move with the range

**Decision.** Stock, expiry, batches, warehouse capacity and open purchase orders remain current snapshots and carry the subtitle "As of {date}". Sales, purchases, orders, returns, receipts, top products, ageing-by-period, leads and activity follow the selected dates.
**Why.** A stock snapshot cannot be reconstructed for an arbitrary historical day without daily snapshots; the movement ledger does allow it for units on hand, which is why only the stock-history trend uses the range. Labelling prevents a reader from assuming the range applies everywhere.

## D-05. Ageing stays "as of the end of the selected range"

**Decision.** Receivables ageing is computed on the selected `to_date`, not on today, and the card says "As of {to_date}". When no date is chosen it is today, which is the previous behaviour.
**Why.** The ageing report already accepts an as-of date; using it makes the card reconcile with the report for the same date.

## D-06. Approvals are decided inline, using the existing endpoint

**Decision.** Each row on the Overview gets Approve and Reject buttons. Approve sends the existing `POST /api/approvals/{id}/decide` with a default reason "Approved from the dashboard"; Reject swaps the buttons for an inline reason field and requires at least 3 characters. The card, the KPI tile and the sidebar badge refresh from one `loadAll()` reload after a decision, and the server retires the cached dashboard payload on every successful decision so a stale count cannot come back for 45 seconds.
**Why.** Reusing the endpoint keeps every rule (segregation of duties, admin-only credit limits, audit log) in one place. The reason field is required by the API (`min_length=3`), so the UI supplies a truthful, visible default rather than inventing one on the server. The inline form keeps the decision in context instead of opening a drawer.
**Consequence.** A user who cannot decide sees no buttons and the rule in words; a requester sees "You raised this request".

## D-07. "Who may decide" is described, not guessed

**Decision.** The API returns `deciders` as a list of role words derived from the same rule `can_decide` uses: "Administrator" for credit-limit and post-billing; "Administrator or an approver with approval:decide" for sales orders; the specific HR permission for HR types. Pending request types with no handler say "No decision handler yet". It also returns `age_days`, counted in whole days in `Asia/Kolkata` (the report timezone) and never negative, because a request cannot be raised in the future.
**Why.** Naming the rule in words is honest; naming individual people would be wrong (any holder of the permission may decide) and could go stale. Age in UTC would show yesterday's request as "today" after 05:30 IST; the business day is what a user reads.

## D-08. Purchases remain valued at order cost

**Decision.** The purchases line continues to value received goods at `purchase_order_lines.unit_cost`, labelled in the card and the metric register.
**Why.** There is no purchase invoice or landed-cost capture. Using the order cost is the only sourced number; zero-cost lines count as zero because the alternative would be to guess a cost.
**Revision (v2).** The card draws sales as a solid green line with the area under it filled and purchases as a dashed amber line. Both legend entries are pills that show or hide their series; the last visible series cannot be hidden, so the card never becomes blank. Sales totals reconcile with the Sales Invoice Register and purchases with the Goods Receipt Register over the same dates; tests check both independently.
**Consequence.** Sales (tax-inclusive) and purchases (cost, exclusive of tax) are different bases; the card legend says so.

## D-09. Warehouse capacity is stored in units with one optional unit word

**Decision.** Add `warehouses.capacity_units` (integer ≥ 0, nullable) and `warehouses.capacity_note` (short free text such as "pallets"). A NULL capacity means "not configured" and the UI says so; it never means zero.
**Why.** Stock on hand is measured in units, so capacity in units is the only comparison that needs no conversion. A note field lets the owner say "120 pallets" without a second unit system that the system cannot convert.
**Migration.** `0009_warehouse_capacity` adds both columns (nullable, no default); its `downgrade()` drops them. No existing row is rewritten.

## D-10. Capacity warnings are warnings, not blocks, by default

**Decision.** A goods receipt that would take a warehouse above its configured capacity returns HTTP 409 "capacity exceeded" unless the caller sends `allow_over_capacity=true`. That flag is only honoured for an Administrator, and the override is written to the audit log with the warehouse, the quantity and the new total.
**Why.** Blocking stock receipt outright could stop the business; a silent warning could let a warehouse overflow. An explicit administrator override is the middle ground and is fully logged.
**Dispatch.** Dispatch is not capped by capacity: it can only reduce stock. It shows the source warehouse's remaining stock and capacity in the dispatch result so the operator sees the position.
**Purchase orders.** Raise-time checking is not possible because a purchase order carries no warehouse; the warehouse is chosen when goods arrive. Capacity is therefore checked at the goods receipt, which is the first moment the destination is known.
**Revision (v2).** The receipt form shows the chosen warehouse's used, free and capacity figures before submission and names the block in the 409 message. The override checkbox is revealed only after the server refuses the receipt, and the server still enforces that only an Administrator may use it; the override is audited as `warehouse.capacity_override` with the before and after totals. A role that is not an Administrator gets a 403 even if it sends the flag.
**Transfers.** There is no transfer endpoint, so no transfer check exists (GAP-V09, recorded, not built).

## D-11. The utilisation report is additive and read-only

**Decision.** Add `warehouse_utilisation` to the report catalog, permission `stock:read`, using the same query as the dashboard.
**Why.** The requirement asks for reconciliation; using one function for both guarantees it. No new permission is introduced.

## D-12. The MoM/YoY page uses one endpoint and two explicit modes

**Decision.** `GET /api/dashboard/compare?mode=full_month|mtd&month=YYYY-MM`. `full_month` compares the whole calendar month with the whole previous month and the same month last year. `mtd` compares day 1 to `min(today, month end)` with the same day number in the previous month (capped at that month's last day) and in the same month last year (capped the same way).
**Why.** Two explicit modes are clearer than inferring "month to date" from a range, and they make the comparison dates explainable on screen.
**Zero base.** When the comparison value is zero or missing, the change is `null` and the UI says "No data yet" or "New" (for a positive current value against zero), never infinity or NaN.
**Future months.** A month that has not started may be selected; every figure is zero and the cards say "No data yet". The current month is labelled "Current month (incomplete)".

**Built in v2.**
- **Windows.** The response carries `ranges.current`, `ranges.previous`, `ranges.last_year` (each with an ISO start and end plus a human label), `ranges.mode`, `ranges.state` (`future`, `current` or `past`), `ranges.elapsed_days` and `ranges.days_in_month`. `elapsed_days` counts real days, so a current full month still covers the whole calendar in the figures but divides the run rate only by the days that have happened. MTD comparison windows stop at the same day number, capped at that month's last day (29 February is therefore compared correctly).
- **Cards.** `cards` has sales, purchases, orders, gross margin, receipts, returns, new leads and new customers. Each carries the current value, the previous month and same-month-last-year values, the change (absolute and percentage) and `available`. The comparison is `null` when the base is zero, never infinity or NaN. A card the caller may not read is **omitted from the payload**, not returned as null, so the browser cannot display a figure the API would hide. Gross margin (`GAP-D04`) and new customers (`GAP-V16`) are returned with `available: false` and their gap code.
- **Trend.** Twelve selected months plus the same twelve months of the prior year, a 3-month moving average over the selected series, best and worst month (only months with a positive figure), month-on-month and year-on-year growth, and a seasonality index (current month over the same month a year earlier) that is `null` when the prior figure is zero. Months before the first data simply read zero; nothing is extrapolated.
- **Projection.** The selected month's figures divided by `elapsed_days` and multiplied by `days_in_month`, returned with `is_estimate`, `complete`, `state`, `elapsed_days`, `days_in_month`, a `label` and an explanatory `note`. A past month is `complete`; a future month is "Not started"; a current month is "Run-rate estimate (not a forecast)" and the UI badges it "Estimate". A run rate is arithmetic, not a forecast: it assumes the rest of the month behaves like the days already recorded.
- **Breakdowns.** Top five products and top five distributors by **taxable value before GST** in the selected window, from issued invoice lines. Rows are sorted by value and the count shown is the number of rows returned, not an estimate.
- **Queries and indexes.** One query per metric per window; the four date columns grouped or filtered on (`sales_orders.created_at`, `credit_notes.note_date`, `goods_receipts.received_at`, `leads.created_at`) are indexed by migration `0010_comparison_indexes`, whose `downgrade()` drops exactly those four indexes. No row is rewritten and no existing index is removed.
- **Caching.** As D-17: the existing 45-second in-process cache, keyed additionally by mode and month.
- **Export.** CSV as D-16, from the rendered data, with the explicit window dates in the header.

## D-13. Gross margin and new customers are shown as gaps

**Decision.** The comparison card for gross margin returns `available: false` with `gap: GAP-D04` because neither stock nor invoice lines carry a cost. New customers returns `available: false` with `gap: GAP-V16` because distributors have no creation timestamp.
**Why.** Computing margin as revenue would be wrong; counting all customers as "new" would be wrong. Both are shown as "No data yet" and listed for review.

## D-14. Geography uses the invoice's frozen buyer state

**Decision.** The state is `invoices.buyer_state_code` from the issued invoice snapshot (falling back to the distributor's current state only when a row predates the snapshot — none exist today). District and city are not available and are not offered. Invoices without any state code are grouped under "Location not recorded" so the total reconciles.
**Why.** The invoice snapshot is immutable and is the document of record for place of supply. The distributor master can change; the invoice cannot.
**Map.** The page draws a local, hand-built state tile grid (an inline SVG built in the browser from a fixed state layout) shaded by the selected metric, with a ranked list as the accessible equivalent on phones. No external map service, no network request. A true geographic outline is not drawn because a hand-drawn India outline risks being inaccurate; the tile grid is labelled "State tile map".
**Territory.** The free-text `distributors.territory` is not used as a geography key (GAP-V12); the page says so.
**Role scope.** Geography is gated by `sales:read` (and return figures additionally by `accounts:read` where they come from notes). There is no territory-scoped user model, so "a regional user sees only their territory" cannot be enforced and is recorded as a gap rather than faked.

**Built in v2.** `GET /api/dashboard/geo?from_date=&to_date=` validates the window with the same rules as the dashboard (422 when from > to, a future date, or an unparseable date) and defaults to the current month. It returns the window and label, a `basis` block (invoices with a snapshot, invoices falling back to the distributor master, the "Location not recorded" count), totals, per-state rows, top and bottom five, the fixed 37-code map list, returns, GST split and the notes shown on the page. Grouping uses `coalesce(invoices.buyer_state_code, distributors.state_code)`, so a pre-snapshot row still lands in a state and the sum of rows always equals the window total; rows with neither code are kept as "Location not recorded" rather than dropped. Tax fields are returned only with `tax:read`; returns only with `accounts:read`; without either, the payload says which permission is missing and the page renders a gap box instead of zeros. "Top" and "bottom" rank only states with a positive sale, so a row of zeros is never presented as a "lowest performer". The page sorts in the browser (server order is sales desc) and exports the rendered table to CSV with the window dates and the same permission-dependent columns. The map is 37 fixed tiles from `app/core/india_states.py`, shaded by sales share; tiles with no sale stay neutral. District/city/pincode remain unavailable (GAP-V11), so the level chips say "No data yet" and the page does not guess. Responses use the existing 45-second cache (D-17), keyed by user, permissions and window.

## D-15. Returns by region are reported at state level only

**Decision.** Return value and count come from issued credit notes grouped by the invoice's buyer state. Return reason is shown as the free text recorded on the note; no categories are invented (GAP-V10).
**Why.** Credit note lines carry the product and quantity, but reasons are prose. Grouping prose would require an unstated dictionary.

## D-16. Export is CSV for the new tables

**Decision.** The MoM/YoY comparison table and the geography table export to CSV through the browser from the data already rendered, naming the exact compared dates in the file header. PDF export of these two tables is not added in v2.
**Why.** The existing export service builds PDFs from the report catalog; these are dashboard tables, not catalog reports, and adding a second PDF layout would duplicate the document pipeline. CSV is a complete, honest export; the gap is recorded.

## D-17. Caching follows the existing rule

**Decision.** The 45-second in-process cache is keyed by user, permissions, date range, mode and month, and is disabled outside production and for `_test` databases (the existing rule). No new cache layer.
**Why.** Keeps behaviour consistent with the current dashboard and prevents tests reading another test's payload.

## D-18. No existing permission is changed

**Decision.** New endpoints reuse `approval:read`, `sales:read`, `stock:read`, `accounts:read`. The capacity editor reuses `stock:write`; the capacity override additionally requires the Administrator role. No role's permission set is edited, and `BASELINE_ROLE_PERMS` is untouched.
**Why.** The owner forbade changing existing permissions. Reusing an existing read permission for a new read endpoint is additive and keeps the permission matrix stable.

## D-19. Invoice print signature block

**Decision.** Centre the company line (`For {seller}`) and "Authorised signatory" on the same horizontal axis, above and below the signature line, in both the invoice and the credit/debit note layout.
**Why.** They are one signature block; right-aligning the company name while centring the designation makes the two lines look misaligned on paper. The fix is layout-only and changes no document content.

## D-20. Demo data is not added in v2

**Decision.** No new demo rows are seeded on this branch. The existing marked demo seed and its rollback remain the only synthetic records.
**Why.** The owner's data-safety rules; v2 changes are verified against the existing demo set and the isolated test database.
