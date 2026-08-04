from scripts.backfill_import import (
    BACKFILL_SKIP_ITEMS,
    EXCLUDED_ITEMS,
    ITEM_ALIASES,
    RECONCILIATION_CLASSES,
    canonical_item_name,
    chronological_sort_key,
    normalize_date,
    parse_wide_product_mix,
)


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


def test_chronological_sort_key_orders_by_calendar_date_not_weekday_name():
    # Naively sorting the raw labels alphabetically would put "Mon" before
    # "Sat" before "Wed" regardless of actual date — this must not happen.
    labels = ["Wed 01/07/2026", "Sat 01/03/2026", "Mon 01/05/2026"]
    ordered = sorted(labels, key=chronological_sort_key)
    assert ordered == ["Sat 01/03/2026", "Mon 01/05/2026", "Wed 01/07/2026"]


def test_chronological_sort_key_falls_back_to_raw_string_when_unparseable():
    assert chronological_sort_key("not a date") == "not a date"


def test_parse_excludes_junk_items_case_insensitively():
    rows = make_rows()
    excluded_name = next(iter(EXCLUDED_ITEMS))
    rows.append(["Smith Brothers Farms", excluded_name.upper(), "", "", "", "", "", "2", "10.00", "2", "10.00"])
    by_date = parse_wide_product_mix(rows)
    for by_class in by_date.values():
        for items in by_class.values():
            assert excluded_name not in items
            assert excluded_name.upper() not in items


def test_milk_class_is_reconciliation():
    # Sanity check that the fixture's milk row actually maps to a
    # reconciliation-mode class, since that's what main() branches on.
    assert "Smith Brothers Farms" in RECONCILIATION_CLASSES


def test_canonical_item_name_merges_aliases_case_insensitively():
    assert canonical_item_name("Alpenrose 2% Milk - Gallon") == "2% Milk (Gallon)"
    assert canonical_item_name("SMITH BROTHERS 2% MILK - GALLON") == "2% Milk (Gallon)"
    assert canonical_item_name("Something Unrelated") == "Something Unrelated"


def test_parse_merges_aliased_items_into_one_canonical_series():
    # "Smith Brothers 2% Milk - Gallon" is ALSO in BACKFILL_SKIP_ITEMS (its
    # historical data is known-unreliable), so only the Alpenrose-branded
    # rows should actually reach the canonical "2% Milk (Gallon)" series —
    # skip takes precedence over aliasing. Two Alpenrose-only aliases here
    # (a fabricated second brand name for the same product) to prove
    # multiple *different* raw names really do collapse into one key.
    rows = make_rows()
    rows.append(["Smith Brothers Farms", "Alpenrose 2% Milk - Gallon", "", "", "", "", "", "4", "20.00", "6", "30.00"])
    rows.append(["Smith Brothers Farms", "Smith Brothers 2% Milk - Gallon", "", "", "", "", "", "3", "15.00", "0", "0.00"])
    by_date = parse_wide_product_mix(rows)
    # only the Alpenrose row counts — the Smith Brothers row was skipped as unreliable
    assert by_date["Mon 08/03/2026"]["Smith Brothers Farms"]["2% Milk (Gallon)"] == 4.0
    assert by_date["Tue 08/04/2026"]["Smith Brothers Farms"]["2% Milk (Gallon)"] == 6.0
    assert "Alpenrose 2% Milk - Gallon" not in by_date["Mon 08/03/2026"]["Smith Brothers Farms"]
    assert "Smith Brothers 2% Milk - Gallon" not in by_date["Mon 08/03/2026"]["Smith Brothers Farms"]


def test_parse_merges_two_distinct_aliases_when_neither_is_skipped():
    # A case where aliasing genuinely combines two different raw names that
    # AREN'T also in BACKFILL_SKIP_ITEMS (e.g. the chocolate pint pair).
    rows = make_rows()
    rows.append(["Smith Brothers Farms", "Alpenrose Chocolate Reduced Fat 2% Milk - Pint", "", "", "", "", "", "5", "10.00", "0", "0.00"])
    rows.append(["Smith Brothers Farms", "Smith Brothers Chocolate 2% Milk - Pint", "", "", "", "", "", "2", "4.00", "0", "0.00"])
    by_date = parse_wide_product_mix(rows)
    assert by_date["Mon 08/03/2026"]["Smith Brothers Farms"]["Chocolate 2% Milk (Pint)"] == 7.0


def test_parse_skips_backfill_unreliable_items():
    rows = make_rows()
    skip_name = next(iter(BACKFILL_SKIP_ITEMS))
    rows.append(["Smith Brothers Farms", skip_name, "", "", "", "", "", "1", "5.00", "1", "5.00"])
    by_date = parse_wide_product_mix(rows)
    for by_class in by_date.values():
        for items in by_class.values():
            assert skip_name not in items


def test_backfill_skip_items_are_not_also_silently_aliased():
    # These items are skipped by name, before any alias lookup would apply —
    # make sure that ordering assumption actually holds for the real pairs.
    for skip_name in BACKFILL_SKIP_ITEMS:
        if skip_name.lower() in ITEM_ALIASES:
            rows = make_rows()
            rows.append(["Smith Brothers Farms", skip_name, "", "", "", "", "", "1", "5.00", "1", "5.00"])
            by_date = parse_wide_product_mix(rows)
            canonical = ITEM_ALIASES[skip_name.lower()]
            for by_class in by_date.values():
                assert canonical not in by_class.get("Smith Brothers Farms", {})
