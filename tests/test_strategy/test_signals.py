"""Unit tests for the SignalGenerator class and trading signals generation layer."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from src.strategy.signals import SignalGenerator


# ---------------------------------------------------------------------------
# Mock Rule Functions
# ---------------------------------------------------------------------------
def rule_rsi(df: pd.DataFrame) -> pd.Series:
    """Mock RSI rule: BUY if RSI < 30, SELL if RSI > 70, else HOLD."""
    signals = pd.Series(0, index=df.index)
    if "rsi" in df.columns:
        signals[df["rsi"] < 30] = 1
        signals[df["rsi"] > 70] = -1
    return signals


def rule_ema_crossover(df: pd.DataFrame) -> pd.Series:
    """Mock EMA crossover rule: BUY if EMA_fast > EMA_slow, SELL if EMA_fast < EMA_slow, else HOLD."""
    signals = pd.Series(0, index=df.index)
    if "ema_fast" in df.columns and "ema_slow" in df.columns:
        signals[df["ema_fast"] > df["ema_slow"]] = 1
        signals[df["ema_fast"] < df["ema_slow"]] = -1
    return signals


def rule_look_ahead_shift(df: pd.DataFrame) -> pd.Series:
    """Uses a shift(-1) to look into the future."""
    signals = pd.Series(0, index=df.index)
    # Peek at future close price
    future_close = df["close"].shift(-1)
    signals[future_close > df["close"]] = 1
    return signals


def rule_look_ahead_global(df: pd.DataFrame) -> pd.Series:
    """Uses the maximum value of the entire series, which relies on the future."""
    signals = pd.Series(0, index=df.index)
    max_close = df["close"].max()
    signals[df["close"] == max_close] = 1
    return signals


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------
def test_rule_registration() -> None:
    """Test that rules are registered correctly."""
    sg = SignalGenerator()
    sg.add_rule("rsi", rule_rsi)
    sg.add_rule("ema", rule_ema_crossover)

    # Internal rules dict should have the keys
    assert "rsi" in sg._rules
    assert "ema" in sg._rules

    # Adding with empty name raises error
    with pytest.raises(ValueError, match="Rule name cannot be empty"):
        sg.add_rule("", rule_rsi)


def test_timezone_and_index_preservation() -> None:
    """Verify that the timezone and index are fully preserved in signal generation."""
    dates = pd.date_range(
        "2026-07-01 09:30:00", periods=10, freq="1min", tz="America/New_York"
    )
    df = pd.DataFrame(
        {
            "close": np.linspace(100, 110, 10),
            "rsi": [20, 25, 35, 40, 50, 60, 75, 80, 50, 45],
        },
        index=dates,
    )

    sg = SignalGenerator()
    sg.add_rule("rsi", rule_rsi)

    res = sg.generate(df, combine_mode="any")

    # Assert index and timezone are preserved
    assert res.index.equals(df.index)
    assert res.index.tz == df.index.tz
    assert res.index.tz == ZoneInfo("America/New_York")


def test_combine_mode_any() -> None:
    """Test the 'any' combine mode and conflict resolution strategies."""
    dates = pd.date_range("2026-07-01", periods=5)
    df = pd.DataFrame({"close": [10, 11, 12, 13, 14]}, index=dates)

    def r1(d: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=d.index)
        if len(d) > 0:
            s.iloc[0] = 1
        if len(d) > 1:
            s.iloc[1] = -1
        return s

    def r2(d: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=d.index)
        if len(d) > 1:
            s.iloc[1] = 1
        return s

    sg = SignalGenerator()
    sg.add_rule("rule1", r1)
    sg.add_rule("rule2", r2)

    # conflict_resolution = 'hold' (default)
    res_hold = sg.generate(df, combine_mode="any", conflict_resolution="hold")
    assert res_hold["signal"].tolist() == [1, 0, 0, 0, 0]

    # conflict_resolution = 'buy'
    res_buy = sg.generate(df, combine_mode="any", conflict_resolution="buy")
    assert res_buy["signal"].tolist() == [1, 1, 0, 0, 0]

    # conflict_resolution = 'sell'
    res_sell = sg.generate(df, combine_mode="any", conflict_resolution="sell")
    assert res_sell["signal"].tolist() == [1, -1, 0, 0, 0]


def test_combine_mode_all() -> None:
    """Test the 'all' combine mode requiring full agreement."""
    dates = pd.date_range("2026-07-01", periods=5)
    df = pd.DataFrame({"close": [10, 11, 12, 13, 14]}, index=dates)

    def r1(d: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=d.index)
        if len(d) > 0:
            s.iloc[0] = 1
        if len(d) > 1:
            s.iloc[1] = 1
        if len(d) > 3:
            s.iloc[3] = -1
        return s

    def r2(d: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=d.index)
        if len(d) > 0:
            s.iloc[0] = 1
        if len(d) > 1:
            s.iloc[1] = -1
        if len(d) > 3:
            s.iloc[3] = -1
        return s

    sg = SignalGenerator()
    sg.add_rule("rule1", r1)
    sg.add_rule("rule2", r2)

    res = sg.generate(df, combine_mode="all")
    assert res["signal"].tolist() == [1, 0, 0, -1, 0]


def test_combine_mode_majority() -> None:
    """Test the class-based 'majority' vote aggregation."""
    dates = pd.date_range("2026-07-01", periods=5)
    df = pd.DataFrame({"close": [10, 11, 12, 13, 14]}, index=dates)

    def r1(d: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=d.index)
        if len(d) > 0:
            s.iloc[0] = 1
        if len(d) > 2:
            s.iloc[2] = -1
        if len(d) > 3:
            s.iloc[3] = 1
        return s

    def r2(d: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=d.index)
        if len(d) > 0:
            s.iloc[0] = 1
        if len(d) > 2:
            s.iloc[2] = -1
        if len(d) > 3:
            s.iloc[3] = -1
        return s

    def r3(d: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=d.index)
        if len(d) > 0:
            s.iloc[0] = -1
        if len(d) > 1:
            s.iloc[1] = 1
        return s

    sg = SignalGenerator()
    sg.add_rule("rule1", r1)
    sg.add_rule("rule2", r2)
    sg.add_rule("rule3", r3)

    res = sg.generate(df, combine_mode="majority")
    assert res["signal"].tolist() == [1, 0, -1, 0, 0]


def test_combine_mode_custom() -> None:
    """Test combining signals via a custom user-defined callable."""
    dates = pd.date_range("2026-07-01", periods=5)
    df = pd.DataFrame({"close": [10, 11, 12, 13, 14]}, index=dates)

    def r1(d: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=d.index)
        if len(d) > 0:
            s.iloc[0] = 1
        if len(d) > 2:
            s.iloc[2] = -1
        return s

    sg = SignalGenerator()
    sg.add_rule("rule1", r1)

    # Custom combiner that just inverts the first rule
    def custom_combiner(sig_df: pd.DataFrame) -> pd.Series:
        return -sig_df["sig_rule1"]

    res = sg.generate(df, combine_mode="custom", custom_combiner=custom_combiner)
    assert res["signal"].tolist() == [-1, 0, 1, 0, 0]

    # Check that it raises error if custom combiner is missing when mode is 'custom'
    with pytest.raises(ValueError, match="A custom_combiner callable must be provided"):
        sg.generate(df, combine_mode="custom")


def test_look_ahead_bias_detection() -> None:
    """Verify that rules utilizing future data are caught by the look-ahead checker."""
    dates = pd.date_range("2026-07-01", periods=10)
    df = pd.DataFrame(
        {
            "close": [10.0, 11.0, 10.5, 12.0, 13.0, 12.5, 14.0, 15.0, 14.5, 16.0],
        },
        index=dates,
    )

    # Shift look-ahead (future-peeking)
    sg_shift = SignalGenerator()
    sg_shift.add_rule("look_ahead_shift", rule_look_ahead_shift)
    with pytest.raises(ValueError, match="Look-ahead bias detected in rule"):
        sg_shift.generate(df, combine_mode="any")

    # Global statistic look-ahead
    sg_global = SignalGenerator()
    sg_global.add_rule("look_ahead_global", rule_look_ahead_global)
    with pytest.raises(ValueError, match="Look-ahead bias detected in rule"):
        sg_global.generate(df, combine_mode="any")

    # Standard non-look-ahead rules (like a backward-rolling rule) should pass
    def rule_rolling(d: pd.DataFrame) -> pd.Series:
        # Buy if close is above 3-day simple moving average
        sma = d["close"].rolling(3).mean()
        sig = pd.Series(0, index=d.index)
        sig[d["close"] > sma] = 1
        sig[d["close"] < sma] = -1
        return sig

    sg_safe = SignalGenerator()
    sg_safe.add_rule("rolling", rule_rolling)
    # This should generate successfully without raising ValueError
    res = sg_safe.generate(df, combine_mode="any")
    assert "signal" in res.columns


def test_empty_dataframe() -> None:
    """Test that passing an empty DataFrame is handled gracefully."""
    df = pd.DataFrame(columns=["close"])
    sg = SignalGenerator()
    sg.add_rule("rsi", rule_rsi)

    res = sg.generate(df, combine_mode="any")
    assert res.empty
    assert "sig_rsi" in res.columns
    assert "signal" in res.columns


def test_invalid_signal_values() -> None:
    """Test that rules returning invalid signal values raise an error."""
    dates = pd.date_range("2026-07-01", periods=5)
    df = pd.DataFrame({"close": [10, 11, 12, 13, 14]}, index=dates)

    # Rule returns invalid integer (e.g., 2)
    sg1 = SignalGenerator()

    def bad_val(d: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=d.index)
        if len(d) > 0:
            s.iloc[0] = 2
        return s

    sg1.add_rule("bad_val", bad_val)
    with pytest.raises(ValueError, match="returned invalid signal values"):
        sg1.generate(df, combine_mode="any")

    # Rule returns floats like 0.5
    sg2 = SignalGenerator()

    def bad_float(d: pd.DataFrame) -> pd.Series:
        s = pd.Series(0.0, index=d.index)
        if len(d) > 0:
            s.iloc[0] = 0.5
        return s

    sg2.add_rule("bad_float", bad_float)
    with pytest.raises(ValueError, match="returned invalid signal values"):
        sg2.generate(df, combine_mode="any")
