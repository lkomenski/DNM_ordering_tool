"""
Order Reconciliation Tool — backend

A tiny API that stores weekly reconciliation entries (milk, sandwiches, etc.)
per category, so multiple people (e.g. Leena + Aiden) see the same saved
history from any device. Uses SQLite — no external database service needed.

Run locally:    uvicorn main:app --reload
Deploy:         Railway / Render, start command: uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import json
import os
import sqlite3
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = os.environ.get("DB_PATH", "data.db")

# Set this to your GitHub Pages URL once deployed, e.g. "https://leena.github.io"
# Using "*" works but allows any website to call this API — fine while testing,
# tighten it once the frontend URL is final.
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS weeks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            week_ending TEXT NOT NULL,
            entries TEXT NOT NULL,
            UNIQUE(category, week_ending)
        )
        """
    )
    try:
        yield conn
    finally:
        conn.close()


app = FastAPI(title="Order Reconciliation Tool API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class WeekEntry(BaseModel):
    category: str
    weekEnding: str  # YYYY-MM-DD
    entries: dict     # { itemLabel: {beginning, ordered, sold, endingCount, gap, totalUsed} }


@app.get("/")
def root():
    return {"status": "ok", "service": "order-reconciliation-tool"}


@app.get("/api/history")
def get_history(category: str):
    """Return all saved weeks for a category, oldest first."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT week_ending, entries FROM weeks WHERE category = ? ORDER BY week_ending",
            (category,),
        ).fetchall()
    return [{"weekEnding": r[0], "entries": json.loads(r[1])} for r in rows]


@app.post("/api/history")
def save_week(week: WeekEntry):
    """Save or overwrite the entry for a given category + week."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO weeks (category, week_ending, entries)
            VALUES (?, ?, ?)
            ON CONFLICT(category, week_ending)
            DO UPDATE SET entries = excluded.entries
            """,
            (week.category, week.weekEnding, json.dumps(week.entries)),
        )
        conn.commit()
    return {"status": "saved", "category": week.category, "weekEnding": week.weekEnding}


@app.delete("/api/history")
def delete_week(category: str, weekEnding: str):
    """Remove a saved week, in case of a data-entry mistake."""
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM weeks WHERE category = ? AND week_ending = ?",
            (category, weekEnding),
        )
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="No matching week found")
    return {"status": "deleted"}
