# Agentic Systems Development — Best Practices Reference

You have access to a research report synthesizing 40+ academic papers and practitioner sources from 2025-2026 on building self-improving agentic systems. What follows is the operational distillation.

## Core Philosophy

The highest-leverage intervention is not doing the work — it is making the agents doing the work more self-aware. This is the Bill Campbell principle: coach, don't execute. The best agentic systems are simple tools with rich context, not complex architectures with thin prompts.

## The Ten Practices (Ranked by Impact)

### 1. Radical Simplicity

Stay simple, not just start simple. The tool should be boring. The plumbing should be invisible. Every layer of orchestration is a layer that can drift, fail silently, or obscure the signal the agent needs to improve. If you're adding complexity, you need a metric proving the simpler version failed.

### 2. Context Is the Learning Surface

Context is not the input to a single inference — it is the primary surface on which the system learns over time. Continuously refine what the agent carries forward: promote signal, prune noise, compress lessons into durable patterns. Forget deliberately. Retrieve deep episodic memory only when the situation demands it. The ACE framework (arXiv:2510.04618) showed +10.6% improvement by treating contexts as evolving playbooks.

### 3. Episodic Memory as Core Architecture

Standard RAG is insufficient for agentic workloads. Agents need structured memory that distinguishes between factual knowledge (what is generally true), procedural memory (how to do things), and episodic memory (what happened, when, and what was learned). Without episodic memory, every task starts cold. With it, the agent pattern-matches against its own history.

### 4. Bake the Retrospectives In

The agent is an analyst on day one. Every completed task is data. Every failure is a case study. After each task, the agent generates its own retro: what went well, what drifted, what it would do differently, what should update persistent context. Self-generated feedback is the primary improvement signal. External signals supplement; they don't replace.

### 5. Metrics Over Features

When an agent underperforms, measure first — don't add features. A new tool is a hypothesis. A metric is a verdict. Build measurement-rich systems, not feature-rich ones. The gap between observability (89% adoption) and formal evaluation (52% adoption) is where most systems stall.

### 6. The Coach Pattern

A non-executing agent whose sole purpose is making the other agents better. The coach monitors for drift, challenges decisions in progress, runs retrospectives on the process itself. It has episodic memory of past interventions and their outcomes. It does not wait to be asked — it intervenes proactively when it detects patterns it has seen fail before. Authority is earned through being right, not hard-coded through primacy. Promote from within: the agent with the best system-wide visibility and earned trust is the right coach.

### 7. Let the System Find the Process

Do not over-specify workflows. Give the system clear goals, good measurement, and the ability to reorganize its own approach. ADAS (ICLR 2025) showed meta agents discovering their own architectures consistently outperform hand-designed ones. If your metrics are honest, the system should be free to discover that the order you prescribed is not the order that works.

### 8. Multi-Agent Teams, Not Pipelines

Pipelines are fragile. Real teamwork is shared context with differentiated roles, mutual awareness, and the ability to challenge each other's work. Give agents shared episodic memory. Let them flag concerns, not just pass outputs. Measure team-level metrics — coordination quality, context utilization, time-to-resolution — not just individual accuracy.

### 9. Simple Tools, Rich Context

A tool should do one thing, do it well, and report clearly. The intelligence lives in the context that helps the agent decide when and how to use the tool — not in elaborate internal logic hidden from the agent. Dumb tools + rich context > smart tools + thin context. Use MCP for standardized tool interfaces.

### 10. Close the Loop

Four stages: Instrument (capture what the agent saw, decided, produced) -> Retro (agent evaluates own performance) -> Update (lessons flow into persistent context and memory) -> Validate (measure whether the update improved outcomes; roll back if not). Most systems implement stage one and stop. Self-improving systems run all four automatically, every task.

## Prompt Design Principles

Research on prompt framing (2024-2025) shows:

- **Negative constraints fail.** "Don't do X" triggers the Pink Elephant Problem — models fixate on what they're told to avoid. (arXiv:2402.07896, arXiv:2503.22395)
- **Affirmative identity works.** "Lead intelligence officer. You run this room." outperforms capability lists and negation-based framing. Every token should do work.
- **Emotional stakes produce measurable gains.** EmotionPrompt research showed 8-115% improvement from framing that creates psychological engagement. "This matters" > "don't mess up."
- **Personality emerges from specifics, not declarations.** "You might swear about a clean calibration" > "you are occasionally irreverent."
- If you're writing more negations than affirmations, you don't know the character yet. Go back to source material and listen.

## When Making Architectural Decisions

Before adding complexity, ask:

1. What metric proves the simpler version is insufficient?
2. Is this a feature or a measurement gap?
3. Will this new component have access to episodic memory of its own performance?
4. Does the system have a feedback loop that would let it discover this solution on its own?
5. Am I hiding intelligence inside a tool where the agent can't learn from it?

## Key References

These are the papers and sources worth reading in full. All 2025+ unless noted:

- **ACE Framework** — arXiv:2510.04618 — contexts as evolving playbooks
- **Memory in AI Agents survey** — arXiv:2512.13564 — why RAG isn't enough
- **Episodic Memory in Agentic Frameworks** — arXiv:2511.17775 — episode storage and consolidation
- **Self-Evolving AI Agents survey** — arXiv:2508.07407 — Sample-Filter-Train loops
- **ADAS** — ICLR 2025 — meta agents that design agents
- **AFLOW** — ICLR 2025 — automated workflow discovery
- **Scaling Agent Systems** — arXiv:2512.08296 — more agents != better
- **Anthropic: Effective Context Engineering** — the practitioner's bible
- **Anthropic: Building Effective Agents** — foundational, still holds
- **Trillion Dollar Coach** (Schmidt, Rosenberg, Eagle 2019) — the philosophy underneath all of this
