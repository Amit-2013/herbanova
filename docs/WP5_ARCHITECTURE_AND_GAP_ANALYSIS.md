# WP-5 architecture and gap analysis

**Planning deliverable for WP-5. 4 November 2026. Analysis only — no code, schema,
migration, data, commit, push or deployment was performed.**

| Item | Value |
|---|---|---|
| Branch | `feature/gap-closure` |
| Verified baseline commit | `ecaef491517e137d44bb7801ae1f2695f807cffa` |
| Working tree | clean at the start of this audit |
| Development database | `0031_navigation_registry`, 90 tables, 64 nav nodes, 14 features, 13 switch rows |
| Production | reported at `0028_advances`; not contacted, not verified in this pass |
| Evidence style | counts measured read-only today; anything not run is marked as not verified |

This document answers the ten WP-5 activities and stops at the decisions. It does
not implement C-6, C-8 or any WP-5 feature. Where a number differs from an older
document, the older number is named rather than silently replaced.

---

## 0. Scope and what was not done

| Required activity | Where answered |
|---|---|
| 1. Audit modules, APIs, tables, screens, permissions, feature switches | §2 |
| 2. Identify incomplete, duplicated, disconnected and non-functional features | §3 |
| 3. Resolve C-6 container permissions with a recommendation and alternatives | §4 |
| 4. Resolve C-8 navigation-label ownership, including localisation | §5 |
| 5. Review roadmap and traceability before proposing features | §3.5, §9, §10 |
| 6. Classify gaps | §7 |
| 7. Cross-module dependencies | §6 |
| 8. Implementation batches, acceptance criteria, tests, rollback | §8 |
| 9. Preserve business logic, records, migrations, working functionality | §12 |
| 10. Create this document | this file |

Not done, deliberately: no file outside `docs/` was created or modified; no
migration applied or generated; no database reset, write or schema change; no
commit, push or deployment. The only database access was read-only
(`SELECT`/`information_schema`). Two failure modes were reproduced with pure
functions against in-memory data (§4.1, §5.1); neither touched a database.

---

## 1. Baseline and method

### 1.1 Measured counts (4 November 2026, read-only)

| Item | Count | How measured |
|---|---:|---|
| API modules | 36 | `app/api/*.py` excluding `__init__` |
| Router objects | 40 | 40 `APIRouter(...)` instantiations; `costs.py`, `db_reset.py`, `email_reports.py` and `signin.py` each define two |
| Route operations | **346** | `APIRoute` objects on the built app |
| Distinct paths | **270** | 269 under `/api` plus `/` |
| Paths owned by a feature prefix | 229 | `app.core.features.feature_for_path` |
| Paths owned by **no** feature | **41** | same function (list in §3.2) |
| Model tables | 89 | `__tablename__` across 13 model modules |
| Public tables | **90** | 89 model tables + `alembic_version`; the development database reports 90 |
| Migrations | 43 | single head `0031_navigation_registry` |
| Service modules | 54 | `app/services/*.py` excluding `__init__` |
| Permission keys | **49** | `app.core.permissions.PERMISSION_KEYS`; 5 Administrator-only |
| Features | **14** | `app/core/features.FEATURES`; 13 `feature_flags` rows (absent row = ON) |
| Routed views | **25** | `TITLES` in `static/js/workspace.js`; 25 `section.view` panels in `static/index.html` |
| Navigation nodes | **64** | 5 modules, 14 categories, 20 groups, 25 screens (catalogue and dev DB agree) |
| Registry features | 14 | `feature_registry` on the development database |
| Test files | 60 | `tests/test_*.py` |

Older values still printed in other documents: 341 decorators / 344 route objects
over 268 paths ([PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) §2), 343
operations over 267 paths ([FEATURE_INVENTORY.md](FEATURE_INVENTORY.md) header,
[REQUIREMENTS_TRACEABILITY_MATRIX.md](REQUIREMENTS_TRACEABILITY_MATRIX.md) §6),
88 tables at `0030`. The drift is explained by routes added after those documents
were written (`/api/navigation`, `/api/admin/navigation`, the two extra sign-in
admin routes) plus different counting rules. **This document uses the measured
346 / 270 / 90 / 49 figures.** Reconciling the three documents is a WP-5
documentation task (§8, B6).

### 1.2 What the audit read

Source only, plus read-only database counts:

- `app/api/*.py` (all 36 files parsed for routers and routes), `app/main.py`;
- `app/core/{permissions,rbac,features,rules,module_register}.py`;
- `app/services/{navigation_catalog,navigation_registry,navigation_store,feature_store,db_reset}.py`;
- `app/models/{core,navigation,hr}.py` for the dependency map;
- `static/js/workspace.js` (the whole model), the navigation and label call sites
  in `static/js/app.js`, and the view panels in `static/index.html`;
- the planning estate: `IMPLEMENTATION_ROADMAP.md`, `REQUIREMENTS_TRACEABILITY_MATRIX.md`,
  `PROJECT_ARCHITECTURE.md`, `FEATURE_INVENTORY.md`, `FEATURE_REGISTRY_DESIGN.md`,
  `WP4_RELEASE_READINESS.md`, `DECISIONS.md`.

Not re-run in this pass: the pytest suite, the Node suite, the browser walk,
migration rehearsal. Their last recorded results stand (545 Python, 20 Node, 11
parity checks, 226 browser checks, all passing on 4 November 2026,
[VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) §38). Nothing in the working tree
changed since that run, so those results still describe this baseline; they were
not independently re-executed here and this document does not claim otherwise.

---

## 2. Audit of what exists

### 2.1 Backend composition

- 40 routers are included in `app/main.py`. The largest route owners are HR (101),
  the accounting family (`ledger` 26, `accounts` 12, `gst` 11, `expenses` 11),
  e-mail (`email_reports` 18, `email_settings` 4) and sign-in content (16).
- 346 route operations over 270 paths: 269 `/api` paths plus the SPA root.
- 330 of 341 decorators carried an auth/permission dependency at the `0030`
  audit; the public set has since grown only by the navigation API, which uses
  `require_login` and `require_admin`. The public-by-design set remains sign-in,
  2FA steps, logout, published sign-in content, unsubscribe links, `/api/health`
  and `/`, plus the retired `POST /api/db/reset` that answers 410.
- Business logic lives in 54 service modules; there is no second implementation
  of accounting, costing, payroll or document printing outside them.

### 2.2 Data layer

- 89 model tables, all present in `create_table(...)` calls across 43 migrations;
  no model-only or migration-only table.
- Latest additions: `nav_nodes` and `feature_registry` (`0031`), both classified
  as KEPT by the reset service (43 kept, 46 business, 1 schema = 90).
- `feature_registry.tables` is empty for all 14 rows and `depends_on` is empty for
  all 14. Both are deliberate placeholders (`navigation_catalog.py:212-229`): the
  code maps features to API prefixes, not tables, and inventing a table list would
  be a guess. WP-5 must derive them or drop the column (§7 W5-04).
- `feature_registry.status` is `active` for every row; `locked` mirrors `users`
  only.

### 2.3 Frontend

- One SPA, no build step: 25 `section.view` panels, one shared drawer, a paged
  list layer used by all eight list screens, one palette, tabs and breadcrumbs.
- The rail renders `GET /api/navigation` by default; `workspace.js` keeps the
  built-in hierarchy as the loading/error/`?nav=builtin` fallback. The converter
  `navFromApi()` keeps the server's **container** labels but discards screen
  labels and resolves every screen title from the local `TITLES` map — the C-8
  inconsistency, reproduced in §5.1.
- `VIEW_PERM`, `VIEW_FEATURE`, `MENU_EXTRA` and `NOT_IN_MENU` in `workspace.js`
  remain the client copy of the access rules; they are used for the fallback and
  for `viewAllowed`. The server tree can only narrow them, never widen them.

### 2.4 Permissions

- 49 keys in one catalogue, a parent/child map with 49 entries, and five
  Administrator-only keys (`approval:credit_limit`, `invoice:edit_post_billing`,
  `email:manage`, `db:reset`, `foc:approve`).
- Effective permissions are the stored role keys, parent-gated, minus the keys of
  unavailable features (`rbac.role_permissions`). This is the fail-closed set the
  route gates, `/api/auth/me`, the navigation API and the Overview all see.
- Route authority is per endpoint (`require`, `require_admin`, `require_login`).
  **The navigation registry's `permission_any` is menu-only**; it never grants or
  refuses a request. This distinction is the basis of the C-6 recommendation.

### 2.5 Feature switches

- 14 features, each owning views, permission keys and API prefixes; `users` is
  locked ON.
- One answer decides availability everywhere: `feature_store.available_keys()`
  applies the `feature_registry` dependency closure to the stored switches, and
  `is_enabled()` — used by the HTTP middleware — delegates to it. A dependency or
  a `planned`/`retired` status therefore narrows both the menu and the API.
- A missing row is ON, so an installation before `0031` is unchanged.
- `GET/PATCH /api/features` is the only switch control, Administrator role
  required, audited as `feature.update`.

### 2.6 Navigation and feature registry

- `nav_nodes` (64 rows) carries hierarchy, order, label, route, component key,
  feature binding, `permission_any`, `menu_rule`/`menu_any`, aliases, `active` and
  one protected Home.
- `GET /api/navigation` filters server-side, prunes empty branches, returns a
  per-user ETag and `304`; `GET /api/admin/navigation` returns the raw rows plus
  `validate_catalog()` errors for the Administrator.
- Both endpoints are **read-only**. No route writes `nav_nodes` or
  `feature_registry`; the only mutation path today is a migration. That is the
  core WP-5 gap (§7 W5-02).
- `validate_catalog()` already enforces identity, hierarchy, aliases, known
  permissions/features, Home shape, feature/catalogue parity, prefix ownership,
  dependency cycles and view ownership. It does **not** constrain container
  permissions (§4).

### 2.7 Three vocabularies called "module"

| Vocabulary | Size | Owner | Purpose |
|---|---:|---|---|
| Delivery register | 18 | `app/core/module_register.py`, served at `/api/modules` | Read-only status/health shown on the Overview |
| Feature switch | 14 | `app/core/features.py` + `feature_flags` + `feature_registry` | Runtime availability and API ownership |
| Menu module | 5 | `nav_nodes` depth 1 | Rail grouping and breadcrumb root |

They are legitimately different (D-02), but all three are displayed as "modules"
in different places, and only the middle one is editable. WP-5 should name them
distinctly in the UI and documentation (delivery status, feature, menu module)
rather than merging them; merging would require mapping delivery status to each
feature and is not a WP-5 requirement.

---

## 3. Incomplete, duplicated, disconnected and non-functional features

### 3.1 Duplication register

| # | Duplication | Evidence | Status after WP-4 | WP-5 action |
|---|---|---|---|---|
| D-01 | Four descriptions of "which screens exist" | formerly `TITLES`, `VIEW_PERM`, `VIEW_FEATURE`, `Feature.views` | Collapsed to two: server tree + `workspace.js` fallback; `Feature.views` still declares ownership | Keep the fallback; validate server-vs-fallback drift in CI (exists) |
| D-02 | "Module" means three things | §2.7 | Unchanged | Rename in UI and docs; do not merge |
| D-03 | Two database-reset routers | `app/api/db_reset.py` (legacy path returns 410) | Unchanged | Low-priority cleanup (W5-20) |
| D-04 | `#/distributors` alias | `nav_nodes.aliases` on Customers | Modelled as an alias, no alias table | Keep |
| D-05 | In-page tab sets (inventory, scheduled, HR profile, report picker) | `index.html`, `app.js` | Unchanged, not duplicates of workspace tabs | Keep; document the distinction |
| D-06 | Unused placeholder CSS for "coming soon" nav items | `static/css/styles.css` | Unchanged | Remove or wire to inactive state (W5-21) |
| D-07 | Overlapping historical audits (`PROJECT_AUDIT`, `STAGE1_REAUDIT`, `STAGE4_REMEDIATION`) | docs/ | Keep as dated evidence | Keep |
| **D-08** | **Two `G-01`…`G-14` registers with different meanings** | [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) §4 vs [REQUIREMENTS_TRACEABILITY_MATRIX.md](REQUIREMENTS_TRACEABILITY_MATRIX.md) §5 | Unchanged | Renumber one namespace (B6) |
| **D-09** | **Three route/path/table counts in three documents** | §1.1 | Unchanged | Replace with one measured table (B6) |
| **D-10** | **Registry screen labels are written but never read** | `navFromApi()` drops `screen.label` | Unchanged | Resolve under C-8 (B2) |

No duplicate master tables exist: customer and distributor are one `distributors`
table and one screen (D-31); supplier, product and employee masters are single
tables.

### 3.2 Disconnection register

| # | Disconnection | Evidence | Effect |
|---|---|---|---|
| X-01 | **No write path to the registry** | both navigation routes are GET; only a migration writes the two tables | An administrator cannot change a label, order, activation or feature binding without a deploy |
| X-02 | **41 API paths belong to no feature** | `feature_for_path` on 270 measured paths | A feature switch cannot govern them; a system-health check cannot classify them |
| X-03 | **Registry screen labels are inert** | §5.1 | Editing a screen label would change nothing on screen |
| X-04 | **Feature → table mapping absent** | `feature_registry.tables = []` ×14 | The "feature to API to table" map the brief asks for does not exist |
| X-05 | **19 accounting sub-sections are outside the registry** | `ACC_SECTIONS` in `app.js`; `ACCOUNTS_SECTION_COUNT = 19` in `navigation_catalog.py` | They are addressable (`#/accounts/<key>`) and per-role filtered, but have no node, breadcrumb, favourite or palette entry |
| X-06 | **Favourites and recents are not served** | API returns `favourites: []`, `recent: []`; browser uses `localStorage` | No cross-device state; `user_favourites` was deferred (D8) |
| X-07 | **Approval types with no producer or handler** | `APPROVAL_TYPES` lists `hr_overtime`, `hr_salary_revision`, `hr_reimbursement`; `HR_DECIDE_PERMISSION` omits them; `/decide` refuses | Latent: a row of those types would render but be undecidable. The development database holds 0 such rows |
| X-08 | **Leads never become orders** | `leads` has no FK to `sales_orders`; `sales_orders` has no `lead_id` | CRM ends at "won"; there is no conversion or quotation stage |
| X-09 | **Delivery register is hardcoded** | `module_register.py` is a literal list | The Overview module panel cannot reflect registry changes |
| X-10 | **Brief §6's twelve screens are not recorded in the repository** | roadmap refers to them; no file lists them | WP-5 screen scope must be confirmed by the owner (§11, D-WP5-07) |

### 3.3 Incomplete register

| # | Item | Evidence | Current behaviour |
|---|---|---|---|
| I-01 | Feature-management screens (roadmap G-03) | none exist | Administrator reads the raw registry as JSON only |
| I-02 | Purchase-order approval (roadmap G-08) | `PurchaseOrder.status` is `open/partially_received/received/cancelled`; no approval category | Receipt-driven status only |
| I-03 | Quotation stage and lead conversion (roadmap G-11) | no model, route or screen | Flow starts at sales order |
| I-04 | Service & Workshop module (roadmap G-10) | no model, service or route | Absent |
| I-05 | Overtime / salary revision / reimbursement approvals (R-77) | labels only, no creator or decider | Not built |
| I-06 | Payroll posted to the ledger (R-78, D-17) | no posting code | Payroll is in the P&L but not in the trial balance or ledgers |
| I-07 | Purchase-order printing (roadmap G-05) | no PDF builder | Not built |
| I-08 | E-invoice / e-way bill portal (MOD-15) | not built, conditional on turnover | Conditional |
| I-09 | Excel export (roadmap G-12) | CSV only on all list screens | Pending decision |
| I-10 | Multi-level approval workflow | `approval_requests` is flat; no step table or chain code | Single decision per request |

### 3.4 Non-functional or unproven features

These exist and are exercised, but the evidence is weaker than the register's
"VERIFIED" bar. They are proof gaps, not confirmed defects.

| # | Feature | Status in the traceability matrix | Missing proof |
|---|---|---|---|
| N-01 | Account lockout after repeated failures (R-15) | PARTIAL | No automated test |
| N-02 | User password reset behind the secondary password (R-19) | PARTIAL | Reset itself not run |
| N-03 | Supplier master and bank change (R-24, F-17) | PARTIAL | No dedicated test |
| N-04 | Leads (R-33, F-28) | PARTIAL | Live smoke only |
| N-05 | Sales orders, every transition (R-34, F-29) | PARTIAL | Promise/approval/dispatch covered; full status machine not |
| N-06 | Tax invoices (R-37, F-32) | PARTIAL | Live smoke and PDF check only |
| N-07 | Credit and debit notes (R-38) | PARTIAL | Open/Print covered; creation path not unit-tested |
| N-08 | Invoice immutability after issue (R-41) | PARTIAL | Code-enforced; the movement gate is tested, immutability itself is not |
| N-09 | Database reset and secondary password (R-21, G-14) | NOT VERIFIED | Destructive; only the gate was read |
| N-10 | Live e-mail delivery (F-92, R-83) | NOT VERIFIED | Test mode only; SMTP not approved |
| N-11 | Physical device, screen reader, load, deployment (G-10) | NOT VERIFIED | No device or target environment |
| N-12 | Leave-type and salary-component create forms (F-108, F-109) | PARTIAL | Lists and edits checked; create form not exercised |

### 3.5 Roadmap and traceability review

Before proposing features, the two planning documents were reconciled:

- **Roadmap status.** WP-1 (documents) is complete except for the four files
  listed in its §1 flag. WP-2 (workspace shell), WP-3 (list standard) and WP-4
  (registry, API, default navigation) are shipped and committed at `ecaef49`.
  WP-5 is next; WP-6/WP-7/WP-8 remain.
- **Roadmap gaps closed since it was written.** G-01 (hardcoded menu), G-02
  (no feature registry), G-04 (no tabs/breadcrumbs), G-05 (no server paging) and
  G-06/G-07 for the eight list screens are closed. G-03 (feature-management
  screens) is now the only S1 gap in that register.
- **Traceability matrix.** 135 requirements: 123 MET, 8 PARTIAL, 2 NOT VERIFIED,
  2 NOT BUILT. The eight PARTIAL and two NOT VERIFIED rows are the evidence gaps
  in §3.4; the two NOT BUILT rows are R-77 and R-78 (I-05, I-06). The matrix is
  otherwise consistent with the code.
- **Where the two documents disagree.** The matrix's §5 `G-01…G-14` are not the
  roadmap's `G-01…G-14`; the matrix still prints 343/267 routes and 467 tests;
  the roadmap still prints 344/268. These are documentation defects (W5-17), not
  feature defects.
- **What this means for WP-5.** WP-5 is not a feature-building package for the
  business modules. It is the package that makes the registry safely editable,
  completes the metadata and health surface, and closes the documentation drift.
  The business gaps (I-02…I-10) need owner decisions and are deliberately not
  folded into WP-5 (§10).

---

## 4. C-6 — Container permissions

### 4.1 Current behaviour

Three facts compose the defect:

1. `visible_keys()` tests only the node's **own** `permission_any`
   (`navigation_registry.py:291-299`); ancestors are checked only for `active`
   and feature availability.
2. `validate_catalog()` accepts `permission_any` on any kind
   (`navigation_registry.py:142-152`); nothing forbids it on a module, category
   or group.
3. `_build_tree()` attaches a visible node to `children[parent_id]` and renders
   only from visible parents (`api/navigation.py:52-83`). A screen whose parent
   is not visible is silently dropped from the response.

Reproduced against the shipped catalogue, with the `people` module given
`permission_any = ["hr:confidential"]` and a caller holding `hr:read`:

```
module node visible:      False
hr screen visible:        True      <- the screen itself passes its own gate
hr offered in menu:       False     <- dropped because its module was filtered
```

The user holds the permission for HR, the route still serves them (route gates
are independent of this table), but the menu silently omits the screen. No error
is shown to the administrator who made the edit; `GET /api/navigation` answers
200 with a smaller tree. The failure is fail-closed — it hides a permitted
screen, it never reveals a forbidden one — but it is silent and it contradicts
the permission the administrator can see on the screen row.

Today all 39 containers hold an empty array (22 nodes carry `permission_any`, all
screens), so there is no present effect. The defect is latent until WP-5 adds
editing, which is exactly when it would be triggered.

### 4.2 Options

| Option | Rule | Behaviour | Cost / risk |
|---|---|---|---|
| **A. Enforce ancestor gate** | A node is visible only if it and every ancestor pass `permission_any`, `active` and feature | Container permission becomes a branch gate; children disappear deliberately | Still menu-only unless routes also gain an ancestor rule. An administrator would reasonably read "branch gate" as access control; it is not. Implementing it on routes would invent a second access model that the per-endpoint `require()` calls do not share |
| **B. Forbid container permissions** (recommended) | `validate_catalog` refuses any non-screen node with `permission_any`, `menu_rule != "always"` or non-empty `menu_any` | Access is expressed only where it is enforced: on screens. Branch hiding is done by the screens' own permissions or the feature switch, and empty branches are already pruned | No branch-level gate. A future requirement for "hide this whole menu branch from role X" is served by giving the screens the key, or by a new approved menu-only rule |
| **C. Menu-only container rule** | Forbid `permission_any` on containers, allow `menu_any` on containers and apply `in_menu()` when building the tree | Administrators can narrow a branch's visibility without claiming access control | A new behaviour and a new test surface; the UI must label it "menu only". Reasonable later; not needed for WP-5 |
| **D. Status quo** | Nothing | Silent contradiction remains | Rejected: it makes an administrator edit produce a result the screen does not explain |

### 4.3 Recommendation

**Option B**, for four reasons:

1. The registry stores **menu** rules; enforcement lives on routes. A container
   rule cannot be enforced without inventing a second authorization layer, and a
   rule that looks authoritative but is not is worse than no rule.
2. Validation is the right place to refuse a configuration that cannot work.
   `validate_catalog` already runs on every public navigation request and on the
   admin read, so an invalid edit would surface as a 503 (public) and as a named
   error (admin) rather than as a quietly shorter menu.
3. It preserves every current behaviour: 39 containers already hold empty
   arrays, so no seed row changes and no menu changes.
4. It is reversible in one direction only — from "forbidden" to "allowed with a
   rule" — which is the safe direction. Starting permissive and tightening later
   would need a data audit of every installation.

### 4.4 Implementation sketch (Batch B1)

- `validate_catalog()`: for `kind != "screen"`, require `permission_any == []`,
  `menu_rule == "always"`, `menu_any == []`, and for screens require
  `permission_any` entries to be known keys (already true).
- No change to `visible_keys()`; its semantics stay per node.
- `GET /api/navigation` keeps answering 503 on an invalid registry (already).
- `GET /api/admin/navigation` already returns `errors`; the WP-5 editor must
  refuse to save while `errors` is non-empty.
- Tests: a container with a permission is refused; a container with
  `menu_rule="menu_any"` is refused; the shipped catalogue still validates;
  a simulated invalid row makes `/api/navigation` answer 503 and the admin read
  name the error; `?nav=builtin` still renders.
- Docs: state in the design doc that container rows are structural.

### 4.5 Rollback and risk

Rollback is a file revert: validation only, no schema, no data. Risk: an
installation that already carries a container permission outside this repository
would start answering 503 after upgrade. The development and test databases do
not (39/39 empty). Before deploying, run the validation query
`SELECT id, node_key, permission_any FROM nav_nodes WHERE kind <> 'screen' AND
json_array_length(permission_any) > 0` and correct any row first.

**Decision required:** D-WP5-01 (§11).

---

## 5. C-8 — Navigation-label ownership

### 5.1 Current behaviour

The registry owns **container** labels and the browser owns **screen** labels:

- `navFromApi()` copies `mod.label`, `cat.label` and `group.label` into the tree,
  but for a screen it reads only `view`, `node_key` and `in_menu`
  (`workspace.js:179-186`). `screen.label` is discarded.
- The rail, breadcrumb, palette and `flatNav()` resolve a screen title from the
  local `TITLES` map (`workspace.js:245`, `app.js:700,731,1119`).

Reproduced with a payload whose screen label is `Human Resources`:

```
server payload screen label: "Human Resources"
tree entry:                  {"id":"g0-0-0","label":"HR","views":["hr"]}   <- no screen label
flatNav label for hr:        "HR Management"                              <- local TITLES
```

So a WP-5 screen-label editor would write a value that nothing reads. Container
labels, by contrast, already change the rail. The ownership model is inconsistent
and half-inert.

### 5.2 Options

| Option | Owner of screen labels | Behaviour | Cost / risk |
|---|---|---|---|
| **A. Registry owns every label** (recommended) | `nav_nodes.label` | Rail, tabs, breadcrumb, palette and `document.title` read the server label; `TITLES` remains the fallback and the built-in hierarchy's source | Every title call site must go through one resolver; the parity test must compare the seed to `workspace.js`, not the live table |
| **B. Local `TITLES` owns screen labels** | `TITLES` | Consistent with today, but a screen label is not administrator-controlled and the registry column becomes decorative for screens | Code deploy for every rename; contradicts the "administrator-managed menu" direction of WP-4/5 |
| **C. Override with fallback** | `nav_nodes.label` nullable | NULL or empty means "use `TITLES`"; a value overrides | Extra branch in every resolver; an empty label cannot be distinguished from "deliberately blank" without a second flag |

### 5.3 Recommendation

**Option A**, with `TITLES` kept as fallback, because:

- The registry already carries the label and the ETag fingerprint already
  includes it (`registry_fingerprint` hashes `label`), so a rename invalidates
  cached navigation by construction. Nothing new is needed server-side.
- The server tree is already the rendered source by default; making the label
  authoritative completes the same move, rather than splitting ownership.
- The fallback path (`?nav=builtin`, a failed request, first paint) must still
  show correct titles, so `TITLES` cannot be removed. It becomes the fallback
  only, and the server label wins while the API tree is active.

Design details:

1. **One resolver.** `titleFor(view)` in `workspace.js`:
   `activeNav && activeNav.labels[view] ? activeNav.labels[view] : TITLES[view]`,
   used by the rail, tab strip, breadcrumb, palette, `document.title`, and the
   tab-restore pruning (which uses titles for display only; keys stay the view).
2. **Carry the label.** `navFromApi()` records `labels[view] = screen.label` when
   it is a non-empty string and still ignores unknown views. The tree shape is
   unchanged, so tabs, breadcrumbs and tests that read the tree keep working.
3. **Server validation.** A screen label must be non-empty after trimming and at
   most 120 characters (the column length). A container label may be empty only
   for the shipped Workspace group (`overview/dashboard/workspace`); every other
   container must be non-empty. Reject control characters. Do not restrict the
   character set: the labels are UTF-8 business text and may contain `&`, `'`,
   `₹`, or non-Latin script.
4. **Safe rendering.** Every render site inserts labels as text (`esc()` or
   `textContent`). Add a regression check that a label containing
   `<img src=x onerror=...>` renders literally and executes nothing. The API
   stores the literal text; escaping is the renderer's job. The admin editor uses
   a plain text input with `maxlength=120`.
5. **Parity test change.** Today `test_navigation_matches_workspace_js_exactly`
   compares the **live table** labels with `TITLES`, which would fail after the
   first legitimate rename. Split it:
   - *source parity*: `navigation_catalog.build_nodes()` must equal the shipped
     `workspace.js` hierarchy and labels — always true, protects the fallback;
   - *seed parity*: the migration's seed must equal the catalogue — checked on a
     freshly seeded database, not after edits.
6. **Admin edits and audit.** A label change writes `navigation.update` with the
   node key, the old value and the new value, so a mistake can be reverted by
   hand (the audit trail is the record; there is no version history table).

### 5.4 Localisation

The application has no localisation layer: one `<html lang="en">`, English
labels, and `en-IN` date/number formatting. One `label` column therefore holds
one language.

- **If a single language is required** (today's state), Option A is complete and
  no schema change is needed.
- **If a second language is required later**, the additive shape is a
  `nav_node_labels(node_id, locale, label)` table with `nav_nodes.label` as the
  default locale and a fallback when a translation is missing. That is a new
  feature with its own decision, not part of WP-5.
- **What must not be done:** storing JSON in `label`, or adding a second
  `label_xx` column per language, because both make validation and the ETag
  fingerprint ambiguous and neither supports a third language.

**Decision required:** D-WP5-02 (ownership) and D-WP5-03 (localisation scope).

### 5.5 The related parity question: can the Administrator edit code-owned fields?

`_validate_features()` today requires every `feature_registry` row's `label`,
`description`, `locked`, `permissions` and `api_prefixes` to equal
`features.py`, and every feature key to exist in code. If WP-5 lets an
Administrator rename a feature, that check fails and the public navigation turns
503 — unacceptable.

Recommendation: split the columns by authority.

| Column | Authority | Editable in WP-5 |
|---|---|---|
| `feature_key` | code | no (key is referenced by nodes and code) |
| `api_prefixes`, `permissions`, `locked` | code (security-relevant) | no; parity-test stays strict |
| `label`, `description` | registry after seeding | yes (with length/trim rules) |
| `status` (`active`/`planned`/`retired`) | registry | yes, Administrator only |
| `depends_on` | registry, validated against known keys and acyclicity | yes |
| `tables` | derived, see B5 | no (generated) |

The parity test then becomes: prefixes, permissions and `locked` must equal code;
keys must match the catalogue exactly; label/description/status/depends_on are
free within validation. The seed still copies the code values at migration time,
so a fresh install looks identical.

**Decision required:** D-WP5-05 (§11).

### 5.6 Rollback and risk

Rollback is a file revert (no schema, no data). The risk is a missing call site:
a title that keeps reading `TITLES` while the rail reads the server would show
two names for one screen. Mitigation: a grep-level test that `TITLES[` is read
only through `titleFor` outside the fallback module, plus the browser walk across
rail, tab, breadcrumb and palette after a rename on the test database.

---

## 6. Cross-module dependency map

### 6.1 Data and control edges

| # | Consumer → provider | Contract | Gate of record | If the edge breaks |
|---|---|---|---|---|
| 1 | Sales → Masters | Product price/MRP/HSN, GST rate, discount slabs | `product:read`, `tax:read`, feature `products`/`tax` | Order cannot price or tax a line; the server refuses an unknown rate |
| 2 | Sales → Credit control | Distributor credit limit; approval on exceed or deep discount | `approval:read/decide`, `credit:manage` | Order stops at `pending_approval`; no silent override |
| 3 | Sales → Inventory | On-hand availability and FEFO batches at submit and dispatch | `stock:read`, feature `stock` | Submit or dispatch is refused; no negative stock |
| 4 | Sales → Billing | Dispatch creates the invoice; terms and tax snapshot at issue | `dispatch:write`, `invoice:write` | No invoice without a dispatch; a later master change cannot move an issued invoice (D-38) |
| 5 | Billing → Inventory | Credit note returns stock and reverses cost | `note:write`, period lock | Return is refused rather than posting a negative-cost movement |
| 6 | Billing → Accounting and GST | Invoices, credit and debit notes feed receivables, GST outward and the document trial balance | `accounts:read`, period lock | Reports would over/under-state; today the registers read the same rows |
| 7 | Purchasing → Inventory | GRN creates batches and receipt movements; capacity checked | `stock:write`, Administrator override | Receipt refused on capacity; override audited |
| 8 | Purchasing → Accounting | Payables = goods received minus payments; supplier bank changes need a second person | `accounts:read`, `supplier:bank` | Payables drift only if a GRN is posted outside the receipt path |
| 9 | Purchasing → GST | **Only** a captured supplier bill creates input tax (not a PO) | `accounts:write` | A PO cannot silently create ITC (D-39) |
| 10 | Inventory → Accounting | COGS by costing replay; FOC receipts in their own cost bucket | `accounts:reports` | P&L COGS would be wrong; costing is replayed, not estimated |
| 11 | Accounting internal | Receipts/payments → allocations and advances → party ledgers → trial balance; vouchers → day book and balance sheet; bank lines match payments or voucher lines | `accounts:write`, month lock, year close | A receipt cannot settle a later document; a locked month refuses the write (423) |
| 12 | HR ← Users | Employee ↔ login, one login per employee | `user:manage`, `hr:read` | Employee without a login cannot self-serve; the link is visible on both screens |
| 13 | HR → Approvals | Leave, OD, correction, geofence and payroll decisions enter the central queue | `hr:leave_approve`, `hr:attendance_manage`, `hr:payroll_approve` | A request with no decider stays pending (see X-07 for the three unhandled types) |
| 14 | HR → Accounting (P&L) | Approved payroll gross; a cut month allocated by working days (D-36) | `accounts:reports` | A missing month is a named gap, never an estimate |
| 15 | HR → Statutory dues | PF/ESI/PT/TDS only from `approved`/`processed`/`paid` periods | `accounts:read` | A draft payroll is not a liability (D-42) |
| 16 | HR → Payroll outputs | Register, payslips, bank file | `hr:payroll_prepare` + `hr:confidential` | Bank file refused unless both rights and a released period |
| 17 | Expenses → P&L and GST | Expense heads and entries; GST on an expense is a memo, not a head split | `expense:read`, `accounts:reports` | Netting a single GST amount would misstate heads (D-40) |
| 18 | Period controls → all dated documents | Month lock and financial-year close refuse dispatch, invoice, receipts, payments, notes, cancellation, expenses, cost corrections, FOC notes | `periods.refuse_if_closed` (423) | A closed year cannot be silently restated (D-37) |
| 19 | **CRM → Sales** | **Missing edge**: no `lead_id` on sales orders, no quotation | — | A won lead is not converted; the order is re-keyed by hand (I-03) |
| 20 | **HR payroll → Ledger** | **Missing edge**: no posting code (D-17) | — | Salary cost is in the P&L but not in the trial balance (W5-06) |

### 6.2 Rules that hold across modules

1. **Menu visibility is not access control.** Only route dependencies and the
   feature middleware decide access; the registry can narrow the menu. WP-5's
   editor must show the route's real gate next to the menu rule.
2. **Fail-closed everywhere.** Unknown permission, unknown feature, unregistered
   dependency, invalid registry → refused or 503, never a partial menu.
3. **Documents are additive.** Invoices, notes, receipts, vouchers and payroll
   are never edited in place; reversal is a new row with a reason. WP-5 touches
   none of these.
4. **Locks precede writes.** The period lock and year close are checked before a
   dated document changes, whatever screen or API path is used.
5. **Feature availability is one answer.** The route middleware, effective
   permissions, identity payload and navigation all use
   `feature_store.available_keys()`; a registry edit to `depends_on` or `status`
   changes that answer for every consumer at once.

### 6.3 Dependency risks for WP-5

| Risk | Why it matters | Mitigation |
|---|---|---|
| Registry edit widens access | An administrator sets a screen permission and assumes it grants | The editor shows "menu only" and the route gate read from code; the API cannot grant access |
| Feature dependency loops | A → B and B → A would make both unavailable | `depends_on` validated acyclic; `feature_available` fails closed on a cycle |
| Prefix ownership collision | Two features claiming `/api/x` would make the switch ambiguous | `validate_catalog` refuses a prefix owned twice |
| Status change hides a module silently | Setting `planned` or `retired` removes it everywhere | Preview "as role" and a warning naming the affected screens before save |
| Label edit breaks a tab restore | Tabs are keyed by view, not label | Keys stay `view`; only display strings change |

---

## 7. Gap classification

Severity: **Critical** blocks WP-5 delivery or can silently produce a wrong
result once configuration is editable; **High** is a brief-level capability
absent or a control gap with operational impact; **Medium** is a material
limitation with a workaround or a pending decision; **Low** is cleanup or
documentation.

| ID | Gap | Sev | Evidence | Batch |
|---|---|---|---|---|
| W5-01 | Container permissions silently hide permitted screens (C-6) | **Critical** | §4.1 reproduction; `visible_keys` per node only | B1 |
| W5-02 | No write API or screen for `nav_nodes` / `feature_registry` (G-03) | **Critical** | both navigation routes are GET; only migrations write | B3, B4 |
| W5-03 | Registry screen labels are inert (C-8) | **Critical** | §5.1 reproduction; `navFromApi` drops `screen.label` | B2 |
| W5-04 | Feature metadata incomplete: `tables` and `depends_on` empty, status always `active` | High | `navigation_catalog.py:212-229`; dev DB 14/14 empty | B5 |
| W5-05 | 41 API paths owned by no feature | High | `feature_for_path` measured; list in §3.2 X-02 | B5 |
| W5-06 | Payroll not posted to the ledger (R-78, D-17) | High | no posting code | decision-gated |
| W5-07 | Three "module" vocabularies (D-02) | High | §2.7 | B4, B6 |
| W5-08 | Approval catalogue advertises three undecidable types (R-77) | High | `APPROVAL_TYPES` vs `HR_DECIDE_PERMISSION`; 0 rows in dev | decision-gated |
| W5-09 | Documents are not posted to vouchers (D-43) | Medium | design decision; balance sheet keeps layers | decision-gated |
| W5-10 | Test evidence gaps: 8 PARTIAL, 2 NOT VERIFIED | Medium | §3.4 | follow-up |
| W5-11 | No purchase-order approval (G-08) | Medium | `PurchaseOrder.status` has no approval state | decision-gated |
| W5-12 | No quotation stage and no lead conversion (G-11) | Medium | no FK, no model | decision-gated |
| W5-13 | No Service & Workshop module (G-10) | Medium | no model, service or route | decision-gated |
| W5-14 | 19 accounting sub-sections outside the registry | Medium | `ACC_SECTIONS`; `ACCOUNTS_SECTION_COUNT` | documented in B5 |
| W5-15 | Favourites and recents device-local (D8/D13) | Medium | API returns empty arrays | decision-gated |
| W5-16 | Deployment configuration unverified: `APP_ENV=production` with the development database; production at `0028` | Medium | matrix G-11; WP-4 §12 | deployment, outside WP-5 |
| W5-17 | Documentation defects: two G registers, three count sets, four missing files, brief §6 list absent | Medium | §3.5; §3.2 X-10 | B6 |
| W5-18 | Excel export absent (G-12) | Low | CSV only | decision-gated |
| W5-19 | No system-health screen for broken links, unowned routes, permission mismatches (G-13) | Low | Overview module panel only | B5 |
| W5-20 | Legacy `/api/db/reset` router answering 410 (D-03) | Low | `app/api/db_reset.py` | cleanup |
| W5-21 | Unused placeholder CSS (D-06) | Low | `styles.css` | cleanup |
| W5-22 | Delivery register hardcoded, not derived (X-09) | Low | `module_register.py` | B5 or B6 |

Count: 3 Critical, 5 High, 9 Medium, 5 Low.

No gap in this table is a confirmed data-integrity defect. The Critical items are
Critical **for WP-5**: each of them would make an administrator edit produce a
result that differs from what the screen promises.

---

## 8. WP-5 implementation batches

Every batch below is independently shippable, has its own tests, and changes no
business table, no route permission, no accounting rule and no migration. A batch
is only "done" when its acceptance criteria are met with a named command or test.

### B0 — Owner decisions (no code)

- **Scope:** approve or change D-WP5-01…D-WP5-07 (§11).
- **Acceptance:** each decision recorded in `DECISIONS.md` with the date and the
  alternative rejected.
- **Tests:** none.
- **Rollback:** not applicable.

### B1 — C-6 validation hardening (server only)

- **Scope:** forbid `permission_any`, `menu_rule != "always"` and `menu_any` on
  non-screen nodes in `validate_catalog`; document container rows as structural.
- **Files:** `app/services/navigation_registry.py`, `docs/FEATURE_REGISTRY_DESIGN.md`,
  `docs/WP4_RELEASE_READINESS.md` (C-6 status).
- **Acceptance criteria:**
  1. A catalogue with one container permission produces a named validation error.
  2. The shipped catalogue validates with zero errors.
  3. `GET /api/navigation` answers 503 for an invalid registry and the admin read
     returns the error text.
  4. `?nav=builtin` renders and the 25 screens are unchanged.
- **Test plan:** extend `tests/test_navigation_registry.py`; add `tests/test_navigation_validation.py`
  for the three refusals and the 503 path; run the full suite; run the Node suite
  (no change expected).
- **Rollback:** revert the two service files and the doc hunks. No schema, no data.
- **Risk:** an installation with an out-of-repo container permission starts
  answering 503; pre-deploy query in §4.5.

### B2 — C-8 label ownership (frontend + contract)

- **Scope:** carry `screen.label` through `navFromApi`; add `titleFor(view)`;
  route every display site through it; server label validation (non-empty,
  ≤120, control characters refused, empty container label only for the Workspace
  group); parity test split into source parity and seed parity.
- **Files:** `static/js/workspace.js`, `static/js/app.js`, `app/services/navigation_registry.py`,
  `tests/js/workspace.test.cjs`, `tests/test_navigation_registry.py`,
  `tests/test_navigation_parity.py`, docs.
- **Acceptance criteria:**
  1. A renamed screen label in the test database appears in rail, tab,
     breadcrumb, palette and `document.title`; the hash, view key and permissions
     are unchanged.
  2. With the API unavailable, titles fall back to `TITLES` and the screen still
     opens.
  3. A label containing `<img src=x onerror=...>` renders as literal text and no
     script runs.
  4. A blank or 121-character screen label is refused by the API with 422 and by
     the editor before save.
  5. Source parity (catalogue vs `workspace.js`) passes; a renamed live row does
     not fail the suite.
- **Test plan:** Node tests for the converter/resolver/fallback; pytest for the
  validation and an API rename round-trip on the test database; browser walk at
  1440/768/390 in both themes; screenshots under `var/shots/`.
- **Rollback:** revert the four code files and the test split. No schema.
- **Risk:** a missed call site shows two names; mitigated by a grep-level test and
  the browser walk across all four surfaces.

### B3 — Registry write API

- **Scope:** Administrator-only write endpoints for nodes and features:
  edit label/description, reorder within a parent, activate/deactivate (never
  delete), change feature binding, change menu rules, set screen permissions,
  change feature status and `depends_on`. Validate with `validate_catalog` before
  writing; refuse a write that would make the registry invalid; audit every
  change with before/after values; optimistic concurrency with `If-Match`
  against `registry_fingerprint` (409 on stale).
- **Files:** `app/api/navigation.py` (or a new `app/api/navigation_admin.py`),
  `app/services/navigation_store.py` (write helpers), `tests/test_navigation_admin.py`.
- **Acceptance criteria:**
  1. Every write is refused for a caller who is not the Administrator role, even
     with `user:manage`.
  2. A write that breaks validation (duplicate order, unknown permission,
     container permission, Home moved or deactivated, alias collision) returns
     422 with the validation message and changes nothing.
  3. A stale `If-Match` returns 409; a current one succeeds and changes the ETag
     of `/api/navigation` for every user.
  4. Every successful write produces one `navigation.update` audit row naming the
     node, the field, the old value and the new value.
  5. Deactivation removes the node and its branch from the menu and keeps the
     row; no delete endpoint exists.
  6. Home cannot be deactivated, renamed to a foreign view, or moved.
- **Test plan:** `tests/test_navigation_admin.py` covering each refusal, the
  concurrency check, the audit row, the ETag change, the role matrix and "a GET
  writes nothing"; full suite.
- **Rollback:** revert the two API/service files; no schema. Data rollback for an
  erroneous edit is the audit record or a restore of the two config tables.
- **Risk:** a write helper that bypasses validation; the helper must call the
  same `validate_catalog` and commit only when it returns no errors.

### B4 — Administration screens

- **Scope:** one Navigation manager screen and one Feature registry screen under
  People and admin, built from the existing list/drawer patterns: tree list with
  search and status filter, inline label edit after B2, up/down ordering (not
  drag-only, for keyboard use), active toggle, feature binding, menu rule,
  screen permissions with the route gate shown read-only, validation panel,
  preview as a chosen role, and a history view read from the audit trail.
- **Files:** `static/index.html`, `static/js/app.js`, `static/css/styles.css`,
  `tests/` for the API contracts used, docs and user manual.
- **Acceptance criteria:**
  1. An administrator can rename, reorder, deactivate and rebind an existing node
     and see the effect on the rail after a reload, without a deploy.
  2. The editor refuses a save that the API would refuse, and shows the same
     message.
  3. The route's real permission gate is displayed for each screen and labelled
     "enforced by the server"; the menu permission is labelled "menu only".
  4. Feature status and dependency edits show which screens would disappear
     before saving.
  5. The screens use the shared drawer, table, pager and filter band; no second
     list implementation.
  6. Keyboard-only operation and both themes work at 1440/768/390.
- **Test plan:** API contract tests (already in B3) plus a browser walk covering
  rename, reorder, deactivate, rebind, preview-as-role, validation refusal and a
  permission check for a non-administrator; evidence JSON and screenshots.
- **Rollback:** revert the frontend files and the new panel markup. The API stays
  usable from a script if the UI is rolled back.
- **Risk:** two navigation sources if the editor writes and the fallback renders;
  the editor operates on the same tables the API reads, and the browser walk
  proves the rail updates.

### B5 — Feature metadata, mapping and system health

- **Scope:** derive `feature_registry.tables` from a reviewed, generated map
  (model table + FK usage per API prefix), fill `depends_on` where a real
  dependency exists, and add a health endpoint/screen that reports: unowned API
  prefixes, nodes whose view is unknown to the router, nodes whose feature is
  unknown, screens whose menu permission differs from the route gate, aliases
  colliding with routes, and an invalid registry. Read-only.
- **Files:** a generator script under `scripts/`, `app/services/navigation_registry.py`
  (health checks), a new API route, the Overview/administration panel,
  `tests/test_navigation_health.py`, docs.
- **Acceptance criteria:**
  1. Every one of the 14 features has a non-empty, generated-and-reviewed table
     list, or an explicit `[]` with a stated reason; no invented table.
  2. The 41 unowned paths are listed with a classification (public, platform,
     authentication, retired) and the list is pinned by a test so a new unowned
     prefix is deliberate.
  3. The health report is empty on the shipped catalogue.
  4. A deliberately broken node (unknown view, colliding alias, mismatched
     permission) appears in the report with its node key.
- **Test plan:** `tests/test_navigation_health.py`; generator check in CI
  (`--check` mode, no write); full suite.
- **Rollback:** revert the script and endpoint; the metadata columns are
  non-functional data and can be regenerated.
- **Risk:** a derived table map that guesses a relationship. The generator may
  only report tables reachable through explicit FKs used by the prefix's routes;
  anything else stays empty.

### B6 — Documentation completion and ID unification

- **Scope:** create `DUPLICATE_FEATURE_AUDIT.md`, `FEATURE_GAP_ANALYSIS.md`,
  `BUSINESS_WORKFLOW_MAP.md`, `DATABASE_RELATIONSHIP_MAP.md`; renumber the
  traceability matrix's gap namespace so it no longer collides with the roadmap's;
  replace the three count sets with one measured table; record the C-6/C-8
  outcomes and the module vocabulary in the design doc and user manual.
- **Acceptance criteria:** the four files exist and are linked from
  `IMPLEMENTATION_ROADMAP.md` §1; one gap namespace; one count table referenced
  by the other documents; the manual explains menu module vs feature vs delivery
  status.
- **Test plan:** link check (no broken relative links in the touched docs); no
  code test.
- **Rollback:** documentation only.

### B7 — Verification and release gate

- **Scope:** full Python and Node suites, parity report, seed-tool check,
  migration head, a browser walk over all 25 screens plus the new administration
  screens, and a security pass over every new write route.
- **Acceptance:** exact counts recorded in `VERIFICATION_REPORT.md`; no skip
  introduced; the migration head unchanged (`0031`); no new route without an
  explicit dependency; every new audit action named.
- **Rollback:** not applicable; this batch records evidence.

---

## 9. Prioritised roadmap

| Order | Batch | Depends on | Why this order | Effort (indicative) |
|---:|---|---|---|---|
| 1 | B0 | — | Blocks every other batch; no code | owner review |
| 2 | B1 | B0 | Smallest change that removes a Critical silent failure | small |
| 3 | B2 | B0 | Makes labels real before any editor exposes them | medium |
| 4 | B3 | B1, B2 | Validation and label rules must exist before writes | medium |
| 5 | B4 | B3 | UI over a proven API; the largest batch | large |
| 6 | B5 | B3 | Mapping and health need the writer to be meaningful | medium |
| 7 | B6 | B1–B5 | Documents the outcomes, including the C-6/C-8 decisions | small |
| 8 | B7 | all | Release gate | medium |

B1 and B2 touch different layers, but running them sequentially keeps the review
surface small; parallelising them is possible if the owner prefers.

**What WP-5 does not deliver:** new business modules, new document types, any
posting rule, any change to accounting, costing, payroll, stock or tax logic. The
registry manages the screens that exist; adding a screen still needs code (view,
route, `TITLES`, component) and then a registry row. A component registry that
would let an administrator create a new screen from configuration alone is a
much larger architecture and is not proposed here (D-WP5-06).

---

## 10. Decision-gated business work (outside WP-5)

These are recorded so they are not lost, and excluded so WP-5 stays a registry
package.

| Item | Gap | Default if no decision |
|---|---|---|
| Payroll → ledger posting | W5-06 | Stays not posted (D-17); the P&L shows payroll, the trial balance does not |
| Document → voucher posting | W5-09 | Stays manual (D-43); the balance sheet keeps the layers separate and names the limits |
| Purchase-order approval | W5-11 | Status stays receipt-driven |
| Quotation stage and lead conversion | W5-12 | Leads stay a separate funnel |
| Service & Workshop | W5-13 | Absent |
| Overtime / salary revision / reimbursement approvals | W5-08 | Labels stay; no request can be raised |
| Live e-mail | N-10 | Test mode only |
| Excel export | W5-18 | CSV only |
| Server-side favourites | W5-15 | Device-local |
| Localisation | §5.4 | English only |
| Missing test coverage | W5-10 | Unchanged until a batch touches the module |

---

## 11. Decisions required from the owner

| ID | Decision | Recommendation | Effect if declined |
|---|---|---|---|
| D-WP5-01 | C-6: how container permissions behave | **Forbid** them on containers (§4.3) | Option A needs a route-level ancestor gate, which is a second access model; Option D keeps the silent contradiction |
| D-WP5-02 | C-8: who owns screen labels | **Registry**, with `TITLES` as fallback (§5.3) | Labels stay code-owned; WP-5 cannot offer label editing |
| D-WP5-03 | Localisation scope | **English only for now**; additive label table later if needed (§5.4) | A label table and locale rules must be designed before B2 |
| D-WP5-04 | Permission for the write API | **Reuse `require_admin("user:manage")`**; no new key | A new `system:manage` key needs a catalogue, matrix and role-seed change |
| D-WP5-05 | Which feature-registry fields are editable | **Label, description, status, depends_on editable; prefixes, permissions, locked stay code-owned** (§5.5) | Editing any code-owned field would break the parity test and 503 the menu |
| D-WP5-06 | Can an administrator create a new screen? | **No.** Code first, then a registry row | A component registry is a separate, much larger programme |
| D-WP5-07 | Confirm the brief §6 "twelve screens" against B4's scope | Owner supplies the list; B4 implements the navigation and feature managers plus validation/preview/history | B4's screen set is defined from the registry's needs, not from the brief |

---

## 12. Preservation guarantees for WP-5

1. **No business table is written.** WP-5 writes only `nav_nodes`,
   `feature_registry`, existing `feature_flags` (unchanged behaviour) and
   `audit_log`. Invoices, orders, stock, ledger, payroll and HR rows are not
   touched.
2. **No schema change in B1–B7.** The registry was designed for editing; no
   column is missing for rename, reorder, activation, feature binding or audit.
   If the owner later approves localisation or server-side favourites, that is a
   separate additive migration with its own rehearsal.
3. **No migration is edited or re-run.** `0031_navigation_registry.py` stays
   byte-identical (`ed52f95566c7b097e1a4dcedd6bb243e51b8ec283a40b1339dec667ecd6c6f04`);
   the seed tool still refuses to rewrite an applied migration.
4. **No access decision changes.** Route gates, the feature middleware, the
   permission parent map and the effective-permission set are untouched. B1 only
   refuses configurations that do not work today.
5. **No screen, route or report is removed.** The eight lists, the 25 screens,
   the 19 accounting sections and every export keep working; validation only
   narrows what can be saved.
6. **The fallback survives.** `workspace.js` keeps its hierarchy and `TITLES`
   for a failed request and `?nav=builtin`; B2 changes which value wins, not
   whether a fallback exists.
7. **Every write is auditable and reversible.** Audit rows carry before/after
   values; the two configuration tables can be dumped and restored independently
   of business data (`pg_dump -t nav_nodes -t feature_registry`).
8. **No data or numbers are invented.** Empty metadata stays empty with a reason
   (`tables`, `depends_on`); a feature with no verified table map is reported as
   such rather than guessed.

---

## 13. Verification performed for this document

| Check | Command / method | Result |
|---|---|---|
| Working tree | `git status --porcelain`, `git log -1` | clean; HEAD `ecaef49` |
| Route table | import `app.main`, count `APIRoute` | 346 objects, 270 paths, 351 total routes |
| Feature ownership of paths | `feature_for_path` over the measured paths | 229 owned, 41 unowned |
| Model/table parity | AST over `app/models` and `create_table` in `alembic/versions` | 89/89, no model-only or migration-only table |
| Migration head | file listing | 43 files, single head `0031` |
| Permissions | `len(PERMISSION_KEYS)` | 49 |
| Development database | read-only `SELECT` | `0031`, 90 tables, 64 nodes, 14 features, 13 flags |
| Container permissions | read-only JSON length query | 0 of 39 containers carry a permission |
| Approval rows | read-only group-by | 5 rows; none of the three unhandled types |
| C-6 reproduction | pure `visible_keys` + `_build_tree` on in-memory nodes | permitted screen dropped with its gated parent |
| C-8 reproduction | Node `navFromApi` with a renamed screen label | label discarded; `flatNav` returns `TITLES` |
| Missing documents | file existence check | 4 absent (listed in §3.5) |

Not run in this pass, and therefore not claimed: pytest, Node suite, parity
report, browser walk, migration rehearsal, production access.

---

## 14. Status

This is a read-only analysis. C-6 and C-8 are resolved **as recommendations
pending approval**, not implemented. No feature was built, no schema changed, no
database migrated or reset, and nothing was committed, pushed or deployed.

**STOP for owner decisions D-WP5-01…D-WP5-07.**
