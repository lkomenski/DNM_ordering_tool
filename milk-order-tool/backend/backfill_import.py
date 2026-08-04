"""
One-time backfill importer for the Order Reconciliation Tool.

Reads a wide-format Product Mix Daily export (same shape as the tool's
regular uploads — one Quantity/Total column pair per day — just spanning
many days instead of 6-7) and creates ONE saved history entry per day per
matched item, not one blended average. That gives the tool real day-by-day
history to compute day-of-week-aware suggestions from.

Usage:
    python backfill_import.py path/to/year_export.csv \
        --api https://your-backend.up.railway.app \
        --category Sandwiches \
        --dry-run          # preview first, without posting anything

Then drop --dry-run to actually post.

Notes:
- Historical on-hand counts aren't knowable retroactively, so `onHand` is
  saved as null for backfilled days. The tool only uses onHand for TODAY's
  suggested order, not for computing historical daily-sold averages, so
  this is safe — it just means backfilled days won't show an on-hand
  number in the history table (shown as "—" instead).
- Damage/waste data is NOT backfilled here — only tested against a single
  week's Inventory Log so far. Damage tracking starts from whenever you
  begin uploading Inventory Log exports going forward.
- The item list mirrors the "Sandwiches" section of DEFAULT_CONFIG in
  frontend/index.html. If you add, rename, or remove items there, update
  ITEM_TYPES below too, or this script will silently skip anything it
  doesn't recognize (same "check the matched count" caution as the
  browser tool).
"""

import argparse
import csv
import datetime
import sys
import time
from pathlib import Path

import requests

# Keep in sync with the "Sandwiches" list in frontend/index.html DEFAULT_CONFIG
ITEM_TYPES = [
    {"label": "Bacon Breakfast Wrap", "vendor": "Memoranda", "keywords": ["bacon breakfast wrap"]},
    {"label": "Belgian Waffle Sandwich", "vendor": "Memoranda", "keywords": ["belgian waffle sandwich"]},
    {"label": "Black Bean Chipotle Wrap", "vendor": "Memoranda", "keywords": ["black bean chipotle wrap"]},
    {"label": "Brisket Melt", "vendor": "Memoranda", "keywords": ["brisket melt"]},
    {"label": "Brown Sugar Bacon Melt", "vendor": "Memoranda", "keywords": ["brown sugar bacon melt"]},
    {"label": "Chipotle Chicken Bacon", "vendor": "Memoranda", "keywords": ["chipotle chicken bacon"]},
    {"label": "GF Bacon Breakfast Sandwich", "vendor": "Memoranda", "keywords": ["gf bacon breakfast sandwich"]},
    {"label": "GF Turkey & Havarti", "vendor": "Memoranda", "keywords": ["gf turkey & havarti", "gf turkey and havarti"]},
    {"label": "Ham & Swiss Croissant", "vendor": "Memoranda", "keywords": ["ham & swiss croissant", "ham and swiss croissant"]},
    {"label": "Jalapeno Bacon Breakfast Wrap", "vendor": "Memoranda", "keywords": ["jalapeno bacon breakfast wrap"]},
    {"label": "Roast Turkey Pesto", "vendor": "Memoranda", "keywords": ["roast turkey pesto"]},
    {"label": "Smoked Ham and Brie", "vendor": "Memoranda", "keywords": ["smoked ham and brie"]},
    {"label": "Smoky Vegan Sausage Breakfast", "vendor": "Memoranda", "keywords": ["smoky vegan sausage breakfast"]},
    {"label": "Turkey Gouda Sandwich", "vendor": "Memoranda", "keywords": ["turkey gouda sandwich"]},
    {"label": "Vegan GF Viet Style Slaw", "vendor": "Memoranda", "keywords": ["vegan gf viet style slaw"]},
    {"label": "Vegan New Mexico Breakfast Wrap", "vendor": "Memoranda", "keywords": ["vegan new mexico breakfast wrap"]},
    {"label": "Vegan Smoky Breakfast Sandwich", "vendor": "Memoranda", "keywords": ["vegan smoky breakfast sandwich"]},
]


def match_type(name: str):
    n = (name or "").lower()
    best = None
    best_len = 0
    for t in ITEM_TYPES:
        for k in t["keywords"]:
            if k and k in n and len(k) > best_len:
                best = t
                best_len = len(k)
    return best


def parse_wide_product_mix(rows):
    """
    rows: list of lists (raw CSV cells), same shape the browser tool expects:
      row[0]: sparse date headers, one label sitting above each day's pair of columns
      row[1]: 'Class','Name',...,'Quantity','Total','Quantity','Total',...
      row[2:]: data rows

    Returns: ({ date_label: { item_label: total_qty_that_day } }, { item_label: vendor })
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
    unmatched = set()
    for row in data_rows:
        item_type = match_type(row[1] if len(row) > 1 else "")
        if not item_type:
            if len(row) > 1 and row[1]:
                unmatched.add(row[1])
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
            by_date.setdefault(date_label, {})
            by_date[date_label][item_type["label"]] = by_date[date_label].get(item_type["label"], 0) + qty

    if unmatched:
        print(f"Note: {len(unmatched)} product name(s) in the file didn't match any known item and were skipped:")
        for name in sorted(unmatched):
            print(f"  - {name}")

    return by_date, {t["label"]: t["vendor"] for t in ITEM_TYPES}


def normalize_date(date_label: str) -> str:
    """Convert a header like 'Wed 07/29/2026' into 'YYYY-MM-DD'."""
    parts = date_label.split()
    date_part = parts[-1]
    dt = datetime.datetime.strptime(date_part, "%m/%d/%Y")
    return dt.strftime("%Y-%m-%d")


def main():
    parser = argparse.ArgumentParser(description="Backfill a year of Product Mix data into saved history.")
    parser.add_argument("file", help="Path to the wide-format Product Mix CSV")
    parser.add_argument("--api", required=True, help="Backend base URL, e.g. https://your-app.up.railway.app")
    parser.add_argument("--category", default="Sandwiches", help="Category name in the tool (default: Sandwiches)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be sent, without posting")
    args = parser.parse_args()

    path = Path(args.file)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    by_date, vendor_map = parse_wide_product_mix(rows)
    if not by_date:
        print("No matching data found — check the file format and ITEM_TYPES list.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(by_date)} day(s) of data.")
    posted = 0
    failed = 0

    for date_label, items in sorted(by_date.items(), key=lambda kv: kv[0]):
        try:
            date_iso = normalize_date(date_label)
        except Exception as e:
            print(f"Skipping unparseable date '{date_label}': {e}")
            continue

        entries = {}
        for item_label, qty in items.items():
            entries[item_label] = {
                "vendor": vendor_map.get(item_label, ""),
                "onHand": None,        # unknowable retroactively; only used for today's suggestion
                "soldInFile": qty,
                "damaged": 0,           # not backfilled — see module docstring
                "daysInFile": 1,        # this entry represents a single day
                "avgDailySold": qty,    # qty over 1 day = that day's rate
                "suggestedOrder": None,
            }

        payload = {"category": args.category, "weekEnding": date_iso, "entries": entries}

        if args.dry_run:
            print(f"[dry-run] {date_iso}: {len(entries)} item(s), e.g. {list(entries.items())[:1]}")
            continue

        try:
            resp = requests.post(f"{args.api}/api/history", json=payload, timeout=15)
            if resp.ok:
                posted += 1
            else:
                failed += 1
                print(f"Failed for {date_iso}: {resp.status_code} {resp.text}")
        except requests.RequestException as e:
            failed += 1
            print(f"Request error for {date_iso}: {e}")

        time.sleep(0.05)  # be gentle with a free-tier backend

    if args.dry_run:
        print("Dry run complete — nothing was posted. Drop --dry-run to actually import.")
    else:
        print(f"Done. Posted {posted} day(s), {failed} failure(s).")


if __name__ == "__main__":
    main()
