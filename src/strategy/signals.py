"""Composable signals engine for trading rule registration and aggregation.

This module provides the SignalGenerator class, which allows registering custom
signal rules, running them on an OHLCV DataFrame, validating them for look-ahead
bias, and combining them into a single execution signal.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict

import numpy as np
import pandas as pd

from src.utils import get_logger

logger = get_logger(__name__)


class SignalGenerator:
    """Generates and aggregates trading signals from rule-based strategies.

    Supports custom rule registration, strict look-ahead bias validation,
    and multiple signal aggregation modes ('any', 'all', 'majority', 'custom').

    Rules are expected to return integer signals:
        +1: BUY
        -1: SELL
         0: HOLD / NEUTRAL
    """

    def __init__(self) -> None:
        """Initialize the SignalGenerator."""
        self._rules: Dict[str, Callable[[pd.DataFrame], pd.Series]] = {}

    def add_rule(self, name: str, rule_func: Callable[[pd.DataFrame], pd.Series]) -> None:
        """Register a custom signal rule function.

        Args:
            name: Unique name for the rule.
            rule_func: Callable that takes an OHLCV DataFrame and returns a
                pandas Series of signals (-1, 0, or 1).

        Raises:
            ValueError: If the rule name is empty.
        """
        if not name:
            raise ValueError("Rule name cannot be empty.")
        if name in self._rules:
            logger.warning("Overwriting existing rule: %s", name)
        self._rules[name] = rule_func
        logger.info("Registered rule: %s", name)

    def _validate_signals(
        self, signals: pd.Series, name: str, expected_index: pd.Index
    ) -> pd.Series:
        """Validate that the signals series is formatted correctly.

        Args:
            signals: The pandas Series to validate.
            name: The name of the rule/combiner for error reporting.
            expected_index: The expected pandas Index of the output.

        Returns:
            A validated pandas Series containing only -1, 0, 1 (integers).

        Raises:
            TypeError: If the return type is not a pandas Series.
            ValueError: If the index does not match or values are invalid.
        """
        if not isinstance(signals, pd.Series):
            raise TypeError(
                f"Rule/Combiner '{name}' must return a pandas Series, got {type(signals)}."
            )

        if not signals.index.equals(expected_index):
            raise ValueError(
                f"Rule/Combiner '{name}' returned a Series with a different index than expected. "
                "Indices must match exactly to preserve timezone and alignment."
            )

        # Fill NaN with 0 (HOLD)
        filled = signals.fillna(0.0)

        # Check that values are only -1, 0, 1
        invalid_mask = ~filled.isin([-1, -1.0, 0, 0.0, 1, 1.0])
        if invalid_mask.any():
            invalid_vals = filled[invalid_mask].unique()
            raise ValueError(
                f"Rule/Combiner '{name}' returned invalid signal values: {list(invalid_vals)}. "
                "Signals must only be +1 (BUY), -1 (SELL), or 0 (HOLD)."
            )

        validated = filled.astype(np.int64)
        return validated

    def _combine_signals(
        self,
        sig_df: pd.DataFrame,
        combine_mode: str,
        custom_combiner: Callable[[pd.DataFrame], pd.Series] | None,
        conflict_resolution: str,
    ) -> pd.Series:
        """Combine individual rule signals into a single execution signal.

        Args:
            sig_df: DataFrame containing the individual rule signals (columns: sig_{rule_name}).
            combine_mode: Aggregation mode ('any', 'all', 'majority', 'custom').
            custom_combiner: A custom callable to combine signals if mode is 'custom'.
            conflict_resolution: Resolution strategy for 'any' mode ('hold', 'buy', 'sell').

        Returns:
            A pandas Series of the combined signal.

        Raises:
            ValueError: If combine_mode or conflict_resolution is invalid.
        """
        if combine_mode == "custom":
            if custom_combiner is None:
                raise ValueError(
                    "A custom_combiner callable must be provided when combine_mode is 'custom'."
                )
            return custom_combiner(sig_df)

        combined = pd.Series(0, index=sig_df.index, dtype=np.int64)

        if combine_mode == "any":
            has_buy = (sig_df == 1).any(axis=1)
            has_sell = (sig_df == -1).any(axis=1)
            conflict = has_buy & has_sell

            if conflict_resolution == "hold":
                combined[has_buy & ~conflict] = 1
                combined[has_sell & ~conflict] = -1
            elif conflict_resolution == "buy":
                combined[has_buy] = 1
                combined[has_sell & ~has_buy] = -1
            elif conflict_resolution == "sell":
                combined[has_sell] = -1
                combined[has_buy & ~has_sell] = 1
            else:
                raise ValueError(
                    f"Invalid conflict_resolution: '{conflict_resolution}'. "
                    "Must be one of 'hold', 'buy', 'sell'."
                )

        elif combine_mode == "all":
            all_buy = (sig_df == 1).all(axis=1)
            all_sell = (sig_df == -1).all(axis=1)
            combined[all_buy] = 1
            combined[all_sell] = -1

        elif combine_mode == "majority":
            num_buys = (sig_df == 1).sum(axis=1)
            num_sells = (sig_df == -1).sum(axis=1)
            num_holds = (sig_df == 0).sum(axis=1)

            max_votes = np.maximum(np.maximum(num_buys, num_sells), num_holds)

            # Strict majority wins (must have strictly more votes than any other option)
            buy_wins = (num_buys == max_votes) & (num_buys > num_sells) & (num_buys > num_holds)
            sell_wins = (num_sells == max_votes) & (num_sells > num_buys) & (num_sells > num_holds)

            combined[buy_wins] = 1
            combined[sell_wins] = -1

        else:
            raise ValueError(
                f"Invalid combine_mode: '{combine_mode}'. "
                "Must be one of 'any', 'all', 'majority', 'custom'."
            )

        return combined

    def _generate_internal(
        self,
        df: pd.DataFrame,
        combine_mode: str,
        custom_combiner: Callable[[pd.DataFrame], pd.Series] | None,
        conflict_resolution: str,
    ) -> pd.DataFrame:
        """Internal generation method without look-ahead checks.

        Args:
            df: Input OHLCV DataFrame.
            combine_mode: Aggregation mode ('any', 'all', 'majority', 'custom').
            custom_combiner: A custom callable to combine signals if mode is 'custom'.
            conflict_resolution: Resolution strategy for 'any' mode.

        Returns:
            DataFrame containing individual and combined signal columns.
        """
        if not self._rules:
            raise ValueError("No rules have been registered in the SignalGenerator.")

        res_df = df.copy()
        rule_signals = {}

        # Evaluate each rule
        for rule_name, rule_func in self._rules.items():
            rule_sig = rule_func(df)
            validated_sig = self._validate_signals(rule_sig, rule_name, df.index)
            res_df[f"sig_{rule_name}"] = validated_sig
            rule_signals[rule_name] = validated_sig

        # Combine signals
        sig_df = pd.DataFrame(
            {f"sig_{name}": sig for name, sig in rule_signals.items()},
            index=df.index,
        )
        combined_signal = self._combine_signals(
            sig_df,
            combine_mode=combine_mode,
            custom_combiner=custom_combiner,
            conflict_resolution=conflict_resolution,
        )

        res_df["signal"] = self._validate_signals(combined_signal, "combined", df.index)
        return res_df

    def _check_look_ahead_bias(
        self,
        df: pd.DataFrame,
        combine_mode: str,
        custom_combiner: Callable[[pd.DataFrame], pd.Series] | None,
        conflict_resolution: str,
    ) -> None:
        """Detect look-ahead bias in rules and aggregation.

        Evaluates rule functions on truncated inputs and compares overlaps to
        ensure outputs do not change with future data.

        Args:
            df: Input OHLCV DataFrame.
            combine_mode: Aggregation mode.
            custom_combiner: A custom callable to combine signals.
            conflict_resolution: Resolution strategy for 'any' mode.

        Raises:
            ValueError: If look-ahead bias is detected.
        """
        if len(df) < 5:
            logger.warning("DataFrame too short to perform look-ahead bias checks.")
            return

        # 1. Check individual rules first
        for rule_name, rule_func in self._rules.items():
            full_rule_sig = rule_func(df)

            for k in (1, 2, 3, 5):
                if len(df) <= k + 2:
                    continue
                df_trunc = df.iloc[:-k]
                trunc_rule_sig = rule_func(df_trunc)
                overlap_full = full_rule_sig.iloc[:-k]

                trunc_vals = trunc_rule_sig.fillna(0).astype(np.int64)
                overlap_vals = overlap_full.fillna(0).astype(np.int64)

                if not (trunc_vals == overlap_vals).all():
                    discrepancy_indices = trunc_vals[trunc_vals != overlap_vals].index
                    msg = (
                        f"Look-ahead bias detected in rule '{rule_name}'! "
                        f"Rule signal differs when trailing data is removed. "
                        f"Discrepancies found at index/indices: {list(discrepancy_indices[-5:])}."
                    )
                    logger.critical(msg)
                    raise ValueError(msg)

        # 2. Check the combined output end-to-end
        full_result = self._generate_internal(
            df,
            combine_mode=combine_mode,
            custom_combiner=custom_combiner,
            conflict_resolution=conflict_resolution,
        )
        full_signals = full_result["signal"]

        for k in (1, 2, 3, 5):
            if len(df) <= k + 2:
                continue

            df_trunc = df.iloc[:-k]
            trunc_result = self._generate_internal(
                df_trunc,
                combine_mode=combine_mode,
                custom_combiner=custom_combiner,
                conflict_resolution=conflict_resolution,
            )
            trunc_signals = trunc_result["signal"]
            overlap_full = full_signals.iloc[:-k]

            if not trunc_signals.index.equals(overlap_full.index):
                msg = "Signal generation altered the DataFrame index during truncation check."
                logger.critical(msg)
                raise ValueError(msg)

            trunc_vals = trunc_signals.fillna(0).astype(np.int64)
            overlap_vals = overlap_full.fillna(0).astype(np.int64)

            if not (trunc_vals == overlap_vals).all():
                discrepancy_indices = trunc_vals[trunc_vals != overlap_vals].index
                msg = (
                    f"Look-ahead bias detected in signal generation! "
                    f"Combined signal differs when trailing data is removed. "
                    f"Discrepancies found at index/indices: {list(discrepancy_indices[-5:])}."
                )
                logger.critical(msg)
                raise ValueError(msg)

    def generate(
        self,
        df: pd.DataFrame,
        combine_mode: str = "custom",
        custom_combiner: Callable[[pd.DataFrame], pd.Series] | None = None,
        conflict_resolution: str = "hold",
        check_look_ahead: bool = True,
    ) -> pd.DataFrame:
        """Evaluate all registered rules on the input DataFrame and combine them.

        The signal at index t represents the decision made at the close of bar t
        (to be executed at the open of bar t+1).

        Args:
            df: Input OHLCV DataFrame with enrichments/indicators.
            combine_mode: Aggregation mode ('any', 'all', 'majority', 'custom'). Defaults to 'custom'.
            custom_combiner: A custom callable to combine signals if mode is 'custom'.
            conflict_resolution: Conflict resolution strategy for 'any' mode ('hold', 'buy', 'sell').
                Defaults to 'hold'.
            check_look_ahead: Whether to run validation checks for look-ahead bias. Defaults to True.

        Returns:
            A copy of the input DataFrame with columns for individual rule signals
            (sig_{rule_name}) and a combined 'signal' column.

        Raises:
            ValueError: If no rules are registered or if look-ahead bias is detected.
        """
        if df.empty:
            logger.warning("Input DataFrame is empty. Returning empty DataFrame.")
            empty_df = df.copy()
            for rule_name in self._rules:
                empty_df[f"sig_{rule_name}"] = pd.Series(dtype=np.int64)
            empty_df["signal"] = pd.Series(dtype=np.int64)
            return empty_df

        if check_look_ahead:
            self._check_look_ahead_bias(
                df,
                combine_mode=combine_mode,
                custom_combiner=custom_combiner,
                conflict_resolution=conflict_resolution,
            )

        return self._generate_internal(
            df,
            combine_mode=combine_mode,
            custom_combiner=custom_combiner,
            conflict_resolution=conflict_resolution,
        )
