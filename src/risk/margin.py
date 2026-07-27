"""Portfolio Margin Stress Simulator implementing TIMS-style risk grid stress checks."""

from __future__ import annotations

import math
from typing import Any, Dict, List
from src.strategy.black_scholes import calculate_option_price_and_delta, parse_option_symbol
from src.utils import get_logger

logger = get_logger(__name__)


class PortfolioMarginSimulator:
    """Stress tests the portfolio net equity across a 15-point risk grid.

    Underlying price shifts: -15%, -8%, 0%, +8%, +15%
    Volatility shifts: -25%, 0%, +25% (Proportional shift of implied volatility)
    """

    # Correlation offsets between major indexes/sectors
    CORRELATION_OFFSETS = {
        ("SPY", "QQQ"): 0.85,   # High correlation between major indices
        ("SPY", "IWM"): 0.75,
        ("XLK", "QQQ"): 0.90,
    }

    def __init__(
        self,
        max_stress_loss_pct: float = 0.15,
        min_option_margin: float = 37.50,
    ) -> None:
        """Initialize the simulator.

        Args:
            max_stress_loss_pct: Maximum allowed stress drawdown as a fraction
                of total equity (default 15%).
            min_option_margin: Minimum margin requirement per option contract.
        """
        self.max_stress_loss_pct = max_stress_loss_pct
        self.min_option_margin = min_option_margin

        # Define TIMS price shifts and proportional volatility shifts
        self.price_shifts = [-0.15, -0.08, 0.0, 0.08, 0.15]
        self.vol_shifts = [-0.25, 0.0, 0.25]  # -25%, 0%, +25% proportional volatility shift

    def calculate_position_pnl(self, rpos: Dict[str, Any], p_shift: float, v_shift: float) -> float:
        """Calculates the dollar change for a single position under scenario shifts."""
        qty = rpos["qty"]
        if rpos["is_option"]:
            try:
                # Proportional volatility shift
                projected_underlying = rpos["curr_underlying"] * (1.0 + p_shift)
                projected_vol = max(0.01, rpos["curr_vol"] * (1.0 + v_shift))
                
                # Revalue the option contract
                proj_price, _ = calculate_option_price_and_delta(
                    S=projected_underlying,
                    K=rpos["strike"],
                    T=rpos["T"],
                    r=0.05,
                    sigma=projected_vol,
                    option_type=rpos["opt_type"]
                )
                
                pos_gain = (proj_price - rpos["curr_price"]) * qty * 100.0
                
                # Enforce minimum option margin charge for short options (qty < 0)
                if qty < 0:
                    min_loss = -self.min_option_margin * abs(qty)
                    if pos_gain > min_loss:
                        pos_gain = min_loss
                        
                return pos_gain
            except Exception as e:
                logger.error(f"Failed to stress-test option position {rpos['symbol']}: {e}")
                return 0.0
        else:
            projected_price = rpos["curr_price"] * (1.0 + p_shift)
            pos_gain = (projected_price - rpos["curr_price"]) * qty
            return pos_gain

    def _apply_correlation_offsets(self, class_pnls: Dict[str, float]) -> float:
        """Applies correlation offsets to opposite-signed underlying groups to limit hedge credit."""
        pnls = class_pnls.copy()
        
        # Apply offsets for predefined correlated asset pairs
        for (sym1, sym2), corr in self.CORRELATION_OFFSETS.items():
            if sym1 in pnls and sym2 in pnls:
                p1 = pnls[sym1]
                p2 = pnls[sym2]
                
                # Correlation offset only applies to hedging (opposite-signed) positions
                if p1 * p2 < 0:
                    loss = p1 if p1 < 0 else p2
                    gain = p2 if p1 < 0 else p1
                    # net PnL limits gain offset credit to (1 - correlation)
                    net_offset_pnl = loss + gain * (1.0 - corr)
                    
                    # Split the resulting net pnl between the two symbols
                    pnls[sym1] = net_offset_pnl / 2.0
                    pnls[sym2] = net_offset_pnl / 2.0
                    
        return sum(pnls.values())

    def aggregate_portfolio_pnl(self, resolved_positions: List[Dict[str, Any]], p_shift: float, v_shift: float) -> float:
        """Aggregates position PnLs for a scenario, grouping by underlying and applying correlation offsets."""
        class_pnls: Dict[str, float] = {}
        
        # Calculate position PnLs and group them by class symbol (underlying symbol)
        for rpos in resolved_positions:
            pnl = self.calculate_position_pnl(rpos, p_shift, v_shift)
            symbol = rpos["symbol"]
            
            # Group options by their underlying symbol to form class groups
            class_symbol = rpos["underlying"] if rpos["is_option"] else symbol
            class_pnls[class_symbol] = class_pnls.get(class_symbol, 0.0) + pnl
            
        return self._apply_correlation_offsets(class_pnls)

    def stress_test(
        self,
        positions: List[Dict[str, Any]],
        account_equity: float,
    ) -> Dict[str, Any]:
        """Calculates the worst-case portfolio loss across the 15-point stress grid.

        Args:
            positions: List of active position dictionaries.
            account_equity: Net portfolio liquidation value.

        Returns:
            A dict containing:
                - 'worst_case_loss' (float): Maximum loss in dollars (negative value).
                - 'worst_case_pct' (float): Worst-case loss as a fraction of equity.
                - 'passed' (bool): True if loss does not exceed max_stress_loss_pct.
        """
        if account_equity <= 0:
            return {"worst_case_loss": 0.0, "worst_case_pct": 0.0, "passed": False}

        if not positions:
            return {"worst_case_loss": 0.0, "worst_case_pct": 0.0, "passed": True}

        # 1. Pre-resolve position price metrics to avoid duplicate yfinance queries inside scenarios loop
        resolved_positions = []
        for pos in positions:
            symbol = pos.get("symbol", "UNKNOWN")
            qty = float(pos.get("quantity") or pos.get("qty") or 0)
            if qty == 0:
                continue

            is_option = len(symbol) > 10 and any(c.isdigit() for c in symbol[-8:])
            resolved_pos = {
                "symbol": symbol,
                "qty": qty,
                "is_option": is_option,
                "raw_pos": pos,
            }

            if is_option:
                try:
                    underlying, opt_type, strike, T = parse_option_symbol(symbol)
                    curr_underlying = pos.get("underlying_price")
                    if curr_underlying is None:
                        try:
                            import yfinance as yf
                            ticker_data = yf.Ticker(underlying)
                            history = ticker_data.history(period="1d")
                            if not history.empty:
                                curr_underlying = float(history["close"].iloc[-1])
                        except Exception as ye:
                            logger.warning(f"Could not fetch live underlying price for {underlying} from yfinance: {ye}")

                    if curr_underlying is None:
                        curr_underlying = float(strike)
                    else:
                        curr_underlying = float(curr_underlying)

                    curr_vol = float(pos.get("implied_vol") or pos.get("sigma") or 0.30)
                    curr_price = float(pos.get("price") or pos.get("market_price") or pos.get("last_price") or pos.get("avg_price") or pos.get("cost_price") or 1.0)

                    resolved_pos.update({
                        "underlying": underlying,
                        "opt_type": opt_type,
                        "strike": strike,
                        "T": T,
                        "curr_underlying": curr_underlying,
                        "curr_vol": curr_vol,
                        "curr_price": curr_price,
                    })
                except Exception as e:
                    logger.error(f"Failed to resolve option parameters for {symbol}: {e}")
                    continue
            else:
                curr_price = float(pos.get("price") or pos.get("market_price") or pos.get("last_price") or pos.get("avg_price") or pos.get("cost_price") or 0.0)
                resolved_pos.update({
                    "curr_price": curr_price,
                })

            resolved_positions.append(resolved_pos)

        worst_loss = 0.0

        # 2. Evaluate every combination of price and volatility shifts
        for p_shift in self.price_shifts:
            for v_shift in self.vol_shifts:
                scenario_gain_loss = self.aggregate_portfolio_pnl(resolved_positions, p_shift, v_shift)

                # Record the worst-case scenario (minimum gain/maximum loss)
                if scenario_gain_loss < worst_loss:
                    worst_loss = scenario_gain_loss

        worst_pct = abs(worst_loss) / account_equity
        passed = worst_pct <= self.max_stress_loss_pct

        logger.debug(
            f"Margin Stress Test Completed. Worst-case loss: ${worst_loss:.2f} "
            f"({worst_pct:.2%} of equity, Limit: {self.max_stress_loss_pct:.2%})"
        )

        return {
            "worst_case_loss": worst_loss,
            "worst_case_pct": worst_pct,
            "passed": passed,
        }
