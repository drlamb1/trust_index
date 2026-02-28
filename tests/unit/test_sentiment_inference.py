"""Tests for ml/sentiment/inference.py — mock ONNX, verify shapes/clamping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ml.sentiment.inference import (
    predict_sentiment,
    predict_sentiment_batch,
    _get_model,
)


def _make_mock_model(output_values: np.ndarray | float = 0.5) -> dict:
    """Create a mock sentiment model dict with fake ONNX session and tokenizer."""
    # Mock ONNX session
    session = MagicMock()
    if isinstance(output_values, (int, float)):
        output_values = np.array([[output_values]], dtype=np.float32)
    session.run.return_value = [output_values]
    session.get_inputs.return_value = [
        MagicMock(name="input_ids"),
        MagicMock(name="attention_mask"),
    ]

    # Mock tokenizer (tokenizers.Tokenizer-compatible)
    mock_encoded = MagicMock()
    mock_encoded.ids = [101, 2003, 1037, 3231, 102] + [0] * 123
    mock_encoded.attention_mask = [1, 1, 1, 1, 1] + [0] * 123
    mock_encoded.type_ids = [0] * 128

    tokenizer = MagicMock()
    tokenizer.encode.return_value = mock_encoded
    tokenizer.encode_batch.return_value = [mock_encoded]

    return {
        "onnx_session": session,
        "tokenizer": tokenizer,
        "max_seq_length": 128,
    }


class TestPredictSentiment:
    """Tests for single-headline sentiment prediction."""

    def test_returns_none_when_no_model(self):
        """Should return None when no model is cached."""
        with patch("ml.sentiment.inference.get_cached_model", return_value=None):
            result = predict_sentiment("AAPL beats earnings estimates")
            assert result is None

    def test_returns_float_with_model(self):
        """Should return a float score when model is available."""
        mock_model = _make_mock_model(0.7)
        with patch("ml.sentiment.inference.get_cached_model", return_value=mock_model):
            result = predict_sentiment("AAPL beats earnings estimates")
            assert isinstance(result, float)
            assert result == pytest.approx(0.7, abs=0.01)

    def test_clamps_positive_extreme(self):
        """Scores > 1.0 should be clamped to 1.0."""
        mock_model = _make_mock_model(2.5)
        with patch("ml.sentiment.inference.get_cached_model", return_value=mock_model):
            result = predict_sentiment("Massive rally")
            assert result == 1.0

    def test_clamps_negative_extreme(self):
        """Scores < -1.0 should be clamped to -1.0."""
        mock_model = _make_mock_model(-3.0)
        with patch("ml.sentiment.inference.get_cached_model", return_value=mock_model):
            result = predict_sentiment("Company goes bankrupt")
            assert result == -1.0

    def test_handles_zero_score(self):
        """Zero score (neutral) should work."""
        mock_model = _make_mock_model(0.0)
        with patch("ml.sentiment.inference.get_cached_model", return_value=mock_model):
            result = predict_sentiment("Company reports results")
            assert result == 0.0

    def test_calls_tokenizer_with_title(self):
        """Should tokenize the input title."""
        mock_model = _make_mock_model(0.3)
        with patch("ml.sentiment.inference.get_cached_model", return_value=mock_model):
            predict_sentiment("Test headline")
            mock_model["tokenizer"].encode.assert_called_once_with("Test headline")

    def test_returns_none_on_inference_error(self):
        """Should return None if ONNX inference raises."""
        mock_model = _make_mock_model(0.5)
        mock_model["onnx_session"].run.side_effect = RuntimeError("ONNX error")
        with patch("ml.sentiment.inference.get_cached_model", return_value=mock_model):
            result = predict_sentiment("Test headline")
            assert result is None

    def test_returns_none_for_invalid_cache_type(self):
        """Should return None if cached model has wrong type."""
        with patch("ml.sentiment.inference.get_cached_model", return_value="not_a_dict"):
            result = predict_sentiment("Test headline")
            assert result is None


class TestPredictSentimentBatch:
    """Tests for batch sentiment prediction."""

    def test_empty_list_returns_empty(self):
        """Empty input → empty output."""
        result = predict_sentiment_batch([])
        assert result == []

    def test_returns_none_list_when_no_model(self):
        """Should return [None, None, ...] when no model is cached."""
        with patch("ml.sentiment.inference.get_cached_model", return_value=None):
            result = predict_sentiment_batch(["a", "b", "c"])
            assert result == [None, None, None]

    def test_returns_scores_with_model(self):
        """Should return float scores for each title."""
        scores = np.array([[0.5], [0.8], [-0.3]], dtype=np.float32)
        mock_model = _make_mock_model(scores)
        # Mock batch encoding
        mock_batch = []
        for _ in range(3):
            enc = MagicMock()
            enc.ids = [101, 102] + [0] * 126
            enc.attention_mask = [1, 1] + [0] * 126
            enc.type_ids = [0] * 128
            mock_batch.append(enc)
        mock_model["tokenizer"].encode_batch.return_value = mock_batch

        with patch("ml.sentiment.inference.get_cached_model", return_value=mock_model):
            result = predict_sentiment_batch(["a", "b", "c"])
            assert len(result) == 3
            assert all(isinstance(s, float) for s in result)
            assert result[0] == pytest.approx(0.5, abs=0.01)
            assert result[1] == pytest.approx(0.8, abs=0.01)
            assert result[2] == pytest.approx(-0.3, abs=0.01)

    def test_batch_clamps_scores(self):
        """Batch scores should be clamped to [-1.0, 1.0]."""
        scores = np.array([[2.0], [-5.0]], dtype=np.float32)
        mock_model = _make_mock_model(scores)
        mock_batch = []
        for _ in range(2):
            enc = MagicMock()
            enc.ids = [101, 102] + [0] * 126
            enc.attention_mask = [1, 1] + [0] * 126
            enc.type_ids = [0] * 128
            mock_batch.append(enc)
        mock_model["tokenizer"].encode_batch.return_value = mock_batch

        with patch("ml.sentiment.inference.get_cached_model", return_value=mock_model):
            result = predict_sentiment_batch(["a", "b"])
            assert result[0] == 1.0
            assert result[1] == -1.0
