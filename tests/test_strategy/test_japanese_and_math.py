"""Unit tests for Heikin-Ashi smoothing, Kalman Filter, Hurst Exponent, and Pivot Points."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.smoothing import calculate_heikin_ashi, apply_kalman_filter
from src.strategy.indicators_math import calculate_hurst_exponent, calculate_vwap, add_pivot_points
from src.strategy.strategies import IchimokuCloudStrategy, PivotPointReversionStrategy


def test_heikin_ashi_calculation() -> None:
    """Verify that Heikin-Ashi candles are computed correctly and have correct OHLC values."""
    df = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0],
            "high": [12.0, 13.0, 14.0],
            "low": [9.0, 10.0, 11.0],
            "close": [11.0, 12.0, 13.0],
            "volume": [100.0, 150.0, 200.0]
        }
    )
    ha_df = calculate_heikin_ashi(df)
    
    # 1. Close check: (10 + 12 + 9 + 11) / 4 = 10.5
    assert ha_df["close"].iloc[0] == 10.5
    
    # 2. Open check: (open[0] + close[0]) / 2 = (10.0 + 11.0) / 2 = 10.5
    assert ha_df["open"].iloc[0] == 10.5
    
    # Second row open: (ha_open[0] + ha_close[0]) / 2 = (10.5 + 10.5) / 2 = 10.5
    assert ha_df["open"].iloc[1] == 10.5


def test_kalman_filter_smoothing() -> None:
    """Verify that Kalman filter outputs a series of the same length and index."""
    series = pd.Series([10.0, 10.2, 10.1, 10.5, 11.0], index=pd.date_range("2023-01-01", periods=5))
    smoothed = apply_kalman_filter(series)
    
    assert len(smoothed) == len(series)
    assert (smoothed.index == series.index).all()
    # The first element must match the original price (initial state)
    assert smoothed.iloc[0] == series.iloc[0]


def test_hurst_exponent() -> None:
    """Verify that the Hurst exponent calculation returns a value between 0.0 and 1.0."""
    # Create random walk series (Hurst should be near 0.5)
    np.random.seed(42)
    random_walk = np.cumsum(np.random.normal(0, 1, 100)) + 100.0
    series = pd.Series(random_walk)
    
    h = calculate_hurst_exponent(series)
    assert 0.0 <= h <= 1.0


def test_pivot_points() -> None:
    """Verify standard pivot points calculation logic and look-ahead safety."""
    df = pd.DataFrame(
        {
            "high": [100.0, 110.0],
            "low": [90.0, 95.0],
            "close": [95.0, 105.0]
        }
    )
    df_pivot = add_pivot_points(df)
    
    # Pivot for the second bar should be based on the first bar's high, low, close:
    # PP = (100 + 90 + 95) / 3 = 95.0
    # R1 = 2 * 95 - 90 = 100.0
    # S1 = 2 * 95 - 100 = 90.0
    assert df_pivot["pivot"].iloc[1] == 95.0
    assert df_pivot["r1"].iloc[1] == 100.0
    assert df_pivot["s1"].iloc[1] == 90.0
