"""Unit tests for DataCleaner and DataStore (mock-based, no network required)."""

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.cleaner import DataCleaner, MARKET_TZ
from src.data.exceptions import ValidationError, StoreError
from src.data.store import DataStore


# ---------------------------------------------------------------------------
# Helper: Generate synthetic test DataFrame
# ---------------------------------------------------------------------------
def generate_test_df(
    start: str,
    periods: int,
    tz: str | None = None,
    with_nans: bool = False,
    with_duplicates: bool = False,
) -> pd.DataFrame:
    """Helper to generate a mock OHLCV DataFrame for testing."""
    idx = pd.date_range(start=start, periods=periods, freq="D", tz=tz)
    
    if with_duplicates and len(idx) > 2:
        # Duplicate the second date
        idx_list = list(idx)
        idx_list[2] = idx_list[1]
        idx = pd.DatetimeIndex(idx_list)

    df = pd.DataFrame(
        {
            "open": np.linspace(100.0, 110.0, periods),
            "high": np.linspace(102.0, 112.0, periods),
            "low": np.linspace(98.0, 108.0, periods),
            "close": np.linspace(101.0, 111.0, periods),
            "volume": np.arange(1000, 1000 + periods, dtype=np.int64),
        },
        index=idx,
    )
    df.index.name = "date"

    if with_nans and periods > 2:
        for col in ["open", "high", "low", "close"]:
            df.iloc[1, df.columns.get_loc(col)] = np.nan
        df.iloc[1, df.columns.get_loc("volume")] = np.nan

    return df


# ---------------------------------------------------------------------------
# Tests: DataCleaner
# ---------------------------------------------------------------------------
class TestDataCleanerUnit:
    """Unit tests for DataCleaner."""

    def test_clean_valid_tz_naive(self) -> None:
        """Naive index should be converted to MARKET_TZ (US/Eastern)."""
        cleaner = DataCleaner()
        df = generate_test_df("2025-01-01", 5, tz=None)
        
        cleaned, report = cleaner.clean(df, symbol="TEST")
        
        assert report["passed"] is True
        assert cleaned.index.tz is not None
        assert str(cleaned.index.tz) == MARKET_TZ
        assert len(cleaned) == 5

    def test_clean_valid_tz_aware(self) -> None:
        """Tz-aware index should be converted to MARKET_TZ."""
        cleaner = DataCleaner()
        df = generate_test_df("2025-01-01", 5, tz="UTC")
        
        cleaned, report = cleaner.clean(df, symbol="TEST")
        
        assert report["passed"] is True
        assert str(cleaned.index.tz) == MARKET_TZ

    def test_clean_duplicates_removed(self) -> None:
        """Duplicate index entries should be removed (keeping the last one)."""
        cleaner = DataCleaner()
        df = generate_test_df("2025-01-01", 4, tz=None, with_duplicates=True)
        
        cleaned, report = cleaner.clean(df, symbol="TEST")
        
        assert report["duplicates_removed"] == 1
        assert len(cleaned) == 3

    def test_clean_gap_filling(self) -> None:
        """NaN values should be filled or resolved up to max_gap_fill_days."""
        cleaner = DataCleaner(max_gap_fill_days=2)
        df = generate_test_df("2025-01-01", 3, tz=None, with_nans=True)
        
        cleaned, report = cleaner.clean(df, symbol="TEST")
        
        assert report["passed"] is True
        assert cleaned["close"].isna().sum() == 0  # Replaced close via ffill
        assert cleaned["volume"].isna().sum() == 0  # Replaced volume with 0
        assert cleaned.loc[cleaned.index[1], "volume"] == 0

    def test_validation_errors_triggered(self) -> None:
        """Should raise ValidationError if clean data is completely corrupt."""
        cleaner = DataCleaner()
        
        # High < Low check
        df = generate_test_df("2025-01-01", 1)
        df["high"] = 50.0
        df["low"] = 150.0
        
        _, report = cleaner.clean(df, symbol="TEST")
        assert len(report["validation_warnings"]) > 0
        assert any("High < Low" in w for w in report["validation_warnings"])


# ---------------------------------------------------------------------------
# Tests: DataStore
# ---------------------------------------------------------------------------
class TestDataStoreUnit:
    """Unit tests for DataStore."""

    def test_save_new_file(self, tmp_path: Path) -> None:
        """Saving a ticker should write a parquet file correctly."""
        store = DataStore(raw_dir=tmp_path)
        df = generate_test_df("2025-01-01", 5, tz=MARKET_TZ)
        
        path = store.save("TEST", df)
        assert path.exists()
        assert path.name == "TEST.parquet"

        # Read back and check timezone
        loaded = store.load("TEST")
        assert loaded.index.tz is None  # Saved as naive UTC
        assert len(loaded) == 5

    def test_save_merges_existing_data(self, tmp_path: Path) -> None:
        """Saving should merge new data with existing data, resolving overlaps."""
        store = DataStore(raw_dir=tmp_path)
        
        # First chunk
        df1 = generate_test_df("2025-01-01", 3, tz=MARKET_TZ)
        store.save("TEST", df1)
        
        # Second chunk overlaps on the 3rd day, adds 4th day
        # Day 3 has different price to verify merge prefers new data (keep="last")
        df2 = generate_test_df("2025-01-03", 2, tz=MARKET_TZ)
        df2.loc[df2.index[0], "close"] = 999.0
        
        store.save("TEST", df2)
        
        # Load with tz to ensure index aligns to Eastern midnight
        loaded = store.load("TEST", tz=MARKET_TZ)
        
        # 1st, 2nd, 3rd, 4th days in total
        assert len(loaded) == 4
        # Verify 3rd day has the updated price
        target_date = pd.Timestamp("2025-01-03", tz=MARKET_TZ)
        assert loaded.loc[target_date, "close"] == 999.0

    def test_load_non_existent_raises(self, tmp_path: Path) -> None:
        """Loading a missing symbol should raise StoreError."""
        store = DataStore(raw_dir=tmp_path)
        with pytest.raises(StoreError):
            store.load("MISSING")

    def test_date_range_slicing(self, tmp_path: Path) -> None:
        """Loading with date range filters should return slices correctly."""
        store = DataStore(raw_dir=tmp_path)
        df = generate_test_df("2025-01-01", 10, tz=MARKET_TZ)
        store.save("TEST", df)
        
        # Load with tz to ensure index aligns to Eastern midnight
        loaded = store.load("TEST", start="2025-01-03", end="2025-01-06", tz=MARKET_TZ)
        assert len(loaded) == 4
        assert loaded.index.min() == pd.Timestamp("2025-01-03", tz=MARKET_TZ)
        assert loaded.index.max() == pd.Timestamp("2025-01-06", tz=MARKET_TZ)

    def test_load_with_timezone(self, tmp_path: Path) -> None:
        """Loading with tz parameter should return a tz-aware DataFrame normalized to the target tz."""
        store = DataStore(raw_dir=tmp_path)
        df = generate_test_df("2025-01-01", 5, tz=MARKET_TZ)
        store.save("TEST", df)
        
        loaded = store.load("TEST", tz=MARKET_TZ)
        assert loaded.index.tz is not None
        assert str(loaded.index.tz) == MARKET_TZ
