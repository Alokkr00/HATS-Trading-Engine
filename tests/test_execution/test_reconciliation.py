"""Unit tests for broker trade reconciliation and execution drift engine."""

import datetime as dt
from unittest.mock import MagicMock
import pytest

from src.execution.reconciliation import BrokerReconciler, FillDiscrepancy


@pytest.fixture
def mock_db():
    """Create a mock DatabaseManager."""
    db = MagicMock()
    db.record_decision.return_value = True
    return db


def test_reconcile_fill_normal_buy(mock_db):
    """Verify standard fill reconciliation for a normal BUY order."""
    reconciler = BrokerReconciler(db_manager=mock_db)
    
    signal_time = dt.datetime(2026, 8, 30, 14, 0, 0, tzinfo=dt.timezone.utc)
    fill_time = dt.datetime(2026, 8, 30, 14, 0, 1, 500000, tzinfo=dt.timezone.utc)

    # Intended $100.00, filled at $100.02 (2 bps slippage on 100 shares = $2.00 drag)
    res = reconciler.reconcile_fill(
        symbol="SPY",
        order_id="order_123",
        side="BUY",
        intended_price=100.00,
        actual_fill_price=100.02,
        intended_qty=100.0,
        filled_qty=100.0,
        signal_time=signal_time,
        fill_time=fill_time,
    )

    assert res.symbol == "SPY"
    assert pytest.approx(res.slippage_bps, rel=1e-2) == 2.0
    assert pytest.approx(res.slippage_usd, rel=1e-2) == 2.0
    assert pytest.approx(res.latency_seconds, rel=1e-2) == 1.5
    assert res.fill_ratio == 1.0
    assert res.severity == "OK"
    assert mock_db.record_decision.called


def test_reconcile_fill_critical_slippage_anomaly(mock_db):
    """Verify that excessive slippage is tagged with CRITICAL severity."""
    reconciler = BrokerReconciler(db_manager=mock_db, critical_slippage_bps=30.0)
    
    # Intended $100.00, filled at $100.40 (40 bps slippage)
    res = reconciler.reconcile_fill(
        symbol="NVDA",
        order_id="order_999",
        side="BUY",
        intended_price=100.00,
        actual_fill_price=100.40,
        intended_qty=50.0,
        filled_qty=50.0,
        signal_time="2026-08-30T14:00:00Z",
        fill_time="2026-08-30T14:00:03Z",
    )

    assert res.severity == "CRITICAL"
    assert res.slippage_bps >= 30.0


def test_aggregate_drift_statistics(mock_db):
    """Verify aggregate statistics calculation across multiple fills."""
    reconciler = BrokerReconciler(db_manager=mock_db)

    fills = [
        FillDiscrepancy("SPY", "1", "BUY", 100.0, 100.01, 100, 100, 1.0, 1.0, 0.5, 1.0, "2026-08-30", "OK"),
        FillDiscrepancy("QQQ", "2", "SELL", 300.0, 299.90, 50, 50, 3.33, 5.0, 0.8, 1.0, "2026-08-30", "OK"),
        FillDiscrepancy("AAPL", "3", "BUY", 150.0, 150.60, 20, 20, 40.0, 12.0, 2.5, 1.0, "2026-08-30", "CRITICAL"),
    ]

    stats = reconciler.compute_aggregate_drift_statistics(fills)

    assert stats["total_fills"] == 3
    assert stats["critical_anomalies"] == 1
    assert stats["cumulative_drag_usd"] == 18.0
    assert stats["mean_fill_ratio"] == 1.0
