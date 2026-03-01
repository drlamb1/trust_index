"""Tests for Edger daily briefing synthesis and prompt rewrites."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat.personas import PERSONAS
from core.models import AgentMemory, DailyBriefing, SimulationLog


# ---------------------------------------------------------------------------
# Prompt rewrite tests
# ---------------------------------------------------------------------------


class TestEdgerPromptRewrite:
    def test_edger_has_connective_tissue_language(self):
        prompt = PERSONAS["edge"].system_prompt
        assert "connective tissue" in prompt

    def test_edger_has_daily_briefing_identity(self):
        prompt = PERSONAS["edge"].system_prompt
        assert "daily briefing" in prompt
        assert "heartbeat" in prompt

    def test_edger_meet_people_where_they_are(self):
        prompt = PERSONAS["edge"].system_prompt
        assert "meet people where they are" in prompt.lower()
        assert "ELI5, always" not in prompt

    def test_edger_record_lesson_enforced(self):
        prompt = PERSONAS["edge"].system_prompt
        assert "not optional" in prompt.lower()

    def test_edger_she_her(self):
        prompt = PERSONAS["edge"].system_prompt
        assert "You use she/her. You have the room." in prompt

    def test_edger_has_generate_full_briefing_tool(self):
        tools = PERSONAS["edge"].tools
        assert "generate_full_briefing" in tools

    def test_edger_tool_count(self):
        """Edge should have 23 tools (22 original + generate_full_briefing)."""
        assert len(PERSONAS["edge"].tools) == 23


class TestPMPromptRewrite:
    def test_pm_self_audit_trigger(self):
        prompt = PERSONAS["pm"].system_prompt
        # Line-wrapped in prompt, so check without the newline
        assert "did you do the thing, or did you describe doing" in prompt

    def test_pm_narration_is_not_execution(self):
        prompt = PERSONAS["pm"].system_prompt
        assert "Narration is not execution" in prompt

    def test_pm_implicit_promise(self):
        prompt = PERSONAS["pm"].system_prompt
        assert "A promise made in another room is still a promise" in prompt

    def test_pm_treasure_island_subordinated(self):
        prompt = PERSONAS["pm"].system_prompt
        assert "metaphor serves the principles" in prompt

    def test_pm_say_no(self):
        prompt = PERSONAS["pm"].system_prompt
        assert "Say no. Clearly." in prompt

    def test_pm_minimal_emoji(self):
        prompt = PERSONAS["pm"].system_prompt
        assert "Minimal\nemoji" in prompt or "Minimal emoji" in prompt

    def test_pm_she_her(self):
        prompt = PERSONAS["pm"].system_prompt
        assert "You use she/her. You have the helm." in prompt

    def test_pm_tool_count_unchanged(self):
        """PM should still have 11 tools."""
        assert len(PERSONAS["pm"].tools) == 11


# ---------------------------------------------------------------------------
# Briefing synthesis tests
# ---------------------------------------------------------------------------


SAMPLE_BRIEFING_MD = """
# EdgeFinder Daily Briefing — Feb 28, 2026

## Market Overview
SPY: $502.30 (+0.8%), VIX: 18.2 (-5.1%)

## Top Movers
NVDA +3.2%, AAPL -1.1%

## Alerts
RSI oversold: SMR (RSI 28.5)

## Technical Signals
Golden cross: MSFT (SMA50 crossed above SMA200)
"""


@pytest.mark.asyncio
async def test_synthesize_briefing_calls_claude(db_session, mock_anthropic):
    """Synthesis function should call Claude with Edger's system prompt."""
    from daily_briefing import synthesize_briefing_with_edger

    synthesis, lesson = await synthesize_briefing_with_edger(
        SAMPLE_BRIEFING_MD, db_session
    )

    # Claude was called
    mock_anthropic.messages.create.assert_called_once()
    call_kwargs = mock_anthropic.messages.create.call_args.kwargs

    # Used Edger's system prompt
    assert "You are The Edger" in call_kwargs["system"]

    # Used sonnet
    assert call_kwargs["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_synthesize_briefing_records_lesson(db_session, mock_anthropic):
    """Synthesis should record a lesson_taught in agent_memories."""
    from daily_briefing import synthesize_briefing_with_edger

    synthesis, lesson = await synthesize_briefing_with_edger(
        SAMPLE_BRIEFING_MD, db_session
    )

    # A lesson should be returned
    assert lesson is not None

    # Check it was persisted to agent_memories
    result = await db_session.execute(
        select(AgentMemory).where(
            AgentMemory.agent_name == "edge",
            AgentMemory.memory_type == "lesson_taught",
        )
    )
    memories = result.scalars().all()
    assert len(memories) == 1
    assert memories[0].content == lesson
    assert memories[0].evidence["source"] == "daily_briefing"


@pytest.mark.asyncio
async def test_synthesize_briefing_skips_without_api_key(db_session, monkeypatch):
    """Without an API key, synthesis should return empty gracefully."""
    monkeypatch.setattr(
        "config.settings.settings",
        type("S", (), {"has_anthropic": False, "anthropic_api_key": ""})(),
    )
    from daily_briefing import synthesize_briefing_with_edger

    synthesis, lesson = await synthesize_briefing_with_edger(
        SAMPLE_BRIEFING_MD, db_session
    )
    assert synthesis == ""
    assert lesson is None


@pytest.mark.asyncio
async def test_pick_briefing_concept_skips_taught(db_session):
    """_pick_briefing_concept should skip already-taught concepts."""
    from daily_briefing import _pick_briefing_concept

    # Teach the first concept
    db_session.add(AgentMemory(
        agent_name="edge",
        memory_type="lesson_taught",
        content="sortino_ratio",
        confidence=1.0,
    ))
    await db_session.flush()

    concept = await _pick_briefing_concept(db_session)
    assert concept is not None
    assert concept[0] != "sortino_ratio"


# ---------------------------------------------------------------------------
# DailyBriefing model tests
# ---------------------------------------------------------------------------


class TestDailyBriefingModel:
    @pytest.mark.asyncio
    async def test_edger_synthesis_column_exists(self, db_session):
        briefing = DailyBriefing(
            date=date(2026, 3, 1),
            content_md="# Test",
            edger_synthesis="This is the Edger's take.",
            lesson_taught="sharpe_ratio",
        )
        db_session.add(briefing)
        await db_session.flush()

        result = await db_session.execute(
            select(DailyBriefing).where(DailyBriefing.date == date(2026, 3, 1))
        )
        row = result.scalar_one()
        assert row.edger_synthesis == "This is the Edger's take."
        assert row.lesson_taught == "sharpe_ratio"
