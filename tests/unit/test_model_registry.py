"""Tests for ml/model_registry.py — save/load/cache/version logic."""

from __future__ import annotations

import hashlib
import pickle

import numpy as np
import pytest
import pytest_asyncio

from core.models import MLModel, MLModelType
from ml.model_registry import (
    clear_cache,
    get_cached_model,
    get_cached_version,
    save_model,
    set_cached_model,
    get_active_model_meta,
    load_model_blob,
    deserialize_pickle,
    deserialize_numpy,
    refresh_models,
)


# ---------------------------------------------------------------------------
# In-memory cache tests (no DB needed)
# ---------------------------------------------------------------------------


class TestInMemoryCache:
    """Tests for module-level model cache."""

    def setup_method(self):
        clear_cache()

    def teardown_method(self):
        clear_cache()

    def test_cache_empty_initially(self):
        assert get_cached_model("sentiment") is None
        assert get_cached_version("sentiment") is None

    def test_set_and_get_cached_model(self):
        dummy = {"type": "test_model"}
        set_cached_model("sentiment", 1, dummy)
        assert get_cached_model("sentiment") is dummy
        assert get_cached_version("sentiment") == 1

    def test_cache_multiple_types(self):
        set_cached_model("sentiment", 1, "model_a")
        set_cached_model("signal_ranker", 3, "model_b")
        assert get_cached_model("sentiment") == "model_a"
        assert get_cached_model("signal_ranker") == "model_b"

    def test_clear_single_type(self):
        set_cached_model("sentiment", 1, "model_a")
        set_cached_model("signal_ranker", 2, "model_b")
        clear_cache("sentiment")
        assert get_cached_model("sentiment") is None
        assert get_cached_model("signal_ranker") == "model_b"

    def test_clear_all(self):
        set_cached_model("sentiment", 1, "model_a")
        set_cached_model("signal_ranker", 2, "model_b")
        clear_cache()
        assert get_cached_model("sentiment") is None
        assert get_cached_model("signal_ranker") is None

    def test_overwrite_cached_model(self):
        set_cached_model("sentiment", 1, "old")
        set_cached_model("sentiment", 2, "new")
        assert get_cached_model("sentiment") == "new"
        assert get_cached_version("sentiment") == 2


# ---------------------------------------------------------------------------
# Deserialization tests
# ---------------------------------------------------------------------------


class TestDeserialization:
    """Tests for model deserialization helpers."""

    def test_deserialize_pickle(self):
        original = {"weight": [1, 2, 3], "bias": [0.1]}
        blob = pickle.dumps(original)
        result = deserialize_pickle(blob)
        assert result == original

    def test_deserialize_numpy(self):
        import io

        arrays = {
            "w1": np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
            "b1": np.array([0.5, -0.5], dtype=np.float32),
        }
        buf = io.BytesIO()
        np.savez(buf, **arrays)
        blob = buf.getvalue()

        result = deserialize_numpy(blob)
        assert isinstance(result, dict)
        np.testing.assert_array_equal(result["w1"], arrays["w1"])
        np.testing.assert_array_equal(result["b1"], arrays["b1"])


# ---------------------------------------------------------------------------
# Database tests (require db_session fixture from conftest)
# ---------------------------------------------------------------------------


class TestSaveModel:
    """Tests for saving models to the database."""

    @pytest.mark.asyncio
    async def test_save_first_model(self, db_session):
        blob = b"fake_model_bytes"
        model = await save_model(
            db_session,
            MLModelType.SIGNAL_RANKER.value,
            blob,
            "pickle",
        )
        assert model.version == 1
        assert model.is_active is True
        assert model.model_size_bytes == len(blob)
        assert model.model_hash == hashlib.sha256(blob).hexdigest()

    @pytest.mark.asyncio
    async def test_save_increments_version(self, db_session):
        await save_model(db_session, "signal_ranker", b"v1", "pickle")
        m2 = await save_model(db_session, "signal_ranker", b"v2", "pickle")
        assert m2.version == 2

    @pytest.mark.asyncio
    async def test_save_deactivates_previous(self, db_session):
        m1 = await save_model(db_session, "signal_ranker", b"v1", "pickle")
        await db_session.commit()

        m2 = await save_model(db_session, "signal_ranker", b"v2", "pickle")
        await db_session.commit()

        # Refresh m1 to see the update
        await db_session.refresh(m1)
        assert m1.is_active is False
        assert m2.is_active is True

    @pytest.mark.asyncio
    async def test_save_without_activation(self, db_session):
        m1 = await save_model(db_session, "signal_ranker", b"v1", "pickle")
        await db_session.commit()

        m2 = await save_model(
            db_session, "signal_ranker", b"v2", "pickle", activate=False,
        )
        await db_session.commit()

        await db_session.refresh(m1)
        assert m1.is_active is True
        assert m2.is_active is False

    @pytest.mark.asyncio
    async def test_save_with_metadata(self, db_session):
        model = await save_model(
            db_session,
            "sentiment",
            b"blob",
            "sentiment_onnx",
            training_config={"lr": 0.001},
            training_metrics={"loss": 0.05},
            eval_metrics={"auc": 0.85},
            training_duration_seconds=120.5,
        )
        assert model.training_config == {"lr": 0.001}
        assert model.eval_metrics == {"auc": 0.85}
        assert model.training_duration_seconds == 120.5


class TestLoadModel:
    """Tests for loading models from the database."""

    @pytest.mark.asyncio
    async def test_get_active_model_meta_none(self, db_session):
        result = await get_active_model_meta(db_session, "sentiment")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_model_meta(self, db_session):
        await save_model(db_session, "sentiment", b"blob1", "sentiment_onnx")
        await db_session.commit()

        meta = await get_active_model_meta(db_session, "sentiment")
        assert meta is not None
        assert meta.version == 1
        assert meta.is_active is True

    @pytest.mark.asyncio
    async def test_load_model_blob(self, db_session):
        await save_model(db_session, "sentiment", b"model_data", "sentiment_onnx")
        await db_session.commit()

        result = await load_model_blob(db_session, "sentiment")
        assert result is not None
        blob, model = result
        assert blob == b"model_data"

    @pytest.mark.asyncio
    async def test_load_model_blob_none(self, db_session):
        result = await load_model_blob(db_session, "sentiment")
        assert result is None


class TestRefreshModels:
    """Tests for the refresh_models function."""

    def setup_method(self):
        clear_cache()

    def teardown_method(self):
        clear_cache()

    @pytest.mark.asyncio
    async def test_refresh_with_no_models(self, db_session):
        refreshed = await refresh_models(db_session)
        assert refreshed == []

    @pytest.mark.asyncio
    async def test_refresh_loads_pickle_model(self, db_session):
        original = {"test": True}
        blob = pickle.dumps(original)
        await save_model(db_session, "signal_ranker", blob, "pickle")
        await db_session.commit()

        refreshed = await refresh_models(db_session)
        assert len(refreshed) == 1
        assert "signal_ranker" in refreshed[0]

        cached = get_cached_model("signal_ranker")
        assert cached == original

    @pytest.mark.asyncio
    async def test_refresh_skips_current_version(self, db_session):
        blob = pickle.dumps({"v": 1})
        await save_model(db_session, "signal_ranker", blob, "pickle")
        await db_session.commit()

        # First refresh loads it
        await refresh_models(db_session)
        # Second refresh should skip (already current)
        refreshed = await refresh_models(db_session)
        assert len(refreshed) == 0

    @pytest.mark.asyncio
    async def test_refresh_loads_numpy_model(self, db_session):
        import io

        arrays = {"w": np.array([1.0, 2.0], dtype=np.float32)}
        buf = io.BytesIO()
        np.savez(buf, **arrays)
        blob = buf.getvalue()

        await save_model(db_session, "deep_hedging", blob, "numpy")
        await db_session.commit()

        refreshed = await refresh_models(db_session)
        assert len(refreshed) == 1

        cached = get_cached_model("deep_hedging")
        assert isinstance(cached, dict)
        np.testing.assert_array_equal(cached["w"], arrays["w"])
