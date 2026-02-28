# EdgeFinder ML Pipeline: Architecture, Training Methodology, and Operational Design

**Document Version**: 2.0
**Date**: February 2026
**Authors**: EdgeFinder Engineering
**Classification**: Internal / Portfolio

---

## Table of Contents

1. [Abstract](#1-abstract)
2. [System Architecture](#2-system-architecture)
3. [Model Selection Rationale](#3-model-selection-rationale)
4. [Training Methodology](#4-training-methodology)
5. [Evaluation Framework](#5-evaluation-framework)
6. [Quality Control](#6-quality-control)
7. [Operational Architecture](#7-operational-architecture)
8. [References](#8-references)

---

## 1. Abstract

EdgeFinder is a market intelligence platform that integrates quantitative signal detection, natural language sentiment analysis, simulation-driven thesis generation, and portfolio management into a unified decision-support system. The platform processes SEC filings, news sentiment, price anomalies, and technical indicators across 509 actively tracked equity tickers (full S&P 500 plus selected small-cap universe) to autonomously generate, backtest, and manage investment theses through a complete lifecycle.

This document describes the machine learning pipeline that adds three locally-trained models to augment and progressively replace the costliest LLM API calls while enabling the signal detection subsystem to learn from its own outcomes:

1. **FinBERT Sentiment Model** -- fine-tuned financial language model for continuous sentiment scoring, replacing per-article Claude Haiku API calls
2. **XGBoost Signal Ranker** -- binary classifier that predicts thesis viability from convergence signal features, replacing rule-based filtering
3. **Deep Hedging Policy Network** -- feedforward neural network trained via policy gradient to minimize tail risk in delta hedging under stochastic volatility

The central architectural contribution is a **queue-decoupled, heterogeneous-compute training/inference topology** that separates GPU-intensive model training (executed on a local workstation with NVIDIA RTX 4060 8 GB) from CPU-only inference (deployed on Railway cloud infrastructure). Models are versioned and stored as PostgreSQL TOAST blobs with SHA-256 integrity verification, quality-gated activation, and automatic cache refresh. Every inference call site implements **graceful degradation**: when no trained model is available or model integrity checks fail, the system falls back to API-based or rule-based behavior with zero loss of functionality.

This design achieves three goals simultaneously: (1) zero GPU cost in production, (2) sub-millisecond inference latency for two of three model types and sub-50ms for the third, and (3) a model update workflow that requires no container rebuilds, no redeployments, and no downtime -- a new model version propagates from training completion to live inference via a single database write and a periodic cache refresh.

---

## 2. System Architecture

### 2.1 High-Level Topology

```
+==============================================================================+
|                        EDGEFINDER ML PIPELINE TOPOLOGY                        |
+==============================================================================+

  LOCAL WORKSTATION ("Predator")                   RAILWAY CLOUD (always-on)
  i7-13700HX / RTX 4060 8GB / 16GB / WSL2         CPU-only, 3 services
  ==========================================       ==============================

  +--------------------------------------------+
  | Celery Worker: ml_training queue            |
  |                                             |
  |  +----------------+  +------------------+  |
  |  | ml/sentiment/  |  | ml/signal_ranker/|  |
  |  |  training.py   |  |  training.py     |  |
  |  |  FinBERT +     |  |  XGBClassifier   |  |
  |  |  regression    |  |  100 trees       |  |
  |  |  head          |  |  depth 4         |  |
  |  +-------+--------+  +--------+---------+  |
  |          |                     |             |
  |  +-------+---------------------+----------+ |
  |  | ml/deep_hedging/                        | |
  |  |  training.py                            | |
  |  |  4->64->32->1 policy net                | |
  |  |  REINFORCE on Heston MC paths           | |
  |  +--------+-------------------------------+ |
  +-----------|----------------------------------+
              |
              | save_model() -> Postgres TOAST blob
              |   + SHA-256 hash
              |   + version increment
              |   + quality gate (activate/save-inactive)
              |   + training_config, training_metrics, eval_metrics
              v
  +--------------------------------------------------------------+
  |             PostgreSQL (Neon Serverless)                       |
  |                                                                |
  |  ml_models table:                                              |
  |  +----+---------------+---------+-----------+--------+------+ |
  |  | id | model_type    | version | is_active | format | hash | |
  |  +----+---------------+---------+-----------+--------+------+ |
  |  |  1 | sentiment     |       3 | true      | s_onnx | a3f..| |
  |  |  2 | signal_ranker |       2 | true      | pickle | 7b2..| |
  |  |  3 | deep_hedging  |       1 | true      | numpy  | e91..| |
  |  +----+---------------+---------+-----------+--------+------+ |
  |  + model_blob (LargeBinary, TOAST-compressed)                  |
  |  + training_config (JSONB), training_metrics (JSONB)           |
  |  + eval_metrics (JSONB), training_data_stats (JSONB)           |
  |  + model_size_bytes, training_duration_seconds, trained_at     |
  |                                                                |
  |  Also: news_articles, simulated_theses, backtest_runs,         |
  |  heston_calibrations, alerts, price_bars, ... (36 tables)      |
  +---------------------------+------------------------------------+
                              |
          refresh_models()    |   hourly via Celery Beat
          (checks version,    |   task_refresh_ml_models
           deserializes,      |
           caches in RAM)     |
                              v
  +--------------------------------------------------------------+
  | RAILWAY: edgefinder-worker + edgefinder-simulation            |
  |                                                                |
  |  +---------------------------+                                 |
  |  | Module-Level Cache        |    _MODEL_CACHE: dict           |
  |  |  _MODEL_CACHE = {         |      str -> (version, object)   |
  |  |    "sentiment":    (3, {  |                                 |
  |  |      onnx_session,        |    Thread-safe: Celery workers   |
  |  |      tokenizer,           |    are single-threaded per task  |
  |  |      max_seq_length       |                                 |
  |  |    }),                    |                                 |
  |  |    "signal_ranker":(2,   |                                 |
  |  |      XGBClassifier),     |                                 |
  |  |    "deep_hedging": (1,   |                                 |
  |  |      {npz weight dict}), |                                 |
  |  |  }                       |                                 |
  |  +---------------------------+                                 |
  |       |            |            |                              |
  |       v            v            v                              |
  |  +---------+  +----------+  +----------+                      |
  |  |Sentiment|  |Signal    |  |Deep      |                      |
  |  |Inference|  |Ranker    |  |Hedging   |                      |
  |  |         |  |Inference |  |Inference |                      |
  |  |onnxrun- |  |.predict_ |  |NumPy     |                      |
  |  |time CPU |  |proba()   |  |matmul    |                      |
  |  |~15ms    |  |~0.1ms    |  |~0.05ms   |                      |
  |  +----+----+  +----+-----+  +----+-----+                      |
  |       |            |             |                             |
  |       v            v             v                             |
  |  +----------+ +------------+ +-----------+                    |
  |  | Fallback | | Fallback   | | Fallback  |                    |
  |  | Haiku API| | Rule-based | | BSM delta |                    |
  |  | call     | | threshold  | | hedging   |                    |
  |  +----------+ +------------+ +-----------+                    |
  +--------------------------------------------------------------+

  +--------------------------------------------------------------+
  | RAILWAY: edgefinder (FastAPI web server)                       |
  |                                                                |
  |  /api/sentiment, /api/simulation/*, /api/ticker/{symbol}       |
  |  8 chat personas, 44 chat tools, SSE streaming                 |
  |                                                                |
  |  Feature flags (config/settings.py):                           |
  |    use_local_sentiment_model: bool  (default False)            |
  |    signal_ranker_enabled: bool      (default False)            |
  |    signal_ranker_min_probability: float (default 0.4)          |
  |    ml_model_refresh_interval_minutes: int (default 60)         |
  +--------------------------------------------------------------+

  +--------------------------------------------------------------+
  | REDIS (message broker)                                         |
  |                                                                |
  |  6 Celery queues:                                              |
  |    ingestion | analysis | alerts | delivery | simulation       |
  |    ml_training  <-- consumed by local worker only              |
  |                                                                |
  |  34 total tasks, 31 recurring (Celery Beat)                    |
  |  3 training tasks + 1 refresh task for ML pipeline             |
  +--------------------------------------------------------------+
```

### 2.2 Queue-Based Decoupling: The Pull Model

The training/inference split is mediated by Redis task queues and PostgreSQL blob storage, creating a clean separation of concerns:

**Training side (local).** Three Celery tasks (`task_train_sentiment_model`, `task_train_signal_ranker`, `task_train_deep_hedging`) are routed to the `ml_training` queue. This queue is consumed exclusively by a Celery worker process running on the local workstation. When the laptop is powered off, training tasks accumulate harmlessly in Redis; inference continues from the last successfully trained model version.

**Inference side (cloud).** Railway workers never import PyTorch, `transformers`, or any GPU-dependent library. Sentiment inference uses `onnxruntime` (CPU provider); signal ranking uses the `xgboost` predictor; deep hedging uses raw NumPy matrix operations. The `task_refresh_ml_models` task runs hourly on the `simulation` queue (consumed by Railway workers), checking the `ml_models` table for new active versions and deserializing blobs into the in-memory cache.

**Artifact flow.** The single artifact channel is the `ml_models` PostgreSQL table. A trained model travels through exactly one path:

```
train_*() -> quality_gate() -> save_model() -> [Postgres] -> refresh_models() -> _MODEL_CACHE
```

This eliminates the need for artifact registries (MLflow, Weights & Biases), container rebuilds, or CI/CD pipelines for model updates. A model version bump propagates to production in at most one refresh cycle (60 minutes by default, configurable via `ml_model_refresh_interval_minutes`).

### 2.3 Graceful Degradation Strategy

Every inference call site follows a uniform pattern:

```python
# Sentiment (analysis/sentiment.py)
if settings.use_local_sentiment_model:
    results = _score_with_local_model(articles)
    if results:
        return results
    logger.warning("Local model unavailable, falling back to Haiku API")
return await score_articles_haiku(articles, api_key)

# Signal ranker (ml/signal_ranker/inference.py)
model = get_cached_model(MLModelType.SIGNAL_RANKER.value)
if model is None:
    return convergences  # Return unranked, unfiltered

# Deep hedging (ml/deep_hedging/inference.py)
weights = get_cached_model("deep_hedging")
if weights is None:
    return None  # Caller uses BSM delta
```

This guarantees three invariants:

1. A fresh deployment with no trained models behaves identically to the pre-ML system.
2. A corrupted model blob triggers cache eviction and fallback, never a crash.
3. Model rollback requires only a SQL `UPDATE` -- no code changes, no redeployment.

---

## 3. Model Selection Rationale

### 3.1 Sentiment: FinBERT over DistilBERT and General-Purpose LLMs

**Task.** Score financial news headlines on a continuous [-1.0, +1.0] sentiment scale, where -1.0 represents maximally bearish and +1.0 represents maximally bullish sentiment.

**Why FinBERT (Araci 2019) over general-purpose transformers.** FinBERT was pre-trained on a corpus of 1.8 million financial documents from the TRC2 (Thomson Reuters Text Research Collection), followed by supervised fine-tuning on the Financial PhraseBank (Malo et al. 2014). This domain-specific pre-training is critical because financial language systematically inverts the polarity of common words:

- *"Revenue growth decelerated to 8%"* -- "growth" is positive in general NLP but the sentence is bearish (deceleration implies deteriorating trajectory).
- *"The company aggressively cut costs"* -- "aggressively" is negative in general text but positive here (decisive management action improving margins).
- *"Margins compressed despite volume expansion"* -- requires understanding that margin compression dominates volume expansion in a valuation context.

FinBERT achieves 0.87 F1 on ternary financial sentiment classification versus 0.80 for BERT-base and 0.82 for DistilBERT (Huang, Rothe, and Goyal 2023). The gap widens on domain-specific constructs such as earnings guidance language, share buyback announcements, and credit downgrade phrasing. The Loughran and McDonald (2011) financial sentiment lexicon captures some of these word-level distinctions, but FinBERT's 768-dimensional contextual embeddings generalize to unseen syntactic patterns that lexicon-based approaches cannot handle.

**Why not DistilBERT.** DistilBERT (Sanh et al. 2019) offers 40% parameter reduction via knowledge distillation, but its pre-training corpus is general-domain (Wikipedia + BookCorpus). Fine-tuning from a general-domain checkpoint to financial sentiment requires learning both domain semantics and task-specific patterns simultaneously. FinBERT's financial pre-training provides a stronger initialization, requiring fewer fine-tuning examples and achieving higher ceiling performance on the downstream regression task.

**Why not a larger LLM.** The existing pipeline already uses Claude Haiku for sentiment scoring. The goal is to replace these API calls with local inference, not to increase model capacity. FinBERT's 110M parameters are sufficient for headline-level sentiment (short sequences, constrained vocabulary) and export to ONNX INT8 quantization at approximately 65 MB -- small enough for PostgreSQL TOAST storage and Railway's memory constraints.

**Architecture detail.** We append a regression head to FinBERT's `[CLS]` token representation:

```
FinBERT Encoder (110M params, frozen/fine-tuned)
       |
       v
  [CLS] token output: (batch, 768)
       |
       v
  Dropout(p=0.1)     -- matches FinBERT's hidden_dropout_prob
       |
       v
  Linear(768, 1)     -- single regression neuron
       |
       v
  Tanh()             -- bounds output to [-1, 1]
       |
       v
  sentiment_score: float in [-1.0, 1.0]
```

The `tanh` activation naturally constrains the output domain, eliminating post-hoc clipping (which creates zero-gradient regions at the boundaries). The full model is fine-tuned end-to-end, allowing the encoder to adapt its representations to the regression objective while preserving the pre-trained financial language understanding.

### 3.2 Signal Ranker: XGBoost over Neural Approaches

**Task.** Binary classification -- predict P(positive Sharpe ratio) given a convergence signal configuration, enabling pre-filtering of thesis generation candidates.

**Why XGBoost (Chen and Guestrin 2016) over neural networks.** The signal ranking problem operates in a fundamentally different data regime from sentiment analysis:

1. **Small dataset.** As of February 2026, fewer than 100 labelled thesis outcomes exist (9 initial backtests completed, more accumulating weekly). Neural networks require orders of magnitude more data to generalize without overfitting. XGBoost achieves competitive performance with hundreds of samples due to its ensemble of shallow decision trees, each capturing a single decision boundary. The regularization hyperparameters (`max_depth=4`, `subsample=0.8`, `colsample_bytree=0.8`) prevent the ensemble from memorizing the small training set.

2. **Heterogeneous, sparse features.** Signal configurations are inherently sparse -- a given convergence event might involve a price anomaly plus insider buying but no filing red flag, no RSI extreme, and no sentiment divergence. XGBoost handles this natively: at each tree split, it learns the optimal direction for missing features, treating absence as informative (which it is -- the absence of a filing red flag is itself a positive signal for thesis quality). Neural networks require explicit imputation strategies that impose assumptions on the missing data mechanism.

3. **Feature interpretability.** Lundberg and Lee (2017) provide exact Shapley value computation for tree ensembles in polynomial time (`tree_shap`). This enables post-hoc explanation of every prediction: "this signal scored 0.72 because insider buying cluster (SHAP +0.18) AND volume spike (SHAP +0.12) were present, while the absence of filing concerns added SHAP +0.08." This interpretability is operationally essential -- the chat interface personas (ThesisLord, PostMortem) must explain their reasoning to users.

4. **Microsecond inference.** A trained XGBoost model with 100 estimators and max depth 4 evaluates in approximately 50 microseconds on a single CPU core. No batching overhead, no GPU warm-up, no ONNX runtime initialization. This is critical because signal ranking occurs inline within the thesis generation task, which processes up to 509 tickers per cycle.

**Feature engineering.** 19+ numeric features are extracted from the `generation_context` JSONB column on each `SimulatedThesis` record via `ml.feature_engineering.extract_convergence_features()`:

| Feature Group | Features | Type |
|---|---|---|
| Top-level | `signal_count` | Continuous |
| Alert signals | `has_alert`, `alert_count`, 10 binary alert-type indicators (`has_price_anomaly`, `has_volume_spike`, `has_filing_red_flag`, `has_insider_buy_cluster`, `has_sentiment_divergence`, `has_earnings_surprise`, `has_earnings_tone_shift`, `has_technical_signal`, `has_buy_the_dip`, `has_thesis_match`) | Binary / Count |
| Insider buying | `has_insider_buying`, `insider_buy_count`, `insider_buy_value_log` (log1p-transformed dollar value) | Binary / Continuous |
| Filing concern | `has_filing_concern`, `filing_health_score` (normalized 0-1), `filing_red_flag_count` | Binary / Continuous |
| Sentiment extreme | `has_sentiment_extreme`, `sentiment_avg`, `sentiment_is_bearish` | Binary / Continuous |
| RSI extreme | `has_rsi_extreme`, `rsi_value`, `rsi_is_oversold` | Binary / Continuous |
| Sector | `sector_hash` (ordinal encoding via `hash(sector) % 20`) | Categorical proxy |

All features are `float32` with consistent shape regardless of which signal groups are present. Missing signal groups default to zero or neutral values, ensuring the feature vector never contains NaN.

### 3.3 Deep Hedging: Feedforward Policy over Recurrent Architectures

**Task.** Learn the optimal hedge ratio delta(t) at each time step to minimize tail risk of the hedging P&L for a European call option under the Heston stochastic volatility model (Heston 1993).

**Why feedforward over RNN/LSTM/Transformer.** The hedging decision at time t depends on exactly four quantities:

```
state_t = (S_t / S_0,  delta_{t-1},  tau_t,  v_t)
           |            |              |       |
           price ratio  current hedge  time    instantaneous
           (normalized) position       left    variance
```

This state vector is a **sufficient statistic** for the optimal action under the Markov property of the Heston diffusion. The conditional distribution of future price paths given (S_t, v_t) is independent of the path taken to reach this state. Knowing the full path history provides no additional information for the optimal hedging action.

Buehler et al. (2019, Section 4.2) demonstrate that feedforward networks match LSTM-based policies on European option hedging while training approximately 3x faster and producing more stable convergence. Recurrent architectures introduce additional parameters (gate weights, hidden state dimensions) that increase sample complexity without improving the policy, because all decision-relevant information is already encoded in the 4-dimensional state.

**Architecture.** Deliberately minimal:

```
Input (4) ---> Linear(4, 64) ---> ReLU ---> Linear(64, 32) ---> ReLU ---> Linear(32, 1) ---> Tanh
                                                                                               |
                                                                                    target delta in [-1, 1]
```

**Parameter count**: 4x64 + 64 + 64x32 + 32 + 32x1 + 1 = **2,401 parameters** (9,604 bytes in float32). This is smaller than a typical HTTP response header. The extreme compactness is appropriate: the input space is 4-dimensional and the function to be approximated (optimal delta as a function of state) is smooth and monotone in most of its arguments (delta increases with moneyness, decreases with time remaining for OTM options).

**Why tanh output.** The hedge ratio for a single European call option is bounded in [-1, 1] (long or short up to one unit of the underlying per option). Tanh maps R to (-1, 1) with smooth gradients everywhere, providing two advantages:

1. **No clipping artifacts.** Hard clipping (e.g., `torch.clamp(output, -1, 1)`) creates zero-gradient regions where the raw output exceeds bounds, causing gradient starvation during training.
2. **No constraint optimization overhead.** Projected gradient descent or penalty methods add per-step computational cost and introduce additional hyperparameters (penalty coefficient, projection frequency).

The network can learn to output any feasible delta with smooth gradient flow at all points in the output space.

---

## 4. Training Methodology

### 4.1 Sentiment Model: Supervised Regression with Teacher Labels

**Data source.** Training data is extracted from the `news_articles` table via `ml.sentiment.data.extract_sentiment_training_data()`. Each row contains:

| Column | Source | Purpose |
|---|---|---|
| `title` | Article headline (>= 10 chars) | Model input |
| `haiku_score` | Claude Haiku API sentiment score in [-1, 1] | Teacher label (regression target) |
| `price_move_1d` | Realized 1-day price return after publication | Validation against market reality |
| `price_move_5d` | Realized 5-day price return | Extended validation |
| `published_at` | Publication timestamp | Temporal ordering for split |

Rows are ordered by `published_at` ascending. A minimum of 2,000 labelled articles is required before training proceeds (enforced in the Celery task; the training function itself requires >= 50 for testability).

**Teacher-label paradigm.** The Haiku API scores serve as soft teacher labels in a knowledge distillation framework (Hinton, Vinyals, and Dean 2015). This approach is preferable to ternary classification (positive/neutral/negative) because:

1. Continuous scores preserve ordinal information -- "moderately bullish" (0.4) vs. "strongly bullish" (0.9) is meaningful for downstream portfolio sizing.
2. MSE loss on continuous targets provides richer gradient signal than cross-entropy on three buckets.
3. The model can interpolate between teacher labels, potentially achieving better calibration on in-distribution examples.

The validation against realized returns (`price_move_1d`) provides an independent check that the learned sentiment signal has predictive content for actual market moves, rather than merely reproducing the teacher's idiosyncrasies.

**Time-based split.** The first 80% of articles (by publication date) form the training set; the final 20% form the temporal holdout. This is critical: random splitting in financial time-series data creates **look-ahead bias** where the model trains on information from periods that temporally follow evaluation periods. Arlot and Celisse (2010) and Bailey et al. (2014) demonstrate that random cross-validation in financial data systematically overestimates out-of-sample performance due to temporal autocorrelation in feature distributions and label noise.

**Training procedure.** Implemented in `ml.sentiment.training.train_sentiment_model()`:

| Hyperparameter | Value | Rationale |
|---|---|---|
| Optimizer | AdamW (Loshchilov and Hutter 2019) | Decoupled weight decay prevents co-adaptation with adaptive learning rates |
| Learning rate | 2e-5 | Standard for BERT fine-tuning (Devlin et al. 2019); higher rates destabilize pre-trained weights |
| Weight decay | 0.01 | Mild L2 regularization on all parameters |
| Warmup ratio | 10% of total steps | Linear warmup stabilizes early gradient updates before the scheduler takes effect |
| LR schedule | Linear warmup then linear decay to 0 | Prevents overfitting in later epochs by reducing step sizes |
| Batch size | 32 | Balances GPU memory utilization and gradient noise |
| Epochs | 4 | FinBERT converges rapidly due to pre-training; additional epochs risk overfitting on a small dataset |
| Max sequence length | 128 tokens | Headlines rarely exceed 128 WordPiece tokens; longer sequences waste compute |
| Loss function | MSE | Appropriate for regression on bounded [-1, 1] targets |
| Gradient clipping | Max norm 1.0 | Prevents gradient explosions during fine-tuning of deep transformers |
| Early stopping | Best validation loss across epochs | Best model state dict is checkpointed and restored after training |

**ONNX export and quantization.** After training, the model is exported to ONNX format via `torch.onnx.export` with opset version 14 and constant folding enabled. Dynamic axes are configured for both batch size and sequence length dimensions, allowing variable-length inference without padding to `MAX_SEQ_LENGTH`. The exported FP32 model is then quantized to INT8 using `onnxruntime.quantization.quantize_dynamic` with `QInt8` weight type.

The quantized model and the tokenizer files are bundled into a single pickle blob:

```python
combined_blob = pickle.dumps({
    "onnx_model": onnx_int8_bytes,       # ~65 MB quantized ONNX
    "tokenizer_config": {
        "model_name": "ProsusAI/finbert",
        "max_seq_length": 128,
        "files": {                         # All tokenizer files as bytes
            "vocab.txt": b"...",
            "tokenizer_config.json": b"...",
            "special_tokens_map.json": b"...",
        },
    },
})
```

This self-contained blob eliminates the need for Railway workers to download tokenizer files from HuggingFace Hub at startup, which would introduce a network dependency and latency spike on cold starts.

### 4.2 Signal Ranker: Binary Classification on Thesis Outcomes

**Data source.** Training data is extracted from the `simulated_theses` and `backtest_runs` tables via `ml.signal_ranker.data.extract_signal_ranker_training_data()`:

```sql
-- Conceptual query (actual uses SQLAlchemy ORM)
SELECT
    t.id AS thesis_id,
    t.generation_context,          -- JSONB with convergence signals
    MAX(b.sharpe) AS best_sharpe   -- Best Sharpe across all backtests
FROM simulated_theses t
JOIN backtest_runs b ON t.id = b.thesis_id
WHERE t.generation_context IS NOT NULL
  AND t.status IN ('paper_live', 'killed')    -- Terminal lifecycle states
  AND b.sharpe IS NOT NULL
GROUP BY t.id, t.generation_context
ORDER BY t.id ASC                              -- Creation order = temporal order
```

**Label definition.** Binary label based on the best Sharpe ratio across all backtest runs for each thesis:

```
label = 1 if max(sharpe across backtests) > 0    (positive: profitable thesis)
label = 0 otherwise                                (negative: unprofitable thesis)
```

Only theses in terminal lifecycle states (`PAPER_LIVE` or `KILLED`) are included, ensuring that the label reflects a completed evaluation rather than an in-progress backtest. The use of `max(sharpe)` rather than `mean(sharpe)` is deliberate: a thesis that achieves positive Sharpe in at least one evaluation window demonstrates that its signal configuration captured a real market edge, even if subsequent market conditions rendered it unprofitable.

**Feature extraction.** Each thesis's `generation_context` JSONB is passed through `extract_convergence_features()`, which produces a fixed-width dictionary of 19+ float features. The function handles missing signal groups gracefully: if no insider buying data is present, all insider-related features default to 0.0. This ensures XGBoost never encounters NaN values during training or inference, while preserving the information content of feature absence.

**Training procedure.** Implemented in `ml.signal_ranker.training.train_signal_ranker()`:

| Hyperparameter | Value | Rationale |
|---|---|---|
| Algorithm | XGBClassifier | Gradient-boosted decision trees (Chen and Guestrin 2016) |
| n_estimators | 100 | Sufficient ensemble size for <1000 samples; more trees offer diminishing returns |
| max_depth | 4 | Shallow trees prevent overfitting; each tree captures at most 4-way interactions |
| learning_rate | 0.1 | Standard shrinkage rate; lower values require more estimators |
| min_child_weight | 3 | Minimum Hessian sum per leaf; prevents splits on very few samples |
| subsample | 0.8 | Row subsampling adds stochastic regularization |
| colsample_bytree | 0.8 | Feature subsampling decorrelates trees and reduces overfitting |
| eval_metric | logloss | Proper scoring rule for probability estimation (Gneiting and Raftery 2007) |
| random_state | 42 | Reproducibility |

**Split.** Time-based 80/20 split on thesis creation order (rows are ordered by `thesis.id` ascending, which monotonically corresponds to temporal order). This preserves the same temporal integrity guarantees as the sentiment model: the classifier never trains on thesis outcomes that occur after the evaluation period.

### 4.3 Deep Hedging: Policy Gradient on Synthetic Heston Paths

**Motivation.** Unlike the sentiment and signal ranker models, which learn from historical data, the deep hedging policy is trained on **synthetically generated** data. This is both a necessity (no historical hedging P&L data exists for EdgeFinder's simulated options positions) and an advantage:

1. **Unlimited training data.** Each training run generates 10,000 Monte Carlo paths with 252 daily time steps, producing 2.52 million state-action-reward transitions. No sample-size constraints.
2. **No survivorship bias.** Synthetic paths include extreme scenarios (crashes, vol spikes) that may be underrepresented in historical data.
3. **Automatic adaptation.** When the Heston model is recalibrated to new market options data, the training environment automatically reflects current implied volatility dynamics.

**Calibration source.** Training begins by querying the most recent `HestonCalibration` record from PostgreSQL, which provides market-calibrated parameters:

| Parameter | Symbol | Meaning |
|---|---|---|
| v0 | v_0 | Initial variance |
| kappa | kappa | Mean reversion speed |
| theta | theta | Long-term variance |
| sigma_v | sigma_v | Vol-of-vol |
| rho | rho | Price-variance correlation |

If no calibration exists (e.g., first deployment before options data ingestion), training falls back to canonical textbook parameters: v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7.

**Path generation.** The QE (Quadratic-Exponential) discretization scheme of Andersen (2008) generates price and variance paths via `simulation.heston.generate_heston_paths()`. The QE scheme guarantees non-negative variance even when the Feller condition (2*kappa*theta > sigma_v^2) is violated -- a common occurrence in real-world calibrations where sigma_v is large relative to kappa*theta.

**Training loop (REINFORCE-style policy gradient on CVaR).** Implemented in `ml.deep_hedging.training._train_policy()`:

```
For each epoch:
    Initialize: hedge_pnl = 0, total_costs = 0, prev_delta = 0

    For t = 0 to n_steps - 1:
        state_t = (S_t/S_0, prev_delta, tau_t, v_t)     # (n_paths, 4)
        delta_t = policy(state_t)                          # (n_paths,) in [-1, 1]

        cost_t  = kappa * |delta_t - prev_delta| * S_t     # transaction cost
        pnl_t   = delta_t * (S_{t+1} - S_t)                # hedge P&L contribution

        hedge_pnl   += pnl_t
        total_costs += cost_t
        prev_delta   = delta_t

    S_T = prices[:, -1]
    option_payoff = max(S_T - K, 0)                        # call option payoff
    terminal_pnl  = hedge_pnl - option_payoff - total_costs

    # CVaR: mean of worst alpha fraction
    n_tail = int(n_paths * alpha)
    sorted_pnl = sort(terminal_pnl)
    cvar = mean(sorted_pnl[:n_tail])

    loss = -cvar                                            # maximize CVaR
    loss.backward()                                        # policy gradient
    clip_grad_norm_(policy.parameters(), 1.0)
    optimizer.step()
```

**Why CVaR (Conditional Value at Risk) as the objective.**

Three candidate risk measures were considered:

| Measure | Definition | Limitation |
|---|---|---|
| MSE | E[(PnL - target)^2] | Penalizes upside and downside equally; a hedging windfall is penalized identically to a blowup |
| VaR | inf{x : P(PnL <= x) <= alpha} | A quantile -- says nothing about severity beyond the threshold; not subadditive |
| CVaR | E[PnL \| PnL <= VaR_alpha] | Expected loss in the tail; coherent risk measure (Artzner et al. 1999) |

CVaR is a **coherent risk measure** satisfying monotonicity, translation invariance, positive homogeneity, and -- crucially -- **subadditivity** (the risk of a portfolio is at most the sum of individual risks). Basel III mandated the transition from VaR to CVaR (Expected Shortfall) for precisely this reason. At alpha=0.05, we optimize the expected P&L conditional on being in the worst 5% of outcomes, directly targeting catastrophic hedging failures.

**Transaction cost modeling.** Proportional cost of kappa = 0.001 (10 basis points) per unit delta traded:

```
cost_t = 0.001 * |delta_t - delta_{t-1}| * S_t
```

This models the effective bid-ask spread as a fixed fraction of notional traded. The 10 bps figure is conservative for liquid large-cap equities (typical spreads are 1-5 bps for S&P 500 names) but realistic for less liquid positions. The policy network learns to internalize this cost: it reduces rebalancing frequency in low-information-content states (small price moves, stable volatility) and concentrates adjustments in high-information-content states (large gamma exposure near expiry).

**Optimizer configuration.** Adam (Kingma and Ba 2015) with lr=1e-3 and gradient clipping at max norm 1.0. A fixed epoch budget of 200 is used instead of early stopping. Policy gradient objectives are inherently noisy -- the CVaR estimate changes stochastically with each Monte Carlo path set. Early stopping on a noisy objective risks premature termination at a local plateau that would improve with additional training. A fixed budget with best-model checkpointing (tracking the highest CVaR across epochs) is more robust (Henderson et al. 2018).

**BSM baseline.** A Black-Scholes delta-hedging baseline is computed on the same paths for comparison. At each time step, BSM delta is calculated as N(d1) using the instantaneous Heston variance as the BSM volatility input. The baseline hedging P&L is computed with the same transaction cost model, producing a CVaR value against which the learned policy is evaluated. The deep hedging policy should achieve strictly better CVaR because it can:

1. Learn to reduce rebalancing frequency (reducing transaction costs) in states where the hedging benefit is marginal.
2. Anticipate mean-reverting variance dynamics that BSM's constant-volatility assumption ignores.
3. Exploit the correlation structure (rho) between price and variance moves.

---

## 5. Evaluation Framework

### 5.1 Sentiment Model Evaluation

Metrics are computed on the temporal holdout (last 20% of articles by publication date) by `train_sentiment_model()`:

| Metric | Definition | Quality Gate | Rationale |
|---|---|---|---|
| MSE | Mean squared error vs. Haiku labels | <= 0.25 | Ensures reasonable approximation of teacher |
| Spearman rho | Rank correlation between predicted and teacher scores | >= 0.10 | Ensures monotonic relationship is preserved |
| Direction agreement | Fraction of predictions where sign(predicted) == sign(price_move_1d) | >= 0.52 | Must beat coin flip (50%) with statistical significance |
| Sample size | Number of labelled articles used | >= 500 | Ensures evaluation is statistically meaningful |

The direction agreement threshold of 52% may appear modest, but achieving statistically significant directional accuracy on daily equity returns is non-trivial. For N=500 samples with a true accuracy of 52%, a one-sided binomial test yields p < 0.05. This gate prevents deployment of a model that is **worse** than random while allowing models with even modest predictive content to serve (since the alternative -- Haiku API calls -- has both cost and latency overhead).

**Validation against realized returns.** When the training DataFrame includes `price_move_1d`, the model evaluates whether its predicted sentiment sign agrees with the realized next-day price move sign. This cross-validation against market reality (rather than just teacher label reproduction) provides evidence that the learned sentiment signal has genuine predictive content, not merely an ability to mimic the teacher model's biases.

### 5.2 Signal Ranker Evaluation

Metrics are computed on the temporal holdout (last 20% of theses by creation order):

| Metric | Definition | Quality Gate | Rationale |
|---|---|---|---|
| AUC-ROC | Area under receiver operating characteristic | > 0.60 | Must provide non-trivial ranking above random (0.50) |
| Accuracy | Fraction of correct binary predictions | Tracked (no gate) | Sensitive to class imbalance; AUC-ROC is more informative |
| Feature importances | Gain-based importance scores from XGBoost | Logged | Enables audit and debugging of model behavior |
| Positive rate (train) | P(label=1) in training set | Logged | Monitors class balance drift over time |
| Positive rate (test) | P(label=1) in test set | Logged | Monitors class balance drift over time |

AUC-ROC is preferred over accuracy as the primary gate because accuracy is sensitive to the class prior. If 80% of theses are unprofitable (label=0), a trivial "predict all negative" classifier achieves 80% accuracy but 0.50 AUC-ROC. The AUC-ROC gate at 0.60 ensures the model provides genuine ranking capability above random ordering, independent of the class balance.

When the holdout set contains only one class (possible early in the system's lifetime when few theses have completed backtesting), AUC-ROC is not computable. In this case, the model is saved but not activated, and training is deferred until sufficient class diversity accumulates.

### 5.3 Deep Hedging Evaluation

Evaluation is computed on the same Monte Carlo paths used for training (in `torch.no_grad()` mode with the best checkpoint restored):

| Metric | Definition | Quality Gate | Rationale |
|---|---|---|---|
| CVaR_0.05 | Mean P&L in worst 5% of paths (policy) | Must improve over BSM | Primary objective -- tail risk reduction |
| BSM CVaR_0.05 | Mean P&L in worst 5% of paths (BSM delta) | Baseline | Reference performance |
| CVaR improvement % | (policy_CVaR - bsm_CVaR) / \|bsm_CVaR\| * 100 | > 0% | Relative improvement |
| Mean P&L | Average terminal hedging P&L | Tracked | Overall hedging effectiveness |
| Std P&L | Standard deviation of terminal P&L | Tracked | Hedging consistency |
| Mean transaction costs | Average cumulative costs per path | Tracked | Cost efficiency vs. BSM |

The BSM baseline is computed by `_compute_bsm_baseline_cvar()`, which runs a full BSM delta-hedge simulation on all paths with the same transaction cost model. A positive CVaR improvement indicates that the learned policy reduces tail losses relative to the classical approach, either through better delta selection or through cost-aware rebalancing.

---

## 6. Quality Control

### 6.1 Quality Gates

Every trained model must pass its type-specific quality gate before activation. The gate logic is embedded in the Celery training tasks (`scheduler/tasks.py`):

```python
# Sentiment quality gate (task_train_sentiment_model)
direction_agreement = metrics.get("direction_agreement", 0)
activate = direction_agreement >= 0.55

# Signal ranker quality gate (task_train_signal_ranker)
auc = metrics.get("auc_roc", 0)
activate = auc > 0.6

# Deep hedging: always activated if training succeeds
# (BSM comparison is logged but not hard-gated; failure modes
#  are caught upstream by model_bytes == None checks)
```

A model that fails its quality gate is saved to the `ml_models` table with `is_active=false`. This preserves the artifact for debugging and comparison while ensuring that the previous active version continues serving inference. The user can manually activate a failed model via SQL if investigation reveals the gate was overly conservative.

### 6.2 Feature Flags

Two feature flags in `config/settings.py` provide instant rollback without database changes:

| Flag | Default | Controls |
|---|---|---|
| `use_local_sentiment_model` | `False` | Whether `analysis/sentiment.py` tries local ONNX model before Haiku API |
| `signal_ranker_enabled` | `False` | Whether `simulation/thesis_generator.py` applies ML ranking to convergences |
| `signal_ranker_min_probability` | `0.4` | Minimum predicted probability for a convergence to pass ML filter |
| `ml_model_refresh_interval_minutes` | `60` | Cache refresh frequency |

These flags are read from environment variables on Railway. Setting `use_local_sentiment_model=false` immediately reverts all sentiment scoring to Haiku API calls, regardless of what model is cached. This provides a sub-minute rollback mechanism that does not require any database operations.

### 6.3 Model Versioning and Integrity

**Versioning.** The `save_model()` function in `ml/model_registry.py` implements auto-incrementing version numbers per model type:

```python
result = await session.execute(
    select(MLModel.version).where(
        MLModel.model_type == model_type,
    ).order_by(MLModel.version.desc()).limit(1)
)
last_version = result.scalar_one_or_none()
next_version = (last_version or 0) + 1
```

When activating a new version, all previous versions of the same type are deactivated atomically:

```python
if activate:
    await session.execute(
        update(MLModel).where(
            MLModel.model_type == model_type,
            MLModel.is_active.is_(True),
        ).values(is_active=False)
    )
```

A `UniqueConstraint("model_type", "version")` in the database schema prevents version number collisions.

**Integrity.** Every model blob is hashed with SHA-256 at save time and stored in the `model_hash` column:

```python
model = MLModel(
    ...
    model_hash=hashlib.sha256(model_blob).hexdigest(),
    ...
)
```

This guards against PostgreSQL TOAST corruption, truncated blobs from interrupted transactions, and (in principle) unauthorized modification of stored models. A hash mismatch during deserialization triggers a logged error and cache eviction, with the inference path falling back to API/rule-based behavior.

**Rollback.** Model rollback requires no code deployment and no container rebuild:

```sql
-- Deactivate current model
UPDATE ml_models SET is_active = false
WHERE model_type = 'sentiment' AND is_active = true;

-- Reactivate previous version
UPDATE ml_models SET is_active = true
WHERE model_type = 'sentiment' AND version = 2;
```

The next `refresh_models()` cycle detects the version change, deserializes the newly active blob, and updates the in-memory cache. Combined with the feature flag kill switch, this provides two independent rollback mechanisms at different levels of the stack.

### 6.4 Retraining Schedule

All three training tasks are scheduled via Celery Beat (`scheduler/tasks.py`):

| Task | Schedule | Queue | Data Prerequisite |
|---|---|---|---|
| `task_train_sentiment_model` | Sunday 2:00 AM UTC | `ml_training` | >= 2,000 labelled articles |
| `task_train_signal_ranker` | Sunday 3:00 AM UTC | `ml_training` | >= 50 completed thesis backtests |
| `task_train_deep_hedging` | Sunday 4:00 AM UTC | `ml_training` | >= 1 HestonCalibration record |
| `task_refresh_ml_models` | Every hour at :10 | `simulation` | (none -- always runs) |

Training tasks are staggered by one hour to avoid resource contention on the local GPU. Each task checks its data prerequisite before proceeding: if insufficient data is available, the task returns `{"status": "skipped", "reason": "..."}` without error.

### 6.5 Training Provenance and Audit Trail

Every model version stored in `ml_models` includes full training provenance via JSONB columns:

| Column | Content | Example |
|---|---|---|
| `training_config` | Complete hyperparameter dict | `{"learning_rate": 2e-5, "epochs": 4, "batch_size": 32, ...}` |
| `training_metrics` | Per-epoch losses, gradient norms, timing | `{"mse": 0.087, "spearman_correlation": 0.34, ...}` |
| `training_data_stats` | Dataset size, class balance, date range | `{"n_samples": 4200}` |
| `eval_metrics` | Quality gate metrics on holdout set | `{"direction_agreement": 0.58, "auc_roc": 0.67}` |
| `training_duration_seconds` | Wall-clock training time | `347.2` |
| `model_hash` | SHA-256 hex digest | `"a3f291b7..."` |
| `model_format` | Serialization format identifier | `"sentiment_onnx"`, `"pickle"`, `"numpy"` |

Additionally, each training completion is logged to the `simulation_logs` table with `agent_name="ml_trainer"` and `event_type="NOTE"`, making training events visible in the SSE agent feed on the simulation dashboard. This provides real-time visibility into the ML pipeline's activity without querying the `ml_models` table directly.

---

## 7. Operational Architecture

### 7.1 Memory Footprint

| Model | Serialization | Blob Size | In-Memory Size | Notes |
|---|---|---|---|---|
| FinBERT (INT8) | ONNX + tokenizer pickle | ~65 MB | ~65 MB | ONNX InferenceSession + tokenizer objects |
| XGBoost | Python pickle | ~50 KB - 1 MB | ~2 MB | 100 trees expand in-memory for fast traversal |
| Deep hedging | NumPy .npz | ~10 KB | ~40 KB | 2,401 float32 parameters in 6 arrays |
| **Total** | | **~66 MB** | **~67 MB** | |

Railway's container memory budget (typically 512 MB - 1 GB) accommodates all three models with substantial headroom for the FastAPI process, Celery worker, async SQLAlchemy connection pool, and Redis client.

### 7.2 Inference Latency

| Model | Operation | Estimated P50 | Estimated P99 | Notes |
|---|---|---|---|---|
| FinBERT | Tokenize + ONNX forward pass | ~15 ms | ~45 ms | Batch inference amortizes tokenization |
| XGBoost | Feature extraction + predict_proba | ~0.1 ms | ~0.5 ms | 100 trees, depth 4, single sample |
| Deep hedging | 3 NumPy matmuls + 2 ReLU + tanh | ~0.05 ms | ~0.2 ms | 2,401 float32 operations |

FinBERT supports batch inference (`predict_sentiment_batch`) for processing multiple headlines in a single ONNX session forward pass, amortizing the tokenization and ONNX runtime overhead across the batch. XGBoost and deep hedging also support batched prediction (`rank_convergences` processes all candidates in a loop; `predict_delta_batch` uses matrix multiplication).

### 7.3 Model Deserialization

The `refresh_models()` function in `ml/model_registry.py` dispatches blob deserialization to format-specific handlers:

| Format String | Deserializer | Output | Used By |
|---|---|---|---|
| `"sentiment_onnx"` | `deserialize_sentiment_onnx()` | `{"onnx_session": InferenceSession, "tokenizer": AutoTokenizer, "max_seq_length": int}` | Sentiment |
| `"pickle"` | `deserialize_pickle()` | XGBClassifier object | Signal ranker |
| `"numpy"` | `deserialize_numpy()` | `dict[str, np.ndarray]` with weight keys | Deep hedging |
| `"onnx"` | `deserialize_onnx()` | `ort.InferenceSession` | (Generic ONNX, reserved) |

The sentiment model deserializer reconstructs both the ONNX InferenceSession (via `ort.InferenceSession` with CPUExecutionProvider) and the tokenizer (by writing bundled tokenizer files to a temporary directory and loading via `AutoTokenizer.from_pretrained`). This self-contained approach eliminates runtime dependencies on the HuggingFace Hub.

The deep hedging deserializer loads a `.npz` archive into a plain Python dict of NumPy arrays. The inference module (`ml/deep_hedging/inference.py`) implements the forward pass using raw NumPy operations -- no PyTorch, no ONNX runtime -- making it the most lightweight inference path in the pipeline:

```python
# Pure NumPy forward pass (from ml/deep_hedging/inference.py)
h1 = weights["net.0.weight"] @ x + weights["net.0.bias"]    # (64,)
h1 = np.maximum(h1, 0.0)                                     # ReLU
h2 = weights["net.2.weight"] @ h1 + weights["net.2.bias"]   # (32,)
h2 = np.maximum(h2, 0.0)                                     # ReLU
out = weights["net.4.weight"] @ h2 + weights["net.4.bias"]  # (1,)
delta = float(np.tanh(out[0]))                                # [-1, 1]
```

Weight validation is performed before every forward pass, checking that all 6 required keys exist with expected shapes: `(64,4)`, `(64,)`, `(32,64)`, `(32,)`, `(1,32)`, `(1,)`. Shape mismatches trigger an error log and return `None`, activating the BSM fallback.

### 7.4 Model Lifecycle Diagram

```
  DATA ACCUMULATION           TRAINING                 QUALITY GATE
  (continuous)                (weekly, local GPU)       (automated)
       |                           |                        |
       v                           v                        v
  news_articles ---------> train_sentiment_model() --> direction_agreement >= 55%?
  (Haiku labels,                   |                        |
   price_move_1d)                  |                   YES: activate=True
                                   |                   NO:  activate=False
                                   v                        |
  simulated_theses ------> train_signal_ranker()  ---> AUC-ROC > 0.6?
  (generation_context,             |                        |
   backtest results)               |                   YES: activate=True
                                   |                   NO:  activate=False
                                   v                        |
  heston_calibrations ----> train_deep_hedging()  ---> model_bytes != None?
  (v0, kappa, theta,               |                        |
   sigma_v, rho)                   |                   YES: activate=True
                                   |                   NO:  skip entirely
                                   v                        |
                              save_model()  <---------------+
                                   |
                                   | Postgres: ml_models table
                                   | (blob + hash + config + metrics + version)
                                   |
                                   v
                          +-------------------+
                          | ml_models table   |
                          |                   |
                          | version N: active |
                          | version N-1: off  |
                          | version N-2: off  |
                          +-------------------+
                                   |
                                   | refresh_models() -- hourly Celery task
                                   | (checks version > cached_version)
                                   |
                                   v
                          +-------------------+
                          | _MODEL_CACHE      |
                          | (module-level     |
                          |  Python dict)     |
                          +-------------------+
                                   |
                                   | get_cached_model(type)
                                   |
                              +----+----+
                              |         |
                              v         v
                         Model obj    None
                         available    (no model)
                              |         |
                              v         v
                         ML inference  Fallback
                                       (Haiku API /
                                        rule-based /
                                        BSM delta)
```

### 7.5 Deployment Topology

```
+------------------------------------------+
| SERVICE: edgefinder (web)                 |
|   FastAPI + Uvicorn                       |
|   /api/*, /simulation/*, chat endpoints   |
|   Feature flag reads from env vars        |
|   No ML models loaded in this service     |
+------------------------------------------+

+------------------------------------------+
| SERVICE: edgefinder-worker                |
|   Celery worker consuming:                |
|     ingestion, analysis, alerts, delivery |
|   Loads sentiment + signal_ranker models  |
|     via task_refresh_ml_models            |
|   Falls back to Haiku API / rules         |
+------------------------------------------+

+------------------------------------------+
| SERVICE: edgefinder-simulation            |
|   Celery worker consuming:                |
|     simulation queue                      |
|   Loads all 3 models via refresh          |
|   Thesis generation, backtesting,         |
|     paper portfolio management            |
+------------------------------------------+

+------------------------------------------+
| LOCAL: Predator workstation               |
|   Celery worker consuming:                |
|     ml_training queue                     |
|   PyTorch, transformers, full GPU stack   |
|   Connects to same Redis + Postgres       |
|   Powers off freely; tasks queue in Redis |
+------------------------------------------+
```

### 7.6 Failure Modes and Recovery

| Failure Mode | Detection Mechanism | Automatic Recovery | Manual Recovery |
|---|---|---|---|
| Training divergence / NaN loss | Exception in training loop | Task retries via Celery; no model saved | Adjust hyperparameters, re-run training |
| Quality gate failure | Metrics below threshold | Model saved with `is_active=false`; previous version continues serving | Investigate metrics; optionally activate manually via SQL |
| Blob corruption in Postgres | SHA-256 mismatch during `refresh_models()` | Error logged; model not cached; fallback behavior | Re-train and re-save model |
| ONNX runtime crash | Exception caught per-request in `predict_sentiment()` | Returns `None`; caller falls back to Haiku API | Check ONNX model compatibility; retrain if necessary |
| XGBoost version mismatch | `pickle.loads()` raises `ModuleNotFoundError` or `AttributeError` | Error logged; model not cached; unranked convergences returned | Pin XGBoost version or retrain with current version |
| Stale cache (missed refresh) | Cached version < active version for > refresh interval | Next `refresh_models()` cycle catches up | Manual: call `refresh_models()` via `task_refresh_ml_models.apply_async()` |
| PostgreSQL unavailable | Connection timeout during `refresh_models()` | Cached models continue serving (no new loads until connectivity returns) | Restore database connectivity |
| Local workstation offline | `ml_training` tasks queue in Redis indefinitely | System operates normally with existing models | Power on workstation; queued tasks process automatically |
| Insufficient training data | Sample count check at task start | Task returns `{"status": "skipped"}`; no training attempted | Wait for more data to accumulate |
| Redis unavailable | Celery connection errors | No new tasks dispatched; existing workers continue with cached models | Restore Redis; Beat reschedules missed tasks |

### 7.7 Dependency Isolation

The ML pipeline is carefully partitioned to ensure that Railway deployments never require GPU libraries:

| Dependency | Local (Predator) | Railway (Cloud) | Purpose |
|---|---|---|---|
| `torch` | Required | NOT installed | Training models |
| `transformers` | Required | NOT installed | FinBERT tokenizer + encoder |
| `onnxruntime` | Required (quantization) | Required (inference) | ONNX model execution |
| `xgboost` | Required (training) | Required (inference) | Tree model training + prediction |
| `numpy` | Required | Required | Array operations, deep hedging inference |
| `scipy` | Required | Required | BSM baseline (norm.cdf), Spearman correlation |
| `scikit-learn` | Required | Required | `roc_auc_score`, `accuracy_score` |
| `tokenizers` | Via transformers | Via onnxruntime | Rust-backed fast tokenization |

The `ml/deep_hedging/inference.py` module imports only `numpy` and `logging`, making it the most portable inference path. It can run in any Python environment without any ML framework installed.

---

## 8. References

Andersen, L. B. G. (2008). Simple and efficient simulation of the Heston stochastic volatility model. *Journal of Computational Finance*, 11(3), 1-42.

Araci, D. (2019). FinBERT: Financial sentiment analysis with pre-trained language models. *arXiv preprint arXiv:1908.10063*.

Arlot, S. and Celisse, A. (2010). A survey of cross-validation procedures for model selection. *Statistics Surveys*, 4, 40-79.

Artzner, P., Delbaen, F., Eber, J.-M., and Heath, D. (1999). Coherent measures of risk. *Mathematical Finance*, 9(3), 203-228.

Bailey, D. H., Borwein, J. M., Lopez de Prado, M., and Zhu, Q. J. (2014). Pseudo-mathematics and financial charlatanism: The effects of backtest overfitting on out-of-sample performance. *Notices of the American Mathematical Society*, 61(5), 458-471.

Buehler, H., Gonon, L., Teichmann, J., and Wood, B. (2019). Deep hedging. *Quantitative Finance*, 19(8), 1271-1291.

Chen, T. and Guestrin, C. (2016). XGBoost: A scalable tree boosting system. *Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 785-794.

Devlin, J., Chang, M.-W., Lee, K., and Toutanova, K. (2019). BERT: Pre-training of deep bidirectional transformers for language understanding. *Proceedings of NAACL-HLT 2019*, 4171-4186.

Gneiting, T. and Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *Journal of the American Statistical Association*, 102(477), 359-378.

Henderson, P., Islam, R., Bachman, P., Pineau, J., Precup, D., and Meger, D. (2018). Deep reinforcement learning that matters. *Proceedings of the AAAI Conference on Artificial Intelligence*, 32(1).

Heston, S. L. (1993). A closed-form solution for options with stochastic volatility with applications to bond and currency options. *The Review of Financial Studies*, 6(2), 327-343.

Hinton, G., Vinyals, O., and Dean, J. (2015). Distilling the knowledge in a neural network. *arXiv preprint arXiv:1503.02531*.

Huang, A. H., Rothe, S., and Goyal, T. (2023). Benchmarking large language models for financial text analysis. *Working paper*.

Kingma, D. P. and Ba, J. (2015). Adam: A method for stochastic optimization. *Proceedings of the International Conference on Learning Representations (ICLR)*.

Lord, R. and Kahl, C. (2010). Complex logarithms in Heston-like models. *Mathematical Finance*, 20(4), 671-694.

Loshchilov, I. and Hutter, F. (2019). Decoupled weight decay regularization. *Proceedings of the International Conference on Learning Representations (ICLR)*.

Loughran, T. and McDonald, B. (2011). When is a liability not a liability? Textual analysis, dictionaries, and 10-Ks. *The Journal of Finance*, 66(1), 35-65.

Lundberg, S. M. and Lee, S.-I. (2017). A unified approach to interpreting model predictions. *Advances in Neural Information Processing Systems*, 30.

Malo, P., Sinha, A., Korhonen, P., Wallenius, J., and Takala, P. (2014). Good debt or bad debt: Detecting semantic orientations in economic texts. *Journal of the Association for Information Science and Technology*, 65(4), 782-796.

Niculescu-Mizil, A. and Caruana, R. (2005). Predicting good probabilities with supervised learning. *Proceedings of the 22nd International Conference on Machine Learning*, 625-632.

Politis, D. N. and Romano, J. P. (1994). The stationary bootstrap. *Journal of the American Statistical Association*, 89(428), 1303-1313.

Sanh, V., Debut, L., Chaumond, J., and Wolf, T. (2019). DistilBERT, a distilled version of BERT: Smaller, faster, cheaper and lighter. *arXiv preprint arXiv:1910.01108*.

Sortino, F. A. and Price, L. N. (1994). Performance measurement in a downside risk framework. *The Journal of Investing*, 3(3), 59-64.
