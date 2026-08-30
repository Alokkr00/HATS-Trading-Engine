"""Data fetcher — pluggable backend for historical market data.

Currently supports yfinance as the data source. Designed so that
additional backends (Webull, Polygon, etc.) can be added by
implementing the same interface.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd
import yfinance as yf

from src.data.exceptions import (
    FetchError,
    InvalidSymbolError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

# Canonical column order — always lowercase, no Adj Close clutter
CANONICAL_COLUMNS: list[str] = ["open", "high", "low", "close", "volume"]


class DataFetcher:
    """Fetches historical OHLCV data with retry logic and validation.

    Attributes:
        source: Name of the data backend (currently only ``"yfinance"``).
        max_retries: Maximum number of retry attempts on transient failure.
        base_delay: Base delay in seconds for exponential backoff.
        max_delay: Maximum delay cap in seconds for backoff.

    Example::

        fetcher = DataFetcher()
        df = fetcher.fetch("AAPL", start="2023-01-01", end="2024-01-01")
        print(df.head())
    """

    def __init__(
        self,
        source: Literal["yfinance"] = "yfinance",
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        """Initialise the DataFetcher.

        Args:
            source: Backend data source name.
            max_retries: Max retry attempts for transient failures.
            base_delay: Initial backoff delay (seconds).
            max_delay: Backoff cap (seconds).
        """
        self.source = source
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        symbol: str,
        start: str | datetime,
        end: str | datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch OHLCV data for a single symbol.

        Args:
            symbol: Ticker symbol (e.g. ``"AAPL"``).
            start: Start date (inclusive), ISO-8601 string or datetime.
            end: End date (inclusive), ISO-8601 string or datetime.
            interval: Bar interval — ``"1d"``, ``"1h"``, ``"5m"``, etc.

        Returns:
            DataFrame with DatetimeIndex and columns
            ``[open, high, low, close, volume]``.

        Raises:
            InvalidSymbolError: If the symbol is invalid or delisted.
            RateLimitError: If the upstream API rate-limits us.
            FetchError: On any other retrieval failure after retries.
        """
        symbol = symbol.upper().strip()
        if not symbol:
            raise InvalidSymbolError("Symbol cannot be empty")

        logger.info(
            "Fetching %s  %s -> %s  interval=%s  source=%s",
            symbol, start, end, interval, self.source,
        )

        raw = self._fetch_with_retry(symbol, start, end, interval)
        df = self._normalize(raw, symbol)

        logger.info(
            "Fetched %s: %d rows, %s -> %s",
            symbol, len(df), df.index.min(), df.index.max(),
        )
        return df

    def fetch_bulk(
        self,
        symbols: list[str],
        start: str | datetime,
        end: str | datetime,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Fetch data for multiple symbols, returning a dict keyed by symbol.

        Symbols that fail are logged and skipped rather than raising.

        Args:
            symbols: List of ticker symbols.
            start: Start date (inclusive).
            end: End date (inclusive).
            interval: Bar interval.

        Returns:
            ``{symbol: DataFrame}`` for each successfully fetched symbol.
        """
        results: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                results[sym] = self.fetch(sym, start, end, interval)
            except FetchError as exc:  # noqa: F841 — broad catch intentional
                logger.error("Skipping %s: %s", sym, exc)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_with_retry(
        self,
        symbol: str,
        start: str | datetime,
        end: str | datetime,
        interval: str,
    ) -> pd.DataFrame:
        """Retry wrapper with exponential backoff.

        Args:
            symbol: Ticker symbol.
            start: Start date.
            end: End date.
            interval: Bar interval.

        Returns:
            Raw DataFrame from the backend.

        Raises:
            InvalidSymbolError: If the symbol is not found.
            RateLimitError: After exhausting retries on rate-limit errors.
            FetchError: After exhausting retries on other errors.
        """
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                return self._call_yfinance(symbol, start, end, interval)

            except InvalidSymbolError:
                raise  # no point retrying

            except RateLimitError as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Rate limited on %s (attempt %d/%d) — backing off %.1fs",
                    symbol, attempt, self.max_retries, delay,
                )
                time.sleep(delay)

            except FetchError as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Fetch error on %s (attempt %d/%d): %s — retrying in %.1fs",
                    symbol, attempt, self.max_retries, exc, delay,
                )
                time.sleep(delay)

        raise FetchError(
            f"Failed to fetch {symbol} after {self.max_retries} retries: {last_exc}"
        )

    def _call_yfinance(
        self,
        symbol: str,
        start: str | datetime,
        end: str | datetime,
        interval: str,
    ) -> pd.DataFrame:
        """Low-level yfinance call.

        Args:
            symbol: Ticker symbol.
            start: Start date.
            end: End date.
            interval: Bar interval.

        Returns:
            Raw DataFrame from yfinance.

        Raises:
            InvalidSymbolError: If yfinance returns empty data.
            RateLimitError: On HTTP 429 or similar rate-limit signal.
            FetchError: On any other failure.
        """
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(
                start=start,
                end=end,
                interval=interval,
                auto_adjust=True,
                actions=False,
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "429" in msg or "rate" in msg or "too many" in msg:
                raise RateLimitError(f"Rate limited fetching {symbol}: {exc}") from exc
            raise FetchError(f"yfinance error fetching {symbol}: {exc}") from exc

        if df is None or df.empty:
            raise InvalidSymbolError(
                f"No data returned for '{symbol}'. "
                "Possible invalid/delisted symbol or no data in range."
            )

        return df

    def _normalize(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Normalize raw backend data to canonical format.

        - Lowercase column names
        - Keep only OHLCV columns
        - Ensure correct dtypes
        - Name the index ``"date"``

        Args:
            df: Raw DataFrame from backend.
            symbol: Symbol (for error messages).

        Returns:
            Cleaned DataFrame with canonical columns.
        """
        # Lowercase all column names
        df.columns = [c.lower().strip() for c in df.columns]

        # Map common alternatives
        rename_map: dict[str, str] = {
            "adj close": "close",  # if auto_adjust is off
        }
        df = df.rename(columns=rename_map)

        # Keep only canonical columns
        missing = [c for c in CANONICAL_COLUMNS if c not in df.columns]
        if missing:
            raise FetchError(
                f"Missing expected columns for {symbol}: {missing}. "
                f"Got: {list(df.columns)}"
            )
        df = df[CANONICAL_COLUMNS].copy()

        # Ensure dtypes
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(np.float64)
        df["volume"] = df["volume"].astype(np.int64)

        # Name the index
        df.index.name = "date"

        return df

    def _backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter.

        Args:
            attempt: Current attempt number (1-indexed).

        Returns:
            Delay in seconds.
        """
        delay = self.base_delay * (2 ** (attempt - 1))
        delay = min(delay, self.max_delay)
        # Add small jitter (±20 %)
        jitter = delay * 0.2 * (2 * np.random.random() - 1)
        return max(0.1, delay + jitter)
