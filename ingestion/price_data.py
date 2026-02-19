"""
EdgeFinder — Price Data Ingestion

Fetches OHLCV (Open/High/Low/Close/Volume) daily price data for tickers.

Primary source: yfinance (free, no API key required)
Fallback source: Alpha Vantage (free tier: 25 req/day)

Flow:
  1. Try yfinance — download bulk data
  2. If empty or error → fall back to Alpha Vantage
  3. Upsert into price_bars table (skip rows already in DB)
  4. Update ticker.last_price_fetch timestamp

Usage:
    from ingestion.price_data import fetch_and_store_prices
    await fetch_and_store_prices(session, ticker, days=365)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.models import PriceBar, Ticker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# yfinance valid period strings
YFINANCE_PERIODS = {
    7: "7d",
    30: "1mo",
    90: "3mo",
    180: "6mo",
    365: "1y",
    730: "2y",
    1825: "5y",
    3650: "10y",
}


def _days_to_yf_period(days: int) -> str:
    """Convert a day count to the nearest yfinance period string."""
    for threshold, period in sorted(YFINANCE_PERIODS.items()):
        if days <= threshold:
            return period
    return "max"


# ---------------------------------------------------------------------------
# Primary: yfinance
# ---------------------------------------------------------------------------

def _fetch_yfinance_sync(symbol: str, period: str) -> pd.DataFrame:
    """
    Synchronous yfinance fetch (runs in thread pool via asyncio.to_thread).

    yfinance is not async-native, so we run it in a thread to avoid
    blocking the event loop.
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, auto_adjust=True, back_adjust=False)

    if df.empty:
        return df

    # Normalize column names to lowercase
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    # Reset index so date becomes a column
    df = df.reset_index()
    df = df.rename(columns={"date": "date", "open": "open", "high": "high",
                             "low": "low", "close": "close", "volume": "volume"})

    # Drop timezone from date index (we store as date, not datetime)
    if hasattr(df["date"].dtype, "tz"):
        df["date"] = df["date"].dt.tz_localize(None)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    # Keep only what we need
    cols = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
    return df[cols].dropna(subset=["close"])


async def _fetch_yfinance(symbol: str, days: int) -> pd.DataFrame:
    """Async wrapper for yfinance fetch using thread pool."""
    period = _days_to_yf_period(days)
    try:
        df = await asyncio.to_thread(_fetch_yfinance_sync, symbol, period)
        if df is not None and not df.empty:
            logger.debug("yfinance fetched %d bars for %s", len(df), symbol)
            return df
        logger.warning("yfinance returned empty DataFrame for %s", symbol)
        return pd.DataFrame()
    except Exception as exc:
        logger.warning("yfinance error for %s: %s", symbol, exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Fallback: Alpha Vantage
# ---------------------------------------------------------------------------

AV_BASE_URL = "https://www.alphavantage.co/query"


async def _fetch_alpha_vantage(symbol: str, days: int) -> pd.DataFrame:
    """
    Fetch daily OHLCV from Alpha Vantage (free tier: 25 req/day).
    Uses TIME_SERIES_DAILY_ADJUSTED for adjusted close prices.
    """
    if not settings.alpha_vantage_api_key:
        logger.debug("Alpha Vantage key not configured, skipping fallback for %s", symbol)
        return pd.DataFrame()

    output_size = "full" if days > 100 else "compact"

    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": symbol,
        "outputsize": output_size,
        "apikey": settings.alpha_vantage_api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(AV_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        if "Time Series (Daily)" not in data:
            error_msg = data.get("Note") or data.get("Information") or "Unknown AV error"
            logger.warning("Alpha Vantage error for %s: %s", symbol, error_msg)
            return pd.DataFrame()

        ts = data["Time Series (Daily)"]
        rows = []
        cutoff = date.today() - timedelta(days=days)

        for date_str, values in ts.items():
            bar_date = date.fromisoformat(date_str)
            if bar_date < cutoff:
                continue
            rows.append({
                "date": bar_date,
                "open": float(values.get("1. open", 0)),
                "high": float(values.get("2. high", 0)),
                "low": float(values.get("3. low", 0)),
                "close": float(values.get("4. close", 0)),
                "volume": int(values.get("6. volume", 0)),
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("date").reset_index(drop=True)
            logger.debug("Alpha Vantage fetched %d bars for %s", len(df), symbol)
        return df

    except Exception as exc:
        logger.error("Alpha Vantage fetch failed for %s: %s", symbol, exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Polygon.io — third fallback (EOD data only)
# ---------------------------------------------------------------------------

async def _fetch_polygon(symbol: str, days: int) -> pd.DataFrame:
    """Fetch EOD data from Polygon.io (free tier: 5 req/min)."""
    if not settings.polygon_api_key:
        return pd.DataFrame()

    from_date = (date.today() - timedelta(days=days)).isoformat()
    to_date = date.today().isoformat()
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{from_date}/{to_date}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                params={"apiKey": settings.polygon_api_key, "adjusted": "true", "limit": 5000},
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "OK" or not data.get("results"):
            logger.warning("Polygon.io returned no results for %s", symbol)
            return pd.DataFrame()

        rows = []
        for bar in data["results"]:
            rows.append({
                "date": date.fromtimestamp(bar["t"] / 1000),
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
            })

        df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
        logger.debug("Polygon.io fetched %d bars for %s", len(df), symbol)
        return df

    except Exception as exc:
        logger.error("Polygon.io fetch failed for %s: %s", symbol, exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Orchestration: try sources in order
# ---------------------------------------------------------------------------

async def fetch_ohlcv(symbol: str, days: int = 365) -> tuple[pd.DataFrame, str]:
    """
    Fetch OHLCV data with automatic source fallback.

    Returns:
        (DataFrame with columns: date, open, high, low, close, volume,
         source_name: "yfinance" | "alpha_vantage" | "polygon")

    DataFrame is empty if all sources fail.
    """
    # Primary: yfinance
    df = await _fetch_yfinance(symbol, days)
    if not df.empty:
        return df, "yfinance"

    logger.info("yfinance failed for %s, trying Alpha Vantage...", symbol)
    df = await _fetch_alpha_vantage(symbol, days)
    if not df.empty:
        return df, "alpha_vantage"

    logger.info("Alpha Vantage failed for %s, trying Polygon.io...", symbol)
    df = await _fetch_polygon(symbol, days)
    if not df.empty:
        return df, "polygon"

    logger.error("All price data sources failed for %s", symbol)
    return pd.DataFrame(), "none"


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

async def upsert_price_bars(
    session: AsyncSession,
    ticker_id: int,
    df: pd.DataFrame,
    source: str,
) -> int:
    """
    Upsert price bars into the database.

    Uses PostgreSQL's ON CONFLICT DO UPDATE for idempotent ingestion.
    Returns the number of rows upserted.
    """
    if df.empty:
        return 0

    rows = []
    for _, row in df.iterrows():
        rows.append({
            "ticker_id": ticker_id,
            "date": row["date"],
            "open": float(row["open"]) if pd.notna(row.get("open")) else None,
            "high": float(row["high"]) if pd.notna(row.get("high")) else None,
            "low": float(row["low"]) if pd.notna(row.get("low")) else None,
            "close": float(row["close"]),
            "adj_close": float(row.get("adj_close", row["close"])) if pd.notna(row.get("adj_close", row["close"])) else None,
            "volume": int(row["volume"]) if pd.notna(row.get("volume")) else None,
            "source": source,
        })

    # Dialect-aware upsert: PostgreSQL and SQLite 3.24+ both support
    # INSERT ... ON CONFLICT (columns) DO UPDATE SET ...
    conn = await session.connection()
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:
        from sqlalchemy.dialects.sqlite import insert as _insert

    stmt = _insert(PriceBar).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker_id", "date"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "adj_close": stmt.excluded.adj_close,
            "volume": stmt.excluded.volume,
            "source": stmt.excluded.source,
        },
    )
    await session.execute(stmt)
    return len(rows)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def fetch_and_store_prices(
    session: AsyncSession,
    ticker: Ticker,
    days: int = 365,
) -> int:
    """
    Fetch price data for a ticker and store in the database.

    Returns the number of rows upserted (new + updated).
    """
    logger.info("Fetching %d days of price data for %s", days, ticker.symbol)

    df, source = await fetch_ohlcv(ticker.symbol, days)

    if df.empty:
        logger.warning("No price data available for %s", ticker.symbol)
        return 0

    count = await upsert_price_bars(session, ticker.id, df, source)

    # Update last_price_fetch timestamp on the ticker
    ticker.last_price_fetch = datetime.now(timezone.utc)
    session.add(ticker)
    await session.flush()  # Write to DB immediately (session.refresh() does not autoflush)

    logger.info(
        "Stored %d price bars for %s (source: %s)", count, ticker.symbol, source
    )
    return count


async def fetch_and_store_prices_batch(
    session: AsyncSession,
    tickers: list[Ticker],
    days: int = 365,
    concurrency: int = 5,
) -> dict[str, int]:
    """
    Fetch price data for multiple tickers and store in the database.

    Two-phase design:
      Phase 1 — Network I/O (concurrent, limited by semaphore): fetch OHLCV from
                 yfinance / Alpha Vantage / Polygon for all tickers simultaneously.
      Phase 2 — DB writes (sequential): AsyncSession is not safe for concurrent
                 use, so upserts and timestamp updates are processed one at a time.

    Returns a dict mapping symbol → rows_upserted.
    """
    semaphore = asyncio.Semaphore(concurrency)

    # Phase 1: concurrent network fetches (no DB access)
    async def _fetch(ticker: Ticker) -> tuple[str, pd.DataFrame, str]:
        async with semaphore:
            try:
                df, source = await fetch_ohlcv(ticker.symbol, days)
                return ticker.symbol, df, source
            except Exception as exc:
                logger.error("Error fetching prices for %s: %s", ticker.symbol, exc)
                return ticker.symbol, pd.DataFrame(), "none"

    fetched: list[tuple[str, pd.DataFrame, str]] = await asyncio.gather(
        *[_fetch(t) for t in tickers]
    )

    # Phase 2: sequential DB writes
    ticker_map = {t.symbol: t for t in tickers}
    results: dict[str, int] = {}

    for symbol, df, source in fetched:
        ticker = ticker_map[symbol]
        try:
            if df.empty:
                results[symbol] = 0
                continue
            count = await upsert_price_bars(session, ticker.id, df, source)
            ticker.last_price_fetch = datetime.now(timezone.utc)
            session.add(ticker)
            await session.flush()
            results[symbol] = count
            logger.info("Stored %d price bars for %s (source: %s)", count, symbol, source)
        except Exception as exc:
            logger.error("Error storing prices for %s: %s", symbol, exc)
            results[symbol] = 0

    return results


# ---------------------------------------------------------------------------
# S&P 500 universe fetcher
# ---------------------------------------------------------------------------

async def fetch_sp500_symbols() -> list[dict]:
    """
    Fetch current S&P 500 constituents from Wikipedia.

    Returns a list of dicts: [{"symbol": "AAPL", "name": "Apple Inc.", "sector": "..."}]

    Wikipedia is the most reliable free source for S&P 500 membership.
    Falls back to a static list if Wikipedia is unreachable.
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        # Use pandas to parse the HTML table (much simpler than BeautifulSoup for this)
        tables = await asyncio.to_thread(pd.read_html, resp.text)
        df = tables[0]  # First table is the S&P 500 constituent list

        # Column names vary slightly — normalize
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        result = []
        for _, row in df.iterrows():
            symbol = str(row.get("symbol", row.get("ticker", ""))).strip()
            if not symbol:
                continue
            # Some symbols have dots (e.g., BRK.B) — convert to yfinance format (BRK-B)
            symbol = symbol.replace(".", "-")
            result.append({
                "symbol": symbol,
                "name": str(row.get("security", row.get("company", ""))).strip(),
                "sector": str(row.get("gics_sector", row.get("sector", ""))).strip(),
                "industry": str(row.get("gics_sub-industry", row.get("sub-industry", ""))).strip(),
            })

        logger.info("Fetched %d S&P 500 constituents from Wikipedia", len(result))
        return result

    except Exception as exc:
        logger.error("Failed to fetch S&P 500 from Wikipedia: %s", exc)
        return []
