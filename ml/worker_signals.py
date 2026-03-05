"""
EdgeFinder — ML Worker Startup Signals & Status Display

Hooks into Celery worker lifecycle to:
  1. On startup: check which models are missing/stale and enqueue training
  2. During execution: print clear status lines so the user can see
     what's running and decide whether to keep the GPU busy

Usage:
    celery -A scheduler.tasks worker -Q ml_training -c 1 \
        --include=ml.worker_signals ...
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone

from celery.signals import (
    task_postrun,
    task_prerun,
    task_failure,
    worker_ready,
    worker_shutting_down,
)

logger = logging.getLogger(__name__)

# Track running tasks for status display
_TASK_START: dict[str, float] = {}

# ANSI helpers (disabled if NO_COLOR is set)
_NO_COLOR = os.environ.get("NO_COLOR", "")

def _c(code: str, text: str) -> str:
    if _NO_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def _green(t: str) -> str: return _c("32", t)
def _yellow(t: str) -> str: return _c("33", t)
def _red(t: str) -> str: return _c("31", t)
def _bold(t: str) -> str: return _c("1", t)
def _dim(t: str) -> str: return _c("2", t)

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


# Model display names
_MODEL_NAMES = {
    "scheduler.tasks.task_train_sentiment_model": "FinBERT Sentiment",
    "scheduler.tasks.task_train_signal_ranker": "XGBoost Signal Ranker",
    "scheduler.tasks.task_train_deep_hedging": "Deep Hedging Policy",
    "scheduler.tasks.task_refresh_ml_models": "Model Cache Refresh",
}


def _banner(msg: str) -> None:
    width = max(len(msg) + 4, 50)
    border = "=" * width
    print(f"\n{_bold(border)}")
    print(f"  {_bold(msg)}")
    print(f"{_bold(border)}\n", flush=True)


# ---------------------------------------------------------------------------
# Worker ready — catch-up logic
# ---------------------------------------------------------------------------

@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """Check for missing models and enqueue training on startup."""
    _banner("ML Worker Ready — Checking Model Status")

    try:
        _check_and_enqueue()
    except Exception as exc:
        print(f"  {_red('ERROR')} checking model status: {exc}")
        logger.exception("ML worker startup check failed")

    print(f"\n  {_dim('Ctrl+C to stop the worker and reclaim your GPU')}\n",
          flush=True)


def _check_and_enqueue():
    """Query ml_models table and enqueue training for anything missing."""
    import asyncio

    from core.database import AsyncSessionLocal
    from core.models import MLModel, MLModelType
    from sqlalchemy import select

    async def _query():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(MLModel.model_type, MLModel.version, MLModel.trained_at)
                .where(MLModel.is_active.is_(True))
                .order_by(MLModel.version.desc())
            )
            return {row.model_type: (row.version, row.trained_at)
                    for row in result.all()}

    # Run the async query
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                active = pool.submit(lambda: asyncio.run(_query())).result()
        else:
            active = loop.run_until_complete(_query())
    except RuntimeError:
        active = asyncio.run(_query())

    # Map model types to their training tasks
    task_map = {
        MLModelType.SENTIMENT.value: "scheduler.tasks.task_train_sentiment_model",
        MLModelType.SIGNAL_RANKER.value: "scheduler.tasks.task_train_signal_ranker",
        MLModelType.DEEP_HEDGING.value: "scheduler.tasks.task_train_deep_hedging",
    }

    missing = []
    stale = []
    current = []

    for model_type, task_name in task_map.items():
        display = _MODEL_NAMES.get(task_name, model_type)
        if model_type not in active:
            missing.append((model_type, task_name, display))
        else:
            version, trained_at = active[model_type]
            age_days = (datetime.now(timezone.utc) - trained_at).days
            if age_days > 14:
                stale.append((model_type, task_name, display, version, age_days))
            else:
                current.append((display, version, age_days))

    # Print status
    for display, version, age_days in current:
        print(f"  {_green('OK')}    {display} v{version} ({age_days}d old)")

    for model_type, task_name, display, version, age_days in stale:
        print(f"  {_yellow('STALE')} {display} v{version} ({age_days}d old) — will retrain")

    for model_type, task_name, display in missing:
        print(f"  {_red('MISS')}  {display} — never trained, will enqueue")

    # Enqueue missing + stale
    to_train = [(t, d) for _, t, d in missing] + [(t, d) for _, t, d, _, _ in stale]

    if not to_train:
        print(f"\n  {_green('All models up to date.')} Worker idle, waiting for scheduled tasks.")
        return

    print(f"\n  Enqueuing {len(to_train)} training job(s)...\n")

    from scheduler.tasks import celery_app

    for task_name, display in to_train:
        celery_app.send_task(task_name, queue="ml_training")
        print(f"  {_yellow('QUEUED')} {display}")

    print(flush=True)


# ---------------------------------------------------------------------------
# Task lifecycle — status display
# ---------------------------------------------------------------------------

@task_prerun.connect
def on_task_prerun(sender, task_id, task, args, kwargs, **kw):
    """Print when an ML task starts."""
    if not task.name.startswith("scheduler.tasks.task_train") and \
       task.name != "scheduler.tasks.task_refresh_ml_models":
        return

    display = _MODEL_NAMES.get(task.name, task.name)
    _TASK_START[task_id] = time.monotonic()

    print(f"\n  [{_now()}] {_yellow('START')} {_bold(display)}", flush=True)
    print(f"  {_dim('This may take a while. Ctrl+C to stop.')}", flush=True)


@task_postrun.connect
def on_task_postrun(sender, task_id, task, retval, state, **kw):
    """Print when an ML task finishes."""
    if not task.name.startswith("scheduler.tasks.task_train") and \
       task.name != "scheduler.tasks.task_refresh_ml_models":
        return

    display = _MODEL_NAMES.get(task.name, task.name)
    elapsed = time.monotonic() - _TASK_START.pop(task_id, time.monotonic())
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    duration = f"{minutes}m{seconds:02d}s" if minutes else f"{seconds}s"

    status = "unknown"
    detail = ""
    if isinstance(retval, dict):
        status = retval.get("status", "done")
        if status == "skipped":
            detail = f" — {retval.get('reason', '')}"
        elif status == "trained":
            metrics = retval.get("metrics", {})
            # Pull out the most interesting metric per model type
            auc = metrics.get("auc_roc")
            agreement = metrics.get("direction_agreement")
            if auc is not None:
                detail = f" — AUC {auc:.3f}"
            elif agreement is not None:
                detail = f" — direction agreement {agreement:.1%}"

    color_fn = _green if status == "trained" else (_yellow if status == "skipped" else _dim)
    print(f"  [{_now()}] {color_fn(status.upper())} {display} ({duration}){detail}",
          flush=True)

    # If nothing is left running, remind about idle
    if not _TASK_START:
        print(f"\n  {_dim('GPU idle. Ctrl+C to stop, or leave running for scheduled tasks.')}",
              flush=True)


@task_failure.connect
def on_task_failure(sender, task_id, exception, traceback, **kw):
    """Print when an ML task fails."""
    task_name = sender.name if hasattr(sender, "name") else str(sender)
    display = _MODEL_NAMES.get(task_name, task_name)
    elapsed = time.monotonic() - _TASK_START.pop(task_id, time.monotonic())

    print(f"  [{_now()}] {_red('FAIL')}  {display} after {int(elapsed)}s — {exception}",
          flush=True)


@worker_shutting_down.connect
def on_worker_shutdown(sender, **kwargs):
    """Clean goodbye."""
    running = len(_TASK_START)
    if running:
        print(f"\n  {_yellow('Shutting down with {running} task(s) still running.')}")
    print(f"\n  {_dim('ML worker stopped. GPU released.')}\n", flush=True)
