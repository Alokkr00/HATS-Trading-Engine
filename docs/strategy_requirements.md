# Strategy Requirements — Sprint 3 Preparation

> **Author:** Lead Quant Researcher
> **Created:** 2026-07-02
> **Status:** Draft — awaiting team review
> **Sprint:** 1 (Data & Infrastructure)

---

## 1. Executive Summary

We plan to evaluate three systematic strategies for US equities and ETFs traded via
Alpaca. **None of these strategies are novel.** MA crossovers, RSI mean-reversion, and
Bollinger Band strategies are among the most widely studied retail setups. The academic
literature is mixed-to-negative on their profitability after costs in modern markets
(see Bajgrowicz & Scaillet 2012, Sullivan, Timmermann & White 1999, etc.).

Our job is not to *assume* they work but to **test whether any residual edge exists**
after realistic costs and proper statistical controls. If the answer is "no," that is a
valid and valuable result — and we move on to better ideas in Sprint 4.

### Benchmark

All strategies are compared against **buy-and-hold SPY** over the same period. A
strategy that cannot beat passive exposure on a risk-adjusted basis has no reason to
exist.

---

## 2. Universe & Data Requirements

### 2.1 Symbol Universe

| Tier | Symbols | Purpose |
|------|---------|---------|
| **Core ETFs** | SPY, QQQ, IWM, DIA | High-liquidity baselines, tight spreads |
| **Large-Cap Stocks** | AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, JPM | Liquid single names |
| **Mid-Cap Stocks** | 10-15 names from S&P 400 (selected by avg daily $ volume > $50M) | Test spread sensitivity |
| **Sector ETFs** | XLF, XLE, XLK, XLV, XLI | Regime diversity |

**Total: ~30-35 instruments.** This is deliberately small. We need enough breadth to
test cross-sectional robustness but not so many that we invite data-mining bias.

### 2.2 Timeframes

| Timeframe | Bar Size | Primary Use |
|-----------|----------|-------------|
| **Daily** | 1D | All three strategies (primary) |
| **Hourly** | 1H | Sensitivity analysis for MA Crossover, Bollinger |
| **15-minute** | 15m | Intraday signal resolution (optional Sprint 4) |

**Primary timeframe is daily bars.** Intraday data increases overfitting surface area
and is harder to execute reliably. We start daily and only move to intraday if daily
shows promise.

### 2.3 Minimum Lookback Period

| Requirement | Duration | Rationale |
|-------------|----------|-----------|
| **Indicator warm-up** | 200 trading days (~10 months) | Longest MA window is 200-day |
| **In-sample training** | 3 years (≈756 trading days) | Need multiple market regimes |
| **Out-of-sample test** | 2 years (≈504 trading days) | Statistically meaningful OOS |
| **Full dataset needed** | **≥ 5 years + 200-day warm-up** | 2020-01 to 2025-12 recommended |
| **Ideal dataset** | 8-10 years | Captures 2015-2025 including COVID, rate hikes, etc. |

**Recommended data range: 2015-01-01 to 2025-12-31 (11 years).**

This captures:
- Bull market (2016-2019)
- COVID crash & recovery (2020)
- Post-COVID inflation / meme-stock era (2021)
- Rate-hike bear market (2022)
- AI-driven rally (2023-2024)
- Current regime (2025)

### 2.4 Required Data Fields

Per bar:
- `open`, `high`, `low`, `close`, `volume`
- `adjusted_close` (split/dividend adjusted) — **critical** for daily bars
- Timestamp (UTC or exchange-local with TZ awareness)

We also need:
- **SPY daily returns** (benchmark)
- **VIX daily close** (regime filter — see §7)
- **Fed Funds rate** (optional, for regime context)
- **Earnings dates** per symbol (to flag event-driven noise)

### 2.5 Data Quality Requirements

- [ ] No gaps > 2 consecutive trading days (unless market closure)
- [ ] Adjusted closes must account for splits and dividends
- [ ] Volume data must be exchange-reported (not dark pool estimated)
- [ ] Verify: no look-ahead bias in adjusted prices (point-in-time adjustment)
- [ ] Cross-validate prices against a second source for at least 5 symbols

---

## 3. Strategy Specifications

---

### 3.1 Strategy A — Moving Average Crossover (Trend Following)

#### Hypothesis

> Equity prices exhibit **serial correlation at medium-term horizons** (momentum
> effect). When a short-term moving average crosses above a long-term moving average,
> it signals that recent momentum is positive and likely to persist for days-to-weeks.

**Theoretical backing: MODERATE.**
The momentum anomaly is one of the most documented in academic finance (Jegadeesh &
Titman 1993, Asness et al. 2013). However, simple MA crossovers are a crude proxy for
momentum, and much of the edge has decayed in liquid US equities as the strategy has
become crowded. Transaction costs from whipsaws (false crosses) are the primary
performance killer.

#### Indicators

| Indicator | Parameters | Range to Test | Justification |
|-----------|-----------|---------------|---------------|
| **SMA (fast)** | Period | [10, 20, 30, 50] | Short-term trend proxy |
| **SMA (slow)** | Period | [50, 100, 150, 200] | Long-term trend proxy |
| **ATR** | Period = 14 | Fixed | Volatility for position sizing & stop |

**Constraint:** fast_period < slow_period (obviously). This gives us 4 × 4 = 16
parameter combos minus invalid pairs = **10 valid combos** to test.

We deliberately use SMA over EMA. EMA is slightly more responsive but the difference
is negligible for daily bars, and SMA is simpler (less room for implementation error).
If SMA shows promise, we can test EMA as a robustness check.

#### Entry Rules

**Long Entry:**
1. `SMA(fast)` crosses above `SMA(slow)` (golden cross)
2. Current price is above `SMA(slow)` (confirmation — no buying into a downtrend)
3. Signal confirmed on **daily close** (no intrabar signals)
4. Execute at **next day's open** (no look-ahead bias)

**Short Entry:** NONE. We are long-only for Sprint 3.
- Shorting introduces borrow costs, short squeeze risk, and margin complexity
- Alpaca's short availability is inconsistent
- Long-only is the conservative starting point

#### Exit Rules

| Exit Type | Rule | Rationale |
|-----------|------|-----------|
| **Trend reversal** | `SMA(fast)` crosses below `SMA(slow)` (death cross) | Core signal negated |
| **Trailing stop** | Close below `entry_price - 2 × ATR(14)` at entry | Limit drawdown on whipsaws |
| **Time stop** | Position open > 60 trading days with < 2% gain | Avoid dead-money positions |
| **Max loss stop** | Unrealized loss > 5% from entry | Hard risk limit |

Exit on **next day's open** after signal triggers on close.

#### Expected Characteristics

| Metric | Expected Range | Notes |
|--------|---------------|-------|
| **Win rate** | 35-45% | Trend following wins rarely but big |
| **Avg Win / Avg Loss** | 1.8 - 3.0 | Must be >1.5 to compensate low win rate |
| **Trade frequency** | 2-5 trades/symbol/year | ~60-150 total trades/year for 30 symbols |
| **Avg holding period** | 15-40 trading days | |
| **Max drawdown** | 15-25% | During choppy/range-bound markets |

#### Key Risks & Failure Modes

1. **Whipsaw losses in range-bound markets.** This is the #1 killer. When price
   oscillates around the MAs, the strategy generates many small losses.
   *Mitigation: ATR-based trailing stop, time stop.*

2. **Lag.** MAs are lagging indicators by construction. Entry is late (after the
   move starts) and exit is late (gives back profit).
   *Mitigation: Use faster MA pairs, but beware more whipsaws.*

3. **Regime dependence.** Works in trending markets, hemorrhages in choppy ones.
   *Mitigation: VIX-based regime filter (see §7).*

4. **Parameter sensitivity.** If performance varies wildly across nearby parameter
   values (e.g., SMA(48) works but SMA(52) doesn't), the result is likely overfit.
   *Mitigation: Require performance stability across parameter neighborhood.*

#### Validation Approach

See §6 for general framework. Strategy-specific checks:
- Compare against **random entry + same exit rules** to test if entry timing adds value
- Test on **non-US markets** (e.g., EFA, EEM ETFs) for out-of-domain validation
- Verify that **profitable parameter regions are contiguous** in parameter space (not isolated points)

---

### 3.2 Strategy B — RSI Mean Reversion

#### Hypothesis

> Short-term price movements in liquid equities exhibit **mean-reverting behavior**:
> extreme readings on the RSI (Relative Strength Index) indicate temporary overbought
> or oversold conditions that tend to reverse over the subsequent 2-10 days.

**Theoretical backing: WEAK-TO-MODERATE.**
Mean reversion at very short horizons (1-5 days) has some academic support
(Lehmann 1990, Jegadeesh 1990), but RSI is a specific implementation that has been
extensively data-mined. The concern is that whatever edge existed has been arbitraged
away, especially in large-cap US equities. RSI may still have edge in mid-caps or
during periods of elevated volatility, but this needs rigorous testing.

#### Indicators

| Indicator | Parameters | Range to Test | Justification |
|-----------|-----------|---------------|---------------|
| **RSI** | Period | [7, 10, 14, 21] | Standard lookback windows |
| **RSI oversold threshold** | Level | [20, 25, 30] | Lower = more extreme = fewer trades |
| **RSI overbought threshold** | Level | [70, 75, 80] | Symmetric to oversold |
| **ATR** | Period = 14 | Fixed | Position sizing |
| **SMA(200)** | Period = 200 | Fixed | Trend filter |

**Total parameter combos:** 4 (RSI period) × 3 (oversold) × 3 (overbought) = **36 combos.**
This is getting large — we must apply multiple comparison correction (see §6.3).

#### Entry Rules

**Long Entry (buy the dip):**
1. RSI(period) crosses below oversold threshold (e.g., RSI < 30)
2. Price is **above SMA(200)** — we only buy dips in uptrends
   (buying dips in downtrends is catching falling knives)
3. Signal confirmed on **daily close**
4. Execute at **next day's open**

**Short Entry:** NONE (long-only, same rationale as Strategy A).

The SMA(200) filter is critical. Without it, this strategy would buy into multi-month
downtrends (e.g., buying the 2022 rate-hike decline repeatedly). The filter ensures
we're buying *pullbacks in uptrends*, not *breakdowns in downtrends.*

#### Exit Rules

| Exit Type | Rule | Rationale |
|-----------|------|-----------|
| **RSI recovery** | RSI crosses above `50` (neutral) | Mean reversion target reached |
| **RSI overbought** | RSI crosses above `overbought_threshold` | Full reversion — take profit |
| **Time stop** | Position open > 10 trading days | Mean reversion should be fast |
| **Stop loss** | Unrealized loss > 3% from entry | Tight stop — if it's still falling, thesis is wrong |

The **time stop** is essential. Mean reversion strategies have a specific time horizon.
If the reversion hasn't happened in 10 days, our hypothesis for this trade is wrong.

#### Expected Characteristics

| Metric | Expected Range | Notes |
|--------|---------------|-------|
| **Win rate** | 55-65% | Mean reversion wins often but small |
| **Avg Win / Avg Loss** | 0.8 - 1.3 | Wins are small, stops hit occasionally |
| **Trade frequency** | 1-4 trades/symbol/year | RSI extremes are infrequent in uptrends |
| **Avg holding period** | 3-8 trading days | Short duration |
| **Max drawdown** | 10-18% | If trend filter fails during regime change |

#### Key Risks & Failure Modes

1. **"Oversold can get more oversold."** In a genuine crash (COVID, Lehman), RSI
   hits 20 and then goes to 10. The stop loss is critical.
   *Mitigation: 3% hard stop, SMA(200) trend filter.*

2. **Low trade frequency.** With strict filters, we may get <30 trades/year across
   the full universe. This makes statistical validation very difficult.
   *Mitigation: May need to relax thresholds — but track the multiple testing cost.*

3. **Spread costs eat small wins.** Mean reversion targets are small (1-3%). If
   round-trip costs are 0.10-0.20%, that's 5-15% of gross profit consumed by costs.
   *Mitigation: Only trade liquid names. See cost model (§ companion doc).*

4. **Trend filter lag.** SMA(200) is very slow. During a regime change (bull → bear),
   the filter stays "bullish" for months while price drops.
   *Mitigation: Could add a faster filter (SMA(50) below SMA(200) = no trades).*

#### Validation Approach

- Test significance with **bootstrap hypothesis test**: is the mean trade return
  statistically different from zero after costs?
- Compare win rate against **coin-flip baseline** (random entries with same holding period)
- Given low trade frequency, we need **≥ 100 trades** for meaningful statistics.
  With 30 symbols over 5 years, that's ~3 trades/symbol/year minimum.

---

### 3.3 Strategy C — Bollinger Band Squeeze & Breakout

#### Hypothesis

> Periods of unusually low volatility (Bollinger Band squeeze) are followed by
> **volatility expansion**. When price breaks out of a compressed Bollinger Band, it
> signals the start of a directional move. By entering at the breakout, we capture the
> subsequent expansion.

**Theoretical backing: MODERATE.**
Volatility clustering is well-documented (Mandelbrot 1963, GARCH literature). Low
volatility periods DO tend to precede high volatility periods. However, the
**direction** of the breakout is the hard part — volatility expansion is symmetric.
The strategy needs a directional filter, or it must quickly cut losses on false
breakouts.

This is fundamentally a **volatility-regime strategy**, which is more theoretically
grounded than pure price-pattern strategies.

#### Indicators

| Indicator | Parameters | Range to Test | Justification |
|-----------|-----------|---------------|---------------|
| **Bollinger Band** | Period | [15, 20, 25] | Standard lookback |
| **Bollinger Band** | Std Dev multiplier | [1.5, 2.0, 2.5] | Band width |
| **BandWidth** | (same as BB) | — | BB Width = (Upper - Lower) / Middle |
| **BandWidth percentile** | Lookback for percentile | [100, 126, 252] days | How "squeezed" is squeezed? |
| **Squeeze threshold** | Percentile | [10, 20, 30] | BW below this % = squeeze |
| **ATR** | Period = 14 | Fixed | Stop loss calculation |

**Total parameter combos:** 3 × 3 × 3 × 3 = **81 combos.** This is too many.

**Parameter reduction plan:**
- Fix BB period = 20, std_dev = 2.0 (Bollinger's original defaults, widely used)
- Test squeeze lookback: [126, 252]
- Test squeeze threshold: [10, 20]
- **Reduced to 4 combos** — much more manageable.

If the strategy shows no promise at default BB parameters, varying them is unlikely to
help (and if it does, it's probably overfit).

#### Entry Rules

**Long Entry:**
1. Bollinger BandWidth is below its `squeeze_threshold` percentile over `lookback` days
   (a "squeeze" is detected)
2. Daily close breaks **above** the upper Bollinger Band
3. Volume on breakout day is ≥ 1.5× the 20-day average volume (volume confirmation)
4. Signal confirmed on **daily close**
5. Execute at **next day's open**

**Short Entry:** NONE (long-only).

The **volume filter** is important. Without it, low-volatility drift through the band
generates false signals. A genuine squeeze breakout should come with volume expansion.

#### Exit Rules

| Exit Type | Rule | Rationale |
|-----------|------|-----------|
| **Band reversal** | Close below middle Bollinger Band (SMA(20)) | Breakout lost momentum |
| **Trailing stop** | Close below `entry_price - 1.5 × ATR(14)` at entry | Protect against false breakout |
| **Profit target** | Gain ≥ 2 × ATR(14) at entry | Take profit on successful breakout |
| **Time stop** | Position open > 20 trading days | Breakout moves should be swift |
| **Stop loss** | Unrealized loss > 4% from entry | Hard cap |

#### Expected Characteristics

| Metric | Expected Range | Notes |
|--------|---------------|-------|
| **Win rate** | 40-50% | Many false breakouts |
| **Avg Win / Avg Loss** | 1.5 - 2.5 | Genuine breakouts should run |
| **Trade frequency** | 1-3 trades/symbol/year | Squeezes are infrequent |
| **Avg holding period** | 5-15 trading days | |
| **Max drawdown** | 12-20% | False breakouts cause clusters of small losses |

#### Key Risks & Failure Modes

1. **False breakouts.** Price pokes above the band, triggers entry, then immediately
   reverses. This is extremely common.
   *Mitigation: Volume filter, tight stop loss.*

2. **Direction ambiguity.** The squeeze tells us volatility will expand, not
   *which way.* We're biased long-only, so we miss downside breakouts and get
   caught by them.
   *Mitigation: Could add trend filter (SMA(50) direction). Consider for Sprint 4.*

3. **Very low trade frequency.** With strict squeeze + volume filters on 30 symbols,
   we may get only 20-40 trades/year. This is statistically thin.
   *Mitigation: May need wider universe or longer test period.*

4. **Bollinger Band parameters are arbitrary.** John Bollinger chose 20-period, 2 std
   dev as defaults. There's no deep statistical reason for these specific values.
   *Mitigation: We use defaults deliberately and test sensitivity modestly.*

#### Validation Approach

- Test whether **post-squeeze volatility expansion is real** before testing direction
  (this validates the underlying mechanism regardless of our entry/exit rules)
- Compare breakout returns against **non-squeeze breakouts** to isolate squeeze effect
- Given very low trade frequency, this strategy may not reach statistical significance
  in our sample — we should be honest about this limitation

---

## 4. Position Sizing

All strategies use the same position sizing framework:

```
risk_per_trade = account_equity × 0.01          # Risk 1% per trade
position_size  = risk_per_trade / (entry_price - stop_price)
max_position   = account_equity × 0.10          # Never > 10% in one name
position_size  = min(position_size, max_position / entry_price)
```

**Constraints:**
- Maximum **6 concurrent positions** (limits correlation risk)
- Maximum **25% of account in a single sector**
- Minimum position: 1 share (no fractional for simplicity)
- If position_size < 1 share, skip the trade

For backtesting, assume a **$100,000 starting account** (realistic for Alpaca active
trader).

---

## 5. Transaction Cost Model

Detailed in companion document `docs/cost_model.md`. Summary:

| Component | Assumption |
|-----------|-----------|
| Commission | $0 (Alpaca) |
| Bid-ask spread (large cap) | 1 bps round-trip |
| Bid-ask spread (mid cap) | 3-5 bps round-trip |
| Slippage | 3-5 bps per trade |
| SEC fee | ~$0.02 per $1,000 on sells |
| **Total round-trip cost (large cap)** | **~5-8 bps** |
| **Total round-trip cost (mid cap)** | **~8-15 bps** |

**All backtest results must be reported AFTER costs.** Gross returns are meaningless.

---

## 6. Statistical Validation Framework

### 6.1 Walk-Forward Optimization

We use **anchored walk-forward** with expanding in-sample window:

```
Full period: 2015-01 to 2025-12 (~11 years)

Step 1: Train on 2015-01 to 2018-12, Test on 2019-01 to 2019-12
Step 2: Train on 2015-01 to 2019-12, Test on 2020-01 to 2020-12
Step 3: Train on 2015-01 to 2020-12, Test on 2021-01 to 2021-12
Step 4: Train on 2015-01 to 2021-12, Test on 2022-01 to 2022-12
Step 5: Train on 2015-01 to 2022-12, Test on 2023-01 to 2023-12
Step 6: Train on 2015-01 to 2023-12, Test on 2024-01 to 2024-12
Step 7: Train on 2015-01 to 2024-12, Test on 2025-01 to 2025-12
```

**7 walk-forward folds.** The strategy must show positive risk-adjusted returns in
**at least 5 of 7 OOS folds** (71%) to be considered. One bad year is acceptable;
three is a pattern.

Why anchored (expanding) instead of rolling? Because we want to use all available
history for training. Rolling windows discard old data, which is wasteful when our
dataset is already limited.

### 6.2 Performance Metrics

For each walk-forward fold and overall, compute:

| Metric | Minimum Threshold | Notes |
|--------|------------------|-------|
| **Sharpe Ratio (annualized, after costs)** | ≥ 0.5 (OOS) | See §6.4 for deflated Sharpe |
| **Sortino Ratio** | ≥ 0.7 | Penalizes downside vol only |
| **Max Drawdown** | ≤ 25% | Capital preservation |
| **Calmar Ratio** (ann return / max DD) | ≥ 0.5 | Return per unit drawdown |
| **Win Rate** | Strategy-dependent | See individual specs above |
| **Profit Factor** | ≥ 1.2 (after costs) | Gross profit / Gross loss |
| **Expectancy per trade** | > 0 (after costs) | Avg $ profit per trade |
| **Ulcer Index** | Report (no threshold) | Duration-weighted drawdown |
| **Beta to SPY** | Report (no threshold) | Market exposure |
| **Alpha (Jensen's)** | > 0, p-value < 0.05 | Excess return over market |

### 6.3 Multiple Hypothesis Testing Correction

We are testing **3 strategies** with a total of ~50 parameter combinations
(10 + 36 + 4). This inflates the probability of finding a "significant" result by
chance.

**Corrections applied:**

1. **Bonferroni correction (conservative):**
   Adjusted significance level = 0.05 / 50 = 0.001. A result is "significant" only
   if p < 0.001.

2. **Benjamini-Hochberg (FDR control, less conservative):**
   Control false discovery rate at 5%. Rank p-values and compare against adjusted
   thresholds. This is our primary correction method.

3. **White's Reality Check / Hansen's SPA test:**
   Test whether the best strategy's performance is significantly better than the best
   performance achievable by random chance across all tested configurations.

4. **Deflated Sharpe Ratio (Bailey & López de Prado 2014):**
   Adjusts the Sharpe ratio for the number of trials, skewness, and kurtosis of
   returns. Accounts for the fact that testing many strategies inflates the expected
   maximum Sharpe ratio.

   ```
   DSR = Prob[ SR* > 0 | trials, skew, kurtosis, var(SR) ]
   ```

   We require **DSR > 0.95** (95% probability the Sharpe is genuinely positive).

### 6.4 Minimum Sharpe Ratio Threshold

The **minimum annualized Sharpe ratio** to consider a strategy viable is **0.5
(out-of-sample, after costs)**.

Rationale:
- A Sharpe of 0.5 means ~50% excess return per unit of volatility
- For typical equity-like vol (~15-20%), this implies ~7.5-10% annual return
- This is competitive with buy-and-hold SPY (~10% long-run nominal return) but
  with the potential for lower drawdowns
- Below 0.5, the strategy doesn't compensate for model risk, execution risk, and
  the effort of running it
- Note: in-sample Sharpe will be higher; we only care about OOS Sharpe

**After deflated Sharpe correction, the effective threshold is higher.** If we test
50 parameter combos, a nominal OOS Sharpe of 0.5 may correspond to a DSR well below
0.95, meaning it's not statistically distinguishable from luck.

### 6.5 Sample Size Requirements

Minimum number of trades for statistical significance:

```
# For a two-sided t-test at alpha=0.05, power=0.80:
# To detect a mean trade return of 0.5% with std dev of 2%:
n = (z_alpha/2 + z_beta)^2 * sigma^2 / delta^2
n = (1.96 + 0.84)^2 * (0.02)^2 / (0.005)^2
n ≈ 100 trades

# With Bonferroni correction (alpha = 0.001):
n = (3.29 + 0.84)^2 * (0.02)^2 / (0.005)^2
n ≈ 109 trades
```

**Minimum: 100 trades per strategy.** Below this, we cannot reliably distinguish
signal from noise.

For strategies with low trade frequency:
- MA Crossover: ~60-150 trades/year → 2-3 years sufficient
- RSI Mean Reversion: ~30-120 trades/year → 3-4 years needed
- Bollinger Squeeze: ~20-40 trades/year → **3-5 years needed, may be insufficient**

**Bollinger Squeeze is at risk of not reaching statistical significance.** We should
acknowledge this upfront and plan accordingly (widen universe or extend backtest
period if needed).

### 6.6 Overfitting Prevention

Beyond multiple testing correction:

1. **Parameter stability test:** Optimal parameters must be robust to ±20% perturbation.
   If SMA(20,100) works but SMA(24,120) doesn't, it's overfit.

2. **Cross-sectional robustness:** The strategy must work on ≥60% of symbols in the
   universe, not just cherry-picked names.

3. **Regime robustness:** Must be tested across bull (2016-2019), crash (2020),
   recovery (2020-2021), bear (2022), and rally (2023-2024) regimes.

4. **Combinatorial Purged Cross-Validation (CPCV):** For any ML-based signal
   enhancement (Sprint 4+), use CPCV instead of standard k-fold to prevent leakage
   from overlapping holding periods.

5. **No peeking:** All parameter selection happens in-sample. OOS data is touched
   ONCE for final evaluation. If we iterate on OOS, we contaminate it.

6. **Implementation decay tracking:** If we deploy, track live vs backtest
   performance divergence. >30% decay in Sharpe = pull the strategy.

---

## 7. Regime Filter (Optional Enhancement)

All three strategies may benefit from a **volatility regime filter** using VIX:

| VIX Level | Regime | Action |
|-----------|--------|--------|
| VIX < 15 | Low vol / complacent | Normal trading |
| 15 ≤ VIX < 25 | Normal | Normal trading |
| 25 ≤ VIX < 35 | Elevated | Reduce position sizes by 50% |
| VIX ≥ 35 | Crisis | No new entries; tighten stops on existing |

This is a **secondary filter**, not part of the core strategy logic. We test each
strategy with and without the VIX filter and report both results.

---

## 8. Backtest Engine Requirements

The backtest engine (built by Infra team) must support:

- [ ] Event-driven architecture (not vectorized — avoids look-ahead)
- [ ] Next-day-open execution (signal on close → execute next open)
- [ ] Configurable transaction cost model (see cost_model.md)
- [ ] Position sizing with portfolio-level constraints
- [ ] Multiple concurrent positions (portfolio mode)
- [ ] Walk-forward mode (train/test split automation)
- [ ] Trade log with entry/exit timestamps, prices, and P&L per trade
- [ ] Drawdown tracking (peak-to-trough, duration)
- [ ] Benchmark comparison (SPY buy-and-hold)
- [ ] No look-ahead bias verification (order fills use next bar's open, not current bar)

---

## 9. Deliverables (Sprint 3)

| Deliverable | Owner |
|-------------|-------|
| Backtest results for all 3 strategies (walk-forward) | Quant Researcher |
| Statistical significance tests (p-values, DSR) | Quant Researcher |
| Parameter sensitivity analysis | Quant Researcher |
| Strategy selection recommendation (go/no-go for each) | Quant Researcher |
| Risk analysis per strategy | Quant Researcher |
| Implementation spec for selected strategies | Quant Researcher + Infra |

---

## 10. Honest Assessment — Probability of Success

| Strategy | Prob. of Real Edge | Confidence | Notes |
|----------|-------------------|------------|-------|
| MA Crossover | **20-30%** | Moderate | Well-studied, likely crowded. May work as regime filter but unlikely as standalone alpha source |
| RSI Mean Reversion | **15-25%** | Low | Thin theoretical backing for RSI specifically. May work in mid-caps or high-vol regimes |
| Bollinger Squeeze | **25-35%** | Moderate | Best theoretical grounding (vol clustering). But directional prediction is hard and trade count will be low |

**Overall probability that at least 1 of 3 strategies shows genuine, cost-effective
edge:** ~40-50%.

If none pass validation, that is a valuable result. We move to:
- Multi-factor models (Sprint 4)
- ML-enhanced signals (Sprint 4)
- Alternative data sources (Sprint 5)
- Cross-sectional momentum / statistical arbitrage (Sprint 5)

---

## Appendix A: References

- Jegadeesh, N. & Titman, S. (1993). *Returns to Buying Winners and Selling Losers.*
- Asness, C., Moskowitz, T., & Pedersen, L. (2013). *Value and Momentum Everywhere.*
- Bailey, D. & López de Prado, M. (2014). *The Deflated Sharpe Ratio.*
- Sullivan, R., Timmermann, A. & White, H. (1999). *Data-Snooping, Technical Trading Rule Performance, and the Bootstrap.*
- Bajgrowicz, P. & Scaillet, O. (2012). *Technical Trading Revisited.*
- Mandelbrot, B. (1963). *The Variation of Certain Speculative Prices.*
- Lehmann, B. (1990). *Fads, Martingales, and Market Efficiency.*

## Appendix B: Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-07-02 | Lead Quant Researcher | Initial draft |
