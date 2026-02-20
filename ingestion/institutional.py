"""
EdgeFinder — 13F-HR Institutional Holdings Tracker

Tracks quarterly 13F-HR filings to monitor institutional position changes.
Any investment manager with >$100M in US equities must file 13F within
45 days of each quarter-end.

Flow:
    1. Fetch 13F-HR filings from EDGAR for a given institution CIK
    2. Download and parse the InfoTable XML
    3. Match holdings to tickers in our DB by CUSIP or company name
    4. Compute quarter-over-quarter position changes
    5. Store InstitutionalHolding records

Note: CUSIP-to-ticker mapping requires a data source (not included here).
Holdings are stored with company name; name-based matching is used
when an exact CUSIP match is unavailable.
"""

from __future__ import annotations

import logging
from datetime import date
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import InstitutionalHolding, Ticker

logger = logging.getLogger(__name__)

# 13F XML namespace
_13F_NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"
_13F_NS_PREFIX = f"{{{_13F_NS}}}"


# ---------------------------------------------------------------------------
# 13F InfoTable XML parser
# ---------------------------------------------------------------------------


def parse_13f_xml(
    xml_content: str,
    institution_name: str,
    institution_cik: str,
    period_date: date,
) -> list[dict]:
    """
    Parse a 13F-HR InfoTable XML and return a list of holding dicts.

    Each dict contains:
        name_of_issuer, cusip, value_thousands, shares, period_date,
        institution_name, institution_cik

    The value field is in thousands of USD (as filed with SEC).
    """
    holdings = []

    try:
        # Try with namespace first, then without
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        logger.error("13F XML parse error for %s: %s", institution_name, exc)
        return []

    def find_tables(root: ET.Element) -> list[ET.Element]:
        """Find infoTable elements with or without namespace."""
        tables = root.findall(f"{_13F_NS_PREFIX}infoTable")
        if not tables:
            tables = root.findall(".//infoTable")
        if not tables:
            tables = root.findall(f".//{_13F_NS_PREFIX}infoTable")
        return tables

    for table in find_tables(root):
        name = _tag_text(table, "nameOfIssuer") or _tag_text(table, f"{_13F_NS_PREFIX}nameOfIssuer")
        cusip = _tag_text(table, "cusip") or _tag_text(table, f"{_13F_NS_PREFIX}cusip")
        value_raw = _tag_text(table, "value") or _tag_text(table, f"{_13F_NS_PREFIX}value")
        shares_raw = _tag_text(table, "shrsOrPrnAmt/sshPrnamt") or _tag_text(
            table, f"{_13F_NS_PREFIX}shrsOrPrnAmt/{_13F_NS_PREFIX}sshPrnamt"
        )

        if not name:
            continue

        try:
            value_thousands = int(value_raw.replace(",", "")) if value_raw else None
        except ValueError:
            value_thousands = None

        try:
            shares = float(shares_raw.replace(",", "")) if shares_raw else None
        except ValueError:
            shares = None

        holdings.append(
            {
                "name_of_issuer": name.strip(),
                "cusip": (cusip or "").strip(),
                "value_thousands": value_thousands,
                "shares": shares,
                "market_value": (value_thousands * 1000) if value_thousands else None,
                "period_date": period_date,
                "institution_name": institution_name,
                "institution_cik": institution_cik,
            }
        )

    return holdings


def _tag_text(elem: ET.Element, path: str) -> str | None:
    """Safely extract text from an XML path."""
    node = elem.find(path)
    return node.text.strip() if node is not None and node.text else None


# ---------------------------------------------------------------------------
# Ticker matching
# ---------------------------------------------------------------------------


async def match_holding_to_ticker(
    session: AsyncSession,
    holding: dict,
) -> Ticker | None:
    """
    Attempt to match a 13F holding to a Ticker in our DB.

    First tries CUSIP-based matching (not yet implemented — requires reference data).
    Falls back to partial name matching on the ticker's company name field.
    Returns None if no confident match is found.
    """
    # Name-based matching (case-insensitive prefix search)
    issuer_name = holding["name_of_issuer"].upper()

    result = await session.execute(select(Ticker).where(Ticker.is_active.is_(True)))
    tickers = result.scalars().all()

    # Simple heuristic: match if ticker name starts with or contains the issuer name
    for ticker in tickers:
        if not ticker.name:
            continue
        ticker_name_upper = ticker.name.upper()
        # Require substantial overlap (first word of issuer name in ticker name)
        first_word = issuer_name.split()[0] if issuer_name else ""
        if first_word and len(first_word) >= 4 and first_word in ticker_name_upper:
            return ticker

    return None


# ---------------------------------------------------------------------------
# Compute position changes
# ---------------------------------------------------------------------------


async def compute_position_change(
    session: AsyncSession,
    ticker_id: int,
    institution_cik: str,
    current_shares: float | None,
    period_date: date,
) -> float | None:
    """
    Compute the quarter-over-quarter position change in shares.

    Finds the most recent prior period holding and computes the difference.
    Returns None if no prior period exists.
    """
    result = await session.execute(
        select(InstitutionalHolding)
        .where(
            InstitutionalHolding.ticker_id == ticker_id,
            InstitutionalHolding.institution_cik == institution_cik,
            InstitutionalHolding.period_date < period_date,
        )
        .order_by(InstitutionalHolding.period_date.desc())
        .limit(1)
    )
    prior = result.scalar_one_or_none()

    if prior is None or prior.shares is None or current_shares is None:
        return None

    return current_shares - prior.shares


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def store_13f_holdings(
    session: AsyncSession,
    holdings: list[dict],
) -> int:
    """
    Match and store a list of parsed 13F holdings to InstitutionalHolding records.

    Returns the number of holdings stored.
    """
    stored = 0
    for holding in holdings:
        ticker = await match_holding_to_ticker(session, holding)
        if ticker is None:
            continue  # No confident match — skip

        period_date = holding["period_date"]
        institution_cik = holding["institution_cik"]
        institution_name = holding["institution_name"]
        current_shares = holding.get("shares")

        # Dedup: check if this period already exists
        existing = await session.execute(
            select(InstitutionalHolding).where(
                InstitutionalHolding.ticker_id == ticker.id,
                InstitutionalHolding.institution_cik == institution_cik,
                InstitutionalHolding.period_date == period_date,
            )
        )
        if existing.scalar_one_or_none():
            continue

        change_shares = await compute_position_change(
            session, ticker.id, institution_cik, current_shares, period_date
        )
        change_pct: float | None = None
        if change_shares is not None and current_shares and current_shares != 0:
            prior_shares = current_shares - change_shares
            if prior_shares != 0:
                change_pct = (change_shares / prior_shares) * 100

        ih = InstitutionalHolding(
            ticker_id=ticker.id,
            institution_name=institution_name,
            institution_cik=institution_cik,
            shares=current_shares,
            market_value=holding.get("market_value"),
            period_date=period_date,
            change_shares=change_shares,
            change_pct=change_pct,
        )
        session.add(ih)
        stored += 1

    if stored:
        await session.flush()
        logger.info("Stored %d institutional holdings", stored)

    return stored
