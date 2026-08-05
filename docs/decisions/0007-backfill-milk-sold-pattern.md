# 0007 - Backfill Milk's sold-quantity pattern (dashboard-only)

Status: Accepted
Date: 2026-08-04

## Context

The owner wants to backfill a year of Milk sales data too, not just
Sandwiches — "the more data the better" — to train the ML pattern-learning
layer on Milk's demand, not just leave it at the flat trailing-average
reconciliation math. But real ordered/beginning/ending counts for a whole
past year aren't practically enterable ("we don't really have the ability to
enter in how many ordered in the past... that would be too much"), and
reconciliation math absolutely requires those to compute the hidden-usage
gap. The explicit ask: backfill just helps with "quantity sold over time,
generally" — the actual weekly ordering keeps using real physical counts,
going forward, exactly as it does today.

A real technical trap here: a backfilled day's `sold` figure and a real
saved week's `sold` figure are **different units**. Backfilled entries come
from the Product Mix Daily export, one row per day — `sold` there is a
single day's quantity. A real reconciliation entry's `sold` is a whole
week's POS total (the amount rung up between saves, typically ~7 days,
though reconciliation entries don't even track how many days that spans).
Feeding both into one "daily rate" signal without distinguishing them would
badly corrupt any day-of-week pattern the model tries to learn — a real
week's total would look like an enormous, false "outlier day."

## Decision

- `scripts/backfill_import.py` no longer skips reconciliation-mode classes.
  It now posts them shaped as `{"vendor": class_name, "sold": qty}` —
  deliberately omitting `beginning`/`ordered`/`endingCount`/`gap`/`totalUsed`,
  since those aren't knowable retroactively.
- The **Suggest-order number is provably unaffected**: `avgWeeklyTotalUse()`
  (frontend) only reads entries with a numeric `totalUsed`; backfilled rows
  never have that key, so they're automatically excluded. `/api/forecast`
  still hard-rejects reconciliation categories (400), so there's no path
  from backfilled data to the order-form's number at all.
- The daily-vs-weekly unit trap is solved with one rule, `ml_forecasting.daily_rate(entry)`:
  an entry counts as "one day's quantity" if it has `avgDailySold` (par mode,
  always daily), OR if it has `sold` **and no `totalUsed` key at all**. A
  real reconciliation week always has `totalUsed` (even if 0), so it's
  structurally impossible for a real week to be misread as a backfilled day
  — the exclusion is by data shape, not a fragile heuristic. `dashboard.py`
  and `ml_forecasting.py` both route through this one function, so the
  dashboard's sold-pattern charts and the model that computes their accuracy
  number always agree on which rows count.
- `dashboard.py`'s `reconciliation_dashboard()` now returns a `soldPattern`
  sub-object (weekday/month/season/daily-trend, same shape as `par_dashboard`)
  built entirely from daily-rate-shaped rows, plus a `modelAccuracy` check
  (reusing `ml_forecasting.validate()`) — the same "does it actually get
  more accurate" proof Sandwiches gets. The existing `byMonth`/`bySeason`/
  `weeklyTrend` (the hidden-usage rollup from real weeks) is untouched.
- **Dashboard-only**, per explicit confirmation: no forecast number or
  reasoning is added to the order-entry form for Milk. The Suggest-order
  column keeps coming from the reconciliation trailing average exactly as
  before; the sold-pattern charts and model-accuracy line are purely
  informational, visible on Milk's Dashboard view.
- `getLastEnding()` (frontend) was hardened to only treat an entry with a
  numeric `endingCount` as a valid "beginning inventory" carry-forward
  source — otherwise a backfilled day sorting as the most recent entry could
  wrongly zero out next week's beginning count. `renderHistory()`'s
  reconciliation table now shows "—" instead of the literal string
  "undefined" for fields a backfilled row doesn't have.
- **New**: `EXCLUDED_ITEMS` (`index.html` and `backfill_import.py`, matched
  case-insensitively) — a small hardcoded list of product names that show up
  under a tracked Class by mistake in Revel (grocery items sharing a
  department with milk) and aren't actually part of this tool's ordering.
  Same treatment as `RECONCILIATION_CLASSES`: a business-knowledge exception
  that can't be inferred from the data, kept as a code constant rather than
  a frontend control, filtered out at parse time in both the regular upload
  path and the backfill script.

## Alternatives considered

- **A separate category/table just for Milk's sold-quantity signal** (fully
  isolated from the reconciliation category): rejected — adds a second
  category per vendor for no real benefit; the shape-based `daily_rate()`
  rule already guarantees real reconciliation weeks can't contaminate the
  signal, so isolation by data shape is sufficient without isolation by
  category too.
- **Converting a real week's `sold` into an implied daily rate** (dividing
  by an assumed ~7 days): rejected — reconciliation entries don't track how
  many days a save actually spans, so the divisor would be a guess, and a
  wrong guess corrupts the pattern more subtly (and more dangerously) than
  just excluding the row outright.
- **Showing the ML forecast on the order-entry form too**, not just the
  dashboard: explicitly declined by the owner — the Suggest-order column
  stays 100% reconciliation-math, no exceptions.

## Consequences

- Until Milk backfill actually runs, `soldPattern.nRecords` is 0 and the
  dashboard shows nothing extra for Milk beyond what it already had —
  verified via `test_dashboard.py`'s new tests and a manual end-to-end
  smoke test (60 backfilled days + 1 real week posted through the actual
  API; confirmed the real week only affects `nRecords`/`byMonth`, never
  `soldPattern`, and `/api/forecast` still 400s for Milk).
- `EXCLUDED_ITEMS` currently has 3 entries the owner spotted by eye while
  reviewing their export. There's no tooling yet to *discover* future
  miscategorized items automatically — if more show up, they'll need to be
  reported and added by hand to both `index.html` and `backfill_import.py`.
