# 📊 H.A.T.S Quantitative Strategy Factsheet & Transparency Report
**Last Updated:** `2026-08-30 11:41 UTC` | **Engine Version:** `v1.2.0-institutional`  
**Execution Environment:** Alpaca Paper Trading API (`ALPACA_PAPER=1`)  

---

## 🎯 Executive Summary & Verification Methodology
To ensure statistical credibility and eliminate overfitting, all strategies in H.A.T.S are audited under:
1. **Purged & Embargoed Walk-Forward Cross-Validation**: 252-day rolling training windows with a strict 5-day post-split embargo buffer to eliminate autocorrelation and look-ahead leakage.
2. **Deflated Sharpe Ratio (DSR)**: Formulated via Bailey & López de Prado to penalize non-normal kurtosis/skewness and correct for multiple testing bias ($N=10$ parameter trials).
3. **Non-Linear Friction**: Square-root market impact ($\Delta P = \eta \sigma \sqrt{\text{Shares}/\text{ADV}}$) + bid-ask spread + exchange fees.

---

## 📈 Strategy Walk-Forward Out-of-Sample Scorecard

| Strategy Model | Benchmark Ticker | In-Sample Sharpe | **Out-of-Sample Sharpe** | **Deflated Sharpe (DSR)** | **CVaR (95%)** | Profit Factor | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Dual Momentum (Antonacci GEM)** | `SPY` | 0.00 | **0.00** | **0.00** | -0.00% | 0.00 | 🟡 VALIDATING |
| **Volatility-Scaled Trend (AQR TSMOM)** | `QQQ` | 0.00 | **0.00** | **0.00** | -0.00% | 0.00 | 🟡 VALIDATING |
| **Connors 2-Day RSI Pullback** | `AAPL` | 0.08 | **0.08** | **0.00** | -0.04% | 1.06 | 🟡 VALIDATING |
| **MACD Histogram Trend** | `SPY` | 0.50 | **0.23** | **0.00** | -0.09% | 1.12 | 🟡 VALIDATING |
| **Sector ETF Momentum Rotation** | `XLK` | 0.44 | **0.37** | **0.00** | -0.09% | 1.19 | 🟡 VALIDATING |
| **Donchian Channel Breakout** | `NVDA` | -0.12 | **0.29** | **0.00** | -0.13% | 1.18 | 🟡 VALIDATING |
| **Pivot Point Intraday Reversion** | `MSFT` | 0.30 | **0.10** | **0.00** | -0.23% | 1.03 | 🟡 VALIDATING |

* **DSR Threshold**: A Deflated Sharpe Ratio > 0.50 indicates statistically significant edge after penalizing selection bias.
* **CVaR (95%)**: Represents the expected tail loss on the worst 5% of trading days.

---

## 🛡️ Real-Time Risk & VaR Parameter Envelope

| Risk Metric | Parameter / Tolerance | Active Engine Status | Enforcement Rule |
| :--- | :--- | :---: | :--- |
| **Max Portfolio Heat** | `6.00%` Total At-Risk Capital | **0.00% (Nominal)** | Blocks new order generation if sum of open stop losses >= 6% |
| **Circuit Breaker Max Daily Drawdown** | `-3.00%` Portfolio NAV | **CLEAR** | Freezes new orders and triggers Telegram emergency alert |
| **Daily Trade Frequency Ceiling** | `20 trades / day` | **0 / 20** | Halts algorithmic execution to prevent overtrading / churn |
| **Multi-Asset Parametric VaR (95%)** | Dynamic Rolling 60D Covariance | **1.14% NAV** | Tail loss envelope modeled via dynamic empirical covariance |
| **AI Order Ticket Mode** | Suggestion-Only Gating | **MANDATORY HUMAN SIGN-OFF** | Programmatic block on unauthenticated autonomous live order dispatch |

---

## 🔍 Broker Fill Reconciliation & Slippage Transparency

| Metric | Target Tolerance | Measured Paper Performance | Status |
| :--- | :--- | :---: | :--- |
| **Average Slippage Drift** | <= 15.0 bps | **1.85 bps** | 🟢 EXCELLENT |
| **Execution Latency Drag** | <= 2.00 s | **0.42 s** | 🟢 FAST |
| **Fill Completeness Ratio** | >= 95.0% | **100.0%** | 🟢 PERFECT |
| **Rejected / Stalled Orders** | `0` | **0** | 🟢 ZERO REJECTIONS |

---

## 📥 Trade Log & Audit Ledger Access
* Real-time executed fills and decision records are saved immutably into SQLite: `data/execution/trading_bot.db`.
* Web Dashboard Live Telemetry: [https://hats-ae7x.onrender.com](https://hats-ae7x.onrender.com)
* Continuous Integration: 187 automated unit tests passing across macOS, Linux, and Windows.
