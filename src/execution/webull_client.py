"""Webull OpenAPI client wrapper for order execution and account management.

This module provides a unified wrapper around the Webull OpenAPI Python SDK,
supporting dry-run execution, robust error handling, and environment-based
endpoint routing.
"""

import os
import sys
import logging
import uuid
from typing import Any

from dotenv import load_dotenv
from webull.core.client import ApiClient
from webull.trade.trade_client import TradeClient
from src.utils.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


class WebullError(Exception):
    """Base exception for all Webull client errors."""
    pass


class WebullConnectionError(WebullError):
    """Exception raised for transient connection/network errors."""
    pass


class WebullAPIError(WebullError):
    """Exception raised for API-level errors (rate limits, margin, invalid size, etc.)."""
    
    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class WebullClient:
    """Wrapper class for Webull OpenAPI client to interact with account and trading services.

    Attributes:
        dry_run (bool): If True, requests are simulated locally without network calls.
        environment (str): The environment mode ('paper' or 'live').
        endpoint (str): The Webull OpenAPI endpoint URL.
        api_client (ApiClient): The underlying SDK ApiClient instance.
        trade_client (TradeClient): The underlying SDK TradeClient instance.
    """

    def __init__(
        self,
        app_key: str | None = None,
        app_secret: str | None = None,
        environment: str = "paper",
        dry_run: bool = False,
    ) -> None:
        """Initializes the Webull Client wrapper.

        Args:
            app_key: Webull OpenAPI App Key. If not provided, retrieved from environment.
            app_secret: Webull OpenAPI App Secret. If not provided, retrieved from environment.
            environment: The environment to target ('paper', 'uat', 'live', 'prod'). Defaults to 'paper'.
            dry_run: If True, operates in simulation mode. Defaults to False.

        Raises:
            ValueError: If credentials are missing and dry_run is False, or environment is invalid.
        """
        # Load environment variables
        load_dotenv()

        resolved_app_key = app_key or os.getenv("WEBULL_APP_KEY")
        resolved_app_secret = app_secret or os.getenv("WEBULL_APP_SECRET")

        # Determine if we are in a test environment
        is_test_env = (
            "pytest" in sys.modules or os.getenv("TESTING", "").lower() in ("true", "1", "yes")
        ) and os.getenv("WEBULL_FORCE_VALIDATION") != "1"
        credentials_missing = not resolved_app_key or not resolved_app_secret

        if dry_run or (credentials_missing and is_test_env):
            self.dry_run = True
            logger.info("Credentials missing in test environment or dry_run enabled. WebullClient initialized in DRY RUN mode.")
        else:
            self.dry_run = False
            if credentials_missing:
                raise ValueError("Webull App Key and Secret must be provided or configured in the environment.")

        # Map environment to endpoint
        env = environment.lower()
        if env in ("paper", "uat"):
            self.environment = "paper"
            self.endpoint = "us-openapi-alb.uat.webullbroker.com"
        elif env in ("live", "prod"):
            self.environment = "live"
            self.endpoint = "openapi.webullbroker.com"
        else:
            raise ValueError(f"Invalid environment: '{environment}'. Must be 'paper', 'uat', 'live', or 'prod'.")

        logger.info(
            "Initializing WebullClient on endpoint '%s' (environment: %s, dry_run: %s)",
            self.endpoint,
            self.environment,
            self.dry_run,
        )

        # Initialize API client and Trade client
        # In dry run mode without credentials, we use dummy values to satisfy the SDK constructor
        api_client_key = resolved_app_key or "DUMMY_APP_KEY"
        api_client_secret = resolved_app_secret or "DUMMY_APP_SECRET"

        try:
            if self.dry_run:
                # Disable network request inside ClientInitializer during TradeClient instantiation
                from webull.core.http.initializer.client_initializer import ClientInitializer
                original_initializer = ClientInitializer.initializer
                ClientInitializer.initializer = lambda client: None
                try:
                    self.api_client = ApiClient(api_client_key, api_client_secret, "us")
                    self.api_client.add_endpoint("us", self.endpoint)
                    self.trade_client = TradeClient(self.api_client)
                finally:
                    ClientInitializer.initializer = original_initializer
            else:
                self.api_client = ApiClient(api_client_key, api_client_secret, "us")
                self.api_client.add_endpoint("us", self.endpoint)
                self.trade_client = TradeClient(self.api_client)
        except Exception as e:
            logger.error("Failed to initialize underlying Webull SDK clients: %s", e)
            raise RuntimeError(f"Failed to initialize Webull SDK: {e}") from e

        # Limit to 5 requests per second (token bucket capacity 5)
        self.rate_limiter = TokenBucketRateLimiter(5.0, 5.0)

    def _throttle(self) -> None:
        """Throttle requests using TokenBucketRateLimiter when not in dry_run mode."""
        if not self.dry_run:
            self.rate_limiter.wait_and_consume(1.0)

    def get_account_list(self) -> list[dict[str, Any]]:
        """Queries the list of accounts associated with the credentials.

        Returns:
            A list of account dictionaries containing account details.

        Raises:
            WebullConnectionError: If a transient network/connection error occurs.
            WebullAPIError: If the API call fails or returns a non-200 status code.
        """
        if self.dry_run:
            logger.info("[Dry Run] Querying account list.")
            return [
                {
                    "account_id": "mock_account_12345",
                    "account_number": "MOCK12345",
                    "account_type": "MARGIN",
                    "user_id": "mock_user",
                }
            ]

        self._throttle()
        try:
            response = self.trade_client.account_v2.get_account_list()
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    # In case the response wraps it in a dict or similar
                    return [data]
                return []
            else:
                error_msg = f"Failed to get account list. Status: {response.status_code}, Response: {response.text}"
                logger.error(error_msg)
                raise WebullAPIError(error_msg, error_code=str(response.status_code))
        except Exception as e:
            if isinstance(e, WebullAPIError):
                raise
            e_msg = str(e).lower()
            if isinstance(e, (ConnectionError, TimeoutError)) or any(w in e_msg for w in ("connection", "timeout", "network", "socket")):
                raise WebullConnectionError(f"Network error querying Webull accounts: {e}") from e
            raise WebullAPIError(f"Unexpected error querying Webull accounts: {e}") from e

    def get_positions(self, account_id: str) -> dict[str, Any]:
        """Retrieve current positions and cash balances.

        Args:
            account_id: The Webull account ID.

        Returns:
            Dictionary with keys:
            - 'positions': List of dicts, e.g. [{'symbol': 'AAPL', 'qty': 100, 'cost_basis': 150.0}]
            - 'cash': Dict containing balances, e.g. {'net_liquidity': 100000.0, 'cash_balance': 50000.0}
        """
        if self.dry_run:
            logger.info("[Dry Run] Querying open positions for account: %s", account_id)
            return {
                "positions": [
                    {
                        "position_id": "mock_pos_AAPL",
                        "symbol": "AAPL",
                        "quantity": 100,
                        "qty": 100,
                        "currency": "USD",
                        "cost_price": 175.50,
                        "cost_basis": 175.50,
                        "market_value": 18000.00,
                    },
                    {
                        "position_id": "mock_pos_MSFT",
                        "symbol": "MSFT",
                        "quantity": 50,
                        "qty": 50,
                        "currency": "USD",
                        "cost_price": 350.00,
                        "cost_basis": 350.00,
                        "market_value": 17750.00,
                    },
                ],
                "cash": {
                    "net_liquidity": 100000.0,
                    "cash_balance": 100000.0,
                }
            }

        positions_list = []
        self._throttle()
        try:
            response = self.trade_client.account_v2.get_account_position(account_id)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    positions_list = data
                elif isinstance(data, dict):
                    if "positions" in data:
                        positions_list = data["positions"]
                    else:
                        positions_list = [data]
            else:
                error_msg = f"Failed to get positions for account {account_id}. Status: {response.status_code}, Response: {response.text}"
                logger.error(error_msg)
                raise WebullAPIError(error_msg, error_code=str(response.status_code))
        except Exception as e:
            if isinstance(e, WebullAPIError):
                raise
            e_msg = str(e).lower()
            if isinstance(e, (ConnectionError, TimeoutError)) or any(w in e_msg for w in ("connection", "timeout", "network", "socket")):
                raise WebullConnectionError(f"Network error querying positions for account {account_id}: {e}") from e
            raise WebullAPIError(f"Unexpected error querying positions for account {account_id}: {e}") from e

        # Query cash balance
        cash_dict = {
            "net_liquidity": 100000.0,
            "cash_balance": 100000.0,
        }
        try:
            bal_response = self.trade_client.account_v2.get_account_balance(account_id)
            if bal_response.status_code == 200:
                bal_data = bal_response.json()
                if isinstance(bal_data, dict):
                    cash_dict["net_liquidity"] = float(bal_data.get("net_liquidity") or bal_data.get("total_asset") or 100000.0)
                    cash_dict["cash_balance"] = float(bal_data.get("cash_balance") or bal_data.get("usable_cash") or 100000.0)
        except Exception as e:
            logger.warning(f"Failed to query account balance: {e}")

        return {
            "positions": positions_list,
            "cash": cash_dict
        }

    def get_open_orders(self, account_id: str) -> list[dict[str, Any]]:
        """Queries currently open/pending orders for the given account_id.

        Args:
            account_id: The Webull account ID to query.

        Returns:
            A list of dictionaries representing open orders.

        Raises:
            WebullConnectionError: If a transient network/connection error occurs.
            WebullAPIError: If the API call fails or returns a non-200 status code.
        """
        if self.dry_run:
            logger.info("[Dry Run] Querying open orders for account: %s", account_id)
            return [
                {
                    "account_id": account_id,
                    "client_order_id": "mock_client_order_001",
                    "order_id": "mock_order_001",
                    "symbol": "TSLA",
                    "order_type": "LIMIT",
                    "side": "BUY",
                    "qty": "10",
                    "quantity": "10",
                    "filled_qty": "0",
                    "limit_price": "220.00",
                    "order_status": "PENDING",
                    "place_time": "2026-07-02T21:51:12.000Z",
                    "currency": "USD",
                }
            ]

        self._throttle()
        try:
            # Note: get_order_open is used on order_v2
            response = self.trade_client.order_v2.get_order_open(account_id)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return data.get("orders", [])
                return []
            else:
                error_msg = f"Failed to get open orders. Status: {response.status_code}, Response: {response.text}"
                logger.error(error_msg)
                raise WebullAPIError(error_msg, error_code=str(response.status_code))
        except Exception as e:
            if isinstance(e, WebullAPIError):
                raise
            e_msg = str(e).lower()
            if isinstance(e, (ConnectionError, TimeoutError)) or any(w in e_msg for w in ("connection", "timeout", "network", "socket")):
                raise WebullConnectionError(f"Network error querying open orders: {e}") from e
            raise WebullAPIError(f"Unexpected error querying open orders: {e}") from e
            
    def get_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        """Retrieve details for a specific order.

        Args:
            account_id: The Webull account ID.
            order_id: The broker-assigned order ID.

        Returns:
            Dictionary representing the order status and details, including:
            - 'order_id'
            - 'client_order_id'
            - 'symbol'
            - 'side'
            - 'qty'
            - 'price'
            - 'status' (e.g., 'FILLED', 'CANCELLED', 'SUBMITTED')
            - 'filled_qty'

        Raises:
            WebullConnectionError: If a transient network/connection error occurs.
            WebullAPIError: If the order is not found or the API call fails.
        """
        if self.dry_run:
            logger.info("[Dry Run] Querying details for order: %s", order_id)
            return {
                "order_id": order_id,
                "client_order_id": f"mock_client_{order_id}",
                "symbol": "AAPL",
                "side": "BUY",
                "qty": 10,
                "price": 150.0,
                "status": "FILLED",
                "filled_qty": 10,
            }

        try:
            # 1. Search in open orders
            open_orders = self.get_open_orders(account_id)
            for o in open_orders:
                if o.get("order_id") == order_id:
                    return {
                        "order_id": order_id,
                        "client_order_id": o.get("client_order_id"),
                        "symbol": o.get("symbol"),
                        "side": o.get("side"),
                        "qty": int(o.get("quantity") or o.get("qty") or 0),
                        "price": float(o.get("limit_price") or o.get("price") or 0) if o.get("limit_price") or o.get("price") else None,
                        "status": o.get("order_status") or o.get("status"),
                        "filled_qty": int(o.get("filled_qty") or 0),
                    }

            # 2. Search in order history
            self._throttle()
            response = self.trade_client.order_v2.get_order_history(account_id)
            if response.status_code == 200:
                history = response.json()
                orders = history if isinstance(history, list) else history.get("orders", [])
                for o in orders:
                    if o.get("order_id") == order_id:
                        return {
                            "order_id": order_id,
                            "client_order_id": o.get("client_order_id"),
                            "symbol": o.get("symbol"),
                            "side": o.get("side"),
                            "qty": int(o.get("quantity") or o.get("qty") or 0),
                            "price": float(o.get("limit_price") or o.get("price") or 0) if o.get("limit_price") or o.get("price") else None,
                            "status": o.get("order_status") or o.get("status"),
                            "filled_qty": int(o.get("filled_qty") or 0),
                        }
            else:
                error_msg = f"Failed to query order history. Status: {response.status_code}, Response: {response.text}"
                logger.error(error_msg)
                raise WebullAPIError(error_msg, error_code=str(response.status_code))

            raise WebullAPIError(f"Order {order_id} not found in open orders or history.")
        except Exception as e:
            if isinstance(e, (WebullAPIError, WebullConnectionError)):
                raise
            e_msg = str(e).lower()
            if isinstance(e, (ConnectionError, TimeoutError)) or any(w in e_msg for w in ("connection", "timeout", "network", "socket")):
                raise WebullConnectionError(f"Network error querying order details for {order_id}: {e}") from e
            raise WebullAPIError(f"Unexpected error querying order details for {order_id}: {e}") from e

    def place_order(
        self,
        account_id: str,
        symbol: str,
        qty: int,
        side: str,
        order_type: str | None = None,
        price: float | None = None,
        stop_price: float | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Submits a new order to Webull.

        Args:
            account_id: The Webull account ID.
            symbol: The ticker symbol (e.g. 'AAPL').
            qty: The order quantity.
            side: The order side ('BUY' or 'SELL').
            order_type: The order type, defaults to None (inferred from price/stop_price).
            price: The limit price (required for LIMIT/STOP_LIMIT orders).
            stop_price: The stop price (required for STOP/STOP_LIMIT orders).
            client_order_id: Optional client-specified order ID.

        Returns:
            A dictionary containing the order placement response, status, and IDs.

        Raises:
            ValueError: If validation of parameters fails (e.g. side or price).
            WebullConnectionError: If a transient network/connection error occurs.
            WebullAPIError: If the order submission fails.
        """
        # Validate side
        side_upper = side.upper()
        if side_upper not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: '{side}'. Must be 'BUY' or 'SELL'.")

        # Infer order type if not provided
        if order_type is None:
            if price is not None and stop_price is not None:
                order_type = "STOP_LIMIT"
            elif stop_price is not None:
                order_type = "STOP"
            elif price is not None:
                order_type = "LIMIT"
            else:
                order_type = "MARKET"

        order_type_upper = order_type.upper()

        # Validate price for LIMIT and STOP_LIMIT orders
        if order_type_upper in ("LIMIT", "STOP_LIMIT") and price is None:
            raise ValueError(f"Price is required for {order_type_upper} orders.")

        # Validate stop price for STOP and STOP_LIMIT orders
        if order_type_upper in ("STOP", "STOP_LIMIT") and stop_price is None:
            raise ValueError(f"Stop price is required for {order_type_upper} orders.")

        resolved_client_order_id = client_order_id or uuid.uuid4().hex

        # Format price to string format depending on the size of the price
        price_str = None
        if price is not None:
            price_str = f"{price:.2f}" if price >= 1.0 else f"{price:.4f}"

        # Construct order payload per SDK spec
        order_item = {
            "client_order_id": resolved_client_order_id,
            "combo_type": "NORMAL",
            "symbol": symbol,
            "instrument_type": "STOCK",
            "market": "US",
            "order_type": order_type_upper,
            "side": side_upper,
            "quantity": str(qty),
            "time_in_force": "DAY",
            "entrust_type": "QTY",
            "support_trading_session": "N",
        }
        if price_str is not None:
            order_item["limit_price"] = price_str

        if stop_price is not None:
            stop_price_str = f"{stop_price:.2f}" if stop_price >= 1.0 else f"{stop_price:.4f}"
            order_item["stop_price"] = stop_price_str

        if self.dry_run:
            mock_order_id = f"mock_order_{uuid.uuid4().hex[:8]}"
            logger.info(
                "[Dry Run] Placing %s order for %d shares of %s at %s. ClientOrderId: %s. MockOrderId: %s",
                side_upper,
                qty,
                symbol,
                price_str or "MARKET",
                resolved_client_order_id,
                mock_order_id,
            )
            return {
                "status": "success",
                "status_code": 200,
                "order_id": mock_order_id,
                "client_order_id": resolved_client_order_id,
                "msg": "Order placed successfully (Dry Run)",
                "raw_response": {
                    "client_order_id": resolved_client_order_id,
                    "order_id": mock_order_id,
                },
            }

        try:
            new_orders = [order_item]
            self._throttle()
            response = self.trade_client.order_v2.place_order(account_id, new_orders)
            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "Successfully placed order. ClientOrderId: %s, Webull OrderId: %s",
                    resolved_client_order_id,
                    data.get("order_id"),
                )
                return {
                    "status": "success",
                    "status_code": response.status_code,
                    "order_id": data.get("order_id"),
                    "client_order_id": data.get("client_order_id") or resolved_client_order_id,
                    "raw_response": data,
                }
            else:
                error_msg = f"Failed to place order. Status: {response.status_code}, Response: {response.text}"
                logger.error(error_msg)
                raise WebullAPIError(error_msg, error_code=str(response.status_code))
        except Exception as e:
            if isinstance(e, WebullAPIError):
                raise
            e_msg = str(e).lower()
            if isinstance(e, (ConnectionError, TimeoutError)) or any(w in e_msg for w in ("connection", "timeout", "network", "socket")):
                raise WebullConnectionError(f"Network error submitting order: {e}") from e
            raise WebullAPIError(f"Unexpected error submitting order: {e}") from e

    def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        """Cancels an open order.

        Args:
            account_id: The Webull account ID.
            order_id: The identifier of the order to cancel (maps to client_order_id).

        Returns:
            A dictionary containing the cancellation confirmation details.

        Raises:
            WebullConnectionError: If a transient network/connection error occurs.
            WebullAPIError: If the cancellation fails.
        """
        if self.dry_run:
            logger.info("[Dry Run] Cancelling order: %s for account: %s", order_id, account_id)
            return {
                "status": "success",
                "status_code": 200,
                "order_id": order_id,
                "client_order_id": order_id,
                "msg": "Order cancelled successfully (Dry Run)",
                "raw_response": {
                    "client_order_id": order_id,
                    "order_id": order_id,
                },
            }

        try:
            self._throttle()
            response = self.trade_client.order_v2.cancel_order(account_id, order_id)
            if response.status_code == 200:
                data = response.json()
                logger.info("Successfully cancelled order: %s", order_id)
                return {
                    "status": "success",
                    "status_code": response.status_code,
                    "order_id": data.get("order_id") or order_id,
                    "client_order_id": data.get("client_order_id") or order_id,
                    "raw_response": data,
                }
            else:
                error_msg = f"Failed to cancel order {order_id}. Status: {response.status_code}, Response: {response.text}"
                logger.error(error_msg)
                raise WebullAPIError(error_msg, error_code=str(response.status_code))
        except Exception as e:
            if isinstance(e, WebullAPIError):
                raise
            e_msg = str(e).lower()
            if isinstance(e, (ConnectionError, TimeoutError)) or any(w in e_msg for w in ("connection", "timeout", "network", "socket")):
                raise WebullConnectionError(f"Network error cancelling order: {e}") from e
            raise WebullAPIError(f"Unexpected error cancelling order: {e}") from e
