"""
Unit tests for analysis/sentiment.py

Tests cover batch/direct scoring (mocked Claude), DB operations,
and sentiment summary computation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.sentiment import (
    HAIKU_MODEL,
    SentimentResult,
    fetch_unscored_articles,
    run_sentiment_pipeline,
    save_sentiment_scores,
    score_articles_direct,
)
from core.models import NewsArticle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_article(
    session,
    title: str = "Test Article",
    url: str | None = None,
    sentiment_score=None,
) -> NewsArticle:
    """Create a NewsArticle ORM object (not yet flushed)."""
    import hashlib

    url = url or f"http://test.com/{title[:10].replace(' ', '-')}"
    h = hashlib.sha256(f"{url}|{title}".encode()).hexdigest()
    return NewsArticle(
        ticker_ids=[],
        source_tier=3,
        title=title,
        url=url,
        published_at=datetime.now(UTC),
        summary="",
        raw_content_hash=h,
        sentiment_score=sentiment_score,
    )


# ---------------------------------------------------------------------------
# SentimentResult dataclass
# ---------------------------------------------------------------------------


class TestSentimentResult:
    def test_fields(self):
        r = SentimentResult(article_id=42, score=0.75)
        assert r.article_id == 42
        assert r.score == 0.75
        assert r.model == HAIKU_MODEL


# ---------------------------------------------------------------------------
# score_articles_direct (mocked Claude)
# ---------------------------------------------------------------------------


class TestScoreArticlesDirect:
    @pytest.mark.asyncio
    async def test_returns_empty_without_api_key(self):
        result = await score_articles_direct([], api_key="")
        assert result == []

    @pytest.mark.asyncio
    async def test_scores_articles_via_direct_api(self, db_session: AsyncSession):
        """Mocked Claude returns JSON score."""
        for i in range(3):
            art = _make_article(db_session, title=f"Article {i}", url=f"http://test.com/{i}")
            db_session.add(art)
        await db_session.flush()
        # Query back to get IDs
        from sqlalchemy import select

        result = await db_session.execute(
            select(NewsArticle).where(NewsArticle.url.like("http://test.com/%"))
        )
        db_articles = result.scalars().all()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"score": 0.65}')]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            results = await score_articles_direct(
                db_articles, api_key="test-key"
            )  # pragma: allowlist secret

        assert len(results) == len(db_articles)
        for r in results:
            assert isinstance(r, SentimentResult)
            assert r.score == pytest.approx(0.65)

    @pytest.mark.asyncio
    async def test_scores_clamped_to_minus_one_plus_one(self, db_session: AsyncSession):
        """Scores outside [-1, 1] should be clamped."""
        art = _make_article(db_session, "Test Title", "http://test.com/clamp")
        db_session.add(art)
        await db_session.flush()
        await db_session.refresh(art)

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"score": 5.0}')]  # out of range
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            results = await score_articles_direct(
                [art], api_key="test-key"
            )  # pragma: allowlist secret

        assert len(results) == 1
        assert results[0].score == pytest.approx(1.0)  # clamped to 1.0

    @pytest.mark.asyncio
    async def test_invalid_json_skipped_gracefully(self, db_session: AsyncSession):
        """If Claude returns invalid JSON, that article is skipped."""
        art = _make_article(db_session, "Bad Response", "http://test.com/bad")
        db_session.add(art)
        await db_session.flush()
        await db_session.refresh(art)

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not valid json")]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            results = await score_articles_direct(
                [art], api_key="test-key"
            )  # pragma: allowlist secret

        assert results == []

    @pytest.mark.asyncio
    async def test_empty_articles_list_returns_empty(self):
        results = await score_articles_direct([], api_key="test-key")  # pragma: allowlist secret
        assert results == []


# ---------------------------------------------------------------------------
# fetch_unscored_articles
# ---------------------------------------------------------------------------


class TestFetchUnscoredArticles:
    @pytest.mark.asyncio
    async def test_returns_articles_with_null_score(self, db_session: AsyncSession):
        art1 = _make_article(db_session, "Unscored 1", "http://test.com/u1")
        art2 = _make_article(db_session, "Unscored 2", "http://test.com/u2")
        art3 = _make_article(db_session, "Scored", "http://test.com/s1", sentiment_score=0.5)
        for a in [art1, art2, art3]:
            db_session.add(a)
        await db_session.flush()

        results = await fetch_unscored_articles(db_session, limit=100)
        urls = [r.url for r in results]
        assert "http://test.com/u1" in urls
        assert "http://test.com/u2" in urls
        assert "http://test.com/s1" not in urls

    @pytest.mark.asyncio
    async def test_respects_limit(self, db_session: AsyncSession):
        for i in range(10):
            art = _make_article(db_session, f"Article {i}", f"http://test.com/{i}")
            db_session.add(art)
        await db_session.flush()

        results = await fetch_unscored_articles(db_session, limit=5)
        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, db_session: AsyncSession):
        results = await fetch_unscored_articles(db_session)
        assert results == []


# ---------------------------------------------------------------------------
# save_sentiment_scores
# ---------------------------------------------------------------------------


class TestSaveSentimentScores:
    @pytest.mark.asyncio
    async def test_saves_scores_to_db(self, db_session: AsyncSession):
        art = _make_article(db_session, "Test Save", "http://test.com/save")
        db_session.add(art)
        await db_session.flush()
        await db_session.refresh(art)
        art_id = art.id

        results = [SentimentResult(article_id=art_id, score=0.42)]
        count = await save_sentiment_scores(db_session, results)
        assert count == 1

        # Verify DB was updated
        from sqlalchemy import select

        result = await db_session.execute(select(NewsArticle).where(NewsArticle.id == art_id))
        updated = result.scalar_one()
        assert updated.sentiment_score == pytest.approx(0.42)
        assert updated.sentiment_model == HAIKU_MODEL
        assert updated.sentiment_scored_at is not None

    @pytest.mark.asyncio
    async def test_empty_results_returns_zero(self, db_session: AsyncSession):
        count = await save_sentiment_scores(db_session, [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_multiple_scores_saved(self, db_session: AsyncSession):
        articles = []
        for i in range(3):
            art = _make_article(db_session, f"Art {i}", f"http://test.com/m{i}")
            db_session.add(art)
            articles.append(art)
        await db_session.flush()
        for art in articles:
            await db_session.refresh(art)

        results = [
            SentimentResult(article_id=articles[0].id, score=0.8),
            SentimentResult(article_id=articles[1].id, score=-0.3),
            SentimentResult(article_id=articles[2].id, score=0.1),
        ]
        count = await save_sentiment_scores(db_session, results)
        assert count == 3


# ---------------------------------------------------------------------------
# run_sentiment_pipeline (integration)
# ---------------------------------------------------------------------------


class TestRunSentimentPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_with_no_articles(self, db_session: AsyncSession):
        count = await run_sentiment_pipeline(
            db_session, api_key="test-key"
        )  # pragma: allowlist secret
        assert count == 0

    @pytest.mark.asyncio
    async def test_pipeline_with_mock_claude(self, db_session: AsyncSession):
        """Full pipeline: insert unscored → score → save."""
        for i in range(5):
            art = _make_article(db_session, f"Pipeline Art {i}", f"http://test.com/pipe{i}")
            db_session.add(art)
        await db_session.flush()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"score": 0.5}')]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            count = await run_sentiment_pipeline(
                db_session, api_key="test-key", limit=10, use_batches=False
            )

        assert count == 5

    @pytest.mark.asyncio
    async def test_pipeline_skips_already_scored(self, db_session: AsyncSession):
        """Articles already scored should not be re-scored."""
        art = _make_article(
            db_session, "Already Scored", "http://test.com/done", sentiment_score=0.9
        )
        db_session.add(art)
        await db_session.flush()

        count = await run_sentiment_pipeline(
            db_session, api_key="test-key"
        )  # pragma: allowlist secret
        assert count == 0  # Nothing to score
