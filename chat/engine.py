"""
EdgeFinder — Chat Engine (Core Agentic Loop)

Handles the full lifecycle of a chat turn:
  1. Load/create conversation
  2. Route user message to persona
  3. Build Claude message history from DB
  4. Stream Claude Sonnet response with tool_use handling
  5. Persist all messages (user, assistant, tool_call, tool_result)
  6. Yield SSE events for the frontend
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import functools
import pathlib
import time

import anthropic
import jinja2
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from chat.personas import PERSONAS as PERSONA_CONFIGS, get_persona
from chat.router import route_message
from chat.tools import TOOL_REGISTRY, execute_tool, get_tools_for_persona
from core.models import (
    ChatConversation,
    ChatMessage,
    FeatureRequest,
    SimulatedThesis,
    BacktestRun,
    PaperPortfolio,
    SimulationLog,
    Ticker,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
CONTEXT_WINDOW = 20  # max messages to include in context

# PM brief template — load once, render per turn with live data
_PM_BRIEF_TEMPLATE_PATH = pathlib.Path(__file__).resolve().parent.parent / "docs" / "pm_brief.md.j2"

_pm_brief_cache: dict[str, Any] = {"text": "", "ts": 0.0}
_PM_BRIEF_TTL = 300  # 5 minutes


@functools.lru_cache(maxsize=1)
def _load_pm_template() -> jinja2.Template | None:
    if _PM_BRIEF_TEMPLATE_PATH.exists():
        return jinja2.Template(_PM_BRIEF_TEMPLATE_PATH.read_text())
    return None


async def _render_pm_brief(session: AsyncSession) -> str:
    """Render the PM brief template with live DB stats. Cached for 5 min."""
    now = time.monotonic()
    if _pm_brief_cache["text"] and (now - _pm_brief_cache["ts"]) < _PM_BRIEF_TTL:
        return _pm_brief_cache["text"]

    tmpl = _load_pm_template()
    if not tmpl:
        return ""

    # Parallel-ish queries (SQLAlchemy batches on same connection)
    active_tickers = (await session.execute(select(func.count(Ticker.id)).where(Ticker.is_active.is_(True)))).scalar() or 0
    thesis_count = (await session.execute(select(func.count(SimulatedThesis.id)))).scalar() or 0
    backtest_count = (await session.execute(select(func.count(BacktestRun.id)))).scalar() or 0
    portfolio_count = (await session.execute(select(func.count(PaperPortfolio.id)))).scalar() or 0
    chat_message_count = (await session.execute(select(func.count(ChatMessage.id)))).scalar() or 0
    conversation_count = (await session.execute(select(func.count(ChatConversation.id)))).scalar() or 0
    sim_log_count = (await session.execute(select(func.count(SimulationLog.id)))).scalar() or 0
    fr_count = (await session.execute(select(func.count(FeatureRequest.id)))).scalar() or 0
    fr_open = (await session.execute(
        select(func.count(FeatureRequest.id)).where(FeatureRequest.status.in_(["captured", "reviewed"]))
    )).scalar() or 0

    personas = [
        {"name": p.display_name, "tools": len(p.tools)}
        for p in PERSONA_CONFIGS.values()
    ]

    rendered = tmpl.render(
        active_tickers=active_tickers,
        thesis_count=thesis_count,
        backtest_count=backtest_count,
        portfolio_count=portfolio_count,
        chat_message_count=chat_message_count,
        conversation_count=conversation_count,
        sim_log_count=sim_log_count,
        fr_count=fr_count,
        fr_open=fr_open,
        persona_count=len(PERSONA_CONFIGS),
        personas=personas,
        tool_count=len(TOOL_REGISTRY),
        celery_task_count=40,  # from scheduler/tasks.py — stable enough to hardcode
    )

    _pm_brief_cache["text"] = rendered
    _pm_brief_cache["ts"] = now
    return rendered
MAX_TOKENS = 8192


# ---------------------------------------------------------------------------
# SSE event helpers
# ---------------------------------------------------------------------------


def _sse(event: str, **data: Any) -> dict:
    """Build an SSE event dict."""
    return {"event": event, "data": data}


# ---------------------------------------------------------------------------
# Conversation management
# ---------------------------------------------------------------------------


async def _get_or_create_conversation(
    session: AsyncSession,
    conversation_id: str | None,
) -> ChatConversation:
    """Load an existing conversation or create a new one."""
    if conversation_id:
        result = await session.execute(
            select(ChatConversation).where(ChatConversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if conv:
            return conv

    conv = ChatConversation(
        id=str(uuid.uuid4()),
        user_id=None,  # Set by caller via chat_turn
        title=None,
        active_persona="edge",
        message_count=0,
        total_input_tokens=0,
        total_output_tokens=0,
    )
    session.add(conv)
    await session.flush()
    return conv


async def _get_next_sequence(session: AsyncSession, conversation_id: str) -> int:
    """Get the next sequence number for a conversation."""
    result = await session.execute(
        select(ChatMessage.sequence)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.sequence.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return (row or 0) + 1


async def _persist_message(
    session: AsyncSession,
    conversation_id: str,
    sequence: int,
    role: str,
    content: str,
    persona: str | None = None,
    tool_name: str | None = None,
    tool_input: dict | None = None,
    tool_result_data: dict | None = None,
    model_used: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
) -> ChatMessage:
    """Insert a ChatMessage row."""
    msg = ChatMessage(
        conversation_id=conversation_id,
        sequence=sequence,
        role=role,
        persona=persona,
        content=content or "",
        tool_name=tool_name,
        tool_input=tool_input,
        tool_result_data=tool_result_data,
        model_used=model_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
    )
    session.add(msg)
    await session.flush()
    return msg


# ---------------------------------------------------------------------------
# Context building — reconstruct Claude message format from DB rows
# ---------------------------------------------------------------------------


def _build_claude_messages(db_messages: list[ChatMessage]) -> list[dict]:
    """
    Convert DB message rows into Claude API message format.

    Groups tool_call/tool_result rows with their adjacent assistant messages
    to reconstruct the proper alternating user/assistant structure.
    """
    claude_msgs: list[dict] = []
    i = 0

    while i < len(db_messages):
        msg = db_messages[i]

        if msg.role == "user":
            claude_msgs.append({"role": "user", "content": msg.content})
            i += 1

        elif msg.role == "assistant":
            # Start building assistant content blocks
            content_blocks: list[dict] = []
            if msg.content:
                content_blocks.append({"type": "text", "text": msg.content})
            i += 1

            # Collect any following tool_call rows into the same assistant message
            tool_use_ids: list[str] = []
            while i < len(db_messages) and db_messages[i].role == "tool_call":
                tc = db_messages[i]
                tool_id = tc.tool_input.get("_tool_use_id", f"toolu_{tc.id}") if tc.tool_input else f"toolu_{tc.id}"
                content_blocks.append({
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tc.tool_name,
                    "input": {k: v for k, v in (tc.tool_input or {}).items() if not k.startswith("_")},
                })
                tool_use_ids.append(tool_id)
                i += 1

            # Format the assistant message
            if len(content_blocks) == 1 and content_blocks[0]["type"] == "text":
                claude_msgs.append({"role": "assistant", "content": content_blocks[0]["text"]})
            elif content_blocks:
                claude_msgs.append({"role": "assistant", "content": content_blocks})

            # Collect tool_result rows into a user message
            if tool_use_ids:
                result_blocks: list[dict] = []
                idx = 0
                while i < len(db_messages) and db_messages[i].role == "tool_result":
                    tr = db_messages[i]
                    matched_id = tool_use_ids[idx] if idx < len(tool_use_ids) else f"toolu_{tr.id}"
                    # Truncate old tool results to save tokens
                    result_str = json.dumps(tr.tool_result_data) if tr.tool_result_data else tr.content
                    if len(result_str) > 2000:
                        result_str = result_str[:2000] + "... [truncated]"
                    result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": matched_id,
                        "content": result_str,
                    })
                    idx += 1
                    i += 1
                if result_blocks:
                    claude_msgs.append({"role": "user", "content": result_blocks})

        else:
            # Skip orphaned tool_call/tool_result rows (shouldn't happen)
            i += 1

    return claude_msgs


async def _load_context(
    session: AsyncSession,
    conversation_id: str,
    limit: int = CONTEXT_WINDOW,
) -> list[dict]:
    """Load recent messages and convert to Claude format."""
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.sequence.desc())
        .limit(limit)
    )
    db_messages = list(reversed(result.scalars().all()))
    return _build_claude_messages(db_messages)


# ---------------------------------------------------------------------------
# Main agentic loop
# ---------------------------------------------------------------------------


async def chat_turn(
    user_text: str,
    session: AsyncSession,
    api_key: str,
    conversation_id: str | None = None,
    persona_override: str | None = None,
    user_id: int | None = None,
    user_role: str = "admin",
) -> AsyncGenerator[dict, None]:
    """
    Execute a full chat turn with streaming.

    Yields SSE event dicts:
      - meta: persona selected, conversation info
      - token: streaming text delta
      - tool_start: tool execution beginning
      - tool_result: tool execution complete
      - handoff: persona switch suggested
      - done: turn complete with usage stats
      - error: something went wrong
    """
    try:
        # 1. Load or create conversation
        conv = await _get_or_create_conversation(session, conversation_id)

        # 2. Route to persona
        _ALL_PERSONAS = {"edge", "analyst", "thesis", "pm", "thesis_lord", "vol_slayer", "heston_cal", "deep_hedge", "post_mortem"}
        if persona_override and persona_override in _ALL_PERSONAS:
            persona_name = persona_override
            cleaned_text = user_text
        else:
            persona_name, cleaned_text = await route_message(
                user_text,
                current_persona=conv.active_persona,
                api_key=api_key,
            )

        persona = get_persona(persona_name)

        # Update conversation persona and ownership
        conv.active_persona = persona_name
        if user_id and not conv.user_id:
            conv.user_id = user_id
        if not conv.title and cleaned_text:
            conv.title = cleaned_text[:100]

        yield _sse("meta",
            conversation_id=conv.id,
            persona=persona_name,
            display_name=persona.display_name,
            color=persona.color,
            icon=persona.icon,
        )

        # 3. Persist user message
        seq = await _get_next_sequence(session, conv.id)
        await _persist_message(
            session, conv.id, seq, "user",
            content=cleaned_text,
            persona=persona_name,
        )
        seq += 1

        # 4. Build message context
        context_messages = await _load_context(session, conv.id)

        # 5. Prepare Claude call
        client = anthropic.AsyncAnthropic(api_key=api_key)
        tool_defs = get_tools_for_persona(persona_name, user_role=user_role)

        # Build system prompt — add viewer restriction if applicable
        system_text = persona.system_prompt
        if user_role == "viewer":
            system_text += (
                "\n\n[VIEWER MODE] This user has viewer-level access. "
                "Do not reveal investment theses, thesis matches, insider trade details, "
                "or filing drift analysis. If asked for this data, explain that it "
                "requires a member account. Focus on publicly available market data, "
                "technicals, news sentiment, and macro indicators."
            )

        if persona_name == "pm":
            pm_brief = await _render_pm_brief(session)
            if pm_brief:
                system_text += f"\n\n{pm_brief}"

        # Inject agent memories — durable lessons from past experience
        from simulation.memory import inject_memories_into_prompt
        memory_block = await inject_memories_into_prompt(
            session, persona_name, context=cleaned_text,
        )
        memory_count = 0
        if memory_block:
            system_text += memory_block
            memory_count = memory_block.count("[") - 1  # count memory entries

        system_blocks = [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        if memory_count > 0:
            yield _sse("memory_info", memory_count=memory_count)

        # 6. Agentic loop — stream response, handle tool_use
        total_input = 0
        total_output = 0
        total_cache_read = 0

        for round_num in range(MAX_TOOL_ROUNDS):
            full_text = ""
            tool_blocks: list[dict] = []  # {id, name, input}
            stop_reason = None

            # Stream Claude response
            async with client.messages.stream(
                model=persona.model,
                max_tokens=MAX_TOKENS,
                system=system_blocks,
                tools=tool_defs if tool_defs else anthropic.NOT_GIVEN,
                messages=context_messages,
            ) as stream:
                # Track content blocks as they stream
                current_block_type = None
                current_tool_id = None
                current_tool_name = None
                current_tool_json = ""

                async for event in stream:
                    event_type = getattr(event, "type", None)

                    if event_type == "content_block_start":
                        block = event.content_block
                        if block.type == "text":
                            current_block_type = "text"
                        elif block.type == "tool_use":
                            current_block_type = "tool_use"
                            current_tool_id = block.id
                            current_tool_name = block.name
                            current_tool_json = ""
                            yield _sse("tool_start",
                                tool_name=block.name,
                                tool_id=block.id,
                            )

                    elif event_type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            full_text += delta.text
                            yield _sse("token", text=delta.text)
                        elif delta.type == "input_json_delta":
                            current_tool_json += delta.partial_json

                    elif event_type == "content_block_stop":
                        if current_block_type == "tool_use" and current_tool_name:
                            try:
                                tool_input = json.loads(current_tool_json) if current_tool_json else {}
                            except json.JSONDecodeError:
                                tool_input = {}
                            tool_blocks.append({
                                "id": current_tool_id,
                                "name": current_tool_name,
                                "input": tool_input,
                            })
                        current_block_type = None
                        current_tool_id = None
                        current_tool_name = None
                        current_tool_json = ""

                # Get final message for usage stats
                final_message = await stream.get_final_message()
                stop_reason = final_message.stop_reason
                usage = final_message.usage
                total_input += usage.input_tokens
                total_output += usage.output_tokens
                total_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0

            # Persist assistant text
            if full_text:
                await _persist_message(
                    session, conv.id, seq, "assistant",
                    content=full_text,
                    persona=persona_name,
                    model_used=persona.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0),
                )
                seq += 1

            # If no tool use, we're done
            if stop_reason != "tool_use" or not tool_blocks:
                break

            # Execute tools and persist
            # First, build the assistant content block for context
            assistant_content: list[dict] = []
            if full_text:
                assistant_content.append({"type": "text", "text": full_text})
            for tb in tool_blocks:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tb["id"],
                    "name": tb["name"],
                    "input": tb["input"],
                })
            context_messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool and collect results
            tool_results: list[dict] = []
            for tb in tool_blocks:
                # Persist tool_call — inject context metadata for tools that need it
                tool_input_with_id = {**tb["input"], "_tool_use_id": tb["id"]}
                tool_input_with_id["_user_id"] = user_id
                if tb["name"] == "capture_feature_request":
                    tool_input_with_id["_conversation_id"] = conv.id
                await _persist_message(
                    session, conv.id, seq, "tool_call",
                    content="",
                    persona=persona_name,
                    tool_name=tb["name"],
                    tool_input=tool_input_with_id,
                )
                seq += 1

                # Execute — pass _user_id and _persona so tools can query user-scoped data
                exec_params = {**tb["input"], "_user_id": user_id, "_persona": persona_name}
                result_data = await execute_tool(tb["name"], exec_params, session)

                # Persist tool_result
                await _persist_message(
                    session, conv.id, seq, "tool_result",
                    content="",
                    persona=persona_name,
                    tool_name=tb["name"],
                    tool_result_data=result_data,
                )
                seq += 1

                result_str = json.dumps(result_data)
                yield _sse("tool_result",
                    tool_name=tb["name"],
                    tool_id=tb["id"],
                    result=result_data,
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tb["id"],
                    "content": result_str,
                })

                # Handle handoff suggestion — update conversation's active persona
                # so the next Auto-routed message goes to the right persona
                if tb["name"] == "suggest_handoff" and result_data.get("handoff_suggested"):
                    target = result_data.get("target_persona", "analyst")
                    reason = result_data.get("reason", "")
                    conv.active_persona = target
                    yield _sse("handoff",
                        target_persona=target,
                        reason=reason,
                    )

            # Add tool results to context for next round
            context_messages.append({"role": "user", "content": tool_results})

            # Signal frontend that a new text round is starting (preserves prior text)
            yield _sse("round_start", round=round_num + 1)

        # 7. Update conversation stats
        conv.message_count = seq - 1
        conv.total_input_tokens += total_input
        conv.total_output_tokens += total_output
        await session.flush()

        yield _sse("done",
            conversation_id=conv.id,
            persona=persona_name,
            input_tokens=total_input,
            output_tokens=total_output,
            cache_read_tokens=total_cache_read,
        )

    except Exception as exc:
        logger.exception("Chat engine error: %s", exc)
        yield _sse("error", message=str(exc))


# ---------------------------------------------------------------------------
# Conversation listing
# ---------------------------------------------------------------------------


async def list_conversations(
    session: AsyncSession,
    limit: int = 20,
    user_id: int | None = None,
) -> list[dict]:
    """List recent conversations, optionally filtered by user."""
    stmt = select(ChatConversation)
    if user_id is not None:
        stmt = stmt.where(ChatConversation.user_id == user_id)
    result = await session.execute(
        stmt.order_by(ChatConversation.updated_at.desc()).limit(limit)
    )
    convs = result.scalars().all()
    return [
        {
            "id": c.id,
            "title": c.title or "New conversation",
            "active_persona": c.active_persona,
            "message_count": c.message_count,
            "total_input_tokens": c.total_input_tokens,
            "total_output_tokens": c.total_output_tokens,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in convs
    ]


async def get_conversation_messages(
    session: AsyncSession,
    conversation_id: str,
    limit: int = 100,
    user_id: int | None = None,
) -> list[dict]:
    """Get messages for a conversation. When user_id is provided, verifies ownership."""
    if user_id is not None:
        conv = await session.execute(
            select(ChatConversation.id).where(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user_id,
            )
        )
        if conv.scalar_one_or_none() is None:
            return []

    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.sequence)
        .limit(limit)
    )
    msgs = result.scalars().all()
    return [
        {
            "id": m.id,
            "sequence": m.sequence,
            "role": m.role,
            "persona": m.persona,
            "content": m.content,
            "tool_name": m.tool_name,
            "tool_input": {k: v for k, v in (m.tool_input or {}).items() if not k.startswith("_")} if m.tool_input else None,
            "tool_result_data": m.tool_result_data,
            "model_used": m.model_used,
            "input_tokens": m.input_tokens,
            "output_tokens": m.output_tokens,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]
