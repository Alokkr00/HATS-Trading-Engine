# Statistical Validation Framework

> **Owner:** ML Engineer  
> **Sprint:** 1 (Foundation)  
> **Status:** Draft v1.0  
> **Last Updated:** 2026-07-02  

---

## 1. Purpose

Every strategy — classical or ML-based — must pass this validation framework before
progressing from backtest to paper trading to live capital. The framework exists to
answer one question with statistical rigour:

**"Is the observed performance distinguishable from luck?"**

This document defines the protocols, metrics, thresholds, and red flags that govern
that decision.

---

## 2. Walk-Forward Validation Protocol

### 2.1 Why Walk-Forward (Not Random Split)

Financial time series are non-stationary and auto-correlated. A random train/test
split introduces look-ahead bias and inflates performance. Walk-forward validation
respects the arrow of time.

### 2.2 Configuration Parameters

| Parameter | Symbol | Default | Rationale |
|---|---|---|---|
| Training window | `W_train` | 3 years (756 trading days) | Captures multiple regimes (bull, bear, sideways) |
| Test window | `W_test` | 6 months (126 trading days) | Long enough for 30+ trades on most strategies |
| Embargo period | `W_embargo` | 5 trading days | Prevents information leakage from autocorrelation at boundary |
| Step size | `W_step` | 3 months (63 trading days) | Controls overlap between consecutive test folds |
| Min folds | `N_folds` | ≥ 6 | Statistical reliability; fewer ⇒ unreliable aggregate |

### 2.3 Walk-Forward Fold Layout

```
Timeline: ──────────────────────────────────────────────────────►

Fold 1:  [========= TRAIN (3y) =========]--E--[== TEST (6m) ==]
Fold 2:       [========= TRAIN (3y) =========]--E--[== TEST ==]
Fold 3:            [========= TRAIN (3y) =========]--E--[TEST ]
  ...

E = Embargo gap (5 trading days, data discarded)
```

### 2.4 Expanding vs. Rolling Window

| Mode | When to Use |
|---|---|
| **Rolling** (fixed `W_train`) | Default. Keeps model exposure to recent regime constant. |
| **Expanding** (growing `W_train`) | Use when strategy has very few parameters and benefits from more data. Report both; prefer rolling if results diverge. |

### 2.5 Per-Fold vs. Aggregate Metrics

**Per-fold (reported individually):**
- Sharpe ratio (annualized)
- Max drawdown (depth and duration in days)
- Number of trades
- Win rate
- Profit factor

**Aggregate (across all folds):**
- Mean and median Sharpe across folds
- Standard deviation of Sharpe across folds
- Worst-fold Sharpe (critical: must be > 0)
- Combined equity curve (concatenated OOS segments)
- Aggregate max drawdown on combined OOS curve
- t-statistic of mean Sharpe vs. zero (see §3.3)

### 2.6 Embargo Period Details

The embargo period exists because:
1. Strategies using lagged features (e.g., 20-day MA) create serial dependence
   spanning the train/test boundary.
2. Positions opened near the end of training may still be open at test start.

**Rule:** Discard `W_embargo` days of data at the end of each training set AND
at the beginning of each test set. This means `2 × W_embargo` days are unused per
boundary.

For strategies using features with lookback `L` days, set:
```
W_embargo = max(5, L)
```

### 2.7 Purged K-Fold (for ML Models in Future Sprints)

When ML models are introduced, standard walk-forward is augmented with **purged
k-fold cross-validation** (de Prado, 2018):

1. Labels are assigned to bars with a known outcome horizon `h`.
2. Any training sample whose label period overlaps a test sample's label period
   is purged from the training set.
3. An additional embargo of `W_embargo` bars is applied after each purged region.

This will be implemented in the ML pipeline (Sprint 5+), but the data pipeline
must preserve timestamps at bar-level granularity to support it.

---

## 3. Overfitting Detection

### 3.1 Deflated Sharpe Ratio (DSR)

The standard Sharpe ratio does not account for:
- The number of strategy variants tried (multiple testing)
- Non-normality of returns (skewness, kurtosis)
- The length of the backtest

**Deflated Sharpe Ratio** (Bailey & de Prado, 2014) adjusts the observed Sharpe:

```
DSR = Φ( (SR_obs - SR_benchmark) / SE(SR) )

where:
  SR_obs        = observed annualized Sharpe ratio
  SR_benchmark  = expected max Sharpe under null (see §3.2)
  SE(SR)        = √((1 - γ₃·SR + (γ₄-1)/4·SR²) / T)
  γ₃            = skewness of returns
  γ₄            = kurtosis of returns
  T             = number of return observations
  Φ             = standard normal CDF
```

**Decision rule:** DSR > 0.95 (i.e., p < 0.05) → strategy passes.

### 3.2 Expected Maximum Sharpe Under Null

When `N` independent strategy variants are tried, the expected maximum Sharpe
under the null hypothesis of zero expected returns is:

```
E[max(SR)] ≈ √(2·ln(N)) - (ln(π) + ln(ln(N))) / (2·√(2·ln(N)))

(Euler-Mascheroni approximation for N > 1)
```

**We MUST track `N`** — the total number of parameter combinations, strategy
variants, and feature sets tried — even across sprints. This is logged in the
experiment tracker.

### 3.3 Multiple Hypothesis Testing Correction

When evaluating multiple strategies or parameter sets simultaneously:

| Method | When to Use | Adjustment |
|---|---|---|
| **Bonferroni** | Conservative; few hypotheses (< 20) | α_adj = α / N |
| **Holm-Bonferroni** | Default; step-down procedure, more powerful | Rank p-values; reject p_(i) if p_(i) ≤ α / (N - i + 1) |
| **Benjamini-Hochberg (FDR)** | Many hypotheses (> 50); controls false discovery rate | Rank p-values; reject p_(i) if p_(i) ≤ (i/N)·α |

**Default:** Use Holm-Bonferroni for strategy selection. Track all trials.

### 3.4 Minimum Trade Count for Statistical Significance

A strategy's win rate `p` is a binomial proportion. The 95% confidence interval
width for `p` with `n` trades is approximately:

```
CI_width ≈ 2 × 1.96 × √(p(1-p)/n)
```

| Trades (n) | CI width (p=0.55) | Reliable? |
|---|---|---|
| 10 | ±0.31 | ❌ Useless |
| 30 | ±0.18 | ⚠️ Marginal |
| 100 | ±0.10 | ✅ Minimum acceptable |
| 300 | ±0.06 | ✅ Good |
| 1000 | ±0.03 | ✅ Excellent |

**Rule:** Minimum **100 trades** across the combined OOS test folds for
a strategy to be considered statistically evaluated. If a strategy trades
infrequently, extend the backtest period rather than lower the threshold.

For the Sharpe ratio itself, a t-test is applied:
```
t = SR × √T  (where T is years of OOS data)

Require t > 1.96 (p < 0.05, two-sided)
⟹ SR ≥ 1.96 / √T
```

With 3 years of OOS data: SR ≥ 1.13 required. With 5 years: SR ≥ 0.88.

### 3.5 Bootstrap Confidence Intervals

For all key metrics, compute bootstrap 95% confidence intervals:

1. Resample the OOS daily returns (block bootstrap with block size = 21 days
   to preserve autocorrelation).
2. Recompute the metric on each bootstrap sample.
3. Report the 2.5th and 97.5th percentiles.
4. Repeat for B = 10,000 bootstrap samples.

**Block bootstrap** is essential — i.i.d. bootstrap destroys serial dependence
and understates uncertainty.

Metrics to bootstrap:
- Annualized Sharpe ratio
- Annualized return
- Maximum drawdown
- Calmar ratio
- Win rate

### 3.6 Combinatorially Symmetric Cross-Validation (CSCV)

CSCV (Bailey et al., 2017) estimates the **Probability of Backtest Overfitting
(PBO)**:

1. Split the OOS equity curve into `2S` contiguous sub-periods.
2. Form all `C(2S, S)` combinations of S sub-periods for "in-sample" and
   the remaining S for "out-of-sample".
3. For each combination, rank strategy variants by IS performance and measure
   whether the IS-best variant also performs well OOS.
4. PBO = fraction of combinations where the IS-best variant underperforms OOS
   median.

**Decision rule:** PBO < 0.40 → acceptable. PBO > 0.50 → strategy is likely
overfit; do not proceed.

**Note:** CSCV is computationally expensive. Apply only to final strategy
candidates, not during exploratory parameter sweeps.

---

## 4. Performance Metrics — Ranked by Importance

### 4.1 Tier 1: Gate Metrics (Must Pass)

| # | Metric | Definition | Threshold |
|---|---|---|---|
| 1 | **OOS Sharpe Ratio** | Annualized SR on concatenated OOS folds, net of transaction costs | > 0.8 (after costs) |
| 2 | **Maximum Drawdown** | Largest peak-to-trough decline in OOS equity curve | < 20% (depth); < 6 months (duration) |
| 3 | **Number of Trades** | Total trades across all OOS folds | ≥ 100 |
| 4 | **Deflated Sharpe Ratio** | DSR as defined in §3.1 | > 0.95 |

If ANY Tier 1 metric fails, the strategy is rejected. No exceptions.

### 4.2 Tier 2: Ranking Metrics (Used to Compare Passing Strategies)

| # | Metric | Definition | Better ↑/↓ |
|---|---|---|---|
| 5 | **Win Rate** | % of trades with positive PnL | ↑ (> 50% preferred) |
| 6 | **Profit Factor** | Gross profit / gross loss | ↑ (> 1.5 preferred) |
| 7 | **Calmar Ratio** | Annualized return / max drawdown | ↑ (> 1.0 preferred) |
| 8 | **Sortino Ratio** | Return / downside deviation | ↑ |
| 9 | **Avg Win / Avg Loss** | Ratio of mean winning trade to mean losing trade | ↑ (> 1.0 preferred) |
| 10 | **Max Drawdown Duration** | Longest time to recover from drawdown | ↓ |

### 4.3 Tier 3: Diagnostic Metrics (Monitored, Not Gated)

| # | Metric | Definition | Purpose |
|---|---|---|---|
| 11 | **Turnover** | Average daily portfolio turnover (% of AUM) | Cost sensitivity |
| 12 | **Skewness of Returns** | Third moment of daily returns | Tail risk profile |
| 13 | **Kurtosis of Returns** | Fourth moment of daily returns | Fat tail exposure |
| 14 | **Beta to SPY** | Regression beta of strategy returns vs. SPY | Market exposure |
| 15 | **Max Consecutive Losses** | Longest streak of losing trades | Psychological risk |

### 4.4 Transaction Cost Model

All performance metrics MUST be computed **after** transaction costs. Default model:

```
Per-trade cost = commission + slippage + market impact

Assumptions (conservative):
  Commission:    $0.00 per share (Alpaca, commission-free)
  Slippage:      0.05% of trade value (half the bid-ask spread)
  Market impact: 0.02% of trade value (small account assumption)
  Total:         ~0.07% per side → ~0.14% round-trip

For backtesting, apply 0.10% per side (0.20% round-trip) as conservative default.
```

Run a **cost sensitivity analysis**: sweep cost from 0.00% to 0.30% per side and
report the breakeven cost (where Sharpe = 0).

---

## 5. Red Flags Checklist

Before any strategy advances from backtest to paper trading, manually review:

### 5.1 Automatic Rejections (Hard Fails)

| # | Red Flag | Threshold | Why It Matters |
|---|---|---|---|
| R1 | Sharpe too high | SR > 2.0 on daily returns | Almost certainly overfit or has a bug |
| R2 | Too few trades | < 30 trades in any single test fold | Insufficient sample; CI too wide |
| R3 | OOS degradation | OOS SR < 50% of IS SR | Classic overfitting signature |
| R4 | Single-symbol dependence | Strategy only profitable on ≤ 3 symbols | Not generalizable; curve-fitted |
| R5 | Look-ahead bias detected | Any feature uses future data | Fatal flaw; invalidates all results |

### 5.2 Warnings (Require Explanation)

| # | Red Flag | Threshold | Mitigation |
|---|---|---|---|
| W1 | High parameter sensitivity | Performance varies > 50% with ±10% param change | Run sensitivity analysis; use param-averaged performance |
| W2 | Regime dependence | Works in bull market only (or bear only) | Test on regime-specific subsets; require profitability in ≥ 2 regimes |
| W3 | Drawdown concentration | > 50% of max drawdown in a single week | Examine tail events; add circuit breaker |
| W4 | Low profit factor | PF between 1.0 and 1.2 | Fragile edge; small cost increase kills profitability |
| W5 | High correlation to benchmark | Beta > 0.8 to SPY | Not generating alpha; just taking beta risk |
| W6 | Inconsistent fold performance | Sharpe std across folds > mean Sharpe | Strategy is unstable across time periods |
| W7 | Short backtest period | < 5 years total data | May miss regime changes; extend if possible |

### 5.3 Parameter Sensitivity Protocol

For each tunable parameter `θ`:

1. Define a ±20% perturbation range around the selected value.
2. Evaluate OOS Sharpe at 5 points within the range.
3. Compute `sensitivity = std(SR) / mean(SR)` across perturbations.
4. If sensitivity > 0.30 → parameter is **brittle**. Flag W1.
5. Prefer the parameter value that maximises **median** OOS Sharpe across
   perturbations (not the peak).

---

## 6. Validation Pipeline Architecture

### 6.1 Execution Flow

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│  Raw OHLCV   │────▶│  Feature     │────▶│  Walk-Forward    │
│  Data        │     │  Pipeline    │     │  Splitter        │
└─────────────┘     └─────────────┘     └────────┬─────────┘
                                                  │
                              ┌────────────────────┼────────────────────┐
                              ▼                    ▼                    ▼
                        ┌──────────┐         ┌──────────┐        ┌──────────┐
                        │  Fold 1  │         │  Fold 2  │   ...  │  Fold N  │
                        │ Train→Test│        │ Train→Test│       │ Train→Test│
                        └────┬─────┘         └────┬─────┘        └────┬─────┘
                             │                    │                    │
                             ▼                    ▼                    ▼
                     ┌──────────────────────────────────────────────────────┐
                     │           Metric Aggregation & Reporting            │
                     └──────────────────────┬──────────────────────────────┘
                                            │
                              ┌──────────────┼──────────────┐
                              ▼              ▼              ▼
                        ┌──────────┐   ┌──────────┐   ┌──────────┐
                        │ Deflated │   │ Bootstrap │   │ Red Flag │
                        │ Sharpe   │   │ CIs      │   │ Checker  │
                        └──────────┘   └──────────┘   └──────────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │  PASS / FAIL    │
                                   │  Decision       │
                                   └─────────────────┘
```

### 6.2 Implementation Plan

| Component | Sprint | Owner | Notes |
|---|---|---|---|
| Walk-Forward Splitter | 2 | ML Engineer | Pure Python, no ML dependencies |
| Per-Fold Metric Calculator | 2 | ML Engineer | Uses pandas/numpy only |
| Aggregate Metric Reporter | 2 | ML Engineer | Markdown/JSON output |
| Deflated Sharpe Module | 3 | ML Engineer | scipy.stats dependency |
| Bootstrap CI Module | 3 | ML Engineer | Block bootstrap implementation |
| Red Flag Checker | 3 | ML Engineer | Rule-based, configurable thresholds |
| CSCV Module | 4+ | ML Engineer | Only for final candidates |
| Experiment Tracker | 2 | ML Engineer | Tracks N (total trials) for DSR |

### 6.3 Data Requirements for Validation Pipeline

The data pipeline (built by Data Engineer) must provide:

1. **OHLCV bars with timestamps** — datetime index, timezone-aware (US/Eastern)
2. **Adjusted prices** — split and dividend adjusted for backtesting
3. **Unadjusted prices** — for live trading signal generation
4. **No forward-fill on missing days** — preserve actual trading calendar
5. **Corporate action flags** — to detect regime breaks in individual stocks
6. **At least 5 years of history** — for 6+ walk-forward folds with 3-year train

---

## 7. Strategy Promotion Workflow

```
         BACKTEST              PAPER TRADING           LIVE
        ┌──────────┐          ┌──────────────┐       ┌──────────┐
        │ Develop & │  PASS   │ Run 30+ days │ PASS  │ Start w/ │
        │ Validate  │────────▶│ Track metrics│──────▶│ 10% size │
        │ (this doc)│         │ Compare to BT│       │ Scale up │
        └──────────┘          └──────────────┘       └──────────┘
              │                      │                     │
           FAIL                   FAIL                  FAIL
              │                      │                     │
              ▼                      ▼                     ▼
         [Reject or           [Return to BT            [Reduce or
          Iterate]             for analysis]            Halt]
```

### Paper Trading Gate

After backtest validation passes, paper trade for minimum 30 calendar days:
- OOS Sharpe must be within 1 standard deviation of backtest OOS Sharpe
- Max drawdown must not exceed 1.5× backtest max drawdown
- Number of trades must be within 50% of expected rate

### Live Trading Gate

After paper trading passes:
- Start with 10% of intended position size
- Scale to 25% → 50% → 100% over 4 weeks if metrics hold
- Automatic halt if drawdown exceeds 15% at any scale

---

## 8. Experiment Logging Requirements

Every backtest run MUST log:

```json
{
  "experiment_id": "uuid",
  "timestamp": "ISO-8601",
  "strategy_name": "MA_crossover_v1",
  "strategy_version": "1.0.0",
  "parameters": {"fast_window": 10, "slow_window": 50},
  "universe": ["SPY", "QQQ", "AAPL"],
  "data_start": "2018-01-01",
  "data_end": "2023-12-31",
  "walk_forward_config": {
    "train_window_days": 756,
    "test_window_days": 126,
    "embargo_days": 5,
    "n_folds": 8
  },
  "per_fold_metrics": [ ... ],
  "aggregate_metrics": {
    "oos_sharpe": 1.05,
    "oos_sharpe_ci_95": [0.72, 1.38],
    "max_drawdown_pct": -12.3,
    "total_trades": 247,
    "deflated_sharpe": 0.97,
    "win_rate": 0.54,
    "profit_factor": 1.65,
    "calmar_ratio": 1.42
  },
  "red_flags_triggered": ["W2"],
  "total_trials_to_date": 15,
  "decision": "PASS",
  "notes": "Regime dependence in 2020 COVID period; acceptable given V-recovery"
}
```

---

## 9. Glossary

| Term | Definition |
|---|---|
| **OOS** | Out-of-sample: data not used during strategy development or parameter tuning |
| **IS** | In-sample: data used for training/optimization |
| **DSR** | Deflated Sharpe Ratio — Sharpe adjusted for multiple testing, skewness, kurtosis |
| **PBO** | Probability of Backtest Overfitting — CSCV-based estimate |
| **Embargo** | Gap between train and test sets to prevent information leakage |
| **Purging** | Removing train samples whose label horizon overlaps with test samples |
| **Walk-forward** | Rolling or expanding window train/test methodology respecting time order |
| **CSCV** | Combinatorially Symmetric Cross-Validation |
| **Block bootstrap** | Bootstrap resampling that preserves serial dependence using contiguous blocks |

---

## 10. References

1. Bailey, D. H., & López de Prado, M. (2014). "The Deflated Sharpe Ratio."
   *Journal of Portfolio Management*, 40(5), 94–107.
2. Bailey, D. H., Borwein, J., López de Prado, M., & Zhu, Q. J. (2017).
   "The Probability of Backtest Overfitting." *Journal of Computational Finance*, 20(4).
3. López de Prado, M. (2018). *Advances in Financial Machine Learning.* Wiley.
4. Harvey, C. R., Liu, Y., & Zhu, H. (2016). "…and the Cross-Section of Expected
   Returns." *Review of Financial Studies*, 29(1), 5–68.
5. White, H. (2000). "A Reality Check for Data Snooping." *Econometrica*, 68(5), 1097–1126.
