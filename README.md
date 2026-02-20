# EdgeFinder — Market Intelligence Platform

A local-first Python application that ingests SEC filings, tracks news sentiment, detects price/volume anomalies, and delivers a daily briefing for a 500+ ticker universe.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, asyncio |
| Database | Neon PostgreSQL (serverless, `asyncpg` + SQLAlchemy 2.0 async) |
| Task Queue | Celery + Upstash Redis (serverless, SSL `rediss://`) |
| Frontend | React SPA (Vite + TypeScript + Tailwind + shadcn/ui) — Phase 5 |
| AI | Claude Sonnet (filing analysis) + Claude Haiku Batches API (bulk sentiment) |
| CLI | Typer |

## Quick Start

### Prerequisites
- Python 3.11+
- [Neon account](https://console.neon.tech) — free PostgreSQL
- [Upstash account](https://console.upstash.com) — free Redis
- Optional: Docker (for local Redis during development)

### Installation (Linux / macOS)

```bash
# 1. Clone the repo
git clone https://github.com/drlamb1/trust_index.git
cd trust_index

# 2. Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — at minimum set DATABASE_URL, REDIS_URL, and EDGAR_USER_AGENT

# 4. Initialize the system (runs Alembic migrations, seeds tickers/theses)
python cli.py init

# 5. Backfill price history (takes ~5-10 min for full S&P 500)
python cli.py ingest prices --days 365

# 6. Fetch SEC filings + run analysis
python cli.py ingest filings --type 10-K --limit 5

# 7. Aggregate news
python cli.py ingest news --days 7
```

### Installation (WSL / Ubuntu)

WSL requires a few extra steps. **Clone into your WSL home directory** — not `/mnt/c/` — to avoid permission and performance issues.

```bash
# 1. Install Python venv support (Ubuntu may not include it)
sudo apt update && sudo apt install python3-full python3-venv -y

# 2. Clone into your WSL home directory (NOT /mnt/c/)
cd ~
git clone https://github.com/drlamb1/trust_index.git
cd trust_index

# 3. Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
nano .env  # set DATABASE_URL, REDIS_URL, EDGAR_USER_AGENT at minimum

# 5. Initialize, ingest, and go
python cli.py init
python cli.py ingest prices --days 365
python cli.py ingest filings --type 10-K --limit 5
python cli.py ingest news --days 7
```

> **WSL gotcha:** Do NOT work from `/mnt/c/Users/.../` — it causes `chmod` errors with git,
> slow I/O, and SQLite locking issues. Always use `~/trust_index`.

### Installation (Windows native)

```bash
# 1. Clone and enter the repo
git clone https://github.com/drlamb1/trust_index.git
cd trust_index

# 2. Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure and run (same steps as above)
copy .env.example .env
# Edit .env, then:
python cli.py init
python cli.py ingest prices --days 365
```

### Running Tests

Tests use SQLite in-memory — no Neon, Redis, or API keys needed.

```bash
# Activate venv first (if not already)
source .venv/bin/activate  # Linux/WSL/macOS
# .venv\Scripts\activate   # Windows

# All tests (327 passing)
pytest tests/ -v

# Unit tests only (fast, no I/O)
pytest tests/unit/ -v

# Skip slow tests
pytest tests/ -m "not slow" -v
```

### Start Workers (optional — for scheduled tasks)

Open separate terminals for each worker type:

```bash
# Ingestion worker (4 concurrent)
celery -A scheduler.tasks worker -Q ingestion -c 4 -n ingestion@%h --loglevel=info

# Analysis worker (2 concurrent)
celery -A scheduler.tasks worker -Q analysis -c 2 -n analysis@%h --loglevel=info

# Alerts worker
celery -A scheduler.tasks worker -Q alerts -c 2 -n alerts@%h --loglevel=info

# Delivery worker
celery -A scheduler.tasks worker -Q delivery -c 1 -n delivery@%h --loglevel=info

# Beat scheduler (ONE instance only!)
celery -A scheduler.tasks beat --loglevel=info
```

### Dashboard (Phase 5)

```bash
python cli.py serve  # http://localhost:8050
```

## CLI Reference

```bash
# System
python cli.py init                                # Initialize DB and seed data
python cli.py status                              # Check DB, Redis, and ticker counts
python cli.py run                                 # Run full daily pipeline

# Tickers
python cli.py ticker add PLTR --thesis ai_defense --notes "Gov AI contracts"
python cli.py ticker remove XYZ                   # Soft deactivate (data preserved)
python cli.py ticker remove XYZ --hard            # Hard delete from DB
python cli.py ticker list
python cli.py ticker list --sector Technology --watchlist

# Ingestion — Prices
python cli.py ingest prices --days 365            # All tickers, 1 year
python cli.py ingest prices NVDA --days 30        # Single ticker

# Ingestion — SEC Filings (Phase 2)
python cli.py ingest filings                      # All active tickers with CIK
python cli.py ingest filings AAPL --type 10-K --limit 5
python cli.py ingest filings --no-analyze         # Skip Claude analysis

# Ingestion — Insider Trades (Phase 2)
python cli.py ingest insider-trades               # All watchlist tickers
python cli.py ingest insider-trades NVDA

# Ingestion — News (Phase 3)
python cli.py ingest news                         # All tickers (RSS + Finnhub + NewsAPI)
python cli.py ingest news AAPL --days 7           # Single ticker
python cli.py ingest news --rss-only              # Skip Finnhub and NewsAPI

# Dashboard
python cli.py serve
```

## Project Structure

```
Trust Index/
├── config/              # Settings (Pydantic), tickers.yaml, theses.yaml
├── core/                # Database, ORM models (15 models), event bus
├── ingestion/           # Price data, SEC EDGAR, insider trades, news, earnings
│   ├── price_data.py    #   yfinance → Alpha Vantage → Polygon fallback
│   ├── sec_edgar.py     #   EDGAR client, token bucket, CIK cache
│   ├── insider_trades.py#   Form 4 parser
│   ├── institutional.py #   13F-HR institutional holdings
│   ├── news_feed.py     #   RSS + Finnhub + NewsAPI aggregation
│   └── earnings_calendar.py  # Finnhub earnings calendar (dataclasses)
├── analysis/            # Technicals, sentiment, anomalies, sector rotation
│   ├── technicals.py    #   pandas-ta indicators, golden cross, Bollinger
│   ├── filing_analyzer.py   # 8 regex red-flag patterns + Claude Sonnet
│   ├── risk_metrics.py  #   Sharpe, max drawdown, beta, VaR
│   ├── sentiment.py     #   Claude Haiku Batches API sentiment scoring
│   ├── anomaly_detector.py  # Z-score volume, price drops, gaps, ATR
│   └── sector_rotation.py   # SPDR ETF relative strength, risk regime
├── alerts/              # Alert engine, buy-the-dip scorer (Phase 4 stubs)
├── scheduler/           # Celery tasks + Beat schedule (4 queues)
├── tests/               # pytest test suite (327 tests)
│   ├── unit/            #   Pure unit tests
│   ├── integration/     #   DB integration tests
│   └── fixtures/        #   Test data fixtures
├── alembic/             # Database migrations
├── cli.py               # Typer CLI
├── daily_briefing.py    # Daily briefing generator (Phase 4)
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
└── docker-compose.yml   # Local Redis for development
```

## Build Phases

- **Phase 1 (Done):** Foundation — DB models, price ingestion (yfinance/AV/Polygon), technicals (pandas-ta), CLI
- **Phase 2 (Done):** Filing Intelligence — SEC EDGAR downloader, 8 regex red-flag patterns + Claude Sonnet analysis, Form 4 insider trades, 13F-HR institutional holdings, risk metrics
- **Phase 3 (Done):** News & Sentiment — RSS/Finnhub/NewsAPI aggregation, Claude Haiku Batches API sentiment scoring, price/volume anomaly detection, SPDR sector rotation & regime detection, earnings calendar
- **Phase 4:** Alerts & Thesis — Alert engine, buy-the-dip scorer, thesis matcher, daily briefing
- **Phase 5:** Dashboard — FastAPI routes, React SPA, SSE real-time alerts

## Key Design Decisions

1. **Neon free tier** — `pool_pre_ping=True` and `pool_recycle=300` handle cold starts; keepalive task every 3 min during market hours
2. **Upstash Redis** — SSL required (`rediss://`); `broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE}`
3. **Celery + asyncio** — Each task wraps async code with `asyncio.run()`. Never share connection pools across event loops.
4. **SEC EDGAR rate limit** — Token bucket at 10 req/s (SEC limit). Proper User-Agent with email required.
5. **Claude API costs** — Sonnet for filing summaries (prompt-cached), Haiku + Batches API for bulk sentiment (50% discount)
6. **Test isolation** — SQLite in-memory for tests; no Neon, Redis, or API keys needed. `ARRAY` and `JSONB` columns use `.with_variant()` for SQLite compat.
7. **News deduplication** — SHA-256(url|title) for hard dedup + rapidfuzz (threshold 85%) for soft dedup within batches

## Environment Variables

See [.env.example](.env.example) for all required and optional variables.

**Minimum required:**
- `DATABASE_URL` — Neon PostgreSQL connection string
- `REDIS_URL` — Upstash Redis URL
- `EDGAR_USER_AGENT` — SEC requires this (format: `AppName/1.0 email@example.com`)

**Optional but recommended:**
- `ANTHROPIC_API_KEY` — Enables Claude filing analysis and sentiment scoring
- `FINNHUB_API_KEY` — Enables company news and earnings calendar
- `NEWS_API_KEY` — Enables NewsAPI aggregation
- `ALPHA_VANTAGE_API_KEY` — Price data fallback
