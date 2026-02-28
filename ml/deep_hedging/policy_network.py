"""Deep Hedging Policy Network (Buehler et al. 2019)

Feedforward neural network that maps market state to optimal hedge ratio.
Runs locally for training (GPU/CPU). Never deployed to Railway -- inference
uses pure NumPy reimplementation (see inference.py).

Architecture: 4 -> 64 -> 32 -> 1
Input:  (price_ratio, current_delta, time_remaining, variance)
Output: target_delta in [-1, 1] via tanh

WHY FEEDFORWARD (NOT RNN/TRANSFORMER):
    The 4-dimensional state vector is a sufficient statistic for the hedging
    decision at each step (Markov property of the Heston model). Recurrent
    architectures add complexity without improving the policy because all
    relevant history is captured in (S_t/S_0, delta_t, tau, v_t). Buehler
    et al. (2019) demonstrate that feedforward networks match or exceed
    LSTM-based policies for European option hedging.

WHY TANH OUTPUT:
    The hedge ratio delta must lie in [-1, 1] for a single option. Tanh
    naturally enforces this bound without clipping or projection, ensuring
    smooth gradients throughout training. The network can learn to output
    any value in the feasible set without constraint-violation penalties.

Usage:
    python -m ml.deep_hedging.training   # full training pipeline
"""

from __future__ import annotations

import torch
import torch.nn as nn


class HedgingPolicyNet(nn.Module):
    """Feedforward policy network for deep hedging.

    Maps a 4-dimensional state vector to a scalar hedge ratio.

    Parameters
    ----------
    state_dim : int
        Dimension of the input state vector. Default 4:
        (price_ratio, current_delta, time_remaining, variance).
    hidden1 : int
        Number of units in the first hidden layer (default 64).
    hidden2 : int
        Number of units in the second hidden layer (default 32).

    Forward pass
    ------------
    state -> Linear(4, 64) -> ReLU -> Linear(64, 32) -> ReLU -> Linear(32, 1) -> Tanh

    The output is squeezed to remove the trailing dimension, yielding a
    scalar (or batch of scalars) in [-1, 1].
    """

    def __init__(self, state_dim: int = 4, hidden1: int = 64, hidden2: int = 32):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden1),
            nn.ReLU(),
            nn.Linear(hidden1, hidden2),
            nn.ReLU(),
            nn.Linear(hidden2, 1),
            nn.Tanh(),
        )

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """Compute target delta from state.

        Args:
            state: Tensor of shape (batch_size, state_dim) or (state_dim,).

        Returns:
            Tensor of shape (batch_size,) or scalar -- target hedge ratio in [-1, 1].
        """
        return self.net(state).squeeze(-1)
