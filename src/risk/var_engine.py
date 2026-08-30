"""Dynamic Empirical Covariance & Portfolio VaR/CVaR Engine.

Calculates rolling covariance, historical simulation Value-at-Risk (VaR 95/99),
parametric VaR, and Expected Shortfall (CVaR) across open portfolio positions
to enforce tail risk constraints beyond static single-scenario models.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


class PortfolioVaREngine:
    """Computes empirical covariance, VaR, and Expected Shortfall for multi-asset portfolios."""

    def __init__(
        self,
        lookback_bars: int = 60,
        confidence_level_1: float = 0.95,
        confidence_level_2: float = 0.99,
    ) -> None:
        """Initialize the VaR & CVaR engine.

        Args:
            lookback_bars: Number of historical daily bars used for rolling covariance & historical simulation.
            confidence_level_1: Primary confidence level (default: 0.95).
            confidence_level_2: Secondary tail confidence level (default: 0.99).
        """
        self.lookback_bars = lookback_bars
        self.conf_1 = confidence_level_1
        self.conf_2 = confidence_level_2

    def calculate_rolling_covariance(self, returns_df: pd.DataFrame) -> pd.DataFrame:
        """Calculate the empirical sample covariance matrix from recent asset returns.

        Args:
            returns_df: DataFrame where each column is a ticker's daily return series.

        Returns:
            Covariance matrix (DataFrame).
        """
        if returns_df.empty or len(returns_df) < 5:
            n_assets = len(returns_df.columns) if not returns_df.empty else 1
            return pd.DataFrame(np.eye(n_assets) * 0.0004, index=returns_df.columns, columns=returns_df.columns)

        window = returns_df.iloc[-self.lookback_bars:].dropna()
        return window.cov()

    def calculate_portfolio_var_cvar(
        self,
        positions_value: dict[str, float],
        historical_returns: pd.DataFrame,
    ) -> dict[str, Any]:
        """Compute parametric and historical VaR and Expected Shortfall (CVaR).

        Args:
            positions_value: Dict mapping ticker symbol to current USD notional market value.
                             (e.g., {'SPY': 50000.0, 'QQQ': 30000.0, 'AAPL': -10000.0})
            historical_returns: DataFrame of daily historical returns for portfolio symbols.

        Returns:
            Dictionary containing portfolio dollar & percentage VaR 95/99 and CVaR 95/99.
        """
        total_equity = sum(abs(v) for v in positions_value.values())
        if total_equity <= 0 or historical_returns.empty:
            return {
                "total_exposure_usd": 0.0,
                "historical_var_95_usd": 0.0,
                "historical_var_99_usd": 0.0,
                "historical_cvar_95_usd": 0.0,
                "historical_cvar_99_usd": 0.0,
                "historical_var_95_pct": 0.0,
                "historical_var_99_pct": 0.0,
                "historical_cvar_95_pct": 0.0,
                "historical_cvar_99_pct": 0.0,
                "parametric_var_95_usd": 0.0,
                "parametric_var_99_usd": 0.0,
                "portfolio_volatility_daily": 0.0,
                "portfolio_volatility_annualized": 0.0,
            }

        # Filter to assets present in historical returns
        valid_symbols = [s for s in positions_value.keys() if s in historical_returns.columns]
        if not valid_symbols:
            return {
                "total_exposure_usd": total_equity,
                "historical_var_95_usd": 0.0,
                "historical_var_99_usd": 0.0,
                "historical_cvar_95_usd": 0.0,
                "historical_cvar_99_usd": 0.0,
                "historical_var_95_pct": 0.0,
                "historical_var_99_pct": 0.0,
                "historical_cvar_95_pct": 0.0,
                "historical_cvar_99_pct": 0.0,
                "parametric_var_95_usd": 0.0,
                "parametric_var_99_usd": 0.0,
                "portfolio_volatility_daily": 0.0,
                "portfolio_volatility_annualized": 0.0,
            }

        returns_slice = historical_returns[valid_symbols].iloc[-self.lookback_bars:].dropna()
        n_bars = len(returns_slice)
        if n_bars < 5:
            return {"total_exposure_usd": total_equity, "historical_var_95_usd": 0.0}

        # Portfolio weights vector (signed by long/short position)
        weights = np.array([positions_value[s] / total_equity for s in valid_symbols])

        # ---------------------------------------------------------------------
        # 1. Historical Simulation VaR & CVaR
        # ---------------------------------------------------------------------
        # Portfolio daily return history: R_p(t) = sum(w_i * R_i(t))
        port_returns = returns_slice.dot(weights)
        sorted_returns = np.sort(port_returns.to_numpy())

        idx_95 = max(0, int(np.floor((1.0 - self.conf_1) * n_bars)))
        idx_99 = max(0, int(np.floor((1.0 - self.conf_2) * n_bars)))

        hist_var_95_pct = float(max(0.0, -sorted_returns[idx_95]))
        hist_var_99_pct = float(max(0.0, -sorted_returns[idx_99]))

        # Expected Shortfall: average loss in the tail beyond the quantile
        hist_cvar_95_pct = float(max(hist_var_95_pct, -sorted_returns[: idx_95 + 1].mean())) if idx_95 >= 0 else hist_var_95_pct
        hist_cvar_99_pct = float(max(hist_var_99_pct, -sorted_returns[: idx_99 + 1].mean())) if idx_99 >= 0 else hist_var_99_pct

        # ---------------------------------------------------------------------
        # 2. Parametric VaR (Covariance Matrix)
        # ---------------------------------------------------------------------
        cov_matrix = returns_slice.cov().to_numpy()
        port_variance = float(weights.T @ cov_matrix @ weights)
        port_daily_vol = float(np.sqrt(max(0.0, port_variance)))
        port_ann_vol = float(port_daily_vol * np.sqrt(252))

        z_95 = float(stats.norm.ppf(self.conf_1))
        z_99 = float(stats.norm.ppf(self.conf_2))

        param_var_95_pct = float(z_95 * port_daily_vol)
        param_var_99_pct = float(z_99 * port_daily_vol)

        return {
            "total_exposure_usd": float(round(total_equity, 2)),
            "historical_var_95_usd": float(round(hist_var_95_pct * total_equity, 2)),
            "historical_var_99_usd": float(round(hist_var_99_pct * total_equity, 2)),
            "historical_cvar_95_usd": float(round(hist_cvar_95_pct * total_equity, 2)),
            "historical_cvar_99_usd": float(round(hist_cvar_99_pct * total_equity, 2)),
            "historical_var_95_pct": float(round(hist_var_95_pct * 100.0, 3)),
            "historical_var_99_pct": float(round(hist_var_99_pct * 100.0, 3)),
            "historical_cvar_95_pct": float(round(hist_cvar_95_pct * 100.0, 3)),
            "historical_cvar_99_pct": float(round(hist_cvar_99_pct * 100.0, 3)),
            "parametric_var_95_usd": float(round(param_var_95_pct * total_equity, 2)),
            "parametric_var_99_usd": float(round(param_var_99_pct * total_equity, 2)),
            "portfolio_volatility_daily": float(round(port_daily_vol * 100.0, 3)),
            "portfolio_volatility_annualized": float(round(port_ann_vol * 100.0, 3)),
        }
