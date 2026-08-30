"""Transaction cost model for high-fidelity backtesting.

Implements spread, slippage, and regulatory fees (SEC, FINRA)
with support for VIX-conditioned spread widening.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np

from src.utils import get_logger

logger = get_logger(__name__)


class LiquidityTier(Enum):
    """Liquidity tiers for stocks to customize transaction cost assumptions."""
    MEGA_CAP = "mega_cap"      # SPY, QQQ, AAPL, MSFT
    LARGE_CAP = "large_cap"    # META, NVDA, JPM, etc.
    MID_CAP = "mid_cap"        # S&P 400 components
    SMALL_CAP = "small_cap"    # Below S&P 600


def spread_multiplier(vix: float) -> float:
    """Estimate spread widening factor based on VIX level.

    Args:
        vix: VIX index level.

    Returns:
        A multiplier factor >= 1.0.
    """
    if vix < 15.0:
        return 1.0
    elif vix < 25.0:
        return 1.0 + (vix - 15.0) * 0.05   # 1.0 to 1.5
    elif vix < 35.0:
        return 1.5 + (vix - 25.0) * 0.15   # 1.5 to 3.0
    else:
        return 3.0 + (vix - 35.0) * 0.10   # 3.0+


@dataclass
class CostModel:
    """Transaction cost model for backtesting.

    All cost rates in basis points (bps). 1 bps = 0.01% = 0.0001.
    """
    spread_bps: float       # Half-spread per side (bps)
    slippage_bps: float     # Fixed baseline slippage per side (bps)
    sec_fee_per_million: float = 8.00   # SEC fee on sells per million dollars
    finra_per_share: float = 0.000166   # FINRA TAF on sells per share
    market_impact_eta: float = 0.10     # Square-root market impact coefficient

    def calculate_market_impact_bps(
        self,
        shares: float,
        adv: float,
        daily_vol: float = 0.015,
    ) -> float:
        """Calculates non-linear square-root market impact in basis points.

        Formula: Impact (bps) = eta * daily_vol * sqrt(shares / ADV) * 10,000

        Args:
            shares: Order quantity in shares.
            adv: 20-day Average Daily Volume in shares.
            daily_vol: Daily asset return volatility (e.g. 0.015 for 1.5% daily vol).

        Returns:
            Market impact in basis points (bps).
        """
        if adv <= 0 or shares <= 0:
            return 0.0
        participation_rate = max(0.0, shares / adv)
        impact_pct = self.market_impact_eta * daily_vol * np.sqrt(participation_rate)
        return float(impact_pct * 10_000.0)

    def round_trip_cost_bps(self, vix: float | None = None) -> float:
        """Total round-trip cost in basis points, potentially VIX-conditioned.

        Args:
            vix: Optional VIX level. If not provided, assumes normal VIX (< 15).

        Returns:
            The round-trip cost in basis points.
        """
        mult = spread_multiplier(vix) if vix is not None else 1.0
        return 2.0 * (self.spread_bps * mult + self.slippage_bps)

    def round_trip_cost_dollars(self, notional: float, shares: float, vix: float | None = None) -> float:
        """Total round-trip cost in dollars for a given trade size.

        Args:
            notional: Notional value of the trade (shares * entry_price).
            shares: Number of shares traded.
            vix: Optional VIX level for spread widening.

        Returns:
            Total round-trip cost in USD.
        """
        spread_slip = notional * self.round_trip_cost_bps(vix) / 10_000.0
        sec = notional * self.sec_fee_per_million / 1_000_000.0  # Sell only
        finra = shares * self.finra_per_share                   # Sell only
        return spread_slip + sec + finra

    @classmethod
    def for_tier(cls, tier: LiquidityTier | str) -> CostModel:
        """Factory method: return cost model appropriate for liquidity tier.

        Args:
            tier: LiquidityTier enum or string representation.

        Returns:
            A CostModel instance configured for that tier.
        """
        if isinstance(tier, str):
            try:
                tier = LiquidityTier(tier.lower())
            except ValueError:
                logger.warning("Unknown tier name '%s', falling back to default.", tier)
                return cls.default()

        configs = {
            LiquidityTier.MEGA_CAP:  cls(spread_bps=1.0, slippage_bps=1.5),
            LiquidityTier.LARGE_CAP: cls(spread_bps=1.5, slippage_bps=2.5),
            LiquidityTier.MID_CAP:   cls(spread_bps=3.5, slippage_bps=4.0),
            LiquidityTier.SMALL_CAP: cls(spread_bps=7.5, slippage_bps=7.0),
        }
        return configs[tier]

    @classmethod
    def default(cls) -> CostModel:
        """Conservative default: 9 bps round-trip.

        RT = 2 * (1.5 spread + 3.0 slippage) = 9.0 bps.
        """
        return cls(spread_bps=1.5, slippage_bps=3.0)


@dataclass
class OptionCostModel:
    """Transaction cost model for option contracts.
    
    Option costs are calculated per contract side plus execution slippage
    (assumed to be 50% of the bid-ask spread away from the midpoint).
    """
    fee_per_contract: float = 0.65  # Standard retail option transaction fee
    slippage_fraction: float = 0.50 # Execute 50% of bid-ask spread away from midpoint (worst side)

    def calculate_cost(self, premium: float, contracts: int, bid: float, ask: float) -> float:
        """Calculates total trade transaction cost in USD (entry or exit)."""
        spread = max(0.0, ask - bid)
        slippage = (spread * self.slippage_fraction) * 100.0 * contracts
        fees = self.fee_per_contract * contracts
        return slippage + fees
