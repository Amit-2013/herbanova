# Scheduled email reports

Scheduled reports send the same figures the screens and Reports show, by email, to
the MD and the Administrators. Nothing in this document contains a credential: the
SMTP password is encrypted at rest, never returned by an API and never written to a
delivery row.

**Current state: test mode, sending disabled.** No real message can leave the
server until the owner sets the SMTP values and both switches below. Every queued
message is redirected to one Administrator address and prefixed `[TEST]`.

SMTP values may be saved on the **Settings → Email and SMTP** screen (stored in
`email_settings`, password encrypted). The environment values remain the deployment
default and are used for any field the screen leaves blank, so a server that has
never opened the screen behaves exactly as before migration `0017`. A saved
password can be replaced but never read back; the screen shows only
`password_set`.

---

## 1. The two switches

A real send requires **both**:

| Setting | Default | Effect |
|---|---|---|
| `EMAIL_MODE` | `test` | `live` is the only value that allows real recipients |
| `EMAIL_SEND_ENABLED` | `false` | `true` enables the mailer at all |

With either one off, `mailer.resolve()` returns one address — `EMAIL_TEST_RECIPIENT`
if set, otherwise the employee email of the first active Administrator. If no such
address exists the send fails closed with "Test mode: no Administrator email is
configured"; it never falls back to the real list. The subject gains `[TEST]` and
the message carries a banner naming the real recipient count that was not used.

"Send test to me" forces the redirect even in live mode, and uses the requesting
Administrator's own employee address when it is valid.

### SMTP settings

| Where | Purpose |
|---|---|
| **Settings → Email and SMTP** | Host, port, security, sending on/off, delivery mode, username, encrypted password, From, Reply-To, test To and test CC |
| Environment | Deployment default for every field; a saved value wins, an empty saved field falls through |

| Variable | Purpose |
|---|---|
| `SMTP_HOST`, `SMTP_PORT` | Server and port (587 default) |
| `SMTP_USER`, `SMTP_PASSWORD` | Optional login; never logged or displayed |
| `SMTP_STARTTLS` | STARTTLS on non-SSL connections (default true) |
| `SMTP_SSL` | Use SMTPS instead of STARTTLS |
| `SMTP_FROM`, `SMTP_REPLY_TO` | From and Reply-To addresses |
| `EMAIL_TEST_RECIPIENT` | The single address used in test mode |
| `EMAIL_MAX_BYTES` | Attachment budget, default 9,500,000 (below the 10 MB limit) |
| `EMAIL_WORKER_INTERVAL` | Seconds between worker cycles, default 60 |
| `APP_BASE_URL` | Used for the dashboard button and links in the email |

The saved password is encrypted with a Fernet key derived from
`herbanova:email:` plus `APP_SECRET`; the API returns a boolean `password_set`, and
the audit row records `unchanged`, `replaced` or `cleared` rather than any value.
Changing `APP_SECRET` with a saved password makes the field unreadable, and the
screen says so instead of pretending the password is set.

TLS is always used when configured, with a verifying SSL context. A missing
`SMTP_HOST` or `SMTP_FROM` makes `smtp_ready` false and a send is refused before
SMTP is contacted.

Live sending requires **both** the saved delivery mode `live` and
`EMAIL_MODE=live` in the server environment. The screen refuses to save `live`
with 409 while the environment still says `test`, so a browser alone cannot put
the installation into production mode.

There is **no password in any email**, attachment or delivery row. Attachments
are plain PDF and XLSX files; no archive is created and no link contains a token.

### Test composer

Settings → Email and SMTP has a composer with a message type, To, CC, subject and
body. Message types are `test`, `hr_notice`, `report_notice` and `custom`; picking
one fills a default subject and body that the Administrator can edit.

* **Dry run** (default) renders and stores the message in `email_test_messages`
  with status `captured` and mode `dry_run`; no socket is opened.
* **Deliver** uses exactly the saved settings and records `sent` or `failed` with
  the SMTP error. The sink used in verification was a local listener, never a real
  inbox.
* Every subject gains `[TEST]`, whatever the chosen type.
* At most ten To and ten CC addresses, each validated; an empty To is refused.
* A send or attempted send writes `email.test.send` to the audit log; the outbox
  keeps the message, size, mode, status and error.

---

## 2. Report packs

A pack fixes the period and the figures; the time of day only decides when the
message is generated.

| Key | Label | Period for a run | Suggested cadence |
|---|---|---|---|
| `daily` | Daily Business Summary | The previous complete day | Every working morning |
| `weekly` | Weekly Management Report | The seven days ending the day before the run | Monday morning |
| `monthly_md` | Monthly MD Report | Previous month on days 1–7, otherwise the current month to date | First working day |
| `alerts` | Alerts Digest | The seven days ending today, plus the current position | Daily or as needed |
| `accounts` | Accounts Report | Same rule as the monthly pack | Monthly, Accounts head |
| `custom` | Custom Report | The selected month, with chosen reports attached | Chosen |

Attachments by pack: `daily` (sales, invoices), `weekly` (sales, invoices,
purchases), `monthly_md` (sales, invoices, purchases, receivables ageing, GST
register), `accounts` (receivables, ageing, payables, GST register, trial
balance), `alerts` (none), `custom` (the reports ticked on the schedule).

Every pack that includes Accounts content also carries the Accounts summary block
(revenue, collections, returns, output GST, receivables, payables, and the gaps
for expenses, net profit and the balance sheet).

### Where the figures come from

`report_packs.build()` calls the same services as the screens: the dashboard's
period helpers for sales, purchases, orders and returns; `ledger.ageing_rows()`
for receivables; `accounting.window()` for payables, GST, cash movement and the
trial balance; the report catalog for attached registers. It does not copy a
query. A missing input is `available: false` with a gap code and renders as
"No data yet" — never as zero.

The previous period is the equally long window immediately before the pack's
window, and last year is the same window shifted back one year. A change against
zero is `null` and reads "No prior figure".

`period_for()` is deterministic: a monthly run on days 1–7 reports the completed
month, a later run reports month-to-date. The pack window is measured from the
slot's own local date, so a delayed send still reports the period that slot
owned.

---

## 3. Schedule timing

All arithmetic is in the schedule's timezone (`Asia/Kolkata` by default) and
stored as UTC. `zoneinfo` means a schedule moved to a DST zone would still fire
at the right local wall-clock time.

| Frequency | Rule |
|---|---|
| `daily` | Every calendar day |
| `weekdays` | Monday to Friday |
| `weekly` | Chosen weekdays (0 = Monday) |
| `monthly` | A chosen day 1–31, the last day, or the first working day |
| `custom` | Five-field cron subset: minute hour day month weekday, with `*`, lists, ranges and `/step` |

* Multiple `HH:MM` slots per schedule are allowed; duplicates are removed.
* A monthly day of 29–31 in a shorter month falls on that month's last day, so
  February is never skipped and a leap year needs no special case.
* A working day is Monday–Friday and **not** in `hr_holidays`. Weekends are never
  shifted; only a listed holiday triggers the schedule's rule:
  * `shift` — send on the next working day at the same times;
  * `skip` — do not send for that slot.
* The first-working-day rule uses the same definition, so a month starting on a
  holiday or weekend sends on the first real working day.
* `next_run()` searches 800 days ahead and returns the first slot strictly after
  "now". If no slot exists inside that horizon the schedule reports `skipped`
  with the reason instead of silently doing nothing.

---

## 4. Recipients

The recipient list is managed by the Administrator and has three groups:

| Group | Meaning | Unsubscribe |
|---|---|---|
| `md` | The MD (email only — there is no MD login) | Not offered; mandatory |
| `admin` | Administrators | Not offered; mandatory |
| `extra` | Anyone else the Administrator adds | Available via a token link |

A schedule sends to named recipients with a per-person field (To, CC, BCC) and/or
to whole groups. Groups are expanded at send time, so a new Administrator is
included without editing every schedule. Addresses are lower-cased, validated and
deduplicated across the three fields.

**Unsubscribe.** Each `extra` recipient has an unguessable token. The link only
deactivates that one address; it returns 403 for MD and Administrator groups.
Re-enabling is an Administrator action. Removing an address from the list never
deletes the delivery log.

**Accounts visibility.** Schedules are Administrator-only, and the Accounts block
is included by the schedule's `include_accounts` flag (default on). The screen
warns when the Accounts pack is addressed to the `extra` group. Put only the MD,
Administrators and an approved Accounts head on schedules that carry Accounts
figures: the email is one message for all its recipients, so the administrator
who builds the schedule is the gate. In the application, Accounts data is
enforced per user on the server by `accounts:reports` (see §9).

---

## 5. Screens (Administrator only)

`Settings → Email and SMTP` (`#/settings`) saves the SMTP configuration and holds
the test composer and outbox described in §1. The panel appears only while the
`scheduled` feature is on and the user holds `srAllowed()`; the API repeats the
`require_admin("email:manage")` check.

`Settings → Scheduled reports` (`#/scheduled`) has three tabs. The screen and the
route are offered only to the seeded Administrator holding `email:manage`; every
API route repeats the check with `require_admin("email:manage")`, so a custom role
granted the key still receives 403.

| Tab | Contents |
|---|---|
| Schedules | Pack, recipients and groups, human-readable timing, next run, last run and status, per-row warnings; Preview / Send test / Run now / Edit / Pause or Resume / Duplicate / Delete |
| Recipients | Address, name, group, active state, whether a schedule uses it, Edit / Remove |
| Delivery log | Time, pack, subject, trigger, period, recipient count, status, attempts, attachments with sizes, error, Resend |

Actions:

* **Preview** renders the HTML in the browser and sends nothing; no delivery row.
* **Send test** queues a delivery with trigger `test`; the worker redirects it to
  one address.
* **Run now** queues a delivery with trigger `manual`.
* **Duplicate** copies the schedule disabled, so enabling is a separate decision.
* **Delete** asks for confirmation, deletes the schedule and keeps its deliveries.
* A recipient used by a schedule cannot be removed until it is detached.

The screen banner always states the current mode, whether sending is enabled,
whether SMTP is ready and the size budget. The status endpoint returns these
facts with no secret values.

---

## 6. The worker

The application has no in-process scheduler: a timer would run once per web
worker and duplicate sends. Run one separate process:

```bash
python -m app.email_worker            # loop, checking every EMAIL_WORKER_INTERVAL
python -m app.email_worker --once     # one cycle, for cron or a smoke test
```

Each cycle does three things:

1. **Enqueue.** Every enabled schedule whose `next_run_at` has arrived gets one
   delivery row. The row's `run_key` is `schedule:<id>:<slot in UTC>` and is
   unique, so two workers or a restart racing for the same slot cannot both
   insert it. After enqueueing, `next_run_at` moves to the first slot after now:
   a worker that was down sends the slot it owes, not a backlog of stale ones.
2. **Release stale claims.** A delivery stuck in `sending` for 30 minutes is
   returned to `retry` (or `failed` if attempts are exhausted), because the
   worker that claimed it stopped.
3. **Process.** Queued and retry rows are claimed with `SELECT … FOR UPDATE SKIP
   LOCKED`, generated, rendered and sent. A paused schedule is skipped, not sent.

| Behaviour | Detail |
|---|---|
| Attempts | First try plus three retries |
| Backoff | 5, 15, 45 minutes |
| Permanent failures | Missing SMTP configuration, sending disabled, no active recipients, invalid address, unknown pack, deleted schedule — fail on the first attempt |
| Final failure | Status `failed`, error kept on the row, one Telegram alert, audit row |
| Restart / two workers | Unique run key; the insert loses the race instead of sending twice |
| If the worker is not running | Nothing is generated; the screen shows the next run as overdue |

If the schedule is paused or deleted after a row is queued, the delivery is
recorded as `skipped` with the reason.

---

## 7. The email itself

* Table-based HTML with inline CSS, 600–640 px wide, readable in Outlook, Gmail
  and on a phone. No JavaScript, no external font, no remote image.
* The logo and charts travel as CID PNG attachments drawn locally with Pillow.
  Every chart has alt text and the same figures in a table beneath it, so a
  blocked image loses nothing. A chart that fails to draw is dropped without
  failing the email.
* A plain-text alternative carries the same headlines, key figures, comparison,
  ageing and attention items.
* Accent `#1F6B4A`; buttons are at least 44 px high; colour is never the only
  signal — every change is written with an arrow and the words "up" or "down".
* Light and dark backgrounds are declared; the body has a dark-scheme media
  query.
* `[TEST]` subject prefix and banner in test mode; `PREVIEW` banner in the
  preview.
* Footer: who scheduled it, when it runs, "data as at", the source note, the
  confidentiality line, the dashboard button (login required), and the sample /
  test marker when applicable.
* The subject follows
  `HERBANOVA | Monthly MD Report | October 2026 | Sales ₹ X (...)`; the sales
  part is omitted when there is no sales figure.

### Sections

Green header with company and period → greeting and headline → KPI tiles →
Needs attention → Comparison table (current, previous, same period last year) →
Sales vs purchases chart and table → Receivables ageing chart and table →
Top products / top customers / top states → Accounts summary (revenue,
collections, returns, output GST, receivables, payables; expenses, net profit and
balance sheet as "No data yet" with their gaps) → Attached reports table →
dashboard button → footer.

---

## 8. Attachments

| Aspect | Rule |
|---|---|
| Files | Pack summary PDF, detail XLSX, and up to two register XLSX files |
| Naming | `HERBANOVA_<Pack>_<YYYY-MM>.pdf`, `HERBANOVA_<Pack>_<YYYY-MM>_Detail.xlsx`, `HERBANOVA_<Report>_<YYYY-MM>.xlsx`; daily and weekly use `<start>_to_<end>` |
| Listed in the email | File, what it contains, row count, size and format, plus "data is as at" |
| Budget | `EMAIL_MAX_BYTES` (9.5 MB default); when exceeded, register files are dropped first, then the detail file, then the summary, and the email says which files were left out and where to open them |
| Links | No expiring link is offered because no tokenised public dashboard exists (GAP-E05); the email says to open Reports instead |

A failure to build one attachment is recorded in the message and does not stop
the email.

---

## 9. Permissions and audit

| Right | Holder | Scope |
|---|---|---|
| `email:manage` | Seeded Administrator | The Email and SMTP panel, the scheduled-reports screen and both APIs |
| `accounts:reports` | Administrator (grantable to the MD / Accounts head) | Accounts dashboard, Overview Accounts tiles and the Accounts content in packs |

The settings API uses `require_admin("email:manage")`. A saved password is never
returned; only `password_set` is. Saving settings writes
`email.settings.update`; a test send or attempt writes `email.test.send`. Neither
audit row contains the password or the message body. The scheduler API uses
`require_admin("email:manage")` as well. The unsubscribe route is public but
addressed only by a 64-character random token and can deactivate only an `extra`
recipient.

Every schedule create, edit, pause/resume, duplicate, delete, recipient change,
manual run and test send writes an `audit_logs` row (`email.schedule.*`,
`email.recipient.*`, `email.queue`, `email.unsubscribe`). A successful worker
send writes `email.send` with pack, subject, mode, recipient count, attachment
count and period. A final failure writes `email.failed`. Routine sends do not
post to Telegram; only a final failure does.

The delivery log keeps rows indefinitely, so it always covers at least twelve
months. A resend creates a new row with trigger `resend` and leaves the original
intact.

---

## 10. API

All routes are under `/api/email-reports` and require the Administrator unless
noted.

| Method and path | Purpose |
|---|---|
| `GET /status` | Mode, send switch, SMTP readiness (boolean), test address, budget, packs, report catalog |
| `GET /recipients` · `POST` · `PATCH /{id}` · `DELETE /{id}` | Manage the recipient list |
| `GET /schedules` · `POST` · `PATCH /{id}` · `DELETE /{id}` | Manage schedules |
| `POST /schedules/{id}/enable` | Pause or resume |
| `POST /schedules/{id}/duplicate` | Copy disabled |
| `POST /schedules/{id}/run-now` | Queue a manual delivery |
| `POST /schedules/{id}/test` | Queue a redirected test |
| `GET /schedules/{id}/preview` | Rendered HTML, sends nothing |
| `GET /deliveries?status&pack&schedule_id&limit` | Delivery log |
| `POST /deliveries/{id}/resend` | New delivery from the original schedule |
| `GET/POST /unsubscribe/{token}` | Public; `extra` recipients only |

SMTP settings and the test composer are under `/api/email-settings`, also
Administrator-only:

| Method and path | Purpose |
|---|---|
| `GET /api/email-settings` | Effective settings (password replaced by `password_set`), suggested To address, message types |
| `PUT /api/email-settings` | Validate and save; `live` refused with 409 unless `EMAIL_MODE=live` |
| `POST /api/email-settings/test` | Build a `[TEST]` message; dry run by default, `deliver=true` opens one SMTP session |
| `GET /api/email-settings/test-messages` | Recent attempts and their status |

Run-now and test are refused with 409 when sending is switched off or SMTP is not
configured; queuing never pretends a message can be delivered.

---

## 11. Tests

| Area | Tests in `tests/test_email_reports.py` and `tests/test_email_api.py` |
|---|---|
| Period rules | Daily, weekly, completed month vs month-to-date |
| Figures | Pack sales equals the dashboard for the same dates; missing inputs are "No data yet"; trial balance balanced |
| Content | HTML and plain text carry the same figures and the test marker; every block is a table row; attachments are named and inside the budget |
| Accounts block | Equals `/api/accounts/report` for revenue, outstanding and output GST; gaps present |
| Test/live mode | Redirect to one address; fail closed with no address; live mode needs recipients; explicit and group recipients |
| Scheduling | A slot is enqueued once; two workers cannot create the same delivery; next run moves past it; paused schedule skipped; stale claim released |
| Failure handling | Transient failure retried four times with increasing delay; permanent failure stops at once |
| API | Administrator-only; status carries no secrets; validation; lifecycle; queue refused while disabled; preview sends nothing; delivery filters; unsubscribe rules; every schedule change audited |
| Settings and test composer (`tests/test_email_settings.py`) | Settings are Administrator-only; the password is never returned, is stored encrypted, and is kept, replaced or cleared explicitly; address validation; live mode refused while the environment says test; dry run stores `captured` and opens no socket; real send through a local sink; refused connection recorded `failed`; saved values drive the scheduler recipient; switching the feature off closes the API |

The email worker is exercised with a stub mailer. One settings test opens a
connection, but only to a `smtplib` sink started by the test itself on `127.0.0.1`;
no test contacts an outside server or sends to a real address.

---

## 12. Go-live checklist (owner approval required)

Nothing below has been done; the system is in test mode.

1. Approve the sender address and Reply-To.
2. Enter `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`,
   `SMTP_REPLY_TO` and the security option on **Settings → Email and SMTP**, or
   set the matching `SMTP_*` environment values. Do not put them in `.env` copies,
   screenshots or chat.
3. Confirm From, Reply-To and the test To/CC addresses, then run a **Deliver**
   test from the composer to the approved test inbox. Check rendering in Outlook,
   Gmail and on a phone.
4. Approve the recipient list: MD group, Administrator group, any extras. Confirm
   who may receive the Accounts block.
5. Set `EMAIL_MODE=live` in the environment, then switch the saved delivery mode
   to `live` and sending to enabled (the screen refuses `live` before the
   environment does).
6. Run **Send test to me** once more, then **Run now** on one low-risk schedule.
7. Start `python -m app.email_worker` under the process supervisor used by the API
   server, with `--interval` as agreed.
8. Check the Delivery log and the audit entries for the first sends.
9. Schedule the monthly MD report for the first working day; confirm the next-run
   time and the holiday rule.
10. Decide the retention/backup policy for `email_deliveries` and
    `email_recipients`; the application never deletes delivery rows.

Apply migration `0011_email_reports` before starting the worker. It adds four
tables and two Administrator keys and has a downgrade that removes only what it
added. Apply `0017_email_settings` for the saved SMTP configuration and test
outbox; it adds two tables and no rows, and its downgrade drops only those tables,
so the installation returns to the environment-only defaults.

---

## 13. What is skipped, and why

| Item | Reason |
|---|---|
| Per-recipient content in one message | SMTP sends one body; the Administrator builds one message per audience and the screen warns when Accounts content would reach the `extra` group. Separate Accounts-only schedules are supported. |
| Secure expiring download link for oversized attachments | No tokenised public dashboard exists (GAP-E05); the email names the files and points to Reports. |
| In-process scheduler | Would duplicate sends per web worker; a separate DB-backed worker is used. |
| Automatic retention deletion | Deleting delivery rows destroys evidence of what was sent; retention is left to the owner. |
| Expense, cost and profit figures | Not captured (GAP-A01/A02); shown as "No data yet" with the gap code. |
| Holiday calendar maintenance | The worker reads `hr_holidays`; keeping it current is an HR task. |
