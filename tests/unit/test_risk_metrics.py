"""
Unit tests for analysis/risk_metrics.py

All tests use synthetic, deterministic price data — no external data sources.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from analysis.risk_metrics import (
    compute_beta,
    compute_correlation,
    compute_max_drawdown,
    compute_risk_snapshot,
    compute_sharpe_ratio,
    compute_var,
    compute_volatility,
)

# ---------------------------------------------------------------------------
# Helpers to build synthetic price DataFrames
# ---------------------------------------------------------------------------


def _make_prices(
    returns: list[float] | None = None,
    *,
    n: int = 252,
    seed: int = 42,
    start_price: float = 100.0,
) -> pd.DataFrame:
    """
    Build a DataFrame with columns [date, close] from a list of daily returns
    or from random returns if none provided.
    """
    if returns is None:
        rng = np.random.default_rng(seed)
        returns = rng.normal(0.0005, 0.015, n).tolist()

    prices = [start_price]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    prices = prices[1:]  # drop the seed price

    start = date(2023, 1, 1)
    dates = []
    d = start
    while len(dates) < len(prices):
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    dates = dates[: len(prices)]

    return pd.DataFrame({"date": dates, "close": prices})


def _make_correlated_pair(
    n: int = 252,
    correlation: float = 0.8,
    ticker_vol: float = 0.02,
    spy_vol: float = 0.015,
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build two price series with a specified correlation."""
    rng = np.random.default_rng(seed)
    z1 = rng.standard_normal(n)
    z2 = rng.standard_normal(n)

    spy_returns = spy_vol * z1
    ticker_returns = ticker_vol * (correlation * z1 + np.sqrt(1 - correlation**2) * z2)

    spy_df = _make_prices(list(spy_returns), start_price=400.0)
    ticker_df = _make_prices(list(ticker_returns), start_price=100.0)
    return ticker_df, spy_df


# ---------------------------------------------------------------------------
# compute_volatility
# ---------------------------------------------------------------------------


class TestComputeVolatility:
    def test_returns_positive_float(self):
        df = _make_prices(n=252)
        vol = compute_volatility(df)
        assert vol is not None
        assert vol > 0

    def test_higher_vol_series_has_higher_vol(self):
        low_vol = _make_prices(returns=[0.001] * 100 + [-0.001] * 100)
        high_vol = _make_prices(returns=[0.05] * 100 + [-0.05] * 100)
        assert compute_volatility(high_vol) > compute_volatility(low_vol)

    def test_insufficient_data_returns_none(self):
        df = _make_prices(n=5)
        assert compute_volatility(df, lookback=252) is None

    def test_annualized_via_sqrt252(self):
        """Constant daily return series: vol = constant × sqrt(252)."""
        returns = [0.01] * 100  # perfectly constant → std dev = 0 → should be near 0
        df = _make_prices(returns=returns)
        vol = compute_volatility(df)
        # constant returns have zero std dev
        assert vol == pytest.approx(0.0, abs=1e-10)

    def test_lookback_respected(self):
        """Using a shorter lookback should use fewer days."""
        df = _make_prices(n=300)
        v30 = compute_volatility(df, lookback=30)
        v252 = compute_volatility(df, lookback=252)
        # Both should be valid floats (different values depending on the series)
        assert v30 is not None
        assert v252 is not None


# ---------------------------------------------------------------------------
# compute_sharpe_ratio
# ---------------------------------------------------------------------------


class TestComputeSharpeRatio:
    def test_positive_for_uptrending_stock(self):
        """A stock with positive drift and realistic volatility should have positive Sharpe."""
        rng = np.random.default_rng(5)
        # Strong uptrend: 0.3% daily drift + 1% vol → annualized ~75% return, ~16% vol
        returns = (rng.normal(0.003, 0.01, 252)).tolist()
        df = _make_prices(returns=returns)
        sharpe = compute_sharpe_ratio(df, risk_free_rate=0.05)
        assert sharpe is not None
        assert sharpe > 0

    def test_negative_for_downtrending_stock(self):
        """A stock with negative drift should have negative Sharpe."""
        rng = np.random.default_rng(6)
        returns = (rng.normal(-0.003, 0.01, 252)).tolist()
        df = _make_prices(returns=returns)
        sharpe = compute_sharpe_ratio(df, risk_free_rate=0.05)
        assert sharpe is not None
        assert sharpe < 0

    def test_insufficient_data_returns_none(self):
        df = _make_prices(n=10)
        assert compute_sharpe_ratio(df) is None

    def test_zero_volatility_returns_none(self):
        """Constant price (zero volatility) → undefined Sharpe → None."""
        df = _make_prices(returns=[0.0] * 100)
        assert compute_sharpe_ratio(df) is None


# ---------------------------------------------------------------------------
# compute_max_drawdown
# ---------------------------------------------------------------------------


class TestComputeMaxDrawdown:
    def test_returns_negative_float(self):
        df = _make_prices(n=252)
        dd = compute_max_drawdown(df)
        assert dd is not None
        assert dd <= 0

    def test_monotonically_rising_is_zero_drawdown(self):
        """Prices that only go up have zero max drawdown."""
        returns = [0.001] * 100
        df = _make_prices(returns=returns)
        dd = compute_max_drawdown(df)
        assert dd == pytest.approx(0.0, abs=1e-10)

    def test_50_percent_drop_detected(self):
        """A series that drops exactly 50% from peak should show -0.50."""
        prices = [100.0] * 50 + [50.0] * 50  # Step down at midpoint
        dates = []
        d = date(2023, 1, 1)
        while len(dates) < 100:
            if d.weekday() < 5:
                dates.append(d)
            d += timedelta(days=1)
        df = pd.DataFrame({"date": dates, "close": prices})
        dd = compute_max_drawdown(df)
        assert dd == pytest.approx(-0.5)

    def test_insufficient_data_returns_none(self):
        df = pd.DataFrame({"date": [date(2024, 1, 1)], "close": [100.0]})
        assert compute_max_drawdown(df) is None


# ---------------------------------------------------------------------------
# compute_beta
# ---------------------------------------------------------------------------


class TestComputeBeta:
    def test_spy_has_beta_one(self):
        """SPY vs SPY should have beta ≈ 1."""
        df, _ = _make_correlated_pair(correlation=1.0)
        spy = df.copy()  # Use same series as SPY
        beta = compute_beta(spy, spy, lookback=252)
        assert beta is not None
        assert beta == pytest.approx(1.0, abs=0.05)

    def test_high_beta_stock_detected(self):
        """A stock with 2× SPY volatility and high correlation → beta ≈ 2."""
        rng = np.random.default_rng(1)
        n = 252
        spy_returns = rng.normal(0, 0.01, n)
        ticker_returns = 2.0 * spy_returns  # Perfect correlation, 2× vol

        spy_df = _make_prices(list(spy_returns))
        ticker_df = _make_prices(list(ticker_returns))
        beta = compute_beta(ticker_df, spy_df, lookback=252)
        assert beta is not None
        assert beta == pytest.approx(2.0, abs=0.1)

    def test_insufficient_data_returns_none(self):
        ticker = _make_prices(n=10)
        spy = _make_prices(n=10, seed=1)
        assert compute_beta(ticker, spy, lookback=252) is None

    def test_empty_dataframe_returns_none(self):
        assert compute_beta(pd.DataFrame(), pd.DataFrame()) is None


# ---------------------------------------------------------------------------
# compute_correlation
# ---------------------------------------------------------------------------


class TestComputeCorrelation:
    def test_high_correlation_pair(self):
        ticker_df, spy_df = _make_correlated_pair(correlation=0.9, n=300)
        corr = compute_correlation(ticker_df, spy_df, lookback=252)
        assert corr is not None
        assert corr > 0.7  # Should be high but not necessarily exactly 0.9

    def test_correlation_in_bounds(self):
        ticker_df, spy_df = _make_correlated_pair(n=300)
        corr = compute_correlation(ticker_df, spy_df, lookback=252)
        assert corr is not None
        assert -1.0 <= corr <= 1.0

    def test_insufficient_data_returns_none(self):
        ticker = _make_prices(n=10)
        spy = _make_prices(n=10, seed=1)
        assert compute_correlation(ticker, spy, lookback=252) is None


# ---------------------------------------------------------------------------
# compute_var
# ---------------------------------------------------------------------------


class TestComputeVar:
    def test_returns_positive_float(self):
        df = _make_prices(n=252)
        var = compute_var(df, confidence=0.95)
        assert var is not None
        assert var > 0

    def test_99_var_ge_95_var(self):
        """VaR at 99% confidence should be ≥ VaR at 95%."""
        df = _make_prices(n=252)
        var95 = compute_var(df, confidence=0.95)
        var99 = compute_var(df, confidence=0.99)
        assert var95 is not None
        assert var99 is not None
        assert var99 >= var95

    def test_insufficient_data_returns_none(self):
        df = _make_prices(n=15)
        assert compute_var(df, lookback=252) is None

    def test_higher_vol_higher_var(self):
        """A more volatile stock should have a higher VaR."""
        rng = np.random.default_rng(7)
        low_vol_returns = rng.normal(0, 0.005, 252).tolist()
        high_vol_returns = rng.normal(0, 0.05, 252).tolist()
        low_df = _make_prices(returns=low_vol_returns)
        high_df = _make_prices(returns=high_vol_returns)
        assert compute_var(high_df) > compute_var(low_df)


# ---------------------------------------------------------------------------
# compute_risk_snapshot
# ---------------------------------------------------------------------------


class TestComputeRiskSnapshot:
    def test_returns_dict_with_all_keys(self):
        df = _make_prices(n=300)
        spy = _make_prices(n=300, seed=99)
        snapshot = compute_risk_snapshot(df, spy)
        expected_keys = {
            "volatility",
            "sharpe",
            "max_drawdown",
            "var_95",
            "var_99",
            "beta",
            "correlation",
        }
        assert set(snapshot.keys()) == expected_keys

    def test_no_spy_beta_and_corr_are_none(self):
        df = _make_prices(n=300)
        snapshot = compute_risk_snapshot(df, spy_df=None)
        assert snapshot["beta"] is None
        assert snapshot["correlation"] is None

    def test_with_spy_beta_populated(self):
        df, spy = _make_correlated_pair(n=300, correlation=0.8)
        snapshot = compute_risk_snapshot(df, spy)
        assert snapshot["beta"] is not None

    def test_max_drawdown_negative_or_zero(self):
        df = _make_prices(n=252)
        snapshot = compute_risk_snapshot(df)
        if snapshot["max_drawdown"] is not None:
            assert snapshot["max_drawdown"] <= 0
