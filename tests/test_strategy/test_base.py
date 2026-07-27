"""Unit tests for the BaseStrategy class."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.base import BaseStrategy


class SimpleStrategy(BaseStrategy):
    """Concrete mock strategy subclass for unit testing."""

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add mock technical indicators."""
        df = df.copy()
        df["sma_10"] = df["close"].rolling(2, min_periods=1).mean()
        return df

    def setup_rules(self) -> None:
        """Set up rules for mock strategy."""
        def rule_above_sma(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            signals[d["close"] > d["sma_10"]] = 1
            signals[d["close"] < d["sma_10"]] = -1
            return signals

        self.signal_generator.add_rule("above_sma", rule_above_sma)


def test_base_strategy_normal_flow() -> None:
    """Test standard execution flow of BaseStrategy subclass."""
    # Create timezone-aware DatetimeIndex
    dates = pd.date_range(
        "2026-07-01 09:30:00", periods=5, freq="1min", tz="America/New_York"
    )
    df = pd.DataFrame(
        {
            "open": [10.0, 10.5, 11.0, 10.8, 11.2],
            "high": [10.6, 11.0, 11.2, 11.0, 11.5],
            "low": [9.9, 10.4, 10.9, 10.7, 11.1],
            "close": [10.2, 10.8, 11.1, 10.9, 11.3],
            "volume": [1000, 1200, 1100, 900, 1300],
        },
        index=dates,
    )

    # Instantiate strategy
    # Config sets check_look_ahead=False for simplicity, and combine_mode="any"
    config = {"combine_mode": "any", "check_look_ahead": False}
    strategy = SimpleStrategy(name="TestStrategy", config=config)

    assert strategy.name == "TestStrategy"
    assert "above_sma" in strategy.signal_generator._rules

    # Generate signals
    res_df = strategy.generate_signals(df)

    # Check indicator added
    assert "sma_10" in res_df.columns
    # Check individual signal and combined signal added
    assert "sig_above_sma" in res_df.columns
    assert "signal" in res_df.columns

    # Verify that index matches original
    assert res_df.index.equals(df.index)
    assert res_df.index.tz == df.index.tz


def test_base_strategy_timezone_validation() -> None:
    """Verify timezone validation rules in BaseStrategy."""
    config = {"check_look_ahead": False}
    strategy = SimpleStrategy(name="TestStrategy", config=config)

    # 1. Non-DatetimeIndex
    df_no_datetime = pd.DataFrame({"close": [10, 11, 12]})
    with pytest.raises(ValueError, match="must be a pandas DatetimeIndex"):
        strategy.generate_signals(df_no_datetime)

    # 2. Timezone-naive DatetimeIndex
    dates_naive = pd.date_range("2026-07-01 09:30:00", periods=3, freq="1min")
    df_naive = pd.DataFrame({"close": [10, 11, 12]}, index=dates_naive)
    with pytest.raises(ValueError, match="DatetimeIndex is naive"):
        strategy.generate_signals(df_naive)


def test_base_strategy_empty_dataframe() -> None:
    """Verify that an empty DataFrame is handled gracefully by BaseStrategy."""
    strategy = SimpleStrategy(name="TestStrategy")
    df_empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    # Set DatetimeIndex for empty dataframe
    df_empty.index = pd.to_datetime(df_empty.index)
    
    res = strategy.generate_signals(df_empty)
    assert res.empty
    assert "sig_above_sma" in res.columns
    assert "signal" in res.columns
