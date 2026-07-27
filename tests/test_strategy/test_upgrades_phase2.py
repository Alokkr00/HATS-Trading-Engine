"""Unit tests for Phase 2 H.A.T.S Institutional Upgrades (Cubic Splines, Margin Simulator, Ledger Triggers)."""

from __future__ import annotations

import os
import tempfile
import datetime as dt
import pytest
import pandas as pd
import numpy as np
from sqlalchemy.exc import OperationalError, IntegrityError

from src.strategy.volatility import CubicSplineVolatilitySurface
from src.risk.margin import PortfolioMarginSimulator
from src.execution.db_manager import DatabaseManager


def test_cubic_spline_volatility_surface():
    # 1. Setup mock option chain with two expirations (30 and 60 days)
    data = []
    # Expiry 30 days
    for strike, iv in [(80, 0.40), (90, 0.35), (100, 0.30), (110, 0.35), (120, 0.42)]:
        data.append({"strike": strike, "days_to_expiry": 30.0, "implied_volatility": iv})
    # Expiry 60 days
    for strike, iv in [(80, 0.35), (90, 0.32), (100, 0.28), (110, 0.31), (120, 0.38)]:
        data.append({"strike": strike, "days_to_expiry": 60.0, "implied_volatility": iv})

    df = pd.DataFrame(data)
    surface = CubicSplineVolatilitySurface(df)

    # 2. Test exact strike match on exact expiry
    vol_exact = surface.interpolate(100.0, 30.0)
    assert pytest.approx(vol_exact, abs=1e-5) == 0.30

    # 3. Test interpolation between strikes
    vol_mid = surface.interpolate(95.0, 30.0)
    assert 0.30 < vol_mid < 0.35

    # 4. Test interpolation between expiries (45 days)
    vol_time = surface.interpolate(100.0, 45.0)
    # At 30d vol=0.30, at 60d vol=0.28. Linear variance interpolation will yield ~0.29
    assert 0.28 < vol_time < 0.30

    # 5. Test flat extrapolation outside bounds
    vol_low_expiry = surface.interpolate(100.0, 10.0)
    assert pytest.approx(vol_low_expiry, abs=1e-5) == 0.30

    vol_high_expiry = surface.interpolate(100.0, 120.0)
    assert pytest.approx(vol_high_expiry, abs=1e-5) == 0.28


def test_portfolio_margin_simulator():
    simulator = PortfolioMarginSimulator(max_stress_loss_pct=0.10)

    # 1. Scenario: Holding 100 shares of stock at $100 price
    positions = [
        {
            "symbol": "AAPL",
            "qty": 100,
            "avg_price": 100.0,
            "sector": "Technology"
        }
    ]

    # Test stress under 100k equity
    res = simulator.stress_test(positions, account_equity=100000.0)
    # Worst case shift is -15% underlying move -> loss = 100 * -15.0 = -1,500.0
    assert pytest.approx(res["worst_case_loss"], abs=1e-2) == -1500.0
    assert pytest.approx(res["worst_case_pct"], abs=1e-5) == 0.015  # 1.5%
    assert res["passed"] is True

    # 2. Scenario: Worst-case loss exceeds limits (1500 shares of Stock -> 150,000 cost)
    large_positions = [
        {
            "symbol": "AAPL",
            "qty": 1500,
            "avg_price": 100.0,
            "sector": "Technology"
        }
    ]
    res_large = simulator.stress_test(large_positions, account_equity=100000.0)
    # Worst case shift -15% -> loss = 1500 * -15 = -22,500.0 (22.5% of equity)
    assert pytest.approx(res_large["worst_case_loss"], abs=1e-2) == -22500.0
    assert res_large["passed"] is False


def test_margin_simulator_correlation_offsets():
    """Verify that correlation offsets limit hedge credit between SPY and QQQ."""
    simulator = PortfolioMarginSimulator(max_stress_loss_pct=0.15)
    
    # Opposite positions (hedging): SPY long, QQQ short
    # With direct summation (no offset), if SPY drops 15% (-$1500) and QQQ drops 15% (which gains +$1500 for short), net is 0.
    # But with a correlation offset of 0.85, the gain only offsets up to (1 - 0.85) = 15%.
    # So net loss = -1500 + 1500 * 0.15 = -1275.
    positions = [
        {"symbol": "SPY", "qty": 100, "avg_price": 100.0},
        {"symbol": "QQQ", "qty": -100, "avg_price": 100.0},
    ]
    
    res = simulator.stress_test(positions, account_equity=100000.0)
    
    # Worst case is -1275.0 (with correlation offset applied)
    assert pytest.approx(res["worst_case_loss"], abs=1.0) == -1275.0


def test_margin_simulator_proportional_vol():
    """Verify that volatility shifts are applied proportionally."""
    simulator = PortfolioMarginSimulator(max_stress_loss_pct=0.15)
    
    resolved = {
        "symbol": "AAPL260717C00100000",
        "qty": 1,
        "is_option": True,
        "underlying": "AAPL",
        "opt_type": "CALL",
        "strike": 100.0,
        "T": 0.1,
        "curr_underlying": 100.0,
        "curr_vol": 0.40,
        "curr_price": 5.0,
    }
    
    # Test positive vol shift (+25% of 0.40 -> 0.50)
    pnl_pos_vol = simulator.calculate_position_pnl(resolved, p_shift=0.0, v_shift=0.25)
    # Test negative vol shift (-25% of 0.40 -> 0.30)
    pnl_neg_vol = simulator.calculate_position_pnl(resolved, p_shift=0.0, v_shift=-0.25)
    
    # Positive vol shift increases option price (vega is positive), negative decreases
    assert pnl_pos_vol > 0
    assert pnl_neg_vol < 0


def test_margin_simulator_minimum_option_margin():
    """Verify that short options are charged a minimum of $37.50 per contract of margin loss."""
    simulator = PortfolioMarginSimulator(max_stress_loss_pct=0.15, min_option_margin=37.50)
    
    pos = {
        "symbol": "AAPL260717C00100000",
        "qty": -2,
        "is_option": True,
        "underlying": "AAPL",
        "opt_type": "CALL",
        "strike": 100.0,
        "T": 0.1,
        "curr_underlying": 100.0,
        "curr_vol": 0.40,
        "curr_price": 5.0,
    }
    
    # Suppose option price drops to 4.90 under some scenario -> standard profit is +0.10 * 200 = +$20.
    # But because it is a short option, the minimum margin loss floor applies:
    # min loss is -37.50 * 2 = -$75.
    # Because +20 > -75, the position PnL is capped/floored at -$75.0.
    pnl = simulator.calculate_position_pnl(pos, p_shift=-0.001, v_shift=-0.25)
    assert pnl == -75.0


def test_database_ledger_immutable_triggers():
    # Create temp database file
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_ledger.db")

    try:
        db = DatabaseManager(db_file)
        
        # Insert mock transaction
        db.execute_query(
            """
            INSERT INTO transactions (client_order_id, symbol, side, qty, price, avg_price, timestamp)
            VALUES ('c_ord_1', 'AAPL', 'BUY', 100, 150.0, 150.0, :ts);
            """,
            {"ts": dt.datetime.now(dt.timezone.utc).isoformat()}
        )

        # Confirm insertion
        rows = db.execute_query("SELECT COUNT(*) FROM transactions;").fetchall()
        assert rows[0][0] == 1

        # Try to UPDATE the transactions log
        with pytest.raises((OperationalError, IntegrityError)) as excinfo:
            db.execute_query("UPDATE transactions SET qty = 200 WHERE client_order_id = 'c_ord_1';")
        assert "prohibited" in str(excinfo.value) or "restrict" in str(excinfo.value)

        # Try to DELETE the transactions log
        with pytest.raises((OperationalError, IntegrityError)) as excinfo:
            db.execute_query("DELETE FROM transactions WHERE client_order_id = 'c_ord_1';")
        assert "prohibited" in str(excinfo.value) or "restrict" in str(excinfo.value)

    finally:
        # Cleanup
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass
        try:
            os.rmdir(temp_dir)
        except Exception:
            pass


def test_decision_logs_ledger_roundtrip_and_immutability():
    from sqlalchemy import text
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_dec_ledger.db")

    try:
        db = DatabaseManager(db_file)
        
        # 1. Test save_decision_log
        log_entry = {
            "cycle_id": "cycle_123",
            "symbol": "XLK",
            "regime_hurst": 0.55,
            "strategy_signals": {"SectorMomentum": 1},
            "portfolio_equity": 100000.0,
            "portfolio_heat": 0.024,
            "risk_passed": True,
            "risk_reason": None,
            "tims_stress_pct": 0.035,
            "action_taken": "BUY_ORDER_PLACED"
        }
        db.save_decision_log(log_entry)
        
        # Read back
        rows = db.execute_query("SELECT * FROM decision_logs;").fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "cycle_123"  # cycle_id
        assert rows[0][3] == "XLK"        # symbol
        assert rows[0][4] == 0.55         # regime_hurst
        assert "SectorMomentum" in rows[0][5]  # strategy_signals JSON
        assert rows[0][6] == 100000.0     # portfolio_equity
        assert rows[0][7] == 0.024        # portfolio_heat
        assert rows[0][8] == 1            # risk_passed
        assert rows[0][9] is None         # risk_reason
        assert rows[0][10] == 0.035       # tims_stress_pct
        assert rows[0][11] == "BUY_ORDER_PLACED"

        # 2. Test immutability triggers (block updates/deletes)
        with pytest.raises((OperationalError, IntegrityError)) as excinfo:
            db.execute_query("UPDATE decision_logs SET action_taken = 'MUTATED' WHERE cycle_id = 'cycle_123';")
        assert "prohibited" in str(excinfo.value) or "restrict" in str(excinfo.value)

        with pytest.raises((OperationalError, IntegrityError)) as excinfo:
            db.execute_query("DELETE FROM decision_logs WHERE cycle_id = 'cycle_123';")
        assert "prohibited" in str(excinfo.value) or "restrict" in str(excinfo.value)

    finally:
        # Cleanup
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass
        try:
            os.rmdir(temp_dir)
        except Exception:
            pass


def test_decision_logs_performance_scale():
    from sqlalchemy import text
    import time
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_scale.db")

    try:
        db = DatabaseManager(db_file)
        
        # Insert 10,000 mock rows inside a single transaction for efficiency
        now = dt.datetime.now(dt.timezone.utc)
        
        with db.engine.begin() as conn:
            for i in range(10000):
                ts = (now - dt.timedelta(seconds=i)).isoformat()
                conn.execute(
                    text(
                        """
                        INSERT INTO decision_logs (cycle_id, timestamp, symbol, regime_hurst, strategy_signals, portfolio_equity, portfolio_heat, risk_passed, risk_reason, tims_stress_pct, action_taken)
                        VALUES (:cid, :ts, :sym, 0.55, '{"SectorMomentum": 0}', 100000.0, 0.0, 1, NULL, 0.0, 'NO_ACTION');
                        """
                    ),
                    {
                        "cid": f"cycle_{i // 10}",
                        "ts": ts,
                        "sym": "AAPL" if i % 2 == 0 else "MSFT"
                    }
                )
                
        # Confirm insertion
        count_row = db.execute_query("SELECT COUNT(*) FROM decision_logs;").fetchone()
        assert count_row[0] == 10000
        
        # Run indexed query and verify sub-100ms response time
        start_time = time.perf_counter()
        
        rows = db.execute_query(
            "SELECT * FROM decision_logs WHERE symbol = 'AAPL' ORDER BY timestamp DESC LIMIT 50;"
        ).fetchall()
        
        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000.0
        
        assert len(rows) == 50
        print(f"\n[SCALE] Queried 50 indexed rows from 10,000 in {duration_ms:.2f} ms.")
        assert duration_ms < 100.0 # Standard requirement for fast interactive dashboard loads

    finally:
        # Cleanup
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass
        try:
            os.rmdir(temp_dir)
        except Exception:
            pass


def test_portfolio_margin_simulator_options():
    """Verify options stress test handles additive vol shifts and fetches underlying prices via mock."""
    from unittest.mock import MagicMock, patch
    import pandas as pd
    
    simulator = PortfolioMarginSimulator(max_stress_loss_pct=0.15)
    
    # Position lacks underlying_price but has strike
    # AAPL Jan 15 2026 Call with strike 150
    positions = [
        {
            "symbol": "AAPL260116C00150000",
            "qty": 10,
            "implied_vol": 0.30,
            "avg_price": 10.0,
        }
    ]
    
    # Mock yfinance to return underlying price of 160.0
    mock_history = MagicMock()
    mock_history.empty = False
    mock_history.__getitem__.return_value.iloc = [-1]
    # We want history['close'].iloc[-1] to be 160.0
    # Create a simple df
    mock_df = pd.DataFrame({"close": [160.0]})
    
    with patch("yfinance.Ticker") as mock_ticker:
        mock_stock = MagicMock()
        mock_stock.history.return_value = mock_df
        mock_ticker.return_value = mock_stock
        
        # Test stress under 100k equity
        res = simulator.stress_test(positions, account_equity=100000.0)
        
        # Assertions
        assert "worst_case_loss" in res
        assert "worst_case_pct" in res
        # Check that yfinance was indeed queried since underlying_price was missing
        mock_ticker.assert_called_once_with("AAPL")
        mock_stock.history.assert_called_once_with(period="1d")

