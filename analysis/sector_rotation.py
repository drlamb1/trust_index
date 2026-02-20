"""
EdgeFinder — Sector Rotation & Relative Strength (Phase 3)

Tracks money flows between sectors using SPDR sector ETFs as proxies.
Computes relative strength vs SPY over multiple lookback windows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SPDR sector ETF universe
# ---------------------------------------------------------------------------

SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
}

LOOKBACK_WINDOWS: list[int] = [20, 65, 252]  # ~1 month, ~1 quarter, ~1 year

# Risk-on ETFs: XLK, XLF, XLE, XLY, XLC
# Risk-off ETFs: XLU, XLP, XLRE, XLV
RISK_ON_SECTORS = {"XLK", "XLF", "XLE", "XLY", "XLC"}
RISK_OFF_SECTORS = {"XLU", "XLP", "XLRE", "XLV"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SectorRelativeStrength:
    """Relative strength for one sector ETF vs SPY."""

    symbol: str
    sector_name: str
    rs_20d: float | None = None  # return relative to SPY over 20 days
    rs_65d: float | None = None
    rs_252d: float | None = None
    momentum_score: float | None = None  # weighted composite
    rank: int | None = None  # 1=strongest, 11=weakest


@dataclass
class SectorRotationSnapshot:
    """Full sector rotation snapshot for a given date."""

    as_of: datetime
    spy_return_20d: float | None = None
    spy_return_65d: float | None = None
    spy_return_252d: float | None = None
    sectors: list[SectorRelativeStrength] = field(default_factory=list)
    regime: str = "neutral"  # "risk_on", "risk_off", "neutral"

    @property
    def ranked(self) -> list[SectorRelativeStrength]:
        """Sectors sorted by momentum score descending (strongest first)."""
        return sorted(
            [s for s in self.sectors if s.momentum_score is not None],
            key=lambda s: s.momentum_score,  # type: ignore
            reverse=True,
        )

    def get_sector(self, symbol: str) -> SectorRelativeStrength | None:
        upper = symbol.upper()
        for s in self.sectors:
            if s.symbol == upper:
                return s
        return None


# ---------------------------------------------------------------------------
# Return computation
# ---------------------------------------------------------------------------


def compute_return(prices: pd.Series, lookback: int) -> float | None:
    """Compute total return over the last *lookback* bars."""
    prices = prices.dropna()
    if len(prices) < lookback + 1:
        return None
    end_price = prices.iloc[-1]
    start_price = prices.iloc[-(lookback + 1)]
    if start_price == 0:
        return None
    return float((end_price - start_price) / start_price)


def compute_sector_returns(
    price_dfs: dict[str, pd.DataFrame],
    lookbacks: list[int] | None = None,
) -> dict[str, dict[int, float | None]]:
    """
    Compute raw returns for each sector ETF over multiple lookback windows.

    Args:
        price_dfs: mapping of symbol → DataFrame with [date, close]
        lookbacks: list of lookback periods in trading days

    Returns:
        {symbol: {lookback_days: return_or_None}}
    """
    if lookbacks is None:
        lookbacks = LOOKBACK_WINDOWS

    results: dict[str, dict[int, float | None]] = {}
    for symbol, df in price_dfs.items():
        if df is None or df.empty or "close" not in df.columns:
            results[symbol] = {lb: None for lb in lookbacks}
            continue

        df_sorted = df.sort_values("date").reset_index(drop=True)
        prices = df_sorted["close"]
        results[symbol] = {lb: compute_return(prices, lb) for lb in lookbacks}

    return results


def compute_sector_relative_strength(
    sector_returns: dict[str, dict[int, float | None]],
    spy_returns: dict[int, float | None],
) -> dict[str, dict[int, float | None]]:
    """
    Compute relative strength = sector_return - spy_return for each window.

    Returns:
        {symbol: {lookback_days: relative_strength_or_None}}
    """
    rs: dict[str, dict[int, float | None]] = {}
    for symbol, windows in sector_returns.items():
        rs[symbol] = {}
        for lb, sector_ret in windows.items():
            spy_ret = spy_returns.get(lb)
            if sector_ret is None or spy_ret is None:
                rs[symbol][lb] = None
            else:
                rs[symbol][lb] = sector_ret - spy_ret
    return rs


def compute_momentum_score(
    rs_by_window: dict[int, float | None],
    weights: dict[int, float] | None = None,
) -> float | None:
    """
    Weighted composite of relative strength across lookback windows.
    Default weights: 20d=0.5, 65d=0.3, 252d=0.2 (overweight near-term).
    """
    if weights is None:
        weights = {20: 0.5, 65: 0.3, 252: 0.2}

    total_weight = 0.0
    score = 0.0
    for lb, w in weights.items():
        rs = rs_by_window.get(lb)
        if rs is not None:
            score += rs * w
            total_weight += w

    if total_weight == 0:
        return None
    return score / total_weight


def detect_regime(
    snapshot: SectorRotationSnapshot,
) -> str:
    """
    Detect market regime based on relative strength of risk-on vs risk-off sectors.

    Returns: "risk_on", "risk_off", or "neutral"
    """
    risk_on_scores: list[float] = []
    risk_off_scores: list[float] = []

    for sector in snapshot.sectors:
        if sector.momentum_score is None:
            continue
        if sector.symbol in RISK_ON_SECTORS:
            risk_on_scores.append(sector.momentum_score)
        elif sector.symbol in RISK_OFF_SECTORS:
            risk_off_scores.append(sector.momentum_score)

    if not risk_on_scores or not risk_off_scores:
        return "neutral"

    avg_risk_on = sum(risk_on_scores) / len(risk_on_scores)
    avg_risk_off = sum(risk_off_scores) / len(risk_off_scores)

    diff = avg_risk_on - avg_risk_off

    if diff > 0.01:  # risk-on outperforming by >1%
        return "risk_on"
    elif diff < -0.01:  # risk-off outperforming by >1%
        return "risk_off"
    else:
        return "neutral"


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_sector_snapshot(
    sector_price_dfs: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame | None = None,
    lookbacks: list[int] | None = None,
    as_of: datetime | None = None,
) -> SectorRotationSnapshot:
    """
    Build a full SectorRotationSnapshot from price data.

    Args:
        sector_price_dfs: {symbol: DataFrame(date, close)} for each SPDR ETF
        spy_df: SPY price DataFrame (used as benchmark)
        lookbacks: lookback windows (default: [20, 65, 252])
        as_of: snapshot timestamp (default: now)

    Returns:
        SectorRotationSnapshot with ranked sectors and regime detection
    """
    if lookbacks is None:
        lookbacks = LOOKBACK_WINDOWS
    if as_of is None:
        as_of = datetime.now(UTC)

    # Compute SPY returns (benchmark)
    spy_returns: dict[int, float | None] = {lb: None for lb in lookbacks}
    if spy_df is not None and not spy_df.empty and "close" in spy_df.columns:
        spy_sorted = spy_df.sort_values("date").reset_index(drop=True)
        spy_prices = spy_sorted["close"]
        spy_returns = {lb: compute_return(spy_prices, lb) for lb in lookbacks}

    snapshot = SectorRotationSnapshot(
        as_of=as_of,
        spy_return_20d=spy_returns.get(20),
        spy_return_65d=spy_returns.get(65),
        spy_return_252d=spy_returns.get(252),
    )

    # Compute raw returns for each sector
    sector_returns = compute_sector_returns(sector_price_dfs, lookbacks=lookbacks)

    # Compute relative strength vs SPY
    rs_dict = compute_sector_relative_strength(sector_returns, spy_returns)

    # Build SectorRelativeStrength objects
    sectors: list[SectorRelativeStrength] = []
    for symbol in SECTOR_ETFS:
        if symbol not in sector_price_dfs:
            continue
        sector_name = SECTOR_ETFS[symbol]
        rs_windows = rs_dict.get(symbol, {})

        momentum = compute_momentum_score(rs_windows)
        sector = SectorRelativeStrength(
            symbol=symbol,
            sector_name=sector_name,
            rs_20d=rs_windows.get(20),
            rs_65d=rs_windows.get(65),
            rs_252d=rs_windows.get(252),
            momentum_score=momentum,
        )
        sectors.append(sector)

    # Assign ranks (1 = strongest)
    ranked = sorted(
        [s for s in sectors if s.momentum_score is not None],
        key=lambda s: s.momentum_score,  # type: ignore
        reverse=True,
    )
    for rank, s in enumerate(ranked, start=1):
        s.rank = rank

    # Sectors with no score get last rank
    unranked = [s for s in sectors if s.momentum_score is None]
    for s in unranked:
        s.rank = len(ranked) + 1

    snapshot.sectors = sectors

    # Detect regime
    snapshot.regime = detect_regime(snapshot)

    return snapshot


def get_sector_for_ticker(ticker_sector: str | None) -> str | None:
    """
    Map a ticker's sector string (from yfinance/Edgar) to the corresponding
    SPDR ETF symbol.

    Example: "Technology" → "XLK"
    """
    if not ticker_sector:
        return None
    lower = ticker_sector.lower()
    for symbol, name in SECTOR_ETFS.items():
        if name.lower() in lower or lower in name.lower():
            return symbol
    return None


async def fetch_sector_prices(
    lookback_days: int = 300,
) -> dict[str, pd.DataFrame]:
    """
    Fetch price data for all SPDR sector ETFs + SPY via yfinance.
    Returns {symbol: DataFrame(date, close)} or empty dict on failure.
    """
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        logger.error("yfinance not installed")
        return {}

    symbols = list(SECTOR_ETFS.keys()) + ["SPY"]
    period = f"{lookback_days}d"

    result: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            raw = yf.download(symbol, period=period, progress=False, auto_adjust=True)
            if raw.empty:
                logger.warning("No price data for %s", symbol)
                continue
            raw = raw.reset_index()
            # yfinance returns 'Date' or 'Datetime'
            date_col = "Date" if "Date" in raw.columns else "Datetime"
            df = raw[[date_col, "Close"]].copy()
            df.columns = ["date", "close"]
            df["date"] = pd.to_datetime(df["date"]).dt.date
            result[symbol] = df
        except Exception as exc:
            logger.warning("Price fetch error for %s: %s", symbol, exc)

    return result
