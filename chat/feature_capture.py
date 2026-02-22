"""
EdgeFinder — Feature Request Capture (PM Persona)

Persists feature requests from the PM persona's tool calls.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.models import FeatureRequest


async def save_feature_request(
    session: AsyncSession,
    title: str,
    user_story: str | None = None,
    acceptance_criteria: list[str] | None = None,
    priority: str = "medium",
    conversation_id: str | None = None,
) -> FeatureRequest:
    """Create and persist a FeatureRequest row."""
    fr = FeatureRequest(
        title=title,
        user_story=user_story,
        acceptance_criteria=acceptance_criteria,
        priority=priority,
        status="captured",
        conversation_id=conversation_id,
    )
    session.add(fr)
    await session.flush()
    return fr
