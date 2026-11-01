# HR Roles and Confidentiality — implemented contract

Date: 1 November 2026
Applies to: `feature/scheduled-reports`, every route under `/api/hr` and
`/api/employees`, and the HR part of `/api/approvals`, `/api/reports` and
`/api/email-reports`.

This is the contract for who may see and do what in HR **as implemented**. The
browser only hides affordances; every rule here is enforced by `require(...)`,
`require_admin(...)`, `is_admin(...)` or an explicit server-side scope check.
The earlier target statements (`S-01`–`S-11`) are closed; the proof for each is
listed in §8 and in [`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md).

Route counts were read from the running FastAPI app on 1 November 2026:
**92 `/api/hr` routes + 4 legacy `/api/employees` routes = 96 path/method
pairs**. "Route" below means one method on one path.

---

## 1. Enforcement model

- Rights resolve from `users.role_id → roles.permissions` on **every request**
  (`app/core/rbac.py:32-40`). No cached permission survives a role edit.
- The Administrator role bypasses permission checks (`is_admin`) but **not**
  segregation of duties: nobody decides a request they raised, and the payroll
  preparer cannot approve or pay the payroll.
- A custom role may hold any catalogue key. Granting the key is the
  authorisation; no code checks a role name except the Administrator bypass.
- The MD has no separate role in the live data (D-02). The MD is represented by
  the Administrator, or by a custom role granted `hr:confidential` plus the
  payroll/HR read keys it needs.
- The 96 routes use four gate types:
  - `require("key")` — one catalogue key;
  - `require_admin("key")` — key plus the `admin` role (used only where the
    brief reserves an action to the Administrator);
  - `_require_hr_view(db, user)` — `hr:read` **or** `hr:attendance_self`,
    followed by row scoping inside the handler;
  - `_employee_or_403` / `_scoped_employee` / `scoped_employee_ids` — the
    reporting-chain scope check.

## 2. Live role sets

Read from the `roles` table on 1 November 2026 (read-only query; no role was
changed). Counts are catalogue keys held.

| Role | Keys | HR-relevant keys |
|---|---:|---|
| `admin` | 44 | the whole catalogue |
| `hr_manager` | 8 | `hr:read`, `hr:write`, `hr:attendance_self`, `hr:attendance_manage`, `hr:leave_approve`, `hr:confidential`, `hr:reports`, `approval:read` |
| `payroll_officer` | 5 | `hr:read`, `hr:confidential`, `hr:payroll_prepare`, `hr:reports`, `approval:read` |
| `reporting_manager` | 5 | `hr:read`, `hr:attendance_self`, `hr:attendance_manage`, `hr:leave_approve`, `approval:read` |
| `employee` | 3 | `hr:read`, `hr:attendance_self`, `approval:read` |
| `sales` | 15 | `hr:attendance_self` (no HR read) |
| `inventory` | 12 | `hr:attendance_self` (no HR read) |
| `viewer` | 4 | `hr:attendance_self` (no HR read) |

`hr:payroll_approve` is held only by the Administrator in the live data, which
separates preparing (`payroll_officer`) from approving (`admin`). A custom role
holding both would collapse that separation; the server enforces the keys, not
the role pairing.

## 3. Capability matrix (implemented)

Legend: **Y** = allowed; **T** = the user's reporting chain only (self plus
direct and indirect reports); **S** = own record only; **–** = refused by the
server. "MD" is the D-02 custom role.

| Capability | Gate | Administrator | MD (`hr:confidential`) | HR manager | Payroll officer | Reporting manager | Employee | Sales / inventory / viewer |
|---|---|---|---|---|---|---|---|---|
| Open HR dashboard | `hr:read` | Y | Y | Y | Y | T | S | – |
| List/search employees | `hr:read` + scope | Y | Y | Y | Y | T | S | – |
| Open a profile | `hr:read` + scope | Y | Y | Y | Y | T | S | – |
| Edit employee job/personal fields | `hr:write` | Y | – | Y | – | – | – | – |
| See bank a/c, IFSC, PAN, UAN, ESI | `hr:confidential` / `hr:payroll_prepare` / self / admin | Y | Y | Y | Y | – | S | – |
| Write bank/ID values | `hr:confidential` **or** `hr:payroll_prepare` + `hr:write` | Y | Y | Y | – | – | – | – |
| Record own attendance | `hr:attendance_self` | Y | Y | Y | Y | Y | Y | Y |
| Mark/correct team attendance | `hr:attendance_manage` + scope | Y | Y | Y | – | T | – | – |
| Apply leave / OD | `hr:attendance_self` + scope | Y | Y | Y | Y | T | S | S |
| Approve leave / OD | `hr:leave_approve` + scope | Y | Y | Y | – | T | – | – |
| See salary components and structures | `hr:payroll_prepare` | Y | – | – | Y | – | – | – |
| Create/edit salary components and structures | `hr:write` **+** (`hr:confidential` or `hr:payroll_prepare`) | Y | Y | Y | Y | – | – | – |
| Payroll period, prepare, submit, register, statutory, reconciliation | `hr:payroll_prepare` | Y | – | – | Y | – | – | – |
| Process (approve) and pay payroll | `hr:payroll_approve` | Y | – | – | – | – | – | – |
| Download any payslip | `hr:confidential` | Y | Y | Y | Y | – | – | – |
| Download own payslip | own login, released periods only | Y | Y | Y | Y | Y | Y | Y |
| Bank upload file | `hr:payroll_prepare` **+** `hr:confidential`, released periods only | Y | – | – | Y | – | – | – |
| See a payroll approval and its net total | `hr:payroll_approve` (and the requester) | Y | – | – | – | – | – | – |
| HR reports | `hr:reports` | Y | Y | Y | Y | – | – | – |
| Department salary-cost report | `hr:reports` **+** (`hr:confidential` or `hr:payroll_prepare`) | Y | Y | Y | Y | – | – | – |
| Configure branches, offices, shifts, holidays, departments, leave types, letters | `hr:write` | Y | – | Y | – | – | – | – |
| Lock attendance / payroll months | `hr:write` / `hr:payroll_prepare` | Y | – | Y (attendance) | Y (payroll) | – | – | – |
| Unlock a month | `is_admin` + written reason | Y | – | – | – | – | – | – |
| Publish announcements | `hr:write` | Y | – | Y | – | – | – | – |
| Read announcements, own notifications | own login | Y | Y | Y | Y | Y | Y | Y |
| Read a policy / own leave records | `hr:read` or `hr:attendance_self` | Y | Y | Y | Y | T | S | S |
| Scheduled HR pack | `email:manage` (Administrator only) | Y | – | – | – | – | – | – |

**Salary is deliberately narrower than personal data.** `hr:confidential`
reveals bank/ID values and payslips, but salary components, structures and the
payroll register require `hr:payroll_prepare`. This keeps an HR manager who is
allowed personal data but not payroll from reading pay; the Administrator can
grant `hr:payroll_prepare` to any custom role. This is the behaviour verified in
`VERIFICATION_REPORT.md` §5 and is recorded as D-15.

## 4. Scope model

`hr_svc.scoped_employee_ids` (`app/services/hr.py:93-110`):

| Caller | Scope returned |
|---|---|
| Administrator | `None` = whole company |
| Holds `hr:write`, `hr:payroll_prepare` or `hr:confidential` | `None` = whole company |
| Holds `hr:attendance_manage` or `hr:leave_approve`, linked to an employee | that employee plus every direct/indirect report (`manager_id` closure) |
| Any other linked login | only its own employee id |
| Login with no employee record | empty set — sees nobody |

`_employee_or_403` (`app/api/hr.py:83-104`) applies the same scope to every
route that accepts an `employee_id`:

- an id outside the scope → **403** "That employee is outside your team";
- no id and a company-wide scope → the caller's own record (or 404 if unlinked);
- no id and a restricted scope → the caller's own record (409 if unlinked).

Applying an `employee_id` in a request body does not widen scope. A manager can
raise leave or OD for a team member because the team is already inside their
scope; a staff member cannot raise one for a colleague.

## 5. Endpoint matrix (96 routes)

### 5.1 Dashboard, directory and profile (37 HR routes + 4 legacy)

| Route | Method | Gate | Scope |
|---|---|---|---|
| `/api/hr/dashboard` | GET | `hr:read` | all / T / S; salary figures only with payroll/confidential |
| `/api/hr/employees` | GET | `hr:read` | all / T / S; confidential fields masked per viewer |
| `/api/hr/employees` | POST | `hr:write` | all |
| `/api/hr/employees/{id}` | GET | `hr:read` | all / T / S |
| `/api/hr/employees/{id}` | PATCH | `hr:write` | all; bank/ID values need `hr:confidential` or payroll |
| `/api/hr/employees/export.csv` | GET | `hr:read` | all / T / S; masked CSV |
| `/api/hr/employees/import-template.csv` | GET | `hr:write` | all |
| `/api/hr/employees/import` | POST | `hr:write` | all; bank columns need `hr:confidential` or payroll |
| `/api/hr/employees/import-batches/{batch}/undo` | POST | `hr:write` | all |
| `/api/hr/employees/{id}/profile` | GET | `hr:read` | all / T / S; bundles tabs and history |
| `/api/hr/employees/{id}/history` | GET | `hr:read` | all / T / S |
| `/api/hr/employees/{id}/photo` | GET | `hr:read` | all / T / S |
| `/api/hr/employees/{id}/photo` | POST | logged in + `_scoped_employee` | `hr:write` or the person themself |
| `/api/hr/employees/{id}/photo` | DELETE | logged in + `_scoped_employee` | `hr:write` or the person themself |
| `/api/hr/employees/{id}/documents` | GET | `hr:read` | all / T / S; document number masked unless confidential/self |
| `/api/hr/employees/{id}/documents` | POST | `hr:write` | all |
| `/api/hr/employees/{id}/documents/{doc}` | PATCH | `hr:write` | all |
| `/api/hr/employees/{id}/assets` | GET | `hr:read` | all / T / S |
| `/api/hr/employees/{id}/assets` | POST | `hr:write` | all |
| `/api/hr/assets/{asset_id}/return` | POST | `hr:write` | all |
| `/api/hr/saved-filters` | GET | `hr:read` | own saved rows |
| `/api/hr/saved-filters` | POST | `hr:read` | own saved rows |
| `/api/hr/saved-filters/{filter_id}` | DELETE | `hr:read` | own saved rows |
| `/api/hr/branches` | GET / POST | `hr:read` / `hr:write` | all |
| `/api/hr/offices` | GET / POST | `hr:read` / `hr:write` | all |
| `/api/hr/shifts` | GET / POST | `hr:read` / `hr:write` | all |
| `/api/hr/shifts/{id}` | PATCH | `hr:write` | all |
| `/api/hr/holidays` | GET / POST | `hr:read` / `hr:write` | all |
| `/api/hr/departments` | GET / POST | `hr:read` / `hr:write` | all |
| `/api/hr/announcements` | GET | logged in | active rows; inactive only with `hr:write` |
| `/api/hr/announcements` | POST | `hr:write` | all |
| `/api/hr/announcements/{id}` | PATCH | `hr:write` | all |
| `/api/employees` (legacy) | GET / POST | `employee:read` / `employee:write` | all; narrow fields only (no bank/ID/salary) |
| `/api/employees/{id}` (legacy) | GET / PATCH | `employee:read` / `employee:write` | all; narrow fields only |

The legacy `/api/employees` routes exist for older callers and are held only by
the Administrator in the live data. The HR screens use `/api/hr/employees`,
which applies scope, masking and the confidentiality rules.

### 5.2 Attendance (8)

| Route | Method | Gate | Scope |
|---|---|---|---|
| `/api/hr/attendance` | GET | `hr:read` or `hr:attendance_self` | all / T / S |
| `/api/hr/attendance/monthly` | GET | `hr:read` or `hr:attendance_self` | all / T / S; empty days stay `null`, never "absent" |
| `/api/hr/attendance/check-in` | POST | `hr:attendance_self` | self; geofence exception raises an approval |
| `/api/hr/attendance/check-out` | POST | `hr:attendance_self` | self; today's own row |
| `/api/hr/attendance/manual` | POST | `hr:attendance_manage` | T; period lock applies |
| `/api/hr/attendance/bulk` | POST | `hr:attendance_manage` | T; rejects any employee outside scope |
| `/api/hr/attendance/{id}/correction` | POST | `hr:attendance_self` + (`hr:attendance_manage` or own) | self, or T for a manager |
| `/api/hr/attendance/corrections` | GET | `hr:read` | all / T / S |

### 5.3 Leave and on-duty (10)

| Route | Method | Gate | Scope |
|---|---|---|---|
| `/api/hr/leave/types` | GET | `hr:read` or `hr:attendance_self` | all |
| `/api/hr/leave/types` | POST | `hr:write` | all |
| `/api/hr/leave/types/{id}` | PATCH | `hr:write` | all |
| `/api/hr/leave/balances` | GET | `hr:read` or `hr:attendance_self` | all / T / S |
| `/api/hr/leave/balances/adjust` | POST | `hr:write` | all; audited |
| `/api/hr/leave/applications` | GET | `hr:read` or `hr:attendance_self` | all / T / S |
| `/api/hr/leave/applications` | POST | `hr:attendance_self` | self or T; working days only; one calendar year; 90-day cap |
| `/api/hr/leave/applications/{id}/cancel` | POST | `hr:attendance_self` + own, or `hr:write` | self / all |
| `/api/hr/leave/calendar` | GET | `hr:read` | all / T |
| `/api/hr/leave/carry-forward` | POST | `hr:write` | all; preview then commit, capped |
| `/api/hr/od` | GET | `hr:read` or `hr:attendance_self` | all / T / S |
| `/api/hr/od` | POST | `hr:attendance_self` | self or T |

### 5.4 Salary and payroll (20)

| Route | Method | Gate | Scope |
|---|---|---|---|
| `/api/hr/salary/components` | GET | `hr:payroll_prepare` | all |
| `/api/hr/salary/components` | POST | `hr:write` + (`hr:confidential` or `hr:payroll_prepare`) | all |
| `/api/hr/salary/components/{id}` | PATCH | `hr:write` + (`hr:confidential` or `hr:payroll_prepare`) | all |
| `/api/hr/salary/structures` | GET | `hr:payroll_prepare` | all |
| `/api/hr/salary/structures` | POST | `hr:write` + (`hr:confidential` or `hr:payroll_prepare`) | all |
| `/api/hr/payroll/periods` | GET / POST | `hr:payroll_prepare` | all |
| `/api/hr/payroll/periods/{id}` | GET | `hr:payroll_prepare` | all |
| `/api/hr/payroll/periods/{id}/prepare` | POST | `hr:payroll_prepare` | all; period lock applies |
| `/api/hr/payroll/periods/{id}/submit` | POST | `hr:payroll_prepare` | all |
| `/api/hr/payroll/periods/{id}/process` | POST | `hr:payroll_approve` | all; not by the preparer |
| `/api/hr/payroll/periods/{id}/pay` | POST | `hr:payroll_approve` | all |
| `/api/hr/payroll/periods/{id}/register` | GET | `hr:payroll_prepare` | all |
| `/api/hr/payroll/periods/{id}/statutory` | GET | `hr:payroll_prepare` | all; unconfigured heads are gaps |
| `/api/hr/payroll/periods/{id}/reconciliation` | GET | `hr:payroll_prepare` | all |
| `/api/hr/payroll/periods/{id}/corrections` | POST | `hr:payroll_prepare` | all; records an audited request |
| `/api/hr/payroll/periods/{id}/bank-file` | GET | `hr:payroll_prepare` + `hr:confidential` | all; released periods only; preview masks account numbers |
| `/api/hr/payroll/entries/{id}/slip` | GET | `hr:confidential` | all |
| `/api/hr/me/payslips` | GET | logged in | own released periods |
| `/api/hr/me/payslips/{id}` | GET | logged in | own; 404 for another employee, 409 before release |

### 5.5 Period locks (3)

| Route | Method | Gate | Scope |
|---|---|---|---|
| `/api/hr/period-locks` | GET | `hr:read` | payroll locks hidden without payroll/confidential |
| `/api/hr/period-locks` | POST | `hr:write` (attendance) / `hr:payroll_prepare` (payroll) | all; reason recorded |
| `/api/hr/period-locks/{id}/unlock` | POST | `is_admin` + written reason | Administrator only |

There is no DELETE route: unlocking is the only release and it requires the
Administrator plus a written reason.

### 5.6 Reports, letters and outputs (12)

| Route | Method | Gate | Scope |
|---|---|---|---|
| `/api/hr/reports` | GET | `hr:reports` | all |
| `/api/hr/reports/{report}` | GET | `hr:reports`; salary-cost reports add confidential/payroll | all |
| `/api/hr/letters/templates` | GET | `hr:read` or `hr:attendance_self` | all |
| `/api/hr/letters/templates/{id}` | PATCH | `hr:write` | all; unknown placeholders rejected |
| `/api/hr/outputs/letter/{code}` | GET | `hr:read` or `hr:attendance_self` | all / T / S |
| `/api/hr/outputs/id-card` | GET | `hr:read` or `hr:attendance_self` | all / T / S; no bank, PAN, salary printed |
| `/api/hr/outputs/attendance-sheet` | GET | `hr:read` or `hr:attendance_self` | all / T / S |
| `/api/hr/outputs/leave-statement` | GET | `hr:read` or `hr:attendance_self` | all / T / S; read-only |
| `/api/hr/notifications` | GET | logged in | own bell only |
| `/api/hr/notifications/{id}/read` | POST | logged in | own note; another user's → 404 |
| `/api/hr/notifications/read-all` | POST | logged in | own notes only |
| `/api/hr/notifications/digest` | POST | `hr:write` | all; once per day per recipient |

### 5.7 Approvals, central reports and e-mail

| Route | Method | Gate | Scope |
|---|---|---|---|
| `/api/approvals` | GET | `approval:read` | HR rows only with an HR decision key; payroll rows only with `hr:payroll_approve` or as requester; team scope |
| `/api/approvals/{id}/decide` | POST | per-type HR key | **never** the requester; payroll approval needs `hr:payroll_approve` |
| `/api/reports/hr_*` | GET | `hr:reports`; confidential keys add `hr:confidential` | all |
| `/api/email-reports/*` | all | `email:manage` | Administrator only; test mode |

HR approval types and their decision keys (`app/api/approvals.py:39-43`):
`hr_leave` and `hr_od` → `hr:leave_approve`; `hr_attendance_correction` and
`hr_geofence_exception` → `hr:attendance_manage`; `hr_payroll` →
`hr:payroll_approve`. The queued employee must be inside the decider's scope.

## 6. Confidentiality rules

### 6.1 Fields and masking

| Group | Fields | Masked unless | Masked form |
|---|---|---|---|
| Bank | `bank_account_no`, `bank_ifsc` | `hr:confidential`, `hr:payroll_prepare`, self, Administrator | last 4 characters kept, e.g. `••••••1234` |
| Identity | `pan`, `uan`, `esi_no` | same | last 4 characters kept |
| Document number | employee document `number` | `hr:confidential`, `hr:payroll_prepare`, self, Administrator | last 4 kept, `number_masked: true` |
| Contact / address / emergency | `address`, `emergency_name`, `emergency_phone`, phone, e-mail | visible to `hr:read` within scope | not masked |
| Salary | components, structures, register, payslip, bank file | `hr:payroll_prepare` (structures/register) and `hr:confidential` (payslip/bank file); self sees own payslip | refused, not masked |
| Audit | bank/ID values in `audit_log` | always | masked before storage |

A masked response keeps the field present and adds `confidential_visible:
false` (employee rows) so existing screens do not break. The real value is
returned with `confidential_visible: true` to an authorised viewer.

The **ID card** and **leave statement** are deliberately free of bank, PAN,
UAN, ESI and salary data. The ID card prints a footer saying so. The salary
slip is the only generated PDF that contains pay figures, and it is gated as
above.

### 6.2 Write-side masking

`_refuse_confidential_write` rejects a create/edit that carries bank or ID
values unless the writer holds `hr:confidential` or `hr:payroll_prepare`;
the Administrator bypasses the check. A writer without those keys can still
edit names, departments, designations and contacts. Audit rows store the
masked old and new value for the five confidential fields.

### 6.3 Outputs

- Letters, ID cards and leave statements apply `_employee_or_403` and
  `_require_hr_view`, so a staff member can generate only their own; a manager
  only their chain; HR/payroll/Administrator anyone.
- The attendance sheet uses `hr_svc.monthly_attendance`, the same scope as the
  screen. Empty days are printed as gaps, not as absences.
- The leave statement reads stored balances and applications and does not
  create or adjust a balance (`test_leave_statement_reads_without_creating_balances`).

## 7. Audit and segregation

Every write in this list records actor, action, record, changed fields and,
where required, a reason:

- employee create/edit/import/undo/photo; bank and ID values masked in the row;
- attendance check-in/out, manual, bulk, correction request and decision;
- leave apply/cancel/approve/reject, balance adjustment, carry-forward;
- OD create and decision;
- salary component/structure create/edit;
- payroll prepare, submit, process, pay, correction request, bank-file download;
- period lock/unlock with a mandatory reason;
- document upload/edit, asset issue/return, letter and output generation;
- announcement publish, digest run;
- report and directory exports.

Segregation of duties:

- an approval cannot be decided by the user who raised it;
- payroll cannot be processed or paid by the user who prepared or submitted it;
- a month can be locked by HR/payroll but unlocked only by the Administrator
  with a written reason;
- `approval:credit_limit` remains descriptive; the credit-limit decision is
  gated by the Administrator role, not by that key.

## 8. Verification status

| Claim | Evidence | Status |
|---|---|---|
| 96 HR/employee routes exist | route dump from the running app, 1 Nov 2026 | VERIFIED |
| Every HR route has a key or an explicit scope check | §5 matrix + route walk in `VERIFICATION_REPORT.md` §4–5 | VERIFIED |
| Scope chain: manager sees own chain, staff sees self | `test_reporting_manager_sees_only_their_chain`, `test_bulk_marking_stays_inside_the_reporting_chain`, `test_team_leave_calendar_is_scoped`, `test_staff_self_service_reads_are_scoped_to_their_own_record`, `test_dashboard_is_scoped_to_the_reporting_chain` | VERIFIED |
| Bank/ID masked without the right | `test_bank_and_id_are_masked_without_the_confidential_right`, `test_export_keeps_confidential_columns_masked` | VERIFIED |
| Bank/ID writes refused without the right | `test_employee_writes_without_confidential_right_cannot_touch_bank_data`, `test_import_of_bank_data_needs_the_confidential_right` | VERIFIED |
| Audit stores masked bank/ID | `test_bank_change_is_written_to_the_audit_trail_masked` | VERIFIED |
| Payroll approvals hidden from non-payroll roles | `test_payroll_approval_is_hidden_from_non_payroll_roles` | VERIFIED |
| Manager decides only inside the chain | `test_manager_decides_only_inside_the_chain` | VERIFIED |
| Salary hidden from staff | `test_salary_payable_is_hidden_from_staff`, `test_department_cost_needs_confidential_rights_and_exports_csv_and_pdf` | VERIFIED |
| Bank file needs approval and confidentiality, preview masked | `test_bank_file_needs_approval_confidential_rights_and_masks_the_preview` | VERIFIED |
| Self-service payslip is own and only after release | `test_self_service_payslips_are_own_and_only_after_release` | VERIFIED |
| Document numbers stay confidential | `test_documents_keep_numbers_confidential` | VERIFIED |
| Outputs follow server-side scope | `test_letters_and_cards_follow_the_server_side_scope`, `test_attendance_sheet_matches_the_screen_and_scope` | VERIFIED |
| Leave statement is read-only | `test_leave_statement_reads_without_creating_balances` | VERIFIED |
| Lock override needs the Administrator and a reason | `test_lock_blocks_edits_until_the_administrator_reopens_with_a_reason` | VERIFIED |
| Live role matrix (admin/HR manager/payroll/sales/inventory/viewer) | `VERIFICATION_REPORT.md` §5 | VERIFIED |

Closed defects (Phase 2, with the tests above): **S-01** masking, **S-02**
salary write gate, **S-03** payroll approvals hidden, **S-04** audit masking,
**S-05** profile read for scope, **S-06** payslip self/payroll access, **S-07**
employee list scoped, **S-08** attendance team scope, **S-09** leave/OD team
scope, **S-10** employee list scope, **S-11** approvals filtered by category and
team.

## 9. Known limitations

| Item | Effect |
|---|---|
| Legacy `/api/employees` | No team scope and no masking; held only by the Administrator live. HR screens use `/api/hr/employees`. |
| HR directory export | Requires `hr:read` only (not `report:export`); confidential columns are masked per viewer. Adding the export key would remove access from the HR manager, so it is documented rather than changed. |
| Salary reads | `hr:payroll_prepare` only; `hr:confidential` alone does not open salary structures (D-15). |
| Bank file download | Not audited with the file contents, only the download event; the preview masks account numbers. |
| No dedicated UI for some server features | Letter templates, saved filters and period-lock controls exist in the API; the HR screen exposes the common paths and the rest are API-only (see `FRONTEND_BACKEND_FIELD_MAPPING.md`). |
| In-memory HR pages | The employee directory and monthly attendance are bounded and built in memory; see the report paging warning in `VERIFICATION_REPORT.md`. |
