# EdgeFinder — Market Intelligence Platform

A local-first Python application that ingests SEC filings, tracks news sentiment, detects price/volume anomalies, and delivers a daily briefing for a 500+ ticker universe.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, asyncio |
| Database | Neon PostgreSQL (serverless, `asyncpg`) |
| Task Queue | Celery + Upstash Redis (serverless) |
| Frontend | React SPA (Vite + TypeScript + Tailwind + shadcn/ui) |
| AI | Claude Sonnet (filings) + Claude Haiku (bulk) |
| CLI | Typer |

## Quick Start

### Prerequisites
- Python 3.11+
- Docker (for local Redis during development)
- [Neon account](https://console.neon.tech) — free PostgreSQL
- [Upstash account](https://console.upstash.com) — free Redis

### Installation

```bash
# 1. Clone and install dependencies
git clone <repo-url>
cd edgefinder
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — at minimum set DATABASE_URL and REDIS_URL

# 3. Start local Redis (if not using Upstash)
docker-compose up -d redis

# 4. Initialize the system
python cli.py init

# 5. Backfill price history (takes ~5-10 min for full S&P 500)
python cli.py ingest prices --days 365

# 6. Run first pipeline
python cli.py run
```

### Start Workers

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
python cli.py init              # Initialize DB and seed data
python cli.py status            # Check DB, Redis, and ticker counts
python cli.py run               # Run full daily pipeline

# Tickers
python cli.py ticker add PLTR --thesis ai_defense --notes "Gov AI contracts"
python cli.py ticker remove XYZ
python cli.py ticker list
python cli.py ticker list --sector Technology --watchlist

# Ingestion
python cli.py ingest prices --days 365      # All tickers, 1 year
python cli.py ingest prices NVDA --days 30  # Single ticker

# Dashboard
python cli.py serve
```

## Project Structure

```
edgefinder/
├── config/          # Settings, tickers.yaml, theses.yaml
├── core/            # Database, ORM models, event bus
├── ingestion/       # SEC EDGAR, price data, news, insider trades
├── analysis/        # Technicals, sentiment, filing analysis, thesis matching
├── alerts/          # Alert engine, buy-the-dip scorer, delivery
├── api/             # FastAPI REST API + SSE
├── frontend/        # React SPA (Phase 5)
├── scheduler/       # Celery tasks + Beat schedule
├── tests/           # pytest test suite
├── cli.py           # Typer CLI
└── daily_briefing.py
```

## Build Phases

- **Phase 1 (✓):** Foundation — DB, price ingestion, technicals, CLI
- **Phase 2:** Filing Intelligence — SEC EDGAR, Claude Sonnet analysis, insider trades
- **Phase 3:** News & Sentiment — RSS aggregation, Claude Haiku batch sentiment
- **Phase 4:** Alerts & Thesis — Buy-the-dip engine, daily briefing
- **Phase 5:** Dashboard — React SPA, FastAPI routes, SSE real-time alerts

## Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only (fast, no I/O)
pytest tests/unit/ -v

# Integration tests (uses SQLite in-memory, no Neon needed)
pytest tests/integration/ -v

# Skip slow tests
pytest tests/ -m "not slow" -v
```

## Key Design Decisions

1. **Neon free tier** — `pool_pre_ping=True` and `pool_recycle=300` handle cold starts
2. **Upstash Redis** — SSL required (`rediss://`); upgrade from free tier when command count exceeds 10K/day
3. **Celery + asyncio** — Each task wraps async code with `asyncio.run()`. Never share connection pools across event loops.
4. **SEC EDGAR rate limit** — Token bucket at 8 req/s (SEC allows 10). Violating this gets you IP-blocked.
5. **Claude API costs** — Sonnet for filing summaries (prompt-cached), Haiku + Batches API for bulk sentiment (50% discount)

## Environment Variables

See [.env.example](.env.example) for all required and optional variables.
