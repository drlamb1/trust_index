#!/usr/bin/env python3
"""
The Pit — Single-Agent Baseline

Runs the same thesis questions through a single agent (The Edger) to measure
how many distinct considerations a solo analyst surfaces. This is the control
group for the multi-agent debate experiment.

Comparison metric: consideration_count (same counter as the_pit.py)

Usage:
  python scripts/the_pit_baseline.py "NVDA is overvalued at current levels"
  python scripts/the_pit_baseline.py --all   # run all preset questions
"""

from __future__ import annotations

import anyio
import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pit_baseline")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_TURNS = 8

os.environ.pop("CLAUDECODE", None)

# ---------------------------------------------------------------------------
# The same Edger identity used as Judge in the debate — now working solo
# ---------------------------------------------------------------------------

SOLO_SYSTEM = """\
You are a financial analyst evaluating an investment thesis.

YOUR TASK:
Analyze the thesis thoroughly, considering both sides.

STRUCTURE YOUR RESPONSE:
1. **THESIS RESTATED**: Restate the thesis in one clear sentence.
2. **BULL CASE**: Strongest arguments FOR. Be specific — name signals, cite data.
3. **BEAR CASE**: Strongest arguments AGAINST. Be specific — name risks, cite precedents.
4. **WHAT'S MISSING**: Under-discussed angles. What data would change your mind?
5. **VERDICT**: Score 1-10, explain in 2-3 sentences.
6. **RISK-ADJUSTED VIEW**: Position size and stop-loss reflecting your confidence.
7. **KEY LEARNING**: What concept or framework does this illuminate?

RULES:
- Pick a side, even if narrowly.
- Be thorough. Surface every consideration you can.
- 600-900 words. Dense.
- All analysis is simulated / educational — not financial advice.
"""

# ---------------------------------------------------------------------------
# Preset questions — same ones we'll run through the debate engine
# ---------------------------------------------------------------------------

PRESET_QUESTIONS = [
    "NVDA is overvalued at current levels",
    "The AI capex cycle is unsustainable and will correct in 2026",
    "Small-cap value will outperform large-cap growth over the next 12 months",
    "Treasury yields above 4.5% will break something in credit markets",
    "AAPL has peaked as an innovation company and is now a financial engineering story",
]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BaselineResult:
    question: str
    content: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    consideration_count: int = 0


# ---------------------------------------------------------------------------
# Consideration counter — identical to the_pit.py
# ---------------------------------------------------------------------------

def count_considerations(text: str) -> int:
    """Count distinct analytical considerations in a single response.

    Same heuristic as the_pit.py's count_considerations, applied to one text block.
    """
    count = 0
    # Markdown headers
    count += len(re.findall(r"^#{2,4}\s+.+", text, re.MULTILINE))
    # Numbered points
    count += len(re.findall(r"^\d+\.\s+\*?\*?.{15,}", text, re.MULTILINE))
    # Bold-labeled points
    count += len(re.findall(r"^\*\*[^*]{5,50}\*\*[:\s]", text, re.MULTILINE))
    # Substantive bullet points
    count += len(re.findall(r"^-\s+.{20,}", text, re.MULTILINE))

    return max(1, int(count * 0.6))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_baseline(question: str) -> BaselineResult:
    """Run a single-agent thesis evaluation."""
    t0 = time.monotonic()
    result = BaselineResult(question=question)

    prompt = (
        f"THESIS TO EVALUATE: {question}\n\n"
        "You have access to tools in this project's codebase. "
        "Use Read/Bash/Grep to inspect code or data if helpful, "
        "but focus on delivering a thorough analysis.\n\n"
        "Deliver your complete analysis following the structure in your system prompt."
    )

    opts = ClaudeAgentOptions(
        system_prompt=SOLO_SYSTEM,
        max_turns=MAX_TURNS,
        permission_mode="default",
        cwd=str(PROJECT_ROOT),
    )

    full_text = []
    log.info(f"[SOLO] evaluating: {question[:60]}...")

    async for message in query(prompt=prompt, options=opts):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if hasattr(block, "text"):
                    full_text.append(block.text)
        if isinstance(message, ResultMessage):
            if hasattr(message, "usage"):
                result.tokens_in = getattr(message.usage, "input_tokens", 0)
                result.tokens_out = getattr(message.usage, "output_tokens", 0)
            if hasattr(message, "cost_usd"):
                cost = message.cost_usd
                result.cost_usd = cost if isinstance(cost, (int, float)) else 0.0

    result.content = "\n".join(full_text).strip()
    result.duration_s = time.monotonic() - t0
    result.consideration_count = count_considerations(result.content)

    log.info(
        f"[SOLO] done in {result.duration_s:.1f}s — "
        f"{result.consideration_count} considerations, "
        f"{len(result.content)} chars"
    )
    return result


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------

def save_baseline(results: list[BaselineResult], output_dir: Path | None = None):
    """Save baseline results as JSON."""
    out = output_dir or PROJECT_ROOT / "scripts" / "debates"
    out.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    path = out / f"baseline_{timestamp}.json"

    data = {
        "timestamp": timestamp,
        "type": "single_agent_baseline",
        "results": [
            {
                "question": r.question,
                "consideration_count": r.consideration_count,
                "duration_s": r.duration_s,
                "cost_usd": r.cost_usd,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "content_length": len(r.content),
                "content": r.content,
            }
            for r in results
        ],
        "summary": {
            "avg_considerations": sum(r.consideration_count for r in results) / len(results),
            "avg_duration_s": sum(r.duration_s for r in results) / len(results),
            "total_cost_usd": sum(r.cost_usd for r in results),
            "questions_run": len(results),
        },
    }
    path.write_text(json.dumps(data, indent=2))
    log.info(f"Baseline saved: {path}")
    return path


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_summary(results: list[BaselineResult]):
    """Print a comparison-ready summary table."""
    print("\n" + "=" * 70)
    print("  SINGLE-AGENT BASELINE RESULTS")
    print("=" * 70)
    print(f"  {'Question':<55} {'Consid':>6} {'Time':>7}")
    print("  " + "-" * 68)
    for r in results:
        q = r.question[:53] + ".." if len(r.question) > 55 else r.question
        print(f"  {q:<55} {r.consideration_count:>6} {r.duration_s:>6.1f}s")
    print("  " + "-" * 68)
    avg_c = sum(r.consideration_count for r in results) / len(results)
    avg_t = sum(r.duration_s for r in results) / len(results)
    total_cost = sum(r.cost_usd for r in results)
    print(f"  {'AVERAGE':<55} {avg_c:>6.1f} {avg_t:>6.1f}s")
    print(f"\n  Total cost: ${total_cost:.4f}")
    print("=" * 70)
    print(
        "\n  Compare against debate format: "
        "python scripts/the_pit.py <same question>"
    )
    print(
        "  Kill condition: debate must surface >20% more considerations "
        "to justify the cost.\n"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="The Pit — Single-Agent Baseline for debate experiment"
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="A single thesis to evaluate",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Run all 5 preset questions",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save results to disk",
    )
    args = parser.parse_args()

    if args.all:
        results = []
        for q in PRESET_QUESTIONS:
            r = anyio.run(run_baseline, q)
            print(f"\n{'─' * 70}")
            print(r.content)
            results.append(r)
        print_summary(results)
        if not args.no_save:
            save_baseline(results)
    elif args.question:
        r = anyio.run(run_baseline, args.question)
        print(f"\n{'─' * 70}")
        print(r.content)
        print_summary([r])
        if not args.no_save:
            save_baseline([r])
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
