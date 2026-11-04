# 1. Getting Started

**Audience:** everyone with a login.
**Chapter status:** written and verified against source on 31 October 2026; §1.6 (detail drawers), §1.10 (Administrator two-step verification, screen layout refreshed), §1.11 (starting the servers) and §1.12 (the application shell) added 3 November 2026; §1.1 and §1.2 rewritten on 4 November 2026 for the new sign-in page (Administrator-managed banner, notices, help line and legal pages) and the **Save ID** / **Forgot Password** controls; §1.12 extended and §1.13 added on 4 November 2026 for workspace tabs, breadcrumbs and favourites.
**What you need:** the application address from your administrator, a username, and your password.

## 1.1 Opening the application

Enter the address in a browser. The server root redirects to **`/ui/`** (`app/main.py:71-81`), which is the single-page application. The sign-in screen asks for a **User ID** and a **Password**. Usernames are matched case-insensitively; the password is case-sensitive.

The page has two columns on a desktop, one column on a phone or a narrow tablet:

| Area | Position | Who writes it |
|---|---|---|
| Promotion banner | Left, above the notices | Administrator, **Settings → Sign-in page** |
| **Notices** | Left, with the date, title and text of each notice | Administrator |
| **Sign in** form | Right, top | Fixed: User ID, Password, **Save ID**, **Forgot Password?**, **Login** |
| **Help line** | Right, under the form | Administrator; one box per team (Sales, Service, Customer Support) |
| Copyright and **Privacy Policy** / **Terms & Conditions** | Footer | Company name from the company profile; the two documents from the Administrator |

Everything except the form itself is stored on the server and can be changed without touching the page. **A part the Administrator has not filled in shows “No data yet” and is never replaced with sample text**: an empty notice list says *No data yet*, a missing banner shows *No data yet* in the promotion area, and a legal page whose text has not been published opens with **Not published yet**. Banners rotate automatically in sort order; the arrows and dots let you choose one, and the rotation stops while the pointer or keyboard focus is on the banner, while the tab is hidden, and when the **reduced motion** system preference is on. **VERIFIED (code)** for the rotation rule: the browser walk had one banner, so the six-second cycle was not exercised.

On a phone the form comes first, then the help line, then the banner and notices, so nothing has to be scrolled past before signing in.

**VERIFIED:** the public payload is `GET /api/public/sign-in` and the banner image is served by `GET /api/public/sign-in/banners/{id}/image` (`app/api/signin.py:145-184`); the browser renders it in `refreshSignInContent()` (`static/js/app.js:461-470`). The empty states come from `signinEmpty()` (`app.js:339-343`). The whole page was walked at 1440, 768 and 390 px in both themes on 4 November 2026 (`docs/VERIFICATION_REPORT.md` §27).

**VERIFIED (code):** `POST /api/auth/login` normalises the username to lower case before lookup (`app/api/auth.py:55-59`) and sets an HttpOnly cookie called `session` (`auth.py:72-73`). The browser never stores the password or a token in JavaScript.

## 1.2 Signing in

1. Type your User ID. Spaces before and after are ignored.
2. Type your password. It is not displayed.
3. Select **Save ID** if you want the browser to remember the User ID on this computer (see below).
4. Select **Login**.

On success the application closes the sign-in screen, loads your identity and permission list from the server, and opens the main shell. The top-right corner shows your username, your role and a **Sign out** button.

**Save ID.** The saved User ID is kept in this browser only — never on the server, and never the password. It is stored only after a **successful** sign-in, so a mistyped ID is not remembered. The next time the sign-in page opens, the User ID is filled in and the box is already ticked. Untick **Save ID** and sign in again, or clear the User ID, to forget it.

**Forgot Password?** opens a panel titled **Forgot password** that names the Administrator as the person who resets passwords and shows the **Customer Support** help-line box the Administrator configured (detail, phone and email). The page deliberately does **not** send an e-mail or reset anything: a reset is issued from **Logins and employees**, and the new temporary password must be changed at the next sign-in (§1.3). If the Administrator has not added a help-line box, the panel says so instead of inventing a phone number.

**Administrator accounts take a second step.** If you sign in as the Administrator or Super Admin, the password alone does not open the shell: a **Two-step verification** screen asks for a six-digit code from Google Authenticator, or — the first time — asks you to set the app up. This is described in §1.10.

**VERIFIED:** the browser re-reads `/api/auth/me` after login instead of trusting a copy of the permissions kept in the page (`static/js/app.js:112-123`). What you can see is therefore decided by the server, not by the screen. **Save ID** was exercised end to end on 4 November 2026: ticked and signed in → stored; signed out and reloaded → filled in and ticked; unticked and signed in → cleared (`docs/VERIFICATION_REPORT.md` §27).

### If the password is wrong

The message is **"Username or password is incorrect."** for every failed sign-in. The application deliberately does not say whether the username exists.

| Situation | What happens |
|---|---|
| 1–4 wrong passwords | The attempt is counted silently. You may try again. |
| 5th wrong password | The account locks for **15 minutes**. The message says so and gives the number of minutes. The counter then starts fresh, so another five failures cause another lock. |
| Login from one address too often | The login endpoint allows **20 requests per minute per IP address**; beyond that the server returns **429 Too many requests. Please wait a moment and try again.** |
| A correct password during a lock | Refused until the lock expires — the lock is checked before the password. |

**VERIFIED (code):** `MAX_FAILED = 5` and `LOCK_MINUTES = 15` in `app/services/lockout.py:14-15`; the failure is recorded per user record, so changing the letter case of the username does not reset it; a successful sign-in clears the count (`lockout.py:29-48`). The rate limit is `20/minute` at `app/api/auth.py:30` and the 429 body is set in `app/main.py:27-30`.

A lockout is written to the audit trail as `auth.lockout` (`app/api/auth.py:65`). An administrator can unlock the account from **Logins and employees** by resetting the password, which also ends every open session.

## 1.3 Temporary passwords and the first sign-in

An administrator creates a user or resets a password in **Logins and employees** (Settings & Administration → Logins and employees). The server generates a temporary password that meets policy and shows it **once**; the administrator must pass it to you directly. The account is marked "Temporary" and the server requires a password change before anything else.

Signing in with a temporary password opens a blocking **Set a new password** screen instead of the main shell. The server allows only `/api/auth/me`, `/api/auth/logout` and `/api/auth/change-password` until the password is replaced (`app/core/rbac.py:27-29, 74-100`), so there is no way past this screen except changing the password or signing out.

1. Type the temporary password in **Current password**.
2. Choose a new password and repeat it in **Confirm new password**.
3. Select **Change password and continue**.

The application checks that the two entries match, that the new password meets the policy, and that it differs from the current one. If the server rejects the current password or the policy, the reason appears on the screen and nothing else changes. On success the shell opens with your role, the audit trail records `auth.password_change`, and every other session for the account is ended.

**VERIFIED:** the screen is `#mustChange` / `#changePwForm` (`static/index.html:43-59`), driven by `must_change_password` on the identity (`static/js/app.js:90,116-146`); the flow was exercised in a browser against a throwaway database on 31 October 2026, and the server-side block, policy checks and session revocation are asserted by `tests/test_authz.py`. This closes mismatch **M-01**.

If you ever see **403 You must change your password before using the application** without the screen, sign out and sign in again; the identity in the browser is out of date. Do not ask an administrator to read or share your password.

**Password policy (enforced by the server and shown in the Logins screen):** at least 12 characters and at most 128; at least three of lowercase, uppercase, digits and symbols; not the same as the username; the new password must differ from the current one. **VERIFIED (code):** `app/core/security.py:24-25, 53-73`; `app/api/auth.py:97-104`.

## 1.4 Sessions

| Property | Behaviour |
|---|---|
| Lifetime | **60 minutes** from sign-in. There is no silent renewal; after expiry the next request returns **401** and the sign-in screen reappears. |
| Storage | An HttpOnly cookie named `session`. The `Secure` flag is set outside the local environment. |
| Revocation | Changing or resetting a password, or deactivating the user, increments `token_version`; every older cookie then receives **401 Session expired** immediately, even if it has not reached 60 minutes. |
| Signing out | **Sign out** in the top-right corner calls `/api/auth/logout`, clears the cookie and returns to the sign-in screen. |

**VERIFIED (code):** `max_age=3600` at `app/api/auth.py:73`; revocation at `app/core/rbac.py:43-54`; sign-out at `static/js/app.js:3125`.

If you leave a shared machine, sign out. Closing the tab does not clear the cookie, although the cookie expires after 60 minutes on its own.

## 1.5 What you will see

The rail lists up to 25 screens in five top-level groups — **Overview**, **Sales and customers**, **Stock and supply**, **Finance and insight**, and **People and admin**. Each top-level group carries a category label (for example *Pipeline* or *Invoicing*), and screens are listed under it. The menu is built by the server for your account, so it shows exactly the screens your role and the enabled modules allow; the server refuses anything you are not permitted to use, so a visible page can still show only the records you may read. The menu is drawn immediately from the application's built-in list while the server answers; if the server cannot supply it, the same built-in list is kept and a notice with **Retry** appears above **Favourites** — the rail is never empty. Adding `?nav=builtin` to the address restores the built-in list for the rest of the session (the manual does not ask you to edit addresses; this is the administrator's fallback).

| Sidebar entry | Usually requires | What it is for |
|---|---|---|
| Overview | Any signed-in user | Counts and work queues drawn from the whole database |
| Leads / Lost leads / Today's follow-ups | `lead:read` for the list; `lead:write` to work it | Enquiry pipeline |
| Customers & distributors | `sales:read` (the entry is always listed; without it the list is empty) | The single buyer master: search, status filter, credit limit, exposure and exposure meter. `distributor:write`, `sales:write` and `credit:manage` add the Open, New order and Change limit buttons |
| Sales orders | `sales:read`; `sales:write` to create | The order-to-dispatch workflow |
| Billing | `sales:read` | Issued invoices, notes and movement details |
| Purchases | `stock:read`; `stock:write` to create | Purchase orders and goods receipts |
| Products | `product:read`; `product:write` to edit | Product master and tax fields |
| Inventory | `stock:read` | Warehouses, batches, stock and movement ledger |
| Free samples | `foc:read`; `foc:write` to record, `foc:approve` to decide | Free-of-cost samples: issue, register and their cost treatment |
| Suppliers | `supplier:read` | Supplier master and bank-change requests |
| Approvals | `approval:read` | Credit-limit, sales-order, post-billing and HR requests |
| Accounting & Finance | `accounts:read`; `accounts:write` to act | Outstanding, party ledgers, GST register, trial balance, ledger heads, openings, vouchers, day book, balance sheet, bank reconciliation |
| Expenses | `expense:read`; `expense:write` to add | Expenses, their approval and reversal |
| Reports | Per-report permission; `report:export` to download | The single reports page |
| Geography | `sales:read` | Sales, returns and GST by buyer state |
| HR Management | `hr:read` or `hr:attendance_self` | Employees, attendance, leave, OD, payroll |
| **Roles & Permissions** | `user:manage` (Administrator role for module switches) | Role tree editor, permission catalogue, access-control rules and module On/Off switches |
| Settings & Administration | `user:manage`, `tax:read`, `audit:read` or `hr:read` | Company profile, tax, logins/employees, email and audit |
| Scheduled reports | `email:manage` | Report packs, recipients and the delivery log |

**VERIFIED (code):** menu visibility at `static/js/app.js:220-246`; reports permissions at `app/api/reports.py:83-85`; the full permission-to-role table is in [`../permissions-matrix.md`](../permissions-matrix.md).

An **employee** without `hr:read` sees the HR home page with their own attendance only; the directory, leave/OD registers and payroll buttons are hidden and refused by the server (`static/js/app.js:602-610`).

**Branches, offices and attendance policy.** Every employee can be placed in a **Branch** and an **Office / work location** in the New/Edit employee form; only the offices of the chosen branch are offered, and choosing an office fills its branch. HR Management shows the office under **Location** in the People table, plus a **No attendance** chip when the policy exempts that person. A role with `hr:write` can open **Branches & locations** to create branches and offices, set a geofence, and write attendance rules. **HR masters** on the same screen holds departments, holidays, leave types, salary components and salary structures; a role with payroll preparation rights also sees a **Salary** tab on each employee profile to assign a structure. The branch and office selectors above the People list, the monthly register and the HR reports narrow every figure to that branch or office, and a printed sheet repeats the filter it used. An employee who is not required to mark attendance is refused a check-in by the server, and their exempt days appear as **not required**, never as absences.

## 1.6 Detail drawers

Most records open in a panel that slides in from the right over the list you were reading — an invoice, a customer or supplier, a distributor ledger, a purchase order, an expense, an HR record or any Accounts entry. The list stays behind it, dimmed but visible, so you do not lose your place.

**How wide it is.** The drawer takes a share of the screen, so a ledger or invoice line table can be read without leaving the list:

| Your screen width | Drawer width |
|---|---|
| Large desktop (1440 px and wider) | 62% of the screen (60–65% band) |
| Desktop (1024–1439 px) | 68% (65–70% band) |
| Tablet (768–1023 px) | 82% (80–85% band) |
| Phone (below 768 px) | The whole screen |

**What the drawer does.**

- It slides in from the right. The background page stays visible and darkened on a desktop or tablet.
- The title and the **×** (close) button stay at the top; only the record below them scrolls.
- The background page cannot scroll while the drawer is open, and it scrolls again as soon as the drawer closes.
- On a phone the drawer fills the screen and the form fields stack in one column.
- Table headers stay pinned to the top of the record while you scroll a long ledger.
- Columns are tightened to fit the drawer; a very wide table (for example an invoice with CGST, SGST and IGST columns) scrolls inside its own box rather than dragging the whole drawer sideways, and the money columns keep their full figures.

**How to close it.** Select **×**, or press **Escape**. On a desktop or tablet you can also click the darkened page outside the drawer. On a phone the panel fills the screen, so use **×** or **Escape**. Closing with any of these returns you to the list with the keyboard back where it was.

Nothing about the record changes because of the wider panel: the same fields, buttons, permissions and server checks apply, and a save or action sends the same request as before.

**VERIFIED:** the shared drawer was measured in the real application (test database) at 1600×900, 1280×900, 900×900 and 390×844 px on 3 November 2026 — widths 62%, 68%, 82% and 100%; no page-level horizontal scrolling; the pinned header stayed 4 px below the scrolled body's top; the **×**, Escape and outside click each closed the drawer and released the background scroll lock; no script error. The invoice, customer and distributor-ledger drawers were opened, and the dark theme was checked. Evidence and the list of what was not tested are in [`../VERIFICATION_REPORT.md`](../VERIFICATION_REPORT.md) §22. Physical phones, tablets and screen readers were not tested.

## 1.7 Messages you may see

| Message | Meaning | What to do |
|---|---|---|
| **Username or password is incorrect.** | The username does not exist, is inactive, or the password is wrong. | Re-type both. Five failures lock the account. |
| **Account temporarily locked after too many failed attempts…** | A 15-minute lock is active. | Wait, or ask an administrator to reset the password. |
| **Too many requests. Please wait a moment and try again.** | More than 20 sign-in attempts per minute from your address. | Wait at least a minute. |
| **You must change your password before using the application** | A temporary password is in force, or the browser identity is out of date. | The change screen should appear at sign-in (§1.3); if it does not, sign out and in again. |
| **Not authenticated** / **Session expired** | The cookie is missing, expired or revoked. | Sign in again. |
| **That code was not accepted.** | An Administrator's six-digit code was wrong, or one already used. | Enter the code on screen for the next 30-second step (§1.10). |
| **Too many wrong codes. Try again in N minute(s).** | Five wrong codes in a row; code entry is paused for 15 minutes. | Wait, then sign in again (§1.10). |
| **Start signing in again** | The password step of an Administrator sign-in expired after 10 minutes. | Begin again with the username and password (§1.10). |
| **Two-factor verification required** | The session did not complete the code step. | Sign in again (§1.10). |
| **Permission denied** | Your role does not hold the required permission, or the screen allowed an action the server refuses. | Ask an administrator; do not retry repeatedly. |
| **Only an Administrator can do this** | The action needs the Administrator role itself, not just a permission. | Ask the Administrator. |
| A red message inside a form | Validation failed; the text names the field or rule. | Correct the field and submit again. |

**VERIFIED (code):** the server messages are the literals in `app/core/rbac.py`, `app/api/auth.py` and `app/core/security.py`; the browser shows the server's detail text in the form (`static/js/app.js:118`).

## 1.8 If you cannot sign in

1. Check that you are using the address ending in `/ui/`.
2. Check the username spelling; case does not matter.
3. If the message is "locked", wait 15 minutes.
4. If it still fails, ask an administrator to reset the password. The administrator can see whether the account is **Temporary** or **Locked** in the Logins screen and can end every open session by resetting.
5. If the page loads but every panel is empty and the address bar is correct, the session may have expired; sign in again. If it persists, report your username, the time and the exact message — never your password.

## 1.9 Roles and permissions (administrators)

Open **Roles & Permissions** in the sidebar. The screen has three parts:

| Part | What an administrator does |
|---|---|
| Roles | Review each role's permission and user count; **Edit permissions** opens the tree editor; **New role** creates a custom role |
| Feature availability | Switch a module on or off for everyone. A switched-off module keeps its stored role assignments but grants nobody access until it is switched back on |
| Access control | Read the whole catalogue: each module gate, each child permission with the parent it needs, and the rights reserved for the Administrator |

The tree editor follows one rule: a **parent** permission is the module gate. Ticking it makes its children selectable but grants none of them. Tick each child you want; unticking the parent clears its children. A child without its parent is refused by the server. Four rights (`approval:credit_limit`, `invoice:edit_post_billing`, `email:manage`, `db:reset`) stay locked to the Administrator and cannot be given to another role.

Module switches are Administrator-only even if a custom role holds `user:manage`. User accounts and temporary passwords are managed separately under **Settings & Administration → Logins and employees**. Every role change and every switch is written to the audit trail.

## 1.10 Two-step verification (Administrator accounts)

**Who it applies to.** Only the **Administrator** and **Super Admin** roles. Every other role signs in with a password alone, exactly as §1.2 describes. The server decides this from the account's role, so a custom role does not receive it and there is no permission switch to turn it on or off. The design and the operator procedure are in [`../ADMIN_2FA.md`](../ADMIN_2FA.md) (decision D-46).

**What it needs.** A code from **Google Authenticator** or any authenticator app. No SMS, no e-mail and no internet connection is needed after the app holds the key; the code is calculated from the key and the device clock.

**First sign-in (enrollment).**

1. Type the username and password and select **Sign in**.
2. A **Set up two-step verification** screen appears instead of the shell and shows a setup key.
3. In the authenticator app choose **Add account → Enter a setup key** and type the key. The screen shows the account name and the settings it uses: issuer Herbanova, SHA1, six digits, 30 seconds.
4. Type the six-digit code the app shows and select **Confirm and continue**.
5. The screen lists **ten recovery codes**. Save them somewhere safe now — they are shown once. Select **I have saved them — continue** to open the shell.

Until a code is confirmed, the password step opens no session, so no data can be read. Finishing enrollment ends any earlier session for the account.

**What the screen looks like.** Both steps use a single centred card on a soft paper background, with the brand at the top, the setup key or code field in the middle and the action button below. A refused code appears as a red band inside the card. The recovery-code list uses two columns on a desktop and one on a phone, and the card follows the light or dark theme chosen for the application.

**Every later sign-in.**

1. Username and password, then **Sign in**.
2. The **Two-step verification** screen asks for the current six-digit code. Type it and select **Verify and continue**.
3. If the phone is unavailable, select **Use a recovery code instead** and type one of the saved codes. Each recovery code works once.

**Rules and messages.**

| Situation | What happens |
|---|---|
| Wrong code | **That code was not accepted.** Type the code on screen now; if it is about to change, wait for the next 30-second step. |
| The same code twice | The server remembers the last accepted step, so a used code is refused; wait for the next one. |
| Five wrong codes in a row | Code entry pauses for **15 minutes**; the message says how many minutes remain. The password step itself is not locked. |
| Recovery code | Single use; a code already used is refused. No screen shows how many are left, so keep the list you saved at enrollment. |
| Password step older than 10 minutes | **Start signing in again.** Begin at the username and password. |
| A session that skipped the code step | The server answers **401 Two-factor verification required**; sign in again. |
| Password reset by an administrator | Does **not** remove the second factor. The account still needs its code. |

**Lost phone and no recovery codes.** An administrator cannot recover the codes from the screen, and a password reset does not clear the second factor. An operator clears the account's two-step columns as described in [`../ADMIN_2FA.md`](../ADMIN_2FA.md); the next sign-in then starts enrollment again.

**Deployment note (3 November 2026).** The second factor is enforced by the server, its tests pass, and enrollment was walked in a browser. The migration that adds its columns (`0029_totp`) is applied to the disposable test database and to the development database (applied 3 November 2026 after a verified backup), so on both an Administrator is sent through enrollment at the next sign-in. It is **not** applied to production. See [`../ADMIN_2FA.md`](../ADMIN_2FA.md).

## 1.11 Starting the application (administrators and operators)

The application can run as **two processes** — an API server and a front-end server — instead of one:

```bash
python scripts/run_backend.py     # API, default http://127.0.0.1:8000
python scripts/run_frontend.py    # browser entry, default http://127.0.0.1:3000
```

- `run_backend.py` serves the API and its documentation.
- `run_frontend.py` serves the `/ui/` pages and forwards `/api`, `/docs`, `/openapi.json` and `/redoc` to the backend, so the browser still uses one address and the session cookie travels unchanged.
- Both scripts accept `--port`; the front-end also accepts `--backend http://127.0.0.1:8000` when the API is elsewhere. Run either with `--help` for the full list.
- If the backend is stopped, the front-end answers **502** and says the API is not reachable instead of showing a broken page.

Commands, options, the proxied paths, cookie and `APP_ENV` behaviour, and the evidence are in [`../RUNNING_SERVERS.md`](../RUNNING_SERVERS.md) (decision D-44).

## 1.12 The application shell

After sign-in every screen shares the same frame.

| Part | Where it is | What it does |
|---|---|---|
| **Application bar** | A dark forest strip across the top, 44 px high | Brand on the left (select it to return to Overview), **Search pages and records** in the middle, **Dark theme** / **Light theme** on the right |
| **Workspace tab bar** | A light strip directly under the application bar | One tab per screen you have opened, with **Home** pinned first. Select a tab to switch screens; **×** closes it; the **⋯** button lists the tabs that do not fit and offers **Close current tab**, **Close other tabs**, **Close all except Home** and **Reopen closed tab** (§1.13) |
| **Search** | The search button, or **Ctrl K** / **⌘ K** from anywhere | Opens the command palette: type at least two characters to find screens, products, orders, invoices and parties your role may read. **Esc** closes it |
| **Module rail** | The left column on a desktop or tablet | Five top-level groups — Overview, Sales and customers, Stock and supply, Finance and insight, People and admin — split into categories. **Favourites** and **Recently opened** appear above them once you have used the star or opened a few screens |
| **Page head** | Right of the rail, above the content | A breadcrumb (**Module › Category › Feature**), then one title, a short factual subtitle, the **☆** favourite button and, where the screen has one, the primary action on the right of the title |
| **Status bar** | A thin strip at the bottom | A factual statement about the figures and the name of the environment the server reports |

**On a phone or a narrow tablet** the tab bar stays under the application bar and scrolls sideways; the rail becomes a band below it: your username, role and **Sign out** sit on the right, and the module list runs horizontally below them (swipe it sideways to reach later modules). The status bar keeps only the environment name.

**Light and dark.** The theme control changes the whole application and is remembered in the browser. It does not change any figure, permission or saved record. The sign-in and two-step screens follow the theme chosen for that browser.

**Where figures come from.** No screen invents a number. A panel the server cannot compute says **No data yet**, names the missing input and links to the screen that supplies it; a section your role may not read is absent, never zero.

**VERIFIED:** the shell was reviewed in the running application on 3 November
2026 at 1440, 1024, 768 and 390 px in both themes, with the drawer and palette
open, using only read requests. The tab bar, breadcrumbs, favourites and
recently opened screens were added on 4 November 2026 and walked at 1440, 768
and 390 px in both themes (`var/shots/wp2-tabs-*.png`) with 42 automated checks
in a real browser (`var/reports/wp2-browser.json`), no console error and no
failed request while signed in. A sweep of 23 routes at four widths found no
sideways page scrolling. Evidence, including what was not tested (physical
devices, screen readers, other browsers), is in
[`../VERIFICATION_REPORT.md`](../VERIFICATION_REPORT.md) §26 and §29; the token
and component rules are in [`../DESIGN_SYSTEM.md`](../DESIGN_SYSTEM.md).

## 1.13 Tabs, breadcrumbs and favourites

**Tabs.** Every screen you open becomes a tab under the application bar, so you can move between two or three screens without losing your place. **Home** is pinned first and cannot be closed. Opening a screen that is already open selects its existing tab instead of making a copy. At most **20 tabs** are kept at once; opening a 21st screen closes the oldest one after Home, and that screen goes to the top of **Reopen closed tab**, so it is one click away if you need it again.

| To do this | Use |
|---|---|
| Open a screen | Select it in the rail, in the palette, or follow a link. A new tab appears and becomes active |
| Switch screens | Select the tab, or press **←** / **→** while a tab has keyboard focus |
| Go to the first or last tab | The **Home** / **End** keys while a tab has keyboard focus |
| Close the current tab | Its **×**, or **Delete** with the tab focused. Home cannot be closed |
| Close every other tab | **⋯** → **Close other tabs**, or **Close all except Home** |
| Reopen the last tab you closed | **⋯** → **Reopen closed tab** |
| Find a tab that does not fit | The **⋯** button lists every open screen; the strip never scrolls a tab out of reach on a desktop |

**Refresh and addresses.** The address bar always shows the screen you are on (`#/products`, `#/accounts/gst-out?...`), so refreshing the page, using Back and Forward, or sending someone a link all work. Your open tabs are remembered for your next visit in the same browser session; a tab whose permission or module switch has since been removed is quietly dropped rather than restored to a screen the server would refuse.

**Unsaved work.** If you are halfway through a form in the detail panel and close the tab (or close the other tabs) that contains it, the application asks before discarding the entry. Select **Cancel** to stay on the form.

**Breadcrumbs.** Above each title a short trail shows where the screen sits, using the same names as the rail — for example **Finance and insight › Books › Accounting & Finance**. Select an earlier part of the trail to return to that screen. The trail never offers a screen your role may not open.

**Favourites and recently opened.** Select the **☆** beside the title to pin the screen. Favourites appear in their own group at the top of the rail, in the order you pinned them; select the star again (**★**) to remove one. The **Recently opened** group lists the screens you used most recently. These two lists are kept in this browser for your username only — they are not shared with other people or other computers. This is a documented temporary limitation until the navigation registry (WP-4) stores them on the server; see [`../NAVIGATION_AND_TAB_DESIGN.md`](../NAVIGATION_AND_TAB_DESIGN.md) §10.5.
