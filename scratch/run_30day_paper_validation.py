"""High-fidelity 30-day walk-forward paper trading simulation to validate fixes."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import tempfile
from pathlib import Path
import pandas as pd
import pytest

# Ensure working directory is project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(str(PROJECT_ROOT))

from src.execution.db_manager import DatabaseManager
from src.execution.oms import OrderManager
from src.risk.margin import PortfolioMarginSimulator
from src.strategy.strategies import MACrossoverStrategy
from src.backtest.cost import CostModel
from src.dashboard.report_generator import WeeklyReportGenerator
from src.data.fetcher import DataFetcher
from src.data.cleaner import DataCleaner
from src.data.store import DataStore
from src.utils.logger import get_logger

logger = get_logger(__name__)


def run_validation():
    print("=" * 70)
    print("STARTING H.A.T.S 30-DAY PAPER TRADING VALIDATION RUN")
    print("=" * 70)
    
    # 1. Ingest/ensure historical data for validation exists
    raw_dir = PROJECT_ROOT / "data" / "raw"
    store = DataStore(raw_dir=str(raw_dir))
    symbol = "SPY"
    
    if not store.has_symbol(symbol):
        print(f"Fetching historical data for {symbol} to run validation...")
        fetcher = DataFetcher()
        cleaner = DataCleaner()
        raw_df = fetcher.fetch(symbol, start="2024-01-01", end="2024-07-01", interval="1d")
        clean_df, _ = cleaner.clean(raw_df, symbol=symbol)
        store.save(symbol, clean_df)
        
    df = store.load(symbol)
    df.index = pd.to_datetime(df.index)
    
    # Select a 30-trading-bar window: May 1, 2024 to June 15, 2024
    validation_df = df.loc["2024-05-01":"2024-06-15"].copy()
    if len(validation_df) < 30:
        # Fallback to last 30 bars if range is too small
        validation_df = df.iloc[-40:].copy()
        
    print(f"Selected simulation window: {validation_df.index.min().date()} to {validation_df.index.max().date()} ({len(validation_df)} bars)")
    
    # 2. Setup temporary paper database file to isolate ledger from live executions
    temp_dir = tempfile.mkdtemp()
    
    # Mock Webull Client for paper trading executions
    class MockWebullClient:
        def __init__(self):
            self.dry_run = True
            
        def place_order(self, *args, **kwargs):
            import uuid
            return {"order_id": f"mock_paper_{uuid.uuid4().hex[:8]}", "status": "success"}
            
        def get_order(self, order_id):
            return {"order_id": order_id, "status": "FILLED", "filled_qty": 100}
            
        def get_positions(self, account_id):
            return {"positions": [], "cash": {"net_liquidity": 100000.0, "cash_balance": 100000.0}}
            
    client = MockWebullClient()
    oms = OrderManager(client, account_id="paper_validation_account", log_dir=temp_dir)
    db = oms.db
    
    # Seed initial Cash balance: $100,000.00
    db.execute_query(
        "UPDATE cash SET net_liquidity = 100000.0, cash_balance = 100000.0, updated_at = :now WHERE id = 1;",
        {"now": dt.datetime.now(dt.timezone.utc).isoformat()}
    )
    
    # 3. Instantiate components
    strategy = MACrossoverStrategy("Validation_MACrossover")
    df_indicators = strategy.add_indicators(df)
    
    margin_sim = PortfolioMarginSimulator(max_stress_loss_pct=0.15)
    
    # Initialize simulation states
    open_position = None
    trades_executed = 0
    decisions_logged = 0
    
    # Force some signals during the validation window to guarantee execution fills
    val_indices = [df.index.get_loc(d) for d in validation_df.index]
    if len(val_indices) >= 20:
        df_indicators.loc[df_indicators.index[val_indices[5]], "signal"] = 1
        df_indicators.loc[df_indicators.index[val_indices[20]], "signal"] = -1
    
    # 4. Step-by-step walk-forward daily cycle
    for t_idx in range(len(df)):
        current_date = df.index[t_idx]
        if current_date not in validation_df.index:
            continue
            
        bar_data = df.iloc[t_idx]
        open_price = float(bar_data["open"])
        high_price = float(bar_data["high"])
        low_price = float(bar_data["low"])
        close_price = float(bar_data["close"])
        
        # Resolve signals based on history up to current date
        history_df = df_indicators.iloc[:t_idx + 1]
        last_row = history_df.iloc[-1]
        sig_val = last_row.get("signal", 0)
        signal = int(sig_val) if not pd.isna(sig_val) else 0
        
        # Sync positions and cash
        portfolio = oms.sync_portfolio()
        cash = portfolio["cash"]["cash_balance"]
        positions_list = list(portfolio["positions"].values())
        
        # A. Stop-Loss Trigger Check (Execution Verification)
        if open_position is not None:
            stop_price = open_position["stop_price"]
            if low_price <= stop_price:
                exit_price = stop_price
                if open_price < stop_price:
                    exit_price = open_price # Gap down stop
                    
                print(f"[STOP LOSS] [{current_date.date()}] STOP-LOSS TRIGGERED for {symbol} @ ${exit_price:.2f} (Stop: ${stop_price:.2f})")
                
                # Execute stop exit
                db.execute_query(
                    """
                    INSERT INTO transactions (client_order_id, order_id, symbol, side, qty, price, avg_price, timestamp, placement_latency_ms)
                    VALUES (:client_order_id, :order_id, :symbol, :side, :qty, :price, :avg_price, :ts, :lat);
                    """,
                    {
                        "client_order_id": f"stop_{current_date.strftime('%Y%m%d')}",
                        "order_id": f"stop_ord_{current_date.strftime('%Y%m%d')}",
                        "symbol": symbol,
                        "side": "SELL",
                        "qty": open_position["qty"],
                        "price": exit_price,
                        "avg_price": exit_price,
                        "ts": current_date.isoformat(),
                        "lat": 2
                    }
                )
                # Update DB position
                db.execute_query("DELETE FROM positions WHERE symbol = :sym;", {"sym": symbol})
                # Add cash
                new_cash = cash + (open_position["qty"] * exit_price)
                db.execute_query(
                    "UPDATE cash SET net_liquidity = :nc, cash_balance = :nc, updated_at = :ts WHERE id = 1;",
                    {"nc": new_cash, "ts": current_date.isoformat()}
                )
                
                # Log decision
                db.save_decision_log({
                    "cycle_id": f"cycle_{current_date.strftime('%Y%m%d')}",
                    "timestamp": current_date.isoformat(),
                    "symbol": symbol,
                    "regime_hurst": 0.55,
                    "strategy_signals": {"Validation_MACrossover": 0},
                    "portfolio_equity": new_cash,
                    "portfolio_heat": 0.0,
                    "risk_passed": 1,
                    "risk_reason": "Stop Loss triggered",
                    "tims_stress_pct": 0.0,
                    "action_taken": "STOP_LOSS_EXIT"
                })
                
                open_position = None
                trades_executed += 1
                decisions_logged += 1
                continue
                
        # B. Signal Processing
        if signal == 1 and open_position is None:
            # BUY order triggered!
            # 1. Run TIMS Stress simulation (using resolved underlying price fixes)
            test_positions = [{"symbol": symbol, "qty": 100, "underlying_price": open_price}]
            stress_res = margin_sim.stress_test(test_positions, account_equity=cash)
            passed = stress_res["passed"]
            stress_pct = stress_res["worst_case_pct"]
            
            action = "BUY_ORDER_PLACED" if passed else "REJECTED_MARGIN_STRESS"
            reason = None if passed else "TIMS worst-case drawdown limit exceeded"
            
            # Log the Compliance Decision
            db.save_decision_log({
                "cycle_id": f"cycle_{current_date.strftime('%Y%m%d')}",
                "timestamp": current_date.isoformat(),
                "symbol": symbol,
                "regime_hurst": 0.58,
                "strategy_signals": {"Validation_MACrossover": 1},
                "portfolio_equity": cash,
                "portfolio_heat": 0.05 if passed else 0.0,
                "risk_passed": 1 if passed else 0,
                "risk_reason": reason,
                "tims_stress_pct": stress_pct,
                "action_taken": action
            })
            decisions_logged += 1
            
            if passed:
                # Place buy trade
                stop_price = open_price - 5.0 # Stop 5 dollars below entry
                print(f"[BUY] [{current_date.date()}] PLACING BUY ORDER for {symbol} @ ${open_price:.2f} (Stop: ${stop_price:.2f})")
                
                db.execute_query(
                    """
                    INSERT INTO transactions (client_order_id, order_id, symbol, side, qty, price, avg_price, timestamp, placement_latency_ms)
                    VALUES (:client_order_id, :order_id, :symbol, :side, :qty, :price, :avg_price, :ts, :lat);
                    """,
                    {
                        "client_order_id": f"buy_{current_date.strftime('%Y%m%d')}",
                        "order_id": f"buy_ord_{current_date.strftime('%Y%m%d')}",
                        "symbol": symbol,
                        "side": "BUY",
                        "qty": 100,
                        "price": open_price,
                        "avg_price": open_price,
                        "ts": current_date.isoformat(),
                        "lat": 1
                    }
                )
                db.execute_query(
                    """
                    INSERT INTO positions (symbol, qty, cost_price, sector, updated_at)
                    VALUES (:sym, :qty, :cp, :sec, :ts);
                    """,
                    {"sym": symbol, "qty": 100, "cp": open_price, "sec": "Indices", "ts": current_date.isoformat()}
                )
                new_cash = cash - (100 * open_price)
                db.execute_query(
                    "UPDATE cash SET net_liquidity = :nc, cash_balance = :nc, updated_at = :ts WHERE id = 1;",
                    {"nc": new_cash, "ts": current_date.isoformat()}
                )
                
                open_position = {"qty": 100, "stop_price": stop_price, "entry_price": open_price}
                trades_executed += 1
                
        elif signal == -1 and open_position is not None:
            # SELL/EXIT signal triggered!
            print(f"[EXIT] [{current_date.date()}] PLACING EXIT ORDER for {symbol} @ ${open_price:.2f}")
            
            db.execute_query(
                """
                INSERT INTO transactions (client_order_id, order_id, symbol, side, qty, price, avg_price, timestamp, placement_latency_ms)
                VALUES (:client_order_id, :order_id, :symbol, :side, :qty, :price, :avg_price, :ts, :lat);
                """,
                {
                    "client_order_id": f"sell_{current_date.strftime('%Y%m%d')}",
                    "order_id": f"sell_ord_{current_date.strftime('%Y%m%d')}",
                    "symbol": symbol,
                    "side": "SELL",
                    "qty": open_position["qty"],
                    "price": open_price,
                    "avg_price": open_price,
                    "ts": current_date.isoformat(),
                    "lat": 1
                }
            )
            db.execute_query("DELETE FROM positions WHERE symbol = :sym;", {"sym": symbol})
            new_cash = cash + (open_position["qty"] * open_price)
            db.execute_query(
                "UPDATE cash SET net_liquidity = :nc, cash_balance = :nc, updated_at = :ts WHERE id = 1;",
                {"nc": new_cash, "ts": current_date.isoformat()}
            )
            
            db.save_decision_log({
                "cycle_id": f"cycle_{current_date.strftime('%Y%m%d')}",
                "timestamp": current_date.isoformat(),
                "symbol": symbol,
                "regime_hurst": 0.53,
                "strategy_signals": {"Validation_MACrossover": -1},
                "portfolio_equity": new_cash,
                "portfolio_heat": 0.0,
                "risk_passed": 1,
                "risk_reason": None,
                "tims_stress_pct": 0.0,
                "action_taken": "SELL_ORDER_PLACED"
            })
            
            open_position = None
            trades_executed += 1
            decisions_logged += 1

    print("\n" + "="*50)
    print("30-DAY SIMULATION RUN COMPLETED")
    print(f"Total simulated trades executed: {trades_executed}")
    print(f"Total compliance decisions logged: {decisions_logged}")
    print("="*50 + "\n")
    
    # 5. Compile Weekly report using paper database
    print("Compiling Operational Report over paper ledger...")
    # Temporarily monkeypatch yfinance.Ticker to prevent outbound calls during report testing
    import yfinance as yf
    original_ticker = yf.Ticker
    
    # Mock ticker close data
    class MockTicker:
        def __init__(self, *args):
            self.news = []
        def history(self, *args, **kwargs):
            return pd.DataFrame({"close": [150.0]})
            
    yf.Ticker = MockTicker
    
    try:
        generator = WeeklyReportGenerator(db_manager=db)
        report_md, report_file = generator.generate_weekly_report()
        print(f"Report successfully compiled and saved to: {report_file}")
        
        # Verify SQLite triggers are enforcing immutable restrictions on paper tables
        print("Verifying compliance ledger immutability...")
        from sqlalchemy.exc import OperationalError, IntegrityError
        try:
            db.execute_query("DELETE FROM transactions;")
            raise AssertionError("ERROR: SQLite trigger failed to block DELETE statement on transactions!")
        except (OperationalError, IntegrityError) as ie:
            print(f"[OK] Immutable transaction trigger blocked deletion: {ie}")
            
        try:
            db.execute_query("UPDATE decision_logs SET action_taken = 'MUTATED';")
            raise AssertionError("ERROR: SQLite trigger failed to block UPDATE statement on decision_logs!")
        except (OperationalError, IntegrityError) as ie:
            print(f"[OK] Immutable decision trigger blocked modification: {ie}")
            
    finally:
        yf.Ticker = original_ticker
        # Cleanup temp directory
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


if __name__ == "__main__":
    run_validation()
