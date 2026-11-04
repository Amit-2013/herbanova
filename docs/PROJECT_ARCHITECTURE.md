# Herbanova — project architecture

**Phase 1 audit of the master architecture brief, 4 November 2026.**

This document records what the repository actually contains. It is a read-only
audit: no code, schema or data was changed to produce it. Every number below was
read from the working tree at `feature/gap-closure` (merged to `master` as
`9ddfe2c`), Alembic head `0030_sign_in_content`. Where a figure could not be
established without querying a live database, the document says so.

Related: [PRODUCT_MAP.md](PRODUCT_MAP.md),
[FEATURE_INVENTORY.md](FEATURE_INVENTORY.md),
[DATABASE_TABLE_COLUMN_REGISTER.md](DATABASE_TABLE_COLUMN_REGISTER.md),
[REQUIREMENTS_TRACEABILITY_MATRIX.md](REQUIREMENTS_TRACEABILITY_MATRIX.md),
[permissions-matrix.md](permissions-matrix.md),
[NAVIGATION_AND_TAB_DESIGN.md](NAVIGATION_AND_TAB_DESIGN.md),
[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md),
[FEATURE_REGISTRY_DESIGN.md](FEATURE_REGISTRY_DESIGN.md) (WP-4 design; not yet
implemented).

---

## 1. Runtime topology

Two processes and one database:

| Process | Entry point | Port | Responsibility |
|---|---|---|---|
| API backend | `scripts/run_backend.py` → `app.main:app` (uvicorn) | 8000 by default | Database, session cookie, permissions, every `/api` route |
| Web frontend | `scripts/run_frontend.py` | 3000 by default | Serves the SPA and proxies `/api` to the backend so the browser keeps one origin and a first-party cookie |
| E-mail worker | `app/email_worker.py` | — | Sends queued mail from `email_deliveries` |

The backend also mounts the static SPA directly at `/ui` (`app/main.py:129`),
so both `:8000/ui` and `:3000/ui` work in development. Stack: FastAPI,
SQLAlchemy 2.x, PostgreSQL 17, Alembic, uvicorn, vanilla JavaScript with no
build step. See [RUNNING_SERVERS.md](RUNNING_SERVERS.md).

## 2. Backend composition

- `app/main.py` registers 39 routers (`app/main.py:87-125`). Thirty-five files
  live in `app/api/`; `costs`, `db_reset`, `email_reports` and `signin` each
  contribute two router objects, which is why the include count exceeds the
  file count.
- **341 route decorators** across `app/api/*.py`, plus two routes declared on
  the app itself (`/api/health`, `/`). 322 decorators sit on primary routers and
  19 on secondary ones. At runtime FastAPI registers **344 `APIRoute` objects
  over 268 distinct paths** (267 `/api` paths plus `/`); `len(app.routes) = 349`
  adds four framework routes (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`,
  `/redoc`) and the static `/ui` mount. The decorator count is an AST figure;
  344 is the authoritative runtime count used by the WP-4 validation.
- Business logic is in `app/services/` (48 modules): accounting, costing, GST,
  statutory dues, payroll, ledger, periods, export, e-mail render/schedule,
  HR documents and approvals, PDF, TOTP.
- Shared concerns are in `app/core/`: `permissions.py`, `rbac.py`,
  `features.py`, `module_register.py`, `pagination.py`, `rules.py`, `security.py`,
  `limiter.py`, `downloads.py`, `india_states.py`, `config.py`, `db.py`.

### 2.1 Routes per API file

| File | Routes | File | Routes |
|---|---:|---|---:|
| `hr.py` | 101 | `users.py` | 5 |
| `ledger.py` | 26 | `costs.py` | 4 |
| `email_reports.py` | 18 | `distributors.py` | 4 |
| `signin.py` | 16 | `email_settings.py` | 4 |
| `accounts.py` | 12 | `employees.py` | 4 |
| `expenses.py` | 11 | `roles.py` | 4 |
| `gst.py` | 11 | `approvals.py` | 3 |
| `tax.py` | 11 | `audit.py` | 3 |
| `foc.py` | 9 | `periods.py` | 3 |
| `leads.py` | 9 | `reports.py` | 3 |
| `auth.py` | 8 | `admin.py` | 2 |
| `invoices.py` | 8 | `features.py` | 2 |
| `sales_orders.py` | 8 | `modules.py` | 1 |
| `db_reset.py` | 7 | `credit_notes.py` | 5 |
| `suppliers.py` | 7 | `debit_notes.py` | 5 |
| `dashboard.py` | 6 | `inventory.py` | 5 |
| `printing.py` | 6 | `products.py` | 5 |
| | | `purchase_orders.py` | 5 |

URL prefixes are declared in each `APIRouter(...)`, not at include time
(`app/main.py:87-125`). Four files share the `/api/accounts` prefix
(`accounts.py:35`, `gst.py:27`, `ledger.py:22`, plus
`costs.py:27-28` and `periods.py:20` for sub-paths). `app/main.py:43-58` also
carries the feature-switch middleware and `:129` the `/ui` mount.

## 3. Data layer

- **87 SQLAlchemy model classes**, each with a distinct `__tablename__`:
  `core.py` 22, `hr.py` 28, `accounts.py` 12, `email.py` 6, `signin.py` 4,
  `tax.py` 3, `suppliers.py` 3, `expenses.py` 3, `foc.py` 2, `users.py` 2,
  `costs.py` 1, `settings.py` 1.
- The same 87 table names appear in `create_table(...)` calls across
  `alembic/versions/`; no table exists only in a model or only in a migration.
- 87 tables plus `alembic_version` gives the **88 public tables** recorded in
  [DATABASE_TABLE_COLUMN_REGISTER.md](DATABASE_TABLE_COLUMN_REGISTER.md) and
  [PRODUCT_MAP.md](PRODUCT_MAP.md).
- **43 migration files**, head `0030_sign_in_content`
  (`alembic/versions/0030_sign_in_content.py:29-30`, down-revision `0029_totp`).
  Test and development databases are at 0030; production is still at
  `0028_advances` and is migrated only as a separate, approved step.
- Foreign keys and columns are documented in the 2,116-line table register
  (53 explicit FK references). A dedicated relationship map does not yet exist;
  see gap G-09 in [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md).

## 4. Authentication and sessions

- Session cookie authentication (`app/core/rbac.py:57-72`), with
  `token_version` revocation and a forced-password-change gate
  (`require_login`, `rbac.py:112-116`).
- Administrator two-factor is backend-enforced TOTP (`app/services/totp.py`,
  `app/api/auth.py`), added by migration `0029_totp`. Normal users keep the
  ordinary login path.
- **330 of 341 route decorators carry an explicit auth/permission dependency.**
  The 11 without one are deliberate public endpoints: login and 2FA steps
  (`auth.py:118,156,175,204`), logout (`auth.py:255`), published sign-in content
  and its image/legal routes (`signin.py:145,174,187`), two token-addressed
  unsubscribe routes (`email_reports.py:512,535`), and the retired
  `POST /api/db/reset` that now returns 410 (`db_reset.py:91-96`).
  `/api/health` and `/` are public by design (`app/main.py:141,145`).
- Logins, lockouts, TOTP events and password changes are audited
  (`app/api/auth.py:113,128,144,151,196,237,287`).

## 5. Authorisation

- **49 permission keys** in one catalogue (`app/core/permissions.py:15-66`),
  written `module:action`, with a parent/child map (`:79-129`) and five
  Administrator-only keys (`:135-143`).
- Enforcement is per-route through FastAPI dependencies in
  `app/core/rbac.py`: `require(perm)` (`:102-109`), `require_admin(perm)`
  (`:91-99`) and `require_login` (`:112-116`). There is no blanket app-wide
  guard; each route declares its own, which is why the coverage check in §4
  matters.
- Role-to-permission grants are database rows (`roles.permissions` JSON,
  `app/models/users.py:21-29`), resolved per request (`rbac.py:33-54`) and
  edited through `/api/roles` (`app/api/roles.py:94-154`). Four baseline roles
  (admin, sales, inventory, viewer) are frozen in code
  (`app/core/permissions.py:188-242`); further roles are data.
- Effective permissions are intersected with switched-off features
  (`app/core/rbac.py:44-54`), so disabling a feature removes its rights as well
  as its middleware access.

## 6. Feature switches

- `feature_flags` table (`app/models/settings.py:15-22`, migration
  `0016_feature_flags.py`); a missing row means the feature is on
  (`app/services/feature_store.py:15-21,46-52`).
- **14 static `Feature` entries** (`app/core/features.py:38-132`), each with a
  key, label, description, view list, permission list, API prefixes and a
  `locked` flag (`users` is locked on).
- Middleware returns 403 for a switched-off API prefix (`app/main.py:43-58`).
- Administration API: `GET /api/features`, `PATCH /api/features/{key}`,
  Administrator only and audited (`app/api/features.py:34-54`).
- `app/core/module_register.py` is **not** a registry: it is a hardcoded list of
  18 delivery modules (MOD-01…MOD-18) with a status letter and a group, served
  read-only by `GET /api/modules` (`app/api/modules.py:16-19`) for the Overview
  "Modules and totals" panel.

## 7. Audit trail

- One writer: `audit(...)` in `app/services/audit.py:8-15` inserts an
  `AuditLog` row (`app/models/core.py:183-190`), strips secret keys and queues a
  Telegram notification.
- **189 call sites** (174 in `app/api/*`, 15 in services), covering auth, users
  and roles, masters, purchasing, stock, sales, billing, notes, printing,
  approvals, leads, accounts, receipts, vouchers, bank reconciliation, expenses,
  FOC, GST/statutory, year close, cost corrections, HR, e-mail scheduling,
  sign-in content, feature switches and admin secrets.
- Read side: `GET /api/audit`, `/api/audit/actions`, `/api/audit/export`, all
  under `audit:read` (`app/api/audit.py:73,80,93`).
- The guarded database reset does not write an audit row; it classifies
  `audit_log` as an immutable table instead (`app/services/db_reset.py`).

## 8. Frontend composition

One SPA, no framework, no build step:

| Asset | Size | Role |
|---|---|---|
| `static/index.html` | 1,670 lines | Shell, 25 `section.view` panels, 56 tables, 50 filter toolbars, 23 export buttons, tab bar, breadcrumb, drawer, palette, dialogs |
| `static/js/app.js` | 12,644 lines | Router, API clients (`apiPage`/`api`), render functions, workspace rendering and events, drawers, theme, palette |
| `static/js/workspace.js` | 376 lines | Pure workspace model shared with the Node tests: hierarchy, permissions, tab model, breadcrumb path, serialisation. No DOM, no network, no storage |
| `static/css/styles.css` | 1,175 lines | Design tokens, shell, components, tab bar, dark theme, responsive and print rules |

- **25 routed views** listed in `TITLES` (`static/js/workspace.js`, re-exported by
  `static/js/app.js`): overview, products, inventory, purchasing, suppliers,
  tax, sales, billing, accounts, expenses, foc, approvals, customers, leads,
  lost, follow-ups, reports, hr, settings, roles, users, audit, MoM/YoY
  comparison, geography, scheduled reports.
- Hash routing (`#/view/section?query`) with a `hashchange` listener
  (`app.js:12631`); unknown or unauthorised routes fall back to the overview
  (`app.js:718`). Deep links and refresh work because `boot()` re-authenticates
  and re-routes; a deep link that names a forbidden screen is rewritten to
  `#/dash` before rendering.
- Permission gating: `VIEW_PERM` and `VIEW_FEATURE` live in
  `static/js/workspace.js` and feed one predicate, `viewAllowed`, used by the
  route, the menu, the breadcrumb, tab restore, favourites/recents and the
  palette. Hidden still does not mean protected — the backend re-checks.
- Two API clients: `apiPage()` returns the parsed body, the status and the
  numeric `X-Total-Count` so a list can print the server's total; `api()` wraps
  it for callers that do not need the count. All eight list screens read one
  server page and print that count: Products through its own
  `loadProductList`/`productSort`/`exportProductsCsv`, and suppliers,
  customers, sales orders, purchases, billing, approvals and leads through the
  shared `LIST_SPEC` layer (`loadList`, `pagerHtml`, `exportListCsv`). Every
  list endpoint is paged by `app/core/pagination.py`. The last seven moved in
  WP-3 batch 2 on 4 November 2026; the WP-3 status, per-screen filters and
  evidence are in [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md).
- One shared drawer (`#drawer`, `static/index.html:1633-1637`;
  `openDrawer` at `app.js:150-189`, 96 call sites) carries almost every form.
- A server-side command palette (`Ctrl/Cmd+K`, `#palette`) searches products,
  distributors, sales orders, invoices, purchase orders, suppliers and leads
  through `GET /api/dashboard/search` (`app/api/dashboard.py:585-653`), filtered
  by permission, max five hits per group.
- Light and dark themes via `data-theme` and `localStorage["hb.theme"]`
  (`app.js:2560-2574`, `11787-11792`); tokens in
  [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

## 9. Navigation as built

- The menu is **rendered from one hierarchy in `static/js/workspace.js`** into
  `#sideNav` at sign-in and whenever the role changes: five modules, each with
  categories and groups, ending in the 25 existing views. `menuAllowed` filters
  each row by permission, feature switch and a few narrower menu rules, so the
  markup no longer has to be edited to hide or reorder a stage of the tree.
  The hierarchy is seeded in migration `0031` (64 nodes, 14 features) and served
  read-only by `GET /api/navigation` (`app/api/navigation.py`). Since Batch 4d
  the sidebar reads that tree by default; `workspace.js`'s built-in `NAV` is
  drawn while the request is in flight, kept on failure with **Retry**, and
  restored for a session with `?nav=builtin`. The endpoint removes
  Administrator-only screens (`ADMIN_ONLY_VIEWS`, `narrow_admin_only()`) for
  every other role and includes that flag in the ETag, so the server tree can
  only narrow the built-in rules, never widen them.
- **Workspace tabs** sit between the top bar and the page: Home is pinned, each
  screen is one tab keyed by view (Accounting adds its section), the active tab
  follows the hash, and the strip persists in `sessionStorage` per username.
  Tabs that do not fit move into the `⋯` menu, which also carries the close and
  reopen actions.
- **Breadcrumbs** show Module → Category → Group → screen and link each ancestor
  to the first screen the role may open at that level.
- **Favourites and recent screens** render above the modules; the star in the
  page header toggles the current screen. They are device-local until the
  registry supplies the server table.
- In-page tabs still exist inside individual screens (inventory, scheduled
  reports, HR profile, report picker) and stay one workspace tab.
- Link visibility and tab restore use the same client predicate as the route
  while the **backend re-checks every request**; the browser walk proves a
  limited role is refused by the API even when a stale document asks.
- The full design, deviations, tests and evidence are in
  [NAVIGATION_AND_TAB_DESIGN.md](NAVIGATION_AND_TAB_DESIGN.md) §10.

## 10. Integrations

- SMTP e-mail through a database-backed worker with retries
  (`app/services/mailer.py`, `email_worker.py`, `schedule.py`); test mode is used
  in development.
- Telegram notifications on audited events (`app/services/telegram.py`).
- PDF generation for invoices, notes, vouchers and HR letters
  (`document_pdf.py`, `reports_pdf.py`, `salary_slip.py`).
- Public sign-in content and banner images (`app/api/signin.py`), with uploads
  validated by PIL, capped at 2 MB and served through a public route rather than
  the static mount.

## 11. Tests and verification

- 57 `test_*.py` files plus `tests/conftest.py` under `tests/`, and two Node
  files under `tests/js/` (one suite, one manifest emitter).
- The suite drops and rebuilds `herbanova_bcs_test`, then runs
  `alembic upgrade head` (`tests/conftest.py:17-54`); tokens are minted directly
  to avoid login and 2FA (`:86-119`).
- Last recorded full run: **525 passed, 0 skipped, 0 failed** on 4 November 2026
  (`python -m pytest -q -rs --junitxml=var/reports/wp4b-pytest.xml`, exit 0,
  219.03 s; [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) §35), after the
  navigation API and its 26 tests were added. The 3 skips in the earlier §32
  run are gone because migration `0031` is now active. Node suites: **18
  passed**.

## 12. Documentation estate

| Area | Document |
|---|---|
| Product and screens | [PRODUCT_MAP.md](PRODUCT_MAP.md) |
| Feature register (142 rows) | [FEATURE_INVENTORY.md](FEATURE_INVENTORY.md) |
| Requirements and traceability (135 rows) | [REQUIREMENTS_TRACEABILITY_MATRIX.md](REQUIREMENTS_TRACEABILITY_MATRIX.md) |
| Tables and columns (88 tables at `0030`, 90 at `0031`) | [DATABASE_TABLE_COLUMN_REGISTER.md](DATABASE_TABLE_COLUMN_REGISTER.md) |
| Roles and permissions | [permissions-matrix.md](permissions-matrix.md) |
| Field-by-field UI/API mapping | [FRONTEND_BACKEND_FIELD_MAPPING.md](FRONTEND_BACKEND_FIELD_MAPPING.md) |
| Formulas and business rules | [FORMULA_AND_BUSINESS_RULE_REGISTER.md](FORMULA_AND_BUSINESS_RULE_REGISTER.md) |
| Design system | [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) |
| Verification evidence | [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) |
| Operations | [RUNNING_SERVERS.md](RUNNING_SERVERS.md), [DB_RESET.md](DB_RESET.md), [ADMIN_2FA.md](ADMIN_2FA.md) |
| Manuals | [user-manual/](user-manual/) |

## 13. Structural gaps found by this audit

The architecture is sound where it exists: permissions are server-enforced,
accounting is posted through services, and feature switches cut both UI and API.
The gaps are structural rather than business-logic defects:

1. Navigation is not configurable — the menu lives in HTML and a code deploy is
   needed to change it (brief §4, §6).
2. There is no feature registry in the database; the 14 static `Feature` entries
   and the 18-entry module register are two partial views of the same idea.
3. The workspace shell (tabs, breadcrumb, favourites, recents) shipped in WP-2 on
   4 November 2026. Navigation is still defined in code rather than a database
   registry, and favourites are device-local until the registry lands
   (brief §7 — the remaining half is WP-4).
4. List screens share server-side pagination, search, status filters, page size
   and CSV export, but not column configuration or row selection (brief §14).
   All eight lists moved onto the shared layer in WP-3 (Products in batch 1,
   the other seven in batch 2, 4 November 2026). Sorting by column header
   remains Products only: its API accepts `sort` plus `direction` from a
   whitelist with NULLS LAST, while the other seven expose no sort parameter
   and are ordered by the server. Reports are a separate path: their paging is
   applied in memory after the register is built
   (`app/api/reports.py`), so do not present its page size as a server count.
5. Purchase orders have no approval step, and there is no Service & Workshop
   module; both must be verified as requirements before any build (brief §10).

The numbered register, evidence and phased plan are in
[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md).
