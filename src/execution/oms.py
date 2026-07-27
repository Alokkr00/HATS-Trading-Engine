"""Order Management System (OMS) for managing trade execution, state, and recovery.

This module provides the OrderManager class, which manages execution states,
writes and maintains the local OMS state file, interacts with WebullClient,
handles rate-limiting and connection errors with exponential backoff, logs
transactions to Parquet/JSON, and implements crash recovery on startup.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

from src.execution.alpaca_client import AlpacaClient, AlpacaAPIError as WebullAPIError, AlpacaConnectionError as WebullConnectionError
from src.execution.db_manager import DatabaseManager
from src.execution.sector_resolver import SectorResolver
from src.utils.logger import get_logger
from src.utils.notifier import send_telegram_alert

logger = get_logger(__name__)

T = TypeVar("T")


class OrderManager:
    """Order Management System (OMS) for managing order execution, state, and recovery."""

    def __init__(
        self,
        client: WebullClient,
        account_id: str,
        log_dir: str = "data/execution",
    ) -> None:
        """Initialize the OrderManager.

        Args:
            client: WebullClient wrapper instance.
            account_id: Webull target account ID.
            log_dir: Directory path for saving execution state and transaction logs.
        """
        self.client = client
        self.account_id = account_id
        self.log_dir = Path(log_dir)
        self.state_file = self.log_dir / "oms_state.json"
        
        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Database Manager
        self.db = DatabaseManager(self.log_dir / "trading_bot.db")

        # Initialize Sector Resolver
        self.sector_resolver = SectorResolver(self.log_dir / "sector_cache.json")
        
        # State will be populated during recover_state()
        self.state: dict[str, Any] = {}
        
        logger.info(f"Initializing OMS for account {self.account_id}. State file: {self.state_file}")
        self.recover_state()

    def _load_state(self) -> None:
        """Load state, preferring oms_state.json for backwards-compatibility/tests, or SQLite database."""
        # 1. Check if oms_state.json exists (this matches unit test setup)
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
                # Seed SQLite DB with the loaded JSON state to keep them in sync
                self._save_state_to_db()
                return
            except Exception as e:
                logger.error(f"Failed to load state from JSON file: {e}")

        # 2. Fallback to loading from SQLite DB
        try:
            net_liq, cash_bal = self.db.get_cash()
            self.state = {
                "orders": self.db.get_orders(),
                "portfolio": {
                    "positions": self.db.get_positions(),
                    "cash": {
                        "net_liquidity": net_liq,
                        "cash_balance": cash_bal,
                    },
                    "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            }
            # Save JSON file to keep it in sync
            self._save_state_to_json()
        except Exception as e:
            logger.error(f"Failed to load state from SQLite: {e}")
            # Fallback default state
            self.state = {
                "orders": {},
                "portfolio": {
                    "positions": {},
                    "cash": {
                        "net_liquidity": 100000.0,
                        "cash_balance": 100000.0,
                    },
                    "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
            }
            self._save_state()

    def _save_state_to_db(self) -> None:
        """Save the in-memory state dictionary to the SQLite database."""
        try:
            portfolio = self.state.get("portfolio", {})
            cash = portfolio.get("cash", {})
            net_liq = float(cash.get("net_liquidity", 100000.0))
            cash_bal = float(cash.get("cash_balance", 100000.0))
            self.db.update_cash(net_liq, cash_bal)

            positions = portfolio.get("positions", {})
            # Read existing DB positions to delete missing ones
            existing_db_positions = self.db.get_positions()
            for sym, pos in positions.items():
                qty = int(pos.get("quantity") or pos.get("qty") or 0)
                cost = float(pos.get("cost_price") or pos.get("cost_basis") or 0.0)
                sector = pos.get("sector", "Unknown")
                self.db.save_position(sym, qty, cost, sector)
                
            for sym in existing_db_positions:
                if sym not in positions:
                    self.db.save_position(sym, 0, 0.0, "")

            orders = self.state.get("orders", {})
            # Valid status values the SQLite schema accepts
            _VALID_STATUSES = {"PENDING_SUBMIT", "SUBMITTED", "PARTIALLY_FILLED", "FILLED", "FAILED", "CANCELED"}
            # Map Alpaca enum strings (from stale state files) to valid OMS statuses
            _ALPACA_STATUS_MAP = {
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
                "orderstatus.rejected":         "FAILED",
                "orderstatus.suspended":        "FAILED",
                "orderstatus.calculated":       "FILLED",
            }
            for client_order_id, order in orders.items():
                raw_status = str(order.get("status", "SUBMITTED"))
                if raw_status not in _VALID_STATUSES:
                    order["status"] = _ALPACA_STATUS_MAP.get(raw_status.lower(), "SUBMITTED")
                self.db.save_order(order)
        except Exception as e:
            logger.error(f"Failed to save state to SQLite database: {e}")

    def _save_state_to_json(self) -> None:
        """Save the current state to the state file using an atomic write."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = self.state_file.with_suffix(".json.tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=4)
            os.replace(tmp_file, self.state_file)
        except Exception as e:
            logger.error(f"Failed to save OMS state to JSON: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    def _save_state(self) -> None:
        """Save state to both SQLite and JSON file to maintain dual-write sync."""
        self._save_state_to_db()
        self._save_state_to_json()

    def _execute_with_retry(
        self,
        func: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute a function with exponential backoff for transient connection errors.

        Args:
            func: The function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            The result of func.

        Raises:
            WebullConnectionError: If the error persists after all retries.
            WebullAPIError: Propagated without retries as it represents non-transient API issues.
            Exception: Any other unexpected exception.
        """
        max_retries = 5
        base_delay = 1.0  # seconds
        max_delay = 30.0

        for attempt in range(1, max_retries + 1):
            try:
                return func(*args, **kwargs)
            except (WebullConnectionError, ConnectionError, TimeoutError) as e:
                if attempt == max_retries:
                    logger.critical(
                        f"Transient connection error persisted after {max_retries} attempts: {e}"
                    )
                    raise WebullConnectionError(
                        f"Transient connection error persisted after {max_retries} attempts"
                    ) from e

                # Exponential backoff with jitter
                delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5), max_delay)
                logger.warning(
                    f"Transient connection error: {e}. Retrying attempt {attempt}/{max_retries} in {delay:.2f}s..."
                )
                time.sleep(delay)
            except WebullAPIError as e:
                # Do not retry on non-transient API exceptions (margin violation, invalid order size, etc.)
                # But rate limits are API errors; if they are rate limit errors, we could also log and fail
                logger.debug(f"Non-transient WebullAPIError encountered: {e}")
                raise

    def place_trade(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str | None:
        """Validate, log intent, and place a trade with Webull.

        Args:
            symbol: Ticker symbol (e.g. 'AAPL').
            side: 'BUY' or 'SELL'.
            qty: Quantity to trade.
            price: Limit price. None for Market order.
            stop_price: Stop price for stop or stop-limit order.

        Returns:
            The broker-assigned order ID (or client_order_id) if submitted, otherwise None.

        Raises:
            ValueError: If parameters fail validation.
        """
        # Validate inputs
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Symbol must be a non-empty string.")
        
        side_upper = side.upper()
        if side_upper not in ("BUY", "SELL"):
            raise ValueError("Side must be either 'BUY' or 'SELL'.")
        
        if qty <= 0:
            raise ValueError("Quantity must be a positive integer.")
        
        if price is not None and price <= 0:
            raise ValueError("Price must be greater than zero if provided.")
            
        if stop_price is not None and stop_price <= 0:
            raise ValueError("Stop price must be greater than zero if provided.")

        client_order_id = f"oms_{uuid.uuid4().hex}"
        
        # 1. Log trade intent (PENDING_SUBMIT)
        order_entry = {
            "client_order_id": client_order_id,
            "order_id": None,
            "symbol": symbol,
            "side": side_upper,
            "qty": qty,
            "price": price,
            "stop_price": stop_price,
            "status": "PENDING_SUBMIT",
            "filled_qty": 0,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        self.state["orders"][client_order_id] = order_entry
        self._save_state()
        
        logger.info(f"Trade intent logged: {client_order_id} ({side_upper} {qty} {symbol})")

        # 2. Call place_order with retries for transient errors
        try:
            start_time = time.perf_counter()
            response = self._execute_with_retry(
                self.client.place_order,
                account_id=self.account_id,
                symbol=symbol,
                side=side_upper,
                qty=qty,
                price=price,
                stop_price=stop_price,
                client_order_id=client_order_id,
            )
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            order_id = response.get("order_id")
            if not order_id:
                raise WebullAPIError("Broker response did not contain 'order_id'")
                
            # Update state on success
            order_entry["order_id"] = order_id
            order_entry["status"] = "SUBMITTED"
            order_entry["placement_latency_ms"] = latency_ms
            order_entry["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self._save_state()
            
            logger.info(f"Order submitted successfully: {client_order_id} -> broker order_id: {order_id} in {latency_ms}ms")
            return order_id

        except WebullAPIError as api_err:
            # API failure (margin violation, invalid order size, rate limit etc.)
            logger.critical(
                f"API Error placing trade for {symbol} ({side_upper} {qty}): {api_err}. Marking order as FAILED.",
                exc_info=True,
            )
            order_entry["status"] = "FAILED"
            order_entry["error_reason"] = str(api_err)
            order_entry["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self._save_state()
            return None

        except Exception as e:
            # Other errors (e.g. connection error that persisted after retries)
            # We keep it as PENDING_SUBMIT so it can be recovered/validated on reboot
            logger.critical(
                f"Failed to submit order {client_order_id} due to persistent errors: {e}. Order state left as PENDING_SUBMIT.",
                exc_info=True,
            )
            raise

    def _append_to_json_list(self, file_path: Path, item: dict[str, Any]) -> None:
        """Appends a dictionary to a JSON file representing a list in O(1) time by seeking to the end."""
        if not file_path.exists() or file_path.stat().st_size < 2:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([item], f, indent=4)
            return

        try:
            with open(file_path, "rb+") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                pos = size - 1
                while pos > 0:
                    f.seek(pos)
                    char = f.read(1)
                    if char == b"]":
                        f.seek(pos)
                        formatted_item = json.dumps(item, indent=4)
                        indented = "\n    ".join(formatted_item.split("\n"))
                        f.write(f",\n    {indented}\n]".encode("utf-8"))
                        f.truncate()
                        return
                    pos -= 1
                
                # Fallback to standard write if malformed
                f.seek(0)
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    # Attempt to recover by appending missing closing bracket
                    try:
                        f.seek(0)
                        content = f.read().decode("utf-8").strip()
                        if not content.endswith("]"):
                            content += "]"
                        data = json.loads(content)
                    except Exception:
                        # If completely corrupt, start a new list
                        data = []
                data.append(item)
                f.seek(0)
                f.write(json.dumps(data, indent=4).encode("utf-8"))
                f.truncate()
        except Exception as e:
            logger.error(f"Error performing O(1) JSON seek append to {file_path}: {e}")

    def _log_transaction(self, order: dict[str, Any]) -> None:
        """Log filled transaction to SQLite database, JSON, JSONL, and Parquet logs."""
        qty = int(order.get("qty") or order.get("filled_qty") or 0)
        price = float(order.get("price") or 0.0)
        avg_price = float(order.get("avg_price") or price or 0.0)
        now_str = dt.datetime.now(dt.timezone.utc).isoformat()
        
        transaction = {
            "client_order_id": order.get("client_order_id"),
            "order_id": order.get("order_id"),
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "qty": qty,
            "price": price,
            "avg_price": avg_price,
            "timestamp": now_str,
            "placement_latency_ms": order.get("placement_latency_ms"),
        }

        # 0. Database transaction ledger logging
        try:
            self.db.execute_query(
                """
                INSERT INTO transactions (client_order_id, order_id, symbol, side, qty, price, avg_price, timestamp, placement_latency_ms)
                VALUES (:client_order_id, :order_id, :symbol, :side, :qty, :price, :avg_price, :timestamp, :placement_latency_ms);
                """,
                transaction
            )
            logger.info(f"Transaction logged to DB: {order.get('symbol')} ({order.get('side')} {qty}) with latency {transaction['placement_latency_ms']}ms")
        except Exception as e:
            logger.error(f"Error logging transaction to DB: {e}")

        # Send Telegram alert on trade fill
        send_telegram_alert(
            f"📈 **H.A.T.S Execution Fill**:\n"
            f"• **Side**: {order.get('side')}\n"
            f"• **Ticker**: {order.get('symbol')}\n"
            f"• **Shares**: {qty}\n"
            f"• **Price**: ${avg_price:.2f}"
        )

        # Broadcast live event to dashboard uvicorn server via HTTP trigger
        try:
            import urllib.request
            import json
            import base64
            
            # Encode basic auth header
            username = os.getenv("DASHBOARD_USERNAME", "admin")
            password = os.getenv("DASHBOARD_PASSWORD", "hats_secure_pass")
            auth_str = f"{username}:{password}"
            auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
            
            req = urllib.request.Request(
                "http://127.0.0.1:8000/api/broadcast",
                data=json.dumps({"type": "transaction_logged", "data": transaction}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Basic {auth_b64}"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=1) as response:
                response.read()
        except Exception:
            pass

        # Legacy transaction mapping with filled_qty (expected by unit tests)
        legacy_tx = transaction.copy()
        legacy_tx["filled_qty"] = order.get("filled_qty", qty)

        # 1. JSON Log Append (O(1) Seek Append)
        json_log_path = self.log_dir / "transactions.json"
        self._append_to_json_list(json_log_path, legacy_tx)

        # 2. JSONL Log Append (O(1) append-only line)
        jsonl_log_path = self.log_dir / "transactions.jsonl"
        try:
            with open(jsonl_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(legacy_tx) + "\n")
        except Exception as e:
            logger.error(f"Error writing transaction log JSONL: {e}")

        # 3. Parquet Log Append using PyArrow (O(1) write_to_dataset directory append)
        parquet_log_path = self.log_dir / "transactions.parquet"
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
            table = pa.Table.from_pydict({k: [v] for k, v in legacy_tx.items()})
            pq.write_to_dataset(table, root_path=str(parquet_log_path))
            logger.info(f"Transaction logged to Parquet: {parquet_log_path}")
        except Exception as e:
            logger.error(f"Error writing transaction log Parquet: {e}")

    def sync_orders(self) -> None:
        """Fetch open orders from Webull and update local tracking states."""
        try:
            open_orders = self._execute_with_retry(self.client.get_open_orders, self.account_id)
        except Exception as e:
            logger.error(f"Failed to fetch open orders during sync: {e}")
            return

        # Map open orders by order_id or client_order_id
        open_orders_by_id = {}
        for o in open_orders:
            if o.get("order_id"):
                open_orders_by_id[o["order_id"]] = o
            if o.get("client_order_id"):
                open_orders_by_id[o["client_order_id"]] = o

        state_changed = False
        active_statuses = {"PENDING_SUBMIT", "SUBMITTED", "PARTIALLY_FILLED"}

        for client_order_id, local_order in list(self.state["orders"].items()):
            if local_order.get("status") not in active_statuses:
                continue

            order_id = local_order.get("order_id")

            # Check if broker reports this order as open/active
            broker_order = open_orders_by_id.get(order_id) or open_orders_by_id.get(client_order_id)

            if broker_order:
                # Order is still active on Webull
                old_status = local_order.get("status")
                new_status = broker_order.get("status", "SUBMITTED")
                filled_qty = broker_order.get("filled_qty", 0)

                if old_status != new_status or local_order.get("filled_qty") != filled_qty:
                    local_order["status"] = new_status
                    local_order["filled_qty"] = filled_qty
                    local_order["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                    state_changed = True
                    logger.info(
                        f"Updated order {client_order_id} state: {old_status} -> {new_status} (Filled: {filled_qty})"
                    )

                    if new_status == "FILLED" and not local_order.get("transaction_logged"):
                        local_order["transaction_logged"] = True
                        self._log_transaction(local_order)
                        self.sync_portfolio()
            else:
                # Order is no longer in open orders list. Query final status.
                if order_id:
                    try:
                        order_detail = self._execute_with_retry(
                            self.client.get_order, self.account_id, order_id
                        )
                        final_status = order_detail.get("status", "FAILED")
                        filled_qty = order_detail.get("filled_qty", 0)

                        local_order["status"] = final_status
                        local_order["filled_qty"] = filled_qty
                        local_order["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                        state_changed = True
                        logger.info(
                            f"Resolved order {client_order_id} ({order_id}) final status: {final_status} (Filled: {filled_qty})"
                        )

                        if final_status in ("FILLED", "CANCELED") and filled_qty > 0 and not local_order.get("transaction_logged"):
                            local_order["transaction_logged"] = True
                            self._log_transaction(local_order)
                            self.sync_portfolio()
                    except WebullAPIError as api_err:
                        logger.error(
                            f"API Error fetching final status for order {order_id}: {api_err}. Marking as FAILED."
                        )
                        local_order["status"] = "FAILED"
                        local_order["error_reason"] = str(api_err)
                        local_order["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                        state_changed = True
                    except Exception as e:
                        logger.error(f"Failed to query status for order {order_id}: {e}")
                else:
                    # Pending order with no broker order_id that is not open was likely never placed
                    logger.warning(
                        f"Pending order {client_order_id} has no order ID and is not open. Marking as FAILED."
                    )
                    local_order["status"] = "FAILED"
                    local_order["error_reason"] = "Order not found in open orders and had no broker order ID."
                    local_order["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                    state_changed = True

        if state_changed:
            self._save_state()

    def sync_portfolio(self) -> dict[str, Any]:
        """Query Webull for positions and cash and update local tracking state.

        Returns:
            The synchronized portfolio state dictionary containing positions and cash.
        """
        try:
            portfolio_data = self._execute_with_retry(self.client.get_positions, self.account_id)
            
            positions = portfolio_data.get("positions", [])
            cash = portfolio_data.get("cash", {})

            # Enrich positions with sector mapping dynamically for risk sizer checks
            for pos in positions:
                symbol = pos.get("symbol")
                if symbol:
                    pos["sector"] = self.sector_resolver.resolve(symbol)

            self.state["portfolio"] = {
                "positions": {pos["symbol"]: pos for pos in positions},
                "cash": cash,
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            self._save_state()
            logger.info("Portfolio state successfully synchronized with Webull.")
            return self.state["portfolio"]
        except Exception as e:
            logger.error(f"Failed to sync portfolio state: {e}")
            raise

    def recover_state(self) -> None:
        """On initialization, check outstanding state and reconcile it with Webull.

        Resolves orders left in PENDING_SUBMIT, SUBMITTED, or PARTIALLY_FILLED states
        to guarantee no duplicates and ensure local tracking is consistent.
        """
        self._load_state()

        active_statuses = {"PENDING_SUBMIT", "SUBMITTED", "PARTIALLY_FILLED"}
        pending_recovery = [
            (client_order_id, ord_data)
            for client_order_id, ord_data in self.state["orders"].items()
            if ord_data.get("status") in active_statuses
        ]

        if not pending_recovery:
            logger.info("No active or pending orders requiring recovery on reboot.")
            return

        logger.info(
            f"Found {len(pending_recovery)} pending or active orders to reconcile on startup."
        )

        try:
            open_orders = self._execute_with_retry(self.client.get_open_orders, self.account_id)
        except Exception as e:
            logger.error(
                f"Failed to fetch open orders during recovery: {e}. State recovery deferred."
            )
            return

        # Map broker open orders by order_id and client_order_id
        open_orders_by_id = {}
        for o in open_orders:
            if o.get("order_id"):
                open_orders_by_id[o["order_id"]] = o
            if o.get("client_order_id"):
                open_orders_by_id[o["client_order_id"]] = o

        state_changed = False

        for client_order_id, local_order in pending_recovery:
            order_id = local_order.get("order_id")
            status = local_order.get("status")

            # Check if broker has it in the active/open list
            broker_order = open_orders_by_id.get(order_id) or open_orders_by_id.get(client_order_id)

            if broker_order:
                # Order exists as open on broker
                broker_order_id = broker_order.get("order_id")
                if order_id != broker_order_id:
                    local_order["order_id"] = broker_order_id
                    logger.info(
                        f"Linked recovered PENDING_SUBMIT order {client_order_id} to broker order_id {broker_order_id}."
                    )

                new_status = broker_order.get("status", "SUBMITTED")
                filled_qty = broker_order.get("filled_qty", 0)

                local_order["status"] = new_status
                local_order["filled_qty"] = filled_qty
                local_order["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                state_changed = True

                logger.info(
                    f"Recovered order {client_order_id} in active state: {status} -> {new_status} (Filled: {filled_qty})"
                )
            else:
                # Order not active on Webull. Reconcile final status.
                if order_id:
                    try:
                        order_detail = self._execute_with_retry(
                            self.client.get_order, self.account_id, order_id
                        )
                        final_status = order_detail.get("status", "FAILED")
                        filled_qty = order_detail.get("filled_qty", 0)

                        local_order["status"] = final_status
                        local_order["filled_qty"] = filled_qty
                        local_order["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                        state_changed = True

                        logger.info(
                            f"Recovered order {client_order_id} ({order_id}) final status: {final_status} (Filled: {filled_qty})"
                        )
                        if final_status == "FILLED":
                            self._log_transaction(local_order)

                    except WebullAPIError as api_err:
                        logger.error(
                            f"API Error recovering order {order_id}: {api_err}. Marking as FAILED."
                        )
                        local_order["status"] = "FAILED"
                        local_order["error_reason"] = f"API error during recovery: {api_err}"
                        local_order["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                        state_changed = True
                    except Exception as e:
                        logger.error(
                            f"Failed to query final status for order {order_id} during recovery: {e}. Keeping state as {status}."
                        )
                else:
                    # Order was PENDING_SUBMIT, has no broker order_id, and is not in open orders.
                    # Safest to mark FAILED to prevent duplicate placement.
                    logger.warning(
                        f"Recovered PENDING_SUBMIT order {client_order_id} was not open and has no order ID. Marking as FAILED."
                    )
                    local_order["status"] = "FAILED"
                    local_order["error_reason"] = (
                        "System rebooted before order ID was received; order not found in open orders."
                    )
                    local_order["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                    state_changed = True

        if state_changed:
            self._save_state()
            try:
                self.sync_portfolio()
            except Exception as e:
                logger.error(f"Failed to sync portfolio after recovering states: {e}")
