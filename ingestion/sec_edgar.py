"""
EdgeFinder — SEC EDGAR Filing Downloader

Rate-limited async downloader for SEC EDGAR filings.

CRITICAL: SEC enforces 10 req/second. The TokenBucket is mandatory.
Violation results in IP bans lasting hours.

Required User-Agent (per SEC policy):
    "AppName/Version contact@email.com"
    Configured via EDGAR_USER_AGENT in .env

Flow:
    1. Look up CIK from company_tickers.json (cached in process memory)
    2. Fetch submissions/CIK{n}.json → filing metadata list
    3. Download primary document (HTML/HTM)
    4. Strip iXBRL tags → plain text
    5. Split into Item sections
    6. Hash-gate: skip if raw_text_hash unchanged
    7. Store Filing + FilingSection rows
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import date

import httpx
from lxml import etree
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.models import Filing, FilingSection, Ticker

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://data.sec.gov"
EDGAR_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# iXBRL namespace URIs used in SEC filings
IXBRL_NAMESPACES = (
    "http://www.xbrl.org/2013/inlineXBRL",
    "http://www.xbrl.org/2011/inlineXBRL",
)

# Module-level CIK cache (ticker symbol → zero-padded CIK string)
_cik_cache: dict[str, str] = {}
_cik_cache_loaded = False

# Max characters stored per section (keeps DB rows manageable)
MAX_SECTION_CHARS = 60_000


# ---------------------------------------------------------------------------
# Token bucket rate limiter
# ---------------------------------------------------------------------------


class TokenBucket:
    """
    Async token bucket for rate-limiting EDGAR HTTP requests.

    Refills at `rate` tokens per second, up to `capacity`.
    Thread-safe via asyncio.Lock.
    """

    def __init__(self, rate: float = 10.0, capacity: float = 10.0) -> None:
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Block until `tokens` are available, then consume them."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last_refill = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return

            wait_time = (tokens - self._tokens) / self.rate

        await asyncio.sleep(wait_time)
        await self.acquire(tokens)


_edgar_bucket: TokenBucket | None = None


def get_edgar_bucket() -> TokenBucket:
    global _edgar_bucket
    if _edgar_bucket is None:
        rate = float(getattr(settings, "edgar_rate_limit", 10.0))
        _edgar_bucket = TokenBucket(rate=rate, capacity=10.0)
    return _edgar_bucket


# ---------------------------------------------------------------------------
# EDGAR HTTP client
# ---------------------------------------------------------------------------


class EdgarClient:
    """Async HTTP client for SEC EDGAR with rate limiting and exponential backoff."""

    def __init__(self) -> None:
        self.headers = {
            "User-Agent": settings.edgar_user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        self.bucket = get_edgar_bucket()

    async def get(self, url: str, retries: int = 3) -> httpx.Response:
        """GET with rate limiting and exponential backoff on 429/5xx."""
        for attempt in range(retries):
            await self.bucket.acquire()
            try:
                async with httpx.AsyncClient(
                    timeout=30, headers=self.headers, follow_redirects=True
                ) as client:
                    resp = await client.get(url)

                if resp.status_code == 429:
                    wait = 5 * (2**attempt)
                    logger.warning(
                        "EDGAR 429 rate-limited, waiting %ds (attempt %d/%d)",
                        wait,
                        attempt + 1,
                        retries,
                    )
                    await asyncio.sleep(wait)
                    continue

                resp.raise_for_status()
                return resp

            except httpx.HTTPStatusError as exc:
                if attempt == retries - 1:
                    raise
                wait = 2**attempt
                logger.warning(
                    "EDGAR HTTP %d, retrying in %ds: %s",
                    exc.response.status_code,
                    wait,
                    url,
                )
                await asyncio.sleep(wait)
            except httpx.RequestError as exc:
                if attempt == retries - 1:
                    raise
                wait = 2**attempt
                logger.warning("EDGAR network error, retrying in %ds: %s", wait, exc)
                await asyncio.sleep(wait)

        raise RuntimeError(f"EDGAR request failed after {retries} attempts: {url}")

    async def get_json(self, url: str) -> dict:
        resp = await self.get(url)
        return resp.json()

    async def get_text(self, url: str) -> str:
        resp = await self.get(url)
        return resp.text


# ---------------------------------------------------------------------------
# CIK lookup
# ---------------------------------------------------------------------------


async def load_cik_cache(client: EdgarClient) -> None:
    """Download and cache the SEC company_tickers.json (symbol → CIK mapping)."""
    global _cik_cache, _cik_cache_loaded
    if _cik_cache_loaded:
        return
    try:
        data = await client.get_json(COMPANY_TICKERS_URL)
        # Format: {"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "..."}, ...}
        for entry in data.values():
            ticker = str(entry.get("ticker", "")).upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            if ticker:
                _cik_cache[ticker] = cik
        _cik_cache_loaded = True
        logger.info("Loaded %d CIK mappings from EDGAR", len(_cik_cache))
    except Exception as exc:
        logger.error("Failed to load CIK cache: %s", exc)


async def lookup_cik(client: EdgarClient, symbol: str) -> str | None:
    """
    Return the 10-digit zero-padded CIK for a ticker symbol, or None.

    Fetches company_tickers.json on first call; result is cached in-process.
    """
    await load_cik_cache(client)
    return _cik_cache.get(symbol.upper())


# ---------------------------------------------------------------------------
# Filing metadata
# ---------------------------------------------------------------------------


async def fetch_filing_metadata(
    client: EdgarClient,
    cik: str,
    filing_types: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    Fetch recent filing metadata from the EDGAR submissions API.

    Returns a list of dicts:
        {form, accession_number, filed_date, report_date, primary_document}
    """
    if filing_types is None:
        filing_types = ["10-K", "10-Q", "8-K"]

    url = f"{EDGAR_BASE}/submissions/CIK{cik}.json"
    data = await client.get_json(url)

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])

    results = []
    for i, form in enumerate(forms):
        if form not in filing_types:
            continue
        if len(results) >= limit:
            break
        results.append(
            {
                "form": form,
                "accession_number": accession_numbers[i] if i < len(accession_numbers) else None,
                "filed_date": filing_dates[i] if i < len(filing_dates) else None,
                "report_date": report_dates[i] if i < len(report_dates) else None,
                "primary_document": primary_docs[i] if i < len(primary_docs) else None,
            }
        )
    return results


def build_filing_url(cik: str, accession_number: str, primary_document: str) -> str:
    """Construct the SEC archive URL for a filing's primary document."""
    accession_clean = accession_number.replace("-", "")
    return f"{EDGAR_ARCHIVE}/{int(cik)}/{accession_clean}/{primary_document}"


# ---------------------------------------------------------------------------
# iXBRL stripping
# ---------------------------------------------------------------------------


def strip_ixbrl(html_content: str) -> str:
    """
    Strip iXBRL namespace tags from SEC filing HTML, preserving readable text.

    iXBRL wraps XBRL-tagged financial values in namespace elements (ix:nonFraction,
    ix:nonNumeric, etc.) that are browser-invisible but clutter text extraction.
    Falls back to regex stripping if lxml fails.
    """
    try:
        parser = etree.HTMLParser(recover=True)
        root = etree.fromstring(html_content.encode("utf-8", errors="replace"), parser)

        # Remove noise elements
        for tag in ("script", "style"):
            for elem in root.iter(tag):
                parent = elem.getparent()
                if parent is not None:
                    parent.remove(elem)

        # Replace iXBRL namespace elements with their contained text
        for ns in IXBRL_NAMESPACES:
            for elem in root.xpath(f"//*[namespace-uri()='{ns}']"):
                parent = elem.getparent()
                if parent is None:
                    continue
                inner = (elem.text or "") + "".join((c.text or "") + (c.tail or "") for c in elem)
                tail = elem.tail or ""
                idx = list(parent).index(elem)
                replacement = inner + tail
                if idx == 0:
                    parent.text = (parent.text or "") + replacement
                else:
                    prev = parent[idx - 1]
                    prev.tail = (prev.tail or "") + replacement
                parent.remove(elem)

        # Collect all text nodes
        parts = []
        for node in root.iter():
            if node.text:
                parts.append(node.text)
            if node.tail:
                parts.append(node.tail)
        raw = " ".join(parts)

    except Exception as exc:
        logger.warning("lxml iXBRL strip failed (%s), using regex fallback", exc)
        raw = re.sub(r"<[^>]+>", " ", html_content)

    lines = [line.strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------

_ITEM_RE = re.compile(
    r"(?:^|\n)\s*(?:ITEM|Item)\s+(\d+[A-Za-z]?)[.\s:]+([^\n]{0,120})",
    re.MULTILINE,
)


def split_into_sections(text: str) -> dict[str, str]:
    """
    Split SEC filing text into named Item sections.

    Returns a dict mapping "Item 1A" → content.
    Falls back to {"full_text": truncated} if no Item headings are found.
    """
    matches = list(_ITEM_RE.finditer(text))
    if not matches:
        return {"full_text": text[:MAX_SECTION_CHARS]}

    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        item_num = match.group(1).upper()
        section_name = f"Item {item_num}"
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            sections[section_name] = content[:MAX_SECTION_CHARS]

    return sections


# ---------------------------------------------------------------------------
# Filing download + parse
# ---------------------------------------------------------------------------


async def download_and_parse_filing(
    client: EdgarClient,
    session: AsyncSession,
    ticker: Ticker,
    filing_meta: dict,
) -> Filing | None:
    """
    Download one filing, strip iXBRL, split into sections, and store in DB.

    Skips re-download if raw_text_hash is unchanged (idempotent ingestion).
    Returns the Filing ORM object, or None on failure.
    """
    accession_no = filing_meta.get("accession_number")
    primary_doc = filing_meta.get("primary_document", "")
    cik = ticker.cik or ""

    if not accession_no or not primary_doc or not cik:
        logger.warning(
            "Skipping %s filing — incomplete metadata: %s",
            ticker.symbol,
            filing_meta,
        )
        return None

    url = build_filing_url(cik, accession_no, primary_doc)

    # Check for existing record
    result = await session.execute(select(Filing).where(Filing.accession_number == accession_no))
    existing = result.scalar_one_or_none()

    # Download HTML
    logger.info(
        "Downloading %s %s for %s", filing_meta.get("form", "filing"), accession_no, ticker.symbol
    )
    try:
        html = await client.get_text(url)
    except Exception as exc:
        logger.error("Failed to download %s: %s", accession_no, exc)
        return None

    content_hash = hashlib.sha256(html.encode()).hexdigest()

    if existing and existing.raw_text_hash == content_hash:
        logger.debug("Filing %s unchanged (hash match), skipping re-parse", accession_no)
        return existing

    # Parse dates
    filed_date: date | None = None
    report_date: date | None = None
    if filing_meta.get("filed_date"):
        try:
            filed_date = date.fromisoformat(filing_meta["filed_date"])
        except ValueError:
            pass
    if filing_meta.get("report_date"):
        try:
            report_date = date.fromisoformat(filing_meta["report_date"])
        except ValueError:
            pass

    # Upsert Filing record
    if existing:
        filing = existing
        filing.raw_text_hash = content_hash
        filing.is_parsed = False
        filing.is_analyzed = False
        filing.parse_error = None
    else:
        filing = Filing(
            ticker_id=ticker.id,
            filing_type=filing_meta.get("form", ""),
            period_of_report=report_date,
            filed_date=filed_date,
            accession_number=accession_no,
            primary_document_url=url,
            raw_text_hash=content_hash,
            is_parsed=False,
            is_analyzed=False,
        )
        session.add(filing)

    await session.flush()

    # Wipe old sections before re-parse
    if existing:
        await session.execute(sa_delete(FilingSection).where(FilingSection.filing_id == filing.id))

    # Strip iXBRL and split into sections
    text = strip_ixbrl(html)
    sections = split_into_sections(text)

    for section_name, content in sections.items():
        session.add(
            FilingSection(
                filing_id=filing.id,
                section_name=section_name,
                content=content,
                word_count=len(content.split()),
            )
        )

    filing.is_parsed = True
    session.add(filing)
    await session.flush()

    logger.info("Parsed %s for %s: %d sections", accession_no, ticker.symbol, len(sections))
    return filing


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def fetch_filings_for_ticker(
    session: AsyncSession,
    ticker: Ticker,
    filing_types: list[str] | None = None,
    limit: int = 5,
) -> list[Filing]:
    """
    Fetch and parse recent SEC filings for a ticker.

    Requires ticker.cik to be set. Use update_ticker_cik() first.
    Returns list of Filing ORM objects (new or updated).
    """
    if not ticker.cik:
        logger.warning("No CIK for %s — run update_ticker_cik() first", ticker.symbol)
        return []

    client = EdgarClient()
    filing_types = filing_types or ["10-K", "10-Q", "8-K"]

    try:
        meta_list = await fetch_filing_metadata(client, ticker.cik, filing_types, limit)
    except Exception as exc:
        logger.error("Failed to fetch filing metadata for %s: %s", ticker.symbol, exc)
        return []

    filings: list[Filing] = []
    for meta in meta_list:
        filing = await download_and_parse_filing(client, session, ticker, meta)
        if filing:
            filings.append(filing)

    return filings


async def update_ticker_cik(session: AsyncSession, ticker: Ticker) -> bool:
    """
    Look up and store the SEC CIK for a ticker.

    Returns True if CIK was found and saved.
    """
    client = EdgarClient()
    cik = await lookup_cik(client, ticker.symbol)
    if cik:
        ticker.cik = cik
        session.add(ticker)
        await session.flush()
        logger.info("CIK for %s: %s", ticker.symbol, cik)
        return True
    logger.warning("CIK not found for %s", ticker.symbol)
    return False
