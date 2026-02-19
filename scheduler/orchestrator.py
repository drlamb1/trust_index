"""
EdgeFinder — Pipeline Orchestrator

DAG-style pipeline helpers using Celery chains and chords.
Allows composing multi-step pipelines with fan-out/fan-in patterns.

Usage:
    from scheduler.orchestrator import run_daily_pipeline
    run_daily_pipeline()  # fires off the full EOD processing chain
"""

from __future__ import annotations

import logging

from celery import chain
from celery.result import AsyncResult

from scheduler.tasks import (
    celery_app,
    task_compute_technicals_batch,
    task_detect_anomalies,
    task_fetch_eod_prices,
    task_run_alert_engine,
    task_sync_sp500,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline builders
# ---------------------------------------------------------------------------


def run_daily_eod_pipeline() -> AsyncResult:
    """
    Full EOD processing pipeline:
    1. Fetch EOD prices for all tickers
    2. Compute technical indicators (depends on step 1)
    3. Detect anomalies (depends on step 2)
    4. Run alert engine (depends on step 3)

    Each step only starts after the previous completes successfully.
    """
    pipeline = chain(
        task_fetch_eod_prices.si(),
        task_compute_technicals_batch.si(),
        task_detect_anomalies.si(),
        task_run_alert_engine.si(),
    )
    result = pipeline.apply_async()
    logger.info("Daily EOD pipeline started: %s", result.id)
    return result


def run_weekly_maintenance() -> AsyncResult:
    """
    Weekly maintenance pipeline:
    - Sync S&P 500 constituent list
    """
    pipeline = chain(
        task_sync_sp500.si(),
    )
    result = pipeline.apply_async()
    logger.info("Weekly maintenance pipeline started: %s", result.id)
    return result


# ---------------------------------------------------------------------------
# Manual trigger helpers (for CLI and testing)
# ---------------------------------------------------------------------------


def trigger_price_fetch_for_tickers(ticker_ids: list[int], days: int = 30) -> list[AsyncResult]:
    """Trigger price fetch for a specific set of tickers in parallel."""
    from scheduler.tasks import task_fetch_prices

    tasks = [task_fetch_prices.apply_async(args=[ticker_id, days]) for ticker_id in ticker_ids]
    logger.info("Triggered price fetch for %d tickers", len(ticker_ids))
    return tasks


def trigger_technicals_for_tickers(ticker_ids: list[int]) -> list[AsyncResult]:
    """Trigger technical indicator computation for specific tickers."""
    from scheduler.tasks import task_compute_technicals

    tasks = [task_compute_technicals.apply_async(args=[ticker_id]) for ticker_id in ticker_ids]
    logger.info("Triggered technicals computation for %d tickers", len(ticker_ids))
    return tasks


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def get_task_status(task_id: str) -> dict:
    """Get the status of a Celery task by ID."""
    result = AsyncResult(task_id, app=celery_app)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }
