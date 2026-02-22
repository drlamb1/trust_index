"""
EdgeFinder — Investment Thesis Matcher

Auto-discovers tickers that match defined investment theses by combining:
  1. Quantitative screens (financial criteria from theses.yaml)
  2. Keyword density in SEC filing MD&A/Business sections
  3. Sector and market-cap gating

Scoring (0-100):
  50 pts — financial criteria (proportional to criteria satisfied)
  50 pts — keyword density in latest 10-K/10-Q MD&A section

ThesisMatch records are upserted weekly. The score is the primary sort key.

Entry points:
    count = await run_thesis_matching(session)          # all theses, all tickers
    matches = await match_thesis(session, thesis_slug)  # one thesis
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import and_, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Filing,
    FilingAnalysis,
    FilingSection,
    FinancialMetric,
    Thesis,
    ThesisMatch,
    Ticker,
)

logger = logging.getLogger(__name__)

_THESES_YAML = Path(__file__).parent.parent / "config" / "theses.yaml"


# ---------------------------------------------------------------------------
# Thesis YAML loading
# ---------------------------------------------------------------------------


def load_theses_yaml() -> dict[str, dict]:
    """Load and return the theses definitions from theses.yaml."""
    with _THESES_YAML.open() as f:
        data = yaml.safe_load(f)
    return data.get("theses", {})


# ---------------------------------------------------------------------------
# Sync Thesis table from YAML
# ---------------------------------------------------------------------------


async def sync_theses(session: AsyncSession) -> int:
    """
    Upsert Thesis records from theses.yaml.
    Returns the number of rows upserted.
    """
    theses_data = load_theses_yaml()
    count = 0
    for slug, defn in theses_data.items():
        result = await session.execute(select(Thesis).where(Thesis.slug == slug))
        thesis = result.scalar_one_or_none()
        if thesis is None:
            thesis = Thesis(slug=slug)
            session.add(thesis)

        thesis.name = defn.get("name", slug)
        thesis.description = defn.get("description", "")
        thesis.criteria_yaml = yaml.dump({slug: defn})
        thesis.is_active = True
        count += 1

    await session.flush()
    logger.info("sync_theses: %d theses upserted", count)
    return count


# ---------------------------------------------------------------------------
# Financial criteria scorer
# ---------------------------------------------------------------------------


def _check_financial_criteria(
    criteria: dict[str, Any],
    metrics: dict[str, float],
) -> tuple[float, list[str]]:
    """
    Score a ticker against financial criteria.
    Returns (score 0-100, list of reasons for the score).
    """
    if not criteria:
        return 100.0, ["no financial criteria"]

    # Map criteria keys to metric names
    _KEY_MAP = {
        "revenue_growth_yoy_min": "revenue_growth_pct",
        "gross_margin_min": "gross_margin_pct",
        "rd_spend_pct_min": "rd_spend_pct",
        "pe_ratio_max": "pe_ratio",
        "price_to_book_max": "price_to_book",
        "fcf_yield_min": "fcf_yield",
        "debt_to_equity_max": "debt_to_equity",
        "roe_min": "roe",
        "dividend_yield_min": "dividend_yield",
        "net_revenue_retention_min": "net_revenue_retention",
        "operating_margin_min": "operating_margin_pct",
    }

    satisfied = 0
    total = 0
    reasons: list[str] = []

    for key, threshold in criteria.items():
        metric_name = _KEY_MAP.get(key, key)
        value = metrics.get(metric_name)
        if value is None:
            continue  # Skip unavailable metrics — don't penalize

        total += 1
        if key.endswith("_min"):
            if value >= threshold:
                satisfied += 1
                reasons.append(f"{metric_name} {value:.1f}% ≥ {threshold}%")
            else:
                reasons.append(f"{metric_name} {value:.1f}% < {threshold}% (miss)")
        elif key.endswith("_max"):
            if value <= threshold:
                satisfied += 1
                reasons.append(f"{metric_name} {value:.1f} ≤ {threshold}")
            else:
                reasons.append(f"{metric_name} {value:.1f} > {threshold} (miss)")

    if total == 0:
        return 50.0, ["no metrics available"]

    score = (satisfied / total) * 100.0
    return score, reasons


# ---------------------------------------------------------------------------
# Keyword density scorer
# ---------------------------------------------------------------------------


def _keyword_density_score(text_content: str, keywords: list[str]) -> tuple[float, list[str]]:
    """
    Score keyword density in a text body.
    Returns (score 0-100, list of matched keywords).
    """
    if not keywords or not text_content:
        return 0.0, []

    text_lower = text_content.lower()
    word_count = max(1, len(text_lower.split()))
    matched: list[str] = []

    for kw in keywords:
        pattern = re.compile(re.escape(kw.lower()))
        occurrences = len(pattern.findall(text_lower))
        if occurrences > 0:
            matched.append(kw)

    if not matched:
        return 0.0, []

    # Score = (matched_keywords / total_keywords) * density_multiplier
    # Density multiplier rewards more keyword matches
    match_ratio = len(matched) / len(keywords)
    score = min(100.0, match_ratio * 100.0 * 1.2)  # slight boost for partial matches
    return score, matched


# ---------------------------------------------------------------------------
# Metrics aggregator per ticker
# ---------------------------------------------------------------------------


async def _get_ticker_metrics(session: AsyncSession, ticker: Ticker) -> dict[str, float]:
    """
    Build a flat dict of metric_name → value for a ticker.
    Sources: FinancialMetric table + FilingAnalysis.financial_metrics JSONB.
    """
    metrics: dict[str, float] = {}

    # From FinancialMetric table (most recent per metric_name)
    fm_result = await session.execute(
        select(FinancialMetric.metric_name, FinancialMetric.value)
        .where(FinancialMetric.ticker_id == ticker.id)
        .order_by(desc(FinancialMetric.period_end_date))
    )
    for name, value in fm_result.fetchall():
        if name not in metrics and value is not None:
            metrics[name] = float(value)

    # From FilingAnalysis.financial_metrics JSONB (richer, extracted by Claude)
    fa_result = await session.execute(
        select(FilingAnalysis.financial_metrics)
        .join(Filing, FilingAnalysis.filing_id == Filing.id)
        .where(
            Filing.ticker_id == ticker.id,
            Filing.filing_type.in_(["10-K", "10-Q"]),
            FilingAnalysis.financial_metrics.isnot(None),
        )
        .order_by(desc(Filing.filed_date))
        .limit(1)
    )
    fa_metrics = fa_result.scalar_one_or_none()
    if fa_metrics and isinstance(fa_metrics, dict):
        for k, v in fa_metrics.items():
            if k not in metrics and v is not None:
                try:
                    metrics[k] = float(v)
                except (TypeError, ValueError):
                    pass

    return metrics


# ---------------------------------------------------------------------------
# Filing text fetcher
# ---------------------------------------------------------------------------


async def _get_mda_text(session: AsyncSession, ticker: Ticker) -> str:
    """Get the latest MD&A section text for a ticker (10-K or 10-Q)."""
    result = await session.execute(
        select(FilingSection.content)
        .join(Filing, FilingSection.filing_id == Filing.id)
        .where(
            Filing.ticker_id == ticker.id,
            Filing.filing_type.in_(["10-K", "10-Q"]),
            FilingSection.section_name.ilike("%management%discussion%"),
        )
        .order_by(desc(Filing.filed_date))
        .limit(1)
    )
    content = result.scalar_one_or_none()
    if content:
        return content

    # Fallback: any section from latest filing
    result2 = await session.execute(
        select(FilingSection.content)
        .join(Filing, FilingSection.filing_id == Filing.id)
        .where(
            Filing.ticker_id == ticker.id,
            Filing.filing_type.in_(["10-K", "10-Q"]),
        )
        .order_by(desc(Filing.filed_date), FilingSection.id)
        .limit(1)
    )
    return result2.scalar_one_or_none() or ""


# ---------------------------------------------------------------------------
# Single thesis scorer
# ---------------------------------------------------------------------------


async def _score_ticker_for_thesis(
    session: AsyncSession,
    ticker: Ticker,
    thesis_defn: dict,
) -> dict | None:
    """
    Score one ticker against one thesis definition.
    Returns match_reasons dict or None if ticker fails hard gates (sector, market_cap).
    """
    # Hard gate: sector filter
    sector_filter = thesis_defn.get("sector_filter") or []
    if sector_filter and ticker.sector not in sector_filter:
        return None

    # Hard gate: market cap
    mc = ticker.market_cap
    mc_min = thesis_defn.get("market_cap_min")
    mc_max = thesis_defn.get("market_cap_max")
    if mc is not None:
        if mc_min and mc < mc_min:
            return None
        if mc_max and mc > mc_max:
            return None

    # Hard gate: exclusions
    exclusions = thesis_defn.get("exclusions") or []
    if ticker.symbol in exclusions:
        return None

    # Financial criteria (50% of score)
    metrics = await _get_ticker_metrics(session, ticker)
    financial_score, fin_reasons = _check_financial_criteria(
        thesis_defn.get("financial_criteria") or {}, metrics
    )

    # Keyword density (50% of score)
    keywords = thesis_defn.get("keywords") or []
    if keywords:
        mda_text = await _get_mda_text(session, ticker)
        keyword_score, matched_kws = _keyword_density_score(mda_text, keywords)
    else:
        keyword_score = 100.0  # pure quant thesis — no keyword filter
        matched_kws = []

    composite = financial_score * 0.5 + keyword_score * 0.5

    return {
        "score": round(composite, 1),
        "financial_score": round(financial_score, 1),
        "keyword_score": round(keyword_score, 1),
        "matched_keywords": matched_kws[:10],  # cap for storage
        "financial_reasons": fin_reasons[:10],
        "sector": ticker.sector,
    }


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def match_thesis(session: AsyncSession, thesis_slug: str) -> list[dict]:
    """
    Run thesis matching for one thesis against all active tickers.
    Upserts ThesisMatch records. Returns list of (symbol, score) dicts.
    """
    theses_data = load_theses_yaml()
    if thesis_slug not in theses_data:
        logger.warning("Thesis '%s' not found in theses.yaml", thesis_slug)
        return []

    thesis_defn = theses_data[thesis_slug]

    # Ensure Thesis row exists
    result = await session.execute(select(Thesis).where(Thesis.slug == thesis_slug))
    thesis_row = result.scalar_one_or_none()
    if thesis_row is None:
        await sync_theses(session)
        result = await session.execute(select(Thesis).where(Thesis.slug == thesis_slug))
        thesis_row = result.scalar_one_or_none()
        if thesis_row is None:
            return []

    # Fetch all active tickers
    tickers_result = await session.execute(
        select(Ticker).where(Ticker.is_active.is_(True))
    )
    tickers = tickers_result.scalars().all()

    matches: list[dict] = []

    for ticker in tickers:
        reasons = await _score_ticker_for_thesis(session, ticker, thesis_defn)
        if reasons is None or reasons["score"] < 10:
            continue  # Doesn't qualify or negligible match

        # Upsert ThesisMatch
        match_result = await session.execute(
            select(ThesisMatch).where(
                ThesisMatch.thesis_id == thesis_row.id,
                ThesisMatch.ticker_id == ticker.id,
            )
        )
        tm = match_result.scalar_one_or_none()
        if tm is None:
            tm = ThesisMatch(thesis_id=thesis_row.id, ticker_id=ticker.id)
            session.add(tm)

        tm.score = reasons["score"]
        tm.match_reasons = reasons

        matches.append({"symbol": ticker.symbol, **reasons})

    await session.flush()
    matches.sort(key=lambda x: x["score"], reverse=True)
    logger.info(
        "match_thesis '%s': %d matches from %d tickers", thesis_slug, len(matches), len(tickers)
    )
    return matches


async def run_thesis_matching(session: AsyncSession) -> int:
    """
    Run thesis matching for all active theses against all active tickers.
    Returns total ThesisMatch records upserted.
    """
    # Sync thesis definitions from YAML
    await sync_theses(session)

    theses_data = load_theses_yaml()
    total = 0

    for slug in theses_data:
        result = await session.execute(
            select(Thesis).where(Thesis.slug == slug, Thesis.is_active.is_(True))
        )
        thesis_row = result.scalar_one_or_none()
        if thesis_row is None:
            continue

        matches = await match_thesis(session, slug)
        total += len(matches)

    await session.commit()
    logger.info("run_thesis_matching: %d total thesis matches upserted", total)
    return total
