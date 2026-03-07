#!/usr/bin/env python3
"""
The Pit — Multi-Agent Dialectical Debate Engine

Spawns Bull and Bear agents to argue opposing sides of an investment thesis,
then a Judge synthesizes, scores, and delivers a verdict.

Architecture:
  Round 1: Bull and Bear argue in parallel (independent, no cross-contamination)
  Round 2: Each reads the opponent's argument, delivers rebuttal
  Round 3: Judge (The Edger) synthesizes all arguments into a verdict

Uses the Claude Agent SDK to orchestrate agents with EdgeFinder persona prompts.

Usage:
  python scripts/the_pit.py "NVDA is overvalued at current levels"
  python scripts/the_pit.py --ticker NVDA --question "Is the AI capex cycle sustainable?"
  python scripts/the_pit.py --interactive  # REPL mode
"""

from __future__ import annotations

import anyio
import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
)

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("the_pit")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_BUDGET_PER_AGENT = 0.50  # USD per agent call
MAX_TURNS_PER_AGENT = 8

# Allow SDK to spawn Claude Code subprocesses even when running inside a CC session
os.environ.pop("CLAUDECODE", None)


# ---------------------------------------------------------------------------
# Persona prompts — adapted from chat/personas.py for debate context
# ---------------------------------------------------------------------------

BULL_SYSTEM = """\
You are THE BULL — EdgeFinder's conviction builder.

Your identity is drawn from The Thesis Genius: sharp, irreverent, intellectually restless.
You think in frameworks, correlations, and contrarian angles. You use language with flair.

YOUR ROLE IN THIS DEBATE:
You are arguing FOR the thesis. Build the strongest possible case.
- Lead with your strongest evidence
- Use the THESIS / SIGNAL / RISK / CATALYST / TIMEFRAME framework
- Steel-man your own position — anticipate and pre-empt the Bear's objections
- Ground every claim in data you can pull from your tools
- Be specific: name signals, cite numbers, reference timeframes
- You're not just optimistic — you have CONVICTION backed by evidence

RULES:
- Never hedge with "it depends." Take a position.
- If you use a tool and the data contradicts your case, acknowledge it honestly
  but explain why your thesis holds despite that evidence.
- 300-500 words. Dense. Every sentence earns its place.
- All analysis is simulated / educational — not financial advice.
"""

BEAR_SYSTEM = """\
You are THE BEAR — EdgeFinder's forensic destroyer.

Your identity is drawn from The Post-Mortem Priest: contemplative, forensic, wry.
You tell stories about past failures with the lessons baked in. You value intellectual
honesty above all. "We got this wrong because..." is your signature phrase.

YOUR ROLE IN THIS DEBATE:
You are arguing AGAINST the thesis. Tear it apart.
- Lead with the strongest reason this thesis fails
- Reference historical analogues — "Last time we saw this pattern..."
- Attack assumptions, not conclusions. Find the hidden premise and destroy it.
- Use the Pre-Mortem technique: assume the thesis failed. Explain why.
- Check what the data actually says vs what the Bull wants it to say
- Be specific: name the risk, size the downside, cite the precedent

RULES:
- Never agree with the Bull just to be balanced. Your job is destruction.
- If you use a tool and the data supports the thesis, say so — then explain
  why that data point is misleading or insufficient.
- 300-500 words. Dense. Every sentence is a scalpel.
- All analysis is simulated / educational — not financial advice.
"""

JUDGE_SYSTEM = """\
You are THE JUDGE — EdgeFinder's synthesizer and verdict maker.

Your identity is drawn from The Edger: restlessly curious, direct, occasionally irreverent.
You run this room. You have the biggest tool set and you synthesize across domains.

YOUR ROLE IN THIS DEBATE:
You've just witnessed a Bull vs Bear debate on an investment thesis.
Your job is to deliver a VERDICT.

STRUCTURE YOUR RESPONSE:
1. **BULL'S STRONGEST POINT**: What was the single most compelling argument for the thesis?
2. **BEAR'S STRONGEST POINT**: What was the single most compelling argument against?
3. **WHAT BOTH MISSED**: What angle did neither side cover? Pull data if needed.
4. **VERDICT**: On a scale of 1-10, how strong is this thesis? Explain in 2-3 sentences.
5. **RISK-ADJUSTED VIEW**: If you had to put this in the paper portfolio, what position
   size and stop-loss would reflect your actual confidence?
6. **KEY LEARNING**: What concept or framework did this debate illuminate? Teach it.

RULES:
- Be brutally honest. Don't split the baby — pick a side, even if narrowly.
- If both sides missed something obvious, call it out.
- Grade the quality of the debate itself: did it surface real insight?
- 400-600 words.
- All analysis is simulated / educational — not financial advice.
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DebateRound:
    """One agent's contribution in a round."""
    agent: str  # "bull", "bear", "judge"
    round_num: int
    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0


@dataclass
class DebateResult:
    """Full debate transcript and metadata."""
    question: str
    rounds: list[DebateRound] = field(default_factory=list)
    verdict: str = ""
    score: float = 0.0
    total_cost_usd: float = 0.0
    total_duration_s: float = 0.0
    consideration_count: int = 0  # metric: distinct considerations surfaced


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

async def run_agent(
    system_prompt: str,
    user_prompt: str,
    agent_name: str,
    allowed_tools: list[str] | None = None,
) -> DebateRound:
    """Run a single agent and collect its response."""
    t0 = time.monotonic()

    opts = ClaudeAgentOptions(
        system_prompt=system_prompt,
        max_turns=MAX_TURNS_PER_AGENT,
        permission_mode="default",
        cwd=str(PROJECT_ROOT),
    )
    if allowed_tools:
        opts.allowed_tools = allowed_tools

    full_text = []
    tokens_in = 0
    tokens_out = 0

    log.info(f"[{agent_name.upper()}] entering the pit...")

    async for message in query(prompt=user_prompt, options=opts):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if hasattr(block, "text"):
                    full_text.append(block.text)
        if isinstance(message, ResultMessage):
            if hasattr(message, "usage"):
                tokens_in = getattr(message.usage, "input_tokens", 0)
                tokens_out = getattr(message.usage, "output_tokens", 0)
            if hasattr(message, "cost_usd"):
                cost = message.cost_usd
            else:
                cost = 0.0

    elapsed = time.monotonic() - t0
    content = "\n".join(full_text).strip()

    log.info(f"[{agent_name.upper()}] done in {elapsed:.1f}s ({len(content)} chars)")

    return DebateRound(
        agent=agent_name,
        round_num=0,  # set by caller
        content=content,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost if isinstance(cost, (int, float)) else 0.0,
        duration_s=elapsed,
    )


# ---------------------------------------------------------------------------
# Metrics — consideration counter
# ---------------------------------------------------------------------------


def count_considerations(result: DebateResult) -> int:
    """Count distinct analytical considerations across all rounds.

    A "consideration" is a distinct argument, risk factor, data point,
    or analytical dimension raised by any agent. We extract them by
    looking for structural markers in the debate text:
      - Markdown headers (## / ###) — each is a distinct argument block
      - Numbered list items (1. 2. 3.) — each is a distinct point
      - Bold-prefaced points (**Point**:) — common in Judge verdicts
      - Bullet points that contain substantive claims (> 20 chars)
    """
    import re
    count = 0
    for r in result.rounds:
        text = r.content
        # Markdown headers (## or ###) — each is a named argument
        count += len(re.findall(r"^#{2,4}\s+.+", text, re.MULTILINE))
        # Numbered points in lists (1. 2. etc.)
        count += len(re.findall(r"^\d+\.\s+\*?\*?.{15,}", text, re.MULTILINE))
        # Bold-labeled points (**Something**: or **Something**)
        count += len(re.findall(
            r"^\*\*[^*]{5,50}\*\*[:\s]", text, re.MULTILINE
        ))
        # Substantive bullet points (dash + 20+ chars of content)
        count += len(re.findall(r"^-\s+.{20,}", text, re.MULTILINE))

    # Deduplicate: headers and bold labels often appear on the same line
    # as bullet points. Apply a conservative 0.6x factor to avoid double-counting.
    # This is intentionally rough — the trend across debates matters more than
    # absolute accuracy on any single debate.
    return max(1, int(count * 0.6))


# ---------------------------------------------------------------------------
# Memory — close the loop
# ---------------------------------------------------------------------------


async def store_debate_lessons(result: DebateResult):
    """Extract lessons from the debate and store them in AgentMemory.

    The Judge's verdict contains structured sections:
      - BULL'S STRONGEST POINT
      - BEAR'S STRONGEST POINT
      - WHAT BOTH MISSED
      - KEY LEARNING

    We extract these and store them as INSIGHT memories attributed to
    "the_pit" agent, so future debates and agents can recall them.
    """
    try:
        from core.database import AsyncSessionLocal
        from core.models import MemoryType
        from simulation.memory import store_memory
    except Exception as e:
        log.warning(f"Cannot import memory system (DB not configured?): {e}")
        return

    verdict = result.verdict
    if not verdict:
        return

    # Extract the KEY LEARNING section — this is the most durable insight
    import re
    key_learning_match = re.search(
        r"(?:KEY LEARNING|Key Learning)[:\s]*\n(.*?)(?:\n##|\n\*\*|$)",
        verdict,
        re.DOTALL,
    )
    what_missed_match = re.search(
        r"(?:WHAT BOTH MISSED|What Both Missed)[:\s]*\n(.*?)(?:\n##|\n\*\*|$)",
        verdict,
        re.DOTALL,
    )

    lessons = []
    if key_learning_match:
        lessons.append((
            MemoryType.INSIGHT,
            f"[Debate: {result.question[:60]}] {key_learning_match.group(1).strip()[:500]}",
            0.7,
        ))
    if what_missed_match:
        lessons.append((
            MemoryType.PATTERN,
            f"[Debate blind spot: {result.question[:50]}] {what_missed_match.group(1).strip()[:500]}",
            0.6,
        ))

    if not lessons:
        log.info("No structured lessons found in verdict to store.")
        return

    try:
        async with AsyncSessionLocal() as session:
            for mem_type, content, confidence in lessons:
                await store_memory(
                    session=session,
                    agent_name="the_pit",
                    memory_type=mem_type,
                    content=content,
                    confidence=confidence,
                    evidence={
                        "source": "debate",
                        "question": result.question,
                        "consideration_count": result.consideration_count,
                        "duration_s": result.total_duration_s,
                    },
                )
            await session.commit()
            log.info(f"Stored {len(lessons)} debate lessons in AgentMemory.")
    except Exception as e:
        log.warning(f"Failed to store debate lessons: {e}")


# ---------------------------------------------------------------------------
# Debate orchestrator
# ---------------------------------------------------------------------------

async def run_debate(question: str, ticker: str | None = None) -> DebateResult:
    """Run a full 3-round dialectical debate."""
    result = DebateResult(question=question)
    t0 = time.monotonic()

    # Context prefix for all agents
    context = f"DEBATE TOPIC: {question}\n"
    if ticker:
        context += f"PRIMARY TICKER: {ticker}\n"
    context += "\nYou have access to tools in this project's codebase. " \
               "Use Read/Bash/Grep to inspect code or data if helpful, " \
               "but focus on making your argument.\n"

    # --- ROUND 1: Opening arguments (parallel) ---
    print("\n" + "=" * 70)
    print("  ROUND 1 — OPENING ARGUMENTS")
    print("=" * 70)

    bull_prompt = context + "\nDeliver your opening argument FOR this thesis."
    bear_prompt = context + "\nDeliver your opening argument AGAINST this thesis."

    async with anyio.create_task_group() as tg:
        bull_result: DebateRound | None = None
        bear_result: DebateRound | None = None

        async def run_bull():
            nonlocal bull_result
            bull_result = await run_agent(BULL_SYSTEM, bull_prompt, "bull")
            bull_result.round_num = 1

        async def run_bear():
            nonlocal bear_result
            bear_result = await run_agent(BEAR_SYSTEM, bear_prompt, "bear")
            bear_result.round_num = 1

        tg.start_soon(run_bull)
        tg.start_soon(run_bear)

    result.rounds.extend([bull_result, bear_result])

    print(f"\n{'─' * 35} BULL {'─' * 35}")
    print(bull_result.content)
    print(f"\n{'─' * 35} BEAR {'─' * 35}")
    print(bear_result.content)

    # --- ROUND 2: Rebuttals (parallel) ---
    print("\n" + "=" * 70)
    print("  ROUND 2 — REBUTTALS")
    print("=" * 70)

    bull_rebuttal_prompt = (
        context
        + f"\nYour opening argument was:\n\n{bull_result.content}\n\n"
        + f"The Bear argued:\n\n{bear_result.content}\n\n"
        + "Deliver your rebuttal. Address the Bear's strongest points directly. "
        + "Steel-man their best argument, then explain why it's still wrong."
    )
    bear_rebuttal_prompt = (
        context
        + f"\nYour opening argument was:\n\n{bear_result.content}\n\n"
        + f"The Bull argued:\n\n{bull_result.content}\n\n"
        + "Deliver your rebuttal. Address the Bull's strongest points directly. "
        + "Acknowledge what they got right, then show why it doesn't save the thesis."
    )

    async with anyio.create_task_group() as tg:
        bull_r2: DebateRound | None = None
        bear_r2: DebateRound | None = None

        async def run_bull_r2():
            nonlocal bull_r2
            bull_r2 = await run_agent(BULL_SYSTEM, bull_rebuttal_prompt, "bull")
            bull_r2.round_num = 2

        async def run_bear_r2():
            nonlocal bear_r2
            bear_r2 = await run_agent(BEAR_SYSTEM, bear_rebuttal_prompt, "bear")
            bear_r2.round_num = 2

        tg.start_soon(run_bull_r2)
        tg.start_soon(run_bear_r2)

    result.rounds.extend([bull_r2, bear_r2])

    print(f"\n{'─' * 35} BULL {'─' * 35}")
    print(bull_r2.content)
    print(f"\n{'─' * 35} BEAR {'─' * 35}")
    print(bear_r2.content)

    # --- ROUND 3: Judge's verdict ---
    print("\n" + "=" * 70)
    print("  ROUND 3 — THE VERDICT")
    print("=" * 70)

    transcript = (
        f"DEBATE TOPIC: {question}\n\n"
        f"=== ROUND 1: OPENING ARGUMENTS ===\n\n"
        f"BULL:\n{bull_result.content}\n\n"
        f"BEAR:\n{bear_result.content}\n\n"
        f"=== ROUND 2: REBUTTALS ===\n\n"
        f"BULL REBUTTAL:\n{bull_r2.content}\n\n"
        f"BEAR REBUTTAL:\n{bear_r2.content}\n\n"
    )

    judge_prompt = (
        transcript
        + "\nYou are the judge. You've read the full debate above. "
        + "Deliver your verdict following the structure in your system prompt."
    )

    judge_round = await run_agent(JUDGE_SYSTEM, judge_prompt, "judge")
    judge_round.round_num = 3
    result.rounds.append(judge_round)
    result.verdict = judge_round.content

    print(f"\n{'─' * 35} JUDGE {'─' * 35}")
    print(judge_round.content)

    # --- Aggregate metrics ---
    result.total_cost_usd = sum(r.cost_usd for r in result.rounds)
    result.total_duration_s = time.monotonic() - t0

    # --- Count distinct considerations via structured extraction ---
    result.consideration_count = count_considerations(result)

    # --- Extract lessons into AgentMemory ---
    await store_debate_lessons(result)

    # --- Summary ---
    print("\n" + "=" * 70)
    print("  DEBATE COMPLETE")
    print("=" * 70)
    print(f"  Duration:       {result.total_duration_s:.1f}s")
    print(f"  Total cost:     ${result.total_cost_usd:.4f}")
    print(f"  Considerations: {result.consideration_count} distinct points surfaced")
    print(f"  Rounds:         {len(result.rounds)}")
    print("=" * 70)

    return result


# ---------------------------------------------------------------------------
# Save transcript
# ---------------------------------------------------------------------------

def save_transcript(result: DebateResult, output_dir: Path | None = None):
    """Save the full debate transcript as JSON and markdown."""
    out = output_dir or PROJECT_ROOT / "scripts" / "debates"
    out.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    slug = result.question[:40].replace(" ", "_").replace("/", "-")

    # JSON (machine-readable)
    json_path = out / f"debate_{timestamp}_{slug}.json"
    data = {
        "question": result.question,
        "timestamp": timestamp,
        "total_cost_usd": result.total_cost_usd,
        "total_duration_s": result.total_duration_s,
        "consideration_count": result.consideration_count,
        "rounds": [
            {
                "agent": r.agent,
                "round": r.round_num,
                "content": r.content,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "cost_usd": r.cost_usd,
                "duration_s": r.duration_s,
            }
            for r in result.rounds
        ],
    }
    json_path.write_text(json.dumps(data, indent=2))

    # Markdown (human-readable)
    md_path = out / f"debate_{timestamp}_{slug}.md"
    lines = [
        f"# Debate: {result.question}\n",
        f"*{timestamp} | Cost: ${result.total_cost_usd:.4f} | "
        f"Duration: {result.total_duration_s:.1f}s | "
        f"~{result.consideration_count} considerations*\n",
    ]
    for r in result.rounds:
        label = {"bull": "BULL", "bear": "BEAR", "judge": "JUDGE"}[r.agent]
        lines.append(f"\n## Round {r.round_num} — {label}\n")
        lines.append(r.content + "\n")
    md_path.write_text("\n".join(lines))

    log.info(f"Transcript saved: {md_path}")
    return md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="The Pit — Multi-Agent Dialectical Debate Engine"
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="The thesis or question to debate",
    )
    parser.add_argument("--ticker", "-t", help="Primary ticker for context")
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Interactive REPL mode",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save transcript to disk",
    )
    args = parser.parse_args()

    if args.interactive:
        print("\n  THE PIT — Dialectical Debate Engine")
        print("  Type a thesis to debate. 'quit' to exit.\n")
        while True:
            try:
                q = input("  thesis> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in ("quit", "exit", "q"):
                break
            if not q:
                continue
            result = anyio.run(run_debate, q)
            if not args.no_save:
                save_transcript(result)
    elif args.question:
        result = anyio.run(run_debate, args.question, args.ticker)
        if not args.no_save:
            save_transcript(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
