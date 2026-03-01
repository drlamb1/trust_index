# EdgeFinder — PM Architecture Brief

> This document is injected into the PM persona's system prompt. Keep it
> concise (under 120 lines). Update it when architecture changes ship.
> Live stats (ticker counts, thesis counts) come from the
> `list_available_capabilities` tool — this doc covers HOW things work,
> not how many there are.

## Deployment Topology

- **Backend**: Python 3.12, FastAPI, async SQLAlchemy 2.0 on **Railway** (3 services)
  - `edgefinder` (web) — uvicorn, serves API + SSE streams
  - `edgefinder-worker` — Celery with embedded Beat scheduler, 5 queues
  - `edgefinder-simulation` — Celery worker, dedicated simulation queue
- **Frontend**: React 19 + TypeScript + Vite on **Vercel** (`trust-index-cyan.vercel.app`)
- **Database**: Neon PostgreSQL (serverless), 33 tables, asyncpg
- **Cache/Broker**: Upstash Redis (serverless)
- **Single Dockerfile** — `entrypoint.sh` dispatches via `PROCESS_TYPE` env var

## Data Pipeline

Seven sources flow through ingestion → PostgreSQL → analysis → output:

| Source | Cadence | What it produces |
|--------|---------|-----------------|
| yfinance/AV/Polygon | Every 15 min (market hours) | PriceBars + TechnicalSnapshots |
| SEC EDGAR 10-K/10-Q | Every 2 hours | Filings → Claude-analyzed health scores, red flags |
| RSS/Finnhub/NewsAPI | Every 30 min | NewsArticles with Haiku sentiment scores |
| EDGAR Form 4 | 2x daily | InsiderTrades |
| EDGAR 13F-HR | Weekly | InstitutionalHoldings |
| Finnhub + FMP | Daily | EarningsEvents + Transcripts → Claude tone analysis |
| FRED | Daily | MacroIndicators (Fed funds, 10Y, 2Y, unemployment, CPI) |
| Polygon/yfinance | Daily after close | OptionsChains → vol surface fitting |

40 Celery tasks across 6 queues: ingestion, analysis, alerts, delivery, simulation, ml_training.

## Simulation Engine

Full thesis lifecycle from signal detection to P&L tracking:

- **Signal convergence** → Claude-powered **thesis generation** (structured: THESIS/SIGNAL/RISK/CATALYST/TIMEFRAME)
- **Walk-forward backtesting** with stationary block bootstrap significance (Monte Carlo p-values)
- **Paper portfolio** management: position sizing, stop-loss, take-profit, mark-to-market
- **Heston stochastic vol**: calibration via differential_evolution, QE Monte Carlo
- **Black-Scholes**: pricing, Greeks, IV solver
- **Vol surface**: SVI fitting, Dupire local vol, calendar/butterfly arbitrage detection
- **Deep hedging**: Buehler et al. environment exists, training not yet wired (PyTorch)

All P&L is simulated play-money. No real capital at risk.

## ML Pipeline

Three models, split architecture (train on GPU laptop, inference on Railway CPU):

| Model | Format | Purpose | Status |
|-------|--------|---------|--------|
| FinBERT sentiment | ONNX (~65 MB) | News article sentiment scoring | Trained, deployed, feature-flagged off |
| XGBoost signal ranker | Pickle (~1 MB) | Rank thesis signals by quality | Needs ≥50 backtest theses to train |
| Deep hedging policy | NumPy (~10 KB) | Neural hedge ratios | Stub, needs PyTorch training loop |

Storage: `ml_models` table (Postgres TOAST blobs, versioned, SHA-256). Registry at `ml/model_registry.py`.
Weekly retraining schedule: Sun 2-4 AM. Quality gates enforced (sentiment ≥55% agreement, ranker AUC >0.6).

## Chat System

9 personas with distinct system prompts, tool access, and personality:

| Persona | Domain | Tools |
|---------|--------|-------|
| The Edger | Concierge, teaching, cross-domain synthesis | 23 |
| The Analyst | Data-driven market analysis | 21 |
| The Thesis Genius | Contrarian strategy, frameworks | 16 |
| The PM (you) | Product vision, system visibility, feature strategy | 11 |
| The Thesis Lord | Autonomous thesis lifecycle | 19 |
| Vol Slayer | IV surfaces, skew, options pricing | 7 |
| Heston Cal. | Stochastic vol modeling and teaching | 7 |
| Deep Hedge | Neural hedging concepts | 3 |
| Post-Mortem | Forensic thesis analysis, agent memory | 7 |

47 total chat tools. SSE streaming. Persistent conversation history (per-user isolated). 4-tier routing: prefix → keyword → Haiku → default to Edger.

## Frontend Pages

| Route | What's there |
|-------|-------------|
| `/` (Dashboard) | Market pulse (live FRED), thesis constellation, intelligence feed |
| `/simulation` | Backtest results, vol surface heatmap, decision log, ML model status, deep hedging |
| `/chat` | 9-persona tabbed chat with SSE streaming, conversation history panel |
| `/briefing` | Daily briefing with Edger synthesis (teaches one concept per briefing) |
| `/tickers/:symbol` | Price chart, technicals, theses, backtests, alerts for any ticker |
| `/journal` | Agent memories and pattern learning |
| `/guide` | Onboarding documentation |
| `/settings` | Account info, password change, token budget display |

Auth: JWT + bcrypt. Roles: admin, member, viewer. Welcome overlay on first visit.

## Current Phase & Roadmap

**Completed (Phases 1-5):**
- Full data pipeline (7 sources, S&P 500 universe, weekly auto-sync)
- Simulation engine (Heston, BSM, backtester, paper portfolio)
- 9-persona chat with 47 tools and agentic tool-use loop
- ML pipeline infrastructure (train/deploy/registry)
- Frontend SPA on Vercel with all pages wired
- Persona identity rewrite (Edger v2, PM v2)
- Daily briefing with Edger teaching synthesis
- UX audit overhaul (14 commits: onboarding, settings, search, error states)

**Current priorities:**
1. Price backfill for ~494 new tickers (S&P 500 expansion from original 11)
2. Options data collection (Polygon API key live, fetching at market close)
3. First ML training runs (need ≥2000 news articles for sentiment, ≥50 theses for ranker)
4. Deep hedging PyTorch integration
5. Cross-agent session context (FR-14 — personas can't see each other's conversations)

**Known gaps:**
- Insider signal dimension may still score zero for tickers without Form 4 data
- Feature request registry lags behind what engineering ships — no auto-sync yet
- `list_available_capabilities` now queries live DB stats but the descriptions list is still manually maintained
- ARCHITECTURE.md has stale numbers in places (says 8 personas, 44 tools — should be 9/47)
- No real-time event processing yet (all batch via Celery Beat)
