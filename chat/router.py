"""
EdgeFinder — Persona Router

Four-tier routing (cheapest first):
  1. Explicit @prefix (free)
  2. Keyword heuristics (free)
  3. Haiku classifier (fallback, ~$0.001/call)
  4. Default: continue with conversation's active persona

Supports 8 personas: analyst, thesis, pm, thesis_lord, vol_slayer,
heston_cal, deep_hedge, post_mortem.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier 1: Explicit prefix
# ---------------------------------------------------------------------------

_PREFIX_RE = re.compile(
    r"^[@/](analyst|thesis|pm|thesis_lord|vol_slayer|heston_cal|deep_hedge|post_mortem)\b\s*",
    re.IGNORECASE,
)


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

# --- Simulation Engine Persona Patterns ---

_THESIS_LORD_PATTERNS = re.compile(
    r"generate\s+thesis|backtest|paper\s+portfolio|paper\s+position|"
    r"thesis\s+lifecycle|retire\s+thesis|kill\s+thesis|mutate\s+thesis|"
    r"simulate|simulation\s+log|play.?money",
    re.IGNORECASE,
)

_VOL_SLAYER_PATTERNS = re.compile(
    r"vol\s+surface|implied\s+vol|iv\s+surface|\bskew\b|"
    r"options?\s+chain|term\s+structure|vol\s+smile|"
    r"implied\s+vs\s+realized|put.?call\s+skew",
    re.IGNORECASE,
)

_HESTON_PATTERNS = re.compile(
    r"\bheston\b|stochastic\s+vol|calibrat|monte\s+carlo|"
    r"characteristic\s+function|feller\s+condition|"
    r"vol.?of.?vol|mean.?reversion|qe\s+scheme",
    re.IGNORECASE,
)

_DEEP_HEDGE_PATTERNS = re.compile(
    r"deep\s+hedg|neural\s+hedg|cvar\s+loss|hedging\s+policy|buehler",
    re.IGNORECASE,
)

_POST_MORTEM_PATTERNS = re.compile(
    r"post.?mortem|what\s+went\s+wrong|lessons?\s+learned|"
    r"retired\s+thesis|agent\s+memor|decision\s+log|"
    r"scar\s+tissue|why\s+did\s+.+\s+fail",
    re.IGNORECASE,
)


def _check_keywords(text: str) -> str | None:
    """Return persona name based on keyword matching, or None.

    Priority: simulation-specific patterns first (more specific),
    then original patterns (broader).
    """
    # Simulation engine personas (most specific first)
    if _HESTON_PATTERNS.search(text):
        return "heston_cal"
    if _VOL_SLAYER_PATTERNS.search(text):
        return "vol_slayer"
    if _DEEP_HEDGE_PATTERNS.search(text):
        return "deep_hedge"
    if _POST_MORTEM_PATTERNS.search(text):
        return "post_mortem"
    if _THESIS_LORD_PATTERNS.search(text):
        return "thesis_lord"

    # Original personas
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
    'Return ONLY valid JSON: {"persona": "<name>"}\n\n'
    'Valid persona names:\n'
    '- "analyst": Data, numbers, analysis of specific tickers, market conditions, briefings.\n'
    '- "thesis": Creative strategy ideas, correlations, risk/reward thinking.\n'
    '- "pm": Feature requests, bug reports, platform capabilities.\n'
    '- "thesis_lord": Thesis generation, backtesting, paper portfolio management, simulations.\n'
    '- "vol_slayer": Implied vol surfaces, skew, options chain analysis, term structure.\n'
    '- "heston_cal": Heston model, stochastic vol, calibration, Monte Carlo paths.\n'
    '- "deep_hedge": Deep hedging, neural hedging policies, CVaR optimization.\n'
    '- "post_mortem": Post-mortems, lessons learned, agent memories, what went wrong.\n\n'
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
        valid = {"analyst", "thesis", "pm", "thesis_lord", "vol_slayer", "heston_cal", "deep_hedge", "post_mortem"}
        if persona in valid:
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
