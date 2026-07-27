"""Backtest framework and statistical validation modules.
"""

from src.backtest.validation import (
    block_bootstrap,
    expected_max_sharpe,
    deflated_sharpe_ratio,
    holm_bonferroni_correction,
    check_red_flags,
)

__all__ = [
    "block_bootstrap",
    "expected_max_sharpe",
    "deflated_sharpe_ratio",
    "holm_bonferroni_correction",
    "check_red_flags",
]
