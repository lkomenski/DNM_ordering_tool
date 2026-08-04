# Order Reconciliation Tool — Delightful Market

Tracks weekly item ordering (milk, sandwiches, and anything else you add) by
comparing what was ordered, what sold, and what's left — surfacing the gap
Revel can't see (café-used milk, sandwich waste/shrink) and suggesting the
next order.

Two pieces, deployed separately:

- **The tool itself** — `index.html` at the **repo root**. (An older
  `frontend/index.html` duplicate existed from before the frontend moved to
  the root for GitHub Pages and has been removed — root was always the one
  actually deployed.) Static, hosted free on GitHub Pages.
- **`backend/`** — a FastAPI service that stores saved history in Postgres
  (local dev falls back to SQLite automatically), runs the ML forecasting
  model, and serves the dashboard aggregates — so the history and the
  suggestions are the same whether you or Aiden opens the page. Layout:
  `app/` is the deployed application (`main.py` + the `db`/`ml_forecasting`/
  `dashboard` modules it imports), `scripts/` holds one-off operational
  scripts you run by hand (backfill, the Postgres migration) rather than
  anything the server imports, `tests/` holds the pytest suite.

Full write-up of what was decided and why, including anything unexpected hit
along the way, is in [`docs/decisions/`](../docs/decisions/) at the repo root.

## 1. Deploy the backend (Railway — free tier)

1. Push this whole folder to a GitHub repo (see step 3 below first if you haven't yet, then come back).
2. Go to [railway.app](https://railway.app), sign in with GitHub.
3. **New Project → Deploy from GitHub repo** → pick this repo.
4. Railway will ask for a root/start directory — set it to `backend`.
5. It should auto-detect Python and use the `Procfile` (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
   If it doesn't auto-detect, set the start command manually in Settings → Deploy.
6. Once deployed, Railway gives you a public URL like
   `https://milk-order-tool-production.up.railway.app` — copy it.
7. (Optional but recommended once it's working) In Railway → Variables, add:
   - `ALLOWED_ORIGINS` = your GitHub Pages URL, e.g. `https://yourusername.github.io`
     This locks the API down so random websites can't call it. Comma-separate
     multiple origins if needed.

Render.com works the same way if you'd rather use that — same repo, same
`backend` root directory, same start command, free tier available too.

### Data persistence: add Postgres

Railway's free tier filesystem is ephemeral on redeploy, and since multiple
people depend on this history building up reliably, the backend uses
Postgres in production rather than a plain file on disk:

1. In your Railway project: **New → Database → Add PostgreSQL**.
2. Railway automatically sets a `DATABASE_URL` variable on your backend
   service — no manual copy/paste needed, and no code change either (`db.py`
   picks it up automatically; SQLite is only used as a local-dev fallback
   when `DATABASE_URL` isn't set).
3. Redeploy the backend service so it picks up the new variable.
4. **If you already had data in the old SQLite file**, migrate it once:
   ```
   cd backend
   python scripts/migrate_sqlite_to_postgres.py path/to/old/data.db --api https://your-backend-url --dry-run
   ```
   Check the dry-run output, then drop `--dry-run` to actually migrate. Safe
   to re-run — it overwrites matching weeks rather than duplicating them.

See `docs/decisions/0002-postgres-migration.md` for why.

## 2. Point the frontend at your backend

Open **`index.html` at the repo root**, find this line near the top of the
`<script>` block:

```js
const API_BASE_URL = "https://dnmorderingtool-production.up.railway.app";
```

Change it to your Railway URL from step 1, then commit and push — GitHub
Pages serves this file directly.

## 3. Deploy the frontend (GitHub Pages — free)

GitHub Pages is already configured to serve `index.html` from the repo root
on the `main` branch. To redeploy after a change: commit and push to `main`
(work happens on a `dev` branch first — see `docs/decisions/0001-scope-and-decisions-so-far.md`
for why — then merge to `main` when you're ready to go live). GitHub Pages
picks up the new `index.html` within a minute or two of the push landing on
`main`.

If you're setting this up from scratch on a new repo: **Settings → Pages**,
set **Source** to "Deploy from a branch", branch `main`, folder `/ (root)`.

## 4. Verify it's actually talking to the backend

Open the GitHub Pages URL, open your browser's dev console (F12), upload a
Product Mix CSV, save a week. You should see a "Saved" toast and no red
errors in the console. If you get "Could not reach server," double check:

- `API_BASE_URL` in `index.html` matches your live Railway URL exactly (no
  trailing slash)
- The Railway service is actually running (check its logs)
- If you set `ALLOWED_ORIGINS`, it matches your GitHub Pages URL exactly

## 5. Backfilling historical sales (strongly recommended — this is what the ML model learns from)

Once your backend is deployed, if you have a large Product Mix export
(e.g. a full year, in the same wide-day-column format as your regular
uploads), seed real day-by-day history instead of starting from zero:

```
cd backend
pip install requests
python scripts/backfill_import.py path/to/year_export.csv --api https://your-backend-url --dry-run
```

Check the dry-run output looks right, then drop `--dry-run` to actually
import. Category, vendor, and every item are read straight from the file's
Class/Name columns — no list to keep in sync, and any item not in the app
yet (a sandwich or milk type you haven't seen before) is picked up
automatically. Pass `--only-category "Memoranda"` if the file has multiple
product lines mixed together and you only want to import one for now.

**Reconciliation-mode categories (Milk) get backfilled too, but only with
`sold` quantity** — never `beginning`/`ordered`/`endingCount`/`gap`/`totalUsed`,
since those need a real physical count each week that can't be reconstructed
after the fact. This can't touch the Suggest-order number (that only ever
reads `totalUsed`, which these rows deliberately don't have) — it only feeds
Milk's Dashboard view (a sold-quantity pattern by weekday/month/season, plus
a model-accuracy check), same as it does for par-mode categories. See
`docs/decisions/0007-backfill-milk-sold-pattern.md`.

Products that get rung up under a tracked Class by mistake (e.g. a grocery
item sharing a department with milk) can be excluded by adding them to
`EXCLUDED_ITEMS` in both `index.html` and `backend/scripts/backfill_import.py`
— a small hardcoded list, matched case-insensitively, kept in sync by hand.

This creates one real saved entry per day (not one blended average), which
is exactly what `backend/app/ml_forecasting.py` trains on — the more you
backfill, the more history the model has to learn day-of-week/month/season
patterns from, per item.

## How the "Suggest order" math works

**Par-mode categories** (Sandwiches, or anything else that isn't Milk):

- A `RandomForestRegressor` is trained per category (pooling every item in
  it) on day-of-week, month, weekend-vs-weekday, and a long-term trend
  index, with item identity as its own feature — so it learns different
  patterns per item, not one blended category-wide average. See
  `docs/decisions/0004-ml-forecasting.md` for the full design and why.
- Each item's suggestion is shown with a plain-language reasoning line
  (e.g. "Based on 5 past Saturdays in August...") so the number isn't a
  black box, plus a model accuracy line showing how it's actually
  performing against a naive average on real holdout data.
- With fewer than 15 saved days for a category, there isn't enough data to
  train on yet — it falls back to a plain average and says so explicitly,
  rather than pretending a model trained on a handful of points means
  anything.
- A **Dashboard** view (per category) shows the same patterns the model is
  using — by day of week, by month, by season, and a trend line over time —
  via `GET /api/dashboard`. See `docs/decisions/0005-dashboards.md`.

**Milk (reconciliation mode)** is untouched by any of the above — it still
uses a simple trailing average of `Beginning + Ordered − Sold − Ending`
across recent saved weeks (`avgWeeklyTotalUse` in `index.html`), since
that's a fundamentally different question (hidden/unrung usage) than a
sell-through forecast.

## Notes

- **Items, vendors, and categories are fully auto-detected** from each
  upload's Class/Name columns — there's no manual list to maintain anymore.
  See `docs/decisions/0003-auto-detect-items-and-categories.md`. The one
  thing that *is* still a hardcoded constant (by necessity — it's a business
  rule, not something in the data) is which category needs reconciliation
  math: `RECONCILIATION_CLASSES` in `index.html`, mirrored in
  `backend/app/main.py` and `backend/scripts/backfill_import.py`. If that value is ever
  wrong or a second reconciliation-mode category gets added, update all
  three.
- **Weekly/daily history** (ordered/sold/count/suggestions) is the thing
  that syncs between you and Aiden, via the backend.
- This repo has no authentication on the API — anyone with the backend URL
  could technically post fake data. Fine for internal café use; if that
  becomes a concern later, a simple shared API key header is a quick add.
- Ideas discussed but deliberately not built yet (weather signals,
  hour-of-day data, labor/scheduling) are logged in
  [`../docs/future-ideas.md`](../docs/future-ideas.md).
