"""Dual Momentum Strategy (Gary Antonacci GEM Model).

Combines absolute momentum (trend filter vs risk-free asset / 200 SMA) and
relative momentum (relative strength across index ETFs) to capture leading trends
while systematically rotating to defensive cash/Treasury assets in bear regimes.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from src.indicators.ta_wrapper import ta
from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class DualMomentumStrategy(BaseStrategy):
    """Dual Momentum model combining absolute trend filter and relative strength momentum."""

    def __init__(self, name: str = "DualMomentum", config: dict | None = None) -> None:
        """Initialize the Dual Momentum strategy.

        Args:
            name: Strategy name identifier.
            config: Configuration parameters (lookback period, moving average filter).
        """
        default_config = {
            "lookback_period": 252,       # 12-month momentum evaluation window
            "trend_ma_period": 200,       # 200-day trend confirmation filter
            "short_momentum_period": 63,  # 3-month secondary confirmation
            "check_look_ahead": False,
        }
        if config:
            default_config.update(config)
        super().__init__(name, default_config)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate 12-month return, 3-month return, 200 SMA, and relative strength."""
        d = df.copy()
        c = d["close"]

        lookback = self.config.get("lookback_period", 252)
        trend_p = self.config.get("trend_ma_period", 200)
        short_p = self.config.get("short_momentum_period", 63)

        # 1. Absolute momentum (12-month & 3-month returns)
        d["abs_mom_12m"] = c.pct_change(lookback)
        d["abs_mom_3m"] = c.pct_change(short_p)

        # 2. Long-term trend moving average
        d["trend_sma"] = ta.sma(c, length=trend_p)

        # 3. Normalized momentum score (composite)
        d["composite_mom"] = 0.70 * d["abs_mom_12m"].fillna(0) + 0.30 * d["abs_mom_3m"].fillna(0)

        return d

    def setup_rules(self) -> None:
        """Register dual momentum regime rules."""
        def dual_momentum_rule(df: pd.DataFrame) -> pd.Series:
            c = df["close"]
            sma = df["trend_sma"]
            mom_12m = df["abs_mom_12m"]
            comp_mom = df["composite_mom"]

            # Long condition: Positive absolute momentum AND price above 200 SMA AND positive composite score
            long_cond = (c > sma) & (mom_12m > 0.0) & (comp_mom > 0.0)

            # Defensive exit condition: Negative absolute momentum OR price below 200 SMA
            exit_cond = (c < sma) | (mom_12m < 0.0)

            signals = pd.Series(0, index=df.index, dtype=int)
            signals[long_cond] = 1
            signals[exit_cond] = -1
            return signals

        self.signal_generator.add_rule("dual_momentum_rule", dual_momentum_rule)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Calculate the initial stop loss price for DualMomentumStrategy."""
        if "trend_sma" in df.columns and idx < len(df):
            sma_val = df["trend_sma"].iloc[idx]
            if pd.notna(sma_val) and sma_val > 0:
                return float(min(entry_price * 0.95, sma_val * 0.98))
        return float(entry_price * 0.95)
