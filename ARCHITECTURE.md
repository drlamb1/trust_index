# EdgeFinder — Architecture, Intent & Vision

## What This Is

EdgeFinder is a Python market intelligence platform deployed on Railway. It ingests SEC filings, tracks news sentiment, detects price/volume anomalies, scores investment theses, and delivers daily intelligence briefings. It combines quantitative signals with Claude-powered qualitative analysis and exposes everything through an agentic multi-persona chat system. Targeting the full S&P 500 universe as a baseline, with active weekly auto-sync. Currently bootstrapped with a seed watchlist; full constituent sync runs via task_sync_sp500.

It's also a personal learning lab — a system designed to sharpen ML intuition, deepen understanding of market microstructure, and build real muscle with agentic AI patterns, all against live market data.

---

## Current State (Phases 1-4 Complete, Phase 5 Partial, Pipeline Live)

### The Data Pipeline

```
Market Sources              Ingestion              PostgreSQL           Analysis              Output
─────────────              ─────────              ──────────           ────────              ──────
yfinance/AV/Polygon  ───►  price_data.py    ───►  PriceBar       ───►  technicals.py    ───►  TechnicalSnapshot
SEC EDGAR            ───►  sec_edgar.py     ───►  Filing/Section ───►  filing_analyzer  ───►  FilingAnalysis
Finnhub/NewsAPI/RSS  ───►  news_feed.py     ───►  NewsArticle    ───►  sentiment.py     ───►  Sentiment scores
EDGAR Form 4         ───►  insider_trades   ───►  InsiderTrade   ───►  anomaly_detector ───►  Alerts
EDGAR 13F-HR         ───►  institutional    ───►  Holdings       ───►  thesis_matcher   ───►  ThesisMatch
Finnhub              ───►  earnings_cal     ───►  EarningsEvent  ───►  risk_metrics     ───►  Beta/Sharpe/VaR
FMP/DDG scrape       ───►  transcripts      ───►  Transcript     ───►  earnings_analyze ───►  Tone/Sentiment
FRED                 ───►  macro_data       ───►  MacroIndicator ───►  sector_rotation  ───►  Regime detection
                                                                       buy_the_dip      ───►  DipScore (8-dim)
                                                                            │
                                                                            ▼
                                                                    Daily Briefing (11 sections)
                                                                    Alert Engine (7+ rules)
                                                                    Chat System (3 personas, 20+ tools)
```

### Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | Python 3.12, FastAPI, async SQLAlchemy 2.0 | Async-first, type-safe, fast iteration |
| Database | Neon PostgreSQL (serverless) + asyncpg | Free tier, zero-ops, cold-start resilient |
| Task Queue | Celery + Upstash Redis (serverless) | Beat scheduling, 4 dedicated queues, retry logic |
| AI | Claude Sonnet (filings, chat), Haiku Batches (sentiment) | Prompt caching on filings, 50% batch discount on sentiment |
| CLI | Typer | Full pipeline control from terminal |
| Deployment | Docker + Railway (2 services) | `entrypoint.sh` dispatches web vs worker via `PROCESS_TYPE` env var |
| Tests | pytest (327 tests), SQLite in-memory | Fast, no infra dependencies |

### What's Built and Working

**Data Ingestion (6 sources, 8 modules)**
- Price data with 3-tier fallback (yfinance > Alpha Vantage > Polygon)
- SEC EDGAR with token-bucket rate limiting and iXBRL stripping
- Multi-source news with SHA-256 hard dedup + rapidfuzz soft dedup (85% threshold)
- Form 4 insider trades, 13F institutional holdings
- Earnings calendar + transcript scraping
- FRED macro indicators (Fed funds, 10Y, unemployment, CPI)

**Analysis Engine (9 modules)**
- Technical indicators via pandas-ta (SMA/EMA/RSI/MACD/Bollinger/ATR)
- Filing analysis: 8 regex red-flag patterns + Claude Sonnet deep analysis with prompt caching
- Claude Haiku Batches API sentiment scoring (-1.0 to +1.0)
- Anomaly detection: volume Z-scores, price drops, overnight gaps, ATR expansion
- Risk metrics: beta, Sharpe, max drawdown, VaR, volatility, SPY correlation
- Sector rotation via SPDR relative strength + regime detection (risk-on/risk-off)
- Thesis matching: hybrid scoring (50% quant criteria, 50% keyword density in MD&A)
- Earnings transcript sentiment analysis with tone-shift detection
- Peer comparables logic

**Alert System**
- 7+ composable rules (RSI oversold, golden/death cross, strong dip, dip+insider, high-volume move, filing red flag, earnings beat/miss, tone shift)
- 8-dimension buy-the-dip scoring (price drop, vol vs history, fundamental, sentiment, insider, institutional, technical, sector relative)
- Per-type dedup windows (24h-168h) with daily rate limits
- Multi-channel delivery: email, Slack, Discord, ntfy.sh

**Daily Briefing (11 sections)**
- Market overview, watchlist movers, recent alerts, top news, insider activity, technical signals, thesis matches, sector rotation, earnings highlights, macro snapshot, key updates

**Chat System (3 personas, agentic tool-use loop)**
- **The Analyst**: data-driven, cites specifics, 16 tools
- **The Thesis Genius**: contrarian, framework-oriented, irreverent, 12 tools
- **The PM**: captures feature requests as structured user stories, 3 tools
- SSE streaming, persistent conversation history, token budgeting per role

**Auth & Admin**
- JWT + bcrypt, role-based access (admin/member/viewer)
- Web admin panel with user management and password reset
- Daily token budget enforcement for viewers

### 23 ORM Models

The data model covers the full lifecycle:

| Domain | Models | Purpose |
|--------|--------|---------|
| Universe | Ticker | S&P 500 constituents (auto-synced weekly), sector, CIK, thesis tags |
| Price | PriceBar, TechnicalSnapshot | OHLCV daily + computed indicators |
| Filings | Filing, FilingSection, FilingAnalysis, FinancialMetric | SEC docs, parsed sections, Claude analysis, extracted KPIs |
| News | NewsArticle | Multi-source with sentiment scores |
| Insider | InsiderTrade | Form 4 buys/sells/grants |
| Institutional | InstitutionalHolding | 13F quarterly positions + changes |
| Alerts | Alert, DipScore | Rule engine output + 8-dim composite |
| Theses | Thesis, ThesisMatch | Definitions + auto-discovered matches |
| Briefing | DailyBriefing | Generated digests (MD + HTML) |
| Chat | ChatConversation, ChatMessage, FeatureRequest | Multi-turn sessions + PM captures |
| Earnings | EarningsEventDB, EarningsTranscript, EarningsAnalysis | Calendar, transcripts, Claude analysis |
| Macro | MacroIndicator | FRED time-series |
| Auth | User | JWT auth, roles, token budgets |

### Deployment Architecture (Railway)

Two Railway services from the same Dockerfile, dispatched by `entrypoint.sh`:

```
┌─────────────────────────────────────────────────────────────────┐
│  Railway Project: edgefinder                                    │
│                                                                 │
│  ┌─────────────────────┐    ┌─────────────────────────────────┐ │
│  │  edgefinder (web)   │    │  edgefinder-worker              │ │
│  │  PROCESS_TYPE=web   │    │  PROCESS_TYPE=worker            │ │
│  │                     │    │                                 │ │
│  │  uvicorn + FastAPI  │    │  celery worker --beat           │ │
│  │  Port $PORT (8080)  │    │  4 queues, concurrency=4        │ │
│  │  /health endpoint   │    │  Beat scheduler (embedded -B)   │ │
│  └────────┬────────────┘    └────────┬────────────────────────┘ │
│           │                          │                          │
│           └──────────┬───────────────┘                          │
│                      │                                          │
│         ┌────────────▼────────────┐                             │
│         │  Neon PostgreSQL        │  Upstash Redis (rediss://)  │
│         │  24 tables, asyncpg     │  Broker + result backend    │
│         │  NullPool for worker    │  SSL with CERT_NONE         │
│         └─────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

Key deployment details:
- **Single Dockerfile** — `entrypoint.sh` reads `PROCESS_TYPE` to run either uvicorn or celery
- **NullPool on worker** — Celery's `asyncio.run()` creates/closes event loops per task; a connection pool bound to one loop goes stale in the next. `NullPool` creates a fresh connection each time, avoiding the "Event loop is closed" error.
- **Beat embedded** (`-B` flag) — single worker instance, so no risk of duplicate scheduling
- Deploy both: `make railway-deploy-all`

### Scheduler Architecture (Celery Beat)

Four dedicated queues, all served by a single worker process in production:

| Queue | Concurrency | Key Tasks |
|-------|------------|-----------|
| ingestion | 4 | Prices (15min), filings (2h), news (30min), insider (2x/day), institutional (weekly), macro (daily) |
| analysis | 2 | Technicals (post-price), filing analysis (3h), sentiment (hourly), anomalies (post-price), thesis matching (daily) |
| alerts | 2 | Alert rules (15min market hours), dip scoring (30min), snoozed alert checks (5min) |
| delivery | 1 | Daily briefing (7AM UTC), weekly digest (Sunday 8PM UTC) |

Resilience: `acks_late=True`, `prefetch_multiplier=1`, Neon keepalive every 3 min during market hours, tenacity retry on cold starts. Beat schedule entries use `"options": {"queue": "..."}` (not top-level `"queue"` — Celery rejects that).

---

## The Intent

EdgeFinder exists at the intersection of three goals:

**1. Build a genuine edge-finding tool.** Not a toy. A system that ingests the same data institutional analysts use (EDGAR filings, insider trades, 13F flows, earnings transcripts, macro indicators) and applies systematic analysis to surface what a solo investor would otherwise miss. The alert engine and thesis matcher are designed to find signals, not just display data.

**2. Keep ML and data engineering skills sharp.** Every module is a mini-project: time-series anomaly detection, NLP sentiment scoring, quantitative factor models, hybrid ML+heuristic scoring. The codebase is structured so new analysis modules slot in cleanly — each one is an opportunity to implement a paper or test a technique.

**3. Go deep on agentic AI patterns.** The chat system isn't a chatbot wrapper. It's a genuine agentic loop: tool selection, multi-turn reasoning, persona routing, streaming output, persistent memory. Each persona has distinct behavior and tool access. This is the foundation for much more ambitious agent architectures.

---

## Where It's Going: The Simulation & Self-Testing Thesis Engine

This is where the vision gets interesting. The current thesis matcher scores tickers against static criteria defined in `theses.yaml`. The next evolution makes theses *alive* — generated, tested, tracked, and killed.

### Thesis Lifecycle Engine (Next Major Feature)

```
Thesis Generation          Backtesting              Live Tracking            Feedback Loop
──────────────            ──────────              ─────────────            ─────────────
Signal detection    ───►  Historical sim     ───►  Paper portfolio   ───►  Performance vs
Macro correlation         Walk-forward test        Position sizing         benchmark
Earnings patterns         Sharpe/drawdown          Entry/exit rules  ───►  Thesis mutation
Filing anomalies          Win rate / expectancy    Stop losses             or retirement
Sector rotation     ───►  Monte Carlo              Risk limits       ───►  Weight adjustment
                          stress testing
```

**Phase 1: Thesis Generator**
- Claude analyzes converging signals (filing red flags + insider buying + sector rotation shift + macro inflection) and proposes structured theses
- Each thesis gets: entry criteria, exit criteria, time horizon, expected catalysts, risk factors, position sizing rules
- The Thesis Genius persona becomes the primary interface for this — it already has the tools and temperament

**Phase 2: Backtesting Sandbox**
- Walk-forward simulation against historical price/filing/news data already in the DB
- Vectorized backtesting (vectorbt or custom pandas engine) for speed
- Metrics: Sharpe, Sortino, max drawdown, win rate, profit factor, expectancy
- Monte Carlo permutation testing to separate skill from luck
- Survivorship-bias-aware (track delisted tickers)

**Phase 3: Paper Portfolio Tracker**
- Thesis-linked paper positions with real entry/exit logging
- Portfolio-level risk: correlation matrix, sector concentration, beta exposure
- Daily P&L attribution (which thesis is driving returns?)
- Automatic stop-loss and take-profit execution against live prices

**Phase 4: Self-Testing Loop**
- Theses that underperform get automatically flagged for review
- The system proposes mutations: tighten criteria, shift sectors, adjust time horizon
- Historical hit rate feeds back into the thesis matcher's confidence scoring
- Dead theses get archived with post-mortem analysis

### Why This Matters for Learning

This architecture forces you to work with:

| Skill | How It Gets Exercised |
|-------|----------------------|
| **ML fundamentals** | Feature engineering for thesis scoring, walk-forward validation, overfitting detection, Monte Carlo methods |
| **Time-series analysis** | Regime detection, mean reversion vs momentum, volatility clustering, cointegration |
| **Reinforcement learning** | Thesis mutation as a bandit problem — explore new theses vs exploit proven ones |
| **Agent design** | Multi-agent collaboration (Analyst generates data, Thesis Genius proposes, a Backtester agent validates, PM tracks) |
| **Bayesian reasoning** | Prior beliefs (thesis criteria) updated by evidence (backtest results, live performance) |
| **Risk management** | Kelly criterion, portfolio optimization, tail risk, correlation breakdown during stress |

---

## Growth Vectors: How This Becomes a Serious Market Intelligence System

### Near-Term (3-6 months)

**Options Flow Analysis**
- IV surface modeling, put/call skew, unusual options activity detection
- Delta hedging simulation (excellent ML exercise: predict realized vs implied vol)
- Data sources: CBOE delayed data, Polygon options chain

**Institutional Flow Tracking**
- 13F diff engine: quarter-over-quarter position changes across top 100 funds
- Crowding detection: when too many institutions pile into the same names
- Smart money vs dumb money divergence signals

**Earnings Prediction Model**
- Features: historical beat/miss patterns, management tone trajectory, sector comps, macro regime
- Target: binary (beat/miss) or continuous (surprise magnitude)
- Classic supervised ML problem with rich feature set already in the DB

**Correlation Regime Detection**
- Rolling correlation matrices across sectors
- Detect when correlations spike (risk-off) or diverge (sector rotation opportunity)
- Hidden Markov Models or changepoint detection (great ML exercise)

### Medium-Term (6-12 months)

**Multi-Agent Simulation**
- Competing thesis agents with different strategies (momentum, value, event-driven, macro)
- Each agent manages a paper portfolio independently
- Tournament-style evaluation: which strategy works in which regime?
- Meta-agent that allocates between strategies based on detected regime

**Natural Language Strategy Specification**
- Describe a strategy in plain English: "Buy oversold large-cap tech with insider buying during Fed easing cycles"
- System decomposes into quantitative rules, backtests, and reports
- The Thesis Genius persona is the natural interface for this

**Alternative Data Integration**
- Satellite imagery (parking lot analysis, construction activity)
- Web scraping (job postings as growth signal, app download trends)
- Social sentiment (Reddit, StockTwits, Twitter — carefully, noise is extreme)
- Patent filings (innovation pipeline proxy)

**Graph-Based Signal Propagation**
- Supply chain graphs (a disruption at Company A propagates to Company B)
- Ownership graphs (institutional overlap, board interlocks)
- Sector contagion modeling

### Long-Term (12+ months)

**Autonomous Research Agent**
- Given a ticker, autonomously: pull filings, read transcripts, check insider activity, run technicals, compare to peers, assess macro backdrop, generate a full research report
- Multi-step reasoning with tool use — the chat engine already supports this pattern
- Citation-backed conclusions (every claim links to specific data)

**Strategy Marketplace (Internal)**
- Version-controlled strategy definitions
- A/B testing framework for strategy variants
- Performance attribution dashboard
- Strategy correlation matrix (avoid running redundant strategies)

**Real-Time Event Processing**
- Move from batch (Celery Beat) to streaming (Kafka/Redpanda or NATS)
- Sub-minute reaction to 8-K filings, insider trade disclosures, earnings releases
- Event-driven thesis activation (a specific catalyst fires, triggering entry logic)

---

## Initial Impressions: What's Strong, What to Watch

### Strengths

**The data foundation is solid.** 23 models covering the full spectrum from raw prices to analyzed filings to scored theses. This isn't a prototype — it's a production data model with proper dedup, indexing, and relationships. Adding new analysis modules is straightforward because the data layer is well-structured.

**The ingestion pipeline is resilient.** Token-bucket rate limiting for EDGAR, 3-tier fallback for prices, hard+soft news dedup, Neon cold-start handling with tenacity retries. These are the kinds of details that separate a weekend project from something that runs reliably.

**The chat system is a real agentic architecture.** Tool-use loops, persona routing, streaming SSE, persistent memory, token budgeting. This isn't a wrapper around an API call — it's a foundation for serious agent work. The 20+ tools mean the agents can actually do useful things, not just talk.

**The thesis system is well-designed for extension.** `theses.yaml` with keyword + quantitative criteria + sector gates is a clean abstraction. The matcher already does hybrid scoring. Adding backtesting, generation, and self-testing is an evolution, not a rewrite.

**Test coverage (327 tests) means you can move fast.** Refactoring analysis modules, adding new ingestion sources, changing scoring logic — all with confidence.

### Watch Points

**Celery + asyncio boundary.** Each task creates its own event loop via `asyncio.run()`. This required `NullPool` on the worker (module-level connection pools go stale across event loop boundaries). The pattern works reliably now, but as tasks get more complex (multi-step agent simulations), consider whether a native async task runner (like arq or taskiq) would reduce overhead.

**Free-tier ceiling.** Neon, Upstash, Finnhub, NewsAPI, FMP — all free tiers. This is smart for development, but simulation workloads (backtesting across 500 tickers x 5 years x multiple theses) will hit limits fast. Plan the upgrade path — self-hosted Postgres and Redis are cheap on a VPS.

**Backtest fidelity.** When you build the simulation engine, look-ahead bias and survivorship bias are the silent killers. The data model tracks `adj_close` (good for splits/dividends) but you'll also need point-in-time filing data (what was knowable on date X?) to avoid leaking future information into backtests.

**Agent cost management.** Claude Sonnet for chat is powerful but expensive at scale. As you add autonomous research agents running multi-step investigations, implement a cost budgeting layer beyond just token counts — track cost-per-insight, and route simpler queries to Haiku.

---

## Architecture Principles (Implicit in the Codebase)

1. **Ingest raw, analyze later.** Raw data goes into the DB first. Analysis is a separate pass. This means you can re-run analysis with new algorithms without re-fetching data.

2. **Dedup everything.** SHA-256 content hashes on filings and news. Accession number uniqueness on EDGAR. Dedup windows on alerts. The system trusts nothing upstream.

3. **Graceful degradation.** Missing API keys? Modules skip gracefully. Neon paused? Retry with backoff. Finnhub rate-limited? Fall back to RSS. No news for a ticker? Briefing section renders empty, not broken.

4. **Personas over features.** The chat system doesn't expose raw tools — it wraps them in personas with distinct analytical personalities. This is better UX and better agent design (constrained tool access per persona reduces hallucination).

5. **YAML-driven configuration.** Tickers and theses are YAML, not code. Adding a new thesis or watchlist ticker is a config change, not a deploy.

---

## File Map (Quick Reference)

| Path | What It Does |
|------|-------------|
| `config/settings.py` | Pydantic settings, single source of truth for all config |
| `config/tickers.yaml` | Universe definition (S&P 500 + custom + watchlist) |
| `config/theses.yaml` | 6 investment thesis definitions with criteria |
| `core/models.py` | 23 SQLAlchemy ORM models |
| `core/database.py` | Async engine, session factory, Neon resilience |
| `core/security.py` | JWT + bcrypt |
| `ingestion/*.py` | 8 data source modules |
| `analysis/*.py` | 9 analysis modules |
| `alerts/alert_engine.py` | 7+ composable alert rules |
| `alerts/buy_the_dip.py` | 8-dimension dip scoring |
| `alerts/delivery.py` | Email/Slack/Discord/ntfy |
| `chat/engine.py` | Agentic loop: prompt > stream > tool_use > persist |
| `chat/personas.py` | Analyst, Thesis Genius, PM definitions |
| `chat/tools.py` | 20+ chat tool implementations |
| `scheduler/tasks.py` | 25 Celery tasks + Beat schedule (4 queues, 23 scheduled jobs) |
| `scheduler/orchestrator.py` | Pipeline DAGs (EOD chain, weekly maintenance) |
| `daily_briefing.py` | 11-section briefing generator |
| `cli.py` | Typer CLI (init, ticker, ingest, run, serve) |
| `entrypoint.sh` | Docker entrypoint: dispatches web/worker/beat via `PROCESS_TYPE` |
| `api/app.py` | FastAPI factory, routes, middleware |
| `api/chat_routes.py` | SSE streaming chat endpoint |
| `api/dependencies.py` | JWT auth, role-based access |

---

## Summary

EdgeFinder is already a capable market intelligence system with a solid data pipeline, multi-source ingestion, Claude-powered analysis, and an agentic chat interface. The architecture is clean enough that the next evolution — self-testing thesis generation with simulation capabilities — is a natural extension, not a rewrite.

The learning surface area is massive: every new feature touches ML fundamentals (backtesting, feature engineering, regime detection), agent design (multi-agent simulation, autonomous research), and market microstructure (options flow, institutional positioning, event-driven strategies). The existing 327-test suite and modular architecture mean you can experiment aggressively without breaking what works.

The system grows from "intelligence briefing tool" to "thesis generation and validation engine" to "multi-agent strategy tournament" — each stage building on the data and infrastructure already in place.
