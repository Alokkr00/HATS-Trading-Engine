# Feature Engineering Plan — ML Signals from OHLCV Data

> **Owner:** ML Engineer  
> **Sprint:** 1 (Planning Only — Implementation in Sprint 5+)  
> **Status:** Draft v1.0  
> **Last Updated:** 2026-07-02  

---

## 1. Purpose

This document catalogs the ML features that **can** be computed from OHLCV
(Open, High, Low, Close, Volume) data for future ML-based signal generation.

**This is a planning document only.** No features will be built until:
1. Classical strategies (MA crossover, RSI, Bollinger) establish a baseline.
2. The validation framework (see `docs/validation_framework.md`) is implemented.
3. There is evidence that ML can improve upon the classical baseline.

The goal is to ensure the data pipeline stores sufficient data granularity
to support these features when the time comes.

---

## 2. Design Principles

1. **No look-ahead bias.** Every feature is computed using only data available
   at time `t`. No future data leaks through centering, normalization, or
   label construction.
2. **Point-in-time correctness.** Features use adjusted prices as they were
   known at time `t`, not retroactively adjusted values (survivorship bias,
   split adjustments applied after the fact).
3. **Multiple lookback windows.** Each feature family is computed over several
   windows (5, 10, 21, 63, 126, 252 days) to capture short- and long-term
   dynamics.
4. **Stationarity.** Raw prices are non-stationary. Features should be
   transformations that are (approximately) stationary: returns, z-scores,
   percentile ranks, ratios.
5. **Rank-normalize where possible.** Cross-sectional rank normalization
   reduces outlier impact and is robust to regime changes.

---

## 3. Feature Taxonomy

### 3.1 Price-Based Features

These capture momentum, mean reversion, and trend characteristics.

| Feature | Formula / Description | Lookback Windows | Stationarity |
|---|---|---|---|
| **Simple return** | `r_t = (P_t - P_{t-k}) / P_{t-k}` | 1, 5, 10, 21, 63, 126, 252 | ✅ Stationary |
| **Log return** | `lr_t = ln(P_t / P_{t-k})` | 1, 5, 10, 21, 63 | ✅ Stationary |
| **Cumulative return** | Cumulative sum of log returns over window | 21, 63, 126, 252 | ✅ Stationary |
| **Momentum (rate of change)** | `(P_t - P_{t-k}) / P_{t-k} × 100` | 10, 21, 63, 126, 252 | ✅ Stationary |
| **RSI** | Relative Strength Index (Wilder) | 14, 21 | ✅ Bounded [0, 100] |
| **MACD signal** | MACD line − Signal line (normalized by price) | (12, 26, 9) | ⚠️ Normalize |
| **Distance from SMA** | `(P_t - SMA_k) / SMA_k` | 10, 20, 50, 200 | ✅ Stationary |
| **Distance from EMA** | `(P_t - EMA_k) / EMA_k` | 10, 20, 50 | ✅ Stationary |
| **Bollinger %B** | `(P_t - BB_lower) / (BB_upper - BB_lower)` | 20 (2σ) | ✅ Bounded |
| **52-week high proximity** | `P_t / max(P_{t-252:t})` | 252 | ✅ Bounded [0, 1] |
| **52-week low proximity** | `P_t / min(P_{t-252:t})` | 252 | ✅ Bounded |
| **Fractional differentiation** | `d`-order differencing (0 < d < 1) | Per series; `d` chosen to pass ADF at 5% | ✅ By construction |

#### Notes on Fractional Differentiation
Standard differencing (`d=1`) achieves stationarity but destroys memory.
Fractional differentiation (de Prado, 2018, Ch. 5) finds the minimum `d` that
makes the series stationary while preserving maximum predictive signal. This
is a high-priority feature for ML models.

### 3.2 Volatility Features

Volatility is often more predictable than returns. These features capture
the volatility regime.

| Feature | Formula / Description | Lookback Windows | Stationarity |
|---|---|---|---|
| **Realised volatility** | `std(log_returns) × √252` | 5, 10, 21, 63 | ✅ Stationary |
| **ATR (Average True Range)** | Wilder's ATR / Close (normalized) | 14, 21 | ✅ Stationary |
| **Parkinson volatility** | `√(1/(4n·ln2) × Σ(ln(H/L))²)` | 10, 21 | ✅ Stationary |
| **Garman-Klass volatility** | Uses OHLC: `0.5·ln(H/L)² - (2ln2-1)·ln(C/O)²` | 10, 21 | ✅ Stationary |
| **Yang-Zhang volatility** | Combines overnight and intraday volatility | 21 | ✅ Stationary |
| **Volatility ratio** | `vol_short / vol_long` (e.g., 5d / 63d) | (5, 63), (10, 63), (21, 252) | ✅ Stationary |
| **Volatility percentile** | Percentile rank of current vol vs. trailing window | 252 | ✅ Bounded |
| **Intraday range** | `(H_t - L_t) / C_t` | 1, 5, 21 | ✅ Stationary |
| **Overnight gap** | `(O_t - C_{t-1}) / C_{t-1}` | 1, 5 | ✅ Stationary |
| **GARCH(1,1) conditional vol** | Fitted conditional volatility | Rolling fit, 252d | ⚠️ Model-based |

#### Parkinson vs. Garman-Klass vs. Yang-Zhang
- **Parkinson**: Uses only H, L. 5× more efficient than close-to-close but
  assumes no overnight jumps.
- **Garman-Klass**: Uses O, H, L, C. 8× more efficient. Still assumes continuous prices.
- **Yang-Zhang**: Handles overnight jumps. Best for daily data with gaps.
  **Recommended default for US stocks.**

### 3.3 Volume Features

Volume carries information about conviction, liquidity, and institutional activity.

| Feature | Formula / Description | Lookback Windows | Stationarity |
|---|---|---|---|
| **Relative volume** | `V_t / SMA(V, k)` | 5, 10, 20 | ✅ Stationary |
| **Volume z-score** | `(V_t - mean(V, k)) / std(V, k)` | 20, 63 | ✅ Stationary |
| **OBV (On-Balance Volume)** | Cumulative volume × sign(return) | — | ⚠️ Use rate of change |
| **OBV momentum** | Rate of change of OBV over window | 10, 21 | ✅ Stationary |
| **Volume-price trend** | `Σ(V_i × (C_i - C_{i-1}) / C_{i-1})` | 21, 63 | ⚠️ Normalize |
| **VWAP deviation** | `(C_t - VWAP_t) / VWAP_t` (intraday) | Intraday only | ✅ Stationary |
| **Accumulation/Distribution** | `((C-L) - (H-C)) / (H-L) × V` | 21 (smoothed) | ⚠️ Normalize |
| **Money Flow Index** | Volume-weighted RSI | 14 | ✅ Bounded |
| **Volume breakout** | `V_t > 2 × SMA(V, 20)` (binary) | 20 | ✅ Binary |
| **Up-volume ratio** | `Σ(V on up days) / Σ(V total)` over window | 10, 21 | ✅ Bounded |

#### VWAP Note
True VWAP requires intraday data. For daily-only data, approximate as:
`VWAP ≈ (typical_price × volume).cumsum() / volume.cumsum()` within each session.
This is an approximation; if intraday data becomes available, use exact VWAP.

### 3.4 Cross-Asset Features

These capture macro regime, sector rotation, and inter-market relationships.

| Feature | Formula / Description | Source | Priority |
|---|---|---|---|
| **SPY return** | Market return (1d, 5d, 21d) | SPY OHLCV | High |
| **SPY–stock beta** | Rolling regression beta (63d, 252d) | SPY + stock | High |
| **Sector ETF momentum** | Return of stock's sector ETF vs. SPY | XLK, XLF, XLE, etc. | Medium |
| **VIX level** | Current VIX value (z-scored over 252d) | VIX index | High |
| **VIX term structure** | VIX - VIX3M (contango/backwardation) | VIX, VIX3M | Medium |
| **Yield curve slope** | 10Y - 2Y Treasury yield | FRED or proxy ETF | Medium |
| **Credit spread** | HYG - LQD spread (z-scored) | HYG, LQD ETFs | Low |
| **Dollar index** | UUP return (1d, 5d, 21d) | UUP ETF | Low |
| **Gold momentum** | GLD return (5d, 21d) | GLD ETF | Low |
| **Breadth** | % of S&P500 stocks above 50d SMA | Requires universe | Medium |

#### Data Pipeline Requirements
The data pipeline must fetch OHLCV for reference instruments (SPY, QQQ,
sector ETFs, VIX) alongside the strategy's tradeable universe. These symbols
should be in a `reference_symbols` config list.

### 3.5 Regime Features

These attempt to characterize the current market regime to enable regime-conditional
strategies.

| Feature | Formula / Description | Method | Priority |
|---|---|---|---|
| **Trend strength (ADX)** | Average Directional Index | Wilder's DI+/DI- | High |
| **Trend direction** | Sign of 50d SMA slope | Linear regression slope | High |
| **Hurst exponent** | Rescaled range (R/S) estimate | Rolling 252d window | Medium |
| **Volatility regime** | HMM-based regime classification (2 states) | Fitted on rolling window | Sprint 6+ |
| **Mean reversion indicator** | Half-life of mean reversion (Ornstein-Uhlenbeck) | Rolling regression | Medium |
| **Market regime (bull/bear/sideways)** | Rule-based: price vs. 200d SMA + vol level | Lookback 200d | High |
| **Correlation regime** | Rolling correlation of stock vs. SPY | 63d | Medium |
| **Dispersion** | Cross-sectional std of returns in universe | Daily | Medium |

#### Hurst Exponent
- `H > 0.5` → trending (momentum strategies likely to work)
- `H ≈ 0.5` → random walk (no edge)
- `H < 0.5` → mean-reverting (mean reversion strategies likely to work)

Compute rolling Hurst with a 252-day window. Use this as a meta-feature to
select between momentum and mean-reversion strategies.

---

## 4. Feature Construction Guidelines

### 4.1 Avoid Look-Ahead Bias — Checklist

| Risk | Mitigation |
|---|---|
| Using future-adjusted prices for past features | Use point-in-time adjusted prices only |
| Centering/scaling with full-sample statistics | Use **expanding** or **rolling** window stats only |
| Survivorship bias in universe selection | Define universe at each point in time using historical constituents |
| Label leakage through overlapping windows | Use purged cross-validation (see validation framework) |
| Feature selection using test data | Feature selection ONLY on training folds |

### 4.2 Handling Missing Data

| Situation | Action |
|---|---|
| Stock not yet listed | `NaN` — do not backfill |
| Trading halt (< 5 days) | Forward-fill price, set volume to 0, flag as halted |
| Trading halt (≥ 5 days) | Exclude from universe during halt period |
| Missing reference data (VIX, etc.) | Forward-fill up to 3 days; beyond that, `NaN` |

### 4.3 Feature Storage Format

```
features/
├── price_features/
│   ├── returns_1d.parquet
│   ├── returns_5d.parquet
│   ├── momentum_21d.parquet
│   └── ...
├── volatility_features/
│   ├── realized_vol_21d.parquet
│   ├── atr_14d.parquet
│   └── ...
├── volume_features/
│   ├── relative_volume_20d.parquet
│   └── ...
├── cross_asset_features/
│   ├── spy_beta_63d.parquet
│   └── ...
├── regime_features/
│   ├── adx_14d.parquet
│   └── ...
└── metadata/
    ├── feature_registry.json    # Schema, version, dependencies
    └── computation_log.json     # When each feature was last computed
```

**Format:** Apache Parquet with columns = symbols, index = datetime.
Parquet is chosen for:
- Columnar compression (10× smaller than CSV)
- Fast partial reads (load one symbol without reading all)
- Type safety (datetime, float64 preserved)

### 4.4 Feature Naming Convention

```
{category}_{name}_{window}[_{variant}]

Examples:
  price_return_5d
  price_momentum_63d
  vol_realized_21d
  vol_parkinsons_10d
  volume_relative_20d
  volume_obv_momentum_21d
  cross_spy_beta_63d
  regime_adx_14d
  regime_hurst_252d
```

---

## 5. Feature Importance and Selection Strategy

### 5.1 Pre-Modelling Filters

Before feeding features to any ML model, apply these filters:

1. **Variance filter:** Drop features with near-zero variance (< 1e-8).
2. **Correlation filter:** If two features have |ρ| > 0.95, keep the one with
   lower lookback window (more responsive).
3. **Missing data filter:** Drop features with > 20% missing values.

### 5.2 Importance Estimation Methods

| Method | When to Use | Notes |
|---|---|---|
| **Mean Decrease Impurity (MDI)** | Quick screening with tree models | Biased toward high-cardinality; use with caution |
| **Mean Decrease Accuracy (MDA)** | More reliable than MDI | Permutation-based; computationally expensive |
| **Single Feature Importance (SFI)** | Feature-by-feature assessment | Misses interactions but avoids substitution effects |
| **SHAP values** | Final model interpretation | Gold standard; use TreeSHAP for tree models |

### 5.3 Feature Selection Protocol

1. Start with all features passing pre-modelling filters.
2. Compute MDA importance using purged walk-forward CV.
3. Drop features with negative MDA (hurting OOS performance).
4. Compute clustered feature importance (hierarchical clustering on correlation
   matrix) to identify redundant feature groups.
5. Select one representative feature per cluster.
6. Validate final feature set on a held-out temporal segment.

**Critical rule:** Feature selection is part of the model and MUST be inside
the walk-forward loop. Selecting features on the full dataset and then
backtesting is a form of look-ahead bias.

---

## 6. Label Construction (for Future ML Models)

### 6.1 Label Types

| Label | Definition | Use Case |
|---|---|---|
| **Fixed-horizon return** | `r_{t+h} = (P_{t+h} - P_t) / P_t` | Regression target |
| **Triple-barrier label** | First barrier hit: upper (take-profit), lower (stop-loss), or time limit | Classification (de Prado, Ch. 3) |
| **Side and size** | Direction (long/short/flat) + confidence weight | Meta-labelling |
| **Quantile label** | Cross-sectional return quantile (top/bottom 20%) | Ranking model |

### 6.2 Triple-Barrier Method (Recommended)

The triple-barrier method assigns a label based on which of three barriers is
hit first:

```
         ┌──── Upper barrier: take-profit (e.g., +2 × ATR)
         │
Price ───┤──── Entry price
         │
         └──── Lower barrier: stop-loss (e.g., -2 × ATR)

         ├────────── Time barrier (e.g., 10 trading days) ──────────┤
```

- **Label = +1** if upper barrier is hit first
- **Label = -1** if lower barrier is hit first
- **Label = 0** if time barrier is hit first (no clear signal)

Advantages over fixed-horizon:
- Path-dependent: captures realistic trade dynamics
- Variable horizon: aligns with how stops/targets actually work
- Natural class balance control via barrier width

### 6.3 Meta-Labelling

Meta-labelling (de Prado, 2018, Ch. 3) is a two-stage approach:

1. **Primary model** predicts direction (e.g., classical MA crossover signal).
2. **Secondary (meta) model** predicts whether the primary signal will be
   profitable (binary classification: take the trade or skip it).

This is particularly relevant for Sprint 5+, where ML can be used to filter
classical strategy signals without replacing them entirely.

---

## 7. Implementation Roadmap

| Sprint | Deliverable | Dependencies |
|---|---|---|
| 1 | This planning document | None |
| 2 | Data pipeline stores OHLCV + reference symbols | Data Engineer |
| 3 | Classical strategy baselines (MA, RSI, Bollinger) | Strategy Developer |
| 4 | Validation framework fully implemented | ML Engineer |
| 5 | Price + Volatility features (Tier 1) | Data pipeline complete |
| 5 | Triple-barrier labelling module | Feature pipeline |
| 6 | Volume + Cross-asset features (Tier 2) | Reference data available |
| 6 | First ML model (gradient boosting baseline) | Features + labels + validation |
| 7 | Regime features (Tier 3) | Sufficient history |
| 7 | Meta-labelling on classical strategies | Classical strategies + ML baseline |
| 8+ | Feature selection, ensembles, online learning | Iterative refinement |

---

## 8. Data Pipeline Requirements Summary

For the Data Engineer — the following must be available to support feature
engineering:

| Requirement | Details | Priority |
|---|---|---|
| Daily OHLCV for tradeable universe | Split/dividend adjusted + unadjusted | P0 (Sprint 2) |
| Daily OHLCV for reference symbols | SPY, QQQ, sector ETFs, VIX, GLD, TLT | P0 (Sprint 2) |
| At least 7 years of history | 2018–2025 minimum | P0 (Sprint 2) |
| Timezone-aware timestamps | US/Eastern, market hours only | P0 (Sprint 2) |
| Corporate action data | Splits, dividends, delistings | P1 (Sprint 3) |
| Historical index constituents | S&P 500 membership over time | P2 (Sprint 4) |
| Intraday data (1-min bars) | For VWAP, microstructure features | P3 (Sprint 6+) |

---

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Look-ahead bias in features | Medium | Critical | Automated bias checks in feature pipeline |
| Overfitting to in-sample | High | Critical | Validation framework (see companion doc) |
| Survivorship bias | Medium | High | Use point-in-time universe membership |
| Feature multicollinearity | High | Medium | Correlation filter + clustered importance |
| Regime change invalidating features | Medium | High | Regime-conditional models; walk-forward retraining |
| Insufficient data for rare events | High | Medium | Stress-test with synthetic tail events |
| Computational cost of feature generation | Low | Medium | Parquet caching; incremental computation |

---

## 10. References

1. López de Prado, M. (2018). *Advances in Financial Machine Learning.* Wiley.
   - Ch. 3: Triple-barrier labelling, meta-labelling
   - Ch. 5: Fractional differentiation
   - Ch. 7-8: Feature importance (MDI, MDA, SFI)
2. Garman, M. B., & Klass, M. J. (1980). "On the Estimation of Security Price
   Volatilities from Historical Data." *Journal of Business*, 53(1), 67–78.
3. Yang, D., & Zhang, Q. (2000). "Drift-Independent Volatility Estimation."
   *Journal of Business*, 73(3), 477–491.
4. Parkinson, M. (1980). "The Extreme Value Method for Estimating the Variance
   of the Rate of Return." *Journal of Business*, 53(1), 61–65.
5. Granville, J. (1963). *Granville's New Key to Stock Market Profits.* — OBV.
