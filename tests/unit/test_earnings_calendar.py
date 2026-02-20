"""
Unit tests for ingestion/earnings_calendar.py

Tests cover event parsing, EarningsCalendarResult operations,
and Finnhub API fetch (mocked).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ingestion.earnings_calendar import (
    EarningsCalendarResult,
    EarningsEvent,
    _parse_finnhub_event,
    fetch_earnings_calendar,
    get_next_earnings,
)

# ---------------------------------------------------------------------------
# EarningsEvent
# ---------------------------------------------------------------------------


class TestEarningsEvent:
    def _make_event(
        self,
        eps_estimate=1.0,
        eps_actual=1.2,
        rev_estimate=1000.0,
        rev_actual=1100.0,
        date_offset_days: int = 7,
    ) -> EarningsEvent:
        return EarningsEvent(
            symbol="AAPL",
            date=datetime.now(UTC) + timedelta(days=date_offset_days),
            hour="bmo",
            eps_estimate=eps_estimate,
            eps_actual=eps_actual,
            revenue_estimate=rev_estimate,
            revenue_actual=rev_actual,
        )

    def test_eps_surprise_pct_beat(self):
        ev = self._make_event(eps_estimate=1.0, eps_actual=1.2)
        assert ev.eps_surprise_pct == pytest.approx(20.0)

    def test_eps_surprise_pct_miss(self):
        ev = self._make_event(eps_estimate=1.0, eps_actual=0.8)
        assert ev.eps_surprise_pct == pytest.approx(-20.0)

    def test_eps_surprise_none_when_no_actual(self):
        ev = self._make_event(eps_estimate=1.0, eps_actual=None)
        assert ev.eps_surprise_pct is None

    def test_eps_surprise_none_when_no_estimate(self):
        ev = self._make_event(eps_estimate=None, eps_actual=1.0)
        assert ev.eps_surprise_pct is None

    def test_eps_surprise_none_when_estimate_is_zero(self):
        ev = self._make_event(eps_estimate=0.0, eps_actual=1.0)
        assert ev.eps_surprise_pct is None

    def test_revenue_surprise_pct(self):
        ev = self._make_event(rev_estimate=1000.0, rev_actual=1050.0)
        assert ev.revenue_surprise_pct == pytest.approx(5.0)

    def test_beat_eps_true(self):
        ev = self._make_event(eps_estimate=1.0, eps_actual=1.5)
        assert ev.beat_eps is True

    def test_beat_eps_false(self):
        ev = self._make_event(eps_estimate=1.0, eps_actual=0.9)
        assert ev.beat_eps is False

    def test_beat_eps_exactly_equal_is_true(self):
        ev = self._make_event(eps_estimate=1.0, eps_actual=1.0)
        assert ev.beat_eps is True

    def test_beat_eps_none_when_no_data(self):
        ev = self._make_event(eps_estimate=None, eps_actual=None)
        assert ev.beat_eps is None


# ---------------------------------------------------------------------------
# EarningsCalendarResult
# ---------------------------------------------------------------------------


class TestEarningsCalendarResult:
    def _make_result(self) -> EarningsCalendarResult:
        now = datetime.now(UTC)
        result = EarningsCalendarResult(from_date=now, to_date=now + timedelta(days=30))
        result.events = [
            EarningsEvent(symbol="AAPL", date=now + timedelta(days=3), hour="bmo"),
            EarningsEvent(symbol="MSFT", date=now + timedelta(days=10), hour="amc"),
            EarningsEvent(symbol="NVDA", date=now - timedelta(days=2), hour="bmo"),  # past
        ]
        return result

    def test_symbols_property(self):
        result = self._make_result()
        assert set(result.symbols) == {"AAPL", "MSFT", "NVDA"}

    def test_for_symbol_found(self):
        result = self._make_result()
        ev = result.for_symbol("AAPL")
        assert ev is not None
        assert ev.symbol == "AAPL"

    def test_for_symbol_not_found(self):
        result = self._make_result()
        assert result.for_symbol("TSLA") is None

    def test_for_symbol_case_insensitive(self):
        result = self._make_result()
        ev = result.for_symbol("aapl")
        assert ev is not None

    def test_upcoming_filters_past_events(self):
        result = self._make_result()
        upcoming = result.upcoming(days=30)
        symbols = {e.symbol for e in upcoming}
        # NVDA is in the past → should not appear
        assert "NVDA" not in symbols
        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_upcoming_respects_window(self):
        result = self._make_result()
        # Only events within next 5 days
        upcoming = result.upcoming(days=5)
        symbols = {e.symbol for e in upcoming}
        assert "AAPL" in symbols  # 3 days away
        assert "MSFT" not in symbols  # 10 days away

    def test_empty_events(self):
        now = datetime.now(UTC)
        result = EarningsCalendarResult(from_date=now, to_date=now + timedelta(days=7))
        assert result.symbols == []
        assert result.upcoming() == []


# ---------------------------------------------------------------------------
# _parse_finnhub_event
# ---------------------------------------------------------------------------


class TestParseFinnhubEvent:
    def test_parses_valid_event(self):
        item = {
            "symbol": "AAPL",
            "date": "2024-01-15",
            "hour": "bmo",
            "epsEstimate": 1.12,
            "epsActual": 1.18,
            "revenueEstimate": 119.5,
            "revenueActual": 122.0,
        }
        ev = _parse_finnhub_event(item)
        assert ev is not None
        assert ev.symbol == "AAPL"
        assert ev.eps_estimate == pytest.approx(1.12)
        assert ev.eps_actual == pytest.approx(1.18)
        assert ev.hour == "bmo"

    def test_returns_none_on_missing_symbol(self):
        item = {"date": "2024-01-15", "hour": "bmo", "epsEstimate": 1.0}
        assert _parse_finnhub_event(item) is None

    def test_returns_none_on_missing_date(self):
        item = {"symbol": "AAPL", "hour": "bmo", "epsEstimate": 1.0}
        assert _parse_finnhub_event(item) is None

    def test_returns_none_on_invalid_date(self):
        item = {"symbol": "AAPL", "date": "not-a-date", "hour": "bmo"}
        assert _parse_finnhub_event(item) is None

    def test_handles_null_estimates(self):
        item = {
            "symbol": "NVDA",
            "date": "2024-03-20",
            "hour": "amc",
            "epsEstimate": None,
            "epsActual": None,
        }
        ev = _parse_finnhub_event(item)
        assert ev is not None
        assert ev.eps_estimate is None
        assert ev.eps_actual is None

    def test_symbol_uppercased(self):
        item = {"symbol": "aapl", "date": "2024-01-15", "hour": ""}
        ev = _parse_finnhub_event(item)
        assert ev is not None
        assert ev.symbol == "AAPL"

    def test_date_timezone_aware(self):
        item = {"symbol": "AAPL", "date": "2024-06-15", "hour": "bmo"}
        ev = _parse_finnhub_event(item)
        assert ev is not None
        assert ev.date.tzinfo is not None


# ---------------------------------------------------------------------------
# fetch_earnings_calendar (mocked httpx)
# ---------------------------------------------------------------------------


class TestFetchEarningsCalendar:
    @pytest.mark.asyncio
    async def test_returns_empty_without_api_key(self):
        result = await fetch_earnings_calendar(api_key="")
        assert result.events == []

    @pytest.mark.asyncio
    async def test_parses_api_response(self, httpx_mock):
        httpx_mock.add_response(
            url=__import__("re").compile(r"https://finnhub.io/api/v1/calendar/earnings.*"),
            json={
                "earningsCalendar": [
                    {
                        "symbol": "AAPL",
                        "date": "2024-01-15",
                        "hour": "bmo",
                        "epsEstimate": 1.12,
                        "epsActual": None,
                    },
                    {
                        "symbol": "MSFT",
                        "date": "2024-01-22",
                        "hour": "amc",
                        "epsEstimate": 2.75,
                        "epsActual": None,
                    },
                ]
            },
        )
        result = await fetch_earnings_calendar(api_key="test-key")  # pragma: allowlist secret
        assert len(result.events) == 2
        symbols = {e.symbol for e in result.events}
        assert symbols == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_filters_by_symbols(self, httpx_mock):
        httpx_mock.add_response(
            url=__import__("re").compile(r"https://finnhub.io/api/v1/calendar/earnings.*"),
            json={
                "earningsCalendar": [
                    {"symbol": "AAPL", "date": "2024-01-15", "hour": "bmo"},
                    {"symbol": "MSFT", "date": "2024-01-22", "hour": "amc"},
                    {"symbol": "NVDA", "date": "2024-01-29", "hour": "bmo"},
                ]
            },
        )
        result = await fetch_earnings_calendar(api_key="test-key", symbols=["AAPL", "NVDA"])
        symbols = {e.symbol for e in result.events}
        assert "AAPL" in symbols
        assert "NVDA" in symbols
        assert "MSFT" not in symbols

    @pytest.mark.asyncio
    async def test_handles_http_error_gracefully(self, httpx_mock):
        httpx_mock.add_response(
            url=__import__("re").compile(r"https://finnhub.io/api/v1/calendar/earnings.*"),
            status_code=403,
        )
        result = await fetch_earnings_calendar(api_key="test-key")  # pragma: allowlist secret
        assert result.events == []

    @pytest.mark.asyncio
    async def test_skips_invalid_events(self, httpx_mock):
        httpx_mock.add_response(
            url=__import__("re").compile(r"https://finnhub.io/api/v1/calendar/earnings.*"),
            json={
                "earningsCalendar": [
                    {"symbol": "", "date": "2024-01-15"},  # missing symbol
                    {"symbol": "AAPL", "date": "bad-date"},  # invalid date
                    {"symbol": "NVDA", "date": "2024-02-20", "hour": "bmo"},  # valid
                ]
            },
        )
        result = await fetch_earnings_calendar(api_key="test-key")  # pragma: allowlist secret
        assert len(result.events) == 1
        assert result.events[0].symbol == "NVDA"


# ---------------------------------------------------------------------------
# get_next_earnings
# ---------------------------------------------------------------------------


class TestGetNextEarnings:
    @pytest.mark.asyncio
    async def test_returns_none_without_api_key(self):
        result = await get_next_earnings("AAPL", api_key="")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_soonest_event(self, httpx_mock):
        now = datetime.now(UTC)
        future1 = (now + timedelta(days=10)).strftime("%Y-%m-%d")
        future2 = (now + timedelta(days=30)).strftime("%Y-%m-%d")

        httpx_mock.add_response(
            url=__import__("re").compile(r"https://finnhub.io/api/v1/calendar/earnings.*"),
            json={
                "earningsCalendar": [
                    {"symbol": "AAPL", "date": future2, "hour": "bmo"},
                    {"symbol": "AAPL", "date": future1, "hour": "amc"},
                ]
            },
        )
        result = await get_next_earnings("AAPL", api_key="test-key", lookahead_days=90)
        assert result is not None
        # Should return the SOONER event
        assert result.date.strftime("%Y-%m-%d") == future1

    @pytest.mark.asyncio
    async def test_returns_none_when_no_events(self, httpx_mock):
        httpx_mock.add_response(
            url=__import__("re").compile(r"https://finnhub.io/api/v1/calendar/earnings.*"),
            json={"earningsCalendar": []},
        )
        result = await get_next_earnings("AAPL", api_key="test-key")  # pragma: allowlist secret
        assert result is None
