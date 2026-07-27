"""Historical portfolio valuation, trade-matching FIFO ledger analysis, and stats builder."""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
import numpy as np

from src.data.store import DataStore
from src.utils.helpers import get_trading_days
from src.utils.logger import get_logger
from src.execution.db_manager import DatabaseManager

logger = get_logger(__name__)

class EquityCurveBuilder:
    """Reconstructs EOD portfolio values chronologically from transactions and daily close prices."""

    def __init__(
        self,
        db: DatabaseManager | Path | str,
        data_store: DataStore,
        initial_capital: float = 100000.0,
        estimated_fee_bps: float = 5.0,  # 5 bps slippage + fees
    ) -> None:
        if isinstance(db, DatabaseManager):
            self.db = db
        else:
            self.db = DatabaseManager(db)
        self.store = data_store
        self.initial_capital = initial_capital
        self.fee_bps = estimated_fee_bps

    def load_transactions(self) -> List[Dict[str, Any]]:
        """Query transactions chronologically from the database."""
        txs = []
        try:
            rows = self.db.execute_query(
                """
                SELECT client_order_id, order_id, symbol, side, qty, price, avg_price, timestamp 
                FROM transactions 
                ORDER BY timestamp ASC;
                """
            ).fetchall()
            for r in rows:
                txs.append({
                    "client_order_id": r[0],
                    "order_id": r[1],
                    "symbol": r[2],
                    "side": r[3],
                    "qty": r[4],
                    "price": r[5],
                    "avg_price": r[6],
                    "timestamp": str(r[7]),
                })
        except Exception as e:
            logger.error(f"Failed to query SQL transactions for performance reconstruction: {e}")
            txs = []
        return txs

    def build_curve(self) -> Dict[str, Any]:
        """Process transactions chronologically to calculate EOD net equity and performance metrics."""
        txs = self.load_transactions()
        
        # If no transactions exist, return flat baseline over past 30 days
        if not txs:
            now = dt.date.today()
            dates = [ (now - dt.timedelta(days=i)).isoformat() for i in range(30, -1, -1) ]
            return {
                "dates": dates,
                "equity": [self.initial_capital] * len(dates),
                "stats": {
                    "sharpe_ratio": 0.0,
                    "sortino_ratio": 0.0,
                    "win_rate": 0.0,
                    "profit_factor": 0.0,
                    "max_drawdown": 0.0,
                    "total_trades": 0,
                }
            }

        # Determine timezone-aware range of dates
        first_tx_time = dt.datetime.fromisoformat(txs[0]["timestamp"].replace("Z", "+00:00"))
        start_date = first_tx_time.date()
        end_date = dt.date.today()
        
        # Get all NYSE trading days in the range
        trading_days = get_trading_days(start_date, end_date)
        if not trading_days:
            trading_days = [start_date]

        # Load historical prices for all symbols traded
        traded_symbols = {tx["symbol"] for tx in txs if tx.get("symbol")}
        price_data: Dict[str, pd.DataFrame] = {}
        for sym in traded_symbols:
            try:
                # Detect if it is an options contract
                is_option = len(sym) > 6 and any(c.isdigit() for c in sym)
                if is_option:
                    # Parse option symbol details (e.g. TSLA260717C00392500)
                    underlying, opt_type, strike = sym, "C", 0.0
                    for char_type in ["C", "P"]:
                        if char_type in sym:
                            c_idx = sym.find(char_type)
                            if c_idx >= 6:
                                underlying = sym[:c_idx-6]
                            else:
                                underlying = sym[:c_idx]
                            try:
                                strike = float(sym[c_idx+1:]) / 1000.0
                            except Exception:
                                strike = 0.0
                            opt_type = char_type
                            break
                    
                    # Try loading underlying stock data
                    df_und = self.store.load(underlying)
                    if df_und is not None and not df_und.empty:
                        # Parse expiry date from symbol (YYMMDD)
                        exp_date = dt.datetime.now()
                        if c_idx >= 6:
                            exp_str = sym[c_idx-6:c_idx]
                            if exp_str.isdigit() and len(exp_str) == 6:
                                try:
                                    yy = int(exp_str[:2]) + 2000
                                    mm = int(exp_str[2:4])
                                    dd = int(exp_str[4:])
                                    exp_date = dt.datetime(yy, mm, dd)
                                except Exception:
                                    pass

                        # Calculate rolling volatility for underlying stock returns
                        df_und["returns"] = df_und["close"].pct_change()
                        df_und["vol"] = df_und["returns"].rolling(30).std() * math.sqrt(252.0)
                        df_und["vol"] = df_und["vol"].bfill().ffill().fillna(0.3)

                        df_opt = df_und.copy()
                        
                        # Apply BSM option pricing formula row-by-row
                        from src.strategy.black_scholes import calculate_option_price_and_delta
                        option_prices = []
                        for idx, row in df_und.iterrows():
                            # idx is a timestamp or date
                            try:
                                row_date = idx.date() if hasattr(idx, "date") else idx
                                days = (exp_date.date() - row_date).days
                                T_years = max(0.0, days / 365.0)
                            except Exception:
                                T_years = 0.0
                                
                            val, _ = calculate_option_price_and_delta(
                                S=float(row["close"]),
                                K=strike,
                                T=T_years,
                                r=0.05,
                                sigma=float(row["vol"]),
                                option_type=opt_type
                            )
                            # Floor value at 5% of strike to account for basic residual time value premium
                            option_prices.append(max(0.05 * strike, val))

                        df_opt["close"] = option_prices
                        df_opt.index = pd.to_datetime(df_opt.index).date
                        price_data[sym] = df_opt
                        logger.info(f"Dynamically generated BSM options price curve for {sym} using underlying {underlying} (Strike: {strike})")
                    else:
                        logger.warning(f"Could not load underlying historical data {underlying} for option {sym}. Using purchase price fallback.")
                else:
                    df = self.store.load(sym)
                    if df is not None and not df.empty:
                        df.index = pd.to_datetime(df.index).date
                        price_data[sym] = df
            except Exception as e:
                logger.error(f"Failed to load historical data for {sym}: {e}")

        # Reconstruct day-by-day portfolio
        equity_curve = []
        dates_list = []
        
        # Active positions: symbol -> quantity
        positions: Dict[str, int] = {}
        cash = self.initial_capital
        tx_idx = 0
        n_tx = len(txs)

        # Matched closed trades for stats
        closed_trades_pnl: List[float] = []
        # FIFO queues for each symbol: list of (qty, price)
        fifo_queues: Dict[str, List[tuple[int, float]]] = {sym: [] for sym in traded_symbols}

        for day in trading_days:
            # Process all transactions occurring on this trading day
            day_str = day.isoformat()
            
            while tx_idx < n_tx:
                tx = txs[tx_idx]
                tx_time = dt.datetime.fromisoformat(tx["timestamp"].replace("Z", "+00:00"))
                tx_date = tx_time.date()
                
                if tx_date > day:
                    break
                    
                symbol = tx["symbol"]
                side = tx["side"].upper()
                qty = int(tx.get("qty") or tx.get("filled_qty") or 0)
                price = float(tx.get("avg_price") or tx.get("price") or 0.0)
                
                if qty <= 0 or price <= 0:
                    tx_idx += 1
                    continue

                fee = (qty * price) * (self.fee_bps / 10000.0)
                
                if side == "BUY":
                    cash -= (qty * price) + fee
                    positions[symbol] = positions.get(symbol, 0) + qty
                    fifo_queues[symbol].append((qty, price))
                elif side == "SELL":
                    cash += (qty * price) - fee
                    positions[symbol] = positions.get(symbol, 0) - qty
                    if positions[symbol] <= 0:
                        positions.pop(symbol, None)
                    
                    # FIFO PnL calculation
                    sell_rem = qty
                    while sell_rem > 0 and fifo_queues[symbol]:
                        buy_qty, buy_price = fifo_queues[symbol][0]
                        if buy_qty <= sell_rem:
                            # Full buy block closed
                            realized_pnl = (price - buy_price) * buy_qty - (buy_qty * buy_price + buy_qty * price) * (self.fee_bps / 10000.0)
                            closed_trades_pnl.append(realized_pnl)
                            sell_rem -= buy_qty
                            fifo_queues[symbol].pop(0)
                        else:
                            # Partial buy block closed
                            realized_pnl = (price - buy_price) * sell_rem - (sell_rem * buy_price + sell_rem * price) * (self.fee_bps / 10000.0)
                            closed_trades_pnl.append(realized_pnl)
                            fifo_queues[symbol][0] = (buy_qty - sell_rem, buy_price)
                            sell_rem = 0
                            
                tx_idx += 1

            # Value portfolio at end of day
            pos_value = 0.0
            for sym, qty in positions.items():
                close_price = None
                if sym in price_data:
                    df = price_data[sym]
                    past_prices = df[df.index <= day]
                    if not past_prices.empty:
                        close_price = float(past_prices["close"].iloc[-1])
                
                if close_price is None:
                    # Fallback to last trade fill price
                    close_price = 0.0
                    for t in reversed(txs[:tx_idx]):
                        if t["symbol"] == sym:
                            close_price = float(t.get("avg_price") or t.get("price") or 0.0)
                            break
                            
                pos_value += qty * close_price

            day_equity = cash + pos_value
            equity_curve.append(round(day_equity, 2))
            dates_list.append(day_str)

        # Calculate statistics
        equity_series = pd.Series(equity_curve)
        daily_returns = equity_series.pct_change().dropna()
        
        # Drawdowns
        cum_max = equity_series.cummax()
        drawdowns = (equity_series - cum_max) / cum_max
        max_dd = float(drawdowns.min() * 100.0)  # negative pct

        # Sharpe & Sortino
        sharpe = 0.0
        sortino = 0.0
        if not daily_returns.empty:
            mean_ret = daily_returns.mean()
            std_ret = daily_returns.std(ddof=1)
            if std_ret > 0:
                sharpe = float(np.sqrt(252.0) * mean_ret / std_ret)
                
            downside_ret = daily_returns[daily_returns < 0]
            downside_std = downside_ret.std(ddof=1) if len(downside_ret) > 1 else daily_returns.std(ddof=1)
            if downside_std > 0:
                sortino = float(np.sqrt(252.0) * mean_ret / downside_std)

        # Win Rate & Profit Factor
        total_trades = len(closed_trades_pnl)
        win_rate = 0.0
        profit_factor = 0.0
        if total_trades > 0:
            wins = [p for p in closed_trades_pnl if p > 0]
            losses = [p for p in closed_trades_pnl if p < 0]
            win_rate = (len(wins) / total_trades) * 100.0
            
            gross_profit = sum(wins)
            gross_loss = abs(sum(losses))
            if gross_loss > 0:
                profit_factor = gross_profit / gross_loss
            else:
                profit_factor = float("inf") if gross_profit > 0 else 0.0

        return {
            "dates": dates_list,
            "equity": equity_curve,
            "stats": {
                "sharpe_ratio": round(sharpe, 2),
                "sortino_ratio": round(sortino, 2),
                "win_rate": round(win_rate, 1),
                "profit_factor": round(profit_factor, 2) if not math.isinf(profit_factor) else 999.0,
                "max_drawdown": abs(round(max_dd, 2)),
                "total_trades": total_trades,
            }
        }
