# HR Roles and Confidentiality — matrix and server enforcement

Date: 1 November 2026
Applies to: `feature/hr-upgrade`, all routes under `/api/hr`, `/api/employees` and the HR
part of `/api/approvals`, `/api/reports` and `/api/email-reports`.

This document is the contract for who may see and do what in HR. The browser is never the
control: every rule here is implemented with `require(...)`, `require_admin(...)` or an
explicit server-side scope check. Where the current code does not yet meet the target, the
gap is listed with an ID and is being closed in Phase 2.

---

## 1. Enforcement model

- A user's rights come from `users.role_id → roles.permissions` on **every request**
  (`app/core/rbac.py:32-40`). The browser only hides affordances.
- The Administrator role bypasses permission checks (`is_admin`) but still obeys segregation
  of duties: nobody decides a request they raised, and the payroll preparer cannot approve
  the payroll.
- A custom role can be granted any catalogue key by the Administrator. Granting a key is the
  authorisation; no code checks a role name except the Administrator bypass.
- The MD has no separate role in the live data (D-02). The MD is represented by the
  Administrator, or by a custom role granted `hr:confidential` and the payroll/HR read keys.
  No `md` role is invented.

## 2. Target role matrix

Legend: **Y** = allowed, **T** = allowed for the user's team only (self plus the reporting
chain), **S** = self only, **–** = not allowed. "Administrator" always means the seeded
`admin` role; "MD" is D-02.

| Capability | Required permission(s) | Administrator | MD (via `hr:confidential`) | HR manager | HR executive (custom) | Payroll officer | Reporting manager | Employee |
|---|---|---|---|---|---|---|---|---|
| Open HR dashboard | `hr:read` | Y | Y | Y | Y | Y | T | S |
| List/search employees | `hr:read` | Y | Y | Y | Y | Y | T | S |
| Open another employee's profile | `hr:read` + scope | Y | Y | Y | Y | Y | T | S |
| Edit employee job/personal fields | `hr:write` | Y | – | Y | Y | – | – | – |
| See bank a/c, IFSC, PAN, UAN, ESI | `hr:confidential` (or self; Administrator) | Y | Y | Y | – | Y | – | S |
| Create/edit salary components and structures | `hr:write` **+** (`hr:confidential` or `hr:payroll_prepare`) | Y | Y | Y | – | Y | – | – |
| Record own attendance, apply own leave/OD | `hr:attendance_self` | Y | Y | Y | Y | Y | Y | Y |
| Mark/correct team attendance | `hr:attendance_manage` + scope | Y | Y | Y | Y | – | T | – |
| Approve leave/OD | `hr:leave_approve` + scope | Y | Y | Y | – | – | T | – |
| See all leave/OD requests | `hr:write` or `hr:leave_approve` + scope | Y | Y | Y | Y | – | T | S |
| Adjust a leave balance | `hr:write` | Y | – | Y | Y | – | – | – |
| See salary structures / payroll register | `hr:payroll_prepare` or `hr:confidential` | Y | Y | Y (confidential) | – | Y | – | – |
| Prepare payroll | `hr:payroll_prepare` | Y | – | – | – | Y | – | – |
| Approve/process/pay payroll | `hr:payroll_approve` | Y | – | – | – | – | – | – |
| Download any payslip | `hr:confidential` | Y | Y | Y | – | Y | – | – |
| Download own payslip | self + `hr:attendance_self` | Y | Y | Y | Y | Y | Y | S |
| See a payroll approval (net total) | `hr:payroll_prepare`/`hr:payroll_approve`/`hr:confidential` | Y | Y | Y | – | Y | – | – |
| HR reports, including confidential pay reports | `hr:reports` (pay reports additionally `hr:confidential`) | Y | Y | Y | Y (non-confidential) | Y | – | – |
| Configure branches, offices, shifts, holidays, departments, leave types | `hr:write` | Y | – | Y | Y | – | – | – |
| Create/edit letter templates | `hr:write` | Y | – | Y | Y | – | – | – |
| Lock/unlock attendance or payroll periods | `hr:write` (attendance) / `hr:payroll_prepare` (payroll) | Y | – | Y | Y | Y | – | – |
| Override a lock | `require_admin` + written reason | Y | – | – | – | – | – | – |
| Manage notification preferences | own login | Y | Y | Y | Y | Y | Y | Y |
| Scheduled HR pack | `email:manage` (Administrator only) | Y | – | – | – | – | – | – |

**HR executive** is a custom role the Administrator may create with:
`hr:read`, `hr:write`, `hr:attendance_self`, `hr:attendance_manage`, `hr:reports`.
It is **not** seeded automatically, because creating a live role is an access change that
belongs to the Administrator. `approval:read` is optional; without it the person cannot open
the central queue but can still use the HR screen's own approve action once that exists.

### 2.1 Team scope

`T` means the employee themself plus every employee reachable through `manager_id`
(direct and indirect reports). `S` means only their own employee record.

Company-wide access is granted when the user holds any of `hr:write`,
`hr:payroll_prepare`, `hr:confidential` (payroll needs every employee), or is the
Administrator. Without one of those keys, a user with `hr:read`, `hr:attendance_manage` or
`hr:leave_approve` is scoped to their reporting chain. A user with no linked employee
record sees nothing (fail closed).

This is a change from the current behaviour, where `reporting_manager` sees every employee
and every attendance row (H-25). It will be applied to: employee list/profile, attendance
list, leave/OD list, and HR approvals.

## 3. Endpoint matrix (all 44 HR routes)

| Area | Route | Method | Permission | Scope |
|---|---|---|---|---|
| Dashboard | `/api/hr/dashboard` | GET | `hr:read` | all / team / self (figures filtered) |
| Employees | `/api/hr/employees` | GET | `hr:read` | all / team / self |
| | `/api/hr/employees` | POST | `hr:write` | all |
| | `/api/hr/employees/{id}` | GET | `hr:read` | all / team / self |
| | `/api/hr/employees/{id}` | PATCH | `hr:write` | all |
| | `/api/hr/employees/{id}/documents` | GET/POST | `hr:read` self / `hr:write` | all / self |
| | `/api/hr/employees/{id}/assets` | GET/POST | `hr:read` self / `hr:write` | all / self |
| | `/api/hr/employees/{id}/history` | GET | `hr:read` | all / team / self |
| | `/api/hr/employees/import/preview` | POST | `hr:write` | all |
| | `/api/hr/employees/import` | POST | `hr:write` | all |
| | `/api/hr/employees/import/{batch}/undo` | POST | `hr:write` | all |
| | `/api/hr/employees/export` | GET | `hr:read` + `report:export` | all / team / self |
| Saved filters | `/api/hr/saved-filters` | GET/POST/DELETE | own login | self |
| Config | branches/offices/shifts/holidays/departments/leave types | GET | `hr:read` | all |
| | same | POST/PATCH | `hr:write` | all |
| Attendance | `/api/hr/attendance` | GET | `hr:read` or `hr:attendance_self` | all / team / self |
| | `/api/hr/attendance/check-in` | POST | `hr:attendance_self` | self |
| | `/api/hr/attendance/check-out` | POST | `hr:attendance_self` | self |
| | `/api/hr/attendance/manual` | POST | `hr:attendance_manage` | team |
| | `/api/hr/attendance/bulk` | POST | `hr:attendance_manage` | team |
| | `/api/hr/attendance/monthly` | GET | `hr:read` | all / team / self |
| | `/api/hr/attendance/{id}/correction` | POST | `hr:attendance_self` | self (team with manage) |
| | `/api/hr/attendance/corrections` | GET | `hr:read` | all / team / self |
| Leave | `/api/hr/leave/types` | GET | `hr:read` | all |
| | `/api/hr/leave/types` | POST | `hr:write` | all |
| | `/api/hr/leave/balances` | GET | `hr:read` | all / team / self |
| | `/api/hr/leave/balances/adjust` | POST | `hr:write` | all |
| | `/api/hr/leave/applications` | GET | `hr:read` | all / team / self |
| | `/api/hr/leave/applications` | POST | `hr:attendance_self` | self |
| | `/api/hr/leave/applications/{id}/cancel` | POST | `hr:attendance_self` | self |
| | `/api/hr/leave/team-calendar` | GET | `hr:read` | all / team |
| | `/api/hr/leave/carry-forward` | POST | `hr:write` | all |
| OD | `/api/hr/od` | GET/POST | `hr:read` / `hr:attendance_self` | all-team-self / self |
| Salary | `/api/hr/salary/components` | GET | `hr:payroll_prepare` | all |
| | `/api/hr/salary/components` | POST | `hr:write` + `hr:confidential` or `hr:payroll_prepare` | all |
| | `/api/hr/salary/structures` | GET | `hr:payroll_prepare` or `hr:confidential` | all |
| | `/api/hr/salary/structures` | POST | `hr:write` + `hr:confidential` or `hr:payroll_prepare` | all |
| Payroll | periods list/create/get/register | GET/POST | `hr:payroll_prepare` | all |
| | `/prepare` | POST | `hr:payroll_prepare` | all |
| | `/submit` | POST | `hr:payroll_prepare` | all |
| | `/process`, `/pay` | POST | `hr:payroll_approve` | all |
| | `/corrections` | POST | `hr:payroll_prepare` | all |
| | `/statutory-summary` | GET | `hr:payroll_prepare` | all |
| | `/bank-file` | GET | `hr:payroll_prepare` + `hr:confidential` | all |
| | `/slip` | GET | `hr:confidential` or self | all / self |
| Period locks | `/api/hr/period-locks` | GET/POST/DELETE | `hr:write` / `hr:payroll_prepare` | all |
| | `/api/hr/period-locks/{id}/override` | POST | `require_admin` + reason | all |
| Letters | `/api/hr/letters/templates` | GET/POST/PATCH | `hr:read` / `hr:write` | all |
| | `/api/hr/letters/{employee_id}/{code}` | GET | `hr:read` | all / team / self (own experience letter) |
| Outputs | `/api/hr/outputs/id-card/{employee_id}` | GET | `hr:read` | all / team / self |
| | `/api/hr/outputs/attendance-sheet` | GET | `hr:read` | all / team |
| | `/api/hr/outputs/leave-statement/{employee_id}` | GET | `hr:read` | all / team / self |
| Notifications | `/api/hr/notifications` | GET/POST(read) | own login | self |
| Reports | central `/api/reports/hr_*` | GET | `hr:reports`; confidential keys also `hr:confidential` | all |
| Scheduled pack | `/api/email-reports/*` | all | `email:manage` | all |

The table is the target; rows marked "new" in the Phase 2 changes are created in this phase.
Existing rows keep their current path and response shape.

## 4. Confidentiality rules

### 4.1 Fields treated as confidential

| Group | Fields | Masked form |
|---|---|---|
| Bank | `bank_name`, `bank_account_no`, `bank_ifsc` | name shown; account `••••••1234`; IFSC first 4 + `••••` |
| Identity | `pan`, `uan`, `esi_no` | `••••••1234` (last 4) |
| Contact/address | `address`, `emergency_name`, `emergency_phone` | shown to self, team manager with `hr:read`, HR and Administrator |
| Salary | structures, entry lines, gross/net, payslip, bank file | only payroll/confidential roles; self sees own payslip |

A masked response still contains the field (so existing screens do not break) plus
`"confidential": false`. A caller with `hr:confidential`, the employee themself, or the
Administrator receives the real value with `"confidential": true`.

### 4.2 Current defects (must be fixed before this document can be called honoured)

| ID | Defect | Target |
|---|---|---|
| S-01 | `GET /api/hr/employees` returns bank/PAN/UAN/ESI/address to every `hr:read` holder (including `employee`). | Mask unless `hr:confidential`, self, or Administrator. |
| S-02 | Salary structure write needs only `hr:write`; `hr:confidential` gates nothing. | Add `hr:confidential` or `hr:payroll_prepare` to writes and reads. |
| S-03 | A leave approver with `approval:read` sees `hr_payroll` approvals and the net total. | Restrict payroll approvals to payroll/confidential roles. |
| S-04 | Employee-update audit stores bank/PAN values in clear text. | Store masked values for confidential keys; keep the fact of the change and the actor. |
| S-05 | A manager with `hr:read` cannot open a team profile (needs `hr:write`) while the list returns the full row. | Profile read allowed for scope (all/team/self), fields masked by 4.1. |
| S-06 | Payroll officer can read the register but not the payslip (`hr:confidential`). | Payroll officer holds `hr:confidential` in the live data; keep the gate but allow self. |
| S-07 | Employee role has `hr:read`, so it can list all employees. | Scope to self (team model) and mask confidential fields. |

### 4.3 Team scoping defects

| ID | Defect | Target |
|---|---|---|
| S-08 | Attendance with `hr:attendance_manage` returns every employee. | Team scope unless `hr:write`/payroll/confidential/admin. |
| S-09 | Leave/OD lists with `hr:leave_approve` return every request. | Team scope unless `hr:write`/admin. |
| S-10 | Employee list with `hr:read` returns every employee. | Scope per §2.1. |
| S-11 | Approvals list returns all HR requests to any HR decision permission. | Filter by team and by category rights. |

## 5. Audit requirements

Every one of these writes an audit row with actor, action, record, before/after values and
reason where one is required:

- employee create/edit, including which fields changed (confidential values masked);
- attendance check-in/out, manual mark, bulk mark, correction request/decision;
- leave apply/cancel/approve/reject, balance adjustment, carry-forward/encashment;
- OD create/decision;
- salary component/structure create/edit;
- payroll prepare/submit/approve/process/pay, correction, bank-file download;
- period lock/unlock/override (reason mandatory);
- document upload/delete, letter generation;
- import preview/commit/undo (batch id and row count);
- notification read is not audited; notification **send** is recorded in the delivery log.

Segregation of duties remains: a request cannot be decided by its raiser; payroll cannot be
approved by its preparer; a lock override cannot be performed by the person who locked the
period without the Administrator gate.

## 6. Verification

| Claim | How it will be proven | Status |
|---|---|---|
| Every HR route has a server permission or explicit scope check | route walk + tests per endpoint | Existing routes verified in Phase 1; new routes to be tested in Phase 3 |
| Confidential fields masked for non-confidential callers | tests as `employee`, `reporting_manager`, `payroll_officer`, `hr_manager`, `admin` | To do |
| Salary read/write gates hold | tests for each role | To do |
| Payroll approval hidden from leave approvers | approvals test as `reporting_manager` | To do |
| Team scoping | tests with a manager/direct-report fixture | To do |
| Audit masking | audit row assertion | To do |
| No secrets in logs | code review + log scan | Phase 3 |
