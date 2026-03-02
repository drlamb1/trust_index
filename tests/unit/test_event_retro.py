"""Tests for event-driven retrospectives (run_event_retro)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import AgentMemory, SimulatedThesis, SimulationLog
from simulation.memory import run_event_retro


def _mock_retro_response(json_text: str):
    """Create a mock Anthropic response with the given JSON text."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json_text)]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


@pytest_asyncio.fixture
async def thesis_ids(db_session: AsyncSession) -> list[int]:
    """Create several SimulatedThesis records for FK references."""
    ids = []
    for i in range(1, 6):
        thesis = SimulatedThesis(
            name=f"Test Thesis {i}",
            thesis_text=f"A test thesis #{i} for event retro testing.",
            generated_by="thesis_lord",
            status="proposed",
        )
        db_session.add(thesis)
    await db_session.flush()
    result = await db_session.execute(
        select(SimulatedThesis).order_by(SimulatedThesis.id)
    )
    for t in result.scalars().all():
        ids.append(t.id)
    return ids


class TestRunEventRetro:
    @pytest.mark.asyncio
    async def test_no_events_returns_zero(self, db_session: AsyncSession):
        """No events for thesis_id means nothing to review."""
        count = await run_event_retro(db_session, thesis_id=999, api_key="fake")
        assert count == 0

    @pytest.mark.asyncio
    async def test_extracts_memories_from_lifecycle(self, db_session: AsyncSession, thesis_ids: list[int]):
        """Given a thesis lifecycle in simulation_logs, should extract memories."""
        tid = thesis_ids[0]
        db_session.add(SimulationLog(
            thesis_id=tid,
            agent_name="thesis_lord",
            event_type="generation",
            event_data={"thesis_name": "NVDA Momentum Play", "model_used": "sonnet"},
        ))
        db_session.add(SimulationLog(
            thesis_id=tid,
            agent_name="thesis_lord",
            event_type="backtest_complete",
            event_data={"outcome": "killed", "reason": "Sharpe -0.3 ≤ 0", "sharpe": -0.3, "win_rate": 0.35},
        ))
        await db_session.flush()

        mock_client = _mock_retro_response(
            '[{"type": "failure", "content": "Momentum-only theses without fundamental confirmation have negative Sharpe.", "confidence": 0.6}]'
        )

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            count = await run_event_retro(db_session, thesis_id=tid, api_key="fake-key")

        assert count == 1

        memories = (await db_session.execute(
            select(AgentMemory).where(AgentMemory.agent_name == "thesis_lord")
        )).scalars().all()
        assert len(memories) == 1
        assert memories[0].memory_type == "failure"
        assert "Momentum" in memories[0].content
        assert memories[0].evidence["source"] == "event_retro"
        assert memories[0].evidence["thesis_id"] == tid

    @pytest.mark.asyncio
    async def test_attributes_to_generating_agent(self, db_session: AsyncSession, thesis_ids: list[int]):
        """Memories should be attributed to the agent that generated the thesis."""
        tid = thesis_ids[1]
        db_session.add(SimulationLog(
            thesis_id=tid,
            agent_name="custom_agent",
            event_type="generation",
            event_data={"thesis_name": "Test"},
        ))
        db_session.add(SimulationLog(
            thesis_id=tid,
            agent_name="thesis_lord",
            event_type="backtest_complete",
            event_data={"outcome": "paper_live", "sharpe": 1.2},
        ))
        await db_session.flush()

        mock_client = _mock_retro_response(
            '[{"type": "success", "content": "Lesson from custom agent.", "confidence": 0.7}]'
        )

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            await run_event_retro(db_session, thesis_id=tid, api_key="fake")

        memories = (await db_session.execute(
            select(AgentMemory).where(AgentMemory.agent_name == "custom_agent")
        )).scalars().all()
        assert len(memories) == 1

    @pytest.mark.asyncio
    async def test_logs_post_mortem_event(self, db_session: AsyncSession, thesis_ids: list[int]):
        """Should write a POST_MORTEM event to simulation_logs."""
        tid = thesis_ids[2]
        db_session.add(SimulationLog(
            thesis_id=tid,
            agent_name="thesis_lord",
            event_type="generation",
            event_data={"thesis_name": "Test"},
        ))
        await db_session.flush()

        mock_client = _mock_retro_response(
            '[{"type": "insight", "content": "A lesson.", "confidence": 0.5}]'
        )

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            await run_event_retro(db_session, thesis_id=tid, api_key="fake")

        logs = (await db_session.execute(
            select(SimulationLog).where(
                SimulationLog.event_type == "post_mortem",
                SimulationLog.thesis_id == tid,
            )
        )).scalars().all()
        assert len(logs) == 1
        assert logs[0].event_data["trigger"] == "event_retro"

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self, db_session: AsyncSession, thesis_ids: list[int]):
        """API failure should return 0, not crash."""
        tid = thesis_ids[3]
        db_session.add(SimulationLog(
            thesis_id=tid,
            agent_name="thesis_lord",
            event_type="generation",
            event_data={"thesis_name": "Test"},
        ))
        await db_session.flush()

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            count = await run_event_retro(db_session, thesis_id=tid, api_key="fake")

        assert count == 0

    @pytest.mark.asyncio
    async def test_defaults_agent_to_thesis_lord(self, db_session: AsyncSession, thesis_ids: list[int]):
        """If no GENERATION event, default to thesis_lord."""
        tid = thesis_ids[4]
        db_session.add(SimulationLog(
            thesis_id=tid,
            agent_name="lifecycle_review",
            event_type="retirement",
            event_data={"reason": "Time horizon expired"},
        ))
        await db_session.flush()

        mock_client = _mock_retro_response(
            '[{"type": "insight", "content": "Lesson.", "confidence": 0.5}]'
        )

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            await run_event_retro(db_session, thesis_id=tid, api_key="fake")

        memories = (await db_session.execute(
            select(AgentMemory).where(AgentMemory.agent_name == "thesis_lord")
        )).scalars().all()
        assert len(memories) == 1
