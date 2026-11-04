/* Compare the built-in menu in workspace.js with the API's menu, for any number
   of permission/feature/role combinations. Read-only: it loads the same file the
   browser loads and feeds it the same payload app.js receives.

   stdin: {"cases":[{"name","permissions":[],"features":[]|null,"admin":bool,"body":{}}]}
   stdout: [{name,ok,error,builtin_visible,builtin_menu,api_visible,api_menu,
             raw_duplicates,raw_unknown}]
   Arrays are sorted so the comparison is order-independent; the API's order is
   asserted separately against the registry. */
const ws = require("../../static/js/workspace.js");

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => { input += chunk; });
process.stdin.on("end", () => {
  const spec = JSON.parse(input || "{}");
  const results = (spec.cases || []).map(run);
  process.stdout.write(JSON.stringify(results));
});

function rawViews(body) {
  const out = [];
  ((body || {}).modules || []).forEach(mod =>
    (mod.categories || []).forEach(cat =>
      (cat.groups || []).forEach(group =>
        (group.screens || []).forEach(screen => out.push(screen && screen.view)))));
  return out;
}

function duplicates(values) {
  return values.filter((value, index) => values.indexOf(value) !== index);
}

function run(testCase) {
  ws.resetNavTree();
  const permissions = testCase.permissions || [];
  const features = testCase.features == null ? null : new Set(testCase.features);
  const ctx = {
    can: key => permissions.includes(key),
    features,
    srAllowed: () => !!testCase.admin,
  };

  const builtinVisible = Object.keys(ws.TITLES)
    .filter(view => ws.viewAllowed(view, ctx)).sort();
  const builtinMenu = Object.keys(ws.TITLES)
    .filter(view => ws.menuAllowed(view, ctx)).sort();

  const converted = ws.navFromApi(testCase.body);
  let apiVisible = [];
  let apiMenu = [];
  if (converted.ok) {
    ws.setNavTree(converted.tree, converted.menu, converted.views);
    const flat = ws.flatNav();
    apiVisible = flat.map(entry => entry.view).sort();
    apiMenu = flat.filter(entry => entry.menu).map(entry => entry.view).sort();
  }
  ws.resetNavTree();

  const raw = rawViews(testCase.body);
  return {
    name: testCase.name,
    ok: converted.ok,
    error: converted.ok ? "" : converted.error,
    builtin_visible: builtinVisible,
    builtin_menu: builtinMenu,
    api_visible: apiVisible,
    api_menu: apiMenu,
    raw_duplicates: duplicates(raw),
    raw_unknown: raw.filter(view => !ws.TITLES[view]),
  };
}
