"""Implementations of the core systematic trading strategies for Sprint 3.

Contains:
    - MACrossoverStrategy: Trend-following Golden Cross / Death Cross.
    - RSIMeanReversionStrategy: Dip-buying using RSI and SMA filter.
    - BollingerSqueezeStrategy: Volatility expansion breakout after BB squeeze.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from src.strategy.base import BaseStrategy
from src.indicators.ta_wrapper import add_indicators
from src.strategy.smoothing import calculate_heikin_ashi, apply_kalman_filter
from src.strategy.indicators_math import calculate_hurst_exponent, calculate_vwap, add_pivot_points, calculate_linear_regression_bands, calculate_rolling_beta
from src.utils import get_logger

logger = get_logger(__name__)


def get_rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """Compute the rolling rank percentile of a Series over a given window.

    Handles NaNs gracefully and computes the percentile rank using Cython-accelerated
    vectorized pandas rolling rank.

    Args:
        series: The input pandas Series.
        window: The size of the rolling window.

    Returns:
        A pandas Series containing the rolling percentile values.
    """
    # Vectorized pandas rolling rank (pct=True returns range 0.0 to 1.0)
    rolling_min = series.rolling(window, min_periods=1).min()
    rolling_max = series.rolling(window, min_periods=1).max()
    
    ranks = series.rolling(window, min_periods=1).rank(pct=True) * 100.0
    # Where rolling window has zero variance, assign 0.0 to match custom logic
    ranks = ranks.where(rolling_min != rolling_max, 0.0)
    return ranks.fillna(0.0)


class MACrossoverStrategy(BaseStrategy):
    """Moving Average Crossover (Trend Following) strategy.

    Hypothesis:
        Equity prices exhibit momentum. A golden cross signals positive momentum,
        while a death cross signals trend exhaustion.

    Rules:
        - Long Entry: Fast SMA crosses above Slow SMA AND current price > Slow SMA.
        - Long Exit: Fast SMA crosses below Slow SMA.
        - Stops:
            - Hard loss stop: >5% drop from entry price.
            - Trailing stop: 2 * ATR below the maximum close since entry.
            - Time stop: >60 trading days with <2% gain.
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        """Initialize MACrossoverStrategy.

        Args:
            name: Unique identifier for this strategy.
            config: Configuration dictionary for parameters and signal combiners.
        """
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        self.fast_period = cfg.get("fast_period", 50)
        self.slow_period = cfg.get("slow_period", 200)
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Fast SMA, Slow SMA, and ATR indicators."""
        configs = [
            {"kind": "sma", "length": self.fast_period},
            {"kind": "sma", "length": self.slow_period},
            {"kind": "atr", "length": 14},
        ]
        return add_indicators(df, configs, overwrite=True)

    def setup_rules(self) -> None:
        """Register crossover and stop signal rules."""
        def rule_macrossover(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            close = d["close"]
            fast_col = f"sma_{self.fast_period}"
            slow_col = f"sma_{self.slow_period}"
            atr_col = "atr_14"

            if fast_col not in d.columns or slow_col not in d.columns:
                logger.warning("[%s] SMA columns not found. Returning neutral signals.", self.name)
                return signals

            sma_fast = d[fast_col]
            sma_slow = d[slow_col]
            atr = d[atr_col] if atr_col in d.columns else pd.Series(0.0, index=d.index)

            # Pre-calculate crossovers
            golden_cross = (sma_fast > sma_slow) & (sma_fast.shift(1) <= sma_slow.shift(1)) & (close > sma_slow)
            death_cross = (sma_fast < sma_slow) & (sma_fast.shift(1) >= sma_slow.shift(1))

            in_position = False
            entry_price = 0.0
            entry_idx = 0
            entry_atr = 0.0
            max_price_since_entry = 0.0

            for i in range(len(d)):
                if in_position:
                    current_close = close.iloc[i]
                    max_price_since_entry = max(max_price_since_entry, current_close)

                    # 1. Hard loss stop (>5% drop from entry)
                    hard_stop = current_close < entry_price * 0.95

                    # 2. Trailing stop (2 * ATR below max price since entry)
                    trailing_stop = current_close < (max_price_since_entry - 2.0 * entry_atr)

                    # 3. Time stop (>60 trading days with <2% gain)
                    time_stop = (i - entry_idx > 60) and (current_close < entry_price * 1.02)

                    # 4. Death cross core exit
                    core_exit = death_cross.iloc[i]

                    if hard_stop or trailing_stop or time_stop or core_exit:
                        signals.iloc[i] = -1
                        in_position = False
                else:
                    if golden_cross.iloc[i]:
                        signals.iloc[i] = 1
                        in_position = True
                        entry_price = close.iloc[i]
                        entry_idx = i
                        entry_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0.0
                        max_price_since_entry = entry_price

            return signals

        self.signal_generator.add_rule("macrossover", rule_macrossover)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Calculate the initial stop loss price for MACrossoverStrategy.

        Returns min(entry_price * 0.95, entry_price - 2.0 * atr) where atr is atr_14 at idx.
        """
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            return entry_price * 0.95
        return min(entry_price * 0.95, entry_price - 2.0 * float(atr_val))



class RSIMeanReversionStrategy(BaseStrategy):
    """RSI Mean Reversion (Pullback Trading) strategy.

    Hypothesis:
        Extreme short-term oversold readings indicate temporary pullbacks that tend
        to mean-revert back toward neutral levels within 2-10 days in a broader uptrend.

    Rules:
        - Long Entry: RSI crosses below oversold threshold AND price > SMA(200).
        - Long Exit: RSI crosses above 50 OR RSI crosses above overbought threshold.
        - Stops:
            - Hard loss stop: >3% drop from entry price.
            - Time stop: >10 trading days.
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        """Initialize RSIMeanReversionStrategy.

        Args:
            name: Unique identifier for this strategy.
            config: Configuration dictionary for parameters and signal combiners.
        """
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        self.rsi_period = cfg.get("rsi_period", 14)
        self.oversold_threshold = cfg.get("oversold_threshold", 30)
        self.overbought_threshold = cfg.get("overbought_threshold", 70)
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add RSI, SMA(200), and ATR indicators."""
        configs = [
            {"kind": "rsi", "length": self.rsi_period},
            {"kind": "sma", "length": 200},
            {"kind": "atr", "length": 14},
        ]
        return add_indicators(df, configs, overwrite=True)

    def setup_rules(self) -> None:
        """Register RSI entry and exit signal rules."""
        def rule_rsi_reversion(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            close = d["close"]
            rsi_col = f"rsi_{self.rsi_period}"
            sma_col = "sma_200"

            if rsi_col not in d.columns or sma_col not in d.columns:
                logger.warning("[%s] RSI or SMA_200 columns not found. Returning neutral signals.", self.name)
                return signals

            rsi = d[rsi_col]
            sma_200 = d[sma_col]

            # Entry: RSI crosses below oversold_threshold and price > SMA(200)
            rsi_cross_under = (rsi < self.oversold_threshold) & (rsi.shift(1) >= self.oversold_threshold)
            entry_cond = rsi_cross_under & (close > sma_200)

            # Exit: RSI crosses above 50 or overbought_threshold
            rsi_cross_above_50 = (rsi > 50) & (rsi.shift(1) <= 50)
            rsi_cross_above_ob = (rsi > self.overbought_threshold) & (rsi.shift(1) <= self.overbought_threshold)
            core_exit = rsi_cross_above_50 | rsi_cross_above_ob

            in_position = False
            entry_price = 0.0
            entry_idx = 0

            for i in range(len(d)):
                if in_position:
                    current_close = close.iloc[i]

                    # 1. Hard loss stop (>3% drop from entry)
                    hard_stop = current_close < entry_price * 0.97

                    # 2. Time stop (>10 trading days)
                    time_stop = (i - entry_idx > 10)

                    # 3. Core exit
                    exit_triggered = core_exit.iloc[i]

                    if hard_stop or time_stop or exit_triggered:
                        signals.iloc[i] = -1
                        in_position = False
                else:
                    if entry_cond.iloc[i]:
                        signals.iloc[i] = 1
                        in_position = True
                        entry_price = close.iloc[i]
                        entry_idx = i

            return signals

        self.signal_generator.add_rule("rsi_reversion", rule_rsi_reversion)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Calculate the initial stop loss price for RSIMeanReversionStrategy.

        Returns entry_price * 0.97.
        """
        return entry_price * 0.97



class BollingerSqueezeStrategy(BaseStrategy):
    """Bollinger Band Squeeze & Breakout strategy.

    Hypothesis:
        Periods of extremely low volatility (squeeze) cluster, followed by volatility expansion.
        A breakout above the upper BB on high volume indicates positive directional momentum.

    Rules:
        - Long Entry: BB Width is below squeeze_percentile percentile over squeeze_lookback AND
                      close breaks above upper BB AND volume >= 1.5x the 20-day Volume SMA.
        - Long Exit: Close breaks below middle BB (SMA 20).
        - Stops:
            - Hard loss stop: >4% drop from entry price.
            - Trailing stop: 1.5 * ATR below maximum close since entry.
            - Profit target: 2 * ATR above entry price.
            - Time stop: >20 trading days.
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        """Initialize BollingerSqueezeStrategy.

        Args:
            name: Unique identifier for this strategy.
            config: Configuration dictionary for parameters and signal combiners.
        """
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        self.bb_length = cfg.get("bb_length", 20)
        self.bb_std = cfg.get("bb_std", 2.0)
        self.squeeze_percentile = cfg.get("squeeze_percentile", 20)
        self.squeeze_lookback = cfg.get("squeeze_lookback", 252)
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Bollinger Bands, Volume SMA, ATR, and BB Width Percentile indicators."""
        df = df.copy()
        std_val = self.bb_std
        std_formatted = str(int(std_val)) if std_val == int(std_val) else str(std_val)

        # Compute Bollinger Bands and ATR
        configs = [
            {"kind": "bbands", "length": self.bb_length, "std": self.bb_std},
            {"kind": "atr", "length": 14},
        ]
        df = add_indicators(df, configs, overwrite=True)

        # Add Volume SMA
        df["volume_sma_20"] = df["volume"].rolling(20, min_periods=1).mean()

        # Add BB Width Percentile
        bb_width_col = f"bb_width_{self.bb_length}_{std_formatted}"
        if bb_width_col not in df.columns:
            upper_col = f"bb_upper_{self.bb_length}_{std_formatted}"
            lower_col = f"bb_lower_{self.bb_length}_{std_formatted}"
            middle_col = f"bb_middle_{self.bb_length}_{std_formatted}"

            if upper_col in df.columns and lower_col in df.columns and middle_col in df.columns:
                df[bb_width_col] = (df[upper_col] - df[lower_col]) / df[middle_col]
            else:
                df[bb_width_col] = pd.Series(np.nan, index=df.index)

        df["bb_width_pct"] = get_rolling_percentile(df[bb_width_col], self.squeeze_lookback)
        return df

    def setup_rules(self) -> None:
        """Register Bollinger Squeeze breakout and exit rules."""
        def rule_bb_squeeze(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            close = d["close"]
            volume = d["volume"]
            atr_col = "atr_14"

            std_val = self.bb_std
            std_formatted = str(int(std_val)) if std_val == int(std_val) else str(std_val)

            bb_upper_col = f"bb_upper_{self.bb_length}_{std_formatted}"
            bb_middle_col = f"bb_middle_{self.bb_length}_{std_formatted}"
            bb_width_pct_col = "bb_width_pct"
            vol_sma_col = "volume_sma_20"

            if (
                bb_upper_col not in d.columns
                or bb_middle_col not in d.columns
                or bb_width_pct_col not in d.columns
                or vol_sma_col not in d.columns
            ):
                logger.warning("[%s] Bollinger Bands or Volume indicators not found. Returning neutral signals.", self.name)
                return signals

            bb_upper = d[bb_upper_col]
            bb_middle = d[bb_middle_col]
            bb_width_pct = d[bb_width_pct_col]
            volume_sma_20 = d[vol_sma_col]
            atr = d[atr_col] if atr_col in d.columns else pd.Series(0.0, index=d.index)

            # Check if squeeze is active on current bar or was active on previous bar (to allow for breakout expansion)
            squeeze_active = (bb_width_pct < self.squeeze_percentile) | (bb_width_pct.shift(1) < self.squeeze_percentile)

            # Entry: Squeeze ACTIVE AND Close breaks upper BB AND Volume expansion
            entry_cond = (
                squeeze_active
                & (close > bb_upper)
                & (volume >= 1.5 * volume_sma_20)
            )

            # Exit: Close breaks below middle BB
            core_exit = close < bb_middle

            in_position = False
            entry_price = 0.0
            entry_idx = 0
            entry_atr = 0.0
            max_price_since_entry = 0.0

            for i in range(len(d)):
                if in_position:
                    current_close = close.iloc[i]
                    max_price_since_entry = max(max_price_since_entry, current_close)

                    # 1. Hard loss stop (>4% drop)
                    hard_stop = current_close < entry_price * 0.96

                    # 2. Trailing stop (1.5 * ATR below max price since entry)
                    trailing_stop = current_close < (max_price_since_entry - 1.5 * entry_atr)

                    # 3. Profit target (2 * ATR above entry price)
                    profit_target = current_close >= (entry_price + 2.0 * entry_atr)

                    # 4. Time stop (>20 trading days)
                    time_stop = (i - entry_idx > 20)

                    # 5. Core exit (close breaks below middle BB)
                    exit_triggered = core_exit.iloc[i]

                    if hard_stop or trailing_stop or profit_target or time_stop or exit_triggered:
                        signals.iloc[i] = -1
                        in_position = False
                else:
                    if entry_cond.iloc[i]:
                        signals.iloc[i] = 1
                        in_position = True
                        entry_price = close.iloc[i]
                        entry_idx = i
                        entry_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0.0
                        max_price_since_entry = entry_price

            return signals

        self.signal_generator.add_rule("bb_squeeze", rule_bb_squeeze)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Calculate the initial stop loss price for BollingerSqueezeStrategy.

        Returns min(entry_price * 0.96, entry_price - 1.5 * atr) where atr is atr_14 at idx.
        """
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            return entry_price * 0.96
        return min(entry_price * 0.96, entry_price - 1.5 * float(atr_val))


class IchimokuCloudStrategy(BaseStrategy):
    """Ichimoku Kinko Hyo (Trend Following) strategy with Hurst Exponent filter.

    Rules:
        - Long Entry: Close price above the Cloud (Span A/B) AND Tenkan-sen crosses above Kijun-sen AND Hurst > 0.5.
        - Long Exit: Price closes inside or below the Cloud, or Tenkan-sen crosses below Kijun-sen.
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        self.tenkan_period = cfg.get("tenkan_period", 9)
        self.kijun_period = cfg.get("kijun_period", 26)
        self.span_b_period = cfg.get("span_b_period", 52)
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        # Optionally apply Heikin-Ashi smoothing to price feed for noise reduction
        if self.config.get("smooth_heikin_ashi", True):
            ha_df = calculate_heikin_ashi(df)
            # Use smoothed prices for calculations
            df["open"] = ha_df["open"]
            df["high"] = ha_df["high"]
            df["low"] = ha_df["low"]
            df["close"] = ha_df["close"]

        # Calculate Conversion (Tenkan)
        high_9 = df["high"].rolling(window=self.tenkan_period).max()
        low_9 = df["low"].rolling(window=self.tenkan_period).min()
        df["tenkan"] = (high_9 + low_9) / 2.0

        # Calculate Base (Kijun)
        high_26 = df["high"].rolling(window=self.kijun_period).max()
        low_26 = df["low"].rolling(window=self.kijun_period).min()
        df["kijun"] = (high_26 + low_26) / 2.0

        # Calculate Spans (shifted 26 periods forward)
        df["span_a"] = ((df["tenkan"] + df["kijun"]) / 2.0).shift(26)
        high_52 = df["high"].rolling(window=self.span_b_period).max()
        low_52 = df["low"].rolling(window=self.span_b_period).min()
        df["span_b"] = ((high_52 + low_52) / 2.0).shift(26)

        # Calculate Hurst Exponent (rolling 50-day window)
        df["hurst"] = df["close"].rolling(50).apply(lambda x: calculate_hurst_exponent(x, max_lags=20), raw=False)
        df["hurst"] = df["hurst"].bfill().ffill().fillna(0.5)

        # Add ATR for stop loss
        configs = [{"kind": "atr", "length": 14}]
        df = add_indicators(df, configs, overwrite=True)
        return df

    def setup_rules(self) -> None:
        def rule_ichimoku(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            close = d["close"]
            tenkan = d["tenkan"]
            kijun = d["kijun"]
            span_a = d["span_a"]
            span_b = d["span_b"]
            hurst = d["hurst"]
            atr = d["atr_14"]

            in_position = False
            entry_price = 0.0
            entry_atr = 0.0

            for i in range(len(d)):
                # Avoid trading during early NaNs
                if pd.isna(span_a.iloc[i]) or pd.isna(span_b.iloc[i]) or pd.isna(tenkan.iloc[i]) or pd.isna(kijun.iloc[i]):
                    continue

                curr_close = close.iloc[i]
                cloud_top = max(span_a.iloc[i], span_b.iloc[i])
                cloud_bottom = min(span_a.iloc[i], span_b.iloc[i])

                if in_position:
                    # Trailing Stop: exit if price falls below cloud top or Tenkan crosses below Kijun
                    exit_cond = curr_close < cloud_top or tenkan.iloc[i] < kijun.iloc[i]
                    hard_stop = curr_close < (entry_price - 2.0 * entry_atr)
                    
                    if exit_cond or hard_stop:
                        signals.iloc[i] = -1
                        in_position = False
                else:
                    # Buy only when price is above cloud, Tenkan > Kijun, and market is trending (Hurst > 0.5)
                    entry_cond = curr_close > cloud_top and tenkan.iloc[i] > kijun.iloc[i] and hurst.iloc[i] > 0.5
                    if entry_cond:
                        signals.iloc[i] = 1
                        in_position = True
                        entry_price = curr_close
                        entry_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 1.0

            return signals

        self.signal_generator.add_rule("ichimoku_cloud", rule_ichimoku)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            return entry_price * 0.95
        return entry_price - 2.0 * float(atr_val)


class PivotPointReversionStrategy(BaseStrategy):
    """Pivot Point Reversion (Mean Reversion) strategy with Hurst Exponent filter.

    Rules:
        - Long Entry: Close crosses below Support Level 1 (S1) or Support Level 2 (S2) AND Hurst < 0.5.
        - Long Exit: Price crosses above Pivot Point (PP) or Resistance Level 1 (R1).
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        # Calculate Pivot levels (prev-bar shifted)
        df = add_pivot_points(df)

        # Calculate Hurst Exponent (rolling 50-day window)
        df["hurst"] = df["close"].rolling(50).apply(lambda x: calculate_hurst_exponent(x, max_lags=20), raw=False)
        df["hurst"] = df["hurst"].bfill().ffill().fillna(0.5)

        # Add ATR for stop loss
        configs = [{"kind": "atr", "length": 14}]
        df = add_indicators(df, configs, overwrite=True)
        return df

    def setup_rules(self) -> None:
        def rule_pivot_reversion(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            close = d["close"]
            pivot = d["pivot"]
            s1 = d["s1"]
            r1 = d["r1"]
            hurst = d["hurst"]
            atr = d["atr_14"]

            in_position = False
            entry_price = 0.0
            entry_atr = 0.0

            for i in range(len(d)):
                curr_close = close.iloc[i]

                if in_position:
                    # Profit target: exit if price crosses above the pivot or resistance R1
                    exit_cond = curr_close >= pivot.iloc[i] or curr_close >= r1.iloc[i]
                    hard_stop = curr_close < (entry_price - 1.5 * entry_atr)
                    
                    if exit_cond or hard_stop:
                        signals.iloc[i] = -1
                        in_position = False
                else:
                    # Buy when price dips below S1 and we are in a mean-reverting regime (Hurst < 0.5)
                    entry_cond = curr_close < s1.iloc[i] and hurst.iloc[i] < 0.5
                    if entry_cond:
                        signals.iloc[i] = 1
                        in_position = True
                        entry_price = curr_close
                        entry_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 1.0

            return signals

        self.signal_generator.add_rule("pivot_reversion", rule_pivot_reversion)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            return entry_price * 0.97
        return entry_price - 1.5 * float(atr_val)


class MACDHistogramStrategy(BaseStrategy):
    """MACD Histogram Divergence & Crossover Strategy.

    Hypothesis:
        Divergence and crossover of the MACD Histogram indicates changes in trend
        momentum. Crossing above 0 signifies early-stage positive trend establishment.

    Rules:
        - Long Entry: MACD Histogram crosses above 0.
        - Long Exit: MACD Histogram crosses below 0 OR MACD line crosses below Signal line.
        - Stops:
            - Initial Stop: 2 * ATR below entry price.
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        self.fast_period = cfg.get("fast_period", 12)
        self.slow_period = cfg.get("slow_period", 26)
        self.signal_period = cfg.get("signal_period", 9)
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        configs = [
            {"kind": "macd", "fast": self.fast_period, "slow": self.slow_period, "signal": self.signal_period},
            {"kind": "atr", "length": 14},
            {"kind": "adx", "length": 14},
        ]
        return add_indicators(df, configs, overwrite=True)

    def setup_rules(self) -> None:
        def rule_macd_hist(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            hist_col = f"macd_hist_{self.signal_period}"
            macd_col = f"macd_{self.fast_period}_{self.slow_period}"
            signal_col = f"macd_signal_{self.signal_period}"
            atr_col = "atr_14"

            if hist_col not in d.columns or macd_col not in d.columns or signal_col not in d.columns:
                logger.warning("[%s] MACD columns not found. Returning neutral signals.", self.name)
                return signals

            close = d["close"]
            macd_hist = d[hist_col]
            macd = d[macd_col]
            macd_signal = d[signal_col]
            atr = d[atr_col] if atr_col in d.columns else pd.Series(0.0, index=d.index)

            # Pre-calculate crossovers
            hist_cross_above = (macd_hist > 0) & (macd_hist.shift(1) <= 0)
            hist_cross_below = (macd_hist < 0) & (macd_hist.shift(1) >= 0)
            macd_cross_below = (macd < macd_signal) & (macd.shift(1) >= macd_signal.shift(1))

            in_position = False
            entry_price = 0.0
            entry_atr = 0.0

            for i in range(len(d)):
                if in_position:
                    current_close = close.iloc[i]
                    hard_stop = current_close < (entry_price - 2.0 * entry_atr)
                    core_exit = hist_cross_below.iloc[i] or macd_cross_below.iloc[i]

                    if hard_stop or core_exit:
                        signals.iloc[i] = -1
                        in_position = False
                else:
                    if hist_cross_above.iloc[i]:
                        signals.iloc[i] = 1
                        in_position = True
                        entry_price = close.iloc[i]
                        entry_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0.0

            return signals

        self.signal_generator.add_rule("macd_hist", rule_macd_hist)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            return entry_price * 0.95
        return entry_price - 2.0 * float(atr_val)


class DonchianChannelBreakoutStrategy(BaseStrategy):
    """Donchian Channel Breakout (Trend Following) strategy.

    Hypothesis:
        Buying breakouts of historical N-day price channels catches strong momentum,
        while crossing below the historical N-day low signals trend reversal.

    Rules:
        - Long Entry: Close price exceeds the highest high of the previous 20 bars.
        - Long Exit: Close price falls below the lowest low of the previous 20 bars.
        - Stops:
            - Initial Stop: 2 * ATR below entry price.
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        self.period = cfg.get("period", 20)
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # Compute Donchian Channel bands (shifted by 1 to prevent look-ahead bias)
        df["dc_upper"] = df["high"].shift(1).rolling(self.period).max()
        df["dc_lower"] = df["low"].shift(1).rolling(self.period).min()
        configs = [
            {"kind": "atr", "length": 14},
            {"kind": "adx", "length": 14},
        ]
        return add_indicators(df, configs, overwrite=True)

    def setup_rules(self) -> None:
        def rule_donchian(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            if "dc_upper" not in d.columns or "dc_lower" not in d.columns:
                logger.warning("[%s] Donchian columns not found. Returning neutral signals.", self.name)
                return signals

            close = d["close"]
            upper = d["dc_upper"]
            lower = d["dc_lower"]
            atr_col = "atr_14"
            atr = d[atr_col] if atr_col in d.columns else pd.Series(0.0, index=d.index)

            in_position = False
            entry_price = 0.0
            entry_atr = 0.0

            for i in range(len(d)):
                current_close = close.iloc[i]
                if in_position:
                    hard_stop = current_close < (entry_price - 2.0 * entry_atr)
                    core_exit = current_close < lower.iloc[i]

                    if hard_stop or core_exit:
                        signals.iloc[i] = -1
                        in_position = False
                else:
                    if current_close > upper.iloc[i] and not pd.isna(upper.iloc[i]):
                        signals.iloc[i] = 1
                        in_position = True
                        entry_price = current_close
                        entry_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0.0

            return signals

        self.signal_generator.add_rule("donchian_breakout", rule_donchian)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            return entry_price * 0.95
        return entry_price - 2.0 * float(atr_val)


class StochasticOscillatorStrategy(BaseStrategy):
    """Stochastic Oscillator (Momentum Reversal) strategy.

    Hypothesis:
        Extreme oversold levels accompanied by a bullish crossover in %K and %D
        indicate momentum exhaustion and key reversal entry points.

    Rules:
        - Long Entry: Both %K and %D are under 20, and %K crosses above %D.
        - Long Exit: Both %K and %D are over 80, and %K crosses below %D.
        - Stops:
            - Initial Stop: 1.5 * ATR below entry price.
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        self.k_period = cfg.get("k_period", 14)
        self.d_period = cfg.get("d_period", 3)
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        configs = [
            {"kind": "stoch", "k": self.k_period, "d": self.d_period},
            {"kind": "atr", "length": 14},
            {"kind": "adx", "length": 14},
        ]
        return add_indicators(df, configs, overwrite=True)

    def setup_rules(self) -> None:
        def rule_stochastic(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            if "stoch_k" not in d.columns or "stoch_d" not in d.columns:
                logger.warning("[%s] Stochastic columns not found. Returning neutral signals.", self.name)
                return signals

            close = d["close"]
            k = d["stoch_k"]
            d_val = d["stoch_d"]
            atr_col = "atr_14"
            atr = d[atr_col] if atr_col in d.columns else pd.Series(0.0, index=d.index)

            # Pre-calculate crossovers & zones
            oversold = (k < 20) & (d_val < 20)
            k_cross_above_d = (k > d_val) & (k.shift(1) <= d_val.shift(1))
            
            overbought = (k > 80) & (d_val > 80)
            k_cross_below_d = (k < d_val) & (k.shift(1) >= d_val.shift(1))

            in_position = False
            entry_price = 0.0
            entry_atr = 0.0

            for i in range(len(d)):
                current_close = close.iloc[i]
                if in_position:
                    hard_stop = current_close < (entry_price - 1.5 * entry_atr)
                    core_exit = overbought.iloc[i] and k_cross_below_d.iloc[i]

                    if hard_stop or core_exit:
                        signals.iloc[i] = -1
                        in_position = False
                else:
                    if oversold.iloc[i] and k_cross_above_d.iloc[i]:
                        signals.iloc[i] = 1
                        in_position = True
                        entry_price = current_close
                        entry_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0.0

            return signals

        self.signal_generator.add_rule("stochastic_oscillator", rule_stochastic)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            return entry_price * 0.95
        return entry_price - 1.5 * float(atr_val)


class ZScoreMeanReversionStrategy(BaseStrategy):
    """Z-Score Mean Reversion strategy.

    Hypothesis:
        Asset prices tend to revert to their rolling mean. When price deviates
        significantly (Z-score < -2.0), it represents a high-probability dip-buying opportunity.

    Rules:
        - Long Entry: Z-score crosses below -2.0.
        - Long Exit: Z-score crosses above 2.0 OR crosses back above 0.0 (mean reversion exit).
        - Stops:
            - Initial Stop: 1.5 * ATR below entry price.
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        self.period = cfg.get("period", 20)
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # Calculate rolling statistics on close price
        df["rolling_mean"] = df["close"].rolling(self.period).mean()
        df["rolling_std"] = df["close"].rolling(self.period).std()
        df["zscore"] = (df["close"] - df["rolling_mean"]) / np.where(df["rolling_std"] > 0, df["rolling_std"], 1e-6)
        
        configs = [
            {"kind": "atr", "length": 14},
            {"kind": "adx", "length": 14},
        ]
        return add_indicators(df, configs, overwrite=True)

    def setup_rules(self) -> None:
        def rule_zscore(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            if "zscore" not in d.columns:
                logger.warning("[%s] Z-Score column not found. Returning neutral signals.", self.name)
                return signals

            close = d["close"]
            z = d["zscore"]
            atr_col = "atr_14"
            atr = d[atr_col] if atr_col in d.columns else pd.Series(0.0, index=d.index)

            # Pre-calculate crossover conditions
            cross_below_entry = (z < -2.0) & (z.shift(1) >= -2.0)
            cross_above_exit = (z > 2.0) & (z.shift(1) <= 2.0)
            cross_above_mean = (z > 0.0) & (z.shift(1) <= 0.0)

            in_position = False
            entry_price = 0.0
            entry_atr = 0.0

            for i in range(len(d)):
                current_close = close.iloc[i]
                if in_position:
                    hard_stop = current_close < (entry_price - 1.5 * entry_atr)
                    core_exit = cross_above_exit.iloc[i] or cross_above_mean.iloc[i]

                    if hard_stop or core_exit:
                        signals.iloc[i] = -1
                        in_position = False
                else:
                    if cross_below_entry.iloc[i]:
                        signals.iloc[i] = 1
                        in_position = True
                        entry_price = current_close
                        entry_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0.0

            return signals

        self.signal_generator.add_rule("zscore_reversion", rule_zscore)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            return entry_price * 0.95
        return entry_price - 1.5 * float(atr_val)


class LinearRegressionChannelStrategy(BaseStrategy):
    """Linear Regression Channel (Mean Reversion) strategy.

    Hypothesis:
        Prices fluctuate around a linear trend projection. When price crosses
        below the -2 standard error lower channel boundary, it is excessively
        discounted relative to its trend and is primed for reversion.

    Rules:
        - Long Entry: Close price crosses below the lower linear regression band.
        - Long Exit: Close price crosses above the upper linear regression band.
        - Stops:
            - Initial Stop: 2 * ATR below entry price.
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        self.period = cfg.get("period", 30)
        self.num_std = cfg.get("num_std", 2.0)
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # Compute linear regression bands
        mid, upper, lower = calculate_linear_regression_bands(df["close"], self.period, self.num_std)
        df["lr_mid"] = mid
        df["lr_upper"] = upper
        df["lr_lower"] = lower
        
        configs = [
            {"kind": "atr", "length": 14},
            {"kind": "adx", "length": 14},
        ]
        return add_indicators(df, configs, overwrite=True)

    def setup_rules(self) -> None:
        def rule_lr_channel(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            if "lr_lower" not in d.columns or "lr_upper" not in d.columns:
                logger.warning("[%s] Linear Regression columns not found. Returning neutral signals.", self.name)
                return signals

            close = d["close"]
            lower = d["lr_lower"]
            upper = d["lr_upper"]
            atr_col = "atr_14"
            atr = d[atr_col] if atr_col in d.columns else pd.Series(0.0, index=d.index)

            # Pre-calculate crossovers
            cross_below_lower = (close < lower) & (close.shift(1) >= lower.shift(1))
            cross_above_upper = (close > upper) & (close.shift(1) <= upper.shift(1))

            in_position = False
            entry_price = 0.0
            entry_atr = 0.0

            for i in range(len(d)):
                current_close = close.iloc[i]
                if in_position:
                    hard_stop = current_close < (entry_price - 2.0 * entry_atr)
                    core_exit = cross_above_upper.iloc[i]

                    if hard_stop or core_exit:
                        signals.iloc[i] = -1
                        in_position = False
                else:
                    if cross_below_lower.iloc[i]:
                        signals.iloc[i] = 1
                        in_position = True
                        entry_price = current_close
                        entry_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0.0

            return signals

        self.signal_generator.add_rule("lr_channel", rule_lr_channel)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            return entry_price * 0.95
        return entry_price - 2.0 * float(atr_val)


class PairsTradingStrategy(BaseStrategy):
    """Statistical Arbitrage / Pairs Trading strategy.

    Hypothesis:
        Cointegrated asset pairs (e.g. JPM and BAC) have a stable, mean-reverting price spread.
        When the spread Z-score deviates significantly, we long the undervalued asset
        and short the overvalued asset, exiting when the spread reverts to the mean.

    Rules:
        - Spread = Price_A - beta * Price_B
        - If Z-score > 2.0: Sell A (short), Buy B (long)
        - If Z-score < -2.0: Buy A (long), Sell B (short)
        - Exit: Z-score reverts to 0.0.
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        cfg = config or {}
        cfg.setdefault("combine_mode", "any")
        self.lookback = cfg.get("lookback", 60)
        self.entry_threshold = cfg.get("entry_threshold", 2.0)
        self.exit_threshold = cfg.get("exit_threshold", 0.0)
        # Default correlated pairs
        self.pairs = cfg.get("pairs", [("JPM", "BAC"), ("PEP", "KO"), ("SPY", "QQQ")])
        super().__init__(name, cfg)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        symbol = df.attrs.get("symbol", "UNKNOWN").upper().strip()
        
        # Add ATR for position sizing
        configs = [
            {"kind": "atr", "length": 14},
            {"kind": "adx", "length": 14},
        ]
        df = add_indicators(df, configs, overwrite=True)

        matched_pair = None
        is_asset_a = True
        for pair in self.pairs:
            if symbol == pair[0].upper().strip():
                matched_pair = pair
                is_asset_a = True
                break
            elif symbol == pair[1].upper().strip():
                matched_pair = pair
                is_asset_a = False
                break

        if not matched_pair:
            df["pairs_zscore"] = 0.0
            df["is_asset_a"] = 0.0
            return df

        partner = matched_pair[1] if is_asset_a else matched_pair[0]

        from src.data.store import DataStore
        store = DataStore()
        df_partner = store.load(partner, tz="America/New_York")
        if df_partner is None or df_partner.empty:
            df["pairs_zscore"] = 0.0
            df["is_asset_a"] = 1.0 if is_asset_a else 0.0
            return df

        df_a = df if is_asset_a else df_partner
        df_b = df_partner if is_asset_a else df

        aligned = pd.concat([df_a["close"], df_b["close"]], axis=1, keys=["close_a", "close_b"]).dropna()
        if len(aligned) < self.lookback:
            df["pairs_zscore"] = 0.0
            df["is_asset_a"] = 1.0 if is_asset_a else 0.0
            return df

        # Calculate rolling beta (OLS of a on b)
        aligned["beta"] = calculate_rolling_beta(aligned["close_a"], aligned["close_b"], self.lookback)
        
        # Calculate spread: A - beta * B
        aligned["spread"] = aligned["close_a"] - aligned["beta"] * aligned["close_b"]
        aligned["spread_mean"] = aligned["spread"].rolling(self.lookback).mean()
        aligned["spread_std"] = aligned["spread"].rolling(self.lookback).std()
        
        # Calculate Z-score
        aligned["zscore"] = (aligned["spread"] - aligned["spread_mean"]) / np.where(aligned["spread_std"] > 0, aligned["spread_std"], 1e-6)

        df["pairs_zscore"] = aligned["zscore"].reindex(df.index).ffill().fillna(0.0)
        df["is_asset_a"] = 1.0 if is_asset_a else 0.0
        return df

    def setup_rules(self) -> None:
        def rule_pairs(d: pd.DataFrame) -> pd.Series:
            signals = pd.Series(0, index=d.index)
            if len(d) == 0:
                return signals

            if "pairs_zscore" not in d.columns:
                return signals

            z = d["pairs_zscore"].values
            is_a = bool(d["is_asset_a"].iloc[0]) if "is_asset_a" in d.columns else True

            # Entry/Exit thresholds
            entry_upper = self.entry_threshold
            entry_lower = -self.entry_threshold
            exit_val = self.exit_threshold

            in_position = 0  # 1 for long, -1 for short, 0 for neutral
            
            for i in range(1, len(d)):
                curr_z = z[i]
                prev_z = z[i - 1]
                
                if in_position == 1:
                    # Exit long: Z-score reverts to or crosses exit value
                    # For asset A: long entry was on z < -2. Exit on z >= 0
                    # For asset B: long entry was on z > 2. Exit on z <= 0
                    if is_a and curr_z >= exit_val:
                        signals.iloc[i] = -1
                        in_position = 0
                    elif not is_a and curr_z <= exit_val:
                        signals.iloc[i] = -1
                        in_position = 0
                elif in_position == -1:
                    # Exit short: Z-score reverts to or crosses exit value
                    # For asset A: short entry was on z > 2. Exit on z <= 0
                    # For asset B: short entry was on z < -2. Exit on z >= 0
                    if is_a and curr_z <= exit_val:
                        signals.iloc[i] = 1
                        in_position = 0
                    elif not is_a and curr_z >= exit_val:
                        signals.iloc[i] = 1
                        in_position = 0
                else:
                    # Entry logic
                    if curr_z < entry_lower and prev_z >= entry_lower:
                        # Spread underpriced -> Buy A, Sell B
                        signals.iloc[i] = 1 if is_a else -1
                        in_position = 1 if is_a else -1
                    elif curr_z > entry_upper and prev_z <= entry_upper:
                        # Spread overpriced -> Sell A, Buy B
                        signals.iloc[i] = -1 if is_a else 1
                        in_position = -1 if is_a else 1

            return signals

        self.signal_generator.add_rule("pairs_arbitrage", rule_pairs)

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        # Since this is a pairs trade, a standard ATR stop is used to protect individual legs from catastrophic events.
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else np.nan
        if pd.isna(atr_val) or atr_val <= 0:
            return entry_price * 0.95
        return entry_price - 2.0 * float(atr_val)


# Re-export new strategies from their respective files
from src.strategy.sector_momentum import SectorMomentumStrategy
from src.strategy.options_iv_runup import OptionsIVRunupStrategy
from src.strategy.breadth_reversion import BreadthThrustReversionStrategy



