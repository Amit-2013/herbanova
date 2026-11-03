# HR Management — Audit (Phase 2, before changes)

Date: 1 November 2026
Baseline: `feature/hr-upgrade` at `b6cb461` (Phase 1 audit committed)
Database: `herbanova_bcs_dev` (demonstration rows), backup `archive/herbanova_pre_hr_20261101_071046.dump`
Test baseline: **169 passed** (`python -m pytest -q`)

This audit covers employee master, attendance, leave, holidays, shifts, payroll and
payslips, advances/loans, documents, onboarding/exit, approvals, reports and roles. It
records what exists, what is absent or half-built, and what this phase will build. Nothing
here is marked "verified" unless it was executed; UI behaviour is **not verified in this
audit** because the screens were not exercised in this phase.

---

## 1. Surface as built

| Layer | Count | Detail |
|---|---:|---|
| HR API routes | 44 | `app/api/hr.py` (prefix `/api/hr`) |
| Legacy employee routes | 4 | `app/api/employees.py` (prefix `/api/employees`) |
| HR tables | 20 | branches, work locations, shifts, holidays, departments, attendance, attendance corrections, leave types, leave balances, leave applications, OD requests, approval workflows, salary components, salary structures, structure lines, payroll periods, payroll entries, entry lines, payroll corrections |
| Employee columns | 33 | identity, job, login link, bank/ID, emergency contact, policies |
| HR screens | 1 | `#/hr` workspace with buttons for employees, attendance, leave, OD, payroll, shifts |
| HR tests | 8 | `tests/test_hr.py` |
| HR reports | 12 keys | employee master, attendance, leave, OD, payroll, approvals, joining/exit, late arrival, missing punch, leave balance, payroll deductions, approval turnaround |
| HR permissions | 9 | `hr:read`, `hr:write`, `hr:attendance_self`, `hr:attendance_manage`, `hr:leave_approve`, `hr:payroll_prepare`, `hr:payroll_approve`, `hr:confidential`, `hr:reports` |

### 1.1 What already works (server-enforced)

- Employee master: create, edit, deactivate, search, filter by department/branch/status,
  pagination, self-profile read, manager link, login link, default general shift.
- Attendance: self check-in/check-out, GPS geofence with inside/outside result, outside
  check-in requires a reason and creates a location exception, manual marking by
  `hr:attendance_manage`, correction request and decision, late/early minutes from the
  shift and India time.
- Leave: paid/unpaid types, document requirement, balance check before submit, overlap
  refusal, approval, cancellation, attendance written on approval, self-service scoping.
- On duty: create/list, approval, attendance marked as OD.
- Payroll: configurable earnings/deductions (`fixed`, `percent_basic`, `percent_gross`),
  salary structures with effective dates, prepare from approved attendance/leave/OD,
  working-day proration, LOP, submit → approve → process → pay state machine, separation
  of duties, register, PDF payslip.
- Approvals: central queue, rejection reason, segregation of duties, audit entries.
- Reports: 12 HR report keys in the central report catalogue with CSV/Excel export.
- RBAC: permissions resolved from the database on every request, Administrator bypass,
  forced password change, session revocation.

### 1.2 What is absent or half-built

Severity: **H** = blocks the brief or leaks data, **M** = named requirement missing,
**L** = polish/scale.

| ID | Gap | Severity | Evidence |
|---|---|---|---|
| H-01 | HR dashboard is today-only and has no date range, trend, joiners/exits, attrition, probation, contract/document expiry, birthdays/anniversaries, leave-by-type or attention list. | H | `app/api/hr.py:181-218`; `static/js/app.js:2480-2488` |
| H-02 | Dashboard tiles are not clickable and there are no filtered drill-down endpoints. | M | same |
| H-03 | Employee list has no manager, office/location, employment-type or sort controls; no saved filters. | M | `app/api/hr.py:222-244` |
| H-04 | No bulk import/export with template, preview, row errors or undo. | H | no route or table |
| H-05 | Employee profile has no tabs, documents, assets, history, photo, status badge or quick actions. | H | only `_employee_dict` fields; one drawer |
| H-06 | No document records (offer letter, contract, ID proof, certificates) and no expiry tracking. | H | no table |
| H-07 | No assets (laptop, phone, keys) issued to an employee. | M | no table |
| H-08 | No onboarding/exit checklist; exit date is a single optional field. | M | `Employee.date_of_exit` only |
| H-09 | No probation/confirmation tracking. | M | no columns |
| H-10 | Attendance has no bulk mark, monthly calendar/heat map or monthly summary screen. | H | only per-row manual route |
| H-11 | No overtime recording or overtime approval. | M | approval label `hr_overtime` with no handler |
| H-12 | No attendance/payroll period lock or Administrator override with reason. | H | no lock table/column |
| H-13 | Leave counts **calendar days**, including weekly offs and holidays. | H | `app/api/hr.py:843` |
| H-14 | No half-day leave (attendance supports half-day; leave does not). | M | `LeaveIn` has only dates |
| H-15 | No team leave calendar or holiday calendar view. | M | no route/screen |
| H-16 | Carry-forward and encashment are columns/labels only; no process. | M | `LeaveType.carry_forward` never read |
| H-17 | No Administrator balance adjustment with reason and audit. | M | `leave_balances` is read-only and auto-creates |
| H-18 | No leave statement output. | M | no route |
| H-19 | No attendance sheet output. | M | no route |
| H-20 | No offer/appointment, experience letter, ID card or editable letter templates. | H | only salary slip PDF |
| H-21 | Payroll has no statutory summary (PF/ESI/PT/TDS) beyond a `statutory` flag on components. | H | `app/services/payroll.py` computes no statutory line |
| H-22 | No bank transfer file or payroll↔Accounts reconciliation. | H | no route |
| H-23 | Payroll corrections are audit-only; `hr_payroll_corrections` is never written. | M | `app/api/hr.py:1244-1258` |
| H-24 | Payslip requires `hr:confidential`; an employee cannot download their own payslip. | H | `app/api/hr.py:1230-1242` |
| H-25 | Managers are not scoped to their team: `reporting_manager` with `hr:read`/`hr:attendance_manage` sees every employee, attendance row and request. | H | `app/api/hr.py:575-592, 812-822, 924-934` |
| H-26 | No in-app notifications or e-mail notifications (requests, decisions, birthdays, expiries). | H | no table/route |
| H-27 | No HR report pack for the MD/Administrator and no scheduled HR e-mail. | H | `app/services/report_packs.py` has no HR pack |
| H-28 | Branches, offices, departments, holidays and leave types have API but no screen. **Fixed** for branches/offices (F-99) and departments/holidays/leave types (F-106–F-108). | M | SPA scan; see `FEATURE_INVENTORY.md` |
| H-29 | Salary components/structures have API but no screen; salary setup is impossible from the UI. **Fixed** (F-109, F-110): HR masters and the profile Salary tab. | H | SPA scan; see `FEATURE_INVENTORY.md` |
| H-30 | Attendance corrections have API but no screen; a staff member cannot raise one in the UI. | M | SPA scan |
| H-31 | Leave cancellation has API but no UI action. | M | SPA scan |
| H-32 | Payroll register route is not used by the UI; the period drawer is the only view. | L | SPA scan |
| H-33 | Two employee masters with different schemas/audit (`/api/employees` vs `/api/hr/employees`). | L | both files |
| H-34 | `hr_approval_workflows` and the overtime/salary-revision/reimbursement approval labels are unused. | L | no reads/writes |
| H-35 | No announcements, even though self-service is requested. | L | no table/route |

Confidentiality gaps are documented separately in `docs/HR_ROLES.md` §4 and
`docs/PROJECT_AUDIT.md` §6 (S-01 to S-07). They are the first fixes in this phase.

---

## 2. Area-by-area assessment

### 2.1 Employee master

**Exists:** `employees` (33 columns), create/edit, deactivate, filters, self-read, login
link, general shift default, legacy `/api/employees` for user linking.

**Missing:** confidentiality masking (S-01), manager/office/type filters, sort, saved
filters, bulk import/export, profile tabs, documents, assets, history, photo, probation,
confirmation, notice period, onboarding/exit checklist, team scoping.

**Data quality (development database):** 7 employees, all active; 7 missing manager,
5 missing joining date, 5 missing e-mail, 7 missing phone, 2 missing office. Department is
present for all 7. These are demonstration rows; production counts must be measured on the
real database when one is connected.

### 2.2 Attendance

**Exists:** check-in/out, geofence, manual marking, corrections, late/early minutes,
shift-based working days, department filter, self/team scoping by permission.

**Missing:** bulk mark, monthly calendar/heat, monthly summary, overtime, device/biometric
import (not requested), period locks, export of an attendance sheet, "missing punch"
detection is a report query only (no action to resolve it), no half-day computation for
late arrivals (half-day rules are not configurable beyond shift hours).

### 2.3 Leave and holidays

**Exists:** leave types, balances, apply/cancel, overlap and balance checks, approvals,
attendance write-back, holidays table used for working-day calculation in payroll.

**Missing:** working-day counting for leave, half-day, team calendar, holiday calendar
screen, carry-forward process, encashment, admin adjustment, leave statement, document
upload (only a text path is stored), approvals with rejection reason (works in Approvals,
not on the HR screen).

**Rule risk:** because leave counts calendar days but payroll counts working days, a
3-day leave spanning a weekend consumes 3 leave days while only 1 working day is deducted
from pay. Leave is paid, so the immediate cash effect is nil, but balances are overstated.
New applications will use working days; historical rows are left unchanged (D-06).

### 2.4 Payroll

**Exists:** configurable components/structures, monthly preparation, proration, LOP,
percent of basic/gross, effective-dated structures, approval separation, process/pay,
register, PDF slip, 12 report keys (payroll, deductions, leave balance, etc.).

**Missing:** statutory configuration and summaries (PF/ESI/PT/TDS), bank transfer file,
Accounts reconciliation, period locks, self-service payslip, correction records,
payslip template customization, salary revision approval flow, reimbursement, loans and
advances (no table at all), gratuity/full-and-final (no table/route).

**Explicitly not invented:** no statutory rate or slab is hard-coded. Where the
Administrator has not configured a component, the UI and report must say "Not configured"
and the verification report records the gap.

### 2.5 Outputs and reports

**Exists:** one salary-slip PDF (`app/services/salary_slip.py`), 12 HR report keys in the
central catalogue, CSV/Excel export via the report API.

**Missing:** appointment/offer letter, experience letter, ID card, leave statement,
attendance sheet, editable templates, department cost report, headcount/attrition report,
document-expiry report, HR pack and scheduled e-mail.

### 2.6 Approvals and audit

**Exists:** central queue, reasons, rejection reason, segregation of duties, audit entries
for creates/edits/requests/decisions/payroll transitions.

**Missing:** notification on request/decision, escalation, multi-level flow, correction
records, locked-period override reason, audit of view access to confidential data (not
required, but worth noting), HR screen decisions (only the Approvals screen decides).

### 2.7 Roles (summary; detail in `docs/HR_ROLES.md`)

Live roles holding HR permissions:

| Role | HR permissions |
|---|---|
| `admin` | all 9 |
| `hr_manager` | read, write, attendance_self, attendance_manage, leave_approve, confidential, reports |
| `payroll_officer` | read, attendance_self? (no), payroll_prepare, confidential, reports |
| `reporting_manager` | read, attendance_self, attendance_manage, leave_approve |
| `employee` | read, attendance_self |
| `sales`, `inventory`, `viewer` | attendance_self only |

There is no MD role and no HR executive role. The role matrix defines what each should be
able to do and the server-side rule that enforces it; no live role is changed without the
Administrator's action.

---

## 3. Phase 2 build plan

| Step | Work | Tests |
|---|---|---|
| 2.1 | Confidentiality fixes (S-01 to S-05): masking, salary gates, payroll approval visibility, audit masking, profile rule alignment | new authz/masking tests |
| 2.2 | Migration (one revision, tested downgrade): employee documents, assets, notifications, letter templates, period locks, saved filters, import batches, announcements; employee probation/confirmation/notice columns; leave portion/encashment columns; attendance overtime column; lock reason columns | migration round-trip + schema tests |
| 2.3 | HR dashboard with range, tiles, cards, attention list, drill-through | dashboard correctness and permission tests |
| 2.4 | Employee list filters/sort/saved views, CSV export/import with preview/errors/undo, profile documents/assets/history/documents | import/undo, masking, profile tests |
| 2.5 | Attendance bulk mark, monthly summary/heat, overtime, lock enforcement; leave working days, half-day, team calendar, admin adjustment, carry-forward action | rule tests |
| 2.6 | Payroll: locks, corrections, self-service payslip, statutory summary where configured, bank file, Accounts reconciliation note, register | payroll tests |
| 2.7 | Outputs: letters + templates, ID card, attendance sheet, leave statement | PDF smoke tests |
| 2.8 | Notifications (in-app; test-mode e-mail), HR pack and scheduled e-mail | notification and pack tests |
| 2.9 | Frontend: dashboard, list, profile tabs, attendance/leave/payroll/outputs, settings, self-service, notifications, bulk import | headless browser checks |

Anything not completed will remain listed here with its status in
`docs/VERIFICATION_REPORT.md`; it will not be silently dropped.

---

## 4. Non-goals confirmed for this phase

- No biometric/device integration (no device is configured and no protocol is specified).
- No Excel parser; CSV import only (D-10).
- No invented statutory rates; configured only (D-08).
- No real e-mail; test mode only (D-09).
- No rewrite of historical payroll or attendance; new rules apply to new rows only.
- No deletion of employees, roles or HR configuration; deactivation only.
- No production deployment or force push.

---

## 5. What was actually run for this audit

| Check | Result |
|---|---|
| `python -m pytest -q` on the untouched branch | 169 passed in 29.74s |
| Route/permission walk of all 184 `/api` routes | every route guarded except six intentional public routes |
| Table inventory (`Base.metadata.tables`) | 54 tables; 20 HR-related |
| Live role permission query (read-only) | output in §2.7; no passwords or secrets read |
| Data-quality aggregates (read-only) | §2.1; no row content printed |
| TODO/FIXME/sample scan | none in production code |
| UI run | **Not verified in this phase**; scheduled for Phase 3 with headless Chrome |
