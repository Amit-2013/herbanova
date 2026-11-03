# Chapter 7 — Products and GST rates

**Audience:** stores and sales. **Permissions:** `product:read` to view, `product:write` to create or edit, `tax:read`/`tax:write` for the rate master. **UI route:** `#/products`. **Evidence:** `app/api/products.py`; `app/api/tax.py`; `tests/test_products.py`; `tests/test_catalog_orders.py`; migration `0024_catalog_order_dates`.

The product master is the source of every SKU, HSN, pack size, MRP, category, brand and reorder level used by purchases, invoices and reports. Products are never deleted; a product that is no longer sold is set to **discontinued**.

## 1. The product list

Columns: **HSN code**, **SKU**, **Name**, **Category / brand**, **Pack size**, **MRP (₹)**, **Reorder level**, **Status** and actions.

- **Missing HSN** appears as an amber chip. A product created before the HSN rule can still be listed and opened; add the HSN on edit.
- **Category / brand** shows both values, or a dash when neither is captured.
- **Reorder level** shows the number, or **Not set** when the product has no level. Not set is not zero.
- The search box matches SKU, name, HSN, category and brand. Search is done by the server; it does not scan only the visible page.
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
| No batch-level cost on the product | Value of stock by product is not shown (valuation policy gap). |
| Categories are free text | No rename-in-one-place; correct each product individually. |

## 7. Verification

- Create, edit, search, pagination and permissions: `tests/test_products.py`.
- Category, brand, reorder round trip, blank handling, negative refusal, catalog facets and search: `tests/test_catalog_orders.py::test_product_grouping_and_reorder_level_round_trip`.
- Low-stock attention and stock-report flag: `tests/test_catalog_orders.py::test_low_stock_attention_uses_the_configured_level` and `test_stock_report_exposes_grouping_and_reorder_flag`.
- The screen wiring was read in `static/js/app.js` (`renderProducts`, `productDrawer`, `saveProduct`, `fillProductCatalog`) and syntax-checked; it was not re-exercised in a browser after migration `0024`.
