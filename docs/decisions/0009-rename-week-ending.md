# 0009 - Rename week_ending to entry_date

Status: Accepted
Date: 2026-08-04

## Context

Browsing the raw `weeks` table in Railway's Postgres data browser, the
owner was confused by the `week_ending` column: for most rows it holds a
plain daily date (every backfilled par-mode and reconciliation-mode row is
a single day, per ADR 0007), not the end of a calendar week. The column
name is a holdover from before the zero-config/ML rework, when every row
really was a real weekly reconciliation entry. It now reads as misleading —
"week_ending" implies weekly cadence for data that's mostly daily.

## Decision

Renamed throughout the stack, mode-neutral: **`entry_date`** for the SQL
column, **`entryDate`** for the JSON/API field and all JS/Python variables
that carry it. Touched:

- `db.py`: `weeks_table`'s column, the unique constraint (now
  `uq_category_entry_date`), and all four CRUD functions.
- `main.py`: `WeekEntry.entryDate`, the save/delete endpoints' field and
  query param.
- `ml_forecasting.py`, `dashboard.py`: read `week.get("entryDate")`.
- `backfill_import.py`: POST payload key.
- `migrate_sqlite_to_postgres.py`: output payload key — the *input* side
  still reads `week_ending` from an old local `data.db`'s SQL schema as-is,
  since that's a fact about a legacy file, not something to rename.
- `index.html`: the `entryDateInput` DOM element/variable (was
  `weekEndingInput`/`id="weekEnding"`), every `.entryDate` property access,
  `saveWeekToServer()`'s parameter. The **visible label text** "Week ending"
  was deliberately left alone — it's already mode-aware (`onCategoryChange()`
  swaps it to "Date" for par-mode categories), so it's contextually correct
  for real reconciliation entries and was never the source of confusion; only
  the underlying field/column name was.
- All 4 backend test files.

Not renamed: the `weeks` table itself, and the Python function names
(`upsert_week`, `delete_week`, `fetch_history`) — the confusion was
specifically about the column holding a date, not the table or function
names, and renaming those too would widen the diff for no clarity gain.

## Required manual step — live database migration

Unlike every prior change, **this one requires an ALTER TABLE against the
live Postgres databases**, run by the owner (no DB credentials were shared
with or available to the agent making this change). The code was written
assuming the column is already renamed — deploying it without running this
first will 500 on every history-touching endpoint.

```sql
ALTER TABLE weeks RENAME COLUMN week_ending TO entry_date;
ALTER TABLE weeks RENAME CONSTRAINT uq_category_week_ending TO uq_category_entry_date;
```

(The second line is cosmetic — Postgres keeps the constraint working
correctly against the renamed column automatically, since `ON CONFLICT`
resolves by column set, not constraint name — but renaming it too avoids a
second, smaller version of the same confusion later.)

**Required order**, since staging deploys from `dev` and production from
`main` automatically on push:

1. Run the SQL above against the **staging** Postgres (Railway → staging
   environment → Postgres service → Query tab).
2. Push this change to `dev` — staging redeploys with code that now expects
   `entry_date`.
3. Verify staging (`/api/history?category=...` should work normally).
4. Run the same SQL against the **production** Postgres.
5. Merge `dev` → `main` — production redeploys.
6. Verify production the same way.

## Consequences

- All 41 backend tests pass with the new naming; a full local `TestClient`
  smoke test (save → fetch → delete) confirms the whole stack agrees on
  `entryDate` end to end.
- If the ALTER TABLE step is skipped or run out of order relative to the
  deploy, the affected environment's `/api/history`, `/api/forecast`, and
  `/api/dashboard` endpoints will fail until it's run — there's no
  backward-compatibility shim for the old column name, on purpose, since
  this is a two-person internal tool where a short window of "run the SQL,
  then deploy" is an acceptable tradeoff for not carrying dual-naming logic
  forward indefinitely.
