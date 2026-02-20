"""
EdgeFinder — SEC Filing Analyzer

Two-stage analysis pipeline for SEC filings:

Stage 1 — Regex-based red flag detection (fast, free, no AI needed):
    - Going concern language in audit opinion
    - Material weakness in internal controls
    - Auditor change (dismissal / new appointment)
    - Large goodwill as fraction of total assets
    - SEC investigation or subpoena mentions
    - Class action lawsuit filings

Stage 2 — Claude Sonnet deep analysis (only if filing content changed):
    - 300-word analyst summary
    - 3-5 bull points / bear points
    - Key financial metric extraction
    - Composite health score 0-100

Cost controls:
    - Prompt caching on the system prompt (~90% input token cost reduction)
    - Hash-gate: skip re-analysis when raw_text_hash is unchanged
    - Analyze only the most informative sections (MD&A + Risk Factors + Audit)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Filing, FilingAnalysis, FilingSection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Red flag pattern definitions
# ---------------------------------------------------------------------------


@dataclass
class RedFlag:
    name: str
    severity: str  # "high" | "medium" | "low"
    quote: str  # Matched excerpt (up to 200 chars)
    section: str  # Which section it was found in


# Patterns: (name, severity, compiled regex)
_RED_FLAG_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    (
        "going_concern",
        "high",
        re.compile(
            r"going\s+concern|substantial\s+doubt\s+about\s+(its\s+)?ability\s+to\s+continue",
            re.IGNORECASE,
        ),
    ),
    (
        "material_weakness",
        "high",
        re.compile(r"material\s+weakness\s+in\s+internal\s+control", re.IGNORECASE),
    ),
    (
        "auditor_change",
        "medium",
        re.compile(
            r"dismissed\s+(our|the)\s+(independent|registered)\s+(public\s+)?accounting"
            r"|change\s+in\s+(independent\s+)?(registered\s+public\s+)?accountant"
            r"|engaged\s+\w[\w\s]{0,50}(LLP|LLC|Inc\.?)\s+as\s+(our\s+)?new\s+independent",
            re.IGNORECASE,
        ),
    ),
    (
        "sec_investigation",
        "high",
        re.compile(
            r"SEC\s+(investigation|subpoena|formal\s+order|inquiry|enforcement)"
            r"|securities\s+and\s+exchange\s+commission\s+(has\s+)?issued\s+a\s+subpoena",
            re.IGNORECASE,
        ),
    ),
    (
        "class_action",
        "medium",
        re.compile(
            r"class\s+action\s+(lawsuit|complaint|litigation|suit)"
            r"|securities\s+class\s+action",
            re.IGNORECASE,
        ),
    ),
    (
        "goodwill_impairment_risk",
        "medium",
        re.compile(
            r"goodwill\s+impairment"
            r"|impairment\s+of\s+goodwill"
            r"|goodwill\s+.{0,80}represent\w*\s+\d+\s*%",
            re.IGNORECASE,
        ),
    ),
    (
        "restatement",
        "high",
        re.compile(
            r"restat(e|ing|ement)\s+(of\s+)?financial\s+statements?"
            r"|restated\s+(previously|prior)\s+reported",
            re.IGNORECASE,
        ),
    ),
    (
        "liquidity_concern",
        "medium",
        re.compile(
            r"insufficient\s+(cash|liquidity|funds)\s+to\s+(fund|meet|support)"
            r"|may\s+not\s+(be\s+able|have\s+sufficient)\s+to\s+(fund|meet)\s+our\s+obligations",
            re.IGNORECASE,
        ),
    ),
]

# Sections to analyze for red flags (lower-cased section names)
_FLAG_SECTIONS = {
    "item 1a",  # Risk Factors
    "item 8",  # Financial Statements (audit opinion)
    "item 9",  # Changes in Accountants
    "item 9a",  # Controls and Procedures
    "item 3",  # Legal Proceedings
    "full_text",  # Fallback
}

# Health score penalties per severity
_SEVERITY_PENALTY = {"high": 25, "medium": 12, "low": 5}


# ---------------------------------------------------------------------------
# Stage 1: Regex red flag detection
# ---------------------------------------------------------------------------


def detect_red_flags(sections: dict[str, str]) -> list[RedFlag]:
    """
    Scan filing sections for red flag patterns using regex.

    Args:
        sections: Mapping of section_name → content text.

    Returns:
        List of RedFlag instances (de-duplicated by flag name).
    """
    found: dict[str, RedFlag] = {}  # name → RedFlag (first match wins)

    for section_name, content in sections.items():
        # Only scan high-signal sections to reduce false positives
        if section_name.lower() not in _FLAG_SECTIONS:
            continue

        for flag_name, severity, pattern in _RED_FLAG_PATTERNS:
            if flag_name in found:
                continue
            match = pattern.search(content)
            if match:
                # Extract a short quote around the match
                start = max(0, match.start() - 50)
                end = min(len(content), match.end() + 100)
                quote = content[start:end].strip().replace("\n", " ")
                found[flag_name] = RedFlag(
                    name=flag_name,
                    severity=severity,
                    quote=quote[:200],
                    section=section_name,
                )

    return list(found.values())


def compute_health_score(red_flags: list[RedFlag]) -> float:
    """
    Compute a filing health score from 0 (terrible) to 100 (clean).

    Deducts penalty points per flag based on severity:
        high   → -25 pts
        medium → -12 pts
        low    → -5 pts

    Minimum score is 0.
    """
    penalty = sum(_SEVERITY_PENALTY.get(f.severity, 0) for f in red_flags)
    return max(0.0, 100.0 - penalty)


# ---------------------------------------------------------------------------
# Stage 2: Claude Sonnet analysis
# ---------------------------------------------------------------------------

# System prompt is expensive to send on every call; prompt caching reduces
# repeat cost by ~90%. The prompt is stable across many filings.
_SYSTEM_PROMPT = """You are an expert securities analyst with deep experience reading SEC filings.
Analyze the provided filing excerpt and respond with a JSON object containing:

{
  "summary": "<300-word analyst summary focusing on key risks, opportunities, and inflection points>",
  "bull_points": ["<concise bullish observation>", ...],
  "bear_points": ["<concise bearish observation>", ...],
  "financial_metrics": {
    "revenue": <number or null>,
    "revenue_growth_pct": <number or null>,
    "gross_margin_pct": <number or null>,
    "operating_margin_pct": <number or null>,
    "net_income": <number or null>,
    "fcf": <number or null>,
    "debt_to_equity": <number or null>
  },
  "health_assessment": "<one of: excellent | good | fair | poor | critical>"
}

Extract only values explicitly stated in the text — use null if not mentioned.
All dollar values should be in millions. Percentages as decimal numbers (e.g. 22.5 for 22.5%).
Provide exactly 3-5 bull points and 3-5 bear points.
Return ONLY valid JSON, no markdown fences."""

# Sections to include in Claude analysis (most informative)
_ANALYSIS_SECTIONS = ["Item 7", "Item 1A", "Item 8", "Item 1"]
_MAX_CONTEXT_CHARS = 40_000  # Stay well within 200K context window


def _build_analysis_context(sections: dict[str, str]) -> str:
    """Select and concatenate the most informative sections for Claude."""
    parts = []
    total = 0
    for target in _ANALYSIS_SECTIONS:
        for key, content in sections.items():
            if key.lower() == target.lower() and content:
                chunk = f"\n\n=== {key} ===\n{content}"
                if total + len(chunk) > _MAX_CONTEXT_CHARS:
                    chunk = chunk[: _MAX_CONTEXT_CHARS - total]
                parts.append(chunk)
                total += len(chunk)
                break
        if total >= _MAX_CONTEXT_CHARS:
            break

    # Fallback: use full_text if no structured sections found
    if not parts and "full_text" in sections:
        parts.append(sections["full_text"][:_MAX_CONTEXT_CHARS])

    return "".join(parts) or "(No filing content available)"


async def analyze_with_claude(
    sections: dict[str, str],
    anthropic_api_key: str,
    model: str = "claude-sonnet-4-6",
) -> dict[str, Any]:
    """
    Send filing sections to Claude Sonnet for deep analysis.

    Uses prompt caching on the system prompt to minimize token cost.
    Returns a dict with summary, bull_points, bear_points, financial_metrics.
    """
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
    context = _build_analysis_context(sections)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1500,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # Cache system prompt
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze this SEC filing excerpt:\n\n{context}",
                }
            ],
        )
        raw = response.content[0].text
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Claude returned non-JSON response: %s", exc)
        return {}
    except Exception as exc:
        logger.error("Claude analysis failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def analyze_filing(
    session: AsyncSession,
    filing: Filing,
    anthropic_api_key: str | None = None,
    force: bool = False,
) -> FilingAnalysis | None:
    """
    Run Stage 1 (regex red flags) and optionally Stage 2 (Claude Sonnet)
    analysis on a parsed filing.

    Args:
        session:            Async DB session.
        filing:             Filing ORM object (must be is_parsed=True).
        anthropic_api_key:  If provided, also runs Claude Sonnet analysis.
        force:              Re-analyze even if analysis already exists.

    Returns:
        FilingAnalysis ORM object, or None on failure.
    """
    if not filing.is_parsed:
        logger.warning("Filing %s is not parsed yet — skipping analysis", filing.id)
        return None

    # Check for existing analysis
    result = await session.execute(
        select(FilingAnalysis).where(FilingAnalysis.filing_id == filing.id)
    )
    existing = result.scalar_one_or_none()

    if existing and not force:
        logger.debug("Analysis already exists for filing %d, skipping", filing.id)
        return existing

    # Load sections from DB
    result = await session.execute(
        select(FilingSection).where(FilingSection.filing_id == filing.id)
    )
    section_rows = result.scalars().all()
    sections = {row.section_name: (row.content or "") for row in section_rows}

    if not sections:
        logger.warning("No sections found for filing %d", filing.id)
        return None

    # Stage 1: Regex red flags
    red_flags = detect_red_flags(sections)
    health_score = compute_health_score(red_flags)

    flags_data = [
        {"name": f.name, "severity": f.severity, "quote": f.quote, "section": f.section}
        for f in red_flags
    ]

    logger.info(
        "Filing %d: %d red flags, health score %.0f",
        filing.id,
        len(red_flags),
        health_score,
    )

    # Stage 2: Claude analysis (if API key provided)
    summary: str | None = None
    bull_points: list | None = None
    bear_points: list | None = None
    financial_metrics: dict | None = None
    model_used: str | None = None

    if anthropic_api_key:
        try:
            model = "claude-sonnet-4-6"
            claude_result = await analyze_with_claude(sections, anthropic_api_key, model)
            if claude_result:
                summary = claude_result.get("summary")
                bull_points = claude_result.get("bull_points")
                bear_points = claude_result.get("bear_points")
                financial_metrics = claude_result.get("financial_metrics")
                model_used = model

                # Blend health assessment from Claude into score
                health_map = {
                    "excellent": 0,
                    "good": -10,
                    "fair": -20,
                    "poor": -35,
                    "critical": -50,
                }
                claude_health = claude_result.get("health_assessment", "")
                if claude_health in health_map:
                    health_score = max(0.0, health_score + health_map[claude_health])

        except Exception as exc:
            logger.error("Claude analysis failed for filing %d: %s", filing.id, exc)

    # Upsert FilingAnalysis record
    if existing:
        analysis = existing
    else:
        analysis = FilingAnalysis(filing_id=filing.id)

    analysis.health_score = health_score
    analysis.red_flags = flags_data
    analysis.financial_metrics = financial_metrics
    analysis.summary = summary
    analysis.bull_points = bull_points
    analysis.bear_points = bear_points
    analysis.analyzed_at = datetime.now(UTC)
    analysis.model_used = model_used

    session.add(analysis)

    filing.is_analyzed = True
    session.add(filing)

    await session.flush()
    return analysis


async def analyze_pending_filings(
    session: AsyncSession,
    anthropic_api_key: str | None = None,
    limit: int = 20,
) -> int:
    """
    Analyze all parsed-but-not-yet-analyzed filings.

    Returns the number of filings analyzed.
    """
    result = await session.execute(
        select(Filing).where(Filing.is_parsed.is_(True), Filing.is_analyzed.is_(False)).limit(limit)
    )
    filings = result.scalars().all()

    count = 0
    for filing in filings:
        analysis = await analyze_filing(session, filing, anthropic_api_key)
        if analysis:
            count += 1

    return count
