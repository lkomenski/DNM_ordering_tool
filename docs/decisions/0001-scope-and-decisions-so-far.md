# 0001 - Scope and decisions so far

Status: Accepted
Date: 2026-08-04

## Context

Starting point: the Sandwiches PAR suggestion (`avgDailySoldFromHistory()` in
`frontend/index.html`) only recognized one pattern — same weekday, ≥3 samples
else a flat average — blended with the latest upload's rate at a fixed
0.7/0.3 split. The ask was to make it actually learn from accumulating sales
data across multiple time dimensions (day-of-week, month, season — not
time-of-day, since the Product Mix export has no hourly breakdown), explain
its reasoning, and add a trends dashboard for both Milk and Sandwiches,
without touching Milk's reconciliation math unless necessary.

Clarifying the approach surfaced several decisions with wider blast radius
than the original ask, recorded here before any code changed.

## Decisions

1. **Milk keeps its reconciliation formula** (Beginning + Ordered − Sold −
   Ending = hidden café usage). This is the only way to catch milk poured
   into drinks that Revel never rings up; a plain par (on-hand vs.
   sell-through) calculation can't recover that signal. The manual
   mode toggle ("Weekly reconciliation" / "Daily par ordering") is removed
   anyway — mode becomes implicit per category (see ADR 0003) instead of a
   user-facing switch, since letting any category be switched to either mode
   never actually made sense.

2. **No manually-maintained item/vendor/category config.** The Product Mix
   CSV's `Class` column carries both vendor and category — the café's Revel
   setup names its product categories after its vendors (e.g. "Smith
   Brothers Farms", "Memoranda"). So items, vendors, and category tabs can
   all be derived straight from what's uploaded, with one exception: whether
   a category needs reconciliation math instead of par math is a business
   rule the POS data can't express, so it's a hardcoded constant in code —
   `"Smith Brothers Farms"` → reconciliation — not a frontend control. See
   ADR 0003.

3. **The pattern-recognition engine is real ML (scikit-learn), not a
   hand-tuned statistical blend.** Explicitly for portfolio value — the
   owner has no ML background but wants the tool to genuinely learn, has
   future interest in adding external signals (weather, school calendar) as
   inputs, and wants the improvement-over-time claim to be a checkable
   number, not an assertion. See ADR 0004.

4. **Data durability: migrate to managed Postgres.** The SQLite file already
   lives on Railway and is already shared between the owner and a co-worker
   through the API — it was never local-only. But Railway's free-tier disk
   is ephemeral on redeploy without a Volume, and every phase of this work
   requires a redeploy. Given multiple people depend on this data building
   up reliably, and the portfolio value of showing a real migration, the
   owner chose Postgres over the smaller Volume fix. See ADR 0002.

5. **Process**: work happens on a `dev` branch, since `main` auto-deploys to
   GitHub Pages + Railway on push and none of this should go live
   incrementally. Every nontrivial decision — including these — gets written
   down here as it's made, not just at the end.

## Consequences

- This is a four-phase build (durability → auto-detection → ML forecasting →
  dashboards) instead of the originally-scoped "additive forecasting tweak."
- The existing manual "Item types" config UI and mode toggle go away
  entirely for both categories, which does touch Milk's UI — but only
  because it was explicitly requested, not as a side effect of the
  forecasting work.
- No browser-automation tooling is available in the session doing this work,
  and no local Postgres/Docker either — both are called out per-phase as
  verification gaps that need a human spot-check after deploying.
- Mid-session discovery: `milk-order-tool/frontend/index.html` was a stale
  duplicate of the root `index.html` (the one GitHub Pages actually serves),
  left over from before the frontend moved to the repo root. The first pass
  of Phase 2 accidentally edited the wrong copy; those edits were reverted
  (`git checkout --`) and redone against root `index.html`. The stale
  duplicate has since been deleted at the owner's request — root
  `index.html` is now the single source of truth.
