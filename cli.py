"""
EdgeFinder — Command Line Interface

Typer-based CLI for managing tickers, running ingestion, and launching the dashboard.

Usage:
    python cli.py init                          # Initialize DB, seed tickers/theses
    python cli.py ticker add PLTR               # Add a ticker
    python cli.py ticker list                   # List all tickers
    python cli.py ingest prices --days 365      # Backfill price history
    python cli.py ingest prices NVDA --days 30  # Backfill single ticker
    python cli.py run                           # Run full daily pipeline
    python cli.py serve                         # Launch dashboard on :8050

Install CLI as a command (optional):
    pip install -e .
    edgefinder ticker list
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="edgefinder",
    help="EdgeFinder Market Intelligence Platform",
    add_completion=False,
    rich_markup_mode="rich",
)

ticker_app = typer.Typer(help="Manage the ticker universe")
ingest_app = typer.Typer(help="Data ingestion commands")
thesis_app = typer.Typer(help="Manage investment theses")

app.add_typer(ticker_app, name="ticker")
app.add_typer(ingest_app, name="ingest")
app.add_typer(thesis_app, name="thesis")

console = Console()

# ---------------------------------------------------------------------------
# Shared async runner
# ---------------------------------------------------------------------------


def run(coro):
    """Run an async coroutine from a sync CLI command."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# init — Bootstrap the system
# ---------------------------------------------------------------------------


@app.command()
def init(
    skip_sp500: bool = typer.Option(False, "--skip-sp500", help="Skip S&P 500 fetch"),
):
    """
    Initialize EdgeFinder: run DB migrations, seed tickers and theses.

    Run this once after installation.
    """
    console.print("[bold green]Initializing EdgeFinder...[/bold green]")

    # 1. Run Alembic migrations
    console.print("  → Running database migrations...")
    try:
        import subprocess

        result = subprocess.run(
            ["alembic", "upgrade", "head"], capture_output=True, text=True, check=True
        )
        console.print(f"    ✓ Migrations complete: {result.stdout.strip() or 'up to date'}")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Migration failed:[/red] {e.stderr}")
        raise typer.Exit(1)

    # 2. Sync theses from YAML
    console.print("  → Syncing investment theses from config/theses.yaml...")
    run(_sync_theses())

    # 3. Load custom tickers from YAML
    console.print("  → Loading tickers from config/tickers.yaml...")
    run(_load_tickers_from_yaml())

    # 4. Fetch S&P 500
    if not skip_sp500:
        console.print("  → Fetching S&P 500 constituents from Wikipedia...")
        from scheduler.tasks import task_sync_sp500

        result = task_sync_sp500.apply_async()
        outcome = result.get(timeout=120)
        console.print(
            f"    ✓ S&P 500 sync: {outcome.get('added', 0)} added, "
            f"{outcome.get('updated', 0)} updated, {outcome.get('removed', 0)} removed"
        )

    console.print("\n[bold green]✓ EdgeFinder initialized successfully![/bold green]")
    console.print("Next steps:")
    console.print("  [cyan]python cli.py ingest prices --days 365[/cyan]  # Backfill price history")
    console.print("  [cyan]python cli.py serve[/cyan]                      # Launch dashboard")


async def _sync_theses() -> None:
    """Sync thesis definitions from theses.yaml into the database."""
    import yaml
    from sqlalchemy import select

    from config.settings import THESES_FILE
    from core.database import AsyncSessionLocal
    from core.models import Thesis

    with open(THESES_FILE) as f:
        data = yaml.safe_load(f)

    theses_data = data.get("theses", {})

    async with AsyncSessionLocal() as session:
        for slug, thesis_def in theses_data.items():
            result = await session.execute(select(Thesis).where(Thesis.slug == slug))
            thesis = result.scalar_one_or_none()

            if thesis:
                thesis.name = thesis_def.get("name", thesis.name)
                thesis.description = thesis_def.get("description", thesis.description)
                thesis.criteria_yaml = yaml.dump(thesis_def)
            else:
                thesis = Thesis(
                    slug=slug,
                    name=thesis_def.get("name", slug),
                    description=thesis_def.get("description"),
                    criteria_yaml=yaml.dump(thesis_def),
                )
            session.add(thesis)

        await session.commit()
        console.print(f"    ✓ Synced {len(theses_data)} thesis definitions")


async def _load_tickers_from_yaml() -> None:
    """Load custom tickers and watchlist from tickers.yaml into the database."""
    from datetime import date

    import yaml
    from sqlalchemy import select

    from config.settings import TICKERS_FILE
    from core.database import AsyncSessionLocal
    from core.models import Ticker

    with open(TICKERS_FILE) as f:
        data = yaml.safe_load(f)

    custom = data.get("universe", {}).get("custom", [])
    watchlist = data.get("watchlist", [])

    async with AsyncSessionLocal() as session:
        processed = 0

        for symbol in custom:
            result = await session.execute(select(Ticker).where(Ticker.symbol == symbol))
            ticker = result.scalar_one_or_none()
            if not ticker:
                ticker = Ticker(symbol=symbol, in_custom=True, first_seen=date.today())
                session.add(ticker)
                processed += 1

        for item in watchlist:
            symbol = item["symbol"]
            result = await session.execute(select(Ticker).where(Ticker.symbol == symbol))
            ticker = result.scalar_one_or_none()
            if not ticker:
                ticker = Ticker(symbol=symbol, first_seen=date.today())

            ticker.in_watchlist = True
            ticker.watchlist_priority = item.get("priority")
            ticker.watchlist_notes = item.get("notes")
            if item.get("thesis"):
                ticker.thesis_tags = [item["thesis"]]
            session.add(ticker)
            processed += 1

        await session.commit()
        console.print(
            f"    ✓ Loaded {len(custom)} custom tickers, {len(watchlist)} watchlist tickers"
        )


# ---------------------------------------------------------------------------
# ticker — Universe management
# ---------------------------------------------------------------------------


@ticker_app.command("add")
def ticker_add(
    symbol: str = typer.Argument(..., help="Ticker symbol (e.g. PLTR)"),
    thesis: str | None = typer.Option(None, "--thesis", help="Thesis slug (e.g. ai_defense)"),
    notes: str | None = typer.Option(None, "--notes", help="Free-text notes"),
    watchlist: bool = typer.Option(True, "--watchlist/--no-watchlist", help="Add to watchlist"),
    priority: int = typer.Option(5, "--priority", help="Watchlist priority (1=highest)"),
):
    """Add a ticker to the universe."""

    async def _add():
        from datetime import date

        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import Ticker

        symbol_upper = symbol.upper()
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Ticker).where(Ticker.symbol == symbol_upper))
            ticker = result.scalar_one_or_none()

            if ticker:
                console.print(f"[yellow]Ticker {symbol_upper} already exists. Updating...[/yellow]")
            else:
                ticker = Ticker(symbol=symbol_upper, first_seen=date.today(), in_custom=True)

            if watchlist:
                ticker.in_watchlist = True
                ticker.watchlist_priority = priority
            if notes:
                ticker.watchlist_notes = notes
            if thesis:
                existing_tags = ticker.thesis_tags or []
                if thesis not in existing_tags:
                    ticker.thesis_tags = existing_tags + [thesis]

            session.add(ticker)
            await session.commit()

        console.print(f"[green]✓ Added {symbol_upper}[/green]", end="")
        if thesis:
            console.print(f" | thesis: {thesis}", end="")
        console.print()

    run(_add())


@ticker_app.command("remove")
def ticker_remove(
    symbol: str = typer.Argument(..., help="Ticker symbol to remove"),
    hard: bool = typer.Option(
        False, "--hard", help="Hard delete from DB (default: soft deactivate)"
    ),
):
    """Remove a ticker from active tracking."""

    async def _remove():
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import Ticker

        symbol_upper = symbol.upper()
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Ticker).where(Ticker.symbol == symbol_upper))
            ticker = result.scalar_one_or_none()

            if not ticker:
                console.print(f"[red]Ticker {symbol_upper} not found.[/red]")
                return

            if hard:
                await session.delete(ticker)
                console.print(f"[red]✗ Hard deleted {symbol_upper} from database[/red]")
            else:
                ticker.is_active = False
                ticker.in_watchlist = False
                ticker.in_custom = False
                ticker.in_sp500 = False
                session.add(ticker)
                console.print(f"[yellow]~ Deactivated {symbol_upper} (data preserved)[/yellow]")

            await session.commit()

    run(_remove())


@ticker_app.command("list")
def ticker_list(
    sector: str | None = typer.Option(None, "--sector", help="Filter by sector"),
    watchlist_only: bool = typer.Option(False, "--watchlist", help="Show watchlist only"),
    sp500_only: bool = typer.Option(False, "--sp500", help="Show S&P 500 only"),
    limit: int = typer.Option(50, "--limit", help="Max results"),
):
    """List tickers in the universe."""

    async def _list():
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import Ticker

        async with AsyncSessionLocal() as session:
            stmt = select(Ticker).where(Ticker.is_active.is_(True))
            if sector:
                stmt = stmt.where(Ticker.sector.ilike(f"%{sector}%"))
            if watchlist_only:
                stmt = stmt.where(Ticker.in_watchlist.is_(True))
            if sp500_only:
                stmt = stmt.where(Ticker.in_sp500.is_(True))
            stmt = stmt.order_by(
                Ticker.watchlist_priority.asc().nullslast(), Ticker.symbol.asc()
            ).limit(limit)

            result = await session.execute(stmt)
            tickers = result.scalars().all()

        table = Table(title=f"Tickers ({len(tickers)} shown)")
        table.add_column("Symbol", style="cyan", width=8)
        table.add_column("Name", width=30)
        table.add_column("Sector", width=22)
        table.add_column("SP500", width=6)
        table.add_column("Watch", width=6)
        table.add_column("Thesis", width=20)

        for t in tickers:
            table.add_row(
                t.symbol,
                (t.name or "")[:30],
                (t.sector or "")[:22],
                "✓" if t.in_sp500 else "",
                "✓" if t.in_watchlist else "",
                ", ".join(t.thesis_tags or [])[:20],
            )

        console.print(table)

    run(_list())


# ---------------------------------------------------------------------------
# ingest — Data ingestion
# ---------------------------------------------------------------------------


@ingest_app.command("prices")
def ingest_prices(
    symbol: str | None = typer.Argument(None, help="Single ticker symbol (default: all)"),
    days: int = typer.Option(365, "--days", "-d", help="Number of days to fetch"),
    concurrency: int = typer.Option(5, "--concurrency", "-c", help="Concurrent fetches"),
):
    """Fetch and store OHLCV price data."""

    async def _ingest():
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.price_data import fetch_and_store_prices, fetch_and_store_prices_batch

        async with AsyncSessionLocal() as session:
            if symbol:
                result = await session.execute(
                    select(Ticker).where(Ticker.symbol == symbol.upper())
                )
                ticker = result.scalar_one_or_none()
                if not ticker:
                    console.print(f"[red]Ticker {symbol.upper()} not found. Add it first:[/red]")
                    console.print(f"  python cli.py ticker add {symbol.upper()}")
                    return

                with console.status(f"Fetching {days} days of prices for {symbol.upper()}..."):
                    count = await fetch_and_store_prices(session, ticker, days=days)
                console.print(f"[green]✓ {symbol.upper()}: {count} bars stored[/green]")
            else:
                result = await session.execute(select(Ticker).where(Ticker.is_active.is_(True)))
                tickers = result.scalars().all()
                console.print(f"Fetching prices for {len(tickers)} active tickers...")

                with console.status(f"Downloading {days} days of OHLCV data..."):
                    results = await fetch_and_store_prices_batch(
                        session, list(tickers), days=days, concurrency=concurrency
                    )

                total = sum(results.values())
                errors = sum(1 for v in results.values() if v == 0)
                console.print(
                    f"[green]✓ Price ingestion complete: {total} bars stored "
                    f"({errors} tickers had no data)[/green]"
                )

    run(_ingest())


@ingest_app.command("filings")
def ingest_filings(
    ticker: str | None = typer.Argument(None, help="Single ticker (default: all active)"),
    filing_type: str = typer.Option("10-K", "--type", "-t", help="Filing type (10-K, 10-Q, 8-K)"),
    limit: int = typer.Option(5, "--limit", "-l", help="Max filings per ticker"),
    analyze: bool = typer.Option(True, "--analyze/--no-analyze", help="Run analysis after fetch"),
):
    """Fetch and parse SEC EDGAR filings."""

    async def _ingest():
        from sqlalchemy import select

        from analysis.filing_analyzer import analyze_pending_filings
        from config.settings import settings
        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.sec_edgar import fetch_filings_for_ticker, update_ticker_cik

        async with AsyncSessionLocal() as session:
            if ticker:
                result = await session.execute(
                    select(Ticker).where(Ticker.symbol == ticker.upper())
                )
                tickers_to_process = [result.scalar_one_or_none()]
                if not tickers_to_process[0]:
                    console.print(f"[red]Ticker {ticker.upper()} not found.[/red]")
                    return
            else:
                result = await session.execute(select(Ticker).where(Ticker.is_active.is_(True)))
                tickers_to_process = list(result.scalars().all())

            console.print(f"Processing {len(tickers_to_process)} ticker(s)...")
            total_filings = 0

            for t in tickers_to_process:
                if not t.cik:
                    console.print(f"  [{t.symbol}] Looking up CIK...")
                    found = await update_ticker_cik(session, t)
                    if not found:
                        console.print(f"  [{t.symbol}] CIK not found — skipping")
                        continue

                with console.status(f"  Fetching {filing_type} for {t.symbol}..."):
                    filings = await fetch_filings_for_ticker(
                        session, t, filing_types=[filing_type], limit=limit
                    )

                console.print(f"  [green]✓ {t.symbol}: {len(filings)} filings[/green]")
                total_filings += len(filings)

            if analyze and total_filings:
                api_key = settings.anthropic_api_key if settings.has_anthropic else None
                label = "Claude + regex" if api_key else "regex only"
                with console.status(f"Analyzing filings ({label})..."):
                    analyzed = await analyze_pending_filings(
                        session, anthropic_api_key=api_key, limit=total_filings
                    )
                console.print(f"  [cyan]↳ {analyzed} filings analyzed[/cyan]")

            await session.commit()
            console.print(f"\n[bold green]✓ Ingested {total_filings} total filings.[/bold green]")

    run(_ingest())


@ingest_app.command("insider-trades")
def ingest_insider_trades(
    ticker: str | None = typer.Argument(None, help="Single ticker (default: watchlist)"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max Form 4 filings per ticker"),
):
    """Fetch Form 4 insider trade filings."""

    async def _ingest():
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.insider_trades import fetch_and_store_insider_trades
        from ingestion.sec_edgar import update_ticker_cik

        async with AsyncSessionLocal() as session:
            if ticker:
                result = await session.execute(
                    select(Ticker).where(Ticker.symbol == ticker.upper())
                )
                tickers_to_process = [result.scalar_one_or_none()]
                if not tickers_to_process[0]:
                    console.print(f"[red]Ticker {ticker.upper()} not found.[/red]")
                    return
            else:
                result = await session.execute(
                    select(Ticker).where(Ticker.is_active.is_(True), Ticker.in_watchlist.is_(True))
                )
                tickers_to_process = list(result.scalars().all())

            total = 0
            for t in tickers_to_process:
                if not t.cik:
                    await update_ticker_cik(session, t)
                    if not t.cik:
                        continue
                count = await fetch_and_store_insider_trades(session, t, limit=limit)
                if count:
                    console.print(f"  [green]✓ {t.symbol}: {count} new trades[/green]")
                total += count

            await session.commit()
            console.print(f"[bold green]✓ Stored {total} total insider trades.[/bold green]")

    run(_ingest())


@ingest_app.command("news")
def ingest_news(
    ticker: str | None = typer.Argument(None, help="Single ticker (default: all active)"),
    days: int = typer.Option(7, "--days", "-d", help="Look-back window in days"),
    rss_only: bool = typer.Option(False, "--rss-only", help="Skip Finnhub and NewsAPI"),
):
    """Aggregate news articles from RSS, Finnhub, and NewsAPI."""

    async def _ingest():
        from sqlalchemy import select

        from config.settings import settings
        from core.database import AsyncSessionLocal
        from core.models import Ticker
        from ingestion.news_feed import aggregate_news_batch, aggregate_news_for_ticker

        async with AsyncSessionLocal() as session:
            if ticker:
                result = await session.execute(
                    select(Ticker).where(Ticker.symbol == ticker.upper())
                )
                t = result.scalar_one_or_none()
                if not t:
                    console.print(f"[red]Ticker {ticker.upper()} not found.[/red]")
                    return

                finnhub_key = (
                    "" if rss_only else (settings.finnhub_api_key if settings.has_finnhub else "")
                )
                newsapi_key = "" if rss_only else getattr(settings, "news_api_key", "")

                with console.status(f"Fetching news for {t.symbol}..."):
                    count = await aggregate_news_for_ticker(
                        session,
                        t,
                        finnhub_api_key=finnhub_key,
                        newsapi_key=newsapi_key,
                        days=days,
                    )
                await session.commit()
                console.print(f"[green]✓ {t.symbol}: {count} new articles stored[/green]")
            else:
                result = await session.execute(select(Ticker).where(Ticker.is_active.is_(True)))
                tickers_to_process = list(result.scalars().all())

                finnhub_key = (
                    "" if rss_only else (settings.finnhub_api_key if settings.has_finnhub else "")
                )
                newsapi_key = "" if rss_only else getattr(settings, "news_api_key", "")

                sources = []
                if not rss_only:
                    if finnhub_key:
                        sources.append("Finnhub")
                    if newsapi_key:
                        sources.append("NewsAPI")
                sources.append("RSS")
                console.print(
                    f"Fetching news for {len(tickers_to_process)} tickers via {', '.join(sources)}..."
                )

                with console.status("Aggregating news..."):
                    total = await aggregate_news_batch(
                        session,
                        tickers=tickers_to_process,
                        finnhub_api_key=finnhub_key,
                        newsapi_key=newsapi_key,
                        days=days,
                    )

                await session.commit()
                console.print(f"[bold green]✓ {total} new articles stored.[/bold green]")

    run(_ingest())


# ---------------------------------------------------------------------------
# run — Full pipeline
# ---------------------------------------------------------------------------


@app.command()
def run_pipeline(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would run, don't execute"),
):
    """Run the full daily data pipeline."""
    console.print("[bold]EdgeFinder Daily Pipeline[/bold]")

    if dry_run:
        console.print("[yellow]DRY RUN — no tasks will execute[/yellow]")
        console.print("Would run:")
        console.print("  1. Fetch EOD prices for all tickers")
        console.print("  2. Compute technical indicators")
        console.print("  3. Detect anomalies")
        console.print("  4. Run alert engine")
        return

    from scheduler.orchestrator import run_daily_eod_pipeline

    result = run_daily_eod_pipeline()
    console.print(f"[green]✓ Pipeline started (task ID: {result.id})[/green]")
    console.print("Monitor with: celery -A scheduler.tasks flower")


# ---------------------------------------------------------------------------
# serve — Launch dashboard
# ---------------------------------------------------------------------------


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8050, "--port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes"),
):
    """Launch the EdgeFinder web dashboard."""
    import uvicorn

    console.print(
        f"[bold green]Starting EdgeFinder dashboard on http://localhost:{port}[/bold green]"
    )
    console.print("Press Ctrl+C to stop.")

    try:
        import api.app  # noqa: F401 — verify module exists before uvicorn loads it

        uvicorn.run(
            "api.app:create_app",
            factory=True,
            host=host,
            port=port,
            reload=reload,
            log_level="info",
        )
    except ImportError:
        console.print(
            "[yellow]Dashboard not yet available (Phase 5).[/yellow]\n"
            "Run [cyan]python cli.py ingest prices --days 365[/cyan] to start with data ingestion."
        )


# ---------------------------------------------------------------------------
# briefing — Generate daily briefing
# ---------------------------------------------------------------------------


@app.command()
def briefing(
    dry_run: bool = typer.Option(True, "--dry-run/--send", help="Print without delivering"),
    date_str: str | None = typer.Option(None, "--date", help="Date (YYYY-MM-DD, default: today)"),
):
    """Generate and optionally deliver the daily briefing. (Phase 4)"""
    console.print("[yellow]Daily briefing generation will be available in Phase 4.[/yellow]")


# ---------------------------------------------------------------------------
# status — System health check
# ---------------------------------------------------------------------------


@app.command()
def status():
    """Show system status: DB, Redis, worker counts, last ingestion timestamps."""

    async def _status():
        checks = {}

        # DB check
        try:
            from core.database import check_db_connection

            ok = await check_db_connection()
            checks["database"] = ("✓ Connected", "green") if ok else ("✗ Failed", "red")
        except Exception as e:
            checks["database"] = (f"✗ Error: {e}", "red")

        # Redis check
        try:
            import redis as redis_lib

            from config.settings import settings

            # Strip rediss:// scheme for redis-py test
            r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=5)
            r.ping()
            checks["redis"] = ("✓ Connected", "green")
        except Exception as e:
            checks["redis"] = (f"✗ Error: {e}", "red")

        # Ticker counts
        try:
            from sqlalchemy import func, select

            from core.database import AsyncSessionLocal
            from core.models import Ticker

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(func.count(Ticker.id)).where(Ticker.is_active.is_(True))
                )
                total = result.scalar_one()
                checks["active_tickers"] = (f"✓ {total} tickers", "green")
        except Exception as e:
            checks["active_tickers"] = (f"✗ {e}", "red")

        table = Table(title="EdgeFinder Status")
        table.add_column("Component")
        table.add_column("Status")
        for component, (msg, color) in checks.items():
            table.add_row(component.replace("_", " ").title(), f"[{color}]{msg}[/{color}]")
        console.print(table)

    run(_status())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
