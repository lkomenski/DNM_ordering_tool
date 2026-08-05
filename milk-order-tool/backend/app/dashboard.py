"""
Sales-trend dashboard aggregation — read-only summaries over saved history,
mode-aware. Par-mode categories (avgDailySold-shaped entries) get weekday,
month/season, and daily-trend breakdowns; reconciliation-mode categories
(Milk; totalUsed-shaped entries) get month/season/weekly-trend "usage"
rollups (the hidden café-usage signal, from real weekly entries only) *plus*
a "sold pattern" sub-object — weekday/month/season/daily-trend breakdowns
from any daily-rate-shaped data (backfilled days; see
docs/decisions/0007-backfill-milk-sold-pattern.md), the same shape par
categories get, so Milk can show a genuine day-of-week/month/season sold
pattern even though its Suggest-order math stays untouched.

This never touches Milk's suggestion math — it only reads and summarizes
what's already saved.
"""

import calendar
import datetime

from . import ml_forecasting

SEASON_BY_MONTH = {
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
    9: "Fall", 10: "Fall", 11: "Fall",
}
SEASON_ORDER = ["Winter", "Spring", "Summer", "Fall"]
WEEKDAY_NAMES = list(calendar.day_name)  # Monday..Sunday, matches date.weekday()


def _parse_date(date_str):
    y, m, d = (int(p) for p in date_str.split("-"))
    return datetime.date(y, m, d)


def _extract_records(weeks, value_field, item_filter=None):
    """weeks: db.fetch_history output. Returns [(date, item, value)] for
    whichever numeric field is present (avgDailySold for par,
    totalUsed for reconciliation), optionally restricted to one item."""
    records = []
    for week in weeks:
        date_str = week.get("weekEnding")
        if not date_str:
            continue
        try:
            date = _parse_date(date_str)
        except (ValueError, TypeError):
            continue
        for item, entry in (week.get("entries") or {}).items():
            if item_filter and item != item_filter:
                continue
            if not isinstance(entry, dict):
                continue
            value = entry.get(value_field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                records.append((date, item, float(value)))
    return records


def _daily_records(weeks, item_filter=None):
    """[(date, item, rate)] using ml_forecasting.daily_rate — the same rule
    that decides what feeds the ML model, so the dashboard's sold-pattern
    charts and the model always agree on which rows count."""
    records = []
    for week in weeks:
        date_str = week.get("weekEnding")
        if not date_str:
            continue
        try:
            date = _parse_date(date_str)
        except (ValueError, TypeError):
            continue
        for item, entry in (week.get("entries") or {}).items():
            if item_filter and item != item_filter:
                continue
            rate = ml_forecasting.daily_rate(entry)
            if rate is not None:
                records.append((date, item, rate))
    return records


def _group_avg(records, key_fn):
    buckets = {}
    for date, _item, value in records:
        buckets.setdefault(key_fn(date), []).append(value)
    return {k: {"avg": sum(v) / len(v), "n": len(v)} for k, v in buckets.items()}


def _series(records, key_fn=lambda d: d):
    """Sum values per key (default: per date), sorted by key."""
    totals = {}
    for date, _item, value in records:
        k = key_fn(date)
        totals[k] = totals.get(k, 0.0) + value
    return [{"date": k.isoformat(), "value": v} for k, v in sorted(totals.items())]


def _all_items(weeks):
    items = set()
    for week in weeks:
        items.update((week.get("entries") or {}).keys())
    return sorted(items)


def _pattern_block(records):
    """Shared weekday/month/season/trend shape, used for par_dashboard
    directly and for reconciliation_dashboard's soldPattern sub-object."""
    return {
        "byWeekday": {WEEKDAY_NAMES[k]: v for k, v in _group_avg(records, lambda d: d.weekday()).items()},
        "byMonth": {calendar.month_name[k]: v for k, v in _group_avg(records, lambda d: d.month).items()},
        "bySeason": _group_avg(records, lambda d: SEASON_BY_MONTH[d.month]),
        "dailyTrend": _series(records),
        "nRecords": len(records),
    }


def par_dashboard(weeks, item=None):
    records = _daily_records(weeks, item_filter=item)
    return {"mode": "par", "items": _all_items(weeks), **_pattern_block(records)}


def reconciliation_dashboard(weeks, item=None):
    """Milk (and any other reconciliation-mode category). Two independent
    signals: `byMonth`/`bySeason`/`weeklyTrend` are the hidden-usage rollup
    from real weekly entries (totalUsed) — untouched, as before. `soldPattern`
    is a separate weekday/month/season/trend breakdown from daily-rate-shaped
    data (i.e. backfilled days — see ml_forecasting.daily_rate), plus a
    modelAccuracy check proving the ML layer is actually learning from it.
    Real weekly entries never contribute to soldPattern (their `sold` is a
    week's total, not a daily rate — see daily_rate's docstring)."""
    usage_records = _extract_records(weeks, "totalUsed", item_filter=item)
    by_month = {calendar.month_name[k]: v for k, v in _group_avg(usage_records, lambda d: d.month).items()}
    by_season = _group_avg(usage_records, lambda d: SEASON_BY_MONTH[d.month])

    sold_records = _daily_records(weeks, item_filter=item)
    sold_pattern = _pattern_block(sold_records)
    sold_pattern["modelAccuracy"] = (
        ml_forecasting.validate(ml_forecasting.frame_from_records(sold_records)) if sold_records else None
    )

    return {
        "mode": "reconciliation",
        "items": _all_items(weeks),
        "byMonth": by_month,
        "bySeason": by_season,
        "weeklyTrend": _series(usage_records),
        "nRecords": len(usage_records),
        "soldPattern": sold_pattern,
    }


def dashboard_for_category(weeks, is_reconciliation, item=None):
    if is_reconciliation:
        return reconciliation_dashboard(weeks, item=item)
    return par_dashboard(weeks, item=item)
