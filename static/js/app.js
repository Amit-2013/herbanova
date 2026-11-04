/* HERBANOVA Business Control - front end.
   Talks only to the FastAPI endpoints; the server stays the authority on every rule.
   All text that came from the server goes through esc() before it reaches innerHTML. */
(() => {
"use strict";

/* ---------- helpers ---------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
/* The navigation hierarchy, view permissions and tab rules live in
   workspace.js so the same definitions run under the Node tests. */
const WS = window.HBWorkspace;
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

const state = {user: null, perms: new Set(), features: null, featureFlags: [], modules: null, dashboard: null, products: [], plist: {rows: [], total: null, page: 1, size: 50, q: "", status: "", sort: "sku", direction: "asc", loading: false, loaded: false, seq: 0, timer: 0}, lp: {}, warehouses: [], batches: [], pos: [], movements: null,
               suppliers: [], bankChanges: [], supFilter: "all",
               dists: [], orders: [], approvals: [], leads: [], rp: {cat: [], key: "stock", from: "", to: "", data: null, tok: 0}, soFilter: "all", apFilter: "pending", ldFilter: "open", ldOwner: "all", distFilter: "all",
               users: [], roles: [], employees: [], permCatalog: [], audit: {rows: [], actions: [], actors: [], total: 0},
               tax: {company: null, rates: [], slabs: [], states: [], rateFilter: "all"},
               invoices: [], creditNotes: [], debitNotes: [], invFilter: "all",
               accounts: {outstanding: null, entries: [], gst: null, tb: null, ageing: null,
                          years: null, locks: [], inputGst: null, netGst: null,
                          reconciliation: null, filedReturns: null, dues: null,
                          challans: null,
                          ledger: {heads: null, openings: null, openingFy: "",
                                   sheet: null, vouchers: null, daybook: null,
                                   statements: null, selected: null, detail: null,
                                   candidates: null, rec: null}},
               acc: {from: "", to: "", state: "", section: "reports", payDue: "", report: null, loading: false, error: null, seq: 0,
                     cmp: {mode: "full_month", month: "", data: null, loading: false, error: null, seq: 0},
                     rbd: {data: null, loading: false, error: null, seq: 0, from: "", to: ""}},
               exp: {rows: [], heads: [], settings: null, status: "", head: "", q: "",
                     loading: false, error: null, seq: 0, loaded: false},
               foc: {stock: [], notes: [], loading: false, error: null, loaded: false},
               sr: {status: null, schedules: [], recipients: [], deliveries: [],
                    tab: "schedules", logStatus: "", logPack: ""},
               email: {settings: null, messages: [], loading: false, loaded: false,
                       error: null},
               poFilter: "all", view: "dash", tab: "stock", lostFilter: "",
               fuFilter: "today", rpPage: 1, rpSearch: "", rpCategory: "",
               dashFrom: "", dashTo: "", dashPreset: "month", dashDateError: "", dashLoading: false, dashError: null, dashSeq: 0, chart: {index: -1},
               compare: {mode: "full_month", month: "", data: null, loading: false, error: null, seq: 0},
               geo: {from: "", to: "", data: null, loading: false, error: null, dateError: "", seq: 0,
                     sort: {key: "sales", dir: "desc"}, selected: null},
               expiry: {bucket: "all", loading: false, data: null},
               palette: {open: false, items: [], i: -1, seq: 0, timer: 0},
               hr: {dashboard: null, employees: [], attendance: [], leave: [], od: [], payroll: [],
                    branches: [], offices: [], rules: [], shifts: [], siteEmps: [],
                    mxBranch: "", mxOffice: "", repBranch: "", repOffice: "",
                    from: "", to: "", error: null, profile: null}};
state.rp.filters = {employee_id: "", department: "", branch_id: ""};
state.rp.opts = null;

/* The Overview window. A preset fills the trigger; a custom range clears it.
   Dates are calendar days in the business time zone, sent to the server as
   from_date/to_date so the figures are counted there, not filtered here. */
function dayIso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function dashWindow(key, now = new Date()) {
  const t = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (key === "1d" || key === "7d" || key === "30d" || key === "90d") {
    const n = Number(key.slice(0, -1));
    const s = new Date(t); s.setDate(t.getDate() - (n - 1));
    return {from: dayIso(s), to: dayIso(t)};
  }
  if (key === "last_month") {
    return {from: dayIso(new Date(t.getFullYear(), t.getMonth() - 1, 1)),
            to: dayIso(new Date(t.getFullYear(), t.getMonth(), 0))};
  }
  if (key === "fy") {
    const y = t.getMonth() >= 3 ? t.getFullYear() : t.getFullYear() - 1;
    return {from: `${y}-04-01`, to: dayIso(t)};
  }
  return {from: dayIso(new Date(t.getFullYear(), t.getMonth(), 1)), to: dayIso(t)};
}
{ const w = dashWindow("month"); state.dashFrom = w.from; state.dashTo = w.to; }
try {
  const from = localStorage.getItem("hb.dashFrom");
  const to = localStorage.getItem("hb.dashTo");
  if (/^\d{4}-\d{2}-\d{2}$/.test(from || "") && /^\d{4}-\d{2}-\d{2}$/.test(to || "")
      && from <= to) {
    state.dashFrom = from; state.dashTo = to;
    state.dashPreset = localStorage.getItem("hb.dashPreset") || "";
    // Presets are relative to today, so a stored one no longer matches once
    // the day moves on. The pair stays; only the highlight is dropped.
    const presetWindow = state.dashPreset ? dashWindow(state.dashPreset) : null;
    if (!presetWindow || presetWindow.from !== from || presetWindow.to !== to) state.dashPreset = "";
  }
} catch (e) { /* storage blocked */ }
try {
  const mode = localStorage.getItem("hb.cmpMode");
  const month = localStorage.getItem("hb.cmpMonth");
  if (mode === "full_month" || mode === "mtd") state.compare.mode = mode;
  if (/^\d{4}-\d{2}$/.test(month || "")) state.compare.month = month;
} catch (e) { /* storage blocked */ }
{ const w = dashWindow("month"); state.geo.from = w.from; state.geo.to = w.to; }
{ const w = dashWindow("month"); state.acc.from = w.from; state.acc.to = w.to; }
const accAllowed = () => can("accounts:reports");
try {
  const from = localStorage.getItem("hb.geoFrom");
  const to = localStorage.getItem("hb.geoTo");
  if (/^\d{4}-\d{2}-\d{2}$/.test(from || "") && /^\d{4}-\d{2}-\d{2}$/.test(to || "")
      && from <= to) {
    state.geo.from = from;
    state.geo.to = to;
  }
} catch (e) { /* storage blocked */ }
const can = p => state.perms.has(p);
const dashQuery = () => `from_date=${encodeURIComponent(state.dashFrom)}&to_date=${encodeURIComponent(state.dashTo)}`;

/* ---------- server calls ---------- */
/* Paged lists answer with X-Total-Count, so the footer can show the true number
   of matching rows rather than the size of the page in hand. */
async function apiPage(path, opts = {}) {
  const o = {credentials: "same-origin", headers: {"Content-Type": "application/json"}, ...opts};
  if (o.body && typeof o.body !== "string") o.body = JSON.stringify(o.body);
  let res;
  try { res = await fetch(path, o); }
  catch (e) { return {status: 0, ok: false, total: null, body: {detail: "Cannot reach the server. Check the connection and try again."}}; }
  let body = null;
  try { body = await res.json(); } catch (e) { /* empty body */ }
  const raw = res.headers.get("X-Total-Count");
  const total = raw != null && /^\d+$/.test(raw) ? Number(raw) : null;
  if (res.status === 401 && state.user && !path.endsWith("/login")) leave("Your session has ended. Sign in again.");
  return {status: res.status, ok: res.ok, body, total};
}
async function api(path, opts = {}) {
  const {status, ok, body} = await apiPage(path, opts);
  return {status, ok, body};
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
  $("#drawer").classList.remove("hr-wide");
  $("#drawer").classList.toggle("wide", wide);
  $("#scrim").classList.remove("hide");
  $("#drawer").classList.remove("hide");
  document.body.classList.add("drawer-open");
  fitDrawerTables();
  drawerSnap = drawerFormSnapshot();
  drawerDirty = false;
  const first = $("#dbody").querySelector("input,select,textarea");
  (first || $("#dclose")).focus();
}
/* A wide table (invoice lines, ledgers) scrolls inside its own box rather than
   dragging the whole drawer body sideways. Only tables that genuinely do not fit
   are wrapped, so the sticky header keeps working on the rest. */
function fitDrawerTables() {
  const body = $("#dbody");
  if (!body || !drawerOpen()) return;
  body.querySelectorAll("table").forEach(t => {
    let wrap = t.parentElement;
    if (!wrap.classList.contains("tw")) {
      wrap = document.createElement("div");
      wrap.className = "tw";
      t.replaceWith(wrap);
      wrap.appendChild(t);
    }
    wrap.classList.toggle("tscroll", t.getBoundingClientRect().width > wrap.clientWidth + 1);
  });
}
function closeDrawer() {
  $("#scrim").classList.add("hide");
  $("#drawer").classList.add("hide");
  document.body.classList.remove("drawer-open");
  $("#dbody").innerHTML = "";
  drawerDirty = false;
  drawerSnap = "";
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  lastFocus = null;
}
const drawerOpen = () => !$("#drawer").classList.contains("hide");

/* ---------- session ---------- */
/* Module switches are separate from permissions: the Administrator turns a
   module off centrally, and the server then removes its permissions from every
   role. The map mirrors app/core/features.py so navigation never offers a
   screen whose API answers 403. A missing list (older server) means all on. */
const VIEW_FEATURE = WS.VIEW_FEATURE;
const featureOn = v => !VIEW_FEATURE[v] || !state.features || state.features.has(VIEW_FEATURE[v]);

function enter(u) {
  state.user = u;
  state.perms = new Set(u.permissions || []);
  state.features = Array.isArray(u.features) ? new Set(u.features) : null;
  if (u.must_change_password) { showPasswordChange(u); return; }
  state.dashboard = null;
  state.dashLoading = true;
  state.dashError = null;
  state.expiry = {bucket: "all", loading: false, data: null};
  state.email = {settings: null, messages: [], loading: false, loaded: false, error: null};
  state.chart = {index: -1, off: {}};
  closePalette();
  $("#mustChange").classList.add("hide");
  $("#login").classList.add("hide");
  $("#totp").classList.add("hide");
  $("#shell").classList.remove("hide");
  $("#who").textContent = u.username;
  $("#role").textContent = u.role;
  // The menu, breadcrumb and favourite star all read the same hierarchy; rows
  // are filtered by the server's permissions and the module switches. A fresh
  // identity starts from the built-in menu while the server's own tree for this
  // account is requested, and keeps it if that request fails or ?nav=builtin
  // was chosen.
  navReset();
  wsEnter();
  route();
  loadAll();
}
function leave(msg) {
  navSeq += 1;
  WS.resetNavTree();
  navState = "builtin";
  navError = "";
  wsClearTabs();
  wsModel = null;
  wsLastHash = "";
  closeTabMenu();
  state.user = null; state.perms = new Set(); state.features = null;
  state.featureFlags = []; state.movements = null;
  state.dashboard = null; state.dashLoading = false; state.dashError = null;
  signinAdmin.loaded = false;
  closePalette();
  closeDrawer();
  closeDashRange();
  $("#mustChange").classList.add("hide");
  $("#changePwForm").reset();
  $("#totp").classList.add("hide");
  $("#totpForm").reset();
  $("#shell").classList.add("hide");
  $("#login").classList.remove("hide");
  $("#lerr").textContent = msg || "";
  refreshSignInContent();
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
  // The policy itself lives only on the server; the browser checks what it can
  // know locally (the two fields match) and shows the server's own reasons.
  if (!current) { err.textContent = "Enter your current password."; return; }
  if (next !== f.confirm_password.value) { err.textContent = "The new passwords do not match."; return; }
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
  if (!res.ok) { $("#lerr").textContent = res.status === 401 ? "User ID or password is incorrect." : detail(res.body); return; }
  saveLoginId();
  const data = res.body || {};
  // The server decides whether a password alone is enough. It never sends a
  // session cookie until the authenticator step (or enrollment) is complete.
  if (data.status === "otp_required") { $("#p").value = ""; return showTotp("verify"); }
  if (data.status === "setup_required") { $("#p").value = ""; return showTotp("setup"); }
  $("#p").value = "";
  const me = await api("/api/auth/me");           // permissions come from the server, not from a copy in this file
  enter(me.ok ? me.body : res.body);
}

/* ---------- sign-in page content (public, Administrator-managed) ---------- */
const SAVE_ID_KEY = "hb.savedUser";
const promoMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
let signinContent = null;
let promoSlides = [];
let promoIndex = 0;
let promoTimer = null;
let promoPaused = false;

function applySavedId() {
  let saved = "";
  try { saved = localStorage.getItem(SAVE_ID_KEY) || ""; } catch (err) { /* storage blocked */ }
  if (saved) { $("#u").value = saved; $("#saveId").checked = true; }
}
function saveLoginId() {
  const value = $("#u").value.trim();
  try {
    if ($("#saveId").checked && value) localStorage.setItem(SAVE_ID_KEY, value);
    else localStorage.removeItem(SAVE_ID_KEY);
  } catch (err) { /* storage blocked */ }
}
function signinEmpty(text = "No data yet") {
  const p = document.createElement("p");
  p.className = "signin-empty"; p.textContent = text;
  return p;
}
function signinDate(iso) {
  const value = new Date(`${iso}T00:00:00`);
  return Number.isNaN(value.getTime()) ? iso
    : value.toLocaleDateString(undefined, {day: "numeric", month: "short", year: "numeric"});
}
function contactBox(contact) {
  const box = document.createElement("div"); box.className = "contact-box";
  const label = document.createElement("h3"); label.textContent = contact.label;
  box.appendChild(label);
  if (contact.detail) {
    const p = document.createElement("p"); p.textContent = contact.detail; box.appendChild(p);
  }
  if (contact.phone) {
    const p = document.createElement("p"), a = document.createElement("a");
    a.href = `tel:${contact.phone.replace(/[^\d+]/g, "")}`; a.textContent = contact.phone;
    p.appendChild(a); box.appendChild(p);
  }
  if (contact.email) {
    const p = document.createElement("p"), a = document.createElement("a");
    a.href = `mailto:${encodeURIComponent(contact.email)}`; a.textContent = contact.email;
    p.appendChild(a); box.appendChild(p);
  }
  return box;
}
function renderPromo(banners) {
  const track = $("#promoTrack"), dots = $("#promoDots"), controls = $("#promoControls");
  stopPromoRotation();
  track.replaceChildren(); dots.replaceChildren();
  promoSlides = []; promoIndex = 0;
  if (!banners.length) { track.appendChild(signinEmpty()); controls.classList.add("hide"); return; }
  banners.forEach((banner, i) => {
    const slide = document.createElement(banner.link_url ? "a" : "div");
    slide.className = "promo-slide";
    slide.setAttribute("aria-hidden", "true");
    if (banner.link_url) {
      slide.href = banner.link_url;             // the server refused javascript: and // hosts
      if (/^https?:\/\//i.test(banner.link_url)) {
        slide.target = "_blank"; slide.rel = "noopener noreferrer";
      }
    }
    const img = document.createElement("img");
    img.src = banner.image_url; img.alt = banner.title || "Promotion";
    img.loading = i ? "lazy" : "eager";
    slide.appendChild(img);
    if (banner.title) {
      const caption = document.createElement("span");
      caption.className = "promo-caption"; caption.textContent = banner.title;
      slide.appendChild(caption);
    }
    track.appendChild(slide); promoSlides.push(slide);
    const dot = document.createElement("button");
    dot.type = "button"; dot.className = "promo-dot"; dot.setAttribute("role", "tab");
    dot.setAttribute("aria-selected", "false");
    dot.setAttribute("aria-label", `Banner ${i + 1} of ${banners.length}`);
    dot.addEventListener("click", () => { showPromo(i); startPromoRotation(); });
    dots.appendChild(dot);
  });
  controls.classList.toggle("hide", banners.length < 2);
  showPromo(0);
  startPromoRotation();
}
function showPromo(index) {
  if (!promoSlides.length) return;
  promoIndex = (index + promoSlides.length) % promoSlides.length;
  promoSlides.forEach((slide, i) => {
    slide.classList.toggle("on", i === promoIndex);
    slide.setAttribute("aria-hidden", i === promoIndex ? "false" : "true");
  });
  $$("#promoDots .promo-dot").forEach((dot, i) =>
    dot.setAttribute("aria-selected", i === promoIndex ? "true" : "false"));
}
function startPromoRotation() {
  stopPromoRotation();
  if (promoPaused || promoSlides.length < 2 || document.hidden
      || (promoMotion && promoMotion.matches)) return;
  promoTimer = setInterval(() => showPromo(promoIndex + 1), 6000);
}
function stopPromoRotation() {
  if (promoTimer) { clearInterval(promoTimer); promoTimer = null; }
}
function renderNotices(notices) {
  const list = $("#noticeList"); list.replaceChildren();
  $("#noticeCount").textContent = notices.length
    ? `${notices.length} item${notices.length === 1 ? "" : "s"}` : "";
  if (!notices.length) { list.appendChild(signinEmpty()); return; }
  notices.forEach(notice => {
    const item = document.createElement("article"); item.className = "notice-item";
    const when = document.createElement("time");
    when.dateTime = notice.date; when.textContent = signinDate(notice.date);
    const title = document.createElement("h3"); title.textContent = notice.title;
    item.append(when, title);
    if (notice.body) {
      const text = document.createElement("p"); text.textContent = notice.body; item.appendChild(text);
    }
    list.appendChild(item);
  });
}
function renderContacts(contacts) {
  const list = $("#contactList"); list.replaceChildren();
  if (!contacts.length) { list.appendChild(signinEmpty()); return; }
  contacts.forEach(contact => list.appendChild(contactBox(contact)));
}
function renderLegalLinks(legal) {
  const docs = new Map((legal || []).map(doc => [doc.key, doc]));
  $$("[data-legal]").forEach(btn => {
    const doc = docs.get(btn.dataset.legal);
    if (doc) { btn.textContent = doc.title || btn.textContent; btn.classList.remove("hide"); }
    else btn.classList.add("hide");
  });
  const shown = $$("[data-legal]").filter(btn => !btn.classList.contains("hide")).length;
  const sep = $("[data-legal-sep]");
  if (sep) sep.classList.toggle("hide", shown < 2);
}
function renderCopyright(company) {
  const name = (company && (company.trade_name || company.name)) || "HERBANOVA";
  $("#copyright").textContent = `© ${new Date().getFullYear()} ${name}. All rights reserved.`;
}
async function refreshSignInContent() {
  const res = await api("/api/public/sign-in");
  signinContent = res.ok ? res.body
    : {company: null, banners: [], notices: [], contacts: [], legal: []};
  renderCopyright(signinContent.company);
  renderPromo(signinContent.banners || []);
  renderNotices(signinContent.notices || []);
  renderContacts(signinContent.contacts || []);
  renderLegalLinks(signinContent.legal || []);
}
async function openLegal(key) {
  const button = $(`[data-legal="${key}"]`);
  const fallback = key === "privacy" ? "Privacy Policy" : "Terms & Conditions";
  $("#legalTitle").textContent = button && button.textContent ? button.textContent : fallback;
  const body = $("#legalBody"); body.textContent = "";
  const dialog = $("#legalDialog");
  if (!dialog.open) dialog.showModal();
  const res = await api(`/api/public/sign-in/legal/${key}`);
  if (!res.ok) { body.textContent = "Could not load this document. Try again."; return; }
  if (!res.body.published || !res.body.body) { body.textContent = "Not published yet"; return; }
  if (res.body.title) $("#legalTitle").textContent = res.body.title;
  body.textContent = res.body.body;
}
function openForgot() {
  const box = $("#forgotContacts"); box.replaceChildren();
  const contacts = (signinContent && signinContent.contacts) || [];
  const support = contacts.find(contact => /customer\s*support/i.test(contact.label || ""));
  const chosen = support || contacts[0];
  const hint = document.createElement("p"); hint.className = "forgot-note";
  if (!chosen) {
    hint.textContent = "No data yet. Ask your Administrator to publish a Customer Support contact.";
    box.appendChild(hint);
  } else {
    hint.textContent = support
      ? "Contact this team to have your password reset:"
      : "Customer Support is not configured yet. The Administrator's published contact is:";
    box.append(hint, contactBox(chosen));
  }
  const dialog = $("#forgotDialog");
  if (!dialog.open) dialog.showModal();
}
function bindSignInPage() {
  applySavedId();
  $("#promoPrev").addEventListener("click", () => { showPromo(promoIndex - 1); startPromoRotation(); });
  $("#promoNext").addEventListener("click", () => { showPromo(promoIndex + 1); startPromoRotation(); });
  const promo = $("#promo");
  promo.addEventListener("mouseenter", () => { promoPaused = true; stopPromoRotation(); });
  promo.addEventListener("mouseleave", () => { promoPaused = false; startPromoRotation(); });
  promo.addEventListener("focusin", () => { promoPaused = true; stopPromoRotation(); });
  promo.addEventListener("focusout", () => { promoPaused = false; startPromoRotation(); });
  document.addEventListener("visibilitychange", startPromoRotation);
  $("#forgotBtn").addEventListener("click", openForgot);
  $$("[data-legal]").forEach(btn => btn.addEventListener("click", () => openLegal(btn.dataset.legal)));
  $("#legalClose").addEventListener("click", () => $("#legalDialog").close());
  $("#forgotClose").addEventListener("click", () => $("#forgotDialog").close());
  [$("#legalDialog"), $("#forgotDialog")].forEach(dialog => {
    dialog.addEventListener("click", e => { if (e.target === dialog) dialog.close(); });
  });
}

/* ---------- two-step verification (Administrator accounts) ---------- */
let totpUseRecovery = false;
let totpPending = null;

function showTotp(mode) {
  $("#login").classList.add("hide");
  $("#mustChange").classList.add("hide");
  $("#shell").classList.add("hide");
  $("#totp").classList.remove("hide");
  $("#totpForm").classList.remove("hide");
  $("#totpRecoveryBox").classList.add("hide");
  $("#totpErr").textContent = "";
  $("#totpCode").value = "";
  totpUseRecovery = false;
  totpPending = null;
  const setup = mode === "setup";
  $("#totpSetup").classList.toggle("hide", !setup);
  $("#totpRecoveryToggle").parentElement.classList.toggle("hide", setup);
  $("#totpCodeLabel").textContent = setup ? "Six-digit code from the app" : "Six-digit code from the app";
  $("#totpCode").setAttribute("maxlength", "12");
  $("#totpCode").setAttribute("inputmode", "numeric");
  $("#totpBtn").textContent = setup ? "Confirm and continue" : "Verify and continue";
  if (setup) {
    $("#totpTitle").textContent = "Set up two-step verification";
    $("#totpHint").textContent = "Administrator accounts need Google Authenticator in addition to the password. Add the key below, then enter the six-digit code it shows.";
    loadTotpSetup();
  } else {
    $("#totpTitle").textContent = "Two-step verification";
    $("#totpHint").textContent = "Enter the six-digit code from Google Authenticator to finish signing in.";
    $("#totpCode").focus();
  }
}

async function loadTotpSetup() {
  $("#totpSecret").textContent = "…";
  $("#totpAccount").textContent = "";
  const res = await api("/api/auth/2fa/setup");
  if (!res.ok) {
    $("#totpSecret").textContent = "";
    $("#totpErr").textContent = detail(res.body) || "Setup could not start. Sign in again.";
    return;
  }
  $("#totpSecret").textContent = res.body.secret;
  $("#totpAccount").textContent = res.body.account || "";
  $("#totpCode").focus();
}

async function totpSubmit(e) {
  e.preventDefault();
  const setup = !$("#totpSetup").classList.contains("hide");
  const value = $("#totpCode").value.trim();
  const err = $("#totpErr"), btn = $("#totpBtn");
  err.textContent = "";
  if (!value) { err.textContent = setup || !totpUseRecovery ? "Enter the six-digit code." : "Enter a recovery code."; return; }
  btn.disabled = true;
  const path = setup ? "/api/auth/2fa/confirm" : "/api/auth/2fa/verify";
  const body = (!setup && totpUseRecovery) ? {recovery_code: value} : {code: value};
  const res = await api(path, {method: "POST", body});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body) || "That code was not accepted."; return; }
  if (setup) {
    totpPending = res.body;
    $("#totpCodes").innerHTML = (res.body.recovery_codes || []).map(c => `<span>${esc(c)}</span>`).join("");
    $("#totpForm").classList.add("hide");
    $("#totpRecoveryBox").classList.remove("hide");
    $("#totpDone").focus();
    return;
  }
  const me = await api("/api/auth/me");
  enter(me.ok ? me.body : res.body);
}

function totpToggleRecovery() {
  totpUseRecovery = !totpUseRecovery;
  $("#totpCodeLabel").textContent = totpUseRecovery ? "Recovery code" : "Six-digit code from the app";
  $("#totpCode").setAttribute("maxlength", totpUseRecovery ? "11" : "12");
  $("#totpCode").setAttribute("inputmode", totpUseRecovery ? "text" : "numeric");
  $("#totpRecoveryToggle").textContent = totpUseRecovery ?
    "Use the authenticator code instead" : "Use a recovery code instead";
  $("#totpCode").value = "";
  $("#totpCode").focus();
}
async function boot() {
  const me = await api("/api/auth/me");
  if (me.ok) enter(me.body);
  else { $("#login").classList.remove("hide"); refreshSignInContent(); }
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
  const isAdminRole = !!state.user && String(state.user.role || "").trim().toLowerCase() === "admin";
  const [h, mo, p, w, b, o, ds, so, ap, ld, us, rl, em, pcat, sp, bc, co, rt, sl, st, inv, cn, dn, ao, ae, ag, fy, pl, da, ff] = await Promise.all([
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
    canAccounts ? api("/api/accounts/financial-years") : none,
    canAccounts ? api("/api/accounts/period-locks") : none,
    api(`/api/dashboard?${dashQuery()}`),
    isAdminRole ? api("/api/features") : none]);
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
  state.featureFlags = ff.ok ? ff.body : [];
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
  if (fy.ok) state.accounts.years = fy.body;
  state.accounts.locks = pl.ok ? pl.body : [];
  $("#env").textContent = h.ok ? `Environment: ${h.body.env}` : "Service unreachable";
  const failed = [p, w, b, o, ds, so, canApprovals ? ap : null, ld, sp].find(r => r && !r.ok);
  if (failed) toast(failed, "Some data could not be loaded");
  renderAll();
  if (state.view === "products" && state.plist.loaded) loadProductList();
  // A save refreshes the cache; a list that has already paged must re-read the
  // server so its page and total stay true to the new record.
  if (LIST_SPEC[state.view] && listState(state.view).loaded) loadList(state.view);
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
const TITLES = WS.TITLES;
const VIEW_PERM = WS.VIEW_PERM;
function route() {
  closeDashRange();
  // A hash may carry a query (`#/accounts/gst-out?from=...&to=...`) so a KPI
  // card can open its own report with the same window. The query is read here
  // and applied after the section has rendered.
  const raw = location.hash.replace(/^#\//, "") || "dash";
  const slash = raw.indexOf("/");
  let v = slash < 0 ? raw : raw.slice(0, slash);
  let sub = slash < 0 ? "" : raw.slice(slash + 1);
  let query = "";
  const qMark = sub.indexOf("?");
  if (qMark >= 0) { query = sub.slice(qMark + 1); sub = sub.slice(0, qMark); }
  const vMark = v.indexOf("?");
  if (vMark >= 0) {
    query = v.slice(vMark + 1) + (query ? "&" + query : "");
    v = v.slice(0, vMark);
  }
  const hashParams = new URLSearchParams(query);
  // Customers and distributors are one master. The older address still opens
  // the screen, so dashboard drill-downs, links and bookmarks keep working.
  if (v === "distributors") v = "customers";
  // One predicate serves the route, the menu, the tabs and the breadcrumb, so a
  // screen the role may not open cannot be reached through any of them.
  state.view = wsViewOk(v) ? v : "dash";
  $("#shell").dataset.view = state.view;
  if (state.view === "inventory") state.tab = ["stock", "ledger", "warehouses"].includes(sub) ? sub : "stock";
  if (state.view === "scheduled") state.sr.tab = ["schedules", "recipients", "log"].includes(sub) ? sub : "schedules";
  $$(".view").forEach(s => s.classList.toggle("hide", s.id !== "v-" + state.view));
  $$(".nav[data-v]").forEach(a => { const on = a.dataset.v === state.view; a.classList.toggle("on", on); on ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"); });
  $("#title").textContent = TITLES[state.view];
  if (state.view === "inventory") showTab();
  renderHead();
  if (state.view === "reports") openReports();
  if (state.view === "audit") openAudit();
  if (state.view === "products") loadProductList();
  if (LIST_SPEC[state.view] && !listState(state.view).loaded) loadList(state.view);
  if (state.view === "lost") renderLost();
  if (state.view === "followups") renderFollowups();
  if (state.view === "customers") renderCustomers();
  if (state.view === "settings") renderSettings();
  if (state.view === "hr") {
    if (can("hr:read")) openHr(); else renderHr();
    // A gap link lands directly on the payroll list, where the missing month is opened.
    if (sub === "payroll" && can("hr:payroll_prepare")) hrPayroll();
  }
  if (state.view === "compare") loadCompare();
  if (state.view === "geo") loadGeo();
  if (state.view === "accounts") {
    const picked = ACC_SECTIONS.find(x => x.key === sub && accSectionAllowed(x));
    state.acc.section = picked ? picked.key : defaultAccountsSection();
    state.acc.payDue = hashParams.get("due") === "week" ? "week" : "";
    applyAccountsSection();
    openAccountsReports();
    openAccountsStatements();
    // A card can land here with ?due=week after the statements were rendered;
    // re-draw them so the list matches the link that opened it.
    if (state.accounts.outstanding) renderAccounts();
    openAccountsSectionData();
    applyAccountsQuery(hashParams);
  }
  if (state.view === "expenses") { openExpenses(); applyExpensesQuery(hashParams); }
  if (state.view === "foc") openFoc();
  if (state.view === "scheduled") openScheduled();
  wsSync();
  document.title = `${TITLES[state.view]} - HERBANOVA`;
}
/* ---------- workspace: tabs, breadcrumbs, menu, favourites ---------- */
/* One hierarchy (workspace.js) renders the sidebar, the breadcrumb and the
   palette's screen list, so a path shown in the breadcrumb is a path in the
   menu, and every placement resolves to the same route. */
const WS_TABS = "hb.tabs";              // sessionStorage, one set per user
const WS_FAV = "hb.favourites";         // localStorage, this device only
const WS_RECENT = "hb.recent";          // localStorage, this device only

let wsModel = null;                     // {open: [tab], active, closed: [tab]}
let wsLastHash = "";                    // the address the screen was drawn for
let drawerDirty = false;                // the open drawer holds unsaved edits
let drawerSnap = "";

const wsCtx = () => ({can, features: state.features, srAllowed});
/* Once the server's hierarchy is in hand it is the narrower of the two: a view
   it left out was hidden for this account and must stay closed to the router,
   the tabs, the breadcrumb and the palette alike. While it is absent, loading
   or failed, the built-in hierarchy (also permission filtered) decides. */
const wsViewOk = v => WS.viewAllowed(v, wsCtx()) && (navState !== "ready" || WS.navAllows(v));
const wsArea = name => { try { return window[name]; } catch (e) { return null; } };
const wsStore = {
  get(area, base) {
    const store = wsArea(area);
    try { return store ? JSON.parse(store.getItem(base) || "null") : null; } catch (e) { return null; }
  },
  set(area, base, value) {
    const store = wsArea(area);
    try { if (store) store.setItem(base, JSON.stringify(value)); } catch (e) { /* storage blocked */ }
  },
};
const wsUserKey = base => `${base}:${(state.user && state.user.username) || "anon"}`;
const wsFavourites = () => {
  const v = wsStore.get("localStorage", wsUserKey(WS_FAV));
  return Array.isArray(v) ? v.filter(k => typeof k === "string" && k) : [];
};
const wsRecents = () => {
  const v = wsStore.get("localStorage", wsUserKey(WS_RECENT));
  return Array.isArray(v) ? v.filter(k => typeof k === "string" && k) : [];
};

/* ---------- navigation source (Batch 4d, on by default) ----------
   `GET /api/navigation` renders the menu. The built-in hierarchy in
   workspace.js remains the fallback: it is drawn while the request is in
   flight, kept when the request fails, and restored on demand with
   ?nav=builtin. ?nav=api re-opts in; the choice is kept in sessionStorage
   because the router rewrites the hash and would drop the query on the next
   click. Either way the built-in rules still apply: wsViewOk() ANDs the two,
   so a server payload can only hide screens, never reveal one. */
const NAV_API_ENABLED = true;      // Batch 4d default for every browser
const NAV_OPT_IN = "hb.navApi";   // "api" | "builtin"
let navState = "builtin";         // builtin | loading | ready | error
let navError = "";
let navSeq = 0;

function navChoice() {
  let pick = "";
  const search = new URLSearchParams(location.search);
  const q = location.hash.indexOf("?");
  const fromUrl = search.get("nav")
    || (q >= 0 ? new URLSearchParams(location.hash.slice(q + 1)).get("nav") : "");
  if (fromUrl === "api" || fromUrl === "builtin") {
    try { const store = wsArea("sessionStorage"); if (store) store.setItem(NAV_OPT_IN, fromUrl); }
    catch (e) { /* storage blocked: this page still honours the query */ }
    pick = fromUrl;
  } else {
    try { const store = wsArea("sessionStorage"); pick = store ? store.getItem(NAV_OPT_IN) || "" : ""; }
    catch (e) { pick = ""; }
  }
  if (pick === "builtin") return false;
  if (pick === "api") return true;
  return NAV_API_ENABLED;
}
/* Cleared typing into the session, a retried request and a re-login all raise
   the sequence, so an answer from an earlier identity is thrown away instead
   of repainting another account's menu. */
function navReset() {
  navSeq += 1;
  WS.resetNavTree();
  navError = "";
  if (!navChoice()) {
    navState = "builtin";
    renderSideNav();
    return;
  }
  navState = "loading";
  renderSideNav();
  navFetch();
}
function navFallback(message) {
  navSeq += 1;
  navState = "error";
  navError = message;
  WS.resetNavTree();
  renderSideNav();
  renderCrumbs();
  renderFavBtn();
}
/* The retry button is only offered from the error state; a second request
   while one is in flight would just race its own answer. */
function navRefresh() {
  if (!state.user || navState === "builtin" || navState === "loading") return;
  navState = "loading";
  navError = "";
  renderSideNav();
  navFetch();
}
async function navFetch() {
  const seq = ++navSeq;
  const who = state.user && state.user.username;
  const res = await api("/api/navigation");
  if (seq !== navSeq || !state.user || state.user.username !== who) return;
  if (!res.ok) {
    if (res.status === 401) return;            // api() has already left the session
    navFallback(res.status === 0
      ? "Cannot reach the server, so the menu could not be loaded."
      : `The server could not supply the menu (HTTP ${res.status}).`);
    return;
  }
  const conv = WS.navFromApi(res.body);
  if (!conv.ok) {
    navFallback("The server sent a menu this screen cannot read.");
    return;
  }
  WS.setNavTree(conv.tree, conv.menu, conv.views);
  navState = "ready";
  navError = "";
  // Tabs, favourites and recents that this account may no longer open leave
  // with the screens they point at.
  if (wsModel) { wsModel = WS.pruneModel(wsModel, wsViewOk); wsSaveTabs(); }
  renderSideNav();
  renderTabs();
  renderCrumbs();
  renderFavBtn();
  if (!wsViewOk(state.view)) {
    const tab = wsLastTab();
    location.hash = tab && wsViewOk(tab.view) ? tab.hash : WS.HOME_HASH;
  }
}

function accSectionLabel(key) {
  const found = ACC_SECTIONS.find(s => s.key === key);
  return found ? found.label : "";
}
/* A tab names the screen, not the file: the accounts sections are separate
   tabs because each is a different report with its own address. */
function wsTabTitle(view, section) {
  if (view === "accounts") return section ? (accSectionLabel(section) || TITLES[view]) : TITLES[view];
  return TITLES[view] || "Screen";
}
function wsCurrentKey() {
  if (state.view === "dash") return WS.HOME;
  return WS.canonicalKey(state.view, state.view === "accounts" ? state.acc.section : "");
}
function wsKeyAllowed(key) {
  const p = WS.parseHash("#/" + key);
  return wsViewOk(p.view);
}
function wsSaveTabs() {
  const store = wsArea("sessionStorage");
  if (!store || !wsModel) return;
  try { store.setItem(wsUserKey(WS_TABS), WS.serializeModel(wsModel)); } catch (e) { /* storage blocked */ }
}
function wsClearTabs() {
  const store = wsArea("sessionStorage");
  if (!store) return;
  try {
    Object.keys(store).filter(k => k.indexOf(WS_TABS + ":") === 0).forEach(k => store.removeItem(k));
  } catch (e) { /* storage blocked */ }
}
/* A login starts from Home; a re-enter (TOTP, password change) keeps the strip. */
function wsEnter() {
  if (!wsModel) {
    const store = wsArea("sessionStorage");
    let raw = null;
    try { raw = store ? store.getItem(wsUserKey(WS_TABS)) : null; } catch (e) { raw = null; }
    wsModel = WS.pruneModel(raw ? WS.deserializeModel(raw) : WS.initialModel(), wsViewOk);
  }
  renderNavExtra();
  renderFavBtn();
}
function wsLastTab() {
  return wsModel ? wsModel.open.find(t => t.key === wsModel.active) || null : null;
}
function wsGoActive() {
  const tab = wsLastTab();
  if (!tab) return;
  if (tab.hash === location.hash) route(); else location.hash = tab.hash;
}
function wsActivate(key) {
  if (!wsModel) return;
  const tab = wsModel.open.find(t => t.key === key);
  if (!tab) return;
  if (tab.key !== wsModel.active && drawerOpen() && !requestCloseDrawer()) return;
  wsModel = WS.activateTab(wsModel, key);
  wsSaveTabs();
  closeTabMenu();
  if (drawerOpen()) closeDrawer();
  wsGoActive();
}

function wsDrawerTouched() {
  if (!drawerOpen()) return;
  drawerDirty = drawerFormSnapshot() !== drawerSnap;
}
/* The form lives in the shared drawer; every field is compared to the snapshot
   taken when it opened, so a reopened record never inherits a stale "dirty". */
function drawerFormSnapshot() {
  const body = $("#dbody");
  if (!body) return "";
  return $$("input,select,textarea", body).map(el => {
    if (el.type === "hidden" || el.type === "file") return "";
    if (el.type === "checkbox" || el.type === "radio") return el.checked ? "1" : "0";
    return el.value;
  }).join("\u0001");
}
function confirmDiscard(what) {
  return window.confirm(`You have unsaved changes in ${what || "this form"}. Discard them?`);
}
function requestCloseDrawer() {
  if (!drawerOpen()) return true;
  if (drawerDirty && !confirmDiscard($("#dtitle").textContent)) return false;
  closeDrawer();
  return true;
}
function wsCloseTab(key) {
  if (!wsModel || key === WS.HOME) return;
  const active = wsModel.active === key;
  if (active && !requestCloseDrawer()) return;
  wsModel = WS.closeTab(wsModel, key);
  wsSaveTabs();
  renderTabs();
  renderNavExtra();
  if (!active) return;
  wsGoActive();
}
function wsCloseSiblings(keep) {
  if (!wsModel) return;
  if (wsModel.active !== keep && !requestCloseDrawer()) return;
  wsModel = keep === WS.HOME ? WS.closeAll(wsModel) : WS.closeOthers(wsModel, keep);
  wsSaveTabs();
  renderTabs();
  renderNavExtra();
  if (drawerOpen()) closeDrawer();
  wsGoActive();
}
function wsReopen() {
  if (!wsModel) return;
  const result = WS.reopenClosed(wsModel);
  if (!result.tab) return;
  wsModel = result.model;
  wsSaveTabs();
  renderTabs();
  renderNavExtra();
  wsGoActive();
}

/* ---------- tab strip ---------- */
function tabElementId(key) {
  return "tab-" + key.replace(/[^a-z0-9]+/gi, "-");
}
function renderTabs() {
  const strip = $("#tabstrip");
  if (!strip || !wsModel) return;
  const focusInside = strip.contains(document.activeElement);
  strip.innerHTML = wsModel.open.map(t => {
    const on = t.key === wsModel.active;
    return `<div class="tab${on ? " on" : ""}${t.closable ? "" : " pinned"}" role="tab"
        id="${tabElementId(t.key)}" aria-selected="${on}" aria-controls="v-${esc(t.view)}"
        tabindex="${on ? 0 : -1}" data-key="${esc(t.key)}" title="${esc(t.title)}">
        <span class="tab-main">${esc(t.title)}</span>
        ${t.closable ? `<button class="tab-x" type="button" data-act="tab-close" data-key="${esc(t.key)}"
          tabindex="-1" aria-label="Close ${esc(t.title)}">×</button>` : ""}
      </div>`;
  }).join("");
  if (focusInside) {
    const active = $("#" + tabElementId(wsModel.active));
    if (active) active.focus();
  }
  fitTabs();
}
/* The strip never scrolls sideways on a desktop width: the tabs that do not fit
   move into the overflow menu, which still lists every open screen. */
function fitTabs() {
  const strip = $("#tabstrip"), more = $("#tabMore");
  if (!strip || !more || !wsModel) return;
  const tabs = $$(".tab", strip);
  tabs.forEach(t => t.classList.remove("away"));
  if (!tabs.length) { more.classList.add("hide"); return; }
  more.classList.remove("hide");
  const overflow = () => strip.scrollWidth > strip.clientWidth + 1;
  if (!overflow()) { more.classList.add("hide"); return; }
  const activeId = tabElementId(wsModel.active);
  for (let i = tabs.length - 1; i >= 0 && overflow(); i--) {
    if (tabs[i].id === activeId || tabs[i].dataset.key === WS.HOME) continue;
    tabs[i].classList.add("away");
  }
  if (overflow()) {
    const home = tabs.find(t => t.dataset.key === WS.HOME);
    if (home && home.id !== activeId) home.classList.add("away");
  }
}
function renderTabMenu() {
  const menu = $("#tabMenu");
  if (!menu || !wsModel) return;
  const closable = wsModel.open.filter(t => t.closable).length;
  const current = wsLastTab();
  menu.innerHTML = `<h3>Open screens</h3>
    ${wsModel.open.map(t => `<button role="menuitem" type="button" data-act="tab-go" data-key="${esc(t.key)}"
      ${t.key === wsModel.active ? "disabled" : ""}>${esc(t.title)}${t.closable ? "" : " · pinned"}</button>`).join("")}
    <div class="tab-menu-sep" role="separator"></div>
    <button role="menuitem" type="button" data-act="tab-close" data-key="${esc(wsModel.active)}"
      ${current && current.closable ? "" : "disabled"}>Close current tab</button>
    <button role="menuitem" type="button" data-act="tab-close-others" ${closable ? "" : "disabled"}>Close other tabs</button>
    <button role="menuitem" type="button" data-act="tab-close-all" ${closable ? "" : "disabled"}>Close all except Home</button>
    <button role="menuitem" type="button" data-act="tab-reopen" ${wsModel.closed.length ? "" : "disabled"}>Reopen closed tab</button>`;
}
function openTabMenu() {
  renderTabMenu();
  $("#tabMenu").classList.remove("hide");
  $("#tabMore").setAttribute("aria-expanded", "true");
}
function closeTabMenu() {
  const menu = $("#tabMenu");
  if (menu) menu.classList.add("hide");
  const btn = $("#tabMore");
  if (btn) btn.setAttribute("aria-expanded", "false");
}
function toggleTabMenu() {
  const menu = $("#tabMenu");
  if (!menu) return;
  menu.classList.contains("hide") ? openTabMenu() : closeTabMenu();
}

/* ---------- breadcrumb ---------- */
function renderCrumbs() {
  const box = $("#crumbs");
  if (!box || !state.user) return;
  const section = state.view === "accounts" ? accSectionLabel(state.acc.section) : "";
  const path = WS.crumbPath(state.view, section, wsViewOk);
  if (!path.length) { box.innerHTML = ""; box.classList.add("hide"); return; }
  box.classList.remove("hide");
  box.innerHTML = "<ol>" + path.map(c => {
    if (c.current) return `<li><span aria-current="page">${esc(c.label)}</span></li>`;
    return c.view ? `<li><a href="#/${esc(c.view)}">${esc(c.label)}</a></li>`
                  : `<li><span>${esc(c.label)}</span></li>`;
  }).join("") + "</ol>";
}

/* ---------- menu, favourites and recents ---------- */
function navRow(v) {
  const ids = WS.MENU_IDS[v] || {};
  return `<a class="nav" href="#/${esc(v)}" data-v="${esc(v)}"${ids.id ? ` id="${ids.id}"` : ""}>${esc(TITLES[v])}`
    + `${ids.count ? `<span class="count hide" id="${ids.count}"></span>` : ""}</a>`;
}
/* The menu is built per role, so a badge is absent whenever its row is absent.
   A renderer must not fail because the screen it belongs to is not in the menu. */
function setBadge(id, n, label) {
  const c = $("#" + id);
  if (!c) return;
  c.textContent = n; c.classList.toggle("hide", !n); c.setAttribute("aria-label", label);
}
function renderSideNav() {
  const nav = $("#sideNav");
  if (!nav) return;
  $$(".nav-module", nav).forEach(el => el.remove());
  const frag = document.createDocumentFragment();
  WS.navTree().forEach(mod => {
    const cats = [];
    mod.categories.forEach(cat => {
      const rows = [];
      cat.groups.forEach(g => g.views.forEach(v => { if (WS.menuAllowed(v, wsCtx())) rows.push(v); }));
      if (rows.length) cats.push({label: cat.label, rows});
    });
    if (!cats.length) return;
    const box = document.createElement("div");
    box.className = "nav-module";
    box.innerHTML = `<p class="nav-mod">${esc(mod.label)}</p>` + cats.map(c =>
      `<div class="nav-group">${c.label ? `<p class="nav-grp">${esc(c.label)}</p>` : ""}`
      + c.rows.map(navRow).join("") + "</div>").join("");
    frag.appendChild(box);
  });
  nav.appendChild(frag);
  renderNavExtra();
}
/* Server-menu states. A failed load keeps the built-in menu (already filtered
   by permissions) and says so, rather than dropping the menu or opening every
   module. */
function navStatusHtml() {
  if (navState === "loading")
    return `<div class="nav-alert" role="status">Loading the menu…</div>`;
  if (navState !== "error") return "";
  return `<div class="nav-alert" role="alert">
      <b>The menu could not be loaded</b>
      <p>${esc(navError)}</p>
      <p class="nav-alert-sub">Showing the built-in menu for this role.</p>
      <button class="btn ghost sm" type="button" data-act="nav-retry">Retry</button>
    </div>`;
}
function renderNavExtra() {
  const box = $("#navExtra");
  if (!box || !state.user) return;
  const favs = wsFavourites().filter(wsKeyAllowed);
  const recents = wsRecents().filter(k => wsKeyAllowed(k) && favs.indexOf(k) < 0).slice(0, 6);
  const row = k => {
    const p = WS.parseHash("#/" + k);
    return `<a class="nav" href="#/${esc(k)}" data-wskey="${esc(k)}">${esc(wsTabTitle(p.view, p.section))}</a>`;
  };
  box.innerHTML = navStatusHtml()
    + (favs.length ? `<div class="nav-group" aria-label="Favourites">
      <p class="nav-grp">Favourites</p>${favs.map(row).join("")}</div>` : "")
    + (recents.length ? `<div class="nav-group" aria-label="Recently opened">
      <p class="nav-grp">Recently opened</p>${recents.map(row).join("")}</div>` : "");
}
function renderFavBtn() {
  const btn = $("#favBtn");
  if (!btn) return;
  const key = wsCurrentKey();
  const show = !!state.user && state.view !== "dash" && wsViewOk(state.view);
  btn.classList.toggle("hide", !show);
  if (!show) return;
  const on = wsFavourites().indexOf(key) >= 0;
  btn.setAttribute("aria-pressed", String(on));
  btn.textContent = on ? "★" : "☆";
  btn.title = on ? "Remove from favourites" : "Add to favourites";
  btn.setAttribute("aria-label", btn.title);
}

/* Called at the end of route(): the rendered screen becomes the active tab. */
function wsSync() {
  if (!state.user) return;
  const view = state.view;
  const parsed = WS.parseHash(location.hash);
  // A screen the role may not open leaves no permission-shaped address behind;
  // the route has already fallen back to Home, so the address follows it.
  if (parsed.view !== "dash" && !wsViewOk(parsed.view)) {
    history.replaceState(null, "", WS.HOME_HASH);
  }
  const section = view === "accounts" ? (state.acc.section || "")
    : (parsed.view === view ? parsed.section : "");
  const q = parsed.view === view && parsed.hash.indexOf("?") >= 0
    ? parsed.hash.slice(parsed.hash.indexOf("?")) : "";
  const hash = view === "dash" ? WS.HOME_HASH
    : "#/" + view + (section ? "/" + section : "") + q;
  if (!wsModel) wsModel = WS.initialModel();
  wsModel = WS.openTab(wsModel, {
    view, section: view === "accounts" ? section : "", hash, title: wsTabTitle(view, section),
  });
  if (view !== "dash") {
    wsStore.set("localStorage", wsUserKey(WS_RECENT),
                WS.pushRecent(wsRecents(), WS.canonicalKey(view, section), 6));
  }
  wsLastHash = location.hash;
  wsSaveTabs();
  renderTabs();
  renderCrumbs();
  renderNavExtra();
  renderFavBtn();
}

function showTab() {
  $$("[data-tab]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
  ["stock", "ledger", "warehouses"].forEach(t => $("#i-" + t).classList.toggle("hide", t !== state.tab));
  if (state.tab === "ledger" && !state.movements) loadMovements();
}
/* The header may count a status breakdown only from the 200-row cache, so it
   says so only while the cache covers the server's total. The headline count
   always comes from the server page's X-Total-Count once that page has loaded. */
function listTotal(key) {
  const s = listState(key);
  return s.loaded && s.total != null ? s.total : null;
}
function listCovers(cache, total) {
  return total == null || cache.length >= total;
}
/* A breakdown describes the whole cache, so it is only shown for the screen's
   default view. Under a search or a narrower filter the header states the
   server's total for that view and nothing more. */
const LIST_DEFAULT_FILTER = {
  suppliers: () => state.supFilter === "all",
  customers: () => state.distFilter === "all",
  sales: () => state.soFilter === "all",
  purchasing: () => state.poFilter === "all",
  billing: () => state.invFilter === "all",
  approvals: () => state.apFilter === "pending",
  leads: () => state.ldFilter === "open" && state.ldOwner === "all",
};
function listNarrowed(key) {
  const s = listState(key);
  const isDefault = LIST_DEFAULT_FILTER[key] ? LIST_DEFAULT_FILTER[key]() : true;
  return !!s.q || !isDefault;
}
/* The rows a header breakdown may count: the server page when it already holds
   every matching row, otherwise the shared cache. */
function listBreakdownRows(key, total, cache) {
  const s = listState(key);
  return s.loaded && listCovers(s.rows, total) ? s.rows : cache;
}

function renderHead() {
  const v = state.view; let sub = "", act = "";
  if (v === "dash") {
    sub = "Every figure is counted by the server over the whole database. Open a tile to see the records behind it.";
    if (can("db:reset")) act = `<button class="btn" data-act="reset-db" type="button">Reset database</button>`;
  }
  if (v === "compare") {
    sub = "One month beside the previous month and the same month last year. Every figure is counted by the server.";
  }
  if (v === "geo") {
    sub = "Sales, returns and GST by the buyer state frozen on each issued invoice. District and city are not recorded, so the page stops at state.";
  }
  if (v === "products") {
    const p = state.plist;
    sub = p.loaded && p.total != null
      ? `${plural(p.total, "product")}${p.q || p.status ? " matching the filters" : " on file"}.`
      : `${plural(state.products.length, "product")} on file, ${state.products.filter(x => x.status === "active").length} active.`;
    act = `${can("product:read") ? `<button class="btn ghost" data-act="export-products" type="button">Export CSV</button>` : ""}${can("product:write") ? `<button class="btn" data-act="new-product" type="button">New product</button>` : ""}`;
  }
  if (v === "inventory") {
    sub = "Stock by batch, the movement ledger and warehouses.";
    if (state.tab === "warehouses" && can("stock:write")) act = `<button class="btn" data-act="new-warehouse" type="button">New warehouse</button>`;
  }
  if (v === "purchasing") {
    const total = listTotal("purchasing");
    const rows = listBreakdownRows("purchasing", total, state.pos);
    const n = s => rows.filter(x => x.status === s).length;
    sub = listCovers(rows, total) && !listNarrowed("purchasing")
      ? `${n("open")} open, ${n("partially_received")} part received, ${n("received")} received, ${n("cancelled")} cancelled.`
      : `${plural(total != null ? total : state.pos.length, "purchase order")}.`;
    act = `<button class="btn ghost" data-act="export-list" data-list="purchasing" type="button">Export CSV</button>`
        + (can("stock:write") ? ` <button class="btn" data-act="new-po" type="button">New purchase order</button>` : "");
  }
  if (v === "suppliers") {
    const pending = state.bankChanges.filter(b => b.status === "pending").length;
    const total = listTotal("suppliers");
    const rows = listBreakdownRows("suppliers", total, state.suppliers);
    const incomplete = rows.filter(s => s.needs_completion).length;
    sub = listCovers(rows, total) && !listNarrowed("suppliers")
      ? `${plural(total != null ? total : state.suppliers.length, "supplier")}. ${pending} bank change${pending === 1 ? "" : "s"} awaiting approval, ${incomplete} still to be completed.`
      : `${plural(total, "supplier")}.`;
    act = `<button class="btn ghost" data-act="export-list" data-list="suppliers" type="button">Export CSV</button>`
        + (can("supplier:write") ? ` <button class="btn" data-act="new-supplier" type="button">New supplier</button>` : "");
  }
  if (v === "sales") {
    const total = listTotal("sales");
    const rows = listBreakdownRows("sales", total, state.orders);
    const n = c => rows.filter(o => o.status === c).length;
    sub = listCovers(rows, total) && !listNarrowed("sales")
      ? `${n("approved")} ready to dispatch, ${n("pending_approval")} awaiting approval, ${n("draft")} draft.`
      : `${plural(total != null ? total : state.orders.length, "sales order")}.`;
    act = `<button class="btn ghost" data-act="export-list" data-list="sales" type="button">Export CSV</button>`
        + (can("sales:write") ? ` <button class="btn" data-act="new-so" type="button">New sales order</button>` : "");
  }
  if (v === "billing") {
    const total = listTotal("billing");
    const rows = listBreakdownRows("billing", total, state.invoices);
    const issued = rows.filter(i => i.status === "issued").length;
    const corrected = state.creditNotes.length + state.debitNotes.length;
    sub = listCovers(rows, total) && !listNarrowed("billing")
      ? `${plural(total != null ? total : state.invoices.length, "tax invoice")}, ${issued} live. ${plural(corrected, "credit or debit note")}. An issued invoice is never edited: correct it with a note.`
      : `${plural(total, "tax invoice")}. An issued invoice is never edited: correct it with a note.`;
    act = `<button class="btn ghost" data-act="export-list" data-list="billing" type="button">Export CSV</button>`;
  }
  if (v === "accounts") {
    const out = state.accounts.outstanding;
    sub = out
      ? `${money(out.receivable_total)} receivable, ${money(out.payable_total)} payable, from the documents as they stand.`
      : "Outstanding, ledgers, GST registers and the trial balance, all built from the documents.";
    if (can("accounts:reports")) sub += " The performance section compares any window with the previous month and the same month last year.";
    if (can("accounts:write")) {
      act = `<button class="btn" data-act="new-entry" data-kind="receipt" type="button">Record receipt</button>`
          + ` <button class="btn ghost" data-act="new-entry" data-kind="payment" type="button">Record payment</button>`;
    }
  }
  if (v === "approvals") {
    const total = listTotal("approvals");
    const rows = listBreakdownRows("approvals", total, state.approvals);
    const waiting = rows.filter(a => a.status === "pending").length;
    sub = state.apFilter === "pending" && !listNarrowed("approvals") && total != null
      ? `${total} waiting for a decision. The person who raised an order cannot approve it.`
      : listCovers(rows, total) && !listNarrowed("approvals")
        ? `${waiting} waiting for a decision. The person who raised an order cannot approve it.`
        : `${plural(total, "request")} in this view. The person who raised an order cannot approve it.`;
    act = `<button class="btn ghost" data-act="export-list" data-list="approvals" type="button">Export CSV</button>`;
  }
  if (v === "leads") {
    const total = listTotal("leads");
    const rows = listBreakdownRows("leads", total, state.leads);
    const od = rows.filter(l => l.follow_up_state === "overdue").length,
          td = rows.filter(l => l.follow_up_state === "today").length;
    sub = listCovers(rows, total) && !listNarrowed("leads")
      ? `${od} overdue and ${td} due today across the team. Only a lead’s owner or an administrator can change it.`
      : `${plural(total != null ? total : state.leads.length, "lead")}. Only a lead’s owner or an administrator can change it.`;
    act = `<button class="btn ghost" data-act="export-list" data-list="leads" type="button">Export CSV</button>`
        + (can("lead:write") ? ` <button class="btn" data-act="new-lead" type="button">New lead</button>` : "");
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
    const total = listTotal("customers");
    const rows = listBreakdownRows("customers", total, state.dists);
    const active = rows.filter(d => d.status === "active").length;
    const blocked = rows.filter(d => d.status === "blocked").length;
    const incomplete = rows.filter(d => d.needs_completion).length;
    sub = listCovers(rows, total) && !listNarrowed("customers")
      ? `${plural(total != null ? total : state.dists.length, "record")} in one customer and distributor master. Active: ${active}, Blocked: ${blocked}${incomplete ? `, needing details: ${incomplete}` : ""}. Credit in use counts orders awaiting approval, approved and dispatched.`
      : `${plural(total, "record")} in one customer and distributor master. Credit in use counts orders awaiting approval, approved and dispatched.`;
    act = `<button class="btn ghost" data-act="export-list" data-list="customers" type="button">Export CSV</button>`
        + (can("distributor:write") ? ` <button class="btn" data-act="new-dist" type="button">New customer or distributor</button>` : "");
  }
  if (v === "hr") {
    const d = state.hr.dashboard;
    sub = d ? `${d.active_employees} active of ${d.total_employees} employees. ${d.pending_approvals} HR approvals pending.`
            : "Employee records, attendance, leave, on-duty and payroll, integrated with Approvals and Reports.";
    if (can("hr:write")) act = `<button class="btn" data-act="hr-employees" type="button">Employee master</button>`;
  }
  if (v === "settings") sub = "Roles, logins, employees, tax configuration, HR policies and the audit trail.";
  if (v === "scheduled") {
    const s = state.sr.status;
    sub = s
      ? `${s.mode === "live" ? "Live mode" : "Test mode"}: ${state.sr.schedules.filter(x => x.enabled).length} of ${plural(state.sr.schedules.length, "schedule")} on. ${s.send_enabled ? "Sending is enabled." : "Sending is disabled."}`
      : "Administrator only. Schedules, recipients and the delivery log, with every send audited.";
  }
  if (v === "reports") sub = "Every figure is checked against the records it comes from. Downloads are recorded in the audit log.";
  if (v === "roles") {
    const rights = PERM_ITEMS().filter(i => i.admin_only).length;
    sub = `${plural(state.roles.length, "role")} and ${plural(PERM_ITEMS().length, "permission")}. ${state.featureFlags.length} module switch${state.featureFlags.length === 1 ? "" : "es"}; ${rights} right${rights === 1 ? " is" : "s are"} reserved for the Administrator.`;
    const btn = [`<button class="btn ghost" data-act="new-role" type="button">New role</button>`];
    if (can("user:manage")) btn.push(`<a class="btn ghost" href="#/users">Logins and employees</a>`);
    act = btn.join(" ");
  }
  if (v === "users") {
    const locked = state.users.filter(u => u.locked).length, pending = state.users.filter(u => u.must_change_password).length;
    sub = `${plural(state.users.length, "login")} and ${plural(state.employees.length, "employee")}. ${pending} awaiting a password change, ${locked} locked. Temporary passwords are shown once.`;
    const btn = [];
    if (can("employee:write")) btn.push(`<button class="btn ghost" data-act="new-employee" type="button">New employee</button>`);
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

/* One footer pager for every list screen. The range and total come from the
   server's X-Total-Count; the page size is offered in the same footer. */
const PG_SIZES = [25, 50, 100, 200];
function pagerHtml(p, key = "products") {
  if (p.total == null) return "";
  const size = p.size || 50;
  const pages = Math.max(1, Math.ceil(p.total / size));
  const page = Math.min(Math.max(1, p.page || 1), pages);
  const first = p.total ? (page - 1) * size + 1 : 0;
  const last = p.total ? Math.min(page * size, p.total) : 0;
  const btn = (to, label, off, name) =>
    `<button class="btn ghost sm" type="button" data-act="list-page" data-list="${key}" data-page="${to}" aria-label="${name}"${off ? " disabled" : ""}>${label}</button>`;
  return `<span class="pager-count">${p.total ? `${qty(first)}–${qty(last)} of ${qty(p.total)}` : "0 of 0"}</span>
    <div class="pager-nav">${btn("first", "«", page <= 1, "First page")}${btn("prev", "‹", page <= 1, "Previous page")}
      <span class="pager-page">Page <b>${page}</b> of ${pages}</span>
      ${btn("next", "›", page >= pages, "Next page")}${btn("last", "»", page >= pages, "Last page")}</div>
    <label class="pager-size">Rows per page<select data-act="list-size" data-list="${key}" aria-label="Rows per page">${PG_SIZES.map(n => `<option value="${n}"${n === size ? " selected" : ""}>${n}</option>`).join("")}</select></label>`;
}
const MOVE = {receipt: ["Goods received", "ok"], issue: ["Issued", "off"], transfer: ["Transferred", "off"],
              adjust: ["Adjustment", "warn"], return: ["Returned", "off"], reversal: ["Reversal", "warn"]};

/* ---------- renderers ---------- */
function renderAll() { renderHead(); renderDash(); renderCompare(); renderGeo(); renderProducts(); renderStock(); renderLedger(); renderWarehouses(); renderPOs(); renderSuppliers(); renderTax(); renderSales(); renderBilling(); renderAccounts(); renderAccountsReport(); renderExpenses(); renderFoc(); renderApprovals(); renderLeads(); renderUsers(); renderLost(); renderFollowups(); renderCustomers(); renderSettings(); renderScheduled(); if (state.view === "hr") renderHr(); }

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
  renderDashRange();
  $$("[data-dash-preset]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.dashPreset === state.dashPreset)));
  const dateErr = $("#dashDateErr");
  dateErr.textContent = state.dashDateError;
  dateErr.classList.toggle("hide", !state.dashDateError);
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
    ? `Refreshing ${esc(period)}…`
    : `Selected period <b>${esc(period)}</b> (${esc(plural(d.range, "day"))}) · `
      + `snapshot cards are as at ${esc(fmtDate(d.as_of))} · updated ${esc(fmtStamp(d.generated_at))}`;

  renderAttention(d.attention || []);
  renderKpis(d.kpis || []);
  renderDashAccounts(d.accounts);
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
  setBadge("poCount", openTotal, `${openTotal} open purchase orders`);
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
  const sOn = c.sales_visible && !(state.chart.off && state.chart.off.sales);
  const pOn = c.purchases_visible && !(state.chart.off && state.chart.off.purchases);
  tip.innerHTML = `<b>${esc(fmtDate(pt.date))}</b>`
    + (sOn ? `<span><i class="key sales"></i>Sales ₹ ${money(pt.sales)}</span>` : "")
    + (pOn ? `<span><i class="key purchases"></i>Purchases ₹ ${money(pt.purchases)}</span>` : "");
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
  state.chart.off = state.chart.off || {};
  const sOn = !!c.sales_visible && !state.chart.off.sales;
  const pOn = !!c.purchases_visible && !state.chart.off.purchases;
  title.textContent = sOn && pOn ? "Sales and purchases"
    : sOn ? "Sales" : pOn ? "Purchases received" : "Sales and purchases";
  const onlyOne = (sOn ? 1 : 0) + (pOn ? 1 : 0) === 1;
  legend.innerHTML =
    (c.sales_visible ? `<button class="legend-pill sales" type="button" data-act="toggle-series" data-series="sales" aria-pressed="${sOn}"${onlyOne && sOn ? " aria-disabled=\"true\" title=\"One line must stay visible\"" : ""}><i></i>Sales</button>` : "")
    + (c.purchases_visible ? `<button class="legend-pill purchases" type="button" data-act="toggle-series" data-series="purchases" aria-pressed="${pOn}"${onlyOne && pOn ? " aria-disabled=\"true\" title=\"One line must stay visible\"" : ""}><i></i>Purchases</button>` : "");

  const series = c.series || [];
  if (!series.length) {
    svg.innerHTML = "";
    totals.innerHTML = `<span class="gap-note">No days fall in this period.</span>`;
    return;
  }

  const W = 760, x0 = 58, x1 = 744, y0 = 14, y1 = 218;
  const vals = [];
  series.forEach(p => {
    if (sOn && p.sales != null) vals.push(Number(p.sales));
    if (pOn && p.purchases != null) vals.push(Number(p.purchases));
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
  const area = sOn
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
    ${sOn ? area + `<path class="series-sales" d="${line("sales")}"/>` + dots("sales") : ""}
    ${pOn ? `<path class="series-purchases" d="${line("purchases")}"/>` + dots("purchases") : ""}
    ${hits}`;
  svg.setAttribute("aria-label",
    `${title.textContent} from ${from} to ${to}. `
    + (sOn ? `Sales total ${money(c.sales_total)} rupees. ` : "")
    + (pOn ? `Purchases total ${money(c.purchases_total)} rupees. ` : "")
    + "Use the left and right arrow keys to read each day.");
  state.chart.index = -1;

  const bits = [];
  if (sOn) bits.push(`<span><b>Sales</b> ₹ ${money(c.sales_total)} ${deltaText(c.sales_change)}</span>`);
  if (pOn) bits.push(`<span><b>Purchases</b> ₹ ${money(c.purchases_total)} ${deltaText(c.purchases_change)}</span>`);
  bits.push(`<span class="source-line">${esc(c.note || "")}</span>`);
  totals.innerHTML = bits.join("");
}

function toggleSeries(key) {
  const c = state.dashboard && state.dashboard.sales_vs_purchases;
  if (!c) return;
  state.chart.off = state.chart.off || {};
  const sOn = !!c.sales_visible && !state.chart.off.sales;
  const pOn = !!c.purchases_visible && !state.chart.off.purchases;
  const on = key === "sales" ? sOn : pOn;
  const other = key === "sales" ? pOn : sOn;
  if (on && !other) return; // the last visible line stays on
  state.chart.off[key] = !state.chart.off[key];
  renderChart(c);
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
  const total = list.reduce((s, w) => s + Number(w.units || w.used_units || 0), 0);
  const configured = list.filter(w => w.capacity_units !== null && w.capacity_units !== undefined);
  const tight = configured.filter(w => ["high", "over", "full"].includes(w.capacity_state));
  el.innerHTML = (list.length ? list.map(w => {
    const units = Number(w.units || w.used_units || 0);
    const share = total > 0 ? units / total * 100 : 0;
    const shareText = units > 0 && share < 0.5 ? "<1%" : `${share.toFixed(0)}%`;
    const hasCap = w.capacity_units !== null && w.capacity_units !== undefined;
    const pct = hasCap ? Math.max(0, Math.min(100, Number(w.utilisation_pct) || 0)) : share;
    const tone = hasCap && ["high", "over", "full"].includes(w.capacity_state) ? ` ${w.capacity_state}` : "";
    const detail = hasCap
      ? `${esc(qty(units))} of ${esc(qty(w.capacity_units))} units · ${Number(w.utilisation_pct).toFixed(1)}%`
      : `${esc(qty(units))} units`;
    const under = hasCap
      ? `${esc(qty(w.free_units))} units free`
      : `${shareText} of stock · capacity not set`;
    return `<li><div class="wh-top"><span><b>${esc(w.name)}</b><small>${plural(w.batches, "batch")} in stock</small></span>
      <span class="num">${detail}<small>${under}</small></span></div>
      <div class="wh-bar" aria-hidden="true"><i class="${tone.trim()}" style="width:${pct.toFixed(1)}%"></i></div></li>`;
  }).join("") : `<li><span class="none">No warehouse has been added yet.</span></li>`)
  + (tight.length
    ? `<li><span class="gap-note">${tight.length === 1 ? "One warehouse is" : `${tight.length} warehouses are`} above 80% of capacity: ${esc(tight.map(w => w.name).join(", "))}.</span></li>`
    : "")
  + (!configured.length
    ? `<li><span class="gap-note">Capacity is not set for any warehouse (GAP-D03), so a fill level against capacity cannot be shown.</span></li>`
    : "");
}

function renderOpenPos(o) {
  const el = $("#openpos"), note = $("#poNote");
  if (!o) {
    note.textContent = "";
    el.innerHTML = `<li><span class="none">Purchase orders are not available to your role.</span></li>`;
    return;
  }
  const rows = o.rows || [];
  const total = o.open_total ?? o.count ?? rows.length;
  const inRange = o.count ?? rows.length;
  note.textContent = (inRange > o.shown ? `Showing ${o.shown} of ${inRange} raised in this period. ` : "")
    + (total > inRange ? `${total - inRange} open order${total - inRange === 1 ? "" : "s"} raised outside it. ` : "")
    + (o.note || "");
  el.innerHTML = rows.length ? rows.map(p => {
    const pct = Math.max(0, Math.min(100, Number(p.pct_received) || 0));
    return `<li><div><button class="rowbtn" data-act="open-po" data-id="${p.id}" type="button">${esc(p.po_number)}</button>
      <small>${esc(p.supplier)} · ${esc(qty(p.received_units))} of ${esc(qty(p.ordered_units))} units received</small>
      <div class="wh-bar" aria-hidden="true"><i style="width:${pct.toFixed(1)}%"></i></div></div>
      <div class="r"><span class="num">₹ ${money(p.value)}<small>${pct.toFixed(0)}% received</small></span></div></li>`;
  }).join("") : `<li><span class="none">No purchase order is waiting for goods.</span></li>`;
}

let dashRejectId = null;

function renderDashApprovals(a) {
  const el = $("#approvalList"), note = $("#apNote");
  if (!a) {
    note.textContent = "";
    el.innerHTML = `<li><span class="none">Approvals are not available to your role.</span></li>`;
    return;
  }
  const rows = a.rows || [];
  note.textContent = (a.count > a.shown ? `Showing ${a.shown} of ${a.count}. ` : "")
    + (a.note || "");
  el.innerHTML = rows.length ? rows.map(x => {
    const me = state.user && x.requested_by === state.user.username;
    const amount = x.order_total != null ? `₹ ${money(x.order_total)}`
      : (x.requested_dates || "");
    const age = x.age_days == null ? ""
      : x.age_days === 0 ? "raised today" : `${plural(x.age_days, "day")} old`;
    const who = me ? "You raised this request"
      : (x.deciders || []).length ? `Awaiting ${x.deciders.join(" or ")}` : "";
    const overLimit = (x.reasons || []).includes("credit_limit");
    const meta = [x.request_type_label, x.requested_by, amount, age]
      .filter(Boolean).map(v => esc(v)).join(" · ");
    let acts = "";
    if (x.can_decide) {
      acts = dashRejectId === x.id
        ? `<form class="ap-reject" id="dashRejectForm" data-id="${x.id}" novalidate>
            <input name="reason" placeholder="Reason (required)" maxlength="300" autocomplete="off"
              aria-label="Reason for rejecting ${esc(x.request_no || x.document_number || "this request")}">
            <button class="btn sm" type="submit">Reject</button>
            <button class="btn ghost sm" type="button" data-act="dash-reject-cancel">Cancel</button>
            <div class="ap-err" role="alert"></div></form>`
        : `<div class="ap-acts">
            <button class="btn ghost sm" type="button" data-act="dash-reject" data-id="${x.id}">Reject</button>
            <button class="btn sm" type="button" data-act="dash-approve" data-id="${x.id}">Approve</button></div>`;
    }
    return `<li class="ap-row"><div>
      <button class="rowbtn" data-act="dash-ap" data-id="${x.id}" type="button">${esc(x.request_no || x.document_number || "Request")}</button>
      <small>${meta}</small>
      ${who ? `<small class="ap-who">${esc(who)}</small>` : ""}
      ${overLimit ? `<span class="chip bad">Over credit limit</span>` : ""}</div>
      ${acts}</li>`;
  }).join("")
    : `<li><span class="none">Nothing is waiting for a decision.</span></li>`;
}

async function dashApprove(id) {
  const res = await api(`/api/approvals/${id}/decide`, {
    method: "POST", body: {decision: "approve", reason: "Approved from the dashboard"}});
  toast(res, res.ok ? "Approved" : "Decision not saved");
  if (!res.ok) return;
  dashRejectId = null;
  await loadAll();
}

async function sendDashReject(form) {
  const err = $(".ap-err", form), reason = form.elements.reason.value.trim();
  err.textContent = "";
  if (reason.length < 3) {
    err.textContent = "Give a reason of at least three characters.";
    form.elements.reason.focus();
    return;
  }
  const res = await api(`/api/approvals/${form.dataset.id}/decide`, {
    method: "POST", body: {decision: "reject", reason}});
  toast(res, res.ok ? "Rejected" : "Decision not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  dashRejectId = null;
  await loadAll();
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
  const el = $("#category"), meta = $("#categoryMeta");
  if (!c || c.available === false) {
    if (meta) meta.textContent = "Not available";
    el.innerHTML = `<div class="category-empty"><div class="donut" aria-hidden="true"></div>
      <div><b>No data yet</b><p>${esc(c && c.note || "Sales cannot be grouped by category until a category is captured on each product.")}</p>
      <code>${esc(c && c.gap || "GAP-D01")}</code></div></div>`;
    return;
  }
  const rows = c.rows || [];
  if (meta) {
    const d = state.dash || {};
    meta.textContent = d.from && d.to
      ? `${fmtDate(d.from)} to ${fmtDate(d.to)} · taxable value`
      : "Issued invoices · taxable value";
  }
  if (!rows.length) {
    el.innerHTML = `<div class="category-empty"><div><b>No data yet</b><p>${esc(c.note || "No issued invoice falls in this period.")}</p></div></div>`;
    return;
  }
  const max = Math.max(...rows.map(r => Number(r.revenue)), 0) || 1;
  el.innerHTML = `<ul class="rows">${rows.map(r => {
    const pct = Math.max(0, Number(r.revenue) / max * 100);
    return `<li><div><b>${esc(r.category)}</b><small>${plural(r.invoices, "invoice")} · ${esc(qty(r.qty))} units</small>
      <div class="wh-bar" aria-hidden="true"><i style="width:${pct.toFixed(1)}%"></i></div></div>
      <div class="r"><span class="num">₹ ${money(r.revenue)}</span></div></li>`;
  }).join("")}</ul>
  <p class="gap-note">${esc(c.note)}</p>`;
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
    const notes = [];
    notes.push(d.average_days != null
      ? `Raised to dispatch: ${d.average_days} days on average across ${plural(d.measured, "dispatched order")}.`
      : "Order-to-dispatch time is not available yet.");
    if (d.approval_average_days != null) {
      notes.push(`Approval: ${d.approval_average_days} days across ${plural(d.approval_measured, "order")}`
        + (d.after_approval_average_days != null
          ? `; approved to dispatch: ${d.after_approval_average_days} days across ${plural(d.after_approval_measured, "order")}.` : "."));
    }
    const dl = d.delivery || {};
    if (dl.measured) {
      notes.push(`Promised date met on ${dl.on_time} of ${plural(dl.measured, "dispatched order")}`
        + (dl.late ? `; ${dl.late} late by ${dl.average_days_late} days on average.` : "."));
    }
    if (d.overdue_open) notes.push(`${plural(d.overdue_open, "open order")} already past the promised date.`);
    if (d.note) notes.push(d.note);
    parts.push(col(`Sales orders · ${plural(p.sales.total, "order")}`, p.sales.rows,
      r => `<li><div><b>${esc(r.label)}</b><small>${plural(r.count, "order")}</small></div>
        <div class="r"><span class="num">₹ ${money(r.value)}</span></div></li>`,
      notes.map(n => `<p class="gap-note">${esc(n)}</p>`).join("")));
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
  const res = await api(`/api/dashboard?${dashQuery()}`);
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

function applyDashDates(from, to, preset) {
  const today = dayIso(new Date());
  let problem = "";
  if (!from || !to) problem = "Choose both dates, or pick a preset.";
  else if (from > to) problem = "The From date cannot be after the To date.";
  else if (to > today) problem = "The To date cannot be in the future.";
  state.dashDateError = problem;
  if (problem) { renderDash(); return; }
  state.dashFrom = from;
  state.dashTo = to;
  state.dashPreset = preset || "";
  try {
    localStorage.setItem("hb.dashFrom", from);
    localStorage.setItem("hb.dashTo", to);
    localStorage.setItem("hb.dashPreset", state.dashPreset);
  } catch (e) { /* storage blocked */ }
  renderDash();
  loadDashboard();
}

function setDashPreset(key) {
  const w = dashWindow(key);
  closeDashRange();
  applyDashDates(w.from, w.to, key);
}

/* The period popover: a preset strip and two month grids for a custom range.
   Selection is start then end; picking an earlier day than the start swaps the
   two, so a range is always sent to the server as from <= to. */
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November", "December"];
const DOW = ["M", "T", "W", "T", "F", "S", "S"];
const dashCal = {open: false, first: "", start: "", end: "", hover: "", picking: false};

const dashDayLabel = iso => new Date(iso + "T00:00:00")
  .toLocaleDateString("en-US", {month: "short", day: "numeric", year: "numeric"});

function renderDashRange() {
  const label = $("#dashRangeLabel");
  if (label) label.textContent = `${dashDayLabel(state.dashFrom)} - ${dashDayLabel(state.dashTo)}`;
}

function shiftDashCalendar(dir) {
  const first = new Date(dashCal.first + "T00:00:00");
  dashCal.first = dayIso(new Date(first.getFullYear(), first.getMonth() + dir, 1));
  drawDashCalendar();
}

function drawDashCalendar() {
  const first = new Date(dashCal.first + "T00:00:00");
  const today = dayIso(new Date());
  $("#dashCalMonths").innerHTML = [0, 1].map(k => {
    const m = new Date(first.getFullYear(), first.getMonth() + k, 1);
    const y = m.getFullYear(), mon = m.getMonth();
    const lead = (m.getDay() + 6) % 7;
    const days = new Date(y, mon + 1, 0).getDate();
    let cells = "";
    for (let i = 0; i < lead; i++) cells += '<span class="drp-blank"></span>';
    for (let day = 1; day <= days; day++) {
      const iso = dayIso(new Date(y, mon, day));
      cells += `<button type="button" class="drp-day" data-day="${iso}" `
        + `aria-label="${dashDayLabel(iso)}"${iso > today ? " disabled" : ""}>${day}</button>`;
    }
    return `<div class="drp-month"><div class="drp-month-name">${MONTH_NAMES[mon]} ${y}</div>`
      + `<div class="drp-week" aria-hidden="true">${DOW.map(w => `<span>${w}</span>`).join("")}</div>`
      + `<div class="drp-days">${cells}</div></div>`;
  }).join("");
  const now = new Date();
  const current = [now.getFullYear(), now.getMonth()];
  $("#dashCalNext").disabled =
    first.getFullYear() > current[0]
    || (first.getFullYear() === current[0] && first.getMonth() >= current[1]);
  paintDashCalendar();
}

function paintDashCalendar() {
  const a = dashCal.start;
  const b = dashCal.picking ? dashCal.hover : dashCal.end;
  const lo = a && b ? (a <= b ? a : b) : "";
  const hi = a && b ? (a <= b ? b : a) : "";
  const today = dayIso(new Date());
  $$("#dashCalMonths .drp-day").forEach(el => {
    const iso = el.dataset.day;
    const edge = iso === dashCal.start || iso === dashCal.end;
    el.classList.toggle("today", iso === today);
    el.classList.toggle("edge", edge);
    el.classList.toggle("in-range", !!lo && !!hi && iso > lo && iso < hi);
    el.setAttribute("aria-pressed", String(edge));
  });
  $("#dashCalHint").textContent = dashCal.picking ? "Choose the end date" : "Choose the start date";
  $("#dashRangePreview").textContent = !dashCal.start ? "No range selected"
    : dashCal.picking ? `${dashDayLabel(dashCal.start)} - …`
      : `${dashDayLabel(dashCal.start)} - ${dashDayLabel(dashCal.end)}`;
}

function openDashRange() {
  if (dashCal.open) return;
  dashCal.open = true;
  dashCal.first = state.dashFrom.slice(0, 8) + "01";
  dashCal.start = state.dashFrom;
  dashCal.end = state.dashTo;
  dashCal.hover = "";
  dashCal.picking = false;
  $("#dashRangePop").classList.remove("hide");
  $("#dashRangeBtn").setAttribute("aria-expanded", "true");
  drawDashCalendar();
}

function closeDashRange() {
  if (!dashCal.open) return;
  dashCal.open = false;
  $("#dashRangePop").classList.add("hide");
  $("#dashRangeBtn").setAttribute("aria-expanded", "false");
}

function pickDashDay(iso) {
  if (!iso) return;
  if (!dashCal.picking) {
    dashCal.start = iso;
    dashCal.end = "";
    dashCal.hover = "";
    dashCal.picking = true;
    paintDashCalendar();
    return;
  }
  let from = dashCal.start, to = iso;
  if (to < from) { const swap = from; from = to; to = swap; }
  dashCal.picking = false;
  dashCal.start = from;
  dashCal.end = to;
  paintDashCalendar();
  closeDashRange();
  applyDashDates(from, to, "");
}

function bindDashRange() {
  if (!$("#dashRangeWrap")) return;
  $("#dashRangeBtn").addEventListener("click", () => {
    if (dashCal.open) closeDashRange(); else openDashRange();
  });
  $("#dashRangeCancel").addEventListener("click", closeDashRange);
  $("#dashCalPrev").addEventListener("click", () => shiftDashCalendar(-1));
  $("#dashCalNext").addEventListener("click", () => {
    if (!$("#dashCalNext").disabled) shiftDashCalendar(1);
  });
  $("#dashCalMonths").addEventListener("click", e => {
    const day = e.target.closest(".drp-day");
    if (day && !day.disabled) pickDashDay(day.dataset.day);
  });
  $("#dashCalMonths").addEventListener("mouseover", e => {
    if (!dashCal.open || !dashCal.picking) return;
    const day = e.target.closest(".drp-day");
    if (!day || day.disabled || day.dataset.day === dashCal.hover) return;
    dashCal.hover = day.dataset.day;
    paintDashCalendar();
  });
  $("#dashCalMonths").addEventListener("mouseleave", () => {
    if (!dashCal.picking || !dashCal.hover) return;
    dashCal.hover = "";
    paintDashCalendar();
  });
  document.addEventListener("click", e => {
    if (dashCal.open && !e.target.closest("#dashRangeWrap")) closeDashRange();
  });
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape" || !dashCal.open) return;
    closeDashRange();
    $("#dashRangeBtn").focus();
  });
}

/* ---------- MoM & YoY comparison ---------- */
const CMP_MODES = {full_month: "Full month", mtd: "Month to date"};
const CMP_STATE = {current: "Current month (incomplete)", past: "Complete month",
                   future: "Not started"};
const cmpAmount = (unit, value) => unit === "amount" ? `₹ ${money(value)}` : qty(value);

function cmpDelta(value) {
  if (value === null || value === undefined) {
    return `<span class="cmp-delta flat">no prior figure</span>`;
  }
  const n = Number(value);
  if (!isFinite(n)) return `<span class="cmp-delta flat">no prior figure</span>`;
  if (n === 0) return `<span class="cmp-delta flat">no change</span>`;
  const dir = n > 0 ? "up" : "down";
  return `<span class="cmp-delta ${dir}">${n > 0 ? "▲" : "▼"} ${Math.abs(n).toFixed(1)}%</span>`;
}

function cmpCard(c, future) {
  if (!c.available) {
    return `<div class="kpi cmp-card-gap">
      <span class="kpi-label">${esc(c.label)}<span class="chip off">Gap ${esc(c.gap)}</span></span>
      <span class="kpi-value">No data yet</span>
      <span class="kpi-note">${esc(c.note)}</span>
    </div>`;
  }
  const tag = c.href ? "a" : "div";
  const href = c.href ? ` href="${esc(c.href)}"` : "";
  return `<${tag} class="kpi"${href}>
    <span class="kpi-label">${esc(c.label)}</span>
    <span class="kpi-value">${future ? "No data yet" : esc(cmpAmount(c.unit, c.current))}</span>
    <span class="kpi-note">${esc(c.note)}</span>
    <div class="cmp-split">
      <span>Previous month<b>${esc(cmpAmount(c.unit, c.previous))}</b>${cmpDelta(c.previous_change)}</span>
      <span>Same month last year<b>${esc(cmpAmount(c.unit, c.last_year))}</b>${cmpDelta(c.last_year_change)}</span>
    </div>
  </${tag}>`;
}

function cmpRange(label, window, on) {
  return `<div class="cmp-range${on ? " on" : ""}">
    <small>${esc(label)}</small>
    <b>${esc(window.label)}</b>
    <span>${esc(plural(window.days, "day"))}</span>
  </div>`;
}

function cmpTrend(months, selected, sales, purchases) {
  if (!sales && !purchases) {
    return `<p class="gap-note">Your role may not read sales or purchases.</p>`;
  }
  const head = ["Month"];
  if (sales) head.push("Sales (incl. GST)", "Same month last year", "YoY");
  if (purchases) head.push("Purchases", "Prior year");
  if (sales) head.push("3-month average");
  const body = months.map(r => {
    const cells = [`<td>${esc(r.label)}</td>`];
    if (sales) {
      cells.push(`<td class="n">${r.sales === null ? "–" : esc(money(r.sales))}</td>`);
      cells.push(`<td class="n">${r.prior_sales === null ? "–" : esc(money(r.prior_sales))}</td>`);
      cells.push(`<td class="n">${cmpDelta(r.yoy_change)}</td>`);
    }
    if (purchases) {
      cells.push(`<td class="n">${r.purchases === null ? "–" : esc(money(r.purchases))}</td>`);
      cells.push(`<td class="n">${r.prior_purchases === null ? "–" : esc(money(r.prior_purchases))}</td>`);
    }
    if (sales) {
      cells.push(`<td class="n">${r.moving_average === null ? "–" : esc(money(r.moving_average))}</td>`);
    }
    return `<tr${r.month === selected ? ` class="on"` : ""}>${cells.join("")}</tr>`;
  }).join("");
  return `<thead><tr>${head.map((h, i) => `<th${i ? ` class="n"` : ""}>${esc(h)}</th>`).join("")}</tr></thead>`
    + `<tbody>${body}</tbody>`;
}

function cmpMoves(trend) {
  const blocks = [];
  const add = (label, g) => {
    if (!g) return;
    blocks.push(`<div class="cmp-move">
      <div><span>${esc(label)} in the window</span><b>₹ ${esc(money(g.current))}</b></div>
      <div><span>Previous month</span><b>₹ ${esc(money(g.previous))}</b>${cmpDelta(g.mom)}</div>
      <div><span>Same month last year</span><b>₹ ${esc(money(g.last_year))}</b>${cmpDelta(g.yoy)}</div>
    </div>`);
  };
  add("Sales", trend.sales_visible ? trend.growth.sales : null);
  add("Purchases", trend.purchases_visible ? trend.growth.purchases : null);
  return blocks.join("") || `<p class="gap-note">No movement figure is available to your role.</p>`;
}

function cmpExtremes(trend) {
  if (!trend.sales_visible) {
    return `<li><div><span class="gap-note">The best and worst month need the sales figure.</span></div></li>`;
  }
  if (!trend.best || !trend.worst) {
    return `<li><div><span class="gap-note">No issued invoices in the twelve months shown, so there is no best or worst month yet.</span></div></li>`;
  }
  return [[`Best month`, trend.best], [`Weakest month`, trend.worst]].map(([label, row]) =>
    `<li><div><b>${esc(label)}</b><small>${esc(row.label)}</small></div>`
    + `<span class="num">₹ ${esc(money(row.sales))}</span></li>`).join("");
}

function cmpBreakdown(table, emptyText) {
  const rows = table.rows || [];
  if (!rows.length) return `<tbody><tr><td colspan="5"><span class="gap-note">${esc(emptyText)}</span></td></tr></tbody>`;
  return `<thead><tr><th>Name</th><th class="n">This window</th><th class="n">Previous</th>`
    + `<th class="n">Change</th><th class="n">Share</th></tr></thead><tbody>`
    + rows.map(r => `<tr><td>${esc(r.label)}</td><td class="n">${esc(money(r.current))}</td>`
      + `<td class="n">${esc(money(r.previous))}</td><td class="n">${cmpDelta(r.change)}</td>`
      + `<td class="n">${r.share === null ? "–" : esc(r.share.toFixed(1)) + "%"}</td></tr>`).join("")
    + `</tbody>`;
}

function renderCompare() {
  const s = state.compare, d = s.data;
  const monthEl = $("#cmpMonth");
  if (monthEl && document.activeElement !== monthEl) {
    monthEl.value = s.month || (d ? d.month : "");
  }
  $$("[data-cmp-mode]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.cmpMode === s.mode)));
  $("#cmpSkeleton").classList.toggle("hide", !(s.loading && !d));
  $("#cmpError").classList.toggle("hide", !s.error);
  $("#cmpContent").classList.toggle("hide", !d);
  $("#cmpContent").setAttribute("aria-busy", s.loading ? "true" : "false");
  if (s.error) {
    $("#cmpErrText").textContent = d
      ? ` The last figures loaded are shown. ${s.error}`
      : ` ${s.error}`;
  }
  if (!d) {
    $("#cmpNote").textContent = s.loading ? "Loading figures from the server…" : "";
    return;
  }

  $("#cmpNote").innerHTML = `${esc(CMP_MODES[d.mode])} · ${esc(CMP_STATE[d.month_state])}`
    + ` · ${esc(d.month_label)}${s.loading ? " · refreshing…" : ""}`;

  const ranges = d.ranges;
  $("#cmpRanges").innerHTML =
    cmpRange(`Selected window · ${CMP_MODES[d.mode]}`, ranges.current, true)
    + cmpRange("Previous month", ranges.previous, false)
    + cmpRange("Same month last year", ranges.last_year, false);

  $("#cmpCards").innerHTML = d.cards.map(c => cmpCard(c, d.month_state === "future")).join("");

  const trend = d.trend;
  $("#cmpTrend").innerHTML = cmpTrend(trend.months, d.month,
                                      trend.sales_visible, trend.purchases_visible);
  $("#cmpTrendNote").textContent = "The selected month is highlighted. Purchases are valued at order cost.";
  $("#cmpGrowth").innerHTML = cmpMoves(trend);
  $("#cmpExtremes").innerHTML = cmpExtremes(trend);
  const seasons = (trend.seasonality || []).filter(x => x.index !== null);
  $("#cmpSeason").innerHTML = seasons.length
    ? seasons.map(x => `<span>${esc(x.label)}<b>${Number(x.index).toFixed(2)}×</b></span>`).join("")
    : `<p class="gap-note">No prior-year sales figure to divide by for these months.</p>`;

  const b = d.breakdowns;
  $("#cmpBreakdowns").classList.toggle("hide", !b);
  if (b) {
    $("#cmpProdNote").textContent = "Taxable value, before GST";
    $("#cmpDistNote").textContent = "Taxable value, before GST";
    $("#cmpProducts").innerHTML = cmpBreakdown(b.sales_by_product,
      "No issued invoices in the selected window.");
    $("#cmpDists").innerHTML = cmpBreakdown(b.sales_by_distributor,
      "No issued invoices in the selected window.");
  }

  const p = d.projection;
  const estimate = p.is_estimate && p.state === "current";
  $("#cmpProjLabel").innerHTML = estimate
    ? `<span class="cmp-est">Estimate</span>${esc(p.label)}` : esc(p.label);
  const stat = (value, label) => `<div><b>${estimate ? "≈ " : ""}₹ ${esc(money(value))}</b>`
    + `<span>${esc(label)}</span></div>`;
  const stats = [];
  const suffix = p.complete ? ", recorded" : estimate ? ", run rate" : "";
  if (p.sales !== null) stats.push(stat(p.sales, `Sales${suffix}`));
  if (p.purchases !== null) stats.push(stat(p.purchases, `Purchases${suffix}`));
  stats.push(`<div><b>${esc(qty(p.elapsed_days))} of ${esc(qty(p.days_in_month))}</b><span>days elapsed in the month</span></div>`);
  $("#cmpProjection").innerHTML = stats.join("");
  $("#cmpProjNote").textContent = p.note;

  $("#cmpFooter").textContent =
    `Counted ${fmtStamp(d.generated_at)} in Asia/Kolkata · `
    + `rolling three-month average over the twelve months ending ${d.month_label}.`;
  $("#cmpNotes").innerHTML = (d.notes || []).map(n => `<li>${esc(n)}</li>`).join("");
}

async function loadCompare() {
  const s = state.compare;
  const seq = ++s.seq;
  s.loading = true;
  s.error = null;
  renderCompare();
  const params = new URLSearchParams({mode: s.mode});
  if (s.month) params.set("month", s.month);
  const res = await api(`/api/dashboard/compare?${params.toString()}`);
  if (seq !== s.seq || !state.user) return;
  s.loading = false;
  if (res.ok && res.body && !Array.isArray(res.body)) {
    s.data = res.body;
    s.error = null;
  } else {
    s.error = detail(res.body);
  }
  renderCompare();
}

function setCompareMode(mode) {
  if (!CMP_MODES[mode]) return;
  state.compare.mode = mode;
  try { localStorage.setItem("hb.cmpMode", mode); } catch (e) { /* storage blocked */ }
  loadCompare();
}

function setCompareMonth(value) {
  state.compare.month = /^\d{4}-\d{2}$/.test(value || "") ? value : "";
  try {
    if (state.compare.month) localStorage.setItem("hb.cmpMonth", state.compare.month);
    else localStorage.removeItem("hb.cmpMonth");
  } catch (e) { /* storage blocked */ }
  loadCompare();
}

function downloadCsv(name, rows) {
  // Same rule as the server exports: text a spreadsheet would run as a formula
  // is prefixed with an apostrophe, but numbers (including negatives) are not.
  const formula = /^[=+\-@\t\r]/;
  const numberLike = /^[+-]?[\d\s().,-]+$/;
  const text = v => {
    const s = String(v ?? "");
    return formula.test(s) && !numberLike.test(s) ? "'" + s : s;
  };
  const cell = v => {
    const s = text(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = rows.map(r => r.map(cell).join(",")).join("\r\n");
  const blob = new Blob(["\ufeff" + csv], {type: "text/csv;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function exportCompareCsv() {
  const d = state.compare.data;
  if (!d) return;
  const t = d.trend;
  const head = ["Month"];
  if (t.sales_visible) head.push("Sales incl. GST", "Same month last year", "YoY %");
  if (t.purchases_visible) head.push("Purchases", "Prior year purchases");
  if (t.sales_visible) head.push("3-month average");
  const rows = [
    ["HERBANOVA MoM and YoY comparison"],
    ["Mode", CMP_MODES[d.mode]],
    ["Selected window", d.ranges.current.from, d.ranges.current.to],
    ["Previous month", d.ranges.previous.from, d.ranges.previous.to],
    ["Same month last year", d.ranges.last_year.from, d.ranges.last_year.to],
    ["Generated", d.generated_at],
    [],
    head,
  ];
  t.months.forEach(r => {
    const row = [r.month];
    if (t.sales_visible) row.push(r.sales, r.prior_sales, r.yoy_change);
    if (t.purchases_visible) row.push(r.purchases, r.prior_purchases);
    if (t.sales_visible) row.push(r.moving_average);
    rows.push(row);
  });
  downloadCsv(`herbanova-mom-yoy-${d.month}.csv`, rows);
}

/* ---------- geography ---------- */
// A fixed local tile layout: roughly north to south, west to east. It is a
// schematic, not a geographic outline, and is labelled as such on screen.
const GEO_LAYOUT = {
  "38": [0, 2],
  "01": [1, 0],
  "02": [2, 0], "04": [2, 1], "05": [2, 2],
  "03": [3, 0], "06": [3, 1], "07": [3, 2], "09": [3, 3], "11": [3, 6], "12": [3, 7],
  "08": [4, 0], "23": [4, 2], "10": [4, 3], "20": [4, 4], "18": [4, 5], "13": [4, 6],
  "24": [5, 0], "27": [5, 1], "22": [5, 2], "21": [5, 3], "19": [5, 4],
  "14": [5, 5], "17": [5, 6], "15": [5, 7],
  "26": [6, 0], "30": [6, 1], "36": [6, 2], "37": [6, 3], "16": [6, 4], "35": [6, 7],
  "31": [7, 0], "29": [7, 1],
  "32": [8, 0], "33": [8, 1], "34": [8, 2],
  "97": [9, 4],
};
const GEO_SHORT = {
  "01": "JK", "02": "HP", "03": "PB", "04": "CH", "05": "UK", "06": "HR", "07": "DL",
  "08": "RJ", "09": "UP", "10": "BR", "11": "SK", "12": "AR", "13": "NL", "14": "MN",
  "15": "MZ", "16": "TR", "17": "ML", "18": "AS", "19": "WB", "20": "JH", "21": "OD",
  "22": "CG", "23": "MP", "24": "GJ", "26": "DN", "27": "MH", "29": "KA", "30": "GA",
  "31": "LD", "32": "KL", "33": "TN", "34": "PY", "35": "AN", "36": "TS", "37": "AP",
  "38": "LA", "97": "OT",
};
const GEO_SORTABLE = new Set(["name", "sales", "share", "invoice_count", "customers",
                              "taxable", "return_value"]);

function applyGeoDates(from, to) {
  const today = dayIso(new Date());
  let problem = "";
  if (!from || !to) problem = "Choose both dates.";
  else if (from > to) problem = "The From date cannot be after the To date.";
  else if (to > today) problem = "The To date cannot be in the future.";
  state.geo.dateError = problem;
  if (problem) { renderGeo(); return; }
  state.geo.from = from;
  state.geo.to = to;
  try {
    localStorage.setItem("hb.geoFrom", from);
    localStorage.setItem("hb.geoTo", to);
  } catch (e) { /* storage blocked */ }
  renderGeo();
  loadGeo();
}

function setGeoSort(key) {
  if (!GEO_SORTABLE.has(key)) return;
  const cur = state.geo.sort;
  if (cur.key === key) cur.dir = cur.dir === "asc" ? "desc" : "asc";
  else state.geo.sort = {key, dir: key === "name" ? "asc" : "desc"};
  renderGeo();
}

function selectGeo(key) {
  state.geo.selected = state.geo.selected === key ? null : key;
  renderGeo();
}

function geoRows() {
  const d = state.geo.data;
  if (!d) return [];
  const {key, dir} = state.geo.sort;
  const value = r => {
    if (key === "name") return r.name.toLowerCase();
    if (key === "share") return r.share === null ? -1 : Number(r.share);
    return Number(r[key] || 0);
  };
  return [...d.states].sort((a, b) => {
    const va = value(a), vb = value(b);
    const cmp = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return dir === "asc" ? cmp : -cmp;
  });
}

function renderGeo() {
  const s = state.geo, d = s.data;
  const today = dayIso(new Date());
  const fromEl = $("#geoFrom"), toEl = $("#geoTo");
  if (fromEl) { fromEl.max = today; if (document.activeElement !== fromEl) fromEl.value = s.from; }
  if (toEl) { toEl.max = today; if (document.activeElement !== toEl) toEl.value = s.to; }
  const dateErr = $("#geoDateErr");
  if (dateErr) {
    dateErr.textContent = s.dateError;
    dateErr.classList.toggle("hide", !s.dateError);
  }
  $("#geoSkeleton").classList.toggle("hide", !(s.loading && !d));
  $("#geoError").classList.toggle("hide", !s.error);
  $("#geoContent").classList.toggle("hide", !d);
  $("#geoContent").setAttribute("aria-busy", s.loading ? "true" : "false");
  if (s.error) {
    $("#geoErrText").textContent = d
      ? ` The last figures loaded are shown. ${s.error}`
      : ` ${s.error}`;
  }
  if (!d) {
    $("#geoNote").textContent = s.loading ? "Loading figures from the server…" : "";
    return;
  }

  $("#geoNote").innerHTML = `${esc(d.range_label)} · ${esc(qty(d.days))} ${d.days === 1 ? "day" : "days"}`
    + (s.loading ? " · refreshing…" : "");

  const level = l => `<div class="geo-level ${l.available ? "" : "off"}">`
    + `<b>${esc(l.level)}</b><span>${l.available
        ? esc(l.note) : `No data yet · ${esc(l.gap)}`}</span></div>`;
  $("#geoLevels").innerHTML = d.levels.map(level).join("");

  const t = d.totals;
  const kpi = (label, value, note) => `<div class="kpi">`
    + `<span class="kpi-label">${esc(label)}</span>`
    + `<span class="kpi-value">${esc(value)}</span>`
    + `<span class="kpi-trend off"><em>${esc(note)}</em></span></div>`;
  const cards = [
    kpi("Sales", `₹ ${money(t.sales)}`, "Issued invoices, including GST."),
    kpi("Invoices", qty(t.invoice_count), "Issued in the selected window."),
    kpi("States with sales", qty(t.states), "States or territories with at least one issued invoice."),
  ];
  if (d.gst.available) {
    cards.push(kpi("Taxable value", `₹ ${money(t.taxable)}`,
                   "Before GST; the tax split is in the table below."));
  } else if (d.returns.available) {
    cards.push(kpi("Returns", `₹ ${money(t.returns)}`,
                   `${plural(t.return_count, "issued credit note")}.`));
  } else {
    cards.push(kpi("Location not recorded", qty(d.basis.unrecorded),
                   "Invoices with no state on the snapshot or the distributor."));
  }
  $("#geoKpis").innerHTML = cards.join("");

  const max = d.map.reduce((m, x) => Math.max(m, Number(x.sales)), 0);
  $("#geoMap").innerHTML = d.map.map(m => {
    const at = GEO_LAYOUT[m.code] || [9, 7];
    const value = Number(m.sales);
    const alpha = m.recorded && max > 0 ? 0.12 + 0.66 * Math.sqrt(value / max) : 0;
    const style = `grid-row:${at[0] + 1};grid-column:${at[1] + 1};`
      + (alpha ? `background:rgba(31,107,68,${alpha.toFixed(2)});` : "")
      + (alpha > 0.55 ? "color:#fff;" : "");
    const label = m.recorded ? `₹ ${money(m.sales)}` : "no issued invoice";
    return `<button type="button" class="geo-tile ${m.recorded ? "" : "zero"}`
      + `${s.selected === m.code ? " on" : ""}" style="${style}"`
      + ` data-geo-code="${esc(m.code)}" title="${esc(m.name)} · ${esc(label)}"`
      + ` aria-label="${esc(m.name)}: ${esc(label)}">`
      + `<b>${esc(GEO_SHORT[m.code] || m.code)}</b>`
      + `${m.recorded ? `<span>₹ ${esc(money(m.sales))}</span>` : ""}</button>`;
  }).join("");
  $("#geoMapNote").textContent = "Tiles are a fixed local layout, not a geographic outline. "
    + "Select a tile to highlight its row in the table."
    + (d.unrecorded ? ` ${plural(d.unrecorded.invoice_count, "invoice")} have no recorded state and are not on the map.` : "");

  const rank = rows => rows.length
    ? rows.map((r, i) => `<li><button type="button" data-geo-code="${esc(r.key)}">`
        + `<b>${i + 1}. ${esc(r.name)}</b>`
        + `<em>₹ ${esc(money(r.sales))}</em>`
        + `<span>${plural(r.invoice_count, "invoice")} · ${r.share === null ? "–" : esc(r.share.toFixed(2)) + "%"} of sales</span>`
        + `</button></li>`).join("")
    : `<li class="geo-sub">No state has a recorded sale in this window.</li>`;
  $("#geoTop").innerHTML = rank(d.top);
  $("#geoBottom").innerHTML = rank(d.bottom);

  const rows = geoRows();
  const cols = [
    {key: "name", label: "State"},
    {key: "sales", label: "Sales (incl. GST)", num: true},
    {key: "share", label: "Share", num: true},
    {key: "invoice_count", label: "Invoices", num: true},
    {key: "customers", label: "Customers", num: true},
  ];
  if (d.gst.available) cols.push({key: "taxable", label: "Taxable", num: true});
  if (d.returns.available) cols.push({key: "return_value", label: "Returns", num: true});
  const head = cols.map(c => {
    const on = s.sort.key === c.key;
    const aria = on ? (s.sort.dir === "asc" ? "ascending" : "descending") : "none";
    return `<th class="${c.num ? "n" : ""}" aria-sort="${aria}">`
      + `<button type="button" class="geo-sort ${on ? "on" : ""}"`
      + ` data-geo-sort="${c.key}">${esc(c.label)}`
      + `${on ? (s.sort.dir === "asc" ? " ↑" : " ↓") : ""}</button></th>`;
  }).join("");
  const body = rows.map(r => {
    const cells = cols.map(c => {
      if (c.key === "name") {
        return `<td><b>${esc(r.name)}</b>${r.recorded ? ""
          : ` <span class="muted">· no state recorded</span>`}</td>`;
      }
      if (c.key === "share") {
        return `<td class="n">${r.share === null ? "–" : esc(r.share.toFixed(2)) + "%"}</td>`;
      }
      if (["sales", "taxable", "return_value"].includes(c.key)) {
        return `<td class="n">₹ ${esc(money(r[c.key]))}</td>`;
      }
      return `<td class="n">${esc(qty(r[c.key]))}</td>`;
    }).join("");
    return `<tr class="${r.recorded ? "" : "geo-unrecorded"}`
      + `${s.selected === r.key ? " on" : ""}" data-geo-row="${esc(r.key)}">${cells}</tr>`;
  }).join("");
  $("#geoTable").innerHTML = `<thead><tr>${head}</tr></thead><tbody>`
    + (body || `<tr><td colspan="${cols.length}" class="muted">No issued invoices in this window.</td></tr>`)
    + `</tbody>`;
  $("#geoTableNote").textContent = `${plural(t.invoice_count, "invoice")} across `
    + `${plural(t.states, "state")}${d.unrecorded ? " plus a location-not-recorded row" : ""}.`;

  if (!d.returns.available) {
    $("#geoReturns").innerHTML = `<div class="geo-gap"><b>No data yet · ${esc(d.returns.gap)}</b><br>`
      + `${esc(d.returns.note)}</div>`;
  } else if (!d.returns.rows.length) {
    $("#geoReturns").innerHTML = `<p class="geo-sub">No issued credit notes in this window.</p>`;
  } else {
    const rrows = d.returns.rows.map(r => {
      const reasons = r.reasons.length ? r.reasons.map(esc).join("; ") : "No reason text recorded";
      const more = r.reasons_total > r.reasons.length
        ? ` <em>Showing ${r.reasons.length} of ${r.reasons_total} reasons.</em>` : "";
      return `<tr><td><b>${esc(r.name)}</b></td>`
        + `<td class="n">₹ ${esc(money(r.value))}</td>`
        + `<td class="n">${esc(qty(r.count))}</td>`
        + `<td><span class="geo-reasons" title="${esc(r.reasons.join("; "))}">${reasons}</span>${more}</td></tr>`;
    }).join("");
    $("#geoReturns").innerHTML = `<div class="tw"><table class="cmp-table"><thead><tr>`
      + `<th>State</th><th class="n">Returns</th><th class="n">Notes</th><th>Reason as recorded</th>`
      + `</tr></thead><tbody>${rrows}</tbody></table></div>`
      + `<p class="geo-sub">${esc(d.returns.note)}</p>`;
  }

  if (!d.gst.available) {
    $("#geoGst").innerHTML = `<div class="geo-gap"><b>No data yet · ${esc(d.gst.gap)}</b><br>`
      + `${esc(d.gst.note)}</div>`;
  } else if (!d.gst.rows.length) {
    $("#geoGst").innerHTML = `<p class="geo-sub">No issued invoices in this window.</p>`;
  } else {
    const grows = d.gst.rows.map(r => `<tr><td><b>${esc(r.name)}</b></td>`
      + `<td class="n">₹ ${esc(money(r.taxable))}</td>`
      + `<td class="n">₹ ${esc(money(r.cgst))}</td>`
      + `<td class="n">₹ ${esc(money(r.sgst))}</td>`
      + `<td class="n">₹ ${esc(money(r.igst))}</td>`
      + `<td class="n">₹ ${esc(money(r.cess))}</td>`
      + `<td class="n">₹ ${esc(money(r.tax))}</td></tr>`).join("");
    $("#geoGst").innerHTML = `<div class="tw"><table class="cmp-table"><thead><tr>`
      + `<th>State</th><th class="n">Taxable</th><th class="n">CGST</th><th class="n">SGST</th>`
      + `<th class="n">IGST</th><th class="n">Cess</th><th class="n">Tax</th>`
      + `</tr></thead><tbody>${grows}</tbody></table></div>`
      + `<p class="geo-sub">${esc(d.gst.note)}</p>`;
  }

  $("#geoFooter").textContent = `Counted ${fmtStamp(d.generated_at)} in Asia/Kolkata`
    + ` · ${d.range_label}.`;
  $("#geoNotes").innerHTML = (d.notes || []).map(n => `<li>${esc(n)}</li>`).join("");
}

async function loadGeo() {
  const s = state.geo;
  const seq = ++s.seq;
  s.loading = true;
  s.error = null;
  renderGeo();
  const params = new URLSearchParams({from_date: s.from, to_date: s.to});
  const res = await api(`/api/dashboard/geo?${params.toString()}`);
  if (seq !== s.seq || !state.user) return;
  s.loading = false;
  if (res.ok && res.body && !Array.isArray(res.body)) {
    s.data = res.body;
    s.error = null;
    if (!s.data.states.some(r => r.key === s.selected)) s.selected = null;
  } else {
    s.error = detail(res.body);
  }
  renderGeo();
}

function exportGeoCsv() {
  const d = state.geo.data;
  if (!d) return;
  const cols = ["State", "State code", "Sales incl. GST", "Share %", "Invoices", "Customers"];
  if (d.gst.available) cols.push("Taxable value", "CGST", "SGST", "IGST", "Cess", "Tax");
  if (d.returns.available) cols.push("Returns", "Credit notes", "Reasons as recorded");
  const rows = [
    ["HERBANOVA sales by state"],
    ["From", d.from], ["To", d.to], ["Generated", d.generated_at], [],
    cols,
  ];
  d.states.forEach(r => {
    const row = [r.name, r.code || "not recorded", r.sales, r.share ?? "",
                 r.invoice_count, r.customers];
    if (d.gst.available) row.push(r.taxable, r.cgst, r.sgst, r.igst, r.cess, r.tax);
    if (d.returns.available) row.push(r.return_value, r.return_count, r.reasons.join("; "));
    rows.push(row);
  });
  if (d.states.length) {
    rows.push(["Total", "", d.totals.sales, "", d.totals.invoice_count, ""]);
  } else {
    rows.push(["No records for this period."]);
  }
  downloadCsv(`herbanova-geography-${d.from}-to-${d.to}.csv`, rows);
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
  $("#paletteQ").focus();
  // Open on the screen list, so the palette is navigation even before a search.
  renderPalette(null, "");
  $("#paletteNote").textContent = "Type at least two characters to search records. Screens are listed above.";
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

/* The palette is navigation as well as record search: the screens the role may
   open come from the same hierarchy the sidebar and breadcrumb use. */
function paletteScreenGroup(term) {
  const q = String(term || "").trim().toLowerCase();
  const seen = {}, items = [];
  WS.flatNav().forEach(n => {
    if (n.view === "dash" || seen[n.view] || !wsViewOk(n.view)) return;
    seen[n.view] = true;
    const hay = [n.label, n.module, n.category, n.group].join(" ").toLowerCase();
    if (q && hay.indexOf(q) < 0) return;
    items.push({id: "", title: n.label,
      subtitle: [n.module, n.category, n.group].filter(Boolean).join(" › "),
      href: "#/" + n.view});
  });
  return items.length ? {key: "screens", label: "Screens", items} : null;
}

function renderPalette(body, term) {
  const groups = body && body.groups ? body.groups.slice() : [];
  const screens = paletteScreenGroup(term);
  if (screens) groups.unshift(screens);
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
    renderPalette(null, term);
    $("#paletteNote").textContent = "Type at least two characters to search records. Screens are listed above.";
    return;
  }
  $("#paletteNote").textContent = "Searching…";
  const res = await api(`/api/dashboard/search?q=${encodeURIComponent(term)}`);
  if (seq !== state.palette.seq || !state.palette.open) return;
  if (!res.ok) {
    renderPalette(null, term);
    $("#paletteNote").textContent = `The record search could not run: ${detail(res.body)}`;
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
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem("hb.theme", next); } catch (e) { /* storage blocked */ }
  applyTheme(next);
}

/* ---------- accounts ---------- */
function renderAccounts() {
  // The statements need accounts:read; the performance section above is
  // accounts:reports, so a role may reach this screen with only that right.
  const stmts = $("#accStatements");
  if (stmts) stmts.classList.toggle("hide", !can("accounts:read"));
  if (!can("accounts:read")) return;
  const out = state.accounts.outstanding;
  const recv = out ? out.receivables.filter(r => Number(r.outstanding) > 0) : [];
  const pay = out ? payablesForView() : [];
  $("#arows").innerHTML = recv.map(r => `<tr><td class="strong">${esc(r.number)}</td><td>${esc(r.date)}</td>
    <td>${esc(r.distributor || "")}</td><td class="n">${money(r.grand_total)}</td>
    <td class="n">${money(r.received)}</td><td class="n strong">${money(r.outstanding)}</td></tr>`).join("");
  empty($("#aempty"), !recv.length, out ? "Nothing is outstanding." : "Accounts could not be loaded.",
    out ? " Every issued invoice has been settled in full." : " Refresh to try again.");
  $("#payrows").innerHTML = pay.map(p => `<tr><td class="strong">${esc(p.number)}</td><td>${esc(p.supplier || "")}</td>
    <td class="n">${money(p.received_value)}</td><td class="n">${money(p.paid)}</td>
    <td>${p.due_on ? esc(fmtDate(p.due_on)) : `<span class="muted">not estimated</span>`}</td>
    <td class="n strong">${money(p.outstanding)}</td></tr>`).join("");
  empty($("#payempty"), !pay.length, "Nothing is payable.", " No supplier is owed for goods already received.");
  $("#recvSub").textContent = out
    ? `${money(out.receivable_total)} outstanding across ${plural(recv.length, "invoice")}.`
    : "What distributors still owe on issued invoices.";
  $("#paySub").textContent = out
    ? (state.acc.payDue === "week"
       ? `${money(pay.reduce((sum, p) => sum + Number(p.outstanding || 0), 0))} estimated to fall due within 7 days. The full payables list is under Payables without the filter.`
       : `${money(out.payable_total)} outstanding across ${plural(pay.length, "order")}. Due dates are estimated from each supplier's current terms.`)
    : "What the business still owes suppliers for goods received.";

  const entries = state.accounts.entries || [];
  $("#enrows").innerHTML = entries.map(e => {
    const settled = (e.allocations || []).map(a => `${a.number || "—"} · ₹ ${money(a.amount)}`).join("<br>");
    const against = settled || esc(e.invoice_number || e.purchase_order_number || "—");
    const advance = Number(e.advance) > 0 ? `<small>Advance ₹ ${money(e.advance)}</small>` : "";
    return `<tr><td class="strong">${esc(e.number)}</td><td>${esc(e.paid_on)}</td>
      <td>${e.kind === "receipt" ? "Receipt" : "Payment"}</td><td>${esc(e.party || "")}</td>
      <td>${against}${advance}</td>
      <td class="n">${money(e.amount)}</td><td>${esc(e.mode)}</td></tr>`;
  }).join("");
  empty($("#enempty"), !entries.length, "No money has been recorded yet.",
    can("accounts:write") ? " Select “Record receipt” or “Record payment” to add the first one." : "");
  if (state.accounts.gst) renderGstRegister();
  if (state.accounts.tb) renderTrialBalance();
  renderAgeing();
  renderRbd();
  if (state.accounts.years) renderPeriods();
}

function renderAgeing() {
  const age = state.accounts.ageing;
  const rows = age ? age.buckets.flatMap(b =>
    b.rows.map(r => ({...r, bucket: b.label}))) : [];
  $("#agerows").innerHTML = rows.map(r => `<tr><td class="strong">${esc(r.number)}</td>
    <td>${esc(r.date)}</td><td>${esc(r.distributor || "")}</td><td class="n">${r.days}</td>
    <td>${esc(r.bucket)}</td>
    <td>${r.due_date ? esc(r.due_date) : `<span class="muted">no due date</span>`}</td>
    <td class="n">${r.days_overdue > 0 ? `<span class="bad">${r.days_overdue}</span>` : "–"}</td>
    <td class="n strong">${money(r.outstanding)}</td></tr>`).join("");
  empty($("#ageempty"), !rows.length, age ? "Nothing is outstanding." : "Ageing could not be loaded.",
    age ? " Every issued invoice has been settled." : " Use “Rebuild ageing” to try again.");
  if (age) {
    const zero = {total: 0, count: 0};
    const due = {overdue: zero, due_this_week: zero, not_yet_due: zero,
                 no_due_date: zero, ...(age.due || {})};
    $("#ageTot").textContent = `${money(age.total)} outstanding across ${plural(age.count, "invoice")} · `
      + age.buckets.map(b => `${b.label} ${money(b.total)}`).join(" · ")
      + ` · as at ${age.as_of}`;
    $("#ageDue").textContent = `Overdue ${money(due.overdue.total)} (${plural(due.overdue.count, "invoice")}) · `
      + `due within 7 days ${money(due.due_this_week.total)} (${plural(due.due_this_week.count, "invoice")}) · `
      + `${money(due.not_yet_due.total)} later · ${money(due.no_due_date.total)} with no due date`;
  }
}

async function loadAgeing() {
  const asOf = $("#ageAsOf").value;
  const res = await api(`/api/accounts/ageing${asOf ? "?as_of=" + encodeURIComponent(asOf) : ""}`);
  if (!res.ok) return toast(res, "Ageing could not be rebuilt");
  state.accounts.ageing = res.body; renderAgeing();
}

/* ---------- financial years and month locks ---------- */
const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"];

function isAdminUser() {
  return !!state.user && String(state.user.role || "").trim().toLowerCase() === "admin";
}

function renderPeriods() {
  const fy = state.accounts.years;
  const years = fy ? fy.years : [];
  $("#fyrows").innerHTML = years.map(y => {
    const stateText = y.active ? `<span class="bad">Closed</span>`
      : (y.reopened_at ? `Open <small>reopened ${esc(String(y.reopened_at).slice(0, 10))}${y.reopen_reason ? ": " + esc(y.reopen_reason) : ""}</small>` : "Open");
    const button = y.active
      ? (isAdminUser() ? `<button class="btn ghost" type="button" data-act="fy-reopen" data-fy="${esc(y.financial_year)}">Reopen</button>`
                       : `<span class="muted">Only the Administrator can reopen</span>`)
      : (can("accounts:write") ? `<button class="btn ghost" type="button" data-act="fy-close" data-fy="${esc(y.financial_year)}">Close year</button>` : "");
    return `<tr><td class="strong">${esc(y.financial_year)}</td><td>${esc(y.first)}</td><td>${esc(y.last)}</td>
      <td>${stateText}</td><td>${esc(y.closed_by || "–")}</td><td>${esc(y.reason || "–")}</td><td>${button}</td></tr>`;
  }).join("");
  empty($("#fyempty"), !years.length, fy ? "No completed financial year yet." : "Financial years could not be loaded.",
    fy ? " A year appears here once its last day has passed." : " Refresh to try again.");
  $("#periodNote").textContent = fy ? `Current year ${fy.current}. Only completed years can be closed.` : "";

  const locks = state.accounts.locks || [];
  const active = locks.filter(l => l.active);
  const lbtn = can("accounts:write");
  $("#lockMonthBtn").classList.toggle("hide", !lbtn);
  $("#lockrows").innerHTML = locks.map(l => {
    const st = l.active
      ? `<span class="bad">Locked</span>`
      : `Open${l.unlock_reason ? " · " + esc(l.unlock_reason) : ""}`;
    const btn = l.active && isAdminUser()
      ? `<button class="btn ghost" type="button" data-act="lock-unlock" data-id="${l.id}">Unlock</button>` : "";
    return `<tr><td class="strong">${MONTHS[l.month - 1]} ${l.year}</td><td>${st}</td>
      <td>${esc(l.reason || "–")}</td><td>${esc(l.locked_by || "–")}</td><td>${btn}</td></tr>`;
  }).join("");
  empty($("#lockempty"), !locks.length, "No accounting month has been locked.",
    " Lock a month while its figures are being reconciled.");
  $("#lockNote").textContent = `${plural(active.length, "month")} locked.`;
}

async function loadPeriods() {
  const [fy, lk] = await Promise.all([api("/api/accounts/financial-years"),
                                      api("/api/accounts/period-locks")]);
  if (fy.ok) state.accounts.years = fy.body; else toast(fy, "Financial years could not be loaded");
  if (lk.ok) state.accounts.locks = lk.body; else toast(lk, "Month locks could not be loaded");
  renderPeriods();
}

function periodReasonDrawer(title, sub, hint, onSave) {
  openDrawer(title, sub, `<form id="periodReasonForm" novalidate>
    <label for="pr-reason">Reason</label><input id="pr-reason" name="reason" placeholder="${esc(hint)}" autocomplete="off">
    <div class="err" role="alert"></div>
    <div class="actions"><button class="btn" type="submit">${esc(title)}</button></div></form>`);
  $("#periodReasonForm").addEventListener("submit", async e => {
    e.preventDefault();
    const form = e.currentTarget;
    const reason = form.querySelector("[name=reason]").value.trim();
    if (reason.length < 5) return drawerErr(form, "Give a reason of at least 5 characters.");
    const res = await onSave(reason);
    if (!res.ok) return drawerErr(form, detail(res.body));
    closeDrawer(); toast(res, "Saved"); await loadPeriods();
  });
}

function drawerErr(form, message) {
  const box = form.querySelector(".err");
  box.textContent = message; box.classList.remove("hide");
}

function closeFinancialYear(label) {
  periodReasonDrawer(`Close ${label}`, "The year's documents become final.", "Why is this year being closed?",
    reason => api(`/api/accounts/financial-years/${encodeURIComponent(label)}/close`,
                  {method: "POST", body: {reason}}));
}

function reopenFinancialYear(label) {
  periodReasonDrawer(`Reopen ${label}`, "Documents dated in the year become changeable again.", "Why is this year being reopened?",
    reason => api(`/api/accounts/financial-years/${encodeURIComponent(label)}/reopen`,
                  {method: "POST", body: {reason}}));
}

function lockAccountingMonth() {
  const value = $("#lockMonth").value;
  if (!/^\d{4}-\d{2}$/.test(value)) return toast({ok: false, status: "—", body: {detail: "Choose a month first"}}, "Choose a month");
  const [year, month] = value.split("-").map(Number);
  periodReasonDrawer(`Lock ${MONTHS[month - 1]} ${year}`, "Posting into this month stops until it is unlocked.",
    "Why is this month being locked?", reason =>
      api("/api/accounts/period-locks", {method: "POST", body: {year, month, reason}}));
}

function unlockAccountingMonth(lockId) {
  const lock = (state.accounts.locks || []).find(l => String(l.id) === String(lockId));
  const label = lock ? `${MONTHS[lock.month - 1]} ${lock.year}` : "this month";
  periodReasonDrawer(`Unlock ${label}`, "Posting into the month is allowed again.", "Why is this month being unlocked?",
    reason => api(`/api/accounts/period-locks/${lockId}/unlock`, {method: "POST", body: {reason}}));
}

/* ---------- stored ledger: heads, openings, balance sheet, vouchers ----------
   The document trial balance above stays the source for what documents say.
   This section is the person's own posting: a chart of heads, opening balances,
   vouchers with a draft and posted state, and a day book. Nothing is guessed; a
   draft may be unbalanced while typed, and posting refuses it until it balances. */
const LEDGER_TYPE_LABEL = {asset: "Asset", liability: "Liability", equity: "Equity",
                           income: "Income", expense: "Expense"};
const VOUCHER_TYPE_LABEL = {journal: "Journal", receipt: "Receipt",
                            payment: "Payment", contra: "Contra"};
const VOUCHER_STATE_LABEL = {draft: "Draft", posted: "Posted", reversed: "Reversed"};

function currentFyLabel(d = new Date()) {
  const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  return `${y}-${String((y + 1) % 100).padStart(2, "0")}`;
}
const lgState = () => state.accounts.ledger;

function renderLedgerHeads() {
  const heads = lgState().heads || [];
  $("#lhrows").innerHTML = heads.map(h => {
    const role = h.role ? `<span class="chip">${esc(h.role.replace(/_/g, " "))}</span>`
                        : `<span class="gap-note">unlinked</span>`;
    const btn = can("accounts:write")
      ? `<button class="btn ghost sm" type="button" data-act="ledger-head-toggle" data-id="${h.id}" data-on="${h.active ? 1 : 0}">${h.active ? "Deactivate" : "Activate"}</button>`
      : "";
    return `<tr><td class="strong">${esc(h.code)}</td><td>${esc(h.name)}</td>
      <td>${esc(LEDGER_TYPE_LABEL[h.type] || h.type)}</td><td>${role}</td>
      <td>${h.active ? `<span class="chip ok">Active</span>` : `<span class="chip off">Inactive</span>`}</td>
      <td>${esc(h.note || "–")}</td><td>${btn}</td></tr>`;
  }).join("");
  empty($("#lhempty"), !heads.length, "No ledger head is on file.",
    " A head is needed before a voucher can post.");
  $("#lhTot").textContent = `${plural(heads.filter(h => h.active).length, "active head")} of ${heads.length}.`;
}

async function loadLedgerHeads() {
  const res = await api("/api/accounts/ledger-accounts?include_inactive=true");
  if (!res.ok) return toast(res, "Ledger heads could not be loaded");
  lgState().heads = Array.isArray(res.body) ? res.body : [];
  renderLedgerHeads();
}

function renderOpenings() {
  const ob = lgState().openings;
  $("#obrows").innerHTML = ob ? ob.rows.map(r => {
    const btn = can("accounts:write")
      ? `<button class="btn ghost sm" type="button" data-act="edit-opening" data-id="${r.account_id}">Set</button>` : "";
    return `<tr${r.active ? "" : ` class="muted"`}><td class="strong">${esc(r.code)}</td>
      <td>${esc(r.name)}</td><td>${esc(LEDGER_TYPE_LABEL[r.type] || r.type)}</td>
      <td class="n">${Number(r.debit) ? money(r.debit) : ""}</td>
      <td class="n">${Number(r.credit) ? money(r.credit) : ""}</td>
      <td>${esc(r.note || "–")}</td><td>${btn}</td></tr>`;
  }).join("") : "";
  empty($("#obempty"), !ob || !ob.rows.length, "No ledger head is on file.",
    " A head is needed before an opening balance can be entered.");
  if (ob) {
    $("#obNote").innerHTML = `Debit ${money(ob.debit_total)} · credit ${money(ob.credit_total)} · `
      + (ob.balanced ? `<span class="chip ok">Balanced</span>`
                     : `<span class="chip bad">Difference ${money(ob.difference)}</span>`);
  } else {
    $("#obNote").textContent = "";
  }
}

async function loadOpenings() {
  const fy = ($("#obFy").value || "").trim() || currentFyLabel();
  $("#obFy").value = fy;
  const res = await api(`/api/accounts/opening-balances?financial_year=${encodeURIComponent(fy)}`);
  if (!res.ok) return toast(res, "Opening balances could not be loaded");
  lgState().openings = res.body;
  lgState().openingFy = fy;
  renderOpenings();
}

function editOpening(accountId) {
  const ob = lgState().openings;
  const row = ob && ob.rows.find(r => String(r.account_id) === String(accountId));
  if (!row) return toast({ok: false, status: "—", body: {detail: "Reload the openings first"}}, "Not found");
  openDrawer(`Opening balance · ${row.code}`, `Financial year ${ob.financial_year}. Setting both sides to zero clears the row.`, `
    <form id="obForm" data-account="${row.account_id}" data-fy="${esc(ob.financial_year)}" novalidate>
      <div class="note">${esc(row.name)} · ${esc(LEDGER_TYPE_LABEL[row.type] || row.type)}</div>
      <div class="row2">
        <div><label for="ob-debit">Debit (₹)</label><input id="ob-debit" name="debit" inputmode="decimal" value="${Number(row.debit) ? Number(row.debit).toFixed(2) : ""}" placeholder="0.00"></div>
        <div><label for="ob-credit">Credit (₹)</label><input id="ob-credit" name="credit" inputmode="decimal" value="${Number(row.credit) ? Number(row.credit).toFixed(2) : ""}" placeholder="0.00"></div>
      </div>
      <label for="ob-note">Note</label><input id="ob-note" name="note" value="${esc(row.note || "")}" placeholder="Optional" autocomplete="off">
      <div class="note">Enter either a debit or a credit. Opening balances are part of the year, so a closed year refuses the change.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save opening</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveOpening(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const debit = Number(f.debit.value || 0), credit = Number(f.credit.value || 0);
  if (debit < 0 || credit < 0) { err.textContent = "Debit and credit cannot be negative."; return; }
  if (debit > 0 && credit > 0) { err.textContent = "Enter either a debit or a credit."; return; }
  btn.disabled = true;
  const res = await api("/api/accounts/opening-balances", {method: "PUT", body: {
    account_id: Number(form.dataset.account), financial_year: form.dataset.fy,
    debit: f.debit.value || "0", credit: f.credit.value || "0",
    note: f.note.value.trim() || null,
  }});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, "Opening balance saved");
  closeDrawer();
  lgState().openings = res.body;
  renderOpenings();
  loadBalanceSheet();
}

function newLedgerHead() {
  openDrawer("New ledger head", "A head is a line the stored ledger can post to. Only a seeded head carries the role that links it to the document trial balance.", `
    <form id="ledgerHeadForm" novalidate>
      <div class="row2">
        <div><label for="lh-code">Code</label><input id="lh-code" name="code" autocomplete="off" maxlength="12" placeholder="5200"></div>
        <div><label for="lh-type">Type</label><select id="lh-type" name="type">${Object.entries(LEDGER_TYPE_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
      </div>
      <label for="lh-name">Name</label><input id="lh-name" name="name" autocomplete="off" maxlength="80" placeholder="Freight inward">
      <label for="lh-note">Note</label><input id="lh-note" name="note" autocomplete="off" maxlength="300" placeholder="Optional">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Create head</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveLedgerHead(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const code = f.code.value.trim(), name = f.name.value.trim();
  if (!code || !name) { err.textContent = "Enter a code and a name."; return; }
  btn.disabled = true;
  const res = await api("/api/accounts/ledger-accounts", {method: "POST", body: {
    code, name, type: f.type.value, note: f.note.value.trim() || null,
  }});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, "Ledger head created");
  closeDrawer();
  await loadLedgerHeads();
  loadOpenings();
}

async function toggleLedgerHead(id, on) {
  const res = await api(`/api/accounts/ledger-accounts/${id}`, {method: "PATCH", body: {active: !on}});
  toast(res, res.ok ? (on ? "Head deactivated" : "Head activated") : "Not changed");
  if (res.ok) await loadLedgerHeads();
}

/* ------------------------------------------------------------ balance sheet */
const BS_SECTIONS = [["asset", "Assets"], ["liability", "Liabilities"],
                     ["equity", "Equity"], ["income", "Income"],
                     ["expense", "Expenses"]];

function renderBalanceSheet() {
  const sheet = lgState().sheet;
  const tb = $("#bsrows");
  if (!sheet) {
    tb.innerHTML = "";
    empty($("#bsempty"), true, "The balance sheet is not built yet.",
      " Choose a date and select “Build balance sheet”.");
    $("#bscash").innerHTML = "";
    $("#bsBal").textContent = "";
    $("#bsOpening").textContent = "";
    $("#bsWarnings").innerHTML = "";
    return;
  }
  let body = "";
  BS_SECTIONS.forEach(([key, label]) => {
    const rows = sheet.sections[key] || [];
    if (!rows.length) return;
    body += `<tr><td colspan="5" class="strong">${esc(label)}</td></tr>`;
    rows.forEach(r => {
      body += `<tr><td>${esc(r.code ? `${r.code} · ${r.name}` : r.name)}${r.unmapped ? ` <span class="gap-note">unlinked</span>` : ""}</td>
        <td class="n">${money(r.opening)}</td><td class="n">${money(r.vouchers)}</td>
        <td class="n">${money(r.documents)}</td><td class="n strong">${money(r.balance)}</td></tr>`;
    });
  });
  const t = sheet.totals;
  body += `<tr><td class="strong">Total assets</td><td></td><td></td><td></td><td class="n strong">${money(t.asset)}</td></tr>`
    + `<tr><td class="strong">Total liabilities</td><td></td><td></td><td></td><td class="n strong">${money(t.liability)}</td></tr>`
    + `<tr><td class="strong">Total equity</td><td></td><td></td><td></td><td class="n strong">${money(t.equity)}</td></tr>`
    + `<tr><td class="strong">Retained earnings <small>income less expenses</small></td><td></td><td></td><td></td><td class="n strong">${money(t.retained_earnings)}</td></tr>`
    + `<tr><td class="strong">Difference</td><td></td><td></td><td></td><td class="n strong">${money(t.difference)}</td></tr>`;
  tb.innerHTML = body;
  empty($("#bsempty"), !body, "Nothing to show.", "");
  $("#bsBal").innerHTML = t.balanced
    ? `<span class="chip ok">Balanced</span>`
    : `<span class="chip bad">Difference ${money(t.difference)}</span>`;
  const opening = sheet.opening || {};
  $("#bsOpening").textContent =
    `As at ${fmtDate(sheet.as_of)} · opening balances ${sheet.opening_fy ? `for ${sheet.opening_fy}` : "not captured"}`
    + ` · movements from ${sheet.window_start || "the first document"}`
    + ` · opening debit ${money(opening.debit_total)} and credit ${money(opening.credit_total)}`
    + (opening.balanced ? " (balanced)." : ` (difference ${money(opening.difference)}).`);

  const cb = sheet.cash_bank || {rows: [], total: 0};
  $("#bscash").innerHTML = cb.rows.map(r =>
      `<tr><td>${esc(r.code ? `${r.code} · ${r.name}` : r.name)}</td><td class="n strong">${money(r.balance)}</td></tr>`).join("")
    + `<tr><td class="strong">Cash and bank total</td><td class="n strong">${money(cb.total)}</td></tr>`;
  $("#bsWarnings").innerHTML = (sheet.warnings || []).map(w => `<li>${esc(w)}</li>`).join("");
}

async function loadBalanceSheet() {
  const asOf = $("#bsAsOf").value;
  const res = await api(`/api/accounts/balance-sheet${asOf ? "?as_of=" + encodeURIComponent(asOf) : ""}`);
  if (!res.ok) return toast(res, "Balance sheet could not be built");
  lgState().sheet = res.body;
  renderBalanceSheet();
}

/* ---------------------------------------------------------------- vouchers */
function renderVouchers() {
  const rows = lgState().vouchers || [];
  $("#vrows").innerHTML = rows.map(v => {
    let actions = "";
    if (can("accounts:write")) {
      if (v.status === "draft") {
        actions = `<button class="btn ghost sm" type="button" data-act="edit-voucher" data-id="${v.id}">Edit</button> `
          + `<button class="btn ghost sm" type="button" data-act="post-voucher" data-id="${v.id}">Post</button> `
          + `<button class="btn ghost sm" type="button" data-act="delete-voucher" data-id="${v.id}">Delete</button>`;
      } else if (v.status === "posted") {
        actions = `<button class="btn ghost sm" type="button" data-act="reverse-voucher" data-id="${v.id}">Reverse</button>`;
      }
    }
    const chip = v.status === "posted" ? `<span class="chip ok">Posted</span>`
      : v.status === "reversed" ? `<span class="chip bad">Reversed</span>`
      : `<span class="chip warn">Draft</span>`;
    const reverse = v.reverse_of ? ` <small>mirror of #${v.reverse_of}</small>` : "";
    return `<tr><td class="strong">${esc(v.number)}${reverse}</td><td>${esc(v.date)}</td>
      <td>${esc(VOUCHER_TYPE_LABEL[v.type] || v.type)}</td>
      <td>${esc(v.narration || "–")}${v.reversal_reason ? `<small>${esc(v.reversal_reason)}</small>` : ""}</td>
      <td class="n">${money(v.debit)}</td><td class="n">${money(v.credit)}</td>
      <td>${chip}</td><td class="rowacts">${actions}</td></tr>`;
  }).join("");
  empty($("#vempty"), !rows.length, "No voucher falls in this window.",
    can("accounts:write") ? " Select “New voucher” to post the first one." : "");
  const drafts = rows.filter(v => v.status === "draft").length;
  $("#vNote").textContent = rows.length
    ? `${plural(rows.length, "voucher")}, ${drafts} draft. A draft is not in the day book.` : "";
}

async function loadVouchers() {
  const qs = new URLSearchParams();
  const from = $("#vFrom").value, to = $("#vTo").value, status = $("#vStatus").value;
  if (from) qs.set("date_from", from);
  if (to) qs.set("date_to", to);
  if (status) qs.set("status", status);
  const res = await api(`/api/accounts/vouchers${qs.toString() ? "?" + qs : ""}`);
  if (!res.ok) return toast(res, "Vouchers could not be loaded");
  lgState().vouchers = Array.isArray(res.body) ? res.body : [];
  lgState().voucherFilters = {from, to, status};
  renderVouchers();
}

let voucherLineSeq = 0;

function voucherLineRow(line = {}, accounts = []) {
  const selected = line.account_id ?? "";
  const options = `<option value="">Choose a head</option>` + accounts.map(h =>
    `<option value="${h.id}"${String(h.id) === String(selected) ? " selected" : ""}>${esc(h.code)} · ${esc(h.name)}</option>`).join("");
  const amount = (v) => Number(v) ? Number(v).toFixed(2) : "";
  return `<tr data-vline="${++voucherLineSeq}">
    <td><select data-vl-account>${options}</select></td>
    <td><input data-vl-debit inputmode="decimal" value="${amount(line.debit)}" placeholder="0.00" aria-label="Debit"></td>
    <td><input data-vl-credit inputmode="decimal" value="${amount(line.credit)}" placeholder="0.00" aria-label="Credit"></td>
    <td><input data-vl-narration value="${esc(line.narration || "")}" autocomplete="off" aria-label="Line narration"></td>
    <td><button class="btn ghost sm" type="button" data-act="voucher-remove-line">Remove</button></td>
  </tr>`;
}

function voucherForm(voucher = null) {
  const accounts = (lgState().heads || []).filter(h => h.active);
  if (accounts.length < 2) {
    return toast({ok: false, status: "—",
      body: {detail: "At least two active ledger heads are needed before a voucher can be written."}}, "No heads to post to");
  }
  const lines = voucher ? (voucher.lines || []) : [{}, {}];
  openDrawer(voucher ? `Edit ${voucher.number}` : "New voucher",
    "Debit equals credit before it can post. A draft is saved as typed and is not in the day book.", `
    <form id="voucherForm" data-id="${voucher ? voucher.id : ""}" novalidate>
      <div class="row2">
        <div><label for="v-date">Date</label><input id="v-date" name="date" type="date" value="${voucher ? esc(voucher.date) : isoDay(0)}"></div>
        <div><label for="v-type">Type</label><select id="v-type" name="type">
          ${Object.entries(VOUCHER_TYPE_LABEL).map(([k, v]) => `<option value="${k}"${voucher && voucher.type === k ? " selected" : ""}>${v}</option>`).join("")}
        </select></div>
      </div>
      <label for="v-narration">Narration</label>
      <input id="v-narration" name="narration" value="${esc(voucher ? voucher.narration || "" : "")}" placeholder="What this voucher records" autocomplete="off" maxlength="300">
      <div class="tw"><table>
        <thead><tr><th>Head</th><th class="n">Debit (₹)</th><th class="n">Credit (₹)</th><th>Line note</th><th></th></tr></thead>
        <tbody id="vLineRows">${lines.map(l => voucherLineRow(l, accounts)).join("")}</tbody>
      </table></div>
      <div class="actions" style="justify-content:flex-start">
        <button class="btn ghost sm" type="button" data-act="voucher-add-line">Add a line</button>
      </div>
      <label><input type="checkbox" id="v-post" name="post"${voucher ? "" : " checked"}> Post it now</label>
      <div class="note">A posted voucher is never edited or deleted. A mistake is corrected with a reversing mirror dated today.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">${voucher ? "Save draft" : "Save voucher"}</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

function addVoucherLine() {
  const tb = $("#vLineRows");
  if (!tb) return;
  const accounts = (lgState().heads || []).filter(h => h.active);
  tb.insertAdjacentHTML("beforeend", voucherLineRow({}, accounts));
}

function removeVoucherLine(btn) {
  const tb = $("#vLineRows");
  if (!tb) return;
  const rows = $$("tr[data-vline]", tb);
  if (rows.length <= 2) return toast({ok: false, status: "—",
    body: {detail: "A voucher needs at least two lines."}}, "Two lines are needed");
  btn.closest("tr").remove();
}

async function saveVoucher(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const f = form.elements;
  const rows = $$("tr[data-vline]", form);
  if (rows.length < 2) { err.textContent = "A voucher needs at least two lines."; return; }
  const lines = [];
  for (let i = 0; i < rows.length; i += 1) {
    const tr = rows[i];
    const account = tr.querySelector("[data-vl-account]").value;
    const debit = Number(tr.querySelector("[data-vl-debit]").value || 0);
    const credit = Number(tr.querySelector("[data-vl-credit]").value || 0);
    const narration = tr.querySelector("[data-vl-narration]").value.trim();
    if (!account) { err.textContent = `Line ${i + 1}: choose a ledger head.`; return; }
    if (debit < 0 || credit < 0) { err.textContent = `Line ${i + 1}: debit and credit cannot be negative.`; return; }
    if ((debit > 0) === (credit > 0)) { err.textContent = `Line ${i + 1}: enter either a debit or a credit.`; return; }
    lines.push({ledger_account_id: Number(account),
                debit: tr.querySelector("[data-vl-debit]").value || "0",
                credit: tr.querySelector("[data-vl-credit]").value || "0",
                narration: narration || null});
  }
  if (!f.date.value) { err.textContent = "Choose a date."; return; }
  const id = form.dataset.id;
  const body = {date: f.date.value, type: f.type.value,
                narration: f.narration.value.trim() || null, lines};
  if (!id) body.post = !!f.post.checked;
  btn.disabled = true;
  const res = await api(id ? `/api/accounts/vouchers/${id}` : "/api/accounts/vouchers",
    {method: id ? "PUT" : "POST", body});
  if (!res.ok) { btn.disabled = false; err.textContent = detail(res.body); return; }
  let posted = !id && !!f.post.checked;
  if (id && f.post.checked) {
    const post = await api(`/api/accounts/vouchers/${id}/post`, {method: "POST", body: {}});
    if (!post.ok) {
      btn.disabled = false;
      err.textContent = `The draft was saved but not posted: ${detail(post.body)}`;
      await loadVouchers();
      return;
    }
    posted = true;
  }
  btn.disabled = false;
  toast(res, posted ? "Voucher posted" : "Draft saved");
  closeDrawer();
  await loadVouchers();
  loadDayBook();
  loadBalanceSheet();
}

async function postVoucher(id) {
  const res = await api(`/api/accounts/vouchers/${id}/post`, {method: "POST", body: {}});
  toast(res, res.ok ? "Voucher posted" : "Not posted");
  if (res.ok) { await loadVouchers(); loadDayBook(); loadBalanceSheet(); }
}

async function deleteVoucher(id) {
  if (!confirm(`Delete draft voucher #${id}? A draft is not in the books, so deleting it leaves no trail.`)) return;
  const res = await api(`/api/accounts/vouchers/${id}`, {method: "DELETE"});
  toast(res, res.ok ? "Draft deleted" : "Not deleted");
  if (res.ok) await loadVouchers();
}

function reverseVoucherForm(id) {
  openDrawer("Reverse a posted voucher", "A mirror voucher dated today is posted, and the original is marked reversed. Both stay in the day book.", `
    <form id="voucherReverseForm" data-id="${id}" novalidate>
      <label for="vr-reason">Reason</label>
      <input id="vr-reason" name="reason" autocomplete="off" maxlength="300" placeholder="Why is this voucher being reversed?">
      <div class="note">A reversal is dated today, so a locked original month does not block it. If today is locked or closed, the reversal is refused.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Reverse voucher</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveVoucherReverse(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const reason = form.elements.reason.value.trim();
  if (reason.length < 5) { err.textContent = "Give a reason of at least 5 characters."; return; }
  btn.disabled = true;
  const res = await api(`/api/accounts/vouchers/${form.dataset.id}/reverse`, {method: "POST", body: {reason}});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, "Voucher reversed");
  closeDrawer();
  await loadVouchers();
  loadDayBook();
  loadBalanceSheet();
}

/* ---------------------------------------------------------------- day book */
function renderDayBook() {
  const book = lgState().daybook;
  const rows = book ? book.rows : [];
  $("#dbrows").innerHTML = rows.map(v => `<tr><td>${esc(v.date)}</td><td class="strong">${esc(v.number)}</td>
    <td>${esc(VOUCHER_TYPE_LABEL[v.type] || v.type)}</td><td>${esc(v.narration || "–")}</td>
    <td class="n">${money(v.debit)}</td><td class="n">${money(v.credit)}</td>
    <td>${v.status === "reversed" ? `<span class="chip bad">Reversed</span>` : `<span class="chip ok">Posted</span>`}</td>
    <td>${v.reverse_of ? `<span class="gap-note">mirror of #${v.reverse_of}</span>` : ""}</td></tr>`).join("");
  empty($("#dbempty"), !rows.length, "Nothing is posted in this window.",
    " Only posted vouchers appear here; a draft is not in the books.");
  $("#dbNote").innerHTML = book
    ? `${plural(book.count, "voucher")} · debit ${money(book.debit_total)} · credit ${money(book.credit_total)} · `
      + (book.balanced ? `<span class="chip ok">Balanced</span>` : `<span class="chip bad">Difference ${money(Number(book.debit_total) - Number(book.credit_total))}</span>`)
    : "";
}

async function loadDayBook() {
  const qs = new URLSearchParams();
  const from = $("#dbFrom").value, to = $("#dbTo").value;
  if (from) qs.set("date_from", from);
  if (to) qs.set("date_to", to);
  const res = await api(`/api/accounts/day-book${qs.toString() ? "?" + qs : ""}`);
  if (!res.ok) return toast(res, "Day book could not be built");
  lgState().daybook = res.body;
  renderDayBook();
}

/* --------------------------------------------------------- bank statements */
function renderBankStatements() {
  const rows = lgState().statements || [];
  const selected = lgState().selected;
  $("#bankStatements").innerHTML = rows.map(s => {
    const on = String(s.id) === String(selected);
    return `<tr${on ? ` class="on"` : ""}><td>${esc(s.account || "–")}</td>
      <td>${esc(s.period_from)} to ${esc(s.period_to)}${s.note ? `<small>${esc(s.note)}</small>` : ""}</td>
      <td class="n">${money(s.opening_balance)}</td><td class="n">${money(s.closing_balance)}</td>
      <td class="n">${s.lines}</td><td class="n">${s.matched} of ${s.lines}</td>
      <td><button class="btn ghost sm" type="button" data-act="open-bank-statement" data-id="${s.id}">Open</button></td></tr>`;
  }).join("");
  empty($("#bankEmpty"), !rows.length, "No bank statement is captured.",
    can("accounts:write") ? " Select “New statement” after the month's statement arrives." : "");
  $("#bankNote").textContent = rows.length ? `${plural(rows.length, "statement")} on file.` : "";
}

async function loadBankStatements() {
  const res = await api("/api/accounts/bank-statements");
  if (!res.ok) return toast(res, "Bank statements could not be loaded");
  lgState().statements = Array.isArray(res.body) ? res.body : [];
  renderBankStatements();
}

function renderBankDetail() {
  const box = $("#bankDetail");
  const lg = lgState();
  const d = lg.detail, rec = lg.rec;
  if (!lg.selected) {
    box.innerHTML = `<p class="muted panel-note">Open a statement to see its lines and the reconciliation proof.</p>`;
    return;
  }
  if (!d) {
    box.innerHTML = `<p class="muted panel-note">Loading the statement…</p>`;
    return;
  }
  const write = can("accounts:write");
  const actions = [];
  if (write) {
    actions.push(`<button class="btn ghost sm" type="button" data-act="bank-line-add">Add line</button>`);
    actions.push(`<button class="btn ghost sm" type="button" data-act="bank-edit-statement">Correct balances</button>`);
    actions.push(`<button class="btn ghost sm" type="button" data-act="bank-delete-statement">Delete statement</button>`);
  }
  let proof = "";
  if (rec) {
    const p = rec.proof;
    proof = `<div class="tw"><table>
        <thead><tr><th>Reconciliation proof</th><th class="n">Amount (₹)</th></tr></thead><tbody>
        <tr><td>Book closing balance</td><td class="n">${money(p.book_closing)}</td></tr>
        <tr><td>Less unmatched book entries</td><td class="n">${money(p.unmatched_book_net)}</td></tr>
        <tr><td class="strong">Adjusted book balance</td><td class="n strong">${money(p.adjusted_book)}</td></tr>
        <tr><td>Statement closing balance</td><td class="n">${money(p.statement_closing)}</td></tr>
        <tr><td>Less unmatched statement lines</td><td class="n">${money(p.unmatched_statement_net)}</td></tr>
        <tr><td class="strong">Adjusted statement balance</td><td class="n strong">${money(p.adjusted_statement)}</td></tr>
        <tr><td class="strong">Difference</td><td class="n strong">${money(p.difference)} ${p.balanced ? `<span class="chip ok">Balanced</span>` : `<span class="chip bad">Open</span>`}</td></tr>
        <tr><td>Opening difference <small>printed opening less book at ${esc(d.period_from)}</small></td><td class="n">${money(p.opening_difference)}</td></tr>
        <tr><td>Lines check <small>opening plus lines less printed closing</small></td><td class="n">${money(p.lines_check)}</td></tr>
        </tbody></table></div>
      <p class="muted panel-note">${plural(rec.matched.count, "line")} matched · matched debit ${money(rec.matched.debit)} · matched credit ${money(rec.matched.credit)}</p>
      <div class="panel-note"><b>What the proof says</b><ul class="gaps">${(rec.warnings || []).map(w => `<li>${esc(w)}</li>`).join("") || "<li>No warning is raised for this statement.</li>"}</ul></div>`;
  }
  const lines = (d.lines || []).map(line => {
    const acts = [];
    if (write) {
      if (line.matched) acts.push(`<button class="btn ghost sm" type="button" data-act="bank-line-unmatch" data-id="${line.id}">Unmatch</button>`);
      else {
        acts.push(`<button class="btn ghost sm" type="button" data-act="bank-line-match" data-id="${line.id}">Match</button>`);
        acts.push(`<button class="btn ghost sm" type="button" data-act="bank-line-delete" data-id="${line.id}">Delete</button>`);
      }
    }
    return `<tr><td>${esc(line.date)}</td><td class="strong">${esc(line.description)}</td>
      <td>${esc(line.reference || "–")}</td><td class="n strong">${money(line.amount)}</td>
      <td>${line.matched ? `<span class="chip ok">Matched</span>` : `<span class="chip warn">Unmatched</span>`}</td>
      <td class="rowacts">${acts.join(" ")}</td></tr>`;
  }).join("");
  const book = rec ? rec.unmatched_book : null;
  const bookRows = book ? [
    ...(book.receipts || []).map(x => ({label: x.party || "Receipt", date: x.date, amount: x.amount,
                                        note: `${esc(x.mode)} ${esc(x.reference || "")}`})),
    ...(book.payments || []).map(x => ({label: x.party || "Payment", date: x.date, amount: -Math.abs(Number(x.amount)),
                                        note: `${esc(x.mode)} ${esc(x.reference || "")}`})),
    ...(book.vouchers || []).map(x => ({label: x.voucher || "Voucher", date: x.date, amount: x.amount,
                                        note: esc(x.narration || "")})),
  ] : [];
  const bookTable = bookRows.length ? `<div class="tw"><table>
      <thead><tr><th>Unmatched in the books</th><th>Date</th><th class="n">Amount (₹)</th><th>Reference</th></tr></thead>
      <tbody>${bookRows.map(x => `<tr><td>${esc(x.label)}</td><td>${esc(x.date)}</td>
        <td class="n">${money(x.amount)}</td><td>${x.note}</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="muted panel-note">Every book entry inside this statement is matched, or none is in reach.</p>`;

  box.innerHTML = `<div class="toolbar" style="padding:12px 18px 0">
      <span class="muted">${esc(d.account || "")} · ${esc(d.period_from)} to ${esc(d.period_to)} · printed opening ${money(d.opening_balance)} and closing ${money(d.closing_balance)}${d.note ? ` · ${esc(d.note)}` : ""}</span>
      ${actions.join(" ")}
    </div>
    ${proof}
    <div class="tw"><table>
      <thead><tr><th>Date</th><th>Description</th><th>Reference</th><th class="n">Amount (₹)</th><th>State</th><th></th></tr></thead>
      <tbody>${lines || `<tr><td colspan="6" class="muted">No statement line is captured.</td></tr>`}</tbody>
    </table></div>
    ${bookTable}`;
}

async function loadBankSelected() {
  const lg = lgState();
  if (!lg.selected) { renderBankDetail(); return; }
  const id = lg.selected;
  const [detail, cands, rec] = await Promise.all([
    api(`/api/accounts/bank-statements/${id}`),
    api(`/api/accounts/bank-statements/${id}/candidates`),
    api(`/api/accounts/bank-statements/${id}/reconciliation`),
  ]);
  if (String(lg.selected) !== String(id)) return;
  lg.detail = detail.ok ? detail.body : null;
  lg.candidates = cands.ok ? cands.body : null;
  lg.rec = rec.ok ? rec.body : null;
  renderBankDetail();
  if (!detail.ok) toast(detail, "Statement could not be loaded");
}

function openBankStatement(id) {
  lgState().selected = Number(id);
  lgState().detail = null;
  lgState().rec = null;
  renderBankStatements();
  renderBankDetail();
  loadBankSelected();
}

function newBankStatement() {
  const heads = (lgState().heads || []).filter(h => h.role === "bank" && h.active);
  if (!heads.length) {
    return toast({ok: false, status: "—",
      body: {detail: "Create an active ledger head with the bank role first; a statement is captured against one bank head."}}, "No bank head");
  }
  openDrawer("Capture a bank statement", "What the bank printed for a period, plus its lines. Each line is matched later to one book entry; nothing is posted from here.", `
    <form id="bankStatementForm" novalidate>
      <label for="bs-account">Bank head</label>
      <select id="bs-account" name="account_id">${heads.map(h => `<option value="${h.id}">${esc(h.code)} · ${esc(h.name)}</option>`).join("")}</select>
      <div class="row2">
        <div><label for="bs-from">Period from</label><input id="bs-from" name="period_from" type="date" value="${isoDay(0).slice(0, 8)}01"></div>
        <div><label for="bs-to">Period to</label><input id="bs-to" name="period_to" type="date" value="${isoDay(0)}"></div>
      </div>
      <div class="row2">
        <div><label for="bs-opening">Printed opening (₹)</label><input id="bs-opening" name="opening_balance" inputmode="decimal" placeholder="0.00"></div>
        <div><label for="bs-closing">Printed closing (₹)</label><input id="bs-closing" name="closing_balance" inputmode="decimal" placeholder="0.00"></div>
      </div>
      <label for="bs-note">Note</label><input id="bs-note" name="note" maxlength="300" placeholder="Optional" autocomplete="off">
      <div class="note">Two statements may not overlap for the same bank head. The printed closing is compared with the book, never forced onto it.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save statement</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

async function saveBankStatement(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  if (!f.period_from.value || !f.period_to.value) { err.textContent = "Choose the statement period."; return; }
  if (!f.opening_balance.value || !f.closing_balance.value) { err.textContent = "Enter both printed balances."; return; }
  btn.disabled = true;
  const res = await api("/api/accounts/bank-statements", {method: "POST", body: {
    account_id: Number(f.account_id.value), period_from: f.period_from.value,
    period_to: f.period_to.value, opening_balance: f.opening_balance.value,
    closing_balance: f.closing_balance.value, note: f.note.value.trim() || null,
  }});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, "Bank statement saved");
  closeDrawer();
  lgState().selected = res.body.id;
  await loadBankStatements();
  renderBankStatements();
  await loadBankSelected();
}

function addBankLineForm() {
  const lg = lgState();
  if (!lg.selected || !lg.detail) return;
  const d = lg.detail;
  openDrawer("Add a statement line", `Inside ${d.period_from} to ${d.period_to}. A positive amount is money in; a negative amount is money out.`, `
    <form id="bankLineForm" data-statement="${d.id}" novalidate>
      <div class="row2">
        <div><label for="bl-date">Date</label><input id="bl-date" name="date" type="date" value="${isoDay(0)}"></div>
        <div><label for="bl-amount">Amount (₹)</label><input id="bl-amount" name="amount" inputmode="decimal" placeholder="Money in positive, out negative"></div>
      </div>
      <label for="bl-desc">Description</label><input id="bl-desc" name="description" maxlength="200" autocomplete="off" placeholder="As printed by the bank">
      <label for="bl-ref">Reference</label><input id="bl-ref" name="reference" maxlength="60" autocomplete="off" placeholder="Cheque or UTR">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Add line</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveBankLine(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  if (!f.description.value.trim()) { err.textContent = "Enter the description printed by the bank."; return; }
  if (!f.amount.value || Number(f.amount.value) === 0) { err.textContent = "Enter a non-zero amount."; return; }
  btn.disabled = true;
  const res = await api(`/api/accounts/bank-statements/${form.dataset.statement}/lines`, {method: "POST", body: {
    lines: [{date: f.date.value, description: f.description.value.trim(),
             reference: f.reference.value.trim() || null, amount: f.amount.value}],
  }});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, "Line added");
  closeDrawer();
  await loadBankSelected();
  loadBankStatements();
}

function editBankStatementForm() {
  const lg = lgState();
  if (!lg.selected || !lg.detail) return;
  const d = lg.detail;
  openDrawer("Correct a bank statement", "Only the printed balances and note can change. A line is deleted, never edited.", `
    <form id="bankEditForm" data-id="${d.id}" novalidate>
      <div class="row2">
        <div><label for="be-opening">Printed opening (₹)</label><input id="be-opening" name="opening_balance" inputmode="decimal" value="${money(d.opening_balance)}"></div>
        <div><label for="be-closing">Printed closing (₹)</label><input id="be-closing" name="closing_balance" inputmode="decimal" value="${money(d.closing_balance)}"></div>
      </div>
      <label for="be-note">Note</label><input id="be-note" name="note" maxlength="300" value="${esc(d.note || "")}" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save balances</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveBankEdit(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  btn.disabled = true;
  const res = await api(`/api/accounts/bank-statements/${form.dataset.id}`, {method: "PATCH", body: {
    opening_balance: f.opening_balance.value, closing_balance: f.closing_balance.value,
    note: f.note.value.trim() || null,
  }});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, "Balances saved");
  closeDrawer();
  await loadBankSelected();
  loadBankStatements();
}

async function deleteBankStatement() {
  const lg = lgState();
  if (!lg.selected) return;
  if (!confirm("Delete this bank statement and every line on it? A matched line must be unmatched first.")) return;
  const res = await api(`/api/accounts/bank-statements/${lg.selected}`, {method: "DELETE"});
  toast(res, res.ok ? "Statement deleted" : "Not deleted");
  if (!res.ok) return;
  lg.selected = null; lg.detail = null; lg.candidates = null; lg.rec = null;
  await loadBankStatements();
  renderBankDetail();
}

function bankMatchDrawer(lineId) {
  const lg = lgState();
  const d = lg.detail, c = lg.candidates;
  const line = d && (d.lines || []).find(x => String(x.id) === String(lineId));
  if (!line) return toast({ok: false, status: "—", body: {detail: "Reload the statement first"}}, "Line not found");
  if (!c) return toast({ok: false, status: "—", body: {detail: "The book entries could not be loaded"}}, "No candidates");
  const target = Number(line.amount);
  const items = [
    ...(c.receipts || []).map(x => ({...x, kind: "payment", label: x.party || "Receipt",
                                     note: `${x.mode} ${x.reference || ""}`, amount: Number(x.amount), dir: "in"})),
    ...(c.payments || []).map(x => ({...x, kind: "payment", label: x.party || "Payment",
                                     note: `${x.mode} ${x.reference || ""}`, amount: -Math.abs(Number(x.amount)), dir: "out"})),
    ...(c.vouchers || []).map(x => ({...x, kind: "voucher_line", label: x.voucher || "Voucher",
                                     note: x.narration || "", amount: Number(x.amount), dir: Number(x.amount) >= 0 ? "in" : "out"})),
  ].sort((a, b) => (Math.abs(b.amount - target) < 0.005 ? 1 : 0) - (Math.abs(a.amount - target) < 0.005 ? 1 : 0));
  const rows = items.map(x => {
    const same = Math.abs(x.amount - target) < 0.005;
    return `<tr><td>${esc(x.label)}${x.voucher ? "" : `<small>${esc(x.note)}</small>`}</td>
      <td>${esc(x.date)}</td><td class="n">${money(x.amount)}</td>
      <td>${same
        ? `<button class="btn ghost sm" type="button" data-act="bank-match" data-line="${line.id}" data-kind="${x.kind}" data-ref="${x.id}">Match</button>`
        : `<span class="gap-note">Amount differs</span>`}</td></tr>`;
  }).join("");
  openDrawer(`Match line ${money(line.amount)}`, `${line.description}${line.reference ? ` · ${line.reference}` : ""}. The amount must agree exactly, and the entry must not already be matched.`, `
    ${(c.warnings || []).length ? `<div class="panel-note"><b>Before matching</b><ul class="gaps">${(c.warnings || []).map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
    <div class="tw"><table>
      <thead><tr><th>Book entry</th><th>Date</th><th class="n">Amount (₹)</th><th></th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4" class="muted">No book entry in reach carries this amount.</td></tr>`}</tbody>
    </table></div>
    <div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`, true);
}

async function bankMatch(lineId, kind, refId) {
  const res = await api(`/api/accounts/bank-lines/${lineId}/match`, {method: "POST", body: {kind, ref_id: Number(refId)}});
  toast(res, res.ok ? "Line matched" : "Not matched");
  if (!res.ok) return;
  closeDrawer();
  await loadBankSelected();
  loadBankStatements();
}

async function bankUnmatch(lineId) {
  const res = await api(`/api/accounts/bank-lines/${lineId}/unmatch`, {method: "POST", body: {}});
  toast(res, res.ok ? "Line unmatched" : "Not unmatched");
  if (res.ok) { await loadBankSelected(); loadBankStatements(); }
}

async function deleteBankLine(lineId) {
  if (!confirm("Delete this statement line? A matched line must be unmatched first.")) return;
  const res = await api(`/api/accounts/bank-lines/${lineId}`, {method: "DELETE"});
  toast(res, res.ok ? "Line deleted" : "Not deleted");
  if (res.ok) { await loadBankSelected(); loadBankStatements(); }
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

/* ---------- input GST, filed returns and statutory dues ----------
   The input register is the only source of purchase-side tax, so net payable
   says "No data yet" until a supplier bill is captured instead of reporting
   zero. Filed figures are what the practitioner reported; the screen compares
   them with the registers and never decides which side is right. */
const GST_HEADS = ["cgst", "sgst", "igst", "cess"];

function renderInputGst() {
  const reg = state.accounts.inputGst, net = state.accounts.netGst;
  const rows = reg ? reg.rows : [];
  $("#igrows").innerHTML = rows.map(r => {
    const status = r.status === "reversed"
      ? `<span class="bad">Reversed</span><small>${esc(r.reversal_reason || "")}</small>`
      : "Posted";
    const act = can("accounts:write") && r.status === "posted"
      ? `<button class="btn ghost sm" type="button" data-act="reverse-purchase-invoice" data-id="${r.id}">Reverse</button>` : "";
    return `<tr><td class="strong">${esc(r.number)}</td><td>${esc(r.invoice_date)}</td>
      <td>${esc(r.supplier || "")}</td><td>${esc(r.supplier_invoice_number)}</td>
      <td class="n">${money(r.taxable)}</td><td class="n">${money(r.cgst)}</td>
      <td class="n">${money(r.sgst)}</td><td class="n">${money(r.igst)}</td>
      <td class="n">${money(r.cess)}</td><td class="n strong">${money(r.total)}</td>
      <td>${r.itc_eligible ? "Eligible" : `<span class="bad">Blocked</span>`}</td>
      <td>${status}</td><td>${act}</td></tr>`;
  }).join("");
  empty($("#igempty"), !rows.length,
    reg ? "No supplier bill is captured for that period." : "The input register could not be loaded.",
    reg ? " Capture the tax the supplier charged to claim input credit." : " Use “Build input register” to try again.");
  if (reg) {
    const t = reg.totals;
    $("#igTot").textContent = `${plural(reg.posted_count, "posted bill")} · taxable ${money(t.taxable)} · tax ${money(t.tax)} · blocked ${money(reg.blocked.tax)}`;
  }
  $("#igNet").textContent = !net ? "" : (net.available
    ? `Net GST payable ${money(net.net_total)}: output ${money(net.output_total)} less eligible input ${money(net.input_total)}`
      + ` (${GST_HEADS.map(h => `${h.toUpperCase()} ${money(net.net[h])}`).join(" · ")}).`
      + ` Blocked input ${money(net.blocked_total)} is shown separately and never netted.`
    : `No data yet: ${net.reason}`);
}

function renderReconciliation() {
  const rec = state.accounts.reconciliation;
  const out = [];
  if (rec) {
    rec.forms.forEach(f => {
      if (!f.filed) {
        out.push(`<tr><td class="strong">${esc(f.form)}</td><td colspan="5" class="muted">No filed return is recorded for this month.</td></tr>`);
        return;
      }
      f.checks.forEach(c => {
        const result = c.ok === true ? `<span class="chip ok">Matches</span>`
          : c.ok === false ? `<span class="chip bad">Difference</span>`
          : `<span class="muted">${esc(c.reason || "Not comparable")}</span>`;
        out.push(`<tr><td class="strong">${esc(f.form)}</td><td>${esc(c.label)}</td>
          <td class="n">${money(c.filed)}</td>
          <td class="n">${c.computed == null ? "No data yet" : money(c.computed)}</td>
          <td class="n">${c.difference == null ? "–" : money(c.difference)}</td><td>${result}</td></tr>`);
      });
    });
  }
  $("#recrows").innerHTML = out.join("");
  empty($("#recempty"), !out.length,
    rec ? "No filed return is recorded for this month." : "Reconciliation could not be loaded.",
    rec ? " Record the figures reported as filed to compare them with the registers." : " Use “Compare” to try again.");
  if (rec) {
    $("#recNote").textContent = `${MONTHS[rec.month - 1]} ${rec.year} · computed payable `
      + (rec.computed.tax_payable == null ? "No data yet" : money(rec.computed.tax_payable));
    const filed = state.accounts.filedReturns || [];
    const line = filed.length
      ? `Recorded filings: ${filed.map(r => `${r.form} ${MONTHS[r.month - 1]} ${r.year}${r.reference ? " (" + r.reference + ")" : ""}`).join(" · ")}. `
      : "";
    $("#recGap").textContent = line + (rec.reason
      || "Filed figures are what the practitioner reported; a difference is shown, not resolved.");
  }
}

function renderStatutory() {
  const dues = state.accounts.dues;
  const rows = dues ? dues.summary : [];
  $("#sdrows").innerHTML = rows.map(h => `<tr><td class="strong">${esc(h.label)}</td>
    <td class="n">${h.withheld_to_date == null ? "No data yet" : money(h.withheld_to_date)}</td>
    <td class="n">${money(h.deposited_to_date)}</td>
    <td class="n">${money(h.deposited_in_window)}</td>
    <td class="n strong">${h.outstanding == null ? "No data yet" : money(h.outstanding)}</td>
    <td>${h.reason ? `<span class="muted">${esc(h.reason)}</span>` : `<span class="chip ok">Available</span>`}</td></tr>`).join("");
  empty($("#sdempty"), !rows.length,
    dues ? "Statutory dues could not be built." : "TDS and statutory dues could not be loaded.",
    dues ? (dues.reason || " No deduction is recorded up to the window end.") : " Use “Build dues” to try again.");
  if (dues) {
    $("#sdNote").textContent = `${fmtDate(dues.from)} to ${fmtDate(dues.to)} · withheld and deposited are cumulative to the window end`;
    const bits = [];
    if (dues.vendor_tds.count) {
      bits.push(`Vendor TDS ${money(dues.vendor_tds.total)} across ${plural(dues.vendor_tds.count, "bill")}`);
    }
    if (dues.payroll.available) {
      bits.push(`Payroll ${plural(dues.payroll.periods.length, "approved period")}`);
    }
    if (dues.payroll.unmapped_reason) bits.push(dues.payroll.unmapped_reason);
    $("#sdDetail").textContent = bits.join(" · ") || dues.note;
  }
  const challans = state.accounts.challans || [];
  $("#chrows").innerHTML = challans.map(c => `<tr><td class="strong">${esc(c.challan_number)}</td>
    <td>${esc(c.label)}</td><td>${esc(c.paid_on)}</td>
    <td>${MONTHS[c.period_month - 1]} ${c.period_year}</td><td>${esc(c.section || "–")}</td>
    <td class="n strong">${money(c.amount)}</td></tr>`).join("");
  empty($("#chempty"), !challans.length, "No challan is recorded.",
    " A challan reduces the outstanding balance it settles.");
}

async function loadInputGst() {
  const from = $("#igFrom").value, to = $("#igTo").value;
  const qs = new URLSearchParams();
  if (from) qs.set("date_from", from);
  if (to) qs.set("date_to", to);
  const query = qs.toString() ? "?" + qs : "";
  const [reg, net] = await Promise.all([
    api(`/api/accounts/input-gst${query}`), api(`/api/accounts/gst-net${query}`)]);
  if (!reg.ok) return toast(reg, "Input register could not be built");
  state.accounts.inputGst = reg.body;
  state.accounts.netGst = net.ok ? net.body : null;
  renderInputGst();
}

async function loadReconciliation() {
  const year = Number($("#recYear").value) || new Date().getFullYear();
  const month = Number($("#recMonth").value) || new Date().getMonth() + 1;
  const [rec, rets] = await Promise.all([
    api(`/api/accounts/gst-reconciliation?year=${year}&month=${month}`),
    api(`/api/accounts/gst-returns?year=${year}`)]);
  if (!rec.ok) return toast(rec, "Reconciliation could not be built");
  state.accounts.reconciliation = rec.body;
  state.accounts.filedReturns = rets.ok ? rets.body.rows : [];
  renderReconciliation();
}

async function loadStatutory() {
  const from = $("#sdFrom").value, to = $("#sdTo").value;
  const qs = new URLSearchParams();
  if (from) qs.set("date_from", from);
  if (to) qs.set("date_to", to);
  const query = qs.toString() ? "?" + qs : "";
  const [dues, challans] = await Promise.all([
    api(`/api/accounts/statutory-dues${query}`), api("/api/accounts/statutory-challans")]);
  if (!dues.ok) return toast(dues, "Statutory dues could not be built");
  state.accounts.dues = dues.body;
  state.accounts.challans = challans.ok ? challans.body.rows : [];
  renderStatutory();
}

function openAccountsStatements() {
  if (!can("accounts:read")) return;
  ["piNewBtn", "grNewBtn", "chNewBtn", "lhNewBtn", "vNewBtn", "bankNewBtn"].forEach(id => {
    const el = $("#" + id);
    if (el) el.classList.toggle("hide", !can("accounts:write"));
  });
  const today = new Date();
  if ($("#recYear") && !$("#recYear").value) $("#recYear").value = today.getFullYear();
  const sel = $("#recMonth");
  if (sel && !sel.value) {
    sel.innerHTML = MONTHS.map((m, i) => `<option value="${i + 1}">${m}</option>`).join("");
    sel.value = today.getMonth() + 1;
  }
  if ($("#sdFrom") && !$("#sdFrom").value) $("#sdFrom").value = isoDay(0).slice(0, 8) + "01";
  if ($("#sdTo") && !$("#sdTo").value) $("#sdTo").value = isoDay(0);
  if ($("#bsAsOf") && !$("#bsAsOf").value) $("#bsAsOf").value = isoDay(0);
  if ($("#obFy") && !$("#obFy").value) $("#obFy").value = currentFyLabel();
  if ($("#vFrom") && !$("#vFrom").value) $("#vFrom").value = isoDay(0).slice(0, 8) + "01";
  if ($("#vTo") && !$("#vTo").value) $("#vTo").value = isoDay(0);
  if ($("#dbFrom") && !$("#dbFrom").value) $("#dbFrom").value = isoDay(0).slice(0, 8) + "01";
  if ($("#dbTo") && !$("#dbTo").value) $("#dbTo").value = isoDay(0);
  prepareRbdInputs();
  if (!state.accounts.inputGst) loadInputGst();
  if (!state.accounts.reconciliation) loadReconciliation();
  if (!state.accounts.dues) loadStatutory();
  if (!state.accounts.years) loadPeriods();
  const lg = state.accounts.ledger;
  if (!lg.heads) loadLedgerHeads();
  if (!lg.openings) loadOpenings();
  if (!lg.sheet) loadBalanceSheet();
  if (!lg.vouchers) loadVouchers();
  if (!lg.daybook) loadDayBook();
  if (!lg.statements) loadBankStatements();
  renderBankDetail();
}

function newPurchaseInvoice() {
  const suppliers = (state.suppliers || []).filter(s => s.status !== "inactive");
  if (!suppliers.length) return toast({ok: false, status: "—",
    body: {detail: "Add an active supplier first."}}, "No supplier to bill");
  openDrawer("Capture a supplier bill",
    "The tax the supplier charged, head by head. This records input credit and does not change payables.", `
    <form id="piForm" novalidate>
      <label for="pi-supplier">Supplier</label>
      <select id="pi-supplier" name="supplier_id">${suppliers.map(s =>
        `<option value="${s.id}">${esc(s.code)} · ${esc(s.name)}</option>`).join("")}</select>
      <div class="row2">
        <div><label for="pi-number">Supplier invoice number</label><input id="pi-number" name="supplier_invoice_number" autocomplete="off"></div>
        <div><label for="pi-date">Invoice date</label><input id="pi-date" name="invoice_date" type="date" value="${isoDay(0)}"></div>
      </div>
      <div class="row2">
        <div><label for="pi-taxable">Taxable value (₹)</label><input id="pi-taxable" name="taxable_value" inputmode="decimal" placeholder="0.00"></div>
        <div><label for="pi-cgst">CGST (₹)</label><input id="pi-cgst" name="cgst_amount" inputmode="decimal" placeholder="0.00"></div>
      </div>
      <div class="row2">
        <div><label for="pi-sgst">SGST (₹)</label><input id="pi-sgst" name="sgst_amount" inputmode="decimal" placeholder="0.00"></div>
        <div><label for="pi-igst">IGST (₹)</label><input id="pi-igst" name="igst_amount" inputmode="decimal" placeholder="0.00"></div>
      </div>
      <div class="row2">
        <div><label for="pi-cess">Cess (₹)</label><input id="pi-cess" name="cess_amount" inputmode="decimal" placeholder="0.00"></div>
        <div><label for="pi-round">Round off (₹)</label><input id="pi-round" name="round_off" inputmode="decimal" placeholder="0.00"></div>
      </div>
      <label><input type="checkbox" id="pi-itc" name="itc_eligible" checked> Input credit is eligible</label>
      <div class="row2">
        <div><label for="pi-tds-section">TDS section</label><input id="pi-tds-section" name="tds_section" placeholder="194C, optional" autocomplete="off"></div>
        <div><label for="pi-tds-amount">TDS amount (₹)</label><input id="pi-tds-amount" name="tds_amount" inputmode="decimal" placeholder="0.00"></div>
      </div>
      <label for="pi-note">Note</label><input id="pi-note" name="note" placeholder="Optional" autocomplete="off">
      <div class="note">A bill is never edited. A wrong one is reversed with a reason and kept on file.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save bill</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

async function savePurchaseInvoice(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const number = f.supplier_invoice_number.value.trim();
  if (!number) { err.textContent = "Enter the supplier's invoice number."; return; }
  if (!(Number(f.taxable_value.value) >= 0)) { err.textContent = "Enter the taxable value."; return; }
  const body = {
    supplier_id: Number(f.supplier_id.value),
    supplier_invoice_number: number,
    invoice_date: f.invoice_date.value,
    taxable_value: f.taxable_value.value || "0",
    cgst_amount: f.cgst_amount.value || "0",
    sgst_amount: f.sgst_amount.value || "0",
    igst_amount: f.igst_amount.value || "0",
    cess_amount: f.cess_amount.value || "0",
    round_off: f.round_off.value || "0",
    itc_eligible: f.itc_eligible.checked,
    tds_amount: f.tds_amount.value || "0",
    note: f.note.value.trim() || null
  };
  if (f.tds_section.value.trim()) body.tds_section = f.tds_section.value.trim();
  btn.disabled = true;
  const res = await api("/api/accounts/purchase-invoices", {method: "POST", body});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); toast(res, "Supplier bill captured");
  await Promise.all([loadInputGst(), loadReconciliation()]);
}

function reversePurchaseInvoice(id) {
  openDrawer("Reverse a supplier bill",
    "The bill stays on file and leaves the input register.", `
    <form id="piReverseForm" data-id="${id}" novalidate>
      <label for="pir-reason">Reason</label><input id="pir-reason" name="reason" autocomplete="off">
      <div class="note">The original row stays; its status becomes Reversed and it no longer counts as input credit.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Reverse bill</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function savePurchaseInvoiceReverse(form) {
  const err = $(".err", form);
  const reason = form.elements.reason.value.trim();
  if (reason.length < 5) { err.textContent = "Give a reason of at least 5 characters."; return; }
  const res = await api(`/api/accounts/purchase-invoices/${form.dataset.id}/reverse`,
                        {method: "POST", body: {reason}});
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); toast(res, "Supplier bill reversed");
  await Promise.all([loadInputGst(), loadReconciliation()]);
}

function newGstReturn() {
  const year = Number($("#recYear").value) || new Date().getFullYear();
  const month = Number($("#recMonth").value) || new Date().getMonth() + 1;
  openDrawer("Record filed GST figures",
    "What the practitioner reported as filed. The application compares it with the registers; it never files.", `
    <form id="grForm" novalidate>
      <div class="row2">
        <div><label for="gr-form">Form</label><select id="gr-form" name="form"><option>GSTR-3B</option><option>GSTR-1</option></select></div>
        <div><label for="gr-filed">Filed on</label><input id="gr-filed" name="filed_on" type="date" value="${isoDay(0)}"></div>
      </div>
      <div class="row2">
        <div><label for="gr-year">Year</label><input id="gr-year" name="year" type="number" min="2000" max="2100" value="${year}"></div>
        <div><label for="gr-month">Month</label><select id="gr-month" name="month">${MONTHS.map((m, i) =>
          `<option value="${i + 1}"${i + 1 === month ? " selected" : ""}>${m}</option>`).join("")}</select></div>
      </div>
      <label for="gr-ref">Portal reference</label><input id="gr-ref" name="reference" placeholder="ARN, optional" autocomplete="off">
      <div class="note">Outward supplies as reported</div>
      <div class="row2">
        <div><label for="gr-taxable">Taxable value (₹)</label><input id="gr-taxable" name="outward_taxable" inputmode="decimal" placeholder="0.00"></div>
        <div><label for="gr-cgst">CGST (₹)</label><input id="gr-cgst" name="outward_cgst" inputmode="decimal" placeholder="0.00"></div>
      </div>
      <div class="row2">
        <div><label for="gr-sgst">SGST (₹)</label><input id="gr-sgst" name="outward_sgst" inputmode="decimal" placeholder="0.00"></div>
        <div><label for="gr-igst">IGST (₹)</label><input id="gr-igst" name="outward_igst" inputmode="decimal" placeholder="0.00"></div>
      </div>
      <div class="row2">
        <div><label for="gr-cess">Cess (₹)</label><input id="gr-cess" name="outward_cess" inputmode="decimal" placeholder="0.00"></div>
        <div></div>
      </div>
      <div class="note">Input credit as reported — GSTR-3B only</div>
      <div class="row2">
        <div><label for="gr-itc-cgst">ITC CGST (₹)</label><input id="gr-itc-cgst" name="itc_cgst" inputmode="decimal" placeholder="0.00"></div>
        <div><label for="gr-itc-sgst">ITC SGST (₹)</label><input id="gr-itc-sgst" name="itc_sgst" inputmode="decimal" placeholder="0.00"></div>
      </div>
      <div class="row2">
        <div><label for="gr-itc-igst">ITC IGST (₹)</label><input id="gr-itc-igst" name="itc_igst" inputmode="decimal" placeholder="0.00"></div>
        <div><label for="gr-itc-cess">ITC cess (₹)</label><input id="gr-itc-cess" name="itc_cess" inputmode="decimal" placeholder="0.00"></div>
      </div>
      <label for="gr-note">Note</label><input id="gr-note" name="note" placeholder="Optional" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save filed figures</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

async function saveGstReturn(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const body = {form: f.form.value, year: Number(f.year.value), month: Number(f.month.value),
                filed_on: f.filed_on.value, reference: f.reference.value.trim() || null,
                note: f.note.value.trim() || null};
  ["outward_taxable", "outward_cgst", "outward_sgst", "outward_igst", "outward_cess",
   "itc_cgst", "itc_sgst", "itc_igst", "itc_cess"].forEach(key => {
    body[key] = f[key].value || "0";
  });
  btn.disabled = true;
  const res = await api("/api/accounts/gst-returns", {method: "POST", body});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); toast(res, "Filed figures recorded");
  $("#recYear").value = body.year;
  $("#recMonth").value = String(body.month);
  await loadReconciliation();
}

function newChallan() {
  const year = Number($("#recYear").value) || new Date().getFullYear();
  const month = Number($("#recMonth").value) || new Date().getMonth() + 1;
  openDrawer("Record a statutory challan",
    "Money paid to the government. It reduces the outstanding balance it settles.", `
    <form id="chForm" novalidate>
      <div class="row2">
        <div><label for="ch-kind">Head</label><select id="ch-kind" name="kind">
          <option value="pf">Provident fund</option><option value="esi">Employee state insurance</option>
          <option value="pt">Professional tax</option><option value="tds">Tax deducted at source</option></select></div>
        <div><label for="ch-amount">Amount (₹)</label><input id="ch-amount" name="amount" inputmode="decimal" placeholder="0.00"></div>
      </div>
      <div class="row2">
        <div><label for="ch-number">Challan number</label><input id="ch-number" name="challan_number" autocomplete="off"></div>
        <div><label for="ch-bsr">BSR code</label><input id="ch-bsr" name="bsr_code" placeholder="Optional" autocomplete="off"></div>
      </div>
      <div class="row2">
        <div><label for="ch-paid">Paid on</label><input id="ch-paid" name="paid_on" type="date" value="${isoDay(0)}"></div>
        <div><label for="ch-section">Section</label><input id="ch-section" name="section" placeholder="Optional" autocomplete="off"></div>
      </div>
      <div class="row2">
        <div><label for="ch-year">Period year</label><input id="ch-year" name="period_year" type="number" min="2000" max="2100" value="${year}"></div>
        <div><label for="ch-month">Period month</label><select id="ch-month" name="period_month">${MONTHS.map((m, i) =>
          `<option value="${i + 1}"${i + 1 === month ? " selected" : ""}>${m}</option>`).join("")}</select></div>
      </div>
      <label for="ch-note">Note</label><input id="ch-note" name="note" placeholder="Optional" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save challan</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

async function saveChallan(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  if (!f.challan_number.value.trim()) { err.textContent = "Enter the challan number."; return; }
  if (!(Number(f.amount.value) > 0)) { err.textContent = "Enter an amount greater than zero."; return; }
  const body = {kind: f.kind.value, challan_number: f.challan_number.value.trim(),
                bsr_code: f.bsr_code.value.trim() || null, paid_on: f.paid_on.value,
                amount: f.amount.value, period_year: Number(f.period_year.value),
                period_month: Number(f.period_month.value),
                section: f.section.value.trim() || null,
                note: f.note.value.trim() || null};
  btn.disabled = true;
  const res = await api("/api/accounts/statutory-challans", {method: "POST", body});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); toast(res, "Challan recorded");
  await loadStatutory();
}


/* ---------- accounts performance (accounts:reports) ----------
   The statements above need accounts:read. This section is the narrower
   accounts:reports right: the Administrator, the MD or an Accounts head the
   Administrator has granted it. The server enforces the same key. */
const accMoney = v => (Number(v) < 0 ? "−₹ " : "₹ ") + money(Math.abs(Number(v) || 0));
const accQuery = () => {
  const p = new URLSearchParams({from_date: state.acc.from, to_date: state.acc.to});
  if (state.acc.state) p.set("state", state.acc.state);
  return p.toString();
};
const ACC_PANELS = ["#accPerfPanel", "#accPnlPanel", "#accCmpPanel", "#accTrendPanel",
                    "#accStatePanel", "#accGapPanel"];
/* Each Accounts subsection is its own address, so a view can be bookmarked,
   opened from a dashboard tile or refreshed without the whole page of panels. */
const ACC_SECTIONS = [
  {key: "reports", label: "Performance and P&L", reports: true},
  {key: "receivables", label: "Receivables"},
  {key: "receivables-by-distributor", label: "Receivables by distributor"},
  {key: "ageing", label: "Ageing"},
  {key: "payables", label: "Payables"},
  {key: "cash", label: "Receipts and payments"},
  {key: "gst-out", label: "GST outward"},
  {key: "gst-in", label: "Input GST"},
  {key: "gst-returns", label: "GST returns"},
  {key: "statutory", label: "TDS and statutory"},
  {key: "trial-balance", label: "Trial balance"},
  {key: "ledger-heads", label: "Ledger heads"},
  {key: "openings", label: "Opening balances"},
  {key: "balance-sheet", label: "Balance sheet"},
  {key: "vouchers", label: "Vouchers"},
  {key: "day-book", label: "Day book"},
  {key: "bank", label: "Bank reconciliation"},
  {key: "years", label: "Financial years"},
  {key: "locks", label: "Month locks"},
];
const accSectionAllowed = s => s.reports ? accAllowed() : can("accounts:read");
const defaultAccountsSection = () => accAllowed() ? "reports" : "receivables";

function renderAccountsNav() {
  const nav = $("#accNav");
  if (!nav) return;
  const visible = ACC_SECTIONS.filter(accSectionAllowed);
  if (nav.dataset.count !== String(visible.length)) {
    nav.innerHTML = visible.map(s =>
      `<a href="#/accounts/${esc(s.key)}" data-acc-section="${esc(s.key)}">${esc(s.label)}</a>`).join("");
    nav.dataset.count = String(visible.length);
  }
  $$("a", nav).forEach(a => {
    const on = a.dataset.accSection === state.acc.section;
    a.classList.toggle("on", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

function applyAccountsSection() {
  const sec = (() => {
    const current = ACC_SECTIONS.find(s => s.key === state.acc.section && accSectionAllowed(s));
    return current ? current.key : defaultAccountsSection();
  })();
  state.acc.section = sec;
  renderAccountsNav();
  ACC_PANELS.forEach(sel => {
    const el = $(sel);
    if (el) el.classList.toggle("hide", !(accAllowed() && sec === "reports"));
  });
  const scope = $("#v-accounts") || document;
  $$("[data-acc-sec]", scope).forEach(el => {
    el.classList.toggle("hide", !(can("accounts:read") && el.dataset.accSec === sec));
  });
}

function openAccountsSectionData() {
  if (!can("accounts:read")) return;
  if (state.acc.section === "gst-out" && !state.accounts.gst) loadGstRegister();
  if (state.acc.section === "trial-balance" && !state.accounts.tb) loadTrialBalance();
  if (state.acc.section === "receivables-by-distributor" && !state.acc.rbd.data
      && !state.acc.rbd.loading) loadReceivablesByDistributor();
}

function renderDashAccounts(a) {
  const panel = $("#accOverviewPanel"), el = $("#accOverview");
  if (!panel || !el) return;
  panel.classList.toggle("hide", !a);
  if (!a) return;
  $("#accOverviewNote").textContent =
    `${fmtDate(a.from)} to ${fmtDate(a.to)} · snapshot balances as at ${fmtDate(a.to)}`;
  const tiles = [
    ["Receivables", a.receivable_total, "#/accounts",
     `${accMoney(a.overdue_60)} has been outstanding more than 60 days.`],
    ["Payables", a.payable_total, "#/accounts",
     `${accMoney(a.payable_due_this_week)} estimated to fall due within 7 days.`],
    ["Cash and bank (net)", a.cash_bank_net, "#/accounts",
     "Receipts minus payments in the selected window; opening balances are not captured."],
    ["Output GST", a.output_gst, "#/accounts",
     "Output only; purchase-side tax is not captured."],
    ["Gross profit", a.gross_profit, "#/accounts",
     a.gross_profit_partial
       ? `${a.invoices_costed} of ${a.invoices_total} invoices fully costed; the rest are named in the gaps.`
       : "Net revenue less cost of goods sold.", null, a.gross_profit_label],
    ["Expenses", a.expenses, "#/expenses",
     a.expenses_note || "Approved entries in the window; non-creditable GST is part of the cost.",
     a.expenses_gap, null, a.expenses_partial ? "Partial" : null],
    ["Net profit", a.net_profit, "#/accounts", a.net_profit_note || "Cost, expenses and payroll are not all complete.",
     a.net_profit_gap],
  ];
  el.innerHTML = tiles.map(([label, value, href, note, gap, shown, partial]) => gap
    ? `<a class="kpi cmp-card-gap" href="${esc(href)}"><span class="kpi-label">${esc(label)}<span class="chip off">Gap ${esc(gap)}</span></span><span class="kpi-value">No data yet</span><span class="kpi-note">${esc(note)}</span></a>`
    : `<a class="kpi" href="${esc(href)}"><span class="kpi-label">${esc(shown || label)}${partial ? ` <span class="chip off">Partial</span>` : ""}</span><span class="kpi-value">${esc(accMoney(value))}</span><span class="kpi-note">${esc(note)}</span></a>`).join("");
}

function openAccountsReports() {
  if (!accAllowed()) return renderAccountsReport();
  renderAccountsReport();
  if (!state.acc.report && !state.acc.loading) loadAccountsReport();
  if (!state.acc.cmp.data && !state.acc.cmp.loading) loadAccountsCompare();
}

async function loadAccountsReport() {
  if (!accAllowed()) return;
  const s = state.acc, seq = ++s.seq;
  s.loading = true; s.error = null;
  renderAccountsReport();
  const res = await api(`/api/accounts/report?${accQuery()}`);
  if (seq !== s.seq || !state.user) return;
  s.loading = false;
  if (res.ok && res.body && !Array.isArray(res.body)) { s.report = res.body; s.error = null; }
  else s.error = detail(res.body);
  renderAccountsReport();
}

async function loadAccountsCompare() {
  if (!accAllowed()) return;
  const s = state.acc.cmp, seq = ++s.seq;
  s.loading = true; s.error = null;
  renderAccountsReport();
  const params = new URLSearchParams({mode: s.mode});
  if (s.month) params.set("month", s.month);
  const res = await api(`/api/accounts/report/compare?${params.toString()}`);
  if (seq !== s.seq || !state.user) return;
  s.loading = false;
  if (res.ok && res.body && !Array.isArray(res.body)) { s.data = res.body; s.error = null; }
  else s.error = detail(res.body);
  renderAccountsReport();
}

function renderAccountsReport() {
  const allowed = accAllowed();
  applyAccountsSection();
  if (!allowed) return;
  const s = state.acc, r = s.report, cmp = s.cmp;
  const fromEl = $("#accFrom"), toEl = $("#accTo"), monthEl = $("#accMonth");
  const today = dayIso(new Date());
  if (fromEl) { fromEl.max = today; if (document.activeElement !== fromEl) fromEl.value = s.from; }
  if (toEl) { toEl.max = today; if (document.activeElement !== toEl) toEl.value = s.to; }
  if (monthEl && document.activeElement !== monthEl) monthEl.value = cmp.month || (cmp.data ? cmp.data.month : "");
  $$("[data-acc-mode]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.accMode === cmp.mode)));

  $("#accPerfErr").classList.toggle("hide", !s.error);
  $("#accPerfErr").textContent = s.error ? `The accounts figures could not be loaded. Last good figures are kept. ${s.error}` : "";
  $("#accPerfNote").textContent = r
    ? `${fmtDate(r.from)} to ${fmtDate(r.to)} · ${plural(r.days, "day")}${r.region ? ` · ${r.region.label}` : " · all states"}${s.loading ? " · refreshing…" : ""}`
    : s.loading ? "Loading figures from the server…" : "Choose a window and refresh.";

  // The region list is always the full company, not the filtered view.
  const stateEl = $("#accState");
  if (stateEl && r) {
    const rows = (r.states || []).filter(x => x.state);
    const current = stateEl.value;
    stateEl.innerHTML = `<option value="">All states</option>` + rows.map(x =>
      `<option value="${esc(x.state)}"${x.state === s.state ? " selected" : ""}>${esc(x.name)}</option>`).join("");
    if (stateEl.value !== current && s.state) stateEl.value = s.state;
  }

  if (!r) {
    $("#accKpis").innerHTML = "";
    ["#accPnl", "#accCmp", "#accTrend", "#accStates", "#accGaps"].forEach(sel => {
      const el = $(sel); if (el) el.innerHTML = `<p class="gap-note">No figures loaded yet.</p>`;
    });
    return;
  }

  $("#accKpis").innerHTML = r.cards.map(c => {
    if (c.available === false) {
      return `<a class="kpi cmp-card-gap" href="${esc(c.href || "#/accounts")}"><span class="kpi-label">${esc(c.label)}<span class="chip off">Gap ${esc(c.gap)}</span></span>`
        + `<span class="kpi-value">No data yet</span><span class="kpi-note">${esc(c.note)}</span></a>`;
    }
    return `<a class="kpi" href="${esc(c.href || "#/accounts")}"><span class="kpi-label">${esc(c.label)}</span>`
      + `<span class="kpi-value">${esc(accMoney(c.value))}</span>`
      + `<span class="kpi-note">${esc(c.note)}</span></a>`;
  }).join("");
  $("#accPerfGaps").textContent = r.notes && r.notes.length ? r.notes.join(" ") : "";

  renderAccPnl(r.profit_and_loss);
  renderAccTrend(r);
  renderAccStates(r);
  renderAccGaps(r.gaps);
  renderAccountsCompare(cmp);
}

function renderAccPnl(pnl) {
  if (!pnl) return;
  const rows = (pnl.rows || []).map(row => {
    if (row.available === false) {
      const fix = row.fix ? ` <a class="link-btn" href="${esc(row.fix)}">Fix this</a>` : "";
      return `<tr><td class="strong">${esc(row.label)}</td><td class="n"><span class="chip off">Gap ${esc(row.gap)}</span> <span class="gap-note">No data yet. ${esc(row.note || "")}</span>${fix}</td></tr>`;
    }
    const note = row.note ? ` <small>${esc(row.note)}</small>` : "";
    const partial = row.partial ? ` <span class="chip off">Partial</span>` : "";
    const fix = row.partial && row.fix
      ? ` <a class="link-btn" href="${esc(row.fix)}">Fix this</a>` : "";
    return `<tr><td class="strong">${esc(row.label)}</td><td class="n strong">${esc(accMoney(row.value))}${partial}${note}${fix}</td></tr>`;
  }).join("");
  const notes = (pnl.notes || []).map(n => `<li>${esc(n)}</li>`).join("");
  $("#accPnl").innerHTML = `<div class="tw"><table>
      <thead><tr><th>Line</th><th class="n">Amount</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <p class="muted panel-note">${esc(pnl.note || "")}</p>`
    + (notes ? `<div class="panel-note"><b>Notes</b><ul class="gaps">${notes}</ul></div>` : "");
}

function renderAccTrend(r) {
  const months = r.trend || [];
  if (!months.length) {
    $("#accTrend").innerHTML = `<p class="gap-note">No month falls in the trend window.</p>`;
    return;
  }
  const selected = (r.to || "").slice(0, 7);
  $("#accTrend").innerHTML = `<div class="tw"><table>
      <thead><tr><th>Month</th><th class="n">Revenue</th><th class="n">Collections</th>`
    + `<th class="n">Payments</th><th class="n">Net cash</th><th class="n">Output GST</th><th class="n">Returns</th></tr></thead><tbody>`
    + months.map(m => {
        const on = `${m.year}-${String(m.month).padStart(2, "0")}` === selected;
        return `<tr${on ? ` class="on"` : ""}><td class="strong">${esc(m.label)}</td>`
          + `<td class="n">${esc(accMoney(m.revenue))}</td><td class="n">${esc(accMoney(m.collections))}</td>`
          + `<td class="n">${esc(accMoney(m.payments))}</td><td class="n">${esc(accMoney(m.net_cash))}</td>`
          + `<td class="n">${esc(accMoney(m.output_gst))}</td><td class="n">${esc(accMoney(m.returns))}</td></tr>`;
      }).join("")
    + `</tbody></table></div><p class="muted panel-note">Net cash is receipts minus supplier payments. GST here is output tax on issued documents; input tax and net payable come from captured supplier bills in the input register.</p>`;
}

function renderAccStates(r) {
  const rows = r.states || [];
  if (!rows.length) {
    $("#accStates").innerHTML = `<p class="gap-note">No issued invoice falls in this window.</p>`;
    return;
  }
  const total = rows.reduce((sum, x) => sum + Number(x.revenue || 0), 0);
  $("#accStates").innerHTML = `<div class="tw"><table>
      <thead><tr><th>State</th><th class="n">Invoices</th><th class="n">Revenue</th><th class="n">Share</th>`
    + `<th class="n">Output GST</th><th class="n">Returns</th><th class="n">Outstanding</th><th></th></tr></thead><tbody>`
    + rows.map(x => {
        const share = total > 0 ? Number(x.revenue) / total * 100 : 0;
        const btn = x.state ? `<button class="rowbtn" type="button" data-acc-state="${esc(x.state)}">Filter</button>` : "";
        return `<tr><td class="strong">${esc(x.name)}</td><td class="n">${esc(qty(x.invoices))}</td>`
          + `<td class="n">${esc(accMoney(x.revenue))}</td><td class="n">${esc(share.toFixed(1))}%</td>`
          + `<td class="n">${esc(accMoney(x.output_gst))}</td><td class="n">${esc(accMoney(x.returns))}</td>`
          + `<td class="n">${esc(accMoney(x.outstanding))}</td><td>${btn}</td></tr>`;
      }).join("")
    + `</tbody></table></div><p class="muted panel-note">Outstanding is grouped by the distributor's current state, because an invoice stores no distributor state snapshot apart from the buyer state used for revenue.</p>`;
}

/* ---------- receivables by distributor (accounts:read) ----------
   Its own navigation section with one From - To date range. Moving the dates
   does not reload anything; the report changes only when Apply is pressed.
   The server builds every figure from the documents; this screen only shows
   the answer and exports the same rows. */
function prepareRbdInputs() {
  const s = state.acc.rbd, today = isoDay(0);
  if (!s.from) { s.from = today.slice(0, 8) + "01"; s.to = today; }
  const from = $("#rbdFrom"), to = $("#rbdTo");
  if (from) { from.max = today; if (!from.value) from.value = s.from; }
  if (to) { to.max = today; if (!to.value) to.value = s.to; }
}

async function loadReceivablesByDistributor() {
  if (!can("accounts:read")) return;
  prepareRbdInputs();
  const s = state.acc.rbd, seq = ++s.seq;
  s.loading = true; s.error = null;
  renderRbd();
  const params = new URLSearchParams({from_date: s.from, to_date: s.to});
  const res = await api(`/api/accounts/receivables-by-distributor?${params.toString()}`);
  if (seq !== s.seq || !state.user) return;
  s.loading = false;
  if (res.ok && res.body && !Array.isArray(res.body)) {
    s.data = res.body; s.error = null;
    s.from = res.body.from; s.to = res.body.to;
    syncRbdInputs(s.from, s.to);
  } else {
    s.error = detail(res.body);
  }
  renderRbd();
}

function renderRbd() {
  const s = state.acc.rbd, d = s.data;
  if (!$("#rbdRows")) return;
  $("#rbdErr").classList.toggle("hide", !s.error);
  $("#rbdErr").textContent = s.error
    ? `The receivables report could not be loaded. Last good figures are kept. ${s.error}` : "";
  $("#rbdNote").textContent = d
    ? `${fmtDate(d.from)} to ${fmtDate(d.to)} · opening, movements and closing at ${fmtDate(d.to)}${s.loading ? " · refreshing…" : ""}`
    : s.loading ? "Loading from the server…" : "Choose a From – To date range and click Apply.";
  if (!d) {
    $("#rbdRows").innerHTML = "";
    $("#rbdFoot").innerHTML = "";
    empty($("#rbdEmpty"), !s.loading, "No figures loaded yet.", " Choose a window to build the report.");
    $("#rbdFootnote").textContent = "";
    return;
  }
  const canLedger = can("accounts:read");
  $("#rbdRows").innerHTML = d.rows.map(x => `<tr>
    <td class="strong">${esc(x.name)}${x.code ? `<br><small>${esc(x.code)}</small>` : ""}</td>
    <td>${esc(x.state || "–")}</td>
    <td class="n">${esc(accMoney(x.opening))}</td>
    <td class="n">${esc(accMoney(x.invoiced))}</td>
    <td class="n">${esc(accMoney(x.credited))}</td>
    <td class="n">${esc(accMoney(x.debited))}</td>
    <td class="n">${esc(accMoney(x.received))}</td>
    <td class="n strong">${esc(accMoney(x.closing))}</td>
    <td class="n">${Number(x.overdue) > 0 ? `<span class="bad">${esc(accMoney(x.overdue))}</span>` : esc(accMoney(x.overdue))}</td>
    <td class="n">${esc(qty(x.open_invoices))}</td>
    <td>${canLedger ? `<button class="rowbtn" type="button" data-act="acc-ledger" data-id="${esc(x.distributor_id)}">Open ledger</button>` : ""}</td>
  </tr>`).join("");
  const t = d.totals;
  $("#rbdFoot").innerHTML = `<tr><td class="strong">Total</td><td></td>
    <td class="n strong">${esc(accMoney(t.opening))}</td>
    <td class="n strong">${esc(accMoney(t.invoiced))}</td>
    <td class="n strong">${esc(accMoney(t.credited))}</td>
    <td class="n strong">${esc(accMoney(t.debited))}</td>
    <td class="n strong">${esc(accMoney(t.received))}</td>
    <td class="n strong">${esc(accMoney(t.closing))}</td>
    <td class="n strong">${esc(accMoney(t.overdue))}</td>
    <td class="n strong">${esc(qty(t.open_invoices))}</td><td></td></tr>`;
  empty($("#rbdEmpty"), !d.rows.length, "Nothing is owed or has moved in this window.",
    " Every distributor balance and every movement in the window is zero.");
  $("#rbdFootnote").textContent = d.note || "";
}

function syncRbdInputs(from, to) {
  if ($("#rbdFrom")) $("#rbdFrom").value = from;
  if ($("#rbdTo")) $("#rbdTo").value = to;
}

function applyRbdFilter() {
  const from = $("#rbdFrom") ? $("#rbdFrom").value : "";
  const to = $("#rbdTo") ? $("#rbdTo").value : "";
  const s = state.acc.rbd;
  if (!from || !to) {
    s.error = "Choose both a From date and a To date before applying.";
    renderRbd();
    return;
  }
  if (from > to) {
    s.error = "The From date is after the To date.";
    renderRbd();
    return;
  }
  s.error = null; s.from = from; s.to = to;
  syncRbdInputs(from, to);
  loadReceivablesByDistributor();
}

function exportRbdCsv() {
  const d = state.acc.rbd.data;
  if (!d) {
    return toast({ok: false, status: "—",
      body: {detail: "Choose a window so the report is loaded before exporting it."}},
      "Nothing to export");
  }
  const rows = [["HERBANOVA receivables by distributor"], ["From", d.from], ["To", d.to],
    ["Distributor", "Code", "State", "Opening (INR)", "Invoiced (INR)",
     "Credit notes (INR)", "Debit notes (INR)", "Received (INR)", "Closing (INR)",
     "Overdue (INR)", "Invoices issued", "Open invoices", "Overdue invoices"]];
  (d.rows || []).forEach(x => rows.push([x.name, x.code || "", x.state || "",
    x.opening, x.invoiced, x.credited, x.debited, x.received, x.closing, x.overdue,
    x.invoices, x.open_invoices, x.overdue_invoices]));
  const t = d.totals || {};
  rows.push(["Total", "", "", t.opening, t.invoiced, t.credited, t.debited, t.received,
    t.closing, t.overdue, t.invoices, t.open_invoices, t.overdue_invoices]);
  rows.push([], ["Note", d.note || ""]);
  downloadCsv(`HERBANOVA_Receivables_by_distributor_${d.from}_${d.to}.csv`, rows);
}

function renderAccGaps(gaps) {
  const rows = gaps || [];
  $("#accGaps").innerHTML = rows.length
    ? `<ul class="gaps">${rows.map(g => `<li><b>${esc(g.code)}</b> ${esc(g.label)} <span>${esc(g.detail)}</span>`
        + (g.fix ? ` <a class="link-btn" href="${esc(g.fix)}">${esc(g.fix_label || "Fix this")}</a>` : "")
        + `</li>`).join("")}</ul>`
    : `<p class="muted">No gaps recorded.</p>`;
}

function renderAccountsCompare(cmp) {
  const d = cmp.data;
  if (!d) {
    $("#accCmp").innerHTML = `<p class="gap-note">${cmp.error ? esc(cmp.error) : "Loading comparison…"}</p>`;
    $("#accCmpNote").textContent = "";
    return;
  }
  $("#accCmpNote").textContent = `${CMP_MODES[d.mode]} · ${CMP_STATE[d.month_state]} · ${d.month_label}${cmp.loading ? " · refreshing…" : ""}`;
  const ranges = d.ranges;
  const rangeRow = `<div class="cmp-ranges">${cmpRange(`Selected · ${CMP_MODES[d.mode]}`, ranges.current, true)}`
    + `${cmpRange("Previous month", ranges.previous, false)}${cmpRange("Same month last year", ranges.last_year, false)}</div>`;
  const unit = m => v => m.unit === "amount" ? accMoney(v) : qty(v);
  const rows = (d.metrics || []).map(m => {
    if (!m.available) {
      const fix = m.fix ? ` <a class="link-btn" href="${esc(m.fix)}">Fix this</a>` : "";
      return `<tr><td class="strong">${esc(m.label)}</td><td colspan="5"><span class="chip off">Gap ${esc(m.gap || "")}</span> <span class="gap-note">No data yet. ${esc(m.note || "")}</span>${fix}</td></tr>`;
    }
    const f = unit(m);
    return `<tr><td class="strong">${esc(m.label)}</td><td class="n">${esc(f(m.current))}</td>`
      + `<td class="n">${esc(f(m.previous))}</td><td class="n">${cmpDelta(m.previous_change)}</td>`
      + `<td class="n">${esc(f(m.last_year))}</td><td class="n">${cmpDelta(m.last_year_change)}</td></tr>`;
  }).join("");
  $("#accCmp").innerHTML = rangeRow + `<div class="tw"><table>
      <thead><tr><th>Metric</th><th class="n">Selected window</th><th class="n">Previous month</th>`
    + `<th class="n">Change</th><th class="n">Same month last year</th><th class="n">Change</th></tr></thead>`
    + `<tbody>${rows}</tbody></table></div>`
    + `<p class="muted panel-note">Snapshot figures (receivables, payables) are as at each window's last day. A comparison against zero has no percentage.</p>`;
}

function setAccMode(mode) {
  if (!CMP_MODES[mode]) return;
  state.acc.cmp.mode = mode;
  loadAccountsCompare();
}
function setAccMonth(value) {
  state.acc.cmp.month = /^\d{4}-\d{2}$/.test(value || "") ? value : "";
  loadAccountsCompare();
}
function setAccStateFilter(value) {
  state.acc.state = /^\d{2}$/.test(value || "") ? value : "";
  loadAccountsReport();
}
function setAccWindow(from, to) {
  if (from) state.acc.from = from;
  if (to) state.acc.to = to;
  if (state.acc.from > state.acc.to) return;
  loadAccountsReport();
  loadAccountsCompare();
}

/* A KPI card carries its own window into the section that proves it. The
   parameter is applied after the section has rendered, so the visible filters
   and the report agree; nothing is guessed when a parameter is missing. */
function applyAccountsQuery(params) {
  if (!params || !params.size) return;
  const sec = state.acc.section;
  const from = params.get("from"), to = params.get("to");
  const asOf = params.get("as_of"), focus = params.get("focus");
  if (focus === "pnl") {
    const panel = $("#accPnlPanel");
    if (panel) {
      panel.scrollIntoView({behavior: "smooth", block: "start"});
      panel.classList.add("focus-flash");
      setTimeout(() => panel.classList.remove("focus-flash"), 1800);
    }
  }
  if (sec === "gst-out" && (from || to)) {
    if (from) $("#gstFrom").value = from;
    if (to) $("#gstTo").value = to;
    loadGstRegister();
  } else if (sec === "ageing" && asOf) {
    $("#ageAsOf").value = asOf;
    loadAgeing();
  } else if (sec === "receivables-by-distributor" && (from || to)) {
    state.acc.rbd.from = from || state.acc.rbd.from;
    state.acc.rbd.to = to || state.acc.rbd.to;
    syncRbdInputs(state.acc.rbd.from, state.acc.rbd.to);
    loadReceivablesByDistributor();
  } else if (sec === "cash" && (from || to)) {
    if (from) $("#enFrom").value = from;
    if (to) $("#enTo").value = to;
    loadEntriesWindow();
  }
}

function applyExpensesQuery(params) {
  if (!params || !params.size) return;
  const from = params.get("from"), to = params.get("to");
  if (from) $("#expFrom").value = from;
  if (to) $("#expTo").value = to;
  if (from || to) loadExpenses();
}

/* Receipts and payments can be narrowed to a window. Empty dates keep the
   previous all-time list, so opening the section directly changes nothing. */
async function loadEntriesWindow() {
  if (!can("accounts:read")) return;
  const from = $("#enFrom") ? $("#enFrom").value : "";
  const to = $("#enTo") ? $("#enTo").value : "";
  if (from && to && from > to) {
    return toast({ok: false, status: "—",
      body: {detail: "The start date is after the end date."}}, "Check the dates");
  }
  const p = new URLSearchParams();
  if (from) p.set("date_from", from);
  if (to) p.set("date_to", to);
  const res = await api(`/api/accounts/payments${p.toString() ? "?" + p : ""}`);
  if (!res.ok) return toast(res, "Entries could not be loaded");
  state.accounts.entries = res.body;
  renderAccounts();
}

/* The payables list behind the two payables cards. `due=week` narrows it to
   the same seven-day estimate the card uses; the full list is unchanged. */
function payablesForView() {
  const out = state.accounts.outstanding;
  if (!out) return null;
  const rows = out.payables.filter(p => Number(p.outstanding) > 0);
  if (state.acc.payDue !== "week") return rows;
  const today = isoDay(0);
  const end = isoDay(new Date(Date.now() + 7 * 86400000));
  return rows.filter(p => p.due_on && p.due_on >= today && p.due_on <= end);
}

function exportAccCsv() {
  const r = state.acc.report;
  if (!r) return;
  const rows = [["HERBANOVA accounts report"], ["From", r.from], ["To", r.to],
                ["Region", r.region ? r.region.label : "All states"], ["Metric", "Amount (INR)"]];
  (r.cards || []).forEach(c => rows.push([c.label,
    c.available === false ? `No data yet (${c.gap})` : c.value]));
  rows.push([], ["Profit and loss (statement)", "Amount (INR)"]);
  (r.profit_and_loss && r.profit_and_loss.rows || []).forEach(x => rows.push([x.label,
    x.available === false ? `No data yet (${x.gap})` : x.value]));
  rows.push(["Note", "GST is excluded from profit; non-creditable GST is part of an expense."], [],
    ["Month", "Revenue", "Collections", "Payments", "Net cash", "Output GST", "Returns"],
    ...(r.trend || []).map(m => [m.label, m.revenue, m.collections, m.payments, m.net_cash, m.output_gst, m.returns]),
    [], ["State", "Invoices", "Revenue", "Output GST", "Returns", "Outstanding"],
    ...(r.states || []).map(x => [x.name, x.invoices, x.revenue, x.output_gst, x.returns, x.outstanding]));
  downloadCsv(`HERBANOVA_Accounts_${r.from}_${r.to}.csv`, rows);
}

/* ---------- CSV exports for Accounts and FOC ----------
   Every export reads the same state the screen renders, so the file matches the
   displayed report and the filters that produced it. Amounts are written as
   plain decimals so a spreadsheet can add them; a total is the sum of the rows
   above it, never a second calculation the screen does not show. */
function csvNotLoaded(label) {
  toast({ok: false, status: "—",
    body: {detail: `Load ${label} before exporting it.`}}, "Nothing to export");
}
function csvSum(rows, pick) {
  const paise = rows.reduce((sum, row) => sum + Math.round(Number(pick(row) || 0) * 100), 0);
  return (paise / 100).toFixed(2);
}
function csvRange(from, to) {
  return [["From", from || "All dates"], ["To", to || "All dates"]];
}

function exportReceivablesCsv() {
  const out = state.accounts.outstanding;
  if (!out) return csvNotLoaded("the receivables list");
  const rows = out.receivables.filter(r => Number(r.outstanding) > 0);
  const csv = [["HERBANOVA receivables"], ["As at", isoDay(0)],
    ["Invoice", "Date", "Distributor", "Payment terms (days)", "Due date",
     "Value (INR)", "Adjusted by notes (INR)", "Received (INR)", "Outstanding (INR)"]];
  rows.forEach(r => csv.push([r.number, r.date, r.distributor || "",
    r.payment_terms_days ?? "", r.due_date || "", r.grand_total, r.adjusted ?? "0.00",
    r.received, r.outstanding]));
  csv.push(["Total", "", "", "", "", csvSum(rows, r => r.grand_total),
    csvSum(rows, r => r.adjusted), csvSum(rows, r => r.received),
    csvSum(rows, r => r.outstanding)]);
  csv.push([], ["Note", "Only invoices with an outstanding balance are listed."]);
  downloadCsv(`HERBANOVA_Receivables_${isoDay(0)}.csv`, csv);
}

function exportAgeingCsv() {
  const age = state.accounts.ageing;
  if (!age) return csvNotLoaded("the ageing report");
  const rows = [];
  age.buckets.forEach(b => b.rows.forEach(r => rows.push({...r, bucket: b.label})));
  const csv = [["HERBANOVA ageing of outstanding invoices"], ["As at", age.as_of],
    ["Invoice", "Date", "Distributor", "Days", "Bucket", "Due date",
     "Days overdue", "Outstanding (INR)"]];
  rows.forEach(r => csv.push([r.number, r.date, r.distributor || "", r.days, r.bucket,
    r.due_date || "No due date", r.days_overdue, r.outstanding]));
  age.buckets.forEach(b => csv.push([`Bucket total · ${b.label}`, "", "", "", "",
    "", `${b.count} invoices`, b.total]));
  csv.push(["Total", "", "", "", "", "", `${age.count} invoices`, age.total]);
  csv.push([], ["Due at the as-at day", "Invoices", "Outstanding (INR)"]);
  [["overdue", "Overdue"], ["due_this_week", "Due within 7 days"],
   ["not_yet_due", "Due later"], ["no_due_date", "No due date"]].forEach(([key, label]) => {
    const x = (age.due || {})[key] || {count: 0, total: "0.00"};
    csv.push([label, x.count, x.total]);
  });
  downloadCsv(`HERBANOVA_Ageing_${age.as_of}.csv`, csv);
}

function exportPayablesCsv() {
  const rows = payablesForView();
  if (!rows) return csvNotLoaded("the payables list");
  const weekly = state.acc.payDue === "week";
  const csv = [["HERBANOVA payables"], ["As at", isoDay(0)],
    ["Filter", weekly ? "Estimated to fall due within 7 days" : "All outstanding orders"],
    ["Purchase order", "Supplier", "Last received", "Payment terms (days)", "Due (estimated)",
     "Received value (INR)", "Paid (INR)", "Outstanding (INR)"]];
  rows.forEach(p => csv.push([p.number, p.supplier || "", p.received_on || "",
    p.terms_days ?? "", p.due_on || "",
    p.received_value, p.paid, p.outstanding]));
  csv.push(["Total", "", "", "", "", csvSum(rows, p => p.received_value),
    csvSum(rows, p => p.paid), csvSum(rows, p => p.outstanding)]);
  csv.push([], ["Note", weekly
    ? "Due dates are estimated from each supplier's current payment terms and the latest receipt."
    : "Only orders with an outstanding balance are listed; due dates are estimated from current terms."]);
  downloadCsv(`HERBANOVA_Payables_${isoDay(0)}.csv`, csv);
}

function exportEntriesCsv() {
  if (!state.accounts.outstanding) return csvNotLoaded("the receipts and payments list");
  const rows = state.accounts.entries || [];
  const csv = [["HERBANOVA receipts and payments"], ["As at", isoDay(0)],
    ["Entry", "Date", "Kind", "Purpose", "Party", "Against", "Allocated (INR)",
     "Advance (INR)", "Amount (INR)", "Mode", "Reference", "Notes"]];
  rows.forEach(e => {
    const against = (e.allocations || []).map(a =>
      `${a.number || "—"} ${a.amount}`).join("; ")
      || e.invoice_number || e.purchase_order_number || "Advance";
    csv.push([e.number, e.paid_on, e.kind === "receipt" ? "Receipt" : "Payment",
      e.purpose || "", e.party || "", against, e.allocated ?? "", e.advance ?? "",
      e.amount, e.mode, e.reference || "", e.notes || ""]);
  });
  const receipts = rows.filter(e => e.kind === "receipt");
  const payments = rows.filter(e => e.kind === "payment");
  csv.push(["Total receipts", "", "", "", "", "", csvSum(receipts, e => e.allocated),
    csvSum(receipts, e => e.advance), csvSum(receipts, e => e.amount), "", "", ""]);
  csv.push(["Total payments", "", "", "", "", "", csvSum(payments, e => e.allocated),
    csvSum(payments, e => e.advance), csvSum(payments, e => e.amount), "", "", ""]);
  csv.push(["Net receipts less payments", "", "", "", "", "", "", "",
    (Math.round((Number(csvSum(receipts, e => e.amount)) - Number(csvSum(payments, e => e.amount))) * 100) / 100).toFixed(2),
    "", "", ""]);
  csv.push([], ["Note", "An entry is never edited; a mistake is corrected by recording the opposite one."]);
  downloadCsv(`HERBANOVA_Receipts_and_payments_${isoDay(0)}.csv`, csv);
}

function exportGstRegisterCsv() {
  const reg = state.accounts.gst;
  if (!reg) return csvNotLoaded("the GST register");
  const cols = ["Document", "Date", "Buyer", "GSTIN", "Place of supply", "Supply kind",
    "Taxable (INR)", "CGST (INR)", "SGST (INR)", "IGST (INR)", "Cess (INR)", "Total (INR)"];
  const csv = [["HERBANOVA GST register · outward supplies"], ...csvRange(reg.from, reg.to),
    ["B2B invoices", ...cols.slice(1)]];
  (reg.b2b || []).forEach(r => csv.push([r.number, r.date, r.party || "", r.gstin || "",
    r.place_of_supply, r.kind || "", r.taxable, r.cgst, r.sgst, r.igst, r.cess, r.total]));
  csv.push([], ["Credit notes", ...cols.slice(1)]);
  (reg.credit_notes || []).forEach(r => csv.push([r.number, r.date, "", "", "", "",
    r.taxable, r.cgst, r.sgst, r.igst, r.cess, r.total]));
  csv.push([], ["Debit notes", ...cols.slice(1)]);
  (reg.debit_notes || []).forEach(r => csv.push([r.number, r.date, "", "", "", "",
    r.taxable, r.cgst, r.sgst, r.igst, r.cess, r.total]));
  const t = reg.totals || {};
  csv.push([], ["Total · invoices plus debit notes less credit notes", "", "", "", "", "",
    t.taxable, t.cgst, t.sgst, t.igst, t.cess, t.total]);
  csv.push(["Note", reg.note || ""]);
  const tag = `${reg.from || "all"}_${reg.to || "all"}`;
  downloadCsv(`HERBANOVA_GST_outward_${tag}.csv`, csv);
}

function exportInputGstCsv() {
  const reg = state.accounts.inputGst;
  if (!reg) return csvNotLoaded("the input register");
  const cols = ["Bill", "Date", "Supplier", "Supplier bill no.", "Taxable (INR)",
    "CGST (INR)", "SGST (INR)", "IGST (INR)", "Cess (INR)", "Round off (INR)",
    "Total (INR)", "ITC", "Status", "TDS section", "TDS rate", "TDS amount",
    "Reversal reason", "Note"];
  const csv = [["HERBANOVA input GST · supplier bills"], ...csvRange(reg.from, reg.to), cols];
  (reg.rows || []).forEach(r => csv.push([r.number, r.invoice_date, r.supplier || "",
    r.supplier_invoice_number, r.taxable, r.cgst, r.sgst, r.igst, r.cess, r.round_off,
    r.total, r.itc_eligible ? "Eligible" : "Blocked",
    r.status === "reversed" ? "Reversed" : "Posted", r.tds_section || "",
    r.tds_rate ?? "", r.tds_amount, r.reversal_reason || "", r.note || ""]));
  const totalsRow = (label, t) => ["", "", "", "", t.taxable, t.cgst, t.sgst, t.igst,
    t.cess, t.round_off, t.total, "", "", "", "", "", "", ""].map((v, i) => i === 0 ? label : v);
  csv.push(totalsRow("Total posted bills", reg.totals || {}));
  csv.push(totalsRow("Eligible ITC", reg.eligible || {}));
  csv.push(totalsRow("Blocked ITC", reg.blocked || {}));
  const net = state.accounts.netGst;
  csv.push([], ["Net GST payable", net && net.available ? net.net_total : "No data yet",
    net && net.available ? "" : (net ? net.reason : "The net GST figure could not be loaded.")]);
  if (net && net.available) {
    csv.push(["Output GST", net.output_total]);
    csv.push(["Eligible input", net.input_total]);
    csv.push(["Blocked input (not netted)", net.blocked_total]);
  }
  const tag = `${reg.from || "all"}_${reg.to || "all"}`;
  downloadCsv(`HERBANOVA_Input_GST_${tag}.csv`, csv);
}

function exportStatutoryCsv() {
  const dues = state.accounts.dues;
  if (!dues) return csvNotLoaded("TDS and statutory dues");
  const rows = dues.summary || [];
  const csv = [["HERBANOVA TDS and statutory dues"], ...csvRange(dues.from, dues.to),
    ["Head", "Withheld to date (INR)", "Deposited to date (INR)",
     "Deposited in window (INR)", "Outstanding (INR)", "State"]];
  rows.forEach(h => csv.push([h.label,
    h.withheld_to_date == null ? "No data yet" : h.withheld_to_date,
    h.deposited_to_date, h.deposited_in_window,
    h.outstanding == null ? "No data yet" : h.outstanding,
    h.reason || "Available"]));
  const available = rows.filter(h => h.withheld_to_date != null);
  csv.push(["Total (heads with data)", csvSum(available, h => h.withheld_to_date),
    csvSum(available, h => h.deposited_to_date),
    csvSum(available, h => h.deposited_in_window),
    csvSum(available, h => h.outstanding), `${available.length} of ${rows.length} heads`]);
  const challans = state.accounts.challans || [];
  csv.push([], ["Challans in the window"],
    ["Challan", "Head", "Paid on", "Period", "Section", "Amount (INR)", "BSR code", "Note"]);
  challans.forEach(c => csv.push([c.challan_number, c.label, c.paid_on,
    `${MONTHS[c.period_month - 1]} ${c.period_year}`, c.section || "", c.amount,
    c.bsr_code || "", c.note || ""]));
  csv.push(["Total challans", "", "", "", "", csvSum(challans, c => c.amount), "", ""]);
  if (dues.vendor_tds && dues.vendor_tds.count) {
    csv.push([], ["Vendor TDS", dues.vendor_tds.total,
      `${dues.vendor_tds.count} source bill(s)`]);
  }
  downloadCsv(`HERBANOVA_Statutory_dues_${dues.from}_${dues.to}.csv`, csv);
}

function exportTrialBalanceCsv() {
  const tb = state.accounts.tb;
  if (!tb) return csvNotLoaded("the trial balance");
  const csv = [["HERBANOVA trial balance"], ["As at", tb.as_of || isoDay(0)],
    ["Account", "Debit (INR)", "Credit (INR)"]];
  (tb.rows || []).forEach(r => csv.push([r.account,
    Number(r.debit) ? r.debit : "", Number(r.credit) ? r.credit : ""]));
  csv.push(["Total", tb.debit_total, tb.credit_total]);
  const diff = Math.round((Number(tb.debit_total) - Number(tb.credit_total)) * 100) / 100;
  csv.push(["Debit less credit", diff.toFixed(2), ""],
    ["State", tb.balanced ? "Balanced" : "Difference reported", ""]);
  downloadCsv(`HERBANOVA_Trial_balance_${tb.as_of || isoDay(0)}.csv`, csv);
}

function exportLedgerHeadsCsv() {
  const heads = lgState().heads;
  if (!heads) return csvNotLoaded("the ledger heads");
  const csv = [["HERBANOVA ledger heads"], ["As at", isoDay(0)],
    ["Code", "Head", "Type", "Role", "State", "Note"]];
  heads.forEach(h => csv.push([h.code, h.name, LEDGER_TYPE_LABEL[h.type] || h.type,
    h.role || "unlinked", h.active ? "Active" : "Inactive", h.note || ""]));
  const active = heads.filter(h => h.active).length;
  csv.push([], ["Active heads", active], ["Inactive heads", heads.length - active],
    ["All heads", heads.length]);
  downloadCsv(`HERBANOVA_Ledger_heads_${isoDay(0)}.csv`, csv);
}

function exportOpeningsCsv() {
  const ob = lgState().openings;
  if (!ob) return csvNotLoaded("the opening balances");
  const csv = [["HERBANOVA opening balances"], ["Financial year", ob.financial_year],
    ["Code", "Head", "Type", "Debit (INR)", "Credit (INR)", "Note"]];
  (ob.rows || []).forEach(r => csv.push([r.code, r.name,
    LEDGER_TYPE_LABEL[r.type] || r.type, Number(r.debit) ? r.debit : "",
    Number(r.credit) ? r.credit : "", r.note || ""]));
  csv.push(["Total", "", "", ob.debit_total, ob.credit_total, ""]);
  csv.push([], ["Balance check", ob.balanced ? "Balanced" : `Difference ${ob.difference}`]);
  downloadCsv(`HERBANOVA_Opening_balances_${ob.financial_year}.csv`, csv);
}

function exportBalanceSheetCsv() {
  const sheet = lgState().sheet;
  if (!sheet) return csvNotLoaded("the balance sheet");
  const csv = [["HERBANOVA balance sheet"], ["As at", sheet.as_of],
    ["Section", "Account", "Opening (INR)", "Vouchers (INR)", "Documents (INR)",
     "Balance (INR)", "Unlinked"]];
  BS_SECTIONS.forEach(([key, label]) => {
    const rows = (sheet.sections || {})[key] || [];
    if (!rows.length) return;
    csv.push([label]);
    rows.forEach(r => csv.push([label, r.code ? `${r.code} · ${r.name}` : r.name,
      r.opening, r.vouchers, r.documents, r.balance, r.unmapped ? "Yes" : "No"]));
  });
  const t = sheet.totals || {};
  csv.push([], ["Totals"], ["Total assets", "", "", "", "", t.asset, ""],
    ["Total liabilities", "", "", "", "", t.liability, ""],
    ["Total equity", "", "", "", "", t.equity, ""],
    ["Retained earnings", "", "", "", "", t.retained_earnings, ""],
    ["Difference", "", "", "", "", t.difference, ""],
    ["State", t.balanced ? "Balanced" : "Difference reported", "", "", "", "", ""]);
  const cb = sheet.cash_bank || {rows: [], total: 0};
  csv.push([], ["Cash and bank closing"],
    ["Account", "Balance (INR)"]);
  (cb.rows || []).forEach(r => csv.push([r.code ? `${r.code} · ${r.name}` : r.name, r.balance]));
  csv.push(["Cash and bank total", cb.total]);
  const opening = sheet.opening || {};
  csv.push([], ["Opening balances", sheet.opening_fy || "not captured"],
    ["Opening debit", opening.debit_total], ["Opening credit", opening.credit_total],
    ["Opening state", opening.balanced ? "Balanced" : `Difference ${opening.difference}`]);
  if ((sheet.warnings || []).length) {
    csv.push([], ["What this sheet does not claim"]);
    sheet.warnings.forEach(w => csv.push([w]));
  }
  downloadCsv(`HERBANOVA_Balance_sheet_${sheet.as_of}.csv`, csv);
}

function exportVouchersCsv() {
  const rows = lgState().vouchers;
  if (!rows) return csvNotLoaded("the vouchers");
  const f = lgState().voucherFilters || {};
  const csv = [["HERBANOVA vouchers and journal"],
    ...csvRange(f.from, f.to),
    ["Status", f.status || "All states"],
    ["Number", "Date", "Type", "Narration", "Debit (INR)", "Credit (INR)", "State",
     "Mirror of", "Reversal reason"]];
  rows.forEach(v => csv.push([v.number, v.date, VOUCHER_TYPE_LABEL[v.type] || v.type,
    v.narration || "", v.debit, v.credit, VOUCHER_STATE_LABEL[v.status] || v.status,
    v.reverse_of || "", v.reversal_reason || ""]));
  csv.push(["Total", "", "", "", csvSum(rows, v => v.debit), csvSum(rows, v => v.credit), "", "", ""]);
  csv.push(["Note", "A draft is not in the books; a posted voucher is corrected by a reversing mirror."]);
  downloadCsv("HERBANOVA_Vouchers.csv", csv);
}

function exportDayBookCsv() {
  const book = lgState().daybook;
  if (!book) return csvNotLoaded("the day book");
  const csv = [["HERBANOVA day book"], ...csvRange(book.date_from, book.date_to),
    ["Date", "Number", "Type", "Narration", "Debit (INR)", "Credit (INR)", "State", "Mirror of"]];
  (book.rows || []).forEach(v => csv.push([v.date, v.number,
    VOUCHER_TYPE_LABEL[v.type] || v.type, v.narration || "", v.debit, v.credit,
    VOUCHER_STATE_LABEL[v.status] || v.status, v.reverse_of || ""]));
  csv.push(["Total", "", "", "", book.debit_total, book.credit_total, "", ""]);
  csv.push([], ["Vouchers", book.count],
    ["Balance", book.balanced ? "Balanced" : "Difference reported"]);
  downloadCsv(`HERBANOVA_Day_book_${book.date_from}_${book.date_to}.csv`, csv);
}

function exportBankCsv() {
  const lg = lgState();
  const statements = lg.statements;
  if (!statements) return csvNotLoaded("the bank statements");
  const csv = [["HERBANOVA bank reconciliation"], ["As at", isoDay(0)],
    ["Bank statements"],
    ["Bank head", "Period from", "Period to", "Opening (INR)", "Closing (INR)",
     "Lines", "Matched", "Note"]];
  statements.forEach(s => csv.push([s.account || "", s.period_from, s.period_to,
    s.opening_balance, s.closing_balance, s.lines, `${s.matched} of ${s.lines}`,
    s.note || ""]));
  const d = lg.detail, rec = lg.rec;
  if (d && rec) {
    csv.push([], ["Selected statement"], ["Bank head", d.account || ""],
      ["Period", `${d.period_from} to ${d.period_to}`],
      ["Printed opening (INR)", d.opening_balance],
      ["Printed closing (INR)", d.closing_balance]);
    csv.push([], ["Statement lines"], ["Date", "Description", "Reference",
      "Amount (INR)", "State"]);
    if (!(d.lines || []).length) csv.push(["No statement line is captured."]);
    (d.lines || []).forEach(line => csv.push([line.date, line.description,
      line.reference || "", line.amount, line.matched ? "Matched" : "Unmatched"]));
    const p = rec.proof || {};
    csv.push([], ["Reconciliation proof"], ["Check", "Amount (INR)"],
      ["Book closing balance", p.book_closing],
      ["Less unmatched book entries", p.unmatched_book_net],
      ["Adjusted book balance", p.adjusted_book],
      ["Statement closing balance", p.statement_closing],
      ["Less unmatched statement lines", p.unmatched_statement_net],
      ["Adjusted statement balance", p.adjusted_statement],
      ["Difference", p.difference],
      ["State", p.balanced ? "Balanced" : "Open"],
      ["Opening difference", p.opening_difference],
      ["Lines check", p.lines_check],
      ["Matched lines", rec.matched ? rec.matched.count : ""],
      ["Matched debit (INR)", rec.matched ? rec.matched.debit : ""],
      ["Matched credit (INR)", rec.matched ? rec.matched.credit : ""]);
    const book = rec.unmatched_book;
    const bookRows = book ? [
      ...(book.receipts || []).map(x => ["Receipt", x.party || "", x.date, x.amount,
        `${x.mode || ""} ${x.reference || ""}`.trim()]),
      ...(book.payments || []).map(x => ["Payment", x.party || "", x.date,
        -Math.abs(Number(x.amount)), `${x.mode || ""} ${x.reference || ""}`.trim()]),
      ...(book.vouchers || []).map(x => ["Voucher", x.voucher || "", x.date, x.amount,
        x.narration || ""]),
    ] : [];
    csv.push([], ["Unmatched in the books"], ["Kind", "Entry", "Date", "Amount (INR)", "Reference"]);
    if (!bookRows.length)
      csv.push(["Every book entry inside this statement is matched, or none is in reach."]);
    bookRows.forEach(r => csv.push(r));
    csv.push([], ["Warnings"]);
    if (!(rec.warnings || []).length)
      csv.push(["No warning is raised for this statement."]);
    (rec.warnings || []).forEach(w => csv.push([w]));
  }
  downloadCsv(`HERBANOVA_Bank_reconciliation_${isoDay(0)}.csv`, csv);
}

function exportYearsCsv() {
  const fy = state.accounts.years;
  if (!fy) return csvNotLoaded("the financial years");
  const csv = [["HERBANOVA financial years"], ["Current year", fy.current],
    ["Financial year", "From", "To", "State", "Closed by", "Closed at", "Reason",
     "Reopened by", "Reopened at", "Reopen reason"]];
  (fy.years || []).forEach(y => csv.push([y.financial_year, y.first, y.last,
    y.active ? "Closed" : (y.reopened_at ? "Open (reopened)" : "Open"),
    y.closed_by || "", y.closed_at || "", y.reason || "", y.reopened_by || "",
    y.reopened_at || "", y.reopen_reason || ""]));
  csv.push([], ["Note", "Only completed years can be closed; the Administrator reopens one."]);
  downloadCsv(`HERBANOVA_Financial_years.csv`, csv);
}

function exportLocksCsv() {
  if (!state.accounts.years && !(state.accounts.locks || []).length)
    return csvNotLoaded("the accounting month locks");
  const locks = state.accounts.locks || [];
  const csv = [["HERBANOVA accounting month locks"], ["As at", isoDay(0)],
    ["Month", "Year", "Period", "State", "Reason", "Locked by", "Locked at",
     "Unlocked by", "Unlocked at", "Unlock reason"]];
  locks.forEach(l => csv.push([MONTHS[l.month - 1], l.year, `${MONTHS[l.month - 1]} ${l.year}`,
    l.active ? "Locked" : "Open", l.reason || "", l.locked_by || "", l.locked_at || "",
    l.unlocked_by || "", l.unlocked_at || "", l.unlock_reason || ""]));
  const active = locks.filter(l => l.active).length;
  csv.push([], ["Locked months", active], ["Open records", locks.length - active]);
  downloadCsv(`HERBANOVA_Accounting_month_locks_${isoDay(0)}.csv`, csv);
}

/* ---------- expenses ---------- */
const EXP_STATUS = {pending_approval: "Waiting approval", approved: "Approved",
                    rejected: "Rejected", reversed: "Reversed"};
const EXP_MODES = ["cash", "bank", "upi", "cheque", "neft", "other"];

function openExpenses() {
  if (!can("expense:read")) return;
  renderExpenses();
  if (!state.exp.loaded && !state.exp.loading) loadExpenses();
}

async function loadExpenses() {
  if (!can("expense:read")) return;
  const s = state.exp, seq = ++s.seq;
  s.loading = true; s.error = null;
  renderExpenses();
  const params = new URLSearchParams();
  if (s.status) params.set("status", s.status);
  if (s.head) params.set("head_id", s.head);
  if (s.q) params.set("q", s.q);
  const from = $("#expFrom") ? $("#expFrom").value : "";
  const to = $("#expTo") ? $("#expTo").value : "";
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const [rows, heads, settings] = await Promise.all([
    api(`/api/expenses?${params.toString()}`),
    api("/api/expenses/heads"),
    api("/api/expenses/settings"),
  ]);
  if (seq !== s.seq || !state.user) return;
  s.loading = false;
  if (rows.ok && Array.isArray(rows.body)) s.rows = rows.body;
  else s.error = detail(rows.body);
  if (heads.ok && Array.isArray(heads.body)) s.heads = heads.body;
  if (settings.ok && settings.body && !Array.isArray(settings.body)) s.settings = settings.body;
  s.loaded = true;
  renderExpenses();
}

function renderExpenses() {
  const s = state.exp, panel = $("#expPanel");
  if (!panel || !state.user) return;
  panel.classList.toggle("hide", !can("expense:read"));
  $("#expNewBtn").classList.toggle("hide", !can("expense:write"));
  $("#expHeadsBtn").classList.toggle("hide", !can("expense:write"));
  $("#expSettingsBtn").classList.toggle("hide", state.user.role !== "admin");
  const st = s.settings;
  $("#expSettingsNote").textContent = st
    ? `Tracked from ${fmtDate(st.tracked_from)} · approval ${st.approval_enabled ? `on above ₹ ${money(st.approval_threshold)}` : "off"}`
    : s.loading ? "Loading settings…" : "";
  $("#expErr").classList.toggle("hide", !s.error);
  $("#expErr").textContent = s.error || "";

  const headEl = $("#expHead");
  if (headEl && document.activeElement !== headEl) {
    headEl.innerHTML = `<option value="">All heads</option>` + s.heads.map(h =>
      `<option value="${h.id}"${String(h.id) === String(s.head) ? " selected" : ""}>${esc(h.name)}</option>`).join("");
  }
  $$("[data-exp-status]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.expStatus === s.status)));

  const rows = s.rows || [];
  const writable = can("expense:write");
  $("#expRows").innerHTML = rows.map(x => {
    const acts = [];
    if (x.attachment) acts.push(`<a class="rowbtn" href="${esc(x.attachment_url)}">Receipt</a>`);
    if (writable && ["approved", "pending_approval"].includes(x.status)) {
      acts.push(`<button class="rowbtn" type="button" data-act="exp-receipt" data-id="${x.id}">Upload</button>`);
    }
    if (writable && x.status === "approved") {
      acts.push(`<button class="rowbtn" type="button" data-act="exp-reverse" data-id="${x.id}">Reverse</button>`);
    }
    if (x.status === "pending_approval" && can("approval:read")) {
      acts.push(`<a class="rowbtn" href="#/approvals">Approve</a>`);
    }
    return `<tr><td class="strong">${esc(x.number)}</td><td>${esc(fmtDate(x.entry_date))}</td>`
      + `<td>${esc(x.head)}</td><td class="n">${esc(money(x.amount))}</td>`
      + `<td class="n">${esc(money(x.gst_amount))}${x.gst_creditable ? "" : ' <span class="chip off">Not creditable</span>'}</td>`
      + `<td class="n strong">${esc(money(x.deductible_amount))}</td>`
      + `<td><span class="pill">${esc(EXP_STATUS[x.status] || x.status)}</span>`
      + (x.reversal_reason ? `<small>${esc(x.reversal_reason)}</small>` : "") + `</td>`
      + `<td>${esc(x.mode)}</td><td>${esc(x.note || x.reference || "")}</td>`
      + `<td class="rowacts">${acts.join(" ") || "–"}</td></tr>`;
  }).join("");
  $("#expEmpty").classList.toggle("hide", rows.length > 0);
  $("#expEmpty").textContent = s.loading ? "Loading expenses…"
    : s.loaded && !rows.length ? "No expense matches this filter." : "";
  const deductible = rows.filter(x => x.status === "approved")
    .reduce((sum, x) => sum + Number(x.deductible_amount || 0), 0);
  $("#expTot").textContent = rows.length
    ? `${plural(rows.length, "entry")} · ₹ ${money(deductible)} carried by approved entries shown` : "";
}

function openExpenseForm() {
  if (!can("expense:write")) return;
  const heads = state.exp.heads.filter(h => h.is_active && !h.is_system);
  if (!heads.length) {
    openDrawer("New expense",
      "Add an expense head first; the payroll head is filled from HR.", `
      <p class="gap-note">No expense head is available. Open <b>Expense heads</b> and add one.</p>
      <div class="actions"><button class="btn" type="button" data-act="exp-heads">Expense heads</button>
      <button class="btn ghost" type="button" data-act="close">Close</button></div>`);
    return;
  }
  openDrawer("New expense",
    "An expense is never edited. A mistake is reversed with a reason.", `
    <form id="expForm" autocomplete="off">
      <div class="row2">
        <div><label for="x-head">Expense head</label><select id="x-head" name="head_id">
          ${heads.map(h => `<option value="${h.id}">${esc(h.name)}</option>`).join("")}
        </select></div>
        <div><label for="x-date">Date</label><input id="x-date" name="entry_date" type="date" value="${dayIso(new Date())}" max="${dayIso(new Date())}" required></div>
      </div>
      <div class="row2">
        <div><label for="x-amount">Amount before GST (₹)</label><input id="x-amount" name="amount" inputmode="decimal" required autocomplete="off"></div>
        <div><label for="x-gst">GST (₹)</label><input id="x-gst" name="gst_amount" inputmode="decimal" value="0" autocomplete="off"></div>
      </div>
      <div class="row2">
        <div><label for="x-mode">Paid by</label><select id="x-mode" name="mode">
          ${EXP_MODES.map(m => `<option value="${m}"${m === "bank" ? " selected" : ""}>${m}</option>`).join("")}
        </select></div>
        <div><label for="x-ref">Reference (optional)</label><input id="x-ref" name="reference" maxlength="60" autocomplete="off"></div>
      </div>
      <label>GST that can be claimed as input credit
        <input type="checkbox" name="gst_creditable" checked> Creditable
      </label>
      <label for="x-note">Note (optional)</label><input id="x-note" name="note" maxlength="300" autocomplete="off">
      <label for="x-file">Receipt (JPEG, PNG, WebP or PDF, 5 MB)</label><input id="x-file" name="receipt" type="file" accept="image/jpeg,image/png,image/webp,application/pdf">
      <div class="note">GST that is not creditable becomes part of the expense in the profit and loss. Creditable GST never does.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save expense</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

async function saveExpense(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = ""; btn.disabled = true;
  const f = form.elements;
  const body = {head_id: Number(f.head_id.value), entry_date: f.entry_date.value,
                amount: f.amount.value.trim(), gst_amount: f.gst_amount.value.trim() || "0",
                gst_creditable: f.gst_creditable.checked, mode: f.mode.value};
  if (f.reference.value.trim()) body.reference = f.reference.value.trim();
  if (f.note.value.trim()) body.note = f.note.value.trim();
  const res = await api("/api/expenses", {method: "POST", body});
  if (!res.ok) {
    btn.disabled = false; err.textContent = detail(res.body);
    return;
  }
  const file = f.receipt.files && f.receipt.files[0];
  if (file) {
    const up = await uploadExpenseReceipt(res.body.id, file);
    if (!up.ok) toast(up, "Expense saved but the receipt was not uploaded");
  }
  btn.disabled = false;
  toast(res, res.body.status === "pending_approval"
    ? "Expense saved and sent for approval" : "Expense saved");
  closeDrawer(); loadExpenses(); loadDashboard();
}

async function uploadExpenseReceipt(id, file) {
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch(`/api/expenses/${id}/attachment`,
      {method: "POST", credentials: "same-origin", body: fd});
    let body = null;
    try { body = await res.json(); } catch (e) { /* empty */ }
    return {status: res.status, ok: res.ok, body};
  } catch (e) {
    return {status: 0, ok: false, body: {detail: "Cannot reach the server."}};
  }
}

function expenseReceiptForm(id) {
  if (!can("expense:write")) return;
  const x = (state.exp.rows || []).find(r => r.id === Number(id));
  if (!x) return;
  openDrawer(`Receipt · ${x.number}`, "The file is private and served only to a signed-in role.",
    `<form id="expReceiptForm" data-id="${x.id}">
      <label for="xr-file">Receipt (JPEG, PNG, WebP or PDF, 5 MB)</label>
      <input id="xr-file" name="receipt" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" required>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Upload</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveExpenseReceipt(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  const file = form.elements.receipt.files && form.elements.receipt.files[0];
  if (!file) { err.textContent = "Choose a file first."; return; }
  btn.disabled = true;
  const res = await uploadExpenseReceipt(form.dataset.id, file);
  btn.disabled = false;
  toast(res, res.ok ? "Receipt uploaded" : "Receipt not uploaded");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadExpenses();
}

function expenseReverseForm(id) {
  if (!can("expense:write")) return;
  const x = (state.exp.rows || []).find(r => r.id === Number(id));
  if (!x) return;
  openDrawer(`Reverse ${x.number}`,
    "The entry keeps its amount and stays on file; the profit and loss stops counting it.", `
    <form id="expReverseForm" data-id="${x.id}">
      <p>${esc(x.head)} · ${esc(fmtDate(x.entry_date))} · ₹ ${esc(money(x.amount))}</p>
      <label for="xr-reason">Reason</label><input id="xr-reason" name="reason" maxlength="300" required autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Reverse expense</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveExpenseReverse(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  const reason = form.elements.reason.value.trim();
  if (reason.length < 3) { err.textContent = "Give a reason of at least three characters."; return; }
  btn.disabled = true;
  const res = await api(`/api/expenses/${form.dataset.id}/reverse`, {method: "POST", body: {reason}});
  btn.disabled = false;
  toast(res, res.ok ? "Expense reversed" : "Not reversed");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadExpenses(); loadDashboard();
}

function openExpenseHeads() {
  if (!can("expense:write")) return;
  const rows = state.exp.heads || [];
  openDrawer("Expense heads", "The payroll head is created by HR and cannot be edited here.", `
    <form id="expHeadForm" autocomplete="off">
      <label for="xh-name">New head</label>
      <div class="toolbar"><input id="xh-name" name="name" maxlength="80" required autocomplete="off">
      <button class="btn" type="submit">Add head</button></div>
      <div class="err" role="alert"></div>
    </form>
    <div class="tw"><table><thead><tr><th>Head</th><th>Status</th><th></th></tr></thead><tbody>
      ${rows.map(h => `<tr><td class="strong">${esc(h.name)}${h.is_system ? ' <span class="chip">Payroll</span>' : ""}</td>`
        + `<td>${h.is_active ? "Active" : "Inactive"}</td><td>${h.is_system ? "–"
          : `<button class="rowbtn" type="button" data-act="exp-head-toggle" data-id="${h.id}" data-on="${h.is_active ? "0" : "1"}">${h.is_active ? "Deactivate" : "Activate"}</button>`}</td></tr>`).join("")}
    </tbody></table></div>`, true);
}

async function saveExpenseHead(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  const name = form.elements.name.value.trim();
  if (name.length < 2) { err.textContent = "The name needs at least two characters."; return; }
  btn.disabled = true;
  const res = await api("/api/expenses/heads", {method: "POST", body: {name}});
  btn.disabled = false;
  toast(res, res.ok ? "Head added" : "Head not added");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  const r2 = await api("/api/expenses/heads");
  if (r2.ok) state.exp.heads = r2.body;
  openExpenseHeads(); renderExpenses();
}

async function toggleExpenseHead(id, on) {
  const res = await api(`/api/expenses/heads/${id}`, {method: "PATCH", body: {is_active: on}});
  toast(res, res.ok ? "Head changed" : "Head not changed");
  if (!res.ok) return;
  const r2 = await api("/api/expenses/heads");
  if (r2.ok) state.exp.heads = r2.body;
  openExpenseHeads(); renderExpenses(); loadExpenses();
}

function openExpenseSettings() {
  if (state.user.role !== "admin") return;
  const st = state.exp.settings;
  if (!st) return;
  openDrawer("Expense settings",
    "Only the Administrator can change the approval rule or the tracking start.", `
    <form id="expSettingsForm" autocomplete="off">
      <label>Approval threshold
        <input type="checkbox" name="approval_enabled"${st.approval_enabled ? " checked" : ""}> Ask for approval above the amount
      </label>
      <label for="xs-threshold">Approval amount (₹)</label>
      <input id="xs-threshold" name="approval_threshold" inputmode="decimal" value="${esc(st.approval_threshold)}">
      <label for="xs-from">Track expenses from</label>
      <input id="xs-from" name="tracked_from" type="date" value="${esc(st.tracked_from)}" max="${dayIso(new Date())}">
      <div class="note">A window that starts before this date reports expenses as a gap, not as zero.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save settings</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveExpenseSettings(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = ""; btn.disabled = true;
  const f = form.elements;
  const res = await api("/api/expenses/settings", {method: "PUT", body: {
    approval_enabled: f.approval_enabled.checked,
    approval_threshold: f.approval_threshold.value.trim() || "0",
    tracked_from: f.tracked_from.value,
  }});
  btn.disabled = false;
  toast(res, res.ok ? "Settings saved" : "Settings not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadExpenses(); loadDashboard();
}

function setExpenseStatus(status) {
  state.exp.status = ["approved", "pending_approval", "rejected", "reversed"].includes(status) ? status : "";
  loadExpenses();
}
function setExpenseHead(value) {
  state.exp.head = /^\d+$/.test(value || "") ? value : "";
  loadExpenses();
}

async function openDistributorLedger(id) {
  const res = await api(`/api/accounts/ledger/distributors/${encodeURIComponent(id)}`);
  if (!res.ok) return toast(res, "Ledger could not be loaded");
  const l = res.body;
  const rows = (l.entries || []).map(e => `<tr><td>${esc(e.date)}</td><td class="strong">${esc(e.document)}</td>`
    + `<td>${esc(e.kind.replace(/_/g, " "))}</td><td class="n">${Number(e.debit) ? money(e.debit) : ""}</td>`
    + `<td class="n">${Number(e.credit) ? money(e.credit) : ""}</td><td class="n">${money(e.balance)}</td>`
    + `<td>${esc(e.note || "")}</td></tr>`).join("");
  openDrawer(`Ledger: ${l.party}`, `${plural((l.entries || []).length, "entry")} · a document is never edited`, `
    <div class="tw"><table>
      <thead><tr><th>Date</th><th>Document</th><th>Kind</th><th class="n">Debit (₹)</th><th class="n">Credit (₹)</th><th class="n">Balance (₹)</th><th>Note</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="7"><span class="gap-note">No entries yet.</span></td></tr>`}</tbody>
    </table></div>
    <p class="closing">Closing balance <b>₹ ${money(l.closing_balance)}</b></p>`, true);
}

function entryForm(kind) {
  const out = state.accounts.outstanding;
  const receipt = kind === "receipt";
  const parties = receipt
    ? activeDists().map(d => `<option value="${d.id}">${esc(d.name)}${d.code ? ` (${esc(d.code)})` : ""}</option>`).join("")
    : activeSuppliers().map(s => `<option value="${s.id}">${esc(s.name)}${s.code ? ` (${esc(s.code)})` : ""}</option>`).join("");
  const options = receipt
    ? (out ? out.receivables.filter(r => Number(r.outstanding) > 0) : []).map(r =>
        `<option value="${r.invoice_id}" data-party="${r.distributor_id}">${esc(r.number)}, ${esc(r.distributor || "")}, ${money(r.outstanding)} due</option>`).join("")
    : (out ? out.payables.filter(p => Number(p.outstanding) > 0) : []).map(p =>
        `<option value="${p.purchase_order_id}" data-party="${p.supplier_id}">${esc(p.number)}, ${esc(p.supplier || "")}, ${money(p.outstanding)} due</option>`).join("");
  openDrawer(receipt ? "Record a receipt" : "Record a payment",
    receipt ? "Money received from a distributor: settle what is open, or hold the whole amount as an advance."
            : "Money paid to a supplier: settle received bills, or hold the whole amount as an advance.", `
    <form id="entryForm" data-kind="${kind}" novalidate>
      <label for="e-party">${receipt ? "Distributor" : "Supplier"}</label>
      <select id="e-party" name="party" required><option value="">Choose a ${receipt ? "distributor" : "supplier"}</option>${parties}</select>
      <label for="e-purpose">Record as</label>
      <select id="e-purpose" name="purpose">
        <option value="outstanding" selected>Existing outstanding ${receipt ? "invoice" : "bill"}</option>
        <option value="advance">Advance / new payment</option>
      </select>
      <label for="e-against" id="e-againstLabel">Settle this ${receipt ? "invoice" : "order"} first (optional)</label>
      <select id="e-against" name="against"><option value="">Oldest open ${receipt ? "invoices" : "bills"} first</option>${options}</select>
      <div class="note" id="e-advanceHint">Choose a party to see any advance already available.</div>
      <div class="row2"><div><label for="e-amount">Amount (₹)</label><input id="e-amount" name="amount" inputmode="decimal" placeholder="0.00" autocomplete="off"></div>
      <div><label for="e-date">Date</label><input id="e-date" name="paid_on" type="date" value="${isoDay(0)}"></div></div>
      <div class="row2"><div><label for="e-mode">Mode</label><select id="e-mode" name="mode">
        ${["bank", "cash", "upi", "cheque", "neft", "other"].map(m => `<option value="${m}"${m === "bank" ? " selected" : ""}>${m.toUpperCase()}</option>`).join("")}</select></div>
      <div><label for="e-ref">Reference</label><input id="e-ref" name="reference" placeholder="UTR, cheque number" autocomplete="off"></div></div>
      <label for="e-notes">Note</label><input id="e-notes" name="notes" placeholder="Optional" autocomplete="off">
      <div class="note">An entry is never edited or deleted. If it is wrong, record the opposite one and note why. An advance is not revenue or a purchase; it settles a later document automatically.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save ${receipt ? "receipt" : "payment"}</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

function syncEntryAgainst() {
  const form = $("#entryForm");
  if (!form) return;
  const receipt = form.dataset.kind === "receipt";
  const party = $("#e-party").value;
  const purpose = $("#e-purpose").value;
  const standing = purpose === "outstanding";
  const against = $("#e-against");
  $("#e-againstLabel").classList.toggle("hide", !standing);
  against.classList.toggle("hide", !standing);
  if (!standing) against.value = "";
  Array.from(against.options).forEach(o => {
    if (o.value) o.hidden = !!party && o.dataset.party !== party;
  });
  if (against.selectedOptions[0] && against.selectedOptions[0].hidden) against.value = "";
  const hint = $("#e-advanceHint");
  hint.textContent = party ? "Checking the advance balance…" : "Choose a party to see any advance already available.";
  if (!party) return;
  const kind = receipt ? "receipt" : "payment";
  api(`/api/accounts/advances?kind=${kind}&party_id=${encodeURIComponent(party)}`).then(res => {
    if (!res.ok || !res.body || Array.isArray(res.body) || !$("#e-advanceHint")) return;
    const available = Number(res.body.available || 0);
    $("#e-advanceHint").textContent = available > 0
      ? `Available advance: ₹ ${money(available)}. A later ${receipt ? "invoice" : "bill"} for this party draws it down automatically.`
      : "No advance is available for this party.";
  });
}

async function saveEntry(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form); err.textContent = "";
  const f = form.elements, kind = form.dataset.kind, receipt = kind === "receipt";
  if (!f.party.value) { err.textContent = `Choose a ${receipt ? "distributor" : "supplier"}.`; return; }
  if (!(Number(f.amount.value) > 0)) { err.textContent = "Enter an amount greater than zero."; return; }
  if (!f.paid_on.value) { err.textContent = "Choose the date the money moved."; return; }
  const purpose = f.purpose.value;
  const body = {kind, purpose, amount: f.amount.value, paid_on: f.paid_on.value, mode: f.mode.value,
                reference: f.reference.value.trim() || null, notes: f.notes.value.trim() || null};
  body[receipt ? "distributor_id" : "supplier_id"] = Number(f.party.value);
  if (purpose === "outstanding" && f.against.value)
    body[receipt ? "invoice_id" : "purchase_order_id"] = Number(f.against.value);
  btn.disabled = true;
  const res = await api("/api/accounts/payments", {method: "POST", body});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); toast(res, "Not recorded"); return; }
  const b = res.body, applied = (b.allocations || []).length;
  let label = `${receipt ? "Receipt" : "Payment"} ${b.number}: ₹ ${money(b.amount)} recorded`;
  if (applied) label += `, ₹ ${money(b.allocated)} settled against ${plural(applied, receipt ? "invoice" : "order")}`;
  if (Number(b.advance) > 0) label += `, ₹ ${money(b.advance)} held as advance`;
  toast(res, label);
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
  const s = listState("customers");
  const q = ($("#cuq")?.value || "").trim().toLowerCase();
  const filter = state.distFilter;
  const sel = $("#cuFilter");
  if (sel && sel.value !== filter) sel.value = filter;
  const list = s.loaded ? s.rows : state.dists.filter(d => {
    const wanted = filter === "all" || (filter === "incomplete" ? d.needs_completion : d.status === filter);
    if (!wanted) return false;
    return !q || [d.code, d.name, d.gstin, d.territory].some(x => (x || "").toLowerCase().includes(q));
  });
  const total = s.loaded ? s.total : state.dists.length;
  $("#curows").innerHTML = list.map(d => {
    const lim = Number(d.credit_limit), use = Number(d.exposure);
    const pct = lim > 0 ? Math.min(100, use / lim * 100) : (use > 0 ? 100 : 0);
    const actions = [
      can("distributor:write") ? `<button class="btn ghost sm" type="button" data-act="edit-dist" data-id="${d.id}">Open</button>` : "",
      can("sales:write") ? `<button class="btn ghost sm" type="button" data-act="new-so-dist" data-id="${d.id}">New order</button>` : "",
      can("credit:manage") ? `<button class="btn ghost sm" type="button" data-act="change-limit" data-id="${d.id}">Change limit</button>` : ""
    ].filter(Boolean).join(" ");
    return `<tr><td class="strong">${esc(d.code)}</td>
      <td>${esc(d.name)}${d.needs_completion ? ` <span class="chip warn">Needs completion</span>` : ""}<small>${esc(d.territory)} · ${esc(d.gstin || "Unregistered")}</small></td>
      <td class="n">${money(lim)}</td>
      <td class="n">${money(use)}<div class="meter use"><i style="width:${pct.toFixed(0)}%"></i></div></td>
      <td class="n">${money(d.available)}</td>
      <td>${distChip(d.status)}</td>
      <td class="rowacts">${actions}</td></tr>`;
  }).join("");
  paintListPager("customers", s);
  const messages = {
    incomplete: ["Every record has the details a tax document needs.", ""],
    active: ["No active customer or distributor matches.", " Select “All” to see the blocked ones."],
    blocked: ["No customer or distributor is blocked.", " Select “Active” to see the ones that are trading."],
    draft: ["No record is still a draft.", " A draft record is kept out of new orders until it is made Active."],
    "pending verification": ["Nothing is awaiting verification.", " A record in this state is kept out of new orders until it is made Active."],
    inactive: ["No record is inactive.", " An inactive record is kept out of new orders until it is made Active."]
  };
  const [title, hint] = messages[filter] || [
    total ? "No customer or distributor matches this search." : "No customers or distributors yet.",
    can("distributor:write") ? " Select “New customer or distributor” to add the first one." : ""];
  empty($("#cuempty"), !list.length, title, hint);
}
/* ---------- free samples (FOC) ---------- */
const FOC_REASONS = {sample: "Sample", promotional: "Promotional",
                     replacement: "Replacement", donation: "Donation", other: "Other"};
const FOC_STATUS = {draft: "Draft", approved: "Approved", rejected: "Rejected",
                    reversed: "Reversed"};

function openFoc() {
  if (!can("foc:read")) return;
  renderFoc();
  if (!state.foc.loaded && !state.foc.loading) loadFoc();
}

async function loadFoc() {
  if (!can("foc:read")) return;
  const s = state.foc;
  s.loading = true; s.error = null;
  renderFoc();
  const [stock, notes] = await Promise.all([
    api("/api/foc/stock"),
    api("/api/foc/notes?limit=200"),
  ]);
  if (!state.user) return;
  s.loading = false;
  if (stock.ok && Array.isArray(stock.body)) s.stock = stock.body;
  else s.error = detail(stock.body);
  if (notes.ok && Array.isArray(notes.body)) s.notes = notes.body;
  else s.error = s.error || detail(notes.body);
  s.loaded = true;
  renderFoc();
}

function renderFoc() {
  if (!$("#focPanel") || !state.user) return;
  const s = state.foc;
  $("#focNewBtn").classList.toggle("hide", !can("foc:write"));
  $("#focErr").classList.toggle("hide", !s.error);
  $("#focErr").textContent = s.error || "";
  $("#focNote").textContent = s.loading ? "Loading free stock…"
    : s.loaded ? `${plural(s.stock.length, "product")} with a stock position` : "";

  $("#focStockRows").innerHTML = (s.stock || []).map(r =>
    `<tr><td class="strong">${esc(r.sku || "")}</td><td>${esc(r.name || "")}</td>`
    + `<td class="n">${esc(r.on_hand)}</td>`
    + `<td class="n strong">${esc(r.foc_qty)}</td>`
    + `<td class="n">${esc(r.costed_qty)}</td>`
    + `<td class="n">${r.average == null ? "–" : esc(money(r.average))}</td></tr>`).join("");
  empty($("#focStockEmpty"), !(s.stock || []).length,
    s.loading ? "Loading free stock…" : "No product holds free or costed stock yet.");

  const notes = s.notes || [];
  $("#focNoteRows").innerHTML = notes.map(n => {
    const qty = (n.lines || []).reduce((sum, l) => sum + Number(l.qty || 0), 0);
    const acts = [];
    if (n.status === "draft" && can("foc:approve") && n.created_by !== state.user.id) {
      acts.push(`<button class="rowbtn" type="button" data-act="foc-approve" data-id="${n.id}">Approve</button>`);
    }
    if (n.status === "draft" && can("foc:write")) {
      acts.push(`<button class="rowbtn" type="button" data-act="foc-reject" data-id="${n.id}">Reject</button>`);
    }
    if (n.status === "approved" && can("foc:approve")) {
      acts.push(`<button class="rowbtn" type="button" data-act="foc-reverse" data-id="${n.id}">Reverse</button>`);
    }
    return `<tr><td class="strong">${esc(n.note_number)}</td>`
      + `<td>${esc(fmtDate(n.note_date))}</td>`
      + `<td>${esc(n.recipient_name)}${n.correction ? ' <span class="chip">Correction</span>' : ""}</td>`
      + `<td>${esc(n.warehouse || "")}</td>`
      + `<td>${esc(FOC_REASONS[n.reason] || n.reason)}</td>`
      + `<td class="n">${esc(qty)}</td>`
      + `<td class="n">${n.notional_value == null ? "–" : esc(money(n.notional_value))}</td>`
      + `<td><span class="pill">${esc(FOC_STATUS[n.status] || n.status)}</span>`
      + (n.rejection_reason ? `<small>${esc(n.rejection_reason)}</small>` : "")
      + (n.reversal_reason ? `<small>${esc(n.reversal_reason)}</small>` : "") + `</td>`
      + `<td class="rowacts">${acts.join(" ") || "–"}</td></tr>`;
  }).join("");
  empty($("#focNoteEmpty"), !notes.length,
    s.loading ? "Loading free-sample notes…" : "No free-sample note has been written yet.",
    can("foc:write") ? " Use “New free-sample note” to record one recipient at a time." : "");
}

function exportFocStockCsv() {
  if (!state.foc.loaded) return csvNotLoaded("free stock");
  const rows = state.foc.stock || [];
  const csv = [["HERBANOVA free stock (FOC)"], ["As at", isoDay(0)],
    ["SKU", "Product", "On hand", "FOC", "Costed", "Average cost (INR)"]];
  rows.forEach(r => csv.push([r.sku || "", r.name || "", r.on_hand, r.foc_qty,
    r.costed_qty, r.average == null ? "" : r.average]));
  csv.push(["Total", "", csvSum(rows, r => r.on_hand), csvSum(rows, r => r.foc_qty),
    csvSum(rows, r => r.costed_qty), ""]);
  csv.push([], ["Note", "Free stock is held apart from purchased stock and never changes the weighted average."]);
  downloadCsv(`HERBANOVA_FOC_stock_${isoDay(0)}.csv`, csv);
}

function exportFocNotesCsv() {
  if (!state.foc.loaded) return csvNotLoaded("the free-sample notes");
  const rows = state.foc.notes || [];
  const csv = [["HERBANOVA free-sample notes"], ["As at", isoDay(0)],
    ["Number", "Date", "Recipient", "Warehouse", "Reason", "Quantity",
     "Notional value (INR)", "Status", "Correction", "Rejection reason",
     "Reversal reason"]];
  rows.forEach(n => {
    const qty = (n.lines || []).reduce((sum, l) => sum + Number(l.qty || 0), 0);
    csv.push([n.note_number, n.note_date, n.recipient_name, n.warehouse || "",
      FOC_REASONS[n.reason] || n.reason, qty,
      n.notional_value == null ? "" : n.notional_value,
      FOC_STATUS[n.status] || n.status, n.correction ? "Yes" : "No",
      n.rejection_reason || "", n.reversal_reason || ""]);
  });
  const notional = rows.filter(n => n.notional_value != null);
  const qtyTotal = (rows || []).reduce((sum, n) =>
    sum + (n.lines || []).reduce((q, l) => q + Number(l.qty || 0), 0), 0);
  csv.push(["Total", "", "", "", "", qtyTotal,
    notional.length ? csvSum(notional, n => n.notional_value) : "", "", "", "", ""]);
  csv.push([], ["Note", "A free-sample note carries no invoice, revenue or GST."]);
  downloadCsv(`HERBANOVA_FOC_notes_${isoDay(0)}.csv`, csv);
}

function fillFocBatches() {
  const product = $("#f-product"), warehouse = $("#f-wh"), batch = $("#f-batch");
  if (!product || !warehouse || !batch) return;
  const pid = Number(product.value), wid = Number(warehouse.value);
  const rows = (state.batches || []).filter(b =>
    Number(b.product_id) === pid && Number(b.warehouse_id) === wid && Number(b.on_hand) > 0);
  batch.innerHTML = rows.length
    ? rows.map(b => `<option value="${b.id}">${esc(b.batch_no)} · ${esc(b.on_hand)} on hand</option>`).join("")
    : `<option value="">No batch with stock in this warehouse</option>`;
}

function focNewForm() {
  if (!can("foc:write")) return;
  const stock = (state.foc.stock || []).filter(r => Number(r.foc_qty) > 0);
  if (!stock.length) {
    openDrawer("New free-sample note", "No FOC stock is on hand.", `
      <p class="gap-note">No product holds free stock yet. Record the purchase receipt with the
      FOC remark first; then a note can give the stock away.</p>
      <div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`);
    return;
  }
  openDrawer("New free-sample note",
    "One recipient per note. No invoice, revenue or GST.", `
    <form id="focForm" autocomplete="off">
      <div class="row2">
        <div><label for="f-date">Date</label><input id="f-date" name="note_date" type="date" value="${dayIso(new Date())}" max="${dayIso(new Date())}" required></div>
        <div><label for="f-wh">Warehouse</label><select id="f-wh" name="warehouse_id">
          ${(state.warehouses || []).map(w => `<option value="${w.id}">${esc(w.name)}</option>`).join("")}
        </select></div>
      </div>
      <div class="row2">
        <div><label for="f-name">Recipient</label><input id="f-name" name="recipient_name" maxlength="150" required autocomplete="off"></div>
        <div><label for="f-contact">Contact (optional)</label><input id="f-contact" name="recipient_contact" maxlength="120" autocomplete="off"></div>
      </div>
      <label for="f-address">Address (optional)</label><input id="f-address" name="recipient_address" maxlength="300" autocomplete="off">
      <div class="row2">
        <div><label for="f-reason">Reason</label><select id="f-reason" name="reason">
          ${Object.entries(FOC_REASONS).map(([k, v]) => `<option value="${k}"${k === "sample" ? " selected" : ""}>${v}</option>`).join("")}
        </select></div>
        <div><label for="f-notional">Notional value (₹, memo only)</label><input id="f-notional" name="notional_value" inputmode="decimal" autocomplete="off"></div>
      </div>
      <label for="f-reason-note">Note (optional)</label><input id="f-reason-note" name="reason_note" maxlength="300" autocomplete="off">
      <div class="row3">
        <div><label for="f-product">Product</label><select id="f-product" name="product_id">
          ${stock.map(r => `<option value="${r.product_id}">${esc(r.sku)} · ${esc(r.foc_qty)} FOC</option>`).join("")}
        </select></div>
        <div><label for="f-batch">Batch</label><select id="f-batch" name="batch_id"></select></div>
        <div><label for="f-qty">Quantity</label><input id="f-qty" name="qty" inputmode="decimal" required autocomplete="off"></div>
      </div>
      <div class="note">The quantity is checked against the product's FOC stock at approval. A zero-rate sample never changes the weighted average of purchased stock. A second Administrator must approve the note.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save draft</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
  fillFocBatches();
  const productSel = $("#f-product"), whSel = $("#f-wh");
  if (productSel) productSel.addEventListener("change", fillFocBatches);
  if (whSel) whSel.addEventListener("change", fillFocBatches);
}

async function saveFocNote(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = ""; btn.disabled = true;
  const f = form.elements;
  if (!f.batch_id.value) {
    btn.disabled = false; err.textContent = "Choose a batch that holds stock in this warehouse.";
    return;
  }
  const body = {
    note_date: f.note_date.value, warehouse_id: Number(f.warehouse_id.value),
    recipient_name: f.recipient_name.value.trim(),
    reason: f.reason.value,
    lines: [{product_id: Number(f.product_id.value), batch_id: Number(f.batch_id.value),
             qty: f.qty.value.trim()}],
  };
  if (f.recipient_address.value.trim()) body.recipient_address = f.recipient_address.value.trim();
  if (f.recipient_contact.value.trim()) body.recipient_contact = f.recipient_contact.value.trim();
  if (f.reason_note.value.trim()) body.reason_note = f.reason_note.value.trim();
  if (f.notional_value.value.trim()) body.notional_value = f.notional_value.value.trim();
  const res = await api("/api/foc/notes", {method: "POST", body});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, "Free-sample note saved as a draft");
  closeDrawer(); loadFoc();
}

async function focApprove(id) {
  const res = await api(`/api/foc/notes/${id}/approve`, {method: "POST"});
  toast(res, res.ok ? "Free-sample note approved; stock has left the ledger" : "Not approved");
  if (res.ok) loadFoc();
}

function focReasonForm(id, mode) {
  const verb = mode === "reject" ? "Reject" : "Reverse";
  openDrawer(`${verb} free-sample note`,
    "The original note and its movements stay on file.", `
    <form id="focReasonForm" data-id="${id}" data-mode="${mode}">
      <label for="f-why">Reason</label>
      <input id="f-why" name="reason" maxlength="300" required autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">${verb}</button>
      <button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveFocReason(form) {
  const err = $(".err", form);
  const reason = form.elements.reason.value.trim();
  if (!reason) { err.textContent = "Give a reason."; return; }
  const res = await api(`/api/foc/notes/${form.dataset.id}/${form.dataset.mode}`,
                        {method: "POST", body: {reason}});
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, form.dataset.mode === "reject" ? "Note rejected" : "Note reversed; stock is back");
  closeDrawer(); loadFoc();
}

/* ---------- HR workspace ---------- */
function hrSetRange(from, to) {
  state.hr.from = from;
  state.hr.to = to;
}
function hrInitRange() {
  if (!state.hr.from || !state.hr.to) {
    const w = dashWindow("month");
    hrSetRange(w.from, w.to);
  }
}
async function openHr() {
  hrInitRange();
  if (!can("hr:read")) {
    state.hr.dashboard = null;
    renderHr();
    return;
  }
  const site = hrSiteParams();
  const [d, e, f, b, o] = await Promise.all([
    api(`/api/hr/dashboard?from_date=${encodeURIComponent(state.hr.from)}&to_date=${encodeURIComponent(state.hr.to)}${site}`),
    api("/api/hr/employees?page_size=200&sort=name"),
    api("/api/hr/saved-filters?view=employees"),
    api("/api/hr/branches"),
    api("/api/hr/offices")]);
  state.hr.dashboard = d.ok ? d.body : null;
  state.hr.error = d.ok ? null : detail(d.body);
  state.hr.employees = e.ok ? e.body : [];
  state.hr.saved = f.ok ? f.body : [];
  state.hr.branches = b.ok ? b.body : [];
  state.hr.offices = o.ok ? o.body : [];
  fillHrSites();
  if (state.view === "hr") { renderHead(); renderHr(); }
}
function hrSiteParams() {
  const q = new URLSearchParams();
  if (state.hr.branchFilter) q.set("branch_id", state.hr.branchFilter);
  if (state.hr.officeFilter) q.set("office_id", state.hr.officeFilter);
  const s = q.toString();
  return s ? `&${s}` : "";
}
function fillHrSites() {
  const branches = state.hr.branches || [];
  const offices = state.hr.offices || [];
  const branch = state.hr.branchFilter || "";
  const shown = offices.filter(o => !branch || String(o.branch_id) === branch);
  const fill = (id, value, allLabel, rows) => {
    const sel = $("#" + id);
    if (!sel) return;
    sel.innerHTML = `<option value="">${esc(allLabel)}</option>` + rows.map(x =>
      `<option value="${x.id}">${esc(x.name)}${x.branch ? ` · ${esc(x.branch)}` : ""}</option>`).join("");
    sel.value = [...sel.options].some(o => o.value === value) ? value : "";
  };
  fill("hrBranchFilter", branch, "All branches", branches);
  fill("hrOfficeFilter", state.hr.officeFilter || "", "All offices", shown);
}
function setHrSite(kind, value) {
  if (kind === "office") {
    state.hr.officeFilter = value;
    const office = (state.hr.offices || []).find(o => String(o.id) === value);
    if (office && office.branch_id) state.hr.branchFilter = String(office.branch_id);
  } else {
    state.hr.branchFilter = value;
    const office = (state.hr.offices || []).find(o => String(o.id) === state.hr.officeFilter);
    if (office && String(office.branch_id) !== value) state.hr.officeFilter = "";
  }
  fillHrSites();
  renderHrDirectory();
  openHr();
}
function setHrRangePreset(key) {
  const w = dashWindow(key === "30" ? "30d" : "month");
  hrSetRange(w.from, w.to);
  $$("[data-hrr]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.hrr === key)));
  $("#hrDateError").classList.add("hide");
  openHr();
}
function applyHrRange() {
  const from = $("#hrFrom").value, to = $("#hrTo").value, err = $("#hrDateError");
  err.classList.add("hide");
  if (!from || !to) { err.textContent = "Choose both dates."; err.classList.remove("hide"); return; }
  if (to < from) { err.textContent = "The end date cannot be before the start date."; err.classList.remove("hide"); return; }
  $$("[data-hrr]").forEach(b => b.setAttribute("aria-pressed", "false"));
  hrSetRange(from, to);
  openHr();
}
function exportHr() {
  const q = new URLSearchParams();
  const search = ($("#hrq").value || "").trim();
  if (search) q.set("q", search);
  if ($("#hrStatus").value) q.set("status", $("#hrStatus").value);
  if ($("#hrDept").value) q.set("department", $("#hrDept").value);
  if (state.hr.branchFilter) q.set("branch_id", state.hr.branchFilter);
  if (state.hr.officeFilter) q.set("office_id", state.hr.officeFilter);
  const s = q.toString();
  location.href = "/api/hr/employees/export.csv" + (s ? "?" + s : "");
}
function hrKpi(label, value, note, opts = {}) {
  const gap = opts.gap ? `<span class="chip off">No data yet</span>` : "";
  return `<div class="kpi${opts.gap ? " cmp-card-gap" : ""}">
    <span class="kpi-label">${esc(label)}${gap}</span>
    <span class="kpi-value">${esc(value)}</span>
    <span class="kpi-note">${esc(note)}</span></div>`;
}
function hrNumber(value) {
  return value == null ? "No data yet" : qty(value);
}
function renderHrKpis(d) {
  const att = d.needs_attention || {};
  const stale = (att.stale_approvals && att.stale_approvals.count) || 0;
  const tiles = [
    hrKpi("On the rolls", hrNumber(d.active_employees),
      `${hrNumber(d.inactive_employees)} inactive · ${hrNumber(d.total_employees)} records`),
    hrKpi("Present today", hrNumber(d.present_today),
      `${hrNumber(d.late_today)} late · ${hrNumber(d.early_today)} early departure`),
    hrKpi("Not in today", hrNumber((d.absent_today || 0) + (d.on_leave_today || 0) + (d.on_od_today || 0)),
      `${hrNumber(d.absent_today)} absent · ${hrNumber(d.on_leave_today)} leave · ${hrNumber(d.on_od_today)} on duty`),
    hrKpi("Joiners this month", hrNumber(d.new_joiners_month),
      `${hrNumber(d.exits_month)} exits this month; ${hrNumber(d.exits_in_range)} in the chosen range`),
    hrKpi("Approvals waiting", hrNumber(d.pending_approvals),
      `${hrNumber(d.pending_leave)} leave; ${stale} older than three days`),
    hrKpi("Probation ending", hrNumber(d.probation_ending_soon),
      "Within 30 days. Confirm or extend on the profile."),
    hrKpi("Documents expiring", hrNumber(d.documents_expiring),
      "Within 60 days.")];
  if (d.payroll_visible) {
    tiles.push(d.payroll_status
      ? hrKpi("Salary payable this month", `₹ ${money(d.salary_payable)}`,
              `Payroll period is ${d.payroll_status}. Costs stay off the HR email.`)
      : hrKpi("Salary payable this month", "", "No payroll period exists for this month yet.", {gap: true}));
  }
  $("#hrKpis").innerHTML = tiles.join("");
}
function renderHrAttention(d) {
  const a = d.needs_attention || {};
  const rows = [];
  if (a.missing_punches && a.missing_punches.count) {
    rows.push(`<li><a class="att-item att-warn" href="#/hr" data-act="hr-attention" data-kind="punches">
      <span class="att-body"><b>Missing punches</b><span>${a.missing_punches.count} attendance row(s) have no check-in or check-out.</span></span>
      <span class="att-go">View</span></a></li>`);
  }
  if (a.negative_leave && a.negative_leave.count) {
    rows.push(`<li><a class="att-item att-bad" href="#/hr" data-act="hr-attention" data-kind="leave">
      <span class="att-body"><b>Leave balance below zero</b><span>${a.negative_leave.count} balance(s) are over-used this year.</span></span>
      <span class="att-go">View</span></a></li>`);
  }
  if (a.stale_approvals && a.stale_approvals.count) {
    rows.push(`<li><a class="att-item att-warn" href="#/approvals">
      <span class="att-body"><b>Approvals older than three days</b><span>${a.stale_approvals.count} request(s) have waited too long.</span></span>
      <span class="att-go">Open</span></a></li>`);
  }
  if (a.incomplete_records && a.incomplete_records.count) {
    rows.push(`<li><a class="att-item att-off" href="#/hr" data-act="hr-attention" data-kind="records">
      <span class="att-body"><b>Incomplete employee records</b><span>${a.incomplete_records.count} active record(s) are missing a field.</span></span>
      <span class="att-go">View</span></a></li>`);
  }
  $("#hrAttentionNote").textContent = rows.length ? `${rows.length} group(s)` : "All clear";
  $("#hrAttention").innerHTML = rows.length ? rows.join("")
    : `<li><div class="att-empty">Nothing needs attention in this range.</div></li>`;
}
function hrTrendChart(points) {
  const last = points.slice(-31);
  if (!last.length) return `<p class="gap-note">No data yet: no attendance rows in this range.</p>`;
  const totals = last.map(p => (p.present || 0) + (p.absent || 0) + (p.leave || 0) + (p.od || 0));
  const max = Math.max(1, ...totals);
  const segs = [
    ["present", "pr", p => p.present || 0, "moss"],
    ["leave", "lv", p => p.leave || 0, "turmeric"],
    ["on duty", "od", p => p.od || 0, "info"],
    ["absent", "ab", p => p.absent || 0, "bad"]];
  const cols = last.map((p, i) => {
    const bars = segs.map(([name, cls, val]) => {
      const n = val(p);
      return n ? `<span class="hr-seg ${cls}" style="height:${(n / max) * 100}%"></span>` : "";
    }).join("");
    const dayLabel = i % 7 === 0 || i === last.length - 1
      ? p.date.slice(8) : "";
    const label = `${p.date}: ${p.present || 0} present, ${p.absent || 0} absent, ` +
      `${p.leave || 0} leave, ${p.od || 0} on duty`;
    return `<div class="hr-col" title="${esc(label)}">
      <div class="hr-stack" role="img" aria-label="${esc(label)}">${bars}</div>
      <span class="hr-date">${esc(dayLabel)}</span></div>`;
  }).join("");
  const legend = `<div class="hr-legend">
    <span><i class="pr"></i>Present</span><span><i class="lv"></i>Leave</span>
    <span><i class="od"></i>On duty</span><span><i class="ab"></i>Absent</span></div>`;
  return `<div class="hr-trend">${cols}</div>${legend}`;
}
function renderHrTrend(d) {
  const trend = d.attendance_trend || [];
  const anyRows = trend.some(p => (p.present || 0) + (p.absent || 0) + (p.leave || 0) + (p.od || 0));
  $("#hrTrend").innerHTML = anyRows ? hrTrendChart(trend)
    : `<p class="gap-note">No data yet: no attendance rows between ${esc(fmtDate(d.from_date))} and ${esc(fmtDate(d.to_date))}.</p>`;
  $("#hrTrendNote").textContent = `${fmtDate(d.from_date)} – ${fmtDate(d.to_date)}`;
  const mix = d.leave_by_type || [];
  $("#hrLeaveMix").innerHTML = `<h3 class="hr-sub">Approved leave by type</h3>` + (mix.length
    ? `<div class="tw"><table class="hr-mini"><thead><tr><th>Type</th><th class="n">Days</th><th class="n">Applications</th></tr></thead><tbody>
        ${mix.map(x => `<tr><td>${esc(x.name)}<small>${esc(x.code)}</small></td><td class="n">${qty(x.days)}</td><td class="n">${x.applications}</td></tr>`).join("")}
      </tbody></table></div>`
    : `<p class="gap-note">No data yet: no approved leave in this range.</p>`);
}
function renderHrCalendar(d) {
  const rows = [];
  (d.birthdays || []).forEach(x => rows.push([x.date, `<b>${esc(x.full_name)}</b>`, `turns ${x.turning}`, "birthday"]));
  (d.anniversaries || []).forEach(x => rows.push([x.date, `<b>${esc(x.full_name)}</b>`, `${x.years} year(s)`, "anniversary"]));
  (d.holidays || []).forEach(x => rows.push([x.date, `<b>${esc(x.name)}</b>`, "holiday", "holiday"]));
  rows.sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
  $("#hrCalendar").innerHTML = rows.length
    ? `<ul class="hr-list">${rows.slice(0, 12).map(([date, name, what, kind]) =>
        `<li><span class="hr-list-when">${esc(fmtDate(date))}<small>${esc(what)}</small></span>
          <span class="hr-list-who">${name}</span><span class="chip ${kind === "holiday" ? "warn" : "ok"}">${esc(kind)}</span></li>`).join("")}</ul>`
    : `<p class="gap-note">No birthdays, work anniversaries or holidays in the next 30 days.</p>`;
}
function renderHrShape(d) {
  const depts = (d.by_department || []).slice().sort((a, b) => b.employees - a.employees);
  const total = depts.reduce((s, x) => s + x.employees, 0) || 1;
  const bars = depts.map(x => `<div class="hr-bar-row">
    <span class="hr-bar-label">${esc(x.department)}</span>
    <span class="hr-bar-track"><i style="width:${Math.round(x.employees / total * 100)}%"></i></span>
    <b>${x.employees}</b></div>`).join("");
  const branches = (d.by_branch || []).map(x =>
    `<li><span>${esc(x.branch)}</span><b>${x.employees}</b></li>`).join("");
  const offices = (d.by_office || []).map(x =>
    `<li><span>${esc(x.office)}</span><b>${x.employees}</b></li>`).join("");
  $("#hrShape").innerHTML = (depts.length
    ? `<div class="hr-bars">${bars}</div>`
    : `<p class="gap-note">No data yet: no active employees are assigned to a department.</p>`)
    + (branches ? `<h3 class="hr-sub">By branch</h3><ul class="hr-split">${branches}</ul>`
      : `<p class="gap-note">No branch has active employees yet.</p>`)
    + (offices ? `<h3 class="hr-sub">By office</h3><ul class="hr-split">${offices}</ul>`
      : `<p class="gap-note">No office has active employees yet.</p>`);
}
function renderHrDirectory() {
  const q = ($("#hrq").value || "").trim().toLowerCase();
  const status = $("#hrStatus").value;
  const dept = $("#hrDept").value;
  const branch = state.hr.branchFilter || "";
  const office = state.hr.officeFilter || "";
  const all = state.hr.employees || [];
  const list = all.filter(e => (!q || [e.code, e.full_name, e.department, e.designation,
      e.branch_name, e.office_name].some(x => (x || "").toLowerCase().includes(q)))
    && (!status || e.status === status)
    && (!dept || (e.department || "Unassigned") === dept)
    && (!branch || String(e.branch_id) === branch)
    && (!office || String(e.office_id) === office));
  $("#hrrows").innerHTML = list.map(e => `<tr>
    <td class="strong">${esc(e.full_name)}<small>${esc(e.code)}</small></td>
    <td>${esc(e.department || "–")}</td><td>${esc(e.designation || "–")}</td>
    <td>${e.office_name ? esc(e.office_name) : "–"}<small>${esc(e.branch_name || "No branch")}</small></td>
    <td>${esc(fmtDate(e.joining_date))}</td>
    <td><span class="chip ${e.status === "active" ? "ok" : "off"}">${esc(e.status)}</span>${e.attendance_required === false
      ? ` <span class="chip warn" title="${esc(`Not required by policy: ${e.attendance_rule || "default"}`)}">No attendance</span>` : ""}</td>
    <td class="rowacts"><button class="btn ghost sm" type="button" data-act="hr-profile" data-id="${e.id}">Open</button></td></tr>`).join("");
  $("#hrDirNote").textContent = all.length === 200
    ? `Showing the first 200 employees; narrow the search to see the rest. ${list.length} match.`
    : `${list.length} of ${plural(all.length, "employee")}.`;
  empty($("#hrempty"), !list.length, all.length ? "No employee matches these filters." : "No employees yet.",
    all.length ? "Clear the search, status, department, branch or office filter." : "Add the first employee with “New employee”.");
}
function fillHrSaved() {
  const sel = $("#hrSaved");
  if (!sel) return;
  const keep = sel.value;
  sel.innerHTML = `<option value="">Saved filters</option>` +
    (state.hr.saved || []).map(f => `<option value="${f.id}">${esc(f.name)}</option>`).join("");
  sel.value = (state.hr.saved || []).some(f => String(f.id) === keep) ? keep : "";
}
function applyHrFilter() {
  const id = Number($("#hrSaved").value);
  const f = (state.hr.saved || []).find(x => x.id === id);
  if (!f) { toast({ok: false, status: 422, body: {detail: "Choose a saved filter first."}}, "No filter"); return; }
  const p = f.params || {};
  $("#hrq").value = p.q || "";
  $("#hrStatus").value = p.status || "";
  $("#hrDept").value = p.department || "";
  state.hr.branchFilter = p.branch_id ? String(p.branch_id) : "";
  state.hr.officeFilter = p.office_id ? String(p.office_id) : "";
  fillHrSites();
  renderHrDirectory();
  openHr();
}
function hrFilterSaveForm() {
  $("#hrSavedBox").innerHTML = `<form id="hrSavedForm" novalidate><h3>Save this view</h3>
    <label>Name</label><input name="name" maxlength="60" autocomplete="off">
    <div class="err" role="alert"></div>
    <div class="actions"><button class="btn" type="submit">Save filter</button>
      <button class="btn ghost" type="button" data-act="hr-filter-cancel">Cancel</button></div></form>`;
}
async function saveHrFilter(form) {
  const name = form.elements.name.value.trim(), err = $(".err", form);
  err.textContent = "";
  if (name.length < 2) { err.textContent = "Give the view a name."; return; }
  const res = await api("/api/hr/saved-filters", {method: "POST", body: {name, view: "employees",
    params: {q: $("#hrq").value.trim(), status: $("#hrStatus").value,
             department: $("#hrDept").value,
             branch_id: state.hr.branchFilter || "",
             office_id: state.hr.officeFilter || ""}}});
  toast(res, res.ok ? "Filter saved" : "Filter not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  $("#hrSavedBox").innerHTML = "";
  state.hr.saved = [...(state.hr.saved || []), res.body].sort((a, b) => a.name.localeCompare(b.name));
  fillHrSaved();
  $("#hrSaved").value = String(res.body.id);
}
async function deleteHrFilter() {
  const id = Number($("#hrSaved").value);
  if (!id) { toast({ok: false, status: 422, body: {detail: "Choose a saved filter first."}}, "No filter"); return; }
  const res = await api(`/api/hr/saved-filters/${id}`, {method: "DELETE"});
  toast(res, res.ok ? "Filter deleted" : "Filter not deleted");
  if (!res.ok) return;
  state.hr.saved = (state.hr.saved || []).filter(f => f.id !== id);
  fillHrSaved();
}
function fillHrDepartments(d) {
  const sel = $("#hrDept"), keep = sel.value;
  const names = new Set((d.by_department || []).map(x => x.department));
  (state.hr.employees || []).forEach(e => names.add(e.department || "Unassigned"));
  sel.innerHTML = `<option value="">All departments</option>` +
    [...names].sort().map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  sel.value = [...names].includes(keep) ? keep : "";
}
function renderHr() {
  if (!$("#hrKpis")) return;
  const wholeTeam = can("hr:read");
  ["#hrDateTools", "#hrKpis", "#hrDirectory"].forEach(s => $(s).classList.toggle("hide", !wholeTeam));
  $("#hrExport").classList.toggle("hide", !wholeTeam);
  $("#hrImport").classList.toggle("hide", !can("hr:write"));
  $("#hrAdd").classList.toggle("hide", !can("hr:write"));
  // Staff get the self-service panel instead of the team task grid.
  $("#hrTasks").classList.toggle("hide", !wholeTeam);
  // Payroll is a closed book: the API needs hr:payroll_prepare to even list a period.
  $$('#v-hr [data-act="hr-payroll"]').forEach(b =>
    b.classList.toggle("hide", !(wholeTeam && can("hr:payroll_prepare"))));
  // Shift, notices, locks, letter templates and site policy are HR/administrator settings.
  ["hr-shifts", "hr-notices", "hr-locks", "hr-letters", "hr-sites", "hr-masters"].forEach(a =>
    $$(`#v-hr [data-act="${a}"]`).forEach(b => b.classList.toggle("hide", !(wholeTeam && can("hr:write")))));
  $$('#v-hr [data-act="hr-reports"]').forEach(b =>
    b.classList.toggle("hide", !(wholeTeam && can("hr:reports"))));
  // The leave calendar is a whole-team view; staff see only their own leave.
  $$('#v-hr [data-act="hr-calendar"]').forEach(b => b.classList.toggle("hide", !wholeTeam));
  $$("#v-hr .hr-team-only").forEach(el => el.classList.toggle("hide", !wholeTeam));
  $("#hrSelf").classList.toggle("hide", wholeTeam || !can("hr:attendance_self"));
  if (!wholeTeam) {
    $("#hrRangeNote").textContent = "Your own attendance, leave and payslips.";
    if (can("hr:attendance_self")) renderHrSelf();
    return;
  }
  refreshHrUnread();
  const d = state.hr.dashboard || {};
  if (!d.from_date) {
    $("#hrKpis").innerHTML = "";
    $("#hrSiteNote").textContent = "";
    $("#hrAttention").innerHTML = `<li><div class="att-empty">${esc(state.hr.error || "The HR figures did not load. Refresh to try again.")}</div></li>`;
    $("#hrTrend").innerHTML = "";
    $("#hrCalendar").innerHTML = "";
    $("#hrShape").innerHTML = "";
    renderHrDirectory();
    return;
  }
  $("#hrFrom").value = state.hr.from;
  $("#hrTo").value = state.hr.to;
  $("#hrRangeNote").textContent = `${fmtDate(d.from_date)} – ${fmtDate(d.to_date)} · today ${fmtDate(d.date)}`;
  fillHrSites();
  $("#hrSiteNote").textContent = d.attendance_required_today == null ? ""
    : `${d.attendance_required_today} of ${d.active_employees} active employee(s) must mark attendance `
      + `today${d.attendance_exempt_today ? `; ${d.attendance_exempt_today} exempt` : ""}.`;
  fillHrDepartments(d);
  fillHrSaved();
  renderHrKpis(d);
  renderHrAttention(d);
  renderHrTrend(d);
  renderHrCalendar(d);
  renderHrShape(d);
  renderHrDirectory();
}
function hrAttention(kind) {
  const a = (state.hr.dashboard && state.hr.dashboard.needs_attention) || {};
  const block = a[kind] || {rows: [], count: 0};
  let rows = "";
  if (kind === "records") {
    rows = (block.rows || []).map(x => `<tr><td class="strong">${esc(x.full_name)}<small>${esc(x.code)}</small></td>
      <td>${esc((x.missing || []).join(", "))}</td>
      <td><button class="btn ghost sm" type="button" data-act="hr-edit-emp" data-id="${x.employee_id}">Complete</button></td></tr>`).join("");
  } else if (kind === "punches") {
    rows = (block.rows || []).map(x => `<tr><td>${esc(x.employee)}</td><td>${esc(fmtDate(x.date))}</td>
      <td></td></tr>`).join("");
  } else {
    rows = (block.rows || []).map(x => `<tr><td>${esc(x.employee)}</td><td>${esc(String(x.year))}</td></tr>`).join("");
  }
  const title = kind === "records" ? "Incomplete employee records"
    : kind === "punches" ? "Attendance missing a punch" : "Leave balances below zero";
  openDrawer(title, `${block.count || 0} item(s). Showing up to 20; the count is complete.`, `
    <div class="tw"><table><thead><tr><th>Employee</th><th>${kind === "records" ? "Missing" : kind === "punches" ? "Date" : "Year"}</th><th></th></tr></thead><tbody>
      ${rows || '<tr><td colspan="3" class="empty-row">Nothing here now.</td></tr>'}</tbody></table></div>`, true);
}
/* ---------- employee profile ---------- */
async function hrProfile(id) {
  const payroll = can("hr:payroll_prepare");
  const [r, bal, br, off, sh, lt, st, cp] = await Promise.all([
    api(`/api/hr/employees/${id}/profile`),
    api(`/api/hr/leave/balances?employee_id=${id}`),
    api("/api/hr/branches"), api("/api/hr/offices"), api("/api/hr/shifts"),
    api("/api/hr/letters/templates"),
    payroll ? api(`/api/hr/salary/structures?employee_id=${id}`) : Promise.resolve(null),
    payroll ? api("/api/hr/salary/components") : Promise.resolve(null)]);
  if (!r.ok) { toast(r, "Employee not loaded"); return; }
  const names = rows => Object.fromEntries((rows && rows.ok ? rows.body : []).map(x => [x.id, x.name]));
  state.hr.profile = {...r.body,
    balances: bal.ok ? bal.body.balances : [],
    balanceYear: bal.ok ? bal.body.year : null,
    branchNames: names(br), officeNames: names(off), shiftNames: names(sh),
    letterTemplates: lt.ok ? lt.body.templates.filter(t => t.active) : [],
    salary: payroll ? {
      structures: st && st.ok ? st.body : [],
      components: cp && cp.ok ? cp.body : [],
      error: st && !st.ok ? detail(st.body) : (cp && !cp.ok ? detail(cp.body) : null)
    } : null};
  hrProfileDrawer("overview");
}
function hrProfileValue(value) {
  return value == null || value === "" ? "—" : esc(value);
}
function hrProfileOverview(p) {
  const e = p.employee;
  const row = (label, value) => `<dt>${esc(label)}</dt><dd>${hrProfileValue(value)}</dd>`;
  const branch = p.branchNames[e.branch_id], office = p.officeNames[e.office_id];
  const shift = p.shiftNames[e.shift_id];
  const dept = e.department || "Unassigned";
  const req = p.attendance_requirement;
  const attendance = req
    ? `${req.required ? "Required" : "Not required"} · self check-in ${req.self_service ? "on" : "off"}${req.attendance_mode ? ` · ${req.attendance_mode}` : ""} · ${req.source}`
    : null;
  const personal = [
    row("Status", e.status), row("Department", dept), row("Designation", e.designation),
    row("Employment type", e.employment_type), row("Joined", fmtDate(e.joining_date)),
    row("Probation ends", e.probation_end_date ? fmtDate(e.probation_end_date) : "—"),
    row("Confirmed", e.confirmation_date ? fmtDate(e.confirmation_date) : "—"),
    row("Branch", branch), row("Office", office), row("Shift", shift),
    row("Attendance policy", attendance),
    row("Phone", e.phone), row("Email", e.email),
    row("Date of birth", e.date_of_birth ? fmtDate(e.date_of_birth) : "—"),
    row("Address", e.address), row("Emergency contact", [e.emergency_name, e.emergency_phone].filter(Boolean).join(" · "))];
  if (e.date_of_exit) personal.push(row("Exited on", fmtDate(e.date_of_exit)), row("Exit reason", e.exit_reason));
  const confidential = p.can_edit_confidential ? `
    <h3 class="hr-sub">Bank and statutory numbers</h3>
    <dl class="dl">
      ${row("Bank", e.bank_name)}${row("Account", e.bank_account_no)}${row("IFSC", e.bank_ifsc)}
      ${row("PAN", e.pan)}${row("UAN", e.uan)}${row("ESI number", e.esi_no)}
    </dl>`
    : `<p class="gap-note">Bank, PAN and statutory numbers are hidden for your role. The server masks them rather than sending them to the browser.</p>`;
  const bals = p.balances || [];
  const balances = `<h3 class="hr-sub">Leave balances ${p.balanceYear ? `in ${p.balanceYear}` : ""}</h3>` +
    (bals.length ? `<div class="tw"><table class="hr-mini"><thead><tr><th>Type</th><th class="n">Entitled</th><th class="n">Carried</th><th class="n">Used</th><th class="n">Pending</th><th class="n">Available</th></tr></thead><tbody>
      ${bals.map(x => `<tr><td>${esc(x.name)}</td><td class="n">${qty(x.entitled)}</td><td class="n">${qty(x.carried)}</td><td class="n">${qty(x.used)}</td><td class="n">${qty(x.pending)}</td><td class="n strong">${qty(x.available)}</td></tr>`).join("")}
      </tbody></table></div>`
    : `<p class="gap-note">No data yet: no leave types are configured.</p>`);
  return `<dl class="dl">${personal.join("")}</dl>${confidential}${balances}`;
}
function hrProfileDocuments(p) {
  const canEdit = p.can_edit;
  return `<div class="actions" style="margin-top:0">
      ${canEdit ? `<button class="btn" type="button" data-act="hr-doc-new" data-id="${p.employee.id}">Add a document</button>` : ""}</div>
    <div class="tw"><table><thead><tr><th>Document</th><th>Number</th><th>Expires</th><th>Status</th><th></th></tr></thead><tbody>
      ${(p.documents || []).map(x => {
        const days = x.expires_on ? daysUntil(x.expires_on) : null;
        return `<tr><td class="strong">${esc(x.title)}<small>${esc(x.doc_type)}</small></td>
          <td>${x.number ? esc(x.number) + (x.number_masked ? ' <span class="chip off">masked</span>' : "") : "—"}</td>
          <td>${x.expires_on ? esc(fmtDate(x.expires_on)) + (days != null && days < 30 ? ` <span class="chip warn">${days < 0 ? "expired" : days + " days"}</span>` : "") : "—"}</td>
          <td><span class="chip ${x.status === "active" ? "ok" : "off"}">${esc(x.status)}</span></td>
          <td class="rowacts">${canEdit ? `<button class="btn ghost sm" type="button" data-act="hr-doc-edit" data-id="${x.id}">Edit</button>` : ""}</td></tr>`;
      }).join("") || '<tr><td colspan="5" class="empty-row">No documents recorded.</td></tr>'}
    </tbody></table></div>
    <p class="note">Documents are never deleted. When one is replaced, mark it replaced so the history stays intact.</p>`;
}
function hrProfileAssets(p) {
  const canEdit = p.can_edit;
  return `<div class="actions" style="margin-top:0">
      ${canEdit ? `<button class="btn" type="button" data-act="hr-asset-new" data-id="${p.employee.id}">Issue an asset</button>` : ""}</div>
    <div class="tw"><table><thead><tr><th>Asset</th><th>Serial</th><th>Issued</th><th>Returned</th><th>Condition</th><th></th></tr></thead><tbody>
      ${(p.assets || []).map(x => `<tr><td class="strong">${esc(x.name)}<small>${esc(x.asset_type)}</small></td>
        <td>${esc(x.serial_no || "—")}</td><td>${esc(fmtDate(x.issued_on))}</td>
        <td>${x.returned_on ? esc(fmtDate(x.returned_on)) : '<span class="chip warn">in use</span>'}</td>
        <td>${esc(x.condition_note || "—")}</td>
        <td class="rowacts">${canEdit && !x.returned_on ? `<button class="btn ghost sm" type="button" data-act="hr-asset-return" data-id="${x.id}">Return</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="6" class="empty-row">No assets issued.</td></tr>'}
    </tbody></table></div>`;
}
function hrProfileHistory(p) {
  return `<div class="tw"><table><thead><tr><th>When</th><th>Action</th><th>Actor</th><th>Changes</th></tr></thead><tbody>
    ${(p.history || []).map(x => `<tr><td>${esc(fmtStamp(x.at))}</td><td>${esc(x.action)}</td><td>${esc(x.actor)}</td>
      <td><code>${esc(JSON.stringify(x.changes || {}))}</code></td></tr>`).join("") || '<tr><td colspan="4" class="empty-row">No changes recorded yet.</td></tr>'}
    </tbody></table></div>`;
}
function hrProfileOutputs(p) {
  const e = p.employee;
  const letters = (p.letterTemplates || []).map(t =>
    `<button class="btn ghost sm" type="button" data-act="hr-letter" data-code="${esc(t.code)}" data-emp="${e.id}">${esc(t.name)} (PDF)</button>`).join("");
  return `<div class="actions hr-wrap" style="margin-top:0">
      <button class="btn ghost" type="button" data-act="hr-card" data-emp="${e.id}">ID card (PDF)</button>
      <button class="btn ghost" type="button" data-act="hr-statement" data-emp="${e.id}">Leave statement (PDF)</button>
    </div>
    <h3 class="hr-sub">Letters</h3>
    <p class="note">Each letter is filled on the server from this record. A date the record does not hold stops the letter instead of printing a blank, and every download is audited.</p>
    <div class="actions hr-wrap">${letters || '<span class="muted">No active letter template.</span>'}</div>`;
}
function hrProfileSalary(p) {
  const s = p.salary;
  if (!s) return "";
  const rows = (s.structures || []).map(x => `<tr>
    <td>${esc(fmtDate(x.effective_from))}${x.effective_to ? `<small>to ${esc(fmtDate(x.effective_to))}</small>` : ""}</td>
    <td>${esc(x.payment_mode)}</td>
    <td><span class="chip ${x.status === "active" ? "ok" : "off"}">${esc(x.status)}</span></td>
    <td>${(x.lines || []).map(l => `${esc(l.component)} ${
      l.percent != null && l.percent !== "" ? esc(String(l.percent)) + "%" : money(l.amount)}`).join(" · ") || "—"}</td></tr>`).join("");
  return `<div class="actions" style="margin-top:0">
      <button class="btn" type="button" data-act="hr-new-structure" data-emp="${p.employee.id}">New salary structure</button></div>
    ${s.error ? `<p class="gap-note">${esc(s.error)}</p>` : ""}
    <div class="tw"><table><thead><tr><th>Effective</th><th>Payment</th><th>Status</th><th>Components</th></tr></thead><tbody>
      ${rows || '<tr><td colspan="4" class="empty-row">No data yet: this employee has no salary structure. Payroll skips them until one is assigned.</td></tr>'}
    </tbody></table></div>
    <div class="note">Salary is confidential. It is shown here only because your role holds payroll preparation rights; every change is recorded in the audit trail.</div>`;
}
function hrProfileDrawer(tab) {
  const p = state.hr.profile;
  if (!p) return;
  const e = p.employee;
  const tabs = [["overview", "Overview"], ["documents", `Documents (${(p.documents || []).length})`]];
  if (p.salary) tabs.push(["salary", "Salary"]);
  tabs.push(["assets", `Assets (${(p.assets || []).length})`], ["outputs", "Letters & ID"],
            ["history", "History"]);
  const body = tab === "documents" ? hrProfileDocuments(p)
    : tab === "salary" ? hrProfileSalary(p)
    : tab === "assets" ? hrProfileAssets(p)
    : tab === "outputs" ? hrProfileOutputs(p)
    : tab === "history" ? hrProfileHistory(p) : hrProfileOverview(p);
  openDrawer(`${e.full_name} · ${e.code}`,
    `${e.designation || "No designation"} · ${e.department || "No department"} · ${e.status}`, `
    <div class="seg compact hr-tabs" role="group" aria-label="Profile section">
      ${tabs.map(([k, label]) => `<button type="button" data-hrp="${k}" aria-pressed="${k === tab}">${esc(label)}</button>`).join("")}
    </div>
    <div id="hrProfileBody">${body}</div>
    <div class="actions">
      ${p.can_edit ? `<button class="btn" type="button" data-act="hr-edit-emp" data-id="${e.id}">Edit employee</button>` : ""}
      <button class="btn ghost" type="button" data-act="close">Close</button></div>`, true);
}
function hrDocForm(employeeId, docId) {
  const p = state.hr.profile;
  const x = docId ? (p.documents || []).find(d => d.id === Number(docId)) : null;
  openDrawer(x ? "Edit document" : "Add a document",
    "A number is stored masked for readers without confidential rights. Documents are never deleted.", `
    <form id="hrDocForm" data-id="${x ? x.id : ""}" data-emp="${employeeId}" novalidate>
      <div class="row2"><div><label>Type</label><input name="doc_type" value="${esc(x ? x.doc_type : "")}" placeholder="licence, contract, ID" autocomplete="off"></div>
      <div><label>Title</label><input name="title" value="${esc(x ? x.title : "")}" autocomplete="off"></div></div>
      <label>Number</label><input name="number" value="${esc(x && x.number ? x.number : "")}" autocomplete="off">
      <div class="row2"><div><label>Issued on</label><input name="issued_on" type="date" value="${x && x.issued_on ? x.issued_on : ""}"></div>
      <div><label>Expires on</label><input name="expires_on" type="date" value="${x && x.expires_on ? x.expires_on : ""}"></div></div>
      <label>Status</label><select name="status"><option value="active"${!x || x.status === "active" ? " selected" : ""}>Active</option>
        <option value="expired"${x && x.status === "expired" ? " selected" : ""}>Expired</option>
        <option value="replaced"${x && x.status === "replaced" ? " selected" : ""}>Replaced</option></select>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save document</button><button class="btn ghost" type="button" data-act="hr-profile-tab" data-tab="documents">Cancel</button></div>
    </form>`, true);
}
async function saveHrDoc(form) {
  const f = form.elements, err = $(".err", form), emp = form.dataset.emp, id = form.dataset.id;
  err.textContent = "";
  if (!f.doc_type.value.trim() || !f.title.value.trim()) { err.textContent = "Give the document a type and a title."; return; }
  if (f.issued_on.value && f.expires_on.value && f.expires_on.value < f.issued_on.value) {
    err.textContent = "The expiry cannot be before the issue date."; return;
  }
  const body = {doc_type: f.doc_type.value.trim(), title: f.title.value.trim(),
    number: f.number.value.trim() || null, issued_on: f.issued_on.value || null,
    expires_on: f.expires_on.value || null, status: f.status.value};
  const res = await api(id ? `/api/hr/employees/${emp}/documents/${id}` : `/api/hr/employees/${emp}/documents`,
    {method: id ? "PATCH" : "POST", body});
  toast(res, res.ok ? "Document saved" : "Document not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await hrProfile(emp);
  hrProfileDrawer("documents");
}
function hrAssetForm(employeeId) {
  openDrawer("Issue an asset", "Returned assets stay on the record; the issue date is kept.", `
    <form id="hrAssetForm" data-emp="${employeeId}" novalidate>
      <div class="row2"><div><label>Type</label><input name="asset_type" placeholder="Laptop, phone, vehicle" autocomplete="off"></div>
      <div><label>Name</label><input name="name" autocomplete="off"></div></div>
      <div class="row2"><div><label>Serial number</label><input name="serial_no" autocomplete="off"></div>
      <div><label>Issued on</label><input name="issued_on" type="date" value="${isoDay(0)}"></div></div>
      <label>Condition note</label><input name="condition_note" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Record the issue</button><button class="btn ghost" type="button" data-act="hr-profile-tab" data-tab="assets">Cancel</button></div>
    </form>`, true);
}
async function saveHrAsset(form) {
  const f = form.elements, err = $(".err", form), emp = form.dataset.emp;
  err.textContent = "";
  if (!f.asset_type.value.trim() || !f.name.value.trim()) { err.textContent = "Give the asset a type and a name."; return; }
  if (!f.issued_on.value) { err.textContent = "Choose the issue date."; return; }
  const res = await api(`/api/hr/employees/${emp}/assets`, {method: "POST", body: {
    asset_type: f.asset_type.value.trim(), name: f.name.value.trim(),
    serial_no: f.serial_no.value.trim() || null, issued_on: f.issued_on.value,
    condition_note: f.condition_note.value.trim() || null}});
  toast(res, res.ok ? "Asset issued" : "Asset not recorded");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await hrProfile(emp);
  hrProfileDrawer("assets");
}
function hrAssetReturnForm(assetId) {
  const p = state.hr.profile, x = (p.assets || []).find(a => a.id === Number(assetId));
  if (!p || !x) return;
  openDrawer(`Return ${x.name}`, "The asset stays in the employee's history as returned.", `
    <form id="hrAssetReturnForm" data-id="${x.id}" data-emp="${p.employee.id}" novalidate>
      <label>Returned on</label><input name="returned_on" type="date" value="${isoDay(0)}">
      <label>Condition note</label><input name="condition_note" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Record the return</button><button class="btn ghost" type="button" data-act="hr-profile-tab" data-tab="assets">Cancel</button></div>
    </form>`, true);
}
async function saveHrAssetReturn(form) {
  const f = form.elements, err = $(".err", form), emp = form.dataset.emp;
  err.textContent = "";
  if (!f.returned_on.value) { err.textContent = "Choose the return date."; return; }
  const res = await api(`/api/hr/assets/${form.dataset.id}/return`, {method: "POST", body: {
    returned_on: f.returned_on.value, condition_note: f.condition_note.value.trim() || null}});
  toast(res, res.ok ? "Asset returned" : "Return not recorded");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await hrProfile(emp);
  hrProfileDrawer("assets");
}
/* ---------- letters and printable output ---------- */
async function hrLetters() {
  const r = await api("/api/hr/letters/templates");
  if (!r.ok) { toast(r, "Templates not loaded"); return; }
  state.hr.letterTemplates = r.body.templates;
  const placeholders = (r.body.placeholders || []).map(x => `<code>{${esc(x)}}</code>`).join(" ");
  openDrawer("Letter templates", "Edits change the wording of every future letter. Every generated letter is a draft until signed and sealed.", `
    <p class="note">Placeholders are filled from the employee record: ${placeholders}. A word in braces that is not on this list is refused when you save.</p>
    <div class="tw"><table><thead><tr><th>Template</th><th>Code</th><th>Status</th><th></th></tr></thead><tbody>
      ${r.body.templates.map(t => `<tr><td class="strong">${esc(t.name)}</td><td>${esc(t.code)}</td>
        <td><span class="chip ${t.active ? "ok" : "off"}">${t.active ? "active" : "retired"}</span></td>
        <td class="rowacts"><button class="btn ghost sm" type="button" data-act="hr-letter-edit" data-id="${t.id}">Edit</button></td></tr>`).join("")}
    </tbody></table></div>
    <p class="note">Open an employee's profile and choose “Letters &amp; ID” to download a filled letter, an ID card or a leave statement.</p>`, true);
}
function hrLetterForm(id) {
  const t = (state.hr.letterTemplates || []).find(x => x.id === Number(id));
  if (!t) return;
  openDrawer(`Edit ${t.name}`, "The body is plain text. Blank lines separate paragraphs.", `
    <form id="hrLetForm" data-id="${t.id}" novalidate>
      <label>Template name</label><input name="name" value="${esc(t.name)}" maxlength="120" autocomplete="off">
      <label>Body</label><textarea name="body" rows="16" spellcheck="false">${esc(t.body)}</textarea>
      <label class="check"><input type="checkbox" name="active"${t.active ? " checked" : ""}> Active — a retired template cannot generate letters</label>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save template</button><button class="btn ghost" type="button" data-act="hr-letters">Cancel</button></div>
    </form>`, true);
}
async function saveHrLetterTemplate(form) {
  const f = form.elements, err = $(".err", form);
  err.textContent = "";
  if (f.name.value.trim().length < 3 || f.body.value.trim().length < 20) {
    err.textContent = "Give the template a name and a body of at least 20 characters."; return;
  }
  const res = await api(`/api/hr/letters/templates/${form.dataset.id}`, {method: "PATCH", body: {
    name: f.name.value.trim(), body: f.body.value.trim(), active: f.active.checked}});
  toast(res, res.ok ? "Template saved" : "Template not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await hrLetters();
}
async function downloadOutput(url) {
  const res = await fetch(url, {credentials: "same-origin"});
  if (!res.ok) {
    let message = `Download failed (${res.status})`;
    try { message = detail(await res.json()) || message; } catch (err) { /* not JSON */ }
    toast({ok: false, body: {detail: message}}, "Not downloaded");
    return;
  }
  const disposition = res.headers.get("Content-Disposition") || "";
  const found = /filename="?([^";]+)"?/.exec(disposition);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await res.blob());
  link.download = found ? found[1] : "hr-output.pdf";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 10000);
}
function downloadAttendanceSheet() {
  const [y, m] = (state.hr.mxMonth || "").split("-").map(Number);
  if (!y || !m) { toast({ok: false, body: {detail: "Choose a month first."}}, "No month"); return; }
  const q = new URLSearchParams({year: y, month: m});
  if (state.hr.mxDept) q.set("department", state.hr.mxDept);
  downloadOutput(`/api/hr/outputs/attendance-sheet?${q}`);
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

/* ---------- HR: branches, offices and attendance policy ---------- */
const HR_MODE = {office: "Office", gps: "GPS", both: "Office or GPS"};
const hrMode = v => (v ? HR_MODE[v] || v : "Office default");
function hrRuleScore(r) {
  return (r.employee_id ? 1000 : 0) + (r.office_id ? 100 : 0)
    + (r.designation ? 10 : 0) + (r.branch_id ? 1 : 0);
}
function hrRuleTarget(r) {
  const bits = [];
  if (r.branch) bits.push(`Branch: ${r.branch}`);
  if (r.office) bits.push(`Office: ${r.office}`);
  if (r.designation) bits.push(`Designation: ${r.designation}`);
  if (r.employee) bits.push(`Employee: ${r.employee}`);
  return bits.join(" · ") || "Whole company";
}
function hrEffective(r) {
  if (!r.effective_from && !r.effective_to) return "Always";
  return `${r.effective_from ? fmtDate(r.effective_from) : "start"} – ${r.effective_to ? fmtDate(r.effective_to) : "open"}`;
}
async function hrSiteData() {
  const [b, o, r, s, e] = await Promise.all([api("/api/hr/branches"), api("/api/hr/offices"),
    api("/api/hr/attendance-rules"), api("/api/hr/shifts"), api("/api/hr/employees?page_size=200&sort=name")]);
  if (b.ok) state.hr.branches = b.body;
  if (o.ok) state.hr.offices = o.body;
  if (r.ok) state.hr.rules = r.body;
  if (s.ok) state.hr.shifts = s.body;
  if (e.ok) state.hr.siteEmps = e.body;
  if (b.ok && o.ok) fillHrSites();
  if (!(b.ok && o.ok && r.ok)) {
    toast({ok: false, body: {detail: "Some branch, office or rule data did not load. Try Refresh."}},
          "Site data incomplete");
  }
  return {branches: state.hr.branches || [], offices: state.hr.offices || [],
          rules: state.hr.rules || [], shifts: state.hr.shifts || [],
          employees: state.hr.siteEmps || []};
}
async function hrSites() {
  await hrSiteData();
  const branches = state.hr.branches || [], offices = state.hr.offices || [];
  const rules = [...(state.hr.rules || [])].sort((a, b) =>
    hrRuleScore(b) - hrRuleScore(a) || a.priority - b.priority || a.id - b.id);
  const writable = can("hr:write");
  const edit = (act, id, label) => writable
    ? `<button class="btn ghost sm" type="button" data-act="${act}" data-id="${id}">${label}</button>` : "";
  const branchRows = branches.map(b => `<tr><td class="strong">${esc(b.name)}<small>${esc(b.code)}</small></td>
    <td>${esc(b.address || "–")}</td><td>${esc(b.hr_admin || "–")}</td>
    <td class="n">${b.active_employees}</td>
    <td><span class="chip ${b.status === "active" ? "ok" : "off"}">${esc(b.status)}</span></td>
    <td class="rowacts">${edit("hr-edit-branch", b.id, "Edit")}</td></tr>`).join("");
  const officeRows = offices.map(o => `<tr><td class="strong">${esc(o.name)}<small>${esc(o.code)}</small></td>
    <td>${esc(o.branch || "–")}</td><td>${esc(hrMode(o.attendance_mode))}</td>
    <td>${o.latitude != null && o.longitude != null
      ? `${esc(String(o.latitude))}, ${esc(String(o.longitude))} · ${o.geofence_radius_m} m`
      : '<span class="muted">No geofence</span>'}</td>
    <td>${esc(o.hr_admin || "–")}</td><td class="n">${o.active_employees}</td>
    <td><span class="chip ${o.status === "active" ? "ok" : "off"}">${esc(o.status)}</span></td>
    <td class="rowacts">${edit("hr-edit-office", o.id, "Edit")}</td></tr>`).join("");
  const ruleRows = rules.map(r => `<tr><td class="strong">${esc(hrRuleTarget(r))}<small>${esc(r.source)}</small></td>
    <td><span class="chip ${r.required ? "ok" : "off"}">${r.required ? "Required" : "Not required"}</span></td>
    <td>${r.self_service ? "On" : "Off"}</td>
    <td>${esc(r.shift || "Office default")}</td><td>${esc(hrMode(r.attendance_mode))}</td>
    <td>${esc(hrEffective(r))}</td><td class="n">${r.priority}</td>
    <td><span class="chip ${r.active ? "ok" : "off"}">${r.active ? "active" : "inactive"}</span></td>
    <td class="rowacts">${edit("hr-edit-rule", r.id, "Edit")}${writable
      ? ` <button class="btn ghost sm" type="button" data-act="hr-rule-delete" data-id="${r.id}">Delete</button>` : ""}</td></tr>`).join("");
  openDrawer("Branches, offices & attendance policy",
    "A branch groups offices. An employee belongs to one office, and that office belongs to one branch. Every change is audited.", `
    <div class="note">Who must mark attendance: the most specific active rule wins — employee, then office, then designation, then branch, then the company default. With no rule at all, attendance is required. A rule can set its own shift and attendance mode but never overrides the office’s own mode unless the rule dates are in force.</div>
    ${writable ? `<div class="actions" style="margin-top:0">
      <button class="btn" type="button" data-act="hr-new-branch">New branch</button>
      <button class="btn" type="button" data-act="hr-new-office">New office</button>
      <button class="btn" type="button" data-act="hr-new-rule">New attendance rule</button>
      <button class="btn ghost" type="button" data-act="hr-sites">Refresh</button></div>` : ""}
    <h3>Branches</h3>
    <div class="tw"><table><thead><tr><th>Branch</th><th>Address</th><th>HR responsible</th><th class="n">Active staff</th><th>Status</th><th></th></tr></thead>
      <tbody>${branchRows || '<tr><td colspan="6" class="empty-row">No branches configured. Attendance is still required company-wide.</td></tr>'}</tbody></table></div>
    <h3>Offices and work locations</h3>
    <div class="tw"><table><thead><tr><th>Office</th><th>Branch</th><th>Mode</th><th>Geofence</th><th>HR responsible</th><th class="n">Active staff</th><th>Status</th><th></th></tr></thead>
      <tbody>${officeRows || '<tr><td colspan="8" class="empty-row">No offices configured.</td></tr>'}</tbody></table></div>
    <h3>Attendance requirements</h3>
    <div class="tw"><table><thead><tr><th>Rule applies to</th><th>Attendance</th><th>Self check-in</th><th>Shift</th><th>Mode</th><th>Effective</th><th class="n">Priority</th><th>Status</th><th></th></tr></thead>
      <tbody>${ruleRows || '<tr><td colspan="9" class="empty-row">No rule yet. Every employee must mark attendance with the office default.</td></tr>'}</tbody></table></div>
    <div class="note">A branch or office with active staff cannot be switched off or moved until those people are reassigned. Deactivate, never delete.</div>`, true);
  $("#drawer").classList.add("hr-wide");
}
function hrSiteSelect(rows, selected, label) {
  return `<option value="">—</option>` + rows.map(v =>
    `<option value="${v.id}"${selected === v.id ? " selected" : ""}>${esc(label(v))}</option>`).join("");
}
function hrAdminField(selected) {
  const emps = state.hr.siteEmps || [];
  return `<label>HR responsible at this site</label><select name="hr_admin_id">${hrSiteSelect(emps, selected,
    v => `${v.full_name} (${v.code})`)}</select>`;
}
async function hrBranchForm(id) {
  await hrSiteData();
  const x = id ? (state.hr.branches || []).find(b => b.id === Number(id)) : null;
  if (id && !x) { toast({ok: false, body: {detail: "Branch not found"}}, "Branch not loaded"); return; }
  const v = x || {id: "", code: "", name: "", address: "", hr_admin_id: null, status: "active"};
  openDrawer(x ? `Edit ${x.name}` : "New branch",
    "The HR responsible at a branch is the employee who answers for its attendance; it does not change who can approve leave.", `
    <form id="hrBranchForm" data-id="${v.id || ""}" novalidate>
      <div class="row2"><div><label for="hrb-code">Branch code</label><input id="hrb-code" name="code" value="${esc(v.code)}"${x ? " readonly" : ""} autocomplete="off"></div>
      <div><label for="hrb-name">Branch name</label><input id="hrb-name" name="name" value="${esc(v.name)}" autocomplete="off"></div></div>
      <label for="hrb-addr">Address</label><input id="hrb-addr" name="address" value="${esc(v.address || "")}" autocomplete="off">
      ${hrAdminField(v.hr_admin_id)}
      ${x ? `<label for="hrb-status">Status</label><select id="hrb-status" name="status"><option value="active"${v.status === "active" ? " selected" : ""}>Active</option><option value="inactive"${v.status !== "active" ? " selected" : ""}>Inactive</option></select>` : ""}
      <div class="note">A code cannot be changed once the branch exists. An inactive branch keeps its history and accepts no new assignment.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save branch</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}
async function saveHrBranch(form) {
  const f = form.elements, err = $(".err", form);
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  err.textContent = "";
  const body = {name: f.name.value.trim(), address: f.address.value.trim() || null,
                hr_admin_id: f.hr_admin_id.value ? Number(f.hr_admin_id.value) : null};
  if (!id) body.code = f.code.value.trim().toUpperCase();
  else body.status = f.status.value;
  if ((body.name || "").length < 2) { err.textContent = "Enter the branch name."; return; }
  if (!id && (body.code || "").length < 2) { err.textContent = "Enter a branch code of at least two characters."; return; }
  const res = await api(id ? `/api/hr/branches/${id}` : "/api/hr/branches",
                        {method: id ? "PATCH" : "POST", body});
  toast(res, res.ok ? (id ? "Branch updated" : "Branch created") : "Branch not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrSites();
}
async function hrOfficeForm(id) {
  await hrSiteData();
  const x = id ? (state.hr.offices || []).find(o => o.id === Number(id)) : null;
  if (id && !x) { toast({ok: false, body: {detail: "Office not found"}}, "Office not loaded"); return; }
  const v = x || {id: "", code: "", name: "", branch_id: null, address: "", latitude: null,
                  longitude: null, geofence_radius_m: 200, attendance_mode: "both",
                  hr_admin_id: null, status: "active"};
  const branches = state.hr.branches || [];
  openDrawer(x ? `Edit ${x.name}` : "New office",
    "The geofence centre and radius decide whether a GPS check-in counts at this office. Leave both coordinates empty for an office without GPS.", `
    <form id="hrOfficeForm" data-id="${v.id || ""}" novalidate>
      <div class="row2"><div><label for="hro-code">Office code</label><input id="hro-code" name="code" value="${esc(v.code)}"${x ? " readonly" : ""} autocomplete="off"></div>
      <div><label for="hro-name">Office name</label><input id="hro-name" name="name" value="${esc(v.name)}" autocomplete="off"></div></div>
      <div class="row2"><div><label for="hro-branch">Branch</label><select id="hro-branch" name="branch_id">${hrSiteSelect(branches, v.branch_id, b => b.name)}</select></div>
      <div><label for="hro-mode">Attendance mode</label><select id="hro-mode" name="attendance_mode">
        <option value="office"${v.attendance_mode === "office" ? " selected" : ""}>Office</option>
        <option value="gps"${v.attendance_mode === "gps" ? " selected" : ""}>GPS</option>
        <option value="both"${v.attendance_mode === "both" ? " selected" : ""}>Office or GPS</option></select></div></div>
      <label for="hro-addr">Address</label><input id="hro-addr" name="address" value="${esc(v.address || "")}" autocomplete="off">
      <div class="row2"><div><label for="hro-lat">Latitude</label><input id="hro-lat" name="latitude" inputmode="decimal" value="${v.latitude == null ? "" : esc(String(v.latitude))}" autocomplete="off"></div>
      <div><label for="hro-lon">Longitude</label><input id="hro-lon" name="longitude" inputmode="decimal" value="${v.longitude == null ? "" : esc(String(v.longitude))}" autocomplete="off"></div></div>
      <label for="hro-radius">Geofence radius (metres)</label><input id="hro-radius" name="geofence_radius_m" type="number" min="1" max="100000" value="${v.geofence_radius_m}">
      ${hrAdminField(v.hr_admin_id)}
      ${x ? `<label for="hro-status">Status</label><select id="hro-status" name="status"><option value="active"${v.status === "active" ? " selected" : ""}>Active</option><option value="inactive"${v.status !== "active" ? " selected" : ""}>Inactive</option></select>` : ""}
      <div class="note">Self check-in still depends on the attendance rule: an employee exempt at this office is refused a check-in even when GPS matches.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save office</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}
async function saveHrOffice(form) {
  const f = form.elements, err = $(".err", form);
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  err.textContent = "";
  const lat = f.latitude.value.trim(), lon = f.longitude.value.trim();
  const body = {name: f.name.value.trim(), branch_id: f.branch_id.value ? Number(f.branch_id.value) : null,
                address: f.address.value.trim() || null,
                latitude: lat === "" ? null : Number(lat), longitude: lon === "" ? null : Number(lon),
                geofence_radius_m: Number(f.geofence_radius_m.value),
                attendance_mode: f.attendance_mode.value,
                hr_admin_id: f.hr_admin_id.value ? Number(f.hr_admin_id.value) : null};
  if (!id) body.code = f.code.value.trim().toUpperCase();
  else body.status = f.status.value;
  if ((body.name || "").length < 2) { err.textContent = "Enter the office name."; return; }
  if (!id && (body.code || "").length < 2) { err.textContent = "Enter an office code of at least two characters."; return; }
  if ((lat === "") !== (lon === "")) { err.textContent = "Give both the latitude and the longitude, or neither."; return; }
  if (lat !== "" && (!(body.latitude >= -90 && body.latitude <= 90)
      || !(body.longitude >= -180 && body.longitude <= 180))) {
    err.textContent = "Latitude must be between -90 and 90 and longitude between -180 and 180."; return;
  }
  if (!(body.geofence_radius_m >= 1)) { err.textContent = "Enter the geofence radius in metres."; return; }
  const res = await api(id ? `/api/hr/offices/${id}` : "/api/hr/offices",
                        {method: id ? "PATCH" : "POST", body});
  toast(res, res.ok ? (id ? "Office updated" : "Office created") : "Office not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrSites();
}
async function hrRuleForm(id) {
  await hrSiteData();
  const x = id ? (state.hr.rules || []).find(r => r.id === Number(id)) : null;
  if (id && !x) { toast({ok: false, body: {detail: "Attendance rule not found"}}, "Rule not loaded"); return; }
  const v = x || {id: "", branch_id: null, office_id: null, designation: "", employee_id: null,
                  required: true, self_service: true, shift_id: null, attendance_mode: null,
                  effective_from: null, effective_to: null, priority: 100, active: true, note: ""};
  const branches = state.hr.branches || [], shifts = state.hr.shifts || [];
  const emps = state.hr.siteEmps || [];
  const designations = [...new Set(emps.map(e => e.designation).filter(Boolean))].sort();
  const offices = (state.hr.offices || []).filter(o => !v.branch_id || o.branch_id === v.branch_id);
  openDrawer(x ? `Edit rule ${x.id}` : "New attendance rule",
    "Leave a target empty to mean “any”. The more targets you fill, the more specific the rule and the earlier it is applied.", `
    <form id="hrRuleForm" data-id="${v.id || ""}" novalidate>
      <div class="row2"><div><label for="hrr-branch">Branch</label><select id="hrr-branch" name="branch_id">${hrSiteSelect(branches, v.branch_id, b => b.name)}</select></div>
      <div><label for="hrr-office">Office / work location</label><select id="hrr-office" name="office_id"><option value="">—</option>${offices.map(o => `<option value="${o.id}" data-branch="${o.branch_id == null ? "" : o.branch_id}"${v.office_id === o.id ? " selected" : ""}>${esc(o.name)}</option>`).join("")}</select></div></div>
      <div class="row2"><div><label for="hrr-des">Designation</label><input id="hrr-des" name="designation" list="hrr-deslist" value="${esc(v.designation || "")}" autocomplete="off" placeholder="Any designation">
        <datalist id="hrr-deslist">${designations.map(d => `<option value="${esc(d)}"></option>`).join("")}</datalist></div>
      <div><label for="hrr-emp">Employee</label><select id="hrr-emp" name="employee_id">${hrSiteSelect(emps, v.employee_id,
        e => `${e.full_name} (${e.code})`)}</select></div></div>
      <div class="row2"><div><label for="hrr-req">Attendance</label><select id="hrr-req" name="required">
        <option value="true"${v.required ? " selected" : ""}>Required</option><option value="false"${v.required ? "" : " selected"}>Not required</option></select></div>
      <div><label for="hrr-self">Self check-in</label><select id="hrr-self" name="self_service">
        <option value="true"${v.self_service ? " selected" : ""}>On</option><option value="false"${v.self_service ? "" : " selected"}>Off</option></select></div></div>
      <div class="row2"><div><label for="hrr-shift">Shift</label><select id="hrr-shift" name="shift_id">${hrSiteSelect(shifts, v.shift_id, s => s.name)}</select></div>
      <div><label for="hrr-mode">Attendance mode</label><select id="hrr-mode" name="attendance_mode">
        <option value=""${v.attendance_mode ? "" : " selected"}>Office default</option>
        <option value="office"${v.attendance_mode === "office" ? " selected" : ""}>Office</option>
        <option value="gps"${v.attendance_mode === "gps" ? " selected" : ""}>GPS</option>
        <option value="both"${v.attendance_mode === "both" ? " selected" : ""}>Office or GPS</option></select></div></div>
      <div class="row2"><div><label for="hrr-from">Effective from</label><input id="hrr-from" name="effective_from" type="date" value="${v.effective_from || ""}"></div>
      <div><label for="hrr-to">Effective to</label><input id="hrr-to" name="effective_to" type="date" value="${v.effective_to || ""}"></div></div>
      <div class="row2"><div><label for="hrr-prio">Priority (1 comes first)</label><input id="hrr-prio" name="priority" type="number" min="1" max="1000" value="${v.priority}"></div>
      <div><label for="hrr-active">Status</label><select id="hrr-active" name="active">
        <option value="true"${v.active ? " selected" : ""}>Active</option><option value="false"${v.active ? "" : " selected"}>Inactive</option></select></div></div>
      <label for="hrr-note">Note</label><input id="hrr-note" name="note" maxlength="200" value="${esc(v.note || "")}" autocomplete="off">
      <div class="note">Two active rules cannot target exactly the same people. Only one company-wide rule can exist at a time. Dates are inclusive and may be left open.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save rule</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
  const bSel = $("#hrr-branch"), oSel = $("#hrr-office");
  const syncOffices = () => {
    const want = bSel.value;
    $$("option[data-branch]", oSel).forEach(op => {
      op.hidden = !!(want && op.dataset.branch !== want);
    });
    const cur = oSel.selectedOptions[0];
    if (cur && cur.hidden) oSel.value = "";
  };
  bSel.addEventListener("change", syncOffices);
  oSel.addEventListener("change", () => {
    const br = oSel.selectedOptions[0] ? oSel.selectedOptions[0].dataset.branch : "";
    if (br) { bSel.value = br; syncOffices(); }
  });
  syncOffices();
}
async function saveHrRule(form) {
  const f = form.elements, err = $(".err", form);
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  err.textContent = "";
  const num = v => (v ? Number(v) : null);
  const body = {branch_id: num(f.branch_id.value), office_id: num(f.office_id.value),
                designation: f.designation.value.trim() || null,
                employee_id: num(f.employee_id.value),
                required: f.required.value === "true", self_service: f.self_service.value === "true",
                shift_id: num(f.shift_id.value), attendance_mode: f.attendance_mode.value || null,
                effective_from: f.effective_from.value || null, effective_to: f.effective_to.value || null,
                priority: Number(f.priority.value || 100), active: f.active.value === "true",
                note: f.note.value.trim() || null};
  if (body.effective_from && body.effective_to && body.effective_to < body.effective_from) {
    err.textContent = "The end date cannot be before the start date."; return;
  }
  if (!(body.priority >= 1 && body.priority <= 1000)) { err.textContent = "Priority must be between 1 and 1000."; return; }
  const res = await api(id ? `/api/hr/attendance-rules/${id}` : "/api/hr/attendance-rules",
                        {method: id ? "PATCH" : "POST", body});
  toast(res, res.ok ? (id ? "Rule updated" : "Rule created") : "Rule not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrSites();
}
async function hrRuleDelete(id) {
  const row = (state.hr.rules || []).find(r => r.id === Number(id));
  if (!confirm(`Delete attendance rule ${id}${row ? ` (${hrRuleTarget(row)})` : ""}? The employees it covers fall back to the next matching rule or the company default.`)) return;
  const res = await api(`/api/hr/attendance-rules/${id}`, {method: "DELETE"});
  toast(res, res.ok ? "Rule deleted" : "Rule not deleted");
  if (res.ok) hrSites();
}

/* ---------- HR masters: departments, holidays, leave types, salary ---------- */
const HR_MASTER_TABS = [["departments", "Departments"], ["holidays", "Holidays"],
  ["leave-types", "Leave types"], ["salary-components", "Salary components"],
  ["salary-structures", "Salary structures"]];
const HR_COMPONENT_CALC = {fixed: "Fixed amount", percent_basic: "% of basic",
                           percent_gross: "% of gross"};
const HR_STATUTORY_HEADS = [["pf", "Provident fund"], ["esi", "Employee state insurance"],
  ["pt", "Professional tax"], ["tds", "Tax deducted at source"]];
const hrHeadLabel = key => (HR_STATUTORY_HEADS.find(h => h[0] === key) || [key, key])[1];

async function hrMasterData() {
  const payroll = can("hr:payroll_prepare");
  const denied = {ok: false, status: 403, body: {detail: "Your role cannot read salary data."}};
  const [d, h, l, c, s, e, b, o] = await Promise.all([
    api("/api/hr/departments"), api("/api/hr/holidays"), api("/api/hr/leave/types"),
    payroll ? api("/api/hr/salary/components") : Promise.resolve(denied),
    payroll ? api("/api/hr/salary/structures") : Promise.resolve(denied),
    api("/api/hr/employees?page_size=200&sort=name"),
    api("/api/hr/branches"), api("/api/hr/offices")]);
  state.hr.masters = {
    departments: d.ok ? d.body : [],
    holidays: h.ok ? h.body : [],
    leaveTypes: l.ok ? l.body : [],
    components: c.ok ? c.body : [],
    structures: s.ok ? s.body : [],
    employees: e.ok ? e.body : [],
    branches: b.ok ? b.body : [],
    offices: o.ok ? o.body : [],
    salaryError: c.ok && s.ok ? null : detail(c.body || s.body),
    errors: {departments: d.ok ? null : detail(d.body), holidays: h.ok ? null : detail(h.body),
             leaveTypes: l.ok ? null : detail(l.body)}
  };
  return state.hr.masters;
}

async function hrMasters(tab = "departments") {
  const m = await hrMasterData();
  const writable = can("hr:write");
  const payroll = can("hr:payroll_prepare");
  const tabs = HR_MASTER_TABS.filter(([k]) =>
    (k !== "salary-components" && k !== "salary-structures") || payroll);
  if (!tabs.some(([k]) => k === tab)) tab = "departments";
  const body = tab === "holidays" ? hrMastersHolidays(m, writable)
    : tab === "leave-types" ? hrMastersLeaveTypes(m, writable)
    : tab === "salary-components" ? hrMastersComponents(m, writable && payroll)
    : tab === "salary-structures" ? hrMastersStructures(m, writable && payroll)
    : hrMastersDepartments(m, writable);
  openDrawer("HR masters",
    "Branches and locations live on their own screen; this screen holds the lists payroll, leave and attendance read from.", `
    <div class="note">Every change is audited. Codes cannot be changed; entries are retired with a status instead of deleted. No statutory rate is prefilled: enter the rate your payroll policy uses.</div>
    <div class="actions" style="margin-top:0">
      <button class="btn ghost" type="button" data-act="hr-sites">Branches &amp; locations</button>
      <button class="btn ghost" type="button" data-act="hr-masters" data-tab="${tab}">Refresh</button>
    </div>
    <div class="seg compact hr-tabs" role="group" aria-label="HR master">
      ${tabs.map(([k, label]) => `<button type="button" data-act="hr-masters-tab" data-tab="${k}" aria-pressed="${k === tab}">${esc(label)}</button>`).join("")}
    </div>
    ${body}`, true);
  $("#drawer").classList.add("hr-wide");
}

function hrMastersDepartments(m, writable) {
  const rows = (m.departments || []).map(d => `<tr>
    <td class="strong">${esc(d.name)}<small>${esc(d.code)}</small></td>
    <td><span class="chip ${d.status === "active" ? "ok" : "off"}">${esc(d.status)}</span></td>
    <td class="rowacts">${writable ? `<button class="btn ghost sm" type="button" data-act="hr-edit-dept" data-id="${d.id}">Edit</button>` : ""}</td></tr>`).join("");
  return `<div class="actions" style="margin-top:0">
      ${writable ? `<button class="btn" type="button" data-act="hr-new-dept">New department</button>` : ""}</div>
    ${m.errors.departments ? `<p class="gap-note">${esc(m.errors.departments)}</p>` : ""}
    <div class="tw"><table><thead><tr><th>Department</th><th>Status</th><th></th></tr></thead><tbody>
      ${rows || '<tr><td colspan="3" class="empty-row">No data yet: no departments configured.</td></tr>'}
    </tbody></table></div>
    <div class="note">The employee form suggests these names. A name typed exactly as a department is linked to it, so a rename follows through to those employees.</div>`;
}

function hrMastersHolidays(m, writable) {
  const branches = Object.fromEntries((m.branches || []).map(b => [b.id, b.name]));
  const offices = Object.fromEntries((m.offices || []).map(o => [o.id, o.name]));
  const rows = [...(m.holidays || [])].sort((a, b) => String(a.date).localeCompare(String(b.date)))
    .map(h => `<tr>
      <td>${esc(fmtDate(h.date))}</td><td class="strong">${esc(h.name)}</td>
      <td>${esc(branches[h.branch_id] || "All branches")}</td>
      <td>${esc(offices[h.location_id] || "All offices")}</td>
      <td class="rowacts">${writable ? `<button class="btn ghost sm" type="button" data-act="hr-edit-holiday" data-id="${h.id}">Edit</button>` : ""}</td></tr>`).join("");
  return `<div class="actions" style="margin-top:0">
      ${writable ? `<button class="btn" type="button" data-act="hr-new-holiday">New holiday</button>` : ""}</div>
    ${m.errors.holidays ? `<p class="gap-note">${esc(m.errors.holidays)}</p>` : ""}
    <div class="tw"><table><thead><tr><th>Date</th><th>Holiday</th><th>Branch</th><th>Office</th><th></th></tr></thead><tbody>
      ${rows || '<tr><td colspan="5" class="empty-row">No data yet: no holidays configured.</td></tr>'}
    </tbody></table></div>
    <div class="note">A holiday with no branch and no office applies to the whole company. Attendance already marked keeps the status it was recorded with.</div>`;
}

function hrMastersLeaveTypes(m, writable) {
  const rows = (m.leaveTypes || []).map(t => `<tr>
    <td class="strong">${esc(t.name)}<small>${esc(t.code)}</small></td>
    <td><span class="chip ${t.kind === "paid" ? "ok" : "off"}">${t.kind === "paid" ? "Paid" : "Unpaid"}</span></td>
    <td class="n">${qty(t.default_days)}</td>
    <td>${t.carry_forward ? `Yes${Number(t.max_carry_forward) > 0 ? ` · up to ${qty(t.max_carry_forward)}` : ""}` : "No"}</td>
    <td>${t.encashable ? "Yes" : "No"}</td>
    <td>${t.half_day_allowed ? "Yes" : "No"}</td>
    <td>${t.requires_document ? "Yes" : "No"}</td>
    <td><span class="chip ${t.active ? "ok" : "off"}">${t.active ? "active" : "inactive"}</span></td>
    <td class="rowacts">${writable ? `<button class="btn ghost sm" type="button" data-act="hr-edit-leave-type" data-id="${t.id}">Edit</button>` : ""}</td></tr>`).join("");
  return `<div class="actions" style="margin-top:0">
      ${writable ? `<button class="btn" type="button" data-act="hr-new-leave-type">New leave type</button>` : ""}</div>
    ${m.errors.leaveTypes ? `<p class="gap-note">${esc(m.errors.leaveTypes)}</p>` : ""}
    <div class="tw"><table><thead><tr><th>Leave type</th><th>Paid</th><th class="n">Days / year</th><th>Carry forward</th><th>Encashable</th><th>Half day</th><th>Document</th><th>Status</th><th></th></tr></thead><tbody>
      ${rows || '<tr><td colspan="9" class="empty-row">No data yet: no leave types configured.</td></tr>'}
    </tbody></table></div>
    <div class="note">A leave type is retired, never deleted, so approved leave keeps its label.</div>`;
}

function hrMastersComponents(m, writable) {
  const rows = (m.components || []).map(c => `<tr>
    <td class="strong">${esc(c.name)}<small>${esc(c.code)}</small></td>
    <td>${c.kind === "earning" ? "Earning" : "Deduction"}</td>
    <td>${esc(HR_COMPONENT_CALC[c.calc_type] || c.calc_type)}</td>
    <td class="n">${c.calc_type === "fixed" ? money(c.default_rate) : qty(c.default_rate) + "%"}</td>
    <td>${c.taxable ? "Yes" : "No"}</td>
    <td>${c.statutory ? esc(hrHeadLabel(c.statutory_head || "")) : "—"}</td>
    <td><span class="chip ${c.active ? "ok" : "off"}">${c.active ? "active" : "inactive"}</span></td>
    <td class="rowacts">${writable ? `<button class="btn ghost sm" type="button" data-act="hr-edit-component" data-id="${c.id}">Edit</button>` : ""}</td></tr>`).join("");
  return `<div class="actions" style="margin-top:0">
      ${writable ? `<button class="btn" type="button" data-act="hr-new-component">New component</button>` : ""}</div>
    ${m.salaryError ? `<p class="gap-note">${esc(m.salaryError)}</p>` : ""}
    <div class="tw"><table><thead><tr><th>Component</th><th>Type</th><th>Calculation</th><th class="n">Default rate</th><th>Taxable</th><th>Statutory head</th><th>Status</th><th></th></tr></thead><tbody>
      ${rows || '<tr><td colspan="8" class="empty-row">No data yet: no salary components configured.</td></tr>'}
    </tbody></table></div>
    <div class="note">The default rate is a starting value for a structure line, not a payroll rule by itself. Percent lines are calculated from basic or gross as shown.</div>`;
}

function hrMastersStructures(m, writable) {
  const emps = Object.fromEntries((m.employees || []).map(e => [e.id, e]));
  const rows = (m.structures || []).map(s => {
    const e = emps[s.employee_id];
    const lines = (s.lines || []).map(l => `${esc(l.component)} ${
      l.percent != null && l.percent !== "" ? esc(String(l.percent)) + "%" : money(l.amount)}`).join(" · ");
    return `<tr>
      <td class="strong">${esc(e ? e.full_name : `Employee ${s.employee_id}`)}<small>${esc(e ? e.code : "")}</small></td>
      <td>${esc(fmtDate(s.effective_from))}${s.effective_to ? `<small>to ${esc(fmtDate(s.effective_to))}</small>` : ""}</td>
      <td>${esc(s.payment_mode)}</td>
      <td><span class="chip ${s.status === "active" ? "ok" : "off"}">${esc(s.status)}</span></td>
      <td><small>${lines || "No lines"}</small></td></tr>`;
  }).join("");
  return `<div class="actions" style="margin-top:0">
      ${writable ? `<button class="btn" type="button" data-act="hr-new-structure">New salary structure</button>` : ""}</div>
    ${m.salaryError ? `<p class="gap-note">${esc(m.salaryError)}</p>` : ""}
    <div class="tw"><table><thead><tr><th>Employee</th><th>Effective</th><th>Payment</th><th>Status</th><th>Components</th></tr></thead><tbody>
      ${rows || '<tr><td colspan="5" class="empty-row">No data yet: no salary structure is assigned. Payroll skips every employee without one.</td></tr>'}
    </tbody></table></div>
    <div class="note">A new structure starts on the date you choose and closes the previous one the day before. Payroll uses the structure that covers the month.</div>`;
}

function hrDepartmentForm(id) {
  const m = state.hr.masters || {};
  const x = id ? (m.departments || []).find(d => d.id === Number(id)) : null;
  if (id && !x) { toast({ok: false, body: {detail: "Department not found"}}, "Department not loaded"); return; }
  const v = x || {id: "", code: "", name: "", status: "active"};
  openDrawer(x ? `Edit ${x.name}` : "New department",
    "The code is permanent. Retire a department by making it inactive; employees keep their history.", `
    <form id="hrDeptForm" data-id="${v.id || ""}" novalidate>
      <div class="row2"><div><label for="hrd-code">Department code</label><input id="hrd-code" name="code" value="${esc(v.code)}"${x ? " readonly" : ""} autocomplete="off"></div>
      <div><label for="hrd-name">Department name</label><input id="hrd-name" name="name" value="${esc(v.name)}" autocomplete="off"></div></div>
      ${x ? `<label for="hrd-status">Status</label><select id="hrd-status" name="status"><option value="active"${v.status === "active" ? " selected" : ""}>Active</option><option value="inactive"${v.status !== "active" ? " selected" : ""}>Inactive</option></select>` : ""}
      <div class="note">Renaming updates employees linked to this department. Free-text names on other employees are left alone.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save department</button><button class="btn ghost" type="button" data-act="hr-masters" data-tab="departments">Cancel</button></div>
    </form>`);
}
async function saveHrDepartment(form) {
  const f = form.elements, err = $(".err", form);
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  err.textContent = "";
  const body = {name: f.name.value.trim()};
  if (!id) body.code = f.code.value.trim().toUpperCase();
  else body.status = f.status.value;
  if ((body.name || "").length < 2) { err.textContent = "Enter the department name."; return; }
  if (!id && (body.code || "").length < 2) { err.textContent = "Enter a department code of at least two characters."; return; }
  const res = await api(id ? `/api/hr/departments/${id}` : "/api/hr/departments",
                        {method: id ? "PATCH" : "POST", body});
  toast(res, res.ok ? (id ? "Department updated" : "Department created") : "Department not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer();
  hrMasters("departments");
}

async function hrHolidayForm(id) {
  const m = state.hr.masters && state.hr.masters.branches ? state.hr.masters : await hrMasterData();
  const x = id ? (m.holidays || []).find(h => h.id === Number(id)) : null;
  if (id && !x) { toast({ok: false, body: {detail: "Holiday not found"}}, "Holiday not loaded"); return; }
  const v = x || {id: "", date: "", name: "", branch_id: null, location_id: null};
  const branches = m.branches || [];
  const offices = (m.offices || []).filter(o => !v.branch_id || o.branch_id === v.branch_id);
  openDrawer(x ? `Edit ${x.name}` : "New holiday",
    "Leave the branch and office empty for a company-wide holiday. A branch holiday covers its offices.", `
    <form id="hrHolidayForm" data-id="${v.id || ""}" novalidate>
      <div class="row2"><div><label for="hrh-date">Date</label><input id="hrh-date" name="date" type="date" value="${esc(v.date || "")}"></div>
      <div><label for="hrh-name">Holiday name</label><input id="hrh-name" name="name" value="${esc(v.name)}" autocomplete="off"></div></div>
      <div class="row2"><div><label for="hrh-branch">Branch</label><select id="hrh-branch" name="branch_id">${hrSiteSelect(branches, v.branch_id, b => b.name)}</select></div>
      <div><label for="hrh-office">Office</label><select id="hrh-office" name="location_id"><option value="">—</option>${offices.map(o => `<option value="${o.id}" data-branch="${o.branch_id == null ? "" : o.branch_id}"${v.location_id === o.id ? " selected" : ""}>${esc(o.name)}</option>`).join("")}</select></div></div>
      <div class="note">Attendance already marked keeps the status it was recorded with; the new date applies to future marking only.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save holiday</button><button class="btn ghost" type="button" data-act="hr-masters" data-tab="holidays">Cancel</button></div>
    </form>`);
  const bSel = $("#hrh-branch"), oSel = $("#hrh-office");
  const syncOffices = () => {
    const want = bSel.value;
    $$("option[data-branch]", oSel).forEach(op => {
      op.hidden = !!(want && op.dataset.branch !== want);
    });
    const cur = oSel.selectedOptions[0];
    if (cur && cur.hidden) oSel.value = "";
  };
  bSel.addEventListener("change", syncOffices);
  oSel.addEventListener("change", () => {
    const br = oSel.selectedOptions[0] ? oSel.selectedOptions[0].dataset.branch : "";
    if (br) { bSel.value = br; syncOffices(); }
  });
  syncOffices();
}
async function saveHrHoliday(form) {
  const f = form.elements, err = $(".err", form);
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  err.textContent = "";
  const body = {date: f.date.value, name: f.name.value.trim(),
                branch_id: f.branch_id.value ? Number(f.branch_id.value) : null,
                location_id: f.location_id.value ? Number(f.location_id.value) : null};
  if (!body.date) { err.textContent = "Choose the holiday date."; return; }
  if (body.name.length < 2) { err.textContent = "Enter the holiday name."; return; }
  const res = await api(id ? `/api/hr/holidays/${id}` : "/api/hr/holidays",
                        {method: id ? "PATCH" : "POST", body});
  toast(res, res.ok ? (id ? "Holiday updated" : "Holiday created") : "Holiday not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer();
  hrMasters("holidays");
}

function hrLeaveTypeForm(id) {
  const m = state.hr.masters || {};
  const x = id ? (m.leaveTypes || []).find(t => t.id === Number(id)) : null;
  if (id && !x) { toast({ok: false, body: {detail: "Leave type not found"}}, "Leave type not loaded"); return; }
  const v = x || {id: "", code: "", name: "", kind: "paid", requires_document: false,
                  default_days: 0, carry_forward: false, encashable: false,
                  max_carry_forward: 0, half_day_allowed: true, active: true};
  openDrawer(x ? `Edit ${x.name}` : "New leave type",
    "The days and flags here are the defaults. An application is still scoped and approved on the server.", `
    <form id="hrLeaveTypeForm" data-id="${v.id || ""}" novalidate>
      <div class="row2"><div><label for="hrlt-code">Code</label><input id="hrlt-code" name="code" value="${esc(v.code)}"${x ? " readonly" : ""} autocomplete="off"></div>
      <div><label for="hrlt-name">Name</label><input id="hrlt-name" name="name" value="${esc(v.name)}" autocomplete="off"></div></div>
      <div class="row2"><div><label for="hrlt-kind">Paid or unpaid</label><select id="hrlt-kind" name="kind"${x ? " disabled" : ""}><option value="paid"${v.kind === "paid" ? " selected" : ""}>Paid</option><option value="unpaid"${v.kind === "unpaid" ? " selected" : ""}>Unpaid</option></select></div>
      <div><label for="hrlt-days">Default days per year</label><input id="hrlt-days" name="default_days" type="number" min="0" step="0.5" value="${qty(v.default_days)}"></div></div>
      <div class="row2"><div><label for="hrlt-carry">Carry forward</label><select id="hrlt-carry" name="carry_forward"><option value="false"${v.carry_forward ? "" : " selected"}>No</option><option value="true"${v.carry_forward ? " selected" : ""}>Yes</option></select></div>
      <div><label for="hrlt-max">Maximum carried days</label><input id="hrlt-max" name="max_carry_forward" type="number" min="0" step="0.5" value="${qty(v.max_carry_forward)}"></div></div>
      <div class="row2"><div><label for="hrlt-encash">Encashable</label><select id="hrlt-encash" name="encashable"><option value="false"${v.encashable ? "" : " selected"}>No</option><option value="true"${v.encashable ? " selected" : ""}>Yes</option></select></div>
      <div><label for="hrlt-half">Half day allowed</label><select id="hrlt-half" name="half_day_allowed"><option value="true"${v.half_day_allowed ? " selected" : ""}>Yes</option><option value="false"${v.half_day_allowed ? "" : " selected"}>No</option></select></div></div>
      <div class="row2"><div><label for="hrlt-doc">Document required</label><select id="hrlt-doc" name="requires_document"><option value="false"${v.requires_document ? "" : " selected"}>No</option><option value="true"${v.requires_document ? " selected" : ""}>Yes</option></select></div>
      ${x ? `<div><label for="hrlt-active">Status</label><select id="hrlt-active" name="active"><option value="true"${v.active ? " selected" : ""}>Active</option><option value="false"${v.active ? "" : " selected"}>Inactive</option></select></div>` : `<div></div>`}</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save leave type</button><button class="btn ghost" type="button" data-act="hr-masters" data-tab="leave-types">Cancel</button></div>
    </form>`);
}
async function saveHrLeaveType(form) {
  const f = form.elements, err = $(".err", form);
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  err.textContent = "";
  const carry = f.carry_forward.value === "true";
  const maxCarry = Number(f.max_carry_forward.value || 0);
  if (!(Number(f.default_days.value) >= 0)) { err.textContent = "Default days cannot be negative."; return; }
  if (!(maxCarry >= 0)) { err.textContent = "The carry-forward cap cannot be negative."; return; }
  if (!carry && maxCarry > 0) { err.textContent = "Set carry forward to yes, or the cap back to zero."; return; }
  const body = {name: f.name.value.trim(), requires_document: f.requires_document.value === "true",
                default_days: f.default_days.value, carry_forward: carry,
                encashable: f.encashable.value === "true",
                max_carry_forward: carry ? maxCarry : 0,
                half_day_allowed: f.half_day_allowed.value === "true"};
  if (!id) { body.code = f.code.value.trim().toUpperCase(); body.kind = f.kind.value; }
  else body.active = f.active.value === "true";
  if (body.name.length < 2) { err.textContent = "Enter the leave type name."; return; }
  if (!id && body.code.length < 1) { err.textContent = "Enter a leave type code."; return; }
  const res = await api(id ? `/api/hr/leave/types/${id}` : "/api/hr/leave/types",
                        {method: id ? "PATCH" : "POST", body});
  toast(res, res.ok ? (id ? "Leave type updated" : "Leave type created") : "Leave type not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer();
  hrMasters("leave-types");
}

function hrComponentForm(id) {
  const m = state.hr.masters || {};
  const x = id ? (m.components || []).find(c => c.id === Number(id)) : null;
  if (id && !x) { toast({ok: false, body: {detail: "Salary component not found"}}, "Component not loaded"); return; }
  const v = x || {id: "", code: "", name: "", kind: "earning", calc_type: "fixed",
                  default_rate: 0, taxable: true, statutory: false, statutory_head: null,
                  sort_order: 0, active: true};
  openDrawer(x ? `Edit ${x.name}` : "New salary component",
    "A component is a rule, not an amount: the amount or percentage is set on each employee's structure.", `
    <form id="hrComponentForm" data-id="${v.id || ""}" novalidate>
      <div class="row2"><div><label for="hrc-code">Code</label><input id="hrc-code" name="code" value="${esc(v.code)}"${x ? " readonly" : ""} autocomplete="off"></div>
      <div><label for="hrc-name">Name</label><input id="hrc-name" name="name" value="${esc(v.name)}" autocomplete="off"></div></div>
      <div class="row2"><div><label for="hrc-kind">Type</label><select id="hrc-kind" name="kind"${x ? " disabled" : ""}><option value="earning"${v.kind === "earning" ? " selected" : ""}>Earning</option><option value="deduction"${v.kind === "deduction" ? " selected" : ""}>Deduction</option></select></div>
      <div><label for="hrc-calc">Calculation</label><select id="hrc-calc" name="calc_type"><option value="fixed"${v.calc_type === "fixed" ? " selected" : ""}>Fixed amount</option><option value="percent_basic"${v.calc_type === "percent_basic" ? " selected" : ""}>Percent of basic</option><option value="percent_gross"${v.calc_type === "percent_gross" ? " selected" : ""}>Percent of gross</option></select></div></div>
      <div class="row2"><div><label for="hrc-rate">Default rate</label><input id="hrc-rate" name="default_rate" type="number" min="0" step="0.01" value="${esc(String(v.default_rate))}"><div class="note" id="hrc-rate-note"></div></div>
      <div><label for="hrc-order">Sort order</label><input id="hrc-order" name="sort_order" type="number" min="0" step="1" value="${v.sort_order}"></div></div>
      <div class="row2"><div><label for="hrc-tax">Taxable</label><select id="hrc-tax" name="taxable"><option value="true"${v.taxable ? " selected" : ""}>Yes</option><option value="false"${v.taxable ? "" : " selected"}>No</option></select></div>
      <div><label for="hrc-stat">Statutory</label><select id="hrc-stat" name="statutory"><option value="false"${v.statutory ? "" : " selected"}>No</option><option value="true"${v.statutory ? " selected" : ""}>Yes</option></select></div></div>
      <label for="hrc-head">Statutory head</label><select id="hrc-head" name="statutory_head"><option value="">—</option>${HR_STATUTORY_HEADS.map(([k, label]) => `<option value="${k}"${v.statutory_head === k ? " selected" : ""}>${esc(label)}</option>`).join("")}</select>
      ${x ? `<label for="hrc-active">Status</label><select id="hrc-active" name="active"><option value="true"${v.active ? " selected" : ""}>Active</option><option value="false"${v.active ? "" : " selected"}>Inactive</option></select>` : ""}
      <div class="note">A deduction may carry a statutory head (PF, ESI, professional tax, TDS). An earning may not. No rate is inferred from the head.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save component</button><button class="btn ghost" type="button" data-act="hr-masters" data-tab="salary-components">Cancel</button></div>
    </form>`);
  const kind = $("#hrc-kind"), stat = $("#hrc-stat"), head = $("#hrc-head"), calc = $("#hrc-calc");
  const syncStat = () => {
    const earning = kind.value === "earning";
    stat.disabled = earning;
    head.disabled = earning;
    if (earning) { stat.value = "false"; head.value = ""; }
  };
  const syncRate = () => {
    $("#hrc-rate-note").textContent = calc.value === "fixed"
      ? "Rupees on a structure line." : "Percent used when a structure line leaves the percent empty.";
  };
  kind.addEventListener("change", syncStat);
  calc.addEventListener("change", syncRate);
  syncStat(); syncRate();
}
async function saveHrComponent(form) {
  const f = form.elements, err = $(".err", form);
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  err.textContent = "";
  const kind = f.kind.value;
  if (kind === "earning" && f.statutory.value === "true") {
    err.textContent = "Statutory is allowed only on a deduction."; return;
  }
  const statutory = kind === "deduction" && f.statutory.value === "true";
  const head = statutory ? (f.statutory_head.value || null) : null;
  if (statutory && !head) { err.textContent = "Choose the statutory head, or set statutory to no."; return; }
  if (!(Number(f.default_rate.value) >= 0)) { err.textContent = "The default rate cannot be negative."; return; }
  if (!(Number(f.sort_order.value) >= 0)) { err.textContent = "Sort order must be zero or more."; return; }
  const body = {name: f.name.value.trim(), calc_type: f.calc_type.value,
                default_rate: f.default_rate.value, taxable: f.taxable.value === "true",
                statutory, statutory_head: head, sort_order: Number(f.sort_order.value)};
  if (!id) { body.code = f.code.value.trim().toUpperCase(); body.kind = kind; }
  else body.active = f.active.value === "true";
  if (body.name.length < 2) { err.textContent = "Enter the component name."; return; }
  if (!id && body.code.length < 1) { err.textContent = "Enter a component code."; return; }
  const res = await api(id ? `/api/hr/salary/components/${id}` : "/api/hr/salary/components",
                        {method: id ? "PATCH" : "POST", body});
  toast(res, res.ok ? (id ? "Component updated" : "Component created") : "Component not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer();
  hrMasters("salary-components");
}

async function hrSalaryStructureForm(employeeId) {
  const m = await hrMasterData();
  const comps = (m.components || []).filter(c => c.active);
  const employees = m.employees || [];
  const empId = employeeId ? Number(employeeId) : null;
  if (!comps.length) {
    openDrawer("New salary structure",
      "Payroll reads an employee's active structure; without components there is nothing to put in one.", `
      <p class="gap-note">No data yet: no active salary components. Add at least one component first.</p>
      <div class="actions"><button class="btn" type="button" data-act="hr-masters" data-tab="salary-components">Open salary components</button></div>`);
    return;
  }
  const emp = empId ? employees.find(e => e.id === empId) : null;
  const rows = comps.map(c => {
    const pct = c.calc_type !== "fixed";
    return `<tr>
      <td><label class="chk"><input type="checkbox" name="comp" value="${c.id}" style="width:auto;margin-right:6px"> ${esc(c.name)}</label><small>${esc(c.code)} · ${c.kind === "earning" ? "Earning" : "Deduction"}</small></td>
      <td>${esc(HR_COMPONENT_CALC[c.calc_type] || c.calc_type)}</td>
      <td class="n">${pct
        ? `<input name="pct_${c.id}" type="number" min="0" max="100" step="0.01" value="${esc(String(c.default_rate))}" style="width:90px"> %`
        : `<input name="amt_${c.id}" type="number" min="0" step="0.01" value="${esc(String(c.default_rate))}" style="width:120px">`}</td></tr>`;
  }).join("");
  openDrawer("New salary structure",
    "A structure covers the month it starts in. Saving a later one closes the current structure the day before.", `
    <form id="hrStructureForm" data-emp="${empId || ""}" novalidate>
      ${emp
        ? `<div class="note">Employee: <b>${esc(emp.full_name)}</b> (${esc(emp.code)})</div>`
        : `<label for="hrs-emp">Employee</label><select id="hrs-emp" name="employee_id"><option value="">—</option>${employees.filter(e => e.status === "active").map(e => `<option value="${e.id}">${esc(e.full_name)} (${esc(e.code)})</option>`).join("")}</select>`}
      <div class="row2"><div><label for="hrs-from">Effective from</label><input id="hrs-from" name="effective_from" type="date"></div>
      <div><label for="hrs-mode">Payment mode</label><select id="hrs-mode" name="payment_mode"><option value="bank">Bank transfer</option><option value="cash">Cash</option><option value="cheque">Cheque</option></select></div></div>
      <h3>Components</h3>
      <div class="tw"><table><thead><tr><th>Component</th><th>Calculation</th><th class="n">Amount / percent</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="note">Tick only the components that apply. Amounts are in rupees; a percent line uses the percentage column. The values shown are the component defaults and can be changed for this employee.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save structure</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}
async function saveHrStructure(form) {
  const f = form.elements, err = $(".err", form);
  err.textContent = "";
  const empId = form.dataset.emp ? Number(form.dataset.emp) : Number(f.employee_id.value || 0);
  if (!empId) { err.textContent = "Choose the employee."; return; }
  if (!f.effective_from.value) { err.textContent = "Choose the effective date."; return; }
  const lines = [];
  for (const cb of form.querySelectorAll('input[name="comp"]:checked')) {
    const cid = Number(cb.value);
    const comp = (state.hr.masters.components || []).find(c => c.id === cid);
    if (!comp) continue;
    if (comp.calc_type === "fixed") {
      const input = f[`amt_${cid}`];
      const amount = Number(input.value);
      if (!(amount >= 0)) { err.textContent = `Enter the amount for ${comp.name}.`; return; }
      lines.push({component_id: cid, amount, percent: null});
    } else {
      const input = f[`pct_${cid}`];
      const percent = Number(input.value);
      if (!(percent >= 0 && percent <= 100)) { err.textContent = `Enter a percentage from 0 to 100 for ${comp.name}.`; return; }
      lines.push({component_id: cid, amount: 0, percent});
    }
  }
  if (!lines.length) { err.textContent = "Tick at least one component."; return; }
  const res = await api("/api/hr/salary/structures", {method: "POST",
    body: {employee_id: empId, effective_from: f.effective_from.value,
           payment_mode: f.payment_mode.value, lines}});
  toast(res, res.ok ? "Salary structure saved" : "Salary structure not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  const inProfile = state.hr.profile && state.hr.profile.employee.id === empId;
  closeDrawer();
  if (inProfile) { await hrProfile(empId); hrProfileDrawer("salary"); }
  else hrMasters("salary-structures");
}

async function hrAttendance() {
  const [a, o, pol] = await Promise.all([api(`/api/hr/attendance?from_date=${isoDay(0)}&to_date=${isoDay(0)}`),
    can("hr:read") ? api("/api/hr/offices") : Promise.resolve({ok: false, body: []}),
    can("hr:attendance_self") ? api("/api/hr/attendance-rules/resolve") : Promise.resolve({ok: false, body: null})]);
  const rows = a.ok ? a.body : [];
  const offices = o.ok ? o.body : [];
  const all = state.hr.employees || [];
  const eligible = all.filter(e => e.attendance_required !== false);
  const exempt = all.length - eligible.length;
  const policy = pol.ok ? pol.body : null;
  openDrawer("Attendance — today", "GPS is requested only for check-in/out and never tracked in the background.", `
    <div class="actions">
      ${can("hr:attendance_self") ? `<button class="btn" type="button" data-act="hr-checkin">Check in</button><button class="btn ghost" type="button" data-act="hr-checkout">Check out</button>` : ""}
      <button class="btn ghost" type="button" data-act="hr-refresh-att">Refresh</button></div>
    ${policy ? `<div class="note">Your policy: attendance ${policy.required ? "required" : "not required"} · self check-in ${policy.self_service ? "on" : "off"}${policy.attendance_mode ? ` · ${esc(policy.attendance_mode)} mode` : ""} · ${esc(policy.source)}.</div>` : ""}
    <div class="tw"><table><thead><tr><th>Employee</th><th>Status</th><th>Check-in</th><th>Check-out</th><th>Location</th><th>Late</th></tr></thead><tbody>
      ${rows.map(x => `<tr><td>${esc(x.employee)}<small>${esc(x.employee_code)}</small></td><td>${esc(x.status)}</td><td>${esc(fmtStamp(x.check_in))}</td><td>${esc(fmtStamp(x.check_out))}</td><td>${esc(x.geofence_result)}</td><td class="n">${x.late_minutes}</td></tr>`).join("") || '<tr><td colspan="6" class="empty-row">No attendance recorded today.</td></tr>'}
    </tbody></table></div>
    ${can("hr:attendance_manage") ? `<form id="hrManualForm" novalidate><h3>Manual attendance</h3>
      <div class="row2"><div><label>Employee</label><select name="employee_id">${eligible.map(e => `<option value="${e.id}">${esc(e.full_name)} (${esc(e.code)})</option>`).join("")}</select></div>
      <div><label>Date</label><input name="date" type="date" value="${isoDay(0)}"></div></div>
      <label>Status</label><select name="status"><option value="present">Present</option><option value="absent">Absent</option><option value="half_day">Half day</option><option value="paid_leave">Paid leave</option><option value="unpaid_leave">Unpaid leave</option><option value="od">On duty</option><option value="late">Late</option><option value="early_departure">Early departure</option></select>
      <label>Remarks (required)</label><input name="remarks" autocomplete="off">
      ${exempt ? `<div class="note">${exempt} employee(s) are exempt from attendance by policy and are not listed here. Change the rule under “Branches &amp; locations”.</div>` : ""}
      ${!eligible.length ? `<div class="note">No employee must mark attendance. Add an attendance rule before recording it manually.</div>` : ""}
      <div class="note">A manual entry is audited with your name, the old value and the new value.</div>
      <div class="err" role="alert"></div><div class="actions"><button class="btn" type="submit"${eligible.length ? "" : " disabled"}>Save manual attendance</button></div></form>` : ""}
    ${offices.length ? `<div class="note">Configured offices: ${offices.length}. Geofence validation runs on the server.</div>` : ""}`, true);
}
async function hrSelfPolicy() {
  const r = await api("/api/hr/attendance-rules/resolve");
  if (!r.ok) { toast(r, "Check-in not recorded"); return null; }
  return r.body;
}
async function hrCheckIn() {
  const policy = await hrSelfPolicy();
  if (!policy) return;
  if (!policy.required) {
    toast({ok: false, status: 409, body: {detail:
      `Attendance is not required for you (${policy.source}). Nothing was recorded.`}}, "Check-in not needed");
    return;
  }
  if (!policy.self_service) {
    toast({ok: false, status: 409, body: {detail:
      `Self check-in is switched off (${policy.source}). HR records your attendance.`}}, "Check-in not needed");
    return;
  }
  const body = {source: policy.attendance_mode === "gps" ? "gps" : "web"};
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
  const [a, e] = await Promise.all([api("/api/hr/od"),
    can("hr:read") ? api("/api/hr/employees?page_size=200") : Promise.resolve({ok: false, body: []})]);
  const rows = a.ok ? a.body : [], emps = e.ok ? e.body : [];
  openDrawer("On duty (OD)", "Approved OD is reflected in attendance and payroll.", `
    <form id="hrOdForm" novalidate><h3>New OD request</h3>
      <div class="row2">${emps.length ? `<div><label>Employee</label><select name="employee_id">${emps.map(x => `<option value="${x.id}">${esc(x.full_name)} (${esc(x.code)})</option>`).join("")}</select></div>` : ""}
      <div><label>Date</label><input name="date" type="date" value="${isoDay(0)}"></div></div>
      <div class="row2"><div><label>Visit type</label><input name="visit_type" placeholder="Customer visit / Field work" autocomplete="off"></div>
      <div><label>Destination</label><input name="destination" autocomplete="off"></div></div>
      <label>Purpose</label><input name="purpose" autocomplete="off">
      <div class="err" role="alert"></div><div class="actions"><button class="btn" type="submit">Submit OD request</button></div></form>
    <h3>Requests</h3><div class="tw"><table><thead><tr><th>Employee</th><th>Date</th><th>Visit</th><th>Purpose</th><th>Status</th><th>Remarks</th></tr></thead><tbody>
      ${rows.map(x => `<tr><td>${esc(x.employee)}</td><td>${esc(fmtDate(x.date))}</td><td>${esc(x.visit_type)}</td><td>${esc(x.purpose)}</td><td>${esc(x.status)}</td><td>${esc(x.decision_remarks || "–")}</td></tr>`).join("") || '<tr><td colspan="6" class="empty-row">No OD requests.</td></tr>'}</tbody></table></div>`, true);
}
async function saveHrOd(form) {
  const f = form.elements, err = $(".err", form), body = {date: f.date.value, visit_type: f.visit_type.value.trim(), purpose: f.purpose.value.trim(), destination: f.destination.value.trim() || null};
  if (f.employee_id) body.employee_id = Number(f.employee_id.value);
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
  const skipped = p.skipped || [];
  const skippedBlock = skipped.length ? `
    <div class="note"><b>${skipped.length} employee(s) have no payroll entry.</b>
      Payroll cannot pay them until each has an active salary structure for this month.
      <ul class="gaps">${skipped.map(s => `<li><b>${esc(s.code)}</b> ${esc(s.name)} <span>${esc(s.reason)}</span></li>`).join("")}</ul>
      <div class="actions"><button class="btn ghost" type="button" data-act="hr-masters" data-tab="salary-structures">Assign salary structures</button></div>
    </div>` : "";
  openDrawer(`Payroll ${p.year}-${String(p.month).padStart(2, "0")}`, `Status: ${p.status}.`, `
    <div class="tw"><table><thead><tr><th>Employee</th><th>Department</th><th class="n">Payable days</th><th class="n">LOP</th><th class="n">Gross (₹)</th><th class="n">Deductions (₹)</th><th class="n">Net (₹)</th><th></th></tr></thead><tbody>
      ${p.entries.map(e => `<tr><td>${esc(e.employee)}<small>${esc(e.employee_code)}</small></td><td>${esc(e.department || "–")}</td><td class="n">${qty(e.payable_days)}</td><td class="n">${qty(e.lop_days)}</td><td class="n">${money(e.gross)}</td><td class="n">${money(e.deductions)}</td><td class="n strong">${money(e.net)}</td>
        <td>${can("hr:confidential") ? `<a class="link-btn" href="/api/hr/payroll/entries/${e.id}/slip" download>Slip</a>` : ""}</td></tr>`).join("")}</tbody></table></div>
    ${skippedBlock}
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
  if (!res.ok) { toast(res, "Payroll not updated"); return; }
  if (act === "prepare" && (res.body.skipped || []).length) {
    // Open the register so the skipped names are in front of the person who prepared it.
    toast(res, `Payroll prepared; ${res.body.skipped.length} employee(s) skipped`);
    await hrPayrollOpen(id);
    return;
  }
  toast(res, "Payroll updated");
  await hrPayroll();
}

/* ---------- HR: monthly attendance ---------- */
const HR_MX = {
  present: ["P", "ok", "Present"], late: ["L", "warn", "Late"],
  early_departure: ["E", "warn", "Early departure"],
  half_day: ["H", "warn", "Half day"], paid_leave: ["L", "lev", "Paid leave"],
  unpaid_leave: ["U", "lev", "Unpaid leave"], od: ["O", "od", "On duty"],
  absent: ["A", "bad", "Absent"], weekly_off: ["W", "off", "Weekly off"],
  holiday: ["F", "off", "Holiday"], correction_pending: ["C", "warn", "Correction pending"]
};
function hrMxCell(c) {
  if (c.not_required) {
    return `<td class="hr-mx-c off" title="${esc(`${fmtDate(c.date)} · Not required by policy`)}">–</td>`;
  }
  const [code, cls, label] = HR_MX[c.status] || ["·", "none", "Not recorded"];
  const bits = [fmtDate(c.date), label];
  if (c.check_in) bits.push(`in ${fmtStamp(c.check_in)}`);
  if (c.check_out) bits.push(`out ${fmtStamp(c.check_out)}`);
  if (c.worked_minutes) bits.push(`${Math.floor(c.worked_minutes / 60)}h ${c.worked_minutes % 60}m`);
  if (c.late_minutes) bits.push(`${c.late_minutes} min late`);
  return `<td class="hr-mx-c ${cls}" title="${esc(bits.join(" · "))}">${code}</td>`;
}
async function hrMonthly() {
  const now = new Date();
  const fallback = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const month = ($("#hrMxMonth") && $("#hrMxMonth").value) || state.hr.mxMonth || fallback;
  state.hr.mxMonth = month;
  state.hr.mxDept = ($("#hrMxDept") && $("#hrMxDept").value) || state.hr.mxDept || "";
  const depts = [...new Set((state.hr.employees || []).map(e => e.department).filter(Boolean))].sort();
  const branches = state.hr.branches || [];
  const offices = (state.hr.offices || []).filter(o =>
    !state.hr.mxBranch || String(o.branch_id) === state.hr.mxBranch);
  openDrawer("Monthly attendance", "A blank day was not recorded. It is a gap, not an absence. A day the policy exempts is marked “not required”.", `
    <div class="toolbar">
      <label class="hr-field">Month <input id="hrMxMonth" type="month" value="${esc(state.hr.mxMonth)}"></label>
      <label class="hr-field">Department <select id="hrMxDept"><option value="">All departments</option>
        ${depts.map(d => `<option value="${esc(d)}"${d === state.hr.mxDept ? " selected" : ""}>${esc(d)}</option>`).join("")}</select></label>
      <label class="hr-field">Branch <select id="hrMxBranch"><option value="">All branches</option>
        ${branches.map(b => `<option value="${b.id}"${String(b.id) === state.hr.mxBranch ? " selected" : ""}>${esc(b.name)}</option>`).join("")}</select></label>
      <label class="hr-field">Office <select id="hrMxOffice"><option value="">All offices</option>
        ${offices.map(o => `<option value="${o.id}"${String(o.id) === state.hr.mxOffice ? " selected" : ""}>${esc(o.name)}</option>`).join("")}</select></label>
      <button class="btn ghost" type="button" data-act="hr-monthly-refresh">Refresh</button>
      <button class="btn ghost" type="button" data-act="hr-sheet">Sheet (PDF)</button>
    </div>
    <div class="hr-legend"><span class="hr-lg ok">P</span> present
      <span class="hr-lg warn">L</span> late <span class="hr-lg warn">H</span> half day
      <span class="hr-lg lev">L / U</span> leave <span class="hr-lg od">O</span> on duty
      <span class="hr-lg bad">A</span> absent <span class="hr-lg off">W / F</span> weekly off / holiday
      <span class="hr-lg off">–</span> not required
      <span class="hr-lg none">·</span> not recorded</div>
    <div id="hrMxBody" aria-live="polite"><p class="muted">Loading…</p></div>`, true);
  $("#drawer").classList.add("hr-wide");
  await loadHrMx();
}
async function loadHrMx() {
  const box = $("#hrMxBody");
  if (!box) return;
  const [y, m] = (state.hr.mxMonth || "").split("-").map(Number);
  if (!y || !m) { box.innerHTML = `<p class="muted">Choose a month.</p>`; return; }
  box.innerHTML = `<p class="muted">Loading…</p>`;
  const q = new URLSearchParams({year: y, month: m});
  if (state.hr.mxDept) q.set("department", state.hr.mxDept);
  if (state.hr.mxBranch) q.set("branch_id", state.hr.mxBranch);
  if (state.hr.mxOffice) q.set("office_id", state.hr.mxOffice);
  const r = await api(`/api/hr/attendance/monthly?${q}`);
  if (!r.ok) { box.innerHTML = `<p class="muted">${esc(detail(r.body))}</p>`; return; }
  const d = r.body;
  if (!d.employees.length) {
    box.innerHTML = `<div class="empty">No active employee matches this month and filter.</div>`;
    return;
  }
  const head = d.days.map(day => `<th class="hr-mx-d" scope="col">${Number(day.slice(8, 10))}</th>`).join("");
  const rows = d.employees.map(e => `<tr><th scope="row" class="hr-mx-name">${esc(e.name)}<small>${esc(e.code)}</small></th>
    ${e.calendar.map(hrMxCell).join("")}
    <td class="n">${qty(e.summary.present_days)}</td><td class="n">${qty(e.summary.leave_days)}</td>
    <td class="n">${e.summary.absent_days}</td><td class="n">${e.summary.missing_days}</td>
    <td class="n">${e.summary.not_required_days || 0}</td></tr>`).join("");
  const t = d.totals;
  box.innerHTML = `<div class="tw hr-mx-wrap"><table class="hr-mx">
      <thead><tr><th scope="col">Employee</th>${head}<th class="n">Present</th><th class="n">Leave</th><th class="n">Absent</th><th class="n">Not recorded</th><th class="n">Not required</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><th scope="row">All ${d.employees.length} employee(s)</th><td colspan="${d.days.length}"></td>
        <td class="n">${qty(t.present_days)}</td><td class="n">${qty(t.leave_days)}</td>
        <td class="n">${t.absent_days}</td><td class="n">${t.missing_days}</td>
        <td class="n">${t.not_required_days || 0}</td></tr></tfoot>
    </table></div>
    <p class="note">${t.missing_days} employee-day(s) have no attendance row. HR reports count them as gaps until they are recorded. ${t.not_required_days || 0} employee-day(s) are exempt by policy and are not gaps.</p>`;
}

/* ---------- HR: leave calendar ---------- */
async function hrCalendar() {
  const now = new Date();
  const fallback = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const month = ($("#hrCalMonth") && $("#hrCalMonth").value) || state.hr.calMonth || fallback;
  state.hr.calMonth = month;
  state.hr.calDept = ($("#hrCalDept") && $("#hrCalDept").value) || state.hr.calDept || "";
  const depts = [...new Set((state.hr.employees || []).map(e => e.department).filter(Boolean))].sort();
  openDrawer("Leave calendar", "Approved and pending leave for the month, with holidays. Nothing here is deducted until an application is approved.", `
    <div class="toolbar">
      <label class="hr-field">Month <input id="hrCalMonth" type="month" value="${esc(state.hr.calMonth)}"></label>
      <label class="hr-field">Department <select id="hrCalDept"><option value="">All departments</option>
        ${depts.map(d => `<option value="${esc(d)}"${d === state.hr.calDept ? " selected" : ""}>${esc(d)}</option>`).join("")}</select></label>
      <button class="btn ghost" type="button" data-act="hr-calendar-refresh">Refresh</button>
    </div>
    <div id="hrCalBody" aria-live="polite"><p class="muted">Loading…</p></div>`, true);
  await loadHrCal();
}
async function loadHrCal() {
  const box = $("#hrCalBody");
  if (!box) return;
  const [y, m] = (state.hr.calMonth || "").split("-").map(Number);
  if (!y || !m) { box.innerHTML = `<p class="muted">Choose a month.</p>`; return; }
  box.innerHTML = `<p class="muted">Loading…</p>`;
  const q = new URLSearchParams({year: y, month: m});
  if (state.hr.calDept) q.set("department", state.hr.calDept);
  const r = await api(`/api/hr/leave/calendar?${q}`);
  if (!r.ok) { box.innerHTML = `<p class="muted">${esc(detail(r.body))}</p>`; return; }
  const d = r.body;
  const daysIn = new Date(y, m, 0).getDate();
  const firstDow = new Date(y, m - 1, 1).getDay();
  const holidays = {};
  d.holidays.forEach(h => { holidays[h.date] = h.name; });
  const pad = n => String(n).padStart(2, "0");
  const cells = [];
  for (let i = 0; i < firstDow; i++) cells.push('<div class="hr-cal-cell blank"></div>');
  for (let day = 1; day <= daysIn; day++) {
    const iso = `${y}-${pad(m)}-${pad(day)}`;
    const dow = new Date(y, m - 1, day).getDay();
    const on = d.entries.filter(e => e.date_from <= iso && e.date_to >= iso);
    const approved = on.filter(e => e.status === "approved");
    const pending = on.filter(e => e.status === "pending");
    const names = approved.slice(0, 3).map(e => `<span class="hr-cal-chip">${esc(e.employee)}</span>`).join("");
    cells.push(`<div class="hr-cal-cell${dow === 0 || dow === 6 ? " wknd" : ""}${holidays[iso] ? " hol" : ""}">
      <div class="hr-cal-n">${day}${holidays[iso] ? `<span class="hr-cal-tag">${esc(holidays[iso])}</span>` : ""}</div>
      <div class="hr-cal-list">${names}
        ${approved.length > 3 ? `<span class="muted">+${approved.length - 3} more</span>` : ""}
        ${pending.length ? `<span class="hr-cal-chip pend">${pending.length} pending</span>` : ""}</div></div>`);
  }
  const entries = d.entries.map(e => `<tr><td class="strong">${esc(e.employee)}</td><td>${esc(e.leave_type)}</td>
    <td>${esc(fmtDate(e.date_from))} – ${esc(fmtDate(e.date_to))}</td><td class="n">${qty(e.days)}</td>
    <td><span class="chip ${e.status === "approved" ? "ok" : "warn"}">${esc(e.status)}</span></td></tr>`).join("");
  box.innerHTML = `<div class="hr-cal-grid" role="grid" aria-label="Leave calendar ${esc(state.hr.calMonth)}">
      ${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(x => `<div class="hr-cal-head" role="columnheader">${x}</div>`).join("")}
      ${cells.join("")}</div>
    <h3>Applications in ${esc(state.hr.calMonth)}</h3>
    <div class="tw"><table><thead><tr><th>Employee</th><th>Type</th><th>Dates</th><th class="n">Days</th><th>Status</th></tr></thead>
      <tbody>${entries || '<tr><td colspan="5" class="empty-row">No leave applications and no holidays in this month.</td></tr>'}</tbody></table></div>`;
}

/* ---------- HR: reports ---------- */
async function hrReports() {
  const [r, b, o] = await Promise.all([api("/api/hr/reports"), api("/api/hr/branches"),
                                       api("/api/hr/offices")]);
  const items = r.ok ? r.body : [];
  const branches = b.ok ? b.body : [];
  const offices = (o.ok ? o.body : []).filter(x =>
    !state.hr.repBranch || String(x.branch_id) === state.hr.repBranch);
  state.hr.repKey = state.hr.repKey || "headcount";
  openDrawer("HR reports", "Every report states its filters and lists missing data instead of filling it with zeroes.", `
    <div class="toolbar">
      <label class="hr-field">From <input id="hrRepFrom" type="date"></label>
      <label class="hr-field">To <input id="hrRepTo" type="date"></label>
      <label class="hr-field">Branch <select id="hrRepBranch"><option value="">All branches</option>
        ${branches.map(x => `<option value="${x.id}"${String(x.id) === state.hr.repBranch ? " selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>
      <label class="hr-field">Office <select id="hrRepOffice"><option value="">All offices</option>
        ${offices.map(x => `<option value="${x.id}"${String(x.id) === state.hr.repOffice ? " selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>
      <button class="btn ghost" type="button" data-act="hr-report-refresh">Refresh</button>
    </div>
    <div class="tw"><table><thead><tr><th>Report</th><th>Access</th><th></th></tr></thead><tbody>
      ${items.map(x => `<tr><td class="strong">${esc(x.title)}<small>${esc(x.key)}</small></td>
        <td>${x.available ? `<span class="chip ok">open</span>` : `<span class="chip warn">restricted</span>`}</td>
        <td class="rowacts">${x.available ? `<button class="btn ghost sm" type="button" data-act="hr-report-view" data-key="${esc(x.key)}">View</button>
          <button class="btn ghost sm" type="button" data-act="hr-report-file" data-key="${esc(x.key)}" data-format="csv">CSV</button>
          <button class="btn ghost sm" type="button" data-act="hr-report-file" data-key="${esc(x.key)}" data-format="pdf">PDF</button>` : `<span class="muted">Ask the Administrator for confidential HR rights.</span>`}</td></tr>`).join("") || '<tr><td colspan="3" class="empty-row">No reports for your role.</td></tr>'}
    </tbody></table></div>
    <div class="note">A branch or office filter narrows every report to the employees assigned there. The header of each report repeats the filter the server applied.</div>
    <div id="hrReportBody" aria-live="polite"><p class="muted">Choose View to open a report.</p></div>`, true);
  $("#drawer").classList.add("hr-wide");
  await hrReportView(state.hr.repKey);
}
function hrReportQuery() {
  const q = new URLSearchParams();
  const from = $("#hrRepFrom") && $("#hrRepFrom").value;
  const to = $("#hrRepTo") && $("#hrRepTo").value;
  if (from) q.set("from_date", from);
  if (to) q.set("to_date", to);
  if (state.hr.repBranch) q.set("branch_id", state.hr.repBranch);
  if (state.hr.repOffice) q.set("office_id", state.hr.repOffice);
  return q.toString();
}
async function hrReportView(key) {
  const box = $("#hrReportBody");
  if (!box) return;
  state.hr.repKey = key;
  box.innerHTML = `<p class="muted">Loading…</p>`;
  const r = await api(`/api/hr/reports/${encodeURIComponent(key)}?${hrReportQuery()}`);
  if (!r.ok) { box.innerHTML = `<p class="muted">${esc(detail(r.body))}</p>`; return; }
  const d = r.body;
  const filters = Object.entries(d.filters || {}).map(([k, v]) =>
    `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(v == null ? "–" : String(v))}</dd>`).join("");
  const summary = Object.entries(d.summary || {}).filter(([, v]) => v === null || typeof v !== "object")
    .map(([k, v]) => `<div class="hr-sum"><b>${esc(k.replace(/_/g, " "))}</b><span>${esc(v == null ? "No data yet" : String(v))}</span></div>`).join("");
  const head = (d.columns || []).map(c => `<th>${esc(c.label)}</th>`).join("");
  const rows = (d.rows || []).slice(0, 100).map(row =>
    `<tr>${d.columns.map(c => `<td>${esc(row[c.key] == null ? "–" : String(row[c.key]))}</td>`).join("")}</tr>`).join("");
  box.innerHTML = `<h3>${esc(d.title)}</h3>
    <dl class="hr-filters">${filters || "<dt>Filters</dt><dd>None</dd>"}</dl>
    <div class="hr-sums">${summary}</div>
    ${d.no_data ? `<div class="empty">No data yet for these filters.</div>` : `<div class="tw"><table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>
      ${d.rows.length > 100 ? `<p class="note">Showing the first 100 of ${d.rows.length} rows. Download the CSV for all of them.</p>` : ""}`}
    ${(d.gaps || []).length ? `<h3>No data yet</h3><ul class="hr-gaps">${d.gaps.map(g => `<li>${esc(g)}</li>`).join("")}</ul>` : ""}`;
}
function hrReportFile(key, format) {
  const q = hrReportQuery();
  const a = document.createElement("a");
  a.href = `/api/hr/reports/${encodeURIComponent(key)}?format=${format}${q ? "&" + q : ""}`;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
  toast({ok: true, status: 200}, `${key} ${format.toUpperCase()} requested`);
}

/* ---------- HR: announcements ---------- */
async function hrNotices() {
  const [a, n] = await Promise.all([api("/api/hr/announcements?include_inactive=true"),
    api("/api/hr/notifications?limit=5")]);
  const rows = a.ok ? a.body : [];
  const unread = n.ok ? n.body.unread : 0;
  openDrawer("Announcements", "Publishing notifies every active user with a linked employee record.", `
    ${can("hr:write") ? `<form id="hrNoticeForm" novalidate><h3>Publish an announcement</h3>
      <label>Title</label><input name="title" maxlength="200" autocomplete="off">
      <label>Message</label><textarea name="body" rows="4" maxlength="4000"></textarea>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Publish</button>
        <button class="btn ghost" type="button" data-act="hr-digest">Send daily digest now</button></div></form>` : ""}
    <h3>Published</h3>
    <div class="tw"><table><thead><tr><th>Title</th><th>Published</th><th>Status</th><th></th></tr></thead><tbody>
      ${rows.map(x => `<tr><td class="strong">${esc(x.title)}<small>${esc((x.body || "").slice(0, 140))}</small></td>
        <td>${esc(fmtStamp(x.published_at))}</td><td><span class="chip ${x.active ? "ok" : "off"}">${x.active ? "active" : "hidden"}</span></td>
        <td class="rowacts">${can("hr:write") && x.active ? `<button class="btn ghost sm" type="button" data-act="hr-notice-hide" data-id="${x.id}">Hide</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="4" class="empty-row">No announcements yet.</td></tr>'}
    </tbody></table></div>
    <p class="note">${unread ? `${unread} notification(s) are waiting in your bell.` : "Your notification bell is clear."}</p>`, true);
}
async function saveHrNotice(form) {
  const f = form.elements, err = $(".err", form);
  err.textContent = "";
  const body = {title: f.title.value.trim(), body: f.body.value.trim()};
  if (body.title.length < 3) { err.textContent = "Give the announcement a title."; return; }
  if (body.body.length < 3) { err.textContent = "Write the message."; return; }
  const res = await api("/api/hr/announcements", {method: "POST", body});
  toast(res, res.ok ? `Announcement published to ${res.body.notified} user(s)` : "Announcement not published");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrNotices();
}

/* ---------- HR: period locks ---------- */
async function hrLocks(unlockId) {
  const [l, p] = await Promise.all([api("/api/hr/period-locks"),
    can("hr:payroll_prepare") ? api("/api/hr/payroll/periods") : Promise.resolve({ok: false, body: []})]);
  const rows = l.ok ? l.body : [];
  const periods = p.ok ? p.body : [];
  const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const now = new Date();
  const scopes = can("hr:payroll_prepare") ? ["attendance", "payroll"] : ["attendance"];
  openDrawer("Period locks", "A locked month rejects attendance and payroll edits. Only the Administrator may unlock one.", `
    ${unlockId ? `<form id="hrUnlockForm" data-id="${unlockId}" novalidate><h3>Unlock period</h3>
      <label>Reason (kept in the audit trail)</label><input name="reason" minlength="5" maxlength="300" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Unlock</button><button class="btn ghost" type="button" data-act="hr-locks">Cancel</button></div></form>` : ""}
    <form id="hrLockForm" novalidate><h3>Lock a month</h3>
      <div class="row2">
        <div><label>Scope</label><select name="scope">${scopes.map(s => `<option value="${s}">${s === "attendance" ? "Attendance" : "Payroll"}</option>`).join("")}</select></div>
        <div><label>Year</label><input name="year" inputmode="numeric" value="${now.getFullYear()}"></div>
      </div>
      <div class="row2"><div><label>Month</label><select name="month">${months.map((m, i) => `<option value="${i + 1}"${i + 1 === now.getMonth() + 1 ? " selected" : ""}>${m}</option>`).join("")}</select></div>
      <div><label>Reason</label><input name="reason" minlength="5" maxlength="300" autocomplete="off"></div></div>
      <div class="note">Lock the previous month once it is reconciled. A payroll lock also freezes that month's payroll entries.</div>
      <div class="err" role="alert"></div><div class="actions"><button class="btn" type="submit">Lock month</button></div></form>
    <h3>Lock history</h3>
    <div class="tw"><table><thead><tr><th>Scope</th><th>Month</th><th>Status</th><th>Locked</th><th>Reason</th><th></th></tr></thead><tbody>
      ${rows.map(x => `<tr><td>${esc(x.scope)}</td><td>${months[x.month - 1]} ${x.year}</td>
        <td><span class="chip ${x.active ? "warn" : "off"}">${x.active ? "locked" : "open"}</span></td>
        <td>${esc(x.locked_by || "–")}<small>${esc(fmtStamp(x.locked_at))}</small></td>
        <td>${esc(x.reason || "–")}${x.unlock_reason ? `<small>Unlocked: ${esc(x.unlock_reason)}</small>` : ""}</td>
        <td class="rowacts">${x.active && state.user.role === "admin" ? `<button class="btn ghost sm" type="button" data-act="hr-lock-unlock" data-id="${x.id}">Unlock</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="6" class="empty-row">No period has been locked yet.</td></tr>'}
    </tbody></table></div>
    ${periods.length ? "" : ""}`, true);
}
async function saveHrLock(form) {
  const f = form.elements, err = $(".err", form);
  err.textContent = "";
  const body = {scope: f.scope.value, year: Number(f.year.value), month: Number(f.month.value),
                reason: f.reason.value.trim()};
  if (!(body.year >= 2000 && body.year <= 2100)) { err.textContent = "Enter a four-digit year."; return; }
  if (body.reason.length < 5) { err.textContent = "Give a reason of at least five characters."; return; }
  const res = await api("/api/hr/period-locks", {method: "POST", body});
  toast(res, res.ok ? `${body.scope} ${body.year}-${String(body.month).padStart(2, "0")} locked` : "Month not locked");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrLocks();
}
async function saveHrUnlock(form) {
  const f = form.elements, err = $(".err", form);
  err.textContent = "";
  const reason = f.reason.value.trim();
  if (reason.length < 5) { err.textContent = "Give a reason of at least five characters."; return; }
  const res = await api(`/api/hr/period-locks/${form.dataset.id}/unlock`, {method: "POST", body: {reason}});
  toast(res, res.ok ? "Period unlocked" : "Period not unlocked");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  hrLocks();
}

/* ---------- HR: employee import ---------- */
function hrImport() {
  state.hr.importText = null;
  openDrawer("Import employees", "Nothing is created until you confirm. The server validates every row and keeps an undo record.", `
    <p class="muted">Download the template, fill one employee per row, then choose the file. Bank and ID columns need confidential HR rights.</p>
    <div class="actions"><a class="btn ghost" href="/api/hr/employees/import-template.csv" download>Download template (CSV)</a></div>
    <label class="hr-field">CSV file <input id="hrImportFile" type="file" accept=".csv,text/csv"></label>
    <div class="actions"><button class="btn" type="button" data-act="hr-import-check">Check the file</button>
      <button class="btn hide" id="hrImportGo" type="button" data-act="hr-import-commit">Import valid rows</button></div>
    <div id="hrImportBody" aria-live="polite"></div>`, true);
}
async function hrImportCheck() {
  const box = $("#hrImportBody"), file = $("#hrImportFile") && $("#hrImportFile").files[0];
  if (!file) { toast({ok: false, status: 422, body: {detail: "Choose a CSV file first."}}, "No file"); return; }
  box.innerHTML = `<p class="muted">Checking…</p>`;
  const text = await file.text();
  state.hr.importText = text;
  const r = await api("/api/hr/employees/import", {method: "POST",
    body: {filename: file.name, csv_text: text, commit: false}});
  if (!r.ok) { box.innerHTML = `<p class="muted">${esc(detail(r.body))}</p>`; return; }
  const d = r.body;
  const errs = d.errors.map(e => `<li>Row ${e.row}${e.code ? ` (${esc(e.code)})` : ""}: ${esc(e.errors.join("; "))}</li>`).join("");
  box.innerHTML = `<div class="hr-sums"><div class="hr-sum"><b>Valid rows</b><span>${d.valid_rows}</span></div>
      <div class="hr-sum"><b>Rows with errors</b><span>${d.error_rows}</span></div></div>
    ${d.preview.length ? `<div class="tw"><table><thead><tr><th>Code</th><th>Name</th><th>Department</th></tr></thead><tbody>
      ${d.preview.map(p => `<tr><td>${esc(p.code)}</td><td>${esc(p.full_name)}</td><td>${esc(p.department || "–")}</td></tr>`).join("")}</tbody></table></div>` : ""}
    ${errs ? `<h3>Rows that cannot be imported</h3><ul class="hr-gaps">${errs}</ul>` : ""}
    <p class="note">${d.valid_rows ? "Check the preview, then choose Import valid rows. Rows with errors are left out." : "Nothing in this file can be imported yet."}</p>`;
  $("#hrImportGo").classList.toggle("hide", !d.valid_rows);
}
async function hrImportCommit() {
  const box = $("#hrImportBody");
  if (!state.hr.importText) { toast({ok: false, status: 422, body: {detail: "Check the file first."}}, "No file"); return; }
  const file = $("#hrImportFile") && $("#hrImportFile").files[0];
  const r = await api("/api/hr/employees/import", {method: "POST",
    body: {filename: file ? file.name : "import.csv", csv_text: state.hr.importText, commit: true}});
  toast(r, r.ok ? `Imported ${r.body.valid_rows} employee(s)` : "Import failed");
  if (!r.ok) { box.innerHTML = `<p class="muted">${esc(detail(r.body))}</p>`; return; }
  const d = r.body;
  box.innerHTML = `<div class="hr-sums"><div class="hr-sum"><b>Created</b><span>${d.valid_rows}</span></div>
      <div class="hr-sum"><b>Left out</b><span>${d.error_rows}</span></div></div>
    <p class="note">The import is recorded in the audit trail. If it was a mistake, undo it now.</p>
    <div class="actions"><button class="btn ghost" type="button" data-act="hr-import-undo" data-id="${d.batch_id}">Undo this import</button></div>`;
  $("#hrImportGo").classList.add("hide");
  openHr();
}
async function hrImportUndo(id) {
  const r = await api(`/api/hr/employees/import-batches/${id}/undo`, {method: "POST", body: {}});
  toast(r, r.ok ? "Import undone" : "Import not undone");
  if (r.ok) hrImport();
}

/* ---------- HR: notifications and self-service ---------- */
async function refreshHrUnread() {
  const el = $("#hrUnread");
  if (!el) return;
  const r = await api("/api/hr/notifications?limit=1");
  const n = r.ok ? r.body.unread : 0;
  el.textContent = n > 99 ? "99+" : String(n);
  el.classList.toggle("hide", !n);
}
async function hrNotifications() {
  const r = await api("/api/hr/notifications?limit=50");
  const items = r.ok ? r.body.items : [];
  const unread = r.ok ? r.body.unread : 0;
  openDrawer("Notifications", unread ? `${unread} unread` : "You are up to date.", `
    ${unread ? `<div class="actions"><button class="btn ghost" type="button" data-act="hr-notes-readall">Mark all read</button></div>` : ""}
    <ul class="hr-notes">${items.map(n => `<li class="hr-note${n.read_at ? "" : " unread"}">
      <b>${esc(n.title)}</b><p>${esc(n.body || "")}</p>
      <small>${esc(fmtStamp(n.created_at))}${n.link ? ` · <a href="${esc(n.link)}">Open</a>` : ""}</small>
      ${n.read_at ? "" : `<button class="btn ghost sm" type="button" data-act="hr-note-read" data-id="${n.id}">Mark read</button>`}
    </li>`).join("") || `<li class="muted">No notifications yet. Announcements and approvals appear here.</li>`}</ul>`, true);
  refreshHrUnread();
}
async function hrPayslips() {
  const r = await api("/api/hr/me/payslips");
  const rows = r.ok ? r.body : [];
  openDrawer("My payslips", "Only payslips released by payroll appear here. Each download is checked against your own employee record.", `
    ${rows.length ? `<div class="tw"><table><thead><tr><th>Period</th><th class="n">Gross (₹)</th><th class="n">Deductions (₹)</th><th class="n">Net (₹)</th><th></th></tr></thead><tbody>
      ${rows.map(x => `<tr><td class="strong">${x.year}-${String(x.month).padStart(2, "0")}</td>
        <td class="n">${money(x.gross)}</td><td class="n">${money(x.deductions)}</td><td class="n strong">${money(x.net)}</td>
        <td><a class="link-btn" href="/api/hr/me/payslips/${x.entry_id}" download>PDF</a></td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">No payslip has been released yet. Payroll releases them after a period is processed.</div>`}`, true);
}
async function renderHrSelf() {
  const box = $("#hrSelfBody");
  if (!box) return;
  const [a, p, n] = await Promise.all([
    api(`/api/hr/attendance?from_date=${isoDay(0)}&to_date=${isoDay(0)}`),
    api("/api/hr/me/payslips"),
    api("/api/hr/announcements?limit=3")]);
  const today = a.ok ? a.body : [];
  const slips = p.ok ? p.body.slice(0, 3) : [];
  const notes = n.ok ? n.body : [];
  box.innerHTML = `<h3>Today</h3>
    ${today.length ? `<div class="tw"><table><thead><tr><th>Status</th><th>Check-in</th><th>Check-out</th><th class="n">Worked</th></tr></thead><tbody>
      ${today.map(x => `<tr><td>${esc(x.status)}</td><td>${esc(fmtStamp(x.check_in))}</td><td>${esc(fmtStamp(x.check_out))}</td>
        <td class="n">${x.worked_minutes ? `${Math.floor(x.worked_minutes / 60)}h ${x.worked_minutes % 60}m` : "–"}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="muted">No attendance recorded today. Open “My attendance” to check in.</p>`}
    <h3>Recent payslips</h3>
    ${slips.length ? `<div class="tw"><table><thead><tr><th>Period</th><th class="n">Net (₹)</th><th></th></tr></thead><tbody>
      ${slips.map(x => `<tr><td>${x.year}-${String(x.month).padStart(2, "0")}</td><td class="n">${money(x.net)}</td>
        <td><a class="link-btn" href="/api/hr/me/payslips/${x.entry_id}" download>PDF</a></td></tr>`).join("")}</tbody></table></div>`
      : `<p class="muted">No payslip has been released yet.</p>`}
    <h3>Announcements</h3>
    ${notes.length ? `<ul class="hr-notes">${notes.map(x => `<li class="hr-note"><b>${esc(x.title)}</b><p>${esc(x.body || "")}</p>
      <small>${esc(fmtStamp(x.published_at))}</small></li>`).join("")}</ul>` : `<p class="muted">No announcements yet.</p>`}`;
}
/* ---------- sign-in page administration (Settings) ---------- */
const signinAdmin = {loaded: false, loading: false,
                     data: {banners: [], notices: [], contacts: [], legal: []}};

function signinAdminVisible() {
  return can("user:manage")
    && String((state.user && state.user.role) || "").trim().toLowerCase() === "admin";
}
function signinActiveChip(on) {
  return `<span class="chip ${on ? "ok" : "off"}">${on ? "Active" : "Hidden"}</span>`;
}
async function loadSigninAdmin(force) {
  if (signinAdmin.loading) return;
  signinAdmin.loading = true;
  const res = await api("/api/admin/sign-in");
  signinAdmin.loading = false;
  if (!res.ok) {
    $("#signinAdminBody").innerHTML = `<p class="muted">${esc(detail(res.body))}</p>`;
    return;
  }
  signinAdmin.data = res.body;
  signinAdmin.loaded = true;
  renderSigninAdmin();
  if (force) signinAdmin.loaded = true;
}
function renderSigninAdmin() {
  const d = signinAdmin.data;
  const banners = d.banners.length ? d.banners.map(b => `<tr>
      <td><img class="sa-thumb" src="${esc(b.image_url)}" alt=""></td>
      <td class="strong">${esc(b.title)}</td>
      <td>${b.link_url ? esc(b.link_url) : "–"}</td>
      <td class="n">${b.sort_order}</td>
      <td>${signinActiveChip(b.active)}</td>
      <td><div class="rowacts">
        <button class="btn sm ghost" type="button" data-act="signin-banner-edit" data-id="${b.id}">Edit</button>
        <button class="btn sm danger" type="button" data-act="signin-banner-delete" data-id="${b.id}">Delete</button>
      </div></td></tr>`).join("") : `<tr><td colspan="6" class="muted">No data yet.</td></tr>`;
  const notices = d.notices.length ? d.notices.map(n => `<tr>
      <td>${esc(fmtDate(n.date))}</td>
      <td class="strong">${esc(n.title)}</td>
      <td>${esc(n.body ? (n.body.length > 80 ? n.body.slice(0, 80) + "…" : n.body) : "–")}</td>
      <td>${signinActiveChip(n.active)}</td>
      <td><div class="rowacts">
        <button class="btn sm ghost" type="button" data-act="signin-notice-edit" data-id="${n.id}">Edit</button>
        <button class="btn sm danger" type="button" data-act="signin-notice-delete" data-id="${n.id}">Delete</button>
      </div></td></tr>`).join("") : `<tr><td colspan="5" class="muted">No data yet.</td></tr>`;
  const contacts = d.contacts.length ? d.contacts.map(c => `<tr>
      <td class="strong">${esc(c.label)}</td>
      <td>${esc(c.detail || "–")}</td>
      <td>${esc(c.phone || "–")}</td>
      <td>${esc(c.email || "–")}</td>
      <td class="n">${c.sort_order}</td>
      <td>${signinActiveChip(c.active)}</td>
      <td><div class="rowacts">
        <button class="btn sm ghost" type="button" data-act="signin-contact-edit" data-id="${c.id}">Edit</button>
        <button class="btn sm danger" type="button" data-act="signin-contact-delete" data-id="${c.id}">Delete</button>
      </div></td></tr>`).join("") : `<tr><td colspan="7" class="muted">No data yet.</td></tr>`;
  const legal = d.legal.length ? d.legal.map(l => `<tr>
      <td class="strong">${esc(l.title)}</td>
      <td><code>${esc(l.key)}</code></td>
      <td>${l.published && l.body ? `<span class="chip ok">Published</span>`
        : `<span class="chip off">Not published yet</span>`}</td>
      <td><div class="rowacts">
        <button class="btn sm ghost" type="button" data-act="signin-legal-edit" data-key="${esc(l.key)}">Edit text</button>
      </div></td></tr>`).join("") : `<tr><td colspan="4" class="muted">No data yet.</td></tr>`;
  $("#signinAdminBody").innerHTML = `
    <section class="sa-section">
      <h3 class="sa-h">Promotion banners
        <button class="btn sm" type="button" data-act="signin-banner-new">Upload banner</button></h3>
      <div class="tw"><table><thead><tr><th>Image</th><th>Title</th><th>Link</th><th class="n">Order</th><th>State</th><th></th></tr></thead>
        <tbody>${banners}</tbody></table></div>
      <p class="help">Active banners rotate on the sign-in page in sort order. JPEG, PNG or WebP, up to 2 MB.</p>
    </section>
    <section class="sa-section">
      <h3 class="sa-h">Notices
        <button class="btn sm" type="button" data-act="signin-notice-new">Add notice</button></h3>
      <div class="tw"><table><thead><tr><th>Date</th><th>Title</th><th>Text</th><th>State</th><th></th></tr></thead>
        <tbody>${notices}</tbody></table></div>
      <p class="help">The sign-in page shows the five most recent active notices.</p>
    </section>
    <section class="sa-section">
      <h3 class="sa-h">Help line
        <button class="btn sm" type="button" data-act="signin-contact-new">Add contact box</button></h3>
      <div class="tw"><table><thead><tr><th>Box</th><th>Detail</th><th>Phone</th><th>Email</th><th class="n">Order</th><th>State</th><th></th></tr></thead>
        <tbody>${contacts}</tbody></table></div>
      <p class="help">Each box needs a label and at least one of detail, phone or email.</p>
    </section>
    <section class="sa-section">
      <h3 class="sa-h">Legal pages</h3>
      <div class="tw"><table><thead><tr><th>Document</th><th>Key</th><th>State</th><th></th></tr></thead>
        <tbody>${legal}</tbody></table></div>
      <p class="help">The footer links open the published text. An unpublished page shows “Not published yet”.</p>
    </section>`;
}
function signinBannerForm(id) {
  const row = id ? signinAdmin.data.banners.find(b => b.id === id) : null;
  openDrawer(row ? "Edit banner" : "Upload banner",
    "A banner is an image file stored on this server. JPEG, PNG or WebP, up to 2 MB.", `
    <form id="signinBannerForm" data-id="${row ? row.id : ""}" novalidate>
      <label>Title <input name="title" maxlength="120" value="${esc(row ? row.title : "")}" required></label>
      <label>Link (optional) <input name="link_url" maxlength="500" value="${esc(row ? row.link_url || "" : "")}"
        placeholder="/ui/#/products or https://…"></label>
      <div class="row2">
        <label>Sort order <input name="sort_order" type="number" step="1" value="${row ? row.sort_order : 0}"></label>
        <div><label class="check" style="margin-bottom:0"><input type="checkbox" name="active" ${!row || row.active ? "checked" : ""}> Active</label></div>
      </div>
      <label>${row ? "Replace image (optional)" : "Image"}
        <input type="file" name="file" accept="image/jpeg,image/png,image/webp"${row ? "" : " required"}>
      </label>
      ${row ? `<div class="note">Leave the file empty to keep the current image. Choose a file to replace it.</div>` : ""}
      <div class="actions"><button class="btn" type="submit">${row ? "Save banner" : "Upload and save"}</button>
        <button class="btn ghost" type="button" data-act="close">Cancel</button></div>
      <div class="err"></div>
    </form>`);
}
async function signinUpload(path, fd) {
  let res;
  try { res = await fetch(path, {method: "POST", credentials: "same-origin", body: fd}); }
  catch (e) { return {status: 0, ok: false, body: {detail: "Cannot reach the server. Check the connection and try again."}}; }
  let body = null;
  try { body = await res.json(); } catch (e) { /* empty body */ }
  if (res.status === 401 && state.user) leave("Your session has ended. Sign in again.");
  return {status: res.status, ok: res.ok, body};
}
async function saveSigninBanner(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  const title = form.elements.title.value.trim();
  const link = form.elements.link_url.value.trim();
  const sort = Number(form.elements.sort_order.value || 0);
  const active = form.elements.active.checked;
  const file = form.elements.file.files[0];
  if (!title) { err.textContent = "Enter a title."; return; }
  if (!id && !file) { err.textContent = "Choose an image to upload."; return; }
  btn.disabled = true;
  let res;
  if (!id) {
    const fd = new FormData();
    fd.append("file", file); fd.append("title", title); fd.append("link_url", link);
    fd.append("sort_order", String(sort)); fd.append("active", String(active));
    res = await signinUpload("/api/admin/sign-in/banners", fd);
  } else {
    res = await api(`/api/admin/sign-in/banners/${id}`,
      {method: "PATCH", body: {title, link_url: link, sort_order: sort, active}});
    if (res.ok && file) {
      const fd = new FormData(); fd.append("file", file);
      res = await signinUpload(`/api/admin/sign-in/banners/${id}/image`, fd);
    }
  }
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, id ? "Banner saved" : "Banner uploaded");
  closeDrawer(); loadSigninAdmin(true);
}
async function deleteSigninBanner(id) {
  if (!confirm("Delete this banner and its image? The sign-in page stops showing it.")) return;
  const res = await api(`/api/admin/sign-in/banners/${id}`, {method: "DELETE"});
  toast(res, "Banner deleted");
  if (res.ok) loadSigninAdmin(true);
}
function signinNoticeForm(id) {
  const row = id ? signinAdmin.data.notices.find(n => n.id === id) : null;
  openDrawer(row ? "Edit notice" : "Add notice",
    "The sign-in page shows the date, title and text of active notices.", `
    <form id="signinNoticeForm" data-id="${row ? row.id : ""}" novalidate>
      <label>Title <input name="title" maxlength="160" value="${esc(row ? row.title : "")}" required></label>
      <label>Notice date <input name="notice_date" type="date" value="${row ? row.date : new Date().toISOString().slice(0, 10)}" required></label>
      <label>Text (optional) <textarea name="body" maxlength="2000" rows="5">${esc(row ? row.body || "" : "")}</textarea></label>
      <label class="check"><input type="checkbox" name="active" ${!row || row.active ? "checked" : ""}> Show on the sign-in page</label>
      <div class="actions"><button class="btn" type="submit">${row ? "Save notice" : "Add notice"}</button>
        <button class="btn ghost" type="button" data-act="close">Cancel</button></div>
      <div class="err"></div>
    </form>`);
}
async function saveSigninNotice(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  const title = form.elements.title.value.trim();
  const date = form.elements.notice_date.value;
  const body = form.elements.body.value.trim() || null;
  const active = form.elements.active.checked;
  if (!title) { err.textContent = "Enter a title."; return; }
  if (!date) { err.textContent = "Choose a date."; return; }
  btn.disabled = true;
  const payload = {title, body, notice_date: date, active};
  const res = id
    ? await api(`/api/admin/sign-in/notices/${id}`, {method: "PATCH", body: payload})
    : await api("/api/admin/sign-in/notices", {method: "POST", body: payload});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, id ? "Notice saved" : "Notice added");
  closeDrawer(); loadSigninAdmin(true);
}
async function deleteSigninNotice(id) {
  if (!confirm("Delete this notice? It disappears from the sign-in page.")) return;
  const res = await api(`/api/admin/sign-in/notices/${id}`, {method: "DELETE"});
  toast(res, "Notice deleted");
  if (res.ok) loadSigninAdmin(true);
}
function signinContactForm(id) {
  const row = id ? signinAdmin.data.contacts.find(c => c.id === id) : null;
  openDrawer(row ? "Edit contact box" : "Add contact box",
    "The boxes appear under the sign-in form. At least one contact value is required.", `
    <form id="signinContactForm" data-id="${row ? row.id : ""}" novalidate>
      <label>Box label <input name="label" maxlength="60" value="${esc(row ? row.label : "")}" required></label>
      <label>Detail (optional) <input name="detail" maxlength="160" value="${esc(row ? row.detail || "" : "")}"></label>
      <div class="row2">
        <label>Phone (optional) <input name="phone" maxlength="40" value="${esc(row ? row.phone || "" : "")}"></label>
        <label>Email (optional) <input name="email" maxlength="160" type="email" value="${esc(row ? row.email || "" : "")}"></label>
      </div>
      <div class="row2">
        <label>Sort order <input name="sort_order" type="number" step="1" value="${row ? row.sort_order : 0}"></label>
        <div><label class="check" style="margin-bottom:0"><input type="checkbox" name="active" ${!row || row.active ? "checked" : ""}> Show on the sign-in page</label></div>
      </div>
      <div class="actions"><button class="btn" type="submit">${row ? "Save box" : "Add box"}</button>
        <button class="btn ghost" type="button" data-act="close">Cancel</button></div>
      <div class="err"></div>
    </form>`);
}
async function saveSigninContact(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const id = form.dataset.id ? Number(form.dataset.id) : null;
  const label = form.elements.label.value.trim();
  const detail = form.elements.detail.value.trim() || null;
  const phone = form.elements.phone.value.trim() || null;
  const email = form.elements.email.value.trim() || null;
  const sort = Number(form.elements.sort_order.value || 0);
  const active = form.elements.active.checked;
  if (!label) { err.textContent = "Enter a box label."; return; }
  btn.disabled = true;
  const payload = {label, detail, phone, email, sort_order: sort, active};
  const res = id
    ? await api(`/api/admin/sign-in/contacts/${id}`, {method: "PATCH", body: payload})
    : await api("/api/admin/sign-in/contacts", {method: "POST", body: payload});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, id ? "Contact box saved" : "Contact box added");
  closeDrawer(); loadSigninAdmin(true);
}
async function deleteSigninContact(id) {
  if (!confirm("Delete this contact box? Its details disappear from the sign-in page.")) return;
  const res = await api(`/api/admin/sign-in/contacts/${id}`, {method: "DELETE"});
  toast(res, "Contact box deleted");
  if (res.ok) loadSigninAdmin(true);
}
function signinLegalForm(key) {
  const row = signinAdmin.data.legal.find(d => d.key === key)
    || {key, title: key === "privacy" ? "Privacy Policy" : "Terms & Conditions", body: "", published: false};
  openDrawer(row.title || "Legal page",
    "The published text opens from the sign-in footer. Nothing is invented: an empty page shows “Not published yet”.", `
    <form id="signinLegalForm" data-key="${esc(key)}" novalidate>
      <label>Title <input name="title" maxlength="120" value="${esc(row.title)}" required></label>
      <label>Text <textarea name="body" maxlength="20000" rows="14">${esc(row.body || "")}</textarea></label>
      <label class="check"><input type="checkbox" name="published" ${row.published ? "checked" : ""}> Publish this document</label>
      <div class="note">Publishing is refused while the text is empty.</div>
      <div class="actions"><button class="btn" type="submit">Save text</button>
        <button class="btn ghost" type="button" data-act="close">Cancel</button></div>
      <div class="err"></div>
    </form>`, true);
}
async function saveSigninLegal(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const key = form.dataset.key;
  const title = form.elements.title.value.trim();
  const body = form.elements.body.value.trim();
  const published = form.elements.published.checked;
  if (!title) { err.textContent = "Enter a title."; return; }
  btn.disabled = true;
  const res = await api(`/api/admin/sign-in/legal/${key}`,
    {method: "PATCH", body: {title, body: body || null, published}});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  toast(res, published ? "Document published" : "Document saved");
  closeDrawer(); loadSigninAdmin(true);
}

function renderSettings() {
  if (!$("#setEmprows")) return;
  const panel = $("#emailPanel");
  if (panel) {
    const showEmail = srAllowed() && featureOn("scheduled");
    panel.classList.toggle("hide", !showEmail);
    if (showEmail && !state.email.loaded && !state.email.loading) loadEmailSettings();
    if (showEmail) renderEmailSettings();
  }
  renderDbResetPanel();
  const signinPanel = $("#signinAdminPanel");
  if (signinPanel) {
    const showSignin = signinAdminVisible();
    signinPanel.classList.toggle("hide", !showSignin);
    if (showSignin && !signinAdmin.loaded && !signinAdmin.loading) loadSigninAdmin();
  }
  $("#setEmprows").innerHTML = state.employees.slice(0, 50).map(e => `<tr><td class="strong">${esc(e.code)}</td><td>${esc(e.full_name)}</td>
    <td>${esc(e.department || "–")}</td><td>${esc(e.designation || "–")}</td><td><span class="chip ${e.status === "active" ? "ok" : "off"}">${esc(e.status)}</span></td></tr>`).join("");
}

/* ---------- guarded database reset (four server-enforced steps) ---------- */
const dbReset = {status: null, loaded: false, run: null};

function dbResetPanelRow(c) {
  return `<li><span class="chip ${c.ok ? "ok" : "bad"}">${c.ok ? "Ready" : "Blocked"}</span>
    <b>${esc(c.key.replace(/_/g, " "))}</b> <span class="muted">${esc(c.detail)}</span></li>`;
}
async function renderDbResetPanel(force) {
  const panel = $("#dbResetPanel");
  if (!panel) return;
  const allowed = can("db:reset");
  panel.classList.toggle("hide", !allowed);
  if (!allowed) return;
  if (!dbReset.loaded || force) {
    const res = await api("/api/db-reset/status");
    if (!res.ok) {
      $("#dbResetBody").innerHTML = `<p class="muted">${esc(detail(res.body))}</p>`;
      return;
    }
    dbReset.status = res.body;
    dbReset.loaded = true;
  }
  const s = dbReset.status;
  $("#dbResetState").textContent = s.enabled ? "Administrator only." : "Switched off on this server.";
  const maintenance = s.maintenance
    ? `<div class="note bad">A reset run is in progress. Writes are paused until it finishes
       (started ${esc(fmtStamp(s.maintenance.started_at))}).</div>` : "";
  const locked = s.locked
    ? `<div class="note bad">Locked after ${s.max_attempts} wrong attempts until
       ${esc(fmtStamp(s.locked_until))}.</div>` : "";
  const off = s.enabled ? "" : `<div class="note">Database reset is switched off in this deployment.
    The Administrator can enable it with <b>DB_RESET_ENABLED=true</b> and the two backup directories.</div>`;
  $("#dbResetBody").innerHTML = `
    ${off}${locked}${maintenance}
    <ul class="hr-notes">${(s.prerequisites.checks || []).map(dbResetPanelRow).join("")}</ul>
    <div class="note">The reset never runs from this screen alone: the server takes two encrypted backups,
      verifies both by restoring them, and asks for a separate reset key within ten minutes.</div>
    <div class="actions"><button class="btn" type="button" data-act="reset-db"${s.enabled && !s.locked && !s.maintenance ? "" : " disabled"}>Start a reset…</button>
      ${s.maintenance ? `<button class="btn ghost" type="button" data-act="dbreset-cancel">Cancel the run and resume writes</button>` : ""}</div>
    ${(s.recent || []).length ? `<h3>Recent reset events</h3><div class="tw"><table><thead><tr><th>When</th><th>Event</th><th>Actor</th><th>Run</th></tr></thead><tbody>
      ${s.recent.slice().reverse().map(x => `<tr><td>${esc(fmtStamp(x.at))}</td><td>${esc(x.event)}</td><td>${esc(x.actor || "–")}</td><td>${esc(x.run_id || "–")}</td></tr>`).join("")}
    </tbody></table></div>` : ""}`;
}
function dbResetTime(iso) {
  if (!iso) return "–";
  try { return new Date(iso).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}); }
  catch (e) { return iso; }
}
async function dbResetOpen() {
  dbReset.run = null;
  if (!dbReset.loaded) {
    const res = await api("/api/db-reset/status");
    if (!res.ok) { toast(res, "Reset status not loaded"); return; }
    dbReset.status = res.body;
    dbReset.loaded = true;
  }
  const s = dbReset.status;
  openDrawer("Reset database",
    "Four steps, each enforced by the server. Nothing is cleared until the fourth succeeds.", `
    <div id="dbResetStep"></div>`, true);
  if (!s.enabled) {
    $("#dbResetStep").innerHTML = `<div class="note bad">Database reset is switched off on this server.
      The Administrator must set <b>DB_RESET_ENABLED=true</b>, two backup directories on different devices
      and <b>DB_RESET_ENCRYPTION_KEY</b>.</div>
      <div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`;
    return;
  }
  if (s.locked) {
    $("#dbResetStep").innerHTML = `<div class="note bad">Locked after ${s.max_attempts} wrong attempts
      until ${esc(fmtStamp(s.locked_until))}.</div>
      <div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`;
    return;
  }
  if (s.maintenance) {
    $("#dbResetStep").innerHTML = `<div class="note bad">A reset run is already in progress.</div>
      <div class="actions"><button class="btn ghost" type="button" data-act="dbreset-cancel">Cancel that run</button>
      <button class="btn ghost" type="button" data-act="close">Close</button></div>`;
    return;
  }
  dbResetStep1();
}
function dbResetStep1() {
  const s = dbReset.status || {phrase: ""};
  $("#dbResetStep").innerHTML = `
    <p class="sub">Step 1 of 4 — confirm who you are and what should be cleared.</p>
    <form id="dbResetForm1" novalidate>
      <label>Mode</label>
      <select name="mode">
        <option value="business" selected>Business data only — keeps users, employees, roles, settings and master data</option>
        <option value="full">Full reset — drops the schema, replays migrations, recreates the base Administrator</option>
      </select>
      <label>Your own login password</label>
      <input type="password" name="password" autocomplete="current-password">
      <label>Type the confirmation phrase exactly</label>
      <input name="phrase" autocomplete="off" spellcheck="false" placeholder="${esc(s.phrase || "RESET database")}">
      <div class="note">Database: <b>${esc(s.database || "–")}</b>. The phrase is case-sensitive.
        Three wrong attempts lock the feature.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Take the backups</button>
        <button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`;
}
async function dbResetBegin(form) {
  const f = form.elements, err = $(".err", form);
  err.textContent = "";
  const res = await api("/api/db-reset/begin", {method: "POST", body: {
    mode: f.mode.value, password: f.password.value, phrase: f.phrase.value}});
  if (!res.ok) { err.textContent = detail(res.body); toast(res, "Reset not started"); return; }
  dbReset.run = {id: res.body.run_id, token: res.body.token, mode: res.body.mode};
  dbResetStep2(res.body);
}
function dbResetStep2(begin) {
  const modeText = begin.mode === "full"
    ? "This mode deletes users, roles, employees and settings. Only the base Administrator survives."
    : "This mode clears documents, stock, payments and HR transactions; users, employees, roles, settings and master data stay.";
  $("#dbResetStep").innerHTML = `
    <p class="sub">Step 1 of 4 complete. Step 2 — take two encrypted backups on different devices.</p>
    <div class="note">${esc(modeText)} Writes are paused while the backup is taken.</div>
    <div class="note">Each copy is encrypted before it leaves the server. A copy without the key cannot be read.</div>
    <div class="err" role="alert"></div>
    <div class="actions"><button class="btn" type="button" data-act="dbreset-backup">Make the backups now</button>
      <button class="btn ghost" type="button" data-act="dbreset-cancel">Cancel the run</button></div>`;
}
async function dbResetBackup() {
  const step = $("#dbResetStep");
  if (!dbReset.run) return;
  step.querySelectorAll("button").forEach(b => b.disabled = true);
  const res = await api("/api/db-reset/backup", {method: "POST",
    body: {run_id: dbReset.run.id, token: dbReset.run.token}});
  if (!res.ok) {
    step.querySelector(".err").textContent = detail(res.body);
    step.querySelectorAll("button").forEach(b => b.disabled = false);
    return;
  }
  dbReset.run.token = res.body.token;
  const rows = Object.entries(res.body.backups || {}).map(([label, b]) => `<tr>
    <td>${esc(label)}</td><td>${esc(b.path)}</td><td><code>${esc(b.sha256.slice(0, 16))}…</code></td>
    <td class="n">${b.bytes.toLocaleString()}</td></tr>`).join("");
  step.innerHTML = `
    <p class="sub">Step 2 of 4 complete. Writes are now paused.</p>
    <div class="tw"><table><thead><tr><th>Copy</th><th>Encrypted file</th><th>SHA-256</th><th class="n">Bytes</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="note">${res.body.tables} tables, ${res.body.rows.toLocaleString()} rows captured.</div>
    <p class="sub">Step 3 of 4 — prove both copies can be restored.</p>
    <div class="err" role="alert"></div>
    <div class="actions"><button class="btn" type="button" data-act="dbreset-verify">Verify both backups</button>
      <button class="btn ghost" type="button" data-act="dbreset-cancel">Cancel the run</button></div>`;
}
async function dbResetVerify() {
  const step = $("#dbResetStep");
  if (!dbReset.run) return;
  step.querySelectorAll("button").forEach(b => b.disabled = true);
  step.querySelector(".err").textContent = "";
  const res = await api("/api/db-reset/verify", {method: "POST",
    body: {run_id: dbReset.run.id, token: dbReset.run.token}});
  if (!res.ok) {
    step.querySelector(".err").textContent = detail(res.body);
    step.querySelectorAll("button").forEach(b => b.disabled = false);
    return;
  }
  dbReset.run.token = res.body.token;
  const checks = res.body.checks.map(c => `<tr><td>${esc(c.backup)}</td><td>${esc(c.key.replace(/_/g, " "))}</td>
    <td><span class="chip ${c.ok ? "ok" : "bad"}">${c.ok ? "Passed" : "Failed"}</span></td>
    <td>${esc(c.detail)}</td></tr>`).join("");
  step.innerHTML = `
    <p class="sub">Step 3 of 4 complete. Both copies were decrypted, restored and compared.</p>
    <div class="tw"><table><thead><tr><th>Copy</th><th>Check</th><th>Result</th><th>Detail</th></tr></thead>
      <tbody>${checks}</tbody></table></div>
    <p class="sub">Step 4 of 4 — confirm with the separate reset key.</p>
    <form id="dbResetForm4" novalidate>
      <label>Reset key (not your password)</label>
      <input type="password" name="reset_key" autocomplete="off">
      <div class="note">This confirmation expires at ${esc(dbResetTime(res.body.expires_at))}
        (${res.body.confirm_minutes} minutes after verification). After that you must take a fresh backup.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn danger" type="submit">Reset the database now</button>
        <button class="btn ghost" type="button" data-act="dbreset-cancel">Cancel the run</button></div>
    </form>`;
}
async function dbResetExecute(form) {
  const err = $(".err", form);
  err.textContent = "";
  if (!dbReset.run) return;
  const full = dbReset.run.mode === "full";
  const question = full
    ? "Full reset: every user, employee, document and setting is removed and only the base Administrator is recreated. Continue?"
    : "Clear business data now? Documents, stock, payments and HR transactions are removed. This cannot be undone except from the verified backups.";
  if (!confirm(question)) return;
  form.querySelectorAll("button").forEach(b => b.disabled = true);
  const res = await api("/api/db-reset/execute", {method: "POST", body: {
    run_id: dbReset.run.id, token: dbReset.run.token, reset_key: form.elements.reset_key.value}});
  if (!res.ok) {
    err.textContent = detail(res.body);
    form.querySelectorAll("button").forEach(b => b.disabled = false);
    toast(res, "Reset not run");
    return;
  }
  dbReset.loaded = false;
  const r = res.body.result || {};
  $("#dbResetStep").innerHTML = `
    <p class="sub">The reset completed at ${esc(fmtStamp(res.body.completed_at))}.</p>
    <div class="note"><b>${esc(res.body.mode === "full" ? "Full reset" : "Business data only")}</b>
      ${res.body.mode === "full"
        ? "— the schema was rebuilt, migrations replayed and the base Administrator recreated."
        : `— ${r.tables_cleared || 0} tables cleared, ${(r.rows_cleared || 0).toLocaleString()} rows removed.`}</div>
    ${res.body.sign_in_again ? `<div class="note bad">Every session has ended. Sign in again as <b>admin</b>
      with your existing password; you will be asked to change it.</div>` : ""}
    <div class="note">The audit trail, both backup paths and the result are stored outside the database in the reset log.</div>
    <div class="actions"><button class="btn" type="button" data-act="close">Close</button></div>`;
  toast(res, "Database reset completed");
}
async function dbResetCancel() {
  const runId = (dbReset.run && dbReset.run.id)
    || (dbReset.status && dbReset.status.maintenance && dbReset.status.maintenance.run_id);
  if (!runId) { closeDrawer(); return; }
  if (!confirm("Cancel this reset run and let the application accept writes again?")) return;
  const res = await api("/api/db-reset/cancel", {method: "POST", body: {run_id: runId}});
  if (!res.ok) { toast(res, "The run was not cancelled"); return; }
  dbReset.run = null;
  dbReset.loaded = false;
  closeDrawer();
  renderDbResetPanel(true);
  toast(res, "Reset cancelled");
}

/* ---------- SMTP settings and the test composer ---------- */
async function loadEmailSettings(force) {
  if (!(srAllowed() && featureOn("scheduled")) || state.email.loading) return;
  if (state.email.loaded && !force) { renderEmailSettings(); return; }
  state.email.loading = true;
  state.email.error = null;
  if (!state.email.settings && $("#emBody")) $("#emBody").innerHTML = `<p class="muted">Loading email settings…</p>`;
  const [s, m] = await Promise.all([api("/api/email-settings"),
    api("/api/email-settings/test-messages?limit=20")]);
  state.email.loading = false;
  if (!s.ok) {
    state.email.error = detail(s.body);
    if ($("#emBody") && !$("#emailSettingsForm")) $("#emBody").innerHTML = `<p class="err">${esc(state.email.error)}</p>`;
    return;
  }
  state.email.settings = s.body;
  state.email.messages = m.ok ? m.body : [];
  state.email.loaded = true;
  renderEmailSettings();
}

function emailTypeLabel(key) {
  const t = state.email.settings && state.email.settings.message_types.find(x => x.key === key);
  return t ? t.label : key;
}

function applyEmailType(force) {
  const cfg = state.email.settings, sel = $("#em-type");
  if (!cfg || !sel) return;
  const meta = cfg.message_types.find(t => t.key === sel.value);
  if (!meta) return;
  if (force || !$("#em-subject").value.trim()) $("#em-subject").value = meta.subject;
  if (force || !$("#em-body").value.trim()) $("#em-body").value = meta.body;
}

function renderEmailSettings() {
  const cfg = state.email.settings;
  if (!cfg) return;
  if ($("#emailSettingsForm")) { renderEmailOutbox(); return; }
  const status = $("#emStatus");
  if (status) status.innerHTML = [
    `<span class="chip ${cfg.smtp_ready ? "ok" : "warn"}">${cfg.smtp_ready ? "SMTP configured" : "SMTP not configured"}</span>`,
    `<span class="chip ${cfg.enabled ? "ok" : "off"}">${cfg.enabled ? "Sending enabled" : "Sending off"}</span>`,
    `<span class="chip ${cfg.mode === "live" ? "warn" : "ok"}">${cfg.mode === "live" ? "Live mode" : "Test mode"}</span>`,
    `<span class="chip ${cfg.password_set ? "ok" : "off"}">${cfg.password_set ? "Password stored" : "No password"}</span>`,
    cfg.password_unreadable ? '<span class="chip bad">Saved password cannot be read: enter it again</span>' : ""
  ].join(" ");
  const typeOpts = cfg.message_types.map(t => `<option value="${esc(t.key)}">${esc(t.label)}</option>`).join("");
  $("#emBody").innerHTML = `
    ${cfg.stored ? "" : '<div class="note">No settings have been saved here yet, so the deployment environment is in use. Saving this form overrides it.</div>'}
    <form id="emailSettingsForm" novalidate>
      <div class="row2"><div><label for="em-host">SMTP host</label><input id="em-host" name="host" value="${esc(cfg.host)}" placeholder="smtp.example.com" autocomplete="off"></div>
      <div><label for="em-port">Port</label><input id="em-port" name="port" type="number" min="1" max="65535" value="${Number(cfg.port) || 587}"></div></div>
      <div class="row2"><div><label for="em-security">Connection security</label><select id="em-security" name="security">
          <option value="none"${cfg.security === "none" ? " selected" : ""}>None</option>
          <option value="starttls"${cfg.security === "starttls" ? " selected" : ""}>STARTTLS</option>
          <option value="ssl"${cfg.security === "ssl" ? " selected" : ""}>SSL/TLS</option></select></div>
        <div><label for="em-enabled">Sending</label><select id="em-enabled" name="enabled">
          <option value="0"${cfg.enabled ? "" : " selected"}>Switched off</option>
          <option value="1"${cfg.enabled ? " selected" : ""}>Enabled</option></select></div></div>
      <div class="row2"><div><label for="em-mode">Delivery mode</label><select id="em-mode" name="mode">
          <option value="test"${cfg.mode === "test" ? " selected" : ""}>Test mode: every message is a test</option>
          <option value="live"${cfg.live_allowed ? "" : " disabled"}${cfg.mode === "live" ? " selected" : ""}>Live mode (deployment approval required)</option></select></div><div></div></div>
      <label for="em-user">SMTP username</label><input id="em-user" name="username" value="${esc(cfg.username)}" autocomplete="off">
      <label for="em-pass">SMTP password</label><input id="em-pass" name="password" type="password" autocomplete="new-password"
        placeholder="${cfg.password_set ? "Stored: leave blank to keep it" : "Not set"}">
      <p class="sub" style="margin:6px 0 0">The password is stored encrypted and never shown again.
        <label style="display:inline;margin:0"><input id="em-clear" type="checkbox" style="width:auto;margin:0 4px 0 8px">Remove the saved password</label></p>
      <div class="row2"><div><label for="em-from">From address</label><input id="em-from" name="from_address" type="email" value="${esc(cfg.from_address)}" placeholder="reports@example.com"></div>
        <div><label for="em-reply">Reply-To</label><input id="em-reply" name="reply_to" type="email" value="${esc(cfg.reply_to)}" placeholder="Optional"></div></div>
      <div class="row2"><div><label for="em-test-to">Default test To</label><input id="em-test-to" name="test_to" value="${esc(cfg.test_to)}" placeholder="Administrator address"></div>
        <div><label for="em-test-cc">Default test CC</label><input id="em-test-cc" name="test_cc" value="${esc(cfg.test_cc)}" placeholder="Optional"></div></div>
      <div class="note">Messages are always test messages: the subject carries [TEST], and only the addresses above are used.
        Live delivery also needs the deployment to be approved for it; until then the server keeps test mode.
        ${cfg.live_allowed ? "" : "Live mode is not approved for this deployment."}</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save SMTP settings</button>
        <button class="btn ghost" type="button" data-act="email-reload">Reload</button></div>
    </form>
    <h3 style="margin-top:22px">Send a test email</h3>
    <form id="emailTestForm" novalidate>
      <div class="row2"><div><label for="em-type">Message type</label><select id="em-type" name="message_type">${typeOpts}</select></div>
        <div><label for="em-deliver">What happens</label><select id="em-deliver" name="deliver">
          <option value="0">Dry run: save only, no SMTP</option>
          <option value="1">Deliver through SMTP</option></select></div></div>
      <div class="row2"><div><label for="em-to">To</label><input id="em-to" name="to" value="${esc(cfg.test_to || cfg.suggested_to)}" placeholder="name@example.com"></div>
        <div><label for="em-cc">CC</label><input id="em-cc" name="cc" value="${esc(cfg.test_cc)}" placeholder="Optional"></div></div>
      <label for="em-subject">Subject</label><input id="em-subject" name="subject" maxlength="250" autocomplete="off">
      <label for="em-body">Message body</label><textarea id="em-body" name="body" rows="5"></textarea>
      <div class="note">A dry run stores the exact message below and opens no connection. Switching to “Deliver” uses the saved SMTP settings.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Send test email</button></div>
    </form>
    <h3 style="margin-top:22px">Recent test messages</h3>
    <div class="tw"><table>
      <thead><tr><th>When</th><th>Type</th><th>To</th><th>Subject</th><th>How</th><th>Status</th><th>Error</th></tr></thead>
      <tbody id="emOutRows"></tbody>
    </table></div>
    <div class="empty hide" id="emOutEmpty"></div>`;
  applyEmailType(false);
  renderEmailOutbox();
}

function renderEmailOutbox() {
  const body = $("#emOutRows");
  if (!body) return;
  body.innerHTML = state.email.messages.map(m => `<tr>
    <td>${esc(fmtStamp(m.created_at))}</td><td>${esc(emailTypeLabel(m.message_type))}</td>
    <td>${esc(m.to)}${m.cc ? `<small>CC ${esc(m.cc)}</small>` : ""}</td>
    <td>${esc(m.subject)}</td><td>${m.mode === "smtp" ? "SMTP" : "Dry run"}</td>
    <td><span class="chip ${m.status === "sent" ? "ok" : m.status === "captured" ? "warn" : "bad"}">${esc(m.status)}</span></td>
    <td>${m.error ? esc(m.error) : "–"}</td></tr>`).join("");
  empty($("#emOutEmpty"), !state.email.messages.length, "No test email has been sent yet.", "");
}

async function saveEmailSettings(f) {
  const err = $(".err", f), btn = $("button[type=submit]", f);
  err.textContent = "";
  btn.disabled = true;
  const res = await api("/api/email-settings", {method: "PUT", body: {
    enabled: $("#em-enabled").value === "1", mode: $("#em-mode") ? $("#em-mode").value : "test",
    host: $("#em-host").value.trim(), port: Number($("#em-port").value) || 0,
    security: $("#em-security").value, username: $("#em-user").value.trim(),
    password: $("#em-pass").value || null, clear_password: $("#em-clear").checked,
    from_address: $("#em-from").value.trim(), reply_to: $("#em-reply").value.trim(),
    test_to: $("#em-test-to").value.trim(), test_cc: $("#em-test-cc").value.trim()}});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  state.email.settings = res.body;
  $("#emBody").innerHTML = "";
  renderEmailSettings();
  toast(res, "SMTP settings saved");
}

async function sendEmailTest(f) {
  const err = $(".err", f), btn = $("button[type=submit]", f);
  err.textContent = "";
  btn.disabled = true;
  const res = await api("/api/email-settings/test", {method: "POST", body: {
    message_type: $("#em-type").value, to: $("#em-to").value.trim(),
    cc: $("#em-cc").value.trim(), subject: $("#em-subject").value.trim(),
    body: $("#em-body").value, deliver: $("#em-deliver").value === "1"}});
  btn.disabled = false;
  if (!res.ok) { err.textContent = detail(res.body); return; }
  const made = res.body;
  state.email.messages = [made, ...state.email.messages].slice(0, 20);
  renderEmailOutbox();
  toast(res, made.status === "sent" ? "Test email sent"
    : made.status === "captured" ? "Dry run saved; no email was sent"
    : `Not sent: ${made.error || "SMTP refused the message"}`);
}

function renderProducts() {
  const p = state.plist;
  // Until the server-paged list has loaded, fall back to the shared cache the
  // forms already use. Once loaded, the table shows exactly one server page.
  const rows = p.loaded ? p.rows : state.products.slice(0, p.size);
  $("#prows").innerHTML = rows.map(x => `<tr><td>${x.hsn ? esc(x.hsn) : '<span class="chip warn">Missing HSN</span>'}</td>
    <td class="strong sku">${esc(x.sku)}</td><td>${esc(x.name)}</td>
    <td>${x.category || x.brand ? `${x.category ? esc(x.category) : "—"}${x.brand ? `<small>${esc(x.brand)}</small>` : ""}` : "—"}</td>
    <td>${esc(x.pack_size)}</td>
    <td class="n">${money(x.mrp)}</td>
    <td class="n">${x.reorder_level != null ? esc(qty(x.reorder_level)) : '<span class="muted">Not set</span>'}</td>
    <td><span class="chip ${x.status === "active" ? "ok" : "off"}">${esc(x.status)}</span></td>
    <td class="rowacts"><button class="btn ghost sm" type="button" data-act="open-product" data-id="${x.id}">Open</button>
      <button class="btn ghost sm" type="button" data-act="edit-product" data-id="${x.id}">Edit</button>
      <button class="btn ghost sm" type="button" data-act="save-product" data-id="${x.id}">Save</button></td></tr>`).join("");
  const pager = $("#ppager");
  pager.innerHTML = p.loaded ? pagerHtml(p) : "";
  pager.classList.toggle("busy", p.loading);
  // The server sorts by a whitelisted column; the header says which one is live.
  $$("#v-products th[data-col]").forEach(th => {
    const on = th.dataset.col === p.sort;
    th.setAttribute("aria-sort", on ? (p.direction === "asc" ? "ascending" : "descending") : "none");
    const mark = $(".sort-mark", th);
    if (mark) mark.textContent = on ? (p.direction === "asc" ? " ▲" : " ▼") : "";
  });
  const filtered = !!(p.q || p.status);
  empty($("#pempty"), p.loaded && !rows.length,
    filtered ? "No product matches these filters." : "No products yet.",
    filtered ? "Change the search or status, or clear the filters."
      : (can("product:write") ? " Select “New product” to add the first one." : ""));
}

async function loadProductList(page) {
  const p = state.plist;
  if (!can("product:read")) return;
  if (page != null) p.page = Math.max(1, Number(page) || 1);
  const tok = ++p.seq;
  p.loading = true;
  $("#ppager").classList.add("busy");
  const qs = new URLSearchParams({page: String(p.page), page_size: String(p.size),
                                 sort: p.sort, direction: p.direction});
  if (p.q) qs.set("q", p.q);
  if (p.status) qs.set("status", p.status);
  const res = await apiPage(`/api/products?${qs}`);
  if (tok !== p.seq) return;                    // a newer request took over
  p.loading = false;
  if (!res.ok) {
    p.loaded = true; p.rows = []; p.total = null;
    toast(res, "Products not loaded");
    renderProducts(); renderHead();
    return;
  }
  p.rows = Array.isArray(res.body) ? res.body : [];
  p.total = res.total;
  p.loaded = true;
  // A narrower filter or a deletion can strand the view past the last page.
  if (p.total != null && !p.rows.length && p.page > 1) {
    p.page = Math.max(1, Math.ceil(p.total / p.size));
    return loadProductList(p.page);
  }
  renderProducts(); renderHead();
}

function productSort(key) {
  const p = state.plist;
  if (!key) return;
  if (p.sort === key) p.direction = p.direction === "asc" ? "desc" : "asc";
  else { p.sort = key; p.direction = "asc"; }
  loadProductList(1);
}

function productListPage(to) {
  const p = state.plist;
  if (p.total == null) return;
  const pages = Math.max(1, Math.ceil(p.total / p.size));
  const target = to === "first" ? 1 : to === "last" ? pages
    : to === "prev" ? p.page - 1 : p.page + 1;
  const next = Math.min(pages, Math.max(1, target));
  if (next !== p.page || p.loading) loadProductList(next);
}

async function exportProductsCsv() {
  const p = state.plist;
  const qs = new URLSearchParams();
  if (p.q) qs.set("q", p.q);
  if (p.status) qs.set("status", p.status);
  // Export covers every matching row, not just the page on screen.
  const res = await api(`/api/products${qs.toString() ? "?" + qs : ""}`);
  if (!res.ok) { toast(res, "Products not exported"); return; }
  const rows = Array.isArray(res.body) ? res.body : [];
  const csv = [["HERBANOVA product master"], ["Exported", fmtStamp(new Date().toISOString())],
    ["Search", p.q || "all"], ["Status", p.status || "all"], ["Rows", String(rows.length)],
    ["HSN code", "SKU", "Name", "Category", "Brand", "Pack size", "MRP (INR)",
     "Reorder level", "Status"]];
  rows.forEach(x => csv.push([x.hsn || "", x.sku, x.name, x.category || "", x.brand || "",
    x.pack_size, x.mrp, x.reorder_level ?? "", x.status]));
  downloadCsv(`HERBANOVA_Products_${isoDay(0)}.csv`, csv);
  toast({ok: true, status: "200"}, `Exported ${plural(rows.length, "product")}`);
}

/* ---------- shared list screens (WP-3 batch 2) ----------
   The filter controls, the footer pager and the export all read one query, so
   the number in the footer is the server's X-Total-Count and the export covers
   every match, not the page on screen. Until a screen's first server page has
   arrived it keeps drawing the shared 200-row cache the forms read, so a slow
   or failed request never blanks a list. */
function listState(key) {
  if (!state.lp[key]) {
    state.lp[key] = {rows: [], total: null, page: 1, size: 50, q: "",
                     loading: false, loaded: false, seq: 0, timer: 0};
  }
  return state.lp[key];
}
function pressSeg(name, value) {
  $$(`[data-${name}]`).forEach(b => b.setAttribute("aria-pressed", String(b.dataset[name] === value)));
}
const LIST_SPEC = {
  suppliers: {
    perm: "supplier:read", input: "supq", pager: "supPager", render: renderSuppliers,
    url: "/api/suppliers", unit: "supplier", title: "Supplier records", file: "Suppliers",
    filter: () => state.supFilter === "incomplete" ? {incomplete: "true"}
      : state.supFilter === "all" ? {} : {status: state.supFilter},
    filterText: () => state.supFilter === "all" ? "all" : state.supFilter,
    clearFilter() { state.supFilter = "all"; pressSeg("sf2", "all"); },
    head: ["Code", "Name", "GSTIN", "State", "Kind", "Terms (days)", "Purchase orders", "Status"],
    row: x => [x.code, x.name, x.gstin || "", x.state || "", x.kind,
      x.payment_terms_days, x.purchase_orders, x.status],
  },
  customers: {
    perm: "sales:read", input: "cuq", pager: "cuPager", render: renderCustomers,
    url: "/api/distributors", unit: "record", title: "Customer and distributor master",
    file: "Customers",
    filter: () => state.distFilter === "all" ? {}
      : state.distFilter === "incomplete" ? {incomplete: "true"} : {status: state.distFilter},
    filterText: () => state.distFilter === "all" ? "all" : state.distFilter,
    clearFilter() {
      state.distFilter = "all";
      const el = $("#cuFilter");
      if (el) el.value = "all";
    },
    head: ["Code", "Name", "GSTIN", "Territory", "Status", "Credit limit", "In use", "Available"],
    row: x => [x.code, x.name, x.gstin || "", x.territory || "", x.status,
      x.credit_limit, x.exposure, x.available],
  },
  sales: {
    perm: "sales:read", input: "soq", pager: "soPager", render: renderSales,
    url: "/api/sales-orders", unit: "order", title: "Sales orders", file: "Sales_Orders",
    filter: () => state.soFilter === "all" ? {} : {status: state.soFilter},
    filterText: () => state.soFilter === "all" ? "all" : state.soFilter,
    clearFilter() { state.soFilter = "all"; pressSeg("sf", "all"); },
    head: ["Order", "Distributor", "Code", "Created", "Lines", "Value", "Status"],
    row: x => [x.so_number, x.distributor_name, x.distributor_code,
      fmtDay(x.created_at), x.lines.length, x.total, x.status],
  },
  purchasing: {
    perm: "stock:read", input: "oq", pager: "poPager", render: renderPOs,
    url: "/api/purchase-orders", unit: "order", title: "Purchase orders", file: "Purchase_Orders",
    filter: () => state.poFilter === "all" ? {} : {status: state.poFilter},
    filterText: () => state.poFilter === "all" ? "all" : state.poFilter,
    clearFilter() { state.poFilter = "all"; pressSeg("pf", "all"); },
    head: ["PO number", "Supplier", "Created", "Lines", "Receipts", "Value", "Status"],
    row: x => [x.po_number, x.supplier, fmtDay(x.created_at), x.lines.length,
      x.receipts ? x.receipts.length : 0, poValue(x), x.status],
  },
  billing: {
    perm: "sales:read", input: "biq", pager: "invPager", render: renderBilling,
    url: "/api/invoices", unit: "invoice", title: "Tax invoices", file: "Invoices",
    filter: () => state.invFilter === "all" ? {} : {status: state.invFilter},
    filterText: () => state.invFilter === "all" ? "all" : state.invFilter,
    clearFilter() { state.invFilter = "all"; pressSeg("if", "all"); },
    head: ["Invoice", "Financial year", "Date", "Buyer", "Buyer GSTIN", "Value", "Credited", "Status"],
    row: x => [x.invoice_number, x.financial_year, x.invoice_date, x.buyer_name,
      x.buyer_gstin || "", x.grand_total, x.credit_note_total, x.status],
  },
  approvals: {
    perm: "approval:read", input: "apq", pager: "apPager", render: renderApprovals,
    url: "/api/approvals", unit: "request", title: "Approvals", file: "Approvals",
    filter: () => state.apFilter === "pending" ? {status: "pending"}
      : state.apFilter === "decided" ? {decided: "true"} : {},
    filterText: () => state.apFilter,
    clearFilter() { state.apFilter = "pending"; pressSeg("af", "pending"); },
    head: ["Request", "Type", "Document", "Requester", "Submitted", "Status", "Decision remarks"],
    row: x => [x.request_no || x.document_number || "", x.request_type_label,
      x.document_number || "", x.requested_by, fmtDay(x.requested_at), x.status,
      x.decision_reason || ""],
  },
  leads: {
    perm: "lead:read", input: "ldq", pager: "ldPager", render: renderLeads,
    url: "/api/leads", unit: "lead", title: "Leads", file: "Leads",
    filter() {
      const p = {}, f = state.ldFilter;
      if (f === "open") p.status = "open";
      else if (f === "closed") p.status = "closed";
      else if (f === "overdue" || f === "today" || f === "week") p.due = f;
      if (state.ldOwner === "mine") p.owner = "me";
      return p;
    },
    filterText: () => `${state.ldFilter} / ${state.ldOwner}`,
    clearFilter() { state.ldFilter = "open"; state.ldOwner = "all"; pressSeg("lf", "open"); pressSeg("lo", "all"); },
    head: ["Lead number", "Name", "Company", "Owner", "Source", "Status", "Next follow-up", "Last activity"],
    row: x => [x.lead_no, x.name, x.company || "", x.owner, x.source, x.status,
      x.next_follow_up || "", fmtDay(x.last_activity_at)],
  },
};
async function loadList(key, page) {
  const spec = LIST_SPEC[key], s = listState(key);
  if (!spec || !can(spec.perm)) return;
  if (page != null) s.page = Math.max(1, Number(page) || 1);
  const tok = ++s.seq;
  s.loading = true;
  const pager = $("#" + spec.pager);
  if (pager) pager.classList.add("busy");
  const qs = new URLSearchParams({page: String(s.page), page_size: String(s.size)});
  if (s.q) qs.set("q", s.q);
  Object.entries(spec.filter()).forEach(([k, v]) => qs.set(k, String(v)));
  const res = await apiPage(`${spec.url}?${qs}`);
  if (tok !== s.seq) return;                    // a newer request took over
  s.loading = false;
  if (!res.ok) {
    s.loaded = true; s.rows = []; s.total = null;
    toast(res, `${spec.title} not loaded`);
    spec.render(); renderHead();
    return;
  }
  s.rows = Array.isArray(res.body) ? res.body : [];
  s.total = res.total;
  s.loaded = true;
  // A narrower filter or a deletion can strand the view past the last page.
  if (s.total != null && !s.rows.length && s.page > 1) {
    s.page = Math.max(1, Math.ceil(s.total / s.size));
    return loadList(key, s.page);
  }
  spec.render(); renderHead();
}
function listGo(key, to) {
  const s = listState(key);
  if (s.total == null) return;
  const pages = Math.max(1, Math.ceil(s.total / s.size));
  const target = to === "first" ? 1 : to === "last" ? pages
    : to === "prev" ? s.page - 1 : s.page + 1;
  const next = Math.min(pages, Math.max(1, target));
  if (next !== s.page || s.loading) loadList(key, next);
}
function searchList(key) {
  const spec = LIST_SPEC[key], s = listState(key);
  if (!spec) return;
  clearTimeout(s.timer);
  const el = spec.input ? $("#" + spec.input) : null;
  s.q = el ? el.value.trim() : "";
  loadList(key, 1);
}
function clearList(key) {
  const spec = LIST_SPEC[key], s = listState(key);
  if (!spec) return;
  clearTimeout(s.timer);
  s.q = "";
  if (spec.input) { const el = $("#" + spec.input); if (el) el.value = ""; }
  spec.clearFilter();
  loadList(key, 1);
}
async function exportListCsv(key) {
  const spec = LIST_SPEC[key], s = listState(key);
  if (!spec) return;
  const qs = new URLSearchParams();
  if (s.q) qs.set("q", s.q);
  Object.entries(spec.filter()).forEach(([k, v]) => qs.set(k, String(v)));
  // The export read has no page, so the server returns every matching row.
  const res = await api(`${spec.url}${qs.toString() ? "?" + qs : ""}`);
  if (!res.ok) { toast(res, `${spec.title} not exported`); return; }
  const rows = Array.isArray(res.body) ? res.body : [];
  const csv = [[`HERBANOVA ${spec.title}`], ["Exported", fmtStamp(new Date().toISOString())],
    ["Search", s.q || "all"], ["Filter", spec.filterText()], ["Rows", String(rows.length)],
    spec.head];
  rows.forEach(x => csv.push(spec.row(x)));
  downloadCsv(`HERBANOVA_${spec.file}_${isoDay(0)}.csv`, csv);
  toast({ok: true, status: "200"}, `Exported ${plural(rows.length, spec.unit)}`);
}
/* A page can show a record the 200-row cache does not hold; fetch it once so
   Open still works from any page. */
async function ensureCached(key, url, id) {
  const list = state[key] || (state[key] = []);
  const hit = list.find(x => x.id === Number(id));
  if (hit) return hit;
  const res = await api(url);
  if (!res.ok) { toast(res, "Record not opened"); return null; }
  if (res.body && typeof res.body === "object") list.push(res.body);
  return res.body;
}

function productDrawer(id, mode) {
  const x = id ? (state.plist.rows.find(p => p.id === Number(id)) || state.products.find(p => p.id === Number(id))) : null;
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
      <div class="row2"><div><label for="f-cat">Category</label><input id="f-cat" name="category" list="prodCats" value="${val("category")}" placeholder="e.g. Skincare" maxlength="60" autocomplete="off"${edit ? "" : " readonly"}><datalist id="prodCats"></datalist></div>
      <div><label for="f-brand">Brand</label><input id="f-brand" name="brand" list="prodBrands" value="${val("brand")}" placeholder="e.g. Herbanova" maxlength="60" autocomplete="off"${edit ? "" : " readonly"}><datalist id="prodBrands"></datalist></div></div>
      <div class="row2"><div><label for="f-pack">Pack size</label><input id="f-pack" name="pack" value="${val("pack_size")}" placeholder="100 g" autocomplete="off"${edit ? "" : " readonly"}></div>
      <div><label for="f-mrp">MRP (₹)</label><input id="f-mrp" name="mrp" value="${val("mrp")}" inputmode="decimal" placeholder="199.00" autocomplete="off"${edit ? "" : " readonly"}></div></div>
      <label for="f-reorder">Reorder level (units, optional)</label><input id="f-reorder" name="reorder_level" value="${x && x.reorder_level != null ? esc(x.reorder_level) : ""}" inputmode="decimal" placeholder="Leave blank if not set" autocomplete="off"${edit ? "" : " readonly"}>
      ${x ? `<label for="f-status">Status</label><select id="f-status" name="status"${edit ? "" : " disabled"}><option value="active"${x.status === "active" ? " selected" : ""}>Active</option><option value="discontinued"${x.status === "discontinued" ? " selected" : ""}>Discontinued</option></select>` : ""}
      <div class="note">The HSN is stored on the product and copied onto every invoice line. GST is looked up from the rate master, never assumed. A blank reorder level means "not set", never zero.</div>
      <div class="err" role="alert"></div>
      <div class="actions">${edit ? `<button class="btn" type="submit">${x ? "Save product" : "Create product"}</button>` : ""}<button class="btn ghost" type="button" data-act="close">${edit ? "Cancel" : "Close"}</button></div>
    </form>`, true);
  fillProductCatalog();
}

async function fillProductCatalog() {
  if (!can("product:read")) return;
  const res = await api("/api/products/catalog");
  if (!res.ok) return;
  const cats = $("#prodCats"), brands = $("#prodBrands");
  if (cats) cats.innerHTML = (res.body.categories || []).map(v => `<option value="${esc(v)}"></option>`).join("");
  if (brands) brands.innerHTML = (res.body.brands || []).map(v => `<option value="${esc(v)}"></option>`).join("");
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
  $("#srows").innerHTML = list.map(b => {
    const low = b.reorder_level != null && Number(b.product_on_hand) < Number(b.reorder_level);
    return `<tr><td><span class="strong">${esc(b.product_name)}</span><small>${esc(b.sku)}, ${esc(b.pack_size)}</small></td>
    <td>${esc(b.batch_no)}</td><td>${esc(b.warehouse)}</td><td>${shelf(b.expiry)}</td><td>${esc(b.owner)}</td>
    <td class="n strong">${esc(qty(b.on_hand))}</td>
    <td class="n">${b.reorder_level != null ? `${esc(qty(b.reorder_level))}${low ? ' <span class="chip bad">Low</span>' : ""}` : '<span class="muted">Not set</span>'}</td></tr>`;
  }).join("");
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

function warehouseCapacityNote(id) {
  const w = state.warehouses.find(x => String(x.id) === String(id));
  if (!w) return "";
  if (w.capacity_units === null || w.capacity_units === undefined)
    return "Capacity has not been set for this warehouse (GAP-D03), so the fill level cannot be checked.";
  const free = Number(w.free_units);
  const space = free < 0 ? `${qty(-free)} units over capacity` : `${qty(free)} units free`;
  return `${qty(w.used_units)} of ${qty(w.capacity_units)} units used; ${space}. A receipt beyond the free space is blocked unless an Administrator overrides it.`;
}

function renderWarehouses() {
  const CAP_STATE = {ok: ["Within capacity", "ok"], high: ["Above 80%", "warn"],
                     over: ["Over capacity", "bad"], full: ["Full", "warn"]};
  const rows = state.warehouses.map(w => {
    const used = Number(w.used_units ?? 0);
    const hasCap = w.capacity_units !== null && w.capacity_units !== undefined;
    const st = hasCap ? (CAP_STATE[w.capacity_state] || [w.capacity_state, "off"]) : ["Not set", "off"];
    const pct = hasCap ? `<span class="strong">${Number(w.utilisation_pct).toFixed(1)}%</span>` : `<span class="muted">No data yet</span>`;
    return `<tr><td class="strong">${esc(w.name)}${w.capacity_note ? `<small>${esc(w.capacity_note)}</small>` : ""}</td>
      <td class="n">${Number(w.batches ?? 0)}</td><td class="n">${esc(qty(used))}</td>
      <td class="n">${hasCap ? esc(qty(w.capacity_units)) : `<span class="muted">Not set</span>`}</td>
      <td class="n">${hasCap ? esc(qty(w.free_units)) : `<span class="muted">—</span>`}</td>
      <td class="n">${pct} <span class="chip ${st[1]}">${esc(st[0])}</span></td>
      <td class="n">${can("stock:write") ? `<button class="btn ghost sm" type="button" data-act="edit-capacity" data-id="${w.id}">Edit capacity</button>` : ""}</td></tr>`;
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
  const s = listState("purchasing");
  const q = $("#oq").value.trim().toLowerCase(), f = state.poFilter;
  const list = s.loaded ? s.rows
    : state.pos.filter(p => (f === "all" || p.status === f) && (!q || p.po_number.toLowerCase().includes(q) || p.supplier.toLowerCase().includes(q)));
  const total = s.loaded ? s.total : state.pos.length;
  $("#orows").innerHTML = list.map(p => `<tr class="go" data-po="${p.id}"><td><button class="rowbtn" data-act="open-po" data-id="${p.id}" type="button">${esc(p.po_number)}</button></td>
    <td>${esc(p.supplier)}</td><td>${esc(fmtDay(p.created_at))}</td><td class="n">${p.lines.length}</td>
    <td class="n">${p.receipts ? p.receipts.length : 0}</td><td class="n">${money(poValue(p))}</td>
    <td>${chipOf(PO_STATUS, p.status)}</td></tr>`).join("");
  paintListPager("purchasing", s);
  empty($("#oempty"), !list.length, total ? "No purchase order matches these filters." : "No purchase orders yet.",
    total ? "" : (can("stock:write") ? " Select “New purchase order” to raise the first one." : ""));
}
function paintListPager(key, s) {
  const el = $("#" + LIST_SPEC[key].pager);
  if (!el) return;
  el.innerHTML = s.loaded ? pagerHtml(s, key) : "";
  el.classList.toggle("busy", s.loading);
}

/* ---------- suppliers (Module Phase 2) ---------- */
const SUP_STATUS = {active: ["Active", "ok"], blocked: ["Blocked", "bad"]};
const SKIND = {supplier: "Supplier", manufacturer: "Manufacturer", both: "Manufacturer and supplier"};
const REG = {regular: "Regular", composition: "Composition", unregistered: "Unregistered"};
const BSTAT = {pending: ["Awaiting approval", "warn"], approved: ["Approved", "ok"], rejected: ["Rejected", "bad"]};
const activeSuppliers = () => state.suppliers.filter(s => s.status === "active");

function renderSuppliers() {
  const s = listState("suppliers");
  const q = $("#supq").value.trim().toLowerCase(), f = state.supFilter;
  const list = s.loaded ? s.rows
    : state.suppliers.filter(x => (f === "all" || (f === "incomplete" ? x.needs_completion : x.status === f)) &&
      (!q || [x.code, x.name, x.gstin || "", x.state || ""].some(t => t.toLowerCase().includes(q))));
  const total = s.loaded ? s.total : state.suppliers.length;
  $("#suprows").innerHTML = list.map(x => `<tr><td><button class="rowbtn" data-act="open-supplier" data-id="${x.id}" type="button">${esc(x.code)}</button></td>
    <td>${esc(x.name)}${x.needs_completion ? ` <span class="chip warn">Needs completion</span>` : ""}</td>
    <td>${esc(x.gstin || "–")}</td><td>${esc(x.state || "–")}</td><td>${esc(SKIND[x.kind] || x.kind)}</td>
    <td class="n">${esc(x.payment_terms_days)} d</td><td class="n">${x.purchase_orders}</td><td>${chipOf(SUP_STATUS, x.status)}</td></tr>`).join("");
  paintListPager("suppliers", s);
  empty($("#supempty"), !list.length, total ? "No supplier matches these filters." : "No suppliers yet.",
    total ? "" : (can("supplier:write") ? " Select “New supplier” to add the first one." : ""));

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
  const reorder = f.reorder_level.value.trim();
  if (reorder !== "" && !(Number(reorder) >= 0)) { err.textContent = "The reorder level must be zero or more, or blank."; return; }
  const body = {hsn, name: f.name.value.trim(), pack_size: f.pack.value.trim(), mrp: f.mrp.value,
                category: f.category.value.trim() || null, brand: f.brand.value.trim() || null,
                reorder_level: reorder === "" ? null : reorder};
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
      <div class="row2">
        <div><label for="f-wh-cap">Capacity in units (optional)</label><input id="f-wh-cap" name="capacity_units" inputmode="numeric" placeholder="Leave blank if not measured" autocomplete="off"></div>
        <div><label for="f-wh-note">Capacity note (optional)</label><input id="f-wh-note" name="capacity_note" maxlength="40" placeholder="e.g. rack space" autocomplete="off"></div>
      </div>
      <p class="note">Blank capacity means it has not been measured; it never means zero.</p>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save warehouse</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}
function capacityInput(form, name) {
  const raw = form.elements[name].value.trim();
  if (!raw) return {ok: true, value: null};
  if (!/^\d+$/.test(raw)) return {ok: false, error: "Capacity must be a whole number of units."};
  return {ok: true, value: Number(raw)};
}
async function saveWarehouse(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = ""; btn.disabled = true;
  const cap = capacityInput(form, "capacity_units");
  if (!cap.ok) { err.textContent = cap.error; btn.disabled = false; form.elements.capacity_units.focus(); return; }
  const body = {name: form.elements.name.value.trim(), capacity_units: cap.value,
                capacity_note: form.elements.capacity_note.value.trim() || null};
  const res = await api("/api/warehouses", {method: "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? "Warehouse saved" : "Warehouse not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer(); loadAll();
}
function capacityForm(id) {
  const w = state.warehouses.find(x => Number(x.id) === Number(id));
  if (!w) return;
  const hasCap = w.capacity_units !== null && w.capacity_units !== undefined;
  openDrawer("Warehouse capacity", w.name, `
    <p class="note">${hasCap
      ? `${esc(qty(w.used_units))} units are on hand, ${esc(qty(w.free_units))} free of ${esc(qty(w.capacity_units))}.`
      : `${esc(qty(w.used_units))} units are on hand. Capacity has not been set for this warehouse.`}</p>
    <form id="capForm" data-id="${w.id}" novalidate>
      <div class="row2">
        <div><label for="c-units">Capacity in units</label><input id="c-units" name="capacity_units" inputmode="numeric" value="${hasCap ? w.capacity_units : ""}" placeholder="Leave blank to clear" autocomplete="off"></div>
        <div><label for="c-note">Capacity note (optional)</label><input id="c-note" name="capacity_note" maxlength="40" value="${esc(w.capacity_note || "")}" placeholder="e.g. rack space" autocomplete="off"></div>
      </div>
      <p class="note">Clearing the capacity records that it is not known; it never means zero.</p>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">Save capacity</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}
async function saveCapacity(form) {
  const err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = ""; btn.disabled = true;
  const cap = capacityInput(form, "capacity_units");
  if (!cap.ok) { err.textContent = cap.error; btn.disabled = false; form.elements.capacity_units.focus(); return; }
  const res = await api(`/api/warehouses/${Number(form.dataset.id)}/capacity`, {
    method: "PUT", body: {capacity_units: cap.value,
                          capacity_note: form.elements.capacity_note.value.trim() || null}});
  btn.disabled = false;
  toast(res, res.ok ? "Capacity saved" : "Capacity not saved");
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
        <select id="r-wh" name="warehouse">${state.warehouses.length > 1 ? `<option value="">Select a warehouse</option>` : ""}${state.warehouses.map(w => `<option value="${w.id}">${esc(w.name)}${w.capacity_units != null ? ` — ${esc(qty(w.used_units))} of ${esc(qty(w.capacity_units))} units` : " — capacity not set"}</option>`).join("")}</select>
        <p class="note" id="rWhNote">${warehouseCapacityNote(state.warehouses.length === 1 ? state.warehouses[0].id : "")}</p>
        <div class="hide" id="rOverBox"><label class="check"><input type="checkbox" name="allow_over_capacity"> Receive over capacity (Administrator only; recorded in the audit log)</label></div>
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
  if (form.elements.allow_over_capacity && form.elements.allow_over_capacity.checked)
    body.allow_over_capacity = true;
  const dn = form.elements.delivery_note.value.trim();
  if (dn) body.delivery_note = dn;
  const id = Number(form.dataset.po);
  btn.disabled = true;
  const res = await api(`/api/purchase-orders/${id}/receive`, {method: "POST", body});
  btn.disabled = false;
  toast(res, res.ok ? `Receipt ${res.body.grn_number} posted` : "Receipt not posted");
  if (!res.ok) {
    const msg = detail(res.body);
    err.textContent = msg;
    // Only the server decides who may override; the control is merely revealed
    // after the block so an Administrator can choose to record the overage.
    if (res.status === 409 && /capacity/i.test(msg)) {
      const box = $("#rOverBox", form);
      if (box) box.classList.remove("hide");
    }
    return;
  }
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
  const s = listState("sales");
  const q = $("#soq").value.trim().toLowerCase(), f = state.soFilter;
  const list = s.loaded ? s.rows
    : state.orders.filter(o => (f === "all" || o.status === f) &&
      (!q || o.so_number.toLowerCase().includes(q) || o.distributor_code.toLowerCase().includes(q) || o.distributor_name.toLowerCase().includes(q)));
  const total = s.loaded ? s.total : state.orders.length;
  $("#sorows").innerHTML = list.map(o => `<tr class="go" data-so="${o.id}"><td><button class="rowbtn" data-act="open-so" data-id="${o.id}" type="button">${esc(o.so_number)}</button></td>
    <td>${esc(o.distributor_name)}<small>${esc(o.distributor_code)}</small></td><td>${esc(fmtDay(o.created_at))}</td><td class="n">${o.lines.length}</td>
    <td class="n">${money(o.total)}</td><td>${chipOf(SO, o.status)}</td></tr>`).join("");
  paintListPager("sales", s);
  empty($("#soempty"), !list.length, total ? "No order matches these filters." : "No sales orders yet.",
    total ? "" : (can("sales:write") ? " Select “New sales order” to start one." : ""));
  const n = state.orders.filter(o => o.status === "approved").length;
  setBadge("soCount", n, `${n} orders ready to dispatch`);
}

function renderApprovals() {
  const s = listState("approvals");
  const f = state.apFilter;
  const list = s.loaded ? s.rows
    : state.approvals.filter(a => f === "all" || (f === "pending" ? a.status === "pending" : a.status !== "pending"));
  const total = s.loaded ? s.total : state.approvals.length;
  $("#aprows").innerHTML = list.map(a => `<tr class="go" data-ap="${a.id}"><td><button class="rowbtn" data-act="open-ap" data-id="${a.id}" type="button">${esc(a.request_no || a.document_number || "Request")}</button></td>
    <td>${esc(a.request_type_label)}</td><td>${esc(a.document_number || "–")}<small>${esc(a.subject || "")}</small></td>
    <td>${esc(a.requested_by)}</td><td>${esc(fmtDay(a.requested_at))}</td>
    <td>${chipOf(AP, a.status)}${a.decided_by ? `<small>by ${esc(a.decided_by)}, ${esc(fmtDay(a.decided_at))}</small>` : ""}</td>
    <td>${esc(a.decision_reason || "–")}</td></tr>`).join("");
  paintListPager("approvals", s);
  empty($("#apempty"), !list.length,
    total ? "No request matches these filters."
      : (f === "pending" ? "Nothing is waiting for a decision." : "No approval requests yet."),
    total ? "" : (f === "pending" ? " Orders over a credit limit, large discounts, HR requests and post-billing edits appear here." : ""));
  const n = state.approvals.filter(a => a.status === "pending").length;
  setBadge("apCount", n, `${n} approvals waiting`);
}

// One status vocabulary, shared with the API (COR-001). An unknown value must
// never throw: one bad chip in the party master would blank every section
// rendered after it. Every value the API can store is listed here, so the form
// can offer them and the chip can name them.
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
      <label for="s-edd">Expected delivery date (optional)</label>
      <input id="s-edd" name="expected_delivery_date" type="date" min="${new Date().toISOString().slice(0, 10)}">
      <div class="note">The date promised to the buyer. Leave it blank if no promise was made; lateness is only reported against a promise.</div>
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
  const promised = form.elements.expected_delivery_date.value;
  btn.disabled = true;
  const res = await api("/api/sales-orders", {method: "POST", body: {distributor_id: Number(dist), lines,
    ...(promised ? {expected_delivery_date: promised} : {})}});
  btn.disabled = false;
  toast(res, res.ok ? `Draft ${res.body.so_number} saved` : "Order not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  closeDrawer();
  if (state.view !== "sales") location.hash = "#/sales";
  await loadAll(); soDetail(res.body.id);
}

async function saveSoPromise(form, ev) {
  const err = $(".err", form), id = Number(form.dataset.id);
  const clear = !!(ev && ev.submitter && ev.submitter.value === "clear");
  const date = clear ? null : form.elements.expected_delivery_date.value;
  err.textContent = "";
  if (!clear && !date) { err.textContent = "Choose a date, or use Clear promise."; return; }
  const res = await api(`/api/sales-orders/${id}/delivery-date`,
    {method: "PATCH", body: {expected_delivery_date: date}});
  toast(res, res.ok ? "Promised date saved" : "Promise not saved");
  if (!res.ok) { err.textContent = detail(res.body); return; }
  await loadAll(); soDetail(id);
}

/* --- order detail: submit, cancel, dispatch --- */
function promiseCell(o) {
  if (!o.expected_delivery_date) return '<span class="muted">Not recorded</span>';
  let suffix = "";
  if (o.dispatched_at) {
    const done = new Date(o.dispatched_at);
    const iso = `${done.getFullYear()}-${String(done.getMonth() + 1).padStart(2, "0")}-${String(done.getDate()).padStart(2, "0")}`;
    const diff = Math.round((new Date(iso) - new Date(o.expected_delivery_date)) / 86400000);
    suffix = diff > 0 ? ` <span class="chip bad">${plural(diff, "day")} late</span>`
      : diff === 0 ? ' <span class="chip ok">On the promised day</span>'
      : ` <span class="chip ok">${plural(-diff, "day")} early</span>`;
  }
  return `${esc(fmtDate(o.expected_delivery_date))}${suffix}`;
}

function promiseEditor(o) {
  if (!can("sales:write") || !["draft", "pending_approval", "approved"].includes(o.status)) return "";
  const min = new Date().toISOString().slice(0, 10);
  return `<form id="soPromiseForm" data-id="${o.id}" novalidate><h3>Promised delivery date</h3>
    <label for="sp-date">Date</label><input id="sp-date" name="expected_delivery_date" type="date" min="${min}" value="${o.expected_delivery_date || ""}">
    <div class="note">The date given to the buyer. Lateness is measured against it; an order without a promise is not counted. No date is inferred from payment terms.</div>
    <div class="err" role="alert"></div>
    <div class="actions"><button class="btn sm" type="submit">Save promise</button>${o.expected_delivery_date ? `<button class="btn ghost sm" type="submit" value="clear">Clear promise</button>` : ""}</div></form>`;
}

function soDetail(id, result, err) {
  const o = orderOf(id); if (!o) return;
  const a = o.approval;  const lines = o.lines.map(l => `<tr><td><span class="strong">${esc(l.product_name)}</span><small>${esc(l.sku)}</small></td>
    <td class="n">${esc(qty(l.qty))}</td><td class="n">${money(l.unit_price)}${Number(l.discount_pct) > 0 ? `<small>${esc(l.discount_pct)}% below MRP</small>` : ""}</td>
    <td class="n">${money(l.line_total)}</td></tr>`).join("");
  const cancelForm = () => can("sales:write") ? `<form id="cancelForm" data-id="${o.id}" novalidate><h3>Cancel this order</h3>
      <label for="c-r">Reason</label><input id="c-r" name="reason" placeholder="Why is it being cancelled?" autocomplete="off">
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn ghost" type="submit">Cancel order</button><button class="btn ghost" type="button" data-act="close">Close</button></div></form>` : `<div class="actions"><button class="btn ghost" type="button" data-act="close">Close</button></div>`;
  let foot = "";
  if (err) foot += `<div class="err" role="alert">${esc(err)}</div>`;
  if (result) {
    const src = result.source_warehouse;
    const space = src
      ? `<p class="muted">${esc(src.name)} now holds ${esc(qty(src.used_units))} units${src.capacity_units != null
          ? ` of ${esc(qty(src.capacity_units))} (${Number(src.utilisation_pct).toFixed(1)}%)` : ""}.</p>`
      : "";
    foot += `<div class="done"><b>Dispatched. Stock has been issued, earliest expiry first.</b><ul>${result.allocations.map(x =>
      `<li>${esc(qty(x.qty))} of ${esc(x.sku)} from batch ${esc(x.batch_no)}${x.expiry ? `, expires ${esc(fmtDate(x.expiry))}` : ""}.</li>`).join("")}</ul>${space}</div>
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
          <select id="d-wh" name="warehouse">${state.warehouses.length > 1 ? `<option value="">Select a warehouse</option>` : ""}${state.warehouses.map(w => `<option value="${w.id}">${esc(w.name)}${w.capacity_units != null ? ` — ${esc(qty(w.used_units))} of ${esc(qty(w.capacity_units))} units` : ""}</option>`).join("")}</select>
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
      ${o.approved_at ? `<dt>Approved</dt><dd>${esc(fmtStamp(o.approved_at))}</dd>` : ""}
      <dt>Promised delivery</dt><dd>${promiseCell(o)}</dd>
      ${a ? `<dt>Approval</dt><dd>${chipOf(AP, a.status)} ${reasonChips(a.reasons)}</dd>` : ""}</dl>
    ${promiseEditor(o)}
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
  const s = listState("billing");
  const q = $("#biq").value.trim().toLowerCase(), f = state.invFilter;
  const list = s.loaded ? s.rows
    : state.invoices.filter(i => (f === "all" || i.status === f) &&
      (!q || [i.invoice_number, i.buyer_name, i.so_number || ""].some(t => t.toLowerCase().includes(q))));
  const total = s.loaded ? s.total : state.invoices.length;
  $("#invrows").innerHTML = list.map(i => `<tr><td><button class="rowbtn" data-act="open-inv" data-id="${i.id}" type="button">${esc(i.invoice_number)}</button><small>${esc(i.financial_year)}${i.so_number ? " · " + esc(i.so_number) : ""}</small></td>
    <td>${esc(fmtDate(i.invoice_date))}</td><td>${esc(i.buyer_name)}<small>${esc(i.buyer_gstin || "Unregistered")}</small></td>
    <td class="n strong">${money(i.grand_total)}</td><td class="n">${money(i.credit_note_total)}</td>
    <td>${chipOf(INV_STATUS, i.status)}</td>
    <td><button class="btn ghost sm" data-act="open-inv" data-id="${i.id}" type="button">Open</button><button class="btn ghost sm" data-act="print-inv" data-id="${i.id}" type="button">Print</button></td></tr>`).join("");
  paintListPager("billing", s);
  empty($("#invempty"), !list.length, total ? "No invoice matches this filter." : "No invoices yet.",
    total ? "" : " An invoice is issued automatically when an approved sales order is dispatched.");

  const notes = [...state.creditNotes.map(n => ({...n, kind: "Credit", no: n.credit_note_number, noteKind: "credit_note"})),
                 ...state.debitNotes.map(n => ({...n, kind: "Debit", no: n.debit_note_number, noteKind: "debit_note"}))]
    .sort((a, b) => b.id - a.id);
  $("#noterows").innerHTML = notes.map(n => `<tr><td class="strong">${esc(n.no)}</td><td>${esc(n.invoice_number || "–")}</td>
    <td>${esc(fmtDate(n.note_date))}</td><td>${esc(n.kind)}<small>${esc(n.reason)}${n.returned_to_stock ? ` · returned to ${esc(n.warehouse || "stock")}` : ""}</small></td>
    <td class="n">${money(n.grand_total)}</td><td>${chipOf(INV_STATUS, n.status)}</td>
    <td><button class="btn ghost sm" data-act="open-note" data-kind="${n.noteKind}" data-id="${n.id}" type="button">Open</button>${can("print:document") ? `<button class="btn ghost sm" data-act="print-note" data-kind="${n.noteKind}" data-id="${n.id}" type="button">Print</button>` : ""}</td></tr>`).join("");
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
      <dt>Payment terms</dt><dd>${inv.payment_terms_days == null
        ? "Not captured when this invoice was issued, so it has no due date"
        : `${esc(String(inv.payment_terms_days))} days${inv.due_date ? ` · due ${fmtDate(inv.due_date)}` : ""}`}</dd>
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

/* A note is immutable, so its drawer is a record, not a form: what was issued,
   the invoice it corrects, the lines and the tax it reversed, and the print
   panel that serves the PDF and checks a printed copy. */
function noteDetail(kind, id) {
  const list = kind === "credit_note" ? state.creditNotes : state.debitNotes;
  const n = list.find(x => x.id === Number(id));
  if (!n) return;
  const label = kind === "credit_note" ? "Credit note" : "Debit note";
  const number = kind === "credit_note" ? n.credit_note_number : n.debit_note_number;
  const inv = state.invoices.find(i => i.id === n.invoice_id);
  const lines = (n.lines || []).map(l => `<tr><td><span class="strong">${esc(l.product_name)}</span><small>${esc(l.sku)}</small></td>
    <td class="n">${esc(qty(l.qty))}</td><td class="n">${money(l.taxable_value)}</td>
    <td class="n">${money(l.cgst_amount)}</td><td class="n">${money(l.sgst_amount)}</td>
    <td class="n">${money(l.igst_amount)}</td><td class="n">${money(l.cess_amount)}</td>
    <td class="n">${money(l.line_total)}</td></tr>`).join("");
  openDrawer(number, `${label} · ${fmtDate(n.note_date)} · ${INV_STATUS[n.status] ? INV_STATUS[n.status][0] : n.status}`, `
    <dl class="dl"><dt>Document</dt><dd>${esc(number)}<small>${esc(n.financial_year)}</small></dd>
      <dt>Against invoice</dt><dd>${esc(n.invoice_number || `#${n.invoice_id}`)}</dd>
      <dt>Buyer</dt><dd>${esc(inv && inv.buyer_name ? inv.buyer_name : "Not shown on the note record")}</dd>
      <dt>Date</dt><dd>${esc(fmtDate(n.note_date))}</dd>
      <dt>Reason</dt><dd>${esc(n.reason)}</dd>
      ${kind === "credit_note" ? `<dt>Goods returned to stock</dt><dd>${n.returned_to_stock
        ? esc(n.warehouse || "Yes") : "No — money correction only"}</dd>` : ""}
      <dt>Taxable value</dt><dd>₹ ${money(n.taxable_value)}</dd>
      <dt>CGST / SGST / IGST / Cess</dt><dd>₹ ${money(n.cgst_total)} / ${money(n.sgst_total)} / ${money(n.igst_total)} / ${money(n.cess_total)}</dd>
      <dt>Tax total</dt><dd>₹ ${money(n.tax_total)}</dd>
      <dt>Note total</dt><dd><b>₹ ${money(n.grand_total)}</b></dd></dl>
    <div class="tw"><table class="dtable"><thead><tr><th>Line</th><th class="n">Qty</th><th class="n">Taxable</th><th class="n">CGST</th><th class="n">SGST</th><th class="n">IGST</th><th class="n">Cess</th><th class="n">Total</th></tr></thead><tbody>${lines || `<tr><td colspan="8">No line detail was recorded.</td></tr>`}</tbody></table></div>
    <div class="note">A ${label.toLowerCase()} cannot be edited or deleted after issue. It is corrected by issuing another note, which is added to this invoice's record.</div>
    ${can("print:document") ? verifyPanel(kind, n.id) : ""}`, true);
  if (can("print:document")) loadPrintPanel(kind, n.id);
}

/* The panel below the invoice. It reads the print log, shows the real QR symbol
   served by /api/print/qr, and prints any of the three copy sets — the copy is
   chosen here because the invoice list's Print button issues ORIGINAL only. */
function verifyPanel(kind, id) {
  const copies = ["ORIGINAL", "DUPLICATE", "TRIPLICATE"]
    .map(c => `<option value="${c}">${c}</option>`).join("");
  return `<div class="qr-panel" style="margin-top:16px; padding:12px; background:var(--wash); border:1px solid var(--line); border-radius:4px;">
    <h3>Print and verification</h3>
    <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap;">
      <img id="qrImg" class="hide" width="128" height="128" alt="QR code carrying the latest print's short code" style="background:var(--surface)">
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
  const s = listState("leads");
  const q = $("#ldq").value.trim().toLowerCase();
  const list = s.loaded ? s.rows
    : state.leads.filter(l => leadVisible(l) && (!q || [l.name, l.company, l.lead_no, l.phone, l.email].some(x => (x || "").toLowerCase().includes(q))));
  const total = s.loaded ? s.total : state.leads.length;
  $("#ldrows").innerHTML = list.map(l => `<tr class="go" data-ld="${l.id}"><td><button class="rowbtn" data-act="open-lead" data-id="${l.id}" type="button">${esc(l.name)}</button><small>${esc(l.company || l.lead_no)}</small></td>
    <td>${esc(l.owner)}</td><td>${esc(SRC[l.source] || l.source)}</td><td>${chipOf(LSTAT, l.status)}</td><td>${followCell(l)}</td><td>${esc(fmtDay(l.last_activity_at))}</td></tr>`).join("");
  paintListPager("leads", s);
  empty($("#ldempty"), !list.length, total ? "No lead matches these filters." : "No leads yet.",
    total ? "" : (can("lead:write") ? " Select “New lead” to add the first one." : ""));
  const n = state.leads.filter(l => l.owner === state.user.username && (l.follow_up_state === "overdue" || l.follow_up_state === "today")).length;
  setBadge("ldCount", n, `${n} of your follow-ups need attention`);
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

  if ($("#frows")) {
    $("#frows").innerHTML = state.featureFlags.map(f => `<tr>
      <td><span class="strong">${esc(f.label)}</span><small>${esc(f.description)}</small></td>
      <td>${f.permissions.map(p => `<code>${esc(p)}</code>`).join(" ")}</td>
      <td><span class="chip ${f.enabled ? "ok" : "off"}">${f.enabled ? "Available" : "Switched off"}</span></td>
      <td class="rowacts">${f.locked ? '<span class="muted">Always on</span>'
        : `<button class="btn ghost sm" type="button" data-act="toggle-feature" data-key="${esc(f.key)}" data-enabled="${f.enabled}">${f.enabled ? "Switch off" : "Switch on"}</button>`}</td></tr>`).join("");
    empty($("#fempty"), !state.featureFlags.length,
      "Only the Administrator role can read or change module switches.", "");
  }
  renderAccessRules();

  $("#erows").innerHTML = state.employees.map(e => `<tr>
    <td class="strong">${esc(e.code)}</td><td>${esc(e.full_name)}</td>
    <td>${esc(e.designation || "–")}</td><td>${esc(e.department || "–")}</td>
    <td>${esc(e.username || "Not linked")}</td>
    <td><span class="chip ${e.status === "active" ? "ok" : "off"}">${esc(e.status)}</span></td>
    <td class="rowacts"><button class="btn ghost sm" type="button" data-act="edit-emp" data-id="${e.id}">Edit</button></td></tr>`).join("");
  empty($("#eempty"), !state.employees.length, "No employees yet.", can("employee:write") ? " Select “New employee” to add the first one." : "");
}

function renderAccessRules() {
  const rows = $("#acrows");
  if (!rows) return;
  rows.innerHTML = state.permCatalog.map(g => {
    const parents = g.items.filter(i => !i.parent);
    const children = g.items.filter(i => i.parent);
    const key = i => `<code>${esc(i.key)}</code>${i.admin_only ? ' <span class="chip warn">Admin only</span>' : ""}`;
    const parentCell = parents.map(key).join("<br>") || "–";
    const childCell = children.map(i => `${key(i)} <span class="muted">needs ${esc(i.parent)}</span>`).join("<br>") || "–";
    const locked = g.items.filter(i => i.admin_only).map(i => `<code>${esc(i.key)}</code>`).join(" ") || "–";
    return `<tr><td class="strong">${esc(g.module)}</td><td>${parentCell}</td><td>${childCell}</td><td>${locked}</td></tr>`;
  }).join("");
  empty($("#acempty"), !state.permCatalog.length,
    "The permission catalogue is available to a role holding user:manage.", "");
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

const PERM_ITEMS = () => state.permCatalog.flatMap(g => g.items);
const PERM_CHILDREN = () => {
  const map = {};
  PERM_ITEMS().forEach(i => { if (i.parent) (map[i.parent] = map[i.parent] || []).push(i.key); });
  return map;
};

function roleForm(roleId) {
  const role = roleId ? state.roles.find(r => r.id === Number(roleId)) : null;
  const isAdminRole = !!role && (role.name || "").toLowerCase() === "admin";
  const stored = new Set(role ? role.permissions : []);
  const children = PERM_CHILDREN();
  // A child is offered only when its parent is already held. It is never
  // checked by the parent: the Administrator chooses each child explicitly.
  const usable = i => !i.parent || stored.has(i.parent);
  const matrix = state.permCatalog.map(g => {
    const items = [...g.items].sort((a, b) =>
      (a.parent ? 1 : 0) - (b.parent ? 1 : 0) || a.key.localeCompare(b.key));
    return `<div class="permgroup"><b>${esc(g.module)}</b>${items.map(i => {
      const lockedAdmin = i.admin_only && !isAdminRole;
      const checked = stored.has(i.key) && usable(i) && !lockedAdmin;
      const disabled = (i.parent && !stored.has(i.parent)) || lockedAdmin;
      const note = lockedAdmin ? "Administrator only"
        : (i.parent ? `Needs ${i.parent}` : `Controls ${(children[i.key] || []).length || "no"} child permission${(children[i.key] || []).length === 1 ? "" : "s"}`);
      return `<label class="check${i.parent ? " child" : ""}"${lockedAdmin ? ' title="Only the Administrator role can hold this permission"' : ""}>
        <input type="checkbox" name="perm" value="${esc(i.key)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}
          data-perm="${esc(i.key)}"${lockedAdmin ? ' data-locked="1"' : ""}${i.parent ? ` data-parent="${esc(i.parent)}"` : ""}
          ${!i.parent ? `data-controls="${esc((children[i.key] || []).join(","))}"` : ""}>
        <span>${esc(i.key)}<small>${esc(i.description)} · ${esc(note)}</small></span></label>`;
    }).join("")}</div>`;
  }).join("");
  openDrawer(role ? `Edit role: ${role.name}` : "New role",
    "Parent checked: its children become selectable. Children are granted only when you tick them. Unchecking a parent removes its children. Administrator-only rights stay with the Administrator.", `
    <form id="roleForm" data-id="${role ? role.id : ""}" novalidate>
      ${role ? "" : `<label for="nr-name">Role name</label><input id="nr-name" name="name" autocomplete="off" placeholder="e.g. accounts">`}
      <label for="nr-label">Display name</label><input id="nr-label" name="display_name" autocomplete="off" value="${role ? esc(role.display_name) : ""}" placeholder="e.g. Accounts">
      <div class="matrix">${matrix}</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">${role ? "Save permissions" : "Create role"}</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
}

function syncPermissionTree(form) {
  $$('input[name="perm"][data-parent]', form).forEach(child => {
    if (child.dataset.locked) return;
    const parent = $('input[name="perm"][data-perm="' + CSS.escape(child.dataset.parent) + '"]', form);
    const on = !!(parent && parent.checked);
    if (!on) child.checked = false;
    child.disabled = !on;
  });
}
async function toggleFeature(key, enabled) {
  const next = enabled !== "true";
  const row = state.featureFlags.find(f => f.key === key);
  if (!next && !confirm(`Switch off “${row ? row.label : key}”? Every role loses access to it until it is switched back on.`)) return;
  const res = await api(`/api/features/${encodeURIComponent(key)}`, {method: "PATCH",
    body: {enabled: next}});
  toast(res, res.ok ? (next ? "Module switched on" : "Module switched off") : "Module not changed");
  if (!res.ok) return;
  // The switch changes this session's own effective permissions, so re-enter
  // with a fresh identity rather than patching the browser's copy.
  const me = await api("/api/auth/me");
  if (me.ok) enter(me.body); else loadAll();
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
  // A role edit can change this very account's permissions, so ask the server
  // for the menu again rather than trusting the copy loaded at sign-in.
  if (res.ok) { closeDrawer(); loadAll(); navRefresh(); } else $(".err", form).textContent = detail(res.body);
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
  const [b, o, s, prof, dept] = rich
    ? await Promise.all([api("/api/hr/branches"), api("/api/hr/offices"), api("/api/hr/shifts"),
        empId ? api(`/api/hr/employees/${empId}/profile`) : Promise.resolve(null),
        api("/api/hr/departments")])
    : [null, null, null, null, null];
  const departments = dept && dept.ok ? dept.body : [];
  if (dept && dept.ok) state.hr.departments = departments;
  const deptName = e ? (e.department || (departments.find(d => d.id === e.department_id) || {}).name || "") : "";
  const deptList = departments.length
    ? `<datalist id="ne-deptlist">${departments.filter(d => d.status === "active")
        .map(d => `<option value="${esc(d.name)}"></option>`).join("")}</datalist>` : "";
  const opts = (res, sel, label) => (res && res.ok ? res.body : [])
    .map(v => `<option value="${v.id}"${sel === v.id ? " selected" : ""}>${esc(label(v))}</option>`).join("");
  const req = prof && prof.ok ? prof.body.attendance_requirement : null;
  const policy = req
    ? `<div class="note" id="ne-policy">Attendance policy: ${req.required ? "required" : "not required"} · self check-in ${req.self_service ? "on" : "off"}${req.attendance_mode ? ` · ${req.attendance_mode} mode` : ""} · ${esc(req.source)}.</div>`
    : `<div class="note" id="ne-policy">Attendance is required by default. The rule that applies (branch, office, designation or employee) is shown here after the employee is saved.</div>`;
  const hrFields = rich ? `
      <div class="row2"><div><label for="ne-join">Joining date</label><input id="ne-join" name="joining_date" type="date" value="${e && e.joining_date ? e.joining_date : ""}"></div>
      <div><label for="ne-type">Employment type</label><input id="ne-type" name="employment_type" autocomplete="off" value="${e && e.employment_type ? esc(e.employment_type) : ""}" placeholder="Full time / Contract"></div></div>
      <div class="row2"><div><label for="ne-branch">Branch</label><select id="ne-branch" name="branch_id"><option value="">—</option>${opts(b, e ? e.branch_id : null, v => v.name)}</select></div>
      <div><label for="ne-office">Office / work location</label><select id="ne-office" name="office_id"><option value="">—</option>${(o && o.ok ? o.body : []).map(v => `<option value="${v.id}" data-branch="${v.branch_id == null ? "" : v.branch_id}"${e && e.office_id === v.id ? " selected" : ""}>${esc(v.name)}</option>`).join("")}</select></div></div>
      ${policy}
      <div class="row2"><div><label for="ne-shift">Shift</label><select id="ne-shift" name="shift_id"><option value="">—</option>${opts(s, e ? e.shift_id : null, v => v.name)}</select></div>
      <div><label for="ne-status">Status</label><select id="ne-status" name="status"><option value="active" ${!e || e.status === "active" ? "selected" : ""}>Active</option><option value="inactive" ${e && e.status === "inactive" ? "selected" : ""}>Inactive</option></select></div></div>`
    : `<label for="ne-status">Status</label><select id="ne-status" name="status"><option value="active" ${!e || e.status === "active" ? "selected" : ""}>Active</option><option value="inactive" ${e && e.status === "inactive" ? "selected" : ""}>Inactive</option></select>`;
  openDrawer(e ? `Employee ${e.code}` : "New employee",
    "One employee master for HR and settings. Employees are deactivated, never deleted.", `
    <form id="empForm" data-id="${e ? e.id : ""}" novalidate>
      <div class="row2"><div><label for="ne-code">Employee code</label><input id="ne-code" name="code" autocomplete="off" value="${e ? esc(e.code) : ""}" ${e ? "readonly" : ""}></div>
      <div><label for="ne-name">Full name</label><input id="ne-name" name="full_name" autocomplete="off" value="${e ? esc(e.full_name) : ""}"></div></div>
      <div class="row2"><div><label for="ne-dept">Department</label><input id="ne-dept" name="department" list="ne-deptlist" autocomplete="off" value="${esc(deptName)}" placeholder="Choose or type a department">${deptList}</div>
      <div><label for="ne-des">Designation</label><input id="ne-des" name="designation" autocomplete="off" value="${e && e.designation ? esc(e.designation) : ""}"></div></div>
      <div class="row2"><div><label for="ne-phone">Phone</label><input id="ne-phone" name="phone" autocomplete="off" value="${e && e.phone ? esc(e.phone) : ""}"></div>
      <div><label for="ne-email">Email</label><input id="ne-email" name="email" autocomplete="off" value="${e && e.email ? esc(e.email) : ""}"></div></div>
      ${hrFields}
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">${e ? "Save employee" : "Create employee"}</button><button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
  if (!rich) return;
  // An office belongs to one branch, so the pair can never disagree: picking a
  // branch hides the offices of other branches, picking an office fills its branch.
  const bSel = $("#ne-branch"), oSel = $("#ne-office");
  const syncOffices = () => {
    const want = bSel.value;
    $$("option[data-branch]", oSel).forEach(op => {
      op.hidden = !!(want && op.dataset.branch !== want);
    });
    const cur = oSel.selectedOptions[0];
    if (cur && cur.hidden) oSel.value = "";
  };
  bSel.addEventListener("change", syncOffices);
  oSel.addEventListener("change", () => {
    const br = oSel.selectedOptions[0] ? oSel.selectedOptions[0].dataset.branch : "";
    if (br) { bSel.value = br; syncOffices(); }
  });
  syncOffices();
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
    // A name typed exactly as a master is linked to it; free text stays text.
    const dept = (state.hr.departments || []).find(d => d.name === body.department);
    body.department_id = dept ? dept.id : null;
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

/* ---------- scheduled reports (Administrator only) ----------
   The server refuses every route here to anyone who is not the seeded
   Administrator, even if a custom role was granted email:manage. The nav link
   and this screen follow the same rule so a role is never offered a screen
   that can only answer 403. Nothing here sends: Preview renders, and Run now /
   Send test only queue a delivery row for the worker. */
const srAllowed = () => can("email:manage") && !!state.user
  && String(state.user.role || "").trim().toLowerCase() === "admin";
const SR_STATUS = {queued: ["Queued", "off"], sending: ["Sending", "warn"], sent: ["Sent", "ok"],
                   retry: ["Retry", "warn"], failed: ["Failed", "bad"], skipped: ["Skipped", "off"]};
const SR_TRIGGER = {scheduled: "Scheduled", manual: "Run now", test: "Test", resend: "Resend"};
const SR_GROUP = {md: "MD", admin: "Administrators", extra: "Extras"};
const SR_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SR_FREQ = {daily: "Every day", weekdays: "Monday to Friday", weekly: "Chosen weekdays",
                 monthly: "Monthly rule", custom: "Custom cron"};
const srChip = status => {
  const [label, tone] = SR_STATUS[status] || [status || "–", "off"];
  return `<span class="chip ${tone}">${esc(label)}</span>`;
};
const humanBytes = n => {
  const v = Number(n) || 0;
  if (v >= 1048576) return `${(v / 1048576).toFixed(1)} MB`;
  if (v >= 1024) return `${Math.round(v / 1024)} KB`;
  return `${v} B`;
};

function srTab(tab) {
  state.sr.tab = ["schedules", "recipients", "log"].includes(tab) ? tab : "schedules";
  srShowTab();
  if (state.sr.tab === "log") loadDeliveries();
}
function srShowTab() {
  ["schedules", "recipients", "log"].forEach(t =>
    $("#sr-" + t).classList.toggle("hide", t !== state.sr.tab));
  $$("#srTabs [data-sr-tab]").forEach(b =>
    b.setAttribute("aria-selected", String(b.dataset.srTab === state.sr.tab)));
}

async function openScheduled() {
  if (!srAllowed()) return;
  srShowTab();
  const [status, people, schedules] = await Promise.all([
    api("/api/email-reports/status"),
    api("/api/email-reports/recipients"),
    api("/api/email-reports/schedules")
  ]);
  if (!status.ok) { toast(status, "Scheduled reports not loaded"); return; }
  state.sr.status = status.body;
  if (people.ok) state.sr.recipients = people.body || [];
  if (schedules.ok) state.sr.schedules = schedules.body || [];
  renderScheduled();
  renderHead();
  if (state.sr.tab === "log") await loadDeliveries();
}

function renderScheduled() {
  if (!$("#srSchedRows") || !state.sr.status) return;
  renderSrBanner();
  renderSrSchedules();
  renderSrRecipients();
  renderSrLog();
  srShowTab();
}

function renderSrBanner() {
  const s = state.sr.status, el = $("#srBanner");
  if (!s || !el) return;
  const interval = s.worker_interval ? `The worker checks every ${s.worker_interval} s.` : "";
  const testTo = s.test_recipient || "the first active Administrator";
  let banner;
  if (s.mode !== "live") {
    banner = `<div class="callout"><div><b>Test mode.</b> Nothing is delivered to the real list: every queued
      message is redirected to ${esc(testTo)} and marked as a test. SMTP
      ${s.smtp_ready ? "is configured" : "is not configured, so a send cannot start"}.</div></div>`;
  } else if (!s.send_enabled) {
    banner = `<div class="callout"><div><b>Live mode selected, sending disabled.</b> A queued report waits
      until the Administrator enables sending (EMAIL_SEND_ENABLED). Nothing leaves the server now.</div></div>`;
  } else if (!s.smtp_ready) {
    banner = `<div class="callout"><div><b>Live sending is on, but SMTP is not configured.</b> A send cannot
      start until SMTP_HOST and SMTP_FROM are set.</div></div>`;
  } else {
    banner = `<div class="note"><span class="chip ok">Live</span> Sending is enabled. A scheduled run goes to
      its real recipients and is written to the audit log.</div>`;
  }
  el.innerHTML = banner + `<div class="note">${esc(interval)} The largest message is ${esc(humanBytes(s.max_bytes))};
    a larger set of attachments is reduced, never silently truncated.</div>`;
}

function renderSrSchedules() {
  const list = state.sr.schedules;
  $("#srSchedNote").textContent =
    `${plural(list.length, "schedule")}, ${list.filter(s => s.enabled).length} on.`;
  $("#srSchedRows").innerHTML = list.map(s => {
    const people = s.recipients || [];
    const counts = {to: 0, cc: 0, bcc: 0};
    people.forEach(p => { counts[p.field] = (counts[p.field] || 0) + 1; });
    const who = [counts.to ? `${counts.to} To` : "", counts.cc ? `${counts.cc} CC` : "",
                 counts.bcc ? `${counts.bcc} BCC` : ""].filter(Boolean).join(", ");
    const groups = (s.groups || []).map(g => SR_GROUP[g] || g);
    const content = [
      `<b>${esc(s.pack_label)}</b>`,
      groups.length ? `Groups: ${esc(groups.join(", "))}` : "",
      who ? `Named: ${esc(who)}` : "",
      s.include_attachments ? "PDF + Excel" : "No attachments",
      s.include_accounts ? "Accounts block" : "",
      (s.custom_reports || []).length ? `${plural(s.custom_reports.length, "custom report")}` : ""
    ].filter(Boolean).join("<br>");
    const warnings = (s.warnings || []).map(w => `<div class="hint">${esc(w)}</div>`).join("");
    const next = s.enabled ? fmtStamp(s.next_run_at) : "Paused";
    const last = s.last_run_at
      ? `${fmtStamp(s.last_run_at)} ${s.last_status ? srChip(s.last_status) : ""}`
      : "Never run";
    return `<tr>
      <td><b>${esc(s.name)}</b><small>${esc(SR_FREQ[s.frequency] || s.frequency)}</small>
        <small>${esc(s.timezone)}</small></td>
      <td>${content}</td>
      <td>${esc(s.description)}</td>
      <td>${esc(next)}</td>
      <td>${last}</td>
      <td><span class="chip ${s.enabled ? "ok" : "off"}">${s.enabled ? "On" : "Paused"}</span>${warnings}</td>
      <td class="rowacts">
        <button class="btn ghost sm" type="button" data-act="sr-preview" data-id="${s.id}">Preview</button>
        <button class="btn ghost sm" type="button" data-act="sr-test" data-id="${s.id}">Send test</button>
        <button class="btn ghost sm" type="button" data-act="sr-run" data-id="${s.id}">Run now</button>
        <button class="btn ghost sm" type="button" data-act="sr-edit" data-id="${s.id}">Edit</button>
        <button class="btn ghost sm" type="button" data-act="sr-toggle" data-id="${s.id}" data-on="${s.enabled ? "1" : "0"}">${s.enabled ? "Pause" : "Resume"}</button>
        <button class="btn ghost sm" type="button" data-act="sr-duplicate" data-id="${s.id}">Duplicate</button>
        <button class="btn ghost sm" type="button" data-act="sr-delete" data-id="${s.id}">Delete</button>
      </td></tr>`;
  }).join("");
  empty($("#srSchedEmpty"), !list.length, "No schedules yet.",
    " A schedule is a pack, a set of recipients and a time. Nothing is sent until one exists, sending is enabled and the Administrator approves the list.");
}

function renderSrRecipients() {
  const list = state.sr.recipients;
  $("#srRecNote").textContent = `${plural(list.length, "recipient")}, ${list.filter(r => r.active).length} active.`;
  $("#srRecRows").innerHTML = list.map(r => `<tr>
    <td class="strong">${esc(r.email)}</td>
    <td>${esc(r.name || "–")}</td>
    <td><span class="chip ${r.group === "md" ? "ok" : r.group === "admin" ? "warn" : "off"}">${esc(SR_GROUP[r.group] || r.group)}</span></td>
    <td><span class="chip ${r.active ? "ok" : "off"}">${r.active ? "Active" : "Inactive"}</span></td>
    <td>${r.in_use ? "Used by a schedule" : "Not used yet"}</td>
    <td class="rowacts">
      <button class="btn ghost sm" type="button" data-act="sr-recipient-edit" data-id="${r.id}">Edit</button>
      <button class="btn ghost sm" type="button" data-act="sr-recipient-delete" data-id="${r.id}"${r.in_use ? " title=\"Remove it from the schedule first\"" : ""}>Remove</button>
    </td></tr>`).join("");
  empty($("#srRecEmpty"), !list.length, "No recipients yet.",
    " MD and Administrator groups are mandatory. An extra recipient can unsubscribe; the Administrator can re-enable or remove any address.");
}

function renderSrLog() {
  const list = state.sr.deliveries;
  const pack = $("#srLogPack"), keep = state.sr.logPack;
  if (pack && state.sr.status) {
    pack.innerHTML = `<option value="">All packs</option>` + state.sr.status.packs.map(p =>
      `<option value="${esc(p.key)}">${esc(p.label)}</option>`).join("");
    pack.value = state.sr.status.packs.some(p => p.key === keep) ? keep : "";
  }
  $("#srLogRows").innerHTML = list.map(d => {
    const att = Array.isArray(d.attachments) ? d.attachments : [];
    const files = att.length
      ? att.map(a => `<small>${esc(a.filename)} · ${esc(humanBytes(a.bytes))}</small>`).join("")
      : `<small>None</small>`;
    const period = d.period_from ? `${fmtDate(d.period_from)} – ${fmtDate(d.period_to)}` : "–";
    const resend = d.schedule_id != null && !["queued", "sending"].includes(d.status)
      ? `<button class="btn ghost sm" type="button" data-act="sr-resend" data-id="${d.id}">Resend</button>` : "";
    return `<tr>
      <td>${esc(fmtStamp(d.created_at))}<small>${esc(d.mode)}</small></td>
      <td><b>${esc((reportPackLabel(d.pack)))}</b>${d.subject ? `<small>${esc(d.subject.slice(0, 80))}</small>` : ""}</td>
      <td>${esc(SR_TRIGGER[d.trigger] || d.trigger)}</td>
      <td>${esc(period)}</td>
      <td class="n">${esc(d.recipient_count)}</td>
      <td>${srChip(d.status)}${d.attempts ? `<small>${plural(d.attempts, "attempt")}</small>` : ""}</td>
      <td>${files}${d.attachment_bytes ? `<small>${esc(humanBytes(d.attachment_bytes))} total</small>` : ""}</td>
      <td><small>${esc(d.error || "–")}</small></td>
      <td class="rowacts">${resend}</td></tr>`;
  }).join("");
  empty($("#srLogEmpty"), !list.length, "No deliveries match these filters.",
    " A delivery row is written when a run is queued, and its status changes as the worker picks it up.");
  $("#srLogNote").textContent = list.length ? `${list.length} shown, newest first.` : "";
}
function reportPackLabel(key) {
  const meta = state.sr.status && state.sr.status.packs.find(p => p.key === key);
  return meta ? meta.label : key;
}

async function loadDeliveries() {
  if (!srAllowed() || !state.sr.status) return;
  const q = new URLSearchParams();
  if (state.sr.logStatus) q.set("status", state.sr.logStatus);
  if (state.sr.logPack) q.set("pack", state.sr.logPack);
  q.set("limit", "200");
  const res = await api("/api/email-reports/deliveries?" + q.toString());
  if (!res.ok) { toast(res, "Delivery log not loaded"); return; }
  state.sr.deliveries = res.body || [];
  renderSrLog();
}

function scheduleForm(id) {
  if (!state.sr.status) return;
  const s = id ? state.sr.schedules.find(x => x.id === Number(id)) : null;
  if (id && !s) return;
  const f = s || {name: "", pack_key: "monthly_md", enabled: true, frequency: "monthly",
                  timezone: "Asia/Kolkata", weekdays: [0], times: ["09:00"],
                  month_day: 1, month_rule: "first_working_day", custom_cron: "",
                  holiday_rule: "shift", include_attachments: true, include_accounts: true,
                  custom_reports: [], groups: [], recipients: []};
  const packOptions = state.sr.status.packs.map(p =>
    `<option value="${esc(p.key)}"${p.key === f.pack_key ? " selected" : ""} data-accounts="${p.accounts ? "1" : "0"}">${esc(p.label)}</option>`).join("");
  const groups = new Set(f.groups || []);
  const groupBoxes = ["md", "admin", "extra"].map(g =>
    `<label style="font-weight:400"><input type="checkbox" name="group" value="${g}"${groups.has(g) ? " checked" : ""}> ${SR_GROUP[g]}</label>`).join(" ");
  const linked = new Map((f.recipients || []).map(p => [p.id, p.field]));
  const people = state.sr.recipients.length
    ? state.sr.recipients.map(p => {
        const on = linked.has(p.id);
        const field = linked.get(p.id) || "to";
        return `<tr>
          <td><input type="checkbox" name="rcpt" value="${p.id}" id="sr-r${p.id}"${on ? " checked" : ""}></td>
          <td><label for="sr-r${p.id}" style="font-weight:400">${esc(p.email)}${p.name ? ` <small>${esc(p.name)}</small>` : ""}</label>
            ${p.active ? "" : `<span class="chip off">Inactive</span>`}</td>
          <td><select data-sr-field="${p.id}" aria-label="To, CC or BCC for ${esc(p.email)}"${on ? "" : " disabled"}>
            ${["to", "cc", "bcc"].map(x => `<option value="${x}"${x === field ? " selected" : ""}>${x.toUpperCase()}</option>`).join("")}
          </select></td></tr>`;
      }).join("")
    : `<tr><td colspan="3"><small>No recipients yet. Add one on the Recipients tab.</small></td></tr>`;
  const weekly = new Set((f.weekdays || []).map(Number));
  const dayBoxes = SR_DAYS.map((name, i) =>
    `<label style="font-weight:400"><input type="checkbox" name="wd" value="${i}"${weekly.has(i) ? " checked" : ""}> ${name}</label>`).join(" ");
  const reportKeys = new Set(f.custom_reports || []);
  const reportBoxes = state.sr.status.report_catalog.map(r =>
    `<label style="font-weight:400"><input type="checkbox" name="creport" value="${esc(r.key)}"${reportKeys.has(r.key) ? " checked" : ""}> ${esc(r.title)}</label>`).join("<br>");
  openDrawer(s ? `Edit ${s.name}` : "New schedule",
    s ? s.description : "A pack, its recipients and when it runs. Every change is audited and takes effect on the next worker pass.",
    `<form id="srForm" data-id="${s ? s.id : ""}" novalidate>
      <label for="sr-name">Name</label>
      <input id="sr-name" name="name" value="${esc(f.name)}" placeholder="Monthly MD report" maxlength="120" autocomplete="off">
      <div class="row2">
        <div><label for="sr-pack">Report pack</label>
          <select id="sr-pack" name="pack_key">${packOptions}</select>
          <div class="hint" id="srPackHint"></div></div>
        <div><label for="sr-freq">Frequency</label>
          <select id="sr-freq" name="frequency">
            ${Object.entries(SR_FREQ).map(([k, label]) => `<option value="${k}"${k === f.frequency ? " selected" : ""}>${esc(label)}</option>`).join("")}
          </select></div>
      </div>
      <div class="row2">
        <div><label for="sr-times">Time(s) of day (24-hour)</label>
          <input id="sr-times" name="times" value="${esc((f.times || []).join(", "))}" placeholder="09:00, 18:00" autocomplete="off">
          <div class="hint">Comma-separated HH:MM. Several slots are allowed.</div></div>
        <div><label for="sr-tz">Timezone</label>
          <input id="sr-tz" name="timezone" value="${esc(f.timezone)}" list="srTzList" autocomplete="off">
          <datalist id="srTzList">
            <option value="Asia/Kolkata"></option><option value="Asia/Dubai"></option>
            <option value="Europe/London"></option><option value="America/New_York"></option>
            <option value="UTC"></option>
          </datalist></div>
      </div>
      <div id="sr-weekly" class="hide"><label>Weekdays</label>
        <div class="toolbar" style="padding:0;border:0;background:none;gap:12px">${dayBoxes}</div></div>
      <div id="sr-monthly" class="hide">
        <div class="row2">
          <div><label for="sr-monthrule">Monthly rule</label>
            <select id="sr-monthrule" name="month_rule">
              <option value="day"${f.month_rule === "day" ? " selected" : ""}>A chosen day</option>
              <option value="last_day"${f.month_rule === "last_day" ? " selected" : ""}>Last day of the month</option>
              <option value="first_working_day"${f.month_rule === "first_working_day" ? " selected" : ""}>First working day</option>
            </select></div>
          <div id="sr-monthday"><label for="sr-monthdayin">Day</label>
            <input id="sr-monthdayin" name="month_day" type="number" min="1" max="31" value="${esc(f.month_day == null ? 1 : f.month_day)}">
            <div class="hint">29–31 on a shorter month uses that month's last day.</div></div>
        </div>
      </div>
      <div id="sr-cron" class="hide"><label for="sr-cr">Custom cron (minute hour day month weekday)</label>
        <input id="sr-cr" name="custom_cron" value="${esc(f.custom_cron || "")}" placeholder="0 9 * * 1-5" autocomplete="off"></div>
      <label for="sr-holiday">If the slot falls on a company holiday</label>
      <select id="sr-holiday" name="holiday_rule">
        <option value="shift"${f.holiday_rule === "shift" ? " selected" : ""}>Move to the next working day</option>
        <option value="skip"${f.holiday_rule === "skip" ? " selected" : ""}>Skip that run</option>
      </select>
      <h3>Recipient groups</h3>
      <div class="toolbar" style="padding:0;border:0;background:none;gap:14px">${groupBoxes}</div>
      <div class="hint">MD and Administrator groups are mandatory report mail. Extra recipients can unsubscribe.</div>
      <h3>Named recipients</h3>
      <div class="tw"><table><tbody>${people}</tbody></table></div>
      <h3>Content</h3>
      <div class="toolbar" style="padding:0;border:0;background:none;gap:16px">
        <label style="font-weight:400"><input type="checkbox" name="include_attachments"${f.include_attachments ? " checked" : ""}> Attach PDF and Excel</label>
        <label style="font-weight:400" id="srAccountsWrap"><input type="checkbox" name="include_accounts"${f.include_accounts ? " checked" : ""}> Include the Accounts summary</label>
        <label style="font-weight:400"><input type="checkbox" name="enabled"${f.enabled ? " checked" : ""}> Schedule is on</label>
      </div>
      <div id="srCustomReports" class="hide"><label>Custom pack: reports to include</label>${reportBoxes || '<div class="hint">No report is available to this user.</div>'}</div>
      <div class="note">Figures are built by the same services as the Reports screen and the dashboards, for the pack's own period. A figure with no data is shown as “No data yet”; nothing is estimated.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">${s ? "Save schedule" : "Create schedule"}</button>
        <button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`, true);
  srFreqSync();
  srPackSync();
}

function srFreqSync() {
  const form = $("#srForm");
  if (!form) return;
  const freq = form.elements.frequency.value;
  $("#sr-weekly").classList.toggle("hide", freq !== "weekly");
  $("#sr-monthly").classList.toggle("hide", freq !== "monthly");
  $("#sr-cron").classList.toggle("hide", freq !== "custom");
  const rule = form.elements.month_rule.value;
  $("#sr-monthday").classList.toggle("hide", freq !== "monthly" || rule !== "day");
}
function srPackSync() {
  const form = $("#srForm");
  if (!form) return;
  const key = form.elements.pack_key.value;
  const meta = state.sr.status.packs.find(p => p.key === key) || {};
  const wrap = $("#srAccountsWrap");
  if (wrap) wrap.classList.toggle("hide", !meta.accounts);
  const custom = $("#srCustomReports");
  if (custom) custom.classList.toggle("hide", key !== "custom");
  const hint = $("#srPackHint");
  if (hint) hint.textContent = meta.hint || "";
}

async function saveSchedule(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const times = String(f.times.value).split(",").map(t => t.trim()).filter(Boolean);
  const weekdays = $$('input[name="wd"]:checked', form).map(x => Number(x.value));
  const recipients = $$('input[name="rcpt"]:checked', form).map(x => ({
    recipient_id: Number(x.value),
    field: $(`[data-sr-field="${x.value}"]`, form).value
  }));
  const groups = $$('input[name="group"]:checked', form).map(x => x.value);
  const customReports = $$('input[name="creport"]:checked', form).map(x => x.value);
  const body = {
    name: f.name.value.trim(),
    pack_key: f.pack_key.value,
    enabled: f.enabled.checked,
    frequency: f.frequency.value,
    timezone: f.timezone.value.trim() || "Asia/Kolkata",
    weekdays,
    times,
    month_day: f.frequency.value === "monthly" && f.month_rule.value === "day"
      ? Number(f.month_day.value) : null,
    month_rule: f.frequency.value === "monthly" ? f.month_rule.value : null,
    custom_cron: f.frequency.value === "custom" ? f.custom_cron.value.trim() : null,
    holiday_rule: f.holiday_rule.value,
    include_attachments: f.include_attachments.checked,
    include_accounts: f.include_accounts ? f.include_accounts.checked : false,
    custom_reports: customReports,
    groups,
    recipients
  };
  if (body.name.length < 2) { err.textContent = "Give the schedule a name."; return; }
  if (!times.length || times.some(t => !/^\d{1,2}:\d{2}$/.test(t))) {
    err.textContent = "Enter at least one time as HH:MM, for example 09:00."; return;
  }
  if (body.frequency === "weekly" && !weekdays.length) {
    err.textContent = "A weekly schedule needs at least one weekday."; return;
  }
  if (!recipients.length && !groups.length) {
    err.textContent = "Choose at least one recipient or group."; return;
  }
  btn.disabled = true;
  const id = form.dataset.id;
  const res = await api(id ? `/api/email-reports/schedules/${id}` : "/api/email-reports/schedules",
    {method: id ? "PATCH" : "POST", body});
  if (!res.ok) { err.textContent = detail(res.body); btn.disabled = false; return; }
  toast(res, "Schedule saved");
  closeDrawer();
  await openScheduled();
}

function recipientForm(id) {
  const r = id ? state.sr.recipients.find(x => x.id === Number(id)) : null;
  if (id && !r) return;
  openDrawer(r ? "Edit recipient" : "Add recipient",
    "An address is verified only by the first delivered message. MD and Administrator recipients are mandatory.",
    `<form id="srRecipientForm" data-id="${r ? r.id : ""}" novalidate>
      <label for="sr-r-email">Email</label>
      <input id="sr-r-email" name="email" type="email" value="${esc(r ? r.email : "")}" placeholder="name@company.com" autocomplete="off"${r ? " readonly" : ""}>
      ${r ? '<div class="hint">An address cannot be changed. Remove it and add the new one instead.</div>' : ""}
      <label for="sr-r-name">Name (optional)</label>
      <input id="sr-r-name" name="name" value="${esc(r && r.name ? r.name : "")}" autocomplete="off">
      <label for="sr-r-group">Group</label>
      <select id="sr-r-group" name="group_key">
        ${["md", "admin", "extra"].map(g => `<option value="${g}"${r && r.group === g ? " selected" : ""}>${SR_GROUP[g]}</option>`).join("")}
      </select>
      ${r ? `<label for="sr-r-active" style="font-weight:400;margin-top:14px"><input id="sr-r-active" type="checkbox" name="active"${r.active ? " checked" : ""}> Active</label>` : ""}
      <div class="note">The unsubscribe link in every email works only for an extra recipient. Removing an address from this list does not erase the delivery log.</div>
      <div class="err" role="alert"></div>
      <div class="actions"><button class="btn" type="submit">${r ? "Save recipient" : "Add recipient"}</button>
        <button class="btn ghost" type="button" data-act="close">Cancel</button></div>
    </form>`);
}

async function saveRecipient(form) {
  const f = form.elements, err = $(".err", form), btn = $("button[type=submit]", form);
  err.textContent = "";
  const id = form.dataset.id;
  if (!id && !f.email.value.trim()) { err.textContent = "Enter an email address."; return; }
  btn.disabled = true;
  const body = id
    ? {name: f.name.value.trim() || null, group_key: f.group_key.value, active: f.active.checked}
    : {email: f.email.value.trim(), name: f.name.value.trim() || null, group_key: f.group_key.value};
  const res = await api(id ? `/api/email-reports/recipients/${id}` : "/api/email-reports/recipients",
    {method: id ? "PATCH" : "POST", body});
  if (!res.ok) { err.textContent = detail(res.body); btn.disabled = false; return; }
  toast(res, "Recipient saved");
  closeDrawer();
  await openScheduled();
}

async function srRun(id) {
  const s = state.sr.schedules.find(x => x.id === Number(id));
  const live = state.sr.status && state.sr.status.mode === "live" && state.sr.status.send_enabled;
  if (live && !confirm(`Queue “${s ? s.name : "this schedule"}” now? It will be sent to its real recipients.`)) return;
  const res = await api(`/api/email-reports/schedules/${id}/run-now`, {method: "POST"});
  toast(res, res.ok ? "Queued. The worker will send it." : "Not queued");
  if (res.ok) { state.sr.tab = "log"; await openScheduled(); }
}
async function srTest(id) {
  const res = await api(`/api/email-reports/schedules/${id}/test`, {method: "POST"});
  toast(res, res.ok ? `Test queued. It goes only to ${(res.body && res.body.redirected_to) || "the Administrator"}.` : "Test not queued");
  if (res.ok) { state.sr.tab = "log"; await openScheduled(); }
}
function srPreview(id) {
  window.open(`/api/email-reports/schedules/${id}/preview`, "_blank", "noopener");
}
async function srToggle(id, enabled) {
  const res = await api(`/api/email-reports/schedules/${id}/enable`,
    {method: "POST", body: {enabled: !enabled}});
  toast(res, res.ok ? (enabled ? "Schedule paused" : "Schedule resumed") : "Not changed");
  if (res.ok) await openScheduled();
}
async function srDuplicate(id) {
  const res = await api(`/api/email-reports/schedules/${id}/duplicate`, {method: "POST"});
  toast(res, res.ok ? "Copy created, paused" : "Not copied");
  if (res.ok) await openScheduled();
}
async function srDelete(id) {
  const s = state.sr.schedules.find(x => x.id === Number(id));
  if (!confirm(`Delete “${s ? s.name : "this schedule"}”? Past sends stay in the delivery log.`)) return;
  const res = await api(`/api/email-reports/schedules/${id}`, {method: "DELETE"});
  toast(res, res.ok ? "Schedule deleted" : "Not deleted");
  if (res.ok) await openScheduled();
}
async function srResend(id) {
  const live = state.sr.status && state.sr.status.mode === "live" && state.sr.status.send_enabled;
  if (live && !confirm("Resend this report now? It will be sent to its real recipients.")) return;
  const res = await api(`/api/email-reports/deliveries/${id}/resend`, {method: "POST"});
  toast(res, res.ok ? "Resend queued" : "Not queued");
  if (res.ok) await loadDeliveries();
}
async function srRecipientDelete(id) {
  const r = state.sr.recipients.find(x => x.id === Number(id));
  if (r && r.in_use) {
    alert("This address is used by a schedule. Remove it from that schedule first.");
    return;
  }
  if (!confirm(`Remove ${r ? r.email : "this address"} from the recipient list?`)) return;
  const res = await api(`/api/email-reports/recipients/${id}`, {method: "DELETE"});
  toast(res, res.ok ? "Recipient removed" : "Not removed");
  if (res.ok) await openScheduled();
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
  const modeBtn = e.target.closest("[data-cmp-mode]");
  if (modeBtn) return setCompareMode(modeBtn.dataset.cmpMode);
  const accModeBtn = e.target.closest("[data-acc-mode]");
  if (accModeBtn) return setAccMode(accModeBtn.dataset.accMode);
  const accStateBtn = e.target.closest("[data-acc-state]");
  if (accStateBtn) return setAccStateFilter(accStateBtn.dataset.accState);
  const expStatusBtn = e.target.closest("[data-exp-status]");
  if (expStatusBtn) return setExpenseStatus(expStatusBtn.dataset.expStatus);
  const geoTile = e.target.closest("[data-geo-code]");
  if (geoTile) return selectGeo(geoTile.dataset.geoCode);
  const geoSortBtn = e.target.closest("[data-geo-sort]");
  if (geoSortBtn) return setGeoSort(geoSortBtn.dataset.geoSort);
  const srTabBtn = e.target.closest("[data-sr-tab]");
  if (srTabBtn) return srTab(srTabBtn.dataset.srTab);
  const hrRangeBtn = e.target.closest("[data-hrr]");
  if (hrRangeBtn) return setHrRangePreset(hrRangeBtn.dataset.hrr);
  const hrpTab = e.target.closest("[data-hrp]");
  if (hrpTab) return hrProfileDrawer(hrpTab.dataset.hrp);
  const a = e.target.closest("[data-act]");
  const lp = e.target.closest("[data-act='list-page']");
  if (lp) {
    return lp.dataset.list === "products" ? productListPage(lp.dataset.page)
      : listGo(lp.dataset.list, lp.dataset.page);
  }
  if (a && a.dataset.act === "nav-retry") return navRefresh();
  if (a && a.dataset.act === "reset-db") return dbResetOpen();
  if (a && a.dataset.act === "dbreset-backup") return dbResetBackup();
  if (a && a.dataset.act === "dbreset-verify") return dbResetVerify();
  if (a && a.dataset.act === "dbreset-cancel") return dbResetCancel();
  if (a && a.dataset.act === "new-entry") return entryForm(a.dataset.kind || "receipt");
  if (a && a.dataset.act === "signin-banner-new") return signinBannerForm();
  if (a && a.dataset.act === "signin-banner-edit") return signinBannerForm(Number(a.dataset.id));
  if (a && a.dataset.act === "signin-banner-delete") return deleteSigninBanner(Number(a.dataset.id));
  if (a && a.dataset.act === "signin-notice-new") return signinNoticeForm();
  if (a && a.dataset.act === "signin-notice-edit") return signinNoticeForm(Number(a.dataset.id));
  if (a && a.dataset.act === "signin-notice-delete") return deleteSigninNotice(Number(a.dataset.id));
  if (a && a.dataset.act === "signin-contact-new") return signinContactForm();
  if (a && a.dataset.act === "signin-contact-edit") return signinContactForm(Number(a.dataset.id));
  if (a && a.dataset.act === "signin-contact-delete") return deleteSigninContact(Number(a.dataset.id));
  if (a && a.dataset.act === "signin-legal-edit") return signinLegalForm(a.dataset.key);
  if (a && a.dataset.act === "load-gst") return loadGstRegister();
  if (a && a.dataset.act === "load-entries") return loadEntriesWindow();
  if (a && a.dataset.act === "load-tb") return loadTrialBalance();
  if (a && a.dataset.act === "load-input-gst") return loadInputGst();
  if (a && a.dataset.act === "new-purchase-invoice") return newPurchaseInvoice();
  if (a && a.dataset.act === "reverse-purchase-invoice") return reversePurchaseInvoice(a.dataset.id);
  if (a && a.dataset.act === "load-reconciliation") return loadReconciliation();
  if (a && a.dataset.act === "new-gst-return") return newGstReturn();
  if (a && a.dataset.act === "load-dues") return loadStatutory();
  if (a && a.dataset.act === "new-challan") return newChallan();
  if (a && a.dataset.act === "load-ageing") return loadAgeing();
  if (a && a.dataset.act === "load-rbd") return applyRbdFilter();
  if (a && a.dataset.act === "export-rbd") return exportRbdCsv();
  if (a && a.dataset.act === "periods-refresh") return loadPeriods();
  if (a && a.dataset.act === "fy-close") return closeFinancialYear(a.dataset.fy);
  if (a && a.dataset.act === "fy-reopen") return reopenFinancialYear(a.dataset.fy);
  if (a && a.dataset.act === "lock-month") return lockAccountingMonth();
  if (a && a.dataset.act === "lock-unlock") return unlockAccountingMonth(a.dataset.id);
  if (a && a.dataset.act === "load-acc-report") return loadAccountsReport();
  if (a && a.dataset.act === "export-acc") return exportAccCsv();
  if (a && a.dataset.act === "export-ar") return exportReceivablesCsv();
  if (a && a.dataset.act === "export-ageing") return exportAgeingCsv();
  if (a && a.dataset.act === "export-ap") return exportPayablesCsv();
  if (a && a.dataset.act === "export-entries") return exportEntriesCsv();
  if (a && a.dataset.act === "export-gst-out") return exportGstRegisterCsv();
  if (a && a.dataset.act === "export-gst-in") return exportInputGstCsv();
  if (a && a.dataset.act === "export-statutory") return exportStatutoryCsv();
  if (a && a.dataset.act === "export-tb") return exportTrialBalanceCsv();
  if (a && a.dataset.act === "export-ledger-heads") return exportLedgerHeadsCsv();
  if (a && a.dataset.act === "export-openings") return exportOpeningsCsv();
  if (a && a.dataset.act === "export-balance-sheet") return exportBalanceSheetCsv();
  if (a && a.dataset.act === "export-vouchers") return exportVouchersCsv();
  if (a && a.dataset.act === "export-daybook") return exportDayBookCsv();
  if (a && a.dataset.act === "export-bank") return exportBankCsv();
  if (a && a.dataset.act === "export-years") return exportYearsCsv();
  if (a && a.dataset.act === "export-locks") return exportLocksCsv();
  if (a && a.dataset.act === "foc-export-stock") return exportFocStockCsv();
  if (a && a.dataset.act === "foc-export-notes") return exportFocNotesCsv();
  if (a && a.dataset.act === "acc-ledger") return openDistributorLedger(a.dataset.id);
  if (a && a.dataset.act === "load-ledger-heads") return loadLedgerHeads();
  if (a && a.dataset.act === "new-ledger-head") return newLedgerHead();
  if (a && a.dataset.act === "ledger-head-toggle") return toggleLedgerHead(a.dataset.id, a.dataset.on === "1");
  if (a && a.dataset.act === "load-openings") return loadOpenings();
  if (a && a.dataset.act === "edit-opening") return editOpening(a.dataset.id);
  if (a && a.dataset.act === "load-bs") return loadBalanceSheet();
  if (a && a.dataset.act === "load-vouchers") return loadVouchers();
  if (a && a.dataset.act === "new-voucher") return voucherForm();
  if (a && a.dataset.act === "edit-voucher") {
    const v = (state.accounts.ledger.vouchers || []).find(x => String(x.id) === String(a.dataset.id));
    return v ? voucherForm(v) : toast({ok: false, status: "—", body: {detail: "Reload the vouchers first"}}, "Voucher not found");
  }
  if (a && a.dataset.act === "voucher-add-line") return addVoucherLine();
  if (a && a.dataset.act === "voucher-remove-line") return removeVoucherLine(a);
  if (a && a.dataset.act === "post-voucher") return postVoucher(a.dataset.id);
  if (a && a.dataset.act === "delete-voucher") return deleteVoucher(a.dataset.id);
  if (a && a.dataset.act === "reverse-voucher") return reverseVoucherForm(a.dataset.id);
  if (a && a.dataset.act === "load-daybook") return loadDayBook();
  if (a && a.dataset.act === "load-bank-statements") return loadBankStatements();
  if (a && a.dataset.act === "new-bank-statement") return newBankStatement();
  if (a && a.dataset.act === "open-bank-statement") return openBankStatement(a.dataset.id);
  if (a && a.dataset.act === "bank-line-add") return addBankLineForm();
  if (a && a.dataset.act === "bank-edit-statement") return editBankStatementForm();
  if (a && a.dataset.act === "bank-delete-statement") return deleteBankStatement();
  if (a && a.dataset.act === "bank-line-match") return bankMatchDrawer(a.dataset.id);
  if (a && a.dataset.act === "bank-match") return bankMatch(a.dataset.line, a.dataset.kind, a.dataset.ref);
  if (a && a.dataset.act === "bank-line-unmatch") return bankUnmatch(a.dataset.id);
  if (a && a.dataset.act === "bank-line-delete") return deleteBankLine(a.dataset.id);
  if (a && a.dataset.act === "exp-refresh") return loadExpenses();
  if (a && a.dataset.act === "new-expense") return openExpenseForm();
  if (a && a.dataset.act === "exp-heads") return openExpenseHeads();
  if (a && a.dataset.act === "exp-settings") return openExpenseSettings();
  if (a && a.dataset.act === "exp-reverse") return expenseReverseForm(a.dataset.id);
  if (a && a.dataset.act === "exp-receipt") return expenseReceiptForm(a.dataset.id);
  if (a && a.dataset.act === "exp-head-toggle") return toggleExpenseHead(a.dataset.id, a.dataset.on === "1");
  if (a && a.dataset.act === "foc-refresh") return loadFoc();
  if (a && a.dataset.act === "new-foc") return focNewForm();
  if (a && a.dataset.act === "foc-approve") return focApprove(a.dataset.id);
  if (a && a.dataset.act === "foc-reject") return focReasonForm(a.dataset.id, "reject");
  if (a && a.dataset.act === "foc-reverse") return focReasonForm(a.dataset.id, "reverse");
  if (a && a.dataset.act === "open-search") return openPalette();
  if (a && a.dataset.act === "reload-dash") return loadDashboard();
  if (a && a.dataset.act === "reload-compare") return loadCompare();
  if (a && a.dataset.act === "cmp-csv") return exportCompareCsv();
  if (a && a.dataset.act === "reload-geo") return loadGeo();
  if (a && a.dataset.act === "geo-csv") return exportGeoCsv();
  if (a && a.dataset.act === "toggle-series") return toggleSeries(a.dataset.series);
  if (a && a.dataset.act === "dash-ap") return dashOpenApproval(a.dataset.id);
  if (a && a.dataset.act === "dash-approve") return dashApprove(a.dataset.id);
  if (a && a.dataset.act === "dash-reject") {
    dashRejectId = Number(a.dataset.id);
    renderDashApprovals(state.dashboard && state.dashboard.approvals);
    const inp = $("#dashRejectForm input");
    if (inp) inp.focus();
    return;
  }
  if (a && a.dataset.act === "dash-reject-cancel") {
    dashRejectId = null;
    return renderDashApprovals(state.dashboard && state.dashboard.approvals);
  }
  if (a && a.dataset.act === "expiry-detail") return expiryDetail(a.dataset.id);
  if (a) {
    const act = a.dataset.act;
    if (act === "close") closeDrawer();
    else if (act === "new-product") productForm();
    else if (act === "open-product") productDrawer(a.dataset.id, "open");
    else if (act === "edit-product") productForm(a.dataset.id);
    else if (act === "save-product") productForm(a.dataset.id);
    else if (act === "search-products") {
      clearTimeout(state.plist.timer);
      state.plist.q = ($("#pq").value || "").trim();
      loadProductList(1);
    }
    else if (act === "clear-products") {
      clearTimeout(state.plist.timer);
      state.plist.q = ""; state.plist.status = "";
      $("#pq").value = ""; $("#pstat").value = "";
      loadProductList(1);
    }
    else if (act === "export-products") exportProductsCsv();
    else if (act === "sort-products") productSort(a.dataset.sort);
    else if (act === "search-list") searchList(a.dataset.list);
    else if (act === "clear-list") clearList(a.dataset.list);
    else if (act === "export-list") exportListCsv(a.dataset.list);
    else if (act === "new-so-dist") { state.soDistPreset = Number(a.dataset.id); soForm(); }
    else if (act === "hr-employees") hrEmployees();
    else if (act === "hr-range-apply") applyHrRange();
    else if (act === "hr-refresh") openHr();
    else if (act === "hr-filter-apply") applyHrFilter();
    else if (act === "hr-filter-save") hrFilterSaveForm();
    else if (act === "hr-filter-cancel") { $("#hrSavedBox").innerHTML = ""; }
    else if (act === "hr-filter-delete") deleteHrFilter();
    else if (act === "hr-export") exportHr();
    else if (act === "hr-profile") hrProfile(a.dataset.id);
    else if (act === "hr-profile-tab") hrProfileDrawer(a.dataset.tab);
    else if (act === "hr-doc-new") hrDocForm(a.dataset.id);
    else if (act === "hr-doc-edit") hrDocForm(state.hr.profile && state.hr.profile.employee.id, a.dataset.id);
    else if (act === "hr-asset-new") hrAssetForm(a.dataset.id);
    else if (act === "hr-asset-return") hrAssetReturnForm(a.dataset.id);
    else if (act === "hr-attention") hrAttention(a.dataset.kind);
    else if (act === "hr-monthly") hrMonthly();
    else if (act === "hr-monthly-refresh") loadHrMx();
    else if (act === "hr-sheet") downloadAttendanceSheet();
    else if (act === "hr-letters") hrLetters();
    else if (act === "hr-letter-edit") hrLetterForm(a.dataset.id);
    else if (act === "hr-card") downloadOutput("/api/hr/outputs/id-card" + (a.dataset.emp ? `?employee_id=${a.dataset.emp}` : ""));
    else if (act === "hr-statement") downloadOutput("/api/hr/outputs/leave-statement" + (a.dataset.emp ? `?employee_id=${a.dataset.emp}` : ""));
    else if (act === "hr-letter") downloadOutput(`/api/hr/outputs/letter/${encodeURIComponent(a.dataset.code)}` + (a.dataset.emp ? `?employee_id=${a.dataset.emp}` : ""));
    else if (act === "hr-calendar") hrCalendar();
    else if (act === "hr-calendar-refresh") loadHrCal();
    else if (act === "hr-reports") hrReports();
    else if (act === "hr-report-refresh") hrReportView(state.hr.repKey);
    else if (act === "hr-report-view") hrReportView(a.dataset.key);
    else if (act === "hr-report-file") hrReportFile(a.dataset.key, a.dataset.format);
    else if (act === "hr-notices") hrNotices();
    else if (act === "hr-notice-hide") api(`/api/hr/announcements/${a.dataset.id}`, {method: "PATCH", body: {active: false}}).then(r => { toast(r, r.ok ? "Announcement hidden" : "Not changed"); if (r.ok) hrNotices(); });
    else if (act === "hr-digest") api("/api/hr/notifications/digest", {method: "POST", body: {}}).then(r => { toast(r, r.ok ? `Digest queued for ${r.body.queued}; ${r.body.skipped} already had one` : "Digest not sent"); if (r.ok) refreshHrUnread(); });
    else if (act === "hr-locks") hrLocks();
    else if (act === "hr-lock-unlock") hrLocks(Number(a.dataset.id));
    else if (act === "hr-import") hrImport();
    else if (act === "hr-import-check") hrImportCheck();
    else if (act === "hr-import-commit") hrImportCommit();
    else if (act === "hr-import-undo") hrImportUndo(a.dataset.id);
    else if (act === "hr-notifications") hrNotifications();
    else if (act === "hr-notes-readall") api("/api/hr/notifications/read-all", {method: "POST", body: {}}).then(r => { toast(r, r.ok ? `${r.body.marked} notification(s) marked read` : "Not changed"); if (r.ok) hrNotifications(); });
    else if (act === "hr-note-read") api(`/api/hr/notifications/${a.dataset.id}/read`, {method: "POST", body: {}}).then(r => { if (r.ok) hrNotifications(); else toast(r, "Not changed"); });
    else if (act === "hr-payslips") hrPayslips();
    else if (act === "hr-shifts") hrShifts();
    else if (act === "hr-new-shift") hrShiftForm();
    else if (act === "hr-edit-shift") hrShiftForm(a.dataset.id);
    else if (act === "hr-sites") hrSites();
    else if (act === "hr-masters") hrMasters(a.dataset.tab);
    else if (act === "hr-masters-tab") hrMasters(a.dataset.tab);
    else if (act === "hr-new-dept") hrDepartmentForm();
    else if (act === "hr-edit-dept") hrDepartmentForm(a.dataset.id);
    else if (act === "hr-new-holiday") hrHolidayForm();
    else if (act === "hr-edit-holiday") hrHolidayForm(a.dataset.id);
    else if (act === "hr-new-leave-type") hrLeaveTypeForm();
    else if (act === "hr-edit-leave-type") hrLeaveTypeForm(a.dataset.id);
    else if (act === "hr-new-component") hrComponentForm();
    else if (act === "hr-edit-component") hrComponentForm(a.dataset.id);
    else if (act === "hr-new-structure") hrSalaryStructureForm(a.dataset.emp || null);
    else if (act === "hr-new-branch") hrBranchForm();
    else if (act === "hr-edit-branch") hrBranchForm(a.dataset.id);
    else if (act === "hr-new-office") hrOfficeForm();
    else if (act === "hr-edit-office") hrOfficeForm(a.dataset.id);
    else if (act === "hr-new-rule") hrRuleForm();
    else if (act === "hr-edit-rule") hrRuleForm(a.dataset.id);
    else if (act === "hr-rule-delete") hrRuleDelete(a.dataset.id);
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
    else if (act === "edit-capacity") capacityForm(a.dataset.id);
    else if (act === "new-po") poForm();
    else if (act === "open-po") ensureCached("pos", `/api/purchase-orders/${a.dataset.id}`, a.dataset.id).then(x => { if (x) poDetail(x.id); });
    else if (act === "cancel-po") cancelPoForm(a.dataset.id);
    else if (act === "new-supplier") supplierForm();
    else if (act === "open-supplier") ensureCached("suppliers", `/api/suppliers/${a.dataset.id}`, a.dataset.id).then(x => { if (x) supplierDetail(x.id); });
    else if (act === "toggle-supplier") toggleSupplier(a.dataset.id);
    else if (act === "decide-bank") decideBankForm(a.dataset.id);
    else if (act === "add-line") { $("#plines").insertAdjacentHTML("beforeend", lineRow(true)); syncPoLines(); $("#plines").lastElementChild.querySelector("select").focus(); }
    else if (act === "rm-line") { a.closest("[data-line]").remove(); syncPoLines(); }
    else if (act === "goto-wh") { closeDrawer(); location.hash = "#/inventory/warehouses"; }
    else if (act === "new-so") soForm();
    else if (act === "open-so") ensureCached("orders", `/api/sales-orders/${a.dataset.id}`, a.dataset.id).then(x => { if (x) soDetail(x.id); });
    else if (act === "submit-so") submitSO(a.dataset.id);
    else if (act === "open-ap") ensureCached("approvals", `/api/approvals/${a.dataset.id}`, a.dataset.id).then(x => { if (x) apDetail(x.id); });
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
    else if (act === "toggle-feature") toggleFeature(a.dataset.key, a.dataset.enabled);
    else if (act === "new-employee") employeeForm();
    else if (act === "edit-emp") employeeForm(a.dataset.id);
    else if (act === "edit-company") companyForm();
    else if (act === "new-rate") rateForm();
    else if (act === "close-rate") closeRateForm(a.dataset.id);
    else if (act === "new-slab") slabForm();
    else if (act === "edit-slab") editSlabForm(a.dataset.id);
    else if (act === "open-inv") ensureCached("invoices", `/api/invoices/${a.dataset.id}`, a.dataset.id).then(x => { if (x) invDetail(x.id); });
    else if (act === "print-inv") printDocument("invoice", Number(a.dataset.id), "ORIGINAL");
    else if (act === "open-note") noteDetail(a.dataset.kind, Number(a.dataset.id));
    else if (act === "print-note" && can("print:document"))
      printDocument(a.dataset.kind, Number(a.dataset.id), "ORIGINAL");
    else if (act === "print-copy") {
      const chosen = $("#printCopy");
      printDocument(a.dataset.kind, Number(a.dataset.id), chosen ? chosen.value : "ORIGINAL");
    }
    else if (act === "sr-new") scheduleForm();
    else if (act === "sr-edit") scheduleForm(a.dataset.id);
    else if (act === "sr-preview") srPreview(a.dataset.id);
    else if (act === "sr-test") srTest(a.dataset.id);
    else if (act === "sr-run") srRun(a.dataset.id);
    else if (act === "sr-toggle") srToggle(a.dataset.id, a.dataset.on === "1");
    else if (act === "sr-duplicate") srDuplicate(a.dataset.id);
    else if (act === "sr-delete") srDelete(a.dataset.id);
    else if (act === "sr-resend") srResend(a.dataset.id);
    else if (act === "sr-recipient-new") recipientForm();
    else if (act === "sr-recipient-edit") recipientForm(a.dataset.id);
    else if (act === "sr-recipient-delete") srRecipientDelete(a.dataset.id);
    else if (act === "sr-refresh-log") loadDeliveries();
    else if (act === "email-reload") loadEmailSettings(true);
    return;
  }
  const tab = e.target.closest("[data-tab]");
  if (tab) { location.hash = "#/inventory/" + tab.dataset.tab; return; }
  const dp = e.target.closest("[data-dash-preset]");
  if (dp) { setDashPreset(dp.dataset.dashPreset); return; }
  const expb = e.target.closest("[data-eb]");
  if (expb) { setExpiryBucket(expb.dataset.eb); return; }
  const pf = e.target.closest("[data-pf]");
  if (pf) { state.poFilter = pf.dataset.pf; pressSeg("pf", pf.dataset.pf); loadList("purchasing", 1); return; }
  const inf = e.target.closest("[data-if]");
  if (inf) { state.invFilter = inf.dataset["if"]; pressSeg("if", inf.dataset["if"]); loadList("billing", 1); return; }
  const spf = e.target.closest("[data-sf2]");
  if (spf) { state.supFilter = spf.dataset.sf2; pressSeg("sf2", spf.dataset.sf2); loadList("suppliers", 1); return; }
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
  if (lf) { state.ldFilter = lf.dataset.lf; pressSeg("lf", lf.dataset.lf); loadList("leads", 1); return; }
  const lo = e.target.closest("[data-lo]");
  if (lo) { state.ldOwner = lo.dataset.lo; pressSeg("lo", lo.dataset.lo); loadList("leads", 1); return; }
  const lr = e.target.closest("tr[data-ld]");
  if (lr) { leadDetail(lr.dataset.ld); return; }
  const sf = e.target.closest("[data-sf]");
  if (sf) { state.soFilter = sf.dataset.sf; pressSeg("sf", sf.dataset.sf); loadList("sales", 1); return; }
  const af = e.target.closest("[data-af]");
  if (af) { state.apFilter = af.dataset.af; pressSeg("af", af.dataset.af); loadList("approvals", 1); return; }
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
  else if (f.id === "totpForm") totpSubmit(e);
  else if (f.id === "prodForm") saveProduct(f);
  else if (f.id === "whForm") saveWarehouse(f);
  else if (f.id === "capForm") saveCapacity(f);
  else if (f.id === "poForm") savePO(f);
  else if (f.id === "rcvForm") postReceipt(f);
  else if (f.id === "poCancel") cancelPo(f);
  else if (f.id === "supForm") saveSupplier(f);
  else if (f.id === "bankForm") requestBankChange(f);
  else if (f.id === "bankDecide") decideBank(f, (e.submitter && e.submitter.dataset.decide) || "approve");
  else if (f.id === "soForm") saveSO(f);
  else if (f.id === "soPromiseForm") saveSoPromise(f, e);
  else if (f.id === "cancelForm") cancelSO(f);
  else if (f.id === "dispForm") postDispatch(f);
  else if (f.id === "decideForm") decide(f, (e.submitter && e.submitter.value) || "approve");
  else if (f.id === "dashRejectForm") sendDashReject(f);
  else if (f.id === "distForm") saveDist(f);
  else if (f.id === "moveForm") saveInvoiceMovement(f);
  else if (f.id === "amendReqForm") requestInvoiceAmendment(f);
  else if (f.id === "invCancelForm") cancelInvoice(f);
  else if (f.id === "cnForm") issueNote(f, "cn");
  else if (f.id === "dnForm") issueNote(f, "dn");
  else if (f.id === "limitForm") saveLimit(f);
  else if (f.id === "verifyForm") submitVerification(f);
  else if (f.id === "entryForm") saveEntry(f);
  else if (f.id === "piForm") savePurchaseInvoice(f);
  else if (f.id === "piReverseForm") savePurchaseInvoiceReverse(f);
  else if (f.id === "obForm") saveOpening(f);
  else if (f.id === "ledgerHeadForm") saveLedgerHead(f);
  else if (f.id === "voucherForm") saveVoucher(f);
  else if (f.id === "voucherReverseForm") saveVoucherReverse(f);
  else if (f.id === "bankStatementForm") saveBankStatement(f);
  else if (f.id === "bankLineForm") saveBankLine(f);
  else if (f.id === "bankEditForm") saveBankEdit(f);
  else if (f.id === "grForm") saveGstReturn(f);
  else if (f.id === "chForm") saveChallan(f);
  else if (f.id === "expForm") saveExpense(f);
  else if (f.id === "expReceiptForm") saveExpenseReceipt(f);
  else if (f.id === "expReverseForm") saveExpenseReverse(f);
  else if (f.id === "expHeadForm") saveExpenseHead(f);
  else if (f.id === "expSettingsForm") saveExpenseSettings(f);
  else if (f.id === "signinBannerForm") saveSigninBanner(f);
  else if (f.id === "signinNoticeForm") saveSigninNotice(f);
  else if (f.id === "signinContactForm") saveSigninContact(f);
  else if (f.id === "signinLegalForm") saveSigninLegal(f);
  else if (f.id === "focForm") saveFocNote(f);
  else if (f.id === "focReasonForm") saveFocReason(f);
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
  else if (f.id === "hrDeptForm") saveHrDepartment(f);
  else if (f.id === "hrHolidayForm") saveHrHoliday(f);
  else if (f.id === "hrLeaveTypeForm") saveHrLeaveType(f);
  else if (f.id === "hrComponentForm") saveHrComponent(f);
  else if (f.id === "hrStructureForm") saveHrStructure(f);
  else if (f.id === "hrBranchForm") saveHrBranch(f);
  else if (f.id === "hrOfficeForm") saveHrOffice(f);
  else if (f.id === "hrRuleForm") saveHrRule(f);
  else if (f.id === "hrManualForm") saveManualAttendance(f);
  else if (f.id === "hrLeaveForm") saveHrLeave(f);
  else if (f.id === "hrOdForm") saveHrOd(f);
  else if (f.id === "hrPeriodForm") saveHrPeriod(f);
  else if (f.id === "hrDocForm") saveHrDoc(f);
  else if (f.id === "hrAssetForm") saveHrAsset(f);
  else if (f.id === "hrAssetReturnForm") saveHrAssetReturn(f);
  else if (f.id === "hrNoticeForm") saveHrNotice(f);
  else if (f.id === "hrLockForm") saveHrLock(f);
  else if (f.id === "hrUnlockForm") saveHrUnlock(f);
  else if (f.id === "hrSavedForm") saveHrFilter(f);
  else if (f.id === "hrLetForm") saveHrLetterTemplate(f);
  else if (f.id === "srForm") saveSchedule(f);
  else if (f.id === "srRecipientForm") saveRecipient(f);
  else if (f.id === "emailSettingsForm") saveEmailSettings(f);
  else if (f.id === "emailTestForm") sendEmailTest(f);
  else if (f.id === "dbResetForm1") dbResetBegin(f);
  else if (f.id === "dbResetForm4") dbResetExecute(f);
});
document.addEventListener("input", e => {
  if (e.target.closest("#poForm")) syncPoLines();
  if (e.target.closest("#soForm")) syncSoLines();
  if (e.target.id === "lostq") renderLost();
  if (e.target.id === "fuq") renderFollowups();
  const listHit = Object.entries(LIST_SPEC).find(([, v]) => v.input === e.target.id);
  if (listHit) {
    const [key] = listHit, s = listState(key);
    clearTimeout(s.timer);
    s.q = e.target.value.trim();
    s.timer = setTimeout(() => loadList(key, 1), 300);
  }
  if (e.target.id === "pq") {
    clearTimeout(state.plist.timer);
    state.plist.q = e.target.value.trim();
    state.plist.timer = setTimeout(() => loadProductList(1), 300);
  }
  if (e.target.id === "rpq") { state.rpSearch = e.target.value; drawRpTabs(); }
  if (e.target.id === "hrq") renderHrDirectory();
  if (e.target.id === "expq") {
    clearTimeout(state.exp.timer);
    state.exp.q = e.target.value.trim();
    state.exp.timer = setTimeout(loadExpenses, 300);
  }
});
document.addEventListener("change", e => {
  if (e.target.closest("#poForm")) syncPoLines();
  if (e.target.closest("#roleForm") && e.target.name === "perm") {
    syncPermissionTree(e.target.closest("form"));
  }
  if (e.target.id === "rpCategory") { state.rpCategory = e.target.value; drawRpTabs(); }
  if (e.target.id === "em-type") applyEmailType(true);
  if (e.target.id === "cmpMonth") setCompareMonth(e.target.value);
  if (e.target.id === "geoFrom" || e.target.id === "geoTo") {
    applyGeoDates($("#geoFrom").value, $("#geoTo").value);
  }
  if (e.target.id === "hrStatus" || e.target.id === "hrDept") renderHrDirectory();
  if (e.target.id === "expHead") setExpenseHead(e.target.value);
  if (e.target.id === "expFrom" || e.target.id === "expTo") loadExpenses();
  if (e.target.id === "pstat") {
    clearTimeout(state.plist.timer);
    state.plist.status = e.target.value;
    loadProductList(1);
  }
  if (e.target.dataset.act === "list-size") {
    const key = e.target.dataset.list || "products";
    const size = Number(e.target.value) || 50;
    if (key === "products") { state.plist.size = size; loadProductList(1); }
    else { listState(key).size = size; loadList(key, 1); }
  }
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
  if (e.key === "Escape") { if (!requestCloseDrawer()) e.preventDefault(); return; }
  if (e.key === "Tab") {                                   // keep focus inside the open drawer
    const f = $$("#drawer button:not([disabled]),#drawer input,#drawer select,#drawer a[href]").filter(x => x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});
/* One missing marker must not stop the rest of the page from booting: bind only
   when the element is there, so a stale markup/cache pair degrades to one dead
   control instead of a blank screen. */
const bind = (sel, event, fn) => { const el = typeof sel === "string" ? $(sel) : sel; if (el) el.addEventListener(event, fn); return el; };
bind("#scrim", "click", () => requestCloseDrawer());
bind("#dclose", "click", () => requestCloseDrawer());
window.addEventListener("resize", () => { fitDrawerTables(); fitTabs(); });

/* Workspace tabs: click, keyboard, overflow menu and favourites. */
bind("#tabstrip", "click", e => {
  const close = e.target.closest("[data-act='tab-close']");
  if (close) { e.stopPropagation(); wsCloseTab(close.dataset.key); return; }
  const tab = e.target.closest(".tab");
  if (tab) wsActivate(tab.dataset.key);
});
bind("#tabstrip", "keydown", e => {
  const strip = $("#tabstrip");
  if (!strip) return;
  const tabs = $$(".tab", strip);
  if (!tabs.length) return;
  const current = document.activeElement.closest(".tab");
  const i = tabs.indexOf(current);
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    e.preventDefault();
    const j = i < 0 ? 0 : (e.key === "ArrowRight" ? (i + 1) % tabs.length : (i - 1 + tabs.length) % tabs.length);
    tabs[j].focus();
    wsActivate(tabs[j].dataset.key);
  } else if (e.key === "Home" || e.key === "End") {
    e.preventDefault();
    const j = e.key === "Home" ? 0 : tabs.length - 1;
    tabs[j].focus();
    wsActivate(tabs[j].dataset.key);
  } else if ((e.key === "Delete" || e.key === "Backspace") && current && current.dataset.key !== WS.HOME) {
    e.preventDefault();
    wsCloseTab(current.dataset.key);
  }
});
bind("#tabMore", "click", e => { e.stopPropagation(); toggleTabMenu(); });
bind("#tabMenu", "click", e => {
  const btn = e.target.closest("[data-act]");
  if (!btn || btn.disabled) return;
  const act = btn.dataset.act, key = btn.dataset.key;
  if (act === "tab-go") wsActivate(key);
  else if (act === "tab-close") { closeTabMenu(); wsCloseTab(key); }
  else if (act === "tab-close-others") { closeTabMenu(); wsCloseSiblings(wsModel ? wsModel.active : WS.HOME); }
  else if (act === "tab-close-all") { closeTabMenu(); wsCloseSiblings(WS.HOME); }
  else if (act === "tab-reopen") { closeTabMenu(); wsReopen(); }
});
document.addEventListener("click", e => {
  if (!e.target.closest("#tabMenu, #tabMore")) closeTabMenu();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !$("#tabMenu").classList.contains("hide")) { e.preventDefault(); closeTabMenu(); }
});
bind("#favBtn", "click", () => {
  const key = wsCurrentKey();
  if (key === WS.HOME) return;
  const next = WS.toggleFavourite(wsFavourites(), key);
  wsStore.set("localStorage", wsUserKey(WS_FAV), next);
  renderNavExtra();
  renderFavBtn();
  toast({ok: true, status: "★"}, next.indexOf(key) >= 0 ? "Added to favourites" : "Removed from favourites");
});
document.addEventListener("input", wsDrawerTouched);
document.addEventListener("change", wsDrawerTouched);
window.addEventListener("beforeunload", e => {
  if (state.user && drawerOpen() && drawerDirty) { e.preventDefault(); e.returnValue = ""; }
});
const signOut = async () => { const r = await api("/api/auth/logout", {method: "POST"}); toast(r, "Signed out"); leave(); };
bind("#out", "click", signOut);
bind("#mcOut", "click", signOut);
bind("#totpOut", "click", signOut);
bind("#totpRecoveryToggle", "click", totpToggleRecovery);
bind("#totpDone", "click", async () => {
  const me = await api("/api/auth/me");
  enter(me.ok ? me.body : (totpPending || {}));
});
bind("#themeToggle", "click", toggleTheme);
bind("#paletteQ", "input", e => {
  clearTimeout(state.palette.timer);
  const term = e.target.value.trim();
  state.palette.timer = setTimeout(() => paletteSearch(term), 180);
});
bind("#paletteResults", "click", e => {
  const item = e.target.closest(".palette-item");
  if (item) paletteGo(item);
});
bind("#palette", "click", e => { if (e.target.id === "palette") closePalette(); });
const chartEl = $("#salesChart");
if (chartEl) {
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
}
["pq", "sq", "lq", "oq"].forEach(id => bind("#" + id, "input", () => ({pq: renderProducts, sq: renderStock, lq: renderLedger, oq: renderPOs})[id]));
bind("#supq", "input", renderSuppliers);
bind("#soq", "input", renderSales);
bind("#biq", "input", renderBilling);
bind("#ldq", "input", renderLeads);
bind("#rateq", "input", renderTax);
document.addEventListener("change", e => {
  if (e.target.id === "rpFrom" || e.target.id === "rpTo") { state.rp.from = $("#rpFrom").value; state.rp.to = $("#rpTo").value; markPreset(""); loadReport(); }  if (["rpEmployee", "rpDepartment", "rpBranch"].includes(e.target.id)) {
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
bind("#swh", "change", renderStock);
bind("#sin", "change", renderStock);
bind("#ltype", "change", renderLedger);
["audAction", "audActor", "audFrom", "audTo"].forEach(id => bind("#" + id, "change", loadAudit));
// The party master's status filter sits in the page toolbar, so it survives a
// re-render; only the chosen value has to be kept in state.
document.addEventListener("change", e => {
  if (e.target.id !== "cuFilter") return;
  state.distFilter = e.target.value;
  loadList("customers", 1);
});
// The receipt drawer's warehouse choice shows the capacity it is going into.
document.addEventListener("change", e => {
  if (e.target.id !== "r-wh") return;
  const note = $("#rWhNote");
  if (note) note.textContent = warehouseCapacityNote(e.target.value);
});
// Scheduled reports: frequency and pack change which fields apply, a named
// recipient's To/CC/BCC follows its checkbox, and the log filters reload it.
// HR month views reload the matrix or calendar; the picker is rebuilt each time.
document.addEventListener("change", e => {
  if (e.target.id === "hrMxMonth" || e.target.id === "hrMxDept") {
    if (e.target.id === "hrMxMonth") state.hr.mxMonth = e.target.value;
    else state.hr.mxDept = e.target.value;
    loadHrMx();
  }
  if (e.target.id === "hrCalMonth" || e.target.id === "hrCalDept") {
    if (e.target.id === "hrCalMonth") state.hr.calMonth = e.target.value;
    else state.hr.calDept = e.target.value;
    loadHrCal();
  }
  if (e.target.id === "hrMxBranch" || e.target.id === "hrMxOffice") {
    if (e.target.id === "hrMxOffice") {
      state.hr.mxOffice = e.target.value;
      const o = (state.hr.offices || []).find(x => String(x.id) === state.hr.mxOffice);
      if (o && o.branch_id) state.hr.mxBranch = String(o.branch_id);
    } else {
      state.hr.mxBranch = e.target.value;
      const o = (state.hr.offices || []).find(x => String(x.id) === state.hr.mxOffice);
      if (o && String(o.branch_id) !== state.hr.mxBranch) state.hr.mxOffice = "";
    }
    hrMonthly();
  }
  if (e.target.id === "hrRepBranch" || e.target.id === "hrRepOffice") {
    if (e.target.id === "hrRepOffice") {
      state.hr.repOffice = e.target.value;
      const o = (state.hr.offices || []).find(x => String(x.id) === state.hr.repOffice);
      if (o && o.branch_id) state.hr.repBranch = String(o.branch_id);
    } else {
      state.hr.repBranch = e.target.value;
      const o = (state.hr.offices || []).find(x => String(x.id) === state.hr.repOffice);
      if (o && String(o.branch_id) !== state.hr.repBranch) state.hr.repOffice = "";
    }
    hrReports();
  }
  if (e.target.id === "hrBranchFilter") setHrSite("branch", e.target.value);
  if (e.target.id === "hrOfficeFilter") setHrSite("office", e.target.value);
});
document.addEventListener("change", e => {
  if (e.target.id === "sr-freq" || e.target.id === "sr-monthrule") srFreqSync();
  if (e.target.id === "sr-pack") srPackSync();
  if (e.target.name === "rcpt" && e.target.closest("#srForm")) {
    const sel = $(`[data-sr-field="${e.target.value}"]`, $("#srForm"));
    if (sel) sel.disabled = !e.target.checked;
  }
  if (e.target.id === "srLogStatus") { state.sr.logStatus = e.target.value; loadDeliveries(); }
  if (e.target.id === "srLogPack") { state.sr.logPack = e.target.value; loadDeliveries(); }
});
// Accounts performance: the window reloads the report and the comparison; the
// region narrows only the flows the server can attribute to a buyer state.
document.addEventListener("change", e => {
  if (e.target.id === "accFrom") return setAccWindow(e.target.value, null);
  if (e.target.id === "accTo") return setAccWindow(null, e.target.value);
  if (e.target.id === "e-party" || e.target.id === "e-purpose") return syncEntryAgainst();
  if (e.target.id === "accState") return setAccStateFilter(e.target.value);
  if (e.target.id === "accMonth") return setAccMonth(e.target.value);
});
window.addEventListener("hashchange", () => {
  if (!state.user) return;
  // Navigating away is a close of the open drawer: keep the address and the
  // form when the operator says no, instead of losing what they typed.
  if (drawerOpen() && drawerDirty && !confirmDiscard($("#dtitle").textContent)) {
    if (wsLastHash) history.replaceState(null, "", wsLastHash);
    return;
  }
  closeDrawer();
  closePalette();
  route();
});

let startTheme = "light";
try {
  startTheme = localStorage.getItem("hb.theme")
    || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
} catch (e) { /* storage blocked */ }
applyTheme(startTheme === "dark" ? "dark" : "light");

bindSignInPage();
bindDashRange();
boot();
})();