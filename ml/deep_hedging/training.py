"""Deep Hedging Training Pipeline — runs locally, never on Railway.

Trains a feedforward policy network (Buehler et al. 2019) to hedge a
European call option under the Heston stochastic volatility model. The
objective is to minimize the negative CVaR (Conditional Value at Risk)
of the hedging P&L at the alpha=0.05 level, penalizing the worst 5%
of terminal outcomes.

ALGORITHM (REINFORCE-style policy gradient on CVaR):
    1. Query the most recent HestonCalibration from Postgres for market-
       realistic parameters (v0, kappa, theta, sigma_v, rho).
    2. Generate n_paths Heston Monte Carlo paths via the QE scheme
       (Andersen 2008) from simulation/heston.py.
    3. For each epoch:
       a. Roll out the policy across all paths, collecting deltas and
          transaction costs at each time step.
       b. Compute terminal P&L for every path: option_payoff - hedge_pnl - costs.
       c. Compute CVaR_alpha as the mean of the worst alpha fraction of P&Ls.
       d. Backpropagate through -CVaR (we MAXIMIZE CVaR, i.e., minimize tail losses).
    4. Export trained weights as .npz bytes for storage in ml_models table.

TRAINING DETAILS:
    - Optimizer: Adam (lr=1e-3) with gradient clipping at norm 1.0
    - Batch processing: all paths evaluated in parallel per epoch (no mini-batching
      across paths -- the full path must be rolled forward sequentially)
    - Transaction cost: 10 bps per unit delta traded (κ = 0.001)
    - Early stopping not used: CVaR landscape is noisy; fixed epoch budget is more
      robust for policy gradient methods (Henderson et al. 2018)

KNOWN BUG (fixed in this file):
    The original DeepHedgingEnv.step() has: delta_change = abs(action_delta - action_delta)
    which always yields 0. The correct computation is abs(action_delta - self._prev_delta).
    This training loop tracks prev_delta explicitly and computes costs correctly.

Usage:
    python -m ml.deep_hedging.training                  # from DB calibration
    python -m ml.deep_hedging.training --n-epochs 500   # override epochs
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from typing import Any

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

N_PATHS = 10_000
N_STEPS = 252  # daily steps for 1 year
N_EPOCHS = 200
BATCH_SIZE = 256  # unused for full-path rollouts, reserved for future mini-batch variant
LEARNING_RATE = 1e-3
ALPHA = 0.05  # CVaR tail probability
TRANSACTION_COST = 0.001  # 10 bps per unit traded
STRIKE_MONEYNESS = 1.0  # ATM option
RISK_FREE_RATE_DEFAULT = 0.05


# ---------------------------------------------------------------------------
# Core training function (async -- queries DB for calibration)
# ---------------------------------------------------------------------------


async def train_deep_hedging_model(
    session: Any,
    *,
    n_paths: int = N_PATHS,
    n_steps: int = N_STEPS,
    n_epochs: int = N_EPOCHS,
    lr: float = LEARNING_RATE,
    alpha: float = ALPHA,
    transaction_cost: float = TRANSACTION_COST,
    device: str | None = None,
    seed: int = 42,
) -> tuple[bytes | None, dict]:
    """Train a deep hedging policy from the latest HestonCalibration in DB.

    Args:
        session: SQLAlchemy AsyncSession for querying HestonCalibration.
        n_paths: Number of Monte Carlo paths to generate.
        n_steps: Number of time steps per path (252 = daily for 1 year).
        n_epochs: Number of training epochs.
        lr: Learning rate for Adam optimizer.
        alpha: CVaR tail probability (0.05 = worst 5%).
        transaction_cost: Proportional transaction cost per unit traded.
        device: PyTorch device string ('cuda', 'cpu', or None for auto).
        seed: Random seed for reproducibility.

    Returns:
        (model_bytes, metrics_dict) where model_bytes is the .npz blob
        containing policy weights, or (None, {"reason": ...}) on failure.
    """
    from sqlalchemy import select

    from core.models import HestonCalibration, PriceBar

    # --- 1. Query most recent calibration ---
    result = await session.execute(
        select(HestonCalibration)
        .order_by(HestonCalibration.id.desc())
        .limit(1)
    )
    calibration = result.scalar_one_or_none()

    if calibration is None:
        logger.warning("No HestonCalibration found in database -- cannot train.")
        return None, {"reason": "no calibration data"}

    logger.info(
        "Using HestonCalibration id=%d ticker_id=%d: v0=%.4f kappa=%.2f theta=%.4f sigma_v=%.3f rho=%.3f",
        calibration.id,
        calibration.ticker_id,
        calibration.v0,
        calibration.kappa,
        calibration.theta,
        calibration.sigma_v,
        calibration.rho,
    )

    # --- 2. Generate Heston paths ---
    from simulation.heston import HestonParams, generate_heston_paths

    params = HestonParams(
        v0=calibration.v0,
        kappa=calibration.kappa,
        theta=calibration.theta,
        sigma_v=calibration.sigma_v,
        rho=calibration.rho,
    )

    # Fetch latest close price for the calibration's ticker
    price_result = await session.execute(
        select(PriceBar.close)
        .where(PriceBar.ticker_id == calibration.ticker_id)
        .order_by(PriceBar.date.desc())
        .limit(1)
    )
    latest_close = price_result.scalar_one_or_none()
    spot = float(latest_close) if latest_close else 100.0
    r = RISK_FREE_RATE_DEFAULT
    T = 1.0  # 1-year option

    logger.info(
        "Generating %d Heston paths (%d steps, S0=%.2f, T=%.1f)...",
        n_paths, n_steps, spot, T,
    )

    price_paths, variance_paths = generate_heston_paths(
        S0=spot,
        T=T,
        r=r,
        params=params,
        n_paths=n_paths,
        n_steps=n_steps,
        seed=seed,
    )

    # --- 3. Train the policy ---
    strike = spot * STRIKE_MONEYNESS  # ATM

    model_bytes, metrics = _train_policy(
        price_paths=price_paths,
        variance_paths=variance_paths,
        spot=spot,
        strike=strike,
        r=r,
        T=T,
        n_epochs=n_epochs,
        lr=lr,
        alpha=alpha,
        transaction_cost=transaction_cost,
        device=device,
        seed=seed,
    )

    # Add calibration provenance to metrics
    metrics["calibration_id"] = calibration.id
    metrics["ticker_id"] = calibration.ticker_id
    metrics["heston_params"] = {
        "v0": calibration.v0,
        "kappa": calibration.kappa,
        "theta": calibration.theta,
        "sigma_v": calibration.sigma_v,
        "rho": calibration.rho,
    }
    metrics["spot_price"] = spot
    metrics["risk_free_rate"] = r

    return model_bytes, metrics


# ---------------------------------------------------------------------------
# Pure training loop (no DB dependency -- works with raw numpy arrays)
# ---------------------------------------------------------------------------


def _train_policy(
    price_paths: np.ndarray,
    variance_paths: np.ndarray,
    spot: float,
    strike: float,
    r: float,
    T: float,
    n_epochs: int,
    lr: float,
    alpha: float,
    transaction_cost: float,
    device: str | None = None,
    seed: int = 42,
) -> tuple[bytes, dict]:
    """Train the hedging policy on pre-generated paths.

    This function is pure computation -- no DB access, no async. Factored
    out so it can be tested independently and called from __main__.

    The training loop processes ALL paths each epoch. At each time step t,
    the policy receives the state vector and outputs a target delta. We
    track P&L and transaction costs across the full path, then optimize
    the negative CVaR of terminal P&L.

    Args:
        price_paths: Shape (n_paths, n_steps+1) -- Heston price paths.
        variance_paths: Shape (n_paths, n_steps+1) -- Heston variance paths.
        spot: Initial spot price S0.
        strike: Option strike price.
        r: Risk-free rate.
        T: Time to expiry in years.
        n_epochs: Number of training epochs.
        lr: Learning rate.
        alpha: CVaR tail probability.
        transaction_cost: Proportional cost per unit traded.
        device: PyTorch device.
        seed: Random seed.

    Returns:
        (npz_bytes, metrics_dict)
    """
    from ml.deep_hedging.policy_network import HedgingPolicyNet

    torch.manual_seed(seed)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    dev = torch.device(device)

    n_paths, n_cols = price_paths.shape
    n_steps = n_cols - 1

    logger.info(
        "Training policy: %d paths, %d steps, %d epochs, device=%s",
        n_paths, n_steps, n_epochs, dev,
    )

    # Convert to tensors
    prices_t = torch.tensor(price_paths, dtype=torch.float32, device=dev)
    variances_t = torch.tensor(variance_paths, dtype=torch.float32, device=dev)
    S0 = prices_t[:, 0].unsqueeze(1)  # (n_paths, 1)

    # Pre-compute normalized prices: S_t / S_0
    price_ratios = prices_t / S0  # (n_paths, n_steps+1)

    # Time remaining at each step: 1.0 -> 0.0
    time_remaining = torch.linspace(1.0, 0.0, n_steps + 1, device=dev)  # (n_steps+1,)

    # Initialize policy
    policy = HedgingPolicyNet(state_dim=4).to(dev)
    optimizer = torch.optim.Adam(policy.parameters(), lr=lr)

    # --- BSM delta baseline for comparison ---
    bsm_cvar = _compute_bsm_baseline_cvar(
        price_paths, variance_paths, spot, strike, r, T, transaction_cost, alpha,
    )

    t_start = time.time()
    loss_history = []
    best_cvar = float("-inf")
    best_weights = None

    for epoch in range(n_epochs):
        optimizer.zero_grad()

        # Roll out policy across all paths simultaneously
        # State: (price_ratio, current_delta, time_remaining, variance)
        hedge_pnl = torch.zeros(n_paths, device=dev)
        total_costs = torch.zeros(n_paths, device=dev)
        prev_delta = torch.zeros(n_paths, device=dev)

        for t in range(n_steps):
            # Build state vector: (n_paths, 4)
            state = torch.stack([
                price_ratios[:, t],
                prev_delta,
                time_remaining[t].expand(n_paths),
                variances_t[:, t],
            ], dim=1)

            # Policy output: target delta in [-1, 1]
            action_delta = policy(state)  # (n_paths,)

            # Transaction cost: proportional to |delta_change| * S_t
            delta_change = torch.abs(action_delta - prev_delta)
            step_cost = transaction_cost * delta_change * prices_t[:, t]
            total_costs = total_costs + step_cost

            # Hedge P&L contribution: delta * (S_{t+1} - S_t)
            price_change = prices_t[:, t + 1] - prices_t[:, t]
            hedge_pnl = hedge_pnl + action_delta * price_change

            prev_delta = action_delta

        # Terminal P&L: option_payoff - hedge_pnl - total_costs
        # We are HEDGING a short call position, so:
        #   - If we sold the call, we owe max(S_T - K, 0) at expiry
        #   - Our hedge portfolio gained hedge_pnl
        #   - We paid total_costs in transaction fees
        # Net P&L = hedge_pnl - option_payoff - total_costs
        # (positive = profit for the hedger)
        S_T = prices_t[:, -1]
        option_payoff = torch.clamp(S_T - strike, min=0.0)
        terminal_pnl = hedge_pnl - option_payoff - total_costs

        # Compute CVaR (worst alpha fraction)
        n_tail = max(int(n_paths * alpha), 1)
        sorted_pnl, _ = torch.sort(terminal_pnl)
        cvar = sorted_pnl[:n_tail].mean()

        # Loss: minimize negative CVaR (maximize CVaR)
        loss = -cvar
        loss.backward()

        # Gradient clipping for stability
        nn.utils.clip_grad_norm_(policy.parameters(), max_norm=1.0)
        optimizer.step()

        cvar_val = cvar.item()
        loss_history.append(cvar_val)

        # Track best model
        if cvar_val > best_cvar:
            best_cvar = cvar_val
            best_weights = {k: v.cpu().clone() for k, v in policy.state_dict().items()}

        if (epoch + 1) % 20 == 0 or epoch == 0:
            mean_pnl = terminal_pnl.mean().item()
            std_pnl = terminal_pnl.std().item()
            logger.info(
                "Epoch %3d/%d  CVaR=%.4f  mean_PnL=%.4f  std_PnL=%.4f",
                epoch + 1, n_epochs, cvar_val, mean_pnl, std_pnl,
            )

    elapsed = time.time() - t_start

    # Restore best weights
    if best_weights is not None:
        policy.load_state_dict(best_weights)

    # --- Final evaluation ---
    policy.eval()
    with torch.no_grad():
        hedge_pnl = torch.zeros(n_paths, device=dev)
        total_costs = torch.zeros(n_paths, device=dev)
        prev_delta = torch.zeros(n_paths, device=dev)

        for t in range(n_steps):
            state = torch.stack([
                price_ratios[:, t],
                prev_delta,
                time_remaining[t].expand(n_paths),
                variances_t[:, t],
            ], dim=1)
            action_delta = policy(state)

            delta_change = torch.abs(action_delta - prev_delta)
            step_cost = transaction_cost * delta_change * prices_t[:, t]
            total_costs = total_costs + step_cost
            price_change = prices_t[:, t + 1] - prices_t[:, t]
            hedge_pnl = hedge_pnl + action_delta * price_change
            prev_delta = action_delta

        S_T = prices_t[:, -1]
        option_payoff = torch.clamp(S_T - strike, min=0.0)
        terminal_pnl = hedge_pnl - option_payoff - total_costs
        final_cvar = float(torch.sort(terminal_pnl)[0][:max(int(n_paths * alpha), 1)].mean().item())
        final_mean = float(terminal_pnl.mean().item())
        final_std = float(terminal_pnl.std().item())
        total_cost_mean = float(total_costs.mean().item())

    # --- Export weights as .npz ---
    state_dict = policy.cpu().state_dict()
    weight_arrays = {k: v.numpy() for k, v in state_dict.items()}
    buf = io.BytesIO()
    np.savez(buf, **weight_arrays)
    model_bytes = buf.getvalue()

    cvar_improvement = (final_cvar - bsm_cvar) / abs(bsm_cvar) * 100 if bsm_cvar != 0 else 0.0

    metrics = {
        "n_paths": n_paths,
        "n_steps": n_steps,
        "n_epochs": n_epochs,
        "learning_rate": lr,
        "alpha": alpha,
        "transaction_cost": transaction_cost,
        "strike": strike,
        "spot": spot,
        "final_cvar": final_cvar,
        "final_mean_pnl": final_mean,
        "final_std_pnl": final_std,
        "mean_transaction_costs": total_cost_mean,
        "bsm_baseline_cvar": bsm_cvar,
        "cvar_improvement_pct": cvar_improvement,
        "best_epoch_cvar": best_cvar,
        "training_duration_seconds": elapsed,
        "model_size_bytes": len(model_bytes),
        "device": str(dev),
        "loss_history_sample": loss_history[::max(1, len(loss_history) // 20)],
    }

    logger.info(
        "Training complete in %.1fs. Final CVaR=%.4f (BSM baseline=%.4f, improvement=%.1f%%)",
        elapsed, final_cvar, bsm_cvar, cvar_improvement,
    )

    return model_bytes, metrics


# ---------------------------------------------------------------------------
# BSM delta-hedge baseline (for comparison)
# ---------------------------------------------------------------------------


def _compute_bsm_baseline_cvar(
    price_paths: np.ndarray,
    variance_paths: np.ndarray,
    spot: float,
    strike: float,
    r: float,
    T: float,
    transaction_cost: float,
    alpha: float,
) -> float:
    """Compute CVaR of BSM delta-hedging strategy as a baseline.

    Uses Black-Scholes delta at each step, computed from the average
    variance over the step (converted to BSM vol). This is the strategy
    that the deep hedging policy should improve upon, since BSM delta
    ignores transaction costs and assumes constant volatility.

    Returns:
        CVaR of the BSM hedging P&L (negative = losses in the tail).
    """
    import math

    from scipy.stats import norm

    n_paths, n_cols = price_paths.shape
    n_steps = n_cols - 1
    dt = T / n_steps

    pnl_array = np.zeros(n_paths)

    for i in range(n_paths):
        hedge_pnl = 0.0
        total_costs = 0.0
        prev_delta = 0.0

        for t in range(n_steps):
            S_t = price_paths[i, t]
            S_next = price_paths[i, t + 1]
            tau = T - t * dt  # time remaining

            if tau <= 1e-8:
                # At expiry, delta is 0 or 1
                bsm_delta = 1.0 if S_t > strike else 0.0
            else:
                # BSM delta: N(d1)
                vol = math.sqrt(max(variance_paths[i, t], 1e-8))
                d1 = (math.log(S_t / strike) + (r + 0.5 * vol**2) * tau) / (vol * math.sqrt(tau))
                bsm_delta = float(norm.cdf(d1))

            # Transaction cost
            total_costs += transaction_cost * abs(bsm_delta - prev_delta) * S_t

            # Hedge P&L
            hedge_pnl += bsm_delta * (S_next - S_t)
            prev_delta = bsm_delta

        # Terminal P&L
        S_T = price_paths[i, -1]
        option_payoff = max(S_T - strike, 0.0)
        pnl_array[i] = hedge_pnl - option_payoff - total_costs

    # CVaR
    sorted_pnl = np.sort(pnl_array)
    n_tail = max(int(len(sorted_pnl) * alpha), 1)
    return float(np.mean(sorted_pnl[:n_tail]))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Train deep hedging policy on Heston-simulated paths",
    )
    parser.add_argument("--n-paths", type=int, default=N_PATHS)
    parser.add_argument("--n-steps", type=int, default=N_STEPS)
    parser.add_argument("--n-epochs", type=int, default=N_EPOCHS)
    parser.add_argument("--lr", type=float, default=LEARNING_RATE)
    parser.add_argument("--alpha", type=float, default=ALPHA)
    parser.add_argument("--transaction-cost", type=float, default=TRANSACTION_COST)
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output", type=str, default="deep_hedging_policy.npz",
        help="Output path for the .npz weights file",
    )
    parser.add_argument(
        "--save-to-db", action="store_true",
        help="Save trained model to database via model registry",
    )
    args = parser.parse_args()

    # Try to load calibration from DB; fall back to sensible defaults
    import asyncio

    calibration_params = None

    async def _load_calibration():
        global calibration_params
        try:
            from core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                model_bytes, metrics = await train_deep_hedging_model(
                    session,
                    n_paths=args.n_paths,
                    n_steps=args.n_steps,
                    n_epochs=args.n_epochs,
                    lr=args.lr,
                    alpha=args.alpha,
                    transaction_cost=args.transaction_cost,
                    device=args.device,
                    seed=args.seed,
                )

                if model_bytes is None:
                    logger.warning("train_deep_hedging_model returned None: %s", metrics)
                    return None, metrics

                if args.save_to_db:
                    from ml.model_registry import save_model

                    await save_model(
                        session,
                        model_type="deep_hedging",
                        model_blob=model_bytes,
                        model_format="numpy",
                        training_config={
                            "n_paths": args.n_paths,
                            "n_steps": args.n_steps,
                            "n_epochs": args.n_epochs,
                            "lr": args.lr,
                            "alpha": args.alpha,
                            "transaction_cost": args.transaction_cost,
                            "seed": args.seed,
                        },
                        training_metrics=metrics,
                        eval_metrics={
                            "final_cvar": metrics["final_cvar"],
                            "bsm_baseline_cvar": metrics["bsm_baseline_cvar"],
                            "cvar_improvement_pct": metrics["cvar_improvement_pct"],
                            "final_mean_pnl": metrics["final_mean_pnl"],
                        },
                        training_duration_seconds=metrics["training_duration_seconds"],
                    )
                    await session.commit()
                    logger.info("Model saved to database via model registry.")

                return model_bytes, metrics

        except Exception as e:
            logger.warning("Could not load from DB (%s), falling back to defaults.", e)
            return None, {"reason": str(e)}

    result = asyncio.run(_load_calibration())

    if result is None or result[0] is None:
        # Fallback: train with default Heston parameters (no DB needed)
        logger.info("Training with default Heston parameters (no DB calibration).")

        from simulation.heston import HestonParams, generate_heston_paths

        default_params = HestonParams(
            v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7,
        )
        spot = 100.0
        r = 0.05
        T_val = 1.0

        price_paths, variance_paths = generate_heston_paths(
            S0=spot, T=T_val, r=r, params=default_params,
            n_paths=args.n_paths, n_steps=args.n_steps, seed=args.seed,
        )

        model_bytes, metrics = _train_policy(
            price_paths=price_paths,
            variance_paths=variance_paths,
            spot=spot,
            strike=spot,  # ATM
            r=r,
            T=T_val,
            n_epochs=args.n_epochs,
            lr=args.lr,
            alpha=args.alpha,
            transaction_cost=args.transaction_cost,
            device=args.device,
            seed=args.seed,
        )
    else:
        model_bytes, metrics = result

    if model_bytes is not None:
        # Save to disk
        from pathlib import Path

        output_path = Path(args.output)
        output_path.write_bytes(model_bytes)
        logger.info(
            "Saved policy weights to %s (%.1f KB)",
            output_path, len(model_bytes) / 1024,
        )

    # Print summary
    print("\n" + "=" * 60)
    print("DEEP HEDGING TRAINING SUMMARY")
    print("=" * 60)
    for key in [
        "final_cvar", "bsm_baseline_cvar", "cvar_improvement_pct",
        "final_mean_pnl", "final_std_pnl", "mean_transaction_costs",
        "training_duration_seconds", "model_size_bytes",
    ]:
        if key in metrics:
            val = metrics[key]
            if isinstance(val, float):
                print(f"  {key:30s}: {val:.4f}")
            else:
                print(f"  {key:30s}: {val}")
    print("=" * 60)
