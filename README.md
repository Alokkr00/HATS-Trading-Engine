# H.A.T.S — Hedge & Algorithmic Trading System

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-161%20passed-brightgreen.svg)](https://github.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

H.A.T.S is a modular **quantitative trading framework and paper-trading engine** in Python built for backtesting, paper-trading, and managing swing trading strategies on US equities and options via the Alpaca API.

Originally started as an experimental trading bot, the project has evolved into a full-featured research and execution framework equipped with risk-gating, an event-driven backtesting engine, an ACID-compliant audit ledger, and a web dashboard.

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
│  • Correlation Offsets (SPY/QQQ/XLK Hedging Credit)                     │
│  • Minimum Short Option Margin Charge ($37.50/contract)                 │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Risk-Approved Orders
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       Order Management System (OMS)                     │
│  • Alpaca REST API Integration                                          │
│  • OTO (One-Triggers-Other) Bracket Orders (Stop-Loss & Take-Profit)     │
│  • Immutable SQLite Compliance Ledger (Database-level Triggers)         │
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

## Key Features

### 📈 1. Quantitative Strategies
* **Statistical Arbitrage / Pairs Trading**:
  * Computes a rolling OLS hedge ratio ($\beta$) between cointegrated pairs (e.g., `JPM`-`BAC`, `SPY`-`QQQ`).
  * Trades spread Z-Score deviations ($Z = \frac{\text{Spread} - \mu}{\sigma}$) on a market-neutral basis.
* **Mean Reversion & Regression**:
  * **Z-Score Reversion**: Captures price deviations from 20-period rolling moving averages.
  * **Linear Regression Channels**: Fits rolling linear regression bands and trades bounces off $\pm 2\sigma$ standard error channels.
* **Trend & Oscillator Suite**: MACD Histogram, Donchian Breakout, Stochastic Oscillator, Sector Momentum, Options IV Runup (Black-Scholes-based), and Breadth Thrust Reversion.

### 🛡️ 2. Risk & Portfolio Management (Custom Stress Grid)
* **15-Point Stress Matrix**: Evaluates portfolio liquidation value across a 15-scenario grid ($5$ price shifts $\times$ $3$ volatility shifts).
* **Option Revaluation**: Reprices option contracts under scenario shifts using Black-Scholes.
* **Correlation Offsets**: Applies partial hedging credit to opposite-signed positions across correlated assets (e.g., 0.85 offset for SPY/QQQ).
* **Short Option Floor**: Enforces a minimum $-37.50/contract risk charge for short options.

### ⚙️ 3. Execution & Compliance Infrastructure
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
* **Testing**: `pytest`, `pytest-cov` (161 unit & integration tests)

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
*Output: 161 passed in ~50s.*

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
