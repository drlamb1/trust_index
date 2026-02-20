"""
EdgeFinder — Price/Volume Anomaly Detector (Phase 3)

Statistical detection of unusual price and volume activity:
  - Z-score volume spikes (lookback=20 days, threshold=2.0)
  - Price drop alerts (1d/5d/20d thresholds)
  - Overnight gap detection (>3% gap)
  - ATR-based volatility regime change
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Alert, Ticker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

VOLUME_ZSCORE_THRESHOLD = 2.0  # standard deviations
VOLUME_LOOKBACK = 20  # trading days for rolling stats

PRICE_DROP_THRESHOLDS: list[tuple[int, float]] = [
    (1, -0.05),  # -5% in 1 day
    (5, -0.10),  # -10% in 5 days
    (20, -0.15),  # -15% in 20 days
]

GAP_THRESHOLD = 0.03  # 3% overnight gap magnitude
ATR_EXPANSION_THRESHOLD = 1.5  # ATR_current / ATR_baseline ratio

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AnomalyResult:
    """A single detected anomaly."""

    anomaly_type: Literal[
        "volume_spike",
        "price_drop_1d",
        "price_drop_5d",
        "price_drop_20d",
        "gap_up",
        "gap_down",
        "atr_expansion",
    ]
    magnitude: float  # percentage or z-score value
    severity: Literal["high", "medium", "low"]
    title: str
    context: dict  # extra metadata (thresholds, values, etc.)


# ---------------------------------------------------------------------------
# Core detection functions
# ---------------------------------------------------------------------------


def detect_volume_spike(
    df: pd.DataFrame,
    lookback: int = VOLUME_LOOKBACK,
    threshold: float = VOLUME_ZSCORE_THRESHOLD,
) -> AnomalyResult | None:
    """
    Detect unusually high volume using Z-score.
    Requires columns: [date, close, volume]
    """
    if "volume" not in df.columns or len(df) < lookback + 1:
        return None

    df = df.sort_values("date").reset_index(drop=True)
    recent = df.iloc[-lookback - 1 : -1]["volume"]  # baseline window (exclude today)
    today_vol = df.iloc[-1]["volume"]

    mean = recent.mean()
    std = recent.std(ddof=1)

    if std == 0 or np.isnan(std):
        return None

    z = (today_vol - mean) / std
    if z < threshold:
        return None

    if z >= 4.0:
        severity: Literal["high", "medium", "low"] = "high"
    elif z >= 3.0:
        severity = "medium"
    else:
        severity = "low"

    return AnomalyResult(
        anomaly_type="volume_spike",
        magnitude=round(float(z), 2),
        severity=severity,
        title=f"Volume spike: {z:.1f}σ above 20-day average",
        context={
            "z_score": round(float(z), 2),
            "today_volume": int(today_vol),
            "avg_volume_20d": round(float(mean), 0),
            "threshold": threshold,
        },
    )


def detect_price_drops(
    df: pd.DataFrame,
    thresholds: list[tuple[int, float]] | None = None,
) -> list[AnomalyResult]:
    """
    Detect significant price drops over multiple windows.
    Requires columns: [date, close]
    """
    if thresholds is None:
        thresholds = PRICE_DROP_THRESHOLDS

    if "close" not in df.columns or len(df) < 2:
        return []

    df = df.sort_values("date").reset_index(drop=True)
    current_price = df.iloc[-1]["close"]

    results: list[AnomalyResult] = []
    for days, threshold in thresholds:
        if len(df) < days + 1:
            continue

        past_price = df.iloc[-(days + 1)]["close"]
        if past_price == 0:
            continue

        ret = (current_price - past_price) / past_price

        if ret > threshold:  # threshold is negative; only flag drops
            continue

        drop_pct = abs(ret) * 100

        if drop_pct >= abs(threshold) * 100 * 1.5:
            severity: Literal["high", "medium", "low"] = "high"
        elif drop_pct >= abs(threshold) * 100 * 1.2:
            severity = "medium"
        else:
            severity = "low"

        anomaly_type_map = {1: "price_drop_1d", 5: "price_drop_5d", 20: "price_drop_20d"}
        anomaly_type = anomaly_type_map.get(days, f"price_drop_{days}d")  # type: ignore

        results.append(
            AnomalyResult(
                anomaly_type=anomaly_type,
                magnitude=round(float(ret * 100), 2),
                severity=severity,
                title=f"Price drop {days}d: {ret * 100:.1f}% (threshold: {threshold * 100:.0f}%)",
                context={
                    "return_pct": round(float(ret * 100), 2),
                    "days": days,
                    "current_price": round(float(current_price), 2),
                    "past_price": round(float(past_price), 2),
                    "threshold_pct": threshold * 100,
                },
            )
        )

    return results


def detect_overnight_gap(
    df: pd.DataFrame,
    threshold: float = GAP_THRESHOLD,
) -> AnomalyResult | None:
    """
    Detect significant overnight price gaps.
    Requires columns: [date, open, close]
    """
    if "open" not in df.columns or "close" not in df.columns or len(df) < 2:
        return None

    df = df.sort_values("date").reset_index(drop=True)
    prev_close = df.iloc[-2]["close"]
    today_open = df.iloc[-1]["open"]

    if prev_close == 0:
        return None

    gap = (today_open - prev_close) / prev_close

    if abs(gap) < threshold:
        return None

    is_up = gap > 0
    anomaly_type: Literal["gap_up", "gap_down"] = "gap_up" if is_up else "gap_down"

    gap_pct = abs(gap) * 100
    if gap_pct >= threshold * 100 * 2:
        severity: Literal["high", "medium", "low"] = "high"
    elif gap_pct >= threshold * 100 * 1.5:
        severity = "medium"
    else:
        severity = "low"

    direction = "up" if is_up else "down"
    return AnomalyResult(
        anomaly_type=anomaly_type,
        magnitude=round(float(gap * 100), 2),
        severity=severity,
        title=f"Overnight gap {direction}: {gap * 100:.1f}%",
        context={
            "gap_pct": round(float(gap * 100), 2),
            "prev_close": round(float(prev_close), 2),
            "today_open": round(float(today_open), 2),
            "threshold_pct": threshold * 100,
        },
    )


def detect_atr_expansion(
    df: pd.DataFrame,
    baseline_days: int = 20,
    recent_days: int = 5,
    threshold: float = ATR_EXPANSION_THRESHOLD,
) -> AnomalyResult | None:
    """
    Detect ATR expansion (volatility regime change).
    Requires columns: [date, high, low, close]
    """
    required = {"high", "low", "close"}
    if not required.issubset(df.columns) or len(df) < baseline_days + recent_days:
        return None

    df = df.sort_values("date").reset_index(drop=True)

    # Compute true range
    df = df.copy()
    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "prev_close"]].max(axis=1) - df[["low", "prev_close"]].min(axis=1)
    df = df.dropna(subset=["tr"])

    if len(df) < baseline_days:
        return None

    recent_atr = df["tr"].iloc[-recent_days:].mean()
    baseline_atr = df["tr"].iloc[-(baseline_days + recent_days) : -recent_days].mean()

    if baseline_atr == 0 or np.isnan(baseline_atr) or np.isnan(recent_atr):
        return None

    ratio = recent_atr / baseline_atr

    if ratio < threshold:
        return None

    if ratio >= threshold * 1.5:
        severity: Literal["high", "medium", "low"] = "high"
    elif ratio >= threshold * 1.25:
        severity = "medium"
    else:
        severity = "low"

    return AnomalyResult(
        anomaly_type="atr_expansion",
        magnitude=round(float(ratio), 2),
        severity=severity,
        title=f"Volatility expansion: ATR {ratio:.1f}× baseline",
        context={
            "atr_ratio": round(float(ratio), 2),
            "recent_atr": round(float(recent_atr), 4),
            "baseline_atr": round(float(baseline_atr), 4),
            "recent_days": recent_days,
            "baseline_days": baseline_days,
            "threshold": threshold,
        },
    )


# ---------------------------------------------------------------------------
# Combined scanner
# ---------------------------------------------------------------------------


def scan_ticker_for_anomalies(
    df: pd.DataFrame,
    volume_threshold: float = VOLUME_ZSCORE_THRESHOLD,
    gap_threshold: float = GAP_THRESHOLD,
    atr_threshold: float = ATR_EXPANSION_THRESHOLD,
    price_thresholds: list[tuple[int, float]] | None = None,
) -> list[AnomalyResult]:
    """
    Run all anomaly detectors on a price DataFrame.

    Expects columns: [date, open, high, low, close, volume]
    (columns are optional — detectors will skip gracefully)

    Returns sorted list of AnomalyResult, high severity first.
    """
    results: list[AnomalyResult] = []

    vol = detect_volume_spike(df, threshold=volume_threshold)
    if vol:
        results.append(vol)

    results.extend(detect_price_drops(df, thresholds=price_thresholds))

    gap = detect_overnight_gap(df, threshold=gap_threshold)
    if gap:
        results.append(gap)

    atr = detect_atr_expansion(df, threshold=atr_threshold)
    if atr:
        results.append(atr)

    # Sort: high > medium > low
    order = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda r: order[r.severity])

    return results


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


async def store_anomaly_alerts(
    session: AsyncSession,
    ticker: Ticker,
    anomalies: list[AnomalyResult],
) -> int:
    """
    Persist detected anomalies as Alert rows.
    Returns number of alerts created.
    """
    if not anomalies:
        return 0

    count = 0

    for anomaly in anomalies:
        severity_map = {"high": "red", "medium": "yellow", "low": "green"}
        alert = Alert(
            ticker_id=ticker.id,
            alert_type=anomaly.anomaly_type.upper(),
            severity=severity_map[anomaly.severity],
            score=abs(anomaly.magnitude),
            title=f"[{ticker.symbol}] {anomaly.title}",
            body=f"Detected {anomaly.anomaly_type} for {ticker.symbol}. "
            f"Magnitude: {anomaly.magnitude:+.2f}",
            context_json=anomaly.context,
        )
        session.add(alert)
        count += 1

    if count:
        await session.flush()

    return count


async def scan_and_store(
    session: AsyncSession,
    ticker: Ticker,
    df: pd.DataFrame,
    **kwargs,
) -> int:
    """
    Convenience: scan a price DataFrame and immediately persist alerts.
    Returns number of alerts stored.
    """
    anomalies = scan_ticker_for_anomalies(df, **kwargs)
    return await store_anomaly_alerts(session, ticker, anomalies)
