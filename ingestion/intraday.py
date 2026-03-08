"""
EdgeFinder — Intraday Price Data Ingestion

Fetches hourly OHLCV bars for watchlist tickers during market hours.
Uses yfinance (free, no API key) with 1h interval.

Budget-conscious design:
  - Only fetches for watchlist tickers (typically 20-40), not all 500
  - Runs 3x during market hours (open, midday, close)
  - Hourly bars, not minute-level (minimizes storage and API load)
  - Auto-prunes bars older than 5 trading days (keeps DB lean)

Usage:
    from ingestion.intraday import fetch_and_store_intraday_batch
    await fetch_and_store_intraday_batch(session)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import IntradayBar, Ticker

logger = logging.getLogger(__name__)

# Keep intraday data for this many calendar days before pruning
RETENTION_DAYS = 7


def _fetch_intraday_sync(symbol: str, interval: str = "1h") -> pd.DataFrame:
    """
    Synchronous yfinance fetch for intraday data.

    yfinance intraday constraints:
      - 1m: max 7 days
      - 5m/15m/30m: max 60 days
      - 1h: max 730 days
    We use 1h with period="5d" — gets this week's hourly bars.
    """
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="5d", interval=interval, auto_adjust=True)

        if df.empty:
            return df

        df = df.reset_index()
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        # Unify datetime column name
        dt_col = None
        for candidate in ["datetime", "date", "index"]:
            if candidate in df.columns:
                dt_col = candidate
                break
        if dt_col is None:
            return pd.DataFrame()

        if dt_col != "timestamp":
            df = df.rename(columns={dt_col: "timestamp"})

        # Ensure timezone-aware UTC timestamps
        if hasattr(df["timestamp"].dtype, "tz") and df["timestamp"].dtype.tz is not None:
            df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize("UTC")

        cols = [c for c in ["timestamp", "open", "high", "low", "close", "volume"]
                if c in df.columns]
        return df[cols].dropna(subset=["close"])

    except Exception as exc:
        logger.warning("Intraday fetch failed for %s: %s", symbol, exc)
        return pd.DataFrame()


async def fetch_intraday(symbol: str, interval: str = "1h") -> pd.DataFrame:
    """Async wrapper for intraday fetch."""
    return await asyncio.to_thread(_fetch_intraday_sync, symbol, interval)


async def upsert_intraday_bars(
    session: AsyncSession,
    ticker_id: int,
    df: pd.DataFrame,
    interval: str = "1h",
) -> int:
    """Upsert intraday bars for a ticker."""
    if df.empty:
        return 0

    rows = []
    for _, row in df.iterrows():
        rows.append({
            "ticker_id": ticker_id,
            "timestamp": row["timestamp"],
            "interval": interval,
            "open": float(row["open"]) if pd.notna(row.get("open")) else None,
            "high": float(row["high"]) if pd.notna(row.get("high")) else None,
            "low": float(row["low"]) if pd.notna(row.get("low")) else None,
            "close": float(row["close"]),
            "volume": int(row["volume"]) if pd.notna(row.get("volume")) else None,
            "source": "yfinance",
        })

    conn = await session.connection()
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:
        from sqlalchemy.dialects.sqlite import insert as _insert

    stmt = _insert(IntradayBar).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker_id", "timestamp", "interval"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    await session.execute(stmt)
    return len(rows)


async def prune_old_intraday(session: AsyncSession) -> int:
    """Remove intraday bars older than RETENTION_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    result = await session.execute(
        delete(IntradayBar).where(IntradayBar.timestamp < cutoff)
    )
    deleted = result.rowcount
    if deleted:
        logger.info("Pruned %d old intraday bars (before %s)", deleted, cutoff.date())
    return deleted


async def fetch_and_store_intraday_batch(
    session: AsyncSession,
    interval: str = "1h",
    concurrency: int = 5,
) -> dict:
    """
    Fetch intraday bars for all watchlist tickers.

    Only targets watchlist tickers to keep API calls low (~20-40 tickers).
    Also prunes old data to keep DB lean.
    """
    result = await session.execute(
        select(Ticker).where(Ticker.in_watchlist.is_(True), Ticker.is_active.is_(True))
    )
    tickers = result.scalars().all()

    if not tickers:
        logger.info("No watchlist tickers for intraday fetch")
        return {"tickers": 0, "bars": 0}

    semaphore = asyncio.Semaphore(concurrency)

    async def _fetch(ticker: Ticker) -> tuple[str, pd.DataFrame]:
        async with semaphore:
            df = await fetch_intraday(ticker.symbol, interval)
            return ticker.symbol, df

    fetched = await asyncio.gather(*[_fetch(t) for t in tickers])

    ticker_map = {t.symbol: t for t in tickers}
    total_bars = 0

    for symbol, df in fetched:
        ticker = ticker_map[symbol]
        try:
            count = await upsert_intraday_bars(session, ticker.id, df, interval)
            total_bars += count
        except Exception as exc:
            logger.error("Error storing intraday bars for %s: %s", symbol, exc)

    # Prune old data
    pruned = await prune_old_intraday(session)

    logger.info(
        "Intraday batch: %d tickers, %d bars upserted, %d old bars pruned",
        len(tickers), total_bars, pruned,
    )
    return {"tickers": len(tickers), "bars": total_bars, "pruned": pruned}
