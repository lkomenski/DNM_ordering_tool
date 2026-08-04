import datetime

from app import ml_forecasting as mf


def make_weeks(start, n_days, rate_fn, item="Croissant"):
    """Build synthetic history rows: n_days consecutive days starting at
    `start` (a date), avgDailySold given by rate_fn(date)."""
    weeks = []
    for i in range(n_days):
        d = start + datetime.timedelta(days=i)
        weeks.append({
            "weekEnding": d.isoformat(),
            "entries": {item: {"avgDailySold": rate_fn(d)}},
        })
    return weeks


def saturday_heavy_rate(d):
    # Saturday (weekday() == 5) sells much more than the rest of the week.
    return 20.0 if d.weekday() == 5 else 8.0


def test_build_training_frame_extracts_numeric_rates_only():
    weeks = [
        {"weekEnding": "2026-08-01", "entries": {"A": {"avgDailySold": 5}, "B": {"totalUsed": 10}}},
        {"weekEnding": "2026-08-02", "entries": {"A": {"avgDailySold": None}}},
        {"weekEnding": "not-a-date", "entries": {"A": {"avgDailySold": 5}}},
    ]
    df = mf.build_training_frame(weeks)
    assert len(df) == 1
    assert df.iloc[0]["item"] == "A"
    assert df.iloc[0]["rate"] == 5.0


def test_build_training_frame_empty_input():
    df = mf.build_training_frame([])
    assert df.empty


def test_train_model_none_below_threshold():
    start = datetime.date(2026, 1, 1)
    weeks = make_weeks(start, mf.MIN_ROWS_TO_TRAIN - 1, saturday_heavy_rate)
    df = mf.build_training_frame(weeks)
    assert mf.train_model(df) is None


def test_train_model_trains_above_threshold():
    start = datetime.date(2026, 1, 1)
    weeks = make_weeks(start, mf.MIN_ROWS_TO_TRAIN + 5, saturday_heavy_rate)
    df = mf.build_training_frame(weeks)
    trained = mf.train_model(df)
    assert trained is not None


def test_forecast_cold_start_falls_back_to_average():
    start = datetime.date(2026, 1, 1)
    weeks = make_weeks(start, 5, saturday_heavy_rate)  # well under MIN_ROWS_TO_TRAIN
    target = start + datetime.timedelta(days=30)
    result = mf.forecast_category(weeks, target.isoformat())
    assert "Not enough history" in result["items"]["Croissant"]["reasoning"]
    assert result["modelAccuracy"] is None


def test_forecast_with_enough_data_beats_naive_average_on_a_saturday():
    start = datetime.date(2026, 1, 1)  # a Thursday
    weeks = make_weeks(start, 140, saturday_heavy_rate)  # ~20 weeks of daily data

    # find a Saturday well within (not at the edge of) the training window
    target = start + datetime.timedelta(days=100)
    while target.weekday() != 5:
        target += datetime.timedelta(days=1)

    result = mf.forecast_category(weeks, target.isoformat())
    estimate = result["items"]["Croissant"]["estimate"]

    naive_average = (20.0 + 8.0 * 6) / 7  # ~9.7 — a flat average ignores the Saturday spike entirely
    assert abs(estimate - 20.0) < abs(naive_average - 20.0)
    assert abs(estimate - 20.0) < 3.0  # model should land close to the true Saturday rate
    assert "Saturday" in result["items"]["Croissant"]["reasoning"]


def test_more_data_improves_accuracy_on_a_thin_but_real_pattern():
    """The core 'gets smarter over time' claim: with too little data the
    system honestly falls back to a pattern-blind average; once enough
    accumulates, it recovers the day-of-week pattern specifically."""
    start = datetime.date(2026, 1, 1)
    target = start + datetime.timedelta(days=100)
    while target.weekday() != 5:
        target += datetime.timedelta(days=1)

    thin_weeks = make_weeks(start, 10, saturday_heavy_rate)  # cold start
    thin_result = mf.forecast_category(thin_weeks, target.isoformat())
    thin_estimate = thin_result["items"]["Croissant"]["estimate"]

    rich_weeks = make_weeks(start, 140, saturday_heavy_rate)
    rich_result = mf.forecast_category(rich_weeks, target.isoformat())
    rich_estimate = rich_result["items"]["Croissant"]["estimate"]

    assert abs(rich_estimate - 20.0) < abs(thin_estimate - 20.0)


def test_validate_model_beats_naive_baseline_on_strong_signal():
    start = datetime.date(2026, 1, 1)
    weeks = make_weeks(start, 140, saturday_heavy_rate)
    df = mf.build_training_frame(weeks)
    result = mf.validate(df)
    assert result is not None
    assert result["mae"] < result["naiveMae"]
    assert result["improvementOverNaive"] > 0


def test_validate_none_when_too_little_data():
    start = datetime.date(2026, 1, 1)
    weeks = make_weeks(start, mf.MIN_ROWS_TO_TRAIN, saturday_heavy_rate)
    df = mf.build_training_frame(weeks)
    assert mf.validate(df) is None


def test_forecast_differentiates_between_items_with_different_patterns():
    """The core 'per-item matters' guarantee: pooling items into one model
    per category must not blur them together. Two items with opposite
    weekday peaks, forecast for the same date, must get different,
    pattern-correct estimates — not the same category-wide blend."""
    start = datetime.date(2026, 1, 1)
    weeks = []
    for i in range(140):
        d = start + datetime.timedelta(days=i)
        weeks.append({
            "weekEnding": d.isoformat(),
            "entries": {
                "Croissant": {"avgDailySold": 20.0 if d.weekday() == 5 else 8.0},  # peaks Saturday
                "Bagel": {"avgDailySold": 15.0 if d.weekday() == 0 else 5.0},       # peaks Monday
            },
        })

    target = start + datetime.timedelta(days=100)
    while target.weekday() != 5:  # a Saturday
        target += datetime.timedelta(days=1)

    result = mf.forecast_category(weeks, target.isoformat())
    croissant_estimate = result["items"]["Croissant"]["estimate"]
    bagel_estimate = result["items"]["Bagel"]["estimate"]

    assert abs(croissant_estimate - 20.0) < 3.0  # Croissant: Saturday is its peak
    assert abs(bagel_estimate - 5.0) < 3.0        # Bagel: Saturday is NOT its peak (Monday is)
    assert croissant_estimate > bagel_estimate + 5  # must not collapse to one shared category rate


def test_predict_never_negative():
    start = datetime.date(2026, 1, 1)
    weeks = make_weeks(start, 30, lambda d: 0.0)  # an item that never sells
    df = mf.build_training_frame(weeks)
    trained = mf.train_model(df)
    assert trained is not None
    preds = mf.predict(trained, start + datetime.timedelta(days=60), ["Croissant"])
    assert preds["Croissant"] >= 0.0
