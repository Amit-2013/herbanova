# WP-4 approval-readiness review

> **Superseded — kept for history.** This document records the Batch 4a
> approval review and activation. Batches 4b, 4c and 4d were subsequently
> approved, implemented and activated; the current release position is
> [WP4_RELEASE_READINESS.md](WP4_RELEASE_READINESS.md) (4 November 2026).
> Statements below such as "NO-GO for 4b–4d" and "`/api/navigation` remains
> unimplemented (404)" describe 4a at the time and are no longer current.
> Production remains at `0028_advances` and has not been touched.

**Date:** 4 November 2026
**Branch:** `feature/gap-closure`
**HEAD:** `77f5a96e4182af7a67eea95405d4c03fc66820e6`
**Working tree at activation:** 24 modified and 19 untracked files (43 total); nothing reset, cleaned, committed or pushed. The review snapshot (22 modified, 19 untracked) is preserved in `var/backups/wp4-review-20261104T122641/`; the activation checkpoint is `var/backups/wp4a-activation-20261104T082147Z/`.
**Scope:** re-verify WP-2 and WP-3 from the running application and the suite, then audit the WP-4 design in [FEATURE_REGISTRY_DESIGN.md](FEATURE_REGISTRY_DESIGN.md) against the code and the live schema.
**Owner decision under review:** "WP-2 / WP-3 direction accepted; WP-4 implementation not yet approved. I would move forward with the approval-readiness review first."
**Correction pass:** 4 November 2026, later the same day. R-01, R-02 and R-03 are resolved in the corrected design and in code. See §11.
**Rehearsal:** 4 November 2026, later again. `0031` applied, seeded, downgraded and re-applied on two disposable scratch databases; the three gated tests passed. See §13 and [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) §33.
**Activation:** 4 November 2026, after explicit owner approval. The draft was renamed to `alembic/versions/0031_navigation_registry.py`, both tables were added to `KEPT_TABLES`, and `0031` was applied to the approved development database `herbanova_bcs_dev` only (`0030_sign_in_content` → `0031_navigation_registry`). Full suite **499 passed, 0 failed, 0 skipped**; browser walk **113/113**. See §14 and [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) §34.

**Verdict at the time (4a only):** **Batch 4a is activated in development and verified**; WP-2 and WP-3 behaviour is unchanged. **NO-GO for 4b–4d** until each is separately approved. Production remains at `0028_advances` and was not touched. **Superseded:** 4b–4d were later approved and activated — see [WP4_RELEASE_READINESS.md](WP4_RELEASE_READINESS.md).

---

## 1. Preservation record

| Item | State |
|---|---|
| Branch / HEAD | `feature/gap-closure` at `77f5a96` (unchanged by activation) |
| Working tree | 24 modified, 19 untracked, 0 deleted after activation; the review snapshot in `var/backups/wp4-review-20261104T122641/` and the activation checkpoint in `var/backups/wp4a-activation-20261104T082147Z/` are both complete |
| WP-2 / WP-3 source | behaviour untouched; activation edited only navigation plumbing: the migration rename, `app/services/db_reset.py` (`KEPT_TABLES`), `app/models/__init__.py` (model import) and path resolution in the navigation scripts and one test |
| Database | the review itself was read-only; the rehearsal used two scratch databases, both dropped; the activation applied `0031` to `herbanova_bcs_dev` only, after a verified dump and with no business row changed (§14) |
| Production settings | not read, not changed |
| Emails | none sent |

Commands that did **not** run: `git reset`, `git clean`, `git checkout`, `git commit`, `git push`, any business `INSERT`/`UPDATE`/`DELETE`. The review and rehearsal touched no existing database; the only `alembic upgrade` against an existing database is the approved activation on `herbanova_bcs_dev` recorded in §14. No downgrade was run on that database.

The 43 working-tree entries are listed in §10.

---

## 2. Method and evidence index

Every fact below is labelled one of:

- **Verified** — measured in this working tree or observed in the running application during this review.
- **Assumption** — inferred from code but not executed.
- **Not verified** — stated as a gap, with the reason.

| Evidence | Path | What it proves |
|---|---|---|
| Route, ownership, catalogue and schema census (read-only) | `var/reports/wp4r-audit.json` | 344 `APIRoute` objects, 268 distinct paths (267 `/api` + `/`), 229 owned / 39 unowned, 14 features, 49 permissions, 87 model tables, 182 FKs |
| Table census (read-only) | `var/reports/wp4r-tables.json` | all 88 live tables, row counts, incoming FK counts, CLEAR/KEEP/SCHEMA class |
| Hierarchy extraction | `var/reports/wp4r-hierarchy.json` | 5 modules, 14 categories, 20 groups, 25 screens, 25 titles, 4 hidden |
| Full suite | `var/reports/wp4r-pytest.xml`, `wp4r-pytest.log` | 468 passed, 0 failed, 0 skipped, 695 warnings, 227.65 s, exit 0 |
| Workspace model | `var/reports/wp4r-node.log` | 18 passed, 0 failed |
| Browser walk | `var/reports/wp4r-browser.json`, `wp4r-browser.log` | 113/113 checks: WP-2 replay 42, 21st tab 20, eight lists 51 |
| WP-2 replay only | `var/reports/wp4r-wp2walk.json` | the unchanged WP-2 walk, 42/42 |
| Review scripts | `var/review/audit.py`, `var/review/tables.py`, `var/review/wp4walk.py` | reproducible measurements; all read-only except the browser's GET requests |

Environment for the browser walk (**Verified**): temporary API `python var/probe/serve_test.py` on `127.0.0.1:8011` over `herbanova_bcs_test`; static UI `python scripts/run_frontend.py --port 3011 --backend http://127.0.0.1:8011`; headless Chrome exposing CDP on `127.0.0.1:9223` with a throwaway profile. Session cookies were minted in-process for `admin` and a `viewer`-role account. The Chrome binary path is machine-specific and is not stored; it is the only launch step not reproducible from a repository command.

No data was created or changed. Phase C issues only GET requests: the search, filter and export requests named in §5 are the application's own reads.

---

## 3. Independent re-verification

### 3.1 Automated suites — **Verified**

| Run | Result |
|---|---|
| `node --test tests/js/workspace.test.cjs` | **18 passed, 0 failed, 0 skipped** in 72.7 ms |
| `python -m pytest -q -rs` | **468 passed, 0 failed, 0 skipped, 695 warnings in 227.65 s**, exit 0 |

`pytest.ini` sets `testpaths = tests`, so the probe servers under `var/` are not collected. The suite includes the Node file through `tests/test_workspace_model.py`, which is why 18 Node tests appear as one pytest test.

### 3.2 WP-2 — **Verified**, including the previously unwalked 21st tab

Phase A replayed the WP-2 walk unchanged: **42/42 passed**. It covers Home and hierarchy, opening screens, accounting sections as separate tabs, switching and duplicate identity, the overflow menu, closing current/others/all, reopen, keyboard arrow/Delete, favourites and recents, reload and deep links, the unsaved-drawer guard, the palette, 1440/768/390, both themes, and role filtering. The viewer phase made no refused call in a steady session.

Phase B is the flow the WP-2 report explicitly left unwalked (`VERIFICATION_REPORT.md` §30.4: "the browser path for the 21st tab was not re-walked"). **20/20 passed:**

| Check | Result |
|---|---|
| B0 fixture starts from Home only | pass |
| B1 the fixture holds the 20-tab bound with Home pinned first | pass |
| B1a the deep-linked screen keeps its query while open (`#/accounts/gst-out?due=week`) | pass |
| B2 opening `#/users` as the 21st screen keeps the strip at 20 | pass |
| B2a the 21st screen is open, active and shows its own route | pass |
| B2b Home is still pinned first and cannot have been evicted | pass |
| B3 the oldest screen is evicted from the strip, not silently lost | pass |
| B3a the evicted screen is offered by *Reopen closed tab* | pass |
| B4 reopening restores the evicted screen as the active tab | pass |
| B4a the restored screen keeps its exact address and query | pass |
| B4b the restored screen renders its own section and breadcrumb (`GST outward`) | pass |
| B4c reopening at the bound keeps the strip at 20 | pass |
| B4d the screen evicted by the reopen is itself recoverable | pass |
| B5 the second reopen brings back the screen the first reopen evicted | pass |
| B6 Home has no close button and the menu cannot close it | pass |
| B6a Delete on the Home tab does not close it | pass |
| B7 reopening the same screen never duplicates the tab | pass |
| B7a a second query on the same screen updates that tab's address | pass |
| B7b Home is one tab no matter how often it is opened | pass |
| B8 no page errors or unhandled rejections in the tab flows | pass |

This closes the WP-2 evidence gap: eviction is recoverable, and the restored tab keeps route, query and breadcrumb. The browser path for the *second* reopen at the bound was also exercised.

### 3.3 WP-3 — **Verified**, all eight lists read-only

Phase C: **51/51 passed** across Products, Suppliers, Customers, Sales orders, Purchase orders, Billing, Approvals and Leads. For each list: the server pager total, the presence of search/clear/export/rows, search sending `q=ZZZQ-NO-SUCH-RECORD` and the server answering with zero rows, Clear dropping `q=` and restoring the base total, the filter request carrying the filter parameter, and the CSV export request carrying no `page=`.

| List | Server total | Pager |
|---|---:|---|
| Products | 58 | 1–50 of 58 |
| Suppliers | 6 | 1–6 of 6 |
| Customers (distributors) | 47 | 1–47 of 47 |
| Sales orders | 93 | 1–50 of 93 |
| Purchase orders | 56 | 1–50 of 56 |
| Billing invoices | 85 | 1–50 of 85 |
| Approvals | 14 | 1–14 of 14 |
| Leads | 2 | 1–2 of 2 |

Products is the only list with sort controls: 7 header buttons, and two clicks on `mrp` produced `/api/products?page=1&page_size=50&sort=mrp&direction=asc` then `…&direction=desc` with `aria-sort` `ascending` then `descending`. The other seven lists had **0** sort controls. No shared list infrastructure was rewritten.

### 3.4 Not verified in this review

| Item | Why |
|---|---|
| Screen readers, physical tablets/phones, Safari and Firefox | no assistive tooling or devices in this workspace; only headless Chrome was driven |
| 21st-tab flow at 768/390 and in the dark theme | phase B ran at 1440 in the default theme; responsive tab layout is covered by phase A, not the 20-tab bound |
| Two concurrent browser tabs sharing `sessionStorage` | not exercised |
| Session restoration after a full browser restart | tabs are `sessionStorage`; reload restoration was proved, not browser restart |
| Real email delivery | test mode only, as required |
| Production and staging | not touched; `0031` is active in the repository and applied to `herbanova_bcs_dev` only. Production is still at `0028_advances` and needs 0029 → 0030 → 0031 under separate approval |
| The 46 cleared / 43 kept tables after an actual business reset | classification and CASCADE graph were read, not executed; the existing reset tests remain the authority |

---

## 4. WP-4 audit A–H against the code

### A. Hierarchy, screens and feature ownership — **Verified**

| Thing | Measured | Design seed target | Result |
|---|---:|---:|---|
| Modules | 5 | 5 | match |
| Categories | 14 | 14 | match |
| Groups | 20 | 20 | match |
| Screens (routed views) | 25 | 25 | match |
| Titles | 25 | 25 | match |
| Hidden from rail | 4 (`compare`, `tax`, `users`, `audit`) | encoded by `NOT_IN_MENU` | match |
| Aliases | 1 (`distributors` → `customers`, `workspace.js:199`) | 1 | match |
| Feature switches | 14 | 14 | match |
| Permission keys | 49 | not seeded | — |

Source: `static/js/workspace.js` `NAV` (line 19), `TITLES` (80), `VIEW_PERM` (91), `VIEW_FEATURE` (103), `SECTION_VIEWS` (115), `MENU_EXTRA` (120), `NOT_IN_MENU` (125); extraction in `var/reports/wp4r-hierarchy.json`.

**Feature coverage does not equal the screen count.** `Feature.views` holds **22** strings: 21 of the 25 screens plus the alias `distributors`. `dash` and `settings` are deliberately featureless (Home and Settings). `expenses` and `roles` are missing from every `Feature.views` even though the browser maps them to `accounts` and `users` — design drift **D-01 is confirmed**, not assumed. `distributors` is the alias, not a screen — **D-02 is confirmed**.

**The fourth level is a screen, not a feature.** Feature is a cross-cutting attribute (`feature_key`), not a hierarchy level. The design's Module → Category → Group → Screen is correct; describing it as "→Feature" would conflate two axes.

**Gap G-01 (new, not in the design): the 19 accounting sub-sections are not modelled.** `ACC_SECTIONS` (`app.js:4371`) defines 19 sections; each is a separate tab (`#/accounts/gst-out`) with its own visibility rule (`accSectionAllowed`, `app.js:4392`: `reports` needs the reports permission, the rest need `accounts:read`). `/api/navigation` returns screens, not sections. A 4c/4d SPA can render the 25-screen tree from the API but must still take the accounts sections from `workspace.js`/`app.js`, or the schema needs a section concept. This does not block 4a; it blocks any claim that 4d makes the API the *only* navigation source.

### B. Proposed schema, table by table and field by field

Design reference: §4.1 table audit, §4.2 `nav_nodes`, §4.3 `feature_registry`, §4.4 R-01. The corrected design creates **two** tables; `nav_aliases` and `user_favourites` are not in `0031`.

#### `nav_nodes` — necessary for a DB-managed menu

| Column | Verdict |
|---|---|
| `id`, `parent_id`, `depth` | Correct. `depth` duplicates the parent chain but makes queries and the `(depth between 1 and 4)` check cheap; the service check in §4.1 is the right place for parent/child agreement. `parent_id ON DELETE RESTRICT` matches D7 (deactivate, never delete). |
| `node_key` | Correct and stable. It is the identity the API, favourites and aliases use. `unique` is required; the design has it. |
| `label`, `kind`, `sort_order`, `active`, timestamps` | Correct. `kind` plus `check((kind='screen') = (view is not null))` is a real invariant. |
| `view` | Correct; `view` is the renderer identity today. Must be a key of `TITLES`; §7 validates it. |
| `route` | **Duplication.** Today `route = "#/" + view` for all 25 screens (sections and query strings excluded). Storing it is only useful as a route inventory. If kept, `validate_registry` must refuse a stored route that is not exactly `"#/" + view`; otherwise the inventory can lie. |
| `component_key` | **Duplication today** (equals `view`). The design keeps it so a screen can be re-implemented without renaming its node. Acceptable only with a validation that it equals `view` until a real second component exists, or with a documented invariant. |
| `feature_key` | Correct as a nullable attribute. **No FK** to `feature_flags.key`: R-01 is resolved in the corrected design and asserted by tests. |
| `aliases` | Added by the correction. One JSON array on the target node (`["distributors"]` on `customers`); replaces the `nav_aliases` table. |
| `is_home` | Added by the correction. Exactly one row, partial unique index, active/depth 4/featureless/permissionless; makes D6 a schema invariant rather than a comment. |
| `permission_any` | Correct for today's four OR rules: `accounts` (`accounts:read` or `accounts:reports`), `hr` (`hr:read` or `hr:attendance_self`), `compare` (`sales:read` or `stock:read`), and the single-key screens. JSON array is proportionate for 25 rows (D4). |
| `menu_rule`, `menu_any` | Correct and necessary. It encodes `MENU_EXTRA` for `settings` (4 keys) and `reports` (6 keys) and `NOT_IN_MENU` for four screens, which a single `permission` column cannot express (D-03, D-04). |
| missing | No uniqueness on `(parent_id, label)`; two siblings may share a label while `node_key` stays unique, which would confuse the rail. No column enforces the Home lock; D6 must be a service/validation guard on `node_key='home'`. Both are additions to §7, not new tables. |

#### `nav_aliases` — **not created (resolved)**

One row (`distributors`). A separate table, a join and a second natural key are
not justified for one value. The corrected design folds it into
`nav_nodes.aliases`; validation refuses a collision and the Node parity test
proves `#/distributors` still opens Customers. R-03 is resolved.

#### `feature_registry` — necessary

`feature_flags` cannot be reused: it is the sparse switch state (one boolean per feature, an absent row meaning ON — `app/services/feature_store.py:5-9`), and it holds no ownership mapping. Adding ownership columns would alter an existing table, which the additive rule forbids, and would lose ownership for any feature whose flag row is absent. `feature_registry` is therefore justified. `label`/`description`/`permissions`/`api_prefixes` duplicate `app/core/features.py` **on purpose** so a management screen can read the registry without importing code; that duplication is safe only with the parity test in design §5. `tables` is documentation-in-DB and can drift; it is not read at runtime in 4a–4d. `enabled` is correctly absent (D3). `depends_on` is empty today; acceptable as a declared future column, but it is speculative.

#### `user_favourites` — **deferred to `0032` (resolved)**

It cannot reuse `hr_saved_filters`: that table is `(user_id, view, name)` unique with a JSON parameter payload, belongs to the HR feature, and is cleared by a business reset. Favourites are a different object (ordered node pins, no name, no params). But nothing reads favourites before 4d and D8 is unapproved, so `0031` does not create an empty table; `0032` adds it, additively, only if server-side favourites are approved. Favourites are preferences, not events: no audit rows (D12).

`feature_registry.tables` stays `[]`: the code maps features to API prefixes, not model tables. Inventing a table list would violate the no-invented-inputs rule; WP-5 derives it or the column is dropped.

### C. Permissions and enforcement — **Verified**

- 49 permission keys; every key has a parent entry; every key belongs to exactly one feature; no view belongs to two features (`wp4r-audit.json`).
- Effective permissions are `effective_permissions(stored) - disabled_permissions(db)` (`app/core/rbac.py:44`). Parent gating and feature narrowing therefore apply to routes, `/api/auth/me`, navigation and search alike.
- `require_admin` checks both the permission and the Administrator role (`rbac.py:91`); `require` checks the permission (`rbac.py:102`); `_feature_gate` refuses a path whose feature is off (`app/main.py:44`, longest-prefix lookup in `features.py:142`).
- Five keys are Administrator-only (`permissions.py:135`), and a non-admin role cannot even store them (`app/services/accounts.py:51-55`).
- The browser rules that the registry must preserve are exactly: `compare` OR, `hr` OR, `accounts` OR, `scheduled` `email:manage` plus `srAllowed`, and the menu-only narrowing for `reports` and `settings` (`workspace.js:151-169`). `srAllowed` additionally checks that the user's role string is `admin` (`app.js:11084`); since `email:manage` is Administrator-only on the server, dropping `srAllowed` from navigation (D-05) does not widen access in any supported state. A direct database edit that bypasses `validate_permissions` could create a non-admin role holding `email:manage`; in that unsupported state today's client hides the screen while the API would allow it. Dropping the client rule aligns the UI with the API rather than weakening it.
- The 38 unowned `/api` paths (39 including the root `/` redirect) are identity, Administrator-only, public or health paths; D-06's list matches the measurement exactly (11 admin, 8 auth, 6 db-reset, 1 db/reset, 3 public, 3 roles, 2 dashboard, 2 features, 1 health, 1 modules).

### D. Frontend routes and screens — **Verified**

25 `<section id="v-*">` elements, 25 `TITLES`, hash routes `#/view/section?query`, alias resolution at `workspace.js:199`, four hidden screens. Deep links and refresh passed in the walk, including `#/accounts/gst-out?due=week` as the evicted-and-restored tab. Sections exist only for `accounts` (`SECTION_VIEWS`, line 115); the Inventory and Scheduled in-page tabs deliberately stay one workspace tab, pinned by a Node test.

### E. API ownership — **Verified, with one correction**

| Measure | Value |
|---|---:|
| `APIRoute` objects registered | **344** |
| Distinct paths (267 `/api` + `/`) | **268** |
| Owned by a feature prefix | 229 |
| Unowned | **39** (38 `/api` + `/`) |
| Duplicate path+method pairs | 0 |

Per-feature owned paths: `hr` 81, `accounts` 50, `sales` 26, `scheduled` 16, `stock` 9, `foc` 8, `tax` 8, `leads` 7, `suppliers` 5, `approvals` 4, `audit` 4, `products` 4, `reports` 4, `users` 3.

**Correction to design §1:** it states 348 API routes. The runtime has 344 `APIRoute`s; `len(app.routes) = 349` is 344 plus four framework `Route`s (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`) and one static `Mount` at `/ui`. The design's "348 is what FastAPI actually registers" is an overcount of four. Paths were re-counted for this correction pass: **268 distinct paths, 229 owned, 39 unowned** — 38 `/api` paths plus the root `/` redirect, which the earlier draft omitted by counting `/api` only. The unowned `/api` group list in D-06 is unchanged. Corrected in `FEATURE_REGISTRY_DESIGN.md` §1.

### F. Feature flags and module registration — **Verified**

- 14 feature rows in `Feature.views`/`FEATURES`; `users` is locked ON; `/api/features` is Administrator-only (`app/api/features.py`).
- `feature_flags` is sparse. Migration `0016_feature_flags` bulk-inserts the 14 keys at creation, but the live test database currently holds **0** rows because `tests/test_feature_switches.py:30-33` deletes every row after each test. Absence means ON (`feature_store.feature_rows`).
- 18 delivery modules (`/api/modules`) are a different concept from the 14 switches. D-07's naming warning is real; the new names `nav_nodes`/`feature_registry` avoid a third meaning.
- D-01's ownership gaps (`expenses` → accounts, `roles` → users) are confirmed and the seed corrects them. The parity test pins the corrected map (`DOCUMENTED_VIEW_ADDITIONS` in `app/services/navigation_registry.py`), not the current `Feature.views`.

### G. Duplicates, aliases, orphans and gaps

| Finding | Status |
|---|---|
| Duplicate API path+method | none (0) |
| Permission owned by two features | none |
| View owned by two features | none (`feature_views_listed_twice` empty) |
| Permission with no parent entry | none |
| Permission in no feature | none |
| Unclassified table | none (46 + 41 + 1 = 88) |
| Proposed table-name clash | none |
| Alias represented twice | `distributors` is a view in `sales` **and** an alias; the seed stores it only as an alias (`nav_nodes.aliases` on the `customers` node), never as a node (design D-02) |
| Screen unreachable from the rail but reachable by route | `compare`, `tax`, `users`, `audit` — intentional, not orphans |
| Screen with no feature | `dash`, `settings` (intentional); `expenses`, `roles` (a defect the seed fixes) |
| Navigation modelled twice | `workspace.js` and `nav_nodes` until 4d — transitional by D1, not removable before cutover |
| Owning metadata modelled twice | `features.py` and `feature_registry` — intentional, parity-tested |
| Derivable data stored | `route` = `#/` + `view`; `component_key` = `view` today; both refused by validation if they diverge (R-04) |
| **Unmodelled sub-navigation** | 19 accounting sections (G-01), out of registry scope for 4a–4c |

### H. Existing business data and migration blast radius — **Verified from the live test schema**

- Live schema: **88 tables, 182 foreign keys, revision `0030_sign_in_content`** (`wp4r-audit.json`). Models define 87 tables; `alembic_version` is the 88th.
- The **two** tables in 0031 (`nav_nodes`, `feature_registry`) add **no foreign key to `feature_flags`** and reference exactly one existing table: `nav_nodes.parent_id` → `nav_nodes.id` (self-referencing). `feature_registry.feature_key` and `nav_nodes.feature_key` are plain `String(32)` validated against `FEATURES`. **No foreign key points at any of the 46 CLEAR tables.** Therefore 0031 cannot delete, truncate, rewrite or cascade into a document, stock, money or HR-transaction row, and the downgrade drops only the two new tables.
- New incoming foreign keys: **none.** `users` stays at 79 incoming FKs, `feature_flags` stays at 0. `user_favourites` (which would have added the one `users.id` FK) and `nav_aliases` (which would have added a second `nav_nodes.node_key` FK) are not in 0031 (design §4.1). This also removes the R-01 failure path: nothing in the registry can block the switch-test fixture from deleting `feature_flags` rows.
- Business-reset guard: `_reset_business_data` truncates `BUSINESS_TABLES` with `CASCADE` and refuses if `_cascade_reaches` touches a kept table (`app/services/db_reset.py:843-849`). No BUSINESS table references the new tables, so the new tables cannot enter that CASCADE. A full reset drops the schema and replays every migration, so the new tables and seed are recreated.
- Existing row volumes in the CLEAR half (largest first): `stock_movements` 113, `sales_orders` 93, `invoices` 85, `invoice_lines` 85, `hr_notifications` 73, `batches` 67, `sales_order_lines` 58, `purchase_orders`/`purchase_order_lines` 56 each, `hr_leave_balances` 56, `goods_receipts`/`lines` 48 each, `approval_requests` 46, `hr_payroll_entry_lines` 46. None is touched by 0031.

---

## 5. Migration risk register

Status column: **Resolved** = fixed in the corrected design and covered by a test or a validation rule; **Open — owner decision** = needs a decision, not a code change; **Open — later batch** = deliberately deferred.

| # | Severity | Risk | Evidence | Resolution in this correction pass |
|---|---|---|---|---|
| **R-01** | ~~High~~ **Resolved** | `feature_registry.feature_key` and `nav_nodes.feature_key` were foreign keys to a sparse `feature_flags.key`, with no cascade. `tests/test_feature_switches.py:32` deletes every flag row after each test, and an absent row means ON, so a registered feature could legitimately have no row. | `tests/test_feature_switches.py:30-33`; `app/services/feature_store.py:5-9`; 0 `feature_flags` rows on the test DB | **Both foreign keys removed.** `feature_key` is `String(32)` on both tables and is validated against `FEATURES` by `validate_catalog` (unknown key → error). `feature_flags` stays the only switch state; absence stays ON. Five tests pin it: registered feature with no switch row (on), registered feature with a disabled row (registry row survives, nodes hidden), deleting every switch row (no FK error, rollback clean), unknown feature key rejected, registry membership neither enables nor disables a switch. `test_registry_has_no_foreign_key_to_feature_flags` asserts the FK sets directly. `ON DELETE CASCADE` was rejected: deleting a switch row means "ON again", not "forget the feature". |
| **R-02** | Medium (documentary) — **Resolved** | Design §1 said 348 API routes; runtime is 344 `APIRoute`s, and the path count omitted the root `/`. | route-type census; `wp4r-audit.json` | §1 now reads **344 `APIRoute`s, 268 distinct paths (267 `/api` + `/`), 229 owned, 39 unowned**, with the four framework `Route`s and the `/ui` `Mount` reconciled. No test depends on 348. |
| **R-03** | Medium (simplification) — **Resolved** | A whole `nav_aliases` table for one row (`distributors`). | design §4.2; `workspace.js:199`; exactly one alias | **`nav_aliases` is not created.** The alias is a JSON array `aliases` on `nav_nodes`, populated with `distributors` on the `customers` node. Validation refuses a duplicate alias, an alias that collides with a node key, or an empty segment. `user_favourites` is also deferred to a hypothetical additive 0032 contingent on D8, so 0031 creates **two** tables. |
| **R-04** | Medium (drift) — **Resolved** | `route` and `component_key` duplicate derivable data; a registry edit could point a node at a route no renderer serves. | `route = "#/" + view`; `component_key = view` for all 25 | `validate_catalog` refuses a screen whose `route != "#/" + view` or whose `component_key != view`. Both are pinned by tests. |
| **R-05** | Medium (completeness) — **Open — later batch** | The registry models 25 screens, not the 19 accounting sections or their per-section permission rule. | `app.js:4371` `ACC_SECTIONS`; `app.js:4392` `accSectionAllowed` | Recorded as out of registry scope for 4a–4c in design §4.1 and §13. A decision is required before 4d: keep sections in code or add a section table in a later migration. 0031 does not model them. |
| **R-06** | Medium (test) — **Resolved** | Seed literal and generator could diverge; a screen added to the SPA without a registry row must fail the suite. | design §5, §9 | `scripts/generate_navigation_seed.py` is the only writer of the literal; `tests/test_navigation_registry.py` re-reads `workspace.js` (through `tests/js/emit_nav_manifest.cjs`) and `features.py` and compares counts, labels, order, permissions, menu rules, feature keys and the alias. Draft literal verified equal to `build_nodes()`/`build_features()`. |
| **R-07** | Medium (cache) — **Resolved (design)** | An ETag of registry version + user + permission hash could serve a stale menu after a feature switch, because a switch changes the menu without changing permissions. | design §6.1 | `navigation_etag()` hashes the registry fingerprint **plus** user id, sorted permissions, **sorted enabled features**, favourites and recent keys. The registry fingerprint is derived from the seeded rows, not a hand-bumped column. The API test that flips a feature and expects a new ETag belongs to batch 4b (no endpoint exists in 4a); the hash function and its tests exist now. |
| **R-08** | Low–Medium (scope) — **Resolved (policy)** | Recents were to be computed from `audit_log` `view.open` rows, inflating the security/business audit trail. | design §6.1; `audit_log` 943 rows and KEEP | **No audit row is written for opening a screen, for navigation overall, or for favourites.** Recents are therefore deferred: the response returns an empty list until a separate lightweight per-user mechanism is designed and approved (design §6.1, §13). Navigation stays decoupled from the audit register. |
| **R-09** | Low (governance) — **Resolved** | Home was "locked" by decision only. | design D6 | `nav_nodes.is_home` plus a **partial unique index** (`ux_nav_nodes_home`) and a CHECK (`NOT is_home OR (depth = 4 AND view IS NOT NULL AND feature_key IS NULL)`); `validate_catalog` refuses zero or more than one Home, and refuses a Home that is inactive, permission-gated, in the menu-`never` rule, or not the `dash` view. Enforced again in the WP-5 edit endpoints. |
| **R-10** | Low (behaviour) — **Open — owner decision** | `reports` and `settings` are open by URL to any signed-in user today, with only the rail narrowed by `MENU_EXTRA`. | `workspace.js:151-169`; `MENU_EXTRA` | The seed preserves the behaviour: `permission_any=[]`, `menu_rule='menu_any'`. Recorded as an explicit intent (design D-03/D-04, §12 Q5). Each panel's API enforces its own permission, so preserving it is not a security regression; tightening it would be a behaviour change and needs approval. |
| **R-11** | Low (promotion) — **Open — later batch** | Production is at `0028_advances`; 0031 cannot be the first migration applied there. | design §10 | Promotion order 0028 → 0029 → 0030 → 0031, with a verified dump and a rollback tested at 0030. Documented in design §10; nothing applied. |
| **R-12** | Low (documentation) — **Resolved** | `PROJECT_ARCHITECTURE.md` and `NAVIGATION_AND_TAB_DESIGN.md` still quoted 341 routes, the 467-test baseline and HEAD `eaf38d2`. | greps in those files | Corrected in this pass to 344 `APIRoute`s / 268 paths, the current test count and HEAD `77f5a96`. |

**Business-data risk (H): none identified for upgrade or downgrade.** With R-01 removed, the only foreign key in 0031 is `nav_nodes.parent_id` → `nav_nodes.id`; nothing references a business table, and nothing blocks the switch fixture.

---

## 6. KEPT_TABLES classification

As it stands in `app/services/db_reset.py` (BUSINESS_TABLES line 54, KEPT_TABLES line 88, SCHEMA_TABLES line 106). Counts are from `var/reports/wp4r-tables.json` on `herbanova_bcs_test`. "Survives business reset" is the existing contract, unchanged by this review. WP-4 adds **two** rows to KEEP at activation (§7 Q3) — not in this pass.

### 6.1 Kept (41)

| Table | Rows | Incoming FKs | Purpose | Business-data status |
|---|---:|---:|---|---|
| `users` | 35 | 79 | Sign-in identities, password hashes, token version | Identity and credentials; not transaction data |
| `roles` | 20 | 1 | Role names, stored permission keys, parent gating | Access configuration |
| `employees` | 383 | 17 | HR employee master (personal data) | HR master data, deliberately kept |
| `products` | 58 | 10 | Product master, prices, HSN, stock flags | Master data |
| `suppliers` | 6 | 3 | Supplier master, bank details (encrypted) | Master data |
| `distributors` | 47 | 6 | Customer/distributor master | Master data |
| `warehouses` | 47 | 4 | Warehouse/site master | Master data |
| `tax_rates` | 1 | 0 | GST rate master | Master data |
| `discount_slabs` | 0 | 0 | Discount slab master | Master data (empty) |
| `ledger_accounts` | 11 | 3 | Chart of accounts | Accounting master data |
| `expense_heads` | 10 | 1 | Expense category master | Master data |
| `company_profile` | 1 | 0 | Legal name, address, GSTIN, print identity | Company configuration |
| `expense_settings` | 1 | 0 | Expense numbering/approval configuration | Configuration |
| `email_settings` | 0 | 0 | SMTP configuration (secrets not printed) | Configuration |
| `email_recipients` | 1 | 1 | Scheduled-report recipients | Configuration |
| `email_schedule_recipients` | 0 | 0 | Per-schedule recipient links | Configuration |
| `email_schedules` | 0 | 2 | Scheduled-report definitions | Configuration |
| `feature_flags` | 0 | 0 | Sparse ON/OFF override per feature; absent = ON | Feature-switch state |
| `document_sequences` | 5 | 0 | Next document number per series | Numbering state |
| `financial_year_closes` | 1 | 0 | Year-close record and lock | Financial control record, kept by existing decision |
| `hr_approval_workflows` | 6 | 0 | HR approval routing | HR configuration |
| `hr_attendance_rules` | 0 | 0 | Attendance/shift rules | HR configuration |
| `hr_branches` | 12 | 4 | Branch/site master | HR master data |
| `hr_departments` | 3 | 1 | Department master | HR master data |
| `hr_holidays` | 2 | 0 | Holiday calendar | HR configuration |
| `hr_leave_types` | 20 | 2 | Leave type master and entitlements | HR configuration |
| `hr_letter_templates` | 4 | 0 | Letter/PDF templates | HR configuration |
| `hr_shifts` | 3 | 2 | Shift master | HR configuration |
| `hr_work_locations` | 11 | 4 | Work location master | HR master data |
| `hr_salary_components` | 13 | 2 | Salary component master | HR configuration |
| `hr_salary_structures` | 8 | 1 | Salary structures | HR configuration |
| `hr_salary_structure_lines` | 13 | 0 | Structure components and amounts | HR configuration |
| `hr_period_locks` | 11 | 0 | Payroll period locks | HR control record |
| `hr_saved_filters` | 0 | 0 | Per-user saved list filters (view + name + JSON params) | Per-user preference, HR-scoped; not usable for favourites |
| `hr_employee_assets` | 1 | 0 | Assets assigned to an employee | HR employee record, kept with the employee |
| `hr_employee_documents` | 3 | 0 | Employee document metadata | HR employee record, kept with the employee |
| `sign_in_banners` | 0 | 0 | Sign-in screen banners | Public content configuration |
| `sign_in_contacts` | 0 | 0 | Sign-in support contacts | Public content configuration |
| `sign_in_notices` | 0 | 0 | Sign-in notices | Public content configuration |
| `legal_documents` | 2 | 0 | Terms/privacy text shown at sign-in | Public content configuration |
| `audit_log` | 943 | 0 | In-database audit trail | Audit trail; deliberately survives a business reset |

### 6.2 Cleared by a business reset (46)

Every row is transactional or a derived log; none is referenced by the two new tables.

| Table | Purpose | Status |
|---|---|---|
| `approval_requests` | Approval requests and decisions | Cleared |
| `bank_statement_lines` | Imported bank statement lines | Cleared |
| `bank_statements` | Imported bank statements | Cleared |
| `batches` | Stock batches and expiry | Cleared |
| `cost_corrections` | Audited cost-correction records | Cleared |
| `credit_note_lines` | Credit-note lines | Cleared |
| `credit_notes` | Customer credit notes | Cleared |
| `debit_note_lines` | Debit-note lines | Cleared |
| `debit_notes` | Supplier debit notes | Cleared |
| `email_deliveries` | Scheduled-email delivery log | Cleared |
| `email_test_messages` | Test-email log | Cleared |
| `expenses` | Expense claims and postings | Cleared |
| `foc_note_lines` | Free-of-cost note lines | Cleared |
| `foc_notes` | Free-of-cost notes | Cleared |
| `goods_receipt_lines` | Goods-receipt lines | Cleared |
| `goods_receipts` | Goods receipts | Cleared |
| `gst_returns` | Filed GST returns | Cleared |
| `hr_announcements` | HR announcements | Cleared |
| `hr_attendance` | Attendance events | Cleared |
| `hr_attendance_corrections` | Attendance corrections | Cleared |
| `hr_import_batches` | Attendance import batches | Cleared |
| `hr_leave_applications` | Leave applications | Cleared |
| `hr_leave_balances` | Per-employee leave balances | Cleared |
| `hr_notifications` | HR notifications | Cleared |
| `hr_od_requests` | On-duty/out-of-office requests | Cleared |
| `hr_payroll_corrections` | Payroll corrections | Cleared |
| `hr_payroll_entries` | Payroll entries | Cleared |
| `hr_payroll_entry_lines` | Payroll entry lines | Cleared |
| `hr_payroll_periods` | Payroll periods | Cleared |
| `invoice_lines` | Sales invoice lines | Cleared |
| `invoices` | Sales invoices | Cleared |
| `lead_activities` | Lead activity log | Cleared |
| `leads` | Leads | Cleared |
| `opening_balances` | Opening balances | Cleared |
| `payment_allocations` | Payment-to-invoice allocations | Cleared |
| `payments` | Receipts and payments | Cleared |
| `print_logs` | Document print log | Cleared |
| `purchase_invoices` | Purchase invoices | Cleared |
| `purchase_order_lines` | Purchase-order lines | Cleared |
| `purchase_orders` | Purchase orders | Cleared |
| `sales_order_lines` | Sales-order lines | Cleared |
| `sales_orders` | Sales orders | Cleared |
| `statutory_challans` | Statutory payment challans | Cleared |
| `stock_movements` | Stock ledger | Cleared |
| `voucher_lines` | Accounting voucher lines | Cleared |
| `vouchers` | Accounting vouchers | Cleared |

### 6.3 Schema bookkeeping (1)

| Table | Purpose | Status |
|---|---|---|
| `alembic_version` | Installed revision | Never cleared; a business reset leaves it so Alembic still knows the revision |

**Guard:** `table_classification()` exists so a test fails if a new table appears in neither list (`db_reset.py:109-116`). Adding the two WP-4 tables to KEEP was therefore a required edit at activation, and the suite would have failed until it was made — as the design says. **Done on 4 November 2026:** `nav_nodes` and `feature_registry` were added to `KEPT_TABLES` in the same change that renamed the draft to `.py`, before the suite ran.

**Count after activation:** 46 CLEAR + **43 KEEP** + 1 SCHEMA = **90 tables** on `herbanova_bcs_dev` (measured 16/16 in `var/reports/wp4a-activation-verify.json`). Before activation the classification was 46 + 41 + 1 = 88.

---

## 7. The five approval questions

### Q1. Is Module → Category → Group → Feature correct, and does it map every existing screen?

**Yes for navigation, with two corrections and one gap.**

1. The fourth level is a **Screen**, not a Feature. Module → Category → Group → Screen is correct (5 → 14 → 20 → 25). Feature is a separate, many-to-one attribute on the screen (`feature_key`). Making Feature a level would imply one screen per feature and would not fit 14 features to 25 screens (22 feature views including the alias).
2. All **25** existing screens map: 25 titles, 25 nodes, 0 missing titles. `distributors` is an alias, not a node. `expenses` and `roles` acquire feature ownership in the seed (`accounts`, `users`), closing D-01. `dash` and `settings` remain featureless by design.
3. **Not mapped:** the 19 accounting sub-sections. They must stay code-driven in 4a–4c; 4d needs a decision (G-01).

### Q2. Are all four tables necessary, and why can they not reuse existing tables?

**Answer after the correction pass: two are built in 0031 (`nav_nodes`, `feature_registry`); `nav_aliases` is eliminated; `user_favourites` is deferred.**

| Table | Necessary? | Why it cannot reuse an existing table |
|---|---|---|
| `nav_nodes` | **Yes, built in 0031** — database-managed navigation is the point of WP-4/WP-5 | There is no navigation table today. The menu lives in `workspace.js` `NAV`; `/api/modules` is a hardcoded delivery register in code, not a table. |
| `nav_aliases` | **No — eliminated** | One row (`distributors`) does not justify a table. It is a JSON `aliases` array on the `customers` node, resolved before routing. |
| `feature_registry` | **Yes, built in 0031** | `feature_flags` is the sparse switch state (absent = ON) and holds no ownership mapping. Adding columns would alter an existing table and would lose ownership for features with no flag row. |
| `user_favourites` | **No, not in 0031 — deferred to 0032 contingent on D8** | `hr_saved_filters` is a per-view, named, parameterised filter owned by HR and cleared by a business reset; it cannot represent ordered, unnamed screen pins. But nothing reads favourites server-side before 4d, and D8 is unapproved, so creating the table now would be speculative. |

### Q3. Exact KEPT_TABLES classification

See §6: **46 CLEAR + 43 KEEP + 1 SCHEMA = 90** after activation (88 before), every table named with its purpose and business-data status. `nav_aliases` and `user_favourites` were not created, so WP-4 added exactly two tables — `nav_nodes` and `feature_registry` — to KEEP. Both are configuration and reference no kept parent by foreign key, so a business reset leaves them intact and no CLEAR table references them. The edit was made at activation, in the same change as the rename, because `_kept_snapshot` at `tests/test_db_reset.py:544` counts every KEEP table and would have failed on a name that did not yet exist.

### Q4. Safest batch order, with migration, seed, API, frontend and rollback per batch

| Batch | Migration | Seed | API | Frontend | Rollback | Stop point |
|---|---|---|---|---|---|---|
| **4a** | `0031_navigation_registry`, down_revision `0030_sign_in_content`; **two** tables, indexes, checks; full downgrade | Literal rows from a committed generator: 5 modules / 14 categories / 20 groups / 25 screens (**64 nodes**), 14 features, 1 alias; add **two** tables to KEEP at activation | none | none | `alembic downgrade 0030_sign_in_content`; revert KEEP edit | Prove upgrade → downgrade → upgrade on the test DB; row counts 64 / 14 / 1 Home / 1 alias; parity and validation tests; `test_feature_switches` green **after R-01 is resolved** |
| **4b** | none | none | `GET /api/navigation` (filtered, ordered), `GET /api/admin/navigation` (read-only) | none | revert the router include | Role diff for four seeded roles reports zero differences against `workspace.js`; 503 path tested; ETag changes when a feature is switched off |
| **4c** | none | none | favourites endpoints if approved | opt-in `?nav=api`/setting; fallback to `workspace.js` | switch off (default stays `workspace.js`) | Side-by-side 1440/768/390 both themes; forced 503 proves fallback; console clean; sections still render (G-01) |
| **4d** | none | import device favourites once (if approved) | API becomes default; server favourites replace `localStorage` (**needs 0032 `user_favourites` if D8 is approved**) | default flip; `workspace.js` constants stay as fallback | flip default back; keep server rows | Full browser walk, keyboard, permissions, manual, CHANGELOG |

Preconditions before 4a: owner answers design §12; **R-01 is resolved in the design (done in this pass)**; WP-2/WP-3 committed or checkpointed (they are currently uncommitted); a verified database dump; `alembic current` recorded. Each batch is a separate approval and a separate stop.

### Q5. Recommended target environment and promotion sequence

1. **Test (`herbanova_bcs_test`)** — first. The suite drops and rebuilds it, so it is disposable. Run `upgrade → downgrade → upgrade` and the full suite here. Nothing is promoted on the strength of this step alone.
2. **A restored copy of the development database** — second, not the live development database. Restore the pre-4a dump into an isolated instance, apply 0029 → 0030 → 0031 if the copy predates them, run the API diff and the browser walk against it. This also rehearses the production gap.
3. **Development (`herbanova_bcs_dev`, currently `0030`)** — after the restored copy passes and a fresh verified dump exists. Apply 0031 only; 0029/0030 are already present. Re-walk the four seeded roles.
4. **Staging** — this repository documents no staging host. If one exists, promote to it next; if not, use a **restored production dump on an isolated instance** as the staging step. Do not treat development as staging.
5. **Production (currently `0028_advances`)** — last, in a maintenance window, after a verified dump and after the restored production copy has passed 0029 → 0030 → 0031. Roll back to `0030` if 0031 fails; never attempt 0031 before 0029/0030 are proven on the copy. Keep the previous SPA so the browser falls back to `workspace.js`.

No step in this sequence was performed in this review.

---

## 8. Go / no-go

**GO for batch 4a only, conditional on C1–C6.** → **Met and executed on 4 November 2026.**
**NO-GO for batches 4b, 4c and 4d** until each is separately approved. *(Historical: all three were later approved and activated — see [WP4_RELEASE_READINESS.md](WP4_RELEASE_READINESS.md).)*

| # | Condition | State after activation |
|---|---|---|
| **C1** | The owner records the decisions in design §12 (hierarchy, **two** tables, KEEP classification, batch order, target environment). | **Met.** The owner approved Batch 4a activation by explicit instruction on 4 November 2026, naming the development/test environment and prohibiting production. |
| **C2** | **R-01 is resolved before the migration file is written.** | **Met.** No FK to `feature_flags`; `feature_key` validated against `FEATURES`; five R-01 tests pass against PostgreSQL. |
| **C3** | WP-2/WP-3 are committed or checkpointed and a verified dump is taken. | **Met.** Source checkpoint `var/backups/wp4a-activation-20261104T082147Z/` (diff, stat, 20-file archive, checksums); database dump verified by restore into a scratch database (941 archive entries, 88 tables, 891 rows, identical revision and columns). Nothing committed or pushed. |
| **C4** | Design §7 gains the validation rules: `route == "#/" + view`, `component_key == view`, one protected Home, sections out of scope, plus the rest of the §4 list. | **Met.** Design §7 lists sixteen rules, all implemented in `validate_catalog` and tested. |
| **C5** | The ETag input includes the enabled-feature set and a registry version, so a feature switch cannot serve a stale 304 (R-07). | **Met in design and code.** `navigation_etag()` hashes the registry fingerprint, permissions, enabled features, favourites and recent. |
| **C6** | 4a evidence includes upgrade → downgrade → upgrade on the test DB, row counts, the parity test re-reading `workspace.js`/`features.py`, and a green `test_feature_switches.py` after the C2 change. | **Met twice.** Rehearsal: 13/13 steps on a scratch database, 31 gated tests passed. Activation: `0031` applied to `herbanova_bcs_dev` from `0030`, 16/16 verification checks, 78 seed rows, 90 tables, no business row or column changed; `test_feature_switches.py` green in the full 499-test suite. Evidence in §14 and `var/reports/wp4a-activation-*`. |

Nothing in the design requires changing an existing table, dropping a column, rewriting a row or touching production settings. With C1–C6 met, the risk of 4a is confined to two new, empty tables and a seed.

---

## 9. Outstanding issues recorded outside this review

| # | Issue | Owner action | State |
|---|---|---|---|
| O-01 | `PROJECT_ARCHITECTURE.md` and `NAVIGATION_AND_TAB_DESIGN.md` quoted 341 routes, the 467-test baseline and HEAD `eaf38d2`. | Correct in the WP-4 pass. | **Done** — both corrected to 344 `APIRoute`s / 268 paths, the current test count and HEAD `77f5a96`. |
| O-02 | The design's 348-route figure is an overcount of four (R-02). | Correct §1. | **Done** — §1 reads 344 / 268 / 229 / 39. |
| O-03 | No staging host is documented; the restored-production-copy step stands in for it. | Confirm the host, if one exists. | Open — owner. |
| O-04 | Production is at `0028`; it cannot run the current application until 0029 and 0030 are applied. | Plan the ordered promotion; do not combine it with 0031. | Open — owner; sequence documented in design §10. |
| O-05 | Device-local favourites remain device-local until 4d (D8). This is a recorded deviation, not a defect. | Approve or defer in §12. | Open — owner; `user_favourites` deferred to 0032. |
| O-06 | The 19 accounting sub-sections are not in the registry (G-01/R-05). | Decide before 4d: keep in code or add a section table. | Open — owner; recorded out of scope for 4a–4c. |

---

## 10. Files and state

**Documents written or updated in this pass**

- `docs/FEATURE_REGISTRY_DESIGN.md` (corrected: two tables, R-01 resolved, sixteen validation rules, migration sequence, owner decisions)
- `docs/WP4_APPROVAL_READINESS.md` (this file, correction pass applied)
- `docs/VERIFICATION_REPORT.md` (new §32; historical §30/§31 left intact)
- `docs/IMPLEMENTATION_ROADMAP.md` (WP-4 status)
- `docs/PROJECT_ARCHITECTURE.md`, `docs/NAVIGATION_AND_TAB_DESIGN.md` (route counts and HEAD corrected)

**Batch 4a source, activated 4 November 2026**

- `alembic/versions/0031_navigation_registry.py` — active; discovered by Alembic, revision `0031_navigation_registry`, down_revision `0030_sign_in_content`
- `app/models/navigation.py` — `NavNode`, `FeatureRegistry`; imported from `app/models/__init__.py`
- `app/services/navigation_catalog.py` — canonical catalogue; no DB import
- `app/services/navigation_registry.py` — validation, visibility, fingerprint, ETag
- `scripts/generate_navigation_seed.py` — `--check`/`--write` seed generator (reads the active file)
- `scripts/navigation_parity_report.py` — machine-readable catalogue/frontend parity report
- `scripts/verify_navigation_migration.py` — scratch-DB upgrade/downgrade/re-upgrade; dry-run by default
- `tests/test_navigation_registry.py`, `tests/js/emit_nav_manifest.cjs`
- `app/services/db_reset.py` — `nav_nodes` and `feature_registry` added to `KEPT_TABLES`

**Review and rehearsal evidence written under `var/` (not application code)**

- `var/reports/wp4r-audit.json`, `wp4r-tables.json`, `wp4r-hierarchy.json`
- `var/reports/wp4r-pytest.xml`, `wp4r-pytest.log`, `wp4r-node.log`
- `var/reports/wp4r-browser.json`, `wp4r-browser.log`, `wp4r-wp2walk.json`
- `var/reports/wp4a-catalogue-parity.json`
- `var/reports/wp4a-migration-rehearsal.json`, `wp4a-migration-rehearsal.log`
- `var/reports/wp4a-gated-tests.xml`, `wp4a-gated-tests.log`, `wp4a-gated-tests.json`
- Activation: `var/reports/wp4a-activation-upgrade.log`, `wp4a-activation-verify.json`, `wp4a-activation-pytest.xml`/`.log`, `wp4a-activation-targeted.xml`/`.log`, `wp4a-activation-node.log`, `wp4a-activation-browser.json`/`.log`, `wp4a-activation-browser-routes.json`, `wp4a-activation-dev-api.json`
- Activation checkpoint: `var/backups/wp4a-activation-20261104T082147Z/` (`tracked.diff`, `tracked.stat`, `untracked.tar.gz`, `untracked.txt`, `checksums.txt`, `git-status.txt`, `herbanova_bcs_dev.dump`, `backup.json`, `restore-verify.log`)
- `var/review/audit.py`, `var/review/tables.py`, `var/review/wp4walk.py`
- `var/backups/wp4-review-20261104T122641/`

**Working tree: 43 entries (24 modified, 19 untracked)**

Modified (24): `app/api/approvals.py`, `app/api/distributors.py`, `app/api/invoices.py`, `app/api/products.py`, `app/api/purchase_orders.py`, `app/api/sales_orders.py`, `app/api/suppliers.py`, `app/core/pagination.py`, `app/models/__init__.py`, `app/services/db_reset.py`, `docs/DESIGN_SYSTEM.md`, `docs/FEATURE_INVENTORY.md`, `docs/FRONTEND_BACKEND_FIELD_MAPPING.md`, `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md`, `docs/VERIFICATION_REPORT.md`, `docs/user-manual/00-quick-start.md`, `docs/user-manual/07-products.md`, `docs/user-manual/11-sales-orders.md`, `docs/user-manual/README.md`, `static/css/styles.css`, `static/index.html`, `static/js/app.js`, `tests/test_products.py`, `tests/test_profit_loss.py`.

Untracked (19 entries): `alembic/versions/0031_navigation_registry.py`, `app/models/navigation.py`, `app/services/navigation_catalog.py`, `app/services/navigation_registry.py`, `scripts/generate_navigation_seed.py`, `scripts/navigation_parity_report.py`, `scripts/verify_navigation_migration.py`, `tests/test_navigation_registry.py`, plus the previously untracked `docs/CHANGELOG.md`, `docs/FEATURE_REGISTRY_DESIGN.md`, `docs/IMPLEMENTATION_ROADMAP.md`, `docs/NAVIGATION_AND_TAB_DESIGN.md`, `docs/PROJECT_ARCHITECTURE.md`, `docs/WP4_APPROVAL_READINESS.md`, `pytest.ini`, `static/js/workspace.js`, `tests/js/` (a directory holding both `workspace.test.cjs` and `emit_nav_manifest.cjs`), `tests/test_list_standard.py` and `tests/test_workspace_model.py`.

No business table, business row or production setting was changed by activation. The application's routes, permissions, feature switches and screens were not altered; the registry is additive and has no caller yet (batch 4b). `/api/navigation` remains unimplemented (404), as required for 4a. **Superseded:** Batch 4b implemented both navigation endpoints and Batch 4d made the server menu the default; see [WP4_RELEASE_READINESS.md](WP4_RELEASE_READINESS.md).

---

## 11. Correction pass (4 November 2026)

What changed between the approval-readiness review and this pass, and why.

| Area | Before | After | Evidence |
|---|---|---|---|
| Feature FK | `feature_registry.feature_key` and `nav_nodes.feature_key` → `feature_flags.key` (no cascade) | Plain `String(32)`, validated against `FEATURES` | `tests/test_navigation_registry.py`; `test_registry_has_no_foreign_key_to_feature_flags` |
| Table count | Four | **Two** (`nav_nodes`, `feature_registry`) | One alias folded into `nav_nodes.aliases`; favourites deferred to 0032 |
| Route count | 348 / 267 / 38 | **344 / 268 / 39** | `len(app.routes) = 349` = 344 APIRoutes + 4 framework Routes + 1 `/ui` Mount; root `/` added to the path count |
| Validation | §7 list without drift, Home or alias rules | **Sixteen rules**, all implemented in `validate_catalog` | `app/services/navigation_registry.py` |
| ETag | version + user + permission hash | **+ enabled features + favourites + recent + registry fingerprint** | `navigation_etag()` |
| Recents | audit `view.open` rows | **No audit rows**; recents deferred to a separate mechanism | design §6.1 |
| KEPT edit | "add four now" | **Two at activation**, deferred because `_kept_snapshot` counts every KEPT table | `tests/test_db_reset.py:544` |

**Test results:** `tests/test_navigation_registry.py` — **28 passed, 3 skipped** (the three skipped are the DB-backed checks, gated on the migration being active). Full suite: **496 passed, 3 skipped, 0 failed in 225.06 s**, exit 0 (`var/reports/wp4c-pytest.xml`); 18 Node tests pass. Details in `docs/VERIFICATION_REPORT.md` §32. The seed literal was verified equal to `build_nodes()`/`build_features()` (`--check`: 78 rows), and `validate_catalog` returns 0 errors over the 64 nodes and 14 features. `scripts/verify_navigation_migration.py` was run in dry-run mode only; it printed the exact chain `0028_advances → 0031_navigation_registry → 0030_sign_in_content → 0031_navigation_registry` and did not touch a database.

**Rehearsal results (later the same day):** the same file now also runs **31 passed, 0 failed, 0 skipped** in an isolated copy where the draft is active. The repository keeps its 28 passed / 3 skipped split, because the three gates correctly remain closed here. The rehearsal script ran all 13 steps with 0 failures. See §13.

---

## 12. Reproduce this review

```bash
# read-only measurements (refuse a non-test database)
python var/review/audit.py
python var/review/tables.py

# Batch 4a, no database access
python scripts/generate_navigation_seed.py --check      # seed literal vs catalogue
python scripts/navigation_parity_report.py              # 11 checks; writes wp4a-catalogue-parity.json
python -m pytest tests/test_navigation_registry.py -q   # 31 passed after activation (was 28 passed, 3 skipped)
python scripts/verify_navigation_migration.py           # dry run; prints the chain only

# Batch 4a rehearsal (authorised 4 November 2026; scratch databases only)
python scripts/verify_navigation_migration.py --run     # creates, rehearses and drops herbanova_nav_migration_scratch_test
python var/reports/run_gated_tests.py                   # isolated copy; creates and drops herbanova_nav_rehearsal_test
# Neither command touches dev, test, staging or production; each uses a fixed *_test name it creates and drops.

# automated suites
node --test tests/js/workspace.test.cjs
python -m pytest -q -rs

# browser walk (three processes; test database only)
python var/probe/serve_test.py                                  # :8011
python scripts/run_frontend.py --port 3011 --backend http://127.0.0.1:8011
# headless Chrome with a throwaway profile exposing CDP on :9223
python var/review/wp4walk.py
```

The browser command needs a Chrome binary path, which is machine-specific and deliberately not committed. The three server/walk scripts refuse to run against a database whose name does not end in `_test`.

---

## 13. Batch 4a migration rehearsal (4 November 2026)

Authorised scope: rehearsal only, on newly created disposable scratch databases. No development, test, staging or production database was written; the draft was not renamed; `/api/navigation` and frontend navigation were not touched; nothing was committed or pushed.

### 13.1 Repository preserved

`feature/gap-closure` at `77f5a96e4182af7a67eea95405d4c03fc66820e6`, 41 working-tree entries (22 modified, 19 untracked) before and after. The draft's SHA-256 is unchanged at `6d6328a5aadf078d982c8ad9585c78c075ba85089d6def6f2405de8aae27e891`; `alembic/versions/0031_navigation_registry.py` did not exist before or after. No reset, clean, checkout, rebase, commit or push.

### 13.2 The three formerly skipped tests

They were executed for real in an isolated copy of `app/`, `alembic/`, `tests/`, `scripts/`, `alembic.ini`, `pytest.ini` and the two JavaScript files, with the draft copied to an active `.py` **in the copy only** and `tests/conftest.py` repointed from `herbanova_bcs_test` to `herbanova_nav_rehearsal_test`. The repository copy was never altered.

| Test | Needs a database? | What it proves | Rehearsal result |
|---|---|---|---|
| `test_migration_seed_matches_the_catalogue` | **Yes** — it reads the seeded rows back from PostgreSQL and compares them to `build_nodes()`/`build_features()` | The rows written by the migration are exactly the canonical catalogue | **pass** |
| `test_deleting_every_switch_row_leaves_the_registry_intact` | **Yes** — it deletes real `feature_flags` rows and reads `nav_nodes`/`feature_registry` | R-01: the registry has no FK to the sparse switch table; removing every switch row neither errors nor removes registry rows | **pass** |
| `test_downgrade_and_reupgrade_are_covered_by_the_verify_script` | **No** — it is a static contract test over the migration source and the verify script | The migration defines a complete downgrade and the script covers upgrade → downgrade → re-upgrade | **pass** (documented as not needing a database; gated only with the migration evidence) |

Result: **31 passed, 0 failed, 0 skipped** in 4.12 s (`var/reports/wp4a-gated-tests.xml`). `var/reports/wp4a-gated-tests.json` records `existed_before: false`, `dropped: true`, `exists_after: false`, `isolated_from_repo: true`, `draft_kept: true`. The repository still reports 28 passed / 3 skipped because the draft is inactive there — the gates are honest, not bypassed.

### 13.3 Catalogue parity — 11/11

`python scripts/navigation_parity_report.py` → `var/reports/wp4a-catalogue-parity.json`.

| Check | Result |
|---|---|
| `counts` | 5 modules, 14 categories, 20 groups, 25 screens, 14 features, **78 seed rows** |
| `catalogue_valid` | `validate_catalog` reports 0 errors |
| `seed_literal_matches_catalogue` | draft literal equals `build_nodes()`/`build_features()` |
| `no_duplicates` | 0 duplicate node keys, 0 duplicate routes, 0 duplicate sibling sort keys |
| `no_orphans` | 0 orphan parents, 0 orphan feature keys |
| `permissions_known` | all 17 nav permission keys and all 49 feature permission keys exist in the backend catalogue |
| `routes_and_menu` | 25 routes match `workspace.js`; the four `NOT_IN_MENU` screens are encoded |
| `view_permission_feature_menu_maps` | every view's permissions, feature and menu rule match the frontend, including the four OR rules |
| `distributors_alias` | `distributors → sales/parties/customer-master/customers`, stored once as the alias, not as a node |
| `accounts_sections` | all **19** accounting sub-sections remain reachable through code-driven navigation (`ACC_SECTIONS`, `state.view === "accounts"`) |
| `home` | exactly one Home, `overview/dashboard/workspace/dash`, route `#/dash` |

### 13.4 The 13 rehearsal steps — 13/13 pass

`python scripts/verify_navigation_migration.py --run` → `var/reports/wp4a-migration-rehearsal.json`; scratch database `herbanova_nav_migration_scratch_test` (PostgreSQL 17.11), created and dropped in the same run.

| # | Step | Result |
|---:|---|---|
| 1 | `create_database` | created, server 17.11 |
| 2 | `temp_alembic` | draft activated only inside a temporary script directory |
| 3 | `upgrade_0028_advances` | `0028_advances`, 2.177 s |
| 4 | `upgrade_0029_totp` | `0029_totp`, 1.369 s |
| 5 | `upgrade_0030_sign_in_content` | `0030_sign_in_content`, 1.381 s |
| 6 | `upgrade_0031_navigation_registry` | `0031_navigation_registry`, 1.469 s |
| 7 | `verify_seed` | 64 nodes + 14 features = 78 rows, 1 Home, 1 alias; rows equal the catalogue; 0 validation errors |
| 8 | `verify_schema` | 6 nav indexes + 1 feature index; 11 nav constraints + 2 feature constraints; self-FK `ON DELETE RESTRICT`; sequence at 64; 6 write probes behaved |
| 9 | `downgrade_0030` | `0030_sign_in_content`; removed exactly `nav_nodes`, `feature_registry`; added none |
| 10 | `reupgrade_0031` | `0031_navigation_registry`; same 78 rows and 1 Home; 0 orphans/duplicates |
| 11 | `business_data_unchanged` | 88 pre-existing tables: no row-count change, no column change |
| 12 | `r01_five_behaviours` | 5/5 pass on PostgreSQL |
| 13 | `drop_database` | removed; `exists_after_drop: false` |

### 13.5 Business-data safety

| Measure | At `0030` | At `0031` |
|---|---:|---:|
| Revision | `0030_sign_in_content` | `0031_navigation_registry` |
| Tables | 88 | 90 |
| Total rows across pre-existing tables | 64 (12 migration-seeded tables, e.g. `roles` 8, `feature_flags` 13, `ledger_accounts` 11) | 142 = 64 unchanged + 78 seeded rows |
| Database size | 13,588,147 B | 13,776,563 B |

Only `nav_nodes` and `feature_registry` appear; nothing is removed. Classification on the scratch DB: 46 CLEAR + 41 KEEP + 1 SCHEMA = 88, with the two new tables reported as unclassified/new, which is exactly the KEPT edit activation requires. `tables_added_by_0031: [feature_registry, nav_nodes]`, `tables_removed_by_0031: []`, `other_tables_unchanged: true`, `row_count_changes: {}`, `columns_changed: []`.

### 13.6 R-01 on the scratch database — 5/5

| Check | Result |
|---|---|
| A registered feature with no switch row reads as ON | pass |
| Disabling the `hr` switch hides `hr` screens but keeps all 64 node rows and 14 registry rows | pass |
| Deleting **every** `feature_flags` row causes no FK error and leaves the registry intact | pass |
| An unknown `feature_key` is rejected by validation | pass |
| Registry membership neither enables nor disables a switch | pass |

Schema proof: the only foreign key in either new table is `nav_nodes.parent_id → nav_nodes.id` (`ON DELETE RESTRICT`). There is **no** FK to `feature_flags.key`; `feature_flags` still has 0 incoming FKs.

### 13.7 Rollback proof

Upgrade → downgrade → re-upgrade: downgrade removed exactly the two tables in 1.349 s with all 88 earlier tables and their columns unchanged; re-upgrade re-created the same 78 rows with 1 Home and 0 orphans/duplicates in 1.397 s; final revision `0031_navigation_registry`. R-01 was re-run after the re-upgrade and passed again.

### 13.8 Evidence

| File | Content |
|---|---|
| `var/reports/wp4a-migration-rehearsal.json` / `.log` | 13 steps, revisions, seed, schema, business snapshot, rollback, classification, R-01, scratch create/drop |
| `var/reports/wp4a-catalogue-parity.json` | 11 parity checks with counts and evidence |
| `var/reports/wp4a-gated-tests.xml` / `.log` / `.json` | 31 passed; isolated copy; database created and dropped |
| `var/reports/run_gated_tests.py` | the isolated-copy harness (git-ignored under `var/`) |
| `docs/VERIFICATION_REPORT.md` §33 | rehearsal narrative |

### 13.9 Verdict at rehearsal time (superseded by §14)

At rehearsal time Batch 4a was **technically safe to activate** but not authorised. That is no longer the current state: the owner approved activation on 4 November 2026 and §14 records the execution.

---

## 14. Batch 4a activation record (4 November 2026)

Authorised scope: activate Batch 4a only, on the approved development/test environment, after a verified checkpoint and dump. Production, staging, batches 4b–4d, `/api/navigation` and frontend navigation were out of scope.

### 14.1 Repository checkpoint

| Item | Value |
|---|---|
| Branch / HEAD | `feature/gap-closure` / `77f5a96e4182af7a67eea95405d4c03fc66820e6`, unchanged before and after |
| Checkpoint directory | `var/backups/wp4a-activation-20261104T082147Z/` |
| Tracked changes | `tracked.diff` (251,166 B) and `tracked.stat` |
| Untracked changes | `untracked.txt` (20 files) and `untracked.tar.gz` (106,453 B, 20 entries) |
| Integrity | `checksums.txt` over `tracked.diff` and `untracked.tar.gz`; the dump hash is in `backup.json`; `git-status.txt` at capture time |
| Destructive commands | none — no reset, clean, checkout, rebase, commit or push |

### 14.2 Database backup and restore proof

| Item | Value |
|---|---|
| Database | `herbanova_bcs_dev` at `0030_sign_in_content` |
| Dump | `herbanova_bcs_dev.dump`, `pg_dump -Fc --no-owner --no-privileges`, 406,720 B, 941 archive entries |
| SHA-256 | `eeaba325bf99a2ec69a2f286a5dce31fd64d20072096a9f58d7adae0637a2499` |
| Restore test | restored into `herbanova_restore_check_20261104t082247z_test`; revision, table names, row counts and column counts all equal to source (`equals_source` true on all three) |
| Totals at backup | 88 tables, 891 rows |
| Verified at | 2026-11-04T08:22:50Z; scratch restore database dropped afterwards |
| Evidence | `backup.json`, `restore-verify.log` in the checkpoint directory |

### 14.3 Activation edits and chain

| Edit | File | Result |
|---|---|---|
| Draft renamed to active | `alembic/versions/0031_navigation_registry.py` | discovered by Alembic; docstring now states the activation date and target |
| Two tables kept by a business reset | `app/services/db_reset.py` | `nav_nodes`, `feature_registry` in `KEPT_TABLES`; 46 CLEAR + 43 KEEP + 1 SCHEMA = 90 |
| Models imported | `app/models/__init__.py` | `navigation` imported so metadata sees both tables |
| Path resolution after rename | `scripts/generate_navigation_seed.py`, `scripts/navigation_parity_report.py`, `scripts/verify_navigation_migration.py`, `tests/test_navigation_registry.py` | load the active `.py` if present, else the `.draft`; no behaviour depends on which exists |

Chain verified before execution: `0028_advances → 0029_totp → 0030_sign_in_content → 0031_navigation_registry`, a single head. **Target confirmed as `herbanova_bcs_dev`** (the database URL parsed and asserted to end in `_dev`); the command refused to run against any other name. `alembic upgrade 0031_navigation_registry` exited 0 (`var/reports/wp4a-activation-upgrade.log`).

### 14.4 Migration result — 16/16 checks

`var/reports/wp4a-activation-verify.json`, measured on `herbanova_bcs_dev` at 2026-11-04T08:26:32Z:

| Check | Result |
|---|---|
| Revision is `0031_navigation_registry` | pass |
| Exactly two tables added (`feature_registry`, `nav_nodes`); none removed | pass, 90 tables total |
| `nav_nodes` rows = 64; `feature_registry` rows = 14; total seed = 78 | pass |
| Exactly one Home: `#/dash`, depth 4, featureless, guarded by `ux_nav_nodes_home` | pass |
| 6 `nav_nodes` indexes + 1 `feature_registry` index present | pass |
| 11 `nav_nodes` constraints + 2 `feature_registry` constraints present | pass |
| Only foreign key is `nav_nodes.parent_id → nav_nodes.id` `ON DELETE RESTRICT` | pass |
| No incoming foreign key to `feature_flags` (R-01) | pass |
| All 14 feature keys and all node keys are known to the catalogue | pass |
| Seeded rows equal `build_nodes()` / `build_features()` exactly | pass |
| Catalogue validation returns 0 errors | pass |
| Business rows unchanged (`changed_rows: {}`); no business table removed | pass |

Database size after activation: 15,529,651 B (13,776,563 B on the rehearsal scratch DB at the same revision).

### 14.5 Full test evidence

Serial runs, no concurrent pytest sharing a database. The session fixture rebuilds `herbanova_bcs_test` from migrations, so the test database was created, upgraded through `0031`, used and left at `0031`.

| Run | Command | Result |
|---|---|---|
| Full Python suite | `python -m pytest -q -rs --junitxml=var/reports/wp4a-activation-pytest.xml` | **499 passed, 0 failed, 0 skipped**, 695 warnings, 204.86 s, exit 0 |
| Navigation and registry-sensitive subset | `pytest tests/test_navigation_registry.py tests/test_db_reset.py tests/test_feature_switches.py tests/test_permission_tree.py tests/test_roles_parity.py` | **83 passed, 0 failed, 0 skipped**, 114.53 s, exit 0 (31 registry + 24 reset + 10 feature switch + 11 permission tree + 7 role parity) |
| Node workspace model | `node --test tests/js/workspace.test.cjs` | **18 passed, 0 failed, 0 skipped**, 93.7 ms |
| Migration/seed parity | `python scripts/navigation_parity_report.py` | **11/11** checks, 0 failed |
| Seed literal drift | `python scripts/generate_navigation_seed.py --check` | current, 78 rows |

The 499 total is three more than the pre-activation 496 because the three formerly skipped DB-gated tests now execute; no test was skipped, weakened or removed. JUnit XML totals: `tests="499" errors="0" failures="0" skipped="0" time="204.851"`.

### 14.6 Application verification

| Area | Evidence | Result |
|---|---|---|
| Login and permissions unchanged | `wp4a-activation-dev-api.json` | admin 49 permissions, viewer 5; `/api/auth/me` 200 for both; viewer receives 403 on `/api/features` and `/api/roles` exactly as before |
| Existing routes | same probe, GET-only against `:8000` | 35/35 checks pass: health, modules, features (14), eight WP-3 lists, 19 accounting GET endpoints, and `/api/navigation` **404** (at 4a; implemented in 4b — see [WP4_RELEASE_READINESS.md](WP4_RELEASE_READINESS.md)) |
| WP-3 eight lists | same probe | Products 5, Suppliers 3, Customers 5, Sales orders 5, Purchase orders 5, Billing 4, Approvals 5, Leads 3 items returned; no list contract changed |
| 19 accounting sub-sections | `wp4a-activation-browser-routes.json` | **19/19** load `v-accounts` with their own hash and active tab; e.g. `#/accounts/gst-out` → tab `accounts/gst-out`, breadcrumb "GST outward" |
| `distributors` alias | same probe | `#/distributors` renders `v-customers` with the Customers tab active and breadcrumb |
| Home | same probe | `#/dash` renders `v-dash` with the Home tab active |
| WP-2 tabs and breadcrumbs | `wp4a-activation-browser.json` (re-run on the rebuilt test DB) | **113/113**: WP-2 replay 42/42, 21st-tab flow 20/20, eight lists 51/51 |
| 64 nodes / 14 features / 25 screens | registry tests and activation verify | 64 + 14 = 78 rows; 25 screens and 14 features match the catalogue |
| No business change on dev | `wp4a-activation-verify.json` | `changed_rows: {}`, `removed_tables: []`, only `feature_registry` and `nav_nodes` added |

`/api/navigation` was deliberately **not** implemented and the frontend navigation was **not** switched to the registry; those are batch 4b and later.

### 14.7 Rollback

Rollback is additive and rehearsed on a scratch database (§13.7):

```bash
# 1. revert the schema on the same approved database
alembic downgrade 0030_sign_in_content
# 2. revert the code edits that assumed the tables exist
#    - remove nav_nodes / feature_registry from KEPT_TABLES in app/services/db_reset.py
#    - remove the navigation import from app/models/__init__.py
#    - delete or re-draft alembic/versions/0031_navigation_registry.py
# 3. restore the checkpoint if a full application rollback is required
#    var/backups/wp4a-activation-20261104T082147Z/ (tracked.diff + untracked.tar.gz)
```

The dump `herbanova_bcs_dev.dump` restores the exact pre-activation state (88 tables, 891 rows, revision `0030_sign_in_content`) and was verified before the upgrade. No business row was written by `0031`, so a schema-only downgrade loses nothing but the 78 seeded configuration rows.

### 14.8 Outstanding risks and decisions

| # | Risk / decision | State |
|---|---|---|
| A-01 | Production is still at `0028_advances`; it cannot run the current application. Promotion needs 0029 → 0030 → 0031 in order, a verified dump and a restored-copy rehearsal. | Open — owner; not part of this approval |
| A-02 | The registry has no caller until 4b; it is inert configuration in development. A future change to `workspace.js` must update the catalogue or parity fails. | Guarded by `tests/test_navigation_registry.py` and the parity report |
| A-03 | The 19 accounting sub-sections remain code-driven (G-01), unchanged by 4a. | Open — decide before 4d |
| A-04 | Device-local favourites remain until 4d (D8); `user_favourites` is not created. | Open — owner |
| A-05 | A business reset keeps both registry tables; the suite proves classification but no reset was executed against development in this pass. | Covered by `tests/test_db_reset.py` (24 passed) |
| A-06 | Nothing is committed or pushed; all 43 working-tree entries remain local. | Open — owner action |

### 14.9 Status

**Batch 4a: DONE and verified in development.** Migration `0031_navigation_registry` is active in the repository and applied to `herbanova_bcs_dev`; both tables are in `KEPT_TABLES`; the full suite and browser evidence are green; no business data changed.

**Batches 4b, 4c and 4d: NOT STARTED.** `/api/navigation` does not exist, the frontend still renders from `workspace.js`, and no favourites endpoint or default flip has been written.

**Production: NOT TOUCHED.** Still `0028_advances`; deployment, commit and push each require separate explicit approval.

**STOP:** Batch 4a is activated and verified. Work stops here pending separate approval for 4b or for production promotion. Nothing was committed or pushed.
