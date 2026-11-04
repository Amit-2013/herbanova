# Interface design system

**Status:** applied on `feature/gap-closure`, 3 November 2026; sign-in page and Overview range control added 4 November 2026; workspace tab bar, breadcrumbs and favourites added in WP-2 on 4 November 2026.
**Applies to:** every screen in the single-page application (`static/index.html`, `static/css/styles.css`, `static/js/app.js`, `static/js/workspace.js`).
**Evidence:** `var/shots/*.png` and [`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) §26–§27, §29.

This document is the reference for anyone changing the interface. It records the
rules the current CSS follows, so a later change can keep them rather than
reinvent them.

## 1. Direction

The interface is a dense operations tool, not a marketing page. It borrows the
structure of the supplied DMS sample — a 44 px branded application bar, a module
rail, a horizontal tab strip on narrow screens, tinted filter bands, zebra data
grids with sticky headers, a 26 px status bar, 3–6 px radii and pill-shaped
primary actions — while keeping **Herbanova's original palette**: forest,
moss, turmeric and cool paper. No colour was replaced and no screen was removed.

Three rules decide most questions:

1. **The data is the decoration.** Chrome is quiet; figures, status chips and
   movement are the only things allowed to draw the eye.
2. **One accent does one job.** Turmeric marks attention (a live nav item,
   expiry, a warning rail). Moss marks actions. Nothing else is coloured.
3. **Density with air.** Rows are compact, but each block has 8–14 px of space
   around it so the eye can separate sections without scrolling.

## 2. Typography

| Token | Value | Used for |
|---|---|---|
| Family | `Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` | Everything. There is one family; `--serif` is an alias kept for older rules. |
| Body | 13.5 px / 1.45 | Default text, tables, forms |
| Page title | 22 px, 600, −0.025 em | `.page-head h1`; 20 px below 820 px |
| Card figure | 24 px, 600, tabular numerals | `.kpi-value` and dashboard tiles |
| Panel header | 14 px, 700 (13.5 px on the dashboard) | `.panel-h h2` |
| Form title | 22 px, 600 | Sign-in, two-step card |
| Sign-in headline | `clamp(27px, 3vw, 34px)` | Left brand panel only |
| Secondary | 12.5 px | Notes, subtitles, helper text |
| Label | 12 px, 600, `--mute` | Field labels |
| Micro | 10–11.5 px, uppercase, 0.05–0.1 em tracking | Column groups, KPI labels, status bar |

Long-form explanatory text is capped at **78 characters per line**
(`.panel-note`); page subtitles are capped at 82 (`max-width:82ch`). Figures use
`font-variant-numeric: tabular-nums` so columns line up.

## 3. Colour

### Light theme

| Token | Value | Role | Contrast |
|---|---|---|---|
| `--forest` | `#14231b` | Application bar, module rail | 16.3:1 on white |
| `--moss` | `#1F6B4A` | Primary action, focus ring, links | 6.44:1 with white text |
| `--moss-d` | `#175539` | Hover/active on primary | — |
| `--turmeric` | `#d9a441` | Attention rail, active nav line, count badge (with dark text) | 7.62:1 with `#241a06` |
| `--paper` | `#f3f5f2` | Page background | — |
| `--surface` | `#ffffff` | Cards, drawers, inputs | — |
| `--head` | `#e8ede9` | Table headers, filter bands, drawer header | — |
| `--zebra` | `#f6f8f5` | Even table rows | — |
| `--ink` | `#16211b` | Body text | 16.6:1 on white |
| `--mute` | `#56635b` | Secondary text and labels | 6.30:1 on white, 5.32:1 on `--head` |
| `--faint` | `#66736b` | Input placeholders only | 4.97:1 on white |
| `--line` | `#dfe6e0` | Borders | — |
| `--ok` / `--warn` / `--bad` | `#1b7443` / `#8a5a00` / `#b3261e` | Status text on their tinted backgrounds | 4.91:1 / 5.29:1 / 5.37:1 |

### Dark theme

`html[data-theme="dark"]` overrides the same tokens and sets
`color-scheme: dark`, so native date pickers, selects and scrollbars render
dark. Because `--moss` becomes a light green in this theme, primary buttons
have explicit dark overrides (`#2f7d57`, hover `#276b4a`; danger `#b3261e`,
hover `#932a20`) so white labels keep a contrast above 5:1. Placeholder
`--faint` is `#84968a` (4.71:1 on `--head`, 5.19:1 on `--surface`).

**Rules**

- Never place white text on `--turmeric` (2.25:1). The logo tile and count
  badges use `#241a06`, which is 7.62:1.
- A focus ring is `--moss` on light surfaces (6.44:1) and `--turmeric` on the
  dark chrome (`.appbar`, `.side`), where moss would fall under 3:1.
- Secondary text uses `--mute`, not `--faint`. `--faint` is reserved for
  placeholder text on an input.
- Status colour is text plus a tinted background, never colour alone; the word
  ("active", "expired") is always present.

## 4. Space, shape and elevation

- **Spacing** follows a 4/8 scale: 4, 8, 12, 16, 20, 24, 32, 44.
- **Radii:** 3 px (inputs, small controls), 4 px (filter bands, callouts),
  6 px (cards, panels), 10 px (`--r-l`, used sparingly), 16 px (pill buttons),
  99 px (status chips and counts).
- **Shadows:** one resting shadow (`0 1px 2px rgba(16,35,25,.06)`) for cards;
  one raised shadow (`0 18px 44px rgba(9,24,17,.2)`) for the command palette and
  drawer. No glow.
- **Borders** carry most separation. No panel uses a drop shadow without a
  1 px border.
- **Layout:** `grid-template-columns: 232px minmax(0, 1fr)`; rows
  `44px 40px minmax(0,1fr) 26px` — application bar, workspace tab bar, content,
  status bar. The page scrolls as a whole so `scrollIntoView` and browser find
  keep working. Below 820 px the rail becomes a top band:
  rows `auto auto auto minmax(0,1fr) auto`, with the module list on its own
  horizontally scrolling line under the tab bar.

## 5. Components

| Component | Rules |
|---|---|
| **Application bar** | 44 px forest strip: brand tile, global search (Ctrl/⌘ K), theme toggle. Search is a button that opens the palette, not an input, so it never traps focus. |
| **Workspace tab bar** | 40 px `--head` strip directly under the application bar, holding one tab per open screen plus the overflow button. Tabs are 29 px, 210 px at most (176 px of label), `--r-xs` radius on the top corners only, 12.5 px/500 label. The active tab uses the page background, a stronger border and a 2 px turmeric inset line along its top edge — the same "active line" language as the rail. The pinned Home tab is narrower (130 px label) and has no close button. `+`-free: the overflow button (`⋯`, 30×26 px) opens a menu of hidden tabs, recently closed tabs, and the Close-others / Close-all-but-Home actions. Tabs never wrap; the strip clips and the overflow menu lists what is hidden. Below 820 px the strip becomes a scrolling row of 28 px tabs. |
| **Breadcrumb** | 11.5 px `--mute` line above the page title, inside the page head: `Module › Category › Group › Feature` in a real `<ol>`, separated by a typographic `›`. Ancestors are links; the current screen is plain text with `aria-current="page"`. The trail is produced by the same hierarchy that renders the rail, so it cannot name a path the menu does not have. Segments truncate with an ellipsis rather than wrapping. |
| **Module rail** | 232 px, grouped by verb ("Sales and customers", "Stock and supply", "Finance and insight", "People and admin"). 10 px uppercase group labels, 30 px rows, active row uses a translucent fill plus a 3 px turmeric inset line. Counts sit at the right as turmeric pills. Above the modules sit two compact groups: **Favourites** (screens pinned with the star, in the user's order) and **Recent** (the last screens opened this session). Each empty group renders nothing rather than a placeholder. A favourite or recent row whose permission or feature switch no longer allows it is omitted. |
| **Favourite star** | 26×26 px ghost button in the page head beside the title, `aria-pressed` and an `aria-label` naming the screen ("Add Products to favourites"). Hollow `--faint` at rest, turmeric on hover and solid `#a9761f` when active. Its state survives reloads per user. |
| **Page head** | Title and one-line factual subtitle. Primary action sits on the same line, right-aligned. |
| **Filter band** | Tinted `--head` strip with 4 px radius; controls align on a common baseline. Labels are 10.5 px uppercase. Presets use the segmented control. Secondary reset action is pushed to the far right. |
| **List filter band** | The plain-toolbar form of the band: search input, optional status select, then explicit **Search** and ghost **Clear** buttons on the same row. Typing filters after a 300 ms pause and the buttons act immediately, so the band works with or without a click. Clear resets every control and returns to page 1. The band sits above the table inside the same panel. |
| **Range trigger and calendar** | In the tinted filter strip, a 34 px bordered trigger showing the selected window (`Oct 5, 2026 - Nov 3, 2026`), a calendar glyph and a caret; the open state takes a moss border plus a 2 px halo. Immediately to its right sits a wrapping row of pill presets (1D … This FY) that acts at once and never opens the popover. The popover is anchored left under the trigger, 620 px wide (never wider than the viewport minus 48 px), `--r` radius, `--shadow-2`, and holds only the calendar: hint and month arrows above, two months `1fr` each 18 px apart. Days are 28 px; in-range days use `--moss-t`, the two ends use solid moss, today is moss bold, future days are disabled at 40% and arrows stop at the current month. A hint line and a live preview sit above and below the grid. Below 720 px one month is shown; below 560 px the trigger and popover go full width and the preset row wraps under the trigger. |
| **Sign-in page** | Two columns, `1.22fr / 1fr`, 20 px gap inside a 1240 px shell: promotion banner and notices on the left, the credentials panel and help-line boxes on the right (the right column caps at 470 px). The banner keeps a 16/10 frame with `object-fit: cover`, a gradient title strip and arrow/dot controls; notices are dated cards. At 1000 px the grid becomes one column with the credentials **first** (order 1) and the banner and notices below; the banner shortens to 16/9 at 300 px tall, 240 px at 820 px and 200 px at 520 px, and the footer wraps left-aligned. Empty banner/notice/contact slots hold a neutral "No data yet" row, never placeholder marketing text. |
| **Buttons** | Pill (16 px radius; 6 px when small), 34 px tall (27 px `sm`), 13 px/600. Primary moss, ghost white with border, danger red. 150 ms hover transition; `:active` darkens one step. |
| **Inputs** | 34 px, 3 px radius, 1 px line. Hover darkens the border; focus adds a 1 px moss ring plus a 2 px `moss-t` halo. Placeholders are `--faint` and never the only label. |
| **Cards** | White, 1 px border, 6 px radius, 16–18 px padding. KPI tiles use a 24 px figure, a sentence of context and an optional sparkline drawn from stored movements. |
| **Tables** | 7 px/12 px cells (6/9 in drawers), zebra even rows, hover highlight, sticky header in scrolling boxes, right-aligned tabular figures. SKU cells stay on one line; row action buttons never wrap, so a narrow screen scrolls the table rather than stretching rows. |
| **List footer pager** | `--head` strip under the table with a 1 px top line. Left: a bold tabular `1–50 of 52` count read from `X-Total-Count`, never from the rows in hand. Right: `«`, `‹`, `Page n of m`, `›`, `»` and a **Rows per page** select (25, 50, 100, 200; default 50, the server's maximum). Buttons disable at the ends instead of disappearing. The whole strip is hidden while the count is unknown and dimmed with pointer-events off during a load. Below 600 px the nav row takes a full line under the count and the size select stays right. |
| **Drawer** | Full-height right panel: 62% at ≥1440, 68% at 1024–1439, 82% at 768–1023, 100% below 768. It sits above the application bar (`z-index` 23 vs 22), so the title and × are never covered; the scrim dims the bar too. Header and body are separate scroll regions. |
| **Command palette** | 620 px card at 10 vh, one input, grouped results, Esc to close. This is the only overlay with a centred search field. |
| **Status bar** | 26 px `--head` strip: a factual sentence ("Every figure is counted by the server") and the environment name. It states no invented statistic. |
| **Toast** | Forest card bottom-centre, 180 ms entry, 12.5 px, 30 px above the status bar. |

### 5.1 List screens (WP-3 standard)

A list screen is always the same three parts, in this order: the list filter
band, the table box, and the footer pager. The count in the pager is the
server's answer for the current filters, so the parts cannot be mixed — a
pager over rows the browser happened to receive would state a wrong total.

The contract behind the screen:

- Every filter is applied by the server before the count is taken. The client
  never filters a page it already has.
- One request fills the table, the pager count and the page bounds. A slower
  earlier request cannot overwrite a newer one; the newest response wins.
- If a filter strands the reader on a page past the end, the screen reloads
  page 1 itself and says so through the count, rather than showing an empty
  table.
- Export reads the same endpoint with `page` omitted, which returns every
  matching row; the file is built from that response and the toast names the
  row count. No separate export route exists.
- One export button per screen, in the page head beside the primary action.
- The page head's count is the server's `X-Total-Count` for the current view.
  A status breakdown (for example "3 ready to dispatch, 45 draft") is shown
  only when the rows in hand cover that total and the screen is on its default
  filter with no search; otherwise the head states the total and nothing more.
  A breakdown is never paired with a different, narrower total.

**Status (4 November 2026):** all eight list screens follow this standard.
Products was the batch-1 pilot (`pagerHtml`, `loadProductList`,
`exportProductsCsv`, `#/products`). Batch 2 moved suppliers, customers, sales
orders, purchases, approvals, leads and billing onto the shared `LIST_SPEC`
layer (`listState`, `loadList`, `pagerHtml`, `searchList`, `clearList`,
`exportListCsv`); their old in-browser filters and counts were replaced, not
layered over. Sortable column headers are offered only where the endpoint
sorts on the server: today that is Products (`sort` + `direction`, NULLS LAST).
The seven batch-2 endpoints keep their documented row order, so their headers
are deliberately not clickable.

### 5.2 Workspace shell (WP-2)

The tab bar is a workspace, not a browser clone. The rules that keep it
predictable:

- **One tab per screen.** A tab is keyed by view; Accounting adds its section
  (`accounts/gst-out`) because its 18 registers are separate reports, while the
  in-page tabs of Inventory, Scheduled reports and HR stay inside one tab.
  Selecting a screen that is already open activates its tab instead of opening
  a second copy. Context records (a customer, an order) open in the drawer, so
  they never multiply tabs.
- **Home is pinned and cannot be closed.** Close-others and close-all keep it.
- **The strip is bounded twice, and both bounds are visible.** Width decides
  which tabs are hidden behind `⋯` — a hidden tab is still open and listed
  there. The model keeps at most **20 tabs, Home included**; opening a 21st
  screen evicts the oldest screen after Home into the reopen list, so
  *Reopen closed tab* brings it straight back. Nothing is closed without a way
  back, and Home is never evicted.
- **The hash is the truth.** The active tab always matches
  `#/view/section?query`, so refresh, back/forward and pasted links all land on
  the same screen with its query intact.
- **The open set survives reloads, not logins.** It is stored per user in
  `sessionStorage` and re-validated against `/api/auth/me` and the feature
  switches on restore; a tab the user may no longer open is dropped silently.
- **Unsaved work is protected.** Closing a tab, another tab or switching away
  while the shared drawer holds a dirty form asks first, using the same
  confirmation as closing the drawer itself.

## 6. States

| State | Treatment |
|---|---|
| Hover | Background or border one step darker; 150 ms. Never moves layout. |
| Focus | 2 px ring, 2 px offset; inputs add an inner ring. Visible on keyboard only (`:focus-visible`). |
| Active/pressed | One step darker than hover; no scale transform. |
| Disabled | Native disabled styles plus `--faint` text; aria-disabled where the action is guarded by the server. |
| Empty | Sentence first, next action second ("No products yet. Select New product…"). Never a blank panel. A filtered empty state names the filters and offers Clear ("No product matches these filters…"), so it is never confused with an empty master. |
| Missing data | "No data yet" plus the missing input, from the server. Never zero. |
| Error | Red text inside the form, `role="alert"`, naming the field or rule. Dashboard errors use a red rail card. |
| Loading | Existing skeleton/spinner treatment inside the affected panel; the shell stays usable. A reloading list keeps its rows and count visible and dims the pager (`pointer-events: none`) instead of blanking the table. |
| Reduced motion | `@media (prefers-reduced-motion: reduce)` removes drawer, palette, toast and chart transitions. |

## 7. Motion

- Hover/focus: 150 ms; drawer entry: 200 ms; toast: 180 ms.
- Easing: `cubic-bezier(.2,.7,.3,1)` (`--ease`) for entry, plain `ease` for
  colour changes.
- Nothing loops, pulses or glows. No parallax, no scroll-triggered animation.
- The sign-in banner rotates every 6 s with a 350 ms cross-fade. Rotation stops
  while the pointer or keyboard focus is inside the banner, while the tab is
  hidden, and permanently under reduced motion; arrows and dots always work.
- `prefers-reduced-motion: reduce` collapses every animation and transition to
  0.001 ms (`styles.css:357-359`). Verified with an emulated preference in
  headless Chrome on 3 November 2026: drawer and buttons reported `1e-06s`
  against `0.2s` / `0.15s` with no preference.

## 8. Breakpoints

| Width | Shell | Notable changes |
|---|---|---|
| ≥1440 px | Rail 232 px, tab bar one row | Drawer 62%; 4 KPI columns; tab overflow hides whole tabs only |
| 1081–1439 px | Rail 232 px | Drawer 68%; 4 KPI columns; range popover 620 px |
| 821–1080 px | Rail 232 px | 3 KPI columns (`max-width:1080`); drawer 82% at 1024–1439 or 768–1023 |
| 601–820 px | Rail becomes a horizontal module strip under the tab bar | Tab bar 38 px min, 28 px tabs that scroll behind the overflow button; 2 KPI columns; drawer 100%; status bar shows only the environment |
| ≤600 px | Horizontal strip | Toolbar stacks, page-head actions take a full row, table cells tighten, list pager wraps its nav row under the count and keeps every button |
| ≤520 px | — | Sign-in help-line boxes stack one column; banner 200 px; footer wraps left |
| ≤500 px (sign-in) | one column | Credentials first, banner and notices below; banner shortens |
| ≤420 px | — | Search label hidden, icon only |
| Print | All chrome hidden | Application bar, tab bar, rail, status bar, breadcrumbs, favourites, toolbar and pager are suppressed; the grid prints with its heading and filter summary |

The tab bar never introduces a breakpoint of its own between 601 and 1080 px:
it clips and the `⋯` menu lists hidden tabs. The rail keeps its 232 px width
until 820 px, where the existing horizontal strip takes over — there is still
no icon-only rail (see §10).

## 9. Accessibility

- WCAG AA contrast checked numerically for every text/background pair in §3;
  the only sub-3:1 colour combination (`white` on `--turmeric`) is not used.
- Semantic landmarks: `header`, `nav aria-label="Modules"`, `main`, `aside
  role="dialog" aria-modal="true"`, `footer`.
- The workspace strip is the WAI-ARIA tabs pattern: `role="tablist"` with
  `aria-label="Open screens"`, each tab `role="tab"` with `aria-selected` and
  `aria-controls` pointing at the screen section. The strip is one tab stop
  (roving `tabindex="0"` on the active tab, `-1` on the rest); Left/Right move
  to and activate the adjacent tab, `Home`/`End` jump to the ends, `Delete`
  closes the focused tab (Home is protected), and clicking a tab activates it
  (automatic activation, so `Enter` is not a second step). The overflow `⋯`
  button is a real button with `aria-haspopup="menu"` and `aria-expanded`; its
  menu closes on Escape and returns focus to the button.
- Breadcrumbs are an ordered list; the last item carries
  `aria-current="page"`. A trail is never rendered for a screen the current user
  may not open.
- Favourite buttons expose `aria-pressed` and an accessible name, and are
  reachable by keyboard from the page head. The favourites and recent groups in
  the rail are ordinary links inside the module `nav`.
- One `h1` per screen. Drawers are labelled by their title via
  `aria-labelledby`.
- Focus is never removed; `:focus-visible` is the ring described above.
- Tables use real `th` cells; money columns are right-aligned and tabular.
- The palette and drawer close on Escape; the drawer releases the background
  scroll lock.
- Status is never colour-only. Icons are inline SVG or typographic, never
  emoji.
- `prefers-reduced-motion` is honoured globally.

## 10. What was not changed

- Every route, id, permission gate, endpoint and report is untouched. The
  redesigned CSS keeps all existing class names. Markup changes are limited to
  the application bar, the dashboard hero/filter band, the status bar, one
  `sku` class on the product table and — since WP-2 — the workspace tab bar,
  breadcrumb and favourites/recents groups around the existing module rail.
- The rail markup is still the same list of routable views; WP-2 regrouped it
  under the shared hierarchy and added the star control, it did not replace the
  screens.
- Numbers still come from the server. No sample or placeholder figure was
  introduced anywhere.

## 10.1 Known limits carried by WP-2

| Limit | Why it exists | What replaces it |
|---|---|---|
| The rail is never collapsed to icons | The breakpoint work was scoped to the tab bar, and the rail keeps its labels down to 821 px before becoming the horizontal module strip | A later responsive pass, only if operators ask for it |
| The tab strip keeps at most 20 tabs, Home included | A bound keeps the model and the `⋯` menu predictable; the oldest screen after Home is evicted into the reopen list rather than closed outright | WP-4 can lift the bound if tabs move to the server per user |
| Favourites and recents are device-local (`localStorage`) | The brief wants them server-side, which needs the WP-4 registry tables | WP-4 moves them to `user_favourites`; until then they are per browser and re-filtered on every render |
| Sorting stays Products-only | The other seven list endpoints expose no `sort`/`direction` | WP-4 does not change this; sorting is added per endpoint when the SQL order is defined |
| Menus are still code-defined in `workspace.js` | Registry tables and `/api/navigation` are WP-4 | WP-4 replaces the constant with server data, keeping `workspace.js` signatures |

## 11. Owner input needed

| Item | Why it needs you |
|---|---|
| **Brand colours** | The forest/moss/turmeric palette was kept exactly as it was. If a formal brand palette exists, change the tokens in `:root` and the dark block; nothing else references raw hues. |
| **Logo** | The mark is still the letter **H** in a turmeric tile. A real logo needs an SVG and one size rule (30 px in the bar, 30 px on sign-in). |
| **Real copy** | Placeholders such as "Search pages and records" and the status-bar sentence are accurate but generic. A short product tagline for the sign-in panel would replace "One controlled record of products, stock and orders." |
| **Product imagery** | None is used, by design. If the catalogue needs thumbnails, they need a storage policy and a fallback tile first. |
| **Environment label** | The status bar currently reports `Environment: production` while the development backend serves it. That value comes from the server's `APP_ENV`; confirm what each deployment should say before it is shown to operators. |
