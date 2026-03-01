"""
EdgeFinder — Chat API Routes

Endpoints:
    POST /api/chat                              → SSE stream (main chat)
    GET  /api/chat/conversations                → List conversations
    GET  /api/chat/conversations/{id}/messages   → Message history
    GET  /api/chat/feature-requests              → PM-captured features
"""

from __future__ import annotations

import json
import logging
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from config.settings import settings
from core.database import AsyncSessionLocal, get_db
from core.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    persona: str | None = None  # explicit persona override


# ---------------------------------------------------------------------------
# SSE streaming endpoint
# ---------------------------------------------------------------------------


@router.post("")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Main chat endpoint. Streams SSE events. Requires authentication.

    Manages its own DB session inside the generator because
    StreamingResponse runs the generator after the route handler returns,
    which means FastAPI's Depends(get_db) session would already be closed.
    """
    from chat.engine import chat_turn

    api_key = settings.anthropic_api_key
    if not api_key:
        return JSONResponse(
            {"error": "ANTHROPIC_API_KEY not configured"},
            status_code=500,
        )

    # Token budget enforcement for viewers
    if user.role == "viewer" and user.daily_token_budget > 0:
        if user.last_token_reset != date.today():
            user.tokens_used_today = 0
            user.last_token_reset = date.today()
        if user.tokens_used_today >= user.daily_token_budget:
            return JSONResponse(
                {"error": "Daily token limit reached. Try again tomorrow."},
                status_code=429,
            )

    user_id = user.id
    user_role = user.role

    async def event_generator():
        async with AsyncSessionLocal() as session:
            try:
                total_tokens = 0
                async for event in chat_turn(
                    user_text=body.message,
                    session=session,
                    api_key=api_key,
                    conversation_id=body.conversation_id,
                    persona_override=body.persona,
                    user_id=user_id,
                    user_role=user_role,
                ):
                    event_type = event.get("event", "message")
                    data = event.get("data", {})

                    # Track token usage from done event
                    if event_type == "done":
                        total_tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)

                    yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

                # Update viewer token budget after stream completes
                if user_role == "viewer" and total_tokens > 0:
                    from sqlalchemy import update as sa_update

                    await session.execute(
                        sa_update(User)
                        .where(User.id == user_id)
                        .values(
                            tokens_used_today=User.tokens_used_today + total_tokens,
                            last_token_reset=date.today(),
                        )
                    )

                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.exception("Chat stream error: %s", exc)
                yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------


@router.get("/conversations")
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from chat.engine import list_conversations as _list_convs
    convs = await _list_convs(db, user_id=user.id)
    return JSONResponse({"conversations": convs})


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from chat.engine import get_conversation_messages
    msgs = await get_conversation_messages(db, conversation_id, user_id=user.id)
    return JSONResponse({"messages": msgs})


# ---------------------------------------------------------------------------
# Feature requests
# ---------------------------------------------------------------------------


@router.get("/feature-requests")
async def list_feature_requests(
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from chat.tools import execute_tool
    result = await execute_tool(
        "list_feature_requests",
        {"status": status} if status else {},
        db,
    )
    return JSONResponse(result)
