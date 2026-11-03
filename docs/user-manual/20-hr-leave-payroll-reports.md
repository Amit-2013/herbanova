# Chapter 20 — HR: leave, on-duty, payroll and HR reports

**Audience:** HR manager, payroll officer, Administrator, reporting manager; a self-service employee for their own leave, on-duty and payslips.
**Screens:** **HR Management** and **Approvals**.
**Written:** 1 November 2026 against the build at migration `0018_attendance_rules`.

This chapter follows the HR request from “I need a day off” to the payslip and
the report. It states the rules the server enforces and the controls the screen
actually offers; where a rule is API-only, it says so.

## 20.1 What an employee sees

A user without `hr:read` gets **My workspace**, not the team dashboard:

- **My attendance** and **My monthly attendance** — own rows only.
- **Leave** — own balances, own applications, and the apply form.
- **On duty** — own requests.
- **My payslips** — released payslips only.
- **My ID card** and **My leave statement** — PDFs built from the own record.
- **Notifications** — announcements and decisions addressed to them.

Every call behind those buttons is scoped to the signed-in employee on the
server. A manager sees their reporting chain; HR and the Administrator see the
whole company, subject to confidentiality.

## 20.2 Leave

**Leave** opens a drawer with three parts: **Balances**, **Apply for leave** and
**Applications**.

### Balances

The **Balances** table shows **Type**, **Entitled**, **Used**, **Pending** and
**Available** for the signed-in user's own employee record. Another person's
balances — including **Carried** — are on their profile (chapter 19, 19.4).

If no leave type is configured the panel says **No leave types.** Leave types
now have a screen under **HR masters** (chapter 19, 19.6); an HR role with
`hr:write` creates them there. Opening balances still have no screen and are
loaded through the API. Until a type exists, the apply form has nothing to
choose and cannot submit.

### Applying

1. Choose the **Leave type**.
2. Write a **Reason** of at least three characters.
3. Choose **From** and **To**. Both default to tomorrow.
4. **Submit application**. The message reads “Leave submitted for approval”.

The form refuses missing dates (“Choose both dates.”) and an empty reason
(“Give a reason.”).

**Rules the server applies.**

| Rule | Behaviour |
|---|---|
| Working days | The request counts working days: weekly offs and applicable holidays are excluded. Stored historical `days` are not recalculated |
| One calendar year | An application may not cross 31 December; balances are per year |
| Length | The span `date_to − date_from` may not exceed 90 days |
| Balance | A paid leave type refuses a request above the available balance; an application never creates a negative balance |
| Overlap | A request overlapping a pending or approved one is refused |
| Approval | Submitting reserves **Pending** days; approval moves them to **Used** and writes the attendance rows; rejection releases them |
| Lock | Approval that would write into a locked attendance month is refused |

**Not on the screen.** Half-day leave (allowed only when the leave type allows
it, one date, 0.5 day), a required supporting document, party/destination
fields and balance adjustment or carry-forward are server fields with no
control here. If you need them, ask the Administrator; do not expect a button.

### Applications

The table lists **Employee**, **Type**, **Dates**, **Days**, **Status** and
**Remarks** for the applications you may see — your own, your chain's, or the
company's, according to your scope.

### Approving leave

Decisions are made in **Approvals**, not in the HR drawer.

1. Open **Approvals** in the sidebar. You need `approval:read` to open the list
   and `hr:leave_approve` to decide.
2. Filter to **Pending** and open the request. It shows the employee, the type,
   the requested dates and the reason.
3. Write a **Reason** of at least three characters and choose **Approve** or
   **Reject**.

The server refuses a decision when:

- you raised the request (“Segregation of duties: you cannot decide a request
  you raised”);
- the employee is outside your reporting chain (“That request is outside your
  team”);
- your role lacks `hr:leave_approve`;
- the attendance month is locked.

On approval the attendance rows for the leave dates are written, so the day is
leave in the monthly register and in payroll. A rejection leaves attendance
untouched and releases the pending days.

### Leave calendar

**Leave calendar** (team readers only) shows a month grid with approved names,
a **pending** count per day, holiday tags and shaded weekends. **Month**,
**Department** and **Refresh** control it; the table below lists every
application in the month with its status.

Nothing is deducted until an application is approved — the drawer says so.

## 20.3 On duty (OD)

**On duty** opens the OD drawer with **New OD request** and **Requests**.

1. **Employee** — offered only when you can read the team; a self-service user
   files their own.
2. **Date** — defaults to today.
3. **Visit type** — for example “Customer visit / Field work”.
4. **Destination** and **Purpose**.
5. **Submit OD request**.

Visit type and purpose are required. The request goes to the reporting manager
with `hr:leave_approve`.

On approval an OD attendance row is written, so the day counts as on duty in the
register and in payroll. A rejection leaves the day untouched. The **Requests**
table shows **Employee**, **Date**, **Visit**, **Purpose**, **Status** and
**Remarks**.

The server also accepts a duration, party, worksite and an optional document;
the screen does not offer them.

## 20.4 Payroll

Payroll is a closed book: the **Payroll** button appears only with
`hr:payroll_prepare`, and the API refuses to list a period to anyone without it.

### Opening a period

**Payroll** opens the period list. **Open a payroll period** takes a **Year** and
a **Month**; **Create period** adds it as **draft**. The drawer states the
lifecycle: “Draft → Under review → Approved → Processed → Paid. A period cannot
be paid twice.”

### The lifecycle

| State | Action in the drawer | Who may do it |
|---|---|---|
| draft | **Prepare** | `hr:payroll_prepare` |
| under_review | **Recalculate** | `hr:payroll_prepare` |
| under_review | **Submit for approval** (raises an HR approval) | `hr:payroll_prepare` |
| approved | **Process** | `hr:payroll_approve` |
| processed | **Mark paid** | `hr:payroll_approve` |
| any | **Open** — view the register | `hr:payroll_prepare` |

Approval itself happens in **Approvals**, like leave and OD. The person who
prepared the period cannot approve it: the server answers “The person who
prepared payroll cannot approve it”. A period that is not **under_review** cannot
be approved (“Payroll period is not under review”).

Preparing recalculates the period while it is **draft** or **under_review**; an
approved period cannot be recalculated.

### What the calculation uses

- Active employees with an active salary structure effective in the month.
- Approved attendance, leave and on-duty.
- The configured salary components. No statutory rate or amount is written in
  the code.

| Rule | Behaviour |
|---|---|
| No attendance rows | The month is treated as fully present. This is a stated assumption (D-14), not a hidden one |
| Half day | A paid half-day counts 0.5 present + 0.5 paid leave; an unpaid half-day counts 0.5 present |
| Payable days | `min(working days, present + paid leave)`; loss of pay is the remainder |
| Pro-rating | Earnings are prorated by payable ÷ working days. **INCENTIVE**, **OVERTIME**, **BONUS** and **REIMBURSEMENT** are not prorated |
| Exempt days | A day the attendance policy exempts is not an absence and is not loss of pay |

**Who was skipped (M-06).** An employee with no active salary structure is still
not paid by the run, but the screen now says so. After **Prepare**, and whenever
you open the period, a **Skipped** block lists each active employee left out with
the reason — **No active salary structure covers this month** or **Not in the
prepared entries** — and a **Assign salary structures** button takes you to the
salary-structure masters (chapter 19, 19.6). The same codes are written to the
audit entry, so a short run can be traced later. Do not read a short run as
correct without reading this list first.

### The register

**Open** shows **Employee**, **Department**, **Payable days**, **LOP**,
**Gross (₹)**, **Deductions (₹)** and **Net (₹)**.

- The **Slip** link appears with `hr:confidential`.
- **Download salary register (Excel)** needs both `hr:reports` and
  `report:export`.
- The statutory summary, bank file and reconciliation exist on the server with
  no control on this screen.

Payroll is not posted to the accounting ledger (D-17). Overtime, salary-revision
and reimbursement approval handlers do not exist.

### Payslips

**My payslips** lists only periods that have been **processed** or **paid**, for
the signed-in employee. Each row downloads a PDF. A payslip for someone else is
available through the payroll register with `hr:confidential`. Before processing,
nothing is released.

## 20.5 Period locks

**Period locks** (`hr:write`) closes a month against changes.

1. Choose the **Scope** — **Attendance**, and **Payroll** when you also hold
   `hr:payroll_prepare`.
2. Choose the **Year** and **Month**.
3. Give a **Reason** of at least five characters.
4. **Lock month**.

**Lock history** shows **Scope**, **Month**, **Status** (locked/open),
**Locked** (who and when) and **Reason**, including the unlock reason after a
reopen.

Effects:

- Attendance writes and approvals into the month are refused with **423** and
  the lock reason.
- A payroll lock freezes that month's payroll: prepare, submit, process and pay
  are refused.
- Only the Administrator sees **Unlock**, and the unlock needs a reason of at
  least five characters. The unlock is audited.

Lock the previous month once it is reconciled; the drawer says the same.

## 20.6 HR reports

**HR reports** (`hr:reports`) opens a wide drawer.

**Filters:** **From**, **To**, **Branch**, **Office**, **Refresh**.

**The seven reports** are **Headcount**, **Joiners and leavers**,
**Attendance summary**, **Late and absentee**, **Leave balances**,
**Department cost** and **Document expiry**.

Each row shows **Access**: **open** or **restricted**. A restricted report says
“Ask the Administrator for confidential HR rights.” — **Department cost**
requires `hr:confidential` or `hr:payroll_prepare` in addition to `hr:reports`.

For an open report:

- **View** builds it below the list. The report states its **filters**, a
  **summary**, and the rows. The screen shows the first 100 rows and says
  “Showing the first 100 of N rows. Download the CSV for all of them.”
- An empty period shows **No data yet for these filters.** and lists **gaps**
  rather than filling zeroes.
- **CSV** and **PDF** download the full report. Every export is audited.

A branch or office filter narrows every report to the employees assigned there,
and the report header repeats the filter the server applied.

The central **Reports** screen also carries twelve `hr_*` reports (employee
master, attendance, leave, OD, payroll, approvals, joining/exit, late arrival,
missing punch, leave balance, payroll deductions, approval turnaround). They
obey the same permissions and are described in chapter 18 when it is written.

## 20.7 Announcements and notifications

### Announcements

**Announcements** (`hr:write`) publishes a **Title** and a **Message** to every
active user with a linked employee record. The confirmation names how many users
were notified. **Send daily digest now** sends that day's digest immediately;
the scheduled digest runs once per recipient per day.

**Published** lists **Title**, **Published**, **Status** and **Hide**. Hiding
retires an announcement but does not delete it.

### Notifications

The **Notifications** button carries an unread count. The drawer lists each note
with its text and time; **Mark read** clears one, **Mark all read** clears the
list, and **Open** follows the note's link. Approvals and announcements appear
here. Reading is not audited; sending is recorded in the delivery log.

## 20.8 The scheduled HR Report Pack

The Administrator can schedule the **HR Report Pack** from **Scheduled reports**
(`email:manage`, Administrator only). It carries headcount, attendance, leave,
approvals and announcements with a monthly window, and **no salary amount**
(D-18), because pay stays behind the confidential right in the application.

The screen shows whether the deployment is in **test mode**. In test mode every
message is redirected to the test recipient and marked as a test; nothing goes
to the real list. Live delivery requires both the deployment approval and SMTP
configured by the Administrator.

## 20.9 Messages you may meet

| Message | What it means | What to do |
|---|---|---|
| **Segregation of duties: you cannot decide a request you raised** | You are the requester | Let another approver decide |
| **Your role cannot decide leave or on-duty requests** | Missing `hr:leave_approve` | Ask the Administrator |
| **That request is outside your team** | The employee is not below you in the chain | Ask HR or the Administrator |
| **The attendance period … is locked: …** | The month is closed | Ask the Administrator to reopen it with a reason |
| **Leave application is not pending** | It was already decided | Refresh the list |
| **The person who prepared payroll cannot approve it** | Segregation of duties | A different approver decides |
| **Payroll period is not under review** | It was not submitted, or already decided | Check the period status |
| **No payslip has been released yet** | Payroll has not processed the period | Wait for processing |

## 20.10 What this chapter does not cover

| Missing control | Effect |
|---|---|
| Half-day leave, leave document, leave-balance adjustment, carry-forward | API only |
| Paying an employee who has no salary structure | Not done by the run; the **Skipped** list names them and links to the masters (M-06 closed 3 Nov 2026) |
| Attendance correction request and bulk marking | API only |
| OD duration, party, worksite and document | API only |
| Payroll statutory summary, bank file and reconciliation | API only |
| Posting payroll to the accounting ledger | Not built (D-17) |
| Overtime, salary-revision and reimbursement approvals | Not built |

## 20.11 Verification for this chapter

- Leave approval (including the self-approval refusal and the attendance
  effect), the payroll lifecycle, and period locks are exercised by
  `tests/test_hr.py`, `tests/test_hr_leave.py`, `tests/test_hr_attendance.py`
  and `tests/test_hr_payroll_outputs.py`.
- OD creation and approval are read in source and covered by the scoped read in
  `tests/test_hr_leave.py` and the report tests; there is no direct OD approval
  test. Treat that path as **VERIFIED (code)**, not exercised end to end.
- Announcements, the digest and notifications are covered by
  `tests/test_hr_notifications.py`; the HR Report Pack by `tests/test_hr_pack.py`;
  the seven reports by `tests/test_hr_reports.py`.
- The leave, OD and payroll **forms were not submitted in a browser** during
  this review; the automated browser refused write actions. The rules above come
  from the source and the tests, not from a recorded click-through.
- On 2 November 2026 a separate test instance allowed writes: a salary structure
  was created from **HR masters** and from an employee **Salary** tab, the
  overlap refusal was shown in the form, and a later structure closed the
  previous one. `tests/test_hr_masters.py` covers the structure guards.
- The **Skipped** block on a payroll period is covered by `tests/test_hr.py`
  (prepare result and register agree; reason text) but was **not** seen in a
  browser; the markup and the API response were read instead. Mark it
  **Not verified in the browser** until a write-enabled session is allowed.
- No salary, bank, statutory or live employee figure appears in this manual.
