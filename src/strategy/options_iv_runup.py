"""Options IV Run-up Strategy.

Buys ATM Call options 10-14 days before a scheduled earnings announcement to
exploit the pre-earnings rise in Implied Volatility (IV), and exits the trade
1-2 days before the earnings date to avoid overnight gap risk.
"""

from __future__ import annotations

import logging
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class OptionsIVRunupStrategy(BaseStrategy):
    """Buys options before earnings to capture vega expansion and momentum."""

    def __init__(self, name: str, config: dict | None = None) -> None:
        """Initialize the strategy."""
        super().__init__(name, config)
        self.entry_days_before = self.config.get("entry_days_before", 10)
        self.exit_days_before = self.config.get("exit_days_before", 1)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate indicators and identify upcoming earnings proximity.

        Args:
            df: Input OHLCV DataFrame.

        Returns:
            DataFrame with 'days_to_earnings' and 'atr_14'.
        """
        df = df.copy()
        symbol = df.attrs.get("symbol", "UNKNOWN").upper().strip()

        # Add ATR for risk sizing
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        df["atr_14"] = tr.rolling(14).mean().fillna(close * 0.02)

        # Default days_to_earnings to a large number
        df["days_to_earnings"] = 999.0

        if symbol == "UNKNOWN":
            return df

        # Fetch all historical and upcoming earnings dates
        earnings_dates = self._get_all_earnings_dates(symbol)
        if not earnings_dates:
            return df

        # Calculate calendar days from each bar's timestamp to the next earnings date
        days_diffs = []
        for idx in df.index:
            # Strip timezone to compare dates
            bar_date = idx.to_pydatetime().date()
            future_earnings = [e for e in earnings_dates if e > bar_date]
            if future_earnings:
                next_earnings = min(future_earnings)
                diff = (next_earnings - bar_date).days
                days_diffs.append(float(diff))
            else:
                days_diffs.append(999.0)

        df["days_to_earnings"] = pd.Series(days_diffs, index=df.index)
        return df

    def setup_rules(self) -> None:
        """Register the pre-earnings rules."""
        self.signal_generator.add_rule("iv_runup", self._rule_iv_runup)

    def _rule_iv_runup(self, df: pd.DataFrame) -> pd.Series:
        """Rule: Enter 10 days before earnings, exit 1 day before earnings."""
        signals = pd.Series(0.0, index=df.index)
        if "days_to_earnings" not in df.columns:
            return signals

        days_to_earnings = df["days_to_earnings"].values
        in_position = False

        for i in range(len(df)):
            days = days_to_earnings[i]
            # Enter window: between 14 days and entry_days_before (e.g. 10 days)
            if not in_position and self.exit_days_before < days <= self.entry_days_before:
                signals.iloc[i] = 1.0
                in_position = True
            # Exit window: days to earnings <= exit_days_before (e.g. 1 day)
            elif in_position and days <= self.exit_days_before:
                signals.iloc[i] = -1.0
                in_position = False
            else:
                signals.iloc[i] = 0.0

        return signals

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Calculate stop price for equity (share) trades using 2x ATR below entry.

        Note: When this strategy trades options, main.py uses opt_stop_price = premium * 0.5
        instead. This method is only called for equity (share) trades, so we use a
        sensible ATR-based stop rather than the 50%-of-price nonsense.
        """
        atr_col = "atr_14"
        atr_val = df[atr_col].iloc[idx] if atr_col in df.columns else float("nan")
        if pd.isna(atr_val) or atr_val <= 0:
            # Fallback: 5% below entry
            return entry_price * 0.95
        # 2x ATR stop, capped at 8% max loss
        atr_stop = entry_price - 2.0 * float(atr_val)
        pct_stop = entry_price * 0.92
        return max(atr_stop, pct_stop)

    def _get_all_earnings_dates(self, symbol: str) -> list[date]:
        """Fetch all historical and upcoming earnings dates from yfinance."""
        dates = []
        try:
            ticker = yf.Ticker(symbol)
            # 1. Historical earnings dates
            try:
                earnings_df = ticker.earnings_dates
                if earnings_df is not None and not earnings_df.empty:
                    for idx in earnings_df.index:
                        if isinstance(idx, (datetime, pd.Timestamp)):
                            dates.append(idx.date())
                        elif isinstance(idx, str):
                            try:
                                dates.append(pd.Timestamp(idx).date())
                            except Exception:
                                pass
            except Exception:
                pass
            
            # 2. Upcoming earnings dates
            try:
                calendar = ticker.calendar
                if calendar is not None and not calendar.empty:
                    if "Earnings Date" in calendar.index:
                        dates_list = calendar.loc["Earnings Date"].values[0]
                        if isinstance(dates_list, list):
                            for d in dates_list:
                                if isinstance(d, (datetime, pd.Timestamp)):
                                    dates.append(d.date())
                        elif isinstance(dates_list, (datetime, pd.Timestamp)):
                            dates.append(dates_list.date())
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Failed to fetch earnings for {symbol}: {e}")

        # Remove duplicates and return sorted list
        return sorted(list(set(dates)))
