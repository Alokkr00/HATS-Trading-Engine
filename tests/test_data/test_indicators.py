"""Unit tests for technical indicators calculation wrapper."""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
import pytest

from src.indicators import add_indicators, add_standard_indicators


# ---------------------------------------------------------------------------
# Helper: Generate synthetic test DataFrame
# ---------------------------------------------------------------------------
def generate_synthetic_ohlcv(
    start_date: str = "2026-01-01",
    periods: int = 250,
    tz: str | None = None,
) -> pd.DataFrame:
    """Helper to generate a mock OHLCV DataFrame with a business day index."""
    idx = pd.date_range(start=start_date, periods=periods, freq="B", tz=tz)

    np.random.seed(42)
    # Generate a random walk for close prices
    close = 100.0 + np.cumsum(np.random.normal(0, 1.0, periods))
    open_val = close + np.random.normal(0, 0.5, periods)
    high = np.maximum(open_val, close) + np.abs(np.random.normal(0, 0.5, periods))
    low = np.minimum(open_val, close) - np.abs(np.random.normal(0, 0.5, periods))
    volume = np.random.randint(1000, 100000, size=periods).astype(np.int64)

    df = pd.DataFrame(
        {
            "open": open_val,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )
    df.index.name = "date"
    return df


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_add_standard_indicators_columns() -> None:
    """Verify that calling add_standard_indicators appends correct columns."""
    df = generate_synthetic_ohlcv(periods=250)
    result = add_standard_indicators(df)

    expected_cols = [
        "sma_50",
        "sma_200",
        "ema_10",
        "ema_20",
        "ema_30",
        "ema_50",
        "rsi_14",
        "macd_12_26",
        "macd_signal_9",
        "macd_hist_9",
        "bb_lower_20_2",
        "bb_middle_20_2",
        "bb_upper_20_2",
        "bb_width_20_2",
        "bb_percent_20_2",
        "atr_14",
    ]

    # Verify all expected columns are present
    for col in expected_cols:
        assert col in result.columns

    # Verify that the values in the computed columns are numeric (float)
    for col in expected_cols:
        assert pd.api.types.is_numeric_dtype(result[col])
        # Verify that we have some valid non-null values (except during the initial lookback window)
        assert result[col].notna().sum() > 0


def test_index_and_timezone_preserved() -> None:
    """Verify that timezone and index are preserved exactly."""
    # Test with timezone-aware index
    df_tz = generate_synthetic_ohlcv(periods=50, tz="America/New_York")
    result_tz = add_standard_indicators(df_tz)

    assert result_tz.index.tz is not None
    assert str(result_tz.index.tz) == "America/New_York"
    assert (result_tz.index == df_tz.index).all()

    # Test with timezone-naive index
    df_naive = generate_synthetic_ohlcv(periods=50, tz=None)
    result_naive = add_standard_indicators(df_naive)

    assert result_naive.index.tz is None
    assert (result_naive.index == df_naive.index).all()


def test_short_lookback_warnings(caplog: pytest.LogCaptureFixture) -> None:
    """Verify that a warning is logged when data is shorter than lookback periods."""
    # Create a very short dataframe of 50 periods (which is < 200 required for SMA 200)
    df = generate_synthetic_ohlcv(periods=50)

    with caplog.at_level(logging.WARNING):
        add_standard_indicators(df)

    # Check for expected warning about SMA 200 lookback
    assert any(
        "less than the required lookback 200 for SMA" in record.message
        for record in caplog.records
    )


def test_column_collision_handling(caplog: pytest.LogCaptureFixture) -> None:
    """Verify column collision warning logs and protection against overwriting."""
    df = generate_synthetic_ohlcv(periods=250)

    # Calculate indicators once
    result1 = add_standard_indicators(df)

    # Mutate a column to detect if it is overwritten
    dummy_value = 12345.6
    result1["sma_50"] = dummy_value

    # Call with overwrite=False (default)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        result2 = add_standard_indicators(result1, overwrite=False)

    # Column should NOT be overwritten, value remains the dummy value
    assert (result2["sma_50"] == dummy_value).all()
    assert any(
        "already exists in DataFrame and overwrite=False" in record.message
        for record in caplog.records
    )

    # Call with overwrite=True
    result3 = add_standard_indicators(result1, overwrite=True)
    # Column should be overwritten and should NOT be the dummy value anymore
    assert not (result3["sma_50"] == dummy_value).all()


def test_empty_dataframe(caplog: pytest.LogCaptureFixture) -> None:
    """Verify handling of empty DataFrame."""
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    with caplog.at_level(logging.WARNING):
        result = add_standard_indicators(df)

    assert result.empty
    assert any(
        "Empty DataFrame passed" in record.message
        for record in caplog.records
    )


def test_missing_ohlcv_columns_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Verify warning is logged when standard OHLCV columns are missing."""
    # Dataframe missing high, low, volume
    df = pd.DataFrame({"open": [10.0, 11.0], "close": [10.5, 11.5]})

    with caplog.at_level(logging.WARNING):
        add_standard_indicators(df)

    assert any(
        "missing standard OHLCV columns" in record.message
        for record in caplog.records
    )
