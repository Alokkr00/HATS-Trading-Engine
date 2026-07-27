"""Portfolio allocation and position sizing module.

Provides classes and methods for calculating position sizes based on account equity,
risk limits, and technical indicators, as well as checking portfolio-level risk limits.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List
import numpy as np
import pandas as pd

from src.utils import get_logger

logger = get_logger(__name__)


class PositionSizer:
    """Calculates position sizes and enforces portfolio risk constraints.

    Provides mechanisms to size trades using a fixed-fractional risk model (e.g. 1% risk)
    subject to max position limits and sector concentration caps.
    """

    def __init__(self) -> None:
        """Initialize the PositionSizer."""
        pass

    def calculate_size(
        self,
        account_equity: float,
        entry_price: float,
        stop_price: float,
        atr: float | None = None,
        slippage_bps: float = 0.0,
        is_option: bool = False,
        delta: float = 1.0,
    ) -> Dict[str, Any]:
        """Calculate position size based on equity, entry/stop prices, and risk rules.

        Rules:
            1. Risk per trade is 1% of account equity: risk_per_trade = account_equity * 0.01.
            2. Raw shares based on stop distance: shares = risk_per_trade / abs(entry_price - stop_price).
            3. Maximum position value is 10% of equity: max_position_value = account_equity * 0.10.
            4. Shares are capped at max_position_value / entry_price.
            5. For options, we scale sizing by Delta to maintain delta-equivalent equity exposure.
            6. Shares are rounded down to the nearest integer.

        Args:
            account_equity: Current total account equity.
            entry_price: Planned entry price for the trade.
            stop_price: Stop loss price.
            atr: Optional Average True Range for volatility-based sizing (not used in base calculation).
            slippage_bps: slippage points.
            is_option: True if options contract.
            delta: The option Delta value.

        Returns:
            A dictionary containing:
                - 'shares' (int): Number of shares to trade (rounded down).
                - 'notional_value' (float): Total cost of the position (shares * entry_price).
                - 'risk_pct' (float): Actual percentage of equity at risk (decimal fraction, e.g. 0.01 for 1%).

        Raises:
            ValueError: If account_equity, entry_price, or stop_price are invalid.
        """
        # Input Validation
        if account_equity <= 0:
            logger.warning("Account equity must be positive. Got %s. Returning 0 shares.", account_equity)
            return {"shares": 0, "notional_value": 0.0, "risk_pct": 0.0}

        if entry_price <= 0:
            logger.warning("Entry price must be positive. Got %s. Returning 0 shares.", entry_price)
            return {"shares": 0, "notional_value": 0.0, "risk_pct": 0.0}

        if stop_price < 0:
            logger.warning("Stop price must be non-negative. Got %s. Returning 0 shares.", stop_price)
            return {"shares": 0, "notional_value": 0.0, "risk_pct": 0.0}

        if stop_price >= entry_price:
            logger.warning(
                "Stop price (%s) is greater than or equal to entry price (%s) for long position. "
                "Returning 0 shares.",
                stop_price,
                entry_price,
            )
            return {"shares": 0, "notional_value": 0.0, "risk_pct": 0.0}

        # Factor in estimated execution slippage to scale down risk
        multiplier = 100.0 if is_option else 1.0
        slippage_penalty = entry_price * (slippage_bps / 10000.0)
        stop_distance = abs(entry_price - stop_price) + slippage_penalty
        
        # Overnight Gap Risk: assume a minimum 3% adverse price move overnight
        overnight_gap_risk = entry_price * 0.03
        stop_distance = max(stop_distance, overnight_gap_risk)
        
        if stop_distance == 0:
            logger.warning(
                "Stop price (%s) is equal to entry price (%s). Stop distance is zero. "
                "Returning 0 shares/contracts to avoid division by zero.",
                stop_price,
                entry_price,
            )
            return {"shares": 0, "notional_value": 0.0, "risk_pct": 0.0}

        # For options, scale sizing by Delta to maintain delta-equivalent equity exposure
        abs_delta = max(0.1, abs(delta)) if is_option else 1.0

        # 1. 1% Risk per trade
        risk_per_trade = account_equity * 0.01

        # 2. Position size based on stop distance * contract multiplier * delta
        raw_size = risk_per_trade / (stop_distance * multiplier * abs_delta)

        # 3. Maximum position value is 10% of equity (capping delta-equivalent value for options)
        max_position_value = account_equity * 0.10
        max_size = max_position_value / (entry_price * multiplier * abs_delta)

        # 4. Cap size at max position value
        capped_size = min(raw_size, max_size)

        # 5. Round down to nearest integer
        final_size = int(math.floor(capped_size))

        # Handle edge case where size rounds down to 0
        if final_size <= 0:
            logger.info("Calculated size rounded down to 0.")
            return {"shares": 0, "notional_value": 0.0, "risk_pct": 0.0}

        # Calculate actual metrics
        notional_value = float(final_size * entry_price * multiplier)
        actual_risk = float(final_size * stop_distance * multiplier * abs_delta)
        risk_pct = float(actual_risk / account_equity)

        logger.debug(
            "Size calculated: size=%d, notional_value=%.2f, risk_pct=%.4f%% (target: 1%%), is_option=%s, delta=%.4f",
            final_size,
            notional_value,
            risk_pct * 100.0,
            is_option,
            delta,
        )

        return {
            "shares": final_size,
            "notional_value": notional_value,
            "risk_pct": risk_pct,
        }

    def check_portfolio_limits(
        self,
        current_positions: List[Dict[str, Any] | Any],
        new_sector: str,
        new_trade_weight: float | None = None,
        account_equity: float = 100000.0,
    ) -> bool:
        """Check if adding a new trade violates portfolio risk limits.

        Limits:
            - Max 6 concurrent positions.
            - Max 25% of account in a single sector.
            - Max 15% TIMS Portfolio Margin Stress Drawdown.

        Args:
            current_positions: List of active positions. Each position can be a dict
                or an object. Must have a 'sector' and optionally 'weight' (fraction of equity,
                e.g. 0.10 for 10%).
            new_sector: Sector string for the new trade (case-insensitive).
            new_trade_weight: Optional weight of the new trade as a fraction of equity.
                If not specified, it defaults to 0.10 (conservative maximum position value).
            account_equity: Net portfolio liquidation value.

        Returns:
            True if the trade is allowed under portfolio limits, False otherwise.
        """
        # 1. Max 6 concurrent positions
        if len(current_positions) >= 6:
            logger.warning(
                "Trade rejected: Maximum concurrent positions (6) reached. Current count: %d",
                len(current_positions),
            )
            return False

        # 2. Portfolio Margin Stress Test (TIMS-style Simulator)
        from src.risk.margin import PortfolioMarginSimulator
        
        formatted_positions = []
        for pos in current_positions:
            if isinstance(pos, dict):
                formatted_positions.append(pos)
            else:
                formatted_positions.append({
                    "symbol": getattr(pos, "symbol", "UNKNOWN"),
                    "qty": getattr(pos, "quantity", getattr(pos, "qty", 0)),
                    "avg_price": getattr(pos, "avg_price", getattr(pos, "cost_price", 0.0)),
                    "stop_price": getattr(pos, "stop_price", 0.0),
                    "underlying_price": getattr(pos, "underlying_price", 0.0),
                    "implied_vol": getattr(pos, "implied_vol", getattr(pos, "sigma", 0.30)),
                })
                
        simulator = PortfolioMarginSimulator()
        stress_res = simulator.stress_test(formatted_positions, account_equity)
        if not stress_res["passed"]:
            logger.warning(
                "Trade rejected: Portfolio margin stress test failed. Worst-case loss: %.2f%% "
                "exceeds stress loss limit of %.2f%%.",
                stress_res["worst_case_pct"] * 100.0,
                simulator.max_stress_loss_pct * 100.0,
            )
            return False

        # If new_sector is empty/invalid, log warning but allow or block based on strictness.
        # Let's normalize it.
        if not new_sector or not isinstance(new_sector, str):
            logger.warning("Empty or invalid sector name '%s' provided. Falling back to 'Unknown'.", new_sector)
            new_sector = "Unknown"

        normalized_new_sector = new_sector.strip().lower()

        # 2. Sector concentration check (Max 25% in a single sector)
        existing_sector_weight = 0.0
        for pos in current_positions:
            # Try dictionary access first, then object attribute
            sector = pos.get("sector") if isinstance(pos, dict) else getattr(pos, "sector", None)
            if not sector or not isinstance(sector, str):
                sector = "Unknown"

            if sector.strip().lower() == normalized_new_sector:
                weight = pos.get("weight") if isinstance(pos, dict) else getattr(pos, "weight", None)
                if weight is None:
                    # Check if 'percent' exists and convert to weight
                    percent = pos.get("percent") if isinstance(pos, dict) else getattr(pos, "percent", None)
                    if percent is not None:
                        weight = percent / 100.0
                    else:
                        # Fallback default weight if not provided (equal weighting assumption: 10% per position)
                        weight = 0.10

                existing_sector_weight += weight

        # Set default trade weight to 0.10 (max position value) if not provided
        trade_weight = new_trade_weight if new_trade_weight is not None else 0.10
        total_sector_weight = existing_sector_weight + trade_weight

        if total_sector_weight > 0.25:
            logger.warning(
                "Trade rejected: Adding sector '%s' (weight: %.2f%%) to existing weight (%.2f%%) "
                "would exceed the maximum sector concentration limit of 25.0%%.",
                new_sector,
                trade_weight * 100.0,
                existing_sector_weight * 100.0,
            )
            return False

        logger.info(
            "Portfolio limits check passed for sector '%s'. Combined weight: %.2f%% (limit: 25.0%%).",
            new_sector,
            total_sector_weight * 100.0,
        )
        return True

    def check_correlation(
        self,
        new_symbol: str,
        current_positions: List[Dict[str, Any] | Any],
        price_data: Dict[str, pd.DataFrame],
        threshold: float = 0.70,
        max_correlated: int = 3,
    ) -> bool:
        """Check if new_symbol is highly correlated with existing positions.

        Args:
            new_symbol: Ticker symbol of the new trade.
            current_positions: List of current open positions.
            price_data: Dict mapping ticker symbols to their historical DataFrames.
            threshold: Correlation coefficient threshold (ρ).
            max_correlated: Max number of positions allowed to exceed the correlation threshold.

        Returns:
            True if correlation limits are satisfied, False otherwise.
        """
        if not current_positions or new_symbol not in price_data:
            return True

        new_df = price_data[new_symbol]
        if new_df.empty or len(new_df) < 60:
            return True

        new_returns = new_df["close"].pct_change().tail(60)

        correlated_count = 0
        correlations = []

        for pos in current_positions:
            sym = pos.get("symbol") if isinstance(pos, dict) else getattr(pos, "symbol", None)
            if not sym or sym == new_symbol:
                continue

            # Strip option contract details to get underlying symbol if applicable
            underlying = sym
            if len(sym) > 10:  # Option contract OSI format
                underlying = sym[:4].rstrip("0123456789")

            if underlying in price_data:
                pos_df = price_data[underlying]
                if pos_df.empty or len(pos_df) < 60:
                    continue
                pos_returns = pos_df["close"].pct_change().tail(60)
                
                # Align indices to compute correlation
                aligned = pd.concat([new_returns, pos_returns], axis=1).dropna()
                if len(aligned) >= 30:
                    corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
                    if not pd.isna(corr):
                        correlations.append(corr)
                        if corr > threshold:
                            correlated_count += 1

        if correlated_count >= max_correlated:
            logger.warning(
                f"Trade {new_symbol} rejected by correlation filter. "
                f"Number of highly correlated positions (ρ > {threshold}): {correlated_count} "
                f"(Limit: {max_correlated}). Avg correlation: {np.mean(correlations):.2f}"
            )
            return False

        logger.info(
            f"Correlation check passed for {new_symbol}. "
            f"Correlated positions count: {correlated_count}."
        )
        return True

