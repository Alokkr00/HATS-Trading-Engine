"""Circuit Breaker module for system-level risk protection.

Hhalts trading activities when daily loss, max drawdown, or transaction
frequency exceed conservative baseline thresholds.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Monitors portfolio equity and order metrics to enforce safety halts."""

    def __init__(self, config: dict | None = None) -> None:
        """Initialize CircuitBreaker with config dictionary."""
        config = config or {}
        cb_cfg = config.get("circuit_breakers", {})

        self.max_daily_loss_pct = cb_cfg.get("max_daily_loss_pct", 0.03)
        self.max_drawdown_pct = cb_cfg.get("max_drawdown_pct", 0.10)
        self.max_trades_per_day = cb_cfg.get("max_trades_per_day", 20)
        self.cooldown_min = cb_cfg.get("cooldown_after_circuit_break_min", 60)

        # Persistence path for circuit breaker state
        self.state_path = Path("data/execution/circuit_breaker_state.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()

    def _load_state(self) -> None:
        """Load persistent state from disk."""
        if self.state_path.exists():
            try:
                with open(self.state_path, "r") as f:
                    self.state = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load circuit breaker state: {e}")
                self._reset_state()
        else:
            self._reset_state()

    def _save_state(self) -> None:
        """Save state to disk."""
        try:
            with open(self.state_path, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save circuit breaker state: {e}")

    def _reset_state(self) -> None:
        """Reset state to default values."""
        self.state = {
            "halted": False,
            "halt_reason": "",
            "halt_timestamp": "",
            "equity_peak": 0.0,
            "last_check_date": str(datetime.now().date()),
            "daily_start_equity": 0.0,
            "trades_today_count": 0,
        }
        self._save_state()

    def check(
        self,
        net_liquidity: float,
        trades_today: int = 0,
    ) -> tuple[bool, str]:
        """Perform risk check.

        Args:
            net_liquidity: Current net account liquidation value.
            trades_today: Total trades executed today.

        Returns:
            Tuple of (is_allowed, reason). If is_allowed is False, trading is blocked.
        """
        today_str = str(datetime.now().date())
        self._load_state()

        # Handle date transition (reset daily start equity and trade counts)
        if self.state["last_check_date"] != today_str:
            self.state["daily_start_equity"] = net_liquidity
            self.state["trades_today_count"] = 0
            self.state["last_check_date"] = today_str
            # If we were halted for daily limits/trade count yesterday, auto-resume
            if self.state["halted"] and "Drawdown" not in self.state["halt_reason"]:
                self.state["halted"] = False
                self.state["halt_reason"] = ""
                self.state["halt_timestamp"] = ""
            self._save_state()

        # Initialize start equity if first run of the day
        if self.state["daily_start_equity"] <= 0.0:
            self.state["daily_start_equity"] = net_liquidity
            self._save_state()

        # Update equity peak
        if net_liquidity > self.state["equity_peak"]:
            self.state["equity_peak"] = net_liquidity
            self._save_state()

        # Check if already halted and in cooldown
        if self.state["halted"]:
            halt_ts_str = self.state.get("halt_timestamp", "")
            if halt_ts_str:
                try:
                    halt_ts = datetime.fromisoformat(halt_ts_str)
                    elapsed = (datetime.now() - halt_ts).total_seconds() / 60.0
                    # Cooldown period check (unless it's max drawdown kill switch which is persistent)
                    if "Drawdown" not in self.state["halt_reason"] and elapsed >= self.cooldown_min:
                        self.state["halted"] = False
                        self.state["halt_reason"] = ""
                        self.state["halt_timestamp"] = ""
                        self._save_state()
                        logger.info("Circuit breaker cooldown period elapsed. Resuming trading.")
                    else:
                        return False, f"Trading halted: {self.state['halt_reason']}"
                except ValueError:
                    return False, f"Trading halted: {self.state['halt_reason']}"
            else:
                return False, f"Trading halted: {self.state['halt_reason']}"

        # 1. Check Daily Loss Limit
        start_equity = self.state["daily_start_equity"]
        daily_loss_pct = (start_equity - net_liquidity) / start_equity if start_equity > 0.0 else 0.0
        if daily_loss_pct >= self.max_daily_loss_pct:
            reason = f"Daily loss ({daily_loss_pct:.2%}) exceeded limit of {self.max_daily_loss_pct:.2%}"
            self._trigger_halt(reason)
            return False, reason

        # 2. Check Peak Drawdown Limit
        peak = self.state["equity_peak"]
        drawdown_pct = (peak - net_liquidity) / peak if peak > 0.0 else 0.0
        if drawdown_pct >= self.max_drawdown_pct:
            reason = f"Drawdown from peak ({drawdown_pct:.2%}) exceeded limit of {self.max_drawdown_pct:.2%}"
            self._trigger_halt(reason)
            return False, reason

        # 3. Check Max Trades Rate Limit
        total_trades = max(trades_today, self.state["trades_today_count"])
        if total_trades >= self.max_trades_per_day:
            reason = f"Daily trades count ({total_trades}) exceeded limit of {self.max_trades_per_day}"
            self._trigger_halt(reason)
            return False, reason

        # Synchronize trades count state
        if trades_today > self.state["trades_today_count"]:
            self.state["trades_today_count"] = trades_today
            self._save_state()

        return True, "Risk checks passed."

    def _trigger_halt(self, reason: str) -> None:
        """Trigger emergency halt state."""
        self.state["halted"] = True
        self.state["halt_reason"] = reason
        self.state["halt_timestamp"] = datetime.now().isoformat()
        self._save_state()
        logger.critical(f"⚠️ CIRCUIT BREAKER TRIGGERED: {reason}")

    def reset(self) -> None:
        """Manually clear circuit breaker halts."""
        self._reset_state()
        logger.info("Circuit breaker manual reset performed.")
