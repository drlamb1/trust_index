"""ONNX inference for sentiment model — CPU only (Railway deployment).

Loads the combined blob (ONNX model + tokenizer) from the model registry
cache, tokenizes input headlines, runs inference, and returns clamped
sentiment scores in [-1.0, 1.0].
"""

from __future__ import annotations

import logging
import os
import pickle
import tempfile
from typing import Any

import numpy as np

from core.models import MLModelType
from ml.model_registry import get_cached_model

logger = logging.getLogger(__name__)

# Maximum sequence length must match training config
MAX_SEQ_LENGTH = 128


# ---------------------------------------------------------------------------
# Deserialization
# ---------------------------------------------------------------------------


def deserialize_sentiment_model(blob: bytes) -> dict[str, Any]:
    """Deserialize the combined sentiment model blob.

    The blob is a pickle of::

        {
            "onnx_model": bytes,           # quantized ONNX model
            "tokenizer_config": {
                "model_name": str,
                "max_seq_length": int,
                "files": {filename: bytes},  # tokenizer files
            },
        }

    Uses the lightweight ``tokenizers`` Rust library (not ``transformers``)
    so Railway doesn't need the heavy transformers package.

    Returns
    -------
    dict
        {"onnx_session": ort.InferenceSession, "tokenizer": tokenizers.Tokenizer, ...}
    """
    import onnxruntime as ort
    from tokenizers import Tokenizer

    payload = pickle.loads(blob)  # noqa: S301 — trusted source (our own training)

    # Restore ONNX InferenceSession
    onnx_bytes = payload["onnx_model"]
    session = ort.InferenceSession(
        onnx_bytes,
        providers=["CPUExecutionProvider"],
    )

    # Restore tokenizer from bundled files
    tokenizer_cfg = payload["tokenizer_config"]
    tokenizer_files = tokenizer_cfg.get("files", {})

    tokenizer = None
    if tokenizer_files:
        # Write tokenizer files to a temp dir and load from there
        with tempfile.TemporaryDirectory(prefix="ef_tok_") as tmpdir:
            for fname, fbytes in tokenizer_files.items():
                fpath = os.path.join(tmpdir, fname)
                with open(fpath, "wb") as f:
                    f.write(fbytes)

            # Prefer tokenizer.json (fast tokenizer), fall back to vocab-based
            tok_json = os.path.join(tmpdir, "tokenizer.json")
            if os.path.exists(tok_json):
                tokenizer = Tokenizer.from_file(tok_json)
            else:
                logger.warning("No tokenizer.json found in blob; trying vocab.txt fallback")

    if tokenizer is None:
        logger.error(
            "Could not load tokenizer from blob files. "
            "Ensure training exports tokenizer.json."
        )
        raise ValueError("Tokenizer deserialization failed: no tokenizer.json in blob")

    logger.info(
        "Deserialized sentiment model: ONNX session + tokenizer (max_seq=%d)",
        tokenizer_cfg.get("max_seq_length", MAX_SEQ_LENGTH),
    )

    return {
        "onnx_session": session,
        "tokenizer": tokenizer,
        "max_seq_length": tokenizer_cfg.get("max_seq_length", MAX_SEQ_LENGTH),
    }


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def _get_model() -> dict[str, Any] | None:
    """Retrieve the cached sentiment model dict."""
    model = get_cached_model(MLModelType.SENTIMENT.value)
    if model is None:
        logger.debug("Sentiment model not loaded in cache")
        return None
    if not isinstance(model, dict) or "onnx_session" not in model:
        logger.error(
            "Cached sentiment model has unexpected type: %s", type(model).__name__,
        )
        return None
    return model


def predict_sentiment(title: str) -> float | None:
    """Predict sentiment score for a single headline.

    Parameters
    ----------
    title : str
        News headline / article title.

    Returns
    -------
    float | None
        Sentiment score clamped to [-1.0, 1.0], or None if model
        is not available or inference fails.
    """
    model = _get_model()
    if model is None:
        return None

    try:
        session = model["onnx_session"]
        tokenizer = model["tokenizer"]
        max_len = model.get("max_seq_length", MAX_SEQ_LENGTH)

        # tokenizers.Tokenizer API (Rust-based, no transformers dependency)
        tokenizer.enable_padding(length=max_len, pad_id=0, pad_token="[PAD]")
        tokenizer.enable_truncation(max_length=max_len)
        encoded = tokenizer.encode(title)

        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)

        feed = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }

        # Include token_type_ids if the model expects them
        input_names = {inp.name for inp in session.get_inputs()}
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = np.array([encoded.type_ids], dtype=np.int64)

        outputs = session.run(None, feed)
        raw_score = float(outputs[0].flat[0])

        # Clamp to [-1.0, 1.0]
        return float(np.clip(raw_score, -1.0, 1.0))

    except Exception:
        logger.exception("Sentiment inference failed for title: %.80s...", title)
        return None


def predict_sentiment_batch(titles: list[str]) -> list[float | None]:
    """Predict sentiment scores for a batch of headlines.

    Parameters
    ----------
    titles : list[str]
        List of news headlines / article titles.

    Returns
    -------
    list[float | None]
        Sentiment scores clamped to [-1.0, 1.0], or None for each
        title where inference failed.
    """
    if not titles:
        return []

    model = _get_model()
    if model is None:
        return [None] * len(titles)

    try:
        session = model["onnx_session"]
        tokenizer = model["tokenizer"]
        max_len = model.get("max_seq_length", MAX_SEQ_LENGTH)

        # tokenizers.Tokenizer API (Rust-based, no transformers dependency)
        tokenizer.enable_padding(length=max_len, pad_id=0, pad_token="[PAD]")
        tokenizer.enable_truncation(max_length=max_len)
        encoded_batch = tokenizer.encode_batch(titles)

        input_ids = np.array([e.ids for e in encoded_batch], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded_batch], dtype=np.int64)

        feed = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }

        input_names = {inp.name for inp in session.get_inputs()}
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = np.array(
                [e.type_ids for e in encoded_batch], dtype=np.int64,
            )

        outputs = session.run(None, feed)
        raw_scores = outputs[0].flatten()

        # Clamp each score to [-1.0, 1.0]
        clamped = np.clip(raw_scores, -1.0, 1.0)
        return [float(s) for s in clamped]

    except Exception:
        logger.exception("Batch sentiment inference failed for %d titles", len(titles))
        return [None] * len(titles)
