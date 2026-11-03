# HR Features — what the module does and how it behaves

Date: 1 November 2026
Branch: `feature/scheduled-reports`
Companions: [`HR_ROLES.md`](HR_ROLES.md) (who may do what),
[`HR_AUDIT.md`](HR_AUDIT.md) (the review that produced the upgrade),
[`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) (executed evidence),
[`FEATURE_INVENTORY.md`](FEATURE_INVENTORY.md) (whole-project list).

This is the functional description of HR. It states the rule, the API that
enforces it and the tests that prove it. A rule that exists only in the screen
is not listed as a feature; the server is the control.

## 1. Entry points

| Screen | How it opens | What it shows |
|---|---|---|
| HR dashboard | sidebar **HR Management** | headcount, today's attendance, trends, pending approvals, birthdays/anniversaries, holidays, gaps |
| Employee master | HR dashboard → **Employee master** | directory with filters, saved views, import/export, employee drawer |
| Employee profile | directory → **Open** | overview, documents, assets, history tabs, photo, letters and PDFs |
| Attendance | HR dashboard section | today's list, monthly calendar, check-in/out, manual and bulk marking, corrections |
| Leave and OD | HR dashboard section | leave types, balances, applications, team calendar, carry-forward, OD |
| Payroll | HR dashboard → **Payroll** | periods, register, skipped-employee list, payslips, statutory summary, bank file, reconciliation |
| HR reports | HR dashboard → **Reports** | seven HR reports, each as JSON, CSV or PDF |
| Locks | HR dashboard → **Period locks** | attendance and payroll month locks |
| Branches & locations | HR dashboard → **Branches & locations** (`hr:write`) | the branch and office masters with geofence and the HR responsible person, and the attendance-rule table with New/Edit/Delete (the drawer is titled "Branches, offices & attendance policy") |
| HR masters | HR dashboard → **HR masters** (`hr:write`; the two salary tabs need `hr:payroll_prepare`) | departments, holidays with branch/office scope, leave types, salary components and salary structures |

The HR menu is shown to anyone holding `hr:read` or `hr:attendance_self`
(`static/js/app.js:172`). A staff member without `hr:read` sees the self-service
home and their own attendance only; the server refuses the wider reads.

## 2. HR dashboard

**What it does.** One call, `GET /api/hr/dashboard`, returns the home page in a
single response. The default range is the current month to today; the range may
span at most 366 days. `day` selects the "today" figures independently.

| Group | Figures |
|---|---|
| Headcount | total, active, inactive, new joiners this month, exits this month and in the range, attrition % (null when the opening headcount is zero) |
| Today | present (present + late), absent, on leave, on OD, late, early departure |
| Approvals | pending HR requests, split into leave and other |
| Attention | missing punches, negative leave balances, approvals older than three days, incomplete employee records — each with a complete count and at most 20 rows |
| Trends | daily attendance series for the range (present, absent, leave, OD, late) |
| Distribution | by department, by branch, leave by type |
| Dates | birthdays and work anniversaries in the next 30 days, holidays in the next 90 days |
| Payroll | status only; `salary_payable` is `null` without `hr:confidential` or `hr:payroll_prepare` |

**Rules.** Rows are scoped by the reporting chain (§4 of `HR_ROLES.md`). A missing
attendance row is never counted as absence; the attention list says it is a
missing punch. An empty list is returned as an empty list, not a fabricated row.
An invalid range (end before start, or more than 366 days) is a 422.

**Tests.** `tests/test_hr_dashboard.py` (5), including scoping, real-row cards,
exits/stale approvals and the "no data is null" rule.

## 3. Employee master and directory

**What it does.** `GET /api/hr/employees` supports free-text search, department,
branch, office, status, employment type, manager, joining and exit ranges,
probation-due and incomplete-record filters, and sorting by code, name,
department, joining date or status. The CSV export and saved views reuse the
same filter builder, so the file cannot disagree with the screen.

**Saved views.** `GET/POST/DELETE /api/hr/saved-filters`. A view belongs to the
user who created it; another user cannot list or delete it.

**Bulk import.** `GET /employees/import-template.csv` returns the header;
`POST /employees/import` validates a CSV (2 MB maximum, unknown columns refused)
and returns per-row errors; `commit=true` creates the valid rows and tags them
with a batch id; `POST /employees/import-batches/{batch}/undo` removes that
batch. Bank/ID columns need `hr:confidential` or `hr:payroll_prepare`.

**Rules.**

- Employee code is unique and normalised to upper case; a duplicate is a 409.
- An employee is deactivated, never deleted; `status` is `active` or `inactive`.
- A manager must exist and cannot be the employee themself.
- New employees without an explicit shift receive the general office shift,
  which is what late/early calculations need.
- An employee may be assigned a **branch** and an **office / work location**; an
  office belongs to one branch, the branch is inferred from the office, and a
  mismatched pair is refused (422). The New employee form offers only the
  offices of the chosen branch.
- Bank and ID values are masked unless the viewer is the person, the
  Administrator, or holds `hr:confidential`/`hr:payroll_prepare`.
- The CSV export is masked per viewer. It requires `hr:read` (not
  `report:export`); see D-21.

**Tests.** `tests/test_hr_directory.py` (5), `tests/test_hr.py` (employee master,
shift assignment, login link), `tests/test_hr_security.py` (masking and scope).

## 4. Profile, documents, assets and photo

**What it does.** `GET /api/hr/employees/{id}/profile` bundles the tabs the
drawer renders: identity and job data, contacts, documents, assets, leave
balances and recent history. Its writes are the ordinary employee PATCH and the
document/asset routes.

| Item | Rule |
|---|---|
| Photo | JPEG, PNG or WebP, 2 MB maximum, verified as an image; served only through the authenticated route with `no-store`; the uploader must hold `hr:write` or be the person |
| Document | type and title required; issue date cannot be after expiry; the number is masked unless the viewer holds `hr:confidential`/payroll or is the person |
| Asset | issued to one employee; returned once; a second return is refused |
| History | assembled from audit rows; it is a read, not a second store |

**Scope.** Profile, photo and history use `_scoped_employee`, so a manager sees
the chain and a staff member sees themself. Documents do the same; the number is
masked for a manager without the confidential right.

**Tests.** `tests/test_hr_profile.py` (4), `tests/test_hr_documents.py`
(letters/cards/scope), `tests/test_hr_security.py`.

## 5. Attendance

**What it does.**

- **Check-in / check-out** (`hr:attendance_self`): one row per employee per
  business day. Check-out needs today's check-in and records worked minutes and
  early departure. Check-in inside an office geofence records `inside`; outside
  records `outside` and raises an `hr_geofence_exception` approval with the
  reason. No punch is invented.
- **Manual marking** (`hr:attendance_manage`): status, times, office, overtime
  and remarks for one employee; check-out must be later than check-in.
- **Bulk marking** (`hr:attendance_manage`): one status across a set of
  employees and dates; rejects any employee outside the caller's scope; can skip
  weekly offs and holidays; records created/updated/skipped counts.
- **Monthly view** (`hr:read` or `hr:attendance_self`): every day of the month,
  with `null` for a day that has no row. It reports missing days separately and
  never calls an unrecorded day "absent".
- **Corrections**: a staff member asks for a change to their own row; a manager
  with `hr:attendance_manage` can raise one inside the chain. Approval applies
  the new status/times and is audited.
- **Locks**: attendance and payroll months lock independently. Any write to a
  locked month is refused unless the caller is the Administrator and gives a
  written override reason.
- **Attendance rules** (`hr:write`): a rule may target any mix of branch, office,
  designation and employee, with optional effective dates, priority, shift and
  attendance-mode override. The most specific active rule wins — employee 1000,
  office 100, designation 10, branch 1 — then the lower priority, then the newest;
  with no matching rule attendance is required (D-32). The resolved requirement
  and its source are shown on the employee form, the profile and the attendance
  drawer.
- **Only when required**: check-in, check-out, a correction request, a manual
  entry and a bulk row are refused with **409** and the rule's source for an
  exempt employee. The monthly register marks an exempt day `not_required`
  instead of a gap, the totals carry `not_required_days`, and payroll does not
  infer an absence there.
- **Location scope**: branches and offices (geofence centre/radius, mode) are
  maintained in the browser; attendance, the monthly register, the dashboard and
  every HR report accept `branch_id` and `office_id`, and a report header repeats
  the filter applied.

**Tests.** `tests/test_hr.py` (check-in, shift late/early), `test_hr_attendance.py`
(6: bulk, validation, scope, monthly gaps, lock override, payroll lock),
`test_hr_security.py` (team scope), `test_hr_sites.py` (7: site CRUD and employee
assignment, rule validation and precedence, exempt gating, self-service under a
rule, location filters, monthly not-required days, payroll exemption).

## 6. Leave and on-duty

**Leave rules**

| Rule | Behaviour |
|---|---|
| Working days | New applications count working days; weekly offs and applicable holidays are excluded (D-06). Historical stored `days` are not recalculated. |
| One calendar year | An application may not cross 31 December; balances are per year. |
| 90-day span | The validator refuses a span where `date_to - date_from > 90`. |
| Half day | Allowed only when the leave type allows it, and only for a single date; it deducts 0.5 day. |
| Document | A leave type marked `requires_document` refuses an application without one. |
| Balance | A paid leave type refuses an application that exceeds the available balance; a negative balance is never created by an application. |
| Overlap | An application overlapping a pending or approved one is a 409. |
| Approval | Applying reserves `pending` days; approval moves them to `used` and writes the attendance rows; rejection releases the pending days. The approver must be inside the chain and cannot be the requester. |
| Lock | Approval that would write into a locked attendance month is refused. |

**Balances and carry-forward.** `GET /leave/balances` reads stored entitlements,
carried days, used, pending and available. `POST /leave/balances/adjust` is an
audited HR write. `POST /leave/carry-forward` previews or applies
`min(unused, max_carry_forward)` into the following year, only for active
employees and active types with carry-forward enabled.

**On-duty.** `POST /api/hr/od` records the date, duration, visit type, purpose,
party, worksite, destination and optional document, and raises an approval to the
reporting manager. Approval writes an OD attendance row; rejection leaves the
day untouched.

**Team calendar.** `GET /leave/calendar` is scoped to the chain and is hidden
from a staff member without a team.

**Tests.** `tests/test_hr_leave.py` (8), `tests/test_hr.py`
(leave approval, self-approval refusal), `test_hr_security.py`
(manager decision inside the chain).

## 7. Payroll

**Inputs.** Active employees, an active salary structure effective in the month,
approved attendance/leave/OD, and configured salary components. No statutory
rate or amount is written in the code.

**Preparation rules**

- A month with no attendance rows is treated as fully present (D-14); this is a
  stated assumption, not a hidden one.
- A paid half-day counts 0.5 present + 0.5 paid leave; an unpaid half-day counts
  0.5 present; a full paid leave day counts 1 paid leave day.
- Payable days = `min(working days, present + paid leave)`; loss of pay is the
  remainder; earnings are prorated by payable/working days.
- `INCENTIVE`, `OVERTIME`, `BONUS` and `REIMBURSEMENT` are not prorated.
- An employee with no active salary structure is still skipped, but never
  silently: the prepare result and the period screen list every active employee
  left out with the reason ("No active salary structure covers this month" or
  "Not in the prepared entries"), and the audit entry records their codes
  (F-80, closes M-06). The screen offers **Assign salary structures**.
- Preparing a period deletes and recalculates its draft entries while the period
  is `draft` or `under_review`; it cannot recalculate an approved period.

**Lifecycle**

`draft` → **prepare** → `under_review` → **submit** (raises `hr_payroll`
approval) → **approve** → `approved` → **process** → `processed` → **pay** →
`paid`.

- Prepare and submit need `hr:payroll_prepare`.
- Process and pay need `hr:payroll_approve`.
- The preparer cannot approve their own payroll (segregation of duties).
- A period lock blocks prepare, submit, process and pay until the Administrator
  reopens it with a reason.

**Outputs**

| Output | Rule |
|---|---|
| Register | Every earning and deduction stored as a line with its basis |
| Skipped employees | Every active employee the run did not pay, with the reason; returned by prepare and by the period screen, and their codes stored on the audit entry (F-80) |
| Payslip | Own payslip after release (`processed`/`paid`); any payslip with `hr:confidential` |
| Statutory summary | PF, ESI, PT and TDS from active components marked `statutory`; an unconfigured head is a gap, never zero |
| Bank file | CSV or JSON; needs payroll **and** confidential rights; released periods only; JSON preview masks account numbers; skipped rows name the missing field, not its value |
| Reconciliation | Ties register lines, net total and bank-file total; held rows are explained |

**Not built.** Payroll is not posted to the accounting ledger (D-17), and
overtime/salary-revision/reimbursement approval handlers do not exist.

**Tests.** `tests/test_hr.py` (full lifecycle), `test_hr_payroll_outputs.py`
(5), `test_hr_attendance.py` (payroll lock), `test_hr_security.py` (salary
hidden from staff, payroll approvals hidden).

## 8. HR reports

Two surfaces share the same data:

- **HR report screen** — `GET /api/hr/reports/{report}`. Seven reports:
  headcount, joiners and leavers, attendance summary, late and absentee,
  leave balances, department cost, document expiry. JSON, CSV or PDF.
- **Central report catalogue** — `/api/reports/hr_*`. Twelve reports: employee
  master, attendance, leave, OD, payroll, approvals, joining/exit, late arrival,
  missing punch, leave balance, payroll deductions, approval turnaround.

**Rules.** `hr:reports` is required. The department cost report additionally
requires `hr:confidential` or `hr:payroll_prepare`. An empty period returns the
report with a "no data yet" marker and honest checks, never fabricated zeroes.
Every export is audited.

**Tests.** `tests/test_hr_reports.py` (5), `tests/test_reports.py` (HR rows,
permissions, filters, every format), `test_report_reconciliation.py`.

## 9. Letters and printable outputs

**Letter templates.** Four seeded templates — offer, appointment, experience and
relieving — editable with `hr:write`. A template body may use the placeholders
`{employee_name}`, `{code}`, `{designation}`, `{department}`, `{joining_date}`,
`{exit_date}`, `{company_name}`, `{company_address}` and `{today}`. An unknown
placeholder is a 422; an experience letter without an exit date reports the
missing date rather than printing a blank.

**Generated PDFs**

| Output | Content | Confidentiality |
|---|---|---|
| Letter | Company, employee, dates, template body, signature | Scope-checked; no bank/ID/salary |
| ID card | Front: company, name, code, designation, department, branch, office, joining date, photo. Back: return address and phone, emergency contact, date of birth and phone, seal notice; front and back on A4 with cut marks | Scope-checked; footer states bank, PAN and salary are deliberately absent |
| Attendance sheet | Month grid, legend, totals and missing-day count | Same scope as the monthly screen |
| Leave statement | Stored balances, applications and gaps for a year | Read-only; does not create or adjust a balance |

Every generation writes an audit row. A staff member can generate only their
own; a manager only the chain; HR, payroll and the Administrator anyone in their
scope.

**Tests.** `tests/test_hr_documents.py` (6).

## 10. Notifications and announcements

- A request notifies the employee's own manager (or the queue) — never a
  colleague's manager.
- A decision notifies the requester.
- An announcement fans out to every active linked user and can be retired.
- A notification read is not audited; a send is recorded in the delivery log.
- The daily digest runs once per recipient per day; a second run does not
  duplicate notes.

**Tests.** `tests/test_hr_notifications.py` (4).

## 11. Scheduled HR pack

The pack is a registered e-mail pack with a monthly window. It reuses the HR
report layer, so the e-mail, attachments and screens cannot drift. It carries
headcount, attendance, leave, approvals and announcements, and **no salary
amount** (D-18). Rendering marks test mode; the worker sends it only through the
test-mode mailer until SMTP and recipients are approved.

**Tests.** `tests/test_hr_pack.py` (6).

## 12. HR masters

**What it does.** A single wide drawer, `HR → HR masters`, holds the lists that
payroll, leave and attendance read from, with a Create/Edit form per list. The
button **Branches & locations** inside the drawer opens the branch/office
screen; the same screen is reachable directly from HR tasks.

| Tab | Route | Rules |
|---|---|---|
| Departments | `GET/POST /api/hr/departments`, `PATCH /api/hr/departments/{id}` | code is created once and cannot be changed; a rename is unique and updates every employee linked by `department_id`, while free-text department names are untouched; status is retired rather than deleted |
| Holidays | `GET/POST /api/hr/holidays`, `PATCH /api/hr/holidays/{id}` | no branch and no office means company-wide; an office must belong to the chosen branch (422 otherwise); date and name cannot be cleared; attendance already marked keeps its recorded status |
| Leave types | `GET/POST /api/hr/leave/types`, `PATCH /api/hr/leave/types/{id}` | carry-forward, encashment, half-day and document flags; no rate prefilled |
| Salary components | `GET/POST/PATCH /api/hr/salary/components` | read and write need `hr:payroll_prepare`; a statutory head is allowed only on a deduction; every rate starts at 0 and is entered by the user, never inferred |
| Salary structures | `GET/POST /api/hr/salary/structures` | one line per component (duplicate is 422); a new start date on or before the active structure's start is 409; a later date closes the previous structure the day before; write needs `hr:write` **and** `hr:confidential` or `hr:payroll_prepare` |

**Employee salary tab.** The profile drawer adds a **Salary** tab for roles with
`hr:payroll_prepare`; it lists the employee's structures with their effective
window and opens the same structure form with the employee fixed. A structure
saved from the profile returns to the profile's Salary tab.

**Department assignment.** The one-page employee form suggests department names
from this master through a datalist. A name typed exactly as a department is
sent as `department_id`, so a later rename follows through; a name that matches
nothing is stored as free text and is not affected by a rename.

**Permissions.** Reads of departments, holidays and leave types follow
`hr:read`; every create and edit requires `hr:write`. The server enforces each
rule even if the button is hidden, and the role-boundary assertions live in
`tests/test_hr_masters.py`.

**Browser check (2 Nov 2026).** Department created and renamed with the change
propagating to the linked employee after a directory refresh; a holiday created
company-wide and then scoped to a branch and office; the office list narrowed
to the chosen branch; an employee assigned to an active branch and office; a
structure created from the masters and from the profile, the overlap guard
shown in the form, and a later structure closing the previous one. The only
error responses were the three deliberate ones (401 before login, 409 overlap,
422 inactive branch).

## 13. Known gaps and limitations

| ID | Gap | Effect |
|---|---|---|
| M-06 | **Closed 3 Nov 2026.** Payroll still does not pay an employee with no active salary structure, but the prepare result, the period screen and the audit entry now name every skipped employee with the reason, and the screen links to the salary-structure masters | The gap that remains is only the missing structure itself, which the screen now points at |
| M-09 | Manual attendance from the screen is status-only; punch times and office are API fields | A correction cannot set a punch time from the browser |
| — | No screen for attendance corrections, bulk attendance, leave-balance adjustment/carry-forward or the employee photo | API-only paths; see `FRONTEND_BACKEND_FIELD_MAPPING.md` and chapters 19–20 of the user manual |
| — | `hr:attendance_self` users can read leave types, own balances, applications and OD | Deliberate (D-23); every read is scoped |
| — | Bank file download event is audited, not the file contents | The preview masks account numbers; full numbers leave only in the downloaded file |
| — | HR manager sees bank/ID but not salary structures | Deliberate (D-15); grant `hr:payroll_prepare` if the answer changes |
| — | Payroll not posted to the ledger; overtime/salary-revision/reimbursement approvals absent | Not built (D-17, G-03) |
| — | No physical-device or screen-reader test of the HR screens | Only headless Chrome at 1400×1000 and 390×844 |

## 14. Test map

| Area | File | Tests |
|---|---|---:|
| Employee master, lifecycle, login link | `tests/test_hr.py` | 8 |
| Attendance, locks | `tests/test_hr_attendance.py` | 6 |
| HR dashboard | `tests/test_hr_dashboard.py` | 5 |
| Directory, saved views, import/export | `tests/test_hr_directory.py` | 5 |
| Documents, letters, ID card, statement | `tests/test_hr_documents.py` | 6 |
| Leave, balances, carry-forward | `tests/test_hr_leave.py` | 8 |
| Notifications, announcements, digest | `tests/test_hr_notifications.py` | 4 |
| Scheduled HR pack | `tests/test_hr_pack.py` | 6 |
| Statutory, bank file, payslips, reconciliation | `tests/test_hr_payroll_outputs.py` | 5 |
| Profile, documents, assets, photo | `tests/test_hr_profile.py` | 4 |
| HR reports | `tests/test_hr_reports.py` | 5 |
| Confidentiality and scope | `tests/test_hr_security.py` | 7 |
| Branches, offices and attendance rules | `tests/test_hr_sites.py` | 7 |
| Departments, holidays, salary components and structures | `tests/test_hr_masters.py` | 5 |
| **HR total** | | **81** |

The whole-project suite is 268 tests; the HR files are the 76 above. Central
report tests (`test_reports.py`), role parity (`test_roles_parity.py`) and the
dashboard tests also exercise HR paths.
