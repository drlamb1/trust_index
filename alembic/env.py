"""
Alembic Migration Environment — Async Configuration

EdgeFinder uses SQLAlchemy async + Neon PostgreSQL.
Alembic runs migrations synchronously using a sync engine wrapper.

Run migrations:
    alembic upgrade head
    alembic revision --autogenerate -m "description"
    alembic downgrade -1
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Add project root to sys.path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import models so Alembic's autogenerate can see all tables
from config.settings import settings  # noqa: E402
from core.models import Base  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic Config
# ---------------------------------------------------------------------------

config = context.config

# Interpret alembic.ini's logging config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the metadata for autogenerate support
target_metadata = Base.metadata


# Use the DATABASE_URL from settings (not alembic.ini)
# Convert asyncpg URL to psycopg2 for synchronous Alembic migrations
def get_sync_url() -> str:
    url = settings.database_url
    # asyncpg → psycopg2 (sync driver for Alembic)
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ---------------------------------------------------------------------------
# Offline migrations (generates SQL without connecting to DB)
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL script)."""
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations (connects to Neon PostgreSQL)
# ---------------------------------------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using async engine (required for asyncpg)."""
    alembic_config = config.get_section(config.config_ini_section) or {}
    alembic_config["sqlalchemy.url"] = get_sync_url()

    connectable = async_engine_from_config(
        alembic_config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations with a live DB connection."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
