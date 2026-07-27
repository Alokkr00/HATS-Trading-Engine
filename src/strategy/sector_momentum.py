"""Sector Momentum Rotation Strategy.

Ranks the 11 SPDR Sector ETFs by rolling returns and selects the top 3 sectors
for long positions, rebalancing periodically.
"""

from __future__ import annotations

import logging
import pandas as pd
import numpy as np

from src.strategy.base import BaseStrategy
from src.data.store import DataStore
from src.data.exceptions import StoreError

logger = logging.getLogger(__name__)


class SectorMomentumStrategy(BaseStrategy):
    """Goes long the top 3 performing sectors over a rolling lookback period.

    Rebalances every N trading days (default 20).
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        """Initialize SectorMomentumStrategy."""
        self.sectors = [
            "XLK", "XLF", "XLV", "XLY", "XLP",
            "XLE", "XLI", "XLB", "XLRE", "XLU", "XLC"
        ]
        # Set lookback and rebalance periods
        config = config or {}
        self.lookback = config.get("lookback", 40)
        self.rebalance_period = config.get("rebalance_period", 20)
        self.store = DataStore()
        super().__init__(name, config)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Technical Indicators.

        For sector momentum, we calculate rolling returns and ranks across all
        sector ETFs.

        Args:
            df: Input OHLCV DataFrame for the current symbol.

        Returns:
            DataFrame with 'sector_rank' and 'atr_14'.
        """
        df = df.copy()
        symbol = df.attrs.get("symbol", "UNKNOWN").upper().strip()

        # Add ATR for stop loss calculation
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        df["atr_14"] = tr.rolling(14).mean().fillna(close * 0.02)

        # Default rank to lowest if not a sector ETF or if we fail to load others
        df["sector_rank"] = len(self.sectors)

        if symbol not in self.sectors:
            return df

        # Load close prices for all sectors to compute relative rankings
        sector_closes = {}
        for sec in self.sectors:
            try:
                sec_df = self.store.load(sec, tz="US/Eastern")
                if not sec_df.empty:
                    # Align index to current df index
                    sec_df = sec_df.reindex(df.index).ffill().bfill()
                    sector_closes[sec] = sec_df["close"]
            except StoreError:
                # If sector ETF data is missing, we skip it
                logger.warning(f"Sector data for {sec} not found in store.")
                continue

        if len(sector_closes) < 3:
            logger.warning("Not enough sector data to rank. Skipping ranking.")
            return df

        # Create a DataFrame of all sector closes
        closes_df = pd.DataFrame(sector_closes)

        # Compute rolling returns
        returns_df = closes_df.pct_change(self.lookback).fillna(0.0)

        # Rank returns across columns (1 is best, higher is worse)
        ranks_df = returns_df.rank(axis=1, ascending=False)

        # Store the current symbol's rank in df
        if symbol in ranks_df.columns:
            df["sector_rank"] = ranks_df[symbol]

        return df

    def setup_rules(self) -> None:
        """Register the momentum rules."""
        self.signal_generator.add_rule("momentum_rank", self._rule_momentum)

    def _rule_momentum(self, df: pd.DataFrame) -> pd.Series:
        """Rule: Buy if sector rank is in top 3 on rebalance day, exit otherwise."""
        signals = pd.Series(0.0, index=df.index)
        symbol = df.attrs.get("symbol", "UNKNOWN").upper().strip()

        if symbol not in self.sectors or "sector_rank" not in df.columns:
            return signals

        ranks = df["sector_rank"].values
        n_bars = len(df)

        # Start generating signals after lookback
        in_position = False
        for i in range(self.lookback, n_bars):
            # Check if this is a rebalance day
            is_rebalance = (i % self.rebalance_period == 0)

            if is_rebalance:
                rank = ranks[i]
                if rank <= 3.0:
                    signals.iloc[i] = 1.0
                    in_position = True
                else:
                    signals.iloc[i] = -1.0 if in_position else 0.0
                    in_position = False
            else:
                # Hold previous signal/position state
                signals.iloc[i] = 0.0

        return signals

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Use ATR-based stop price (e.g. 2.5 * ATR below entry)."""
        atr_val = float(df["atr_14"].iloc[idx])
        return entry_price - 2.5 * atr_val
