"""
EdgeFinder — Alert Rule Engine

Composable, data-driven rule engine. Rules are dataclasses — not if/else chains.
Each rule evaluates a RuleContext (all signals for one ticker) and returns a
severity if triggered.

Built-in rules:
  rsi_oversold         – RSI below 28 on watchlist ticker
  golden_cross         – 50d SMA crosses above 200d SMA
  death_cross          – 50d SMA crosses below 200d SMA
  strong_dip           – DipScore composite ≥ 80
  dip_with_insider     – DipScore ≥ 70 AND insider buys in last 7d
  high_volume_move     – Volume ≥ 2× 20d avg AND price move ≥ 3%
  filing_red_flag      – health_score < 35 on most recent 10-K/10-Q

Entry point:
    alerts_created = await run_alert_engine(session)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Alert,
    EarningsEventDB,
    Filing,
    FilingAnalysis,
    InsiderTrade,
    PriceBar,
    TechnicalSnapshot,
    Ticker,
)

logger = logging.getLogger(__name__)

# Dedup: don't re-fire the same rule for the same ticker within N hours
DEDUP_HOURS: dict[str, int] = {
    "default": 24,
    "golden_cross": 72,
    "death_cross": 72,
    "filing_red_flag": 168,  # 1 week — filing doesn't change quickly
    "earnings_beat": 72,     # earnings don't repeat
    "earnings_miss": 72,
    "earnings_tone_shift": 168,
}

# Per-ticker per-type daily rate limit
MAX_ALERTS_PER_TYPE_PER_DAY = 3


# ---------------------------------------------------------------------------
# Rule context — all signals for one ticker at one point in time
# ---------------------------------------------------------------------------


@dataclass
class RuleContext:
    ticker: Ticker

    # Price
    current_price: float = 0.0
    change_5d_pct: float = 0.0       # % change last 5 trading days
    high_20d: float = 0.0
    low_20d: float = 0.0

    # Technical indicators (latest snapshot)
    rsi: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    volume_ratio_20d: float | None = None  # current vol / 20d avg vol

    # Previous snapshot (for cross detection)
    prev_sma_50: float | None = None
    prev_sma_200: float | None = None

    # Fundamental
    health_score: float | None = None      # 0-100 from FilingAnalysis
    red_flag_count: int = 0

    # Insider trades last 7d
    insider_buy_count: int = 0
    insider_buy_value: float = 0.0

    # Dip score composite (from alerts table)
    dip_score: float | None = None

    # Earnings (from earnings_events table)
    eps_surprise_pct: float | None = None
    rev_surprise_pct: float | None = None
    earnings_beat: bool | None = None  # True=beat, False=miss, None=no data


# ---------------------------------------------------------------------------
# AlertRule dataclass
# ---------------------------------------------------------------------------


@dataclass
class AlertRule:
    name: str
    condition: Callable[[RuleContext], bool]
    severity: str  # "green" | "yellow" | "red"
    alert_type: str
    title_fn: Callable[[RuleContext], str]
    body_fn: Callable[[RuleContext], str] = field(default_factory=lambda: lambda ctx: "")

    def evaluate(self, ctx: RuleContext) -> bool:
        try:
            return self.condition(ctx)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------

RULES: list[AlertRule] = [
    AlertRule(
        name="rsi_oversold",
        alert_type="rsi_oversold",
        severity="yellow",
        condition=lambda ctx: ctx.rsi is not None and ctx.rsi < 28,
        title_fn=lambda ctx: f"{ctx.ticker.symbol} RSI oversold: {ctx.rsi:.1f}",
        body_fn=lambda ctx: (
            f"RSI 14-day = {ctx.rsi:.1f} — below oversold threshold (28).\n"
            f"Price: ${ctx.current_price:.2f}  |  5d change: {ctx.change_5d_pct:+.1f}%"
        ),
    ),
    AlertRule(
        name="golden_cross",
        alert_type="golden_cross",
        severity="green",
        condition=lambda ctx: (
            ctx.sma_50 is not None
            and ctx.sma_200 is not None
            and ctx.prev_sma_50 is not None
            and ctx.prev_sma_200 is not None
            and ctx.prev_sma_50 <= ctx.prev_sma_200  # was below
            and ctx.sma_50 > ctx.sma_200              # now above
        ),
        title_fn=lambda ctx: f"{ctx.ticker.symbol} golden cross (50d > 200d)",
        body_fn=lambda ctx: (
            f"50-day SMA crossed above 200-day SMA.\n"
            f"SMA50: ${ctx.sma_50:.2f}  |  SMA200: ${ctx.sma_200:.2f}"
        ),
    ),
    AlertRule(
        name="death_cross",
        alert_type="death_cross",
        severity="red",
        condition=lambda ctx: (
            ctx.sma_50 is not None
            and ctx.sma_200 is not None
            and ctx.prev_sma_50 is not None
            and ctx.prev_sma_200 is not None
            and ctx.prev_sma_50 >= ctx.prev_sma_200  # was above
            and ctx.sma_50 < ctx.sma_200              # now below
        ),
        title_fn=lambda ctx: f"{ctx.ticker.symbol} death cross (50d < 200d)",
        body_fn=lambda ctx: (
            f"50-day SMA crossed below 200-day SMA — bearish signal.\n"
            f"SMA50: ${ctx.sma_50:.2f}  |  SMA200: ${ctx.sma_200:.2f}"
        ),
    ),
    AlertRule(
        name="strong_dip",
        alert_type="buy_the_dip",
        severity="yellow",
        condition=lambda ctx: ctx.dip_score is not None and ctx.dip_score >= 80,
        title_fn=lambda ctx: (
            f"{ctx.ticker.symbol} strong dip score: {ctx.dip_score:.0f}/100"
        ),
        body_fn=lambda ctx: (
            f"Dip composite score = {ctx.dip_score:.1f}. Price: ${ctx.current_price:.2f}  "
            f"|  5d: {ctx.change_5d_pct:+.1f}%"
        ),
    ),
    AlertRule(
        name="dip_with_insider",
        alert_type="buy_the_dip",
        severity="red",
        condition=lambda ctx: (
            ctx.dip_score is not None
            and ctx.dip_score >= 70
            and ctx.insider_buy_count > 0
        ),
        title_fn=lambda ctx: (
            f"{ctx.ticker.symbol} dip + insider buy ({ctx.insider_buy_count} buys, "
            f"${ctx.insider_buy_value/1e6:.1f}M)"
        ),
        body_fn=lambda ctx: (
            f"Dip score {ctx.dip_score:.1f}  |  "
            f"Insiders bought {ctx.insider_buy_count}x in last 7d "
            f"(${ctx.insider_buy_value/1e6:.1f}M).\n"
            f"Price: ${ctx.current_price:.2f}  |  5d: {ctx.change_5d_pct:+.1f}%"
        ),
    ),
    AlertRule(
        name="high_volume_move",
        alert_type="volume_spike",
        severity="yellow",
        condition=lambda ctx: (
            ctx.volume_ratio_20d is not None
            and ctx.volume_ratio_20d >= 2.0
            and abs(ctx.change_5d_pct) >= 3.0
        ),
        title_fn=lambda ctx: (
            f"{ctx.ticker.symbol} high-volume move: "
            f"{ctx.change_5d_pct:+.1f}% on {ctx.volume_ratio_20d:.1f}× avg volume"
        ),
        body_fn=lambda ctx: (
            f"Volume {ctx.volume_ratio_20d:.1f}× 20-day average. "
            f"Price: ${ctx.current_price:.2f}  |  5d: {ctx.change_5d_pct:+.1f}%"
        ),
    ),
    AlertRule(
        name="filing_red_flag",
        alert_type="filing_risk",
        severity="red",
        condition=lambda ctx: ctx.health_score is not None and ctx.health_score < 35,
        title_fn=lambda ctx: (
            f"{ctx.ticker.symbol} filing health score low: {ctx.health_score:.0f}/100"
            + (f" ({ctx.red_flag_count} red flags)" if ctx.red_flag_count else "")
        ),
        body_fn=lambda ctx: (
            f"Most recent 10-K/10-Q health score: {ctx.health_score:.0f}/100. "
            f"Red flags: {ctx.red_flag_count}."
        ),
    ),
    # --- Earnings surprise rules ---
    AlertRule(
        name="earnings_beat",
        alert_type="earnings_beat",
        severity="yellow",
        condition=lambda ctx: (
            ctx.earnings_beat is True
            and ctx.eps_surprise_pct is not None
            and ctx.eps_surprise_pct > 15.0
        ),
        title_fn=lambda ctx: (
            f"{ctx.ticker.symbol} earnings beat: EPS +{ctx.eps_surprise_pct:.1f}% vs estimate"
        ),
        body_fn=lambda ctx: (
            f"EPS surprise: +{ctx.eps_surprise_pct:.1f}%"
            + (f"  |  Revenue surprise: {ctx.rev_surprise_pct:+.1f}%"
               if ctx.rev_surprise_pct is not None else "")
            + f"\nPrice: ${ctx.current_price:.2f}"
        ),
    ),
    AlertRule(
        name="earnings_miss",
        alert_type="earnings_miss",
        severity="red",
        condition=lambda ctx: (
            ctx.earnings_beat is False
            and ctx.eps_surprise_pct is not None
            and ctx.eps_surprise_pct < -10.0
        ),
        title_fn=lambda ctx: (
            f"{ctx.ticker.symbol} earnings miss: EPS {ctx.eps_surprise_pct:.1f}% vs estimate"
        ),
        body_fn=lambda ctx: (
            f"EPS surprise: {ctx.eps_surprise_pct:.1f}%"
            + (f"  |  Revenue surprise: {ctx.rev_surprise_pct:+.1f}%"
               if ctx.rev_surprise_pct is not None else "")
            + f"\nPrice: ${ctx.current_price:.2f}"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


async def _build_context(session: AsyncSession, ticker: Ticker) -> RuleContext:
    ctx = RuleContext(ticker=ticker)

    # Price bars: last 22 days
    bars_result = await session.execute(
        select(PriceBar.close, PriceBar.volume, PriceBar.date)
        .where(PriceBar.ticker_id == ticker.id)
        .order_by(desc(PriceBar.date))
        .limit(22)
    )
    bars = bars_result.fetchall()
    if bars:
        ctx.current_price = bars[0].close
        ctx.high_20d = max(b.close for b in bars)
        ctx.low_20d = min(b.close for b in bars)
        if len(bars) >= 5:
            ctx.change_5d_pct = (bars[0].close - bars[4].close) / bars[4].close * 100

    # Technical snapshots: last 2 (for cross detection)
    tech_result = await session.execute(
        select(TechnicalSnapshot)
        .where(TechnicalSnapshot.ticker_id == ticker.id)
        .order_by(desc(TechnicalSnapshot.date))
        .limit(2)
    )
    techs = tech_result.scalars().all()
    if techs:
        t = techs[0]
        ctx.rsi = t.rsi_14
        ctx.sma_50 = t.sma_50
        ctx.sma_200 = t.sma_200
        ctx.volume_ratio_20d = t.volume_ratio_20d
    if len(techs) >= 2:
        ctx.prev_sma_50 = techs[1].sma_50
        ctx.prev_sma_200 = techs[1].sma_200

    # Fundamental: latest analyzed filing
    fund_result = await session.execute(
        select(FilingAnalysis.health_score, FilingAnalysis.red_flags)
        .join(Filing, FilingAnalysis.filing_id == Filing.id)
        .where(
            Filing.ticker_id == ticker.id,
            Filing.filing_type.in_(["10-K", "10-Q"]),
            FilingAnalysis.health_score.isnot(None),
        )
        .order_by(desc(Filing.filed_date))
        .limit(1)
    )
    fund = fund_result.one_or_none()
    if fund:
        ctx.health_score = fund.health_score
        ctx.red_flag_count = len(fund.red_flags or [])

    # Insider buys last 7 days
    cutoff_7d = date.today() - timedelta(days=7)
    ins_result = await session.execute(
        select(func.count(InsiderTrade.id), func.sum(InsiderTrade.total_amount))
        .where(
            InsiderTrade.ticker_id == ticker.id,
            InsiderTrade.trade_type == "buy",
            InsiderTrade.transaction_date >= cutoff_7d,
        )
    )
    ins_count, ins_value = ins_result.one()
    ctx.insider_buy_count = ins_count or 0
    ctx.insider_buy_value = float(ins_value or 0)

    # Most recent earnings event (last 7 days, with actuals)
    earnings_result = await session.execute(
        select(EarningsEventDB)
        .where(
            EarningsEventDB.ticker_id == ticker.id,
            EarningsEventDB.eps_actual.isnot(None),
            EarningsEventDB.eps_estimate.isnot(None),
            EarningsEventDB.event_date >= date.today() - timedelta(days=7),
        )
        .order_by(desc(EarningsEventDB.event_date))
        .limit(1)
    )
    earnings = earnings_result.scalar_one_or_none()
    if earnings:
        ctx.eps_surprise_pct = earnings.eps_surprise_pct
        ctx.rev_surprise_pct = earnings.rev_surprise_pct
        ctx.earnings_beat = (
            earnings.eps_actual >= earnings.eps_estimate
            if earnings.eps_actual is not None and earnings.eps_estimate is not None
            else None
        )

    # Most recent dip score
    dip_result = await session.execute(
        select(Alert.score)
        .where(
            Alert.ticker_id == ticker.id,
            Alert.alert_type == "buy_the_dip",
            Alert.dismissed_at.is_(None),
        )
        .order_by(desc(Alert.created_at))
        .limit(1)
    )
    ctx.dip_score = dip_result.scalar_one_or_none()

    return ctx


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


async def _is_duped(session: AsyncSession, ticker_id: int, alert_type: str) -> bool:
    hours = DEDUP_HOURS.get(alert_type, DEDUP_HOURS["default"])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Check dedup window
    result = await session.execute(
        select(Alert.id)
        .where(
            Alert.ticker_id == ticker_id,
            Alert.alert_type == alert_type,
            Alert.created_at >= cutoff,
        )
        .limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return True

    # Rate limit: max N per day per type
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    count_result = await session.execute(
        select(func.count(Alert.id))
        .where(
            Alert.ticker_id == ticker_id,
            Alert.alert_type == alert_type,
            Alert.created_at >= today_start,
        )
    )
    return (count_result.scalar_one() or 0) >= MAX_ALERTS_PER_TYPE_PER_DAY


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_alert_engine(session: AsyncSession) -> int:
    """
    Run all alert rules against all active watchlist tickers.
    Creates Alert records for any triggered, non-deduped rules.
    Returns the number of new alerts created.
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
        ctx = await _build_context(session, ticker)
        if not ctx.current_price:
            continue  # No price data — skip

        for rule in RULES:
            if not rule.evaluate(ctx):
                continue
            if await _is_duped(session, ticker.id, rule.alert_type):
                logger.debug("Alert deduped: %s / %s", ticker.symbol, rule.name)
                continue

            alert = Alert(
                ticker_id=ticker.id,
                alert_type=rule.alert_type,
                severity=rule.severity,
                title=rule.title_fn(ctx),
                body=rule.body_fn(ctx),
                context_json={
                    "rule": rule.name,
                    "rsi": ctx.rsi,
                    "sma_50": ctx.sma_50,
                    "sma_200": ctx.sma_200,
                    "change_5d_pct": ctx.change_5d_pct,
                    "health_score": ctx.health_score,
                    "dip_score": ctx.dip_score,
                },
            )
            session.add(alert)
            created += 1
            logger.info(
                "Alert fired: rule=%s  ticker=%s  severity=%s",
                rule.name, ticker.symbol, rule.severity,
            )

    if created:
        await session.flush()

    logger.info(
        "run_alert_engine: %d new alerts from %d watchlist tickers (%d rules)",
        created, len(tickers), len(RULES),
    )
    return created
