# Chapter 7 — Products and GST rates

**Audience:** stores and sales. **Permissions:** `product:read` to view, `product:write` to create or edit, `tax:read`/`tax:write` for the rate master. **UI route:** `#/products`. **Evidence:** `app/api/products.py`; `app/api/tax.py`; `tests/test_products.py`; `tests/test_catalog_orders.py`; migration `0024_catalog_order_dates`.

The product master is the source of every SKU, HSN, pack size, MRP, category, brand and reorder level used by purchases, invoices and reports. Products are never deleted; a product that is no longer sold is set to **discontinued**.

## 1. The product list

Columns: **HSN code**, **SKU**, **Name**, **Category / brand**, **Pack size**, **MRP (₹)**, **Reorder level**, **Status** and actions. Rows are ordered by SKU ascending until you choose another order.

The screen is read from the server in pages. The filter band above the table holds a search box and a **Status** select, with explicit **Search** and **Clear** buttons:

- **Search** matches SKU, name, HSN, category and brand. Typing searches after a short pause; the button searches at once. Both run on the server, so they cover every product, not only the page on screen.
- **Status** narrows to active or discontinued. Choosing a value searches immediately.
- **Clear** empties the search and resets the status, then returns to page 1.
- The footer reads **1–50 of 52** — the first and last row of this page, then the total number of products matching the current filters. It also carries **«**, **‹**, **›** and **»** for the first, previous, next and last page, a **Page n of m** label, and **Rows per page** (25, 50, 100 or 200; 50 by default). Buttons are disabled, not hidden, at the first and last page.
- **Export CSV** in the page head writes every product that matches the current search and status, not just the visible page. The file is named `HERBANOVA_Products_<date>.csv`, records the search, status and row count in its header block, and a toast confirms how many products were written.
- Every column heading except **Pack size** and the action column is a button. Click once to sort ascending, again to sort descending; the marker and `aria-sort` follow the click. Blank optional values (category, brand, reorder level) always sort last. Sorting and paging compose: changing the sort returns you to page 1 of the same filter.

Further rows:

- **Missing HSN** appears as an amber chip. A product created before the HSN rule can still be listed and opened; add the HSN on edit.
- **Category / brand** shows both values, or a dash when neither is captured.
- **Reorder level** shows the number, or **Not set** when the product has no level. Not set is not zero.
- A search with no match shows **No product matches these filters** and asks you to change the search or status, or clear the filters. This is distinct from **No products yet**, which appears only when the master is empty.
- **Open** shows the record read-only. **Edit** opens the form. **Save** on a row is a shortcut used by the edit flow.

## 2. Creating and editing a product

| Field | Required | Rule |
|---|---|---|
| HSN code | Yes | 4 to 8 digits. The GST rate master is keyed by the HSN, so a product without one cannot be created. Fixed after creation. |
| SKU | Yes | At least 3 characters; stored upper-case; unique. Fixed after creation. |
| Product name | Yes | |
| Category | No | Up to 60 characters. Free text; the form suggests values already used in the master. Blank means uncategorised. |
| Brand | No | Up to 60 characters, same rule as category. |
| Pack size | Yes | Free text, for example `10 tablets` or `100 g`. |
| MRP (₹) | Yes | Zero or more, two decimals. A line cannot be sold above MRP. |
| Reorder level | No | Zero or more units. Blank means **not set**; it never means zero. |
| Status | On edit | `active` or `discontinued`. |

The form offers suggestions for category and brand from values already saved (`GET /api/products/catalog`). The list is not a fixed taxonomy: typing a new category adds it to the master, and nothing is invented for products left blank.

Every change is audited with the old and the new value. A blank category, brand or reorder level is stored as `null`, not an empty string.

## 3. What the reorder level does

A product's balance is the total of all its batches across warehouses. When that balance is **below** the captured reorder level:

- the Stock screen shows a red **Low** chip beside the level;
- the Overview's needs-attention list counts the product and names up to three as `SKU (balance of level)`;
- the Stock report returns `below_reorder: true`.

A product with no level returns `below_reorder: null` and is not counted anywhere as low. Setting a level is a management decision, not a calculation: the system does not compute an economic order quantity or days of cover.

## 4. Categories and sales by category

The Overview's **Sales by category** panel groups issued invoices by the product's current category. A product with no category is grouped as **Uncategorised**. Categories are deliberately free text rather than a fixed list, so the business decides its own vocabulary; the cost is that two spellings of the same category appear as two rows.

## 5. GST rates

GST is looked up from the rate master by HSN, effective date and registration type. The product screen stores the HSN only; it does not store a rate, so an old invoice keeps the rate that applied when it was issued. Manage rates under the tax master screen (chapter 22).

## 6. Known limitations

| Limitation | Effect |
|---|---|
| **M-03** — the browser form never sends **UQC** | The API accepts a three-character unit, but the screen has no control, so invoice lines print "—" for the unit. Add the UQC through the API until the control exists. |
| No created/updated timestamp on the product | The list cannot be sorted or filtered by when a product was added. |
| Sorting is limited to the product's own columns | The list sorts by HSN, SKU, name, category, MRP, reorder level or status. It cannot be sorted by created date, stock or sales, which are not product fields. |
| No batch-level cost on the product | Value of stock by product is not shown (valuation policy gap). |
| Categories are free text | No rename-in-one-place; correct each product individually. |

## 7. Verification

- Create, edit, search, pagination and permissions: `tests/test_products.py`.
- List contract — disjoint pages, a stable `X-Total-Count`, export reads every matching row when `page` is omitted, server-side status filter: `tests/test_products.py::test_product_list_pages_and_server_filters`.
- Category, brand, reorder round trip, blank handling, negative refusal, catalog facets and search: `tests/test_catalog_orders.py::test_product_grouping_and_reorder_level_round_trip`.
- Low-stock attention and stock-report flag: `tests/test_catalog_orders.py::test_low_stock_attention_uses_the_configured_level` and `test_stock_report_exposes_grouping_and_reorder_flag`.
- Full suite on 4 November 2026: **467 passed**, 0 skipped.
- Header sorting was exercised in the same browser walk on 4 November 2026: MRP ascending `100.00 → 900.00`, descending `900.00 → 100.00`; each request carried `sort=mrp&direction=asc|desc` and `aria-sort` moved with the click.
- The list screen was exercised in a real browser on 4 November 2026 against a temporary server over the test database (52 products), at 1440, 768 and 390 px wide in light and dark themes. Observed: page 1 `1–50 of 52` with 50 rows, page 2 `51–52 of 52` with 2, search `COST` → 30 matching rows, a zero-match search → the filtered empty state, Clear → 50 rows with both controls reset, status `discontinued` → 0 rows, 25 rows per page → 3 pages with correct bounds, disabled next/last on the final page, opening a product from page 2, returning to the screen preserving page 2, and an export named `HERBANOVA_Products_2026-11-04.csv` with the toast **Exported 52 products**. Screenshots: `var/shots/wp-products-{1440,768,390}-{light,dark}.png` plus their `-foot` variants.
- The load-ordering guard (a slow earlier request losing to a newer one, and the page-1 retry when a filter empties the current page) was code-reviewed but not reproduced in the browser, because every filter control deliberately reloads page 1.
