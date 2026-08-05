"""
One-time backfill importer for the Order Reconciliation Tool.

Reads a wide-format Product Mix Daily export (same shape as the tool's
regular uploads — one Quantity/Total column pair per day — just spanning
many days instead of 6-7) and creates ONE saved history entry per day per
item, not one blended average. That gives the tool real day-by-day history
to compute day-of-week/month/season-aware suggestions from.

Category and vendor are both read straight from the file's Class column —
there's no manual item/keyword list to keep in sync here. Each distinct
Class value becomes its own category, with that same string as the vendor
for every item under it (see docs/decisions/0003-auto-detect-items-and-categories.md).

Usage:
    python scripts/backfill_import.py path/to/year_export.csv \
        --api https://your-backend.up.railway.app \
        --dry-run          # preview first, without posting anything

Then drop --dry-run to actually post. Optionally pass --only-category to
restrict the import to a single Class value (case-insensitive) if your file
has multiple product lines mixed together and you only want one for now.

Notes:
- Historical on-hand counts aren't knowable retroactively, so `onHand` is
  saved as null for backfilled days. The tool only uses onHand for TODAY's
  suggested order, not for computing historical daily-sold averages, so
  this is safe — it just means backfilled days won't show an on-hand
  number in the history table (shown as "—" instead).
- Damage/waste data is NOT backfilled here — only tested against a single
  week's Inventory Log so far. Damage tracking starts from whenever you
  begin uploading Inventory Log exports going forward.
- Reconciliation-mode categories (see RECONCILIATION_CLASSES, e.g. Milk) ARE
  backfilled, but only with `sold` (POS quantity) — never `beginning`,
  `ordered`, `endingCount`, `gap`, or `totalUsed`, since those need a real
  physical count each week that can't be reconstructed after the fact. This
  can't feed the Suggest-order number (that only ever reads `totalUsed`,
  which these rows deliberately don't have), but it does feed the ML
  pattern-learning and dashboard views — see
  docs/decisions/0007-backfill-milk-sold-pattern.md.
- Some products get rung up under a tracked Class by mistake (e.g. a grocery
  item sharing a department with milk) and aren't actually something this
  tool should track — see EXCLUDED_ITEMS below.
- Some products are the same real item sold under different vendor/brand
  names over time (e.g. a distributor switch) — see ITEM_ALIASES below,
  which merges them into one canonical item so pattern learning sees one
  continuous series instead of two fragments.
- Some products have a stretch of historical export data that's known to be
  unreliable (e.g. a POS reporting gap) rather than genuinely zero sales —
  see BACKFILL_SKIP_ITEMS below, which skips them for backfill only; regular
  going-forward uploads through the app are unaffected.
"""

import argparse
import csv
import datetime
import sys
import time
from pathlib import Path

import requests

# Mirrors RECONCILIATION_CLASSES in index.html — the one Class value that
# needs Beginning+Ordered-Sold-Ending reconciliation math instead of plain
# par (sell-through) ordering. Keep these two in sync by hand if it ever
# changes; see docs/decisions/0003-auto-detect-items-and-categories.md.
RECONCILIATION_CLASSES = {"Smith Brothers Farms"}

# Products that show up under a tracked Class by mistake in Revel but aren't
# actually part of this tool's ordering (e.g. a grocery item rung up under
# the same department as milk). Mirrors EXCLUDED_ITEMS in index.html — a
# hardcoded exception since "this doesn't belong here" is operational
# knowledge, not something inferable from the data. Matched case-insensitively.
EXCLUDED_ITEMS = {
    "Beechers Worlds Best Mac + Cheese 20oz",
    "Simply Organic Mild Taco 1.13oz",
    "Simply Organic Spicy Taco 1.13oz",
}
_EXCLUDED_ITEMS_LOWER = {s.lower() for s in EXCLUDED_ITEMS}

# Product names that refer to the same underlying item under a different
# vendor/brand label (e.g. a distributor switch) — merged into one canonical
# item so the ML model and dashboard see one continuous series instead of
# two artificially fragmented ones. Mirrors ITEM_ALIASES in index.html — keep
# both in sync. Matched case-insensitively; see
# docs/decisions/0008-item-name-aliasing.md.
ITEM_ALIASES = {
    "alpenrose 2% milk - gallon": "2% Milk (Gallon)",
    "smith brothers 2% milk - gallon": "2% Milk (Gallon)",
    "alpenrose chocolate reduced fat 2% milk - pint": "Chocolate 2% Milk (Pint)",
    "smith brothers chocolate 2% milk - pint": "Chocolate 2% Milk (Pint)",
}


def canonical_item_name(raw_name: str) -> str:
    return ITEM_ALIASES.get(raw_name.lower(), raw_name)


# Items whose historical export data is known to be unreliable — e.g. a POS
# reporting gap that left an otherwise continuously-sold staple showing
# essentially no recorded sales for an untraceable stretch of the past (a
# real zero-sales day is implausible for these, so the data itself, not the
# item, is what's untrusted). Skipped during BACKFILL ONLY — not mirrored to
# index.html, since regular going-forward uploads aren't affected by a
# historical export gap and shouldn't be blocked from tracking these items
# once (if) their live reporting is trustworthy again. Matched
# case-insensitively; see docs/decisions/0007-backfill-milk-sold-pattern.md.
BACKFILL_SKIP_ITEMS = {
    "Smith Brothers Whole Milk - Gallon",
    "Smith Brothers 2% Milk - Gallon",
}
_BACKFILL_SKIP_ITEMS_LOWER = {s.lower() for s in BACKFILL_SKIP_ITEMS}


def parse_wide_product_mix(rows):
    """
    rows: list of lists (raw CSV cells), same shape the browser tool expects:
      row[0]: sparse date headers, one label sitting above each day's pair of columns
      row[1]: 'Class','Name',...,'Quantity','Total','Quantity','Total',...
      row[2:]: data rows, each with a Class (col 0) and Name (col 1)

    Returns: { date_label: { class_name: { item_name: total_qty_that_day } } }
    """
    date_row = rows[0]
    label_row = rows[1]
    data_rows = [r for r in rows[2:] if len(r) > 1 and r[1]]

    start_col = None
    for i, c in enumerate(label_row):
        if c and c.strip() == "Quantity":
            start_col = i
            break
    if start_col is None:
        start_col = 7

    # Forward-fill the sparse date header across each Quantity/Total pair
    date_for_col = {}
    last_date = None
    for c in range(start_col, len(label_row)):
        if c < len(date_row) and date_row[c]:
            last_date = date_row[c]
        if (c - start_col) % 2 == 0:  # Quantity columns only, Total is c+1
            date_for_col[c] = last_date

    by_date = {}
    skipped_rows = 0
    skipped_excluded = 0
    skipped_unreliable = 0
    for row in data_rows:
        class_name = (row[0] or "").strip() if len(row) > 0 else ""
        item_name = (row[1] or "").strip() if len(row) > 1 else ""
        if not class_name or not item_name:
            skipped_rows += 1
            continue
        if item_name.lower() in _EXCLUDED_ITEMS_LOWER:
            skipped_excluded += 1
            continue
        if item_name.lower() in _BACKFILL_SKIP_ITEMS_LOWER:
            skipped_unreliable += 1
            continue
        item_name = canonical_item_name(item_name)
        for c in range(start_col, len(row), 2):
            date_label = date_for_col.get(c)
            if not date_label:
                continue
            qty_raw = row[c] if c < len(row) else ""
            try:
                qty = float(qty_raw)
            except (TypeError, ValueError):
                continue
            by_class = by_date.setdefault(date_label, {})
            by_item = by_class.setdefault(class_name, {})
            by_item[item_name] = by_item.get(item_name, 0) + qty

    if skipped_rows:
        print(f"Note: {skipped_rows} row(s) had no Class or Name and were skipped.")
    if skipped_unreliable:
        print(f"Note: {skipped_unreliable} row(s) matched BACKFILL_SKIP_ITEMS (unreliable historical data) and were skipped.")
    if skipped_excluded:
        print(f"Note: {skipped_excluded} row(s) matched EXCLUDED_ITEMS and were skipped.")

    return by_date


def normalize_date(date_label: str) -> str:
    """Convert a header like 'Wed 07/29/2026' into 'YYYY-MM-DD'."""
    parts = date_label.split()
    date_part = parts[-1]
    dt = datetime.datetime.strptime(date_part, "%m/%d/%Y")
    return dt.strftime("%Y-%m-%d")


def chronological_sort_key(date_label: str) -> str:
    """Sorting by the raw label (e.g. "Wed 07/29/2026") sorts by weekday
    name first, not date — a full year of daily labels would group into
    weekday-name buckets instead of a real timeline. This sorts by the
    actual calendar date instead, so dry-run output (and posting order)
    reads chronologically. Unparseable labels are skipped by the caller
    anyway, so falling back to the raw string here is harmless."""
    try:
        return normalize_date(date_label)
    except Exception:
        return date_label


def main():
    parser = argparse.ArgumentParser(description="Backfill a Product Mix export into saved history, auto-split by Class.")
    parser.add_argument("file", help="Path to the wide-format Product Mix CSV")
    parser.add_argument("--api", required=True, help="Backend base URL, e.g. https://your-app.up.railway.app")
    parser.add_argument("--only-category", default=None, help="Only import this Class value (case-insensitive); default imports every category found")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be sent, without posting")
    args = parser.parse_args()

    path = Path(args.file)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    by_date = parse_wide_product_mix(rows)
    if not by_date:
        print("No data found — check the file format (expects a Class column before Name, and Quantity/Total column pairs).", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(by_date)} day(s) of data.")
    posted = 0
    failed = 0
    posted_reconciliation = set()
    skipped_filtered = set()

    for date_label, by_class in sorted(by_date.items(), key=lambda kv: chronological_sort_key(kv[0])):
        try:
            date_iso = normalize_date(date_label)
        except Exception as e:
            print(f"Skipping unparseable date '{date_label}': {e}")
            continue

        for class_name, items in by_class.items():
            if args.only_category and class_name.lower() != args.only_category.lower():
                skipped_filtered.add(class_name)
                continue

            is_reconciliation = class_name in RECONCILIATION_CLASSES
            entries = {}
            for item_name, qty in items.items():
                if is_reconciliation:
                    # Only `sold` is knowable retroactively — no beginning/ordered/
                    # endingCount/gap/totalUsed, so this can never feed the
                    # Suggest-order number, only the ML/dashboard sold pattern.
                    entries[item_name] = {"vendor": class_name, "sold": qty}
                else:
                    entries[item_name] = {
                        "vendor": class_name,
                        "onHand": None,        # unknowable retroactively; only used for today's suggestion
                        "soldInFile": qty,
                        "damaged": 0,           # not backfilled — see module docstring
                        "daysInFile": 1,        # this entry represents a single day
                        "avgDailySold": qty,    # qty over 1 day = that day's rate
                        "suggestedOrder": None,
                    }

            if is_reconciliation:
                posted_reconciliation.add(class_name)

            payload = {"category": class_name, "entryDate": date_iso, "entries": entries}

            if args.dry_run:
                print(f"[dry-run] {class_name} / {date_iso}: {len(entries)} item(s), e.g. {list(entries.items())[:1]}")
                continue

            try:
                resp = requests.post(f"{args.api}/api/history", json=payload, timeout=15)
                if resp.ok:
                    posted += 1
                else:
                    failed += 1
                    print(f"Failed for {class_name} / {date_iso}: {resp.status_code} {resp.text}")
            except requests.RequestException as e:
                failed += 1
                print(f"Request error for {class_name} / {date_iso}: {e}")

            time.sleep(0.05)  # be gentle with a free-tier backend

    if posted_reconciliation:
        print(f"Reconciliation-mode categor{'y' if len(posted_reconciliation) == 1 else 'ies'} included with `sold` only, no Suggest-order impact (see module docstring): {sorted(posted_reconciliation)}")
    if skipped_filtered:
        print(f"Skipped categories not matching --only-category={args.only_category!r}: {sorted(skipped_filtered)}")

    if args.dry_run:
        print("Dry run complete — nothing was posted. Drop --dry-run to actually import.")
    else:
        print(f"Done. Posted {posted} day(s), {failed} failure(s).")


if __name__ == "__main__":
    main()
