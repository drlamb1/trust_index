"""Tests for ml/feature_engineering.py — convergence feature extraction."""

from __future__ import annotations

import pytest

from ml.feature_engineering import extract_convergence_features


class TestExtractConvergenceFeatures:
    """Tests for the convergence feature extractor."""

    def test_empty_context(self):
        """Empty/None context should produce all-zero features."""
        features = extract_convergence_features({})
        assert isinstance(features, dict)
        assert features["signal_count"] == 0.0
        assert features["has_alert"] == 0.0
        assert features["alert_count"] == 0.0

    def test_none_context(self):
        """None context handled gracefully."""
        features = extract_convergence_features(None)
        assert features["signal_count"] == 0.0

    def test_signal_count(self):
        """signal_count from top-level key."""
        ctx = {"signal_count": 3}
        features = extract_convergence_features(ctx)
        assert features["signal_count"] == 3.0

    def test_alert_features(self):
        """Alert signals extracted correctly."""
        ctx = {
            "signal_count": 2,
            "signals": {
                "alert": {
                    "count": 2,
                    "types": ["PRICE_ANOMALY", "VOLUME_SPIKE"],
                },
            },
        }
        features = extract_convergence_features(ctx)
        assert features["has_alert"] == 1.0
        assert features["alert_count"] == 2.0
        assert features["has_price_anomaly"] == 1.0
        assert features["has_volume_spike"] == 1.0
        assert features["has_filing_red_flag"] == 0.0

    def test_insider_buying_features(self):
        """Insider buying signals extracted with log transform."""
        ctx = {
            "signals": {
                "insider_buying": {
                    "count": 5,
                    "total_value": 1_000_000,
                },
            },
        }
        features = extract_convergence_features(ctx)
        assert features["has_insider_buying"] == 1.0
        assert features["insider_buy_count"] == 5.0
        assert features["insider_buy_value_log"] > 0.0  # log1p(1M) > 0

    def test_filing_concern_features(self):
        """Filing concern signal extraction."""
        ctx = {
            "signals": {
                "filing_concern": {
                    "health_score": 30,
                    "red_flag_count": 3,
                },
            },
        }
        features = extract_convergence_features(ctx)
        assert features["has_filing_concern"] == 1.0
        assert features["filing_health_score"] == 0.30  # normalized to [0,1]
        assert features["filing_red_flag_count"] == 3.0

    def test_sentiment_extreme_features(self):
        """Sentiment extreme signal extraction."""
        ctx = {
            "signals": {
                "sentiment_extreme": {
                    "avg_score": -0.8,
                    "direction": "bearish",
                },
            },
        }
        features = extract_convergence_features(ctx)
        assert features["has_sentiment_extreme"] == 1.0
        assert features["sentiment_avg"] == -0.8
        assert features["sentiment_is_bearish"] == 1.0

    def test_rsi_oversold_features(self):
        """RSI oversold signal extraction."""
        ctx = {
            "signals": {
                "rsi_oversold": {
                    "rsi": 28.5,
                },
            },
        }
        features = extract_convergence_features(ctx)
        assert features["has_rsi_extreme"] == 1.0
        assert features["rsi_value"] == 28.5
        assert features["rsi_is_oversold"] == 1.0

    def test_rsi_overbought_features(self):
        """RSI overbought signal — not oversold."""
        ctx = {
            "signals": {
                "rsi_overbought": {
                    "rsi": 75.0,
                },
            },
        }
        features = extract_convergence_features(ctx)
        assert features["has_rsi_extreme"] == 1.0
        assert features["rsi_value"] == 75.0
        assert features["rsi_is_oversold"] == 0.0

    def test_sector_hash(self):
        """Sector produces a consistent hash in [0, 20)."""
        ctx = {"sector": "Information Technology"}
        features = extract_convergence_features(ctx)
        assert 0.0 <= features["sector_hash"] < 20.0

    def test_sector_hash_empty(self):
        """Empty sector defaults to 0."""
        features = extract_convergence_features({"sector": ""})
        assert features["sector_hash"] == 0.0

    def test_full_convergence(self):
        """Full convergence context with all signal types."""
        ctx = {
            "signal_count": 5,
            "sector": "Healthcare",
            "signals": {
                "alert": {"count": 1, "types": ["EARNINGS_SURPRISE"]},
                "insider_buying": {"count": 2, "total_value": 500_000},
                "filing_concern": {"health_score": 40, "red_flag_count": 2},
                "sentiment_extreme": {"avg_score": 0.6, "direction": "bullish"},
                "rsi_oversold": {"rsi": 32.0},
            },
        }
        features = extract_convergence_features(ctx)
        assert features["signal_count"] == 5.0
        assert features["has_alert"] == 1.0
        assert features["has_insider_buying"] == 1.0
        assert features["has_filing_concern"] == 1.0
        assert features["has_sentiment_extreme"] == 1.0
        assert features["has_rsi_extreme"] == 1.0
        assert features["sentiment_is_bearish"] == 0.0

    def test_feature_count_consistent(self):
        """Feature count should be the same regardless of input."""
        f1 = extract_convergence_features({})
        f2 = extract_convergence_features({"signal_count": 3, "signals": {}})
        assert len(f1) == len(f2)

    def test_all_features_are_float(self):
        """All feature values must be floats (required by XGBoost)."""
        ctx = {
            "signal_count": 2,
            "signals": {
                "alert": {"count": 1, "types": ["PRICE_ANOMALY"]},
            },
        }
        features = extract_convergence_features(ctx)
        for key, value in features.items():
            assert isinstance(value, float), f"{key} is {type(value)}, expected float"
