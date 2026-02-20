"""
Unit tests for analysis/sector_rotation.py

Tests cover return computation, relative strength, momentum scoring,
regime detection, and full snapshot building.
"""

from __future__ import annotations

from datetime import UTC, date, timedelta

import numpy as np
import pandas as pd
import pytest

from analysis.sector_rotation import (
    SECTOR_ETFS,
    SectorRelativeStrength,
    SectorRotationSnapshot,
    build_sector_snapshot,
    compute_momentum_score,
    compute_return,
    compute_sector_relative_strength,
    compute_sector_returns,
    detect_regime,
    get_sector_for_ticker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_price_df(n: int = 300, start_price: float = 100.0, trend: float = 0.001) -> pd.DataFrame:
    """Build a synthetic price DataFrame."""
    np.random.seed(42)
    dates = []
    d = date(2023, 1, 2)
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    dates = dates[:n]

    closes = [start_price]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + trend + 0.01 * np.random.standard_normal()))

    return pd.DataFrame({"date": dates, "close": closes})


# ---------------------------------------------------------------------------
# compute_return
# ---------------------------------------------------------------------------


class TestComputeReturn:
    def test_positive_trend(self):
        """Uptrend series should give positive return."""
        prices = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        ret = compute_return(prices, lookback=5)
        assert ret is not None
        assert ret > 0

    def test_negative_trend(self):
        prices = pd.Series([100.0, 99.0, 98.0, 97.0, 96.0, 95.0])
        ret = compute_return(prices, lookback=5)
        assert ret is not None
        assert ret < 0

    def test_flat_series_returns_zero(self):
        prices = pd.Series([100.0] * 10)
        ret = compute_return(prices, lookback=5)
        assert ret == pytest.approx(0.0)

    def test_insufficient_data_returns_none(self):
        prices = pd.Series([100.0, 101.0])
        assert compute_return(prices, lookback=5) is None

    def test_exact_return(self):
        # 10% return over 1 period
        prices = pd.Series([100.0, 110.0])
        ret = compute_return(prices, lookback=1)
        assert ret == pytest.approx(0.10)

    def test_zero_start_price_returns_none(self):
        prices = pd.Series([0.0, 100.0])
        assert compute_return(prices, lookback=1) is None


# ---------------------------------------------------------------------------
# compute_sector_returns
# ---------------------------------------------------------------------------


class TestComputeSectorReturns:
    def test_returns_correct_lookbacks(self):
        df = _make_price_df(n=300)
        price_dfs = {"XLK": df}
        results = compute_sector_returns(price_dfs, lookbacks=[20, 65])
        assert "XLK" in results
        assert 20 in results["XLK"]
        assert 65 in results["XLK"]

    def test_empty_df_returns_none(self):
        results = compute_sector_returns({"XLK": pd.DataFrame()}, lookbacks=[20])
        assert results["XLK"][20] is None

    def test_no_close_column_returns_none(self):
        df = pd.DataFrame({"date": [date(2024, 1, 1)], "price": [100.0]})
        results = compute_sector_returns({"XLK": df}, lookbacks=[20])
        assert results["XLK"][20] is None

    def test_multiple_sectors(self):
        results = compute_sector_returns(
            {
                "XLK": _make_price_df(n=300, trend=0.002),  # outperforming
                "XLU": _make_price_df(n=300, trend=-0.001),  # underperforming
            },
            lookbacks=[20],
        )
        xlk_ret = results["XLK"][20]
        xlu_ret = results["XLU"][20]
        # XLK has positive trend, XLU negative → XLK > XLU
        if xlk_ret is not None and xlu_ret is not None:
            assert xlk_ret > xlu_ret


# ---------------------------------------------------------------------------
# compute_sector_relative_strength
# ---------------------------------------------------------------------------


class TestComputeSectorRelativeStrength:
    def test_positive_rs_when_outperforms_spy(self):
        sector_returns = {"XLK": {20: 0.05}}  # +5% vs SPY +2% → RS = +3%
        spy_returns = {20: 0.02}
        rs = compute_sector_relative_strength(sector_returns, spy_returns)
        assert rs["XLK"][20] == pytest.approx(0.03)

    def test_negative_rs_when_underperforms_spy(self):
        sector_returns = {"XLU": {20: 0.01}}
        spy_returns = {20: 0.05}
        rs = compute_sector_relative_strength(sector_returns, spy_returns)
        assert rs["XLU"][20] == pytest.approx(-0.04)

    def test_none_when_sector_return_is_none(self):
        sector_returns = {"XLK": {20: None}}
        spy_returns = {20: 0.02}
        rs = compute_sector_relative_strength(sector_returns, spy_returns)
        assert rs["XLK"][20] is None

    def test_none_when_spy_return_is_none(self):
        sector_returns = {"XLK": {20: 0.05}}
        spy_returns = {20: None}
        rs = compute_sector_relative_strength(sector_returns, spy_returns)
        assert rs["XLK"][20] is None


# ---------------------------------------------------------------------------
# compute_momentum_score
# ---------------------------------------------------------------------------


class TestComputeMomentumScore:
    def test_all_positive_rs_gives_positive_score(self):
        rs = {20: 0.03, 65: 0.02, 252: 0.01}
        score = compute_momentum_score(rs)
        assert score is not None
        assert score > 0

    def test_all_negative_rs_gives_negative_score(self):
        rs = {20: -0.03, 65: -0.02, 252: -0.01}
        score = compute_momentum_score(rs)
        assert score is not None
        assert score < 0

    def test_none_windows_handled(self):
        rs = {20: 0.05, 65: None, 252: None}
        score = compute_momentum_score(rs)
        # Only 20d window available → score uses 20d weight only
        assert score is not None

    def test_all_none_returns_none(self):
        rs = {20: None, 65: None, 252: None}
        score = compute_momentum_score(rs)
        assert score is None

    def test_custom_weights(self):
        rs = {20: 1.0, 65: 0.0}
        weights = {20: 1.0, 65: 0.0}
        score = compute_momentum_score(rs, weights=weights)
        assert score == pytest.approx(1.0)

    def test_weighted_average_correct(self):
        # 20d weight=0.5, 65d weight=0.3, 252d weight=0.2
        # RS: 20d=0.10, 65d=0.05, 252d=0.02
        rs = {20: 0.10, 65: 0.05, 252: 0.02}
        expected = (0.10 * 0.5 + 0.05 * 0.3 + 0.02 * 0.2) / (0.5 + 0.3 + 0.2)
        score = compute_momentum_score(rs)
        assert score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# detect_regime
# ---------------------------------------------------------------------------


class TestDetectRegime:
    def _make_snapshot(
        self,
        risk_on_score: float,
        risk_off_score: float,
    ) -> SectorRotationSnapshot:
        from analysis.sector_rotation import RISK_OFF_SECTORS, RISK_ON_SECTORS

        snapshot = SectorRotationSnapshot(as_of=__import__("datetime").datetime.now(UTC))
        sectors = []
        for symbol in list(RISK_ON_SECTORS)[:3]:
            s = SectorRelativeStrength(
                symbol=symbol,
                sector_name=SECTOR_ETFS.get(symbol, symbol),
                momentum_score=risk_on_score,
            )
            sectors.append(s)
        for symbol in list(RISK_OFF_SECTORS)[:3]:
            s = SectorRelativeStrength(
                symbol=symbol,
                sector_name=SECTOR_ETFS.get(symbol, symbol),
                momentum_score=risk_off_score,
            )
            sectors.append(s)
        snapshot.sectors = sectors
        return snapshot

    def test_risk_on_when_cyclicals_outperform(self):
        snapshot = self._make_snapshot(risk_on_score=0.05, risk_off_score=-0.02)
        regime = detect_regime(snapshot)
        assert regime == "risk_on"

    def test_risk_off_when_defensives_outperform(self):
        snapshot = self._make_snapshot(risk_on_score=-0.03, risk_off_score=0.04)
        regime = detect_regime(snapshot)
        assert regime == "risk_off"

    def test_neutral_when_balanced(self):
        snapshot = self._make_snapshot(risk_on_score=0.005, risk_off_score=0.003)
        regime = detect_regime(snapshot)
        assert regime == "neutral"

    def test_empty_snapshot_is_neutral(self):
        snapshot = SectorRotationSnapshot(as_of=__import__("datetime").datetime.now(UTC))
        assert detect_regime(snapshot) == "neutral"


# ---------------------------------------------------------------------------
# build_sector_snapshot (full pipeline)
# ---------------------------------------------------------------------------


class TestBuildSectorSnapshot:
    def _make_all_sector_dfs(self, n: int = 300) -> dict[str, pd.DataFrame]:
        """Build synthetic price DFs for all SPDR sectors."""
        result = {}
        trends = {
            "XLK": 0.002,
            "XLF": 0.001,
            "XLE": -0.001,
            "XLV": 0.0005,
            "XLI": 0.001,
            "XLU": -0.0005,
            "XLB": 0.0008,
            "XLRE": -0.0002,
            "XLC": 0.0015,
            "XLY": 0.0012,
            "XLP": 0.0003,
        }
        for symbol, trend in trends.items():
            result[symbol] = _make_price_df(n=n, trend=trend)
        return result

    def test_returns_snapshot_object(self):
        dfs = self._make_all_sector_dfs()
        spy = _make_price_df(n=300, trend=0.001)
        snapshot = build_sector_snapshot(dfs, spy_df=spy)
        assert isinstance(snapshot, SectorRotationSnapshot)

    def test_sectors_have_ranks(self):
        dfs = self._make_all_sector_dfs()
        spy = _make_price_df(n=300)
        snapshot = build_sector_snapshot(dfs, spy_df=spy)
        ranked = snapshot.ranked
        assert len(ranked) > 0
        for s in ranked:
            assert s.rank is not None

    def test_all_sectors_present(self):
        dfs = self._make_all_sector_dfs()
        spy = _make_price_df(n=300)
        snapshot = build_sector_snapshot(dfs, spy_df=spy)
        symbols_in_snapshot = {s.symbol for s in snapshot.sectors}
        for symbol in SECTOR_ETFS:
            assert symbol in symbols_in_snapshot

    def test_regime_is_valid(self):
        dfs = self._make_all_sector_dfs()
        spy = _make_price_df(n=300)
        snapshot = build_sector_snapshot(dfs, spy_df=spy)
        assert snapshot.regime in {"risk_on", "risk_off", "neutral"}

    def test_ranked_sorted_by_momentum(self):
        dfs = self._make_all_sector_dfs()
        spy = _make_price_df(n=300)
        snapshot = build_sector_snapshot(dfs, spy_df=spy)
        ranked = snapshot.ranked
        for i in range(len(ranked) - 1):
            assert ranked[i].momentum_score >= ranked[i + 1].momentum_score

    def test_spy_returns_populated(self):
        dfs = self._make_all_sector_dfs()
        spy = _make_price_df(n=300)
        snapshot = build_sector_snapshot(dfs, spy_df=spy)
        assert snapshot.spy_return_20d is not None

    def test_handles_missing_sector_data_gracefully(self):
        """Missing sectors should be absent from snapshot, not crash."""
        # Only provide a few sectors
        dfs = {
            "XLK": _make_price_df(n=300, trend=0.002),
            "XLU": _make_price_df(n=300, trend=-0.001),
        }
        spy = _make_price_df(n=300)
        snapshot = build_sector_snapshot(dfs, spy_df=spy)
        symbols = {s.symbol for s in snapshot.sectors}
        assert "XLK" in symbols
        assert "XLU" in symbols

    def test_no_spy_df_still_works(self):
        dfs = {"XLK": _make_price_df(n=300)}
        snapshot = build_sector_snapshot(dfs, spy_df=None)
        assert snapshot is not None
        assert snapshot.spy_return_20d is None


# ---------------------------------------------------------------------------
# get_sector_for_ticker
# ---------------------------------------------------------------------------


class TestGetSectorForTicker:
    def test_technology_maps_to_xlk(self):
        result = get_sector_for_ticker("Technology")
        assert result == "XLK"

    def test_financials_maps_to_xlf(self):
        result = get_sector_for_ticker("Financials")
        assert result == "XLF"

    def test_energy_maps_to_xle(self):
        result = get_sector_for_ticker("Energy")
        assert result == "XLE"

    def test_case_insensitive(self):
        result = get_sector_for_ticker("TECHNOLOGY")
        assert result == "XLK"

    def test_none_input_returns_none(self):
        assert get_sector_for_ticker(None) is None

    def test_unknown_sector_returns_none(self):
        assert get_sector_for_ticker("Cryptocurrency") is None

    def test_partial_match(self):
        # "Information Technology" should match "Technology"
        result = get_sector_for_ticker("Information Technology")
        assert result == "XLK"
