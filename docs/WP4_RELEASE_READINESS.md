# WP-4 Release Readiness Audit

| Field | Value |
| --- | --- |
| Audit date | 2026-11-04 (Asia/Kolkata) |
| Scope | WP-2, WP-3 and WP-4 working tree, migration chain 0028 → 0031, development database, checkpoints |
| Branch | `feature/gap-closure` |
| HEAD | `77f5a96e4182af7a67eea95405d4c03fc66820e6` |
| Parent | `eaf38d2` (accounting gap closure, Admin 2FA, split servers) |
| Mode | Read-only. No commit, push, migration, database reset or production deployment was performed. |
| Working tree | 26 modified + 26 untracked = 52 entries at audit start; 53 including this report; 0 staged; 0 deleted; 0 renames |
| Report status | Submitted for approval. No finding was fixed during the audit. |

---

## 1. Verdict

| Decision | Verdict | Condition |
| --- | --- | --- |
| WP-4 development activation (4a–4d) | **Complete** | Verified against dev at `0031_navigation_registry` |
| Git commit to `feature/gap-closure` | **CONDITIONAL GO** | Take a checkpoint of the exact final tree (C-7) and decide the documentation/script corrections (C-1 – C-5) before or immediately after the commit |
| Production promotion | **NO-GO** | Production is reported at `0028_advances`; HEAD needs 0029 → 0030 → 0031 first, and a production clone rehearsal plus a fresh verified backup are missing |
| Blocking code defects | **None found** | 542 Python tests and 20 Node tests pass; no secret, credential or generated artefact in the 52 entries |

The working tree is releasable as source. Production is not ready, because the application at HEAD expects schema that production does not have and because no production backup or clone rehearsal exists for this release.

---

## 2. Scope, method and limits

### What was examined

- Every modified and untracked file in the working tree, including a full read of the new navigation API, models, catalogue, registry, store, migration, frontend controller and model.
- The full RBAC and feature-switch path that decides which screens a user may see and open.
- Migrations `0028_advances`, `0029_totp`, `0030_sign_in_content` and `0031_navigation_registry`, upgrade and downgrade.
- The development database (read-only SQL) and both source/database checkpoints.
- The isolated Python suite, the Node suite and the Alembic head/current state.

### What was not examined

- **Production was not connected to.** Its revision `0028_advances` is the owner-reported state recorded in project notes, not a value this audit measured. Any production statement in this report is conditional on that report being correct.
- No new browser walk was performed during this audit. Screen functionality rests on the Batch 4d browser regression (`var/reports/junit-wp4d.xml` and the 4d walk evidence) and on the automated suites. A fresh walk on a production clone remains a promotion prerequisite.
- The 13-step migration rehearsal (`scripts/verify_navigation_migration.py --run`) was not re-executed: it creates, upgrades and drops a database, which is outside this read-only mandate. The Batch 4a rehearsal evidence (`var/reports/wp4a-migration-rehearsal.json`) is cited instead.
- The test runner drops and recreates only `herbanova_bcs_test`. `herbanova_bcs_dev` and production were never written to. This is disclosed because it is the one database object the verification touched.

---

## 3. Working-tree inventory

`git diff --stat` totals **2 972 insertions and 337 deletions** across 26 modified files. The 26 untracked files add **9 543 lines**. No file is deleted or renamed, and nothing is staged.

This report (`docs/WP4_RELEASE_READINESS.md`) is itself a new untracked file created by the audit and is not one of the 26 entries below; include it when committing, for 53 files in total.

### 3.1 Modified files (26)

| File | + | − | Work package |
| --- | ---: | ---: | --- |
| `app/api/approvals.py` | 54 | 35 | WP-3 — SQL-side HR visibility, detail route, `decided` filter |
| `app/api/distributors.py` | 9 | 1 | WP-3 — standardised list |
| `app/api/invoices.py` | 8 | 2 | WP-3 — standardised list |
| `app/api/products.py` | 8 | 4 | WP-3 — standardised list |
| `app/api/purchase_orders.py` | 8 | 1 | WP-3 — standardised list |
| `app/api/sales_orders.py` | 8 | 2 | WP-3 — standardised list |
| `app/api/suppliers.py` | 3 | 0 | WP-3 — standardised list |
| `app/core/pagination.py` | 10 | 2 | WP-3 — `sort_clause`, null placement |
| `app/main.py` | 2 | 1 | WP-4 — register navigation router |
| `app/models/__init__.py` | 2 | 2 | WP-4 — export navigation models |
| `app/services/db_reset.py` | 1 | 0 | WP-4 — `nav_nodes`, `feature_registry` in `KEPT_TABLES` |
| `app/services/feature_store.py` | 36 | 9 | WP-4 — dependency closure in `available_keys`, `disabled_permissions`, `is_enabled` |
| `docs/DESIGN_SYSTEM.md` | 126 | 22 | WP-2/3 — design tokens and list standard |
| `docs/FEATURE_INVENTORY.md` | 4 | 2 | WP-2/4 |
| `docs/FRONTEND_BACKEND_FIELD_MAPPING.md` | 4 | 0 | WP-4 |
| `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md` | 2 | 1 | WP-4 |
| `docs/VERIFICATION_REPORT.md` | 1 274 | 0 | WP-2/3/4 — appended evidence |
| `docs/user-manual/00-quick-start.md` | 39 | 21 | WP-2/4 |
| `docs/user-manual/07-products.md` | 19 | 3 | WP-3 |
| `docs/user-manual/11-sales-orders.md` | 22 | 9 | WP-3 |
| `docs/user-manual/README.md` | 8 | 6 | WP-2/3/4 |
| `static/css/styles.css` | 99 | 6 | WP-2/3 — tabs, rail, lists |
| `static/index.html` | 55 | 40 | WP-2/4 — shell, rail, tab strip |
| `static/js/app.js` | 1 138 | 162 | WP-2/3/4 — nav controller, workspace UI, lists |
| `tests/test_products.py` | 23 | 0 | WP-3 — list standard |
| `tests/test_profit_loss.py` | 10 | 6 | WP-2/WP-4 — assertions moved to `workspace.js` and the rail |

### 3.2 Untracked files (26)

| File | Lines | Purpose |
| --- | ---: | --- |
| `alembic/versions/0031_navigation_registry.py` | 1 396 | Migration: two registry tables, 78 seeded rows |
| `app/api/navigation.py` | 173 | `GET /api/navigation`, `GET /api/admin/navigation` |
| `app/models/navigation.py` | 119 | `NavNode`, `FeatureRegistry` |
| `app/services/navigation_catalog.py` | 250 | Single source of truth: 5/14/20/25/14 catalogue |
| `app/services/navigation_registry.py` | 364 | Visibility, menu rule, ETag, validation |
| `app/services/navigation_store.py` | 101 | Registry reads and feature closure |
| `docs/CHANGELOG.md` | 390 | Release history |
| `docs/FEATURE_REGISTRY_DESIGN.md` | 738 | Registry design |
| `docs/IMPLEMENTATION_ROADMAP.md` | 512 | WP roadmap and gap register |
| `docs/NAVIGATION_AND_TAB_DESIGN.md` | 546 | Navigation and tab design |
| `docs/PROJECT_ARCHITECTURE.md` | 321 | Architecture reference |
| `docs/WP4_APPROVAL_READINESS.md` | 798 | Batch 4a approval record (historical) |
| `pytest.ini` | 4 | Restricts collection to `tests/`, excluding probe servers under `var/` |
| `scripts/generate_navigation_seed.py` | 85 | Seed block generator and `--check` |
| `scripts/navigation_parity_report.py` | 338 | Machine-readable catalogue parity report |
| `scripts/verify_navigation_migration.py` | 716 | Guarded 13-step scratch-database rehearsal |
| `static/js/workspace.js` | 457 | Shared workspace model (UMD) |
| `tests/js/emit_nav_manifest.cjs` | 52 | Browser-side manifest emitter |
| `tests/js/nav_parity.cjs` | 72 | Built-in vs API nav parity harness |
| `tests/js/workspace.test.cjs` | 302 | Workspace model tests |
| `tests/test_feature_dependencies.py` | 153 | Feature closure and fail-closed behaviour |
| `tests/test_list_standard.py` | 354 | Eight standardised lists |
| `tests/test_navigation_api.py` | 423 | Endpoint, ETag, RBAC and fallback |
| `tests/test_navigation_parity.py` | 383 | Catalogue/registry/API parity |
| `tests/test_navigation_registry.py` | 474 | Validation, visibility, menu and ETag |
| `tests/test_workspace_model.py` | 22 | Node suite entry from pytest |

### 3.3 Hygiene classification

| Category | Result |
| --- | --- |
| Secrets or credentials in the 52 entries | **None found.** Scanned modified and untracked content for API keys, private keys, inline passwords and `postgres://user:pass@` URLs. |
| Generated reports or probe artefacts | **None in the tree.** All reports, dumps, probe servers and screenshots live under `var/`, which is ignored. |
| `.env` / tokens | `.env` is ignored. The baseline checkpoint also contains `config/.env` inside its hash manifest — keep `var/` out of version control and access-controlled (SEC-08). |
| Obsolete scripts | None. All three new scripts serve the current design. `docs/WP4_APPROVAL_READINESS.md` contains superseded statements (SEC-05), but is still useful as Batch 4a history. |
| Unintended changes | None identified. Every modified file maps to WP-2, WP-3 or WP-4. `docs/VERIFICATION_REPORT.md` is a 1 274-line append; confirm the append was intended when staging. |
| Merge artefacts or debug leftovers | None found. No `print()`, `breakpoint()`, TODO scratch blocks or commented-out endpoints in the new modules. |
| File-mode changes | None. |

---

## 4. Security findings

### 4.1 Findings

| ID | Severity | Area | Finding | Impact |
| --- | --- | --- | --- | --- |
| SEC-01 | **High** (deployment) | Release ordering | HEAD application code expects `users.totp_*` (0029), sign-in tables (0030) and both registry tables (0031). Production is reported at `0028_advances`. The 0029 dependency predates WP-4 (2FA is in the current release baseline); WP-4 adds 0031 on top. | Deploying the app before the migrations leaves login/2FA and the navigation endpoint broken, and `0031` absent returns 503 for `/api/navigation`. Migrations must run first. |
| SEC-02 | **Medium** | Build tooling | `scripts/generate_navigation_seed.py` docstring still says `--write` edits an "inert `.py.draft`", but the script now targets the active `0031_navigation_registry.py` when it exists (`scripts/generate_navigation_seed.py:29-31, 11-12`). | A future `--write` against a stale catalogue silently rewrites an already-applied migration. Alembic does not checksum applied revisions, so the drift would go undetected. |
| SEC-03 | **Low** (latent) | RBAC | `visible_keys` checks a node's own `permission_any` but not an ancestor container's; `validate_catalog` does not reject permissions on containers. All 39 current containers hold an empty permission array, so there is no present effect. | When containers gain permission rules in WP-5, a screen could appear under a container the user cannot access. Menu visibility only; route guards remain authoritative. |
| SEC-04 | **Low** | Availability / UX | `validate_catalog` enforces exact counts (5/14/20/25/14). Any unaccompanied catalogue or seed change returns 503 from `/api/navigation`. | The frontend falls back to the built-in menu, so the app stays usable, but the failure is invisible to the user and to monitoring beyond the 503. Changes must update catalogue, seed and counts together. |
| SEC-05 | **Low** | Documentation integrity | `docs/WP4_APPROVAL_READINESS.md` still states "NO-GO for 4b–4d" (line 13), "`/api/navigation` remains unimplemented (404)" (line 515) and records a 404 probe (line 751). | An operator reading it during a promotion could conclude the feature is absent or blocked. |
| SEC-06 | **Low** | Functional drift | The API returns screen `label` values, but the rail renders the local `TITLES` map (`static/js/app.js`, `navRow`). | Server-side labels are inert. Editing a label in the registry would not change the UI, which will matter once WP-5 adds registry editing. |
| SEC-07 | **Low** | Verification integrity | The pytest harness uses one fixed test database, `herbanova_bcs_test`, recreated per run. Two suites started at the same time corrupt each other. This was observed: a concurrent attempt produced 22 failed / 2 errors, and an isolated rerun passed 542/542. | Test results are only trustworthy when exactly one suite runs at a time. CI must not shard or overlap runs without separate databases. |
| SEC-08 | Info | Backup custody | `var/backups/baseline-20261103T175350/config/.env` exists inside the checkpoint, and `SHA256SUMS` covers it. | `var/` is ignored by Git, but the backup directory holds live secrets and needs restricted access and encrypted storage. |
| SEC-09 | Info | Line endings | Nine working copies are CRLF; `.gitattributes` normalises Python/JS/CSS/HTML/Markdown to LF on commit. | Commit output will print CRLF warnings. Stored blobs will be LF; no behavioural effect. |
| SEC-10 | Info | ETag inputs | `navigation_etag` is called with constant `favourites=[]` and `recent=[]` (`app/api/navigation.py`). | Forward-compatible placeholders today; they add no discrimination until server-side favourites/recent exist. |

### 4.2 Controls confirmed

- **Authentication:** `/api/navigation` uses `require_login`; `/api/admin/navigation` uses `require_admin("user:manage")`, which requires both the permission and an admin role.
- **Authorisation is server-side:** navigation visibility is presentation only. Route access is enforced by each endpoint's dependency; feature switches remove permissions from the effective role (`disabled_permissions`), so hiding a screen and refusing its API stay consistent.
- **Fail-closed features:** `feature_available` resolves status, switch and dependencies recursively and treats a cycle as unavailable (`app/services/navigation_store.py`).
- **Admin-only screen:** `scheduled` is removed for non-admins by `narrow_admin_only` (`app/services/navigation_registry.py:302`), and the `admin` flag is part of the ETag payload.
- **Cache isolation:** the navigation ETag includes user id, sorted permissions, enabled features and the admin flag; responses are `private, no-cache` with `Vary: Cookie`; the admin endpoint is `no-store`. A 304 is returned only on an exact match, after `require_login` has run.
- **Input handling:** the frontend drops unknown and duplicate views from the server payload (`navFromApi`), so server data cannot widen the route gate. Error text is HTML-escaped before insertion.
- **Injection:** all database access uses SQLAlchemy constructs; no string-built SQL was found in the new modules or the migration.
- **State changes:** both navigation endpoints are read-only `GET`s; no CSRF surface is added.

---

## 5. Functional preservation

| Area | Evidence | Result |
| --- | --- | --- |
| WP-2 workspace | Node suite: 20/20 pass. Tests cover tab cap (20 open + 10 closed), recency ordering, breadcrumbs, palette search, unsaved-change guards and persistence. | Preserved |
| WP-3 lists | `tests/test_list_standard.py` covers Products plus the seven batch-2 lists: suppliers, distributors, sales orders, purchase orders, invoices, approvals, leads — **eight standardised lists**. Server paging, totals, sorting (Products) and export agree. | Preserved |
| WP-4 hierarchy | Catalogue counts 5 modules / 14 categories / 20 groups / 25 screens, plus one alias (`distributors` → `customers`) stored in `nav_nodes.aliases`; dev DB matches (64 nodes = 25 screens + 39 containers, 25 unique views). | Preserved |
| Accounting | `ACCOUNTS_SECTION_COUNT = 19` in the catalogue; the section bar renders all 19 sub-sections. | Preserved |
| Feature registry | 14 registered features; 13 switches in `feature_flags`; closure logic tested in `tests/test_feature_dependencies.py`. | Preserved |
| Default navigation | `NAV_API_ENABLED = true` (`static/js/app.js:816`); API payload is the default, built-in menu is the fallback; `?nav=builtin` and `?nav=api` remain available. | Active as designed |
| 25 screens | Every screen is routable from the rail; parity tests compare built-in and API-derived sets per role and feature combination. | Preserved |

The eight list screens, the 19 accounting sub-sections and the 25 navigation screens are accounted for by the catalogue, the dev registry rows and the automated suites. The last full browser regression was Batch 4d; this audit did not repeat it.

---

## 6. Navigation security, RBAC and session isolation

### Backend path

1. `require_login` authenticates the session and enforces a pending forced password change.
2. `role_permissions` returns the role's effective permissions, minus permissions belonging to disabled features.
3. `feature_store.available_keys` returns the enabled-feature closure: registry status `active`, switch on, dependencies satisfied; unregistered legacy switches are merged in.
4. `visible_keys` keeps a screen when its ancestors are active, its own `feature_key` is available and its `permission_any` intersects the user's permissions.
5. `narrow_admin_only` removes `scheduled` for non-admins.
6. `navigation_etag` fingerprints the registry plus the user's identity, permissions, features and admin flag.

### Session isolation

- Two users with the same permissions still receive different ETags because `user_id` is in the payload.
- A stale cached response cannot be reused across a permission or feature change: the tag changes with both.
- `Vary: Cookie` keeps shared caches from serving one user's menu to another.
- The admin endpoint returns validation errors instead of 503 and is never cached.

### Frontend guards

- The rail, palette, tabs, breadcrumbs and route gate all read the same tree.
- `wsViewOk` requires both the workspace rule and the server gate; clicking an unknown or removed view cannot open it.
- A username guard and a request sequence number discard responses that arrive after a user switch or a newer request.
- Load failure leaves the built-in menu in place and offers a retry, so a registry outage does not lock users out of the app.

No cross-user leakage or privilege escalation path was found.

---

## 7. Migration chain 0028 → 0031

### Structure

```
0027? → 0028_advances → 0029_totp → 0030_sign_in_content → 0031_navigation_registry (head)
```

`alembic heads` reports a single head. `alembic current` on dev reports `0031_navigation_registry (head)`. No branch labels, no merge revisions, no duplicate revision ids.

### Per-revision review

| Revision | Upgrade | Downgrade | Assessment |
| --- | --- | --- | --- |
| `0028_advances` | Creates `payment_allocations`, widens `ck_ledger_account_role`, seeds control heads 1110/2110 | Refuses if the seeded heads are referenced by opening balances or voucher lines; otherwise deletes heads, restores the old check, drops the table | Guarded, ordered correctly |
| `0029_totp` | Adds seven `users` columns; NOT NULL columns carry server defaults; bumps `token_version` for admin and super-admin roles | Drops the columns; **intentionally does not restore `token_version`** | Additive; downgrade cannot revive revoked sessions by design. Enrolled admins lose 2FA if rolled back. |
| `0030_sign_in_content` | Creates four sign-in tables with indexes; seeds two unpublished legal documents | Drops indexes and tables | Additive; downgrade discards admin-entered sign-in content |
| `0031_navigation_registry` | Creates `nav_nodes` and `feature_registry`, constraints and indexes, seeds 64 + 14 rows, advances the `nav_nodes` sequence | Drops `feature_registry`, its indexes and `nav_nodes` | Additive; no FK to `feature_flags` (deliberate R-01 separation). Re-upgrade reseeds. |

### Safety properties verified

- All four revisions are additive to existing business tables; no column is dropped or narrowed on upgrade.
- `0031` seeds explicit ids and then calls `setval(pg_get_serial_sequence(...), MAX(id))`, so later inserts cannot collide.
- `nav_nodes` self-reference uses `ON DELETE RESTRICT`; the Home invariant is enforced by a partial unique index and check constraints.
- No migration imports application code, so the chain keeps working as the catalogue evolves.
- No table in the new chain is dropped by a later revision.
- `KEPT_TABLES` in `app/services/db_reset.py` now protects both registry tables from the guarded reset.

### Rehearsal status

The 13-step scratch-database rehearsal (create → 0028 → 0029 → 0030 → 0031 → verify rows/indexes/constraints → 0030 downgrade → verify → re-upgrade → 78 rows → feature-switch behaviours → drop) was executed during Batch 4a, with evidence in `var/reports/wp4a-migration-rehearsal.json`. It was **not** re-executed here, because it creates and drops a database. For production, the same rehearsal must be repeated against a clone of the production database, not just a scratch database (see §12).

---

## 8. Database state and drift

### Development (measured, read-only)

| Fact | Value |
| --- | --- |
| Alembic revision | `0031_navigation_registry` |
| Public tables | 90 |
| `nav_nodes` | 64 rows (25 screens with 25 unique views, 39 containers); one screen carries the `distributors` → `customers` alias |
| `feature_registry` | 14 rows |
| `feature_flags` | 13 rows |
| Container permission arrays | Empty on all 39 containers (supports SEC-03 being latent) |

### Production (reported, not measured)

Recorded at `0028_advances`. This audit did not open a production connection; the value must be confirmed with `alembic current` before a promotion plan is written.

### Drift since the 2026-11-03 baseline

- Business rows created on 3 November between 18:36 and 18:44 — invoice #4 and stock movements #19–21 — predate WP-4 work and are development data, not WP-4 writes.
- Audit rows since the baseline were 41 at query time, all authentication events (`auth.password_ok`, `auth.totp_login`) for user 1, latest 2026-11-04 15:21:36 +05:30.
- No WP-4 code path writes business rows. The registry migration writes only the two registry tables.

### Schema/registry drift

- Catalogue, migration seed and dev registry agree at 5/14/20/25/14 and 64/14.
- No drift was found between `feature_registry` and the catalogue. The 13 `feature_flags` rows are independent switches by design (R-01); `foc` is the one registered feature without a stored flag row, and `feature_available` treats a missing row as on (`navigation_store.py:84-85`), so FOC remains available until a row is created.

---

## 9. Test and verification evidence

| Check | Command | Result |
| --- | --- | --- |
| Python suite (isolated) | `python -m pytest -q --junitxml=var/reports/junit-readiness.xml` | **542 passed, 0 failed, 0 errors, 0 skipped** in 231.45 s |
| JUnit totals | parsed `var/reports/junit-readiness.xml` | tests 542, failures 0, errors 0, skipped 0 |
| Node workspace suite | `node --test tests/js/*.test.cjs` | **20 passed, 0 failed**, 81.6 ms |
| Alembic head | `python -m alembic heads` | `0031_navigation_registry (head)` — single |
| Alembic current (dev) | `python -m alembic current` | `0031_navigation_registry (head)` |
| Registry rows (dev) | read-only SQL | 64 / 14 / 13; 90 tables |

### Disclosed test-run incident

The first attempt at this audit started while an earlier background suite was still alive. Both runs shared `herbanova_bcs_test`, which the harness drops and recreates. That attempt reported 22 failed / 2 errors; the failures were cross-run database interference, not product defects. After stopping the duplicate and confirming no pytest process remained, the isolated rerun above passed all 542 tests. This is recorded as SEC-07, not as a product failure.

### Earlier evidence still valid

- `var/reports/junit-wp4d.xml` — Batch 4d full-suite evidence.
- `var/reports/wp4a-migration-rehearsal.json` — 13-step migration rehearsal.
- Batch 4b/4c/4d browser walk reports — navigation, fallback, route guards and screen rendering.

---

## 10. Source checkpoints and recoverability

### Checkpoint A — `var/backups/baseline-20261103T175350`

| Artefact | SHA-256 | Verified now |
| --- | --- | --- |
| `herbanova-source-eaf38d2.tar.gz` | `d556d1ba5e928067985ba7ac81184e5707d3feb6800a48f17e82b0501991b9c3` | Matches manifest and re-hash |
| `herbanova_bcs_dev-baseline-20261103T175350.dump` | `90d3276e94a4b9c1490404f23521f835838d33112ca377881e6558835de5b883` | Matches manifest and re-hash |

The directory carries `SHA256SUMS`, a dump TOC, Alembic status, pip freeze, error baseline and a recorded restore test with zero row differences. The database is at `0029`, so it is a pre-0030/0031 restore point.

### Checkpoint B — `var/backups/wp4d-preflight-20261104T105859Z`

| Artefact | SHA-256 | Verified now |
| --- | --- | --- |
| `source.zip` (304 entries) | `0f1838e8165e6d8429fc2b9db18d057678443e73dfbf851cf17a442573cf1618` | Matches manifest and re-hash |
| `herbanova_bcs_dev.dump` | `59cb23d7c0be20acc8446b2afd0b6e6bb78751fd6e063350f6c62ab4f6cca62a` | Matches manifest and re-hash; `pg_restore --list` shows 90 TABLE DATA entries including `nav_nodes` and `feature_registry` |

### Gap

Checkpoint B was taken **before** Batch 4d activation: its `static/js/app.js` still has `NAV_API_ENABLED = false`, and its manifest counts 49 working-tree entries, not the current 52. **No checkpoint captures the exact final 4d tree** (`NAV_API_ENABLED = true`, 52 entries, including this report).

Recoverability is otherwise sound: both archives extract, both dumps list and restore, and the older dump gives a clean pre-registry fallback. The gap is closed either by taking a final archive before committing (C-7) or by treating the approved commit and tag as the checkpoint.

---

## 11. Known limitations and technical debt

1. **Server labels are unused** by the rail (SEC-06); labels are effectively catalogue-owned.
2. **Favourites and recents are client-side only.** The ETag accepts them but receives empty lists (SEC-10). There is no server persistence yet.
3. **No admin editing of the registry.** Screens and features change by catalogue + migration + seed only. The admin endpoint is read-only.
4. **Exact catalogue counts** make any unaccompanied change a 503 + built-in fallback (SEC-04).
5. **Built-in menu remains duplicated** in `workspace.js`. Parity tests protect it, but two sources still exist until WP-5.
6. **Container permission rules are not enforced** (SEC-03), latent until WP-5.
7. **Test database is a single fixed name** (SEC-07); suites must run serially.
8. **Stale historical docs** (SEC-05) and **stale comments** in `static/js/workspace.js` ("Batch 4c, opt-in") and `app/services/navigation_registry.py` ("WP-4a calls none of this at runtime").
9. **Production schema lag** of three revisions (SEC-01), including an irreversible admin session revocation in 0029.
10. **No browser re-walk in this audit**; the promotion gate needs one on a production clone.

None of these is a runtime defect at HEAD. Items 1–8 are cleanup or WP-5 groundwork; 9–10 are promotion gates.

---

## 12. Production deployment prerequisites

All of the following must be true before a production promotion is requested. None is satisfied today except by owner assertion.

1. **Confirm production revision** with a read-only `alembic current`; expect `0028_advances`. If it differs, stop and re-plan.
2. **Fresh production `pg_dump`** (custom format) plus a verified restore of that dump into a disposable clone; record SHA-256 and row counts.
3. **Full rehearsal 0028 → 0031 on a clone of production**, not a scratch database. This must include the 0029 `token_version` bump and a login test for each admin role.
4. **Admin 2FA runbook.** 0029 revokes every admin session and requires enrolment at next login. Recovery codes must be issued and stored offline before the window; the enrolment path must be tested on the clone.
5. **Freeze the application during migration.** The new schema is additive, so old code tolerates it; the new code does not tolerate the old schema. Migrate before starting HEAD.
6. **Verify the seeded registry on the clone:** 64 nodes, 14 features, counts 5/14/20/25/14, Home present, alias unique. A mismatch means 503 and fallback in production.
7. **Smoke-test the clone:** `/api/navigation` returns 200 with a private ETag, revalidation returns 304, a non-admin gets 403 from `/api/admin/navigation`, `?nav=builtin` still renders.
8. **Confirm `feature_flags` mapping** for the 14 registered features so no screen disappears unexpectedly at switch-off.
9. **Rollback window and owner approval.** Named operator, maintenance window, approval to deploy, and a tested rollback path (§13) must be recorded before the change.
10. **Browser sign-off** on the clone across desktop/tablet/mobile and both themes, covering the 25 screens, 19 accounting sub-sections and eight lists.

---

## 13. Rollback and recovery requirements

### Application rollback

All four revisions are additive. The previous release can run against the 0031 schema, so an application rollback does **not** require a database downgrade. Roll back the app image first; keep the schema in place while diagnosing.

### Database rollback (only if the schema must be reverted)

| Target | What is lost |
| --- | --- |
| `0031 → 0030` | `nav_nodes` and `feature_registry`, including any admin edits made after activation. Re-upgrade reseeds the catalogue. |
| `0030 → 0029` | `sign_in_banners`, `sign_in_notices`, `sign_in_contacts`, `legal_documents` and any edited content. The two legal rows are reseeded on re-upgrade. |
| `0029 → 0028` | TOTP columns and recovery hashes; every enrolled admin must re-enrol. `token_version` remains bumped, so sessions stay revoked. |
| `0028 → 0027` | Refused while control heads 1110/2110 are referenced by openings or vouchers. |

For any incident after business writes, prefer restoring the pre-deployment dump over Alembic downgrade. The downgrade path is for schema-only rollback.

### Recovery assets

- Pre-deployment production dump (to be created; does not exist yet).
- Checkpoint A dump at 0029, verified.
- Checkpoint B dump at 0031 with registry rows, verified.
- Dev migration dumps: `pre-0029-totp-20261103T172245.dump`, `pre-0030-20261104T004028`, `wp4a-activation-20261104T082147Z`.
- `scripts/verify_navigation_migration.py` recreates and drops only `herbanova_nav_migration_scratch_test`; use it for future rehearsals.

---

## 14. Git commit readiness

| Item | State |
| --- | --- |
| Branch | `feature/gap-closure` |
| HEAD | `77f5a96` (no local commits since) |
| Staged changes | None |
| Entries to commit | 52 inventoried + this report = 53 |
| Deletions / renames | None |
| Ignored artefacts | `var/` (reports, dumps, probes), `.env` |
| Line endings | `.gitattributes` converts CRLF → LF; expect warnings, blobs will be LF |
| Secret scan | Clean |
| Test gate | 542 Python + 20 Node, all passing |

**Recommended commit shape:** one release commit for WP-2/3/4 on `feature/gap-closure`, staging the 52 inventoried files plus this report explicitly rather than `git add -A`, then tag `wp4-navigation-registry`. If the team prefers reviewable history, split into (1) migration + backend + feature closure, (2) frontend workspace/navigation, (3) tests, docs and manual. Either shape includes every file in §3.

**Before committing:** take the final tree checkpoint (C-7) or accept that the commit plus tag becomes the checkpoint. Do not include `var/`, and do not push until approved.

---

## 15. Proposed corrections — for approval, not applied

| ID | Severity | Change | Risk |
| --- | --- | --- | --- |
| C-1 | Low | Add a "superseded by 4b–4d" banner to `docs/WP4_APPROVAL_READINESS.md` and correct the three stale statements (lines 13, 515, 751) without deleting the historical record. | Docs only |
| C-2 | Medium | Update the `scripts/generate_navigation_seed.py` docstring; make `--write` refuse to edit the active migration unless an explicit `--force-active` flag is passed, while keeping `--check` against the active file. | Tooling only; no schema change |
| C-3 | Low | Align `scripts/navigation_parity_report.py` with the generator: resolve the active `0031` file first, use `.draft` only as a fallback, and rename `_load_draft`/messages accordingly. | Tooling only |
| C-4 | Low | Replace the "(Batch 4c, opt-in)" comment and the "WP-4a calls none of this at runtime" comment with the current default-API description. | Comments only |
| C-5 | Low | Add a one-line note to the WP-4 docs that suites must run serially because `herbanova_bcs_test` is recreated per run. | Docs only |
| C-6 | Low (WP-5 gate) | Decide container permissions: either enforce ancestor `permission_any` in `visible_keys` and add a validation rule, or explicitly forbid permissions on containers in `validate_catalog`. | Backend; needs tests |
| C-7 | Operational | Take a final source checkpoint of the exact 52-entry tree, or approve the release commit + tag as the checkpoint. | None |
| C-8 | Low (WP-5 gate) | Decide whether the rail should render the registry `label` or the local `TITLES`; document the choice and, if registry-owned, render the server label safely. | Frontend; needs a parity test update |

C-1 – C-5 and C-7 are safe to apply as a follow-up. C-6 and C-8 should be settled before WP-5 starts, not before this commit.

---

## 16. Final recommendation

**CONDITIONAL GO for the Git commit; NO-GO for production promotion.**

The working tree contains no blocking defect: 542 Python tests and 20 Node tests pass, the migration chain is linear and additive, the dev database is correct at 0031, and the new navigation path is authenticated, per-user cache-isolated and fail-closed.

Conditions for the commit:

1. Take the final-tree checkpoint or explicitly accept the commit/tag as the checkpoint (C-7).
2. Approve or defer the documentation and generator corrections (C-1 – C-5) — they do not block the code.
3. Commit only the 52 inventoried files plus this report (53 total), with no `var/` content, and do not push until approved.

Production remains **NO-GO** until the ten prerequisites in §12 are met, above all a confirmed production revision, a fresh verified backup, a clone rehearsal of 0028 → 0031 with admin 2FA enrolment, and a browser sign-off.

No fix, commit, push, migration, reset or deployment was performed during this audit. Awaiting approval.

---

## 17. Post-audit hardening status — 4 November 2026

This audit is the accepted baseline. A controlled correction batch then applied
**C-1, C-2, C-3, C-4, C-5 and C-7 only**. C-6 and C-8 were not implemented and
remain gates for WP-5.

| ID | State |
| --- | --- |
| C-1 | **Done** — `WP4_APPROVAL_READINESS.md` is marked superseded, historical values intact. |
| C-2 | **Done** — `--write` refuses the active migration (exit 2); three regression tests. The optional `--force-active` bypass suggested here was deliberately not added. |
| C-3 | **Done** — active-first source resolution, clearer error, relative `--out` resolved against the repository root. |
| C-4 | **Done** — the three stale comments now describe the default-API behaviour. |
| C-5 | **Done and strengthened** — `tests/conftest.py` holds an OS lock before the test database is dropped; `docs/TESTING.md` documents the serial procedure. |
| C-6 | **Open** — WP-5 gate, untouched. |
| C-7 | **Done** — final source checkpoint at `var/backups/wp4-final-20261104T120641Z/` with `manifest.json` and `SHA256SUMS`. |
| C-8 | **Open** — WP-5 gate, untouched. |

Migration `0031_navigation_registry.py` is unchanged
(`ed52f95566c7b097e1a4dcedd6bb243e51b8ec283a40b1339dec667ecd6c6f04`), the
development database remains at `0031_navigation_registry`, and the verification
run is 545 Python tests, 20 Node tests, 11 parity checks and 226 browser checks,
all passing. The §14 entry count predates `docs/TESTING.md`, the seed-tool test
and the final-tree checkpoint; the staging manifest in the hardening report is
authoritative. Full evidence: [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md)
§38.

Nothing was committed, pushed or deployed after this status update.
