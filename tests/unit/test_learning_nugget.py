"""Tests for the learning nugget tools (get_learning_nugget + record_lesson_taught)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from chat.tools import _exec_get_learning_nugget, _exec_record_lesson_taught, TOOL_REGISTRY
from core.models import AgentMemory


class TestGetLearningNugget:
    @pytest.mark.asyncio
    async def test_returns_concept(self, db_session: AsyncSession):
        result = await _exec_get_learning_nugget(db_session, {})
        assert "concept_id" in result
        assert "concept_name" in result
        assert "one_liner" in result
        assert "difficulty" in result
        assert result["already_taught_count"] == 0
        assert result["concepts_remaining"] > 0

    @pytest.mark.asyncio
    async def test_filters_taught_concepts(self, db_session: AsyncSession):
        # Record the first concept as taught
        first_result = await _exec_get_learning_nugget(db_session, {})
        first_id = first_result["concept_id"]

        # Mark it as taught
        db_session.add(AgentMemory(
            agent_name="edge",
            memory_type="lesson_taught",
            content=first_id,
            confidence=1.0,
        ))
        await db_session.flush()

        # Next nugget should be different
        second_result = await _exec_get_learning_nugget(db_session, {})
        assert second_result["concept_id"] != first_id
        assert second_result["already_taught_count"] == 1


class TestRecordLessonTaught:
    @pytest.mark.asyncio
    async def test_records_memory(self, db_session: AsyncSession):
        result = await _exec_record_lesson_taught(db_session, {
            "concept_id": "sortino_ratio",
            "summary": "Explained Sortino using RKLB backtest data",
        })
        assert result["recorded"] is True
        assert result["concept_id"] == "sortino_ratio"

    @pytest.mark.asyncio
    async def test_requires_concept_id(self, db_session: AsyncSession):
        result = await _exec_record_lesson_taught(db_session, {})
        assert "error" in result


class TestToolRegistry:
    def test_learning_nugget_registered(self):
        assert "get_learning_nugget" in TOOL_REGISTRY
        assert "edge" in TOOL_REGISTRY["get_learning_nugget"].personas

    def test_record_lesson_registered(self):
        assert "record_lesson_taught" in TOOL_REGISTRY
        assert "edge" in TOOL_REGISTRY["record_lesson_taught"].personas

    def test_edge_tools_all_exist_in_registry(self):
        """Every tool in Edge's tool list must exist in the registry."""
        from chat.personas import PERSONAS
        edge_tools = PERSONAS["edge"].tools
        for tool_name in edge_tools:
            assert tool_name in TOOL_REGISTRY, f"Tool '{tool_name}' in Edge's list but not in TOOL_REGISTRY"
            assert "edge" in TOOL_REGISTRY[tool_name].personas, f"Tool '{tool_name}' missing 'edge' in personas"

    def test_suggest_handoff_has_all_nine_personas(self):
        """suggest_handoff should list all 9 personas in its enum."""
        schema = TOOL_REGISTRY["suggest_handoff"].input_schema
        enum_values = set(schema["properties"]["target_persona"]["enum"])
        expected = {"edge", "analyst", "thesis", "pm", "thesis_lord", "vol_slayer", "heston_cal", "deep_hedge", "post_mortem"}
        assert enum_values == expected

    def test_conversation_summaries_registered(self):
        assert "get_conversation_summaries" in TOOL_REGISTRY
        assert "edge" in TOOL_REGISTRY["get_conversation_summaries"].personas
        assert "post_mortem" in TOOL_REGISTRY["get_conversation_summaries"].personas

    def test_thesis_tools_all_exist_in_registry(self):
        """Every tool in Thesis Genius's list must exist in the registry."""
        from chat.personas import PERSONAS
        thesis_tools = PERSONAS["thesis"].tools
        for tool_name in thesis_tools:
            assert tool_name in TOOL_REGISTRY, f"Tool '{tool_name}' in Thesis's list but not in TOOL_REGISTRY"
            assert "thesis" in TOOL_REGISTRY[tool_name].personas, f"Tool '{tool_name}' missing 'thesis' in personas"
