"""Unit tests for PortfolioVaREngine (Historical & Parametric VaR / CVaR)."""

import numpy as np
import pandas as pd
import pytest

from src.risk.var_engine import PortfolioVaREngine


@pytest.fixture
def sample_portfolio_returns():
    """Create 100 days of correlated multi-asset returns."""
    np.random.seed(42)
    # Generate SPY, QQQ, and AAPL returns
    spy = np.random.normal(0.0005, 0.012, 100)
    qqq = 0.8 * spy + np.random.normal(0.0002, 0.008, 100)
    aapl = 0.6 * spy + np.random.normal(0.0001, 0.010, 100)

    dates = pd.date_range("2026-01-01", periods=100, freq="B")
    return pd.DataFrame({"SPY": spy, "QQQ": qqq, "AAPL": aapl}, index=dates)


def test_portfolio_var_cvar_calculation(sample_portfolio_returns):
    """Verify VaR and CVaR calculations on a long portfolio."""
    engine = PortfolioVaREngine(lookback_bars=60)
    positions = {"SPY": 50000.0, "QQQ": 30000.0, "AAPL": 20000.0}

    res = engine.calculate_portfolio_var_cvar(positions, sample_portfolio_returns)

    assert res["total_exposure_usd"] == 100000.0
    assert res["historical_var_95_usd"] > 0
    assert res["historical_var_99_usd"] >= res["historical_var_95_usd"]
    assert res["historical_cvar_95_usd"] >= res["historical_var_95_usd"]
    assert res["historical_cvar_99_usd"] >= res["historical_cvar_99_usd"]
    assert res["portfolio_volatility_annualized"] > 0


def test_hedged_portfolio_var_reduction(sample_portfolio_returns):
    """Verify that a market-neutral hedged position reduces portfolio VaR."""
    engine = PortfolioVaREngine(lookback_bars=60)
    
    # Long SPY $50k, Short QQQ -$50k (Hedged)
    hedged_positions = {"SPY": 50000.0, "QQQ": -50000.0}
    res_hedged = engine.calculate_portfolio_var_cvar(hedged_positions, sample_portfolio_returns)

    # Long SPY $50k, Long QQQ $50k (Unhedged Long)
    long_positions = {"SPY": 50000.0, "QQQ": 50000.0}
    res_long = engine.calculate_portfolio_var_cvar(long_positions, sample_portfolio_returns)

    # Volatility and dollar VaR should be substantially lower for hedged pair
    assert res_hedged["portfolio_volatility_daily"] < res_long["portfolio_volatility_daily"]
    assert res_hedged["historical_var_95_usd"] < res_long["historical_var_95_usd"]


def test_empty_or_zero_portfolio(sample_portfolio_returns):
    """Verify safe zero-handling for empty portfolio."""
    engine = PortfolioVaREngine()
    res = engine.calculate_portfolio_var_cvar({}, sample_portfolio_returns)
    assert res["total_exposure_usd"] == 0.0
    assert res["historical_var_95_usd"] == 0.0
