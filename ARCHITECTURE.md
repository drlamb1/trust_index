# EdgeFinder — Architecture, Intent & Vision

## What This Is

EdgeFinder is a Python market intelligence platform deployed on Railway. It ingests SEC filings, tracks news sentiment, detects price/volume anomalies, scores investment theses, runs stochastic volatility models, backtests thesis strategies, manages a paper portfolio, and delivers daily intelligence briefings. It combines quantitative signals with Claude-powered qualitative analysis and exposes everything through an agentic multi-persona chat system with 8 specialized personas. Targeting the full S&P 500 universe as a baseline, with active weekly auto-sync.

It's also a personal learning lab — a system designed to sharpen ML intuition, deepen understanding of market microstructure, and build real muscle with agentic AI patterns, all against live market data.

---

## Current State (Phases 1-5 Complete, Simulation Engine Live)

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
Polygon/yfinance     ───►  options_data     ───►  OptionsChain   ───►  buy_the_dip      ───►  DipScore (8-dim)
                                                                       vol_surface       ───►  SVI/Local vol
                                                                       heston            ───►  Stoch vol params
                                                                            │
                                                                            ▼
                                                                    Daily Briefing (11 sections)
                                                                    Alert Engine (7+ rules)
                                                                    Chat System (8 personas, 44 tools)
                                                                    Simulation Engine (backtest, paper portfolio)
```

### Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | Python 3.12, FastAPI, async SQLAlchemy 2.0 | Async-first, type-safe, fast iteration |
| Database | Neon PostgreSQL (serverless) + asyncpg | Free tier, zero-ops, cold-start resilient |
| Task Queue | Celery + Upstash Redis (serverless) | Beat scheduling, 5 dedicated queues, retry logic |
| AI | Claude Sonnet (filings, chat, theses), Haiku (sentiment, routing) | Prompt caching on filings, batch discount on sentiment |
| Simulation | Black-Scholes, Heston stoch vol, walk-forward backtesting, paper portfolio | Full thesis lifecycle from signal to P&L |
| CLI | Typer | Full pipeline control from terminal |
| Frontend | React 19, TypeScript, Vite, Zustand | SPA with SSE streaming, deployed on Vercel |
| Deployment | Docker + Railway (3 services) | `entrypoint.sh` dispatches web/worker/simulation via `PROCESS_TYPE` |
| Tests | pytest (368 tests), SQLite in-memory | Fast, no infra dependencies |

### What's Built and Working

**Data Ingestion (7 sources, 9 modules)**
- Price data with 3-tier fallback (yfinance > Alpha Vantage > Polygon)
- SEC EDGAR with token-bucket rate limiting and iXBRL stripping
- Multi-source news with SHA-256 hard dedup + rapidfuzz soft dedup (85% threshold)
- Form 4 insider trades, 13F institutional holdings
- Earnings calendar + transcript scraping
- FRED macro indicators (Fed funds, 10Y, unemployment, CPI)
- Options chain data (Polygon + yfinance fallback)

**Analysis Engine (9 modules)**
- Technical indicators via pandas-ta (SMA/EMA/RSI/MACD/Bollinger/ATR)
- Filing analysis: 8 regex red-flag patterns + Claude Sonnet deep analysis with prompt caching
- Claude Haiku Batches API sentiment scoring (-1.0 to +1.0)
- Anomaly detection: volume Z-scores, price drops, overnight gaps, ATR expansion
- Risk metrics: beta, Sharpe, Sortino, max drawdown, VaR, volatility, SPY correlation
- Sector rotation via SPDR relative strength + regime detection (risk-on/risk-off)
- Thesis matching: hybrid scoring (50% quant criteria, 50% keyword density in MD&A)
- Earnings transcript sentiment analysis with tone-shift detection
- Peer comparables logic

**Simulation Engine (8 modules)**
- Black-Scholes-Merton: pricing, Greeks, IV solver (Newton-Raphson + bisection fallback)
- Heston stochastic volatility: characteristic function (Lord & Kahl branch cut fix), QE Monte Carlo, calibration via differential_evolution
- Vol surface: SVI fitting, Dupire local vol extraction, calendar/butterfly arbitrage detection
- Walk-forward backtester with stationary block bootstrap significance testing (Politis & Romano 1994)
- Paper portfolio manager: position sizing, stop-loss/take-profit, mark-to-market
- Thesis generator: Claude-powered signal convergence → structured thesis proposals
- Deep hedging: Buehler et al. environment/CVaR loss (stubs — PyTorch not yet integrated)
- Agent memory: consolidation, recall, injection for cross-session learning

**Alert System**
- 7+ composable rules (RSI oversold, golden/death cross, strong dip, dip+insider, high-volume move, filing red flag, earnings beat/miss, tone shift)
- 8-dimension buy-the-dip scoring (price drop, vol vs history, fundamental, sentiment, insider, institutional, technical, sector relative)
- Per-type dedup windows (24h-168h) with daily rate limits
- Multi-channel delivery: email, Slack, Discord, ntfy.sh

**Daily Briefing (11 sections)**
- Market overview, watchlist movers, recent alerts, top news, insider activity, technical signals, thesis matches, sector rotation, earnings highlights, macro snapshot, key updates

**Chat System (8 personas, agentic tool-use loop, 44 tools)**

| Persona | Role | Tools |
|---------|------|-------|
| The Analyst | Data-driven market analysis, cites specifics | 21 |
| The Thesis Genius | Contrarian, framework-oriented, irreverent | 12 |
| The PM | Feature requests as structured user stories | 4 |
| The Thesis Lord | Autonomous thesis lifecycle — generate, backtest, manage, kill | 20 |
| The Vol Surface Slayer (Trogdor) | IV surface interpretation, SVI/Dupire teaching | 7 |
| The Heston Calibrator | Stochastic vol modeling, Monte Carlo, calibration | 7 |
| The Deep Hedge Alchemist | Neural hedging concepts (Buehler et al.) | 3 |
| The Post-Mortem Priest | Forensic thesis analysis, agent memory keeper | 7 |

SSE streaming, persistent conversation history, per-persona tool access, 4-tier routing (prefix → keyword → Haiku → default), token budgeting per role.

**Auth & Admin**
- JWT + bcrypt, role-based access (admin/member/viewer)
- Web admin panel with user management and password reset
- Daily token budget enforcement for viewers

### 33 ORM Models

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
| Options | OptionsChain | Strike/expiry IV data from Polygon |
| Vol Surface | VolSurface | SVI-fitted implied vol surfaces |
| Heston | HestonCalibration | Calibrated stochastic vol parameters |
| Simulation | SimulatedThesis, BacktestRun | Auto-generated theses + backtest results |
| Portfolio | PaperPortfolio, PaperPosition | Play-money positions with P&L tracking |
| Logging | SimulationLog | Agent activity stream (SSE feed source) |
| Deep Hedging | DeepHedgingModel | Neural hedging model checkpoints (stub) |
| Memory | AgentMemory | Cross-session agent learning journal |

### Deployment Architecture (Railway)

Three Railway services from the same Dockerfile, dispatched by `entrypoint.sh`:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  Railway Project: edgefinder                                                     │
│                                                                                  │
│  ┌──────────────────┐  ┌──────────────────────┐  ┌────────────────────────────┐  │
│  │ edgefinder (web)  │  │ edgefinder-worker    │  │ edgefinder-simulation      │  │
│  │ PROCESS_TYPE=web  │  │ PROCESS_TYPE=worker  │  │ PROCESS_TYPE=simulation-   │  │
│  │                   │  │                      │  │              worker        │  │
│  │ uvicorn + FastAPI │  │ celery worker --beat  │  │ celery worker              │  │
│  │ Port $PORT (8080) │  │ 5 queues, concur=4   │  │ simulation queue, concur=2 │  │
│  │ /health endpoint  │  │ Beat scheduler (-B)   │  │                            │  │
│  └───────┬───────────┘  └───────┬──────────────┘  └──────────┬─────────────────┘  │
│          │                      │                             │                    │
│          └──────────────┬───────┴─────────────────────────────┘                    │
│                         │                                                          │
│          ┌──────────────▼──────────────┐                                           │
│          │  Neon PostgreSQL            │  Upstash Redis (rediss://)                 │
│          │  33 tables, asyncpg         │  Broker + result backend                   │
│          │  NullPool for workers       │  SSL with CERT_NONE                        │
│          └─────────────────────────────┘                                            │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Key deployment details:
- **Single Dockerfile** — `entrypoint.sh` reads `PROCESS_TYPE` to run uvicorn, celery worker, or simulation worker
- **NullPool on workers** — Celery's `asyncio.run()` creates/closes event loops per task; a connection pool bound to one loop goes stale in the next. `NullPool` creates a fresh connection each time.
- **Beat embedded** (`-B` flag) — single worker instance, so no risk of duplicate scheduling
- Deploy all 3: `make railway-deploy-all-3`

### Scheduler Architecture (Celery Beat)

Five dedicated queues, all served by worker processes in production:

| Queue | Concurrency | Key Tasks |
|-------|------------|-----------|
| ingestion | 4 | Prices (15min), filings (2h), news (30min), insider (2x/day), institutional (weekly), macro (daily), options (daily) |
| analysis | 2 | Technicals (post-price), filing analysis (3h), sentiment (hourly), anomalies (post-price), thesis matching (daily) |
| alerts | 2 | Alert rules (15min market hours), dip scoring (30min), snoozed alert checks (5min) |
| delivery | 1 | Daily briefing (7AM UTC), weekly digest (Sunday 8PM UTC) |
| simulation | 2 | Heston calibration, vol surface build, thesis generation, paper portfolio MTM, stop checks, lifecycle review, memory consolidation |

34 Celery tasks total, 31 Beat schedule entries.

Resilience: `acks_late=True`, `prefetch_multiplier=1`, Neon keepalive every 3 min during market hours, tenacity retry on cold starts. Beat schedule entries use `"options": {"queue": "..."}` (not top-level `"queue"` — Celery rejects that).

---

## The Intent

EdgeFinder exists at the intersection of three goals:

**1. Build a genuine edge-finding tool.** Not a toy. A system that ingests the same data institutional analysts use (EDGAR filings, insider trades, 13F flows, earnings transcripts, macro indicators) and applies systematic analysis to surface what a solo investor would otherwise miss. The alert engine and thesis matcher are designed to find signals, not just display data.

**2. Keep ML and data engineering skills sharp.** Every module is a mini-project: time-series anomaly detection, NLP sentiment scoring, quantitative factor models, stochastic volatility modeling, Monte Carlo simulation, walk-forward backtesting. The codebase is structured so new analysis modules slot in cleanly — each one is an opportunity to implement a paper or test a technique.

**3. Go deep on agentic AI patterns.** The chat system isn't a chatbot wrapper. It's a genuine agentic loop: tool selection, multi-turn reasoning, persona routing, streaming output, persistent memory. Eight personas with distinct behavior, tool access, and personality. The simulation personas (Thesis Lord, Vol Slayer, Heston Calibrator, Post-Mortem Priest) collaborate on thesis lifecycle management. This is the foundation for much more ambitious agent architectures.

---

## Where It's Going

### Near-Term Growth Vectors

**Deep Hedging Integration**
- Buehler et al. (2019) neural hedging with PyTorch
- CVaR loss optimization, transaction cost modeling
- Compare learned hedge ratios to BSM delta hedging
- Infrastructure stubs exist — needs PyTorch training loop

**Options Flow Analysis**
- Unusual options activity detection from existing OptionsChain data
- Put/call skew tracking, IV term structure monitoring
- Delta hedging simulation (predict realized vs implied vol)

**Institutional Flow Tracking**
- 13F diff engine: quarter-over-quarter position changes across top funds
- Crowding detection: when too many institutions pile into the same names
- Smart money vs dumb money divergence signals

**Multi-Agent Simulation**
- Competing thesis agents with different strategies (momentum, value, event-driven, macro)
- Each agent manages a paper portfolio independently
- Tournament-style evaluation: which strategy works in which regime?
- Meta-agent that allocates between strategies based on detected regime

### Medium-Term

**Autonomous Research Agent**
- Given a ticker, autonomously: pull filings, read transcripts, check insider activity, run technicals, compare to peers, assess macro backdrop, generate a full research report
- Multi-step reasoning with tool use — the chat engine already supports this pattern
- Citation-backed conclusions (every claim links to specific data)

**Real-Time Event Processing**
- Move from batch (Celery Beat) to streaming for latency-sensitive signals
- Sub-minute reaction to 8-K filings, insider trade disclosures, earnings releases
- Event-driven thesis activation (specific catalyst fires, triggering entry logic)

---

## Architecture Principles

1. **Ingest raw, analyze later.** Raw data goes into the DB first. Analysis is a separate pass. This means you can re-run analysis with new algorithms without re-fetching data.

2. **Dedup everything.** SHA-256 content hashes on filings and news. Accession number uniqueness on EDGAR. Dedup windows on alerts. The system trusts nothing upstream.

3. **Graceful degradation.** Missing API keys? Modules skip gracefully. Neon paused? Retry with backoff. Finnhub rate-limited? Fall back to RSS. No news for a ticker? Briefing section renders empty, not broken.

4. **Personas over features.** The chat system doesn't expose raw tools — it wraps them in personas with distinct analytical personalities. Constrained tool access per persona reduces hallucination and improves response quality.

5. **YAML-driven configuration.** Tickers and theses are YAML, not code. Adding a new thesis or watchlist ticker is a config change, not a deploy.

6. **Play money only.** All simulation P&L is simulated. Explicit disclaimers in every UI surface, API response, and log line. No real capital at risk, ever.

---

## File Map (Quick Reference)

| Path | What It Does |
|------|-------------|
| `config/settings.py` | Pydantic settings, single source of truth for all config |
| `config/tickers.yaml` | Universe definition (S&P 500 + custom + watchlist) |
| `config/theses.yaml` | 6 investment thesis definitions with criteria |
| `core/models.py` | 33 SQLAlchemy ORM models |
| `core/database.py` | Async engine, session factory, NullPool for workers, Neon resilience |
| `core/security.py` | JWT + bcrypt |
| `ingestion/*.py` | 9 data source modules |
| `analysis/*.py` | 9 analysis modules |
| `simulation/black_scholes.py` | BSM pricing, Greeks, IV solver |
| `simulation/heston.py` | Heston stoch vol: char function, calibration, QE Monte Carlo |
| `simulation/vol_surface.py` | SVI fitting, Dupire local vol, arb detection |
| `simulation/backtester.py` | Walk-forward backtest + block bootstrap significance test |
| `simulation/paper_portfolio.py` | Paper position manager, stop-loss, MTM |
| `simulation/thesis_generator.py` | Claude-powered thesis generation from signals |
| `simulation/deep_hedging.py` | Buehler et al. deep hedging env (CVaR, policy stub) |
| `simulation/memory.py` | Agent long-term memory: consolidation, recall, injection |
| `alerts/alert_engine.py` | 7+ composable alert rules |
| `alerts/buy_the_dip.py` | 8-dimension dip scoring |
| `alerts/delivery.py` | Email/Slack/Discord/ntfy |
| `chat/engine.py` | Agentic loop: prompt > stream > tool_use > persist |
| `chat/personas.py` | 8 personas with distinct tools and personalities |
| `chat/tools.py` | 44 chat tool implementations |
| `chat/router.py` | 4-tier routing (prefix → keyword → Haiku → default) |
| `scheduler/tasks.py` | 34 Celery tasks + Beat schedule (5 queues, 31 entries) |
| `scheduler/orchestrator.py` | Pipeline DAGs (EOD chain, weekly maintenance) |
| `daily_briefing.py` | 11-section briefing generator |
| `cli.py` | Typer CLI (init, ticker, ingest, run, serve) |
| `entrypoint.sh` | Docker entrypoint: dispatches web/worker/simulation via `PROCESS_TYPE` |
| `api/app.py` | FastAPI factory, routes, middleware |
| `api/chat_routes.py` | SSE streaming chat endpoint |
| `api/simulation_routes.py` | Simulation JSON API + SSE agent feed |
| `api/simulation_page.py` | Simulation dashboard HTML |
| `api/ticker_routes.py` | Ticker data endpoints |
| `api/dependencies.py` | JWT auth, role-based access |

---

## Summary

EdgeFinder is a market intelligence system with a complete data pipeline (9 ingestion sources, 9 analysis modules), a stochastic volatility simulation engine (Black-Scholes, Heston, walk-forward backtesting, paper portfolio), Claude-powered agentic chat (8 personas, 44 tools), and automated thesis lifecycle management. The architecture supports the full loop: signal detection → thesis generation → backtesting → paper trading → post-mortem analysis → agent learning.

The learning surface area is massive: every new feature touches ML fundamentals (stochastic calculus, Monte Carlo methods, feature engineering, regime detection), agent design (multi-agent collaboration, autonomous research), and market microstructure (options flow, institutional positioning, event-driven strategies). The 368-test suite and modular architecture mean you can experiment aggressively without breaking what works.
