"""Unit tests for Phase 1 H.A.T.S Strategy and Indicator Upgrades."""

from __future__ import annotations

import datetime as dt
import numpy as np
import pandas as pd
import pytest

from src.indicators.ta_wrapper import add_indicators
from src.strategy.strategies import (
    MACDHistogramStrategy,
    DonchianChannelBreakoutStrategy,
    StochasticOscillatorStrategy,
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


def test_new_indicators_computation(dummy_ohlcv):
    """Verify that new technical indicators (ADX, Stochastic, CCI, OBV, ROC, Williams %R, MFI) compute without errors."""
    configs = [
        {"kind": "adx", "length": 14},
        {"kind": "stoch", "k": 14, "d": 3},
        {"kind": "cci", "length": 14},
        {"kind": "obv"},
        {"kind": "roc", "length": 10},
        {"kind": "williams_r", "length": 14},
        {"kind": "mfi", "length": 14},
    ]
    df_res = add_indicators(dummy_ohlcv, configs, overwrite=True)

    assert "adx_14" in df_res.columns
    assert "dmp_14" in df_res.columns
    assert "dmn_14" in df_res.columns
    assert "stoch_k" in df_res.columns
    assert "stoch_d" in df_res.columns
    assert "cci_14" in df_res.columns
    assert "obv" in df_res.columns
    assert "roc_10" in df_res.columns
    assert "williams_r_14" in df_res.columns
    assert "mfi_14" in df_res.columns

    # Check that they aren't all NaNs (except for the initial lookback period)
    assert not df_res["adx_14"].iloc[30:].isna().all()
    assert not df_res["stoch_k"].iloc[30:].isna().all()
    assert not df_res["cci_14"].iloc[30:].isna().all()
    assert not df_res["obv"].isna().all()
    assert not df_res["roc_10"].iloc[20:].isna().all()
    assert not df_res["williams_r_14"].iloc[20:].isna().all()
    assert not df_res["mfi_14"].iloc[20:].isna().all()


def test_macd_histogram_strategy(dummy_ohlcv):
    """Test MACDHistogramStrategy rule generation and initial stop calculation."""
    strategy = MACDHistogramStrategy(name="TestMACDHist", config={"use_adx_filter": False})
    res_df = strategy.generate_signals(dummy_ohlcv)

    assert "signal" in res_df.columns
    assert "sig_macd_hist" in res_df.columns
    assert set(res_df["signal"].unique()).issubset({-1, 0, 1})

    # Test initial stop loss
    idx = 50
    entry_price = float(res_df["close"].iloc[idx])
    stop = strategy.get_initial_stop_price(res_df, idx, entry_price)
    atr_val = float(res_df["atr_14"].iloc[idx])
    assert stop == entry_price - 2.0 * atr_val


def test_donchian_breakout_strategy(dummy_ohlcv):
    """Test DonchianChannelBreakoutStrategy rule generation and stop calculation."""
    strategy = DonchianChannelBreakoutStrategy(name="TestDonchian", config={"use_adx_filter": False, "period": 20})
    res_df = strategy.generate_signals(dummy_ohlcv)

    assert "dc_upper" in res_df.columns
    assert "dc_lower" in res_df.columns
    assert "signal" in res_df.columns
    assert "sig_donchian_breakout" in res_df.columns
    assert set(res_df["signal"].unique()).issubset({-1, 0, 1})

    # Test initial stop loss
    idx = 50
    entry_price = float(res_df["close"].iloc[idx])
    stop = strategy.get_initial_stop_price(res_df, idx, entry_price)
    atr_val = float(res_df["atr_14"].iloc[idx])
    assert stop == entry_price - 2.0 * atr_val


def test_stochastic_oscillator_strategy(dummy_ohlcv):
    """Test StochasticOscillatorStrategy rule generation and stop calculation."""
    strategy = StochasticOscillatorStrategy(name="TestStoch", config={"use_adx_filter": False})
    res_df = strategy.generate_signals(dummy_ohlcv)

    assert "stoch_k" in res_df.columns
    assert "stoch_d" in res_df.columns
    assert "signal" in res_df.columns
    assert "sig_stochastic_oscillator" in res_df.columns
    assert set(res_df["signal"].unique()).issubset({-1, 0, 1})

    # Test initial stop loss
    idx = 50
    entry_price = float(res_df["close"].iloc[idx])
    stop = strategy.get_initial_stop_price(res_df, idx, entry_price)
    atr_val = float(res_df["atr_14"].iloc[idx])
    assert stop == entry_price - 1.5 * atr_val


def test_adx_trend_filter_neutralization(dummy_ohlcv):
    """Verify that the ADX filter correctly forces strategy signals to 0 (neutral) when ADX < threshold."""
    # First, run the strategy without the ADX filter and confirm it generates signals
    strategy_no_filter = MACDHistogramStrategy(name="TestNoFilter", config={"use_adx_filter": False})
    res_no_filter = strategy_no_filter.generate_signals(dummy_ohlcv)
    assert not (res_no_filter["signal"] == 0).all(), "Strategy should generate signals on the wave data."

    # Next, run with the ADX filter enabled and a very high threshold (1000.0)
    # This guarantees that the computed ADX values (which are < 100) are under the threshold
    strategy_filter = MACDHistogramStrategy(
        name="TestWithFilter", 
        config={"use_adx_filter": True, "adx_filter_threshold": 1000.0}
    )
    res_filter = strategy_filter.generate_signals(dummy_ohlcv)

    # All signals must be neutralized to 0 because ADX is always < 1000
    assert (res_filter["signal"] == 0).all(), "All signals should be neutralized to 0."
    assert (res_filter["sig_macd_hist"] == 0).all(), "All individual rule signals should be neutralized to 0."


def test_new_strategies_look_ahead_bias(dummy_ohlcv):
    """Verify that all three new strategies pass look-ahead bias validation checks."""
    for strat_cls, name in [
        (MACDHistogramStrategy, "MACDHist"),
        (DonchianChannelBreakoutStrategy, "Donchian"),
        (StochasticOscillatorStrategy, "Stoch"),
    ]:
        strategy = strat_cls(name=name, config={"use_adx_filter": False, "check_look_ahead": True})
        # If look-ahead bias was present, this method would raise ValueError
        res_df = strategy.generate_signals(dummy_ohlcv)
        assert not res_df.empty
