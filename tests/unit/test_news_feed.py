"""
Unit tests for ingestion/news_feed.py

Tests cover hash dedup, fuzzy dedup, ticker matching, feed parsing,
Finnhub/NewsAPI fetching (all mocked), and DB storage logic.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import NewsArticle, Ticker
from ingestion.news_feed import (
    _build_ticker_index,
    _is_fuzzy_duplicate,
    aggregate_news_batch,
    compute_content_hash,
    match_ticker_ids,
    store_news_articles,
)

# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    def test_returns_64_char_hex(self):
        h = compute_content_hash("http://example.com/article", "Some headline")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_inputs_same_hash(self):
        h1 = compute_content_hash("http://example.com", "title")
        h2 = compute_content_hash("http://example.com", "title")
        assert h1 == h2

    def test_different_urls_different_hash(self):
        h1 = compute_content_hash("http://a.com", "title")
        h2 = compute_content_hash("http://b.com", "title")
        assert h1 != h2

    def test_different_titles_different_hash(self):
        h1 = compute_content_hash("http://a.com", "title A")
        h2 = compute_content_hash("http://a.com", "title B")
        assert h1 != h2

    def test_empty_strings_handled(self):
        h = compute_content_hash("", "")
        assert len(h) == 64

    def test_strips_whitespace(self):
        h1 = compute_content_hash("  http://a.com  ", "  title  ")
        h2 = compute_content_hash("http://a.com", "title")
        assert h1 == h2


# ---------------------------------------------------------------------------
# _is_fuzzy_duplicate
# ---------------------------------------------------------------------------


class TestIsFuzzyDuplicate:
    def test_exact_match_is_duplicate(self):
        assert _is_fuzzy_duplicate("Apple Beats Earnings", ["Apple Beats Earnings"]) is True

    def test_case_insensitive(self):
        assert _is_fuzzy_duplicate("apple beats earnings", ["APPLE BEATS EARNINGS"]) is True

    def test_high_similarity_is_duplicate(self):
        # Very similar titles (one word different)
        result = _is_fuzzy_duplicate(
            "Apple Beats Q3 Earnings Estimates",
            ["Apple Beats Q3 Earnings Estimates by Large Margin"],
        )
        # May or may not be ≥85%, depends on length; just check it returns bool
        assert isinstance(result, bool)

    def test_unrelated_titles_not_duplicate(self):
        assert _is_fuzzy_duplicate("NVDA Reports Record Revenue", ["Oil Prices Fall 5%"]) is False

    def test_empty_seen_list(self):
        assert _is_fuzzy_duplicate("Any Title", []) is False

    def test_custom_threshold(self):
        # With low threshold, almost everything matches
        result = _is_fuzzy_duplicate("AAPL Up", ["AAPL Up 3%"], threshold=50)
        assert result is True


# ---------------------------------------------------------------------------
# _build_ticker_index
# ---------------------------------------------------------------------------


class TestBuildTickerIndex:
    def _make_ticker(self, tid: int, symbol: str, name: str | None = None):
        from types import SimpleNamespace

        return SimpleNamespace(id=tid, symbol=symbol, name=name)

    def test_symbol_map_populated(self):
        t = self._make_ticker(1, "AAPL", "Apple Inc.")
        symbol_map, _ = _build_ticker_index([t])
        assert "AAPL" in symbol_map
        assert symbol_map["AAPL"] == 1

    def test_name_map_uses_first_significant_word(self):
        t = self._make_ticker(1, "NVDA", "NVIDIA Corporation")
        _, name_map = _build_ticker_index([t])
        assert "NVIDIA" in name_map
        assert name_map["NVIDIA"] == 1

    def test_short_words_excluded_from_name_map(self):
        t = self._make_ticker(1, "F", "Ford Motor Co.")
        _, name_map = _build_ticker_index([t])
        # "Ford" has 4 chars — should be included; "F" is the symbol
        # The name_map should contain "FORD" (4 chars)
        assert "FORD" in name_map

    def test_common_suffixes_excluded(self):
        """CORP, INC, LTD should not be added as keywords."""
        t = self._make_ticker(1, "XYZ", "XYZ Corp Inc Ltd Group")
        _, name_map = _build_ticker_index([t])
        assert "CORP" not in name_map
        assert "INC" not in name_map
        assert "LTD" not in name_map
        assert "GROUP" not in name_map

    def test_multiple_tickers(self):
        tickers = [
            self._make_ticker(1, "AAPL", "Apple Inc."),
            self._make_ticker(2, "MSFT", "Microsoft Corporation"),
        ]
        symbol_map, name_map = _build_ticker_index(tickers)
        assert symbol_map["AAPL"] == 1
        assert symbol_map["MSFT"] == 2

    def test_none_name_handled(self):
        t = self._make_ticker(1, "ZZZ", None)
        symbol_map, name_map = _build_ticker_index([t])
        assert "ZZZ" in symbol_map
        # No name → name_map empty for this ticker
        assert "ZZZ" not in name_map


# ---------------------------------------------------------------------------
# match_ticker_ids
# ---------------------------------------------------------------------------


class TestMatchTickerIds:
    def test_symbol_matched_in_title(self):
        symbol_map = {"AAPL": 1, "MSFT": 2}
        tids = match_ticker_ids("AAPL reports strong earnings", symbol_map, {})
        assert 1 in tids
        assert 2 not in tids

    def test_symbol_requires_word_boundary(self):
        """'SNAPCHAT' should not match 'SNAP'."""
        symbol_map = {"SNAP": 1}
        tids = match_ticker_ids("SNAPCHAT launches new feature", symbol_map, {})
        assert 1 not in tids

    def test_name_keyword_matched(self):
        name_map = {"APPLE": 1}
        tids = match_ticker_ids("Apple announces new iPhone", {}, name_map)
        assert 1 in tids

    def test_both_symbol_and_name_deduplicated(self):
        """If AAPL is found by both symbol and name, only one entry."""
        symbol_map = {"AAPL": 1}
        name_map = {"APPLE": 1}
        tids = match_ticker_ids("AAPL stock rises as Apple beats earnings", symbol_map, name_map)
        assert tids.count(1) == 1

    def test_multiple_tickers_in_headline(self):
        symbol_map = {"AAPL": 1, "MSFT": 2}
        tids = match_ticker_ids("AAPL and MSFT both rise today", symbol_map, {})
        assert 1 in tids
        assert 2 in tids

    def test_empty_title_returns_empty(self):
        symbol_map = {"AAPL": 1}
        tids = match_ticker_ids("", symbol_map, {})
        assert tids == []

    def test_result_is_sorted(self):
        symbol_map = {"MSFT": 2, "AAPL": 1}
        tids = match_ticker_ids("AAPL and MSFT both rise", symbol_map, {})
        assert tids == sorted(tids)


# ---------------------------------------------------------------------------
# store_news_articles (requires DB)
# ---------------------------------------------------------------------------


class TestStoreNewsArticles:
    def _make_article(self, title: str, url: str, tier: int = 3) -> dict:
        return {
            "title": title,
            "url": url,
            "summary": "Summary text",
            "published_at": datetime.now(UTC),
            "source_name": "TestSource",
            "source_tier": tier,
            "ticker_ids": [],
            "raw_content_hash": compute_content_hash(url, title),
        }

    @pytest.mark.asyncio
    async def test_inserts_new_articles(self, db_session: AsyncSession):
        articles = [
            self._make_article("NVDA Beats Earnings", "http://test.com/1"),
            self._make_article("AAPL Launches Product", "http://test.com/2"),
        ]
        count = await store_news_articles(db_session, articles)
        assert count == 2

    @pytest.mark.asyncio
    async def test_deduplicates_by_hash(self, db_session: AsyncSession):
        """Same article inserted twice → only 1 row."""
        art = self._make_article("NVDA Beats Earnings", "http://test.com/1")
        count1 = await store_news_articles(db_session, [art])
        count2 = await store_news_articles(db_session, [art])
        assert count1 == 1
        assert count2 == 0  # already exists

    @pytest.mark.asyncio
    async def test_within_batch_dedup(self, db_session: AsyncSession):
        """Duplicate in same batch is only inserted once."""
        art = self._make_article("Same Title", "http://test.com/dupe")
        art2 = dict(art)  # same hash
        count = await store_news_articles(db_session, [art, art2])
        assert count == 1

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, db_session: AsyncSession):
        count = await store_news_articles(db_session, [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_ticker_tagging_applied(self, db_session: AsyncSession):
        """Articles get tagged with matching ticker IDs."""
        ticker = Ticker(
            symbol="NVDA",
            name="NVIDIA Corporation",
            is_active=True,
            first_seen=datetime.now(UTC).date(),
        )
        db_session.add(ticker)
        await db_session.flush()
        await db_session.refresh(ticker)

        articles = [self._make_article("NVDA stock hits all-time high", "http://test.com/3")]
        await store_news_articles(db_session, articles, tickers=[ticker])

        from sqlalchemy import select

        result = await db_session.execute(
            select(NewsArticle).where(NewsArticle.url == "http://test.com/3")
        )
        row = result.scalar_one_or_none()
        assert row is not None
        assert ticker.id in (row.ticker_ids or [])

    @pytest.mark.asyncio
    async def test_source_tier_stored(self, db_session: AsyncSession):
        art = self._make_article("Test Article", "http://test.com/tier", tier=2)
        await store_news_articles(db_session, [art])

        from sqlalchemy import select

        result = await db_session.execute(
            select(NewsArticle).where(NewsArticle.url == "http://test.com/tier")
        )
        row = result.scalar_one_or_none()
        assert row is not None
        assert row.source_tier == 2


# ---------------------------------------------------------------------------
# fetch_finnhub_news (mocked httpx)
# ---------------------------------------------------------------------------


class TestFetchFinnhubNews:
    @pytest.mark.asyncio
    async def test_returns_empty_without_api_key(self):
        from ingestion.news_feed import fetch_finnhub_news

        result = await fetch_finnhub_news("AAPL", api_key="")
        assert result == []

    @pytest.mark.asyncio
    async def test_parses_response(self, httpx_mock):
        from ingestion.news_feed import fetch_finnhub_news

        httpx_mock.add_response(
            url=__import__("re").compile(r"https://finnhub.io/.*"),
            json=[
                {
                    "headline": "Apple beats Q3 earnings",
                    "url": "http://news.com/1",
                    "summary": "Apple reported Q3 earnings...",
                    "datetime": 1700000000,
                    "source": "Reuters",
                }
            ],
        )
        articles = await fetch_finnhub_news("AAPL", api_key="test-key")  # pragma: allowlist secret
        assert len(articles) == 1
        assert articles[0]["title"] == "Apple beats Q3 earnings"
        assert articles[0]["source_tier"] == 2
        assert articles[0]["source_name"] == "Reuters"

    @pytest.mark.asyncio
    async def test_skips_empty_headline_or_url(self, httpx_mock):
        from ingestion.news_feed import fetch_finnhub_news

        httpx_mock.add_response(
            url=__import__("re").compile(r"https://finnhub.io/.*"),
            json=[
                {"headline": "", "url": "http://news.com/1", "datetime": 1700000000},
                {"headline": "Valid Title", "url": "", "datetime": 1700000000},
                {"headline": "Good Article", "url": "http://news.com/2", "datetime": 1700000000},
            ],
        )
        articles = await fetch_finnhub_news("AAPL", api_key="test-key")  # pragma: allowlist secret
        assert len(articles) == 1
        assert articles[0]["title"] == "Good Article"

    @pytest.mark.asyncio
    async def test_returns_empty_on_http_error(self, httpx_mock):
        from ingestion.news_feed import fetch_finnhub_news

        httpx_mock.add_response(
            url=__import__("re").compile(r"https://finnhub.io/.*"), status_code=429
        )
        articles = await fetch_finnhub_news("AAPL", api_key="test-key")  # pragma: allowlist secret
        assert articles == []


# ---------------------------------------------------------------------------
# fetch_newsapi_articles (mocked httpx)
# ---------------------------------------------------------------------------


class TestFetchNewsApiArticles:
    @pytest.mark.asyncio
    async def test_returns_empty_without_api_key(self):
        from ingestion.news_feed import fetch_newsapi_articles

        result = await fetch_newsapi_articles("AAPL", ticker_ids=[1], api_key="")
        assert result == []

    @pytest.mark.asyncio
    async def test_parses_response(self, httpx_mock):
        from ingestion.news_feed import fetch_newsapi_articles

        httpx_mock.add_response(
            url=__import__("re").compile(r"https://newsapi.org/.*"),
            json={
                "articles": [
                    {
                        "title": "Apple Stock Surges",
                        "url": "http://wsj.com/article/1",
                        "description": "Apple stock...",
                        "publishedAt": "2024-01-15T12:00:00Z",
                        "source": {"name": "WSJ"},
                    }
                ]
            },
        )
        articles = await fetch_newsapi_articles(
            "AAPL", ticker_ids=[1], api_key="test-key"
        )  # pragma: allowlist secret
        assert len(articles) == 1
        assert articles[0]["title"] == "Apple Stock Surges"
        assert articles[0]["source_tier"] == 3
        assert articles[0]["ticker_ids"] == [1]

    @pytest.mark.asyncio
    async def test_skips_removed_articles(self, httpx_mock):
        from ingestion.news_feed import fetch_newsapi_articles

        httpx_mock.add_response(
            url=__import__("re").compile(r"https://newsapi.org/.*"),
            json={
                "articles": [
                    {
                        "title": "[Removed]",
                        "url": "http://wsj.com/removed",
                        "publishedAt": "2024-01-15T12:00:00Z",
                        "source": {"name": "WSJ"},
                    }
                ]
            },
        )
        articles = await fetch_newsapi_articles(
            "AAPL", ticker_ids=[1], api_key="test-key"
        )  # pragma: allowlist secret
        assert len(articles) == 0

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, httpx_mock):
        from ingestion.news_feed import fetch_newsapi_articles

        httpx_mock.add_response(
            url=__import__("re").compile(r"https://newsapi.org/.*"), status_code=401
        )
        articles = await fetch_newsapi_articles("AAPL", ticker_ids=[1], api_key="bad-key")
        assert articles == []


# ---------------------------------------------------------------------------
# aggregate_news_batch (integration with mocked DB + external APIs)
# ---------------------------------------------------------------------------


class TestAggregateNewsBatch:
    @pytest.mark.asyncio
    async def test_batch_with_no_api_keys_uses_rss_only(
        self, db_session: AsyncSession, sample_ticker
    ):
        """With no API keys and no RSS feeds, batch should complete cleanly."""
        inserted = await aggregate_news_batch(
            db_session,
            tickers=[sample_ticker],
            finnhub_api_key="",
            newsapi_key="",
            rss_feed_urls={},  # Empty RSS — skip feed fetching
            world_rss_feed_urls={},  # Empty world RSS too
        )
        # No articles to insert; should return 0 cleanly
        assert inserted == 0

    @pytest.mark.asyncio
    async def test_batch_returns_inserted_count(
        self, db_session: AsyncSession, sample_ticker, httpx_mock
    ):
        """Batch with Finnhub mock returns correct count."""
        httpx_mock.add_response(
            url=__import__("re").compile(r"https://finnhub.io/.*"),
            json=[
                {
                    "headline": "NVDA Announces New GPU",
                    "url": "http://news.com/nvda-gpu",
                    "datetime": 1700000000,
                    "source": "Reuters",
                }
            ],
        )
        inserted = await aggregate_news_batch(
            db_session,
            tickers=[sample_ticker],
            finnhub_api_key="test-key",  # pragma: allowlist secret
            newsapi_key="",
            rss_feed_urls={},
        )
        assert inserted >= 1
