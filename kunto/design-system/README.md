# Kunto

Kunto is the design system of a personal training dashboard: readiness, the training plan and the gym log, read in ten seconds each morning. It is loud where the answer is and quiet everywhere else: big bold numbers, one violet for training, a traffic light for the body, and cards that float on a cool grey ground.

Kunto runs on the same component engine as the Calm Admin design system. The markup, the `ca-` classes and the behaviour (charts, menus, dialogs, keyboard handling) are shared; Kunto supplies its own tokens, type, rules, and a layer of Kunto-only components (`ku-` classes). An app can move between the two looks by swapping `tokens.css` and `components/bundle.css`.

## Using it

Start the page with `<html lang="en">` and `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">` (the tab bar pads itself by the phone's safe-area inset). Then load, in this order:

1. The font: `fonts/Manrope-Variable.woff2` (weights 200–800), or Google Fonts `family=Manrope:wght@200..800`.
2. `tokens.css`: compiled from `tokens.json` (light on `:root`, dark on `[data-theme="dark"]`, a `type-*` class per type style). A page outside this project compiles it the same way or inlines the variables; the Kunto app inlines them, with dark mode following the system unless `data-theme` says otherwise.
3. `components/bundle.css`: the shared engine and the Kunto layer.
4. `components/bundle.js` at the end of `<body>`: defines `window.Kunto` (and the engine on `window.CalmAdmin`) and wires up every control on `DOMContentLoaded`. Markup added later (a view drawn on demand) needs `Kunto.init(container)` to wire its radio groups, tabs and menus.

Put `class="ca"` on `<body>`. For dark mode set `data-theme="dark"` on `<html>`, or add `data-ca-theme-auto` to follow the person's saved choice and then their system.

Icons are Lucide 0.469.0, inlined as SVG: `<svg class="ca-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">…</svg>`.

```html
<body class="ca">
  <a class="ca-skip" href="#main">Skip to content</a>
  <div class="ca-frame ca-frame--bleed">
    <aside class="ca-sidebar">…</aside>
    <div class="ca-main"><main class="ca-content" id="main">
      <header class="ku-head">…</header>
      <div class="ca-grid"><div class="ca-stack">…cards…</div><div class="ca-stack">…</div></div>
    </main></div>
  </div>
  <script src="components/bundle.js"></script>
</body>
```

`window.Kunto` has, from the engine: `init`, `lineChart`, `stackedBarChart` and `barChart` (each returns a handle `{ el, update(options), destroy() }`), `toast`, `setTheme`, `getTheme` and `format`. Kunto adds:

- `gauge(svg, { value, level, label })`: the readiness gauge.
- `zone(score)`, `levelZone(level)` and `wordZone(phrase)`: the zone (`good`, `ok`, `low`, `poor`) for a 0–100 score, a 0–5 level or a status phrase.
- `badgeClass(word, fallback)`: the pill class for a status word (see principle 5).
- `sportIcon(kind)`: Kunto's run, lift and ball icons as SVG markup.

Controls fire the engine's events: `ca:change` (segmented controls, radio groups, tabs), `ca:select` (menus), `ca:themechange`.

The three page templates (Overview, TrainingPlan, GymLog) are the real Kunto app running on invented sample data. Start a new screen from AppShell and copy the cards you need from them.

## Principles

1. **The verdict comes first.** Every page opens with the answer: the readiness gauge and "MODERATE · Today: Easy run 6 km". Detail follows, in the order you would ask for it.
2. **Numbers are the heroes.** Values are weight 800 and big (`type-title` 30px, `type-figure` 26px, `type-stat` 18px). Labels and pills share the weight but not the size: at 11px they stay quiet next to the number they explain.
3. **Labels whisper in capitals.** Eyebrows, sources and stat labels are 11px, weight 700–800, uppercase with 0.04–0.08em tracking, in `ink-subtle`. Type them in normal case; CSS makes them capitals, so screen readers say words, not letters.
4. **Violet is training.** `primary` (#5A5AD6) marks where you are (the nav pill, today on the timeline, today's day card), the training line in every chart, the training-effect words and the top set. The violet ramp (`series-1` to `series-3`) orders intensity: deep sleep, anaerobic, hard blocks are darkest.
5. **The body gets a traffic light.** Good is green, low is amber, poor is red, and a fair or moderate middle is violet. The word always shows; colour only repeats it. Red appears only for something to act on: poor readiness, a missed session, a field to fix, a failed load. Status words always get the same colour, whatever the data source called them (`Kunto.badgeClass`):

| Colour | Words |
| --- | --- |
| Green (`ca-badge--success`) | Good, High, Excellent, Prime, Balanced, Optimal, Productive, Peaking, Done, On plan, Best yet |
| Violet (`ca-badge--accent`) | Fair, Moderate, Today, Optional, Moved, Maintaining, Recovery, and the plan's own flags |
| Amber (`ca-badge--warning`) | Low, Below target, Above optimal, Below optimal, Over plan, Under plan, Unbalanced, Unproductive, Overreaching, Strained |
| Red (`ca-badge--critical`) | Poor, Missed, Detraining |
| Grey (`ca-badge`) | Rest, Skipped, Tomorrow |
| Outlined (`ku-badge--ghost`) | Planned, No data |
6. **Cards float on a cool ground.** The `app` ground is a lavender grey (#F3F4F9); cards and the sidebar are white with a soft shadow and no border. Inside a card, tiles use the `chip` grey and session cards use a hairline.
7. **Phones get a tab bar.** Below 860px the sidebar becomes a bottom tab bar with the same sections; the page header keeps freshness and the account.

## Colour

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `app` | #F3F4F9 | #0F1120 | The ground behind cards and the sidebar |
| `surface` | #FFFFFF | #181B2D | Cards, the sidebar, chips in the header |
| `chip` | #F4F4FA | #20243A | Tiles inside cards: meters, stats, key sessions |
| `ink` | #191B2B | #ECEDF7 | Titles and numbers |
| `ink-muted` | #4A4D63 | #B7BAD0 | Labels, chip text |
| `ink-subtle` | #646780 | #9295AF | Captions, uppercase labels, axis ticks |
| `primary` | #5A5AD6 | #8D8DF2 | Training violet |
| `primary-soft` / `primary-ink` | #EDEDFC / #3F3FB4 | #262A4F / #B9B9FA | Current nav item, optional sessions, top sets |
| `success` / `-soft` / `-ink` | #17895F | #4CC794 | Good, done, on plan, fresh data |
| `warning-strong` / `-soft` / `-ink` | #B7780A | #E3AE48 | Low, above optimal, over or under plan, flagged points, stale data |
| `critical` / `-soft` / `-ink` | #C8413A | #F0736B | Poor, missed, form errors, failed loads |
| `neutral` | #80849B | #6E7290 | Grey chart marks that must still read at 3:1: awake time in the sleep bars |
| `series-1` … `series-3` | #2F2F99 … #A9A9EE | #C3C3FA … #5353B8 | The intensity ramp (dark is strongest in light mode, light is strongest in dark mode) |

Every text token passes 4.5:1 on `app`, `surface`, `chip` and the tinted grounds in both themes; status inks pass on their soft backgrounds. The original Kunto's grey (#7C7F96) failed at 4.0:1, so `ink-subtle` is darker. `series-3` is a fill colour only, never text, and always sits next to a value in words.

## Type

One family, **Manrope**, does everything. Personality comes from weight: 800 for numbers, titles, verdicts, uppercase labels and pills; 700 for card titles and names; 600 for navigation, buttons and chips; 400 for body text. Size keeps the 800-weight labels and pills quiet.

Each style below is also a class in the compiled `tokens.css` (`.type-figure`), for text that isn't part of a component. Components set their own type; don't stack a `type-*` class on them.

| Style | Size / line | Weight | Use |
| --- | --- | --- | --- |
| `type-score` | 48 / 56 | 800 | The number in the gauge |
| `type-title` | 30 / 36 | 800 | Page title, the season countdown (24px on phones) |
| `type-figure` | 26 / 32 | 800 | A card's one number |
| `type-verdict` | 22 / 28 | 800 | The readiness verdict, the training-status phrase |
| `type-stat` | 18 / 24 | 800 | Stat tiles |
| `type-heading` | 15 / 22 | 700 | Card titles |
| `type-body` | 14 / 20 | 400 | Body text |
| `type-body-strong` | 14 / 20 | 700 | Session and activity titles, names |
| `type-nav` | 14 / 20 | 600 | Navigation, buttons, chips |
| `type-small` | 12 / 16 | 400 | Meta lines, notes |
| `type-label` | 11 / 14 | 800, 0.08em, uppercase | Eyebrows, sources, stat labels |
| `type-pill` | 11 / 14 | 800, 0.03em | Status pills |

Numbers that line up use tabular figures (`ku-num` or `ca-num`).

## Layout and shape

- The frame pads 16px and stops growing at 1440px; cards sit 20px apart and pad 20px inside. The right column is 320px (`rail-w`); when the main column is narrower than 916px (about a 1180px window) it moves underneath and lays its cards out two across. Two cards in a split stay side by side while each gets 320px.
- Radii: 6px tags, 10px controls and nav items, 12px tiles and session cards (`radius-tile`), 16px cards, 20px the sidebar, full pills.
- Shadows: `shadow-xs` lifts cards and the sidebar; `shadow-pop` for menus, tooltips and the tab bar; `shadow-frame` for dialogs. No borders on cards.

## Voice and content

- Lead with the number and its unit: "45 ms · 7-night avg", "31.6 of 20–30 km". Units always; a dash for ranges (20–30).
- Dates are short and day-first: "Mon 12 Oct", "12–18 Oct 2026". Times are 24-hour: "Data as of 07:45".
- Verdicts are one or two words from a fixed ladder: Poor, Low, Fair, Moderate, Good, High, Excellent; Below target, Above optimal, Balanced.
- Data from devices keeps its own words and case where people know them (Garmin's "POOR", "Productive"). Kunto's own labels use sentence case.
- Say what changed and what to do: "Swap the intervals for an easy run, or move them to Thursday."

## Iconography

Lucide icons (0.469.0), 1.75px stroke, `currentColor`: 18px in navigation, activity chips and the status chip; 16px in buttons and chips. Sports use Kunto's own three icons, drawn for the original app on the same grid: a runner, a barbell and a floorball, from `Kunto.sportIcon('run' | 'lift' | 'ball')`; anything else gets Lucide `activity`.

Manrope has no ★, ✓, ✗, → or ▲, so those are icons too: a filled Lucide `star` (`ku-star`) marks a key session and is always followed by "Key session" for screen readers; `check` and `x` sit inside Done and Missed pills; `arrow-right` ends a card link; `arrow-up` and `arrow-down` mark a lift's change.

The Kunto mark is a ring with a heartbeat, drawn in `primary` on a `primary-soft` track; it sits in the sidebar brand row (`ku-mark`):

```html
<svg viewBox="0 0 30 30" aria-hidden="true"><circle cx="15" cy="15" r="13" fill="none" stroke="var(--primary-soft)" stroke-width="4"/><path d="M15 2a13 13 0 0 1 12.4 9" fill="none" stroke="var(--primary)" stroke-width="4" stroke-linecap="round"/><path d="M8 16h3.5l2-4 3 8 2-4H22" fill="none" stroke="var(--primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
```

## Components

- **Layout:** AppShell, Sidebar, TabBar, PageHeader, Card.
- **Readiness:** ReadinessGauge, Readiness (the hero card), MeterTile, StatTile.
- **Training:** ActivityList, AgendaList, TargetBar, SeasonTimeline, SeasonStrip, WeekPlan, RowList.
- **Gym:** CalendarHeatmap, WorkoutLog, ExerciseHistory.
- **Charts:** LineChart, StackedBarChart, BarChart.
- **Actions and inputs:** Button, SegmentedControl, Chip, Tabs, Menu, SearchField, Form, Choices, ThemeToggle.
- **Feedback and overlays:** StatusBadge, DataSource, Alert, Toast, EmptyState, Skeleton, Dialog.
- **Pages:** Overview, TrainingPlan, GymLog.

The engine also carries Calm Admin's data table, KPI strip, pager and date-range picker. They work in Kunto and take its tokens, but Kunto doesn't use them and their look isn't tuned here.

## Accessibility

- Every state is a word, not only a colour: pills, meter verdicts, the gauge level.
- Charts are keyboard reachable (arrow keys, Home, End) and include a hidden data table. Decorative graphics (the trend bars, the timeline) carry an `aria-label` or a screen-reader line with the same facts.
- Focus rings are 2px `primary`. Segmented controls, the season strip, the exercise list and tabs are radio groups or tab lists: one tab stop, arrow keys inside. The heatmap is one tab stop too, with arrow keys between gym days.
- Focus follows the person's intent: opening a gym session keeps focus on its button; a link to another tab moves focus to the page title; a marker chip or a past week moves it to the week's heading (headings that take focus this way show no ring). When Prev or Next reaches the end and disables, focus moves to This week.
- Changes that don't move focus are announced in one `role="status"` region: the tab, the week, how many sessions match a search.
- Jumps scroll smoothly unless the person prefers reduced motion. Nothing hides behind the phone tab bar.
- Text passes 4.5:1 in both themes; controls and meaningful marks pass 3:1.
