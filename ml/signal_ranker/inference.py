"""
EdgeFinder — Signal Ranker Inference

Uses the cached XGBoost signal ranker model to predict the probability
that a given convergence signal configuration will produce a positive-Sharpe
thesis.  Provides two entry points:

    predict_signal_probability(convergence)
        Returns P(positive Sharpe) for a single convergence dict, or None
        if the model is not loaded.

    rank_convergences(convergences, min_probability=0.4)
        Re-ranks a list of convergence dicts by ML probability (descending),
        filters out those below the threshold, and annotates each dict with
        an ``ml_probability`` key.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from core.models import MLModelType
from ml.feature_engineering import extract_convergence_features
from ml.model_registry import get_cached_model

logger = logging.getLogger(__name__)


def predict_signal_probability(convergence: dict) -> float | None:
    """Predict the probability that a convergence will yield positive Sharpe.

    Parameters
    ----------
    convergence:
        A convergence dict with the same structure as
        ``SimulatedThesis.generation_context`` (contains ``signals``,
        ``signal_count``, ``sector``, etc.).

    Returns
    -------
    float | None
        Probability in [0, 1], or ``None`` if the signal ranker model is
        not available in the in-memory cache.
    """
    model = get_cached_model(MLModelType.SIGNAL_RANKER.value)
    if model is None:
        logger.debug(
            "Signal ranker model not cached; returning None "
            "(model may not be trained yet)"
        )
        return None

    features = extract_convergence_features(convergence)
    feature_names = sorted(features.keys())
    X = np.array(
        [[features[k] for k in feature_names]],
        dtype=np.float32,
    )

    try:
        proba = model.predict_proba(X)[0, 1]
        return float(proba)
    except Exception:
        logger.exception("Signal ranker prediction failed")
        return None


def rank_convergences(
    convergences: list[dict],
    min_probability: float = 0.4,
) -> list[dict]:
    """Rank and filter convergence dicts by ML-predicted quality.

    Each convergence dict is annotated in-place with an ``ml_probability``
    key.  Convergences below ``min_probability`` are excluded from the
    result.  The returned list is sorted by ``ml_probability`` descending.

    If the model is not available, the original list is returned unmodified
    (no filtering, no ``ml_probability`` key added).

    Parameters
    ----------
    convergences:
        List of convergence dicts (same shape as ``generation_context``).
    min_probability:
        Minimum predicted probability to include in the result.

    Returns
    -------
    list[dict]
        Filtered and sorted convergence dicts, each with an
        ``ml_probability`` key.
    """
    model = get_cached_model(MLModelType.SIGNAL_RANKER.value)
    if model is None:
        logger.debug(
            "Signal ranker model not cached; returning convergences unranked"
        )
        return convergences

    scored: list[tuple[float, dict]] = []
    for conv in convergences:
        prob = predict_signal_probability(conv)
        if prob is None:
            # Prediction failed for this item; skip it
            continue
        conv["ml_probability"] = round(prob, 4)
        scored.append((prob, conv))

    # Sort descending by probability
    scored.sort(key=lambda x: x[0], reverse=True)

    # Filter by threshold
    result = [conv for prob, conv in scored if prob >= min_probability]

    logger.info(
        "Signal ranker: %d/%d convergences above %.2f threshold",
        len(result),
        len(convergences),
        min_probability,
    )

    return result
