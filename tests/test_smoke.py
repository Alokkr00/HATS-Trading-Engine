"""Tests for src/utils (smoke tests rewritten for pytest)."""

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src import __version__
from src.utils import (
    ensure_dir,
    format_currency,
    format_pct,
    get_logger,
    get_trading_days,
    is_market_open,
    is_trading_day,
)


def test_version() -> None:
    """Verify project version import."""
    assert __version__ == "0.1.0"


def test_logger_idempotency() -> None:
    """Verify that get_logger is idempotent and does not duplicate handlers."""
    logger1 = get_logger("test_smoke")
    logger2 = get_logger("test_smoke")

    assert logger1 is logger2
    # Standard logger setup creates console + file handler
    assert len(logger1.handlers) >= 2


def test_format_currency() -> None:
    """Test currency formatting utility."""
    assert format_currency(1234.5) == "$1,234.50"
    assert format_currency(-99) == "-$99.00"
    assert format_currency(0) == "$0.00"


def test_format_pct() -> None:
    """Test percentage formatting utility."""
    assert format_pct(12.345) == "+12.35%"
    assert format_pct(-5.678, decimals=1) == "-5.7%"
    assert format_pct(0) == "+0.00%"


def test_is_trading_day() -> None:
    """Test market trading day checks including weekends and holidays."""
    assert not is_trading_day(dt.date(2025, 12, 25))  # Christmas
    assert not is_trading_day(dt.date(2025, 1, 4))    # Saturday
    assert is_trading_day(dt.date(2025, 3, 4))        # Normal weekday
    assert not is_trading_day(dt.date(2025, 1, 9))    # Carter mourning day


def test_get_trading_days() -> None:
    """Test retrieval of trading days in range."""
    days = get_trading_days("2024-12-23", "2024-12-27")
    assert dt.date(2024, 12, 25) not in days  # Christmas excluded
    assert len(days) == 4

    # Reverse order raises ValueError
    with pytest.raises(ValueError):
        get_trading_days("2025-01-05", "2025-01-01")


def test_ensure_dir(tmp_path: Path) -> None:
    """Test directory creation helper."""
    target_dir = tmp_path / "test_logs"
    assert not target_dir.exists()
    p = ensure_dir(target_dir)
    assert p.is_dir()
    assert p == target_dir


def test_is_market_open() -> None:
    """Test time-based market hours check using tz-aware datetimes."""
    et = ZoneInfo("America/New_York")
    # Open hours
    assert is_market_open(dt.datetime(2025, 3, 5, 10, 0, tzinfo=et)) is True
    # After close
    assert is_market_open(dt.datetime(2025, 3, 5, 17, 0, tzinfo=et)) is False
    # Weekend
    assert is_market_open(dt.datetime(2025, 3, 8, 12, 0, tzinfo=et)) is False
    # Holiday
    assert is_market_open(dt.datetime(2025, 12, 25, 11, 0, tzinfo=et)) is False
