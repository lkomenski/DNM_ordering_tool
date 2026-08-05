# Future ideas (discussed, not built)

Not scoped into the current build — logged here so the reasoning isn't lost
before they're picked up later.

## Weather as a forecast feature

Owner's sense is a lot of sales are directly weather-driven, more than just
seasonal. `backend/ml_forecasting.py`'s `FEATURE_COLUMNS` list was
deliberately kept flat for this reason — adding a weather signal is a
feature-engineering change, not a model-architecture change:

1. **Training-time data**: pull a year of *historical* daily weather
   (temperature, precipitation, maybe a condition category) for the café's
   location from a historical weather API (e.g. Open-Meteo's historical
   endpoint is free and needs no API key), keyed by date, and join it into
   `build_training_frame()`'s output alongside the existing calendar
   features.
2. **Prediction-time data**: forecasting *today's* suggested order needs a
   weather *forecast* for the target date, not historical weather — a
   different API call, with its own uncertainty (a temperature forecast for
   tomorrow is much more reliable than one for two weeks out). This is the
   part that adds real complexity — the model would effectively be trained
   on ground-truth weather but predicting from a forecast, which is a
   legitimate but nontrivial ML pattern (feature drift between train and
   serve time) worth being deliberate about, not just bolting on.
3. Numeric weather features (temperature, precipitation amount) would join
   `FEATURE_COLUMNS` and pass through the `ColumnTransformer`'s numeric
   passthrough; a categorical condition (sunny/rainy/snowy) would join
   `CATEGORICAL_COLUMNS` and get one-hot encoded like `day_of_week`/`month`.
4. Estimated effort: the model change itself is small (a few new columns);
   the real work is data plumbing — fetching and storing a year of
   historical weather once, then a forecast lookup at prediction time going
   forward, plus deciding where that data lives (a new small table, most
   likely, rather than cramming it into the existing `entries` JSON blob).

Explicitly out of scope for now per the original ask ("not weather data,
not external signals of any kind") — logged here because the owner
confirmed this is a near-term next step they're already thinking about.

## Hour-of-day sales data

The owner has access to a Revel export aggregating sales by hour by day
across a full year, filterable to Sandwiches — a genuinely different report
from the "Product Mix Daily" export this tool currently imports (which has
no intraday granularity, which is why time-of-day was ruled out of the
initial ML feature set in ADR 0004). This reopens that dimension as a real
possibility:

- Would need a new import path (a new parser, since the file shape is
  different from the wide day-column Product Mix format).
- Most useful for the **dashboard** (an hour-of-day trend chart) and as a
  richer training signal (an `hour` feature) if the tool ever moves from
  once-a-day PAR suggestions to intraday reordering — today's PAR ordering
  is fundamentally a once-a-day decision (on-hand vs. expected sell-through
  until the next delivery), so hour-of-day data mostly enriches
  understanding rather than changing the suggested-order math, unless the
  ordering cadence itself changes.

## Labor/scheduling comparison

Longer-term idea: compare how busy a given day/hour was (from sales volume)
against labor cost, to inform scheduling. Explicitly a "someday, not now"
item — no design work done yet. Would likely want the hour-of-day data above
as a prerequisite, plus a labor-cost data source that doesn't exist in this
tool today.
