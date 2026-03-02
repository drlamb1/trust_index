"""Tests for remember_this tool, memory injection into chat engine, and cross-agent recall."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat.tools import _exec_remember_this, TOOL_REGISTRY, get_tools_for_persona
from core.models import AgentMemory, MemoryType
from simulation.memory import inject_memories_into_prompt, recall_relevant_memories


# ---------------------------------------------------------------------------
# remember_this tool
# ---------------------------------------------------------------------------


class TestRememberThis:
    @pytest.mark.asyncio
    async def test_stores_user_context_memory(self, db_session: AsyncSession):
        result = await _exec_remember_this(db_session, {
            "content": "Marine Corps vet. 'Backblast area all clear' = check downstream risk.",
            "memory_type": "user_context",
            "confidence": 0.9,
            "_persona": "edge",
        })
        assert result["stored"] is True
        assert result["memory_type"] == "user_context"
        assert result["confidence"] == 0.9

        # Verify persisted to DB
        memories = (await db_session.execute(
            select(AgentMemory).where(AgentMemory.memory_type == "user_context")
        )).scalars().all()
        assert len(memories) == 1
        assert "Marine Corps" in memories[0].content
        assert memories[0].agent_name == "edge"

    @pytest.mark.asyncio
    async def test_stores_teaching_memory(self, db_session: AsyncSession):
        result = await _exec_remember_this(db_session, {
            "content": "Explained Sortino vs Sharpe — user groks downside deviation now.",
            "memory_type": "teaching",
            "confidence": 0.8,
            "_persona": "analyst",
        })
        assert result["stored"] is True
        assert result["memory_type"] == "teaching"

    @pytest.mark.asyncio
    async def test_stores_insight_memory(self, db_session: AsyncSession):
        result = await _exec_remember_this(db_session, {
            "content": "RSI < 30 plus insider buying has 73% hit rate in backtests.",
            "memory_type": "insight",
            "_persona": "thesis_lord",
        })
        assert result["stored"] is True
        assert result["memory_type"] == "insight"
        # Default confidence is 0.7
        assert result["confidence"] == 0.7

    @pytest.mark.asyncio
    async def test_requires_content(self, db_session: AsyncSession):
        result = await _exec_remember_this(db_session, {
            "memory_type": "insight",
            "_persona": "edge",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_memory_type_defaults_to_insight(self, db_session: AsyncSession):
        result = await _exec_remember_this(db_session, {
            "content": "Some observation",
            "memory_type": "nonexistent",
            "_persona": "edge",
        })
        assert result["stored"] is True
        assert result["memory_type"] == "insight"

    @pytest.mark.asyncio
    async def test_clamps_confidence(self, db_session: AsyncSession):
        result = await _exec_remember_this(db_session, {
            "content": "Observation",
            "memory_type": "pattern",
            "confidence": 1.5,
            "_persona": "edge",
        })
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_fallback_persona(self, db_session: AsyncSession):
        """Without _persona, defaults to edge."""
        result = await _exec_remember_this(db_session, {
            "content": "A memory without explicit persona",
            "memory_type": "insight",
        })
        assert result["stored"] is True
        memories = (await db_session.execute(select(AgentMemory))).scalars().all()
        assert memories[0].agent_name == "edge"


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


class TestRememberThisRegistry:
    def test_registered_for_all_personas(self):
        tool = TOOL_REGISTRY["remember_this"]
        expected = [
            "edge", "analyst", "thesis", "pm", "thesis_lord",
            "vol_slayer", "heston_cal", "deep_hedge", "post_mortem",
        ]
        for persona in expected:
            assert persona in tool.personas, f"remember_this missing for {persona}"

    def test_available_in_tool_defs(self):
        for persona in ["edge", "analyst", "thesis", "pm", "thesis_lord"]:
            tools = get_tools_for_persona(persona)
            tool_names = [t["name"] for t in tools]
            assert "remember_this" in tool_names, f"remember_this not in {persona} tools"


# ---------------------------------------------------------------------------
# Memory injection into prompt
# ---------------------------------------------------------------------------


class TestMemoryInjection:
    @pytest.mark.asyncio
    async def test_no_memories_returns_empty(self, db_session: AsyncSession):
        result = await inject_memories_into_prompt(db_session, "edge")
        assert result == ""

    @pytest.mark.asyncio
    async def test_own_memories_injected(self, db_session: AsyncSession):
        db_session.add(AgentMemory(
            agent_name="thesis_lord",
            memory_type="insight",
            content="Low-float small caps need tighter stops.",
            confidence=0.7,
        ))
        await db_session.flush()

        result = await inject_memories_into_prompt(db_session, "thesis_lord")
        assert "AGENT MEMORIES" in result
        assert "Low-float small caps" in result
        assert "INSIGHT" in result

    @pytest.mark.asyncio
    async def test_user_context_shared_across_agents(self, db_session: AsyncSession):
        """USER_CONTEXT memories from one agent should appear for another."""
        db_session.add(AgentMemory(
            agent_name="edge",
            memory_type="user_context",
            content="User is a Marine veteran with quantitative background.",
            confidence=0.9,
        ))
        await db_session.flush()

        # thesis_lord should see the user_context even though edge stored it
        result = await inject_memories_into_prompt(db_session, "thesis_lord")
        assert "Marine veteran" in result

    @pytest.mark.asyncio
    async def test_low_confidence_user_context_not_shared(self, db_session: AsyncSession):
        """USER_CONTEXT with confidence < 0.7 should not be shared cross-agent."""
        db_session.add(AgentMemory(
            agent_name="edge",
            memory_type="user_context",
            content="User might be interested in energy sector.",
            confidence=0.4,
        ))
        await db_session.flush()

        result = await inject_memories_into_prompt(db_session, "thesis_lord")
        assert result == ""  # Not shared because confidence < 0.7

    @pytest.mark.asyncio
    async def test_no_duplicate_shared_memories(self, db_session: AsyncSession):
        """If agent already owns the memory, don't show it twice."""
        db_session.add(AgentMemory(
            agent_name="edge",
            memory_type="user_context",
            content="Unique user context memory.",
            confidence=0.9,
        ))
        await db_session.flush()

        result = await inject_memories_into_prompt(db_session, "edge")
        assert result.count("Unique user context memory") == 1

    @pytest.mark.asyncio
    async def test_include_shared_false(self, db_session: AsyncSession):
        """Can disable cross-agent sharing."""
        db_session.add(AgentMemory(
            agent_name="edge",
            memory_type="user_context",
            content="Shared context.",
            confidence=0.9,
        ))
        await db_session.flush()

        result = await inject_memories_into_prompt(
            db_session, "thesis_lord", include_shared=False,
        )
        assert result == ""

    @pytest.mark.asyncio
    async def test_memory_icons(self, db_session: AsyncSession):
        """Each memory type should get its proper icon."""
        for mem_type, icon in [
            ("user_context", "👤"),
            ("teaching", "📚"),
            ("insight", "💡"),
            ("failure", "⚠️"),
        ]:
            db_session.add(AgentMemory(
                agent_name="edge",
                memory_type=mem_type,
                content=f"Test {mem_type}",
                confidence=0.8,
            ))
        await db_session.flush()

        result = await inject_memories_into_prompt(db_session, "edge")
        assert "👤" in result
        assert "📚" in result
        assert "💡" in result
        assert "⚠️" in result


# ---------------------------------------------------------------------------
# MemoryType enum
# ---------------------------------------------------------------------------


class TestMemoryTypeEnum:
    def test_new_types_exist(self):
        assert MemoryType.USER_CONTEXT.value == "user_context"
        assert MemoryType.TEACHING.value == "teaching"

    def test_all_types(self):
        values = {m.value for m in MemoryType}
        assert values == {
            "insight", "pattern", "failure", "success",
            "user_context", "teaching",
        }
