"""Unit tests for H.A.T.S systematic upgrades (Phase 1, 2, and 3)."""

from __future__ import annotations

import os
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import pytest

from src.strategy.regime import MarketRegimeClassifier, RegimeState
from src.risk.circuit_breaker import CircuitBreaker
from src.risk.heat_tracker import PortfolioHeatTracker
from src.strategy.sector_momentum import SectorMomentumStrategy
from src.strategy.options_iv_runup import OptionsIVRunupStrategy
from src.strategy.breadth_reversion import BreadthThrustReversionStrategy


def create_test_df(n_bars: int, initial_price: float = 100.0) -> pd.DataFrame:
    """Helper to create a timezone-aware DatetimeIndex DataFrame."""
    dates = pd.date_range("2025-01-01", periods=n_bars, freq="D", tz="America/New_York")
    df = pd.DataFrame(
        {
            "open": np.full(n_bars, initial_price),
            "high": np.full(n_bars, initial_price + 1.0),
            "low": np.full(n_bars, initial_price - 1.0),
            "close": np.full(n_bars, initial_price),
            "volume": np.full(n_bars, 1000000.0),
        },
        index=dates,
    )
    return df


# ---------------------------------------------------------------------------
# 1. Market Regime Classifier Tests
# ---------------------------------------------------------------------------
def test_regime_classifier() -> None:
    classifier = MarketRegimeClassifier(
        low_vol_threshold=16.0,
        high_vol_threshold=25.0,
        crisis_vol_threshold=35.0
    )

    # Create SPY DataFrame with close above 200 SMA (Bullish)
    # 250 bars all at 100.0 -> SMA200 = 100.0
    spy_df = create_test_df(250, 100.0)
    spy_df.iloc[-1, spy_df.columns.get_loc("close")] = 110.0 # Above SMA200

    # Test Bullish States
    res = classifier.classify(spy_df, vix_value=12.0)
    assert res["state"] == RegimeState.BULL_QUIET
    assert res["size_multiplier"] == 1.0
    assert "BUY" in res["allowed_actions"]

    res = classifier.classify(spy_df, vix_value=20.0)
    assert res["state"] == RegimeState.BULL_NORMAL
    assert res["size_multiplier"] == 1.0

    res = classifier.classify(spy_df, vix_value=28.0)
    assert res["state"] == RegimeState.BULL_VOLATILE
    assert res["size_multiplier"] == 0.5

    # Test Bearish States
    spy_df_bear = create_test_df(250, 100.0)
    spy_df_bear.iloc[-1, spy_df_bear.columns.get_loc("close")] = 90.0 # Below SMA200

    res = classifier.classify(spy_df_bear, vix_value=12.0)
    assert res["state"] == RegimeState.BEAR_QUIET
    assert res["size_multiplier"] == 0.75
    assert "INVERSE" in res["allowed_actions"]

    res = classifier.classify(spy_df_bear, vix_value=20.0)
    assert res["state"] == RegimeState.BEAR_NORMAL

    res = classifier.classify(spy_df_bear, vix_value=28.0)
    assert res["state"] == RegimeState.BEAR_VOLATILE
    assert res["size_multiplier"] == 0.25

    # Test Crisis state
    res = classifier.classify(spy_df, vix_value=40.0)
    assert res["state"] == RegimeState.RISK_OFF
    assert res["size_multiplier"] == 0.0
    assert len(res["allowed_actions"]) == 0


# ---------------------------------------------------------------------------
# 2. Circuit Breaker Tests
# ---------------------------------------------------------------------------
def test_circuit_breaker(tmp_path: Path) -> None:
    config = {
        "circuit_breakers": {
            "max_daily_loss_pct": 0.03,
            "max_drawdown_pct": 0.10,
            "max_trades_per_day": 20,
            "cooldown_after_circuit_break_min": 60
        }
    }
    
    # We instantiate first, then override state_path and reset state to tmp_path
    cb = CircuitBreaker(config)
    cb.state_path = tmp_path / "cb_state.json"
    cb._reset_state()

    # Normal check
    allowed, reason = cb.check(net_liquidity=100000.0, trades_today=5)
    assert allowed is True

    # Daily loss limit exceeded (drop from 100k to 96k is 4%)
    allowed, reason = cb.check(net_liquidity=96000.0)
    assert allowed is False
    assert "Daily loss" in reason
    assert cb.state["halted"] is True

    # Reset
    cb.reset()
    assert cb.state["halted"] is False

    # Max trades limit exceeded
    allowed, reason = cb.check(net_liquidity=100000.0, trades_today=25)
    assert allowed is False
    assert "trades count" in reason


# ---------------------------------------------------------------------------
# 3. Portfolio Heat Tracker Tests
# ---------------------------------------------------------------------------
def test_portfolio_heat_tracker() -> None:
    tracker = PortfolioHeatTracker(max_heat_pct=0.06)

    positions = [
        {"symbol": "AAPL", "qty": 100, "avg_price": 150.0, "stop_price": 145.0}, # Risk: 100 * 5 = $500
        {"symbol": "MSFT", "qty": 50, "avg_price": 300.0, "stop_price": 290.0},  # Risk: 50 * 10 = $500
    ]

    # Total risk = $1000. Equity = $20,000. Heat = 5%
    heat = tracker.calculate_heat(positions, net_equity=20000.0)
    assert abs(heat - 0.05) < 1e-6

    # Adding a 1.5% risk trade should fail (exceeds 6%)
    assert tracker.can_add_trade(0.015, heat) is False

    # Adding a 0.5% risk trade should pass
    assert tracker.can_add_trade(0.005, heat) is True


# ---------------------------------------------------------------------------
# 4. Sector Momentum Strategy Tests
# ---------------------------------------------------------------------------
@patch("src.strategy.sector_momentum.DataStore.load")
def test_sector_momentum_strategy(mock_load: MagicMock) -> None:
    # Set up mock sector DataFrames
    # We want XLK to have a positive return, XLF to have negative
    xlk_df = create_test_df(50, 100.0)
    xlk_df.loc[xlk_df.index[-1], "close"] = 110.0 # +10% return
    xlf_df = create_test_df(50, 100.0)
    xlf_df.loc[xlf_df.index[-1], "close"] = 90.0  # -10% return
    
    # Mock data store returns
    def store_load_side_effect(symbol: str, *args, **kwargs):
        df = xlk_df.copy() if symbol == "XLK" else xlf_df.copy()
        df.attrs["symbol"] = symbol
        return df

    mock_load.side_effect = store_load_side_effect

    strategy = SectorMomentumStrategy(
        "Momentum",
        config={"lookback": 10, "rebalance_period": 5, "check_look_ahead": False}
    )

    # Generate signals for XLK
    df_xlk = xlk_df.copy()
    df_xlk.attrs["symbol"] = "XLK"
    res_xlk = strategy.generate_signals(df_xlk)

    assert "sector_rank" in res_xlk.columns
    # XLK should be ranked #1 (or highly) because it has the +10% return
    assert res_xlk["sector_rank"].iloc[-1] <= 3.0


# ---------------------------------------------------------------------------
# 5. Options IV Run-up Strategy Tests
# ---------------------------------------------------------------------------
def test_options_iv_runup_strategy() -> None:
    strategy = OptionsIVRunupStrategy("IVRunup", config={"check_look_ahead": False})
    
    # Mock next earnings date to be exactly 10 days from the last bar in df
    df = create_test_df(20, 100.0)
    df.attrs["symbol"] = "AAPL"
    last_bar_date = df.index[-1].to_pydatetime().date()
    earnings_date = last_bar_date + timedelta(days=10)
 
    with patch.object(strategy, "_get_all_earnings_dates", return_value=[earnings_date]):
        res = strategy.generate_signals(df)
        assert "days_to_earnings" in res.columns
        assert res["days_to_earnings"].iloc[-1] == 10.0
        
        # At 10 days to earnings, signal should trigger BUY (1)
        assert res["signal"].iloc[-1] == 1.0


# ---------------------------------------------------------------------------
# 6. Breadth Thrust Reversion Strategy Tests
# ---------------------------------------------------------------------------
@patch("src.strategy.breadth_reversion.DataStore.load")
def test_breadth_reversion_strategy(mock_load: MagicMock) -> None:
    # Mock VIX level at 25 (above threshold of 20)
    vix_df = create_test_df(50, 25.0)
    vix_df.attrs["symbol"] = "^VIX"
    mock_load.return_value = vix_df

    strategy = BreadthThrustReversionStrategy("Breadth", config={"check_look_ahead": False})

    # Create oversold SPY DataFrame
    # Price dropping rapidly will make RSI(5) drop below 20
    spy_df = create_test_df(50, 100.0)
    for i in range(10, 50):
        spy_df.iloc[i, spy_df.columns.get_loc("close")] = 100.0 - (i - 9) * 2.0
    
    spy_df.attrs["symbol"] = "SPY"
    res = strategy.generate_signals(spy_df)

    assert "rsi_5" in res.columns
    assert "vix" in res.columns
    assert "signal" in res.columns

    # Verify BUY signal was generated at some point during the drop
    assert 1.0 in res["signal"].values
