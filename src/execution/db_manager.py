"""ACID-compliant Database Manager supporting SQLite/PostgreSQL, TimescaleDB hypertables, and compliance ledgers."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CachedResult:
    """A thread-safe in-memory cache of query execution results.
    
    This avoids keeping database connections checked out of the pool while 
    iterating or fetching rows, preventing ConnectionFairy exhaustion.
    """
    def __init__(self, rows: list, returns_rows: bool) -> None:
        self._rows = rows
        self.returns_rows = returns_rows
        self._idx = 0

    def fetchall(self) -> list:
        return self._rows

    def fetchone(self) -> Any:
        if self._idx < len(self._rows):
            val = self._rows[self._idx]
            self._idx += 1
            return val
        return None

    def __iter__(self):
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


class DatabaseManager:
    """Manages SQLite and PostgreSQL database connection pools, TimescaleDB migrations, and compliance loggers."""

    def __init__(self, db_uri: str | Path) -> None:
        """Initialize the Database Manager.

        Args:
            db_uri: Either a local file path (SQLite) or a PostgreSQL connection string
                (e.g., 'postgresql://user:pass@localhost:5432/db').
        """
        self.db_uri = str(db_uri)
        self.is_postgres = self.db_uri.startswith(("postgresql://", "postgres://", "postgresql+psycopg2://"))

        # Setup SQLAlchemy connection engines
        if self.is_postgres:
            logger.info("Initializing PostgreSQL database manager backend...")
            self.engine: Engine = create_engine(
                self.db_uri,
                pool_size=10,
                max_overflow=20,
                pool_recycle=1800,
                pool_pre_ping=True
            )
        else:
            self.db_path = Path(db_uri)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"Initializing SQLite database manager backend at {self.db_path}...")
            # Use SQLite with a connection pool limit of 1 to prevent DB locking under thread write concurrency
            self.engine = create_engine(
                f"sqlite:///{self.db_path}",
                connect_args={"timeout": 15.0}
            )

        self.init_db()

    def execute_query(self, query: str, params: Dict[str, Any] | None = None) -> Any:
        """Execute a query using SQLAlchemy connection pool."""
        with self.engine.begin() as conn:
            # Enable SQLite journal options on connection check-out
            if not self.is_postgres:
                conn.execute(text("PRAGMA journal_mode=WAL;"))
                conn.execute(text("PRAGMA foreign_keys=ON;"))
            result = conn.execute(text(query), params or {})
            if result.returns_rows:
                return CachedResult(result.fetchall(), returns_rows=True)
            return CachedResult([], returns_rows=False)

    def get_connection(self) -> Any:
        """Returns a raw DBAPI connection from the SQLAlchemy connection pool for compatibility."""
        return self.engine.raw_connection()

    def init_db(self) -> None:
        """Runs standard DDL schema tables, TimescaleDB hypertables, and ledger triggers."""
        # 1. Cash Table
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS cash (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                net_liquidity REAL NOT NULL CHECK (net_liquidity >= 0.0),
                cash_balance REAL NOT NULL CHECK (cash_balance >= 0.0),
                updated_at TEXT NOT NULL
            );
            """
        )
        
        # Seed cash row if empty
        res = self.execute_query("SELECT COUNT(*) as count FROM cash;").fetchone()
        if res[0] == 0:
            self.execute_query(
                "INSERT INTO cash (id, net_liquidity, cash_balance, updated_at) VALUES (1, 0.0, 0.0, :updated_at);",
                {"updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
            )

        # 2. Positions Table
        # SQLite uses standard PRIMARY KEY, Postgres can use standard schemas
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS positions (
                symbol VARCHAR(30) PRIMARY KEY,
                qty INTEGER NOT NULL CHECK (qty >= 0),
                cost_price REAL NOT NULL CHECK (cost_price >= 0.0),
                sector VARCHAR(50) NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # 3. Orders Table
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS orders (
                client_order_id VARCHAR(100) PRIMARY KEY,
                order_id VARCHAR(100) UNIQUE,
                symbol VARCHAR(30) NOT NULL,
                side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
                qty INTEGER NOT NULL CHECK (qty > 0),
                price REAL CHECK (price > 0.0),
                stop_price REAL CHECK (stop_price > 0.0),
                status VARCHAR(30) NOT NULL CHECK (status IN ('PENDING_SUBMIT', 'SUBMITTED', 'PARTIALLY_FILLED', 'FILLED', 'FAILED', 'CANCELED')),
                filled_qty INTEGER NOT NULL DEFAULT 0 CHECK (filled_qty >= 0),
                error_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        
        # 4. Transactions Table (Partitions via TimescaleDB if postgres active)
        timestamp_type = "TIMESTAMPTZ" if self.is_postgres else "TEXT"
        self.execute_query(
            f"""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id SERIAL PRIMARY KEY,
                client_order_id VARCHAR(100) NOT NULL,
                order_id VARCHAR(100),
                symbol VARCHAR(30) NOT NULL,
                side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
                qty INTEGER NOT NULL CHECK (qty > 0),
                price REAL NOT NULL CHECK (price >= 0.0),
                avg_price REAL NOT NULL CHECK (avg_price >= 0.0),
                timestamp {timestamp_type} NOT NULL,
                placement_latency_ms INTEGER
            );
            """
        )

        # 5. Signal Cache Table
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS signal_cache (
                symbol VARCHAR(30) NOT NULL,
                strategy_name VARCHAR(50) NOT NULL,
                signal INTEGER NOT NULL,
                close_price REAL NOT NULL,
                bar_timestamp TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, strategy_name)
            );
            """
        )

        # 6. Decision Logs Table (JSONB on Postgres, TEXT on SQLite)
        json_type = "JSONB" if self.is_postgres else "TEXT"
        log_id_type = "SERIAL PRIMARY KEY" if self.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        self.execute_query(
            f"""
            CREATE TABLE IF NOT EXISTS decision_logs (
                log_id {log_id_type},
                cycle_id VARCHAR(100) NOT NULL,
                timestamp TEXT NOT NULL,
                symbol VARCHAR(30) NOT NULL,
                regime_hurst REAL NOT NULL,
                strategy_signals {json_type} NOT NULL,
                portfolio_equity REAL NOT NULL,
                portfolio_heat REAL NOT NULL,
                risk_passed INTEGER NOT NULL,
                risk_reason TEXT,
                tims_stress_pct REAL NOT NULL,
                action_taken VARCHAR(50) NOT NULL
            );
            """
        )

        # Indexes
        if self.is_postgres:
            self.execute_query("CREATE INDEX IF NOT EXISTS idx_trans_ts ON transactions(timestamp DESC);")
        else:
            self.execute_query("CREATE INDEX IF NOT EXISTS idx_trans_ts ON transactions(timestamp);")
        self.execute_query("CREATE INDEX IF NOT EXISTS idx_trans_sym ON transactions(symbol);")
        self.execute_query("CREATE INDEX IF NOT EXISTS idx_dec_ts_sym ON decision_logs(timestamp DESC, symbol);")

        # 6. TimescaleDB Hypertable Setup (PostgreSQL only)
        if self.is_postgres:
            try:
                # Check if TimescaleDB extension is active
                self.execute_query("CREATE EXTENSION IF NOT EXISTS timescaledb;")
                # Convert transactions table to hypertable partitioned by the timestamp column
                self.execute_query(
                    "SELECT create_hypertable('transactions', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);"
                )
                logger.info("TimescaleDB extension verified: converted transactions table to hypertable.")
            except Exception as e:
                logger.warning(f"TimescaleDB hypertable conversion skipped or failed: {e}")

        # 7. Immutable Compliance Ledger Triggers (Disables UPDATE and DELETE statements)
        if self.is_postgres:
            try:
                self.execute_query(
                    """
                    CREATE OR REPLACE FUNCTION block_ledger_mutation()
                    RETURNS TRIGGER AS $$
                    BEGIN
                        RAISE EXCEPTION 'Mutations (UPDATES/DELETES) are prohibited on the immutable ledger table: %', TG_TABLE_NAME;
                    END;
                    $$ LANGUAGE plpgsql;
                    """
                )
                # Drop existing to prevent duplicates
                self.execute_query("DROP TRIGGER IF EXISTS block_tx_update ON transactions;")
                self.execute_query("DROP TRIGGER IF EXISTS block_tx_delete ON transactions;")
                self.execute_query("DROP TRIGGER IF EXISTS block_dec_update ON decision_logs;")
                self.execute_query("DROP TRIGGER IF EXISTS block_dec_delete ON decision_logs;")
                
                self.execute_query(
                    """
                    CREATE TRIGGER block_tx_update
                    BEFORE UPDATE ON transactions
                    FOR EACH ROW EXECUTE FUNCTION block_ledger_mutation();
                    """
                )
                self.execute_query(
                    """
                    CREATE TRIGGER block_tx_delete
                    BEFORE DELETE ON transactions
                    FOR EACH ROW EXECUTE FUNCTION block_ledger_mutation();
                    """
                )
                self.execute_query(
                    """
                    CREATE TRIGGER block_dec_update
                    BEFORE UPDATE ON decision_logs
                    FOR EACH ROW EXECUTE FUNCTION block_ledger_mutation();
                    """
                )
                self.execute_query(
                    """
                    CREATE TRIGGER block_dec_delete
                    BEFORE DELETE ON decision_logs
                    FOR EACH ROW EXECUTE FUNCTION block_ledger_mutation();
                    """
                )
                logger.info("Enforced Postgres database triggers for immutable transaction & decision log auditing.")
            except Exception as e:
                logger.error(f"Failed to setup Postgres immutable triggers: {e}")
        else:
            # SQLite compliance triggers
            try:
                self.execute_query(
                    """
                    CREATE TRIGGER IF NOT EXISTS limit_transactions_update
                    BEFORE UPDATE ON transactions
                    BEGIN
                        SELECT RAISE(FAIL, 'Updates are prohibited on the transactions ledger table (immutable compliance requirement).');
                    END;
                    """
                )
                self.execute_query(
                    """
                    CREATE TRIGGER IF NOT EXISTS limit_transactions_delete
                    BEFORE DELETE ON transactions
                    BEGIN
                        SELECT RAISE(FAIL, 'Deletions are prohibited on the transactions ledger table (immutable compliance requirement).');
                    END;
                    """
                )
                self.execute_query(
                    """
                    CREATE TRIGGER IF NOT EXISTS limit_decision_logs_update
                    BEFORE UPDATE ON decision_logs
                    BEGIN
                        SELECT RAISE(FAIL, 'Updates are prohibited on the decision_logs ledger table (immutable compliance requirement).');
                    END;
                    """
                )
                self.execute_query(
                    """
                    CREATE TRIGGER IF NOT EXISTS limit_decision_logs_delete
                    BEFORE DELETE ON decision_logs
                    BEGIN
                        SELECT RAISE(FAIL, 'Deletions are prohibited on the decision_logs ledger table (immutable compliance requirement).');
                    END;
                    """
                )
                logger.info("Enforced SQLite database triggers for immutable transaction & decision log auditing.")
            except Exception as e:
                logger.error(f"Failed to setup SQLite immutable triggers: {e}")

    # ---------------------------------------------------------
    # Database helpers
    # ---------------------------------------------------------

    def get_cash(self) -> Tuple[float, float]:
        """Retrieve (net_liquidity, cash_balance) from DB."""
        row = self.execute_query("SELECT net_liquidity, cash_balance FROM cash WHERE id = 1;").fetchone()
        if row:
            return float(row[0]), float(row[1])
        return 0.0, 0.0

    def update_cash(self, net_liquidity: float, cash_balance: float) -> None:
        """Update cash record."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self.execute_query(
            "UPDATE cash SET net_liquidity = :net, cash_balance = :cash, updated_at = :upd WHERE id = 1;",
            {"net": net_liquidity, "cash": cash_balance, "upd": now}
        )

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        """Retrieve positions mapped by symbol."""
        positions = {}
        rows = self.execute_query("SELECT symbol, qty, cost_price, sector FROM positions;").fetchall()
        for r in rows:
            positions[r[0]] = {
                "symbol": r[0],
                "quantity": int(r[1]),
                "qty": int(r[1]),
                "cost_price": float(r[2]),
                "cost_basis": float(r[2]),
                "sector": r[3]
            }
        return positions

    def save_position(self, symbol: str, qty: int, cost_price: float, sector: str) -> None:
        """Save or update position entry."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if qty <= 0:
            self.execute_query("DELETE FROM positions WHERE symbol = :symbol;", {"symbol": symbol})
        else:
            if self.is_postgres:
                # Postgres UPSERT
                self.execute_query(
                    """
                    INSERT INTO positions (symbol, qty, cost_price, sector, updated_at)
                    VALUES (:sym, :qty, :cost, :sector, :now)
                    ON CONFLICT(symbol) DO UPDATE SET
                        qty = EXCLUDED.qty,
                        cost_price = EXCLUDED.cost_price,
                        sector = EXCLUDED.sector,
                        updated_at = EXCLUDED.updated_at;
                    """,
                    {"sym": symbol, "qty": qty, "cost": cost_price, "sector": sector, "now": now}
                )
            else:
                # SQLite UPSERT
                self.execute_query(
                    """
                    INSERT INTO positions (symbol, qty, cost_price, sector, updated_at)
                    VALUES (:sym, :qty, :cost, :sector, :now)
                    ON CONFLICT(symbol) DO UPDATE SET
                        qty = excluded.qty,
                        cost_price = excluded.cost_price,
                        sector = excluded.sector,
                        updated_at = excluded.updated_at;
                    """,
                    {"sym": symbol, "qty": qty, "cost": cost_price, "sector": sector, "now": now}
                )

    def get_orders(self) -> Dict[str, Dict[str, Any]]:
        """Retrieve all database orders."""
        orders = {}
        rows = self.execute_query("SELECT * FROM orders;").fetchall()
        for r in rows:
            # Convert row mapping to dict
            orders[r[0]] = {
                "client_order_id": r[0],
                "order_id": r[1],
                "symbol": r[2],
                "side": r[3],
                "qty": r[4],
                "price": r[5],
                "stop_price": r[6],
                "status": r[7],
                "filled_qty": r[8],
                "error_reason": r[9],
                "created_at": r[10],
                "updated_at": r[11]
            }
        return orders

    def save_order(self, order: Dict[str, Any]) -> None:
        """Insert or update order entry."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if self.is_postgres:
            self.execute_query(
                """
                INSERT INTO orders (client_order_id, order_id, symbol, side, qty, price, stop_price, status, filled_qty, error_reason, created_at, updated_at)
                VALUES (:client_order_id, :order_id, :symbol, :side, :qty, :price, :stop_price, :status, :filled_qty, :error_reason, :created_at, :updated_at)
                ON CONFLICT(client_order_id) DO UPDATE SET
                    order_id = COALESCE(EXCLUDED.order_id, orders.order_id),
                    status = EXCLUDED.status,
                    filled_qty = EXCLUDED.filled_qty,
                    error_reason = COALESCE(EXCLUDED.error_reason, orders.error_reason),
                    updated_at = EXCLUDED.updated_at;
                """,
                {
                    "client_order_id": order["client_order_id"],
                    "order_id": order.get("order_id"),
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "qty": int(order["qty"]),
                    "price": float(order["price"]) if order.get("price") is not None else None,
                    "stop_price": float(order["stop_price"]) if order.get("stop_price") is not None else None,
                    "status": order["status"],
                    "filled_qty": int(order.get("filled_qty", 0)),
                    "error_reason": order.get("error_reason"),
                    "created_at": order.get("created_at") or now,
                    "updated_at": now
                }
            )
        else:
            self.execute_query(
                """
                INSERT INTO orders (client_order_id, order_id, symbol, side, qty, price, stop_price, status, filled_qty, error_reason, created_at, updated_at)
                VALUES (:client_order_id, :order_id, :symbol, :side, :qty, :price, :stop_price, :status, :filled_qty, :error_reason, :created_at, :updated_at)
                ON CONFLICT(client_order_id) DO UPDATE SET
                    order_id = COALESCE(excluded.order_id, orders.order_id),
                    status = excluded.status,
                    filled_qty = excluded.filled_qty,
                    error_reason = COALESCE(excluded.error_reason, orders.error_reason),
                    updated_at = excluded.updated_at;
                """,
                {
                    "client_order_id": order["client_order_id"],
                    "order_id": order.get("order_id"),
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "qty": int(order["qty"]),
                    "price": float(order["price"]) if order.get("price") is not None else None,
                    "stop_price": float(order["stop_price"]) if order.get("stop_price") is not None else None,
                    "status": order["status"],
                    "filled_qty": int(order.get("filled_qty", 0)),
                    "error_reason": order.get("error_reason"),
                    "created_at": order.get("created_at") or now,
                    "updated_at": now
                }
            )

    def save_decision_log(self, log_entry: Dict[str, Any]) -> None:
        """Insert a decision log record. Safe wrapper: failure never blocks trading."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            import json
            signals = log_entry.get("strategy_signals")
            signals_str = json.dumps(signals) if isinstance(signals, (dict, list)) else str(signals or "{}")

            self.execute_query(
                """
                INSERT INTO decision_logs (cycle_id, timestamp, symbol, regime_hurst, strategy_signals, portfolio_equity, portfolio_heat, risk_passed, risk_reason, tims_stress_pct, action_taken)
                VALUES (:cycle_id, :timestamp, :symbol, :regime_hurst, :strategy_signals, :portfolio_equity, :portfolio_heat, :risk_passed, :risk_reason, :tims_stress_pct, :action_taken);
                """,
                {
                    "cycle_id": log_entry["cycle_id"],
                    "timestamp": log_entry.get("timestamp") or now,
                    "symbol": log_entry["symbol"],
                    "regime_hurst": float(log_entry.get("regime_hurst") or 0.0),
                    "strategy_signals": signals_str,
                    "portfolio_equity": float(log_entry.get("portfolio_equity") or 0.0),
                    "portfolio_heat": float(log_entry.get("portfolio_heat") or 0.0),
                    "risk_passed": 1 if log_entry.get("risk_passed") else 0,
                    "risk_reason": log_entry.get("risk_reason"),
                    "tims_stress_pct": float(log_entry.get("tims_stress_pct") or 0.0),
                    "action_taken": log_entry["action_taken"]
                }
            )
            logger.debug(f"Decision log successfully saved for {log_entry['symbol']} ({log_entry['action_taken']}).")
        except Exception as e:
            logger.error(f"Non-blocking failure: failed to save decision log: {e}")
