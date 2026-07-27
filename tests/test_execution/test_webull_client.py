import os
import pytest
from unittest.mock import MagicMock, patch
from src.execution.webull_client import WebullClient, WebullAPIError, WebullConnectionError


@pytest.fixture(autouse=True)
def mock_load_dotenv():
    """Mock load_dotenv to prevent loading physical .env files during webull client testing."""
    with patch("src.execution.webull_client.load_dotenv") as mock:
        yield mock


def test_auth_validation_raises_value_error(monkeypatch):
    """Test that WebullClient raises ValueError when credentials are missing and dry_run=False."""
    # Ensure no environment variables are present
    monkeypatch.delenv("WEBULL_APP_KEY", raising=False)
    monkeypatch.delenv("WEBULL_APP_SECRET", raising=False)
    monkeypatch.setenv("WEBULL_FORCE_VALIDATION", "1")

    with pytest.raises(ValueError) as excinfo:
        WebullClient(app_key=None, app_secret=None, dry_run=False, environment="paper")
    assert "Webull App Key and Secret must be provided" in str(excinfo.value)


@patch("webull.core.http.initializer.client_initializer.ClientInitializer.initializer")
def test_successful_auth_with_provided_credentials(mock_init):
    """Test that WebullClient initializes correctly when credentials are provided."""
    client = WebullClient(app_key="my_key", app_secret="my_secret", dry_run=False, environment="paper")
    assert client.dry_run is False
    assert client.api_client.get_app_key() == "my_key"
    assert client.api_client.get_app_secret() == "my_secret"
    mock_init.assert_called_once()


def test_uat_and_production_endpoints():
    """Test that environment names map to correct endpoints."""
    # Test paper/uat
    client_paper = WebullClient(app_key="key", app_secret="secret", environment="paper", dry_run=True)
    assert client_paper.endpoint == "us-openapi-alb.uat.webullbroker.com"
    assert client_paper.environment == "paper"

    client_uat = WebullClient(app_key="key", app_secret="secret", environment="uat", dry_run=True)
    assert client_uat.endpoint == "us-openapi-alb.uat.webullbroker.com"
    assert client_uat.environment == "paper"

    # Test live/prod
    client_live = WebullClient(app_key="key", app_secret="secret", environment="live", dry_run=True)
    assert client_live.endpoint == "openapi.webullbroker.com"
    assert client_live.environment == "live"

    client_prod = WebullClient(app_key="key", app_secret="secret", environment="prod", dry_run=True)
    assert client_prod.endpoint == "openapi.webullbroker.com"
    assert client_prod.environment == "live"

    # Test invalid env
    with pytest.raises(ValueError) as excinfo:
        WebullClient(app_key="key", app_secret="secret", environment="invalid_env", dry_run=True)
    assert "Invalid environment" in str(excinfo.value)


def test_dry_run_flag_in_test_environment(monkeypatch):
    """Test that client falls back to dry-run in test environment if credentials are missing."""
    monkeypatch.delenv("WEBULL_APP_KEY", raising=False)
    monkeypatch.delenv("WEBULL_APP_SECRET", raising=False)

    # In a pytest run, "pytest" is in sys.modules, so it should auto-enable dry-run
    client = WebullClient(environment="paper")
    assert client.dry_run is True


def test_dry_run_methods():
    """Test that in dry_run mode, methods return expected mock data without network calls."""
    client = WebullClient(dry_run=True)
    assert client.dry_run is True

    # Test get_account_list
    accounts = client.get_account_list()
    assert isinstance(accounts, list)
    assert len(accounts) == 1
    assert accounts[0]["account_id"] == "mock_account_12345"

    # Test get_positions
    portfolio_res = client.get_positions("mock_account_12345")
    assert isinstance(portfolio_res, dict)
    positions = portfolio_res["positions"]
    assert isinstance(positions, list)
    assert len(positions) == 2
    assert positions[0]["symbol"] == "AAPL"
    assert "cash" in portfolio_res

    # Test get_open_orders
    open_orders = client.get_open_orders("mock_account_12345")
    assert isinstance(open_orders, list)
    assert len(open_orders) == 1
    assert open_orders[0]["symbol"] == "TSLA"

    # Test place_order (LIMIT)
    order_res = client.place_order(
        account_id="mock_account_12345",
        symbol="AAPL",
        qty=10,
        side="BUY",
        order_type="LIMIT",
        price=180.50
    )
    assert order_res["status"] == "success"
    assert "mock_order_" in order_res["order_id"]
    assert len(order_res["client_order_id"]) == 32  # uuid hex length

    # Test place_order (MARKET)
    market_order_res = client.place_order(
        account_id="mock_account_12345",
        symbol="AAPL",
        qty=5,
        side="SELL",
        order_type="MARKET"
    )
    assert market_order_res["status"] == "success"
    assert "mock_order_" in market_order_res["order_id"]

    # Test cancel_order
    cancel_res = client.cancel_order(
        account_id="mock_account_12345",
        order_id="mock_order_001"
    )
    assert cancel_res["status"] == "success"
    assert cancel_res["order_id"] == "mock_order_001"


def test_place_order_parameter_validation():
    """Test parameter validation in place_order."""
    client = WebullClient(dry_run=True)

    # Test invalid side
    with pytest.raises(ValueError) as excinfo:
        client.place_order("acc_id", "AAPL", 10, "INVALID_SIDE", "LIMIT", 150.0)
    assert "Invalid side" in str(excinfo.value)

    # Test missing price for LIMIT order
    with pytest.raises(ValueError) as excinfo:
        client.place_order("acc_id", "AAPL", 10, "BUY", "LIMIT", None)
    assert "Price is required for LIMIT orders" in str(excinfo.value)


@patch("src.execution.webull_client.ApiClient")
@patch("src.execution.webull_client.TradeClient")
@patch("webull.core.http.initializer.client_initializer.ClientInitializer.initializer")
def test_real_client_integration(mock_init, mock_trade_client_cls, mock_api_client_cls):
    """Test that real mode correctly forwards calls to SDK and handles success."""
    mock_api_instance = MagicMock()
    mock_api_client_cls.return_value = mock_api_instance
    
    mock_trade_instance = MagicMock()
    mock_trade_client_cls.return_value = mock_trade_instance

    # Instantiate in non-dry-run mode
    client = WebullClient(app_key="key", app_secret="secret", dry_run=False)
    assert client.dry_run is False

    # 1. Test get_account_list
    mock_response_accounts = MagicMock()
    mock_response_accounts.status_code = 200
    mock_response_accounts.json.return_value = [{"account_id": "real_acc_1"}]
    mock_trade_instance.account_v2.get_account_list.return_value = mock_response_accounts

    accounts = client.get_account_list()
    assert accounts == [{"account_id": "real_acc_1"}]
    mock_trade_instance.account_v2.get_account_list.assert_called_once()

    # 2. Test get_positions
    mock_response_positions = MagicMock()
    mock_response_positions.status_code = 200
    mock_response_positions.json.return_value = [{"position_id": "pos_1", "symbol": "NVDA"}]
    mock_trade_instance.account_v2.get_account_position.return_value = mock_response_positions

    mock_response_balance = MagicMock()
    mock_response_balance.status_code = 200
    mock_response_balance.json.return_value = {"net_liquidity": 120000.0, "cash_balance": 110000.0}
    mock_trade_instance.account_v2.get_account_balance.return_value = mock_response_balance

    portfolio_res = client.get_positions("real_acc_1")
    assert portfolio_res["positions"] == [{"position_id": "pos_1", "symbol": "NVDA"}]
    assert portfolio_res["cash"]["net_liquidity"] == 120000.0
    mock_trade_instance.account_v2.get_account_position.assert_called_once_with("real_acc_1")
    mock_trade_instance.account_v2.get_account_balance.assert_called_once_with("real_acc_1")

    # 3. Test get_open_orders
    mock_response_orders = MagicMock()
    mock_response_orders.status_code = 200
    mock_response_orders.json.return_value = {"orders": [{"order_id": "ord_1"}]}
    mock_trade_instance.order_v2.get_order_open.return_value = mock_response_orders

    open_orders = client.get_open_orders("real_acc_1")
    assert open_orders == [{"order_id": "ord_1"}]
    mock_trade_instance.order_v2.get_order_open.assert_called_once_with("real_acc_1")

    # 4. Test place_order
    mock_response_place = MagicMock()
    mock_response_place.status_code = 200
    mock_response_place.json.return_value = {"order_id": "webull_ord_999", "client_order_id": "client_ord_999"}
    mock_trade_instance.order_v2.place_order.return_value = mock_response_place

    order_res = client.place_order("real_acc_1", "AAPL", 100, "BUY", "LIMIT", 185.50)
    assert order_res["status"] == "success"
    assert order_res["order_id"] == "webull_ord_999"
    mock_trade_instance.order_v2.place_order.assert_called_once()
    
    # Verify price formatting (price >= 1.0 -> 2 decimals, price < 1.0 -> 4 decimals)
    mock_trade_instance.order_v2.place_order.reset_mock()
    client.place_order("real_acc_1", "PENNY", 1000, "BUY", "LIMIT", 0.1234)
    args, kwargs = mock_trade_instance.order_v2.place_order.call_args
    assert args[1][0]["limit_price"] == "0.1234"

    # 5. Test cancel_order
    mock_response_cancel = MagicMock()
    mock_response_cancel.status_code = 200
    mock_response_cancel.json.return_value = {"client_order_id": "client_ord_999"}
    mock_trade_instance.order_v2.cancel_order.return_value = mock_response_cancel

    cancel_res = client.cancel_order("real_acc_1", "client_ord_999")
    assert cancel_res["status"] == "success"
    mock_trade_instance.order_v2.cancel_order.assert_called_once_with("real_acc_1", "client_ord_999")


@patch("src.execution.webull_client.ApiClient")
@patch("src.execution.webull_client.TradeClient")
@patch("webull.core.http.initializer.client_initializer.ClientInitializer.initializer")
def test_real_client_error_handling(mock_init, mock_trade_client_cls, mock_api_client_cls):
    """Test that real mode wraps and raises errors when API fails."""
    mock_trade_instance = MagicMock()
    mock_trade_client_cls.return_value = mock_trade_instance

    client = WebullClient(app_key="key", app_secret="secret", dry_run=False)

    # Mock non-200 responses
    mock_err_response = MagicMock()
    mock_err_response.status_code = 400
    mock_err_response.text = "Invalid account ID"
    mock_trade_instance.account_v2.get_account_position.return_value = mock_err_response

    with pytest.raises(WebullAPIError) as excinfo:
        client.get_positions("bad_acc")
    assert "Failed to get positions" in str(excinfo.value)


def test_get_order_dry_run():
    """Test get_order in dry run mode."""
    client = WebullClient(dry_run=True)
    res = client.get_order("mock_acc", "mock_order_123")
    assert res["order_id"] == "mock_order_123"
    assert res["status"] == "FILLED"
    assert res["filled_qty"] == 10


@patch("src.execution.webull_client.ApiClient")
@patch("src.execution.webull_client.TradeClient")
@patch("webull.core.http.initializer.client_initializer.ClientInitializer.initializer")
def test_get_order_real_mode(mock_init, mock_trade_client_cls, mock_api_client_cls):
    """Test get_order in real mode checking both open orders search and history search."""
    mock_trade_instance = MagicMock()
    mock_trade_client_cls.return_value = mock_trade_instance

    client = WebullClient(app_key="key", app_secret="secret", dry_run=False)

    # Scenario 1: Order found in open orders
    mock_response_open = MagicMock()
    mock_response_open.status_code = 200
    mock_response_open.json.return_value = [
        {"order_id": "ord_open_1", "client_order_id": "c_open_1", "symbol": "AAPL", "side": "BUY", "quantity": "10", "limit_price": "150.0", "order_status": "PENDING", "filled_qty": "2"}
    ]
    mock_trade_instance.order_v2.get_order_open.return_value = mock_response_open

    res_open = client.get_order("acc_1", "ord_open_1")
    assert res_open["order_id"] == "ord_open_1"
    assert res_open["client_order_id"] == "c_open_1"
    assert res_open["status"] == "PENDING"
    assert res_open["filled_qty"] == 2
    assert res_open["qty"] == 10
    assert res_open["price"] == 150.0

    # Scenario 2: Order not in open orders, but found in history
    mock_response_open_empty = MagicMock()
    mock_response_open_empty.status_code = 200
    mock_response_open_empty.json.return_value = []
    mock_trade_instance.order_v2.get_order_open.return_value = mock_response_open_empty

    mock_response_history = MagicMock()
    mock_response_history.status_code = 200
    mock_response_history.json.return_value = {
        "orders": [
            {"order_id": "ord_hist_1", "client_order_id": "c_hist_1", "symbol": "MSFT", "side": "SELL", "quantity": "5", "limit_price": "350.0", "order_status": "FILLED", "filled_qty": "5"}
        ]
    }
    mock_trade_instance.order_v2.get_order_history.return_value = mock_response_history

    res_hist = client.get_order("acc_1", "ord_hist_1")
    assert res_hist["order_id"] == "ord_hist_1"
    assert res_hist["status"] == "FILLED"
    assert res_hist["qty"] == 5
    assert res_hist["filled_qty"] == 5

    # Scenario 3: Order not found anywhere raises WebullAPIError
    with pytest.raises(WebullAPIError) as excinfo:
        client.get_order("acc_1", "ord_nonexistent")
    assert "not found in open orders or history" in str(excinfo.value)


def test_token_bucket_rate_limiter() -> None:
    """Test standard TokenBucketRateLimiter token consumption and throttling."""
    from src.utils.rate_limiter import TokenBucketRateLimiter
    import time
    
    # Bucket rate = 10 tokens/sec, capacity = 2.
    limiter = TokenBucketRateLimiter(rate=10.0, capacity=2.0)
    
    # First 2 consume calls should succeed immediately
    assert limiter.consume(1.0) is True
    assert limiter.consume(1.0) is True
    # Third should fail as bucket is empty
    assert limiter.consume(1.0) is False
    
    # Wait for refill (0.1 second = 1 token refilled)
    time.sleep(0.12)
    assert limiter.consume(1.0) is True


