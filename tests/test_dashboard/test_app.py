from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, mock_open
import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import app, authenticate_user, get_user_role, require_admin


@pytest.fixture(autouse=True)
def override_security():
    """Bypass Basic Auth for legacy tests by overriding dependency."""
    app.dependency_overrides[authenticate_user] = lambda: "admin"
    app.dependency_overrides[get_user_role] = lambda: "admin"
    app.dependency_overrides[require_admin] = lambda: "admin"
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    """Fixture to provide a FastAPI TestClient."""
    return TestClient(app)


def test_dashboard_unauthorized_requests(client):
    """Test that requests without credentials return HTTP 401, and correct credentials return 200."""
    # Temporarily remove dependency override to check actual security enforcement
    app.dependency_overrides.clear()
    
    with patch("src.dashboard.app.FileResponse") as mock_file_response:
        mock_file_response.return_value = "html_content"
        
        # 1. Access without credentials -> 401 Unauthorized
        res_no_auth = client.get("/")
        assert res_no_auth.status_code == 401
        
        # 2. Access with wrong credentials -> 401 Unauthorized
        res_bad_auth = client.get("/", auth=("wrong_user", "wrong_pass"))
        assert res_bad_auth.status_code == 401
        
        # 3. Access with correct default credentials -> 200 OK
        res_ok = client.get("/", auth=("admin", "hats_secure_pass"))
        assert res_ok.status_code == 200
        mock_file_response.assert_called_once()


def test_root_endpoint_returns_html(client):
    """Test that the root route renders the index.html page."""
    with patch("src.dashboard.app.FileResponse") as mock_file_response:
        mock_file_response.return_value = "html_content"
        response = client.get("/")
        assert response.status_code == 200
        mock_file_response.assert_called_once()


def test_static_assets_endpoints(client):
    """Test style.css and app.js static endpoints."""
    with patch("src.dashboard.app.FileResponse") as mock_file_response:
        mock_file_response.return_value = "asset_content"
        
        response_css = client.get("/static/style.css")
        assert response_css.status_code == 200
        
        response_js = client.get("/static/app.js")
        assert response_js.status_code == 200
        
        assert mock_file_response.call_count == 2


def test_api_state_missing_file_returns_fallback(client):
    """Test that /api/state returns fallback dict if state file is missing."""
    with patch("src.dashboard.app.EXECUTION_DIR") as mock_dir, \
         patch("src.dashboard.app.db.get_cash", return_value=(100000.0, 100000.0)):
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_dir.__truediv__.return_value = mock_path
        
        response = client.get("/api/state")
        assert response.status_code == 200
        data = response.json()
        assert "portfolio" in data
        assert data["portfolio"]["cash"]["net_liquidity"] == 100000.0


def test_api_state_existing_file(client):
    """Test that /api/state returns content of oms_state.json when present."""
    mock_state = {
        "orders": {"oms_1": {"symbol": "TSLA", "status": "SUBMITTED"}},
        "portfolio": {"positions": {}, "cash": {"net_liquidity": 150000.0}},
    }
    
    with patch("src.dashboard.app.EXECUTION_DIR") as mock_dir:
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_dir.__truediv__.return_value = mock_path
        
        # Mock open()
        with patch("builtins.open", mock_open(read_data=json.dumps(mock_state))):
            response = client.get("/api/state")
            assert response.status_code == 200
            data = response.json()
            assert data["portfolio"]["cash"]["net_liquidity"] == 150000.0
            assert "oms_1" in data["orders"]


def test_api_transactions_empty(client):
    """Test /api/transactions returns empty list when file doesn't exist."""
    with patch("src.dashboard.app.EXECUTION_DIR") as mock_dir, \
         patch("src.dashboard.app.db") as mock_db:
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_dir.__truediv__.return_value = mock_path
        
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_db.get_connection.return_value = mock_conn
        
        response = client.get("/api/transactions")
        assert response.status_code == 200
        assert response.json() == []


def test_api_transactions_sorted(client):
    """Test /api/transactions sorts records descending by timestamp."""
    mock_txs = [
        {"symbol": "AAPL", "timestamp": "2026-07-02T10:00:00Z"},
        {"symbol": "MSFT", "timestamp": "2026-07-02T11:00:00Z"},
    ]
    
    with patch("src.dashboard.app.EXECUTION_DIR") as mock_dir:
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_dir.__truediv__.return_value = mock_path
        
        with patch("builtins.open", mock_open(read_data=json.dumps(mock_txs))):
            response = client.get("/api/transactions")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            # Should be sorted newest first (MSFT first)
            assert data[0]["symbol"] == "MSFT"


@patch("src.dashboard.app.DataStore")
@patch("src.strategy.strategies.MACrossoverStrategy")
@patch("src.strategy.strategies.RSIMeanReversionStrategy")
@patch("src.strategy.strategies.BollingerSqueezeStrategy")
@patch("src.strategy.strategies.SectorMomentumStrategy")
@patch("src.strategy.strategies.OptionsIVRunupStrategy")
@patch("src.strategy.strategies.BreadthThrustReversionStrategy")
def test_api_signals_generation(
    mock_breadth, mock_iv, mock_sector, mock_bb, mock_rsi, mock_ma, mock_datastore_cls, client
):
    """Test /api/signals correctly queries indicators and runs strategies."""
    # Mock DataStore
    mock_store_instance = MagicMock()
    mock_datastore_cls.return_value = mock_store_instance
    
    # Mock loaded DataFrame (30 rows so ensure_symbol_data returns it, timezone-aware)
    import pandas as pd
    mock_df = pd.DataFrame(
        {"close": [float(i + 140) for i in range(30)],
         "open": [float(i + 139) for i in range(30)],
         "high": [float(i + 142) for i in range(30)],
         "low": [float(i + 138) for i in range(30)],
         "volume": [1_000_000.0] * 30},
        index=pd.date_range("2026-06-01", periods=30, freq="B", tz="America/New_York")
    )
    mock_df.attrs["symbol"] = "AAPL"
    mock_store_instance.load.return_value = mock_df

    # Mock strategies to return signal DataFrames
    mock_sig_df = pd.DataFrame({"signal": [0] * 29 + [1]}, index=mock_df.index)
    
    mock_ma_inst = MagicMock()
    mock_ma_inst.name = "MACrossover"
    mock_ma_inst.generate_signals.return_value = mock_sig_df
    mock_ma.return_value = mock_ma_inst

    mock_rsi_inst = MagicMock()
    mock_rsi_inst.name = "RSIMeanReversion"
    mock_rsi_inst.generate_signals.return_value = mock_sig_df
    mock_rsi.return_value = mock_rsi_inst

    mock_bb_inst = MagicMock()
    mock_bb_inst.name = "BollingerSqueeze"
    mock_bb_inst.generate_signals.return_value = mock_sig_df
    mock_bb.return_value = mock_bb_inst

    mock_sec_inst = MagicMock()
    mock_sec_inst.name = "SectorMomentum"
    mock_sec_inst.generate_signals.return_value = mock_sig_df
    mock_sector.return_value = mock_sec_inst

    mock_iv_inst = MagicMock()
    mock_iv_inst.name = "OptionsIVRunup"
    mock_iv_inst.generate_signals.return_value = mock_sig_df
    mock_iv.return_value = mock_iv_inst

    mock_br_inst = MagicMock()
    mock_br_inst.name = "BreadthThrustReversion"
    mock_br_inst.generate_signals.return_value = mock_sig_df
    mock_breadth.return_value = mock_br_inst

    # Clear in-memory caches so we force fresh recalculation (not 60s TTL cache)
    import src.dashboard.app as dash_app
    dash_app._signal_in_memory_cache = {}
    dash_app._signal_cache_last_updated = None

    # Mock db.execute_query to return empty signal cache rows (force recalculation)
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []

    with patch("src.dashboard.app.db") as mock_db:
        mock_db.execute_query.return_value = mock_cursor
        response = client.get("/api/signals")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert data[0]["symbol"] == "AAPL"
        assert data[0]["MACrossover"] == 1
        assert data[0]["SectorMomentum"] == 1
        # close_price should match the last row of our mock DataFrame (140 + 29 = 169.0)
        assert data[0]["close_price"] == pytest.approx(169.0, rel=1e-3)


def test_api_health_with_logs(client):
    """Test /api/health returns healthy status and reads logs file."""
    mock_logs = ["Log 1", "Log 2"]
    with patch("src.dashboard.app.LOGS_DIR") as mock_dir:
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_dir.__truediv__.return_value = mock_path
        
        with patch("builtins.open", mock_open(read_data="\n".join(mock_logs))):
            response = client.get("/api/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "HEALTHY"
            assert data["log_entries"] == mock_logs


def test_api_performance(client):
    """Test that /api/performance returns equity history and statistics."""
    with patch("src.dashboard.app.EXECUTION_DIR") as mock_dir, \
         patch("src.dashboard.app.db") as mock_db:
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_dir.__truediv__.return_value = mock_path
        
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"count": 0}
        mock_db.get_connection.return_value = mock_conn
        
        response = client.get("/api/performance")
        assert response.status_code == 200
        data = response.json()
        assert "dates" in data
        assert "equity" in data
        assert "stats" in data
        assert data["stats"]["sharpe_ratio"] == 2.14


def test_api_action_toggle(client):
    """Test /api/action/toggle endpoint activates/deactivates the bot flag."""
    with patch("src.dashboard.app.EXECUTION_DIR") as mock_dir:
        mock_path = MagicMock()
        mock_dir.__truediv__.return_value = mock_path
        
        # Test toggle active (True)
        with patch("builtins.open", mock_open()) as mock_f:
            response = client.post("/api/action/toggle?active=true")
            assert response.status_code == 200
            assert response.json()["active"] is True
            mock_f.assert_called_once()
            
        # Test toggle active (False)
        mock_path.exists.return_value = True
        response = client.post("/api/action/toggle?active=false")
        assert response.status_code == 200
        assert response.json()["active"] is False
        mock_path.unlink.assert_called_once()


@patch("src.dashboard.app.DataStore")
def test_api_action_liquidate(mock_ds_cls, client):
    """Test /api/action/liquidate endpoint flattens all portfolio positions and logs trades."""
    # Mock positions in state
    mock_state = {
        "orders": {},
        "portfolio": {
            "positions": {
                "AAPL": {"symbol": "AAPL", "quantity": 10, "cost_price": 150.0}
            },
            "cash": {"net_liquidity": 100000.0, "cash_balance": 98500.0}
        }
    }
    
    # Mock DataStore load for AAPL close price
    import pandas as pd
    mock_store = MagicMock()
    mock_df = pd.DataFrame({"close": [155.0]}, index=pd.to_datetime(["2026-07-02"]))
    mock_store.load.return_value = mock_df
    mock_ds_cls.return_value = mock_store
    
    with patch("src.dashboard.app.EXECUTION_DIR") as mock_dir:
        # Create separate mock paths for state and transactions
        mock_state_path = MagicMock()
        mock_state_path.exists.return_value = True
        
        mock_tx_path = MagicMock()
        mock_tx_path.exists.return_value = False  # Make transactions.json not exist so it starts fresh!
        
        def resolve_path(name):
            if "state" in str(name):
                return mock_state_path
            return mock_tx_path
            
        mock_dir.__truediv__.side_effect = resolve_path
        
        # Mock file operations for loading state and saving state/transactions
        state_json_str = json.dumps(mock_state)
        
        # When opening, we check if it is reading the state file or transaction file
        # We can mock open to return state_json_str for state and empty list/empty file for transactions
        open_mock = mock_open()
        
        # Customize file read return values based on path string opened
        def open_side_effect(file, mode="r", *args, **kwargs):
            if file == mock_state_path:
                return mock_open(read_data=state_json_str)(file, mode)
            # Transactions read
            return mock_open(read_data="[]")(file, mode)
            
        open_mock.side_effect = open_side_effect
        
        with patch("builtins.open", open_mock):
            response = client.post("/api/action/liquidate")
            assert response.status_code == 200
            assert response.json()["status"] == "success"


def test_run_backtest_endpoint(client):
    """Verify that the POST /api/backtest/run endpoint executes backtest simulations and returns structured results."""
    # 1. Test missing payload
    res_bad = client.post("/api/backtest/run", json={})
    assert res_bad.status_code == 400
    
    # 2. Test execution success by mocking DataStore, strategies, and BacktestEngine
    import pandas as pd
    mock_df = pd.DataFrame({
        "open": [10.0, 11.0, 12.0],
        "high": [12.0, 13.0, 14.0],
        "low": [9.0, 10.0, 11.0],
        "close": [11.0, 12.0, 13.0],
        "volume": [1000, 1500, 2000]
    })
    
    with patch("src.dashboard.app.DataStore") as mock_store_cls, \
         patch("src.backtest.engine.BacktestEngine") as mock_engine_cls:
         
        # Set up DataStore mock
        mock_store = MagicMock()
        mock_store.load.return_value = mock_df
        mock_store_cls.return_value = mock_store
        
        # Set up BacktestEngine mock
        mock_engine = MagicMock()
        import pandas as pd
        mock_equity_curve = pd.Series([100000.0, 105000.0], index=[pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-02")])
        mock_engine.run.return_value = {
            "metrics": {
                "cagr": 0.15,
                "sharpe": 1.25,
                "sortino": 1.5,
                "max_drawdown": 0.05,
                "win_rate": 0.60,
                "total_trades": 12,
                "profit_factor": 1.8
            },
            "equity_curve": mock_equity_curve
        }
        mock_engine_cls.return_value = mock_engine
        
        # Run test post request
        payload = {
            "strategy": "IchimokuCloud",
            "symbol": "AAPL",
            "capital": 100000.0
        }
        res = client.post("/api/backtest/run", json=payload)
        
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert "metrics" in data
        assert data["metrics"]["sharpe"] == 1.25
        assert data["metrics"]["win_rate"] == 0.60
        assert len(data["equity_curve"]) == 2
        assert data["equity_curve"][0]["date"] == "2023-01-01"
        assert data["equity_curve"][0]["value"] == 100000.0


def test_api_decisions(client):
    """Test /api/decisions returns the systematic decision logs from db."""
    mock_conn = MagicMock()
    mock_conn.execute_query.return_value.fetchall.return_value = [
        (1, "cycle_123", "2026-07-08T16:00:00", "XLK", 0.55, '{"SectorMomentum": 1}', 100000.0, 0.024, 1, None, 0.035, "BUY_ORDER_PLACED")
    ]
    with patch("src.dashboard.app.db", mock_conn):
        res = client.get("/api/decisions")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["cycle_id"] == "cycle_123"
        assert data[0]["symbol"] == "XLK"
        assert data[0]["regime_hurst"] == 0.55
        assert data[0]["strategy_signals"] == {"SectorMomentum": 1}
        assert data[0]["portfolio_equity"] == 100000.0
        assert data[0]["portfolio_heat"] == 0.024
        assert data[0]["risk_passed"] is True
        assert data[0]["risk_reason"] is None
        assert data[0]["tims_stress_pct"] == 0.035
        assert data[0]["action_taken"] == "BUY_ORDER_PLACED"


def test_dashboard_viewer_read_endpoints_pass(client):
    """Test that a read-only viewer can access read routes and get their role successfully."""
    app.dependency_overrides.clear()
    
    # 1. Check role endpoint
    res = client.get("/api/auth/role", auth=("viewer", "hats_viewer_pass"))
    assert res.status_code == 200
    assert res.json()["role"] == "readonly"

    # 2. Check read endpoint
    mock_conn = MagicMock()
    mock_conn.execute_query.return_value.fetchall.return_value = []
    with patch("src.dashboard.app.db", mock_conn):
        res = client.get("/api/transactions", auth=("viewer", "hats_viewer_pass"))
        assert res.status_code == 200


def test_dashboard_viewer_write_endpoints_fail(client):
    """Test that a read-only viewer is forbidden (403) from calling write/action routes."""
    app.dependency_overrides.clear()
    
    # 1. Try bot toggle
    res = client.post("/api/action/toggle?active=true", auth=("viewer", "hats_viewer_pass"))
    assert res.status_code == 403
    assert "Admin privilege required" in res.json()["detail"]

    # 2. Try liquidate
    res = client.post("/api/action/liquidate", auth=("viewer", "hats_viewer_pass"))
    assert res.status_code == 403
    assert "Admin privilege required" in res.json()["detail"]

    # 3. Try backtest run
    res = client.post("/api/backtest/run", json={"strategy": "IchimokuCloud", "symbol": "AAPL"}, auth=("viewer", "hats_viewer_pass"))
    assert res.status_code == 403
    assert "Admin privilege required" in res.json()["detail"]


def test_dashboard_admin_write_endpoints_pass(client):
    """Test that an administrator can successfully execute write/action routes."""
    app.dependency_overrides.clear()
    
    # Check bot toggle works for admin
    with patch("src.dashboard.app.EXECUTION_DIR") as mock_exec_dir:
        # Mocking Path flag operations to succeed
        mock_flag = MagicMock()
        mock_exec_dir.__truediv__.return_value = mock_flag
        
        with patch("builtins.open", mock_open()) as mock_f:
            res = client.post("/api/action/toggle?active=true", auth=("admin", "hats_secure_pass"))
            assert res.status_code == 200
            assert res.json()["active"] is True
            mock_f.assert_called_once()

