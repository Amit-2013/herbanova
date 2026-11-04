# Navigation, workspace tabs and list-screen design

**Phase 1 design deliverable for the master architecture brief, 4 November 2026.**

This document records the navigation that exists today, the gaps against the
brief, and the design to be implemented in controlled phases. The GDMS 2.0
screenshots supplied with the brief are treated as a functional reference only
— no branding, assets, text or proprietary code are copied.

**Update 4 November 2026 — WP-2 (step N1) shipped.** Tabs, breadcrumbs, the
rebuildable sidebar, favourites, recent screens, the palette screen group and
the unsaved-change guards are live in the SPA; §10 records what shipped, the
three deviations from this design, the tests and the evidence. Steps N3-N4
(the registry) remain a design only.

Related: [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md),
[DESIGN_SYSTEM.md](DESIGN_SYSTEM.md),
[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md),
[PRODUCT_MAP.md](PRODUCT_MAP.md).

---

## 1. Navigation as built

| Element | Current state | Evidence |
|---|---|---|
| Top bar | Brand, global search trigger, theme toggle | `static/index.html:147-159` |
| Module rail | Fixed left column, five flat groups, permission-gated links | `static/index.html:160-204` |
| Groups | Overview; Sales and customers; Stock and supply; Finance and insight; People and admin | `static/index.html:161-197` |
| Menu source | Hardcoded HTML; a code deploy is needed to change it | same |
| Visibility | Client-side `featureOn(view)` using the 14 feature switches from `/api/auth/me` | `static/js/app.js:234`; `app/api/auth.py:61-67` |
| Routing | Hash routes `#/view/section?query`, deep-linkable and refresh-safe | `static/js/app.js:722-787`, `:11785` |
| Tabs | **None** — one view at a time; in-page tabs only | `static/js/app.js:752` |
| Favourites | **None** | no matching code or CSS in `static/` |
| Breadcrumb | **None** — the page header shows title and subtitle only | `static/index.html:206-212` |
| Status bar | Environment and totals | `static/index.html:1625-1630` |

The 25 routed views are declared in `TITLES` (`static/js/app.js:701-710`).
Everything below builds on those views; no new business screen is invented here.

## 2. Gaps against the brief

| Brief | Requirement | Status |
|---|---|---|
| §4 | Configurable module → category → submenu → feature hierarchy, centrally managed | Missing (HTML only) |
| §4 | Menu activation, ordering, parent-child, role/branch visibility, favourites | Missing |
| §5 | Central feature registry with route, API, table, permission and dependency mapping | Partial: 14 static `Feature` entries, no DB registry |
| §6 | Twelve feature-management screens | Missing |
| §7 | Multi-tab workspace with Home tab, close/close-others, overflow, reopen, unsaved guard | Missing |
| §7 | Breadcrumbs | Missing |
| §14 | Shared list pagination, sorting, column configuration, row selection | Partial/missing (see §6) |

## 3. Proposed hierarchy

Four levels. Level 1 modules follow the brief's list; level 2/3 categories follow
what the code already separates; level 4 is always one of the 25 existing views.
A view may appear under more than one category, but every placement resolves to
the same canonical view and route.

| L1 module | L2 category | L3 group | L4 features (existing views) |
|---|---|---|---|
| Dashboard | Overview | — | Overview (`dash`), MoM & YoY (`compare`) |
| CRM | Pipeline | Leads | Leads (`leads`), Lost leads (`lost`), Today's follow-ups (`followups`) |
| CRM | Parties | — | Customers & distributors (`customers`) |
| Sales | Orders | — | Sales orders (`sales`) |
| Sales | Billing | — | Billing (`billing`) |
| Sales | Control | — | Approvals (`approvals`) |
| Purchase | Buying | — | Purchases (`purchasing`) |
| Purchase | Parties | — | Suppliers (`suppliers`) |
| Inventory | Masters | — | Products (`products`) |
| Inventory | Stock | — | Inventory (`inventory`), Free samples (`foc`) |
| Accounts & Finance | Books | — | Accounting & Finance (`accounts`, 18 register sections) |
| Accounts & Finance | Spend | — | Expenses (`expenses`) |
| Accounts & Finance | Tax | — | Tax and discounts (`tax`) |
| HR & Payroll | People | — | HR Management (`hr`) |
| MIS & Reports | Library | — | Reports (`reports`), Scheduled reports (`scheduled`) |
| MIS & Reports | Analytics | — | Geography (`geo`), MoM & YoY (`compare`) |
| Administration | Access | — | Logins and employees (`users`), Roles & Permissions (`roles`) |
| Administration | Governance | — | Audit trail (`audit`), Settings & Administration (`settings`) |
| System Management | Platform | — | Module/feature availability (inside Settings), database reset (inside Settings) |

Deliberately **not** proposed:

- **Service & Workshop** — the brief lists it, but the repository has no booking,
  job-card, estimate, parts-issue or service-billing tables, services or routes.
  It must not be created as an empty menu entry. Verify the business need first
  (brief §4: add missing categories only after verifying requirements).
- **Quotation** — the sales flow in the brief starts at enquiry → quotation, but
  the code starts at lead → sales order. Adding a quotation document is a
  business decision with numbering, tax and accounting consequences.

Both are recorded as open questions in
[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md), not as work packages.

## 4. Workspace tabs

### 4.1 Model

- `Home` is a permanent, non-closable tab pinned first, showing `#/dash`.
- Selecting a menu item or deep link opens a tab whose **canonical key** is the
  view name (`dash` becomes `home`), extended with the section **only for
  Accounting & Finance**, whose register sections are real destinations
  (`accounts/gst-out`). Inventory, Scheduled reports and HR keep their in-page
  tabs inside one workspace tab, so switching an in-page tab never creates or
  destroys a workspace tab. Context objects (a customer, an order) open in the
  existing drawer, not as separate tabs, so the key stays stable and duplicates
  are impossible.
- Clicking an already-open feature activates its tab rather than opening a
  second copy (brief §7).
- Closing is per tab; `Close others` and `Close all except Home` are offered in
  the tab context menu; recently closed tabs can be reopened from the same menu
  for the current session.
- The active tab is reflected in the hash, so refresh and direct links keep
  working exactly as they do today.
- Tab order and the open set are kept in `sessionStorage`; a fresh login starts
  with Home only. Restoration re-checks `/api/auth/me` first, so a user who
  loses a permission cannot restore a tab they may no longer open.
- Unsaved form data: every form already lives in the shared drawer
  (`#drawer`, `openDrawer` at `static/js/app.js:150-189`). Closing a tab with the
  drawer open warns before discarding, mirroring the existing close behaviour.
- Overflow: when the strip exceeds the width, the remaining tabs move into an
  overflow menu; the strip scrolls horizontally on touch widths.

### 4.2 Accessibility

Tabs use the WAI-ARIA tabs pattern: `role="tablist"`, `role="tab"`,
`aria-selected`, `aria-controls`, left/right arrow keys, `Home`/`End`, and a
visible focus ring from the design system. Closing is available from the
keyboard, not only the mouse.

## 5. Favourites

- Favourites are per user and, once moved server-side, follow the user across
  browsers. The proposed table is `user_favourites` (`user_id`, `node_key`,
  `position`, timestamps), keyed on the navigation node rather than a feature.
  It is **deferred**: WP-4a's `0031_navigation_registry` creates only
  `nav_nodes` and `feature_registry`, and favourites stay device-local until
  owner decision D8 is approved (a later additive `0032`).
- A star control appears on each menu row on hover/focus, matching the reference;
  it must also be reachable by keyboard and announce its state.
- Favourites render as a pinned group above the modules. A favourite whose
  feature is switched off or whose permission is revoked is hidden, not shown
  broken.
- Until the registry exists, favourites are not shipped as a localStorage-only
  feature: a browser-only favourite list would contradict the brief's
  server-side source of truth.
  **Shipped 4 November 2026 with that deviation, deliberately and temporarily:**
  favourite keys and the recent-screen list live in `localStorage` under
  `hb.favourites:<username>` and `hb.recent:<username>`. They are device-local,
  never leave the browser, are re-filtered through the same visibility predicate
  as the menu on every render, and are dropped when the role loses the screen.
  Server-side favourites move with the registry (N3); until then the star on the
  page header is the only favourite control, so no menu row needs a hover-only
  hit target.

## 6. List-screen standard (from the GDMS reference)

The screenshots show one consistent list pattern. The following is adopted as
the Herbanova standard; it is a restyle of behaviour the app already has, not a
copy of the reference's code or styling.

1. **Filter band** at the top of the screen, in a labelled grid: required fields
   marked with an asterisk, selects for masters, paired date fields with the
   range control already used on the Overview, and free-text search.
2. **Search and Clear** as explicit buttons at the top right of the band
   (today most screens filter live on input and have no Clear). Clear resets to
   the screen's default window.
3. **Grid**: fixed header, zebra rows, one highlighted selected row, ellipsis on
   long cells, click to open the record in the drawer.
4. **Footer**: first / previous / `Page n of m` / next / last, a page-size selector
   (25/50/100/200, default 50 — the existing backend maximum), and an accurate
   `1–N of TOTAL` label from `X-Total-Count`. The shipped design uses a page
   *label* rather than a page *input*: the four buttons already reach every page,
   and a free number field adds a second validation path. Buttons disable at the
   ends rather than disappearing, and the strip is hidden while the count is
   unknown.
5. **Export**: one labelled export button per screen, using the existing CSV
   endpoints and permission checks. Excel format is a separate decision, not an
   assumed rename.
6. **Master-detail split** (as in the reference's message screen) only where the
   detail is genuinely useful beside the list, for example bank reconciliation
   matching; it is not applied to every list.
7. **Pagination must be server-side.** Today the client requests up to 200 rows
   and filters in the browser; the backend helper `app/core/pagination.py` is
   already used by eight endpoints and must be adopted by the rest before a
   footer pager is shown, otherwise the row count would be a lie.
   **Status 4 November 2026:** all eight list screens satisfy items 1-5 — server
   search and the screen's own filters, true `X-Total-Count`, footer pager and a
   CSV export of all matching rows. Products was the batch-1 pilot; batch 2
   moved suppliers, customers, sales orders, purchases, billing, approvals and
   leads onto the shared `LIST_SPEC` layer. Sortable headers exist on Products
   only: its endpoint accepts `sort` + `direction` through a whitelist, while
   the other seven endpoints keep their documented order.

## 7. Responsive behaviour

| Width | Behaviour |
|---|---|
| ≥1081 | Rail expanded, tabs on one row with overflow menu, filter band in its grid |
| 821–1080 | Rail still expanded; tabs fit or overflow into the `⋯` menu; filter band wraps |
| 601–820 | Rail becomes the horizontal module strip (implemented at ≤820); the tab row stays above it, tabs scroll and overflow into `⋯`; filter band wraps |
| ≤600 | Horizontal module strip, horizontal tab strip, single-column form rows and filter band, drawer 100%, pager nav row under the count |
| Print | Tabs, rail and pager hidden; the grid prints with its heading and filter summary |

The earlier draft expected an icon-only rail between 720 and 1079 px. That was
not built: the rail keeps its labels until it becomes a horizontal strip at
820 px, which is the breakpoint the shell already had. An icon rail is a
possible refinement, not part of N1, and it must not be documented as shipped
before it exists.

## 8. Security and permissions

- The menu and tabs are navigation, not security. Every API keeps its existing
  backend dependency; hiding a menu item never removes the check.
- Menu visibility is the intersection of role permission, feature switch,
  branch scope where applicable, and the feature's activation status.
- Tab restoration re-validates the session and feature switches before
  rendering anything. With the server tree active, `wsViewOk()` also requires
  the view to be in the server's visible set, so a restored tab from an older
  hierarchy cannot reopen a screen the server no longer offers.
- Favourites never store a URL that bypasses permission resolution — they store
  a feature key and are resolved through the same visibility rules as the menu.
- Server navigation is a narrowing filter, never a grant: the endpoint is
  already permission-filtered, and the route gate keeps its backend dependency.
  A failed or malformed response leaves the built-in permission-filtered menu
  (with a visible alert and **Retry**), never an unfiltered one.

## 9. Implementation path

| Step | Scope | Depends on |
|---|---|---|
| N1 | Tab strip, breadcrumbs, overflow and keyboard support in the current SPA; no schema change | — **shipped 4 Nov 2026, see §10** |
| N2 | List-screen standard: Search/Clear, server-side pagination adoption, footer pager, sorting on lists that need it | N1 (shared components) — **shipped 4 Nov 2026 for all eight lists (Products batch 1; suppliers, customers, sales orders, purchases, billing, approvals and leads batch 2). Sorting remains Products only, because the other seven endpoints expose no `sort`/`direction`** |
| N3 | Registry migration: modules, menu items, feature registry and favourites tables; `/api/navigation`; sidebar renders from the API with the current HTML as fallback. **Design complete 4 Nov 2026:** [FEATURE_REGISTRY_DESIGN.md](FEATURE_REGISTRY_DESIGN.md) (schema, seed parity, drift register, four implementation batches, rollback). **4a activated 4 Nov 2026** (tables and seed, `0031`); **4b implemented 4 Nov 2026** (`GET /api/navigation` and the read-only `GET /api/admin/navigation`, contract in design §6.1 and §6.3); **4c implemented 4 Nov 2026** — the sidebar reads `WS.navTree()` behind the `?nav=api` opt-in; **4d implemented 4 Nov 2026** — `NAV_API_ENABLED = true` makes the server tree the default for every browser, with `?nav=builtin` and the loading/error fallback as rollback | N2 |
| N4 | Feature-management screens (brief §6) and navigation validation | N3 |

Each step ships with tests and doc updates, and no step removes the existing
`#/view` routes.

## 10. What shipped in WP-2 (4 November 2026)

### 10.1 Files

| File | Change | Role |
|---|---|---|
| `static/js/workspace.js` | **new, 376 lines** | Pure workspace model, shared by the browser and Node: `NAV` hierarchy, `TITLES`, `VIEW_PERM`, `VIEW_FEATURE`, `viewAllowed`, `menuAllowed`, `parseHash`, `openTab`/`closeTab`/`closeOthers`/`closeAll`/`reopenClosed`, `pruneModel`, `serializeModel`/`deserializeModel`, `toggleFavourite`, `pushRecent`, `crumbPath`. No DOM, no network, no storage |
| `static/js/app.js` | +~420 lines, no renderer rewritten | Rendering and events only: `wsEnter`/`wsSync` (`:828`, `:1071`), `renderTabs`/`fitTabs` (`:918`, `:940`), tab menu (`:959`, `:974`), `renderCrumbs` (`:992`), `renderSideNav`/`renderNavExtra`/`renderFavBtn` (`:1019`, `:1042`, `:1056`), dirty snapshot and guards (`:861`-`:891`), tab clicks and keys (`:12424`-`:12468`), unload guard (`:12480`), palette screen group (`:2908`) |
| `static/index.html` | tab bar, breadcrumb nav, favourite button, empty sidebar nav, `workspace.js` before `app.js` | `:160-164` (tab bar, `⋯` and menu), `:166-168` (empty `#sideNav`), `:178` (breadcrumb), `:183` (favourite), `:1668-1669` (scripts) |
| `static/css/styles.css` | tab bar/strip/tab/overflow/crumbs/favourite rules, shell rows, mobile block, print block | `:156-190`, `:420-430`, `:1169` |
| `tests/js/workspace.test.cjs` | **new** | 17 `node:test` cases for the model: keys, dedupe, close/open/reopen, pruning, serialisation, favourites, recents, breadcrumb paths |
| `tests/test_workspace_model.py` | **new** | Runs `node --test tests/js/workspace.test.cjs` from pytest and fails on 0 passes, so one entry point covers both suites |
| `pytest.ini` | **new, 3 lines** | `testpaths = tests`. Without it pytest imports `var/probe/serve_test.py`, which matches the default `*_test.py` pattern and calls `uvicorn.run()` at import, so collection never finishes |

The hierarchy is **one definition** in `workspace.js`; the sidebar, breadcrumb and
palette screen list all read it, so a path shown in the breadcrumb is a path in
the menu, and every placement resolves to an existing route. No screen was
duplicated, no iframe was introduced and the 11,000-line renderer was not
rewritten.

### 10.2 Behaviour

- **Tabs.** Home is pinned and not closable. Every routed screen opens one tab,
  keyed by view (Accounting sections add their section key). Re-opening an open
  screen activates it. Two separate bounds apply:
  - **The model keeps at most 20 tabs, Home included.** Opening a 21st distinct
    screen evicts the oldest screen after Home and pushes it to the top of the
    reopen list (last 10), so *Reopen closed tab* brings it straight back. Home
    is never evicted. The eviction happens inside `openTab`, so a restored
    session cannot exceed the bound and a reopen at the bound evicts rather than
    loses (pinned by the Node test added 4 November 2026).
  - **The strip is bounded by width, not count.** `fitTabs()` marks tabs that do
    not fit with the `away` class, which takes them out of the visible row and
    leaves them open. It works from the right-hand end inwards, never hides the
    active tab, and hides Home only when Home is the only tab left. Every hidden
    tab is still listed in the `⋯` menu, which also carries *Close current tab*,
    *Close other tabs*, *Close all except Home* and *Reopen closed tab*.
- **Keyboard.** `role="tablist"` with roving `tabindex`; ArrowLeft/ArrowRight
  wrap and Home/End jump, and focus moves **and activates** in one step
  (automatic activation, the ARIA tabs pattern); a click does the same. There is
  no separate Enter/Space step. Delete/Backspace close the focused tab (Home
  refuses). The close button is a real button inside the tab, so it is
  reachable without the mouse. Escape closes the tab menu.
- **Persistence and deep links.** `sessionStorage["hb.tabs:<username>"]` holds
  the open tabs and the active key. A refresh restores them, then the route is
  re-validated: a stored tab for a screen the role may no longer open is pruned
  silently. The hash stays the single source of the active screen, so
  `#/accounts/gst-out?due=week` and every existing bookmark keep working; a
  forbidden deep link is rewritten to `#/dash` with `history.replaceState` so no
  permission-shaped address is left behind.
- **Unsaved changes.** The shared drawer snapshots its controls on open. Closing
  the drawer (X, scrim, Escape), closing a tab, switching tabs, closing siblings
  and the browser back/forward hash change all ask before discarding when a
  control changed. A page unload with a dirty drawer triggers the browser's own
  confirmation. Programmatic closes after a successful save remain unguarded.
- **Breadcrumbs.** Module → Category → Group → screen, read from `NAV`. Each
  ancestor links to the first screen the role may open at that level; a level
  with no allowed target renders as plain text. An Accounting section shows its
  own label as the last crumb.
- **Favourites, recents and search.** A star in the page header toggles the
  current screen for the signed-in username; favourites and the last six
  screens render above the modules. Both lists are re-filtered by the same
  visibility predicate as the menu. The global palette now leads with matching
  **screens** before record results, and opens on that list.

### 10.3 Screens the role cannot open

`viewAllowed` is the single predicate used by `route()`, the menu, the
breadcrumb, the tab restore, the favourite/recents lists and the palette. It
intersects the permission, the feature switch and the few narrower menu rules
(Settings, Reports, Scheduled reports). Hiding a screen here is navigation, not
security: every API keeps its backend dependency. The browser walk proves both
halves — a viewer's menu, tab restore, deep link and breadcrumb never offer a
forbidden screen, and when a session is swapped under a live document the
server refuses the stale reads (`403`) while the fresh viewer page renders no
accounts content.

### 10.4 Tests and evidence

- `node --test tests/js/workspace.test.cjs` — 18 pass, 0 fail (the 18th pins the
  20-tab bound and that an evicted tab stays in the reopen list).
- `pytest tests/test_workspace_model.py` — 1 pass (the wrapper).
- Full `pytest` — **468 passed, 0 failed, 0 skipped in 239.05 s**, exit 0
  (`var/reports/wp2b-pytest.xml`, run after the 20-tab eviction fix)
  (`var/reports/wp2-pytest.xml`, 4 November 2026).
- `var/shots/wp2walk.py` — **42 checks, 42 pass**, against a temp backend on the
  test database, driven through headless Chrome. It covers the pinned Home tab,
  the five menu modules, tab opening/dedupe/switching, Accounting section tabs,
  overflow and its menu, every close action, reopen, arrow/Delete keys,
  favourites, recents, reload restore, palette screens, the dirty-drawer and
  dirty-tab guards, a deep link with a query and its refresh, the viewer
  permission probes, and the network/console evidence.
- Screenshots in `var/shots/`: `wp2-tabs-1440-light.png`,
  `wp2-tabs-1440-dark.png`, `wp2-tabs-768-light.png`,
  `wp2-tabs-390-light.png`, `wp2-crumbs-1440-light.png`,
  `wp2-overflow-1440.png`, `wp2-favourites-1440.png`, `wp2-palette-1440.png`,
  `wp2-dirty-1440.png`, `wp2-viewer-1440.png`.
- The walk recorded **227 API responses at `200`** in the signed-in segment, **0
  page errors**, **0 console events**, and exactly **14 refused calls** during
  the deliberate session swap to the viewer (`403`), which are the expected
  refusals described in §10.3 rather than failures
  (`var/reports/wp2-browser.json`).

### 10.5 Deviations recorded rather than hidden

1. **Favourites are device-local** (`localStorage`) until the registry supplies
   the server table. See §5.
2. **The rail is never collapsed to icons.** It keeps its labels at every width
   where it exists and becomes a horizontal module strip at ≤820 px
   (`styles.css:412-436`). The draft expected an icon-only rail between 720 and
   1079 px; that was not built. See §7.
3. **Tab keys are per view, with sections only for Accounting.** Section-level
   tabs for every screen would multiply tabs for in-page tab sets that the
   existing screens already manage. See §4.1.
4. **The open-tab list is restored from `sessionStorage`, not the server.** It is
   a per-user, per-browser convenience; the registry phase (N3) can move it to
   the server if tabs are meant to follow the user across devices.

### 10.6 Rollback

WP-2 is **not committed** at the time of writing: everything below is in the
working tree of `feature/gap-closure`, alongside the uncommitted WP-3 batches.
(When WP-2 was written the chain sat at `eaf38d2`; after the accounting
gap-closure commit the current HEAD is `77f5a96`.) No migration, table, route or
API was added, so the rollback is a code revert with two distinct scopes.

**WP-2 only** (the files this package created or touched):

| File | Undo |
|---|---|
| `static/js/workspace.js` | delete (new file) |
| `tests/js/workspace.test.cjs` | delete (new file) |
| `tests/test_workspace_model.py` | delete (new file) |
| `pytest.ini` | delete (new file; only `testpaths = tests`) |
| `static/index.html`, `static/js/app.js`, `static/css/styles.css` | `git checkout -- <file>` would also discard WP-3 work in these files, so revert only the WP-2 hunks by hand. The pre-WP-2 copies sit in `var/backups/baseline-20261103T175350/herbanova-source-eaf38d2.tar.gz`, but they are also pre-WP-3, so unpacking them rolls WP-3 back as well |
| `docs/*`, `docs/user-manual/*` | revert the WP-2 sections (§30, §1.13, F-139, R-135, §5.2, this §10) |

**Everything uncommitted, WP-2 and WP-3 together:** `git stash push -u` (keeps
the work recoverable) or `git checkout -- .` plus deleting the four new files.
Neither is authorised by this document; a destructive command needs the owner's
explicit approval.

After a WP-2 revert the SPA behaves as it did before: the previous sidebar HTML,
the single-view router and the old styles return, and every existing screen and
route works unchanged. Browser state left behind is inert:
`hb.tabs:*` in sessionStorage expires with the tab, and `hb.favourites:*` /
`hb.recent:*` in localStorage are ignored by the reverted code.

One defect found by the walk was fixed before sign-off: `renderApprovals`,
`renderLeads`, `renderSales` and `renderDash` updated sidebar badges by id, and
the rebuilt sidebar no longer creates a badge for a screen the role cannot see,
so a viewer boot threw on `#apCount`. Badges now go through `setBadge()`, which
returns quietly when the row is absent.

## 11. What shipped in WP-4 Batch 4c (4 November 2026)

### 11.1 Opt-in, not a replacement

| Piece | Where | Behaviour |
|---|---|---|
| `NAV_API_ENABLED = false` | `static/js/app.js` | The release default for every browser; no fetch, no change |
| `?nav=api` / `?nav=builtin` | `app.js` `navChoice()` | Puts the choice in `sessionStorage["hb.navApi"]` so a later hash change cannot drop it |
| `navFromApi(payload)` | `static/js/workspace.js` | Converts Modules → Categories → Groups → Screens into the existing shape; drops unknown and duplicate views; `null` means the built-in `NAV` |
| `navTree()`, `navAllows()`, `navInMenu()` | `workspace.js` | Every reader (rail, palette, breadcrumb, route gate) goes through these, so the two hierarchies never mix |
| `navFetch()` / `navRefresh()` | `app.js` | Fetch and Retry; `wsViewOk()` additionally requires `navAllows(view)` while the server tree is active |
| `.nav-alert` | `static/css/styles.css` | Loading and failure notice above Favourites; full width on mobile |

### 11.2 Failure behaviour

- `401`: no menu of its own; `api()` has already ended the session.
- Network error / non-2xx: state `error`, alert **"The menu could not be loaded"**
  with the HTTP status, **"Showing the built-in menu for this role."**, a
  **Retry** button, and the built-in permission-filtered rail.
- Malformed or empty payload: the same alert with
  **"The server sent a menu this screen cannot read."**
- No path renders every module, and no path leaves the rail blank.
- A sequence number and the username captured at send time discard a late
  answer from a previous account; login, logout and a role save reset the tree.

### 11.3 Verified

Browser walk on a test-database stack, `var/reports/wp4c-browser.json`:
**199/199** (WP-2 42, 21st-tab 20, WP-3 lists 51, navigation 86).

| Role | Built-in | API | Server screens |
|---|---|---|---|
| Administrator | 21 | 21 | 25 |
| Sales | 16 | 16 | 18 |
| Inventory | 14 | 14 | 16 |
| Viewer | 11 | 11 | 13 |
| HR manager | 5 | 5 | 5 |

Per role the API rail equals the server's `in_menu` set exactly, is a subset of
the built-in menu, and contains no duplicate. The walk also covers breadcrumbs
from the server tree, one tab per accounting section, favourites across a
reload, the palette, the eight WP-3 lists, all 19 accounting sub-sections, a
deep link with refresh and back/forward, 1440/768/390 px, both themes,
`200 → 304`, a simulated `503` with a successful **Retry**, anonymous `401`,
and no uncaught errors.

### 11.4 Rollback

1. **Instant, no code:** leave `NAV_API_ENABLED = false` (already the default)
   and clear `hb.navApi` from the browser session. The rail is the built-in one.
2. **Remove the code:** revert the 4c hunks in `static/js/workspace.js`
   (active-hierarchy block and its exports), `static/js/app.js` (navigation
   block, `wsViewOk`, `renderSideNav`, `enter`/`leave`, role-save refresh,
   click handler) and the `.nav-alert` rules in `static/css/styles.css`;
   restore `app/services/feature_store.py`, `tests/test_feature_dependencies.py`
   (delete), `tests/test_navigation_registry.py` and `tests/test_profit_loss.py`.
3. No database change exists to undo: 4c added no table, row, column or
   migration. The `0031` rollback remains the 4a procedure.

## 12. What shipped in WP-4 Batch 4d (4 November 2026)

### 12.1 The default, and the two ways back

| Piece | Where | Behaviour |
|---|---|---|
| `NAV_API_ENABLED = true` | `static/js/app.js` | The server tree is requested on sign-in and after a role save; no query needed |
| `?nav=builtin` | `app.js` `navChoice()` | Writes `sessionStorage["hb.navApi"] = "builtin"`; the rail is the built-in `NAV` for that session until `?nav=api` |
| Loading | `app.js` `navReset()` | The built-in, permission-filtered rail is drawn while the request is in flight, so the rail is never blank |
| Failure | `app.js` `navFallback()` | The built-in rail is kept with the alert and **Retry**; no path renders every module |
| `wsViewOk()` | `app.js` | `WS.viewAllowed(...) && WS.navAllows(...)` while the server tree is active, so the payload can only hide screens, never reveal one |

The built-in hierarchy in `workspace.js` is unchanged and remains the fallback;
the SPA, the router, the tab strip, breadcrumbs, favourites, recents and the
palette were not rewritten. A browser that has no server answer still sees the
same menu it saw before Batch 4a.

### 12.2 The `scheduled` discrepancy, resolved without weakening RBAC

`Scheduled reports` is guarded by `require_admin("email:manage")`
(`app/core/rbac.py`), not by a permission alone, and `email:manage` is refused
to non-Administrator roles. A restored dump or direct SQL can still write that
permission onto a custom role, and the registry records permissions only.

- `ADMIN_ONLY_VIEWS = {"scheduled"}` in `app/services/navigation_catalog.py`.
- `narrow_admin_only(visible, nodes, admin=...)` in
  `app/services/navigation_registry.py` removes those screens for every caller
  who is not the Administrator. `/api/navigation` computes `is_admin(db, user)`
  and applies it before pruning empty branches.
- `navigation_etag(..., admin=...)` includes Administrator status in the ETag
  identity, so a promotion or demotion cannot be served a stale `304`.
- No route gate was loosened: the endpoint offers strictly less than the
  built-in menu, and the route still refuses a non-Administrator. The built-in
  menu already required `srAllowed` (role `admin`); the server is now the
  authority and can only agree or narrow.

### 12.3 Parity proof

`tests/test_navigation_parity.py` evaluates the shipped `workspace.js` in Node
(`tests/js/nav_parity.cjs`) against the real endpoint body, so the comparison is
between the code the browser runs and the payload it receives, not a second
Python reimplementation.

- Five seeded roles (`admin`, `sales`, `inventory`, `viewer`, `hr_manager`):
  identical view and menu sets; `/api/auth/me` permissions agree.
- **173 synthetic combinations**: the 5 seeded roles, every single gate
  permission (17), every pair of them (136), each feature switched off (14)
  and all features off (1). Every case: no duplicate, no unknown view, and the
  server never offers a screen the built-in rules would hide.
- Home and the `distributors` alias stay present; hidden routes (`tax`, `users`,
  `audit`, `compare`) stay addressable but out of the menu; a feature switch
  removes the screen and its permissions; `foc` closes when `stock` is off; a
  custom role holding `email:manage` still does not receive `scheduled`.
- Admin parity: the Administrator receives all 25 registered screens and
  `scheduled`; every other role does not.

### 12.4 Verified

Browser walk on a test-database stack, `var/reports/wp4d-browser.json`:
**226/226** (WP-2 42, 21st-tab 20, WP-3 lists 51, navigation 113).

| Role | Built-in | Server tree | Server screens | Modules |
|---|---|---|---|---|
| Administrator | 21 | 21 | 25 | 5 |
| Sales | 16 | 16 | 18 | 5 |
| Inventory | 14 | 14 | 16 | 5 |
| Viewer | 11 | 11 | 13 | 5 |
| HR manager | 5 | 5 | 5 | 4 |

With no query parameter the rail equals the server's `in_menu` set exactly and
no alert appears. The walk also proves: `?nav=builtin` and its persistence
across in-app navigation, `?nav=api` re-opting in, all 25 screens opening with
the right title, the palette by keyboard, an account switch (Viewer deep link to
`#/scheduled` falls back to Home), breadcrumbs, one tab per accounting section,
favourites across a reload, the eight WP-3 lists, all 19 accounting sub-sections,
deep link with refresh and back/forward, 1440/768/390 px in both themes,
`200 → 304`, 401, three forced failures (503, network reject, malformed JSON)
each with alert and successful **Retry**, and a live permission change that
removes a screen from the menu and closes its tab. No uncaught page errors.

### 12.5 Rollback

1. **Instant, no code:** set `NAV_API_ENABLED = false` (one line,
   `static/js/app.js`) or open the app with `?nav=builtin`. The rail is the
   built-in `workspace.js` menu; no server call is needed.
2. **Per browser:** `sessionStorage.removeItem("hb.navApi")`; the next sign-in
   follows the release default again.
3. **Remove the code:** revert the 4d hunks in `static/js/app.js`
   (`NAV_API_ENABLED`), `app/api/navigation.py`, `app/services/navigation_registry.py`
   and `app/services/navigation_catalog.py`; delete
   `tests/test_navigation_parity.py` and `tests/js/nav_parity.cjs`. The 4c
   model and fallback stay in place and behave exactly as they did.
4. No database change exists to undo: 4d added no table, row, column or
   migration.
