# H.A.T.S — Hedge & Algorithmic Trading System

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-161%20passed-brightgreen.svg)](https://github.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A production-grade, event-driven **Quantitative Trading Engine & Risk Management System** built in Python for US Equities and Options. Features automated multi-strategy signal generation, a 15-point TIMS-style portfolio stress-testing engine, an OTO (One-Triggers-Other) bracket order manager with Alpaca API integration, an ACID-compliant immutable SQLite execution ledger, and a real-time FastAPI dashboard.

---

## 🏗️ Architecture Overview

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
│                    Portfolio Risk & Stress Engine                       │
│  • 15-Point Stress Grid (-15% to +15% Price, -25% to +25% Volatility)  │
│  • Correlation Offsets (SPY/QQQ/XLK Hedging Credit)                     │
│  • Minimum Short Option Margin Floor ($37.50/contract)                  │
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
  * Calculates rolling OLS hedge ratio ($\beta$) between cointegrated pairs (e.g., `JPM`-`BAC`, `SPY`-`QQQ`).
  * Computes spread Z-Score: $Z = \frac{\text{Spread} - \mu}{\sigma}$.
  * Enters market-neutral long/short positions when $Z > 2.0$ or $Z < -2.0$, and exits upon mean-reversion ($Z \to 0$).
* **Z-Score Mean Reversion**: Trades 20-period rolling price deviations with ATR-based stop-loss protection.
* **Linear Regression Channels**: Fits rolling linear regression bands and trades bounces off $\pm 2\sigma$ standard error boundaries.
* **Trend & Oscillator Suite**: Includes Donchian Breakout, MACD Histogram, Stochastic Oscillator, Sector Momentum, Options IV Runup (Black-Scholes-based), and Breadth Thrust Reversion.

### 🛡️ 2. Institutional Risk Management
* **TIMS-Style Portfolio Margin Simulator**:
  * Evaluates net portfolio liquidation value across a 15-point stress matrix ($5$ price shifts $\times$ $3$ volatility shifts).
  * Reprices options using Black-Scholes under shifted underlying prices and implied volatilities.
* **Correlation Offsets**: Applies partial hedging credit to opposite-signed positions across correlated assets (e.g., 0.85 offset for SPY/QQQ).
* **Option Margin Floor**: Enforces a minimum $-37.50/contract risk charge for short options to account for tail risk.

### ⚙️ 3. Execution & Compliance Infrastructure
* **Alpaca Broker Integration**: Native support for live & paper trading via `alpaca-py`.
* **OTO Bracket Orders**: Automatically attaches stop-loss and take-profit orders at entry.
* **Immutable Compliance Ledger**: SQLite database equipped with database-level `BEFORE UPDATE` and `BEFORE DELETE` triggers that prevent tampering with trade history or audit logs.
* **Walk-Forward Backtest Engine**: Out-of-sample backtesting with block-bootstrapped confidence intervals and Deflated Sharpe Ratio (DSR) calculation.

### 📊 4. Real-time Dashboard & Alerts
* **FastAPI Backend**: Provides REST endpoints for live state, performance metrics, and backtesting.
* **Role-Based Auth**: Basic Authentication with `admin` and `readonly` roles.
* **Telegram Integration**: Instant notifications for order fills, risk rejections, and daily cycle summaries.

---

## 🛠️ Tech Stack

* **Language**: Python 3.11+
* **Data Processing**: `pandas`, `numpy`, `pyarrow` (Parquet)
* **Quantitative Math**: `scipy`, `statsmodels`, custom Black-Scholes & OLS modules
* **Web Framework & API**: `FastAPI`, `uvicorn`, `websockets`
* **Broker SDK**: `alpaca-py` (Alpaca Trading API)
* **Database**: `SQLite3` + `SQLAlchemy` (with custom DDL triggers)
* **Testing**: `pytest`, `pytest-cov` (161 passing tests)

---

## 🚀 Quick Start

### 1. Clone & Setup Environment

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

### 2. Configure Environment Variables

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

### 4. Execute a Systematic Trading Cycle

```bash
# Force a 1d systematic cycle run (works during or outside market hours)
python -m src.main --force
```

### 5. Launch the Dashboard

```bash
python -m src.dashboard.app --host 127.0.0.1 --port 8000
```
Open your browser at `http://127.0.0.1:8000` and log in using `admin` / `hats_secure_pass`.

---

## 🧪 Testing & Validation

The codebase maintains 100% test pass rates across 161 unit & integration tests:
* `test_upgrades_phase2_strategies.py`: StatArb rolling OLS, Z-Score, and Linear Regression signals.
* `test_upgrades_phase2.py`: TIMS stress grid, correlation offsets, and SQLite immutability triggers.
* `test_oms.py`: Bracket order state machine, retries, and execution logging.

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
