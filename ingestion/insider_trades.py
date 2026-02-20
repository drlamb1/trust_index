"""
EdgeFinder — Insider Trades (SEC Form 4) Parser

Fetches and parses Form 4 (Statement of Changes in Beneficial Ownership) XML
filings to track insider buying and selling activity.

Cluster buys (3+ insiders buying within 7 days) are a high-signal bullish
indicator, especially when the stock has recently declined.

Flow:
    1. Fetch Form 4 metadata for ticker's CIK from EDGAR
    2. Download each Form 4 XML document
    3. Parse insider name, title, transaction type, shares, price
    4. Store InsiderTrade rows (dedup via accession number)

Transaction codes (SEC Form 4 spec):
    P = Open market purchase       → BUY
    S = Open market sale           → SELL
    A = Grant / award              → GRANT
    M = Option exercise            → EXERCISE
    F = Tax withholding (skip)
    G = Gift (skip)
    J, U, C, X, O, etc. (skip — not market transactions)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import InsiderTrade, InsiderTradeType, Ticker

logger = logging.getLogger(__name__)

# Mapping from Form 4 transaction code → InsiderTradeType enum value
TRADE_CODE_MAP: dict[str, InsiderTradeType] = {
    "P": InsiderTradeType.BUY,
    "S": InsiderTradeType.SELL,
    "A": InsiderTradeType.GRANT,
    "M": InsiderTradeType.EXERCISE,
}

# Codes to ignore (non-market, tax-related, or gift transactions)
SKIP_CODES = frozenset({"F", "G", "J", "U", "C", "X", "O"})


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------


def _text(elem: ET.Element | None, path: str, default: str = "") -> str:
    """Safely extract and strip text from an XML sub-element path."""
    if elem is None:
        return default
    node = elem.find(path)
    return node.text.strip() if node is not None and node.text else default


def _float(elem: ET.Element | None, path: str) -> float | None:
    """Safely extract a float value from an XML sub-element path."""
    raw = _text(elem, path)
    if not raw:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _date(elem: ET.Element | None, path: str) -> date | None:
    """Safely extract a date (YYYY-MM-DD) from an XML sub-element path."""
    raw = _text(elem, path)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Form 4 parser
# ---------------------------------------------------------------------------


def parse_form4_xml(
    xml_content: str,
    accession_number: str,
    ticker_id: int,
) -> list[InsiderTrade]:
    """
    Parse a Form 4 XML document and return InsiderTrade ORM objects.

    The objects are NOT yet added to any session — caller is responsible.

    Args:
        xml_content:      Raw XML string from EDGAR.
        accession_number: Filing accession number (for deduplication).
        ticker_id:        Database ID of the associated Ticker.

    Returns:
        List of InsiderTrade instances (may be empty on parse failure).
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        logger.error("Form 4 XML parse error (%s): %s", accession_number, exc)
        return []

    reporter = root.find("reportingOwner")
    if reporter is None:
        logger.warning("No reportingOwner in Form 4 %s", accession_number)
        return []

    insider_name = _text(reporter, "reportingOwnerId/rptOwnerName") or "Unknown"
    relationship = reporter.find("reportingOwnerRelationship")
    insider_title = _resolve_title(relationship)

    trades: list[InsiderTrade] = []

    # Non-derivative (direct stock) transactions
    for txn in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        trade = _parse_txn(txn, ticker_id, accession_number, insider_name, insider_title)
        if trade:
            trades.append(trade)

    # Derivative (options / warrants) transactions
    for txn in root.findall("derivativeTable/derivativeTransaction"):
        trade = _parse_txn(
            txn, ticker_id, accession_number, insider_name, insider_title, is_derivative=True
        )
        if trade:
            trades.append(trade)

    return trades


def _resolve_title(relationship: ET.Element | None) -> str | None:
    """Determine the insider's role from the reportingOwnerRelationship element."""
    if relationship is None:
        return None
    officer_title = _text(relationship, "officerTitle")
    if officer_title:
        return officer_title
    if _text(relationship, "isDirector") == "1":
        return "Director"
    if _text(relationship, "isTenPercentOwner") == "1":
        return "10% Owner"
    if _text(relationship, "isOfficer") == "1":
        return "Officer"
    return None


def _parse_txn(
    txn: ET.Element,
    ticker_id: int,
    accession_number: str,
    insider_name: str,
    insider_title: str | None,
    is_derivative: bool = False,
) -> InsiderTrade | None:
    """Parse a single transaction element from a Form 4 XML."""
    code = _text(txn, "transactionCoding/transactionCode")
    if not code or code in SKIP_CODES:
        return None

    trade_type = TRADE_CODE_MAP.get(code)
    if trade_type is None:
        return None

    # Acquired (A) vs Disposed (D) refines the trade type
    ad_code = _text(txn, "transactionAmounts/transactionAcquiredDisposedCode/value")
    if ad_code == "D" and trade_type == InsiderTradeType.BUY:
        trade_type = InsiderTradeType.SELL

    transaction_date = _date(txn, "transactionDate/value")
    shares = _float(txn, "transactionAmounts/transactionShares/value")
    price = _float(txn, "transactionAmounts/transactionPricePerShare/value")
    shares_after = _float(txn, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
    total = (shares * price) if (shares is not None and price is not None) else None

    return InsiderTrade(
        ticker_id=ticker_id,
        accession_number=accession_number,
        insider_name=insider_name,
        insider_title=insider_title,
        trade_type=trade_type.value,
        shares=shares,
        price_per_share=price,
        total_amount=total,
        shares_owned_after=shares_after,
        transaction_date=transaction_date,
        filed_date=None,  # Populated by caller from filing metadata
    )


# ---------------------------------------------------------------------------
# Cluster buy detection
# ---------------------------------------------------------------------------


def detect_cluster_buy(
    trades: list[InsiderTrade],
    window_days: int = 7,
    min_insiders: int = 3,
) -> bool:
    """
    Return True if ≥ `min_insiders` distinct insiders made open-market buys
    within any `window_days`-day rolling window.

    This is a high-conviction bullish signal when the stock has recently declined.
    """
    buys = [t for t in trades if t.trade_type == InsiderTradeType.BUY.value and t.transaction_date]
    if len(buys) < min_insiders:
        return False

    buys_sorted = sorted(buys, key=lambda t: t.transaction_date)
    window = timedelta(days=window_days)

    for i, anchor in enumerate(buys_sorted):
        cutoff = anchor.transaction_date + window
        insiders_in_window = {
            b.insider_name for b in buys_sorted[i:] if b.transaction_date <= cutoff
        }
        if len(insiders_in_window) >= min_insiders:
            return True

    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def fetch_and_store_insider_trades(
    session: AsyncSession,
    ticker: Ticker,
    limit: int = 20,
) -> int:
    """
    Fetch recent Form 4 filings for a ticker and store insider trades.

    Skips accession numbers already in the database (idempotent).
    Returns number of new trade records stored.
    """
    if not ticker.cik:
        logger.warning("No CIK for %s — skipping insider trades", ticker.symbol)
        return 0

    from ingestion.sec_edgar import EdgarClient, build_filing_url, fetch_filing_metadata

    client = EdgarClient()

    try:
        meta_list = await fetch_filing_metadata(client, ticker.cik, filing_types=["4"], limit=limit)
    except Exception as exc:
        logger.error("Failed to fetch Form 4 metadata for %s: %s", ticker.symbol, exc)
        return 0

    new_count = 0
    for meta in meta_list:
        accession_no = meta.get("accession_number")
        primary_doc = meta.get("primary_document")
        if not accession_no or not primary_doc:
            continue

        # Dedup: skip if any trade with this accession number exists
        existing = await session.execute(
            select(InsiderTrade).where(InsiderTrade.accession_number == accession_no).limit(1)
        )
        if existing.scalar_one_or_none():
            continue

        url = build_filing_url(ticker.cik, accession_no, primary_doc)
        try:
            xml = await client.get_text(url)
        except Exception as exc:
            logger.error("Failed to download Form 4 %s: %s", accession_no, exc)
            continue

        filed_date: date | None = None
        if meta.get("filed_date"):
            try:
                filed_date = date.fromisoformat(meta["filed_date"])
            except ValueError:
                pass

        for trade in parse_form4_xml(xml, accession_no, ticker.id):
            trade.filed_date = filed_date
            session.add(trade)
            new_count += 1

    if new_count:
        await session.flush()
        logger.info("Stored %d new insider trades for %s", new_count, ticker.symbol)

    return new_count
