"""Storage-layer tests, run against an in-memory SQLite engine — proves the
SQLAlchemy query logic (upsert/fetch/delete/categories) is correct without
needing a live Postgres instance. The same code path runs against Postgres
in production; only the connection string differs."""

from sqlalchemy import create_engine

from app import db


def make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    db.metadata.create_all(engine)
    return engine


def test_fetch_history_empty():
    engine = make_engine()
    assert db.fetch_history(engine, "Milk") == []


def test_upsert_then_fetch():
    engine = make_engine()
    db.upsert_week(engine, "Milk", "2026-08-01", {"Whole Milk": {"sold": 10}})
    history = db.fetch_history(engine, "Milk")
    assert history == [{"entryDate": "2026-08-01", "entries": {"Whole Milk": {"sold": 10}}}]


def test_upsert_overwrites_same_category_and_week():
    engine = make_engine()
    db.upsert_week(engine, "Milk", "2026-08-01", {"Whole Milk": {"sold": 10}})
    db.upsert_week(engine, "Milk", "2026-08-01", {"Whole Milk": {"sold": 15}})
    history = db.fetch_history(engine, "Milk")
    assert len(history) == 1
    assert history[0]["entries"]["Whole Milk"]["sold"] == 15


def test_history_ordered_oldest_first():
    engine = make_engine()
    db.upsert_week(engine, "Milk", "2026-08-08", {})
    db.upsert_week(engine, "Milk", "2026-08-01", {})
    history = db.fetch_history(engine, "Milk")
    assert [w["entryDate"] for w in history] == ["2026-08-01", "2026-08-08"]


def test_history_scoped_to_category():
    engine = make_engine()
    db.upsert_week(engine, "Milk", "2026-08-01", {"a": 1})
    db.upsert_week(engine, "Sandwiches", "2026-08-01", {"b": 2})
    assert len(db.fetch_history(engine, "Milk")) == 1
    assert len(db.fetch_history(engine, "Sandwiches")) == 1


def test_delete_week():
    engine = make_engine()
    db.upsert_week(engine, "Milk", "2026-08-01", {})
    assert db.delete_week(engine, "Milk", "2026-08-01") == 1
    assert db.fetch_history(engine, "Milk") == []


def test_delete_missing_week_returns_zero():
    engine = make_engine()
    assert db.delete_week(engine, "Milk", "2099-01-01") == 0


def test_fetch_categories_distinct_and_sorted():
    engine = make_engine()
    db.upsert_week(engine, "Sandwiches", "2026-08-01", {})
    db.upsert_week(engine, "Milk", "2026-08-01", {})
    db.upsert_week(engine, "Milk", "2026-08-08", {})
    assert db.fetch_categories(engine) == ["Milk", "Sandwiches"]
