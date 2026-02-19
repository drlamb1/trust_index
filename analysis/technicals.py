"""
EdgeFinder — Technical Indicators Engine

Computes technical indicators from OHLCV price data and stores snapshots
in the technical_snapshots table.

Uses pandas-ta for efficient vectorized computation of all indicators in
a single pass via ta.strategy("All") or targeted strategy.

Indicators computed:
  Trend:     SMA 20/50/100/200, EMA 20/50
  Momentum:  RSI(14), MACD(12,26,9)
  Volatility: Bollinger Bands(20,2), ATR(14)
  Volume:    Volume ratio vs 20-day average
  Relative:  Return vs SPY over 20 days

Usage:
    from analysis.technicals import compute_and_store_technicals
    await compute_and_store_technicals(session, ticker)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pandas_ta as ta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import PriceBar, TechnicalSnapshot, Ticker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Indicator computation
# ---------------------------------------------------------------------------


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all technical indicators for a price DataFrame.

    Input DataFrame must have columns: date, open, high, low, close, volume
    (all lowercase). Index should be RangeIndex (not DatetimeIndex).

    Returns the same DataFrame with additional indicator columns.
    Rows with insufficient history for an indicator will have NaN.
    """
    if df.empty or len(df) < 20:
        logger.warning("Insufficient price data (%d rows) for indicator computation", len(df))
        return df

    # pandas-ta expects specific column names
    df = df.copy()
    df = df.rename(
        columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    )

    # --- Moving Averages ---
    df["sma_20"] = ta.sma(df["Close"], length=20)
    df["sma_50"] = ta.sma(df["Close"], length=50)
    df["sma_100"] = ta.sma(df["Close"], length=100)
    df["sma_200"] = ta.sma(df["Close"], length=200)
    df["ema_20"] = ta.ema(df["Close"], length=20)
    df["ema_50"] = ta.ema(df["Close"], length=50)

    # --- Momentum ---
    df["rsi_14"] = ta.rsi(df["Close"], length=14)

    macd_df = ta.macd(df["Close"], fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        df["macd"] = macd_df.iloc[:, 0]  # MACD line
        df["macd_histogram"] = macd_df.iloc[:, 1]  # Histogram
        df["macd_signal"] = macd_df.iloc[:, 2]  # Signal line

    # --- Volatility ---
    bbands_df = ta.bbands(df["Close"], length=20, std=2)
    if bbands_df is not None and not bbands_df.empty:
        # Columns are: BBL, BBM, BBU, BBB, BBP (lower, middle, upper, bandwidth, %)
        df["bb_lower"] = bbands_df.iloc[:, 0]
        df["bb_middle"] = bbands_df.iloc[:, 1]
        df["bb_upper"] = bbands_df.iloc[:, 2]
        df["bb_bandwidth"] = bbands_df.iloc[:, 3]

    df["atr_14"] = ta.atr(df["High"], df["Low"], df["Close"], length=14)

    # --- Volume ---
    vol_ma_20 = df["Volume"].rolling(window=20).mean()
    df["volume_ratio_20d"] = df["Volume"] / vol_ma_20

    # Rename back to lowercase
    df = df.rename(
        columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    )

    return df


def _safe_float(val) -> float | None:
    """Convert a value to float, returning None for NaN/None."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) or np.isinf(f) else f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Relative strength vs SPY
# ---------------------------------------------------------------------------


def compute_relative_strength(
    ticker_df: pd.DataFrame,
    spy_df: pd.DataFrame,
    lookback: int = 20,
) -> pd.Series:
    """
    Compute relative price return vs SPY over `lookback` trading days.

    Returns a Series with the same index as ticker_df.
    Positive values mean the ticker outperformed SPY.
    """
    if spy_df.empty or ticker_df.empty:
        return pd.Series(dtype=float, index=ticker_df.index)

    # Align on date
    spy_aligned = spy_df.set_index("date")["close"].pct_change(lookback)
    ticker_aligned = ticker_df.set_index("date")["close"].pct_change(lookback)

    rs = (ticker_aligned - spy_aligned).reset_index(drop=True)
    return rs * 100  # as percentage


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------


async def upsert_technical_snapshots(
    session: AsyncSession,
    ticker_id: int,
    df: pd.DataFrame,
) -> int:
    """
    Upsert technical snapshots for a ticker.

    Only upserts rows for dates that have complete close price data.
    Returns number of rows upserted.
    """
    if df.empty:
        return 0

    indicator_cols = [
        "sma_20",
        "sma_50",
        "sma_100",
        "sma_200",
        "ema_20",
        "ema_50",
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_histogram",
        "bb_upper",
        "bb_middle",
        "bb_lower",
        "bb_bandwidth",
        "atr_14",
        "volume_ratio_20d",
    ]

    rows = []
    for _, row in df.iterrows():
        if pd.isna(row.get("close")):
            continue

        row_data = {"ticker_id": ticker_id, "date": row["date"]}
        for col in indicator_cols:
            row_data[col] = _safe_float(row.get(col))

        # rs_vs_spy_20d is added separately when SPY data is available
        row_data["rs_vs_spy_20d"] = _safe_float(row.get("rs_vs_spy_20d"))

        rows.append(row_data)

    if not rows:
        return 0

    conn = await session.connection()
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:
        from sqlalchemy.dialects.sqlite import insert as _insert

    stmt = _insert(TechnicalSnapshot).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker_id", "date"],
        set_={col: stmt.excluded[col] for col in indicator_cols + ["rs_vs_spy_20d"]},
    )
    await session.execute(stmt)
    logger.debug("Upserted %d technical snapshots for ticker_id=%d", len(rows), ticker_id)
    return len(rows)


# ---------------------------------------------------------------------------
# Load price bars from DB
# ---------------------------------------------------------------------------


async def load_price_bars(
    session: AsyncSession,
    ticker_id: int,
    days: int = 400,  # Slightly more than 200 to ensure SMA200 has data
) -> pd.DataFrame:
    """Load OHLCV bars from the database for indicator computation."""
    cutoff = date.today() - timedelta(days=days)

    result = await session.execute(
        select(PriceBar)
        .where(PriceBar.ticker_id == ticker_id, PriceBar.date >= cutoff)
        .order_by(PriceBar.date.asc())
    )
    bars = result.scalars().all()

    if not bars:
        return pd.DataFrame()

    rows = [
        {
            "date": b.date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume or 0,
        }
        for b in bars
    ]

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def compute_and_store_technicals(
    session: AsyncSession,
    ticker: Ticker,
    spy_df: pd.DataFrame | None = None,
) -> int:
    """
    Compute technical indicators for a ticker and store in the database.

    Args:
        session: Async DB session
        ticker: Ticker ORM object
        spy_df: Optional pre-loaded SPY price DataFrame for relative strength.
                If None, relative strength is skipped.

    Returns:
        Number of snapshots upserted.
    """
    logger.info("Computing technicals for %s", ticker.symbol)

    # Load price bars from DB
    df = await load_price_bars(session, ticker.id, days=400)

    if df.empty:
        logger.warning("No price bars in DB for %s — run price ingestion first", ticker.symbol)
        return 0

    # Compute all indicators
    df = compute_indicators(df)

    # Add relative strength vs SPY if available
    if spy_df is not None and not spy_df.empty:
        rs = compute_relative_strength(df, spy_df, lookback=20)
        df["rs_vs_spy_20d"] = rs.values

    # Upsert to DB
    count = await upsert_technical_snapshots(session, ticker.id, df)
    logger.info("Stored %d technical snapshots for %s", count, ticker.symbol)
    return count


async def compute_technicals_batch(
    session: AsyncSession,
    tickers: list[Ticker],
    include_spy_rs: bool = True,
) -> dict[str, int]:
    """
    Compute technical indicators for multiple tickers.

    Loads SPY data once (for relative strength calculation) and reuses it.
    """
    spy_df: pd.DataFrame | None = None

    if include_spy_rs:
        # Find SPY ticker in DB
        result = await session.execute(select(Ticker).where(Ticker.symbol == "SPY"))
        spy_ticker = result.scalar_one_or_none()
        if spy_ticker:
            spy_df = await load_price_bars(session, spy_ticker.id, days=400)

    results: dict[str, int] = {}
    for ticker in tickers:
        try:
            count = await compute_and_store_technicals(session, ticker, spy_df=spy_df)
            results[ticker.symbol] = count
        except Exception as exc:
            logger.error("Failed to compute technicals for %s: %s", ticker.symbol, exc)
            results[ticker.symbol] = 0

    return results


# ---------------------------------------------------------------------------
# Signal detection helpers (used by alert engine)
# ---------------------------------------------------------------------------


def detect_golden_cross(df: pd.DataFrame) -> bool:
    """
    Returns True if SMA50 crossed above SMA200 in the last 3 bars.
    Classic bullish signal.
    """
    if "sma_50" not in df.columns or "sma_200" not in df.columns:
        return False
    if len(df) < 4:
        return False

    recent = df.tail(4)
    # Check: 3+ bars ago, SMA50 was BELOW SMA200; today SMA50 is ABOVE SMA200
    prev_below = (recent.iloc[0]["sma_50"] or 0) < (recent.iloc[0]["sma_200"] or 0)
    now_above = (recent.iloc[-1]["sma_50"] or 0) > (recent.iloc[-1]["sma_200"] or 0)
    return bool(prev_below and now_above)


def detect_bollinger_squeeze(df: pd.DataFrame, threshold: float = 0.03) -> bool:
    """
    Returns True if Bollinger Band bandwidth is unusually narrow (squeeze).
    A squeeze often precedes a large directional move.
    threshold: bandwidth / price ratio below which a squeeze is detected
    """
    if "bb_bandwidth" not in df.columns or "close" not in df.columns:
        return False

    recent = df.tail(5).dropna(subset=["bb_bandwidth", "close"])
    if recent.empty:
        return False

    last = recent.iloc[-1]
    normalized_bw = last["bb_bandwidth"] / last["close"]
    return bool(normalized_bw < threshold)


def get_rsi_signal(rsi: float | None) -> str:
    """Classify RSI value into a human-readable signal."""
    if rsi is None:
        return "unknown"
    if rsi < 20:
        return "extremely_oversold"
    if rsi < 30:
        return "oversold"
    if rsi < 45:
        return "weak"
    if rsi < 55:
        return "neutral"
    if rsi < 70:
        return "strong"
    if rsi < 80:
        return "overbought"
    return "extremely_overbought"
