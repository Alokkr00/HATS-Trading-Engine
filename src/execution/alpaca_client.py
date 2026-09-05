"""Alpaca paper/live trading client wrapper.

The OMS calls three methods:
    client.place_order(account_id, symbol, side, qty, price, stop_price, client_order_id)
    client.get_order(order_id)
    client.get_positions(account_id)

This wrapper translates those calls to the alpaca-py SDK and normalises
the responses to the same dict format the OMS already understands.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class AlpacaError(Exception):
    """Base exception for AlpacaClient errors."""


class AlpacaAuthError(AlpacaError):
    """Raised on authentication failures (invalid, expired, or revoked API key/secret)."""


class AlpacaConnectionError(AlpacaError):
    """Raised on transient network failures or rate limits."""


class AlpacaAPIError(AlpacaError):
    """Raised on API-level rejections (insufficient buying power, invalid qty, etc.)."""

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class AlpacaClient:
    """Wraps the alpaca-py TradingClient to match the OMS broker interface.

    Environment variables read from .env:
        APCA_API_KEY_ID     – Alpaca paper API key
        APCA_API_SECRET_KEY – Alpaca paper API secret
        ALPACA_PAPER        – '1' (default) for paper, '0' for live

    Set ALPACA_PAPER=0 only when you are ready for real money.
    """

    @staticmethod
    def _classify_exception(exc: Exception, context: str) -> AlpacaError:
        """Classify raw Alpaca SDK / network exceptions into precise OMS domain exceptions."""
        msg = str(exc).lower()
        if "unauthorized" in msg or "forbidden" in msg or "invalid key" in msg or "401" in msg or "403" in msg:
            logger.critical(f"Alpaca authentication failed during {context}: {exc}")
            return AlpacaAuthError(
                f"Alpaca API Authentication Failed: Invalid, expired, or revoked API Key/Secret. "
                f"Please verify APCA_API_KEY_ID and APCA_API_SECRET_KEY at https://app.alpaca.markets (Raw error: {exc})"
            )
        if "rate limit" in msg or "429" in msg or "too many requests" in msg:
            logger.warning(f"Alpaca rate limited during {context}: {exc}")
            return AlpacaConnectionError(f"Alpaca rate limit encountered: {exc}")
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or "connection" in msg or "timeout" in msg or "502" in msg or "503" in msg or "504" in msg:
            logger.warning(f"Alpaca network connection failed during {context}: {exc}")
            return AlpacaConnectionError(f"Network connection error during {context}: {exc}")
        
        return AlpacaAPIError(f"Alpaca API error during {context}: {exc}")

    def __init__(self) -> None:
        load_dotenv()

        api_key = os.getenv("APCA_API_KEY_ID", "")
        secret_key = os.getenv("APCA_API_SECRET_KEY", "")
        paper = os.getenv("ALPACA_PAPER", "1").lower() not in ("0", "false", "no")

        if not api_key or not secret_key:
            raise AlpacaError(
                "Alpaca credentials missing. Set APCA_API_KEY_ID and "
                "APCA_API_SECRET_KEY in your .env file."
            )

        try:
            from alpaca.trading.client import TradingClient
        except ImportError as exc:
            raise AlpacaError(
                "alpaca-py is not installed. Run: pip install alpaca-py"
            ) from exc

        self._client = TradingClient(api_key, secret_key, paper=paper)
        self.paper = paper
        mode = "PAPER" if paper else "LIVE"
        logger.info(f"AlpacaClient initialised in {mode} mode.")

    @classmethod
    def is_configured(cls) -> bool:
        """Check whether Alpaca API credentials are present in the environment."""
        load_dotenv()
        key = os.getenv("APCA_API_KEY_ID", "").strip()
        secret = os.getenv("APCA_API_SECRET_KEY", "").strip()
        return bool(key and secret and not key.startswith("mock_"))

    def get_account(self) -> dict[str, Any]:
        """Return account financial details and status from Alpaca."""
        try:
            acc = self._client.get_account()
            return {
                "id": str(acc.id),
                "status": str(acc.status),
                "currency": str(acc.currency),
                "cash": float(acc.cash or 0),
                "equity": float(acc.equity or 0),
                "buying_power": float(acc.buying_power or 0),
                "portfolio_value": float(acc.portfolio_value or 0),
                "pattern_day_trader": bool(getattr(acc, "pattern_day_trader", False)),
                "trading_blocked": bool(getattr(acc, "trading_blocked", False)),
            }
        except Exception as exc:
            logger.error(f"Failed to fetch Alpaca account: {exc}")
            raise self._classify_exception(exc, "fetching account") from exc

    # ------------------------------------------------------------------
    # Status normalisation
    # Alpaca returns enum strings like "OrderStatus.NEW", "OrderStatus.FILLED".
    # The OMS SQLite schema only accepts a fixed set of internal status values.
    # ------------------------------------------------------------------

    _STATUS_MAP: dict[str, str] = {
        "orderstatus.new":              "SUBMITTED",
        "orderstatus.accepted":         "SUBMITTED",
        "orderstatus.pending_new":      "SUBMITTED",
        "orderstatus.partially_filled": "PARTIALLY_FILLED",
        "orderstatus.filled":           "FILLED",
        "orderstatus.done_for_day":     "FILLED",
        "orderstatus.canceled":         "CANCELED",
        "orderstatus.expired":          "CANCELED",
        "orderstatus.replaced":         "CANCELED",
        "orderstatus.pending_cancel":   "SUBMITTED",
        "orderstatus.held":             "SUBMITTED",
        "orderstatus.accepted_for_bidding": "SUBMITTED",
        "orderstatus.stopped":          "SUBMITTED",
        "orderstatus.rejected":         "FAILED",
        "orderstatus.suspended":        "FAILED",
        "orderstatus.calculated":       "FILLED",
    }

    def _normalize_status(self, alpaca_status: str) -> str:
        """Translate an Alpaca OrderStatus string to an OMS-compatible status string."""
        return self._STATUS_MAP.get(alpaca_status.lower(), "SUBMITTED")

    # ------------------------------------------------------------------
    # OMS interface methods
    # ------------------------------------------------------------------

    def place_order(
        self,
        account_id: str,  # kept for interface compatibility, unused by Alpaca
        symbol: str,
        side: str,
        qty: int,
        price: float | None = None,
        stop_price: float | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a market, limit, or stop-limit order to Alpaca.

        Returns a normalised dict: {"order_id": str, "status": str}
        """
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
        from alpaca.trading.requests import (
            LimitOrderRequest,
            MarketOrderRequest,
            StopOrderRequest,
            StopLossRequest,
        )

        side_enum = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        tif = TimeInForce.DAY  # Day orders are safest for equities

        try:
            # If we are BUYING with a stop-loss, we use OTO order class
            if side_enum == OrderSide.BUY and stop_price is not None:
                stop_loss_req = StopLossRequest(stop_price=round(stop_price, 2))
                if price is not None:
                    # Limit entry with stop-loss protection
                    req = LimitOrderRequest(
                        symbol=symbol,
                        qty=qty,
                        side=side_enum,
                        time_in_force=tif,
                        limit_price=round(price, 2),
                        client_order_id=client_order_id,
                        order_class=OrderClass.OTO,
                        stop_loss=stop_loss_req,
                    )
                else:
                    # Market entry with stop-loss protection
                    req = MarketOrderRequest(
                        symbol=symbol,
                        qty=qty,
                        side=side_enum,
                        time_in_force=tif,
                        client_order_id=client_order_id,
                        order_class=OrderClass.OTO,
                        stop_loss=stop_loss_req,
                    )
            elif stop_price is not None:
                # Stop (market) order — e.g. standalone stop-loss exit
                req = StopOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=side_enum,
                    time_in_force=tif,
                    stop_price=round(stop_price, 2),
                    client_order_id=client_order_id,
                )
            elif price is not None:
                # Limit order
                req = LimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=side_enum,
                    time_in_force=tif,
                    limit_price=round(price, 2),
                    client_order_id=client_order_id,
                )
            else:
                # Market order
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=side_enum,
                    time_in_force=TimeInForce.DAY,
                    client_order_id=client_order_id,
                )

            order = self._client.submit_order(order_data=req)
            logger.info(
                f"Alpaca order submitted: {order.id} ({side.upper()} {qty} {symbol})"
            )
            return {"order_id": str(order.id), "status": self._normalize_status(str(order.status))}

        except Exception as exc:
            msg = str(exc)
            logger.error(f"Alpaca order submission failed for {symbol}: {msg}")
            raise self._classify_exception(exc, f"submitting {side} order for {symbol}") from exc

    def get_order(self, account_id_or_order_id: str, order_id: str | None = None) -> dict[str, Any]:
        """Return the current status of an order.

        Accepts two calling conventions:
            get_order(order_id)                  — direct call
            get_order(account_id, order_id)      — OMS calling convention (account_id ignored)

        Returns a normalised dict:
            {"order_id": str, "status": str, "filled_qty": int}
        """
        # Handle both calling conventions
        actual_order_id = order_id if order_id is not None else account_id_or_order_id
        try:
            from alpaca.trading.requests import GetOrderByIdRequest
            req = GetOrderByIdRequest(nested=False)
            order = self._client.get_order_by_id(actual_order_id, filter=req)
            filled_qty = int(float(order.filled_qty or 0))
            return {
                "order_id": str(order.id),
                "status": self._normalize_status(str(order.status)),
                "filled_qty": filled_qty,
            }
        except Exception as exc:
            logger.error(f"Failed to fetch order {actual_order_id}: {exc}")
            raise self._classify_exception(exc, f"fetching order {actual_order_id}") from exc

    def get_positions(self, account_id: str) -> dict[str, Any]:
        """Return current account positions and cash in OMS-expected format.

        Returns:
            {
                "positions": [{"symbol": str, "qty": int, "cost_price": float}, ...],
                "cash": {"cash_balance": float, "net_liquidity": float}
            }
        """
        try:
            raw_positions = self._client.get_all_positions()
            account = self._client.get_account()

            positions = []
            for pos in raw_positions:
                positions.append(
                    {
                        "symbol": pos.symbol,
                        "qty": int(float(pos.qty)),
                        "cost_price": float(pos.avg_entry_price or 0),
                        "market_value": float(pos.market_value or 0),
                        "unrealized_pl": float(pos.unrealized_pl or 0),
                        "current_price": float(pos.current_price or 0),
                    }
                )

            cash_balance = float(account.cash)
            net_liquidity = float(account.equity)

            return {
                "positions": positions,
                "cash": {
                    "cash_balance": cash_balance,
                    "net_liquidity": net_liquidity,
                },
            }
        except Exception as exc:
            logger.error(f"Failed to sync Alpaca portfolio: {exc}")
            raise self._classify_exception(exc, "syncing portfolio positions and cash") from exc

    def get_open_orders(self, account_id: str) -> list[dict[str, Any]]:
        """Return all open (not yet filled/cancelled) orders from Alpaca.

        Returns a list of normalised dicts:
            [{"order_id": str, "client_order_id": str, "status": str, "filled_qty": int}, ...]
        """
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus

            req = GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=100)
            orders = self._client.get_orders(filter=req)

            result = []
            for o in orders:
                result.append({
                    "order_id": str(o.id),
                    "client_order_id": str(o.client_order_id) if o.client_order_id else None,
                    "status": self._normalize_status(str(o.status)),
                    "filled_qty": int(float(o.filled_qty or 0)),
                    "symbol": o.symbol,
                    "side": str(o.side),
                    "qty": int(float(o.qty or 0)),
                })
            return result
        except Exception as exc:
            logger.error(f"Failed to fetch open orders from Alpaca: {exc}")
            raise self._classify_exception(exc, "fetching open orders") from exc
