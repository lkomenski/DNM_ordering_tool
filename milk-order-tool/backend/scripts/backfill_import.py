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
- Reconciliation-mode categories (see RECONCILIATION_CLASSES) are skipped
  entirely — that math needs a real physical beginning/ending count each
  week, which can't be reconstructed from a sales export after the fact.
"""

import argparse
import csv
import datetime
import sys
import time
from pathlib import Path

import requests

# Mirrors RECONCILIATION_CLASSES in frontend/index.html — the one Class
# value that needs Beginning+Ordered-Sold-Ending reconciliation math instead
# of plain par (sell-through) ordering. Keep these two in sync by hand if it
# ever changes; see docs/decisions/0003-auto-detect-items-and-categories.md.
RECONCILIATION_CLASSES = {"Smith Brothers Farms"}


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
    for row in data_rows:
        class_name = (row[0] or "").strip() if len(row) > 0 else ""
        item_name = (row[1] or "").strip() if len(row) > 1 else ""
        if not class_name or not item_name:
            skipped_rows += 1
            continue
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

    return by_date


def normalize_date(date_label: str) -> str:
    """Convert a header like 'Wed 07/29/2026' into 'YYYY-MM-DD'."""
    parts = date_label.split()
    date_part = parts[-1]
    dt = datetime.datetime.strptime(date_part, "%m/%d/%Y")
    return dt.strftime("%Y-%m-%d")


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
    skipped_reconciliation = set()
    skipped_filtered = set()

    for date_label, by_class in sorted(by_date.items(), key=lambda kv: kv[0]):
        try:
            date_iso = normalize_date(date_label)
        except Exception as e:
            print(f"Skipping unparseable date '{date_label}': {e}")
            continue

        for class_name, items in by_class.items():
            if class_name in RECONCILIATION_CLASSES:
                skipped_reconciliation.add(class_name)
                continue
            if args.only_category and class_name.lower() != args.only_category.lower():
                skipped_filtered.add(class_name)
                continue

            entries = {}
            for item_name, qty in items.items():
                entries[item_name] = {
                    "vendor": class_name,
                    "onHand": None,        # unknowable retroactively; only used for today's suggestion
                    "soldInFile": qty,
                    "damaged": 0,           # not backfilled — see module docstring
                    "daysInFile": 1,        # this entry represents a single day
                    "avgDailySold": qty,    # qty over 1 day = that day's rate
                    "suggestedOrder": None,
                }

            payload = {"category": class_name, "weekEnding": date_iso, "entries": entries}

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

    if skipped_reconciliation:
        print(f"Skipped reconciliation-mode categor{'y' if len(skipped_reconciliation) == 1 else 'ies'} (needs real physical counts, not backfillable): {sorted(skipped_reconciliation)}")
    if skipped_filtered:
        print(f"Skipped categories not matching --only-category={args.only_category!r}: {sorted(skipped_filtered)}")

    if args.dry_run:
        print("Dry run complete — nothing was posted. Drop --dry-run to actually import.")
    else:
        print(f"Done. Posted {posted} day(s), {failed} failure(s).")


if __name__ == "__main__":
    main()
