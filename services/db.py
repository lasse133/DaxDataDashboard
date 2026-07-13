"""Optional PostgreSQL persistence for the DAX 40 Audit Risk Radar.

The dashboard must keep working when no database is configured (local dev,
demos), so every public function here degrades gracefully: if DATABASE_URL
is unset or the database is unreachable, reads return None and writes are
silently skipped. The app then behaves exactly as before (in-memory only).

On CapRover the connection string points at the one-click Postgres app via
its internal DNS name, e.g.:

    DATABASE_URL=postgresql://postgres:<password>@srv-captain--dax-db:5432/risk_data

set on the *dashboard* app under App Configs -> Environment Variables.

Two tables, both created automatically on first use:

* nlp_cache      -- one row per analyzed headline. Stores the expensive
                    transformer output (translation, sentiment, topic scores)
                    keyed by a hash of (topics_key, language_hint, title), so
                    a container restart or redeploy never re-pays for
                    inference already done.
* headline_cache -- one row per reporting-period fetch (ticker/year/quarters).
                    Stores the merged, filtered headline list + diagnostics so
                    restarts don't re-hit the rate-limited news APIs. Rows
                    older than the caller's max_age are ignored; the
                    "Fetch latest data" button bypasses this cache entirely.

Design notes: plain functions and SQLAlchemy Core, no ORM models — matching
the "no abstraction until it earns its keep" style of services/news.py.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert

# JSONB on Postgres, generic JSON elsewhere (lets tests run against SQLite).
_JSON = sa.JSON().with_variant(JSONB(), "postgresql")

_metadata = sa.MetaData()

nlp_cache = sa.Table(
    "nlp_cache",
    _metadata,
    sa.Column("cache_key", sa.String(64), primary_key=True),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("language_hint", sa.String(16), nullable=False, default=""),
    sa.Column("topics_key", sa.String(32), nullable=False),
    sa.Column("analysis", _JSON, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

headline_cache = sa.Table(
    "headline_cache",
    _metadata,
    sa.Column("cache_key", sa.String(255), primary_key=True),
    sa.Column("headlines", _JSON, nullable=False),
    sa.Column("diagnostics", _JSON, nullable=False),
    sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
)

# Engine is created lazily once per process. _status carries a short
# human-readable string for the sidebar ("connected", "not configured", ...).
_engine: sa.Engine | None = None
_engine_initialized = False
_status = "not configured"


def _get_engine() -> sa.Engine | None:
    global _engine, _engine_initialized, _status
    if _engine_initialized:
        return _engine
    _engine_initialized = True

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        _status = "not configured (set DATABASE_URL)"
        return None
    try:
        engine = sa.create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        _metadata.create_all(engine)
        _engine = engine
        _status = "connected"
    except Exception as exc:  # noqa: BLE001 — any DB failure means "run without persistence"
        _status = f"unavailable ({type(exc).__name__})"
        _engine = None
    return _engine


def available() -> bool:
    return _get_engine() is not None


def status() -> str:
    """Short connection-state string for the sidebar."""
    _get_engine()
    return _status


def analysis_key(title: str, language_hint: str, topics_key: str) -> str:
    raw = f"{topics_key}|{language_hint}|{title}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# NLP result cache
# ---------------------------------------------------------------------------

def get_analysis(cache_key: str) -> dict[str, Any] | None:
    engine = _get_engine()
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa.select(nlp_cache.c.analysis).where(nlp_cache.c.cache_key == cache_key)
            ).first()
        return row[0] if row else None
    except Exception:
        return None


def save_analysis(
    cache_key: str,
    title: str,
    language_hint: str,
    topics_key: str,
    analysis: dict[str, Any],
) -> None:
    engine = _get_engine()
    if engine is None:
        return
    values = {
        "cache_key": cache_key,
        "title": title,
        "language_hint": language_hint or "",
        "topics_key": topics_key,
        "analysis": analysis,
        "created_at": datetime.now(timezone.utc),
    }
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                stmt = pg_insert(nlp_cache).values(**values)
                stmt = stmt.on_conflict_do_nothing(index_elements=["cache_key"])
                conn.execute(stmt)
            else:
                exists = conn.execute(
                    sa.select(nlp_cache.c.cache_key).where(nlp_cache.c.cache_key == cache_key)
                ).first()
                if not exists:
                    conn.execute(sa.insert(nlp_cache).values(**values))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Headline fetch cache
# ---------------------------------------------------------------------------

def headlines_key(ticker: str, year: int, quarters: tuple[int, ...]) -> str:
    return f"{ticker}|{year}|{'-'.join(str(q) for q in quarters)}"


def get_headlines(
    cache_key: str, max_age: timedelta
) -> tuple[list[dict], list[dict]] | None:
    """Return (headlines, diagnostics) if a fresh-enough row exists, else None."""
    engine = _get_engine()
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa.select(
                    headline_cache.c.headlines,
                    headline_cache.c.diagnostics,
                    headline_cache.c.fetched_at,
                ).where(headline_cache.c.cache_key == cache_key)
            ).first()
        if row is None:
            return None
        fetched_at = row.fetched_at
        if fetched_at.tzinfo is None:  # SQLite drops tzinfo
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched_at > max_age:
            return None
        return list(row.headlines), list(row.diagnostics)
    except Exception:
        return None


def save_headlines(
    cache_key: str, headlines: list[dict], diagnostics: list[dict]
) -> None:
    """Upsert the fetch result; always overwrites so refreshes win."""
    engine = _get_engine()
    if engine is None:
        return
    values = {
        "cache_key": cache_key,
        "headlines": headlines,
        "diagnostics": diagnostics,
        "fetched_at": datetime.now(timezone.utc),
    }
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                stmt = pg_insert(headline_cache).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["cache_key"],
                    set_={
                        "headlines": stmt.excluded.headlines,
                        "diagnostics": stmt.excluded.diagnostics,
                        "fetched_at": stmt.excluded.fetched_at,
                    },
                )
                conn.execute(stmt)
            else:
                conn.execute(
                    sa.delete(headline_cache).where(headline_cache.c.cache_key == cache_key)
                )
                conn.execute(sa.insert(headline_cache).values(**values))
    except Exception:
        pass
