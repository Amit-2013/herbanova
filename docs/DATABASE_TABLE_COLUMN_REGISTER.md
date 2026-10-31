# Herbanova — Database table and column register

**Verified:** 31 October 2026 against the live development database (`localhost:5432/herbanova_bcs_dev`) and the ORM at Alembic revision `e4f5a6b7c8d9`. **Scope:** read-only; no row or schema was changed.

**What this register contains:** every application table (50) and every column (604), taken from the database itself, with the matching ORM class, type, nullability, database default, primary/foreign/unique keys, indexes, check constraints and incoming relationships. Inline `#` comments from the model source are reproduced in the Notes column.

**Usage columns are a text-search guide, not proof of use.** `be/ui/rep` counts word-boundary occurrences of the column name in backend code (`app/api`, `app/services`, `app/core`), the browser app (`static/js/app.js`, `static/index.html`) and report builders. Generic names (`id`, `status`, `created_at`) are counted wherever the word appears, so treat the numbers as a pointer for follow-up, not a semantic claim.

**Row counts** are the development dataset on the audit date; they are not a production volume and not a performance benchmark.

| Module | Tables | Columns |
|---|---:|---:|
| Core trading (products, stock, purchase, sales, billing, leads) (`core`) | 22 | 284 |
| Human resources (`hr`) | 19 | 188 |
| Suppliers and goods receipts (`suppliers`) | 3 | 33 |
| Tax and discount configuration (`tax`) | 3 | 47 |
| Users and roles (`users`) | 2 | 39 |
| Receipts and payments (`accounts`) | 1 | 13 |
| **Total** | **50** | **604** |

## Table index

**Core trading (products, stock, purchase, sales, billing, leads)**

- [`approval_requests`](#approval_requests) — One row per action that needs a second person's approval (credit-limit breach, post-billing edit, HR requests). Holds the pending state, the requester and the decision.
- [`audit_log`](#audit_log) — Append-only trail of material actions (who, what, when, before/after payload).
- [`batches`](#batches) — One row per received stock batch: warehouse, batch number, expiry and current on-hand quantity.
- [`credit_note_lines`](#credit_note_lines) — Line items of a credit note (customer return / reduction).
- [`credit_notes`](#credit_notes) — Issued credit notes that reduce a previously issued invoice; consecutive numbering, tax split and grand total.
- [`debit_note_lines`](#debit_note_lines) — Line items of a debit note (additional charge / supplier-side debit).
- [`debit_notes`](#debit_notes) — Issued debit notes that add to a previously issued document; consecutive numbering and tax split.
- [`distributors`](#distributors) — Customer / distributor master, including GSTIN, state, credit limit, discount rule and status.
- [`document_sequences`](#document_sequences) — Consecutive per-financial-year counters behind every document number.
- [`invoice_lines`](#invoice_lines) — Line items of a tax invoice (product, batch, quantity, price, tax split).
- [`invoices`](#invoices) — Issued tax invoices: buyer, place of supply, taxable value, CGST/SGST/IGST/cess, grand total, status.
- [`lead_activities`](#lead_activities) — Append-only activity history for a lead (remark, status change, owner change, follow-up change).
- [`leads`](#leads) — Sales leads with owner, source, status, next follow-up date and closing reason.
- [`print_logs`](#print_logs) — Every printed/verified document with its full and short SHA-256 hash, copy type and actor.
- [`products`](#products) — Product / SKU master with HSN, tax rate, price and status.
- [`purchase_order_lines`](#purchase_order_lines) — Ordered quantities and unit costs per purchase-order line.
- [`purchase_orders`](#purchase_orders) — Purchase orders to suppliers with status and totals.
- [`sales_order_lines`](#sales_order_lines) — Ordered quantities, price and discount per sales-order line.
- [`sales_orders`](#sales_orders) — Sales orders with distributor, status, taxable value, tax and total.
- [`stock_movements`](#stock_movements) — Append-only stock ledger; one row per quantity change with an idempotency key.
- [`users`](#users) — Application users: password hash, role, lockout state, token version.
- [`warehouses`](#warehouses) — Stock locations.

**Human resources**

- [`hr_approval_workflows`](#hr_approval_workflows) — Routing configuration for HR approval requests by request type.
- [`hr_attendance`](#hr_attendance) — One attendance record per employee per day: status, check-in/out, geofence result, late minutes.
- [`hr_attendance_corrections`](#hr_attendance_corrections) — Audited corrections to attendance records (old value, new value, reason, actor).
- [`hr_branches`](#hr_branches) — Branch master for HR posting and report filters.
- [`hr_departments`](#hr_departments) — Department master.
- [`hr_holidays`](#hr_holidays) — Holiday calendar used by attendance and payroll.
- [`hr_leave_applications`](#hr_leave_applications) — Leave applications with dates, reason and approval status.
- [`hr_leave_balances`](#hr_leave_balances) — Per-employee, per-leave-type annual entitlement and consumed balance.
- [`hr_leave_types`](#hr_leave_types) — Leave type master (paid/unpaid, annual quota).
- [`hr_od_requests`](#hr_od_requests) — On-duty requests (outdoor work) with place, purpose, dates and approval status.
- [`hr_payroll_corrections`](#hr_payroll_corrections) — Audited corrections to a payroll entry or period.
- [`hr_payroll_entries`](#hr_payroll_entries) — One payroll result per employee per payroll period (gross, deductions, net).
- [`hr_payroll_entry_lines`](#hr_payroll_entry_lines) — Component-level amounts behind each payroll entry.
- [`hr_payroll_periods`](#hr_payroll_periods) — Payroll run header: month, dates, status and approver.
- [`hr_salary_components`](#hr_salary_components) — Salary component master (earning or deduction, calculation basis).
- [`hr_salary_structure_lines`](#hr_salary_structure_lines) — Component amounts/percentages within a salary structure.
- [`hr_salary_structures`](#hr_salary_structures) — Per-employee salary structure header.
- [`hr_shifts`](#hr_shifts) — Shift master with start/end times and grace period.
- [`hr_work_locations`](#hr_work_locations) — Office / work location master with geofence coordinates and radius.

**Suppliers and goods receipts**

- [`goods_receipt_lines`](#goods_receipt_lines) — Received quantities per purchase-order line.
- [`goods_receipts`](#goods_receipts) — Goods receipt notes (GRN) against purchase orders, with warehouse and status.
- [`suppliers`](#suppliers) — Supplier master, including GSTIN, PAN, bank details and status.

**Tax and discount configuration**

- [`company_profile`](#company_profile) — Single-row company identity, GST details and print settings used on invoices and reports.
- [`discount_slabs`](#discount_slabs) — Quantity-based discount bands used by order pricing.
- [`tax_rates`](#tax_rates) — HSN-to-GST-rate master with effective-from dates, CGST/SGST/IGST/cess rates.

**Users and roles**

- [`employees`](#employees) — Employee master for HR (identity, posting, shift, dates, bank/PF details).
- [`roles`](#roles) — Role definitions and their permission keys.

**Receipts and payments**

- [`payments`](#payments) — Receipts from distributors and payments to suppliers, with allocation to an invoice or note.

---

## Core trading (products, stock, purchase, sales, billing, leads)

### approval_requests

**Purpose:** One row per action that needs a second person's approval (credit-limit breach, post-billing edit, HR requests). Holds the pending state, the requester and the decision.

**ORM:** `ApprovalRequest` · **Rows (dev):** 4 · **Columns:** 16

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('approval_requests_id_seq') | PK |  | 770/821/59 |
| 2 | `record_type` | varchar(30) | no | — | IX |  | 45/1/3 |
| 3 | `record_id` | integer | no | — | IX |  | 38/2/3 |
| 4 | `reasons` | json | no | — | — | ["credit_limit", "discount"] | 33/7/0 |
| 5 | `status` | varchar(20) | no | — | IX | pending/approved/rejected/withdrawn/cancelled | 430/170/49 |
| 6 | `requested_by` | integer | no | — | FK→users.id |  | 29/4/3 |
| 7 | `requested_at` | timestamp | no | now() | — |  | 14/2/8 |
| 8 | `decided_by` | integer | yes | — | FK→users.id |  | 22/4/3 |
| 9 | `decided_at` | timestamp | yes | — | — |  | 22/2/5 |
| 10 | `decision_reason` | varchar(300) | yes | — | — |  | 17/3/3 |
| 11 | `detail` | json | yes | — | — |  | 35/60/0 |
| 12 | `request_no` | varchar(40) | yes | — | IX |  | 10/2/3 |
| 13 | `document_number` | varchar(40) | yes | — | — |  | 27/4/3 |
| 14 | `subject` | varchar(200) | yes | — | — |  | 24/3/3 |
| 15 | `requested_dates` | varchar(80) | yes | — | — |  | 11/2/0 |
| 16 | `pending_approver_role` | varchar(40) | yes | — | — |  | 12/0/3 |

**Indexes:** `ix_approval_requests_request_no` (request_no); `ix_approval_status_type` (status, record_type); `uq_approval_pending` (record_type, record_id) unique

**Foreign keys:** (decided_by) → `users`(id); (requested_by) → `users`(id)

**Referenced by:** nothing


### audit_log

**Purpose:** Append-only trail of material actions (who, what, when, before/after payload).

**ORM:** `AuditLog` · **Rows (dev):** 318 · **Columns:** 6

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('audit_log_id_seq') | PK |  | 770/821/59 |
| 2 | `actor_id` | integer | yes | — | FK→users.id |  | 29/1/0 |
| 3 | `action` | varchar(40) | no | — | — |  | 28/4/0 |
| 4 | `record` | varchar(80) | no | — | — |  | 54/17/4 |
| 5 | `changes` | json | yes | — | — | never include secrets | 77/12/0 |
| 6 | `at` | timestamp | no | now() | — |  | 54/30/8 |

**Foreign keys:** (actor_id) → `users`(id)

**Referenced by:** nothing


### batches

**Purpose:** One row per received stock batch: warehouse, batch number, expiry and current on-hand quantity.

**ORM:** `Batch` · **Rows (dev):** 3 · **Columns:** 7

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('batches_id_seq') | PK |  | 770/821/59 |
| 2 | `product_id` | integer | no | — | FK→products.id, UQ, IX |  | 115/5/14 |
| 3 | `warehouse_id` | integer | no | — | FK→warehouses.id, UQ, IX |  | 43/5/2 |
| 4 | `batch_no` | varchar(40) | no | — | UQ, IX |  | 28/9/0 |
| 5 | `expiry` | date | yes | — | — |  | 59/13/0 |
| 6 | `owner` | varchar(20) | no | — | — | or MANUFACTURER | 51/32/2 |
| 7 | `on_hand` | numeric(14, 3) | no | — | — |  | 16/5/2 |

**Unique constraints:** `batches_product_id_warehouse_id_batch_no_key` (product_id, warehouse_id, batch_no)

**Indexes:** `batches_product_id_warehouse_id_batch_no_key` (product_id, warehouse_id, batch_no) unique

**Foreign keys:** (product_id) → `products`(id); (warehouse_id) → `warehouses`(id)

**Referenced by:** `goods_receipt_lines.batch_id`, `stock_movements.batch_id`

**Check constraints:** `ck_no_negative_stock`: `on_hand >= 0::numeric`


### credit_note_lines

**Purpose:** Line items of a credit note (customer return / reduction).

**ORM:** `CreditNoteLine` · **Rows (dev):** 0 · **Columns:** 13

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('credit_note_lines_id_seq') | PK |  | 770/821/59 |
| 2 | `credit_note_id` | integer | no | — | FK→credit_notes.id |  | 1/0/0 |
| 3 | `invoice_line_id` | integer | no | — | FK→invoice_lines.id |  | 15/2/0 |
| 4 | `product_id` | integer | no | — | FK→products.id |  | 115/5/14 |
| 5 | `sku` | varchar(40) | no | — | — |  | 101/65/4 |
| 6 | `product_name` | varchar(200) | no | — | — |  | 22/9/0 |
| 7 | `qty` | numeric(14, 3) | no | — | — |  | 126/70/13 |
| 8 | `taxable_value` | numeric(14, 2) | no | — | — |  | 51/5/14 |
| 9 | `cgst_amount` | numeric(14, 2) | no | — | — |  | 25/4/0 |
| 10 | `sgst_amount` | numeric(14, 2) | no | — | — |  | 25/4/0 |
| 11 | `igst_amount` | numeric(14, 2) | no | — | — |  | 25/4/0 |
| 12 | `cess_amount` | numeric(14, 2) | no | — | — |  | 25/3/0 |
| 13 | `line_total` | numeric(14, 2) | no | — | — |  | 21/2/0 |

**Foreign keys:** (credit_note_id) → `credit_notes`(id); (invoice_line_id) → `invoice_lines`(id); (product_id) → `products`(id)

**Referenced by:** nothing

**Check constraints:** `ck_credit_note_line_qty_positive`: `qty > 0::numeric`


### credit_notes

**Purpose:** Issued credit notes that reduce a previously issued invoice; consecutive numbering, tax split and grand total.

**ORM:** `CreditNote` · **Rows (dev):** 0 · **Columns:** 22

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('credit_notes_id_seq') | PK |  | 770/821/59 |
| 2 | `credit_note_number` | varchar(16) | no | — | UQ, IX |  | 10/3/2 |
| 3 | `financial_year` | varchar(9) | no | — | UQ, IX |  | 21/1/2 |
| 4 | `invoice_id` | integer | no | — | FK→invoices.id |  | 99/5/18 |
| 5 | `sales_order_id` | integer | no | — | FK→sales_orders.id |  | 27/0/2 |
| 6 | `distributor_id` | integer | no | — | FK→distributors.id |  | 81/5/20 |
| 7 | `status` | varchar(20) | no | — | — |  | 430/170/49 |
| 8 | `note_date` | date | no | — | — |  | 43/2/12 |
| 9 | `reason` | varchar(300) | no | — | — |  | 121/93/4 |
| 10 | `gross_total` | numeric(14, 2) | no | — | — |  | 9/0/1 |
| 11 | `discount_total` | numeric(14, 2) | no | — | — |  | 10/0/1 |
| 12 | `taxable_value` | numeric(14, 2) | no | — | — |  | 51/5/14 |
| 13 | `cgst_total` | numeric(14, 2) | no | — | — |  | 25/1/10 |
| 14 | `sgst_total` | numeric(14, 2) | no | — | — |  | 25/1/10 |
| 15 | `igst_total` | numeric(14, 2) | no | — | — |  | 25/1/10 |
| 16 | `cess_total` | numeric(14, 2) | no | — | — |  | 18/1/2 |
| 17 | `tax_total` | numeric(14, 2) | no | — | — |  | 29/1/4 |
| 18 | `round_off` | numeric(14, 2) | no | — | — |  | 16/3/0 |
| 19 | `grand_total` | numeric(14, 2) | no | — | — |  | 41/8/12 |
| 20 | `issued_by` | integer | no | — | FK→users.id |  | 19/0/0 |
| 21 | `issued_at` | timestamp | no | now() | — |  | 0/0/0 |
| 22 | `return_warehouse_id` | integer | yes | — | FK→warehouses.id |  | 19/0/0 |

**Unique constraints:** `uq_credit_note_number_fy` (credit_note_number, financial_year)

**Indexes:** `ix_credit_notes_credit_note_number` (credit_note_number); `uq_credit_note_number_fy` (credit_note_number, financial_year) unique

**Foreign keys:** (distributor_id) → `distributors`(id); (invoice_id) → `invoices`(id); (issued_by) → `users`(id); (sales_order_id) → `sales_orders`(id); (return_warehouse_id) → `warehouses`(id)

**Referenced by:** `credit_note_lines.credit_note_id`

**Check constraints:** `ck_credit_note_status`: `status::text = ANY (ARRAY['issued'::character varying::text, 'cancelled'::character varying::text])`


### debit_note_lines

**Purpose:** Line items of a debit note (additional charge / supplier-side debit).

**ORM:** `DebitNoteLine` · **Rows (dev):** 0 · **Columns:** 13

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('debit_note_lines_id_seq') | PK |  | 770/821/59 |
| 2 | `debit_note_id` | integer | no | — | FK→debit_notes.id |  | 1/0/0 |
| 3 | `invoice_line_id` | integer | no | — | FK→invoice_lines.id |  | 15/2/0 |
| 4 | `product_id` | integer | no | — | FK→products.id |  | 115/5/14 |
| 5 | `sku` | varchar(40) | no | — | — |  | 101/65/4 |
| 6 | `product_name` | varchar(200) | no | — | — |  | 22/9/0 |
| 7 | `qty` | numeric(14, 3) | no | — | — |  | 126/70/13 |
| 8 | `taxable_value` | numeric(14, 2) | no | — | — |  | 51/5/14 |
| 9 | `cgst_amount` | numeric(14, 2) | no | — | — |  | 25/4/0 |
| 10 | `sgst_amount` | numeric(14, 2) | no | — | — |  | 25/4/0 |
| 11 | `igst_amount` | numeric(14, 2) | no | — | — |  | 25/4/0 |
| 12 | `cess_amount` | numeric(14, 2) | no | — | — |  | 25/3/0 |
| 13 | `line_total` | numeric(14, 2) | no | — | — |  | 21/2/0 |

**Foreign keys:** (debit_note_id) → `debit_notes`(id); (invoice_line_id) → `invoice_lines`(id); (product_id) → `products`(id)

**Referenced by:** nothing

**Check constraints:** `ck_debit_note_line_qty_positive`: `qty > 0::numeric`


### debit_notes

**Purpose:** Issued debit notes that add to a previously issued document; consecutive numbering and tax split.

**ORM:** `DebitNote` · **Rows (dev):** 0 · **Columns:** 19

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('debit_notes_id_seq') | PK |  | 770/821/59 |
| 2 | `debit_note_number` | varchar(16) | no | — | UQ, IX |  | 10/3/2 |
| 3 | `financial_year` | varchar(9) | no | — | UQ, IX |  | 21/1/2 |
| 4 | `invoice_id` | integer | no | — | FK→invoices.id |  | 99/5/18 |
| 5 | `sales_order_id` | integer | no | — | FK→sales_orders.id |  | 27/0/2 |
| 6 | `distributor_id` | integer | no | — | FK→distributors.id |  | 81/5/20 |
| 7 | `status` | varchar(20) | no | — | — |  | 430/170/49 |
| 8 | `note_date` | date | no | — | — |  | 43/2/12 |
| 9 | `reason` | varchar(300) | no | — | — |  | 121/93/4 |
| 10 | `gross_total` | numeric(14, 2) | no | — | — |  | 9/0/1 |
| 11 | `taxable_value` | numeric(14, 2) | no | — | — |  | 51/5/14 |
| 12 | `cgst_total` | numeric(14, 2) | no | — | — |  | 25/1/10 |
| 13 | `sgst_total` | numeric(14, 2) | no | — | — |  | 25/1/10 |
| 14 | `igst_total` | numeric(14, 2) | no | — | — |  | 25/1/10 |
| 15 | `cess_total` | numeric(14, 2) | no | — | — |  | 18/1/2 |
| 16 | `tax_total` | numeric(14, 2) | no | — | — |  | 29/1/4 |
| 17 | `grand_total` | numeric(14, 2) | no | — | — |  | 41/8/12 |
| 18 | `issued_by` | integer | no | — | FK→users.id |  | 19/0/0 |
| 19 | `issued_at` | timestamp | no | now() | — |  | 0/0/0 |

**Unique constraints:** `uq_debit_note_number_fy` (debit_note_number, financial_year)

**Indexes:** `ix_debit_notes_debit_note_number` (debit_note_number); `uq_debit_note_number_fy` (debit_note_number, financial_year) unique

**Foreign keys:** (distributor_id) → `distributors`(id); (invoice_id) → `invoices`(id); (issued_by) → `users`(id); (sales_order_id) → `sales_orders`(id)

**Referenced by:** `debit_note_lines.debit_note_id`

**Check constraints:** `ck_debit_note_status`: `status::text = ANY (ARRAY['issued'::character varying::text, 'cancelled'::character varying::text])`


### distributors

**Purpose:** Customer / distributor master, including GSTIN, state, credit limit, discount rule and status.

**ORM:** `Distributor` · **Rows (dev):** 4 · **Columns:** 17

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('distributors_id_seq') | PK |  | 770/821/59 |
| 2 | `code` | varchar(40) | no | — | IX |  | 226/93/28 |
| 3 | `name` | varchar(150) | no | — | — |  | 227/375/30 |
| 4 | `territory` | varchar(60) | no | — | — |  | 19/12/2 |
| 5 | `status` | varchar(20) | no | — | — | active / blocked | 430/170/49 |
| 6 | `credit_limit` | numeric(14, 2) | no | — | — |  | 31/11/2 |
| 7 | `gstin` | varchar(15) | yes | — | UQ, IX |  | 69/29/8 |
| 8 | `pan` | varchar(10) | yes | — | — |  | 55/20/0 |
| 9 | `state_code` | varchar(2) | yes | — | — |  | 70/15/4 |
| 10 | `registration_type` | varchar(20) | no | 'unregistered' | — |  | 46/15/2 |
| 11 | `billing_address` | varchar(300) | yes | — | — |  | 8/4/0 |
| 12 | `shipping_address` | varchar(300) | yes | — | — |  | 8/4/0 |
| 13 | `contact_person` | varchar(120) | yes | — | — |  | 7/4/0 |
| 14 | `phone` | varchar(40) | yes | — | — |  | 54/40/5 |
| 15 | `email` | varchar(150) | yes | — | — |  | 55/44/4 |
| 16 | `group_name` | varchar(60) | yes | — | — |  | 35/10/0 |
| 17 | `payment_terms_days` | integer | yes | — | — |  | 19/10/4 |

**Unique constraints:** `uq_distributors_gstin` (gstin)

**Indexes:** `ix_distributors_code` (code) unique; `uq_distributors_gstin` (gstin) unique

**Referenced by:** `credit_notes.distributor_id`, `debit_notes.distributor_id`, `invoices.distributor_id`, `payments.distributor_id`, `sales_orders.distributor_id`

**Check constraints:** `ck_credit_limit_nonneg`: `credit_limit >= 0::numeric`; `ck_distributor_payment_terms`: `payment_terms_days IS NULL OR payment_terms_days >= 0`; `ck_distributor_registration_type`: `registration_type::text = ANY (ARRAY['regular'::character varying::text, 'composition'::character varying::text, 'unregistered'::character varying::text])`; `ck_distributor_state_code`: `state_code IS NULL OR length(state_code::text) = 2`


### document_sequences

**Purpose:** Consecutive per-financial-year counters behind every document number.

**ORM:** `DocumentSequence` · **Rows (dev):** 1 · **Columns:** 4

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('document_sequences_id_seq') | PK |  | 770/821/59 |
| 2 | `doc_type` | varchar(20) | no | — | UQ, IX |  | 16/0/0 |
| 3 | `financial_year` | varchar(9) | no | — | UQ, IX |  | 21/1/2 |
| 4 | `last_number` | integer | no | — | — |  | 3/0/0 |

**Unique constraints:** `uq_document_sequence` (doc_type, financial_year)

**Indexes:** `uq_document_sequence` (doc_type, financial_year) unique

**Referenced by:** nothing


### invoice_lines

**Purpose:** Line items of a tax invoice (product, batch, quantity, price, tax split).

**ORM:** `InvoiceLine` · **Rows (dev):** 1 · **Columns:** 23

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('invoice_lines_id_seq') | PK |  | 770/821/59 |
| 2 | `invoice_id` | integer | no | — | FK→invoices.id |  | 99/5/18 |
| 3 | `product_id` | integer | no | — | FK→products.id |  | 115/5/14 |
| 4 | `sku` | varchar(40) | no | — | — |  | 101/65/4 |
| 5 | `product_name` | varchar(200) | no | — | — |  | 22/9/0 |
| 6 | `hsn` | varchar(8) | yes | — | — |  | 71/28/0 |
| 7 | `uqc` | varchar(3) | yes | — | — |  | 13/3/0 |
| 8 | `qty` | numeric(14, 3) | no | — | — |  | 126/70/13 |
| 9 | `unit_price` | numeric(14, 2) | no | — | — |  | 32/6/0 |
| 10 | `mrp` | numeric(14, 2) | no | — | — |  | 32/9/0 |
| 11 | `discount_percent` | numeric(5, 2) | no | — | — |  | 31/13/0 |
| 12 | `discount_amount` | numeric(14, 2) | no | — | — |  | 11/2/0 |
| 13 | `taxable_value` | numeric(14, 2) | no | — | — |  | 51/5/14 |
| 14 | `cgst_rate` | numeric(5, 2) | no | — | — |  | 25/6/0 |
| 15 | `sgst_rate` | numeric(5, 2) | no | — | — |  | 25/6/0 |
| 16 | `igst_rate` | numeric(5, 2) | no | — | — |  | 24/6/0 |
| 17 | `cess_rate` | numeric(5, 2) | no | — | — |  | 22/5/0 |
| 18 | `cgst_amount` | numeric(14, 2) | no | — | — |  | 25/4/0 |
| 19 | `sgst_amount` | numeric(14, 2) | no | — | — |  | 25/4/0 |
| 20 | `igst_amount` | numeric(14, 2) | no | — | — |  | 25/4/0 |
| 21 | `cess_amount` | numeric(14, 2) | no | — | — |  | 25/3/0 |
| 22 | `line_total` | numeric(14, 2) | no | — | — |  | 21/2/0 |
| 23 | `expiry` | date | yes | — | — |  | 59/13/0 |

**Foreign keys:** (invoice_id) → `invoices`(id); (product_id) → `products`(id)

**Referenced by:** `credit_note_lines.invoice_line_id`, `debit_note_lines.invoice_line_id`

**Check constraints:** `ck_invoice_line_price_nonneg`: `unit_price >= 0::numeric`; `ck_invoice_line_qty_positive`: `qty > 0::numeric`


### invoices

**Purpose:** Issued tax invoices: buyer, place of supply, taxable value, CGST/SGST/IGST/cess, grand total, status.

**ORM:** `Invoice` · **Rows (dev):** 1 · **Columns:** 47

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('invoices_id_seq') | PK |  | 770/821/59 |
| 2 | `invoice_number` | varchar(16) | no | — | UQ, IX |  | 50/5/5 |
| 3 | `financial_year` | varchar(9) | no | — | UQ, IX | e.g. 2026-27 | 21/1/2 |
| 4 | `sales_order_id` | integer | no | — | FK→sales_orders.id |  | 27/0/2 |
| 5 | `distributor_id` | integer | no | — | FK→distributors.id |  | 81/5/20 |
| 6 | `status` | varchar(20) | no | — | — |  | 430/170/49 |
| 7 | `invoice_date` | date | no | — | IX |  | 27/2/15 |
| 8 | `place_of_supply_state_code` | varchar(2) | no | — | — |  | 10/1/1 |
| 9 | `place_of_supply_kind` | varchar(10) | no | — | — | intra/inter | 9/1/1 |
| 10 | `reverse_charge` | boolean | no | — | — |  | 17/1/0 |
| 11 | `seller_legal_name` | varchar(200) | no | — | — |  | 8/1/0 |
| 12 | `seller_gstin` | varchar(15) | yes | — | — |  | 5/1/0 |
| 13 | `seller_pan` | varchar(10) | yes | — | — |  | 5/0/0 |
| 14 | `seller_state_code` | varchar(2) | yes | — | — |  | 5/1/0 |
| 15 | `seller_address_line1` | varchar(200) | yes | — | — |  | 2/0/0 |
| 16 | `seller_address_line2` | varchar(200) | yes | — | — |  | 2/0/0 |
| 17 | `seller_city` | varchar(100) | yes | — | — |  | 2/0/0 |
| 18 | `seller_pincode` | varchar(6) | yes | — | — |  | 2/0/0 |
| 19 | `buyer_name` | varchar(150) | no | — | — |  | 7/4/1 |
| 20 | `buyer_gstin` | varchar(15) | yes | — | — |  | 7/2/1 |
| 21 | `buyer_pan` | varchar(10) | yes | — | — |  | 2/0/0 |
| 22 | `buyer_state_code` | varchar(2) | yes | — | — |  | 5/1/0 |
| 23 | `buyer_address_line1` | varchar(300) | yes | — | — |  | 2/0/0 |
| 24 | `buyer_address_line2` | varchar(300) | yes | — | — |  | 2/0/0 |
| 25 | `gross_total` | numeric(14, 2) | no | — | — |  | 9/0/1 |
| 26 | `discount_total` | numeric(14, 2) | no | — | — |  | 10/0/1 |
| 27 | `taxable_value` | numeric(14, 2) | no | — | — |  | 51/5/14 |
| 28 | `cgst_total` | numeric(14, 2) | no | — | — |  | 25/1/10 |
| 29 | `sgst_total` | numeric(14, 2) | no | — | — |  | 25/1/10 |
| 30 | `igst_total` | numeric(14, 2) | no | — | — |  | 25/1/10 |
| 31 | `cess_total` | numeric(14, 2) | no | — | — |  | 18/1/2 |
| 32 | `tax_total` | numeric(14, 2) | no | — | — |  | 29/1/4 |
| 33 | `round_off` | numeric(14, 2) | no | — | — |  | 16/3/0 |
| 34 | `grand_total` | numeric(14, 2) | no | — | — |  | 41/8/12 |
| 35 | `amount_in_words` | varchar(300) | yes | — | — |  | 10/1/0 |
| 36 | `copy_designation` | varchar(20) | no | — | — |  | 11/2/0 |
| 37 | `notes` | json | yes | — | — |  | 69/25/9 |
| 38 | `issued_by` | integer | no | — | FK→users.id |  | 19/0/0 |
| 39 | `issued_at` | timestamp | no | now() | — |  | 0/0/0 |
| 40 | `cancel_reason` | varchar(300) | yes | — | — |  | 15/5/0 |
| 41 | `cancelled_by` | integer | yes | — | FK→users.id |  | 1/0/0 |
| 42 | `cancelled_at` | timestamp | yes | — | — |  | 4/0/0 |
| 43 | `delivery_challan_number` | varchar(30) | yes | — | — |  | 9/5/0 |
| 44 | `vehicle_number` | varchar(20) | yes | — | — |  | 9/5/0 |
| 45 | `transporter_name` | varchar(120) | yes | — | — |  | 9/3/0 |
| 46 | `eway_bill_number` | varchar(30) | yes | — | — |  | 10/3/0 |
| 47 | `eway_bill_date` | date | yes | — | — |  | 9/5/0 |

**Unique constraints:** `uq_invoice_number_fy` (invoice_number, financial_year)

**Indexes:** `ix_invoices_invoice_date` (invoice_date); `ix_invoices_invoice_number` (invoice_number); `uq_invoice_number_fy` (invoice_number, financial_year) unique

**Foreign keys:** (cancelled_by) → `users`(id); (distributor_id) → `distributors`(id); (issued_by) → `users`(id); (sales_order_id) → `sales_orders`(id)

**Referenced by:** `credit_notes.invoice_id`, `debit_notes.invoice_id`, `invoice_lines.invoice_id`, `payments.invoice_id`

**Check constraints:** `ck_invoice_status`: `status::text = ANY (ARRAY['issued'::character varying::text, 'cancelled'::character varying::text])`


### lead_activities

**Purpose:** Append-only activity history for a lead (remark, status change, owner change, follow-up change).

**ORM:** `LeadActivity` · **Rows (dev):** 0 · **Columns:** 6

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('lead_activities_id_seq') | PK |  | 770/821/59 |
| 2 | `lead_id` | integer | no | — | FK→leads.id, IX |  | 29/0/0 |
| 3 | `kind` | varchar(20) | no | — | — | created/note/call/email/meeting/status_change/follow_up_change/owner_change/updated | 146/56/23 |
| 4 | `summary` | varchar(600) | no | — | — |  | 17/7/1 |
| 5 | `actor_id` | integer | no | — | FK→users.id |  | 29/1/0 |
| 6 | `created_at` | timestamp | no | now() | IX |  | 42/6/18 |

**Indexes:** `ix_lead_activities_lead_created` (lead_id, created_at); `ix_lead_activities_lead_id` (lead_id)

**Foreign keys:** (actor_id) → `users`(id); (lead_id) → `leads`(id)

**Referenced by:** nothing


### leads

**Purpose:** Sales leads with owner, source, status, next follow-up date and closing reason.

**ORM:** `Lead` · **Rows (dev):** 0 · **Columns:** 16

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('leads_id_seq') | PK |  | 770/821/59 |
| 2 | `lead_no` | varchar(40) | no | — | IX |  | 18/8/0 |
| 3 | `name` | varchar(150) | no | — | — |  | 227/375/30 |
| 4 | `company` | varchar(150) | yes | — | — |  | 61/36/0 |
| 5 | `phone` | varchar(40) | yes | — | — |  | 54/40/5 |
| 6 | `email` | varchar(150) | yes | — | — |  | 55/44/4 |
| 7 | `phone_key` | varchar(20) | yes | — | UQ, IX | last 10 digits, for duplicate checks | 9/0/0 |
| 8 | `email_key` | varchar(150) | yes | — | UQ, IX | lower-case | 6/0/0 |
| 9 | `source` | varchar(30) | no | — | — |  | 46/16/17 |
| 10 | `status` | varchar(20) | no | — | IX |  | 430/170/49 |
| 11 | `owner_id` | integer | no | — | FK→users.id, IX |  | 21/3/0 |
| 12 | `next_follow_up` | date | yes | — | IX |  | 52/17/0 |
| 13 | `closed_reason` | varchar(300) | yes | — | — |  | 5/5/0 |
| 14 | `created_by` | integer | no | — | FK→users.id |  | 14/2/0 |
| 15 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |
| 16 | `updated_at` | timestamp | no | now() | — |  | 0/0/0 |

**Unique constraints:** `uq_lead_email` (email_key); `uq_lead_phone` (phone_key)

**Indexes:** `ix_leads_lead_no` (lead_no) unique; `ix_leads_owner_followup` (owner_id, next_follow_up); `ix_leads_status_followup` (status, next_follow_up); `uq_lead_email` (email_key) unique; `uq_lead_phone` (phone_key) unique

**Foreign keys:** (created_by) → `users`(id); (owner_id) → `users`(id)

**Referenced by:** `lead_activities.lead_id`

**Check constraints:** `ck_lead_has_contact`: `phone_key IS NOT NULL OR email_key IS NOT NULL`


### print_logs

**Purpose:** Every printed/verified document with its full and short SHA-256 hash, copy type and actor.

**ORM:** `PrintLog` · **Rows (dev):** 7 · **Columns:** 8

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('print_logs_id_seq') | PK |  | 770/821/59 |
| 2 | `document_type` | varchar(20) | no | — | IX |  | 7/1/0 |
| 3 | `document_id` | integer | no | — | — |  | 19/0/0 |
| 4 | `document_number` | varchar(16) | no | — | — |  | 27/4/3 |
| 5 | `copy_designation` | varchar(20) | no | — | — |  | 11/2/0 |
| 6 | `sha256` | varchar(64) | no | — | IX |  | 14/3/0 |
| 7 | `printed_by` | integer | no | — | FK→users.id |  | 28/1/0 |
| 8 | `printed_at` | timestamp | no | now() | — |  | 5/1/0 |

**Indexes:** `ix_print_logs_document_type` (document_type); `ix_print_logs_sha256` (sha256)

**Foreign keys:** (printed_by) → `users`(id)

**Referenced by:** nothing

**Check constraints:** `ck_print_log_copy`: `copy_designation::text = ANY (ARRAY['ORIGINAL'::character varying::text, 'DUPLICATE'::character varying::text, 'TRIPLICATE'::character varying::text])`; `ck_print_log_document_type`: `document_type::text = ANY (ARRAY['invoice'::character varying::text, 'credit_note'::character varying::text, 'debit_note'::character varying::text])`


### products

**Purpose:** Product / SKU master with HSN, tax rate, price and status.

**ORM:** `Product` · **Rows (dev):** 3 · **Columns:** 8

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('products_id_seq') | PK |  | 770/821/59 |
| 2 | `sku` | varchar(40) | no | — | IX |  | 101/65/4 |
| 3 | `name` | varchar(200) | no | — | — |  | 227/375/30 |
| 4 | `pack_size` | varchar(40) | no | — | — |  | 11/4/3 |
| 5 | `mrp` | numeric(14, 2) | no | — | — |  | 32/9/0 |
| 6 | `status` | varchar(20) | no | — | IX |  | 430/170/49 |
| 7 | `hsn` | varchar(8) | yes | — | IX |  | 71/28/0 |
| 8 | `uqc` | varchar(3) | yes | — | — |  | 13/3/0 |

**Indexes:** `ix_products_hsn` (hsn); `ix_products_sku` (sku) unique; `ix_products_status` (status)

**Referenced by:** `batches.product_id`, `credit_note_lines.product_id`, `debit_note_lines.product_id`, `discount_slabs.product_id`, `goods_receipt_lines.product_id`, `invoice_lines.product_id`, `purchase_order_lines.product_id`, `sales_order_lines.product_id`

**Check constraints:** `ck_mrp_nonneg`: `mrp >= 0::numeric`; `ck_product_hsn`: `hsn IS NULL OR length(hsn::text) >= 4 AND length(hsn::text) <= 8`


### purchase_order_lines

**Purpose:** Ordered quantities and unit costs per purchase-order line.

**ORM:** `PurchaseOrderLine` · **Rows (dev):** 5 · **Columns:** 6

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('purchase_order_lines_id_seq') | PK |  | 770/821/59 |
| 2 | `po_id` | integer | no | — | FK→purchase_orders.id, UQ, IX |  | 46/0/12 |
| 3 | `product_id` | integer | no | — | FK→products.id, UQ, IX |  | 115/5/14 |
| 4 | `qty` | numeric(14, 3) | no | — | — |  | 126/70/13 |
| 5 | `unit_cost` | numeric(14, 2) | yes | — | — |  | 10/6/2 |
| 6 | `rate_remark` | varchar(30) | yes | — | — |  | 10/1/0 |

**Unique constraints:** `uq_po_line_product` (po_id, product_id)

**Indexes:** `uq_po_line_product` (po_id, product_id) unique

**Foreign keys:** (po_id) → `purchase_orders`(id); (product_id) → `products`(id)

**Referenced by:** nothing

**Check constraints:** `ck_po_line_cost_nonneg`: `unit_cost IS NULL OR unit_cost >= 0::numeric`; `ck_po_line_cost_or_remark`: `unit_cost IS NOT NULL OR rate_remark IS NOT NULL`; `ck_po_line_qty_positive`: `qty > 0::numeric`


### purchase_orders

**Purpose:** Purchase orders to suppliers with status and totals.

**ORM:** `PurchaseOrder` · **Rows (dev):** 4 · **Columns:** 8

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('purchase_orders_id_seq') | PK |  | 770/821/59 |
| 2 | `po_number` | varchar(40) | no | — | IX |  | 26/9/4 |
| 3 | `supplier` | varchar(120) | no | — | — | display snapshot of the supplier name | 85/42/6 |
| 4 | `status` | varchar(20) | no | 'open' | IX | open/partially_received/received/cancelled | 430/170/49 |
| 5 | `created_by` | integer | no | — | FK→users.id |  | 14/2/0 |
| 6 | `created_at` | timestamp | no | now() | IX |  | 42/6/18 |
| 7 | `supplier_id` | integer | yes | — | FK→suppliers.id |  | 62/6/12 |
| 8 | `cancel_reason` | varchar(300) | yes | — | — |  | 15/5/0 |

**Indexes:** `ix_purchase_orders_po_number` (po_number) unique; `ix_purchase_orders_status_created` (status, created_at)

**Foreign keys:** (supplier_id) → `suppliers`(id); (created_by) → `users`(id)

**Referenced by:** `goods_receipts.po_id`, `payments.purchase_order_id`, `purchase_order_lines.po_id`


### sales_order_lines

**Purpose:** Ordered quantities, price and discount per sales-order line.

**ORM:** `SalesOrderLine` · **Rows (dev):** 2 · **Columns:** 6

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('sales_order_lines_id_seq') | PK |  | 770/821/59 |
| 2 | `order_id` | integer | no | — | FK→sales_orders.id, UQ, IX |  | 17/0/0 |
| 3 | `product_id` | integer | no | — | FK→products.id, UQ, IX |  | 115/5/14 |
| 4 | `qty` | numeric(14, 3) | no | — | — |  | 126/70/13 |
| 5 | `unit_price` | numeric(14, 2) | no | — | — |  | 32/6/0 |
| 6 | `line_total` | numeric(14, 2) | no | — | — |  | 21/2/0 |

**Unique constraints:** `uq_so_line_product` (order_id, product_id)

**Indexes:** `uq_so_line_product` (order_id, product_id) unique

**Foreign keys:** (order_id) → `sales_orders`(id); (product_id) → `products`(id)

**Referenced by:** nothing

**Check constraints:** `ck_so_line_price_nonneg`: `unit_price >= 0::numeric`; `ck_so_line_qty_positive`: `qty > 0::numeric`


### sales_orders

**Purpose:** Sales orders with distributor, status, taxable value, tax and total.

**ORM:** `SalesOrder` · **Rows (dev):** 2 · **Columns:** 12

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('sales_orders_id_seq') | PK |  | 770/821/59 |
| 2 | `so_number` | varchar(40) | no | — | IX |  | 23/8/2 |
| 3 | `distributor_id` | integer | no | — | FK→distributors.id |  | 81/5/20 |
| 4 | `status` | varchar(20) | no | — | IX |  | 430/170/49 |
| 5 | `total` | numeric(14, 2) | no | — | — |  | 108/26/34 |
| 6 | `needs_approval` | boolean | no | — | — |  | 4/0/0 |
| 7 | `created_by` | integer | no | — | FK→users.id |  | 14/2/0 |
| 8 | `submitted_by` | integer | yes | — | FK→users.id |  | 1/0/0 |
| 9 | `dispatched_by` | integer | yes | — | FK→users.id |  | 1/0/0 |
| 10 | `created_at` | timestamp | no | now() | IX |  | 42/6/18 |
| 11 | `dispatched_at` | timestamp | yes | — | — |  | 11/1/2 |
| 12 | `cancel_reason` | varchar(300) | yes | — | — |  | 15/5/0 |

**Indexes:** `ix_sales_orders_so_number` (so_number) unique; `ix_sales_orders_status_created` (status, created_at)

**Foreign keys:** (created_by) → `users`(id); (dispatched_by) → `users`(id); (distributor_id) → `distributors`(id); (submitted_by) → `users`(id)

**Referenced by:** `credit_notes.sales_order_id`, `debit_notes.sales_order_id`, `invoices.sales_order_id`, `sales_order_lines.order_id`


### stock_movements

**Purpose:** Append-only stock ledger; one row per quantity change with an idempotency key.

**ORM:** `StockMovement` · **Rows (dev):** 6 · **Columns:** 8

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('stock_movements_id_seq') | PK |  | 770/821/59 |
| 2 | `batch_id` | integer | no | — | FK→batches.id, UQ, IX |  | 19/0/0 |
| 3 | `movement_type` | varchar(20) | no | — | UQ, IX | receipt/issue/transfer/adjust/return/reversal | 11/5/0 |
| 4 | `qty_delta` | numeric(14, 3) | no | — | — |  | 16/1/1 |
| 5 | `ref_type` | varchar(30) | no | — | UQ, IX |  | 17/0/0 |
| 6 | `ref_id` | varchar(40) | no | — | UQ, IX |  | 28/0/6 |
| 7 | `actor_id` | integer | no | — | FK→users.id |  | 29/1/0 |
| 8 | `created_at` | timestamp | no | now() | IX |  | 42/6/18 |

**Unique constraints:** `uq_movement_idempotency` (batch_id, movement_type, ref_type, ref_id)

**Indexes:** `ix_stock_movements_batch_created` (batch_id, created_at); `uq_movement_idempotency` (batch_id, movement_type, ref_type, ref_id) unique

**Foreign keys:** (actor_id) → `users`(id); (batch_id) → `batches`(id)

**Referenced by:** nothing


### users

**Purpose:** Application users: password hash, role, lockout state, token version.

**ORM:** `User` · **Rows (dev):** 6 · **Columns:** 17

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('users_id_seq') | PK |  | 770/821/59 |
| 2 | `username` | varchar(64) | no | — | UQ, IX |  | 64/26/0 |
| 3 | `password_hash` | varchar(255) | no | — | — |  | 7/0/0 |
| 4 | `role` | varchar(20) | no | — | — | display/legacy copy of the role name | 96/114/1 |
| 5 | `is_active` | boolean | no | — | — |  | 31/11/0 |
| 6 | `username_key` | varchar(64) | yes | — | UQ, IX |  | 4/0/0 |
| 7 | `role_id` | integer | yes | — | FK→roles.id | source of truth for permissions | 20/3/0 |
| 8 | `employee_id` | integer | yes | — | FK→employees.id, UQ, IX |  | 218/15/51 |
| 9 | `must_change_password` | boolean | no | false | — |  | 12/2/0 |
| 10 | `failed_attempts` | integer | no | 0 | — |  | 7/0/0 |
| 11 | `locked_until` | timestamp | yes | — | — |  | 6/0/0 |
| 12 | `token_version` | integer | no | 1 | — |  | 16/0/0 |
| 13 | `password_changed_at` | timestamp | yes | — | — |  | 5/0/0 |
| 14 | `reset_password_secondary_hash` | varchar(255) | yes | — | — |  | 3/0/0 |
| 15 | `secondary_set_at` | timestamp | yes | — | — |  | 1/0/0 |
| 16 | `db_reset_count` | integer | yes | 0 | — |  | 6/0/0 |
| 17 | `db_reset_at` | timestamp | yes | — | — |  | 1/0/0 |

**Unique constraints:** `uq_users_employee_id` (employee_id); `uq_users_username_key` (username_key); `users_username_key` (username)

**Indexes:** `uq_users_employee_id` (employee_id) unique; `uq_users_username_key` (username_key) unique; `users_username_key` (username) unique

**Foreign keys:** (employee_id) → `employees`(id); (role_id) → `roles`(id)

**Referenced by:** `approval_requests.decided_by`, `approval_requests.requested_by`, `audit_log.actor_id`, `credit_notes.issued_by`, `debit_notes.issued_by`, `discount_slabs.created_by`, `employees.user_id`, `goods_receipts.received_by`, `hr_attendance.approved_by`, `hr_attendance_corrections.decided_by`, `hr_attendance_corrections.requested_by`, `hr_leave_applications.created_by`, `hr_leave_applications.decided_by`, `hr_od_requests.created_by`, `hr_od_requests.decided_by`, `hr_payroll_corrections.decided_by`, `hr_payroll_corrections.requested_by`, `hr_payroll_periods.approved_by`, `hr_payroll_periods.prepared_by`, `hr_salary_structures.created_by`, `invoices.cancelled_by`, `invoices.issued_by`, `lead_activities.actor_id`, `leads.created_by`, `leads.owner_id`, `payments.created_by`, `print_logs.printed_by`, `purchase_orders.created_by`, `sales_orders.created_by`, `sales_orders.dispatched_by`, `sales_orders.submitted_by`, `stock_movements.actor_id`, `suppliers.bank_approved_by`, `tax_rates.created_by`


### warehouses

**Purpose:** Stock locations.

**ORM:** `Warehouse` · **Rows (dev):** 4 · **Columns:** 2

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('warehouses_id_seq') | PK |  | 770/821/59 |
| 2 | `name` | varchar(100) | no | — | UQ, IX |  | 227/375/30 |

**Unique constraints:** `warehouses_name_key` (name)

**Indexes:** `warehouses_name_key` (name) unique

**Referenced by:** `batches.warehouse_id`, `credit_notes.return_warehouse_id`, `goods_receipts.warehouse_id`


---

## Human resources

### hr_approval_workflows

**Purpose:** Routing configuration for HR approval requests by request type.

**ORM:** `ApprovalWorkflow` · **Rows (dev):** 6 · **Columns:** 5

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_approval_workflows_id_seq') | PK |  | 770/821/59 |
| 2 | `request_type` | varchar(30) | no | — | UQ, IX |  | 5/1/0 |
| 3 | `level` | integer | no | 1 | UQ, IX |  | 1/2/0 |
| 4 | `approver_role` | varchar(40) | no | — | — |  | 7/0/0 |
| 5 | `active` | boolean | no | true | — |  | 55/45/1 |

**Unique constraints:** `uq_hr_workflow` (request_type, level)

**Indexes:** `uq_hr_workflow` (request_type, level) unique

**Referenced by:** nothing


### hr_attendance

**Purpose:** One attendance record per employee per day: status, check-in/out, geofence result, late minutes.

**ORM:** `Attendance` · **Rows (dev):** 5 · **Columns:** 18

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_attendance_id_seq') | PK |  | 770/821/59 |
| 2 | `employee_id` | integer | no | — | FK→employees.id, UQ, IX |  | 218/15/51 |
| 3 | `date` | date | no | — | UQ, IX |  | 305/76/68 |
| 4 | `status` | varchar(20) | no | 'present' | — |  | 430/170/49 |
| 5 | `check_in` | timestamp | yes | — | — |  | 26/1/4 |
| 6 | `check_out` | timestamp | yes | — | — |  | 25/1/4 |
| 7 | `office_id` | integer | yes | — | FK→hr_work_locations.id |  | 15/5/0 |
| 8 | `source` | varchar(10) | no | 'web' | — |  | 46/16/17 |
| 9 | `latitude` | numeric(9, 6) | yes | — | — |  | 12/2/0 |
| 10 | `longitude` | numeric(9, 6) | yes | — | — |  | 12/2/0 |
| 11 | `geofence_result` | varchar(12) | no | 'na' | — |  | 9/1/0 |
| 12 | `late_minutes` | integer | no | 0 | — |  | 11/1/5 |
| 13 | `early_minutes` | integer | no | 0 | — |  | 8/0/3 |
| 14 | `worked_minutes` | integer | no | 0 | — |  | 12/0/4 |
| 15 | `remarks` | varchar(300) | yes | — | — |  | 33/8/2 |
| 16 | `approved_by` | integer | yes | — | FK→users.id |  | 4/0/0 |
| 17 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |
| 18 | `updated_at` | timestamp | no | now() | — |  | 0/0/0 |

**Unique constraints:** `uq_hr_attendance_employee_date` (employee_id, date)

**Indexes:** `ix_hr_attendance_date` (date); `ix_hr_attendance_employee` (employee_id); `uq_hr_attendance_employee_date` (employee_id, date) unique

**Foreign keys:** (approved_by) → `users`(id); (employee_id) → `employees`(id); (office_id) → `hr_work_locations`(id)

**Referenced by:** `hr_attendance_corrections.attendance_id`

**Check constraints:** `ck_hr_attendance_source`: `source::text = ANY (ARRAY['web'::character varying, 'office'::character varying, 'gps'::character varying, 'manual'::character varying, 'system'::character varying]::text[])`; `ck_hr_attendance_status`: `status::text = ANY (ARRAY['present'::character varying, 'absent'::character varying, 'half_day'::character varying, 'weekly_off'::character varying, 'holiday'::character varying, 'paid_leave'::character varying, 'unpaid_leave'::character varying, 'od'::character varying, 'late'::character varying, 'early_departure'::character varying, 'correction_pending'::character varying]::text[])`; `ck_hr_geofence_result`: `geofence_result::text = ANY (ARRAY['inside'::character varying, 'outside'::character varying, 'unavailable'::character varying, 'manual'::character varying, 'na'::character varying]::text[])`


### hr_attendance_corrections

**Purpose:** Audited corrections to attendance records (old value, new value, reason, actor).

**ORM:** `AttendanceCorrection` · **Rows (dev):** 0 · **Columns:** 16

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_attendance_corrections_id… | PK |  | 770/821/59 |
| 2 | `attendance_id` | integer | no | — | FK→hr_attendance.id, IX |  | 12/0/2 |
| 3 | `employee_id` | integer | no | — | FK→employees.id, IX |  | 218/15/51 |
| 4 | `requested_by` | integer | no | — | FK→users.id |  | 29/4/3 |
| 5 | `old_status` | varchar(20) | yes | — | — |  | 4/0/0 |
| 6 | `new_status` | varchar(20) | yes | — | — |  | 9/0/0 |
| 7 | `old_check_in` | timestamp | yes | — | — |  | 1/0/0 |
| 8 | `new_check_in` | timestamp | yes | — | — |  | 5/0/0 |
| 9 | `old_check_out` | timestamp | yes | — | — |  | 1/0/0 |
| 10 | `new_check_out` | timestamp | yes | — | — |  | 5/0/0 |
| 11 | `reason` | varchar(300) | no | — | — |  | 121/93/4 |
| 12 | `status` | varchar(20) | no | 'pending' | — |  | 430/170/49 |
| 13 | `decided_by` | integer | yes | — | FK→users.id |  | 22/4/3 |
| 14 | `decided_at` | timestamp | yes | — | — |  | 22/2/5 |
| 15 | `remarks` | varchar(300) | yes | — | — |  | 33/8/2 |
| 16 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |

**Indexes:** `ix_hr_attendance_corrections_attendance` (attendance_id); `ix_hr_attendance_corrections_employee` (employee_id)

**Foreign keys:** (attendance_id) → `hr_attendance`(id); (decided_by) → `users`(id); (employee_id) → `employees`(id); (requested_by) → `users`(id)

**Referenced by:** nothing


### hr_branches

**Purpose:** Branch master for HR posting and report filters.

**ORM:** `Branch` · **Rows (dev):** 2 · **Columns:** 5

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_branches_id_seq') | PK |  | 770/821/59 |
| 2 | `code` | varchar(20) | no | — | UQ, IX |  | 226/93/28 |
| 3 | `name` | varchar(120) | no | — | — |  | 227/375/30 |
| 4 | `address` | varchar(300) | yes | — | — |  | 19/5/0 |
| 5 | `status` | varchar(20) | no | 'active' | — |  | 430/170/49 |

**Unique constraints:** `hr_branches_code_key` (code)

**Indexes:** `hr_branches_code_key` (code) unique; `ix_hr_branches_code` (code)

**Referenced by:** `employees.branch_id`, `hr_holidays.branch_id`, `hr_work_locations.branch_id`


### hr_departments

**Purpose:** Department master.

**ORM:** `Department` · **Rows (dev):** 2 · **Columns:** 4

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_departments_id_seq') | PK |  | 770/821/59 |
| 2 | `code` | varchar(20) | no | — | UQ, IX |  | 226/93/28 |
| 3 | `name` | varchar(100) | no | — | UQ, IX |  | 227/375/30 |
| 4 | `status` | varchar(20) | no | 'active' | — |  | 430/170/49 |

**Unique constraints:** `hr_departments_code_key` (code); `hr_departments_name_key` (name)

**Indexes:** `hr_departments_code_key` (code) unique; `hr_departments_name_key` (name) unique

**Referenced by:** `employees.department_id`


### hr_holidays

**Purpose:** Holiday calendar used by attendance and payroll.

**ORM:** `Holiday` · **Rows (dev):** 0 · **Columns:** 5

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_holidays_id_seq') | PK |  | 770/821/59 |
| 2 | `date` | date | no | — | UQ, IX |  | 305/76/68 |
| 3 | `name` | varchar(120) | no | — | UQ, IX |  | 227/375/30 |
| 4 | `branch_id` | integer | yes | — | FK→hr_branches.id |  | 64/9/40 |
| 5 | `location_id` | integer | yes | — | FK→hr_work_locations.id |  | 5/0/0 |

**Unique constraints:** `uq_hr_holiday` (date, name)

**Indexes:** `ix_hr_holidays_date` (date); `uq_hr_holiday` (date, name) unique

**Foreign keys:** (branch_id) → `hr_branches`(id); (location_id) → `hr_work_locations`(id)

**Referenced by:** nothing


### hr_leave_applications

**Purpose:** Leave applications with dates, reason and approval status.

**ORM:** `LeaveApplication` · **Rows (dev):** 1 · **Columns:** 14

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_leave_applications_id_seq') | PK |  | 770/821/59 |
| 2 | `employee_id` | integer | no | — | FK→employees.id, IX |  | 218/15/51 |
| 3 | `leave_type_id` | integer | no | — | FK→hr_leave_types.id |  | 17/3/2 |
| 4 | `date_from` | date | no | — | — |  | 104/6/74 |
| 5 | `date_to` | date | no | — | — |  | 106/6/79 |
| 6 | `days` | numeric(6, 1) | no | — | — |  | 53/10/15 |
| 7 | `reason` | varchar(300) | no | — | — |  | 121/93/4 |
| 8 | `document` | varchar(300) | yes | — | — |  | 91/27/20 |
| 9 | `status` | varchar(20) | no | 'pending' | — |  | 430/170/49 |
| 10 | `created_by` | integer | no | — | FK→users.id |  | 14/2/0 |
| 11 | `decided_by` | integer | yes | — | FK→users.id |  | 22/4/3 |
| 12 | `decided_at` | timestamp | yes | — | — |  | 22/2/5 |
| 13 | `remarks` | varchar(300) | yes | — | — |  | 33/8/2 |
| 14 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |

**Indexes:** `ix_hr_leave_applications_employee` (employee_id)

**Foreign keys:** (created_by) → `users`(id); (decided_by) → `users`(id); (employee_id) → `employees`(id); (leave_type_id) → `hr_leave_types`(id)

**Referenced by:** nothing

**Check constraints:** `ck_hr_leave_dates`: `date_to >= date_from`; `ck_hr_leave_status`: `status::text = ANY (ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'cancelled'::character varying]::text[])`


### hr_leave_balances

**Purpose:** Per-employee, per-leave-type annual entitlement and consumed balance.

**ORM:** `LeaveBalance` · **Rows (dev):** 5 · **Columns:** 8

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_leave_balances_id_seq') | PK |  | 770/821/59 |
| 2 | `employee_id` | integer | no | — | FK→employees.id, UQ, IX |  | 218/15/51 |
| 3 | `leave_type_id` | integer | no | — | FK→hr_leave_types.id, UQ, IX |  | 17/3/2 |
| 4 | `year` | integer | no | — | UQ, IX |  | 83/9/14 |
| 5 | `entitled` | numeric(6, 1) | no | '0' | — |  | 10/1/4 |
| 6 | `used` | numeric(6, 1) | no | '0' | — |  | 19/4/4 |
| 7 | `pending` | numeric(6, 1) | no | '0' | — |  | 67/27/5 |
| 8 | `carried` | numeric(6, 1) | no | '0' | — |  | 14/0/5 |

**Unique constraints:** `uq_hr_leave_balance` (employee_id, leave_type_id, year)

**Indexes:** `ix_hr_leave_balances_employee` (employee_id); `uq_hr_leave_balance` (employee_id, leave_type_id, year) unique

**Foreign keys:** (employee_id) → `employees`(id); (leave_type_id) → `hr_leave_types`(id)

**Referenced by:** nothing


### hr_leave_types

**Purpose:** Leave type master (paid/unpaid, annual quota).

**ORM:** `LeaveType` · **Rows (dev):** 5 · **Columns:** 8

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_leave_types_id_seq') | PK |  | 770/821/59 |
| 2 | `code` | varchar(10) | no | — | UQ, IX |  | 226/93/28 |
| 3 | `name` | varchar(80) | no | — | — |  | 227/375/30 |
| 4 | `kind` | varchar(10) | no | 'paid' | — |  | 146/56/23 |
| 5 | `requires_document` | boolean | no | false | — |  | 4/0/0 |
| 6 | `default_days` | numeric(6, 1) | no | '0' | — |  | 4/0/0 |
| 7 | `carry_forward` | boolean | no | false | — |  | 3/0/0 |
| 8 | `active` | boolean | no | true | — |  | 55/45/1 |

**Unique constraints:** `hr_leave_types_code_key` (code)

**Indexes:** `hr_leave_types_code_key` (code) unique

**Referenced by:** `hr_leave_applications.leave_type_id`, `hr_leave_balances.leave_type_id`

**Check constraints:** `ck_hr_leave_kind`: `kind::text = ANY (ARRAY['paid'::character varying, 'unpaid'::character varying]::text[])`


### hr_od_requests

**Purpose:** On-duty requests (outdoor work) with place, purpose, dates and approval status.

**ORM:** `ODRequest` · **Rows (dev):** 0 · **Columns:** 21

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_od_requests_id_seq') | PK |  | 770/821/59 |
| 2 | `employee_id` | integer | no | — | FK→employees.id, IX |  | 218/15/51 |
| 3 | `date` | date | no | — | IX |  | 305/76/68 |
| 4 | `end_date` | date | yes | — | — |  | 10/0/2 |
| 5 | `duration` | varchar(20) | no | 'full_day' | — |  | 7/0/2 |
| 6 | `visit_type` | varchar(40) | no | — | — |  | 12/5/2 |
| 7 | `purpose` | varchar(300) | no | — | — |  | 12/7/2 |
| 8 | `party_type` | varchar(20) | yes | — | — |  | 3/0/0 |
| 9 | `party_name` | varchar(150) | yes | — | — |  | 5/0/0 |
| 10 | `worksite` | varchar(150) | yes | — | — |  | 3/0/0 |
| 11 | `destination` | varchar(200) | yes | — | — |  | 7/3/2 |
| 12 | `manager_id` | integer | yes | — | FK→employees.id |  | 16/0/0 |
| 13 | `document` | varchar(300) | yes | — | — |  | 91/27/20 |
| 14 | `remarks` | varchar(300) | yes | — | — |  | 33/8/2 |
| 15 | `status` | varchar(20) | no | 'pending' | — |  | 430/170/49 |
| 16 | `regularisation` | boolean | no | false | — |  | 5/0/0 |
| 17 | `created_by` | integer | no | — | FK→users.id |  | 14/2/0 |
| 18 | `decided_by` | integer | yes | — | FK→users.id |  | 22/4/3 |
| 19 | `decided_at` | timestamp | yes | — | — |  | 22/2/5 |
| 20 | `decision_remarks` | varchar(300) | yes | — | — |  | 3/1/0 |
| 21 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |

**Indexes:** `ix_hr_od_requests_date` (date); `ix_hr_od_requests_employee` (employee_id)

**Foreign keys:** (created_by) → `users`(id); (decided_by) → `users`(id); (employee_id) → `employees`(id); (manager_id) → `employees`(id)

**Referenced by:** nothing

**Check constraints:** `ck_hr_od_status`: `status::text = ANY (ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'cancelled'::character varying]::text[])`


### hr_payroll_corrections

**Purpose:** Audited corrections to a payroll entry or period.

**ORM:** `PayrollCorrection` · **Rows (dev):** 0 · **Columns:** 11

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_payroll_corrections_id_seq') | PK |  | 770/821/59 |
| 2 | `period_id` | integer | no | — | FK→hr_payroll_periods.id |  | 27/0/3 |
| 3 | `employee_id` | integer | yes | — | FK→employees.id |  | 218/15/51 |
| 4 | `requested_by` | integer | no | — | FK→users.id |  | 29/4/3 |
| 5 | `reason` | varchar(300) | no | — | — |  | 121/93/4 |
| 6 | `old_net` | numeric(14, 2) | yes | — | — |  | 0/0/0 |
| 7 | `new_net` | numeric(14, 2) | yes | — | — |  | 1/0/0 |
| 8 | `status` | varchar(20) | no | 'pending' | — |  | 430/170/49 |
| 9 | `decided_by` | integer | yes | — | FK→users.id |  | 22/4/3 |
| 10 | `decided_at` | timestamp | yes | — | — |  | 22/2/5 |
| 11 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |

**Foreign keys:** (decided_by) → `users`(id); (employee_id) → `employees`(id); (period_id) → `hr_payroll_periods`(id); (requested_by) → `users`(id)

**Referenced by:** nothing


### hr_payroll_entries

**Purpose:** One payroll result per employee per payroll period (gross, deductions, net).

**ORM:** `PayrollEntry` · **Rows (dev):** 1 · **Columns:** 13

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_payroll_entries_id_seq') | PK |  | 770/821/59 |
| 2 | `period_id` | integer | no | — | FK→hr_payroll_periods.id, UQ, IX |  | 27/0/3 |
| 3 | `employee_id` | integer | no | — | FK→employees.id, UQ, IX |  | 218/15/51 |
| 4 | `working_days` | numeric(6, 1) | no | '0' | — |  | 16/0/2 |
| 5 | `payable_days` | numeric(6, 1) | no | '0' | — |  | 8/1/2 |
| 6 | `present_days` | numeric(6, 1) | no | '0' | — |  | 6/0/2 |
| 7 | `paid_leave_days` | numeric(6, 1) | no | '0' | — |  | 6/0/2 |
| 8 | `lop_days` | numeric(6, 1) | no | '0' | — |  | 8/1/2 |
| 9 | `gross` | numeric(14, 2) | no | '0' | — |  | 33/3/3 |
| 10 | `deductions` | numeric(14, 2) | no | '0' | — |  | 14/1/3 |
| 11 | `net` | numeric(14, 2) | no | '0' | — |  | 24/2/9 |
| 12 | `status` | varchar(20) | no | 'draft' | — |  | 430/170/49 |
| 13 | `note` | varchar(300) | yes | — | — |  | 131/85/15 |

**Unique constraints:** `uq_hr_payroll_entry` (period_id, employee_id)

**Indexes:** `ix_hr_payroll_entries_employee` (employee_id); `uq_hr_payroll_entry` (period_id, employee_id) unique

**Foreign keys:** (employee_id) → `employees`(id); (period_id) → `hr_payroll_periods`(id)

**Referenced by:** `hr_payroll_entry_lines.entry_id`


### hr_payroll_entry_lines

**Purpose:** Component-level amounts behind each payroll entry.

**ORM:** `PayrollEntryLine` · **Rows (dev):** 4 · **Columns:** 7

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_payroll_entry_lines_id_seq') | PK |  | 770/821/59 |
| 2 | `entry_id` | integer | no | — | FK→hr_payroll_entries.id |  | 9/0/4 |
| 3 | `component_id` | integer | yes | — | FK→hr_salary_components.id |  | 15/0/0 |
| 4 | `name` | varchar(80) | no | — | — |  | 227/375/30 |
| 5 | `kind` | varchar(10) | no | — | — |  | 146/56/23 |
| 6 | `amount` | numeric(14, 2) | no | '0' | — |  | 79/8/30 |
| 7 | `basis` | varchar(200) | yes | — | — |  | 15/0/0 |

**Foreign keys:** (component_id) → `hr_salary_components`(id); (entry_id) → `hr_payroll_entries`(id)

**Referenced by:** nothing


### hr_payroll_periods

**Purpose:** Payroll run header: month, dates, status and approver.

**ORM:** `PayrollPeriod` · **Rows (dev):** 1 · **Columns:** 11

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_payroll_periods_id_seq') | PK |  | 770/821/59 |
| 2 | `year` | integer | no | — | UQ, IX |  | 83/9/14 |
| 3 | `month` | integer | no | — | UQ, IX |  | 48/11/7 |
| 4 | `status` | varchar(20) | no | 'draft' | — |  | 430/170/49 |
| 5 | `prepared_by` | integer | yes | — | FK→users.id |  | 2/0/0 |
| 6 | `prepared_at` | timestamp | yes | — | — |  | 3/0/0 |
| 7 | `approved_by` | integer | yes | — | FK→users.id |  | 4/0/0 |
| 8 | `approved_at` | timestamp | yes | — | — |  | 3/0/0 |
| 9 | `processed_at` | timestamp | yes | — | — |  | 3/0/0 |
| 10 | `paid_at` | timestamp | yes | — | — |  | 3/0/0 |
| 11 | `notes` | varchar(300) | yes | — | — |  | 69/25/9 |

**Unique constraints:** `uq_hr_payroll_period` (year, month)

**Indexes:** `uq_hr_payroll_period` (year, month) unique

**Foreign keys:** (approved_by) → `users`(id); (prepared_by) → `users`(id)

**Referenced by:** `hr_payroll_corrections.period_id`, `hr_payroll_entries.period_id`

**Check constraints:** `ck_hr_payroll_month`: `month >= 1 AND month <= 12`; `ck_hr_payroll_period_status`: `status::text = ANY (ARRAY['draft'::character varying, 'under_review'::character varying, 'approved'::character varying, 'processed'::character varying, 'paid'::character varying]::text[])`


### hr_salary_components

**Purpose:** Salary component master (earning or deduction, calculation basis).

**ORM:** `SalaryComponent` · **Rows (dev):** 11 · **Columns:** 10

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_salary_components_id_seq') | PK |  | 770/821/59 |
| 2 | `code` | varchar(20) | no | — | UQ, IX |  | 226/93/28 |
| 3 | `name` | varchar(80) | no | — | — |  | 227/375/30 |
| 4 | `kind` | varchar(10) | no | — | — |  | 146/56/23 |
| 5 | `calc_type` | varchar(20) | no | 'fixed' | — |  | 8/0/0 |
| 6 | `default_rate` | numeric(10, 4) | no | '0' | — |  | 8/0/0 |
| 7 | `taxable` | boolean | no | true | — |  | 41/3/13 |
| 8 | `statutory` | boolean | no | false | — |  | 8/0/2 |
| 9 | `active` | boolean | no | true | — |  | 55/45/1 |
| 10 | `sort_order` | integer | no | 0 | — |  | 4/0/0 |

**Unique constraints:** `hr_salary_components_code_key` (code)

**Indexes:** `hr_salary_components_code_key` (code) unique

**Referenced by:** `hr_payroll_entry_lines.component_id`, `hr_salary_structure_lines.component_id`

**Check constraints:** `ck_hr_component_calc`: `calc_type::text = ANY (ARRAY['fixed'::character varying, 'percent_basic'::character varying, 'percent_gross'::character varying]::text[])`; `ck_hr_component_kind`: `kind::text = ANY (ARRAY['earning'::character varying, 'deduction'::character varying]::text[])`


### hr_salary_structure_lines

**Purpose:** Component amounts/percentages within a salary structure.

**ORM:** `SalaryStructureLine` · **Rows (dev):** 4 · **Columns:** 5

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_salary_structure_lines_id… | PK |  | 770/821/59 |
| 2 | `structure_id` | integer | no | — | FK→hr_salary_structures.id, UQ, IX |  | 1/0/0 |
| 3 | `component_id` | integer | no | — | FK→hr_salary_components.id, UQ, IX |  | 15/0/0 |
| 4 | `amount` | numeric(14, 2) | no | '0' | — |  | 79/8/30 |
| 5 | `percent` | numeric(6, 2) | yes | — | — |  | 12/1/0 |

**Unique constraints:** `uq_hr_structure_component` (structure_id, component_id)

**Indexes:** `uq_hr_structure_component` (structure_id, component_id) unique

**Foreign keys:** (component_id) → `hr_salary_components`(id); (structure_id) → `hr_salary_structures`(id)

**Referenced by:** nothing


### hr_salary_structures

**Purpose:** Per-employee salary structure header.

**ORM:** `SalaryStructure` · **Rows (dev):** 1 · **Columns:** 8

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_salary_structures_id_seq') | PK |  | 770/821/59 |
| 2 | `employee_id` | integer | no | — | FK→employees.id, IX |  | 218/15/51 |
| 3 | `effective_from` | date | no | — | — |  | 57/10/0 |
| 4 | `effective_to` | date | yes | — | — |  | 53/16/0 |
| 5 | `payment_mode` | varchar(20) | no | 'bank' | — |  | 5/0/0 |
| 6 | `status` | varchar(20) | no | 'active' | — |  | 430/170/49 |
| 7 | `created_by` | integer | yes | — | FK→users.id |  | 14/2/0 |
| 8 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |

**Indexes:** `ix_hr_salary_structures_employee` (employee_id)

**Foreign keys:** (created_by) → `users`(id); (employee_id) → `employees`(id)

**Referenced by:** `hr_salary_structure_lines.structure_id`


### hr_shifts

**Purpose:** Shift master with start/end times and grace period.

**ORM:** `Shift` · **Rows (dev):** 1 · **Columns:** 9

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_shifts_id_seq') | PK |  | 770/821/59 |
| 2 | `name` | varchar(80) | no | — | UQ, IX |  | 227/375/30 |
| 3 | `start_time` | time | no | '09:00:00' | — |  | 11/8/0 |
| 4 | `end_time` | time | no | '18:00:00' | — |  | 9/8/0 |
| 5 | `grace_minutes` | integer | no | 10 | — |  | 5/7/0 |
| 6 | `full_day_hours` | numeric(6, 2) | no | '8' | — |  | 4/6/0 |
| 7 | `half_day_hours` | numeric(6, 2) | no | '4' | — |  | 4/6/0 |
| 8 | `weekly_offs` | json | no | '[5, 6]' | — | Mon=0 .. Sun=6 | 8/4/0 |
| 9 | `status` | varchar(20) | no | 'active' | — |  | 430/170/49 |

**Unique constraints:** `hr_shifts_name_key` (name)

**Indexes:** `hr_shifts_name_key` (name) unique

**Referenced by:** `employees.shift_id`


### hr_work_locations

**Purpose:** Office / work location master with geofence coordinates and radius.

**ORM:** `WorkLocation` · **Rows (dev):** 2 · **Columns:** 10

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('hr_work_locations_id_seq') | PK |  | 770/821/59 |
| 2 | `branch_id` | integer | yes | — | FK→hr_branches.id |  | 64/9/40 |
| 3 | `code` | varchar(20) | no | — | UQ, IX |  | 226/93/28 |
| 4 | `name` | varchar(120) | no | — | — |  | 227/375/30 |
| 5 | `address` | varchar(300) | yes | — | — |  | 19/5/0 |
| 6 | `latitude` | numeric(9, 6) | yes | — | — |  | 12/2/0 |
| 7 | `longitude` | numeric(9, 6) | yes | — | — |  | 12/2/0 |
| 8 | `geofence_radius_m` | integer | yes | 200 | — |  | 5/0/0 |
| 9 | `attendance_mode` | varchar(10) | no | 'office' | — |  | 5/0/0 |
| 10 | `status` | varchar(20) | no | 'active' | — |  | 430/170/49 |

**Unique constraints:** `hr_work_locations_code_key` (code)

**Indexes:** `hr_work_locations_code_key` (code) unique; `ix_hr_work_locations_code` (code)

**Foreign keys:** (branch_id) → `hr_branches`(id)

**Referenced by:** `employees.office_id`, `hr_attendance.office_id`, `hr_holidays.location_id`

**Check constraints:** `ck_hr_lat`: `latitude IS NULL OR latitude >= '-90'::integer::numeric AND latitude <= 90::numeric`; `ck_hr_lon`: `longitude IS NULL OR longitude >= '-180'::integer::numeric AND longitude <= 180::numeric`; `ck_hr_mode`: `attendance_mode::text = ANY (ARRAY['office'::character varying, 'gps'::character varying, 'both'::character varying]::text[])`; `ck_hr_radius`: `geofence_radius_m IS NULL OR geofence_radius_m > 0`


---

## Suppliers and goods receipts

### goods_receipt_lines

**Purpose:** Received quantities per purchase-order line.

**ORM:** `GoodsReceiptLine` · **Rows (dev):** 5 · **Columns:** 5

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('goods_receipt_lines_id_seq') | PK |  | 770/821/59 |
| 2 | `grn_id` | integer | no | — | FK→goods_receipts.id, UQ, IX |  | 5/0/2 |
| 3 | `product_id` | integer | no | — | FK→products.id |  | 115/5/14 |
| 4 | `batch_id` | integer | no | — | FK→batches.id, UQ, IX |  | 19/0/0 |
| 5 | `qty` | numeric(14, 3) | no | — | — |  | 126/70/13 |

**Unique constraints:** `uq_grn_line_batch` (grn_id, batch_id)

**Indexes:** `uq_grn_line_batch` (grn_id, batch_id) unique

**Foreign keys:** (batch_id) → `batches`(id); (grn_id) → `goods_receipts`(id); (product_id) → `products`(id)

**Referenced by:** nothing

**Check constraints:** `ck_grn_line_qty_positive`: `qty > 0::numeric`


### goods_receipts

**Purpose:** Goods receipt notes (GRN) against purchase orders, with warehouse and status.

**ORM:** `GoodsReceipt` · **Rows (dev):** 4 · **Columns:** 9

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('goods_receipts_id_seq') | PK |  | 770/821/59 |
| 2 | `grn_number` | varchar(40) | no | — | IX |  | 11/3/2 |
| 3 | `po_id` | integer | no | — | FK→purchase_orders.id, IX |  | 46/0/12 |
| 4 | `warehouse_id` | integer | no | — | FK→warehouses.id |  | 43/5/2 |
| 5 | `received_by` | integer | no | — | FK→users.id |  | 3/0/2 |
| 6 | `owner` | varchar(20) | no | 'HERBANOVA' | — | HERBANOVA / MANUFACTURER | 51/32/2 |
| 7 | `delivery_note` | varchar(60) | yes | — | IX |  | 11/4/2 |
| 8 | `note` | varchar(300) | yes | — | — |  | 131/85/15 |
| 9 | `received_at` | timestamp | no | now() | — |  | 8/1/5 |

**Indexes:** `ix_goods_receipts_grn_number` (grn_number) unique; `ix_goods_receipts_po_id` (po_id); `uq_grn_delivery_note` (po_id, delivery_note) unique

**Foreign keys:** (po_id) → `purchase_orders`(id); (received_by) → `users`(id); (warehouse_id) → `warehouses`(id)

**Referenced by:** `goods_receipt_lines.grn_id`

**Check constraints:** `ck_grn_owner`: `owner::text = ANY (ARRAY['HERBANOVA'::character varying::text, 'MANUFACTURER'::character varying::text])`


### suppliers

**Purpose:** Supplier master, including GSTIN, PAN, bank details and status.

**ORM:** `Supplier` · **Rows (dev):** 2 · **Columns:** 19

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('suppliers_id_seq') | PK |  | 770/821/59 |
| 2 | `code` | varchar(30) | no | — | IX |  | 226/93/28 |
| 3 | `name` | varchar(150) | no | — | — |  | 227/375/30 |
| 4 | `kind` | varchar(20) | no | 'supplier' | — |  | 146/56/23 |
| 5 | `registration_type` | varchar(20) | no | 'regular' | — |  | 46/15/2 |
| 6 | `gstin` | varchar(15) | yes | — | UQ, IX |  | 69/29/8 |
| 7 | `pan` | varchar(10) | yes | — | — |  | 55/20/0 |
| 8 | `state_code` | varchar(2) | yes | — | — |  | 70/15/4 |
| 9 | `payment_terms_days` | integer | no | 30 | — |  | 19/10/4 |
| 10 | `status` | varchar(20) | no | 'active' | — |  | 430/170/49 |
| 11 | `needs_completion` | boolean | no | false | — |  | 10/8/2 |
| 12 | `bank_name` | varchar(120) | yes | — | — |  | 12/11/0 |
| 13 | `bank_account_no` | varchar(30) | yes | — | — |  | 13/4/0 |
| 14 | `bank_ifsc` | varchar(11) | yes | — | — |  | 14/9/0 |
| 15 | `bank_holder` | varchar(120) | yes | — | — |  | 5/4/0 |
| 16 | `bank_approved_by` | integer | yes | — | FK→users.id |  | 1/0/0 |
| 17 | `bank_approved_at` | timestamp | yes | — | — |  | 4/2/0 |
| 18 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |
| 19 | `updated_at` | timestamp | no | now() | — |  | 0/0/0 |

**Unique constraints:** `uq_suppliers_gstin` (gstin)

**Indexes:** `ix_suppliers_code` (code) unique; `uq_suppliers_gstin` (gstin) unique

**Foreign keys:** (bank_approved_by) → `users`(id)

**Referenced by:** `payments.supplier_id`, `purchase_orders.supplier_id`

**Check constraints:** `ck_supplier_kind`: `kind::text = ANY (ARRAY['supplier'::character varying::text, 'manufacturer'::character varying::text, 'both'::character varying::text])`; `ck_supplier_registration_type`: `registration_type::text = ANY (ARRAY['regular'::character varying::text, 'composition'::character varying::text, 'unregistered'::character varying::text])`; `ck_supplier_status`: `status::text = ANY (ARRAY['active'::character varying::text, 'blocked'::character varying::text])`; `ck_supplier_terms_nonneg`: `payment_terms_days >= 0`


---

## Tax and discount configuration

### company_profile

**Purpose:** Single-row company identity, GST details and print settings used on invoices and reports.

**ORM:** `CompanyProfile` · **Rows (dev):** 1 · **Columns:** 19

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('company_profile_id_seq') | PK |  | 770/821/59 |
| 2 | `legal_name` | varchar(200) | no | — | — |  | 12/6/0 |
| 3 | `trade_name` | varchar(200) | yes | — | — |  | 4/5/0 |
| 4 | `gstin` | varchar(15) | yes | — | UQ, IX |  | 69/29/8 |
| 5 | `pan` | varchar(10) | yes | — | — |  | 55/20/0 |
| 6 | `state_code` | varchar(2) | yes | — | — |  | 70/15/4 |
| 7 | `registration_type` | varchar(20) | no | 'regular' | — |  | 46/15/2 |
| 8 | `address_line1` | varchar(200) | yes | — | — |  | 6/5/0 |
| 9 | `address_line2` | varchar(200) | yes | — | — |  | 6/5/0 |
| 10 | `city` | varchar(100) | yes | — | — |  | 6/7/0 |
| 11 | `pincode` | varchar(6) | yes | — | — |  | 6/5/0 |
| 12 | `phone` | varchar(30) | yes | — | — |  | 54/40/5 |
| 13 | `email` | varchar(150) | yes | — | — |  | 55/44/4 |
| 14 | `invoice_prefix` | varchar(10) | yes | — | — |  | 5/5/0 |
| 15 | `bank_name` | varchar(120) | yes | — | — |  | 12/11/0 |
| 16 | `bank_account_name` | varchar(150) | yes | — | — |  | 4/5/0 |
| 17 | `bank_account_number` | varchar(40) | yes | — | — |  | 8/3/0 |
| 18 | `bank_ifsc` | varchar(20) | yes | — | — |  | 14/9/0 |
| 19 | `updated_at` | timestamp | no | now() | — |  | 0/0/0 |

**Unique constraints:** `uq_company_profile_gstin` (gstin)

**Indexes:** `uq_company_profile_gstin` (gstin) unique

**Referenced by:** nothing

**Check constraints:** `ck_company_registration_type`: `registration_type::text = ANY (ARRAY['regular'::character varying::text, 'composition'::character varying::text, 'unregistered'::character varying::text])`; `ck_company_state_code`: `state_code IS NULL OR length(state_code::text) = 2`


### discount_slabs

**Purpose:** Quantity-based discount bands used by order pricing.

**ORM:** `DiscountSlab` · **Rows (dev):** 0 · **Columns:** 16

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('discount_slabs_id_seq') | PK |  | 770/821/59 |
| 2 | `name` | varchar(100) | no | — | — |  | 227/375/30 |
| 3 | `scope` | varchar(20) | no | 'all' | — | all / product / group | 25/16/0 |
| 4 | `product_id` | integer | yes | — | FK→products.id |  | 115/5/14 |
| 5 | `group_name` | varchar(60) | yes | — | — | distributor group | 35/10/0 |
| 6 | `min_qty` | numeric(14, 3) | yes | — | — |  | 17/4/0 |
| 7 | `max_qty` | numeric(14, 3) | yes | — | — |  | 16/4/0 |
| 8 | `min_value` | numeric(14, 2) | yes | — | — |  | 17/4/0 |
| 9 | `max_value` | numeric(14, 2) | yes | — | — |  | 16/4/0 |
| 10 | `discount_percent` | numeric(5, 2) | no | — | — |  | 31/13/0 |
| 11 | `approval_above` | numeric(5, 2) | yes | — | — |  | 17/14/0 |
| 12 | `effective_from` | date | no | — | — |  | 57/10/0 |
| 13 | `effective_to` | date | yes | — | — |  | 53/16/0 |
| 14 | `is_active` | boolean | no | true | — |  | 31/11/0 |
| 15 | `created_by` | integer | no | — | FK→users.id |  | 14/2/0 |
| 16 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |

**Foreign keys:** (created_by) → `users`(id); (product_id) → `products`(id)

**Referenced by:** nothing

**Check constraints:** `ck_discount_slab_approval`: `approval_above IS NULL OR approval_above >= 0::numeric AND approval_above <= 100::numeric`; `ck_discount_slab_bound`: `min_qty IS NOT NULL OR min_value IS NOT NULL`; `ck_discount_slab_group`: `scope::text <> 'group'::text OR group_name IS NOT NULL`; `ck_discount_slab_min_qty`: `min_qty IS NULL OR min_qty > 0::numeric`; `ck_discount_slab_min_value`: `min_value IS NULL OR min_value > 0::numeric`; `ck_discount_slab_percent`: `discount_percent >= 0::numeric AND discount_percent <= 100::numeric`; `ck_discount_slab_product`: `scope::text <> 'product'::text OR product_id IS NOT NULL`; `ck_discount_slab_qty_band`: `max_qty IS NULL OR min_qty IS NULL OR max_qty >= min_qty`; `ck_discount_slab_scope`: `scope::text = ANY (ARRAY['all'::character varying::text, 'product'::character varying::text, 'group'::character varying::text])`; `ck_discount_slab_value_band`: `max_value IS NULL OR min_value IS NULL OR max_value >= min_value`; `ck_discount_slab_window`: `effective_to IS NULL OR effective_to >= effective_from`


### tax_rates

**Purpose:** HSN-to-GST-rate master with effective-from dates, CGST/SGST/IGST/cess rates.

**ORM:** `TaxRate` · **Rows (dev):** 1 · **Columns:** 12

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('tax_rates_id_seq') | PK |  | 770/821/59 |
| 2 | `hsn` | varchar(8) | no | — | IX |  | 71/28/0 |
| 3 | `description` | varchar(200) | yes | — | — |  | 11/10/1 |
| 4 | `cgst_rate` | numeric(5, 2) | no | — | — |  | 25/6/0 |
| 5 | `sgst_rate` | numeric(5, 2) | no | — | — |  | 25/6/0 |
| 6 | `igst_rate` | numeric(5, 2) | no | — | — |  | 24/6/0 |
| 7 | `cess_rate` | numeric(5, 2) | no | '0' | — |  | 22/5/0 |
| 8 | `is_reverse_charge` | boolean | no | false | — |  | 8/4/0 |
| 9 | `effective_from` | date | no | — | IX |  | 57/10/0 |
| 10 | `effective_to` | date | yes | — | — | NULL = still in force | 53/16/0 |
| 11 | `created_by` | integer | no | — | FK→users.id |  | 14/2/0 |
| 12 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |

**Indexes:** `ix_tax_rates_hsn_from` (hsn, effective_from)

**Foreign keys:** (created_by) → `users`(id)

**Referenced by:** nothing

**Check constraints:** `ck_tax_rate_hsn_digits`: `length(hsn::text) >= 4 AND length(hsn::text) <= 8`; `ck_tax_rate_nonneg`: `cgst_rate >= 0::numeric AND sgst_rate >= 0::numeric AND igst_rate >= 0::numeric AND cess_rate >= 0::numeric`; `ck_tax_rate_split`: `(cgst_rate + sgst_rate) = igst_rate`; `ck_tax_rate_window`: `effective_to IS NULL OR effective_to >= effective_from`


---

## Users and roles

### employees

**Purpose:** Employee master for HR (identity, posting, shift, dates, bank/PF details).

**ORM:** `Employee` · **Rows (dev):** 5 · **Columns:** 33

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('employees_id_seq') | PK |  | 770/821/59 |
| 2 | `code` | varchar(30) | no | — | IX |  | 226/93/28 |
| 3 | `full_name` | varchar(120) | no | — | — |  | 40/18/19 |
| 4 | `department` | varchar(60) | yes | — | — |  | 76/19/41 |
| 5 | `designation` | varchar(80) | yes | — | — |  | 12/12/4 |
| 6 | `phone` | varchar(40) | yes | — | — |  | 54/40/5 |
| 7 | `email` | varchar(120) | yes | — | — |  | 55/44/4 |
| 8 | `joining_date` | date | yes | — | — |  | 13/5/5 |
| 9 | `manager_id` | integer | yes | — | FK→employees.id |  | 16/0/0 |
| 10 | `status` | varchar(20) | no | 'active' | — | active / inactive | 430/170/49 |
| 11 | `user_id` | integer | yes | — | FK→users.id, UQ, IX |  | 27/1/0 |
| 12 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |
| 13 | `updated_at` | timestamp | no | now() | — |  | 0/0/0 |
| 14 | `branch_id` | integer | yes | — | FK→hr_branches.id |  | 64/9/40 |
| 15 | `office_id` | integer | yes | — | FK→hr_work_locations.id |  | 15/5/0 |
| 16 | `department_id` | integer | yes | — | FK→hr_departments.id |  | 3/0/0 |
| 17 | `shift_id` | integer | yes | — | FK→hr_shifts.id |  | 14/5/0 |
| 18 | `employment_type` | varchar(30) | yes | — | — |  | 3/4/0 |
| 19 | `work_schedule` | varchar(80) | yes | — | — |  | 3/0/0 |
| 20 | `date_of_exit` | date | yes | — | — |  | 10/0/5 |
| 21 | `photo_path` | varchar(300) | yes | — | — |  | 0/0/0 |
| 22 | `address` | varchar(300) | yes | — | — |  | 19/5/0 |
| 23 | `emergency_name` | varchar(120) | yes | — | — |  | 3/0/0 |
| 24 | `emergency_phone` | varchar(40) | yes | — | — |  | 3/0/0 |
| 25 | `bank_name` | varchar(120) | yes | — | — |  | 12/11/0 |
| 26 | `bank_account_no` | varchar(30) | yes | — | — |  | 13/4/0 |
| 27 | `bank_ifsc` | varchar(11) | yes | — | — |  | 14/9/0 |
| 28 | `pan` | varchar(10) | yes | — | — |  | 55/20/0 |
| 29 | `uan` | varchar(20) | yes | — | — |  | 3/0/0 |
| 30 | `esi_no` | varchar(20) | yes | — | — |  | 3/0/0 |
| 31 | `attendance_policy` | varchar(80) | yes | — | — |  | 3/0/0 |
| 32 | `leave_policy` | varchar(80) | yes | — | — |  | 3/0/0 |
| 33 | `hr_admin_id` | integer | yes | — | FK→employees.id |  | 3/0/0 |

**Unique constraints:** `uq_employees_user` (user_id)

**Indexes:** `ix_employees_code` (code) unique; `uq_employees_user` (user_id) unique

**Foreign keys:** (branch_id) → `hr_branches`(id); (department_id) → `hr_departments`(id); (hr_admin_id) → `employees`(id); (manager_id) → `employees`(id); (office_id) → `hr_work_locations`(id); (shift_id) → `hr_shifts`(id); (user_id) → `users`(id)

**Referenced by:** `employees.hr_admin_id`, `employees.manager_id`, `hr_attendance.employee_id`, `hr_attendance_corrections.employee_id`, `hr_leave_applications.employee_id`, `hr_leave_balances.employee_id`, `hr_od_requests.employee_id`, `hr_od_requests.manager_id`, `hr_payroll_corrections.employee_id`, `hr_payroll_entries.employee_id`, `hr_salary_structures.employee_id`, `users.employee_id`


### roles

**Purpose:** Role definitions and their permission keys.

**ORM:** `Role` · **Rows (dev):** 8 · **Columns:** 6

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('roles_id_seq') | PK |  | 770/821/59 |
| 2 | `name` | varchar(40) | no | — | IX |  | 227/375/30 |
| 3 | `display_name` | varchar(80) | no | — | — |  | 12/7/0 |
| 4 | `is_system` | boolean | no | false | — | the four seeded roles | 4/2/0 |
| 5 | `permissions` | json | no | — | — | ["product:read", ...] | 33/11/1 |
| 6 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |

**Indexes:** `ix_roles_name` (name) unique

**Referenced by:** `users.role_id`


---

## Receipts and payments

### payments

**Purpose:** Receipts from distributors and payments to suppliers, with allocation to an invoice or note.

**ORM:** `Payment` · **Rows (dev):** 1 · **Columns:** 13

| # | Column | Type | Null | DB default | Key | Inline note | be/ui/rep |
|---:|---|---|:--:|---|---|---|---|
| 1 | `id` | integer | no | nextval('payments_id_seq') | PK |  | 770/821/59 |
| 2 | `kind` | varchar(10) | no | — | IX |  | 146/56/23 |
| 3 | `distributor_id` | integer | yes | — | FK→distributors.id |  | 81/5/20 |
| 4 | `supplier_id` | integer | yes | — | FK→suppliers.id |  | 62/6/12 |
| 5 | `invoice_id` | integer | yes | — | FK→invoices.id |  | 99/5/18 |
| 6 | `purchase_order_id` | integer | yes | — | FK→purchase_orders.id |  | 19/2/6 |
| 7 | `amount` | numeric(14, 2) | no | — | — |  | 79/8/30 |
| 8 | `paid_on` | date | no | — | IX |  | 14/4/3 |
| 9 | `mode` | varchar(10) | no | — | — |  | 23/8/4 |
| 10 | `reference` | varchar(60) | yes | — | — |  | 31/4/2 |
| 11 | `notes` | varchar(300) | yes | — | — |  | 69/25/9 |
| 12 | `created_by` | integer | no | — | FK→users.id |  | 14/2/0 |
| 13 | `created_at` | timestamp | no | now() | — |  | 42/6/18 |

**Indexes:** `ix_payments_kind` (kind); `ix_payments_paid_on` (paid_on)

**Foreign keys:** (created_by) → `users`(id); (distributor_id) → `distributors`(id); (invoice_id) → `invoices`(id); (purchase_order_id) → `purchase_orders`(id); (supplier_id) → `suppliers`(id)

**Referenced by:** nothing

**Check constraints:** `ck_payment_amount_positive`: `amount > 0::numeric`; `ck_payment_kind`: `kind::text = ANY (ARRAY['receipt'::character varying, 'payment'::character varying]::text[])`; `ck_payment_mode`: `mode::text = ANY (ARRAY['cash'::character varying, 'bank'::character varying, 'upi'::character varying, 'cheque'::character varying, 'neft'::character varying, 'other'::character varying]::text[])`; `ck_payment_party`: `kind::text = 'receipt'::text AND distributor_id IS NOT NULL AND supplier_id IS NULL OR kind::text = 'payment'::text AND supplier_id IS NOT NULL AND distributor_id IS NULL`


---

## Limits of this register

- The database is the authority for structure; the ORM was compared with it and showed 0 column, type-class or nullability differences on the audit date.
- Purpose text and inline notes are curated from the model source; a field with no note may still be used. The `be/ui/rep` counts are text matches only.
- Row counts are the development dataset and prove nothing about production size.
- Column semantics that could not be verified from code are not asserted here. Run `python -m alembic check` before any migration; it was clean on the audit date.
