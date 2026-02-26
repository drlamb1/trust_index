"""
EdgeFinder — Agent Memory System

Long-term memory for the agent swarm. The Post-Mortem Priest extracts
durable insights from the SimulationLog and stores them as AgentMemory
records. These memories are injected into agent system prompts to make
future decisions smarter.

If the user ghosts for 30 days, the system wakes up with accumulated
wisdom — not because it ran, but because the memories persist.

Memory types:
  INSIGHT  — "RSI oversold + insider buying has 73% hit rate"
  PATTERN  — "Heston rho consistently < -0.6 for tech names"
  FAILURE  — "Thesis X failed because we ignored sector rotation"
  SUCCESS  — "Energy transition thesis outperformed by 12%"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import AgentMemory, MemoryType, SimulationLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Memory Storage
# ---------------------------------------------------------------------------


async def store_memory(
    session: AsyncSession,
    agent_name: str,
    memory_type: MemoryType,
    content: str,
    confidence: float = 0.5,
    evidence: dict | None = None,
) -> AgentMemory:
    """Store a new agent memory.

    Args:
        agent_name: Which agent created this memory
        memory_type: Category (insight, pattern, failure, success)
        content: The actual memory text
        confidence: How confident we are this is durable (0-1)
        evidence: Supporting data references

    Returns:
        The created AgentMemory record
    """
    memory = AgentMemory(
        agent_name=agent_name,
        memory_type=memory_type.value,
        content=content,
        confidence=confidence,
        evidence=evidence,
    )
    session.add(memory)
    await session.flush()

    logger.info(
        "Stored %s memory for %s (confidence=%.2f): %s",
        memory_type.value, agent_name, confidence, content[:80],
    )
    return memory


# ---------------------------------------------------------------------------
# Memory Recall
# ---------------------------------------------------------------------------


async def recall_relevant_memories(
    session: AsyncSession,
    agent_name: str,
    context: str | None = None,
    memory_type: str | None = None,
    limit: int = 5,
    min_confidence: float = 0.3,
) -> list[AgentMemory]:
    """Retrieve the most relevant memories for an agent.

    Ranking: confidence × recency × access_count.
    Updates access_count and last_accessed on recalled memories.

    Args:
        agent_name: Which agent's memories to search (or None for all)
        context: Optional context string for keyword matching
        memory_type: Filter by type (insight, pattern, failure, success)
        limit: Max memories to return
        min_confidence: Minimum confidence threshold

    Returns:
        List of AgentMemory records, most relevant first
    """
    query = (
        select(AgentMemory)
        .where(AgentMemory.confidence >= min_confidence)
        .order_by(desc(AgentMemory.confidence), desc(AgentMemory.last_accessed))
        .limit(limit * 2)  # fetch extra, then filter
    )

    if agent_name:
        query = query.where(AgentMemory.agent_name == agent_name)
    if memory_type:
        query = query.where(AgentMemory.memory_type == memory_type)

    result = await session.execute(query)
    memories = list(result.scalars().all())

    # Simple keyword relevance if context provided
    if context and memories:
        context_lower = context.lower()
        context_words = set(context_lower.split())

        def relevance_score(mem: AgentMemory) -> float:
            mem_words = set(mem.content.lower().split())
            overlap = len(context_words & mem_words)
            return overlap * mem.confidence

        memories.sort(key=relevance_score, reverse=True)

    memories = memories[:limit]

    # Update access tracking
    now = datetime.now(timezone.utc)
    for mem in memories:
        mem.access_count += 1
        mem.last_accessed = now

    return memories


async def inject_memories_into_prompt(
    session: AsyncSession,
    agent_name: str,
    context: str | None = None,
    limit: int = 5,
) -> str:
    """Build a memory block to prepend to an agent's system prompt.

    Returns formatted string of relevant memories, or empty string if none.
    """
    memories = await recall_relevant_memories(
        session, agent_name, context=context, limit=limit,
    )

    if not memories:
        return ""

    lines = ["\n--- AGENT MEMORIES (from past experience) ---"]
    for mem in memories:
        type_icon = {"insight": "💡", "pattern": "🔄", "failure": "⚠️", "success": "✅"}.get(mem.memory_type, "📝")
        lines.append(
            f"{type_icon} [{mem.memory_type.upper()}] (confidence: {mem.confidence:.0%}) {mem.content}"
        )
    lines.append("--- END MEMORIES ---\n")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Memory Consolidation
# ---------------------------------------------------------------------------


async def consolidate_memories(
    session: AsyncSession,
    api_key: str,
    lookback_days: int = 7,
) -> int:
    """Weekly memory consolidation via Claude.

    Reviews recent SimulationLog entries and extracts durable insights.
    Updates confidence on existing memories. Prunes old low-confidence ones.

    Returns count of memories created/updated.
    """
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    # Fetch recent simulation events
    result = await session.execute(
        select(SimulationLog)
        .where(SimulationLog.created_at >= since)
        .order_by(SimulationLog.created_at)
        .limit(100)
    )
    events = result.scalars().all()

    if not events:
        logger.info("No simulation events in last %d days — nothing to consolidate", lookback_days)
        return 0

    # Format events for Claude
    event_summaries = []
    for e in events:
        event_summaries.append({
            "type": e.event_type,
            "agent": e.agent_name,
            "thesis_id": e.thesis_id,
            "data": e.event_data,
            "timestamp": e.created_at.isoformat() if e.created_at else None,
        })

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)

        prompt = f"""Review these simulation engine events from the past {lookback_days} days and extract
durable lessons. For each lesson, provide:
1. The insight/pattern/failure/success
2. Confidence level (0.0-1.0) based on how much evidence supports it
3. Whether it's an INSIGHT, PATTERN, FAILURE, or SUCCESS

Events:
{json.dumps(event_summaries, indent=2, default=str)}

Return a JSON array of memories:
[
  {{"type": "insight", "content": "description", "confidence": 0.7}},
  ...
]

Only extract genuinely durable lessons. Not every event is worth remembering.
Focus on patterns that would help future thesis generation and evaluation."""

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",  # Haiku for cost efficiency
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]

        new_memories = json.loads(raw)
        count = 0

        for mem_data in new_memories:
            if not isinstance(mem_data, dict) or "content" not in mem_data:
                continue

            mem_type = mem_data.get("type", "insight")
            try:
                memory_type = MemoryType(mem_type)
            except ValueError:
                memory_type = MemoryType.INSIGHT

            await store_memory(
                session,
                agent_name="post_mortem",
                memory_type=memory_type,
                content=mem_data["content"],
                confidence=float(mem_data.get("confidence", 0.5)),
                evidence={"source": "weekly_consolidation", "event_count": len(events)},
            )
            count += 1

        # Log the consolidation
        log_entry = SimulationLog(
            thesis_id=None,
            agent_name="post_mortem",
            event_type="memory_consolidated",
            event_data={
                "events_reviewed": len(events),
                "memories_created": count,
                "lookback_days": lookback_days,
            },
        )
        session.add(log_entry)

        logger.info("Memory consolidation complete: %d memories from %d events", count, len(events))
        return count

    except Exception as e:
        logger.error("Memory consolidation failed: %s", e)
        return 0


# ---------------------------------------------------------------------------
# Memory Pruning
# ---------------------------------------------------------------------------


async def prune_stale_memories(
    session: AsyncSession,
    max_age_days: int = 90,
    min_confidence: float = 0.3,
) -> int:
    """Remove old, low-confidence memories.

    Keeps memories that are:
      - Less than max_age_days old, OR
      - Have confidence >= min_confidence, OR
      - Have been accessed recently (last 30 days)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    recent_access = datetime.now(timezone.utc) - timedelta(days=30)

    result = await session.execute(
        select(AgentMemory).where(
            AgentMemory.created_at < cutoff,
            AgentMemory.confidence < min_confidence,
            AgentMemory.last_accessed < recent_access,
        )
    )
    stale = result.scalars().all()

    for mem in stale:
        await session.delete(mem)

    logger.info("Pruned %d stale memories", len(stale))
    return len(stale)
