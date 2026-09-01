"""Data cleaner — validates and repairs OHLCV DataFrames.

Handles timezone normalization, gap filling, duplicate removal,
and comprehensive OHLCV integrity checks.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from src.data.exceptions import ValidationError

logger = logging.getLogger(__name__)

# America/New_York is the reference timezone for US equity market data
MARKET_TZ = "America/New_York"


class DataCleaner:
    """Cleans and validates OHLCV market data.

    Attributes:
        max_gap_fill_days: Maximum gap (in calendar days) to forward-fill.
            Gaps larger than this are flagged but not filled.

    Example::

        cleaner = DataCleaner()
        clean_df, report = cleaner.clean(raw_df, symbol="AAPL")
        print(report)
    """

    def __init__(self, max_gap_fill_days: int = 2) -> None:
        """Initialise the DataCleaner.

        Args:
            max_gap_fill_days: Max calendar-day gap to forward-fill.
        """
        self.max_gap_fill_days = max_gap_fill_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clean(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Clean and validate an OHLCV DataFrame.

        Processing pipeline:
            1. Ensure timezone-aware DatetimeIndex (America/New_York).
            2. Sort by timestamp and remove duplicates.
            3. Forward-fill small gaps (≤ ``max_gap_fill_days``).
            4. Run OHLCV integrity checks.

        Args:
            df: Raw OHLCV DataFrame with DatetimeIndex.
            symbol: Ticker symbol (used in log messages).

        Returns:
            Tuple of ``(cleaned_df, quality_report)`` where
            ``quality_report`` is a dict summarizing the cleaning steps.

        Raises:
            ValidationError: If the data has irrecoverable problems
                (e.g. all-NaN price columns after cleaning).
        """
        if df.empty:
            raise ValidationError(f"[{symbol}] Empty DataFrame — nothing to clean.")

        report: dict[str, Any] = {
            "symbol": symbol,
            "rows_before": len(df),
            "duplicates_removed": 0,
            "gaps_filled": 0,
            "large_gaps": [],
            "validation_warnings": [],
            "rows_after": 0,
            "passed": False,
        }

        df = df.copy()

        # Step 1: Timezone
        df = self._ensure_timezone(df, symbol)

        # Step 2: Sort + deduplicate
        df, n_dups = self._sort_and_deduplicate(df, symbol)
        report["duplicates_removed"] = n_dups

        # Step 3: Gap handling
        df, n_filled, large_gaps = self._handle_gaps(df, symbol)
        report["gaps_filled"] = n_filled
        report["large_gaps"] = large_gaps

        # Step 4: Validate OHLCV integrity
        warnings = self._validate_ohlcv(df, symbol)
        report["validation_warnings"] = warnings

        report["rows_after"] = len(df)
        report["passed"] = len(warnings) == 0

        if report["passed"]:
            logger.info("[%s] Data cleaning passed - %d rows", symbol, len(df))
        else:
            logger.warning(
                "[%s] Data cleaning completed with %d warnings",
                symbol, len(warnings),
            )

        return df, report

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    def _ensure_timezone(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Normalize index to US/Eastern timezone-aware DatetimeIndex.

        Args:
            df: Input DataFrame.
            symbol: Ticker symbol.

        Returns:
            DataFrame with tz-aware index.
        """
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValidationError(
                f"[{symbol}] Index is not DatetimeIndex (got {type(df.index).__name__})"
            )

        if df.index.tz is None:
            # Naive → localize (assume UTC from yfinance, convert to Eastern)
            logger.debug("[%s] Localizing naive timestamps to UTC → %s", symbol, MARKET_TZ)
            df.index = df.index.tz_localize("UTC").tz_convert(MARKET_TZ)
        else:
            # Already tz-aware → convert to Eastern
            df.index = df.index.tz_convert(MARKET_TZ)

        return df

    def _sort_and_deduplicate(
        self, df: pd.DataFrame, symbol: str
    ) -> tuple[pd.DataFrame, int]:
        """Sort by index and remove duplicate timestamps.

        Args:
            df: Input DataFrame.
            symbol: Ticker symbol.

        Returns:
            Tuple of ``(df, n_duplicates_removed)``.
        """
        df = df.sort_index()

        dup_mask = df.index.duplicated(keep="last")
        n_dups = int(dup_mask.sum())
        if n_dups > 0:
            logger.warning("[%s] Removing %d duplicate timestamps", symbol, n_dups)
            df = df[~dup_mask]

        # Verify monotonicity
        if not df.index.is_monotonic_increasing:
            raise ValidationError(
                f"[{symbol}] Index is not monotonic increasing after sort — "
                "possible corrupt data."
            )

        return df, n_dups

    def _handle_gaps(
        self, df: pd.DataFrame, symbol: str
    ) -> tuple[pd.DataFrame, int, list[dict[str, Any]]]:
        """Detect and forward-fill small trading-day gaps.

        Only forward-fills gaps ≤ ``max_gap_fill_days`` calendar days.
        Larger gaps are recorded but not filled.

        Args:
            df: Input DataFrame (sorted, no duplicates).
            symbol: Ticker symbol.

        Returns:
            Tuple of ``(df, n_rows_filled, large_gaps_list)``.
            Each large gap is a dict with keys ``from``, ``to``,
            ``calendar_days``.
        """
        if len(df) < 2:
            return df, 0, []

        # Detect gaps by comparing date diffs to expected trading cadence
        # For daily data, >3 calendar days is noteworthy (Mon→Mon = 3 if
        # no holiday); >max_gap_fill_days means we flag it
        date_diffs = df.index.to_series().diff()

        large_gaps: list[dict[str, Any]] = []
        threshold = pd.Timedelta(days=self.max_gap_fill_days + 1)

        for i, delta in enumerate(date_diffs):
            if pd.isna(delta):
                continue
            if delta > threshold:
                gap_info = {
                    "from": str(df.index[i - 1]),
                    "to": str(df.index[i]),
                    "calendar_days": delta.days,
                }
                large_gaps.append(gap_info)
                logger.warning(
                    "[%s] Large gap detected: %s -> %s (%d days)",
                    symbol, gap_info["from"], gap_info["to"], delta.days,
                )

        # Forward-fill NaN values in OHLC (small intraday gaps)
        n_nans_before = int(df[["open", "high", "low", "close"]].isna().sum().sum())
        df[["open", "high", "low", "close"]] = (
            df[["open", "high", "low", "close"]].ffill(limit=self.max_gap_fill_days)
        )
        # Volume NaN → 0 (no volume on gap days is expected)
        df["volume"] = df["volume"].fillna(0).astype(np.int64)

        n_nans_after = int(df[["open", "high", "low", "close"]].isna().sum().sum())
        n_filled = n_nans_before - n_nans_after

        if n_filled > 0:
            logger.info("[%s] Forward-filled %d NaN values", symbol, n_filled)

        return df, n_filled, large_gaps

    def _validate_ohlcv(
        self, df: pd.DataFrame, symbol: str
    ) -> list[str]:
        """Run OHLCV integrity checks.

        Checks:
            - No NaN in OHLC columns
            - Volume ≥ 0
            - High ≥ Low
            - High ≥ Open and High ≥ Close
            - Low ≤ Open and Low ≤ Close

        Args:
            df: Cleaned DataFrame.
            symbol: Ticker symbol.

        Returns:
            List of warning strings (empty = all checks passed).
        """
        warnings: list[str] = []

        # NaN checks
        for col in ["open", "high", "low", "close"]:
            n_nan = int(df[col].isna().sum())
            if n_nan > 0:
                warnings.append(f"Column '{col}' has {n_nan} NaN value(s)")

        # Volume ≥ 0
        neg_vol = int((df["volume"] < 0).sum())
        if neg_vol > 0:
            warnings.append(f"Volume has {neg_vol} negative value(s)")

        # High ≥ Low
        bad_hl = int((df["high"] < df["low"]).sum())
        if bad_hl > 0:
            warnings.append(f"High < Low on {bad_hl} row(s)")

        # High ≥ Open
        bad_ho = int((df["high"] < df["open"]).sum())
        if bad_ho > 0:
            warnings.append(f"High < Open on {bad_ho} row(s)")

        # High ≥ Close
        bad_hc = int((df["high"] < df["close"]).sum())
        if bad_hc > 0:
            warnings.append(f"High < Close on {bad_hc} row(s)")

        # Low ≤ Open
        bad_lo = int((df["low"] > df["open"]).sum())
        if bad_lo > 0:
            warnings.append(f"Low > Open on {bad_lo} row(s)")

        # Low ≤ Close
        bad_lc = int((df["low"] > df["close"]).sum())
        if bad_lc > 0:
            warnings.append(f"Low > Close on {bad_lc} row(s)")

        for w in warnings:
            logger.warning("[%s] Validation: %s", symbol, w)

        return warnings
