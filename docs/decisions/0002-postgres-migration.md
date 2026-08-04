# 0002 - SQLite → Postgres migration

Status: Accepted
Date: 2026-08-04

## Context

The backend stored everything in a single SQLite file on the Railway
instance, accessed only through `sqlite3` directly in `main.py`. This was
already shared between Leena and Aiden through the API (not local-only), but
Railway's free-tier filesystem is ephemeral on redeploy unless a Volume is
attached — and this project is about to require several redeploys (Postgres
migration itself, then the auto-detection rework, then the ML forecasting
endpoints, then the dashboard endpoint). Two people now depend on this
history accumulating reliably over time, since the whole point of the ML
forecasting work (ADR 0004) is that more history makes the suggestions
better — losing it on a redeploy would be worse than before this project
started.

Two fixes were on the table: attach a Railway Volume (small, keeps SQLite),
or migrate to managed Postgres (bigger lift, real concurrent-safe database).
The owner chose Postgres — partly for the stronger reliability story with
two people writing concurrently, partly for the portfolio value of a real
migration.

## Decision

- Added `backend/db.py`: a SQLAlchemy Core storage layer against
  `DATABASE_URL` (Railway auto-injects this once its Postgres plugin is
  added), falling back to local SQLite (`sqlite:///data.db`) when
  `DATABASE_URL` is unset.
- The `weeks` table keeps its exact shape (id, category, week_ending,
  entries) and `entries` stays a JSON *string* column, not Postgres-native
  JSONB — nothing queries inside the JSON today, and keeping it a string
  means the identical schema and queries run against both SQLite and
  Postgres, which is what makes `test_db.py` a real test of the production
  code path even though it only ever touches SQLite in this environment.
- `main.py`'s endpoints were rewritten to call `db.py` instead of raw
  `sqlite3`; endpoint behavior/response shapes are unchanged.
- Added `backend/migrate_sqlite_to_postgres.py` — reads an existing local
  `data.db` directly and POSTs every week to a Postgres-backed deployment via
  the existing `/api/history` endpoint, which already upserts on
  `(category, week_ending)`, so the migration is safe to re-run.
- Added `GET /api/categories` (`SELECT DISTINCT category`) to `db.py`/`main.py`
  while touching this layer anyway — it's needed starting ADR 0003 but is a
  trivial addition on top of the same query pattern.

## Alternatives considered

- **Railway Volume + keep SQLite**: less code, no new dependency, but a
  single-file database doesn't handle concurrent writes as gracefully as a
  real database, and doesn't demonstrate a proper migration for the
  portfolio angle the owner cares about here.
- **Postgres-native JSONB for `entries`**: would allow querying inside the
  JSON later, but breaks SQLite/Postgres parity for testing, and nothing
  needs that querying yet. Can migrate the column type later without
  touching the rest of the schema if it becomes useful.

## Consequences

- New dependencies: `sqlalchemy`, `psycopg2-binary`, `requests` (for the
  migration script), `pytest`.
- `psycopg2-binary==2.9.9` (the originally planned pin) has no prebuilt wheel
  for Python 3.13 on Windows and fails to build from source (`pg_config`
  missing). Pinned `2.9.12` instead, which does ship a matching wheel — worth
  knowing if this ever needs pinning again on a newer Python.
- **No local Postgres or Docker is available in this dev environment**, so
  `test_db.py` only proves the query logic against SQLite. The Postgres code
  path (real `DATABASE_URL`, `pg_insert().on_conflict_do_update()`) is
  exercised for the first time on Railway. Verify after deploying: add the
  Postgres plugin, redeploy, save a test week from the app, confirm it
  appears in `GET /api/history`, and confirm it survives a second redeploy.
- The old raw-`sqlite3` `get_db()` context manager in `main.py` is gone;
  anything that imported it directly (nothing currently does, outside
  `main.py` itself) would need updating to use `db.get_engine()` instead.
