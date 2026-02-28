"""
EdgeFinder — ML Model Registry

Loads trained models from Postgres blob storage, caches in module-level
globals, and provides clean interfaces for inference code.

Architecture:
  - Models are stored in the ml_models table as binary blobs
  - On worker startup (or periodic refresh), the active model for each
    type is loaded and cached in _MODEL_CACHE
  - Inference code calls get_cached_model(type) which returns the cached
    model or None (triggering fallback behavior)
  - Thread-safe: Celery workers are single-threaded per task
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import pickle
import tempfile
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import MLModel, MLModelType

logger = logging.getLogger(__name__)

# Module-level cache: {model_type: (version, loaded_model_object)}
_MODEL_CACHE: dict[str, tuple[int, Any]] = {}
_LAST_REFRESH: datetime | None = None


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


async def get_active_model_meta(
    session: AsyncSession,
    model_type: str,
) -> MLModel | None:
    """Get metadata (without blob) for the currently active model."""
    result = await session.execute(
        select(MLModel).where(
            MLModel.model_type == model_type,
            MLModel.is_active.is_(True),
        ).order_by(MLModel.version.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def load_model_blob(
    session: AsyncSession,
    model_type: str,
) -> tuple[bytes, MLModel] | None:
    """Load the active model blob for a given type from Postgres."""
    model = await get_active_model_meta(session, model_type)
    if model is None:
        return None
    return model.model_blob, model


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


async def save_model(
    session: AsyncSession,
    model_type: str,
    model_blob: bytes,
    model_format: str,
    training_config: dict | None = None,
    training_metrics: dict | None = None,
    training_data_stats: dict | None = None,
    eval_metrics: dict | None = None,
    training_duration_seconds: float | None = None,
    activate: bool = True,
) -> MLModel:
    """Save a new model version and optionally activate it.

    Deactivates all previous versions of this type when activating.
    """
    # Get next version number
    result = await session.execute(
        select(MLModel.version).where(
            MLModel.model_type == model_type,
        ).order_by(MLModel.version.desc()).limit(1)
    )
    last_version = result.scalar_one_or_none()
    next_version = (last_version or 0) + 1

    if activate:
        # Deactivate all previous versions of this type
        await session.execute(
            update(MLModel).where(
                MLModel.model_type == model_type,
                MLModel.is_active.is_(True),
            ).values(is_active=False)
        )

    model = MLModel(
        model_type=model_type,
        version=next_version,
        is_active=activate,
        model_blob=model_blob,
        model_format=model_format,
        model_size_bytes=len(model_blob),
        model_hash=hashlib.sha256(model_blob).hexdigest(),
        training_config=training_config,
        training_metrics=training_metrics,
        training_data_stats=training_data_stats,
        eval_metrics=eval_metrics,
        training_duration_seconds=training_duration_seconds,
    )
    session.add(model)
    await session.flush()

    logger.info(
        "Saved %s model v%d (%s, %.1f KB, active=%s)",
        model_type, next_version, model_format,
        len(model_blob) / 1024, activate,
    )
    return model


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------


def get_cached_model(model_type: str) -> Any | None:
    """Get model from in-memory cache. Returns None if not loaded."""
    entry = _MODEL_CACHE.get(model_type)
    return entry[1] if entry else None


def get_cached_version(model_type: str) -> int | None:
    """Get the version number of the cached model."""
    entry = _MODEL_CACHE.get(model_type)
    return entry[0] if entry else None


def set_cached_model(model_type: str, version: int, model_obj: Any) -> None:
    """Set model in in-memory cache."""
    _MODEL_CACHE[model_type] = (version, model_obj)
    logger.info("Cached %s model v%d in memory", model_type, version)


def clear_cache(model_type: str | None = None) -> None:
    """Clear cached model(s). If model_type is None, clears all."""
    if model_type:
        _MODEL_CACHE.pop(model_type, None)
    else:
        _MODEL_CACHE.clear()


# ---------------------------------------------------------------------------
# Deserialization helpers
# ---------------------------------------------------------------------------


def deserialize_onnx(blob: bytes) -> Any:
    """Deserialize an ONNX model blob into an InferenceSession."""
    import onnxruntime as ort

    fd, path = tempfile.mkstemp(suffix=".onnx")
    try:
        os.write(fd, blob)
        os.close(fd)
        session = ort.InferenceSession(
            path,
            providers=["CPUExecutionProvider"],
        )
        return session
    finally:
        os.unlink(path)


def deserialize_pickle(blob: bytes) -> Any:
    """Deserialize a pickled model (XGBoost, scikit-learn, etc.)."""
    return pickle.loads(blob)  # noqa: S301 — trusted source (our own training)


def deserialize_numpy(blob: bytes) -> Any:
    """Deserialize numpy .npz weights (deep hedging policy)."""
    import numpy as np

    return dict(np.load(io.BytesIO(blob), allow_pickle=False))


def deserialize_sentiment_onnx(blob: bytes) -> Any:
    """Deserialize the combined sentiment model blob (ONNX + tokenizer)."""
    from ml.sentiment.inference import deserialize_sentiment_model

    return deserialize_sentiment_model(blob)


_DESERIALIZERS = {
    "onnx": deserialize_onnx,
    "pickle": deserialize_pickle,
    "numpy": deserialize_numpy,
    "sentiment_onnx": deserialize_sentiment_onnx,
}


# ---------------------------------------------------------------------------
# Refresh logic
# ---------------------------------------------------------------------------


async def refresh_models(session: AsyncSession) -> list[str]:
    """Check for new model versions and reload into cache.

    Returns list of model types that were refreshed.
    """
    global _LAST_REFRESH
    refreshed = []

    for model_type in MLModelType:
        meta = await get_active_model_meta(session, model_type.value)
        if meta is None:
            continue

        cached_version = get_cached_version(model_type.value)
        if cached_version is not None and cached_version >= meta.version:
            continue  # Already up to date

        deserializer = _DESERIALIZERS.get(meta.model_format)
        if deserializer is None:
            logger.error(
                "Unknown model format '%s' for %s v%d",
                meta.model_format, model_type.value, meta.version,
            )
            continue

        try:
            model_obj = deserializer(meta.model_blob)
            set_cached_model(model_type.value, meta.version, model_obj)
            refreshed.append(f"{model_type.value} v{meta.version}")
        except Exception as e:
            logger.error(
                "Failed to deserialize %s v%d: %s",
                model_type.value, meta.version, e,
            )

    _LAST_REFRESH = datetime.now(timezone.utc)
    return refreshed
