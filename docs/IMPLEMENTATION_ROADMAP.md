# Implementation roadmap and gap register

**Phase 1 deliverable for the master architecture brief, 4 November 2026.**

The brief requires twelve deliverables before substantial code changes:
architecture, menu and feature inventory, database inventory, API inventory,
route inventory, role and permission inventory, duplicate findings, missing
feature findings, proposed menu hierarchy, proposed navigation architecture, a
feature-to-API-to-table mapping and an implementation plan with dependencies and
risks. They are satisfied as follows:

| # | Deliverable | Where |
|---|---|---|
| 1 | Existing application architecture | [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) |
| 2 | Menu and feature inventory | [PRODUCT_MAP.md](PRODUCT_MAP.md) §2.2, [FEATURE_INVENTORY.md](FEATURE_INVENTORY.md) (142 rows) |
| 3 | Database table inventory | [DATABASE_TABLE_COLUMN_REGISTER.md](DATABASE_TABLE_COLUMN_REGISTER.md) (88 tables) |
| 4 | API inventory | [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) §2.1 (344 route objects, 268 paths) |
| 5 | Frontend route inventory | [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) §8 (25 views) |
| 6 | Role and permission inventory | [permissions-matrix.md](permissions-matrix.md), [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) §5 (49 keys) |
| 7 | Duplicate feature findings | §3 below |
| 8 | Missing feature findings | §4 below |
| 9 | Proposed menu hierarchy | [NAVIGATION_AND_TAB_DESIGN.md](NAVIGATION_AND_TAB_DESIGN.md) §3 |
| 10 | Proposed navigation architecture | [NAVIGATION_AND_TAB_DESIGN.md](NAVIGATION_AND_TAB_DESIGN.md) §4-5 |
| 11 | Feature-to-API-to-table mapping | Existing matrices in §5 below; registry-backed map is WP-4 |
| 12 | Implementation plan, dependencies and risks | §6-§8 below |

Baseline at the time of writing: `master` at `9ddfe2c`, Alembic head
`0030_sign_in_content`, 88 public tables, API routes now measured at **344 route
objects over 268 distinct paths** (this line originally read 341; the runtime
count is authoritative), 25 routed views, 14 feature switches, 49 permission
keys, 53 test files. Last recorded suite result at that writing: 454 passed, 0
failed (3 November 2026). Nothing in this phase changed code or data.

**Latest suite result (4 November 2026, Batch 4a activation):** **499 passed, 0
skipped, 0 failed**, 695 warnings in 204.86 s on `herbanova_bcs_test`
(`var/reports/wp4a-activation-pytest.xml`, exit 0), plus **18** Node workspace
tests. The three WP-4 registry checks that were gated on migration `0031` now
run in the main suite because the migration is active; no test is skipped. The
previous run, before activation, was 496 passed / 3 skipped. The working tree
sits on `feature/gap-closure` at `77f5a96` with 24 modified and 19 untracked
entries (WP-2, WP-3 and the activated Batch 4a artifacts), all uncommitted; the
pre-activation checkpoint is `var/backups/wp4a-activation-20261104T082147Z/`.
The browser re-verification passed 113/113 checks, and development
`herbanova_bcs_dev` is at `0031_navigation_registry` with 90 tables; see
[WP4_APPROVAL_READINESS.md](WP4_APPROVAL_READINESS.md) §14 and
[VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) §34.

**Latest suite result (4 November 2026, Batch 4b navigation API):** **525
passed, 0 failed, 0 skipped**, 699 warnings in 219.03 s on
`herbanova_bcs_test` (`var/reports/wp4b-pytest.xml`, exit 0), plus **18**
Node workspace tests. The 26 new tests in `tests/test_navigation_api.py` cover
the five seeded roles' exact screen sets, feature and dependency switches,
aliases, Home protection, the `503` path, ETag `200`/`304`, per-user ETags and
"a GET writes nothing"; the navigation four-file subset is 78 passed. The
working tree is still `feature/gap-closure` at `77f5a96`, uncommitted, now 47
entries (25 modified, 22 untracked). The browser walk re-ran on a
test-database stack at **113/113** and the in-browser API probe returned
`200 → 304` for Admin and Viewer; see [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md)
§35.

**Latest suite result (4 November 2026, Batch 4d default activation):** **542
passed, 0 failed, 0 skipped** on `herbanova_bcs_test`
(`var/reports/junit-wp4d.xml`, exit 0), plus **20** Node workspace tests. The
12 new tests are the 10 parity checks in `tests/test_navigation_parity.py` and
two Administrator-narrowing checks in `tests/test_navigation_registry.py`. The
browser walk passed **226/226** (A=42, B=20, C=51, D=113) on a test-database
stack (`var/reports/wp4d-browser.json`). The working tree is `feature/gap-closure`
at `77f5a96`, uncommitted, 50 entries (26 modified, 24 untracked); see
[VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) §37.

## 1. Documentation map against the brief's required files

The brief says to maintain its list "adapting existing files instead of creating
unnecessary duplicates". Mapping:

| Required file | Current home | Action |
|---|---|---|
| PROJECT_ARCHITECTURE.md | **new** | Created this phase |
| APPLICATION_MENU_STRUCTURE.md | `PRODUCT_MAP.md` §2.2 | Replaced by registry output in WP-4 |
| FEATURE_REGISTRY.md | `FEATURE_INVENTORY.md` + `app/core/features.py` | DB registry in WP-4 |
| FEATURE_API_DATABASE_MAPPING.md | `REQUIREMENTS_TRACEABILITY_MATRIX.md`, `FRONTEND_BACKEND_FIELD_MAPPING.md`, table register | Machine-readable registry in WP-4 |
| DATABASE_RELATIONSHIP_MAP.md | Table register (columns and 53 FK references) | Dedicated map in WP-4 |
| ROLE_PERMISSION_MATRIX.md | `permissions-matrix.md` | Keep |
| BUSINESS_WORKFLOW_MAP.md | `FEATURE_INVENTORY.md` §4-8, `FORMULA_AND_BUSINESS_RULE_REGISTER.md` | **Missing as a file** — WP-6 |
| NAVIGATION_AND_TAB_DESIGN.md | **new** | Created this phase |
| DUPLICATE_FEATURE_AUDIT.md | `PROJECT_AUDIT.md` §3, §3 below | **Missing as a file** — WP-1 follow-up |
| FEATURE_GAP_ANALYSIS.md | §4 below, `ACCOUNTS_DATA_GAPS.md`, `HR_AUDIT.md` | **Missing as a file** — WP-1 follow-up |
| TESTING_AND_VERIFICATION.md | `VERIFICATION_REPORT.md`, `FORMULA_RECONCILIATION_TESTS.md` | Keep |
| IMPLEMENTATION_ROADMAP.md | **new** | Created this phase |
| CHANGELOG.md | [CHANGELOG.md](CHANGELOG.md) | Created 4 November 2026 at WP-2 |
| USER_MANUAL.md | `docs/user-manual/` | Keep |

## 2. Method and limits

The audit read the working tree directly: AST parsing of `app/api/*.py` for
routes, AST parsing of `app/models/*.py` and every `create_table` call in
`alembic/versions/` for tables, and full reads of the SPA shell, router table and
feature catalogue. No database was queried and no migration was run, so table
counts are source-verified (87 models + `alembic_version`), not `information_schema`
counts. The test suite was not re-run because nothing changed.

## 3. Duplicate findings

| # | Finding | Evidence | Assessment |
|---|---|---|---|
| D-01 | Four parallel descriptions of "which screens exist": `TITLES`, `VIEW_PERM`, `VIEW_FEATURE` in the SPA and `Feature.views` on the server | `static/js/app.js:701-721`, `:196-205`; `app/core/features.py:38-132` | Real duplication; any new screen must be added in four places today. WP-4 collapses them into the registry |
| D-02 | Two navigation concepts that look alike: the static 18-module delivery register and the 14 feature switches | `app/core/module_register.py:55-164`; `app/core/features.py:38-132` | Different purposes (delivery status vs runtime switch), but both are called "module"; the registry must name them distinctly |
| D-03 | Two database-reset routers, one legacy | `app/api/db_reset.py:18-19`; legacy path `:91` returns 410 | Harmless but should be removed in a cleanup package |
| D-04 | View alias: `#/distributors` opens `customers` | `static/js/app.js:742` | Keep for compatibility; record in the route registry as an alias |
| D-05 | In-page tab sets (inventory, scheduled reports, HR profile, report picker) | `static/index.html:573-577,1563-1567`; `app.js:6092,6652` | Not duplicates of workspace tabs; do not merge the concepts |
| D-06 | Empty placeholder CSS for "coming soon" nav items, no markup uses it | `static/css/styles.css:367` | Remove or wire to the registry's inactive state |
| D-07 | Historical audit documents overlap: `PROJECT_AUDIT.md`, `STAGE1_REAUDIT.md`, `STAGE4_REMEDIATION.md` | docs/ | Keep as dated evidence; do not merge |

No duplicate master tables were found. Customer and distributor still share one
master and one API file (`app/api/distributors.py`), supplier and product masters
are single tables, and employee data is not duplicated in users.

## 4. Gap register

Severity: **S1** blocks a brief requirement outright; **S2** materially limits
it; **S3** cosmetic or documentary.

| # | Gap | Sev | Evidence | Work package |
|---|---|---|---|---|
| G-01 | Navigation is hardcoded HTML; no menu table, API, ordering, activation or hierarchy | S1 | `static/index.html:160-197`. **Closed for the delivery path 4 Nov 2026:** the hierarchy, ordering and activation exist as 64 rows in `nav_nodes` (4a), `GET /api/navigation` serves the filtered tree (4b), and the browser renders that tree by default (4d); the built-in `workspace.js` hierarchy remains the loading/error fallback and is restorable with `?nav=builtin` | WP-4 |
| G-02 | No database feature registry; no route/API/table/permission/dependency mapping per feature | S1 | `app/core/features.py:38-132` only. **Closed on the server 4 Nov 2026 (4a/4b):** `feature_registry` carries route, component key, API prefixes, tables, permissions and dependencies, readable at `GET /api/admin/navigation`. No generated document yet, so G-09 stays open | WP-4 |
| G-03 | No feature-management screens (brief §6 lists twelve) | S1 | none exist | WP-5 |
| G-04 | No workspace tabs, Home tab, overflow, reopen, favourites or breadcrumb | S2 | `app.js:752` showed one view at a time. **Closed 4 Nov 2026 in WP-2** for tabs, Home, overflow, reopen, breadcrumb, favourites and recents; favourites are device-local until WP-4 | WP-2 |
| G-05 | Lists are not paginated server-side in the UI; client requests up to 200 rows and filters locally | S1 | `app.js:621-636,694`; helper used by only 8 endpoints (`app/core/pagination.py`). **Closed for the eight list screens on 4 Nov 2026** (Products batch 1, the other seven batch 2): each reads one server page with the true total. The remaining 200-row caches feed drawers and forms, not lists | WP-3 |
| G-06 | No shared pager, sortable columns (except Geography), column configuration or row selection | S2 | `app.js:2182,2203-2210`; 1 sortable screen. **All eight list screens share the pager since 4 Nov 2026** (Products batch 1; the other seven batch 2). Header sorting remains Products only; column configuration and row selection remain | WP-3 |
| G-07 | Filter bands are inconsistent and have no explicit Search/Clear; Accounts/HR use Apply buttons, several screens have no band | S2 | 50 `.toolbar` bands; outliers at `index.html:780-1019,1124,1147-1155`. **The eight list screens have Search/Clear since 4 Nov 2026**; the Accounts/HR Apply bands remain | WP-3 |
| G-08 | Purchase orders have no approval workflow (receipt-driven status only) | S2 | `app/models/core.py:156`; no approval category in `app/core/rules.py` | WP-6, pending decision |
| G-09 | No dedicated database relationship map document | S3 | 53 FK references exist in the table register only | WP-4 |
| G-10 | No Service & Workshop module, although the brief lists it | S2 | no models, services or routes | WP-6, pending decision |
| G-11 | No quotation stage between lead and sales order | S2 | flow starts at sales order | WP-6, pending decision |
| G-12 | Export is CSV only; the reference shows an Excel download | S3 | 23 CSV buttons, `downloadCsv` at `app.js:2106`. The eight list screens export CSV in WP-3 (Products batch 1, the other seven batch 2, 4 Nov 2026); Excel remains a pending decision | WP-3, pending decision |
| G-13 | No system-health screen for broken menu links, missing permission mappings or route mismatches | S3 | Overview module panel only (`app.js:620,648,1679`) | WP-7 |
| G-14 | Four documentation files missing (see §1) | S3 | docs/ | WP-1 follow-up |

`#128` — browser verification of HR saves and statutory refusal — remains
pending from the earlier programme and is not part of this one; it must not be
closed by implication.

## 5. Feature-to-API-to-table mapping today

The mapping exists as prose and tables, not as a registry:

- 142 feature rows in `FEATURE_INVENTORY.md` carry status and evidence.
- 135 requirement rows in `REQUIREMENTS_TRACEABILITY_MATRIX.md` link each
  requirement to its screen, API and migration.
- `FRONTEND_BACKEND_FIELD_MAPPING.md` maps each form to its payload and endpoint.
- `DATABASE_TABLE_COLUMN_REGISTER.md` describes every table and column.

What is missing is a single queryable source: feature → route → router → service
→ model/table → permissions → dependencies → activation. That is the core of
WP-4. Until it exists, no screen should be declared "registered" — the brief's
acceptance criterion ("every screen is mapped to a registered feature") cannot
be met with four parallel JavaScript objects.

## 6. Work packages

Each package is independently shippable, with its own tests and documentation.
No package rewrites the accounting, inventory or permission logic.

### WP-1 — Phase 1 deliverables (this document set) — **complete**
- Files: `docs/PROJECT_ARCHITECTURE.md`, `docs/NAVIGATION_AND_TAB_DESIGN.md`,
  `docs/IMPLEMENTATION_ROADMAP.md`.
- Follow-up: create `DUPLICATE_FEATURE_AUDIT.md` and `FEATURE_GAP_ANALYSIS.md`
  from §3-§4 (still open). `CHANGELOG.md` was started on 4 November 2026.
- Risk: none; documentation only.

### WP-2 — Workspace shell: tabs, breadcrumbs, overflow — **shipped 4 November 2026**
- Scope: tab strip with permanent Home, canonical keys, close / close others /
  close all except Home, reopen last closed, overflow menu, keyboard support;
  breadcrumb from the shared hierarchy; `sessionStorage` persistence and
  permission re-validation on restore; favourites, recent screens and the
  palette's screen group; unsaved-drawer guard.
- Files: new `static/js/workspace.js` (376 lines, UMD, pure functions shared
  with the tests); `static/js/app.js` (rendering and events only); `static/css/styles.css`
  (tab bar, breadcrumbs, favourite star, responsive shell); `static/index.html`
  (tab bar, breadcrumb container, favourite button).
- Schema: none.
- Tests: `tests/js/workspace.test.cjs` — 18 Node tests covering hierarchy,
  hash parsing, canonical keys, duplicate protection, Home protection, close/
  close-others/close-all, reopen, restore pruning, serialisation, permission and
  feature rules, breadcrumb depth and ancestor permission, favourites,
  recents, and the 20-tab bound with recoverable eviction.
  `tests/test_workspace_model.py` runs the file from `pytest` and fails if fewer
  than 18 tests run.
- Browser evidence: `var/shots/wp2-tabs-{1440,768,390}-{light,dark}.png`, plus a
  CDP walk (`var/reports/wp2-browser.json`) with **42/42 checks passing**, no
  page errors or unhandled rejections, and 227 API calls at HTTP 200 in the
  signed-in walk. The walk covers deep links, refresh, duplicate prevention,
  close/close-others/close-all, overflow, keyboard navigation, favourite
  toggle persistence, breadcrumb trail and a deliberate session swap to a
  viewer role (14 requests refused with 403 — the expected backend enforcement,
  and the viewer page rendered no accounts content).
- Rollback: remove `static/js/workspace.js` and the WP-2 hunks in the three
  other frontend files (WP-2 is uncommitted, so `git checkout -- <file>` would
  also discard WP-3 work). No route, permission gate or endpoint changed. The
  file-by-file procedure is in
  [NAVIGATION_AND_TAB_DESIGN.md](NAVIGATION_AND_TAB_DESIGN.md) §10.6.
- Deviations, deliberate and recorded in
  [NAVIGATION_AND_TAB_DESIGN.md](NAVIGATION_AND_TAB_DESIGN.md) §10.5:
  1. Favourites and recents are stored in `localStorage` per user instead of
     server-side, because the server-side table belongs to WP-4. They are
     re-filtered by the menu predicate on every render.
  2. The rail is never collapsed to icons. It keeps its labels and becomes the
     horizontal module strip at ≤820 px, which is the shell's existing
     breakpoint; an icon-only rail remains a possible refinement.
  3. Breadcrumb segments are text-only where the hierarchy has no routable
     ancestor (for example the module name), because the app has no module
     landing screen and inventing one would create a dead link.
  4. The model keeps at most 20 tabs; the oldest screen after Home is evicted
     into the reopen list, so nothing is lost without a way back. The strip
     itself is additionally bounded by width through `fitTabs()`.
- Defect found and fixed during verification: `#poCount`, `#soCount`,
  `#apCount` and `#ldCount` were updated unconditionally, which threw on a role
  whose menu omits those rows. They now go through the null-safe `setBadge()`
  helper. This was a pre-existing latent bug exposed by the viewer-role walk;
  it is fixed in this package, not deferred.
- Risk: tab state versus hash routing. Mitigation: the hash remains the single
  source of the active tab; the strip never invents history entries.

### WP-3 — List-screen standard — **shipped 4 November 2026**
- Scope: labelled filter band with explicit Search/Clear on every list, adopt
  `app/core/pagination.py` across list endpoints, footer pager (page size
  25/50/100/200, default 50, `1–N of TOTAL` from `X-Total-Count`), sortable
  columns where the backend can sort safely, one export button per screen.
- Files: `app/api/*` list endpoints, `app/core/pagination.py`,
  `static/js/app.js`, `static/index.html`, `static/css/styles.css`.
- Schema: none.

**Batch 1 / pilot — Products (`#/products`): complete.**

| Piece | Where | Verified by |
|---|---|---|
| Filter band with search, status, Search and Clear | `static/index.html` Products panel; `static/js/app.js` `search-products`, `clear-products`, debounced `#pq`, `#pstat` | Browser probe: search `COST` → 30 matching rows on page 1; zero-match search → filtered empty state; Clear → 50 rows and both controls reset |
| Server-side paging with the true total | `apiPage()` reads `X-Total-Count`; `loadProductList()`; `productListPage()`; `pagerHtml()` | 52 products on the test DB: page 1 `1–50 of 52`, page 2 `51–52 of 52`; page size 25 → `1–25 of 52`, 3 pages |
| Pager controls | `static/css/styles.css` `.pager` rules; `#ppager` in the Products panel | `«`/`‹` disabled on page 1, `›`/`»` disabled on the last page, both re-enable mid-list; `Page n of m` reports the server's page |
| Load ordering | sequence guard in `loadProductList()`; stranded-page retry to page 1 | Not exercised: code-reviewed only. Every filter control deliberately requests page 1, so the probe never produced a stranded page or an out-of-order response. |
| Export CSV | `exportProductsCsv()` — same endpoint without `page`, all matching rows | Probe intercepted the download: `HERBANOVA_Products_2026-11-04.csv`, toast `Exported 52 products` |
| Regression safety | `state.products` (200-row form cache) is untouched; the screen uses `state.plist`; `productDrawer` reads `plist.rows` first | Full suite 455 passed; order/invoice product selectors still read `state.products` |
| Sortable headers | `#prows` headers call `sort-products`; the API reads `sort` + `direction` through the whitelist in `app/api/products.py` | Probe clicked MRP: ascending `100.00 → 900.00`, descending `900.00 → 100.00`; each request carried `sort=mrp&direction=asc|desc` and `aria-sort` followed the click |

`tests/test_products.py::test_product_list_pages_and_server_filters` asserts
disjoint pages, a stable `X-Total-Count` across pages, that omitting `page`
returns every matching row (the export read), and that the status filter is
applied on the server.

**Batch 2 — the other seven lists: complete.**

Suppliers, customers, sales orders, purchases, billing, approvals and leads now
share one layer instead of seven hand-rolled ones: `LIST_SPEC`, `listState`,
`loadList` (sequence guard + stranded-page retry), `pagerHtml`/`paintListPager`,
`searchList`, `clearList` and `exportListCsv`. Server filters moved behind the
same query strings the endpoints already documented; no business rule,
permission or API shape changed. The status breakdown in the page head is shown
only when the rows in hand cover the server total and the default filter is
active; a search or a narrower filter shows the server total alone, so the head
can never pair one filter's total with another filter's breakdown.

| Screen | Filter carried to the server | Evidence on `herbanova_bcs_test` |
|---|---|---|
| Suppliers | `q`, `status`, `incomplete` | 27 on file; search `INC-518674` → `1–1 of 1`; Needs completion → 1; Clear → `1–25 of 27`; export `27 suppliers` |
| Customers | `q`, `status`, `incomplete` | 30 on file; search `CD-7E3FCC` → `1–1 of 1`; incomplete → 25; Clear → 30; export `30 records` |
| Sales orders | `q`, `status` | 95 on file, `Page 1 of 2` at 50; at 25 rows page 2 shows `26–50 of 95`; draft → 45; Clear → 95; export `95 orders` |
| Purchases | `q`, `status` | 27 on file; received → 2; Clear → `1–25 of 27`; page 2 `26–27 of 27`; export `27 orders` |
| Billing | `q`, `status` | 26 on file; issued → 26; search `INV/2627/000026` → `1–1 of 1`; export `26 invoices` |
| Approvals | `q`, `status`, `decided` | pending 23 on open; decided → 4; `1–23 of 23` back on pending; export `23 requests` |
| Leads | `q`, `status`, `due`, `owner` | 30 on file; closed → `0 of 0` with the filtered empty state; due today → 30; export `30 leads` |

Tests: `tests/test_list_standard.py` (12 tests) pins each screen's contract —
server filters that change both rows and total, `X-Total-Count` agreeing with
the unpaged read, pages that do not overlap, an unpaged export read, and the
new `test_every_list_pages_on_the_server`, which loops over all seven endpoints
and proves page 1, page 2 and the unpaged read share one total and that
`page_size=201` is refused. Full suite: **467 passed**, 0 failed, 0 skipped
(`python -m pytest -q -rs --junitxml=var/reports/pytest-wp3b2.xml`,
exit 0, 241 s, 4 November 2026).

Browser evidence: `var/shots/wp3b2-<screen>-{page1,page2,search,cleared,filter}-1440.png`
for all seven screens (35 images) plus the machine-readable walk in
`var/reports/wp3b2-browser.json`, captured against a temporary backend on :8011
over `herbanova_bcs_test` and a temporary frontend on :3011. No console errors
were recorded during the walk. Opening a record from page 2 also worked
(`ensureCached`): the drawer showed `SO-20261104-A152CE` with its buyer.

**Known limits, not silently claimed:**

- Sortable headers exist on Products only. The seven batch-2 endpoints keep
  their documented order (`created_at` descending, or the list's own key), so
  their headers are not clickable rather than offering a sort the server does
  not apply.
- Export is CSV everywhere; `.xlsx` remains a separate decision.
- Column configuration and row selection are not implemented.
- Approval totals describe the rows the signed-in role may see, not the table;
  `tests/test_list_standard.py` pins that behaviour.

- Rollback: endpoints keep their current defaults when `page` is omitted, so a
  partial rollout is safe; each screen can be reverted alone. Reverting batch 2
  restores the previous render functions and leaves the APIs untouched.
- Risk: changing a list from "all rows in the browser" to server pages can hide
  rows if a client-side filter was doing work the server does not. Mitigation:
  every batch-2 filter was compared against the current behaviour in tests, and
  the head count now follows the server total instead of the cache size.

### WP-4 — Navigation and feature registry (migration)

**Batch 4a was activated and Batches 4b (the read-only navigation API), 4c
(the opt-in frontend integration) and 4d (default activation) were implemented
and verified on 4 November 2026, each after explicit owner approval.** The
corrected design is
[FEATURE_REGISTRY_DESIGN.md](FEATURE_REGISTRY_DESIGN.md); the review and
activation record is [WP4_APPROVAL_READINESS.md](WP4_APPROVAL_READINESS.md).
Development is at `0031_navigation_registry`; production remains at
`0028_advances` and was not touched.

- **R-01 is resolved in the design and in code.** Neither `feature_registry.feature_key`
  nor `nav_nodes.feature_key` is a foreign key to `feature_flags.key`; both are
  `String(32)` validated against `FEATURES`. `feature_flags` stays the only
  switch state and an absent row still means ON. Five tests pin the behaviour,
  including deleting every switch row without an FK error.
- **Two tables, not four.** `0031` creates `nav_nodes` and `feature_registry`
  only. `nav_aliases` is eliminated (one alias, stored as a JSON `aliases` array
  on the `customers` node); `user_favourites` is deferred to a hypothetical
  additive `0032` contingent on owner decision D8.
- **Measured corrections:** 344 `APIRoute` objects (not 348), **268 distinct
  paths / 229 owned / 39 unowned** (38 `/api` plus `/`); 25 screens, 22
  `Feature.views` strings (21 screens plus the `distributors` alias); 88 tables
  and 182 foreign keys at `0030`, 90 tables at `0031`. The 19 accounting
  sub-sections are not modelled by the registry and stay code-driven through 4c
  (gap G-01).
- **Activated:** `alembic/versions/0031_navigation_registry.py` (chain
  `0028 → 0029 → 0030 → 0031`), `app/models/navigation.py`,
  `app/services/navigation_catalog.py`, `app/services/navigation_registry.py`,
  `scripts/generate_navigation_seed.py`, `scripts/navigation_parity_report.py`,
  `scripts/verify_navigation_migration.py`, `tests/test_navigation_registry.py`,
  `tests/js/emit_nav_manifest.cjs`; both tables added to `KEPT_TABLES`.
- **Applied to development:** `herbanova_bcs_dev` moved from
  `0030_sign_in_content` to `0031_navigation_registry` after a verified dump and
  restore test. 90 tables, 64 + 14 = 78 seeded rows, one Home, no business row
  or column changed; activation verification 16/16. Full suite **499 passed, 0
  failed, 0 skipped**; registry-sensitive subset **83 passed**; Node **18**;
  parity **11/11**; browser walk **113/113**; 19 accounting sub-sections and the
  `distributors` alias verified in the browser; `/api/navigation` was still 404
  at that point. Evidence in `var/reports/wp4a-activation-*` and
  `var/backups/wp4a-activation-20261104T082147Z/`. Details: approval-review §14
  and verification report §34.
- **Batch 4b implemented and verified, uncommitted.** `GET /api/navigation`
  returns the Module → Category → Group → Screen tree for the signed-in user,
  filtered by `role_permissions()` and by the feature switches, with dependency
  closure over `feature_registry.depends_on`, empty branches pruned, Home always
  present and protected, aliases passed through, deterministic ordering, a
  per-user ETag with `Cache-Control: private, no-cache` and `Vary: Cookie`,
  `304` on `If-None-Match`, and `503` when the registry is missing or invalid.
  The approved read-only `GET /api/admin/navigation` reports nodes, features,
  counts, fingerprint and validation errors. Both are read-only: neither writes
  a row nor an audit entry. No migration, table, seed or business-data change.
  Full suite **525 passed, 0 failed, 0 skipped**; Node **18 passed**; browser
  walk **113/113** (A=42, B=20, C=51); in-browser probe Admin 200→304 with 25
  screens and 49 permissions, Viewer 200→304 with 13 screens and 5 permissions.
  Evidence in `var/reports/wp4b-*`. Details: verification report §35 and design
  §6.1, §6.3, §9.1.
- **Batch 4c implemented and verified, uncommitted.** The SPA can read
  `/api/navigation` when the browser opts in with `?nav=api`;
  `NAV_API_ENABLED = false` remains the release default, so an ordinary browser
  renders the unchanged built-in menu. `workspace.js` gained the active-tree
  model and `navFromApi` converter; `app.js` gained the opt-in loader, the
  sequence and username guard, and a failure alert with **Retry** that keeps the
  built-in filtered menu. Tabs, breadcrumbs, favourites, recents, the palette,
  the router and all 19 accounting sub-sections are unchanged. `feature_store`
  now derives the route gate, `/api/auth/me`, RBAC and navigation from one
  dependency closure, which closes the inconsistency 4b carried. No migration,
  table, seed or business-data change. Full suite **530 passed**; Node **20**;
  browser **199/199** (A=42, B=20, C=51, D=86) across the five roles, both
  themes and 1440/768/390 px, including a simulated 503 and recovery. Evidence
  in `var/reports/wp4c-*`. Details: verification report §36, design §6.4 and
  navigation design §11.
- **Batch 4d implemented and verified, uncommitted.** `NAV_API_ENABLED = true`
  makes the server tree the default menu for every browser; `?nav=builtin`
  restores the built-in hierarchy for the session, and the built-in,
  permission-filtered rail is drawn while the request is in flight and kept on
  failure with **Retry**. The `scheduled` visibility discrepancy is closed
  without loosening RBAC: `ADMIN_ONLY_VIEWS` and `narrow_admin_only()` remove
  Administrator-only screens for every other caller, and `admin` joins the ETag
  identity so a promotion or demotion cannot yield a stale `304`. The parity
  harness runs the shipped `workspace.js` in Node against the real endpoint
  body for the five seeded roles and 173 permission/feature combinations
  (`tests/test_navigation_parity.py`, `tests/js/nav_parity.cjs`); view and menu
  sets are identical, with no duplicate or unknown view. No migration, table,
  seed or business-data change. Full suite **542 passed**; Node **20**; browser
  **226/226** (A=42, B=20, C=51, D=113) across five roles, all 25 screens, 19
  accounting sub-sections, eight WP-3 lists, tabs, deep links, both themes,
  1440/768/390 px, three forced failures and a live permission change. Evidence
  in `var/reports/wp4d-*` and `var/reports/junit-wp4d.xml`. Details:
  verification report §37, design §6.4/§6.5 and navigation design §12.
- Favourites and recents remain device-local (D8/D13); server-side favourites
  were not implemented.
- **Rollback:** set `NAV_API_ENABLED = false` or open the app with
  `?nav=builtin`; no data or server change is involved. The `0031` downgrade
  remains the 4a procedure and was rehearsed; it removes no business row.
- **Next:** production promotion is a separate approval and must apply
  `0029 → 0030 → 0031` in order. WP-4 editing screens belong to WP-5.

- Original scope as planned (tables and seed: done in 4a; `GET /api/navigation`:
  done in 4b; sidebar renders from the API: done in 4c behind the switch, and
  the default since 4d): tables for
  modules, menu items (levels 1–4, ordering, activation,
  aliases inline), feature registry (route, component key, API prefixes, tables,
  permissions, dependencies, status); seed from the 25 views and 14 features;
  `GET /api/navigation`; sidebar renders from the API with the current HTML as a
  fallback until verified; dependency and duplicate checks.
- Migration: `0031_navigation_registry` with a full downgrade. Additive only; no
  existing table is altered or dropped; no foreign key to `feature_flags`.
- Tests: seed parity (every current view and feature represented), permission
  filtering, alias resolution, downgrade, and a guard that no route is orphaned.
- Rollback: `alembic downgrade 0030_sign_in_content` plus the previous SPA; the
  frontend falls back to the hardcoded menu if the API is absent.
- Risk: drift between registry and code. Mitigation: a startup validation that
  compares registry API prefixes and routes against the FastAPI app, reported on
  the health screen (WP-7).

### WP-5 — Feature-management screens
- Scope: the twelve screens from brief §6, read/write under `user:manage` (or a
  new `system:manage`), audited, with search, filters, status and history;
  deactivation instead of deletion for anything with history.
- Depends on WP-4.
- Tests: permission enforcement on every screen, audit rows, refusal to delete
  referenced features.

### WP-6 — Workflow gaps (decision-gated)
- Purchase-order approval: add an approval category, request creation, decision
  routing and status transition; migration only if a column is needed.
- Quotation: new document family with numbering, tax and print — a business
  decision, not a UI addition.
- Service & Workshop: only if confirmed as a real requirement; otherwise the
  brief's module is documented as intentionally absent.
- Each item is separately approved and separately tested; none starts before
  the questions in §9 are answered.

### WP-7 — System health and navigation validation
- Scope: a System Management screen showing API/database health, recent failed
  e-mails and jobs, registry-versus-code mismatches, broken menu targets,
  missing permission mappings and feature activation state.
- Depends on WP-4. Read-only except for safe actions already audited elsewhere.

### WP-8 — Verification and release
- Full suite, `alembic check` on a restored copy, browser evidence at 1440/768/390
  in both themes, documentation and changelog updates, then the production
  migration as a separate approved step (production is still at `0028_advances`).

## 7. Sequence and dependencies

```
WP-1 (done)
  ├─ WP-2 (tabs/breadcrumbs, shipped 4 Nov 2026) ──┐
  ├─ WP-3 (list standard, shipped 4 Nov 2026) ─────┤
  └────────────────────────────────────────────────┴─ WP-4 (registry 4a, API 4b, opt-in 4c, default 4d) ── WP-5 (admin screens)
                                                                        ├─ WP-7 (health)
                                                                        └─ WP-6 (decisions) ── WP-8
```

WP-2 and WP-3 were built in that order. WP-4 now follows the list standard, so
the registry can record real pagination metadata rather than client-side
behaviour. Within WP-4, 4a (schema and seed), 4b (the read-only API), 4c (the
SPA integration) and 4d (default activation) are done; the server tree is the
default menu, with the built-in hierarchy as the loading/error fallback and the
`?nav=builtin` rollback. Server-side favourites were not part of 4d.

## 8. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Registry drifts from code | Menus point at dead routes | Startup validation + health screen; registry seeded from code, not hand-typed |
| Permission regression while moving menu visibility | Users lose or gain screens | Backend enforcement unchanged; authz tests run per package; no permission key renamed |
| Pagination change hides rows | Wrong operational decisions | Server-side filters first, count comparisons, boundary tests |
| Tab state loss or duplicate tabs | Poor trust in the shell | Hash remains authoritative; canonical keys; unsaved-drawer warning |
| Scope creep into Service/Quotation | Half-built modules | Decision-gated; refuse to create empty menu entries |
| Frontend-only changes outrun the backend | Fake buttons | No package ships a control whose API does not exist |
| Production migration done too early | Downtime or drift | Production stays at 0028 until WP-8 approval |

## 9. Open decisions needed before WP-6

1. **Service & Workshop** — build it, or record it as intentionally out of
   scope? Nothing exists today.
2. **Quotation** — add a quotation document between lead and sales order, or
   keep the current lead → order flow?
3. **Purchase-order approval** — is a manager approval step required, and at
   what value?
4. **Export format** — keep CSV, or add a true XLSX writer (a dependency
   decision, not a button rename)?
5. **Favourites scope** — per user only, or per role default sets as well?
6. **Branch/office menu restrictions** — enforce now in the registry, or keep
   current permission-only visibility?

## 10. Acceptance criteria carried from the brief

The application is ready only when every active menu item opens the correct
screen, every screen is a registered feature, every feature uses its mapped API
and tables, no duplicate business logic exists, permissions are backend-enforced,
transactions follow valid workflows, accounting and inventory reconcile, reports
read real transactions, navigation and tabs are reliable, no existing feature is
lost, critical workflows have passing tests and the documentation reflects the
delivered application.

## 11. Reporting per package

Every package reports: files inspected, files changed, database changes, APIs
added or modified, features affected, tests executed and their results, remaining
issues and the rollback procedure — matching the pattern already used in
[VERIFICATION_REPORT.md](VERIFICATION_REPORT.md).
