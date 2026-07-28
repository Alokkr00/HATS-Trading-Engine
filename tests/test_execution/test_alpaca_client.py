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
