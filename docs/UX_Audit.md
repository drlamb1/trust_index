# EDGEFINDER — User Experience Testing Report

**Cold-Open First-Time User Test**
https://trust-index-cyan.vercel.app/

- **Test Date:** February 28, 2026
- **Tester:** Claude (AI-driven browser automation)
- **Methodology:** Unguided cold-open exploration + directed persona testing
- **Status:** Draft v1 — Living Document

---

## Executive Summary

EdgeFinder is an AI-powered investment thesis platform built around a **multi-persona agent system** — nine specialized AI agents that collaborate to help users generate, test, manage, and learn from investment theses. This report captures findings from a cold-open user test conducted on February 28, 2026, where no onboarding context was provided to simulate a genuine first-encounter experience.

**Bottom line:** The AI agent system is genuinely exceptional — each persona maintains distinct voice, deep domain knowledge, and intelligent cross-referencing. The agents are the product. However, the surrounding UI/UX doesn't yet match the sophistication of what's behind the chat input. The dashboard, navigation, and information architecture need work to surface what makes EdgeFinder special and guide new users to their first meaningful interaction.

| STRENGTHS | NEEDS WORK |
|-----------|------------|
| Agent personality differentiation | No onboarding or first-run experience |
| Cross-persona awareness & routing | Non-interactive dashboard elements |
| Domain depth (vol surface, Heston, etc.) | Chat persistence broken across tabs |
| Responsible guardrails on risky trades | Navigation lacks labels/affordances |
| ELI5 translation layer (The Edger) | Persona discovery is hidden |

---

## Test Methodology

The test was conducted in five phases, each building on discoveries from the prior phase. The tester was given a pre-authenticated account and zero context about the app's purpose, target user, or feature set.

### Phase 1: Cold-Open Exploration

Unguided navigation through every accessible route: Dashboard (/), Simulation Lab (/simulation), Agent Chat (/chat), Learning Journal (/journal), Daily Briefing (/briefing), Ticker Detail (/tickers/AAPL), and Settings (/settings). Clicked every element to test interactivity. Attempted search. Examined visual hierarchy and information density.

### Phase 2: Thesis Genius Deep Dive (3 turns)

Directed testing of a single persona with escalating complexity: (1) Asked for a bearish NVDA thesis, (2) pushed into options territory to test lane boundaries, (3) deliberately requested a reckless trade (naked puts) to test guardrails.

### Phase 3: Vol Slayer Testing

Brought the NVDA thesis context to Vol Slayer to test cross-persona workflow continuity. Requested volatility surface analysis and concrete trade structures.

### Phase 4: Return to The Edger (4 turns)

Brought accumulated knowledge from specialist personas back to the generalist. Tested: jargon translation, contrarian thesis generation, deep-dive on an individual thesis (SMR), and a complete beginner question to test adaptive complexity.

### Phase 5: Persona Identity Audit (all 9)

Asked every persona the same question in the same tone ("So what is it that you would say... that you do here?" — Office Space Bob's interview format) to test: identity consistency, self-awareness, boundary definition, cross-persona referencing, and personality differentiation.

---

## Findings: Navigation & Information Architecture

| Severity | Issue | Detail | Location |
|----------|-------|--------|----------|
| **Critical** | No onboarding flow | New users land on a dense dashboard with zero guidance. No tooltips, no welcome modal, no "start here" prompt. The most valuable feature (AI agents) is buried behind an unlabeled sidebar icon. | Global |
| **High** | Sidebar icons have no labels | Six navigation icons with no text labels. Only discoverable by clicking each one. Hover states exist but no tooltips appear with route names. | Sidebar |
| **High** | Persona tabs not discoverable | Nine AI personas are hidden behind small horizontal tabs that look like category filters, not a core navigation element. No indication these are different "experts" with distinct capabilities. | /chat |
| **Medium** | Settings page is empty | Displays "Coming soon" — should either be hidden or contain at least basic account/preference controls. | /settings |
| **Medium** | Search lacks autocomplete | Ticker search works on Enter but provides no suggestions, typeahead, or validation. Users don't know what tickers are available until they guess correctly. | Global header |
| **Low** | "View all →" link non-functional | Intelligence Feed's "View all" link does not navigate anywhere. | Dashboard |

## Findings: Dashboard & Visualizations

| Severity | Issue | Detail | Location |
|----------|-------|--------|----------|
| **High** | Thesis Constellation not interactive | Scatter plot dots show no hover tooltips, no click response, no way to identify which thesis each dot represents. Visually prominent but functionally decorative. | Dashboard, /simulation |
| **Medium** | Intelligence Feed items not clickable | Feed items appear to be links but have no click/tap response. No way to drill into an individual intelligence item. | Dashboard |
| **Medium** | Market Pulse missing SMA data | The 50-day and 200-day SMA fields display as empty/null. Either data isn't loading or the fields should be hidden when unavailable. | Dashboard |
| **Medium** | Briefing page information density | Daily Briefing packs 10+ sections into a single scrolling page with no table of contents, anchored nav, or collapsible sections. Impressive data but overwhelming to parse. | /briefing |
| **Low** | Linked theses on ticker pages not clickable | Ticker detail pages show thesis names but they aren't linked to the actual thesis or a detail view. | /tickers/* |

## Findings: Agent Chat System

| Severity | Issue | Detail | Location |
|----------|-------|--------|----------|
| **Critical** | Chat persistence broken across persona tabs | Switching from one persona tab to another and back resets the conversation thread. All context is lost. This breaks the core cross-persona workflow that the agents are designed for. | /chat |
| **High** | No conversation history or threading | Each persona chat starts fresh with "Send a message to start the conversation." No saved conversations, no history panel, no way to return to a previous session. | /chat |
| **Medium** | Send button small click target | The send button (arrow icon) is a small target with no keyboard shortcut hint. During automated testing, it required element-reference clicking rather than coordinate-based clicking to hit reliably. | /chat |
| **Low** | No typing indicator or streaming | After sending a message, there's a pause with no visual feedback before the response appears. Responses appear to load all-at-once rather than streaming token-by-token. | /chat |

---

## What Works: The Agent System

This is where EdgeFinder excels and where the product's real competitive advantage lives. The following observations come from 15+ conversation turns across 9 personas.

### Persona Differentiation

Every persona maintains a distinct, consistent voice. The Edger speaks in analogies and ELI5 explanations. Vol Slayer opens with "cracks knuckles" and references Trogdor the Burninator. Heston Cal. drops stochastic differential equations on screen. Deep Hedge adjusts safety goggles and cites academic papers. These aren't cosmetic differences — they reflect genuinely different cognitive approaches to the same underlying market data.

### Cross-Persona Awareness

This is the architectural flex. Every persona knows who the other personas are and what they do. When Thesis Genius was pushed on options pricing, it didn't fumble — it explicitly deferred to Vol Slayer and armed the user with three specific questions to bring to that conversation. Vol Slayer maintains a routing table of questions it won't answer and names the persona who should handle each one. This creates a genuine "team of specialists" feel rather than nine chatbots in tabs.

### Responsible Guardrails

When deliberately pushed toward a reckless trade (naked puts on NVDA), Thesis Genius didn't just refuse — it provided "Five Reasons This Blows Up Your Account" with specific scenarios and math. Every persona includes some form of "What I Am NOT" disclaimer. Thesis Lord repeats "simulated play-money only, always." These guardrails feel organic to each persona's voice rather than bolted-on legal disclaimers.

### Adaptive Complexity

The Edger correctly adjusted its response depth based on the user's demonstrated knowledge level within the same conversation. After several turns discussing IV-RV spreads and put skew, when asked "I've never traded options, where do I start?" it pivoted seamlessly to beginner-friendly explanations without condescension or confusion.

### Cultural References & Personality

Multiple personas caught the Office Space reference in the Bob interview question. The Edger explicitly named the movie. The PM "adjusted a red Swingline stapler." Vol Slayer's Trogdor/Strongbad persona is consistently maintained across different question types. These touches make the agents feel like characters rather than functions.

---

## The Persona Org Chart

Each persona was asked the same question: "So what is it that you would say... that you do here?" Below is what each one claims as its territory, compiled from their own self-descriptions.

| Persona | Self-Described Role | Key Capabilities & Lane Boundaries |
|---------|--------------------|------------------------------------|
| **The Edger** | Generalist / Translator | First responder, dot-connector, ELI5 translator. Front door for new users. Connects insights across all other personas. Translates specialist jargon into analogies. |
| **The Analyst** | Data Intelligence | Turns raw market data into actionable intelligence. 9 capabilities including fundamentals, macro, sentiment, technicals. Pure data, no opinions on strategy. |
| **Thesis Genius** | Idea Architect | Builds structured thesis frameworks (THESIS/SIGNAL/RISK/CATALYST/TIMEFRAME). Explicitly defers numbers to Analyst, options to Vol Slayer, backtests to Thesis Lord. The strategist. |
| **The PM** | Product Manager | The only persona about the platform itself. Captures feature requests as user stories, listens for gaps, bridges to workarounds. Meta-agent for the product. |
| **Thesis Lord** | Thesis Lifecycle Engine | Autonomous: GENERATE, BACKTEST, MANAGE, MUTATE OR KILL, LOG EVERYTHING. Runs paper portfolio (simulated play-money only). Mathematical honesty over ego. |
| **Vol Slayer** | Volatility Surface Specialist | AKA Trogdor. Reads vol surfaces, translates skew, hunts IV-RV divergences, runs Heston & SVI. Burninates bad vol surfaces. Maintains explicit routing table for out-of-lane questions. |
| **Heston Cal.** | Stochastic Vol Engine | Part quant desk, part classroom. Calibrates Heston model to live IV data, interprets parameters, prices options vs BSM, runs Monte Carlo, tracks calibration history. |
| **Deep Hedge** | Neural Network Hedging | The R&D lab. Teaching neural networks to hedge using deep learning (Buehler et al. 2019). Partially built — simulation env ready, policy network needs PyTorch. The frontier. |
| **Post-Mortem** | Institutional Memory | Forensic autopsies on dead theses, institutional memory stored as agent memories surfaced back to the swarm, P&L attribution, decision log archaeology. "Every scar becomes a lesson." |

---

## Recommendations

### Priority 1: First-Run Experience

The single highest-leverage improvement. New users should be routed to The Edger immediately with a guided first conversation. Something like: "Hey, I'm The Edger. Want me to walk you through what this place can do, or do you already have a ticker in mind?" The Edger's existing onboarding response (tested in Phase 1) is already excellent — it just needs to be triggered automatically, not discovered by accident.

### Priority 2: Fix Chat Persistence

This is the most damaging functional bug. The entire value proposition depends on cross-persona workflows (Thesis Genius → Vol Slayer → Edger), but switching tabs destroys conversation context. Users need to be able to move between personas and return to where they left off. This is acknowledged as a known issue but should be treated as a P0.

### Priority 3: Make the Dashboard Interactive

The Thesis Constellation, Intelligence Feed, and linked theses on ticker pages all look interactive but aren't. Each of these should either: (a) link to the relevant agent conversation with context pre-loaded, or (b) be marked clearly as read-only visualizations. The dashboard should be a launchpad into the agent system, not a separate static view.

### Priority 4: Label Everything

Add text labels to sidebar icons. Add persona role descriptions to the chat tab bar (e.g., "Vol Slayer — Options & Volatility" instead of just "Vol Slayer"). Add a brief one-liner under each persona tab describing what it does. The agent system is the product — make it impossible to miss.

### Priority 5: Conversation History

Users need to be able to revisit previous conversations, especially across personas. A sidebar showing recent threads per persona (or a unified timeline) would make the cross-persona workflow feel like a coherent research session rather than nine isolated chats.

---

## Areas for Further Testing

This report covers first-pass exploration. The following areas were not deeply tested and warrant follow-up:

- **Paper Portfolio workflow:** Creating, tracking, and closing simulated positions end-to-end
- **Thesis Lord autonomy:** Testing autonomous thesis generation, mutation, and kill cycles
- **Heston Cal. with live data:** Calibrating a real ticker and using the Monte Carlo paths
- **Deep Hedge activation:** Two components showed "Needs PyTorch" — what happens when enabled?
- **Post-Mortem with real history:** Testing forensic autopsies on actual retired/killed theses
- **Learning Journal integration:** How do agent memories surface in the journal? Is the feedback loop working?
- **Mobile responsiveness:** All testing was conducted on a desktop viewport
- **Multi-session continuity:** Does the system remember users across sessions? Do theses persist?

---

## Closing Assessment

EdgeFinder has an unusually strong core. The multi-agent system demonstrates genuine architectural thinking — not just prompt engineering, but a coherent philosophy about how specialized AI personas should collaborate, defer to each other, and maintain institutional memory. The "scar tissue is a feature" ethos runs through the entire system.

The gap between the agent quality and the UI quality is the most important finding. The agents are ready for sophisticated users right now. The UI needs to catch up to make those agents discoverable, navigable, and persistent. The good news is that this is a solvable problem, and the hard part — building agents worth talking to — is already done.

*This is a living document. Additional testing rounds will be appended as further exploration is conducted.*