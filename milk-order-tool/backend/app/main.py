"""
Order Reconciliation Tool — backend

A tiny API that stores weekly reconciliation entries (milk, sandwiches, etc.)
per category, so multiple people (e.g. Leena + Aiden) see the same saved
history from any device. Storage is Postgres in production (DATABASE_URL) or
local SQLite for dev — see db.py.

Run locally:    uvicorn app.main:app --reload
Deploy:         Railway / Render, start command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""

import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import dashboard, db, ml_forecasting

# Set this to your GitHub Pages URL once deployed, e.g. "https://leena.github.io"
# Using "*" works but allows any website to call this API — fine while testing,
# tighten it once the frontend URL is final.
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

# Mirrors RECONCILIATION_CLASSES in index.html and backend/scripts/backfill_import.py —
# the one category that needs reconciliation math instead of ML-forecasted par
# ordering. Keep all three in sync. See docs/decisions/0003-auto-detect-items-and-categories.md.
RECONCILIATION_CLASSES = {"Smith Brothers Farms"}

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


@app.get("/api/categories")
def get_categories():
    """Distinct categories that have at least one saved week — lets the
    frontend build its category tabs from real data instead of a manually
    maintained list."""
    return db.fetch_categories(db.get_engine())


@app.get("/api/history")
def get_history(category: str):
    """Return all saved weeks for a category, oldest first."""
    return db.fetch_history(db.get_engine(), category)


@app.post("/api/history")
def save_week(week: WeekEntry):
    """Save or overwrite the entry for a given category + week."""
    db.upsert_week(db.get_engine(), week.category, week.weekEnding, week.entries)
    return {"status": "saved", "category": week.category, "weekEnding": week.weekEnding}


@app.get("/api/forecast")
def get_forecast(category: str, targetDate: str):
    """ML-based demand forecast for a par-mode category — see
    ml_forecasting.py. Not available for reconciliation-mode categories
    (Milk's suggestion math is untouched by this feature)."""
    if category in RECONCILIATION_CLASSES:
        raise HTTPException(
            status_code=400,
            detail=f"{category} uses reconciliation math, not ML forecasting.",
        )
    weeks = db.fetch_history(db.get_engine(), category)
    try:
        return ml_forecasting.forecast_category(weeks, targetDate)
    except ValueError:
        raise HTTPException(status_code=400, detail="targetDate must be YYYY-MM-DD")


@app.get("/api/dashboard")
def get_dashboard(category: str, item: Optional[str] = None):
    """Mode-aware sales-trend aggregates for the dashboard view — see
    dashboard.py. Read-only; never touches Milk's suggestion math."""
    weeks = db.fetch_history(db.get_engine(), category)
    is_reconciliation = category in RECONCILIATION_CLASSES
    return dashboard.dashboard_for_category(weeks, is_reconciliation, item=item)


@app.delete("/api/history")
def delete_week(category: str, weekEnding: str):
    """Remove a saved week, in case of a data-entry mistake."""
    rowcount = db.delete_week(db.get_engine(), category, weekEnding)
    if rowcount == 0:
        raise HTTPException(status_code=404, detail="No matching week found")
    return {"status": "deleted"}
