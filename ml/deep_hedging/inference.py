"""Deep Hedging Inference — pure NumPy, no PyTorch dependency.

This module runs on Railway (CPU-only, no PyTorch installed). It
reconstructs the forward pass of HedgingPolicyNet using raw matrix
operations on NumPy arrays.

The weights are stored as an .npz blob in the ml_models table and
deserialized into a dict by model_registry.deserialize_numpy(). The
dict keys match the PyTorch state_dict naming convention:

    net.0.weight  (64, 4)    Linear layer 1 weights
    net.0.bias    (64,)      Linear layer 1 bias
    net.2.weight  (32, 64)   Linear layer 2 weights
    net.2.bias    (32,)      Linear layer 2 bias
    net.4.weight  (1, 32)    Linear layer 3 weights
    net.4.bias    (1,)       Linear layer 3 bias

Forward pass: matmul + ReLU -> matmul + ReLU -> matmul + tanh

MEMORY FOOTPRINT:
    Total parameters: 4*64 + 64 + 64*32 + 32 + 32*1 + 1 = 2,401
    At float32: 2,401 * 4 = 9,604 bytes (~10 KB)
    Negligible impact on Railway's memory budget.

GRACEFUL DEGRADATION:
    If no trained model is cached, predict_delta() returns None. The
    calling code (simulation tasks, chat tools) falls back to BSM delta
    hedging or returns a "model not trained" status message. This ensures
    the system never crashes due to a missing ML model.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Weight key constants
# ---------------------------------------------------------------------------

_W1_KEY = "net.0.weight"
_B1_KEY = "net.0.bias"
_W2_KEY = "net.2.weight"
_B2_KEY = "net.2.bias"
_W3_KEY = "net.4.weight"
_B3_KEY = "net.4.bias"

_REQUIRED_KEYS = {_W1_KEY, _B1_KEY, _W2_KEY, _B2_KEY, _W3_KEY, _B3_KEY}


# ---------------------------------------------------------------------------
# Forward pass
# ---------------------------------------------------------------------------


def predict_delta(state_array: np.ndarray) -> float | None:
    """Compute the target hedge ratio from a state vector using cached weights.

    Reconstructs the forward pass of HedgingPolicyNet without PyTorch:
        x = state_array                     # (4,)
        h1 = ReLU(W1 @ x + b1)             # (64,)
        h2 = ReLU(W2 @ h1 + b2)            # (32,)
        out = tanh(W3 @ h2 + b3)           # (1,)  -> scalar

    Args:
        state_array: NumPy array of shape (4,) containing:
            [price_ratio, current_delta, time_remaining, variance]
            Typically obtained from HedgingState.to_array().

    Returns:
        Target delta in [-1, 1], or None if no model is cached.
    """
    from ml.model_registry import get_cached_model

    weights = get_cached_model("deep_hedging")
    if weights is None:
        return None

    return _forward(weights, state_array)


def predict_delta_batch(state_batch: np.ndarray) -> np.ndarray | None:
    """Compute hedge ratios for a batch of state vectors.

    Args:
        state_batch: NumPy array of shape (batch_size, 4).

    Returns:
        Array of shape (batch_size,) with deltas in [-1, 1], or None
        if no model is cached.
    """
    from ml.model_registry import get_cached_model

    weights = get_cached_model("deep_hedging")
    if weights is None:
        return None

    return _forward_batch(weights, state_batch)


def predict_delta_with_weights(
    weights: dict[str, np.ndarray],
    state_array: np.ndarray,
) -> float | None:
    """Forward pass using explicitly provided weights (for testing).

    Args:
        weights: Dict with keys matching PyTorch state_dict naming.
        state_array: Shape (4,) state vector.

    Returns:
        Target delta in [-1, 1], or None on error.
    """
    return _forward(weights, state_array)


# ---------------------------------------------------------------------------
# Internal forward pass implementations
# ---------------------------------------------------------------------------


def _forward(weights: dict[str, np.ndarray], x: np.ndarray) -> float | None:
    """Single-sample forward pass.

    Args:
        weights: Weight dict from .npz deserialization.
        x: Shape (4,) input vector.

    Returns:
        Scalar delta in [-1, 1], or None on error.
    """
    if not _validate_weights(weights):
        return None

    try:
        x = np.asarray(x, dtype=np.float32)

        # Layer 1: Linear + ReLU
        h1 = weights[_W1_KEY] @ x + weights[_B1_KEY]
        h1 = np.maximum(h1, 0.0)  # ReLU

        # Layer 2: Linear + ReLU
        h2 = weights[_W2_KEY] @ h1 + weights[_B2_KEY]
        h2 = np.maximum(h2, 0.0)  # ReLU

        # Layer 3: Linear + Tanh
        out = weights[_W3_KEY] @ h2 + weights[_B3_KEY]
        delta = float(np.tanh(out[0]))

        return delta

    except Exception as e:
        logger.error("Deep hedging inference failed: %s", e)
        return None


def _forward_batch(weights: dict[str, np.ndarray], x_batch: np.ndarray) -> np.ndarray | None:
    """Batched forward pass for efficiency.

    Args:
        weights: Weight dict from .npz deserialization.
        x_batch: Shape (batch_size, 4) input matrix.

    Returns:
        Shape (batch_size,) array of deltas in [-1, 1], or None on error.
    """
    if not _validate_weights(weights):
        return None

    try:
        x = np.asarray(x_batch, dtype=np.float32)

        # Layer 1: (batch, 4) @ (4, 64).T -> (batch, 64)
        h1 = x @ weights[_W1_KEY].T + weights[_B1_KEY]
        h1 = np.maximum(h1, 0.0)

        # Layer 2: (batch, 64) @ (64, 32).T -> (batch, 32)
        h2 = h1 @ weights[_W2_KEY].T + weights[_B2_KEY]
        h2 = np.maximum(h2, 0.0)

        # Layer 3: (batch, 32) @ (32, 1).T -> (batch, 1)
        out = h2 @ weights[_W3_KEY].T + weights[_B3_KEY]
        deltas = np.tanh(out).squeeze(-1)

        return deltas

    except Exception as e:
        logger.error("Deep hedging batch inference failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_weights(weights: dict[str, np.ndarray]) -> bool:
    """Check that the weight dict has the expected keys and shapes.

    Expected shapes:
        net.0.weight: (64, 4)
        net.0.bias:   (64,)
        net.2.weight: (32, 64)
        net.2.bias:   (32,)
        net.4.weight: (1, 32)
        net.4.bias:   (1,)
    """
    if not isinstance(weights, dict):
        logger.error("Expected dict of weights, got %s", type(weights).__name__)
        return False

    missing = _REQUIRED_KEYS - set(weights.keys())
    if missing:
        logger.error("Missing weight keys: %s", missing)
        return False

    expected_shapes = {
        _W1_KEY: (64, 4),
        _B1_KEY: (64,),
        _W2_KEY: (32, 64),
        _B2_KEY: (32,),
        _W3_KEY: (1, 32),
        _B3_KEY: (1,),
    }

    for key, expected_shape in expected_shapes.items():
        actual_shape = weights[key].shape
        if actual_shape != expected_shape:
            logger.error(
                "Weight %s has shape %s, expected %s",
                key, actual_shape, expected_shape,
            )
            return False

    return True
