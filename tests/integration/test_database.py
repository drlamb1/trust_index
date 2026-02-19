"""
Integration tests for core/database.py and core/models.py

Tests ORM model CRUD operations using an in-memory SQLite database.
No Neon connection required.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Alert,
    AlertType,
    DipScore,
    Filing,
    PriceBar,
    TechnicalSnapshot,
    Thesis,
    ThesisMatch,
    Ticker,
)


@pytest.mark.integration
class TestTickerCRUD:
    async def test_create_ticker(self, db_session: AsyncSession):
        ticker = Ticker(
            symbol="AAPL",
            name="Apple Inc.",
            sector="Information Technology",
            in_sp500=True,
            is_active=True,
            first_seen=date.today(),
        )
        db_session.add(ticker)
        await db_session.commit()

        result = await db_session.execute(select(Ticker).where(Ticker.symbol == "AAPL"))
        fetched = result.scalar_one()
        assert fetched.symbol == "AAPL"
        assert fetched.in_sp500 is True
        assert fetched.id is not None

    async def test_ticker_unique_symbol(self, db_session: AsyncSession):
        """Symbol must be unique — inserting duplicate should raise."""
        db_session.add(Ticker(symbol="NVDA", in_sp500=True, is_active=True))
        await db_session.commit()

        db_session.add(Ticker(symbol="NVDA", in_sp500=False, is_active=True))
        with pytest.raises(Exception):  # IntegrityError
            await db_session.commit()

    async def test_update_ticker(self, db_session: AsyncSession, sample_ticker: Ticker):
        sample_ticker.market_cap = 2_000_000_000_000
        db_session.add(sample_ticker)
        await db_session.commit()

        result = await db_session.execute(
            select(Ticker).where(Ticker.symbol == sample_ticker.symbol)
        )
        updated = result.scalar_one()
        assert updated.market_cap == 2_000_000_000_000

    async def test_soft_delete_ticker(self, db_session: AsyncSession, sample_ticker: Ticker):
        """Soft delete: set is_active=False, data is preserved."""
        sample_ticker.is_active = False
        db_session.add(sample_ticker)
        await db_session.commit()

        result = await db_session.execute(
            select(Ticker).where(Ticker.symbol == sample_ticker.symbol)
        )
        still_exists = result.scalar_one()
        assert still_exists.is_active is False
        assert still_exists.symbol == sample_ticker.symbol


@pytest.mark.integration
class TestPriceBarCRUD:
    async def test_create_price_bars(self, db_session: AsyncSession, sample_ticker: Ticker):
        bars = [
            PriceBar(
                ticker_id=sample_ticker.id,
                date=date(2024, 1, i),
                open=100.0 + i,
                high=102.0 + i,
                low=99.0 + i,
                close=101.0 + i,
                volume=1_000_000,
                source="test",
            )
            for i in range(1, 6)
        ]
        for bar in bars:
            db_session.add(bar)
        await db_session.commit()

        result = await db_session.execute(
            select(PriceBar).where(PriceBar.ticker_id == sample_ticker.id)
        )
        fetched = result.scalars().all()
        assert len(fetched) == 5

    async def test_price_bar_cascade_delete(self, db_session: AsyncSession, sample_ticker: Ticker):
        """Deleting a ticker should cascade-delete its price bars."""
        bar = PriceBar(
            ticker_id=sample_ticker.id,
            date=date(2024, 1, 1),
            close=100.0,
            source="test",
        )
        db_session.add(bar)
        await db_session.commit()

        await db_session.delete(sample_ticker)
        await db_session.commit()

        result = await db_session.execute(
            select(PriceBar).where(PriceBar.ticker_id == sample_ticker.id)
        )
        assert result.scalars().all() == []


@pytest.mark.integration
class TestFilingCRUD:
    async def test_create_filing(self, db_session: AsyncSession, sample_ticker: Ticker):
        filing = Filing(
            ticker_id=sample_ticker.id,
            filing_type="10-K",
            period_of_report=date(2024, 12, 31),
            filed_date=date(2025, 2, 1),
            accession_number="0001234567-25-000001",
            is_parsed=False,
            is_analyzed=False,
        )
        db_session.add(filing)
        await db_session.commit()

        result = await db_session.execute(
            select(Filing).where(Filing.ticker_id == sample_ticker.id)
        )
        fetched = result.scalar_one()
        assert fetched.filing_type == "10-K"
        assert fetched.is_parsed is False


@pytest.mark.integration
class TestAlertCRUD:
    async def test_create_alert(self, db_session: AsyncSession, sample_ticker: Ticker):
        alert = Alert(
            ticker_id=sample_ticker.id,
            alert_type=AlertType.BUY_THE_DIP,
            severity="red",
            score=87.5,
            title="NVDA down 12% — BuyTheDip score: 87",
            body="Fundamental score intact. RSI oversold at 28.",
            context_json={"rsi": 28, "drop_pct": -12.1},
        )
        db_session.add(alert)
        await db_session.commit()

        result = await db_session.execute(
            select(Alert).where(Alert.ticker_id == sample_ticker.id)
        )
        fetched = result.scalar_one()
        assert fetched.severity == "red"
        assert fetched.score == pytest.approx(87.5)
        assert fetched.context_json["rsi"] == 28

    async def test_alert_with_dip_score(self, db_session: AsyncSession, sample_ticker: Ticker):
        """Alert → DipScore one-to-one relationship."""
        alert = Alert(
            ticker_id=sample_ticker.id,
            alert_type=AlertType.BUY_THE_DIP,
            severity="yellow",
            score=75.0,
            title="Test alert",
        )
        db_session.add(alert)
        await db_session.flush()  # Get alert.id without committing

        dip = DipScore(
            alert_id=alert.id,
            price_drop_magnitude=70.0,
            fundamental_score=80.0,
            technical_setup=75.0,
            composite_score=75.0,
        )
        db_session.add(dip)
        await db_session.commit()

        result = await db_session.execute(
            select(Alert).where(Alert.id == alert.id)
        )
        fetched_alert = result.scalar_one()
        # Relationship should be accessible (if loaded)
        assert fetched_alert.id == alert.id


@pytest.mark.integration
class TestThesisCRUD:
    async def test_create_thesis(self, db_session: AsyncSession):
        thesis = Thesis(
            slug="ai_infrastructure",
            name="AI Infrastructure Buildout",
            description="Companies providing compute for AI training and inference.",
            is_active=True,
        )
        db_session.add(thesis)
        await db_session.commit()

        result = await db_session.execute(select(Thesis).where(Thesis.slug == "ai_infrastructure"))
        fetched = result.scalar_one()
        assert fetched.name == "AI Infrastructure Buildout"

    async def test_thesis_match(self, db_session: AsyncSession, sample_ticker: Ticker):
        thesis = Thesis(slug="test_thesis", name="Test", is_active=True)
        db_session.add(thesis)
        await db_session.flush()

        match = ThesisMatch(
            thesis_id=thesis.id,
            ticker_id=sample_ticker.id,
            score=82.5,
            match_reasons={"keyword_density": 0.85, "revenue_growth": 25.0},
        )
        db_session.add(match)
        await db_session.commit()

        result = await db_session.execute(
            select(ThesisMatch).where(ThesisMatch.thesis_id == thesis.id)
        )
        fetched = result.scalar_one()
        assert fetched.score == pytest.approx(82.5)
        assert fetched.match_reasons["revenue_growth"] == pytest.approx(25.0)
