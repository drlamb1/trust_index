"""
EdgeFinder — Celery Task Definitions

All Celery tasks and the Beat (scheduler) configuration.

Architecture decision: Celery tasks are synchronous wrappers around
async functions. Each task calls asyncio.run() to spin up a fresh event
loop for its async work. This avoids celery-pool-asyncio complexity.

IMPORTANT: Never share asyncpg connection pools across asyncio.run() calls.
The AsyncSessionLocal factory creates a fresh connection per call, which
is correct for this pattern.

Queues:
  ingestion  — Data fetching (prices, filings, news) — 4 workers
  analysis   — Computation (technicals, sentiment, NLP) — 2 workers
  alerts     — Alert engine + dip scoring — 2 workers
  delivery   — Email, Slack, webhook delivery — 1 worker

Worker startup:
  celery -A scheduler.tasks worker -Q ingestion -c 4 -n ingestion@%h
  celery -A scheduler.tasks worker -Q analysis  -c 2 -n analysis@%h
  celery -A scheduler.tasks worker -Q alerts    -c 2 -n alerts@%h
  celery -A scheduler.tasks worker -Q delivery  -c 1 -n delivery@%h
  celery -A scheduler.tasks beat --loglevel=info
"""

from __future__ import annotations

import asyncio
import logging
import ssl

from celery import Celery
from celery.schedules import crontab

from config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery app initialization
# ---------------------------------------------------------------------------

celery_app = Celery("edgefinder")

# SSL configuration for Upstash Redis (rediss:// URLs require SSL)
_ssl_options = {"ssl_cert_reqs": ssl.CERT_NONE} if settings.redis_uses_ssl else {}

celery_app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    # SSL for Upstash
    broker_use_ssl=_ssl_options if settings.redis_uses_ssl else None,
    redis_backend_use_ssl=_ssl_options if settings.redis_uses_ssl else None,
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Reliability
    task_acks_late=True,  # Only ack after task completes (not crashes)
    worker_prefetch_multiplier=1,  # Don't pre-fetch; each task may be long-running
    task_reject_on_worker_lost=True,  # Re-queue on worker crash
    broker_connection_retry_on_startup=True,
    broker_heartbeat=10,  # Detect Upstash connection drops
    # Timeouts
    task_soft_time_limit=3600,  # 1 hour soft limit (sends SoftTimeLimitExceeded)
    task_time_limit=3900,  # 1h 5min hard kill
    # Queue routing
    task_routes={
        "scheduler.tasks.task_fetch_prices": {"queue": "ingestion"},
        "scheduler.tasks.task_fetch_prices_batch": {"queue": "ingestion"},
        "scheduler.tasks.task_fetch_eod_prices": {"queue": "ingestion"},
        "scheduler.tasks.task_sync_sp500": {"queue": "ingestion"},
        "scheduler.tasks.task_fetch_new_filings": {"queue": "ingestion"},
        "scheduler.tasks.task_aggregate_news": {"queue": "ingestion"},
        "scheduler.tasks.task_fetch_insider_trades": {"queue": "ingestion"},
        "scheduler.tasks.task_fetch_institutional": {"queue": "ingestion"},
        "scheduler.tasks.task_sync_earnings_calendar": {"queue": "ingestion"},
        "scheduler.tasks.task_compute_technicals": {"queue": "analysis"},
        "scheduler.tasks.task_compute_technicals_batch": {"queue": "analysis"},
        "scheduler.tasks.task_analyze_pending_filings": {"queue": "analysis"},
        "scheduler.tasks.task_run_sentiment_batch": {"queue": "analysis"},
        "scheduler.tasks.task_detect_anomalies": {"queue": "analysis"},
        "scheduler.tasks.task_compute_sector_rotation": {"queue": "analysis"},
        "scheduler.tasks.task_run_thesis_matching": {"queue": "analysis"},
        "scheduler.tasks.task_db_keepalive": {"queue": "analysis"},
        "scheduler.tasks.task_run_alert_engine": {"queue": "alerts"},
        "scheduler.tasks.task_compute_dip_scores": {"queue": "alerts"},
        "scheduler.tasks.task_check_snoozed_alerts": {"queue": "alerts"},
        "scheduler.tasks.task_send_daily_briefing": {"queue": "delivery"},
        "scheduler.tasks.task_send_weekly_digest": {"queue": "delivery"},
    },
    # Default queue for unrouted tasks
    task_default_queue="ingestion",
)

# ---------------------------------------------------------------------------
# Beat Schedule — all recurring tasks
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    # ================================================================
    # INGESTION QUEUE
    # ================================================================
    # Intraday price refresh — every 15 min Mon-Fri 2:30-9 PM UTC (9:30 AM-4 PM EST)
    "fetch-intraday-prices": {
        "task": "scheduler.tasks.task_fetch_prices_batch",
        "schedule": crontab(minute="*/15", hour="14-21", day_of_week="1-5"),
        "queue": "ingestion",
    },
    # EOD price confirmation — 9 PM UTC (4 PM EST) Mon-Fri
    "fetch-eod-prices": {
        "task": "scheduler.tasks.task_fetch_eod_prices",
        "schedule": crontab(minute=0, hour=21, day_of_week="1-5"),
        "queue": "ingestion",
    },
    # S&P 500 constituent sync — weekly on Sunday at 6 AM UTC
    "sync-sp500": {
        "task": "scheduler.tasks.task_sync_sp500",
        "schedule": crontab(minute=0, hour=6, day_of_week=0),
        "queue": "ingestion",
    },
    # EDGAR new filings check — every 2 hours Mon-Fri during trading hours
    "fetch-new-filings": {
        "task": "scheduler.tasks.task_fetch_new_filings",
        "schedule": crontab(minute=0, hour="*/2", day_of_week="1-5"),
        "queue": "ingestion",
    },
    # News aggregation — every 30 minutes (all week)
    "aggregate-news": {
        "task": "scheduler.tasks.task_aggregate_news",
        "schedule": crontab(minute="*/30"),
        "queue": "ingestion",
    },
    # Insider trades (Form 4) — twice daily Mon-Fri
    "fetch-insider-trades": {
        "task": "scheduler.tasks.task_fetch_insider_trades",
        "schedule": crontab(minute=0, hour="8,17", day_of_week="1-5"),
        "queue": "ingestion",
    },
    # 13F institutional holdings — Monday 7 AM UTC (quarterly filings but check weekly)
    "fetch-institutional": {
        "task": "scheduler.tasks.task_fetch_institutional",
        "schedule": crontab(minute=0, hour=7, day_of_week=1),
        "queue": "ingestion",
    },
    # Earnings calendar sync — daily at 6 AM UTC
    "sync-earnings-calendar": {
        "task": "scheduler.tasks.task_sync_earnings_calendar",
        "schedule": crontab(minute=0, hour=6),
        "queue": "ingestion",
    },
    # ================================================================
    # ANALYSIS QUEUE
    # ================================================================
    # Technical indicators — 35 min after EOD prices (9:35 PM UTC Mon-Fri)
    "compute-technicals-eod": {
        "task": "scheduler.tasks.task_compute_technicals_batch",
        "schedule": crontab(minute=35, hour=21, day_of_week="1-5"),
        "queue": "analysis",
    },
    # Filing analysis — process new filings every 3 hours Mon-Fri
    "analyze-pending-filings": {
        "task": "scheduler.tasks.task_analyze_pending_filings",
        "schedule": crontab(minute=0, hour="*/3", day_of_week="1-5"),
        "queue": "analysis",
    },
    # Batch sentiment scoring — hourly at :45 (offset from other jobs)
    "score-news-sentiment": {
        "task": "scheduler.tasks.task_run_sentiment_batch",
        "schedule": crontab(minute=45, hour="*"),
        "queue": "analysis",
    },
    # Anomaly detection — 45 min after EOD (9:45 PM UTC Mon-Fri)
    "detect-anomalies": {
        "task": "scheduler.tasks.task_detect_anomalies",
        "schedule": crontab(minute=45, hour=21, day_of_week="1-5"),
        "queue": "analysis",
    },
    # Sector rotation — 10 PM UTC Mon-Fri (after technicals complete)
    "compute-sector-rotation": {
        "task": "scheduler.tasks.task_compute_sector_rotation",
        "schedule": crontab(minute=0, hour=22, day_of_week="1-5"),
        "queue": "analysis",
    },
    # Thesis matching — 10:30 PM UTC daily
    "match-theses": {
        "task": "scheduler.tasks.task_run_thesis_matching",
        "schedule": crontab(minute=30, hour=22),
        "queue": "analysis",
    },
    # Neon DB keepalive — every 3 minutes during market hours to prevent cold starts
    # Neon free tier pauses after 5 min of inactivity
    "db-keepalive": {
        "task": "scheduler.tasks.task_db_keepalive",
        "schedule": crontab(minute="*/3", hour="13-22", day_of_week="1-5"),
        "queue": "analysis",
    },
    # ================================================================
    # ALERTS QUEUE
    # ================================================================
    # Alert engine — every 15 min Mon-Fri 2-10 PM UTC (market hours + post-market)
    "run-alert-engine": {
        "task": "scheduler.tasks.task_run_alert_engine",
        "schedule": crontab(minute="*/15", hour="14-22", day_of_week="1-5"),
        "queue": "alerts",
    },
    # DipScore computation — every 30 min during market hours
    "compute-dip-scores": {
        "task": "scheduler.tasks.task_compute_dip_scores",
        "schedule": crontab(minute="*/30", hour="14-21", day_of_week="1-5"),
        "queue": "alerts",
    },
    # Snoozed alert expiry — every 5 minutes
    "check-snoozed-alerts": {
        "task": "scheduler.tasks.task_check_snoozed_alerts",
        "schedule": crontab(minute="*/5"),
        "queue": "alerts",
    },
    # ================================================================
    # DELIVERY QUEUE
    # ================================================================
    # Daily briefing — 7 AM UTC (2 AM EST, before pre-market opens)
    "send-daily-briefing": {
        "task": "scheduler.tasks.task_send_daily_briefing",
        "schedule": crontab(minute=0, hour=7),
        "queue": "delivery",
    },
    # Weekly digest — Sunday 8 PM UTC
    "send-weekly-digest": {
        "task": "scheduler.tasks.task_send_weekly_digest",
        "schedule": crontab(minute=0, hour=20, day_of_week=0),
        "queue": "delivery",
    },
}

# ---------------------------------------------------------------------------
# Helper: async task wrapper pattern
# ---------------------------------------------------------------------------


def run_async(coro):
    """
    Run an async coroutine synchronously inside a Celery task.

    Each call creates a fresh event loop. This is safe because:
    - asyncpg connections are created inside the coroutine (not shared across loops)
    - aiohttp/httpx clients are created fresh per call
    - No persistent async state exists across task invocations
    """
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# PHASE 1 TASKS — Foundation (prices + technicals)
# ---------------------------------------------------------------------------


@celery_app.task(name="scheduler.tasks.task_fetch_prices", bind=True, max_retries=3)
def task_fetch_prices(self, ticker_id: int, days: int = 1) -> dict:
    """Fetch price data for a single ticker."""

    async def _run():
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.price_data import fetch_and_store_prices

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Ticker).where(Ticker.id == ticker_id))
            ticker = result.scalar_one_or_none()
            if not ticker:
                return {"error": f"Ticker {ticker_id} not found"}
            count = await fetch_and_store_prices(session, ticker, days=days)
            return {"ticker_id": ticker_id, "rows_upserted": count}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_fetch_prices failed for ticker_id=%d: %s", ticker_id, exc)
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


@celery_app.task(name="scheduler.tasks.task_fetch_prices_batch")
def task_fetch_prices_batch(days: int = 1) -> dict:
    """Fetch price data for all active tickers."""

    async def _run():
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.price_data import fetch_and_store_prices_batch

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Ticker).where(Ticker.is_active.is_(True)))
            tickers = result.scalars().all()
            results = await fetch_and_store_prices_batch(session, list(tickers), days=days)
            return {"total_tickers": len(tickers), "results": results}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_fetch_prices_batch failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_fetch_eod_prices")
def task_fetch_eod_prices() -> dict:
    """Fetch EOD (end-of-day) prices for all active tickers."""
    return task_fetch_prices_batch(days=3)  # Fetch last 3 days to catch any gaps


@celery_app.task(name="scheduler.tasks.task_sync_sp500")
def task_sync_sp500() -> dict:
    """Sync S&P 500 constituent list from Wikipedia."""

    async def _run():
        from datetime import date

        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.price_data import fetch_sp500_symbols

        constituents = await fetch_sp500_symbols()
        if not constituents:
            return {"error": "Failed to fetch S&P 500 list"}

        async with AsyncSessionLocal() as session:
            current_symbols = {c["symbol"] for c in constituents}

            # Mark all current S&P 500 tickers
            existing = await session.execute(select(Ticker).where(Ticker.in_sp500.is_(True)))
            existing_sp500 = {t.symbol: t for t in existing.scalars().all()}

            added = 0
            updated = 0

            for constituent in constituents:
                symbol = constituent["symbol"]
                if symbol in existing_sp500:
                    # Already tracked — update metadata
                    ticker = existing_sp500[symbol]
                    ticker.name = constituent.get("name") or ticker.name
                    ticker.sector = constituent.get("sector") or ticker.sector
                    session.add(ticker)
                    updated += 1
                else:
                    # New S&P 500 ticker
                    result = await session.execute(select(Ticker).where(Ticker.symbol == symbol))
                    ticker = result.scalar_one_or_none()
                    if ticker:
                        ticker.in_sp500 = True
                        ticker.sp500_added_date = date.today()
                    else:
                        ticker = Ticker(
                            symbol=symbol,
                            name=constituent.get("name"),
                            sector=constituent.get("sector"),
                            industry=constituent.get("industry"),
                            in_sp500=True,
                            sp500_added_date=date.today(),
                            first_seen=date.today(),
                        )
                    session.add(ticker)
                    added += 1

            # Mark removed tickers
            removed = 0
            for symbol, ticker in existing_sp500.items():
                if symbol not in current_symbols:
                    ticker.in_sp500 = False
                    ticker.sp500_removed_date = date.today()
                    session.add(ticker)
                    removed += 1
                    logger.info("Ticker %s removed from S&P 500", symbol)

            await session.commit()
            return {"added": added, "updated": updated, "removed": removed}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_sync_sp500 failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_compute_technicals")
def task_compute_technicals(ticker_id: int) -> dict:
    """Compute technical indicators for a single ticker."""

    async def _run():
        from sqlalchemy import select

        from analysis.technicals import compute_and_store_technicals
        from core.database import AsyncSessionLocal
        from core.models import Ticker

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Ticker).where(Ticker.id == ticker_id))
            ticker = result.scalar_one_or_none()
            if not ticker:
                return {"error": f"Ticker {ticker_id} not found"}
            count = await compute_and_store_technicals(session, ticker)
            return {"ticker_id": ticker_id, "snapshots": count}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_compute_technicals failed for ticker_id=%d: %s", ticker_id, exc)
        raise


@celery_app.task(name="scheduler.tasks.task_compute_technicals_batch")
def task_compute_technicals_batch() -> dict:
    """Compute technical indicators for all active tickers."""

    async def _run():
        from sqlalchemy import select

        from analysis.technicals import compute_technicals_batch
        from core.database import AsyncSessionLocal
        from core.models import Ticker

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Ticker).where(Ticker.is_active.is_(True)))
            tickers = result.scalars().all()
            results = await compute_technicals_batch(session, list(tickers))
            total = sum(results.values())
            return {"total_tickers": len(tickers), "total_snapshots": total}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_compute_technicals_batch failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_db_keepalive")
def task_db_keepalive() -> dict:
    """Ping the database to prevent Neon cold start latency."""

    async def _run():
        from sqlalchemy import text

        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.warning("DB keepalive failed (will retry): %s", exc)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# PHASE 2+ STUBS — Filing, News, Alerts, Briefing
# These are stubs that will be fully implemented in later phases.
# Defined here so the Beat schedule can reference them without import errors.
# ---------------------------------------------------------------------------


@celery_app.task(name="scheduler.tasks.task_fetch_new_filings")
def task_fetch_new_filings() -> dict:
    logger.info("task_fetch_new_filings — stub (implement in Phase 2)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_aggregate_news")
def task_aggregate_news() -> dict:
    logger.info("task_aggregate_news — stub (implement in Phase 3)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_fetch_insider_trades")
def task_fetch_insider_trades() -> dict:
    logger.info("task_fetch_insider_trades — stub (implement in Phase 2)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_fetch_institutional")
def task_fetch_institutional() -> dict:
    logger.info("task_fetch_institutional — stub (implement in Phase 2)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_sync_earnings_calendar")
def task_sync_earnings_calendar() -> dict:
    logger.info("task_sync_earnings_calendar — stub (implement in Phase 3)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_analyze_pending_filings")
def task_analyze_pending_filings() -> dict:
    logger.info("task_analyze_pending_filings — stub (implement in Phase 2)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_run_sentiment_batch")
def task_run_sentiment_batch() -> dict:
    logger.info("task_run_sentiment_batch — stub (implement in Phase 3)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_detect_anomalies")
def task_detect_anomalies() -> dict:
    logger.info("task_detect_anomalies — stub (implement in Phase 3)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_compute_sector_rotation")
def task_compute_sector_rotation() -> dict:
    logger.info("task_compute_sector_rotation — stub (implement in Phase 3)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_run_thesis_matching")
def task_run_thesis_matching() -> dict:
    logger.info("task_run_thesis_matching — stub (implement in Phase 4)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_run_alert_engine")
def task_run_alert_engine() -> dict:
    logger.info("task_run_alert_engine — stub (implement in Phase 4)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_compute_dip_scores")
def task_compute_dip_scores() -> dict:
    logger.info("task_compute_dip_scores — stub (implement in Phase 4)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_check_snoozed_alerts")
def task_check_snoozed_alerts() -> dict:
    logger.info("task_check_snoozed_alerts — stub (implement in Phase 4)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_send_daily_briefing")
def task_send_daily_briefing() -> dict:
    logger.info("task_send_daily_briefing — stub (implement in Phase 4)")
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_send_weekly_digest")
def task_send_weekly_digest() -> dict:
    logger.info("task_send_weekly_digest — stub (implement in Phase 4)")
    return {"status": "stub"}
