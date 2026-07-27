"""Acceptance tests for the data layer (Sprint 1).

Tests the full pipeline: fetch → clean → save → load → verify.
These are integration tests that hit the real yfinance API.
Mark as slow / skip in CI if needed.

Run with:
    python -m pytest tests/test_data/test_fetcher.py -v
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.cleaner import DataCleaner
from src.data.exceptions import InvalidSymbolError
from src.data.fetcher import CANONICAL_COLUMNS, DataFetcher
from src.data.store import DataStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fetcher() -> DataFetcher:
    """Return a default DataFetcher instance."""
    return DataFetcher(max_retries=2, base_delay=0.5)


@pytest.fixture()
def cleaner() -> DataCleaner:
    """Return a default DataCleaner instance."""
    return DataCleaner(max_gap_fill_days=2)


@pytest.fixture()
def tmp_store(tmp_path: Path) -> DataStore:
    """Return a DataStore writing to a temporary directory."""
    return DataStore(raw_dir=tmp_path / "raw")


# ---------------------------------------------------------------------------
# Test: Fetch AAPL
# ---------------------------------------------------------------------------


class TestDataFetcher:
    """Tests for the DataFetcher class."""

    def test_fetch_aapl_daily(self, fetcher: DataFetcher) -> None:
        """Fetch AAPL 2023-01-01 → 2024-12-31 and validate shape/columns."""
        df = fetcher.fetch("AAPL", start="2023-01-01", end="2024-12-31")

        # Must have rows
        assert len(df) > 0, "Fetched DataFrame should not be empty"

        # Expected ~500 trading days in 2 years
        assert len(df) > 400, f"Expected >400 rows, got {len(df)}"

        # Canonical columns
        assert list(df.columns) == CANONICAL_COLUMNS

        # Index type
        assert isinstance(df.index, pd.DatetimeIndex)

        # No NaN in OHLC
        for col in ["open", "high", "low", "close"]:
            assert df[col].notna().all(), f"NaN found in {col}"

        # Volume ≥ 0
        assert (df["volume"] >= 0).all(), "Negative volume detected"

        # Monotonic index
        assert df.index.is_monotonic_increasing

    def test_invalid_symbol_raises(self, fetcher: DataFetcher) -> None:
        """Invalid symbol should raise InvalidSymbolError."""
        with pytest.raises(InvalidSymbolError):
            fetcher.fetch("ZZZZZZZNOTREAL123", start="2023-01-01", end="2023-02-01")


# ---------------------------------------------------------------------------
# Test: Cleaner
# ---------------------------------------------------------------------------


class TestDataCleaner:
    """Tests for the DataCleaner class."""

    def test_clean_valid_data(
        self, fetcher: DataFetcher, cleaner: DataCleaner
    ) -> None:
        """Clean fetched AAPL data and verify quality report."""
        raw = fetcher.fetch("AAPL", start="2024-01-01", end="2024-06-30")
        clean_df, report = cleaner.clean(raw, symbol="AAPL")

        assert report["symbol"] == "AAPL"
        assert report["rows_after"] > 0
        assert report["rows_after"] == len(clean_df)

        # Cleaned data should still be valid OHLCV
        assert list(clean_df.columns) == CANONICAL_COLUMNS
        assert clean_df.index.is_monotonic_increasing


# ---------------------------------------------------------------------------
# Test: Store round-trip
# ---------------------------------------------------------------------------


class TestDataStore:
    """Tests for the DataStore class."""

    def test_save_and_load_roundtrip(
        self, fetcher: DataFetcher, cleaner: DataCleaner, tmp_store: DataStore
    ) -> None:
        """Fetch → clean → save → load → verify data integrity."""
        # Fetch
        raw = fetcher.fetch("AAPL", start="2024-01-01", end="2024-06-30")
        clean_df, _ = cleaner.clean(raw, symbol="AAPL")

        # Save
        path = tmp_store.save("AAPL", clean_df)
        assert path.exists()
        assert path.suffix == ".parquet"

        # Load
        loaded = tmp_store.load("AAPL")

        # Same shape
        assert loaded.shape == clean_df.shape, (
            f"Shape mismatch: saved {clean_df.shape} vs loaded {loaded.shape}"
        )

        # Same columns
        assert list(loaded.columns) == list(clean_df.columns)

        # Strip tz for comparison (store converts to UTC-naive)
        clean_naive = clean_df.copy()
        if clean_naive.index.tz is not None:
            clean_naive.index = clean_naive.index.tz_convert("UTC").tz_localize(None)
        clean_naive.index = clean_naive.index.astype(loaded.index.dtype)

        # Values match
        pd.testing.assert_frame_equal(
            loaded, clean_naive, check_exact=False, atol=1e-6
        )

    def test_list_symbols(
        self, fetcher: DataFetcher, tmp_store: DataStore
    ) -> None:
        """list_symbols() returns saved tickers."""
        df = fetcher.fetch("AAPL", start="2024-01-01", end="2024-03-01")
        tmp_store.save("AAPL", df)

        symbols = tmp_store.list_symbols()
        assert "AAPL" in symbols

    def test_has_symbol(
        self, fetcher: DataFetcher, tmp_store: DataStore
    ) -> None:
        """has_symbol() correctly reports presence."""
        assert not tmp_store.has_symbol("AAPL")
        df = fetcher.fetch("AAPL", start="2024-01-01", end="2024-03-01")
        tmp_store.save("AAPL", df)
        assert tmp_store.has_symbol("AAPL")

    def test_date_range_slicing(
        self, fetcher: DataFetcher, tmp_store: DataStore
    ) -> None:
        """load() with start/end returns the correct subset."""
        df = fetcher.fetch("AAPL", start="2024-01-01", end="2024-06-30")
        tmp_store.save("AAPL", df)

        subset = tmp_store.load("AAPL", start="2024-03-01", end="2024-04-30")
        assert len(subset) < len(df)
        assert subset.index.min() >= pd.Timestamp("2024-03-01")
        assert subset.index.max() <= pd.Timestamp("2024-04-30")


# ---------------------------------------------------------------------------
# Quick smoke test (can run standalone)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)

    log.info("=" * 60)
    log.info("Sprint 1 — Acceptance Test")
    log.info("=" * 60)

    # 1) Fetch
    log.info("1) Fetching AAPL 2023-01-01 → 2024-12-31 ...")
    f = DataFetcher(max_retries=3)
    df = f.fetch("AAPL", start="2023-01-01", end="2024-12-31")
    log.info("   Shape: %s | Columns: %s", df.shape, list(df.columns))
    log.info("   Date range: %s → %s", df.index.min(), df.index.max())

    # 2) Validate columns
    assert list(df.columns) == CANONICAL_COLUMNS, "Column mismatch!"
    assert len(df) > 400, f"Too few rows: {len(df)}"
    log.info("   ✓ Columns and shape OK")

    # 3) Clean
    log.info("2) Cleaning data ...")
    c = DataCleaner()
    clean_df, report = c.clean(df, symbol="AAPL")
    log.info("   Report: %s", report)

    # 4) Save
    tmp_dir = Path("data/raw")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    store = DataStore(raw_dir=tmp_dir)
    log.info("3) Saving to Parquet ...")
    saved_path = store.save("AAPL", clean_df)
    log.info("   Saved to: %s", saved_path)

    # 5) Load back
    log.info("4) Loading from Parquet ...")
    loaded = store.load("AAPL")
    log.info("   Loaded shape: %s", loaded.shape)

    # 6) Verify round-trip
    clean_naive = clean_df.copy()
    if clean_naive.index.tz is not None:
        clean_naive.index = clean_naive.index.tz_convert("UTC").tz_localize(None)
    clean_naive.index = clean_naive.index.astype(loaded.index.dtype)

    pd.testing.assert_frame_equal(loaded, clean_naive, check_exact=False, atol=1e-6)
    log.info("   ✓ Round-trip integrity verified")

    log.info("=" * 60)
    log.info("ALL ACCEPTANCE TESTS PASSED ✓")
    log.info("=" * 60)
