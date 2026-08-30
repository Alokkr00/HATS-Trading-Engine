"""Advanced quantitative performance & robustness metrics.

Implements Bailey & López de Prado's Deflated Sharpe Ratio (DSR),
Probabilistic Sharpe Ratio (PSR), Expected Shortfall (CVaR), Expectancy,
Calmar ratio, Gain-to-Pain ratio, and consecutive drawdown metrics.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Sequence
import numpy as np
import pandas as pd
from scipy import stats


def calculate_advanced_metrics(
    returns: pd.Series | np.ndarray | Sequence[float],
    benchmark_sr: float = 0.0,
    num_trials: int = 1,
    var_trials_sr: float = 1.0,
    risk_free_rate: float = 0.0,
    trades: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute institutional quantitative performance and robustness metrics.

    Args:
        returns: Periodic (e.g. daily) return series.
        benchmark_sr: Annualized benchmark Sharpe Ratio (e.g. 0.0 or SPY Sharpe).
        num_trials: Number of strategy parameters/configurations tested (N for DSR).
        var_trials_sr: Variance of Sharpe ratios across all tested trials.
        risk_free_rate: Annual risk-free rate (e.g. 0.04 for 4%).
        trades: Optional list of trade records with 'pnl' or 'return' keys.

    Returns:
        Dictionary containing advanced metrics (DSR, PSR, CVaR 95/99, Expectancy, etc.).
    """
    if isinstance(returns, (list, tuple)):
        r = pd.Series(returns, dtype=float).dropna()
    elif isinstance(returns, np.ndarray):
        r = pd.Series(returns.flatten(), dtype=float).dropna()
    else:
        r = returns.dropna()

    if len(r) < 5 or float(r.std()) <= 1e-7:
        return {
            "sharpe": 0.0,
            "annualized_sharpe": 0.0,
            "psr": 0.0,
            "dsr": 0.0,
            "cvar_95": 0.0,
            "cvar_99": 0.0,
            "var_95": 0.0,
            "var_99": 0.0,
            "skewness": 0.0,
            "kurtosis": 3.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "gain_to_pain": 0.0,
            "calmar_ratio": 0.0,
            "max_consecutive_losses": 0,
            "win_rate": 0.0,
        }

    n = len(r)
    mean_r = float(r.mean())
    std_r = float(r.std(ddof=1))
    daily_rf = (1.0 + risk_free_rate) ** (1.0 / 252.0) - 1.0
    excess_r = r - daily_rf

    # Moments
    skew = float(stats.skew(r, bias=False)) if n >= 3 else 0.0
    # Fisher kurtosis (normal = 0) vs Pearson (normal = 3)
    kurt = float(stats.kurtosis(r, fisher=False, bias=False)) if n >= 4 else 3.0

    # Daily & Annualized Sharpe Ratio
    daily_sr = float(excess_r.mean() / std_r) if std_r > 0 else 0.0
    ann_sr = daily_sr * math.sqrt(252)

    # -------------------------------------------------------------------------
    # 1. Probabilistic Sharpe Ratio (PSR) - Bailey & López de Prado (2012)
    # -------------------------------------------------------------------------
    # Benchmark daily Sharpe
    daily_bench_sr = benchmark_sr / math.sqrt(252)

    # Variance of the Sharpe ratio estimator
    sr_var = (1.0 - skew * daily_sr + ((kurt - 1.0) / 4.0) * (daily_sr ** 2)) / (n - 1.0)
    sr_std = math.sqrt(max(sr_var, 1e-12))

    psr_stat = (daily_sr - daily_bench_sr) / sr_std
    psr = float(stats.norm.cdf(psr_stat))

    # -------------------------------------------------------------------------
    # 2. Deflated Sharpe Ratio (DSR) - Bailey & López de Prado (2014)
    # Corrects for selection bias & multiple testing across N trials
    # -------------------------------------------------------------------------
    if num_trials > 1:
        euler_mascheroni = 0.57721566490153286
        # Expected maximum Sharpe ratio from N independent trials
        z_n = (1.0 - euler_mascheroni) * stats.norm.ppf(1.0 - 1.0 / num_trials) + \
              euler_mascheroni * stats.norm.ppf(1.0 - 1.0 / (num_trials * math.e))
        expected_max_daily_sr = math.sqrt(var_trials_sr / 252.0) * z_n
        dsr_stat = (daily_sr - expected_max_daily_sr) / sr_std
        dsr = float(stats.norm.cdf(dsr_stat))
    else:
        dsr = psr

    # -------------------------------------------------------------------------
    # 3. Value-at-Risk (VaR) & Expected Shortfall (CVaR) - Historical
    # -------------------------------------------------------------------------
    sorted_r = np.sort(r.to_numpy())
    idx_95 = max(0, int(np.floor(0.05 * n)))
    idx_99 = max(0, int(np.floor(0.01 * n)))

    var_95 = float(-sorted_r[idx_95])
    var_99 = float(-sorted_r[idx_99])

    cvar_95 = float(-sorted_r[: idx_95 + 1].mean()) if idx_95 >= 0 else var_95
    cvar_99 = float(-sorted_r[: idx_99 + 1].mean()) if idx_99 >= 0 else var_99

    # -------------------------------------------------------------------------
    # 4. Trade-Level Metrics (Expectancy, Win Rate, Profit Factor, Loss Streaks)
    # -------------------------------------------------------------------------
    trade_pnls: list[float] = []
    if trades:
        for t in trades:
            if "pnl" in t:
                trade_pnls.append(float(t["pnl"]))
            elif "return" in t:
                trade_pnls.append(float(t["return"]))

    if trade_pnls:
        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        n_trades = len(trade_pnls)
        n_wins = len(wins)
        n_losses = len(losses)

        win_rate = n_wins / n_trades if n_trades > 0 else 0.0
        loss_rate = n_losses / n_trades if n_trades > 0 else 0.0

        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(abs(np.mean(losses))) if losses else 0.0

        expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        # Max consecutive losses
        max_consec = 0
        curr_consec = 0
        for p in trade_pnls:
            if p < 0:
                curr_consec += 1
                max_consec = max(max_consec, curr_consec)
            else:
                curr_consec = 0
        max_consecutive_losses = max_consec
    else:
        # Fallback to bar-level returns
        pos_r = r[r > 0]
        neg_r = r[r < 0]
        win_rate = float(len(pos_r) / n) if n > 0 else 0.0
        avg_win = float(pos_r.mean()) if len(pos_r) > 0 else 0.0
        avg_loss = float(abs(neg_r.mean())) if len(neg_r) > 0 else 0.0
        expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss)
        gross_profit = float(pos_r.sum())
        gross_loss = float(abs(neg_r.sum()))
        profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        max_consec = 0
        curr_consec = 0
        for val in r:
            if val < 0:
                curr_consec += 1
                max_consec = max(max_consec, curr_consec)
            else:
                curr_consec = 0
        max_consecutive_losses = max_consec

    # -------------------------------------------------------------------------
    # 5. Gain-to-Pain & Calmar Ratio
    # -------------------------------------------------------------------------
    sum_pos = float(r[r > 0].sum())
    sum_neg = float(abs(r[r < 0].sum()))
    gain_to_pain = float(sum_pos / sum_neg) if sum_neg > 0 else (999.0 if sum_pos > 0 else 0.0)

    # Cumulative equity drawdown
    cum_ret = (1.0 + r).cumprod()
    running_max = cum_ret.cummax()
    drawdowns = (cum_ret - running_max) / running_max
    max_dd = float(abs(drawdowns.min()))

    total_return = float(cum_ret.iloc[-1] - 1.0)
    years = max(n / 252.0, 1.0 / 252.0)
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0)
    calmar_ratio = float(cagr / max_dd) if max_dd > 0 else 0.0

    return {
        "sharpe": float(round(daily_sr, 4)),
        "annualized_sharpe": float(round(ann_sr, 4)),
        "psr": float(round(psr, 4)),
        "dsr": float(round(dsr, 4)),
        "cvar_95": float(round(cvar_95, 4)),
        "cvar_99": float(round(cvar_99, 4)),
        "var_95": float(round(var_95, 4)),
        "var_99": float(round(var_99, 4)),
        "skewness": float(round(skew, 4)),
        "kurtosis": float(round(kurt, 4)),
        "expectancy": float(round(expectancy, 6)),
        "profit_factor": float(round(profit_factor, 4)),
        "gain_to_pain": float(round(gain_to_pain, 4)),
        "calmar_ratio": float(round(calmar_ratio, 4)),
        "max_consecutive_losses": int(max_consecutive_losses),
        "win_rate": float(round(win_rate, 4)),
        "max_drawdown": float(round(max_dd, 4)),
        "cagr": float(round(cagr, 4)),
    }
