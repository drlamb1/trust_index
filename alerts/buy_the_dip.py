"""
EdgeFinder — Buy The Dip Scorer

8-dimension composite score that evaluates whether a price drop represents
a genuine buying opportunity. Only fires for watchlist tickers.

Score dimensions (weights sum to 1.0):
  0.25  price_drop_magnitude     – Normalized drop vs recent high
  0.20  fundamental_score        – FilingAnalysis health score (0-100)
  0.15  technical_setup          – RSI oversold + Bollinger proximity
  0.15  sentiment_context        – Drop NOT explained by bad news (inverted)
  0.10  insider_activity         – Form 4 cluster buys in last 7 days
  0.10  drop_vs_historical_vol   – Drop relative to ATR (sigma of move)
  0.05  sector_relative          – Systematic vs isolated drop

Alert tiers:
  green  ≥ 60 : Moderate dip in quality name — worth watching
  yellow ≥ 75 : Strong dip with intact fundamentals
  red    ≥ 88 : Exceptional — deep dip, strong fundamentals, insiders buying

Entry points:
    count = await compute_dip_scores(session)       # all watchlist tickers
    ctx   = await score_ticker(session, ticker)     # single ticker
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Alert,
    DipScore,
    Filing,
    FilingAnalysis,
    InsiderTrade,
    NewsArticle,
    PriceBar,
    TechnicalSnapshot,
    Ticker,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WEIGHTS = {
    "price_drop_magnitude": 0.25,
    "fundamental_score": 0.20,
    "technical_setup": 0.15,
    "sentiment_context": 0.15,
    "drop_vs_historical_vol": 0.10,
    "insider_activity": 0.10,
    "sector_relative": 0.05,
}

TIER_GREEN = 60
TIER_YELLOW = 75
TIER_RED = 88

# Minimum 5-day drop to qualify for scoring (vs 20-day high)
DROP_THRESHOLD_PCT = 3.0

# Dedup window: don't re-fire the same alert type for same ticker
DEDUP_HOURS = 24


# ---------------------------------------------------------------------------
# Score context dataclass
# ---------------------------------------------------------------------------


@dataclass
class DipContext:
    ticker_id: int
    symbol: str

    # Raw data
    drop_pct: float = 0.0        # % below 20-day high
    current_price: float = 0.0
    atr_pct: float = 0.0         # ATR as % of price
    rsi: float | None = None

    # Dimension scores (0-100)
    price_drop_magnitude: float = 0.0
    drop_vs_historical_vol: float = 0.0
    fundamental_score: float = 50.0     # default neutral
    technical_setup: float = 0.0
    sentiment_context: float = 50.0     # default neutral
    insider_activity: float = 0.0
    institutional_support: float = 50.0
    sector_relative: float = 50.0       # default neutral

    @property
    def composite_score(self) -> float:
        return round(
            self.price_drop_magnitude * WEIGHTS["price_drop_magnitude"]
            + self.fundamental_score * WEIGHTS["fundamental_score"]
            + self.technical_setup * WEIGHTS["technical_setup"]
            + self.sentiment_context * WEIGHTS["sentiment_context"]
            + self.drop_vs_historical_vol * WEIGHTS["drop_vs_historical_vol"]
            + self.insider_activity * WEIGHTS["insider_activity"]
            + self.sector_relative * WEIGHTS["sector_relative"],
            1,
        )

    @property
    def severity(self) -> str:
        s = self.composite_score
        if s >= TIER_RED:
            return "red"
        if s >= TIER_YELLOW:
            return "yellow"
        return "green"

    @property
    def qualifies(self) -> bool:
        return self.composite_score >= TIER_GREEN


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _score_price_drop(drop_pct: float) -> float:
    """Score the magnitude of the price drop. 20%+ = 100."""
    return min(100.0, drop_pct * 5.0)


def _score_drop_vs_vol(drop_pct: float, atr_pct: float) -> float:
    """Score drop relative to ATR. 3× ATR drop = 100."""
    if atr_pct <= 0:
        return 0.0
    sigmas = drop_pct / atr_pct
    return min(100.0, sigmas * 33.3)


def _score_technical(rsi: float | None, bb_pct: float | None) -> float:
    """Score oversold technical setup using RSI and Bollinger position."""
    score = 0.0
    if rsi is not None:
        if rsi < 20:
            score += 80
        elif rsi < 30:
            score += 60
        elif rsi < 40:
            score += 35
        elif rsi < 50:
            score += 15
    if bb_pct is not None:
        # bb_pct = (price - bb_lower) / (bb_upper - bb_lower)
        # Near lower band (< 0.15) = strong signal
        if bb_pct < 0.05:
            score += 25
        elif bb_pct < 0.15:
            score += 15
        elif bb_pct < 0.25:
            score += 5
    return min(100.0, score)


def _score_sentiment(avg_sentiment: float | None) -> float:
    """
    Higher score = drop NOT explained by bad news (contrarian opportunity).
    sentiment_score in DB is -1 (very negative) to +1 (very positive).
    """
    if avg_sentiment is None:
        return 50.0  # neutral: no news
    # Invert: positive sentiment during a dip = strong contrarian signal
    return min(100.0, max(0.0, 50.0 + avg_sentiment * 50.0))


def _score_insider(buy_count: int, total_value: float) -> float:
    """Score insider buy activity in last 7 days."""
    if buy_count == 0:
        return 0.0
    base = min(60.0, buy_count * 20.0)
    # Bonus for large dollar amounts
    if total_value >= 5_000_000:
        base = min(100.0, base + 40)
    elif total_value >= 1_000_000:
        base = min(100.0, base + 25)
    elif total_value >= 500_000:
        base = min(100.0, base + 15)
    return base


def _score_sector_relative(ticker_drop: float, spy_drop: float) -> float:
    """
    Score whether this is a systematic (sector-wide) or isolated drop.
    Systematic drops (whole market down) score higher — more likely to recover.
    """
    if spy_drop <= 0:
        # Market up but ticker down — isolated. Could be company-specific.
        return 30.0
    ratio = ticker_drop / max(spy_drop, 0.01)
    if ratio <= 1.5:
        # Ticker dropped similarly to market — systematic
        return 70.0
    elif ratio <= 3.0:
        # Ticker dropped moderately more than market
        return 50.0
    else:
        # Ticker dropped much more than market — company-specific concern
        return 25.0


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


async def _get_spy_drop(session: AsyncSession, lookback: int = 5) -> float:
    """Get SPY's % drop over last N trading days. Returns positive number if down."""
    result = await session.execute(
        select(PriceBar.close, PriceBar.date)
        .join(Ticker, PriceBar.ticker_id == Ticker.id)
        .where(Ticker.symbol == "SPY")
        .order_by(desc(PriceBar.date))
        .limit(lookback + 1)
    )
    rows = result.fetchall()
    if len(rows) < 2:
        return 0.0
    latest = rows[0].close
    oldest = rows[-1].close
    return max(0.0, (oldest - latest) / oldest * 100)


async def score_ticker(session: AsyncSession, ticker: Ticker) -> DipContext | None:
    """
    Compute the full dip score for a single ticker.
    Returns None if the ticker doesn't qualify (drop < threshold).
    """
    ctx = DipContext(ticker_id=ticker.id, symbol=ticker.symbol)

    # ------------------------------------------------------------------
    # 1. Price drop: compare current price to 20-day high
    # ------------------------------------------------------------------
    bars_result = await session.execute(
        select(PriceBar.close, PriceBar.date)
        .where(PriceBar.ticker_id == ticker.id)
        .order_by(desc(PriceBar.date))
        .limit(22)
    )
    bars = bars_result.fetchall()
    if len(bars) < 5:
        return None

    ctx.current_price = bars[0].close
    high_20d = max(b.close for b in bars)
    ctx.drop_pct = max(0.0, (high_20d - ctx.current_price) / high_20d * 100)

    if ctx.drop_pct < DROP_THRESHOLD_PCT:
        return None  # Not enough of a dip

    ctx.price_drop_magnitude = _score_price_drop(ctx.drop_pct)

    # ------------------------------------------------------------------
    # 2. Technical setup: RSI + Bollinger from latest TechnicalSnapshot
    # ------------------------------------------------------------------
    tech_result = await session.execute(
        select(TechnicalSnapshot)
        .where(TechnicalSnapshot.ticker_id == ticker.id)
        .order_by(desc(TechnicalSnapshot.date))
        .limit(1)
    )
    tech = tech_result.scalar_one_or_none()

    if tech:
        ctx.rsi = tech.rsi_14
        ctx.atr_pct = (tech.atr_14 / ctx.current_price * 100) if tech.atr_14 and ctx.current_price else 0.0

        bb_pct: float | None = None
        if tech.bb_upper and tech.bb_lower and tech.bb_upper != tech.bb_lower:
            bb_pct = (ctx.current_price - tech.bb_lower) / (tech.bb_upper - tech.bb_lower)

        ctx.technical_setup = _score_technical(ctx.rsi, bb_pct)
        ctx.drop_vs_historical_vol = _score_drop_vs_vol(ctx.drop_pct, ctx.atr_pct)

    # ------------------------------------------------------------------
    # 3. Fundamental score: latest 10-K health score
    # ------------------------------------------------------------------
    fund_result = await session.execute(
        select(FilingAnalysis.health_score)
        .join(Filing, FilingAnalysis.filing_id == Filing.id)
        .where(
            Filing.ticker_id == ticker.id,
            Filing.filing_type.in_(["10-K", "10-Q"]),
            FilingAnalysis.health_score.isnot(None),
        )
        .order_by(desc(Filing.filed_date))
        .limit(1)
    )
    health = fund_result.scalar_one_or_none()
    if health is not None:
        ctx.fundamental_score = float(health)

    # ------------------------------------------------------------------
    # 4. Sentiment context: avg sentiment of news last 3 days
    # ------------------------------------------------------------------
    cutoff_3d = datetime.now(timezone.utc) - timedelta(days=3)
    sent_result = await session.execute(
        select(func.avg(NewsArticle.sentiment_score))
        .where(
            NewsArticle.ticker_ids.contains([ticker.id]),
            NewsArticle.published_at >= cutoff_3d,
            NewsArticle.sentiment_score.isnot(None),
        )
    )
    avg_sent = sent_result.scalar_one_or_none()
    ctx.sentiment_context = _score_sentiment(float(avg_sent) if avg_sent is not None else None)

    # ------------------------------------------------------------------
    # 5. Insider activity: Form 4 buys last 7 days
    # ------------------------------------------------------------------
    cutoff_7d = date.today() - timedelta(days=7)
    insider_result = await session.execute(
        select(
            func.count(InsiderTrade.id),
            func.sum(InsiderTrade.total_amount),
        )
        .where(
            InsiderTrade.ticker_id == ticker.id,
            InsiderTrade.trade_type == "buy",
            InsiderTrade.transaction_date >= cutoff_7d,
        )
    )
    ins_count, ins_value = insider_result.one()
    ctx.insider_activity = _score_insider(ins_count or 0, float(ins_value or 0))
    if (ins_count or 0) == 0:
        logger.debug("No insider trades found for %s — insider score is 0", ticker.symbol)

    # ------------------------------------------------------------------
    # 6. Sector relative: compare to SPY over last 5 days
    # ------------------------------------------------------------------
    spy_drop = await _get_spy_drop(session)
    ctx.sector_relative = _score_sector_relative(ctx.drop_pct, spy_drop)

    return ctx


# ---------------------------------------------------------------------------
# Deduplication check
# ---------------------------------------------------------------------------


async def _alert_exists(session: AsyncSession, ticker_id: int) -> bool:
    """Return True if an active dip alert was created for this ticker recently."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)
    result = await session.execute(
        select(Alert.id)
        .where(
            Alert.ticker_id == ticker_id,
            Alert.alert_type == "buy_the_dip",
            Alert.created_at >= cutoff,
            Alert.dismissed_at.is_(None),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Persist alert + dip score
# ---------------------------------------------------------------------------


async def _persist(session: AsyncSession, ctx: DipContext) -> None:
    """Write Alert + DipScore rows for a qualifying dip."""
    title = (
        f"{ctx.symbol} dip {ctx.drop_pct:.1f}% below 20d-high"
        f" — composite {ctx.composite_score:.0f}"
    )
    body_parts = [
        f"Drop: {ctx.drop_pct:.1f}%  |  Score: {ctx.composite_score:.1f}  |  Tier: {ctx.severity.upper()}",
        f"Fundamentals: {ctx.fundamental_score:.0f}/100"
        + (f"  |  RSI: {ctx.rsi:.1f}" if ctx.rsi else ""),
        f"Insider buys (7d): {ctx.insider_activity:.0f}/100"
        f"  |  Sentiment: {ctx.sentiment_context:.0f}/100",
    ]

    alert = Alert(
        ticker_id=ctx.ticker_id,
        alert_type="buy_the_dip",
        severity=ctx.severity,
        score=ctx.composite_score,
        title=title,
        body="\n".join(body_parts),
        context_json={
            "drop_pct": ctx.drop_pct,
            "current_price": ctx.current_price,
            "rsi": ctx.rsi,
            "dimensions": {
                "price_drop_magnitude": ctx.price_drop_magnitude,
                "fundamental_score": ctx.fundamental_score,
                "technical_setup": ctx.technical_setup,
                "sentiment_context": ctx.sentiment_context,
                "insider_activity": ctx.insider_activity,
                "drop_vs_historical_vol": ctx.drop_vs_historical_vol,
                "sector_relative": ctx.sector_relative,
            },
        },
    )
    session.add(alert)
    await session.flush()  # get alert.id

    dip = DipScore(
        alert_id=alert.id,
        price_drop_magnitude=ctx.price_drop_magnitude,
        drop_vs_historical_vol=ctx.drop_vs_historical_vol,
        fundamental_score=ctx.fundamental_score,
        technical_setup=ctx.technical_setup,
        sentiment_context=ctx.sentiment_context,
        insider_activity=ctx.insider_activity,
        institutional_support=ctx.institutional_support,
        sector_relative=ctx.sector_relative,
        composite_score=ctx.composite_score,
    )
    session.add(dip)
    logger.info(
        "DipAlert created: %s  score=%.1f  severity=%s",
        ctx.symbol, ctx.composite_score, ctx.severity,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def compute_dip_scores(session: AsyncSession) -> int:
    """
    Run the dip scorer for all active watchlist tickers.
    Creates Alert + DipScore records for qualifying dips.
    Returns the number of alerts created.
    """
    result = await session.execute(
        select(Ticker).where(
            Ticker.is_active.is_(True),
            Ticker.in_watchlist.is_(True),
        )
    )
    tickers = result.scalars().all()

    created = 0
    for ticker in tickers:
        ctx = await score_ticker(session, ticker)
        if ctx is None or not ctx.qualifies:
            continue
        if await _alert_exists(session, ticker.id):
            logger.debug("DipAlert deduped for %s (recent alert exists)", ticker.symbol)
            continue
        await _persist(session, ctx)
        created += 1

    if created:
        await session.flush()

    logger.info("compute_dip_scores: %d alerts created from %d watchlist tickers", created, len(tickers))
    return created
