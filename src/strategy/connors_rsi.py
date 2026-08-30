"""Larry Connors 2-Period RSI Trend-Filtered Mean Reversion Strategy.

Identifies sharp, high-probability short-term pullbacks strictly within confirmed
long-term secular uptrends (Price > 200 SMA), targeting rapid mean reversion to the 5-day SMA.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from src.indicators.ta_wrapper import ta
from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class ConnorsMeanReversionStrategy(BaseStrategy):
    """Trend-filtered 2-period RSI mean-reversion strategy for liquid large-caps and index ETFs."""

    def __init__(self, name: str = "ConnorsMeanReversion", config: dict | None = None) -> None:
        """Initialize Connors Mean Reversion strategy.

        Args:
            name: Strategy name identifier.
            config: Configuration dictionary (rsi_length, oversold_threshold, exit_sma_length).
        """
        default_config = {
            "rsi_length": 2,              # Ultra short-term 2-day RSI
            "trend_ma_period": 200,       # 200-day trend gate
            "exit_sma_period": 5,         # 5-day mean reversion target
            "oversold_threshold": 10.0,   # RSI(2) < 10 for entry
            "overbought_exit": 70.0,      # RSI(2) > 70 for take profit
            "check_look_ahead": False,
        }
        if config:
            default_config.update(config)
        super().__init__(name, default_config)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate 2-period RSI, 200-day trend SMA, and 5-day exit SMA."""
        d = df.copy()
        c = d["close"]

        rsi_len = self.config.get("rsi_length", 2)
        trend_p = self.config.get("trend_ma_period", 200)
        exit_p = self.config.get("exit_sma_period", 5)

        # 1. 2-period RSI
        d["rsi_2"] = ta.rsi(c, length=rsi_len)

        # 2. 200-day trend confirmation filter
        d["sma_200"] = ta.sma(c, length=trend_p)

        # 3. 5-day exit SMA target
        d["sma_5"] = ta.sma(c, length=exit_p)

        return d

    def setup_rules(self) -> None:
        """Register entry and exit mean reversion rules."""
        def connors_reversion_rule(df: pd.DataFrame) -> pd.Series:
            c = df["close"]
            rsi = df["rsi_2"]
            sma_200 = df["sma_200"]
            sma_5 = df["sma_5"]

            os_thresh = self.config.get("oversold_threshold", 10.0)
            ob_thresh = self.config.get("overbought_exit", 70.0)

            # Long Entry: Strict bull trend (Price > 200 SMA) AND extreme oversold dip (RSI(2) < 10) AND Close < 5 SMA
            long_cond = (c > sma_200) & (rsi < os_thresh) & (c < sma_5)

            # Exit: Price recovers above 5 SMA OR RSI(2) reaches overbought territory
            exit_cond = (c > sma_5) | (rsi > ob_thresh) | (c < sma_200 * 0.95)

            signals = pd.Series(0, index=df.index, dtype=int)
            signals[long_cond] = 1
            signals[exit_cond] = -1
            return signals

        self.signal_generator.add_rule("connors_reversion_rule", connors_reversion_rule)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Calculate the initial stop loss price for ConnorsMeanReversionStrategy."""
        return float(entry_price * 0.97)
