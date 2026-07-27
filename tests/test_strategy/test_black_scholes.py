import datetime as dt
import pytest
import math
from src.strategy.black_scholes import (
    norm_cdf,
    calculate_option_price_and_delta,
    parse_option_symbol,
)

def test_norm_cdf():
    # Mean of standard normal is 0.5 at x=0
    assert pytest.approx(norm_cdf(0.0), abs=1e-6) == 0.5
    # Standard 1.96 standard deviations cover ~97.5% cumulative density
    assert pytest.approx(norm_cdf(1.96), abs=1e-2) == 0.975
    assert pytest.approx(norm_cdf(-1.96), abs=1e-2) == 0.025


def test_calculate_option_price_and_delta():
    # Test ATM Option
    # S=100, K=100, T=1 year, r=5%, sigma=30%
    call_price, call_delta = calculate_option_price_and_delta(
        S=100.0, K=100.0, T=1.0, r=0.05, sigma=0.30, option_type="C"
    )
    # Expected call price is roughly $14.23 and delta is roughly 0.60
    assert call_price > 12.0 and call_price < 16.0
    assert call_delta > 0.55 and call_delta < 0.65

    put_price, put_delta = calculate_option_price_and_delta(
        S=100.0, K=100.0, T=1.0, r=0.05, sigma=0.30, option_type="P"
    )
    # Put-Call Parity: C - P = S - K * exp(-r*T)
    # 14.23 - P = 100 - 100 * exp(-0.05) = 100 - 95.12 = 4.88 -> P = 9.35
    assert put_price > 8.0 and put_price < 11.0
    assert put_delta > -0.45 and put_delta < -0.35
    assert pytest.approx(call_price - put_price, abs=1e-4) == 100.0 - 100.0 * math.exp(-0.05)


def test_black_scholes_expired_and_edges():
    # Expired Call Option: T=0, S=105, K=100 -> intrinsic price is 5.0, delta is 1.0
    price, delta = calculate_option_price_and_delta(S=105.0, K=100.0, T=0.0, option_type="C")
    assert price == 5.0
    assert delta == 1.0

    # Expired Put Option: T=0, S=95, K=100 -> intrinsic price is 5.0, delta is -1.0
    price, delta = calculate_option_price_and_delta(S=95.0, K=100.0, T=0.0, option_type="P")
    assert price == 5.0
    assert delta == -1.0

    # Underflow/zero checks
    price, delta = calculate_option_price_and_delta(S=0.0, K=100.0, T=0.5)
    assert price == 0.0
    assert delta == 0.0


def test_parse_option_symbol():
    # Sample symbol: TSLA260717C00392500
    # YYMMDD = 260717 -> July 17, 2026
    # Strike = 00392500 -> 392.5
    now_date = dt.datetime(2026, 1, 17) # 6 months before expiry
    underlying, opt_type, strike, T = parse_option_symbol("TSLA260717C00392500", current_time=now_date)
    
    assert underlying == "TSLA"
    assert opt_type == "C"
    assert strike == 392.5
    # T should be roughly 181 days / 365.0 = ~0.495 years
    assert pytest.approx(T, abs=1e-2) == 0.495
