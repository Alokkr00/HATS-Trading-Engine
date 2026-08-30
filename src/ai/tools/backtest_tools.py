"""Backtesting tool wrappers for H.A.T.S AI Copilot."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
import pandas as pd
import yfinance as yf

from src.backtest.engine import BacktestEngine
from src.backtest.cost import CostModel
from src.strategy.strategies import (
    MACrossoverStrategy,
    RSIMeanReversionStrategy,
    BollingerSqueezeStrategy,
    DonchianChannelBreakoutStrategy,
    LinearRegressionChannelStrategy,
    ZScoreMeanReversionStrategy,
)

logger = logging.getLogger(__name__)

STRATEGY_MAP = {
    "macrossover": (MACrossoverStrategy, {"fast_period": 20, "slow_period": 50}),
    "rsi_reversion": (RSIMeanReversionStrategy, {"rsi_period": 14, "oversold": 30, "overbought": 70}),
    "bb_squeeze": (BollingerSqueezeStrategy, {"bb_length": 20, "bb_std": 2.0, "kc_length": 20, "kc_mult": 1.5}),
    "donchian": (DonchianChannelBreakoutStrategy, {"lookback": 20}),
    "linreg": (LinearRegressionChannelStrategy, {"period": 20, "std_devs": 2.0}),
    "zscore": (ZScoreMeanReversionStrategy, {"period": 20, "entry_z": 2.0, "exit_z": 0.0}),
}


def run_strategy_backtest(
    strategy_name: str = "donchian",
    symbol: str = "SPY",
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
    capital: float = 100000.0,
    custom_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a realistic vectorized backtest for a strategy on historical OHLCV data.

    Args:
        strategy_name: Name of strategy ('donchian', 'macrossover', 'rsi_reversion', 'linreg', 'zscore').
        symbol: Ticker symbol (e.g. 'SPY', 'QQQ', 'AAPL').
        start_date: Backtest start date YYYY-MM-DD.
        end_date: Backtest end date YYYY-MM-DD.
        capital: Starting capital in dollars.
        custom_params: Optional dict overriding default strategy parameters.

    Returns:
        Dict with CAGR %, Sharpe Ratio, Max Drawdown %, Win Rate %, Total Trades, and Cost Model specs.
    """
    strat_key = strategy_name.lower().replace(" ", "_").replace("-", "_")
    strat_tuple = STRATEGY_MAP.get(strat_key, STRATEGY_MAP["donchian"])
    strat_cls, default_params = strat_tuple

    params = {**default_params, **(custom_params or {})}

    try:
        data = yf.download(symbol, start=start_date, end=end_date, progress=False)
        if data.empty:
            return {"status": "error", "error": f"No data retrieved for symbol {symbol}"}

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [c[0] for c in data.columns]
        data = data.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})

        if data.index.tz is None:
            data.index = data.index.tz_localize("America/New_York")
        else:
            data.index = data.index.tz_convert("America/New_York")

        strategy = strat_cls(params)
        cost_model = CostModel(spread_bps=1.5, slippage_bps=3.0)
        engine = BacktestEngine(strategy=strategy, capital=capital, cost_model=cost_model)

        res = engine.run_vectorized(data)
        metrics = res.get("metrics", {})

        return {
            "status": "success",
            "strategy": strat_key,
            "symbol": symbol,
            "cagr_pct": round(metrics.get("cagr", 0.0) * 100.0, 2),
            "sharpe_ratio": round(metrics.get("sharpe", 0.0), 2),
            "sortino_ratio": round(metrics.get("sortino", 0.0), 2),
            "max_drawdown_pct": round(metrics.get("max_drawdown", 0.0) * 100.0, 2),
            "win_rate_pct": round(metrics.get("win_rate", 0.0) * 100.0, 2),
            "profit_factor": round(metrics.get("profit_factor", 0.0), 2),
            "total_trades": metrics.get("total_trades", 0),
            "cost_model": "1.5 bps spread + 3.0 bps slippage per trade",
            "period": f"{start_date} to {end_date}",
        }
    except Exception as e:
        logger.error(f"Error in backtest tool for {strategy_name} on {symbol}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "strategy": strategy_name,
            "symbol": symbol,
        }
