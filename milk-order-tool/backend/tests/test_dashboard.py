from app import dashboard


def par_weeks():
    return [
        {"weekEnding": "2026-08-01", "entries": {"Croissant": {"avgDailySold": 10.0}, "Bagel": {"avgDailySold": 4.0}}},  # Saturday
        {"weekEnding": "2026-08-02", "entries": {"Croissant": {"avgDailySold": 3.0}}},  # Sunday
        {"weekEnding": "2026-08-08", "entries": {"Croissant": {"avgDailySold": 12.0}}},  # Saturday
        {"weekEnding": "2026-02-07", "entries": {"Croissant": {"avgDailySold": 6.0}}},  # Saturday, different month
    ]


def reconciliation_weeks():
    return [
        {"weekEnding": "2026-08-01", "entries": {"Whole Milk": {"totalUsed": 20.0}}},
        {"weekEnding": "2026-08-08", "entries": {"Whole Milk": {"totalUsed": 24.0}}},
        {"weekEnding": "2026-02-01", "entries": {"Whole Milk": {"totalUsed": 18.0}}},
    ]


def test_par_dashboard_by_weekday():
    result = dashboard.par_dashboard(par_weeks())
    assert result["mode"] == "par"
    assert set(result["items"]) == {"Croissant", "Bagel"}
    # Saturday records: Croissant+Bagel on 08-01, Croissant on 08-08 and 02-07
    saturday = result["byWeekday"]["Saturday"]
    assert saturday["n"] == 4
    assert saturday["avg"] == (10.0 + 4.0 + 12.0 + 6.0) / 4
    assert result["byWeekday"]["Sunday"]["n"] == 1


def test_par_dashboard_by_month_and_season():
    result = dashboard.par_dashboard(par_weeks())
    assert result["byMonth"]["August"]["n"] == 4  # Croissant+Bagel(08-01), Croissant(08-02, 08-08)
    assert result["byMonth"]["February"]["n"] == 1
    assert result["bySeason"]["Summer"]["n"] == 4
    assert result["bySeason"]["Winter"]["n"] == 1


def test_par_dashboard_daily_trend_sums_all_items_per_day():
    result = dashboard.par_dashboard(par_weeks())
    trend = {p["date"]: p["value"] for p in result["dailyTrend"]}
    assert trend["2026-08-01"] == 14.0  # Croissant + Bagel
    assert trend["2026-08-02"] == 3.0


def test_par_dashboard_item_filter():
    result = dashboard.par_dashboard(par_weeks(), item="Bagel")
    assert result["nRecords"] == 1
    assert result["byWeekday"]["Saturday"]["n"] == 1


def test_reconciliation_dashboard_has_no_weekday_breakdown():
    result = dashboard.reconciliation_dashboard(reconciliation_weeks())
    assert result["mode"] == "reconciliation"
    assert "byWeekday" not in result
    assert result["byMonth"]["August"]["avg"] == 22.0
    assert result["bySeason"]["Winter"]["n"] == 1


def test_dashboard_for_category_dispatches_on_mode():
    par_result = dashboard.dashboard_for_category(par_weeks(), is_reconciliation=False)
    assert par_result["mode"] == "par"
    recon_result = dashboard.dashboard_for_category(reconciliation_weeks(), is_reconciliation=True)
    assert recon_result["mode"] == "reconciliation"


def test_empty_history_returns_empty_aggregates():
    result = dashboard.par_dashboard([])
    assert result["items"] == []
    assert result["byWeekday"] == {}
    assert result["dailyTrend"] == []
    assert result["nRecords"] == 0
