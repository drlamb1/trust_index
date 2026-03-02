"""
EdgeFinder — Daily Briefing Generator (Phase 4)

Assembles a Markdown daily briefing from whatever data exists in the DB
and delivers it via configured channels at 7 AM UTC.

Sections (gracefully empty if data is absent):
  1. Market Overview      — yfinance SPY/QQQ/VIX/TLT (always live)
  2. Watchlist Movers     — top gainers/losers from price_bars (last 5 days)
  3. Recent Alerts        — any alerts created in last 24h
  4. Top News             — highest |sentiment_score| articles (last 24h)
  5. Insider Activity     — Form 4 buys filed in last 7 days
  6. Technical Signals    — RSI extremes + golden/death cross from snapshots
  7. Thesis Matches       — placeholder until thesis_matcher is wired

CLI:
    python daily_briefing.py --dry-run          # print to terminal
    python daily_briefing.py --send             # deliver via configured channels
    python daily_briefing.py --date 2026-02-19  # specific date
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Market overview — fetched live from yfinance
# ---------------------------------------------------------------------------

_MARKET_SYMBOLS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq",
    "^VIX": "VIX",
    "TLT": "20Y Treasury",
    "DX-Y.NYB": "US Dollar",
}


def _fetch_market_data_sync() -> dict[str, dict]:
    """Fetch last 5 days of prices for market overview symbols (sync, run in thread)."""
    import yfinance as yf

    results = {}
    for symbol, label in _MARKET_SYMBOLS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if len(hist) < 2:
                continue
            # Reset index first (yfinance >= 0.2.50 uses Datetime index)
            hist = hist.reset_index()
            hist.columns = [c.lower().replace(" ", "_") for c in hist.columns]
            if "datetime" in hist.columns and "date" not in hist.columns:
                hist = hist.rename(columns={"datetime": "date"})

            prev = float(hist["close"].iloc[-2])
            last = float(hist["close"].iloc[-1])
            pct = (last - prev) / prev * 100
            results[symbol] = {
                "label": label,
                "price": last,
                "change_pct": pct,
                "prev": prev,
            }
        except Exception as exc:
            logger.warning("Market data fetch failed for %s: %s", symbol, exc)
    return results


async def _fetch_market_overview() -> dict[str, dict]:
    return await asyncio.to_thread(_fetch_market_data_sync)


def _format_market_overview(market: dict[str, dict]) -> str:
    if not market:
        return "_Market data unavailable._\n"

    lines = []
    for symbol, data in market.items():
        label = data["label"]
        price = data["price"]
        pct = data["change_pct"]
        arrow = "▲" if pct >= 0 else "▼"
        sign = "+" if pct >= 0 else ""

        if symbol == "^VIX":
            # VIX: no $ prefix
            lines.append(f"  {label:<18} {price:>7.2f}   {arrow} {sign}{pct:.2f}%")
        elif symbol == "DX-Y.NYB":
            lines.append(f"  {label:<18} {price:>7.3f}   {arrow} {sign}{pct:.2f}%")
        else:
            lines.append(f"  {label:<18} ${price:>8.2f}  {arrow} {sign}{pct:.2f}%")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Watchlist movers — from price_bars
# ---------------------------------------------------------------------------


async def _fetch_watchlist_movers(session: AsyncSession, days: int = 5) -> list[dict]:
    """Return top 5 gainers and top 5 losers among watchlist tickers over `days` days."""
    from core.models import PriceBar, Ticker

    cutoff = date.today() - timedelta(days=days + 3)  # buffer for weekends

    result = await session.execute(
        select(Ticker).where(Ticker.is_active.is_(True), Ticker.in_watchlist.is_(True))
    )
    tickers = result.scalars().all()

    movers = []
    for ticker in tickers:
        bars_result = await session.execute(
            select(PriceBar)
            .where(PriceBar.ticker_id == ticker.id, PriceBar.date >= cutoff)
            .order_by(PriceBar.date.asc())
        )
        bars = bars_result.scalars().all()
        if len(bars) < 2:
            continue

        start_price = bars[0].close
        end_price = bars[-1].close
        if start_price and start_price > 0:
            pct = (end_price - start_price) / start_price * 100
            movers.append({
                "symbol": ticker.symbol,
                "name": ticker.name or ticker.symbol,
                "start": start_price,
                "end": end_price,
                "pct": pct,
                "days": (bars[-1].date - bars[0].date).days,
            })

    movers.sort(key=lambda x: x["pct"], reverse=True)
    return movers


def _format_movers(movers: list[dict]) -> str:
    if not movers:
        return "_No price data available yet. Run: `./ef ingest prices`_\n"

    gainers = [m for m in movers if m["pct"] > 0][:5]
    losers = [m for m in reversed(movers) if m["pct"] < 0][:5]

    lines = []
    if gainers:
        lines.append("**Top Gainers**\n")
        lines.append("| Ticker | 5D % | Start | End | Period |")
        lines.append("|--------|------|-------|-----|--------|")
        for m in gainers:
            lines.append(f"| {m['symbol']} | +{m['pct']:.1f}% | ${m['start']:.2f} | ${m['end']:.2f} | {m['days']}d |")
    if losers:
        lines.append("\n**Top Losers**\n")
        lines.append("| Ticker | 5D % | Start | End | Period |")
        lines.append("|--------|------|-------|-----|--------|")
        for m in losers:
            lines.append(f"| {m['symbol']} | {m['pct']:.1f}% | ${m['start']:.2f} | ${m['end']:.2f} | {m['days']}d |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Recent alerts
# ---------------------------------------------------------------------------


async def _fetch_recent_alerts(session: AsyncSession, hours: int = 24) -> list[Any]:
    from core.models import Alert, Ticker

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await session.execute(
        select(Alert, Ticker.symbol)
        .join(Ticker, Alert.ticker_id == Ticker.id)
        .where(Alert.created_at >= cutoff)
        .order_by(desc(Alert.score), desc(Alert.created_at))
        .limit(10)
    )
    return result.all()


def _format_alerts(rows: list) -> str:
    if not rows:
        return "_No alerts in the last 24 hours._\n"

    severity_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
    lines = [
        "| Severity | Ticker | Alert | Score |",
        "|----------|--------|-------|-------|",
    ]
    for alert, symbol in rows:
        icon = severity_icon.get(alert.severity, "⚪")
        score_str = f"{alert.score:.0f}" if alert.score else "—"
        title = alert.title or ""
        lines.append(f"| {icon} {alert.severity or '?'} | {symbol} | {title} | {score_str} |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Top news by sentiment
# ---------------------------------------------------------------------------


async def _fetch_top_news(session: AsyncSession, hours: int = 24, limit: int = 8) -> list[Any]:
    from sqlalchemy import func

    from core.models import NewsArticle

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await session.execute(
        select(NewsArticle)
        .where(
            NewsArticle.published_at >= cutoff,
            NewsArticle.sentiment_score.isnot(None),
        )
        .order_by(desc(func.abs(NewsArticle.sentiment_score)))
        .limit(limit)
    )
    return result.scalars().all()


def _format_news(articles: list) -> str:
    if not articles:
        return "_No scored news in the last 24 hours. Run: `./ef ingest news`_\n"

    lines = [
        "| Sentiment | Score | Headline | Source |",
        "|-----------|-------|----------|--------|",
    ]
    for art in articles:
        score = art.sentiment_score or 0
        icon = "📈" if score > 0.2 else ("📉" if score < -0.2 else "➡️")
        source = art.source_name or "Unknown"
        title = (art.title[:80] + "…" if len(art.title) > 80 else art.title).replace("|", "—")
        lines.append(f"| {icon} | {score:+.2f} | {title} | {source} |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Insider activity
# ---------------------------------------------------------------------------


async def _fetch_insider_buys(session: AsyncSession, days: int = 7) -> list[Any]:
    from core.models import InsiderTrade, Ticker

    cutoff = date.today() - timedelta(days=days)
    result = await session.execute(
        select(InsiderTrade, Ticker.symbol)
        .join(Ticker, InsiderTrade.ticker_id == Ticker.id)
        .where(
            InsiderTrade.filed_date >= cutoff,
            InsiderTrade.trade_type == "buy",
        )
        .order_by(desc(InsiderTrade.total_amount))
        .limit(8)
    )
    return result.all()


def _format_insider_buys(rows: list) -> str:
    if not rows:
        return "_No insider buys in the last 7 days._\n"

    lines = [
        "| Ticker | Insider | Title | Amount | Filed |",
        "|--------|---------|-------|--------|-------|",
    ]
    for trade, symbol in rows:
        amount = f"${trade.total_amount:,.0f}" if trade.total_amount else "—"
        name = trade.insider_name or "Unknown"
        title = trade.insider_title or "—"
        filed = trade.filed_date.strftime("%b %d") if trade.filed_date else "—"
        lines.append(f"| {symbol} | {name} | {title} | {amount} | {filed} |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Technical signals
# ---------------------------------------------------------------------------


async def _fetch_technical_signals(session: AsyncSession) -> list[dict]:
    """Find RSI extremes and SMA crossovers from the most recent snapshot per ticker."""
    from core.models import TechnicalSnapshot, Ticker

    result = await session.execute(
        select(Ticker).where(Ticker.is_active.is_(True), Ticker.in_watchlist.is_(True))
    )
    tickers = result.scalars().all()

    signals = []
    for ticker in tickers:
        snap_result = await session.execute(
            select(TechnicalSnapshot)
            .where(TechnicalSnapshot.ticker_id == ticker.id)
            .order_by(desc(TechnicalSnapshot.date))
            .limit(2)
        )
        snaps = snap_result.scalars().all()
        if not snaps:
            continue

        latest = snaps[0]
        prev = snaps[1] if len(snaps) > 1 else None

        # RSI oversold / overbought
        if latest.rsi_14 is not None:
            if latest.rsi_14 < 30:
                signals.append({
                    "symbol": ticker.symbol,
                    "signal": "RSI Oversold",
                    "detail": f"RSI={latest.rsi_14:.1f}",
                    "icon": "📉",
                })
            elif latest.rsi_14 > 70:
                signals.append({
                    "symbol": ticker.symbol,
                    "signal": "RSI Overbought",
                    "detail": f"RSI={latest.rsi_14:.1f}",
                    "icon": "📈",
                })

        # Golden cross / death cross (SMA50 vs SMA200)
        if prev and all(
            x is not None
            for x in [latest.sma_50, latest.sma_200, prev.sma_50, prev.sma_200]
        ):
            if prev.sma_50 < prev.sma_200 and latest.sma_50 > latest.sma_200:
                signals.append({
                    "symbol": ticker.symbol,
                    "signal": "Golden Cross",
                    "detail": f"SMA50={latest.sma_50:.2f} crossed above SMA200={latest.sma_200:.2f}",
                    "icon": "✨",
                })
            elif prev.sma_50 > prev.sma_200 and latest.sma_50 < latest.sma_200:
                signals.append({
                    "symbol": ticker.symbol,
                    "signal": "Death Cross",
                    "detail": f"SMA50={latest.sma_50:.2f} crossed below SMA200={latest.sma_200:.2f}",
                    "icon": "💀",
                })

    return signals


def _format_technical_signals(signals: list[dict]) -> str:
    if not signals:
        return "_No technical signals. Run: `./ef ingest prices` then compute technicals._\n"

    lines = [
        "| Ticker | Signal | Detail |",
        "|--------|--------|--------|",
    ]
    for sig in signals:
        lines.append(f"| {sig['symbol']} | {sig['icon']} {sig['signal']} | {sig['detail']} |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 10-K drift analysis
# ---------------------------------------------------------------------------


async def _fetch_filing_drift(session: AsyncSession) -> list[dict]:
    """
    For each watchlist ticker, fetch the last 2 analyzed 10-K FilingAnalysis
    records and compute year-over-year drift in health score, red flags,
    and key financial metrics.
    """
    from core.models import Filing, FilingAnalysis, Ticker

    result = await session.execute(
        select(Ticker).where(Ticker.is_active.is_(True), Ticker.in_watchlist.is_(True))
    )
    tickers = result.scalars().all()

    drift_rows = []
    for ticker in tickers:
        # Get last 2 analyzed 10-K filings, newest first
        analyses_result = await session.execute(
            select(FilingAnalysis, Filing.filed_date, Filing.period_of_report)
            .join(Filing, FilingAnalysis.filing_id == Filing.id)
            .where(
                Filing.ticker_id == ticker.id,
                Filing.filing_type == "10-K",
                FilingAnalysis.health_score.isnot(None),
            )
            .order_by(desc(Filing.filed_date))
            .limit(2)
        )
        rows = analyses_result.all()
        if not rows:
            continue

        current_analysis, current_filed, current_period = rows[0]
        prior = rows[1] if len(rows) > 1 else None

        def _m(analysis, key):
            """Safely extract a financial metric."""
            fm = analysis.financial_metrics or {}
            v = fm.get(key)
            return float(v) if v is not None else None

        def _flag_count(analysis):
            return len(analysis.red_flags or [])

        current_score = current_analysis.health_score
        current_flags = _flag_count(current_analysis)
        current_gm = _m(current_analysis, "gross_margin_pct")
        current_om = _m(current_analysis, "operating_margin_pct")
        current_rev_growth = _m(current_analysis, "revenue_growth_pct")
        current_bull = len(current_analysis.bull_points or [])
        current_bear = len(current_analysis.bear_points or [])

        row = {
            "symbol": ticker.symbol,
            "period": current_period.strftime("%Y") if current_period else "?",
            "score": current_score,
            "flags": current_flags,
            "gross_margin": current_gm,
            "op_margin": current_om,
            "rev_growth": current_rev_growth,
            "bull": current_bull,
            "bear": current_bear,
            "score_delta": None,
            "flags_delta": None,
            "gm_delta": None,
            "om_delta": None,
            "has_prior": False,
        }

        if prior:
            prior_analysis, prior_filed, _ = prior
            prior_score = prior_analysis.health_score
            prior_gm = _m(prior_analysis, "gross_margin_pct")
            prior_om = _m(prior_analysis, "operating_margin_pct")

            row["has_prior"] = True
            row["score_delta"] = (current_score - prior_score) if prior_score is not None else None
            row["flags_delta"] = current_flags - _flag_count(prior_analysis)
            row["gm_delta"] = (current_gm - prior_gm) if (current_gm is not None and prior_gm is not None) else None
            row["om_delta"] = (current_om - prior_om) if (current_om is not None and prior_om is not None) else None

        drift_rows.append(row)

    # Sort by abs(score_delta) desc so biggest movers come first, then by score desc
    drift_rows.sort(key=lambda x: (-(abs(x["score_delta"]) if x["score_delta"] is not None else 0), -(x["score"] or 0)))
    return drift_rows


def _format_filing_drift(rows: list[dict]) -> str:
    if not rows:
        return "_No 10-K analyses available. Run: `./ef ingest filings --type 10-K --limit 2`_\n"

    lines = [
        "| Ticker | Year | Health | Δ | Flags | GM | OpM | RevGrowth | Tone |",
        "|--------|------|--------|---|-------|----|-----|-----------|------|",
    ]
    for r in rows:
        symbol = r["symbol"]
        score = f"{r['score']:.0f}" if r["score"] is not None else "—"
        period = r["period"]

        # Score delta
        if r["has_prior"] and r["score_delta"] is not None:
            delta = r["score_delta"]
            sign = "+" if delta >= 0 else ""
            delta_str = f"{sign}{delta:.0f}"
        else:
            delta_str = "—"

        flags = str(r["flags"])
        gm = f"{r['gross_margin']:.1f}%" if r["gross_margin"] is not None else "—"
        om = f"{r['op_margin']:.1f}%" if r["op_margin"] is not None else "—"
        rev = f"{r['rev_growth']:.1f}%" if r["rev_growth"] is not None else "—"

        bull, bear = r["bull"], r["bear"]
        tone = f"↑ {bull}B/{bear}b" if bull > bear else (f"↓ {bull}B/{bear}b" if bear > bull else f"→ {bull}B/{bear}b")

        lines.append(f"| {symbol} | {period} | {score} | {delta_str} | {flags} | {gm} | {om} | {rev} | {tone} |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Thesis matches
# ---------------------------------------------------------------------------


async def _fetch_thesis_matches(session: AsyncSession) -> list[dict]:
    """Fetch top thesis matches across all theses, grouped by thesis."""
    from core.models import Thesis, ThesisMatch, Ticker

    result = await session.execute(
        select(ThesisMatch, Ticker.symbol, Thesis.name)
        .join(Ticker, ThesisMatch.ticker_id == Ticker.id)
        .join(Thesis, ThesisMatch.thesis_id == Thesis.id)
        .where(ThesisMatch.score >= 20)
        .order_by(desc(ThesisMatch.score))
        .limit(20)
    )
    rows = result.all()

    matches = []
    for tm, symbol, thesis_name in rows:
        reasons = tm.match_reasons or {}
        matches.append({
            "symbol": symbol,
            "thesis": thesis_name,
            "score": tm.score,
            "fin_score": reasons.get("financial_score"),
            "kw_score": reasons.get("keyword_score"),
            "matched_kws": reasons.get("matched_keywords", []),
        })
    return matches


def _format_thesis_matches(matches: list[dict]) -> str:
    if not matches:
        return "_No thesis matches found. Run thesis matching to populate._\n"

    # Group by thesis
    from collections import defaultdict
    by_thesis: dict[str, list[dict]] = defaultdict(list)
    for m in matches:
        by_thesis[m["thesis"]].append(m)

    lines = []
    for thesis_name, tickers in by_thesis.items():
        lines.append(f"  **{thesis_name}**")
        for t in tickers[:5]:  # top 5 per thesis
            fin = f"Fin:{t['fin_score']:.0f}" if t["fin_score"] is not None else ""
            kw = f"KW:{t['kw_score']:.0f}" if t["kw_score"] is not None else ""
            parts = [p for p in [fin, kw] if p]
            detail = f"  ({' | '.join(parts)})" if parts else ""
            lines.append(f"    {t['symbol']:<6} score {t['score']:.0f}/100{detail}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Buy-the-dip scores
# ---------------------------------------------------------------------------


async def _fetch_dip_scores(session: AsyncSession) -> list[dict]:
    """Fetch recent dip alerts with their dimension scores."""
    from core.models import Alert, DipScore, Ticker

    result = await session.execute(
        select(Alert, DipScore, Ticker.symbol)
        .join(DipScore, DipScore.alert_id == Alert.id)
        .join(Ticker, Alert.ticker_id == Ticker.id)
        .where(Alert.alert_type == "buy_the_dip")
        .order_by(desc(Alert.created_at))
        .limit(10)
    )
    rows = result.all()

    dips = []
    for alert, dip, symbol in rows:
        dips.append({
            "symbol": symbol,
            "composite": dip.composite_score or 0,
            "severity": alert.severity or "green",
            "drop_pct": (alert.context_json or {}).get("drop_pct", 0),
            "price": (alert.context_json or {}).get("current_price", 0),
            "fundamental": dip.fundamental_score,
            "technical": dip.technical_setup,
            "sentiment": dip.sentiment_context,
            "insider": dip.insider_activity,
            "sector_rel": dip.sector_relative,
        })
    return dips


def _format_dip_scores(dips: list[dict]) -> str:
    if not dips:
        return "_No dip opportunities detected (all tickers within normal range)._\n"

    severity_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
    lines = []
    for d in dips:
        icon = severity_icon.get(d["severity"], "⚪")
        dims = []
        if d["fundamental"] is not None:
            dims.append(f"Fund:{d['fundamental']:.0f}")
        if d["technical"] is not None:
            dims.append(f"Tech:{d['technical']:.0f}")
        if d["sentiment"] is not None:
            dims.append(f"Sent:{d['sentiment']:.0f}")
        if d["insider"] is not None and d["insider"] > 0:
            dims.append(f"Insider:{d['insider']:.0f}")

        dim_str = f"  ({' | '.join(dims)})" if dims else ""
        lines.append(
            f"  {icon} {d['symbol']:<6} {d['composite']:.0f}/100  "
            f"drop {d['drop_pct']:.1f}%  @ ${d['price']:.2f}{dim_str}"
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Macro summary
# ---------------------------------------------------------------------------


async def _fetch_macro_summary(session: AsyncSession) -> list[dict]:
    """Fetch latest macro indicator values."""
    try:
        from ingestion.macro_data import get_latest_macro
        return await get_latest_macro(session)
    except Exception as exc:
        logger.warning("Macro summary fetch failed: %s", exc)
        return []


def _format_macro_summary(indicators: list[dict]) -> str:
    if not indicators:
        return "_No macro data available._\n"

    lines = []
    for ind in indicators:
        name = ind.get("series_name", ind.get("series_id", "?"))
        value = ind.get("value", 0)
        dt = ind.get("date", "?")
        # Format value based on series
        sid = ind.get("series_id", "")
        if sid == "CPIAUCSL":
            val_str = f"{value:,.1f}"
        elif sid in ("FEDFUNDS", "DGS10", "DGS2", "T10Y2Y", "UNRATE"):
            val_str = f"{value:.2f}%"
        else:
            val_str = f"{value:.2f}"
        lines.append(f"  {name:<25} {val_str:>10}  (as of {dt})")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Earnings summary
# ---------------------------------------------------------------------------


async def _fetch_earnings_summary(session: AsyncSession) -> dict:
    """Fetch recent earnings events + latest transcript analyses."""
    result: dict = {"events": [], "analyses": []}
    try:
        from core.models import EarningsEventDB, Ticker
        cutoff = date.today() - timedelta(days=7)
        ev_result = await session.execute(
            select(EarningsEventDB, Ticker.symbol)
            .join(Ticker, EarningsEventDB.ticker_id == Ticker.id)
            .where(
                EarningsEventDB.event_date >= cutoff,
                EarningsEventDB.eps_actual.isnot(None),
            )
            .order_by(desc(EarningsEventDB.event_date))
            .limit(10)
        )
        for ev, sym in ev_result.all():
            result["events"].append({
                "symbol": sym,
                "date": ev.event_date.isoformat() if ev.event_date else "?",
                "eps_surprise": ev.eps_surprise_pct,
                "rev_surprise": ev.rev_surprise_pct,
                "beat": ev.eps_actual >= ev.eps_estimate if ev.eps_actual is not None and ev.eps_estimate is not None else None,
            })
    except Exception as exc:
        logger.warning("Earnings events fetch failed: %s", exc)

    try:
        from core.models import EarningsAnalysis, EarningsTranscript, Ticker
        an_result = await session.execute(
            select(EarningsAnalysis, Ticker.symbol, EarningsTranscript.quarter, EarningsTranscript.fiscal_year)
            .join(EarningsTranscript, EarningsAnalysis.transcript_id == EarningsTranscript.id)
            .join(Ticker, EarningsTranscript.ticker_id == Ticker.id)
            .where(EarningsAnalysis.analyzed_at >= datetime.now(timezone.utc) - timedelta(days=14))
            .order_by(desc(EarningsAnalysis.analyzed_at))
            .limit(5)
        )
        for analysis, sym, q, fy in an_result.all():
            result["analyses"].append({
                "symbol": sym,
                "quarter": f"Q{q} FY{fy}",
                "tone": analysis.management_tone,
                "sentiment": analysis.overall_sentiment,
                "tone_vs_prior": analysis.tone_vs_prior,
                "summary": (analysis.summary or "")[:150],
            })
    except Exception as exc:
        logger.warning("Earnings analyses fetch failed: %s", exc)

    return result


def _format_earnings_summary(data: dict) -> str:
    events = data.get("events", [])
    analyses = data.get("analyses", [])
    if not events and not analyses:
        return "_No recent earnings data._\n"

    lines = []
    if events:
        lines.append("**Recent Earnings Results:**")
        for ev in events:
            icon = "✅" if ev.get("beat") else "❌" if ev.get("beat") is False else "❓"
            eps_str = f"EPS {ev['eps_surprise']:+.1f}%" if ev.get("eps_surprise") is not None else ""
            rev_str = f"Rev {ev['rev_surprise']:+.1f}%" if ev.get("rev_surprise") is not None else ""
            lines.append(f"  {icon} {ev['symbol']:<6} {ev['date']}  {eps_str}  {rev_str}")
        lines.append("")

    if analyses:
        lines.append("**Earnings Call Analysis:**")
        for a in analyses:
            tone_icon = {"confident": "💪", "optimistic": "☀️", "cautious": "⚠️", "defensive": "🛡️"}.get(
                a.get("tone", ""), "📊"
            )
            shift = a.get("tone_vs_prior", "stable")
            shift_icon = {"improving": "▲", "deteriorating": "▼"}.get(shift, "—")
            lines.append(
                f"  {tone_icon} {a['symbol']:<6} {a['quarter']}  "
                f"Tone: {a.get('tone', '?')} ({shift_icon})  "
                f"Sentiment: {a.get('sentiment', 0):+.2f}"
            )
            if a.get("summary"):
                lines.append(f"    {a['summary']}...")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Assemble the full briefing
# ---------------------------------------------------------------------------


def _header(for_date: date) -> str:
    date_str = for_date.strftime("%B %d, %Y").upper()
    title = f"  EDGEFINDER DAILY BRIEFING — {date_str}"
    bar = "═" * (len(title) + 2)
    return f"\n{bar}\n{title}\n{bar}\n"


async def generate_briefing(
    session: AsyncSession,
    for_date: date | None = None,
    is_weekly: bool = False,
) -> str:
    """
    Assemble the full Markdown briefing string.
    All sections are gracefully empty if data is absent.
    """
    for_date = for_date or date.today()

    # Market overview is network-only (yfinance) — run concurrently with DB queries
    market_task = asyncio.create_task(_fetch_market_overview())

    # DB queries must be sequential on a single session
    movers = await _fetch_watchlist_movers(session)
    alerts = await _fetch_recent_alerts(session)
    news = await _fetch_top_news(session)
    insider_buys = await _fetch_insider_buys(session)
    tech_signals = await _fetch_technical_signals(session)
    filing_drift = await _fetch_filing_drift(session)
    thesis_matches = await _fetch_thesis_matches(session)
    dip_scores = await _fetch_dip_scores(session)
    macro = await _fetch_macro_summary(session)
    earnings = await _fetch_earnings_summary(session)

    market = await market_task

    digest_type = "WEEKLY DIGEST" if is_weekly else "DAILY BRIEFING"
    date_str = for_date.strftime("%B %d, %Y").upper()
    title = f"  EDGEFINDER {digest_type} — {date_str}"
    bar = "═" * (len(title) + 2)

    sections = [
        f"\n{bar}",
        title,
        f"{bar}\n",

        "## 📊 MARKET OVERVIEW\n",
        _format_market_overview(market),

        "## 🏛️ MACRO SNAPSHOT\n",
        _format_macro_summary(macro),

        "## 📈 WATCHLIST MOVERS (5-DAY)\n",
        _format_movers(movers),

        "## 🔔 ALERTS (LAST 24H)\n",
        _format_alerts(alerts),

        "## 📰 TOP NEWS BY SENTIMENT\n",
        _format_news(news),

        "## 🏦 INSIDER BUYING (LAST 7 DAYS)\n",
        _format_insider_buys(insider_buys),

        "## ⚡ TECHNICAL SIGNALS\n",
        _format_technical_signals(tech_signals),

        "## 📋 10-K DRIFT (YoY)\n",
        _format_filing_drift(filing_drift),

        "## 🎯 THESIS MATCHES\n",
        _format_thesis_matches(thesis_matches),

        "## 💧 BUY-THE-DIP SCORES\n",
        _format_dip_scores(dip_scores),

        "## 🎙️ EARNINGS HIGHLIGHTS\n",
        _format_earnings_summary(earnings),

        "─" * 60,
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
        f"by EdgeFinder\n",
    ]

    return "\n".join(sections)


async def generate_and_send_briefing(
    session: AsyncSession,
    for_date: date | None = None,
    dry_run: bool = True,
    is_weekly: bool = False,
) -> dict:
    """
    Generate the briefing, store it in daily_briefings, and optionally deliver it.

    Returns:
        {"content_md": str, "delivered": dict[channel, bool] | None}
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from core.models import DailyBriefing

    for_date = for_date or date.today()

    content_md = await generate_briefing(session, for_date=for_date, is_weekly=is_weekly)

    # Upsert into daily_briefings (idempotent re-runs)
    existing = await session.execute(
        select(DailyBriefing).where(DailyBriefing.date == for_date)
    )
    briefing_row = existing.scalar_one_or_none()

    if briefing_row:
        briefing_row.content_md = content_md
    else:
        briefing_row = DailyBriefing(date=for_date, content_md=content_md)
        session.add(briefing_row)

    await session.flush()

    delivered = None
    if not dry_run:
        from alerts.delivery import deliver

        subject = f"EdgeFinder {'Weekly Digest' if is_weekly else 'Daily Briefing'} — {for_date.strftime('%b %d, %Y')}"
        delivered = await deliver(subject, content_md)

        briefing_row.delivered_at = datetime.now(timezone.utc)
        briefing_row.delivery_channels = [ch for ch, ok in delivered.items() if ok]

    # ── Edger synthesis: intelligence layer on top of raw data ──
    try:
        synthesis, lesson = await synthesize_briefing_with_edger(
            content_md, session
        )
        briefing_row.edger_synthesis = synthesis
        briefing_row.lesson_taught = lesson

        # Write to simulation_log so it appears in the agent feed
        from core.models import SimulationLog

        session.add(SimulationLog(
            agent_name="edge",
            event_type="DAILY_BRIEFING",
            event_data={
                "date": str(for_date),
                "lesson_taught": lesson,
                "synthesis_preview": synthesis[:300] if synthesis else None,
            },
        ))
    except Exception:
        logger.exception("Edger synthesis failed — raw briefing still saved")

    await session.commit()
    return {
        "content_md": content_md,
        "edger_synthesis": briefing_row.edger_synthesis,
        "delivered": delivered,
    }


# ---------------------------------------------------------------------------
# Edger synthesis — autonomous intelligence commentary
# ---------------------------------------------------------------------------


async def synthesize_briefing_with_edger(
    raw_briefing_md: str,
    session: AsyncSession,
) -> tuple[str, str | None]:
    """
    Have The Edger synthesize the raw daily briefing into intelligence.

    Returns (synthesis_text, concept_id_taught_or_None).
    """
    import anthropic

    from config.settings import settings

    if not settings.has_anthropic:
        logger.warning("No ANTHROPIC_API_KEY — skipping Edger synthesis")
        return ("", None)

    from chat.personas import PERSONAS

    edger = PERSONAS["edge"]

    # Pick an untaught concept to weave into the briefing
    concept = await _pick_briefing_concept(session)
    concept_instruction = ""
    if concept:
        concept_instruction = (
            f"\n\nToday's teaching concept: {concept[1]} — {concept[2]}. "
            f"Weave this into your synthesis naturally, grounded in today's data. "
            f"Don't announce it as a lesson. Just make it part of the story."
        )

    synthesis_prompt = (
        "You're writing today's daily briefing. The crew has gathered the raw "
        "data below. Your job: synthesize it into what actually matters. Lead "
        "with the single most important thing. Call out what changed or what's "
        "building. Flag anything that smells like a signal others will miss. "
        "Keep it under 500 words. This gets persisted — if someone reads it in "
        "30 days, it should still make sense."
        f"{concept_instruction}\n\n"
        f"--- RAW BRIEFING ---\n{raw_briefing_md[:12000]}"
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=edger.system_prompt,
        messages=[{"role": "user", "content": synthesis_prompt}],
    )
    synthesis = response.content[0].text

    # Record the lesson as taught so it won't repeat
    lesson_id = None
    if concept:
        from core.models import AgentMemory

        lesson_id = concept[0]
        session.add(AgentMemory(
            agent_name="edge",
            memory_type="lesson_taught",
            content=lesson_id,
            confidence=1.0,
            evidence={"source": "daily_briefing", "summary": concept[1]},
        ))

    return (synthesis, lesson_id)


async def _pick_briefing_concept(session: AsyncSession) -> tuple | None:
    """Pick an untaught concept from the library for the daily briefing."""
    from sqlalchemy import func as sa_func

    from core.models import AgentMemory

    # Get already-taught concept IDs
    result = await session.execute(
        select(AgentMemory.content).where(
            AgentMemory.agent_name == "edge",
            AgentMemory.memory_type == "lesson_taught",
        )
    )
    taught_ids = {r[0] for r in result.all()}

    # Import the concept library from tools
    from chat.tools import _CONCEPT_LIBRARY

    untaught = [c for c in _CONCEPT_LIBRARY if c[0] not in taught_ids]
    if not untaught:
        untaught = list(_CONCEPT_LIBRARY)  # cycle back

    return untaught[0] if untaught else None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    from core.database import AsyncSessionLocal

    parser = argparse.ArgumentParser(description="EdgeFinder Daily Briefing")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Print, don't deliver")
    parser.add_argument("--send", action="store_true", help="Deliver via configured channels")
    parser.add_argument("--date", help="Date YYYY-MM-DD (default: today)")
    parser.add_argument("--weekly", action="store_true", help="Generate weekly digest")
    args = parser.parse_args()

    dry_run = not args.send
    for_date = date.fromisoformat(args.date) if args.date else None

    async def _main():
        async with AsyncSessionLocal() as session:
            result = await generate_and_send_briefing(
                session,
                for_date=for_date,
                dry_run=dry_run,
                is_weekly=args.weekly,
            )
        print(result["content_md"])
        if result["delivered"]:
            print("\nDelivery results:", result["delivered"])

    logging.basicConfig(level=logging.WARNING)  # quiet for CLI
    asyncio.run(_main())
