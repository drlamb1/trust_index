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
        "scheduler.tasks.task_fetch_macro_data": {"queue": "ingestion"},
        "scheduler.tasks.task_fetch_transcripts": {"queue": "ingestion"},
        "scheduler.tasks.task_analyze_transcripts": {"queue": "analysis"},
        "scheduler.tasks.task_run_alert_engine": {"queue": "alerts"},
        "scheduler.tasks.task_compute_dip_scores": {"queue": "alerts"},
        "scheduler.tasks.task_check_snoozed_alerts": {"queue": "alerts"},
        "scheduler.tasks.task_send_daily_briefing": {"queue": "delivery"},
        "scheduler.tasks.task_send_weekly_digest": {"queue": "delivery"},
        # Simulation queue
        "scheduler.tasks.task_fetch_options_chains": {"queue": "ingestion"},
        "scheduler.tasks.task_calibrate_heston_batch": {"queue": "simulation"},
        "scheduler.tasks.task_build_vol_surfaces": {"queue": "simulation"},
        "scheduler.tasks.task_generate_theses": {"queue": "simulation"},
        "scheduler.tasks.task_backtest_thesis": {"queue": "simulation"},
        "scheduler.tasks.task_paper_portfolio_mark": {"queue": "simulation"},
        "scheduler.tasks.task_check_paper_stops": {"queue": "simulation"},
        "scheduler.tasks.task_thesis_lifecycle_review": {"queue": "simulation"},
        "scheduler.tasks.task_agent_memory_consolidation": {"queue": "simulation"},
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
        "options": {"queue": "ingestion"},
    },
    # EOD price confirmation — 9 PM UTC (4 PM EST) Mon-Fri
    "fetch-eod-prices": {
        "task": "scheduler.tasks.task_fetch_eod_prices",
        "schedule": crontab(minute=0, hour=21, day_of_week="1-5"),
        "options": {"queue": "ingestion"},
    },
    # S&P 500 constituent sync — weekly on Sunday at 6 AM UTC
    "sync-sp500": {
        "task": "scheduler.tasks.task_sync_sp500",
        "schedule": crontab(minute=0, hour=6, day_of_week=0),
        "options": {"queue": "ingestion"},
    },
    # EDGAR new filings check — every 2 hours Mon-Fri during trading hours
    "fetch-new-filings": {
        "task": "scheduler.tasks.task_fetch_new_filings",
        "schedule": crontab(minute=0, hour="*/2", day_of_week="1-5"),
        "options": {"queue": "ingestion"},
    },
    # News aggregation — every 30 minutes (all week)
    "aggregate-news": {
        "task": "scheduler.tasks.task_aggregate_news",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "ingestion"},
    },
    # Insider trades (Form 4) — twice daily Mon-Fri
    "fetch-insider-trades": {
        "task": "scheduler.tasks.task_fetch_insider_trades",
        "schedule": crontab(minute=0, hour="8,17", day_of_week="1-5"),
        "options": {"queue": "ingestion"},
    },
    # 13F institutional holdings — Monday 7 AM UTC (quarterly filings but check weekly)
    "fetch-institutional": {
        "task": "scheduler.tasks.task_fetch_institutional",
        "schedule": crontab(minute=0, hour=7, day_of_week=1),
        "options": {"queue": "ingestion"},
    },
    # Earnings calendar sync — daily at 6 AM UTC
    "sync-earnings-calendar": {
        "task": "scheduler.tasks.task_sync_earnings_calendar",
        "schedule": crontab(minute=0, hour=6),
        "options": {"queue": "ingestion"},
    },
    # FRED macro indicators — daily at 6:30 AM UTC
    "fetch-macro-data": {
        "task": "scheduler.tasks.task_fetch_macro_data",
        "schedule": crontab(minute=30, hour=6),
        "options": {"queue": "ingestion"},
    },
    # Earnings transcripts — daily at 7:30 AM UTC (after earnings calendar sync)
    "fetch-transcripts": {
        "task": "scheduler.tasks.task_fetch_transcripts",
        "schedule": crontab(minute=30, hour=7),
        "options": {"queue": "ingestion"},
    },
    # ================================================================
    # ANALYSIS QUEUE
    # ================================================================
    # Technical indicators — 35 min after EOD prices (9:35 PM UTC Mon-Fri)
    "compute-technicals-eod": {
        "task": "scheduler.tasks.task_compute_technicals_batch",
        "schedule": crontab(minute=35, hour=21, day_of_week="1-5"),
        "options": {"queue": "analysis"},
    },
    # Filing analysis — process new filings every 3 hours Mon-Fri
    "analyze-pending-filings": {
        "task": "scheduler.tasks.task_analyze_pending_filings",
        "schedule": crontab(minute=0, hour="*/3", day_of_week="1-5"),
        "options": {"queue": "analysis"},
    },
    # Batch sentiment scoring — hourly at :45 (offset from other jobs)
    "score-news-sentiment": {
        "task": "scheduler.tasks.task_run_sentiment_batch",
        "schedule": crontab(minute=45, hour="*"),
        "options": {"queue": "analysis"},
    },
    # Anomaly detection — 45 min after EOD (9:45 PM UTC Mon-Fri)
    "detect-anomalies": {
        "task": "scheduler.tasks.task_detect_anomalies",
        "schedule": crontab(minute=45, hour=21, day_of_week="1-5"),
        "options": {"queue": "analysis"},
    },
    # Sector rotation — 10 PM UTC Mon-Fri (after technicals complete)
    "compute-sector-rotation": {
        "task": "scheduler.tasks.task_compute_sector_rotation",
        "schedule": crontab(minute=0, hour=22, day_of_week="1-5"),
        "options": {"queue": "analysis"},
    },
    # Thesis matching — 10:30 PM UTC daily
    "match-theses": {
        "task": "scheduler.tasks.task_run_thesis_matching",
        "schedule": crontab(minute=30, hour=22),
        "options": {"queue": "analysis"},
    },
    # Earnings transcript analysis — 11 PM UTC daily (after transcripts fetched)
    "analyze-transcripts": {
        "task": "scheduler.tasks.task_analyze_transcripts",
        "schedule": crontab(minute=0, hour=23),
        "options": {"queue": "analysis"},
    },
    # Neon DB keepalive — every 3 minutes during market hours to prevent cold starts
    # Neon free tier pauses after 5 min of inactivity
    "db-keepalive": {
        "task": "scheduler.tasks.task_db_keepalive",
        "schedule": crontab(minute="*/3", hour="13-22", day_of_week="1-5"),
        "options": {"queue": "analysis"},
    },
    # ================================================================
    # ALERTS QUEUE
    # ================================================================
    # Alert engine — every 15 min Mon-Fri 2-10 PM UTC (market hours + post-market)
    "run-alert-engine": {
        "task": "scheduler.tasks.task_run_alert_engine",
        "schedule": crontab(minute="*/15", hour="14-22", day_of_week="1-5"),
        "options": {"queue": "alerts"},
    },
    # DipScore computation — every 30 min during market hours
    "compute-dip-scores": {
        "task": "scheduler.tasks.task_compute_dip_scores",
        "schedule": crontab(minute="*/30", hour="14-21", day_of_week="1-5"),
        "options": {"queue": "alerts"},
    },
    # Snoozed alert expiry — every 5 minutes
    "check-snoozed-alerts": {
        "task": "scheduler.tasks.task_check_snoozed_alerts",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "alerts"},
    },
    # ================================================================
    # DELIVERY QUEUE
    # ================================================================
    # Daily briefing — 7 AM UTC (2 AM EST, before pre-market opens)
    "send-daily-briefing": {
        "task": "scheduler.tasks.task_send_daily_briefing",
        "schedule": crontab(minute=0, hour=7),
        "options": {"queue": "delivery"},
    },
    # Weekly digest — Sunday 8 PM UTC
    "send-weekly-digest": {
        "task": "scheduler.tasks.task_send_weekly_digest",
        "schedule": crontab(minute=0, hour=20, day_of_week=0),
        "options": {"queue": "delivery"},
    },
    # ================================================================
    # SIMULATION QUEUE — thesis lifecycle, vol modeling, paper portfolio
    # All P&L is play-money. Zero real capital.
    # ================================================================
    # Options chain fetch — daily after EOD prices (9:15 PM UTC Mon-Fri)
    "fetch-options-chains": {
        "task": "scheduler.tasks.task_fetch_options_chains",
        "schedule": crontab(minute=15, hour=21, day_of_week="1-5"),
        "options": {"queue": "ingestion"},
    },
    # Heston calibration — daily after options data (9:30 PM UTC Mon-Fri)
    "calibrate-heston-batch": {
        "task": "scheduler.tasks.task_calibrate_heston_batch",
        "schedule": crontab(minute=30, hour=21, day_of_week="1-5"),
        "options": {"queue": "simulation"},
    },
    # Vol surface construction — daily after calibration (9:45 PM UTC Mon-Fri)
    "build-vol-surfaces": {
        "task": "scheduler.tasks.task_build_vol_surfaces",
        "schedule": crontab(minute=45, hour=21, day_of_week="1-5"),
        "options": {"queue": "simulation"},
    },
    # Thesis generation — every 6 hours (0, 6, 12, 18 UTC)
    "generate-theses": {
        "task": "scheduler.tasks.task_generate_theses",
        "schedule": crontab(minute=0, hour="0,6,12,18"),
        "options": {"queue": "simulation"},
    },
    # Paper portfolio mark-to-market — daily at 10 PM UTC
    "paper-portfolio-mark": {
        "task": "scheduler.tasks.task_paper_portfolio_mark",
        "schedule": crontab(minute=0, hour=22, day_of_week="1-5"),
        "options": {"queue": "simulation"},
    },
    # Paper stop-loss/take-profit checks — every 15 min during market hours
    "check-paper-stops": {
        "task": "scheduler.tasks.task_check_paper_stops",
        "schedule": crontab(minute="*/15", hour="14-21", day_of_week="1-5"),
        "options": {"queue": "simulation"},
    },
    # Thesis lifecycle review — daily at 11 PM UTC
    "thesis-lifecycle-review": {
        "task": "scheduler.tasks.task_thesis_lifecycle_review",
        "schedule": crontab(minute=0, hour=23),
        "options": {"queue": "simulation"},
    },
    # Agent memory consolidation — Sundays 10 PM UTC
    "agent-memory-consolidation": {
        "task": "scheduler.tasks.task_agent_memory_consolidation",
        "schedule": crontab(minute=0, hour=22, day_of_week=0),
        "options": {"queue": "simulation"},
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
def task_fetch_new_filings(limit_per_ticker: int = 3) -> dict:
    """Fetch recent EDGAR filings (10-K, 10-Q, 8-K) for all tickers with a CIK."""

    async def _run():
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.sec_edgar import fetch_filings_for_ticker

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True), Ticker.cik.isnot(None))
            )
            tickers = result.scalars().all()

            total = 0
            for ticker in tickers:
                filings = await fetch_filings_for_ticker(
                    session, ticker, filing_types=["10-K", "10-Q", "8-K"], limit=limit_per_ticker
                )
                total += len(filings)

            await session.commit()
            return {"tickers_processed": len(tickers), "filings_fetched": total}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_fetch_new_filings failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_aggregate_news")
def task_aggregate_news(days: int = 7) -> dict:
    """Aggregate news from RSS, Finnhub, and NewsAPI for all active tickers."""

    async def _run():
        from sqlalchemy import select

        from config.settings import settings
        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.news_feed import aggregate_news_batch

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Ticker).where(Ticker.is_active.is_(True)))
            tickers = list(result.scalars().all())

            finnhub_key = settings.finnhub_api_key if settings.has_finnhub else ""
            newsapi_key = getattr(settings, "news_api_key", "")

            total = await aggregate_news_batch(
                session,
                tickers=tickers,
                finnhub_api_key=finnhub_key,
                newsapi_key=newsapi_key,
                days=days,
            )
            await session.commit()
            return {"tickers_processed": len(tickers), "articles_inserted": total}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_aggregate_news failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_fetch_insider_trades")
def task_fetch_insider_trades(limit_per_ticker: int = 20) -> dict:
    """Fetch Form 4 insider trades for all watchlist tickers."""

    async def _run():
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.insider_trades import fetch_and_store_insider_trades
        from ingestion.sec_edgar import update_ticker_cik

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True), Ticker.in_watchlist.is_(True))
            )
            tickers = result.scalars().all()

            total = 0
            for ticker in tickers:
                if not ticker.cik:
                    await update_ticker_cik(session, ticker)
                    if not ticker.cik:
                        continue
                count = await fetch_and_store_insider_trades(
                    session, ticker, limit=limit_per_ticker
                )
                total += count

            await session.commit()
            return {"tickers_processed": len(tickers), "trades_stored": total}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_fetch_insider_trades failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_fetch_institutional")
def task_fetch_institutional() -> dict:
    logger.info(
        "task_fetch_institutional — stub (implement in Phase 2: requires institution CIK list)"
    )
    return {"status": "stub"}


@celery_app.task(name="scheduler.tasks.task_sync_earnings_calendar")
def task_sync_earnings_calendar(lookahead_days: int = 30, lookback_days: int = 7) -> dict:
    """Fetch earnings calendar and persist events to DB."""

    async def _run():
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from config.settings import settings
        from core.database import AsyncSessionLocal
        from core.models import EarningsEventDB, Ticker
        from ingestion.earnings_calendar import fetch_earnings_for_tickers

        if not settings.has_finnhub:
            return {"status": "skipped", "reason": "no Finnhub API key"}

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True))
            )
            tickers = result.scalars().all()
            symbol_to_id = {t.symbol.upper(): t.id for t in tickers}
            symbols = list(symbol_to_id.keys())

        calendar = await fetch_earnings_for_tickers(
            symbols=symbols,
            api_key=settings.finnhub_api_key,
            lookback_days=lookback_days,
            lookahead_days=lookahead_days,
        )

        # Persist events to DB
        stored = 0
        async with AsyncSessionLocal() as session:
            for event in calendar.events:
                ticker_id = symbol_to_id.get(event.symbol.upper())
                if not ticker_id:
                    continue

                row = {
                    "ticker_id": ticker_id,
                    "event_date": event.date.date() if hasattr(event.date, "date") else event.date,
                    "hour": event.hour or "",
                    "eps_estimate": event.eps_estimate,
                    "eps_actual": event.eps_actual,
                    "revenue_estimate": event.revenue_estimate,
                    "revenue_actual": event.revenue_actual,
                    "source": "finnhub",
                }

                # Compute surprise percentages for events with actuals
                if event.eps_surprise_pct is not None:
                    row["eps_surprise_pct"] = round(event.eps_surprise_pct, 2)
                if event.revenue_surprise_pct is not None:
                    row["rev_surprise_pct"] = round(event.revenue_surprise_pct, 2)

                stmt = pg_insert(EarningsEventDB).values(row)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_earnings_ticker_date",
                    set_={
                        "eps_actual": stmt.excluded.eps_actual,
                        "revenue_actual": stmt.excluded.revenue_actual,
                        "eps_surprise_pct": stmt.excluded.eps_surprise_pct,
                        "rev_surprise_pct": stmt.excluded.rev_surprise_pct,
                    },
                )
                await session.execute(stmt)
                stored += 1

            await session.commit()

        upcoming = calendar.upcoming(days=lookahead_days)
        return {
            "total_events": len(calendar.events),
            "persisted": stored,
            "upcoming_7d": len(calendar.upcoming(days=7)),
            "symbols_with_earnings": [e.symbol for e in upcoming[:20]],
        }

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_sync_earnings_calendar failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_analyze_pending_filings")
def task_analyze_pending_filings(limit: int = 20) -> dict:
    """Run filing analyzer (Stage 1 regex + optional Stage 2 Claude) on pending filings."""

    async def _run():
        from analysis.filing_analyzer import analyze_pending_filings
        from config.settings import settings
        from core.database import AsyncSessionLocal

        api_key = settings.anthropic_api_key if settings.has_anthropic else None

        async with AsyncSessionLocal() as session:
            count = await analyze_pending_filings(session, anthropic_api_key=api_key, limit=limit)
            await session.commit()
            return {"filings_analyzed": count}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_analyze_pending_filings failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_run_sentiment_batch")
def task_run_sentiment_batch(limit: int = 500) -> dict:
    """Score unscored news articles using Claude Haiku Batches API."""

    async def _run():
        from analysis.sentiment import run_sentiment_pipeline
        from config.settings import settings
        from core.database import AsyncSessionLocal

        if not settings.has_anthropic:
            return {"status": "skipped", "reason": "no Anthropic API key"}

        async with AsyncSessionLocal() as session:
            scored = await run_sentiment_pipeline(
                session,
                api_key=settings.anthropic_api_key,
                limit=limit,
                use_batches=True,
            )
            await session.commit()
            return {"articles_scored": scored}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_run_sentiment_batch failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_detect_anomalies")
def task_detect_anomalies(lookback_days: int = 60) -> dict:
    """Run price/volume anomaly detection for all active tickers."""

    async def _run():
        from datetime import date, timedelta

        import pandas as pd
        from sqlalchemy import select

        from analysis.anomaly_detector import scan_and_store
        from core.database import AsyncSessionLocal
        from core.models import PriceBar, Ticker

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Ticker).where(Ticker.is_active.is_(True)))
            tickers = list(result.scalars().all())

            cutoff = date.today() - timedelta(days=lookback_days)
            total_alerts = 0

            for ticker in tickers:
                bars_result = await session.execute(
                    select(PriceBar)
                    .where(PriceBar.ticker_id == ticker.id, PriceBar.date >= cutoff)
                    .order_by(PriceBar.date.asc())
                )
                bars = bars_result.scalars().all()
                if len(bars) < 5:
                    continue

                df = pd.DataFrame(
                    [
                        {
                            "date": b.date,
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                        }
                        for b in bars
                    ]
                )
                count = await scan_and_store(session, ticker, df)
                total_alerts += count

            await session.commit()
            return {"tickers_scanned": len(tickers), "alerts_created": total_alerts}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_detect_anomalies failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_compute_sector_rotation")
def task_compute_sector_rotation() -> dict:
    """Compute SPDR sector ETF relative strength and detect market regime."""

    async def _run():
        from analysis.sector_rotation import build_sector_snapshot, fetch_sector_prices

        price_dfs = await fetch_sector_prices(lookback_days=300)
        if not price_dfs:
            return {"status": "error", "reason": "no price data fetched"}

        spy_df = price_dfs.pop("SPY", None)
        snapshot = build_sector_snapshot(price_dfs, spy_df=spy_df)

        return {
            "regime": snapshot.regime,
            "top_3_sectors": [s.symbol for s in snapshot.ranked[:3]],
            "bottom_3_sectors": [s.symbol for s in snapshot.ranked[-3:]],
            "spy_return_20d": snapshot.spy_return_20d,
        }

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_compute_sector_rotation failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_run_thesis_matching")
def task_run_thesis_matching() -> dict:
    """Run investment thesis matching for all active theses and tickers."""

    async def _run():
        from analysis.thesis_matcher import run_thesis_matching
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            total = await run_thesis_matching(session)
            return {"matches_upserted": total}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_run_thesis_matching failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_fetch_macro_data")
def task_fetch_macro_data(days: int = 365) -> dict:
    """Fetch FRED macroeconomic indicators and store to DB."""

    async def _run():
        from config.settings import settings
        from core.database import AsyncSessionLocal
        from ingestion.macro_data import fetch_and_store_macro

        if not settings.has_fred:
            return {"status": "skipped", "reason": "no FRED API key"}

        async with AsyncSessionLocal() as session:
            results = await fetch_and_store_macro(session, settings.fred_api_key, days=days)
            await session.commit()
            return {
                "series": results,
                "total_observations": sum(results.values()),
            }

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_fetch_macro_data failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_fetch_transcripts")
def task_fetch_transcripts(quarters_back: int = 1) -> dict:
    """Fetch earnings call transcripts (Motley Fool + FMP fallback) for watchlist tickers."""

    async def _run():
        from sqlalchemy import select

        from config.settings import settings
        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.earnings_transcripts import (
            discover_and_store_from_sitemap,
            fetch_and_store_transcripts_batch,
        )

        fmp_key = settings.fmp_api_key if settings.has_fmp else ""

        async with AsyncSessionLocal() as session:
            # First: check Motley Fool sitemap for any new transcripts
            sitemap_count = await discover_and_store_from_sitemap(session, fmp_key)

            # Then: targeted fetch for watchlist tickers
            result = await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True), Ticker.in_watchlist.is_(True))
            )
            tickers = list(result.scalars().all())

            results = await fetch_and_store_transcripts_batch(
                session, tickers, fmp_api_key=fmp_key, quarters_back=quarters_back
            )
            await session.commit()
            return {
                "tickers_processed": len(tickers),
                "sitemap_discovered": sitemap_count,
                "transcripts_per_ticker": results,
                "total_new": sitemap_count + sum(results.values()),
            }

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_fetch_transcripts failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_analyze_transcripts")
def task_analyze_transcripts() -> dict:
    """Analyze unprocessed earnings call transcripts with Claude."""

    async def _run():
        from analysis.earnings_analyzer import analyze_unprocessed
        from config.settings import settings
        from core.database import AsyncSessionLocal

        if not settings.has_anthropic:
            return {"status": "skipped", "reason": "no Anthropic API key"}

        async with AsyncSessionLocal() as session:
            count = await analyze_unprocessed(session, settings.anthropic_api_key)
            await session.commit()
            return {"transcripts_analyzed": count}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_analyze_transcripts failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_run_alert_engine")
def task_run_alert_engine() -> dict:
    """Run rule-based alert engine for all watchlist tickers."""

    async def _run():
        from alerts.alert_engine import run_alert_engine
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            created = await run_alert_engine(session)
            await session.commit()
            return {"alerts_created": created}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_run_alert_engine failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_compute_dip_scores")
def task_compute_dip_scores() -> dict:
    """Score all watchlist tickers for buy-the-dip opportunities."""

    async def _run():
        from alerts.buy_the_dip import compute_dip_scores
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            created = await compute_dip_scores(session)
            await session.commit()
            return {"alerts_created": created}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_compute_dip_scores failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_check_snoozed_alerts")
def task_check_snoozed_alerts() -> dict:
    """Expire snoozed alerts whose snooze window has passed."""

    async def _run():
        from datetime import datetime, timezone

        from sqlalchemy import update

        from core.database import AsyncSessionLocal
        from core.models import Alert

        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                update(Alert)
                .where(Alert.snoozed_until <= now, Alert.dismissed_at.is_(None))
                .values(snoozed_until=None)
                .returning(Alert.id)
            )
            expired = len(result.fetchall())
            await session.commit()
            return {"snoozed_expired": expired}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_check_snoozed_alerts failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_send_daily_briefing")
def task_send_daily_briefing() -> dict:
    """Generate and deliver the daily market briefing."""

    async def _run():
        from core.database import AsyncSessionLocal
        from daily_briefing import generate_and_send_briefing

        async with AsyncSessionLocal() as session:
            result = await generate_and_send_briefing(
                session, dry_run=False, is_weekly=False
            )
            return {
                "date": result.get("date"),
                "delivered": result.get("delivery_results", {}),
                "chars": len(result.get("content_md", "")),
            }

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_send_daily_briefing failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_send_weekly_digest")
def task_send_weekly_digest() -> dict:
    """Generate and deliver the weekly digest briefing."""

    async def _run():
        from core.database import AsyncSessionLocal
        from daily_briefing import generate_and_send_briefing

        async with AsyncSessionLocal() as session:
            result = await generate_and_send_briefing(
                session, dry_run=False, is_weekly=True
            )
            return {
                "date": result.get("date"),
                "delivered": result.get("delivery_results", {}),
                "chars": len(result.get("content_md", "")),
            }

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_send_weekly_digest failed: %s", exc)
        raise


# =========================================================================
# SIMULATION ENGINE TASKS
# All P&L is simulated play-money. Zero real capital at risk.
# =========================================================================


@celery_app.task(name="scheduler.tasks.task_fetch_options_chains", bind=True, max_retries=2)
def task_fetch_options_chains(self) -> dict:
    """Fetch options chain data for all watchlist tickers."""

    async def _run():
        from core.database import AsyncSessionLocal
        from ingestion.options_data import fetch_options_batch

        async with AsyncSessionLocal() as session:
            result = await fetch_options_batch(session)
            await session.commit()
            return result

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_fetch_options_chains failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


@celery_app.task(name="scheduler.tasks.task_calibrate_heston_batch", bind=True, max_retries=1)
def task_calibrate_heston_batch(self) -> dict:
    """Calibrate Heston model for tickers with options data."""

    async def _run():
        from datetime import date as date_type

        from sqlalchemy import func, select

        from core.database import AsyncSessionLocal
        from core.models import HestonCalibration, OptionsChain, PriceBar, Ticker
        from simulation.heston import HestonParams, calibrate_heston

        async with AsyncSessionLocal() as session:
            # Find tickers with recent options data
            result = await session.execute(
                select(Ticker).where(Ticker.in_watchlist.is_(True), Ticker.is_active.is_(True))
            )
            tickers = result.scalars().all()
            calibrated = 0

            for ticker in tickers:
                try:
                    # Get latest options chain
                    opts_result = await session.execute(
                        select(OptionsChain).where(
                            OptionsChain.ticker_id == ticker.id,
                            OptionsChain.implied_vol.isnot(None),
                            OptionsChain.implied_vol > 0,
                        ).order_by(OptionsChain.fetched_at.desc()).limit(200)
                    )
                    options = opts_result.scalars().all()
                    if len(options) < 10:
                        continue

                    # Get current price
                    price_result = await session.execute(
                        select(PriceBar.close).where(
                            PriceBar.ticker_id == ticker.id
                        ).order_by(PriceBar.date.desc()).limit(1)
                    )
                    S = price_result.scalar_one_or_none()
                    if S is None:
                        continue

                    import numpy as np
                    strikes = np.array([float(o.strike) for o in options])
                    ivs = np.array([float(o.implied_vol) for o in options])
                    today = date_type.today()
                    expiries = np.array([(o.expiration - today).days / 365.0 for o in options])
                    expiries = np.maximum(expiries, 0.01)

                    params, rmse = calibrate_heston(ivs, strikes, expiries, float(S), 0.05)

                    cal = HestonCalibration(
                        ticker_id=ticker.id,
                        as_of=today,
                        v0=params.v0,
                        kappa=params.kappa,
                        theta=params.theta,
                        sigma_v=params.sigma_v,
                        rho=params.rho,
                        calibration_error=rmse,
                        market_iv_snapshot={"count": len(options), "mean_iv": float(np.mean(ivs))},
                    )
                    session.add(cal)
                    calibrated += 1

                except Exception as e:
                    logger.warning("Heston calibration failed for %s: %s", ticker.symbol, e)

            await session.commit()
            return {"calibrated": calibrated}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_calibrate_heston_batch failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)


@celery_app.task(name="scheduler.tasks.task_build_vol_surfaces")
def task_build_vol_surfaces() -> dict:
    """Build vol surfaces from options data for watchlist tickers."""

    async def _run():
        from datetime import date as date_type

        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import OptionsChain, PriceBar, Ticker, VolSurface

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Ticker).where(Ticker.in_watchlist.is_(True), Ticker.is_active.is_(True))
            )
            tickers = result.scalars().all()
            built = 0

            for ticker in tickers:
                try:
                    opts_result = await session.execute(
                        select(OptionsChain).where(
                            OptionsChain.ticker_id == ticker.id,
                        ).order_by(OptionsChain.fetched_at.desc()).limit(500)
                    )
                    options = opts_result.scalars().all()
                    if len(options) < 10:
                        continue

                    from simulation.vol_surface import build_iv_surface, surface_to_grid
                    import pandas as pd

                    today = date_type.today()
                    df = pd.DataFrame([{
                        "strike": float(o.strike),
                        "expiry_years": max((o.expiration - today).days / 365.0, 0.01),
                        "call_put": o.call_put,
                        "bid": o.bid or 0,
                        "ask": o.ask or 0,
                        "volume": o.volume or 0,
                        "open_interest": o.open_interest or 0,
                        "implied_vol": o.implied_vol,
                    } for o in options])

                    price_result = await session.execute(
                        select(PriceBar.close).where(
                            PriceBar.ticker_id == ticker.id
                        ).order_by(PriceBar.date.desc()).limit(1)
                    )
                    S = price_result.scalar_one_or_none()
                    if S is None:
                        continue

                    surface_df = build_iv_surface(df, float(S), 0.05)
                    if surface_df.empty:
                        continue

                    grid = surface_to_grid(surface_df)

                    vol_surface = VolSurface(
                        ticker_id=ticker.id,
                        as_of=today,
                        surface_data=grid,
                        model_type="svi",
                        calibration_error=None,
                    )
                    session.add(vol_surface)
                    built += 1

                except Exception as e:
                    logger.warning("Vol surface build failed for %s: %s", ticker.symbol, e)

            await session.commit()
            return {"surfaces_built": built}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_build_vol_surfaces failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_generate_theses")
def task_generate_theses() -> dict:
    """Detect signal convergences and generate new theses."""

    async def _run():
        from config.settings import settings
        from core.database import AsyncSessionLocal
        from simulation.thesis_generator import detect_signal_convergence, generate_thesis

        if not settings.has_anthropic:
            return {"skipped": "No Anthropic API key"}

        async with AsyncSessionLocal() as session:
            convergences = await detect_signal_convergence(session)
            generated = 0

            for conv in convergences[:3]:  # max 3 new theses per cycle
                thesis = await generate_thesis(session, conv, settings.anthropic_api_key)
                if thesis:
                    generated += 1

            await session.commit()
            return {"convergences_found": len(convergences), "theses_generated": generated}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_generate_theses failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_backtest_thesis", bind=True, max_retries=1)
def task_backtest_thesis(self, thesis_id: int, ticker_id: int) -> dict:
    """Run a walk-forward backtest for a specific thesis."""

    async def _run():
        from datetime import date as date_type, timedelta

        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import SimulatedThesis
        from simulation.backtester import BacktestConfig, run_backtest

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SimulatedThesis).where(SimulatedThesis.id == thesis_id)
            )
            thesis = result.scalar_one_or_none()
            if thesis is None:
                return {"error": f"Thesis {thesis_id} not found"}

            config = BacktestConfig(
                start_date=date_type.today() - timedelta(days=365),
                end_date=date_type.today(),
            )

            backtest_run = await run_backtest(session, thesis, ticker_id, config)
            await session.commit()

            return {
                "thesis_id": thesis_id,
                "ticker_id": ticker_id,
                "sharpe": backtest_run.sharpe,
                "sortino": backtest_run.sortino,
                "max_drawdown": backtest_run.max_drawdown,
                "total_trades": backtest_run.total_trades,
                "monte_carlo_p_value": backtest_run.monte_carlo_p_value,
            }

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_backtest_thesis failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="scheduler.tasks.task_paper_portfolio_mark")
def task_paper_portfolio_mark() -> dict:
    """Daily mark-to-market of the paper portfolio."""

    async def _run():
        from core.database import AsyncSessionLocal
        from simulation.paper_portfolio import daily_mark_to_market, get_or_create_portfolio

        async with AsyncSessionLocal() as session:
            portfolio = await get_or_create_portfolio(session)
            result = await daily_mark_to_market(session, portfolio)
            await session.commit()
            return result

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_paper_portfolio_mark failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_check_paper_stops")
def task_check_paper_stops() -> dict:
    """Check paper positions for stop-loss/take-profit triggers."""

    async def _run():
        from core.database import AsyncSessionLocal
        from simulation.paper_portfolio import check_stops, get_or_create_portfolio

        async with AsyncSessionLocal() as session:
            portfolio = await get_or_create_portfolio(session)
            closed = await check_stops(session, portfolio)
            await session.commit()
            return {"positions_closed": len(closed)}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_check_paper_stops failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_thesis_lifecycle_review")
def task_thesis_lifecycle_review() -> dict:
    """Daily review of live theses — flag underperformers for mutation/retirement."""

    async def _run():
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import SimulatedThesis, ThesisStatus
        from simulation.thesis_generator import retire_thesis

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SimulatedThesis).where(
                    SimulatedThesis.status == ThesisStatus.PAPER_LIVE.value
                )
            )
            live_theses = result.scalars().all()
            reviewed = 0
            retired = 0

            for thesis in live_theses:
                reviewed += 1
                # Check time horizon expiry
                if thesis.time_horizon_days and thesis.created_at:
                    horizon_end = thesis.created_at + timedelta(days=thesis.time_horizon_days)
                    if datetime.now(timezone.utc) > horizon_end:
                        await retire_thesis(
                            session, thesis.id,
                            reason="Time horizon expired",
                            agent_name="lifecycle_review",
                        )
                        retired += 1

            await session.commit()
            return {"reviewed": reviewed, "retired": retired}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_thesis_lifecycle_review failed: %s", exc)
        raise


@celery_app.task(name="scheduler.tasks.task_agent_memory_consolidation")
def task_agent_memory_consolidation() -> dict:
    """Weekly consolidation of agent memories from simulation log."""

    async def _run():
        from config.settings import settings
        from core.database import AsyncSessionLocal
        from simulation.memory import consolidate_memories, prune_stale_memories

        if not settings.has_anthropic:
            return {"skipped": "No Anthropic API key"}

        async with AsyncSessionLocal() as session:
            created = await consolidate_memories(session, settings.anthropic_api_key)
            pruned = await prune_stale_memories(session)
            await session.commit()
            return {"memories_created": created, "memories_pruned": pruned}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("task_agent_memory_consolidation failed: %s", exc)
        raise
