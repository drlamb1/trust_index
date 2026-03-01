"""Sentiment model training — runs locally on GPU, never on Railway.

Fine-tunes ProsusAI/finbert with a regression head (single float output)
predicting the Haiku sentiment score. Exports to ONNX with INT8 dynamic
quantization and bundles the tokenizer alongside for self-contained deployment.

Usage:
    python -m ml.sentiment.training          # expects DB credentials in env
    python -m ml.sentiment.training --csv data/sentiment_training.csv
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import pickle
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy.stats import spearmanr
from torch.utils.data import DataLoader, Dataset
from transformers import AutoConfig, AutoModel, AutoTokenizer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FINBERT_MODEL_NAME = "ProsusAI/finbert"
MAX_SEQ_LENGTH = 128
BATCH_SIZE = 32
LEARNING_RATE = 2e-5
NUM_EPOCHS = 4
WEIGHT_DECAY = 0.01
WARMUP_RATIO = 0.1
TRAIN_SPLIT = 0.80  # time-based: first 80% train, last 20% holdout

# Quality gate thresholds (checked by caller, not enforced here)
QUALITY_GATE = {
    "min_direction_agreement": 0.52,  # must beat coin flip
    "min_spearman": 0.10,
    "max_mse": 0.25,
    "min_sample_size": 500,
}


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class SentimentDataset(Dataset):
    """Tokenised headline dataset with float regression targets."""

    def __init__(
        self,
        titles: list[str],
        scores: list[float],
        tokenizer: Any,
        max_length: int = MAX_SEQ_LENGTH,
    ) -> None:
        self.encodings = tokenizer(
            titles,
            padding="max_length",
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        self.scores = torch.tensor(scores, dtype=torch.float32)

    def __len__(self) -> int:
        return len(self.scores)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        item = {k: v[idx] for k, v in self.encodings.items()}
        item["labels"] = self.scores[idx]
        return item


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class FinBERTRegressor(nn.Module):
    """FinBERT encoder + single-neuron regression head."""

    def __init__(self, model_name: str = FINBERT_MODEL_NAME) -> None:
        super().__init__()
        self.config = AutoConfig.from_pretrained(model_name)
        self.encoder = AutoModel.from_pretrained(model_name)
        self.dropout = nn.Dropout(self.config.hidden_dropout_prob)
        self.regressor = nn.Linear(self.config.hidden_size, 1)

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        token_type_ids: torch.Tensor | None = None,
    ) -> torch.Tensor:
        outputs = self.encoder(
            input_ids=input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
        )
        # Use [CLS] token representation
        cls_output = outputs.last_hidden_state[:, 0, :]
        cls_output = self.dropout(cls_output)
        logit = self.regressor(cls_output).squeeze(-1)
        # Tanh to bound output in [-1, 1]
        return torch.tanh(logit)


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------


def _get_linear_schedule_with_warmup(
    optimizer: torch.optim.Optimizer,
    num_warmup_steps: int,
    num_training_steps: int,
) -> torch.optim.lr_scheduler.LambdaLR:
    """Linear warmup then linear decay to zero."""

    def lr_lambda(current_step: int) -> float:
        if current_step < num_warmup_steps:
            return float(current_step) / float(max(1, num_warmup_steps))
        return max(
            0.0,
            float(num_training_steps - current_step)
            / float(max(1, num_training_steps - num_warmup_steps)),
        )

    return torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)


def train_sentiment_model(
    df: pd.DataFrame,
    *,
    num_epochs: int = NUM_EPOCHS,
    batch_size: int = BATCH_SIZE,
    learning_rate: float = LEARNING_RATE,
    device: str | None = None,
) -> tuple[bytes, dict]:
    """Train a FinBERT regression model and export to quantized ONNX.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: title, haiku_score. Assumed to be ordered by
        published_at ascending (for time-based splitting).
    num_epochs : int
        Number of training epochs.
    batch_size : int
        Training and evaluation batch size.
    learning_rate : float
        Peak learning rate for AdamW.
    device : str | None
        Torch device string. Auto-detects GPU if None.

    Returns
    -------
    tuple[bytes, dict]
        (combined_blob, metrics_dict)
        combined_blob is a pickle of {"onnx_model": bytes, "tokenizer_config": dict}
        metrics_dict contains mse, direction_agreement, spearman_correlation,
        sample_size, config, and quality_gate info.
    """
    t_start = time.time()

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Training on device: %s", device)

    # ------------------------------------------------------------------
    # 1. Validate & prepare data
    # ------------------------------------------------------------------
    required_cols = {"title", "haiku_score"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    df = df.dropna(subset=["title", "haiku_score"]).copy()
    df = df[df["title"].str.len() >= 10].reset_index(drop=True)

    if len(df) < 50:
        raise ValueError(
            f"Insufficient training data: {len(df)} rows (need >= 50)"
        )

    # ------------------------------------------------------------------
    # 2. Time-based split (first 80% train, last 20% holdout)
    # ------------------------------------------------------------------
    split_idx = int(len(df) * TRAIN_SPLIT)
    train_df = df.iloc[:split_idx]
    val_df = df.iloc[split_idx:]

    logger.info(
        "Data split: %d train, %d validation (%.1f%% holdout)",
        len(train_df), len(val_df), (1 - TRAIN_SPLIT) * 100,
    )

    # ------------------------------------------------------------------
    # 3. Tokenizer & datasets
    # ------------------------------------------------------------------
    tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL_NAME)

    train_dataset = SentimentDataset(
        train_df["title"].tolist(),
        train_df["haiku_score"].tolist(),
        tokenizer,
    )
    val_dataset = SentimentDataset(
        val_df["title"].tolist(),
        val_df["haiku_score"].tolist(),
        tokenizer,
    )

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    # ------------------------------------------------------------------
    # 4. Model, optimizer, scheduler
    # ------------------------------------------------------------------
    model = FinBERTRegressor(FINBERT_MODEL_NAME).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=learning_rate, weight_decay=WEIGHT_DECAY,
    )

    total_steps = len(train_loader) * num_epochs
    warmup_steps = int(total_steps * WARMUP_RATIO)
    scheduler = _get_linear_schedule_with_warmup(optimizer, warmup_steps, total_steps)

    loss_fn = nn.MSELoss()

    # ------------------------------------------------------------------
    # 5. Training loop
    # ------------------------------------------------------------------
    best_val_loss = float("inf")
    best_state = None

    for epoch in range(num_epochs):
        model.train()
        train_losses = []

        for batch in train_loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            token_type_ids = batch.get("token_type_ids")
            if token_type_ids is not None:
                token_type_ids = token_type_ids.to(device)
            labels = batch["labels"].to(device)

            optimizer.zero_grad()
            preds = model(input_ids, attention_mask, token_type_ids)
            loss = loss_fn(preds, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            train_losses.append(loss.item())

        # Validation
        model.eval()
        val_losses = []
        with torch.no_grad():
            for batch in val_loader:
                input_ids = batch["input_ids"].to(device)
                attention_mask = batch["attention_mask"].to(device)
                token_type_ids = batch.get("token_type_ids")
                if token_type_ids is not None:
                    token_type_ids = token_type_ids.to(device)
                labels = batch["labels"].to(device)

                preds = model(input_ids, attention_mask, token_type_ids)
                val_losses.append(loss_fn(preds, labels).item())

        avg_train_loss = np.mean(train_losses)
        avg_val_loss = np.mean(val_losses)
        logger.info(
            "Epoch %d/%d — train_mse: %.4f, val_mse: %.4f",
            epoch + 1, num_epochs, avg_train_loss, avg_val_loss,
        )

        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    # Restore best checkpoint
    if best_state is not None:
        model.load_state_dict(best_state)
    model.to(device)

    # ------------------------------------------------------------------
    # 6. Holdout evaluation
    # ------------------------------------------------------------------
    model.eval()
    all_preds = []
    all_labels = []
    with torch.no_grad():
        for batch in val_loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            token_type_ids = batch.get("token_type_ids")
            if token_type_ids is not None:
                token_type_ids = token_type_ids.to(device)

            preds = model(input_ids, attention_mask, token_type_ids)
            all_preds.extend(preds.cpu().numpy().tolist())
            all_labels.extend(batch["labels"].numpy().tolist())

    all_preds_arr = np.array(all_preds)
    all_labels_arr = np.array(all_labels)

    holdout_mse = float(np.mean((all_preds_arr - all_labels_arr) ** 2))

    # Direction agreement: does predicted sentiment sign agree with 1-day
    # price move sign? Requires price_move_1d in the validation set.
    price_moves_val = val_df["price_move_1d"].values if "price_move_1d" in val_df.columns else None
    if price_moves_val is not None and len(price_moves_val) == len(all_preds_arr):
        # Only evaluate where price move is non-zero
        mask = price_moves_val != 0
        if mask.sum() > 0:
            pred_sign = np.sign(all_preds_arr[mask])
            price_sign = np.sign(price_moves_val[mask])
            direction_agreement = float(np.mean(pred_sign == price_sign))
        else:
            direction_agreement = None
    else:
        direction_agreement = None

    # Spearman rank correlation between predicted score and actual score
    spearman_corr, spearman_p = spearmanr(all_preds_arr, all_labels_arr)
    spearman_corr = float(spearman_corr)

    training_duration = time.time() - t_start

    # ------------------------------------------------------------------
    # 7. Export to ONNX with INT8 dynamic quantization
    # ------------------------------------------------------------------
    model.cpu().eval()

    # Create dummy inputs for ONNX export
    dummy_input_ids = torch.zeros(1, MAX_SEQ_LENGTH, dtype=torch.long)
    dummy_attention_mask = torch.ones(1, MAX_SEQ_LENGTH, dtype=torch.long)
    dummy_token_type_ids = torch.zeros(1, MAX_SEQ_LENGTH, dtype=torch.long)

    with tempfile.TemporaryDirectory() as tmpdir:
        onnx_fp32_path = os.path.join(tmpdir, "model_fp32.onnx")
        onnx_int8_path = os.path.join(tmpdir, "model_int8.onnx")

        torch.onnx.export(
            model,
            (dummy_input_ids, dummy_attention_mask, dummy_token_type_ids),
            onnx_fp32_path,
            input_names=["input_ids", "attention_mask", "token_type_ids"],
            output_names=["sentiment_score"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "seq"},
                "attention_mask": {0: "batch", 1: "seq"},
                "token_type_ids": {0: "batch", 1: "seq"},
                "sentiment_score": {0: "batch"},
            },
            opset_version=14,
            do_constant_folding=True,
        )

        # INT8 dynamic quantization via onnxruntime
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quantize_dynamic(
            onnx_fp32_path,
            onnx_int8_path,
            weight_type=QuantType.QInt8,
        )

        onnx_bytes = Path(onnx_int8_path).read_bytes()

    logger.info(
        "ONNX model exported: fp32 -> INT8 quantized (%.1f KB)",
        len(onnx_bytes) / 1024,
    )

    # ------------------------------------------------------------------
    # 8. Bundle tokenizer alongside ONNX model
    # ------------------------------------------------------------------
    # Serialize tokenizer to a temp dir, then read all files as bytes
    with tempfile.TemporaryDirectory() as tmpdir:
        tokenizer.save_pretrained(tmpdir)
        tokenizer_files = {}
        for fname in os.listdir(tmpdir):
            fpath = os.path.join(tmpdir, fname)
            if os.path.isfile(fpath):
                tokenizer_files[fname] = Path(fpath).read_bytes()

    combined_blob = pickle.dumps({
        "onnx_model": onnx_bytes,
        "tokenizer_config": {
            "model_name": FINBERT_MODEL_NAME,
            "max_seq_length": MAX_SEQ_LENGTH,
            "files": tokenizer_files,
        },
    })

    logger.info(
        "Combined blob size: %.1f MB (ONNX: %.1f KB + tokenizer files)",
        len(combined_blob) / (1024 * 1024),
        len(onnx_bytes) / 1024,
    )

    # ------------------------------------------------------------------
    # 9. Build metrics dict
    # ------------------------------------------------------------------
    metrics = {
        "mse": holdout_mse,
        "direction_agreement": direction_agreement,
        "spearman_correlation": spearman_corr,
        "spearman_p_value": float(spearman_p),
        "sample_size": len(df),
        "train_size": len(train_df),
        "val_size": len(val_df),
        "best_val_mse": float(best_val_loss),
        "training_duration_seconds": training_duration,
        "onnx_size_bytes": len(onnx_bytes),
        "combined_blob_size_bytes": len(combined_blob),
        "config": {
            "base_model": FINBERT_MODEL_NAME,
            "max_seq_length": MAX_SEQ_LENGTH,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "num_epochs": num_epochs,
            "weight_decay": WEIGHT_DECAY,
            "warmup_ratio": WARMUP_RATIO,
            "train_split": TRAIN_SPLIT,
            "quantization": "INT8_dynamic",
        },
        "quality_gate": QUALITY_GATE,
        "quality_gate_passed": {
            "direction_agreement": (
                direction_agreement is not None
                and direction_agreement >= QUALITY_GATE["min_direction_agreement"]
            ),
            "spearman_correlation": spearman_corr >= QUALITY_GATE["min_spearman"],
            "mse": holdout_mse <= QUALITY_GATE["max_mse"],
            "sample_size": len(df) >= QUALITY_GATE["min_sample_size"],
        },
    }

    all_passed = all(metrics["quality_gate_passed"].values())
    metrics["quality_gate_all_passed"] = all_passed

    if not all_passed:
        logger.warning(
            "Quality gate NOT fully passed: %s",
            {k: v for k, v in metrics["quality_gate_passed"].items() if not v},
        )
    else:
        logger.info("Quality gate passed on all criteria")

    return combined_blob, metrics


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run training from the command line."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Train EdgeFinder sentiment model")
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to CSV with pre-extracted training data (title, haiku_score, price_move_1d columns)",
    )
    parser.add_argument("--epochs", type=int, default=NUM_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--lr", type=float, default=LEARNING_RATE)
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument(
        "--output",
        type=str,
        default="sentiment_model.pkl",
        help="Output path for the combined model blob",
    )
    args = parser.parse_args()

    # Load data
    if args.csv:
        logger.info("Loading training data from CSV: %s", args.csv)
        df = pd.read_csv(args.csv)
    else:
        # Extract from database
        import asyncio

        from core.database import AsyncSessionLocal

        async def _extract() -> pd.DataFrame:
            from ml.sentiment.data import extract_sentiment_training_data

            async with AsyncSessionLocal() as session:
                return await extract_sentiment_training_data(session)

        df = asyncio.run(_extract())

    logger.info("Training data: %d rows", len(df))

    # Train
    combined_blob, metrics = train_sentiment_model(
        df,
        num_epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        device=args.device,
    )

    # Save blob to disk
    output_path = Path(args.output)
    output_path.write_bytes(combined_blob)
    logger.info("Saved combined blob to %s (%.1f MB)", output_path, len(combined_blob) / (1024 * 1024))

    # Print metrics
    import json

    print("\n--- Training Metrics ---")
    print(json.dumps(metrics, indent=2, default=str))

    if metrics["quality_gate_all_passed"]:
        print("\nQuality gate: PASSED")
    else:
        print("\nQuality gate: FAILED")
        failed = {k: v for k, v in metrics["quality_gate_passed"].items() if not v}
        print(f"Failed criteria: {failed}")

    return


if __name__ == "__main__":
    main()
