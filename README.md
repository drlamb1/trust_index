# EdgeFinder — Market Intelligence & Simulation Lab

SEC filings, news sentiment, price anomalies, stochastic vol modeling, and a self-improving thesis simulation engine — all running on play money against live market data.

**Two environments:** local (venv + Docker Redis) and Railway (3 services, fully managed). Pick your mode and stay in it.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, async SQLAlchemy 2.0 |
| Database | Neon PostgreSQL (serverless) |
| Queue | Celery + Upstash Redis — 5 queues, 34 tasks |
| AI | Claude Sonnet (filings, chat, theses) · Haiku (sentiment, routing) |
| Simulation | Heston stochastic vol, walk-forward backtesting, paper portfolio |
| Deploy | Docker + Railway (web · worker · simulation-worker) |

---

## Prerequisites

- Python 3.12, Docker, `make`
- [Neon](https://console.neon.tech) — free PostgreSQL (or any `postgresql+asyncpg://` URL)
- [Upstash](https://console.upstash.com) — free Redis (or local Docker Redis)
- API keys: `ANTHROPIC_API_KEY` (required for chat/analysis), others optional

---

## Local Development

Everything goes through `make`. The venv runs the app; Docker runs Redis only.

### First time setup

```bash
git clone https://github.com/drlamb1/trust_index.git
cd trust_index

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — required: DATABASE_URL, REDIS_URL, EDGAR_USER_AGENT
# For chat/analysis also set: ANTHROPIC_API_KEY

make init       # starts Redis, runs Alembic migrations, seeds tickers + theses
make status     # verify DB, Redis, and ticker count look right
```

### Daily workflow

```bash
# Terminal 1 — web dashboard (http://localhost:8050)
make serve

# Terminal 2 — Celery worker + beat scheduler (all 5 queues)
make worker

# Backfill data (one-time, run while worker is up)
make ingest-prices        # price history (365 days default)
make ingest-filings       # SEC 10-K/10-Q filings
make ingest-news          # RSS + Finnhub + NewsAPI
make ingest-macro         # FRED economic indicators
make ingest-insider       # Form 4 insider trades
make ingest-transcripts   # earnings call transcripts
```

The beat scheduler handles everything on a recurring basis once the worker is running. The manual ingest commands are for initial backfill or forcing a refresh.

### Full Docker stack (optional — mirrors Railway locally)

If you want to test the containerized build before pushing:

```bash
make docker-build   # build image
make docker-up      # web + worker + simulation-worker + Redis
make docker-down    # tear it all down
```

---

## Railway (Deployed)

Three Railway services, all from the same Dockerfile, dispatched by `PROCESS_TYPE` env var.

| Service | `PROCESS_TYPE` | Purpose |
|---|---|---|
| `edgefinder` | `web` | FastAPI dashboard + chat API |
| `edgefinder-worker` | `worker` | Celery worker + beat (all queues) |
| `edgefinder-simulation` | `simulation-worker` | Dedicated simulation queue |

### First deploy

```bash
# 1. Set env vars on each Railway service (copy from your .env)
#    All three services need DATABASE_URL, REDIS_URL, ANTHROPIC_API_KEY, etc.
#    PROCESS_TYPE is set per-service as above

# 2. Run migrations against Neon (runs from your local venv via Railway tunnel)
make railway-migrate

# 3. Create an admin user
make railway-admin

# 4. Deploy all three services
make railway-deploy-all-3
```

### Routine deploys

```bash
# After code changes — deploy the service(s) that changed
make railway-deploy              # web only
make railway-deploy-worker       # worker only
make railway-deploy-simulation   # simulation worker only
make railway-deploy-all-3        # all three

# After schema changes (new Alembic migration)
make railway-migrate             # always before deploying new code with model changes

# Logs
make railway-logs                # web service
make railway-logs-worker         # worker service
```

### Railway env var notes

- `DATABASE_URL` — Neon `postgresql+asyncpg://...` connection string (same on all 3 services)
- `REDIS_URL` — Upstash `rediss://...` (SSL, same on all 3)
- `PROCESS_TYPE` — unique per service (see table above)
- `PORT` — Railway injects this automatically on the web service; don't set it manually
- `CORS_ORIGINS` — comma-separated, e.g. `https://edgefinder.up.railway.app`

---

## Make Reference

```
make help             # full list with descriptions

# Local
make init             # first-time setup: Redis + migrate + seed
make migrate          # run Alembic migrations only
make serve            # web dashboard on :8050
make worker           # Celery worker + beat (all queues)
make simulation-worker # simulation queue only (separate terminal)
make status           # health check: DB, Redis, tickers
make create-admin     # create admin user interactively

# Data (manual backfill / refresh)
make ingest-prices    # DAYS=365 (override: make ingest-prices DAYS=90)
make ingest-filings
make ingest-news
make ingest-macro
make ingest-insider
make ingest-transcripts
make ticker-list

# Docker
make docker-up        # full stack containerized
make docker-down

# Tests
make test             # all 368 tests
make test-unit        # unit tests only (fast, no I/O)

# Railway
make railway-migrate
make railway-admin
make railway-deploy
make railway-deploy-worker
make railway-deploy-simulation
make railway-deploy-all-3
make railway-logs
make railway-logs-worker
```

---

## Tests

SQLite in-memory — no Neon, Redis, or API keys required.

```bash
make test             # 368 tests, ~20s
make test-unit        # unit tests only, ~15s
```

What's covered: price ingestion mocks, SEC EDGAR parsing, news dedup, sentiment scoring, anomaly detection, risk metrics, sector rotation, technical indicators, earnings pipeline, Black-Scholes (put-call parity, Greeks, IV round-trip), Heston (characteristic function, QE Monte Carlo paths, calibration, Feller condition).

---

## Project Structure

```
├── api/                 FastAPI app, chat routes, simulation dashboard
│   ├── app.py             main FastAPI factory
│   ├── chat_routes.py     SSE streaming chat endpoint
│   ├── simulation_routes.py  simulation JSON API + SSE feed
│   └── simulation_page.py    simulation dashboard HTML
├── chat/                Agent chat system
│   ├── engine.py          agentic loop (tool-use, streaming, persona routing)
│   ├── personas.py        8 personas: Analyst, Thesis Genius, PM,
│   │                        Thesis Lord, Vol Surface Slayer, Heston Calibrator,
│   │                        Deep Hedge Alchemist, Post-Mortem Priest
│   ├── tools.py           23+ tool implementations
│   └── router.py          4-tier routing (prefix → keyword → Haiku → default)
├── simulation/          Stochastic vol + thesis simulation engine
│   ├── black_scholes.py   BSM baseline: pricing, Greeks, IV solver
│   ├── heston.py          Heston model: char function, calibration, QE Monte Carlo
│   ├── vol_surface.py     IV surface: SVI fitting, Dupire local vol, arb detection
│   ├── backtester.py      walk-forward backtest + Monte Carlo permutation test
│   ├── paper_portfolio.py paper position manager, stop-loss, MTM
│   ├── thesis_generator.py Claude-powered thesis generation from signals
│   ├── deep_hedging.py    Buehler et al. deep hedging env (CVaR, policy stub)
│   └── memory.py          agent long-term memory: consolidation, recall, injection
├── ingestion/           Data source modules
│   ├── price_data.py      yfinance → Alpha Vantage → Polygon fallback
│   ├── sec_edgar.py       EDGAR client, token-bucket rate limiting
│   ├── news_feed.py       RSS + Finnhub + NewsAPI, SHA-256 + rapidfuzz dedup
│   ├── insider_trades.py  Form 4 parser
│   ├── institutional.py   13F-HR institutional holdings
│   ├── earnings_calendar.py Finnhub earnings calendar
│   ├── transcripts.py     Motley Fool + FMP transcript scraping
│   ├── macro_data.py      FRED economic indicators
│   └── options_data.py    Polygon + yfinance options chain
├── analysis/            Analysis modules
│   ├── technicals.py      pandas-ta: SMA, EMA, RSI, MACD, Bollinger, ATR
│   ├── filing_analyzer.py 8 regex red-flags + Claude Sonnet deep analysis
│   ├── sentiment.py       Claude Haiku Batches API (-1.0 to +1.0)
│   ├── anomaly_detector.py Z-score volume, price drops, overnight gaps, ATR
│   ├── risk_metrics.py    Sharpe, Sortino, max drawdown, VaR, beta
│   ├── sector_rotation.py SPDR ETF relative strength, regime detection
│   ├── thesis_matcher.py  hybrid scoring: 50% quant criteria + 50% keyword
│   └── earnings_analyzer.py transcript tone, guidance sentiment, tone-shift
├── alerts/              Alert rule engine
│   ├── alert_engine.py    9 composable rules, dedup windows, rate limits
│   └── buy_the_dip.py     8-dimension dip scoring (price, fundamental, etc.)
├── scheduler/           Celery tasks + Beat schedule
│   ├── tasks.py           34 tasks, 5 queues, 31 Beat schedule entries
│   └── orchestrator.py    pipeline DAGs (EOD chain, weekly maintenance)
├── core/
│   ├── models.py          33 SQLAlchemy ORM models
│   ├── database.py        async engine, NullPool for workers, retry logic
│   └── security.py        JWT + bcrypt
├── config/
│   ├── settings.py        Pydantic BaseSettings (single source of truth)
│   ├── tickers.yaml       universe definition (S&P 500 + watchlist)
│   └── theses.yaml        6 investment thesis definitions
├── tests/               368 tests (SQLite in-memory, no live services)
├── alembic/             DB migrations
├── cli.py               Typer CLI
├── daily_briefing.py    11-section briefing generator
├── Dockerfile
├── docker-compose.yml   web + worker + simulation-worker + Redis
├── entrypoint.sh        PROCESS_TYPE dispatch
└── Makefile             all dev and deploy commands
```

---

## Architecture Notes

**NullPool on workers** — Celery tasks call `asyncio.run()` per task, creating and closing event loops. A module-level connection pool bound to one event loop becomes invalid in the next. `NullPool` creates a fresh connection per task, avoiding stale-loop errors. Applied to `PROCESS_TYPE` values: `worker`, `simulation-worker`, `beat`.

**Beat embedded** — worker service runs `-B` flag (beat embedded). Single instance means no duplicate scheduling risk. Fine for this scale.

**5 Celery queues** — ingestion (4 workers), analysis (2), alerts (2), delivery (1), simulation (2). Each queue has different concurrency tuned to its workload. The simulation queue handles heavy compute (Heston calibration, Monte Carlo paths, backtesting).

**Play money only** — all simulation P&L is simulated. Explicit disclaimers in every UI surface, API response, and log line. `DISCLAIMER: SIMULATED PLAY-MONEY` appears in every SimulationLog entry.

**Claude cost tiers** — Haiku for sentiment, routing, memory consolidation. Sonnet for filing analysis, chat, thesis generation. Prompt caching on long system prompts. Hash-gating to skip re-analysis of unchanged content.

---

## Environment Variables

See [.env.example](.env.example) for the full list.

**Required:**
- `DATABASE_URL` — `postgresql+asyncpg://...` (Neon connection string)
- `REDIS_URL` — `redis://localhost:6379` or `rediss://...` for Upstash
- `EDGAR_USER_AGENT` — `AppName/1.0 youremail@example.com` (SEC policy)
- `SECRET_KEY` — generate with `openssl rand -hex 32`

**Strongly recommended:**
- `ANTHROPIC_API_KEY` — enables all Claude-powered features (chat, analysis, theses)

**Optional:**
- `FINNHUB_API_KEY` — company news + earnings calendar
- `NEWS_API_KEY` — NewsAPI aggregation
- `ALPHA_VANTAGE_API_KEY` — price data fallback
- `POLYGON_API_KEY` — options chain data (needed for vol surface / Heston calibration)
- `FRED_API_KEY` — macro indicators
- `FMP_API_KEY` — earnings transcripts
- SMTP, Slack, Discord, ntfy — alert delivery
