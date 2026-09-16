"""Black-Scholes-Merton options pricing model and Greeks calculations."""

from __future__ import annotations

import datetime as dt
import math

def norm_cdf(x: float) -> float:
    """Cumulative distribution function of standard normal distribution."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def calculate_option_price_and_delta(
    S: float,
    K: float,
    T: float,
    r: float = 0.05,
    sigma: float = 0.3,
    option_type: str = "C"
) -> tuple[float, float]:
    """Calculate Black-Scholes option price and delta.
    
    Args:
        S: Underlying asset price
        K: Option strike price
        T: Time to expiry in years
        r: Risk-free interest rate (annualized)
        sigma: Volatility (annualized)
        option_type: 'C' for Call, 'P' for Put
    """
    # Edge case: option expired or zero time remaining
    if T <= 0.0:
        if option_type == "C":
            val = max(0.0, S - K)
            delta = 1.0 if S > K else 0.0
        else:
            val = max(0.0, K - S)
            delta = -1.0 if S < K else 0.0
        return val, delta

    # Prevent math domain/div errors for zero values
    if S <= 0.0 or K <= 0.0 or sigma <= 0.0:
        return 0.0, 0.0

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type == "C":
        price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
        delta = norm_cdf(d1)
    else:
        price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
        delta = norm_cdf(d1) - 1.0

    return max(0.0, price), delta


import re

_OCC_OPTION_REGEX = re.compile(
    r"^([A-Za-z]{1,6})\s*(\d{2})(\d{2})(\d{2})([CPcp])(\d{8})$"
)


def parse_option_symbol(symbol: str, current_time: dt.datetime | None = None) -> tuple[str, str, float, float]:
    """Parse standard OCC option symbol to extract parameters.
    
    Example: TSLA260717C00392500 -> ('TSLA', 'C', 392.5, T_in_years)
    Handles tickers containing 'C' or 'P' (e.g. CAT, COP, C, CRM, PFE, PYPL)
    without misidentifying the underlying vs option type.
    """
    now = current_time or dt.datetime.now()
    clean_sym = symbol.strip().upper()

    match = _OCC_OPTION_REGEX.match(clean_sym)
    if match:
        underlying = match.group(1).upper()
        yy = int(match.group(2)) + 2000
        mm = int(match.group(3))
        dd = int(match.group(4))
        char_type = match.group(5).upper()
        strike_raw = match.group(6)
        strike = float(strike_raw) / 1000.0

        try:
            exp_date = dt.datetime(yy, mm, dd)
            days_to_expiry = (exp_date - now).days
            T = max(0.0, days_to_expiry / 365.0)
        except Exception:
            T = 0.0

        return underlying, char_type, strike, T

    # Fallback for non-padded or loose option symbols:
    # Look for 6 date digits followed by C/P and strike digits at the end
    loose_match = re.search(r"(\d{6})([CPcp])(\d+)$", clean_sym)
    if loose_match:
        prefix_end = loose_match.start()
        underlying = clean_sym[:prefix_end].strip().upper()
        date_str = loose_match.group(1)
        char_type = loose_match.group(2).upper()
        strike_str = loose_match.group(3)

        try:
            yy = int(date_str[:2]) + 2000
            mm = int(date_str[2:4])
            dd = int(date_str[4:])
            exp_date = dt.datetime(yy, mm, dd)
            T = max(0.0, (exp_date - now).days / 365.0)
        except Exception:
            T = 0.0

        try:
            strike = float(strike_str) / 1000.0 if len(strike_str) >= 6 else float(strike_str)
        except Exception:
            strike = 0.0

        return underlying, char_type, strike, T

    return clean_sym, "C", 0.0, 0.0

