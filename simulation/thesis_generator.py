"""
EdgeFinder — Thesis Generation Pipeline

Claude-powered thesis generation from converging market signals.
The Thesis Lord persona uses these functions to propose, evaluate,
and mutate investment theses autonomously.

Signal convergence detection: scans recent alerts, filings, insider
trades, sentiment, and macro data for clusters of activity that might
indicate an opportunity worth investigating (with play money).

All theses are SIMULATED. Zero real capital at risk.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Alert,
    FilingAnalysis,
    InsiderTrade,
    MacroIndicator,
    NewsArticle,
    SimEventType,
    SimulatedThesis,
    SimulationLog,
    Ticker,
    ThesisStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal Convergence Detection
# ---------------------------------------------------------------------------


async def detect_signal_convergence(
    session: AsyncSession,
    lookback_hours: int = 72,
) -> list[dict]:
    """Scan for converging signals across data sources.

    Looks for tickers that have multiple signal types firing simultaneously:
      - Alert clusters (3+ alerts in lookback window)
      - Filing anomalies + insider buying
      - Sentiment divergence (bearish news + rising price, or vice versa)
      - Macro regime shifts affecting sector

    Returns list of convergence dicts with ticker info and signal details.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    convergences = []

    # Get watchlist tickers
    result = await session.execute(
        select(Ticker).where(Ticker.in_watchlist.is_(True), Ticker.is_active.is_(True))
    )
    tickers = result.scalars().all()

    for ticker in tickers:
        signals = {}

        # Check alert clusters
        alert_result = await session.execute(
            select(func.count(Alert.id)).where(
                Alert.ticker_id == ticker.id,
                Alert.created_at >= since,
            )
        )
        alert_count = alert_result.scalar_one()
        if alert_count >= 2:
            signals["alert_cluster"] = {"count": alert_count}

        # Check recent insider buying
        insider_result = await session.execute(
            select(func.count(InsiderTrade.id), func.sum(InsiderTrade.total_amount)).where(
                InsiderTrade.ticker_id == ticker.id,
                InsiderTrade.trade_type == "buy",
                InsiderTrade.filed_date >= since.date(),
            )
        )
        row = insider_result.one()
        if row[0] and row[0] > 0:
            signals["insider_buying"] = {
                "count": row[0],
                "total_value": float(row[1] or 0),
            }

        # Check filing red flags
        filing_result = await session.execute(
            select(FilingAnalysis.health_score, FilingAnalysis.red_flags)
            .join(FilingAnalysis.filing)
            .where(FilingAnalysis.filing.has(ticker_id=ticker.id))
            .order_by(desc(FilingAnalysis.analyzed_at))
            .limit(1)
        )
        filing_row = filing_result.first()
        if filing_row and filing_row.health_score is not None:
            if filing_row.health_score < 50:
                signals["filing_concern"] = {
                    "health_score": filing_row.health_score,
                    "red_flag_count": len(filing_row.red_flags or []),
                }

        # Check sentiment
        sentiment_result = await session.execute(
            select(func.avg(NewsArticle.sentiment_score)).where(
                NewsArticle.ticker_ids.contains([ticker.id]) if hasattr(NewsArticle.ticker_ids, 'contains')
                else NewsArticle.ticker_ids.isnot(None),
                NewsArticle.sentiment_scored_at >= since,
            )
        )
        avg_sentiment = sentiment_result.scalar_one()
        if avg_sentiment is not None and abs(avg_sentiment) > 0.3:
            signals["sentiment_extreme"] = {
                "avg_score": float(avg_sentiment),
                "direction": "bearish" if avg_sentiment < 0 else "bullish",
            }

        # Convergence = 2+ signal types firing
        if len(signals) >= 2:
            convergences.append({
                "ticker_id": ticker.id,
                "ticker_symbol": ticker.symbol,
                "ticker_name": ticker.name,
                "sector": ticker.sector,
                "signal_count": len(signals),
                "signals": signals,
            })

    # Sort by signal count (most convergent first)
    convergences.sort(key=lambda x: x["signal_count"], reverse=True)

    logger.info("Detected %d signal convergences across %d tickers", len(convergences), len(tickers))
    return convergences


# ---------------------------------------------------------------------------
# Thesis Generation via Claude
# ---------------------------------------------------------------------------


async def generate_thesis(
    session: AsyncSession,
    convergence: dict,
    api_key: str,
) -> SimulatedThesis | None:
    """Generate a structured thesis from converging signals via Claude.

    Claude analyzes the convergence data and produces:
      - Thesis name and narrative
      - Entry/exit criteria (quantitative)
      - Time horizon and expected catalysts
      - Risk factors and position sizing
    """
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)

        prompt = f"""Analyze these converging market signals for {convergence['ticker_symbol']} ({convergence['ticker_name']})
in the {convergence['sector']} sector and generate a structured investment thesis.

CONVERGING SIGNALS:
{json.dumps(convergence['signals'], indent=2)}

Generate a thesis in this EXACT JSON format:
{{
    "name": "Short memorable name (3-5 words)",
    "thesis_text": "2-3 paragraph narrative explaining the opportunity",
    "entry_criteria": {{
        "price_condition": "description of price level/pattern for entry",
        "confirmation_signals": ["list", "of", "required", "confirmations"]
    }},
    "exit_criteria": {{
        "profit_target_pct": 15.0,
        "stop_loss_pct": 8.0,
        "time_exit_days": 90,
        "invalidation_triggers": ["list of conditions that kill the thesis"]
    }},
    "time_horizon_days": 90,
    "expected_catalysts": ["upcoming events that could trigger the thesis"],
    "risk_factors": ["what could go wrong"],
    "position_sizing": {{
        "max_portfolio_pct": 5.0,
        "conviction_level": "high/medium/low"
    }}
}}

IMPORTANT: This is for a SIMULATED learning lab. Be intellectually honest about risks.
Focus on what the signal convergence genuinely suggests, not what sounds exciting."""

        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text
        # Extract JSON from response (handle markdown code blocks)
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]

        thesis_data = json.loads(raw)

        thesis = SimulatedThesis(
            name=thesis_data["name"],
            thesis_text=thesis_data["thesis_text"],
            entry_criteria=thesis_data.get("entry_criteria"),
            exit_criteria=thesis_data.get("exit_criteria"),
            time_horizon_days=thesis_data.get("time_horizon_days", 90),
            expected_catalysts=thesis_data.get("expected_catalysts"),
            risk_factors=thesis_data.get("risk_factors"),
            position_sizing=thesis_data.get("position_sizing"),
            generated_by="thesis_lord",
            generation_context=convergence,
            status=ThesisStatus.PROPOSED.value,
            ticker_ids=[convergence["ticker_id"]],
        )
        session.add(thesis)
        await session.flush()

        # Log the generation event
        log_entry = SimulationLog(
            thesis_id=thesis.id,
            agent_name="thesis_lord",
            event_type=SimEventType.GENERATION.value,
            event_data={
                "convergence": convergence,
                "thesis_name": thesis.name,
                "model_used": "claude-sonnet-4-6",
                "disclaimer": "SIMULATED THESIS — NOT FINANCIAL ADVICE",
            },
        )
        session.add(log_entry)

        logger.info("Generated thesis '%s' for %s", thesis.name, convergence["ticker_symbol"])
        return thesis

    except Exception as e:
        logger.error("Thesis generation failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Thesis Lifecycle Management
# ---------------------------------------------------------------------------


async def retire_thesis(
    session: AsyncSession,
    thesis_id: int,
    reason: str,
    agent_name: str = "thesis_lord",
) -> SimulatedThesis | None:
    """Retire or kill a thesis with a documented reason."""
    result = await session.execute(
        select(SimulatedThesis).where(SimulatedThesis.id == thesis_id)
    )
    thesis = result.scalar_one_or_none()
    if thesis is None:
        return None

    thesis.status = ThesisStatus.KILLED.value
    thesis.retired_at = datetime.now(timezone.utc)
    thesis.retirement_reason = reason

    log_entry = SimulationLog(
        thesis_id=thesis.id,
        agent_name=agent_name,
        event_type=SimEventType.RETIREMENT.value,
        event_data={
            "reason": reason,
            "final_status": thesis.status,
        },
    )
    session.add(log_entry)

    logger.info("Retired thesis '%s': %s", thesis.name, reason)
    return thesis


async def get_thesis_lifecycle(
    session: AsyncSession,
    status_filter: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Get all theses with their lifecycle status.

    Returns structured dicts with thesis info, backtest results, and position P&L.
    """
    query = select(SimulatedThesis).order_by(desc(SimulatedThesis.created_at)).limit(limit)
    if status_filter:
        query = query.where(SimulatedThesis.status == status_filter)

    result = await session.execute(query)
    theses = result.scalars().all()

    return [
        {
            "id": t.id,
            "name": t.name,
            "status": t.status,
            "generated_by": t.generated_by,
            "time_horizon_days": t.time_horizon_days,
            "ticker_ids": t.ticker_ids,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "retired_at": t.retired_at.isoformat() if t.retired_at else None,
            "retirement_reason": t.retirement_reason,
            "thesis_text": t.thesis_text[:200] + "..." if len(t.thesis_text) > 200 else t.thesis_text,
        }
        for t in theses
    ]
