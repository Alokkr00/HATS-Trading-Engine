# Transaction Cost Model — Webull Broker

> **Author:** Lead Quant Researcher
> **Created:** 2026-07-02
> **Status:** Draft — awaiting team review
> **Sprint:** 1 (Data & Infrastructure)
> **Companion to:** `docs/strategy_requirements.md`

---

## 1. Overview

Webull advertises "commission-free" trading. This does **not** mean trading is free.
Every trade incurs:

1. **Bid-ask spread** — the dominant cost for retail
2. **Slippage** — difference between expected and actual fill price
3. **Market impact** — our order moves the price (negligible for our sizes, but modeled)
4. **Regulatory fees** — SEC and FINRA fees on sells

We model all of these and require **all backtest results to be reported after costs.**
A strategy that looks good before costs but dies after costs is not a strategy.

---

## 2. Commission

| Fee Type | Amount | Notes |
|----------|--------|-------|
| Equity commission | **$0.00** | Webull's core value proposition |
| Options commission | $0.00 (we don't use options in Sprint 3) | — |

**Caveat:** Webull routes order flow to market makers (PFOF — Payment for Order Flow).
This is legal and disclosed, but it means our fills may be slightly worse than on
exchanges with direct market access. The cost of PFOF is embedded in wider effective
spreads. We capture this in our spread model below.

---

## 3. Bid-Ask Spread Model

The bid-ask spread is the most significant cost. We model it by liquidity tier.

### 3.1 Methodology

Spread cost per side = half the bid-ask spread (we cross the spread on entry and exit).
Round-trip spread cost = full bid-ask spread.

We express costs in **basis points (bps)** relative to the stock price for
comparability across price levels.

```
spread_bps = (ask - bid) / midpoint × 10,000
cost_per_side_bps = spread_bps / 2
round_trip_cost_bps = spread_bps
```

### 3.2 Spread Estimates by Tier

| Tier | Example Symbols | Avg Spread ($) | Avg Price ($) | Spread (bps) | Round-Trip Cost (bps) |
|------|----------------|----------------|---------------|-------------|----------------------|
| **Tier 1: Mega-cap / Major ETF** | SPY, QQQ, AAPL, MSFT, GOOGL | $0.01 | $150-500 | 0.5-1.5 | **1-3 bps** |
| **Tier 2: Large-cap** | META, NVDA, JPM, TSLA, DIA | $0.01-0.02 | $100-300 | 1-3 | **2-5 bps** |
| **Tier 3: Mid-cap** | S&P 400 components | $0.03-0.05 | $50-150 | 3-8 | **5-10 bps** |
| **Tier 4: Small-cap / Low volume** | Below S&P 600, thin ETFs | $0.05-0.20 | $20-80 | 10-50 | **15-60 bps** |

**Notes:**
- Spreads widen significantly during pre/post-market hours. Our model assumes
  **regular trading hours only** (9:30 AM - 4:00 PM ET).
- Spreads widen during high-volatility events (earnings, FOMC, etc.). We do NOT model
  event-specific widening — this is a source of model conservatism.
- PFOF routing may add 0.5-1 bps of hidden spread cost vs. direct exchange routing.
  We include this in our estimates above.

### 3.3 Spread Widening During Stress

During market stress (VIX > 30), spreads can widen 2-5× normal levels:

| Tier | Normal Spread | Stress Spread (2-5×) |
|------|--------------|---------------------|
| Tier 1 | 1-3 bps | 3-10 bps |
| Tier 2 | 2-5 bps | 5-15 bps |
| Tier 3 | 5-10 bps | 15-40 bps |
| Tier 4 | 15-60 bps | 50-150+ bps |

We model this as a **VIX-conditioned spread multiplier:**

```python
def spread_multiplier(vix: float) -> float:
    """Estimate spread widening factor based on VIX level."""
    if vix < 15:
        return 1.0
    elif vix < 25:
        return 1.0 + (vix - 15) * 0.05   # 1.0 to 1.5
    elif vix < 35:
        return 1.5 + (vix - 25) * 0.15   # 1.5 to 3.0
    else:
        return 3.0 + (vix - 35) * 0.10   # 3.0+ (capped in practice)
```

### 3.4 Our Universe Spread Assumptions

For our 30-35 symbol universe, the effective breakdown is:

| Category | # Symbols | Assumed Round-Trip Spread |
|----------|-----------|--------------------------|
| Core ETFs (SPY, QQQ, IWM, DIA) | 4 | **2 bps** |
| Large-cap stocks | 8 | **3 bps** |
| Sector ETFs (XLF, XLE, etc.) | 5 | **3 bps** |
| Mid-cap stocks | 13-18 | **7 bps** |

**Weighted average across universe: ~4-5 bps round-trip spread cost.**

---

## 4. Slippage Model

Slippage is the difference between the **expected fill price** (e.g., the open price
we target) and the **actual fill price** we'd receive.

### 4.1 Sources of Slippage

1. **Market order fill vs. reference price:** We plan to submit market orders at the
   open. The actual fill may differ from the "official" open price by a small amount.

2. **Time delay:** Between signal generation (prior day's close) and order submission
   (next day's pre-market or at-open), the price may gap.

3. **Order queue position:** As a retail PFOF order, we're not first in queue.
   Fills are typically at NBBO or better (legally required), but "at NBBO" means
   we eat the spread.

### 4.2 Slippage Estimate

| Tier | Slippage (bps per side) | Rationale |
|------|------------------------|-----------|
| Tier 1 (mega-cap/ETF) | **1-2 bps** | Very deep order books, open auction |
| Tier 2 (large-cap) | **2-3 bps** | Deep but not as tight |
| Tier 3 (mid-cap) | **3-5 bps** | Thinner books, more gaps |
| Tier 4 (small-cap) | **5-10+ bps** | Avoid if possible |

**Round-trip slippage = 2 × per-side slippage.**

**Default assumption for backtesting: 3 bps per side (6 bps round-trip).**

This is deliberately conservative for our Tier 1-2 heavy universe. It's better to
overestimate costs in backtesting and be pleasantly surprised in live trading than
the reverse.

### 4.3 Why 3 bps?

- Academic studies (Frazzini, Israel & Moskowitz 2015) estimate institutional slippage
  at 5-20 bps for US equities, but their position sizes are much larger than ours.
- Retail orders ($5K-$10K notional) have minimal market impact.
- The 3 bps figure accounts for: (a) imperfect fill at open, (b) PFOF routing
  inefficiency, (c) intraday price movement between signal and fill.
- We'd rather model 3 bps and be conservative than model 1 bps and be optimistic.

---

## 5. Regulatory Fees

These are small but real:

| Fee | Amount | Applies To |
|-----|--------|-----------|
| **SEC Transaction Fee** | $8.00 per $1,000,000 of principal | Sell orders only |
| **FINRA TAF** | $0.000166 per share (max $8.30/trade) | Sell orders only |

At our typical trade sizes ($5K-$10K):

```
SEC fee on $10,000 sell = $10,000 × ($8.00 / $1,000,000) = $0.08
FINRA fee on 100 shares = 100 × $0.000166 = $0.017

Total regulatory: ~$0.10 per sell
As % of $10,000 trade: 0.001% = 0.1 bps
```

**Regulatory fees are negligible (<0.5 bps) and we round them into our slippage
estimate.** We do not model them separately.

---

## 6. Total Cost Model

### 6.1 Round-Trip Cost Summary

| Component | Tier 1-2 (bps) | Tier 3 (bps) | Used in Backtest |
|-----------|----------------|-------------|------------------|
| Spread | 2-3 | 5-10 | **3 bps** (avg) |
| Slippage | 4-6 | 6-10 | **6 bps** (round-trip) |
| Regulatory | <0.5 | <0.5 | Included in slippage |
| **Total Round-Trip** | **6-9** | **11-20** | **9 bps default** |

**Default backtest cost: 9 bps per round-trip (0.09%).**

This is our baseline. We also run sensitivity analysis at 5, 9, 15, and 20 bps to
see how robust each strategy is to cost assumptions.

### 6.2 Cost in Dollar Terms

For a typical trade:

| Position Size | Round-Trip Cost (9 bps) | Annual Cost (50 trades/year) |
|--------------|------------------------|------------------------------|
| $5,000 | $4.50 | $225 |
| $10,000 | $9.00 | $450 |
| $15,000 | $13.50 | $675 |

For a $100,000 account doing ~100 round-trip trades/year:
- Average position: ~$10,000 (10% of account, per sizing rules)
- **Annual trading costs: ~$900 (0.9% of account)**

This is significant! A strategy must generate >0.9% annual return just to cover costs.
At 200 trades/year, costs double to ~$1,800 (1.8%).

### 6.3 Implementation in Code

```python
from dataclasses import dataclass
from enum import Enum


class LiquidityTier(Enum):
    MEGA_CAP = "mega_cap"      # SPY, QQQ, AAPL, MSFT
    LARGE_CAP = "large_cap"    # META, NVDA, JPM, etc.
    MID_CAP = "mid_cap"        # S&P 400 components
    SMALL_CAP = "small_cap"    # Below S&P 600


@dataclass
class CostModel:
    """Transaction cost model for backtesting.

    All costs in basis points (bps). 1 bps = 0.01% = 0.0001.
    """
    spread_bps: float       # Half-spread per side
    slippage_bps: float     # Per side
    sec_fee_per_million: float = 8.00   # SEC fee on sells
    finra_per_share: float = 0.000166   # FINRA TAF on sells

    def round_trip_cost_bps(self) -> float:
        """Total round-trip cost in basis points."""
        return 2 * (self.spread_bps + self.slippage_bps)

    def round_trip_cost_dollars(self, notional: float, shares: float) -> float:
        """Total round-trip cost in dollars for a given trade size."""
        spread_slip = notional * self.round_trip_cost_bps() / 10_000
        sec = notional * self.sec_fee_per_million / 1_000_000  # Sell only
        finra = shares * self.finra_per_share                   # Sell only
        return spread_slip + sec + finra

    @classmethod
    def for_tier(cls, tier: LiquidityTier) -> "CostModel":
        """Factory method: return cost model appropriate for liquidity tier."""
        configs = {
            LiquidityTier.MEGA_CAP:  cls(spread_bps=1.0, slippage_bps=1.5),
            LiquidityTier.LARGE_CAP: cls(spread_bps=1.5, slippage_bps=2.5),
            LiquidityTier.MID_CAP:   cls(spread_bps=3.5, slippage_bps=4.0),
            LiquidityTier.SMALL_CAP: cls(spread_bps=7.5, slippage_bps=7.0),
        }
        return configs[tier]

    @classmethod
    def default(cls) -> "CostModel":
        """Conservative default: 9 bps round-trip."""
        return cls(spread_bps=1.5, slippage_bps=3.0)  # RT = 2*(1.5+3.0) = 9 bps
```

---

## 7. Impact on Strategy Viability

### 7.1 Breakeven Analysis

A strategy must earn enough per trade to cover costs. Here's the minimum required
average trade return (after costs) to be profitable:

```
min_avg_return = round_trip_cost_bps / 10_000
```

| Cost (bps) | Min Avg Return per Trade | With 50% Win Rate, Min Win Size |
|------------|-------------------------|-------------------------------|
| 5 bps | 0.05% | 0.10% per winning trade (assuming equal # wins/losses) |
| 9 bps | 0.09% | 0.18% per winning trade |
| 15 bps | 0.15% | 0.30% per winning trade |
| 20 bps | 0.20% | 0.40% per winning trade |

These look small, but compounded over many trades and accounting for realistic win
rates, they erode returns significantly.

### 7.2 Strategy-Specific Cost Impact

#### MA Crossover (avg hold: 15-40 days, avg return target: 2-5%)

```
Typical trade return: 2-5% (winners), -1-2% (losers)
Round-trip cost: 9 bps = 0.09%
Cost as % of avg winning trade: 0.09% / 3.5% ≈ 2.6%
Cost as % of avg losing trade: 0.09% / 1.5% ≈ 6.0%
```

**Verdict: Costs are manageable.** The longer holding period and larger per-trade
returns mean costs are a small fraction of profits. This is the least
cost-sensitive of our three strategies.

#### RSI Mean Reversion (avg hold: 3-8 days, avg return target: 1-3%)

```
Typical trade return: 1-3% (winners), -1-2% (losers)
Round-trip cost: 9 bps = 0.09%
Cost as % of avg winning trade: 0.09% / 2.0% ≈ 4.5%
Cost as % of avg losing trade: 0.09% / 1.5% ≈ 6.0%
```

**Verdict: Costs are meaningful but tolerable.** Must stick to Tier 1-2 symbols to
keep spreads tight. Trading mid-caps with this strategy could push costs to 15 bps,
which eats 7.5% of already-small winners.

#### Bollinger Squeeze (avg hold: 5-15 days, avg return target: 2-4%)

```
Typical trade return: 2-4% (winners), -1.5-3% (losers, false breakouts)
Round-trip cost: 9 bps = 0.09%
Cost as % of avg winning trade: 0.09% / 3.0% ≈ 3.0%
Cost as % of avg losing trade: 0.09% / 2.0% ≈ 4.5%
```

**Verdict: Costs are manageable** but the low trade frequency means each trade matters
more. There's less room for error.

### 7.3 Annual Cost Drag by Strategy

| Strategy | Est. Trades/Year | Cost/Trade (9bps) | Annual Cost Drag |
|----------|-----------------|-------------------|------------------|
| MA Crossover | 60-150 | ~$9 on $10K | 0.5-1.4% of account |
| RSI Mean Reversion | 30-120 | ~$9 on $10K | 0.3-1.1% of account |
| Bollinger Squeeze | 20-40 | ~$9 on $10K | 0.2-0.4% of account |

**Key insight:** The Bollinger Squeeze strategy has the lowest cost drag due to
infrequent trading. If it has any edge at all, costs won't kill it. The MA Crossover,
with its higher trade frequency (especially during choppy markets), faces the highest
cost drag.

---

## 8. Cost Sensitivity Analysis Plan

For each strategy, we will report backtest results at multiple cost levels:

| Scenario | Round-Trip Cost (bps) | Purpose |
|----------|----------------------|---------|
| **Optimistic** | 5 bps | Best-case (mega-cap only, perfect fills) |
| **Baseline** | 9 bps | Our default assumption |
| **Conservative** | 15 bps | Mid-cap heavy or stressed markets |
| **Worst-case** | 20 bps | Small-cap or high-vol environment |

If a strategy is profitable at 5 bps but not at 9 bps, it is **not viable** — we
don't trust the optimistic scenario enough to risk capital on it.

If a strategy is profitable even at 15 bps, it is **robust** — we have high confidence
it will survive real-world conditions.

---

## 9. Comparison to Alternatives

For context, here's how Webull's cost structure compares:

| Broker | Commission | Est. Spread Cost | Total RT Cost |
|--------|-----------|-----------------|---------------|
| **Webull** | $0 | 3-7 bps (PFOF) | **5-10 bps** |
| Interactive Brokers (tiered) | $0.005/share (~1 bps) | 1-3 bps (direct routing) | **3-6 bps** |
| Schwab | $0 | 3-5 bps (PFOF) | **5-8 bps** |
| Institutional (DMA) | 1-3 bps | 0.5-2 bps | **2-5 bps** |

Webull is competitive with other retail brokers. The main disadvantage vs.
institutional is PFOF routing, which adds ~1-2 bps of hidden cost. For our position
sizes ($5K-$15K), this is a reasonable tradeoff.

---

## 10. Recommendations

1. **Restrict RSI Mean Reversion to Tier 1-2 symbols only.** The small trade returns
   cannot absorb mid-cap spread costs.

2. **Report all results at 9 bps (baseline).** This is our "single number" cost
   assumption. If forced to pick one number, use 9 bps round-trip.

3. **Run cost sensitivity at [5, 9, 15, 20] bps.** Strategies that only work at 5 bps
   are rejected. Strategies profitable at 15 bps are prioritized.

4. **Model VIX-conditioned spread widening in the backtest engine.** This is a
   second-order effect but matters for stress-period drawdown estimation.

5. **Track live fill quality.** Once deployed, log expected vs. actual fill prices for
   every trade. If average slippage exceeds our model, increase the cost assumption
   for ongoing evaluation.

---

## Appendix: Fee Schedule Sources

- Webull fee schedule: https://www.webull.com/pricing
- SEC fee rate (updated semiannually): https://www.sec.gov/fee-rate-advisory
- FINRA TAF: https://www.finra.org/rules-guidance/key-topics/trading-activity-fee
- Frazzini, Israel & Moskowitz (2015). *Trading Costs of Asset Pricing Anomalies.* (Institutional slippage estimates)

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-07-02 | Lead Quant Researcher | Initial draft |
