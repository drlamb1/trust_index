"""
EdgeFinder — pytest Configuration and Shared Fixtures

Key design decisions:
  - Tests use SQLite in-memory (not Neon) for speed and isolation
  - Each test function gets a fresh DB (function-scoped fixture)
  - Claude API calls are mocked by default — no tokens burned during tests
  - yfinance calls are mocked to avoid rate limits and network dependencies
  - Each test is fully isolated — no shared state between tests

Run tests:
    pytest tests/unit/                    # Fast unit tests only
    pytest tests/integration/            # Integration tests (requires local SQLite)
    pytest tests/ -m "not slow"          # Skip slow tests
    pytest tests/ -v                     # Verbose output
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.models import Base, PriceBar, Ticker

# ---------------------------------------------------------------------------
# Test database (SQLite in-memory)
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default event loop policy for tests."""
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create a fresh in-memory SQLite engine for each test."""
    engine = create_async_engine(TEST_DB_URL, echo=False)

    # SQLite disables FK enforcement by default; enable it so ondelete="CASCADE" works
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a fresh AsyncSession for each test.

    Uses SQLite in-memory — no Neon connection required.
    Session is automatically rolled back after each test for isolation.
    """
    session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sample_ticker(db_session: AsyncSession) -> Ticker:
    """Create and persist a sample ticker for use in tests."""
    ticker = Ticker(
        symbol="NVDA",
        name="NVIDIA Corporation",
        sector="Information Technology",
        industry="Semiconductors",
        market_cap=3_000_000_000_000,
        in_sp500=True,
        in_watchlist=True,
        watchlist_priority=1,
        is_active=True,
        first_seen=date.today(),
    )
    db_session.add(ticker)
    await db_session.commit()
    await db_session.refresh(ticker)
    return ticker


@pytest_asyncio.fixture
async def sample_tickers(db_session: AsyncSession) -> list[Ticker]:
    """Create a batch of tickers for bulk operation tests."""
    tickers = [
        Ticker(
            symbol="AAPL",
            name="Apple Inc.",
            sector="Information Technology",
            in_sp500=True,
            is_active=True,
            first_seen=date.today(),
        ),
        Ticker(
            symbol="MSFT",
            name="Microsoft Corp.",
            sector="Information Technology",
            in_sp500=True,
            is_active=True,
            first_seen=date.today(),
        ),
        Ticker(
            symbol="SPY",
            name="SPDR S&P 500 ETF",
            sector="ETF",
            in_sp500=False,
            is_active=True,
            first_seen=date.today(),
        ),
    ]
    for t in tickers:
        db_session.add(t)
    await db_session.commit()
    for t in tickers:
        await db_session.refresh(t)
    return tickers


def _make_ohlcv_df(
    days: int = 60,
    start_price: float = 100.0,
    trend: float = 0.001,
    volatility: float = 0.015,
) -> pd.DataFrame:
    """
    Generate a synthetic OHLCV DataFrame for testing.

    Args:
        days: Number of trading days
        start_price: Starting close price
        trend: Daily drift (positive = uptrend)
        volatility: Daily volatility (std dev as fraction of price)

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    import numpy as np

    rng = np.random.default_rng(seed=42)
    dates = []
    d = date.today() - timedelta(days=days)
    while len(dates) < days:
        if d.weekday() < 5:  # Skip weekends
            dates.append(d)
        d += timedelta(days=1)

    prices = [start_price]
    for _ in range(len(dates) - 1):
        change = trend + volatility * rng.standard_normal()
        prices.append(prices[-1] * (1 + change))

    closes = prices
    opens = [p * (1 + volatility * 0.3 * rng.standard_normal()) for p in closes]
    highs = [
        max(o, c) * (1 + abs(volatility * rng.standard_normal())) for o, c in zip(opens, closes)
    ]
    lows = [
        min(o, c) * (1 - abs(volatility * rng.standard_normal())) for o, c in zip(opens, closes)
    ]
    volumes = [max(1, int(1_000_000 + 500_000 * rng.standard_normal())) for _ in closes]

    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


@pytest.fixture
def sample_ohlcv_df() -> pd.DataFrame:
    """Synthetic 60-day OHLCV DataFrame for indicator testing."""
    return _make_ohlcv_df(days=60)


@pytest.fixture
def sample_ohlcv_df_200() -> pd.DataFrame:
    """Synthetic 220-day OHLCV DataFrame (enough for SMA200)."""
    return _make_ohlcv_df(days=220)


@pytest_asyncio.fixture
async def sample_price_bars(db_session: AsyncSession, sample_ticker: Ticker) -> list[PriceBar]:
    """Create 60 days of price bars in the test DB."""
    df = _make_ohlcv_df(days=60)
    bars = []
    for _, row in df.iterrows():
        bar = PriceBar(
            ticker_id=sample_ticker.id,
            date=row["date"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=int(row["volume"]),
            source="test",
        )
        db_session.add(bar)
        bars.append(bar)
    await db_session.commit()
    return bars


# ---------------------------------------------------------------------------
# API mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_yfinance(monkeypatch):
    """
    Mock yfinance so tests don't make real network calls.
    Returns a synthetic 60-day OHLCV history.
    """
    df = _make_ohlcv_df(days=60)

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df.rename(
        columns={
            "date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    ).set_index("Date")

    with patch("yfinance.Ticker", return_value=mock_ticker):
        yield mock_ticker


@pytest.fixture
def mock_alpha_vantage_success(httpx_mock):
    """Mock Alpha Vantage API response with sample data."""
    df = _make_ohlcv_df(days=10)
    time_series = {}
    for _, row in df.iterrows():
        date_str = row["date"].isoformat()
        time_series[date_str] = {
            "1. open": str(row["open"]),
            "2. high": str(row["high"]),
            "3. low": str(row["low"]),
            "4. close": str(row["close"]),
            "5. adjusted close": str(row["close"]),
            "6. volume": str(int(row["volume"])),
        }

    import re

    httpx_mock.add_response(
        url=re.compile(r"https://www.alphavantage.co/.*"),
        json={"Time Series (Daily)": time_series},
    )


@pytest.fixture
def mock_anthropic():
    """
    Mock Anthropic API client — no real API calls during tests.
    Returns a predefined sentiment/analysis response.
    """
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"score": 0.7}')]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        yield mock_client


# ---------------------------------------------------------------------------
# Settings override for tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def override_settings(monkeypatch):
    """
    Override settings for test environment.
    Ensures tests never accidentally hit production systems.
    """
    monkeypatch.setattr(
        "config.settings.settings",
        type(
            "TestSettings",
            (),
            {
                "database_url": TEST_DB_URL.replace("sqlite+aiosqlite", "sqlite"),
                "redis_url": "redis://localhost:6379",
                "redis_uses_ssl": False,
                "anthropic_api_key": "test-key",
                "alpha_vantage_api_key": "test-key",
                "polygon_api_key": "",
                "finnhub_api_key": "",
                "edgar_user_agent": "EdgeFinder/test test@example.com",
                "environment": "development",
                "log_level": "ERROR",  # Quiet in tests
                "edgar_rate_limit": 10.0,
                "has_anthropic": True,
                "has_finnhub": False,
                "use_local_sentiment_model": False,
                "signal_ranker_enabled": False,
                "signal_ranker_min_probability": 0.4,
                "ml_model_refresh_interval_minutes": 60,
                "is_production": False,
            },
        )(),
    )
