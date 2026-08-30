"""Broker Trade Reconciliation & Execution Drift Engine.

Audits theoretical signal order parameters against actual executed broker fills,
logging slippage drift, latency drag, and fill completeness into the immutable
audit ledger to detect execution anomalies before live capital scaling.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import logging
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from src.execution.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class FillDiscrepancy:
    """Encapsulates execution reconciliation between theoretical and actual fills."""
    symbol: str
    order_id: str
    side: str
    intended_price: float
    actual_fill_price: float
    intended_qty: float
    filled_qty: float
    slippage_bps: float
    slippage_usd: float
    latency_seconds: float
    fill_ratio: float
    timestamp: str
    severity: str  # 'OK', 'WARNING', 'CRITICAL'


class BrokerReconciler:
    """Monitors, calculates, and records execution drift against broker fills."""

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        max_acceptable_slippage_bps: float = 15.0,
        critical_slippage_bps: float = 35.0,
        min_acceptable_fill_ratio: float = 0.95,
    ) -> None:
        """Initialize BrokerReconciler.

        Args:
            db_manager: Instance of DatabaseManager for audit logging.
            max_acceptable_slippage_bps: Threshold in bps for logging a WARNING.
            critical_slippage_bps: Threshold in bps for logging a CRITICAL anomaly.
            min_acceptable_fill_ratio: Minimum acceptable executed quantity ratio.
        """
        self.db = db_manager or DatabaseManager()
        self.max_acceptable_slippage_bps = max_acceptable_slippage_bps
        self.critical_slippage_bps = critical_slippage_bps
        self.min_acceptable_fill_ratio = min_acceptable_fill_ratio

    def reconcile_fill(
        self,
        symbol: str,
        order_id: str,
        side: str,
        intended_price: float,
        actual_fill_price: float,
        intended_qty: float,
        filled_qty: float,
        signal_time: dt.datetime | str,
        fill_time: dt.datetime | str,
    ) -> FillDiscrepancy:
        """Reconcile an individual order fill against intended signal parameters.

        Args:
            symbol: Ticker symbol (e.g. 'SPY').
            order_id: Broker order identifier.
            side: Trade direction ('BUY' or 'SELL').
            intended_price: Theoretical signal price at trigger time.
            actual_fill_price: Actual execution price from broker confirmation.
            intended_qty: Number of shares requested.
            filled_qty: Number of shares filled.
            signal_time: Timestamp when signal was generated.
            fill_time: Timestamp when broker fill was confirmed.

        Returns:
            FillDiscrepancy record with calculated drift and severity.
        """
        side_clean = side.upper().strip()
        
        # Calculate Slippage Drift
        if intended_price > 0:
            if side_clean == "BUY":
                # For buys, paying more than intended is negative slippage
                price_diff = actual_fill_price - intended_price
            else:
                # For sells, receiving less than intended is negative slippage
                price_diff = intended_price - actual_fill_price
            
            slippage_bps = float((price_diff / intended_price) * 10_000.0)
            slippage_usd = float(price_diff * filled_qty)
        else:
            slippage_bps = 0.0
            slippage_usd = 0.0

        # Calculate Latency Drag
        if isinstance(signal_time, str):
            signal_dt = pd.to_datetime(signal_time)
        else:
            signal_dt = signal_time

        if isinstance(fill_time, str):
            fill_dt = pd.to_datetime(fill_time)
        else:
            fill_dt = fill_time

        try:
            latency_sec = float(abs((fill_dt - signal_dt).total_seconds()))
        except Exception:
            latency_sec = 0.0

        # Fill Completeness Ratio
        fill_ratio = float(filled_qty / intended_qty) if intended_qty > 0 else 1.0

        # Determine Severity Level
        if abs(slippage_bps) >= self.critical_slippage_bps or fill_ratio < 0.50:
            severity = "CRITICAL"
        elif abs(slippage_bps) >= self.max_acceptable_slippage_bps or fill_ratio < self.min_acceptable_fill_ratio:
            severity = "WARNING"
        else:
            severity = "OK"

        now_str = dt.datetime.now(dt.timezone.utc).isoformat()
        discrepancy = FillDiscrepancy(
            symbol=symbol,
            order_id=str(order_id),
            side=side_clean,
            intended_price=float(round(intended_price, 4)),
            actual_fill_price=float(round(actual_fill_price, 4)),
            intended_qty=float(intended_qty),
            filled_qty=float(filled_qty),
            slippage_bps=float(round(slippage_bps, 2)),
            slippage_usd=float(round(slippage_usd, 2)),
            latency_seconds=float(round(latency_sec, 3)),
            fill_ratio=float(round(fill_ratio, 4)),
            timestamp=now_str,
            severity=severity,
        )

        # Log to Database Decision & Audit Ledger
        try:
            reason = (
                f"RECONCILIATION: {symbol} {side_clean} fill drift={slippage_bps:.1f}bps "
                f"(${slippage_usd:.2f}), latency={latency_sec:.2f}s, fill_ratio={fill_ratio*100:.1f}% [{severity}]"
            )
            self.db.record_decision(
                strategy_name="BrokerReconciler",
                symbol=symbol,
                decision=severity,
                reason=reason,
                market_data={
                    "order_id": order_id,
                    "intended_price": intended_price,
                    "actual_fill_price": actual_fill_price,
                    "slippage_bps": slippage_bps,
                    "slippage_usd": slippage_usd,
                    "latency_sec": latency_sec,
                },
            )
        except Exception as e:
            logger.warning("Failed to persist reconciliation record to database: %s", e)

        return discrepancy

    def compute_aggregate_drift_statistics(
        self,
        reconciled_fills: list[FillDiscrepancy],
    ) -> dict[str, Any]:
        """Aggregate execution statistics across multiple reconciled trade fills.

        Args:
            reconciled_fills: List of FillDiscrepancy records.

        Returns:
            Dict containing mean slippage bps, cumulative drag USD, and fill success rate.
        """
        if not reconciled_fills:
            return {
                "total_fills": 0,
                "mean_slippage_bps": 0.0,
                "cumulative_drag_usd": 0.0,
                "mean_latency_sec": 0.0,
                "mean_fill_ratio": 1.0,
                "critical_anomalies": 0,
                "warning_anomalies": 0,
            }

        slippage_bps_list = [f.slippage_bps for f in reconciled_fills]
        slippage_usd_list = [f.slippage_usd for f in reconciled_fills]
        latencies = [f.latency_seconds for f in reconciled_fills]
        fill_ratios = [f.fill_ratio for f in reconciled_fills]

        crit_count = sum(1 for f in reconciled_fills if f.severity == "CRITICAL")
        warn_count = sum(1 for f in reconciled_fills if f.severity == "WARNING")

        return {
            "total_fills": len(reconciled_fills),
            "mean_slippage_bps": float(round(float(np.mean(slippage_bps_list)), 2)),
            "cumulative_drag_usd": float(round(float(np.sum(slippage_usd_list)), 2)),
            "mean_latency_sec": float(round(float(np.mean(latencies)), 3)),
            "mean_fill_ratio": float(round(float(np.mean(fill_ratios)), 4)),
            "critical_anomalies": int(crit_count),
            "warning_anomalies": int(warn_count),
        }
