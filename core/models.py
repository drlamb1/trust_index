"""
EdgeFinder — SQLAlchemy ORM Models

All 33 database models defined here. Uses SQLAlchemy 2.0 "mapped column" style
with full type annotations.

PostgreSQL-specific types:
  - JSONB for flexible structured data (red_flags, metrics, context)
  - ARRAY(Integer) for ticker_ids on NewsArticle

SQLite compatibility (for tests):
  JSON fields use JSON (not JSONB) on SQLite.
  ARRAY fields use JSON on SQLite (serialized as [1, 2, 3]).
  This is handled via SQLAlchemy's .with_variant() mechanism.

Models 24-33 (Simulation Engine):
  - OptionsChain: market options data (IV, Greeks, bid/ask)
  - VolSurface: fitted implied volatility surfaces (SVI, Heston, etc.)
  - HestonCalibration: calibrated Heston stochastic vol params
  - SimulatedThesis: auto-generated investment theses with lifecycle
  - BacktestRun: walk-forward backtest results with Monte Carlo p-values
  - PaperPortfolio: simulated play-money portfolio
  - PaperPosition: individual paper positions linked to theses
  - SimulationLog: immutable decision log for agent transparency
  - DeepHedgingModel: trained deep hedging policy metadata
  - AgentMemory: long-term agent learning and pattern recognition
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
    LargeBinary,
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
    EARNINGS_TONE_SHIFT = "EARNINGS_TONE_SHIFT"
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


# --- Simulation Engine Enums ---


class ThesisStatus(str, enum.Enum):
    """Lifecycle state of an auto-generated thesis."""

    PROPOSED = "proposed"  # Claude generated it, awaiting backtest
    BACKTESTING = "backtesting"  # Walk-forward sim in progress
    PAPER_LIVE = "paper_live"  # Passed backtest, tracking with play money
    RETIRED = "retired"  # Gracefully deactivated (time horizon expired, etc.)
    KILLED = "killed"  # Failed hard — max drawdown, p-value > 0.10, etc.


class PositionSide(str, enum.Enum):
    LONG = "long"
    SHORT = "short"


class PositionStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    STOPPED_OUT = "stopped_out"


class SimEventType(str, enum.Enum):
    """Immutable event types for the SimulationLog decision journal."""

    GENERATION = "generation"
    BACKTEST_START = "backtest_start"
    BACKTEST_COMPLETE = "backtest_complete"
    ENTRY = "entry"
    EXIT = "exit"
    STOP_TRIGGERED = "stop_triggered"
    MUTATION = "mutation"
    RETIREMENT = "retirement"
    POST_MORTEM = "post_mortem"
    MEMORY_CONSOLIDATED = "memory_consolidated"


class VolModelType(str, enum.Enum):
    """Volatility model used for surface fitting or calibration."""

    BLACK_SCHOLES = "black_scholes"
    HESTON = "heston"
    SABR = "sabr"
    SVI = "svi"


class MemoryType(str, enum.Enum):
    """Categories of durable agent knowledge."""

    INSIGHT = "insight"  # "RSI oversold + insider buying → 73% hit rate"
    PATTERN = "pattern"  # "Heston rho < -0.6 for tech names"
    FAILURE = "failure"  # "Thesis X failed: ignored sector rotation"
    SUCCESS = "success"  # "Energy thesis outperformed by 12%"


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


# ---------------------------------------------------------------------------
# 16. ChatConversation — multi-persona chat sessions
# ---------------------------------------------------------------------------


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str | None] = mapped_column(String(255))
    active_persona: Mapped[str] = mapped_column(String(30), default="analyst")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation",
        passive_deletes=True,
        order_by="ChatMessage.sequence",
    )


# ---------------------------------------------------------------------------
# 17. ChatMessage — individual messages in a conversation
# ---------------------------------------------------------------------------


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user/assistant/tool_call/tool_result
    persona: Mapped[str | None] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(100))
    tool_input: Mapped[dict | None] = mapped_column(JsonType)
    tool_result_data: Mapped[dict | None] = mapped_column(JsonType)
    model_used: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer)

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_chat_messages_conv_seq", "conversation_id", "sequence"),
    )


# ---------------------------------------------------------------------------
# 18. FeatureRequest — captured by the PM persona
# ---------------------------------------------------------------------------


class FeatureRequest(Base):
    __tablename__ = "feature_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chat_conversations.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    user_story: Mapped[str | None] = mapped_column(Text)
    acceptance_criteria: Mapped[list | None] = mapped_column(JsonType)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="captured")
    tags: Mapped[list | None] = mapped_column(JsonType)


# ---------------------------------------------------------------------------
# 19. MacroIndicator — FRED economic data series
# ---------------------------------------------------------------------------


class MacroIndicator(Base):
    __tablename__ = "macro_indicators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_id: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "FEDFUNDS"
    date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    series_name: Mapped[str | None] = mapped_column(String(100))  # human-readable

    __table_args__ = (
        UniqueConstraint("series_id", "date", name="uq_macro_series_date"),
        Index("ix_macro_series_date", "series_id", "date"),
    )


# ---------------------------------------------------------------------------
# 20. EarningsEvent — persisted earnings calendar from Finnhub
# ---------------------------------------------------------------------------


class EarningsEventDB(Base):
    __tablename__ = "earnings_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    hour: Mapped[str | None] = mapped_column(String(10))  # bmo/amc/dmh/""

    eps_estimate: Mapped[float | None] = mapped_column(Float)
    eps_actual: Mapped[float | None] = mapped_column(Float)
    revenue_estimate: Mapped[float | None] = mapped_column(Float)  # millions USD
    revenue_actual: Mapped[float | None] = mapped_column(Float)  # millions USD
    eps_surprise_pct: Mapped[float | None] = mapped_column(Float)
    rev_surprise_pct: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(50), default="finnhub")

    ticker: Mapped[Ticker] = relationship()

    __table_args__ = (
        UniqueConstraint("ticker_id", "event_date", name="uq_earnings_ticker_date"),
        Index("ix_earnings_ticker_date", "ticker_id", "event_date"),
        Index("ix_earnings_event_date", "event_date"),
    )


# ---------------------------------------------------------------------------
# 21. EarningsTranscript — earnings call transcripts from FMP
# ---------------------------------------------------------------------------


class EarningsTranscript(Base):
    __tablename__ = "earnings_transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    event_date: Mapped[date | None] = mapped_column(Date)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-4
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(50), default="fmp")
    content_hash: Mapped[str | None] = mapped_column(String(64))  # SHA-256

    ticker: Mapped[Ticker] = relationship()
    analysis: Mapped[EarningsAnalysis | None] = relationship(
        back_populates="transcript", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("ticker_id", "fiscal_year", "quarter", name="uq_transcript_ticker_fy_q"),
        Index("ix_transcript_ticker_date", "ticker_id", "event_date"),
    )


# ---------------------------------------------------------------------------
# 22. EarningsAnalysis — Claude Sonnet analysis of earnings transcripts
# ---------------------------------------------------------------------------


class EarningsAnalysis(Base):
    __tablename__ = "earnings_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transcript_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("earnings_transcripts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    overall_sentiment: Mapped[float | None] = mapped_column(Float)  # -1.0 to +1.0
    management_tone: Mapped[str | None] = mapped_column(String(20))  # confident/cautious/etc.
    forward_guidance_sentiment: Mapped[float | None] = mapped_column(Float)  # -1.0 to +1.0
    key_topics: Mapped[list | None] = mapped_column(JsonType)
    analyst_concerns: Mapped[list | None] = mapped_column(JsonType)
    management_quotes: Mapped[list | None] = mapped_column(JsonType)  # [{speaker, quote, sentiment}]
    summary: Mapped[str | None] = mapped_column(Text)
    bull_signals: Mapped[list | None] = mapped_column(JsonType)
    bear_signals: Mapped[list | None] = mapped_column(JsonType)
    tone_vs_prior: Mapped[str | None] = mapped_column(String(20))  # improving/stable/deteriorating
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_used: Mapped[str | None] = mapped_column(String(50))

    transcript: Mapped[EarningsTranscript] = relationship(back_populates="analysis")


# ---------------------------------------------------------------------------
# 23. User — authentication and authorization
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")  # admin/member/viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Token budget for viewers (protects Claude API key from abuse)
    daily_token_budget: Mapped[int] = mapped_column(Integer, default=50000)
    tokens_used_today: Mapped[int] = mapped_column(Integer, default=0)
    last_token_reset: Mapped[date | None] = mapped_column(Date)


# =========================================================================
# SIMULATION ENGINE MODELS (24-33)
# =========================================================================
# All P&L is simulated play-money. Zero real capital at risk.
# These models power the thesis lifecycle, stochastic vol calibration,
# backtesting, and agent self-improvement systems.
# =========================================================================


# ---------------------------------------------------------------------------
# 24. OptionsChain — market options data for IV surface construction
# ---------------------------------------------------------------------------


class OptionsChain(Base):
    __tablename__ = "options_chain"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )

    expiration: Mapped[date] = mapped_column(Date, nullable=False)
    strike: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    call_put: Mapped[str] = mapped_column(String(4), nullable=False)  # "call" or "put"

    # Market data
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    last: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)
    open_interest: Mapped[int | None] = mapped_column(Integer)

    # Derived / computed
    implied_vol: Mapped[float | None] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float)
    gamma: Mapped[float | None] = mapped_column(Float)
    theta: Mapped[float | None] = mapped_column(Float)
    vega: Mapped[float | None] = mapped_column(Float)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now()
    )

    ticker: Mapped[Ticker] = relationship()

    __table_args__ = (
        Index("ix_options_chain_ticker_exp_strike", "ticker_id", "expiration", "strike"),
        Index("ix_options_chain_fetched", "fetched_at"),
    )


# ---------------------------------------------------------------------------
# 25. VolSurface — fitted implied volatility surfaces
# ---------------------------------------------------------------------------


class VolSurface(Base):
    """Stores a fitted vol surface (strike × expiry → IV grid).

    Why we store the full surface: rebuilding from raw options data is expensive
    (SVI calibration, arbitrage checks). Caching the fitted surface lets the
    chat agents and dashboard render instantly.
    """

    __tablename__ = "vol_surfaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)

    # The surface itself: JSON grid of {expiry: {strike: iv, ...}, ...}
    surface_data: Mapped[dict | None] = mapped_column(JsonType)

    # Model used to fit
    model_type: Mapped[str] = mapped_column(String(20), nullable=False)  # VolModelType values
    model_params: Mapped[dict | None] = mapped_column(JsonType)  # SVI a,b,rho,m,sigma etc.
    calibration_error: Mapped[float | None] = mapped_column(Float)  # RMSE of fit

    ticker: Mapped[Ticker] = relationship()

    __table_args__ = (
        UniqueConstraint("ticker_id", "as_of", "model_type", name="uq_vol_surface_ticker_date_model"),
        Index("ix_vol_surface_ticker_date", "ticker_id", "as_of"),
    )


# ---------------------------------------------------------------------------
# 26. HestonCalibration — calibrated Heston stochastic vol parameters
# ---------------------------------------------------------------------------


class HestonCalibration(Base):
    """Stores calibrated Heston model parameters for a given ticker and date.

    The Heston model: dS = r*S*dt + sqrt(v)*S*dW1
                      dv = kappa*(theta - v)*dt + sigma_v*sqrt(v)*dW2
                      corr(dW1, dW2) = rho

    Five parameters capture what Black-Scholes cannot:
      v0      — current instantaneous variance (not constant!)
      kappa   — speed at which vol reverts to long-run mean
      theta   — long-run variance level
      sigma_v — vol-of-vol (how noisy the variance process itself is)
      rho     — correlation between stock and vol shocks (leverage effect)
    """

    __tablename__ = "heston_calibrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)

    # Heston parameters
    v0: Mapped[float] = mapped_column(Float, nullable=False)
    kappa: Mapped[float] = mapped_column(Float, nullable=False)
    theta: Mapped[float] = mapped_column(Float, nullable=False)
    sigma_v: Mapped[float] = mapped_column(Float, nullable=False)
    rho: Mapped[float] = mapped_column(Float, nullable=False)

    # Fit quality
    calibration_error: Mapped[float | None] = mapped_column(Float)  # RMSE
    market_iv_snapshot: Mapped[dict | None] = mapped_column(JsonType)  # input IVs used
    calibrated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now()
    )

    ticker: Mapped[Ticker] = relationship()

    __table_args__ = (
        UniqueConstraint("ticker_id", "as_of", name="uq_heston_cal_ticker_date"),
        Index("ix_heston_cal_ticker_date", "ticker_id", "as_of"),
    )


# ---------------------------------------------------------------------------
# 27. SimulatedThesis — auto-generated theses with full lifecycle
# ---------------------------------------------------------------------------


class SimulatedThesis(Base):
    """An investment thesis generated by the agent swarm.

    Unlike the static Thesis model (synced from theses.yaml), SimulatedThesis
    objects are born, tested, tracked, mutated, and eventually retired or killed.
    Every state transition is logged to SimulationLog for full auditability.

    All positions linked to these theses are PLAY MONEY.
    """

    __tablename__ = "simulated_theses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    thesis_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured criteria for entry/exit
    entry_criteria: Mapped[dict | None] = mapped_column(JsonType)
    exit_criteria: Mapped[dict | None] = mapped_column(JsonType)
    time_horizon_days: Mapped[int | None] = mapped_column(Integer)
    expected_catalysts: Mapped[list | None] = mapped_column(JsonType)
    risk_factors: Mapped[list | None] = mapped_column(JsonType)
    position_sizing: Mapped[dict | None] = mapped_column(JsonType)

    # Provenance
    generated_by: Mapped[str] = mapped_column(String(50), nullable=False)  # persona name
    generation_context: Mapped[dict | None] = mapped_column(JsonType)  # signals that triggered

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ThesisStatus.PROPOSED.value
    )
    parent_thesis_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("simulated_theses.id", ondelete="SET NULL")
    )
    ticker_ids: Mapped[list | None] = mapped_column(IntArrayType)  # target tickers
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retirement_reason: Mapped[str | None] = mapped_column(Text)

    # Relationships
    parent_thesis: Mapped[SimulatedThesis | None] = relationship(
        remote_side="SimulatedThesis.id"
    )
    backtest_runs: Mapped[list[BacktestRun]] = relationship(
        back_populates="thesis", passive_deletes=True
    )
    paper_positions: Mapped[list[PaperPosition]] = relationship(
        back_populates="thesis", passive_deletes=True
    )
    simulation_logs: Mapped[list[SimulationLog]] = relationship(
        back_populates="thesis", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_sim_thesis_status", "status"),
        Index("ix_sim_thesis_generated_by", "generated_by"),
    )


# ---------------------------------------------------------------------------
# 28. BacktestRun — walk-forward backtest results
# ---------------------------------------------------------------------------


class BacktestRun(Base):
    """Results from a walk-forward backtest of a SimulatedThesis.

    Includes standard quant metrics plus Monte Carlo permutation p-value
    to separate genuine signal from luck. p < 0.05 means the Sharpe ratio
    is unlikely to have arisen from random shuffling of daily returns.
    """

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("simulated_theses.id", ondelete="CASCADE"), nullable=False
    )
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )

    # Time window
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Capital
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False)
    final_capital: Mapped[float | None] = mapped_column(Float)

    # Performance metrics
    sharpe: Mapped[float | None] = mapped_column(Float)
    sortino: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)  # negative pct
    win_rate: Mapped[float | None] = mapped_column(Float)  # 0-1
    profit_factor: Mapped[float | None] = mapped_column(Float)  # gross_profit / gross_loss
    expectancy: Mapped[float | None] = mapped_column(Float)  # avg $ per trade
    total_trades: Mapped[int | None] = mapped_column(Integer)

    # Statistical significance
    monte_carlo_p_value: Mapped[float | None] = mapped_column(Float)

    # Full config and detailed results
    config: Mapped[dict | None] = mapped_column(JsonType)  # BacktestConfig as dict
    results_detail: Mapped[dict | None] = mapped_column(JsonType)  # trade-by-trade

    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now()
    )

    thesis: Mapped[SimulatedThesis] = relationship(back_populates="backtest_runs")
    ticker: Mapped[Ticker] = relationship()

    __table_args__ = (
        Index("ix_backtest_thesis_ran", "thesis_id", "ran_at"),
    )


# ---------------------------------------------------------------------------
# 29. PaperPortfolio — simulated play-money portfolio
# ---------------------------------------------------------------------------


class PaperPortfolio(Base):
    """A simulated portfolio for paper-trading thesis-linked positions.

    DISCLAIMER: All capital values are simulated. Zero real money at risk.
    This exists purely for learning and thesis validation.
    """

    __tablename__ = "paper_portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False, default=100_000.0)
    current_value: Mapped[float] = mapped_column(Float, nullable=False, default=100_000.0)
    cash: Mapped[float] = mapped_column(Float, nullable=False, default=100_000.0)
    total_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_pnl_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    positions: Mapped[list[PaperPosition]] = relationship(
        back_populates="portfolio", passive_deletes=True
    )


# ---------------------------------------------------------------------------
# 30. PaperPosition — individual thesis-linked paper trade
# ---------------------------------------------------------------------------


class PaperPosition(Base):
    """A single paper position within a PaperPortfolio.

    Each position is linked to the SimulatedThesis that generated it,
    enabling P&L attribution by thesis (which idea is driving returns?).
    """

    __tablename__ = "paper_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    thesis_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("simulated_theses.id", ondelete="CASCADE"), nullable=False
    )
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )

    side: Mapped[str] = mapped_column(String(10), nullable=False)  # PositionSide values
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_date: Mapped[date | None] = mapped_column(Date)
    exit_price: Mapped[float | None] = mapped_column(Float)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PositionStatus.OPEN.value
    )

    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    pnl: Mapped[float | None] = mapped_column(Float)
    pnl_pct: Mapped[float | None] = mapped_column(Float)

    portfolio: Mapped[PaperPortfolio] = relationship(back_populates="positions")
    thesis: Mapped[SimulatedThesis] = relationship(back_populates="paper_positions")
    ticker: Mapped[Ticker] = relationship()

    __table_args__ = (
        Index("ix_paper_pos_portfolio_status", "portfolio_id", "status"),
        Index("ix_paper_pos_thesis", "thesis_id"),
    )


# ---------------------------------------------------------------------------
# 31. SimulationLog — immutable decision journal
# ---------------------------------------------------------------------------


class SimulationLog(Base):
    """Immutable event log for the simulation engine.

    Every thesis generation, backtest, entry, exit, mutation, and retirement
    is recorded here with full context. This is how the Post-Mortem Priest
    reconstructs what happened and why — scar tissue as tuition.
    """

    __tablename__ = "simulation_logs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    thesis_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("simulated_theses.id", ondelete="SET NULL")
    )
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)  # SimEventType values
    event_data: Mapped[dict | None] = mapped_column(JsonType)

    thesis: Mapped[SimulatedThesis | None] = relationship(back_populates="simulation_logs")

    __table_args__ = (
        Index("ix_sim_log_thesis_created", "thesis_id", "created_at"),
        Index("ix_sim_log_event_type", "event_type", "created_at"),
    )


# ---------------------------------------------------------------------------
# 32. DeepHedgingModel — trained hedging policy metadata
# ---------------------------------------------------------------------------


class DeepHedgingModel(Base):
    """Metadata for a trained deep hedging policy (Buehler et al. 2019).

    The actual model weights can be stored as binary blob or referenced
    by file path. Training config, loss curves, and hedging error are
    stored here for experiment tracking.

    WHY CVaR loss: Traditional MSE penalizes all hedging errors equally.
    CVaR focuses on the worst 5% of outcomes — which is what actually matters
    in risk management. A policy that's great on average but occasionally
    blows up is worthless.
    """

    __tablename__ = "deep_hedging_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )

    model_blob: Mapped[bytes | None] = mapped_column(LargeBinary)
    training_config: Mapped[dict | None] = mapped_column(JsonType)
    training_loss: Mapped[float | None] = mapped_column(Float)
    validation_loss: Mapped[float | None] = mapped_column(Float)
    hedging_error: Mapped[float | None] = mapped_column(Float)  # avg |PnL| on test set
    epochs: Mapped[int | None] = mapped_column(Integer)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now()
    )

    ticker: Mapped[Ticker] = relationship()


# ---------------------------------------------------------------------------
# 33. AgentMemory — long-term agent learning and self-improvement
# ---------------------------------------------------------------------------


class AgentMemory(Base):
    """Durable knowledge extracted by agents over time.

    The Post-Mortem Priest reviews SimulationLog entries weekly,
    extracts durable insights, and stores them here. These memories
    are injected into agent system prompts to improve future decisions.

    If the user ghosts for 30 days, the system wakes up smarter —
    not because it ran, but because the memories are already baked in.
    """

    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(20), nullable=False)  # MemoryType values
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)  # 0-1
    evidence: Mapped[dict | None] = mapped_column(JsonType)  # supporting data refs
    last_accessed: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now()
    )
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_agent_memory_agent_type", "agent_name", "memory_type"),
        Index("ix_agent_memory_confidence", "confidence"),
    )
