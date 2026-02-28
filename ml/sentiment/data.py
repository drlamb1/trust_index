"""Training data extraction for sentiment model."""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import NewsArticle

logger = logging.getLogger(__name__)


async def extract_sentiment_training_data(session: AsyncSession) -> pd.DataFrame:
    """Extract (title, haiku_score, price_move_1d) from news_articles.

    Filters: must have sentiment_score, price_move_1d, title >= 10 chars.
    Ordered by published_at ascending for time-based splitting.
    """
    result = await session.execute(
        select(
            NewsArticle.title,
            NewsArticle.sentiment_score,
            NewsArticle.price_move_1d,
            NewsArticle.price_move_5d,
            NewsArticle.published_at,
        ).where(
            NewsArticle.sentiment_score.is_not(None),
            NewsArticle.price_move_1d.is_not(None),
            func.length(NewsArticle.title) >= 10,
        ).order_by(NewsArticle.published_at.asc())
    )
    rows = result.all()
    logger.info("Extracted %d labelled news rows for sentiment training", len(rows))
    return pd.DataFrame(
        rows,
        columns=["title", "haiku_score", "price_move_1d", "price_move_5d", "published_at"],
    )
