/* HERBANOVA Business Control - front end.
   Talks only to the FastAPI endpoints; the server stays the authority on every rule.
   All text that came from the server goes through esc() before it reaches innerHTML. */
(() => {
"use strict";

/* ---------- helpers ---------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = n => new Intl.NumberFormat("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Number(n) || 0);
const qty = n => new Intl.NumberFormat("en-IN", {maximumFractionDigits: 3}).format(Number(n) || 0);
const PLURALS = {batch: "batches", entry: "entries"};
const plural = (n, w) => `${n} ${n === 1 ? w : (PLURALS[w] || w + "s")}`;
const parseTs = s => new Date(/([zZ]|[+-]\d\d:?\d\d)$/.test(s) ? s : s + "Z");
const fmtDate = d => d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", {day: "2-digit", month: "short", year: "numeric"}) : "–";
const fmtStamp = s => s ? parseTs(s).toLocaleString("en-IN", {day: "2-digit", month: "short", year: "numeric", hour: "numeric", minute: "2-digit"}) : "–";
const fmtDay = s => s ? parseTs(s).toLocaleDateString("en-IN", {day: "2-digit", month: "short", year: "numeric"}) : "–";
const daysUntil = iso => { const t = new Date(); t.setHours(0, 0, 0, 0); return Math.round((new Date(iso + "T00:00:00") - t) / 86400000); };
const poValue = po => Math.round(po.lines.reduce((s, l) => s + Number(l.qty) * Number(l.unit_cost), 0) * 100) / 100;

const state = {user: null, perms: new Set(), modules: null, dashboard: null, products: [], warehouses: [], batches: [], pos: [], movements: null,
               suppliers: [], bankChanges: [], supFilter: "all",
               dists: [], orders: [], approvals: [], leads: [], rp: {cat: [], key: "stock", from: "", to: "", data: null, tok: 0}, soFilter: "all", apFilter: "pending", ldFilter: "open", ldOwner: "all", distFilter: "all",
               users: [], roles: [], employees: [], permCatalog: [], audit: {rows: [], actions: [], actors: [], total: 0},
               tax: {company: null, rates: [], slabs: [], states: [], rateFilter: "all"},
               invoices: [], creditNotes: [], debitNotes: [], invFilter: "all",
               accounts: {outstanding: null, entries: [], gst: null, tb: null, ageing: null},
               poFilter: "all", view: "dash", tab: "stock", lostFilter: "",
               fuFilter: "today", rpPage: 1, rpSearch: "", rpCategory: "",
               dashRange: 30, dashLoading: false, dashError: null, dashSeq: 0, chart: {index: -1},
               expiry: {bucket: "all", loading: false, data: null},
               palette: {open: false, items: [], i: -1, seq: 0, timer: 0},
               hr: {dashboard: null, employees: [], attendance: [], leave: [], od: [], payroll: []}};
state.rp.filters = {employee_id: "", department: "", branch_id: ""};
state.rp.opts = null;
try {
  const saved = Number(localStorage.getItem("hb.dashRange"));
  if ([7, 30, 90].includes(saved)) state.dashRange = saved;
} catch (e) { /* storage blocked */ }
const can = p => state.perms.has(p);

/* ---------- server calls ---------- */
async function api(path, opts = {}) {
  const o = {credentials: "same-origin", headers: {"Content-Type": "application/json"}, ...opts};
  if (o.body && typeof o.body !== "string") o.body = JSON.stringify(o.body);
  let res;
  try { res = await fetch(path, o); }
  catch (e) { return {status: 0, ok: false, body: {detail: "Cannot reach the server. Check the connection and try again."}}; }
  let body = null;
  try { body = await res.json(); } catch (e) { /* empty body */ }
  if (res.status === 401 && state.user && !path.endsWith("/login")) leave("Your session has ended. Sign in again.");
  return {status: res.status, ok: res.ok, body};
}
function detail(b) {
  const d = b && b.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map(e => ((e.loc || []).slice(1).join(".") + ": " + e.msg).replace(/^: /, "")).join("; ");
  return b ? JSON.stringify(b) : "No response from the server.";
}

/* ---------- toast ---------- */
let toastTimer;
function toast(res, label) {
  const t = $("#toast");
  t.className = res.ok ? "" : "bad";
  t.innerHTML = `<b>${res.status || "–"}</b><span>${esc(label)}${res.ok ? "" : ": " + esc(detail(res.body))}</span>`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hide"), 4800);
}

/* ---------- drawer ---------- */
let lastFocus = null;
function openDrawer(title, sub, html, wide = false) {
  lastFocus = document.activeElement;
  $("#dtitle").textContent = title;
  $("#dsub").textContent = sub || "";
  $("#dbody").innerHTML = html;
  $("#drawer").classList.toggle("wide", wide);
  $("#scrim").classList.remove("hide");
  $("#drawer").classList.remove("hide");
  const first = $("#dbody").querySelector("input,select,textarea");
  (first || $("#dclose")).focus();
}
function closeDrawer() {
  $("#scrim").classList.add("hide");
  $("#drawer").classList.add("hide");
  $("#dbody").innerHTML = "";
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  lastFocus = null;
}
const drawerOpen = () => !$("#drawer").classList.contains("hide");

/* ---------- session ---------- */
function enter(u) {
  state.user = u;
  state.perms = new Set(u.permissions || []);
  if (u.must_change_password) { showPasswordChange(u); return; }
  state.dashboard = null;
  state.dashLoading = true;
  state.dashError = null;
  state.expiry = {bucket: "all", loading: false, data: null};
  state.chart.index = -1;
  closePalette();
  $("#mustChange").classList.add("hide");
  $("#login").classList.add("hide");
  $("#shell").classList.remove("hide");
  $("#who").textContent = u.username;
  const show = (id, on) => { const el = $(id); if (el) el.classList.toggle("hide", !on); };
  show("#navLeads", can("lead:read"));
  show("#navSuppliers", can("supplier:read"));
  show("#navBilling", can("sales:read"));
  show("#navAccounts", can("accounts:read"));
  show("#navHr", can("hr:read") || can("hr:attendance_self"));
  show("#navSettings", can("user:manage") || can("tax:read") || can("audit:read") || can("hr:read"));
  // Every other module link follows the read permission its API requires, so a
  // role is never offered a screen that can only answer 403.
  const showView = (v, on) => $$(`.side a.nav[data-v="${v}"]`).forEach(a => a.classList.toggle("hide", !on));
  showView("lost", can("lead:read"));
  showView("followups", can("lead:read"));
  showView("customers", can("sales:read"));
  showView("sales", can("sales:read"));
  showView("approvals", can("approval:read"));
  showView("purchasing", can("stock:read"));
  showView("products", can("product:read"));
  showView("inventory", can("stock:read"));
  showView("distributors", can("sales:read"));
  showView("reports", ["accounts:read", "hr:reports", "sales:read", "stock:read",
                       "supplier:read", "tax:read"].some(k => can(k)));
  $$(".nav-group").forEach(g => g.classList.toggle("hide", !g.querySelector("a.nav:not(.hide)")));
  $("#role").textContent = u.role;
  route();
  loadAll();
}
function leave(msg) {
  state.user = null; state.perms = new Set(); state.movements = null;
  state.dashboard = null; state.dashLoading = false; state.dashError = null;
  closePalette();
  closeDrawer();
  $("#mustChange").classList.add("hide");
  $("#changePwForm").reset();
  $("#shell").classList.add("hide");
  $("#login").classList.remove("hide");
  $("#lerr").textContent = msg || "";
  $("#u").focus();
}
function showPasswordChange(u) {
  closeDrawer();
  $("#changePwForm").reset();
  $("#mcErr").textContent = "";
  $("#mcUser").textContent = u.username || "";
  $("#login").classList.add("hide");
  $("#shell").classList.add("hide");
  $("#mustChange").classList.remove("hide");
  $("#mcCurrent").focus();
}
async function changePassword(form) {
  const f = form.elements, err = $("#mcErr"), btn = $("#mcBtn");
  err.textContent = "";
  const current = f.current_password.value, next = f.new_password.value;
  if (!current) { err.textContent = "Enter your current password."; return; }
  if (next !== f.confirm_password.value) { err.textContent = "The new passwords do not match."; return; }
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter(re => re.test(next)).length;
  if (next.length < 12 || next.length > 128 || classes < 3) {
    err.textContent = "Use 12 to 128 characters with at least three of: lowercase, uppercase, digits, symbols.";
    return;
  }
  if (next === current) { err.textContent = "The new password must differ from the current password."; return; }
  btn.disabled = true;
  const res = await api("/api/auth/change-password", {method: "POST",
    body: {current_password: current, new_password: next}});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  form.reset();
  toast(res, "Password changed");
  enter(res.body);
}
async function login(e) {
  e.preventDefault();
  $("#lerr").textContent = "";
  const btn = $("#loginBtn"); btn.disabled = true;
  const res = await api("/api/auth/login", {method: "POST", body: {username: $("#u").value.trim(), password: $("#p").value}});
  btn.disabled = false;
  if (!res.ok) { $("#lerr").textContent = res.status === 401 ? "Username or password is incorrect." : detail(res.body); return; }
  $("#p").value = "";
  const me = await api("/api/auth/me");           // permissions come from the server, not from a copy in this file
  enter(me.ok ? me.body : res.body);
}
async function boot() {
  const me = await api("/api/auth/me");
  if (me.ok) enter(me.body); else $("#login").classList.remove("hide");
}

/* ---------- data ---------- */
async function loadAll() {
  if (!state.dashboard) { state.dashLoading = true; renderDash(); }
  const none = Promise.resolve({ok: true, body: []});
  const canUsers = can("user:manage");
  const canTax = can("tax:read");
  const canSales = can("sales:read");
  const canAccounts = can("accounts:read");
  const canApprovals = can("approval:read");
  const [h, mo, p, w, b, o, ds, so, ap, ld, us, rl, em, pcat, sp, bc, co, rt, sl, st, inv, cn, dn, ao, ae, ag, da] = await Promise.all([
    api("/api/health"), api("/api/modules"),
    can("product:read") ? api("/api/products?page=1&page_size=200") : none,
    can("stock:read") ? api("/api/warehouses") : none,
    can("stock:read") ? api("/api/inventory/batches") : none,
    can("stock:read") ? api("/api/purchase-orders?page=1&page_size=200") : none,
    canSales ? api("/api/distributors?page=1&page_size=200") : none,
    canSales ? api("/api/sales-orders?page=1&page_size=200") : none,
    canApprovals ? api("/api/approvals?page=1&page_size=200") : none,
    can("lead:read") ? api("/api/leads?page=1&page_size=200") : none,
    canUsers ? api("/api/users") : none, canUsers ? api("/api/roles") : none,
    can("employee:read") ? api("/api/employees") : none,
    canUsers ? api("/api/roles/permissions") : none,
    can("supplier:read") ? api("/api/suppliers?page=1&page_size=200") : none,
    can("supplier:read") ? api("/api/suppliers/bank-changes") : none,
    canTax ? api("/api/company") : none, canTax ? api("/api/tax/rates") : none,
    canTax ? api("/api/discount-slabs") : none, canTax ? api("/api/tax/states") : none,
    canSales ? api("/api/invoices?page=1&page_size=200") : none, canSales ? api("/api/credit-notes") : none,
    canSales ? api("/api/debit-notes") : none,
    canAccounts ? api("/api/accounts/outstanding") : none,
    canAccounts ? api("/api/accounts/payments") : none,
    canAccounts ? api("/api/accounts/ageing") : none,
    api(`/api/dashboard?range=${state.dashRange}`)]);
  if (!state.user) return;
  // The register is load-bearing for the Overview: keep the last good copy if a
  // refresh fails rather than blanking the module panel.
  if (mo.ok && mo.body) state.modules = mo.body;
  // Overview figures are counted by the server over the whole database; the lists
  // below are capped at 200 rows and must never be used to compute a tile.
  state.dashLoading = false;
  if (da.ok && da.body && !Array.isArray(da.body)) {
    state.dashboard = da.body;
    state.dashError = null;
    state.expiry.data = null;
  } else if (!state.dashboard) {
    state.dashError = da.ok ? "The server returned an unexpected response." : detail(da.body);
  }
  state.products = p.ok ? p.body : [];
  state.warehouses = w.ok ? w.body : [];
  state.batches = b.ok ? b.body : [];
  state.pos = o.ok ? o.body.slice().sort((x, y) => y.id - x.id) : [];
  state.dists = ds.ok ? ds.body : [];
  state.orders = so.ok ? so.body : [];
  state.approvals = ap.ok ? ap.body : [];
  state.leads = ld.ok ? ld.body : [];
  state.users = us.ok ? us.body : [];
  state.roles = rl.ok ? rl.body : [];
  state.employees = em.ok ? em.body : [];
  state.permCatalog = pcat.ok ? pcat.body : [];
  state.suppliers = sp.ok ? sp.body : [];
  state.bankChanges = bc.ok ? bc.body : [];
  state.tax.company = co.ok ? co.body : null;
  state.tax.rates = rt.ok ? rt.body : [];
  state.tax.slabs = sl.ok ? sl.body : [];
  state.tax.states = st.ok ? st.body : [];
  state.invoices = inv.ok ? inv.body : [];
  state.creditNotes = cn.ok ? cn.body : [];
  state.debitNotes = dn.ok ? dn.body : [];
  if (ao.ok) state.accounts.outstanding = ao.body;
  state.accounts.entries = ae.ok ? ae.body : [];
  if (ag.ok) state.accounts.ageing = ag.body;
  $("#env").textContent = h.ok ? `Environment: ${h.body.env}` : "Service unreachable";
  const failed = [p, w, b, o, ds, so, canApprovals ? ap : null, ld, sp].find(r => r && !r.ok);
  if (failed) toast(failed, "Some data could not be loaded");
  renderAll();
  if (state.dashboard && state.expiry.bucket !== "all") setExpiryBucket(state.expiry.bucket);
  if (state.movements) loadMovements();
}
async function loadMovements() {
  const r = await api("/api/inventory/movements?limit=200");
  state.movements = r.ok ? r.body : [];
  if (!r.ok) toast(r, "Ledger could not be loaded");
  renderLedger();
}

/* ---------- routing ---------- */
const TITLES = {dash: "Overview", products: "Products", inventory: "Inventory", purchasing: "Purchases",
                suppliers: "Suppliers", tax: "Tax and discounts",
                sales: "Sales orders", billing: "Billing", accounts: "Accounting & Finance",
                approvals: "Approvals", distributors: "Distributors", customers: "Customers",
                leads: "Leads", lost: "Lost leads", followups: "Today's follow-ups",
                reports: "Reports", hr: "HR Management", settings: "Settings & Administration",
                users: "Users and rights", audit: "Audit trail"};
const VIEW_PERM = {leads: "lead:read", lost: "lead:read", followups: "lead:read",
                   customers: "sales:read", users: "user:manage", audit: "audit:read",
                   suppliers: "supplier:read", tax: "tax:read", accounts: "accounts:read",
                   products: "product:read", inventory: "stock:read", purchasing: "stock:read",
                   distributors: "sales:read", sales: "sales:read", billing: "sales:read",
                   approvals: "approval:read",
                   hr: "hr:read"};
function route() {
  const [v, sub] = (location.hash.replace(/^#\//, "") || "dash").split("/");
  // Staff with only self-service attendance still reach the HR page for their own day.
  const allowed = !VIEW_PERM[v] || can(VIEW_PERM[v]) || (v === "hr" && can("hr:attendance_self"));
  state.view = TITLES[v] && allowed ? v : "dash";
  $("#shell").dataset.view = state.view;
  if (state.view === "inventory") state.tab = ["stock", "ledger", "warehouses"].includes(sub) ? sub : "stock";
  $$(".view").forEach(s => s.classList.toggle("hide", s.id !== "v-" + state.view));
  $$(".nav[data-v]").forEach(a => { const on = a.dataset.v === state.view; a.classList.toggle("on", on); on ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"); });
  $("#title").textContent = TITLES[state.view];
  if (state.view === "inventory") showTab();
  renderHead();
  if (state.view === "reports") openReports();
  if (state.view === "audit") openAudit();
  if (state.view === "lost") renderLost();
  if (state.view === "followups") renderFollowups();
  if (state.view === "customers") renderCustomers();
  if (state.view === "settings") renderSettings();
  if (state.view === "hr") { if (can("hr:read")) openHr(); else renderHr(); }
  document.title = `${TITLES[state.view]} - HERBANOVA`;
}
function showTab() {
  $$("[data-tab]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
  ["stock", "ledger", "warehouses"].forEach(t => $("#i-" + t).classList.toggle("hide", t !== state.tab));
  if (state.tab === "ledger" && !state.movements) loadMovements();
}
function renderHead() {
  const v = state.view; let sub = "", act = "";
  if (v === "dash") {
    sub = "Every figure is counted by the server over the whole database. Open a tile to see the records behind it.";
    if (can("db:reset")) act = `<button class="btn" data-act="reset-db" type="button">Reset database</button>`;
  }
  if (v === "products") {
    sub = `${plural(state.products.length, "product")} on file, ${state.products.filter(x => x.status === "active").length} active.`;
    if (can("product:write")) act = `<button class="btn" data-act="new-product" type="button">New product</button>`;
  }
  if (v === "inventory") {
    sub = "Stock by batch, the movement ledger and warehouses.";
    if (state.tab === "warehouses" && can("stock:write")) act = `<button class="btn" data-act="new-warehouse" type="button">New warehouse</button>`;
  }
  if (v === "purchasing") {
    const n = s => state.pos.filter(x => x.status === s).length;
    sub = `${n("open")} open, ${n("partially_received")} part received, ${n("received")} received, ${n("cancelled")} cancelled.`;
    if (can("stock:write")) act = `<button class="btn" data-act="new-po" type="button">New purchase order</button>`;
  }
  if (v === "suppliers") {
    const pending = state.bankChanges.filter(b => b.status === "pending").length;
    const incomplete = state.suppliers.filter(s => s.needs_completion).length;
    sub = `${plural(state.suppliers.length, "supplier")}. ${pending} bank change${pending === 1 ? "" : "s"} awaiting approval, ${incomplete} still to be completed.`;
    if (can("supplier:write")) act = `<button class="btn" data-act="new-supplier" type="button">New supplier</button>`;
  }
  if (v === "sales") {
    const n = c => state.orders.filter(o => o.status === c).length;
    sub = `${n("approved")} ready to dispatch, ${n("pending_approval")} awaiting approval, ${n("draft")} draft.`;
    if (can("sales:write")) act = `<button class="btn" data-act="new-so" type="button">New sales order</button>`;
  }
  if (v === "billing") {
    const issued = state.invoices.filter(i => i.status === "issued").length;
    const corrected = state.creditNotes.length + state.debitNotes.length;
    sub = `${plural(state.invoices.length, "tax invoice")}, ${issued} live. ${plural(corrected, "credit or debit note")}. An issued invoice is never edited: correct it with a note.`;
  }
  if (v === "accounts") {
    const out = state.accounts.outstanding;
    sub = out
      ? `${money(out.receivable_total)} receivable, ${money(out.payable_total)} payable, from the documents as they stand.`
      : "Outstanding, ledgers, GST registers and the trial balance, all built from the documents.";
    if (can("accounts:write")) {
      act = `<button class="btn" data-act="new-entry" data-kind="receipt" type="button">Record receipt</button>`
          + ` <button class="btn ghost" data-act="new-entry" data-kind="payment" type="button">Record payment</button>`;
    }
  }
  if (v === "approvals") sub = `${state.approvals.filter(a => a.status === "pending").length} waiting for a decision. The person who raised an order cannot approve it.`;
  if (v === "distributors") {
    const active = state.dists.filter(d => d.status === "active").length;
    const blocked = state.dists.filter(d => d.status === "blocked").length;
    const incomplete = state.dists.filter(d => d.needs_completion).length;
    sub = `${plural(state.dists.length, "distributor")}. Active: ${active}, Blocked: ${blocked}${incomplete ? `, needing details: ${incomplete}` : ""}. Credit in use counts orders awaiting approval, approved and dispatched.`;
    if (can("distributor:write")) act = `<button class="btn" data-act="new-dist" type="button">New distributor</button>`;
    // The header is rebuilt on every render, so the chosen filter lives in
    // state and is restored here; reading it from the DOM lost the choice and
    // crashed on first load, when this screen's header is not the one shown.
    const fopt = ["all", ...DIST_STATUSES, "incomplete"].map(v =>
      `<option value="${v}"${state.distFilter === v ? " selected" : ""}>${v === "all" ? "All" : v === "incomplete" ? "Needs completion" : DSTAT[v][1]}</option>`).join("");
    act += ` <select id="dists-filter" class="ghost" aria-label="Filter distributors by status">${fopt}</select>`;
  }
  if (v === "leads") {
    const od = state.leads.filter(l => l.follow_up_state === "overdue").length, td = state.leads.filter(l => l.follow_up_state === "today").length;
    sub = `${od} overdue and ${td} due today across the team. Only a lead’s owner or an administrator can change it.`;
    if (can("lead:write")) act = `<button class="btn" data-act="new-lead" type="button">New lead</button>`;
  }
  if (v === "lost") {
    sub = `${plural(state.leads.filter(l => l.status === "lost").length, "lost lead")}. A lost lead keeps its history; only an Administrator can reopen it.`;
  }
  if (v === "followups") {
    const n = state.leads.filter(l => l.follow_up_state === "today").length;
    const od = state.leads.filter(l => l.follow_up_state === "overdue").length;
    sub = `${n} due today, ${od} overdue across the team. Record a remark and schedule the next follow-up.`;
    if (can("lead:write")) act = `<button class="btn" data-act="new-lead" type="button">New lead</button>`;
  }
  if (v === "customers") {
    sub = `${plural(state.dists.length, "customer")} in the distributor master. Open a record to see orders, invoices and outstanding.`;
    if (can("distributor:write")) act = `<button class="btn" data-act="new-dist" type="button">New customer</button>`;
  }
  if (v === "hr") {
    const d = state.hr.dashboard;
    sub = d ? `${d.active_employees} active of ${d.total_employees} employees. ${d.pending_approvals} HR approvals pending.`
            : "Employee records, attendance, leave, on-duty and payroll, integrated with Approvals and Reports.";
    if (can("hr:write")) act = `<button class="btn" data-act="hr-employees" type="button">Employee master</button>`;
  }
  if (v === "settings") sub = "Users, roles, employees, tax configuration, HR policies and the audit trail.";
  if (v === "reports") sub = "Every figure is checked against the records it comes from. Downloads are recorded in the audit log.";
  if (v === "users") {
    const locked = state.users.filter(u => u.locked).length, pending = state.users.filter(u => u.must_change_password).length;
    sub = `${plural(state.users.length, "login")} and ${plural(state.employees.length, "employee")}. ${pending} awaiting a password change, ${locked} locked. Temporary passwords are shown once.`;
    const btn = [];
    if (can("employee:write")) btn.push(`<button class="btn ghost" data-act="new-employee" type="button">New employee</button>`);
    btn.push(`<button class="btn ghost" data-act="new-role" type="button">New role</button>`);
    btn.push(`<button class="btn" data-act="new-user" type="button">New user</button>`);
    act = btn.join(" ");
  }
  if (v === "tax") {
    const live = state.tax.rates.filter(r => r.in_force).length;
    const c = state.tax.company;
    sub = c ? `${c.legal_name} · ${c.gstin || "unregistered"} · ${plural(live, "rate")} in force today.`
            : "No company tax profile yet. Until it is saved, no tax can be quoted.";
  }
  if (v === "audit") sub = "Every create, change, approval, export and sign-in. Secrets are stripped before a row is written; downloads are recorded too.";
  $("#subtitle").textContent = sub;
  $("#actions").innerHTML = act;
}

/* ---------- shared fragments ---------- */
function shelf(expiry) {
  if (!expiry) return `<div class="shelf none"><span class="t">No expiry date</span></div>`;
  const d = daysUntil(expiry);
  let cls, text;
  if (d < 0) { cls = "gone"; text = `Expired ${plural(-d, "day")} ago`; }
  else if (d === 0) { cls = "gone"; text = "Expires today"; }
  else { cls = d <= 90 ? "urgent" : d <= 180 ? "watch" : "ok"; text = d >= 365 ? `${(d / 365).toFixed(1)} years left` : `${plural(d, "day")} left`; }
  const pct = d <= 0 ? 100 : Math.max(4, Math.min(100, d / 365 * 100));
  return `<div class="shelf ${cls}"><span class="t">${esc(text)}</span><div class="g"><i style="width:${pct.toFixed(0)}%"></i></div><small>${esc(fmtDate(expiry))}</small></div>`;
}
const empty = (el, show, title, hint) => { el.classList.toggle("hide", !show); if (show) el.innerHTML = `<b>${esc(title)}</b>${esc(hint || "")}`; };
const MOVE = {receipt: ["Goods received", "ok"], issue: ["Issued", "off"], transfer: ["Transferred", "off"],
              adjust: ["Adjustment", "warn"], return: ["Returned", "off"], reversal: ["Reversal", "warn"]};

/* ---------- renderers ---------- */
function renderAll() { renderHead(); renderDash(); renderProducts(); renderStock(); renderLedger(); renderWarehouses(); renderPOs(); renderSuppliers(); renderTax(); renderSales(); renderBilling(); renderAccounts(); renderApprovals(); renderDists(); renderLeads(); renderUsers(); renderLost(); renderFollowups(); renderCustomers(); renderSettings(); if (state.view === "hr") renderHr(); }

// The module list is not here any more: it is served by GET /api/modules from
// app/core/module_register.py, so the screen renders the server's register and
// there is no second copy to drift from it (COR-007).

function renderDash() {
  const d = state.dashboard;
  const loading = state.dashLoading;
  const err = state.dashError;
  const u = state.user;

  $("#dashGreet").textContent = u ? `${greeting()}, ${u.username}` : "Overview";
  $("#dashDate").textContent = new Date().toLocaleDateString("en-IN", {
    weekday: "long", day: "numeric", month: "long", year: "numeric" });
  $$("[data-dash-range]").forEach(b =>
    b.setAttribute("aria-pressed", String(Number(b.dataset.dashRange) === state.dashRange)));
  $("#dashNewSo").classList.toggle("hide", !can("sales:write"));
  $("#dashReset").classList.toggle("hide", !can("db:reset"));

  $("#dashSkeleton").classList.toggle("hide", !(loading && !d));
  $("#dashError").classList.toggle("hide", !err);
  $("#dashContent").classList.toggle("hide", !d);
  $("#dashContent").setAttribute("aria-busy", loading ? "true" : "false");
  if (err) {
    $("#dashErrText").textContent = d
      ? ` The last figures loaded are shown. ${err}`
      : ` ${err}`;
  }

  // A failed load is shown as such. It must never be drawn as zeros.
  $("#whCallout").classList.toggle("hide", !d || d.warehouse_count !== 0 || !can("stock:write"));
  if (!d) {
    $("#dashUpdated").textContent = loading ? "Loading figures from the server…" : "";
    return;
  }

  const period = d.from === d.to ? fmtDate(d.from) : `${fmtDate(d.from)} to ${fmtDate(d.to)}`;
  $("#dashUpdated").innerHTML = loading
    ? `Refreshing the ${esc(String(d.range))}-day period…`
    : `As at <b>${esc(fmtDate(d.as_of))}</b> · ${esc(String(d.range))}-day period, `
      + `${esc(period)} · updated ${esc(fmtStamp(d.generated_at))}`;

  renderAttention(d.attention || []);
  renderKpis(d.kpis || []);
  renderChart(d.sales_vs_purchases);
  renderDashAgeing(d.receivables_ageing);
  renderExpiry(d);
  renderDashWarehouses(d.stock_by_warehouse);
  renderOpenPos(d.open_pos);
  renderDashApprovals(d.approvals);
  renderTopProducts(d.top_products, d);
  renderCategory(d.category_sales);
  renderInsights(d.insights);
  renderActivity(d.recent_activity);
  renderHealth(d.health);
  renderModuleList();

  const openTotal = d.purchase_orders ? d.purchase_orders.open_count : 0;
  const c = $("#poCount");
  c.textContent = openTotal; c.classList.toggle("hide", !openTotal);
  c.setAttribute("aria-label", `${openTotal} open purchase orders`);
}

/* ---------- dashboard fragments ---------- */
function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function inrShort(n) {
  const v = Number(n) || 0, a = Math.abs(v);
  if (a >= 1e7) return `₹${(v / 1e7).toFixed(a >= 1e8 ? 0 : 1)} Cr`;
  if (a >= 1e5) return `₹${(v / 1e5).toFixed(a >= 1e6 ? 0 : 1)} L`;
  if (a >= 1e3) return `₹${(v / 1e3).toFixed(a >= 1e4 ? 0 : 1)} K`;
  return `₹${Math.round(v)}`;
}
const dayLabel = iso => iso
  ? new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short" })
  : "";

function niceMax(v) {
  if (!(v > 0)) return 1;
  const power = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / power;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * power;
}

function deltaText(v) {
  if (v === null || v === undefined) return `<span class="delta flat">no prior period to compare</span>`;
  const n = Number(v);
  if (!isFinite(n)) return `<span class="delta flat">no prior period to compare</span>`;
  const dir = n > 0 ? "up" : n < 0 ? "down" : "flat";
  const arrow = n > 0 ? "▲" : n < 0 ? "▼" : "■";
  return `<span class="delta ${dir}">${arrow} ${Math.abs(n).toFixed(1)}% against the previous period</span>`;
}

function sparkline(values) {
  const vals = values.map(Number).filter(Number.isFinite);
  if (vals.length < 2) return "";
  const w = 112, h = 30, max = Math.max(...vals), min = Math.min(...vals);
  const step = w / (vals.length - 1);
  const y = v => max === min ? h / 2 : h - 4 - ((v - min) / (max - min)) * (h - 8);
  const pts = vals.map((v, i) => `${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true" focusable="false"><polyline points="${pts}"/></svg>`;
}

function renderAttention(items) {
  const el = $("#attention"), note = $("#attNote");
  const live = items.filter(i => i.available && i.severity !== "ok");
  const gaps = items.filter(i => !i.available);
  const shown = [...live, ...gaps];
  note.textContent = shown.length
    ? `${plural(shown.length, "item")}${gaps.length ? ` · ${gaps.length} data gap${gaps.length === 1 ? "" : "s"}` : ""}`
    : "";
  if (!shown.length) {
    el.innerHTML = `<li class="att-empty">Nothing needs attention in the figures the server can see.</li>`;
    return;
  }
  el.innerHTML = shown.map(i => {
    if (!i.available) {
      const gap = i.gap ? ` (${i.gap})` : "";
      return `<li><span class="att-item att-off"><span class="att-body"><b>${esc(i.label)}</b><span>${esc(i.note || "This figure cannot be sourced yet.")}${esc(gap)}</span></span><span class="chip off">No data</span></span></li>`;
    }
    const bits = [];
    if (i.count !== null && i.count !== undefined) bits.push(plural(i.count, "record"));
    if (i.units !== null && i.units !== undefined) bits.push(`${qty(i.units)} units`);
    if (i.amount) bits.push(`₹ ${money(i.amount)}`);
    const sev = i.severity === "bad" ? "att-bad" : "att-warn";
    const tag = i.href ? "a" : "span";
    const href = i.href ? ` href="${esc(i.href)}"` : "";
    return `<li><${tag} class="att-item ${sev}"${href}><span class="att-body"><b>${esc(i.label)}</b><span>${esc(bits.join(" · ") || "Open the records behind this figure.")}</span></span>${i.href ? `<span class="att-go">Open</span>` : ""}</${tag}></li>`;
  }).join("");
}

function renderKpis(kpis) {
  const el = $("#stats");
  if (!kpis.length) {
    el.innerHTML = `<div class="att-empty">No figure on this screen is available to your role.</div>`;
    return;
  }
  el.innerHTML = kpis.map(k => {
    const trend = Array.isArray(k.trend) && k.trend.length > 1 ? sparkline(k.trend) : "";
    return `<a class="kpi" href="${esc(k.href)}">
      <span class="kpi-label">${esc(k.label)}</span>
      <span class="kpi-value">${esc(qty(k.value))}</span>
      ${k.note && trend ? `<span class="kpi-note">${esc(k.note)}</span>` : ""}
      ${trend ? `<span class="kpi-trend">${trend}<em>${esc(k.trend_note || "")}</em></span>`
              : `<span class="kpi-trend off"><em>${esc(k.trend_note || k.note || "")}</em></span>`}
    </a>`;
  }).join("");
}

function hideChartTip() {
  const tip = $("#chartTip");
  if (tip) tip.classList.add("hide");
  $$("#salesChart .hit.on").forEach(h => h.classList.remove("on"));
  state.chart.index = -1;
}

function chartTip(i) {
  const c = state.dashboard && state.dashboard.sales_vs_purchases;
  if (!c || !c.series || !c.series[i]) return;
  const pt = c.series[i], n = c.series.length;
  const svg = $("#salesChart"), tip = $("#chartTip");
  if (!svg || !tip) return;
  state.chart.index = i;
  $$(".hit", svg).forEach((h, j) => h.classList.toggle("on", j === i));
  tip.innerHTML = `<b>${esc(fmtDate(pt.date))}</b>`
    + (c.sales_visible ? `<span><i class="sales"></i>Sales ₹ ${money(pt.sales)}</span>` : "")
    + (c.purchases_visible ? `<span><i class="purchases"></i>Purchases ₹ ${money(pt.purchases)}</span>` : "");
  tip.classList.remove("hide");
  const ratio = n > 1 ? i / (n - 1) : 0.5;
  const left = 58 + ratio * (744 - 58);
  tip.style.left = `${(left / 760) * 100}%`;
  tip.style.top = "50%";
}

function renderChart(c) {
  const panel = $("#chartPanel"), svg = $("#salesChart");
  const legend = $("#chartLegend"), totals = $("#chartTotals");
  const note = $("#chartNote"), title = $("#chartTitle");
  hideChartTip();
  if (!c) {
    panel.classList.add("hide");
    return;
  }
  panel.classList.remove("hide");
  const from = fmtDate(c.from), to = fmtDate(c.to);
  note.textContent = `${from} to ${to}; the previous period is `
    + `${fmtDate(c.previous_from)} to ${fmtDate(c.previous_to)}.`;
  title.textContent = c.sales_visible && c.purchases_visible ? "Sales and purchases"
    : c.sales_visible ? "Sales" : "Purchases received";
  legend.innerHTML = (c.sales_visible ? `<span class="sales"><i></i>Sales</span>` : "")
    + (c.purchases_visible ? `<span class="purchases"><i></i>Purchases</span>` : "");

  const series = c.series || [];
  if (!series.length) {
    svg.innerHTML = "";
    totals.innerHTML = `<span class="gap-note">No days fall in this period.</span>`;
    return;
  }

  const W = 760, x0 = 58, x1 = 744, y0 = 14, y1 = 218;
  const vals = [];
  series.forEach(p => {
    if (c.sales_visible && p.sales != null) vals.push(Number(p.sales));
    if (c.purchases_visible && p.purchases != null) vals.push(Number(p.purchases));
  });
  const max = niceMax(Math.max(...vals, 0));
  const x = i => x0 + (series.length === 1 ? 0.5 : i / (series.length - 1)) * (x1 - x0);
  const y = v => y1 - (Number(v) / max) * (y1 - y0);

  const grid = [0, 0.25, 0.5, 0.75, 1].map(f => {
    const gy = y1 - f * (y1 - y0);
    return `<line class="grid-line" x1="${x0}" y1="${gy.toFixed(1)}" x2="${x1}" y2="${gy.toFixed(1)}"/>`
      + `<text class="axis-label" x="${x0 - 8}" y="${(gy + 4).toFixed(1)}" text-anchor="end">${esc(inrShort(max * f))}</text>`;
  }).join("");

  const every = Math.max(1, Math.ceil(series.length / 6));
  const xlabels = series.map((p, i) => (i % every === 0 || i === series.length - 1)
    ? `<text class="axis-label" x="${x(i).toFixed(1)}" y="${y1 + 20}" text-anchor="middle">${esc(dayLabel(p.date))}</text>`
    : "").join("");

  const line = key => series.map((p, i) =>
    `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[key] ?? 0).toFixed(1)}`).join(" ");
  const dots = key => series.map((p, i) =>
    `<circle class="dot ${key}" cx="${x(i).toFixed(1)}" cy="${y(p[key] ?? 0).toFixed(1)}" r="2.6"/>`).join("");
  const area = c.sales_visible
    ? `<path d="${line("sales")} L${x(series.length - 1).toFixed(1)},${y1} L${x0},${y1} Z" fill="url(#salesFill)" stroke="none"/>`
    : "";

  const step = series.length > 1 ? (x1 - x0) / (series.length - 1) : (x1 - x0);
  const hits = series.map((p, i) => {
    const left = Math.max(x0, x(i) - step / 2);
    const right = Math.min(x1, x(i) + step / 2);
    return `<rect class="hit" data-i="${i}" x="${left.toFixed(1)}" y="${y0}" width="${(right - left).toFixed(1)}" height="${y1 - y0}"/>`;
  }).join("");

  svg.innerHTML = `<defs><linearGradient id="salesFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="var(--moss)" stop-opacity=".20"/>
      <stop offset="1" stop-color="var(--moss)" stop-opacity="0"/>
    </linearGradient></defs>${grid}${xlabels}
    ${c.sales_visible ? area + `<path class="series-sales" d="${line("sales")}"/>` + dots("sales") : ""}
    ${c.purchases_visible ? `<path class="series-purchases" d="${line("purchases")}"/>` + dots("purchases") : ""}
    ${hits}`;
  svg.setAttribute("aria-label",
    `${title.textContent} from ${from} to ${to}. `
    + (c.sales_visible ? `Sales total ${money(c.sales_total)} rupees. ` : "")
    + (c.purchases_visible ? `Purchases total ${money(c.purchases_total)} rupees. ` : "")
    + "Use the left and right arrow keys to read each day.");
  state.chart.index = -1;

  const bits = [];
  if (c.sales_visible) bits.push(`<span><b>Sales</b> ₹ ${money(c.sales_total)} ${deltaText(c.sales_change)}</span>`);
  if (c.purchases_visible) bits.push(`<span><b>Purchases</b> ₹ ${money(c.purchases_total)} ${deltaText(c.purchases_change)}</span>`);
  bits.push(`<span class="source-line">${esc(c.note || "")}</span>`);
  totals.innerHTML = bits.join("");
}

function renderDashAgeing(a) {
  const el = $("#ageing"), note = $("#ageNote");
  if (!a) {
    note.textContent = "";
    el.innerHTML = `<p class="gap-note">Receivables are not shown because your role cannot read accounting.</p>`;
    return;
  }
  note.textContent = `As at ${fmtDate(a.as_of)} · ${plural(a.count, "invoice")}`;
  const max = Math.max(...a.buckets.map(b => Number(b.amount)), 0) || 1;
  el.innerHTML = a.buckets.map(b => {
    const amt = Number(b.amount);
    const pct = amt > 0 ? Math.max(2, amt / max * 100) : 0;
    const tone = b.key === "90+" ? "bad" : b.key === "61-90" ? "warn" : "ok";
    return `<div class="age-row">
      <div class="age-top"><span>${esc(b.label)} <small>${plural(b.count, "invoice")}</small></span><b>₹ ${money(amt)}</b></div>
      <div class="age-bar ${tone}" aria-hidden="true"><i style="width:${pct.toFixed(1)}%"></i></div>
    </div>`;
  }).join("")
  + `<p class="age-total"><span>Total outstanding</span><b>₹ ${money(a.total)}</b></p>`
  + `<p class="gap-note">${esc(a.note || "")}</p>`;
}

function expiryLabel(bucket) {
  return { expired: "already expired", lt30: "expiring within 30 days", lt90: "expiring in 31 to 90 days" }[bucket]
    || "expiring within 90 days";
}

function renderExpiry(d) {
  const w = d && d.expiry_watch;
  const el = $("#watch"), note = $("#watchNote");
  $$("[data-eb]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.eb === state.expiry.bucket)));
  if (state.expiry.loading) {
    note.textContent = "Loading…";
    el.innerHTML = `<li><span class="none">Loading the batches in this window…</span></li>`;
    return;
  }
  if (!w) {
    note.textContent = "";
    el.innerHTML = `<li><span class="none">Stock is not available to your role.</span></li>`;
    return;
  }
  let rows, total;
  if (state.expiry.bucket === "all") {
    rows = w.rows || [];
    total = w.shown_of != null ? w.shown_of : rows.length;
  } else {
    const x = state.expiry.data;
    if (x && x.error) {
      note.textContent = "";
      el.innerHTML = `<li><span class="none">${esc(x.error)}</span></li>`;
      return;
    }
    rows = x && x.rows ? x.rows : [];
    total = x && x.total != null ? x.total : rows.length;
  }
  note.textContent = `${total > rows.length ? `Showing ${rows.length} of ${total}. ` : ""}${plural(total, "batch")} ${expiryLabel(state.expiry.bucket)}.`;
  el.innerHTML = (rows.length ? rows.map(b => {
    const left = b.days_left < 0 ? `Expired ${plural(-b.days_left, "day")} ago`
      : b.days_left === 0 ? "Expires today" : `${plural(b.days_left, "day")} left`;
    const tone = b.tone === "bad" ? "bad" : b.tone === "warn" ? "warn" : "off";
    return `<li><div><button class="rowbtn" data-act="expiry-detail" data-id="${b.batch_id}" type="button">${esc(b.product_name)}</button>
      <small>Batch ${esc(b.batch_no)} · ${esc(b.warehouse)} · ${esc(qty(b.on_hand))} on hand</small></div>
      <div class="r"><span class="chip ${tone}">${esc(left)}</span></div></li>`;
  }).join("") : `<li><span class="none">Nothing in stock falls in this window.</span></li>`)
  + `<li><span class="gap-note">Batch value is not shown because stock carries no cost (GAP-D04).</span></li>`;
}

async function setExpiryBucket(bucket) {
  state.expiry.bucket = bucket;
  $$("[data-eb]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.eb === bucket)));
  if (bucket === "all") {
    state.expiry.loading = false;
    state.expiry.data = null;
    renderExpiry(state.dashboard || {});
    return;
  }
  state.expiry.loading = true;
  state.expiry.data = null;
  renderExpiry(state.dashboard || {});
  const res = await api(`/api/dashboard/expiry?bucket=${encodeURIComponent(bucket)}&page_size=25`);
  if (state.expiry.bucket !== bucket) return;
  state.expiry.loading = false;
  state.expiry.data = res.ok ? res.body : { error: detail(res.body) };
  if (!res.ok) toast(res, "Expiry list could not be loaded");
  renderExpiry(state.dashboard || {});
}

function expiryDetail(id) {
  const d = state.dashboard;
  if (!d) return;
  const pool = [];
  if (d.expiry_watch) pool.push(...(d.expiry_watch.rows || []));
  if (state.expiry.data && state.expiry.data.rows) pool.push(...state.expiry.data.rows);
  const b = pool.find(r => Number(r.batch_id) === Number(id));
  if (!b) return;
  const left = b.days_left < 0 ? `Expired ${plural(-b.days_left, "day")} ago`
    : b.days_left === 0 ? "Expires today" : `${plural(b.days_left, "day")} left`;
  openDrawer("Batch expiry", `${b.product_name} · ${b.sku}`, `
    <dl class="dl">
      <dt>Batch</dt><dd>${esc(b.batch_no)}</dd>
      <dt>Warehouse</dt><dd>${esc(b.warehouse)}</dd>
      <dt>On hand</dt><dd>${esc(qty(b.on_hand))} units</dd>
      <dt>Expiry</dt><dd>${esc(fmtDate(b.expiry))} <span class="chip ${b.tone === "bad" ? "bad" : b.tone === "warn" ? "warn" : "off"}">${esc(left)}</span></dd>
      <dt>Suggested action</dt><dd>${esc(b.action)}</dd>
    </dl>
    <div class="note">The value of this stock is not shown because a batch carries no cost (GAP-D04).</div>
    <div class="actions"><a class="btn ghost" href="#/inventory/stock">Open inventory</a><button class="btn ghost" type="button" data-act="close">Close</button></div>`);
}

function renderDashWarehouses(list) {
  const el = $("#whList");
  if (!list) {
    el.innerHTML = `<li class="gap-note">Stock by warehouse is not available to your role.</li>`;
    return;
  }
  const total = list.reduce((s, w) => s + Number(w.units), 0);
  el.innerHTML = (list.length ? list.map(w => {
    const units = Number(w.units);
    const share = total > 0 ? units / total * 100 : 0;
    const shareText = units > 0 && share < 0.5 ? "<1%" : `${share.toFixed(0)}%`;
    return `<li><div class="wh-top"><span><b>${esc(w.name)}</b><small>${plural(w.batches, "batch")} in stock</small></span>
      <span class="num">${esc(qty(units))} units<small>${shareText} of stock</small></span></div>
      <div class="wh-bar" aria-hidden="true"><i style="width:${share.toFixed(1)}%"></i></div></li>`;
  }).join("") : `<li><span class="none">No warehouse has been added yet.</span></li>`)
  + `<li><span class="gap-note">Capacity is not captured (GAP-D03), so a fill level against capacity cannot be shown.</span></li>`;
}

function renderOpenPos(o) {
  const el = $("#openpos"), note = $("#poNote");
  if (!o) {
    note.textContent = "";
    el.innerHTML = `<li><span class="none">Purchase orders are not available to your role.</span></li>`;
    return;
  }
  const rows = o.rows || [];
  note.textContent = (o.count > o.shown ? `Showing ${o.shown} of ${o.count}. ` : "") + (o.note || "");
  el.innerHTML = rows.length ? rows.map(p => {
    const pct = Math.max(0, Math.min(100, Number(p.pct_received) || 0));
    return `<li><div><button class="rowbtn" data-act="open-po" data-id="${p.id}" type="button">${esc(p.po_number)}</button>
      <small>${esc(p.supplier)} · ${esc(qty(p.received_units))} of ${esc(qty(p.ordered_units))} units received</small>
      <div class="wh-bar" aria-hidden="true"><i style="width:${pct.toFixed(1)}%"></i></div></div>
      <div class="r"><span class="num">₹ ${money(p.value)}<small>${pct.toFixed(0)}% received</small></span></div></li>`;
  }).join("") : `<li><span class="none">No purchase order is waiting for goods.</span></li>`;
}

function renderDashApprovals(a) {
  const el = $("#approvalList"), note = $("#apNote");
  if (!a) {
    note.textContent = "";
    el.innerHTML = `<li><span class="none">Approvals are not available to your role.</span></li>`;
    return;
  }
  const rows = a.rows || [];
  note.textContent = (a.count > a.shown ? `Showing ${a.shown} of ${a.count}. ` : "") + (a.note || "");
  el.innerHTML = rows.length ? rows.map(x => `<li><div>
      <button class="rowbtn" data-act="dash-ap" data-id="${x.id}" type="button">${esc(x.request_no || x.document_number || "Request")}</button>
      <small>${esc(x.request_type_label)} · ${esc(x.subject || x.document_number || "")} · raised by ${esc(x.requested_by)}</small></div>
      <div class="r">${(x.reasons || []).includes("credit_limit")
        ? `<span class="chip bad">Over credit limit</span>` : `<span class="chip warn">Pending</span>`}</div></li>`).join("")
    : `<li><span class="none">Nothing is waiting for a decision.</span></li>`;
}

function dashOpenApproval(id) {
  if (state.approvals.some(a => a.id === Number(id))) return apDetail(id);
  const a = state.dashboard && state.dashboard.approvals
    ? (state.dashboard.approvals.rows || []).find(x => x.id === Number(id)) : null;
  if (!a) return;
  state.approvals = [a, ...state.approvals.filter(x => x.id !== a.id)];
  apDetail(id);
}

function renderTopProducts(t, d) {
  const el = $("#topProducts"), note = $("#topNote");
  if (!t) {
    note.textContent = "";
    el.innerHTML = `<li><span class="none">Sales are not available to your role.</span></li>`;
    return;
  }
  note.textContent = `${fmtDate(d.from)} to ${fmtDate(d.to)}, taxable value before GST`;
  const rows = t.rows || [];
  if (!rows.length) {
    el.innerHTML = `<li><span class="none">No issued invoice falls in this period.</span></li>`;
    return;
  }
  const max = Math.max(...rows.map(r => Number(r.revenue)), 0) || 1;
  el.innerHTML = rows.map(r => {
    const rev = Number(r.revenue), prev = Number(r.previous_revenue);
    const pct = Math.max(0, rev / max * 100);
    const change = r.change == null
      ? (prev === 0 && rev > 0 ? `<span class="delta up">new this period</span>` : `<span class="delta flat">no prior sales</span>`)
      : Number(r.change) > 0 ? `<span class="delta up">▲ ${Number(r.change).toFixed(1)}%</span>`
      : Number(r.change) < 0 ? `<span class="delta down">▼ ${Math.abs(Number(r.change)).toFixed(1)}%</span>`
      : `<span class="delta flat">no change</span>`;
    return `<li><div><b>${esc(r.name)}</b><small>${esc(r.sku)} · ${esc(qty(r.qty))} units</small>
      <div class="wh-bar" aria-hidden="true"><i style="width:${pct.toFixed(1)}%"></i></div></div>
      <div class="r"><span class="num">₹ ${money(rev)}<small>${change}</small></span></div></li>`;
  }).join("");
}

function renderCategory(c) {
  const el = $("#category");
  if (!c || c.available === false) {
    el.innerHTML = `<div class="category-empty"><div class="donut" aria-hidden="true"></div>
      <div><b>No data yet</b><p>${esc(c && c.note || "Sales cannot be grouped by category until a category is captured on each product.")}</p>
      <code>${esc(c && c.gap || "GAP-D01")}</code></div></div>`;
    return;
  }
  el.innerHTML = `<p class="gap-note">Category totals are not available.</p>`;
}

/* ---------- phase 3 insight cards ---------- */
function renderInsights(ins) {
  renderInsightPipeline(ins && ins.pipeline);
  renderInsightCustomers(ins && ins.customers);
  renderInsightPurchasing(ins && ins.purchasing);
  renderInsightCorrections(ins && ins.corrections);
  renderInsightHrToday(ins && ins.hr);
}

function renderInsightPipeline(p) {
  const show = !!(p && (p.sales || p.leads));
  $("#pipePanel").classList.toggle("hide", !show);
  if (!show) return;
  const col = (title, rows, render, extra = "") => `<div><h3 class="ins-h">${esc(title)}</h3>
    <ul class="rows">${rows.length ? rows.map(render).join("") : `<li><span class="none">None.</span></li>`}</ul>${extra}</div>`;
  const parts = [];
  if (p.sales) {
    const d = p.sales.dispatch || {};
    const dispatch = d.average_days != null
      ? `Raised to dispatch: ${d.average_days} days on average across ${plural(d.measured, "dispatched order")}. ${d.note || ""}`
      : `Order-to-dispatch time is not available yet. ${d.note || ""}`;
    parts.push(col(`Sales orders · ${plural(p.sales.total, "order")}`, p.sales.rows,
      r => `<li><div><b>${esc(r.label)}</b><small>${plural(r.count, "order")}</small></div>
        <div class="r"><span class="num">₹ ${money(r.value)}</span></div></li>`,
      `<p class="gap-note">${esc(dispatch)}</p>`));
  }
  if (p.leads) parts.push(col(`Leads · ${plural(p.leads.total, "lead")}`, p.leads.rows,
    r => `<li><div><b>${esc(r.label)}</b></div><span class="num">${qty(r.count)}</span></li>`));
  $("#pipeBody").innerHTML = parts.join("");
}

function renderInsightCustomers(c) {
  $("#custPanel").classList.toggle("hide", !c);
  if (!c) return;
  $("#custNote").textContent = `${fmtDate(c.from)} to ${fmtDate(c.to)} · top by invoiced value`;
  $("#custTop").innerHTML = c.top
    ? (c.top.length ? c.top.map(r => `<li><div><b>${esc(r.name)}</b><small>${plural(r.invoices, "invoice")}</small></div>
        <div class="r"><span class="num">₹ ${money(r.revenue)}</span></div></li>`).join("")
      : `<li><span class="none">No issued invoice falls in this period.</span></li>`)
    : `<li><span class="none">Top customers are not available to your role.</span></li>`;
  $("#custOutWrap").classList.toggle("hide", !c.outstanding);
  if (c.outstanding) {
    $("#custOut").innerHTML = (c.outstanding.length ? c.outstanding.map(r => `<li><div><b>${esc(r.name)}</b><small>${plural(r.invoices, "invoice")}</small></div>
        <div class="r"><span class="num">₹ ${money(r.outstanding)}</span></div></li>`).join("")
      : `<li><span class="none">Nothing is outstanding.</span></li>`)
      + `<li><div><b>Total outstanding</b></div><span class="num">₹ ${money(c.outstanding_total)}</span></li>`;
  }
  $("#custCreditWrap").classList.toggle("hide", !c.credit);
  if (c.credit) {
    $("#custCredit").innerHTML = (c.credit.length ? c.credit.map(r => {
      const pct = Number(r.pct_used) || 0;
      const pctText = `${pct.toLocaleString("en-IN", {maximumFractionDigits: 0})}%`;
      return `<li><div><b>${esc(r.name)}</b><small>₹ ${money(r.exposure)} of ₹ ${money(r.credit_limit)} in use</small>
        <div class="meter use" aria-hidden="true"><i style="width:${Math.min(pct, 100).toFixed(1)}%;background:${pct > 100 ? "var(--bad)" : pct >= 80 ? "var(--turmeric)" : "var(--moss)"}"></i></div></div>
        <div class="r"><span class="num">${pctText}${pct > 100 ? "<small>over limit</small>" : ""}</span></div></li>`;
    }).join("") : `<li><span class="none">No distributor has a credit limit.</span></li>`);
  }
}

function renderInsightPurchasing(p) {
  $("#purPanel").classList.toggle("hide", !p);
  if (!p) return;
  $("#purNote").textContent = `${plural(p.open_count, "open purchase order")}`
    + ` · ${p.no_receipt} with no goods received · ${p.partial} part received`;
  $("#purAge").innerHTML = (p.rows || []).map(r => `<li><div><b>${esc(r.label)}</b><small>${plural(r.count, "order")}</small></div>
    <div class="r"><span class="num">₹ ${money(r.value)}</span></div></li>`).join("")
    || `<li><span class="none">No purchase order is waiting for goods.</span></li>`;
  $("#purGap").textContent = p.note || "";
}

function renderInsightCorrections(c) {
  $("#corrPanel").classList.toggle("hide", !c);
  if (!c) return;
  $("#corrNote").textContent = `${fmtDate(c.from)} to ${fmtDate(c.to)}`;
  const latest = [...(c.credit_notes.rows || []).map(r => ({...r, kind: "Credit"})),
                  ...(c.debit_notes.rows || []).map(r => ({...r, kind: "Debit"}))]
    .sort((a, b) => (b.date || "").localeCompare(a.date || "")).slice(0, 6);
  $("#corrNotes").innerHTML =
    `<li><div><b>Credit notes</b><small>${plural(c.credit_notes.count, "note")}</small></div>
      <div class="r"><span class="num">₹ ${money(c.credit_notes.value)}</span></div></li>`
    + `<li><div><b>Debit notes</b><small>${plural(c.debit_notes.count, "note")}</small></div>
      <div class="r"><span class="num">₹ ${money(c.debit_notes.value)}</span></div></li>`
    + (latest.length ? latest.map(r => `<li><div><b>${esc(r.kind)} note ${esc(r.number)}</b>
        <small>${esc(r.invoice)} · ${esc(r.distributor)} · ${esc(r.reason)}</small></div>
        <div class="r"><span class="num">₹ ${money(r.total)}</span></div></li>`).join("")
      : `<li><span class="none">No credit or debit note was issued in this period.</span></li>`);
  $("#postWrap").classList.remove("hide");
  const posts = c.post_billing;
  $("#corrPosts").innerHTML = posts.count
    ? posts.rows.map(r => {
        const tone = r.status === "approved" ? "ok" : r.status === "rejected" ? "bad" : r.status === "pending" ? "warn" : "off";
        return `<li><div><b>${esc(r.request_no || "—")}</b><small>${esc(r.document || "")} ${esc(r.subject || "")}</small></div>
          <div class="r"><span class="chip ${tone}">${esc(r.status)}</span>
          <small>${esc(fmtStamp(r.requested_at))}</small></div></li>`;
      }).join("")
    : `<li><span class="none">No post-billing request in this period.</span></li>`;
}

function renderInsightHrToday(h) {
  $("#hrPanel").classList.toggle("hide", !h);
  if (!h) return;
  $("#hrNote").textContent = fmtDate(h.date);
  const stat = (n, label) => `<div><b>${qty(n)}</b><span>${esc(label)}</span></div>`;
  $("#hrStats").innerHTML = stat(h.headcount, "active employees")
    + stat(h.marked, "attendance marked") + stat(h.not_marked, "not marked")
    + stat(h.leave_pending, "leave pending") + stat(h.od_pending, "on-duty pending");
  const rows = (h.attendance || []).filter(r => r.count > 0);
  $("#hrAtt").innerHTML = rows.length
    ? rows.map(r => `<li><div><b>${esc(r.label)}</b></div><span class="num">${qty(r.count)}</span></li>`).join("")
    : `<li><span class="none">No attendance is marked for today.</span></li>`;
}

function renderActivity(a) {
  const el = $("#activity"), note = $("#actNote");
  if (!a) {
    note.textContent = "";
    el.innerHTML = `<li><span class="none">The audit trail is not available to your role.</span></li>`;
    return;
  }
  const rows = a.rows || [];
  note.textContent = a.total > a.shown ? `Latest ${a.shown} of ${a.total} entries.` : `${plural(a.total, "entry")}.`;
  el.innerHTML = rows.length ? rows.map(r => {
    const changed = r.changes && Object.keys(r.changes).length ? ` · ${Object.keys(r.changes).join(", ")}` : "";
    return `<li><div><span class="who-done">${esc(r.actor)}</span>
      <span class="what">${esc(r.action)} · ${esc(r.record)}${esc(changed)}</span></div>
      <time datetime="${esc(r.at || "")}">${esc(fmtStamp(r.at))}</time></li>`;
  }).join("") : `<li><span class="none">No activity has been recorded yet.</span></li>`;
}

function renderHealth(h) {
  const el = $("#health"), prog = $("#prog"), bar = $("#barfill");
  if (!h) {
    prog.textContent = "";
    el.innerHTML = `<p class="gap-note">Health information is not available.</p>`;
    return;
  }
  const m = h.modules || {}, s = h.schema || {}, b = h.backup || {}, al = h.alerts || {};
  prog.textContent = `${m.working ?? 0} of ${m.counted ?? 0} modules working`;
  bar.style.width = `${Number(m.percent) || 0}%`;
  const schemaOk = !!s.at_head;
  const schemaText = s.current
    ? `${s.current}${schemaOk ? " · at the latest migration" : s.head ? ` · latest is ${s.head}` : ""}`
    : "No migration version recorded";
  const backupOk = !!b.status && b.status !== "not_recorded";
  el.innerHTML = `
    <div class="health-row"><div class="h-label"><b>Modules</b><span>From the server's module register.</span></div>
      <span class="chip ${m.counted && m.working === m.counted ? "ok" : "warn"}">${m.working ?? 0} of ${m.counted ?? 0}</span></div>
    <div class="health-row"><div class="h-label"><b>Schema migration</b><span>${esc(schemaText)}</span></div>
      <span class="chip ${schemaOk ? "ok" : "warn"}">${schemaOk ? "At head" : "Check"}</span></div>
    <div class="health-row"><div class="h-label"><b>Backup and restore</b><span>${esc(b.note || "Not recorded.")}</span></div>
      <span class="chip ${backupOk ? "ok" : "warn"}">${backupOk ? "Recorded" : "Not recorded"}</span></div>
    <div class="health-row"><div class="h-label"><b>Alert channel</b><span>${esc(al.note || "")}</span></div>
      <span class="chip ${al.configured ? "ok" : "off"}">${al.configured ? "Configured" : "Not configured"}</span></div>`;
}

function renderModuleList() {
  const reg = state.modules;
  if (!reg) return;
  const CHIP = reg.chips;
  $("#mods").innerHTML = reg.groups.map(g => {
    const rows = reg.modules.filter(m => m.group === g.name);
    return `<li class="grp"><b>${esc(g.name)}</b><span>${g.counted ? `${g.working} of ${g.counted} working` : "optional"}</span></li>`
      + rows.map(m => {
        const chip = CHIP[m.status] || ["off", m.status];
        return `<li><div>${esc(m.name)}<small>${esc(m.does)}</small></div><span class="chip ${chip[0]}">${esc(chip[1])}</span></li>`;
      }).join("");
  }).join("");
}

async function loadDashboard() {
  const seq = ++state.dashSeq;
  state.dashLoading = true;
  state.dashError = null;
  renderDash();
  const res = await api(`/api/dashboard?range=${state.dashRange}`);
  if (seq !== state.dashSeq || !state.user) return;
  state.dashLoading = false;
  if (res.ok && res.body && !Array.isArray(res.body)) {
    state.dashboard = res.body;
    state.dashError = null;
    state.expiry.data = null;
    state.chart.index = -1;
  } else {
    state.dashError = detail(res.body);
  }
  renderDash();
  if (state.dashboard && state.expiry.bucket !== "all") setExpiryBucket(state.expiry.bucket);
}

function setDashRange(days) {
  if (![7, 30, 90].includes(days) || days === state.dashRange) return;
  state.dashRange = days;
  try { localStorage.setItem("hb.dashRange", String(days)); } catch (e) { /* storage blocked */ }
  $$("[data-dash-range]").forEach(b =>
    b.setAttribute("aria-pressed", String(Number(b.dataset.dashRange) === days)));
  loadDashboard();
}

/* ---------- command palette ---------- */
function openPalette() {
  if (!state.user) return;
  state.palette.open = true;
  state.palette.seq++;
  state.palette.items = [];
  state.palette.i = -1;
  clearTimeout(state.palette.timer);
  $("#palette").classList.remove("hide");
  $("#paletteQ").value = "";
  $("#paletteQ").setAttribute("aria-activedescendant", "");
  $("#paletteResults").innerHTML = "";
  $("#paletteNote").textContent = "Type at least two characters. Results follow what your role may read.";
  $("#paletteQ").focus();
}

function closePalette() {
  const p = $("#palette");
  state.palette.open = false;
  state.palette.seq++;
  clearTimeout(state.palette.timer);
  state.palette.items = [];
  state.palette.i = -1;
  if (!p) return;
  p.classList.add("hide");
  $("#paletteQ").value = "";
  $("#paletteResults").innerHTML = "";
}

function paletteSetIndex(i) {
  const items = state.palette.items;
  if (!items.length) { state.palette.i = -1; return; }
  state.palette.i = Math.max(0, Math.min(items.length - 1, i));
  items.forEach((el, j) => {
    el.classList.toggle("on", j === state.palette.i);
    el.setAttribute("aria-selected", String(j === state.palette.i));
  });
  const active = items[state.palette.i];
  if (active) {
    if (!active.id) active.id = `palette-item-${state.palette.i}`;
    $("#paletteQ").setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  }
}

function renderPalette(body, term) {
  const groups = body && body.groups ? body.groups : [];
  const box = $("#paletteResults");
  if (!groups.length) {
    box.innerHTML = `<p class="palette-empty">No record matches “${esc(term)}” in the sections your role can read.</p>`;
    $("#paletteNote").textContent = "Nothing to open.";
    state.palette.items = [];
    state.palette.i = -1;
    return;
  }
  box.innerHTML = groups.map(g => `<div class="palette-group" role="group" aria-label="${esc(g.label)}">
    <h3>${esc(g.label)}</h3>
    ${(g.items || []).map(it => `<button class="palette-item" type="button" role="option" aria-selected="false"
      data-href="${esc(it.href)}" data-group="${esc(g.key)}" data-id="${esc(it.id)}">
      <b>${esc(it.title)}</b><span>${esc(it.subtitle || "")}</span></button>`).join("")}
  </div>`).join("");
  state.palette.items = $$(".palette-item", box);
  const count = state.palette.items.length;
  $("#paletteNote").textContent = `${plural(count, "result")} across ${plural(groups.length, "section")} · `
    + "↑ ↓ to move · Enter to open · Esc to close";
  paletteSetIndex(0);
}

async function paletteSearch(term) {
  const seq = ++state.palette.seq;
  if (term.length < 2) {
    $("#paletteResults").innerHTML = "";
    state.palette.items = [];
    state.palette.i = -1;
    $("#paletteNote").textContent = "Type at least two characters. Results follow what your role may read.";
    return;
  }
  $("#paletteNote").textContent = "Searching…";
  const res = await api(`/api/dashboard/search?q=${encodeURIComponent(term)}`);
  if (seq !== state.palette.seq || !state.palette.open) return;
  if (!res.ok) {
    $("#paletteResults").innerHTML = `<p class="palette-empty">${esc(detail(res.body))}</p>`;
    $("#paletteNote").textContent = "The search could not run.";
    state.palette.items = [];
    state.palette.i = -1;
    return;
  }
  renderPalette(res.body, term);
}

function paletteGo(btn) {
  const href = btn.dataset.href || "#/dash";
  const group = btn.dataset.group, id = btn.dataset.id;
  closePalette();
  if (location.hash !== href) location.hash = href;
  else route();
  if (!id) return;
  // Let the screen render before a record drawer opens on top of it.
  setTimeout(() => {
    if (group === "sales_orders") soDetail(id);
    else if (group === "invoices") invDetail(id);
    else if (group === "purchase_orders") poDetail(id);
    else if (group === "distributors") distForm(id);
    else if (group === "suppliers") supplierDetail(id);
    else if (group === "leads") leadDetail(id);
    else if (group === "products") productDrawer(id, "open");
  }, 80);
}

/* ---------- theme ---------- */
function applyTheme(theme) {
  const dark = theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  const b = $("#themeToggle");
  if (b) {
    b.setAttribute("aria-pressed", String(dark));
    b.textContent = dark ? "Light theme" : "Dark theme";
  }
  const d = $("#dashTheme");
  if (d) {
    d.setAttribute("aria-pressed", String(dark));
    d.textContent = dark ? "Light theme" : "Dark theme";
  }
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem("hb.theme", next); } catch (e) { /* storage blocked */ }
  applyTheme(next);
}

/* ---------- accounts ---------- */
function renderAccounts() {
  if (!can("accounts:read")) return;
  const out = state.accounts.outstanding;
  const recv = out ? out.receivables.filter(r => Number(r.outstanding) > 0) : [];
  const pay = out ? out.payables.filter(p => Number(p.outstanding) > 0) : [];
  $("#arows").innerHTML = recv.map(r => `<tr><td class="strong">${esc(r.number)}</td><td>${esc(r.date)}</td>
    <td>${esc(r.distributor || "")}</td><td class="n">${money(r.grand_total)}</td>
    <td class="n">${money(r.received)}</td><td class="n strong">${money(r.outstanding)}</td></tr>`).join("");
  empty($("#aempty"), !recv.length, out ? "Nothing is outstanding." : "Accounts could not be loaded.",
    out ? " Every issued invoice has been settled in full." : " Refresh to try again.");
  $("#payrows").innerHTML = pay.map(p => `<tr><td class="strong">${esc(p.number)}</td><td>${esc(p.supplier || "")}</td>
    <td class="n">${money(p.received_value)}</td><td class="n">${money(p.paid)}</td>
    <td class="n strong">${money(p.outstanding)}</td></tr>`).join("");
  empty($("#payempty"), !pay.length, "Nothing is payable.", " No supplier is owed for goods already received.");
  $("#recvSub").textContent = out
    ? `${money(out.receivable_total)} outstanding across ${plural(recv.length, "invoice")}.`
    : "What distributors still owe on issued invoices.";
  $("#paySub").textContent = out
    ? `${money(out.payable_total)} outstanding across ${plural(pay.length, "order")}.`
    : "What the business still owes suppliers for goods received.";

  const entries = state.accounts.entries || [];
  $("#enrows").innerHTML = entries.map(e => `<tr><td class="strong">${esc(e.number)}</td><td>${esc(e.paid_on)}</td>
    <td>${e.kind === "receipt" ? "Receipt" : "Payment"}</td><td>${esc(e.party || "")}</td>
    <td>${esc(e.invoice_number || e.purchase_order_number || "unallocated")}</td>
    <td class="n">${money(e.amount)}</td><td>${esc(e.mode)}</td></tr>`).join("");
  empty($("#enempty"), !entries.length, "No money has been recorded yet.",
    can("accounts:write") ? " Select “Record receipt” or “Record payment” to add the first one." : "");
  if (state.accounts.gst) renderGstRegister();
  if (state.accounts.tb) renderTrialBalance();
  renderAgeing();
}

function renderAgeing() {
  const age = state.accounts.ageing;
  const rows = age ? age.buckets.flatMap(b =>
    b.rows.map(r => ({...r, bucket: b.label}))) : [];
  $("#agerows").innerHTML = rows.map(r => `<tr><td class="strong">${esc(r.number)}</td>
    <td>${esc(r.date)}</td><td>${esc(r.distributor || "")}</td><td class="n">${r.days}</td>
    <td>${esc(r.bucket)}</td><td class="n strong">${money(r.outstanding)}</td></tr>`).join("");
  empty($("#ageempty"), !rows.length, age ? "Nothing is outstanding." : "Ageing could not be loaded.",
    age ? " Every issued invoice has been settled." : " Use “Rebuild ageing” to try again.");
  if (age) {
    $("#ageTot").textContent = `${money(age.total)} outstanding across ${plural(age.count, "invoice")} · `
      + age.buckets.map(b => `${b.label} ${money(b.total)}`).join(" · ")
      + ` · as at ${age.as_of}`;
  }
}

async function loadAgeing() {
  const asOf = $("#ageAsOf").value;
  const res = await api(`/api/accounts/ageing${asOf ? "?as_of=" + encodeURIComponent(asOf) : ""}`);
  if (!res.ok) return toast(res, "Ageing could not be rebuilt");
  state.accounts.ageing = res.body; renderAgeing();
}

function renderGstRegister() {
  const reg = state.accounts.gst;
  const rows = reg ? reg.b2b : [];
  $("#gstrows").innerHTML = rows.map(r => `<tr><td class="strong">${esc(r.number)}</td><td>${esc(r.date)}</td>
    <td>${esc(r.party || "")}</td><td>${esc(r.gstin || "unregistered")}</td><td>${esc(r.place_of_supply)}</td>
    <td class="n">${money(r.taxable)}</td><td class="n">${money(r.cgst)}</td><td class="n">${money(r.sgst)}</td>
    <td class="n">${money(r.igst)}</td><td class="n strong">${money(r.total)}</td></tr>`).join("");
  empty($("#gstempty"), !rows.length, "Nothing was issued in that period.",
    " Choose a wider range, or leave both dates blank for everything.");
  if (reg) {
    const t = reg.totals;
    $("#gstTot").textContent = `Taxable ${money(t.taxable)} · CGST ${money(t.cgst)} · SGST ${money(t.sgst)} · IGST ${money(t.igst)} · Total ${money(t.total)} · ${plural(reg.credit_notes.length, "credit note")} · ${plural(reg.debit_notes.length, "debit note")}`;
  }
}

function renderTrialBalance() {
  const tb = state.accounts.tb;
  $("#tbrows").innerHTML = tb ? tb.rows.map(r => `<tr><td class="strong">${esc(r.account)}</td>
    <td class="n">${Number(r.debit) ? money(r.debit) : ""}</td><td class="n">${Number(r.credit) ? money(r.credit) : ""}</td></tr>`).join("")
    + `<tr><td class="strong">Total</td><td class="n strong">${money(tb.debit_total)}</td><td class="n strong">${money(tb.credit_total)}</td></tr>` : "";
  empty($("#tbempty"), !tb || !tb.rows.length, "The trial balance is not built yet.",
    " Choose a date and select “Build trial balance”.");
  if (tb) $("#tbBal").innerHTML = tb.balanced
    ? `<span class="chip ok">Balanced</span>`
    : `<span class="chip bad">Difference ${money(Number(tb.debit_total) - Number(tb.credit_total))}</span>`;
}

async function loadGstRegister() {
  const from = $("#gstFrom").value, to = $("#gstTo").value;
  const qs = new URLSearchParams();
  if (from) qs.set("date_from", from);
  if (to) qs.set("date_to", to);
  const res = await api(`/api/accounts/gst-register${qs.toString() ? "?" + qs : ""}`);
  if (!res.ok) return toast(res, "Register could not be built");
  state.accounts.gst = res.body; renderGstRegister();
}

async function loadTrialBalance() {
  const asOf = $("#tbAsOf").value;
  const res = await api(`/api/accounts/trial-balance${asOf ? "?as_of=" + encodeURIComponent(asOf) : ""}`);
  if (!res.ok) return toast(res, "Trial balance could not be built");
  state.accounts.tb = res.body; renderTrialBalance();
}

function entryForm(kind) {
  const out = state.accounts.outstanding;
  const receipt = kind === "receipt";
  const options = receipt
    ? (out ? out.receivables.filter(r => Number(r.outstanding) > 0) : []).map(r =>
        `<option value="${r.invoice_id}">${esc(r.number)}, ${esc(r.distributor || "")}, ${money(r.outstanding)} due</option>`).join("")
    : (out ? out.payables.filter(p => Number(p.outstanding) > 0) : []).map(p =>
        `<option value="${p.purchase_order_id}">${esc(p.number)}, ${esc(p.supplier || "")}, ${money(p.outstanding)} due</option>`).join("");
  openDrawer(receipt ? "Record a receipt" : "Record a payment",
    receipt ? "Money received from a distributor, allocated to an invoice." : "Money paid to a supplier for goods received.", `
    <form id="entryForm" data-kind="${kind}" novalidate>
      <label for="e-against">${receipt ? "Against invoice" : "Against order"}</label>
      <select id="e-against" name="against"><option value="">Not allocated yet</option>${options}</select>
      <div class="row2"><div><label for="e-amount">Amount (₹)</label><input id="e-amount" name="amount" inputmode="decimal" placeholder="0.00" autocomplete="off"></div>
      <div><label for="e-date">Date</label><input id="e-date" name="paid_on" type="date" value="${isoDay(0)}"></div></div>
      <div class="row2"><div><label for="e-mode">Mode</label><select id="e-mode" name="mode">
        ${["bank", "cash", "upi", "cheque", "neft", "other"].map(m => `<option value="${m}"${m === "bank" ? " selected" : ""}>${m.toUpperCase()}</option>`).join("")}</select></div>
      <div><label for="e-ref">Reference</label><input id="e-ref" name="reference" placeholder="UTR, cheque number" autocomplete="off"></div></div>
      <label for="e-notes">Note</label><input id="e-notes" name="notes" placeholder="Optional" autocomplete="off">
      <div class="note">An entry is never edited or deleted. If it is wrong, record the opposite one and note why.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save ${receipt ? "receipt" : "payment"}</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

async function saveEntry(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form); err.textContent = "";
  const f = form.elements, kind = form.dataset.kind, receipt = kind === "receipt";
  if (!(Number(f.amount.value) > 0)) { err.textContent = "Enter an amount greater than zero."; return; }
  const body = {kind, amount: f.amount.value, paid_on: f.paid_on.value, mode: f.mode.value,
                reference: f.reference.value.trim() || null, notes: f.notes.value.trim() || null};
  if (f.against.value) body[receipt ? "invoice_id" : "purchase_order_id"] = Number(f.against.value);
  btn.disabled = true;
  const res = await api("/api/accounts/payments", {method: "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? (receipt ? "Receipt recorded" : "Payment recorded") : "Not recorded");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

function renderLost() {
  if (!$("#lostrows")) return;
  const q = ($("#lostq")?.value || "").trim().toLowerCase();
  const list = state.leads.filter(l => l.status === "lost" &&
    (!q || [l.name, l.company, l.lead_no, l.owner, l.closed_reason].some(x => (x || "").toLowerCase().includes(q))));
  $("#lostrows").innerHTML = list.map(l => `<tr class="go" data-ld="${l.id}"><td><button class="rowbtn" data-act="open-lead" data-id="${l.id}" type="button">${esc(l.name)}</button><small>${esc(l.lead_no)}</small></td>
    <td>${esc(l.company || "–")}<small>${esc(l.phone || l.email || "")}</small></td><td>${esc(l.closed_reason || "–")}</td>
    <td>${esc(l.owner)}</td><td>${esc(SRC[l.source] || l.source)}</td><td>${esc(fmtDay(l.last_activity_at))}</td></tr>`).join("");
  empty($("#lostempty"), !list.length, "No lost leads match this search.", "Leads closed as lost appear here with their reason and owner.");
}
function renderFollowups() {
  if (!$("#furows")) return;
  const q = ($("#fuq")?.value || "").trim().toLowerCase();
  const f = state.fuFilter;
  const list = state.leads.filter(l => {
    if (isClosed(l)) return false;
    if (f === "overdue" && l.follow_up_state !== "overdue") return false;
    if (f === "today" && l.follow_up_state !== "today") return false;
    if (f === "upcoming" && !["today", "upcoming"].includes(l.follow_up_state)) return false;
    return !q || [l.name, l.company, l.lead_no, l.owner].some(x => (x || "").toLowerCase().includes(q));
  }).sort((a, b) => String(a.next_follow_up || "").localeCompare(String(b.next_follow_up || "")));
  $("#furows").innerHTML = list.map(l => `<tr class="go" data-ld="${l.id}"><td><button class="rowbtn" data-act="open-lead" data-id="${l.id}" type="button">${esc(l.name)}</button><small>${esc(l.lead_no)}</small></td>
    <td>${esc(l.company || "–")}<small>${esc(l.phone || l.email || "")}</small></td><td>${esc(l.owner)}</td>
    <td>${esc(l.last_remark || l.closed_reason || "–")}</td><td>${followCell(l)}</td>
    <td><button class="btn ghost sm" type="button" data-act="lead-panel" data-id="${l.id}" data-panel="activity">Log remark</button></td></tr>`).join("");
  empty($("#fuempty"), !list.length, "Nothing in this follow-up window.", "Follow-ups appear here once a lead has a next date.");
}
function renderCustomers() {
  if (!$("#curows")) return;
  const q = ($("#cuq")?.value || "").trim().toLowerCase();
  const list = state.dists.filter(d => !q || [d.code, d.name, d.gstin, d.territory].some(x => (x || "").toLowerCase().includes(q)));
  $("#curows").innerHTML = list.map(d => `<tr><td class="strong">${esc(d.code)}</td><td>${esc(d.name)}</td>
    <td>${esc(d.territory)}</td><td>${esc(d.gstin || "–")}</td><td class="n">${money(d.credit_limit)}</td>
    <td class="n">${money(d.exposure)}</td><td>${distChip(d.status)}</td>
    <td class="rowacts"><button class="btn ghost sm" type="button" data-act="edit-dist" data-id="${d.id}">Open</button>
      <button class="btn ghost sm" type="button" data-act="new-so-dist" data-id="${d.id}">New order</button></td></tr>`).join("");
  empty($("#cuempty"), !list.length, "No customer matches this search.", "Customers and distributors are one master; records are never deleted.");
}
function renderHr() {
  if (!$("#hrrows")) return;
  // Staff without hr:read get their own attendance, not the company directory.
  const wholeTeam = can("hr:read");
  $("#hrStats").classList.toggle("hide", !wholeTeam);
  $("#hrDirectory").classList.toggle("hide", !wholeTeam);
  ["hr-employees", "hr-leave", "hr-od"].forEach(a =>
    $$(`#v-hr [data-act="${a}"]`).forEach(b => b.classList.toggle("hide", !wholeTeam)));
  // Payroll is a closed book: the API needs hr:payroll_prepare to even list a period.
  $$('#v-hr [data-act="hr-payroll"]').forEach(b =>
    b.classList.toggle("hide", !(wholeTeam && can("hr:payroll_prepare"))));
  // Shift policy is an HR/administrator setting, not something every reader edits.
  $$('#v-hr [data-act="hr-shifts"]').forEach(b =>
    b.classList.toggle("hide", !(wholeTeam && can("hr:write"))));
  if (!wholeTeam) return;
  const d = state.hr.dashboard || {};
  $("#hrStats").innerHTML = [
    ["Employees", d.total_employees ?? state.hr.employees.length],
    ["Active", d.active_employees ?? "–"],
    ["Present today", d.present_today ?? "–"],
    ["Absent / leave / OD", d.absent_today != null ? `${d.absent_today} / ${d.on_leave_today} / ${d.on_od_today}` : "–"],
    ["Pending HR approvals", d.pending_approvals ?? "–"],
    ["Salary payable", d.salary_payable != null ? "₹ " + money(d.salary_payable) : "–"]
  ].map(([k, v]) => `<div class="stat"><span class="k">${esc(k)}</span><span class="v">${esc(String(v))}</span></div>`).join("");
  $("#hrrows").innerHTML = state.hr.employees.map(e => `<tr><td class="strong">${esc(e.full_name)}<small>${esc(e.code)}</small></td>
    <td>${esc(e.department || "–")}</td><td>${esc(e.designation || "–")}</td>
    <td><span class="chip ${e.status === "active" ? "ok" : "off"}">${esc(e.status)}</span></td></tr>`).join("");
  empty($("#hrempty"), !state.hr.employees.length, "No employees yet.", "Add the first employee from the employee master.");
}
async function openHr() {
  const [d, e] = await Promise.all([api("/api/hr/dashboard"), api("/api/hr/employees")]);
  state.hr.dashboard = d.ok ? d.body : null;
  state.hr.employees = e.ok ? e.body : [];
  if (state.view === "hr") { renderHead(); renderHr(); }
}
async function hrEmployees() {
  const [e, b, o, s] = await Promise.all([api("/api/hr/employees"), api("/api/hr/branches"),
                                         api("/api/hr/offices"), api("/api/hr/shifts")]);
  const emps = e.ok ? e.body : [];
  state.hr.employees = emps;
  const rows = emps.map(x => `<tr><td class="strong">${esc(x.code)}</td><td>${esc(x.full_name)}</td><td>${esc(x.department || "–")}</td>
    <td>${esc(x.designation || "–")}</td><td>${esc(x.status)}</td>
    <td>${can("hr:write") ? `<button class="btn ghost sm" type="button" data-act="hr-edit-emp" data-id="${x.id}">Edit</button>` : ""}</td></tr>`).join("");
  openDrawer("Employee master", `${emps.length} employee record(s). Deactivate, never delete.`, `
    ${can("hr:write") ? `<div class="actions"><button class="btn" type="button" data-act="hr-new-emp">New employee</button></div>` : ""}
    <div class="tw"><table><thead><tr><th>Code</th><th>Name</th><th>Department</th><th>Designation</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`, true);
}
const HR_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const hrTime = v => (v || "").slice(0, 5);
const hrOffs = offs => (offs || []).map(d => HR_WEEKDAYS[d]).join(", ") || "None";
async function hrShifts() {
  const s = await api("/api/hr/shifts");
  const rows = s.ok ? s.body : [];
  openDrawer("Shift settings", "Office timings drive late arrival and early departure. Existing attendance keeps the minutes it was recorded with.", `
    ${can("hr:write") ? `<div class="actions" style="margin-top:0"><button class="btn" type="button" data-act="hr-new-shift">New shift</button></div>` : ""}
    <div class="tw"><table><thead><tr><th>Shift</th><th>Office hours</th><th class="n">Grace (min)</th><th>Weekly offs</th><th>Status</th><th></th></tr></thead><tbody>
      ${rows.map(x => `<tr><td class="strong">${esc(x.name)}</td>
        <td>${esc(hrTime(x.start_time))} – ${esc(hrTime(x.end_time))}</td>
        <td class="n">${x.grace_minutes}</td><td>${esc(hrOffs(x.weekly_offs))}</td>
        <td><span class="chip ${x.status === "active" ? "ok" : "off"}">${esc(x.status)}</span></td>
        <td>${can("hr:write") ? `<button class="btn ghost sm" type="button" data-act="hr-edit-shift" data-id="${x.id}">Edit</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="6" class="empty-row">No shifts configured.</td></tr>'}
    </tbody></table></div>`, true);
}
async function hrShiftForm(id) {
  let x;
  if (id) {
    const s = await api("/api/hr/shifts");
    x = (s.ok ? s.body : []).find(v => v.id === Number(id));
    if (!x) { toast(s, "Shift not loaded"); return; }
  } else {
    x = {id: "", name: "", start_time: "09:30", end_time: "18:30",
         grace_minutes: 10, full_day_hours: 8, half_day_hours: 4,
         weekly_offs: [5, 6], status: "active"};
  }
  const offs = new Set(x.weekly_offs || []);
  openDrawer(x.id ? `Edit ${x.name}` : "New shift",
    "Late arrival is measured from the start time plus grace. Early departure is measured against the end time.", `
    <form id="hrShiftForm" data-id="${x.id || ""}" novalidate>
      <label>Shift name</label><input name="name" value="${esc(x.name)}" autocomplete="off">
      <div class="row2"><div><label>Start time</label><input name="start_time" type="time" value="${esc(hrTime(x.start_time))}" step="60"></div>
      <div><label>End time</label><input name="end_time" type="time" value="${esc(hrTime(x.end_time))}" step="60"></div></div>
      <div class="row2"><div><label>Grace period (minutes)</label><input name="grace_minutes" type="number" min="0" max="120" value="${x.grace_minutes}"></div>
      <div><label>Status</label><select name="status"><option value="active"${x.status === "active" ? " selected" : ""}>Active</option><option value="inactive"${x.status !== "active" ? " selected" : ""}>Inactive</option></select></div></div>
      <div class="row2"><div><label>Full day hours</label><input name="full_day_hours" type="number" min="0.25" max="24" step="0.25" value="${x.full_day_hours}"></div>
      <div><label>Half day hours</label><input name="half_day_hours" type="number" min="0.25" max="24" step="0.25" value="${x.half_day_hours}"></div></div>
      <label>Weekly offs</label>
      <div class="offs">${HR_WEEKDAYS.map((name, day) => `<label class="chk"><input type="checkbox" name="off" value="${day}"${offs.has(day) ? " checked" : ""} style="width:auto;margin-right:6px"> ${name}</label>`).join("")}</div>
      <div class="note">Changing a timing does not rewrite minutes already recorded. Future check-ins use the new policy.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save shift</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}
async function saveHrShift(form) {
  const f = form.elements, err = $(".err", form);
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  const offs = [...form.querySelectorAll('input[name="off"]:checked')].map(x => Number(x.value));
  err.textContent = "";
  const body = {name: f.name.value.trim(), start_time: f.start_time.value, end_time: f.end_time.value,
                grace_minutes: Number(f.grace_minutes.value),
                full_day_hours: f.full_day_hours.value, half_day_hours: f.half_day_hours.value,
                weekly_offs: offs, status: f.status.value};
  if (!body.name || body.name.length < 2) { err.textContent = "Enter a shift name."; return; }
  if (!body.start_time || !body.end_time) { err.textContent = "Choose both office times."; return; }
  if (body.start_time === body.end_time) { err.textContent = "Start and end times cannot be the same."; return; }
  if (!(body.grace_minutes >= 0)) { err.textContent = "Enter the grace period in minutes."; return; }
  if (!(Number(body.full_day_hours) > 0) || !(Number(body.half_day_hours) > 0)) {
    err.textContent = "Full-day and half-day hours must be greater than zero."; return;
  }
  const res = await api(id ? `/api/hr/shifts/${id}` : "/api/hr/shifts",
                        {method: id ? "PATCH" : "POST", body});
  toast(res, res.ok ? (id ? "Shift updated" : "Shift created") : "Shift not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrShifts();
}
async function hrAttendance() {
  const [a, o] = await Promise.all([api(`/api/hr/attendance?from_date=${isoDay(0)}&to_date=${isoDay(0)}`),
    can("hr:read") ? api("/api/hr/offices") : Promise.resolve({ok: false, body: []})]);
  const rows = a.ok ? a.body : [];
  const offices = o.ok ? o.body : [];
  openDrawer("Attendance — today", "GPS is requested only for check-in/out and never tracked in the background.", `
    <div class="actions">
      ${can("hr:attendance_self") ? `<button class="btn" type="button" data-act="hr-checkin">Check in</button><button class="btn ghost" type="button" data-act="hr-checkout">Check out</button>` : ""}
      <button class="btn ghost" type="button" data-act="hr-refresh-att">Refresh</button></div>
    <div class="tw"><table><thead><tr><th>Employee</th><th>Status</th><th>Check-in</th><th>Check-out</th><th>Location</th><th>Late</th></tr></thead><tbody>
      ${rows.map(x => `<tr><td>${esc(x.employee)}<small>${esc(x.employee_code)}</small></td><td>${esc(x.status)}</td><td>${esc(fmtStamp(x.check_in))}</td><td>${esc(fmtStamp(x.check_out))}</td><td>${esc(x.geofence_result)}</td><td class="n">${x.late_minutes}</td></tr>`).join("") || '<tr><td colspan="6" class="empty-row">No attendance recorded today.</td></tr>'}
    </tbody></table></div>
    ${can("hr:attendance_manage") ? `<form id="hrManualForm" novalidate><h3>Manual attendance</h3>
      <div class="row2"><div><label>Employee</label><select name="employee_id">${state.hr.employees.map(e => `<option value="${e.id}">${esc(e.full_name)} (${esc(e.code)})</option>`).join("")}</select></div>
      <div><label>Date</label><input name="date" type="date" value="${isoDay(0)}"></div></div>
      <label>Status</label><select name="status"><option value="present">Present</option><option value="absent">Absent</option><option value="half_day">Half day</option><option value="paid_leave">Paid leave</option><option value="unpaid_leave">Unpaid leave</option><option value="od">On duty</option><option value="late">Late</option><option value="early_departure">Early departure</option></select>
      <label>Remarks (required)</label><input name="remarks" autocomplete="off">
      <div class="note">A manual entry is audited with your name, the old value and the new value.</div>
      <div class="err" role="alert"></div><div class="actions"><button class="btn" type="submit">Save manual attendance</button></div></form>` : ""}
    ${offices.length ? `<div class="note">Configured offices: ${offices.length}. Geofence validation runs on the server.</div>` : ""}`, true);
}
async function hrCheckIn() {
  const body = {source: "gps"};
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(async pos => {
      body.latitude = pos.coords.latitude; body.longitude = pos.coords.longitude;
      const res = await api("/api/hr/attendance/check-in", {method: "POST", body});
      toast(res, res.ok ? "Checked in" : "Check-in not recorded");
      if (res.ok) hrAttendance();
    }, async () => {
      const res = await api("/api/hr/attendance/check-in", {method: "POST", body: {source: "web"}});
      toast(res, res.ok ? "Checked in (location unavailable)" : "Check-in not recorded");
      if (res.ok) hrAttendance();
    }, {timeout: 10000});
  } else {
    const res = await api("/api/hr/attendance/check-in", {method: "POST", body: {source: "web"}});
    toast(res, res.ok ? "Checked in" : "Check-in not recorded");
    if (res.ok) hrAttendance();
  }
}
async function saveManualAttendance(form) {
  const f = form.elements, err = $(".err", form), body = {employee_id: Number(f.employee_id.value), date: f.date.value, status: f.status.value, remarks: f.remarks.value.trim()};
  err.textContent = "";
  if (body.remarks.length < 3) { err.textContent = "Give a reason of at least three characters."; return; }
  const res = await api("/api/hr/attendance/manual", {method: "POST", body});
  toast(res, res.ok ? "Attendance saved" : "Attendance not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrAttendance();
}
async function hrLeave() {
  const [t, b, a] = await Promise.all([api("/api/hr/leave/types"), api("/api/hr/leave/balances"), api("/api/hr/leave/applications")]);
  const types = t.ok ? t.body : [], apps = a.ok ? a.body : [];
  const bals = b.ok ? b.body.balances : [];
  openDrawer("Leave", "Approved leave updates balances, attendance and payroll.", `
    <h3>Balances</h3><div class="tw"><table><thead><tr><th>Type</th><th class="n">Entitled</th><th class="n">Used</th><th class="n">Pending</th><th class="n">Available</th></tr></thead><tbody>
      ${bals.map(x => `<tr><td>${esc(x.name)}</td><td class="n">${qty(x.entitled)}</td><td class="n">${qty(x.used)}</td><td class="n">${qty(x.pending)}</td><td class="n">${qty(x.available)}</td></tr>`).join("") || '<tr><td colspan="5" class="empty-row">No leave types.</td></tr>'}</tbody></table></div>
    <form id="hrLeaveForm" novalidate><h3>Apply for leave</h3>
      <div class="row2"><div><label>Leave type</label><select name="leave_type_id">${types.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></div>
      <div><label>Reason</label><input name="reason" autocomplete="off"></div></div>
      <div class="row2"><div><label>From</label><input name="date_from" type="date" value="${isoDay(1)}"></div><div><label>To</label><input name="date_to" type="date" value="${isoDay(1)}"></div></div>
      <div class="err" role="alert"></div><div class="actions"><button class="btn" type="submit">Submit application</button></div></form>
    <h3>Applications</h3><div class="tw"><table><thead><tr><th>Employee</th><th>Type</th><th>Dates</th><th class="n">Days</th><th>Status</th><th>Remarks</th></tr></thead><tbody>
      ${apps.map(x => `<tr><td>${esc(x.employee)}</td><td>${esc(x.leave_type)}</td><td>${esc(fmtDate(x.date_from))} – ${esc(fmtDate(x.date_to))}</td><td class="n">${qty(x.days)}</td><td>${esc(x.status)}</td><td>${esc(x.remarks || "–")}</td></tr>`).join("" ) || '<tr><td colspan="6" class="empty-row">No applications.</td></tr>'}</tbody></table></div>`, true);
}
async function saveHrLeave(form) {
  const f = form.elements, err = $(".err", form), body = {leave_type_id: Number(f.leave_type_id.value), date_from: f.date_from.value, date_to: f.date_to.value, reason: f.reason.value.trim()};
  err.textContent = "";
  if (!body.date_from || !body.date_to) { err.textContent = "Choose both dates."; return; }
  if (body.reason.length < 3) { err.textContent = "Give a reason."; return; }
  const res = await api("/api/hr/leave/applications", {method: "POST", body});
  toast(res, res.ok ? "Leave submitted for approval" : "Leave not submitted");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrLeave();
}
async function hrOd() {
  const [a, e] = await Promise.all([api("/api/hr/od"), api("/api/hr/employees")]);
  const rows = a.ok ? a.body : [], emps = e.ok ? e.body : [];
  openDrawer("On duty (OD)", "Approved OD is reflected in attendance and payroll.", `
    <form id="hrOdForm" novalidate><h3>New OD request</h3>
      <div class="row2"><div><label>Employee</label><select name="employee_id">${emps.map(x => `<option value="${x.id}">${esc(x.full_name)} (${esc(x.code)})</option>`).join("")}</select></div>
      <div><label>Date</label><input name="date" type="date" value="${isoDay(0)}"></div></div>
      <div class="row2"><div><label>Visit type</label><input name="visit_type" placeholder="Customer visit / Field work" autocomplete="off"></div>
      <div><label>Destination</label><input name="destination" autocomplete="off"></div></div>
      <label>Purpose</label><input name="purpose" autocomplete="off">
      <div class="err" role="alert"></div><div class="actions"><button class="btn" type="submit">Submit OD request</button></div></form>
    <h3>Requests</h3><div class="tw"><table><thead><tr><th>Employee</th><th>Date</th><th>Visit</th><th>Purpose</th><th>Status</th><th>Remarks</th></tr></thead><tbody>
      ${rows.map(x => `<tr><td>${esc(x.employee)}</td><td>${esc(fmtDate(x.date))}</td><td>${esc(x.visit_type)}</td><td>${esc(x.purpose)}</td><td>${esc(x.status)}</td><td>${esc(x.decision_remarks || "–")}</td></tr>`).join("") || '<tr><td colspan="6" class="empty-row">No OD requests.</td></tr>'}</tbody></table></div>`, true);
}
async function saveHrOd(form) {
  const f = form.elements, err = $(".err", form), body = {employee_id: Number(f.employee_id.value), date: f.date.value, visit_type: f.visit_type.value.trim(), purpose: f.purpose.value.trim(), destination: f.destination.value.trim() || null};
  err.textContent = "";
  if (!body.visit_type || !body.purpose) { err.textContent = "Visit type and purpose are required."; return; }
  const res = await api("/api/hr/od", {method: "POST", body});
  toast(res, res.ok ? "OD submitted for approval" : "OD not submitted");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrOd();
}
async function hrPayroll() {
  const p = await api("/api/hr/payroll/periods");
  const rows = p.ok ? p.body : [];
  openDrawer("Payroll", "Draft → Under review → Approved → Processed → Paid. A period cannot be paid twice.", `
    <form id="hrPeriodForm" novalidate><h3>Open a payroll period</h3>
      <div class="row2"><div><label>Year</label><input name="year" inputmode="numeric" value="${new Date().getFullYear()}"></div>
      <div><label>Month</label><input name="month" inputmode="numeric" value="${new Date().getMonth() + 1}"></div></div>
      <div class="err" role="alert"></div><div class="actions"><button class="btn" type="submit">Create period</button></div></form>
    <div class="tw"><table><thead><tr><th>Period</th><th>Status</th><th class="n">Entries</th><th class="n">Net (₹)</th><th></th></tr></thead><tbody>
      ${rows.map(x => `<tr><td class="strong">${x.year}-${String(x.month).padStart(2, "0")}</td><td>${esc(x.status)}</td><td class="n">${x.entries}</td><td class="n">${money(x.net)}</td>
        <td class="rowacts">${can("hr:payroll_prepare") && ["draft", "under_review"].includes(x.status) ? `<button class="btn ghost sm" type="button" data-act="pay-prepare" data-id="${x.id}">${x.status === "draft" ? "Prepare" : "Recalculate"}</button>` : ""}
        ${can("hr:payroll_prepare") && x.status === "under_review" ? `<button class="btn ghost sm" type="button" data-act="pay-submit" data-id="${x.id}">Submit for approval</button>` : ""}
        ${can("hr:payroll_approve") && x.status === "approved" ? `<button class="btn ghost sm" type="button" data-act="pay-process" data-id="${x.id}">Process</button>` : ""}
        ${can("hr:payroll_approve") && x.status === "processed" ? `<button class="btn ghost sm" type="button" data-act="pay-paid" data-id="${x.id}">Mark paid</button>` : ""}
        <button class="btn ghost sm" type="button" data-act="pay-open" data-id="${x.id}">Open</button></td></tr>`).join("") || '<tr><td colspan="5" class="empty-row">No payroll periods.</td></tr>'}</tbody></table></div>`, true);
}
async function hrPayrollOpen(id) {
  const r = await api(`/api/hr/payroll/periods/${id}`);
  if (!r.ok) { toast(r, "Payroll not loaded"); return; }
  const p = r.body;
  openDrawer(`Payroll ${p.year}-${String(p.month).padStart(2, "0")}`, `Status: ${p.status}.`, `
    <div class="tw"><table><thead><tr><th>Employee</th><th>Department</th><th class="n">Payable days</th><th class="n">LOP</th><th class="n">Gross (₹)</th><th class="n">Deductions (₹)</th><th class="n">Net (₹)</th><th></th></tr></thead><tbody>
      ${p.entries.map(e => `<tr><td>${esc(e.employee)}<small>${esc(e.employee_code)}</small></td><td>${esc(e.department || "–")}</td><td class="n">${qty(e.payable_days)}</td><td class="n">${qty(e.lop_days)}</td><td class="n">${money(e.gross)}</td><td class="n">${money(e.deductions)}</td><td class="n strong">${money(e.net)}</td>
        <td>${can("hr:confidential") ? `<a class="link-btn" href="/api/hr/payroll/entries/${e.id}/slip" download>Slip</a>` : ""}</td></tr>`).join("")}</tbody></table></div>
    ${can("hr:reports") && can("report:export") ? `<a class="btn ghost" href="/api/reports/hr_payroll/export?format=xlsx" download>Download salary register (Excel)</a>` : ""}`, true);
}
async function saveHrPeriod(form) {
  const f = form.elements, err = $(".err", form);
  err.textContent = "";
  const res = await api("/api/hr/payroll/periods", {method: "POST", body: {year: Number(f.year.value), month: Number(f.month.value)}});
  toast(res, res.ok ? "Payroll period created" : "Period not created");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrPayroll();
}
async function hrPayrollAction(act, id) {
  const map = {prepare: "prepare", submit: "submit", process: "process", paid: "pay"};
  const res = await api(`/api/hr/payroll/periods/${id}/${map[act]}`, {method: "POST", body: {}});
  toast(res, res.ok ? "Payroll updated" : "Payroll not updated");
  if (!res.ok) return;
  await hrPayroll();
}
function renderSettings() {
  if (!$("#setEmprows")) return;
  $("#setEmprows").innerHTML = state.employees.slice(0, 50).map(e => `<tr><td class="strong">${esc(e.code)}</td><td>${esc(e.full_name)}</td>
    <td>${esc(e.department || "–")}</td><td>${esc(e.designation || "–")}</td><td><span class="chip ${e.status === "active" ? "ok" : "off"}">${esc(e.status)}</span></td></tr>`).join("");
}

function renderProducts() {
  const q = $("#pq").value.trim().toLowerCase();
  const list = state.products.filter(x => !q || [x.sku, x.name, x.hsn || ""].some(t => t.toLowerCase().includes(q)));
  $("#prows").innerHTML = list.map(x => `<tr><td>${x.hsn ? esc(x.hsn) : '<span class="chip warn">Missing HSN</span>'}</td>
    <td class="strong">${esc(x.sku)}</td><td>${esc(x.name)}</td><td>${esc(x.pack_size)}</td>
    <td class="n">${money(x.mrp)}</td><td><span class="chip ${x.status === "active" ? "ok" : "off"}">${esc(x.status)}</span></td>
    <td class="rowacts"><button class="btn ghost sm" type="button" data-act="open-product" data-id="${x.id}">Open</button>
      <button class="btn ghost sm" type="button" data-act="edit-product" data-id="${x.id}">Edit</button>
      <button class="btn ghost sm" type="button" data-act="save-product" data-id="${x.id}">Save</button></td></tr>`).join("");
  empty($("#pempty"), !list.length, state.products.length ? "No product matches that search." : "No products yet.",
    state.products.length ? "" : (can("product:write") ? " Select “New product” to add the first one." : ""));
}

function productDrawer(id, mode) {
  const x = id ? state.products.find(p => p.id === Number(id)) : null;
  if (id && !x) return;
  const edit = mode !== "open";
  const val = k => (x && x[k] != null ? esc(x[k]) : "");
  openDrawer(x ? `${edit ? "Edit" : "Open"} ${x.sku}` : "New product",
    x ? "Every change is recorded with its old and new value."
      : "The HSN is required for GST: the rate master is keyed by it.", `
    <form id="prodForm" data-id="${x ? x.id : ""}" novalidate>
      <div class="row2"><div><label for="f-hsn">HSN code</label><input id="f-hsn" name="hsn" value="${val("hsn")}" placeholder="3004" inputmode="numeric" maxlength="8" autocomplete="off"${edit ? "" : " readonly"}></div>
      <div><label for="f-sku">SKU</label><input id="f-sku" name="sku" value="${val("sku")}" placeholder="DEMO-HN-001" autocomplete="off"${edit ? " readonly" : ""}></div></div>
      <label for="f-name">Product name</label><input id="f-name" name="name" value="${val("name")}" placeholder="Herbal Product Alpha" autocomplete="off"${edit ? "" : " readonly"}>
      <div class="row2"><div><label for="f-pack">Pack size</label><input id="f-pack" name="pack" value="${val("pack_size")}" placeholder="100 g" autocomplete="off"${edit ? "" : " readonly"}></div>
      <div><label for="f-mrp">MRP (₹)</label><input id="f-mrp" name="mrp" value="${val("mrp")}" inputmode="decimal" placeholder="199.00" autocomplete="off"${edit ? "" : " readonly"}></div></div>
      ${x ? `<label for="f-status">Status</label><select id="f-status" name="status"${edit ? "" : " disabled"}><option value="active"${x.status === "active" ? " selected" : ""}>Active</option><option value="discontinued"${x.status === "discontinued" ? " selected" : ""}>Discontinued</option></select>` : ""}
      <div class="note">The HSN is stored on the product and copied onto every invoice line. GST is looked up from the rate master, never assumed.</div>
      <div class="err" role="alert"></div>
      <div class="actions">${edit ? `<button class="btn" type="submit">${x ? "Save product" : "Create product"}</button>` : ""}<button class="btn ghost" type="button" data-act="close">${edit ? "Cancel" : "Close"}</button></div>
    </form>`, true);
}
function productForm(id) { productDrawer(id, id ? "edit" : "new"); }

function fillWarehouseSelect() {
  const sel = $("#swh"), keep = sel.value;
  sel.innerHTML = `<option value="">All warehouses</option>` + state.warehouses.map(w => `<option value="${w.id}">${esc(w.name)}</option>`).join("");
  sel.value = state.warehouses.some(w => String(w.id) === keep) ? keep : "";
}
function renderStock() {
  fillWarehouseSelect();
  const q = $("#sq").value.trim().toLowerCase(), wh = $("#swh").value, hide = $("#sin").checked;
  const list = state.batches.filter(b => (!hide || Number(b.on_hand) > 0) && (!wh || String(b.warehouse_id) === wh) &&
    (!q || [b.sku, b.product_name, b.batch_no].some(t => t.toLowerCase().includes(q))));
  $("#srows").innerHTML = list.map(b => `<tr><td><span class="strong">${esc(b.product_name)}</span><small>${esc(b.sku)}, ${esc(b.pack_size)}</small></td>
    <td>${esc(b.batch_no)}</td><td>${esc(b.warehouse)}</td><td>${shelf(b.expiry)}</td><td>${esc(b.owner)}</td>
    <td class="n strong">${esc(qty(b.on_hand))}</td></tr>`).join("");
  empty($("#sempty"), !list.length, state.batches.length ? "No batch matches these filters." : "No stock has been received yet.",
    state.batches.length ? "" : " Stock appears here once a purchase order is received.");
}

/* ---------- print and verification ---------- */
async function printDocument(kind, documentId, copy = "ORIGINAL") {
  let res;
  try {
    // The copy is a query parameter on the print route, not a JSON field: sent
    // in the body it was silently dropped and every copy came out ORIGINAL.
    res = await fetch(`/api/print/${kind}/${documentId}?copy=${encodeURIComponent(copy)}`, {
      method: "POST",
      credentials: "same-origin"
    });
  } catch (e) {
    toast({ok: false, status: 0, body: {detail: "Cannot reach the server. Check the connection and try again."}}, "Print error");
    return;
  }
  if (res.status === 401) { leave("Your session has ended. Sign in again."); return; }
  if (!res.ok) {
    let body = null;
    try { body = await res.json(); } catch (e) { /* not JSON */ }
    toast({ok: false, status: res.status, body}, "Print error");
    return;
  }

  const digest = res.headers.get("X-Document-SHA256");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60000);

  if (digest) {
    toast({ok: true, status: 200, body: {detail: "Printed and logged. The code below verifies this file."}}, "Print");
    // Show where the code is: printing from the list opens the invoice so its
    // verification panel and QR are visible, not hidden on another screen.
    if (kind === "invoice" && !$("#verifyState")) invDetail(documentId);
    else await paintVerification(digest);
  }
}

/* The verification panel lives in the invoice drawer. It shows the QR of the
   last print (a real symbol from /api/print/qr, not a drawing) and lets anyone
   type the 16-character code it displays. Both read the same endpoint, so a
   symbol and a typed code always agree. */
async function loadPrintPanel(kind, id) {
  if (!$("#verifyState")) return;
  const img = $("#qrImg");
  const res = await api(`/api/print/log/${kind}/${id}`);
  const latest = Array.isArray(res.body) ? res.body[0] : null;
  if (!res.ok || !latest) {
    if (img) { img.removeAttribute("src"); img.classList.add("hide"); }
    $("#verifyState").innerHTML = `<span class="chip off">Not printed</span> No print has been made yet. Printing records a hash of the exact file served, and that is what this panel checks.`;
    $("#verifyDoc").textContent = "–";
    $("#verifyBy").textContent = "–";
    $("#verifyCode").textContent = "–";
    $("#verifyHash").textContent = "–";
    return;
  }
  await paintVerification(latest.print_code || latest.sha256);
}

async function paintVerification(code) {
  if (!$("#verifyState")) return null;
  const img = $("#qrImg");
  const res = await api(`/api/print/verify/${encodeURIComponent(code)}`);
  const body = res.body || {};
  // Only a code the log vouches for has a symbol to show: asking for the QR of
  // an unknown hash is a 404, which would leave a broken image beside the
  // "not valid" message.
  if (img) {
    if (body.valid) {
      // The symbol always encodes the code printed on the page, so the QR on
      // screen and the QR on paper resolve to the same print-log row.
      img.src = `/api/print/qr/${encodeURIComponent(body.print_code || body.sha256 || code)}`;
      img.classList.remove("hide");
    } else {
      img.removeAttribute("src");
      img.classList.add("hide");
    }
  }
  const state = $("#verifyState");
  if (body.valid) {
    state.innerHTML = `<span class="chip ok">Valid</span> This code matches the print log, so the file served has not been altered.`;
  } else {
    state.innerHTML = `<span class="chip bad">Not valid</span> ${esc(body.reason || body.detail || "This code does not match any printed document.")}`;
  }
  $("#verifyDoc").textContent = body.valid ? `${body.document_type.replace("_", " ")} ${body.document_number} (${body.copy_designation})` : "–";
  $("#verifyBy").textContent = body.valid ? `${body.printed_by}, ${fmtStamp(body.printed_at)}` : "–";
  // The print code is exactly what the QR encodes and what the PDF prints, so
  // scanning, typing and checking the paper all name the same print.
  $("#verifyCode").textContent = body.valid ? (body.print_code || "–") : "–";
  $("#verifyHash").textContent = body.valid ? (body.sha256 || "–") : "–";
  return body;
}

async function submitVerification(form) {
  const err = $(".err", form), input = form.elements.code, code = (input.value || "").trim();
  err.textContent = "";
  const looksRight = /^PRT-\d{1,9}$/i.test(code) || (code.length >= 16 && /^[0-9a-f]+$/i.test(code));
  if (!looksRight) { err.textContent = "Enter the code printed on the page (for example PRT-000123), or its 16-character hash."; return; }
  const body = await paintVerification(code);
  if (!body || !body.valid) err.textContent = "Not a code this system printed.";
}

function renderLedger() {
  const rows = state.movements || [];
  const sel = $("#ltype"), keep = sel.value;
  sel.innerHTML = `<option value="">All movements</option>` + [...new Set(rows.map(m => m.movement_type))].sort()
    .map(t => `<option value="${esc(t)}">${esc((MOVE[t] || [t])[0])}</option>`).join("");
  sel.value = rows.some(m => m.movement_type === keep) ? keep : "";
  const q = $("#lq").value.trim().toLowerCase(), ty = sel.value;
  const list = rows.filter(m => (!ty || m.movement_type === ty) &&
    (!q || [m.sku, m.product_name, m.batch_no, m.ref_label].some(t => t.toLowerCase().includes(q))));
  $("#lnote").textContent = rows.length >= 200 ? "Showing the latest 200 movements" : "";
  $("#lrows").innerHTML = list.map(m => {
    const mv = MOVE[m.movement_type] || [m.movement_type, "off"], d = Number(m.qty_delta);
    return `<tr><td>${esc(fmtStamp(m.created_at))}</td><td><span class="chip ${mv[1]}">${esc(mv[0])}</span></td>
      <td><span class="strong">${esc(m.product_name)}</span><small>${esc(m.sku)}</small></td><td>${esc(m.batch_no)}</td><td>${esc(m.warehouse)}</td>
      <td>${esc(m.ref_label)}</td><td>${esc(m.actor)}</td><td class="n ${d >= 0 ? "qty-in" : "qty-out"}">${d >= 0 ? "+" : "−"}${esc(qty(Math.abs(d)))}</td></tr>`;
  }).join("");
  empty($("#lempty"), state.movements !== null && !list.length, rows.length ? "No movement matches these filters." : "The ledger is empty.",
    rows.length ? "" : " Every stock change is recorded here, with who made it and why.");
}

function renderWarehouses() {
  const rows = state.warehouses.map(w => {
    const bs = state.batches.filter(b => b.warehouse_id === w.id && Number(b.on_hand) > 0);
    return `<tr><td class="strong">${esc(w.name)}</td><td class="n">${bs.length}</td><td class="n">${esc(qty(bs.reduce((s, b) => s + Number(b.on_hand), 0)))}</td></tr>`;
  });
  $("#wrows").innerHTML = rows.join("");
  empty($("#wempty"), !rows.length, "No warehouses yet.", can("stock:write") ? " Select “New warehouse” to add the first one." : "");
}

const PO_STATUS = {open: ["Open", "warn"], partially_received: ["Part received", "warn"],
                   received: ["Received", "ok"], cancelled: ["Cancelled", "off"]};
function poRemaining(p) {
  return p.lines.reduce((s, l) => s + Math.max(Number(l.qty) - Number(l.received_qty || 0), 0), 0);
}
const openLine = p => p.status === "partially_received"
  ? `${qty(poRemaining(p))} unit${Number(poRemaining(p)) === 1 ? "" : "s"} still to come`
  : `${plural(p.receipts ? p.receipts.length : 0, "receipt")} so far`;

function renderPOs() {
  const q = $("#oq").value.trim().toLowerCase(), f = state.poFilter;
  const list = state.pos.filter(p => (f === "all" || p.status === f) && (!q || p.po_number.toLowerCase().includes(q) || p.supplier.toLowerCase().includes(q)));
  $("#orows").innerHTML = list.map(p => `<tr class="go" data-po="${p.id}"><td><button class="rowbtn" data-act="open-po" data-id="${p.id}" type="button">${esc(p.po_number)}</button></td>
    <td>${esc(p.supplier)}</td><td>${esc(fmtDay(p.created_at))}</td><td class="n">${p.lines.length}</td>
    <td class="n">${p.receipts ? p.receipts.length : 0}</td><td class="n">${money(poValue(p))}</td>
    <td>${chipOf(PO_STATUS, p.status)}</td></tr>`).join("");
  empty($("#oempty"), !list.length, state.pos.length ? "No purchase order matches these filters." : "No purchase orders yet.",
    state.pos.length ? "" : (can("stock:write") ? " Select “New purchase order” to raise the first one." : ""));
}

/* ---------- suppliers (Module Phase 2) ---------- */
const SUP_STATUS = {active: ["Active", "ok"], blocked: ["Blocked", "bad"]};
const SKIND = {supplier: "Supplier", manufacturer: "Manufacturer", both: "Manufacturer and supplier"};
const REG = {regular: "Regular", composition: "Composition", unregistered: "Unregistered"};
const BSTAT = {pending: ["Awaiting approval", "warn"], approved: ["Approved", "ok"], rejected: ["Rejected", "bad"]};
const activeSuppliers = () => state.suppliers.filter(s => s.status === "active");

function renderSuppliers() {
  const q = $("#supq").value.trim().toLowerCase(), f = state.supFilter;
  const list = state.suppliers.filter(s => (f === "all" || (f === "incomplete" ? s.needs_completion : s.status === f)) &&
    (!q || [s.code, s.name, s.gstin || "", s.state || ""].some(t => t.toLowerCase().includes(q))));
  $("#suprows").innerHTML = list.map(s => `<tr><td><button class="rowbtn" data-act="open-supplier" data-id="${s.id}" type="button">${esc(s.code)}</button></td>
    <td>${esc(s.name)}${s.needs_completion ? ` <span class="chip warn">Needs completion</span>` : ""}</td>
    <td>${esc(s.gstin || "–")}</td><td>${esc(s.state || "–")}</td><td>${esc(SKIND[s.kind] || s.kind)}</td>
    <td class="n">${esc(s.payment_terms_days)} d</td><td class="n">${s.purchase_orders}</td><td>${chipOf(SUP_STATUS, s.status)}</td></tr>`).join("");
  empty($("#supempty"), !list.length, state.suppliers.length ? "No supplier matches these filters." : "No suppliers yet.",
    state.suppliers.length ? "" : (can("supplier:write") ? " Select “New supplier” to add the first one." : ""));

  const rows = state.bankChanges || [];
  $("#bankrows").innerHTML = rows.map(b => `<tr><td>${esc(b.supplier_code)}<small>${esc(b.supplier_name)}</small></td>
    <td>${esc(b.pending.bank_name || "–")}</td><td>${esc(b.pending.bank_account_no || "–")}</td>
    <td>${esc(b.requested_by)}</td><td>${esc(fmtStamp(b.requested_at))}</td><td>${chipOf(BSTAT, b.status)}</td>
    <td>${b.status === "pending" && can("approval:decide") ? `<button class="btn ghost sm" data-act="decide-bank" data-id="${b.id}" type="button">Decide</button>` : ""}</td></tr>`).join("");
  empty($("#bankempty"), !rows.length, "No bank-detail changes yet.",
    " A bank change is requested here and applied only after a different person approves it.");
}

function supplierForm() {
  openDrawer("New supplier", "GSTIN and PAN are checked for format and check character. The state comes from the GSTIN.", `
    <form id="supForm" novalidate>
      <div class="row2"><div><label for="f-scode">Supplier code</label><input id="f-scode" name="code" placeholder="SUP-001" autocomplete="off"></div>
      <div><label for="f-sname">Name</label><input id="f-sname" name="name" placeholder="Supplier name" autocomplete="off"></div></div>
      <div class="row2"><div><label for="f-skind">Type</label><select id="f-skind" name="kind">
        <option value="supplier">Supplier</option><option value="manufacturer">Manufacturer</option><option value="both">Manufacturer and supplier</option></select></div>
      <div><label for="f-sreg">GST registration</label><select id="f-sreg" name="registration_type">
        <option value="regular">Regular</option><option value="composition">Composition</option><option value="unregistered">Unregistered</option></select></div></div>
      <label for="f-sgstin">GSTIN</label><input id="f-sgstin" name="gstin" placeholder="27AAACX1234Z1Z5" autocomplete="off" autocapitalize="characters" spellcheck="false">
      <label for="f-span">PAN</label><input id="f-span" name="pan" placeholder="Taken from the GSTIN when left blank" autocomplete="off" autocapitalize="characters" spellcheck="false">
      <div class="row2"><div><label for="f-sstate">State code (unregistered only)</label><input id="f-sstate" name="state_code" placeholder="27" autocomplete="off" maxlength="2"></div>
      <div><label for="f-sterms">Payment terms (days)</label><input id="f-sterms" name="payment_terms_days" inputmode="numeric" value="30" autocomplete="off"></div></div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save supplier</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}
async function saveSupplier(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = ""; btn.disabled = true;
  const f = new FormData(form);
  const body = {code: (f.get("code") || "").trim(), name: (f.get("name") || "").trim(),
                kind: f.get("kind"), registration_type: f.get("registration_type"),
                payment_terms_days: Number(f.get("payment_terms_days") || 30)};
  const gstin = (f.get("gstin") || "").trim().toUpperCase();
  const pan = (f.get("pan") || "").trim().toUpperCase();
  const st = (f.get("state_code") || "").trim();
  if (gstin) body.gstin = gstin;
  if (pan) body.pan = pan;
  if (st) body.state_code = st;
  const res = await api("/api/suppliers", {method: "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? "Supplier saved" : "Supplier not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

function supplierDetail(id) {
  const s = state.suppliers.find(x => x.id === Number(id));
  if (!s) return;
  const canBank = can("supplier:bank"), canWrite = can("supplier:write");
  const bank = s.bank_name
    ? `<dl class="dl"><dt>Bank</dt><dd>${esc(s.bank_name)}</dd><dt>Account</dt><dd>${esc(s.bank_account_masked || "–")}</dd>
         <dt>IFSC</dt><dd>${esc(s.bank_ifsc || "–")}</dd><dt>Holder</dt><dd>${esc(s.bank_holder || "–")}</dd>
         <dt>Approved</dt><dd>${esc(s.bank_approved_at ? fmtStamp(s.bank_approved_at) : "No approval on record")}</dd></dl>`
    : `<div class="note">No bank details on file.</div>`;
  const bankForm = canBank ? `<h3>Request a bank-detail change</h3>
      <div class="note">The change is saved as a request and applied only when a <b>different</b> person approves it.</div>
      <form id="bankForm" data-sup="${s.id}" novalidate>
        <label for="b-name">Bank name</label><input id="b-name" name="bank_name" autocomplete="off">
        <label for="b-acc">Account number</label><input id="b-acc" name="bank_account_no" inputmode="numeric" autocomplete="off">
        <div class="row2"><div><label for="b-ifsc">IFSC</label><input id="b-ifsc" name="bank_ifsc" autocomplete="off" autocapitalize="characters"></div>
        <div><label for="b-holder">Account holder</label><input id="b-holder" name="bank_holder" autocomplete="off"></div></div>
        <div class="err" role="alert"></div>
        <div class="actions"><button class="btn" type="submit">Request change</button></div>
      </form>` : "";
  const blockBtn = canWrite ? `<button class="btn ghost" type="button" data-act="toggle-supplier" data-id="${s.id}">${s.status === "blocked" ? "Unblock supplier" : "Block supplier"}</button>` : "";
  openDrawer(s.code, s.name, `
    <dl class="dl"><dt>Status</dt><dd>${chipOf(SUP_STATUS, s.status)}</dd>
      <dt>Type</dt><dd>${esc(SKIND[s.kind] || s.kind)}</dd>
      <dt>GST registration</dt><dd>${esc(REG[s.registration_type] || s.registration_type)}</dd>
      <dt>GSTIN</dt><dd>${esc(s.gstin || "–")}</dd><dt>PAN</dt><dd>${esc(s.pan || "–")}</dd>
      <dt>State</dt><dd>${esc(s.state || "Not recorded yet")}</dd>
      <dt>Payment terms</dt><dd>${esc(s.payment_terms_days)} days</dd>
      <dt>Purchase orders</dt><dd>${esc(s.purchase_orders)}</dd></dl>
    ${s.needs_completion ? `<div class="note">This record came from an older free-text purchase order. Complete its GST details before using it on a tax document.</div>` : ""}
    <h3>Bank details</h3>${bank}${bankForm}
    <div class="actions">${blockBtn}<button class="btn ghost" type="button" data-act="close">Close</button></div>`, true);
}
async function requestBankChange(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = ""; btn.disabled = true;
  const f = new FormData(form);
  const res = await api(`/api/suppliers/${Number(form.dataset.sup)}/bank`, {method: "POST", body: {
    bank_name: (f.get("bank_name") || "").trim(), bank_account_no: (f.get("bank_account_no") || "").trim(),
    bank_ifsc: (f.get("bank_ifsc") || "").trim().toUpperCase(), bank_holder: (f.get("bank_holder") || "").trim()}});
  btn.disabled = false;
  toast(res, res.ok ? "Change requested for approval" : "Request not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}
async function toggleSupplier(id) {
  const s = state.suppliers.find(x => x.id === Number(id));
  if (!s) return;
  const res = await api(`/api/suppliers/${s.id}`, {method: "PATCH", body: {status: s.status === "blocked" ? "active" : "blocked"}});
  toast(res, res.ok ? `Supplier ${res.body.status}` : "Supplier not changed");
  if (res.ok) { closeDrawer(); loadAll(); }
}
function decideBankForm(id) {
  openDrawer("Decide a bank-detail change", "Approving applies the new account details to the supplier record.", `
    <form id="bankDecide" data-ap="${id}" novalidate>
      <label for="d-reason">Reason</label><input id="d-reason" name="reason" placeholder="e.g. verified with the supplier by phone" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit" data-decide="approve">Approve</button>
        <button class="btn ghost" type="submit" data-decide="reject">Reject</button></div>
    </form>`);
}
async function decideBank(form, decision) {
  const err = $(".err", form), reason = form.elements.reason.value.trim();
  err.textContent = "";
  if (reason.length < 3) { err.textContent = "Give a short reason for the decision."; form.elements.reason.focus(); return; }
  const res = await api(`/api/suppliers/bank-changes/${Number(form.dataset.ap)}/decide`,
                        {method: "POST", body: {decision, reason}});
  toast(res, res.ok ? (decision === "approve" ? "Change approved" : "Change rejected") : "Decision not recorded");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

/* ---------- forms: product, warehouse ---------- */
async function saveProduct(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  const hsn = f.hsn.value.trim();
  if (!/^[0-9]{4,8}$/.test(hsn)) { err.textContent = "Enter a 4 to 8 digit HSN code."; f.hsn.focus(); return; }
  if (!f.sku.value.trim() || !f.name.value.trim() || !f.pack.value.trim()) { err.textContent = "SKU, name and pack size are required."; return; }
  if (!(Number(f.mrp.value) >= 0)) { err.textContent = "Enter the MRP as zero or more."; return; }
  const body = {hsn, name: f.name.value.trim(), pack_size: f.pack.value.trim(), mrp: f.mrp.value};
  if (id) { if (f.status) body.status = f.status.value; }
  else { body.sku = f.sku.value.trim(); }
  btn.disabled = true;
  const res = await api(id ? `/api/products/${id}` : "/api/products", {method: id ? "PATCH" : "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? "Product saved" : "Product not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

function warehouseForm() {
  openDrawer("New warehouse", "Goods are received into a warehouse, so add one before the first receipt.", `
    <form id="whForm" novalidate>
      <label for="f-wh">Warehouse name</label><input id="f-wh" name="name" placeholder="Main store" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save warehouse</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}
async function saveWarehouse(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = ""; btn.disabled = true;
  const res = await api("/api/warehouses", {method: "POST", body: {name: new FormData(form).get("name")}});
  btn.disabled = false;
  toast(res, res.ok ? "Warehouse saved" : "Warehouse not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

/* ---------- forms: purchase order ---------- */
const PO_REMARKS = {testing: "Testing", sample: "Sample", foc: "Free of Cost (FOC)",
                    rate_pending: "Rate Pending", quotation_pending: "Quotation Pending",
                    promotional_stock: "Promotional Stock", replacement: "Replacement"};
function lineRow(canRemove) {
  const opts = state.products.filter(p => p.status === "active").map(p => `<option value="${esc(p.sku)}">${esc(p.sku)}, ${esc(p.name)}</option>`).join("");
  const remarks = Object.entries(PO_REMARKS).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  return `<div class="lrow" data-line>
    <div><span class="lab">Product</span><select name="sku" aria-label="Product"><option value="">Select a product</option>${opts}</select></div>
    <div><span class="lab">Quantity</span><input name="qty" inputmode="decimal" placeholder="0" aria-label="Quantity" autocomplete="off"></div>
    <div><span class="lab">Unit cost (₹)</span><input name="cost" inputmode="decimal" placeholder="Blank needs a remark" aria-label="Unit cost in rupees" autocomplete="off">
      <select name="remark" class="remark" aria-label="Reason the unit cost is blank"><option value="">Remark (required if blank)</option>${remarks}</select></div>
    <button class="rm" type="button" data-act="rm-line" aria-label="Remove this line" ${canRemove ? "" : "disabled"}>&times;</button></div>`;
}
function poForm() {
  if (!state.products.some(p => p.status === "active")) { toast({ok: false, status: 0, body: {detail: "Add a product first; an order needs at least one product line."}}, "Cannot start an order"); return; }
  const suppliers = activeSuppliers();
  if (!suppliers.length) { toast({ok: false, status: 0, body: {detail: "Add a supplier record first; every order is placed against one."}}, "Cannot start an order"); return; }
  const supOpts = suppliers.map(s => `<option value="${s.id}">${esc(s.name)} (${esc(s.code)})</option>`).join("");
  openDrawer("New purchase order", "Raise an order against a supplier record. Stock is added when the goods are received.", `
    <form id="poForm" novalidate>
      <label for="f-sup">Supplier</label><select id="f-sup" name="supplier_id">${supOpts}</select>
      <label for="f-pon">PO number</label><input id="f-pon" name="po_number" placeholder="Leave blank to generate one" autocomplete="off">
      <h3>Products ordered</h3>
      <div class="lines" id="plines">${lineRow(false)}</div>
      <button class="btn ghost sm addline" type="button" data-act="add-line">Add a line</button>
      <div class="total"><span>Order value</span><span class="num" id="ptotal">₹ 0.00</span></div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save purchase order</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}
function syncPoLines() {
  const rows = $$("[data-line]", $("#poForm"));
  rows.forEach(r => {
    $(".rm", r).disabled = rows.length < 2;
    const blank = $("[name=cost]", r).value.trim() === "";
    $("[name=remark]", r).classList.toggle("hide", !blank);
    $("[name=remark]", r).required = blank;
  });
  const total = rows.reduce((s, r) => s + (Number($("[name=qty]", r).value) || 0) * (Number($("[name=cost]", r).value) || 0), 0);
  $("#ptotal").textContent = "₹ " + money(total);
}
async function savePO(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const el = form.elements;
  const supplier_id = Number(el.supplier_id.value);
  if (!supplier_id) { err.textContent = "Choose a supplier."; el.supplier_id.focus(); return; }
  const lines = [];
  for (const r of $$("[data-line]", form)) {
    const sku = $("[name=sku]", r).value, q = $("[name=qty]", r).value.trim(), c = $("[name=cost]", r).value.trim();
    const remark = $("[name=remark]", r).value;
    if (!sku && !q && !c) continue;
    if (!sku) { err.textContent = "Choose a product on every line."; return; }
    if (!(Number(q) > 0)) { err.textContent = `Enter a quantity above zero for ${sku}.`; return; }
    if (c && !(Number(c) >= 0)) { err.textContent = `Unit cost for ${sku} must be zero or more.`; return; }
    if (c === "" && !remark) { err.textContent = `Enter a unit cost for ${sku}, or choose why it is blank.`; return; }
    lines.push(c === "" ? {sku, qty: q, unit_cost: null, rate_remark: remark}
                        : {sku, qty: q, unit_cost: c});
  }
  if (!lines.length) { err.textContent = "Add at least one product line."; return; }
  if (new Set(lines.map(l => l.sku)).size !== lines.length) { err.textContent = "Each product can appear on an order only once."; return; }
  const body = {supplier_id, lines};
  if (el.po_number.value.trim()) body.po_number = el.po_number.value.trim();
  btn.disabled = true;
  const res = await api("/api/purchase-orders", {method: "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? `Purchase order ${res.ok ? res.body.po_number : ""} saved` : "Order not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer();
  if (state.view !== "purchasing") location.hash = "#/purchasing";
  loadAll();
}

/* ---------- purchase order detail and goods receipt ---------- */
function poDetail(id, result) {
  const po = state.pos.find(p => p.id === Number(id));
  if (!po) return;
  const name = sku => (state.products.find(p => p.sku === sku) || {}).name || "";
  const lines = po.lines.map(l => `<tr><td><span class="strong">${esc(name(l.sku))}</span><small>${esc(l.sku)}</small></td>
    <td class="n">${esc(qty(l.qty))}</td><td class="n">${esc(qty(l.received_qty || 0))}</td>
    <td class="n">${l.unit_cost == null ? `<span class="chip warn">${esc(l.rate_remark_label || "No cost")}</span>` : money(l.unit_cost)}</td>
    <td class="n">${money(Number(l.qty) * Number(l.unit_cost || 0))}</td></tr>`).join("");
  const receipts = (po.receipts || []).map(r => `<tr><td>${esc(r.grn_number)}</td><td>${esc(fmtStamp(r.received_at))}</td>
    <td>${esc(r.owner)}</td><td>${esc(r.delivery_note || "–")}</td>
    <td>${r.lines.map(x => `${esc(x.sku)} ${esc(qty(x.qty))} (${esc(x.batch_no)})`).join(", ")}</td></tr>`).join("");
  const open = po.status === "open" || po.status === "partially_received";
  let foot;
  if (result) {
    const left = Object.entries(result.remaining).filter(([, v]) => Number(v) > 0);
    foot = `<div class="done"><b>Receipt ${esc(result.grn_number)} posted.${left.length ? " The order is still partly open." : " The order is now fully received."}</b><ul>${result.received.map(r =>
      `<li>${esc(qty(r.qty))} of ${esc(r.sku)} added to batch ${esc(r.batch_no)}; ${esc(qty(r.batch_on_hand))} now on hand.</li>`).join("")}</ul>
      ${left.length ? `<p class="muted">Still to come: ${left.map(([sku, v]) => `${esc(sku)} ${esc(qty(v))}`).join(", ")}.</p>` : ""}</div>`;
  } else if (!open) {
    foot = `<div class="note">${po.status === "cancelled" ? `This order was cancelled${po.cancel_reason ? `: ${esc(po.cancel_reason)}` : ""}.` : "This order has been received in full. The stock it added is in the stock ledger."}</div>`;
  } else if (!can("stock:write")) {
    foot = `<div class="note">Your role can view orders but not receive goods.</div>`;
  } else if (!state.warehouses.length) {
    foot = `<div class="note">Add a warehouse before receiving goods. <button class="link-btn" type="button" data-act="goto-wh">Add a warehouse</button></div>`;
  } else {
    foot = `<h3>Receive goods</h3>
      <div class="note">Enter what actually arrived in this delivery. The order stays open until every line is received in full, and each receipt posts its own stock-ledger movements.</div>
      <form id="rcvForm" data-po="${po.id}" novalidate>
        <label for="r-wh">Warehouse</label>
        <select id="r-wh" name="warehouse">${state.warehouses.length > 1 ? `<option value="">Select a warehouse</option>` : ""}${state.warehouses.map(w => `<option value="${w.id}">${esc(w.name)}</option>`).join("")}</select>
        <div class="row2"><div><label for="r-dn">Supplier delivery-note number</label><input id="r-dn" name="delivery_note" placeholder="Optional, blocks a repeat" autocomplete="off"></div>
        <div><label for="r-own">Who owns the stock</label><select id="r-own" name="owner"><option value="HERBANOVA">HERBANOVA</option><option value="MANUFACTURER">Manufacturer</option></select></div></div>
        <div class="rcv">${po.lines.map((l, i) => { const rest = Math.max(Number(l.qty) - Number(l.received_qty || 0), 0);
          return `<div class="rcv-line" data-sku="${esc(l.sku)}">
          <div class="hd"><span class="strong">${esc(name(l.sku)) || esc(l.sku)}</span><span class="muted">Ordered ${esc(qty(l.qty))}, received ${esc(qty(l.received_qty || 0))}, still to come ${esc(qty(rest))}</span></div>
          <div class="row3">
            <div><label for="r-b${i}">Batch number</label><input id="r-b${i}" name="batch" autocomplete="off"></div>
            <div><label for="r-q${i}">Quantity in this delivery</label><input id="r-q${i}" name="qty" inputmode="decimal" value="${rest ? esc(rest) : ""}" ${rest ? "" : "disabled"} autocomplete="off"></div>
            <div><label for="r-e${i}">Expiry date</label><input id="r-e${i}" name="expiry" type="date"></div>
          </div></div>`; }).join("")}</div>
        <div class="err" role="alert"></div>
        <div class="actions"><button class="btn" type="submit">Post receipt</button><button class="btn ghost" type="button" data-act="cancel-po" data-id="${po.id}">Cancel order</button><button class="btn ghost" type="button" data-act="close">Close</button></div>
      </form>`;
  }
  if (!foot.includes("<form")) foot += `<div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`;
  openDrawer(po.po_number, `Purchase order with ${po.supplier}`, `
    <dl class="dl"><dt>Status</dt><dd>${chipOf(PO_STATUS, po.status)}</dd>
      <dt>Created</dt><dd>${esc(fmtDay(po.created_at))}</dd><dt>Supplier</dt><dd>${esc(po.supplier)}</dd>
      <dt>Still to come</dt><dd>${esc(qty(poRemaining(po)))} units on ${plural((po.receipts || []).length, "receipt")}</dd></dl>
    <h3>Products ordered</h3>
    <table class="dtable"><thead><tr><th>Product</th><th class="n">Qty</th><th class="n">Received</th><th class="n">Unit cost (₹)</th><th class="n">Line total (₹)</th></tr></thead><tbody>${lines}</tbody>
      <tfoot><tr><td colspan="4">Order value</td><td class="n">${money(poValue(po))}</td></tr></tfoot></table>
    ${receipts ? `<h3>Goods receipt notes</h3><table class="dtable"><thead><tr><th>Receipt</th><th>When</th><th>Owner</th><th>Delivery note</th><th>What arrived</th></tr></thead><tbody>${receipts}</tbody></table>` : ""}
    ${foot}`, true);
}
async function postReceipt(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const wh = form.elements.warehouse.value;
  if (!wh) { err.textContent = "Choose the warehouse the goods went into."; form.elements.warehouse.focus(); return; }
  const lines = [];
  for (const row of $$(".rcv-line", form)) {
    const q = $("[name=qty]", row).value.trim(), sku = row.dataset.sku, b = $("[name=batch]", row).value.trim(), e = $("[name=expiry]", row).value;
    if (!q || Number(q) === 0) continue;
    if (!(Number(q) > 0)) { err.textContent = `Quantity for ${sku} must be above zero.`; return; }
    if (!b) { err.textContent = `Enter a batch number for ${sku}.`; $("[name=batch]", row).focus(); return; }
    lines.push({sku, batch_no: b, qty: q, ...(e ? {expiry: e} : {})});
  }
  if (!lines.length) { err.textContent = "Enter a received quantity for at least one line."; return; }
  const body = {warehouse_id: Number(wh), lines, owner: form.elements.owner.value};
  const dn = form.elements.delivery_note.value.trim();
  if (dn) body.delivery_note = dn;
  const id = Number(form.dataset.po);
  btn.disabled = true;
  const res = await api(`/api/purchase-orders/${id}/receive`, {method: "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? `Receipt ${res.body.grn_number} posted` : "Receipt not posted");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await loadAll();
  poDetail(id, res.body);
}
function cancelPoForm(id) {
  openDrawer("Cancel purchase order", "Only an order with no goods received can be cancelled.", `
    <form id="poCancel" data-po="${id}" novalidate>
      <label for="c-reason">Reason</label><input id="c-reason" name="reason" placeholder="e.g. supplier cannot supply" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Cancel the order</button><button class="btn ghost" type="button" data-act="close">Keep it open</button></div>
    </form>`);
}
async function cancelPo(form) {
  const err = $(".err", form), reason = form.elements.reason.value.trim();
  err.textContent = "";
  if (reason.length < 3) { err.textContent = "Give a short reason."; form.elements.reason.focus(); return; }
  const id = Number(form.dataset.po);
  const res = await api(`/api/purchase-orders/${id}/cancel`, {method: "POST", body: {reason}});
  toast(res, res.ok ? "Order cancelled" : "Order not cancelled");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); await loadAll();
  if (state.view !== "purchasing") location.hash = "#/purchasing";
}

/* ---------- sales orders, approvals, distributors ---------- */
const SO = {draft: ["Draft", "off"], pending_approval: ["Awaiting approval", "warn"], approved: ["Approved", "ok"],
            dispatched: ["Dispatched", "ok"], rejected: ["Rejected", "bad"], cancelled: ["Cancelled", "off"]};
const AP = {pending: ["Pending", "warn"], approved: ["Approved", "ok"], rejected: ["Rejected", "bad"], withdrawn: ["Withdrawn", "off"]};
const REASON = {credit_limit: "Over credit limit", discount: "Discount approval"};
const chipOf = (map, k) => { const m = map[k] || [k, "off"]; return `<span class="chip ${m[1]}">${esc(m[0])}</span>`; };
const reasonChips = rs => (rs || []).map(r => `<span class="chip warn">${esc(REASON[r] || r)}</span>`).join(" ");
const orderOf = id => state.orders.find(o => o.id === Number(id));
const activeDists = () => state.dists.filter(d => d.status === "active");

function renderSales() {
  const q = $("#soq").value.trim().toLowerCase(), f = state.soFilter;
  const list = state.orders.filter(o => (f === "all" || o.status === f) &&
    (!q || o.so_number.toLowerCase().includes(q) || o.distributor_code.toLowerCase().includes(q) || o.distributor_name.toLowerCase().includes(q)));
  $("#sorows").innerHTML = list.map(o => `<tr class="go" data-so="${o.id}"><td><button class="rowbtn" data-act="open-so" data-id="${o.id}" type="button">${esc(o.so_number)}</button></td>
    <td>${esc(o.distributor_name)}<small>${esc(o.distributor_code)}</small></td><td>${esc(fmtDay(o.created_at))}</td><td class="n">${o.lines.length}</td>
    <td class="n">${money(o.total)}</td><td>${chipOf(SO, o.status)}</td></tr>`).join("");
  empty($("#soempty"), !list.length, state.orders.length ? "No order matches these filters." : "No sales orders yet.",
    state.orders.length ? "" : (can("sales:write") ? " Select “New sales order” to start one." : ""));
  const n = state.orders.filter(o => o.status === "approved").length, c = $("#soCount");
  c.textContent = n; c.classList.toggle("hide", !n); c.setAttribute("aria-label", `${n} orders ready to dispatch`);
}

function renderApprovals() {
  const f = state.apFilter;
  const list = state.approvals.filter(a => f === "all" || (f === "pending" ? a.status === "pending" : a.status !== "pending"));
  $("#aprows").innerHTML = list.map(a => `<tr class="go" data-ap="${a.id}"><td><button class="rowbtn" data-act="open-ap" data-id="${a.id}" type="button">${esc(a.request_no || a.document_number || "Request")}</button></td>
    <td>${esc(a.request_type_label)}</td><td>${esc(a.document_number || "–")}<small>${esc(a.subject || "")}</small></td>
    <td>${esc(a.requested_by)}</td><td>${esc(fmtDay(a.requested_at))}</td>
    <td>${chipOf(AP, a.status)}${a.decided_by ? `<small>by ${esc(a.decided_by)}, ${esc(fmtDay(a.decided_at))}</small>` : ""}</td>
    <td>${esc(a.decision_reason || "–")}</td></tr>`).join("");
  empty($("#apempty"), !list.length, f === "pending" ? "Nothing is waiting for a decision." : "No approval requests yet.",
    f === "pending" ? " Orders over a credit limit, large discounts, HR requests and post-billing edits appear here." : "");
  const n = state.approvals.filter(a => a.status === "pending").length, c = $("#apCount");
  c.textContent = n; c.classList.toggle("hide", !n); c.setAttribute("aria-label", `${n} approvals waiting`);
}

// One status vocabulary, shared with the API (COR-001). An unknown value must
// never throw: renderDists runs before renderLeads and renderUsers, so a single
// bad chip would blank every section after it. Every value the API can store is
// listed here, so the form can offer them and the chip can name them.
const DSTAT = {
  active: ["ok", "Active"],
  blocked: ["bad", "Blocked"],
  draft: ["off", "Draft"],
  "pending verification": ["warn", "Pending verification"],
  inactive: ["off", "Inactive"]
};
// The order the form offers them in; the stored value is the key, unchanged.
const DIST_STATUSES = ["active", "draft", "pending verification", "blocked", "inactive"];
const DSTAT_MISSING = {state_code: "place of supply (state code)", gstin: "GSTIN"};
function distChip(status) {
  const c = DSTAT[status] || ["off", status || "unknown"];
  return `<span class="chip ${c[0]}">${esc(c[1])}</span>`;
}
function distGaps(d) {
  const gaps = (d.completion_missing || []).map(k => DSTAT_MISSING[k] || k);
  return gaps.length ? gaps.join(", ") : "none";
}

function renderDists() {
  const filter = state.distFilter;
  const showed = state.dists.filter(d => {
    if (filter === "incomplete") return !!d.needs_completion;
    if (DIST_STATUSES.includes(filter)) return d.status === filter;
    return true;
  });
  $("#drows").innerHTML = showed.map(d => {
    const lim = Number(d.credit_limit), use = Number(d.exposure);
    const pct = lim > 0 ? Math.min(100, use / lim * 100) : (use > 0 ? 100 : 0);
    const actions = [
      can("distributor:write") ? `<button class="btn ghost sm" type="button" data-act="edit-dist" data-id="${d.id}">Edit</button>` : "",
      can("credit:manage") ? `<button class="btn ghost sm" type="button" data-act="change-limit" data-id="${d.id}">Change limit</button>` : ""
    ].join(" ");
    return `<tr><td class="strong">${esc(d.code)}</td>
      <td>${esc(d.name)}${d.needs_completion ? ` <span class="chip warn">Needs completion</span>` : ""}<small>${esc(d.territory)}</small></td>
      <td class="n">${money(lim)}</td>
      <td class="n">${money(use)}<div class="meter use"><i style="width:${pct.toFixed(0)}%"></i></div></td>
      <td class="n">${money(d.available)}</td>
      <td>${distChip(d.status)}</td>
      <td>${actions}</td></tr>`;
  }).join("");
  const messages = {
    incomplete: ["Every distributor has the details a tax document needs.", ""],
    active: ["No active distributor matches.", " Select “All” to see the blocked ones."],
    blocked: ["No distributor is blocked.", " Select “Active” to see the ones that are trading."],
    draft: ["No distributor is still a draft.", " A draft record is kept out of new orders until it is made Active."],
    "pending verification": ["Nothing is awaiting verification.", " A record in this state is kept out of new orders until it is made Active."],
    inactive: ["No distributor is inactive.", " An inactive record is kept out of new orders until it is made Active."]
  };
  const [title, hint] = messages[filter] || ["No distributors yet.", can("distributor:write") ? " Select “New distributor” to add the first one." : ""];
  empty($("#dempty"), !showed.length, title, hint);
}

/* --- new sales order --- */
function soLineRow(canRemove) {
  const opts = state.products.filter(p => p.status === "active").map(p => `<option value="${esc(p.sku)}">${esc(p.sku)}, ${esc(p.name)}</option>`).join("");
  return `<div class="lrow" data-line>
    <div><span class="lab">Product</span><select name="sku" aria-label="Product"><option value="">Select a product</option>${opts}</select></div>
    <div><span class="lab">Quantity</span><input name="qty" inputmode="numeric" placeholder="0" aria-label="Quantity in packs" autocomplete="off"></div>
    <div><span class="lab">Price (₹)</span><input name="price" inputmode="decimal" placeholder="MRP" aria-label="Price in rupees, blank for MRP" autocomplete="off"></div>
    <button class="rm" type="button" data-act="rm-sline" aria-label="Remove this line" ${canRemove ? "" : "disabled"}>&times;</button></div>`;
}
function soForm() {
  const ds = activeDists();
  if (!ds.length) { toast({ok: false, status: 0, body: {detail: "Add a distributor first; an order needs one."}}, "Cannot start an order"); return; }
  if (!state.products.some(p => p.status === "active")) { toast({ok: false, status: 0, body: {detail: "Add a product first; an order needs at least one product line."}}, "Cannot start an order"); return; }
  openDrawer("New sales order", "Saved as a draft. Stock and credit are checked when you submit it.", `
    <form id="soForm" novalidate>
      <label for="s-d">Distributor</label>
      <select id="s-d" name="dist"><option value="">Select a distributor</option>${ds.map(d => `<option value="${d.id}"${state.soDistPreset === d.id ? " selected" : ""}>${esc(d.code)}, ${esc(d.name)} (₹ ${money(d.available)} credit available)</option>`).join("")}</select>
      <h3>Products</h3>
      <div class="lines" id="slines">${soLineRow(false)}</div>
      <button class="btn ghost sm addline" type="button" data-act="add-sline">Add a line</button>
      <div class="total"><span>Order value</span><span class="num" id="stotal">₹ 0.00</span></div>
      <div class="note">Leave the price blank to sell at MRP. A price above MRP is refused, and a discount over 10% needs an approver.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save draft</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}
function syncSoLines() {
  const f = $("#soForm"); if (!f) return;
  const rows = $$("[data-line]", f);
  rows.forEach(r => $(".rm", r).disabled = rows.length < 2);
  const total = rows.reduce((s, r) => {
    const p = state.products.find(x => x.sku === $("[name=sku]", r).value), pr = $("[name=price]", r).value.trim();
    return s + (Number($("[name=qty]", r).value) || 0) * (pr !== "" ? Number(pr) || 0 : p ? Number(p.mrp) : 0);
  }, 0);
  $("#stotal").textContent = "₹ " + money(total);
}
async function saveSO(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form); err.textContent = "";
  const dist = form.elements.dist.value;
  if (!dist) { err.textContent = "Choose the distributor."; form.elements.dist.focus(); return; }
  const lines = [];
  for (const r of $$("[data-line]", form)) {
    const sku = $("[name=sku]", r).value, q = $("[name=qty]", r).value.trim(), pr = $("[name=price]", r).value.trim();
    if (!sku && !q && !pr) continue;
    if (!sku) { err.textContent = "Choose a product on every line."; return; }
    if (!(Number(q) > 0) || !Number.isInteger(Number(q))) { err.textContent = `Enter a whole number of packs above zero for ${sku}.`; return; }
    if (pr !== "" && !(Number(pr) >= 0)) { err.textContent = `Price for ${sku} must be zero or more.`; return; }
    lines.push({sku, qty: q, ...(pr !== "" ? {unit_price: pr} : {})});
  }
  if (!lines.length) { err.textContent = "Add at least one product line."; return; }
  if (new Set(lines.map(l => l.sku)).size !== lines.length) { err.textContent = "Each product can appear on an order only once."; return; }
  btn.disabled = true;
  const res = await api("/api/sales-orders", {method: "POST", body: {distributor_id: Number(dist), lines}});
  btn.disabled = false;
  toast(res, res.ok ? `Draft ${res.body.so_number} saved` : "Order not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer();
  if (state.view !== "sales") location.hash = "#/sales";
  await loadAll(); soDetail(res.body.id);
}

/* --- order detail: submit, cancel, dispatch --- */
function soDetail(id, result, err) {
  const o = orderOf(id); if (!o) return;
  const a = o.approval;
  const lines = o.lines.map(l => `<tr><td><span class="strong">${esc(l.product_name)}</span><small>${esc(l.sku)}</small></td>
    <td class="n">${esc(qty(l.qty))}</td><td class="n">${money(l.unit_price)}${Number(l.discount_pct) > 0 ? `<small>${esc(l.discount_pct)}% below MRP</small>` : ""}</td>
    <td class="n">${money(l.line_total)}</td></tr>`).join("");
  const cancelForm = () => can("sales:write") ? `<form id="cancelForm" data-id="${o.id}" novalidate><h3>Cancel this order</h3>
      <label for="c-r">Reason</label><input id="c-r" name="reason" placeholder="Why is it being cancelled?" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn ghost" type="submit">Cancel order</button><button class="btn ghost" type="button" data-act="close">Close</button></div></form>` : `<div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`;
  let foot = "";
  if (err) foot += `<div class="err" role="alert">${esc(err)}</div>`;
  if (result) {
    foot += `<div class="done"><b>Dispatched. Stock has been issued, earliest expiry first.</b><ul>${result.allocations.map(x =>
      `<li>${esc(qty(x.qty))} of ${esc(x.sku)} from batch ${esc(x.batch_no)}${x.expiry ? `, expires ${esc(fmtDate(x.expiry))}` : ""}.</li>`).join("")}</ul></div>
      <div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`;
  } else if (o.status === "draft") {
    foot += can("sales:write")
      ? `<div class="note">Submitting checks that the stock is available and that the distributor stays within their credit limit.</div>
         <div class="actions"><button class="btn" type="button" data-act="submit-so" data-id="${o.id}">Submit for checks</button></div>${cancelForm()}`
      : `<div class="note">This draft has not been submitted. Your role can view orders but not submit them.</div><div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`;
  } else if (o.status === "pending_approval") {
    foot += `<div class="note">${reasonChips(a && a.reasons)} A different person must approve this order before it can be dispatched.</div>
      ${can("approval:decide") && a ? `<div class="actions"><button class="btn" type="button" data-act="open-ap" data-id="${a.id}">Review approval</button></div>` : ""}${cancelForm()}`;
  } else if (o.status === "approved") {
    if (can("dispatch:write")) {
      foot += state.warehouses.length ? `<h3>Dispatch goods</h3>
        <div class="note">Check the discount slab and the GST shown above first: they are what the invoice will charge. Stock is taken from the chosen warehouse, earliest expiry first. Credit and stock are checked again now. An order is dispatched once.</div>
        <form id="dispForm" data-id="${o.id}" novalidate>
          <label for="d-wh">Warehouse</label>
          <select id="d-wh" name="warehouse">${state.warehouses.length > 1 ? `<option value="">Select a warehouse</option>` : ""}${state.warehouses.map(w => `<option value="${w.id}">${esc(w.name)}</option>`).join("")}</select>
          <div class="err" role="alert"></div>
          <div class="actions"><button class="btn" type="submit">Dispatch goods</button><button class="btn ghost" type="button" data-act="close">Close</button></div></form>`
        : `<div class="note">Add a warehouse before dispatching.</div>`;
    } else foot += `<div class="note">Approved. Waiting for the warehouse to dispatch.</div>`;
    foot += can("sales:write") ? cancelForm() : "";
  } else if (o.status === "dispatched") {
    foot += `<div class="note">Dispatched ${esc(fmtStamp(o.dispatched_at))}. The stock it used is in the stock ledger.</div><div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`;
  } else {
    const why = o.status === "cancelled" ? o.cancel_reason : (a && a.status === "rejected" ? "Rejected by an approver." : "");
    foot += `<div class="note">This order is ${esc(SO[o.status][0].toLowerCase())}. ${esc(why || "")}</div><div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`;
  }
  openDrawer(o.so_number, `Sales order for ${o.distributor_name}`, `
    <dl class="dl"><dt>Status</dt><dd>${chipOf(SO, o.status)}</dd><dt>Distributor</dt><dd>${esc(o.distributor_code)}, ${esc(o.distributor_name)}</dd>
      <dt>Created</dt><dd>${esc(fmtDay(o.created_at))} by ${esc(o.created_by)}</dd>
      ${a ? `<dt>Approval</dt><dd>${chipOf(AP, a.status)} ${reasonChips(a.reasons)}</dd>` : ""}</dl>
    <h3>Products</h3>
    <table class="dtable"><thead><tr><th>Product</th><th class="n">Qty</th><th class="n">Price (₹)</th><th class="n">Line total (₹)</th></tr></thead><tbody>${lines}</tbody>
      <tfoot><tr><td colspan="3">Order value</td><td class="n">${money(o.total)}</td></tr></tfoot></table>
    <h3>GST and discount</h3><div id="soTax"><div class="note">Working out the tax…</div></div>${foot}`, true);
  loadSoTax(o);
}

/* --- the GST and the discount slab this order will invoice (FR-13) --- */
const slabWhere = s => s.scope === "group" ? ` for the ${esc(s.group_name)} group`
  : s.scope === "product" ? " for one product" : "";
async function loadSoTax(o) {
  const box = $("#soTax"); if (!box) return;
  const res = await api(`/api/sales-orders/${o.id}/tax-preview`);
  if (!box.isConnected) return;                     // the drawer has moved on
  if (!res.ok) {
    box.innerHTML = `<div class="err" role="alert">${esc(detail(res.body))}</div>
      <div class="note">Until the company tax profile and the distributor's state are saved, this order cannot be shown as a tax document. Nothing is assumed in their place.</div>`;
    return;
  }
  const t = res.body, totals = t.totals, pos = t.place_of_supply, sgst = pos.sgst_label;
  const intra = pos.kind === "intra";
  const withCess = t.lines.some(l => l.rate_found && Number(l.cess_amount) !== 0);
  const cols = 3 + (intra ? 2 : 1) + (withCess ? 1 : 0) + 1;   // product, rate, taxable, heads, [cess], total
  const head = ["<th>Product</th>", `<th class="n">GST %</th>`, `<th class="n">Taxable (₹)</th>`]
    .concat(intra ? [`<th class="n">CGST</th>`, `<th class="n">${esc(sgst)}</th>`]
                  : [`<th class="n">IGST</th>`])
    .concat(withCess ? [`<th class="n">Cess</th>`] : [])
    .concat([`<th class="n">Total (₹)</th>`]).join("");
  const rows = t.lines.map(l => {
    const num = v => `<td class="n">${money(v)}</td>`, none = `<td class="n">–</td>`;
    const heads = l.rate_found
      ? (intra ? num(l.cgst_amount) + num(l.sgst_amount) : num(l.igst_amount))
      : (intra ? none + none : none);
    return `<tr>
      <td><span class="strong">${esc(l.product_name)}</span><small>${esc(l.sku)}${l.hsn ? ` · HSN ${esc(l.hsn)}` : ""}${l.uqc ? ` · ${esc(l.uqc)}` : ""}${l.slab && (!t.slab || l.slab.id !== t.slab.id) ? ` · slab: ${esc(l.slab.name)}` : ""}</small>${l.approval_needed ? ` <span class="chip warn">needs approval</span>` : ""}</td>
      <td class="n">${l.rate_found ? (intra ? `${money(l.cgst_rate)} + ${money(l.sgst_rate)}` : money(l.igst_rate)) : "–"}</td>
      ${l.rate_found ? num(l.taxable_value) : none}
      ${heads}
      ${withCess ? (l.rate_found ? num(l.cess_amount) : none) : ""}
      ${l.rate_found ? num(l.total) : `<td class="n"><small>no rate</small></td>`}</tr>`;
  }).join("");
  const slab = t.slab
    ? `<span class="chip ok">${esc(t.slab.name)}</span> ${money(t.slab.discount_percent)}% off${slabWhere(t.slab)}${t.slab.approval_above != null ? `, approval above ${money(t.slab.approval_above)}%` : ""}`
    : `No discount slab applies to this order as a whole.`;
  box.innerHTML = `
    <div class="note">Place of supply: <b>${esc(pos.buyer_state_name)} (${esc(pos.buyer_state)})</b> — ${intra ? "inside the seller's state, so CGST + SGST is charged" : "another state, so IGST is charged"}. Rates are the ones in force on ${esc(fmtDate(t.on))}.</div>
    <div class="tw"><table class="dtable"><thead><tr>${head}</tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><td colspan="${cols - 1}">Total with GST</td><td class="n">${money(totals.grand_total)}</td></tr></tfoot></table></div>
    <dl class="dl"><dt>Discount slab</dt><dd>${slab}</dd>
      <dt>Order value</dt><dd>₹ ${money(totals.gross)}</dd>
      <dt>Discount</dt><dd>− ₹ ${money(totals.discount_amount)}</dd>
      <dt>Taxable value</dt><dd>₹ ${money(totals.taxable_value)}</dd>
      <dt>GST</dt><dd>₹ ${money(totals.tax_total)}${pos.kind === "intra" ? ` (CGST ₹ ${money(totals.cgst_amount)} + ${esc(sgst)} ₹ ${money(totals.sgst_amount)})` : ` (IGST ₹ ${money(totals.igst_amount)})`}</dd>
      <dt>Round off</dt><dd>₹ ${money(totals.round_off)}</dd>
      <dt>Invoice total</dt><dd>₹ ${money(totals.grand_total)}</dd></dl>
    ${t.notes.length ? `<div class="note"><b>Before dispatch, check</b><ul class="notes">${t.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}`;
}
async function submitSO(id) {
  const res = await api(`/api/sales-orders/${id}/submit`, {method: "POST"});
  toast(res, res.ok ? (res.body.status === "approved" ? "Checks passed: order approved" : "Sent for approval") : "Checks failed");
  await loadAll(); soDetail(id, null, res.ok ? "" : detail(res.body));
}
async function cancelSO(form) {
  const err = $(".err", form), reason = form.elements.reason.value.trim(); err.textContent = "";
  if (reason.length < 3) { err.textContent = "Give a reason of at least three characters."; return; }
  const res = await api(`/api/sales-orders/${form.dataset.id}/cancel`, {method: "POST", body: {reason}});
  toast(res, res.ok ? "Order cancelled" : "Order not cancelled");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await loadAll(); soDetail(form.dataset.id);
}
async function postDispatch(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form); err.textContent = "";
  const wh = form.elements.warehouse.value;
  if (!wh) { err.textContent = "Choose the warehouse the goods leave from."; return; }
  btn.disabled = true;
  const res = await api(`/api/sales-orders/${form.dataset.id}/dispatch`, {method: "POST", body: {warehouse_id: Number(wh)}});
  btn.disabled = false;
  toast(res, res.ok ? "Goods dispatched" : "Not dispatched");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await loadAll(); soDetail(form.dataset.id, res.body);
}

/* --- billing: invoices and the notes that correct them (Module Phase 4) --- */
const INV_STATUS = {issued: ["Issued", "ok"], cancelled: ["Cancelled", "off"]};

function renderBilling() {
  const q = $("#biq").value.trim().toLowerCase(), f = state.invFilter;
  const list = state.invoices.filter(i => (f === "all" || i.status === f) &&
    (!q || [i.invoice_number, i.buyer_name, i.so_number || ""].some(t => t.toLowerCase().includes(q))));
  $("#invrows").innerHTML = list.map(i => `<tr><td><button class="rowbtn" data-act="open-inv" data-id="${i.id}" type="button">${esc(i.invoice_number)}</button><small>${esc(i.financial_year)}${i.so_number ? " · " + esc(i.so_number) : ""}</small></td>
    <td>${esc(fmtDate(i.invoice_date))}</td><td>${esc(i.buyer_name)}<small>${esc(i.buyer_gstin || "Unregistered")}</small></td>
    <td class="n strong">${money(i.grand_total)}</td><td class="n">${money(i.credit_note_total)}</td>
    <td>${chipOf(INV_STATUS, i.status)}</td>
    <td><button class="btn ghost sm" data-act="open-inv" data-id="${i.id}" type="button">Open</button><button class="btn ghost sm" data-act="print-inv" data-id="${i.id}" type="button">Print</button></td></tr>`).join("");
  empty($("#invempty"), !list.length, state.invoices.length ? "No invoice matches this filter." : "No invoices yet.",
    state.invoices.length ? "" : " An invoice is issued automatically when an approved sales order is dispatched.");

  const notes = [...state.creditNotes.map(n => ({...n, kind: "Credit", no: n.credit_note_number})),
                 ...state.debitNotes.map(n => ({...n, kind: "Debit", no: n.debit_note_number}))]
    .sort((a, b) => b.id - a.id);
  $("#noterows").innerHTML = notes.map(n => `<tr><td class="strong">${esc(n.no)}</td><td>${esc(n.invoice_number || "–")}</td>
    <td>${esc(fmtDate(n.note_date))}</td><td>${esc(n.kind)}<small>${esc(n.reason)}${n.returned_to_stock ? ` · returned to ${esc(n.warehouse || "stock")}` : ""}</small></td>
    <td class="n">${money(n.grand_total)}</td><td>${chipOf(INV_STATUS, n.status)}</td></tr>`).join("");
  empty($("#noteempty"), !notes.length, "No credit or debit notes yet.",
    " A note corrects an issued invoice, is linked to it, and cannot exceed it.");
}

function invDetail(id, err, notice) {
  const inv = state.invoices.find(x => x.id === Number(id)); if (!inv) return;
  const live = inv.status === "issued";
  const lines = inv.lines.map(l => `<tr><td><span class="strong">${esc(l.product_name)}</span><small>${esc(l.sku)} · HSN ${esc(l.hsn || "missing")} · ${esc(l.uqc || "no UQC")}</small></td>
      <td class="n">${esc(qty(l.qty))}</td><td class="n">${money(l.unit_price)}</td><td class="n">${money(l.taxable_value)}</td>
      <td class="n">${money(l.cgst_amount)}</td><td class="n">${money(l.sgst_amount)}</td><td class="n">${money(l.igst_amount)}</td><td class="n">${money(l.line_total)}</td></tr>`).join("");
  const noted = [...state.creditNotes.filter(n => n.invoice_id === inv.id).map(n => ({...n, kind: "Credit note", no: n.credit_note_number})),
                 ...state.debitNotes.filter(n => n.invoice_id === inv.id).map(n => ({...n, kind: "Debit note", no: n.debit_note_number}))];
  const retRows = inv.lines.map(l => `<tr><td><span class="strong">${esc(l.product_name)}</span><small>${esc(l.sku)} · invoiced ${esc(qty(l.qty))}</small></td>
      <td><input name="qty-${l.invoice_line_id}" inputmode="decimal" placeholder="0" aria-label="Quantity to note for ${esc(l.sku)}" style="max-width:120px"></td></tr>`).join("");
  const qtyInputs = retRows;
  const whOptions = state.warehouses.map(w => `<option value="${w.id}">${esc(w.name)}</option>`).join("");
  const noteForm = (kind, label) => `<form id="${kind}Form" data-id="${inv.id}" novalidate>
      <h3>${esc(label)}</h3>
      <div class="note">Enter the quantity to correct on each line; leave the rest blank. Tax is reversed line by line, and the total cannot pass what the invoice charged.</div>
      <div class="tw"><table class="dtable"><thead><tr><th>Line</th><th class="n">Quantity</th></tr></thead><tbody>${qtyInputs}</tbody></table></div>
      ${kind === "cn" ? `<label for="cn-ret">Put the returned goods back into stock?</label>
      <select id="cn-ret" name="return_to_stock"><option value="">No — a money correction only</option>${whOptions}</select>
      <div class="note">Choosing a warehouse returns the credited quantities to the same batches they were issued from, in this warehouse. It cannot exceed what this order issued.</div>` : ""}
      <label for="${kind}-r">Reason</label><input id="${kind}-r" name="reason" placeholder="Sales return, rate difference, freight undercharged…" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Issue ${esc(label.toLowerCase())}</button></div></form>`;

  let foot = "";
  if (err) foot += `<div class="err" role="alert">${esc(err)}</div>`;
  if (notice) foot += `<div class="note">${esc(notice)}</div>`;
  if (inv.status === "cancelled") {
    foot += `<div class="note"><b>Cancelled</b>${inv.cancel_reason ? `: ${esc(inv.cancel_reason)}` : ""}. The number is kept and never reused.</div>`;
  } else {
    if (can("invoice:edit_post_billing")) foot += `<form id="moveForm" data-id="${inv.id}" novalidate><h3>Amend after billing (Administrator)</h3>
        <div class="row2"><div><label for="mv-dc">Delivery challan</label><input id="mv-dc" name="delivery_challan_number" value="${esc(inv.delivery_challan_number || "")}" autocomplete="off"></div>
        <div><label for="mv-veh">Vehicle</label><input id="mv-veh" name="vehicle_number" value="${esc(inv.vehicle_number || "")}" autocomplete="off"></div></div>
        <div class="row2"><div><label for="mv-tr">Transporter</label><input id="mv-tr" name="transporter_name" value="${esc(inv.transporter_name || "")}" autocomplete="off"></div>
        <div><label for="mv-ew">E-way bill number</label><input id="mv-ew" name="eway_bill_number" value="${esc(inv.eway_bill_number || "")}" autocomplete="off"></div></div>
        <label for="mv-ed">E-way bill date</label><input id="mv-ed" name="eway_bill_date" type="date" value="${esc(inv.eway_bill_date || "")}">
        <label for="mv-r">Reason for the change</label><input id="mv-r" name="reason" placeholder="Required: why is an issued invoice being amended?" autocomplete="off">
        <div class="note">Only non-financial fields can be amended. Amounts and tax are corrected with a credit or debit note.</div>
        <div class="err" role="alert"></div>
        <div class="actions"><button class="btn ghost" type="submit">Save amendment</button></div></form>`;
    else if (can("invoice:write")) foot += `<div class="note">After billing, only an Administrator can amend an issued invoice. You may request a non-financial change; an Administrator must approve it.</div>
      <form id="amendReqForm" data-id="${inv.id}" novalidate><h3>Request a post-billing change</h3>
        <div class="row2"><div><label for="ar-dc">Delivery challan</label><input id="ar-dc" name="challan" value="${esc(inv.delivery_challan_number || "")}"></div>
        <div><label for="ar-veh">Vehicle</label><input id="ar-veh" name="vehicle" value="${esc(inv.vehicle_number || "")}"></div></div>
        <label for="ar-r">Reason</label><input id="ar-r" name="reason" placeholder="Why is the change needed?" autocomplete="off">
        <div class="err" role="alert"></div>
        <div class="actions"><button class="btn ghost" type="submit">Send for Administrator approval</button></div></form>`;
    else foot += `<div class="note">After billing, only an Administrator can amend an issued invoice.</div>`;
    if (can("note:write")) foot += noteForm("cn", "Credit note") + noteForm("dn", "Debit note");
    if (can("invoice:cancel")) foot += `<form id="invCancelForm" data-id="${inv.id}" novalidate><h3>Cancel the invoice</h3>
        <div class="note">Cancelling keeps the document and its number, marked CANCELLED. It cannot be undone.</div>
        <label for="ic-r">Reason</label><input id="ic-r" name="reason" placeholder="Why is the invoice being cancelled?" autocomplete="off">
        <div class="err" role="alert"></div>
        <div class="actions"><button class="btn ghost" type="submit">Cancel invoice</button></div></form>`;
  }

  openDrawer(inv.invoice_number, `${inv.buyer_name} · ${fmtDate(inv.invoice_date)} · ${INV_STATUS[inv.status][0]}`, `
    <dl class="dl"><dt>Seller</dt><dd>${esc(inv.seller_legal_name)}<small>GSTIN ${esc(inv.seller_gstin || "not configured")}, state ${esc(inv.seller_state_code || "–")}</small></dd>
      <dt>Buyer</dt><dd>${esc(inv.buyer_name)}<small>GSTIN ${esc(inv.buyer_gstin || "unregistered")}, state ${esc(inv.buyer_state_code || "–")}</small></dd>
      <dt>Place of supply</dt><dd>${esc(inv.place_of_supply_state_code)} · ${inv.place_of_supply_kind === "intra" ? "CGST + SGST" : "IGST"}</dd>
      <dt>Sales order</dt><dd>${esc(inv.so_number || "–")}</dd>
      <dt>Stock dispatched</dt><dd>${esc(inv.lines.reduce((s, l) => s + Number(l.qty), 0))} units</dd>
      <dt>Taxable value</dt><dd>₹ ${money(inv.taxable_value)}</dd>
      <dt>CGST / SGST / IGST / Cess</dt><dd>₹ ${money(inv.cgst_total)} / ${money(inv.sgst_total)} / ${money(inv.igst_total)} / ${money(inv.cess_total)}</dd>
      <dt>Round off</dt><dd>₹ ${money(inv.round_off)}</dd>
      <dt>Invoice total</dt><dd><b>₹ ${money(inv.grand_total)}</b></dd>
      <dt>In words</dt><dd>${esc(inv.amount_in_words || "–")}</dd>
      <dt>Copy</dt><dd>${esc(inv.copy_designation)}</dd>
      <dt>Corrected so far</dt><dd>credit ₹ ${money(inv.credit_note_total)} · debit ₹ ${money(inv.debit_note_total)}</dd>
      ${inv.notes && inv.notes.length ? `<dt>Check before issuing</dt><dd><ul class="notes">${inv.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul></dd>` : ""}</dl>
    <div class="tw"><table class="dtable"><thead><tr><th>Line</th><th class="n">Qty</th><th class="n">Rate</th><th class="n">Taxable</th><th class="n">CGST</th><th class="n">SGST</th><th class="n">IGST</th><th class="n">Total</th></tr></thead><tbody>${lines}</tbody></table></div>
    ${noted.length ? `<h3>Notes on this invoice</h3><div class="tw"><table class="dtable"><thead><tr><th>Document</th><th>Date</th><th>Reason</th><th class="n">Value</th></tr></thead><tbody>${noted.map(n => `<tr><td class="strong">${esc(n.no)}</td><td>${esc(fmtDate(n.note_date))}</td><td>${esc(n.reason)}${n.returned_to_stock ? `<small>returned to ${esc(n.warehouse || "stock")}</small>` : ""}</td><td class="n">${money(n.grand_total)}</td></tr>`).join("")}</tbody></table></div>` : ""}
    ${foot}
    ${can("print:document") ? verifyPanel("invoice", inv.id) : ""}`, true);
  if (can("print:document")) loadPrintPanel("invoice", inv.id);
}

/* The panel below the invoice. It reads the print log, shows the real QR symbol
   served by /api/print/qr, and prints any of the three copy sets — the copy is
   chosen here because the invoice list's Print button issues ORIGINAL only. */
function verifyPanel(kind, id) {
  const copies = ["ORIGINAL", "DUPLICATE", "TRIPLICATE"]
    .map(c => `<option value="${c}">${c}</option>`).join("");
  return `<div class="qr-panel" style="margin-top:16px; padding:12px; background:#f8f9fa; border-radius:4px;">
    <h3>Print and verification</h3>
    <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap;">
      <img id="qrImg" class="hide" width="128" height="128" alt="QR code carrying the latest print's short code" style="background:#fff">
      <div style="flex:1; min-width:220px;">
        <p class="note" id="verifyState" role="status">Checking the print log…</p>
        <p class="note">Document: <b id="verifyDoc">–</b><br>Printed: <b id="verifyBy">–</b><br>
          Code: <b id="verifyCode">–</b><br>
          SHA-256: <b id="verifyHash" style="word-break:break-all">–</b></p>
      </div>
    </div>
    <div class="actions" style="margin:8px 0">
      <label for="printCopy" class="note">Print a copy</label>
      <select id="printCopy" aria-label="Copy set to print">${copies}</select>
      <button class="btn" type="button" data-act="print-copy" data-kind="${esc(kind)}" data-id="${esc(String(id))}">Print</button>
    </div>
    <form id="verifyForm" novalidate>
      <label for="v-code">Check a code against the print log</label>
      <input id="v-code" name="code" placeholder="Code printed on the page, e.g. PRT-000123" autocomplete="off">
      <div class="note">The PDF prints its own verification code with a QR symbol beside it. Scan that symbol or type the code here: the answer names the print, its copy and who made it, and shows the SHA-256 of the file that was served. A returned copy whose bytes differ no longer matches.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn ghost" type="submit">Check</button></div>
    </form>
  </div>`;
}

async function requestInvoiceAmendment(form) {
  const f = form.elements, err = $(".err", form);
  err.textContent = "";
  const changes = {};
  if (f.challan.value.trim()) changes.delivery_challan_number = f.challan.value.trim();
  if (f.vehicle.value.trim()) changes.vehicle_number = f.vehicle.value.trim();
  if (!f.reason.value.trim() || f.reason.value.trim().length < 3) { err.textContent = "Give a reason of at least three characters."; return; }
  if (!Object.keys(changes).length) { err.textContent = "Change at least one field."; return; }
  const res = await api(`/api/approvals/post-billing/${form.dataset.id}`, {method: "POST", body: {reason: f.reason.value.trim(), changes}});
  toast(res, res.ok ? "Change sent for Administrator approval" : "Request not sent");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}
async function saveInvoiceMovement(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements; err.textContent = "";
  if (!f.reason || f.reason.value.trim().length < 3) { err.textContent = "Give a reason of at least three characters."; return; }
  const body = {reason: f.reason.value.trim()};
  ["delivery_challan_number", "vehicle_number", "transporter_name", "eway_bill_number"].forEach(k => {
    if (f[k].value.trim() !== "") body[k] = f[k].value.trim();
  });
  if (f.eway_bill_date.value) body.eway_bill_date = f.eway_bill_date.value;
  btn.disabled = true;
  const res = await api(`/api/invoices/${form.dataset.id}/movement`, {method: "PATCH", body});
  btn.disabled = false;
  toast(res, res.ok ? "Movement details saved" : "Movement details not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await loadAll(); invDetail(form.dataset.id, null, "Movement details saved. The tax particulars did not change.");
}

async function cancelInvoice(form) {
  const err = $(".err", form), reason = form.elements.reason.value.trim(); err.textContent = "";
  if (reason.length < 3) { err.textContent = "Give a reason of at least three characters."; return; }
  const res = await api(`/api/invoices/${form.dataset.id}/cancel`, {method: "POST", body: {reason}});
  toast(res, res.ok ? "Invoice cancelled" : "Invoice not cancelled");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await loadAll(); invDetail(form.dataset.id, null, "Invoice cancelled. Its number is kept and will not be reused.");
}

async function issueNote(form, kind) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements; err.textContent = "";
  const lines = [...form.querySelectorAll("input[name^=qty-]")].map(i => ({
    invoice_line_id: Number(i.name.slice(4)), qty: i.value.trim() })).filter(l => l.qty !== "" && Number(l.qty) > 0);
  if (!lines.length) { err.textContent = "Enter the quantity to correct on at least one line."; return; }
  const reason = f.reason.value.trim();
  if (reason.length < 3) { err.textContent = "Give a reason of at least three characters."; return; }
  const body = {invoice_id: Number(form.dataset.id), reason, lines};
  if (kind === "cn" && f.return_to_stock && f.return_to_stock.value !== "")
    body.warehouse_id = Number(f.return_to_stock.value);
  btn.disabled = true;
  const res = await api(kind === "cn" ? "/api/credit-notes" : "/api/debit-notes", {method: "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? (kind === "cn" ? "Credit note issued" : "Debit note issued") : "Note not issued");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await loadAll(); invDetail(form.dataset.id, null, `${kind === "cn" ? "Credit" : "Debit"} note ${res.body[kind === "cn" ? "credit_note_number" : "debit_note_number"]} issued for ₹ ${money(res.body.grand_total)}.`);
}

/* --- approval review --- */
function apDetail(id, err) {
  const a = state.approvals.find(x => x.id === Number(id)); if (!a) return;
  const d = a.detail || {}, o = state.orders.find(x => x.id === a.record_id);
  const me = state.user.username, mine = a.requested_by === me || (o && o.created_by === me);
  let foot = "";
  if (err) foot += `<div class="err" role="alert">${esc(err)}</div>`;
  if (a.status !== "pending") {
    foot += `<div class="note">${esc((AP[a.status] || [a.status])[0])}${a.decided_by ? ` by ${esc(a.decided_by)} on ${esc(fmtStamp(a.decided_at))}` : ""}.${a.decision_reason ? ` Reason: ${esc(a.decision_reason)}` : ""}</div>`;
  } else if (mine) {
    foot += `<div class="note">You raised this request, so a different approver must decide it.</div>`;
  } else if (!a.can_decide) {
    foot += `<div class="note">Your role can view this request but not decide it.${a.reasons.includes("credit_limit") ? " Only an Administrator can decide an over-credit-limit request." : ""}</div>`;
  } else {
    foot += `<form id="decideForm" data-id="${a.id}" novalidate><h3>Your decision</h3>
      <label for="a-r">Reason</label><input id="a-r" name="reason" placeholder="Record why you are approving or rejecting" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit" value="approve">Approve</button><button class="btn ghost" type="submit" value="reject">Reject</button></div></form>`;
  }
  const detailRows = Object.entries(d).filter(([k]) => !["changes", "pending"].includes(k))
    .map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</dd>`).join("");
  const openLink = a.record_type === "sales_order"
    ? `<button class="btn ghost" type="button" data-act="open-so" data-id="${a.record_id}">Open the order</button>` : "";
  foot += `<div class="actions">${openLink}<button class="btn ghost" type="button" data-act="close">Close</button></div>`;
  openDrawer(`${a.request_type_label} ${a.request_no || ""}`.trim(), `${a.document_number || ""}${a.distributor ? ", " + a.distributor : ""} · raised by ${a.requested_by}`, `
    <dl class="dl"><dt>Status</dt><dd>${chipOf(AP, a.status)}</dd><dt>Type</dt><dd>${esc(a.request_type_label)}</dd>
      ${a.subject ? `<dt>Subject</dt><dd>${esc(a.subject)}</dd>` : ""}
      ${a.requested_dates ? `<dt>Requested dates</dt><dd>${esc(a.requested_dates)}</dd>` : ""}
      ${a.order_total != null ? `<dt>Value</dt><dd>₹ ${money(a.order_total)}</dd>` : ""}
      <dt>Why</dt><dd>${reasonChips(a.reasons)}</dd>
      ${a.reasons.includes("credit_limit") ? `<dt>Credit limit</dt><dd>₹ ${money(d.credit_limit)}</dd><dt>Already in use</dt><dd>₹ ${money(d.current_exposure)}</dd>
        <dt>In use with this request</dt><dd>₹ ${money(d.projected_exposure)}</dd>` : ""}
      ${a.reasons.includes("discount") ? `<dt>Largest discount</dt><dd>${esc(d.max_discount_pct)}% below MRP</dd>` : ""}
      ${detailRows}</dl>${foot}`, true);
}
async function decide(form, decision) {
  const err = $(".err", form), reason = form.elements.reason.value.trim(); err.textContent = "";
  if (reason.length < 3) { err.textContent = "Give a reason of at least three characters."; return; }
  const res = await api(`/api/approvals/${form.dataset.id}/decide`, {method: "POST", body: {decision, reason}});
  toast(res, res.ok ? (decision === "approve" ? "Order approved" : "Order rejected") : "Decision not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await loadAll(); apDetail(form.dataset.id);
}

/* --- distributors --- */
function distForm(id) {
  const d = id ? state.dists.find(x => x.id === Number(id)) : null;
  if (id && !d) return;
  const edit = !!d;
  const val = k => (d && d[k] != null ? esc(d[k]) : "");
  const options = (k, pairs, fallback) => pairs.map(([v, label]) =>
    `<option value="${v}"${(d ? d[k] : fallback) === v ? " selected" : ""}>${label}</option>`).join("");
  // A record carrying a value this build does not know must still show the truth:
  // without a matching option the browser would quietly submit the first one.
  const statusPairs = DIST_STATUSES.map(v => [v, DSTAT[v][1]]);
  if (edit && d.status && !DIST_STATUSES.includes(d.status)) statusPairs.unshift([d.status, d.status]);
  const note = edit
    ? (d.needs_completion
      ? `<div class="note"><b>Needs completion:</b> ${esc(distGaps(d))}. A tax document cannot be issued for this distributor until it is recorded.</div>`
      : `<div class="note">This record has everything a tax document needs. Every change is recorded with the old and the new value.</div>`)
    : `<div class="note">Pick the status the record is really in: a Draft or Pending verification distributor is kept out of new orders until it is made Active. Leave the GSTIN blank for an unregistered buyer; a registered one needs a GSTIN, and the place of supply is taken from it.</div>`;
  openDrawer(edit ? `Edit ${d.code}` : "New distributor",
    edit ? `${d.name} · ${d.territory}` : "A distributor needs a unique code, a territory and a place of supply.", `
    <form id="distForm" data-id="${edit ? d.id : ""}" novalidate>
      <div class="row2"><div><label for="x-c">Code</label><input id="x-c" name="code" value="${val("code")}" placeholder="DST-DEMO-003" autocomplete="off"${edit ? " readonly" : ""}></div>
      <div><label for="x-n">Name</label><input id="x-n" name="name" value="${val("name")}" placeholder="Demo Distributor East" autocomplete="off"></div></div>
      <div class="row2"><div><label for="x-t">Territory</label><input id="x-t" name="territory" value="${val("territory")}" placeholder="East" autocomplete="off"></div>
      ${edit ? "" : `<div><label for="x-l">Credit limit (₹)</label><input id="x-l" name="limit" inputmode="decimal" placeholder="0.00" autocomplete="off"></div>`}</div>
      <div class="row2"><div><label for="x-reg">Registration</label><select id="x-reg" name="registration_type">
        ${options("registration_type", [["unregistered", "Unregistered"], ["regular", "Regular"], ["composition", "Composition"]], "unregistered")}</select></div>
      <div><label for="x-gstin">GSTIN</label><input id="x-gstin" name="gstin" value="${val("gstin")}" placeholder="27AAACX1234Z1Z5" autocomplete="off" autocapitalize="characters" spellcheck="false"></div></div>
      <div class="row2"><div><label for="x-pan">PAN</label><input id="x-pan" name="pan" value="${val("pan")}" placeholder="Taken from the GSTIN when left blank" autocomplete="off" autocapitalize="characters" spellcheck="false"></div>
      <div><label for="x-s">State code</label><input id="x-s" name="state_code" value="${val("state_code")}" placeholder="27" autocomplete="off" maxlength="2"></div></div>
      <div class="row2"><div><label for="x-billing">Billing address</label><input id="x-billing" name="billing_address" value="${val("billing_address")}" placeholder="Street, building, locality" autocomplete="off"></div>
      <div><label for="x-shipping">Shipping address</label><input id="x-shipping" name="shipping_address" value="${val("shipping_address")}" placeholder="Street, building, locality" autocomplete="off"></div></div>
      <div class="row2"><div><label for="x-contact">Contact person</label><input id="x-contact" name="contact_person" value="${val("contact_person")}" placeholder="Contact person" autocomplete="off"></div>
      <div><label for="x-phone">Phone</label><input id="x-phone" name="phone" value="${val("phone")}" placeholder="Contact phone" autocomplete="off"></div>
      <div><label for="x-email">Email</label><input id="x-email" name="email" value="${val("email")}" placeholder="contact@email.com" autocomplete="off"></div></div>
      <div class="row2"><div><label for="x-group">Group name</label><input id="x-group" name="group_name" value="${val("group_name")}" placeholder="Group name" autocomplete="off"></div>
      <div><label for="x-terms">Payment terms (days)</label><input id="x-terms" name="payment_terms_days" value="${val("payment_terms_days")}" inputmode="numeric" placeholder="30" autocomplete="off"></div></div>
      <div class="row2"><div><label for="x-status">Status</label><select id="x-status" name="status">
        ${options("status", statusPairs, "active")}</select></div></div>
      ${note}
      ${edit ? `<div class="note">The credit limit is changed with “Change limit”, which needs <b>credit:manage</b> and a reason.</div>` : ""}
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">${edit ? "Save changes" : "Save distributor"}</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

async function saveDist(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements; err.textContent = "";
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  const text = el => (el && el.value ? el.value.trim() : "");
  const full = {
    name: text(f.name), territory: text(f.territory),
    registration_type: f.registration_type.value,
    gstin: text(f.gstin).toUpperCase() || null, pan: text(f.pan).toUpperCase() || null,
    state_code: text(f.state_code).toUpperCase() || null,
    billing_address: text(f.billing_address) || null,
    shipping_address: text(f.shipping_address) || null,
    contact_person: text(f.contact_person) || null,
    phone: text(f.phone) || null, email: text(f.email) || null,
    group_name: text(f.group_name) || null,
    payment_terms_days: text(f.payment_terms_days) === "" ? null : Number(text(f.payment_terms_days)),
    status: f.status.value
  };
  if (full.name.length < 2) { err.textContent = "Give the distributor a name of at least two characters."; return; }
  if (full.territory.length < 2) { err.textContent = "Give a territory of at least two characters."; return; }

  let body, method, path, done;
  if (id) {
    const before = state.dists.find(x => x.id === id) || {};
    const same = (a, b) => (a === null || a === "" ? null : String(a)) === (b === null || b === undefined || b === "" ? null : String(b));
    body = {};
    Object.keys(full).forEach(k => { if (!same(full[k], before[k])) body[k] = full[k]; });
    if (!Object.keys(body).length) { err.textContent = "Nothing has changed."; return; }
    method = "PATCH"; path = `/api/distributors/${id}`; done = "Distributor updated";
  } else {
    const code = text(f.code).toUpperCase();
    if (code.length < 3) { err.textContent = "Give a code of at least three characters."; return; }
    body = {...full, code};
    if (text(f.limit) !== "") body.credit_limit = Number(text(f.limit));
    method = "POST"; path = "/api/distributors"; done = "Distributor saved";
  }

  btn.disabled = true;
  const res = await api(path, {method, body});
  btn.disabled = false;
  toast(res, res.ok ? done : (id ? "Changes not saved" : "Distributor not saved"));
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}
function limitForm(id) {
  const d = state.dists.find(x => x.id === Number(id)); if (!d) return;
  openDrawer("Credit limit", `${d.code}, ${d.name}`, `
    <dl class="dl"><dt>Current limit</dt><dd>₹ ${money(d.credit_limit)}</dd><dt>In use</dt><dd>₹ ${money(d.exposure)}</dd></dl>
    <form id="limitForm" data-id="${d.id}" novalidate>
      <label for="l-v">New limit (₹)</label><input id="l-v" name="limit" inputmode="decimal" autocomplete="off">
      <label for="l-r">Reason</label><input id="l-r" name="reason" placeholder="Why is the limit changing?" autocomplete="off">
      <div class="note">Every change is recorded with the old limit, the new limit, your name and the reason. In use counts orders awaiting approval, approved and dispatched. Payments are not tracked yet.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save limit</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}
async function saveLimit(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements; err.textContent = "";
  if (f.limit.value.trim() === "" || !(Number(f.limit.value) >= 0)) { err.textContent = "Enter the new limit as zero or more."; return; }
  if (f.reason.value.trim().length < 3) { err.textContent = "Give a reason of at least three characters."; return; }
  btn.disabled = true;
  const res = await api(`/api/distributors/${form.dataset.id}/credit-limit`, {method: "PATCH", body: {credit_limit: f.limit.value.trim(), reason: f.reason.value.trim()}});
  btn.disabled = false;
  toast(res, res.ok ? "Credit limit updated" : "Limit not changed");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

/* ---------- leads and follow-ups ---------- */
const LSTAT = {new: ["New", "off"], contacted: ["Contacted", "off"], qualified: ["Qualified", "ok"], won: ["Won", "ok"], lost: ["Lost", "bad"]};
const SRC = {referral: "Referral", website: "Website", event: "Event or expo", cold_call: "Cold call", distributor: "Distributor", social: "Social media", other: "Other"};
const KIND = {created: "Created", note: "Note", call: "Call", email: "Email", meeting: "Meeting", status_change: "Status", follow_up_change: "Follow-up", owner_change: "Owner", updated: "Edited"};
const NEXT = {new: ["contacted", "qualified", "lost"], contacted: ["qualified", "lost"], qualified: ["contacted", "won", "lost"]};
const isoDay = n => { const d = new Date(); d.setDate(d.getDate() + n); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); };
const daysTo = d => Math.round((new Date(d + "T00:00:00") - new Date(isoDay(0) + "T00:00:00")) / 86400000);
const srcOpts = sel => Object.entries(SRC).map(([k, v]) => `<option value="${k}"${k === sel ? " selected" : ""}>${esc(v)}</option>`).join("");
const isClosed = l => l.status === "won" || l.status === "lost";

function followCell(l) {
  if (l.follow_up_state === "overdue") return `<span class="chip bad">Overdue ${plural(l.days_overdue, "day")}</span><small>${esc(fmtDate(l.next_follow_up))}</small>`;
  if (l.follow_up_state === "today") return `<span class="chip warn">Due today</span>`;
  if (l.follow_up_state === "upcoming") { const n = daysTo(l.next_follow_up); return `${esc(fmtDate(l.next_follow_up))}<small>${n === 1 ? "tomorrow" : "in " + plural(n, "day")}</small>`; }
  if (l.follow_up_state === "none") return `<span class="chip warn">No follow-up planned</span>`;
  return "–";
}
function leadVisible(l) {
  const f = state.ldFilter;
  if (state.ldOwner === "mine" && l.owner !== state.user.username) return false;
  if (f === "open") return !isClosed(l);
  if (f === "overdue") return l.follow_up_state === "overdue";
  if (f === "today") return l.follow_up_state === "today";
  if (f === "week") return (l.follow_up_state === "today" || l.follow_up_state === "upcoming") && daysTo(l.next_follow_up) <= 7;
  if (f === "closed") return isClosed(l);
  return true;
}
function renderLeads() {
  if (!state.user) return;
  const q = $("#ldq").value.trim().toLowerCase();
  const list = state.leads.filter(l => leadVisible(l) && (!q || [l.name, l.company, l.lead_no, l.phone, l.email].some(x => (x || "").toLowerCase().includes(q))));
  $("#ldrows").innerHTML = list.map(l => `<tr class="go" data-ld="${l.id}"><td><button class="rowbtn" data-act="open-lead" data-id="${l.id}" type="button">${esc(l.name)}</button><small>${esc(l.company || l.lead_no)}</small></td>
    <td>${esc(l.owner)}</td><td>${esc(SRC[l.source] || l.source)}</td><td>${chipOf(LSTAT, l.status)}</td><td>${followCell(l)}</td><td>${esc(fmtDay(l.last_activity_at))}</td></tr>`).join("");
  empty($("#ldempty"), !list.length, state.leads.length ? "No lead matches these filters." : "No leads yet.",
    state.leads.length ? "" : (can("lead:write") ? " Select “New lead” to add the first one." : ""));
  const n = state.leads.filter(l => l.owner === state.user.username && (l.follow_up_state === "overdue" || l.follow_up_state === "today")).length, c = $("#ldCount");
  c.textContent = n; c.classList.toggle("hide", !n); c.setAttribute("aria-label", `${n} of your follow-ups need attention`);
}

/* --- new lead --- */
async function leadForm() {
  let owners = [];
  if (can("lead:assign")) { const o = await api("/api/leads/owners"); owners = o.ok ? o.body : []; }
  openDrawer("New lead", "Every open lead has one owner and a next follow-up date.", `
    <form id="leadForm" novalidate>
      <label for="n-n">Contact name</label><input id="n-n" name="name" autocomplete="off">
      <label for="n-c">Company</label><input id="n-c" name="company" autocomplete="off">
      <div class="row2"><div><label for="n-p">Phone</label><input id="n-p" name="phone" inputmode="tel" autocomplete="off"></div>
      <div><label for="n-e">Email</label><input id="n-e" name="email" inputmode="email" autocomplete="off"></div></div>
      <div class="note">Enter a phone number or an email address. A number or address already on another lead is refused.</div>
      <div class="row2"><div><label for="n-s">Source</label><select id="n-s" name="source">${srcOpts("referral")}</select></div>
      <div><label for="n-d">First follow-up</label><input id="n-d" name="date" type="date" min="${isoDay(0)}" value="${isoDay(2)}"></div></div>
      ${owners.length ? `<label for="n-o">Owner</label><select id="n-o" name="owner">${owners.map(o => `<option value="${o.id}"${o.username === state.user.username ? " selected" : ""}>${esc(o.username)} (${esc(o.role)})</option>`).join("")}</select>` : ""}
      <label for="n-t">First note (optional)</label><input id="n-t" name="note" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save lead</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}
async function saveLead(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements; err.textContent = "";
  if (f.name.value.trim().length < 2) { err.textContent = "Enter the contact’s name."; f.name.focus(); return; }
  if (!f.phone.value.trim() && !f.email.value.trim()) { err.textContent = "Enter a phone number or an email address."; return; }
  if (!f.date.value) { err.textContent = "Choose the first follow-up date."; return; }
  const body = {name: f.name.value, company: f.company.value, phone: f.phone.value, email: f.email.value, source: f.source.value, next_follow_up: f.date.value, note: f.note.value};
  if (f.owner) body.owner_id = Number(f.owner.value);
  btn.disabled = true;
  const res = await api("/api/leads", {method: "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? `Lead ${res.body.lead_no} saved` : "Lead not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer();
  if (state.view !== "leads") location.hash = "#/leads";
  await loadAll(); leadDetail(res.body.id);
}

/* --- lead detail, history and actions --- */
async function leadDetail(id, err, panel) {
  const r = await api(`/api/leads/${id}`);
  if (!r.ok) { toast(r, "Lead not opened"); return; }
  let owners = [];
  if (panel === "owner") { const o = await api("/api/leads/owners"); owners = o.ok ? o.body : []; }
  drawLead(r.body, err || "", panel || "activity", owners);
}
function drawLead(l, err, panel, owners) {
  const me = state.user.username, closed = isClosed(l);
  const canAct = can("lead:write") && (l.owner === me || can("lead:assign"));
  const hist = l.activities.map(a => `<li><b>${esc(KIND[a.kind] || a.kind)}</b> ${esc(a.summary)}<span class="who">${esc(a.actor)}, ${esc(fmtStamp(a.created_at))}</span></li>`).join("");
  const tabs = [["activity", "Log activity"], ["status", closed ? "Reopen" : "Change status"], ["follow", "Reschedule"], ["edit", "Edit details"], ["owner", "Reassign"]]
    .filter(([k]) => !(k === "follow" && closed) && !(k === "owner" && !can("lead:assign")) && !(k === "status" && closed && !can("lead:assign")));
  if (!tabs.some(([k]) => k === panel)) panel = "activity";
  let form = "";
  const tail = `<div class="err" role="alert">${esc(err)}</div>`;
  if (panel === "activity") {
    form = `<form id="actForm" data-id="${l.id}" novalidate>
      <label for="ac-k">What happened</label>
      <select id="ac-k" name="kind">${closed ? "" : `<option value="call">Call</option><option value="email">Email</option><option value="meeting">Meeting</option>`}<option value="note">${closed ? "Note" : "Note only"}</option></select>
      <label for="ac-s">Summary</label><input id="ac-s" name="summary" placeholder="What was said or agreed" autocomplete="off">
      ${closed ? "" : `<div class="row2"><div><label for="ac-d">Next follow-up</label><input id="ac-d" name="date" type="date" min="${isoDay(0)}" value="${l.next_follow_up && daysTo(l.next_follow_up) > 0 ? l.next_follow_up : isoDay(3)}"></div>
      <div><label for="ac-x">&nbsp;</label><label class="chk" for="ac-x"><input id="ac-x" type="checkbox" name="clear" style="width:auto;margin-right:8px">No follow-up needed</label></div></div>
      <div class="note">After a call, email or meeting, say what happens next.</div>`}
      ${tail}<div class="actions"><button class="btn" type="submit">Save activity</button></div></form>`;
  } else if (panel === "status") {
    const opts = closed ? ["contacted"] : NEXT[l.status];
    form = `<form id="lstatusForm" data-id="${l.id}" data-closed="${closed ? 1 : 0}" novalidate>
      <label for="ls-s">${closed ? "Reopen as" : "Move to"}</label>
      <select id="ls-s" name="status">${opts.map(s => `<option value="${s}">${esc(LSTAT[s][0])}</option>`).join("")}</select>
      <label for="ls-r">Reason <span class="hint">(needed for lost${closed ? " and for reopening" : ""})</span></label><input id="ls-r" name="reason" autocomplete="off">
      ${closed ? `<label for="ls-d">New follow-up date</label><input id="ls-d" name="date" type="date" min="${isoDay(0)}" value="${isoDay(2)}">` : `<div class="note">Won and lost close the lead and clear its follow-up date.</div>`}
      ${tail}<div class="actions"><button class="btn" type="submit">Save status</button></div></form>`;
  } else if (panel === "follow") {
    form = `<form id="lfuForm" data-id="${l.id}" novalidate>
      <label for="lf-d">New follow-up date</label><input id="lf-d" name="date" type="date" min="${isoDay(0)}" value="${l.next_follow_up && daysTo(l.next_follow_up) > 0 ? l.next_follow_up : isoDay(3)}">
      <label for="lf-r">Reason</label><input id="lf-r" name="reason" placeholder="Why is it moving?" autocomplete="off">
      <label class="chk" for="lf-x"><input id="lf-x" type="checkbox" name="clear" style="width:auto;margin-right:8px">Clear the follow-up (a reason is needed)</label>
      ${tail}<div class="actions"><button class="btn" type="submit">Save date</button></div></form>`;
  } else if (panel === "edit") {
    form = `<form id="leditForm" data-id="${l.id}" novalidate>
      <label for="le-n">Contact name</label><input id="le-n" name="name" value="${esc(l.name)}" autocomplete="off">
      <label for="le-c">Company</label><input id="le-c" name="company" value="${esc(l.company || "")}" autocomplete="off">
      <div class="row2"><div><label for="le-p">Phone</label><input id="le-p" name="phone" value="${esc(l.phone || "")}" autocomplete="off"></div>
      <div><label for="le-e">Email</label><input id="le-e" name="email" value="${esc(l.email || "")}" autocomplete="off"></div></div>
      <label for="le-s">Source</label><select id="le-s" name="source">${srcOpts(l.source)}</select>
      ${tail}<div class="actions"><button class="btn" type="submit">Save details</button></div></form>`;
  } else if (panel === "owner") {
    form = `<form id="lownerForm" data-id="${l.id}" novalidate>
      <label for="lo-o">New owner</label>
      <select id="lo-o" name="owner">${owners.filter(o => o.id !== l.owner_id).map(o => `<option value="${o.id}">${esc(o.username)} (${esc(o.role)})</option>`).join("")}</select>
      <label for="lo-r">Reason</label><input id="lo-r" name="reason" placeholder="Why is it changing hands?" autocomplete="off">
      ${tail}<div class="actions"><button class="btn" type="submit">Reassign</button></div></form>`;
  }
  const acts = canAct
    ? `<div class="seg compact" role="group" aria-label="Lead actions">${tabs.map(([k, t]) => `<button type="button" data-act="lead-panel" data-id="${l.id}" data-panel="${k}" aria-pressed="${k === panel}">${esc(t)}</button>`).join("")}</div>${form}`
    : `<div class="note">This lead belongs to ${esc(l.owner)}. Only the owner or an administrator can change it.</div>`;
  openDrawer(l.name, `${l.lead_no}${l.company ? ", " + l.company : ""}`, `
    <dl class="dl"><dt>Status</dt><dd>${chipOf(LSTAT, l.status)}${l.closed_reason ? ` <small>${esc(l.closed_reason)}</small>` : ""}</dd>
      <dt>Owner</dt><dd>${esc(l.owner)}</dd><dt>Source</dt><dd>${esc(SRC[l.source] || l.source)}</dd>
      <dt>Phone</dt><dd>${esc(l.phone || "–")}</dd><dt>Email</dt><dd>${esc(l.email || "–")}</dd>
      <dt>Next follow-up</dt><dd>${closed ? "–" : l.follow_up_state === "none" ? followCell(l) : esc(fmtDate(l.next_follow_up)) + " " + (l.follow_up_state === "overdue" || l.follow_up_state === "today" ? followCell(l).replace(/<small>.*?<\/small>/, "") : "")}</dd></dl>
    <h3>Actions</h3>${acts}
    <h3>History</h3><ol class="tl">${hist}</ol>`, true);
}
async function leadCall(form, method, path, body, okLabel) {
  const err = $(".err", form), btn = $("button[type=submit]", form); err.textContent = "";
  btn.disabled = true;
  const res = await api(path, {method, body});
  btn.disabled = false;
  toast(res, res.ok ? okLabel : "Not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await loadAll(); leadDetail(form.dataset.id);
}
function saveActivity(form) {
  const f = form.elements, err = $(".err", form), contact = f.kind.value !== "note";
  if (f.summary.value.trim().length < 3) { err.textContent = "Write a short summary (three characters or more)."; f.summary.focus(); return; }
  if (contact && f.date && !f.date.value && !f.clear.checked) { err.textContent = "Say what happens next: choose a follow-up date, or tick “No follow-up needed”."; return; }
  const body = {kind: f.kind.value, summary: f.summary.value};
  if (f.clear && f.clear.checked) body.clear_follow_up = true; else if (f.date && f.date.value && contact) body.next_follow_up = f.date.value;
  leadCall(form, "POST", `/api/leads/${form.dataset.id}/activities`, body, "Activity saved");
}
function saveLeadStatus(form) {
  const f = form.elements, err = $(".err", form), reopen = form.dataset.closed === "1";
  if ((f.status.value === "lost" || reopen) && f.reason.value.trim().length < 3) { err.textContent = reopen ? "Give a reason for reopening." : "Give the reason the lead was lost."; return; }
  const body = {status: f.status.value, reason: f.reason.value};
  if (reopen) body.next_follow_up = f.date.value;
  leadCall(form, "POST", `/api/leads/${form.dataset.id}/status`, body, "Status updated");
}
function saveFollowUp(form) {
  const f = form.elements, err = $(".err", form), clear = f.clear.checked;
  if (clear && f.reason.value.trim().length < 3) { err.textContent = "Give a reason for clearing the follow-up."; return; }
  if (!clear && !f.date.value) { err.textContent = "Choose the new date."; return; }
  leadCall(form, "POST", `/api/leads/${form.dataset.id}/follow-up`, {next_follow_up: clear ? null : f.date.value, reason: f.reason.value}, "Follow-up updated");
}
function saveLeadEdit(form) {
  const f = form.elements;
  leadCall(form, "PATCH", `/api/leads/${form.dataset.id}`, {name: f.name.value, company: f.company.value, phone: f.phone.value, email: f.email.value, source: f.source.value}, "Details saved");
}
function saveOwner(form) {
  const f = form.elements, err = $(".err", form);
  if (!f.owner.value) { err.textContent = "Choose the new owner."; return; }
  if (f.reason.value.trim().length < 3) { err.textContent = "Give a reason of at least three characters."; return; }
  leadCall(form, "POST", `/api/leads/${form.dataset.id}/owner`, {owner_id: Number(f.owner.value), reason: f.reason.value}, "Lead reassigned");
}

/* ---------- reports and exports ---------- */
const RSTATUS = {...Object.fromEntries(Object.entries(SO).map(([k, v]) => [k, v[0]])), ...Object.fromEntries(Object.entries(LSTAT).map(([k, v]) => [k, v[0]])),
                 ...Object.fromEntries(Object.entries(PO_STATUS).map(([k, v]) => [k, v[0]])),
                 open: "Open", received: "Received", active: "Active", on_hold: "On hold",
                 blocked: "Blocked", cancelled: "Cancelled", partially_received: "Part received"};
const RNUM = new Set(["money", "qty", "int", "pct"]);
function rpCell(v, col) {
  if (v === null || v === undefined || v === "") return "–";
  if (col.type === "money") return money(v);
  if (col.type === "qty") return qty(v);
  if (col.type === "int") return String(v);
  if (col.type === "pct") return Number(v).toFixed(1) + "%";
  if (col.type === "date") return esc(fmtDate(v));
  return esc(col.key === "status" ? (RSTATUS[v] || String(v).replace(/_/g, " ")) : v);
}
const rpUnit = (v, unit) => unit === "money" ? "₹ " + money(v) : unit === "units" ? qty(v) : String(v);
function rpQuery(c) {
  const q = [];
  if (!c || c.kind === "period") {
    if (state.rp.from) q.push("from=" + state.rp.from);
    if (state.rp.to) q.push("to=" + state.rp.to);
  }
  (c && c.filters ? c.filters : []).forEach(k => {
    const v = state.rp.filters[k];
    if (v !== "" && v !== undefined && v !== null) q.push(`${k}=${encodeURIComponent(v)}`);
  });
  return q.length ? "?" + q.join("&") : "";
}
async function rpFilterOptions() {
  if (state.rp.opts) return state.rp.opts;
  const [e, b] = await Promise.all([api("/api/hr/employees?page_size=200"), api("/api/hr/branches")]);
  const emps = e.ok ? e.body : [];
  const branches = b.ok ? b.body : [];
  state.rp.opts = {
    employee_id: emps.map(x => ({v: x.id, t: `${x.full_name} (${x.code})`})),
    department: [...new Set(emps.map(x => x.department).filter(Boolean))].sort()
      .map(d => ({v: d, t: d})),
    branch_id: branches.map(x => ({v: x.id, t: x.name})),
  };
  return state.rp.opts;
}
async function drawRpFilters(c) {
  const wrap = $("#rpFilters"), want = (c && c.filters) || [];
  wrap.classList.toggle("hide", !want.length);
  if (!want.length) return;
  const opts = await rpFilterOptions();
  const fill = (sel, key, label) => {
    const el = $(sel);
    el.classList.toggle("hide", !want.includes(key));
    el.innerHTML = `<option value="">${esc(label)}</option>` +
      opts[key].map(o => `<option value="${esc(o.v)}">${esc(o.t)}</option>`).join("");
    el.value = state.rp.filters[key] || "";
  };
  fill("#rpEmployee", "employee_id", "All employees");
  fill("#rpDepartment", "department", "All departments");
  fill("#rpBranch", "branch_id", "All branches");
}
function drawRpTabs() {
  const q = state.rpSearch.toLowerCase(), cat = state.rpCategory;
  const list = state.rp.cat.filter(c => (!cat || c.category === cat) &&
    (!q || (c.title + " " + c.description + " " + c.category).toLowerCase().includes(q)));
  $("#rpTabs").innerHTML = list.map(c => `<button type="button" data-rp="${esc(c.key)}" aria-pressed="${c.key === state.rp.key}">${esc(c.title)}<small>${esc(c.category)}</small></button>`).join("")
    || `<span class="muted">No report matches this search.</span>`;
  const sel = $("#rpCategory");
  if (sel) {
    const cats = [...new Set(state.rp.cat.map(c => c.category))];
    const keep = sel.value;
    sel.innerHTML = `<option value="">All categories</option>` + cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    sel.value = cats.includes(keep) ? keep : "";
  }
}
function markPreset(p) { $$("[data-rpp]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.rpp === p))); }
function setPreset(p) {
  const t = new Date(), iso = d => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  let from = "", to = "";
  if (p === "month") from = iso(new Date(t.getFullYear(), t.getMonth(), 1));
  else if (p === "30") from = isoDay(-30);
  else if (p === "fy") from = (t.getMonth() >= 3 ? t.getFullYear() : t.getFullYear() - 1) + "-04-01";
  state.rp.from = from; state.rp.to = to; $("#rpFrom").value = from; $("#rpTo").value = to;
  markPreset(p); loadReport();
}
async function openReports() {
  const r = await api("/api/reports");
  state.rp.cat = r.ok ? r.body : [];
  state.rpPage = 1;
  if (!state.rp.cat.some(c => c.key === state.rp.key)) state.rp.key = state.rp.cat.length ? state.rp.cat[0].key : null;
  drawRpTabs(); loadReport();
}
async function loadReport() {
  const c = state.rp.cat.find(x => x.key === state.rp.key);
  if (!c) { $("#rpDesc").textContent = "No reports are available to your role."; $("#rpBody").innerHTML = ""; return; }
  $("#rpDesc").textContent = c.description;
  $("#rpPeriod").classList.toggle("hide", c.kind !== "period");
  drawRpFilters(c);
  const tok = ++state.rp.tok;
  const qs = rpQuery(c);
  const pageQs = `page=${state.rpPage}&page_size=100`;
  const res = await api(`/api/reports/${c.key}${qs}${qs ? "&" : "?"}${pageQs}`);
  if (tok !== state.rp.tok || state.view !== "reports") return;          // a newer request or another page took over
  if (!res.ok) { toast(res, "Report not loaded"); return; }
  state.rp.data = res.body; drawReport(c, res.body);
}
function drawReport(c, r) {
  const bad = r.checks.filter(k => !k.ok);
  const when = r.kind === "period" ? (r.period_from || r.period_to ? `${r.period_from ? fmtDate(r.period_from) : "the start"} to ${r.period_to ? fmtDate(r.period_to) : "today"}` : "all dates") : `as at ${fmtDate(r.as_at)}`;
  const link = (fmt, tkey) => `/api/reports/${r.key}/export?format=${fmt}${tkey ? "&table=" + tkey : ""}${rpQuery(c).replace("?", "&")}`;
  const pager = t => {
    const pages = Math.max(1, Math.ceil((t.total_rows || t.rows.length) / (t.page_size || 100)));
    if (pages <= 1) return "";
    return `<div class="actions" style="padding:8px 18px"><button class="btn ghost sm" type="button" data-act="rp-page" data-page="${Math.max(1, (t.page || 1) - 1)}"${t.page <= 1 ? " disabled" : ""}>Previous</button>
      <span class="muted">Page ${t.page} of ${pages} · ${t.total_rows} rows</span>
      <button class="btn ghost sm" type="button" data-act="rp-page" data-page="${Math.min(pages, (t.page || 1) + 1)}"${t.page >= pages ? " disabled" : ""}>Next</button></div>`;
  };
  const banner = r.reconciled
    ? `<span class="chip ok">All ${r.checks.length} checks agree with the records</span>`
    : `<span class="chip bad">${bad.length} of ${r.checks.length} checks differ. Do not rely on these figures until they are explained.</span>`;
  const tables = r.tables.map(t => {
    const th = t.columns.map(k => `<th${RNUM.has(k.type) ? ' class="n"' : ""}>${esc(k.label)}</th>`).join("");
    const empty = !t.rows.length;
    const body = empty
      ? `<tr><td colspan="${Math.max(t.columns.length, 1)}" class="empty-row">No records for this period.</td></tr>`
      : t.rows.map(x => `<tr>${t.columns.map(k => `<td${RNUM.has(k.type) ? ' class="n"' : ""}>${rpCell(x[k.key], k)}</td>`).join("")}</tr>`).join("");
    const foot = !empty && t.totals ? `<tfoot><tr>${t.columns.map(k => `<td${RNUM.has(k.type) ? ' class="n"' : ""}>${k === t.columns[0] ? "Total" : rpCell(t.totals[k.key], k)}</td>`).join("")}</tr></tfoot>` : "";
    const head = th ? `<thead><tr>${th}</tr></thead>` : "";
    return `<div class="panel flush rp"><div class="panel-h" style="padding:14px 18px 0"><h3>${esc(t.title)}</h3>${c.can_export ? `<span><a class="link-btn" href="${link("csv", t.key)}" download>CSV</a> · <a class="link-btn" href="${link("pdf", t.key)}" download>PDF</a></span>` : ""}</div>
      <div class="tw"><table>${head}<tbody>${body}</tbody>${foot}</table></div>${pager(t)}</div>`;
  }).join("");
  const checks = r.checks.map(k => `<li class="${k.ok ? "ok" : "bad"}"><span class="mark" aria-hidden="true">${k.ok ? "✓" : "✗"}</span>
      <div><b>${esc(k.name)}</b><small>${esc(k.report_label)}: ${esc(rpUnit(k.report_value, k.unit))} &nbsp;|&nbsp; ${esc(k.record_label)}: ${esc(rpUnit(k.record_value, k.unit))}</small></div>
      <span class="chip ${k.ok ? "ok" : "bad"}">${k.ok ? "Agrees" : "Differs"}</span></li>`).join("");
  $("#rpBody").innerHTML = `
    <div class="panel"><div class="rp-head"><div><h3 style="margin:0">${esc(r.title)}</h3><small style="color:var(--mute)">Figures ${esc(when)}</small></div>
      <div>${c.can_export ? `<a class="btn" href="${link("xlsx")}" download>Download Excel (all tables)</a>` : `<small style="color:var(--mute)">Your role can view reports but not download them.</small>`}</div></div>
      <div style="margin-top:10px">${banner}</div></div>
    ${tables}
    <div class="panel"><h3>How these totals tie back to the records</h3>
      <p class="sub" style="margin:2px 0 0">Each figure below is recomputed from the underlying records by a separate query and compared with the report.</p><ul class="checks">${checks}</ul></div>
    <div class="panel"><h3>What this report leaves out</h3><ul class="notes">${r.limitations.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>`;
}

/* ---------- users, roles and employees (Module Phase 1) ---------- */
const roleLabel = id => { const r = state.roles.find(x => x.id === id); return r ? r.name : "–"; };
const employeeName = id => { const e = state.employees.find(x => x.id === id); return e ? `${e.full_name} (${e.code})` : "–"; };

function renderUsers() {
  $("#urows").innerHTML = state.users.map(u => `<tr>
    <td class="strong">${esc(u.username)}</td>
    <td>${esc(roleLabel(u.role_id) === "–" ? u.role : roleLabel(u.role_id))}</td>
    <td>${u.employee_id ? esc(employeeName(u.employee_id)) : "–"}</td>
    <td><span class="chip ${u.is_active ? "ok" : "off"}">${u.is_active ? "Active" : "Inactive"}</span></td>
    <td>${u.locked ? '<span class="chip bad">Locked</span>' : u.must_change_password ? '<span class="chip warn">Temporary</span>' : '<span class="chip ok">Set</span>'}</td>
    <td class="rowacts"><button class="btn ghost sm" type="button" data-act="change-role" data-id="${u.id}">Change role</button>
      <button class="btn ghost sm" type="button" data-act="reset-pw" data-id="${u.id}">Reset password</button>
      <button class="btn ghost sm" type="button" data-act="toggle-user" data-id="${u.id}" data-active="${u.is_active}">${u.is_active ? "Deactivate" : "Activate"}</button></td></tr>`).join("");
  empty($("#uempty"), !state.users.length, "No logins are visible.", can("user:manage") ? " Select “New user” to create the first one." : "");
  $("#userNote").textContent = state.users.length ? `${state.users.filter(u => u.is_active).length} active` : "";

  $("#rrows").innerHTML = state.roles.map(r => `<tr>
    <td><span class="strong">${esc(r.name)}</span><small>${esc(r.display_name)}</small></td>
    <td class="n">${r.permissions.length}</td><td class="n">${r.user_count}</td>
    <td><span class="chip ${r.is_system ? "ok" : "off"}">${r.is_system ? "Built-in" : "Custom"}</span></td>
    <td class="rowacts"><button class="btn ghost sm" type="button" data-act="edit-role" data-id="${r.id}">Edit permissions</button></td></tr>`).join("");
  empty($("#rempty"), !state.roles.length, "No roles are visible.", "");

  $("#erows").innerHTML = state.employees.map(e => `<tr>
    <td class="strong">${esc(e.code)}</td><td>${esc(e.full_name)}</td>
    <td>${esc(e.designation || "–")}</td><td>${esc(e.department || "–")}</td>
    <td>${esc(e.username || "Not linked")}</td>
    <td><span class="chip ${e.status === "active" ? "ok" : "off"}">${esc(e.status)}</span></td>
    <td class="rowacts"><button class="btn ghost sm" type="button" data-act="edit-emp" data-id="${e.id}">Edit</button></td></tr>`).join("");
  empty($("#eempty"), !state.employees.length, "No employees yet.", can("employee:write") ? " Select “New employee” to add the first one." : "");
}

function showSecret(title, sub, username, password) {
  openDrawer(title, sub, `<div class="note"><b>Username:</b> ${esc(username)}<br><b>Temporary password:</b> <code>${esc(password)}</code></div>
    <p class="sub">It is stored only as a hash and cannot be shown again. A reset issues a new one and ends every open session.</p>
    <div class="actions"><button class="btn" type="button" data-act="close">I have saved it</button></div>`);
}

function userForm() {
  const active = state.employees.filter(e => !e.user_id && e.status === "active");
  openDrawer("New user", "A temporary password is generated and shown once. The user must change it at first sign-in.", `
    <form id="userForm" novalidate>
      <label for="nu-emp">Employee (active, no login)</label>
      <select id="nu-emp" name="employee_id">
        <option value="">— Not linked —</option>
        ${active.map(e => `<option value="${e.id}">${esc(e.code)} – ${esc(e.full_name)}</option>`).join("")}
      </select>
      <label for="nu-name">Username</label>
      <select id="nu-name" name="username" disabled><option value="">Choose an employee first</option></select>
      <input id="nu-name-manual" name="username_manual" autocomplete="off" placeholder="e.g. priya.sales" class="hide">
      <label for="nu-role">Role</label><select id="nu-role" name="role">${state.roles.map(r => `<option value="${r.id}">${esc(r.display_name)} (${esc(r.name)})</option>`).join("")}</select>
      <div class="note">Usernames are matched case-insensitively. A password needs 12+ characters and three of: lowercase, uppercase, digits, symbols. Only active employees without a login are listed; choose “Not linked” to type a username.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Create user</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
  const emp = $("#nu-emp"), name = $("#nu-name"), manual = $("#nu-name-manual");
  const slug = s => (s || "").toLowerCase().replace(/[^a-z0-9._-]+/g, ".").replace(/^[._-]+|[._-]+$/g, "");
  const taken = new Set(state.users.map(u => u.username.toLowerCase()));
  const candidates = e => [...new Set([
    e.email ? slug(e.email.split("@")[0]) : "",
    slug(e.code),
    slug(e.full_name)
  ].filter(u => u.length >= 3 && !taken.has(u)))].slice(0, 4);
  const sync = () => {
    const e = active.find(x => x.id === Number(emp.value));
    const opts = e ? candidates(e) : [];
    if (!opts.length) {
      name.disabled = true;
      name.innerHTML = `<option value="">Type a username below</option>`;
      manual.classList.remove("hide"); manual.disabled = false;
      return;
    }
    name.disabled = false;
    name.innerHTML = opts.map(u => `<option value="${esc(u)}">${esc(u)}</option>`).join("");
    manual.classList.add("hide"); manual.disabled = true; manual.value = "";
  };
  emp.addEventListener("change", sync);
  sync();
}
async function saveUser(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = ""; btn.disabled = true;
  const sel = form.elements.username, manual = form.elements.username_manual;
  const username = (!sel.disabled && sel.value ? sel.value : manual.value).trim();
  const employee_id = form.elements.employee_id.value || null;
  if (!username) {
    btn.disabled = false;
    err.textContent = "Choose an employee or type a username.";
    return;
  }
  const res = await api("/api/users", {method: "POST", body: {username, role: form.elements.role.value, employee_id}});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, "User created");
  showSecret(`User ${res.body.username} created`, "Give this temporary password to the user directly. It is shown once.", res.body.username, res.body.temporary_password);
  loadAll();
}

function changeRoleForm(id) {
  const u = state.users.find(x => x.id === Number(id));
  if (!u) return;
  openDrawer(`Change role: ${u.username}`, "Permissions change on the user's next request. You cannot change your own role.", `
    <form id="chroleForm" data-id="${u.id}" novalidate>
      <label for="cr-role">Role</label><select id="cr-role" name="role">${state.roles.map(r => `<option value="${r.id}" ${r.id === u.role_id ? "selected" : ""}>${esc(r.display_name)} (${esc(r.name)})</option>`).join("")}</select>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save role</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}
async function saveChangeRole(form) {
  const res = await api(`/api/users/${form.dataset.id}`, {method: "PATCH", body: {role: new FormData(form).get("role")}});
  toast(res, res.ok ? "Role changed" : "Role not changed");
  if (res.ok) { closeDrawer(); loadAll(); } else $(".err", form).textContent = detail(res.body);
}

function resetPwForm(id) {
  const u = state.users.find(x => x.id === Number(id));
  if (!u) return;
  openDrawer(`Reset password: ${u.username}`, "A new temporary password is shown once, must be changed at the next sign-in, and every open session ends.", `
    <form id="resetpwForm" data-id="${u.id}" novalidate>
      <div class="note">A reset also clears a lockout.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Reset the password</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}
async function saveResetPw(form) {
  const res = await api(`/api/users/${form.dataset.id}/reset-password`, {method: "POST"});
  if (!res.ok) { $(".err", form).textContent = detail(res.body); return; }
  toast(res, "Password reset");
  showSecret(`New password for ${res.body.username}`, "This is shown once. Every older session has been ended.", res.body.username, res.body.temporary_password);
  loadAll();
}
async function toggleUser(id, active) {
  const res = await api(`/api/users/${id}`, {method: "PATCH", body: {is_active: active !== "true"}});
  toast(res, res.ok ? (active === "true" ? "User deactivated" : "User activated") : "User not changed");
  if (res.ok) loadAll();
}

function roleForm(roleId) {
  const role = roleId ? state.roles.find(r => r.id === Number(roleId)) : null;
  const matrix = state.permCatalog.map(g => `<div class="permgroup"><b>${esc(g.module)}</b>${g.items.map(i =>
    `<label class="check"><input type="checkbox" name="perm" value="${esc(i.key)}" ${role && role.permissions.includes(i.key) ? "checked" : ""}> <span>${esc(i.key)}<small>${esc(i.description)}</small></span></label>`).join("")}</div>`).join("");
  openDrawer(role ? `Edit role: ${role.name}` : "New role", role ? "Built-in roles keep their name; permissions can be adjusted. The last active administrator cannot lose user:manage." : "Custom roles are enforced by the server exactly like the built-in ones.", `
    <form id="roleForm" data-id="${role ? role.id : ""}" novalidate>
      ${role ? "" : `<label for="nr-name">Role name</label><input id="nr-name" name="name" autocomplete="off" placeholder="e.g. accounts">`}
      <label for="nr-label">Display name</label><input id="nr-label" name="display_name" autocomplete="off" value="${role ? esc(role.display_name) : ""}" placeholder="e.g. Accounts">
      <div class="matrix">${matrix}</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">${role ? "Save permissions" : "Create role"}</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}
async function saveRole(form) {
  const perms = $$('input[name="perm"]:checked', form).map(x => x.value);
  const f = new FormData(form);
  const body = {permissions: perms, display_name: f.get("display_name") || null};
  const id = form.dataset.id;
  const res = id
    ? await api(`/api/roles/${id}`, {method: "PATCH", body})
    : await api("/api/roles", {method: "POST", body: {...body, name: f.get("name")}});
  toast(res, res.ok ? "Role saved" : "Role not saved");
  if (res.ok) { closeDrawer(); loadAll(); } else $(".err", form).textContent = detail(res.body);
}

async function employeeForm(empId) {
  const rich = can("hr:write");
  let e = empId ? state.employees.find(x => x.id === Number(empId)) : null;
  if (empId && can("hr:read")) {
    // The settings list omits the HR master fields; read the full record so the
    // same form edits it identically from either entry point.
    const full = await api(`/api/hr/employees/${empId}`);
    if (full.ok) e = full.body;
  }
  const [b, o, s] = rich
    ? await Promise.all([api("/api/hr/branches"), api("/api/hr/offices"), api("/api/hr/shifts")])
    : [null, null, null];
  const opts = (res, sel, label) => (res && res.ok ? res.body : [])
    .map(v => `<option value="${v.id}"${sel === v.id ? " selected" : ""}>${esc(label(v))}</option>`).join("");
  const hrFields = rich ? `
      <div class="row2"><div><label for="ne-join">Joining date</label><input id="ne-join" name="joining_date" type="date" value="${e && e.joining_date ? e.joining_date : ""}"></div>
      <div><label for="ne-type">Employment type</label><input id="ne-type" name="employment_type" autocomplete="off" value="${e && e.employment_type ? esc(e.employment_type) : ""}" placeholder="Full time / Contract"></div></div>
      <div class="row2"><div><label for="ne-branch">Branch</label><select id="ne-branch" name="branch_id"><option value="">—</option>${opts(b, e ? e.branch_id : null, v => v.name)}</select></div>
      <div><label for="ne-office">Office / work location</label><select id="ne-office" name="office_id"><option value="">—</option>${opts(o, e ? e.office_id : null, v => v.name)}</select></div></div>
      <div class="row2"><div><label for="ne-shift">Shift</label><select id="ne-shift" name="shift_id"><option value="">—</option>${opts(s, e ? e.shift_id : null, v => v.name)}</select></div>
      <div><label for="ne-status">Status</label><select id="ne-status" name="status"><option value="active" ${!e || e.status === "active" ? "selected" : ""}>Active</option><option value="inactive" ${e && e.status === "inactive" ? "selected" : ""}>Inactive</option></select></div></div>`
    : `<label for="ne-status">Status</label><select id="ne-status" name="status"><option value="active" ${!e || e.status === "active" ? "selected" : ""}>Active</option><option value="inactive" ${e && e.status === "inactive" ? "selected" : ""}>Inactive</option></select>`;
  openDrawer(e ? `Employee ${e.code}` : "New employee",
    "One employee master for HR and settings. Employees are deactivated, never deleted.", `
    <form id="empForm" data-id="${e ? e.id : ""}" novalidate>
      <div class="row2"><div><label for="ne-code">Employee code</label><input id="ne-code" name="code" autocomplete="off" value="${e ? esc(e.code) : ""}" ${e ? "readonly" : ""}></div>
      <div><label for="ne-name">Full name</label><input id="ne-name" name="full_name" autocomplete="off" value="${e ? esc(e.full_name) : ""}"></div></div>
      <div class="row2"><div><label for="ne-dept">Department</label><input id="ne-dept" name="department" autocomplete="off" value="${e && e.department ? esc(e.department) : ""}"></div>
      <div><label for="ne-des">Designation</label><input id="ne-des" name="designation" autocomplete="off" value="${e && e.designation ? esc(e.designation) : ""}"></div></div>
      <div class="row2"><div><label for="ne-phone">Phone</label><input id="ne-phone" name="phone" autocomplete="off" value="${e && e.phone ? esc(e.phone) : ""}"></div>
      <div><label for="ne-email">Email</label><input id="ne-email" name="email" autocomplete="off" value="${e && e.email ? esc(e.email) : ""}"></div></div>
      ${hrFields}
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">${e ? "Save employee" : "Create employee"}</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}
async function saveEmployee(form) {
  const f = form.elements, err = $(".err", form), id = form.dataset.id || null, rich = can("hr:write");
  err.textContent = "";
  const body = {full_name: f.full_name.value.trim(), department: f.department.value || null,
                designation: f.designation.value || null, phone: f.phone.value || null,
                email: f.email.value || null, status: f.status.value};
  if (body.full_name.length < 2) { err.textContent = "Enter the employee's full name."; return; }
  if (!id) body.code = f.code.value.trim();
  if (!id && !body.code) { err.textContent = "Enter an employee code."; return; }
  if (rich) {
    body.joining_date = f.joining_date.value || null;
    body.employment_type = f.employment_type.value || null;
    body.branch_id = f.branch_id.value ? Number(f.branch_id.value) : null;
    body.office_id = f.office_id.value ? Number(f.office_id.value) : null;
    body.shift_id = f.shift_id.value ? Number(f.shift_id.value) : null;
  }
  const base = rich ? "/api/hr/employees" : "/api/employees";
  const res = await api(id ? `${base}/${id}` : base, {method: id ? "PATCH" : "POST", body});
  toast(res, res.ok ? "Employee saved" : "Employee not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer();
  await loadAll();
  if (can("hr:read")) await openHr();
}

/* ---------- audit trail ---------- */
async function openAudit() {
  const meta = await api("/api/audit/actions");
  if (meta.ok) {
    state.audit.actions = meta.body.actions;
    state.audit.actors = meta.body.actors;
    const a = $("#audAction"), keep = a.value;
    a.innerHTML = `<option value="">All actions</option>` + state.audit.actions.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
    a.value = keep;
    const u = $("#audActor"), keepU = u.value;
    u.innerHTML = `<option value="">All users</option>` + state.audit.actors.map(x => `<option value="${x.id}">${esc(x.username)}</option>`).join("");
    u.value = keepU;
  }
  $("#audExport").classList.toggle("hide", !can("report:export"));
  await loadAudit();
}
function audQuery(withLimit) {
  const q = new URLSearchParams();
  if ($("#audAction").value) q.set("action", $("#audAction").value);
  if ($("#audActor").value) q.set("actor_id", $("#audActor").value);
  if ($("#audFrom").value) q.set("from", $("#audFrom").value);
  if ($("#audTo").value) q.set("to", $("#audTo").value);
  if (withLimit) q.set("limit", "200");
  const s = q.toString();
  return s ? "?" + s : "";
}
async function loadAudit() {
  const res = await api("/api/audit" + audQuery(true));
  if (!res.ok) { toast(res, "Audit trail not loaded"); return; }
  state.audit.rows = res.body.rows;
  state.audit.total = res.body.total;
  $("#audExport").href = "/api/audit/export" + audQuery(false);
  renderAudit();
}
function renderAudit() {
  $("#audrows").innerHTML = state.audit.rows.map(r => {
    const d = JSON.stringify(r.changes || {});
    return `<tr><td>${esc(fmtStamp(r.at))}</td><td>${esc(r.actor)}</td>
      <td><span class="chip off">${esc(r.action)}</span></td><td><code>${esc(r.record)}</code></td>
      <td><small>${esc(d.length > 180 ? d.slice(0, 177) + "…" : d)}</small></td></tr>`;
  }).join("");
  empty($("#audempty"), !state.audit.rows.length, "Nothing matches these filters.", "");
  $("#audNote").textContent = state.audit.total ? `Showing ${state.audit.rows.length} of ${state.audit.total}` : "";
}

/* ---------- tax and discounts (Module Phase 3) ---------- */
const taxNum = v => { const n = Number(String(v).trim()); return Number.isFinite(n) ? n : 0; };
const stateOptions = sel => (state.tax.states || [])
  .map(s => `<option value="${esc(s.code)}"${s.code === sel ? " selected" : ""}>${esc(s.name)} (${esc(s.code)})${s.is_union_territory ? " — UT" : ""}</option>`).join("");

function renderTax() {
  const c = state.tax.company;
  const fields = c ? [
    ["Legal name", c.legal_name],
    ["Trade name", c.trade_name],
    ["GST registration", REG[c.registration_type] || c.registration_type],
    ["GSTIN", c.gstin],
    ["PAN", c.pan],
    ["State (place of supply)", c.state ? `${c.state} (${c.state_code})` : c.state_code],
    ["Address", [c.address_line1, c.address_line2, c.city, c.pincode].filter(Boolean).join(", ")],
    ["Phone", c.phone],
    ["Email", c.email],
    ["Invoice prefix", c.invoice_prefix],
    ["Bank", c.bank_name],
    ["Account name", c.bank_account_name],
    ["Account number", c.bank_account_masked],
    ["IFSC", c.bank_ifsc]
  ] : [];
  $("#companyRows").innerHTML = fields.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v || "–")}</td></tr>`).join("");
  empty($("#companyEmpty"), !c, "No company tax profile yet.",
    " The company profile is the seller on every tax document: its GSTIN, its state and its invoice series.");
  $("#companyNote").textContent = c
    ? (c.gstin ? `GSTIN ${c.gstin} · ${c.state || c.state_code || "no state"}` : "Unregistered — no GSTIN on file")
    : "";

  const w = can("tax:write");
  $$('#v-tax [data-act="edit-company"], #v-tax [data-act="new-rate"], #v-tax [data-act="new-slab"]')
    .forEach(b => b.classList.toggle("hide", !w));

  const today = isoDay(0);
  const q = ($("#rateq") ? $("#rateq").value : "").trim().toLowerCase();
  const filter = state.tax.rateFilter;
  const rates = state.tax.rates.filter(r => (filter !== "current" || r.in_force) &&
    (!q || [r.hsn, r.description || ""].some(t => String(t).toLowerCase().includes(q))));
  $("#rateRows").innerHTML = rates.map(r => {
    const status = r.in_force ? `<span class="chip ok">In force</span>`
      : (r.effective_from > today ? `<span class="chip warn">From ${esc(fmtDate(r.effective_from))}</span>`
        : `<span class="chip off">Closed</span>`);
    return `<tr><td><code>${esc(r.hsn)}</code></td><td>${esc(r.description || "–")}</td>
      <td class="n">${esc(r.cgst_rate)}</td><td class="n">${esc(r.sgst_rate)}</td>
      <td class="n">${esc(r.igst_rate)}</td><td class="n">${esc(r.cess_rate)}</td>
      <td>${esc(fmtDate(r.effective_from))}</td><td>${r.effective_to ? esc(fmtDate(r.effective_to)) : "–"}</td>
      <td>${r.is_reverse_charge ? `<span class="chip warn">Reverse charge</span> ` : ""}${status}</td>
      <td class="rowacts">${w && !r.effective_to ? `<button class="btn ghost sm" type="button" data-act="close-rate" data-id="${r.id}">Close</button>` : ""}</td></tr>`;
  }).join("");
  empty($("#rateEmpty"), !rates.length, state.tax.rates.length ? "No rate matches these filters." : "No GST rates yet.",
    state.tax.rates.length ? "" : " A rate is the HSN, the split and the dates it applies to. No rate is assumed for a product that has none.");

  const slabs = state.tax.slabs;
  $("#slabRows").innerHTML = slabs.map(s => {
    const who = s.scope === "product" ? (s.product_sku || `Product #${s.product_id}`)
      : s.scope === "group" ? (s.group_name || "Group") : "Every product";
    const status = s.in_force ? `<span class="chip ok">In force</span>`
      : (s.is_active ? `<span class="chip off">Outside its dates</span>` : `<span class="chip bad">Inactive</span>`);
    return `<tr><td>${esc(s.name)}</td><td>${esc(who)}</td><td>${esc(s.band || "–")}</td>
      <td class="n">${esc(s.discount_percent)}</td>
      <td class="n">${s.approval_above == null ? "–" : esc(s.approval_above)}</td>
      <td>${esc(fmtDate(s.effective_from))}</td><td>${s.effective_to ? esc(fmtDate(s.effective_to)) : "–"}</td>
      <td>${status}</td>
      <td class="rowacts">${w ? `<button class="btn ghost sm" type="button" data-act="edit-slab" data-id="${s.id}">Edit</button>` : ""}</td></tr>`;
  }).join("");
  empty($("#slabEmpty"), !slabs.length, "No discount slabs yet.",
    " A slab is the discount policy as data: a band, a percentage, and the point above which a second person must approve it.");

  const st = $("#q-state"), dist = $("#q-dist");
  if (st) { const cur = st.value; st.innerHTML = `<option value="">Choose a state</option>${stateOptions(cur)}`; if (cur) st.value = cur; }
  if (dist) {
    const cur = dist.value;
    dist.innerHTML = `<option value="">None</option>` + state.dists.map(d =>
      `<option value="${d.id}"${String(d.id) === cur ? " selected" : ""}>${esc(d.name)}</option>`).join("");
    if (cur) dist.value = cur;
  }
}

function companyForm() {
  const c = state.tax.company || {};
  openDrawer("Company tax profile",
    "The seller on every tax document. For a registered company the GSTIN is checked for format and check character, and the state is taken from it.",
    `<form id="companyForm" novalidate>
      <div class="row2"><div><label for="c-legal">Legal name</label><input id="c-legal" name="legal_name" value="${esc(c.legal_name || "")}" autocomplete="off"></div>
      <div><label for="c-trade">Trade name</label><input id="c-trade" name="trade_name" value="${esc(c.trade_name || "")}" autocomplete="off"></div></div>
      <div class="row2"><div><label for="c-reg">GST registration</label><select id="c-reg" name="registration_type">
        ${["regular", "composition", "unregistered"].map(k => `<option value="${k}"${c.registration_type === k ? " selected" : ""}>${esc(REG[k])}</option>`).join("")}</select></div>
      <div><label for="c-state">State</label><select id="c-state" name="state_code"><option value="">—</option>${stateOptions(c.state_code || "")}</select></div></div>
      <label for="c-gstin">GSTIN</label><input id="c-gstin" name="gstin" value="${esc(c.gstin || "")}" placeholder="27AAACX1234Z1Z5" autocomplete="off" autocapitalize="characters" spellcheck="false">
      <label for="c-pan">PAN</label><input id="c-pan" name="pan" value="${esc(c.pan || "")}" placeholder="Taken from the GSTIN when left blank" autocomplete="off" autocapitalize="characters" spellcheck="false">
      <h3>Address and contact</h3>
      <label for="c-a1">Address line 1</label><input id="c-a1" name="address_line1" value="${esc(c.address_line1 || "")}" autocomplete="off">
      <label for="c-a2">Address line 2</label><input id="c-a2" name="address_line2" value="${esc(c.address_line2 || "")}" autocomplete="off">
      <div class="row3"><div><label for="c-city">City</label><input id="c-city" name="city" value="${esc(c.city || "")}" autocomplete="off"></div>
      <div><label for="c-pin">Pincode</label><input id="c-pin" name="pincode" value="${esc(c.pincode || "")}" inputmode="numeric" maxlength="6" autocomplete="off"></div>
      <div><label for="c-phone">Phone</label><input id="c-phone" name="phone" value="${esc(c.phone || "")}" autocomplete="off"></div></div>
      <div class="row2"><div><label for="c-email">Email</label><input id="c-email" name="email" type="email" value="${esc(c.email || "")}" autocomplete="off"></div>
      <div><label for="c-prefix">Invoice prefix</label><input id="c-prefix" name="invoice_prefix" value="${esc(c.invoice_prefix || "")}" placeholder="HB" maxlength="10" autocomplete="off"></div></div>
      <h3>Bank details for the invoice</h3>
      <div class="row2"><div><label for="c-bank">Bank</label><input id="c-bank" name="bank_name" value="${esc(c.bank_name || "")}" autocomplete="off"></div>
      <div><label for="c-bname">Account name</label><input id="c-bname" name="bank_account_name" value="${esc(c.bank_account_name || "")}" autocomplete="off"></div></div>
      <div class="row2"><div><label for="c-bacct">Account number</label><input id="c-bacct" name="bank_account_number" value="" placeholder="${esc(c.bank_account_masked || "Account number")}" autocomplete="off">
        <div class="hint">Leave it blank to keep the number on file. It is never shown again, only its last four digits.</div></div>
      <div><label for="c-ifsc">IFSC</label><input id="c-ifsc" name="bank_ifsc" value="${esc(c.bank_ifsc || "")}" autocomplete="off" autocapitalize="characters" spellcheck="false"></div></div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save company profile</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

async function saveCompany(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements;
  err.textContent = ""; btn.disabled = true;
  const reg = f.registration_type.value;
  const body = {
    // the save replaces the whole profile, so every field is sent: a field the
    // form leaves blank is cleared on purpose
    legal_name: f.legal_name.value.trim(),
    trade_name: f.trade_name.value.trim() || null,
    registration_type: reg,
    gstin: f.gstin.value.trim().toUpperCase() || null,
    pan: f.pan.value.trim().toUpperCase() || null,
    // a registered company takes its state from the GSTIN; an unregistered one
    // must say which state it sells from
    state_code: reg === "unregistered" ? (f.state_code.value || null) : null,
    address_line1: f.address_line1.value.trim() || null,
    address_line2: f.address_line2.value.trim() || null,
    city: f.city.value.trim() || null,
    pincode: f.pincode.value.trim() || null,
    phone: f.phone.value.trim() || null,
    email: f.email.value.trim() || null,
    invoice_prefix: f.invoice_prefix.value.trim() || null,
    bank_name: f.bank_name.value.trim() || null,
    bank_account_name: f.bank_account_name.value.trim() || null,
    bank_account_number: f.bank_account_number.value.trim() || null,
    bank_ifsc: f.bank_ifsc.value.trim().toUpperCase() || null
  };
  const res = await api("/api/company", {method: "PUT", body});
  btn.disabled = false;
  toast(res, res.ok ? "Company profile saved" : "Company profile not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

function rateForm() {
  openDrawer("New GST rate",
    "One rate in force per HSN per date. CGST + SGST must equal IGST for the same supply, and a new rate closes the open window the day before it starts.",
    `<form id="rateForm" novalidate>
      <div class="row2"><div><label for="r-hsn">HSN code</label><input id="r-hsn" name="hsn" inputmode="numeric" placeholder="2106" autocomplete="off"></div>
      <div><label for="r-desc">Description</label><input id="r-desc" name="description" placeholder="Herbal tea" autocomplete="off"></div></div>
      <div class="row3"><div><label for="r-cgst">CGST %</label><input id="r-cgst" name="cgst_rate" inputmode="decimal" value="9" autocomplete="off"></div>
      <div><label for="r-sgst">SGST %</label><input id="r-sgst" name="sgst_rate" inputmode="decimal" value="9" autocomplete="off"></div>
      <div><label for="r-igst">IGST %</label><input id="r-igst" name="igst_rate" inputmode="decimal" value="18" autocomplete="off"></div></div>
      <div class="row2"><div><label for="r-cess">Cess %</label><input id="r-cess" name="cess_rate" inputmode="decimal" value="0" autocomplete="off"></div>
      <div><label for="r-from">Effective from</label><input id="r-from" name="effective_from" type="date" value="${isoDay(0)}"></div></div>
      <label class="chk" for="r-rc"><input id="r-rc" name="is_reverse_charge" type="checkbox" style="width:auto;margin-right:8px">Reverse charge (the tax is stated, the recipient pays it)</label>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save rate</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveRate(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements;
  err.textContent = ""; btn.disabled = true;
  const body = {
    hsn: f.hsn.value.trim(),
    cgst_rate: taxNum(f.cgst_rate.value),
    sgst_rate: taxNum(f.sgst_rate.value),
    igst_rate: taxNum(f.igst_rate.value),
    cess_rate: taxNum(f.cess_rate.value),
    is_reverse_charge: f.is_reverse_charge.checked,
    effective_from: f.effective_from.value
  };
  if (f.description.value.trim()) body.description = f.description.value.trim();
  const res = await api("/api/tax/rates", {method: "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? "Rate saved" : "Rate not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

function closeRateForm(id) {
  const r = state.tax.rates.find(x => x.id === Number(id));
  if (!r) return;
  openDrawer("Close this rate", `HSN ${r.hsn} — the rate stops applying on the date you choose.`,
    `<form id="closeRateForm" data-id="${r.id}" novalidate>
      <label for="cr-to">Effective to</label><input id="cr-to" name="effective_to" type="date" value="${isoDay(0)}">
      <label for="cr-reason">Reason</label><input id="cr-reason" name="reason" placeholder="Why is it closing?" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Close the rate</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveCloseRate(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements;
  err.textContent = ""; btn.disabled = true;
  const res = await api(`/api/tax/rates/${form.dataset.id}/close`, {method: "POST",
    body: {effective_to: f.effective_to.value, reason: f.reason.value.trim()}});
  btn.disabled = false;
  toast(res, res.ok ? "Rate closed" : "Rate not closed");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

function slabForm() {
  const products = state.products.map(p => `<option value="${p.id}">${esc(p.sku)} — ${esc(p.name)}</option>`).join("");
  openDrawer("New discount slab",
    "A band, a percentage, and the point above which a second person must approve the discount.",
    `<form id="slabForm" novalidate>
      <div class="row2"><div><label for="sl-name">Name</label><input id="sl-name" name="name" placeholder="Bulk herbal tea" autocomplete="off"></div>
      <div><label for="sl-scope">Applies to</label><select id="sl-scope" name="scope">
        <option value="all">Every product</option><option value="product">One product</option><option value="group">A distributor group</option></select></div></div>
      <div class="row2" id="sl-productRow" hidden><div><label for="sl-product">Product</label><select id="sl-product" name="product_id"><option value="">Choose a product</option>${products}</select></div></div>
      <div class="row2" id="sl-groupRow" hidden><div><label for="sl-group">Distributor group</label><input id="sl-group" name="group_name" placeholder="North" autocomplete="off"></div></div>
      <div class="row2"><div><label for="sl-minq">Minimum quantity</label><input id="sl-minq" name="min_qty" inputmode="decimal" autocomplete="off"></div>
      <div><label for="sl-maxq">Maximum quantity</label><input id="sl-maxq" name="max_qty" inputmode="decimal" autocomplete="off"></div></div>
      <div class="row2"><div><label for="sl-minv">Minimum value (₹)</label><input id="sl-minv" name="min_value" inputmode="decimal" autocomplete="off"></div>
      <div><label for="sl-maxv">Maximum value (₹)</label><input id="sl-maxv" name="max_value" inputmode="decimal" autocomplete="off"></div></div>
      <div class="row2"><div><label for="sl-pct">Discount %</label><input id="sl-pct" name="discount_percent" inputmode="decimal" value="5" autocomplete="off"></div>
      <div><label for="sl-approval">Approval needed above %</label><input id="sl-approval" name="approval_above" inputmode="decimal" placeholder="10" autocomplete="off"></div></div>
      <div class="row2"><div><label for="sl-from">Effective from</label><input id="sl-from" name="effective_from" type="date" value="${isoDay(0)}"></div>
      <div><label for="sl-to">Effective to</label><input id="sl-to" name="effective_to" type="date"></div></div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save slab</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
  const scope = $("#sl-scope");
  const sync = () => {
    $("#sl-productRow").hidden = scope.value !== "product";
    $("#sl-groupRow").hidden = scope.value !== "group";
  };
  scope.addEventListener("change", sync);
  sync();
}

async function saveSlab(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements;
  err.textContent = ""; btn.disabled = true;
  const body = {
    name: f.name.value.trim(),
    scope: f.scope.value,
    discount_percent: taxNum(f.discount_percent.value),
    effective_from: f.effective_from.value
  };
  if (f.scope.value === "product" && f.product_id.value) body.product_id = Number(f.product_id.value);
  if (f.scope.value === "group" && f.group_name.value.trim()) body.group_name = f.group_name.value.trim();
  if (f.min_qty.value.trim()) body.min_qty = taxNum(f.min_qty.value);
  if (f.max_qty.value.trim()) body.max_qty = taxNum(f.max_qty.value);
  if (f.min_value.value.trim()) body.min_value = taxNum(f.min_value.value);
  if (f.max_value.value.trim()) body.max_value = taxNum(f.max_value.value);
  if (f.approval_above.value.trim()) body.approval_above = taxNum(f.approval_above.value);
  if (f.effective_to.value) body.effective_to = f.effective_to.value;
  const res = await api("/api/discount-slabs", {method: "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? "Discount slab saved" : "Discount slab not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

function editSlabForm(id) {
  const s = state.tax.slabs.find(x => x.id === Number(id));
  if (!s) return;
  openDrawer("Edit discount slab", s.name,
    `<form id="slabPatchForm" data-id="${s.id}" novalidate>
      <div class="row2"><div><label for="sp-name">Name</label><input id="sp-name" name="name" value="${esc(s.name)}" autocomplete="off"></div>
      <div><label for="sp-pct">Discount %</label><input id="sp-pct" name="discount_percent" inputmode="decimal" value="${esc(s.discount_percent)}" autocomplete="off"></div></div>
      <div class="row2"><div><label for="sp-approval">Approval needed above %</label><input id="sp-approval" name="approval_above" inputmode="decimal" value="${s.approval_above == null ? "" : esc(s.approval_above)}" autocomplete="off"></div>
      <div><label for="sp-to">Effective to</label><input id="sp-to" name="effective_to" type="date" value="${s.effective_to || ""}"></div></div>
      <label class="chk" for="sp-active"><input id="sp-active" name="is_active" type="checkbox" style="width:auto;margin-right:8px"${s.is_active ? " checked" : ""}>Active</label>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save slab</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveSlabPatch(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements;
  err.textContent = ""; btn.disabled = true;
  const body = {
    name: f.name.value.trim(),
    discount_percent: taxNum(f.discount_percent.value),
    approval_above: f.approval_above.value.trim() ? taxNum(f.approval_above.value) : null,
    effective_to: f.effective_to.value || null,
    is_active: f.is_active.checked
  };
  const res = await api(`/api/discount-slabs/${form.dataset.id}`, {method: "PATCH", body});
  btn.disabled = false;
  toast(res, res.ok ? "Discount slab saved" : "Discount slab not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}

async function doQuote(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form), f = form.elements;
  err.textContent = ""; btn.disabled = true;
  const p = new URLSearchParams();
  p.set("hsn", f.hsn.value.trim());
  p.set("qty", f.qty.value.trim());
  p.set("unit_price", f.unit_price.value.trim());
  p.set("discount_percent", f.discount_percent.value.trim() || "0");
  if (f.buyer_state.value) p.set("buyer_state", f.buyer_state.value);
  if (f.distributor_id.value) p.set("distributor_id", f.distributor_id.value);
  const res = await api("/api/tax/quote?" + p.toString());
  btn.disabled = false;
  if (!res.ok) {
    err.textContent = detail(res.body);
    $("#quoteOut").innerHTML = "";
    return;
  }
  const q = res.body;
  if (!q.rate_found) {
    $("#quoteOut").innerHTML = `<div class="note">${esc(q.message || "No rate is in force for that HSN.")}</div>`;
    return;
  }
  const c = q.computed;
  const head = c.split === "intra"
    ? `${esc(c.sgst_label)} (${esc(c.place_of_supply_name)})`
    : `IGST to ${esc(c.place_of_supply_name)}`;
  const rows = [
    ["Gross value", money(c.gross)],
    [`Discount (${c.discount_percent}%)`, "−" + money(c.discount_amount)],
    ["Taxable value", money(c.taxable_value)],
    [`CGST ${c.cgst_rate}%`, money(c.cgst_amount)],
    [`${c.sgst_label} ${c.sgst_rate}%`, money(c.sgst_amount)],
    [`IGST ${c.igst_rate}%`, money(c.igst_amount)],
    [`Cess ${c.cess_rate}%`, money(c.cess_amount)]
  ];
  $("#quoteOut").innerHTML = `<div class="tw"><table>
      <thead><tr><th>Line</th><th class="n">Amount (₹)</th></tr></thead>
      <tbody>${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${esc(v)}</td></tr>`).join("")}
        <tr><td><b>Total</b><small>${esc(head)}${c.reverse_charge ? " · reverse charge" : ""}</small></td><td class="n"><b>${esc(money(c.total))}</b><small>round-off ${esc(money(c.round_off))}</small></td></tr>
      </tbody></table></div>
    ${q.discount_slab ? `<div class="note">The best matching slab is “${esc(q.discount_slab)}” (${esc(q.slab_discount_percent)}%). ${q.approval_needed ? "A discount at this level needs a second person to approve it." : "No second approval is needed at this level."}</div>` : ""}`;
}

/* ---------- events ---------- */
document.addEventListener("click", e => {
  const a = e.target.closest("[data-act]");
  if (a && a.dataset.act === "new-entry") return entryForm(a.dataset.kind || "receipt");
  if (a && a.dataset.act === "load-gst") return loadGstRegister();
  if (a && a.dataset.act === "load-tb") return loadTrialBalance();
  if (a && a.dataset.act === "load-ageing") return loadAgeing();
  if (a && a.dataset.act === "open-search") return openPalette();
  if (a && a.dataset.act === "reload-dash") return loadDashboard();
  if (a && a.dataset.act === "dash-ap") return dashOpenApproval(a.dataset.id);
  if (a && a.dataset.act === "expiry-detail") return expiryDetail(a.dataset.id);
  if (a) {
    const act = a.dataset.act;
    if (act === "close") closeDrawer();
    else if (act === "new-product") productForm();
    else if (act === "open-product") productDrawer(a.dataset.id, "open");
    else if (act === "edit-product") productForm(a.dataset.id);
    else if (act === "save-product") productForm(a.dataset.id);
    else if (act === "new-so-dist") { state.soDistPreset = Number(a.dataset.id); soForm(); }
    else if (act === "hr-employees") hrEmployees();
    else if (act === "hr-shifts") hrShifts();
    else if (act === "hr-new-shift") hrShiftForm();
    else if (act === "hr-edit-shift") hrShiftForm(a.dataset.id);
    else if (act === "hr-new-emp") employeeForm();
    else if (act === "hr-edit-emp") employeeForm(a.dataset.id);
    else if (act === "hr-attendance") hrAttendance();
    else if (act === "hr-checkin") hrCheckIn();
    else if (act === "hr-checkout") api("/api/hr/attendance/check-out", {method: "POST", body: {}}).then(r => { toast(r, r.ok ? "Checked out" : "Check-out not recorded"); if (r.ok) hrAttendance(); });
    else if (act === "hr-refresh-att") hrAttendance();
    else if (act === "hr-leave") hrLeave();
    else if (act === "hr-od") hrOd();
    else if (act === "hr-payroll") hrPayroll();
    else if (act === "pay-prepare") hrPayrollAction("prepare", a.dataset.id);
    else if (act === "pay-submit") hrPayrollAction("submit", a.dataset.id);
    else if (act === "pay-process") hrPayrollAction("process", a.dataset.id);
    else if (act === "pay-paid") hrPayrollAction("paid", a.dataset.id);
    else if (act === "pay-open") hrPayrollOpen(a.dataset.id);
    else if (act === "new-warehouse") warehouseForm();
    else if (act === "new-po") poForm();
    else if (act === "open-po") poDetail(a.dataset.id);
    else if (act === "cancel-po") cancelPoForm(a.dataset.id);
    else if (act === "new-supplier") supplierForm();
    else if (act === "open-supplier") supplierDetail(a.dataset.id);
    else if (act === "toggle-supplier") toggleSupplier(a.dataset.id);
    else if (act === "decide-bank") decideBankForm(a.dataset.id);
    else if (act === "add-line") { $("#plines").insertAdjacentHTML("beforeend", lineRow(true)); syncPoLines(); $("#plines").lastElementChild.querySelector("select").focus(); }
    else if (act === "rm-line") { a.closest("[data-line]").remove(); syncPoLines(); }
    else if (act === "goto-wh") { closeDrawer(); location.hash = "#/inventory/warehouses"; }
    else if (act === "new-so") soForm();
    else if (act === "open-so") soDetail(a.dataset.id);
    else if (act === "submit-so") submitSO(a.dataset.id);
    else if (act === "open-ap") apDetail(a.dataset.id);
    else if (act === "new-dist") distForm();
    else if (act === "edit-dist") distForm(a.dataset.id);
    else if (act === "change-limit") limitForm(a.dataset.id);
    else if (act === "add-sline") { $("#slines").insertAdjacentHTML("beforeend", soLineRow(true)); syncSoLines(); $("#slines").lastElementChild.querySelector("select").focus(); }
    else if (act === "rm-sline") { a.closest("[data-line]").remove(); syncSoLines(); }
    else if (act === "new-lead") leadForm();
    else if (act === "open-lead") leadDetail(a.dataset.id);
    else if (act === "lead-panel") leadDetail(a.dataset.id, "", a.dataset.panel);
    else if (act === "new-user") userForm();
    else if (act === "change-role") changeRoleForm(a.dataset.id);
    else if (act === "reset-pw") resetPwForm(a.dataset.id);
    else if (act === "toggle-user") toggleUser(a.dataset.id, a.dataset.active);
    else if (act === "new-role") roleForm();
    else if (act === "edit-role") roleForm(a.dataset.id);
    else if (act === "new-employee") employeeForm();
    else if (act === "edit-emp") employeeForm(a.dataset.id);
    else if (act === "edit-company") companyForm();
    else if (act === "new-rate") rateForm();
    else if (act === "close-rate") closeRateForm(a.dataset.id);
    else if (act === "new-slab") slabForm();
    else if (act === "edit-slab") editSlabForm(a.dataset.id);
    else if (act === "open-inv") invDetail(a.dataset.id);
    else if (act === "print-inv") printDocument("invoice", Number(a.dataset.id), "ORIGINAL");
    else if (act === "print-copy") {
      const chosen = $("#printCopy");
      printDocument(a.dataset.kind, Number(a.dataset.id), chosen ? chosen.value : "ORIGINAL");
    }
    return;
  }
  const tab = e.target.closest("[data-tab]");
  if (tab) { location.hash = "#/inventory/" + tab.dataset.tab; return; }
  const dr = e.target.closest("[data-dash-range]");
  if (dr) { setDashRange(Number(dr.dataset.dashRange)); return; }
  const expb = e.target.closest("[data-eb]");
  if (expb) { setExpiryBucket(expb.dataset.eb); return; }
  const pf = e.target.closest("[data-pf]");
  if (pf) { state.poFilter = pf.dataset.pf; $$("[data-pf]").forEach(b => b.setAttribute("aria-pressed", String(b === pf))); renderPOs(); return; }
  const inf = e.target.closest("[data-if]");
  if (inf) { state.invFilter = inf.dataset["if"]; $$("[data-if]").forEach(b => b.setAttribute("aria-pressed", String(b === inf))); renderBilling(); return; }
  const spf = e.target.closest("[data-sf2]");
  if (spf) { state.supFilter = spf.dataset.sf2; $$("[data-sf2]").forEach(b => b.setAttribute("aria-pressed", String(b === spf))); renderSuppliers(); return; }
  const srow = e.target.closest("tr[data-sup]");
  if (srow) { supplierDetail(srow.dataset.sup); return; }
  const rf = e.target.closest("[data-rf]");
  if (rf) { state.tax.rateFilter = rf.dataset.rf; $$("[data-rf]").forEach(b => b.setAttribute("aria-pressed", String(b === rf))); renderTax(); return; }
  const rpb = e.target.closest("[data-rp]");
  if (rpb) { state.rp.key = rpb.dataset.rp; state.rpPage = 1; state.rp.data = null; drawRpTabs(); loadReport(); return; }
  const rppage = e.target.closest("[data-act='rp-page']");
  if (rppage) { state.rpPage = Number(rppage.dataset.page) || 1; loadReport(); return; }
  const rpp = e.target.closest("[data-rpp]");
  if (rpp) { setPreset(rpp.dataset.rpp); return; }
  const fuf = e.target.closest("[data-fuf]");
  if (fuf) { state.fuFilter = fuf.dataset.fuf; $$("[data-fuf]").forEach(b => b.setAttribute("aria-pressed", String(b === fuf))); renderFollowups(); return; }
  const lf = e.target.closest("[data-lf]");
  if (lf) { state.ldFilter = lf.dataset.lf; $$("[data-lf]").forEach(b => b.setAttribute("aria-pressed", String(b === lf))); renderLeads(); return; }
  const lo = e.target.closest("[data-lo]");
  if (lo) { state.ldOwner = lo.dataset.lo; $$("[data-lo]").forEach(b => b.setAttribute("aria-pressed", String(b === lo))); renderLeads(); return; }
  const lr = e.target.closest("tr[data-ld]");
  if (lr) { leadDetail(lr.dataset.ld); return; }
  const sf = e.target.closest("[data-sf]");
  if (sf) { state.soFilter = sf.dataset.sf; $$("[data-sf]").forEach(b => b.setAttribute("aria-pressed", String(b === sf))); renderSales(); return; }
  const af = e.target.closest("[data-af]");
  if (af) { state.apFilter = af.dataset.af; $$("[data-af]").forEach(b => b.setAttribute("aria-pressed", String(b === af))); renderApprovals(); return; }
  const sr = e.target.closest("tr[data-so]");
  if (sr) { soDetail(sr.dataset.so); return; }
  const ar = e.target.closest("tr[data-ap]");
  if (ar) { apDetail(ar.dataset.ap); return; }
  const row = e.target.closest("tr[data-po]");
  if (row) poDetail(row.dataset.po);
});
document.addEventListener("submit", e => {
  e.preventDefault();
  const f = e.target;
  if (f.id === "loginForm") login(e);
  else if (f.id === "changePwForm") changePassword(f);
  else if (f.id === "prodForm") saveProduct(f);
  else if (f.id === "whForm") saveWarehouse(f);
  else if (f.id === "poForm") savePO(f);
  else if (f.id === "rcvForm") postReceipt(f);
  else if (f.id === "poCancel") cancelPo(f);
  else if (f.id === "supForm") saveSupplier(f);
  else if (f.id === "bankForm") requestBankChange(f);
  else if (f.id === "bankDecide") decideBank(f, (e.submitter && e.submitter.dataset.decide) || "approve");
  else if (f.id === "soForm") saveSO(f);
  else if (f.id === "cancelForm") cancelSO(f);
  else if (f.id === "dispForm") postDispatch(f);
  else if (f.id === "decideForm") decide(f, (e.submitter && e.submitter.value) || "approve");
  else if (f.id === "distForm") saveDist(f);
  else if (f.id === "moveForm") saveInvoiceMovement(f);
  else if (f.id === "amendReqForm") requestInvoiceAmendment(f);
  else if (f.id === "invCancelForm") cancelInvoice(f);
  else if (f.id === "cnForm") issueNote(f, "cn");
  else if (f.id === "dnForm") issueNote(f, "dn");
  else if (f.id === "limitForm") saveLimit(f);
  else if (f.id === "verifyForm") submitVerification(f);
  else if (f.id === "entryForm") saveEntry(f);
  else if (f.id === "leadForm") saveLead(f);
  else if (f.id === "actForm") saveActivity(f);
  else if (f.id === "lstatusForm") saveLeadStatus(f);
  else if (f.id === "lfuForm") saveFollowUp(f);
  else if (f.id === "leditForm") saveLeadEdit(f);
  else if (f.id === "lownerForm") saveOwner(f);
  else if (f.id === "userForm") saveUser(f);
  else if (f.id === "chroleForm") saveChangeRole(f);
  else if (f.id === "resetpwForm") saveResetPw(f);
  else if (f.id === "roleForm") saveRole(f);
  else if (f.id === "empForm") saveEmployee(f);
  else if (f.id === "companyForm") saveCompany(f);
  else if (f.id === "rateForm") saveRate(f);
  else if (f.id === "closeRateForm") saveCloseRate(f);
  else if (f.id === "slabForm") saveSlab(f);
  else if (f.id === "slabPatchForm") saveSlabPatch(f);
  else if (f.id === "quoteForm") doQuote(f);
  else if (f.id === "hrShiftForm") saveHrShift(f);
  else if (f.id === "hrManualForm") saveManualAttendance(f);
  else if (f.id === "hrLeaveForm") saveHrLeave(f);
  else if (f.id === "hrOdForm") saveHrOd(f);
  else if (f.id === "hrPeriodForm") saveHrPeriod(f);
});
document.addEventListener("input", e => {
  if (e.target.closest("#poForm")) syncPoLines();
  if (e.target.closest("#soForm")) syncSoLines();
  if (e.target.id === "lostq") renderLost();
  if (e.target.id === "fuq") renderFollowups();
  if (e.target.id === "cuq") renderCustomers();
  if (e.target.id === "pq") renderProducts();
  if (e.target.id === "rpq") { state.rpSearch = e.target.value; drawRpTabs(); }
});
document.addEventListener("change", e => {
  if (e.target.closest("#poForm")) syncPoLines();
  if (e.target.id === "rpCategory") { state.rpCategory = e.target.value; drawRpTabs(); }
});
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
    e.preventDefault();
    state.palette.open ? closePalette() : openPalette();
    return;
  }
  if (!state.palette.open) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); closePalette(); return; }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const n = state.palette.items.length;
    if (!n) return;
    const step = e.key === "ArrowDown" ? 1 : -1;
    const base = state.palette.i < 0 ? (step > 0 ? -1 : n) : state.palette.i;
    paletteSetIndex(base + step);
    return;
  }
  if (e.key === "Enter") {
    const item = state.palette.items[state.palette.i];
    if (item) { e.preventDefault(); paletteGo(item); }
    return;
  }
  if (e.key === "Tab") {
    const f = $$("#palette button, #palette input").filter(x => x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); e.stopImmediatePropagation(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); e.stopImmediatePropagation(); first.focus(); }
  }
});
document.addEventListener("keydown", e => {
  if (!drawerOpen()) return;
  if (e.key === "Escape") { closeDrawer(); return; }
  if (e.key === "Tab") {                                   // keep focus inside the open drawer
    const f = $$("#drawer button:not([disabled]),#drawer input,#drawer select,#drawer a[href]").filter(x => x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});
$("#scrim").addEventListener("click", closeDrawer);
$("#dclose").addEventListener("click", closeDrawer);
const signOut = async () => { const r = await api("/api/auth/logout", {method: "POST"}); toast(r, "Signed out"); leave(); };
$("#out").addEventListener("click", signOut);
$("#mcOut").addEventListener("click", signOut);
$("#themeToggle").addEventListener("click", toggleTheme);
$("#dashTheme").addEventListener("click", toggleTheme);
$("#paletteQ").addEventListener("input", e => {
  clearTimeout(state.palette.timer);
  const term = e.target.value.trim();
  state.palette.timer = setTimeout(() => paletteSearch(term), 180);
});
$("#paletteResults").addEventListener("click", e => {
  const item = e.target.closest(".palette-item");
  if (item) paletteGo(item);
});
$("#palette").addEventListener("click", e => { if (e.target.id === "palette") closePalette(); });
const chartEl = $("#salesChart");
chartEl.addEventListener("pointermove", e => {
  const hit = e.target.closest("[data-i]");
  if (hit) chartTip(Number(hit.dataset.i));
});
chartEl.addEventListener("pointerleave", hideChartTip);
chartEl.addEventListener("blur", hideChartTip);
chartEl.addEventListener("keydown", e => {
  const c = state.dashboard && state.dashboard.sales_vs_purchases;
  if (!c || !c.series || !c.series.length) return;
  const n = c.series.length;
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    e.preventDefault();
    const i = state.chart.index < 0
      ? (e.key === "ArrowRight" ? 0 : n - 1)
      : Math.max(0, Math.min(n - 1, state.chart.index + (e.key === "ArrowRight" ? 1 : -1)));
    chartTip(i);
  } else if (e.key === "Escape") {
    hideChartTip();
  }
});
["pq", "sq", "lq", "oq"].forEach(id => $("#" + id).addEventListener("input", () => ({pq: renderProducts, sq: renderStock, lq: renderLedger, oq: renderPOs})[id]()));
$("#supq").addEventListener("input", renderSuppliers);
$("#soq").addEventListener("input", renderSales);
$("#biq").addEventListener("input", renderBilling);
$("#ldq").addEventListener("input", renderLeads);
$("#rateq").addEventListener("input", renderTax);
document.addEventListener("change", e => {
  if (e.target.id === "rpFrom" || e.target.id === "rpTo") { state.rp.from = $("#rpFrom").value; state.rp.to = $("#rpTo").value; markPreset(""); loadReport(); }
  if (["rpEmployee", "rpDepartment", "rpBranch"].includes(e.target.id)) {
    const key = {rpEmployee: "employee_id", rpDepartment: "department", rpBranch: "branch_id"}[e.target.id];
    state.rp.filters[key] = e.target.value;
    state.rpPage = 1;
    loadReport();
  }
});
document.addEventListener("change", e => {                       // activity form: keep the date field sensible
  const f = e.target.closest("#actForm"); if (!f) return;
  if (e.target.name === "kind" && f.elements.date) f.elements.date.value = e.target.value === "note" ? "" : (f.elements.date.value || isoDay(3));
  if (e.target.name === "clear" && f.elements.date) f.elements.date.disabled = e.target.checked;
});
$("#swh").addEventListener("change", renderStock);
$("#sin").addEventListener("change", renderStock);
$("#ltype").addEventListener("change", renderLedger);
["audAction", "audActor", "audFrom", "audTo"].forEach(id => $("#" + id).addEventListener("change", loadAudit));
// The distributor filter is rebuilt with the header on every render, so it is
// handled by delegation. Without this the choice did nothing until the screen
// was reloaded, which is why the All/Active/Blocked filter looked broken.
document.addEventListener("change", e => {
  if (e.target.id !== "dists-filter") return;
  state.distFilter = e.target.value;
  renderDists();   // the header's own copy of the select keeps the chosen value
});
window.addEventListener("hashchange", () => { if (state.user) { closeDrawer(); closePalette(); route(); } });

let startTheme = "light";
try {
  startTheme = localStorage.getItem("hb.theme")
    || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
} catch (e) { /* storage blocked */ }
applyTheme(startTheme === "dark" ? "dark" : "light");

boot();
})();