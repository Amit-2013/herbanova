# Chapter 8 — Inventory and warehouses

**Audience:** stores and dispatch. **Permissions:** `stock:read` to view, `stock:write` to maintain warehouses and capacity. **UI routes:** `#/inventory/stock`, `#/inventory/ledger`, `#/inventory/warehouses`. **Evidence:** `app/api/inventory.py`; `app/services/inventory.py`; `tests/test_capacity.py`; `tests/test_report_reconciliation.py`; `tests/test_catalog_orders.py`.

Stock is never typed in directly. Every balance is the sum of the append-only movement ledger, and stock only changes through a goods receipt, a dispatch, a return, a free-of-cost receipt or an approved correction. The screens here are read-only views of that ledger plus warehouse master data.

## 1. Stock on hand

Columns: **Product**, **Batch**, **Warehouse**, **Shelf life**, **Owner**, **On hand**, **Reorder level**.

- Rows are ordered first-expiry-first-out, with batches that have no expiry last.
- The filters are a product/batch search, a warehouse selector, and **Hide empty batches** (on by default).
- **Shelf life** is a chip such as "Expired 2 days ago", "Expires today" or "14 days left".
- **Reorder level** is the product's captured level, or **Not set**. When the product's total balance across all warehouses is below the level, an amber/red **Low** chip appears beside it. A product with no level can never show Low.
- The list shows one row per batch. The Low chip uses the product's whole balance, not just the batch on that row, so seeing it on one row does not mean that batch alone is short.
- Stock with no receipts yet shows "No stock has been received yet", not a zero row.

## 2. Stock ledger

The ledger is append-only and shows **time**, **movement type**, **product**, **batch**, **warehouse**, **reference** (the document that caused it), **actor** and **quantity delta**. Inbound rows are green, outbound rows red.

Movement types include receipt (goods receipt or opening), issue (dispatch), return, adjustment, transfer, write-off and free-of-cost receipt. The search matches SKU, product name, batch, and the reference label; the type selector filters to one movement type. If the ledger is long, the screen states that it is showing the latest 200 movements; older rows remain in reports and exports.

## 3. Warehouses and capacity

Warehouses are master data. A warehouse row shows batches, units in stock, capacity, free units and utilisation with a chip:

| State | Meaning |
|---|---|
| Within capacity | Below 80% |
| Above 80% | 80% to 95% |
| Over capacity | Above 95% |
| Not set | No capacity captured; the screen says **No data yet**, never 0% |

`stock:write` can set or change capacity and an optional short note. Capacity is in units; leave it blank when it has not been measured. Blank never means zero, and a warehouse without capacity is not treated as full.

## 4. Receipts, dispatch and FEFO

- Goods arrive only through a purchase order receipt (chapter 9) or a free-of-cost receipt. A receipt posts one inbound movement per batch and is refused when the warehouse would exceed its capacity, unless an Administrator explicitly overrides.
- Dispatch allocates batches first-expiry-first-out from the chosen warehouse (chapter 11). If stock is short, the whole dispatch is refused before anything moves.
- A free-of-cost receipt is costless by design and is recorded with its own cost source so it cannot distort weighted-average cost.

## 5. Reports that read this data

The Stock report lists every product with its quantity, batch count, category, brand, reorder level and a **below reorder** flag. It is the exportable form of the same balances shown here. The Inventory reports also cover movements and warehouse utilisation (chapter 18).

## 6. Known limitations

| Limitation | Effect |
|---|---|
| No stock transfer between warehouses | Moving stock requires a return plus a new receipt today |
| No write-off or shrinkage workflow | Corrections exist only through the audited cost-correction/free-of-cost paths |
| No batch QC status or licence expiry | Compliance cards cannot be built |
| No batch valuation policy | The stock screen shows quantities only; expiry rows omit value |

## 7. Verification

- Capacity check and Administrator override: `tests/test_capacity.py`.
- Exact balances and movement reconciliation: `tests/test_report_reconciliation.py`.
- Reorder level on batches and the stock report, including "not set" vs false: `tests/test_catalog_orders.py::test_stock_report_exposes_grouping_and_reorder_flag`.
- The stock screen's Low chip was read in `static/js/app.js` (`renderStock`) and syntax-checked; it was not re-exercised in a browser after migration `0024`.
