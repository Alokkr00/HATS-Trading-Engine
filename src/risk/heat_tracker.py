"""Portfolio Heat Tracker module.

Calculates aggregate open risk across all positions (heat) and prevents opening
new trades if total risk exceeds set limits.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PortfolioHeatTracker:
    """Monitors total open risk of all positions compared to total equity."""

    def __init__(self, max_heat_pct: float = 0.06) -> None:
        """Initialize the heat tracker.

        Args:
            max_heat_pct: Maximum allowed risk-to-equity ratio (default 6%).
        """
        self.max_heat_pct = max_heat_pct

    def calculate_heat(
        self,
        positions: list[dict],
        net_equity: float,
    ) -> float:
        """Calculate the total portfolio heat (aggregate risk percent).

        Args:
            positions: List of position dictionaries.
                Each position must have 'symbol', 'quantity' (or 'qty'), 'avg_price'
                (or 'cost_price'), and optionally 'stop_price'.
            net_equity: Total net account equity.

        Returns:
            Portfolio heat as a decimal float (e.g. 0.045 for 4.5%).
        """
        if net_equity <= 0.0 or not positions:
            return 0.0

        total_risk_dollars = 0.0

        for pos in positions:
            qty = float(pos.get("quantity") or pos.get("qty") or 0)
            if qty <= 0:
                continue

            entry_price = float(pos.get("avg_price") or pos.get("cost_price") or pos.get("entry_price") or 0)
            stop_price = float(pos.get("stop_price") or 0)

            # If no stop price is defined, assume a conservative 5% stop distance
            if stop_price <= 0.0:
                stop_price = entry_price * 0.95

            risk_per_share = abs(entry_price - stop_price)
            position_risk = qty * risk_per_share
            total_risk_dollars += position_risk

        heat = total_risk_dollars / net_equity
        logger.debug(f"Total open risk: ${total_risk_dollars:.2f} (Heat: {heat:.2%}, Limit: {self.max_heat_pct:.2%})")
        return heat

    def can_add_trade(
        self,
        new_trade_risk_pct: float,
        current_heat: float,
    ) -> bool:
        """Check if adding a new trade exceeds the max heat limit.

        Args:
            new_trade_risk_pct: The risk percentage of the new trade (e.g. 0.01 for 1%).
            current_heat: The current portfolio heat.

        Returns:
            True if the trade is allowed, False otherwise.
        """
        projected_heat = current_heat + new_trade_risk_pct
        allowed = projected_heat <= self.max_heat_pct
        if not allowed:
            logger.warning(
                f"Trade rejected by heat tracker. Projected heat: {projected_heat:.2%}, "
                f"Limit: {self.max_heat_pct:.2%}"
            )
        return allowed
