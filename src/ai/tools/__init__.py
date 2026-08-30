"""Deterministic Tool Wrappers for H.A.T.S AI Copilot."""

from src.ai.tools.risk_tools import stress_test_portfolio, check_circuit_breaker
from src.ai.tools.backtest_tools import run_strategy_backtest
from src.ai.tools.portfolio_tools import get_live_portfolio_summary, get_recent_decision_logs
from src.ai.tools.data_tools import get_market_regime, fetch_ticker_data_summary

__all__ = [
    "stress_test_portfolio",
    "check_circuit_breaker",
    "run_strategy_backtest",
    "get_live_portfolio_summary",
    "get_recent_decision_logs",
    "get_market_regime",
    "fetch_ticker_data_summary",
]
