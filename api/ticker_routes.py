"""
EdgeFinder — Ticker Detail Routes

Per-ticker data endpoints for the TickerDetail page.

Routes:
    GET /api/tickers                          — Active ticker list (for autocomplete)
    GET /api/ticker/{symbol}                  — Ticker info + latest price + technicals
    GET /api/ticker/{symbol}/price-history    — PriceBar history (default 90 days)
    GET /api/ticker/{symbol}/alerts           — Recent alerts for ticker
    GET /api/ticker/{symbol}/theses           — Linked SimulatedTheses
    GET /api/ticker/{symbol}/backtests        — BacktestRun results for ticker
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from api.dependencies import get_current_user
from core.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


def _json_safe(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)}")


async def _get_ticker(session, symbol: str):
    from sqlalchemy import select
    from core.models import Ticker
    result = await session.execute(
        select(Ticker).where(Ticker.symbol == symbol.upper())
    )
    return result.scalar_one_or_none()


@router.get("/api/tickers")
async def api_ticker_list(user: User = Depends(get_current_user)):
    """Active ticker list for search autocomplete."""
    from sqlalchemy import select
    from core.database import AsyncSessionLocal
    from core.models import Ticker

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Ticker.symbol, Ticker.name)
            .where(Ticker.is_active.is_(True))
            .order_by(Ticker.symbol)
        )
        return JSONResponse([
            {"symbol": r[0], "name": r[1]}
            for r in result.all()
        ])


@router.get("/api/ticker/{symbol}")
async def api_ticker_summary(symbol: str, user: User = Depends(get_current_user)):
    """Ticker info, latest price, and most recent technical snapshot."""
    from sqlalchemy import desc, select
    from core.database import AsyncSessionLocal
    from core.models import PriceBar, TechnicalSnapshot

    async with AsyncSessionLocal() as session:
        ticker = await _get_ticker(session, symbol)
        if not ticker:
            return JSONResponse({"error": f"Ticker {symbol.upper()} not found"}, status_code=404)

        # Latest 2 price bars for close + daily change
        pb_result = await session.execute(
            select(PriceBar.close, PriceBar.date)
            .where(PriceBar.ticker_id == ticker.id)
            .order_by(desc(PriceBar.date))
            .limit(2)
        )
        pb_rows = pb_result.all()
        latest_close = pb_rows[0].close if pb_rows else None
        prev_close = pb_rows[1].close if len(pb_rows) > 1 else None
        daily_change_pct = (
            (latest_close - prev_close) / prev_close * 100
            if latest_close and prev_close and prev_close != 0
            else None
        )
        price_date = str(pb_rows[0].date) if pb_rows else None

        # Latest technical snapshot
        ts_result = await session.execute(
            select(TechnicalSnapshot)
            .where(TechnicalSnapshot.ticker_id == ticker.id)
            .order_by(desc(TechnicalSnapshot.date))
            .limit(1)
        )
        ts = ts_result.scalar_one_or_none()

        technicals = None
        if ts:
            # BB position
            if ts.bb_upper and ts.bb_lower and ts.bb_middle and latest_close:
                if latest_close > ts.bb_upper:
                    bb_position = "above upper"
                elif latest_close < ts.bb_lower:
                    bb_position = "below lower"
                else:
                    bb_position = "in band"
            else:
                bb_position = None

            technicals = {
                "date": str(ts.date),
                "rsi_14": ts.rsi_14,
                "macd": ts.macd,
                "macd_signal": ts.macd_signal,
                "macd_histogram": ts.macd_histogram,
                "macd_direction": "bull" if ts.macd_histogram and ts.macd_histogram > 0 else "bear",
                "bb_position": bb_position,
                "bb_upper": ts.bb_upper,
                "bb_lower": ts.bb_lower,
                "sma_20": ts.sma_20,
                "sma_50": ts.sma_50,
                "sma_200": ts.sma_200,
                "volume_ratio_20d": ts.volume_ratio_20d,
            }

        return JSONResponse({
            "id": ticker.id,
            "symbol": ticker.symbol,
            "name": ticker.name,
            "sector": ticker.sector,
            "in_watchlist": ticker.in_watchlist,
            "latest_close": latest_close,
            "daily_change_pct": daily_change_pct,
            "price_date": price_date,
            "technicals": technicals,
        })


@router.get("/api/ticker/{symbol}/price-history")
async def api_ticker_price_history(
    symbol: str,
    days: int = Query(default=90, le=365),
    user: User = Depends(get_current_user),
):
    """Price bar history for a ticker."""
    from sqlalchemy import desc, select
    from core.database import AsyncSessionLocal
    from core.models import PriceBar

    since = date.today() - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        ticker = await _get_ticker(session, symbol)
        if not ticker:
            return JSONResponse({"error": f"Ticker {symbol.upper()} not found"}, status_code=404)

        result = await session.execute(
            select(PriceBar)
            .where(PriceBar.ticker_id == ticker.id, PriceBar.date >= since)
            .order_by(PriceBar.date)
        )
        bars = result.scalars().all()

        return JSONResponse([
            {
                "date": str(b.date),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ])


@router.get("/api/ticker/{symbol}/alerts")
async def api_ticker_alerts(
    symbol: str,
    limit: int = Query(default=30, le=100),
    user: User = Depends(get_current_user),
):
    """Recent alerts for a ticker."""
    from sqlalchemy import desc, select
    from core.database import AsyncSessionLocal
    from core.models import Alert

    async with AsyncSessionLocal() as session:
        ticker = await _get_ticker(session, symbol)
        if not ticker:
            return JSONResponse({"error": f"Ticker {symbol.upper()} not found"}, status_code=404)

        result = await session.execute(
            select(Alert)
            .where(Alert.ticker_id == ticker.id)
            .order_by(desc(Alert.created_at))
            .limit(limit)
        )
        alerts = result.scalars().all()

        return JSONResponse([
            {
                "id": a.id,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "score": a.score,
                "title": a.title,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ])


@router.get("/api/ticker/{symbol}/theses")
async def api_ticker_theses(
    symbol: str,
    limit: int = Query(default=20, le=100),
    user: User = Depends(get_current_user),
):
    """SimulatedTheses linked to a ticker."""
    from sqlalchemy import desc, select
    from core.database import AsyncSessionLocal
    from core.models import SimulatedThesis

    async with AsyncSessionLocal() as session:
        ticker = await _get_ticker(session, symbol)
        if not ticker:
            return JSONResponse({"error": f"Ticker {symbol.upper()} not found"}, status_code=404)

        # JSONB array containment: ticker_ids @> '[ticker.id]'
        result = await session.execute(
            select(SimulatedThesis)
            .where(SimulatedThesis.ticker_ids.contains([ticker.id]))
            .order_by(desc(SimulatedThesis.created_at))
            .limit(limit)
        )
        theses = result.scalars().all()

        return JSONResponse(json.loads(json.dumps([
            {
                "id": t.id,
                "name": t.name,
                "status": t.status,
                "generated_by": t.generated_by,
                "time_horizon_days": t.time_horizon_days,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "thesis_text": t.thesis_text[:300] + "…" if len(t.thesis_text) > 300 else t.thesis_text,
                "risk_factors": t.risk_factors,
                "expected_catalysts": t.expected_catalysts,
            }
            for t in theses
        ], default=_json_safe)))


@router.get("/api/ticker/{symbol}/backtests")
async def api_ticker_backtests(
    symbol: str,
    limit: int = Query(default=20, le=100),
    user: User = Depends(get_current_user),
):
    """BacktestRun results for a ticker."""
    from sqlalchemy import desc, select
    from core.database import AsyncSessionLocal
    from core.models import BacktestRun, SimulatedThesis

    async with AsyncSessionLocal() as session:
        ticker = await _get_ticker(session, symbol)
        if not ticker:
            return JSONResponse({"error": f"Ticker {symbol.upper()} not found"}, status_code=404)

        result = await session.execute(
            select(BacktestRun, SimulatedThesis.name)
            .join(SimulatedThesis, BacktestRun.thesis_id == SimulatedThesis.id)
            .where(BacktestRun.ticker_id == ticker.id)
            .order_by(desc(BacktestRun.ran_at))
            .limit(limit)
        )
        rows = result.all()

        return JSONResponse(json.loads(json.dumps([
            {
                "id": bt.id,
                "thesis_id": bt.thesis_id,
                "thesis_name": thesis_name,
                "start_date": str(bt.start_date) if bt.start_date else None,
                "end_date": str(bt.end_date) if bt.end_date else None,
                "sharpe": bt.sharpe,
                "sortino": bt.sortino,
                "max_drawdown": bt.max_drawdown,
                "win_rate": bt.win_rate,
                "profit_factor": bt.profit_factor,
                "total_trades": bt.total_trades,
                "monte_carlo_p_value": bt.monte_carlo_p_value,
                "ran_at": bt.ran_at.isoformat() if bt.ran_at else None,
            }
            for bt, thesis_name in rows
        ], default=_json_safe)))
