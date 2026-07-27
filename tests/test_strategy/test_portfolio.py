"""Unit tests for the PositionSizer class."""

from __future__ import annotations

import pytest
from src.strategy.portfolio import PositionSizer


class MockPosition:
    """Mock position class for testing object-based attributes."""

    def __init__(self, sector: str, weight: float) -> None:
        self.sector = sector
        self.weight = weight


def test_calculate_size_normal() -> None:
    """Test position size calculations under normal market and risk conditions."""
    sizer = PositionSizer()

    # Normal case 1: Capped by max position value (10% of equity)
    # Account: 100k, 1% risk = $1,000, 10% max weight = $10,000
    # Entry: $100, Stop: $95 (Stop distance: $5)
    # Target shares based on risk: 1000 / 5 = 200 shares ($20,000 notional)
    # Target shares based on max size: 10000 / 100 = 100 shares ($10,000 notional)
    # Expected result: 100 shares (capped)
    res = sizer.calculate_size(
        account_equity=100000.0,
        entry_price=100.0,
        stop_price=95.0,
    )
    assert res["shares"] == 100
    assert res["notional_value"] == 10000.0
    # Actual risk = 100 shares * $5 = $500. $500 / 100k = 0.005 (0.5%)
    assert res["risk_pct"] == pytest.approx(0.005)

    # Normal case 2: Uncapped (limited purely by 1% risk)
    # Account: 100k, 1% risk = $1,000, 10% max weight = $10,000
    # Entry: $100, Stop: $80 (Stop distance: $20)
    # Target shares based on risk: 1000 / 20 = 50 shares ($5,000 notional)
    # Target shares based on max size: 10000 / 100 = 100 shares ($10,000 notional)
    # Expected result: 50 shares
    res = sizer.calculate_size(
        account_equity=100000.0,
        entry_price=100.0,
        stop_price=80.0,
    )
    assert res["shares"] == 50
    assert res["notional_value"] == 5000.0
    # Actual risk = 50 shares * $20 = $1,000. $1000 / 100k = 0.01 (1.0%)
    assert res["risk_pct"] == pytest.approx(0.01)


def test_calculate_size_extreme() -> None:
    """Test position size calculations under extreme/boundary conditions."""
    sizer = PositionSizer()

    # Extreme case 1: Zero stop distance (entry_price == stop_price)
    res = sizer.calculate_size(
        account_equity=100000.0,
        entry_price=100.0,
        stop_price=100.0,
    )
    assert res["shares"] == 0
    assert res["notional_value"] == 0.0
    assert res["risk_pct"] == 0.0

    # Extreme case 2: Extremely tight stop (high raw shares count, capped by max weight)
    # Entry: $100, Stop: $99.99 (Stop distance: $0.01)
    # Raw shares = 1000 / 0.01 = 100,000 shares
    # Max shares = 10,000 / 100 = 100 shares
    # Expected result: 100 shares (capped)
    res = sizer.calculate_size(
        account_equity=100000.0,
        entry_price=100.0,
        stop_price=99.99,
    )
    assert res["shares"] == 100
    assert res["notional_value"] == 10000.0
    # Actual risk = 100 shares * max(0.01, 3.0) = $300.00. $300 / 100k = 0.003
    assert res["risk_pct"] == pytest.approx(0.003)

    # Extreme case 3: Extremely wide stop
    # Entry: $100, Stop: $0.0 (Stop distance: $100)
    # Raw shares = 1000 / 100 = 10 shares
    # Expected result: 10 shares
    res = sizer.calculate_size(
        account_equity=100000.0,
        entry_price=100.0,
        stop_price=0.0,
    )
    assert res["shares"] == 10
    assert res["notional_value"] == 1000.0
    assert res["risk_pct"] == pytest.approx(0.01)

    # Extreme case 4: Fractional shares rounding down to 0
    # Account: 10,000, 1% risk = $100
    # Entry: $100, Stop: $10 (Stop distance: $90)
    # Raw shares = 100 / 90 = 1.11 shares
    # Expected result: 1 share
    res1 = sizer.calculate_size(
        account_equity=10000.0,
        entry_price=100.0,
        stop_price=10.0,
    )
    assert res1["shares"] == 1
    assert res1["notional_value"] == 100.0
    assert res1["risk_pct"] == pytest.approx(90.0 / 10000.0)

    # Entry: $1,000, Stop: $100 (Stop distance: $900)
    # Raw shares = 100 / 900 = 0.11 shares
    # Expected result: 0 shares (rounded down)
    res2 = sizer.calculate_size(
        account_equity=10000.0,
        entry_price=1000.0,
        stop_price=100.0,
    )
    assert res2["shares"] == 0
    assert res2["notional_value"] == 0.0
    assert res2["risk_pct"] == 0.0


def test_calculate_size_invalid_inputs() -> None:
    """Test position sizer handles invalid parameter inputs gracefully."""
    sizer = PositionSizer()

    # Zero/Negative Account Equity
    assert sizer.calculate_size(0.0, 100.0, 95.0)["shares"] == 0
    assert sizer.calculate_size(-500.0, 100.0, 95.0)["shares"] == 0

    # Zero/Negative Entry Price
    assert sizer.calculate_size(100000.0, 0.0, 95.0)["shares"] == 0
    assert sizer.calculate_size(100000.0, -10.0, 95.0)["shares"] == 0

    # Negative Stop Price
    assert sizer.calculate_size(100000.0, 100.0, -5.0)["shares"] == 0


def test_calculate_size_options_delta() -> None:
    """Test options position sizing scaled by Delta."""
    sizer = PositionSizer()

    # ATM option with delta = 0.50
    # Account: 100k, 1% risk = 1000. Max allocation = 10,000.
    # Option Entry Premium: 5.0, Stop: 2.5 (Stop distance: 2.5)
    # Multiplier: 100
    # Stop distance cost with delta = 2.5 * 100 * 0.5 = 125.
    # Expected size = 1000 / 125 = 8 contracts.
    res = sizer.calculate_size(
        account_equity=100000.0,
        entry_price=5.0,
        stop_price=2.5,
        is_option=True,
        delta=0.50
    )
    assert res["shares"] == 8
    assert res["notional_value"] == 4000.0  # 8 * 5.0 * 100
    assert res["risk_pct"] == pytest.approx(0.01)  # 8 * 2.5 * 100 * 0.5 = 1000 risk (1.0%)

    # Deep ITM option with delta = 1.0
    # Expected size = 1000 / (2.5 * 100 * 1.0) = 4 contracts.
    res_itm = sizer.calculate_size(
        account_equity=100000.0,
        entry_price=5.0,
        stop_price=2.5,
        is_option=True,
        delta=1.00
    )
    assert res_itm["shares"] == 4
    assert res_itm["notional_value"] == 2000.0
    assert res_itm["risk_pct"] == pytest.approx(0.01)


def test_check_portfolio_limits_positions_count() -> None:
    """Test portfolio sizer enforces max 6 concurrent positions constraint."""
    sizer = PositionSizer()

    # 5 existing positions — new one should be allowed
    positions_5 = [{"sector": "Technology", "weight": 0.05} for _ in range(5)]
    assert sizer.check_portfolio_limits(positions_5, "Finance", new_trade_weight=0.05) is True

    # 6 existing positions — new one should be rejected
    positions_6 = [{"sector": "Technology", "weight": 0.05} for _ in range(6)]
    assert sizer.check_portfolio_limits(positions_6, "Finance", new_trade_weight=0.05) is False

    # More than 6 existing positions — new one should be rejected
    positions_7 = [{"sector": "Technology", "weight": 0.05} for _ in range(7)]
    assert sizer.check_portfolio_limits(positions_7, "Finance", new_trade_weight=0.05) is False


def test_check_portfolio_limits_sector_exposure_dict() -> None:
    """Test portfolio sizer enforces max 25% sector exposure using dictionary positions."""
    sizer = PositionSizer()

    # Normal case: existing sector weight = 15%, adding 10% new trade = 25% (allowed)
    positions_ok = [
        {"sector": "Technology", "weight": 0.10},
        {"sector": "Technology", "weight": 0.05},
        {"sector": "Energy", "weight": 0.10},
    ]
    assert sizer.check_portfolio_limits(positions_ok, "Technology", new_trade_weight=0.10) is True

    # Exceeding case: existing sector weight = 20%, adding 10% new trade = 30% (rejected)
    positions_exceed = [
        {"sector": "Technology", "weight": 0.10},
        {"sector": "Technology", "weight": 0.10},
        {"sector": "Energy", "weight": 0.05},
    ]
    assert sizer.check_portfolio_limits(positions_exceed, "Technology", new_trade_weight=0.10) is False

    # Default weight behavior: if new_trade_weight is None, defaults to 0.10
    # Tech sector has 20% weight already. Adding a default 10% weight trade makes it 30% (rejected)
    assert sizer.check_portfolio_limits(positions_exceed, "Technology") is False

    # tech sector has 10% weight. Adding default 10% weight trade makes it 20% (allowed)
    positions_low = [{"sector": "Technology", "weight": 0.10}]
    assert sizer.check_portfolio_limits(positions_low, "Technology") is True


def test_check_portfolio_limits_sector_exposure_object() -> None:
    """Test portfolio sizer enforces sector concentration using object-based positions."""
    sizer = PositionSizer()

    # Tech sector: 10% + 5% = 15%. Adding new trade with weight 10% = 25% (allowed)
    positions_ok = [
        MockPosition(sector="Technology", weight=0.10),
        MockPosition(sector="Technology", weight=0.05),
        MockPosition(sector="Energy", weight=0.10),
    ]
    assert sizer.check_portfolio_limits(positions_ok, "Technology", new_trade_weight=0.10) is True

    # Tech sector: 10% + 10% = 20%. Adding new trade with weight 10% = 30% (rejected)
    positions_exceed = [
        MockPosition(sector="Technology", weight=0.10),
        MockPosition(sector="Technology", weight=0.10),
        MockPosition(sector="Energy", weight=0.05),
    ]
    assert sizer.check_portfolio_limits(positions_exceed, "Technology", new_trade_weight=0.10) is False


def test_check_portfolio_limits_fallback_weight() -> None:
    """Test portfolio sizer handles positions missing weight but having percent or no weight attributes."""
    sizer = PositionSizer()

    # Position using percent instead of weight: 10% + 10% = 20%. Add 5% = 25% (allowed)
    positions_percent = [
        {"sector": "Technology", "percent": 10.0},
        {"sector": "Technology", "percent": 10.0},
    ]
    assert sizer.check_portfolio_limits(positions_percent, "Technology", new_trade_weight=0.05) is True
    assert sizer.check_portfolio_limits(positions_percent, "Technology", new_trade_weight=0.06) is False

    # Position with no weight/percent at all. Should fallback to default weight (0.10)
    positions_no_weight = [
        {"sector": "Technology"},
        {"sector": "Technology"},
    ]
    # Sum of existing Tech is 0.10 + 0.10 = 0.20. Adding 5% = 25% (allowed)
    assert sizer.check_portfolio_limits(positions_no_weight, "Technology", new_trade_weight=0.05) is True
    # Adding 6% = 26% (rejected)
    assert sizer.check_portfolio_limits(positions_no_weight, "Technology", new_trade_weight=0.06) is False


def test_calculate_size_with_slippage() -> None:
    """Test that position sizer successfully factors slippage buffer into trade sizing."""
    sizer = PositionSizer()

    # Account: 100k, 1% risk = $1,000, 10% max weight = $10,000
    # Entry: $100, Stop: $80
    # Without slippage: stop distance = $20, raw shares = 50.
    # With 100 bps slippage: entry price is $100, slippage penalty = $100 * 0.01 = $1.00.
    # Adjusted stop distance = $20 + $1 = $21.
    # Raw shares = 1000 / 21 = 47.62 -> 47 shares.
    res = sizer.calculate_size(
        account_equity=100000.0,
        entry_price=100.0,
        stop_price=80.0,
        slippage_bps=100.0,
    )
    assert res["shares"] == 47
    assert res["notional_value"] == 4700.0

