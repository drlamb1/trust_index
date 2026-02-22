"""
EdgeFinder — Persona Router

Three-tier routing (cheapest first):
  1. Explicit @prefix (free)
  2. Keyword heuristics (free)
  3. Haiku classifier (fallback, ~$0.001/call)
  4. Default: continue with conversation's active persona
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier 1: Explicit prefix
# ---------------------------------------------------------------------------

_PREFIX_RE = re.compile(r"^[@/](analyst|thesis|pm)\b\s*", re.IGNORECASE)


def _check_prefix(text: str) -> tuple[str | None, str]:
    """Check for @analyst/@thesis/@pm prefix. Returns (persona, cleaned_text)."""
    match = _PREFIX_RE.match(text)
    if match:
        persona = match.group(1).lower()
        cleaned = text[match.end():].strip()
        return persona, cleaned or text  # keep original if nothing left
    return None, text


# ---------------------------------------------------------------------------
# Tier 2: Keyword heuristics
# ---------------------------------------------------------------------------

_PM_PATTERNS = re.compile(
    r"i\s+wish|it\s+would\s+be\s+(nice|cool|great)|can\s+you\s+add|"
    r"feature\s+request|doesn.t\s+support|add\s+support|"
    r"missing\s+(feature|functionality)|would\s+love\s+(to\s+see|if)|"
    r"how\s+do\s+i\s+request|user\s+story|acceptance\s+criteria",
    re.IGNORECASE,
)

_THESIS_PATTERNS = re.compile(
    r"\bthesis\b|\bstrategy\b|what\s+if|correlation|risk.?reward|"
    r"asymmetr|contrarian|bull\s+case|bear\s+case|"
    r"investment\s+(idea|framework)|risk\s+tolerance|"
    r"theoriz|speculate|macro\s+(view|outlook)",
    re.IGNORECASE,
)


def _check_keywords(text: str) -> str | None:
    """Return persona name based on keyword matching, or None."""
    if _PM_PATTERNS.search(text):
        return "pm"
    if _THESIS_PATTERNS.search(text):
        return "thesis"
    return None


# ---------------------------------------------------------------------------
# Tier 3: Haiku classifier (async, costs ~$0.001)
# ---------------------------------------------------------------------------

_ROUTER_SYSTEM = (
    "Classify this user message for a market intelligence chatbot. "
    'Return ONLY valid JSON: {"persona": "<analyst|thesis|pm>"}\n\n'
    '- "analyst": User wants data, numbers, analysis of specific tickers, market conditions, or a briefing.\n'
    '- "thesis": User wants creative strategy ideas, correlations, risk/reward thinking, or investment thesis generation.\n'
    '- "pm": User is requesting a feature that doesn\'t exist, reporting a bug, or asking about platform capabilities.\n\n'
    "If unsure, default to analyst."
)


async def _classify_with_haiku(text: str, api_key: str) -> str:
    """Call Haiku to classify the message. Returns persona name."""
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            system=_ROUTER_SYSTEM,
            messages=[{"role": "user", "content": text[:500]}],
        )
        raw = response.content[0].text.strip()
        data = json.loads(raw)
        persona = data.get("persona", "analyst")
        if persona in ("analyst", "thesis", "pm"):
            return persona
    except Exception as exc:
        logger.warning("Haiku routing failed: %s", exc)
    return "analyst"


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------


async def route_message(
    text: str,
    current_persona: str | None = None,
    api_key: str | None = None,
) -> tuple[str, str]:
    """
    Route a user message to the appropriate persona.

    Returns:
        (persona_name, cleaned_text) — cleaned_text has @prefix stripped if present.
    """
    # Tier 1: Explicit prefix
    persona, cleaned = _check_prefix(text)
    if persona:
        logger.debug("Routed via prefix: %s", persona)
        return persona, cleaned

    # Tier 2: Keyword heuristics
    persona = _check_keywords(text)
    if persona:
        logger.debug("Routed via keywords: %s", persona)
        return persona, text

    # Tier 3: If we have an API key and no current persona, use Haiku
    if api_key and not current_persona:
        persona = await _classify_with_haiku(text, api_key)
        logger.debug("Routed via Haiku: %s", persona)
        return persona, text

    # Tier 4: Default to current persona or analyst
    return current_persona or "analyst", text
