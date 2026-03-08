"""
EdgeFinder — Fundamental Financial Data Ingestion

Fetches structured financial metrics from yfinance (free, no API key)
and populates the financial_metrics table.

Metrics extracted:
  Valuation:    pe_ratio, price_to_book, market_cap
  Profitability: gross_margin_pct, operating_margin_pct, net_margin_pct, roe, roa
  Growth:       revenue_growth_yoy (trailing), earnings_growth_yoy
  Income:       revenue, net_income, ebitda
  Cash flow:    fcf, fcf_yield
  Leverage:     debt_to_equity, current_ratio
  Dividends:    dividend_yield
  R&D:          rd_spend_pct (R&D as % of revenue)

These metrics feed the thesis matcher (config/theses.yaml financial_criteria)
and chat tool responses. Without them, theses like "Deep Value" can't screen
for P/E, price-to-book, FCF yield, etc.

Usage:
    from ingestion.fundamentals import fetch_and_store_fundamentals
    await fetch_and_store_fundamentals(session, ticker)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from decimal import Decimal

import yfinance as yf
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import FinancialMetric, Ticker

logger = logging.getLogger(__name__)


# Metrics we extract from yfinance ticker.info
# Maps our metric_name → (yfinance info key, unit, optional transform)
_INFO_METRICS: dict[str, tuple[str, str]] = {
    "pe_ratio": ("trailingPE", "ratio"),
    "forward_pe_ratio": ("forwardPE", "ratio"),
    "price_to_book": ("priceToBook", "ratio"),
    "market_cap": ("marketCap", "USD"),
    "enterprise_value": ("enterpriseValue", "USD"),
    "gross_margin_pct": ("grossMargins", "%"),  # yfinance returns as decimal (0.45 = 45%)
    "operating_margin_pct": ("operatingMargins", "%"),
    "net_margin_pct": ("profitMargins", "%"),
    "roe": ("returnOnEquity", "%"),
    "roa": ("returnOnAssets", "%"),
    "revenue": ("totalRevenue", "USD"),
    "net_income": ("netIncomeToCommon", "USD"),
    "ebitda": ("ebitda", "USD"),
    "revenue_growth_yoy": ("revenueGrowth", "%"),
    "earnings_growth_yoy": ("earningsGrowth", "%"),
    "debt_to_equity": ("debtToEquity", "ratio"),
    "current_ratio": ("currentRatio", "ratio"),
    "dividend_yield": ("dividendYield", "%"),
    "fcf": ("freeCashflow", "USD"),
    "book_value_per_share": ("bookValue", "USD"),
    "earnings_per_share": ("trailingEps", "USD"),
    "beta": ("beta", "ratio"),
}

# Percentage fields that yfinance returns as decimals (0.45 = 45%)
_PCT_AS_DECIMAL = {
    "gross_margin_pct",
    "operating_margin_pct",
    "net_margin_pct",
    "roe",
    "roa",
    "revenue_growth_yoy",
    "earnings_growth_yoy",
    "dividend_yield",
}


def _fetch_fundamentals_sync(symbol: str) -> dict[str, tuple[float, str]]:
    """
    Synchronous yfinance fetch for fundamental data.
    Returns dict mapping metric_name → (value, unit).
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
    except Exception as exc:
        logger.warning("yfinance info fetch failed for %s: %s", symbol, exc)
        return {}

    if not info or info.get("quoteType") == "NONE":
        return {}

    metrics: dict[str, tuple[float, str]] = {}

    for metric_name, (info_key, unit) in _INFO_METRICS.items():
        raw = info.get(info_key)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue

        # Convert decimal ratios to percentages for human readability
        if metric_name in _PCT_AS_DECIMAL:
            val = val * 100.0

        # yfinance returns debtToEquity already as a percentage (e.g., 150 = 150%)
        # but we want it as a ratio for thesis matching (1.5)
        if metric_name == "debt_to_equity":
            val = val / 100.0

        metrics[metric_name] = (val, unit)

    # Compute FCF yield if we have both FCF and market cap
    if "fcf" in metrics and "market_cap" in metrics:
        fcf_val = metrics["fcf"][0]
        mcap_val = metrics["market_cap"][0]
        if mcap_val > 0:
            fcf_yield = (fcf_val / mcap_val) * 100.0
            metrics["fcf_yield"] = (fcf_yield, "%")

    # Compute R&D as % of revenue from financials if available
    try:
        financials = ticker.financials
        if financials is not None and not financials.empty:
            # financials columns are dates, rows are line items
            latest_col = financials.columns[0]
            rd_row = None
            for label in ["Research Development", "Research And Development"]:
                if label in financials.index:
                    rd_row = financials.loc[label, latest_col]
                    break
            revenue_row = None
            for label in ["Total Revenue", "Revenue"]:
                if label in financials.index:
                    revenue_row = financials.loc[label, latest_col]
                    break

            if rd_row is not None and revenue_row is not None:
                rd_val = float(rd_row)
                rev_val = float(revenue_row)
                if rev_val > 0 and rd_val > 0:
                    metrics["rd_spend_pct"] = ((rd_val / rev_val) * 100.0, "%")
    except Exception:
        pass  # R&D extraction is best-effort

    return metrics


async def fetch_fundamentals(symbol: str) -> dict[str, tuple[float, str]]:
    """Async wrapper for yfinance fundamentals fetch."""
    try:
        return await asyncio.to_thread(_fetch_fundamentals_sync, symbol)
    except Exception as exc:
        logger.warning("Fundamentals fetch failed for %s: %s", symbol, exc)
        return {}


async def upsert_financial_metrics(
    session: AsyncSession,
    ticker_id: int,
    metrics: dict[str, tuple[float, str]],
    period: str = "TTM",
    source: str = "yfinance",
) -> int:
    """
    Upsert financial metrics for a ticker.

    Uses period="TTM" (trailing twelve months) for yfinance data since
    ticker.info returns trailing metrics, not quarterly snapshots.
    """
    if not metrics:
        return 0

    rows = []
    for metric_name, (value, unit) in metrics.items():
        rows.append({
            "ticker_id": ticker_id,
            "period": period,
            "period_end_date": date.today(),
            "metric_name": metric_name,
            "value": Decimal(str(round(value, 4))),
            "unit": unit,
            "source": source,
        })

    conn = await session.connection()
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:
        from sqlalchemy.dialects.sqlite import insert as _insert

    stmt = _insert(FinancialMetric).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker_id", "period", "metric_name"],
        set_={
            "value": stmt.excluded.value,
            "unit": stmt.excluded.unit,
            "period_end_date": stmt.excluded.period_end_date,
            "source": stmt.excluded.source,
        },
    )
    await session.execute(stmt)
    return len(rows)


async def fetch_and_store_fundamentals(
    session: AsyncSession,
    ticker: Ticker,
) -> int:
    """
    Fetch fundamental metrics for a ticker and store in the database.
    Returns number of metrics upserted.
    """
    logger.info("Fetching fundamentals for %s", ticker.symbol)

    metrics = await fetch_fundamentals(ticker.symbol)
    if not metrics:
        logger.warning("No fundamental data available for %s", ticker.symbol)
        return 0

    count = await upsert_financial_metrics(session, ticker.id, metrics)
    logger.info("Stored %d fundamental metrics for %s", count, ticker.symbol)
    return count


async def fetch_and_store_fundamentals_batch(
    session: AsyncSession,
    tickers: list[Ticker],
    concurrency: int = 5,
) -> dict[str, int]:
    """
    Fetch fundamentals for multiple tickers with controlled concurrency.

    Two-phase: concurrent network fetches, then sequential DB writes.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _fetch(ticker: Ticker) -> tuple[str, dict[str, tuple[float, str]]]:
        async with semaphore:
            try:
                metrics = await fetch_fundamentals(ticker.symbol)
                return ticker.symbol, metrics
            except Exception as exc:
                logger.error("Error fetching fundamentals for %s: %s", ticker.symbol, exc)
                return ticker.symbol, {}

    fetched = await asyncio.gather(*[_fetch(t) for t in tickers])

    ticker_map = {t.symbol: t for t in tickers}
    results: dict[str, int] = {}

    for symbol, metrics in fetched:
        ticker = ticker_map[symbol]
        try:
            if not metrics:
                results[symbol] = 0
                continue
            count = await upsert_financial_metrics(session, ticker.id, metrics)
            results[symbol] = count
        except Exception as exc:
            logger.error("Error storing fundamentals for %s: %s", symbol, exc)
            results[symbol] = 0

    return results
