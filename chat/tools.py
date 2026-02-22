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
        personas=["analyst", "thesis", "pm"],
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
