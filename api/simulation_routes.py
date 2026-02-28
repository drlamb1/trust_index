"""
EdgeFinder — Simulation Dashboard Routes

FastAPI routes for the simulation engine dashboard and JSON API.

Routes:
    GET /simulation              — HTML dashboard
    GET /simulation/stream       — SSE agent activity feed
    GET /api/simulation/portfolio — Paper portfolio JSON
    GET /api/simulation/theses   — Thesis lifecycle JSON
    GET /api/simulation/vol-surface/{ticker} — Vol surface JSON
    GET /api/simulation/heston/{ticker}     — Heston params JSON
    GET /api/simulation/decision-log        — Paginated SimulationLog
    GET /api/simulation/memories            — Agent memory bank
    GET /api/simulation/stats               — Aggregate statistics
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from api.dependencies import get_current_user, get_optional_user
from config.settings import settings
from core.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


def _json_safe(obj):
    """Convert non-JSON-safe types."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, float) and (obj != obj):  # NaN check
        return None
    return obj


# ---------------------------------------------------------------------------
# HTML Dashboard
# ---------------------------------------------------------------------------


@router.get("/simulation", response_class=HTMLResponse)
async def simulation_dashboard(user: User | None = Depends(get_optional_user)):
    if settings.is_production and user is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login", status_code=302)

    from api.simulation_page import simulation_page_html
    return HTMLResponse(simulation_page_html())


# ---------------------------------------------------------------------------
# SSE Agent Activity Feed
# ---------------------------------------------------------------------------


@router.get("/simulation/stream")
async def simulation_stream(user: User | None = Depends(get_optional_user)):
    """SSE endpoint that tails the SimulationLog for live agent activity updates."""

    async def event_generator():
        from sqlalchemy import desc, select
        from core.database import AsyncSessionLocal
        from core.models import SimulationLog

        last_id = 0
        async with AsyncSessionLocal() as session:
            # Get most recent entries to initialize
            result = await session.execute(
                select(SimulationLog)
                .order_by(desc(SimulationLog.id))
                .limit(20)
            )
            entries = list(reversed(result.scalars().all()))
            for entry in entries:
                event_data = {
                    "id": entry.id,
                    "agent_name": entry.agent_name,
                    "event_type": entry.event_type,
                    "thesis_id": entry.thesis_id,
                    "event_data": entry.event_data,
                    "created_at": entry.created_at.isoformat() if entry.created_at else None,
                }
                yield f"data: {json.dumps(event_data, default=_json_safe)}\n\n"
                last_id = max(last_id, entry.id)

        yield f"data: {json.dumps({'type': 'connected', 'last_id': last_id})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ---------------------------------------------------------------------------
# JSON API Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/simulation/portfolio")
async def api_portfolio(user: User = Depends(get_current_user)):
    """Paper portfolio state with positions and P&L attribution."""
    from core.database import AsyncSessionLocal
    from simulation.paper_portfolio import get_or_create_portfolio, portfolio_summary

    async with AsyncSessionLocal() as session:
        portfolio = await get_or_create_portfolio(session)
        summary = await portfolio_summary(session, portfolio)
        return JSONResponse(json.loads(json.dumps(summary, default=_json_safe)))


@router.get("/api/simulation/theses")
async def api_theses(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, le=50),
    user: User = Depends(get_current_user),
):
    """All theses with lifecycle status."""
    from sqlalchemy import select
    from core.database import AsyncSessionLocal
    from core.models import Ticker
    from simulation.thesis_generator import get_thesis_lifecycle

    async with AsyncSessionLocal() as session:
        theses = await get_thesis_lifecycle(session, status_filter=status, limit=limit)

        # Build ticker_id → symbol lookup
        ticker_result = await session.execute(select(Ticker.id, Ticker.symbol))
        ticker_map = {row.id: row.symbol for row in ticker_result}

        for t in theses:
            ids = t.get("ticker_ids") or []
            t["ticker_symbols"] = [ticker_map[i] for i in ids if i in ticker_map]
            t["ticker_symbol"] = t["ticker_symbols"][0] if t["ticker_symbols"] else None

        return JSONResponse(json.loads(json.dumps(theses, default=_json_safe)))


@router.get("/api/simulation/vol-surface/{ticker}")
async def api_vol_surface(ticker: str, user: User = Depends(get_current_user)):
    """Vol surface data for a specific ticker."""
    from sqlalchemy import desc, select
    from core.database import AsyncSessionLocal
    from core.models import Ticker, VolSurface

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Ticker).where(Ticker.symbol == ticker.upper())
        )
        ticker_obj = result.scalar_one_or_none()
        if not ticker_obj:
            return JSONResponse({"error": f"Ticker {ticker} not found"}, 404)

        result = await session.execute(
            select(VolSurface)
            .where(VolSurface.ticker_id == ticker_obj.id)
            .order_by(desc(VolSurface.as_of))
            .limit(1)
        )
        surface = result.scalar_one_or_none()
        if not surface:
            return JSONResponse({"error": "No vol surface data available"}, 404)

        return JSONResponse({
            "ticker": ticker.upper(),
            "as_of": surface.as_of.isoformat(),
            "model_type": surface.model_type,
            "surface_data": surface.surface_data,
            "calibration_error": surface.calibration_error,
        })


@router.get("/api/simulation/heston/{ticker}")
async def api_heston(ticker: str, user: User = Depends(get_current_user)):
    """Latest Heston calibration parameters for a ticker."""
    from sqlalchemy import desc, select
    from core.database import AsyncSessionLocal
    from core.models import HestonCalibration, Ticker

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Ticker).where(Ticker.symbol == ticker.upper())
        )
        ticker_obj = result.scalar_one_or_none()
        if not ticker_obj:
            return JSONResponse({"error": f"Ticker {ticker} not found"}, 404)

        result = await session.execute(
            select(HestonCalibration)
            .where(HestonCalibration.ticker_id == ticker_obj.id)
            .order_by(desc(HestonCalibration.as_of))
            .limit(1)
        )
        cal = result.scalar_one_or_none()
        if not cal:
            return JSONResponse({"error": "No Heston calibration available"}, 404)

        feller = 2 * cal.kappa * cal.theta > cal.sigma_v ** 2

        return JSONResponse({
            "ticker": ticker.upper(),
            "as_of": cal.as_of.isoformat(),
            "v0": cal.v0,
            "kappa": cal.kappa,
            "theta": cal.theta,
            "sigma_v": cal.sigma_v,
            "rho": cal.rho,
            "calibration_error": cal.calibration_error,
            "feller_satisfied": feller,
            "interpretation": {
                "current_vol": f"{(cal.v0 ** 0.5) * 100:.1f}%",
                "long_run_vol": f"{(cal.theta ** 0.5) * 100:.1f}%",
                "leverage_effect": "strong" if cal.rho < -0.5 else "moderate" if cal.rho < -0.3 else "weak",
            },
        })


@router.get("/api/simulation/decision-log")
async def api_decision_log(
    thesis_id: int | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    user: User = Depends(get_current_user),
):
    """Paginated simulation decision log."""
    from sqlalchemy import desc, select
    from core.database import AsyncSessionLocal
    from core.models import SimulationLog

    async with AsyncSessionLocal() as session:
        query = select(SimulationLog).order_by(desc(SimulationLog.created_at)).limit(limit)
        if thesis_id:
            query = query.where(SimulationLog.thesis_id == thesis_id)
        if event_type:
            query = query.where(SimulationLog.event_type == event_type)

        result = await session.execute(query)
        entries = result.scalars().all()

        return JSONResponse([
            {
                "id": e.id,
                "thesis_id": e.thesis_id,
                "agent_name": e.agent_name,
                "event_type": e.event_type,
                "event_data": e.event_data,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ])


@router.get("/api/simulation/memories")
async def api_memories(
    agent_name: str | None = Query(default=None),
    memory_type: str | None = Query(default=None),
    limit: int = Query(default=20, le=50),
    user: User = Depends(get_current_user),
):
    """Agent memory bank."""
    from sqlalchemy import desc, select
    from core.database import AsyncSessionLocal
    from core.models import AgentMemory

    async with AsyncSessionLocal() as session:
        query = select(AgentMemory).order_by(desc(AgentMemory.confidence)).limit(limit)
        if agent_name:
            query = query.where(AgentMemory.agent_name == agent_name)
        if memory_type:
            query = query.where(AgentMemory.memory_type == memory_type)

        result = await session.execute(query)
        memories = result.scalars().all()

        return JSONResponse([
            {
                "id": m.id,
                "agent_name": m.agent_name,
                "memory_type": m.memory_type,
                "content": m.content,
                "confidence": m.confidence,
                "evidence": m.evidence,
                "access_count": m.access_count,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ])


@router.get("/api/simulation/stats")
async def api_stats(user: User = Depends(get_current_user)):
    """Aggregate simulation statistics."""
    from sqlalchemy import func, select
    from core.database import AsyncSessionLocal
    from core.models import (
        AgentMemory, BacktestRun, PaperPortfolio, PaperPosition,
        SimulatedThesis, SimulationLog, ThesisStatus, PositionStatus,
    )

    async with AsyncSessionLocal() as session:
        # Thesis counts by status
        thesis_result = await session.execute(
            select(SimulatedThesis.status, func.count(SimulatedThesis.id))
            .group_by(SimulatedThesis.status)
        )
        thesis_counts = dict(thesis_result.all())

        # Total backtests
        bt_count = (await session.execute(
            select(func.count(BacktestRun.id))
        )).scalar_one()

        # Portfolio value
        portfolio_result = await session.execute(
            select(PaperPortfolio).limit(1)
        )
        portfolio = portfolio_result.scalar_one_or_none()

        # Memory count
        mem_count = (await session.execute(
            select(func.count(AgentMemory.id))
        )).scalar_one()

        # Log entries
        log_count = (await session.execute(
            select(func.count(SimulationLog.id))
        )).scalar_one()

        # Avg backtest performance
        bt_perf = (await session.execute(
            select(func.avg(BacktestRun.win_rate), func.avg(BacktestRun.sharpe))
            .where(BacktestRun.win_rate.isnot(None))
        )).one()

        return JSONResponse({
            "theses": {
                "total": sum(thesis_counts.values()),
                "by_status": thesis_counts,
            },
            "backtests": bt_count,
            "avg_win_rate": float(bt_perf[0]) if bt_perf[0] is not None else None,
            "avg_sharpe": float(bt_perf[1]) if bt_perf[1] is not None else None,
            "portfolio": {
                "value": portfolio.current_value if portfolio else 100_000,
                "pnl": portfolio.total_pnl if portfolio else 0,
                "pnl_pct": portfolio.total_pnl_pct if portfolio else 0,
            },
            "memories": mem_count,
            "log_entries": log_count,
            "disclaimer": "ALL VALUES ARE SIMULATED PLAY-MONEY",
        })


@router.get("/api/macro/pulse")
async def api_macro_pulse(user: User = Depends(get_current_user)):
    """Latest macro indicator values with change from previous reading."""
    from sqlalchemy import desc, select
    from core.database import AsyncSessionLocal
    from core.models import MacroIndicator

    SERIES_CONFIG = [
        ("FEDFUNDS", "Fed Funds",    "rate"),
        ("DGS10",    "10Y Yield",    "rate"),
        ("DGS2",     "2Y Yield",     "rate"),
        ("T10Y2Y",   "Yield Curve",  "spread"),
        ("UNRATE",   "Unemployment", "rate"),
        ("CPIAUCSL", "CPI",          "index"),
    ]

    async with AsyncSessionLocal() as session:
        cards = []
        for series_id, label, fmt in SERIES_CONFIG:
            result = await session.execute(
                select(MacroIndicator.value, MacroIndicator.date)
                .where(MacroIndicator.series_id == series_id)
                .order_by(desc(MacroIndicator.date))
                .limit(2)
            )
            rows = result.all()
            if not rows:
                cards.append({
                    "series_id": series_id, "label": label,
                    "value_str": "—", "change_str": None, "direction": "flat", "as_of": None,
                })
                continue

            latest_val = rows[0].value
            prev_val = rows[1].value if len(rows) > 1 else None

            if fmt == "rate":
                value_str = f"{latest_val:.2f}%"
            elif fmt == "spread":
                value_str = f"{latest_val:+.2f}"
            else:
                value_str = f"{latest_val:.1f}"

            if prev_val is not None:
                delta = latest_val - prev_val
                change_str = f"{delta:+.2f}pp" if fmt in ("rate", "spread") else f"{delta:+.1f}"
                direction = "flat" if abs(delta) < 0.005 else ("up" if delta > 0 else "down")
            else:
                change_str = None
                direction = "flat"

            cards.append({
                "series_id": series_id,
                "label": label,
                "value_str": value_str,
                "change_str": change_str,
                "direction": direction,
                "as_of": str(rows[0].date),
            })

        return JSONResponse(cards)


# ---------------------------------------------------------------------------
# ML Model Status
# ---------------------------------------------------------------------------


@router.get("/api/ml/status")
async def ml_model_status(
    user: User = Depends(get_current_user),
):
    """Return status of all ML models (versions, metrics, training info)."""
    from sqlalchemy import select

    from core.database import AsyncSessionLocal
    from core.models import MLModel, MLModelType

    async with AsyncSessionLocal() as session:
        status = {}
        for model_type in MLModelType:
            result = await session.execute(
                select(MLModel).where(
                    MLModel.model_type == model_type.value,
                    MLModel.is_active.is_(True),
                ).order_by(MLModel.version.desc()).limit(1)
            )
            model = result.scalar_one_or_none()

            if model:
                status[model_type.value] = {
                    "active": True,
                    "version": model.version,
                    "trained_at": model.trained_at.isoformat() if model.trained_at else None,
                    "size_kb": round(model.model_size_bytes / 1024, 1),
                    "format": model.model_format,
                    "model_hash": model.model_hash[:12],
                    "eval_metrics": model.eval_metrics,
                    "training_metrics": model.training_metrics,
                    "training_duration_seconds": model.training_duration_seconds,
                }
            else:
                status[model_type.value] = {
                    "active": False,
                    "version": 0,
                    "message": "No trained model available",
                }

        return JSONResponse(status)
