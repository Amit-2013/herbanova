# Permissions Matrix

**Project:** Herbanova Business Control
**Stage:** 3 — audit registers, refreshed after the Phase 3 verification
**Date:** 31 October 2026; role grants and guard counts refreshed 1 November 2026; sign-in content routes added 4 November 2026
**Sources:** `app/core/permissions.py` (`PERMISSIONS`, `BASELINE_ROLE_PERMS`), the live `roles` table (read-only query), `app/core/rbac.py`, and every `require(...)` / `require_admin(...)` / `is_admin(...)` call site under `app/api/`.
**Change note:** no application code, configuration or business data was changed to produce this document. Every table below was generated from the two sources above rather than typed by hand. The 1 November refresh adds `accounts:reports` and `email:manage` to the matrices and recounts the literal guards after the HR and Accounts reporting work. The 2 November refresh adds `expense:read`/`expense:write` (46 keys, 12 groups) after the expense backend; the expense rows are still Administrator-only and the UI is Stage 3. The Stage 2 cost work adds no key: the audited PO cost correction is a second `accounts:write` route (`POST /api/accounts/costs/correction`). The 2 November FOC refresh adds `foc:read`/`foc:write`/`foc:approve` (49 keys, still 12 groups); migration 0023 grants them to the Administrator, inventory and viewer roles. `foc:approve` is Administrator-only. The 3 November ledger refresh adds no key: vouchers, opening balances, ledger heads and bank reconciliation reuse `accounts:read` and `accounts:write`, and their literal guard counts are recounted below.

## How permissions are enforced

| Rule | Implementation | Consequence |
|---|---|---|
| Every API route that touches business data declares a permission | `require(perm)` in `app/core/rbac.py:84-91` | The server returns **403 Permission denied** when the effective set lacks the key. Hiding a menu item is convenience, never a control. |
| A few decisions also require the **Administrator role itself** | `require_admin(perm)` at `rbac.py:73-81`; `is_admin()` at `rbac.py:57-70` | Granting the permission to a custom role does **not** confer the role. The role name is compared case-insensitively with `admin`. |
| Effective permissions resolve from the **database role first** | `role_permissions()` at `rbac.py:32-40` | `user.role_id -> Role.permissions`; edits take effect on the next request. `BASELINE_ROLE_PERMS` is the fallback for a user with no `role_id`, and the frozen parity constant for seeding. |
| A forced password change blocks everything else | `ALLOW_WHILE_MUST_CHANGE` at `rbac.py:27-29` | Only `/api/auth/me`, `/api/auth/logout`, `/api/auth/change-password` are reachable until the password is changed. |
| Session revocation is separate from permissions | `token_version` check at `rbac.py:43-54` | Password change, admin reset and deactivation revoke existing cookies with **401 Session expired**. |
| Being signed in is not enough | `require_login` at `rbac.py:94-98` | Still honours the forced password change. |
| The Administrator second factor is a **role** rule, not a permission key | `requires_totp(user)` in `app/services/totp.py`; `current_user` in `rbac.py` refuses a `totp_enabled` account whose session lacks the `otp` claim | The role `admin` or `super_admin` must sign in with a TOTP code; no permission can grant or waive it. A custom role never receives it. The login step issues no session for these roles until the code is accepted. See [`ADMIN_2FA.md`](ADMIN_2FA.md) and decision D-46. |

Two endpoints add their own administrator checks rather than relying on `require_admin`:

- `POST /api/approvals/{id}/decide` — a sales-order request whose reasons include `credit_limit` can only be decided by the Administrator (`app/api/approvals.py:200-202`); post-billing amendment requests can only be decided by an Administrator **other than the requester** (`approvals.py:228-232`); the requester or creator of a sales order can never decide it (`approvals.py:205-207`).
- `GET /api/dashboard` — the payload is built per permission: stock sections need `stock:read`; orders, top products and category need `sales:read`; ageing needs `accounts:read`; approvals need `approval:read`; follow-ups need `lead:read`; active products need `product:read`; activity needs `audit:read`. The Phase 3 insight cards repeat the same gates: pipeline sales/top customers/credit/corrections need `sales:read`, pipeline leads needs `lead:read`, customer outstanding needs `accounts:read`, PO ageing needs `stock:read`, HR today needs `hr:read`. A section the caller cannot read is `null`, never zero, and the chart's unreadable side is masked in the payload (`app/api/dashboard.py:825-975`). `GET /api/dashboard/expiry` adds its own `stock:read` gate (`dashboard.py:582`). The section-by-section matrix is in `docs/DASHBOARD_FEATURES.md` §7.

## Roles & Permissions screen

`#/roles` (sidebar: **Roles & Permissions**, People and admin group) is the single screen for access control. It is offered only to a role holding `user:manage`; every API behind it repeats the check on the server.

| Panel | What it does | API |
|---|---|---|
| Roles | Lists every role with its stored and effective permission count and user count; **Edit permissions** opens the tree editor | `GET /api/roles`, `PATCH /api/roles/{id}`, `POST /api/roles` |
| Feature availability | One on/off switch per module. The Users and rights module is locked on, so the screen that switches the others back on can never be disabled | `GET /api/features`, `PATCH /api/features/{key}` |
| Access control | The whole catalogue grouped by module: each top-level gate, each child with the parent it needs, and the keys reserved for the Administrator | `GET /api/roles/permissions` |

The editor renders all 49 keys in 12 groups and applies these rules:

| Rule | Browser | Server |
|---|---|---|
| Parent unchecked means no module access | Child inputs are disabled and unticked | A child stored without its parent is removed from the effective set (`rbac.role_permissions`) and dropped on save |
| Parent checked makes children selectable | Child inputs become enabled | The parent must be present for any child to be usable |
| Checking the parent grants no child | Children stay unticked | `sanitized_permissions` never adds a key the caller did not send |
| Only explicit children are granted | Only ticked children are submitted | The submitted set is stored as sent, minus orphans |
| Unchecking the parent removes children | The browser clears them and posts without them | `validate_permissions` drops them and the audit row lists `dropped_children` |
| A child cannot work without its parent | Disabled control | `permission_allowed()` fails closed |
| Navigation hides modules without the parent | `showView` follows the read permission and the feature switch | The API gate returns 403 regardless of the menu |
| Administrator-only rights stay with the Administrator | Inputs are locked for every role except `admin` | `validate_permissions` refuses the key on any other role; the Administrator role cannot save without them |
| Feature switches are central | Overview shows module status read-only; only Roles & Permissions has switches | `_feature_gate` refuses the module's API prefixes and removes its permissions from the effective set; only the Administrator role may call `/api/features` |

`tests/test_permission_tree.py` (11 tests) locks the catalogue, parent map and admin-only set together with the server rules; `tests/test_feature_switches.py` (10 tests) covers the module switches and the API gate. The browser was also checked: a viewer opening `#/roles` is returned to Overview with the link hidden, and the editor for the `sales` role showed 44 inputs, 12 groups, 4 disabled admin-only rights and HR children disabled because `sales` lacks `hr:read` (`docs/VERIFICATION_REPORT.md` §5). The 2 November refresh adds the two expense keys; the editor now renders 46 inputs, still in 12 groups, and the 4 Administrator-only rights are unchanged. Migration 0023, applied on 2 November 2026, adds the three FOC keys, so the editor renders 49 inputs, still in 12 groups, and the 5 Administrator-only rights include `foc:approve`.

## Roles

| Role | Live permissions | Origin | Intended use |
|---|---:|---|---|
| `admin` | 49 | baseline + seeded | Administrator. Holds the entire catalogue, including `db:reset`, `user:manage`, `approval:credit_limit`, `invoice:edit_post_billing`, `accounts:reports`, `email:manage`, `hr:payroll_approve`, the expense keys and the FOC keys. |
| `sales` | 15 | baseline | Sales desk: leads, sales orders, distributors, notes, challan/e-way, own attendance, read-only accounts. |
| `inventory` | 14 | baseline | Stores and dispatch: products, stock, purchasing receipts, dispatch, invoice movement, own attendance, free-sample drafts. |
| `viewer` | 5 | baseline | Read-only products, stock, free samples, sales; own attendance. |
| `employee` | 3 | live only | Self-service: own attendance, the HR home page, and the approvals list — HR requests are limited to the ones they raised, while sales-order requests are visible but not decidable without `approval:decide`. |
| `hr_manager` | 8 | live only | HR operations: employee master, shifts, attendance management, leave/OD approval, confidential HR data, HR reports. Cannot prepare or approve payroll. |
| `payroll_officer` | 5 | live only | Prepare payroll and view confidential salary data; cannot approve payroll. |
| `reporting_manager` | 5 | live only | Team attendance and leave approval, read HR, own attendance. |

The four **baseline** roles are the frozen parity sets in `app/core/permissions.py:66-110`. The four **live only** roles exist in the development database but not in the baseline constant; users assigned to them must carry a `role_id`, because the string fallback (`ROLE_PERMS.get(user.role, set())`) would otherwise return an empty set. Verified read-only against the `roles` table on 31 October 2026.

After migration 0023 the live Administrator set matches the 49-key catalogue exactly: no catalogue key is missing and no unknown key is present.

## Permission catalogue and role grants

`Y` = granted in the live database on 31 October 2026.

### Users and rights

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `user:manage` | Y |  |  |  |  |  |  |  |
| `employee:read` | Y |  |  |  |  |  |  |  |
| `employee:write` | Y |  |  |  |  |  |  |  |
| `audit:read` | Y |  |  |  |  |  |  |  |
| `db:reset` | Y |  |  |  |  |  |  |  |

`db:reset` is not sufficient on its own: `POST /api/admin/reset` additionally verifies the Administrator's **secondary password** (`app/api/db_reset.py:113`), which is set through `POST /api/admin/secondary-password` (`app/api/admin.py:35`). Both routes are listed in the Stage 1 audit for their destructive nature; the reset is outside normal operations.

### Purchasing

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `supplier:read` | Y |  | Y |  |  |  |  |  |
| `supplier:write` | Y |  |  |  |  |  |  |  |
| `supplier:bank` | Y |  |  |  |  |  |  |  |

`supplier:bank` only **requests** a bank-detail change; the change is applied after second-person approval, so holding the permission does not directly move money.

### Products

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `product:read` | Y | Y | Y | Y |  |  |  |  |
| `product:write` | Y |  | Y |  |  |  |  |  |

### Tax and discounts

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `tax:read` | Y | Y | Y |  |  |  |  |  |
| `tax:write` | Y |  |  |  |  |  |  |  |

### Inventory

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `stock:read` | Y | Y | Y | Y |  |  |  |  |
| `stock:write` | Y |  | Y |  |  |  |  |  |
| `foc:read` | Y |  | Y | Y |  |  |  |  |
| `foc:write` | Y |  | Y |  |  |  |  |  |
| `foc:approve` | Y |  |  |  |  |  |  |  |

`foc:read` gates free-of-cost stock and the free-sample notes; `foc:write` drafts a note; `foc:approve` approves or reverses one and additionally needs the Administrator role (`require_admin("foc:approve")`). A note posts a zero-cost issue with no invoice, revenue or GST. The audited historical correction (`POST /api/foc/correction/plan|apply`) is Administrator-only and refuses a fingerprint that no longer matches the database. Events: `foc.create`, `foc.approve`, `foc.reject`, `foc.reverse`, `foc.correction`, `stock.foc_correction`, `po_line.rate_remark`.

### Sales

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `sales:read` | Y | Y | Y | Y |  |  |  |  |
| `sales:write` | Y | Y |  |  |  |  |  |  |
| `approval:decide` | Y |  |  |  |  |  |  |  |
| `distributor:write` | Y | Y |  |  |  |  |  |  |
| `credit:manage` | Y |  |  |  |  |  |  |  |
| `dispatch:write` | Y |  | Y |  |  |  |  |  |

`approval:decide` is deliberately absent from `sales`: a sales user can raise and see approvals but cannot decide a sales-order approval. The Administrator always passes the decision gate through `is_admin`, even when the permission key is present.

### Approvals

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `approval:read` | Y | Y | Y |  | Y | Y | Y | Y |
| `approval:credit_limit` | Y |  |  |  |  |  |  |  |

`approval:credit_limit` describes the authority; the deciding check is the **role** check at `app/api/approvals.py:200`. A custom role holding this key still cannot decide an over-limit request.

### Billing

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `invoice:edit_post_billing` | Y |  |  |  |  |  |  |  |
| `invoice:write` | Y | Y | Y |  |  |  |  |  |
| `invoice:cancel` | Y |  |  |  |  |  |  |  |
| `note:write` | Y | Y |  |  |  |  |  |  |
| `print:document` | Y | Y | Y |  |  |  |  |  |

`invoice:write` asks an Administrator to change the delivery challan or e-way bill on an **issued** invoice; it does not create the invoice, and the change itself needs `invoice:edit_post_billing` (Administrator) at `PATCH /api/invoices/{id}/movement`. `invoice:cancel` is administrator-only in the live sets but is enforced as a permission, not as a role.

### Accounts

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `accounts:read` | Y | Y |  |  |  |  |  |  |
| `accounts:write` | Y |  |  |  |  |  |  |  |
| `accounts:reports` | Y |  |  |  |  |  |  |  |
| `expense:read` | Y |  |  |  |  |  |  |  |
| `expense:write` | Y |  |  |  |  |  |  |  |

`accounts:reports` gates the Accounts dashboard, the `report` and report-pack downloads and the Accounts e-mail block. It is granted only to the Administrator in the live data; `accounts:read` alone does not open them (verified live in `docs/VERIFICATION_REPORT.md` §5).

Receipts, payments and advances use the same two keys: `GET /api/accounts/advances` and the party ledgers need `accounts:read`, while `POST /api/accounts/payments` (either an `outstanding` settlement or an `advance` entry) needs `accounts:write`. A role with only `accounts:read`, such as `sales`, can see a distributor's available advance but cannot record one. The server check is asserted for sales and viewer in `tests/test_accounts_advances.py::test_advances_need_accounts_rights`.

`expense:read` is the parent gate for the expense screens and exports; `expense:write` is its child and covers recording an expense, reversing an approved one, uploading its receipt and editing the heads. Editing the approval switch and threshold additionally needs the Administrator role (`require_admin("expense:write")`). No non-Administrator baseline role holds either key, so the module stays closed to other staff until a role is granted them. Recording and reversal are audit events (`expense.create`, `expense.reverse`, `expense.approval`, `expense.attachment`).

### Leads

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `lead:read` | Y | Y |  |  |  |  |  |  |
| `lead:write` | Y | Y |  |  |  |  |  |  |
| `lead:assign` | Y |  |  |  |  |  |  |  |

### Reports

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `report:export` | Y | Y |  |  |  |  |  |  |
| `email:manage` | Y |  |  |  |  |  |  |  |

`email:manage` gates recipient and schedule administration and the delivery log. The worker and the test-mode redirect do not depend on the browser. In the current configuration the scheduler is in test mode with no SMTP and no test recipient, so it cannot send to a real address (`docs/VERIFICATION_REPORT.md` §9).

Report **viewing** is not governed by `report:export` alone: each report declares a viewing permission in the report catalogue (`app/services/reports.py`), and `GET /api/reports/{key}` checks it (`app/api/reports.py:83-85`). Export adds the `report:export` check. The catalogue permission per report is listed in `docs/FRONTEND_BACKEND_FIELD_MAPPING.md` §12.

### HR

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `hr:read` | Y |  |  |  | Y | Y | Y | Y |
| `hr:write` | Y |  |  |  |  | Y |  |  |
| `hr:attendance_self` | Y | Y | Y | Y | Y | Y |  | Y |
| `hr:attendance_manage` | Y |  |  |  |  | Y |  | Y |
| `hr:leave_approve` | Y |  |  |  |  | Y |  | Y |
| `hr:payroll_prepare` | Y |  |  |  |  |  | Y |  |
| `hr:payroll_approve` | Y |  |  |  |  |  |  |  |
| `hr:confidential` | Y |  |  |  |  | Y | Y |  |
| `hr:reports` | Y |  |  |  |  | Y | Y |  |

`hr:payroll_approve` is held only by the Administrator in the live data, which gives a practical separation between preparation (`payroll_officer`) and approval (`admin`). The server enforces the permission, not a specific role pairing, so a future role granted both would collapse that separation.

## Route groups by permission

Counts are the literal `require(...)` call sites in `app/api/`, regenerated on 1 November 2026 after the HR upgrade, HR outputs and Accounts reporting. Routes that call `_can(...)` inside the handler (for example the bank file's `hr:confidential` check) are not double-counted here. The three `accounts:*` rows were recounted on 3 November 2026 after the GST, statutory, ledger, receivables-by-distributor and advances work (`grep -rn 'Depends(require("accounts:..."))' app/api`).

| Permission | Routes guarded | Representative surface |
|---|---:|---|
| `accounts:read` | 29 | Statements, ledger heads, opening balances, vouchers, day book, balance sheet, bank statements and reconciliation, supplier bills, filed returns, statutory dues, receipts/payments reads, party advances and receivables by distributor |
| `hr:write` | 26 | Employees, HR configuration, leave balances, salary, locks, templates |
| `accounts:write` | 23 | Receipts/payments, the audited PO cost correction, supplier bills and reversals, filed returns, challans, ledger heads, openings, vouchers and posting, bank statements and matching |
| `hr:read` | 20 | HR dashboard, employee master, profile, attendance/leave reads, outputs |
| `sales:read` | 12 | Sales orders, invoices, credit/debit notes, distributors, customers, expiry history |
| `hr:payroll_prepare` | 12 | Payroll runs, register, bank file, statutory summary, payslips |
| `user:manage` | 10 | Users, roles, secondary password, employee login link |
| `note:write` / `stock:read` / `hr:attendance_self` / `tax:read` | 6 each | Notes; stock and warehouses; own check-in/out and requests; rate master and slabs |
| `stock:write` / `lead:write` / `print:document` / `tax:write` / `expense:read` / `expense:write` | 5 each | Warehouses and POs; leads; PDFs; settings and rates; expense reads and writes |
| `audit:read` | 4 | Audit trail and activity feed |
| `lead:read` / `sales:write` / `supplier:read` | 3 each | Leads; sales orders; suppliers |
| `accounts:reports` | 2 | Accounts dashboard and report export |
| `email:manage` | 2 | Scheduled recipients/schedules and delivery administration |
| `employee:read` / `employee:write` / `approval:read` / `invoice:write` / `invoice:cancel` / `hr:attendance_manage` / `hr:payroll_approve` / `hr:reports` / `distributor:write` / `product:read` / `product:write` / `supplier:write` | 2 each | Respective masters, approvals and HR actions |
| `db:reset` / `credit:manage` / `hr:confidential` / `lead:assign` / `report:export` / `dispatch:write` / `approval:decide` / `supplier:bank` | 1 each | Reset; credit limits; confidential reads (most use `_can` inside); reassignment; export; dispatch; decisions; bank-change request |

The catalogue has **49** keys. `accounts:reports`, `email:manage`, the two expense keys and `foc:approve` are Administrator-only in the live data; no non-Administrator baseline role carries them.

**Sign-in page content.** The 13 routes under `/api/admin/sign-in/*` (banner list, upload, replace, patch, delete and image; notice create/patch/delete; contact create/patch/delete; legal patch) do not appear in the `require("user:manage")` count because they take `Depends(admin_only)`, where `admin_only = require_admin("user:manage")` (`app/api/signin.py:43`). They are Administrator-only on the same rule as the users and roles routes: the permission alone is not enough, the role must be `admin`. The three `/api/public/sign-in*` reads are unauthenticated by design, rate-limited and return active rows only.

## Verification status

| Claim | Status | Evidence |
|---|---|---|
| 49 permission keys are defined | VERIFIED | `PERMISSIONS` count, `app/core/permissions.py` |
| Live Administrator set equals the catalogue | VERIFIED | read-only `roles` query, 1 November 2026 |
| Role grants shown above match the live database | VERIFIED | same query; regenerated, not hand-typed |
| `require` / `require_admin` / forced-password / revocation semantics | VERIFIED (code) | `app/core/rbac.py` |
| Administrator-only approval decisions and segregation of duties | VERIFIED (code) | `app/api/approvals.py` |
| `db:reset` requires the secondary password | VERIFIED (code) | `app/api/db_reset.py`; `app/api/admin.py` |
| Frozen role parity with the seeded roles | **VERIFIED** | `tests/test_roles_parity.py` — catalogue coverage, admin completeness, baseline subset, seeded-role equality and unknown-key rejection |
| Authentication, permission denial, the Administrator role gate, immediate DB-role edits, baseline fallback, deactivation and forced password change | **VERIFIED** | `tests/test_authz.py` (7 tests) |
| Parent-child rules, admin-only locking and API enforcement | **VERIFIED** | `tests/test_permission_tree.py` (11 tests); browser check in `docs/VERIFICATION_REPORT.md` §5 |
| Administrator second factor: RFC 6238 vectors, replay, non-admin unaffected, no session before enrollment, recovery code single use, session without the `otp` claim refused, five-code lock | **VERIFIED** | `tests/test_totp.py` (8 tests); enrollment walked in a browser, code-entry step not re-exercised; migration `0029_totp` on the test database only — `docs/VERIFICATION_REPORT.md` §25.5 |
| Central module switches and the API gate | **VERIFIED** | `tests/test_feature_switches.py` (10 tests); `docs/VERIFICATION_REPORT.md` §5 |
| Sign-in content: Administrator-only writes, public reads | **VERIFIED** | `tests/test_signin.py::test_only_the_administrator_manages_sign_in_content`; a `viewer` login received `403` on `GET`, `POST` and `PATCH` under `/api/admin/sign-in/*` while the public reads answered `200` (`docs/VERIFICATION_REPORT.md` §27.2) |
| Live role matrix for HR, payroll, accounts reporting and the audit/user surfaces | **VERIFIED** | `docs/VERIFICATION_REPORT.md` §5: admin/admin2 `200`, HR manager `200` on HR and `403` on payroll/bank/audit/users, business roles `403` on HR |
| Every individual guarded route is exercised | **PARTIAL** | Decision paths are covered by `tests/test_approvals.py`, `tests/test_hr.py` and the Phase 3 live GET sweep (75 routes); the gate-type tests are not repeated for every endpoint |

## Open items (recorded 31 October 2026)

1. **Parity test added.** `tests/test_roles_parity.py` now exists and passes, closing the former unverified-docstring gap. It asserts that every `require(...)`/`require_admin(...)` key and every report permission is in the catalogue, that all baseline sets use catalogue keys, that the Administrator holds the whole catalogue, and that the live seeded roles equal the frozen sets.
2. **Live-only roles and the string fallback.** `employee`, `hr_manager`, `payroll_officer` and `reporting_manager` have no entry in `BASELINE_ROLE_PERMS`. A user holding one of those role names **without** a `role_id` would receive an empty permission set. This is safe (fail closed) but should be confirmed as intentional.
3. **Permission edits are immediate.** Because resolution reads the database on each request, an administrator changing a role takes effect on the next request without re-login; there is no audit event dedicated to a permission-set change beyond the generic user/role write audit. See the Stage 1 audit finding on role-change auditing.
4. **`approval:credit_limit` is descriptive.** It is in the catalogue and granted to the Administrator, but the deciding gate is the role check at `app/api/approvals.py:200`; a custom role granted only this key gets no authority. Recorded so a future reader does not mistake the key for the control.
5. **UI gating re-checked from zero (1 November 2026).** Every sidebar link now follows the read permission its API requires, so a role is not offered a screen that can only answer 403; data loads in `loadAll` are guarded the same way (`product:read`, `stock:read`, `sales:read`). The payroll drawer opens only with `hr:payroll_prepare`, and Process / Mark paid appear only with `hr:payroll_approve`. An approval's `can_decide` flag is computed from the same rules the decide handler enforces (per-type HR permission, `approval:decide` or Administrator for sales orders, Administrator for credit-limit and post-billing, never your own request), so Approve/Reject is not offered where the server would refuse. The server remains the control; these are the matching affordances.
