"""
EdgeFinder — Signal Ranker Training Data Extraction

Joins ``simulated_theses`` with ``backtest_runs`` to produce labelled training
data for the signal ranker XGBoost classifier.

Label logic:
    1 if the best (max) Sharpe ratio across all backtest runs for a thesis > 0
    0 otherwise

Only theses that have completed the backtest lifecycle (PAPER_LIVE or KILLED)
and have a non-NULL ``generation_context`` are included.
"""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import BacktestRun, SimulatedThesis, ThesisStatus
from ml.feature_engineering import extract_convergence_features

logger = logging.getLogger(__name__)

# Thesis statuses that indicate the backtest lifecycle is complete
_TERMINAL_STATUSES = (
    ThesisStatus.PAPER_LIVE.value,
    ThesisStatus.KILLED.value,
)


async def extract_signal_ranker_training_data(
    session: AsyncSession,
) -> pd.DataFrame:
    """Build a labelled DataFrame for training the signal ranker.

    Each row corresponds to one SimulatedThesis that has:
      - a non-NULL ``generation_context``
      - a terminal status (PAPER_LIVE or KILLED)
      - at least one associated BacktestRun

    Columns:
      - All features from :func:`extract_convergence_features`
      - ``label``: 1 if best Sharpe > 0, else 0
      - ``thesis_id``: for diagnostics / debugging (not a training feature)
      - ``best_sharpe``: the raw max Sharpe value (not a training feature)

    Rows are ordered by ``thesis.id`` ascending (creation order) so a simple
    positional split preserves temporal ordering.

    Returns
    -------
    pd.DataFrame
        Empty DataFrame (with correct columns) when no qualifying data exists.
    """

    # Subquery: best Sharpe per thesis
    best_sharpe_sq = (
        select(
            BacktestRun.thesis_id,
            func.max(BacktestRun.sharpe).label("best_sharpe"),
        )
        .where(BacktestRun.sharpe.is_not(None))
        .group_by(BacktestRun.thesis_id)
        .subquery("best_sharpe")
    )

    # Main query: join theses with their best Sharpe
    stmt = (
        select(
            SimulatedThesis.id.label("thesis_id"),
            SimulatedThesis.generation_context,
            best_sharpe_sq.c.best_sharpe,
        )
        .join(
            best_sharpe_sq,
            SimulatedThesis.id == best_sharpe_sq.c.thesis_id,
        )
        .where(
            SimulatedThesis.generation_context.is_not(None),
            SimulatedThesis.status.in_(_TERMINAL_STATUSES),
        )
        .order_by(SimulatedThesis.id.asc())
    )

    result = await session.execute(stmt)
    rows = result.all()

    if not rows:
        logger.warning(
            "No qualifying theses for signal ranker training "
            "(need PAPER_LIVE/KILLED with generation_context + backtest runs)"
        )
        # Return empty DataFrame with expected columns
        sample_features = extract_convergence_features({})
        columns = list(sample_features.keys()) + ["label", "thesis_id", "best_sharpe"]
        return pd.DataFrame(columns=columns)

    records: list[dict] = []
    for thesis_id, gen_ctx, best_sharpe in rows:
        features = extract_convergence_features(gen_ctx)
        features["label"] = 1.0 if best_sharpe > 0 else 0.0
        features["thesis_id"] = float(thesis_id)
        features["best_sharpe"] = float(best_sharpe)
        records.append(features)

    df = pd.DataFrame(records)
    n_positive = int(df["label"].sum())
    n_total = len(df)
    logger.info(
        "Extracted %d labelled theses for signal ranker: %d positive (%.1f%%), %d negative",
        n_total,
        n_positive,
        100 * n_positive / n_total if n_total else 0,
        n_total - n_positive,
    )
    return df
