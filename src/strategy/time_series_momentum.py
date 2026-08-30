"""Volatility-Scaled Time-Series Momentum (TSMOM) Strategy.

Implements the classic Moskowitz, Ooi, Pedersen / AQR multi-horizon trend-following
model with inverse-volatility risk target scaling to capture long-term momentum
while systematically reducing risk during market volatility spikes.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from src.indicators.ta_wrapper import ta
from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class VolatilityScaledTrendStrategy(BaseStrategy):
    """Multi-horizon time-series momentum with inverse-volatility risk targeting."""

    def __init__(self, name: str = "VolatilityScaledTrend", config: dict | None = None) -> None:
        """Initialize the TSMOM strategy.

        Args:
            name: Strategy name identifier.
            config: Configuration dictionary (lookbacks, vol target).
        """
        default_config = {
            "sma_trend_period": 200,
            "fast_momentum_period": 63,   # ~3 months
            "slow_momentum_period": 252,  # ~12 months
            "vol_lookback": 21,           # ~1 month realized volatility
            "target_annual_vol": 0.15,    # 15% annual target volatility
            "check_look_ahead": False,
        }
        if config:
            default_config.update(config)
        super().__init__(name, default_config)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate trend MA, multi-horizon returns, and rolling annualized volatility."""
        d = df.copy()
        c = d["close"]

        # 1. Long-term trend benchmark (200 SMA)
        sma_p = self.config.get("sma_trend_period", 200)
        d["sma_200"] = ta.sma(c, length=sma_p)

        # 2. Multi-horizon momentum returns
        fast_p = self.config.get("fast_momentum_period", 63)
        slow_p = self.config.get("slow_momentum_period", 252)
        d["ret_fast"] = c.pct_change(fast_p)
        d["ret_slow"] = c.pct_change(slow_p)

        # 3. Realized rolling daily volatility (annualized)
        vol_p = self.config.get("vol_lookback", 21)
        daily_returns = c.pct_change()
        rolling_std = daily_returns.rolling(vol_p).std()
        d["realized_ann_vol"] = rolling_std * np.sqrt(252)

        # 4. Volatility sizing scalar
        target_vol = self.config.get("target_annual_vol", 0.15)
        # Avoid division by zero
        safe_vol = d["realized_ann_vol"].fillna(target_vol).clip(lower=0.05)
        d["vol_scalar"] = (target_vol / safe_vol).clip(lower=0.2, upper=1.5)

        return d

    def setup_rules(self) -> None:
        """Register entry and exit rules for multi-horizon trend following."""
        def trend_following_rule(df: pd.DataFrame) -> pd.Series:
            c = df["close"]
            sma_200 = df["sma_200"]
            ret_fast = df["ret_fast"]
            ret_slow = df["ret_slow"]

            # Long entry: Price above 200 SMA AND positive 12m return AND positive 3m return
            long_cond = (c > sma_200) & (ret_slow > 0) & (ret_fast > 0)

            # Exit to Cash: Price drops below 200 SMA OR negative 12m return
            exit_cond = (c < sma_200) | (ret_slow < -0.02)

            signals = pd.Series(0, index=df.index, dtype=int)
            signals[long_cond] = 1
            signals[exit_cond] = -1
            return signals

        self.signal_generator.add_rule("tsmom_rule", trend_following_rule)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Calculate the initial stop loss price for VolatilityScaledTrendStrategy."""
        if "sma_200" in df.columns and idx < len(df):
            sma_val = df["sma_200"].iloc[idx]
            if pd.notna(sma_val) and sma_val > 0:
                return float(min(entry_price * 0.95, sma_val * 0.98))
        return float(entry_price * 0.95)
