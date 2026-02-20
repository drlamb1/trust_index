"""
EdgeFinder — Earnings Calendar (Phase 3)

Fetches upcoming earnings dates, EPS estimates, and revenue estimates
from the Finnhub earnings calendar API.

No DB model — returns dataclasses only (earnings data is transient).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class EarningsEvent:
    """Earnings event for a single company on a single date."""

    symbol: str
    date: datetime
    hour: str  # "bmo" (before market open), "amc" (after market close), "dmh" (during market hours), ""
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None  # in millions USD
    revenue_actual: float | None = None  # in millions USD
    ticker_id: int | None = None

    @property
    def eps_surprise_pct(self) -> float | None:
        """EPS surprise as percentage: (actual - estimate) / |estimate| × 100."""
        if self.eps_actual is None or self.eps_estimate is None:
            return None
        if self.eps_estimate == 0:
            return None
        return (self.eps_actual - self.eps_estimate) / abs(self.eps_estimate) * 100.0

    @property
    def revenue_surprise_pct(self) -> float | None:
        """Revenue surprise as percentage."""
        if self.revenue_actual is None or self.revenue_estimate is None:
            return None
        if self.revenue_estimate == 0:
            return None
        return (self.revenue_actual - self.revenue_estimate) / abs(self.revenue_estimate) * 100.0

    @property
    def beat_eps(self) -> bool | None:
        """True if EPS beat, False if missed, None if unavailable."""
        if self.eps_actual is None or self.eps_estimate is None:
            return None
        return self.eps_actual >= self.eps_estimate


@dataclass
class EarningsCalendarResult:
    """Result container for a calendar fetch window."""

    from_date: datetime
    to_date: datetime
    events: list[EarningsEvent] = field(default_factory=list)

    @property
    def symbols(self) -> list[str]:
        return [e.symbol for e in self.events]

    def for_symbol(self, symbol: str) -> EarningsEvent | None:
        """Return the first matching event for a symbol."""
        upper = symbol.upper()
        for e in self.events:
            if e.symbol.upper() == upper:
                return e
        return None

    def upcoming(self, days: int = 7) -> list[EarningsEvent]:
        """Events within the next *days* days from now."""
        now = datetime.now(UTC)
        cutoff = now + timedelta(days=days)
        return [e for e in self.events if now <= e.date <= cutoff]


# ---------------------------------------------------------------------------
# Finnhub API client
# ---------------------------------------------------------------------------


def _parse_finnhub_event(item: dict[str, Any]) -> EarningsEvent | None:
    """Parse one Finnhub earningsCalendar entry into an EarningsEvent."""
    symbol = (item.get("symbol") or "").strip().upper()
    date_str = (item.get("date") or "").strip()
    if not symbol or not date_str:
        return None

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None

    def _float_or_none(v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # Revenue: Finnhub reports in millions
    rev_est = _float_or_none(item.get("revenueEstimate"))
    rev_act = _float_or_none(item.get("revenueActual"))

    return EarningsEvent(
        symbol=symbol,
        date=date,
        hour=item.get("hour", ""),
        eps_estimate=_float_or_none(item.get("epsEstimate")),
        eps_actual=_float_or_none(item.get("epsActual")),
        revenue_estimate=rev_est,
        revenue_actual=rev_act,
    )


async def fetch_earnings_calendar(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    api_key: str = "",
    symbols: list[str] | None = None,
) -> EarningsCalendarResult:
    """
    Fetch earnings calendar from Finnhub.

    Args:
        from_date: Start date (default: today)
        to_date: End date (default: today + 7 days)
        api_key: Finnhub API token
        symbols: If provided, filter results to only these symbols

    Returns:
        EarningsCalendarResult with parsed events
    """
    if from_date is None:
        from_date = datetime.now(UTC)
    if to_date is None:
        to_date = from_date + timedelta(days=7)

    result = EarningsCalendarResult(from_date=from_date, to_date=to_date)

    if not api_key:
        logger.warning("No Finnhub API key — earnings calendar unavailable")
        return result

    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {
        "from": from_date.strftime("%Y-%m-%d"),
        "to": to_date.strftime("%Y-%m-%d"),
        "token": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Finnhub earnings calendar error: %s", exc)
        return result

    symbol_set: set[str] | None = None
    if symbols:
        symbol_set = {s.upper() for s in symbols}

    for item in data.get("earningsCalendar", []):
        event = _parse_finnhub_event(item)
        if event is None:
            continue
        if symbol_set and event.symbol not in symbol_set:
            continue
        result.events.append(event)

    logger.info(
        "Fetched %d earnings events from %s to %s",
        len(result.events),
        from_date.strftime("%Y-%m-%d"),
        to_date.strftime("%Y-%m-%d"),
    )
    return result


async def fetch_earnings_for_tickers(
    symbols: list[str],
    api_key: str = "",
    lookback_days: int = 90,
    lookahead_days: int = 30,
) -> EarningsCalendarResult:
    """
    Fetch recent + upcoming earnings for a list of ticker symbols.
    Covers [today - lookback_days, today + lookahead_days].
    """
    now = datetime.now(UTC)
    return await fetch_earnings_calendar(
        from_date=now - timedelta(days=lookback_days),
        to_date=now + timedelta(days=lookahead_days),
        api_key=api_key,
        symbols=symbols,
    )


async def get_next_earnings(
    symbol: str,
    api_key: str = "",
    lookahead_days: int = 90,
) -> EarningsEvent | None:
    """
    Return the next upcoming earnings event for a single symbol, or None.
    """
    now = datetime.now(UTC)
    result = await fetch_earnings_calendar(
        from_date=now,
        to_date=now + timedelta(days=lookahead_days),
        api_key=api_key,
        symbols=[symbol],
    )
    upcoming = result.upcoming(days=lookahead_days)
    if not upcoming:
        return None
    # Sort by date ascending and return soonest
    return sorted(upcoming, key=lambda e: e.date)[0]
