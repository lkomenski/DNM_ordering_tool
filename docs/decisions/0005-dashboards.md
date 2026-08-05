# 0005 - Sales trend dashboards

Status: Accepted
Date: 2026-08-04

## Context

The original ask included a dashboard for both Milk and Sandwiches showing
sales trends by time of day, day of week, month, and season, so the pattern
the ML model (ADR 0004) is using is visible rather than just the output
number. Time-of-day was already ruled out early (the Product Mix export has
no hourly breakdown).

## Decision

- New `backend/dashboard.py`: read-only, mode-aware aggregation over the
  same saved history the rest of the app uses — no schema change, no new
  storage. `par_dashboard()` (Sandwiches and any other par-mode category)
  returns averages by weekday, by month, by season, and a daily trend
  series. `reconciliation_dashboard()` (Milk) returns by-month, by-season,
  and a weekly trend series only — weekly rows carry no weekday signal, so
  there's deliberately no weekday chart for Milk. Both support an optional
  `item` filter.
- `GET /api/dashboard?category=&item=` in `main.py` dispatches to the right
  one based on `RECONCILIATION_CLASSES` membership, same rule used for
  `/api/forecast` and the frontend's mode logic.
- Frontend (`index.html`): a new "Dashboard" / "Order form" view toggle next
  to the category tabs; an item picker (default "All items combined"); four
  Chart.js charts for par-mode categories (weekday, month, season, daily
  trend) and three for reconciliation-mode (month, season, weekly trend).
- **Chart styling reuses the tool's own existing palette** (`--bottle-blue`
  for marks, `--line`/`--muted` for grid and axis text, the same mono/sans
  fonts) rather than introducing a new color system. Every chart here is a
  single-series magnitude comparison (one average per weekday/month/season,
  or one trend line) — there's no multi-series categorical-identity problem
  to solve, so the `dataviz` skill's categorical-palette workflow doesn't
  apply; the skill's other rules still do: one axis, thin bar marks with
  rounded corners, a recessive grid, hover tooltips (bar tooltips show both
  the average and its sample size `n`, so a thin pattern is visibly thin
  rather than looking as confident as a well-supported one), and no chart
  where a stat or table would do.
- Chart.js loaded via CDN, consistent with how PapaParse and xlsx.js are
  already loaded in this file.

## Alternatives considered

- **Hand-rolled inline SVG** instead of Chart.js: ruled out earlier in favor
  of Chart.js for less code to write/maintain for straightforward bar/line
  charts, at the cost of one more CDN dependency.
- **A single combined chart per metric** (e.g. one chart with weekday, month,
  and season all as grouped bars): rejected — mixing categorical axes with
  different cardinalities (7 vs. 12 vs. 4) in one chart obscures more than it
  clarifies; four small, single-purpose charts read faster.

## Consequences

- The dashboard reads live from `/api/dashboard` on every view-toggle click,
  category switch, or item-picker change — no caching layer. Fine at this
  data scale (a café's saved history is at most a few thousand rows); revisit
  if that ever becomes slow.
- No browser-automation tool was available to visually verify the charts
  render correctly in this environment — verified the endpoint's JSON shape
  and values directly (`test_dashboard.py` plus a manual smoke test against
  a seeded database), and reviewed the chart-building JS statically, but the
  actual rendered charts need a human spot-check in a real browser.
