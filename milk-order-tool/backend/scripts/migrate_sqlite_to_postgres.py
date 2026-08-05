"""
One-time migration: read an existing local SQLite data.db and POST every
saved week to a Postgres-backed deployment of this API, via the existing
/api/history endpoint. Safe to re-run — that endpoint upserts on
(category, entryDate), so posting the same week twice just overwrites it
with itself.

Note: an old local data.db predates the entry_date rename (see
docs/decisions/0009-rename-week-ending.md) and still has its column named
week_ending — that's read as-is below and translated to the current
entryDate API field on the way out.

Usage:
    python scripts/migrate_sqlite_to_postgres.py path/to/data.db \
        --api https://your-backend.up.railway.app \
        --dry-run           # preview first, without posting anything

Then drop --dry-run to actually migrate. Run this once, after the backend at
--api is already deployed with DATABASE_URL pointed at Postgres (see
docs/decisions/0002-postgres-migration.md), and before you rely on the
Postgres-backed data for anything.
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import requests


def read_local_weeks(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT category, week_ending, entries FROM weeks ORDER BY category, week_ending"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"category": r[0], "entryDate": r[1], "entries": json.loads(r[2])}
        for r in rows
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Migrate a local SQLite data.db into a Postgres-backed deployment."
    )
    parser.add_argument("db_path", help="Path to the existing local data.db")
    parser.add_argument("--api", required=True, help="Backend base URL, already running against Postgres")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be sent, without posting")
    args = parser.parse_args()

    if not Path(args.db_path).exists():
        print(f"No SQLite file found at {args.db_path} — nothing to migrate.", file=sys.stderr)
        sys.exit(1)

    weeks = read_local_weeks(args.db_path)
    print(f"Found {len(weeks)} saved week(s) across all categories.")

    posted = 0
    failed = 0
    for week in weeks:
        if args.dry_run:
            print(f"[dry-run] {week['category']} / {week['entryDate']}: {len(week['entries'])} item(s)")
            continue
        try:
            resp = requests.post(f"{args.api}/api/history", json=week, timeout=15)
            if resp.ok:
                posted += 1
            else:
                failed += 1
                print(f"Failed for {week['category']} / {week['entryDate']}: {resp.status_code} {resp.text}")
        except requests.RequestException as e:
            failed += 1
            print(f"Request error for {week['category']} / {week['entryDate']}: {e}")
        time.sleep(0.05)  # be gentle with a free-tier backend

    if args.dry_run:
        print("Dry run complete — nothing was posted. Drop --dry-run to actually migrate.")
    else:
        print(f"Done. Posted {posted} week(s), {failed} failure(s).")
        if failed == 0 and posted == len(weeks):
            print("All weeks migrated successfully — verify a few in the app, then you can retire the old SQLite file.")


if __name__ == "__main__":
    main()
