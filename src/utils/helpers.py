"""General-purpose trading utilities (zero external dependencies).

All time-aware functions use the **America/New_York** timezone via the
standard-library :mod:`zoneinfo` module (Python 3.9+).

Holiday calendar covers **2024-2026** for NYSE/NASDAQ observed closures.
Extend ``_US_MARKET_HOLIDAYS`` when rolling into a new year.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ET = ZoneInfo("America/New_York")

_MARKET_OPEN = dt.time(9, 30)
_MARKET_CLOSE = dt.time(16, 0)

# NYSE / NASDAQ observed holidays (confirmed schedule).
# Sources: NYSE Rule 7.2, SIFMA.
# fmt: off
_US_MARKET_HOLIDAYS: frozenset[dt.date] = frozenset({
    # ---- 2024 ----
    dt.date(2024, 1, 1),   # New Year's Day
    dt.date(2024, 1, 15),  # MLK Jr. Day
    dt.date(2024, 2, 19),  # Presidents' Day
    dt.date(2024, 3, 29),  # Good Friday
    dt.date(2024, 5, 27),  # Memorial Day
    dt.date(2024, 6, 19),  # Juneteenth
    dt.date(2024, 7, 4),   # Independence Day
    dt.date(2024, 9, 2),   # Labor Day
    dt.date(2024, 11, 28), # Thanksgiving Day
    dt.date(2024, 12, 25), # Christmas Day

    # ---- 2025 ----
    dt.date(2025, 1, 1),   # New Year's Day
    dt.date(2025, 1, 9),   # National Day of Mourning (Jimmy Carter)
    dt.date(2025, 1, 20),  # MLK Jr. Day
    dt.date(2025, 2, 17),  # Presidents' Day
    dt.date(2025, 4, 18),  # Good Friday
    dt.date(2025, 5, 26),  # Memorial Day
    dt.date(2025, 6, 19),  # Juneteenth
    dt.date(2025, 7, 4),   # Independence Day
    dt.date(2025, 9, 1),   # Labor Day
    dt.date(2025, 11, 27), # Thanksgiving Day
    dt.date(2025, 12, 25), # Christmas Day

    # ---- 2026 ----
    dt.date(2026, 1, 1),   # New Year's Day
    dt.date(2026, 1, 19),  # MLK Jr. Day
    dt.date(2026, 2, 16),  # Presidents' Day
    dt.date(2026, 4, 3),   # Good Friday
    dt.date(2026, 5, 25),  # Memorial Day
    dt.date(2026, 6, 19),  # Juneteenth
    dt.date(2026, 7, 3),   # Independence Day (observed — Jul 4 is Sat)
    dt.date(2026, 9, 7),   # Labor Day
    dt.date(2026, 11, 26), # Thanksgiving Day
    dt.date(2026, 12, 25), # Christmas Day

    # ---- 2027 ----
    dt.date(2027, 1, 1),   # New Year's Day
    dt.date(2027, 1, 18),  # MLK Jr. Day
    dt.date(2027, 2, 15),  # Presidents' Day
    dt.date(2027, 3, 26),  # Good Friday
    dt.date(2027, 5, 31),  # Memorial Day
    dt.date(2027, 6, 18),  # Juneteenth (observed — Jun 19 is Sat)
    dt.date(2027, 7, 5),   # Independence Day (observed — Jul 4 is Sun)
    dt.date(2027, 9, 6),   # Labor Day
    dt.date(2027, 11, 25), # Thanksgiving Day
    dt.date(2027, 12, 24), # Christmas Day (observed — Dec 25 is Sat)

    # ---- 2028 ----
    dt.date(2028, 1, 17),  # MLK Jr. Day
    dt.date(2028, 2, 21),  # Presidents' Day
    dt.date(2028, 4, 14),  # Good Friday
    dt.date(2028, 5, 29),  # Memorial Day
    dt.date(2028, 6, 19),  # Juneteenth
    dt.date(2028, 7, 4),   # Independence Day
    dt.date(2028, 9, 4),   # Labor Day
    dt.date(2028, 11, 23), # Thanksgiving Day
    dt.date(2028, 12, 25), # Christmas Day
})
# fmt: on


# ---------------------------------------------------------------------------
# Market-calendar helpers
# ---------------------------------------------------------------------------


def is_market_open(now: dt.datetime | None = None) -> bool:
    """Check whether the US stock market (NYSE) is currently in session.

    Rules applied (in order):
        1. Weekends → closed.
        2. Observed US market holidays → closed.
        3. Outside 09:30–16:00 ET → closed.

    Args:
        now: An *aware* datetime to test.  Defaults to the current wall-clock
            time in Eastern Time if ``None``.

    Returns:
        ``True`` if the market is open at the given moment.

    Example::

        >>> is_market_open()  # live check
        False
    """
    if now is None:
        now = dt.datetime.now(tz=_ET)
    else:
        # Normalise to Eastern regardless of what tz the caller provides.
        now = now.astimezone(_ET)

    # Weekend check (Mon=0 … Sun=6)
    if now.weekday() >= 5:
        return False

    # Holiday check
    if now.date() in _US_MARKET_HOLIDAYS:
        return False

    # Intraday window
    current_time = now.time()
    return _MARKET_OPEN <= current_time < _MARKET_CLOSE


def is_trading_day(day: dt.date) -> bool:
    """Return ``True`` if *day* is a regular NYSE trading session.

    Args:
        day: The calendar date to check.

    Returns:
        ``True`` when *day* is a weekday **and** not an observed holiday.
    """
    return day.weekday() < 5 and day not in _US_MARKET_HOLIDAYS


def get_trading_days(
    start: dt.date | str,
    end: dt.date | str,
) -> list[dt.date]:
    """Return an inclusive list of NYSE trading days between *start* and *end*.

    Args:
        start: First date (inclusive).  Accepts ``date`` or ISO-8601 string.
        end: Last date (inclusive).  Accepts ``date`` or ISO-8601 string.

    Returns:
        Sorted list of :class:`datetime.date` objects.

    Raises:
        ValueError: If *start* is after *end*.

    Example::

        >>> get_trading_days("2024-12-23", "2024-12-27")
        [datetime.date(2024, 12, 23), datetime.date(2024, 12, 24),
         datetime.date(2024, 12, 26), datetime.date(2024, 12, 27)]
    """
    if isinstance(start, str):
        start = dt.date.fromisoformat(start)
    if isinstance(end, str):
        end = dt.date.fromisoformat(end)

    if start > end:
        raise ValueError(
            f"start ({start.isoformat()}) must be <= end ({end.isoformat()})"
        )

    days: list[dt.date] = []
    current = start
    one_day = dt.timedelta(days=1)
    while current <= end:
        if is_trading_day(current):
            days.append(current)
        current += one_day
    return days


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_currency(value: float | int) -> str:
    """Format a numeric value as US-dollar currency.

    Args:
        value: Dollar amount.

    Returns:
        String like ``"$1,234.56"`` or ``"-$1,234.56"`` for negatives.

    Example::

        >>> format_currency(1234.5)
        '$1,234.50'
        >>> format_currency(-99)
        '-$99.00'
    """
    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


def format_pct(value: float | int, decimals: int = 2) -> str:
    """Format a numeric value as a signed percentage string.

    Args:
        value: Percentage value (e.g. ``12.345`` → ``"+12.35%"``).
        decimals: Decimal places (default 2).

    Returns:
        String like ``"+12.35%"`` or ``"-5.67%"``.

    Example::

        >>> format_pct(12.345)
        '+12.35%'
        >>> format_pct(-5.678, decimals=1)
        '-5.7%'
    """
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}%"


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def ensure_dir(path: str | Path) -> Path:
    """Create a directory (including parents) if it does not exist.

    Args:
        path: Directory path to ensure.

    Returns:
        The resolved :class:`Path` object.

    Example::

        >>> p = ensure_dir("data/raw")
        >>> p.is_dir()
        True
    """
    p = Path(path).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Position dictionary normalization
# ---------------------------------------------------------------------------


def normalize_position(pos: dict[str, Any] | Any) -> dict[str, Any]:
    """Normalize a position dictionary or object to a standard canonical schema.

    Guarantees that both 'qty' and 'quantity', and both 'cost_price' and 'avg_price'
    are present and populated with standard numeric types. Also ensures 'symbol'
    and 'sector' keys exist.

    Args:
        pos: Dict or object representing a held position.

    Returns:
        Canonical position dict with consistent keys.
    """
    if not isinstance(pos, dict):
        result: dict[str, Any] = {}
        for attr in ("weight", "percent", "underlying_price", "implied_vol", "sigma", "option_type", "strike"):
            if hasattr(pos, attr):
                result[attr] = getattr(pos, attr)
        raw_qty = getattr(pos, "quantity", getattr(pos, "qty", 0))
        raw_price = getattr(pos, "avg_price", getattr(pos, "cost_price", getattr(pos, "avg_entry_price", 0.0)))
        symbol = getattr(pos, "symbol", "")
        sector = getattr(pos, "sector", "Unknown")
        stop_price = getattr(pos, "stop_price", None)
        market_value = getattr(pos, "market_value", 0.0)
    else:
        result = dict(pos)
        raw_qty = pos.get("quantity") if pos.get("quantity") is not None else pos.get("qty", 0)
        raw_price = pos.get("cost_price") if pos.get("cost_price") is not None else pos.get("avg_price", pos.get("avg_entry_price", 0.0))
        symbol = pos.get("symbol", "")
        sector = pos.get("sector", "Unknown")
        stop_price = pos.get("stop_price")
        market_value = pos.get("market_value", 0.0)

    qty = int(float(raw_qty or 0))
    price = float(raw_price or 0.0)
    stop = float(stop_price) if (stop_price is not None and not str(stop_price).lower() == "none") else None
    val = float(market_value) if market_value else float(qty * price)

    result.update({
        "symbol": str(symbol).strip().upper(),
        "qty": qty,
        "quantity": qty,
        "cost_price": price,
        "avg_price": price,
        "sector": str(sector).strip() if sector else "Unknown",
        "stop_price": stop,
        "market_value": val,
    })
    return result

