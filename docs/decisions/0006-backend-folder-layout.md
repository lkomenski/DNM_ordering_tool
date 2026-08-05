# 0006 - Backend folder layout

Status: Accepted
Date: 2026-08-04

## Context

By the end of ADRs 0002–0005, `backend/` had accumulated 13 files flat in
one directory: the deployed app (`main.py`, `db.py`, `ml_forecasting.py`,
`dashboard.py`), two standalone operational scripts you run by hand
(`backfill_import.py`, `migrate_sqlite_to_postgres.py`), and four test files
(`test_*.py`), plus `requirements.txt`/`Procfile`/`.gitignore`. The owner
flagged this as confusing to navigate.

## Decision

Split into three subpackages, keeping `requirements.txt`, `Procfile`, and
`.gitignore` at `backend/` root (they describe the whole backend, not one
part of it):

```
backend/
  app/          # the deployed FastAPI application
    __init__.py
    main.py             # routes
    db.py               # storage layer
    ml_forecasting.py   # ML forecasting
    dashboard.py        # dashboard aggregation
  scripts/      # one-off scripts, run by hand, never imported by the server
    __init__.py
    backfill_import.py
    migrate_sqlite_to_postgres.py
  tests/        # pytest suite
    test_db.py
    test_ml_forecasting.py
    test_dashboard.py
    test_backfill_import.py
```

- `main.py`'s imports changed from bare `import db` to relative
  `from . import dashboard, db, ml_forecasting` — standard for a module
  inside a package.
- `Procfile` changed from `uvicorn main:app` to `uvicorn app.main:app`, run
  with `backend/` as the working directory (Railway's root/start directory
  is already set to `backend`, so no deployment config changed beyond the
  Procfile's command itself).
- Tests import `from app import db` / `from app import ml_forecasting as mf`
  / `from app import dashboard` / `from scripts.backfill_import import ...`.
  Running `python -m pytest` from `backend/` puts `backend/` on `sys.path`,
  so `app` and `scripts` resolve as regular packages — no `conftest.py` or
  path hacking needed.
- All path references in the README and in ADRs 0002–0005 describe
  `backend/<file>.py` from before this reorg; they now live under
  `backend/app/` or `backend/scripts/` as laid out above. Not rewriting
  those ADRs' history — this note is the pointer to the current location.

## Consequences

- Verified end-to-end after the move: `python -m pytest` (29/29 passing) and
  a manual `TestClient` smoke test importing `from app.main import app` and
  hitting `/`, `/api/history`, `/api/categories`.
- Anyone running the backend locally now uses `uvicorn app.main:app --reload`
  from inside `backend/`, not `uvicorn main:app --reload`.
- `scripts/backfill_import.py` and `scripts/migrate_sqlite_to_postgres.py`
  are invoked as `python scripts/<name>.py ...` from `backend/` now, not
  `python <name>.py ...`.
