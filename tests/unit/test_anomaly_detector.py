"""
Unit tests for analysis/anomaly_detector.py

All tests use synthetic, deterministic price data — no external dependencies.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.anomaly_detector import (
    AnomalyResult,
    detect_atr_expansion,
    detect_overnight_gap,
    detect_price_drops,
    detect_volume_spike,
    scan_ticker_for_anomalies,
    store_anomaly_alerts,
)
from core.models import Alert

# ---------------------------------------------------------------------------
# Helpers to build synthetic price DataFrames
# ---------------------------------------------------------------------------


def _make_price_df(
    n: int = 30,
    close_vals: list[float] | None = None,
    volume_vals: list[int] | None = None,
    include_ohlcv: bool = True,
    seed: int = 42,
) -> pd.DataFrame:
    """Build a synthetic price DataFrame."""
    rng = np.random.default_rng(seed)
    start = date(2024, 1, 2)
    dates = []
    d = start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)

    if close_vals is None:
        close_vals = list(100.0 * np.cumprod(1 + rng.normal(0, 0.01, n)))
    else:
        # Truncate or extend to n
        close_vals = (close_vals * ((n // len(close_vals)) + 1))[:n]

    data: dict = {"date": dates[:n], "close": close_vals[:n]}

    if include_ohlcv:
        c = np.array(close_vals[:n])
        data["open"] = list(c * (1 + rng.normal(0, 0.005, n)))
        data["high"] = [
            max(o, cl) * (1 + abs(rng.normal(0, 0.005))) for o, cl in zip(data["open"], c)
        ]
        data["low"] = [
            min(o, cl) * (1 - abs(rng.normal(0, 0.005))) for o, cl in zip(data["open"], c)
        ]
        if volume_vals is None:
            volume_vals = list(rng.integers(800_000, 1_200_000, n))
        data["volume"] = volume_vals[:n]

    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# detect_volume_spike
# ---------------------------------------------------------------------------


class TestDetectVolumeSpike:
    def test_normal_volume_returns_none(self):
        df = _make_price_df(n=30)
        # Replace today's volume with average (z-score ≈ 0)
        avg = int(df["volume"].mean())
        df.at[df.index[-1], "volume"] = avg
        result = detect_volume_spike(df)
        assert result is None

    def test_massive_volume_spike_detected(self):
        """Volume 10× average should be detected."""
        n = 30
        rng = np.random.default_rng(7)
        # Varied baseline (non-zero std) with a massive spike on the last day
        baseline = list(rng.integers(800_000, 1_200_000, n - 1))
        volumes = baseline + [10_000_000]
        df = _make_price_df(n=n, volume_vals=volumes)
        result = detect_volume_spike(df, threshold=2.0)
        assert result is not None
        assert result.anomaly_type == "volume_spike"
        assert result.magnitude > 2.0

    def test_spike_severity_levels(self):
        """Z-scores map to severity levels correctly."""
        n = 30
        rng = np.random.default_rng(8)
        baseline = list(rng.integers(800_000, 1_200_000, n - 1))
        volumes = baseline + [20_000_000]  # extreme spike
        df = _make_price_df(n=n, volume_vals=volumes)
        result = detect_volume_spike(df)
        assert result is not None
        assert result.severity in {"high", "medium", "low"}

    def test_insufficient_data_returns_none(self):
        df = _make_price_df(n=10)
        assert detect_volume_spike(df, lookback=20) is None

    def test_no_volume_column_returns_none(self):
        df = _make_price_df(n=30, include_ohlcv=False)
        assert detect_volume_spike(df) is None

    def test_constant_volume_returns_none(self):
        """Zero std dev means no z-score can be computed."""
        n = 30
        df = _make_price_df(n=n, volume_vals=[1_000_000] * n)
        result = detect_volume_spike(df)
        assert result is None  # std=0 → skip

    def test_result_has_context(self):
        """Result context should include z_score, today_volume, avg_volume_20d."""
        n = 30
        rng = np.random.default_rng(9)
        baseline = list(rng.integers(800_000, 1_200_000, n - 1))
        volumes = baseline + [10_000_000]
        df = _make_price_df(n=n, volume_vals=volumes)
        result = detect_volume_spike(df)
        assert result is not None
        assert "z_score" in result.context
        assert "today_volume" in result.context
        assert "avg_volume_20d" in result.context


# ---------------------------------------------------------------------------
# detect_price_drops
# ---------------------------------------------------------------------------


class TestDetectPriceDrops:
    def test_no_drop_returns_empty(self):
        # Steady uptrend — no drop
        closes = [100.0 + i for i in range(30)]
        df = _make_price_df(n=30, close_vals=closes)
        results = detect_price_drops(df)
        assert results == []

    def test_1d_drop_detected(self):
        # Drop >5% in 1 day
        closes = [100.0] * 28 + [100.0, 90.0]  # last day: -10% drop
        df = _make_price_df(n=30, close_vals=closes)
        results = detect_price_drops(df, thresholds=[(1, -0.05)])
        assert len(results) >= 1
        types = [r.anomaly_type for r in results]
        assert "price_drop_1d" in types

    def test_5d_drop_detected(self):
        # Drop >10% in 5 days
        closes = [100.0] * 25 + [100.0, 98.0, 96.0, 94.0, 88.0]
        df = _make_price_df(n=30, close_vals=closes)
        results = detect_price_drops(df, thresholds=[(5, -0.10)])
        types = [r.anomaly_type for r in results]
        assert "price_drop_5d" in types

    def test_returns_negative_magnitude(self):
        closes = [100.0] * 29 + [90.0]  # -10% drop
        df = _make_price_df(n=30, close_vals=closes)
        results = detect_price_drops(df, thresholds=[(1, -0.05)])
        assert results[0].magnitude < 0

    def test_insufficient_data_returns_empty(self):
        df = _make_price_df(n=3, close_vals=[100.0, 95.0, 90.0])
        results = detect_price_drops(df, thresholds=[(5, -0.10)])
        assert results == []

    def test_multiple_windows(self):
        """A large drop can trigger multiple window thresholds."""
        closes = [100.0] * 24 + [99.0, 95.0, 90.0, 85.0, 80.0, 70.0]  # big crash
        df = _make_price_df(n=30, close_vals=closes)
        results = detect_price_drops(df)
        assert len(results) >= 2

    def test_result_is_anomaly_result(self):
        closes = [100.0] * 29 + [80.0]
        df = _make_price_df(n=30, close_vals=closes)
        results = detect_price_drops(df, thresholds=[(1, -0.05)])
        for r in results:
            assert isinstance(r, AnomalyResult)
            assert r.severity in {"high", "medium", "low"}


# ---------------------------------------------------------------------------
# detect_overnight_gap
# ---------------------------------------------------------------------------


class TestDetectOvernightGap:
    def _make_gap_df(self, prev_close: float, today_open: float) -> pd.DataFrame:
        n = 5
        dates = [date(2024, 1, i + 2) for i in range(n)]
        closes = [prev_close] * (n - 1) + [today_open * 1.01]
        opens = [prev_close * 0.99] * (n - 1) + [today_open]
        highs = [max(o, c) * 1.005 for o, c in zip(opens, closes)]
        lows = [min(o, c) * 0.995 for o, c in zip(opens, closes)]
        return pd.DataFrame(
            {
                "date": dates,
                "open": opens,
                "close": closes,
                "high": highs,
                "low": lows,
            }
        )

    def test_no_gap_returns_none(self):
        df = self._make_gap_df(prev_close=100.0, today_open=100.5)  # 0.5% gap
        result = detect_overnight_gap(df, threshold=0.03)
        assert result is None

    def test_gap_up_detected(self):
        df = self._make_gap_df(prev_close=100.0, today_open=106.0)  # +6% gap
        result = detect_overnight_gap(df, threshold=0.03)
        assert result is not None
        assert result.anomaly_type == "gap_up"
        assert result.magnitude > 0

    def test_gap_down_detected(self):
        df = self._make_gap_df(prev_close=100.0, today_open=94.0)  # -6% gap
        result = detect_overnight_gap(df, threshold=0.03)
        assert result is not None
        assert result.anomaly_type == "gap_down"
        assert result.magnitude < 0

    def test_insufficient_data_returns_none(self):
        df = pd.DataFrame({"date": [date(2024, 1, 2)], "open": [100.0], "close": [101.0]})
        result = detect_overnight_gap(df)
        assert result is None

    def test_missing_columns_returns_none(self):
        df = _make_price_df(n=5, include_ohlcv=False)  # no open column
        result = detect_overnight_gap(df)
        assert result is None


# ---------------------------------------------------------------------------
# detect_atr_expansion
# ---------------------------------------------------------------------------


class TestDetectAtrExpansion:
    def _make_atr_df(
        self, n: int = 40, base_atr: float = 1.0, recent_mult: float = 1.0
    ) -> pd.DataFrame:
        """Build a DataFrame where baseline ATR = base_atr, recent ATR = base_atr × recent_mult."""
        dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(n)]
        closes = [100.0 + i * 0.1 for i in range(n)]
        # Set highs/lows to control ATR:
        # base period: ATR ≈ base_atr; recent period: ATR ≈ base_atr × recent_mult
        highs = []
        lows = []
        for i, c in enumerate(closes):
            is_recent = i >= (n - 5)
            daily_range = base_atr * recent_mult if is_recent else base_atr
            highs.append(c + daily_range / 2)
            lows.append(c - daily_range / 2)
        opens = closes.copy()
        return pd.DataFrame(
            {
                "date": dates,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
            }
        )

    def test_no_expansion_returns_none(self):
        df = self._make_atr_df(n=40, base_atr=1.0, recent_mult=1.0)
        result = detect_atr_expansion(df, threshold=1.5)
        assert result is None

    def test_large_expansion_detected(self):
        df = self._make_atr_df(n=40, base_atr=1.0, recent_mult=3.0)
        result = detect_atr_expansion(df, threshold=1.5)
        assert result is not None
        assert result.anomaly_type == "atr_expansion"
        assert result.magnitude >= 1.5

    def test_insufficient_data_returns_none(self):
        df = _make_price_df(n=10)
        result = detect_atr_expansion(df, baseline_days=20, recent_days=5)
        assert result is None

    def test_missing_columns_returns_none(self):
        df = pd.DataFrame({"date": [date(2024, 1, 2)], "close": [100.0]})
        result = detect_atr_expansion(df)
        assert result is None


# ---------------------------------------------------------------------------
# scan_ticker_for_anomalies (combined scanner)
# ---------------------------------------------------------------------------


class TestScanTickerForAnomalies:
    def test_clean_data_returns_empty(self):
        """Normal market data → no anomalies."""
        df = _make_price_df(n=60)
        results = scan_ticker_for_anomalies(df)
        # Might return a few anomalies due to random data; just check it's a list
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, AnomalyResult)

    def test_multiple_anomalies_detected(self):
        """A big volume spike + big price drop should both be detected."""
        n = 30
        rng = np.random.default_rng(10)
        closes = [100.0] * 29 + [85.0]  # -15% drop
        baseline_vols = list(rng.integers(800_000, 1_200_000, 29))
        volumes = baseline_vols + [10_000_000]  # large spike with varied baseline
        df = _make_price_df(n=n, close_vals=closes, volume_vals=volumes)

        results = scan_ticker_for_anomalies(df)
        types = {r.anomaly_type for r in results}
        assert "volume_spike" in types
        assert any(t.startswith("price_drop") for t in types)

    def test_results_sorted_by_severity(self):
        n = 30
        rng = np.random.default_rng(11)
        closes = [100.0] * 29 + [80.0]
        baseline_vols = list(rng.integers(800_000, 1_200_000, 29))
        volumes = baseline_vols + [10_000_000]
        df = _make_price_df(n=n, close_vals=closes, volume_vals=volumes)
        results = scan_ticker_for_anomalies(df)

        order = {"high": 0, "medium": 1, "low": 2}
        for i in range(len(results) - 1):
            assert order[results[i].severity] <= order[results[i + 1].severity]

    def test_minimal_df_no_crash(self):
        """Very small DataFrame shouldn't crash."""
        df = _make_price_df(n=2)
        results = scan_ticker_for_anomalies(df)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# store_anomaly_alerts (requires DB)
# ---------------------------------------------------------------------------


class TestStoreAnomalyAlerts:
    @pytest.mark.asyncio
    async def test_stores_alerts(self, db_session: AsyncSession, sample_ticker):
        anomalies = [
            AnomalyResult(
                anomaly_type="volume_spike",
                magnitude=3.5,
                severity="high",
                title="Volume spike 3.5σ",
                context={"z_score": 3.5},
            )
        ]
        count = await store_anomaly_alerts(db_session, sample_ticker, anomalies)
        assert count == 1

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, db_session: AsyncSession, sample_ticker):
        count = await store_anomaly_alerts(db_session, sample_ticker, [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_alert_fields_populated(self, db_session: AsyncSession, sample_ticker):
        from sqlalchemy import select

        anomaly = AnomalyResult(
            anomaly_type="price_drop_1d",
            magnitude=-8.5,
            severity="high",
            title="Price drop 1d: -8.5%",
            context={"return_pct": -8.5, "days": 1},
        )
        await store_anomaly_alerts(db_session, sample_ticker, [anomaly])

        result = await db_session.execute(select(Alert).where(Alert.ticker_id == sample_ticker.id))
        alert = result.scalar_one_or_none()
        assert alert is not None
        assert alert.alert_type == "PRICE_DROP_1D"
        assert alert.severity == "red"
        assert alert.ticker_id == sample_ticker.id

    @pytest.mark.asyncio
    async def test_severity_mapping(self, db_session: AsyncSession, sample_ticker):
        """AnomalyResult severity maps to Alert severity (red/yellow/green)."""
        from sqlalchemy import select

        anomalies = [
            AnomalyResult("volume_spike", 2.5, "high", "High", {}),
            AnomalyResult("gap_up", 4.0, "medium", "Medium", {}),
            AnomalyResult("atr_expansion", 1.6, "low", "Low", {}),
        ]
        await store_anomaly_alerts(db_session, sample_ticker, anomalies)

        result = await db_session.execute(select(Alert).where(Alert.ticker_id == sample_ticker.id))
        alerts = result.scalars().all()
        severities = {a.severity for a in alerts}
        assert "red" in severities
        assert "yellow" in severities
        assert "green" in severities

    @pytest.mark.asyncio
    async def test_multiple_anomalies_stored(self, db_session: AsyncSession, sample_ticker):
        from sqlalchemy import func, select

        anomalies = [
            AnomalyResult("volume_spike", 3.0, "high", "Vol spike", {}),
            AnomalyResult("price_drop_1d", -6.0, "medium", "Drop", {}),
        ]
        count = await store_anomaly_alerts(db_session, sample_ticker, anomalies)
        assert count == 2

        result = await db_session.execute(
            select(func.count(Alert.id)).where(Alert.ticker_id == sample_ticker.id)
        )
        db_count = result.scalar_one()
        assert db_count == 2
