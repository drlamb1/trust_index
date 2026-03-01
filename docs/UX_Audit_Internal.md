# EDGEFINDER — Internal UX Audit (Code-Level)

**Auditor:** Claude (codebase review, not browser automation)
**Date:** February 28, 2026
**Methodology:** Full source read of frontend + backend + chat engine
**Baseline:** Blind tester report (docs/UX_Audit.md) — used as input, not gospel

---

## Where the Blind Tester Was Right

### 1. The agents ARE the product
Confirmed. 9 personas with genuinely distinct system prompts (not template variations), 46 tools with real implementations, a 4-tier routing system that's architecturally sound, and cross-persona awareness baked into every system prompt. The blind tester's strongest finding holds up completely under code review.

### 2. Chat persistence was broken
Was true at time of testing. The last 3 commits (`74593c2`, `7a3adf0`) fixed this. Conversations now persist per-persona in localStorage (keyed `edgefinder_conv_{persona}`) and restore from the DB via `/api/chat/conversations/{id}/messages` on tab switch. **This is resolved.**

### 3. Settings page is a stub
Confirmed. It's literally `<div>Settings — coming soon</div>` inline in App.tsx (line 46). The sidebar still links to it. Either hide the nav item or ship something minimal.

---

## Where the Blind Tester Was Wrong

### 1. "Thesis Constellation not interactive" — WRONG
The constellation IS interactive. `ThesisConstellation.tsx` fires `onThesisSelect()` on node click, which opens a `ThesisDrawer` component — a 380px side panel with full thesis details, a "View Ticker" button linking to `/tickers/:symbol`, and a "Discuss with Thesis Lord" button linking to `/chat?persona=thesis_lord&message=...`. The blind tester's browser automation likely failed to detect the drawer opening, or clicked the canvas background instead of a node. The hover cursor change is implemented (`pointer` on node hover). This is working as designed.

### 2. "Intelligence Feed items not clickable" — PARTIALLY WRONG
Feed items with a ticker ARE clickable — `IntelligenceFeed.tsx` navigates to `/tickers/{ticker}` on click when a ticker is present in the event data. Items without tickers (general system events) correctly have no click target. The blind tester may have been clicking non-ticker events.

### 3. "No typing indicator or streaming" — WRONG
SSE streaming is fully implemented. The frontend handles `token` events and appends text in real-time with a streaming cursor (CSS class `streaming-cursor` with an amber blinking `▋` character). The `round_start` event correctly freezes prior text before tool execution rounds. This is a sophisticated implementation, not a "load all-at-once" pattern.

### 4. "Sidebar icons have no labels" — MISLEADING
The sidebar has text labels on every nav item. `Sidebar.tsx` renders both a Lucide icon AND a text label (`Dashboard`, `Simulation Lab`, `Agent Chat`, `Learning Journal`, `Briefing`). The sidebar is 88px wide with labels below icons. This isn't "icons with no labels" — it's compact labels. Whether they're discoverable enough is a design opinion, but the claim that there are "no text labels" is factually incorrect.

### 5. "Send button small click target" — BROWSER AUTOMATION ARTIFACT
The send button is a standard 36x36px icon button. The blind tester noted it "required element-reference clicking rather than coordinate-based clicking" — this is a limitation of their automated testing tool, not a UX problem. Real users clicking with a mouse or tapping on mobile would have no issue.

---

## What the Blind Tester Missed Entirely

### 1. SimulationEngine sparkline is fake data (MEDIUM)
`SimulationEngine.tsx` lines 54-56: the P&L sparkline is a hardcoded sine wave with noise — `Array.from({ length: 30 }, (_, i) => ({ v: 100000 + Math.sin(i * 0.4) * 3000 ... }))`. There's even a comment: "placeholder until we connect historical P&L API." This is visible on both the Dashboard and Simulation Lab. A user who watches it will notice it never changes and doesn't correlate with actual portfolio P&L. **This is more misleading than a missing feature — it looks real but isn't.**

### 2. No error states on several data-fetching components (MEDIUM)
- `MarketPulse.tsx`: If `/api/macro/pulse` fails, skeleton cards display forever with no error message. User sees perpetual loading.
- `SimulationEngine.tsx`: If `/api/simulation/stats` fails, stat tiles show stale or default values with no indication of failure.
- `IntelligenceFeed.tsx`: If SSE connection drops, the connection dot goes dark but there's no "reconnect" button or retry UI.
- `Briefing.tsx`: If markdown fetch fails, no error state.

These aren't edge cases — FRED data depends on an external API, and Railway cold starts can cause timeouts.

### 3. Conversation history UI doesn't exist (HIGH)
The backend has `GET /api/chat/conversations` that returns a list of all user conversations. The frontend never calls it in a visible way. There's no sidebar, no history panel, no way to browse past conversations. The per-persona localStorage key only stores the LATEST conversation ID — starting a "new conversation" permanently orphans the old one. Users can never get back to a previous conversation. The blind tester noted this but undersold its severity.

### 4. Vol Surface data fetched but never displayed (LOW)
`/api/simulation/vol-surface/{ticker}` is defined in the API module (`lib/api.ts`) but the frontend never renders it. The SimulationLab shows Heston calibration parameters but not the actual implied volatility surface. For a platform with "Vol Slayer" as a persona, this is a gap. Not urgent, but notable.

### 5. Decision Log not surfaced anywhere (LOW)
`/api/simulation/decision-log` exists and returns paginated SimulationLog entries with filters. The frontend never fetches or displays it. The data is there — it just needs a UI. The LearningJournal page shows agent memories but not the decision log, which is a different (and arguably more valuable) dataset.

### 6. ML Status endpoint not surfaced (LOW)
`GET /api/ml/status` returns active model versions, eval metrics, training timestamps, and model hashes. No frontend page displays this. When ML models are active, users have no visibility into what's running. Could be a simple card on the SimulationLab page.

### 7. No pagination anywhere (MEDIUM)
- LearningJournal: Fetches 30 memories, no "load more"
- IntelligenceFeed: Keeps last 50 items in-memory, older items gone
- TickerDetail theses: Max 20, no pagination
- TickerDetail backtests: Max 20, no pagination
- Decision log: Not rendered at all

This will become a real problem as the system generates more data. 509 tickers generating theses, backtests, alerts, and memories will exceed these limits quickly.

### 8. Ticker search has no validation feedback (MEDIUM)
TopBar search converts input to uppercase and navigates to `/tickers/:symbol` on Enter. If the ticker doesn't exist, TickerDetail.tsx shows "Ticker {sym} not found in watchlist" — but only AFTER the navigation and API call. There's no typeahead, no suggestion dropdown, no inline validation. With 509 active tickers, users are guessing. The blind tester mentioned "no autocomplete" but didn't flag the post-navigation error as a UX issue.

### 9. No mobile responsiveness testing needed — but layout will break (LOW)
All layouts use fixed pixel widths: sidebar 88px, drawer 380px, TopBar 56px height. The Dashboard uses a percentage-based grid (55%/45%) which is good, but the fixed sidebar + topbar + drawer stack means screens under ~600px wide will have content overlap. Not a priority if this is a desktop-first tool, but worth documenting.

### 10. Chat deep-linking is excellent but undiscoverable (OBSERVATION)
Chat.tsx reads `?persona=` and `?message=` query params on mount, enabling pre-filled conversations from anywhere in the app. The AgentConsole, ThesisDrawer, and TickerDetail all use this pattern. But users can't construct these URLs themselves, and there's no "share this conversation" or "copy link" feature. This is a hidden superpower that could be surfaced.

---

## What's Actually Good (Beyond the Agents)

The blind tester focused heavily on agent quality and underreported the structural strengths:

1. **TickerDetail page is genuinely complete.** Price chart, technicals (7 indicators, color-coded), linked theses, alerts with severity, backtest history with Sharpe/Sortino/p-value — all from 5 parallel API calls. This is a real equity research page.

2. **The dual-auth strategy is correct.** Bearer tokens for SPA, cookie fallback for EventSource SSE (which can't set custom headers). This solves the Vercel-to-Railway cross-origin problem cleanly.

3. **Token budget enforcement for viewers is well-implemented.** Per-user daily budgets checked before chat turns, tracked per-message, with clear 429 responses. The viewer system prompt restriction is also smart — it constrains at the AI level, not just the tool level.

4. **The agentic loop (max 5 rounds) with tool persistence is production-grade.** Each tool call and result gets its own DB row with sequence numbers, enabling full audit trails. The context reconstruction from DB rows back into Claude format (grouping tool_call rows into assistant blocks) is non-trivial and working correctly.

5. **Market status indicator is a nice touch.** TopBar shows green "Market Open" badge during NYSE hours (Mon-Fri 9:30-16:00 ET), auto-updates every second. Small detail, but signals that this is a live market tool.

---

## Prioritized Recommendations

### Tier 1: Fix What's Misleading

| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 1 | **Replace fake sparkline with real data or remove it** | Small | High — fake data erodes trust in a platform about trust signals |
| 2 | **Add error states to MarketPulse, SimulationEngine, Briefing** | Small | Medium — perpetual loading is worse than "data unavailable" |
| 3 | **Hide Settings nav item or ship a minimal page** | Trivial | Low — but "coming soon" in a shipped product looks unfinished |

### Tier 2: Surface What's Already Built

| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 4 | **Add conversation history sidebar in Chat** | Medium | High — the backend endpoint exists, just needs UI |
| 5 | **Show ML model status somewhere** | Small | Low — the endpoint exists, add a card to SimulationLab |
| 6 | **Render decision log in LearningJournal or SimulationLab** | Small | Medium — the data is there, users just can't see it |
| 7 | **Display vol surface on SimulationLab** | Medium | Medium — completes the Heston panel story |

### Tier 3: Improve Discoverability

| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 8 | **First-run onboarding to The Edger** | Medium | High — agree with blind tester, this is the front door |
| 9 | **Ticker search autocomplete** | Medium | Medium — 509 tickers is too many to guess |
| 10 | **Persona role descriptions on chat tabs** | Small | Medium — "Vol Slayer" means nothing to a new user |

### Tier 4: Scaling Prep

| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 11 | **Pagination for memories, theses, backtests, alerts** | Medium | Future-high — will matter when data volume grows |
| 12 | **Reconnect UI for SSE feeds** | Small | Low — only matters on unreliable connections |

---

## Disagreements with Blind Tester's Recommendations

### Their Priority 2 (Chat Persistence) — Already Fixed
The last 3 commits addressed this. Per-persona localStorage keys, DB-backed message restoration on tab switch. Conversation context survives persona switching. **Done.**

### Their Priority 3 (Make Dashboard Interactive) — Already Is
The Thesis Constellation clicks open a drawer. The Intelligence Feed items link to ticker pages. The AgentConsole routes to Chat. The dashboard IS a launchpad — the blind tester's automation just didn't detect it.

### Their Priority 1 (First-Run Experience) — Agree, But Nuance
The Edger auto-greeting is a good idea, but it needs to be opt-in or dismissible. Forcing a modal/conversation on every new session would be annoying for returning users. A better pattern: detect first-ever visit (no localStorage keys exist) and auto-open The Edger with a welcome message. Subsequent visits land on the dashboard normally.

### Their Priority 5 (Conversation History) — Underweighted
This should be Priority 2, not 5. The inability to revisit conversations is a bigger problem than labeling. The backend already supports it — this is pure frontend work.

---

## Summary

The blind tester's report is useful but has significant false positives (constellation "not interactive", feed "not clickable", "no streaming") that appear to stem from browser automation limitations rather than actual UX failures. Their strongest findings — agent quality, onboarding gap, conversation history — hold up. Their weakest findings are about interactivity that actually exists.

The real gaps they missed: fake sparkline data, missing error states, orphaned conversations, unsurfaced backend features (vol surface, decision log, ML status), and zero pagination. These are more actionable than most of what the blind tester flagged.

**Overall assessment:** The product is further along than the blind tester's report suggests. The biggest risk isn't missing features — it's that built features aren't visible to users, and one component (sparkline) is actively misleading.
