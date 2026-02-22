"""
EdgeFinder — FRED Macroeconomic Indicators

Fetches key economic data series from the FRED API (Federal Reserve Bank
of St. Louis) and stores them as daily observations.

Key series:
    FEDFUNDS  — Federal funds effective rate
    DGS10     — 10-Year Treasury constant maturity
    DGS2      — 2-Year Treasury constant maturity
    T10Y2Y    — 10Y-2Y yield spread (recession predictor)
    UNRATE    — Unemployment rate
    CPIAUCSL  — Consumer Price Index (all urban, seasonally adjusted)

Run manually:
    python cli.py ingest macro
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import MacroIndicator

logger = logging.getLogger(__name__)

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Series we track, with human-readable names
FRED_SERIES: dict[str, str] = {
    "FEDFUNDS": "Fed Funds Rate",
    "DGS10": "10-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
    "T10Y2Y": "10Y-2Y Yield Spread",
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "CPI (All Urban)",
}


async def fetch_fred_series(
    series_id: str,
    api_key: str,
    days: int = 365,
) -> list[dict]:
    """
    Fetch observations for a single FRED series.

    Returns list of {"date": date, "value": float} dicts.
    Skips observations where value is "." (missing data).
    """
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "sort_order": "desc",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(FRED_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("FRED API error for %s: %s", series_id, exc)
        return []

    observations = []
    for obs in data.get("observations", []):
        value_str = obs.get("value", ".")
        if value_str == ".":
            continue
        try:
            observations.append({
                "date": datetime.strptime(obs["date"], "%Y-%m-%d").date(),
                "value": float(value_str),
            })
        except (ValueError, KeyError):
            continue

    return observations


async def fetch_and_store_macro(
    session: AsyncSession,
    api_key: str,
    days: int = 365,
) -> dict[str, int]:
    """
    Fetch all tracked FRED series and upsert to macro_indicators table.

    Returns dict mapping series_id → rows upserted.
    """
    results: dict[str, int] = {}

    for series_id, series_name in FRED_SERIES.items():
        observations = await fetch_fred_series(series_id, api_key, days)
        if not observations:
            results[series_id] = 0
            continue

        rows = [
            {
                "series_id": series_id,
                "date": obs["date"],
                "value": obs["value"],
                "series_name": series_name,
            }
            for obs in observations
        ]

        stmt = pg_insert(MacroIndicator).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_macro_series_date",
            set_={"value": stmt.excluded.value, "series_name": stmt.excluded.series_name},
        )
        await session.execute(stmt)
        results[series_id] = len(rows)
        logger.info("FRED %s: upserted %d observations", series_id, len(rows))

    await session.flush()
    total = sum(results.values())
    logger.info("Macro data: %d total observations across %d series", total, len(results))
    return results


async def get_latest_macro(
    session: AsyncSession,
) -> list[dict]:
    """
    Return the latest observation for each tracked FRED series.
    Used by chat tools and daily briefing.
    """
    from sqlalchemy import select, func

    # Subquery: max date per series
    subq = (
        select(
            MacroIndicator.series_id,
            func.max(MacroIndicator.date).label("max_date"),
        )
        .group_by(MacroIndicator.series_id)
        .subquery()
    )

    result = await session.execute(
        select(MacroIndicator)
        .join(
            subq,
            (MacroIndicator.series_id == subq.c.series_id)
            & (MacroIndicator.date == subq.c.max_date),
        )
    )
    rows = result.scalars().all()

    indicators = []
    for row in rows:
        indicators.append({
            "series_id": row.series_id,
            "series_name": row.series_name or FRED_SERIES.get(row.series_id, row.series_id),
            "date": row.date.isoformat(),
            "value": row.value,
        })
    return indicators


async def get_macro_trend(
    session: AsyncSession,
    series_id: str,
    days: int = 30,
) -> list[dict]:
    """Return recent observations for a single series (for trend analysis)."""
    from sqlalchemy import select

    cutoff = (datetime.now() - timedelta(days=days)).date()
    result = await session.execute(
        select(MacroIndicator)
        .where(
            MacroIndicator.series_id == series_id,
            MacroIndicator.date >= cutoff,
        )
        .order_by(MacroIndicator.date)
    )
    rows = result.scalars().all()
    return [
        {"date": r.date.isoformat(), "value": r.value}
        for r in rows
    ]
