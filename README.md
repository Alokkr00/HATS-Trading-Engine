# H.A.T.S — Hedge & Algorithmic Trading System

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Build Status](https://github.com/Alokkr00/HATS-Trading-Engine/actions/workflows/tests.yml/badge.svg)](https://github.com/Alokkr00/HATS-Trading-Engine/actions)
[![Tests](https://img.shields.io/badge/tests-198%20passed-brightgreen.svg)](https://github.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

H.A.T.S is a modular **quantitative trading framework, paper-trading engine, and agentic research copilot** in Python built for systematic research, risk-gating, backtesting, and automated execution on US equities and options via the Alpaca API.

---

## 🤖 AI Trading Research Copilot (Multi-Agent System)

H.A.T.S features an **Agentic Research Copilot** powered by a **LangGraph State Machine** and Google Gemini. The system allows traders to ask complex research questions in natural language, retrieving grounded context, executing real backtests, evaluating a 15-point portfolio stress grid, and enforcing safety guardrails before formulating trade ideas.

```
                     ┌────────────────────────────────────────┐
                     │    User Query (API / Dashboard Web)    │
                     └───────────────────┬────────────────────┘
                                         ▼
                     ┌────────────────────────────────────────┐
                     │     LangGraph Multi-Agent Pipeline     │
                     │                                        │
                     │   ┌────────────────────────────────┐   │
                     │   │ 1. Research Agent (RAG + Data) │   │
                     │   └───────────────┬────────────────┘   │
                     │                   ▼                    │
                     │   ┌────────────────────────────────┐   │
                     │   │ 2. Quant Agent (Backtester)    │   │
                     │   └───────────────┬────────────────┘   │
                     │                   ▼                    │
                     │   ┌────────────────────────────────┐   │
                     │   │ 3. Risk Agent (Stress Grid)    │   │
                     │   └───────────────┬────────────────┘   │
                     │                   ▼                    │
                     │   ┌────────────────────────────────┐   │
                     │   │ 4. Critic Agent (Auditor)      │   │
                     │   └───────────────┬────────────────┘   │
                     │                   ▼                    │
                     │   ┌────────────────────────────────┐   │
                     │   │ 5. Synthesizer (Pydantic Out)  │   │
                     │   └────────────────────────────────┘   │
                     └───────────────────┬────────────────────┘
                                         ▼
                     ┌────────────────────────────────────────┐
                     │  Grounded Research Report with Proofs  │
                     │  (Citations, Confidence & Risk Flags)  │
                     └────────────────────────────────────────┘
```

### 📊 Benchmark Evaluation Scorecard (30 Golden Queries)
The AI Copilot is audited using an automated offline evaluation harness (`python -m src.ai.evaluation.offline_eval`) tracking groundedness, latency, and strict risk adherence:

| Metric | Score | Target |
| :--- | :--- | :--- |
| **Task Success Rate** | **100.0%** | $\ge 95\%$ |
| **Risk Compliance Rate** | **100.0%** | $100\%$ |
| **Citation Faithfulness** | **100.0%** | $\ge 90\%$ |
| **High Confidence Rate** | **100.0%** | $\ge 85\%$ |
| **Average Query Latency** | **4.65s** | $< 10\text{s}$ |
| **Estimated Cost / Query** | **\$0.00030** | $< \$0.01$ |

---

## 🔬 System Architecture

```
                        ┌────────────────────────┐
                        │   Yahoo Finance Data   │
                        └───────────┬────────────┘
                                    │ (Parquet Storage)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Strategy Execution Pipeline                    │
│ ┌──────────────────────────┐  ┌─────────────────────┐  ┌──────────────┐ │
│ │ Pairs Trading (StatArb)  │  │ Z-Score Mean Rev.   │  │ LinReg Band  │ │
│ └──────────────────────────┘  └─────────────────────┘  └──────────────┘ │
│ ┌──────────────────────────┐  ┌─────────────────────┐  ┌──────────────┐ │
│ │ Donchian Breakout        │  │ MACD Histogram      │  │ Stochastic   │ │
│ └──────────────────────────┘  └─────────────────────┘  └──────────────┘ │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Signals (Buy / Sell / Exit)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Portfolio Risk & Stress Grid                        │
│  • 15-Point Stress Grid (-15% to +15% Price, -25% to +25% Volatility)  │
│  • Static ETF Correlation Offsets (SPY/QQQ/XLK Hedging Credit)          │
│  • Minimum Short Option Margin Charge ($37.50/contract)                 │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Risk-Approved Orders
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       Order Management System (OMS)                     │
│  • Alpaca REST API Integration                                          │
│  • OTO (One-Triggers-Other) Bracket Orders (Stop-Loss & Take-Profit)     │
│  • Immutable SQLite Audit Ledger (Database-level Triggers)              │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
         ┌─────────────────────┐           ┌─────────────────────┐
         │  FastAPI Dashboard  │           │   Telegram Alerts   │
         │  (http://127.0.0.1) │           │   (Real-time Bot)   │
         └─────────────────────┘           └─────────────────────┘
```

---

## 🏛️ System Design Trade-offs & Architecture

* **Batch Cycle vs. Streaming Architecture**: H.A.T.S is intentionally built around scheduled batch execution cycles (`python -m src.main --interval 1d`) rather than a real-time HFT streaming pipeline. This aligns with the requirements of daily swing trading, minimizing memory footprint and operational complexity.
* **Single Authoritative State Store**: All order states, positions, and risk audit logs are persisted in an ACID-compliant SQLite database equipped with DDL-level immutability triggers. JSON files serve only as exported state snapshots.
* **Decoupled Risk Gate Interface**: The risk engine enforces a 15-scenario stress matrix before any order is dispatched. The risk module interface is decoupled from the OMS, allowing more complex multi-factor or Monte Carlo risk models to be plugged in.
* **Modular Strategy Architecture**: Strategies inherit from a common `BaseStrategy` interface, separating signal generation from order sizing and execution.─────────────────────────────────┬────────────────────────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
         ┌─────────────────────┐           ┌─────────────────────┐
         │  FastAPI Dashboard  │           │   Telegram Alerts   │
         │  (http://127.0.0.1) │           │   (Real-time Bot)   │
         └─────────────────────┘           └─────────────────────┘
```

---

## 🏛️ System Design Trade-offs & Architecture

* **Batch Cycle vs. Streaming Architecture**: H.A.T.S is intentionally built around scheduled batch execution cycles (`python -m src.main --interval 1d`) rather than a real-time HFT streaming pipeline. This aligns with the requirements of daily swing trading, minimizing memory footprint and operational complexity.
* **Single Authoritative State Store**: All order states, positions, and risk audit logs are persisted in an ACID-compliant SQLite database equipped with DDL-level immutability triggers. JSON files serve only as exported state snapshots.
* **Decoupled Risk Gate Interface**: The risk engine enforces a 15-scenario stress matrix before any order is dispatched. The risk module interface is decoupled from the OMS, allowing more complex multi-factor or Monte Carlo risk models to be plugged in.
* **Modular Strategy Architecture**: Strategies inherit from a common `BaseStrategy` interface, separating signal generation from order sizing and execution.

---

## 🔑 Core Features & Design

### 📊 1. Quantitative Strategies & Sample Backtest Benchmarks
The framework evaluates multiple strategy modules against historical daily bars with transaction cost modeling (1.5 bps spread + 3.0 bps slippage per side):

| Strategy | Asset | CAGR | Sharpe Ratio | Max Drawdown | Win Rate | Trades |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Donchian Breakout (20-day)** | SPY (2021-2025) | **12.36%** | **0.99** | -20.99% | 83.33% | 6 |
| **RSI Mean Reversion (14-day)** | SPY (2021-2025) | **0.59%** | **0.83** | -0.05% | 100.0% | 1 |
| **MA Crossover (20/50-day)** | SPY (2021-2025) | -0.10% | -0.03 | -4.29% | 50.00% | 2 |

* **Statistical Arbitrage / Pairs Trading**:
  * Computes a rolling OLS hedge ratio ($\beta$) between cointegrated pairs (e.g., `JPM`-`BAC`, `SPY`-`QQQ`).
  * Trades spread Z-Score deviations ($Z = \frac{\text{Spread} - \mu}{\sigma}$) on a market-neutral basis.
* **Mean Reversion & Regression**:
  * **Z-Score Reversion**: Captures price deviations from 20-period rolling moving averages.
  * **Linear Regression Channels**: Fits rolling linear regression bands and trades bounces off $\pm 2\sigma$ standard error channels.
* **Trend & Oscillator Suite**: MACD Histogram, Donchian Breakout, Stochastic Oscillator, Sector Momentum, Options IV Runup (Black-Scholes-based), and Breadth Thrust Reversion.

### 🛡️ 2. Risk & Portfolio Management (Custom Stress Grid)
* **15-Point Stress Matrix**: Evaluates portfolio liquidation value across a 15-scenario grid ($5$ price shifts $\times$ $3$ volatility shifts).
* **Option Revaluation**: Reprices option contracts under scenario shifts using Black-Scholes (fixed 5% risk-free rate assumption).
* **Correlation Offsets**: Applies partial hedging credit to opposite-signed positions across predefined ETF pairs (e.g., 0.85 offset for SPY/QQQ).
* **Short Option Floor**: Enforces a minimum $-37.50/contract risk charge for short options.

### ⚙️ 3. Execution & Audit Infrastructure
* **Alpaca Broker Integration**: Native support for live & paper trading via `alpaca-py`.
* **OTO Bracket Orders**: Automatically attaches stop-loss and take-profit orders at entry.
* **Immutable Compliance Ledger**: SQLite database with `BEFORE UPDATE` and `BEFORE DELETE` triggers that prevent altering trade history or audit logs.
* **Walk-Forward Backtesting**: Out-of-sample backtesting module with block-bootstrapped confidence intervals.

### 🌐 4. Web Dashboard & Monitoring
* **FastAPI Backend**: REST endpoints for real-time portfolio state, performance metrics, and strategy backtesting.
* **Basic Auth Protection**: Role-based access for `admin` and `readonly` users.
* **Telegram Integration**: Real-time notifications for order fills, risk rejections, and daily cycle summaries.

---

## 🛠️ Tech Stack

* **Language**: Python 3.11+
* **Data Processing**: `pandas`, `numpy`, `pyarrow` (Parquet)
* **Quantitative & Math**: `scipy`, `statsmodels`, custom Black-Scholes & OLS modules
* **Web Framework**: `FastAPI`, `uvicorn`, `websockets`
* **Broker SDK**: `alpaca-py` (Alpaca Trading API)
* **Database**: `SQLite3` + `SQLAlchemy` (with custom DDL triggers)
* **Testing**: `pytest`, `pytest-cov` (153 unit & integration tests)

---

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/Alokkr00/HATS-Trading-Engine.git
cd HATS-Trading-Engine

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file in the root directory:

```env
# Alpaca Paper Trading Credentials
APCA_API_KEY_ID=your_alpaca_key_id
APCA_API_SECRET_KEY=your_alpaca_secret_key
ALPACA_PAPER=1

# Telegram Alerts (Optional)
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_CHAT_ID="your_chat_id"

# Dashboard Authentication
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=hats_secure_pass
```

### 3. Run the Test Suite

```bash
pytest
```
*Output: 153 passed in ~90s.*

### 4. Run a Systematic Trading Cycle

```bash
python -m src.main --force
```

### 5. Launch the Dashboard

```bash
python -m src.dashboard.app --host 127.0.0.1 --port 8000
```
Navigate to `http://127.0.0.1:8000` and log in using `admin` / `hats_secure_pass`.

---

## ⚠️ Disclaimer

This software is for **educational, analytical, and paper-testing purposes only**. It is not financial advice, and should not be used as the sole basis for live financial trading. Systematic trading involves substantial risk of loss. Always test thoroughly in a paper-trading environment.

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
