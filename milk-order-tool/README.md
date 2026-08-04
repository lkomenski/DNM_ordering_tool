# Order Reconciliation Tool — Delightful Market

Tracks weekly item ordering (milk, sandwiches, and anything else you add) by
comparing what was ordered, what sold, and what's left — surfacing the gap
Revel can't see (café-used milk, sandwich waste/shrink) and suggesting the
next order.

Two pieces, deployed separately:

- **`frontend/`** — the tool itself (`index.html`). Static, hosted free on GitHub Pages.
- **`backend/`** — a tiny FastAPI service that stores saved weeks in SQLite, so the
  history is the same whether you or Aiden opens the page.

## 1. Deploy the backend (Railway — free tier)

1. Push this whole folder to a GitHub repo (see step 3 below first if you haven't yet, then come back).
2. Go to [railway.app](https://railway.app), sign in with GitHub.
3. **New Project → Deploy from GitHub repo** → pick this repo.
4. Railway will ask for a root/start directory — set it to `backend`.
5. It should auto-detect Python and use the `Procfile` (`uvicorn main:app --host 0.0.0.0 --port $PORT`).
   If it doesn't auto-detect, set the start command manually in Settings → Deploy.
6. Once deployed, Railway gives you a public URL like
   `https://milk-order-tool-production.up.railway.app` — copy it.
7. (Optional but recommended once it's working) In Railway → Variables, add:
   - `ALLOWED_ORIGINS` = your GitHub Pages URL, e.g. `https://yourusername.github.io`
     This locks the API down so random websites can't call it. Comma-separate
     multiple origins if needed.

Render.com works the same way if you'd rather use that — same repo, same
`backend` root directory, same start command, free tier available too.

**Data persistence note:** Railway's free tier filesystem is ephemeral on
redeploy unless you attach a volume. For a low-volume weekly tool this is
usually fine to start, but if you want the SQLite file to survive deploys,
add a Railway Volume mounted at the backend's working directory (Railway →
your service → Settings → Volumes), or point `DB_PATH` at that mount.

## 2. Point the frontend at your backend

Open `frontend/index.html`, find this line near the top of the `<script>`
block:

```js
const API_BASE_URL = "http://localhost:8000";
```

Change it to your Railway URL from step 1:

```js
const API_BASE_URL = "https://milk-order-tool-production.up.railway.app";
```

Save the file.

## 3. Deploy the frontend (GitHub Pages — free)

1. Create a new repo on GitHub (or use an existing one), e.g. `milk-order-tool`.
2. Push this whole project to it:
   ```
   git init
   git add .
   git commit -m "Order reconciliation tool"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```
3. On GitHub: **Settings → Pages**.
4. Under "Build and deployment", set **Source** to "Deploy from a branch".
5. Branch: `main`, folder: if GitHub Pages lets you pick `/frontend`, use that;
   otherwise set folder to `/ (root)` and instead move `frontend/index.html`
   to the repo root (GitHub Pages serves `index.html` from whatever folder
   you point it at, and doesn't support arbitrary subfolders on the free tier
   without a bit of extra config).
6. Save. GitHub will give you a URL like `https://YOUR_USERNAME.github.io/YOUR_REPO/`
   within a minute or two.
7. Send that link to Aiden — no Claude account, no login, works in any browser.

## 4. Verify it's actually talking to the backend

Open the GitHub Pages URL, open your browser's dev console (F12), upload a
Product Mix CSV, save a week. You should see a "Saved" toast and no red
errors in the console. If you get "Could not reach server," double check:

- `API_BASE_URL` in `index.html` matches your live Railway URL exactly (no
  trailing slash)
- The Railway service is actually running (check its logs)
- If you set `ALLOWED_ORIGINS`, it matches your GitHub Pages URL exactly

## 5. Backfilling historical sales (optional, for a real "smarter" baseline)

Once your backend is deployed, if you have a large Product Mix export
(e.g. a full year, in the same wide-day-column format as your regular
weekly exports), you can seed real day-by-day history instead of starting
from zero:

```
cd backend
pip install requests
python backfill_import.py path/to/year_export.csv --api https://your-backend-url --category Sandwiches --dry-run
```

Check the dry-run output looks right, then drop `--dry-run` to actually
import. This creates one real saved entry per day (not one blended
average), which is what lets the "Suggest order" math use real
day-of-week patterns (see below) instead of a flat average.

**Important:** this only makes sense for **par-mode categories** (Sandwiches).
Milk's reconciliation math needs a real physical count for each week, which
can't be reconstructed retroactively — don't run this against Milk.

If you add, rename, or remove sandwich items in `frontend/index.html`
later, update the matching `ITEM_TYPES` list in `backend/backfill_import.py`
too — they're intentionally kept in sync but aren't automatically shared.

## How the "Suggest order" math works (par mode)

- Each saved entry stores that day's actual sold count (`avgDailySold`,
  computed as sold ÷ days-in-file — usually 1 for a single day).
- When you're entering today's count, the tool looks at your saved history
  for **the same day of the week** (e.g. all past Saturdays) and averages
  the most recent ~8 of those, so a Saturday's suggestion is based on past
  Saturdays, not diluted by weekday data.
- If there isn't enough same-weekday history yet (fewer than 3 saved
  entries for that weekday), it falls back to a flat average across
  whatever's been saved recently.
- This is still simple math, not machine learning — no weather, no trend
  detection, no promo awareness. It's a reasonable baseline that gets
  better with more real data, not a forecasting model.


## Notes

- **Item types** (which milk types, which sandwiches) are hardcoded in
  `frontend/index.html` under `DEFAULT_CONFIG`, based on your real CSVs.
  Use "+ Add item type" in the tool to add more on the fly — those
  additions save to the browser you're using (not synced), so for
  something permanent, add it to `DEFAULT_CONFIG` in the code instead.
- **Item matching uses exact-ish full product names on purpose.** Early
  testing caught a real bug where a short generic keyword (like "bacon
  breakfast wrap") silently matched a longer, different product ("Jalapeno
  Bacon Breakfast Wrap") and misattributed its sales. If you add new items,
  prefer full, distinguishing names as keywords rather than short fragments.
- **Weekly/daily history** (ordered/sold/count/suggestions) is the thing
  that syncs between you and Aiden, via the backend.
- This repo has no authentication on the API — anyone with the backend URL
  could technically post fake data. Fine for internal café use; if that
  becomes a concern later, a simple shared API key header is a quick add.
