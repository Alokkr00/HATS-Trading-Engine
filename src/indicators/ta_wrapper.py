"""Technical indicators wrapper for computing indicators on OHLCV DataFrames.

Provides functions to compute technical indicators using pandas-ta with standardized,
lowercase naming conventions, preserving original indexes and timezones.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pandas_ta as ta  # noqa: F401

from src.utils import get_logger

logger = get_logger(__name__)


def add_indicators(
    df: pd.DataFrame,
    configs: list[dict[str, Any]],
    overwrite: bool = False,
) -> pd.DataFrame:
    """Computes technical indicators on a copy of the input OHLCV DataFrame.

    Supports SMA, EMA, RSI, MACD, Bollinger Bands, and ATR.

    Args:
        df: Input DataFrame. Must contain standard OHLCV columns (lowercase:
            'open', 'high', 'low', 'close', 'volume').
        configs: List of indicator configurations. Each config is a dict with
            at least 'kind' (or 'indicator') and parameters:
            - SMA: {'kind': 'sma', 'length': int}
            - EMA: {'kind': 'ema', 'length': int}
            - RSI: {'kind': 'rsi', 'length': int}
            - MACD: {'kind': 'macd', 'fast': int, 'slow': int, 'signal': int}
            - Bollinger Bands: {'kind': 'bbands', 'length': int, 'std': float}
            - ATR: {'kind': 'atr', 'length': int}
        overwrite: If True, overwrites existing columns in df. If False, skips
            computation and logs a warning for colliding columns.

    Returns:
        A copy of the DataFrame with computed indicator columns appended.
    """
    result_df = df.copy()

    # Verify input DataFrame is not empty
    if result_df.empty:
        logger.warning("Empty DataFrame passed to add_indicators. Returning copy.")
        return result_df

    # Check for expected OHLCV columns
    required_cols = ["open", "high", "low", "close", "volume"]
    missing_cols = [col for col in required_cols if col not in result_df.columns]
    if missing_cols:
        logger.warning(
            "Input DataFrame is missing standard OHLCV columns: %s. "
            "Computation may fail or be incomplete.",
            missing_cols,
        )

    for config in configs:
        kind = config.get("kind", config.get("indicator", ""))
        if not isinstance(kind, str) or not kind:
            logger.warning("Invalid config: missing or invalid 'kind' key: %s", config)
            continue

        kind = kind.lower().strip()

        try:
            if kind == "sma":
                length = config.get("length", 50)
                if len(result_df) < length:
                    logger.warning(
                        "Input DataFrame length %d is less than the required lookback %d for SMA.",
                        len(result_df),
                        length,
                    )

                col_name = f"sma_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning(
                        "Column '%s' already exists in DataFrame and overwrite=False. Skipping.",
                        col_name,
                    )
                    continue

                sma_series = result_df.ta.sma(length=length)
                result_df[col_name] = sma_series

            elif kind == "ema":
                length = config.get("length", 10)
                if len(result_df) < length:
                    logger.warning(
                        "Input DataFrame length %d is less than the required lookback %d for EMA.",
                        len(result_df),
                        length,
                    )

                col_name = f"ema_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning(
                        "Column '%s' already exists in DataFrame and overwrite=False. Skipping.",
                        col_name,
                    )
                    continue

                ema_series = result_df.ta.ema(length=length)
                result_df[col_name] = ema_series

            elif kind == "rsi":
                length = config.get("length", 14)
                if len(result_df) < length:
                    logger.warning(
                        "Input DataFrame length %d is less than the required lookback %d for RSI.",
                        len(result_df),
                        length,
                    )

                col_name = f"rsi_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning(
                        "Column '%s' already exists in DataFrame and overwrite=False. Skipping.",
                        col_name,
                    )
                    continue

                rsi_series = result_df.ta.rsi(length=length)
                result_df[col_name] = rsi_series

            elif kind == "atr":
                length = config.get("length", 14)
                if len(result_df) < length:
                    logger.warning(
                        "Input DataFrame length %d is less than the required lookback %d for ATR.",
                        len(result_df),
                        length,
                    )

                col_name = f"atr_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning(
                        "Column '%s' already exists in DataFrame and overwrite=False. Skipping.",
                        col_name,
                    )
                    continue

                atr_series = result_df.ta.atr(length=length)
                result_df[col_name] = atr_series

            elif kind == "macd":
                fast = config.get("fast", 12)
                slow = config.get("slow", 26)
                signal = config.get("signal", 9)

                max_lookback = max(fast, slow)
                if len(result_df) < max_lookback:
                    logger.warning(
                        "Input DataFrame length %d is less than the required slow lookback %d for MACD.",
                        len(result_df),
                        max_lookback,
                    )

                macd_col = f"macd_{fast}_{slow}"
                signal_col = f"macd_signal_{signal}"
                hist_col = f"macd_hist_{signal}"

                target_cols = [macd_col, signal_col, hist_col]
                colliding_cols = [c for c in target_cols if c in result_df.columns]
                if colliding_cols and not overwrite:
                    logger.warning(
                        "Columns %s already exist in DataFrame and overwrite=False. Skipping MACD.",
                        colliding_cols,
                    )
                    continue

                macd_df = result_df.ta.macd(fast=fast, slow=slow, signal=signal)
                if macd_df is not None and not macd_df.empty:
                    for col in macd_df.columns:
                        col_lower = col.lower()
                        if col_lower.startswith("macdh_") or "h_" in col_lower:
                            result_df[hist_col] = macd_df[col]
                        elif col_lower.startswith("macds_") or "s_" in col_lower:
                            result_df[signal_col] = macd_df[col]
                        elif col_lower.startswith("macd_"):
                            result_df[macd_col] = macd_df[col]
                else:
                    logger.warning("MACD computation returned empty or None DataFrame.")

            elif kind in ["bbands", "bb", "bollinger_bands"]:
                length = config.get("length", 20)
                std = config.get("std", 2.0)

                if len(result_df) < length:
                    logger.warning(
                        "Input DataFrame length %d is less than the required lookback %d for Bollinger Bands.",
                        len(result_df),
                        length,
                    )

                std_formatted = str(int(std)) if std == int(std) else str(std)
                lower_col = f"bb_lower_{length}_{std_formatted}"
                middle_col = f"bb_middle_{length}_{std_formatted}"
                upper_col = f"bb_upper_{length}_{std_formatted}"
                width_col = f"bb_width_{length}_{std_formatted}"
                percent_col = f"bb_percent_{length}_{std_formatted}"

                bb_cols = [lower_col, middle_col, upper_col, width_col, percent_col]
                colliding_cols = [c for c in bb_cols if c in result_df.columns]
                if colliding_cols and not overwrite:
                    logger.warning(
                        "Columns %s already exist in DataFrame and overwrite=False. Skipping Bollinger Bands.",
                        colliding_cols,
                    )
                    continue

                bb_df = result_df.ta.bbands(length=length, std=std)
                if bb_df is not None and not bb_df.empty:
                    for col in bb_df.columns:
                        col_upper = col.upper()
                        if col_upper.startswith("BBL_"):
                            result_df[lower_col] = bb_df[col]
                        elif col_upper.startswith("BBM_"):
                            result_df[middle_col] = bb_df[col]
                        elif col_upper.startswith("BBU_"):
                            result_df[upper_col] = bb_df[col]
                        elif col_upper.startswith("BBB_"):
                            result_df[width_col] = bb_df[col]
                        elif col_upper.startswith("BBP_"):
                            result_df[percent_col] = bb_df[col]
                else:
                    logger.warning("Bollinger Bands computation returned empty or None DataFrame.")

            elif kind == "adx":
                length = config.get("length", 14)
                if len(result_df) < length:
                    logger.warning("Input DataFrame length %d is less than required lookback %d for ADX.", len(result_df), length)
                col_name = f"adx_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue
                adx_df = result_df.ta.adx(length=length)
                if adx_df is not None and not adx_df.empty:
                    for col in adx_df.columns:
                        col_upper = col.upper()
                        if col_upper.startswith("ADX_"):
                            result_df[col_name] = adx_df[col]
                        elif col_upper.startswith("DMP_"):
                            result_df[f"dmp_{length}"] = adx_df[col]
                        elif col_upper.startswith("DMN_"):
                            result_df[f"dmn_{length}"] = adx_df[col]
                else:
                    logger.warning("ADX computation returned empty/None.")

            elif kind in ["stoch", "stochastic"]:
                k = config.get("k", 14)
                d = config.get("d", 3)
                smooth_k = config.get("smooth_k", 3)
                if len(result_df) < k:
                    logger.warning("Input DataFrame length %d is less than required lookback %d for Stochastic.", len(result_df), k)
                k_col = f"stoch_k_{k}_{d}_{smooth_k}" if "smooth_k" in config or "k" in config else "stoch_k"
                d_col = f"stoch_d_{k}_{d}_{smooth_k}" if "smooth_k" in config or "d" in config else "stoch_d"
                # Support simple standardized column aliases too
                aliases = ["stoch_k", "stoch_d"]
                colliding = [c for c in [k_col, d_col] if c in result_df.columns]
                if colliding and not overwrite:
                    logger.warning("Stochastic columns %s already exist and overwrite=False. Skipping.", colliding)
                    continue
                stoch_df = result_df.ta.stoch(k=k, d=d, smooth_k=smooth_k)
                if stoch_df is not None and not stoch_df.empty:
                    for col in stoch_df.columns:
                        col_upper = col.upper()
                        if col_upper.startswith("STOCHK_"):
                            result_df[k_col] = stoch_df[col]
                            result_df["stoch_k"] = stoch_df[col]
                        elif col_upper.startswith("STOCHD_"):
                            result_df[d_col] = stoch_df[col]
                            result_df["stoch_d"] = stoch_df[col]
                else:
                    logger.warning("Stochastic computation returned empty/None.")

            elif kind == "cci":
                length = config.get("length", 14)
                if len(result_df) < length:
                    logger.warning("Input DataFrame length %d is less than required lookback %d for CCI.", len(result_df), length)
                col_name = f"cci_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue
                cci_series = result_df.ta.cci(length=length)
                result_df[col_name] = cci_series

            elif kind == "obv":
                col_name = "obv"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue
                obv_series = result_df.ta.obv()
                result_df[col_name] = obv_series

            elif kind == "roc":
                length = config.get("length", 10)
                if len(result_df) < length:
                    logger.warning("Input DataFrame length %d is less than required lookback %d for ROC.", len(result_df), length)
                col_name = f"roc_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue
                roc_series = result_df.ta.roc(length=length)
                result_df[col_name] = roc_series

            elif kind in ["willr", "williams_r"]:
                length = config.get("length", 14)
                if len(result_df) < length:
                    logger.warning("Input DataFrame length %d is less than required lookback %d for Williams %%R.", len(result_df), length)
                col_name = f"williams_r_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue
                willr_series = result_df.ta.willr(length=length)
                result_df[col_name] = willr_series

            elif kind == "mfi":
                length = config.get("length", 14)
                if len(result_df) < length:
                    logger.warning("Input DataFrame length %d is less than required lookback %d for MFI.", len(result_df), length)
                col_name = f"mfi_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue
                mfi_series = result_df.ta.mfi(length=length)
                result_df[col_name] = mfi_series

            else:
                logger.warning("Unsupported indicator kind: %s", kind)

        except Exception as e:
            logger.error(
                "Error computing indicator %s with config %s: %s",
                kind,
                config,
                e,
                exc_info=True,
            )

    return result_df


def add_standard_indicators(df: pd.DataFrame, overwrite: bool = False) -> pd.DataFrame:
    """Adds all indicators needed for Sprint 3 strategies with standard naming.

    Adds:
        - sma_50, sma_200
        - ema_10, ema_20, ema_30, ema_50
        - rsi_14
        - macd_12_26, macd_signal_9, macd_hist_9
        - bb_lower_20_2, bb_middle_20_2, bb_upper_20_2, bb_width_20_2, bb_percent_20_2
        - atr_14

    Args:
        df: Input DataFrame with standard OHLCV columns.
        overwrite: If True, overwrites existing columns. Otherwise, warns and skips.

    Returns:
        A copy of the DataFrame with the standard indicators computed and appended.
    """
    configs = [
        {"kind": "sma", "length": 50},
        {"kind": "sma", "length": 200},
        {"kind": "ema", "length": 10},
        {"kind": "ema", "length": 20},
        {"kind": "ema", "length": 30},
        {"kind": "ema", "length": 50},
        {"kind": "rsi", "length": 14},
        {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
        {"kind": "bbands", "length": 20, "std": 2},
        {"kind": "atr", "length": 14},
    ]
    return add_indicators(df, configs, overwrite=overwrite)
