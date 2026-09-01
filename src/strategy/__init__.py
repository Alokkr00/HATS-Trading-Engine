"""Strategy module containing signal generation and aggregation rules.

Exports:
    SignalGenerator: Aggregates custom trading rules into executable signals.
    BaseStrategy: Abstract base class for strategy implementations.
    PositionSizer: Risk-based sizing and portfolio allocation rules.
    MACrossoverStrategy: Trend-following crossover strategy.
    RSIMeanReversionStrategy: Mean reversion dip buying strategy.
    BollingerSqueezeStrategy: Bollinger Band squeeze breakout strategy.
"""

from src.strategy.signals import SignalGenerator
from src.strategy.base import BaseStrategy
from src.strategy.portfolio import PositionSizer
from src.strategy.strategies import (
    MACrossoverStrategy,
    RSIMeanReversionStrategy,
    BollingerSqueezeStrategy,
    IchimokuCloudStrategy,
    PivotPointReversionStrategy,
)
from src.strategy.dual_momentum import DualMomentumStrategy
from src.strategy.time_series_momentum import VolatilityScaledTrendStrategy
from src.strategy.connors_rsi import ConnorsMeanReversionStrategy
from src.strategy.opening_range_breakout import OpeningRangeBreakoutStrategy
from src.strategy.vwap_reversion import IntradayVWAPStrategy
from src.strategy.option_selector import select_option

__all__ = [
    "SignalGenerator",
    "BaseStrategy",
    "PositionSizer",
    "MACrossoverStrategy",
    "RSIMeanReversionStrategy",
    "BollingerSqueezeStrategy",
    "IchimokuCloudStrategy",
    "PivotPointReversionStrategy",
    "DualMomentumStrategy",
    "VolatilityScaledTrendStrategy",
    "ConnorsMeanReversionStrategy",
    "OpeningRangeBreakoutStrategy",
    "IntradayVWAPStrategy",
    "select_option",
]
