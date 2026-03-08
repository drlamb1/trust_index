"""
Integration tests for ingestion/fundamentals.py

Tests fundamental metric fetching and storage using:
  - Mocked yfinance (no real network calls)
  - In-memory SQLite database (no Neon connection)
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import FinancialMetric, Ticker
from ingestion.fundamentals import (
    _fetch_fundamentals_sync,
    fetch_and_store_fundamentals,
    upsert_financial_metrics,
)


def _mock_yfinance_info():
    """Return a realistic yfinance ticker.info dict."""
    return {
        "quoteType": "EQUITY",
        "trailingPE": 28.5,
        "forwardPE": 25.2,
        "priceToBook": 3.1,
        "marketCap": 150_000_000_000,
        "enterpriseValue": 160_000_000_000,
        "grossMargins": 0.452,  # 45.2%
        "operatingMargins": 0.281,  # 28.1%
        "profitMargins": 0.215,  # 21.5%
        "returnOnEquity": 0.35,  # 35%
        "returnOnAssets": 0.12,  # 12%
        "totalRevenue": 50_000_000_000,
        "netIncomeToCommon": 10_750_000_000,
        "ebitda": 15_000_000_000,
        "revenueGrowth": 0.125,  # 12.5%
        "earningsGrowth": 0.08,  # 8%
        "debtToEquity": 45.0,  # yfinance returns as percentage (45 = 0.45 ratio)
        "currentRatio": 2.1,
        "dividendYield": 0.015,  # 1.5%
        "freeCashflow": 12_000_000_000,
        "bookValue": 42.5,
        "trailingEps": 8.75,
        "beta": 1.15,
    }


@pytest.mark.integration
class TestFetchFundamentalsSync:
    def test_extracts_metrics(self):
        mock_ticker = MagicMock()
        mock_ticker.info = _mock_yfinance_info()
        mock_ticker.financials = MagicMock()
        mock_ticker.financials.empty = True

        with patch("ingestion.fundamentals.yf.Ticker", return_value=mock_ticker):
            metrics = _fetch_fundamentals_sync("AAPL")

        assert "pe_ratio" in metrics
        assert metrics["pe_ratio"][0] == pytest.approx(28.5)

        assert "gross_margin_pct" in metrics
        assert metrics["gross_margin_pct"][0] == pytest.approx(45.2)

        assert "debt_to_equity" in metrics
        assert metrics["debt_to_equity"][0] == pytest.approx(0.45)  # converted from 45%

        assert "revenue_growth_yoy" in metrics
        assert metrics["revenue_growth_yoy"][0] == pytest.approx(12.5)

        assert "dividend_yield" in metrics
        assert metrics["dividend_yield"][0] == pytest.approx(1.5)

    def test_computes_fcf_yield(self):
        mock_ticker = MagicMock()
        mock_ticker.info = _mock_yfinance_info()
        mock_ticker.financials = MagicMock()
        mock_ticker.financials.empty = True

        with patch("ingestion.fundamentals.yf.Ticker", return_value=mock_ticker):
            metrics = _fetch_fundamentals_sync("AAPL")

        assert "fcf_yield" in metrics
        expected = (12_000_000_000 / 150_000_000_000) * 100
        assert metrics["fcf_yield"][0] == pytest.approx(expected)

    def test_handles_missing_fields(self):
        mock_ticker = MagicMock()
        mock_ticker.info = {"quoteType": "EQUITY", "trailingPE": 15.0}
        mock_ticker.financials = MagicMock()
        mock_ticker.financials.empty = True

        with patch("ingestion.fundamentals.yf.Ticker", return_value=mock_ticker):
            metrics = _fetch_fundamentals_sync("XYZ")

        assert "pe_ratio" in metrics
        assert "gross_margin_pct" not in metrics
        assert "fcf_yield" not in metrics

    def test_handles_none_info(self):
        mock_ticker = MagicMock()
        mock_ticker.info = None

        with patch("ingestion.fundamentals.yf.Ticker", return_value=mock_ticker):
            metrics = _fetch_fundamentals_sync("BAD")

        assert metrics == {}


@pytest.mark.integration
class TestUpsertFinancialMetrics:
    async def test_upsert_new_metrics(
        self, db_session: AsyncSession, sample_ticker: Ticker
    ):
        metrics = {
            "pe_ratio": (28.5, "ratio"),
            "gross_margin_pct": (45.2, "%"),
            "revenue": (50_000_000_000.0, "USD"),
        }
        count = await upsert_financial_metrics(db_session, sample_ticker.id, metrics)
        assert count == 3

        result = await db_session.execute(
            select(func.count(FinancialMetric.id)).where(
                FinancialMetric.ticker_id == sample_ticker.id
            )
        )
        assert result.scalar_one() == 3

    async def test_upsert_updates_existing(
        self, db_session: AsyncSession, sample_ticker: Ticker
    ):
        metrics_v1 = {"pe_ratio": (28.5, "ratio")}
        await upsert_financial_metrics(db_session, sample_ticker.id, metrics_v1)

        metrics_v2 = {"pe_ratio": (30.0, "ratio")}
        await upsert_financial_metrics(db_session, sample_ticker.id, metrics_v2)

        result = await db_session.execute(
            select(FinancialMetric).where(
                FinancialMetric.ticker_id == sample_ticker.id,
                FinancialMetric.metric_name == "pe_ratio",
            )
        )
        row = result.scalar_one()
        assert float(row.value) == pytest.approx(30.0)

    async def test_upsert_empty_returns_zero(
        self, db_session: AsyncSession, sample_ticker: Ticker
    ):
        count = await upsert_financial_metrics(db_session, sample_ticker.id, {})
        assert count == 0


@pytest.mark.integration
class TestFetchAndStoreFundamentals:
    async def test_end_to_end(
        self, db_session: AsyncSession, sample_ticker: Ticker
    ):
        mock_ticker = MagicMock()
        mock_ticker.info = _mock_yfinance_info()
        mock_ticker.financials = MagicMock()
        mock_ticker.financials.empty = True

        with patch("ingestion.fundamentals.yf.Ticker", return_value=mock_ticker):
            count = await fetch_and_store_fundamentals(db_session, sample_ticker)

        assert count > 0

        result = await db_session.execute(
            select(FinancialMetric).where(
                FinancialMetric.ticker_id == sample_ticker.id
            )
        )
        rows = result.scalars().all()
        metric_names = {r.metric_name for r in rows}
        assert "pe_ratio" in metric_names
        assert "fcf_yield" in metric_names
        assert "gross_margin_pct" in metric_names
