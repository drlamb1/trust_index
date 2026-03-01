# EdgeFinder — Where This Is Going

## The Arc (read from the commit history)

The repo name is `trust_index`. Not `edgefinder`. Not `market-dashboard`. **Trust index.**

The commit history tells the story in four acts:

**Act 1: Data.** SEC filings, price bars, news sentiment, FRED macro, earnings transcripts, insider trades. Build the nervous system. Ingest everything, score everything, detect anomalies. 509 tickers, 38 Celery tasks, 6 queues. This is infrastructure — the boring, essential plumbing that makes everything else possible.

**Act 2: Simulation.** Heston stochastic vol, Black-Scholes, walk-forward backtesting, paper portfolio, thesis generation. The system stops being a dashboard and starts being a lab. Play money, explicit disclaimers, immutable decision logs. Every thesis is born, tested, lives, mutates, or dies — and the record is permanent. The math gets peer-reviewed: Monte Carlo bootstrap fixed (Politis & Romano 1994), Sortino denominator corrected, Heston branch cut guarded. Correctness matters because you can't build trust on wrong math.

**Act 3: Agents.** Nine personas, each with a distinct cognitive style, tool access, and domain. Not chatbots — specialists who know their lane, know each other's lanes, and know when to hand off. The Thesis Lord executes with scar tissue. The Post-Mortem Priest ensures failures become institutional memory. The Edger translates the whole thing for humans. Cross-agent communication via SimulationLog NOTE events. The swarm talks to itself.

**Act 4: Learning.** Self-learning eval loop with prompt registry and outcome linking. ML pipeline: FinBERT sentiment (replace API calls with local inference), XGBoost signal ranker (learn from backtest outcomes which signal clusters actually predict thesis viability), deep hedging policy (neural network learns to hedge better than Black-Scholes). Train on a gaming laptop, deploy to cloud, zero downtime model updates via database. The system gets smarter by running.

**Where this is going:** A system that ingests market reality, generates hypotheses about it, tests those hypotheses with mathematical honesty, remembers what it learned, teaches what it knows, and gets better every cycle. The "trust index" is the measure of whether you should believe it — built from the immutable log of every decision, every failure, every correction. Not a dashboard. Not a chatbot. A self-improving decision system that earns trust by being transparent about its track record.

The product isn't the agents. The product isn't the dashboard. The product is the **trust loop**: ingest → hypothesize → test → log → learn → teach → repeat. Everything else is interface.

---

# UX Audit Response — To the Testing Committee of One

## What you tested

You ran a cold-open, zero-context test from a member account. You explored every route, stress-tested persona boundaries, deliberately tried to break guardrails (naked puts), and audited all nine personas with the same question. That's thorough work and the findings are real.

## What you found (the accurate parts)

1. **No onboarding.** A new user lands on a dense dashboard with no guidance. The most valuable interaction layer is behind an unlabeled sidebar icon. This is true.

2. **Chat persistence was broken.** Switching persona tabs destroyed conversation context. This was a real bug — a useEffect race condition. **Fixed.** Conversations now survive tab switches.

3. **Dashboard elements look interactive but aren't.** Intelligence Feed items, "View all" links, linked theses on ticker pages — they look clickable but do nothing. This is real.

4. **The Edger gave a specific trade recommendation to a beginner without disclaiming.** "PLTR — a long call, 30-45 days out, slightly out of the money." No "not financial advice" anywhere. This is a guardrail gap that needs fixing.

5. **Persona cross-referencing works.** You noted this as a strength and it is. The handoff from Thesis Genius → Vol Slayer worked. The Edger picked up cross-persona context. The Thesis Genius's naked puts pushback was excellent.

6. **Sidebar has no labels.** Six icons, no text. Real problem for discoverability.

## What you found (where I'd push back)

1. **"The agents are the product."** They're not — they're the interface to the product. The product is the trust loop: the data pipeline, the simulation engine, the backtest lifecycle, the immutable decision log, the ML models that learn from outcomes. The agents are the most visible layer, so they naturally dominate a UX test. But they're the tip.

2. **"Thesis Constellation not interactive."** It is — `onThesisSelect` opens a ThesisDrawer with details, "View Ticker" button, and "Open in Thesis Lord" link. The dots may be too small or lack hover affordance, but the interaction exists. Likely a discoverability issue, not a missing feature.

3. **"No typing indicator or streaming."** SSE streaming IS implemented — token events, streaming cursor CSS. Automated browser testing may not render incremental updates. Responses that start with tool calls show a delay before text appears (the tool executes first), which could look like "loading all at once."

## What I'd actually do with this information

**Immediate (prompt fix, no code):**
- Add "not financial advice" guardrail to The Edger's system prompt. Don't dodge trade questions — explain concepts, show data, but never frame a specific ticker + direction + instrument as a recommendation. The educational voice stays. The recommendation energy goes.

**Short-term (UI fixes):**
- Fix the broken interactive elements: Intelligence Feed click targets, "View all" links, ticker page thesis links. These are the "half the UI doesn't work" items — not polish, just wiring.
- Sidebar labels. Trivial but high-impact for first-time navigation.
- Thesis Constellation hover states — if dots aren't obviously clickable, they're not clickable.

**Not now (resist the urge):**
- Full onboarding flow, conversation history sidebar, persona subtitles, auto-greeting. These are real features on the roadmap but they're polish on top of a system that still has broken links and non-functional click targets. Fix the building before decorating the lobby.

**The question I'd ask the committee:** The audit was run from a member account. What should member-level access actually look like vs. admin? Right now they're identical. Is that intentional, or should members have a different experience (e.g., read-only simulation data, no thesis lifecycle tools)?

---

*Submitted for review. Waiting on your thoughts before touching code.*
