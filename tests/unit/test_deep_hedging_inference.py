"""Tests for ml/deep_hedging/inference.py — NumPy forward pass vs known weights."""

from __future__ import annotations

import numpy as np
import pytest

from ml.deep_hedging.inference import (
    predict_delta,
    predict_delta_batch,
    predict_delta_with_weights,
    _forward,
    _forward_batch,
    _validate_weights,
)


def _torch_available() -> bool:
    try:
        import torch
        return True
    except ImportError:
        return False


@pytest.fixture
def known_weights() -> dict[str, np.ndarray]:
    """Create deterministic weights for reproducible tests.

    Architecture: 4 -> 64 -> 32 -> 1
    All weights initialized to small values for predictable outputs.
    """
    rng = np.random.default_rng(42)
    return {
        "net.0.weight": rng.standard_normal((64, 4)).astype(np.float32) * 0.1,
        "net.0.bias": np.zeros(64, dtype=np.float32),
        "net.2.weight": rng.standard_normal((32, 64)).astype(np.float32) * 0.1,
        "net.2.bias": np.zeros(32, dtype=np.float32),
        "net.4.weight": rng.standard_normal((1, 32)).astype(np.float32) * 0.1,
        "net.4.bias": np.zeros(1, dtype=np.float32),
    }


@pytest.fixture
def sample_state() -> np.ndarray:
    """Sample 4D state vector: (price_ratio, delta, time_remaining, variance)."""
    return np.array([1.05, 0.5, 0.75, 0.04], dtype=np.float32)


class TestValidateWeights:
    """Tests for weight validation."""

    def test_valid_weights(self, known_weights):
        assert _validate_weights(known_weights) is True

    def test_missing_key(self, known_weights):
        del known_weights["net.0.weight"]
        assert _validate_weights(known_weights) is False

    def test_wrong_shape(self, known_weights):
        known_weights["net.0.weight"] = np.zeros((32, 4), dtype=np.float32)
        assert _validate_weights(known_weights) is False

    def test_not_a_dict(self):
        assert _validate_weights("not_a_dict") is False

    def test_empty_dict(self):
        assert _validate_weights({}) is False


class TestForwardPass:
    """Tests for the single-sample NumPy forward pass."""

    def test_output_is_scalar(self, known_weights, sample_state):
        result = _forward(known_weights, sample_state)
        assert isinstance(result, float)

    def test_output_bounded(self, known_weights, sample_state):
        """Output should be in [-1, 1] (tanh)."""
        result = _forward(known_weights, sample_state)
        assert -1.0 <= result <= 1.0

    def test_deterministic(self, known_weights, sample_state):
        """Same inputs → same output."""
        r1 = _forward(known_weights, sample_state)
        r2 = _forward(known_weights, sample_state)
        assert r1 == r2

    def test_zero_input(self, known_weights):
        """Zero state with zero biases should give tanh(0) = 0."""
        # With zero biases and zero input, all layers output zero
        # So final output = tanh(0) = 0
        zero_state = np.zeros(4, dtype=np.float32)
        result = _forward(known_weights, zero_state)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_returns_none_on_invalid_weights(self, sample_state):
        result = _forward({}, sample_state)
        assert result is None


class TestForwardBatch:
    """Tests for the batched NumPy forward pass."""

    def test_batch_shape(self, known_weights):
        batch = np.random.randn(10, 4).astype(np.float32)
        result = _forward_batch(known_weights, batch)
        assert result is not None
        assert result.shape == (10,)

    def test_batch_bounded(self, known_weights):
        """All outputs should be in [-1, 1]."""
        batch = np.random.randn(100, 4).astype(np.float32) * 10
        result = _forward_batch(known_weights, batch)
        assert result is not None
        assert np.all(result >= -1.0)
        assert np.all(result <= 1.0)

    def test_batch_matches_single(self, known_weights):
        """Batch inference should match individual inference."""
        batch = np.random.default_rng(42).standard_normal((5, 4)).astype(np.float32)
        batch_result = _forward_batch(known_weights, batch)

        for i in range(5):
            single_result = _forward(known_weights, batch[i])
            assert batch_result[i] == pytest.approx(single_result, abs=1e-6)

    def test_returns_none_on_invalid_weights(self):
        result = _forward_batch({}, np.zeros((5, 4), dtype=np.float32))
        assert result is None


class TestPredictDelta:
    """Tests for the cache-aware predict_delta function."""

    def test_returns_none_when_no_model(self):
        from unittest.mock import patch

        with patch("ml.model_registry.get_cached_model", return_value=None):
            result = predict_delta(np.array([1.0, 0.5, 0.75, 0.04]))
            assert result is None

    def test_returns_float_with_model(self, known_weights):
        from unittest.mock import patch

        with patch("ml.model_registry.get_cached_model", return_value=known_weights):
            result = predict_delta(np.array([1.0, 0.5, 0.75, 0.04]))
            assert isinstance(result, float)
            assert -1.0 <= result <= 1.0


class TestPredictDeltaWithWeights:
    """Tests for the explicit-weights interface."""

    def test_matches_forward(self, known_weights, sample_state):
        result = predict_delta_with_weights(known_weights, sample_state)
        expected = _forward(known_weights, sample_state)
        assert result == expected


class TestPyTorchConsistency:
    """Verify NumPy forward pass matches PyTorch (when torch is available)."""

    @pytest.mark.skipif(
        not _torch_available(), reason="PyTorch not installed"
    )
    def test_numpy_matches_pytorch(self, sample_state):
        """NumPy inference should produce identical results to PyTorch."""
        import io
        import torch
        from ml.deep_hedging.policy_network import HedgingPolicyNet

        # Create policy with known seed
        torch.manual_seed(42)
        policy = HedgingPolicyNet(state_dim=4)
        policy.eval()

        # Get PyTorch output
        state_t = torch.tensor(sample_state).unsqueeze(0)
        with torch.no_grad():
            torch_out = policy(state_t).item()

        # Export weights to numpy
        state_dict = policy.state_dict()
        weight_arrays = {k: v.numpy() for k, v in state_dict.items()}

        # Get NumPy output
        numpy_out = _forward(weight_arrays, sample_state)

        assert numpy_out == pytest.approx(torch_out, abs=1e-5)
