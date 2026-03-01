"""
EdgeFinder — Briefing Routes

Daily briefing endpoints with Edger synthesis.

Routes:
    GET /api/briefings         — Recent daily briefings (paginated)
    GET /api/briefings/latest  — Today's (or most recent) briefing
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select

from api.dependencies import get_optional_user
from core.database import AsyncSessionLocal
from core.models import DailyBriefing, User

logger = logging.getLogger(__name__)

router = APIRouter()


def _briefing_to_dict(b: DailyBriefing) -> dict:
    return {
        "id": b.id,
        "date": str(b.date),
        "edger_synthesis": b.edger_synthesis,
        "lesson_taught": b.lesson_taught,
        "content_md": b.content_md,
        "delivered_at": b.delivered_at.isoformat() if b.delivered_at else None,
    }


@router.get("/api/briefings")
async def list_briefings(
    limit: int = Query(default=10, le=60),
    offset: int = Query(default=0, ge=0),
    user: User | None = Depends(get_optional_user),
):
    """Return recent daily briefings with Edger synthesis."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DailyBriefing)
            .order_by(desc(DailyBriefing.date))
            .offset(offset)
            .limit(limit)
        )
        briefings = result.scalars().all()
        return JSONResponse([_briefing_to_dict(b) for b in briefings])


@router.get("/api/briefings/latest")
async def latest_briefing(
    user: User | None = Depends(get_optional_user),
):
    """Return the most recent daily briefing."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DailyBriefing)
            .order_by(desc(DailyBriefing.date))
            .limit(1)
        )
        briefing = result.scalar_one_or_none()
        if not briefing:
            return JSONResponse({"error": "No briefings yet"}, status_code=404)
        return JSONResponse(_briefing_to_dict(briefing))
