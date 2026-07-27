"""Base Strategy class for developing and executing trading strategies.

Provides the abstract base class that all strategies must inherit from,
ensuring consistent interfaces, proper logging, timezone checking,
and look-ahead bias validation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import pandas as pd

from src.strategy.signals import SignalGenerator
from src.utils import get_logger

logger = get_logger(__name__)


class BaseStrategy(ABC):
    """Abstract base class for all algorithmic trading strategies.

    This class coordinates technical indicator calculations, registers signal rules,
    performs index validation (e.g. timezone checks), and triggers the composable
    signals engine (with look-ahead bias checks).
    """

    def __init__(self, name: str, config: dict | None = None) -> None:
        """Initialize the BaseStrategy.

        Args:
            name: Unique name identifying the strategy.
            config: Optional configuration dictionary.
        """
        self.name = name
        self.config = config or {}
        self.signal_generator = SignalGenerator()
        self.setup_rules()

    @abstractmethod
    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators to the input OHLCV DataFrame.

        Must be implemented by concrete subclasses to compute technical indicator
        columns (e.g. SMA, RSI, ATR) on the DataFrame.

        Args:
            df: Input OHLCV DataFrame.

        Returns:
            A copy of the DataFrame with calculated indicator columns.
        """
        pass

    @abstractmethod
    def setup_rules(self) -> None:
        """Register the strategy's signal rules with self.signal_generator.

        Must be implemented by concrete subclasses. Typically calls
        `self.signal_generator.add_rule()` for each rule function.
        """
        pass

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Main execution entrypoint for generating signals.

        Validates the timezone of the index, computes the required indicators,
        evaluates all registered rules, and performs look-ahead bias checks.

        Args:
            df: Input OHLCV DataFrame.

        Returns:
            A copy of the DataFrame with indicator columns, individual rule signals,
            and the aggregated 'signal' column.

        Raises:
            ValueError: If the DataFrame index is not DatetimeIndex, is not timezone-aware,
                or if look-ahead bias validation fails.
        """
        if df.empty:
            logger.warning("[%s] Empty DataFrame passed to generate_signals. Returning empty df.", self.name)
            return self.signal_generator.generate(df, check_look_ahead=False)

        # Timezone checks
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError(
                f"[{self.name}] Input DataFrame index must be a pandas DatetimeIndex, "
                f"got {type(df.index).__name__}."
            )
        if df.index.tz is None:
            raise ValueError(
                f"[{self.name}] DatetimeIndex is naive. A timezone-aware DatetimeIndex "
                "is required for signal generation to prevent look-ahead bias and alignment issues."
            )

        logger.debug("[%s] Timezone check passed. Index timezone is: %s", self.name, df.index.tz)

        # Apply strategy indicators
        df_indicators = self.add_indicators(df)

        # Retrieve rule aggregation settings from config
        combine_mode = self.config.get("combine_mode", "any")
        conflict_resolution = self.config.get("conflict_resolution", "hold")
        custom_combiner = self.config.get("custom_combiner", None)
        check_look_ahead = self.config.get("check_look_ahead", True)

        # Run registered rules & combine signals
        res_df = self.signal_generator.generate(
            df_indicators,
            combine_mode=combine_mode,
            custom_combiner=custom_combiner,
            conflict_resolution=conflict_resolution,
            check_look_ahead=check_look_ahead,
        )

        # Apply ADX trend filter overlay if enabled
        if self.config.get("use_adx_filter", True):
            adx_cols = [c for c in res_df.columns if c.lower().startswith("adx")]
            if adx_cols:
                adx_col = adx_cols[0]
                adx_threshold = self.config.get("adx_filter_threshold", 20.0)
                mask_trendless = res_df[adx_col] < adx_threshold
                
                # Neutralize signals when trend strength is weak (ADX < threshold)
                res_df.loc[mask_trendless, "signal"] = 0
                for col in res_df.columns:
                    if col.startswith("sig_"):
                        res_df.loc[mask_trendless, col] = 0
                logger.debug("[%s] ADX filter neutralized %d bars (ADX < %.1f)", self.name, mask_trendless.sum(), adx_threshold)

        return res_df

    def get_initial_stop_price(self, df: pd.DataFrame, idx: int, entry_price: float) -> float:
        """Calculate the initial stop loss price for a trade.

        Must be implemented by concrete subclasses.

        Args:
            df: The strategy DataFrame containing technical indicators.
            idx: The integer index of the entry signal.
            entry_price: The price at which the position is entered.

        Returns:
            The stop loss price.
        """
        raise NotImplementedError("Subclasses must implement get_initial_stop_price")

