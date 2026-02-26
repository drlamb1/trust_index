"""
EdgeFinder — Paper Portfolio Manager

Manages simulated play-money positions linked to auto-generated theses.
Every action is logged to SimulationLog for full audit trail.

DISCLAIMER: All capital values are simulated. Zero real money at risk.
This exists purely for learning and thesis validation.

FEATURES:
  - Position entry/exit linked to SimulatedThesis
  - Automatic stop-loss and take-profit execution
  - Daily mark-to-market with P&L attribution by thesis
  - Portfolio-level risk metrics (sector concentration, beta)
  - Cash management (can't spend more than you have)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.models import (
    PaperPortfolio,
    PaperPosition,
    PriceBar,
    PositionSide,
    PositionStatus,
    SimEventType,
    SimulatedThesis,
    SimulationLog,
    Ticker,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Portfolio Management
# ---------------------------------------------------------------------------


async def get_or_create_portfolio(
    session: AsyncSession,
    name: str = "default",
) -> PaperPortfolio:
    """Get or create a paper portfolio by name.

    Default portfolio starts with $100,000 play-money capital.
    """
    result = await session.execute(
        select(PaperPortfolio).where(PaperPortfolio.name == name)
    )
    portfolio = result.scalar_one_or_none()

    if portfolio is None:
        capital = settings.simulation_initial_capital
        portfolio = PaperPortfolio(
            name=name,
            initial_capital=capital,
            current_value=capital,
            cash=capital,
            total_pnl=0.0,
            total_pnl_pct=0.0,
        )
        session.add(portfolio)
        await session.flush()
        logger.info("Created paper portfolio '%s' with $%.0f play-money", name, capital)

    return portfolio


async def count_open_positions(session: AsyncSession, portfolio_id: int) -> int:
    """Count currently open positions in a portfolio."""
    result = await session.execute(
        select(func.count(PaperPosition.id)).where(
            PaperPosition.portfolio_id == portfolio_id,
            PaperPosition.status == PositionStatus.OPEN.value,
        )
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Position Entry
# ---------------------------------------------------------------------------


async def open_position(
    session: AsyncSession,
    portfolio: PaperPortfolio,
    thesis: SimulatedThesis,
    ticker: Ticker,
    side: PositionSide,
    shares: int,
    price: float,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> PaperPosition | None:
    """Open a new paper position.

    Validates:
      - Sufficient cash for the position
      - Not exceeding max open positions
      - Positive share count and price

    Deducts cash, creates PaperPosition, logs to SimulationLog.

    Returns PaperPosition or None if validation fails.
    """
    if shares <= 0 or price <= 0:
        logger.warning("Invalid position: shares=%d price=%.2f", shares, price)
        return None

    # Check position limit
    open_count = await count_open_positions(session, portfolio.id)
    if open_count >= settings.simulation_max_open_positions:
        logger.warning("Max open positions (%d) reached", settings.simulation_max_open_positions)
        return None

    # Check cash
    notional = shares * price
    if notional > portfolio.cash:
        logger.warning("Insufficient cash: need $%.2f, have $%.2f", notional, portfolio.cash)
        return None

    # Set default stops if not provided
    if stop_loss is None:
        stop_loss = price * (1 - settings.simulation_default_stop_loss_pct / 100)
    if take_profit is None:
        take_profit = price * (1 + settings.simulation_default_take_profit_pct / 100)

    # Create position
    position = PaperPosition(
        portfolio_id=portfolio.id,
        thesis_id=thesis.id,
        ticker_id=ticker.id,
        side=side.value,
        entry_date=date.today(),
        entry_price=price,
        shares=shares,
        status=PositionStatus.OPEN.value,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )
    session.add(position)

    # Deduct cash
    portfolio.cash -= notional
    await session.flush()

    # Log the event
    log_entry = SimulationLog(
        thesis_id=thesis.id,
        agent_name="paper_portfolio",
        event_type=SimEventType.ENTRY.value,
        event_data={
            "position_id": position.id,
            "ticker": ticker.symbol,
            "side": side.value,
            "shares": shares,
            "entry_price": price,
            "notional": notional,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "cash_remaining": portfolio.cash,
            "disclaimer": "SIMULATED PLAY-MONEY POSITION",
        },
    )
    session.add(log_entry)

    logger.info(
        "Opened %s %d shares of %s @ $%.2f (thesis: %s) [PLAY MONEY]",
        side.value, shares, ticker.symbol, price, thesis.name,
    )

    return position


# ---------------------------------------------------------------------------
# Position Exit
# ---------------------------------------------------------------------------


async def close_position(
    session: AsyncSession,
    position: PaperPosition,
    price: float,
    reason: str,
) -> PaperPosition:
    """Close an open paper position.

    Computes P&L, credits cash back to portfolio, updates position status.
    Logs the event to SimulationLog.

    Args:
        position: The PaperPosition to close
        price: Exit price
        reason: Why closing (stop_loss, take_profit, signal, manual, etc.)

    Returns:
        Updated PaperPosition with P&L computed
    """
    if position.status != PositionStatus.OPEN.value:
        logger.warning("Position %d already closed", position.id)
        return position

    # Compute P&L
    if position.side == PositionSide.LONG.value:
        pnl = (price - position.entry_price) * position.shares
    else:
        pnl = (position.entry_price - price) * position.shares

    pnl_pct = pnl / (position.entry_price * position.shares)

    # Update position
    position.exit_date = date.today()
    position.exit_price = price
    position.pnl = pnl
    position.pnl_pct = pnl_pct
    position.status = (
        PositionStatus.STOPPED_OUT.value if reason in ("stop_loss", "take_profit")
        else PositionStatus.CLOSED.value
    )

    # Credit cash back (return original capital + P&L)
    result = await session.execute(
        select(PaperPortfolio).where(PaperPortfolio.id == position.portfolio_id)
    )
    portfolio = result.scalar_one()
    portfolio.cash += position.entry_price * position.shares + pnl

    # Log the event
    event_type = SimEventType.STOP_TRIGGERED.value if reason in ("stop_loss", "take_profit") else SimEventType.EXIT.value
    log_entry = SimulationLog(
        thesis_id=position.thesis_id,
        agent_name="paper_portfolio",
        event_type=event_type,
        event_data={
            "position_id": position.id,
            "exit_price": price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "reason": reason,
            "held_days": (position.exit_date - position.entry_date).days,
            "disclaimer": "SIMULATED PLAY-MONEY P&L",
        },
    )
    session.add(log_entry)

    logger.info(
        "Closed position %d: P&L=$%.2f (%.1f%%) reason=%s [PLAY MONEY]",
        position.id, pnl, pnl_pct * 100, reason,
    )

    return position


# ---------------------------------------------------------------------------
# Stop-Loss / Take-Profit Checks
# ---------------------------------------------------------------------------


async def check_stops(
    session: AsyncSession,
    portfolio: PaperPortfolio,
) -> list[PaperPosition]:
    """Check all open positions for stop-loss and take-profit triggers.

    Uses the latest PriceBar close for each ticker.
    Returns list of positions that were closed.
    """
    result = await session.execute(
        select(PaperPosition).where(
            PaperPosition.portfolio_id == portfolio.id,
            PaperPosition.status == PositionStatus.OPEN.value,
        )
    )
    open_positions = result.scalars().all()
    closed = []

    for pos in open_positions:
        # Get latest price
        price_result = await session.execute(
            select(PriceBar.close)
            .where(PriceBar.ticker_id == pos.ticker_id)
            .order_by(PriceBar.date.desc())
            .limit(1)
        )
        latest_price = price_result.scalar_one_or_none()
        if latest_price is None:
            continue

        current_price = float(latest_price)

        # Check stops
        if pos.side == PositionSide.LONG.value:
            if pos.stop_loss and current_price <= pos.stop_loss:
                await close_position(session, pos, current_price, "stop_loss")
                closed.append(pos)
            elif pos.take_profit and current_price >= pos.take_profit:
                await close_position(session, pos, current_price, "take_profit")
                closed.append(pos)
        else:  # short
            if pos.stop_loss and current_price >= pos.stop_loss:
                await close_position(session, pos, current_price, "stop_loss")
                closed.append(pos)
            elif pos.take_profit and current_price <= pos.take_profit:
                await close_position(session, pos, current_price, "take_profit")
                closed.append(pos)

    return closed


# ---------------------------------------------------------------------------
# Mark-to-Market
# ---------------------------------------------------------------------------


async def daily_mark_to_market(
    session: AsyncSession,
    portfolio: PaperPortfolio,
) -> dict:
    """Recompute portfolio value from current prices.

    Returns P&L attribution dict:
    {
        "total_value": float,
        "cash": float,
        "positions_value": float,
        "total_pnl": float,
        "total_pnl_pct": float,
        "by_thesis": {thesis_id: {"pnl": float, "pnl_pct": float, "positions": int}},
    }
    """
    result = await session.execute(
        select(PaperPosition).where(
            PaperPosition.portfolio_id == portfolio.id,
            PaperPosition.status == PositionStatus.OPEN.value,
        )
    )
    open_positions = result.scalars().all()

    positions_value = 0.0
    by_thesis: dict[int, dict] = {}

    for pos in open_positions:
        # Get latest price
        price_result = await session.execute(
            select(PriceBar.close)
            .where(PriceBar.ticker_id == pos.ticker_id)
            .order_by(PriceBar.date.desc())
            .limit(1)
        )
        latest_price = price_result.scalar_one_or_none()
        if latest_price is None:
            continue

        current_price = float(latest_price)
        pos_value = current_price * pos.shares
        positions_value += pos_value

        # P&L for this position
        if pos.side == PositionSide.LONG.value:
            unrealized_pnl = (current_price - pos.entry_price) * pos.shares
        else:
            unrealized_pnl = (pos.entry_price - current_price) * pos.shares

        tid = pos.thesis_id
        if tid not in by_thesis:
            by_thesis[tid] = {"pnl": 0.0, "positions": 0, "notional": 0.0}
        by_thesis[tid]["pnl"] += unrealized_pnl
        by_thesis[tid]["positions"] += 1
        by_thesis[tid]["notional"] += pos.entry_price * pos.shares

    # Also include realized P&L from closed positions
    closed_result = await session.execute(
        select(PaperPosition).where(
            PaperPosition.portfolio_id == portfolio.id,
            PaperPosition.status != PositionStatus.OPEN.value,
        )
    )
    for pos in closed_result.scalars().all():
        tid = pos.thesis_id
        if tid not in by_thesis:
            by_thesis[tid] = {"pnl": 0.0, "positions": 0, "notional": 0.0}
        by_thesis[tid]["pnl"] += pos.pnl or 0

    # Compute thesis P&L percentages
    for tid, data in by_thesis.items():
        if data["notional"] > 0:
            data["pnl_pct"] = data["pnl"] / data["notional"]
        else:
            data["pnl_pct"] = 0.0

    total_value = portfolio.cash + positions_value
    total_pnl = total_value - portfolio.initial_capital
    total_pnl_pct = total_pnl / portfolio.initial_capital if portfolio.initial_capital > 0 else 0.0

    # Update portfolio
    portfolio.current_value = total_value
    portfolio.total_pnl = total_pnl
    portfolio.total_pnl_pct = total_pnl_pct

    return {
        "total_value": total_value,
        "cash": portfolio.cash,
        "positions_value": positions_value,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "by_thesis": {str(k): v for k, v in by_thesis.items()},
        "open_positions": len(open_positions),
        "disclaimer": "ALL VALUES ARE SIMULATED PLAY-MONEY",
    }


# ---------------------------------------------------------------------------
# Portfolio Summary
# ---------------------------------------------------------------------------


async def portfolio_summary(
    session: AsyncSession,
    portfolio: PaperPortfolio,
) -> dict:
    """Full portfolio snapshot for dashboard/chat tools.

    Returns structured summary with positions, P&L, and thesis attribution.
    """
    # Mark-to-market
    mtm = await daily_mark_to_market(session, portfolio)

    # Open positions detail
    result = await session.execute(
        select(PaperPosition, Ticker.symbol, SimulatedThesis.name)
        .join(Ticker, PaperPosition.ticker_id == Ticker.id)
        .join(SimulatedThesis, PaperPosition.thesis_id == SimulatedThesis.id)
        .where(
            PaperPosition.portfolio_id == portfolio.id,
            PaperPosition.status == PositionStatus.OPEN.value,
        )
    )
    positions = []
    for pos, symbol, thesis_name in result:
        # Get current price for unrealized P&L
        price_result = await session.execute(
            select(PriceBar.close)
            .where(PriceBar.ticker_id == pos.ticker_id)
            .order_by(PriceBar.date.desc())
            .limit(1)
        )
        current_price = price_result.scalar_one_or_none()
        current_price = float(current_price) if current_price else pos.entry_price

        unrealized = (current_price - pos.entry_price) * pos.shares
        if pos.side == PositionSide.SHORT.value:
            unrealized = -unrealized

        positions.append({
            "id": pos.id,
            "ticker": symbol,
            "thesis": thesis_name,
            "side": pos.side,
            "shares": pos.shares,
            "entry_price": pos.entry_price,
            "current_price": current_price,
            "unrealized_pnl": unrealized,
            "unrealized_pnl_pct": unrealized / (pos.entry_price * pos.shares),
            "entry_date": pos.entry_date.isoformat(),
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
        })

    return {
        "portfolio_name": portfolio.name,
        "initial_capital": portfolio.initial_capital,
        **mtm,
        "positions": positions,
    }
