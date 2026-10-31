# Permissions Matrix

**Project:** Herbanova Business Control
**Stage:** 3 — audit registers
**Date:** 31 October 2026
**Sources:** `app/core/permissions.py` (`PERMISSIONS`, `BASELINE_ROLE_PERMS`), the live `roles` table (read-only query), `app/core/rbac.py`, and every `require(...)` / `require_admin(...)` / `is_admin(...)` call site under `app/api/`.
**Change note:** no application code, configuration or business data was changed to produce this document. Every table below was generated from the two sources above rather than typed by hand.

## How permissions are enforced

| Rule | Implementation | Consequence |
|---|---|---|
| Every API route that touches business data declares a permission | `require(perm)` in `app/core/rbac.py:84-91` | The server returns **403 Permission denied** when the effective set lacks the key. Hiding a menu item is convenience, never a control. |
| A few decisions also require the **Administrator role itself** | `require_admin(perm)` at `rbac.py:73-81`; `is_admin()` at `rbac.py:57-70` | Granting the permission to a custom role does **not** confer the role. The role name is compared case-insensitively with `admin`. |
| Effective permissions resolve from the **database role first** | `role_permissions()` at `rbac.py:32-40` | `user.role_id -> Role.permissions`; edits take effect on the next request. `BASELINE_ROLE_PERMS` is the fallback for a user with no `role_id`, and the frozen parity constant for seeding. |
| A forced password change blocks everything else | `ALLOW_WHILE_MUST_CHANGE` at `rbac.py:27-29` | Only `/api/auth/me`, `/api/auth/logout`, `/api/auth/change-password` are reachable until the password is changed. |
| Session revocation is separate from permissions | `token_version` check at `rbac.py:43-54` | Password change, admin reset and deactivation revoke existing cookies with **401 Session expired**. |
| Being signed in is not enough | `require_login` at `rbac.py:94-98` | Still honours the forced password change. |

Two endpoints add their own administrator checks rather than relying on `require_admin`:

- `POST /api/approvals/{id}/decide` — a sales-order request whose reasons include `credit_limit` can only be decided by the Administrator (`app/api/approvals.py:171-173`); post-billing amendment requests can only be decided by an Administrator **other than the requester** (`approvals.py:199-203`); the requester or creator of a sales order can never decide it (`approvals.py:176-178`).
- `GET /api/dashboard` — the administrative panels are shown only to the Administrator or to a user holding the relevant module permissions (`app/api/dashboard.py:122`).

## Roles

| Role | Live permissions | Origin | Intended use |
|---|---:|---|---|
| `admin` | 42 | baseline + seeded | Administrator. Holds the entire catalogue, including `db:reset`, `user:manage`, `approval:credit_limit`, `invoice:edit_post_billing`, `hr:payroll_approve`. |
| `sales` | 15 | baseline | Sales desk: leads, sales orders, distributors, notes, challan/e-way, own attendance, read-only accounts. |
| `inventory` | 12 | baseline | Stores and dispatch: products, stock, purchasing receipts, dispatch, invoice movement, own attendance. |
| `viewer` | 4 | baseline | Read-only products, stock, sales; own attendance. |
| `employee` | 3 | live only | Self-service: own attendance, the HR home page, and the approvals list — HR requests are limited to the ones they raised, while sales-order requests are visible but not decidable without `approval:decide`. |
| `hr_manager` | 8 | live only | HR operations: employee master, shifts, attendance management, leave/OD approval, confidential HR data, HR reports. Cannot prepare or approve payroll. |
| `payroll_officer` | 5 | live only | Prepare payroll and view confidential salary data; cannot approve payroll. |
| `reporting_manager` | 5 | live only | Team attendance and leave approval, read HR, own attendance. |

The four **baseline** roles are the frozen parity sets in `app/core/permissions.py:66-110`. The four **live only** roles exist in the development database but not in the baseline constant; users assigned to them must carry a `role_id`, because the string fallback (`ROLE_PERMS.get(user.role, set())`) would otherwise return an empty set. Verified read-only against the `roles` table on 31 October 2026.

The live Administrator set matches the 42-key catalogue exactly: no catalogue key is missing and no unknown key is present.

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

`approval:credit_limit` describes the authority; the deciding check is the **role** check at `app/api/approvals.py:171`. A custom role holding this key still cannot decide an over-limit request.

### Billing

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `invoice:edit_post_billing` | Y |  |  |  |  |  |  |  |
| `invoice:write` | Y | Y | Y |  |  |  |  |  |
| `invoice:cancel` | Y |  |  |  |  |  |  |  |
| `note:write` | Y | Y |  |  |  |  |  |  |
| `print:document` | Y | Y | Y |  |  |  |  |  |

`invoice:write` records the delivery challan and e-way bill on an **issued** invoice; it does not create the invoice. `invoice:cancel` is administrator-only in the live sets but is enforced as a permission, not as a role.

### Accounts

| Permission | admin | sales | inventory | viewer | employee | hr_manager | payroll_officer | reporting_manager |
|---|---|---|---|---|---|---|---|---|
| `accounts:read` | Y | Y |  |  |  |  |  |  |
| `accounts:write` | Y |  |  |  |  |  |  |  |

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

Counts are the literal `require(...)` call sites in `app/api/` on 31 October 2026.

| Permission | Routes guarded | Representative surface |
|---|---:|---|
| `hr:read` | 13 | HR dashboard, employee master, attendance reads, leave/OD reads, payroll reads |
| `hr:write` | 11 | Employees, offices, branches, shifts, holidays, salary components/structures, policies |
| `sales:read` | 10 | Sales orders, distributors, customers |
| `user:manage` | 9 | Users, roles, secondary password, employee login link |
| `hr:payroll_prepare` | 9 | Payroll runs, payslips, exports |
| `accounts:read` | 7 | Outstanding, party ledgers, GST register, trial balance, receipts/payments reads |
| `tax:read` / `note:write` / `hr:attendance_self` | 6 each | Rate master and slabs; credit/debit notes; own check-in/out and requests |
| `tax:write` / `stock:read` / `print:document` / `lead:write` | 5 each | Settings and rates; stock and warehouses; PDFs; leads |
| `stock:write` | 4 | Warehouses, POs, goods receipts |
| `supplier:read` / `sales:write` / `lead:read` / `audit:read` | 3 each | Suppliers; sales orders; leads; audit trail |
| `supplier:write` / `product:write` / `product:read` / `invoice:write` / `invoice:cancel` / `hr:payroll_approve` / `employee:write` / `employee:read` / `distributor:write` / `approval:read` | 2 each | Respective masters and documents |
| `user:manage` (no-arg form), `supplier:bank` | 1 each | Secondary password; bank-change request |

## Verification status

| Claim | Status | Evidence |
|---|---|---|
| 42 permission keys are defined | VERIFIED | `PERMISSIONS` count, `app/core/permissions.py:15-59` |
| Live Administrator set equals the catalogue | VERIFIED | read-only `roles` query, 31 Oct 2026 |
| Role grants shown above match the live database | VERIFIED | same query; regenerated, not hand-typed |
| `require` / `require_admin` / forced-password / revocation semantics | VERIFIED (code) | `app/core/rbac.py:27-98` |
| Administrator-only approval decisions and segregation of duties | VERIFIED (code) | `app/api/approvals.py:147-224` |
| `db:reset` requires the secondary password | VERIFIED (code) | `app/api/db_reset.py:113`; `app/api/admin.py:35-59` |
| Frozen role parity with the seeded roles | **VERIFIED** | `tests/test_roles_parity.py` — catalogue coverage, admin completeness, baseline subset, seeded-role equality and unknown-key rejection |
| Authentication, permission denial, the Administrator role gate, immediate DB-role edits, baseline fallback, deactivation and forced password change | **VERIFIED** | `tests/test_authz.py` (7 tests) |
| Every individual guarded route is exercised | **PARTIAL** | Decision paths are covered by `tests/test_approvals.py` and `tests/test_hr.py`; the new module covers the gate types, not every endpoint |

## Open items (recorded 31 October 2026)

1. **Parity test added.** `tests/test_roles_parity.py` now exists and passes, closing the former unverified-docstring gap. It asserts that every `require(...)`/`require_admin(...)` key and every report permission is in the catalogue, that all baseline sets use catalogue keys, that the Administrator holds the whole catalogue, and that the live seeded roles equal the frozen sets.
2. **Live-only roles and the string fallback.** `employee`, `hr_manager`, `payroll_officer` and `reporting_manager` have no entry in `BASELINE_ROLE_PERMS`. A user holding one of those role names **without** a `role_id` would receive an empty permission set. This is safe (fail closed) but should be confirmed as intentional.
3. **Permission edits are immediate.** Because resolution reads the database on each request, an administrator changing a role takes effect on the next request without re-login; there is no audit event dedicated to a permission-set change beyond the generic user/role write audit. See the Stage 1 audit finding on role-change auditing.
4. **`approval:credit_limit` is descriptive.** It is in the catalogue and granted to the Administrator, but the deciding gate is the role check at `app/api/approvals.py:171`; a custom role granted only this key gets no authority. Recorded so a future reader does not mistake the key for the control.
