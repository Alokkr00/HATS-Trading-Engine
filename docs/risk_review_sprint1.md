# Risk Review — Sprint 1: Data Layer

> **Reviewer:** Risk Management / Infrastructure Engineer
> **Date:** 2026-07-02
> **Sprint:** 1 — Data Pipeline (Fetcher → Cleaner → Store)
> **Status:** ⚠️ Review in progress — Data layer is under construction

---

## 1. Executive Summary

Sprint 1 builds the foundational data pipeline: fetching OHLCV data from
yfinance, cleaning it, and storing it locally.  **Every downstream decision —
strategy signals, position sizing, stop-loss placement, P&L reporting — depends
on this data being correct.**  A single bad adjusted-close value can silently
flip a buy into a sell, over-state returns in a backtest, or trigger a real
order on a phantom signal.

This document catalogues data-layer risks, defines validation gates the
pipeline must enforce, and provides concrete recommendations for the Data
Engineer.  It will be updated as code is delivered and reviewed.

---

## 2. Threat Model — What Can Go Wrong

| # | Threat | Severity | Likelihood | Impact |
|---|--------|----------|------------|--------|
| T1 | yfinance returns **wrong prices** (unofficial, scraping-based) | 🔴 High | Medium | Corrupt signals, real $ loss |
| T2 | **Stock splits / reverse splits** not adjusted, or double-adjusted | 🔴 High | Medium | Position sizing off by 2×–10× |
| T3 | **Look-ahead bias** — future data leaks into backtest | 🔴 Critical | High | Backtest results are fiction |
| T4 | **Survivorship bias** — only testing stocks that exist today | 🟡 Medium | High | Overstated strategy returns |
| T5 | **Data gaps** during volatile sessions (exactly when needed most) | 🟡 Medium | High | Missed stop-loss triggers |
| T6 | **Stale data in live mode** — API lag, rate-limit, or outage | 🔴 High | Medium | Orders at wrong price |
| T7 | **Dividend adjustment errors** — cash vs. proportional adjustment | 🟡 Medium | Medium | Slightly skewed returns |
| T8 | **Timezone / market-hours confusion** — bars at wrong timestamp | 🟡 Medium | Medium | Signals shifted by 1 bar |
| T9 | **Duplicate rows** or overlapping date ranges after incremental fetch | 🟡 Medium | Medium | Inflated bar count, corrupt indicators |
| T10 | **Silent schema change** in yfinance upstream | 🔴 High | Low | Pipeline breaks or silently returns NaN |

---

## 3. Data Quality Risks & Mitigations

### 3.1 yfinance Is Unofficial — Trust But Verify

yfinance scrapes Yahoo Finance.  It is **not an official API** and has no SLA.
Known issues include:

* Occasional wrong adjusted-close values after corporate actions.
* Intermittent HTTP 429 rate-limits that return empty DataFrames.
* Schema changes that break silently (column renames, dtype changes).
* 1-minute data only available for the last 7 days (then gone forever).

**Required mitigations:**

1. **Schema assertion on every fetch:**
   ```python
   REQUIRED_COLUMNS = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
   assert REQUIRED_COLUMNS.issubset(set(df.columns)), f"Missing columns: {REQUIRED_COLUMNS - set(df.columns)}"
   ```
2. **Empty-response guard:** If `df` is empty or has < 1 row, raise, do not
   return silently.
3. **Cross-validation (recommended for live):** Spot-check a random recent
   close against a second source (e.g., Alpaca's own quote API) before
   accepting a full dataset.
4. **Pin yfinance version** in `requirements.txt` and test on every upgrade.
5. **Retry with back-off** on HTTP errors; after 3 retries, flag symbol as
   unavailable — do NOT proceed with partial data.

### 3.2 Stock Splits & Corporate Actions

A split that isn't properly reflected in adjusted prices will cause:

* ATR to be wildly wrong → stop-loss at nonsensical level.
* Position-sizing math to compute wrong share counts.
* Percentage-change signals (momentum, mean-reversion) to fire falsely.

**Required mitigations:**

1. **Always use `Adj Close` for all calculations**, never raw `Close`.
2. **Detect split artifacts:** Flag any day where
   `|close_today / close_yesterday - 1| > 0.25` AND volume is normal — this
   is almost certainly an unadjusted split.
   ```python
   pct_change = df["Adj Close"].pct_change()
   suspicious = pct_change.abs() > 0.25
   # Cross-check: if volume is NOT abnormally low, likely a data error
   ```
3. **Re-fetch full history** periodically (not just incremental appends) to
   pick up retroactive adjustments Yahoo applies.
4. **Log a warning** for every split-like move detected; require human ack
   before the symbol is used in live trading after a split event.

### 3.3 Data Gaps & Missing Bars

Yahoo can return data with missing trading days, especially around:

* Half-days (day before Thanksgiving, July 3, etc.)
* Flash-crash / halt days where data quality is degraded.
* Delisted / re-listed instruments.

**Required mitigations:**

1. **Check for calendar gaps.** Generate expected trading days from a market
   calendar (use `exchange_calendars` or `pandas_market_calendars`) and
   compare:
   ```python
   expected = mcal.get_calendar("XNYS").valid_days(start, end)
   actual = df.index.normalize()
   missing = expected.difference(actual)
   if len(missing) > MAX_GAP_DAYS:
       raise DataQualityError(f"{symbol}: {len(missing)} missing trading days")
   ```
2. **Never forward-fill prices by default.** Forward-filling a $50 close into
   a missing day hides a data problem and creates a phantom "flat" bar that
   will suppress volatility estimates. If forward-fill is used (e.g., for
   calendar-day alignment), tag those rows explicitly so strategies can
   exclude them.
3. **Reject symbols exceeding `max_gap_days` (5)** from any strategy run
   without explicit override.

### 3.4 Stale Data in Live Mode

In live trading, stale quotes can cause orders at wrong prices.

**Required mitigations:**

1. **Timestamp every data fetch** (wall-clock time, not the bar's timestamp).
2. **Before any order, assert:**
   ```python
   age = datetime.now(tz=pytz.UTC) - last_fetch_time
   if age > timedelta(minutes=STALE_DATA_MINUTES):
       raise StaleDataError(f"Data is {age} old — refusing to trade")
   ```
3. **In backtest mode, this check is a no-op** (historical data is inherently
   "old").

### 3.5 Volume Anomalies

Zero-volume bars are a red flag — they indicate the bar was synthesized or the
stock was halted / illiquid.

**Required mitigations:**

1. **Flag zero-volume bars.** If > 2% of bars have volume == 0, reject the
   symbol (`max_allowed_zero_volume_pct: 0.02` in config).
2. **Check minimum average daily volume** (`min_avg_daily_volume: 100_000`).
   Low-liquidity names will cause slippage in live trading that backtests
   don't model.

---

## 4. Look-Ahead Bias Prevention Checklist

Look-ahead bias is the single most dangerous backtest error.  It makes
worthless strategies look profitable.

| # | Check | Description | How to Enforce |
|---|-------|-------------|----------------|
| L1 | **No future-close in same-bar signal** | A signal generated on bar `t` must use only data from bars `≤ t-1`, OR be executed at bar `t+1`'s open | Code review + unit tests |
| L2 | **Train/test split respects time** | Walk-forward or expanding-window only; NEVER random shuffle split on time series | Code review |
| L3 | **Indicators use only past data** | Rolling windows must not include the current bar if the signal is acted on at the current bar | Unit test: compare indicator output with manual calculation |
| L4 | **Adjusted prices fetched as of backtest date** | Don't use today's adjustment factors for 2020 data — Yahoo re-adjusts retroactively | Hard to enforce perfectly; document as known limitation |
| L5 | **No `shift(-1)` or equivalent** | Negative shifts in pandas pull future data into the present row | `grep -rn "shift\s*(\s*-" src/` in CI |
| L6 | **Event data (earnings, splits) timestamped correctly** | If used, ensure the event timestamp is the announcement time, not the filing time | Manual review |
| L7 | **Universe selection is point-in-time** | Don't select today's S&P 500 for a 2015 backtest — use historical constituents | See Survivorship Bias section |

### Automated Enforcement (CI/Pre-commit)

```bash
# Reject any negative shift in production code
grep -rn "shift\s*(\s*-" src/ && echo "FAIL: Negative shift detected" && exit 1

# Reject peeking at 'Close' when 'Adj Close' should be used
grep -rn '\\["Close"\\]' src/ | grep -v "Adj Close" && echo "WARNING: Raw Close used"
```

---

## 5. Survivorship Bias Considerations

**The problem:** If we backtest a strategy on today's stock universe, we only
test stocks that survived.  The ones that crashed, were delisted, or were
acquired are invisible — and they are exactly the ones that would have
generated the largest losses.

**Severity:** This is a medium-term concern.  Sprint 1 doesn't build the
backtester, but the data layer shapes what's possible later.

**Recommendations for the Data Engineer:**

1. **Store data by symbol+date range**, not just "current" data.  This allows
   us to add historical constituent lists later.
2. **Never automatically delete old data** for tickers that are now invalid.
   Archive them instead.  A delisted stock's history is precious for honest
   backtesting.
3. **Add a `status` field** to the symbol metadata: `active`, `delisted`,
   `acquired`, `suspended`.
4. **In Sprint 3+**, integrate a historical S&P 500 / Russell 2000 constituent
   list so universe selection is point-in-time.

---

## 6. Data Validation Requirements

Every dataset that enters the system — whether from yfinance, a CSV, or any
future source — must pass the following gates **before** it is accepted by the
data store.

### 6.1 Structural Validations (must pass, no exceptions)

| ID | Check | Fail Action |
|----|-------|-------------|
| V1 | DataFrame is not empty | Raise `EmptyDataError` |
| V2 | Required columns present (`Open`, `High`, `Low`, `Close`, `Adj Close`, `Volume`) | Raise `SchemaError` |
| V3 | Index is `DatetimeIndex`, sorted ascending, no duplicates | Raise `IndexError` |
| V4 | No NaN in OHLCV columns | Raise or drop rows + warn (configurable) |
| V5 | All prices > 0 | Raise `InvalidPriceError` |
| V6 | `High >= Low` on every bar | Raise `InvalidPriceError` |
| V7 | `High >= Open` and `High >= Close` on every bar | Raise `InvalidPriceError` |
| V8 | `Low <= Open` and `Low <= Close` on every bar | Raise `InvalidPriceError` |
| V9 | Volume ≥ 0 (no negative volume) | Raise `InvalidVolumeError` |
| V10 | Minimum bar count ≥ `min_bars_required` (200) | Reject symbol |

### 6.2 Statistical Validations (warn or reject, configurable)

| ID | Check | Fail Action |
|----|-------|-------------|
| S1 | Single-day return > 50% | Warn + flag for review (could be split artifact) |
| S2 | Zero-volume bars > 2% of total | Reject symbol |
| S3 | Calendar-day gap > `max_gap_days` (5 trading days) | Reject symbol |
| S4 | Identical OHLC on > 5 consecutive bars | Warn (frozen/stale data) |
| S5 | Adjusted close diverges from close by > 50% | Warn (check split/dividend) |
| S6 | Average daily volume < `min_avg_daily_volume` | Reject symbol |

### 6.3 Validation Implementation Guidance

```python
class DataValidator:
    """
    Validate OHLCV DataFrames before they enter the data store.
    Every check is logged.  Structural failures raise.
    Statistical failures warn or reject based on config.
    """

    def validate(self, df: pd.DataFrame, symbol: str) -> ValidationResult:
        results = []
        results.append(self._check_not_empty(df, symbol))
        results.append(self._check_schema(df, symbol))
        results.append(self._check_index(df, symbol))
        results.append(self._check_no_nans(df, symbol))
        results.append(self._check_price_sanity(df, symbol))
        results.append(self._check_hloc_consistency(df, symbol))
        results.append(self._check_volume(df, symbol))
        results.append(self._check_min_bars(df, symbol))
        results.append(self._check_returns(df, symbol))
        results.append(self._check_gaps(df, symbol))
        # ... etc.
        return ValidationResult(results)
```

---

## 7. Error Handling Requirements for the Data Pipeline

The data pipeline (fetcher → cleaner → store) must handle errors according to
these principles:

### 7.1 Principles

1. **Fail loud, not silent.**  An exception is always better than silently
   returning bad data.  `return pd.DataFrame()` is FORBIDDEN as a way to
   handle errors — it hides failures.
2. **Fail closed.**  If validation fails, the data does NOT enter the store.
   The symbol is flagged as `unavailable`.
3. **Every error is logged** with: timestamp, symbol, stage (fetch/clean/store),
   error type, and full traceback.
4. **Retries are bounded.** Max 3 retries with exponential back-off (1s, 2s,
   4s).  After 3 failures, mark symbol as failed, do NOT retry forever.
5. **Partial success is OK at portfolio level** but NOT at symbol level.  If
   we're fetching 50 symbols and 3 fail, those 3 are marked failed and the
   other 47 proceed.  But a single symbol's data is either fully valid or
   fully rejected — no "partial" OHLCV.

### 7.2 Error Categories & Handling

| Error Category | Examples | Handling |
|----------------|----------|----------|
| **Network / API** | HTTP 429, timeout, DNS failure | Retry 3× with back-off; then mark failed |
| **Empty response** | yfinance returns empty DataFrame | Retry once (could be transient); then mark failed |
| **Schema change** | Missing column, wrong dtype | Raise `SchemaError`; alert team; do not proceed |
| **Validation failure** | Prices ≤ 0, High < Low | Raise `InvalidDataError`; log full details |
| **Storage I/O** | Disk full, permission denied, corrupt parquet | Raise; alert; halt pipeline for this symbol |
| **Rate limit** | yfinance 429 / Yahoo block | Exponential back-off up to 60s; reduce batch size |

### 7.3 Required Error Fields (Logging)

```python
{
    "timestamp": "2026-07-02T05:10:27Z",
    "level": "ERROR",
    "stage": "fetcher",          # fetcher | cleaner | store
    "symbol": "AAPL",
    "error_type": "SchemaError",
    "message": "Missing column: Adj Close",
    "retry_count": 2,
    "traceback": "..."
}
```

---

## 8. Recommendations for the Data Engineer

These are concrete, actionable items I need the Data Engineer to implement or
confirm:

### 🔴 Must Have (Block deployment)

| # | Recommendation |
|---|----------------|
| R1 | Implement `DataValidator` class with all V1–V10 checks from §6.1 |
| R2 | Never return an empty DataFrame on failure — always raise |
| R3 | Use `Adj Close` everywhere; raw `Close` only for display / logging |
| R4 | Pin yfinance version in `requirements.txt` |
| R5 | Add retry logic with exponential back-off (max 3 retries) to the fetcher |
| R6 | Ensure `DatetimeIndex` is timezone-aware (US/Eastern or UTC) and sorted |
| R7 | Add schema assertion at the top of every data-ingestion function |
| R8 | Log every fetch with: symbol, date range requested, rows returned, elapsed time |

### 🟡 Should Have (Sprint 2)

| # | Recommendation |
|---|----------------|
| R9 | Add market-calendar gap detection (use `exchange_calendars`) |
| R10 | Store raw + cleaned data separately so we can audit transformations |
| R11 | Add a data freshness timestamp to stored data for stale-data checks |
| R12 | Build a simple data health dashboard (per-symbol validation status) |

### 🟢 Nice to Have (Sprint 3+)

| # | Recommendation |
|---|----------------|
| R13 | Cross-validate prices against a second source (Alpaca quote API) |
| R14 | Add historical constituent lists for survivorship-bias-free backtests |
| R15 | Implement incremental fetch with de-duplication and overlap handling |
| R16 | Add data lineage tracking (source → raw → cleaned → stored, with hashes) |

---

## 9. Failure Scenario Analysis

### 9.1 Scenario: yfinance Returns Wrong Adjusted Close After a Split

**What happens:**
A 4-for-1 split occurs.  yfinance initially returns correctly adjusted data
but a later re-fetch reverts some historical bars to unadjusted.  Our stored
data now has a 4× jump in the middle.

**Consequence:**
- ATR spikes to 4× normal → position size drops to ¼ (under-invested).
- Momentum signal fires a massive "buy" signal on the phantom 300% move.
- In live trading, the position sizer could place an outsized order if the
  error goes the other direction.

**Mitigation:**
- V-check S1 catches single-day returns > 50%.
- Full re-fetch + diff against stored data; flag any bar that changed by > 5%.
- Human review before any data update that modifies > 10 historical bars.

### 9.2 Scenario: Data Gap on a Crash Day

**What happens:**
Yahoo's servers are overloaded during a market crash.  Our fetcher gets rate-
limited and the 14:30–15:00 bars are missing (intraday) or the daily bar
returns volume = 0.

**Consequence:**
- Stop-loss isn't evaluated because the bar never arrived.
- ATR underestimates volatility because the crash bar is missing.
- Backtest looks better than reality because the worst bar is gone.

**Mitigation:**
- Gap detection flags the missing bar immediately.
- In live mode: stale-data check refuses to send orders.
- In backtest mode: symbol is rejected if gap coincides with high-VIX days
  (Sprint 3 enhancement).

### 9.3 Scenario: Duplicate Rows After Incremental Fetch

**What happens:**
We fetch 2020-01-01 to 2020-12-31, then later fetch 2020-12-01 to 2021-06-30.
The overlap (December) creates duplicate rows.

**Consequence:**
- Indicators that count rows (e.g., "200-bar SMA") shift forward by the
  number of duplicates.
- `pct_change()` shows 0% returns for duplicated bars → suppresses volatility.

**Mitigation:**
- V3 check: index must have no duplicates.
- Data store must de-duplicate on `(symbol, date)` before writing.
- Log a warning when duplicates are detected and removed.

### 9.4 Scenario: Strategy Code Uses `shift(-1)` (Look-Ahead)

**What happens:**
A developer accidentally writes `df["signal"] = df["Close"].shift(-1) > df["Close"]`
which peeks one bar into the future.

**Consequence:**
- Backtest shows near-perfect returns.  Live trading loses money immediately.
- This is the #1 most common backtest bug.

**Mitigation:**
- CI check: `grep -rn "shift\s*(\s*-" src/` — fail the build.
- Code review policy: any use of `.shift()` with a negative argument requires
  a written justification and risk-engineer sign-off.
- Backtest framework should provide a `get_data(as_of=t)` API that makes
  look-ahead structurally impossible (Sprint 3).

### 9.5 Scenario: yfinance Schema Change

**What happens:**
yfinance 0.3.x renames `Adj Close` to `Adjusted_Close` or changes
the DataFrame structure.  Our fetcher doesn't crash — it just silently
returns a DataFrame missing `Adj Close`, and downstream code falls back
to `Close` without adjustment.

**Consequence:**
- All historical split/dividend adjustments are lost.
- Returns are computed on raw prices — grossly incorrect for stocks with
  large dividends or splits.

**Mitigation:**
- Schema assertion (V2) catches this immediately.
- Pin yfinance version.  Upgrade only after testing in a staging environment.
- CI integration tests that fetch real data for 3 known tickers and validate
  schema + value ranges.

---

## 10. Audit & Compliance

Every data-pipeline run must produce an audit record containing:

```yaml
run_id: "uuid"
timestamp: "2026-07-02T05:10:00Z"
symbols_requested: 50
symbols_succeeded: 47
symbols_failed: ["XYZ", "ABC", "DEF"]
failure_reasons:
  XYZ: "EmptyDataError: yfinance returned 0 rows"
  ABC: "SchemaError: Missing column Adj Close"
  DEF: "ValidationError: High < Low on 3 bars"
total_bars_stored: 47000
elapsed_seconds: 120
data_source: "yfinance"
data_source_version: "0.2.40"
```

This record will be consumed by the monitoring system in Sprint 4.

---

## 11. Open Questions for the Team

1. **Data Engineer:** How are you handling timezone normalization?  All
   timestamps must be either US/Eastern or UTC — mixing will cause
   off-by-one-bar errors.

2. **Data Engineer:** What format is the data store using (Parquet, SQLite,
   CSV)?  Parquet is strongly preferred for type safety, compression, and
   columnar access.  CSV is fragile (float precision loss, date parsing
   ambiguity).

3. **Algo Developer:** Will the backtester provide a `DataView` abstraction
   that prevents look-ahead by construction, or will we rely on convention
   + code review?

4. **Team:** Do we need intraday bars in Sprint 1, or is daily sufficient?
   Intraday data from yfinance has a 7-day retention limit — if we need it
   later, we must start collecting NOW.

---

## 12. Summary of Risk Verdicts

| Area | Verdict | Notes |
|------|---------|-------|
| yfinance as data source | ⚠️ Acceptable with mitigations | Must validate aggressively; no blind trust |
| Daily OHLCV quality | ✅ Manageable | Standard validations cover most issues |
| Look-ahead bias | 🔴 High risk | Requires structural prevention, not just reviews |
| Survivorship bias | ⚠️ Deferred risk | Acceptable for Sprint 1 if we design data store correctly |
| Data gaps | ⚠️ Acceptable with mitigations | Gap detection + rejection policy needed |
| Live data staleness | 🔴 Must enforce | Stale-data check is non-negotiable before any order |
| Error handling | 🔴 Must enforce | Fail-loud, fail-closed, log everything |

---

## Appendix A: Risk Defaults Reference

See `config/risk_defaults.yaml` for all configurable risk parameters.  All
data-quality thresholds referenced in this document are sourced from that file.

---

*This document is a living artifact.  It will be updated after Sprint 1 code
review and before Sprint 2 planning.*
