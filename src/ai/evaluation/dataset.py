"""Golden evaluation dataset containing 30+ benchmark research queries."""

from __future__ import annotations

from typing import Any, Dict, List
from pydantic import BaseModel


class GoldenTestCase(BaseModel):
    id: str
    category: str
    query: str
    expected_symbol: str
    requires_risk_check: bool
    requires_backtest: bool
    expected_keywords: List[str]


GOLDEN_BENCHMARK_DATASET: List[GoldenTestCase] = [
    # Category 1: Market Regime & Macro (6 queries)
    GoldenTestCase(
        id="regime_01",
        category="regime",
        query="What is the current market regime for SPY and what is the Hurst exponent?",
        expected_symbol="SPY",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["regime", "hurst", "vix"],
    ),
    GoldenTestCase(
        id="regime_02",
        category="regime",
        query="Is the market currently trending or mean-reverting?",
        expected_symbol="SPY",
        requires_risk_check=False,
        requires_backtest=False,
        expected_keywords=["regime", "hurst"],
    ),
    GoldenTestCase(
        id="regime_03",
        category="regime",
        query="Evaluate QQQ macro structure and volatility environment.",
        expected_symbol="QQQ",
        requires_risk_check=False,
        requires_backtest=False,
        expected_keywords=["volatility", "regime"],
    ),
    GoldenTestCase(
        id="regime_04",
        category="regime",
        query="Check spot VIX level and its impact on position sizing multipliers.",
        expected_symbol="SPY",
        requires_risk_check=False,
        requires_backtest=False,
        expected_keywords=["vix", "multiplier"],
    ),
    GoldenTestCase(
        id="regime_05",
        category="regime",
        query="What is the 200-day moving average status for SPY?",
        expected_symbol="SPY",
        requires_risk_check=False,
        requires_backtest=False,
        expected_keywords=["200", "sma", "close"],
    ),
    GoldenTestCase(
        id="regime_06",
        category="regime",
        query="Are equity markets in a persistent or anti-persistent structure?",
        expected_symbol="SPY",
        requires_risk_check=False,
        requires_backtest=False,
        expected_keywords=["hurst", "persistent"],
    ),

    # Category 2: Risk Management & Stress Testing (8 queries)
    GoldenTestCase(
        id="risk_01",
        category="risk",
        query="Run a 15-scenario stress grid test on our current portfolio.",
        expected_symbol="SPY",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["stress", "drawdown", "grid"],
    ),
    GoldenTestCase(
        id="risk_02",
        category="risk",
        query="Check if the system circuit breaker is active or tripped.",
        expected_symbol="SPY",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["circuit", "breaker", "normal"],
    ),
    GoldenTestCase(
        id="risk_03",
        category="risk",
        query="Evaluate risk on opening 50 shares of AAPL at current market price.",
        expected_symbol="AAPL",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["risk", "stress", "compliant"],
    ),
    GoldenTestCase(
        id="risk_04",
        category="risk",
        query="What is the maximum allowed portfolio drawdown before trading halts?",
        expected_symbol="SPY",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["drawdown", "circuit", "breaker"],
    ),
    GoldenTestCase(
        id="risk_05",
        category="risk",
        query="Stress test a long TSLA breakout trade against a -15% market shock.",
        expected_symbol="TSLA",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["stress", "loss", "grid"],
    ),
    GoldenTestCase(
        id="risk_06",
        category="risk",
        query="What minimum margin floor is charged on short option contracts?",
        expected_symbol="SPY",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["margin", "option", "floor"],
    ),
    GoldenTestCase(
        id="risk_07",
        category="risk",
        query="Check if adding 100 shares of NVDA violates the 15% stress drawdown cap.",
        expected_symbol="NVDA",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["stress", "cap", "drawdown"],
    ),
    GoldenTestCase(
        id="risk_08",
        category="risk",
        query="Review portfolio heat and exposure limits across open holdings.",
        expected_symbol="SPY",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["heat", "exposure", "portfolio"],
    ),

    # Category 3: Strategy & Quantitative Backtesting (8 queries)
    GoldenTestCase(
        id="quant_01",
        category="quant",
        query="Backtest Donchian Breakout strategy on SPY from 2021 to 2025.",
        expected_symbol="SPY",
        requires_risk_check=True,
        requires_backtest=True,
        expected_keywords=["donchian", "cagr", "sharpe"],
    ),
    GoldenTestCase(
        id="quant_02",
        category="quant",
        query="Compare RSI Mean Reversion performance against MA Crossover on SPY.",
        expected_symbol="SPY",
        requires_risk_check=True,
        requires_backtest=True,
        expected_keywords=["rsi", "sharpe", "trades"],
    ),
    GoldenTestCase(
        id="quant_03",
        category="quant",
        query="Evaluate Linear Regression Channel trading setup on QQQ.",
        expected_symbol="QQQ",
        requires_risk_check=True,
        requires_backtest=True,
        expected_keywords=["linreg", "channel", "backtest"],
    ),
    GoldenTestCase(
        id="quant_04",
        category="quant",
        query="What is the historical win rate and max drawdown for Donchian channels on QQQ?",
        expected_symbol="QQQ",
        requires_risk_check=False,
        requires_backtest=True,
        expected_keywords=["win_rate", "drawdown"],
    ),
    GoldenTestCase(
        id="quant_05",
        category="quant",
        query="Calculate 20-day ATR and 14-day RSI for AAPL.",
        expected_symbol="AAPL",
        requires_risk_check=False,
        requires_backtest=False,
        expected_keywords=["rsi", "atr"],
    ),
    GoldenTestCase(
        id="quant_06",
        category="quant",
        query="Generate a trend-following trade setup on MSFT with stop loss.",
        expected_symbol="MSFT",
        requires_risk_check=True,
        requires_backtest=True,
        expected_keywords=["stop_loss", "entry", "trade"],
    ),
    GoldenTestCase(
        id="quant_07",
        category="quant",
        query="Backtest Z-Score mean reversion strategy with 1.5 bps fee and 3 bps slippage.",
        expected_symbol="SPY",
        requires_risk_check=False,
        requires_backtest=True,
        expected_keywords=["zscore", "slippage", "cagr"],
    ),
    GoldenTestCase(
        id="quant_08",
        category="quant",
        query="Suggest optimal position size for a swing trade on AMZN given current ATR.",
        expected_symbol="AMZN",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["position_size", "atr"],
    ),

    # Category 4: Audit & Decision Logs (4 queries)
    GoldenTestCase(
        id="audit_01",
        category="audit",
        query="What actions were logged in recent trading cycles from SQLite?",
        expected_symbol="SPY",
        requires_risk_check=False,
        requires_backtest=False,
        expected_keywords=["log", "cycle", "action"],
    ),
    GoldenTestCase(
        id="audit_02",
        category="audit",
        query="Retrieve recent risk rejection reasons from the immutable audit ledger.",
        expected_symbol="SPY",
        requires_risk_check=False,
        requires_backtest=False,
        expected_keywords=["risk_reason", "decision", "audit"],
    ),
    GoldenTestCase(
        id="audit_03",
        category="audit",
        query="Show current cash balance and net liquidation value.",
        expected_symbol="SPY",
        requires_risk_check=False,
        requires_backtest=False,
        expected_keywords=["net_liquidity", "cash"],
    ),
    GoldenTestCase(
        id="audit_04",
        category="audit",
        query="Check if there are any open unfilled orders currently in the OMS.",
        expected_symbol="SPY",
        requires_risk_check=False,
        requires_backtest=False,
        expected_keywords=["orders", "positions"],
    ),

    # Category 5: Complex Synthesis & Multi-Agent Planning (4 queries)
    GoldenTestCase(
        id="synthesis_01",
        category="synthesis",
        query="Comprehensive research report on SPY: regime status, Donchian backtest, and risk audit.",
        expected_symbol="SPY",
        requires_risk_check=True,
        requires_backtest=True,
        expected_keywords=["regime", "donchian", "stress", "confidence"],
    ),
    GoldenTestCase(
        id="synthesis_02",
        category="synthesis",
        query="Evaluate hedging SPY with QQQ during volatile market regimes.",
        expected_symbol="SPY",
        requires_risk_check=True,
        requires_backtest=False,
        expected_keywords=["hedge", "correlation", "regime"],
    ),
    GoldenTestCase(
        id="synthesis_03",
        category="synthesis",
        query="Should we initiate a long position in TSLA today given risk and macro regime?",
        expected_symbol="TSLA",
        requires_risk_check=True,
        requires_backtest=True,
        expected_keywords=["regime", "risk", "action"],
    ),
    GoldenTestCase(
        id="synthesis_04",
        category="synthesis",
        query="Full quantitative teardown for QQQ: calculate RSI, ATR, backtest breakout, and check circuit breaker.",
        expected_symbol="QQQ",
        requires_risk_check=True,
        requires_backtest=True,
        expected_keywords=["rsi", "atr", "circuit_breaker", "backtest"],
    ),
]
