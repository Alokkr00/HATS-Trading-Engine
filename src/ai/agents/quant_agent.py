"""Quant Analyst Agent: Formulates systematic trade ideas and verifies historical backtests."""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from src.ai.schemas import TradeIdea, BacktestMetricReport
from src.ai.tools.backtest_tools import run_strategy_backtest

logger = logging.getLogger(__name__)


class QuantAgent:
    """Agent responsible for quantitative modeling, strategy selection, and backtesting."""

    def run(
        self,
        query: str,
        symbol: str = "SPY",
        regime_info: Dict[str, Any] | None = None,
        ticker_summary: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Formulate trade ideas and execute backtest validation."""
        logger.info(f"QuantAgent formulating strategies for {symbol}")

        regime = regime_info or {}
        ticker = ticker_summary or {}
        curr_price = ticker.get("latest_close", 500.0)
        atr = ticker.get("atr14", 5.0)

        # Determine strategy to backtest based on query or regime
        strat_name = "donchian"
        if "rsi" in query.lower() or "mean reversion" in query.lower():
            strat_name = "rsi_reversion"
        elif "ma" in query.lower() or "crossover" in query.lower():
            strat_name = "macrossover"
        elif "linear" in query.lower() or "channel" in query.lower():
            strat_name = "linreg"
        elif "zscore" in query.lower() or "z-score" in query.lower():
            strat_name = "zscore"

        # 1. Run real deterministic backtest
        bt_res = run_strategy_backtest(strategy_name=strat_name, symbol=symbol)
        
        benchmarks = []
        if bt_res.get("status") == "success":
            benchmarks.append(BacktestMetricReport(
                strategy=bt_res.get("strategy", strat_name),
                symbol=symbol,
                cagr_pct=bt_res.get("cagr_pct", 0.0),
                sharpe_ratio=bt_res.get("sharpe_ratio", 0.0),
                max_drawdown_pct=bt_res.get("max_drawdown_pct", 0.0),
                win_rate_pct=bt_res.get("win_rate_pct", 0.0),
                total_trades=bt_res.get("total_trades", 0),
            ))

        # 2. Formulate grounded trade idea
        action = "BUY" if ticker.get("latest_close", 0) >= ticker.get("sma200", 0) else "HOLD"
        stop_loss = round(curr_price - (2.0 * atr), 2) if action == "BUY" else None
        take_profit = round(curr_price + (3.0 * atr), 2) if action == "BUY" else None

        trade_ideas = [
            TradeIdea(
                action=action,
                symbol=symbol,
                strategy=strat_name,
                suggested_entry=curr_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size_pct=0.05,
                rationale=f"Model recommendation based on {strat_name} strategy aligned with {regime.get('regime_state', 'BULL_NORMAL')} market regime."
            )
        ]

        return {
            "trade_ideas": trade_ideas,
            "backtests": benchmarks,
        }


quant_agent = QuantAgent()
