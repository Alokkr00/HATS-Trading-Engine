"""Walk-Forward Cross-Validation & Out-of-Sample Testing Engine.

Implements sequential expanding and rolling window out-of-sample validation
with an explicit embargo period between train and test slices to prevent
serial correlation and look-ahead information leakage (López de Prado).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from src.backtest.cost import CostModel
from src.backtest.engine import BacktestEngine
from src.backtest.metrics_advanced import calculate_advanced_metrics
from src.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardFoldResult:
    """Encapsulates the results of a single walk-forward cross-validation fold."""
    fold_index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    in_sample_metrics: dict[str, Any]
    out_of_sample_metrics: dict[str, Any]
    out_of_sample_equity_curve: pd.Series
    out_of_sample_trades: list[dict[str, Any]]


class WalkForwardValidator:
    """Orchestrates purged and embargoed walk-forward backtesting."""

    def __init__(
        self,
        strategy: BaseStrategy,
        train_bars: int = 252,
        test_bars: int = 63,
        embargo_bars: int = 5,
        mode: str = "rolling",
        capital: float = 100000.0,
        cost_model: CostModel | None = None,
        num_tested_trials: int = 1,
    ) -> None:
        """Initialize the WalkForwardValidator.

        Args:
            strategy: Concrete instance of BaseStrategy.
            train_bars: Number of daily bars for the in-sample (train) window.
            test_bars: Number of daily bars for the out-of-sample (test) window.
            embargo_bars: Number of bars to discard between train and test to prevent leakage.
            mode: Window expansion mode ('rolling' or 'expanding').
            capital: Starting account equity.
            cost_model: Transaction friction model.
            num_tested_trials: Number of trial variations tested (used for Deflated Sharpe calculation).
        """
        self.strategy = strategy
        self.train_bars = train_bars
        self.test_bars = test_bars
        self.embargo_bars = embargo_bars
        self.mode = mode.lower().strip()
        self.capital = capital
        self.cost_model = cost_model or CostModel(spread_bps=1.5, slippage_bps=3.0)
        self.num_tested_trials = num_tested_trials

        if self.mode not in ["rolling", "expanding"]:
            raise ValueError(f"Invalid mode '{self.mode}'. Must be 'rolling' or 'expanding'.")

    def run(self, df: pd.DataFrame) -> dict[str, Any]:
        """Execute walk-forward cross-validation over the input OHLCV DataFrame.

        Args:
            df: Historical market DataFrame with timezone-aware DatetimeIndex.

        Returns:
            Dictionary containing:
                - 'folds': List of WalkForwardFoldResult objects.
                - 'oos_equity_curve': Stitched out-of-sample equity curve (pd.Series).
                - 'oos_returns': Stitched daily out-of-sample return series (pd.Series).
                - 'oos_advanced_metrics': Robustness metrics (DSR, PSR, CVaR, Expectancy).
                - 'summary': Aggregate summary comparison (In-sample vs Out-of-sample degradation).
        """
        n_total = len(df)
        min_required = self.train_bars + self.embargo_bars + self.test_bars
        if n_total < min_required:
            raise ValueError(
                f"Input DataFrame length ({n_total}) is insufficient for walk-forward validation. "
                f"Minimum required is {min_required} bars."
            )

        fold_results: list[WalkForwardFoldResult] = []
        oos_return_series_list: list[pd.Series] = []
        all_oos_trades: list[dict[str, Any]] = []

        step = self.test_bars
        current_fold = 0
        train_start_idx = 0

        while True:
            train_end_idx = train_start_idx + self.train_bars if self.mode == "rolling" else (current_fold * step) + self.train_bars
            test_start_idx = train_end_idx + self.embargo_bars
            test_end_idx = test_start_idx + self.test_bars

            if test_end_idx > n_total:
                # If we don't have enough bars for a full test slice, include remaining bars if >= 10
                if n_total - test_start_idx >= 10:
                    test_end_idx = n_total
                else:
                    break

            df_train = df.iloc[train_start_idx:train_end_idx].copy()
            df_test = df.iloc[test_start_idx:test_end_idx].copy()

            # Preserve symbol attribute
            if "symbol" in df.attrs:
                df_train.attrs["symbol"] = df.attrs["symbol"]
                df_test.attrs["symbol"] = df.attrs["symbol"]

            # 1. Run In-Sample Backtest
            engine_is = BacktestEngine(
                strategy=self.strategy,
                capital=self.capital,
                cost_model=self.cost_model,
            )
            res_is = engine_is.run(df_train)

            # 2. Run Out-of-Sample Backtest
            engine_oos = BacktestEngine(
                strategy=self.strategy,
                capital=self.capital,
                cost_model=self.cost_model,
            )
            res_oos = engine_oos.run(df_test)

            # Extract fold out-of-sample daily returns
            eq_oos = res_oos["equity_curve"]
            ret_oos = eq_oos.pct_change().fillna(0.0)
            oos_return_series_list.append(ret_oos)
            all_oos_trades.extend(res_oos.get("trades", []))

            # Advanced metrics for fold
            adv_is = calculate_advanced_metrics(
                res_is["equity_curve"].pct_change().fillna(0.0),
                num_trials=self.num_tested_trials,
                trades=res_is.get("trades", []),
            )
            adv_oos = calculate_advanced_metrics(
                ret_oos,
                num_trials=self.num_tested_trials,
                trades=res_oos.get("trades", []),
            )

            fold_res = WalkForwardFoldResult(
                fold_index=current_fold,
                train_start=df_train.index[0],
                train_end=df_train.index[-1],
                test_start=df_test.index[0],
                test_end=df_test.index[-1],
                in_sample_metrics={**res_is["metrics"], **adv_is},
                out_of_sample_metrics={**res_oos["metrics"], **adv_oos},
                out_of_sample_equity_curve=eq_oos,
                out_of_sample_trades=res_oos.get("trades", []),
            )
            fold_results.append(fold_res)

            # Advance window
            current_fold += 1
            if self.mode == "rolling":
                train_start_idx += step
            # expanding: train_start_idx stays 0

            if test_end_idx >= n_total:
                break

        # Stitch aggregated Out-of-Sample return series
        if oos_return_series_list:
            stitched_oos_returns = pd.concat(oos_return_series_list).sort_index()
            # Remove any duplicated timestamp indices if folds overlapped
            stitched_oos_returns = stitched_oos_returns[~stitched_oos_returns.index.duplicated(keep="first")]
            stitched_oos_equity = self.capital * (1.0 + stitched_oos_returns).cumprod()
        else:
            stitched_oos_returns = pd.Series(dtype=float)
            stitched_oos_equity = pd.Series(dtype=float)

        # Compute full out-of-sample advanced metrics
        oos_advanced = calculate_advanced_metrics(
            stitched_oos_returns,
            num_trials=self.num_tested_trials,
            trades=all_oos_trades,
        )

        # In-sample vs Out-of-sample degradation metrics
        avg_is_sharpe = float(np.mean([f.in_sample_metrics.get("annualized_sharpe", 0.0) for f in fold_results])) if fold_results else 0.0
        oos_sharpe = float(oos_advanced.get("annualized_sharpe", 0.0))
        sharpe_degradation = (oos_sharpe / avg_is_sharpe - 1.0) if avg_is_sharpe > 0 else 0.0

        summary = {
            "num_folds": len(fold_results),
            "mode": self.mode,
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "embargo_bars": self.embargo_bars,
            "avg_in_sample_sharpe": float(round(avg_is_sharpe, 4)),
            "out_of_sample_sharpe": float(round(oos_sharpe, 4)),
            "sharpe_degradation_pct": float(round(sharpe_degradation * 100.0, 2)),
            "deflated_sharpe_ratio": float(oos_advanced.get("dsr", 0.0)),
            "probabilistic_sharpe_ratio": float(oos_advanced.get("psr", 0.0)),
            "expected_shortfall_cvar95": float(oos_advanced.get("cvar_95", 0.0)),
            "expectancy": float(oos_advanced.get("expectancy", 0.0)),
            "profit_factor": float(oos_advanced.get("profit_factor", 0.0)),
            "max_consecutive_losses": int(oos_advanced.get("max_consecutive_losses", 0)),
        }

        return {
            "folds": fold_results,
            "oos_equity_curve": stitched_oos_equity,
            "oos_returns": stitched_oos_returns,
            "oos_advanced_metrics": oos_advanced,
            "summary": summary,
        }
