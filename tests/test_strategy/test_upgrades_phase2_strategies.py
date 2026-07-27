"""Unit tests for Phase 2 H.A.T.S Strategy Upgrades (Z-Score & Linear Regression Channels)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.indicators_math import calculate_linear_regression_bands, calculate_rolling_beta
from src.strategy.strategies import (
    ZScoreMeanReversionStrategy,
    LinearRegressionChannelStrategy,
    PairsTradingStrategy,
)


@pytest.fixture
def dummy_ohlcv() -> pd.DataFrame:
    """Create a dummy 100-day timezone-aware OHLCV DataFrame for testing."""
    dates = pd.date_range("2026-01-01", periods=100, freq="D", tz="UTC")
    
    # Generate structured price waves so indicators show variance
    t = np.linspace(0, 4 * np.pi, 100)
    prices = 100.0 + 10.0 * np.sin(t)
    
    df = pd.DataFrame({
        "open": prices - np.random.uniform(0.5, 1.5, 100),
        "high": prices + np.random.uniform(1.0, 2.0, 100),
        "low": prices - np.random.uniform(1.0, 2.0, 100),
        "close": prices,
        "volume": np.random.uniform(10000, 50000, 100),
    }, index=dates)
    return df


def test_linear_regression_bands_math():
    """Verify that calculate_linear_regression_bands calculates mid, upper, and lower bands correctly."""
    series = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    # Exact linear slope = 1.0, intercept at index 4 prediction = 14.0. Standard error = 0.0.
    mid, upper, lower = calculate_linear_regression_bands(series, period=5, num_std=2.0)
    
    assert pytest.approx(mid.iloc[4]) == 14.0
    assert pytest.approx(upper.iloc[4]) == 14.0
    assert pytest.approx(lower.iloc[4]) == 14.0


def test_zscore_mean_reversion_strategy(dummy_ohlcv):
    """Test ZScoreMeanReversionStrategy signal generation, initial stop, and ADX filter neutralization."""
    strategy = ZScoreMeanReversionStrategy(name="TestZScore", config={"use_adx_filter": False})
    res_df = strategy.generate_signals(dummy_ohlcv)
    
    assert "rolling_mean" in res_df.columns
    assert "rolling_std" in res_df.columns
    assert "zscore" in res_df.columns
    assert "signal" in res_df.columns
    assert set(res_df["signal"].unique()).issubset({-1, 0, 1})
    
    # Test initial stop loss (1.5x ATR)
    idx = 50
    entry_price = float(res_df["close"].iloc[idx])
    stop = strategy.get_initial_stop_price(res_df, idx, entry_price)
    atr_val = float(res_df["atr_14"].iloc[idx])
    assert stop == entry_price - 1.5 * atr_val


def test_linear_regression_channel_strategy(dummy_ohlcv):
    """Test LinearRegressionChannelStrategy signal generation, bands, and stop calculation."""
    strategy = LinearRegressionChannelStrategy(name="TestLRChannel", config={"use_adx_filter": False, "period": 20})
    res_df = strategy.generate_signals(dummy_ohlcv)
    
    assert "lr_mid" in res_df.columns
    assert "lr_upper" in res_df.columns
    assert "lr_lower" in res_df.columns
    assert "signal" in res_df.columns
    assert set(res_df["signal"].unique()).issubset({-1, 0, 1})
    
    # Test initial stop loss (2x ATR)
    idx = 50
    entry_price = float(res_df["close"].iloc[idx])
    stop = strategy.get_initial_stop_price(res_df, idx, entry_price)
    atr_val = float(res_df["atr_14"].iloc[idx])
    assert stop == entry_price - 2.0 * atr_val


def test_phase2_strategies_look_ahead_bias(dummy_ohlcv):
    """Verify that all Phase 2 strategies pass look-ahead bias validation checks."""
    for strat_cls, name in [
        (ZScoreMeanReversionStrategy, "ZScore"),
        (LinearRegressionChannelStrategy, "LRChannel"),
    ]:
        strategy = strat_cls(name=name, config={"use_adx_filter": False, "check_look_ahead": True})
        res_df = strategy.generate_signals(dummy_ohlcv)
        assert not res_df.empty


def test_pairs_trading_beta_math():
    """Verify that calculate_rolling_beta outputs the correct slope beta on perfect correlation."""
    series_x = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    series_y = 1.5 * series_x  # perfect linear correlation with beta = 1.5
    
    beta = calculate_rolling_beta(series_y, series_x, period=5)
    assert pytest.approx(beta.iloc[4]) == 1.5


from unittest.mock import patch

@patch("src.data.store.DataStore.load")
def test_pairs_trading_strategy_signals(mock_load, dummy_ohlcv):
    """Verify that PairsTradingStrategy generates opposite leg signals for pairs."""
    # 1. Setup mock partner DataFrame
    partner_df = dummy_ohlcv.copy()
    partner_df["close"] = partner_df["close"] * 0.5  # perfectly correlated with half price
    partner_df.attrs["symbol"] = "BAC"
    
    mock_load.return_value = partner_df
    
    # 2. Setup strategy for JPM (Asset A in the JPM-BAC pair)
    dummy_ohlcv.attrs["symbol"] = "JPM"
    strategy_jpm = PairsTradingStrategy(
        name="PairsJPM",
        config={"pairs": [("JPM", "BAC")], "lookback": 20, "use_adx_filter": False}
    )
    
    res_jpm = strategy_jpm.generate_signals(dummy_ohlcv)
    assert "pairs_zscore" in res_jpm.columns
    assert "is_asset_a" in res_jpm.columns
    assert float(res_jpm["is_asset_a"].iloc[0]) == 1.0
    
    # 3. Setup strategy for BAC (Asset B in the JPM-BAC pair)
    # Re-copy dummy_ohlcv as BAC to test Leg B evaluation
    bac_df = dummy_ohlcv.copy()
    bac_df.attrs["symbol"] = "BAC"
    
    # Mock load JPM for B's partner lookup
    mock_load.return_value = dummy_ohlcv
    
    strategy_bac = PairsTradingStrategy(
        name="PairsBAC",
        config={"pairs": [("JPM", "BAC")], "lookback": 20, "use_adx_filter": False}
    )
    
    res_bac = strategy_bac.generate_signals(bac_df)
    assert float(res_bac["is_asset_a"].iloc[0]) == 0.0
    
    # 4. Assert that signals generated for the two assets on the same day are opposite
    # Whenever Asset A gets a BUY (1) signal, Asset B must get a SELL (-1) signal
    signals_jpm = res_jpm["signal"].values
    signals_bac = res_bac["signal"].values
    
    for i in range(len(signals_jpm)):
        if signals_jpm[i] != 0:
            assert signals_bac[i] == -signals_jpm[i]

