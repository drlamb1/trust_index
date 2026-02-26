"""
EdgeFinder — Options Chain Data Ingestion

Fetches delayed options chain data for vol surface construction and
Heston calibration. Two data sources with automatic fallback:

  1. Polygon.io (primary) — 15-min delayed, free tier: 5 calls/min
  2. yfinance (fallback) — real-time but less reliable, no API key needed

The data feeds into the OptionsChain model and is consumed by:
  - simulation/vol_surface.py (IV surface construction)
  - simulation/heston.py (calibration to market IVs)
  - chat tools (Vol Surface Slayer, Heston Calibrator personas)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.models import OptionsChain, Ticker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Polygon.io Options Chain
# ---------------------------------------------------------------------------


async def _fetch_polygon_options(
    ticker_symbol: str,
    api_key: str,
    limit: int = 250,
) -> pd.DataFrame | None:
    """Fetch options chain from Polygon.io REST API (delayed data).

    Endpoint: GET /v3/snapshot/options/{underlyingAsset}
    Free tier: 5 calls/minute, 15-min delayed data.

    Returns DataFrame with standardized columns or None on failure.
    """
    url = f"https://api.polygon.io/v3/snapshot/options/{ticker_symbol}"
    params = {
        "limit": limit,
        "apiKey": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            logger.info("Polygon: no options data for %s", ticker_symbol)
            return None

        rows = []
        for item in results:
            details = item.get("details", {})
            greeks = item.get("greeks", {})
            day = item.get("day", {})
            last_quote = item.get("last_quote", {})

            rows.append({
                "expiration": details.get("expiration_date"),
                "strike": details.get("strike_price"),
                "call_put": details.get("contract_type", "").lower(),
                "bid": last_quote.get("bid", 0),
                "ask": last_quote.get("ask", 0),
                "last": day.get("close", 0),
                "volume": day.get("volume", 0),
                "open_interest": item.get("open_interest", 0),
                "implied_vol": item.get("implied_volatility"),
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega"),
            })

        df = pd.DataFrame(rows)
        df["expiration"] = pd.to_datetime(df["expiration"]).dt.date
        df["strike"] = pd.to_numeric(df["strike"], errors="coerce")

        logger.info("Polygon: fetched %d options for %s", len(df), ticker_symbol)
        return df

    except httpx.HTTPStatusError as e:
        logger.warning("Polygon API error for %s: %s", ticker_symbol, e.response.status_code)
        return None
    except Exception as e:
        logger.warning("Polygon fetch failed for %s: %s", ticker_symbol, e)
        return None


# ---------------------------------------------------------------------------
# yfinance Fallback
# ---------------------------------------------------------------------------


async def _fetch_yfinance_options(ticker_symbol: str) -> pd.DataFrame | None:
    """Fetch options chain via yfinance (no API key needed).

    yfinance provides real-time data but can be unreliable.
    We use it as a fallback when Polygon is unavailable.
    """
    try:
        import yfinance as yf

        ticker = yf.Ticker(ticker_symbol)
        expirations = ticker.options

        if not expirations:
            logger.info("yfinance: no options expirations for %s", ticker_symbol)
            return None

        all_rows = []
        for exp_str in expirations[:6]:  # limit to 6 nearest expirations
            try:
                chain = ticker.option_chain(exp_str)
                exp_date = pd.to_datetime(exp_str).date()

                for _, row in chain.calls.iterrows():
                    all_rows.append({
                        "expiration": exp_date,
                        "strike": float(row["strike"]),
                        "call_put": "call",
                        "bid": float(row.get("bid", 0)),
                        "ask": float(row.get("ask", 0)),
                        "last": float(row.get("lastPrice", 0)),
                        "volume": int(row.get("volume", 0) or 0),
                        "open_interest": int(row.get("openInterest", 0) or 0),
                        "implied_vol": float(row.get("impliedVolatility", 0) or 0),
                        "delta": None,
                        "gamma": None,
                        "theta": None,
                        "vega": None,
                    })

                for _, row in chain.puts.iterrows():
                    all_rows.append({
                        "expiration": exp_date,
                        "strike": float(row["strike"]),
                        "call_put": "put",
                        "bid": float(row.get("bid", 0)),
                        "ask": float(row.get("ask", 0)),
                        "last": float(row.get("lastPrice", 0)),
                        "volume": int(row.get("volume", 0) or 0),
                        "open_interest": int(row.get("openInterest", 0) or 0),
                        "implied_vol": float(row.get("impliedVolatility", 0) or 0),
                        "delta": None,
                        "gamma": None,
                        "theta": None,
                        "vega": None,
                    })
            except Exception as e:
                logger.debug("yfinance chain fetch failed for %s %s: %s", ticker_symbol, exp_str, e)

        if not all_rows:
            return None

        df = pd.DataFrame(all_rows)
        logger.info("yfinance: fetched %d options for %s", len(df), ticker_symbol)
        return df

    except ImportError:
        logger.error("yfinance not installed — cannot fetch options fallback")
        return None
    except Exception as e:
        logger.warning("yfinance options fetch failed for %s: %s", ticker_symbol, e)
        return None


# ---------------------------------------------------------------------------
# Unified Fetch + Store Pipeline
# ---------------------------------------------------------------------------


async def fetch_options_chain(ticker_symbol: str) -> pd.DataFrame | None:
    """Fetch options chain with Polygon → yfinance fallback.

    Returns standardized DataFrame or None if both sources fail.
    """
    # Try Polygon first (if API key available)
    if settings.has_polygon:
        df = await _fetch_polygon_options(ticker_symbol, settings.polygon_api_key)
        if df is not None and not df.empty:
            return df

    # Fallback to yfinance
    df = await _fetch_yfinance_options(ticker_symbol)
    return df


async def store_options_chain(
    session: AsyncSession,
    ticker_id: int,
    chain_df: pd.DataFrame,
) -> int:
    """Store options chain data to the OptionsChain table.

    Performs bulk insert (not upsert — we want timestamped snapshots).
    Returns count of rows inserted.
    """
    now = datetime.now(timezone.utc)
    count = 0

    for _, row in chain_df.iterrows():
        try:
            record = OptionsChain(
                ticker_id=ticker_id,
                expiration=row["expiration"],
                strike=row["strike"],
                call_put=row["call_put"],
                bid=row.get("bid"),
                ask=row.get("ask"),
                last=row.get("last"),
                volume=int(row.get("volume") or 0),
                open_interest=int(row.get("open_interest") or 0),
                implied_vol=row.get("implied_vol"),
                delta=row.get("delta"),
                gamma=row.get("gamma"),
                theta=row.get("theta"),
                vega=row.get("vega"),
                fetched_at=now,
            )
            session.add(record)
            count += 1
        except Exception as e:
            logger.debug("Skipping options row: %s", e)

    if count > 0:
        await session.flush()
        logger.info("Stored %d options chain rows for ticker_id=%d", count, ticker_id)

    return count


async def fetch_and_store_options(session: AsyncSession, ticker: Ticker) -> int:
    """Main pipeline: fetch options chain and store for one ticker.

    Returns count of rows stored.
    """
    chain_df = await fetch_options_chain(ticker.symbol)
    if chain_df is None or chain_df.empty:
        return 0

    return await store_options_chain(session, ticker.id, chain_df)


async def fetch_options_batch(session: AsyncSession) -> dict:
    """Fetch options for all active watchlist tickers.

    Returns summary dict with per-ticker results.
    """
    result = await session.execute(
        select(Ticker).where(Ticker.in_watchlist.is_(True), Ticker.is_active.is_(True))
    )
    tickers = result.scalars().all()

    summary = {"tickers_processed": 0, "total_options_stored": 0, "errors": []}

    for ticker in tickers:
        try:
            count = await fetch_and_store_options(session, ticker)
            summary["total_options_stored"] += count
            summary["tickers_processed"] += 1
        except Exception as e:
            logger.error("Options fetch failed for %s: %s", ticker.symbol, e)
            summary["errors"].append({"ticker": ticker.symbol, "error": str(e)})

    return summary
