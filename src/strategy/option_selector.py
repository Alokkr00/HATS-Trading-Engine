"""Option Selector module to select At-The-Money Call/Put contracts using yfinance."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any
import pandas as pd
import yfinance as yf

import numpy as np

logger = logging.getLogger(__name__)


def select_option(
    symbol: str,
    side: str,
    current_price: float,
    min_days_out: int = 10,
    target_days_out: int = 14,
) -> dict[str, Any] | None:
    """
    Selects the At-The-Money (ATM) Call or Put option contract for the given symbol.
    
    Args:
        symbol: Underlying ticker symbol (e.g. "AAPL")
        side: Trading side ("BUY" -> Call, "SELL" -> Put)
        current_price: Last closing price of the underlying stock
        min_days_out: Minimum calendar days to expiration
        target_days_out: Preferred calendar days to expiration
        
    Returns:
        A dictionary containing:
            - 'contract_symbol' (str): The OSI option ticker (e.g. "AAPL260717C00200000")
            - 'strike' (float): The strike price
            - 'expiry' (str): Expiration date (YYYY-MM-DD)
            - 'last_price' (float): Option premium price
            - 'bid' (float): Option bid price
            - 'ask' (float): Option ask price
            - 'underlying' (str): Underlying symbol
        Or None if resolution fails.
    """
    try:
        ticker = yf.Ticker(symbol)
        expirations = ticker.options
        if not expirations:
            logger.warning(f"No option expirations found for {symbol}.")
            return None
            
        # Parse expirations to datetimes and filter for >= min_days_out
        today = dt.date.today()
        valid_expiries = []
        for exp in expirations:
            try:
                exp_date = dt.datetime.strptime(exp, "%Y-%m-%d").date()
                days_to_exp = (exp_date - today).days
                if days_to_exp >= min_days_out:
                    valid_expiries.append((exp, days_to_exp))
            except ValueError:
                continue
                
        if not valid_expiries:
            # Fallback to the first available expiry if none satisfy the minimum
            valid_expiries = [(expirations[0], 0)]
            
        # Select expiry closest to target_days_out
        selected_expiry = min(valid_expiries, key=lambda x: abs(x[1] - target_days_out))[0]
        logger.debug(f"Selected option expiration {selected_expiry} for {symbol}.")
        
        # Fetch option chain
        chain = ticker.option_chain(selected_expiry)
        options_df = chain.calls if side.upper() == "BUY" else chain.puts
        
        if options_df.empty:
            logger.warning(f"No option contracts found in option chain for {symbol} on {selected_expiry}.")
            return None
            
        # Filter for liquidity
        min_open_interest = 100
        min_volume = 50
        max_spread_pct = 0.20
        
        liquid_df = options_df.copy()
        
        # Handle NaN values in volume/openInterest columns
        if "openInterest" in liquid_df.columns:
            liquid_df["openInterest"] = liquid_df["openInterest"].fillna(0.0)
            liquid_df = liquid_df[liquid_df["openInterest"] >= min_open_interest]
        if "volume" in liquid_df.columns:
            liquid_df["volume"] = liquid_df["volume"].fillna(0.0)
            liquid_df = liquid_df[liquid_df["volume"] >= min_volume]
            
        # Filter for narrow spread
        if not liquid_df.empty and "bid" in liquid_df.columns and "ask" in liquid_df.columns and "lastPrice" in liquid_df.columns:
            liquid_df["spread_pct"] = (liquid_df["ask"] - liquid_df["bid"]) / liquid_df["lastPrice"].replace(0, np.nan)
            liquid_df = liquid_df[liquid_df["spread_pct"] <= max_spread_pct]
            
        if liquid_df.empty:
            logger.warning(
                f"No option contracts satisfied the liquidity filters (Open Interest >= {min_open_interest}, "
                f"Volume >= {min_volume}, Spread <= {max_spread_pct * 100}%). Falling back to standard ATM contract."
            )
            use_df = options_df
        else:
            use_df = liquid_df
            
        # Find the contract with strike closest to current_price
        use_df = use_df.copy()
        use_df["strike_diff"] = (use_df["strike"] - current_price).abs()
        atm_contract = use_df.loc[use_df["strike_diff"].idxmin()]
        
        contract_symbol = atm_contract["contractSymbol"]
        strike = float(atm_contract["strike"])
        last_price = float(atm_contract["lastPrice"])
        bid = float(atm_contract.get("bid", last_price))
        ask = float(atm_contract.get("ask", last_price))
        
        logger.info(
            f"Selected ATM {side.upper()} contract for {symbol}: {contract_symbol} "
            f"(Strike: {strike}, Expiry: {selected_expiry}, Premium: ${last_price:.2f})"
        )
        
        return {
            "contract_symbol": contract_symbol,
            "strike": strike,
            "expiry": selected_expiry,
            "last_price": last_price,
            "bid": bid,
            "ask": ask,
            "underlying": symbol,
        }
        
    except Exception as e:
        logger.error(f"Failed to resolve option contract for {symbol}: {e}", exc_info=True)
        return None
