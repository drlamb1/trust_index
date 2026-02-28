"""
EdgeFinder — Signal Ranker XGBoost Training

Trains a binary classifier that predicts whether a convergence signal
configuration will produce a positive-Sharpe thesis.  The model is used at
inference time to rank and filter candidate convergences before thesis
generation, avoiding wasted compute on low-quality signals.

Training pipeline:
    1. Load labelled data (from ``ml.signal_ranker.data``)
    2. Time-based 80/20 split (preserves temporal ordering)
    3. Train XGBClassifier with tuned hyperparameters
    4. Evaluate on holdout (AUC-ROC, accuracy, feature importances)
    5. Serialize model to pickle bytes

Runnable as:
    python -m ml.signal_ranker.training
"""

from __future__ import annotations

import asyncio
import logging
import pickle
import time
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score
from xgboost import XGBClassifier

from core.database import AsyncSessionLocal
from ml.signal_ranker.data import extract_signal_ranker_training_data

logger = logging.getLogger(__name__)

# Columns that are metadata, not training features
_META_COLUMNS = {"label", "thesis_id", "best_sharpe"}

# XGBoost hyperparameters
_XGB_CONFIG = {
    "n_estimators": 100,
    "max_depth": 4,
    "learning_rate": 0.1,
    "min_child_weight": 3,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "eval_metric": "logloss",
    "use_label_encoder": False,
    "random_state": 42,
    "n_jobs": 1,
}


def train_signal_ranker(
    df: pd.DataFrame,
    train_frac: float = 0.8,
) -> tuple[bytes, dict[str, Any]]:
    """Train the signal ranker classifier and return serialized model + metrics.

    Parameters
    ----------
    df:
        Labelled DataFrame from ``extract_signal_ranker_training_data``.
        Must contain feature columns, ``label``, ``thesis_id``, ``best_sharpe``.
    train_frac:
        Fraction of data to use for training (time-ordered split).

    Returns
    -------
    tuple[bytes, dict]
        (pickle_bytes, metrics_dict)

    Raises
    ------
    ValueError
        If the DataFrame is empty or has fewer than 10 samples.
    """
    if len(df) < 10:
        raise ValueError(
            f"Need at least 10 labelled theses to train; got {len(df)}. "
            "Wait for more backtest completions."
        )

    feature_cols = [c for c in df.columns if c not in _META_COLUMNS]
    X = df[feature_cols].astype(np.float32)
    y = df["label"].astype(np.int32)

    # --- Time-based split (rows are already in creation order) ---------------
    split_idx = int(len(df) * train_frac)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    logger.info(
        "Training signal ranker: %d train, %d test, %d features",
        len(X_train), len(X_test), len(feature_cols),
    )

    # --- Train ---------------------------------------------------------------
    t0 = time.perf_counter()
    model = XGBClassifier(**_XGB_CONFIG)
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )
    train_duration = time.perf_counter() - t0

    # --- Evaluate on holdout -------------------------------------------------
    y_prob = model.predict_proba(X_test)[:, 1]
    y_pred = model.predict(X_test)

    # AUC-ROC requires both classes in the holdout set
    n_classes_test = len(np.unique(y_test))
    if n_classes_test >= 2:
        auc_roc = float(roc_auc_score(y_test, y_prob))
    else:
        auc_roc = None
        logger.warning(
            "Holdout set has only %d class(es); AUC-ROC not computable",
            n_classes_test,
        )

    accuracy = float(accuracy_score(y_test, y_pred))

    # Feature importances (gain-based)
    importance_raw = model.feature_importances_
    feature_importances = {
        col: float(imp)
        for col, imp in sorted(
            zip(feature_cols, importance_raw),
            key=lambda x: x[1],
            reverse=True,
        )
    }

    # --- Serialize -----------------------------------------------------------
    model_bytes = pickle.dumps(model)

    metrics = {
        "auc_roc": auc_roc,
        "accuracy": accuracy,
        "feature_importances": feature_importances,
        "sample_size": len(df),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "positive_rate_train": float(y_train.mean()),
        "positive_rate_test": float(y_test.mean()),
        "training_duration_seconds": round(train_duration, 3),
        "config": _XGB_CONFIG,
    }

    logger.info(
        "Signal ranker trained: AUC=%.4f, Acc=%.4f, %d samples, %.1fs",
        auc_roc or 0.0,
        accuracy,
        len(df),
        train_duration,
    )

    return model_bytes, metrics


# ---------------------------------------------------------------------------
# CLI entry point: python -m ml.signal_ranker.training
# ---------------------------------------------------------------------------


async def _main() -> None:
    """Extract data from DB, train model, and print metrics."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Extracting training data from database...")
    async with AsyncSessionLocal() as session:
        df = await extract_signal_ranker_training_data(session)

    if df.empty:
        logger.error("No training data available. Exiting.")
        return

    model_bytes, metrics = train_signal_ranker(df)

    logger.info("Model size: %.1f KB", len(model_bytes) / 1024)
    logger.info("Metrics:")
    for k, v in metrics.items():
        if k == "feature_importances":
            logger.info("  feature_importances:")
            for feat, imp in v.items():
                logger.info("    %s: %.4f", feat, imp)
        elif k == "config":
            continue
        else:
            logger.info("  %s: %s", k, v)

    # Optionally save to DB — the Celery task handles this in production.
    # To persist manually, use ml.model_registry.save_model().
    logger.info(
        "Training complete. Use ml.model_registry.save_model() to persist "
        "the model blob to Postgres."
    )


if __name__ == "__main__":
    asyncio.run(_main())
