PYTHON  := .venv/bin/python
COMPOSE := docker compose
DAYS    ?= 365       # override with: make ingest-prices DAYS=90

.DEFAULT_GOAL := help

.PHONY: help \
        up down logs \
        docker-build docker-up docker-down \
        status init migrate worker serve run \
        create-admin \
        ingest-prices ingest-filings ingest-insider ingest-news ingest-macro ingest-transcripts \
        ticker-list \
        railway-deploy railway-migrate railway-admin railway-logs

# ── Help ────────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  EdgeFinder — Make Targets"
	@echo ""
	@echo "  Docker (local dev)"
	@echo "    make up                 Start Redis container"
	@echo "    make down               Stop containers"
	@echo "    make logs               Tail Redis logs"
	@echo ""
	@echo "  Docker (full stack)"
	@echo "    make docker-build       Build Docker image"
	@echo "    make docker-up          Start web + worker + Redis"
	@echo "    make docker-down        Stop all containers"
	@echo ""
	@echo "  Project"
	@echo "    make status             System health (DB + Redis + tickers)"
	@echo "    make init               Migrate + seed tickers and theses"
	@echo "    make migrate            Run Alembic migrations only"
	@echo "    make worker             Start Celery worker"
	@echo "    make serve              Launch dashboard on :8050"
	@echo "    make run                Full daily EOD pipeline"
	@echo "    make create-admin       Create an admin user"
	@echo ""
	@echo "  Data"
	@echo "    make ingest-prices      Backfill all tickers  DAYS=$(DAYS)"
	@echo "    make ingest-filings     Fetch 10-K filings"
	@echo "    make ingest-insider     Fetch Form 4 insider trades"
	@echo "    make ingest-news        Aggregate news articles"
	@echo "    make ingest-macro       Fetch FRED macro indicators"
	@echo "    make ingest-transcripts Fetch earnings call transcripts"
	@echo "    make ticker-list        List active tickers"
	@echo ""
	@echo "  Railway (production)"
	@echo "    make railway-deploy     Deploy to Railway"
	@echo "    make railway-migrate    Run migrations on Railway"
	@echo "    make railway-admin      Create admin user on Railway"
	@echo "    make railway-logs       Tail Railway service logs"
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

# ── Auth ────────────────────────────────────────────────────────────────────────

create-admin:
	@read -p "Email: " email; \
	read -sp "Password: " password; echo; \
	$(PYTHON) cli.py create-admin --email "$$email" --password "$$password"

# ── Project ─────────────────────────────────────────────────────────────────────

status: up
	$(PYTHON) cli.py status

init: up migrate
	$(PYTHON) cli.py init --skip-sp500

worker: up
	$(PYTHON) -m celery -A scheduler.tasks worker --loglevel=info

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
	railway up

railway-migrate:
	railway run python -m alembic upgrade head

railway-admin:
	@read -p "Email: " email; \
	read -sp "Password: " password; echo; \
	railway run python cli.py create-admin --email "$$email" --password "$$password"

railway-logs:
	railway logs
