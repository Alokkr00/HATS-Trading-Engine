"""Opening Range Breakout (ORB) Strategy for Intraday Equities and Index ETFs.

Implements the classical Toby Crabel / Linda Raschke Opening Range Breakout model:
1. Calculates the High and Low of the initial session window (e.g. first 15m / 30m after 9:30 AM ET).
2. Triggers Long on breakout above Opening Range High with relative volume confirmation.
3. Automatically manages risk with ATR-based stops and session close time-based flattening.
"""

from __future__ import annotations

import logging
import datetime as dt
import numpy as np
import pandas as pd

from src.indicators.ta_wrapper import ta
from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """Institutional Opening Range Breakout (ORB) model for 5m, 15m, and 30m intraday bars."""

    def __init__(self, name: str = "OpeningRangeBreakout", config: dict | None = None) -> None:
        """Initialize the ORB strategy.

        Args:
            name: Strategy name identifier.
            config: Configuration dictionary (opening_minutes, volume_mult, atr_mult).
        """
        default_config = {
            "opening_bars": 2,            # Number of opening bars that define the range (2 * 15m = 30m range)
            "volume_threshold_mult": 1.2, # Volume expansion factor vs 20-period volume MA
            "atr_period": 14,
            "atr_stop_mult": 1.5,
            "check_look_ahead": False,
        }
        if config:
            default_config.update(config)
        super().__init__(name, default_config)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate session opening range high/low, volume average, and ATR."""
        d = df.copy()
        c = d["close"]
        h = d["high"]
        l = d["low"]
        v = d["volume"]

        atr_p = self.config.get("atr_period", 14)
        opening_bars = self.config.get("opening_bars", 2)

        # 1. 14-period ATR for volatility-scaled stops
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        d["atr_14"] = tr.rolling(atr_p, min_periods=1).mean()

        # 2. Volume moving average
        d["vol_sma_20"] = v.rolling(20, min_periods=1).mean()

        # 3. Session Opening Range High / Low tracking
        # Group by trading date
        d["date"] = d.index.date if hasattr(d.index, "date") else pd.to_datetime(d.index).dt.date
        
        # Calculate opening range per session
        orb_highs = []
        orb_lows = []
        orb_mids = []

        for date, group in d.groupby("date", sort=False):
            n_bars = min(len(group), opening_bars)
            session_open_high = group["high"].iloc[:n_bars].max()
            session_open_low = group["low"].iloc[:n_bars].min()
            session_mid = (session_open_high + session_open_low) / 2.0

            orb_highs.extend([session_open_high] * len(group))
            orb_lows.extend([session_open_low] * len(group))
            orb_mids.extend([session_mid] * len(group))

        d["orb_high"] = pd.Series(orb_highs, index=d.index)
        d["orb_low"] = pd.Series(orb_lows, index=d.index)
        d["orb_mid"] = pd.Series(orb_mids, index=d.index)
        
        if "date" in d.columns:
            d.drop(columns=["date"], inplace=True)

        return d

    def setup_rules(self) -> None:
        """Register ORB breakout and risk rules."""
        def orb_breakout_rule(df: pd.DataFrame) -> pd.Series:
            c = df["close"]
            orb_high = df["orb_high"]
            orb_mid = df["orb_mid"]
            orb_low = df["orb_low"]
            vol = df["volume"]
            vol_sma = df["vol_sma_20"]
            vol_mult = self.config.get("volume_threshold_mult", 1.2)

            # Long Entry: Close breaks above Opening Range High with volume confirmation
            long_cond = (c > orb_high) & (vol >= vol_sma * vol_mult)

            # Exit: Price drops back below the opening range midpoint or breaks low
            exit_cond = (c < orb_mid) | (c < orb_low)

            signals = pd.Series(0, index=df.index, dtype=int)
            signals[long_cond] = 1
            signals[exit_cond] = -1
            return signals

        self.signal_generator.add_rule("orb_breakout_rule", orb_breakout_rule)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Calculate the initial stop loss price for ORB (Opening Midpoint or 1.5x ATR)."""
        stop_mult = self.config.get("atr_stop_mult", 1.5)
        if "atr_14" in df.columns and idx < len(df):
            atr_val = df["atr_14"].iloc[idx]
            if pd.notna(atr_val) and atr_val > 0:
                atr_stop = entry_price - (stop_mult * float(atr_val))
                if "orb_mid" in df.columns:
                    mid_val = df["orb_mid"].iloc[idx]
                    if pd.notna(mid_val) and mid_val > 0:
                        return float(max(mid_val, atr_stop))
                return float(atr_stop)

        return float(entry_price * 0.985)
