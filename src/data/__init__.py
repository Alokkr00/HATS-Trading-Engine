"""Data layer — fetching, cleaning, and storage for market data.

Public API::

    from src.data import DataFetcher, DataCleaner, DataStore

    fetcher = DataFetcher()
    cleaner = DataCleaner()
    store   = DataStore()
"""

from src.data.cleaner import DataCleaner
from src.data.exceptions import (
    DataError,
    FetchError,
    InvalidSymbolError,
    RateLimitError,
    StoreError,
    ValidationError,
)
from src.data.fetcher import DataFetcher
from src.data.store import DataStore

__all__ = [
    "DataFetcher",
    "DataCleaner",
    "DataStore",
    # Exceptions
    "DataError",
    "FetchError",
    "InvalidSymbolError",
    "RateLimitError",
    "StoreError",
    "ValidationError",
]
