"""Technical indicators module.

Provides wrappers over pandas-ta to easily add technical indicators to DataFrames.
"""

from src.indicators.ta_wrapper import add_indicators, add_standard_indicators

__all__ = [
    "add_indicators",
    "add_standard_indicators",
]
