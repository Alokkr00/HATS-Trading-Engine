"""Custom exceptions for the data layer.

All data-related errors inherit from DataError so callers can
catch broad or specific failures.
"""


class DataError(Exception):
    """Base exception for all data-layer errors."""


class FetchError(DataError):
    """Raised when data fetching fails (network, API, invalid symbol)."""


class InvalidSymbolError(FetchError):
    """Raised when the requested ticker symbol is invalid or delisted."""


class RateLimitError(FetchError):
    """Raised when the upstream API rate limit is hit."""


class ValidationError(DataError):
    """Raised when data fails quality validation checks."""


class StoreError(DataError):
    """Raised when data storage read/write operations fail."""
