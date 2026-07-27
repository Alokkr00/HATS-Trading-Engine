"""Statistical validation layer for backtest results.

Includes block bootstrapping, Deflated Sharpe Ratio (DSR), expected maximum
Sharpe ratio, multiple testing corrections (Holm-Bonferroni), and red flags checker.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
import scipy.stats as stats

from src.utils import get_logger

logger = get_logger(__name__)


def block_bootstrap(
    returns: pd.Series,
    block_size: int = 21,
    num_samples: int = 1000
) -> dict[str, dict[str, float]]:
    """Resamples daily returns of the OOS equity curve using circular block bootstrap.

    Preserves serial correlation of returns and computes the bootstrap distribution
    of Sharpe ratio, annualized return, max drawdown, and daily win rate.

    Args:
        returns: Daily returns of the OOS equity curve.
        block_size: Size of contiguous blocks to resample (default 21).
        num_samples: Number of bootstrap iterations (default 1000).

    Returns:
        Dict containing mean, median, and 95% confidence intervals (ci_lower, ci_upper)
        for each metric: 'sharpe_ratio', 'annualized_return', 'max_drawdown', 'win_rate'.
    """
    n = len(returns)
    if n == 0:
        empty_stats = {"mean": 0.0, "median": 0.0, "ci_lower": 0.0, "ci_upper": 0.0}
        return {
            "sharpe_ratio": empty_stats.copy(),
            "annualized_return": empty_stats.copy(),
            "max_drawdown": empty_stats.copy(),
            "win_rate": empty_stats.copy(),
        }

    # Pre-allocate arrays
    sharpes = np.zeros(num_samples)
    ann_rets = np.zeros(num_samples)
    max_dds = np.zeros(num_samples)
    win_rates = np.zeros(num_samples)

    effective_block_size = min(block_size, n)
    num_blocks = int(np.ceil(n / effective_block_size))

    # Convert to numpy array for performance
    returns_arr = returns.values

    for s in range(num_samples):
        # Choose start indices uniformly from 0 to n-1
        start_indices = np.random.randint(0, n, size=num_blocks)

        # Build resampled index sequence using circular wrapping
        boot_indices = []
        for start in start_indices:
            boot_indices.extend([(start + i) % n for i in range(effective_block_size)])

        boot_indices = boot_indices[:n]
        boot_returns = returns_arr[boot_indices]

        # Calculate metrics for the bootstrap sample
        # 1. Sharpe Ratio
        mean_r = np.mean(boot_returns)
        if len(boot_returns) > 1:
            std_r = np.std(boot_returns, ddof=1)
        else:
            std_r = 0.0
        sharpe = (mean_r / std_r) * np.sqrt(252.0) if std_r > 1e-9 else 0.0

        # 2. Annualized Return
        prod = np.prod(1.0 + boot_returns)
        if prod > 0:
            ann_ret = (prod) ** (252.0 / n) - 1.0
        else:
            ann_ret = mean_r * 252.0

        # 3. Max Drawdown
        equity = np.cumprod(1.0 + boot_returns)
        running_max = np.maximum.accumulate(equity)
        with np.errstate(divide="ignore", invalid="ignore"):
            drawdown = np.where(running_max > 0, (equity - running_max) / running_max, 0.0)
            max_dd = np.nanmin(drawdown) if len(drawdown) > 0 else 0.0

        # 4. Win Rate
        win_rate = np.mean(boot_returns > 0)

        # Replace potential NaNs or Infs
        sharpes[s] = 0.0 if np.isnan(sharpe) or np.isinf(sharpe) else sharpe
        ann_rets[s] = 0.0 if np.isnan(ann_ret) or np.isinf(ann_ret) else ann_ret
        max_dds[s] = 0.0 if np.isnan(max_dd) or np.isinf(max_dd) else max_dd
        win_rates[s] = 0.0 if np.isnan(win_rate) or np.isinf(win_rate) else win_rate

    def get_stats(arr: np.ndarray) -> dict[str, float]:
        return {
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "ci_lower": float(np.percentile(arr, 2.5)),
            "ci_upper": float(np.percentile(arr, 97.5)),
        }

    return {
        "sharpe_ratio": get_stats(sharpes),
        "annualized_return": get_stats(ann_rets),
        "max_drawdown": get_stats(max_dds),
        "win_rate": get_stats(win_rates),
    }


def expected_max_sharpe(N_trials: int, T_days: int) -> float:
    """Computes the expected maximum Sharpe ratio under the null hypothesis.

    Uses the Euler-Mascheroni approximation for the expected maximum of
    N_trials independent standard normal variables, scaled to the annualized
    Sharpe ratio standard deviation under the null (where true SR = 0).

    Args:
        N_trials: Number of independent strategy configurations tested.
        T_days: Number of trading days in the backtest.

    Returns:
        Expected maximum annualized Sharpe ratio under the null.
    """
    if N_trials <= 1:
        return 0.0
    if T_days <= 0:
        return 0.0

    ln_N = np.log(N_trials)
    # Euler-Mascheroni approximation for the expected max of N standard normal variables
    expected_z = np.sqrt(2.0 * ln_N) - (np.log(np.pi) + np.log(ln_N)) / (2.0 * np.sqrt(2.0 * ln_N))

    # Standard deviation of the annualized Sharpe ratio under the null:
    # Daily SR variance under null = 1 / T_days.
    # Annualized SR standard deviation = sqrt(252 / T_days).
    std_ann_sr_null = np.sqrt(252.0 / T_days)

    return float(expected_z * std_ann_sr_null)


def deflated_sharpe_ratio(
    observed_sr: float,
    skewness: float,
    kurtosis: float,
    T_days: int,
    N_trials: int
) -> float:
    """Computes the Deflated Sharpe Ratio (DSR) probability.

    Adjusts the observed Sharpe ratio to account for non-normal returns and
    multiple trials (selection bias) to check if the strategy performance
    is statistically significant.

    Args:
        observed_sr: Observed annualized Sharpe ratio.
        skewness: Skewness of daily returns.
        kurtosis: Pearson kurtosis of daily returns (normal = 3).
        T_days: Number of trading days in the backtest.
        N_trials: Number of strategy configurations tested.

    Returns:
        The probability of Deflated Sharpe Ratio (value between 0.0 and 1.0).
        If > 0.95, it indicates statistical significance at alpha = 0.05.
    """
    if T_days <= 1:
        return 0.0

    # Convert observed_sr (annualized) to daily space
    sr_daily = observed_sr / np.sqrt(252.0)

    # Compute expected max Sharpe ratio (annualized) under the null
    sr_benchmark = expected_max_sharpe(N_trials, T_days)

    # Calculate standard error of the daily Sharpe ratio
    # SE(SR_daily) = sqrt((1 - skewness * SR_daily + (kurtosis - 1)/4 * SR_daily**2) / T_days)
    se_daily = np.sqrt(
        (1.0 - skewness * sr_daily + (kurtosis - 1.0) / 4.0 * (sr_daily ** 2)) / T_days
    )

    # Annualize the standard error to match the scale of observed_sr and sr_benchmark
    se_ann = se_daily * np.sqrt(252.0)

    if se_ann > 1e-9:
        dsr_prob = stats.norm.cdf((observed_sr - sr_benchmark) / se_ann)
    else:
        dsr_prob = 0.0

    return float(dsr_prob)


def holm_bonferroni_correction(p_values: list[float], alpha: float = 0.05) -> list[bool]:
    """Computes the Holm-Bonferroni correction on a list of p-values.

    Args:
        p_values: List of p-values.
        alpha: Significance level (default 0.05).

    Returns:
        A list of booleans indicating whether each hypothesis is rejected (True) or not (False).
    """
    n = len(p_values)
    if n == 0:
        return []

    # Store original indices to restore order at the end
    indexed_p = [(p, idx) for idx, p in enumerate(p_values)]
    # Sort by p-value
    indexed_p.sort(key=lambda x: x[0])

    reject = [False] * n

    for i, (p, idx) in enumerate(indexed_p):
        threshold = alpha / (n - i)
        if p <= threshold:
            reject[idx] = True
        else:
            break

    return reject


def check_red_flags(metrics: dict, total_trials: int) -> list[str]:
    """Audits backtest results against the guidelines in validation_framework.md.

    Checks for automatic rejections (hard fails) and warnings.

    Args:
        metrics: Dictionary containing backtest performance metrics.
        total_trials: Total number of trials to compute DSR.

    Returns:
        List of warning and rejection strings.
    """
    flags = []

    def get_metric(keys: list[str], default=None):
        for k in keys:
            if k in metrics:
                return metrics[k]
        return default

    # 1. Sharpe Ratio check
    sharpe = get_metric(["sharpe_ratio", "oos_sharpe", "sharpe"])
    if sharpe is not None:
        if sharpe > 2.0:
            flags.append(
                f"REJECT: Sharpe ratio ({sharpe:.2f}) is too high (> 2.0). "
                "Likely overfitting or look-ahead bias."
            )

    # 2. Total trades check
    trades = get_metric(["total_trades", "trades", "num_trades", "trade_count"])
    if trades is not None:
        if trades < 100:
            flags.append(
                f"REJECT: Total trades ({trades}) is below the minimum threshold of 100."
            )

    # 3. Maximum drawdown check
    drawdown = get_metric(["max_drawdown", "drawdown", "max_dd", "max_drawdown_pct"])
    if drawdown is not None:
        abs_dd = abs(drawdown)
        if abs_dd <= 1.0:
            if abs_dd > 0.20:
                flags.append(
                    f"REJECT: Maximum drawdown ({drawdown:.2%}) exceeds the maximum threshold of 20.0%."
                )
        else:
            if abs_dd > 20.0:
                flags.append(
                    f"REJECT: Maximum drawdown ({drawdown:.2f}%) exceeds the maximum threshold of 20.0%."
                )

    # 4. DSR check
    dsr = get_metric(["deflated_sharpe_ratio", "deflated_sharpe", "dsr"])
    if dsr is None and sharpe is not None:
        skewness = get_metric(["skewness", "skew"])
        kurtosis = get_metric(["kurtosis", "kurt", "pearson_kurtosis"])
        t_days = get_metric(["t_days", "T", "trading_days", "len_returns"])
        if skewness is not None and kurtosis is not None and t_days is not None:
            dsr = deflated_sharpe_ratio(sharpe, skewness, kurtosis, int(t_days), total_trials)

    if dsr is not None:
        if dsr <= 0.95:
            flags.append(
                f"REJECT: Deflated Sharpe Ratio ({dsr:.4f}) is <= 0.95. "
                "Performance is not statistically significant."
            )

    # 5. Profit factor check (Warning)
    pf = get_metric(["profit_factor", "pf"])
    if pf is not None:
        if 1.0 <= pf <= 1.2:
            flags.append(
                f"WARNING: Low profit factor ({pf:.2f}) between 1.0 and 1.2. "
                "Edge is fragile."
            )

    # 6. Inconsistent fold performance (Warning)
    sharpe_std = get_metric(["sharpe_std", "sharpe_ratio_std"])
    sharpe_mean = get_metric(["sharpe_mean", "sharpe_ratio_mean", "mean_sharpe"])
    if sharpe_std is not None and sharpe_mean is not None:
        if sharpe_std > sharpe_mean:
            flags.append(
                "WARNING: Inconsistent fold performance. "
                f"Standard deviation of Sharpe across folds ({sharpe_std:.2f}) "
                f"is greater than the mean Sharpe ({sharpe_mean:.2f})."
            )

    # 7. Short backtest period (Warning)
    total_years = get_metric(["total_years", "backtest_years", "years"])
    if total_years is not None:
        if total_years < 5:
            flags.append(
                f"WARNING: Short backtest period ({total_years:.1f} years). "
                "Less than the recommended 5 years."
            )

    return flags
