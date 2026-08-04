from scripts.backfill_import import normalize_date, parse_wide_product_mix


def make_rows():
    date_row = ["", "", "", "", "", "", "", "Mon 08/03/2026", "", "Tue 08/04/2026", ""]
    label_row = ["Class", "Name", "", "", "", "", "", "Quantity", "Total", "Quantity", "Total"]
    data_rows = [
        ["Memoranda", "Brisket Melt", "", "", "", "", "", "3", "21.00", "5", "35.00"],
        ["Smith Brothers Farms", "Whole Milk", "", "", "", "", "", "10", "40.00", "12", "48.00"],
    ]
    return [date_row, label_row] + data_rows


def test_parse_splits_by_class_and_date():
    by_date = parse_wide_product_mix(make_rows())
    assert set(by_date.keys()) == {"Mon 08/03/2026", "Tue 08/04/2026"}
    assert by_date["Mon 08/03/2026"]["Memoranda"]["Brisket Melt"] == 3
    assert by_date["Tue 08/04/2026"]["Memoranda"]["Brisket Melt"] == 5
    assert by_date["Mon 08/03/2026"]["Smith Brothers Farms"]["Whole Milk"] == 10


def test_parse_skips_rows_without_class_or_name():
    rows = make_rows()
    rows.append(["", "Mystery Item", "", "", "", "", "", "1", "5.00", "1", "5.00"])
    by_date = parse_wide_product_mix(rows)
    for by_class in by_date.values():
        for items in by_class.values():
            assert "Mystery Item" not in items


def test_normalize_date():
    assert normalize_date("Mon 08/03/2026") == "2026-08-03"
    assert normalize_date("08/03/2026") == "2026-08-03"
