PYTHON  := .venv/bin/python
COMPOSE := docker compose
DAYS    ?= 365       # override with: make ingest-prices DAYS=90

.DEFAULT_GOAL := help

.PHONY: help \
        up down logs \
        docker-build docker-up docker-down \
        status init migrate worker serve run \
        create-admin test test-unit \
        ingest-prices ingest-filings ingest-insider ingest-news ingest-macro ingest-transcripts \
        ticker-list \
        railway-deploy railway-deploy-worker \
        railway-migrate railway-admin railway-logs railway-logs-worker \
        simulation-worker railway-deploy-simulation railway-deploy-all-3

# ── Help ────────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  EdgeFinder — Make Targets"
	@echo ""
	@echo "  ── Local Dev ─────────────────────────────────────"
	@echo "    make init               First-time: Redis + migrate + seed"
	@echo "    make serve              Web dashboard  http://localhost:8050"
	@echo "    make worker             Celery worker + beat (all queues)"
	@echo "    make simulation-worker  Simulation queue only"
	@echo "    make status             Health check: DB, Redis, tickers"
	@echo "    make migrate            Run Alembic migrations only"
	@echo "    make create-admin       Create admin user interactively"
	@echo "    make run                Trigger full daily EOD pipeline"
	@echo ""
	@echo "  ── Tests ─────────────────────────────────────────"
	@echo "    make test               All 368 tests (~20s, no live services)"
	@echo "    make test-unit          Unit tests only (~15s)"
	@echo ""
	@echo "  ── Data Backfill ─────────────────────────────────"
	@echo "    make ingest-prices      All tickers  DAYS=$(DAYS)"
	@echo "    make ingest-filings     SEC 10-K/10-Q filings"
	@echo "    make ingest-news        RSS + Finnhub + NewsAPI"
	@echo "    make ingest-macro       FRED macro indicators"
	@echo "    make ingest-insider     Form 4 insider trades"
	@echo "    make ingest-transcripts Earnings call transcripts"
	@echo "    make ticker-list        List active tickers"
	@echo ""
	@echo "  ── Docker (full stack) ───────────────────────────"
	@echo "    make docker-build       Build Docker image"
	@echo "    make docker-up          web + worker + simulation + Redis"
	@echo "    make docker-down        Stop all containers"
	@echo "    make up                 Redis only (for local dev)"
	@echo "    make down               Stop all"
	@echo ""
	@echo "  ── Railway (deployed) ────────────────────────────"
	@echo "    make railway-migrate            Run migrations on Neon via Railway"
	@echo "    make railway-admin              Create admin user on Railway"
	@echo "    make railway-deploy             Deploy: web"
	@echo "    make railway-deploy-worker      Deploy: worker"
	@echo "    make railway-deploy-simulation  Deploy: simulation-worker"
	@echo "    make railway-deploy-all-3       Deploy: all three services"
	@echo "    make railway-logs               Tail web logs"
	@echo "    make railway-logs-worker        Tail worker logs"
	@echo ""

# ── Docker (local dev — Redis only) ──────────────────────────────────────────

up:
	$(COMPOSE) up -d redis

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f redis

# ── Docker (full stack) ──────────────────────────────────────────────────────

docker-build:
	$(COMPOSE) build

docker-up:
	$(COMPOSE) up -d

docker-down:
	$(COMPOSE) down

# ── DB ──────────────────────────────────────────────────────────────────────────

migrate:
	$(PYTHON) -m alembic upgrade head

# ── Tests ───────────────────────────────────────────────────────────────────────

test:
	$(PYTHON) -m pytest tests/ -q

test-unit:
	$(PYTHON) -m pytest tests/unit/ -q

# ── Auth ────────────────────────────────────────────────────────────────────────

create-admin:
	@bash -c 'read -p "Email: " email; read -sp "Password: " password; echo; $(PYTHON) cli.py create-admin --email "$$email" --password "$$password"'

# ── Project ─────────────────────────────────────────────────────────────────────

status: up
	$(PYTHON) cli.py status

init: up migrate
	$(PYTHON) cli.py init --skip-sp500

worker: up
	$(PYTHON) -m celery -A scheduler.tasks worker --beat --loglevel=info -Q ingestion,analysis,alerts,delivery,simulation

serve: up
	$(PYTHON) cli.py serve

run: up
	$(PYTHON) cli.py run

# ── Data ─────────────────────────────────────────────────────────────────────────

ingest-prices: up
	$(PYTHON) cli.py ingest prices --days $(DAYS)

ingest-filings: up
	$(PYTHON) cli.py ingest filings

ingest-insider: up
	$(PYTHON) cli.py ingest insider-trades

ingest-news: up
	$(PYTHON) cli.py ingest news

ingest-macro: up
	$(PYTHON) cli.py ingest macro

ingest-transcripts: up
	$(PYTHON) cli.py ingest transcripts

ticker-list:
	$(PYTHON) cli.py ticker list

# ── Railway (production) ────────────────────────────────────────────────────

railway-deploy:
	railway up --service edgefinder

railway-deploy-worker:
	railway up --service edgefinder-worker


railway-migrate:
	railway run .venv/bin/python -m alembic upgrade head

railway-admin:
	@bash -c 'read -p "Email: " email; read -sp "Password: " password; echo; railway run .venv/bin/python cli.py create-admin --email "$$email" --password "$$password"'

railway-logs:
	railway logs --service edgefinder

railway-logs-worker:
	railway logs --service edgefinder-worker

# ── Simulation Engine ──────────────────────────────────────────────────────

simulation-worker: up
	$(PYTHON) -m celery -A scheduler.tasks worker -Q simulation -c 2 --loglevel=info

railway-deploy-simulation:
	railway up --service edgefinder-simulation

railway-deploy-all-3:
	railway up --service edgefinder
	railway up --service edgefinder-worker
	railway up --service edgefinder-simulation

# ── ML Training (local GPU only) ────────────────────────────────────────

ml-worker: up
	$(PYTHON) -m celery -A scheduler.tasks worker -Q ml_training -c 1 --loglevel=info -n ml_training@%h

ml-train-sentiment:
	$(PYTHON) -m ml.sentiment.training

ml-train-ranker:
	$(PYTHON) -m ml.signal_ranker.training

ml-train-hedging:
	$(PYTHON) -m ml.deep_hedging.training
