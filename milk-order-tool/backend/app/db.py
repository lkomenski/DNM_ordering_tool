"""
Storage layer for the Order Reconciliation Tool.

Uses SQLAlchemy Core against Postgres in production (DATABASE_URL, which
Railway auto-injects once its Postgres plugin is added to the project) or a
local SQLite file for local dev and tests when DATABASE_URL isn't set.

`entries` stays a JSON *string* column rather than Postgres-native JSONB, so
the exact same schema and queries work unchanged against both backends —
nothing queries inside the JSON today. See docs/decisions/0002-postgres-migration.md.
"""

import json
import os

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete as sa_delete,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

metadata = MetaData()

weeks_table = Table(
    "weeks",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("category", String, nullable=False),
    Column("week_ending", String, nullable=False),
    Column("entries", Text, nullable=False),
    UniqueConstraint("category", "week_ending", name="uq_category_week_ending"),
)


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        # Railway (and Heroku-style providers) hand out "postgres://", but
        # SQLAlchemy 2.x's psycopg2 dialect requires "postgresql://".
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    db_path = os.environ.get("DB_PATH", "data.db")
    return f"sqlite:///{db_path}"


_engine = None


def get_engine():
    """Process-wide singleton engine, built from DATABASE_URL/DB_PATH."""
    global _engine
    if _engine is None:
        url = get_database_url()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args, future=True)
        metadata.create_all(_engine)
    return _engine


def fetch_categories(engine) -> list:
    """Distinct categories that have at least one saved week, alphabetical."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(weeks_table.c.category).distinct().order_by(weeks_table.c.category)
        )
        return [r[0] for r in rows]


def fetch_history(engine, category: str) -> list:
    """All saved weeks for a category, oldest first."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(weeks_table.c.week_ending, weeks_table.c.entries)
            .where(weeks_table.c.category == category)
            .order_by(weeks_table.c.week_ending)
        )
        return [{"weekEnding": r[0], "entries": json.loads(r[1])} for r in rows]


def upsert_week(engine, category: str, week_ending: str, entries: dict) -> None:
    """Save or overwrite the entry for a given category + week."""
    entries_json = json.dumps(entries)
    insert = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    with engine.begin() as conn:
        stmt = insert(weeks_table).values(
            category=category, week_ending=week_ending, entries=entries_json
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["category", "week_ending"],
            set_={"entries": stmt.excluded.entries},
        )
        conn.execute(stmt)


def delete_week(engine, category: str, week_ending: str) -> int:
    """Remove a saved week. Returns the number of rows deleted (0 or 1)."""
    with engine.begin() as conn:
        result = conn.execute(
            sa_delete(weeks_table).where(
                weeks_table.c.category == category,
                weeks_table.c.week_ending == week_ending,
            )
        )
        return result.rowcount
