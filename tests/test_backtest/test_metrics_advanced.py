"""Unit tests for advanced quantitative and deflated Sharpe metrics."""

import numpy as np
import pandas as pd
import pytest

from src.backtest.metrics_advanced import calculate_advanced_metrics


def test_advanced_metrics_basic_calculation():
    """Verify calculation of advanced metrics on known positive returns."""
    np.random.seed(42)
    # Generate 500 daily returns with positive drift
    daily_returns = np.random.normal(loc=0.0008, scale=0.012, size=500)
    metrics = calculate_advanced_metrics(daily_returns, benchmark_sr=0.0, num_trials=1)

    assert metrics["annualized_sharpe"] > 0
    assert 0.0 <= metrics["psr"] <= 1.0
    assert 0.0 <= metrics["dsr"] <= 1.0
    assert metrics["cvar_95"] > 0
    assert metrics["cvar_99"] >= metrics["cvar_95"]
    assert "expectancy" in metrics
    assert "profit_factor" in metrics
    assert metrics["profit_factor"] > 0
    assert metrics["calmar_ratio"] > 0


def test_deflated_sharpe_penalizes_multiple_trials():
    """Verify that DSR strictly decreases as the number of trials N increases."""
    np.random.seed(42)
    daily_returns = np.random.normal(loc=0.0005, scale=0.01, size=500)

    res_1 = calculate_advanced_metrics(daily_returns, num_trials=1)
    res_10 = calculate_advanced_metrics(daily_returns, num_trials=10)
    res_100 = calculate_advanced_metrics(daily_returns, num_trials=100)

    # With 1 trial, DSR == PSR
    assert res_1["dsr"] == res_1["psr"]
    # With 10 trials, DSR should be strictly lower than with 1 trial
    assert res_10["dsr"] <= res_1["dsr"]
    # With 100 trials, DSR should be strictly lower than with 10 trials
    assert res_100["dsr"] <= res_10["dsr"]


def test_trade_level_expectancy_and_loss_streaks():
    """Verify trade-level expectancy, profit factor, and max consecutive losses."""
    trades = [
        {"pnl": 150.0},
        {"pnl": 200.0},
        {"pnl": -50.0},
        {"pnl": -80.0},
        {"pnl": -40.0},
        {"pnl": 300.0},
    ]
    daily_returns = np.array([0.01, 0.015, -0.005, -0.008, -0.004, 0.02] * 20)
    metrics = calculate_advanced_metrics(daily_returns, trades=trades)

    assert metrics["max_consecutive_losses"] == 3
    # Gross profit = 650, Gross loss = 170 -> Profit factor ~ 3.82
    assert pytest.approx(metrics["profit_factor"], rel=1e-2) == 3.82
    assert metrics["win_rate"] == 0.5
    assert metrics["expectancy"] > 0


def test_empty_or_degenerate_returns():
    """Verify graceful zero-handling for empty or constant return series."""
    metrics_empty = calculate_advanced_metrics([])
    assert metrics_empty["annualized_sharpe"] == 0.0
    assert metrics_empty["dsr"] == 0.0

    metrics_constant = calculate_advanced_metrics([0.001] * 10)
    assert metrics_constant["annualized_sharpe"] == 0.0
