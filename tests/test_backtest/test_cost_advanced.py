"""Unit tests for non-linear square-root market impact and cost modeling."""

import pytest
from src.backtest.cost import CostModel, LiquidityTier, OptionCostModel


def test_market_impact_calculation():
    """Verify non-linear square-root market impact scaling with order size and ADV."""
    model = CostModel(spread_bps=1.5, slippage_bps=2.5, market_impact_eta=0.10)
    
    # 10,000 shares on 1,000,000 ADV with 1.5% daily vol
    # participation_rate = 0.01 -> sqrt = 0.10 -> impact = 0.10 * 0.015 * 0.10 = 0.00015 = 1.5 bps
    impact_10k = model.calculate_market_impact_bps(shares=10_000, adv=1_000_000, daily_vol=0.015)
    assert pytest.approx(impact_10k, rel=1e-2) == 1.5

    # 40,000 shares (4x size) on same ADV -> participation = 0.04 -> sqrt = 0.20 -> impact = 3.0 bps (2x impact, non-linear!)
    impact_40k = model.calculate_market_impact_bps(shares=40_000, adv=1_000_000, daily_vol=0.015)
    assert pytest.approx(impact_40k, rel=1e-2) == 3.0
    assert pytest.approx(impact_40k, rel=1e-2) == 2.0 * impact_10k


def test_market_impact_zero_or_negative():
    """Verify zero impact for zero or invalid ADV / shares."""
    model = CostModel(spread_bps=1.5, slippage_bps=2.5)
    assert model.calculate_market_impact_bps(shares=0, adv=1_000_000) == 0.0
    assert model.calculate_market_impact_bps(shares=1000, adv=0) == 0.0


def test_option_cost_model():
    """Verify retail option transaction fee and half-spread slippage modeling."""
    opt_model = OptionCostModel(fee_per_contract=0.65, slippage_fraction=0.50)
    # 5 contracts with bid $2.00, ask $2.20 (spread = $0.20)
    # slippage = (0.20 * 0.50) * 100 * 5 = $50.00
    # fees = 5 * 0.65 = $3.25
    # total = $53.25
    cost = opt_model.calculate_cost(premium=2.10, contracts=5, bid=2.00, ask=2.20)
    assert pytest.approx(cost, rel=1e-2) == 53.25
