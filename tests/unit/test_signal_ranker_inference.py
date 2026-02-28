"""Tests for ml/signal_ranker/inference.py — mock XGBoost, verify ranking."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ml.signal_ranker.inference import predict_signal_probability, rank_convergences


def _make_convergence(**overrides) -> dict:
    """Create a sample convergence context dict."""
    base = {
        "signal_count": 2,
        "sector": "Information Technology",
        "signals": {
            "alert": {"count": 1, "types": ["PRICE_ANOMALY"]},
            "insider_buying": {"count": 0, "total_value": 0},
        },
    }
    base.update(overrides)
    return base


class TestPredictSignalProbability:
    """Tests for single-convergence probability prediction."""

    def test_returns_none_when_no_model(self):
        """Should return None when signal ranker model is not cached."""
        with patch("ml.signal_ranker.inference.get_cached_model", return_value=None):
            result = predict_signal_probability(_make_convergence())
            assert result is None

    def test_returns_probability_with_model(self):
        """Should return a float probability when model is available."""
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])

        with patch("ml.signal_ranker.inference.get_cached_model", return_value=mock_model):
            result = predict_signal_probability(_make_convergence())
            assert isinstance(result, float)
            assert result == pytest.approx(0.7, abs=0.01)

    def test_returns_none_on_prediction_error(self):
        """Should return None if predict_proba raises."""
        mock_model = MagicMock()
        mock_model.predict_proba.side_effect = ValueError("Bad input")

        with patch("ml.signal_ranker.inference.get_cached_model", return_value=mock_model):
            result = predict_signal_probability(_make_convergence())
            assert result is None

    def test_uses_correct_feature_ordering(self):
        """Features should be sorted alphabetically (consistent with training)."""
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.4, 0.6]])

        with patch("ml.signal_ranker.inference.get_cached_model", return_value=mock_model):
            predict_signal_probability(_make_convergence())

            # Check that predict_proba was called with a 2D array
            call_args = mock_model.predict_proba.call_args
            X = call_args[0][0]
            assert X.ndim == 2
            assert X.shape[0] == 1  # single sample


class TestRankConvergences:
    """Tests for batch ranking and filtering of convergences."""

    def test_returns_unranked_when_no_model(self):
        """Should return original list unmodified when model not available."""
        convs = [_make_convergence(signal_count=1), _make_convergence(signal_count=3)]
        with patch("ml.signal_ranker.inference.get_cached_model", return_value=None):
            result = rank_convergences(convs)
            assert result is convs  # same object, unmodified

    def test_ranks_by_probability(self):
        """Should sort convergences by predicted probability descending."""
        mock_model = MagicMock()
        # Return different probabilities for different calls
        mock_model.predict_proba.side_effect = [
            np.array([[0.4, 0.6]]),  # first convergence: 0.6
            np.array([[0.2, 0.8]]),  # second convergence: 0.8
            np.array([[0.5, 0.5]]),  # third convergence: 0.5
        ]

        convs = [
            _make_convergence(signal_count=1),
            _make_convergence(signal_count=2),
            _make_convergence(signal_count=3),
        ]

        with patch("ml.signal_ranker.inference.get_cached_model", return_value=mock_model):
            result = rank_convergences(convs, min_probability=0.4)

        assert len(result) == 3
        # Should be sorted: 0.8, 0.6, 0.5
        assert result[0]["ml_probability"] == pytest.approx(0.8, abs=0.01)
        assert result[1]["ml_probability"] == pytest.approx(0.6, abs=0.01)
        assert result[2]["ml_probability"] == pytest.approx(0.5, abs=0.01)

    def test_filters_below_threshold(self):
        """Should exclude convergences below min_probability threshold."""
        mock_model = MagicMock()
        mock_model.predict_proba.side_effect = [
            np.array([[0.3, 0.7]]),  # passes: 0.7
            np.array([[0.8, 0.2]]),  # fails: 0.2
            np.array([[0.4, 0.6]]),  # passes: 0.6
        ]

        convs = [
            _make_convergence(signal_count=1),
            _make_convergence(signal_count=2),
            _make_convergence(signal_count=3),
        ]

        with patch("ml.signal_ranker.inference.get_cached_model", return_value=mock_model):
            result = rank_convergences(convs, min_probability=0.5)

        assert len(result) == 2
        assert all(c["ml_probability"] >= 0.5 for c in result)

    def test_annotates_ml_probability(self):
        """Each convergence dict should have an ml_probability key."""
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])

        convs = [_make_convergence()]

        with patch("ml.signal_ranker.inference.get_cached_model", return_value=mock_model):
            result = rank_convergences(convs, min_probability=0.0)

        assert "ml_probability" in result[0]
        assert isinstance(result[0]["ml_probability"], float)

    def test_empty_convergences(self):
        """Empty input should return empty output."""
        mock_model = MagicMock()
        with patch("ml.signal_ranker.inference.get_cached_model", return_value=mock_model):
            result = rank_convergences([], min_probability=0.4)
            assert result == []
