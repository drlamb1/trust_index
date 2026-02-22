"""
EdgeFinder — Earnings Call Transcript Ingestion

Multi-source transcript pipeline:

  1. Motley Fool (free, primary) — scrapes full transcripts from fool.com
     Discovery strategies (tried in order):
       a) DuckDuckGo search — most reliable, finds exact URL
       b) Direct URL construction — builds URL from company name + date range
       c) news-sitemap.xml — firehose for recently published transcripts
     Extraction from <div id="article-body-transcript">

  2. FMP API (paid fallback) — if user has a paid FMP plan

Run manually:
    python cli.py ingest transcripts
    python cli.py ingest transcripts --ticker NVDA
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import date, datetime
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import EarningsTranscript, Ticker

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Corporate suffixes to strip when building URL slugs
_CORP_SUFFIXES = re.compile(
    r",?\s*\b(Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Company|Ltd\.?|"
    r"Limited|PLC|SA|SE|NV|AG|Group|Holdings|Holding)\s*$",
    re.IGNORECASE,
)

# Well-known company names — avoids a network call for common tickers
_KNOWN_NAMES: dict[str, str] = {
    "AAPL": "Apple",
    "AMZN": "Amazon.com",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet",
    "META": "Meta Platforms",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "TSLA": "Tesla",
    "TSM": "Taiwan Semiconductor Manufacturing",
    "AVGO": "Broadcom",
    "AMD": "Advanced Micro Devices",
    "INTC": "Intel",
    "NFLX": "Netflix",
    "CRM": "Salesforce",
    "ORCL": "Oracle",
    "ADBE": "Adobe",
    "CSCO": "Cisco Systems",
    "ACN": "Accenture",
    "IBM": "IBM",
    "QCOM": "Qualcomm",
    "TXN": "Texas Instruments",
    "NOW": "ServiceNow",
    "PLTR": "Palantir Technologies",
    "UBER": "Uber Technologies",
    "ABNB": "Airbnb",
    "SQ": "Block",
    "SHOP": "Shopify",
    "SNOW": "Snowflake",
    "NET": "Cloudflare",
    "CRWD": "CrowdStrike Holdings",
    "DDOG": "Datadog",
    "ZS": "Zscaler",
    "PANW": "Palo Alto Networks",
    "V": "Visa",
    "MA": "Mastercard",
    "JPM": "JPMorgan Chase",
    "BAC": "Bank of America",
    "GS": "Goldman Sachs",
    "MS": "Morgan Stanley",
    "WMT": "Walmart",
    "COST": "Costco Wholesale",
    "HD": "Home Depot",
    "DIS": "Walt Disney",
    "PEP": "PepsiCo",
    "KO": "Coca-Cola",
    "MCD": "McDonald's",
    "NKE": "Nike",
    "BA": "Boeing",
    "LMT": "Lockheed Martin",
    "RTX": "RTX",
    "UNH": "UnitedHealth Group",
    "JNJ": "Johnson & Johnson",
    "PFE": "Pfizer",
    "ABBV": "AbbVie",
    "LLY": "Eli Lilly",
    "MRK": "Merck",
    "CVX": "Chevron",
    "XOM": "Exxon Mobil",
    "CEG": "Constellation Energy",
    "VST": "Vistra",
    "SMR": "NuScale Power",
    "RR": "Rolls-Royce Holdings",
    "SOFI": "SoFi Technologies",
    "COIN": "Coinbase Global",
    "HOOD": "Robinhood Markets",
    "RIVN": "Rivian Automotive",
    "LCID": "Lucid Group",
    "ARM": "Arm Holdings",
    "SMCI": "Super Micro Computer",
    "MU": "Micron Technology",
    "MRVL": "Marvell Technology",
    "ON": "ON Semiconductor",
    "ANET": "Arista Networks",
    "APP": "AppLovin",
}

# FMP API (paid plans only)
FMP_BASE_URL = "https://financialmodelingprep.com/stable"
FMP_LEGACY_URL = "https://financialmodelingprep.com/api/v3"

# Typical earnings reporting months by calendar quarter
# Q1 (Jan-Mar) -> reported Apr/May, Q2 (Apr-Jun) -> Jul/Aug,
# Q3 (Jul-Sep) -> Oct/Nov, Q4 (Oct-Dec) -> Jan/Feb
_QUARTER_REPORT_MONTHS: dict[int, list[str]] = {
    1: ["04", "05"],
    2: ["07", "08"],
    3: ["10", "11"],
    4: ["01", "02", "03"],
}


# ---------------------------------------------------------------------------
# Motley Fool — URL discovery strategies
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Convert a company name to a URL slug (lowercase, hyphens, no special chars)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    return slug


def _build_slug_variants(company_name: str, symbol: str) -> list[str]:
    """
    Generate URL slug variants for a company.

    Motley Fool slugs vary — sometimes they include suffixes, sometimes not.
    Examples: "nvidia-nvda", "apple-aapl", "alphabet-goog", "amazoncom-amzn"
    """
    sym = symbol.lower()
    variants = set()

    if company_name:
        # Full name slug
        full_slug = _slugify(company_name)
        variants.add(f"{full_slug}-{sym}")

        # Without corporate suffix
        stripped = _CORP_SUFFIXES.sub("", company_name).strip()
        if stripped != company_name:
            variants.add(f"{_slugify(stripped)}-{sym}")

        # First word only (common: "nvidia", "apple", "microsoft")
        first_word = company_name.split()[0].strip(",.")
        if len(first_word) > 2:
            variants.add(f"{_slugify(first_word)}-{sym}")

    # Just ticker repeated (e.g., "ppl-ppl")
    variants.add(f"{sym}-{sym}")

    return list(variants)


def _url_matches_calendar_quarter(url: str, quarter: int, year: int) -> bool:
    """
    Check if a Motley Fool transcript URL's publication date falls in the
    expected window for a given calendar quarter's earnings report.

    Calendar Q3 2025 (Jul-Sep) → reported Oct/Nov 2025
    Calendar Q4 2025 (Oct-Dec) → reported Jan/Feb/Mar 2026
    """
    # Extract publication date from URL: /YYYY/MM/DD/slug
    date_match = re.search(r"/(\d{4})/(\d{2})/\d{2}/", url)
    if not date_match:
        return True  # Can't validate, let it through

    pub_year = int(date_match.group(1))
    pub_month = date_match.group(2)

    expected_months = _QUARTER_REPORT_MONTHS.get(quarter, [])
    if quarter == 4:
        # Q4 reports come in Jan/Feb/Mar of the NEXT year
        return pub_year == year + 1 and pub_month in expected_months
    else:
        return pub_year == year and pub_month in expected_months


async def _discover_via_ddg(
    symbol: str,
    quarter: int,
    year: int,
) -> str | None:
    """
    Find a Motley Fool transcript URL via DuckDuckGo/Bing search.

    Uses the ddgs package (handles anti-bot/sessions via primp).
    Searches for both the calendar year and fiscal year+1 (for companies
    with offset fiscal years like NVDA).
    """
    sym_lower = symbol.lower()

    # Companies have different fiscal year alignments, so we can't assume
    # the fiscal quarter matches the calendar quarter. Search broadly by
    # expected report publication timeframe and filter by date.
    report_months = _QUARTER_REPORT_MONTHS.get(quarter, [])
    if quarter == 4:
        report_year = year + 1  # Q4 reports come in Jan/Feb/Mar next year
    else:
        report_year = year

    # Broad query + year-specific queries to maximize coverage
    queries = [
        f"site:fool.com {symbol} earnings call transcript {report_year}",
        f"site:fool.com {symbol} Q{quarter} {year} earnings call transcript",
        f"site:fool.com {symbol} Q{quarter} {year + 1} earnings call transcript",
    ]

    candidates: list[str] = []
    seen: set[str] = set()
    for query in queries:
        try:
            from ddgs import DDGS

            results = await asyncio.to_thread(
                lambda q=query: DDGS().text(q, max_results=5)
            )
            for r in results:
                href = r.get("href", "")
                if href in seen:
                    continue
                seen.add(href)
                if "fool.com/earnings/call-transcripts/" not in href:
                    continue
                if sym_lower not in href.lower():
                    continue
                candidates.append(href)
        except Exception as exc:
            logger.debug("DDG search failed for query %r: %s", query, exc)

    # Filter by publication date matching the expected report window
    unparseable: list[str] = []
    for url in candidates:
        date_match = re.search(r"/(\d{4})/(\d{2})/\d{2}/", url)
        if not date_match:
            unparseable.append(url)
            continue
        if _url_matches_calendar_quarter(url, quarter, year):
            logger.debug("DDG found (date-validated): %s", url)
            return url

    # Only fall back to URLs we couldn't validate (not ones we rejected)
    if unparseable:
        logger.debug("DDG found (unparseable date): %s", unparseable[0])
        return unparseable[0]

    return None


async def _discover_via_url_construction(
    symbol: str,
    quarter: int,
    year: int,
    company_name: str = "",
    fmp_api_key: str = "",
) -> str | None:
    """
    Build Motley Fool transcript URLs from company name + date range and
    probe with GET requests until we find a hit.

    Generates a focused set of candidates (~30-50 URLs) by:
    - Using 2-3 slug variants from company name
    - Trying fiscal year and fiscal year + 1 (for offset fiscal years)
    - Limiting date range to typical earnings report months
    """
    # Get company name if not provided
    if not company_name:
        company_name = await _resolve_company_name(symbol, fmp_api_key)

    slugs = _build_slug_variants(company_name or "", symbol)

    # Typical earnings report months for this calendar quarter
    report_months = _QUARTER_REPORT_MONTHS.get(quarter, ["01", "04", "07", "10"])

    # Fiscal year/quarter can differ from calendar. NVDA calendar Q3 -> fiscal Q3
    # of year+1. AAPL calendar Q4 -> fiscal Q1 of year+1. Try all combos.
    fiscal_variants = [
        (quarter, year), (quarter, year + 1),           # Same fiscal Q, both years
        ((quarter % 4) + 1, year), ((quarter % 4) + 1, year + 1),  # Next fiscal Q
    ]

    # Build candidate URLs — keep it focused
    candidates = []
    for slug in slugs[:3]:  # Max 3 slug variants
        for fq, fy in fiscal_variants:
            for month in report_months:
                url_year = year + 1 if quarter == 4 and month in ("01", "02", "03") else year
                # Earnings typically reported in the second half of the month
                for day in range(17, 32):
                    candidates.append(
                        f"https://www.fool.com/earnings/call-transcripts/"
                        f"{url_year}/{month}/{day:02d}/{slug}-q{fq}-{fy}-earnings-call-transcript/"
                    )

    logger.debug("URL construction: trying %d candidates for %s Q%d %d", len(candidates), symbol, quarter, year)

    # Probe with HEAD requests in small batches with backoff
    async with httpx.AsyncClient(timeout=8.0, headers=_HEADERS, follow_redirects=True) as client:
        for i in range(0, len(candidates), 5):
            batch = candidates[i : i + 5]
            tasks = [client.head(url) for url in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for url, result in zip(batch, results):
                if isinstance(result, httpx.Response) and result.status_code == 200:
                    logger.debug("URL construction found: %s", url)
                    return url
                if isinstance(result, httpx.Response) and result.status_code == 429:
                    # Rate limited — back off and stop probing
                    logger.debug("Rate limited by Motley Fool, backing off")
                    await asyncio.sleep(5.0)
                    return None

            await asyncio.sleep(0.3)  # Small delay between batches

    return None


async def _resolve_company_name(symbol: str, fmp_api_key: str = "") -> str:
    """
    Resolve company name for a ticker.

    Priority: static map → yfinance (free, no key) → FMP profile → empty.
    """
    sym = symbol.upper()

    # 1. Static map (instant, covers most common tickers)
    if sym in _KNOWN_NAMES:
        return _KNOWN_NAMES[sym]

    # 2. yfinance (free, no API key needed)
    try:
        import yfinance as yf

        info = await asyncio.to_thread(lambda: yf.Ticker(sym).info)
        name = info.get("shortName") or info.get("longName") or ""
        if name:
            logger.debug("yfinance resolved %s → %s", sym, name)
            return name
    except Exception as exc:
        logger.debug("yfinance name lookup failed for %s: %s", sym, exc)

    # 3. FMP profile API (free tier)
    if fmp_api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{FMP_BASE_URL}/profile",
                    params={"symbol": sym, "apikey": fmp_api_key},
                )
                resp.raise_for_status()
                data = resp.json()
                if data and isinstance(data, list):
                    return data[0].get("companyName", "")
        except Exception:
            pass

    return ""


# ---------------------------------------------------------------------------
# Motley Fool — page extraction
# ---------------------------------------------------------------------------


async def _extract_transcript_from_page(url: str) -> str | None:
    """
    Fetch a Motley Fool transcript page and extract the text.

    Targets <div id="article-body-transcript"> with BeautifulSoup.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to fetch transcript page %s: %s", url, exc)
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Primary target: transcript-specific div
    article = soup.find("div", id="article-body-transcript")
    if not article:
        article = soup.find("div", class_="article-body")
    if not article:
        logger.warning("No transcript content found on page: %s", url)
        return None

    paragraphs = []
    for elem in article.find_all(["p", "h2", "h3"]):
        text = elem.get_text(strip=True)
        if text:
            paragraphs.append(text)

    content = "\n\n".join(paragraphs)

    if len(content) < 500:
        logger.warning("Transcript too short (%d chars) from %s", len(content), url)
        return None

    return content


async def fetch_transcript_from_motley_fool(
    symbol: str,
    quarter: int,
    year: int,
    company_name: str = "",
    fmp_api_key: str = "",
) -> str | None:
    """
    Fetch a transcript from Motley Fool using multi-strategy discovery.

    Strategy order:
      1. DuckDuckGo search (most reliable when not rate-limited)
      2. Direct URL construction (always works, more HEAD requests)
    """
    # Strategy 1: DuckDuckGo
    url = await _discover_via_ddg(symbol, quarter, year)

    # Strategy 2: URL construction
    if not url:
        url = await _discover_via_url_construction(
            symbol, quarter, year, company_name, fmp_api_key
        )

    if not url:
        logger.debug("No Motley Fool transcript found for %s Q%d %d", symbol, quarter, year)
        return None

    content = await _extract_transcript_from_page(url)
    if content:
        logger.info(
            "Scraped Motley Fool transcript: %s Q%d %d (%d chars)",
            symbol, quarter, year, len(content),
        )
    return content


# ---------------------------------------------------------------------------
# Motley Fool — sitemap discovery (firehose mode)
# ---------------------------------------------------------------------------


async def _discover_transcript_urls_sitemap() -> list[dict]:
    """
    Discover recent transcript URLs from Motley Fool's news sitemap.

    Returns list of {"url": str, "ticker": str|None, "quarter": int, "year": int}.
    """
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://www.fool.com/news-sitemap.xml",
                headers=_HEADERS,
            )
            resp.raise_for_status()
    except Exception as exc:
        logger.debug("Motley Fool sitemap fetch failed: %s", exc)
        return []

    transcripts = []
    for match in re.finditer(
        r"<loc>(https?://[^<]*earnings/call-transcripts/[^<]+)</loc>", resp.text
    ):
        url = match.group(1)
        slug = url.rstrip("/").rsplit("/", 1)[-1]

        # Extract ticker and quarter from slug
        # Pattern: {company}-{ticker}-q{N}-{year}-earnings-call-transcript
        ticker_match = re.search(r"-([a-z]{1,5})-q(\d)-(\d{4})-earnings", slug)
        if ticker_match:
            transcripts.append({
                "url": url,
                "ticker": ticker_match.group(1).upper(),
                "quarter": int(ticker_match.group(2)),
                "year": int(ticker_match.group(3)),
            })

    logger.debug("Sitemap: found %d transcript URLs", len(transcripts))
    return transcripts


# ---------------------------------------------------------------------------
# Source 2: FMP API (paid fallback)
# ---------------------------------------------------------------------------


async def fetch_transcript_from_fmp(
    symbol: str,
    quarter: int,
    year: int,
    api_key: str,
) -> str | None:
    """Fetch from FMP paid API. Returns transcript text or None."""
    urls = [
        (f"{FMP_BASE_URL}/earning-call-transcript", {"symbol": symbol, "quarter": quarter, "year": year, "apikey": api_key}),
        (f"{FMP_LEGACY_URL}/earning_call_transcript/{symbol}", {"quarter": quarter, "year": year, "apikey": api_key}),
    ]

    for url, params in urls:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code in (402, 403):
                    return None
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError:
            continue
        except Exception:
            return None

        if not data or not isinstance(data, list):
            continue

        content = (data[0] if data else {}).get("content", "")
        if content and len(content) >= 100:
            return content

    return None


# ---------------------------------------------------------------------------
# Unified fetch — tries all sources
# ---------------------------------------------------------------------------


async def fetch_transcript(
    symbol: str,
    quarter: int,
    year: int,
    company_name: str = "",
    fmp_api_key: str = "",
) -> tuple[str | None, str]:
    """
    Fetch a transcript from any available source.

    Returns (content, source) where source is "motley_fool" or "fmp".
    Tries Motley Fool first (free), then FMP (paid).
    """
    # Source 1: Motley Fool
    content = await fetch_transcript_from_motley_fool(
        symbol, quarter, year, company_name, fmp_api_key
    )
    if content:
        return content, "motley_fool"

    # Source 2: FMP
    if fmp_api_key:
        content = await fetch_transcript_from_fmp(symbol, quarter, year, fmp_api_key)
        if content:
            return content, "fmp"

    return None, ""


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _content_hash(text: str) -> str:
    """SHA-256 hash of transcript text for dedup."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def fetch_and_store_transcript(
    session: AsyncSession,
    ticker: Ticker,
    quarter: int,
    year: int,
    fmp_api_key: str = "",
) -> bool:
    """
    Fetch and store a single transcript. Returns True if new transcript stored.
    """
    # Dedup check
    existing = await session.execute(
        select(EarningsTranscript.id).where(
            EarningsTranscript.ticker_id == ticker.id,
            EarningsTranscript.fiscal_year == year,
            EarningsTranscript.quarter == quarter,
        )
    )
    if existing.scalar_one_or_none() is not None:
        logger.debug("Transcript already exists: %s Q%d %d", ticker.symbol, quarter, year)
        return False

    # Resolve company name (needed for URL construction)
    company_name = ticker.name or ""
    if not company_name:
        company_name = await _resolve_company_name(ticker.symbol, fmp_api_key)
        if company_name:
            ticker.name = company_name
            await session.flush()

    content, source = await fetch_transcript(
        ticker.symbol, quarter, year,
        company_name=company_name,
        fmp_api_key=fmp_api_key,
    )
    if not content:
        return False

    transcript = EarningsTranscript(
        ticker_id=ticker.id,
        quarter=quarter,
        fiscal_year=year,
        transcript_text=content,
        word_count=len(content.split()),
        source=source,
        content_hash=_content_hash(content),
    )
    session.add(transcript)
    await session.flush()

    logger.info(
        "Stored transcript: %s Q%d %d (%d words, source=%s)",
        ticker.symbol, quarter, year, transcript.word_count, source,
    )
    return True


def _get_recent_quarters(count: int = 4) -> list[tuple[int, int]]:
    """Return the most recent N fiscal quarters as (quarter, year) tuples."""
    today = date.today()
    current_q = (today.month - 1) // 3 + 1
    current_y = today.year

    quarters = []
    q, y = current_q, current_y
    for _ in range(count):
        q -= 1
        if q == 0:
            q = 4
            y -= 1
        quarters.append((q, y))
    return quarters


async def fetch_and_store_transcripts_batch(
    session: AsyncSession,
    tickers: list[Ticker],
    fmp_api_key: str = "",
    quarters_back: int = 4,
    concurrency: int = 2,
) -> dict[str, int]:
    """
    Fetch transcripts for multiple tickers across recent quarters.

    Uses Motley Fool (free) with FMP as paid fallback.
    Throttled to be polite to Motley Fool.
    """
    quarters = _get_recent_quarters(quarters_back)
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, int] = {}

    async def _fetch_ticker(ticker: Ticker) -> int:
        stored = 0
        for q, y in quarters:
            async with sem:
                if await fetch_and_store_transcript(session, ticker, q, y, fmp_api_key):
                    stored += 1
                await asyncio.sleep(2.0)  # Be polite to Motley Fool
        return stored

    for ticker in tickers:
        count = await _fetch_ticker(ticker)
        results[ticker.symbol] = count

    total = sum(results.values())
    logger.info(
        "Transcript batch: %d new transcripts for %d tickers (%d quarters)",
        total, len(tickers), len(quarters),
    )
    return results


async def discover_and_store_from_sitemap(
    session: AsyncSession,
    fmp_api_key: str = "",
) -> int:
    """
    Discover new transcripts from Motley Fool's news sitemap and store any
    that match tickers in our database.

    Good for daily scheduled runs — catches transcripts as they're published.
    """
    sitemap_entries = await _discover_transcript_urls_sitemap()
    if not sitemap_entries:
        return 0

    result = await session.execute(
        select(Ticker).where(Ticker.is_active.is_(True))
    )
    tickers = result.scalars().all()
    symbol_map = {t.symbol.upper(): t for t in tickers}

    stored = 0
    for entry in sitemap_entries:
        ticker_sym = entry.get("ticker")
        if not ticker_sym or ticker_sym not in symbol_map:
            continue

        ticker = symbol_map[ticker_sym]
        quarter = entry["quarter"]
        fiscal_year = entry["year"]

        # Dedup
        existing = await session.execute(
            select(EarningsTranscript.id).where(
                EarningsTranscript.ticker_id == ticker.id,
                EarningsTranscript.fiscal_year == fiscal_year,
                EarningsTranscript.quarter == quarter,
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        content = await _extract_transcript_from_page(entry["url"])
        if not content:
            continue

        transcript = EarningsTranscript(
            ticker_id=ticker.id,
            quarter=quarter,
            fiscal_year=fiscal_year,
            transcript_text=content,
            word_count=len(content.split()),
            source="motley_fool",
            content_hash=_content_hash(content),
        )
        session.add(transcript)
        await session.flush()
        stored += 1

        logger.info(
            "Sitemap transcript: %s Q%d %d (%d words)",
            ticker_sym, quarter, fiscal_year, transcript.word_count,
        )
        await asyncio.sleep(2.0)

    return stored
