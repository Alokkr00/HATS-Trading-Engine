"""Shared utilities — logging, formatting, and market-calendar helpers.

Canonical imports::

    from src.utils import get_logger, setup_logger
    from src.utils import is_market_open, get_trading_days
    from src.utils import format_currency, format_pct, ensure_dir
"""

from src.utils.helpers import (
    ensure_dir,
    format_currency,
    format_pct,
    get_trading_days,
    is_market_open,
    is_trading_day,
)
from src.utils.logger import get_logger, setup_logger
from src.utils.rate_limiter import TokenBucketRateLimiter
from src.utils.notifier import send_telegram_alert
from src.utils.paths import (
    PROJECT_ROOT,
    DATA_DIR,
    RAW_DATA_DIR,
    EXECUTION_DIR,
    REPORTS_DIR,
    CHARTS_DIR,
    CHROMA_DB_DIR,
    COPILOT_DIR,
    LOGS_DIR,
    CONFIG_DIR,
    DASHBOARD_DIR,
    TEMPLATES_DIR,
    STATIC_DIR,
    DB_PATH,
    CIRCUIT_BREAKER_PATH,
    ENGINE_STATUS_PATH,
    SECTOR_CACHE_PATH,
    OMS_STATE_PATH,
    ensure_project_dirs,
    get_project_path,
)

__all__ = [
    # Logging
    "get_logger",
    "setup_logger",
    # Market calendar
    "is_market_open",
    "is_trading_day",
    "get_trading_days",
    # Formatting
    "format_currency",
    "format_pct",
    # Filesystem & Paths
    "ensure_dir",
    "PROJECT_ROOT",
    "DATA_DIR",
    "RAW_DATA_DIR",
    "EXECUTION_DIR",
    "REPORTS_DIR",
    "CHARTS_DIR",
    "CHROMA_DB_DIR",
    "COPILOT_DIR",
    "LOGS_DIR",
    "CONFIG_DIR",
    "DASHBOARD_DIR",
    "TEMPLATES_DIR",
    "STATIC_DIR",
    "DB_PATH",
    "CIRCUIT_BREAKER_PATH",
    "ENGINE_STATUS_PATH",
    "SECTOR_CACHE_PATH",
    "OMS_STATE_PATH",
    "ensure_project_dirs",
    "get_project_path",
    # Throttling
    "TokenBucketRateLimiter",
    # Alerts
    "send_telegram_alert",
]
