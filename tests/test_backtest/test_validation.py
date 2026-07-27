"""Unit tests for statistical validation functions in src/backtest/validation.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtest.validation import (
    block_bootstrap,
    expected_max_sharpe,
    deflated_sharpe_ratio,
    holm_bonferroni_correction,
    check_red_flags,
)


def test_block_bootstrap_valid_metrics():
    """Test that block_bootstrap returns stats dicts with valid confidence intervals."""
    # Seed generator for reproducibility
    np.random.seed(42)
    # Generate daily returns with small positive mean
    returns = pd.Series(np.random.normal(loc=0.0005, scale=0.01, size=100))

    results = block_bootstrap(returns, block_size=10, num_samples=100)

    # Check keys
    expected_keys = {"sharpe_ratio", "annualized_return", "max_drawdown", "win_rate"}
    assert set(results.keys()) == expected_keys

    # Check stats structure and order of values in confidence intervals
    for metric, stats in results.items():
        assert "mean" in stats
        assert "median" in stats
        assert "ci_lower" in stats
        assert "ci_upper" in stats

        mean = stats["mean"]
        median = stats["median"]
        ci_lower = stats["ci_lower"]
        ci_upper = stats["ci_upper"]

        # Confidence intervals should enclose the median and mean (typically)
        assert ci_lower <= ci_upper
        assert ci_lower <= median <= ci_upper
        assert ci_lower <= mean <= ci_upper

    # Check win rate values are between 0 and 1
    assert 0.0 <= results["win_rate"]["mean"] <= 1.0
    assert 0.0 <= results["win_rate"]["median"] <= 1.0


def test_block_bootstrap_edge_cases():
    """Test block_bootstrap with empty inputs or length 1 inputs."""
    # Empty Series
    empty_series = pd.Series([], dtype=float)
    empty_results = block_bootstrap(empty_series)
    for metric, stats in empty_results.items():
        assert stats["mean"] == 0.0
        assert stats["median"] == 0.0
        assert stats["ci_lower"] == 0.0
        assert stats["ci_upper"] == 0.0

    # Length 1 Series
    len1_series = pd.Series([0.01])
    len1_results = block_bootstrap(len1_series, block_size=5, num_samples=10)
    assert "sharpe_ratio" in len1_results


def test_expected_max_sharpe():
    """Test that expected_max_sharpe logic behaves correctly."""
    # Fewer or equal to 1 trials should yield 0.0 expected max Sharpe
    assert expected_max_sharpe(1, 1000) == 0.0
    assert expected_max_sharpe(0, 1000) == 0.0
    # Negative T_days should yield 0.0
    assert expected_max_sharpe(10, 0) == 0.0
    assert expected_max_sharpe(10, -5) == 0.0

    # More trials should increase the expected max Sharpe
    val_10 = expected_max_sharpe(10, 252)
    val_100 = expected_max_sharpe(100, 252)
    assert val_10 > 0
    assert val_100 > val_10


def test_deflated_sharpe_ratio_behavior():
    """Test that deflated_sharpe_ratio behaves correctly with mock parameters."""
    observed_sr = 1.2
    skew = 0.0
    kurt = 3.0  # Normal distribution kurtosis
    T = 500

    # Case A: Low number of trials (low selection bias) -> DSR should be high
    dsr_low_trials = deflated_sharpe_ratio(
        observed_sr=observed_sr,
        skewness=skew,
        kurtosis=kurt,
        T_days=T,
        N_trials=2
    )

    # Case B: High number of trials (high selection bias) -> DSR should be lower
    dsr_high_trials = deflated_sharpe_ratio(
        observed_sr=observed_sr,
        skewness=skew,
        kurtosis=kurt,
        T_days=T,
        N_trials=100
    )

    assert 0.0 <= dsr_low_trials <= 1.0
    assert 0.0 <= dsr_high_trials <= 1.0
    assert dsr_high_trials < dsr_low_trials

    # Verify that skewness affects the standard error and thus DSR
    # Positive observed Sharpe + negative skewness = larger daily standard error
    dsr_neg_skew = deflated_sharpe_ratio(
        observed_sr=observed_sr,
        skewness=-0.8,
        kurtosis=kurt,
        T_days=T,
        N_trials=5
    )
    dsr_pos_skew = deflated_sharpe_ratio(
        observed_sr=observed_sr,
        skewness=0.8,
        kurtosis=kurt,
        T_days=T,
        N_trials=5
    )
    # Larger daily standard error -> wider distribution -> lower DSR probability
    assert dsr_neg_skew != dsr_pos_skew


def test_holm_bonferroni_correction():
    """Test Holm-Bonferroni correction function."""
    # Test case 1: Rejects only H0
    p_values = [0.01, 0.04, 0.03]
    # alpha = 0.05
    # Sorted: p_0 = 0.01 (threshold 0.05/3 = 0.0167) -> Reject (True)
    #         p_2 = 0.03 (threshold 0.05/2 = 0.025) -> Fail to reject (False)
    #         p_1 = 0.04 (threshold 0.05/1 = 0.05) -> Fail to reject (False) (due to step-down halt)
    rejections = holm_bonferroni_correction(p_values, alpha=0.05)
    assert rejections == [True, False, False]

    # Test case 2: Rejects all
    p_values_all = [0.01, 0.02, 0.04]
    # Sorted: p_0 = 0.01 <= 0.0167 -> Reject
    #         p_1 = 0.02 <= 0.025 -> Reject
    #         p_2 = 0.04 <= 0.05 -> Reject
    assert holm_bonferroni_correction(p_values_all, alpha=0.05) == [True, True, True]

    # Test case 3: Rejects none
    p_values_none = [0.06, 0.1, 0.15]
    assert holm_bonferroni_correction(p_values_none, alpha=0.05) == [False, False, False]

    # Test case 4: Empty list
    assert holm_bonferroni_correction([], alpha=0.05) == []


def test_check_red_flags_triggers():
    """Test check_red_flags triggers appropriate rejections and warnings."""
    # All metrics perfect -> no flags
    perfect_metrics = {
        "sharpe_ratio": 1.2,
        "total_trades": 150,
        "max_drawdown": -0.10,
        "dsr": 0.98,
        "profit_factor": 1.8,
        "total_years": 6.0,
    }
    assert len(check_red_flags(perfect_metrics, total_trials=5)) == 0

    # Sharpe too high (>2.0) -> Rejection
    high_sharpe_metrics = {
        "sharpe_ratio": 2.5,
        "total_trades": 150,
        "max_drawdown": -0.10,
        "dsr": 0.98,
    }
    flags = check_red_flags(high_sharpe_metrics, total_trials=5)
    assert any("REJECT: Sharpe ratio" in f for f in flags)

    # Too few trades (<100) -> Rejection
    few_trades_metrics = {
        "sharpe_ratio": 1.2,
        "total_trades": 45,
        "max_drawdown": -0.10,
        "dsr": 0.98,
    }
    flags = check_red_flags(few_trades_metrics, total_trials=5)
    assert any("REJECT: Total trades" in f for f in flags)

    # High drawdown (>20%) -> Rejection (handles fractional drawdown)
    high_dd_fraction_metrics = {
        "sharpe_ratio": 1.2,
        "total_trades": 150,
        "max_drawdown": -0.25,
        "dsr": 0.98,
    }
    flags = check_red_flags(high_dd_fraction_metrics, total_trials=5)
    assert any("REJECT: Maximum drawdown" in f for f in flags)

    # High drawdown (>20%) -> Rejection (handles percentage drawdown)
    high_dd_pct_metrics = {
        "sharpe_ratio": 1.2,
        "total_trades": 150,
        "max_drawdown": -25.0,
        "dsr": 0.98,
    }
    flags = check_red_flags(high_dd_pct_metrics, total_trials=5)
    assert any("REJECT: Maximum drawdown" in f for f in flags)

    # DSR <= 0.95 -> Rejection
    low_dsr_metrics = {
        "sharpe_ratio": 1.2,
        "total_trades": 150,
        "max_drawdown": -0.10,
        "dsr": 0.90,
    }
    flags = check_red_flags(low_dsr_metrics, total_trials=5)
    assert any("REJECT: Deflated Sharpe Ratio" in f for f in flags)

    # DSR computed on the fly and fails
    on_the_fly_dsr_fail = {
        "sharpe_ratio": 0.8,
        "total_trades": 150,
        "max_drawdown": -0.10,
        "skewness": 0.0,
        "kurtosis": 3.0,
        "t_days": 500,
    }
    # With 100 trials, observed_sr of 0.8 is not significant under null
    flags = check_red_flags(on_the_fly_dsr_fail, total_trials=100)
    assert any("REJECT: Deflated Sharpe Ratio" in f for f in flags)

    # Warnings triggered (Low profit factor, inconsistent folds, short backtest)
    warning_metrics = {
        "sharpe_ratio": 1.2,
        "total_trades": 150,
        "max_drawdown": -0.10,
        "dsr": 0.98,
        "profit_factor": 1.1,
        "sharpe_std": 1.2,
        "sharpe_mean": 1.0,
        "total_years": 4.0,
    }
    flags = check_red_flags(warning_metrics, total_trials=5)
    assert any("WARNING: Low profit factor" in f for f in flags)
    assert any("WARNING: Inconsistent fold performance" in f for f in flags)
    assert any("WARNING: Short backtest period" in f for f in flags)
