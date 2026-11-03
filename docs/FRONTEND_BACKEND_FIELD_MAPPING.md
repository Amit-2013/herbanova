# Frontend–Backend Field Mapping

**Project:** Herbanova Business Control
**Stage:** 3 — audit registers
**Date:** 31 October 2026
**Appendix A updated:** 2 November 2026 — M-06 partly closed and M-11 closed by the HR masters screens, salary-structure assignment and department/holiday edit routes. **Section 12 updated:** 3 November 2026 — input GST from supplier bills, filed-return reconciliation and statutory dues (Batch 4).
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
| API routes under `/api/` | 267 paths / 343 methods (4 Nov 2026, `APIRoute`s excluding HEAD/OPTIONS) | introspected from `app.main:app` |
| Browser views (`#/…`) | 20 | `static/js/app.js:200-208` |
| Report catalogue entries | 25 | `app/services/reports.py` `CATALOG` |
| Request schemas with a JSON body | 64 | `app/api/**` |
| Database tables | 84 at head `0029_totp` | `docs/DATABASE_TABLE_COLUMN_REGISTER.md`; `db_reset.table_classification()` |

The SPA is a single page with hash routes. Visibility of a view is decided in the browser by `VIEW_PERM` (`static/js/app.js:205-208`), but authorisation is always re-checked on the server by `require(perm)` / `require_admin(perm)` (`app/core/rbac.py:74-100`). Hiding a button is therefore a convenience, never a control.

**Two processes.** The browser talks to the frontend server (`scripts/run_frontend.py`), which serves `static/` and proxies `/api` to the backend (`scripts/run_backend.py`). The relative URLs in this document are unchanged; see [RUNNING_SERVERS.md](RUNNING_SERVERS.md).

---

## 1. Authentication and session

| UI control | UI source | API | Schema | Effect | Perm |
|---|---|---|---|---|---|
| `#u`, `#p`, Sign in | `app.js:112-119` | `POST /api/auth/login` | `Login{username, password}` | Sets HttpOnly `session` cookie; returns identity | none (rate-limited) |
| Session restore on load | `app.js:120-124` | `GET /api/auth/me` | — | Returns user, role, permissions, `must_change_password` | any signed-in user |
| Sign out | `app.js:3125` | `POST /api/auth/logout` | — | Clears cookie | any signed-in user |
| Forced change form (`#changePwForm`) | `index.html:43-59`; `app.js:116-146` | `POST /api/auth/change-password` | `ChangePassword{current_password, new_password}` | Blocking screen shown when `me.must_change_password`; on success re-hashes, bumps `token_version`, issues a new cookie, enters the shell | any signed-in user with a temporary password |
| Administrator second factor — setup | `showTotpSetup` in `app.js`; enrollment screen after the password step | `GET /api/auth/2fa/setup` | — | Returns `secret`, `otpauth_uri`, issuer, account, digits and period once; a short-lived `totp_challenge` cookie is required | password-step ticket, role `admin`/`super_admin` |
| Administrator second factor — confirm | enrollment screen code box | `POST /api/auth/2fa/confirm` | `TotpCode{code}` | Enables the factor, returns 10 one-time `recovery_codes` once and sets the session cookie | password-step ticket, mode `setup` |
| Administrator second factor — sign-in | code/recovery screen after the password | `POST /api/auth/2fa/verify` | `TotpVerify{code, recovery_code}` | Accepts a 6-digit code or one recovery code, then sets the session cookie; 5 wrong codes pause entry for 15 minutes | password-step ticket, mode `verify` |
| Second-factor state | profile/status display | `GET /api/auth/2fa/status` | — | `required`, `enabled`, `confirmed_at`, `recovery_codes_left`; never the secret | any signed-in user |

**Login response for an Administrator.** With the role `admin` or `super_admin`, `POST /api/auth/login` returns `{"status": "otp_required"}` (enrolled) or `{"status": "setup_required"}` (not enrolled) and sets **no** `session` cookie. Every other role receives `{"status": "ok", ...identity}` as before. The session JWT carries an `otp` claim only when issued after an accepted code; `current_user` refuses an enrolled account without it (`app/core/rbac.py`).

**Password policy.** The policy is server-side only: `validate_password` (`app/core/security.py`) runs in the `ChangePassword` field validator and in user create/reset; a temporary password is generated by `generate_temp_password` and returned once (`POST /api/users`, `POST /api/users/{id}/reset-password`). The browser sends the typed password, displays the one-time password the server returned, and mirrors no policy, generator or stored password.

**What is stored:** `users.username`, `users.password_hash` (Argon2id), `users.role_id`, `users.employee_id`, `users.must_change_password`, `users.token_version`, `users.failed_attempts`, `users.locked_until`, `users.last_login_at` (`app/models/core.py`); for the Administrator factor, `users.totp_secret` (sealed), `totp_enabled`, `totp_confirmed_at`, `totp_last_counter`, `totp_failed_attempts`, `totp_locked_until`, `totp_recovery_hashes` (migration `0029_totp`, applied to the test and development databases on 3 November 2026).

**Login behaviour:** case-insensitive usernames, lockout after repeated failures, the per-IP rate limit, the forced change on the next request and session revocation through `token_version` are VERIFIED (code) in `app/api/auth.py` and `app/core/rbac.py`. The forced-change branch, including the block, the policy checks and token revocation, is now covered by `tests/test_authz.py::test_forced_password_change_gates_data_and_revokes_the_old_token`; the basic boot path is covered by `tests/test_smoke.py:1`.

### 1.1 Sign-in page content

The signed-out screen renders only what the server supplies. There are no fixed banners, notices, phone numbers or policy text in `index.html` or `app.js`; an empty table produces a neutral "No data yet" row.

| UI element | UI source | API | Fields | Effect | Perm |
|---|---|---|---|---|---|
| Whole page on load | `loadSignIn()` / `renderPromo()`, `renderNotices()`, `renderContacts()`, `renderLegalLinks()` in `app.js` | `GET /api/public/sign-in` | `company{name,trade_name}`, `banners[]`, `notices[]`, `contacts[]`, `legal[]` | One unauthenticated read; active rows only; notices capped at 5, newest date first | none (60/min per IP) |
| Promotion banner image | `<img>` inside `.promo-slide` | `GET /api/public/sign-in/banners/{id}/image` | bytes | JPEG/PNG/WebP served from `var/signin_banners`; `Cache-Control: public, no-cache`; 404 when inactive or the file is missing | none (240/min per IP) |
| Legal dialog | footer buttons `[data-legal]`, `openLegal()` | `GET /api/public/sign-in/legal/{privacy\|terms}` | `key`, `title`, `published`, `body` | `body` is `null` and `published` is `false` until the Administrator writes and publishes text; the dialog then says "Not published yet" | none (60/min per IP) |
| Save ID (`#saveId`) | `applySavedId()` on boot, `saveLoginId()` after a successful login | — | `hb.savedUser` in `localStorage` | The User ID, never the password, is remembered after a successful sign-in and refilled on the next visit; clearing the box removes it | none |
| Forgot Password | `#forgotBtn` panel | — | uses the `contacts[]` row labelled Customer Support | Names the Administrator and shows the configured support box; sends no e-mail and reveals no account state | none |
| Banner list / upload / replace / remove | Settings → Sign-in page (`#signinAdminPanel`, `#signinBannerForm`) | `GET /api/admin/sign-in`; `POST /api/admin/sign-in/banners` (multipart `file`, `title`, `link_url`, `sort_order`, `active`); `POST …/banners/{id}/image`; `PATCH …/banners/{id}`; `DELETE …/banners/{id}`; `GET …/banners/{id}/image` | `title` ≤120, `link_url` ≤500 and only `http(s)://` or a single-slash path, `sort_order`, `active`; file checked with PIL and capped at 2,000,000 bytes | A replaced image's old file is deleted; the value stored is a file name, not a path | `user:manage` |
| Notice list / edit | admin panel | `POST /api/admin/sign-in/notices`; `PATCH`/`DELETE …/notices/{id}` | `title` ≤160, `body` ≤2000, `notice_date`, `active` | Order on the public page is `notice_date` descending | `user:manage` |
| Help-line boxes (Sales, Service, Customer Support) | admin panel | `POST /api/admin/sign-in/contacts`; `PATCH`/`DELETE …/contacts/{id}` | `label` ≤60 required, `detail` ≤160, `phone` ≤40, `email` ≤160, `sort_order`, `active` | At least one of detail/phone/e-mail is required; the e-mail must look like an address | `user:manage` |
| Legal text editor | admin panel | `PATCH /api/admin/sign-in/legal/{key}` | `title` ≤120, `body` ≤20,000, `published` | Publishing with an empty or blank body is refused with `422` "Write the document text before publishing it"; `privacy` and `terms` are the only keys | `user:manage` |

**No invented content.** `tests/test_signin.py::test_the_public_page_never_invents_content` pins the empty payload, and `test_unpublished_legal_text_is_not_returned` pins the withheld body. The server gates every write through `require_admin("user:manage")`; the browser hiding the panel is a convenience only. Migration `0030_sign_in_content` creates the four tables and seeds the two legal rows unpublished; downgrade drops them and leaves any banner file on disk for an operator to remove.

**M-01 (High) — FIXED 31 October 2026.** The server blocks every endpoint except `/api/auth/me`, `/api/auth/logout` and `/api/auth/change-password` while `must_change_password` is true (`app/core/rbac.py:27-29, 74-100`). The SPA now shows a blocking **Set a new password** screen (`index.html:43-59`; `showPasswordChange` at `static/js/app.js:116-125`) whenever the identity reports `must_change_password`, hides the shell and login form, validates the policy and confirmation in the browser, posts to the endpoint, and only then enters the shell with the fresh identity (`app.js:126-146`). Sign out remains available from the screen. Verified in an in-app browser against a throwaway database: sign-in with a temporary password showed the screen, a mismatched confirmation was rejected locally, the correct change loaded the shell, and the spurious 403 banner formerly caused by loading the approvals queue without `approval:read` was removed (`app.js:170-175, 222`).

---

## 2. Dashboard and module register

**UI route:** `#/dash` (`renderDash`, `app.js:423-472`; insight cards, `app.js:887-996`). **Phase 2 metric definitions, sources, permissions and refresh rules:** `docs/DASHBOARD_FEATURES.md`.

| UI element | API | Permission | Content |
|---|---|---|---|
| Period control: one trigger (`#dashRangeLabel`, e.g. `Oct 5, 2026 - Nov 3, 2026`) opens a popover with presets `1D` `7D` `30D` `Month to date` `Last month` `90D` `This FY` and a two-month calendar (first click start, second end, backwards pair swapped), all tiles and panels | `GET /api/dashboard?from_date=&to_date=` | `require_login`, then per section | Payload as at §2.1; the browser sends calendar dates, and the legacy `range=` parameter is still accepted for older callers but limited to 7/30/90 (422 otherwise). `to_date` in the future or `from_date` after `to_date` → **422**. `from_date`/`to_date` persist in `localStorage` (`hb.dashFrom`, `hb.dashTo`, `hb.dashPreset`); a stored preset that no longer matches today is dropped from the highlight, not from the window. Sections the role cannot read are `null`, never `0`. |
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
| `category_sales` | `{available:true,rows[{category,revenue,qty,invoices}],total,classified_total,uncategorised_total,note}` grouped from issued-invoice taxable value by the product's captured category; blanks are "Uncategorised" | `sales:read` |
| `recent_activity` | `{rows[{id,at,actor,action,record,changes}],shown,total}` | `audit:read` |
| `insights.pipeline` | `{sales:{rows[{status,label,count,value}],total,dispatch:{measured,average_days,approval_measured,approval_average_days,after_approval_measured,after_approval_average_days,delivery:{measured,on_time,late,average_days_late},overdue_open,note}},leads:{rows[{status,label,count}],total}}`; each side `null` without its permission | `sales:read` / `lead:read` |
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
| Category | `category` | `str \| None`, max 60 | `category` | blank is stored as null; suggestions come from `GET /api/products/catalog` |
| Brand | `brand` | `str \| None`, max 60 | `brand` | blank is stored as null; suggestions from the same endpoint |
| Reorder level | `reorder_level` | `Decimal \| None` ≥ 0, 3 dp | `reorder_level` | blank is "not set", never zero; drives the low-stock attention rule |
| **Unit (UQC)** | **never sent** | `uqc: str \| None`, max 3 | `uqc` | **Mismatch M-03** |

API: `POST /api/products` (`product:write`), `PATCH /api/products/{id}` (`product:write`), `GET /api/products/catalog` (`product:read`, distinct non-blank categories and brands for the form's suggestions). The server uppercases a supplied UQC and stores null when blank (`app/api/products.py:40-42`); the invoice copies `products.uqc` onto the line at issue time (`app/services/invoice.py:114`). Category, brand and reorder level were added in migration `0024`; all three are nullable so existing products stay valid, and every change is audited with old and new values.

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
| Expected delivery date | `expected_delivery_date` (only if non-blank) | `date \| None` | `expected_delivery_date` | optional promise; a past date is refused; null means no promise and the order contributes nothing to lateness |

API: `POST /api/sales-orders` (`sales:write`). The service freezes the product name, HSN, pack size and MRP on the line, and computes tax through the same `line_tax()` used by invoices (F-05, F-07–F-10). A price above MRP is refused; a discount over the configured threshold creates an approval (section 10).

### 7.2 Order actions

| UI action | API | Schema | Perm | Effect |
|---|---|---|---|---|
| Preview tax | `GET /api/sales-orders/{id}/tax-preview` | — | `sales:read` | Recomputes heads without writing |
| Submit | `POST /api/sales-orders/{id}/submit` | — | `sales:write` | Draft → pending approval or approved |
| Cancel | `POST /api/sales-orders/{id}/cancel` | `ReasonIn{reason}` | `sales:write` | Allowed only before dispatch |
| Dispatch | `POST /api/sales-orders/{id}/dispatch` | `DispatchIn{warehouse_id}` | `dispatch:write` | FEFO issue, invoice issue, stock movements |
| Set/clear promise | `PATCH /api/sales-orders/{id}/delivery-date` | `DeliveryIn{expected_delivery_date}` | `sales:write` | Allowed on draft, pending-approval and approved orders; null clears; unchanged or past date → 422; after dispatch → 409; audited `so.delivery_date` |

The submit response carries `status` and, when held, `approval{id, reasons[]}`; the UI opens the approval drawer or shows "Awaiting approval" (`app.js:1705-1720`). Dispatch selects a warehouse from `state.warehouses` and is refused when stock is insufficient (F-24, F-30).

**Reports:** `sales` (Sales Orders), period, `sales:read` — **row-count-only reconciliation**.

---

## 8. Dispatch, invoices and post-billing movement

An invoice is **issued by the dispatch transaction**, not by a form. The billing view (`#/billing`) is therefore read-mostly: list, open, print, cancel, note, and (Administrator only) amend movement details.

### 8.1 Invoice list and detail

| UI element | API | Perm | Fields shown |
|---|---|---|---|
| Invoice register | `GET /api/invoices` | `sales:read` | number, FY, date, buyer, GSTIN, grand total, credited total, status |
| Invoice detail | `GET /api/invoices/{id}` | `sales:read` | line product, SKU, HSN, UQC, quantity, price, taxable, CGST/SGST/IGST, total; movement fields; `payment_terms_days` and `due_date` (both NULL when no terms were captured) |
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

**Open and Print.** The notes table in Billing lists credit and debit notes together, newest first, and each row carries **Open** and — with `print:document` — **Print**. `GET /api/credit-notes` and `GET /api/debit-notes` return each note with `invoice_number` and its `lines`, so **Open** needs no extra request; `noteDetail(kind, id)` draws the stored note in the shared drawer (number and financial year, invoice, buyer only when known, date, reason, returned-to-stock quantity for a credit, tax breakdown, lines and the print-log verification). **Print** calls the same route as every other document, `POST /api/print/{credit_note|debit_note}/{id}?copy=ORIGINAL`, which renders the PDF, records the print log and offers the verification page and QR. The browser never builds or edits a note PDF. Covered by `tests/test_file_audit.py::test_a_credit_and_a_debit_note_can_be_opened_and_printed`; see [FEATURE_INVENTORY.md](FEATURE_INVENTORY.md) F-132.

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

**KPI card links (Performance and P&L).** `GET /api/accounts/report` returns ten `cards[]` entries with `key`, `label`, `value`, `note`, `available`, optional `gap` and an `href`. The tile is an `<a href>`; no click handler chooses the destination, so the server and the report cannot disagree.

| Card (`key`) | `href` | Window carried | Opens |
|---|---|---|---|
| Revenue (`revenue`) | `#/accounts/gst-out` | `?from`/`?to` | GST outward, taxable value |
| Collections (`collections`) | `#/accounts/cash` | `?from`/`?to` | Receipts and payments |
| Receivables (`outstanding`) | `#/accounts/receivables` | — (as-at list) | Receivables |
| Over 60 days (`overdue_60`) | `#/accounts/ageing` | `?as_of` | Ageing of outstanding invoices |
| Payables (`payables`) | `#/accounts/payables` | — | Payables |
| Payable within 7 days (`payable_week`) | `#/accounts/payables?due=week` | `due=week` | Payables, filtered to the next seven days |
| Output GST (`gst`) | `#/accounts/gst-out` | `?from`/`?to` | GST outward |
| Cash and bank (`cash_bank`) | `#/accounts/cash` | `?from`/`?to` | Receipts and payments |
| Expenses (`expenses`) | `#/expenses` | `?from`/`?to` | Expenses screen |
| Net profit (`net_profit`) | `#/accounts/reports?focus=pnl` | `focus=pnl` | Performance and P&L, statement focused |

A card with `available: false` still links to the section that explains it (the gap code is shown on the tile). The browser parses the query in `route()` and applies it to the section before drawing, so a refresh, a bookmark or a browser back/forward lands on the same filtered report.

| UI field | Request field | Schema (`EntryIn`) | Store (`payments`) |
|---|---|---|---|
| Kind (drawer mode) | `kind` | `receipt` / `payment` | `kind` |
| Record as (`#e-purpose`) | `purpose` | `outstanding` / `advance` | drives allocation; not stored on the payment |
| Party (`#e-party`) | `distributor_id` / `supplier_id` | `int` | `distributor_id` / `supplier_id` |
| Settle this first (`#e-against`) | `invoice_id` / `purchase_order_id` | `int \| None` | legacy columns stay NULL; the settlement is a `payment_allocations` row |
| Amount | `amount` | `Decimal` > 0, 2 dp | `amount` |
| Date | `paid_on` | `date` | `paid_on` |
| Mode | `mode` | `bank/cash/upi/cheque/neft/other` | `mode` |
| Reference | `reference` | `str \| None`, 60 | `reference` |
| Note | `notes` | `str \| None`, 300 | `notes` |
| Advance hint | — | — | read from `GET /api/accounts/advances?kind&party_id` (`available`, `entries`) |

Response (`EntryOut`): `number`, `kind`, `amount`, `paid_on`, `mode`, `reference`, `notes`, `purpose`, `allocated`, `advance`, `allocations[]` (`invoice_id` / `purchase_order_id`, `number`, `amount`, `applied_on`). The entry table prints each allocation and any advance held.

API: `POST /api/accounts/payments` (`accounts:write`). Reads: outstanding (`/outstanding`), ageing (`/ageing`), advances (`/advances`), distributor and supplier ledgers, trial balance, GST register, and the last 500 entries (`/payments`).

**M-02 closed.** The drawer now has a party selector (`#e-party`, distributors for a receipt, suppliers for a payment) and a two-mode choice. `distributor_id` / `supplier_id` are always sent, so money with nothing to settle is recorded as an advance instead of failing with 422. Naming a settled document still fails, and an advance that names any document is refused.

**Immutability:** no update or delete route exists for a payment. A wrong entry is corrected by recording the opposite entry with a note (`app/api/accounts.py:1-16`). This is deliberate and matches F-43 and F-74.

**Reports:** `receivables`, `receivables_ageing`, `payables`, `trial_balance`, `gst_register` — all five carry independent checks (section 13.2).

**Profit and loss fields (`GET /api/accounts/report` → `profit_and_loss`, and the Overview `accounts` block).** Each row carries `key`, `label`, `value`, `available`, `partial`, `gap` and `fix`; the statement carries `payroll.method`, `payroll.periods[]`, `payroll.missing_months[]`, `payroll.partial_months[]` and `net_profit.available`.

| Server field | Meaning | Browser use |
|---|---|---|
| `profit_and_loss.rows[].partial` | The figure covers only part of the window (expenses before `tracked_from`, payroll with an unapproved month) | **Partial** chip beside the amount; `fix` opens `#/expenses` or `#/hr/payroll` |
| `profit_and_loss.payroll.periods[].prorated` | The window cut this approved month short | Note names the month as allocated |
| `profit_and_loss.payroll.periods[].allocated` | Approved month gross × (working days inside the window ÷ working days in the month) | Summed into the payroll line |
| `profit_and_loss.payroll.periods[].included` | Whether the period contributed (`false` for a draft/unapproved month) | Named in the GAP-P03 note |
| `profit_and_loss.net_profit.available` | Every input for the window is complete | `No data yet` with the first gap when false |
| Overview `accounts.expenses_known`, `expenses_partial`, `expenses_note`, `expenses_gap` | The same facts for the Overview Expenses tile | Amount with **Partial** chip and the note; gap link when unknown |

### 12.1 Financial years and accounting month locks

**UI:** two panels on `#/accounts` — “Financial years” and “Accounting month locks”.

| UI field | Request field | Endpoint | Store | Notes |
|---|---|---|---|---|
| Close year reason | `reason` | `POST /api/accounts/financial-years/{label}/close` | `financial_year_closes.reason` | `accounts:write`; label `YYYY-YY`; at least 5 characters (`min_length=5`), max 300; only a completed year, not before the first document |
| Reopen reason | `reason` | `POST /api/accounts/financial-years/{label}/reopen` | `financial_year_closes.reopen_reason` | `require_admin`; sets `active=false`, `reopened_by/at` and the reason |
| Lock month | `year`, `month`, `reason` | `POST /api/accounts/period-locks` | `hr_period_locks` scope `accounting` | `accounts:write`; month `YYYY-MM` typed in the drawer |
| Unlock month | `reason` | `POST /api/accounts/period-locks/{id}/unlock` | `hr_period_locks.unlock_reason` | Administrator only |

Read: `GET /api/accounts/financial-years` (`accounts:read`) returns `current`, `today` and `years[]` with `financial_year`, `first`, `last`, `active`, `reason`, `closed_by`, `closed_at`, `reopened_by`, `reopened_at`, `reopen_reason`. `GET /api/accounts/period-locks` returns the lock rows. A refused document returns **423** with the year or month in `detail`.

**Ageing due fields (`GET /api/accounts/ageing`).** Each row carries `due_date` and `days_overdue`; the payload carries `due = {overdue, due_this_week, not_yet_due, no_due_date}`, each with `total` and `count`. The table shows “Due date” and “Overdue (days)” columns and prints the four buckets under the table; the buckets sum to `total` and their counts to `count`.

### 12.2 Input GST — supplier bills

**UI:** panel “Input GST — supplier bills” on `#/accounts`; `piForm` drawer, `piReverseForm` drawer.

| UI field | Request field | Schema (`PurchaseInvoiceIn`) | Store (`purchase_invoices`) |
|---|---|---|---|
| Supplier | `supplier_id` | `int` | `supplier_id` |
| Purchase order (optional) | `purchase_order_id` | `int \| None` | `purchase_order_id` |
| Supplier bill number | `supplier_invoice_number` | `str`, 1–60 | `supplier_invoice_number` (unique per supplier) |
| Bill date | `invoice_date` | `date` | `invoice_date` |
| Taxable value | `taxable_value` | `Decimal` ≥ 0 | `taxable_value` |
| CGST / SGST / IGST / cess | `cgst_amount` … `cess_amount` | `Decimal` ≥ 0 | the four head columns |
| Round-off | `round_off` | `Decimal` | `round_off` |
| ITC eligible | `itc_eligible` | `bool` | `itc_eligible` |
| TDS section / rate / amount | `tds_section`, `tds_rate`, `tds_amount` | `str \| None`, `Decimal`, `Decimal` | the three TDS columns |
| Note | `note` | `str \| None`, 300 | `note` |
| Reversal reason | `reason` | `str`, ≥ 5 | `reversal_reason`, `status = reversed`, `reversed_by/at` |

API: `GET/POST /api/accounts/purchase-invoices`, `POST /api/accounts/purchase-invoices/{id}/reverse` (`accounts:read` / `accounts:write`, audit `accounts.purchase_invoice.reverse`). Duplicate live bill number for the same supplier → 409; a date in a locked month or closed year → 423.

Read surface: `GET /api/accounts/input-gst?from=&to=` returns `rows`, `totals`, `eligible`, `blocked`, `blocked_count`, `available`, `note`; `GET /api/accounts/gst-net` returns `output`, `input`, `blocked_input`, `net`, `expense_itc`, `available`, `reason`, `note`. The panel renders the tax columns, the ITC flag, the net line and the expense-ITC memo under the table. All money is a two-decimal string.

### 12.3 Filed GST returns and reconciliation

**UI:** panel “GST returns and reconciliation”; `grForm` drawer with year and month selects.

| UI field | Request field | Schema (`GstReturnIn`) | Store (`gst_returns`) |
|---|---|---|---|
| Year / month | `year`, `month` | `int` | `year`, `month` (unique with `form`) |
| Form | `form` | `GSTR-1` / `GSTR-3B` | `form` |
| Outward taxable value | `outward_taxable` | `Decimal` | `outward_taxable` |
| Outward heads | `outward_cgst`, `outward_sgst`, `outward_igst`, `outward_cess` | `Decimal` | the four columns |
| ITC heads (GSTR-3B only) | `itc_cgst`, `itc_sgst`, `itc_igst`, `itc_cess` | `Decimal` | the four columns (422 on GSTR-1) |
| Filed on / reference | `filed_on`, `reference` | `date \| None`, `str \| None` | `filed_on`, `reference` |
| Note | `note` | `str \| None` | `note` |

API: `GET/POST /api/accounts/gst-returns` (`accounts:read` / `accounts:write`, audit `accounts.gst_return.record`), `GET /api/accounts/gst-reconciliation?year=&month=`. The panel prints Form / Check / Filed / Computed / Difference / Result per line; a difference is shown, never corrected. An unknown form or a future month → 422.

### 12.4 TDS and statutory dues

**UI:** panel “TDS and statutory dues”; `chForm` drawer.

| UI field | Request field | Schema (`ChallanIn`) | Store (`statutory_challans`) |
|---|---|---|---|
| Head | `kind` | `pf` / `esi` / `pt` / `tds` | `kind` |
| BSR code | `bsr_code` | `str \| None` | `bsr_code` |
| Challan number | `challan_number` | `str` | `challan_number` |
| Paid on | `paid_on` | `date` | `paid_on` |
| Amount | `amount` | `Decimal` > 0 | `amount` |
| Period | `period_year`, `period_month` | `int` | `period_year`, `period_month` |
| Section / note | `section`, `note` | `str \| None` | `section`, `note` |

API: `GET /api/accounts/statutory-dues?from=&to=`, `GET/POST /api/accounts/statutory-challans` (`accounts:read` / `accounts:write`, audit `accounts.challan.record`). The dues payload carries `summary[]` (`kind`, `label`, `withheld_to_date`, `deposited_to_date`, `deposited_in_window`, `outstanding`, `available`, `reason`), `vendor_tds`, `payroll`, `challans`, `available`, `notes`. An unknown kind or a future period → 422. The panel prints the four heads, the challan table and the vendor-TDS / payroll detail lines.

### 12.5 Receivables by distributor

**UI:** its own section, `#/accounts/receivables-by-distributor`; inputs `#rbdFrom` (From date) and `#rbdTo` (To date), buttons `load-rbd` (Apply) and `export-rbd` (Export CSV); table body `#rbdRows`, total `#rbdFoot`. There is no date, month or year shortcut: the two date boxes are the only window controls.

| UI control | Request field | Endpoint | Notes |
|---|---|---|---|
| From date | `from_date` | `GET /api/accounts/receivables-by-distributor` | Read only when Apply is pressed; an empty box is refused |
| To date | `to_date` | same | Capped at today; `from_date` after `to_date` → 422; a future `to_date` → 422 |
| Apply | — | same | The only trigger that reloads the report, with a sequence guard so a stale response cannot overwrite a newer window. Changing either date makes no request |
| Export CSV | — | client-side `downloadCsv` | Works on the loaded payload; header row carries `From` / `To`; one row per distributor; `Total` row; filename `HERBANOVA_Receivables_by_distributor_<from>_<to>.csv` |

The payload is `{from, to, rows[], totals, count, note}`. Each row carries `distributor_id`, `name`, `code`, `state`, `opening`, `invoiced`, `credited`, `debited`, `received`, `closing`, `overdue`, `invoices`, `open_invoices`, `overdue_invoices` (money as two-decimal strings). `totals` adds the same amount columns plus `invoices`, `open_invoices`, `overdue_invoices`. Per row and in total, `opening + invoiced + debited − credited − received = closing`; `overdue` is the part of `closing` whose invoice `due_date` is before `to`, so an invoice with no due date is never overdue. Permission `accounts:read`.

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

The People table shows each employee's office under **Location** and a **No attendance** chip when the attendance policy exempts that employee (`app.js:2740`). The header offers **Branches & locations** (`data-act="hr-sites"`, drawer titled *Branches, offices & attendance policy*) and **HR masters** (`data-act="hr-masters"`, §14.6) to `hr:write`, and branch/office filters (`#hrBranchFilter`, `#hrOfficeFilter`) that scope the dashboard, the register and the reports (`setHrSite`, `app.js:2564`).

### 14.1 Employee master

Two APIs exist:

- `POST/PATCH /api/employees` — the legacy, narrow employee record used by the Users page; `EmployeeIn{code, full_name, department, designation, phone, email, joining_date, manager_id}`.
- `POST/PATCH /api/hr/employees` — the full HR record. `EmployeeIn` accepts 27 fields: the eight above plus `branch_id, office_id, department_id, shift_id, hr_admin_id, employment_type, work_schedule, date_of_exit, address, emergency_name, emergency_phone, bank_name, bank_account_no, bank_ifsc, pan, uan, esi_no, attendance_policy, leave_policy`; `EmployeePatch` adds `status` (`app/api/hr.py:83-139`).

| UI field (`employeeForm`, `app.js:6069`) | Request field | Schema | Store (`employees`) | Perm |
|---|---|---|---|---|
| Employee code (create only) | `code` | `str` | `code` | `hr:write` |
| Full name | `full_name` | `str`, min 2 | `full_name` | same |
| Department (free text) | `department` | `str \| None` | `department` | same |
| Designation | `designation` | `str \| None` | `designation` | same |
| Phone, email | `phone`, `email` | `str \| None` | same | same |
| Joining date | `joining_date` | `date \| None` | `joining_date` | same |
| Employment type | `employment_type` | `str \| None` | `employment_type` | same |
| **Branch** | `branch_id` | `int \| None` | `branch_id` → `hr_branches.id` | same |
| **Office / work location** | `office_id` | `int \| None` | `office_id` → `hr_work_locations.id` | same |
| Shift | `shift_id` | `int \| None` | `shift_id` | same |
| Status | `status` | `active` / `inactive` | `status` | same |
| Attendance policy (read-only note) | — | `/api/hr/employees/{id}/profile` → `attendance_requirement` | computed | `hr:write` |

**Branch/office cascade (`app.js:6110-6127`).** Each office option carries `data-branch`. Choosing a branch hides the offices of other branches and clears an office that no longer belongs; choosing an office fills its branch. The server repeats the pairing check (`OfficeIn`/`EmployeeIn`: an office's branch must match `branch_id` when both are given) and refuses a mismatch with 422, so a crafted request cannot create the disagreement the screen prevents. When absent, `branch_id` is inferred from the chosen office.

The policy note is read, never edited: it shows `required`, `self_service`, the mode override and the rule `source` returned by `resolve_attendance_requirement()`. Before the first save it says attendance is required by default, because there is no record to resolve against yet.

**Mismatch M-07 (Low, narrowed).** The HR screen still cannot capture bank details, PAN, UAN, ESI number, emergency contacts, address, exit date, `department_id`, `hr_admin_id`, work schedule or the attendance/leave policy permanent overrides, although the API accepts all of them. Those remain API- or data-load-only. Branch, office and shift are no longer part of M-07.

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
| Your own policy (note) | `GET /api/hr/attendance-rules/resolve` | — (defaults to the signed-in employee) | computed from `hr_attendance_rules` | `current_user` |
| Today's register (location filters) | `GET /api/hr/attendance?...&branch_id=&office_id=` | — | `hr_attendance` | `hr:read` |
| Monthly register | `GET /api/hr/attendance/monthly?year=&month=&branch_id=&office_id=` | — | computed | own row or `hr:read` |
| HR dashboard | `GET /api/hr/dashboard?branch_id=&office_id=` | — | computed | `hr:read` |

The UI sends `source: "gps"` with coordinates when the browser allows it and falls back to `source: "web"` without coordinates. The geofence result is computed on the server (`app/services/hr.py:80-86`); the browser never decides it.

**Attendance requirement is enforced on the server.** Before any write, the service calls `require_attendance()` and `require_self_service()` (`app/services/hr.py`), which resolve the employee's rule for the day. An employee the policy exempts is refused check-in, check-out, a correction request, a manual entry and a bulk row with **409** and the rule's source in the message; `hrAttendance()` hides exempt employees from the manual list and states how many were left out. A day the policy exempts is written to the register as `status: null, not_required: true` and to the totals as `not_required_days` — never as a gap and never as an inferred absence. Screening differs from gating: hiding the button is a convenience; the 409 is the control.

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
| Open period | `GET /api/hr/payroll/periods/{id}` | `hr:payroll_prepare` | Entries, days, gross, deductions, net; **`skipped[]`** `{employee_id, code, name, reason}` |
| Prepare / recalculate | `POST /api/hr/payroll/periods/{id}/prepare` | `hr:payroll_prepare` | Builds entries; returns and audits **`skipped[]`** `{employee_id, code, name, reason}` |
| Submit | `POST /api/hr/payroll/periods/{id}/submit` | `hr:payroll_prepare` | Draft → under review |
| Process | `POST /api/hr/payroll/periods/{id}/process` | `hr:payroll_approve` | Approved → processed |
| Mark paid | `POST /api/hr/payroll/periods/{id}/pay` | `hr:payroll_approve` | Processed → paid |
| Salary slip | `GET /api/hr/payroll/entries/{id}/slip` | `hr:confidential` | PDF |
| Salary register | `GET /api/reports/hr_payroll/export?format=xlsx` | `report:export` + `hr:reports` | XLSX |
| Correction | `POST /api/hr/payroll/periods/{id}/corrections` | `hr:payroll_prepare` | **no UI** |

**Skipped employees (M-06, closed 3 Nov 2026).** `run_payroll()` still does not pay an active employee with no effective structure, but the period screen and the prepare response now carry `skipped[]`; the browser renders each name with its reason ("No active salary structure covers this month" or "Not in the prepared entries") and an **Assign salary structures** button (`data-act="hr-masters"`, tab `salary-structures`). The prepare audit entry stores the skipped codes. `app/services/payroll.py:skipped_employees`, `app/api/hr.py` (`get_period`, `prepare_payroll`); `tests/test_hr.py` asserts the prepare result and the register agree.

**Formula references:** F-51–F-58 (gross, deductions, net, effective dating, state machine). Payroll is audited and a paid period cannot be paid twice. An employee whose attendance policy exempts them has `payable_days = working_days − recorded unpaid days` and the period note says attendance is not required for them (`app/services/payroll.py`), so an exempt person is never docked for days they were not asked to mark.

### 14.6 HR master data

| Master | API | UI |
|---|---|---|
| Branches | `GET/POST /api/hr/branches`, `PATCH /api/hr/branches/{id}` | **full UI** — New/Edit on *Branches & locations* (`hrBranchForm`, `app.js:3346`) |
| Offices / work locations | `GET/POST /api/hr/offices`, `PATCH /api/hr/offices/{id}` | **full UI** — New/Edit, branch, mode, geofence (`hrOfficeForm`, `app.js:3380`) |
| Attendance rules | `GET/POST /api/hr/attendance-rules`, `PATCH`/`DELETE /{id}`, `GET /resolve` | **full UI** — New/Edit/Delete (`hrRuleForm`, `app.js:3436`; `hrRuleDelete`, `app.js:3515`) |
| Departments | `GET/POST /api/hr/departments`, `PATCH /api/hr/departments/{id}` | **full UI** — HR masters → Departments (`hrMastersDepartments`, `hrDepartmentForm`) |
| Shifts | `GET/POST/PATCH /api/hr/shifts` | full UI (`app.js:691-755`) |
| Holidays | `GET/POST /api/hr/holidays`, `PATCH /api/hr/holidays/{id}` | **full UI** — HR masters → Holidays (`hrMastersHolidays`, `hrHolidayForm`) |
| Leave types | `GET/POST /api/hr/leave/types`, `PATCH /api/hr/leave/types/{id}` | **full UI** — HR masters → Leave types (`hrMastersLeaveTypes`, `hrLeaveTypeForm`) |
| Salary components | `GET/POST /api/hr/salary/components`, `PATCH /{id}` | **full UI** — HR masters → Salary components (`hrMastersComponents`, `hrComponentForm`) |
| Salary structures | `GET/POST /api/hr/salary/structures` | **full UI** — HR masters → Salary structures and the profile Salary tab (`hrMastersStructures`, `hrSalaryStructureForm`, `hrProfileSalary`) |

The development database already contains two branches, two work locations, two departments, one active "General" shift, five leave types and eleven salary components (read-only counts, no amounts read). Those records were not created by `seed.py`, which seeds no HR masters. Every master above can now be created in the browser, so a fresh environment is configurable from the screen; a payroll run that leaves an employee out says so on the period screen (M-06 closed 3 Nov 2026).

**Reports:** twelve HR registers. `hr_attendance`, `hr_leave`, `hr_od`, `hr_payroll` and the other period registers share the `_empty_reconciled` row-count-only check. The register and report screens pass the selected branch/office to the server (`hrReports`, `app.js:3837`; request fields `branch_id`, `office_id`) and repeat the selection in the printed header, so a filtered sheet always says what it was filtered by.

### 14.7 HR approvals

Leave and OD applications create `approval_requests` rows through `request_approval()` (`app/services/hr.py:153+`). The HR screen shows status and remarks but does not offer a decision button; decisions are made in `#/approvals` or through the HR approval endpoints (`app/services/hr_approvals.py`). HR self-approval is refused (F-66), tested in `tests/test_hr.py:11-47`. Naming an `hr_admin` on a branch or office does not grant approval rights and does not widen data scope; it is a display label for who answers for attendance there.

### 14.8 Branch, office and attendance-rule screens

**Branch** (`hrBranchForm`, `app.js:3346`; `saveHrBranch`, `app.js:3364`)

| UI field | Request field | Schema (`BranchIn` / `BranchPatch`) | Store (`hr_branches`) | Perm |
|---|---|---|---|---|
| Branch code (create only, upper-cased) | `code` | `str`, min 2, unique | `code` | `hr:write` |
| Branch name | `name` | `str`, min 2 | `name` | same |
| Address | `address` | `str \| None` | `address` | same |
| HR responsible | `hr_admin_id` | `int \| None` → `employees.id` | `hr_admin_id` | same |
| Status (edit only) | `status` | `active` / `inactive` | `status` | same |

**Office / work location** (`hrOfficeForm`, `app.js:3380`; `saveHrOffice`, `app.js:3409`)

| UI field | Request field | Schema (`OfficeIn` / `OfficePatch`) | Store (`hr_work_locations`) | Perm |
|---|---|---|---|---|
| Office code (create only, upper-cased) | `code` | `str`, min 2, unique | `code` | `hr:write` |
| Office name | `name` | `str`, min 2 | `name` | same |
| Branch | `branch_id` | `int \| None` → `hr_branches.id` | `branch_id` | same |
| Address | `address` | `str \| None` | `address` | same |
| Latitude, longitude | `latitude`, `longitude` | `Decimal \| None`; **both or neither**, lat −90..90, lon −180..180 | same | same |
| Geofence radius (m) | `geofence_radius_m` | `int`, 1–100 000, default 200 | same | same |
| Attendance mode | `attendance_mode` | `office` / `gps` / `both` | same | same |
| HR responsible | `hr_admin_id` | `int \| None` | same | same |
| Status (edit only) | `status` | `active` / `inactive` | same | same |

The client mirrors the server's coordinate rule (`saveHrOffice`: both-or-neither, range, radius) so the operator sees the error before the request; the schema validator is the control, and a crafted payload cannot store half a geofence centre.

**Attendance rule** (`hrRuleForm`, `app.js:3436`; `saveHrRule`, `app.js:3492`)

| UI field | Request field | Schema (`AttendanceRuleIn` / `AttendanceRulePatch`) | Store (`hr_attendance_rules`) |
|---|---|---|---|
| Branch | `branch_id` | `int \| None` (any) | `branch_id` |
| Office / work location | `office_id` | `int \| None` (any); must belong to `branch_id` when both set | `office_id` |
| Designation | `designation` | `str \| None` (any) | `designation` |
| Employee | `employee_id` | `int \| None` (any) | `employee_id` |
| Attendance | `required` | `bool`, default `true` | `required` |
| Self check-in | `self_service` | `bool`, default `true` | `self_service` |
| Shift | `shift_id` | `int \| None` (office default) | `shift_id` |
| Attendance mode | `attendance_mode` | `office` / `gps` / `both` / `None` (office default) | `attendance_mode` |
| Effective from / to | `effective_from`, `effective_to` | `date \| None`, inclusive; end ≥ start | same |
| Priority | `priority` | `int`, 1–1000, default 100 | `priority` |
| Status | `active` | `bool`, default `true` | `active` |
| Note | `note` | `str \| None`, max 200 | `note` |

**Resolution** (`resolve_attendance_requirement`, `app/services/hr.py`). Candidates are active rules whose dates include the day and whose every filled target matches the employee. Score: employee 1000, office 100, designation 10, branch 1. Order: `(-score, priority, -id)` — most specific first, then the lower priority number, then the newest. No match returns `required: true, self_service: true, source: "Company default"`; a rule targeting only the office returns `source: "Office default (<name>)"`. The chosen rule's shift replaces the employee's shift for that day when set. The screen sorts its table with the same score so the operator can read precedence top-down.

**Server validations the form can trigger.** 404 for an unknown branch, office, employee or shift reference; 422 when the office belongs to another branch, when the named employee is not assigned to that office or branch (the rule could never match), or when `effective_to` precedes `effective_from`; 409 when an active rule targets exactly the same people as another, or when a second company-wide rule is active; 409 when a branch or office with active staff is deactivated or moved to another branch; 409 for a duplicate code. The drawer surfaces `detail` verbatim in its `.err` region.

**Read/write split.** `GET` on branches, offices and rules is `hr:read`; every write is `hr:write`. The drawer renders the New/Edit/Delete controls only for `hr:write`, but the endpoints re-check, so a hidden button is never the only guard.

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
| **M-02** | **Closed** (3 Nov 2026) | The "Not allocated yet" dead end is gone: the drawer sends the party and offers **Existing outstanding** or **Advance / new payment**, and the server records the excess or the whole amount as an advance | `static/js/app.js` (`entryForm`, `syncEntryAgainst`, `saveEntry`); `app/api/accounts.py` (`record_entry`); `app/services/advances.py`; `tests/test_accounts_advances.py` | Money with nothing to settle is recorded as an advance instead of failing 422 | — |
| **M-03** | Medium | Product UQC is never captured | `app.js:911-930,1236-1250`; schema accepts it at `app/api/products.py:30` | Printed GST invoices show "—" for the unit | Add a three-character UQC control |
| **M-04** | Low | Note date is never sent | `app.js:1908-1915`; schemas accept `note_date` | A late note lands in the wrong GST period | Offer an optional, audited note date |
| **M-05** | Low | Movement fields cannot be cleared | `app.js:1883-1892`; `app/api/invoices.py:329-355` | A wrong challan or e-way bill cannot be erased, only replaced | Send explicit nulls for cleared fields |
| **M-06** | **Closed** (3 Nov 2026) | Payroll still does not pay an employee with no active structure, but every skipped employee is now named with the reason in the prepare result, the period screen and the audit entry | `app/services/payroll.py:skipped_employees`; `app/api/hr.py` (`get_period`, `prepare_payroll`); `static/js/app.js` (`hrPayrollOpen`); `tests/test_hr.py` | None: the run and the screen agree, and the screen links to the structure masters | — |
| **M-07** | Low | HR employee screen exposes 11 of the 27 create fields (12 including `status` on edit) | `app.js:646-685`; `app/api/hr.py:83-139` | Bank, PAN, UAN, ESI, emergency and policy data cannot be entered in the browser | Add the remaining fields or a second tab |
| **M-08** | Low | OD screen omits end date, duration, party, worksite, document, regularisation | `app.js:828-849`; `ODIn` schema | Multi-day and regularised OD cannot be created from the browser | Extend the form |
| **M-09** | Low | Manual attendance omits punch times and office | `app.js:766-771`; `ManualAttendanceIn` | A wrong punch cannot be corrected in the browser | Add optional time fields |
| **M-10** | Low | Report sort and paging are applied in memory | `app/api/reports.py:118-132` | Large registers materialise fully before paging | Push ordering and paging into SQL, or cap period length |
| **M-11** | **Fixed** (2 Nov 2026) | HR masters screen added for departments, holidays, leave types, salary components and salary structures; branches and offices already had one | `static/js/app.js` (`hrMasters`, `HR_MASTER_TABS`); `tests/test_hr_masters.py` | A fresh environment can be configured in the browser | Closed; keep the test in place |

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
| `/api/products` | 5 | `product:read`, `product:write` |
| `/api/warehouses` | 2 | `stock:read`, `stock:write` |
| `/api/inventory` | 2 | `stock:read` |
| `/api/purchase-orders` | 5 | `stock:read`, `stock:write` |
| `/api/sales-orders` | 8 | `sales:read`, `sales:write`, `dispatch:write` |
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
| Product category, brand and reorder level | VERIFIED | `tests/test_catalog_orders.py::test_product_grouping_and_reorder_level_round_trip` |
| Product catalog facets | VERIFIED | same file; `GET /api/products/catalog` |
| Sales-order promise date, approval stamp and lateness | VERIFIED | `tests/test_catalog_orders.py` (promise round trip, approval stamp, pipeline reconciliation) |
| Category sales and low-stock attention | VERIFIED | `tests/test_catalog_orders.py`, `tests/test_dashboard_phase2.py` |
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
| HR employee extended fields, holidays, leave types, components, structures | VERIFIED / PARTIAL | Masters screens and structure assignment browser-checked 2 Nov 2026, `tests/test_hr_masters.py`; employee extended fields still UI-partial (M-07) |
| Company profile, tax rates, slabs, quote | VERIFIED (code) | schemas and UI read; fixtures insert directly, no API test |
| Users, roles, permission catalog | VERIFIED | handlers read; catalogue/role parity and authorisation gates asserted by `tests/test_roles_parity.py` and `tests/test_authz.py` |
| Audit trail read | VERIFIED (code) | handler read; export audit is asserted in `tests/test_reports.py:163-181` |
| Print, QR, verification | VERIFIED (code) | handlers read; **no test** |
| Field-level mismatches | VERIFIED (code) | M-01 fixed and browser-verified; M-11 closed and M-06 partly closed on 2 Nov 2026; M-02–M-05 and M-07–M-10 remain source-level findings in Appendix A |

**Nothing in this document certifies a workflow that lacks the cited test or source.** Where a field is accepted but unreachable from the browser, the row is marked PARTIAL or the mismatch is listed in Appendix A rather than being described as working. The current suite has 12 test modules; most write workflows outside products, purchase-order validation, approvals, HR and reports are **not** covered by an executable test.
