# Interface design system

**Status:** applied on `feature/gap-closure`, 3 November 2026; sign-in page and Overview range control added 4 November 2026.
**Applies to:** every screen in the single-page application (`static/index.html`, `static/css/styles.css`, `static/js/app.js`).
**Evidence:** `var/shots/*.png` and [`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) §26–§27.

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
  `44px minmax(0,1fr) 26px`. The page scrolls as a whole so `scrollIntoView`
  and browser find keep working. Below 820 px the rail becomes a top band:
  rows `auto auto minmax(0,1fr) auto`, with the module list on its own
  horizontally scrolling line.

## 5. Components

| Component | Rules |
|---|---|
| **Application bar** | 44 px forest strip: brand tile, global search (Ctrl/⌘ K), theme toggle. Search is a button that opens the palette, not an input, so it never traps focus. |
| **Module rail** | 232 px, grouped by verb ("Sales and customers", "Stock and supply", "Finance and insight", "People and admin"). 10 px uppercase group labels, 30 px rows, active row uses a translucent fill plus a 3 px turmeric inset line. Counts sit at the right as turmeric pills. |
| **Page head** | Title and one-line factual subtitle. Primary action sits on the same line, right-aligned. |
| **Filter band** | Tinted `--head` strip with 4 px radius; controls align on a common baseline. Labels are 10.5 px uppercase. Presets use the segmented control. Secondary reset action is pushed to the far right. |
| **Range trigger and calendar** | One 34 px bordered trigger showing the selected window (`Oct 5, 2026 - Nov 3, 2026`), a calendar glyph and a caret; the open state takes a moss border plus a 2 px halo. The popover is anchored left under the trigger, 620 px wide (never wider than the viewport minus 48 px), `--r` radius, `--shadow-2`. Inside: a wrapping row of pill presets, then two stacked months (`3fr` each, 18 px apart). Days are 28 px; in-range days use `--moss-t`, the two ends use solid moss, today is moss bold, future days are disabled at 40% and arrows stop at the current month. A hint line and a live preview sit above and below the grid. Below 560 px the trigger and popover go full width. |
| **Sign-in page** | Two columns, `1.22fr / 1fr`, 20 px gap inside a 1240 px shell: promotion banner and notices on the left, the credentials panel and help-line boxes on the right (the right column caps at 470 px). The banner keeps a 16/10 frame with `object-fit: cover`, a gradient title strip and arrow/dot controls; notices are dated cards. At 1000 px the grid becomes one column with the credentials **first** (order 1) and the banner and notices below; the banner shortens to 16/9 at 300 px tall, 240 px at 820 px and 200 px at 520 px, and the footer wraps left-aligned. Empty banner/notice/contact slots hold a neutral "No data yet" row, never placeholder marketing text. |
| **Buttons** | Pill (16 px radius; 6 px when small), 34 px tall (27 px `sm`), 13 px/600. Primary moss, ghost white with border, danger red. 150 ms hover transition; `:active` darkens one step. |
| **Inputs** | 34 px, 3 px radius, 1 px line. Hover darkens the border; focus adds a 1 px moss ring plus a 2 px `moss-t` halo. Placeholders are `--faint` and never the only label. |
| **Cards** | White, 1 px border, 6 px radius, 16–18 px padding. KPI tiles use a 24 px figure, a sentence of context and an optional sparkline drawn from stored movements. |
| **Tables** | 7 px/12 px cells (6/9 in drawers), zebra even rows, hover highlight, sticky header in scrolling boxes, right-aligned tabular figures. SKU cells stay on one line; row action buttons never wrap, so a narrow screen scrolls the table rather than stretching rows. |
| **Drawer** | Full-height right panel: 62% at ≥1440, 68% at 1024–1439, 82% at 768–1023, 100% below 768. It sits above the application bar (`z-index` 23 vs 22), so the title and × are never covered; the scrim dims the bar too. Header and body are separate scroll regions. |
| **Command palette** | 620 px card at 10 vh, one input, grouped results, Esc to close. This is the only overlay with a centred search field. |
| **Status bar** | 26 px `--head` strip: a factual sentence ("Every figure is counted by the server") and the environment name. It states no invented statistic. |
| **Toast** | Forest card bottom-centre, 180 ms entry, 12.5 px, 30 px above the status bar. |

## 6. States

| State | Treatment |
|---|---|
| Hover | Background or border one step darker; 150 ms. Never moves layout. |
| Focus | 2 px ring, 2 px offset; inputs add an inner ring. Visible on keyboard only (`:focus-visible`). |
| Active/pressed | One step darker than hover; no scale transform. |
| Disabled | Native disabled styles plus `--faint` text; aria-disabled where the action is guarded by the server. |
| Empty | Sentence first, next action second ("No products yet. Select New product…"). Never a blank panel. |
| Missing data | "No data yet" plus the missing input, from the server. Never zero. |
| Error | Red text inside the form, `role="alert"`, naming the field or rule. Dashboard errors use a red rail card. |
| Loading | Existing skeleton/spinner treatment inside the affected panel; the shell stays usable. |
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
| ≥1440 px | Rail visible | Drawer 62%; 4 KPI columns |
| 1024–1439 px | Rail visible | 3 KPI columns; drawer 68%; range popover 620 px |
| ≤1000 px | Sign-in only | Sign-in grid becomes one column, credentials first, banner below |
| ≤560 px | — | KPI single column; filter segments wrap; dates full width; range trigger and popover full width |
| ≤520 px | — | Help-line boxes stack one column; sign-in banner 200 px; sign-in footer wraps left |
| 821–1023 px | Rail visible | Nav compresses below 820 px height |
| ≤820 px | Rail becomes a top band | 2 KPI columns; drawer 82%; status bar shows only the environment |
| ≤600 px | Top band | Form rows collapse to one column; drawer 100% |
| ≤560 px | — | KPI single column; filter segments wrap; dates full width |
| ≤420 px | — | Search label hidden, icon only |

## 9. Accessibility

- WCAG AA contrast checked numerically for every text/background pair in §3;
  the only sub-3:1 colour combination (`white` on `--turmeric`) is not used.
- Semantic landmarks: `header`, `nav aria-label="Modules"`, `main`, `aside
  role="dialog" aria-modal="true"`, `footer`.
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
  redesigned CSS keeps all existing class names; the only markup changes are
  the application bar, the dashboard hero/filter band, the status bar and one
  `sku` class on the product table.
- Numbers still come from the server. No sample or placeholder figure was
  introduced anywhere.

## 11. Owner input needed

| Item | Why it needs you |
|---|---|
| **Brand colours** | The forest/moss/turmeric palette was kept exactly as it was. If a formal brand palette exists, change the tokens in `:root` and the dark block; nothing else references raw hues. |
| **Logo** | The mark is still the letter **H** in a turmeric tile. A real logo needs an SVG and one size rule (30 px in the bar, 30 px on sign-in). |
| **Real copy** | Placeholders such as "Search pages and records" and the status-bar sentence are accurate but generic. A short product tagline for the sign-in panel would replace "One controlled record of products, stock and orders." |
| **Product imagery** | None is used, by design. If the catalogue needs thumbnails, they need a storage policy and a fallback tile first. |
| **Environment label** | The status bar currently reports `Environment: production` while the development backend serves it. That value comes from the server's `APP_ENV`; confirm what each deployment should say before it is shown to operators. |
