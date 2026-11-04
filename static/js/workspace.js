/* HERBANOVA workspace model: navigation hierarchy, workspace tabs, favourites.
   Pure functions only: no DOM, no network, no storage. app.js renders them and
   calls them; tests/js/workspace.test.cjs exercises the same code under Node.
   Loaded before app.js, so the browser and the tests share one definition. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.HBWorkspace = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
"use strict";

const HOME = "home";
const HOME_HASH = "#/dash";

/* One ordered hierarchy drives the sidebar, the breadcrumb and the palette's
   screen list, so a path shown in the breadcrumb is a path in the menu.
   `menu:false` screens are reached from inside another screen (settings,
   dashboard link); they still get a breadcrumb and a title. */
const NAV = [
  {id: "overview", label: "Overview", categories: [
    {id: "dashboard", label: "Dashboard", groups: [
      {id: "workspace", label: "", views: ["dash", "compare"]},
    ]},
  ]},
  {id: "sales", label: "Sales and customers", categories: [
    {id: "pipeline", label: "Pipeline", groups: [
      {id: "lead-desk", label: "Lead desk", views: ["leads", "lost", "followups"]},
    ]},
    {id: "sales", label: "Sales", groups: [
      {id: "order-desk", label: "Order desk", views: ["sales"]},
      {id: "invoicing", label: "Invoicing", views: ["billing"]},
      {id: "approvals", label: "Approvals", views: ["approvals"]},
    ]},
    {id: "parties", label: "Parties", groups: [
      {id: "customer-master", label: "Customer master", views: ["customers"]},
    ]},
  ]},
  {id: "stock", label: "Stock and supply", categories: [
    {id: "buying", label: "Buying", groups: [
      {id: "purchase-desk", label: "Purchase desk", views: ["purchasing"]},
    ]},
    {id: "parties", label: "Parties", groups: [
      {id: "supplier-master", label: "Supplier master", views: ["suppliers"]},
    ]},
    {id: "inventory", label: "Inventory", groups: [
      {id: "masters", label: "Masters", views: ["products"]},
      {id: "stock", label: "Stock", views: ["inventory", "foc"]},
    ]},
  ]},
  {id: "finance", label: "Finance and insight", categories: [
    {id: "books", label: "Books", groups: [
      {id: "ledgers", label: "Ledgers", views: ["accounts"]},
    ]},
    {id: "spend", label: "Spend", groups: [
      {id: "expenses", label: "Expenses", views: ["expenses"]},
    ]},
    {id: "tax", label: "Tax", groups: [
      {id: "tax-master", label: "Tax master", views: ["tax"]},
    ]},
    {id: "insight", label: "Insight", groups: [
      {id: "reports", label: "Reports", views: ["reports", "scheduled"]},
      {id: "analytics", label: "Analytics", views: ["geo"]},
    ]},
  ]},
  {id: "people", label: "People and admin", categories: [
    {id: "people", label: "People", groups: [
      {id: "hr", label: "HR", views: ["hr"]},
    ]},
    {id: "access", label: "Access", groups: [
      {id: "logins", label: "Logins", views: ["users"]},
      {id: "permissions", label: "Permissions", views: ["roles"]},
    ]},
    {id: "governance", label: "Governance", groups: [
      {id: "audit", label: "Audit", views: ["audit"]},
      {id: "settings", label: "Settings", views: ["settings"]},
    ]},
  ]},
];

const TITLES = {dash: "Overview", products: "Products", inventory: "Inventory", purchasing: "Purchases",
                suppliers: "Suppliers", tax: "Tax and discounts",
                sales: "Sales orders", billing: "Billing", accounts: "Accounting & Finance",
                expenses: "Expenses", foc: "Free samples (FOC)",
                approvals: "Approvals", customers: "Customers and distributors",
                leads: "Leads", lost: "Lost leads", followups: "Today's follow-ups",
                reports: "Reports", hr: "HR Management", settings: "Settings & Administration",
                roles: "Roles & Permissions", users: "Logins and employees", audit: "Audit trail",
                compare: "MoM & YoY dashboard", geo: "Geography",
                scheduled: "Scheduled reports"};

const VIEW_PERM = {leads: "lead:read", lost: "lead:read", followups: "lead:read",
                   geo: "sales:read",
                   customers: "sales:read", users: "user:manage", roles: "user:manage",
                   audit: "audit:read",
                   suppliers: "supplier:read", tax: "tax:read", accounts: "accounts:read",
                   expenses: "expense:read",
                   products: "product:read", inventory: "stock:read", purchasing: "stock:read",
                   foc: "foc:read",
                   sales: "sales:read", billing: "sales:read",
                   approvals: "approval:read",
                   hr: "hr:read", scheduled: "email:manage"};

const VIEW_FEATURE = {products: "products", inventory: "stock", purchasing: "stock",
                      foc: "foc",
                      suppliers: "suppliers", sales: "sales", billing: "sales",
                      customers: "sales", geo: "sales",
                      approvals: "approvals", leads: "leads", lost: "leads",
                      followups: "leads", accounts: "accounts", expenses: "accounts",
                      tax: "tax",
                      reports: "reports", compare: "reports", hr: "hr", audit: "audit",
                      scheduled: "scheduled", users: "users", roles: "users"};

/* Only these views have a routed section that names a different screen. The
   in-page tabs of Inventory and Scheduled reports stay one tab. */
const SECTION_VIEWS = {accounts: true};

/* Extra menu rules that are narrower than the route's permission: the screen
   opens from a link inside Settings, so its menu row follows the settings
   audience rather than every signed-in user. */
const MENU_EXTRA = {
  settings: ctx => ctx.can("user:manage") || ctx.can("tax:read") || ctx.can("audit:read") || ctx.can("hr:read"),
  reports: ctx => ["accounts:read", "hr:reports", "sales:read", "stock:read",
                   "supplier:read", "tax:read"].some(k => ctx.can(k)),
};
const NOT_IN_MENU = {tax: true, users: true, audit: true, compare: true};
const MENU_IDS = {
  leads: {id: "navLeads", count: "ldCount"},
  sales: {count: "soCount"},
  approvals: {count: "apCount"},
  purchasing: {count: "poCount"},
  billing: {id: "navBilling"},
  suppliers: {id: "navSuppliers"},
  accounts: {id: "navAccounts"},
  expenses: {id: "navExpenses"},
  reports: {id: "navReports"},
  geo: {id: "navGeo"},
  hr: {id: "navHr"},
  roles: {id: "navRoles"},
  settings: {id: "navSettings"},
  scheduled: {id: "navScheduled"},
};

/* ---------- active hierarchy (server registry, default since Batch 4d) ----------
   The NAV above is the built-in hierarchy and stays the fallback. app.js
   replaces it with the server's answer from GET /api/navigation through
   navFromApi(); every reader below goes through navTree()/navInMenu()/
   navAllows() so the two hierarchies can never mix. `null` means the built-in
   one (fallback or `?nav=builtin`). The server payload is already permission
   filtered; using it can only hide screens, never add one. */
let activeNav = null;               // {tree, menu: {view: bool}, views: {view: true}}

function navTree() { return activeNav ? activeNav.tree : NAV; }
function navAllows(view) { return !activeNav || activeNav.views[view] === true; }
function navInMenu(view) {
  if (!activeNav) return null;
  return Object.prototype.hasOwnProperty.call(activeNav.menu, view) ? activeNav.menu[view] : false;
}
function setNavTree(tree, menu, views) {
  activeNav = {tree: tree, menu: menu || {}, views: views || {}};
}
function resetNavTree() { activeNav = null; }

/* The API tree ({modules:[{label,categories:[{label,groups:[{label,screens:[{view,...}]}]}]}]})
   becomes the shape everything above understands. Unknown views are dropped and
   a view seen twice keeps its first place, so a bad registry row cannot render
   a duplicate entry or a screen the router does not know. */
function navFromApi(payload) {
  if (!payload || !Array.isArray(payload.modules)) return {ok: false, error: "payload"};
  const seen = {}, menu = {}, views = {}, tree = [];
  payload.modules.forEach((mod, mi) => {
    if (!mod || typeof mod.label !== "string" || !Array.isArray(mod.categories)) return;
    const categories = [];
    mod.categories.forEach((cat, ci) => {
      if (!cat || typeof cat.label !== "string" || !Array.isArray(cat.groups)) return;
      const groups = [];
      cat.groups.forEach((group, gi) => {
        if (!group || !Array.isArray(group.screens)) return;
        const list = [];
        group.screens.forEach(screen => {
          const view = screen && screen.view;
          if (!view || !TITLES[view] || seen[view]) return;
          seen[view] = true;
          views[view] = true;
          menu[view] = screen.in_menu !== false;
          list.push(view);
        });
        if (list.length) groups.push({
          id: group.node_key || `g${mi}-${ci}-${gi}`,
          label: typeof group.label === "string" ? group.label : "",
          views: list,
        });
      });
      if (groups.length) categories.push({
        id: cat.node_key || `c${mi}-${ci}`,
        label: cat.label,
        groups,
      });
    });
    if (categories.length) tree.push({
      id: mod.node_key || `m${mi}`,
      label: mod.label,
      categories,
    });
  });
  if (!tree.length) return {ok: false, error: "empty"};
  return {ok: true, tree, menu, views};
}

function featureAllowed(view, features) {
  const key = VIEW_FEATURE[view];
  if (!key) return true;
  // A missing list (older server) means every module is on, as in enter().
  if (!features) return true;
  return typeof features.has === "function" ? features.has(key) : features.indexOf(key) >= 0;
}

function viewAllowed(view, ctx) {
  if (!TITLES[view]) return false;
  const c = ctx || {};
  const can = typeof c.can === "function" ? c.can : () => false;
  if (!featureAllowed(view, c.features)) return false;
  if (view === "compare") return can("sales:read") || can("stock:read");
  if (view === "hr") return can("hr:read") || can("hr:attendance_self");
  if (view === "accounts") return can("accounts:read") || can("accounts:reports");
  if (view === "scheduled") return can("email:manage") && (!c.srAllowed || !!c.srAllowed());
  const perm = VIEW_PERM[view];
  return perm ? can(perm) : true;
}

function menuAllowed(view, ctx) {
  if (!TITLES[view]) return false;
  if (!viewAllowed(view, ctx)) return false;
  // With the server hierarchy the registry's own menu rule decides, so the
  // built-in extras cannot disagree with the screen list the server sent.
  if (activeNav) return navInMenu(view) === true;
  if (NOT_IN_MENU[view]) return false;
  const extra = MENU_EXTRA[view];
  return extra ? !!extra(ctx || {can: () => false}) : true;
}

function flatNav() {
  const out = [];
  navTree().forEach(mod => mod.categories.forEach(cat => cat.groups.forEach(group =>
    group.views.forEach(view => out.push({
      view, label: TITLES[view], module: mod.label, category: cat.label,
      group: group.label,
      menu: activeNav ? navInMenu(view) === true : !NOT_IN_MENU[view],
    })))));
  return out;
}

function navFor(view) {
  return flatNav().find(n => n.view === view) || null;
}
function canonicalKey(view, section) {
  if (!view || view === "dash") return HOME;
  return SECTION_VIEWS[view] && section ? view + "/" + section : view;
}

function parseHash(hash) {
  let raw = String(hash || "").replace(/^#\/?/, "");
  let query = "";
  const q = raw.indexOf("?");
  if (q >= 0) { query = raw.slice(q + 1); raw = raw.slice(0, q); }
  const slash = raw.indexOf("/");
  let view = (slash < 0 ? raw : raw.slice(0, slash)) || "dash";
  const section = slash < 0 ? "" : raw.slice(slash + 1);
  // The older address for the merged customer master still opens that screen.
  if (view === "distributors") view = "customers";
  const path = section ? view + "/" + section : view;
  return {view, section, key: canonicalKey(view, section),
          hash: "#/" + path + (query ? "?" + query : "")};
}

function homeTab() {
  return {key: HOME, view: "dash", section: "", hash: HOME_HASH, title: "Home", closable: false};
}

function initialModel() {
  return {open: [homeTab()], active: HOME, closed: []};
}

function copyModel(model) {
  return {open: model.open.slice(), active: model.active, closed: model.closed.slice()};
}

function normaliseTab(tab) {
  const view = tab && TITLES[tab.view] ? tab.view : "dash";
  const section = view === "accounts" && tab.section ? String(tab.section) : "";
  const key = canonicalKey(view, section);
  return {
    key, view, section,
    hash: tab.hash || (view === "dash" ? HOME_HASH : "#/" + (section ? view + "/" + section : view)),
    title: tab.title || TITLES[view],
    closable: key !== HOME,
  };
}

/* Opening an already-open screen activates it instead of duplicating it; a new
   hash for the same key (another query) becomes that tab's address. */
function openTab(model, tab) {
  const next = normaliseTab(tab);
  const base = model || initialModel();
  const existing = base.open.find(t => t.key === next.key) ||
    (next.key === HOME ? base.open.find(t => t.key === HOME) : null);
  if (existing) {
    const open = base.open.map(t => t.key === existing.key
      ? {...t, hash: next.hash, title: next.title, view: next.view, section: next.section}
      : t);
    return {open, active: existing.key, closed: base.closed.slice()};
  }
  const open = base.open.slice();
  const home = open.findIndex(t => t.key === HOME);
  if (home < 0) open.unshift(homeTab());
  const closed = base.closed.slice();
  // The strip is bounded at 20 tabs. The oldest screen after Home is evicted
  // into the reopen list rather than disappearing, so Reopen can bring it back.
  while (open.length >= 20) {
    const oldest = open.findIndex(t => t.key !== HOME);
    if (oldest < 0) break;
    closed.unshift(open[oldest]);
    open.splice(oldest, 1);
  }
  open.push(next);
  return {open, active: next.key, closed: closed.slice(0, 10)};
}

function activateTab(model, key) {
  if (!model.open.some(t => t.key === key)) return model;
  if (model.active === key) return model;
  return {...copyModel(model), active: key};
}

function closeTab(model, key) {
  if (key === HOME) return model;
  const index = model.open.findIndex(t => t.key === key);
  if (index < 0) return model;
  const closed = [model.open[index], ...model.closed].slice(0, 10);
  const open = model.open.filter(t => t.key !== key);
  const active = model.active === key ? open[Math.min(index, open.length - 1)].key : model.active;
  return {open, active, closed};
}

function closeOthers(model, key) {
  const keep = model.open.find(t => t.key === key);
  const home = model.open.find(t => t.key === HOME) || homeTab();
  const dropped = model.open.filter(t => t.key !== HOME && t.key !== key);
  const open = [home].concat(keep && keep.key !== HOME ? [keep] : []);
  const closed = dropped.reverse().concat(model.closed).slice(0, 10);
  return {open, active: keep ? keep.key : HOME, closed};
}

function closeAll(model) {
  const home = model.open.find(t => t.key === HOME) || homeTab();
  const dropped = model.open.filter(t => t.key !== HOME);
  return {open: [home], active: HOME, closed: dropped.reverse().concat(model.closed).slice(0, 10)};
}

function reopenClosed(model) {
  if (!model.closed.length) return {model, tab: null};
  const tab = model.closed[0];
  const rest = model.closed.slice(1);
  // Keep the closed list openTab hands back: reopening at the 20-tab bound can
  // evict another screen, and that screen must stay recoverable.
  const opened = openTab({...model, closed: rest}, tab);
  return {model: opened, tab};
}

function pruneModel(model, isAllowed) {
  const allow = typeof isAllowed === "function" ? isAllowed : () => true;
  const seen = {};
  const open = [model.open.find(t => t.key === HOME) || homeTab()];
  model.open.forEach(t => {
    if (t.key === HOME || seen[t.key] || !allow(t.view)) return;
    seen[t.key] = true;
    open.push(t);
  });
  const active = open.some(t => t.key === model.active) ? model.active : HOME;
  const closed = model.closed.filter(t => t.key !== HOME && allow(t.view));
  return {open, active, closed};
}

function serializeModel(model) {
  return JSON.stringify({
    v: 1,
    active: model.active,
    open: model.open.filter(t => t.closable).map(t => ({
      key: t.key, view: t.view, section: t.section, hash: t.hash, title: t.title,
    })),
  });
}

function deserializeModel(text) {
  if (!text) return initialModel();
  let data;
  try { data = JSON.parse(text); } catch (err) { return initialModel(); }
  if (!data || data.v !== 1 || !Array.isArray(data.open)) return initialModel();
  let model = initialModel();
  data.open.forEach(t => {
    if (!t || !TITLES[t.view]) return;
    model = openTab(model, t);
  });
  model = activateTab(model, data.active);
  return model;
}

function toggleFavourite(list, key) {
  const current = Array.isArray(list) ? list.filter(k => k && k !== HOME) : [];
  if (current.indexOf(key) >= 0) return current.filter(k => k !== key);
  return current.concat([key]);
}

function pushRecent(list, key, max = 6) {
  const current = (Array.isArray(list) ? list : []).filter(k => k && k !== HOME);
  if (!key || key === HOME) return current;
  return [key].concat(current.filter(k => k !== key)).slice(0, max);
}

function firstAllowed(views, isAllowed) {
  if (typeof isAllowed !== "function") return null;
  return views.find(v => isAllowed(v)) || null;
}

/* Ancestors link to the first screen the role may open at that level, so a
   breadcrumb can never lead to a hidden screen. Empty levels are omitted. */
function crumbPath(view, sectionLabel, isAllowed) {
  const nav = navFor(view);
  if (!nav) return [];
  const module = navTree().find(m => m.label === nav.module);
  if (!module) return [];
  const category = module.categories.find(c => c.label === nav.category);
  const group = category.groups.find(g => g.label === nav.group);
  const viewsInModule = [];
  module.categories.forEach(c => c.groups.forEach(g => g.views.forEach(v => viewsInModule.push(v))));
  const viewsInCategory = [];
  category.groups.forEach(g => g.views.forEach(v => viewsInCategory.push(v)));
  const out = [];
  const push = (label, views) => {
    const target = firstAllowed(views, isAllowed);
    out.push({label, view: target});
  };
  push(module.label, viewsInModule);
  if (category.label) push(category.label, viewsInCategory);
  if (group.label) push(group.label, group.views);
  out.push({label: sectionLabel || TITLES[view], view: null, current: true});
  return out;
}

return {
  HOME, HOME_HASH, NAV, TITLES, VIEW_PERM, VIEW_FEATURE, MENU_IDS,
  viewAllowed, menuAllowed, flatNav, navFor, canonicalKey, parseHash,
  homeTab, initialModel, openTab, activateTab, closeTab, closeOthers,
  closeAll, reopenClosed, pruneModel, serializeModel, deserializeModel,
  toggleFavourite, pushRecent, crumbPath,
  navTree, navAllows, navInMenu, setNavTree, resetNavTree, navFromApi,
};
});
