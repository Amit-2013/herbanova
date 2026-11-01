# Frontend–Backend Field Mapping

**Project:** Herbanova Business Control
**Stage:** 3 — audit registers
**Date:** 31 October 2026
**Scope:** every write workflow and every read surface reachable from the browser, traced from the HTML/JavaScript control through the HTTP request, the Pydantic schema, the service function, the database column, the permission gate, and the report that consumes it.

**Evidence basis:** `static/index.html`, `static/js/app.js` (3,914 lines), the FastAPI application object (introspected, 161 `/api/` routes), every request schema in `app/api/`, the services in `app/services/`, the models in `app/models/`, and read-only catalogue queries against the development database. **No application code, configuration, or business data was changed to produce this document.**

## How to read this document

Every row is a field that actually crosses the browser boundary. The status column uses the same vocabulary as the other Stage 3 registers:

| Status | Meaning |
|---|---|
| **VERIFIED** | The control, the request field, the schema field, the stored column and the permission were all read in source, and an executable test asserts the workflow or the value survives the round trip. |
| **VERIFIED (code)** | All six links were read in source; the workflow is exercised only indirectly by the test suite. |
| **PARTIAL** | The field crosses the boundary but a known limitation prevents a complete round trip (for example, it can be set but not cleared, or the UI never offers it). |
| **UNVERIFIED** | One of the links could not be established from source. |

Abbreviations: **UI** = control in `static/index.html` / `static/js/app.js`; **API** = route; **Schema** = Pydantic request model; **Store** = SQLAlchemy model and column; **Perm** = the permission the server actually enforces. Where the server enforces a role as well as a permission, both are stated.

The browser talks to the API through one helper, `api()` at `static/js/app.js:36-46`: JSON body, `credentials: "same-origin"`, a 401 while signed in sends the user back to the login screen. Every field below is therefore a JSON member unless stated otherwise (print and export use query strings; file downloads use `fetch`).

---

## 0. Coverage at a glance

| Surface | Count | Source |
|---|---|---|
| API routes under `/api/` | 161 | introspected from `app.main:app` |
| Browser views (`#/…`) | 20 | `static/js/app.js:200-208` |
| Report catalogue entries | 25 | `app/services/reports.py` `CATALOG` |
| Request schemas with a JSON body | 64 | `app/api/**` |
| Database tables | 50 | `docs/DATABASE_TABLE_COLUMN_REGISTER.md` |

The SPA is a single page with hash routes. Visibility of a view is decided in the browser by `VIEW_PERM` (`static/js/app.js:205-208`), but authorisation is always re-checked on the server by `require(perm)` / `require_admin(perm)` (`app/core/rbac.py:74-100`). Hiding a button is therefore a convenience, never a control.

---

## 1. Authentication and session

| UI control | UI source | API | Schema | Effect | Perm |
|---|---|---|---|---|---|
| `#u`, `#p`, Sign in | `app.js:112-119` | `POST /api/auth/login` | `Login{username, password}` | Sets HttpOnly `session` cookie; returns identity | none (rate-limited) |
| Session restore on load | `app.js:120-124` | `GET /api/auth/me` | — | Returns user, role, permissions, `must_change_password` | any signed-in user |
| Sign out | `app.js:3125` | `POST /api/auth/logout` | — | Clears cookie | any signed-in user |
| Forced change form (`#changePwForm`) | `index.html:43-59`; `app.js:116-146` | `POST /api/auth/change-password` | `ChangePassword{current_password, new_password}` | Blocking screen shown when `me.must_change_password`; on success re-hashes, bumps `token_version`, issues a new cookie, enters the shell | any signed-in user with a temporary password |

**What is stored:** `users.username`, `users.password_hash` (Argon2id), `users.role_id`, `users.employee_id`, `users.must_change_password`, `users.token_version`, `users.failed_attempts`, `users.locked_until`, `users.last_login_at` (`app/models/core.py`).

**Login behaviour:** case-insensitive usernames, lockout after repeated failures, the per-IP rate limit, the forced change on the next request and session revocation through `token_version` are VERIFIED (code) in `app/api/auth.py` and `app/core/rbac.py`. The forced-change branch, including the block, the policy checks and token revocation, is now covered by `tests/test_authz.py::test_forced_password_change_gates_data_and_revokes_the_old_token`; the basic boot path is covered by `tests/test_smoke.py:1`.

**M-01 (High) — FIXED 31 October 2026.** The server blocks every endpoint except `/api/auth/me`, `/api/auth/logout` and `/api/auth/change-password` while `must_change_password` is true (`app/core/rbac.py:27-29, 74-100`). The SPA now shows a blocking **Set a new password** screen (`index.html:43-59`; `showPasswordChange` at `static/js/app.js:116-125`) whenever the identity reports `must_change_password`, hides the shell and login form, validates the policy and confirmation in the browser, posts to the endpoint, and only then enters the shell with the fresh identity (`app.js:126-146`). Sign out remains available from the screen. Verified in an in-app browser against a throwaway database: sign-in with a temporary password showed the screen, a mismatched confirmation was rejected locally, the correct change loaded the shell, and the spurious 403 banner formerly caused by loading the approvals queue without `approval:read` was removed (`app.js:170-175, 222`).

---

## 2. Dashboard and module register

**UI route:** `#/dash` (`renderDash`, `app.js:423-472`; insight cards, `app.js:887-996`). **Phase 2 metric definitions, sources, permissions and refresh rules:** `docs/DASHBOARD_FEATURES.md`.

| UI element | API | Permission | Content |
|---|---|---|---|
| Period 7D/30D/90D, all tiles and panels | `GET /api/dashboard?range=` | `require_login`, then per section | Payload as at §2.1; `range` outside 7/30/90 → 422. Sections the role cannot read are `null`, never `0`. |
| Stock KPIs, expiry watch, warehouses, open POs | same payload | `stock:read` | `stock`, `purchase_orders`, `stock_by_warehouse`, `expiry_watch`, `open_pos`, stock KPI tiles |
| Sales KPIs, top products, category panel | same payload | `sales:read` | `orders_ready`, `top_products`, `category_sales`; sales side of `sales_vs_purchases` is masked server-side without it |
| Receivables ageing | same payload | `accounts:read` | `receivables_ageing`, from `ledger.ageing_rows` (same function as the report) |
| Approvals tile and list | same payload | `approval:read` | `approvals`, `approvals_waiting`; HR requests are further limited to the caller's own |
| Follow-ups tile | same payload | `lead:read` | `leads`, `followups_overdue` |
| Active products tile | same payload | `product:read` | `active_products` |
| Recent activity | same payload | `audit:read` | `recent_activity` (latest 8, exact total) |
| Expiry filter and detail drawer | `GET /api/dashboard/expiry?bucket=&page=&page_size=` | `stock:read` | Paged batches in a disjoint bucket; row detail is rendered from the same fields |
| Global search palette (Ctrl/⌘ K) | `GET /api/dashboard/search?q=` | signed in; groups gated | Products, customers, sales orders, invoices, purchase orders, suppliers, leads; max 5 rows per visible group |
| Activity feed (palette/audit) | `GET /api/dashboard/activity?limit=` | `audit:read` | Audit rows |
| Module register | `GET /api/modules` | `require_login` | Declared modules, groups and derived counts (`app/api/modules.py:17`) |
| Health badge | `GET /api/health` | none | Liveness and schema revision |

### 2.1 Dashboard payload fields

| Payload member | Shape / meaning | Gate |
|---|---|---|
| `as_of`, `range`, `from`, `to`, `generated_at` | Date, period length and UTC build time | always |
| `kpis[]` | `{key,label,value,href,note,trend,trend_points,trend_note}` — 8 tiles; `trend` is null where no history is stored | per tile (see DASHBOARD_FEATURES §4) |
| `attention[]` | `{key,label,count,units,amount,severity,available,gap,note,href}`; `available:false` marks a data gap | per rule |
| `sales_vs_purchases` | `{series[{date,sales,purchases}],sales_total,purchases_total,sales_change,purchases_change,previous_from,previous_to,sales_visible,purchases_visible,note}`; hidden side is `null` | `sales:read` and/or `stock:read` |
| `receivables_ageing` | `{buckets[{key,label,amount,count}],total,count,as_of,note}` | `accounts:read` |
| `stock_by_warehouse[]` | `{id,name,batches,units,capacity:null,share:null,gap:"GAP-D03"}` | `stock:read` |
| `expiry_watch` | `{expired,lt30,lt90,total,rows[],shown,shown_of,buckets[],note}`; rows carry `action`/`tone`/`value:null`/`value_gap` | `stock:read` |
| `open_pos` | `{count,rows[{po_number,supplier,value,remaining_units,ordered_units,received_units,pct_received,receipt_count}],shown,note}` | `stock:read` |
| `approvals` | `{count,rows[ApprovalOut],shown,note}` | `approval:read` |
| `top_products` | `{rows[{product_id,sku,name,qty,revenue,previous_revenue,change}],previous_from,previous_to,note}` | `sales:read` |
| `category_sales` | `{available:false,gap:"GAP-D01",note}` | `sales:read` |
| `recent_activity` | `{rows[{id,at,actor,action,record,changes}],shown,total}` | `audit:read` |
| `insights.pipeline` | `{sales:{rows[{status,label,count,value}],total,dispatch:{measured,average_days,note}},leads:{rows[{status,label,count}],total}}`; each side `null` without its permission | `sales:read` / `lead:read` |
| `insights.customers` | `{from,to,top[{distributor_id,name,invoices,revenue}],outstanding[{distributor_id,name,outstanding,invoices}],outstanding_total,credit[{distributor_id,name,credit_limit,exposure,available,pct_used}],note}`; `outstanding` is `null` without `accounts:read` | `sales:read` and/or `accounts:read` |
| `insights.purchasing` | `{as_of,open_count,no_receipt,partial,rows[{key,label,count,value}],note}` for PO age buckets | `stock:read` |
| `insights.corrections` | `{from,to,credit_notes{label,count,value,shown,rows[]},debit_notes{…},post_billing{count,pending,shown,rows[]},note}` | `sales:read` |
| `insights.hr` | `{date,headcount,marked,not_marked,attendance[{status,label,count}],leave_pending,od_pending,note}` | `hr:read` |
| `health` | `{modules{working,counted,percent},schema{current,head,at_head},backup{status,gap,note},alerts{configured,note}}` | signed in |
| legacy `stock`, `purchase_orders`, `active_products`, `orders_ready`, `approvals_waiting`, `leads`, `warehouse_count` | unchanged definitions for older callers | as before |

The dashboard is read-only. It adds no write path and composes no new figures: stock, receivables and payables come from the same services as the reports (section 13), and approvals decisions still go through `POST /api/approvals/{id}/decide` (section 10). **Status: VERIFIED** for aggregates, periods, masking and reconciliation by `tests/test_dashboard.py` and `tests/test_dashboard_phase2.py`; the browser check is recorded in `docs/DASHBOARD_FEATURES.md` §9.

---

## 3. Leads and follow-ups

**UI routes:** `#/leads`, `#/lost`, `#/followups` — all require `lead:read` (`VIEW_PERM`, `app.js:205-206`).

### 3.1 Create a lead (`app.js:2120-2156`)

| UI field | Request field | Schema (`app/api/leads.py`) | Store (`leads`) | Notes |
|---|---|---|---|---|
| Contact name | `name` | `LeadIn.name` (min 2) | `name` | required |
| Company | `company` | `company: str \| None` | `company` | |
| Phone | `phone` | `phone: str \| None` | `phone` | phone **or** email required by the handler |
| Email | `email` | `email: str \| None` | `email` | |
| Source | `source` | `source: Literal[...]` | `source` | dropdown of known sources |
| Owner | `owner_id` | `int \| None` | `owner_id` | only shown when the role may read owners |
| First follow-up | `next_follow_up` | `date` | `next_follow_up` | required by the form |
| First note | `note` | `str \| None` | activity row | written as the first `lead_activities` entry |

API: `POST /api/leads` — permission `lead:write`. The server assigns `lead_no` from the document sequence and writes an audit row. No monetary figure is involved.

### 3.2 Subsequent actions

| UI action | API | Schema | Store | Perm |
|---|---|---|---|---|
| Edit details | `PATCH /api/leads/{id}` | `LeadEditIn{name, company, phone, email, source}` | `leads` | `lead:write` |
| Add activity | `POST /api/leads/{id}/activities` | `ActivityIn{kind, summary, next_follow_up, clear_follow_up}` | `lead_activities` | `lead:write` |
| Change status | `POST /api/leads/{id}/status` | `StatusIn{status, reason, next_follow_up}` | `leads.status`, `lead_activities` | `lead:write` |
| Reschedule follow-up | `POST /api/leads/{id}/follow-up` | `FollowUpIn{next_follow_up, reason}` | `leads.next_follow_up` | `lead:write` |
| Reassign owner | `POST /api/leads/{id}/owner` | `OwnerIn{owner_id, reason}` | `leads.owner_id` | `lead:assign` |
| Read one lead | `GET /api/leads/{id}` | — | — | `lead:read` |
| Owner choices | `GET /api/leads/owners` | — | — | `lead:read` |

**Reports:** `leads` (Lead Register) uses `leads` + `lead_activities`, filters by period, and is one of the 17 reports whose reconciliation check is row-count only (section 13.3).

**Status:** VERIFIED (code) only. No test in `tests/` calls `/api/leads`; the schemas, handlers and audit calls were read, but the lead workflow is not exercised by the suite.

---

## 4. Distributors and customers

`#/customers` is the single master screen, titled **Customers and distributors** (`v-customers` in `static/index.html`, `renderCustomers()` in `app.js`). The two former views read the same rows from `state.dists`, loaded from `/api/distributors`; there is one table, one search box and one status filter. `#/distributors` is kept as an alias in `route()` so the Overview drill-down, bookmarks and older links open the same screen. The merged table shows Code, name with territory and GSTIN, credit limit, in use (with a meter), available, status and actions; the actions are `Open` (`distributor:write`), `New order` (`sales:write`) and `Change limit` (`credit:manage`), so a reader without those rights sees no button that the server would refuse.

### 4.1 Create / edit (`app.js:1977-2063`)

| UI field | Request field | Schema (`app/api/distributors.py`) | Store (`distributors`) | Notes |
|---|---|---|---|---|
| Code (new only) | `code` | `DistributorIn.code` | `code` | unique; read-only after creation |
| Name | `name` | `name` | `name` | required, min 2 |
| Territory | `territory` | `territory` | `territory` | required, min 2 |
| Credit limit (new only) | `credit_limit` | `Decimal \| None` | `credit_limit` | later changes go through the credit-limit endpoint |
| Registration | `registration_type` | `str` | `registration_type` | `regular` / `composition` / `unregistered` |
| GSTIN | `gstin` | `str \| None`, upper-cased | `gstin` | central check-digit validation |
| PAN | `pan` | `str \| None`, upper-cased | `pan` | derived from GSTIN when blank |
| State code | `state_code` | `str \| None` | `state_code` | derived from GSTIN for a registered party |
| Billing / shipping address | `billing_address`, `shipping_address` | `str \| None` | same | |
| Contact person / phone / email | `contact_person`, `phone`, `email` | `str \| None` | same | |
| Group name | `group_name` | `str \| None` | `group_name` | used by group-scoped discount slabs |
| Payment terms | `payment_terms_days` | `int \| None` | `payment_terms_days` | |
| Status | `status` | `str` | `status` | draft / pending verification / active / blocked |

API: `POST /api/distributors` with `distributor:write`; `PATCH /api/distributors/{id}` with the same permission. The edit form sends **only changed fields** (`app.js:2033-2039`), so an untouched field is not overwritten with a null.

**Tax identity normalisation:** the same `identity_problems()` / `normalize_identity()` used by suppliers and the company profile (`app/services/tax_ids.py:103-166`) validates GSTIN, PAN and state; an unregistered buyer may omit the state at creation, but the tax engine refuses to quote without a place of supply.

### 4.2 Credit limit (`app.js:2050-2077`)

| UI field | Request field | Schema | Store | Perm |
|---|---|---|---|---|
| New limit | `credit_limit` | `CreditLimitIn{credit_limit, reason}` | `distributors.credit_limit` | `credit:manage` |
| Reason | `reason` | same | `audit_log` | same |

API: `PATCH /api/distributors/{id}/credit-limit`. The endpoint changes the limit and writes the old value, the new value, the actor and the reason in one transaction; it does not recompute orders. Exposure is derived on read (`app/services/sales.py:15-40`). The UI note that "payments are not tracked yet" is accurate for exposure: receipts are recorded in Accounting but are not subtracted from credit exposure (see F-20 in the formula register and Appendix A).

**Reports:** `distributors` (Distributor Register), snapshot, `sales:read`; **row-count-only reconciliation**.

---

## 5. Products, warehouses and inventory

### 5.1 Product (`app.js:911-930` form, `1236-1250` save)

| UI field | Request field | Schema (`app/api/products.py`) | Store (`products`) | Notes |
|---|---|---|---|---|
| HSN | `hsn` | `hsn` (4–8 digits) | `hsn` | read-only after creation |
| SKU | `sku` | `sku` | `sku` | read-only after creation |
| Name | `name` | `name` | `name` | |
| Pack size | `pack_size` (control name `pack`) | `pack_size` | `pack_size` | |
| MRP | `mrp` | `Decimal` ≥ 0 | `mrp` | |
| Status (edit) | `status` | `active` / `discontinued` | `status` | |
| **Unit (UQC)** | **never sent** | `uqc: str \| None`, max 3 | `uqc` | **Mismatch M-03** |

API: `POST /api/products` (`product:write`), `PATCH /api/products/{id}` (`product:write`). The server uppercases a supplied UQC and stores null when blank (`app/api/products.py:40-42`); the invoice copies `products.uqc` onto the line at issue time (`app/services/invoice.py:114`).

**Mismatch M-03 (Medium).** The API and the schema accept a three-character UQC, but the browser form has no control and `saveProduct()` never sends it. Issued invoice lines therefore store null and the printed tax invoice shows "—" for the unit (`app/services/document_pdf.py:521`), which is a GST-document defect for goods sold by count or weight.

### 5.2 Warehouse (`app.js:1255-1272`)

| UI field | Request field | Schema | Store | Perm |
|---|---|---|---|---|
| Name | `name` | `WarehouseIn{name}` | `warehouses.name` | `stock:write` |

API: `POST /api/warehouses`. Warehouses cannot be renamed or deleted from the UI; the API exposes no update or delete route either.

### 5.3 Inventory views (read-only)

| UI | API | Perm | Source |
|---|---|---|---|
| Batch stock, filters | `GET /api/inventory/batches` | `stock:read` | `batches` |
| Movement ledger (limit 200) | `GET /api/inventory/movements?limit=200` | `stock:read` | `stock_movements` |
| Warehouse filter | `GET /api/warehouses` | `stock:read` | `warehouses` |

**Reports:** `stock` (Stock on Hand) is snapshot, `stock:read`, and carries a real reconciliation: the sum of `batches.on_hand` is compared with the net of `stock_movements` (`tests/test_report_reconciliation.py:118-124`).

---

## 6. Purchase orders and goods receipts

### 6.1 Create a purchase order (`app.js:1287-1346`)

| UI field | Request field | Schema (`app/api/purchase_orders.py`) | Store | Notes |
|---|---|---|---|---|
| Supplier | `supplier_id` | `POIn.supplier_id` | `purchase_orders.supplier_id` | required |
| PO number | `po_number` (only if non-blank) | `str \| None`, 3–40 | `po_number` | otherwise generated |
| Line product | `lines[].sku` | `POLineIn.sku` | `purchase_order_lines.sku` | upper-cased; unique per order |
| Line quantity | `lines[].qty` | `Decimal` > 0 | `qty` | |
| Unit cost | `lines[].unit_cost` | `Decimal \| None` ≥ 0 | `unit_cost` | |
| Reason cost is blank | `lines[].rate_remark` | `str \| None` (known code or label) | `rate_remark` | required when `unit_cost` is null |

API: `POST /api/purchase-orders` (`stock:write`). A model validator enforces "cost or remark"; a list validator refuses duplicate SKUs (`app/api/purchase_orders.py:42-90`). Neither the UI nor the API accepts a tax split on a purchase line: purchases record cost, not input GST (Appendix A, "No input GST / ITC", of the formula register).

### 6.2 Receive goods (`app.js:1403-1438`)

| UI field | Request field | Schema (`ReceiveIn`) | Store | Notes |
|---|---|---|---|---|
| Warehouse | `warehouse_id` | `int` | `goods_receipts.warehouse_id` | required |
| Ownership | `owner` | `HERBANOVA` / `MANUFACTURER` | `owner` | |
| Delivery note | `delivery_note` (only if non-blank) | `str \| None` | `delivery_note` | |
| Line SKU | `lines[].sku` | `str` | `goods_receipt_lines.sku` | |
| Batch number | `lines[].batch_no` | `str` | `batch_no` | required |
| Quantity | `lines[].qty` | `Decimal` > 0 | `qty` | |
| Expiry | `lines[].expiry` (only if set) | `date \| None` | `expiry` | |

API: `POST /api/purchase-orders/{id}/receive` (`stock:write`). The service creates a GRN, adds batches, writes `stock_movements`, and changes the order to `partially_received` or `received` (`app/api/purchase_orders.py:305+`). Duplicate `(sku, batch_no)` pairs inside one receipt are refused.

**Reports:** `purchases` (Purchase Orders) and `goods_receipts` (Goods Receipt Register) — both **row-count-only reconciliation**.

---

## 7. Sales orders

**UI:** `#/sales`; new order also reachable from a distributor row. Requires `sales:read` to view, `sales:write` to create.

### 7.1 Create a draft (`app.js:1552-1605`)

| UI field | Request field | Schema (`app/api/sales_orders.py`) | Store | Notes |
|---|---|---|---|---|
| Distributor | `distributor_id` | `SOIn.distributor_id` | `sales_orders.distributor_id` | required |
| Line product | `lines[].sku` | `SOLineIn.sku` | `sales_order_lines.sku` | upper-cased; unique |
| Line quantity | `lines[].qty` | `Decimal` > 0, 3 dp, **whole number** | `qty` | model validator refuses fractions of a pack |
| Unit price | `lines[].unit_price` (only if non-blank) | `Decimal \| None` ≥ 0 | `unit_price` | null means "use MRP" at issue |

API: `POST /api/sales-orders` (`sales:write`). The service freezes the product name, HSN, pack size and MRP on the line, and computes tax through the same `line_tax()` used by invoices (F-05, F-07–F-10). A price above MRP is refused; a discount over the configured threshold creates an approval (section 10).

### 7.2 Order actions

| UI action | API | Schema | Perm | Effect |
|---|---|---|---|---|
| Preview tax | `GET /api/sales-orders/{id}/tax-preview` | — | `sales:read` | Recomputes heads without writing |
| Submit | `POST /api/sales-orders/{id}/submit` | — | `sales:write` | Draft → pending approval or approved |
| Cancel | `POST /api/sales-orders/{id}/cancel` | `ReasonIn{reason}` | `sales:write` | Allowed only before dispatch |
| Dispatch | `POST /api/sales-orders/{id}/dispatch` | `DispatchIn{warehouse_id}` | `dispatch:write` | FEFO issue, invoice issue, stock movements |

The submit response carries `status` and, when held, `approval{id, reasons[]}`; the UI opens the approval drawer or shows "Awaiting approval" (`app.js:1705-1720`). Dispatch selects a warehouse from `state.warehouses` and is refused when stock is insufficient (F-24, F-30).

**Reports:** `sales` (Sales Orders), period, `sales:read` — **row-count-only reconciliation**.

---

## 8. Dispatch, invoices and post-billing movement

An invoice is **issued by the dispatch transaction**, not by a form. The billing view (`#/billing`) is therefore read-mostly: list, open, print, cancel, note, and (Administrator only) amend movement details.

### 8.1 Invoice list and detail

| UI element | API | Perm | Fields shown |
|---|---|---|---|
| Invoice register | `GET /api/invoices` | `sales:read` | number, FY, date, buyer, GSTIN, grand total, credited total, status |
| Invoice detail | `GET /api/invoices/{id}` | `sales:read` | line product, SKU, HSN, UQC, quantity, price, taxable, CGST/SGST/IGST, total; movement fields |
| Expiry history | `GET /api/invoices/expiry` | `sales:read` | batch expiry at issue |
| Print | `POST /api/print/invoice/{id}?copy=ORIGINAL` | `print:document` | server-rendered PDF |

The detail screen deliberately exposes `PUT /api/invoices/{id}` and `DELETE /api/invoices/{id}` as **405 immutability traps** (`app/api/invoices.py:389-397`), not as editing routes. Cancellation is the only removal, and it keeps the number (`POST /api/invoices/{id}/cancel`, `invoice:cancel`, `CancelIn{reason}`).

### 8.2 Post-billing movement (Administrator)

| UI field | Request field | Schema (`MovementIn`) | Store | Notes |
|---|---|---|---|---|
| Delivery challan | `delivery_challan_number` | `str \| None` | `invoices.delivery_challan_number` | |
| Vehicle | `vehicle_number` | `str \| None` | `vehicle_number` | |
| Transporter | `transporter_name` | `str \| None` | `transporter_name` | |
| E-way bill number | `eway_bill_number` | `str \| None` | `eway_bill_number` | number and date must be supplied together |
| E-way bill date | `eway_bill_date` | `date \| None` | `eway_bill_date` | |
| Reason | `reason` | `str`, 3–300 | `audit_log` | mandatory |

API: `PATCH /api/invoices/{id}/movement` (`require_admin("invoice:edit_post_billing")`). Only fields present in the JSON body are compared, and only non-financial fields are in `AMENDABLE` (`app/api/invoices.py:329-355`). Amounts and tax never change here.

**Mismatch M-05 (Low).** `saveInvoiceMovement()` only appends a field when the input is non-empty (`app.js:1883-1892`). Because the backend applies exactly the fields present in the body, the browser can set or change a movement field but **cannot clear** one (sending an empty string would normalise to null). The same applies to the e-way bill date.

### 8.3 Non-Administrator request

The UI offers `delivery_challan_number` and `vehicle_number` only, posts to `POST /api/approvals/post-billing/{invoice_id}` with `AmendRequestIn{reason, changes}`, and needs `invoice:write`. The server filters the requested keys through `AMENDABLE` and stores the request (`app/api/approvals.py:254+`). An Administrator decides it with `POST /api/approvals/{id}/decide`.

**Reports:** `invoices` (Sales Invoice Register), period, `sales:read` — source count and sum checks are real (section 13.2).

---

## 9. Credit and debit notes

**UI:** invoice detail drawer, `app.js:1759-1935`.

| UI field | Credit note request | Debit note request | Schema | Store |
|---|---|---|---|---|
| Invoice (from drawer) | `invoice_id` | `invoice_id` | `int` | `credit_notes.invoice_id` / `debit_notes.invoice_id` |
| Per line quantity | `lines[].invoice_line_id`, `lines[].qty` | same | `NoteLineIn{invoice_line_id, qty > 0}` | `*_note_lines` |
| Reason | `reason` | `reason` | `str`, 1–300 | `reason` |
| Return to stock warehouse | `warehouse_id` (credit only) | — | `int \| None` | `warehouse_id` |
| Note date | **never sent** | **never sent** | `note_date: date \| None` | `note_date` (server uses today) |

APIs: `POST /api/credit-notes` (`note:write`), `POST /api/debit-notes` (`note:write`). The service refuses a quantity above what remains creditable on the invoice line, and a return-to-stock credit writes positive `stock_movements` back to the original batches (F-37–F-38).

**Mismatch M-04 (Low).** Both schemas accept `note_date`, but the browser never sends it. A note raised late for an earlier correction is therefore dated the day it is entered, which misplaces it in the GST period. The server has no backdating guard on this field beyond the schema, so the only current control is the absence of a UI control.

**Reports:** credit and debit notes feed `gst_register`, `trial_balance`, `receivables` and `receivables_ageing`; each carries independent checks.

---

## 10. Approvals

**UI:** `#/approvals`, `approval:read`; decision buttons are additionally gated by `approval:decide`, and the server narrows sales/post-billing decisions to the literal Administrator role.

| UI action | API | Schema | Server rule | Store |
|---|---|---|---|---|
| Queue, filters | `GET /api/approvals` | — | `approval:read` | `approval_requests` |
| Approve / reject | `POST /api/approvals/{id}/decide` | `DecisionIn{decision, reason}` | `approval:read`, then: a sales order needs `approval:decide` or the Administrator, a credit-limit reason needs the Administrator, a post-billing edit needs the Administrator; nobody may decide their own request | `status`, `decided_by`, `decided_at`, `decision_reason` |
| Decide supplier bank change | `POST /api/suppliers/bank-changes/{id}/decide` | `BankDecisionIn{decision, reason}` | `approval:decide` | `approval_requests`, `suppliers` bank fields |

**Verified by tests:** `tests/test_approvals.py:1-107` proves the sales desk and inventory roles cannot decide a credit-limit request, the Administrator cannot decide one they raised, a request is decided once, and only permitted post-billing fields are applied (`grand_total` is dropped).

**Order of checks (VERIFIED, code):** the handler dispatches by `record_type`, then checks status = pending, then the role rule (Administrator for a credit-limit reason or post-billing; `approval:decide` or Administrator for a sales order), then the segregation rule (requester or order creator), then applies the effect and audits it (`app/api/approvals.py:177-253`).

---

## 11. Suppliers and bank-detail changes

### 11.1 Create a supplier (`app.js:1129-1168`)

| UI field | Request field | Schema (`app/api/suppliers.py`) | Store (`suppliers`) |
|---|---|---|---|
| Code | `code` | `SupplierIn.code` | `code` |
| Name | `name` | `name` | `name` |
| Type | `kind` | `supplier` / `manufacturer` / `both` | `kind` |
| Registration | `registration_type` | `regular` / `composition` / `unregistered` | `registration_type` |
| GSTIN | `gstin` (only if non-blank) | `str \| None` | `gstin` |
| PAN | `pan` (only if non-blank) | `str \| None` | `pan` |
| State code | `state_code` (only if non-blank) | `str \| None` | `state_code` |
| Payment terms | `payment_terms_days` | `int` | `payment_terms_days` |

API: `POST /api/suppliers` (`supplier:write`); edit `PATCH /api/suppliers/{id}` (`supplier:write`); block/unblock `PATCH` with `status` (same permission). A legacy free-text supplier carried from an older purchase order is flagged `needs_completion` until its tax identity is filled.

### 11.2 Bank-detail change (`app.js:1198-1232`)

| UI field | Request field | Schema (`BankIn`) | Store | Perm |
|---|---|---|---|---|
| Bank name | `bank_name` | `str` | `approval_requests.detail` until approved | `supplier:bank` |
| Account number | `bank_account_no` | `str` | same | same |
| IFSC | `bank_ifsc` | `str`, upper-cased by the UI | same | same |
| Account holder | `bank_holder` | `str` | same | same |
| Decision reason | `reason` | `BankDecisionIn.reason` | `approval_requests` | `approval:decide` |

A bank change is never written directly: it creates an approval request, and only a different person with `approval:decide` can apply it. The server rule was read in `app/api/suppliers.py` and the shared decision service; **no test in `tests/` exercises the supplier bank-change workflow**, so this row is VERIFIED (code), not test-verified.

**Reports:** `suppliers` (Supplier Register) — **row-count-only reconciliation**.

---

## 12. Accounting and finance

**UI:** `#/accounts`, `accounts:read`; writing needs `accounts:write`.

| UI field | Request field | Schema (`EntryIn`) | Store (`payments`) |
|---|---|---|---|
| Kind (drawer mode) | `kind` | `receipt` / `payment` | `kind` |
| Against invoice | `invoice_id` | `int \| None` | `invoice_id` |
| Against order | `purchase_order_id` | `int \| None` | `purchase_order_id` |
| Party | **never sent** | `distributor_id` / `supplier_id` | `distributor_id` / `supplier_id` |
| Amount | `amount` | `Decimal` > 0, 2 dp | `amount` |
| Date | `paid_on` | `date` | `paid_on` |
| Mode | `mode` | `bank/cash/upi/cheque/neft/other` | `mode` |
| Reference | `reference` | `str \| None`, 60 | `reference` |
| Note | `notes` | `str \| None`, 300 | `notes` |

API: `POST /api/accounts/payments` (`accounts:write`). Reads: outstanding (`/outstanding`), ageing (`/ageing`), distributor and supplier ledgers, trial balance, GST register, and the last 500 entries (`/payments`).

**Mismatch M-02 (Medium).** The select offers an empty first option labelled "Not allocated yet" (`app.js:533`), but the server requires an invoice (to derive the distributor) or a purchase order (to derive the supplier): `app/api/accounts.py:124-131` and `:154-160` return 422 otherwise. The browser never sends `distributor_id` or `supplier_id`, so choosing "Not allocated yet" always fails. Either the option should be removed and allocation made mandatory, or the drawer should offer a party selector for unallocated money.

**Immutability:** no update or delete route exists for a payment. A wrong entry is corrected by recording the opposite entry with a note (`app/api/accounts.py:1-16`). This is deliberate and matches F-43 and F-74.

**Reports:** `receivables`, `receivables_ageing`, `payables`, `trial_balance`, `gst_register` — all five carry independent checks (section 13.2).

---

## 13. Reports and exports

**UI:** `#/reports`, permission-filtered catalogue. The catalogue itself is computed on the server: a role only receives reports whose data permission it holds (`app/api/reports.py:107-114`).

| UI element | API | Permission | Behaviour |
|---|---|---|---|
| Catalogue | `GET /api/reports` | any signed-in user | Returns only reports the role may open; `can_export` reflects `report:export` |
| Run report | `GET /api/reports/{key}?from=&to=&page=&page_size=&sort=&direction=&employee_id=&department=&branch_id=` | the report's data permission, checked in `_open()` | Builds from documents, then sorts and pages in memory |
| Download CSV / XLSX / PDF | `GET /api/reports/{key}/export?format=&table=&from=&to=` | `report:export` **and** the report's data permission | Streams a file and writes `report.export` to the audit log with format, table, row count and reconciled flag |

### 13.1 Report catalogue (25)

| Key | Title | Kind | Data permission | Primary table |
|---|---|---|---|---|
| `stock` | Stock on Hand | snapshot | `stock:read` | `stock` |
| `sales` | Sales Orders | period | `sales:read` | `sales_orders` |
| `invoices` | Sales Invoice Register | period | `sales:read` | `invoices` |
| `leads` | Lead Register | period | `sales:read` | `leads` |
| `purchases` | Purchase Orders | period | `stock:read` | `purchase_orders` |
| `goods_receipts` | Goods Receipt Register | period | `stock:read` | `goods_receipts` |
| `suppliers` | Supplier Register | snapshot | `supplier:read` | `suppliers` |
| `distributors` | Distributor Register | snapshot | `sales:read` | `distributors` |
| `receivables` | Receivables | snapshot | `accounts:read` | `receivables` |
| `receivables_ageing` | Receivables Ageing | snapshot | `accounts:read` | `receivables_ageing` |
| `payables` | Payables | snapshot | `accounts:read` | `payables` |
| `gst_register` | GST Outward Register | period | `tax:read` | `gst_register` |
| `trial_balance` | Trial Balance | snapshot | `accounts:read` | `trial_balance` |
| `hr_employee_master` | Employee Master | snapshot | `hr:reports` | `employees` |
| `hr_attendance` | Attendance Register | period | `hr:reports` | `attendance` |
| `hr_leave` | Leave Register | period | `hr:reports` | `leave` |
| `hr_od` | On Duty Register | period | `hr:reports` | `od_requests` |
| `hr_payroll` | Payroll Register | period | `hr:reports` | `payroll` |
| `hr_approvals` | Approval Register | period | `hr:reports` | `approvals` |
| `hr_joining_exit` | Joining and Exit Register | period | `hr:reports` | `employees` |
| `hr_late_arrival` | Late Arrival Register | period | `hr:reports` | `late_arrivals` |
| `hr_missing_punch` | Missing Punch Register | period | `hr:reports` | `missing_punches` |
| `hr_leave_balance` | Leave Balances | period | `hr:reports` | `leave_balances` |
| `hr_payroll_deductions` | Payroll Deductions | period | `hr:reports` | `payroll_deductions` |
| `hr_approval_turnaround` | Approval Turnaround | period | `hr:reports` | `approval_turnaround` |

Filters are validated per report: a filter a report cannot use is refused with 422 rather than silently returning unfiltered data (`_filters()`, `app/api/reports.py:90-105`). Current filter keys: employee/department/branch on the HR registers; none on the financial registers.

### 13.2 Reports with independent reconciliation (8)

| Report | Check | Independent source |
|---|---|---|
| `stock` | batch quantity vs stock-movement ledger | `_stock_checks` |
| `receivables` | row count and outstanding total | `_source_receivables` (grouped SQL) |
| `receivables_ageing` | ageing total and row count | recomputed buckets |
| `payables` | received value and paid total | GRN × PO line cost |
| `trial_balance` | balanced, row debits, row credits | document postings |
| `gst_register` | six checks against invoice/note sums | `_source_gst` (SQL sums) |
| `sales` | source count and value | `_source_sales` |
| `invoices` | source count and totals | `_source_invoices` |

### 13.3 Reports with row-count-only reconciliation (17)

`leads`, `purchases`, `goods_receipts`, `suppliers`, `distributors`, and the twelve `hr_*` registers. Their `checks[]` compares the built row count with the model row count; it does **not** independently recompute money or dates. This is recorded as an open item in `docs/FORMULA_RECONCILIATION_TESTS.md` and must not be read as proof of correctness for those reports.

### 13.4 Paging and sorting

`get_report()` builds the whole report, then sorts and slices each table in memory (`app/api/reports.py:118-132`). `total_rows` is the full count, `page_size` is capped at 500, and the UI requests page 1 with the default 100. This is functionally correct but **does not scale**: a large register is fully materialised before paging (R-02 in the remediation record, M-10 below).

---

## 14. Human resources

**UI:** `#/hr`. A role with only `hr:attendance_self` sees its own day; a role with `hr:read` sees the team. The server enforces the same distinction inside `/api/hr/attendance` (`app/api/hr.py:542-560`).

### 14.1 Employee master

Two APIs exist:

- `POST/PATCH /api/employees` — the legacy, narrow employee record used by the Users page; `EmployeeIn{code, full_name, department, designation, phone, email, joining_date, manager_id}`.
- `POST/PATCH /api/hr/employees` — the full HR record. `EmployeeIn` accepts 27 fields: the eight above plus `branch_id, office_id, department_id, shift_id, hr_admin_id, employment_type, work_schedule, date_of_exit, address, emergency_name, emergency_phone, bank_name, bank_account_no, bank_ifsc, pan, uan, esi_no, attendance_policy, leave_policy`; `EmployeePatch` adds `status` (`app/api/hr.py:83-139`).

The HR screen (`app.js:646-685`) sends only: `code` (create), `full_name`, `department`, `designation`, `phone`, `email`, `joining_date`, `employment_type`, `branch_id`, `office_id`, `shift_id`, `status`.

**Mismatch M-07 (Low).** The HR screen cannot capture bank details, PAN, UAN, ESI number, emergency contacts, address, exit date, `department_id`, `hr_admin_id`, work schedule or the attendance/leave policies, although the API accepts all of them. Those fields can only be set through the API or a data load.

**Reports:** `hr_employee_master`, `hr_joining_exit` — **row-count-only reconciliation**. The employee master report deliberately omits confidential bank and identity fields.

### 14.2 Attendance

| UI action | API | Schema | Store | Perm |
|---|---|---|---|---|
| Today's register | `GET /api/hr/attendance?from_date=&to_date=` | — | `hr_attendance` | `hr:read`, or own row with `hr:attendance_self` |
| Check in (GPS) | `POST /api/hr/attendance/check-in` | `CheckInIn{office_id, latitude, longitude, source, remarks}` | `hr_attendance.check_in`, `geofence_result` | `hr:attendance_self` |
| Check out | `POST /api/hr/attendance/check-out` | `CheckOutIn{latitude, longitude, remarks}` | `check_out`, `early_minutes` | `hr:attendance_self` |
| Manual entry | `POST /api/hr/attendance/manual` | `ManualAttendanceIn{employee_id, date, status, check_in, check_out, office_id, remarks}` | `hr_attendance` | `hr:attendance_manage` |
| Request correction | `POST /api/hr/attendance/{id}/correction` | `CorrectionIn{new_status, new_check_in, new_check_out, reason}` | `hr_attendance_corrections` | `hr:attendance_self` |
| Correction queue | `GET /api/hr/attendance/corrections` | — | same | `hr:read` |

The UI sends `source: "gps"` with coordinates when the browser allows it and falls back to `source: "web"` without coordinates. The geofence result is computed on the server (`app/services/hr.py:80-86`); the browser never decides it.

**Mismatch M-09 (Low).** The manual-attendance form sends only `employee_id`, `date`, `status` and `remarks`; `check_in`, `check_out` and `office_id` are accepted by the schema but not offered. A corrected punch time therefore cannot be entered from this screen; the correction request endpoint exists but has no UI either.

### 14.3 Leave

| UI field | Request field | Schema (`LeaveIn`) | Store | Perm |
|---|---|---|---|---|
| Type | `leave_type_id` | `int` | `hr_leave_applications.leave_type_id` | `hr:attendance_self` |
| From / To | `date_from`, `date_to` | `date` | same | same |
| Reason | `reason` | `str` | `reason` | same |
| Document | **not offered** | `document: str \| None` | `document` | same |
| Employee | **not sent** (defaults to the signed-in employee) | `employee_id: int \| None` | `employee_id` | same |
| Cancel | `POST /api/hr/leave/applications/{id}/cancel` | — | `status` | `hr:attendance_self` |

Reads: types, balances, applications (`hr:read` for the team; own rows otherwise). Approval is through the HR approval workflow (`app/services/hr_approvals.py`), and approved leave writes attendance and reduces the balance (F-63).

### 14.4 On duty (OD)

The UI sends `employee_id`, `date`, `visit_type`, `purpose`, `destination`. The schema also accepts `end_date`, `duration`, `party_type`, `party_name`, `worksite`, `document`, `remarks`, `regularisation` (`app/api/hr.py` ODIn). **Mismatch M-08 (Low):** the additional fields are not reachable from the screen, so a multi-day or regularised OD cannot be created in the browser.

### 14.5 Payroll

| UI action | API | Perm | Effect |
|---|---|---|---|
| List periods | `GET /api/hr/payroll/periods` | `hr:payroll_prepare` | `hr_payroll_periods` |
| Create period | `POST /api/hr/payroll/periods` | `hr:payroll_prepare` | `PeriodIn{year, month}` |
| Open period | `GET /api/hr/payroll/periods/{id}` | `hr:payroll_prepare` | Entries, days, gross, deductions, net |
| Prepare / recalculate | `POST /api/hr/payroll/periods/{id}/prepare` | `hr:payroll_prepare` | Builds entries |
| Submit | `POST /api/hr/payroll/periods/{id}/submit` | `hr:payroll_prepare` | Draft → under review |
| Process | `POST /api/hr/payroll/periods/{id}/process` | `hr:payroll_approve` | Approved → processed |
| Mark paid | `POST /api/hr/payroll/periods/{id}/pay` | `hr:payroll_approve` | Processed → paid |
| Salary slip | `GET /api/hr/payroll/entries/{id}/slip` | `hr:confidential` | PDF |
| Salary register | `GET /api/reports/hr_payroll/export?format=xlsx` | `report:export` + `hr:reports` | XLSX |
| Correction | `POST /api/hr/payroll/periods/{id}/corrections` | `hr:payroll_prepare` | **no UI** |

**Mismatch M-06 (Medium).** There is **no UI for salary components or salary structures** (`grep` for `/api/hr/salary` in `static/js/app.js` finds nothing), and `run_payroll()` silently skips any active employee without an effective structure (`app/services/payroll.py:59-60`). The live database currently holds 11 components and one structure for five employees (read-only count), so a payroll run will produce one entry and look empty to an operator. Components and structures are otherwise complete APIs (`POST /api/hr/salary/components`, `POST /api/hr/salary/structures`).

**Formula references:** F-51–F-58 (gross, deductions, net, effective dating, state machine). Payroll is audited and a paid period cannot be paid twice.

### 14.6 HR master data — API complete, UI absent

| Master | API | UI |
|---|---|---|
| Branches | `GET/POST /api/hr/branches` | read via dropdown; **no create form** |
| Offices / work locations | `GET/POST /api/hr/offices` | read via dropdown; **no create form** |
| Departments | `GET/POST /api/hr/departments` | **no UI at all** |
| Shifts | `GET/POST/PATCH /api/hr/shifts` | full UI (`app.js:691-755`) |
| Holidays | `GET/POST /api/hr/holidays` | **no UI at all** |
| Leave types | `GET/POST /api/hr/leave/types` | read in the leave form; **no create form** |
| Salary components | `GET/POST /api/hr/salary/components` | **no UI** |
| Salary structures | `GET/POST /api/hr/salary/structures` | **no UI** |

The development database already contains two branches, two work locations, two departments, one active "General" shift, five leave types and eleven salary components (read-only counts, no amounts read). Those records were not created by `seed.py`, which seeds no HR masters, so a fresh environment would have none of them and the UI cannot create them. This is M-06.

**Reports:** twelve HR registers. `hr_attendance`, `hr_leave`, `hr_od`, `hr_payroll` and the other period registers share the `_empty_reconciled` row-count-only check.

### 14.7 HR approvals

Leave and OD applications create `approval_requests` rows through `request_approval()` (`app/services/hr.py:153+`). The HR screen shows status and remarks but does not offer a decision button; decisions are made in `#/approvals` or through the HR approval endpoints (`app/services/hr_approvals.py`). HR self-approval is refused (F-66), tested in `tests/test_hr.py:11-47`.

---

## 15. Settings: company, tax, discounts, quote

### 15.1 Company profile (`app.js:2713-2745`)

| UI field | Request field | Schema (`CompanyIn`) | Store (`company_profile`) |
|---|---|---|---|
| Legal name | `legal_name` | `str` | `legal_name` |
| Trade name | `trade_name` | `str \| None` | `trade_name` |
| Registration | `registration_type` | `regular` / `composition` / `unregistered` | `registration_type` |
| GSTIN, PAN | `gstin`, `pan` | `str \| None`, upper-cased | same |
| State code | `state_code` (only for unregistered) | `str \| None` | `state_code` |
| Address lines, city, PIN | `address_line1`, `address_line2`, `city`, `pincode` | `str \| None` | same |
| Phone, email | `phone`, `email` | `str \| None` | same |
| Invoice prefix | `invoice_prefix` | `str \| None` | `invoice_prefix` |
| Bank block | `bank_name`, `bank_account_name`, `bank_account_number`, `bank_ifsc` | `str \| None` | same |

API: `GET /api/company` (`tax:read`), `PUT /api/company` (`tax:write`). For a registered company the place of supply is derived from the GSTIN; the form deliberately nulls `state_code` in that case, matching `normalize_identity()`.

### 15.2 GST rate master (`app.js:2747-2805`)

| UI field | Request field | Schema (`RateIn`) | Store (`tax_rates`) |
|---|---|---|---|
| HSN | `hsn` | `str` | `hsn` |
| Description | `description` (only if non-blank) | `str \| None` | `description` |
| CGST / SGST / IGST / cess % | `cgst_rate`, `sgst_rate`, `igst_rate`, `cess_rate` | `Decimal` | same |
| Reverse charge | `is_reverse_charge` | `bool` | `is_reverse_charge` |
| Effective from | `effective_from` | `date` | `effective_from` |
| Close with date | `effective_to` | `CloseIn{effective_to, reason}` | `effective_to` |

API: `POST /api/tax/rates` and `POST /api/tax/rates/{id}/close` (`tax:write`). Overlapping windows are refused (F-02). Reads: `/api/tax/rates`, `/api/tax/states`, `/api/tax/place-of-supply`, `/api/tax/quote` (`tax:read`).

### 15.3 Discount slabs (`app.js:2807-2892`)

| UI field | Request field | Schema (`SlabIn`) | Store (`discount_slabs`) |
|---|---|---|---|
| Name | `name` | `str` | `name` |
| Scope | `scope` | `product` / `group` | `scope` |
| Product / group | `product_id` / `group_name` | conditional | same |
| Quantity band | `min_qty`, `max_qty` | `Decimal` | same |
| Value band | `min_value`, `max_value` | `Decimal` | same |
| Discount % | `discount_percent` | `Decimal` | same |
| Approval above % | `approval_above` | `Decimal \| None` | same |
| Effective from / to | `effective_from`, `effective_to` | `date` | same |

API: `POST /api/discount-slabs` and `PATCH /api/discount-slabs/{id}` (`tax:write`). The UI hides the product or group input according to the selected scope; the server validates that the matching reference exists and that the bands do not overlap (F-07–F-11). The best applicable slab is chosen, not the first.

### 15.4 Tax quote (`app.js:2893-2925`)

`GET /api/tax/quote?hsn=&qty=&unit_price=&discount_percent=&buyer_state=&distributor_id=` (`tax:read`) returns `rate_found`, the resolved rate, the head split and the computed line. `buyer_state` is ignored when `distributor_id` supplies a place of supply and the server refuses a mismatch. Nothing is written.

---

## 16. Roles & Permissions, logins and employees

### 16.1 Logins (`app.js:5450-5490`, screen `#/users`)

| UI field | Request field | Schema (`CreateUserIn`) | Store (`users`) | Perm |
|---|---|---|---|---|
| Username | `username` | `str` | `username` | `user:manage` |
| Role | `role` | role id | `role_id` | `user:manage` |
| Employee link | `employee_id` (empty → null) | `int \| None` | `employee_id` | `user:manage` |
| Password | **not sent** | `password: str \| None` | `password_hash` | the server generates a temporary password |
| Change role | `role` | `UpdateUserIn.role` | `role_id` | `user:manage` |
| Activate / deactivate | `is_active` | `UpdateUserIn.is_active` | `is_active` | `user:manage` |
| Reset password | — | — | `password_hash`, `must_change_password`, `token_version` | `user:manage` |

The temporary password is shown once in a modal (`showSecret()`) and is never stored in the browser. Two self-protection rules are enforced server-side: an administrator cannot change their own role, and the last active administrator cannot lose `user:manage`.

### 16.2 Roles, permissions and feature switches (`app.js:5491-5690`, screen `#/roles`)

| UI field | Request field | Schema | Store | Perm |
|---|---|---|---|---|
| Role name (new) | `name` | `CreateRoleIn.name` | `roles.name` | `user:manage` |
| Display name | `display_name` | `str \| None` | `display_name` | `user:manage` |
| Permission checkboxes | `permissions[]` | `list[str]` | `role_permissions` (stored) and the effective set | `user:manage` |
| Module switch | `enabled` | `FeatureToggle` | `feature_flags` | Administrator role only |

The checkbox tree is built from `GET /api/roles/permissions` (the server's 44-key catalogue with `parent` and `admin_only`), not from a hard-coded browser list. A child input is disabled until its parent is ticked, and unticking the parent clears its children. The Access control panel (`renderAccessRules`) is generated from the same catalogue, so it cannot drift from the editor. Permission changes take effect on the next request because the server re-reads the role set each time.

The Feature availability panel calls `GET /api/features` and `PATCH /api/features/{key}`. The Overview module list is read-only and has no switch. Switching a module off does not rewrite `roles.permissions`; the server removes its keys from the effective set and refuses its API prefixes (see `docs/permissions-matrix.md`).

### 16.3 Employees (`app.js:5673-5760`)

See 14.1. This screen uses the narrower `/api/employees` route, not `/api/hr/employees`.

---

## 17. Audit trail

| UI element | API | Perm | Content |
|---|---|---|---|
| Filter options | `GET /api/audit/actions` | `audit:read` | Distinct action names and actors |
| Search | `GET /api/audit?…` | `audit:read` | Actor, action, entity, timestamp, before/after payload |
| Export | `GET /api/audit/export?…` | `audit:read` | CSV of the filtered trail |

Every write endpoint in this document calls `audit(...)` with the actor, a stable action name, the entity reference and the before/after values. The audit table is append-only: no endpoint updates or deletes an audit row (F-71).

---

## 18. Print and document verification

| UI element | API | Perm | Notes |
|---|---|---|---|
| Print invoice / credit note / debit note | `POST /api/print/{kind}/{id}?copy=` | `print:document` | Server-rendered PDF; `kind` is one of `invoice`, `credit_note`, `debit_note` — **purchase orders cannot be printed** (`app/api/printing.py:32`) |
| Print QR | `GET /api/print/qr/{reference}` | `print:document` | Real symbol, not a drawing |
| Verify a printed document | `POST /api/print/verify/{reference}` | `print:document` | Returns the stored fingerprint and whether it matches |
| Print log | `GET /api/print/log/{kind}/{id}` | `print:document` | Who printed which copy and when |

The print code records a SHA-256 fingerprint of the document and a stable print code. `verify` recomputes it from the current document, so a reprinted or altered document does not verify. The SPA reads the copy from the query string because a body field was previously dropped silently (comment at `app.js:952-956`).

---

## Appendix A — Mismatches and coverage gaps

| ID | Severity | Finding | Where | Effect | Recommendation |
|---|---|---|---|---|---|
| **M-01** | **Fixed** | Change-password screen added; the server still blocks all data until the temporary password is replaced | `index.html:43-59`; `app.js:90,116-146`; `app/core/rbac.py:27-29,74-100`; test `tests/test_authz.py` | Users created or reset in the UI can now set their own password and continue | Closed; keep the test in place |
| **M-02** | Medium | "Not allocated yet" is offered but rejected | `app.js:533,556-558`; `app/api/accounts.py:124-131,154-160` | Receipt/payment fails 422 unless an invoice/order is chosen | Add party selectors or remove the empty option and require allocation |
| **M-03** | Medium | Product UQC is never captured | `app.js:911-930,1236-1250`; schema accepts it at `app/api/products.py:30` | Printed GST invoices show "—" for the unit | Add a three-character UQC control |
| **M-04** | Low | Note date is never sent | `app.js:1908-1915`; schemas accept `note_date` | A late note lands in the wrong GST period | Offer an optional, audited note date |
| **M-05** | Low | Movement fields cannot be cleared | `app.js:1883-1892`; `app/api/invoices.py:329-355` | A wrong challan or e-way bill cannot be erased, only replaced | Send explicit nulls for cleared fields |
| **M-06** | Medium | No salary-structure or salary-component UI; employees without a structure are silently skipped | `app/services/payroll.py:59-60`; absent in `static/js/app.js` | A payroll run can produce almost no entries and look broken | Add structure/component screens; surface "skipped — no structure" in the run result |
| **M-07** | Low | HR employee screen exposes 11 of the 27 create fields (12 including `status` on edit) | `app.js:646-685`; `app/api/hr.py:83-139` | Bank, PAN, UAN, ESI, emergency and policy data cannot be entered in the browser | Add the remaining fields or a second tab |
| **M-08** | Low | OD screen omits end date, duration, party, worksite, document, regularisation | `app.js:828-849`; `ODIn` schema | Multi-day and regularised OD cannot be created from the browser | Extend the form |
| **M-09** | Low | Manual attendance omits punch times and office | `app.js:766-771`; `ManualAttendanceIn` | A wrong punch cannot be corrected in the browser | Add optional time fields |
| **M-10** | Low | Report sort and paging are applied in memory | `app/api/reports.py:118-132` | Large registers materialise fully before paging | Push ordering and paging into SQL, or cap period length |
| **M-11** | Info | HR masters (branches, offices, departments, holidays, leave types, components, structures) have no create UI | `app.js`; `app/api/hr.py` | A fresh environment cannot be configured in the browser | Build the master screens or document a supported seed step |

Dedicated labels: "Info" means the behaviour is a deliberate scope decision, not a defect; all others are defects to be scheduled.

---

## Appendix B — Route inventory by module

Counts are from introspection of the live `app` object; the full request/response schema is available at `/openapi.json`.

| Prefix | Routes | Main permissions |
|---|---|---|
| `/api/auth` | 4 | public login; signed-in otherwise |
| `/api/dashboard`, `/api/modules`, `/api/health` | 3 | signed-in |
| `/api/leads` | 9 | `lead:read`, `lead:write`, `lead:assign` |
| `/api/distributors` | 4 | `sales:read`, `distributor:write`, `credit:manage` |
| `/api/products` | 4 | `product:read`, `product:write` |
| `/api/warehouses` | 2 | `stock:read`, `stock:write` |
| `/api/inventory` | 2 | `stock:read` |
| `/api/purchase-orders` | 5 | `stock:read`, `stock:write` |
| `/api/sales-orders` | 7 | `sales:read`, `sales:write`, `dispatch:write` |
| `/api/invoices` | 8 | `sales:read`, `invoice:cancel`, `invoice:write`, `invoice:edit_post_billing` |
| `/api/credit-notes`, `/api/debit-notes` | 10 | `sales:read`, `note:write` |
| `/api/approvals` | 3 | `approval:read`; Administrator for sales/post-billing decisions |
| `/api/suppliers` | 7 | `supplier:read`, `supplier:write`, `supplier:bank`, `approval:decide` |
| `/api/accounts` | 8 | `accounts:read`, `accounts:write` |
| `/api/reports` | 3 | per-report data permission; `report:export` for files |
| `/api/hr` | 44 | `hr:read`, `hr:write`, `hr:attendance_self`, `hr:attendance_manage`, `hr:payroll_prepare`, `hr:payroll_approve`, `hr:confidential`, `hr:reports` |
| `/api/company` | 2 | `tax:read`, `tax:write` |
| `/api/tax` | 6 | `tax:read`, `tax:write` |
| `/api/discount-slabs` | 3 | `tax:read`, `tax:write` |
| `/api/users`, `/api/roles` | 9 | `user:manage` |
| `/api/employees` | 4 | `employee:read`, `employee:write` |
| `/api/audit` | 3 | `audit:read` |
| `/api/print` | 6 | `print:document` |
| `/api/admin/secondary-password`, `/api/db/reset` | 2 | `user:manage`, `db:reset` + secondary password |

---

## Appendix C — Verification ledger

| Area | Status | Evidence |
|---|---|---|
| Boot and sign-in | VERIFIED | `tests/test_smoke.py:1` |
| Lockout, forced change, reset, revoke | VERIFIED (code) | `app/api/auth.py`, `app/core/rbac.py`; **no test** |
| Leads create/list/actions | VERIFIED (code) | `app/api/leads.py`, `app.js`; **no test** |
| Distributor create/edit/identity | VERIFIED (code) | schemas and UI read; **no test**; the fixture creates a `Distributor` directly |
| Distributor credit limit | VERIFIED (code) | Exposure is exercised by `tests/test_approvals.py:30-76`; the `PATCH …/credit-limit` endpoint itself has no test |
| Product create/edit/pagination/permission | VERIFIED | `tests/test_products.py:1-53` |
| Product UQC | PARTIAL | Schema read; fixture inserts `uqc="TAB"` directly, UI never sends it (M-03) |
| Warehouse | VERIFIED (code) | schema and UI read; **no test** |
| Purchase order validation and rate remarks | VERIFIED | `tests/test_purchase_orders.py:1-38` |
| Goods receipt and stock posting | VERIFIED (code) | `app/api/purchase_orders.py`; **no test calls `/receive`** |
| Sales order create/submit/dispatch | VERIFIED | `tests/test_approvals.py:12-27` (`_invoice_for`) |
| Sales order cancel and tax preview | VERIFIED (code) | handlers read; **no test** |
| Invoice issue | VERIFIED | `tests/test_approvals.py:12-27`, `tests/test_report_reconciliation.py` |
| Invoice cancel, movement, amendment | VERIFIED (code) | handlers and UI read; **no test** |
| Credit and debit notes | VERIFIED (code) | schemas, service and UI read; **no test** |
| Approvals: credit limit, self-decision, post-billing | VERIFIED | `tests/test_approvals.py:30-102` |
| Supplier bank-change approval | VERIFIED (code) | handler read; **no test** |
| Accounts entry and ledgers | VERIFIED (code) | handler read; M-02 reproduced from source; only `/gst-register` is called by a test |
| Reports catalogue, filters, exports, reconciliation | VERIFIED | `tests/test_reports.py:1-181`, `tests/test_report_reconciliation.py:36-170` |
| HR employee permission, leave, payroll, shifts, check-in | VERIFIED | `tests/test_hr.py:1-253` |
| HR employee extended fields, holidays, leave types, components, structures | VERIFIED (code) / PARTIAL | API read; no UI for most (M-06, M-07) |
| Company profile, tax rates, slabs, quote | VERIFIED (code) | schemas and UI read; fixtures insert directly, no API test |
| Users, roles, permission catalog | VERIFIED | handlers read; catalogue/role parity and authorisation gates asserted by `tests/test_roles_parity.py` and `tests/test_authz.py` |
| Audit trail read | VERIFIED (code) | handler read; export audit is asserted in `tests/test_reports.py:163-181` |
| Print, QR, verification | VERIFIED (code) | handlers read; **no test** |
| Field-level mismatches | VERIFIED (code) | M-01 fixed and browser-verified; M-02–M-11 remain source-level findings in Appendix A |

**Nothing in this document certifies a workflow that lacks the cited test or source.** Where a field is accepted but unreachable from the browser, the row is marked PARTIAL or the mismatch is listed in Appendix A rather than being described as working. The current suite has 12 test modules; most write workflows outside products, purchase-order validation, approvals, HR and reports are **not** covered by an executable test.
