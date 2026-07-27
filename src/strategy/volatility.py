"""Cubic Spline Volatility Surface module for option chain pricing and Greek calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline
from src.utils import get_logger

logger = get_logger(__name__)


class CubicSplineVolatilitySurface:
    """Fits 1D Cubic Splines slice-by-slice across strike prices for options expiration dates.

    Provides robust interpolation of Implied Volatility (IV) using linear interpolation
    in variance space (vol^2 * T) between expiration dates.
    """

    def __init__(self, option_chain: pd.DataFrame) -> None:
        """Initialize the volatility surface.

        Args:
            option_chain: DataFrame with columns:
                ['strike', 'days_to_expiry', 'implied_volatility']
        """
        self.splines: dict[float, CubicSpline] = {}
        self.expiries: list[float] = []
        self._fit_surface(option_chain)

    def _fit_surface(self, df: pd.DataFrame) -> None:
        """Fits cubic splines for each unique expiration slice."""
        if df is None or df.empty:
            logger.warning("Empty option chain provided to volatility surface. Defaulting to flat vol.")
            return

        required = ["strike", "days_to_expiry", "implied_volatility"]
        for col in required:
            if col not in df.columns:
                logger.error(f"Missing required column '{col}' in option chain. Spline fit skipped.")
                return

        # Group by days to expiry (T in years)
        df = df.copy()
        df["T"] = df["days_to_expiry"] / 365.0

        for t_val, group in df.groupby("T"):
            # Sort by strike to satisfy spline fitting requirements
            group = group.sort_values("strike").dropna(subset=["implied_volatility"])
            if len(group) < 3:
                # Need at least 3 points for cubic spline fitting
                continue

            strikes = group["strike"].values
            ivs = group["implied_volatility"].values

            # Remove duplicate strikes if any (take average IV)
            if len(np.unique(strikes)) < len(strikes):
                group = group.groupby("strike")["implied_volatility"].mean().reset_index()
                strikes = group["strike"].values
                ivs = group["implied_volatility"].values

            try:
                # Fit 1D CubicSpline with natural boundary conditions
                self.splines[t_val] = CubicSpline(strikes, ivs, bc_type="natural", extrapolate=True)
                self.expiries.append(t_val)
            except Exception as e:
                logger.error(f"Failed to fit spline for expiry T={t_val:.4f}: {e}")

        self.expiries = sorted(self.expiries)
        logger.info(f"Fitted cubic spline volatility surface with {len(self.splines)} expiration slices.")

    def interpolate(self, strike: float, days_to_expiry: float) -> float:
        """Interpolates IV for a given strike and days to expiry.

        Interpolates linearly in variance space (vol^2 * T) between the two nearest expiries.

        Args:
            strike: Option strike price.
            days_to_expiry: Days remaining to expiration.

        Returns:
            Interpolated implied volatility (float).
        """
        if not self.splines:
            return 0.30  # Fallback flat 30% volatility

        t = max(0.001, days_to_expiry / 365.0)

        # 1. Exact expiry match or only one slice available
        if t in self.splines:
            return float(np.clip(self.splines[t](strike), 0.01, 3.0))

        if len(self.expiries) == 1:
            only_t = self.expiries[0]
            return float(np.clip(self.splines[only_t](strike), 0.01, 3.0))

        # 2. Extrapolate outside bounds (flat extrapolation)
        if t <= self.expiries[0]:
            first_t = self.expiries[0]
            return float(np.clip(self.splines[first_t](strike), 0.01, 3.0))

        if t >= self.expiries[-1]:
            last_t = self.expiries[-1]
            return float(np.clip(self.splines[last_t](strike), 0.01, 3.0))

        # 3. Interpolate between two nearest expiries T1 and T2 in variance space
        idx = np.searchsorted(self.expiries, t)
        t1 = self.expiries[idx - 1]
        t2 = self.expiries[idx]

        iv1 = float(np.clip(self.splines[t1](strike), 0.01, 3.0))
        iv2 = float(np.clip(self.splines[t2](strike), 0.01, 3.0))

        # Variance space linear interpolation: Var = vol^2 * T
        var1 = (iv1 ** 2) * t1
        var2 = (iv2 ** 2) * t2

        w = (t - t1) / (t2 - t1)
        var_interp = (1.0 - w) * var1 + w * var2
        vol_interp = np.sqrt(max(0.0001, var_interp) / t)

        return float(np.clip(vol_interp, 0.01, 3.0))
