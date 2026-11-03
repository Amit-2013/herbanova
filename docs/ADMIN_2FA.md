# Administrator two-factor authentication (Google Authenticator / TOTP)

Date: 3 November 2026
Branch: `feature/gap-closure`
Status: backend and tests verified; enrollment walked in a browser. Migration
`0029_totp` is applied to the disposable test database and to the development
database (applied 3 November 2026 after a verified backup, with the owner's
explicit `apply 0029_totp`); it is **not** applied to production.

This document describes the second factor for **Administrator** and
**Super Administrator** accounts. Every other role keeps the existing
password-only sign-in and nothing on their screens changes.

## 1. What is enforced, and where

The code screen is not the control. The server is:

| Step | Endpoint | What the server decides |
|---|---|---|
| Password | `POST /api/auth/login` | For an Administrator the password alone **never** sets the `session` cookie. It sets a short-lived `totp_challenge` cookie and answers `otp_required` (enrolled) or `setup_required` (not enrolled). |
| Enrollment start | `GET /api/auth/2fa/setup` | Creates a new secret and returns the `otpauth://` URI. Refused once enrollment is confirmed. |
| Enrollment finish | `POST /api/auth/2fa/confirm` | Accepts a code from the app, enables the second factor, issues 10 recovery codes and only then sets the session cookie. |
| Sign-in second step | `POST /api/auth/2fa/verify` | Accepts an authenticator code or a recovery code, then sets the session cookie. |
| Every later request | `current_user` | A session token without the `otp` claim is refused with **401 Two-factor verification required** for an account whose `totp_enabled` is true. |

Role check: `app/services/totp.py:requires_totp` returns true only for the role
names `admin` and `super_admin` (`TOTP_ROLES`). It reads the role from the
database (`role_rel.name`), not from anything the browser sends.

## 2. The code

- Standard **RFC 6238** TOTP: HMAC-SHA1, **6 digits**, **30-second** step, a
  one-step window either side so a slightly slow phone still works.
- No SMS, no e-mail and no network on the phone after enrollment.
- The provisioning URI carries `issuer=Herbanova`, the account name, `SHA1`,
  6 digits and a 30-second period, so Google Authenticator, Microsoft
  Authenticator, Authy and similar apps all work.
- The maths is checked against the published RFC 6238 test vectors
  (`tests/test_totp.py::test_codes_match_the_rfc_6238_vectors`).

## 3. Secret at rest and replay

- The shared secret is sealed with **Fernet**, using a key derived from
  `APP_SECRET` (`sha256("herbanova:totp:" + APP_SECRET)`), before it is stored
  in `users.totp_secret`. A copy of the database alone cannot produce codes.
- **Changing `APP_SECRET` makes stored secrets unreadable.** Every enrolled
  Administrator must then be re-enrolled. Keep `APP_SECRET` stable and backed
  up like any other key.
- `users.totp_last_counter` records the accepted 30-second step. A code from
  that step, or earlier, is refused, so a seen code cannot be replayed inside
  its window.
- The API never returns the secret after setup and never returns a stored
  secret to any account. `GET /api/auth/2fa/status` returns only `required`,
  `enabled`, `confirmed_at` and `recovery_codes_left`.

## 4. Recovery codes

- Enrollment returns **10** codes once, in the response to
  `POST /api/auth/2fa/confirm`. They are shown to the person and are **not
  retrievable later**.
- Only **argon2 hashes** are stored (`users.totp_recovery_hashes`). Each code is
  **single-use**: a match removes its hash.
- A recovery code signs in once through `POST /api/auth/2fa/verify`
  (`recovery_code` instead of `code`); the audit row records
  `{"method": "recovery"}`.
- If a code is lost, use another one. There is no regeneration screen yet; see
  §7.

## 5. Guessing, locking and the challenge ticket

- **Five** wrong codes in a row (authenticator or recovery) pause code entry
  for **15 minutes** (`auth.totp_lockout`). The password lockout is separate
  and unchanged.
- The `totp_challenge` cookie is a JWT valid for **10 minutes**, `HttpOnly`,
  `SameSite=Lax`, `Secure` outside `local`, scoped to `path=/api/auth`. It is
  **not a session**: it opens only the two factor endpoints and cannot read
  any data.
- The challenge carries `purpose=totp`, the user id, the `token_version` and
  the mode (`setup` or `verify`). A setup ticket cannot be used to verify an
  enrolled account, and a bumped `token_version` invalidates it.
- Confirming enrollment bumps `token_version`, so a session opened before
  enrollment ends.
- The session JWT records `otp: true` only when issued after an accepted code.
  Even if a bug issued a password-only session, `current_user` refuses it.

## 6. Schema and migration

Migration `0029_totp` (additive; no existing row changes) adds to `users`:

| Column | Purpose |
|---|---|
| `totp_secret` | The sealed shared secret (`String(512)`, nullable) |
| `totp_enabled` | The switch the server checks (`Boolean`, default false) |
| `totp_confirmed_at` | When enrollment was confirmed |
| `totp_last_counter` | Last accepted 30-second step (replay guard) |
| `totp_failed_attempts` | Wrong codes since the last success |
| `totp_locked_until` | End of a code-entry pause |
| `totp_recovery_hashes` | Argon2 hashes of single-use recovery codes (`JSON`) |

The upgrade also bumps `token_version` for the Administrator roles, so sessions
issued before the release must sign in again and pass the second factor. The
downgrade drops the seven columns; it deliberately does **not** revive the
sessions it ended.

**Deployment status.** `0029_totp` is at the head of the test database because
the suite runs `alembic upgrade head` there, and it was applied to the
development database (`herbanova_bcs_dev`) on 3 November 2026 after the owner's
explicit `apply 0029_totp` and a verified `pg_dump`. The apply was checked
straight after: `alembic current` read `0029_totp (head)`, the seven columns
existed with the expected nullability and defaults, the 84 tables and 6 user
rows were unchanged, `admin` and `admin2` moved from `token_version` 3 to 4
(their pre-release sessions end), and a full `User` select — which failed with
`UndefinedColumn` before the apply — succeeded. Backup:
`var/backups/pre-0029-totp-20261103T172245.dump` (392 KB, 84 table entries,
SHA-256 `0d791f2795eb84db54a4c6a504e2b37ff9377732ddae84f6bc67dd47d5ee99b4`).
Both Administrators now enrol at their next sign-in; production remains on
`0028_advances` until the same approval is given there.

## 7. Operating it

**First sign-in after the release (Administrator).**

1. Username and password as before.
2. A **Set up two-factor** screen appears. A QR code and the setup key are
   shown once.
3. Scan the QR code (or type the key) into Google Authenticator.
4. Type the current 6-digit code and confirm.
5. Write down the 10 recovery codes shown; they are not shown again.
6. The application opens. Later sign-ins ask for the 6-digit code after the
   password.

**Lost phone.** Use a recovery code. If the recovery codes are also lost, an
operator must clear the second factor for that account in the database
(`totp_enabled = false`, `totp_secret = NULL`, `totp_recovery_hashes = NULL`,
`totp_last_counter = NULL`), then the account is sent through enrollment at the
next sign-in. This is a **controlled operator action**, not a screen: resetting
a password does **not** clear the second factor, so a stolen password alone
cannot bypass it.

**Audit rows.** `auth.password_ok` (mode), `auth.totp_enabled`,
`auth.totp_login` (method `totp` or `recovery`) and `auth.totp_lockout`. No
secret or code is written to the audit trail or the log.

## 8. What is not built

| Item | Status |
|---|---|
| Administrator screen to view or reset another account's second factor | Not built. Use the operator procedure in §7. |
| Regenerate recovery codes from inside the application | Not built. |
| Push/WebAuthn or hardware keys | Not built; TOTP only. |
| Second factor for any non-Administrator role | Deliberately not enforced. |
| A check that the phone's clock is correct | Not possible server-side; the ±1 step window absorbs small drift. |

## 9. Evidence

- `tests/test_totp.py` (8 tests): RFC 6238 vectors, replay refusal, a
  non-Administrator still signing in with the password alone, an Administrator
  getting no session before enrollment, enrollment then a code on the next
  sign-in, a recovery code working once, a session without the `otp` claim
  being refused, and five wrong codes locking the second step.
- Browser walk 3 November 2026 (disposable test database): the enrollment
  screen appeared after the password, showed the key and QR, and refused to
  open the shell without a code. The pre-enrollment session was not created.
- **Not verified in the browser:** typing the verify code after enrollment.
  Reading a stored secret or generated code back out of the database is
  blocked by the environment's credential-handling rules, so that one step was
  covered by the automated test instead. Live e-mail, SMS and physical phones
  are not involved by design.

## 10. Related reading

- [user-manual/00-quick-start.md](user-manual/00-quick-start.md) §1.2–1.3 and
  §1.7 — what the person signing in sees.
- [FRONTEND_BACKEND_FIELD_MAPPING.md](FRONTEND_BACKEND_FIELD_MAPPING.md) §1 —
  endpoint and field mapping.
- [FEATURE_INVENTORY.md](FEATURE_INVENTORY.md) F-135.
- [DECISIONS.md](DECISIONS.md) D-46.
