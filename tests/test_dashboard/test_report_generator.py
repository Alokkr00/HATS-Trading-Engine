"""Unit tests for the Weekly Operational Report Generator module."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.execution.db_manager import DatabaseManager
from src.dashboard.report_generator import WeeklyReportGenerator


@pytest.fixture
def temp_db():
    """Setup a temporary SQLite database with mock operational data."""
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_report.db")
    db = DatabaseManager(db_file)
    
    # 1. Populate mock transactions for the past week
    now = dt.datetime.now(dt.timezone.utc)
    now_str = now.isoformat()
    t1 = (now - dt.timedelta(days=2)).isoformat()
    t2 = (now - dt.timedelta(days=1)).isoformat()
    
    db.execute_query(
        """
        INSERT INTO transactions (client_order_id, symbol, side, qty, price, avg_price, timestamp)
        VALUES 
            ('c1', 'XLK', 'BUY', 10, 150.0, 150.0, :t1),
            ('c2', 'XLK', 'SELL', 10, 155.0, 155.0, :t2);
        """,
        {"t1": t1, "t2": t2}
    )
    
    # 2. Populate mock decision logs for the past week
    db.execute_query(
        """
        INSERT INTO decision_logs (cycle_id, timestamp, symbol, regime_hurst, strategy_signals, portfolio_equity, portfolio_heat, risk_passed, risk_reason, tims_stress_pct, action_taken)
        VALUES
            ('cy1', :t1, 'XLK', 0.55, '{"SectorMomentum": 1}', 100000.0, 0.02, 1, NULL, 0.04, 'BUY_ORDER_PLACED'),
            ('cy2', :t2, 'XLK', 0.56, '{"SectorMomentum": -1}', 100050.0, 0.0, 0, 'Portfolio heat limit exceeded', 0.0, 'REJECTED_HEAT_LIMIT');
        """,
        {"t1": t1, "t2": t2}
    )
    
    yield db
    
    # Cleanup
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass


def test_weekly_report_generation(temp_db):
    """Test compiling the weekly report and verifying calculations and Markdown outputs."""
    generator = WeeklyReportGenerator(db_manager=temp_db)
    
    # Run generator
    report_md, report_file = generator.generate_weekly_report()
    
    assert report_file is not None
    assert report_file.exists()
    assert report_file.name.endswith(".md")
    
    # Verify calculation outputs inside Markdown
    assert "# H.A.T.S Weekly Operational Audit Report" in report_md
    assert "Net Realized PnL" in report_md
    assert "$50.00" in report_md  # (155 - 150) * 10 PnL
    assert "Win Rate" in report_md
    assert "100.00%" in report_md  # 1 trade: 1 win
    assert "Portfolio heat limit exceeded" in report_md
    assert "1 times" in report_md  # 1 heat rejection occurrence
    
    # Clean up generated files
    if report_file.exists():
        os.remove(report_file)
        
    # Verify chart file created
    chart_dir = Path("data/reports/charts")
    charts = list(chart_dir.glob("weekly_chart_*.png"))
    for chart in charts:
        try:
            os.remove(chart)
        except Exception:
            pass


def test_weekly_report_empty_state():
    """Test compiling report when no transactions or logs exist (protection against div-by-zero)."""
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "empty_report.db")
    empty_db = DatabaseManager(db_file)
    
    generator = WeeklyReportGenerator(db_manager=empty_db)
    
    # Should complete without raising any ZeroDivisionError exceptions
    report_md, report_file = generator.generate_weekly_report()
    
    assert "**Total Trades** | 0" in report_md
    assert "**Net Realized PnL** | $0.00" in report_md
    assert "**Win Rate** | 0.00%" in report_md
    
    if report_file and report_file.exists():
        os.remove(report_file)
        
    chart_dir = Path("data/reports/charts")
    charts = list(chart_dir.glob("weekly_chart_*.png"))
    for chart in charts:
        try:
            os.remove(chart)
        except Exception:
            pass

    # Cleanup empty db
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass


@patch("src.dashboard.report_generator.send_alert")
def test_send_report_summary(mock_send_alert, temp_db):
    """Test summary extraction and Slack/Telegram routing."""
    generator = WeeklyReportGenerator(db_manager=temp_db)
    report_md, report_file = generator.generate_weekly_report()
    
    # Mock configs
    env_vars = {
        "SEND_TELEGRAM_WEEKLY_REPORT": "True",
        "SEND_SLACK_WEEKLY_REPORT": "False"
    }
    with patch.dict(os.environ, env_vars):
        generator.send_report_summary(report_md)
        assert mock_send_alert.call_count == 1
        args, kwargs = mock_send_alert.call_args
        summary_msg = args[0]
        
        assert "H.A.T.S Weekly Performance Report" in summary_msg
        assert "$50.00" in summary_msg
        assert "100.00%" in summary_msg
        
    if report_file and report_file.exists():
        os.remove(report_file)
