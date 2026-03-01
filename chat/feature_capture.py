"""
EdgeFinder — Feature Request Capture (PM Persona)

Persists feature requests from the PM persona's tool calls.
"""

from __future__ import annotations

from sqlalchemy import select
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


async def update_feature_request(
    session: AsyncSession,
    feature_id: int,
    *,
    status: str | None = None,
    priority: str | None = None,
    title: str | None = None,
    user_story: str | None = None,
    tags: list[str] | None = None,
) -> FeatureRequest | None:
    """Update an existing FeatureRequest. Returns None if not found."""
    result = await session.execute(
        select(FeatureRequest).where(FeatureRequest.id == feature_id)
    )
    fr = result.scalar_one_or_none()
    if fr is None:
        return None
    if status is not None:
        fr.status = status
    if priority is not None:
        fr.priority = priority
    if title is not None:
        fr.title = title
    if user_story is not None:
        fr.user_story = user_story
    if tags is not None:
        fr.tags = tags
    await session.flush()
    return fr
