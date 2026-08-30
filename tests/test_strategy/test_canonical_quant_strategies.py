"""Unit tests for canonical quantitative strategies (Dual Momentum, TSMOM, Connors RSI)."""

import numpy as np
import pandas as pd
import pytest

from src.strategy.dual_momentum import DualMomentumStrategy
from src.strategy.time_series_momentum import VolatilityScaledTrendStrategy
from src.strategy.connors_rsi import ConnorsMeanReversionStrategy
from src.backtest.engine import BacktestEngine
from src.backtest.cost import CostModel


@pytest.fixture
def market_cycle_df():
    """Create 600 days of trending and mean-reverting price action with timezone index."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=600, freq="B", tz="America/New_York")
    
    # Uptrend followed by a consolidation and pullback
    t = np.linspace(0, 10, 600)
    trend = 50.0 + 10.0 * t
    cycle = 5.0 * np.sin(t * 3)
    noise = np.random.normal(0, 0.5, 600)
    close = trend + cycle + noise

    high = close + np.random.uniform(0.5, 1.5, 600)
    low = close - np.random.uniform(0.5, 1.5, 600)
    open_p = low + np.random.uniform(0.1, 0.9, 600) * (high - low)
    volume = np.random.uniform(1000000, 5000000, 600)

    df = pd.DataFrame(
        {"open": open_p, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )
    df.attrs["symbol"] = "SPY"
    return df


def test_volatility_scaled_trend_strategy(market_cycle_df):
    """Verify indicators and signal generation for TSMOM."""
    strat = VolatilityScaledTrendStrategy(name="TSMOM_Test", config={"check_look_ahead": False})
    res_df = strat.generate_signals(market_cycle_df)

    assert "sma_200" in res_df.columns
    assert "realized_ann_vol" in res_df.columns
    assert "vol_scalar" in res_df.columns
    assert "signal" in res_df.columns

    # Volatility scalar must be bounded between 0.2 and 1.5
    valid_scalars = res_df["vol_scalar"].dropna()
    assert (valid_scalars >= 0.2).all()
    assert (valid_scalars <= 1.5).all()


def test_dual_momentum_strategy(market_cycle_df):
    """Verify dual momentum absolute and relative trend rules."""
    strat = DualMomentumStrategy(name="DualMom_Test", config={"check_look_ahead": False})
    res_df = strat.generate_signals(market_cycle_df)

    assert "abs_mom_12m" in res_df.columns
    assert "trend_sma" in res_df.columns
    assert "composite_mom" in res_df.columns
    assert "signal" in res_df.columns

    # Backtest engine simulation should run smoothly
    engine = BacktestEngine(strategy=strat, capital=100000.0, cost_model=CostModel(spread_bps=1.5, slippage_bps=2.5))
    results = engine.run(market_cycle_df)
    assert "metrics" in results
    assert "equity_curve" in results


def test_connors_mean_reversion_strategy(market_cycle_df):
    """Verify Connors RSI-2 pullback strategy signal triggers."""
    strat = ConnorsMeanReversionStrategy(name="Connors_Test", config={"check_look_ahead": False})
    res_df = strat.generate_signals(market_cycle_df)

    assert "rsi_2" in res_df.columns
    assert "sma_200" in res_df.columns
    assert "sma_5" in res_df.columns
    assert "signal" in res_df.columns

    # Signal values must be strictly in {-1, 0, 1}
    assert set(res_df["signal"].unique()).issubset({-1, 0, 1})
