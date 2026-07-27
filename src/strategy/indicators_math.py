"""Advanced mathematical and statistical indicators for H.A.T.S."""

from __future__ import annotations

import pandas as pd
import numpy as np


def calculate_hurst_exponent(series: pd.Series, max_lags: int = 20) -> float:
    """
    Calculates the Hurst Exponent of a price series using simplified R/S regression.
    
    Interpretations:
        H < 0.5: Mean-reverting (anti-persistent).
        H > 0.5: Trending (persistent).
        H = 0.5: Random walk (Geometric Brownian Motion).
        
    Args:
        series: Price series (e.g. close price).
        max_lags: Number of lags to regression test.
        
    Returns:
        Hurst exponent value (float).
    """
    n = len(series)
    if n < max_lags * 2:
        return 0.5  # Fallback to random walk if not enough history
        
    try:
        # Convert series to logs of price differences
        log_prices = np.log(series.values)
        lags = range(2, min(max_lags, n // 2))
        
        # Calculate standard deviations of differences for each lag
        tau = []
        for lag in lags:
            diffs = log_prices[lag:] - log_prices[:-lag]
            tau.append(np.std(diffs))
            
        # Fit log(lags) vs log(tau) using simple linear regression
        reg = np.polyfit(np.log(lags), np.log(tau), 1)
        # The slope of the line is the Hurst exponent estimate
        h = float(reg[0])
        # Bound between 0.0 and 1.0
        return max(0.0, min(1.0, h))
    except Exception:
        return 0.5


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Calculates Volume Weighted Average Price (VWAP).
    
    Args:
        df: DataFrame containing 'high', 'low', 'close', and 'volume' columns.
        
    Returns:
        Series containing the cumulative VWAP.
    """
    # Verify required columns
    required = ["high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            return pd.Series(df["close"], index=df.index)
            
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].fillna(0.0)
    
    # Avoid division by zero
    cum_vol = vol.cumsum()
    cum_pv = (typical_price * vol).cumsum()
    
    vwap = cum_pv / np.where(cum_vol > 0, cum_vol, 1.0)
    return pd.Series(vwap, index=df.index)


def add_pivot_points(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds support and resistance Pivot Points to the DataFrame using the previous bar values.
    This guarantees zero look-ahead bias.
    
    Args:
        df: DataFrame containing 'high', 'low', 'close' columns.
        
    Returns:
        The DataFrame enriched with 'pivot', 'r1', 's1', 'r2', 's2' columns.
    """
    df = df.copy()
    
    # Shift to get previous bar OHLC values
    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)
    prev_close = df["close"].shift(1)
    
    # Calculate Pivot (PP)
    df["pivot"] = (prev_high + prev_low + prev_close) / 3.0
    
    # Calculate Resistance/Support Level 1
    df["r1"] = 2.0 * df["pivot"] - prev_low
    df["s1"] = 2.0 * df["pivot"] - prev_high
    
    # Calculate Resistance/Support Level 2
    df["r2"] = df["pivot"] + (prev_high - prev_low)
    df["s2"] = df["pivot"] - (prev_high - prev_low)
    
    # Fill first row NaNs with close value for safety
    df["pivot"] = df["pivot"].bfill().ffill()
    df["r1"] = df["r1"].bfill().ffill()
    df["s1"] = df["s1"].bfill().ffill()
    df["r2"] = df["r2"].bfill().ffill()
    df["s2"] = df["s2"].bfill().ffill()
    
    return df


def calculate_linear_regression_bands(series: pd.Series, period: int, num_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculates rolling linear regression line middle, upper, and lower bands.
    
    For each index i, we fit a linear regression on the values from index i - period + 1 to i.
    The middle line is the regression prediction for today (x = period - 1).
    The upper and lower bands are middle +/- num_std * standard error of the fit.
    
    Args:
        series: Closing price series.
        period: Number of periods for regression lookback.
        num_std: Multiplier for standard error bands.
        
    Returns:
        tuple containing (mid_band, upper_band, lower_band) as pandas Series.
    """
    n = len(series)
    if n < period:
        # Fallback to defaults
        return series.copy(), series.copy(), series.copy()
        
    # Pre-compute x values: [0, 1, 2, ..., period - 1]
    x = np.arange(period)
    x_mean = x.mean()
    x_dev = x - x_mean
    sum_x_dev_sq = np.sum(x_dev ** 2)
    
    y_vals = series.values
    
    # Pre-allocate output arrays
    mid_arr = np.full(n, np.nan)
    upper_arr = np.full(n, np.nan)
    lower_arr = np.full(n, np.nan)
    
    for i in range(period - 1, n):
        y = y_vals[i - period + 1 : i + 1]
        
        # Linear regression calculation: slope and intercept
        y_mean = y.mean()
        slope = np.sum(x_dev * (y - y_mean)) / sum_x_dev_sq
        intercept = y_mean - slope * x_mean
        
        # Prediction at current point (x = period - 1)
        pred = intercept + slope * (period - 1)
        
        # Standard error of the estimate
        residuals = y - (intercept + slope * x)
        std_err = np.sqrt(np.sum(residuals ** 2) / max(1, period - 2))
        
        mid_arr[i] = pred
        upper_arr[i] = pred + num_std * std_err
        lower_arr[i] = pred - num_std * std_err
        
    mid = pd.Series(mid_arr, index=series.index).bfill().ffill()
    upper = pd.Series(upper_arr, index=series.index).bfill().ffill()
    lower = pd.Series(lower_arr, index=series.index).bfill().ffill()
    
    return mid, upper, lower


def calculate_rolling_beta(series_a: pd.Series, series_b: pd.Series, period: int = 60) -> pd.Series:
    """Calculates a rolling OLS hedge ratio (slope beta) of series_a on series_b.
    
    Fits the model: series_a = beta * series_b (without intercept).
    """
    n = len(series_a)
    betas = np.full(n, np.nan)
    
    if n < period:
        # Fallback to simple price ratio
        ratio = series_a / np.where(series_b > 0, series_b, 1e-6)
        return ratio.bfill().ffill()
        
    y_vals = series_a.values
    x_vals = series_b.values
    
    for i in range(period - 1, n):
        y = y_vals[i - period + 1 : i + 1]
        x = x_vals[i - period + 1 : i + 1]
        
        sum_xx = np.sum(x ** 2)
        if sum_xx > 0:
            betas[i] = np.sum(x * y) / sum_xx
            
    return pd.Series(betas, index=series_a.index).bfill().ffill()
