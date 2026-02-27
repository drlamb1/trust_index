"""
EdgeFinder — Walk-Forward Backtesting Engine

Test your theses against history — with mathematical honesty.

CRITICAL PRINCIPLE: No look-ahead bias.
  Every signal, metric, and decision in the backtest uses ONLY data that
  was available on that date. Filing dates (not period dates), news
  published_at (not ingested_at), prices at close (not intraday).

  If you violate this, your backtest is fiction. And not the good kind.

KEY METRICS:
  Sharpe Ratio  — return per unit of risk (risk-adjusted performance)
  Sortino Ratio — like Sharpe but only penalizes downside volatility
  Max Drawdown  — worst peak-to-trough decline (the "puke point")
  Win Rate      — fraction of trades that are profitable
  Profit Factor — gross profit / gross loss (>1 = net profitable)
  Expectancy    — average P&L per trade (the "edge" in dollars)

MONTE CARLO PERMUTATION TEST:
  Shuffle daily returns, recompute Sharpe. Repeat 10,000 times.
  p-value = fraction of permuted Sharpes ≥ observed Sharpe.
  If p < 0.05, your edge is likely real. Otherwise, you got lucky.
  This is the single most important statistical test in quant finance.

All P&L is simulated. Zero real capital.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import BacktestRun, PriceBar, SimulatedThesis

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class BacktestConfig:
    """Configuration for a walk-forward backtest.

    Attributes:
        start_date: Backtest start (inclusive)
        end_date: Backtest end (inclusive)
        initial_capital: Starting play-money capital
        commission_pct: Round-trip commission (10 bps default)
        slippage_pct: Slippage per trade (5 bps default)
        max_position_pct: Max position size as fraction of capital
        stop_loss_pct: Stop-loss trigger (8% default)
        take_profit_pct: Take-profit trigger (20% default)
    """

    start_date: date
    end_date: date
    initial_capital: float = 100_000.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005
    max_position_pct: float = 0.10
    stop_loss_pct: float = 0.08
    take_profit_pct: float = 0.20

    def to_dict(self) -> dict:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "initial_capital": self.initial_capital,
            "commission_pct": self.commission_pct,
            "slippage_pct": self.slippage_pct,
            "max_position_pct": self.max_position_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }


@dataclass
class Trade:
    """Record of a completed trade."""

    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: int
    side: str  # "long" or "short"
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # "stop_loss", "take_profit", "signal", "end_of_backtest"


# ---------------------------------------------------------------------------
# Core Backtesting Logic
# ---------------------------------------------------------------------------


async def load_price_data(
    session: AsyncSession,
    ticker_id: int,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Load historical price bars for backtesting.

    Returns DataFrame indexed by date with OHLCV columns.
    """
    result = await session.execute(
        select(PriceBar)
        .where(
            PriceBar.ticker_id == ticker_id,
            PriceBar.date >= start_date,
            PriceBar.date <= end_date,
        )
        .order_by(PriceBar.date)
    )
    bars = result.scalars().all()

    if not bars:
        return pd.DataFrame()

    data = [{
        "date": bar.date,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "adj_close": bar.adj_close or bar.close,
        "volume": bar.volume,
    } for bar in bars]

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


def _compute_position_size(
    capital: float, price: float, config: BacktestConfig,
) -> int:
    """Compute number of shares for a position.

    Respects max_position_pct limit.
    """
    max_notional = capital * config.max_position_pct
    shares = int(max_notional / price)
    return max(shares, 0)


def run_backtest_sync(
    prices: pd.DataFrame,
    config: BacktestConfig,
    entry_signal_fn=None,
    exit_signal_fn=None,
) -> tuple[list[Trade], pd.Series]:
    """Execute a walk-forward backtest on price data.

    This is the synchronous core — no DB access. Pure function on DataFrames.

    If no signal functions are provided, uses a simple momentum strategy:
      Entry: 5-day return > 0 (momentum)
      Exit: stop-loss, take-profit, or signal reversal

    Args:
        prices: DataFrame with 'close' column, indexed by date
        config: BacktestConfig
        entry_signal_fn: callable(prices_up_to_today) -> bool
        exit_signal_fn: callable(prices_up_to_today, entry_price) -> bool

    Returns:
        (trades, daily_returns) — list of Trade objects and daily return series
    """
    if prices.empty or len(prices) < 5:
        return [], pd.Series(dtype=float)

    trades: list[Trade] = []
    capital = config.initial_capital
    position: dict | None = None  # {entry_date, entry_price, shares, side}
    daily_values = []

    for i, (dt, row) in enumerate(prices.iterrows()):
        today_price = row["close"]
        dt_date = dt.date() if hasattr(dt, "date") else dt

        # Point-in-time: only use data up to today
        prices_to_today = prices.iloc[: i + 1]

        if position is not None:
            # Check stops
            entry_price = position["entry_price"]
            pnl_pct = (today_price - entry_price) / entry_price
            if position["side"] == "short":
                pnl_pct = -pnl_pct

            exit_reason = None
            if pnl_pct <= -config.stop_loss_pct:
                exit_reason = "stop_loss"
            elif pnl_pct >= config.take_profit_pct:
                exit_reason = "take_profit"
            elif exit_signal_fn and exit_signal_fn(prices_to_today, entry_price):
                exit_reason = "signal"

            if exit_reason:
                # Close position
                exit_price = today_price * (1 - config.slippage_pct)
                shares = position["shares"]
                if position["side"] == "long":
                    trade_pnl = (exit_price - entry_price) * shares
                else:
                    trade_pnl = (entry_price - exit_price) * shares
                commission = (entry_price + exit_price) * shares * config.commission_pct
                trade_pnl -= commission

                capital += trade_pnl + entry_price * shares  # return capital

                trades.append(Trade(
                    entry_date=position["entry_date"],
                    exit_date=dt_date,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    shares=shares,
                    side=position["side"],
                    pnl=trade_pnl,
                    pnl_pct=trade_pnl / (entry_price * shares),
                    exit_reason=exit_reason,
                ))
                position = None

        if position is None and i >= 5:
            # Check for entry signal
            should_enter = False
            if entry_signal_fn:
                should_enter = entry_signal_fn(prices_to_today)
            else:
                # Default: momentum — 5-day return positive
                ret_5d = (today_price - prices.iloc[i - 5]["close"]) / prices.iloc[i - 5]["close"]
                should_enter = ret_5d > 0

            if should_enter:
                entry_price = today_price * (1 + config.slippage_pct)
                shares = _compute_position_size(capital, entry_price, config)
                if shares > 0:
                    capital -= entry_price * shares  # deploy capital
                    position = {
                        "entry_date": dt_date,
                        "entry_price": entry_price,
                        "shares": shares,
                        "side": "long",
                    }

        # Track daily portfolio value
        pos_value = 0
        if position is not None:
            pos_value = today_price * position["shares"]
        daily_values.append(capital + pos_value)

    # Close any open position at end
    if position is not None:
        last_price = prices.iloc[-1]["close"]
        shares = position["shares"]
        trade_pnl = (last_price - position["entry_price"]) * shares
        commission = (position["entry_price"] + last_price) * shares * config.commission_pct
        trade_pnl -= commission

        trades.append(Trade(
            entry_date=position["entry_date"],
            exit_date=prices.index[-1].date() if hasattr(prices.index[-1], "date") else prices.index[-1],
            entry_price=position["entry_price"],
            exit_price=last_price,
            shares=shares,
            side=position["side"],
            pnl=trade_pnl,
            pnl_pct=trade_pnl / (position["entry_price"] * shares),
            exit_reason="end_of_backtest",
        ))

    # Compute daily returns
    values = pd.Series(daily_values, index=prices.index)
    daily_returns = values.pct_change().dropna()

    return trades, daily_returns


# ---------------------------------------------------------------------------
# Performance Metrics
# ---------------------------------------------------------------------------


def compute_backtest_metrics(
    trades: list[Trade],
    daily_returns: pd.Series,
    risk_free_rate: float = 0.05,
) -> dict:
    """Compute standard quant performance metrics.

    MATH:
      Sharpe = (μ - r_f) / σ · √252
        where μ = annualized mean return, r_f = risk-free rate, σ = annualized vol
        √252 annualizes from daily to yearly

      Sortino = (μ - r_f) / σ_down · √252
        σ_down = std of NEGATIVE returns only
        Better than Sharpe because it doesn't penalize upside volatility

      Max Drawdown = max over t of (peak_t - trough_t) / peak_t
        The worst loss from any peak — this is what keeps you up at night

      Profit Factor = Σ(winning trades) / Σ(losing trades)
        >1 means net profitable, >2 means strong, >3 means exceptional

      Expectancy = (win_rate × avg_win) - (loss_rate × avg_loss)
        The average $ you make per trade — your per-trade edge
    """
    if not trades and daily_returns.empty:
        return {
            "sharpe": None, "sortino": None, "max_drawdown": None,
            "win_rate": None, "profit_factor": None, "expectancy": None,
            "total_trades": 0, "total_pnl": 0.0,
        }

    total_pnl = sum(t.pnl for t in trades)
    total_trades = len(trades)

    # Win rate
    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]
    win_rate = len(winners) / total_trades if total_trades > 0 else 0

    # Profit factor
    gross_profit = sum(t.pnl for t in winners) if winners else 0
    gross_loss = abs(sum(t.pnl for t in losers)) if losers else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    # Expectancy
    avg_win = gross_profit / len(winners) if winners else 0
    avg_loss = gross_loss / len(losers) if losers else 0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    # Daily return metrics
    sharpe = None
    sortino = None
    max_drawdown = None

    if not daily_returns.empty and len(daily_returns) > 5:
        mean_daily = float(daily_returns.mean())
        std_daily = float(daily_returns.std())
        rfr_daily = risk_free_rate / 252

        # Sharpe
        if std_daily > 0:
            sharpe = (mean_daily - rfr_daily) / std_daily * math.sqrt(252)

        # Sortino — target downside deviation over ALL periods (not conditional std
        # of negative periods). Correct formula: sqrt(mean of squared negative
        # excess returns), denominator includes zero-return days. Ref: Sortino &
        # Price (1994). Using conditional std overestimates the denominator and
        # systematically underestimates the Sortino ratio.
        excess_returns = daily_returns - rfr_daily
        downside_sq = np.minimum(excess_returns, 0.0) ** 2
        downside_dev = math.sqrt(float(downside_sq.mean()))
        if downside_dev > 0:
            sortino = (mean_daily - rfr_daily) / downside_dev * math.sqrt(252)

        # Max drawdown
        cumulative = (1 + daily_returns).cumprod()
        peak = cumulative.cummax()
        drawdown = (cumulative - peak) / peak
        max_drawdown = float(drawdown.min())

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "total_trades": total_trades,
        "total_pnl": total_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }


# ---------------------------------------------------------------------------
# Monte Carlo Permutation Test
# ---------------------------------------------------------------------------


def monte_carlo_permutation_test(
    daily_returns: pd.Series | np.ndarray,
    n_perms: int = 10_000,
    risk_free_rate: float = 0.05,
    seed: int | None = None,
) -> float:
    """Test whether the observed Sharpe ratio is distinguishable from chance.

    Uses a stationary block bootstrap (Politis & Romano 1994) rather than
    a naive permutation. Naive permutation of returns preserves the sample
    mean and variance exactly — every permuted Sharpe equals the observed
    Sharpe, giving zero statistical power. Block bootstrap resamples with
    replacement, so each bootstrap draw has a different mean and variance,
    producing a non-degenerate null distribution.

    ALGORITHM:
      1. Compute observed Sharpe from actual daily returns
      2. Resample overlapping blocks of size `block_size` with replacement
         to form a bootstrap return series of the same length
      3. Compute Sharpe on each bootstrap draw — repeat N times
      4. p-value = fraction of bootstrap Sharpes ≥ observed Sharpe

    INTERPRETATION:
      p < 0.01  → very strong evidence of real edge
      p < 0.05  → statistically significant edge
      p < 0.10  → suggestive but not conclusive
      p ≥ 0.10  → can't distinguish from luck

    WHY BLOCK BOOTSTRAP:
      Sampling blocks (not individual days) preserves the serial correlation
      structure of the return series, so the null distribution respects
      realistic return dynamics rather than assuming i.i.d. returns.

    Args:
        daily_returns: Series or array of daily portfolio returns
        n_perms: Number of bootstrap draws (10,000 is standard)
        risk_free_rate: Annual risk-free rate
        seed: Random seed for reproducibility

    Returns:
        p-value (0 to 1)
    """
    rng = np.random.default_rng(seed)
    returns = np.array(daily_returns, dtype=float)
    n = len(returns)

    if n < 10:
        return 1.0

    rfr_daily = risk_free_rate / 252
    std = np.std(returns, ddof=1)
    if std == 0:
        return 1.0

    observed_sharpe = (np.mean(returns) - rfr_daily) / std * np.sqrt(252)

    # Build overlapping blocks (~2 trading weeks preserves weekly autocorrelation)
    block_size = 10
    blocks = [returns[i : i + block_size] for i in range(n - block_size + 1)]
    n_blocks_needed = math.ceil(n / block_size)

    count_gte = 0
    for _ in range(n_perms):
        idxs = rng.integers(0, len(blocks), size=n_blocks_needed)
        boot = np.concatenate([blocks[i] for i in idxs])[:n]
        boot_std = np.std(boot, ddof=1)
        if boot_std > 0:
            boot_sharpe = (np.mean(boot) - rfr_daily) / boot_std * np.sqrt(252)
            if boot_sharpe >= observed_sharpe:
                count_gte += 1

    return count_gte / n_perms


# ---------------------------------------------------------------------------
# Full Backtest Pipeline (with DB)
# ---------------------------------------------------------------------------


async def run_backtest(
    session: AsyncSession,
    thesis: SimulatedThesis,
    ticker_id: int,
    config: BacktestConfig,
) -> BacktestRun:
    """Run a full backtest and persist results.

    Loads price data, executes the backtest, computes metrics,
    runs Monte Carlo significance test, and stores a BacktestRun record.

    Returns the persisted BacktestRun.
    """
    prices = await load_price_data(session, ticker_id, config.start_date, config.end_date)

    if prices.empty:
        logger.warning("No price data for ticker_id=%d in [%s, %s]", ticker_id, config.start_date, config.end_date)
        backtest_run = BacktestRun(
            thesis_id=thesis.id,
            ticker_id=ticker_id,
            start_date=config.start_date,
            end_date=config.end_date,
            initial_capital=config.initial_capital,
            final_capital=config.initial_capital,
            total_trades=0,
            config=config.to_dict(),
            results_detail={"error": "No price data available"},
        )
        session.add(backtest_run)
        return backtest_run

    trades, daily_returns = run_backtest_sync(prices, config)
    metrics = compute_backtest_metrics(trades, daily_returns)

    # Monte Carlo significance test
    mc_p_value = None
    if not daily_returns.empty and len(daily_returns) > 20:
        mc_p_value = monte_carlo_permutation_test(daily_returns, n_perms=5000)

    final_capital = config.initial_capital + metrics["total_pnl"]

    # Build trade detail for storage
    trade_details = [
        {
            "entry_date": t.entry_date.isoformat(),
            "exit_date": t.exit_date.isoformat(),
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "shares": t.shares,
            "side": t.side,
            "pnl": t.pnl,
            "pnl_pct": t.pnl_pct,
            "exit_reason": t.exit_reason,
        }
        for t in trades
    ]

    backtest_run = BacktestRun(
        thesis_id=thesis.id,
        ticker_id=ticker_id,
        start_date=config.start_date,
        end_date=config.end_date,
        initial_capital=config.initial_capital,
        final_capital=final_capital,
        sharpe=metrics["sharpe"],
        sortino=metrics["sortino"],
        max_drawdown=metrics["max_drawdown"],
        win_rate=metrics["win_rate"],
        profit_factor=metrics["profit_factor"],
        expectancy=metrics["expectancy"],
        total_trades=metrics["total_trades"],
        monte_carlo_p_value=mc_p_value,
        config=config.to_dict(),
        results_detail={
            "trades": trade_details,
            "gross_profit": metrics["gross_profit"],
            "gross_loss": metrics["gross_loss"],
        },
    )
    session.add(backtest_run)

    logger.info(
        "Backtest complete: thesis=%d ticker=%d trades=%d Sharpe=%.2f p=%.3f",
        thesis.id, ticker_id, len(trades),
        metrics["sharpe"] or 0, mc_p_value or 1.0,
    )

    return backtest_run
