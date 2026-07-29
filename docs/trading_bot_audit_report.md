# Systematic Trading Bot Audit & Evaluation Report

This audit report provides a professional, trading-focused evaluation of the indicators, systematic strategies, and dashboard state controls implemented in the `stocks` repository. It identifies architectural strengths, details a critical runtime bug that has been successfully fixed, exposes gaps in the testing framework, and outlines the roadmap to elevate this system to institutional-grade.

---

## 1. Executive Summary

- **Indicators Wrapper (`src/indicators/ta_wrapper.py`)**: Solid, clean integration of standard indicators (SMA, EMA, RSI, MACD, Bollinger Bands, ATR) via `pandas_ta`. The wrapper enforces lowercase naming conventions, handles column collisions, and is timezone-preserving.
- **Strategies & Signals Engine (`src/strategy/`)**: The `SignalGenerator` class implements a composable rules engine that includes **strict look-ahead bias validation** (evaluating on truncated data to ensure outputs do not change with future data). This is a highly robust, institutional-grade pattern. Timezone checks are correctly enforced at the `BaseStrategy` level.
- **Dashboard Controls (`src/dashboard/app.py`)**: The FastAPI server provides crucial monitoring endpoints and execution controls (bot toggling, emergency liquidation).
- **Critical Bug Fixed**: A `TypeError` in `app.py` was discovered where `store.load(symbol, limit=1)` was invoked. Because the `DataStore.load` signature does not accept a `limit` parameter, this error caused position PnL calculations to fail and the **emergency liquidation action to crash with an HTTP 500 error** when open positions were present. This has been patched and resolved.
- **Testing Gaps**: Unit tests were bypassing these critical code paths due to over-mocking (e.g., testing state with empty positions and mocking out the strategy signal generation entirely), which allowed these runtime errors to go undetected.

---

## 2. Technical Indicators Review (`ta_wrapper.py`)

The wrapper uses `pandas_ta` to enrich historical OHLCV data with technical indicators:
- **SMA/EMA**: Standard lookback-based moving averages.
- **RSI/MACD**: Standard momentum indicators.
- **Bollinger Bands & ATR**: Standard volatility metrics.

### Quantitative Evaluation
While the technical implementation is clean, the indicator library is **insufficient** for a robust, institutional-grade trading bot due to the following structural limitations:
1. **Lack of Market Regime Filters**: Trend-following indicators (SMA/EMA crossover, BB breakout) suffer severe drawdowns (whipsaws) in low-volatility, mean-reverting markets. Conversely, mean-reversion indicators (RSI) fail in strong, persistent trends. The bot requires a regime classifier (e.g., ADX for trend strength, or rolling standard deviation of returns for volatility regimes) to adjust parameters dynamically.
2. **Single-Timeframe Limitation**: The indicators are computed solely on the execution timeframe. Institutional systems use multi-timeframe analysis (e.g., requiring the weekly trend to be positive before executing a daily mean-reversion buy).
3. **Volume Volatility Ignored**: In the Bollinger Squeeze strategy, volume breakout is hardcoded to `volume >= 1.5 * volume_sma_20`. This does not account for the standard deviation of volume. Using a Volume Z-score would be statistically superior.

---

## 3. Systematic Strategies & Signals Review

Three core strategies are implemented:
1. **MACrossoverStrategy**: Classic golden/death cross with trailing and time-based stops.
2. **RSIMeanReversionStrategy**: Pullback trading in an uptrend (filtered by SMA 200) with a 10-day time stop.
3. **BollingerSqueezeStrategy**: Volatility breakout with ATR-based profit targets and trailing stops.

### Strengths
- **Timezone Enforcement**: `BaseStrategy.generate_signals()` enforces that the input DataFrame has a timezone-aware `DatetimeIndex`. This is critical to prevent misalignment of market hours and look-ahead bias when merging daily/intraday bars.
- **Look-Ahead Bias Validation**: The `SignalGenerator._check_look_ahead_bias()` truncates the input DataFrame by `k` bars (for $k \in \{1, 2, 3, 5\}$) and compares the historical signals. If a signal at index $t$ changes after removing trailing data, it raises a `ValueError`. This is a best-in-class defense against look-ahead bias in indicators and aggregations.

### Weaknesses & Operational Risks
- **Stateful Exit Logic in Signal Rules**: The strategies execute stateful loops inside the rule callables (tracking `in_position`, `entry_price`, `max_price_since_entry` bar-by-bar). This makes the rule functions highly sensitive to index ordering and starting bars. If historical data is truncated too much, the simulated portfolio state inside the signal rules shifts, which can lead to false look-ahead bias detections or incorrect signals.
- **ATR NaNs at Warm-up**: In `MACrossoverStrategy`, if a golden cross occurs during the ATR warm-up period, `entry_atr` is set to `0.0`. This causes the trailing stop condition `current_close < max_price_since_entry - 2.0 * entry_atr` to immediately evaluate to `current_close < max_price_since_entry`, causing an instant trailing stop trigger on the very next bar.

---

## 4. Dashboard State Controls & Critical Bug Fix

The dashboard FastAPI app (`src/dashboard/app.py`) provides the interface to track the bot's state, view signals, and perform control actions.

### The DataStore.load `limit` TypeError Bug (Fixed)
During the audit, a major API mismatch was identified in `src/dashboard/app.py`:
- **API Call**: `df = store.load(symbol, limit=1)` was used in the `/api/state` position PnL enrichment (lines 119) and the `/api/action/liquidate` emergency endpoint (line 335).
- **Underlying Method**: `DataStore.load` in `src/data/store.py` takes parameters `(self, symbol, start, end, tz)`. It does **not** accept a `limit` argument.
- **Impact**:
  1. **Position PnL**: When the bot had active positions, fetching the state would log a warning and fail to update the current price and unrealized PnL (falling back to cost basis).
  2. **Emergency Liquidation**: Triggering the "Emergency Flat" button on the UI with open positions would crash the endpoint with an HTTP 500 error, **preventing emergency position closure**.

#### Code Patch Applied
The `limit=1` parameter was removed from `app.py`. The updated blocks now load the full history and safely slice the last row:

```python
# In app.get("/api/state")
df = store.load(symbol)
if df is not None and not df.empty:
    current_price = float(df["close"].iloc[-1])
    # ... calculates PnL correctly

# In app.post("/api/action/liquidate")
df = store.load(symbol)
close_price = float(df["close"].iloc[-1]) if df is not None and not df.empty else cost
```

---

## 5. Testing Framework & Verification Gaps

Executing `pytest tests/test_strategy` completed successfully with 25 tests passed:
- `test_base.py` (3 tests passed)
- `test_portfolio.py` (7 tests passed)
- `test_signals.py` (9 tests passed)
- `test_strategies.py` (6 tests passed)

### Why the Bug Slipped Through Tests
1. **Mocking State with Empty Positions**: The unit test `test_api_state_existing_file` mocked the OMS state file with `"positions": {}`. Because there were no positions, the loop invoking `store.load` was never executed, hiding the `TypeError`.
2. **Over-Mocking in Signals Test**: In `test_api_signals_generation`, the strategy objects were mocked, replacing the `generate_signals` method with a `MagicMock`. Consequently, the real strategy logic, technical indicators calculation, and timezone checks were never executed, leaving integration issues between the dashboard and data layers untested.

---

## 6. Recommendations for Institutional-Grade Enhancements

To upgrade this codebase from a retail-grade framework to an institutional-grade automated trading system, we recommend the following enhancements:

### A. Technical & Data Indicators
1. **Add Regime Indicators**:
   - **ADX (Average Directional Index)**: Only allow crossover/breakout signals when ADX > 20 (trending market).
   - **Historical Volatility Ratio**: Compare short-term volatility to long-term volatility. In low-volatility regimes, disable breakout entries to avoid false starts.
2. **Standardize Warm-up & Burn-in Periods**:
   - Force all strategies to discard the first `N` bars of computed indicators (e.g., 200 bars for SMA 200, 14 bars for ATR) before evaluating rules. This prevents `NaN` values and `0.0` ATR trailing stops.

### B. Strategy Improvements
1. **Stateless Signal Generation**:
   - Separate **signal generation** (which should be stateless, return +1/0/-1 based solely on historical price data) from **position management** (which is stateful and should live in the `OrderManager` or a dedicated `ExecutionEngine`).
   - Tracking position state (e.g., `max_price_since_entry` for trailing stops) inside the indicator/signal engine is an anti-pattern. If the bot crashes, the signal engine loses its memory of the entry price and trailing stops unless it reconstructs it from transaction logs, which is error-prone.

### C. Dashboard & Monitoring
1. **Strengthen State Reconciliations**:
   - Build a robust websocket connection instead of polling `/api/state` every 5 seconds to reduce broker/server overhead.
2. **Add Transaction Cost Models**:
   - Incorporate Alpaca commission/fees and estimated slippage (e.g., half-bid-ask spread) into the equity curve and performance statistics calculations.

### D. Testing Enhancements
1. **Add Contract/Integration Tests**:
   - Write integration tests for `app.py` that include mocked portfolios with actual open positions, verifying that PnL calculation and emergency liquidation do not regress.
2. **Verify Timezone Behavior**:
   - Test strategies with timezone-naive inputs explicitly to confirm they raise the expected `ValueError`.
