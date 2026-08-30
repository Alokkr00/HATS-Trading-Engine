"""Risk Engine tool wrappers for H.A.T.S AI Copilot."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from src.risk.margin import PortfolioMarginSimulator
from src.risk.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


def stress_test_portfolio(
    positions: Optional[List[Dict[str, Any]]] = None,
    account_equity: float = 100000.0,
    max_stress_loss_pct: float = 0.15,
) -> Dict[str, Any]:
    """Execute the deterministic 15-scenario stress grid on a set of positions.

    Args:
        positions: List of position dicts. Format:
            [{"symbol": "SPY", "qty": 100, "curr_price": 500.0, "is_option": False}, ...]
        account_equity: Total net portfolio liquidation value.
        max_stress_loss_pct: Maximum allowed stress drawdown (default: 0.15 = 15%).

    Returns:
        Dict with worst_case_loss, worst_case_pct, passed (bool), and scenario matrix.
    """
    try:
        simulator = PortfolioMarginSimulator(max_stress_loss_pct=max_stress_loss_pct)
        pos_list = positions or []
        res = simulator.stress_test(pos_list, account_equity)
        return {
            "status": "success",
            "worst_case_loss": res.get("worst_case_loss", 0.0),
            "worst_case_pct": res.get("worst_case_pct", 0.0),
            "passed": bool(res.get("passed", True)),
            "max_stress_loss_pct": max_stress_loss_pct,
            "positions_evaluated": len(pos_list),
            "account_equity": account_equity,
        }
    except Exception as e:
        logger.error(f"Error in stress_test_portfolio tool: {e}")
        return {
            "status": "error",
            "error": str(e),
            "passed": False,
            "worst_case_pct": 1.0,
        }


def check_circuit_breaker() -> Dict[str, Any]:
    """Check current system-level circuit breaker status and thresholds.

    Returns:
        Dict with state ('NORMAL', 'CAUTION', 'HALTED'), thresholds, and cooldown status.
    """
    try:
        cb = CircuitBreaker()
        state = cb.get_state() if hasattr(cb, "get_state") else getattr(cb, "state", {})
        is_tripped = cb.is_tripped() if hasattr(cb, "is_tripped") else False
        return {
            "status": "success",
            "circuit_breaker_tripped": is_tripped,
            "circuit_breaker_state": "HALTED" if is_tripped else "NORMAL",
            "max_daily_loss_pct": cb.max_daily_loss_pct,
            "max_drawdown_pct": cb.max_drawdown_pct,
            "max_trades_per_day": cb.max_trades_per_day,
            "details": state,
        }
    except Exception as e:
        logger.error(f"Error checking circuit breaker: {e}")
        return {
            "status": "error",
            "circuit_breaker_tripped": False,
            "circuit_breaker_state": "NORMAL",
            "error": str(e),
        }
