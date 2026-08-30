"""Test suite for AI Copilot deterministic tool wrappers."""

import pytest
from src.ai.tools.risk_tools import stress_test_portfolio, check_circuit_breaker
from src.ai.tools.portfolio_tools import get_live_portfolio_summary
from src.ai.tools.data_tools import fetch_ticker_data_summary


def test_stress_test_portfolio_tool():
    positions = [
        {"symbol": "SPY", "qty": 100, "curr_price": 500.0, "is_option": False},
        {"symbol": "QQQ", "qty": -50, "curr_price": 400.0, "is_option": False},
    ]
    res = stress_test_portfolio(positions=positions, account_equity=100000.0)
    assert res["status"] == "success"
    assert "worst_case_pct" in res
    assert "passed" in res
    assert isinstance(res["passed"], bool)


def test_check_circuit_breaker_tool():
    res = check_circuit_breaker()
    assert res["status"] in ["success", "error"]
    assert "circuit_breaker_tripped" in res
    assert "circuit_breaker_state" in res


def test_get_live_portfolio_summary_tool():
    res = get_live_portfolio_summary()
    assert res["status"] == "success"
    assert "net_liquidity" in res
    assert "cash_balance" in res
    assert isinstance(res["positions"], list)


def test_fetch_ticker_data_summary_tool():
    res = fetch_ticker_data_summary("SPY")
    assert res["status"] == "success"
    assert res["symbol"] == "SPY"
    assert "latest_close" in res
    assert "rsi14" in res
