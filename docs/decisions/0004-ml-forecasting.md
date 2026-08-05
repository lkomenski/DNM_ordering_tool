# 0004 - ML-based demand forecasting for par-mode categories

Status: Accepted
Date: 2026-08-04

## Context

The original PAR suggestion (`avgDailySoldFromHistory()` in `index.html`)
recognized exactly one pattern: same weekday, ≥3 samples else a flat
average, blended with the latest upload's rate at a fixed 0.7/0.3 split. The
owner wants the suggestion to genuinely learn across day-of-week, month, and
season as data accumulates, explain its reasoning, and — explicitly for
portfolio purposes — wants the "learning" to be real machine learning, not a
hand-tuned statistical formula. The owner has no ML background and mentioned
wanting to add external signals (weather, school calendar) in the future,
which shaped the feature design even though those signals aren't built now.

## Decision

- New `backend/ml_forecasting.py`: one `RandomForestRegressor` **per
  category**, pooling every item in that category rather than training one
  model per item. Features: `item` (categorical), `day_of_week`, `month`,
  `is_weekend`, and `day_index` (days since the category's earliest saved
  record, capturing trend/drift). Pooling is what handles cold start — a
  brand-new item with only a handful of saved days still inherits the
  category's weekday/month patterns from the items with a full history,
  instead of needing its own history before the model says anything useful.
- **Cold-start guard**: categories with fewer than `MIN_ROWS_TO_TRAIN` (15)
  total saved days skip training entirely and fall back to a plain average,
  with the reasoning string saying so explicitly — the system is honest
  about when it doesn't have enough to work with, rather than pretending a
  model trained on 4 data points means something.
- **Reasoning** (`explain()`): blends a concrete same-weekday-same-month
  analog ("4 past Saturdays in August, avg 12.1/day") with the model's
  `feature_importances_` ranking ("the model weighed day of week and which
  item most heavily") — real ML output, still legible to someone with no ML
  background.
- **Validation** (`validate()`): a time-based holdout (train on the earliest
  ~85% of dates, evaluate on the most recent ~15%) reports MAE against a
  naive flat-average baseline. This is the literal, checkable proof that
  accuracy improves as data accumulates — surfaced in the app as "Model
  accuracy: off by X.X/day on average ... Y% better than a flat average"
  rather than just asserted in a doc.
- `GET /api/forecast?category=&targetDate=` in `main.py` — rejects
  reconciliation-mode categories (400) rather than silently returning
  nonsense, since Milk's suggestion math is untouched by this feature
  entirely.
- Frontend (`index.html`): fetches the forecast once per category+date
  change, caches it, and `recomputeAll()` blends the cached estimate with
  the just-uploaded (not-yet-saved) file's rate the same 0.7/0.3 way the old
  code did — the backend can't see data that hasn't been saved yet. If the
  fetch fails, falls back to the old client-side `avgDailySoldFromHistory()`
  so the tool still works offline or if the backend is down. Each item's row
  shows its `reasoning` as a small line under the item name.
- Designed for extensibility: `FEATURE_COLUMNS` is a flat list a future
  weather or school-calendar signal could join without restructuring
  anything — not built now, explicitly out of scope, but the owner's
  stated future interest shaped this choice.

## Alternatives considered

- **XGBoost instead of scikit-learn's RandomForest**: offered as an option;
  the owner had no strong preference. RandomForest was chosen for one fewer
  dependency (no extra boosting library) and because `min_samples_leaf`
  regularization behaves predictably on the small datasets this tool will
  have for a long time (a few thousand rows at most).
- **One model per item** instead of pooling per category: rejected — with
  daily café-scale data, individual items often don't have enough history on
  their own for a stable tree ensemble, and per-item models can't share the
  weekday/seasonal pattern that's common across a whole product line.
- **SHAP for explanations**: more standard in ML explainability, but adds a
  dependency and complexity beyond what a two-line reasoning string needs
  here; plain `feature_importances_` plus a concrete historical analog gets
  the same legibility with much less code.

## Consequences

- New dependencies: `scikit-learn`, `pandas`, `numpy`. All installed and
  tested locally; no GPU or special runtime needed, trains in low
  milliseconds at this data scale.
- `RANDOM_STATE = 0` is fixed for reproducibility — forecasts (and their
  reasoning) are deterministic given the same saved history and target date,
  which matters for debugging and for the "why did it suggest this" trust
  the owner asked for.
- `test_ml_forecasting.py` proves the core claims on synthetic data: the
  model recovers a planted day-of-week signal, beats a naive baseline once
  there's enough data, and — the specific "gets smarter over time" check —
  a forecast built on 140 days of history lands measurably closer to the
  true rate than the same forecast built on only 10 days.
- The cold-start threshold (15 rows) and holdout split (85/15) are
  reasonable starting points, not tuned against real café data yet — revisit
  once real Sandwiches history accumulates and `modelAccuracy` is visible in
  the app.
