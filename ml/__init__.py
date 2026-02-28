"""
EdgeFinder — ML Pipeline

Training runs locally on GPU (Predator). Inference runs on Railway (CPU).
Models are stored as Postgres TOAST blobs in the ml_models table.

Subpackages:
  sentiment/     — FinBERT-based sentiment scoring (replaces Haiku API)
  signal_ranker/ — XGBoost convergence signal ranking (replaces rule-based threshold)
  deep_hedging/  — Policy network for delta hedging (completes the stub)
"""
