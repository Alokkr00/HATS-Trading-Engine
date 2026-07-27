"""Market Regime Classifier module.

Classifies the market environment (using SPY/VIX) into trend and volatility
regimes to gate strategies and adjust position sizing.
"""

from __future__ import annotations

from enum import Enum
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class RegimeState(Enum):
    BULL_QUIET = "BULL_QUIET"          # Up-trend, low vol (ideal for trend/momentum)
    BULL_NORMAL = "BULL_NORMAL"        # Up-trend, normal vol (standard momentum)
    BULL_VOLATILE = "BULL_VOLATILE"    # Up-trend, high vol (mean-reversion longs, reduced size)
    BEAR_QUIET = "BEAR_QUIET"          # Down-trend, low vol (shorting / inverse ETFs)
    BEAR_NORMAL = "BEAR_NORMAL"        # Down-trend, normal vol (inverse ETFs)
    BEAR_VOLATILE = "BEAR_VOLATILE"    # Down-trend, high vol (mean-reversion longs/shorts, small size)
    RISK_OFF = "RISK_OFF"              # Market crisis (cash only, flatten positions)


class MarketRegimeClassifier:
    """Classifies global market regime using index trend and volatility metrics."""

    def __init__(
        self,
        vix_ticker: str = "^VIX",
        market_proxy: str = "SPY",
        low_vol_threshold: float = 16.0,
        high_vol_threshold: float = 25.0,
        crisis_vol_threshold: float = 35.0,
    ) -> None:
        """Initialize the regime classifier.

        Args:
            vix_ticker: Ticker for market volatility index.
            market_proxy: Ticker for trend proxy index.
            low_vol_threshold: VIX below this is low volatility.
            high_vol_threshold: VIX above this is high volatility.
            crisis_vol_threshold: VIX above this is a risk-off crisis.
        """
        self.vix_ticker = vix_ticker
        self.market_proxy = market_proxy
        self.low_vol_threshold = low_vol_threshold
        self.high_vol_threshold = high_vol_threshold
        self.crisis_vol_threshold = crisis_vol_threshold

    def classify(self, spy_df: pd.DataFrame, vix_value: float | None) -> dict:
        """Classify the current market regime.

        Args:
            spy_df: Historical OHLCV DataFrame for the market proxy (SPY).
            vix_value: Current spot VIX value. If None, defaults to normal volatility.

        Returns:
            A dict containing:
                - 'state': RegimeState Enum.
                - 'size_multiplier': float multiplier for position sizing (0.0 to 1.0).
                - 'allowed_actions': list of allowed side actions: ['BUY', 'SELL', 'INVERSE'].
        """
        if spy_df is None or spy_df.empty:
            logger.warning("Empty market proxy DataFrame. Defaulting to BULL_NORMAL regime.")
            return {
                "state": RegimeState.BULL_NORMAL,
                "size_multiplier": 1.0,
                "allowed_actions": ["BUY", "SELL"],
            }

        # Calculate SPY 200-day simple moving average
        close_series = spy_df["close"]
        if len(close_series) >= 200:
            spy_sma200 = float(close_series.rolling(200).mean().iloc[-1])
            spy_last = float(close_series.iloc[-1])
            is_bullish = spy_last >= spy_sma200
        else:
            # Fallback if history is insufficient
            logger.warning(
                f"Insufficient history for SPY trend calculation ({len(close_series)}/200 bars). "
                "Defaulting to bullish trend."
            )
            is_bullish = True

        # Volatility Classification
        vix = vix_value if vix_value is not None else 18.0

        if vix >= self.crisis_vol_threshold:
            state = RegimeState.RISK_OFF
        elif is_bullish:
            if vix < self.low_vol_threshold:
                state = RegimeState.BULL_QUIET
            elif vix < self.high_vol_threshold:
                state = RegimeState.BULL_NORMAL
            else:
                state = RegimeState.BULL_VOLATILE
        else:
            if vix < self.low_vol_threshold:
                state = RegimeState.BEAR_QUIET
            elif vix < self.high_vol_threshold:
                state = RegimeState.BEAR_NORMAL
            else:
                state = RegimeState.BEAR_VOLATILE

        # Determine size multiplier and allowed actions based on state
        if state == RegimeState.RISK_OFF:
            size_multiplier = 0.0
            allowed_actions = []
        elif state == RegimeState.BULL_QUIET:
            size_multiplier = 1.0
            allowed_actions = ["BUY", "SELL"]
        elif state == RegimeState.BULL_NORMAL:
            size_multiplier = 1.0
            allowed_actions = ["BUY", "SELL"]
        elif state == RegimeState.BULL_VOLATILE:
            size_multiplier = 0.5
            allowed_actions = ["BUY", "SELL"]
        elif state == RegimeState.BEAR_QUIET:
            size_multiplier = 0.75
            allowed_actions = ["SELL", "INVERSE"]
        elif state == RegimeState.BEAR_NORMAL:
            size_multiplier = 0.50
            allowed_actions = ["SELL", "INVERSE"]
        else:  # BEAR_VOLATILE
            size_multiplier = 0.25
            allowed_actions = ["SELL", "INVERSE"]

        return {
            "state": state,
            "size_multiplier": size_multiplier,
            "allowed_actions": allowed_actions,
            "vix": vix,
            "trend_bullish": is_bullish,
        }
