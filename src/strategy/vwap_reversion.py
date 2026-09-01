"""Intraday Anchored Volume-Weighted Average Price (VWAP) Strategy.

Computes the session cumulative Volume-Weighted Average Price (VWAP) and its
associated standard deviation volatility bands (+/- 1.0 sigma, +/- 2.0 sigma) to capture:
1. High-probability mean-reversion bounces when price reaches oversold lower VWAP bands.
2. Trend-following momentum pullbacks to the session VWAP line.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from src.indicators.ta_wrapper import ta
from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class IntradayVWAPStrategy(BaseStrategy):
    """Institutional Intraday VWAP & Volatility Bands Strategy."""

    def __init__(self, name: str = "IntradayVWAP", config: dict | None = None) -> None:
        """Initialize the Intraday VWAP strategy.

        Args:
            name: Strategy name identifier.
            config: Configuration dictionary (band_mult, rsi_length, oversold_rsi).
        """
        default_config = {
            "band_mult": 1.5,            # Standard deviation multiplier for bands
            "rsi_length": 14,
            "rsi_oversold": 35.0,
            "rsi_overbought": 70.0,
            "atr_stop_mult": 1.5,
            "check_look_ahead": False,
        }
        if config:
            default_config.update(config)
        super().__init__(name, default_config)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate session-anchored VWAP, variance bands, RSI, and ATR."""
        d = df.copy()
        c = d["close"]
        h = d["high"]
        l = d["low"]
        v = d["volume"]

        band_mult = self.config.get("band_mult", 1.5)
        rsi_len = self.config.get("rsi_length", 14)

        # 1. 14-period RSI
        d["rsi_14"] = ta.rsi(c, length=rsi_len)

        # 2. 14-period ATR
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        d["atr_14"] = tr.rolling(14, min_periods=1).mean()

        # 3. Session Anchored Cumulative VWAP and Standard Deviation
        d["date"] = d.index.date if hasattr(d.index, "date") else pd.to_datetime(d.index).dt.date
        typical_price = (h + l + c) / 3.0
        pv = typical_price * v

        vwap_list = []
        upper_band_list = []
        lower_band_list = []

        for date, group in d.groupby("date", sort=False):
            grp_pv = pv.loc[group.index]
            grp_v = v.loc[group.index]
            grp_tp = typical_price.loc[group.index]

            cum_pv = grp_pv.cumsum()
            cum_v = grp_v.cumsum().replace(0, np.nan)
            session_vwap = cum_pv / cum_v

            # Volume-weighted variance
            sq_diff = (grp_tp - session_vwap) ** 2
            cum_sq_diff_v = (sq_diff * grp_v).cumsum()
            session_vwap_std = np.sqrt(cum_sq_diff_v / cum_v).fillna(0.0)

            upper_band = session_vwap + (band_mult * session_vwap_std)
            lower_band = session_vwap - (band_mult * session_vwap_std)

            vwap_list.extend(session_vwap.tolist())
            upper_band_list.extend(upper_band.tolist())
            lower_band_list.extend(lower_band.tolist())

        d["vwap"] = pd.Series(vwap_list, index=d.index).ffill()
        d["vwap_upper"] = pd.Series(upper_band_list, index=d.index).ffill()
        d["vwap_lower"] = pd.Series(lower_band_list, index=d.index).ffill()

        if "date" in d.columns:
            d.drop(columns=["date"], inplace=True)

        return d

    def setup_rules(self) -> None:
        """Register VWAP discount bounce and take-profit rules."""
        def vwap_reversion_rule(df: pd.DataFrame) -> pd.Series:
            c = df["close"]
            vwap = df["vwap"]
            vwap_lower = df["vwap_lower"]
            vwap_upper = df["vwap_upper"]
            rsi = df["rsi_14"]
            rsi_os = self.config.get("rsi_oversold", 35.0)
            rsi_ob = self.config.get("rsi_overbought", 70.0)

            # Long Entry: Price dips to or below Lower VWAP Band with oversold RSI (Institutional Discount)
            # OR bounces directly off rising VWAP in a trend
            long_cond = ((c <= vwap_lower * 1.002) & (rsi <= rsi_os)) | ((c > vwap) & (c.shift(1) <= vwap.shift(1)) & (rsi > 45.0) & (rsi < 65.0))

            # Exit / Take Profit: Price hits Upper VWAP Band OR RSI becomes overbought
            exit_cond = (c >= vwap_upper) | (rsi >= rsi_ob)

            signals = pd.Series(0, index=df.index, dtype=int)
            signals[long_cond] = 1
            signals[exit_cond] = -1
            return signals

        self.signal_generator.add_rule("vwap_reversion_rule", vwap_reversion_rule)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Calculate the initial stop loss price for Intraday VWAP (Lower Band - 1.0x ATR)."""
        stop_mult = self.config.get("atr_stop_mult", 1.5)
        if "atr_14" in df.columns and idx < len(df):
            atr_val = df["atr_14"].iloc[idx]
            if pd.notna(atr_val) and atr_val > 0:
                atr_stop = entry_price - (stop_mult * float(atr_val))
                if "vwap_lower" in df.columns:
                    lower_val = df["vwap_lower"].iloc[idx]
                    if pd.notna(lower_val) and lower_val > 0:
                        return float(min(atr_stop, lower_val * 0.995))
                return float(atr_stop)

        return float(entry_price * 0.985)
