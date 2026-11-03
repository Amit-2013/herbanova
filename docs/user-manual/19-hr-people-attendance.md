# Chapter 19 — HR: people, shifts and attendance

**Audience:** HR manager, Administrator, reporting manager; a self-service employee for their own attendance.
**Screen:** sidebar **HR Management**.
**Written:** 1 November 2026 against the build at migration `0018_attendance_rules`.

This chapter describes the screens as they exist. Labels in **bold** are the
literal on-screen labels. Where the server supports something the browser does
not offer, the chapter says so instead of describing a screen that is not there.

## 19.1 Who sees what

The server checks your role on every request. A hidden button is a convenience,
not a control.

| You want to | Your role needs |
|---|---|
| See the team dashboard, People list, monthly register, leave calendar | `hr:read` |
| Check in, check out, see your own attendance, apply for your own leave or OD, download your payslips | `hr:attendance_self` |
| Add or edit an employee, and import employees | `hr:write` |
| Record attendance manually for someone else | `hr:attendance_manage` |
| Create branches, offices, attendance rules, shifts, announcements, letter templates, period locks | `hr:write` |
| Open the Payroll screen | `hr:payroll_prepare` |
| Approve payroll, process it and mark it paid | `hr:payroll_approve` |
| Open HR reports | `hr:reports` |
| See salary, bank and statutory numbers | `hr:confidential` or `hr:payroll_prepare` (you always see your own) |
| Unlock a locked month | the Administrator, and no one else |

A role holding only `hr:attendance_self` sees **My workspace** instead of the
team dashboard. Every list and report it opens is restricted to that person's
own record by the server (`static/js/app.js:2849-2853`).

## 19.2 The HR dashboard

Open **HR Management**. The page is one dashboard: headcount, today, trends,
the People list and the task buttons.

### Date range and site filters

- **From** and **To** with **Apply** set the reporting period. Quick choices are
  **This month** and **Last 30 days**. The period may span at most 366 days.
- **Branch** and **Office** narrow the dashboard, the People list, the monthly
  register and the HR reports to that place. Choosing an office also selects its
  branch. Choosing a branch clears an office that belongs to another branch.
- The line under the title states today's obligation, for example
  “N of M active employee(s) must mark attendance today; K exempt.” It is
  computed from the attendance rules (19.6).

Invalid dates are refused in the screen: “Choose both dates.” and
“The end date cannot be before the start date.”

### What the cards show

| Card | Meaning |
|---|---|
| **On the rolls** | Active employees; the note gives inactive and total records |
| **Present today** | Present plus late; the note gives late and early departure |
| **Not in today** | Absent + on leave + on duty; the note splits the three |
| **Joiners this month** | New joiners; the note gives exits this month and in the range |
| **Approvals waiting** | Pending HR requests; the note gives leave and how many are older than three days |
| **Probation ending** | Within 30 days |
| **Documents expiring** | Within 60 days |
| **Salary payable this month** | Only with payroll rights; **No data yet** when no payroll period exists for the month |

A figure the server cannot compute is shown as **No data yet**, never as zero.
The dashboard's **Needs attention** list opens four groups: **Missing punches**,
**Leave balance below zero**, **Approvals older than three days** (which opens
Approvals) and **Incomplete employee records**. Each opens a drawer with the
complete count and at most 20 rows.

**Attendance** charts the last 31 days of the chosen period with a legend for
Present, Leave, On duty and Absent; **Approved leave by type** lists days and
applications. **Celebrations and holidays** covers the next 30 days. **Team
shape** shows departments by headcount, then **By branch** and **By office**.

An empty range says so, for example “No data yet: no attendance rows between …”.
Nothing is filled in with invented figures.

### People

The **People** table lists employees with **Employee**, **Department**,
**Designation**, **Location** (the office, with the branch underneath),
**Joined**, **Status** and **Open**.

- **Location** shows “–” when no office is assigned.
- A person the attendance rules exempt carries a **No attendance** chip; hover
  over it to read the rule that exempts them.
- Search covers name, code, department, branch and office. **All statuses** and
  **All departments** narrow further, and the branch and office selectors above
  also apply.
- The count reads “N of M employees.” When the list reaches its 200-record
  reading limit the note says so and asks you to narrow the search.
- **Saved filters** stores the current search, status, department, branch and
  office under a name you choose. **Apply**, **Save current** and **Delete** act
  on it. A saved view belongs to the person who created it.
- **Export CSV** downloads the People list with the same filters. Bank, PAN and
  statutory columns are masked unless your role may see them.

## 19.3 Employee master and the employee form

**Employee master** (top-right of the HR page, `hr:write`) opens the whole list
with an **Edit** button per row and a **New employee** button. Employees are
deactivated, never deleted.

### Fields on the form

| Field | Notes |
|---|---|
| **Employee code** | Required when creating; normalised to upper case; read-only afterwards |
| **Full name** | Required, at least two characters |
| **Department** | Free text |
| **Designation** | Free text |
| **Phone**, **Email** | Optional |
| **Joining date**, **Employment type** | Optional |
| **Branch** | Optional; a branch groups its offices |
| **Office / work location** | Optional; only offices of the chosen branch are offered |
| **Shift** | Optional; the office/general shift applies when empty |
| **Status** | **Active** or **Inactive** |

The **Branch** and **Office / work location** pair can never disagree. Picking a
branch hides the offices of other branches; picking an office fills its branch.
The server repeats the check: a mismatched pair is refused with **422**.

Under the pair, **Attendance policy** states the resolved result before you save
(the company default), and after the employee exists it states the rule that
applies — for example “Attendance policy: not required · self check-in off ·
Office default (South Office - Bengaluru).”

The form does **not** carry a manager, date of birth, address, emergency
contact, probation or exit dates, bank/PAN/statutory numbers or a photo. Those
are server fields: set them through the employee import (19.9) or the API. The
import template carries `manager_code`, `date_of_birth` and the bank/ID columns;
the rest have no screen in this build.

## 19.4 The employee profile

**Open** in the People table (or **Edit employee** in the profile) shows the
record in five tabs: **Overview**, **Documents (n)**, **Assets (n)**,
**Letters & ID** and **History**. A role with `hr:payroll_prepare` also sees a
**Salary** tab between **Documents** and **Assets**; it is described in §19.6.

**Overview** shows identity and job data, contacts, branch, office, shift and
**Attendance policy** with its source. **Bank and statutory numbers** appear only
to a role allowed to see them; otherwise the panel says the server masks them
rather than sending them to the browser. Leave balances for the current year are
listed with entitled, carried, used, pending and available days.

**Documents** — **Add a document** asks for **Type**, **Title**, **Number**,
**Issued on**, **Expires on** and **Status** (**Active**, **Expired**,
**Replaced**). Type and title are required; the expiry cannot be before the
issue date. Documents are never deleted; mark a replaced one **Replaced** so the
history stays intact. A number is shown as **masked** to a reader without the
confidential right.

**Assets** — **Issue an asset** records **Type**, **Name**, **Serial number**,
**Issued on** and **Condition note**; **Return** records the return date and
condition. A returned asset stays in the history as returned.

**Letters & ID** — **ID card (PDF)**, **Leave statement (PDF)** and one button
per active letter template. A letter stops with the missing date instead of
printing a blank, and every download is audited.

**History** lists the audited changes with actor and the changed fields.

There is no photo control on the screen; the photo routes exist for the API and
the ID card.

## 19.5 Branches and locations

**Branches & locations** (`hr:write`) opens a wide drawer titled *Branches,
offices & attendance policy* with three tables: **Branches**, **Offices and work
locations** and **Attendance requirements**. Every change is audited. The same
drawer opens from the **Branches & locations** button inside **HR masters**
(§19.6).

### Branch

**New branch** asks for **Branch code**, **Branch name**, **Address** and
**HR responsible at this site**. On an existing branch the code is read-only and
**Status** becomes editable.

- The code is upper-cased and cannot be changed once the branch exists.
- An inactive branch keeps its history and accepts no new assignment.
- The HR responsible is the person who answers for attendance at that site. It
  is informational: it does not grant approvals and does not change who may
  decide leave.
- A branch with active staff cannot be switched off until those people are
  reassigned.

### Office / work location

**New office** asks for **Office code**, **Office name**, **Branch**,
**Attendance mode**, **Address**, **Latitude**, **Longitude**,
**Geofence radius (metres)** and **HR responsible at this site**.

| Rule | Behaviour |
|---|---|
| Branch | An office belongs to one branch; the branch is required for the office to appear in branch filters |
| Attendance mode | **Office**, **GPS** or **Office or GPS** |
| Geofence | Give both coordinates or neither; latitude −90 to 90, longitude −180 to 180; radius at least 1 metre |
| Status | **Active** / **Inactive**; an office with active staff cannot be switched off or moved until they are reassigned |

A GPS check-in is compared with this centre and radius. Self check-in still
depends on the attendance rule: an employee exempt at this office is refused
even when GPS matches.

### Attendance requirements

**New attendance rule** has twelve controls plus **Note**:

| Control | Meaning |
|---|---|
| **Branch** | Applies to everyone in the branch (least specific) |
| **Office / work location** | Applies to everyone at the office |
| **Designation** | Applies to that designation (free text, with suggestions) |
| **Employee** | Applies to one person (most specific) |
| **Attendance** | **Required** or **Not required** |
| **Self check-in** | **On** or **Off** |
| **Shift** | Optional override |
| **Attendance mode** | **Office default**, **Office**, **GPS**, **Office or GPS** |
| **Effective from**, **Effective to** | Inclusive dates; either may be left open |
| **Priority (1 comes first)** | 1–1000; breaks ties between equally specific rules |
| **Status** | **Active** / **Inactive** |

Leave a target empty to mean “any”. The more targets you fill, the more specific
the rule.

**Which rule wins.** The most specific active rule for the date:
employee (1000) → office (100) → designation (10) → branch (1). Equal
specificity is broken by the lower priority number, then the newest rule. With
no matching rule, attendance is **required** and the source reads
“Company default”; an office with no rule reads “Office default (name)”.

**Guards.**

- Two active rules cannot target exactly the same set of people.
- Only one company-wide rule can exist at a time.
- The end date cannot be before the start date.
- A rule that names an office must name that office's branch. A named employee
  who is assigned to a different office or branch is refused, because the rule
  could never match.
- **Delete** asks for confirmation, and the people it covered fall back to the
  next matching rule or the company default.

**What “not required” means.** An exempt employee is refused a check-in,
check-out, correction, manual entry or bulk row by the server with the rule
named, so the hidden controls are a convenience, not the control. In the monthly
register an exempt day is **– not required**, never an absence, and payroll does
not count it as loss of pay.

## 19.6 HR masters

**HR masters** (`hr:write`; salary tabs need `hr:payroll_prepare`) opens a wide
drawer with five tabs: **Departments**, **Holidays**, **Leave types**, **Salary
components** and **Salary structures**. Each tab has **New …** and **Edit**
forms. Codes are permanent; a record is retired by setting it inactive instead
of deleting it, because payroll, leave and attendance history still point to it.
Every change writes an audit row.

### Departments

Create with **Department code** and **Department name**. On an existing
department the code is read-only, the name can change and **Status** is editable.

- A rename is refused if another department already uses that name.
- Employees linked to the department are updated by the rename. The link is made
  when the department name on the employee form matches a master name exactly;
  free-text department names on other employees are left alone.
- The employee form suggests the master names as you type.

### Holidays

Record **Date**, **Holiday name**, and optionally **Branch** and **Office**.

| Choice | Applies to |
|---|---|
| Branch and office empty | The whole company |
| Branch only | Every office in that branch |
| Branch and office | That office |

- An office that belongs to a different branch is refused.
- A holiday date or name cannot be blanked once saved.
- Marking attendance on a date that later becomes a holiday does not rewrite
  history: the status already recorded stays.

### Leave types

Create with **Code**, **Name**, **Paid / Unpaid**, **Days per year**,
**Carry forward**, **Encashable**, **Half day** and **Document required**.
No number is prefilled as a company entitlement; enter the policy your company
uses.

### Salary components

An **Earning** or **Deduction** with a **Calculation** of **Fixed amount**,
**% of basic** or **% of gross**.

- A **statutory head** (provident fund, employee state insurance, professional
  tax, tax deducted at source) applies only to a deduction; marking an earning
  statutory is refused before saving. Gratuity and full-and-final settlement
  are not modelled.
- **Default rate** starts at zero and is a starting value for new structure
  lines, never a hidden payroll rule. Nothing is calculated until a structure
  supplies the amount or percent.
- Only roles with payroll preparation rights can open this tab; changing a
  component needs `hr:write` as well.

### Salary structures

A structure is the employee's pay for an effective period. Choose **Employee**,
**Effective from**, **Payment mode** (bank transfer, cash or cheque), tick each
component that applies, then enter the **Amount** for a fixed component or the
**Percent** for a % of basic/gross component.

- Each component appears once; a duplicate is refused.
- A new structure must start after the current one. If you choose the same date
  or earlier, the save is refused and the previous structure still applies.
- A later date closes the previous structure the day before, so payroll always
  finds exactly one structure for the month.
- Payroll uses the structure that covers the month; an employee with no active
  structure is still skipped (see the warning in §20.4).

### Salary tab on the employee profile

A role with `hr:payroll_prepare` sees a **Salary** tab in the employee profile.
It lists the employee's structures with their effective window and a **New
salary structure** button. The form opens with the employee fixed, and saving
returns you to the same tab. Salary is confidential: the tab is shown only to
payroll-enabled roles, and every change is recorded in the audit trail. The
server does not write an audit row merely because the tab was opened.

## 19.7 Shifts

**Shift settings** lists **Shift**, **Office hours**, **Grace (min)**,
**Weekly offs** and **Status**.

**New shift** / **Edit** records **Shift name**, **Start time**, **End time**,
**Grace period (minutes)** (0–120), **Status**, **Full day hours**,
**Half day hours** and the **Weekly offs** checkboxes. A new shift starts at
09:30–18:30 with a 10-minute grace, 8/4 hours and Saturday and Sunday off.

- Late arrival is measured from the start time plus grace; early departure from
  the end time.
- Start and end cannot be the same, and the day lengths must be greater than
  zero.
- Changing a timing does not rewrite minutes already recorded. Future check-ins
  use the new timings.

## 19.8 Attendance — today

**Attendance** opens today's register.

### Checking in and out

**Check in** and **Check out** are yours only (`hr:attendance_self`).

1. The screen first reads your resolved policy. If attendance is not required it
   stops with “Attendance is not required for you (source). Nothing was
   recorded.” If self check-in is off it stops with “Self check-in is switched
   off (source). HR records your attendance.”
2. The browser asks for your location at that moment only — never in the
   background. If you refuse or the location times out, the check-in is sent
   without coordinates and the message says “Checked in (location unavailable)”.
3. A check-in inside the office geofence is recorded as inside. One outside is
   still recorded and raises a location exception for an approver; the decision
   appears in Approvals.
4. **Check out** needs today's check-in and records worked minutes and early
   departure. Check-out before check-in is refused.

The policy line at the top of the drawer reads, for example, “Your policy:
attendance required · self check-in on · Office default (South Office -
Bengaluru).”

### The register

The table lists **Employee**, **Status**, **Check-in**, **Check-out**,
**Location** and **Late**. **Location** is the geofence result (inside, outside
or manual). **Refresh** reloads it.

### Manual attendance

With `hr:attendance_manage` the drawer also offers **Manual attendance**:
**Employee**, **Date**, **Status** and **Remarks (required)**. The statuses are
Present, Absent, Half day, Paid leave, Unpaid leave, On duty, Late and Early
departure. The remark must be at least three characters; the entry is audited
with your name, the old value and the new value.

- Exempt employees are not offered: the form states how many are excluded and
  points to the policy drawer.
- If nobody is required to mark attendance, the form says so and **Save manual
  attendance** is disabled.
- The screen records a **status only**. Punch times, the office and overtime are
  API fields, not screen fields (M-09).

### Corrections

A correction request exists on the server (`POST /api/hr/attendance/{id}/correction`)
but this build has **no button for it**. Once a request exists it appears in
Approvals with a reason and is decided by a holder of
`hr:attendance_manage` inside the team. The monthly register shows such a day
as **C — correction pending**.

### Locked months

If the month is locked, the server refuses the write with **423** and names the
reason. The screen cannot supply an override reason; only the Administrator can
override a single entry through the API, and that override is audited.

## 19.9 Monthly attendance

**Monthly attendance** (or **My monthly attendance** for staff) shows a month
grid per employee.

- Filters: **Month**, **Department**, **Branch**, **Office**, **Refresh** and
  **Sheet (PDF)**.
- Legend: **P** present, **L** late, **H** half day, **L / U** leave,
  **O** on duty, **A** absent, **W / F** weekly off / holiday,
  **–** not required, **·** not recorded.
- Columns after the days: **Present**, **Leave**, **Absent**, **Not recorded**,
  **Not required**.
- Hovering a cell shows the date, status, punches, worked time and late minutes
  when present.

The distinction that matters: a **blank day** was not recorded and is a gap; a
day the policy exempts is **not required** and is not a gap. The footer repeats
both counts. Absence is only what somebody recorded as absent.

## 19.10 Importing employees

**Import** (`hr:write`) opens a drawer that creates nothing until you confirm.

1. **Download template (CSV)**. The columns are `code`, `full_name`,
   `department`, `designation`, `phone`, `email`, `joining_date`,
   `date_of_birth`, `employment_type`, `manager_code`, `branch_code`,
   `office_code`, `department_code`, `bank_account_no`, `bank_ifsc`, `pan`,
   `uan`, `esi_no`.
2. Choose the file and **Check the file**. The server validates every row and
   shows **Valid rows**, **Rows with errors**, a preview (Code, Name,
   Department) and a list of the rows it cannot import with their reasons.
   Unknown columns are refused.
3. **Import valid rows** creates the valid rows and leaves the rest out. The
   result offers **Undo this import**, which removes that batch.

Bank and ID columns require `hr:confidential` or `hr:payroll_prepare`; without
that right, leave them out. A duplicate employee code is refused. The whole
import is recorded in the audit trail.

## 19.11 Letter templates

**Letter templates** (`hr:write`) lists each template with its code and status.
**Edit** changes the name, the body and whether it is **Active**. The body may
use the placeholders shown at the top of the drawer; the braces are filled from
the employee record. An unknown placeholder is refused when you save.

A retired template stays in the list but cannot generate a letter.

## 19.12 Messages you may meet

| Message | What it means | What to do |
|---|---|---|
| **Attendance is not required for you (…). Nothing was recorded.** | Your rule exempts you | Ask HR to change the rule if this is wrong |
| **Self check-in is switched off (…). HR records your attendance.** | A rule says HR marks your attendance | Ask HR to record it |
| **That employee is outside your team** | The person is not below you in the reporting chain | Ask HR or the Administrator |
| **The attendance period … is locked: …** | The month is closed | Ask the Administrator to reopen it, with a reason |
| **Check-out must be later than check-in** | Times are in the wrong order | Correct the times |
| **Give a reason of at least three characters.** | Manual attendance needs a remark | Write the reason |
| **Give both the latitude and the longitude, or neither.** | Half a geofence | Fill both or clear both |
| **Latitude must be between -90 and 90 and longitude between -180 and 180.** | Coordinates out of range | Correct them |
| **A branch or office with active staff cannot be switched off or moved…** | People are still assigned | Reassign them first |
| **No employee must mark attendance. Add an attendance rule before recording it manually.** | Every active employee is exempt | Create or change a rule |

## 19.13 What this chapter does not cover

These exist on the server but have no control in this build. They are recorded
as gaps, not described as screens:

| Missing control | Effect |
|---|---|
| Attendance correction request | API only; approvals still work once raised |
| Bulk attendance marking | API only (`POST /api/hr/attendance/bulk`) |
| Punch times, office and overtime in manual attendance | API fields (M-09) |
| Employee photo upload | API only |
| Manager, address, emergency contact, probation/exit fields on the employee form | API or import (`manager_code`, `date_of_birth`) |
| Leave-balance adjustment and carry-forward | API only |
| Saving a new leave type or salary component through the browser | The forms exist; the write was not exercised in the 2 Nov 2026 check and has no automated test (F-108, F-109) |

## 19.14 Verification for this chapter

- The branch, office and rule screens, the cascade, the Location column, the
  **No attendance** chip, the resolved policy text, the monthly legend and the
  site filters were read in a browser on 1 November 2026 (read-only check,
  `docs/VERIFICATION_REPORT.md` §10.2). Screenshots were unavailable in that
  environment.
- Creating and editing through the browser was **not** exercised by the 1 November
  review: the automated browser refused write actions. The branch, office and
  rule paths are covered by `tests/test_hr_sites.py`, `test_hr_directory.py`,
  `test_hr_attendance.py`, `test_hr.py`, `test_hr_profile.py` and
  `test_hr_documents.py`.
- On 2 November 2026 a separate test instance allowed writes. Verified live:
  department create and rename with the linked employee following after a
  directory refresh, holiday create and edit with company-wide then branch+office
  scope and the office list narrowing to the branch, employee assignment to an
  active branch and office, and salary structures created from both the masters
  and the profile. The overlap guard appeared in the form, and a later structure
  closed the previous one. `tests/test_hr_masters.py` (5 tests) covers the same
  write paths and role boundaries. Creating a leave type or salary component
  through the browser was **not** exercised and is listed as a gap above.
- The exempt employee's screen state (**No attendance**, **– not required**,
  refused check-in message) is proven by `test_hr_sites.py`; the development
  database held no attendance rule when the manual was written, so that state
  was not seen live.
- Employee figures and lists in this chapter are described, not sampled. No
  live payroll, salary or bank figure appears in this manual.
