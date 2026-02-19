"""
Integration tests for ingestion/price_data.py

Tests price fetching and storage using:
  - Mocked yfinance (no real network calls)
  - In-memory SQLite database (no Neon connection)
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import PriceBar, Ticker
from ingestion.price_data import (
    _days_to_yf_period,
    fetch_and_store_prices,
    fetch_and_store_prices_batch,
    fetch_ohlcv,
    upsert_price_bars,
)


@pytest.mark.integration
class TestDaysToYfPeriod:
    def test_7_days(self):
        assert _days_to_yf_period(7) == "7d"

    def test_30_days(self):
        assert _days_to_yf_period(30) == "1mo"

    def test_365_days(self):
        assert _days_to_yf_period(365) == "1y"

    def test_over_3650_days(self):
        assert _days_to_yf_period(5000) == "max"


@pytest.mark.integration
class TestUpsertPriceBars:
    async def test_upsert_new_bars(
        self, db_session: AsyncSession, sample_ticker: Ticker, sample_ohlcv_df
    ):
        """New price bars should be inserted."""
        count = await upsert_price_bars(db_session, sample_ticker.id, sample_ohlcv_df, "yfinance")
        assert count == len(sample_ohlcv_df)

        result = await db_session.execute(
            select(func.count(PriceBar.id)).where(PriceBar.ticker_id == sample_ticker.id)
        )
        stored_count = result.scalar_one()
        assert stored_count == len(sample_ohlcv_df)

    async def test_upsert_empty_df_returns_zero(
        self, db_session: AsyncSession, sample_ticker: Ticker
    ):
        count = await upsert_price_bars(db_session, sample_ticker.id, pd.DataFrame(), "yfinance")
        assert count == 0

    async def test_upsert_updates_existing(
        self, db_session: AsyncSession, sample_ticker: Ticker, sample_ohlcv_df
    ):
        """Upserting the same data twice should not duplicate rows."""
        await upsert_price_bars(db_session, sample_ticker.id, sample_ohlcv_df, "yfinance")

        # Modify close price and upsert again
        modified_df = sample_ohlcv_df.copy()
        modified_df["close"] = modified_df["close"] * 1.1  # 10% higher

        count2 = await upsert_price_bars(db_session, sample_ticker.id, modified_df, "yfinance")
        assert count2 == len(sample_ohlcv_df)  # Same number of rows processed

        # Total row count should still equal original df length
        result = await db_session.execute(
            select(func.count(PriceBar.id)).where(PriceBar.ticker_id == sample_ticker.id)
        )
        stored_count = result.scalar_one()
        assert stored_count == len(sample_ohlcv_df)

    async def test_source_is_recorded(
        self, db_session: AsyncSession, sample_ticker: Ticker, sample_ohlcv_df
    ):
        await upsert_price_bars(db_session, sample_ticker.id, sample_ohlcv_df, "alpha_vantage")

        result = await db_session.execute(
            select(PriceBar).where(PriceBar.ticker_id == sample_ticker.id).limit(1)
        )
        bar = result.scalar_one()
        assert bar.source == "alpha_vantage"


@pytest.mark.integration
class TestFetchOhlcv:
    async def test_yfinance_primary_success(self, sample_ohlcv_df):
        """When yfinance succeeds, returns its data with 'yfinance' source."""
        with patch("ingestion.price_data._fetch_yfinance", return_value=sample_ohlcv_df):
            df, source = await fetch_ohlcv("NVDA", days=60)

        assert not df.empty
        assert source == "yfinance"

    async def test_falls_back_to_alpha_vantage(self, sample_ohlcv_df):
        """When yfinance returns empty, falls back to Alpha Vantage."""
        with patch("ingestion.price_data._fetch_yfinance", return_value=pd.DataFrame()):
            with patch("ingestion.price_data._fetch_alpha_vantage", return_value=sample_ohlcv_df):
                df, source = await fetch_ohlcv("NVDA", days=60)

        assert not df.empty
        assert source == "alpha_vantage"

    async def test_falls_back_to_polygon(self, sample_ohlcv_df):
        """When yfinance and Alpha Vantage fail, falls back to Polygon."""
        with patch("ingestion.price_data._fetch_yfinance", return_value=pd.DataFrame()):
            with patch("ingestion.price_data._fetch_alpha_vantage", return_value=pd.DataFrame()):
                with patch("ingestion.price_data._fetch_polygon", return_value=sample_ohlcv_df):
                    df, source = await fetch_ohlcv("NVDA", days=60)

        assert not df.empty
        assert source == "polygon"

    async def test_all_sources_fail_returns_empty(self):
        """When all sources fail, returns empty DataFrame."""
        with patch("ingestion.price_data._fetch_yfinance", return_value=pd.DataFrame()):
            with patch("ingestion.price_data._fetch_alpha_vantage", return_value=pd.DataFrame()):
                with patch("ingestion.price_data._fetch_polygon", return_value=pd.DataFrame()):
                    df, source = await fetch_ohlcv("FAKE", days=60)

        assert df.empty
        assert source == "none"


@pytest.mark.integration
class TestFetchAndStorePrices:
    async def test_stores_prices_in_db(
        self, db_session: AsyncSession, sample_ticker: Ticker, sample_ohlcv_df
    ):
        with patch("ingestion.price_data._fetch_yfinance", return_value=sample_ohlcv_df):
            count = await fetch_and_store_prices(db_session, sample_ticker, days=60)

        assert count > 0

        result = await db_session.execute(
            select(func.count(PriceBar.id)).where(PriceBar.ticker_id == sample_ticker.id)
        )
        stored_count = result.scalar_one()
        assert stored_count == count

    async def test_updates_last_price_fetch(
        self, db_session: AsyncSession, sample_ticker: Ticker, sample_ohlcv_df
    ):
        """fetch_and_store_prices should update ticker.last_price_fetch."""
        assert sample_ticker.last_price_fetch is None

        with patch("ingestion.price_data._fetch_yfinance", return_value=sample_ohlcv_df):
            await fetch_and_store_prices(db_session, sample_ticker, days=60)

        # Refresh ticker from DB
        await db_session.refresh(sample_ticker)
        assert sample_ticker.last_price_fetch is not None

    async def test_no_data_returns_zero(self, db_session: AsyncSession, sample_ticker: Ticker):
        with patch("ingestion.price_data._fetch_yfinance", return_value=pd.DataFrame()):
            with patch("ingestion.price_data._fetch_alpha_vantage", return_value=pd.DataFrame()):
                with patch("ingestion.price_data._fetch_polygon", return_value=pd.DataFrame()):
                    count = await fetch_and_store_prices(db_session, sample_ticker)

        assert count == 0


@pytest.mark.integration
class TestFetchBatch:
    async def test_batch_processes_all_tickers(
        self, db_session: AsyncSession, sample_tickers: list[Ticker], sample_ohlcv_df
    ):
        with patch("ingestion.price_data._fetch_yfinance", return_value=sample_ohlcv_df):
            results = await fetch_and_store_prices_batch(
                db_session, sample_tickers, days=60, concurrency=3
            )

        assert len(results) == len(sample_tickers)
        for symbol, count in results.items():
            assert count > 0, f"Expected rows for {symbol}"

    async def test_batch_tolerates_individual_failures(
        self, db_session: AsyncSession, sample_tickers: list[Ticker]
    ):
        """If one ticker fails, others should still succeed."""
        call_count = 0

        async def flaky_fetch(symbol, days):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated network error")
            return _make_ohlcv_df(days=10)

        def _make_ohlcv_df(days=10):
            from tests.conftest import _make_ohlcv_df as make_df

            return make_df(days=days)

        with patch("ingestion.price_data._fetch_yfinance", side_effect=flaky_fetch):
            with patch("ingestion.price_data._fetch_alpha_vantage", return_value=pd.DataFrame()):
                with patch("ingestion.price_data._fetch_polygon", return_value=pd.DataFrame()):
                    results = await fetch_and_store_prices_batch(
                        db_session, sample_tickers, days=10, concurrency=1
                    )

        # Should complete without raising, even with a failed ticker
        assert len(results) == len(sample_tickers)
