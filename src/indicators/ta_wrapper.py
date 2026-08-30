"""Technical indicators wrapper for computing indicators on OHLCV DataFrames.

Provides functions to compute technical indicators using pure NumPy and Pandas
with standardized, lowercase naming conventions, preserving original indexes and timezones.
Zero external fragile dependencies (eliminates unmaintained pandas-ta).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

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

                sma_series = result_df["close"].rolling(window=length, min_periods=length).mean()
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

                ema_series = result_df["close"].ewm(span=length, adjust=False).mean()
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

                delta = result_df["close"].diff()
                gain = delta.clip(lower=0.0)
                loss = (-delta).clip(lower=0.0)
                avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
                avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
                rs = avg_gain / avg_loss.replace(0.0, np.nan)
                rsi_series = 100.0 - (100.0 / (1.0 + rs))
                rsi_series = rsi_series.fillna(100.0 * (avg_gain > 0))
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

                high = result_df["high"]
                low = result_df["low"]
                close = result_df["close"]
                prev_close = close.shift(1)
                tr1 = high - low
                tr2 = (high - prev_close).abs()
                tr3 = (low - prev_close).abs()
                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                atr_series = tr.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
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

                fast_ema = result_df["close"].ewm(span=fast, adjust=False).mean()
                slow_ema = result_df["close"].ewm(span=slow, adjust=False).mean()
                macd_line = fast_ema - slow_ema
                signal_line = macd_line.ewm(span=signal, adjust=False).mean()
                hist_line = macd_line - signal_line

                result_df[macd_col] = macd_line
                result_df[signal_col] = signal_line
                result_df[hist_col] = hist_line

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

                middle = result_df["close"].rolling(window=length, min_periods=length).mean()
                sigma = result_df["close"].rolling(window=length, min_periods=length).std()
                upper = middle + std * sigma
                lower = middle - std * sigma
                width = ((upper - lower) / middle) * 100.0
                band_diff = (upper - lower).replace(0.0, np.nan)
                percent = (result_df["close"] - lower) / band_diff

                result_df[lower_col] = lower
                result_df[middle_col] = middle
                result_df[upper_col] = upper
                result_df[width_col] = width
                result_df[percent_col] = percent

            elif kind == "adx":
                length = config.get("length", 14)
                if len(result_df) < length:
                    logger.warning(
                        "Input DataFrame length %d is less than required lookback %d for ADX.",
                        len(result_df),
                        length,
                    )
                col_name = f"adx_{length}"
                dmp_col = f"dmp_{length}"
                dmn_col = f"dmn_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue

                high = result_df["high"]
                low = result_df["low"]
                close = result_df["close"]
                prev_close = close.shift(1)
                tr1 = high - low
                tr2 = (high - prev_close).abs()
                tr3 = (low - prev_close).abs()
                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

                up_move = high.diff()
                down_move = -low.diff()
                plus_dm = pd.Series(
                    np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
                    index=result_df.index,
                )
                minus_dm = pd.Series(
                    np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
                    index=result_df.index,
                )

                atr_smooth = tr.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
                plus_di = 100.0 * (
                    plus_dm.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
                    / atr_smooth.replace(0.0, np.nan)
                )
                minus_di = 100.0 * (
                    minus_dm.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
                    / atr_smooth.replace(0.0, np.nan)
                )

                sum_di = (plus_di + minus_di).replace(0.0, np.nan)
                dx = 100.0 * ((plus_di - minus_di).abs() / sum_di)
                adx = dx.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()

                result_df[col_name] = adx
                result_df[dmp_col] = plus_di
                result_df[dmn_col] = minus_di

            elif kind in ["stoch", "stochastic"]:
                k = config.get("k", 14)
                d = config.get("d", 3)
                smooth_k = config.get("smooth_k", 3)
                if len(result_df) < k:
                    logger.warning(
                        "Input DataFrame length %d is less than required lookback %d for Stochastic.",
                        len(result_df),
                        k,
                    )
                k_col = f"stoch_k_{k}_{d}_{smooth_k}" if "smooth_k" in config or "k" in config else "stoch_k"
                d_col = f"stoch_d_{k}_{d}_{smooth_k}" if "smooth_k" in config or "d" in config else "stoch_d"
                colliding = [c for c in [k_col, d_col] if c in result_df.columns]
                if colliding and not overwrite:
                    logger.warning(
                        "Stochastic columns %s already exist and overwrite=False. Skipping.",
                        colliding,
                    )
                    continue

                lowest_low = result_df["low"].rolling(window=k, min_periods=k).min()
                highest_high = result_df["high"].rolling(window=k, min_periods=k).max()
                range_hl = (highest_high - lowest_low).replace(0.0, np.nan)
                fast_k = 100.0 * (result_df["close"] - lowest_low) / range_hl
                smooth_k_series = fast_k.rolling(window=smooth_k, min_periods=smooth_k).mean()
                smooth_d_series = smooth_k_series.rolling(window=d, min_periods=d).mean()

                result_df[k_col] = smooth_k_series
                result_df[d_col] = smooth_d_series
                result_df["stoch_k"] = smooth_k_series
                result_df["stoch_d"] = smooth_d_series

            elif kind == "cci":
                length = config.get("length", 14)
                if len(result_df) < length:
                    logger.warning(
                        "Input DataFrame length %d is less than required lookback %d for CCI.",
                        len(result_df),
                        length,
                    )
                col_name = f"cci_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue

                tp = (result_df["high"] + result_df["low"] + result_df["close"]) / 3.0
                sma_tp = tp.rolling(window=length, min_periods=length).mean()
                mad = tp.rolling(window=length, min_periods=length).apply(
                    lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
                )
                mad_adj = (0.015 * mad).replace(0.0, np.nan)
                cci_series = (tp - sma_tp) / mad_adj
                result_df[col_name] = cci_series

            elif kind == "obv":
                col_name = "obv"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue
                direction = np.sign(result_df["close"].diff()).fillna(0.0)
                obv_series = (direction * result_df["volume"]).cumsum()
                result_df[col_name] = obv_series

            elif kind == "roc":
                length = config.get("length", 10)
                if len(result_df) < length:
                    logger.warning(
                        "Input DataFrame length %d is less than required lookback %d for ROC.",
                        len(result_df),
                        length,
                    )
                col_name = f"roc_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue
                roc_series = (result_df["close"] / result_df["close"].shift(length) - 1.0) * 100.0
                result_df[col_name] = roc_series

            elif kind in ["willr", "williams_r"]:
                length = config.get("length", 14)
                if len(result_df) < length:
                    logger.warning(
                        "Input DataFrame length %d is less than required lookback %d for Williams %%R.",
                        len(result_df),
                        length,
                    )
                col_name = f"williams_r_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning(
                        "Column '%s' already exists and overwrite=False. Skipping.",
                        col_name,
                    )
                    continue
                highest_high = result_df["high"].rolling(window=length, min_periods=length).max()
                lowest_low = result_df["low"].rolling(window=length, min_periods=length).min()
                range_hl = (highest_high - lowest_low).replace(0.0, np.nan)
                willr_series = -100.0 * (highest_high - result_df["close"]) / range_hl
                result_df[col_name] = willr_series

            elif kind == "mfi":
                length = config.get("length", 14)
                if len(result_df) < length:
                    logger.warning(
                        "Input DataFrame length %d is less than required lookback %d for MFI.",
                        len(result_df),
                        length,
                    )
                col_name = f"mfi_{length}"
                if col_name in result_df.columns and not overwrite:
                    logger.warning("Column '%s' already exists and overwrite=False. Skipping.", col_name)
                    continue
                tp = (result_df["high"] + result_df["low"] + result_df["close"]) / 3.0
                rmf = tp * result_df["volume"]
                pos_mf = pd.Series(np.where(tp > tp.shift(1), rmf, 0.0), index=result_df.index)
                neg_mf = pd.Series(np.where(tp < tp.shift(1), rmf, 0.0), index=result_df.index)
                pos_sum = pos_mf.rolling(window=length, min_periods=length).sum()
                neg_sum = neg_mf.rolling(window=length, min_periods=length).sum().replace(0.0, np.nan)
                mfr = pos_sum / neg_sum
                mfi_series = 100.0 - (100.0 / (1.0 + mfr))
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
