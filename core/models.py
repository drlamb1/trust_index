"""
EdgeFinder — SQLAlchemy ORM Models

All 15 database models defined here. Uses SQLAlchemy 2.0 "mapped column" style
with full type annotations.

PostgreSQL-specific types:
  - JSONB for flexible structured data (red_flags, metrics, context)
  - ARRAY(Integer) for ticker_ids on NewsArticle

SQLite compatibility (for tests):
  JSON fields use JSON (not JSONB) on SQLite.
  ARRAY fields use JSON on SQLite (serialized as [1, 2, 3]).
  This is handled via SQLAlchemy's .with_variant() mechanism.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Dialect-adaptive types
# ---------------------------------------------------------------------------

# JSONB on PostgreSQL, JSON on SQLite (for tests)
JsonType = JSONB().with_variant(sa.JSON(), "sqlite")

# ARRAY(Integer) on PostgreSQL, JSON on SQLite (store as [1, 2, 3])
IntArrayType = ARRAY(Integer).with_variant(sa.JSON(), "sqlite")


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    # Shared audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FilingType(str, enum.Enum):
    TEN_K = "10-K"
    TEN_Q = "10-Q"
    EIGHT_K = "8-K"
    DEF_14A = "DEF 14A"
    FORM_4 = "4"
    FORM_13F = "13F-HR"


class AlertSeverity(str, enum.Enum):
    GREEN = "green"  # 70-80: worth watching
    YELLOW = "yellow"  # 80-90: strong signal
    RED = "red"  # 90-100: exceptional opportunity


class AlertType(str, enum.Enum):
    BUY_THE_DIP = "BUY_THE_DIP"
    PRICE_ANOMALY = "PRICE_ANOMALY"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    FILING_RED_FLAG = "FILING_RED_FLAG"
    INSIDER_BUY_CLUSTER = "INSIDER_BUY_CLUSTER"
    SENTIMENT_DIVERGENCE = "SENTIMENT_DIVERGENCE"
    EARNINGS_SURPRISE = "EARNINGS_SURPRISE"
    TECHNICAL_SIGNAL = "TECHNICAL_SIGNAL"
    THESIS_MATCH = "THESIS_MATCH"


class InsiderTradeType(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    GRANT = "grant"
    EXERCISE = "exercise"


class NewsTier(int, enum.Enum):
    SEC = 1  # SEC filings / press releases — highest signal
    TIER1 = 2  # Reuters, WSJ, FT, Bloomberg
    TIER2 = 3  # Seeking Alpha, Yahoo Finance, CNBC
    SOCIAL = 4  # Reddit, StockTwits, Twitter


# ---------------------------------------------------------------------------
# 1. Ticker — master universe table
# ---------------------------------------------------------------------------


class Ticker(Base):
    __tablename__ = "tickers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    market_cap: Mapped[float | None] = mapped_column(Float)
    cik: Mapped[str | None] = mapped_column(String(20), index=True)  # SEC CIK number

    # Universe membership
    in_sp500: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    in_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    in_watchlist: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    watchlist_priority: Mapped[int | None] = mapped_column(Integer)
    watchlist_notes: Mapped[str | None] = mapped_column(Text)

    # Thesis associations (list of thesis slugs, stored as JSON array)
    thesis_tags: Mapped[list | None] = mapped_column(JsonType)

    # Metadata
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sp500_added_date: Mapped[date | None] = mapped_column(Date)
    sp500_removed_date: Mapped[date | None] = mapped_column(Date)
    first_seen: Mapped[date | None] = mapped_column(Date)
    last_price_fetch: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships — passive_deletes=True lets the DB handle ondelete="CASCADE"
    # instead of SQLAlchemy trying to null-out the FK before deletion.
    price_bars: Mapped[list[PriceBar]] = relationship(back_populates="ticker", passive_deletes=True)
    technical_snapshots: Mapped[list[TechnicalSnapshot]] = relationship(
        back_populates="ticker", passive_deletes=True
    )
    filings: Mapped[list[Filing]] = relationship(back_populates="ticker", passive_deletes=True)
    financial_metrics: Mapped[list[FinancialMetric]] = relationship(
        back_populates="ticker", passive_deletes=True
    )
    alerts: Mapped[list[Alert]] = relationship(back_populates="ticker", passive_deletes=True)
    thesis_matches: Mapped[list[ThesisMatch]] = relationship(
        back_populates="ticker", passive_deletes=True
    )
    insider_trades: Mapped[list[InsiderTrade]] = relationship(
        back_populates="ticker", passive_deletes=True
    )
    institutional_holdings: Mapped[list[InstitutionalHolding]] = relationship(
        back_populates="ticker", passive_deletes=True
    )


# ---------------------------------------------------------------------------
# 2. PriceBar — OHLCV daily data
# ---------------------------------------------------------------------------


class PriceBar(Base):
    __tablename__ = "price_bars"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)

    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)

    # Source tracking
    source: Mapped[str] = mapped_column(String(50), default="yfinance")

    ticker: Mapped[Ticker] = relationship(back_populates="price_bars")

    __table_args__ = (
        UniqueConstraint("ticker_id", "date", name="uq_price_bars_ticker_date"),
        Index("ix_price_bars_ticker_date", "ticker_id", "date"),
    )


# ---------------------------------------------------------------------------
# 3. TechnicalSnapshot — computed indicators per ticker per day
# ---------------------------------------------------------------------------


class TechnicalSnapshot(Base):
    __tablename__ = "technical_snapshots"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)

    # Trend
    sma_20: Mapped[float | None] = mapped_column(Float)
    sma_50: Mapped[float | None] = mapped_column(Float)
    sma_100: Mapped[float | None] = mapped_column(Float)
    sma_200: Mapped[float | None] = mapped_column(Float)
    ema_20: Mapped[float | None] = mapped_column(Float)
    ema_50: Mapped[float | None] = mapped_column(Float)

    # Momentum
    rsi_14: Mapped[float | None] = mapped_column(Float)
    macd: Mapped[float | None] = mapped_column(Float)
    macd_signal: Mapped[float | None] = mapped_column(Float)
    macd_histogram: Mapped[float | None] = mapped_column(Float)

    # Volatility
    bb_upper: Mapped[float | None] = mapped_column(Float)  # Bollinger Band upper
    bb_middle: Mapped[float | None] = mapped_column(Float)  # = SMA 20
    bb_lower: Mapped[float | None] = mapped_column(Float)  # Bollinger Band lower
    bb_bandwidth: Mapped[float | None] = mapped_column(Float)
    atr_14: Mapped[float | None] = mapped_column(Float)  # Average True Range

    # Volume
    volume_ratio_20d: Mapped[float | None] = mapped_column(Float)  # volume / 20d avg volume

    # Relative strength vs SPY
    rs_vs_spy_20d: Mapped[float | None] = mapped_column(Float)  # % return relative to SPY

    ticker: Mapped[Ticker] = relationship(back_populates="technical_snapshots")

    __table_args__ = (
        UniqueConstraint("ticker_id", "date", name="uq_tech_ticker_date"),
        Index("ix_tech_ticker_date", "ticker_id", "date"),
    )


# ---------------------------------------------------------------------------
# 4. Filing — SEC filing metadata
# ---------------------------------------------------------------------------


class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )

    filing_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_of_report: Mapped[date | None] = mapped_column(Date)
    filed_date: Mapped[date | None] = mapped_column(Date, index=True)
    accession_number: Mapped[str | None] = mapped_column(String(50), unique=True)
    primary_document_url: Mapped[str | None] = mapped_column(Text)

    # Deduplication: skip re-download if hash matches
    raw_text_hash: Mapped[str | None] = mapped_column(String(64))  # SHA-256 hex

    # Processing status
    is_parsed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    parse_error: Mapped[str | None] = mapped_column(Text)

    ticker: Mapped[Ticker] = relationship(back_populates="filings")
    sections: Mapped[list[FilingSection]] = relationship(back_populates="filing")
    analysis: Mapped[FilingAnalysis | None] = relationship(back_populates="filing", uselist=False)

    __table_args__ = (
        Index("ix_filings_ticker_type_date", "ticker_id", "filing_type", "filed_date"),
    )


# ---------------------------------------------------------------------------
# 5. FilingSection — extracted sections from filings
# ---------------------------------------------------------------------------


class FilingSection(Base):
    __tablename__ = "filing_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filing_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("filings.id", ondelete="CASCADE"), nullable=False
    )
    section_name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int | None] = mapped_column(Integer)

    filing: Mapped[Filing] = relationship(back_populates="sections")

    __table_args__ = (Index("ix_sections_filing_name", "filing_id", "section_name"),)


# ---------------------------------------------------------------------------
# 6. FilingAnalysis — Claude Sonnet analysis output
# ---------------------------------------------------------------------------


class FilingAnalysis(Base):
    __tablename__ = "filing_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filing_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("filings.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    health_score: Mapped[float | None] = mapped_column(Float)  # 0-100
    red_flags: Mapped[list | None] = mapped_column(JsonType)  # list of {flag, severity, quote}
    financial_metrics: Mapped[dict | None] = mapped_column(JsonType)  # extracted KPIs
    summary: Mapped[str | None] = mapped_column(Text)  # 500-word analyst summary
    bull_points: Mapped[list | None] = mapped_column(JsonType)  # list of strings
    bear_points: Mapped[list | None] = mapped_column(JsonType)  # list of strings
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_used: Mapped[str | None] = mapped_column(String(50))

    filing: Mapped[Filing] = relationship(back_populates="analysis")


# ---------------------------------------------------------------------------
# 7. FinancialMetric — time-series of extracted financial metrics
# ---------------------------------------------------------------------------


class FinancialMetric(Base):
    __tablename__ = "financial_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g., "2024-Q3", "2024-FY"
    period_end_date: Mapped[date | None] = mapped_column(Date)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    unit: Mapped[str | None] = mapped_column(String(20))  # "USD", "%", "ratio"
    source: Mapped[str | None] = mapped_column(String(50))  # "10-K", "10-Q", "xbrl"

    ticker: Mapped[Ticker] = relationship(back_populates="financial_metrics")

    __table_args__ = (
        UniqueConstraint(
            "ticker_id", "period", "metric_name", name="uq_financial_metrics_ticker_period_name"
        ),
        Index("ix_financial_metrics_ticker_period", "ticker_id", "period"),
    )


# ---------------------------------------------------------------------------
# 8. NewsArticle — aggregated news with sentiment scoring
# ---------------------------------------------------------------------------


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ticker_ids: list of Ticker.id values this article mentions
    # Uses ARRAY on PostgreSQL, JSON on SQLite
    ticker_ids: Mapped[list | None] = mapped_column(IntArrayType)

    source_tier: Mapped[int] = mapped_column(Integer, default=3)  # 1=SEC, 2=T1, 3=T2, 4=Social
    source_name: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now()
    )

    # Content
    summary: Mapped[str | None] = mapped_column(Text)
    full_text: Mapped[str | None] = mapped_column(Text)
    raw_content_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    # Sentiment scoring
    sentiment_score: Mapped[float | None] = mapped_column(Float)  # -1.0 to +1.0
    sentiment_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sentiment_model: Mapped[str | None] = mapped_column(String(50))

    __table_args__ = (Index("ix_news_published_tier", "published_at", "source_tier"),)


# ---------------------------------------------------------------------------
# 9. InsiderTrade — SEC Form 4 derived data
# ---------------------------------------------------------------------------


class InsiderTrade(Base):
    __tablename__ = "insider_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    accession_number: Mapped[str | None] = mapped_column(String(50), unique=True)

    insider_name: Mapped[str] = mapped_column(String(255), nullable=False)
    insider_title: Mapped[str | None] = mapped_column(String(100))
    trade_type: Mapped[str] = mapped_column(String(20), nullable=False)  # buy/sell/grant/exercise
    shares: Mapped[float | None] = mapped_column(Float)
    price_per_share: Mapped[float | None] = mapped_column(Float)
    total_amount: Mapped[float | None] = mapped_column(Float)  # shares * price
    shares_owned_after: Mapped[float | None] = mapped_column(Float)
    filed_date: Mapped[date | None] = mapped_column(Date, index=True)
    transaction_date: Mapped[date | None] = mapped_column(Date)

    ticker: Mapped[Ticker] = relationship(back_populates="insider_trades")

    __table_args__ = (Index("ix_insider_trades_ticker_date", "ticker_id", "filed_date"),)


# ---------------------------------------------------------------------------
# 10. InstitutionalHolding — 13F-HR derived data
# ---------------------------------------------------------------------------


class InstitutionalHolding(Base):
    __tablename__ = "institutional_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    institution_name: Mapped[str] = mapped_column(String(255), nullable=False)
    institution_cik: Mapped[str | None] = mapped_column(String(20))
    shares: Mapped[float | None] = mapped_column(Float)
    market_value: Mapped[float | None] = mapped_column(Float)
    period_date: Mapped[date] = mapped_column(Date, nullable=False)
    change_shares: Mapped[float | None] = mapped_column(Float)  # vs prior quarter
    change_pct: Mapped[float | None] = mapped_column(Float)  # %

    ticker: Mapped[Ticker] = relationship(back_populates="institutional_holdings")

    __table_args__ = (
        UniqueConstraint(
            "ticker_id",
            "institution_cik",
            "period_date",
            name="uq_institutional_ticker_inst_period",
        ),
        Index("ix_institutional_ticker_period", "ticker_id", "period_date"),
    )


# ---------------------------------------------------------------------------
# 11. Alert — generated alerts from the rule engine
# ---------------------------------------------------------------------------


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )

    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # green/yellow/red
    score: Mapped[float | None] = mapped_column(Float)  # 0-100

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    context_json: Mapped[dict | None] = mapped_column(JsonType)  # supporting data

    # State management
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ticker: Mapped[Ticker] = relationship(back_populates="alerts")
    dip_score: Mapped[DipScore | None] = relationship(back_populates="alert", uselist=False)

    __table_args__ = (
        Index("ix_alerts_ticker_severity_created", "ticker_id", "severity", "created_at"),
    )


# ---------------------------------------------------------------------------
# 12. DipScore — 8-dimension Buy-the-Dip composite score
# ---------------------------------------------------------------------------


class DipScore(Base):
    __tablename__ = "dip_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    price_drop_magnitude: Mapped[float | None] = mapped_column(Float)  # 0-100
    drop_vs_historical_vol: Mapped[float | None] = mapped_column(Float)  # 0-100
    fundamental_score: Mapped[float | None] = mapped_column(Float)  # 0-100 (filing health)
    sentiment_context: Mapped[float | None] = mapped_column(Float)  # 0-100
    insider_activity: Mapped[float | None] = mapped_column(Float)  # 0-100
    institutional_support: Mapped[float | None] = mapped_column(Float)  # 0-100
    technical_setup: Mapped[float | None] = mapped_column(Float)  # 0-100 (RSI, support)
    sector_relative: Mapped[float | None] = mapped_column(Float)  # 0-100

    composite_score: Mapped[float | None] = mapped_column(Float)  # 0-100, weighted

    alert: Mapped[Alert] = relationship(back_populates="dip_score")


# ---------------------------------------------------------------------------
# 13. Thesis — investment thesis definitions (synced from theses.yaml)
# ---------------------------------------------------------------------------


class Thesis(Base):
    __tablename__ = "theses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    criteria_yaml: Mapped[str | None] = mapped_column(Text)  # raw YAML string
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    matches: Mapped[list[ThesisMatch]] = relationship(back_populates="thesis")


# ---------------------------------------------------------------------------
# 14. ThesisMatch — auto-discovered ticker ↔ thesis alignment scores
# ---------------------------------------------------------------------------


class ThesisMatch(Base):
    __tablename__ = "thesis_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("theses.id", ondelete="CASCADE"), nullable=False
    )
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )

    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100
    match_reasons: Mapped[dict | None] = mapped_column(JsonType)  # why it matched
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now()
    )

    thesis: Mapped[Thesis] = relationship(back_populates="matches")
    ticker: Mapped[Ticker] = relationship(back_populates="thesis_matches")

    __table_args__ = (
        UniqueConstraint("thesis_id", "ticker_id", name="uq_thesis_matches_thesis_ticker"),
        Index("ix_thesis_matches_thesis_score", "thesis_id", "score"),
    )


# ---------------------------------------------------------------------------
# 15. DailyBriefing — generated daily digest
# ---------------------------------------------------------------------------


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    content_md: Mapped[str | None] = mapped_column(Text)  # Markdown version
    content_html: Mapped[str | None] = mapped_column(Text)  # HTML version
    market_snapshot: Mapped[dict | None] = mapped_column(JsonType)  # SPY, VIX, etc.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_channels: Mapped[list | None] = mapped_column(JsonType)  # ["email", "slack"]
