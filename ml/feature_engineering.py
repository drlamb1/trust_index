"""
EdgeFinder — Feature Engineering for Signal Ranker

Extracts numeric features from the generation_context JSONB stored on each
SimulatedThesis.  The context captures which convergence signals triggered
thesis generation (alerts, insider buying, filing concerns, sentiment
extremes, RSI extremes) along with sector metadata.

All features are returned as float values suitable for XGBoost.  Missing
signal groups default to 0 / neutral so the feature vector always has a
consistent shape.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# AlertType values we track as binary indicators
_ALERT_TYPES = (
    "PRICE_ANOMALY",
    "VOLUME_SPIKE",
    "FILING_RED_FLAG",
    "INSIDER_BUY_CLUSTER",
    "SENTIMENT_DIVERGENCE",
    "EARNINGS_SURPRISE",
    "EARNINGS_TONE_SHIFT",
    "TECHNICAL_SIGNAL",
    "BUY_THE_DIP",
    "THESIS_MATCH",
)


def _get(d: dict | None, *keys: str, default: Any = 0) -> Any:
    """Safely traverse nested dicts, returning *default* on any miss."""
    current = d
    for k in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(k, default)
    return current if current is not None else default


def extract_convergence_features(generation_context: dict) -> dict[str, float]:
    """Convert a generation_context JSONB blob into a flat feature dict.

    Returns ~19 numeric features (all floats).  Unknown / missing signal
    groups gracefully default to zero or neutral values.

    Parameters
    ----------
    generation_context:
        The ``generation_context`` column value from a SimulatedThesis row.
        Expected top-level keys: ``signal_count``, ``signals``, ``sector``,
        ``ticker_symbol``, etc.

    Returns
    -------
    dict[str, float]
        Feature name -> float value mapping.
    """
    ctx = generation_context or {}
    signals: dict = ctx.get("signals", {})

    # --- Top-level -----------------------------------------------------------
    signal_count = float(ctx.get("signal_count", 0))

    # --- Alert signals -------------------------------------------------------
    alert_info: dict = signals.get("alert", {})
    alert_count = float(alert_info.get("count", 0))
    alert_types: list[str] = alert_info.get("types", [])
    has_alert = float(alert_count > 0)

    # Binary indicators for each common AlertType
    alert_type_set = set(alert_types)
    alert_features: dict[str, float] = {}
    for at in _ALERT_TYPES:
        key = f"has_{at.lower()}"
        alert_features[key] = float(at in alert_type_set)

    # --- Insider buying ------------------------------------------------------
    insider_info: dict = signals.get("insider_buying", {})
    insider_buy_count = float(insider_info.get("count", 0))
    insider_buy_value = float(insider_info.get("total_value", 0))
    has_insider_buying = float(insider_buy_count > 0)
    insider_buy_value_log = float(np.log1p(insider_buy_value))

    # --- Filing concern ------------------------------------------------------
    filing_info: dict = signals.get("filing_concern", {})
    has_filing_concern = float(bool(filing_info))
    filing_health_score = float(filing_info.get("health_score", 50)) / 100.0
    filing_red_flag_count = float(filing_info.get("red_flag_count", 0))

    # --- Sentiment extreme ---------------------------------------------------
    sentiment_info: dict = signals.get("sentiment_extreme", {})
    has_sentiment_extreme = float(bool(sentiment_info))
    sentiment_avg = float(sentiment_info.get("avg_score", 0.0))
    sentiment_direction = sentiment_info.get("direction", "")
    sentiment_is_bearish = float(sentiment_direction == "bearish")

    # --- RSI extreme ---------------------------------------------------------
    rsi_info: dict = signals.get("rsi_oversold", signals.get("rsi_overbought", {}))
    has_rsi_extreme = float(bool(rsi_info))
    rsi_value = float(rsi_info.get("rsi", 50.0))
    rsi_is_oversold = float(rsi_value < 35.0) if has_rsi_extreme else 0.0

    # --- Sector hash (ordinal encoding) --------------------------------------
    sector = ctx.get("sector", "")
    sector_hash = float(int(hashlib.md5(sector.encode()).hexdigest(), 16) % 20) if sector else 0.0

    # --- Assemble feature dict -----------------------------------------------
    features: dict[str, float] = {
        "signal_count": signal_count,
        "has_alert": has_alert,
        "alert_count": alert_count,
        **alert_features,
        "has_insider_buying": has_insider_buying,
        "insider_buy_count": insider_buy_count,
        "insider_buy_value_log": insider_buy_value_log,
        "has_filing_concern": has_filing_concern,
        "filing_health_score": filing_health_score,
        "filing_red_flag_count": filing_red_flag_count,
        "has_sentiment_extreme": has_sentiment_extreme,
        "sentiment_avg": sentiment_avg,
        "sentiment_is_bearish": sentiment_is_bearish,
        "has_rsi_extreme": has_rsi_extreme,
        "rsi_value": rsi_value,
        "rsi_is_oversold": rsi_is_oversold,
        "sector_hash": sector_hash,
    }

    return features
