"""Data smoothing modules including Heikin-Ashi and Kalman Filters."""

from __future__ import annotations

import pandas as pd
import numpy as np


def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates Heikin-Ashi smoothed candles from a standard OHLC DataFrame.
    
    Args:
        df: DataFrame containing 'open', 'high', 'low', 'close' columns.
        
    Returns:
        A new DataFrame with 'open', 'high', 'low', 'close' columns smoothed.
    """
    ha_df = pd.DataFrame(index=df.index)
    
    # Calculate Close first: (Open + High + Low + Close) / 4
    ha_df["close"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    
    # Calculate Open iteratively: (Open_prev + Close_prev) / 2
    ha_open = np.zeros(len(df))
    # Seed first value
    ha_open[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0
    
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i-1] + ha_df["close"].iloc[i-1]) / 2.0
        
    ha_df["open"] = ha_open
    
    # High = max(High, Open, Close)
    ha_df["high"] = np.maximum(df["high"].values, np.maximum(ha_df["open"].values, ha_df["close"].values))
    
    # Low = min(Low, Open, Close)
    ha_df["low"] = np.minimum(df["low"].values, np.minimum(ha_df["open"].values, ha_df["close"].values))
    
    # Copy volume if present
    if "volume" in df.columns:
        ha_df["volume"] = df["volume"]
        
    return ha_df


def apply_kalman_filter(series: pd.Series, q: float = 1e-4, r: float = 1e-2) -> pd.Series:
    """
    Applies a single-state Kalman filter to smooth a price series without lag.
    
    Args:
        series: Price series (e.g. close price).
        q: Process noise covariance (smaller = smoother, larger = follows price closer).
        r: Measurement noise covariance (larger = filters more noise).
        
    Returns:
        A smoothed price series of the same length and index.
    """
    n = len(series)
    if n == 0:
        return series
        
    values = series.values
    smoothed = np.zeros(n)
    
    # Initialize state
    x = values[0]
    p = 1.0  # estimation error covariance
    
    smoothed[0] = x
    
    for i in range(1, n):
        # Predict
        x_pred = x
        p_pred = p + q
        
        # Update
        k = p_pred / (p_pred + r)
        x = x_pred + k * (values[i] - x_pred)
        p = (1.0 - k) * p_pred
        
        smoothed[i] = x
        
    return pd.Series(smoothed, index=series.index)
