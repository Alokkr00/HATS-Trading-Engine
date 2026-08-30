"""Market data and regime classification tools for H.A.T.S AI Copilot."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
import pandas as pd
import yfinance as yf

from src.strategy.regime import MarketRegimeClassifier
from src.strategy.indicators_math import calculate_hurst_exponent

logger = logging.getLogger(__name__)


def get_market_regime() -> Dict[str, Any]:
    """Classify the current macro market regime using SPY trend and spot VIX.

    Returns:
        Dict with state, size_multiplier, allowed_actions, and Hurst exponent.
    """
    try:
        spy_data = yf.download("SPY", period="1y", progress=False)
        vix_data = yf.download("^VIX", period="5d", progress=False)

        if isinstance(spy_data.columns, pd.MultiIndex):
            spy_data.columns = [c[0] for c in spy_data.columns]
        spy_data = spy_data.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})

        if isinstance(vix_data.columns, pd.MultiIndex):
            vix_data.columns = [c[0] for c in vix_data.columns]

        vix_spot = 18.0
        if not vix_data.empty and "Close" in vix_data.columns:
            val = vix_data["Close"].iloc[-1]
            try:
                vix_spot = float(val.item() if hasattr(val, "item") else val)
            except Exception:
                vix_spot = 18.0

        classifier = MarketRegimeClassifier()
        regime_result = classifier.classify(spy_data, vix_spot)

        # Calculate rolling Hurst exponent on SPY close series
        hurst = 0.50
        try:
            if not spy_data.empty and len(spy_data) >= 100:
                hurst = float(calculate_hurst_exponent(spy_data["close"].values[-100:]))
        except Exception:
            pass

        state_str = regime_result.get("state").value if hasattr(regime_result.get("state"), "value") else str(regime_result.get("state", "BULL_NORMAL"))

        return {
            "status": "success",
            "regime_state": state_str,
            "vix_spot": round(vix_spot, 2),
            "hurst_exponent": round(hurst, 3),
            "market_structure": "Trending / Persistent" if hurst > 0.55 else ("Mean-Reverting / Anti-persistent" if hurst < 0.45 else "Random Walk"),
            "size_multiplier": regime_result.get("size_multiplier", 1.0),
            "allowed_actions": regime_result.get("allowed_actions", ["BUY", "SELL"]),
        }
    except Exception as e:
        logger.error(f"Error in get_market_regime: {e}")
        return {
            "status": "error",
            "regime_state": "BULL_NORMAL",
            "vix_spot": 18.0,
            "hurst_exponent": 0.50,
            "market_structure": "Random Walk",
            "size_multiplier": 1.0,
            "allowed_actions": ["BUY", "SELL"],
            "error": str(e),
        }


def fetch_ticker_data_summary(symbol: str = "SPY") -> Dict[str, Any]:
    """Fetch current technical summary and price levels for a symbol.

    Args:
        symbol: Ticker symbol (e.g. 'SPY', 'AAPL').

    Returns:
        Dict with latest close, 20 SMA, 200 SMA, 14 RSI, ATR, and 52-week range.
    """
    try:
        df = yf.download(symbol, period="1y", progress=False)
        if df.empty:
            return {"status": "error", "error": f"No data found for {symbol}"}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        close = df["Close"]
        high = df["High"]
        low = df["Low"]

        latest_close = float(close.iloc[-1])
        sma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else latest_close
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else latest_close
        
        # 14-day RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0.0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss.replace(0, 0.0001)
        rsi14 = float(100.0 - (100.0 / (1.0 + rs)).iloc[-1])

        # 14-day ATR
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else 1.0

        return {
            "status": "success",
            "symbol": symbol,
            "latest_close": round(latest_close, 2),
            "sma20": round(sma20, 2),
            "sma200": round(sma200, 2),
            "rsi14": round(rsi14, 2),
            "atr14": round(atr14, 2),
            "52w_high": round(float(high.max()), 2),
            "52w_low": round(float(low.min()), 2),
        }
    except Exception as e:
        logger.error(f"Error fetching ticker summary for {symbol}: {e}")
        return {"status": "error", "error": str(e), "symbol": symbol}
