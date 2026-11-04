/* Emit what workspace.js says about the menu, so the Python registry test can
   compare it with app/services/navigation_catalog.py. Read-only.

   node tests/js/emit_nav_manifest.cjs '{"base":{"dash":[],"products":["product:read"]},"candidates":["product:read","sales:read"]}'
*/
const ws = require("../../static/js/workspace.js");

const spec = JSON.parse(process.argv[2] || "{}");
const base = spec.base || {};
const candidates = spec.candidates || [];
const keys = view => base[view] || [];
const ctx = (view, extra) => ({
  can: k => keys(view).includes(k) || (extra || []).includes(k),
  features: null,
});

const out = {
  nav: ws.NAV,
  titles: ws.TITLES,
  flat: ws.flatNav(),
  view_feature: ws.VIEW_FEATURE,
  view_perm: ws.VIEW_PERM,
  home: ws.HOME,
  home_hash: ws.HOME_HASH,
  alias_customers: ws.parseHash("#/distributors").view,
  routes: {},
  view_allowed_single: {},
  view_allowed_base: {},
  feature_off: {},
  menu_base: {},
  menu_single: {},
};

Object.keys(ws.TITLES).forEach(view => {
  out.routes[view] = ws.parseHash("#/" + view).view;

  out.view_allowed_base[view] = ws.viewAllowed(view, ctx(view, []));
  out.view_allowed_single[view] = candidates.filter(k =>
    ws.viewAllowed(view, {can: key => key === k, features: null}));

  // Every feature list is non-null in the browser; an empty set proves what
  // the view does without its declared feature.
  out.feature_off[view] = ws.viewAllowed(view, {
    can: k => keys(view).includes(k), features: new Set(),
  });

  out.menu_base[view] = ws.menuAllowed(view, ctx(view, []));
  out.menu_single[view] = candidates.filter(k =>
    ws.menuAllowed(view, ctx(view, [k])));
});

process.stdout.write(JSON.stringify(out));
