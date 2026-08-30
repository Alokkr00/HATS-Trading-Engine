"""Unit tests for purged & embargoed Walk-Forward Cross-Validation."""

import numpy as np
import pandas as pd
import pytest

from src.backtest.walk_forward import WalkForwardValidator
from src.strategy.strategies import MACDHistogramStrategy, RSIMeanReversionStrategy


@pytest.fixture
def synthetic_walk_forward_df():
    """Generate 600 daily bars of synthetic OHLCV data with timezone index."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=600, freq="B", tz="America/New_York")
    
    # Random walk with sinusoidal cycle
    t = np.linspace(0, 8 * np.pi, 600)
    cycle = 10.0 * np.sin(t)
    noise = np.cumsum(np.random.normal(0.05, 1.0, 600))
    close = 100.0 + cycle + noise
    close = np.maximum(close, 10.0)

    high = close + np.random.uniform(0.5, 2.0, 600)
    low = close - np.random.uniform(0.5, 2.0, 600)
    open_p = low + np.random.uniform(0.1, 0.9, 600) * (high - low)
    volume = np.random.uniform(100000, 500000, 600)

    df = pd.DataFrame(
        {
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )
    df.attrs["symbol"] = "SPY"
    return df


def test_walk_forward_rolling_validation(synthetic_walk_forward_df):
    """Verify rolling window walk-forward validation with embargo."""
    strategy = MACDHistogramStrategy(name="MACDFilterTest", config={"use_adx_filter": False, "check_look_ahead": False})
    
    validator = WalkForwardValidator(
        strategy=strategy,
        train_bars=252,
        test_bars=63,
        embargo_bars=5,
        mode="rolling",
        capital=100000.0,
        num_tested_trials=5,
    )

    results = validator.run(synthetic_walk_forward_df)

    assert "folds" in results
    assert len(results["folds"]) >= 4
    assert "oos_equity_curve" in results
    assert len(results["oos_equity_curve"]) > 0
    assert "summary" in results

    summary = results["summary"]
    assert summary["mode"] == "rolling"
    assert summary["embargo_bars"] == 5
    assert "deflated_sharpe_ratio" in summary
    assert "expected_shortfall_cvar95" in summary

    # Verify fold boundary integrity (embargo between train_end and test_start)
    for fold in results["folds"]:
        assert fold.train_end < fold.test_start
        assert fold.test_start <= fold.test_end
        assert "annualized_sharpe" in fold.in_sample_metrics
        assert "annualized_sharpe" in fold.out_of_sample_metrics


def test_walk_forward_expanding_validation(synthetic_walk_forward_df):
    """Verify expanding window walk-forward validation."""
    strategy = RSIMeanReversionStrategy(name="RSITest", config={"check_look_ahead": False})
    
    validator = WalkForwardValidator(
        strategy=strategy,
        train_bars=200,
        test_bars=50,
        embargo_bars=5,
        mode="expanding",
        capital=100000.0,
    )

    results = validator.run(synthetic_walk_forward_df)

    assert len(results["folds"]) >= 4
    # In expanding mode, all folds start at the initial bar
    first_train_start = results["folds"][0].train_start
    for fold in results["folds"]:
        assert fold.train_start == first_train_start


def test_walk_forward_insufficient_bars_error(synthetic_walk_forward_df):
    """Verify ValueError is raised if DataFrame has fewer bars than train + embargo + test."""
    strategy = MACDHistogramStrategy(name="ShortTest")
    validator = WalkForwardValidator(
        strategy=strategy,
        train_bars=500,
        test_bars=200,
        embargo_bars=10,
    )
    # DataFrame only has 600 bars, required is 710
    with pytest.raises(ValueError, match="insufficient"):
        validator.run(synthetic_walk_forward_df)
