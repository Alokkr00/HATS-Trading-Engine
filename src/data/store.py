"""Data store — Parquet-based persistence with smart caching.

Saves and loads OHLCV DataFrames to/from Parquet files.
Implements incremental fetching: if data already exists on disk,
only the missing date range is returned/requested.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.data.exceptions import StoreError

logger = logging.getLogger(__name__)

# Default storage root (relative to project root)
_DEFAULT_RAW_DIR = Path("data/raw")


class DataStore:
    """Parquet-backed storage for OHLCV market data.

    Attributes:
        raw_dir: Directory where ``{SYMBOL}.parquet`` files are stored.

    Example::

        store = DataStore()
        store.save("AAPL", df)
        loaded = store.load("AAPL", start="2023-01-01", end="2024-01-01")
    """

    def __init__(self, raw_dir: Path | str | None = None) -> None:
        """Initialise the DataStore.

        Args:
            raw_dir: Root directory for Parquet files.  Defaults to
                     ``data/raw/`` relative to the current working
                     directory.
        """
        self.raw_dir = Path(raw_dir) if raw_dir else _DEFAULT_RAW_DIR
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        logger.info("DataStore initialised — raw_dir=%s", self.raw_dir.resolve())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, symbol: str, df: pd.DataFrame) -> Path:
        """Save OHLCV DataFrame to Parquet, merging with existing data.

        If a Parquet file already exists for the symbol, the new data
        is merged (union by index) so that we accumulate history without
        duplicates.

        Args:
            symbol: Ticker symbol (e.g. ``"AAPL"``).
            df: DataFrame with DatetimeIndex and OHLCV columns.

        Returns:
            Path to the written Parquet file.

        Raises:
            StoreError: On write failure.
        """
        symbol = symbol.upper().strip()
        path = self._symbol_path(symbol)

        try:
            # Remove timezone info for Parquet compatibility (store as UTC)
            df = df.copy()
            if df.index.tz is not None:
                df.index = df.index.tz_convert("UTC").tz_localize(None)

            if path.exists():
                existing = self._read_parquet(path)
                df = self._merge(existing, df)
                logger.info(
                    "[%s] Merged with existing data: %d total rows", symbol, len(df)
                )

            df = df.sort_index()
            df.to_parquet(path, engine="pyarrow", compression="snappy")
            logger.info("[%s] Saved %d rows to %s", symbol, len(df), path)
            return path

        except Exception as exc:
            raise StoreError(f"Failed to save {symbol}: {exc}") from exc

    def load(
        self,
        symbol: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        tz: str | None = None,
    ) -> pd.DataFrame:
        """Load OHLCV data from Parquet, optionally slicing by date.

        Args:
            symbol: Ticker symbol.
            start: Optional start date for slicing (inclusive).
            end: Optional end date for slicing (inclusive).
            tz: Optional timezone to convert/localize the index to (e.g. ``"US/Eastern"``).

        Returns:
            DataFrame with DatetimeIndex and OHLCV columns.

        Raises:
            StoreError: If the file does not exist or cannot be read.
        """
        symbol = symbol.upper().strip()
        path = self._symbol_path(symbol)

        if not path.exists():
            raise StoreError(f"No data on disk for {symbol} (looked in {path})")

        df = self._read_parquet(path)

        # Timezone localization / conversion
        if tz is not None and not df.empty:
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC").tz_convert(tz)
            else:
                df.index = df.index.tz_convert(tz)

        # Slice by date range
        if start is not None:
            start_ts = pd.Timestamp(start)
            if tz is not None and start_ts.tzinfo is None:
                start_ts = start_ts.tz_localize(tz)
            df = df[df.index >= start_ts]
        if end is not None:
            end_ts = pd.Timestamp(end)
            if tz is not None and end_ts.tzinfo is None:
                end_ts = end_ts.tz_localize(tz)
            df = df[df.index <= end_ts]

        df.attrs["symbol"] = symbol
        logger.info("[%s] Loaded %d rows from %s", symbol, len(df), path)
        return df

    def has_symbol(self, symbol: str) -> bool:
        """Check whether a Parquet file exists for the symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            True if a file exists, False otherwise.
        """
        return self._symbol_path(symbol.upper().strip()).exists()

    def list_symbols(self) -> list[str]:
        """List all symbols that have cached Parquet files.

        Returns:
            Sorted list of symbol strings.
        """
        symbols = sorted(
            p.stem.upper() for p in self.raw_dir.glob("*.parquet")
        )
        logger.debug("Cached symbols: %s", symbols)
        return symbols

    def get_date_range(self, symbol: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """Return the min/max dates stored for a symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            ``(min_date, max_date)`` or ``None`` if no data exists.
        """
        symbol = symbol.upper().strip()
        path = self._symbol_path(symbol)
        if not path.exists():
            return None

        df = self._read_parquet(path)
        if df.empty:
            return None
        return df.index.min(), df.index.max()

    def delete(self, symbol: str) -> bool:
        """Delete the Parquet file for a symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            True if file was deleted, False if it didn't exist.
        """
        path = self._symbol_path(symbol.upper().strip())
        if path.exists():
            path.unlink()
            logger.info("Deleted %s", path)
            return True
        return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _symbol_path(self, symbol: str) -> Path:
        """Build the file path for a symbol.

        Args:
            symbol: Ticker symbol (already uppercased).

        Returns:
            Path like ``data/raw/AAPL.parquet``.
        """
        return self.raw_dir / f"{symbol}.parquet"

    @staticmethod
    def _read_parquet(path: Path) -> pd.DataFrame:
        """Read a Parquet file and ensure DatetimeIndex.

        Args:
            path: Parquet file path.

        Returns:
            DataFrame with DatetimeIndex.
        """
        try:
            df = pd.read_parquet(path, engine="pyarrow")
        except Exception as exc:
            raise StoreError(f"Failed to read {path}: {exc}") from exc

        # Ensure index is DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            if "date" in df.columns:
                df = df.set_index("date")
            else:
                df.index = pd.to_datetime(df.index)

        df.index.name = "date"
        return df

    @staticmethod
    def _merge(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        """Merge existing and new DataFrames, preferring new data on overlap.

        Args:
            existing: Previously stored DataFrame.
            new: Newly fetched DataFrame.

        Returns:
            Combined DataFrame with no duplicate timestamps.
        """
        combined = pd.concat([existing, new])
        # Keep last (= new data) on duplicate timestamps
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
        return combined
