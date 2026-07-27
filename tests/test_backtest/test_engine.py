"""Unit tests for high-fidelity backtesting engine and transaction cost model."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from src.strategy.base import BaseStrategy
from src.backtest.cost import CostModel, LiquidityTier, spread_multiplier
from src.backtest.engine import BacktestEngine, compute_performance_metrics


# 1. Mock Strategy for testing execution correctness and cost calculations
class MockStrategy(BaseStrategy):
    """Simple mock strategy that executes pre-configured signal series."""

    def __init__(self, name: str, signals: pd.Series) -> None:
        self.mock_signals = signals
        super().__init__(name, config={"check_look_ahead": False, "combine_mode": "any"})


    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # Mock ATR indicator (e.g. constant 1.0)
        df = df.copy()
        df["atr_14"] = 1.0
        return df

    def setup_rules(self) -> None:
        def rule_mock(df: pd.DataFrame) -> pd.Series:
            return self.mock_signals.reindex(df.index).fillna(0).astype(int)
        self.signal_generator.add_rule("mock_rule", rule_mock)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        # 2 dollars below entry price
        return entry_price - 2.0


def create_test_df(n_bars: int, initial_price: float = 100.0) -> pd.DataFrame:
    """Helper to create test OHLCV DataFrame with timezone-aware index."""
    dates = pd.date_range("2020-01-01", periods=n_bars, freq="D", tz="America/New_York")
    df = pd.DataFrame(
        {
            "open": np.arange(initial_price, initial_price + n_bars, dtype=float),
            "high": np.arange(initial_price + 0.5, initial_price + n_bars + 0.5, dtype=float),
            "low": np.arange(initial_price - 0.5, initial_price + n_bars - 0.5, dtype=float),
            "close": np.arange(initial_price + 0.2, initial_price + n_bars + 0.2, dtype=float),
            "volume": np.full(n_bars, 1000.0),
            "vix": np.full(n_bars, 15.0),  # multiplier will be 1.0
        },
        index=dates,
    )
    return df


def test_spread_multiplier() -> None:
    """Test spread widening logic based on VIX thresholds."""
    assert spread_multiplier(10.0) == 1.0
    assert spread_multiplier(15.0) == 1.0
    # 20 is mid-way between 15 and 25 (multiplier: 1.0 + (20-15)*0.05 = 1.25)
    assert pytest.approx(spread_multiplier(20.0)) == 1.25
    assert spread_multiplier(25.0) == 1.5
    # 30 is mid-way between 25 and 35 (multiplier: 1.5 + (30-25)*0.15 = 2.25)
    assert pytest.approx(spread_multiplier(30.0)) == 2.25
    assert spread_multiplier(35.0) == 3.0
    # 40 (multiplier: 3.0 + (40-35)*0.10 = 3.5)
    assert pytest.approx(spread_multiplier(40.0)) == 3.5


def test_cost_model_rates() -> None:
    """Verify CostModel factory and defaults."""
    default_model = CostModel.default()
    assert default_model.spread_bps == 1.5
    assert default_model.slippage_bps == 3.0
    assert default_model.round_trip_cost_bps() == 9.0

    tier1_model = CostModel.for_tier(LiquidityTier.MEGA_CAP)
    assert tier1_model.spread_bps == 1.0
    assert tier1_model.slippage_bps == 1.5
    assert tier1_model.round_trip_cost_bps() == 5.0

    # Test dollar calculation for a $10,000 notional trade (100 shares at $100)
    # default round-trip = 9 bps -> $9.00
    # SEC = 10,000 * 8.00 / 1,000,000 = $0.08
    # FINRA = 100 * 0.000166 = $0.0166
    # Total = 9.00 + 0.08 + 0.0166 = $9.0966
    default_cost_dlr = default_model.round_trip_cost_dollars(notional=10000.0, shares=100)
    assert pytest.approx(default_cost_dlr) == 9.0966


def test_backtest_execution_and_costs() -> None:
    """Test trade execution and cost deductions."""
    df = create_test_df(10, initial_price=100.0)
    
    # Buy signal at index 1 (Day 2) -> executed at Open of index 2 (Day 3, Open = 102.0)
    # Sell signal at index 4 (Day 5) -> executed at Open of index 5 (Day 6, Open = 105.0)
    signals = pd.Series(0, index=df.index)
    signals.iloc[1] = 1
    signals.iloc[4] = -1

    strategy = MockStrategy("Mock", signals)
    cost_model = CostModel.default()
    engine = BacktestEngine(strategy, capital=100000.0, cost_model=cost_model)

    res = engine.run(df)
    trades = res["trades"]
    equity_curve = res["equity_curve"]

    # 1. Trade execution checks
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_time"] == df.index[2]
    assert trade["exit_time"] == df.index[5]
    assert trade["entry_price"] == 102.0
    assert trade["exit_price"] == 105.0

    # 2. Position sizing checks:
    # Stop price = 102.0 - 2.0 = 100.0
    # stop distance = 2.0
    # 1% risk = 1000.0 -> shares = 1000 / 2.0 = 500
    # Capped at 10% of equity = 10,000 -> max shares = 10,000 / 102.0 = 98.039 -> floor = 98 shares.
    assert trade["shares"] == 98

    # 3. Cost deduction checks:
    # Entry cost = 98 * 102.0 * 4.5 bps = 9996.0 * 0.00045 = 4.4982
    assert pytest.approx(trade["entry_cost"]) == 4.4982

    # Exit cost = 98 * 105.0 * 4.5 bps + (98 * 105.0) * 8.00 / 1e6 + 98 * 0.000166
    # = 10290.0 * 0.00045 + 10290.0 * 0.000008 + 0.016268
    # = 4.6305 + 0.08232 + 0.016268 = 4.729088
    assert pytest.approx(trade["exit_cost"]) == 4.729088

    # Net PnL = (105.0 - 102.0) * 98 - 4.4982 - 4.729088 = 294.0 - 9.227288 = 284.772712
    assert pytest.approx(trade["pnl"]) == 284.772712


def test_performance_metrics_calculation() -> None:
    """Test performance metrics logic using a predetermined mock equity curve."""
    dates = pd.date_range("2020-01-01", periods=10, freq="D", tz="America/New_York")
    
    # 10 days of returns: 1% compounding daily growth
    equity = 100000.0 * (1.01 ** np.arange(10))
    equity_curve = pd.Series(equity, index=dates)

    # 1 win, 1 loss trade
    mock_trades = [
        {"pnl": 500.0},
        {"pnl": -250.0}
    ]

    metrics = compute_performance_metrics(equity_curve, mock_trades)

    assert metrics["total_trades"] == 2
    assert metrics["win_rate"] == 0.5
    # Gross Profit = 500, Gross Loss = 250 -> Profit Factor = 2.0
    assert metrics["profit_factor"] == 2.0
    assert metrics["max_drawdown"] == 0.0  # continuous up-trend
    assert metrics["max_drawdown_duration_days"] == 0

    # CAGR: (Ending / Beginning) ** (252 / 10) - 1
    expected_cagr = (equity[-1] / equity[0]) ** (252.0 / 10) - 1.0
    assert pytest.approx(metrics["cagr"]) == expected_cagr


def test_walk_forward_splitter_boundaries() -> None:
    """Verify walk-forward window splitting and boundary correctness."""
    df = create_test_df(1000, initial_price=100.0)
    signals = pd.Series(0, index=df.index)
    strategy = MockStrategy("Mock", signals)
    
    engine = BacktestEngine(strategy, capital=100000.0, cost_model=None)
    
    res = engine.run_walk_forward(
        df,
        train_window_days=756,
        test_window_days=126,
        embargo_days=5,
        step_size_days=63
    )

    folds = res["folds"]
    
    # Verify exact fold count:
    # start_idx = 0 -> train_end = 756 -> test_start = 761 -> test_end = 887
    # start_idx = 63 -> train_end = 819 -> test_start = 824 -> test_end = 950
    # start_idx = 126 -> train_end = 882 -> test_start = 887 -> test_end = 1000
    # start_idx = 189 -> train_end = 945 -> test_start = 950 -> test_end = 1000
    # start_idx = 252 -> train_end = 1008 -> test_start = 1013 >= 1000 (breaks)
    # Expected: 4 folds
    assert len(folds) == 4

    # Fold 0 boundaries check
    assert folds[0]["train_range"][0] == df.index[0]
    assert folds[0]["train_range"][1] == df.index[755]
    assert folds[0]["test_range"][0] == df.index[761]
    assert folds[0]["test_range"][1] == df.index[886]

    # Fold 3 boundaries check
    assert folds[3]["train_range"][0] == df.index[189]
    assert folds[3]["train_range"][1] == df.index[944]
    assert folds[3]["test_range"][0] == df.index[950]
    assert folds[3]["test_range"][1] == df.index[999]


def test_run_vectorized() -> None:
    """Verify that vectorized simulation calculates returns and metrics correctly."""
    df = create_test_df(100, initial_price=100.0)
    signals = pd.Series(0, index=df.index)
    # Buy signal at bar 10, Sell/exit signal at bar 20
    signals.iloc[10] = 1
    signals.iloc[20] = -1
    
    strategy = MockStrategy("Mock", signals)
    engine = BacktestEngine(strategy, capital=100000.0, cost_model=None)
    
    res = engine.run_vectorized(df)
    
    assert "equity_curve" in res
    assert "trades" in res
    assert "metrics" in res
    
    assert len(res["equity_curve"]) == 100
    assert len(res["trades"]) == 1
    assert res["metrics"]["total_trades"] == 1
    # Entry price at bar 11 open should be 111.0, exit at bar 21 close should be 121.2
    trade = res["trades"][0]
    assert trade["entry_price"] == pytest.approx(111.0)
    assert trade["exit_price"] == pytest.approx(121.2)


def test_stop_loss_execution() -> None:
    """Verify that stop-loss exits are executed when price drops below stop price."""
    df = create_test_df(10, initial_price=100.0)
    # Day 0: open=100, high=100.5, low=99.5, close=100.2
    # Day 1: open=101, high=101.5, low=100.5, close=101.2
    # Day 2: open=102, high=102.5, low=101.5, close=102.2
    # Day 3: open=103, high=103.5, low=90.0, close=103.2 (Low hits stop price of 100.0!)
    
    df.loc[df.index[3], "low"] = 90.0 # Force a drop to hit the stop
    
    signals = pd.Series(0, index=df.index)
    signals.iloc[1] = 1 # Buy signal on Day 1 -> Entry on Day 2 Open (102.0)
    # Stop price is entry - 2.0 = 100.0.
    
    strategy = MockStrategy("MockStopLoss", signals)
    engine = BacktestEngine(strategy, capital=100000.0, cost_model=None)
    
    res = engine.run(df)
    
    assert len(res["trades"]) == 1
    trade = res["trades"][0]
    assert trade["status"] == "stopped"
    assert trade["exit_price"] == pytest.approx(100.0)
    assert trade["exit_time"] == df.index[3]


