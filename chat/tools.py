"""
EdgeFinder — Chat Tool Registry

Wraps existing data-fetching functions as Claude tool_use definitions.
Each tool has a JSON schema for Claude and an async execute function.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Coroutine

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict
    execute: Callable[..., Coroutine[Any, Any, dict]]
    personas: list[str] = field(default_factory=list)


def _json_safe(obj: Any) -> Any:
    """Convert non-JSON-safe types."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "__dict__") and hasattr(obj, "__tablename__"):
        # SQLAlchemy ORM object — extract column values
        return {
            c.key: _json_safe(getattr(obj, c.key))
            for c in obj.__class__.__table__.columns
        }
    if isinstance(obj, list):
        return [_json_safe(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def _exec_watchlist_movers(session: AsyncSession, params: dict) -> dict:
    from daily_briefing import _fetch_watchlist_movers
    days = params.get("days", 5)
    movers = await _fetch_watchlist_movers(session, days=days)
    return {"movers": _json_safe(movers), "count": len(movers)}


async def _exec_recent_alerts(session: AsyncSession, params: dict) -> dict:
    from daily_briefing import _fetch_recent_alerts
    hours = params.get("hours", 24)
    rows = await _fetch_recent_alerts(session, hours=hours)
    alerts = []
    for alert, symbol in rows:
        alerts.append({
            "symbol": symbol,
            "type": alert.alert_type,
            "severity": alert.severity,
            "title": alert.title,
            "body": alert.body,
            "score": float(alert.score) if alert.score else None,
            "created_at": _json_safe(alert.created_at),
        })
    return {"alerts": alerts, "count": len(alerts)}


async def _exec_top_news(session: AsyncSession, params: dict) -> dict:
    from daily_briefing import _fetch_top_news
    hours = params.get("hours", 24)
    limit = params.get("limit", 8)
    articles = await _fetch_top_news(session, hours=hours, limit=limit)
    news = []
    for art in articles:
        news.append({
            "title": art.title,
            "source": art.source_name,
            "sentiment_score": float(art.sentiment_score) if art.sentiment_score else None,
            "published_at": _json_safe(art.published_at),
        })
    return {"articles": news, "count": len(news)}


async def _exec_insider_buys(session: AsyncSession, params: dict) -> dict:
    from daily_briefing import _fetch_insider_buys
    days = params.get("days", 7)
    rows = await _fetch_insider_buys(session, days=days)
    buys = []
    for trade, symbol in rows:
        buys.append({
            "symbol": symbol,
            "insider_name": trade.insider_name,
            "insider_title": trade.insider_title,
            "total_amount": float(trade.total_amount) if trade.total_amount else None,
            "filed_date": _json_safe(trade.filed_date),
        })
    return {"buys": buys, "count": len(buys)}


async def _exec_technical_signals(session: AsyncSession, params: dict) -> dict:
    from daily_briefing import _fetch_technical_signals
    signals = await _fetch_technical_signals(session)
    return {"signals": signals, "count": len(signals)}


async def _exec_filing_drift(session: AsyncSession, params: dict) -> dict:
    from daily_briefing import _fetch_filing_drift
    rows = await _fetch_filing_drift(session)
    return {"drift": _json_safe(rows), "count": len(rows)}


async def _exec_thesis_matches(session: AsyncSession, params: dict) -> dict:
    from daily_briefing import _fetch_thesis_matches
    matches = await _fetch_thesis_matches(session)
    return {"matches": _json_safe(matches), "count": len(matches)}


async def _exec_dip_scores(session: AsyncSession, params: dict) -> dict:
    from daily_briefing import _fetch_dip_scores
    dips = await _fetch_dip_scores(session)
    return {"dip_scores": _json_safe(dips), "count": len(dips)}


async def _exec_full_briefing(session: AsyncSession, params: dict) -> dict:
    from daily_briefing import generate_briefing
    md = await generate_briefing(session)
    return {"briefing_markdown": md}


async def _exec_lookup_ticker(session: AsyncSession, params: dict) -> dict:
    from core.models import PriceBar, Ticker
    symbol = params.get("ticker", "").upper()
    result = await session.execute(select(Ticker).where(Ticker.symbol == symbol))
    ticker = result.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {symbol} not found"}

    data = {
        "ticker_id": ticker.id,
        "symbol": ticker.symbol,
        "name": ticker.name,
        "sector": ticker.sector,
        "industry": ticker.industry,
        "market_cap": float(ticker.market_cap) if ticker.market_cap else None,
        "in_watchlist": ticker.in_watchlist,
        "thesis_tags": ticker.thesis_tags,
    }

    # Latest price
    price_result = await session.execute(
        select(PriceBar.close, PriceBar.volume, PriceBar.date)
        .where(PriceBar.ticker_id == ticker.id)
        .order_by(desc(PriceBar.date))
        .limit(1)
    )
    bar = price_result.one_or_none()
    if bar:
        data["latest_price"] = float(bar.close)
        data["latest_volume"] = int(bar.volume) if bar.volume else None
        data["latest_date"] = bar.date.isoformat()

    return data


async def _exec_lookup_filing(session: AsyncSession, params: dict) -> dict:
    from core.models import Filing, FilingAnalysis, Ticker
    symbol = params.get("ticker", "").upper()
    result = await session.execute(select(Ticker).where(Ticker.symbol == symbol))
    ticker = result.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {symbol} not found"}

    fa_result = await session.execute(
        select(FilingAnalysis, Filing.filing_type, Filing.filed_date, Filing.period_of_report)
        .join(Filing, FilingAnalysis.filing_id == Filing.id)
        .where(Filing.ticker_id == ticker.id)
        .order_by(desc(Filing.filed_date))
        .limit(1)
    )
    row = fa_result.one_or_none()
    if not row:
        return {"error": f"No analyzed filings for {symbol}"}

    analysis, filing_type, filed_date, period = row
    return {
        "symbol": symbol,
        "filing_type": filing_type,
        "filed_date": _json_safe(filed_date),
        "period": _json_safe(period),
        "health_score": analysis.health_score,
        "red_flags": analysis.red_flags,
        "summary": analysis.summary,
        "bull_points": analysis.bull_points,
        "bear_points": analysis.bear_points,
        "financial_metrics": _json_safe(analysis.financial_metrics),
        "model_used": analysis.model_used,
    }


async def _exec_sentiment_summary(session: AsyncSession, params: dict) -> dict:
    from analysis.sentiment import compute_sentiment_summary
    from core.models import Ticker
    symbol = params.get("ticker", "").upper()
    result = await session.execute(select(Ticker).where(Ticker.symbol == symbol))
    ticker = result.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {symbol} not found"}

    summary = await compute_sentiment_summary(session, ticker.id)
    return {
        "symbol": symbol,
        "ma_3d": summary.ma_3d,
        "ma_7d": summary.ma_7d,
        "ma_30d": summary.ma_30d,
        "article_count": summary.article_count,
        "divergence_signal": summary.divergence_signal,
    }


async def _exec_search_tickers(session: AsyncSession, params: dict) -> dict:
    from core.models import Ticker
    query = params.get("query", "")
    watchlist_only = params.get("watchlist_only", False)

    stmt = select(Ticker).where(Ticker.is_active.is_(True))
    if watchlist_only:
        stmt = stmt.where(Ticker.in_watchlist.is_(True))
    if query:
        stmt = stmt.where(
            (Ticker.symbol.ilike(f"%{query}%"))
            | (Ticker.name.ilike(f"%{query}%"))
            | (Ticker.sector.ilike(f"%{query}%"))
        )
    stmt = stmt.order_by(Ticker.symbol).limit(20)

    result = await session.execute(stmt)
    tickers = result.scalars().all()
    return {
        "tickers": [
            {
                "symbol": t.symbol,
                "name": t.name,
                "sector": t.sector,
                "in_watchlist": t.in_watchlist,
            }
            for t in tickers
        ],
        "count": len(tickers),
    }


async def _exec_capture_feature(session: AsyncSession, params: dict) -> dict:
    from chat.feature_capture import save_feature_request
    fr = await save_feature_request(
        session,
        title=params.get("title", ""),
        user_story=params.get("user_story"),
        acceptance_criteria=params.get("acceptance_criteria"),
        priority=params.get("priority", "medium"),
        conversation_id=params.get("_conversation_id"),
    )
    return {
        "id": fr.id,
        "title": fr.title,
        "status": fr.status,
        "message": "Feature request captured successfully.",
    }


async def _exec_list_features(session: AsyncSession, params: dict) -> dict:
    from core.models import FeatureRequest
    status = params.get("status")
    stmt = select(FeatureRequest).order_by(desc(FeatureRequest.created_at)).limit(20)
    if status:
        stmt = stmt.where(FeatureRequest.status == status)
    result = await session.execute(stmt)
    features = result.scalars().all()
    return {
        "features": [
            {
                "id": f.id,
                "title": f.title,
                "user_story": f.user_story,
                "priority": f.priority,
                "status": f.status,
                "created_at": _json_safe(f.created_at),
            }
            for f in features
        ],
        "count": len(features),
    }


async def _exec_list_capabilities(session: AsyncSession, params: dict) -> dict:
    return {
        "capabilities": [
            "10-K/10-Q filing analysis with Claude (health scores, red flags, bull/bear points)",
            "Price data from yfinance with technical indicators (RSI, SMA 50/200, Bollinger, ATR, volume ratio)",
            "News aggregation from RSS with Claude Haiku sentiment scoring (-1 to +1)",
            "8-dimension buy-the-dip composite scoring (price drop, fundamentals, technicals, sentiment, insider, sector relative)",
            "Alert engine with 9 rules (RSI oversold, golden/death cross, volume spike, dip, dip+insider, filing red flag, earnings beat/miss)",
            "Investment thesis matching from theses.yaml (financial criteria + keyword density)",
            "FRED macroeconomic indicators (Fed funds rate, 10Y/2Y yields, yield curve, unemployment, CPI)",
            "Earnings call transcript analysis with Claude (management tone, forward guidance, key topics, bull/bear signals)",
            "Multi-quarter earnings sentiment trajectory tracking",
            "Earnings surprise alerts (EPS beat/miss thresholds)",
            "Daily/weekly briefing generation with macro + earnings sections",
            "11 watchlist tickers with full data: NVDA, AAPL, MSFT, GOOGL, META, AMZN, PLTR, VST, CEG, RKLB, SMR",
            "Institutional holdings with CUSIP-based matching (OpenFIGI + rapidfuzz)",
            "Web dashboard at localhost:8050 with dark theme",
            "Chat with 3 personas: Analyst, Thesis Genius, Product Manager",
        ],
    }


async def _exec_macro_indicators(session: AsyncSession, params: dict) -> dict:
    from ingestion.macro_data import get_latest_macro, get_macro_trend
    latest = await get_latest_macro(session)
    # Optionally get trend for a specific series
    series = params.get("series_id")
    trend = None
    if series:
        trend = await get_macro_trend(session, series, days=params.get("days", 30))
    result = {"indicators": latest, "count": len(latest)}
    if trend is not None:
        result["trend"] = trend
    return result


async def _exec_earnings_calendar(session: AsyncSession, params: dict) -> dict:
    from core.models import EarningsEventDB, Ticker
    from datetime import timedelta
    symbol = params.get("ticker", "").upper()
    days_back = params.get("days_back", 90)
    days_ahead = params.get("days_ahead", 30)

    cutoff_past = date.today() - timedelta(days=days_back)
    cutoff_future = date.today() + timedelta(days=days_ahead)

    stmt = (
        select(EarningsEventDB, Ticker.symbol)
        .join(Ticker, EarningsEventDB.ticker_id == Ticker.id)
        .where(EarningsEventDB.event_date.between(cutoff_past, cutoff_future))
    )
    if symbol:
        stmt = stmt.where(Ticker.symbol == symbol)
    stmt = stmt.order_by(desc(EarningsEventDB.event_date)).limit(20)

    result = await session.execute(stmt)
    rows = result.all()
    events = []
    for ev, sym in rows:
        events.append({
            "symbol": sym,
            "event_date": _json_safe(ev.event_date),
            "hour": ev.hour,
            "eps_estimate": ev.eps_estimate,
            "eps_actual": ev.eps_actual,
            "revenue_estimate": ev.revenue_estimate,
            "revenue_actual": ev.revenue_actual,
            "eps_surprise_pct": ev.eps_surprise_pct,
            "rev_surprise_pct": ev.rev_surprise_pct,
        })
    return {"events": events, "count": len(events)}


async def _exec_earnings_analysis(session: AsyncSession, params: dict) -> dict:
    from core.models import EarningsAnalysis, EarningsTranscript, Ticker
    symbol = params.get("ticker", "").upper()
    result = await session.execute(select(Ticker).where(Ticker.symbol == symbol))
    ticker = result.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {symbol} not found"}

    # Get latest transcript with analysis
    row = await session.execute(
        select(EarningsAnalysis, EarningsTranscript.quarter, EarningsTranscript.fiscal_year)
        .join(EarningsTranscript, EarningsAnalysis.transcript_id == EarningsTranscript.id)
        .where(EarningsTranscript.ticker_id == ticker.id)
        .order_by(desc(EarningsTranscript.fiscal_year), desc(EarningsTranscript.quarter))
        .limit(1)
    )
    analysis_row = row.one_or_none()
    if not analysis_row:
        return {"error": f"No earnings analysis available for {symbol}"}

    analysis, quarter, fiscal_year = analysis_row
    return {
        "symbol": symbol,
        "quarter": quarter,
        "fiscal_year": fiscal_year,
        "overall_sentiment": analysis.overall_sentiment,
        "management_tone": analysis.management_tone,
        "forward_guidance_sentiment": analysis.forward_guidance_sentiment,
        "key_topics": analysis.key_topics,
        "analyst_concerns": analysis.analyst_concerns,
        "management_quotes": analysis.management_quotes,
        "summary": analysis.summary,
        "bull_signals": analysis.bull_signals,
        "bear_signals": analysis.bear_signals,
        "tone_vs_prior": analysis.tone_vs_prior,
        "analyzed_at": _json_safe(analysis.analyzed_at),
    }


async def _exec_earnings_sentiment_trend(session: AsyncSession, params: dict) -> dict:
    from core.models import EarningsAnalysis, EarningsTranscript, Ticker
    symbol = params.get("ticker", "").upper()
    quarters = params.get("quarters", 4)
    result = await session.execute(select(Ticker).where(Ticker.symbol == symbol))
    ticker = result.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {symbol} not found"}

    rows = await session.execute(
        select(EarningsAnalysis, EarningsTranscript.quarter, EarningsTranscript.fiscal_year)
        .join(EarningsTranscript, EarningsAnalysis.transcript_id == EarningsTranscript.id)
        .where(EarningsTranscript.ticker_id == ticker.id)
        .order_by(desc(EarningsTranscript.fiscal_year), desc(EarningsTranscript.quarter))
        .limit(quarters)
    )
    trend = []
    for analysis, q, fy in rows.all():
        trend.append({
            "quarter": f"Q{q} FY{fy}",
            "overall_sentiment": analysis.overall_sentiment,
            "management_tone": analysis.management_tone,
            "forward_guidance_sentiment": analysis.forward_guidance_sentiment,
            "tone_vs_prior": analysis.tone_vs_prior,
        })
    trend.reverse()  # oldest first for trajectory
    return {"symbol": symbol, "trend": trend, "quarters": len(trend)}


async def _exec_suggest_handoff(session: AsyncSession, params: dict) -> dict:
    return {
        "handoff_suggested": True,
        "target_persona": params.get("target_persona", "analyst"),
        "reason": params.get("reason", ""),
    }


# ---------------------------------------------------------------------------
# Simulation Engine Tool Implementations
# ---------------------------------------------------------------------------


async def _exec_get_paper_portfolio(session: AsyncSession, params: dict) -> dict:
    from simulation.paper_portfolio import get_or_create_portfolio, portfolio_summary
    portfolio = await get_or_create_portfolio(session)
    return await portfolio_summary(session, portfolio)


async def _exec_propose_thesis(session: AsyncSession, params: dict) -> dict:
    from config.settings import settings
    from simulation.thesis_generator import detect_signal_convergence, generate_thesis
    if not settings.has_anthropic:
        return {"error": "ANTHROPIC_API_KEY not configured"}
    convergences = await detect_signal_convergence(session)
    if not convergences:
        return {"message": "No signal convergences detected in current watchlist data.", "convergences": 0}
    top = convergences[0]
    thesis = await generate_thesis(session, top, settings.anthropic_api_key)
    if thesis:
        await session.commit()
        return {
            "thesis_id": thesis.id,
            "name": thesis.name,
            "thesis_text": thesis.thesis_text,
            "status": thesis.status,
            "generated_for": top["ticker_symbol"],
            "signals": top["signals"],
            "disclaimer": "SIMULATED PLAY-MONEY THESIS — NOT FINANCIAL ADVICE",
        }
    return {"error": "Thesis generation failed — check logs"}


async def _exec_trigger_backtest(session: AsyncSession, params: dict) -> dict:
    from scheduler.tasks import task_backtest_thesis
    thesis_id = params.get("thesis_id")
    ticker_id = params.get("ticker_id")
    if not thesis_id or not ticker_id:
        return {"error": "thesis_id and ticker_id are required"}
    result = task_backtest_thesis.apply_async(args=[thesis_id, ticker_id])
    return {
        "task_id": result.id,
        "status": "queued",
        "message": f"Backtest enqueued for thesis {thesis_id} on ticker {ticker_id}",
        "check_status": f"task_id={result.id}",
    }


async def _exec_get_thesis_lifecycle(session: AsyncSession, params: dict) -> dict:
    from simulation.thesis_generator import get_thesis_lifecycle
    status_filter = params.get("status")
    limit = min(params.get("limit", 20), 50)
    theses = await get_thesis_lifecycle(session, status_filter=status_filter, limit=limit)
    return {"theses": theses, "count": len(theses), "status_filter": status_filter}


async def _exec_get_simulation_log(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import desc, select
    from core.models import SimulationLog
    thesis_id = params.get("thesis_id")
    event_type = params.get("event_type")
    limit = min(params.get("limit", 30), 100)
    query = select(SimulationLog).order_by(desc(SimulationLog.created_at)).limit(limit)
    if thesis_id:
        query = query.where(SimulationLog.thesis_id == thesis_id)
    if event_type:
        query = query.where(SimulationLog.event_type == event_type)
    result = await session.execute(query)
    entries = result.scalars().all()
    return {
        "entries": [
            {
                "id": e.id, "thesis_id": e.thesis_id, "agent_name": e.agent_name,
                "event_type": e.event_type, "event_data": e.event_data,
                "created_at": _json_safe(e.created_at),
            } for e in entries
        ],
        "count": len(entries),
    }


async def _exec_mutate_thesis(session: AsyncSession, params: dict) -> dict:
    from datetime import datetime, timezone
    from sqlalchemy import select
    from core.models import SimulatedThesis, SimEventType, SimulationLog
    thesis_id = params.get("thesis_id")
    changes = params.get("changes", {})
    reason = params.get("reason", "Manual mutation")
    if not thesis_id:
        return {"error": "thesis_id required"}
    result = await session.execute(select(SimulatedThesis).where(SimulatedThesis.id == thesis_id))
    thesis = result.scalar_one_or_none()
    if not thesis:
        return {"error": f"Thesis {thesis_id} not found"}
    if "entry_criteria" in changes:
        thesis.entry_criteria = changes["entry_criteria"]
    if "exit_criteria" in changes:
        thesis.exit_criteria = changes["exit_criteria"]
    if "time_horizon_days" in changes:
        thesis.time_horizon_days = changes["time_horizon_days"]
    if "risk_factors" in changes:
        thesis.risk_factors = changes["risk_factors"]
    log = SimulationLog(
        thesis_id=thesis.id, agent_name="thesis_lord",
        event_type=SimEventType.MUTATION.value,
        event_data={"reason": reason, "changes": list(changes.keys())},
    )
    session.add(log)
    await session.commit()
    return {"thesis_id": thesis.id, "name": thesis.name, "changes_applied": list(changes.keys()), "reason": reason}


async def _exec_retire_thesis(session: AsyncSession, params: dict) -> dict:
    from simulation.thesis_generator import retire_thesis
    thesis_id = params.get("thesis_id")
    reason = params.get("reason", "Manually retired")
    if not thesis_id:
        return {"error": "thesis_id required"}
    thesis = await retire_thesis(session, thesis_id, reason, agent_name="thesis_lord")
    if thesis:
        await session.commit()
        return {"thesis_id": thesis.id, "name": thesis.name, "status": thesis.status, "reason": reason}
    return {"error": f"Thesis {thesis_id} not found"}


async def _exec_get_performance_attribution(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import func, select
    from core.models import PaperPosition, SimulatedThesis, Ticker
    result = await session.execute(
        select(
            SimulatedThesis.name,
            func.count(PaperPosition.id).label("position_count"),
            func.sum(PaperPosition.pnl).label("total_pnl"),
            func.avg(PaperPosition.pnl_pct).label("avg_pnl_pct"),
        )
        .join(SimulatedThesis, PaperPosition.thesis_id == SimulatedThesis.id)
        .group_by(SimulatedThesis.name)
        .order_by(func.sum(PaperPosition.pnl).desc().nullslast())
    )
    rows = result.all()
    attribution = [
        {
            "thesis_name": row.name,
            "position_count": row.position_count,
            "total_pnl": float(row.total_pnl or 0),
            "avg_pnl_pct": float(row.avg_pnl_pct or 0),
        }
        for row in rows
    ]
    return {"attribution": attribution, "disclaimer": "SIMULATED PLAY-MONEY P&L"}


async def _exec_get_vol_surface(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import desc, select
    from core.models import Ticker, VolSurface
    ticker_sym = params.get("ticker", "").upper()
    ticker_r = await session.execute(select(Ticker).where(Ticker.symbol == ticker_sym))
    ticker = ticker_r.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {ticker_sym} not found"}
    result = await session.execute(
        select(VolSurface).where(VolSurface.ticker_id == ticker.id)
        .order_by(desc(VolSurface.as_of)).limit(1)
    )
    surface = result.scalar_one_or_none()
    if not surface:
        return {"message": f"No vol surface data for {ticker_sym}. Run options ingestion + calibration first.", "ticker": ticker_sym}
    return {
        "ticker": ticker_sym, "as_of": _json_safe(surface.as_of),
        "model_type": surface.model_type, "calibration_error": surface.calibration_error,
        "surface_data": surface.surface_data,
    }


async def _exec_get_options_chain_data(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import desc, select
    from core.models import OptionsChain, Ticker
    ticker_sym = params.get("ticker", "").upper()
    limit = min(params.get("limit", 50), 200)
    ticker_r = await session.execute(select(Ticker).where(Ticker.symbol == ticker_sym))
    ticker = ticker_r.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {ticker_sym} not found"}
    result = await session.execute(
        select(OptionsChain).where(OptionsChain.ticker_id == ticker.id)
        .order_by(desc(OptionsChain.fetched_at), OptionsChain.expiration, OptionsChain.strike)
        .limit(limit)
    )
    rows = result.scalars().all()
    if not rows:
        return {"message": f"No options chain data for {ticker_sym}. Run `make ingest-options` first.", "ticker": ticker_sym}
    return {
        "ticker": ticker_sym,
        "contracts": [
            {
                "expiration": _json_safe(r.expiration), "strike": float(r.strike),
                "call_put": r.call_put, "bid": r.bid, "ask": r.ask,
                "implied_vol": r.implied_vol, "delta": r.delta, "volume": r.volume,
                "open_interest": r.open_interest,
            } for r in rows
        ],
        "count": len(rows),
    }


async def _exec_compare_iv_rv(session: AsyncSession, params: dict) -> dict:
    import math
    from sqlalchemy import desc, select
    from core.models import PriceBar, Ticker, VolSurface
    ticker_sym = params.get("ticker", "").upper()
    lookback = params.get("lookback_days", 30)
    ticker_r = await session.execute(select(Ticker).where(Ticker.symbol == ticker_sym))
    ticker = ticker_r.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {ticker_sym} not found"}
    # Realized vol from price data
    price_result = await session.execute(
        select(PriceBar.adj_close, PriceBar.close)
        .where(PriceBar.ticker_id == ticker.id)
        .order_by(desc(PriceBar.date)).limit(lookback + 1)
    )
    bars = price_result.all()
    if len(bars) < 10:
        return {"error": "Insufficient price data for realized vol calculation"}
    prices = [float(b.adj_close or b.close) for b in reversed(bars)]
    import numpy as np
    log_returns = np.diff(np.log(prices))
    realized_vol = float(np.std(log_returns) * math.sqrt(252))
    # ATM IV from surface
    surface_result = await session.execute(
        select(VolSurface).where(VolSurface.ticker_id == ticker.id)
        .order_by(desc(VolSurface.as_of)).limit(1)
    )
    surface = surface_result.scalar_one_or_none()
    atm_iv = None
    if surface and surface.surface_data:
        atm_iv = surface.surface_data.get("atm_iv")
    return {
        "ticker": ticker_sym,
        "realized_vol_annualized": round(realized_vol, 4),
        "realized_vol_pct": f"{realized_vol * 100:.1f}%",
        "atm_implied_vol": atm_iv,
        "atm_iv_pct": f"{atm_iv * 100:.1f}%" if atm_iv else "No data",
        "iv_rv_spread": round(atm_iv - realized_vol, 4) if atm_iv else None,
        "interpretation": (
            f"IV > RV by {(atm_iv - realized_vol)*100:.1f}% — market is pricing in more uncertainty than realized"
            if atm_iv and atm_iv > realized_vol
            else f"IV < RV by {(realized_vol - atm_iv)*100:.1f}% — vol may be cheap relative to recent moves"
            if atm_iv else "No implied vol surface available"
        ),
        "lookback_days": lookback,
    }


async def _exec_explain_skew(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import desc, select
    from core.models import Ticker, VolSurface
    ticker_sym = params.get("ticker", "").upper()
    ticker_r = await session.execute(select(Ticker).where(Ticker.symbol == ticker_sym))
    ticker = ticker_r.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {ticker_sym} not found"}
    result = await session.execute(
        select(VolSurface).where(VolSurface.ticker_id == ticker.id)
        .order_by(desc(VolSurface.as_of)).limit(1)
    )
    surface = result.scalar_one_or_none()
    if not surface or not surface.surface_data:
        return {"message": f"No vol surface data for {ticker_sym}"}
    sd = surface.surface_data
    skew = sd.get("skew_25d")
    atm_iv = sd.get("atm_iv")
    if skew is None:
        return {"message": "Skew data not available in surface", "ticker": ticker_sym}
    interpretation = ""
    if skew > 0.03:
        interpretation = f"Steep put skew ({skew*100:.1f}%). Market is paying a significant premium for downside protection. Crash fear or event risk is elevated. Institutions hedging long equity exposure."
    elif skew > 0.01:
        interpretation = f"Moderate put skew ({skew*100:.1f}%). Normal risk premium for tail hedging. Typical regime."
    elif skew < -0.01:
        interpretation = f"Call skew ({abs(skew)*100:.1f}%). Unusual — market is paying MORE for upside than downside. Possible short-squeeze positioning or takeover speculation."
    else:
        interpretation = f"Skew is flat ({skew*100:.1f}%). Market sees symmetric risk in both directions."
    return {
        "ticker": ticker_sym,
        "atm_iv": atm_iv,
        "skew_25d": skew,
        "interpretation": interpretation,
        "as_of": _json_safe(surface.as_of),
    }


async def _exec_get_heston_params(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import desc, select
    from core.models import HestonCalibration, Ticker
    ticker_sym = params.get("ticker", "").upper()
    ticker_r = await session.execute(select(Ticker).where(Ticker.symbol == ticker_sym))
    ticker = ticker_r.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {ticker_sym} not found"}
    result = await session.execute(
        select(HestonCalibration).where(HestonCalibration.ticker_id == ticker.id)
        .order_by(desc(HestonCalibration.as_of)).limit(1)
    )
    cal = result.scalar_one_or_none()
    if not cal:
        return {"message": f"No Heston calibration for {ticker_sym}. Options data needed first.", "ticker": ticker_sym}
    feller = 2 * cal.kappa * cal.theta > cal.sigma_v ** 2
    return {
        "ticker": ticker_sym, "as_of": _json_safe(cal.as_of),
        "v0": cal.v0, "kappa": cal.kappa, "theta": cal.theta,
        "sigma_v": cal.sigma_v, "rho": cal.rho,
        "calibration_error_rmse": cal.calibration_error,
        "feller_condition": "satisfied" if feller else "violated (QE scheme handles this)",
        "interpretation": {
            "current_vol": f"{(cal.v0 ** 0.5) * 100:.1f}%",
            "long_run_vol": f"{(cal.theta ** 0.5) * 100:.1f}%",
            "mean_reversion_speed": f"κ={cal.kappa:.2f} — {'fast' if cal.kappa > 3 else 'moderate' if cal.kappa > 1.5 else 'slow'} mean reversion",
            "leverage_effect": f"ρ={cal.rho:.3f} — {'strong' if cal.rho < -0.5 else 'moderate' if cal.rho < -0.3 else 'weak'} negative correlation (leverage effect)",
        },
    }


async def _exec_price_option_heston(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import desc, select
    from core.models import HestonCalibration, Ticker
    from simulation.heston import HestonParams, heston_call_price, heston_implied_vol
    from simulation.black_scholes import bs_call_price
    ticker_sym = params.get("ticker", "").upper()
    strike = params.get("strike")
    expiry_years = params.get("expiry_years")
    risk_free_rate = params.get("risk_free_rate", 0.05)
    if not all([ticker_sym, strike, expiry_years]):
        return {"error": "ticker, strike, and expiry_years are required"}
    ticker_r = await session.execute(select(Ticker).where(Ticker.symbol == ticker_sym))
    ticker = ticker_r.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {ticker_sym} not found"}
    # Get current price
    from sqlalchemy import desc as _desc
    from core.models import PriceBar
    pr = await session.execute(
        select(PriceBar.close).where(PriceBar.ticker_id == ticker.id)
        .order_by(_desc(PriceBar.date)).limit(1)
    )
    spot = pr.scalar_one_or_none()
    if not spot:
        return {"error": f"No price data for {ticker_sym}"}
    S = float(spot)
    # Get Heston params
    cal_r = await session.execute(
        select(HestonCalibration).where(HestonCalibration.ticker_id == ticker.id)
        .order_by(desc(HestonCalibration.as_of)).limit(1)
    )
    cal = cal_r.scalar_one_or_none()
    if not cal:
        return {"error": f"No Heston calibration for {ticker_sym}"}
    hp = HestonParams(v0=cal.v0, kappa=cal.kappa, theta=cal.theta, sigma_v=cal.sigma_v, rho=cal.rho)
    K, T, r = float(strike), float(expiry_years), float(risk_free_rate)
    heston_price = heston_call_price(S, K, T, r, hp)
    bsm_price = bs_call_price(S, K, T, r, (cal.v0 ** 0.5))
    heston_iv = heston_implied_vol(S, K, T, r, hp)
    return {
        "ticker": ticker_sym, "spot": S, "strike": K, "expiry_years": T,
        "heston_call_price": round(heston_price, 4),
        "bsm_call_price": round(bsm_price, 4),
        "heston_implied_vol": round(heston_iv * 100, 2) if heston_iv else None,
        "price_difference": round(heston_price - bsm_price, 4),
        "note": "All prices are theoretical/simulated. Not financial advice.",
    }


async def _exec_calibrate_heston_now(session: AsyncSession, params: dict) -> dict:
    from scheduler.tasks import task_calibrate_heston_batch
    ticker_sym = params.get("ticker", "").upper()
    result = task_calibrate_heston_batch.apply_async()
    return {
        "task_id": result.id, "status": "queued",
        "message": f"Heston calibration batch enqueued. Will process all watchlist tickers with options data.",
        "note": "Results available via get_heston_params after completion (~2-5 min)",
    }


async def _exec_generate_mc_paths(session: AsyncSession, params: dict) -> dict:
    import math
    import numpy as np
    from sqlalchemy import desc, select
    from core.models import HestonCalibration, PriceBar, Ticker
    from simulation.heston import HestonParams, generate_heston_paths
    ticker_sym = params.get("ticker", "").upper()
    horizon_years = float(params.get("horizon_years", 1.0))
    n_paths = min(int(params.get("n_paths", 1000)), 5000)
    ticker_r = await session.execute(select(Ticker).where(Ticker.symbol == ticker_sym))
    ticker = ticker_r.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {ticker_sym} not found"}
    pr = await session.execute(
        select(PriceBar.close).where(PriceBar.ticker_id == ticker.id)
        .order_by(desc(PriceBar.date)).limit(1)
    )
    spot = pr.scalar_one_or_none()
    if not spot:
        return {"error": f"No price data for {ticker_sym}"}
    cal_r = await session.execute(
        select(HestonCalibration).where(HestonCalibration.ticker_id == ticker.id)
        .order_by(desc(HestonCalibration.as_of)).limit(1)
    )
    cal = cal_r.scalar_one_or_none()
    if not cal:
        return {"error": f"No Heston calibration for {ticker_sym}. Options data needed first."}
    hp = HestonParams(v0=cal.v0, kappa=cal.kappa, theta=cal.theta, sigma_v=cal.sigma_v, rho=cal.rho)
    S, r = float(spot), 0.05
    S_paths, _ = generate_heston_paths(S, horizon_years, r, hp, n_paths=n_paths, n_steps=252, seed=42)
    terminal = S_paths[:, -1]
    pct5, pct25, pct50, pct75, pct95 = np.percentile(terminal, [5, 25, 50, 75, 95])
    expected = float(np.mean(terminal))
    prob_up = float(np.mean(terminal > S))
    return {
        "ticker": ticker_sym, "spot": S, "horizon_years": horizon_years, "n_paths": n_paths,
        "terminal_distribution": {
            "p5": round(float(pct5), 2), "p25": round(float(pct25), 2),
            "p50": round(float(pct50), 2), "p75": round(float(pct75), 2),
            "p95": round(float(pct95), 2), "mean": round(expected, 2),
        },
        "prob_above_spot": f"{prob_up*100:.1f}%",
        "expected_return": f"{((expected/S)-1)*100:.1f}%",
        "note": "Monte Carlo under Heston stochastic vol. Simulated only — not financial advice.",
    }


async def _exec_get_calibration_history(session: AsyncSession, params: dict) -> dict:
    from datetime import date, timedelta
    from sqlalchemy import select
    from core.models import HestonCalibration, Ticker
    ticker_sym = params.get("ticker", "").upper()
    days = min(params.get("days", 30), 90)
    ticker_r = await session.execute(select(Ticker).where(Ticker.symbol == ticker_sym))
    ticker = ticker_r.scalar_one_or_none()
    if not ticker:
        return {"error": f"Ticker {ticker_sym} not found"}
    since = date.today() - timedelta(days=days)
    result = await session.execute(
        select(HestonCalibration).where(
            HestonCalibration.ticker_id == ticker.id,
            HestonCalibration.as_of >= since,
        ).order_by(HestonCalibration.as_of)
    )
    cals = result.scalars().all()
    return {
        "ticker": ticker_sym, "days": days,
        "calibrations": [
            {
                "as_of": _json_safe(c.as_of), "v0": c.v0, "kappa": c.kappa,
                "theta": c.theta, "sigma_v": c.sigma_v, "rho": c.rho,
                "rmse": c.calibration_error,
            } for c in cals
        ],
        "count": len(cals),
    }


async def _exec_get_hedging_status(session: AsyncSession, params: dict) -> dict:
    from simulation.deep_hedging import get_hedging_status
    return get_hedging_status()


async def _exec_explain_hedging_concept(session: AsyncSession, params: dict) -> dict:
    from simulation.deep_hedging import explain_hedging_concept
    concept = params.get("concept", "deep_hedging")
    return explain_hedging_concept(concept)


async def _exec_get_retired_theses(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import desc, select
    from core.models import SimulatedThesis, ThesisStatus
    result = await session.execute(
        select(SimulatedThesis)
        .where(SimulatedThesis.status.in_([ThesisStatus.RETIRED.value, ThesisStatus.KILLED.value]))
        .order_by(desc(SimulatedThesis.retired_at))
        .limit(20)
    )
    theses = result.scalars().all()
    return {
        "retired_theses": [
            {
                "id": t.id, "name": t.name, "status": t.status,
                "thesis_text": t.thesis_text[:300] + "..." if len(t.thesis_text) > 300 else t.thesis_text,
                "retirement_reason": t.retirement_reason,
                "retired_at": _json_safe(t.retired_at),
            } for t in theses
        ],
        "count": len(theses),
    }


async def _exec_write_post_mortem(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import desc, select
    from core.models import BacktestRun, SimulatedThesis, SimulationLog
    from config.settings import settings
    thesis_id = params.get("thesis_id")
    if not thesis_id:
        return {"error": "thesis_id required"}
    if not settings.has_anthropic:
        return {"error": "ANTHROPIC_API_KEY not configured"}
    thesis_r = await session.execute(select(SimulatedThesis).where(SimulatedThesis.id == thesis_id))
    thesis = thesis_r.scalar_one_or_none()
    if not thesis:
        return {"error": f"Thesis {thesis_id} not found"}
    # Gather context
    log_r = await session.execute(
        select(SimulationLog).where(SimulationLog.thesis_id == thesis_id)
        .order_by(SimulationLog.created_at).limit(30)
    )
    logs = log_r.scalars().all()
    bt_r = await session.execute(
        select(BacktestRun).where(BacktestRun.thesis_id == thesis_id)
        .order_by(desc(BacktestRun.ran_at)).limit(1)
    )
    backtest = bt_r.scalar_one_or_none()
    import anthropic, json as _json
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    context_str = f"""Thesis: {thesis.name}
Status: {thesis.status}
Retirement reason: {thesis.retirement_reason or 'Not specified'}

Thesis text: {thesis.thesis_text[:500]}

Backtest results: {_json.dumps({"sharpe": backtest.sharpe, "max_drawdown": backtest.max_drawdown, "win_rate": backtest.win_rate, "p_value": backtest.monte_carlo_p_value}, default=str) if backtest else 'No backtest run'}

Decision log ({len(logs)} events):
{chr(10).join(f"- [{e.event_type}] {e.agent_name}: {str(e.event_data)[:100]}" for e in logs[:10])}"""
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": f"Write a concise 3-paragraph post-mortem for this investment thesis. Be forensically honest. Lead with what failed and why, then extract the durable lesson.\n\n{context_str}"}],
    )
    return {
        "thesis_id": thesis_id, "thesis_name": thesis.name,
        "post_mortem": response.content[0].text,
        "backtest_summary": {"sharpe": backtest.sharpe, "max_drawdown": backtest.max_drawdown} if backtest else None,
    }


async def _exec_get_agent_memories(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import desc, select
    from core.models import AgentMemory
    agent_name = params.get("agent_name")
    memory_type = params.get("memory_type")
    limit = min(params.get("limit", 10), 30)
    query = select(AgentMemory).order_by(desc(AgentMemory.confidence)).limit(limit)
    if agent_name:
        query = query.where(AgentMemory.agent_name == agent_name)
    if memory_type:
        query = query.where(AgentMemory.memory_type == memory_type)
    result = await session.execute(query)
    memories = result.scalars().all()
    return {
        "memories": [
            {
                "id": m.id, "agent_name": m.agent_name, "memory_type": m.memory_type,
                "content": m.content, "confidence": m.confidence,
                "access_count": m.access_count, "created_at": _json_safe(m.created_at),
            } for m in memories
        ],
        "count": len(memories),
    }


async def _exec_search_decision_log(session: AsyncSession, params: dict) -> dict:
    from sqlalchemy import cast, select, String
    from core.models import SimulationLog
    query_str = params.get("query", "").strip()
    limit = min(params.get("limit", 20), 50)
    if not query_str:
        return {"error": "query parameter required"}
    result = await session.execute(
        select(SimulationLog)
        .where(cast(SimulationLog.event_data, String).ilike(f"%{query_str}%"))
        .order_by(SimulationLog.created_at.desc())
        .limit(limit)
    )
    entries = result.scalars().all()
    return {
        "query": query_str,
        "entries": [
            {
                "id": e.id, "thesis_id": e.thesis_id, "agent_name": e.agent_name,
                "event_type": e.event_type, "event_data": e.event_data,
                "created_at": _json_safe(e.created_at),
            } for e in entries
        ],
        "count": len(entries),
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


TOOL_REGISTRY: dict[str, ToolDef] = {
    "get_watchlist_movers": ToolDef(
        name="get_watchlist_movers",
        description="Get top gainers and losers among watchlist tickers over the last N days.",
        input_schema={
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Lookback period in days", "default": 5}},
        },
        execute=_exec_watchlist_movers,
        personas=["analyst", "thesis"],
    ),
    "get_recent_alerts": ToolDef(
        name="get_recent_alerts",
        description="Get recent alerts (RSI oversold, golden/death cross, dip signals, filing red flags) from the last N hours.",
        input_schema={
            "type": "object",
            "properties": {"hours": {"type": "integer", "description": "Lookback in hours", "default": 24}},
        },
        execute=_exec_recent_alerts,
        personas=["analyst", "thesis"],
    ),
    "get_top_news": ToolDef(
        name="get_top_news",
        description="Get top news articles sorted by absolute sentiment score.",
        input_schema={
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "default": 24},
                "limit": {"type": "integer", "default": 8},
            },
        },
        execute=_exec_top_news,
        personas=["analyst", "thesis"],
    ),
    "get_insider_buys": ToolDef(
        name="get_insider_buys",
        description="Get recent Form 4 insider buy transactions.",
        input_schema={
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 7}},
        },
        execute=_exec_insider_buys,
        personas=["analyst"],
    ),
    "get_technical_signals": ToolDef(
        name="get_technical_signals",
        description="Get current technical signals: RSI extremes (oversold/overbought) and SMA golden/death crosses for watchlist tickers.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_technical_signals,
        personas=["analyst", "thesis"],
    ),
    "get_filing_drift": ToolDef(
        name="get_filing_drift",
        description="Get year-over-year 10-K health score drift for all watchlist tickers. Shows health score changes, red flag counts, margin changes, and revenue growth.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_filing_drift,
        personas=["analyst"],
    ),
    "get_thesis_matches": ToolDef(
        name="get_thesis_matches",
        description="Get tickers that match investment theses, with financial and keyword scores.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_thesis_matches,
        personas=["analyst", "thesis"],
    ),
    "get_dip_scores": ToolDef(
        name="get_dip_scores",
        description="Get buy-the-dip composite scores with 8 dimension breakdown (price drop, fundamentals, technicals, sentiment, insider, sector relative).",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_dip_scores,
        personas=["analyst", "thesis"],
    ),
    "generate_full_briefing": ToolDef(
        name="generate_full_briefing",
        description="Generate the complete daily briefing in markdown with all 10 sections.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_full_briefing,
        personas=["analyst"],
    ),
    "lookup_ticker": ToolDef(
        name="lookup_ticker",
        description="Look up detailed info for a specific ticker: name, sector, market cap, latest price, watchlist status.",
        input_schema={
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Ticker symbol (e.g. NVDA)"}},
            "required": ["ticker"],
        },
        execute=_exec_lookup_ticker,
        personas=["analyst", "thesis"],
    ),
    "lookup_filing_analysis": ToolDef(
        name="lookup_filing_analysis",
        description="Get the latest filing analysis for a ticker: health score, red flags, Claude summary, bull/bear points, financial metrics.",
        input_schema={
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Ticker symbol"}},
            "required": ["ticker"],
        },
        execute=_exec_lookup_filing,
        personas=["analyst"],
    ),
    "get_sentiment_summary": ToolDef(
        name="get_sentiment_summary",
        description="Get rolling 3/7/30-day sentiment moving averages for a ticker, plus divergence detection.",
        input_schema={
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Ticker symbol"}},
            "required": ["ticker"],
        },
        execute=_exec_sentiment_summary,
        personas=["analyst"],
    ),
    "search_tickers": ToolDef(
        name="search_tickers",
        description="Search tickers by symbol, name, or sector. Optionally filter to watchlist only.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
                "watchlist_only": {"type": "boolean", "default": False},
            },
        },
        execute=_exec_search_tickers,
        personas=["analyst", "thesis"],
    ),
    "capture_feature_request": ToolDef(
        name="capture_feature_request",
        description="Capture a feature request with title, user story, acceptance criteria, and priority. Use this after discussing the feature with the user.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short feature title"},
                "user_story": {"type": "string", "description": "As a [user], I want [X] so that [Y]"},
                "acceptance_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of acceptance criteria",
                },
                "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"], "default": "medium"},
            },
            "required": ["title"],
        },
        execute=_exec_capture_feature,
        personas=["pm"],
    ),
    "list_feature_requests": ToolDef(
        name="list_feature_requests",
        description="List captured feature requests, optionally filtered by status.",
        input_schema={
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["captured", "reviewed", "planned", "built"]}},
        },
        execute=_exec_list_features,
        personas=["pm"],
    ),
    "list_available_capabilities": ToolDef(
        name="list_available_capabilities",
        description="List all current EdgeFinder platform capabilities. Use this to check if a feature already exists before capturing a new request.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_list_capabilities,
        personas=["pm"],
    ),
    "get_macro_indicators": ToolDef(
        name="get_macro_indicators",
        description="Get current macroeconomic indicators: Fed funds rate, 10Y/2Y Treasury yields, yield curve spread, unemployment, CPI. Optionally get 30-day trend for a specific series.",
        input_schema={
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "Specific FRED series to get trend for (FEDFUNDS, DGS10, DGS2, T10Y2Y, UNRATE, CPIAUCSL)"},
                "days": {"type": "integer", "description": "Days of trend history", "default": 30},
            },
        },
        execute=_exec_macro_indicators,
        personas=["analyst", "thesis"],
    ),
    "get_earnings_calendar": ToolDef(
        name="get_earnings_calendar",
        description="Get upcoming and recent earnings events with EPS/revenue estimates and actuals. Shows surprise percentages for past earnings.",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Filter to specific ticker symbol"},
                "days_back": {"type": "integer", "default": 90},
                "days_ahead": {"type": "integer", "default": 30},
            },
        },
        execute=_exec_earnings_calendar,
        personas=["analyst"],
    ),
    "get_earnings_analysis": ToolDef(
        name="get_earnings_analysis",
        description="Get Claude's deep analysis of a company's latest earnings call: management tone, sentiment, key topics, analyst concerns, bull/bear signals, and executive summary.",
        input_schema={
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Ticker symbol"}},
            "required": ["ticker"],
        },
        execute=_exec_earnings_analysis,
        personas=["analyst", "thesis"],
    ),
    "get_earnings_sentiment": ToolDef(
        name="get_earnings_sentiment",
        description="Get multi-quarter earnings sentiment trajectory for a ticker: overall sentiment, management tone, forward guidance, and tone shifts across recent quarters.",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol"},
                "quarters": {"type": "integer", "description": "Number of quarters to include", "default": 4},
            },
            "required": ["ticker"],
        },
        execute=_exec_earnings_sentiment_trend,
        personas=["analyst", "thesis"],
    ),
    "suggest_handoff": ToolDef(
        name="suggest_handoff",
        description="Suggest handing the conversation to a different persona. Use when the user's question would be better served by another persona.",
        input_schema={
            "type": "object",
            "properties": {
                "target_persona": {"type": "string", "enum": ["analyst", "thesis", "pm"]},
                "reason": {"type": "string", "description": "Brief explanation of why this handoff is suggested"},
            },
            "required": ["target_persona", "reason"],
        },
        execute=_exec_suggest_handoff,
        personas=["analyst", "thesis", "pm", "thesis_lord", "vol_slayer", "heston_cal", "deep_hedge", "post_mortem"],
    ),
    # ─── Simulation Engine Tools ───────────────────────────────────────────
    "get_paper_portfolio": ToolDef(
        name="get_paper_portfolio",
        description="Get the current paper portfolio state — open positions, P&L attribution by thesis, and portfolio-level metrics. All play-money.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_get_paper_portfolio,
        personas=["analyst", "thesis_lord"],
    ),
    "propose_thesis": ToolDef(
        name="propose_thesis",
        description="Detect signal convergences across the watchlist and generate a new structured investment thesis. Uses Claude to synthesize alert clusters, filing anomalies, insider buying, and macro shifts. Play money only.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_propose_thesis,
        personas=["thesis_lord"],
    ),
    "trigger_backtest": ToolDef(
        name="trigger_backtest",
        description="Enqueue a walk-forward backtest for a specific thesis and ticker. Returns a task_id to check status.",
        input_schema={
            "type": "object",
            "properties": {
                "thesis_id": {"type": "integer", "description": "ID of the SimulatedThesis to backtest"},
                "ticker_id": {"type": "integer", "description": "ID of the ticker to backtest against"},
            },
            "required": ["thesis_id", "ticker_id"],
        },
        execute=_exec_trigger_backtest,
        personas=["thesis_lord"],
    ),
    "get_thesis_lifecycle": ToolDef(
        name="get_thesis_lifecycle",
        description="List all simulated theses with their lifecycle status (proposed, backtesting, paper_live, retired, killed).",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["proposed", "backtesting", "paper_live", "retired", "killed"], "description": "Filter by status"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        execute=_exec_get_thesis_lifecycle,
        personas=["thesis_lord", "post_mortem"],
    ),
    "get_simulation_log": ToolDef(
        name="get_simulation_log",
        description="Query the immutable simulation decision log. Every thesis generation, backtest, entry, exit, mutation, and retirement is here.",
        input_schema={
            "type": "object",
            "properties": {
                "thesis_id": {"type": "integer", "description": "Filter by thesis ID"},
                "event_type": {"type": "string", "description": "Filter by event type (generation, backtest_start, entry, exit, etc.)"},
                "limit": {"type": "integer", "default": 30},
            },
        },
        execute=_exec_get_simulation_log,
        personas=["thesis_lord", "post_mortem"],
    ),
    "mutate_thesis": ToolDef(
        name="mutate_thesis",
        description="Propose and apply mutations to an existing thesis (tighten criteria, adjust horizon, update risk factors).",
        input_schema={
            "type": "object",
            "properties": {
                "thesis_id": {"type": "integer"},
                "changes": {"type": "object", "description": "Dict of fields to update: entry_criteria, exit_criteria, time_horizon_days, risk_factors"},
                "reason": {"type": "string", "description": "Why this mutation is being applied"},
            },
            "required": ["thesis_id", "reason"],
        },
        execute=_exec_mutate_thesis,
        personas=["thesis_lord"],
    ),
    "retire_thesis": ToolDef(
        name="retire_thesis",
        description="Retire or kill a thesis with a documented reason. Logs to SimulationLog.",
        input_schema={
            "type": "object",
            "properties": {
                "thesis_id": {"type": "integer"},
                "reason": {"type": "string", "description": "Why this thesis is being retired/killed"},
            },
            "required": ["thesis_id", "reason"],
        },
        execute=_exec_retire_thesis,
        personas=["thesis_lord"],
    ),
    "get_performance_attribution": ToolDef(
        name="get_performance_attribution",
        description="Get P&L attribution by thesis — which ideas are driving returns in the paper portfolio.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_get_performance_attribution,
        personas=["thesis_lord", "post_mortem"],
    ),
    "get_vol_surface": ToolDef(
        name="get_vol_surface",
        description="Get the latest fitted implied volatility surface for a ticker (strike × expiry → IV grid).",
        input_schema={
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Ticker symbol e.g. NVDA"}},
            "required": ["ticker"],
        },
        execute=_exec_get_vol_surface,
        personas=["vol_slayer", "analyst"],
    ),
    "get_options_chain_data": ToolDef(
        name="get_options_chain_data",
        description="Get the latest options chain data for a ticker (strikes, expiries, IVs, Greeks).",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["ticker"],
        },
        execute=_exec_get_options_chain_data,
        personas=["vol_slayer", "analyst"],
    ),
    "compare_iv_rv": ToolDef(
        name="compare_iv_rv",
        description="Compare implied volatility (from vol surface) to realized volatility (from price history) for a ticker.",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "lookback_days": {"type": "integer", "default": 30},
            },
            "required": ["ticker"],
        },
        execute=_exec_compare_iv_rv,
        personas=["vol_slayer"],
    ),
    "explain_skew": ToolDef(
        name="explain_skew",
        description="Interpret the current 25-delta skew from the vol surface — what the market is pricing in for this ticker.",
        input_schema={
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
        execute=_exec_explain_skew,
        personas=["vol_slayer"],
    ),
    "get_heston_params": ToolDef(
        name="get_heston_params",
        description="Get the latest Heston stochastic vol calibration parameters for a ticker, with plain-English interpretation of each parameter.",
        input_schema={
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
        execute=_exec_get_heston_params,
        personas=["vol_slayer", "heston_cal"],
    ),
    "price_option_heston": ToolDef(
        name="price_option_heston",
        description="Price a European call option under the Heston stochastic vol model and compare to Black-Scholes.",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "strike": {"type": "number", "description": "Strike price"},
                "expiry_years": {"type": "number", "description": "Time to expiry in years e.g. 0.25 = 3 months"},
                "risk_free_rate": {"type": "number", "default": 0.05},
            },
            "required": ["ticker", "strike", "expiry_years"],
        },
        execute=_exec_price_option_heston,
        personas=["vol_slayer", "heston_cal"],
    ),
    "calibrate_heston_now": ToolDef(
        name="calibrate_heston_now",
        description="Trigger an on-demand Heston calibration batch for all tickers with options data. Returns task_id.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_calibrate_heston_now,
        personas=["heston_cal"],
    ),
    "generate_mc_paths": ToolDef(
        name="generate_mc_paths",
        description="Generate Monte Carlo price paths under the Heston model for a ticker and return the terminal price distribution.",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "horizon_years": {"type": "number", "default": 1.0},
                "n_paths": {"type": "integer", "default": 1000, "description": "Number of simulation paths (max 5000)"},
            },
            "required": ["ticker"],
        },
        execute=_exec_generate_mc_paths,
        personas=["heston_cal"],
    ),
    "get_calibration_history": ToolDef(
        name="get_calibration_history",
        description="Get historical Heston calibration parameters for a ticker over the past N days.",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "days": {"type": "integer", "default": 30},
            },
            "required": ["ticker"],
        },
        execute=_exec_get_calibration_history,
        personas=["heston_cal"],
    ),
    "get_hedging_status": ToolDef(
        name="get_hedging_status",
        description="Get the current status of the deep hedging framework — what's implemented, what's pending, and next steps.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_get_hedging_status,
        personas=["deep_hedge"],
    ),
    "explain_hedging_concept": ToolDef(
        name="explain_hedging_concept",
        description="Explain a deep hedging concept: 'cvar', 'deep_hedging', or 'transaction_costs'.",
        input_schema={
            "type": "object",
            "properties": {
                "concept": {"type": "string", "enum": ["cvar", "deep_hedging", "transaction_costs"]},
            },
            "required": ["concept"],
        },
        execute=_exec_explain_hedging_concept,
        personas=["deep_hedge"],
    ),
    "get_retired_theses": ToolDef(
        name="get_retired_theses",
        description="Get all retired and killed theses with their retirement reasons for post-mortem analysis.",
        input_schema={"type": "object", "properties": {}},
        execute=_exec_get_retired_theses,
        personas=["post_mortem"],
    ),
    "write_post_mortem": ToolDef(
        name="write_post_mortem",
        description="Generate a forensic post-mortem analysis for a retired/killed thesis using its decision log and backtest results.",
        input_schema={
            "type": "object",
            "properties": {"thesis_id": {"type": "integer"}},
            "required": ["thesis_id"],
        },
        execute=_exec_write_post_mortem,
        personas=["post_mortem"],
    ),
    "get_agent_memories": ToolDef(
        name="get_agent_memories",
        description="Query the agent memory bank — durable lessons learned from past thesis generation, backtesting, and trading.",
        input_schema={
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Filter by agent (e.g. thesis_lord, post_mortem)"},
                "memory_type": {"type": "string", "enum": ["insight", "pattern", "failure", "success"]},
                "limit": {"type": "integer", "default": 10},
            },
        },
        execute=_exec_get_agent_memories,
        personas=["post_mortem"],
    ),
    "search_decision_log": ToolDef(
        name="search_decision_log",
        description="Full-text search of the simulation decision log by keyword.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
        execute=_exec_search_decision_log,
        personas=["post_mortem"],
    ),
}


# Tools blocked for viewer role (thesis data, insider trades, admin features)
VIEWER_BLOCKED_TOOLS = {
    "get_thesis_matches",
    "get_filing_drift",
    "capture_feature_request",
    "list_feature_requests",
    "get_insider_buys",
}


def get_tools_for_persona(persona_name: str, user_role: str = "admin") -> list[dict]:
    """Return Claude-formatted tool definitions for a given persona and user role."""
    tools = []
    for tool in TOOL_REGISTRY.values():
        if persona_name in tool.personas:
            # Block sensitive tools for viewers
            if user_role == "viewer" and tool.name in VIEWER_BLOCKED_TOOLS:
                continue
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            })
    return tools


async def execute_tool(name: str, params: dict, session: AsyncSession) -> dict:
    """Execute a tool by name and return the result dict."""
    tool = TOOL_REGISTRY.get(name)
    if not tool:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = await tool.execute(session, params)
        return _json_safe(result)
    except Exception as exc:
        logger.error("Tool %s failed: %s", name, exc)
        return {"error": f"Tool execution failed: {exc}"}
