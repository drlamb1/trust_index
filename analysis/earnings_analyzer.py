"""
EdgeFinder — Earnings Call Transcript Analyzer

Two-stage analysis pipeline for earnings call transcripts:

Stage 1 — Regex pre-scan (fast, free):
    - Guidance language detection (raised/lowered/maintained/withdrew)
    - Hedging language density (uncertainty markers)
    - Key buzzword extraction

Stage 2 — Claude Sonnet deep analysis:
    - Overall sentiment (-1.0 to +1.0)
    - Management tone classification
    - Forward guidance sentiment
    - Key topics + analyst concerns
    - Notable management quotes
    - Bull/bear signals
    - Tone comparison vs prior quarter

Cost controls:
    - Prompt caching on system prompt (~90% input token savings)
    - Hash-gate: skip re-analysis when content_hash unchanged
    - Truncate to 40K chars (covers most earnings calls)

Run via:
    analysis triggered after transcript ingestion (scheduler or CLI)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import EarningsAnalysis, EarningsTranscript

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage 1: Regex pre-scan for guidance signals
# ---------------------------------------------------------------------------

_GUIDANCE_RAISED = re.compile(
    r"rais(?:e|ed|ing)\s+(?:our\s+)?(?:full[\s-]year|annual|quarterly)?\s*(?:guidance|outlook|forecast|target)",
    re.IGNORECASE,
)
_GUIDANCE_LOWERED = re.compile(
    r"lower(?:ed|ing)?\s+(?:our\s+)?(?:full[\s-]year|annual|quarterly)?\s*(?:guidance|outlook|forecast|target)"
    r"|cut\s+(?:our\s+)?(?:guidance|outlook|forecast)",
    re.IGNORECASE,
)
_GUIDANCE_MAINTAINED = re.compile(
    r"maintain(?:ed|ing)?\s+(?:our\s+)?(?:guidance|outlook)"
    r"|reaffirm(?:ed|ing)?\s+(?:our\s+)?(?:guidance|outlook)",
    re.IGNORECASE,
)
_GUIDANCE_WITHDREW = re.compile(
    r"withdraw(?:n|ing)?\s+(?:our\s+)?(?:guidance|outlook)"
    r"|suspend(?:ed|ing)?\s+(?:guidance|outlook)",
    re.IGNORECASE,
)

_HEDGING_WORDS = re.compile(
    r"\b(?:uncertain(?:ty)?|challenging|headwind|cautious(?:ly)?|volatile|"
    r"risk|difficult|concerned|pressure|downturn|deteriorat)\b",
    re.IGNORECASE,
)

_BULLISH_WORDS = re.compile(
    r"\b(?:record|strong|accelerat|outperform|exceed|momentum|"
    r"robust|confident|optimistic|tailwind|growth|expand)\b",
    re.IGNORECASE,
)


def _prescan_transcript(text: str) -> dict[str, Any]:
    """Quick regex scan for guidance and tone signals."""
    word_count = len(text.split())

    guidance_signal = "neutral"
    if _GUIDANCE_WITHDREW.search(text):
        guidance_signal = "withdrew"
    elif _GUIDANCE_LOWERED.search(text):
        guidance_signal = "lowered"
    elif _GUIDANCE_RAISED.search(text):
        guidance_signal = "raised"
    elif _GUIDANCE_MAINTAINED.search(text):
        guidance_signal = "maintained"

    hedging_count = len(_HEDGING_WORDS.findall(text))
    bullish_count = len(_BULLISH_WORDS.findall(text))

    # Normalize per 1000 words
    hedge_density = (hedging_count / max(word_count, 1)) * 1000
    bull_density = (bullish_count / max(word_count, 1)) * 1000

    return {
        "guidance_signal": guidance_signal,
        "hedging_density": round(hedge_density, 1),
        "bullish_density": round(bull_density, 1),
        "word_count": word_count,
    }


# ---------------------------------------------------------------------------
# Stage 2: Claude Sonnet deep analysis
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a senior equity research analyst specializing in earnings call analysis.
You read between the lines of management commentary, detect shifts in tone,
and identify the key signals that matter for investment decisions.

Analyze the earnings call transcript and respond with a JSON object:

{
  "overall_sentiment": <float from -1.0 (very bearish) to +1.0 (very bullish)>,
  "management_tone": "<one of: confident | cautious | defensive | optimistic | neutral>",
  "forward_guidance_sentiment": <float from -1.0 to +1.0 based on forward-looking statements>,
  "key_topics": ["<topic 1>", "<topic 2>", ...],
  "analyst_concerns": ["<concern raised by analysts>", ...],
  "management_quotes": [
    {"speaker": "<name/title>", "quote": "<exact quote, max 150 chars>", "sentiment": "<bullish/bearish/neutral>"},
    ...
  ],
  "summary": "<300-word executive summary of the call — key announcements, guidance changes, and tone>",
  "bull_signals": ["<bullish takeaway>", ...],
  "bear_signals": ["<bearish takeaway>", ...]
}

Guidelines:
- key_topics: 3-5 main discussion themes
- analyst_concerns: 2-5 concerns raised during Q&A
- management_quotes: up to 5 most notable quotes
- bull_signals: 3-5 bullish takeaways
- bear_signals: 3-5 bearish takeaways
- Pay special attention to: guidance changes, margin commentary, competitive dynamics,
  capital allocation priorities, and any hedging/uncertainty in forward-looking statements
- Return ONLY valid JSON, no markdown fences."""

_MAX_TRANSCRIPT_CHARS = 40_000


async def analyze_transcript(
    transcript: EarningsTranscript,
    anthropic_api_key: str,
    prior_analysis: EarningsAnalysis | None = None,
    model: str = "claude-sonnet-4-6",
) -> dict[str, Any]:
    """
    Analyze an earnings call transcript with Claude Sonnet.

    If prior_analysis is provided, includes tone comparison context
    so Claude can assess quarter-over-quarter shifts.

    Returns parsed JSON dict with analysis fields.
    """
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)

    # Build user prompt
    text = (transcript.transcript_text or "")[:_MAX_TRANSCRIPT_CHARS]
    prescan = _prescan_transcript(text)

    user_parts = [
        f"Analyze this earnings call transcript for {transcript.ticker.symbol if hasattr(transcript, 'ticker') and transcript.ticker else 'this company'} "
        f"(Q{transcript.quarter} FY{transcript.fiscal_year}).",
        f"\nPre-scan signals: guidance={prescan['guidance_signal']}, "
        f"hedging density={prescan['hedging_density']}/1000w, "
        f"bullish density={prescan['bullish_density']}/1000w.",
    ]

    if prior_analysis:
        user_parts.append(
            f"\nPrior quarter analysis for comparison:"
            f"\n  - Tone: {prior_analysis.management_tone}"
            f"\n  - Overall sentiment: {prior_analysis.overall_sentiment}"
            f"\n  - Guidance sentiment: {prior_analysis.forward_guidance_sentiment}"
            f"\nPlease note if tone has shifted significantly."
        )

    user_parts.append(f"\n\n--- TRANSCRIPT ---\n{text}")
    user_message = "\n".join(user_parts)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=2000,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        logger.error("Claude earnings analysis failed: %s", exc)
        return {}

    raw_text = response.content[0].text if response.content else ""

    # Parse JSON response
    try:
        # Try to extract JSON from the response (handle potential markdown fences)
        json_match = re.search(r"\{[\s\S]*\}", raw_text)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse Claude response as JSON: %s", raw_text[:200])
        return {}

    # Add prescan data
    result["_prescan"] = prescan
    result["_model"] = model
    result["_input_tokens"] = response.usage.input_tokens
    result["_output_tokens"] = response.usage.output_tokens

    return result


def _determine_tone_vs_prior(
    current: dict[str, Any],
    prior: EarningsAnalysis | None,
) -> str:
    """Compare current analysis to prior quarter and classify shift."""
    if prior is None:
        return "stable"  # No prior to compare

    current_sentiment = current.get("overall_sentiment", 0.0)
    prior_sentiment = prior.overall_sentiment or 0.0
    delta = current_sentiment - prior_sentiment

    if delta > 0.3:
        return "improving"
    elif delta < -0.3:
        return "deteriorating"
    return "stable"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def analyze_and_store(
    session: AsyncSession,
    transcript: EarningsTranscript,
    anthropic_api_key: str,
) -> EarningsAnalysis | None:
    """
    Run full analysis pipeline on a transcript and store results.

    Skips if analysis already exists for this transcript.
    Loads prior quarter's analysis for tone comparison.
    """
    # Check if already analyzed
    existing = await session.execute(
        select(EarningsAnalysis).where(
            EarningsAnalysis.transcript_id == transcript.id
        )
    )
    if existing.scalar_one_or_none():
        logger.debug("Transcript %d already analyzed, skipping", transcript.id)
        return None

    # Load prior quarter's analysis for comparison
    prior_transcript = await session.execute(
        select(EarningsTranscript)
        .where(
            EarningsTranscript.ticker_id == transcript.ticker_id,
            EarningsTranscript.id != transcript.id,
            (
                (EarningsTranscript.fiscal_year < transcript.fiscal_year)
                | (
                    (EarningsTranscript.fiscal_year == transcript.fiscal_year)
                    & (EarningsTranscript.quarter < transcript.quarter)
                )
            ),
        )
        .order_by(
            EarningsTranscript.fiscal_year.desc(),
            EarningsTranscript.quarter.desc(),
        )
        .limit(1)
    )
    prior_t = prior_transcript.scalar_one_or_none()
    prior_analysis: EarningsAnalysis | None = None
    if prior_t:
        prior_a_result = await session.execute(
            select(EarningsAnalysis).where(EarningsAnalysis.transcript_id == prior_t.id)
        )
        prior_analysis = prior_a_result.scalar_one_or_none()

    # Run Claude analysis
    result = await analyze_transcript(
        transcript, anthropic_api_key, prior_analysis=prior_analysis
    )
    if not result:
        return None

    tone_vs_prior = _determine_tone_vs_prior(result, prior_analysis)

    analysis = EarningsAnalysis(
        transcript_id=transcript.id,
        overall_sentiment=result.get("overall_sentiment"),
        management_tone=result.get("management_tone"),
        forward_guidance_sentiment=result.get("forward_guidance_sentiment"),
        key_topics=result.get("key_topics"),
        analyst_concerns=result.get("analyst_concerns"),
        management_quotes=result.get("management_quotes"),
        summary=result.get("summary"),
        bull_signals=result.get("bull_signals"),
        bear_signals=result.get("bear_signals"),
        tone_vs_prior=tone_vs_prior,
        analyzed_at=datetime.now(UTC),
        model_used=result.get("_model", "claude-sonnet-4-6"),
    )
    session.add(analysis)
    await session.flush()

    logger.info(
        "Earnings analysis stored: transcript=%d tone=%s sentiment=%.2f guidance=%.2f",
        transcript.id,
        analysis.management_tone,
        analysis.overall_sentiment or 0,
        analysis.forward_guidance_sentiment or 0,
    )
    return analysis


async def analyze_unprocessed(
    session: AsyncSession,
    anthropic_api_key: str,
) -> int:
    """
    Find all transcripts without analysis and process them.
    Returns count of new analyses created.
    """
    result = await session.execute(
        select(EarningsTranscript)
        .outerjoin(EarningsAnalysis)
        .where(EarningsAnalysis.id.is_(None))
        .options(selectinload(EarningsTranscript.ticker))
        .order_by(EarningsTranscript.fiscal_year, EarningsTranscript.quarter)
    )
    transcripts = result.scalars().all()

    count = 0
    for transcript in transcripts:
        analysis = await analyze_and_store(session, transcript, anthropic_api_key)
        if analysis:
            count += 1

    logger.info("Analyzed %d unprocessed transcripts", count)
    return count
