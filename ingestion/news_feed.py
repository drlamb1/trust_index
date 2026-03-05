"""
EdgeFinder — News Feed Aggregator (Phase 3)

Aggregates news from multiple sources:
  - RSS feeds (Tier 2-3 sources)
  - Finnhub company news API
  - NewsAPI.org aggregation

Deduplication:
  - Hard dedup: SHA-256(url|title) stored as raw_content_hash (UNIQUE constraint)
  - Soft dedup: rapidfuzz title similarity ≥85% within a batch
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import NewsArticle, Ticker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RSS feed catalog: tier → list of feed URLs
# ---------------------------------------------------------------------------

DEFAULT_RSS_FEEDS: dict[int, list[str]] = {
    2: [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    ],
    3: [
        "https://finance.yahoo.com/news/rssindex",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://feeds.marketwatch.com/marketwatch/marketpulse/",
    ],
}

# General / world news — wars, elections, tariffs, pandemics move markets
# before the financial press catches up. Tier 3 (unstructured, NLP-tagged).
WORLD_NEWS_RSS_FEEDS: dict[int, list[str]] = {
    2: [
        "https://feeds.reuters.com/reuters/topNews",
        "https://feeds.reuters.com/reuters/worldNews",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
    ],
    3: [
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://feeds.npr.org/1001/rss.xml",  # NPR News
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
        "https://feeds.reuters.com/reuters/politicsNews",
    ],
}

_EXECUTOR = ThreadPoolExecutor(max_workers=4)


# ---------------------------------------------------------------------------
# Hashing / deduplication helpers
# ---------------------------------------------------------------------------


def compute_content_hash(url: str, title: str) -> str:
    """SHA-256 fingerprint for hard deduplication."""
    key = f"{(url or '').strip()}|{(title or '').strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _is_fuzzy_duplicate(title: str, seen_titles: list[str], threshold: int = 85) -> bool:
    """Return True if *title* is ≥ threshold% similar to any title in seen_titles."""
    try:
        from rapidfuzz import fuzz  # type: ignore
    except ImportError:
        return False
    upper = title.upper()
    for existing in seen_titles:
        if fuzz.ratio(upper, existing.upper()) >= threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# Ticker matching helpers
# ---------------------------------------------------------------------------


def _build_ticker_index(
    tickers: list[Ticker],
) -> tuple[dict[str, int], dict[str, int]]:
    """
    Build two lookup maps from a list of Ticker ORM objects:
      symbol_map: "AAPL" → ticker.id
      name_map:   "APPLE" → ticker.id  (longest keyword ≥4 chars from company name)
    """
    symbol_map: dict[str, int] = {}
    name_map: dict[str, int] = {}

    for t in tickers:
        symbol_map[t.symbol.upper()] = t.id
        if t.name:
            # Extract first meaningful word ≥4 chars from company name
            words = re.split(r"[\s,./&()-]+", t.name.upper())
            for w in words:
                clean = re.sub(r"[^A-Z]", "", w)
                if len(clean) >= 4 and clean not in {"CORP", "INC", "LTD", "GROUP", "HOLDINGS"}:
                    name_map[clean] = t.id
                    break  # only use the first significant word

    return symbol_map, name_map


def match_ticker_ids(
    title: str,
    symbol_map: dict[str, int],
    name_map: dict[str, int],
) -> list[int]:
    """
    Find ticker IDs mentioned in *title*.
    Uses word-boundary regex for symbols and keyword substring search for names.
    Returns deduplicated list.
    """
    found: set[int] = set()
    upper = title.upper()

    for symbol, tid in symbol_map.items():
        pattern = r"\b" + re.escape(symbol) + r"\b"
        if re.search(pattern, upper):
            found.add(tid)

    for keyword, tid in name_map.items():
        if keyword in upper:
            found.add(tid)

    return sorted(found)


# ---------------------------------------------------------------------------
# RSS parsing (feedparser is synchronous)
# ---------------------------------------------------------------------------


def _parse_rss_sync(
    feed_url: str,
    max_age_days: int,
    tier: int,
) -> list[dict[str, Any]]:
    """
    Synchronous RSS parsing. Run via ThreadPoolExecutor in async context.
    """
    try:
        import feedparser  # type: ignore
    except ImportError:
        logger.warning("feedparser not installed; skipping RSS")
        return []

    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    articles: list[dict[str, Any]] = []

    try:
        feed = feedparser.parse(feed_url)
    except Exception as exc:
        logger.warning("RSS parse error %s: %s", feed_url, exc)
        return []

    source_name = getattr(feed.feed, "title", feed_url)

    for entry in feed.entries:
        title = getattr(entry, "title", "").strip()
        url = getattr(entry, "link", "").strip()
        if not title or not url:
            continue

        # Parse published date
        published_at: datetime | None = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_at = datetime(*entry.published_parsed[:6], tzinfo=UTC)
            except Exception:
                pass
        if published_at is None:
            published_at = datetime.now(UTC)

        if published_at < cutoff:
            continue

        summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        summary = summary[:500]

        articles.append(
            {
                "title": title,
                "url": url,
                "summary": summary,
                "published_at": published_at,
                "source_name": source_name,
                "source_tier": tier,
                "ticker_ids": [],
                "raw_content_hash": compute_content_hash(url, title),
            }
        )

    return articles


async def fetch_rss_articles(
    feed_urls: dict[int, list[str]] | None = None,
    max_age_days: int = 7,
) -> list[dict[str, Any]]:
    """Fetch articles from all RSS feeds asynchronously via threadpool."""
    if feed_urls is None:
        feed_urls = DEFAULT_RSS_FEEDS

    loop = asyncio.get_event_loop()
    tasks = []
    for tier, urls in feed_urls.items():
        for url in urls:
            tasks.append(loop.run_in_executor(_EXECUTOR, _parse_rss_sync, url, max_age_days, tier))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    articles: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("RSS fetch error: %s", result)
        else:
            articles.extend(result)

    return articles


# ---------------------------------------------------------------------------
# Finnhub company news
# ---------------------------------------------------------------------------


async def fetch_finnhub_news(
    ticker: str,
    days: int = 7,
    api_key: str = "",
) -> list[dict[str, Any]]:
    """
    Fetch company news from Finnhub for a single ticker.
    Tier 2 source.
    """
    if not api_key:
        return []

    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    url = "https://finnhub.io/api/v1/company-news"
    params = {
        "symbol": ticker.upper(),
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "token": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            items = resp.json()
    except Exception as exc:
        logger.warning("Finnhub news error for %s: %s", ticker, exc)
        return []

    articles: list[dict[str, Any]] = []
    for item in items[:100]:  # cap per ticker per call
        title = (item.get("headline") or "").strip()
        article_url = (item.get("url") or "").strip()
        if not title or not article_url:
            continue

        ts = item.get("datetime", 0)
        published_at = datetime.fromtimestamp(ts, tz=UTC) if ts else datetime.now(UTC)

        articles.append(
            {
                "title": title,
                "url": article_url,
                "summary": (item.get("summary") or "")[:500],
                "published_at": published_at,
                "source_name": item.get("source", "Finnhub"),
                "source_tier": 2,
                "ticker_ids": [],  # will be tagged later
                "raw_content_hash": compute_content_hash(article_url, title),
            }
        )

    return articles


# ---------------------------------------------------------------------------
# NewsAPI.org
# ---------------------------------------------------------------------------


async def fetch_newsapi_articles(
    query: str,
    ticker_ids: list[int],
    days: int = 7,
    api_key: str = "",
    page_size: int = 20,
) -> list[dict[str, Any]]:
    """
    Fetch articles from NewsAPI.org for a query string.
    Tier 3 source.
    """
    if not api_key:
        return []

    from_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "from": from_date,
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "language": "en",
        "apiKey": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise  # let caller handle rate limit
        logger.warning("NewsAPI error for %r: %s", query, exc)
        return []
    except Exception as exc:
        logger.warning("NewsAPI error for %r: %s", query, exc)
        return []

    articles: list[dict[str, Any]] = []
    for item in data.get("articles", []):
        title = (item.get("title") or "").strip()
        article_url = (item.get("url") or "").strip()
        if not title or not article_url or title == "[Removed]":
            continue

        published_raw = item.get("publishedAt") or ""
        try:
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except Exception:
            published_at = datetime.now(UTC)

        source_name = (item.get("source") or {}).get("name", "NewsAPI")

        articles.append(
            {
                "title": title,
                "url": article_url,
                "summary": (item.get("description") or "")[:500],
                "published_at": published_at,
                "source_name": source_name,
                "source_tier": 3,
                "ticker_ids": ticker_ids,
                "raw_content_hash": compute_content_hash(article_url, title),
            }
        )

    return articles


# ---------------------------------------------------------------------------
# NewsAPI.org — top headlines (general / world / politics)
# ---------------------------------------------------------------------------


async def fetch_newsapi_top_headlines(
    api_key: str = "",
    categories: tuple[str, ...] = ("general", "business", "science", "technology"),
    country: str = "us",
    page_size: int = 40,
) -> list[dict[str, Any]]:
    """
    Fetch top headlines across broad categories via NewsAPI.
    These are NOT ticker-specific — they capture macro events (wars, elections,
    tariffs, pandemics) that move markets before financial press catches up.
    Ticker tagging happens downstream via NLP in store_news_articles.
    """
    if not api_key:
        return []

    url = "https://newsapi.org/v2/top-headlines"
    articles: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for category in categories:
            params = {
                "category": category,
                "country": country,
                "pageSize": page_size,
                "apiKey": api_key,
            }
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    logger.warning("NewsAPI rate limited on top-headlines (%s) — stopping", category)
                    return articles
                logger.warning("NewsAPI top-headlines (%s) error: %s", category, exc)
                continue
            except Exception as exc:
                logger.warning("NewsAPI top-headlines (%s) error: %s", category, exc)
                continue

            for item in data.get("articles", []):
                title = (item.get("title") or "").strip()
                article_url = (item.get("url") or "").strip()
                if not title or not article_url or title == "[Removed]":
                    continue

                published_raw = item.get("publishedAt") or ""
                try:
                    published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                except Exception:
                    published_at = datetime.now(UTC)

                source_name = (item.get("source") or {}).get("name", "NewsAPI")

                articles.append(
                    {
                        "title": title,
                        "url": article_url,
                        "summary": (item.get("description") or "")[:500],
                        "published_at": published_at,
                        "source_name": source_name,
                        "source_tier": 3,
                        "ticker_ids": [],  # tagged by NLP downstream
                        "raw_content_hash": compute_content_hash(article_url, title),
                    }
                )

    return articles


# ---------------------------------------------------------------------------
# DB storage
# ---------------------------------------------------------------------------


async def store_news_articles(
    session: AsyncSession,
    articles: list[dict[str, Any]],
    tickers: list[Ticker] | None = None,
) -> int:
    """
    Deduplicate and store articles in the DB.

    Deduplication strategy:
      1. Within-batch: drop fuzzy-duplicate titles and repeated hashes
      2. Against DB: skip rows whose raw_content_hash already exists

    Returns the number of newly inserted rows.
    """
    if not articles:
        return 0

    # Build ticker index if provided
    symbol_map: dict[str, int] = {}
    name_map: dict[str, int] = {}
    if tickers:
        symbol_map, name_map = _build_ticker_index(tickers)

    # Within-batch dedup
    seen_hashes: set[str] = set()
    seen_titles: list[str] = []
    unique: list[dict[str, Any]] = []

    for art in articles:
        h = art.get("raw_content_hash") or compute_content_hash(
            art.get("url", ""), art.get("title", "")
        )
        if h in seen_hashes:
            continue
        title = art.get("title", "")
        if _is_fuzzy_duplicate(title, seen_titles):
            continue
        seen_hashes.add(h)
        seen_titles.append(title)
        art["raw_content_hash"] = h
        unique.append(art)

    if not unique:
        return 0

    # DB-level dedup: find which hashes already exist
    all_hashes = [a["raw_content_hash"] for a in unique]
    stmt = select(NewsArticle.raw_content_hash).where(NewsArticle.raw_content_hash.in_(all_hashes))
    result = await session.execute(stmt)
    existing_hashes: set[str] = {row[0] for row in result.fetchall()}

    inserted = 0
    for art in unique:
        if art["raw_content_hash"] in existing_hashes:
            continue

        # Tag tickers if not already set
        tids = list(art.get("ticker_ids") or [])
        if not tids and (symbol_map or name_map):
            tids = match_ticker_ids(art.get("title", ""), symbol_map, name_map)

        row = NewsArticle(
            ticker_ids=tids,
            source_tier=art.get("source_tier", 3),
            title=art.get("title", ""),
            url=art.get("url", ""),
            published_at=art.get("published_at") or datetime.now(UTC),
            summary=art.get("summary", ""),
            raw_content_hash=art["raw_content_hash"],
            sentiment_score=None,
        )
        session.add(row)
        inserted += 1

    if inserted:
        await session.flush()

    return inserted


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def aggregate_news_for_ticker(
    session: AsyncSession,
    ticker: Ticker,
    finnhub_api_key: str = "",
    newsapi_key: str = "",
    days: int = 7,
) -> int:
    """Aggregate news for a single ticker. Returns articles inserted."""
    articles: list[dict[str, Any]] = []

    # Finnhub company news (ticker-specific)
    if finnhub_api_key:
        fh = await fetch_finnhub_news(ticker.symbol, days=days, api_key=finnhub_api_key)
        for a in fh:
            a["ticker_ids"] = [ticker.id]
        articles.extend(fh)

    # NewsAPI by company name / symbol
    if newsapi_key:
        query = f'"{ticker.symbol}" OR "{ticker.name}"' if ticker.name else ticker.symbol
        na = await fetch_newsapi_articles(
            query=query,
            ticker_ids=[ticker.id],
            days=days,
            api_key=newsapi_key,
        )
        articles.extend(na)

    return await store_news_articles(session, articles, tickers=[ticker])


async def aggregate_news_batch(
    session: AsyncSession,
    tickers: list[Ticker],
    finnhub_api_key: str = "",
    newsapi_key: str = "",
    rss_feed_urls: dict[int, list[str]] | None = None,
    world_rss_feed_urls: dict[int, list[str]] | None = None,
    days: int = 7,
) -> int:
    """
    Full news aggregation run:
      1. Financial RSS feeds (tagged to tickers by NLP)
      2. World/general RSS feeds (wars, elections, tariffs — tagged by NLP)
      3. NewsAPI top headlines (general/business/science/tech categories)
      4. Finnhub per-ticker news (if api_key provided)
      5. NewsAPI per-ticker news (if api_key provided)

    Returns total articles inserted.
    """
    articles: list[dict[str, Any]] = []

    # 1. Financial RSS (existing)
    rss_articles = await fetch_rss_articles(feed_urls=rss_feed_urls, max_age_days=days)
    articles.extend(rss_articles)

    # 2. World / general news RSS — macro events that move everything
    if world_rss_feed_urls is None:
        world_rss_feed_urls = WORLD_NEWS_RSS_FEEDS
    world_articles = await fetch_rss_articles(feed_urls=world_rss_feed_urls, max_age_days=days)
    articles.extend(world_articles)

    # 3. NewsAPI top headlines (general categories, not ticker-specific)
    if newsapi_key:
        headlines = await fetch_newsapi_top_headlines(api_key=newsapi_key)
        articles.extend(headlines)

    # 4. Finnhub per-ticker — chunked to avoid OOM from 500+ concurrent requests
    inserted = 0
    if finnhub_api_key:
        chunk_size = 50
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i + chunk_size]
            fh_tasks = [
                fetch_finnhub_news(t.symbol, days=days, api_key=finnhub_api_key)
                for t in chunk
            ]
            fh_results = await asyncio.gather(*fh_tasks, return_exceptions=True)
            chunk_articles: list[dict[str, Any]] = []
            for ticker, result in zip(chunk, fh_results):
                if isinstance(result, Exception):
                    logger.warning("Finnhub error for %s: %s", ticker.symbol, result)
                    continue
                for a in result:
                    a["ticker_ids"] = [ticker.id]
                chunk_articles.extend(result)
            articles.extend(chunk_articles)

    inserted += await store_news_articles(session, articles, tickers=tickers)

    # 5. NewsAPI per-ticker (rate limited — free tier ~100 req/day).
    #    Top-headlines (step 3) already covers broad news with just 4 calls.
    #    Per-ticker queries are supplementary — cap at 80 tickers per run,
    #    with a 1s delay between calls to stay under the rate limit.
    #    Bail immediately on 429 to stop wasting quota.
    if newsapi_key:
        newsapi_budget = 80  # reserve ~20 calls for top-headlines + buffer
        for i, ticker in enumerate(tickers[:newsapi_budget]):
            query = f'"{ticker.symbol}"'
            try:
                na = await fetch_newsapi_articles(
                    query=query,
                    ticker_ids=[ticker.id],
                    days=days,
                    api_key=newsapi_key,
                )
            except Exception as exc:
                if "429" in str(exc):
                    logger.warning("NewsAPI rate limited at ticker %d/%d — stopping", i + 1, newsapi_budget)
                    break
                raise
            inserted += await store_news_articles(session, na, tickers=[ticker])
            if i < newsapi_budget - 1:
                await asyncio.sleep(1.0)

    return inserted
