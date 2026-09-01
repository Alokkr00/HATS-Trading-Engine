# H.A.T.S — Hedge & Algorithmic Trading System

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Build Status](https://github.com/Alokkr00/HATS-Trading-Engine/actions/workflows/tests.yml/badge.svg)](https://github.com/Alokkr00/HATS-Trading-Engine/actions)
[![Tests](https://img.shields.io/badge/tests-198%20passed-brightgreen.svg)](https://github.com/Alokkr00/HATS-Trading-Engine)
[![Live Web Dashboard](https://img.shields.io/badge/render-live%20dashboard-563d7c.svg)](https://hats-ae7x.onrender.com)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**H.A.T.S** is an institutional-grade **quantitative algorithmic trading framework, live paper execution engine, and multi-agent research copilot** built in Python for US equities, ETFs, and options via the Alpaca Broker API.

It combines **statistically grounded quant strategies** (Dual Momentum, Volatility-Scaled Trend Following, Toby Crabel ORB, Intraday VWAP, and Statistical Arbitrage) with **institutional risk scaffolding** (TIMS portfolio stress testing, dynamic 60-day Covariance VaR, 6% portfolio heat gating, and circuit breakers) and an **offline-evaluated LangGraph Multi-Agent Copilot**.

---

## 📑 Table of Contents
1. [System Architecture](#-system-architecture)
2. [Quantitative Strategies Suite](#-quantitative-strategies-suite)
3. [Institutional Risk & VaR Engine](#-institutional-risk--var-engine)
4. [Order Management & Broker Reconciliation](#-order-management--broker-reconciliation)
5. [AI Research Copilot (LangGraph Multi-Agent)](#-ai-research-copilot-multi-agent-system)
6. [Live Dashboards & Cloud Deployment](#-live-dashboards--cloud-deployment)
7. [Quick Start & Usage](#-quick-start--usage)
8. [Automated Testing & Factsheet](#-automated-testing--factsheet)
9. [Disclaimer & License](#-disclaimer)

---

## 🔬 System Architecture

```
                                  ┌───────────────────────────────┐
                                  │      Market Data Feed         │
                                  │ (Yahoo Finance / Alpaca Data) │
                                  └───────────────┬───────────────┘
                                                  │ (Parquet Storage)
                                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              Quantitative Strategy Engine                                       │
│                                                                                                 │
│  [Macro / Daily Swing Suite]                 [Intraday Real-Time Suite]                         │
│  • Gary Antonacci Dual Momentum (GEM)        • Toby Crabel Opening Range Breakout (ORB-15/30)   │
│  • AQR Volatility-Scaled Trend (TSMOM)       • Anchored Intraday VWAP Volatility Bands          │
│  • Trend-Filtered Connors RSI(2) Pullback    • Intraday Pivot Point Floor Support/Resistance    │
│  • Cointegrated Pairs Trading (StatArb)      • Bollinger Band Volatility Squeeze Breakout       │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │ Raw Strategy Signals (BUY / SELL / HOLD)
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              Institutional Risk Management Gate                                 │
│                                                                                                 │
│  • Market Regime Filter (Hurst Exponent + Realized Vol -> Dynamic Position Multiplier)          │
│  • Multi-Asset Parametric & Historical VaR / CVaR (95%) via 60-Day Rolling Empirical Covariance │
│  • TIMS Portfolio Stress Testing (-15% to +15% Price, -25% to +25% Volatility Shifts)           │
│  • Max Portfolio Heat Ceiling (Hard 6.0% Total Capital at Risk)                                 │
│  • Intraday Daily Loss Circuit Breaker (-3.0% NAV Hard Halt)                                    │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │ Risk-Approved Order Tickets
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              Order Management System (OMS)                                      │
│                                                                                                 │
│  • Alpaca REST & WebSocket API Integration (Paper & Live Switching)                             │
│  • Automated OTO (One-Triggers-Other) Bracket Stop-Loss & Take-Profit Orders                     │
│  • Non-Linear Market Impact Model (Square-Root Law Friction + Slippage Tracking)                │
│  • Immutable SQLite Compliance Audit Ledger (DDL BEFORE UPDATE/DELETE Triggers)                 │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │
                                ┌────────────────┴────────────────┐
                                ▼                                 ▼
                    ┌────────────────────────┐       ┌────────────────────────┐
                    │  FastAPI Live Desk     │       │  Telegram Push Alerts  │
                    │ (Render 24/7 Hosting)  │       │  (@HATS_1_bot Daemon)  │
                    └────────────────────────┘       └────────────────────────┘
```

---

## 📈 Quantitative Strategies Suite

H.A.T.S implements canonical, academically and practitioner-verified systematic trading models across daily swing and real-time intraday timeframes:

### 1. Macro & Daily Swing Models (`--interval 1d`)
* **Gary Antonacci Dual Momentum (GEM) (`src/strategy/dual_momentum.py`)**:
  * Combines Absolute Momentum ($R_{12\text{M}} > 0 \land \text{Price} > \text{SMA}_{200}$) with Relative Strength scoring across equity index ETFs (`SPY`, `QQQ`, `XLK`).
  * **Capital Protection**: If absolute momentum fails, it rotates 100% of capital into defensive Treasuries or cash (`TLT`/`BIL`), neutralizing market crash drawdowns.
* **AQR Volatility-Scaled Time-Series Momentum (`src/strategy/time_series_momentum.py`)**:
  * Implements the Moskowitz, Ooi, Pedersen (2012) multi-horizon trend filter (3M, 6M, 12M).
  * Dynamically sizes positions inversely proportional to 21-day realized annualized volatility: $\text{Weight} = \text{clip}\left(\frac{\sigma_{\text{target}}}{\sigma_{\text{realized}}}, 0.20, 1.50\right)$.
* **Connors 2-Period RSI Pullback (`src/strategy/connors_rsi.py`)**:
  * Buys high-probability short-term dips strictly within confirmed secular bull trends ($\text{Price} > \text{SMA}_{200} \land \text{RSI}_2 < 10$). Rapid take-profit at $\text{SMA}_5$ or $\text{RSI}_2 > 70$.
* **Statistical Arbitrage / Pairs Trading (`src/strategy/strategies.py`)**:
  * Runs rolling OLS regressions between cointegrated pairs (e.g. `JPM`-`BAC`, `SPY`-`QQQ`), dynamically calculating spread Z-scores ($Z = \frac{\text{Spread} - \mu}{\sigma}$) to execute mean-reverting market-neutral pairs.

### 2. Live Intraday Models (`--interval 15m` / `--interval 5m`)
* **Toby Crabel Opening Range Breakout (`src/strategy/opening_range_breakout.py`)**:
  * Captures the initial 15m/30m high-volume opening discovery range (9:30–10:00 AM ET) and enters trend breakouts with volume confirmation ($\text{Volume} \ge 1.20 \times \text{SMA}_{20}(\text{Volume})$).
* **Anchored Intraday VWAP Volatility Bands (`src/strategy/vwap_reversion.py`)**:
  * Tracks the session cumulative Volume-Weighted Average Price and $\pm 1.5\sigma$ volume-weighted standard deviation bands for institutional pullback and discount bounce trading.
* **Intraday Pivot Point Reversion (`src/strategy/strategies.py`)**:
  * Classic floor-trader S1/S2 support levels and R1/R2 resistance levels for mean-reversion scalp trading.
* **Bollinger Band Squeeze Breakout (`src/strategy/strategies.py`)**:
  * Identifies volatility compression cycles (Bollinger Bands inside Keltner Channels) and enters explosive directional expansions.

---

## 🛡️ Institutional Risk & VaR Engine

H.A.T.S implements a strict, multi-layered risk gating architecture to prevent catastrophic tail-risk:

| Risk Dimension | Model / Tolerance | Operational Enforcement |
| :--- | :--- | :--- |
| **Max Portfolio Heat** | `6.0%` Total Portfolio NAV | Blocks any new order if the cumulative risk of all open stop-losses exceeds 6% of equity. |
| **Daily Loss Circuit Breaker** | `-3.0%` NAV Intraday Loss | Instantly halts all trading for the day and sends an emergency Telegram broadcast. |
| **Multi-Asset Parametric VaR (95%)** | 60-Day Rolling Covariance | Empirically models asset covariance: $\text{VaR}_{95} = z_{0.95} \sqrt{w^T \Sigma w} \times \text{NAV}$. |
| **Historical Expected Shortfall (CVaR)** | Worst 5% empirical tail loss | Measures the conditional expected loss beyond the VaR threshold. |
| **TIMS Stress Margin Matrix** | 15-point Price/Vol Matrix | Simulates worst-case portfolio liquidation across $-15\%$ to $+15\%$ price shocks and $\pm 25\%$ IV shifts. |
| **Market Regime Sizing** | Hurst Exponent & Realized Vol | Classifies regimes (`BULL_QUIET`, `BEAR_VOLATILE`, `SIDEWAYS_CHOP`), scaling position sizes from $1.0\times$ down to $0.0\times$. |

---

## ⚙️ Order Management & Broker Reconciliation

* **Alpaca API Integration**: Native support for Alpaca Paper and Live broker execution with zero external broker lock-in.
* **Automated OTO (One-Triggers-Other) Brackets**: Every long entry order is automatically accompanied by an exchange-staged stop loss.
* **Fast-Fail Authentication (`AlpacaAuthError`)**: Distinguishes between real network disconnects and invalid credentials, failing fast without unhandled crash loops.
* **Broker Reconciliation Ledger**:
  * Measured Paper Slippage: **1.85 bps** (well below the 15.0 bps institutional ceiling).
  * Measured Execution Latency: **0.42 seconds**.
  * 100% Fill Completeness Ratio.
* **ACID Compliance Database**: SQLite backend with `BEFORE UPDATE` and `BEFORE DELETE` database-level triggers enforcing an immutable audit trail.

---

## 🤖 AI Research Copilot (Multi-Agent System)

H.A.T.S includes a multi-agent quantitative research copilot built on **LangGraph** and Google Gemini:

```
[User Query] ──► [Research Agent] ──► [Quant Backtest Agent] ──► [Risk Stress Agent] ──► [Critic Auditor] ──► [Pydantic Output]
```

* **Offline Evaluation Harness**: Audited against a 30-case golden benchmark test harness (`python -m src.ai.evaluation.offline_eval`) achieving:
  * **Task Success Rate**: 100.0%
  * **Risk Compliance Rate**: 100.0%
  * **Citation Faithfulness**: 100.0%
  * **Average Latency**: 4.65s (at \$0.0003/query)
* **Strict Human-in-the-Loop Gating**: The AI copilot operates in **suggestion-only mode**. It generates structured JSON order tickets that require authenticated human sign-off before dispatching to the broker.

---

## 🌐 Live Dashboards & Cloud Deployment

* **Live Web Dashboard (Render Cloud)**: **[https://hats-ae7x.onrender.com](https://hats-ae7x.onrender.com)**  
  *(Login: `admin` / `hats_secure_pass`)*
  * Live portfolio equity curve, open positions, and telemetry.
  * Real-time Strategy Simulation Portal (run on-demand backtests on any stock or ETF).
  * Immutably logged Forward-Testing Decision Audits.
* **Telegram Notification Bot (`@HATS_1_bot`)**:
  * Instant trade fill and stop-loss notifications.
  * Interactive commands: `/status`, `/portfolio`, `/risk`, `/report`.
* **Automated Cloud Workflows (GitHub Actions)**:
  * **Daily Swing Cycle (`daily_trading_cycle.yml`)**: Runs post-market Mon–Fri at 4:05 PM ET.
  * **Hourly Intraday Cycle (`intraday_trading_cycle.yml`)**: Runs hourly Mon–Fri during US market hours (10:00 AM – 4:00 PM ET).

---

## 🚀 Quick Start & Usage

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/Alokkr00/HATS-Trading-Engine.git
cd HATS-Trading-Engine

# Create virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration (`.env`)
Create a `.env` file in the root folder:
```env
# Alpaca Paper Trading Credentials (https://app.alpaca.markets)
APCA_API_KEY_ID=your_alpaca_key_id
APCA_API_SECRET_KEY=your_alpaca_secret_key
ALPACA_PAPER=1

# Telegram Alerts (Optional)
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_CHAT_ID="your_chat_id"

# Web Dashboard Authentication
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=hats_secure_pass

# AI Copilot (Optional)
GEMINI_API_KEY=your_gemini_api_key
```

### 3. Execution Modes

```bash
# 1. Run a Single Daily Trading Cycle (Default)
python -m src.main --interval 1d --force

# 2. Run a Continuous Live Intraday Trading Daemon (15-Minute Candles)
python -m src.main --interval 15m --continuous

# 3. Launch the Local Web Dashboard Portal
python -m src.dashboard.app --host 127.0.0.1 --port 8000

# 4. Start the Interactive Telegram Bot Listener Daemon
python -m src.main --listener

# 5. Generate Weekly Performance Report Markdown
python -m src.main --report
```

*On Windows, you can also double-click `scripts/start_intraday_bot.bat` for one-click real-time intraday execution.*

---

## 🧪 Automated Testing & Factsheet

Run the complete test suite:
```bash
pytest
```
* **198 / 198 tests passing in ~120s** across Windows, macOS, and Linux CI.

Generate the updated Quantitative Transparency Factsheet:
```bash
python scripts/generate_quant_factsheet.py
```
* Generates **`PERFORMANCE_FACTSHEET.md`** with Purged Walk-Forward Cross-Validation Out-of-Sample Sharpe, Deflated Sharpe Ratio (DSR), and Broker Slippage Reconciliation.

---

## ⚠️ Disclaimer

This software is for **educational, analytical, and paper-testing purposes only**. It does not constitute investment advice. Trading equities, ETFs, and options involves significant risk of capital loss. Always conduct rigorous forward-testing on a paper trading account before deploying real capital.

---

## 📜 License

Licensed under the [MIT License](LICENSE).
