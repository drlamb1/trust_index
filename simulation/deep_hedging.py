"""
EdgeFinder — Deep Hedging Framework (Buehler et al. 2019)

Neural networks that learn optimal hedging strategies directly from
simulated price paths, bypassing Black-Scholes Greeks entirely.

STATUS: Framework/stub. Full training requires PyTorch and is gated
behind settings.deep_hedging_enabled.

KEY INSIGHT FROM BUEHLER ET AL.:
  Traditional hedging: compute delta from a model → hedge at delta → repeat
  Deep hedging: learn a POLICY π(state) → hedge_ratio directly from data

  The policy learns to minimize CVaR (Conditional Value at Risk) of
  hedging P&L, not MSE. This is critical because:
    - MSE penalizes ALL deviations equally (upside and downside)
    - CVaR focuses on the WORST α% of outcomes
    - A policy that's great on average but blows up 5% of the time is useless
    - Risk management cares about tails, not averages

ARCHITECTURE:
  State:  (S_t/S_0, current_delta, time_remaining, v_t)
  Action: target_delta ∈ [-1, 1] (continuous)
  Reward: -CVaR_α(hedging_PnL) where α = 0.05 (worst 5%)

  Policy network: 3-layer feedforward (state_dim → 64 → 32 → 1)
  Training: policy gradient on simulated Heston paths

All experiments use SIMULATED data. Zero real capital.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


@dataclass
class HedgingState:
    """State representation for the deep hedging environment.

    Attributes:
        price_ratio: S_t / S_0 (normalized price)
        current_delta: Current hedge ratio
        time_remaining: Fraction of time to expiry remaining (1.0 → 0.0)
        variance: Current instantaneous variance (from Heston)

    WHY NORMALIZE PRICE:
        Using S_t/S_0 instead of S_t makes the policy transferable
        across different price levels. A $100 stock and a $1000 stock
        behave the same in ratio space.
    """
    price_ratio: float
    current_delta: float
    time_remaining: float
    variance: float

    def to_array(self) -> np.ndarray:
        return np.array([self.price_ratio, self.current_delta, self.time_remaining, self.variance])


@dataclass
class DeepHedgingEnv:
    """Gym-like environment for learning optimal hedging strategies.

    Simulates hedging a European call option by taking delta positions
    in the underlying, with transaction costs.

    At each step:
      1. Observe state (price, current delta, time remaining, vol)
      2. Choose new delta (hedge ratio)
      3. Pay transaction costs proportional to |delta_change|
      4. Price moves to next step (from pre-generated paths)
      5. Repeat until expiry

    Terminal reward: option payoff - hedge portfolio value - total transaction costs

    WHY THIS MATTERS FOR LEARNING:
      BSM delta hedging assumes continuous rebalancing and zero transaction costs.
      In reality, you rebalance discretely and pay bid-ask spreads. Deep hedging
      learns to trade off hedging accuracy vs transaction costs optimally.
    """
    price_paths: np.ndarray  # (n_paths, n_steps+1)
    variance_paths: np.ndarray  # (n_paths, n_steps+1)
    strike: float
    risk_free_rate: float
    transaction_cost: float = 0.001  # 10 bps per unit traded
    n_steps: int = 0
    current_step: int = 0
    current_path: int = 0
    S0: float = 0.0

    def __post_init__(self):
        self.n_steps = self.price_paths.shape[1] - 1
        self.S0 = float(self.price_paths[0, 0])

    def reset(self, path_idx: int = 0) -> HedgingState:
        """Reset environment to start of a new path."""
        self.current_path = path_idx
        self.current_step = 0
        return HedgingState(
            price_ratio=1.0,
            current_delta=0.0,
            time_remaining=1.0,
            variance=float(self.variance_paths[path_idx, 0]),
        )

    def step(self, action_delta: float) -> tuple[HedgingState, float, bool]:
        """Take one hedging step.

        Args:
            action_delta: Target delta (hedge ratio) in [-1, 1]

        Returns:
            (next_state, transaction_cost, done)
        """
        path = self.current_path
        t = self.current_step

        # Current and next prices
        S_t = float(self.price_paths[path, t])
        S_next = float(self.price_paths[path, t + 1])

        # Transaction cost from rebalancing
        delta_change = abs(action_delta - (0.0 if t == 0 else action_delta))
        cost = self.transaction_cost * abs(delta_change) * S_t

        self.current_step += 1
        done = self.current_step >= self.n_steps

        next_state = HedgingState(
            price_ratio=S_next / self.S0,
            current_delta=action_delta,
            time_remaining=1.0 - self.current_step / self.n_steps,
            variance=float(self.variance_paths[path, self.current_step]),
        )

        return next_state, cost, done

    def compute_terminal_pnl(
        self, hedge_deltas: np.ndarray, path_idx: int
    ) -> float:
        """Compute hedging P&L for a complete path.

        PnL = option_payoff - hedge_portfolio_value - total_costs

        The hedge portfolio tracks: Σ delta_t · (S_{t+1} - S_t)
        minus transaction costs at each rebalance.
        """
        prices = self.price_paths[path_idx]
        S_T = float(prices[-1])

        # Option payoff (long call)
        option_payoff = max(S_T - self.strike, 0.0)

        # Hedge portfolio value
        hedge_pnl = 0.0
        total_costs = 0.0
        prev_delta = 0.0

        for t in range(len(hedge_deltas)):
            delta = float(hedge_deltas[t])
            S_t = float(prices[t])
            S_next = float(prices[t + 1])

            # P&L from delta position
            hedge_pnl += delta * (S_next - S_t)

            # Transaction cost
            total_costs += self.transaction_cost * abs(delta - prev_delta) * S_t
            prev_delta = delta

        return option_payoff - hedge_pnl - total_costs


# ---------------------------------------------------------------------------
# CVaR Loss
# ---------------------------------------------------------------------------


def compute_cvar(pnl_array: np.ndarray, alpha: float = 0.05) -> float:
    """Compute Conditional Value at Risk (CVaR / Expected Shortfall).

    MATH:
      CVaR_α = E[X | X ≤ VaR_α]
      = average of the worst α% of outcomes

    WHY CVaR > VaR:
      VaR says "95% of the time, loss won't exceed X"
      CVaR says "in the worst 5%, the AVERAGE loss is Y"

      VaR is a threshold. CVaR is a tail expectation.
      CVaR is also coherent (satisfies subadditivity),
      while VaR is not. Basel III moved to CVaR for this reason.

    Args:
        pnl_array: Array of P&L values (positive = profit, negative = loss)
        alpha: Tail probability (default 5%)

    Returns:
        CVaR (negative for losses in the tail)
    """
    sorted_pnl = np.sort(pnl_array)
    n_tail = max(int(len(sorted_pnl) * alpha), 1)
    return float(np.mean(sorted_pnl[:n_tail]))


# ---------------------------------------------------------------------------
# Status & Explanation Helpers (for chat tools)
# ---------------------------------------------------------------------------


def get_hedging_status() -> dict:
    """Return current status of the deep hedging system."""
    return {
        "status": "framework_ready",
        "training_available": False,
        "description": (
            "The deep hedging framework (Buehler et al. 2019) is implemented "
            "as a simulation environment with CVaR loss. Full training requires "
            "PyTorch and is gated behind the deep_hedging_enabled setting. "
            "The environment, state representation, and CVaR computation are ready."
        ),
        "components": {
            "environment": "ready",
            "state_representation": "ready",
            "cvar_loss": "ready",
            "policy_network": "requires_pytorch",
            "training_loop": "requires_pytorch",
        },
        "next_steps": [
            "Enable deep_hedging_enabled in settings",
            "Install PyTorch: pip install torch",
            "Train policy on Heston-simulated paths",
            "Compare to BSM delta hedging baseline",
        ],
    }


def explain_hedging_concept(concept: str) -> dict:
    """Explain a deep hedging concept for the chat interface."""
    concepts = {
        "cvar": {
            "name": "Conditional Value at Risk (CVaR)",
            "explanation": (
                "CVaR is the average loss in the worst α% of scenarios. "
                "Unlike VaR (which is just a threshold), CVaR tells you HOW BAD "
                "things get when they go wrong. We use CVaR as our loss function "
                "because risk management is about tails, not averages."
            ),
            "math": "CVaR_α = E[X | X ≤ VaR_α] = (1/α)∫₀^α VaR_u du",
        },
        "deep_hedging": {
            "name": "Deep Hedging (Buehler et al. 2019)",
            "explanation": (
                "Instead of computing Greeks from a model and hedging at delta, "
                "train a neural network to directly output the optimal hedge ratio "
                "given the current market state. The network learns to balance "
                "hedging accuracy against transaction costs — something BSM ignores."
            ),
            "math": "min_π E[-CVaR_α(V_T^π)] where V_T^π = payoff - Σ π(s_t)·ΔS_t - costs",
        },
        "transaction_costs": {
            "name": "Transaction Costs in Hedging",
            "explanation": (
                "BSM assumes continuous, costless rebalancing. In reality, every "
                "rebalance costs bid-ask spread. Deep hedging learns to rebalance "
                "LESS when costs outweigh hedging benefit — it discovers the optimal "
                "trade-off between tracking error and transaction costs."
            ),
            "math": "cost_t = κ · |Δδ_t| · S_t where κ ≈ half the bid-ask spread",
        },
    }

    return concepts.get(concept.lower(), {
        "name": concept,
        "explanation": f"Concept '{concept}' not found. Available: {', '.join(concepts.keys())}",
        "math": "",
    })
