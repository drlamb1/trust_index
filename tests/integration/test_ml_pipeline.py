"""Integration tests for the ML pipeline — full save/load/inference cycle.

Tests the complete lifecycle: save model to DB → refresh cache → inference.
Uses SQLite in-memory (no Postgres needed).
"""

from __future__ import annotations

import io
import pickle

import numpy as np
import pytest
import pytest_asyncio

from core.models import MLModel, MLModelType
from ml.model_registry import (
    clear_cache,
    get_cached_model,
    refresh_models,
    save_model,
)


class _FakeXGBClassifier:
    """Pickle-safe stand-in for XGBClassifier."""

    def __init__(self, proba: list[list[float]]):
        self._proba = np.array(proba, dtype=np.float32)

    def predict_proba(self, X):
        return np.tile(self._proba, (X.shape[0], 1))


class TestSignalRankerPipeline:
    """End-to-end: save XGBoost model → refresh → predict."""

    def setup_method(self):
        clear_cache()

    def teardown_method(self):
        clear_cache()

    @pytest.mark.asyncio
    async def test_full_cycle(self, db_session):
        """Save a mock XGBoost model, refresh cache, and run inference."""
        # Create a pickle-safe fake model
        fake_xgb = _FakeXGBClassifier([[0.3, 0.7]])

        # Serialize as pickle
        model_bytes = pickle.dumps(fake_xgb)

        # Save to DB
        await save_model(
            db_session,
            MLModelType.SIGNAL_RANKER.value,
            model_bytes,
            "pickle",
            eval_metrics={"auc_roc": 0.75},
        )
        await db_session.commit()

        # Refresh cache
        refreshed = await refresh_models(db_session)
        assert any("signal_ranker" in r for r in refreshed)

        # Verify model is cached
        cached = get_cached_model(MLModelType.SIGNAL_RANKER.value)
        assert cached is not None

        # Run inference
        from ml.signal_ranker.inference import predict_signal_probability

        convergence = {
            "signal_count": 3,
            "sector": "Technology",
            "signals": {
                "alert": {"count": 1, "types": ["VOLUME_SPIKE"]},
            },
        }
        prob = predict_signal_probability(convergence)
        assert prob is not None
        assert isinstance(prob, float)
        assert 0.0 <= prob <= 1.0


class TestDeepHedgingPipeline:
    """End-to-end: save numpy weights → refresh → NumPy inference."""

    def setup_method(self):
        clear_cache()

    def teardown_method(self):
        clear_cache()

    @pytest.mark.asyncio
    async def test_full_cycle(self, db_session):
        """Save policy weights, refresh cache, and run NumPy inference."""
        rng = np.random.default_rng(42)

        # Create realistic policy weights
        weights = {
            "net.0.weight": rng.standard_normal((64, 4)).astype(np.float32) * 0.1,
            "net.0.bias": np.zeros(64, dtype=np.float32),
            "net.2.weight": rng.standard_normal((32, 64)).astype(np.float32) * 0.1,
            "net.2.bias": np.zeros(32, dtype=np.float32),
            "net.4.weight": rng.standard_normal((1, 32)).astype(np.float32) * 0.1,
            "net.4.bias": np.zeros(1, dtype=np.float32),
        }

        # Serialize as .npz
        buf = io.BytesIO()
        np.savez(buf, **weights)
        model_bytes = buf.getvalue()

        # Save to DB
        await save_model(
            db_session,
            MLModelType.DEEP_HEDGING.value,
            model_bytes,
            "numpy",
            eval_metrics={"final_cvar": -5.2, "cvar_improvement_pct": 12.3},
        )
        await db_session.commit()

        # Refresh cache
        refreshed = await refresh_models(db_session)
        assert any("deep_hedging" in r for r in refreshed)

        # Run inference
        from ml.deep_hedging.inference import predict_delta, predict_delta_batch

        state = np.array([1.05, 0.5, 0.75, 0.04], dtype=np.float32)
        delta = predict_delta(state)
        assert delta is not None
        assert isinstance(delta, float)
        assert -1.0 <= delta <= 1.0

        # Batch inference
        batch = np.random.randn(5, 4).astype(np.float32)
        deltas = predict_delta_batch(batch)
        assert deltas is not None
        assert deltas.shape == (5,)
        assert np.all(deltas >= -1.0) and np.all(deltas <= 1.0)


class TestModelVersioning:
    """Test model versioning and activation logic end-to-end."""

    def setup_method(self):
        clear_cache()

    def teardown_method(self):
        clear_cache()

    @pytest.mark.asyncio
    async def test_version_upgrade_path(self, db_session):
        """Save v1, then v2 — verify only v2 is active."""
        # Save v1
        v1_data = pickle.dumps({"version": 1})
        m1 = await save_model(db_session, "signal_ranker", v1_data, "pickle")
        await db_session.commit()

        # Refresh — should load v1
        await refresh_models(db_session)
        cached = get_cached_model("signal_ranker")
        assert cached == {"version": 1}

        # Save v2 (auto-deactivates v1)
        v2_data = pickle.dumps({"version": 2})
        m2 = await save_model(db_session, "signal_ranker", v2_data, "pickle")
        await db_session.commit()

        # Refresh — should detect new version and load v2
        refreshed = await refresh_models(db_session)
        assert len(refreshed) == 1

        cached = get_cached_model("signal_ranker")
        assert cached == {"version": 2}

    @pytest.mark.asyncio
    async def test_inactive_model_not_loaded(self, db_session):
        """Models saved without activation should not be loaded by refresh."""
        data = pickle.dumps({"inactive": True})
        await save_model(
            db_session, "signal_ranker", data, "pickle", activate=False,
        )
        await db_session.commit()

        refreshed = await refresh_models(db_session)
        assert len(refreshed) == 0
        assert get_cached_model("signal_ranker") is None


class TestFeatureEngineeringToInference:
    """Test the full feature extraction → ranking pipeline."""

    def setup_method(self):
        clear_cache()

    def teardown_method(self):
        clear_cache()

    @pytest.mark.asyncio
    async def test_feature_extraction_feeds_inference(self, db_session):
        """Features extracted from convergence context should feed the ranker."""
        from ml.feature_engineering import extract_convergence_features

        # Verify feature extraction works
        ctx = {
            "signal_count": 3,
            "sector": "Healthcare",
            "signals": {
                "alert": {"count": 2, "types": ["PRICE_ANOMALY", "VOLUME_SPIKE"]},
                "insider_buying": {"count": 1, "total_value": 250_000},
            },
        }
        features = extract_convergence_features(ctx)
        assert len(features) > 10
        assert all(isinstance(v, float) for v in features.values())

        # Save a pickle-safe fake model
        fake_model = _FakeXGBClassifier([[0.35, 0.65]])
        model_bytes = pickle.dumps(fake_model)
        await save_model(db_session, "signal_ranker", model_bytes, "pickle")
        await db_session.commit()
        await refresh_models(db_session)

        # Run inference through the full pipeline
        from ml.signal_ranker.inference import predict_signal_probability

        prob = predict_signal_probability(ctx)
        assert prob is not None
        assert prob == pytest.approx(0.65, abs=0.01)
