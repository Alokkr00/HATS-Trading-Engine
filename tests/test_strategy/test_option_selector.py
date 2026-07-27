"""Unit tests for the option_selector.py module."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from src.strategy.option_selector import select_option


@patch("src.strategy.option_selector.yf.Ticker")
def test_select_option_success(mock_ticker_cls) -> None:
    """Test successful ATM Call option contract selection from yfinance options chain."""
    mock_ticker = MagicMock()
    mock_ticker_cls.return_value = mock_ticker

    # Mock expirations list (options)
    mock_ticker.options = ["2026-07-10", "2026-07-17", "2026-07-24"]

    # Mock option chain call
    mock_chain = MagicMock()
    mock_ticker.option_chain.return_value = mock_chain

    # Mock calls DataFrame (At-The-Money Call closest to 150)
    mock_calls_df = pd.DataFrame({
        "contractSymbol": ["AAPL260717C00140000", "AAPL260717C00150000", "AAPL260717C00160000"],
        "strike": [140.0, 150.0, 160.0],
        "lastPrice": [12.50, 4.20, 1.10],
        "bid": [12.40, 4.10, 1.05],
        "ask": [12.60, 4.30, 1.15]
    })
    mock_chain.calls = mock_calls_df

    # Target: underlying stock price is $151.0
    # Strike closest to 151 is 150.0. Expiry closest to 14 days is 2026-07-17 (14 days from today if mock is set)
    res = select_option(symbol="AAPL", side="BUY", current_price=151.0, target_days_out=14)
    
    assert res is not None
    assert res["contract_symbol"] == "AAPL260717C00150000"
    assert res["strike"] == 150.0
    assert res["last_price"] == 4.20
    assert res["underlying"] == "AAPL"


@patch("src.strategy.option_selector.yf.Ticker")
def test_select_option_empty_expirations(mock_ticker_cls) -> None:
    """Test select_option returns None if no option expirations exist."""
    mock_ticker = MagicMock()
    mock_ticker_cls.return_value = mock_ticker
    mock_ticker.options = []

    res = select_option(symbol="AAPL", side="BUY", current_price=150.0)
    assert res is None
