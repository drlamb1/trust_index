"""
EdgeFinder — Risk Metrics

Computes security-level risk metrics from historical OHLCV price data.

All functions accept pandas DataFrames (same format as Phase 1 technicals)
and return scalar floats or None when there is insufficient data.

Metrics:
    Beta          — Cov(ticker, SPY) / Var(SPY), rolling 252 trading days
    Sharpe ratio  — Annualized excess return / annualized volatility
    Max drawdown  — Worst peak-to-trough decline over full history
    Volatility    — Annualized std dev of daily log returns (= σ √252)
    Correlation   — Pearson correlation of daily returns vs SPY
    Value at Risk — Historical 1-day VaR at 95% / 99% confidence
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Fallback risk-free rate when FRED data unavailable
DEFAULT_RISK_FREE_RATE = 0.05  # 5% annual


async def get_risk_free_rate() -> float:
    """
    Fetch the latest 10-Year Treasury yield (DGS10) from the macro_indicators
    table. Returns the yield as a decimal (e.g. 0.043 for 4.3%).

    Falls back to DEFAULT_RISK_FREE_RATE if no FRED data available.
    """
    try:
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import MacroIndicator

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(MacroIndicator.value)
                .where(MacroIndicator.series_id == "DGS10")
                .order_by(MacroIndicator.date.desc())
                .limit(1)
            )
            value = result.scalar_one_or_none()
            if value is not None:
                # FRED DGS10 is in percent (e.g. 4.3), convert to decimal
                return float(value) / 100.0
    except Exception as exc:
        logger.debug("Could not fetch DGS10 from DB, using default: %s", exc)

    return DEFAULT_RISK_FREE_RATE


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _daily_log_returns(df: pd.DataFrame, price_col: str = "close") -> pd.Series:
    """Compute daily log returns from a price column, dropping the first NaN."""
    return np.log(df[price_col] / df[price_col].shift(1)).dropna()


def _align_returns(
    ticker_df: pd.DataFrame,
    spy_df: pd.DataFrame,
    lookback: int,
) -> pd.DataFrame | None:
    """
    Align two price DataFrames on their shared dates and compute simple returns.

    Returns a DataFrame with columns ["ticker", "spy"], or None if <30 rows.
    """
    if ticker_df.empty or spy_df.empty:
        return None
    if "date" not in ticker_df.columns or "date" not in spy_df.columns:
        return None

    t = ticker_df.set_index("date")["close"].pct_change().dropna()
    s = spy_df.set_index("date")["close"].pct_change().dropna()
    aligned = pd.concat({"ticker": t, "spy": s}, axis=1, join="inner").dropna()
    aligned = aligned.tail(lookback)
    return aligned if len(aligned) >= 30 else None


# ---------------------------------------------------------------------------
# Beta
# ---------------------------------------------------------------------------


def compute_beta(
    ticker_df: pd.DataFrame,
    spy_df: pd.DataFrame,
    lookback: int = 252,
) -> float | None:
    """
    Compute rolling beta of the ticker vs SPY.

    Beta = Cov(ticker_returns, spy_returns) / Var(spy_returns)
    Returns None if insufficient overlapping data (<30 days).
    """
    aligned = _align_returns(ticker_df, spy_df, lookback)
    if aligned is None:
        return None

    cov = np.cov(aligned["ticker"].values, aligned["spy"].values)
    spy_var = cov[1, 1]
    if spy_var == 0:
        return None
    return float(cov[0, 1] / spy_var)


# ---------------------------------------------------------------------------
# Sharpe ratio
# ---------------------------------------------------------------------------


def compute_sharpe_ratio(
    df: pd.DataFrame,
    lookback: int = 252,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float | None:
    """
    Compute the annualized Sharpe ratio over the last `lookback` trading days.

    Sharpe = (annualized_return - risk_free_rate) / annualized_volatility
    Returns None if insufficient data or zero volatility.
    """
    ret = _daily_log_returns(df).tail(lookback)
    if len(ret) < 30:
        return None

    daily_std = float(ret.std())
    if daily_std == 0:
        return None

    annual_return = float(ret.mean()) * 252
    annual_vol = daily_std * np.sqrt(252)
    return float((annual_return - risk_free_rate) / annual_vol)


# ---------------------------------------------------------------------------
# Max drawdown
# ---------------------------------------------------------------------------


def compute_max_drawdown(df: pd.DataFrame, price_col: str = "close") -> float | None:
    """
    Compute the maximum peak-to-trough drawdown over the full price history.

    Returns a negative float (e.g. -0.35 for a 35% drawdown), or None.
    """
    prices = df[price_col].dropna()
    if len(prices) < 2:
        return None

    rolling_peak = prices.cummax()
    drawdowns = (prices - rolling_peak) / rolling_peak
    return float(drawdowns.min())


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------


def compute_volatility(df: pd.DataFrame, lookback: int = 252) -> float | None:
    """
    Compute annualized historical volatility (std dev of log returns × √252).

    Returns None if fewer than 10 return observations.
    """
    ret = _daily_log_returns(df).tail(lookback)
    if len(ret) < 10:
        return None
    return float(ret.std() * np.sqrt(252))


# ---------------------------------------------------------------------------
# Correlation vs SPY
# ---------------------------------------------------------------------------


def compute_correlation(
    ticker_df: pd.DataFrame,
    spy_df: pd.DataFrame,
    lookback: int = 252,
) -> float | None:
    """
    Compute Pearson correlation of daily returns vs SPY over `lookback` days.

    Returns a float in [-1, 1], or None if insufficient data.
    """
    aligned = _align_returns(ticker_df, spy_df, lookback)
    if aligned is None:
        return None
    return float(aligned["ticker"].corr(aligned["spy"]))


# ---------------------------------------------------------------------------
# Value at Risk
# ---------------------------------------------------------------------------


def compute_var(
    df: pd.DataFrame,
    confidence: float = 0.95,
    lookback: int = 252,
) -> float | None:
    """
    Compute 1-day historical Value at Risk at the given confidence level.

    Returns the loss magnitude as a positive fraction:
        compute_var(df, 0.95) = 0.025 → 95% of days the loss is ≤ 2.5%
    Returns None if fewer than 30 observations.
    """
    ret = _daily_log_returns(df).tail(lookback)
    if len(ret) < 30:
        return None
    return abs(float(ret.quantile(1.0 - confidence)))


# ---------------------------------------------------------------------------
# Composite snapshot
# ---------------------------------------------------------------------------


def compute_risk_snapshot(
    ticker_df: pd.DataFrame,
    spy_df: pd.DataFrame | None = None,
    lookback: int = 252,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict:
    """
    Compute all risk metrics for a ticker in one pass.

    Returns a dict suitable for storage or API response:
        {volatility, sharpe, max_drawdown, var_95, var_99, beta, correlation}
    """
    result: dict = {
        "volatility": compute_volatility(ticker_df, lookback),
        "sharpe": compute_sharpe_ratio(ticker_df, lookback, risk_free_rate),
        "max_drawdown": compute_max_drawdown(ticker_df),
        "var_95": compute_var(ticker_df, confidence=0.95, lookback=lookback),
        "var_99": compute_var(ticker_df, confidence=0.99, lookback=lookback),
        "beta": None,
        "correlation": None,
    }

    if spy_df is not None and not spy_df.empty:
        result["beta"] = compute_beta(ticker_df, spy_df, lookback)
        result["correlation"] = compute_correlation(ticker_df, spy_df, lookback)

    return result
