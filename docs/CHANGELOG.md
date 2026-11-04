# Changelog

Started 4 November 2026 at the owner's direction (roadmap §1). Earlier history
is in `git log`; this file records delivered work packages from WP-2 onward.
Every entry states what changed, what it did **not** change, and how it was
verified. Uncommitted work is marked as such.

## 4 November 2026 — WP-4 Batch 4d: default server navigation (uncommitted)

**Added**

- `app/services/navigation_catalog.py` — `ADMIN_ONLY_VIEWS = {"scheduled"}`:
  screens whose routes are guarded by `require_admin` rather than by a
  permission alone. The registry can record a permission but not a role, so the
  navigation endpoint must subtract them itself.
- `app/services/navigation_registry.py` — `narrow_admin_only(visible, nodes,
  admin=...)` subtracts those screens for every caller who is not the
  Administrator; `navigation_etag(..., admin=...)` adds Administrator status to
  the ETag identity so a promotion or demotion cannot be answered `304` from the
  old body.
- `tests/test_navigation_parity.py` — **new**, 10 tests. It evaluates the shipped
  `workspace.js` under Node (`tests/js/nav_parity.cjs`) against the real
  `GET /api/navigation` body for the five seeded roles and for **173**
  permission/feature combinations (all gate permissions alone, every pair,
  each feature off, all features off). View and menu sets must be identical,
  with no duplicate and no unknown view; the API set must never exceed the
  built-in set. Two further tests pin Home and the `distributors` alias, and a
  custom role holding `email:manage` must not receive `scheduled`.
- `tests/js/nav_parity.cjs` — the Node harness that runs the shipped model.
- `tests/test_navigation_registry.py` — two tests for the Administrator
  narrowing, plus an ETag assertion that `admin` alone changes the validator.

**Changed**

- `static/js/app.js` — `NAV_API_ENABLED = true`. The server tree is requested on
  sign-in and after a role save for every browser; the built-in,
  permission-filtered menu is drawn while the request is in flight and kept on
  failure with **Retry**; `?nav=builtin` restores the built-in menu for the
  session and `?nav=api` re-opts in. The AND-gate `wsViewOk()` is unchanged, so
  the payload can only hide screens.
- `app/api/navigation.py` — computes `is_admin(db, user)`, applies
  `narrow_admin_only` before pruning empty branches, and passes `admin` to the
  ETag.

**Not changed**

- No migration, table, column, seed row, permission key or business row. No
  route gate was loosened. No server-side favourites. Production was not
  connected to. No commit or push.

**Verified**

- Full suite: **542 passed, 0 failed, 0 errors, 0 skipped** in 237.92 s
  (`var/reports/junit-wp4d.xml`, exit 0); Node **20 passed**; parity **10
  passed** over 173 cases.
- Browser (test-database stack, `var/reports/wp4d-browser.json`): **226/226**
  checks (A=42 WP-2, B=20 21st-tab, C=51 WP-3 lists, D=113 navigation). With no
  query parameter the rail equals the server's `in_menu` set for every role:

  | Role | Built-in menu | Server tree | Server screens | Modules |
  |---|---|---|---|---|
  | Administrator | 21 | 21 | 25 | 5 |
  | Sales | 16 | 16 | 18 | 5 |
  | Inventory | 14 | 14 | 16 | 5 |
  | Viewer | 11 | 11 | 13 | 5 |
  | HR manager | 5 | 5 | 5 | 4 |

  The walk also proves `?nav=builtin` and its persistence, `?nav=api`, all 25
  screens, the keyboard palette, an account switch with a `#/scheduled` deep
  link falling back to Home, breadcrumbs, one tab per accounting section,
  favourites across a reload, the eight WP-3 lists, all 19 accounting
  sub-sections, deep link/refresh/back/forward, 1440/768/390 px in light and
  dark, `200 -> 304`, anonymous `401`, three forced failures (503, network
  rejection, malformed JSON) each recovering through **Retry**, a live
  permission change that removes a screen and closes its tab, and no uncaught
  page errors.
- Defect found and fixed in the probe itself: the walk stored role counts where
  sets were expected and crashed comparing them; it now stores the screen lists
  and prints counts.

**Rollback**

- Set `NAV_API_ENABLED = false` or open the app with `?nav=builtin`; the rail is
  the built-in menu and no server call is needed. To remove the code, revert the
  4d hunks in `static/js/app.js`, `app/api/navigation.py`,
  `app/services/navigation_registry.py` and `app/services/navigation_catalog.py`,
  and delete the two parity files. No data to undo.

## 4 November 2026 — WP-4 Batch 4c: opt-in server navigation (uncommitted)

**Added**

- `static/js/workspace.js` — the active-hierarchy model: `navTree()`,
  `navAllows(view)`, `navInMenu(view)`, `setNavTree`, `resetNavTree` and
  `navFromApi(payload)`. The converter turns the endpoint's Module → Category →
  Group → Screen payload into the one shape the menu, breadcrumbs, palette and
  route gate already read. It drops unknown views and keeps the first place of a
  duplicate, so a bad registry row cannot render an entry the router cannot open
  or list the same screen twice; `null` restores the built-in `NAV`.
- `static/js/app.js` — `NAV_API_ENABLED = false` (release default), the
  `?nav=api` / `?nav=builtin` opt-in persisted in
  `sessionStorage["hb.navApi"]`, the `builtin | loading | ready | error` state,
  a sequence and username guard on every answer, and `navFetch()` /
  `navRefresh()`. `renderSideNav()` now iterates `WS.navTree()`; `wsViewOk()`
  additionally requires `WS.navAllows(view)` while the server tree is active.
  Failure renders an alert in the sidebar's status area (above Favourites),
  keeps the built-in permission-filtered menu and offers **Retry**; it never
  falls back to an unfiltered menu. Login, logout and a role save reset or
  reload the tree.
- `static/css/styles.css` — `.nav-alert` and its mobile placement.
- `app/services/feature_store.py` — `available_keys(db)` is now the single
  answer for the route gate, `/api/auth/me`, the RBAC permission filter and the
  navigation endpoint. It closes `feature_registry.depends_on` over the stored
  switches (fail-closed on a cycle) and falls back to the stored switches when
  the registry tables do not exist. This resolves the dependency-versus-route
  inconsistency the brief required before dependency-based navigation.
- `tests/js/workspace.test.cjs` — two Node tests for the converter and for the
  active tree driving the menu, breadcrumb and route gate (**20 pass**).
- `tests/test_feature_dependencies.py` — five tests: a dependency switch closes
  the dependent module in the API, `/api/auth/me` and navigation; an inactive
  row is hidden everywhere; one answer for every reader; a cycle fails closed;
  the pre-0031 fallback.

**Changed**

- `tests/test_navigation_registry.py` — the stub now returns `FeatureFlag` rows
  only for a `FeatureFlag` select, because `feature_store` reads both tables.
- `tests/test_profit_loss.py` — the source guard follows `renderSideNav()` to
  `WS.navTree().forEach`, the hierarchy shared by the built-in and server menus.

**Not changed**

- No migration, table, column, seed row, permission key or business row. The
  default is off: every browser that opens the app without `?nav=api` renders
  exactly the pre-4c menu. Production was not connected to. No commit or push.

**Verified**

- Full suite: **530 passed, 0 failed, 0 skipped** in 240.37 s
  (`var/reports/wp4c-pytest.xml`); Node **20 passed**.
- Browser (test-database stack, `var/reports/wp4c-browser.json`): **199/199**
  checks (A=42 WP-2, B=20 21st-tab, C=51 WP-3 lists, D=86 navigation). With
  `?nav=api` the rail equals the server's `in_menu` set for every role:

  | Role | Built-in menu | API menu | Server screens | Modules |
  |---|---|---|---|---|
  | Administrator | 21 | 21 | 25 | 5 |
  | Sales | 16 | 16 | 18 | 5 |
  | Inventory | 14 | 14 | 16 | 5 |
  | Viewer | 11 | 11 | 13 | 5 |
  | HR manager | 5 | 5 | 5 | 4 |

  The walk also proves: no screen outside the built-in menu and none twice;
  `private, no-cache` / `Vary: Cookie` / per-user `ETag`; switching Viewer →
  Administrator leaves no stale menu; breadcrumbs follow the server tree; all
  eight WP-3 lists and all 19 accounting sub-sections open; deep link, refresh,
  back/forward; 1440/768/390 px in light and dark; `200 → 304`; a simulated
  `503` shows the alert with **Retry**, keeps the filtered built-in menu and
  recovers; anonymous `401`; no uncaught page errors.
- Defect found and fixed during verification: `navReset()` called `navRefresh()`
  while the state was still `builtin`, so the guard returned before the fetch
  and the opted-in rail rendered empty. The loading state is now set before the
  fetch and the sequence guard moved into `navFetch()`.

**Rollback**

- Leave `NAV_API_ENABLED = false` and remove the `hb.navApi` session key; the
  app is back to the built-in menu. To remove the code, revert the 4c hunks in
  `static/js/workspace.js`, `static/js/app.js` and `static/css/styles.css`, and
  restore the previous `feature_store` and test files. No data to undo.

## 4 November 2026 — WP-4 Batch 4b: read-only navigation API (uncommitted)

**Added**

- `app/api/navigation.py` — `GET /api/navigation`, the signed-in user's
  Module → Category → Group → Screen tree. It filters by `role_permissions()`
  and by the feature switches, closes dependencies over
  `feature_registry.depends_on` (fail-closed on a cycle), prunes empty branches,
  keeps Home present and protected, passes aliases through, orders
  deterministically, and returns `ETag`, `Cache-Control: private, no-cache` and
  `Vary: Cookie`, answering `304` to a matching `If-None-Match`. It raises `503`
  when the registry tables are missing or the catalogue fails validation.
  `GET /api/admin/navigation` is the approved read-only registry view under
  `user:manage`: nodes, features with their enabled state, counts, fingerprint
  and validation errors, `no-store`.
- `app/services/navigation_store.py` — read-only queries with a fixed ordering,
  the stored switch flags, and the dependency closure (`feature_available`).
- `tests/test_navigation_api.py` — 26 tests: the five seeded roles' exact screen
  sets, Home protection, branch pruning, aliases, feature and dependency
  switches, inactive nodes, invalid references, `503`, ETag `200`/`304`, ETag
  changes after a permission or feature change, per-user ETags, "a GET writes
  nothing" and the admin endpoint's administrator-only rule.
- `var/reports/serve_wp4b.py`, `var/reports/run_wp4b_walk.py` — the evidence
  probe stack and the browser walk runner used for verification.

**Changed**

- `app/main.py` — the navigation router is registered.

**Not changed**

- No migration, table, column, seed row or business row. No permission key and
  no feature default. `workspace.js` is untouched, so the SPA still renders the
  sidebar from its hardcoded table and does not call the endpoint; wiring it is
  Batch 4c and was not started. Production was not connected to. No commit.
- `depends_on` narrows the navigation response only; the route-level feature
  gate still follows each feature's own switch. No shipped row declares a
  dependency, so this changes no current behaviour.

**Verified**

- Full suite: **525 passed, 0 failed, 0 skipped** in 219.03 s
  (`var/reports/wp4b-pytest.xml`); navigation tests **26 passed**; the
  four-file navigation subset **78 passed**; Node **18 passed**.
- Browser: WP-2/WP-3 walk **113/113** (A=42, B=20, C=51) on a test-database
  stack. In-browser API probe: Admin `200 → 304`, 25 screens, 49 permissions;
  Viewer `200 → 304`, 13 screens, 5 permissions; `private, no-cache` and
  `Vary: Cookie` present. Admin registry view: 64 nodes, 14 features, counts
  5/14/20/25/14, no errors.

**Rollback**

- Delete `app/api/navigation.py`, `app/services/navigation_store.py` and
  `tests/test_navigation_api.py`, and remove the two lines registering the
  router in `app/main.py`. Nothing else touched the database, so there is no
  data to undo.

## 4 November 2026 — WP-4 Batch 4a: navigation and feature registry activated (uncommitted)

**Added**

- `alembic/versions/0031_navigation_registry.py` — active migration creating
  `nav_nodes` and `feature_registry`, their indexes and CHECK constraints, and
  seeding 64 navigation nodes plus 14 feature records (78 rows). Down revision
  `0030_sign_in_content`; full downgrade drops both tables.
- `app/models/navigation.py`, `app/services/navigation_catalog.py`,
  `app/services/navigation_registry.py` — models, the canonical catalogue, and
  validation, visibility, fingerprint and ETag helpers. Nothing in the
  application reads them yet.
- `scripts/generate_navigation_seed.py`, `scripts/navigation_parity_report.py`,
  `scripts/verify_navigation_migration.py` and `tests/test_navigation_registry.py`
  (31 tests) plus `tests/js/emit_nav_manifest.cjs`.

**Changed**

- `app/services/db_reset.py` — `nav_nodes` and `feature_registry` added to
  `KEPT_TABLES`: 46 CLEAR + 43 KEEP + 1 SCHEMA = 90 tables.
- `app/models/__init__.py` — imports the navigation models.
- The seed generator, parity report, migration verifier and one registry test
  resolve the active `.py` first, then a `.draft`.

**Not changed**

- No API route, permission key, feature switch, business table or business row.
  `/api/navigation` is **not** implemented (404) and the frontend still renders
  navigation from `workspace.js`; those are batches 4b–4d. Production was not
  connected to or migrated.

**Verified**

- `herbanova_bcs_dev` at `0031_navigation_registry`, 90 tables, 64 + 14 rows,
  one Home, no business row or column changed; activation verification 16/16.
  A pre-activation dump was restored into a scratch database and matched before
  the upgrade.
- Full suite: **499 passed, 0 failed, 0 skipped** in 204.86 s
  (`var/reports/wp4a-activation-pytest.xml`); registry-sensitive subset **83
  passed**; Node **18 passed**; catalogue parity **11/11**.
- Browser: 113/113 walk, all 19 accounting sub-sections, the `distributors`
  alias and Home verified; dev API probe 35/35.

**Rollback**

- `alembic downgrade 0030_sign_in_content`, revert the `KEPT_TABLES` and model
  import edits, and delete the active migration file. The rehearsed downgrade
  removes exactly the two tables and no business row.

## 4 November 2026 — WP-2: workspace tabs, breadcrumbs and navigation (uncommitted)

**Added**

- `static/js/workspace.js` — one navigation hierarchy (module › category ›
  group › screen), the 25 view titles, view-permission and feature-switch maps,
  the workspace tab model (open, activate, close, close others, close all,
  reopen, prune, serialise) and breadcrumb paths. Pure functions, shared by the
  browser and the Node tests.
- Workspace tab bar: pinned Home, one tab per screen (Accounting adds its
  section), duplicate prevention, close / close others / close all except Home,
  reopen, overflow menu, WAI-ARIA tabs keyboard support.
- Breadcrumbs above every page title, built from the same hierarchy as the rail.
- Favourite star per screen, plus Favourites and Recently opened groups in the
  rail; the command palette gained a Screens group.
- Unsaved-form guard when closing a tab or switching screens with a dirty
  drawer open.
- `tests/js/workspace.test.cjs` (18 tests) and its `pytest` wrapper.
- `pytest.ini` pinning collection to `tests/`, so probe servers under `var/`
  are not imported and do not block collection.

**Changed**

- `static/js/app.js` renders the rail from the hierarchy instead of static HTML;
  `static/index.html` no longer carries the 25 hard-coded menu rows.
- Badge updates (`poCount`, `soCount`, `apCount`, `ldCount`) are null-safe, so a
  role whose menu omits a row no longer throws.
- The 20-tab bound evicts the oldest screen after Home into the reopen list
  instead of dropping it, and `reopenClosed` keeps the list `openTab` returns,
  so a reopen at the bound cannot lose a tab either.
- `tests/test_profit_loss.py::test_expenses_menu_follows_the_central_permission_map`
  now reads the maps from `workspace.js`.

**Not changed**

- No route, endpoint, permission key, feature switch, database table or
  migration. The backend remains the authority for every screen and action.

**Verified**

- Full suite: **468 passed, 0 failed, 0 skipped** in 239.05 s (run after the
  20-tab eviction fix; `var/reports/wp2b-pytest.xml`).
- Browser walk: **42/42 checks**, no console error, 227 API calls at HTTP 200
  while signed in; a deliberate role swap produced only the expected 403s.
  Evidence: `var/reports/wp2-browser.json`, `var/shots/wp2-tabs-*.png`.

**Known limits**

- Favourites and recents are stored per user in `localStorage` (device-local)
  until WP-4 adds server-side storage.
- The rail is never collapsed to icons; it becomes the horizontal module strip
  at ≤820 px.
- The 21st open screen evicts the oldest tab after Home (recoverable through
  *Reopen closed tab*). The eviction is covered by the Node model test; the
  browser walk reached 19 tabs and did not exercise the bound.

## 4 November 2026 — WP-4 design: navigation and feature registry (document only, uncommitted)

**Added**

- `docs/FEATURE_REGISTRY_DESIGN.md` — the WP-4 design and implementation plan:
  the measured baseline (25 screens, 5 modules, 14 categories, 20 groups,
  14 feature switches, 49 permission keys, 229 owned and 38 unowned API paths),
  the 14-feature and 25-screen mappings, the drift register D-01…D-08, decisions
  D1–D8, the four proposed tables (`nav_nodes`, `nav_aliases`,
  `feature_registry`, `user_favourites`) with reset classification, seed parity,
  the `GET /api/navigation` payload, visibility and validation rules, four
  implementation batches with stop points, nine tests, rollback and five owner
  decisions.

**Not changed**

- No code, schema, migration or data. Alembic head stays `0030_sign_in_content`;
  the design is gated on the owner's answers in §12 of the document.

**Verified**

- Every count and mapping in the document was read from the working tree (route
  inventory imported from `app.main.app.routes`; `Feature.views`, `VIEW_PERM`,
  `VIEW_FEATURE` and `WS.NAV` compared directly), not copied from older audits.
  The document is a design record; there was nothing to execute.

## 4 November 2026 — WP-3: list-screen standard (uncommitted on `eaf38d2`)

**Batch 1 — Products.** Labelled filter band with Search and Clear, server
paging with a true `X-Total-Count`, footer pager (25/50/100/200, default 50),
CSV export of all matching rows, and sortable headers on the columns the
endpoint can sort (`mrp`, NULLS LAST).

**Batch 2 — the other seven lists.** Suppliers, customers, sales orders,
purchases, billing, approvals and leads now share `LIST_SPEC`, `listState`,
`loadList`, `pagerHtml`, `searchList`, `clearList` and `exportListCsv`. Every
filter is applied by the server before the count; the page head states the
server total and only shows a breakdown when it matches the current filter.

**Not offered**

- Sorting on the seven batch-2 lists (their endpoints define no sortable order).
- Excel export, column configuration and row selection.

**Verified**

- `tests/test_products.py`, `tests/test_list_standard.py` (12 tests) and the
  browser walk recorded in `docs/VERIFICATION_REPORT.md` §28–§29.

## 3 November 2026 — accounting gap closure (committed in `eaf38d2`)

Purchase invoices and filed GST returns, statutory dues and challans, vouchers,
day book, opening balances, bank reconciliation, invoice due dates and
financial-year close, payroll partial months and skipped employees, free-of-cost
stock treatment, expenses, and Administrator TOTP with split frontend/backend
servers. Details: `docs/VERIFICATION_REPORT.md` §18–§25 and
`docs/ACCOUNTS_DATA_GAPS.md`.
