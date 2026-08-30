"""Risk Engineer Agent: Executes 15-scenario stress testing and circuit breaker evaluation."""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from src.ai.schemas import RiskAssessment, TradeIdea
from src.ai.tools.risk_tools import stress_test_portfolio, check_circuit_breaker
from src.ai.tools.portfolio_tools import get_live_portfolio_summary

logger = logging.getLogger(__name__)


class RiskAgent:
    """Agent strictly tasked with risk gate validation and margin stress checks."""

    def run(
        self,
        trade_ideas: List[TradeIdea],
        account_equity: float = 100000.0,
    ) -> RiskAssessment:
        """Evaluate trade ideas under portfolio stress grid and system circuit breakers."""
        logger.info(f"RiskAgent evaluating {len(trade_ideas)} proposed trades.")

        # 1. Fetch current live positions
        portfolio = get_live_portfolio_summary()
        current_positions = list(portfolio.get("positions", []))
        net_equity = portfolio.get("net_liquidity", account_equity) or account_equity

        # 2. Add hypothetical proposed trades to the position list for stress testing
        test_positions = [dict(p) for p in current_positions]
        for idea in trade_ideas:
            if idea.action == "BUY" and idea.suggested_entry:
                qty = int((net_equity * idea.position_size_pct) / idea.suggested_entry)
                test_positions.append({
                    "symbol": idea.symbol,
                    "qty": max(1, qty),
                    "curr_price": idea.suggested_entry,
                    "is_option": False,
                })

        # 3. Execute deterministic 15-point stress test
        stress_res = stress_test_portfolio(test_positions, account_equity=net_equity)
        worst_case_pct = stress_res.get("worst_case_pct", 0.0)
        stress_passed = stress_res.get("passed", True)

        # 4. Check circuit breaker state
        cb_res = check_circuit_breaker()
        cb_tripped = cb_res.get("circuit_breaker_tripped", False)
        cb_state = cb_res.get("circuit_breaker_state", "NORMAL")

        violations = []
        if not stress_passed or worst_case_pct > 0.15:
            violations.append(f"Stress test projected loss of {worst_case_pct*100:.2f}% exceeds 15.00% cap.")
        if cb_tripped:
            violations.append("System circuit breaker is currently TRIPPED / HALTED.")

        risk_compliant = stress_passed and not cb_tripped and (worst_case_pct <= 0.15)

        return RiskAssessment(
            risk_compliant=risk_compliant,
            stress_drawdown_pct=round(worst_case_pct * 100.0, 2),
            circuit_breaker_passed=not cb_tripped,
            circuit_breaker_state=cb_state,
            short_option_margin_floor_applied=True,
            violations=violations,
        )


risk_agent = RiskAgent()
