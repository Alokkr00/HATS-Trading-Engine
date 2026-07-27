"""Unit tests for the Order Management System (OMS)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.execution.oms import OrderManager
from src.execution.alpaca_client import (
    AlpacaAPIError as WebullAPIError,
    AlpacaClient as WebullClient,
    AlpacaConnectionError as WebullConnectionError,
)


@pytest.fixture
def mock_client() -> MagicMock:
    """Fixture creating a mocked WebullClient."""
    client = MagicMock(spec=WebullClient)
    # Default mock behavior to avoid errors during OrderManager.__init__ recovery
    client.get_open_orders.return_value = []
    client.get_positions.return_value = {"positions": [], "cash": {}}
    return client


@pytest.fixture
def temp_log_dir(tmp_path) -> Path:
    """Fixture returning a temp path for the log/state directory."""
    return tmp_path


def test_oms_init_creates_state_file(mock_client, temp_log_dir) -> None:
    """Verify that OrderManager initializes state and creates oms_state.json."""
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    
    state_file = temp_log_dir / "oms_state.json"
    assert state_file.exists()
    
    # Load state file and check default contents
    with open(state_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "orders" in data
    assert "portfolio" in data
    assert data["portfolio"]["cash"]["net_liquidity"] == 0.0


def test_place_trade_validation(mock_client, temp_log_dir) -> None:
    """Verify that OrderManager validates inputs and raises ValueError on invalid trade params."""
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    
    # Invalid symbol
    with pytest.raises(ValueError, match="Symbol must be a non-empty string"):
        oms.place_trade("", "BUY", 10, 100.0)
    
    # Invalid side
    with pytest.raises(ValueError, match="Side must be either 'BUY' or 'SELL'"):
        oms.place_trade("AAPL", "HOLD", 10, 100.0)
        
    # Invalid quantity
    with pytest.raises(ValueError, match="Quantity must be a positive integer"):
        oms.place_trade("AAPL", "BUY", 0, 100.0)
        
    # Invalid price
    with pytest.raises(ValueError, match="Price must be greater than zero"):
        oms.place_trade("AAPL", "BUY", 10, -5.0)
        
    # Invalid stop price
    with pytest.raises(ValueError, match="Stop price must be greater than zero"):
        oms.place_trade("AAPL", "BUY", 10, 100.0, stop_price=-1.0)


def test_place_trade_success(mock_client, temp_log_dir) -> None:
    """Test standard successful order submission flow."""
    mock_client.place_order.return_value = {"order_id": "broker_id_456"}
    
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    
    order_id = oms.place_trade(symbol="AAPL", side="BUY", qty=10, price=150.0)
    
    assert order_id == "broker_id_456"
    mock_client.place_order.assert_called_once()
    
    # Verify state changes
    state_file = temp_log_dir / "oms_state.json"
    with open(state_file, "r", encoding="utf-8") as f:
        state = json.load(f)
        
    assert len(state["orders"]) == 1
    client_ord_id = list(state["orders"].keys())[0]
    order_data = state["orders"][client_ord_id]
    
    assert order_data["status"] == "SUBMITTED"
    assert order_data["order_id"] == "broker_id_456"
    assert order_data["symbol"] == "AAPL"
    assert order_data["side"] == "BUY"
    assert order_data["qty"] == 10
    assert order_data["price"] == 150.0


def test_place_trade_api_failure(mock_client, temp_log_dir) -> None:
    """Verify that WebullAPIError marks trade state as FAILED and doesn't propagate error."""
    mock_client.place_order.side_effect = WebullAPIError("Margin violation: insufficient funds")
    
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    
    order_id = oms.place_trade(symbol="AAPL", side="BUY", qty=10, price=150.0)
    
    assert order_id is None
    
    # Verify state changes to FAILED
    with open(temp_log_dir / "oms_state.json", "r", encoding="utf-8") as f:
        state = json.load(f)
        
    client_ord_id = list(state["orders"].keys())[0]
    order_data = state["orders"][client_ord_id]
    
    assert order_data["status"] == "FAILED"
    assert "Margin violation" in order_data["error_reason"]


@patch("time.sleep", return_value=None)
def test_place_trade_connection_retry(mock_sleep, mock_client, temp_log_dir) -> None:
    """Verify that place_trade retries on transient connection error and succeeds if connection is restored."""
    # First 2 calls fail with ConnectionError, 3rd succeeds
    mock_client.place_order.side_effect = [
        WebullConnectionError("Timeout"),
        WebullConnectionError("Host unreachable"),
        {"order_id": "broker_id_retry"},
    ]
    
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    
    order_id = oms.place_trade(symbol="MSFT", side="SELL", qty=5)
    
    assert order_id == "broker_id_retry"
    assert mock_client.place_order.call_count == 3
    assert mock_sleep.call_count == 2
    
    # Verify state is SUBMITTED
    with open(temp_log_dir / "oms_state.json", "r", encoding="utf-8") as f:
        state = json.load(f)
        
    client_ord_id = list(state["orders"].keys())[0]
    assert state["orders"][client_ord_id]["status"] == "SUBMITTED"


@patch("time.sleep", return_value=None)
def test_place_trade_connection_persistent_failure(mock_sleep, mock_client, temp_log_dir) -> None:
    """Verify that place_trade propagates WebullConnectionError after maximum retries expire, leaving state as PENDING_SUBMIT."""
    mock_client.place_order.side_effect = WebullConnectionError("Persistent connection failure")
    
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    
    with pytest.raises(WebullConnectionError):
        oms.place_trade(symbol="MSFT", side="SELL", qty=5)
        
    assert mock_client.place_order.call_count == 5
    
    # Verify state remains PENDING_SUBMIT
    with open(temp_log_dir / "oms_state.json", "r", encoding="utf-8") as f:
        state = json.load(f)
        
    client_ord_id = list(state["orders"].keys())[0]
    assert state["orders"][client_ord_id]["status"] == "PENDING_SUBMIT"


def test_sync_orders_resolves_filled_order(mock_client, temp_log_dir) -> None:
    """Verify that sync_orders detects when an order is filled, logs it, and syncs portfolio."""
    mock_client.place_order.return_value = {"order_id": "broker_111"}
    
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    
    # Place order
    oms.place_trade("AAPL", "BUY", 10, 150.0)
    
    # Configure mock for sync_orders:
    # 1. get_open_orders returns empty (the order is no longer working)
    mock_client.get_open_orders.return_value = []
    # 2. get_order returns details showing it was FILLED
    mock_client.get_order.return_value = {
        "order_id": "broker_111",
        "status": "FILLED",
        "filled_qty": 10,
    }
    # 3. get_positions returns updated positions
    mock_client.get_positions.return_value = {
        "positions": [{"symbol": "AAPL", "qty": 10, "cost_basis": 150.0}],
        "cash": {"net_liquidity": 98500.0, "cash_balance": 98500.0},
    }
    
    oms.sync_orders()
    
    # Verify state updated to FILLED
    with open(temp_log_dir / "oms_state.json", "r", encoding="utf-8") as f:
        state = json.load(f)
    
    client_ord_id = list(state["orders"].keys())[0]
    assert state["orders"][client_ord_id]["status"] == "FILLED"
    assert state["orders"][client_ord_id]["filled_qty"] == 10
    
    # Verify transaction JSON log
    tx_json_path = temp_log_dir / "transactions.json"
    assert tx_json_path.exists()
    with open(tx_json_path, "r", encoding="utf-8") as f:
        txs = json.load(f)
    assert len(txs) == 1
    assert txs[0]["order_id"] == "broker_111"
    assert txs[0]["symbol"] == "AAPL"
    
    # Verify transaction Parquet log
    tx_parquet_path = temp_log_dir / "transactions.parquet"
    assert tx_parquet_path.exists()
    df = pd.read_parquet(tx_parquet_path)
    assert len(df) == 1
    assert df.iloc[0]["order_id"] == "broker_111"


def test_reboot_recovery_pending_submit_not_found(mock_client, temp_log_dir) -> None:
    """Test recovery: PENDING_SUBMIT order not found at broker is marked FAILED to prevent duplicate placement."""
    # Write a pre-existing state containing a pending submit order
    initial_state = {
        "orders": {
            "oms_pending_1": {
                "client_order_id": "oms_pending_1",
                "order_id": None,
                "symbol": "AAPL",
                "side": "BUY",
                "qty": 10,
                "status": "PENDING_SUBMIT",
                "filled_qty": 0,
            }
        },
        "portfolio": {"positions": {}, "cash": {}},
    }
    
    state_file = temp_log_dir / "oms_state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(initial_state, f)
        
    # Broker has no open orders and no positions
    mock_client.get_open_orders.return_value = []
    
    # Instantiate OMS, triggering recover_state()
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    
    # Verify that recovery marked the pending order as FAILED
    with open(state_file, "r", encoding="utf-8") as f:
        state = json.load(f)
        
    assert state["orders"]["oms_pending_1"]["status"] == "FAILED"
    assert "System rebooted before order ID was received" in state["orders"]["oms_pending_1"]["error_reason"]


def test_reboot_recovery_pending_submit_found_open(mock_client, temp_log_dir) -> None:
    """Test recovery: PENDING_SUBMIT order found in open orders is linked and updated to active status."""
    initial_state = {
        "orders": {
            "oms_pending_2": {
                "client_order_id": "oms_pending_2",
                "order_id": None,
                "symbol": "TSLA",
                "side": "SELL",
                "qty": 20,
                "status": "PENDING_SUBMIT",
                "filled_qty": 0,
            }
        },
        "portfolio": {"positions": {}, "cash": {}},
    }
    
    state_file = temp_log_dir / "oms_state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(initial_state, f)
        
    # Broker open orders includes this client order ID
    mock_client.get_open_orders.return_value = [
        {
            "order_id": "broker_tsla_200",
            "client_order_id": "oms_pending_2",
            "symbol": "TSLA",
            "side": "SELL",
            "qty": 20,
            "status": "PARTIALLY_FILLED",
            "filled_qty": 5,
        }
    ]
    
    # Instantiate OMS
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    
    # Verify recovery linked the order_id and updated the status/filled_qty
    with open(state_file, "r", encoding="utf-8") as f:
        state = json.load(f)
        
    order = state["orders"]["oms_pending_2"]
    assert order["order_id"] == "broker_tsla_200"
    assert order["status"] == "PARTIALLY_FILLED"
    assert order["filled_qty"] == 5


def test_reboot_recovery_submitted_resolved_filled(mock_client, temp_log_dir) -> None:
    """Test recovery: SUBMITTED order no longer open on broker is resolved as FILLED by querying its details."""
    initial_state = {
        "orders": {
            "oms_submitted_3": {
                "client_order_id": "oms_submitted_3",
                "order_id": "broker_sub_300",
                "symbol": "NFLX",
                "side": "BUY",
                "qty": 15,
                "status": "SUBMITTED",
                "filled_qty": 0,
            }
        },
        "portfolio": {"positions": {}, "cash": {}},
    }
    
    state_file = temp_log_dir / "oms_state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(initial_state, f)
        
    # Broker open orders does not contain the order
    mock_client.get_open_orders.return_value = []
    
    # Broker individual order status query shows FILLED
    mock_client.get_order.return_value = {
        "order_id": "broker_sub_300",
        "client_order_id": "oms_submitted_3",
        "symbol": "NFLX",
        "side": "BUY",
        "qty": 15,
        "status": "FILLED",
        "filled_qty": 15,
    }
    
    # Instantiate OMS
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    
    # Verify state resolved as FILLED
    with open(state_file, "r", encoding="utf-8") as f:
        state = json.load(f)
        
    order = state["orders"]["oms_submitted_3"]
    assert order["status"] == "FILLED"
    assert order["filled_qty"] == 15
    
    # Verify transaction logged
    tx_json_path = temp_log_dir / "transactions.json"
    assert tx_json_path.exists()
    with open(tx_json_path, "r", encoding="utf-8") as f:
        txs = json.load(f)
    assert len(txs) == 1
    assert txs[0]["order_id"] == "broker_sub_300"


def test_append_to_json_list_malformed_fallback(mock_client, temp_log_dir) -> None:
    """Verify that O(1) append falls back to full rewrite and succeeds when JSON is malformed."""
    oms = OrderManager(client=mock_client, account_id="acc123", log_dir=str(temp_log_dir))
    tx_json_path = temp_log_dir / "transactions.json"

    # Write a malformed JSON file (no closing bracket ']')
    with open(tx_json_path, "w", encoding="utf-8") as f:
        f.write('[{"item": 1}')  # Malformed: missing closing bracket

    new_item = {"item": 2}
    # This should trigger the fallback, load the file, parse/reconstruct, and write it back successfully
    oms._append_to_json_list(tx_json_path, new_item)

    assert tx_json_path.exists()
    with open(tx_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 2
    assert data[0]["item"] == 1
    assert data[1]["item"] == 2
