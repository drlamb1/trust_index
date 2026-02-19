"""
Unit tests for analysis/technicals.py

Tests the indicator computation logic in isolation — no DB, no network.
All computations use synthetic OHLCV data from conftest fixtures.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.technicals import (
    _safe_float,
    compute_indicators,
    compute_relative_strength,
    detect_bollinger_squeeze,
    detect_golden_cross,
    get_rsi_signal,
)

# ---------------------------------------------------------------------------
# compute_indicators
# ---------------------------------------------------------------------------


class TestComputeIndicators:
    def test_returns_dataframe(self, sample_ohlcv_df):
        result = compute_indicators(sample_ohlcv_df)
        assert isinstance(result, pd.DataFrame)

    def test_adds_sma_columns(self, sample_ohlcv_df):
        result = compute_indicators(sample_ohlcv_df)
        assert "sma_20" in result.columns
        assert "sma_50" in result.columns

    def test_sma_20_is_valid(self, sample_ohlcv_df):
        result = compute_indicators(sample_ohlcv_df)
        # First 19 rows should be NaN (insufficient history)
        assert result["sma_20"].iloc[:19].isna().all()
        # Row 20+ should have valid values
        assert not result["sma_20"].iloc[20:].isna().all()

    def test_sma_200_requires_200_days(self, sample_ohlcv_df_200):
        result = compute_indicators(sample_ohlcv_df_200)
        assert "sma_200" in result.columns
        # Should have valid SMA200 for recent rows
        recent = result.dropna(subset=["sma_200"])
        assert len(recent) > 0

    def test_rsi_bounds(self, sample_ohlcv_df):
        result = compute_indicators(sample_ohlcv_df)
        rsi_values = result["rsi_14"].dropna()
        assert (rsi_values >= 0).all(), "RSI should be >= 0"
        assert (rsi_values <= 100).all(), "RSI should be <= 100"

    def test_macd_columns_present(self, sample_ohlcv_df):
        result = compute_indicators(sample_ohlcv_df)
        assert "macd" in result.columns
        assert "macd_signal" in result.columns
        assert "macd_histogram" in result.columns

    def test_bollinger_bands_ordering(self, sample_ohlcv_df):
        result = compute_indicators(sample_ohlcv_df)
        valid = result.dropna(subset=["bb_upper", "bb_lower", "bb_middle"])
        if len(valid) > 0:
            # Upper should be >= Middle >= Lower
            assert (valid["bb_upper"] >= valid["bb_middle"]).all()
            assert (valid["bb_middle"] >= valid["bb_lower"]).all()

    def test_atr_is_positive(self, sample_ohlcv_df):
        result = compute_indicators(sample_ohlcv_df)
        atr_values = result["atr_14"].dropna()
        assert (atr_values > 0).all(), "ATR should always be positive"

    def test_volume_ratio_is_positive(self, sample_ohlcv_df):
        result = compute_indicators(sample_ohlcv_df)
        vr = result["volume_ratio_20d"].dropna()
        assert (vr > 0).all(), "Volume ratio should be positive"

    def test_empty_df_returns_empty(self):
        result = compute_indicators(pd.DataFrame())
        assert result.empty

    def test_insufficient_data_returns_df(self):
        """With < 20 rows, returns the DataFrame unchanged (no indicators computed)."""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=5).date,
                "open": [100.0] * 5,
                "high": [102.0] * 5,
                "low": [99.0] * 5,
                "close": [101.0] * 5,
                "volume": [1_000_000] * 5,
            }
        )
        result = compute_indicators(df)
        assert isinstance(result, pd.DataFrame)
        # No indicators should be present (returned early)
        assert "sma_20" not in result.columns


# ---------------------------------------------------------------------------
# compute_relative_strength
# ---------------------------------------------------------------------------


class TestRelativeStrength:
    def test_outperformer_positive_rs(self):
        """A ticker up 20% vs SPY up 10% should show positive relative strength."""
        dates = pd.date_range("2024-01-01", periods=25).date

        ticker_df = pd.DataFrame(
            {
                "date": dates,
                "close": [100 * (1.008**i) for i in range(25)],  # ~20% over 25 days
            }
        )
        spy_df = pd.DataFrame(
            {
                "date": dates,
                "close": [100 * (1.004**i) for i in range(25)],  # ~10% over 25 days
            }
        )

        rs = compute_relative_strength(ticker_df, spy_df, lookback=20)
        # The last row should be positive (ticker outperformed)
        assert rs.iloc[-1] > 0

    def test_underperformer_negative_rs(self):
        """A ticker down 10% vs SPY up 5% should show negative relative strength."""
        dates = pd.date_range("2024-01-01", periods=25).date

        ticker_df = pd.DataFrame(
            {
                "date": dates,
                "close": [100 * (0.995**i) for i in range(25)],  # ~-10%
            }
        )
        spy_df = pd.DataFrame(
            {
                "date": dates,
                "close": [100 * (1.002**i) for i in range(25)],  # ~+5%
            }
        )

        rs = compute_relative_strength(ticker_df, spy_df, lookback=20)
        assert rs.iloc[-1] < 0

    def test_empty_spy_returns_empty_series(self, sample_ohlcv_df):
        rs = compute_relative_strength(sample_ohlcv_df, pd.DataFrame())
        assert rs.empty or rs.isna().all()


# ---------------------------------------------------------------------------
# Signal detection helpers
# ---------------------------------------------------------------------------


class TestGoldenCross:
    def test_detects_golden_cross(self):
        """SMA50 crosses above SMA200 → True."""
        df = pd.DataFrame(
            {
                "sma_50": [95, 98, 100, 102],  # Rising
                "sma_200": [100, 100, 99, 100],  # Flat/declining
            }
        )
        # Manually set up a cross: bars 0-2 have SMA50 < SMA200, bar 3 has SMA50 > SMA200
        df = pd.DataFrame(
            {
                "sma_50": [98, 99, 100, 101],
                "sma_200": [102, 101, 100, 99],
            }
        )
        assert detect_golden_cross(df) is True

    def test_no_cross_returns_false(self):
        """SMA50 consistently above SMA200 → no recent cross."""
        df = pd.DataFrame(
            {
                "sma_50": [110, 111, 112, 113],
                "sma_200": [100, 100, 100, 100],
            }
        )
        assert detect_golden_cross(df) is False

    def test_insufficient_data_returns_false(self):
        df = pd.DataFrame({"sma_50": [100], "sma_200": [99]})
        assert detect_golden_cross(df) is False


class TestBollingerSqueeze:
    def test_detects_narrow_bands(self):
        """Very narrow Bollinger Bands → squeeze detected."""
        df = pd.DataFrame(
            {
                "bb_bandwidth": [1.5, 1.2, 1.0, 0.8],
                "close": [100.0, 100.0, 100.0, 100.0],
            }
        )
        # bandwidth/close = 0.008 < 0.03 threshold → squeeze
        assert detect_bollinger_squeeze(df, threshold=0.03) is True

    def test_wide_bands_no_squeeze(self):
        """Wide Bollinger Bands → no squeeze."""
        df = pd.DataFrame(
            {
                "bb_bandwidth": [8.0, 8.5, 9.0, 10.0],
                "close": [100.0, 100.0, 100.0, 100.0],
            }
        )
        assert detect_bollinger_squeeze(df, threshold=0.03) is False


class TestRsiSignal:
    @pytest.mark.parametrize(
        "rsi,expected",
        [
            (15, "extremely_oversold"),
            (25, "oversold"),
            (40, "weak"),
            (50, "neutral"),
            (60, "strong"),
            (75, "overbought"),
            (85, "extremely_overbought"),
            (None, "unknown"),
        ],
    )
    def test_rsi_classification(self, rsi, expected):
        assert get_rsi_signal(rsi) == expected


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_valid_float(self):
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_nan_returns_none(self):
        assert _safe_float(float("nan")) is None

    def test_inf_returns_none(self):
        assert _safe_float(float("inf")) is None

    def test_string_number(self):
        assert _safe_float("42.0") == pytest.approx(42.0)

    def test_invalid_string_returns_none(self):
        assert _safe_float("not_a_number") is None
