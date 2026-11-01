# 1. Getting Started

**Audience:** everyone with a login.
**Chapter status:** written and verified against source on 31 October 2026.
**What you need:** the application address from your administrator, a username, and your password.

## 1.1 Opening the application

Enter the address in a browser. The server root redirects to **`/ui/`** (`app/main.py:71-81`), which is the single-page application. The sign-in screen asks for a **Username** and a **Password**. Usernames are matched case-insensitively; the password is case-sensitive.

**VERIFIED (code):** `POST /api/auth/login` normalises the username to lower case before lookup (`app/api/auth.py:55-59`) and sets an HttpOnly cookie called `session` (`auth.py:72-73`). The browser never stores the password or a token in JavaScript.

## 1.2 Signing in

1. Type your username. Spaces before and after are ignored.
2. Type your password. It is not displayed.
3. Select **Sign in**.

On success the application closes the sign-in screen, loads your identity and permission list from the server, and opens the main shell. The top-right corner shows your username, your role and a **Sign out** button.

**VERIFIED:** the browser re-reads `/api/auth/me` after login instead of trusting a copy of the permissions kept in the page (`static/js/app.js:112-123`). What you can see is therefore decided by the server, not by the screen.

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

The sidebar has 19 entries. Most are filtered by your permissions when you sign in; the server refuses anything you are not permitted to use, so a visible page can still show only the records you may read.

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
| Suppliers | `supplier:read` | Supplier master and bank-change requests |
| Approvals | `approval:read` | Credit-limit, sales-order, post-billing and HR requests |
| Accounting & Finance | `accounts:read` | Outstanding, party ledgers, GST register, trial balance |
| Reports | Per-report permission; `report:export` to download | The single reports page |
| Geography | `sales:read` | Sales, returns and GST by buyer state |
| HR Management | `hr:read` or `hr:attendance_self` | Employees, attendance, leave, OD, payroll |
| **Roles & Permissions** | `user:manage` (Administrator role for module switches) | Role tree editor, permission catalogue, access-control rules and module On/Off switches |
| Settings & Administration | `user:manage`, `tax:read`, `audit:read` or `hr:read` | Company profile, tax, logins/employees, email and audit |
| Scheduled reports | `email:manage` | Report packs, recipients and the delivery log |

**VERIFIED (code):** menu visibility at `static/js/app.js:86-110`; reports permissions at `app/api/reports.py:83-85`; the full permission-to-role table is in [`../permissions-matrix.md`](../permissions-matrix.md).

An **employee** without `hr:read` sees the HR home page with their own attendance only; the directory, leave/OD registers and payroll buttons are hidden and refused by the server (`static/js/app.js:602-610`).

**Branches, offices and attendance policy.** Every employee can be placed in a **Branch** and an **Office / work location** in the New/Edit employee form; only the offices of the chosen branch are offered, and choosing an office fills its branch. HR Management shows the office under **Location** in the People table, plus a **No attendance** chip when the policy exempts that person. A role with `hr:write` can open **Branches, offices & attendance policy** to create branches and offices, set a geofence, and write attendance rules. The branch and office selectors above the People list, the monthly register and the HR reports narrow every figure to that branch or office, and a printed sheet repeats the filter it used. An employee who is not required to mark attendance is refused a check-in by the server, and their exempt days appear as **not required**, never as absences.

## 1.6 Messages you may see

| Message | Meaning | What to do |
|---|---|---|
| **Username or password is incorrect.** | The username does not exist, is inactive, or the password is wrong. | Re-type both. Five failures lock the account. |
| **Account temporarily locked after too many failed attempts…** | A 15-minute lock is active. | Wait, or ask an administrator to reset the password. |
| **Too many requests. Please wait a moment and try again.** | More than 20 sign-in attempts per minute from your address. | Wait at least a minute. |
| **You must change your password before using the application** | A temporary password is in force, or the browser identity is out of date. | The change screen should appear at sign-in (§1.3); if it does not, sign out and in again. |
| **Not authenticated** / **Session expired** | The cookie is missing, expired or revoked. | Sign in again. |
| **Permission denied** | Your role does not hold the required permission, or the screen allowed an action the server refuses. | Ask an administrator; do not retry repeatedly. |
| **Only an Administrator can do this** | The action needs the Administrator role itself, not just a permission. | Ask the Administrator. |
| A red message inside a form | Validation failed; the text names the field or rule. | Correct the field and submit again. |

**VERIFIED (code):** the server messages are the literals in `app/core/rbac.py`, `app/api/auth.py` and `app/core/security.py`; the browser shows the server's detail text in the form (`static/js/app.js:118`).

## 1.7 If you cannot sign in

1. Check that you are using the address ending in `/ui/`.
2. Check the username spelling; case does not matter.
3. If the message is "locked", wait 15 minutes.
4. If it still fails, ask an administrator to reset the password. The administrator can see whether the account is **Temporary** or **Locked** in the Logins screen and can end every open session by resetting.
5. If the page loads but every panel is empty and the address bar is correct, the session may have expired; sign in again. If it persists, report your username, the time and the exact message — never your password.

## 1.8 Roles and permissions (administrators)

Open **Roles & Permissions** in the sidebar. The screen has three parts:

| Part | What an administrator does |
|---|---|
| Roles | Review each role's permission and user count; **Edit permissions** opens the tree editor; **New role** creates a custom role |
| Feature availability | Switch a module on or off for everyone. A switched-off module keeps its stored role assignments but grants nobody access until it is switched back on |
| Access control | Read the whole catalogue: each module gate, each child permission with the parent it needs, and the rights reserved for the Administrator |

The tree editor follows one rule: a **parent** permission is the module gate. Ticking it makes its children selectable but grants none of them. Tick each child you want; unticking the parent clears its children. A child without its parent is refused by the server. Four rights (`approval:credit_limit`, `invoice:edit_post_billing`, `email:manage`, `db:reset`) stay locked to the Administrator and cannot be given to another role.

Module switches are Administrator-only even if a custom role holds `user:manage`. User accounts and temporary passwords are managed separately under **Settings & Administration → Logins and employees**. Every role change and every switch is written to the audit trail.

**Next chapter (planned):** 2. Finding your way — navigation, roles and permissions in detail.
