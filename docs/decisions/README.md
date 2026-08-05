# Architecture Decision Records

This folder logs the nontrivial decisions behind the Order Reconciliation
Tool — what was decided, why, and what was ruled out — plus anything
unexpected hit along the way. Numbered chronologically; don't renumber old
ones when adding new ones.

| ADR | Title |
|---|---|
| [0001](0001-scope-and-decisions-so-far.md) | Scope and decisions so far |
| [0002](0002-postgres-migration.md) | SQLite → Postgres migration |
| [0003](0003-auto-detect-items-and-categories.md) | Auto-detect items, vendor, and category from uploads |
| [0004](0004-ml-forecasting.md) | ML-based demand forecasting for par-mode categories |
| [0005](0005-dashboards.md) | Sales trend dashboards |
| [0006](0006-backend-folder-layout.md) | Backend folder layout (app/scripts/tests split) |
| [0007](0007-backfill-milk-sold-pattern.md) | Backfill Milk's sold-quantity pattern (dashboard-only) |
| [0008](0008-item-name-aliasing.md) | Item name aliasing and backfill-only exclusions |
| [0009](0009-rename-week-ending.md) | Rename week_ending to entry_date (requires manual DB migration — see file) |

See also [`../future-ideas.md`](../future-ideas.md) — things discussed and
deliberately deferred (weather features, hour-of-day data, labor/scheduling),
kept there rather than as ADRs since nothing was decided, just scoped out.

## Template

```markdown
# NNNN - Title

Status: Accepted | Superseded by NNNN | Rejected
Date: YYYY-MM-DD

## Context
What problem or question prompted this. What was already true in the code.

## Decision
What we're doing.

## Alternatives considered
What else was on the table and why it lost.

## Consequences
What this makes easier, what it makes harder, what to watch for.
```
