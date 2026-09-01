"""Unit tests for Institutional Intraday Strategies (Opening Range Breakout & Intraday VWAP)."""

import numpy as np
import pandas as pd
import pytest

from src.strategy.opening_range_breakout import OpeningRangeBreakoutStrategy
from src.strategy.vwap_reversion import IntradayVWAPStrategy
from src.backtest.engine import BacktestEngine
from src.backtest.cost import CostModel


@pytest.fixture
def intraday_15m_df():
    """Create 5 days of 15-minute intraday bars with realistic session ranges."""
    np.random.seed(42)
    # 5 days * 26 bars/day = 130 bars
    dates = []
    base_dates = pd.date_range("2024-01-08", periods=5, freq="B")
    for b_date in base_dates:
        session_bars = pd.date_range(
            start=b_date.replace(hour=9, minute=30),
            end=b_date.replace(hour=15, minute=45),
            freq="15min",
            tz="America/New_York",
        )
        dates.extend(session_bars)

    n_bars = len(dates)
    t = np.linspace(0, 10, n_bars)
    trend = 100.0 + 5.0 * t
    cycle = 3.0 * np.sin(t * 4)
    noise = np.random.normal(0, 0.4, n_bars)
    close = trend + cycle + noise

    high = close + np.random.uniform(0.2, 0.8, n_bars)
    low = close - np.random.uniform(0.2, 0.8, n_bars)
    open_p = low + np.random.uniform(0.1, 0.9, n_bars) * (high - low)
    volume = np.random.uniform(50000, 500000, n_bars)

    df = pd.DataFrame(
        {"open": open_p, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )
    df.attrs["symbol"] = "SPY"
    return df


def test_opening_range_breakout_strategy(intraday_15m_df):
    """Verify ORB indicator calculations and signal triggers."""
    strat = OpeningRangeBreakoutStrategy(name="ORB_Test", config={"check_look_ahead": False})
    res_df = strat.generate_signals(intraday_15m_df)

    assert "orb_high" in res_df.columns
    assert "orb_low" in res_df.columns
    assert "orb_mid" in res_df.columns
    assert "signal" in res_df.columns

    # Stop loss calculation
    stop = strat.get_initial_stop_price(res_df, 10, res_df["close"].iloc[10])
    assert stop > 0.0
    assert stop < res_df["close"].iloc[10]

    # Backtest simulation
    engine = BacktestEngine(strategy=strat, capital=100000.0, cost_model=CostModel(spread_bps=1.5, slippage_bps=2.5))
    results = engine.run(intraday_15m_df)
    assert "metrics" in results


def test_intraday_vwap_strategy(intraday_15m_df):
    """Verify session-anchored VWAP and volatility band mean reversion."""
    strat = IntradayVWAPStrategy(name="VWAP_Test", config={"check_look_ahead": False})
    res_df = strat.generate_signals(intraday_15m_df)

    assert "vwap" in res_df.columns
    assert "vwap_upper" in res_df.columns
    assert "vwap_lower" in res_df.columns
    assert "rsi_14" in res_df.columns
    assert "signal" in res_df.columns

    # Stop loss calculation
    stop = strat.get_initial_stop_price(res_df, 10, res_df["close"].iloc[10])
    assert stop > 0.0
    assert stop < res_df["close"].iloc[10]

    # Backtest simulation
    engine = BacktestEngine(strategy=strat, capital=100000.0, cost_model=CostModel(spread_bps=1.5, slippage_bps=2.5))
    results = engine.run(intraday_15m_df)
    assert "metrics" in results
