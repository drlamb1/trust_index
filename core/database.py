"""
EdgeFinder — Database Connection

Async SQLAlchemy engine for Neon PostgreSQL.

Key design decisions:
  - pool_pre_ping=True: Re-validates connection before use (handles Neon cold starts)
  - pool_recycle=300: Recycles connections every 5 min (matches Neon's pause threshold)
  - expire_on_commit=False: Prevents lazy-load errors in async contexts
  - tenacity retry: Handles the 2-5s cold start latency on Neon free tier

Usage:
    from core.database import AsyncSessionLocal, get_db

    # In FastAPI route (use get_db dependency instead):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Ticker))

    # In Celery task (sync wrapper with asyncio.run):
    async def _my_async_task():
        async with AsyncSessionLocal() as session:
            ...
    asyncio.run(_my_async_task())
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator

import tenacity
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

# asyncpg doesn't understand the ?sslmode=require query param — strip it
# from the URL and pass ssl="require" via connect_args instead.
_db_url = settings.database_url
if "sslmode=" in _db_url:
    import re

    _db_url = re.sub(r"[?&]sslmode=[^&]*", "", _db_url)

_connect_args: dict = {
    "server_settings": {"application_name": "edgefinder"},
    "command_timeout": 30,
}
if "sslmode=require" in settings.database_url:
    import ssl as _ssl_mod

    _connect_args["ssl"] = _ssl_mod.create_default_context()

# Celery workers call asyncio.run() per task, which creates and closes event
# loops. A connection pool bound to one loop becomes invalid in the next task.
# NullPool creates a fresh connection each time, avoiding stale-loop errors.
# NullPool required for any Celery process type (worker, simulation-worker, beat)
# because each task calls asyncio.run(), creating/destroying event loops.
_is_worker = os.environ.get("PROCESS_TYPE") in ("worker", "simulation-worker", "beat")

_engine_kwargs: dict = {
    "echo": False,
    "connect_args": _connect_args,
}

if _is_worker:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        pool_size=5,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=300,
    )

engine = create_async_engine(_db_url, **_engine_kwargs)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    # CRITICAL for async: prevents "DetachedInstanceError" after session closes.
    # Without this, accessing attributes after commit raises an error because
    # SQLAlchemy tries to lazy-load via a closed session.
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async database session.

    Automatically commits on success and rolls back on exception.
    Usage:
        @router.get("/tickers")
        async def list_tickers(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Resilient query execution (handles Neon cold starts)
# ---------------------------------------------------------------------------


@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=8),
    retry=tenacity.retry_if_exception_type(OperationalError),
    before_sleep=lambda retry_state: logger.warning(
        "Database connection failed (Neon cold start?), retrying in %ss...",
        retry_state.next_action.sleep,  # type: ignore[union-attr]
    ),
    reraise=True,
)
async def execute_with_retry(session: AsyncSession, stmt):
    """
    Execute a SQLAlchemy statement with retry logic for Neon cold starts.

    Neon free tier pauses compute after 5 minutes of inactivity. The first
    query after a pause may fail with OperationalError before the instance wakes.
    Retrying 2-3 times with exponential backoff handles this gracefully.

    Usage:
        result = await execute_with_retry(session, select(Ticker))
        tickers = result.scalars().all()
    """
    return await session.execute(stmt)


# ---------------------------------------------------------------------------
# Startup health check
# ---------------------------------------------------------------------------


async def check_db_connection() -> bool:
    """
    Ping the database. Used on FastAPI startup to warm up Neon connection.
    Returns True if successful, False otherwise.
    """
    from sqlalchemy import text

    try:
        async with AsyncSessionLocal() as session:
            await execute_with_retry(session, text("SELECT 1"))
        logger.info("Database connection established successfully.")
        return True
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Alembic helper (used in alembic/env.py)
# ---------------------------------------------------------------------------


def get_sync_database_url() -> str:
    """
    Returns a synchronous database URL for Alembic migrations.
    Converts postgresql+asyncpg:// → postgresql+psycopg2://

    Note: Alembic runs migrations synchronously even in async projects.
    """
    url = settings.database_url
    return url.replace("postgresql+asyncpg://", "postgresql://")
