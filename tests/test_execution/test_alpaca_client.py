import os
from unittest.mock import MagicMock, patch
import pytest
from src.execution.alpaca_client import (
    AlpacaClient,
    AlpacaError,
    AlpacaAPIError,
    AlpacaConnectionError,
)

@patch.dict(os.environ, {'APCA_API_KEY_ID': 'test_key', 'APCA_API_SECRET_KEY': 'test_secret', 'ALPACA_PAPER': '1'})
@patch('alpaca.trading.client.TradingClient')
def test_alpaca_client_init(mock_trading_client):
    client = AlpacaClient()
    assert client.paper is True

@patch.dict(os.environ, {'APCA_API_KEY_ID': '', 'APCA_API_SECRET_KEY': ''})
def test_alpaca_client_missing_credentials():
    with pytest.raises(AlpacaError, match='Alpaca credentials missing'):
        AlpacaClient()

@patch.dict(os.environ, {'APCA_API_KEY_ID': 'test_key', 'APCA_API_SECRET_KEY': 'test_secret'})
@patch('alpaca.trading.client.TradingClient')
def test_normalize_status(mock_trading_client):
    client = AlpacaClient()
    assert client._normalize_status('OrderStatus.FILLED') == 'FILLED'
    assert client._normalize_status('OrderStatus.CANCELED') == 'CANCELED'
    assert client._normalize_status('OrderStatus.REJECTED') == 'FAILED'
    assert client._normalize_status('OrderStatus.NEW') == 'SUBMITTED'


@patch.dict(os.environ, {'APCA_API_KEY_ID': 'test_key', 'APCA_API_SECRET_KEY': 'test_secret'})
@patch('alpaca.trading.client.TradingClient')
def test_classify_exception_unauthorized(mock_trading_client):
    from src.execution.alpaca_client import AlpacaAuthError
    client = AlpacaClient()
    raw_exc = Exception('{"message": "unauthorized."}')
    classified = client._classify_exception(raw_exc, "test_context")
    assert isinstance(classified, AlpacaAuthError)
    assert "Authentication Failed" in str(classified)


@patch.dict(os.environ, {'APCA_API_KEY_ID': 'test_key', 'APCA_API_SECRET_KEY': 'test_secret'})
@patch('alpaca.trading.client.TradingClient')
def test_classify_exception_network_timeout(mock_trading_client):
    client = AlpacaClient()
    raw_exc = TimeoutError("Connection timed out")
    classified = client._classify_exception(raw_exc, "test_context")
    assert isinstance(classified, AlpacaConnectionError)


@patch.dict(os.environ, {'APCA_API_KEY_ID': 'test_key', 'APCA_API_SECRET_KEY': 'test_secret'})
@patch('alpaca.trading.client.TradingClient')
def test_place_order_bracket(mock_trading_client):
    """Test that specifying both stop_price and take_profit submits an OrderClass.BRACKET order."""
    from unittest.mock import MagicMock
    from alpaca.trading.enums import OrderClass

    client = AlpacaClient()
    mock_order = MagicMock()
    mock_order.id = "mock-bracket-123"
    mock_order.status = "accepted"
    client._client.submit_order.return_value = mock_order

    res = client.place_order(
        account_id="acc",
        symbol="SPY",
        side="BUY",
        qty=10,
        price=500.0,
        stop_price=490.0,
        take_profit=520.0,
    )
    assert res["order_id"] == "mock-bracket-123"
    client._client.submit_order.assert_called_once()
    called_req = client._client.submit_order.call_args[1]["order_data"]
    assert called_req.order_class == OrderClass.BRACKET
    assert called_req.stop_loss.stop_price == 490.0
    assert called_req.take_profit.limit_price == 520.0

