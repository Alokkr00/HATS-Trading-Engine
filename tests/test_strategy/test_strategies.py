"""Unit tests for the Sprint 3 strategy implementations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.strategies import (
    MACrossoverStrategy,
    RSIMeanReversionStrategy,
    BollingerSqueezeStrategy,
)


def create_base_df(n_bars: int, initial_price: float = 100.0) -> pd.DataFrame:
    """Helper to create a base OHLCV DataFrame with timezone-aware index.

    Args:
        n_bars: Number of daily bars to generate.
        initial_price: Initial price for the close and other fields.

    Returns:
        A timezone-aware pandas DataFrame with standard OHLCV columns.
    """
    dates = pd.date_range("2020-01-01", periods=n_bars, freq="D", tz="America/New_York")
    df = pd.DataFrame(
        {
            "open": np.full(n_bars, initial_price),
            "high": np.full(n_bars, initial_price + 0.5),
            "low": np.full(n_bars, initial_price - 0.5),
            "close": np.full(n_bars, initial_price),
            "volume": np.full(n_bars, 1000.0),
        },
        index=dates,
    )
    return df


def test_ma_crossover_signals() -> None:
    """Verify signal generation logic for MACrossoverStrategy."""
    # 100 bars is enough for fast=5, slow=20
    df = create_base_df(100, 100.0)

    # Create a Golden Cross:
    # Bars 31 to 50: price increases to 120. (fast SMA will rise above slow SMA)
    for i in range(30, 50):
        price = 100.0 + (i - 29) * 1.5
        df.loc[df.index[i], ["open", "high", "low", "close"]] = price

    # Bars 51 to 80: price decreases to 75. (fast SMA will cross below slow SMA)
    for i in range(50, 80):
        price = 130.0 - (i - 49) * 2.0
        df.loc[df.index[i], ["open", "high", "low", "close"]] = price

    strategy = MACrossoverStrategy("MA_Test", config={"fast_period": 5, "slow_period": 20, "check_look_ahead": False})
    res = strategy.generate_signals(df)

    # Verify indicators exist
    assert "sma_5" in res.columns
    assert "sma_20" in res.columns
    assert "atr_14" in res.columns
    assert "sig_macrossover" in res.columns
    assert "signal" in res.columns

    # Verify we got a buy signal (1) and later a sell/exit signal (-1)
    signals = res["sig_macrossover"].values
    assert 1 in signals
    assert -1 in signals


def test_ma_crossover_hard_stop() -> None:
    """Verify that MACrossoverStrategy exits correctly on a hard stop loss."""
    # Generate data that triggers a Golden Cross
    df = create_base_df(100, 100.0)
    for i in range(15, 45):
        df.loc[df.index[i], ["open", "high", "low", "close"]] = 100.0 + (i - 14) * 2.0

    strategy = MACrossoverStrategy("MA_Test", config={"fast_period": 5, "slow_period": 10, "check_look_ahead": False})
    res_initial = strategy.generate_signals(df)

    # Find the first buy signal index
    buy_indices = res_initial.index[res_initial["sig_macrossover"] == 1]
    assert len(buy_indices) > 0
    buy_idx = res_initial.index.get_loc(buy_indices[0])

    # Now, create a new DataFrame where price drops 6% on the bar after buy_idx
    df_stop = df.copy()
    entry_price = df_stop["close"].iloc[buy_idx]
    stop_price = entry_price * 0.94  # 6% drop

    # We update the close price at buy_idx + 1 to stop_price, and subsequent bars as well
    for i in range(buy_idx + 1, len(df_stop)):
        df_stop.loc[df_stop.index[i], ["open", "high", "low", "close"]] = stop_price

    res_stop = strategy.generate_signals(df_stop)

    # Verify buy signal still generated at buy_idx
    assert res_stop["sig_macrossover"].iloc[buy_idx] == 1
    # Verify hard stop triggered on buy_idx + 1
    assert res_stop["sig_macrossover"].iloc[buy_idx + 1] == -1


def test_rsi_mean_reversion_signals() -> None:
    """Verify signal generation logic for RSIMeanReversionStrategy."""
    # 250 bars are needed to compute SMA(200) and have a clean signal
    df = create_base_df(250, 100.0)

    # Trend the price up from 100 to 540, so price is well above SMA(200)
    for i in range(220):
        df.loc[df.index[i], ["open", "high", "low", "close"]] = 100.0 + i * 2.0

    # Keep flat at 540 for 5 bars
    for i in range(220, 225):
        df.loc[df.index[i], ["open", "high", "low", "close"]] = 540.0

    # Sudden dip at bar 225 to trigger RSI < 30 (oversold) but remain above SMA(200)
    df.loc[df.index[225], ["open", "high", "low", "close"]] = 380.0

    # Immediate sharp recovery to trigger RSI > 50
    for i in range(226, 245):
        df.loc[df.index[i], ["open", "high", "low", "close"]] = 380.0 + (i - 225) * 15.0

    strategy = RSIMeanReversionStrategy(
        "RSI_Test",
        config={
            "rsi_period": 14,
            "oversold_threshold": 30,
            "overbought_threshold": 70,
            "check_look_ahead": False,
        },
    )
    res = strategy.generate_signals(df)

    assert "rsi_14" in res.columns
    assert "sma_200" in res.columns
    assert "sig_rsi_reversion" in res.columns

    # Verify buy and sell signals are generated
    signals = res["sig_rsi_reversion"].values
    assert 1 in signals
    assert -1 in signals


def test_rsi_time_stop() -> None:
    """Verify that RSIMeanReversionStrategy exits correctly on a time stop (10 days)."""
    df = create_base_df(250, 100.0)
    # Trend the price up
    for i in range(220):
        df.loc[df.index[i], ["open", "high", "low", "close"]] = 100.0 + i * 2.0
    for i in range(220, 225):
        df.loc[df.index[i], ["open", "high", "low", "close"]] = 540.0

    # Trigger oversold entry
    df.loc[df.index[225], ["open", "high", "low", "close"]] = 380.0

    # Hold price flat so no RSI recovery exit is triggered. Time stop should trigger.
    for i in range(226, 245):
        df.loc[df.index[i], ["open", "high", "low", "close"]] = 380.0

    strategy = RSIMeanReversionStrategy("RSI_Test", config={"rsi_period": 14, "oversold_threshold": 30, "check_look_ahead": False})
    res = strategy.generate_signals(df)

    buy_indices = res.index[res["sig_rsi_reversion"] == 1]
    assert len(buy_indices) > 0
    buy_idx = res.index.get_loc(buy_indices[0])

    # Time stop triggers if i - entry_idx > 10, i.e., at buy_idx + 11
    expected_sell_idx = buy_idx + 11
    assert res["sig_rsi_reversion"].iloc[expected_sell_idx] == -1


def test_bb_squeeze_signals() -> None:
    """Verify signal generation logic for BollingerSqueezeStrategy."""
    df = create_base_df(100, 100.0)

    # Let price be extremely flat to squeeze the Bollinger Bands
    # On bar 80, price breaks out on high volume
    df.loc[df.index[80], ["open", "high", "low", "close"]] = 106.0
    df.loc[df.index[80], "volume"] = 2000.0

    # On bar 81, price drops below the middle Bollinger Band (which is around 100.3)
    df.loc[df.index[81], ["open", "high", "low", "close"]] = 95.0

    strategy = BollingerSqueezeStrategy(
        "BB_Test",
        config={
            "bb_length": 10,
            "bb_std": 2.0,
            "squeeze_percentile": 30,
            "squeeze_lookback": 50,
            "check_look_ahead": False,
        },
    )
    res = strategy.generate_signals(df)

    assert "bb_width_10_2" in res.columns
    assert "bb_width_pct" in res.columns
    assert "volume_sma_20" in res.columns

    # Verify buy breakout signal at bar 80
    assert res["sig_bb_squeeze"].iloc[80] == 1
    # Verify exit signal at bar 81
    assert res["sig_bb_squeeze"].iloc[81] == -1


def test_strategies_look_ahead_validation() -> None:
    """Ensure strategies run with the look-ahead bias check enabled without failures."""
    # Create sufficient history for warm-ups (especially Bollinger squeeze)
    df = create_base_df(300, 100.0)

    # Introduce some price and volume variability so indicators are computed normally
    df["close"] = df["close"] + np.random.normal(0, 1, 300).cumsum()
    df["volume"] = df["volume"] + np.random.uniform(-100, 100, 300)

    # Instantiate strategies with default config (check_look_ahead=True)
    strategy_ma = MACrossoverStrategy("MA_Default")
    strategy_rsi = RSIMeanReversionStrategy("RSI_Default")
    strategy_bb = BollingerSqueezeStrategy("BB_Default")

    # These should generate signals and successfully pass the look-ahead checks
    res_ma = strategy_ma.generate_signals(df)
    res_rsi = strategy_rsi.generate_signals(df)
    res_bb = strategy_bb.generate_signals(df)

    assert "signal" in res_ma.columns
    assert "signal" in res_rsi.columns
    assert "signal" in res_bb.columns
