"""High-fidelity event-driven backtesting engine.

Simulates daily bar-by-bar trade execution with transaction costs and
supports out-of-sample walk-forward validation splits.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategy.base import BaseStrategy
from src.backtest.cost import CostModel, spread_multiplier
from src.utils import get_logger

logger = get_logger(__name__)


def compute_performance_metrics(equity_curve: pd.Series, trades: list) -> dict:
    """Calculate standard quantitative performance metrics from equity and trade history.

    Args:
        equity_curve: Series of daily portfolio equity values.
        trades: List of trade dictionaries.

    Returns:
        A dictionary containing CAGR, Sharpe Ratio, Sortino Ratio, Max Drawdown,
        Max Drawdown Duration (calendar days), Win Rate, and Profit Factor.
    """
    if len(equity_curve) == 0:
        return {
            "cagr": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_duration_days": 0,
            "max_drawdown_duration_bars": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_trades": 0,
        }

    initial_equity = float(equity_curve.iloc[0])
    final_equity = float(equity_curve.iloc[-1])

    # CAGR
    n_days = len(equity_curve)
    if initial_equity > 0 and final_equity > 0 and n_days > 0:
        cagr = (final_equity / initial_equity) ** (252.0 / n_days) - 1.0
    else:
        cagr = -1.0 if final_equity <= 0 else 0.0

    # Daily Returns
    daily_returns = equity_curve.pct_change().fillna(0.0)

    # Sharpe Ratio (Assuming Risk-Free Rate = 0)
    mean_ret = daily_returns.mean()
    std_ret = daily_returns.std(ddof=1)
    if std_ret > 0:
        sharpe = float(np.sqrt(252.0) * mean_ret / std_ret)
    else:
        sharpe = 0.0

    # Sortino Ratio (Assuming Risk-Free Rate = 0)
    downside_returns = daily_returns.copy()
    downside_returns[downside_returns > 0] = 0.0
    downside_std = downside_returns.std(ddof=1)
    if downside_std > 0:
        sortino = float(np.sqrt(252.0) * mean_ret / downside_std)
    else:
        sortino = 0.0

    # Max Drawdown & Duration (Calendar & Trading Days)
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    max_dd = float(drawdown.min())  # Negative value, e.g. -0.15 for 15%

    # Duration in calendar days
    peak_date = equity_curve.index[0]
    max_dd_duration_days = 0
    for date, eq in equity_curve.items():
        if eq >= equity_curve.loc[peak_date]:
            peak_date = date
        else:
            duration_days = (date - peak_date).days
            if duration_days > max_dd_duration_days:
                max_dd_duration_days = duration_days

    # Duration in trading days (bars)
    peak_idx = 0
    max_dd_duration_bars = 0
    for idx, eq in enumerate(equity_curve):
        if eq >= equity_curve.iloc[peak_idx]:
            peak_idx = idx
        else:
            duration_bars = idx - peak_idx
            if duration_bars > max_dd_duration_bars:
                max_dd_duration_bars = duration_bars

    # Trade Metrics
    total_trades = len(trades)
    winning_trades = [t for t in trades if t.get("pnl", 0.0) > 0.0]
    losing_trades = [t for t in trades if t.get("pnl", 0.0) < 0.0]

    win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0

    gross_profits = sum(t.get("pnl", 0.0) for t in winning_trades)
    gross_losses = sum(abs(t.get("pnl", 0.0)) for t in losing_trades)

    if gross_losses > 0:
        profit_factor = gross_profits / gross_losses
    else:
        profit_factor = float("inf") if gross_profits > 0 else 0.0

    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "max_drawdown_duration_days": max_dd_duration_days,
        "max_drawdown_duration_bars": max_dd_duration_bars,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_trades": total_trades,
    }


class BacktestEngine:
    """Simulates trading of a strategy under realistic costs and constraints."""

    def __init__(
        self,
        strategy: BaseStrategy,
        capital: float = 100000.0,
        cost_model: CostModel | None = None,
    ) -> None:
        """Initialize the BacktestEngine.

        Args:
            strategy: Concrete subclass of BaseStrategy.
            capital: Starting account equity.
            cost_model: Transaction CostModel (if None, no transaction costs are applied).
        """
        self.strategy = strategy
        self.capital = capital
        self.cost_model = cost_model or CostModel(0.0, 0.0, 0.0, 0.0)

    def run_vectorized(self, df: pd.DataFrame) -> dict:
        """Run a vectorized matrix backtest for fast parameter validation."""
        # 1. Generate Strategy Signals
        df_signals = self.strategy.generate_signals(df).copy()
        
        # 2. Reconstruct position series
        pos = 0.0
        positions = []
        for sig in df_signals["signal"]:
            if sig == 1:
                pos = 1.0
            elif sig == -1:
                pos = 0.0
            positions.append(pos)
        
        df_signals["position"] = pd.Series(positions, index=df_signals.index).shift(1).fillna(0.0)
        
        # Calculate returns
        df_signals["asset_returns"] = df_signals["close"].pct_change().fillna(0.0)
        df_signals["strategy_returns"] = df_signals["asset_returns"] * df_signals["position"]
        
        # Apply 5 bps cost per trade trigger
        df_signals["trades"] = df_signals["position"].diff().abs().fillna(0.0)
        df_signals["strategy_returns"] -= df_signals["trades"] * 0.0005
        
        # Cumulative product starting with capital
        equity_curve = self.capital * (1.0 + df_signals["strategy_returns"]).cumprod()
        
        # Reconstruct trades list
        trades = []
        in_pos = False
        entry_price = 0.0
        entry_date = None
        for idx, row in df_signals.iterrows():
            pos_val = row["position"]
            if pos_val > 0 and not in_pos:
                in_pos = True
                entry_price = float(row["open"])
                entry_date = idx
            elif pos_val == 0 and in_pos:
                in_pos = False
                exit_price = float(row["close"])
                pnl = exit_price - entry_price
                pnl_pct = pnl / entry_price
                trades.append({
                    "symbol": df.attrs.get("symbol", "UNKNOWN"),
                    "entry_time": entry_date,
                    "entry_price": entry_price,
                    "exit_time": idx,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "qty": int(self.capital * 0.1 / entry_price),
                })
                
        metrics = compute_performance_metrics(equity_curve, trades)
        
        return {
            "equity_curve": equity_curve,
            "trades": trades,
            "metrics": metrics
        }

    def run(self, df: pd.DataFrame, simulation_start_idx: int | None = None) -> dict:
        """Simulate trading bar-by-bar on a single stock OHLCV DataFrame.

        Args:
            df: Input OHLCV DataFrame with timezone-aware DatetimeIndex.
            simulation_start_idx: Optional index to start trade simulation. If specified,
                prior bars are used only for indicator warm-up.

        Returns:
            A dict containing:
                - 'equity_curve': pd.Series of daily equity value.
                - 'trades': list of trade records (dict).
                - 'metrics': dict of performance metrics.
        """
        logger.info("[%s] Running backtest with capital: %.2f", self.strategy.name, self.capital)

        # 1. Generate Strategy Signals
        df_signals = self.strategy.generate_signals(df)

        # Extract Series for speed
        opens = df_signals["open"]
        closes = df_signals["close"]
        signals = df_signals["signal"]
        dates = df_signals.index
        n_bars = len(df_signals)

        vix_col = "vix"
        has_vix = vix_col in df_signals.columns

        atr_col = "atr_14"
        has_atr = atr_col in df_signals.columns

        symbol = df.attrs.get("symbol", "UNKNOWN")

        # Initialize Simulation State
        cash = self.capital
        position_shares = 0
        in_position = False
        active_trade = None

        equity_values = []
        trades = []

        # Position Sizer
        from src.strategy.portfolio import PositionSizer
        sizer = PositionSizer()

        start_idx = simulation_start_idx if simulation_start_idx is not None else 0

        # Bar-by-bar Daily Loop
        for t in range(n_bars):
            # A. Execute any pending trades at the Open of the day t
            if t > 0 and t >= start_idx:
                prev_signal = signals.iloc[t - 1]

                if prev_signal == 1 and not in_position:
                    # Buy shares at open of bar t
                    entry_price = float(opens.iloc[t])
                    entry_time = dates[t]

                    # Stop price calculated at index t-1 (where signal was generated)
                    stop_price = self.strategy.get_initial_stop_price(df_signals, t - 1, entry_price)
                    atr_val = float(df_signals[atr_col].iloc[t - 1]) if has_atr and not pd.isna(df_signals[atr_col].iloc[t - 1]) else None

                    # Size the position based on the previous close's equity
                    prev_equity = equity_values[-1] if equity_values else self.capital
                    size_dict = sizer.calculate_size(
                        account_equity=prev_equity,
                        entry_price=entry_price,
                        stop_price=stop_price,
                        atr=atr_val,
                    )
                    shares = size_dict["shares"]

                    # Apply 1% ADV Cap (Market Impact constraint)
                    if "volume" in df_signals.columns and t > 20:
                        adv_20 = df_signals["volume"].iloc[t-20:t].mean()
                        if adv_20 > 0:
                            max_shares = int(0.01 * adv_20)
                            if shares > max_shares:
                                logger.info(
                                    "[%s] Trade size capped by 1%% ADV limit: %d shares -> %d shares (ADV: %d)",
                                    symbol, shares, max_shares, int(adv_20)
                                )
                                shares = max_shares

                    if shares > 0:
                        # Transaction costs on entry
                        entry_cost = 0.0
                        if self.cost_model is not None:
                            vix_val = float(df_signals[vix_col].iloc[t]) if has_vix and not pd.isna(df_signals[vix_col].iloc[t]) else None
                            mult = spread_multiplier(vix_val) if vix_val is not None else 1.0
                            
                            # Almgren-Chriss market impact model
                            impact_bps = 0.0
                            if "volume" in df_signals.columns and t > 20:
                                adv_20 = df_signals["volume"].iloc[t-20:t].mean()
                                if adv_20 > 0:
                                    returns = df_signals["close"].iloc[max(0, t-20):t].pct_change().dropna()
                                    daily_vol = returns.std() if len(returns) > 0 else 0.01
                                    impact_fraction = 0.5 * daily_vol * np.sqrt(shares / adv_20)
                                    impact_bps = impact_fraction * 10000.0

                            entry_bps = self.cost_model.spread_bps * mult + self.cost_model.slippage_bps + impact_bps
                            entry_cost = (shares * entry_price) * entry_bps / 10000.0

                        cash = cash - (shares * entry_price) - entry_cost
                        position_shares = shares
                        in_position = True

                        active_trade = {
                            "entry_time": entry_time,
                            "entry_price": entry_price,
                            "shares": shares,
                            "entry_cost": entry_cost,
                            "stop_price": stop_price,
                        }

                elif prev_signal == -1 and in_position and active_trade is not None:
                    # Sell all shares at open of bar t
                    exit_price = float(opens.iloc[t])
                    exit_time = dates[t]
                    shares = position_shares

                    # Transaction costs on exit
                    exit_cost = 0.0
                    if self.cost_model is not None:
                        vix_val = float(df_signals[vix_col].iloc[t]) if has_vix and not pd.isna(df_signals[vix_col].iloc[t]) else None
                        mult = spread_multiplier(vix_val) if vix_val is not None else 1.0
                        
                        # Almgren-Chriss market impact model on exit
                        impact_bps = 0.0
                        if "volume" in df_signals.columns and t > 20:
                            adv_20 = df_signals["volume"].iloc[t-20:t].mean()
                            if adv_20 > 0:
                                returns = df_signals["close"].iloc[max(0, t-20):t].pct_change().dropna()
                                daily_vol = returns.std() if len(returns) > 0 else 0.01
                                impact_fraction = 0.5 * daily_vol * np.sqrt(shares / adv_20)
                                impact_bps = impact_fraction * 10000.0

                        exit_bps = self.cost_model.spread_bps * mult + self.cost_model.slippage_bps + impact_bps
                        exit_cost = (
                            (shares * exit_price) * exit_bps / 10000.0
                            + (shares * exit_price) * self.cost_model.sec_fee_per_million / 1_000_000.0
                            + shares * self.cost_model.finra_per_share
                        )

                    cash = cash + (shares * exit_price) - exit_cost
                    pnl = (exit_price - active_trade["entry_price"]) * shares - active_trade["entry_cost"] - exit_cost
                    pnl_pct = pnl / (active_trade["entry_price"] * shares) if (active_trade["entry_price"] * shares) > 0 else 0.0

                    trades.append({
                        "symbol": symbol,
                        "entry_time": active_trade["entry_time"],
                        "exit_time": exit_time,
                        "entry_price": active_trade["entry_price"],
                        "exit_price": exit_price,
                        "shares": shares,
                        "entry_cost": active_trade["entry_cost"],
                        "exit_cost": exit_cost,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "stop_price": active_trade["stop_price"],
                        "status": "closed",
                    })

                    active_trade = None
                    position_shares = 0
                    in_position = False

            # Check Stop-Loss hit during the day t if in position
            if in_position and active_trade is not None:
                low_val = float(df_signals["low"].iloc[t]) if "low" in df_signals.columns else float(closes.iloc[t])
                stop_price = active_trade.get("stop_price")
                if stop_price is not None and low_val <= stop_price:
                    # Stopped out!
                    exit_price = stop_price
                    # If open is already below stop, we get stopped out at the open price (gap-down)
                    if float(opens.iloc[t]) < stop_price:
                        exit_price = float(opens.iloc[t])
                        
                    exit_time = dates[t]
                    shares = position_shares
                    
                    # Transaction costs on stop out
                    exit_cost = 0.0
                    if self.cost_model is not None:
                        vix_val = float(df_signals[vix_col].iloc[t]) if has_vix and not pd.isna(df_signals[vix_col].iloc[t]) else None
                        mult = spread_multiplier(vix_val) if vix_val is not None else 1.0
                        
                        impact_bps = 0.0
                        if "volume" in df_signals.columns and t > 20:
                            adv_20 = df_signals["volume"].iloc[t-20:t].mean()
                            if adv_20 > 0:
                                returns = df_signals["close"].iloc[max(0, t-20):t].pct_change().dropna()
                                daily_vol = returns.std() if len(returns) > 0 else 0.01
                                impact_fraction = 0.5 * daily_vol * np.sqrt(shares / adv_20)
                                impact_bps = impact_fraction * 10000.0

                        exit_bps = self.cost_model.spread_bps * mult + self.cost_model.slippage_bps + impact_bps
                        exit_cost = (
                            (shares * exit_price) * exit_bps / 10000.0
                            + (shares * exit_price) * self.cost_model.sec_fee_per_million / 1_000_000.0
                            + shares * self.cost_model.finra_per_share
                        )

                    cash = cash + (shares * exit_price) - exit_cost
                    pnl = (exit_price - active_trade["entry_price"]) * shares - active_trade["entry_cost"] - exit_cost
                    pnl_pct = pnl / (active_trade["entry_price"] * shares) if (active_trade["entry_price"] * shares) > 0 else 0.0

                    trades.append({
                        "symbol": symbol,
                        "entry_time": active_trade["entry_time"],
                        "exit_time": exit_time,
                        "entry_price": active_trade["entry_price"],
                        "exit_price": exit_price,
                        "shares": shares,
                        "entry_cost": active_trade["entry_cost"],
                        "exit_cost": exit_cost,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "stop_price": active_trade["stop_price"],
                        "status": "stopped",
                    })

                    active_trade = None
                    position_shares = 0
                    in_position = False

            # B. Value the portfolio at the Close of day t
            current_equity = cash + position_shares * float(closes.iloc[t])
            equity_values.append(current_equity)

        # Force close any open position at the final close price for reporting purposes
        if in_position and active_trade is not None:
            exit_price = float(closes.iloc[-1])
            exit_time = dates[-1]
            shares = position_shares

            exit_cost = 0.0
            if self.cost_model is not None:
                vix_val = float(df_signals[vix_col].iloc[-1]) if has_vix and not pd.isna(df_signals[vix_col].iloc[-1]) else None
                mult = spread_multiplier(vix_val) if vix_val is not None else 1.0
                
                # Almgren-Chriss market impact model on force-close
                impact_bps = 0.0
                if "volume" in df_signals.columns and len(df_signals) > 20:
                    adv_20 = df_signals["volume"].iloc[-20:].mean()
                    if adv_20 > 0:
                        returns = df_signals["close"].iloc[-20:].pct_change().dropna()
                        daily_vol = returns.std() if len(returns) > 0 else 0.01
                        impact_fraction = 0.5 * daily_vol * np.sqrt(shares / adv_20)
                        impact_bps = impact_fraction * 10000.0

                exit_bps = self.cost_model.spread_bps * mult + self.cost_model.slippage_bps + impact_bps
                exit_cost = (
                    (shares * exit_price) * exit_bps / 10000.0
                    + (shares * exit_price) * self.cost_model.sec_fee_per_million / 1_000_000.0
                    + shares * self.cost_model.finra_per_share
                )

            pnl = (exit_price - active_trade["entry_price"]) * shares - active_trade["entry_cost"] - exit_cost
            pnl_pct = pnl / (active_trade["entry_price"] * shares) if (active_trade["entry_price"] * shares) > 0 else 0.0

            trades.append({
                "symbol": symbol,
                "entry_time": active_trade["entry_time"],
                "exit_time": exit_time,
                "entry_price": active_trade["entry_price"],
                "exit_price": exit_price,
                "shares": shares,
                "entry_cost": active_trade["entry_cost"],
                "exit_cost": exit_cost,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "stop_price": active_trade["stop_price"],
                "status": "open",  # Mark as open since it was force-liquidated at final close
            })

        equity_curve = pd.Series(equity_values, index=df_signals.index)
        metrics = compute_performance_metrics(equity_curve, trades)

        return {
            "equity_curve": equity_curve,
            "trades": trades,
            "metrics": metrics,
        }

    def run_walk_forward(
        self,
        df: pd.DataFrame,
        train_window_days: int = 756,
        test_window_days: int = 126,
        embargo_days: int = 5,
        step_size_days: int = 63,
    ) -> dict:
        """Perform out-of-sample walk-forward strategy evaluation.

        Args:
            df: Input OHLCV DataFrame with timezone-aware DatetimeIndex.
            train_window_days: Size of the training window in trading days.
            test_window_days: Size of the out-of-sample test window in trading days.
            embargo_days: Number of trading days to skip between training and testing.
            step_size_days: Number of trading days to roll forward for each fold.

        Returns:
            A dict containing:
                - 'folds': List of fold results dictionaries.
                - 'equity_curve': Continuous aggregated OOS equity curve.
                - 'trades': Aggregated list of OOS trades.
                - 'metrics': Aggregated performance metrics of the chained curve.
        """
        n_bars = len(df)
        if n_bars < train_window_days + embargo_days + 1:
            logger.warning(
                "DataFrame size (%d) is too small for walk-forward parameters "
                "(train: %d, embargo: %d). Returning empty results.",
                n_bars, train_window_days, embargo_days
            )
            return {
                "folds": [],
                "equity_curve": pd.Series(dtype=float),
                "trades": [],
                "metrics": {},
            }

        # Identify all walk-forward folds
        fold_configs = []
        start_idx = 0
        while True:
            train_end_idx = start_idx + train_window_days
            test_start_idx = train_end_idx + embargo_days
            if test_start_idx >= n_bars:
                break
            test_end_idx = min(test_start_idx + test_window_days, n_bars)

            fold_configs.append({
                "train_start": start_idx,
                "train_end": train_end_idx,
                "test_start": test_start_idx,
                "test_end": test_end_idx,
            })

            start_idx += step_size_days

        if not fold_configs:
            logger.warning("No folds could be created. Returning empty results.")
            return {
                "folds": [],
                "equity_curve": pd.Series(dtype=float),
                "trades": [],
                "metrics": {},
            }

        logger.info("Starting walk-forward validation with %d folds.", len(fold_configs))

        aggregated_equity_parts = []
        aggregated_trades = []
        fold_results = []

        current_capital = self.capital

        for k, fold in enumerate(fold_configs):
            # Slice DF to include training window + test window to calculate indicators properly
            df_fold = df.iloc[fold["train_start"] : fold["test_end"]].copy()

            # Convert test_start index to relative offset inside df_fold
            test_start_rel = fold["test_start"] - fold["train_start"]

            # Initialize a fresh engine instance for the fold using rolled capital
            fold_engine = BacktestEngine(
                strategy=self.strategy,
                capital=current_capital,
                cost_model=self.cost_model,
            )

            # Run backtest, simulating trading starting at OOS test start index
            fold_res = fold_engine.run(df_fold, simulation_start_idx=test_start_rel)

            # Determine the non-overlapping segment of this test window
            if k < len(fold_configs) - 1:
                next_fold = fold_configs[k + 1]
                segment_end_idx = next_fold["test_start"]
            else:
                segment_end_idx = fold["test_end"]

            # absolute segment start and end dates
            segment_start_date = df.index[fold["test_start"]]
            segment_end_date = df.index[segment_end_idx - 1]

            # Relative index range of the segment within fold_res
            fold_test_start_idx = fold["test_start"] - fold["train_start"]
            fold_segment_end_idx = segment_end_idx - fold["train_start"]

            # Slice out-of-sample segment equity curve
            equity_slice = fold_res["equity_curve"].iloc[fold_test_start_idx : fold_segment_end_idx]
            aggregated_equity_parts.append(equity_slice)

            # Filter trades falling inside the segment date range
            fold_trades = fold_res["trades"]
            segment_trades = [
                tr for tr in fold_trades
                if segment_start_date <= tr["entry_time"] <= segment_end_date
            ]
            aggregated_trades.extend(segment_trades)

            # Capital rolls forward into the next segment
            current_capital = float(equity_slice.iloc[-1])

            # Compute fold metrics over its entire OOS test window
            fold_oos_equity = fold_res["equity_curve"].iloc[fold_test_start_idx:]
            fold_oos_trades = [
                tr for tr in fold_trades
                if df.index[fold["test_start"]] <= tr["entry_time"] < df.index[fold["test_end"]]
            ]
            fold_metrics = compute_performance_metrics(fold_oos_equity, fold_oos_trades)

            fold_results.append({
                "fold": k,
                "train_range": (df.index[fold["train_start"]], df.index[fold["train_end"] - 1]),
                "test_range": (df.index[fold["test_start"]], df.index[fold["test_end"] - 1]),
                "metrics": fold_metrics,
                "trades": fold_oos_trades,
            })

        # Concatenate out-of-sample segments into a single curve
        if aggregated_equity_parts:
            combined_equity = pd.concat(aggregated_equity_parts)
        else:
            combined_equity = pd.Series(dtype=float)

        # Compute overall OOS metrics
        combined_metrics = compute_performance_metrics(combined_equity, aggregated_trades)

        return {
            "folds": fold_results,
            "equity_curve": combined_equity,
            "trades": aggregated_trades,
            "metrics": combined_metrics,
        }
