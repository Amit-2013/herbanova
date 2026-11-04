# Feature and navigation registry — WP-4 design (corrected)

**Status: corrected 4 November 2026; Batch 4a activated the same day with
owner approval, and Batches 4b, 4c and 4d implemented and verified the same
day.**
`alembic/versions/0031_navigation_registry.py` is active and applied to
`herbanova_bcs_dev` (`0030_sign_in_content` → `0031_navigation_registry`), after
a verified dump and restore test. Batch 4b adds the read-only
`GET /api/navigation` and `GET /api/admin/navigation` endpoints; Batch 4c wires
the SPA to the first behind a switch; Batch 4d turns that switch on, so the
server tree is the default menu and `static/js/workspace.js` with its built-in
hierarchy remains the loading and failure fallback, restorable with
`?nav=builtin`. Production is still at `0028_advances` and was
not touched. Branch `feature/gap-closure`, HEAD `77f5a96`; the working tree is
preserved and uncommitted — 50 entries at the end of Batch 4d (26 modified, 24
untracked, `git status --porcelain` on 4 November 2026); nothing was reset,
cleaned, committed or pushed.

This revision resolves **R-01** (registry keys are not foreign keys to switch
state), removes two tables that the evidence does not justify
(`nav_aliases`, and `user_favourites` for now), corrects the measured route
count, and completes the validation rules. Everything below marked
**Verified** was measured from this working tree; **Proposed** waits for the
owner; **Pending** is explicitly not done. The activation record, including the
final counts and test evidence, is in
[WP4_APPROVAL_READINESS.md](WP4_APPROVAL_READINESS.md) §14 and
[VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) §34.

Related: [WP4_APPROVAL_READINESS.md](WP4_APPROVAL_READINESS.md) (the review this
revision answers), [NAVIGATION_AND_TAB_DESIGN.md](NAVIGATION_AND_TAB_DESIGN.md),
[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md),
[PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md),
[FEATURE_INVENTORY.md](FEATURE_INVENTORY.md),
[permissions-matrix.md](permissions-matrix.md).

---

## 1. Measured baseline (verified 4 November 2026)

| Thing | Count | Source |
|---|---|---|
| Routed views | **25** | `static/js/workspace.js` `TITLES` |
| Navigation nodes | **64** (5 modules + 14 categories + 20 groups + 25 screens) | `NAV`, recounted by `navigation_catalog.catalog_counts()` |
| Feature switches | **14** | `app/core/features.py` |
| Permission keys | **49** | `app/core/permissions.py` |
| API routes | **344** `APIRoute` objects | `app.main.app.routes`, measured this revision |
| Distinct API paths | **268** = 267 `/api` paths + the SPA `/` | same |
| Paths owned by a feature prefix | **229** | `feature_for_path()` |
| Paths not owned by any feature | **39** = 38 `/api` paths + `/` | same; 10 `/api` groups |
| Tables at `0030` | **88** = 87 model tables + `alembic_version` | `__tablename__` across `app/models` |
| Alembic head | `0030_sign_in_content` | `alembic/versions` |
| Production revision | `0028_advances` (reported) | owner report; not connected to in this revision |

The architecture document's earlier 341 and this design's earlier 348 were both
wrong; the runtime count is **344**. `267` distinct `/api` paths was right, but
the earlier table omitted the `/` SPA route from the unowned total. The registry
work uses the runtime numbers. This is correction **R-02**.

### 1.1 Feature switches as declared in code

| Feature key | `Feature.views` (code) | Permissions it owns | API prefixes |
|---|---|---|---|
| `products` | products | product:read, product:write | /api/products |
| `stock` | inventory, purchasing | stock:read, stock:write | /api/warehouses, /api/inventory, /api/purchase-orders, /api/dashboard/expiry |
| `foc` | foc | foc:read, foc:write, foc:approve | /api/foc |
| `suppliers` | suppliers | supplier:read, supplier:write, supplier:bank | /api/suppliers |
| `sales` | sales, billing, customers, distributors, geo | sales:read, sales:write, distributor:write, credit:manage, dispatch:write, invoice:write, invoice:cancel, invoice:edit_post_billing, note:write, print:document | /api/distributors, /api/sales-orders, /api/invoices, /api/credit-notes, /api/debit-notes, /api/print, /api/dashboard/geo |
| `approvals` | approvals | approval:read, approval:decide, approval:credit_limit | /api/approvals |
| `leads` | leads, lost, followups | lead:read, lead:write, lead:assign | /api/leads |
| `accounts` | accounts | accounts:read, accounts:write, accounts:reports, expense:read, expense:write | /api/accounts, /api/expenses |
| `tax` | tax | tax:read, tax:write | /api/tax, /api/company, /api/discount-slabs |
| `reports` | reports, compare | report:export | /api/reports, /api/dashboard/compare |
| `hr` | hr | hr:read, hr:write, hr:attendance_self, hr:attendance_manage, hr:leave_approve, hr:payroll_prepare, hr:payroll_approve, hr:confidential, hr:reports | /api/hr, /api/employees |
| `audit` | audit | audit:read | /api/audit, /api/dashboard/activity |
| `scheduled` | scheduled | email:manage | /api/email-reports, /api/email-settings |
| `users` | users | user:manage, employee:read, employee:write, db:reset | /api/users (locked ON) |

`Feature.views` is the code-side declaration, not the registry. The registry's
node mapping adds `expenses` → `accounts` and `roles` → `users` (correction
D-01) and resolves `distributors` through the `customers` alias (D-02). The
parity test accepts only those two additions; a third undeclared mapping fails.

### 1.2 Screens, exact node keys and access rules

`menu` is the rail; `hidden` is route-reachable only (`NOT_IN_MENU`).

| Screen | Label | Node key | Permission rule | Menu | Feature |
|---|---|---|---|---|---|
| `dash` | Overview | `overview/dashboard/workspace/dash` | any signed-in (**Home**, locked) | menu | — |
| `compare` | MoM & YoY dashboard | `overview/dashboard/workspace/compare` | sales:read **or** stock:read | hidden | reports |
| `leads` | Leads | `sales/pipeline/lead-desk/leads` | lead:read | menu | leads |
| `lost` | Lost leads | `sales/pipeline/lead-desk/lost` | lead:read | menu | leads |
| `followups` | Today's follow-ups | `sales/pipeline/lead-desk/followups` | lead:read | menu | leads |
| `sales` | Sales orders | `sales/sales/order-desk/sales` | sales:read | menu | sales |
| `billing` | Billing | `sales/sales/invoicing/billing` | sales:read | menu | sales |
| `approvals` | Approvals | `sales/sales/approvals/approvals` | approval:read | menu | approvals |
| `customers` | Customers and distributors | `sales/parties/customer-master/customers` | sales:read; alias `distributors` | menu | sales |
| `purchasing` | Purchases | `stock/buying/purchase-desk/purchasing` | stock:read | menu | stock |
| `suppliers` | Suppliers | `stock/parties/supplier-master/suppliers` | supplier:read | menu | suppliers |
| `products` | Products | `stock/inventory/masters/products` | product:read | menu | products |
| `inventory` | Inventory | `stock/inventory/stock/inventory` | stock:read | menu | stock |
| `foc` | Free samples (FOC) | `stock/inventory/stock/foc` | foc:read | menu | foc |
| `accounts` | Accounting & Finance | `finance/books/ledgers/accounts` | accounts:read **or** accounts:reports | menu | accounts |
| `expenses` | Expenses | `finance/spend/expenses/expenses` | expense:read | menu | accounts (D-01) |
| `tax` | Tax and discounts | `finance/tax/tax-master/tax` | tax:read | hidden | tax |
| `reports` | Reports | `finance/insight/reports/reports` | any signed-in; rail needs one of 6 keys | menu | reports |
| `scheduled` | Scheduled reports | `finance/insight/reports/scheduled` | email:manage | menu | scheduled |
| `geo` | Geography | `finance/insight/analytics/geo` | sales:read | menu | sales |
| `hr` | HR Management | `people/people/hr/hr` | hr:read **or** hr:attendance_self | menu | hr |
| `users` | Logins and employees | `people/access/logins/users` | user:manage | hidden | users |
| `roles` | Roles & Permissions | `people/access/permissions/roles` | user:manage | menu | users (D-01) |
| `audit` | Audit trail | `people/governance/audit/audit` | audit:read | hidden | audit |
| `settings` | Settings & Administration | `people/governance/settings/settings` | any signed-in; rail needs one of 4 keys | menu | — |

Alias: `#/distributors` opens `customers`. The alias is stored once in
`nav_nodes.aliases`; it is not a node and not a feature view.

## 2. Drift the registry fixes, not copies

| # | Finding | Registry treatment |
|---|---|---|
| D-01 | `expenses` and `roles` are absent from `Feature.views` though the browser maps them to `accounts` / `users` | Node `feature_key` set to `accounts` / `users`; the two exceptions are named in `DOCUMENTED_VIEW_ADDITIONS` and tested |
| D-02 | `distributors` is a view in `sales`, but an alias in routing | One `aliases` entry on the `customers` node; **no alias table**; parity test proves `#/distributors` still opens Customers |
| D-03 | `settings` has no route permission and uses a narrower rail rule | `permission_any = []`, `menu_rule = menu_any`, four keys; reachable by URL for every signed-in user, as today |
| D-04 | Four screens use OR rules or narrower rail rules | `permission_any` and `menu_any` arrays; no rule language |
| D-05 | `scheduled` also asks the browser `srAllowed()` | **Decision proposed:** server navigation uses `email:manage` only; the API already refuses a caller without it. The browser rule stayed, and 4d closed the same gap on the server with `narrow_admin_only` (§6.5) |
| D-06 | 38 `/api` paths belong to no feature (plus the `/` SPA route) | `feature_key = null`; the recorded set is pinned by a test so a new unowned prefix is deliberate |
| D-07 | "Module" means the 18-entry delivery register (`/api/modules`), not a feature | New tables are `nav_*` / `feature_registry`; this design does not introduce a third meaning |
| D-08 | Navigation lives in four places | After 4d one registry feeds them; `workspace.js` keeps its signatures and remains the fallback |

## 3. Decisions

### 3.1 Accepted by this correction

| # | Decision | Reason |
|---|---|---|
| D1 | Schema first, behaviour later, four separately approved batches | A read-only batch can be diffed against today's menu before anything depends on it |
| D2 | The registry stores mapping, never business rules | Unknown permissions, features and routes are refused (§7) |
| D3 | `feature_flags` remains the only switch state | Two state tables would disagree; `feature_store.py` already reads one |
| D4 | `permission_any` / `menu_any` arrays, no permission algebra | Expresses all OR rules without a new language |
| D5 | Server-side filtering | A response cannot reveal a screen the caller may not open |
| D6 | Home is locked | A role with no module must still land somewhere |
| D7 | Deactivate, never delete | Preserves history and avoids dangling references |
| **D9** | **`0031` creates two tables, not four** | `nav_aliases` duplicates one row; `user_favourites` has no reader (4d kept favourites device-local). Additive later is cheaper than an empty table now |
| **D10** | **`user_favourites` is deferred to an additive `0032` if D8 is approved** | Nothing reads it in 4a–4d; 4d kept device-local favourites |
| **D11** | **The alias lives in `nav_nodes.aliases` JSON** | One value does not justify a table, a join, or a second natural key |
| **D12** | **Opening a screen writes no audit row; navigation and favourites write none either** | The audit log is a security/business trail. A per-screen-open row would be noise and a privacy liability. Admin navigation edits in WP-5 remain audited |
| **D13** | **Recents use a separate, lightweight mechanism if the owner wants them server-side** | Not in `0031`; until then `recent` is empty and the browser keeps `localStorage`. No audit rows |

### 3.2 Still pending owner approval

| # | Question | Recommendation |
|---|---|---|
| D8 | Move favourites from `localStorage` to the server in 4d? | **Defer.** Keep device-local favourites; add `0032` only if a real cross-device requirement appears |
| D-05 | Drop `srAllowed()` from server navigation? | **Yes**, as the API already enforces `email:manage`; the browser rule stayed, and 4d narrowed the server menu as well (§6.5) |
| — | Approve the two-table reduction (D9–D11), the no-audit decision (D12), and the recents deferral (D13) | Yes |

## 4. Schema — migration `0031_navigation_registry`

**Active and applied.** Additive only: two tables, no existing table altered, no
column dropped, no business row read or written. Conventions follow
`0030_sign_in_content`. Activation created `nav_nodes` (64 rows) and
`feature_registry` (14 rows) on `herbanova_bcs_dev`, taking it from 88 to 90
tables; no business row or column changed.

### 4.1 Table audit (necessity and ownership)

| Candidate | Needed in 4a? | Owner / scope | Why an existing table cannot serve | Decision |
|---|---|---|---|---|
| `nav_nodes` | **Yes** | System-wide configuration; parents are `users` only through future favourites, which are deferred | No navigation table exists. The menu is `workspace.js` `NAV`; `/api/modules` is a hardcoded delivery register in code | Create |
| `feature_registry` | **Yes** | System-wide configuration | `feature_flags` is sparse switch state (absent = ON) and has no label, description, status, prefixes, permissions or dependencies. Adding columns would lose ownership for a feature with no flag row | Create |
| `nav_aliases` | **No** | — | One row (`distributors`). A JSON entry on the target node is exact and needs no second natural key or join | **Do not create** |
| `user_favourites` | **No** | Per-user preference | `hr_saved_filters` is an HR-owned, named, parameterised filter cleared by a business reset; it cannot represent ordered screen pins. But 4d kept favourites device-local and D8 is unapproved | **Defer to `0032`** |

Relationships: `nav_nodes.parent_id → nav_nodes.id` (`ON DELETE RESTRICT`); no
other table references `nav_nodes` in `0031`. `feature_registry` has no
incoming or outgoing foreign key. `nav_nodes.feature_key` and
`feature_registry.feature_key` are plain strings (R-01).

Deletion behaviour: no node is deleted in WP-4. A parent with children cannot be
deleted (`RESTRICT`); nodes are deactivated leaf-first. `feature_registry` rows
are never deleted; `status = retired` is descriptive, and validation refuses a
node that references a feature absent from the code catalogue. The downgrade
drops both tables; there is no user data to lose.

Uniqueness: `node_key`; one `is_home` via a partial unique index; one screen per
`view` and one screen per `route` (service-enforced, because SQL cannot express
it without deferrable constraints); `(parent_id, sort_order)` unique among
siblings (service-enforced so WP-5 can reorder in two steps).

### 4.2 `nav_nodes`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | Seeded explicitly 1–64; `setval` advances the sequence |
| `parent_id` | Integer FK `nav_nodes.id`, null at depth 1 | `ON DELETE RESTRICT` |
| `depth` | SmallInteger, not null | Check 1–4; depth 4 = screen |
| `node_key` | String(64), unique, not null | Full path, e.g. `sales/sales/order-desk/sales` |
| `label` | String(120), not null | Exact rail/breadcrumb text; the Workspace group's label is `""`, as shipped |
| `kind` | String(16), not null | `module`, `category`, `group`, `screen`; check ties it to `depth` |
| `view` | String(32), null | Screens only; must be a key of `TITLES` (service check) |
| `route` | String(120), null | `#/` + view; screens only; unique |
| `component_key` | String(32), null | Equals `view` until a second renderer exists |
| `feature_key` | String(32), null, **no FK** | R-01; validated against `FEATURES` / `feature_registry` |
| `permission_any` | JSON array, not null, `[]` | Any one key opens the node |
| `menu_rule` | String(16), not null, `always` | `always`, `never`, `menu_any` |
| `menu_any` | JSON array, not null, `[]` | Non-empty exactly when `menu_rule = menu_any` |
| `aliases` | JSON array, not null, `[]` | `["distributors"]` on `customers` |
| `is_home` | Boolean, not null, false | Exactly one; partial unique index; must be active, depth 4, featureless, permissionless, in the rail |
| `sort_order` | Integer, not null, 1-based | Sibling order |
| `active` | Boolean, not null, true | Deactivate instead of delete |
| `created_at`, `updated_at` | DateTime(tz), not null | `now()` |

Checks: depth 1–4; kind matches depth; `(kind='screen') = (view is not null)`,
same for `route` and `component_key`; `menu_rule` in the three values;
`sort_order >= 0`; Home shape. Indexes: `(parent_id, sort_order)`,
`feature_key`, `active`, unique `node_key`, partial unique `is_home`.

Not expressible cheaply in PostgreSQL and therefore enforced in the service:
`depth = parent.depth + 1`, `node_key` begins with the parent key + `/`, no
cycle, no duplicate sibling order. A trigger was rejected: it adds a runtime
failure mode for a 64-row configuration table and WP-5 will call the same
service before writing.

### 4.3 `feature_registry`

| Column | Type | Notes |
|---|---|---|
| `feature_key` | String(32) PK, **no FK** | R-01; one row per `FEATURES` entry |
| `label`, `description` | String(120) / Text | Copied from `features.py`; parity-tested |
| `status` | String(12), not null, `active` | `active`, `planned`, `retired` |
| `locked` | Boolean, not null, false | Mirrors `Feature.locked` (`users` only) |
| `api_prefixes` | JSON array, not null | Exact copy; each prefix owned by exactly one row |
| `tables` | JSON array, not null, `[]` | **Empty on purpose.** The code maps features to API prefixes, not model tables; inventing a list would be a guess. WP-5 fills it from a verified derivation or drops the column |
| `permissions` | JSON array, not null | Sorted copy of `Feature.permissions` |
| `depends_on` | JSON array, not null, `[]` | Known feature keys, no self, no cycle |
| `created_at`, `updated_at` | DateTime(tz), not null | |

`enabled` is deliberately absent. `locked` is ownership metadata, not state.

### 4.4 R-01 resolution (explicit)

- `feature_registry.feature_key` has **no** foreign key to `feature_flags.key`.
- `nav_nodes.feature_key` has **no** foreign key to `feature_flags.key`.
- Registration is validated against the canonical `FEATURES` catalogue and the
  seeded registry.
- Switch state stays only in `feature_flags`; a missing row is ON, as today.
- Registering a feature cannot enable it; disabling a switch cannot unregister
  it; deleting every switch row cannot fail on a registry constraint.
- `feature_store.py` is unchanged.

The five required behaviours are tested in
`tests/test_navigation_registry.py` (§9): no switch row, disabled row, no FK /
delete all rows, unknown key refused, membership does not change state.

### 4.5 Reset classification

`app/services/db_reset.py` refuses to run while a table is classified nowhere.
At activation, `feature_registry` and `nav_nodes` join `KEPT_TABLES` (41 → 43);

| | Clear | Keep | Schema | Total |
|---|---|---|---|---|
| At `0030` | 46 | 41 | 1 | 88 |
| After `0031` | 46 | **43** | 1 | **90** |

**Not applied in this revision.** `_kept_snapshot()` queries every KEPT table, so
adding the names before the migration runs would fail
`test_business_mode_leaves_every_kept_table_untouched`. The two insertions are a
required part of the activation step (§10.2), not of this preparation.

## 5. Seed data

**Verified parity target:** 5 modules, 14 categories, 20 groups, 25 screens, 14
features, 1 alias. No screen, route or feature is added or removed.

- The canonical rows are generated from `app/services/navigation_catalog.py`,
  which mirrors `workspace.js` and `features.py`.
- `scripts/generate_navigation_seed.py` writes the literal `NAV_NODES` /
  `FEATURE_ROWS` block into the draft migration (`.py.draft`) before
  activation; once 0031 is active, `--write` refuses it with exit code 2
  because Alembic does not checksum applied revisions and a seed change
  belongs in a new migration. `--check` reads the active `.py` if present and
  fails if the literal and the catalogue differ. The migration imports no
  application code.
- `tests/test_navigation_registry.py` compares the literal, the catalogue and
  `workspace.js` (through a Node manifest). A screen added to the SPA without a
  registry row fails the suite.
- Corrections in the seed: `expenses` → `accounts`, `roles` → `users`,
  `distributors` inline alias, Settings `menu_any`.
- `feature_registry.tables` is `[]` for all 14 rows, asserted by the test.

## 6. API contract (4b onward)

### 6.1 `GET /api/navigation`

Returns only nodes the caller may open, already filtered and ordered:
modules → categories → groups → screens; plus `home`, `features`,
`permissions`, `favourites` and `recent`.

- `features` / `permissions` are the already-narrowed sets from
  `feature_store.enabled_keys` and `rbac.role_permissions`.
- `recent` is **empty** until a lightweight recents mechanism is approved. It is
  never derived from the audit trail, because opening a screen writes no audit
  row (D12).
- A missing table or invalid registry returns `503
  {"detail": "Navigation registry unavailable"}`; never a partial tree.
- `ETag` inputs: registry fingerprint (deterministic SHA-256 over the ordered
  node and feature rows), user id, sorted permissions, sorted enabled features,
  favourites, recent and — since 4d — Administrator status. A switch change
  changes `enabled_features`, so a stale `304` is impossible; a role promotion
  or demotion changes `admin`, so a body narrowed by §6.5 cannot be served from
  the old validator either. `304` is returned only when every input is unchanged
  and the body would be byte-identical.

**Implemented in Batch 4b** (`app/api/navigation.py`,
`app/services/navigation_store.py`):

```json
{
  "modules": [
    {"node_key": "overview", "label": "Overview", "categories": [
      {"node_key": "overview/dashboard", "label": "Dashboard", "groups": [
        {"node_key": "overview/dashboard/workspace", "label": "", "screens": [
          {"node_key": "overview/dashboard/workspace/dash", "label": "Overview",
           "view": "dash", "route": "#/dash", "component_key": "dash",
           "feature_key": null, "is_home": true, "in_menu": true,
           "aliases": []}]}]}]}],
  "home": {"node_key": "overview/dashboard/workspace/dash", "view": "dash", "...": "same screen object"},
  "features": ["accounts", "..."],
  "permissions": ["accounts:read", "..."],
  "favourites": [],
  "recent": []
}
```

- Arrays are ordered by `sort_order` (then id). A container with no visible
  screen is removed, so a closed branch's label is not disclosed.
- `in_menu` carries `menu_rule` (`always`, `never`, `menu_any`); a `never`
  screen is still returned because the caller may open it, but it is not a rail
  entry (`tax`, `users`, `audit`, `compare`).
- `aliases` travel with the visible screen (`distributors` on `customers`), so
  `#/distributors` resolves without a fourth table.
- Dependencies: a feature is offered only when its registry row is `active`,
  its switch is ON (or it is locked ON) and every `depends_on` feature is
  available. No shipped row declares a dependency, so today's menu is
  unchanged; disabling a dependency removes the dependent feature from the
  response without touching its own switch.
- The reader order is fixed in code (depth, `sort_order`, id; features by key)
  so the fingerprint cannot change because a query plan changed.
- Response headers: `ETag`, `Cache-Control: private, no-cache`, `Vary: Cookie`.
  The ETag includes the user id, so two users with identical menus never share
  a cache entry; `If-None-Match` (including `W/` and `*`) returns `304` with no
  body.
- The endpoint calls `require_login`, writes no audit row and no business row
  (D12), and returns `503 {"detail": "Navigation registry unavailable"}` when a
  table is missing or `validate_catalog` reports any error. It never returns a
  partial tree.
- `feature_store` semantics are unchanged: an absent switch row is still ON and
  `users` is still locked ON. Since 4c it answers through one closure,
  `available_keys(db)`, shared by this endpoint, the route gate,
  `/api/auth/me` and `rbac`: a dependent feature is offered only when every
  `depends_on` feature is available, and a cycle fails closed. Before `0031` the
  same function falls back to the stored switches, so an unmigrated database
  behaves exactly as before. `tests/test_feature_dependencies.py` pins that the
  dependency rule and the route gate cannot disagree.

### 6.2 Favourites and recents

- Favourites stay device-local until D8 is approved. If approved, `0032` adds
  `user_favourites` with `(user_id, node_key)` PK, filtered on read against
  visibility, and **no audit rows** (D12).
- Recents, if required server-side, use a separate bounded table (for example
  `user_recent_screens` with an upsert and a six-row trim), not the audit log and
  not `0031`. Nothing in 4a depends on it.
- Administrative navigation edits (WP-5) are configuration changes and **are**
  audited.

### 6.3 Administration

Read-only `GET /api/admin/navigation` in 4b under `require_admin("user:manage")`.
Editing endpoints remain WP-5 and call `validate_catalog` before writing.

**Implemented in Batch 4b.** It returns `nodes` (all 64 stored rows, including
inactive ones), `features` with the stored switch state as `enabled`, `counts`,
`fingerprint` and `errors` (the `validate_catalog` result; empty when valid).
It is `Cache-Control: no-store`, writes nothing and audits nothing. An invalid
registry is returned with its errors here — the Administrator needs to see what
is wrong — while the public endpoint still refuses to render half a menu.

### 6.4 Frontend consumption (Batch 4c, default on in 4d)

The SPA calls `GET /api/navigation` by default since Batch 4d; the query
parameters override the release default for the rest of the session:

| Trigger | Stored | Wins |
|---|---|---|
| No choice | None | `NAV_API_ENABLED = true` → API tree |
| `?nav=builtin` in the query or hash | `sessionStorage["hb.navApi"] = "builtin"` | Built-in `NAV` |
| `?nav=api` | `sessionStorage["hb.navApi"] = "api"` | API tree |

- `navFromApi(payload)` in `workspace.js` converts the response and **drops**
  unknown views and any view seen twice; `activeNav == null` restores `NAV`.
  The conversion can only hide screens: the payload is already filtered, and
  `wsViewOk()` additionally requires `navAllows(view)` while it is active.
- The app keeps `builtin | loading | ready | error`. While the first request is
  in flight the built-in, permission-filtered menu is drawn, so the rail is
  never blank. A per-request sequence number and the username captured at send
  time discard an answer from another account or from a superseded request.
- Login, logout and a successful role save reset the tree and re-fetch it.
  Tabs, favourites and recents are pruned with `wsViewOk` after the tree changes.
- On `401` the app leaves the session to `api()`. On any other failure it shows
  an alert in the sidebar's status area (above Favourites), keeps the built-in
  permission-filtered menu, and offers **Retry**; it never renders every module.
  On a malformed payload it does the same.
- Home protection, aliases and the 19 accounting sub-sections remain the
  existing router's job; 4c and 4d did not change them.

### 6.5 Administrator-only screens (Batch 4d)

Some routes are guarded by `require_admin(permission)` rather than by a
permission alone, and `validate_permissions` refuses `ADMIN_ONLY_PERMISSIONS` to
a custom role. A registry row records a permission, not a role, so a row written
outside the Roles API (restored dump, direct SQL) could carry `email:manage` on
a custom role and the endpoint would offer a screen whose every request answers
`403`.

- `ADMIN_ONLY_VIEWS = frozenset({"scheduled"})` in
  `app/services/navigation_catalog.py` names those screens.
- `narrow_admin_only(visible, nodes, admin=...)` in
  `app/services/navigation_registry.py` subtracts them for every caller who is
  not the Administrator; `GET /api/navigation` passes `is_admin(db, user)`.
- `navigation_etag(..., admin=...)` includes that flag, so the narrowed body is
  never paired with an old validator.
- This only narrows: the built-in menu already required `srAllowed` (role
  `admin`), no route gate changed, and the endpoint can never offer more than
  the permissions and features allow.
- `tests/test_navigation_parity.py` proves a custom role holding `email:manage`
  still does not receive `scheduled`, and `tests/test_navigation_registry.py`
  pins both the subtraction and the ETag change.

## 7. Validation rules (complete)

`validate_catalog(nodes, features)` returns a list of errors; `assert_valid`
raises. Implemented in `app/services/navigation_registry.py` and tested.

1. **Duplicate feature keys** — `FEATURES` and registry rows; the PK is the
   second line of defence.
2. **Duplicate navigation nodes** — `node_key`, `view`, `(parent_id,
   sort_order)`.
3. **Invalid parent-child hierarchy** — parent exists, not self, depth =
   parent + 1, kind matches depth, `node_key` extends the parent key, modules
   have no parent.
4. **Circular parent references** — every chain terminates; a repeated id is an
   error.
5. **Invalid or duplicate routes** — screen only; `route == "#/" + view`; unique.
6. **Unknown permissions** — `permission_any` and `menu_any` ⊆ `PERMISSIONS`;
   no duplicates; `menu_any` non-empty exactly when the rule is `menu_any`.
7. **Invalid feature references** — node `feature_key` ⊆ `FEATURES` and ⊆
   registry rows.
8. **Disabled feature visibility** — `visible_keys()` removes the node and its
   descendants; the registry row survives.
9. **Protected Home** — exactly one; active; depth 4; `dash`; no feature; no
   permission; in the rail; not a second Home.
10. **Alias resolution** — unique, non-empty, no collision with a node key, a
    view, another alias or a key segment; resolves to one screen (today
    `distributors` → `customers`).
11. **Existing accounting sub-sections** — the 19 `ACC_SECTIONS` stay inside the
    one `accounts` screen and are not navigation nodes; `SECTION_VIEWS` remains
    `{accounts: true}`; no route is removed.
12. **Registry seed parity** — every `Feature.views` entry maps to one node with
    that `feature_key`; every mapped node is declared or in the two documented
    additions; every feature has one registry row with the code's label,
    description, locked flag, permissions and prefixes.
13. **Component key** — `component_key == view` until a second renderer exists.
14. **API prefix ownership** — every `Feature.api_prefix` appears exactly once;
    no prefix outside `FEATURES`; the 38 unowned `/api` paths stay the recorded
    set (plus `/`, which is not an API route).
15. **Dependencies** — known feature keys, no self-reference, no cycle.
16. **Status and `tables`** — status in the three values; `tables` is a list and
    is empty until a verified derivation exists.

## 8. Implementation batches

| Batch | Scope | Runtime effect | Stop evidence |
|---|---|---|---|
| **4a** | **Activated 4 November 2026:** `0031` (two tables), catalogue, models, validation service, generator, verify script, tests | **None** — nothing imports or reads the tables; 78 configuration rows added | Done: activation verify 16/16; full suite 499 passed; parity 11/11 |
| **4b** | **Done 4 November 2026:** `GET /api/navigation` and the read-only `GET /api/admin/navigation` | A new read-only endpoint pair; the SPA still does not call either | 26 API tests (`tests/test_navigation_api.py`); browser probe 200/304 with 25 screens for Admin and 13 for Viewer; 503 path tested; full suite 525 passed |
| **4c** | **Done 4 November 2026:** the SPA reads `/api/navigation` behind `?nav=api`, with `NAV_API_ENABLED = false` as the release default; dependency closure shared with the route gate | Opt-in only; no change to a browser that does not opt in | 20 Node tests; 5 dependency tests; full suite 530 passed; browser 199/199 (D=86) at 1440/768/390, both themes; forced 503 proves the fallback; console clean |
| **4d** | **Done 4 November 2026:** `NAV_API_ENABLED = true`; `?nav=builtin` and the loading/error fallback stay; `narrow_admin_only` and the `admin` ETag input resolve the `scheduled` discrepancy; parity harness over 173 permission/feature combinations | Visible: the server tree is the default for every browser; the built-in menu is the fallback | 10 parity tests + 2 registry tests; full suite 542 passed; Node 20; browser 226/226 (D=113) across five roles, all 25 screens, 19 accounting sub-sections, eight lists, tabs, deep links, 1440/768/390, both themes, three forced failures, live permission change |

Rollback per batch: 4a `alembic downgrade 0030_sign_in_content` plus reverting
the `KEPT_TABLES` and model-import edits (rehearsed: removes exactly the two
tables and no business row); 4b revert the router include; 4c switch off; 4d flip
the default back.

## 9. Tests added for 4a

`tests/test_navigation_registry.py` (**31 passed after activation**; three were
gated/skipped while the migration was inactive) plus
`tests/js/emit_nav_manifest.cjs`:

| Test | Proves |
|---|---|
| `test_catalogue_counts_are_the_shipped_counts` | 64 nodes, 25 views, 14 features, counts 5/14/20/25 |
| `test_catalogue_validates_with_no_errors` | The shipped catalogue passes every rule |
| `test_one_protected_home_and_one_alias` | Home shape and the single alias |
| `test_seed_literal_matches_the_catalogue` | The active migration literal is exactly the catalogue; revision/down_revision correct |
| `test_accounts_sections_stay_code_driven` | 19 sections, only `accounts` is sectioned, no route removed |
| `test_navigation_matches_workspace_js_exactly` | NAV, 25 titles, 23 feature mappings, 25 flat rows, order, labels, menu flags |
| `test_browser_access_rules_match_the_catalogue` | Every permission OR rule, feature gate and menu rule agrees with `workspace.js` |
| `test_registered_feature_without_a_switch_row_is_on` | **R-01 (1)** |
| `test_disabled_switch_row_hides_nodes_but_keeps_the_registry_row` | **R-01 (2)** |
| `test_registry_has_no_foreign_key_to_feature_flags` | **R-01 (3, structural)** |
| `test_unknown_feature_key_is_rejected` | **R-01 (4)** |
| `test_registry_membership_does_not_enable_or_disable_a_switch` | **R-01 (5)** |
| `test_duplicate_node_key/permission/hierarchy/cycle/route/home/alias/sort_order/component` | Rules 1–10 |
| `test_feature_rows_must_match_features_py` and `test_feature_references_are_checked_everywhere` | Rules 7, 12, 15 |
| `test_undeclared_screen_feature_mapping_is_rejected` | D-01 cannot grow silently |
| `test_missing_switch_row_and_registry_row_are_independent` | Registration and switch state stay separate |
| `test_permission_and_feature_filtering`, `test_inactive_parent_hides_its_children` | Visibility rules |
| `test_fingerprint_and_etag_include_registry_user_and_switches` | No stale 304 |
| `test_migration_seed_matches_the_catalogue` | Live: the 78 seeded rows equal the catalogue |
| `test_deleting_every_switch_row_leaves_the_registry_intact` | **R-01 (3, live)** |
| `test_downgrade_and_reupgrade_are_covered_by_the_verify_script` | The downgrade and the rehearsal script exist |

All 31 run in the repository suite now that the migration is active. The full
suite result for activation is recorded in
[VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) §34.

### 9.1 Tests added for 4b

`tests/test_navigation_api.py` — **26 passed**:

| Test | Proves |
|---|---|
| `test_requires_authentication` | No session returns 401 |
| `test_role_sees_exactly_its_authorised_screens` (×5 roles) | Admin 25, Sales 18, Inventory 16, Viewer 13, HR Manager 5 screens; exact routes, `component_key`, permissions and feature keys |
| `test_home_is_always_present_and_protected` (×5 roles) | `home` is the `dash` screen, appears in the tree, has no feature and no permission gate |
| `test_empty_branches_are_pruned` | HR Manager gets no Sales "Pipeline"/"Parties", no Stock module |
| `test_alias_resolution_follows_visibility` | `distributors` on `customers` for Admin; absent when the screen is closed |
| `test_additional_route_is_not_offered_to_a_closed_role` | No hidden route or permission key in a Viewer's body |
| `test_feature_switch_hides_the_module_and_its_permissions` | Switch off removes the screen, feature and permission keys; re-enabling restores them |
| `test_dependency_switch_hides_the_dependent_feature` | `foc` follows a disabled `stock` dependency while its own switch stays ON |
| `test_inactive_node_hides_itself_and_descendants` | An inactive group removes its screen and keeps its siblings |
| `test_invalid_feature_reference_returns_503` | Invalid registry reference returns 503, not a partial tree |
| `test_missing_registry_table_returns_503` | Missing table returns the same 503 |
| `test_etag_conditional_get` | Quoted ETag, private/no-cache, `Vary: Cookie`, 304 with empty body, weak and stale validators |
| `test_etag_changes_after_a_permission_change` | A role edit invalidates the old ETag on the next request; the new one returns 304 |
| `test_etag_is_per_user_even_when_the_body_matches` | Two Administrators with identical bodies have different ETags; crossing them does not 304 |
| `test_get_writes_no_navigation_feature_or_audit_row` | Row counts and the maximum audit id are unchanged after three GETs |
| `test_admin_registry_endpoint_is_administrator_only` | 64 nodes, 14 features, 5/14/20/25 counts, no errors, 403 for Sales, 401 anonymous |
| `test_navigation_permissions_match_auth_me` | The endpoint and `/api/auth/me` agree for all five roles |
| `test_response_is_deterministic` | Two requests return identical bytes and ETags |

### 9.2 Tests added for 4d

`tests/test_navigation_parity.py` — **10 passed**; `tests/js/nav_parity.cjs`
runs the shipped `workspace.js` for each case:

| Test | Proves |
|---|---|
| `test_builtin_and_api_agree_for_every_seeded_role` | Five seeded roles over HTTP: identical view and menu sets, no duplicate/unknown; `/api/auth/me` agrees |
| `test_every_role_keeps_home_and_the_alias` | Home, `distributors` and the `accounts` node survive conversion |
| `test_hidden_routes_stay_out_of_the_menu_but_are_still_reachable` | `tax`, `users`, `audit`, `compare` are absent from the rail and present in the tree |
| `test_api_never_offers_a_screen_the_permissions_do_not_cover` | The API set is a subset of the built-in set in every catalogue case |
| `test_builtin_and_api_agree_for_every_gate_combination` | The catalogue count is exactly 5 + 17 + 136 + 14 + 1 = 173 and every case agrees |
| `test_a_feature_switch_removes_its_screen_and_permissions` | 14 switch-off cases |
| `test_dependencies_close_a_dependent_feature` | `foc` follows `stock` in the payload |
| `test_admin_only_screens_are_admin_only` | Administrator keeps `scheduled`; no other case gains it |
| `test_a_stored_role_with_email_manage_cannot_reach_scheduled` | `narrow_admin_only` refuses a custom role even when the row holds `email:manage` |
| `test_etag_separates_the_admin_role_when_bodies_match` | Same user, same body, promotion changes the ETag and returns 200, not 304 |

`tests/test_navigation_registry.py` adds
`test_admin_only_screens_are_removed_for_every_other_role` and
`test_admin_only_narrowing_keeps_home_and_the_alias`.

## 10. Migration and deployment

**Executed for development on 4 November 2026 (§10.2); production is untouched.**
The migration is active and applied to `herbanova_bcs_dev` only, after a verified
dump and restore test.

### 10.1 Sequence

Production is at `0028_advances`; development is now at `0031_navigation_registry`
and test is rebuilt to `0031` by the suite. The full chain is
`0028 → 0029_totp → 0030_sign_in_content → 0031_navigation_registry`.
Never jump from `0028` to `0031`: 0029 and 0030 are prerequisites.

| Step | Target | Command | Evidence |
|---|---|---|---|
| 0 | Any | verified dump; record `alembic current` | dump file and revision |
| 1 | Disposable | `python scripts/verify_navigation_migration.py --run` | creates/drops `herbanova_nav_migration_scratch_test`; 0028→0031, counts 64/14/1/1, no feature_flags FK, downgrade to 0030 removes both tables, re-upgrade reproduces |
| 2 | Restored dev copy | restore the dump; confirm `0030`; activate; upgrade | counts and API diff |
| 3 | Development | **Done 4 November 2026:** §10.2 activation; `alembic upgrade 0031_navigation_registry` | 16/16 activation checks, 90 tables, 78 rows, suite 499 passed |
| 4 | Staging or restored production copy | restore production dump; `alembic upgrade 0029_totp`, `0030_sign_in_content`, `0031_navigation_registry` in order | same checks |
| 5 | Production | maintenance window; repeat step 4 on a fresh copy first; then apply in order | same checks; rollback ready |

### 10.2 Activation (executed 4 November 2026)

The procedure below was followed in order; steps 1–2 and the upgrade were one
change, and the suite ran afterwards.

1. `mv alembic/versions/0031_navigation_registry.py.draft alembic/versions/0031_navigation_registry.py`
2. Add the two KEPT names in `app/services/db_reset.py`:
   - `"feature_registry"` after `"feature_flags"`
   - `"nav_nodes"` after `"legal_documents"`
3. Run `python scripts/generate_navigation_seed.py --check` (must print current).
4. Run `python -m pytest tests/test_navigation_registry.py tests/test_db_reset.py`.
5. Only then run `python -m alembic upgrade 0031_navigation_registry` on the
   approved target (`herbanova_bcs_dev`; the command was guarded to refuse a
   database whose name does not end in `_dev`).

Doing steps 1–2 without step 5, or step 5 without step 2, leaves either an
unclassified table or an unapplied migration. They belong together.

### 10.3 Verification queries

```sql
SELECT count(*) FROM nav_nodes;                      -- 64
SELECT count(*) FROM feature_registry;               -- 14
SELECT count(*) FROM nav_nodes WHERE is_home;        -- 1
SELECT count(*) FROM nav_nodes WHERE aliases <> '[]'::json;  -- 1
SELECT count(*) FROM nav_nodes WHERE kind='screen';  -- 25
-- must return no rows:
SELECT child.relname, parent.relname
FROM pg_constraint k
JOIN pg_class child ON child.oid = k.conrelid
JOIN pg_class parent ON parent.oid = k.confrelid
WHERE k.contype='f' AND child.relname IN ('nav_nodes','feature_registry')
  AND parent.relname='feature_flags';
```

### 10.4 Downgrade and rollback

- `python -m alembic downgrade 0030_sign_in_content` drops `feature_registry`
  then `nav_nodes` and its indexes. No existing table is touched, so no
  business row can be lost.
- Revert the two KEPT additions in the same change and delete the active
  migration file (do not restore a `.py.draft` unless re-planning 4a).
- `workspace.js` was never changed, so the application returns to the shipped
  WP-2 menu with no other step.
- After rollback: `alembic current` = 0030, both tables absent, suite green,
  `#/distributors` still opens Customers.

### 10.5 Production checklist

- [ ] Owner approval for `0031` recorded separately from 4a preparation
- [ ] Verified pre-migration dump, stored and readable
- [ ] Restored production copy passed `0028 → 0029 → 0030 → 0031`
- [ ] `alembic current` recorded immediately before the change
- [ ] Maintenance window; API and email worker stopped/paused
- [ ] Activation commit contains the `.py` rename and the two KEPT additions
- [ ] Upgrade applied in order, not skipped
- [ ] §10.3 queries pass; seed parity tests pass
- [ ] Administrator and one non-admin role see the unchanged rail
- [ ] Rollback command and previous build available
- [ ] Result, duration and revision recorded in the change log

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A registry edit names a permission or feature that is not in code | Medium | A menu entry opens nothing or over-grants | Validation refuses unknown keys; parity test runs in the suite |
| Someone adds a foreign key back to `feature_flags` for "integrity" | Low | A switch-row delete or a flagless feature breaks registration | R-01 tests assert the absence of the FK and the delete-all behaviour |
| The migration is applied before the KEPT edit | Low | The reset guard fails or the snapshot errors | §10.2 makes the edit and the migration one step; `test_db_reset` is in the stop evidence |
| The migration is applied to an unapproved database | Low | An unreviewed schema change reaches a database | Explicit target check (`_dev`); production remains at `0028` and requires separate approval |
| `srAllowed` difference hides or shows Scheduled reports inconsistently | Medium | A user sees a screen the browser would hide | D-05 is an explicit owner decision; the screen's API still enforces `email:manage` |
| Registry and `workspace.js` drift | Medium | Two menus | Node parity test over the exact constants |
| The endpoint becomes a second permission source | Low | Security drift | It reports narrowed sets; it never computes or caches permissions |
| Seed literal and catalogue diverge | Medium | Confusing next change | Generator is the only producer; `--check` and the parity test fail on drift |

## 12. Decisions needed from the owner

1. **Approve two tables** (`nav_nodes`, `feature_registry`) and the deferral of
   `nav_aliases` (inline alias) and `user_favourites` (D9–D11). — **Approved and
   executed by the 4 November 2026 activation instruction.**
2. **Approve the KEPT additions** at activation (41 → 43; total 90 at 0031). —
   **Done:** 46 CLEAR + 43 KEEP + 1 SCHEMA = 90.
3. **Approve no audit rows** for screen opens, navigation reads or favourites,
   and the separate lightweight recents mechanism (D12–D13). — Implemented; no
   audit rows are written by the registry.
4. **Approve D-05**: server navigation for `scheduled` uses `email:manage`
   only; the browser's narrower rule stayed, and 4d also narrowed the server
   menu (§6.5). — Recorded.
5. **Confirm the target environment** and sequence in §10.1. — **Confirmed:**
   `herbanova_bcs_dev`, with production explicitly excluded.
6. **Separately approve activation** of `0031`; this revision prepared it. —
   **Approved and executed 4 November 2026**; 4b, 4c and 4d were separately
   approved and executed the same day.

Resolved by this revision: **R-01** (design and code), **R-02** (route count),
D-02 (alias table removed). Everything else in the approval-readiness register
remains as recorded there.

## 13. Batch status

Batch 4a activated and applied to `herbanova_bcs_dev` on 4 November 2026; Batch
4b implemented and verified the same day; Batch 4c implemented and verified the
same day; Batch 4d turned the integration switch **on** the same day. Working
tree uncommitted; the pre-activation checkpoint is
`var/backups/wp4a-activation-20261104T082147Z/`.

| File | Purpose |
|---|---|
| `app/services/navigation_catalog.py` | 64 nodes, 14 features, counts, alias, `ADMIN_ONLY_VIEWS` (4d) |
| `app/services/navigation_registry.py` | Validation, visibility, fingerprint, ETag, `narrow_admin_only` (4d) |
| `app/services/navigation_store.py` | Read-only DB loader and dependency closure (4b) |
| `app/models/navigation.py` | Two models; no `feature_flags` FK |
| `alembic/versions/0031_navigation_registry.py` | Active schema and literal seed |
| `app/api/navigation.py` | `GET /api/navigation` and `GET /api/admin/navigation` (4b); Administrator narrowing (4d) |
| `scripts/generate_navigation_seed.py` | Writes the draft literal before activation, checks the active one; refuses to rewrite 0031 once applied; no DB |
| `scripts/verify_navigation_migration.py` | 0028→0031 rehearsal on a scratch `_test` DB; dry-run by default |
| `tests/test_navigation_registry.py` | Validation, R-01, parity, DB tests |
| `tests/test_navigation_api.py` | 4b API contract (26 pass) |
| `tests/test_navigation_parity.py` | Built-in vs server view/menu parity over 173 combinations (10 pass, 4d) |
| `tests/test_feature_dependencies.py` | Dependency closure and route-gate agreement (5 pass, 4c) |
| `tests/js/workspace.test.cjs` | Model and `navFromApi` converter (20 pass, 4c) |
| `tests/js/nav_parity.cjs` | Runs the shipped `workspace.js` for the parity test (4d) |
| `static/js/workspace.js` | Active hierarchy and converter; `NAV` remains the fallback (4c) |
| `static/js/app.js` | Default-on fetch (4d), state, failure alert and Retry (4c) |
| `app/services/feature_store.py` | `available_keys` shared by gate, `/me`, RBAC and navigation (4c) |
| `tests/js/emit_nav_manifest.cjs` | Reads `workspace.js` for the parity test |
| `app/services/db_reset.py` | Both tables kept by a business reset (46 + 43 + 1 = 90) |

Not done, by instruction: no new table or migration; no business-data change;
no server-side favourites; no production deployment; no commit or push.

## 14. Batch 4d activation record — development only

| Item | Value |
|---|---|
| Switch | `NAV_API_ENABLED = true` in `static/js/app.js` (one line) |
| Scope | Every browser session; identity is still the signed-in user, and the endpoint is per-user cached |
| Fallback | The built-in `workspace.js` menu is drawn while the request is in flight and kept on any failure, with an alert and **Retry** |
| Rollback (no code) | `?nav=builtin`, or `NAV_API_ENABLED = false`; clearing `sessionStorage["hb.navApi"]` returns a browser to the release default |
| Database | None; `0031` stays as activated in 4a |
| Production | Untouched at `0028_advances`; promotion needs its own approval |
| Evidence | `var/reports/junit-wp4d.xml` (542 passed), `var/reports/wp4d-browser.json` (226/226), `var/shots/wp4d-nav-*` |
| Checkpoint | `var/backups/wp4d-preflight-20261104T105859Z/` (source zip with SHA-256 and extract test, verified development dump, restore log) |
| Residual risks | Registry drift is caught by `validate_catalog`, the fingerprint in the ETag and the startup/health report; a CDN in front of the endpoint would need to honour `Vary: Cookie` and `private, no-cache`; the built-in fallback can lag a registry edit until the server answers |
