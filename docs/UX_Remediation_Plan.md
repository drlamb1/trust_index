# EdgeFinder UX Remediation Plan

**Source:** UX_Test_2.md (Round 2 usability test, 50 minutes, 3 rounds)
**Baseline:** 55 commits in 48 hours (Feb 27-Mar 1, 2026), two prior audits (UX_Audit.md, UX_Audit_Internal.md)
**Design Direction:** Dashboard-first, chat discoverable from dashboard surfaces
**Date:** March 1, 2026

---

## Context

The Round 2 usability test (UX_Test_2.md) was conducted after a 14-commit UX overhaul that addressed many findings from the original blind test. The tester spent 50 minutes across 3 rounds: surface exploration, deep persona conversations, and targeted tasks. Their verdict: "the chat layer is production-quality, the data pages are beta-quality, and the gap between them is the product's defining tension."

Many original audit findings have been addressed (chat persistence, welcome overlay, guide page, settings page, search autocomplete, persona roles, conversation history, fake sparkline, error states, vol surface/decision log/ML status wiring). This plan covers what remains.

---

## Workstream 1: Pipeline Warming & Feed Readiness

**Problem (revised):** The UX tester saw "every entry said pr_merge" and called it trust-destroying. But the root cause isn't data leaking — it's data *sparsity*. 24 PRs merged in 48 hours while the simulation pipeline hadn't had runtime to generate intelligence events (thesis_created, signal_detected, backtest_complete). Once the pipeline warms up, real events will naturally outnumber pr_merge. The fix is making the pipeline produce events, not hiding the ones it has.

**Approach:** Three-layer fix: (1) trigger pipeline data production, (2) visually distinguish system events from intelligence events, (3) add "warming up" empty-state handling.

### Tasks

#### 1.1 Trigger data pipeline to generate real events
**Action:** Run price backfill (`task_fetch_prices_batch`), confirm Beat scheduler is firing thesis generation (`task_scan_for_convergence`), signal detection, and dip scoring tasks. The real fix is making the pipeline produce intelligence events.
**Verification:** After pipeline runs for 1-2 cycles, check `simulation_logs` for non-pr_merge event types. If thesis generation, signal detection, and backtest events are flowing, the feed will self-correct.

#### 1.2 Visual tiering for system vs intelligence events
**File:** `frontend/src/components/dashboard/IntelligenceFeed.tsx`
**Change:** Don't filter pr_merge — instead, visually tier events:
- **Intelligence events** (thesis_created, signal_detected, backtest_complete, position_opened, thesis_killed, DAILY_BRIEFING): full color, normal text, clickable
- **System events** (pr_merge, BACKTEST_START, BACKTEST_COMPLETE): dimmed text (color-text-dim), smaller font, collapsed into an "N system events" accordion when >3 consecutive
- Add icon mapping for DAILY_BRIEFING (BookOpen) → clickable, navigates to `/briefing`
- This preserves the audit trail for admins while not competing with intelligence events visually

#### 1.3 Decision Log default filter
**File:** `frontend/src/components/simulation/DecisionLog.tsx` (line 55)
**Change:** Default the active filter to a new "Intelligence" meta-filter that shows thesis_created, backtest_complete, position_opened, position_closed, signal_detected, thesis_killed, DAILY_BRIEFING. Add a separate "System" filter for pr_merge, BACKTEST_START, BACKTEST_COMPLETE. "All" still shows everything.

#### 1.4 Empty-state awareness
**File:** `frontend/src/components/dashboard/IntelligenceFeed.tsx`
**Change:** When connected but all events are system events (pr_merge), show a contextual note above the feed: "Intelligence pipeline is syncing data. Signals will appear as the system detects thesis-worthy patterns." This handles the cold-start gracefully instead of showing what looks like broken data.

### Consistency with PM knowledge lifecycle (PRs #23-26)

The PM's Jinja2 brief (`docs/pm_brief.md.j2`) now reports live pipeline stats. This workstream ensures those stats reflect actual pipeline activity. When the pipeline warms up:
- PM's brief shows real thesis/backtest counts (not zero)
- Intelligence Feed shows real events (not just pr_merge)
- PM's `list_available_capabilities` tool returns accurate live stats
All three layers update automatically — no manual sync needed.

---

## Workstream 2: Cross-Persona Context Sharing (FR-14) — Full Implementation

**Problem:** Switching personas starts a completely new conversation. The tester manually carried Vol Slayer's output to The Edger by copy-pasting — it worked beautifully but required human routing. The tester called this "probably the platform's biggest usability gap."

**Approach:** Shared conversation threads where multiple personas participate in sequence with full context. This is a significant architectural change.

### Architecture Design

**Current state:** Each conversation has one `active_persona`. Switching personas either loads a different conversation (localStorage-keyed) or creates a new one. Messages belong to a conversation, not a persona.

**Target state:** A conversation can have messages from multiple personas. The `active_persona` field on the conversation tracks the *current* persona, but historical messages retain their `persona` field. When a user switches personas mid-conversation (or the system hands off), the new persona receives the full conversation history — it sees what prior personas said.

**Key design decisions:**
- A "handoff" is NOT a new conversation — it's a persona change within the existing conversation
- The system prompt changes to the new persona's prompt on handoff
- The new persona sees all prior messages (including tool calls/results from other personas)
- The conversation title stays the same (user can rename)
- The persona tabs become a "current speaker" selector, not a conversation switcher
- Conversation history panel shows conversations with multi-persona badges

### Tasks

#### 2.1 Backend: Allow persona changes within a conversation
**File:** `chat/engine.py`
**Change:** When `run_chat_turn` is called with a different persona than `conv.active_persona`:
- Update `conv.active_persona` to the new persona
- Load the full message history (same conversation) — don't start fresh
- Build context using the NEW persona's system prompt but ALL prior messages
- Add a system-injected message like "[Context: You are joining a conversation previously handled by {old_persona}. The user has requested your perspective.]"

#### 2.2 Backend: Conversation summary injection for long threads
**File:** `chat/engine.py`
**Change:** If conversation history exceeds `CONTEXT_WINDOW` (20 messages), generate a Claude-powered summary of the earlier messages and inject it as context. This prevents context window overflow while preserving continuity. Use Haiku for the summary to keep costs low.

#### 2.3 Frontend: Unified conversation with persona switching
**File:** `frontend/src/pages/Chat.tsx`
**Changes:**
- Remove per-persona localStorage conversation keys. One active conversation per session.
- Persona tabs become a "switch speaker" action within the current conversation, NOT a conversation switcher
- When user clicks a different persona tab: send a lightweight API call to update `active_persona`, then continue in the same message thread
- Show a visual separator in the message thread when personas change: "--- The Edger handed off to Vol Slayer ---"
- Each message bubble shows which persona sent it (small badge/tag)
- The "+" button creates a genuinely new conversation (with confirmation dialog — see Workstream 3)

#### 2.4 Frontend: Multi-persona conversation history
**File:** `frontend/src/pages/Chat.tsx`
**Change:** In the conversation history panel, show which personas participated in each conversation. E.g., "NVDA Analysis — Edger, Vol Slayer, Thesis Lord" with small persona avatars.

#### 2.5 Backend: Handoff tool enhancement
**File:** `chat/tools.py` (suggest_handoff tool)
**Change:** When a persona calls `suggest_handoff`, it should:
- Optionally include a "handoff_context" field — a 2-3 sentence summary of what the user should explore with the target persona
- This context gets injected into the next turn as a system message for the target persona
- The handoff becomes a recommendation that the user can accept (click the suggested persona) or ignore

---

## Workstream 3: Chat UX Polish

**Problem:** Several friction points in the chat experience beyond persona switching.

### Tasks

#### 3.1 Confirmation dialog on "+" (new conversation) button
**File:** `frontend/src/pages/Chat.tsx` (lines 622-641)
**Change:** Show a confirmation dialog: "Start a new conversation? Your current conversation will be saved to history." Two buttons: "New Conversation" (primary) and "Cancel". Only shown when current conversation has messages.

#### 3.2 Sticky persona tabs
**File:** `frontend/src/pages/Chat.tsx` (lines 519-582)
**Change:** Use `position: sticky; top: 0; z-index: 10` on the persona tab bar so it stays visible as the user scrolls through conversation messages. Add a subtle bottom border or shadow when scrolled to indicate stickiness.

#### 3.3 Persona tab UX improvements
**File:** `frontend/src/pages/Chat.tsx`
**Changes:**
- After Workstream 2 (FR-14), tabs should visually indicate the "active speaker" (highlight current persona, dim others)
- Show a small indicator on personas that have participated in the current conversation
- On narrow viewports, ensure horizontal scroll works smoothly with left/right fade masks

---

## Workstream 4: Briefing Formatting

**Problem:** The briefing page renders as dense text walls. The tester specifically called out 10-K Drift, Watchlist Movers, and Top News as hard to scan. The frontend HAS markdown table support (react-markdown + remark-gfm), so the issue is in backend markdown generation.

### Tasks

#### 4.1 Audit briefing markdown generation
**File:** `daily_briefing.py` (the section builder functions)
**Change:** For each section, verify the output is structured markdown with tables where appropriate:
- **Watchlist Movers:** Should be a markdown table: `| Ticker | 5D % | Price | Signal |`
- **Top News:** Should be a markdown table: `| Headline | Ticker | Sentiment | Source |`
- **10-K Drift:** Should be a table: `| Ticker | Metric | Last Year | This Year | Change |`
- **Technical Signals:** Table: `| Ticker | Signal | Value | Interpretation |`
- **Insider Buying:** Table: `| Insider | Ticker | Amount | Date |`
- **Alerts:** Table or card format: `| Alert | Ticker | Severity | Time |`

#### 4.2 Add collapsible sections
**File:** `frontend/src/pages/Briefing.tsx`
**Change:** Wrap each h2 section in a collapsible `<details>` element (or custom accordion). All sections expanded by default, but users can collapse sections they've already reviewed. This reduces visual density for returning users.

#### 4.3 Add a table of contents
**File:** `frontend/src/pages/Briefing.tsx`
**Change:** Parse h2 headers from the markdown and render a clickable table of contents at the top. Each link scrolls to the corresponding section. Style as a horizontal pill strip (not a vertical sidebar) to save space.

---

## Workstream 5: Data Coverage Expansion

**Problem:** Non-watchlist tickers (TSLA, etc.) show empty pages — no price chart, no technicals, no theses. With 509 active tickers but data only on ~11, 96% of searchable tickers have hollow pages.

### Tasks

#### 5.1 Trigger historical price backfill for all active tickers
**Action:** Run `task_fetch_prices_batch.apply_async(kwargs={"days": 365})` on the worker
**Prerequisite:** Verify the task handles 509 tickers without rate-limit issues (yfinance throttling). May need to batch in groups of 50 with delays.
**Expected outcome:** 509 tickers with 365 days of PriceBar data, enabling price charts and technical indicators on all ticker pages.

#### 5.2 Verify SMA 50/200 calculation
**File:** `api/ticker_routes.py` (the technicals calculation in the ticker summary endpoint)
**Investigation:** SMA 50 and SMA 200 show "–" on both SMR and AAPL. This could be:
- Insufficient price history (need 200 bars for SMA 200)
- Calculation bug in the API endpoint
- Frontend display issue
**Fix:** Identify root cause and fix. If insufficient history, the backfill in 5.1 should resolve it. If calculation bug, fix the query.

#### 5.3 Improve empty state UX as fallback
**File:** `frontend/src/pages/TickerDetail.tsx`
**Change:** Even after backfill, some tickers may lack theses, alerts, or backtests. Improve empty states:
- Price chart: Show "Loading price data..." or "Price data syncing — check back in an hour" instead of empty space
- Technicals: Show which indicators are available vs pending
- Theses: Keep the current CTA ("ask the Thesis Lord to propose one") — it's well-written
- Add a "Data Coverage" indicator showing which data sources are populated for this ticker

---

## Workstream 6: Dashboard Polish

**Problem:** Several smaller issues on the dashboard that collectively affect perceived quality.

### Tasks

#### 6.1 Thesis Constellation dot affordance
**File:** `frontend/src/components/dashboard/ThesisConstellation.tsx`
**Change:** The clickable thesis list below the canvas (added in #20) is the reliable interaction path. But the canvas dots should also work visually:
- Add a visible hover effect: enlarge dot by 1.5x on hover with a glow/ring
- Add a tooltip on hover showing thesis name + ticker + score
- If the `onNodeClick` handler is already wired (it is), the issue is likely that dots are too small. Increase `nodeRelSize` or minimum node radius.

#### 6.2 Intelligence Feed clickability
**File:** `frontend/src/components/dashboard/IntelligenceFeed.tsx`
**Change:** After pr_merge events are filtered (Workstream 1), make remaining event types more interactive:
- DAILY_BRIEFING → navigate to `/briefing`
- thesis_created → navigate to `/chat?persona=thesis_lord&message=Tell me about the latest thesis`
- signal_detected → navigate to `/tickers/{ticker}`
- Add hover effect and cursor:pointer to all clickable items

#### 6.3 Settings page Guide link
**File:** `frontend/src/pages/Settings.tsx` (line 159)
**Investigation:** The tester reported the Guide link on Settings didn't navigate. Verify `<Link to="/guide">` works and the route is registered in `App.tsx`. If it's a `<a href>` instead of a React Router `<Link>`, fix it.

#### 6.4 Token Budget explanation
**File:** `frontend/src/pages/Settings.tsx`
**Change:** Add a tooltip or subtitle explaining what Token Budget means: "Daily AI conversation allowance. Resets at midnight UTC." If `daily_token_budget` is undefined/null from the backend, show "Unlimited" instead of "–".

---

## Workstream 7: Simulation Lab Polish

**Problem:** Several visual/UX issues on the Simulation Lab page.

### Tasks

#### 7.1 Vol Surface heatmap axis labels
**File:** `frontend/src/components/simulation/VolSurfaceHeatmap.tsx`
**Change:** Axis labels are overlapping and unreadable. Options:
- Rotate X-axis labels 45° or 90°
- Reduce label frequency (show every 2nd or 3rd label)
- Use abbreviated labels (e.g., "30d" instead of "30 days")
- Increase chart width or reduce padding

#### 7.2 Heston Calibration empty state
**File:** Relevant SimulationLab component
**Change:** When Heston shows "No calibration for {ticker}. Options data needed first," add actionable guidance:
- "Options data syncs automatically at market close. Check back tomorrow."
- Or: "Ask Heston Cal. to explain what calibration means → link to `/chat?persona=heston_cal&message=What is Heston calibration?`"

#### 7.3 Learning Journal read-side fix
**Investigation:** The UX tester found "accessed 0x" on all learning journal entries — lessons are written but never retrieved. Check:
- **File:** `chat/tools.py` — Does `get_learning_nugget` actually query and mark access?
- **File:** `chat/engine.py` — Is Edger's system prompt enforcement (must call get_learning_nugget) actually triggering retrievals?
- **File:** The `agent_memories` table — Are memories being written? (Post-Mortem reported 0 entries)
**Expected fix:** Ensure `get_learning_nugget` increments an access counter on the memory/lesson it retrieves.

---

## Workstream 8: Data Integrity Fixes

**Problem:** Backend data quality issues flagged by the personas themselves during testing.

### Tasks

#### 8.1 Insider signal dimension (FR-17)
**Investigation:** The PM reported the insider signal dimension in the 8-factor dip composite is scoring zero silently, corrupting composite scores.
**File:** Likely in `analysis/` or `scheduler/tasks.py` — the dip scoring task
**Fix:** Identify why insider data isn't populating, fix the scoring function, and add a zero-value guard that logs a warning instead of silently scoring zero.

#### 8.2 Thesis retirement reason enforcement
**Investigation:** Post-Mortem found 5+ theses killed with `retirement_reason: null`. No documented cause of death.
**File:** `simulation/thesis_generator.py` or wherever `kill_thesis` is called
**Fix:** Make `retirement_reason` required when transitioning to KILLED status. Add categories: `duplicate`, `wrong_framing`, `market_exit`, `signal_decay`, `negative_sharpe`. Reject kills without a reason.

#### 8.3 Duplicate thesis detection
**Investigation:** Post-Mortem identified ~75% of kills were duplicate pipeline failures (4 PLTR dips, 3 NVDA sentiments, etc.)
**File:** `simulation/thesis_generator.py` — `detect_signal_convergence` and `propose_thesis`
**Fix:** Before proposing a new thesis, check for existing PROPOSED/PAPER_LIVE theses with the same ticker + category. If a near-duplicate exists, log it as a suppression event (visible in Decision Log) instead of creating and immediately killing.

---

## Established Pattern: PM Knowledge Lifecycle (PRs #23-26)

The PM's stale knowledge problem has already been solved with a two-layer approach. This pattern should NOT be re-implemented — it's here as context for consistency.

**Layer 1 — Passive (always-on system prompt context):**
- `docs/pm_brief.md.j2` — Jinja2 template rendered at chat-turn time
- Live DB counts: tickers, theses, backtests, portfolios, conversations, FRs, sim logs
- Persona names and tool counts from Python registries
- 5-minute TTL cache (`_pm_brief_cache` in `chat/engine.py`)
- Structural content (topology, pipeline, roadmap, known gaps) deploys with code; stats refresh automatically

**Layer 2 — Active (tool-callable):**
- `list_available_capabilities` tool in `chat/tools.py` — live DB counts + static capability descriptions
- PM calls this when asked explicit questions about platform state

**Consistency notes for other workstreams:**
- WS2 (FR-14) should update the PM brief template to reflect multi-persona conversations once shipped
- WS5 (Data Backfill) will cause PM's live stats to show real thesis/backtest counts (currently near-zero)
- If adding new personas or tools, the Jinja2 template auto-reflects them (reads from PERSONA_CONFIGS registry)
- The `capabilities` list in the tool (16 static descriptions) could drift from reality — consider templating it too, or accepting that the PM brief covers architecture and the tool covers features

---

## Priority & Sequencing

| Phase | Workstreams | Rationale |
|-------|-------------|-----------|
| **Phase 1** (immediate) | WS1 (Pipeline Warming) + WS5.1 (Data Backfill) | Start the pipeline producing real events. Backfill runs in background while frontend work proceeds. |
| **Phase 2** (same day) | WS3 (Chat Polish) + WS5.2 (SMA fix) | Quick wins that address visible friction. |
| **Phase 3** (next day) | WS4 (Briefing) + WS6 (Dashboard Polish) | Surface quality improvements. |
| **Phase 4** (2-3 days) | WS2 (FR-14 Cross-Persona) | Biggest architectural change. Requires careful implementation. |
| **Phase 5** (parallel with Phase 4) | WS1.2-1.4 (Feed visual tiering) + WS5.3 (Empty States) | Once pipeline is producing events, tier the display and improve empty states. |
| **Phase 6** (after core UX) | WS7 (Sim Lab) + WS8 (Data Integrity) | Important but not user-facing blockers. |

---

## Success Criteria

After all workstreams, a new user should be able to:

1. **Land on Dashboard** and see intelligence events (thesis_created, signal_detected) with system events visually deprioritized, live macro data, and a clickable thesis constellation
2. **Click any thesis** → open detail drawer → navigate to ticker page with full data (price chart, technicals, theses, alerts)
3. **Search any S&P 500 ticker** → get a populated ticker page with 365 days of price history
4. **Open the Briefing** → scan formatted tables, collapse sections, jump to sections via TOC
5. **Start a conversation with The Edger** → get a structured, data-rich response → switch to Vol Slayer mid-conversation without losing context → switch back and The Edger can reference what Vol Slayer said
6. **See which personas have participated** in a conversation thread via visual indicators
7. **Click "+" to start new chat** → get a confirmation dialog before losing current conversation

---

## Files Index (for implementation sessions)

**Workstream 1:**
- Pipeline tasks: `task_fetch_prices_batch`, `task_scan_for_convergence`, Beat scheduler verification
- `frontend/src/components/dashboard/IntelligenceFeed.tsx` — visual tiering, empty-state awareness
- `frontend/src/components/simulation/DecisionLog.tsx` — default filter to Intelligence events

**Workstream 2:**
- `chat/engine.py` — conversation persona switching, context building
- `chat/tools.py` — handoff tool enhancement
- `frontend/src/pages/Chat.tsx` — unified conversation model, persona switching UI

**Workstream 3:**
- `frontend/src/pages/Chat.tsx` — confirmation dialog, sticky tabs

**Workstream 4:**
- `daily_briefing.py` — markdown table formatting per section
- `frontend/src/pages/Briefing.tsx` — collapsible sections, TOC

**Workstream 5:**
- Worker task: `task_fetch_prices_batch` — trigger backfill
- `api/ticker_routes.py` — SMA calculation investigation
- `frontend/src/pages/TickerDetail.tsx` — empty state improvements

**Workstream 6:**
- `frontend/src/components/dashboard/ThesisConstellation.tsx` — dot affordance
- `frontend/src/components/dashboard/IntelligenceFeed.tsx` — clickability
- `frontend/src/pages/Settings.tsx` — Guide link, token budget

**Workstream 7:**
- `frontend/src/components/simulation/VolSurfaceHeatmap.tsx` — axis labels
- `chat/tools.py` — learning nugget access counter
- SimulationLab Heston empty state

**Workstream 8:**
- `analysis/` or `scheduler/tasks.py` — insider signal scoring
- `simulation/thesis_generator.py` — retirement reasons, dedup

---

## What's Already Done (for context — do not re-implement)

These items from the original UX audits have been addressed in the last 48 hours:

- [x] Chat persistence across persona tabs (commits 74593c2, b0f73b1, 3a336e6)
- [x] Welcome overlay for first-time users (7f4bdb7)
- [x] Guide page with persona directory (da9cbe2)
- [x] Settings page with account/password/session (0082283)
- [x] Ticker search autocomplete with backend endpoint (68daace)
- [x] Persona role descriptions on chat tabs (34c4d86)
- [x] Conversation history panel in Chat (9b54103)
- [x] Fake sparkline replaced with real portfolio summary (13926a9)
- [x] Error states on dashboard components (9d6fcc5)
- [x] Vol surface heatmap wired into SimulationLab (c2777c0)
- [x] Decision log wired into SimulationLab (cfcd85d)
- [x] ML model status wired into SimulationLab (223d9c3)
- [x] Load-more pagination on LearningJournal and TickerDetail (b7a8cff)
- [x] Chat conversation isolation per user / IDOR fix (3a336e6)
- [x] Stale static capabilities replaced with live DB queries (10b80cd)
- [x] Clickable thesis list below constellation canvas (7e83c47)
- [x] Sticky chat tabs, discoverable new-convo button (8775302)
- [x] Sidebar labels on all nav items (existing — blind tester was wrong)
- [x] SSE streaming with token events (existing — blind tester was wrong)
- [x] Edger synthesis and lesson taught on Briefing page (e959525)
- [x] PM stale capabilities tool → live DB queries (PR #23, 10b80cd)
- [x] PM architecture brief injected into system prompt (PR #25)
- [x] PM brief converted to Jinja2 template with live stats, 5-min TTL (PR #26)
