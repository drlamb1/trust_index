"""
EdgeFinder — News Sentiment Scorer (Phase 3)

Uses Claude Haiku via the Batches API to score news article sentiment
at scale with 50% cost discount vs standard API.

Sentiment scale: -1.0 (very bearish) to +1.0 (very bullish)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import NewsArticle

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
BATCH_POLL_INTERVAL = 30  # seconds between batch status checks
BATCH_MAX_WAIT = 1800  # 30 minutes max wait

_SENTIMENT_SYSTEM = (
    "You are a financial news sentiment classifier. "
    'Respond ONLY with valid JSON in the exact format: {"score": <float>} '
    "where score is between -1.0 (very bearish) and 1.0 (very bullish). "
    "Consider the impact on the company's stock price, not general market sentiment."
)

_SENTIMENT_PROMPT = (
    "Classify the sentiment of this financial news headline:\n\n{title}\n\n"
    'Respond only with JSON: {{"score": <float between -1.0 and 1.0>}}'
)


# ---------------------------------------------------------------------------
# Scoring result
# ---------------------------------------------------------------------------


@dataclass
class SentimentResult:
    article_id: int
    score: float
    model: str = HAIKU_MODEL


@dataclass
class SentimentSummary:
    """Rolling sentiment statistics for a single ticker."""

    ticker_id: int
    ma_3d: float | None = None
    ma_7d: float | None = None
    ma_30d: float | None = None
    article_count: int = 0
    divergence_signal: bool = False  # sentiment diverges from price action


# ---------------------------------------------------------------------------
# Batch API scoring
# ---------------------------------------------------------------------------


async def score_articles_batch(
    articles: list[NewsArticle],
    api_key: str,
) -> list[SentimentResult]:
    """
    Score a list of NewsArticle objects using Claude Haiku Batches API.
    Returns SentimentResult for each article that was successfully scored.
    """
    if not articles or not api_key:
        return []

    try:
        import anthropic  # type: ignore
    except ImportError:
        logger.error("anthropic package not installed")
        return []

    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Build batch requests
    requests = [
        {
            "custom_id": str(article.id),
            "params": {
                "model": HAIKU_MODEL,
                "max_tokens": 50,
                "system": _SENTIMENT_SYSTEM,
                "messages": [
                    {
                        "role": "user",
                        "content": _SENTIMENT_PROMPT.format(title=article.title[:500]),
                    }
                ],
            },
        }
        for article in articles
        if article.title
    ]

    if not requests:
        return []

    # Submit batch
    try:
        batch = await client.beta.messages.batches.create(requests=requests)
    except Exception as exc:
        logger.error("Failed to create sentiment batch: %s", exc)
        return []

    batch_id = batch.id
    logger.info("Submitted sentiment batch %s with %d requests", batch_id, len(requests))

    # Poll until done
    elapsed = 0
    while elapsed < BATCH_MAX_WAIT:
        await asyncio.sleep(BATCH_POLL_INTERVAL)
        elapsed += BATCH_POLL_INTERVAL
        try:
            batch = await client.beta.messages.batches.retrieve(batch_id)
        except Exception as exc:
            logger.warning("Batch poll error: %s", exc)
            continue
        if batch.processing_status == "ended":
            break
        logger.debug("Batch %s status: %s", batch_id, batch.processing_status)
    else:
        logger.warning("Batch %s timed out after %ds", batch_id, BATCH_MAX_WAIT)
        return []

    # Collect results
    results: list[SentimentResult] = []
    try:
        async for item in await client.beta.messages.batches.results(batch_id):
            if item.result.type != "succeeded":
                continue
            try:
                text = item.result.message.content[0].text
                data = json.loads(text)
                score = float(data["score"])
                score = max(-1.0, min(1.0, score))  # clamp
                results.append(SentimentResult(article_id=int(item.custom_id), score=score))
            except Exception as exc:
                logger.debug("Failed to parse sentiment result for %s: %s", item.custom_id, exc)
    except Exception as exc:
        logger.error("Error reading batch results for %s: %s", batch_id, exc)

    logger.info("Batch %s: scored %d/%d articles", batch_id, len(results), len(requests))
    return results


async def score_articles_direct(
    articles: list[NewsArticle],
    api_key: str,
    concurrency: int = 5,
) -> list[SentimentResult]:
    """
    Score articles using direct API calls (not batches).
    Useful for small batches or when Batches API is unavailable.
    Uses semaphore-limited concurrency.
    """
    if not articles or not api_key:
        return []

    try:
        import anthropic  # type: ignore
    except ImportError:
        logger.error("anthropic package not installed")
        return []

    client = anthropic.AsyncAnthropic(api_key=api_key)
    sem = asyncio.Semaphore(concurrency)

    async def _score_one(article: NewsArticle) -> SentimentResult | None:
        async with sem:
            try:
                resp = await client.messages.create(
                    model=HAIKU_MODEL,
                    max_tokens=50,
                    system=_SENTIMENT_SYSTEM,
                    messages=[
                        {
                            "role": "user",
                            "content": _SENTIMENT_PROMPT.format(title=article.title[:500]),
                        }
                    ],
                )
                text = resp.content[0].text
                data = json.loads(text)
                score = max(-1.0, min(1.0, float(data["score"])))
                return SentimentResult(article_id=article.id, score=score)
            except Exception as exc:
                logger.debug("Direct score error for article %s: %s", article.id, exc)
                return None

    tasks = [_score_one(a) for a in articles if a.title]
    raw = await asyncio.gather(*tasks)
    return [r for r in raw if r is not None]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def fetch_unscored_articles(
    session: AsyncSession,
    limit: int = 500,
) -> list[NewsArticle]:
    """Fetch articles that haven't been scored yet."""
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.sentiment_score.is_(None))
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def save_sentiment_scores(
    session: AsyncSession,
    results: list[SentimentResult],
) -> int:
    """Persist sentiment scores back to the news_articles table."""
    if not results:
        return 0

    now = datetime.now(UTC)
    score_map = {r.article_id: r.score for r in results}

    # Build model name map (per-article, since local model may differ)
    model_map = {r.article_id: r.model for r in results}

    # Bulk-update each article
    updated = 0
    for article_id, score in score_map.items():
        stmt = (
            update(NewsArticle)
            .where(NewsArticle.id == article_id)
            .values(
                sentiment_score=score,
                sentiment_scored_at=now,
                sentiment_model=model_map.get(article_id, HAIKU_MODEL),
            )
        )
        await session.execute(stmt)
        updated += 1

    await session.flush()
    return updated


# ---------------------------------------------------------------------------
# Rolling sentiment moving averages
# ---------------------------------------------------------------------------


async def compute_sentiment_summary(
    session: AsyncSession,
    ticker_id: int,
    price_return_7d: float | None = None,
) -> SentimentSummary:
    """
    Compute rolling sentiment MAs for a single ticker.

    Args:
        ticker_id: DB id of the ticker
        price_return_7d: 7-day price return (optional) for divergence detection
    """
    now = datetime.now(UTC)

    async def _avg(days: int) -> float | None:
        cutoff = now - timedelta(days=days)
        stmt = select(NewsArticle.sentiment_score).where(
            NewsArticle.ticker_ids.contains([ticker_id]),
            NewsArticle.sentiment_score.isnot(None),
            NewsArticle.published_at >= cutoff,
        )
        result = await session.execute(stmt)
        scores = [row[0] for row in result.fetchall() if row[0] is not None]
        if not scores:
            return None
        return sum(scores) / len(scores)

    ma_3 = await _avg(3)
    ma_7 = await _avg(7)
    ma_30 = await _avg(30)

    # Count total articles in last 30d
    cutoff_30 = now - timedelta(days=30)
    count_stmt = select(NewsArticle.id).where(
        NewsArticle.ticker_ids.contains([ticker_id]),
        NewsArticle.published_at >= cutoff_30,
    )
    count_result = await session.execute(count_stmt)
    article_count = len(count_result.fetchall())

    # Divergence: sentiment bearish but price rising, or vice versa
    divergence = False
    if ma_7 is not None and price_return_7d is not None:
        # Significant divergence: sentiment and price move in opposite directions
        if (ma_7 > 0.2 and price_return_7d < -0.03) or (ma_7 < -0.2 and price_return_7d > 0.03):
            divergence = True

    return SentimentSummary(
        ticker_id=ticker_id,
        ma_3d=ma_3,
        ma_7d=ma_7,
        ma_30d=ma_30,
        article_count=article_count,
        divergence_signal=divergence,
    )


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------


async def run_sentiment_pipeline(
    session: AsyncSession,
    api_key: str,
    limit: int = 500,
    use_batches: bool = True,
) -> int:
    """
    Full pipeline: fetch unscored articles → score → save.

    If use_local_sentiment_model is enabled in settings, tries the local
    ONNX FinBERT model first. Falls back to Haiku API if the model is
    unavailable or fails.

    Returns number of articles scored.
    """
    articles = await fetch_unscored_articles(session, limit=limit)
    if not articles:
        logger.info("No unscored articles found")
        return 0

    logger.info("Scoring %d articles", len(articles))

    # Try local ML model first if enabled
    from config.settings import settings

    if settings.use_local_sentiment_model:
        results = _score_with_local_model(articles)
        if results:
            saved = await save_sentiment_scores(session, results)
            logger.info("Saved %d sentiment scores via local model", saved)
            return saved
        logger.warning("Local sentiment model unavailable, falling back to Haiku API")

    # Haiku API path (existing behavior)
    if use_batches and len(articles) >= 10:
        results = await score_articles_batch(articles, api_key)
    else:
        results = await score_articles_direct(articles, api_key)

    saved = await save_sentiment_scores(session, results)
    logger.info("Saved %d sentiment scores", saved)
    return saved


def _score_with_local_model(articles: list[NewsArticle]) -> list[SentimentResult]:
    """Score articles using the local ONNX FinBERT model.

    Returns empty list if model is not available (triggers fallback).
    """
    try:
        from ml.sentiment.inference import predict_sentiment_batch
    except ImportError:
        return []

    titles = []
    ids = []
    for a in articles:
        if a.title:
            titles.append(a.title[:500])
            ids.append(a.id)

    if not titles:
        return []

    scores = predict_sentiment_batch(titles)
    if not scores or all(s is None for s in scores):
        return []

    results = []
    for article_id, score in zip(ids, scores):
        if score is not None:
            results.append(
                SentimentResult(
                    article_id=article_id,
                    score=score,
                    model="finbert-edgefinder",
                )
            )

    return results
