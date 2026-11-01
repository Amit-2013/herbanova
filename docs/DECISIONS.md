# Decisions and assumptions — HR upgrade and verification

This file records decisions that could not be settled from the code alone, so a later
reader can see why the implementation looks the way it does. The dashboard work kept its
log in `docs/DASHBOARD_DECISIONS.md`; this file starts with the whole-project audit and the
HR upgrade.

| # | Date | Decision / assumption | Why | Reversible? |
|---|---|---|---|---|
| D-01 | 1 Nov 2026 | `docs/DECISIONS.md` is created as the running log; `docs/DASHBOARD_DECISIONS.md` is left in place as the dashboard-specific history. | The brief names `docs/DECISIONS.md`, which did not exist. Deleting or rewriting the dashboard log would lose history. | Yes |
| D-02 | 1 Nov 2026 | "MD" is implemented as the Administrator plus any custom role the Administrator grants `hr:confidential`. No new `md` role is invented. | The live `roles` table has no MD role. Creating one would change access without authorisation. | Yes, by adding an MD role later |
| D-03 | 1 Nov 2026 | Confidential employee fields (bank name/account/IFSC, PAN, UAN, ESI) are returned masked to callers without `hr:confidential`, except the employee viewing themself and the Administrator. The response keeps the field present, with a masked display value and a `confidential` flag. | Removing fields would break existing screens; masking is additive and server-enforced. | Yes |
| D-04 | 1 Nov 2026 | Salary structure writes require `hr:confidential` or `hr:payroll_prepare` in addition to `hr:write`. | `hr:confidential` is described as the salary gate but did not gate writes; the change makes the key meaningful. The Administrator bypasses it. | Yes |
| D-05 | 1 Nov 2026 | `hr_payroll` approvals are visible only to users with payroll prepare/approve or confidential rights; other HR approvers keep their own categories. | Net payroll is confidential financial data and must not reach a leave approver. | Yes |
| D-06 | 1 Nov 2026 | Leave days are counted as **working days** (shift weekly offs and applicable holidays excluded) for new applications; historical stored `days` values are not recalculated. Half-days are recorded as a portion of a day. | Counting calendar days overstates leave. Recalculating history would alter approved records, which the brief forbids. | Yes for new rows |
| D-07 | 1 Nov 2026 | Attendance and payroll period locks are additive, default unlocked, and every override needs an Administrator role, a written reason and an audit entry. | Existing periods must keep working; locks cannot silently change historical totals. | Yes |
| D-08 | 1 Nov 2026 | Statutory payroll (PF/ESI/PT/TDS) appears only where the Administrator has configured a component marked `statutory` with a rate. Unconfigured rules are shown as gaps; no rate is hard-coded. | "Do not invent rules." | Yes, by configuration |
| D-09 | 1 Nov 2026 | Notification e-mails use the existing test-mode mailer. A delivery is proven by the stored delivery/test record, never by sending to a real inbox. | Standing instruction: no real e-mail and no secrets printed. | Yes, when SMTP is approved |
| D-10 | 1 Nov 2026 | Bulk employee import accepts CSV only in this phase (Excel requires an extra parser). A template, preview with row errors, commit and undo are provided; imported rows are tagged with a batch id. | CSV is already used by exports; adding an Excel dependency is a larger change than the requirement needs. | Yes |
| D-11 | 1 Nov 2026 | The two employee endpoints (`/api/employees` and `/api/hr/employees`) are kept for compatibility. The HR endpoint becomes the authoritative read for the HR screens and gains the confidentiality rules; the legacy endpoint keeps its narrow public fields. | Existing screens and tests call both. Removing one would break them. | Yes, after callers migrate |
| D-12 | 1 Nov 2026 | "No data yet" is returned as an explicit availability flag/`null` rather than a fabricated zero where a figure has no source rows. Zero is shown only when the source was queried and is genuinely zero. | Never invent data or numbers. | Not applicable |

## Open decisions for the product owner

These do not block the build; the implementation proceeds with the stated default and the
default is visible in the UI.

| # | Question | Default used |
|---|---|---|
| Q-01 | Which custom roles besides Administrator should hold `hr:confidential`? | Whatever the live role table grants; no role is changed automatically. |
| Q-02 | Is leave encashment a payroll earning? | Not paid automatically; a recorded encashment creates an audit entry and a note, and payroll uses only configured components. |
| Q-03 | Should attendance lock also block corrections? | Yes: any change to a locked month needs the Administrator override and reason. |
| Q-04 | Is an MD login required separately from the Administrator? | No MD role is assumed; the Administrator acts for the MD until an MD role exists. |
