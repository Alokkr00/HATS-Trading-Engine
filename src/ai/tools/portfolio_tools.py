"""Portfolio and Database Audit tool wrappers for H.A.T.S AI Copilot."""

from __future__ import annotations

import logging
from pathlib import Path
from src.execution.db_manager import DatabaseManager
from src.utils.paths import DB_PATH

logger = logging.getLogger(__name__)


def _get_db() -> DatabaseManager:
    """Helper to get a DatabaseManager instance."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DatabaseManager(DB_PATH)


def get_live_portfolio_summary() -> Dict[str, Any]:
    """Retrieve live portfolio equity, cash balances, and current open positions.

    Returns:
        Dict with net_liquidity, cash_balance, positions list, and position count.
    """
    try:
        db = _get_db()
        net_liq, cash = db.get_cash()
        raw_positions = db.get_positions()

        positions_list = []
        for sym, pos in raw_positions.items():
            positions_list.append({
                "symbol": sym,
                "qty": pos.get("qty", 0),
                "avg_price": pos.get("avg_price", 0.0),
                "curr_price": pos.get("curr_price", 0.0),
                "market_value": pos.get("market_value", 0.0),
                "unrealized_pnl": pos.get("unrealized_pnl", 0.0),
                "unrealized_pnl_pct": pos.get("unrealized_pnl_pct", 0.0),
                "is_option": pos.get("is_option", False),
            })

        return {
            "status": "success",
            "net_liquidity": round(net_liq, 2),
            "cash_balance": round(cash, 2),
            "positions_count": len(positions_list),
            "positions": positions_list,
        }
    except Exception as e:
        logger.error(f"Error fetching portfolio summary: {e}")
        return {
            "status": "error",
            "net_liquidity": 100000.0,
            "cash_balance": 100000.0,
            "positions_count": 0,
            "positions": [],
            "error": str(e),
        }


def get_recent_decision_logs(limit: int = 20) -> List[Dict[str, Any]]:
    """Query recent immutable decision/audit logs from SQLite.

    Args:
        limit: Number of recent decision records to return.

    Returns:
        List of decision records showing cycle_id, timestamp, symbol, regime_hurst,
        risk_passed, risk_reason, stress_pct, and action_taken.
    """
    try:
        db = _get_db()
        query = """
            SELECT log_id, cycle_id, timestamp, symbol, regime_hurst, portfolio_equity,
                   portfolio_heat, risk_passed, risk_reason, tims_stress_pct, action_taken
            FROM decision_logs
            ORDER BY log_id DESC
            LIMIT :limit;
        """
        res = db.execute_query(query, {"limit": limit})
        rows = res.fetchall()

        logs = []
        for r in rows:
            logs.append({
                "log_id": r[0],
                "cycle_id": r[1],
                "timestamp": r[2],
                "symbol": r[3],
                "regime_hurst": r[4],
                "portfolio_equity": r[5],
                "portfolio_heat": r[6],
                "risk_passed": bool(r[7]),
                "risk_reason": r[8],
                "stress_pct": r[9],
                "action_taken": r[10],
            })
        return logs
    except Exception as e:
        logger.error(f"Error reading decision logs: {e}")
        return []
