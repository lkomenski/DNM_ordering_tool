# 0008 - Item name aliasing and backfill-only exclusions

Status: Accepted
Date: 2026-08-04

## Context

Preparing to actually backfill the real year-long Product Mix export
(instead of synthetic test data) surfaced two real-world messiness problems
that ADR 0003's "exact product Name = item identity, no fuzzy matching"
design didn't account for:

1. **Same product, different brand name over time.** The café switched milk
   distributors mid-year — e.g. "Smith Brothers 2% Milk - Gallon" and
   "Alpenrose 2% Milk - Gallon" are the same real product (a gallon of 2%
   milk) sold under two different vendor-brand names before/after the
   switch. Treated as two distinct items, the ML model and dashboard would
   see two artificially fragmented, shorter series instead of one
   continuous one — exactly the kind of pattern-learning damage the
   zero-config redesign was supposed to avoid, just from a different cause
   (brand switch, not export format).
2. **A known-broken stretch of historical export data.** Inspecting the real
   file (see ADR 0007) found "Smith Brothers Whole Milk - Gallon" and
   "Smith Brothers 2% Milk - Gallon" each have essentially one non-blank
   day-cell across the entire year (`1`, and `1`/`-1` netting to zero) —
   for products the café has sold continuously since opening. That's a POS
   reporting gap, not a real demand signal, and there's no way to identify
   when it started (the owner: "there's no way to trace it"). A blanket
   "distrust all zeros" rule would be wrong — a real zero-sales day is
   meaningful signal for genuinely low-volume items — so this needed to be
   a targeted exception for these specific known-broken items, not a
   general rule.

## Decision

- **`ITEM_ALIASES`** (`index.html` and `backfill_import.py`, kept in sync,
  matched case-insensitively): maps raw product names to one canonical
  item name. Applied at parse time, before any other logic, in both the
  regular upload path and the backfill script — so `salesByClass`/`by_class`
  accumulate quantities from every aliased raw name under one key. Two
  groups confirmed by the owner:
  - `"Alpenrose 2% Milk - Gallon"` / `"Smith Brothers 2% Milk - Gallon"` → `"2% Milk (Gallon)"`
  - `"Alpenrose Chocolate Reduced Fat 2% Milk - Pint"` / `"Smith Brothers Chocolate 2% Milk - Pint"` → `"Chocolate 2% Milk (Pint)"`
- **`BACKFILL_SKIP_ITEMS`** (`backfill_import.py` only — deliberately NOT
  mirrored to `index.html`): items whose historical export data is known
  broken, skipped during backfill only. Checked on the *raw* name, before
  `ITEM_ALIASES` is applied, so `"Smith Brothers 2% Milk - Gallon"` rows are
  dropped entirely while `"Alpenrose 2% Milk - Gallon"` rows still flow
  through to the canonical `"2% Milk (Gallon)"` series normally. Not
  mirrored to the live-upload path because a historical export gap says
  nothing about whether today's live tracking is trustworthy — if these
  items (or their successors) start reporting correctly, regular uploads
  should track them without needing a code change.
  - `"Smith Brothers Whole Milk - Gallon"`, `"Smith Brothers 2% Milk - Gallon"`
- Both mechanisms follow the same shape as `RECONCILIATION_CLASSES`/
  `EXCLUDED_ITEMS` (ADR 0003): a small hardcoded constant, not a frontend
  control, because "these are the same product" and "this data is broken"
  are both operational judgment calls no amount of parsing logic can infer.
- Verified against the real 365-day export (not just synthetic tests): the
  dry-run log matched `BACKFILL_SKIP_ITEMS` on exactly 2 rows and
  `EXCLUDED_ITEMS` on exactly 3, and the resulting `"2% Milk (Gallon)"`
  series showed up repeatedly across the year, confirming the alias merge
  actually fires on real data, not just the fixture in `test_backfill_import.py`.
- While preparing this real dry-run, also found and fixed an unrelated bug:
  `main()`'s date sort key was the raw label string (e.g.
  `"Wed 07/29/2026"`), which sorts alphabetically by weekday name first, not
  calendar date — made a chronological year of data look sparse/weekly in
  a quick terminal glance. Extracted to `chronological_sort_key()`, tested,
  fixed. Didn't affect what got posted (dates are normalized independently
  before posting), only the preview/log's readability.

## Consequences

- Staging (`dnmorderingtool-staging.up.railway.app`) was backfilled for
  real with the full year: 729 of 731 possible (day × category) combinations
  posted, 0 failures. Confirmed end-to-end afterward: `/api/forecast` for
  Memoranda (Sandwiches) returns real per-item estimates and reasoning
  trained on 4,033 real records; `/api/dashboard` for Smith Brothers Farms
  (Milk) shows a real weekday sold-pattern across 3,005 backfilled days with
  its own model-accuracy check. Production has not been backfilled yet —
  same command, `--api` pointed at the production URL, run separately (no
  auto-sync between environments, see ADR 0002's discussion of staging vs.
  production).
- Like `RECONCILIATION_CLASSES`/`EXCLUDED_ITEMS`, both new constants are
  manually-maintained, code-only lists. If another brand switch or another
  broken-data stretch shows up later, someone has to notice it (by eye, as
  happened here) and add it by hand — there's no automated detection.
