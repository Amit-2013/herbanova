/* Workspace model tests. Run with `node --test tests/js` (also invoked by
   tests/test_workspace_model.py so the Python suite covers the same contract).
   The browser loads the identical file as static/js/workspace.js. */
const test = require("node:test");
const assert = require("node:assert/strict");
const ws = require("../../static/js/workspace.js");

const perms = (...keys) => ({has: k => keys.includes(k)});
const ctx = (keys, extra = {}) => ({
  can: k => keys.includes(k),
  features: extra.features === undefined ? null : extra.features,
  srAllowed: extra.srAllowed,
});
const allowedAll = () => true;
const labels = path => path.map(c => c.label);

test("every routed view has a navigation path and a title", () => {
  Object.keys(ws.TITLES).forEach(view => {
    const nav = ws.navFor(view);
    assert.ok(nav, `${view} has no NAV entry`);
    assert.equal(nav.label, ws.TITLES[view]);
    assert.ok(ws.crumbPath(view, "", allowedAll).length >= 2, `${view} has no crumbs`);
  });
  assert.equal(ws.flatNav().length, Object.keys(ws.TITLES).length,
    "a view is listed twice in NAV and the breadcrumb would depend on order");
});

test("parseHash keeps routed sections and query strings", () => {
  assert.deepEqual(ws.parseHash("#/products"),
    {view: "products", section: "", key: "products", hash: "#/products"});
  const acc = ws.parseHash("#/accounts/gst-out?from=2026-04-01&to=2026-04-30");
  assert.equal(acc.view, "accounts");
  assert.equal(acc.section, "gst-out");
  assert.equal(acc.key, "accounts/gst-out");
  assert.equal(acc.hash, "#/accounts/gst-out?from=2026-04-01&to=2026-04-30");
  assert.equal(ws.parseHash("").key, ws.HOME);
  assert.equal(ws.parseHash("#/").key, ws.HOME);
  assert.equal(ws.parseHash("#/distributors").view, "customers");
});

test("inventory and scheduled sub-tabs stay one workspace tab", () => {
  assert.equal(ws.parseHash("#/inventory/ledger").key, "inventory");
  assert.equal(ws.parseHash("#/scheduled/log").key, "scheduled");
  assert.equal(ws.parseHash("#/hr/payroll").key, "hr");
  assert.equal(ws.parseHash("#/accounts/trial-balance").key, "accounts/trial-balance");
});

test("opening the same screen twice activates the first tab", () => {
  let model = ws.initialModel();
  model = ws.openTab(model, {view: "products", hash: "#/products"});
  model = ws.openTab(model, {view: "sales", hash: "#/sales"});
  model = ws.openTab(model, {view: "products", hash: "#/products"});
  assert.deepEqual(model.open.map(t => t.key), [ws.HOME, "products", "sales"]);
  assert.equal(model.active, "products");
});

test("Home is first, permanent and cannot be closed", () => {
  const model = ws.initialModel();
  assert.equal(model.open[0].key, ws.HOME);
  assert.equal(model.open[0].closable, false);
  assert.equal(ws.closeTab(model, ws.HOME), model);
  assert.equal(ws.closeAll(model).open.length, 1);
  assert.equal(ws.closeAll(model).active, ws.HOME);
});

test("closing the active tab activates its right neighbour, else the left", () => {
  let model = ws.initialModel();
  ["products", "sales", "leads"].forEach((v, i) => {
    model = ws.openTab(model, {view: v, hash: "#/" + v, title: v + i});
  });
  model = ws.activateTab(model, "sales");
  const closed = ws.closeTab(model, "sales");
  assert.equal(closed.active, "leads");
  const last = ws.closeTab(ws.activateTab(closed, "leads"), "leads");
  assert.equal(last.active, "products");
});

test("close others keeps Home and the chosen tab; closed tabs reopen", () => {
  let model = ws.initialModel();
  ["products", "sales", "leads"].forEach(v => {
    model = ws.openTab(model, {view: v, hash: "#/" + v});
  });
  const others = ws.closeOthers(model, "sales");
  assert.deepEqual(others.open.map(t => t.key), [ws.HOME, "sales"]);
  assert.equal(others.active, "sales");
  const reopened = ws.reopenClosed(others);
  assert.equal(reopened.tab.key, "leads");
  assert.deepEqual(reopened.model.open.map(t => t.key), [ws.HOME, "sales", "leads"]);
  assert.equal(reopened.model.active, "leads");
});

test("close all except Home records every closed tab for reopening", () => {
  let model = ws.initialModel();
  ["products", "sales"].forEach(v => {
    model = ws.openTab(model, {view: v, hash: "#/" + v});
  });
  const all = ws.closeAll(model);
  assert.deepEqual(all.open.map(t => t.key), [ws.HOME]);
  assert.equal(all.closed.length, 2);
  const reopened = ws.reopenClosed(all);
  assert.equal(reopened.model.open.length, 2);
});

test("restoration drops screens the role may no longer open", () => {
  let model = ws.initialModel();
  ["products", "roles", "sales"].forEach(v => {
    model = ws.openTab(model, {view: v, hash: "#/" + v});
  });
  model = ws.activateTab(model, "roles");
  const pruned = ws.pruneModel(model, v => v !== "roles");
  assert.deepEqual(pruned.open.map(t => t.key), [ws.HOME, "products", "sales"]);
  assert.equal(pruned.active, ws.HOME);
  const stillOpen = ws.pruneModel(model, v => v !== "products");
  assert.equal(stillOpen.active, "roles");
});

test("session serialisation round-trips without Home", () => {
  let model = ws.initialModel();
  model = ws.openTab(model, {view: "sales", hash: "#/sales"});
  model = ws.openTab(model, {view: "accounts", section: "gst-out",
    hash: "#/accounts/gst-out?from=2026-04-01", title: "GST output"});
  const restored = ws.deserializeModel(ws.serializeModel(model));
  assert.deepEqual(restored.open.map(t => t.key), [ws.HOME, "sales", "accounts/gst-out"]);
  assert.equal(restored.active, "accounts/gst-out");
  assert.equal(restored.open[2].title, "GST output");
  assert.equal(restored.open[2].hash, "#/accounts/gst-out?from=2026-04-01");
  assert.deepEqual(ws.deserializeModel("not json"), ws.initialModel());
  assert.deepEqual(ws.deserializeModel(JSON.stringify({v: 9})), ws.initialModel());
});

test("a stale duplicate key in storage does not duplicate the tab", () => {
  const text = JSON.stringify({v: 1, active: "products", open: [
    {key: "products", view: "products", section: "", hash: "#/products", title: "Products"},
    {key: "products", view: "products", section: "", hash: "#/products", title: "Products"},
  ]});
  const restored = ws.deserializeModel(text);
  assert.deepEqual(restored.open.map(t => t.key), [ws.HOME, "products"]);
});

test("permission and module-switch rules match the route", () => {
  assert.equal(ws.viewAllowed("products", ctx([])), false);
  assert.equal(ws.viewAllowed("products", ctx(["product:read"])), true);
  assert.equal(ws.viewAllowed("products",
    ctx(["product:read"], {features: new Set(["stock"])})), false);
  assert.equal(ws.viewAllowed("products",
    ctx(["product:read"], {features: new Set(["products"])})), true);
  assert.equal(ws.viewAllowed("compare", ctx(["stock:read"])), true);
  assert.equal(ws.viewAllowed("compare", ctx([])), false);
  assert.equal(ws.viewAllowed("hr", ctx(["hr:attendance_self"])), true);
  assert.equal(ws.viewAllowed("hr", ctx([])), false);
  assert.equal(ws.viewAllowed("accounts", ctx(["accounts:reports"])), true);
  assert.equal(ws.viewAllowed("scheduled", ctx(["email:manage"], {srAllowed: () => true})), true);
  assert.equal(ws.viewAllowed("scheduled", ctx(["email:manage"], {srAllowed: () => false})), false);
  assert.equal(ws.viewAllowed("nonsense", ctx(["user:manage"])), false);
  assert.equal(ws.viewAllowed("settings", ctx([])), true);
});

test("menu visibility is narrower than route access where the app says so", () => {
  assert.equal(ws.menuAllowed("settings", ctx(["audit:read"])), true);
  assert.equal(ws.menuAllowed("settings", ctx([])), false);
  assert.equal(ws.menuAllowed("reports", ctx(["tax:read"])), true);
  assert.equal(ws.menuAllowed("reports", ctx([])), false);
  assert.equal(ws.menuAllowed("tax", ctx(["tax:read"])), false);
  assert.equal(ws.menuAllowed("products", ctx(["product:read"])), true);
});

test("breadcrumbs follow the navigation hierarchy and skip empty levels", () => {
  assert.deepEqual(labels(ws.crumbPath("sales", "", allowedAll)),
    ["Sales and customers", "Sales", "Order desk", "Sales orders"]);
  assert.deepEqual(labels(ws.crumbPath("products", "", allowedAll)),
    ["Stock and supply", "Inventory", "Masters", "Products"]);
  assert.deepEqual(labels(ws.crumbPath("dash", "", allowedAll)),
    ["Overview", "Dashboard", "Overview"]);
  assert.deepEqual(labels(ws.crumbPath("accounts", "GST output", allowedAll)),
    ["Finance and insight", "Books", "Ledgers", "GST output"]);
  const last = ws.crumbPath("sales", "", allowedAll).pop();
  assert.equal(last.current, true);
  assert.equal(last.view, null);
});

test("breadcrumb ancestors only target a screen the role can open", () => {
  const path = ws.crumbPath("sales", "", v => v === "sales");
  assert.deepEqual(path.map(c => c.view), ["sales", "sales", "sales", null]);
  const scoped = ws.crumbPath("sales", "", v => v === "leads" || v === "sales");
  assert.deepEqual(scoped.map(c => c.view), ["leads", "sales", "sales", null]);
});

test("favourites toggle, keep order and never include Home", () => {
  let list = [];
  list = ws.toggleFavourite(list, "sales");
  list = ws.toggleFavourite(list, "products");
  assert.deepEqual(list, ["sales", "products"]);
  list = ws.toggleFavourite(list, "sales");
  assert.deepEqual(list, ["products"]);
  assert.deepEqual(ws.toggleFavourite([ws.HOME, "sales"], "sales"), []);
});

test("recent screens are newest first, unique and bounded", () => {
  let list = [];
  ["products", "sales", "products", "leads", "hr", "reports", "geo", "foc"].forEach(v => {
    list = ws.pushRecent(list, v, 4);
  });
  assert.deepEqual(list, ["foc", "geo", "reports", "hr"]);
  assert.deepEqual(ws.pushRecent(["products"], ws.HOME), ["products"]);
});

test("the strip keeps 20 tabs and evicts the oldest into the reopen list", () => {
  const views = Object.keys(ws.TITLES).filter(v => v !== "dash");
  assert.ok(views.length > 19, "need more views than the cap to exercise it");
  let model = ws.initialModel();
  views.slice(0, 19).forEach(v => { model = ws.openTab(model, {view: v, hash: "#/" + v}); });
  assert.equal(model.open.length, 20, "Home plus 19 screens fills the strip");
  const oldest = model.open[1].key;
  model = ws.openTab(model, {view: "compare", hash: "#/compare"});
  assert.equal(model.open.length, 20, "opening a 21st screen keeps the bound");
  assert.equal(model.open.some(t => t.key === oldest), false, "the oldest screen made way");
  assert.equal(model.open.filter(t => t.key === ws.HOME).length, 1, "Home survives eviction");
  assert.equal(model.active, "compare");
  assert.equal(model.closed[0].key, oldest, "the evicted tab is recoverable");
  const back = ws.reopenClosed(model);
  assert.equal(back.tab.key, oldest);
  assert.equal(back.model.open.length, 20);
});

/* ---------- server hierarchy (default since Batch 4d) ---------- */
const apiTree = () => ({
  modules: [{
    node_key: "m.stock", label: "Stock and supply",
    categories: [{
      node_key: "c.inv", label: "Inventory",
      groups: [{
        node_key: "g.masters", label: "Masters",
        screens: [
          {view: "products", label: "Products", in_menu: true},
          {view: "reports", label: "Reports", in_menu: true},
          {view: "products", label: "Products again", in_menu: true},
          {view: "nowhere", label: "Unknown", in_menu: true},
        ],
      }],
    }],
  }, {
    node_key: "m.fin", label: "Finance and insight",
    categories: [{
      node_key: "c.books", label: "Books",
      groups: [{
        node_key: "g.ledgers", label: "Ledgers",
        screens: [
          {view: "accounts", label: "Accounts", in_menu: true},
          {view: "tax", label: "Tax", in_menu: false},
        ],
      }],
    }],
  }],
});

test("the server hierarchy drops unknown and duplicate screens", () => {
  const conv = ws.navFromApi(apiTree());
  assert.equal(conv.ok, true);
  assert.deepEqual(conv.tree.map(m => m.label), ["Stock and supply", "Finance and insight"]);
  assert.deepEqual(conv.tree[0].categories[0].groups[0].views, ["products", "reports"]);
  assert.equal(conv.views.nowhere, undefined, "a view the router does not know is ignored");
  assert.equal(conv.views.products, true);
  assert.equal(conv.menu.tax, false, "the registry's menu rule travels with the screen");
  assert.equal(ws.navFromApi({}).ok, false);
  assert.equal(ws.navFromApi({modules: []}).ok, false);
  assert.equal(ws.navFromApi({modules: [{label: "Empty", categories: []}]}).ok, false);
});

test("the active tree drives the menu, breadcrumbs and route gate", () => {
  const conv = ws.navFromApi(apiTree());
  ws.setNavTree(conv.tree, conv.menu, conv.views);
  try {
    assert.deepEqual(ws.navTree().map(m => m.label), ["Stock and supply", "Finance and insight"]);
    assert.equal(ws.navAllows("accounts"), true);
    assert.equal(ws.navAllows("sales"), false, "a screen the server hid stays closed");
    assert.equal(ws.navInMenu("tax"), false);
    assert.equal(ws.navInMenu("accounts"), true);

    const flat = ws.flatNav();
    assert.deepEqual(flat.map(n => n.view), ["products", "reports", "accounts", "tax"]);
    assert.equal(flat.length, 4, "only the screens the server sent are listed, once each");
    assert.equal(flat.find(n => n.view === "tax").menu, false);
    assert.equal(ws.navFor("sales"), null);

    assert.equal(ws.menuAllowed("products", ctx(["product:read"])), true);
    const noTax = ws.menuAllowed("tax", ctx(["tax:read"]));
    assert.equal(noTax, false, "in_menu=false wins even though the role may open tax");
    assert.equal(ws.viewAllowed("tax", ctx(["tax:read"])), true,
      "the client rule alone still allows the route; the tree narrows it");

    assert.deepEqual(labels(ws.crumbPath("accounts", "", allowedAll)),
      ["Finance and insight", "Books", "Ledgers", ws.TITLES.accounts]);
    assert.deepEqual(ws.crumbPath("sales", "", allowedAll), [],
      "a screen outside the server tree has no breadcrumb");
  } finally {
    ws.resetNavTree();
  }
  assert.equal(ws.navTree().length, ws.NAV.length, "reset restores the built-in tree");
  assert.equal(ws.navAllows("sales"), true);
  assert.equal(ws.navInMenu("sales"), null);
  assert.equal(ws.flatNav().length, Object.keys(ws.TITLES).length);
});
