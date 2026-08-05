"""
ML-based demand forecasting for par-mode categories.

Pools all items within a category into one RandomForestRegressor trained on
calendar features (day-of-week, month, is-weekend, a trend index) plus item
identity as a categorical feature. Pooling means a brand-new item with only
a few saved days still gets a sensible weekday/month prior from the rest of
the category's history instead of needing its own history before the model
says anything useful — this is what handles cold start, rather than a
separate fallback formula bolted on top.

Designed so a future external signal (weather, school calendar, etc.) is
just one more feature column — not built now, out of scope, but the shape
is there. See docs/decisions/0004-ml-forecasting.md.

Milk's reconciliation-mode Suggest-order math is untouched by this module —
`/api/forecast` still rejects reconciliation categories outright (see
main.py). But reconciliation-mode history CAN feed the dashboard's pattern
learning (see daily_rate() below and docs/decisions/0007-backfill-milk-sold-pattern.md),
as long as it's genuinely daily-rate data (a backfilled day), never a real
week's aggregate `sold` total — mixing those units would corrupt the model.
"""

import datetime
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

MIN_ROWS_TO_TRAIN = 15
N_ESTIMATORS = 200
RANDOM_STATE = 0

FEATURE_COLUMNS = ["item", "day_of_week", "month", "is_weekend", "day_index"]
CATEGORICAL_COLUMNS = ["item", "day_of_week", "month"]

FEATURE_LABELS = {
    "item": "which item",
    "day_of_week": "day of week",
    "month": "month",
    "is_weekend": "weekend vs. weekday",
    "day_index": "long-term trend",
}


def _parse_date(date_str):
    y, m, d = (int(p) for p in date_str.split("-"))
    return datetime.date(y, m, d)


def daily_rate(entry):
    """Extract a comparable 'quantity for one day' from a saved entry, or
    None if this entry can't safely be treated as one.

    Par-mode entries always qualify via avgDailySold. Reconciliation-mode
    entries only qualify if they're missing `totalUsed` — that's exactly a
    backfilled day (see scripts/backfill_import.py), which only ever stores
    `sold`. A REAL reconciliation week (has totalUsed) always has `sold`
    too, but that figure is a whole week's total, not a daily rate — mixing
    it in here would silently corrupt the day-of-week pattern the model
    learns. See docs/decisions/0007-backfill-milk-sold-pattern.md.
    """
    if not isinstance(entry, dict):
        return None
    rate = entry.get("avgDailySold")
    if isinstance(rate, (int, float)) and not isinstance(rate, bool):
        return float(rate)
    if "totalUsed" not in entry:
        rate = entry.get("sold")
        if isinstance(rate, (int, float)) and not isinstance(rate, bool):
            return float(rate)
    return None


def build_training_frame(weeks):
    """weeks: history rows shaped like db.fetch_history's output —
    [{entryDate, entries}]. Returns a DataFrame with one row per (date,
    item) that has a usable daily_rate(): columns date, item, rate."""
    records = []
    for week in weeks:
        date_str = week.get("entryDate")
        if not date_str:
            continue
        try:
            date = _parse_date(date_str)
        except (ValueError, TypeError):
            continue
        for item, entry in (week.get("entries") or {}).items():
            rate = daily_rate(entry)
            if rate is not None:
                records.append({"date": date, "item": item, "rate": rate})
    return frame_from_records([(r["date"], r["item"], r["rate"]) for r in records])


def frame_from_records(records):
    """records: [(date, item, rate)], already filtered/scoped by the caller
    (e.g. dashboard.py, which needs the same rows for a chart and for
    validate()). Same output shape as build_training_frame."""
    if not records:
        return pd.DataFrame(columns=["date", "item", "rate"])
    df = pd.DataFrame(records, columns=["date", "item", "rate"])
    return df.sort_values("date").reset_index(drop=True)


def _add_calendar_features(df, min_date):
    out = df.copy()
    out["day_of_week"] = out["date"].apply(lambda d: d.weekday())
    out["month"] = out["date"].apply(lambda d: d.month)
    out["is_weekend"] = out["day_of_week"].isin([5, 6]).astype(int)
    out["day_index"] = out["date"].apply(lambda d: (d - min_date).days)
    return out


def _build_pipeline():
    preprocessor = ColumnTransformer(
        transformers=[("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_COLUMNS)],
        remainder="passthrough",
    )
    model = RandomForestRegressor(
        n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, min_samples_leaf=2
    )
    return Pipeline([("prep", preprocessor), ("model", model)])


@dataclass
class TrainedModel:
    pipeline: object
    min_date: datetime.date
    frame: object  # calendar-featured training frame, kept around for explain()


def train_model(df):
    """df: output of build_training_frame. Returns None when there isn't
    enough data to train on — callers should fall back to a simple average."""
    if len(df) < MIN_ROWS_TO_TRAIN:
        return None
    min_date = df["date"].min()
    featured = _add_calendar_features(df, min_date)
    pipeline = _build_pipeline()
    pipeline.fit(featured[FEATURE_COLUMNS], featured["rate"])
    return TrainedModel(pipeline=pipeline, min_date=min_date, frame=featured)


def predict(trained, target_date, items):
    """Returns {item: predicted_rate}, clamped to >= 0."""
    if not items:
        return {}
    rows = pd.DataFrame({
        "item": items,
        "day_of_week": [target_date.weekday()] * len(items),
        "month": [target_date.month] * len(items),
        "is_weekend": [1 if target_date.weekday() in (5, 6) else 0] * len(items),
        "day_index": [(target_date - trained.min_date).days] * len(items),
    })
    preds = trained.pipeline.predict(rows[FEATURE_COLUMNS])
    return {item: max(0.0, float(p)) for item, p in zip(items, preds)}


def _feature_importance_ranking(trained):
    prep = trained.pipeline.named_steps["prep"]
    model = trained.pipeline.named_steps["model"]
    try:
        feature_names = prep.get_feature_names_out()
    except Exception:
        return []
    grouped = {}
    for name, imp in zip(feature_names, model.feature_importances_):
        base = name.split("__", 1)[-1]
        matched = next((col for col in FEATURE_COLUMNS if base == col or base.startswith(col + "_")), base)
        grouped[matched] = grouped.get(matched, 0.0) + float(imp)
    return sorted(grouped.items(), key=lambda kv: kv[1], reverse=True)


def explain(trained, target_date, item):
    """Reasoning string blending a concrete same-weekday(-month) analog with
    the model's feature-importance ranking — real ML output, still legible."""
    frame = trained.frame
    item_rows = frame[frame["item"] == item]
    n_item_total = len(item_rows)

    same_dow_month = item_rows[
        (item_rows["day_of_week"] == target_date.weekday()) & (item_rows["month"] == target_date.month)
    ]
    same_dow = item_rows[item_rows["day_of_week"] == target_date.weekday()]

    weekday_name = target_date.strftime("%A")
    month_name = target_date.strftime("%B")

    parts = []
    if len(same_dow_month) >= 2:
        avg = same_dow_month["rate"].mean()
        parts.append(f"{len(same_dow_month)} past {weekday_name}s in {month_name} (avg {avg:.1f}/day)")
    elif len(same_dow) >= 2:
        avg = same_dow["rate"].mean()
        parts.append(f"{len(same_dow)} past {weekday_name}s overall (avg {avg:.1f}/day)")

    ranking = _feature_importance_ranking(trained)
    top_features = [FEATURE_LABELS.get(name, name) for name, _ in ranking[:2]]
    if top_features:
        parts.append(
            f"the model weighed {' and '.join(top_features)} most heavily across {n_item_total} saved day(s) for this item"
        )

    if not parts:
        return f"Trained on {len(frame)} saved day(s) across this category; not enough {item}-specific history yet for a detailed breakdown."
    return "Based on " + "; ".join(parts) + "."


def validate(df):
    """Time-based holdout (earliest ~85% of dates trains, most recent ~15%
    is evaluated). Returns None when there isn't enough data to hold
    anything out meaningfully. This is the checkable 'does it actually get
    more accurate' number, meant to be shown on the dashboard rather than
    asserted."""
    if len(df) < MIN_ROWS_TO_TRAIN * 2:
        return None
    dates = sorted(df["date"].unique())
    split_idx = int(len(dates) * 0.85)
    if split_idx < 1 or split_idx >= len(dates):
        return None
    split_date = dates[split_idx]

    train_df = df[df["date"] < split_date]
    test_df = df[df["date"] >= split_date]
    if len(train_df) < MIN_ROWS_TO_TRAIN or len(test_df) == 0:
        return None

    trained = train_model(train_df)
    if trained is None:
        return None

    featured_test = _add_calendar_features(test_df, trained.min_date)
    preds = np.clip(trained.pipeline.predict(featured_test[FEATURE_COLUMNS]), 0, None)
    actual = featured_test["rate"].values

    mae = float(mean_absolute_error(actual, preds))
    naive_baseline = float(train_df["rate"].mean())
    naive_mae = float(mean_absolute_error(actual, [naive_baseline] * len(actual)))

    return {
        "mae": mae,
        "naiveMae": naive_mae,
        "nHoldout": int(len(test_df)),
        "nTrain": int(len(train_df)),
        "improvementOverNaive": ((naive_mae - mae) / naive_mae) if naive_mae > 0 else None,
    }


def forecast_category(weeks, target_date_str):
    """Top-level entry point for GET /api/forecast. Returns
    {targetDate, items: {label: {estimate, reasoning}}, modelAccuracy}."""
    target_date = _parse_date(target_date_str)
    df = build_training_frame(weeks)
    items = sorted(df["item"].unique().tolist()) if not df.empty else []

    trained = train_model(df)
    accuracy = validate(df)

    result_items = {}
    if trained is not None and items:
        estimates = predict(trained, target_date, items)
        for item in items:
            result_items[item] = {
                "estimate": round(estimates[item], 2),
                "reasoning": explain(trained, target_date, item),
            }
    else:
        for item in items:
            item_rates = df[df["item"] == item]["rate"]
            avg = float(item_rates.mean()) if len(item_rates) else 0.0
            result_items[item] = {
                "estimate": round(avg, 2),
                "reasoning": (
                    f"Not enough history yet for a trained model ({len(df)} saved day(s) total across "
                    f"this category, need {MIN_ROWS_TO_TRAIN}+) — using a simple average of "
                    f"{len(item_rates)} saved day(s) for this item."
                ),
            }

    return {"targetDate": target_date_str, "items": result_items, "modelAccuracy": accuracy}
