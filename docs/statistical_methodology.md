# EdgeFinder: Statistical Methodology & Play-Money Discipline

*How we generate, test, and kill investment theses — with academic rigor
and zero real dollars at risk.*

---

## The Philosophy

EdgeFinder runs a simulation engine on play money. Every thesis starts as a
conjecture, gets tested against historical data, and either earns the right
to track forward — or gets killed. We don't paper-trade to feel smart. We
paper-trade so we can ask *why* something worked, *what* failed, and *what we
learned from it* with actual numbers behind the answer.

You can YOLO a paper stack on a momentum signal. That's fine — it's play
money. But when the thesis dies (and most of them die), the autopsy is
forensic. The Post-Mortem Priest doesn't care about your feelings. She
cares about your Sharpe ratio.

The rigor isn't in refusing to act. It's in refusing to lie to yourself
after you acted.

---

## 1. Hypothesis Formation: Signal Convergence

Every thesis begins as an observation: multiple independent signals are
firing on the same ticker at the same time. We call this **signal
convergence**.

### The Five Signal Sources

| # | Signal | Detection Rule | Source Data |
|---|--------|---------------|-------------|
| 1 | **Alerts** | >= 1 alert in lookback window | Price anomaly detectors |
| 2 | **Insider buying** | >= 1 buy trade filed | SEC Form 4 filings |
| 3 | **Filing concern** | Health score < 50 | SEC 10-K/10-Q NLP analysis |
| 4 | **Sentiment extreme** | \|avg sentiment\| > 0.3 | News article sentiment scores |
| 5 | **RSI extreme** | RSI < 35 (oversold) or > 70 (overbought) | 14-day RSI from price bars |

**Convergence threshold:** 1+ signals must fire within a 168-hour (7-day)
lookback window. This is deliberately loose — we'd rather generate a
thesis and kill it on data than miss a convergence because we demanded
triple confirmation upfront.

**Optional ML re-ranking:** When `signal_ranker_enabled` is true, an
XGBoost model re-ranks convergences by predicted probability of producing
a positive Sharpe on walkforward. This is a secondary filter, not a gate.

### Thesis Generation

When convergence fires, the Thesis Lord (Claude) receives the signal
package and generates a structured thesis:

- **Name** — 3-5 words, memorable ("RKLB Insider Momentum Squeeze")
- **Narrative** — 2-3 paragraphs explaining the edge
- **Entry criteria** — specific conditions for opening a position
- **Exit criteria** — profit target (%), stop loss (%), time exit (days),
  invalidation triggers
- **Time horizon** — typically 90 days
- **Position sizing** — conviction level (high/medium/low), max portfolio %
- **Risk factors** — what could make this wrong

The thesis is born in **PROPOSED** status. It has not been tested. It is a
conjecture, nothing more.

---

## 2. The Null Hypothesis

Here's where the rigor lives.

**H₀ (null hypothesis):** *This thesis has no edge. Its apparent returns
are indistinguishable from what you'd get by trading randomly on the same
price series with the same risk parameters.*

**H₁ (alternative):** *This thesis produces risk-adjusted returns that
are unlikely to be explained by chance alone.*

We do not test H₁ directly. We try to reject H₀. If we can't reject it,
the thesis is dead. If we can, the thesis earns the right to paper-trade
forward — not the right to be called "correct."

### How We Test It: Walk-Forward Backtest

A PROPOSED thesis is submitted to the backtester via `trigger_backtest`.
The backtest runs on 365 days of historical price data using **strict
point-in-time constraints** — at each timestep, the strategy sees only
data available up to that date. No lookahead. No survivorship bias.

**Default strategy parameters:**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Initial capital | $100,000 | Round number, makes % easy |
| Commission | 10 bps round-trip | Approximates retail brokerage |
| Slippage | 5 bps per trade | Market impact estimate |
| Max position | 10% of capital | Single-name concentration limit |
| Stop loss | 8% | Standard risk management |
| Take profit | 20% | Asymmetric risk/reward target |

**Entry signal (default):** 5-day return > 0 (simple momentum). Theses
can override this with custom entry/exit logic.

**Exit triggers:** Stop loss hit, take profit hit, custom exit signal,
or end of backtest period.

---

## 3. Metrics: How We Measure the Edge

After the walkforward completes, we compute six metrics. Each one answers
a different question.

### Sharpe Ratio — *Is the return worth the risk?*

$$\text{Sharpe} = \frac{\bar{r} - r_f}{\sigma} \times \sqrt{252}$$

Where $\bar{r}$ is mean daily return, $r_f$ is daily risk-free rate
(annualized 5% / 252), and $\sigma$ is daily standard deviation (ddof=1).
Annualized by $\sqrt{252}$.

**This is the kill switch.** Sharpe ≤ 0 means the thesis doesn't even
beat cash. Immediate termination.

### Sortino Ratio — *Is the return worth the downside risk?*

$$\text{Sortino} = \frac{\bar{r} - r_f}{\sigma_{\text{down}}} \times \sqrt{252}$$

Where:

$$\sigma_{\text{down}} = \sqrt{\frac{1}{N}\sum_{i=1}^{N}\min(r_i - r_f, 0)^2}$$

The denominator includes **all** periods — not just the negative ones.
Days where returns equal or exceed the risk-free rate contribute zero to
downside deviation, which is correct per Sortino & Price (1994). We fixed
an earlier implementation that used conditional std of negative returns
only, which systematically inflated the ratio by shrinking the denominator.

### Max Drawdown — *How bad does it get?*

$$\text{MDD} = \min_t \left(\frac{C_t - \max_{s \leq t} C_s}{\max_{s \leq t} C_s}\right)$$

Where $C_t$ is cumulative return at time $t$. Always negative or zero.
A thesis with Sharpe > 0 but MDD of -40% might survive the backtest but
probably shouldn't survive your attention span.

### Win Rate — *How often does a trade make money?*

$$\text{Win Rate} = \frac{\text{winning trades}}{\text{total trades}}$$

A blunt instrument. A 30% win rate with 5:1 profit factor prints money.
A 90% win rate that bleeds on the 10% can wipe you out. Never evaluate
this alone.

### Profit Factor — *How much do you make per dollar you lose?*

$$\text{Profit Factor} = \frac{\text{gross profit}}{\text{gross loss}}$$

- \> 1.0: net profitable
- \> 2.0: strong
- \> 3.0: exceptional (or overfitted — check sample size)

### Expectancy — *What's the average dollar per trade?*

$$E = (W \times \overline{\text{win}}) - ((1 - W) \times \overline{\text{loss}})$$

Where $W$ is win rate, $\overline{\text{win}}$ is average winning trade,
$\overline{\text{loss}}$ is average losing trade. This is the number that
tells you whether to keep trading the strategy.

---

## 4. Statistical Significance: The Monte Carlo Test

Computing a positive Sharpe isn't enough. The question is: *could this
Sharpe have happened by chance?*

### Method: Stationary Block Bootstrap (Politis & Romano 1994)

We do **not** use naive permutation. Naive permutation of daily returns
preserves the sample mean and variance exactly — every permuted sequence
produces the same Sharpe as the observed one. Statistical power: zero.
This was a real bug we caught and fixed.

**Algorithm:**

1. Compute observed Sharpe from the actual daily return series
2. Build overlapping blocks of size 10 (≈ 2 trading weeks)
3. For each of 10,000 bootstrap iterations:
   a. Sample blocks **with replacement**
   b. Concatenate sampled blocks, truncate to original series length
   c. Compute Sharpe on the bootstrap draw
4. p-value = fraction of bootstrap Sharpes ≥ observed Sharpe

**Why block bootstrap:** Resampling with replacement generates draws with
different means and variances, producing a meaningful null distribution.
Block structure preserves the serial correlation in daily returns (mean
reversion, momentum, volatility clustering) so the null isn't unrealistically
shuffled.

### Interpretation

| p-value | Interpretation |
|---------|----------------|
| < 0.01 | Very strong evidence of real edge |
| < 0.05 | Statistically significant |
| < 0.10 | Suggestive but not conclusive |
| ≥ 0.10 | Can't distinguish from luck |

### Current Decision Rule

**The pass/fail gate uses Sharpe > 0 only.** The p-value is computed,
logged, and displayed — but does not currently gate the transition to
PAPER_LIVE.

This is a deliberate choice, not an oversight. With 365 days of data and
a small number of trades, the Monte Carlo test has limited power. We log
it for review but don't auto-kill on p-value alone. As the system
accumulates more theses and more data, we expect to tighten this gate.

The p-value is there so that when you ask "was this luck?", the answer
is a number, not a feeling.

---

## 5. The Decision: Kill or Promote

After the backtest completes, the evaluation is mechanical:

```
IF no price data available:
    → KILLED ("No price data")

ELSE IF Sharpe ≤ 0:
    → KILLED ("Sharpe {x} ≤ 0 — thesis has no edge")

ELSE (Sharpe > 0):
    → PAPER_LIVE ("Sharpe {x:.3f} > 0 — thesis approved for paper trading")
```

Every decision is logged to the `simulation_logs` table with:
- Outcome (killed / paper_live)
- All six metrics (Sharpe, Sortino, MDD, win rate, profit factor, expectancy)
- Monte Carlo p-value
- Full trade-by-trade detail in the BacktestRun record
- Timestamp, agent name, disclaimer

Nothing is deleted. The log is append-only. You can reconstruct every
decision the system ever made.

### First Real Results (Feb 2026)

9 theses generated. 9 backtested. 1 survived.

| Thesis | Sharpe | Outcome |
|--------|--------|---------|
| RKLB Insider Momentum | +0.843 | **PAPER_LIVE** |
| 8 others | ≤ 0 | KILLED |

An 11% survival rate. That's not a problem — that's the system working.
The 8 dead theses generated data. The 1 survivor earned the right to
paper-trade, not the right to be believed.

---

## 6. Paper Trading: Forward Validation

A PAPER_LIVE thesis tracks real prices with simulated positions.

### Position Management

- **Entry:** Open against a $100K paper portfolio with position limits (max
  10% per name, configurable max open positions)
- **Stop loss & take profit:** Enforced daily via `check_stops()` against
  the latest closing price
- **Mark-to-market:** Daily revaluation of all open positions with P&L
  attribution by thesis
- **P&L tracking:** Both realized (closed trades) and unrealized (open
  positions), attributed to the thesis that generated them

### What This Tests

The backtest answers: "Would this have worked in the past?"

Paper trading answers: "Does it work going forward, out of sample?"

A thesis that backtested well but bleeds in paper trading is a thesis
that was overfitted to history. The paper period is the out-of-sample
validation that the backtest can't provide.

### Exit Conditions

| Condition | Transition | Who Triggers |
|-----------|-----------|--------------|
| Time horizon expires | PAPER_LIVE → RETIRED | `task_thesis_lifecycle_review` (daily) |
| Manual kill | Any status → KILLED | Thesis Lord or Post-Mortem Priest |
| Stop loss triggered | Position closed (STOPPED_OUT) | `task_check_paper_stops` (daily) |
| Take profit triggered | Position closed (STOPPED_OUT) | `task_check_paper_stops` (daily) |

---

## 7. The Autopsy: Post-Mortem & Learning

This is where EdgeFinder earns its rigor.

### The Post-Mortem Priest

A dedicated agent persona whose only job is forensic analysis. When a
thesis dies, the Priest:

1. Pulls the full decision log (every event from GENERATION through KILLED)
2. Pulls the backtest results (all six metrics, trade detail)
3. Generates a structured post-mortem: what happened, why, what we learned
4. Rates the confidence of each lesson ("how sure are we this is a pattern?")

The prompt is explicit: *"Never sugarcoat a failure. 'We got this wrong
because...' is your signature phrase."*

### Agent Memory

Lessons aren't just logged — they're persisted as **agent memories** with
four types:

| Type | Example |
|------|---------|
| **INSIGHT** | "RSI oversold + insider buying has 73% hit rate" |
| **PATTERN** | "Heston rho consistently < -0.6 for tech names" |
| **FAILURE** | "Thesis X failed because we ignored sector rotation" |
| **SUCCESS** | "Energy transition thesis outperformed by 12%" |

Each memory has a confidence score (0-1) and evidence chain linking back
to the simulation log entries that produced it.

### Memory Consolidation

Weekly, the system reviews recent simulation events and extracts durable
lessons. The prompt is specific: *"Only extract genuinely durable lessons.
Not every event is worth remembering. Focus on patterns that would help
future thesis generation and evaluation."*

These memories are injected into the Thesis Lord's context when generating
new theses — so the system literally learns from its failures.

### The Learning Loop

```
Signal Convergence → Thesis Generated → Backtest
       ↑                                    |
       |                              [Sharpe > 0?]
       |                               /        \
       |                           YES            NO
       |                            |              |
       |                      PAPER_LIVE        KILLED
       |                            |              |
       |                      [Track P&L]    [Post-Mortem]
       |                            |              |
       |                      [Retire/Kill]  [Extract Lesson]
       |                            |              |
       |                      [Post-Mortem]  [Store Memory]
       |                            |              |
       |                      [Store Memory]       |
       |                            \             /
       +---- memories injected ------\-----------/
```

---

## 8. Mathematical Machinery Under the Hood

The simulation engine isn't just a backtester. It includes publication-grade
quantitative models for options pricing, volatility analysis, and hedging.

### Black-Scholes (Baseline)

Standard BSM for European options. Newton-Raphson implied vol solver with
Brenner-Subrahmanyam initial guess. Converges in ~5 iterations. Greeks
computed analytically (Delta, Gamma, Vega, Theta, Rho).

### Heston Stochastic Volatility

Full Heston (1993) implementation with numerically stable characteristic
function (Albrecher et al. 2007). Calibrates to market IVs via
Levenberg-Marquardt with vega-weighted residuals.

**Branch cut fix (Lord & Kahl 2010 §4):** For extreme parameters, NumPy's
principal square root can select the wrong Riemann sheet. We enforce
Re(d) ≥ 0, which guarantees continuous branch selection and prevents
numerical blowup.

**Monte Carlo paths:** Quadratic-Exponential (QE) scheme (Andersen 2008)
instead of Euler-Maruyama. QE guarantees non-negative variance even when
the Feller condition is violated (which it almost always is in practice).

### Volatility Surface (SVI)

Gatheral (2004) SVI parameterization fitted via trust-region least squares.
Arbitrage detection for calendar spreads (total variance non-decreasing in
T) and butterfly spreads (call price convexity). Dupire (1994) local
volatility extracted via finite differences on the fitted surface.

### Deep Hedging

Buehler et al. (2019) neural hedging environment. The agent learns to
hedge a call option under transaction costs by minimizing CVaR (Conditional
Value-at-Risk, Rockafellar & Uryasev 2000) of the terminal P&L.

**Bug we caught:** `delta_change = abs(action_delta - action_delta)` —
always zero. Transaction costs were being ignored entirely. Fixed to
track `self._prev_delta` across timesteps.

### ML Quality Gates

| Model | Gate | Threshold |
|-------|------|-----------|
| FinBERT sentiment | Direction agreement | ≥ 52% (must beat coin flip) |
| FinBERT sentiment | Holdout MSE | ≤ 0.25 |
| FinBERT sentiment | Spearman correlation | ≥ 0.10 |
| XGBoost signal ranker | AUC-ROC | > 0.6 |

---

## 9. What We Don't Claim (and Why That Matters)

- **We don't claim our theses are correct.** We claim they survived a
  test that most don't.
- **We don't claim statistical significance on most theses.** Sample sizes
  are small. p-values are logged, not gated.
- **We don't claim the backtest predicts the future.** It tests whether
  the past is consistent with the thesis. That's all.
- **We don't claim the models are novel.** BSM, Heston, SVI, and block
  bootstrap are textbook. The value is in wiring them together into a
  system that generates, tests, and learns automatically.
- **We don't trade real money.** This is a simulation engine. Every
  position is play money. Every disclaimer says so.

---

## 10. What We Do Claim

- **Every thesis has a null hypothesis**, and we attempt to reject it
  with data.
- **Every decision is logged** in an append-only audit trail with full
  metrics and provenance.
- **Every dead thesis gets an autopsy**, and the lessons are persisted
  as agent memory that improves future generation.
- **The math is correct.** We peer-reviewed and fixed Sortino, Monte Carlo,
  Heston branch cuts, and deep hedging transaction costs. The fixes are
  documented and tested (510+ tests).
- **The system is honest about its limitations.** p-values are shown, not
  hidden. Sample sizes are small and we say so. Survival rates are low and
  we report them.

This is not an academic paper. It's an edge finder. The rigor isn't in
the formality — it's in the discipline of asking *"was this real, or was
this luck?"* every single time, and recording the honest answer.

---

## 11. Continuous Improvement: Does the System Get Smarter?

The honest answer: **partially, and in specific ways**. Three feedback
loops exist. One is real and closed. Two are wired but haven't accumulated
enough data to prove they work yet. And there are gaps we haven't closed.

### Loop 1: Agent Memory (Wired, Weekly Batch)

The Post-Mortem Priest reviews the simulation log weekly and extracts
durable lessons. Those lessons get injected into future thesis generation.

**How it works:**

```
SimulationLog events accumulate (continuous)
        ↓
Sunday 10 PM UTC: task_agent_memory_consolidation()
        ↓
Claude Haiku reviews last 7 days of events (max 100)
        ↓
Extracts structured memories: INSIGHT / PATTERN / FAILURE / SUCCESS
Each with a confidence score (0.0-1.0)
        ↓
Stored in agent_memories table
        ↓
Next thesis generation: inject_memories_into_prompt()
  → Recalls top 5 memories by confidence × keyword relevance
  → Injects as system prompt context for Claude Sonnet
  → Claude sees: "Last time RSI oversold + insider buying → 73% hit rate"
  → Generates thesis informed by accumulated institutional knowledge
```

**What the injection looks like:**

```
--- AGENT MEMORIES (from past experience) ---
💡 [INSIGHT] (confidence: 87%) RSI oversold + insider buying has 73% hit rate
⚠️ [FAILURE] (confidence: 95%) Thesis X failed because we ignored sector rotation
🔄 [PATTERN] (confidence: 71%) Heston rho < -0.6 for tech names signals vol divergence
✅ [SUCCESS] (confidence: 88%) Energy transition thesis outperformed by 12%
--- END MEMORIES ---
```

**Memory lifecycle:**

- **Birth:** Extracted weekly by Haiku from simulation events
- **Recall:** Ranked by confidence, filtered by keyword overlap with
  current context, top 5 injected
- **Access tracking:** Every recall increments `access_count` and updates
  `last_accessed` — frequently-used memories survive pruning
- **Death:** Memories older than 90 days with confidence < 0.3 AND no
  recent access are pruned. This isn't decay — it's "use it or lose it."

**Honest assessment:** This loop is wired end-to-end but **only feeds
into thesis generation** (the Thesis Lord persona). Chat personas, the
daily briefing, and other agents don't see accumulated memories. The
consolidation runs weekly, not in real-time. And confidence is static —
set once by Haiku, never updated based on whether the memory actually
helped.

### Loop 2: Signal Ranker (The Only True ML Feedback Loop)

An XGBoost model that literally learns which signal configurations
produce profitable theses — using EdgeFinder's own backtest outcomes
as labels.

**The closed loop:**

```
Week N:
  Signal convergence detected → Thesis T generated
  Thesis T backtested → Sharpe = -0.12 → KILLED
  Label: 0 (negative Sharpe = bad signal config)

Week N+1 (Sunday 3 AM):
  task_train_signal_ranker() fires
  Queries: all SimulatedTheses with completed backtests
  For each: extract 19 features from generation_context
    - signal_count, has_insider_buying, rsi_value, sentiment_score,
      sector_hash, filing_health_score, etc.
  Label: 1 if best Sharpe > 0, else 0
  Train XGBoost (100 trees, depth 4, 80/20 time-split)
  If AUC-ROC > 0.6 → activate new model version

Week N+2:
  New convergence detected → rank_convergences() called
  Signal ranker v3 predicts P(positive Sharpe) = 0.74
  High-probability convergences ranked first
  Low-probability ones filtered below min_probability threshold
  → System generates fewer but higher-quality theses
```

**This is genuinely self-improving.** The model uses EdgeFinder's own
outcomes (backtest Sharpe from `backtest_runs` table) to predict which
future signal configurations are worth pursuing. Each completed backtest
adds one labeled training example. The model retrains weekly.

**Current bottleneck:** The signal ranker needs >= 50 labeled theses to
retrain. As of March 2026, we have 9 completed backtests. The loop is
wired but data-starved. It won't start improving predictions until we
accumulate ~50 thesis outcomes — at current generation rates, that's
roughly 2-3 months of operation.

**Quality gate:** AUC-ROC must exceed 0.6 or the new model version isn't
activated. The old version stays live. This prevents a bad training run
from degrading the system.

### Loop 3: Lesson Teaching (Wired, But Doesn't Feed Back)

The Edger teaches one quantitative concept per daily briefing, drawn from
a 20-concept library (Sharpe ratio, Sortino, RSI, Heston model, CVaR,
signal convergence, etc.). Each taught concept is recorded in
`agent_memories` so it's never repeated.

**The concept selection is smart:**

- Tracks what's already been taught via `lesson_taught` memory type
- Prioritizes concepts that match current data (if a backtest just ran,
  teach Sharpe ratio; if vol surface was calibrated, teach vol skew)
- Cycles through the full library before repeating

**But the lessons don't close the loop.** Teaching a user about Sortino
doesn't make the backtester compute Sortino differently. It's a
knowledge-sharing channel, not a feedback mechanism. The Edger's chat
sessions start fresh each time — she doesn't carry forward what she
taught yesterday.

### What Doesn't Improve (Yet)

| Gap | Impact |
|-----|--------|
| **Chat personas don't see memories** | The PM, Analyst, Vol Slayer, etc. start every conversation without institutional context. Only thesis_lord gets memory injection. |
| **No model-thesis lineage** | SimulatedThesis doesn't record which signal ranker version was active at generation time. We can't attribute improvement to a specific model update. |
| **Static confidence scores** | Memory confidence is set once by Haiku and never updated. A memory that led to 5 successful theses has the same confidence as one that led to 5 failures. |
| **Keyword search, not semantic** | Memory recall uses word overlap, not embeddings. "tech sector vol crush" won't match a memory about "technology implied volatility compression." |
| **No real-time learning** | Everything batches weekly. A thesis killed on Monday generates a memory on Sunday. Six days of thesis generation happen without that lesson. |
| **Sentiment model isn't self-improving** | FinBERT retrains on new news articles, but the labels come from the Haiku API, not from whether past predictions actually predicted price moves. It's periodic retraining, not a feedback loop. |
| **Deep hedging trains on synthetic data** | The hedging policy learns from Monte Carlo paths, not real paper-trading outcomes. |

### The Improvement Trajectory

The system is designed to get smarter along two axes:

**Axis 1: Institutional memory (agent memories)**
- Every dead thesis teaches something
- Every successful thesis reinforces a pattern
- The Thesis Lord sees these memories when generating new theses
- Over time, the system accumulates "scar tissue" — it's seen these
  signals before and knows which combinations tend to fail

**Axis 2: Statistical learning (signal ranker)**
- Each backtest adds a labeled training example
- The XGBoost model learns which feature combinations predict positive
  Sharpe
- Once we cross the 50-thesis threshold, the model starts filtering out
  low-probability convergences before they waste a backtest
- This is a genuine, measurable improvement: fewer theses generated,
  higher survival rate

**Where we are now (March 2026):**

- 9 backtested theses (need 50 for signal ranker activation)
- 0 agent memories in production (consolidation hasn't had enough events)
- 60+ simulation log entries (accumulating raw material)
- The loops are wired. The data is accumulating. The improvement hasn't
  started yet.

The system doesn't get smarter by magic. It gets smarter by killing
theses, recording why they died, and making sure the next thesis
generation sees the body. That pipeline is built. It just needs more
bodies.

---

## 12. The Full Picture

```
                    ┌─────────────────────┐
                    │   SIGNAL SOURCES     │
                    │  alerts, insider,    │
                    │  filings, sentiment, │
                    │  RSI                 │
                    └────────┬────────────┘
                             ↓
                    ┌────────────────────┐
                    │ SIGNAL CONVERGENCE  │◄──── signal ranker filters
                    │ (1+ signals fire)   │      (when >= 50 theses)
                    └────────┬───────────┘
                             ↓
                    ┌────────────────────┐
                    │ THESIS GENERATION   │◄──── agent memories injected
                    │ (Claude + memories) │      (weekly consolidation)
                    └────────┬───────────┘
                             ↓
                    ┌────────────────────┐
                    │ BACKTEST            │
                    │ 365-day walkforward │
                    │ Sharpe/Sortino/MDD  │
                    │ Monte Carlo p-value │
                    └────────┬───────────┘
                             ↓
                   ┌─────────┴──────────┐
                   │                    │
              Sharpe > 0           Sharpe ≤ 0
                   │                    │
                   ↓                    ↓
            ┌─────────────┐      ┌──────────┐
            │ PAPER_LIVE   │      │  KILLED   │
            │ track P&L    │      │           │
            │ daily stops  │      └─────┬────┘
            │ mark-to-mkt  │            │
            └──────┬──────┘            │
                   │                    │
                   ↓                    ↓
            ┌─────────────┐      ┌──────────────┐
            │ RETIRE/KILL  │      │ POST-MORTEM   │
            └──────┬──────┘      │ forensic why  │
                   │              └──────┬───────┘
                   ↓                     ↓
            ┌──────────────┐     ┌───────────────┐
            │ POST-MORTEM   │     │ SIMULATION LOG │
            └──────┬───────┘     └───────┬───────┘
                   │                     │
                   └────────┬────────────┘
                            ↓
                   ┌────────────────────┐
                   │ WEEKLY CONSOLIDATION│
                   │ Haiku reviews events│
                   │ extracts lessons    │
                   └────────┬───────────┘
                            ↓
                   ┌────────────────────┐
                   │ AGENT MEMORIES      │──────► thesis generation
                   │ insight/pattern/    │
                   │ failure/success     │
                   └────────────────────┘
                            +
                   ┌────────────────────┐
                   │ SIGNAL RANKER       │──────► convergence filtering
                   │ XGBoost on outcomes │
                   │ (weekly retrain)    │
                   └────────────────────┘
```

---

## References

- Albrecher, H., Mayer, P., Schoutens, W. & Tistaert, J. (2007). The little Heston trap. *Wilmott Magazine*.
- Andersen, L. (2008). Simple and efficient simulation of the Heston stochastic volatility model. *J. Computational Finance* 11(3).
- Buehler, H., Gonon, L., Teichmann, J. & Wood, B. (2019). Deep hedging. *Quantitative Finance* 19(8).
- Dupire, B. (1994). Pricing with a smile. *Risk* 7(1), 18–20.
- Gatheral, J. (2004). A parsimonious arbitrage-free implied volatility parameterization. Presentation at Global Derivatives & Risk Management.
- Heston, S. (1993). A closed-form solution for options with stochastic volatility. *Review of Financial Studies* 6(2), 327–343.
- Lord, R. & Kahl, C. (2010). Complex logarithms in Heston-like models. *Mathematical Finance* 20(4), 671–694.
- Politis, D.N. & Romano, J.P. (1994). The stationary bootstrap. *J. American Statistical Association* 89(428), 1303–1313.
- Rockafellar, R.T. & Uryasev, S. (2000). Optimization of conditional value-at-risk. *J. Risk* 2, 21–42.
- Sortino, F.A. & Price, L.N. (1994). Performance measurement in a downside risk framework. *J. Investing* 3(3), 59–64.
