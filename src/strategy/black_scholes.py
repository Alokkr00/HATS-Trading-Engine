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


def parse_option_symbol(symbol: str, current_time: dt.datetime | None = None) -> tuple[str, str, float, float]:
    """Parse standard OCC option symbol to extract parameters.
    
    Example: TSLA260717C00392500 -> ('TSLA', 'C', 392.5, T_in_years)
    """
    now = current_time or dt.datetime.now()
    for char_type in ["C", "P"]:
        if char_type in symbol:
            c_idx = symbol.find(char_type)
            # Ticker underlying
            underlying = symbol[:c_idx-6] if c_idx >= 6 else symbol[:c_idx]
            # Expiry date part (YYMMDD)
            exp_str = symbol[c_idx-6:c_idx] if c_idx >= 6 else ""
            
            # Time to expiry (T)
            T = 0.0
            if exp_str.isdigit() and len(exp_str) == 6:
                try:
                    yy = int(exp_str[:2]) + 2000
                    mm = int(exp_str[2:4])
                    dd = int(exp_str[4:])
                    exp_date = dt.datetime(yy, mm, dd)
                    days_to_expiry = (exp_date - now).days
                    T = max(0.0, days_to_expiry / 365.0)
                except Exception:
                    pass
            
            # Strike price
            try:
                strike = float(symbol[c_idx+1:]) / 1000.0
            except Exception:
                strike = 0.0
                
            return underlying, char_type, strike, T
            
    return symbol, "C", 0.0, 0.0
