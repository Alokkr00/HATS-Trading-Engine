"""Breadth Thrust Mean Reversion Strategy.

Identifies high-conviction oversold market bottoms using index RSI(5)
and volatility (VIX) spikes, entering long SPY or QQQ positions for a short-term bounce.
"""

from __future__ import annotations

import logging
import pandas as pd
import numpy as np

from src.strategy.base import BaseStrategy
from src.data.store import DataStore
from src.data.exceptions import StoreError

logger = logging.getLogger(__name__)


class BreadthThrustReversionStrategy(BaseStrategy):
    """Buys SPY or QQQ on extreme breadth selloffs and volatility spikes."""

    def __init__(self, name: str, config: dict | None = None) -> None:
        """Initialize BreadthThrustReversionStrategy."""
        config = config or {}
        self.rsi_period = config.get("rsi_period", 5)
        self.oversold_threshold = config.get("oversold_threshold", 20.0)
        self.overbought_threshold = config.get("overbought_threshold", 60.0)
        self.vix_threshold = config.get("vix_threshold", 20.0)
        self.time_stop = config.get("time_stop", 10)
        self.store = DataStore()
        super().__init__(name, config)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators for oversold breadth and VIX.

        Args:
            df: Input OHLCV DataFrame.

        Returns:
            DataFrame with 'rsi_5', 'vix', and 'atr_14'.
        """
        df = df.copy()

        # 1. Calculate RSI(5)
        close = df["close"]
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()
        rs = gain / (loss + 1e-9)
        df["rsi_5"] = 100 - (100 / (1 + rs))
        df["rsi_5"] = df["rsi_5"].fillna(50.0)

        # 2. Add ATR(14)
        high = df["high"]
        low = df["low"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        df["atr_14"] = tr.rolling(14).mean().fillna(close * 0.02)

        # 3. Add VIX data
        df["vix"] = self.vix_threshold  # Default to threshold if not found
        try:
            vix_df = self.store.load("^VIX", tz="US/Eastern")
            if not vix_df.empty:
                vix_df = vix_df.reindex(df.index).ffill().bfill()
                df["vix"] = vix_df["close"].fillna(self.vix_threshold)
        except StoreError:
            logger.warning("VIX data not found in store for BreadthThrustReversion. Using default VIX threshold.")

        return df

    def setup_rules(self) -> None:
        """Register breadth thrust rules."""
        self.signal_generator.add_rule("breadth_reversion", self._rule_reversion)

    def _rule_reversion(self, df: pd.DataFrame) -> pd.Series:
        """Rule: Buy when RSI(5) < 20 and VIX > 20. Exit when RSI(5) > 60."""
        signals = pd.Series(0.0, index=df.index)
        symbol = df.attrs.get("symbol", "UNKNOWN").upper().strip()

        # Only trade SPY and QQQ
        if symbol not in ["SPY", "QQQ"]:
            return signals

        if "rsi_5" not in df.columns or "vix" not in df.columns:
            return signals

        rsi = df["rsi_5"].values
        vix = df["vix"].values
        n_bars = len(df)

        in_position = False
        bars_since_entry = 0

        for i in range(1, n_bars):
            if in_position:
                bars_since_entry += 1
                # Exit conditions
                is_overbought = rsi[i] >= self.overbought_threshold
                is_time_stop = bars_since_entry >= self.time_stop

                if is_overbought or is_time_stop:
                    signals.iloc[i] = -1.0
                    in_position = False
                    bars_since_entry = 0
            else:
                # Entry condition: RSI < 20 and VIX > 20
                is_oversold = rsi[i] < self.oversold_threshold
                is_vix_spike = vix[i] > self.vix_threshold

                if is_oversold and is_vix_spike:
                    signals.iloc[i] = 1.0
                    in_position = True
                    bars_since_entry = 0

        return signals

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Wider stop for high-conviction oversold: 3% below entry or 2 * ATR."""
        atr_val = float(df["atr_14"].iloc[idx])
        stop_dist = max(entry_price * 0.03, 2.0 * atr_val)
        return entry_price - stop_dist
