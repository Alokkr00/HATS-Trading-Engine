"""Structured logging with console and rotating file handlers.

Usage::

    from src.utils import get_logger

    logger = get_logger(__name__)
    logger.info("Order submitted", extra={"order_id": "12345"})

Design decisions:
    - RotatingFileHandler (10 MB / 5 backups) keeps disk usage bounded.
    - One logger per *name* — repeated calls with the same name return
      the same logger instance (standard ``logging`` behaviour), so it is
      safe to call ``get_logger`` at module level.
    - Handler deduplication: ``setup_logger`` is idempotent; calling it
      twice with the same name will not double-attach handlers.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_FMT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
_DEFAULT_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_LOG_DIR: Path = Path(__file__).resolve().parents[2] / "logs"  # <project>/logs
_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT: int = 5

_UNIFIED_FILE_HANDLER: RotatingFileHandler | None = None
_SDK_LOGGING_CONFIGURED: bool = False


def configure_sdk_logging(log_dir: Path | None = None) -> None:
    """Intercept the Alpaca SDK logger and bind it to a RotatingFileHandler to prevent disk filling."""
    global _SDK_LOGGING_CONFIGURED
    if _SDK_LOGGING_CONFIGURED:
        return
        
    sdk_logger = logging.getLogger("alpaca")
    sdk_logger.propagate = False
    
    # Remove existing handlers
    for h in list(sdk_logger.handlers):
        sdk_logger.removeHandler(h)
        
    resolved_log_dir = log_dir or _LOG_DIR
    _ensure_log_dir(resolved_log_dir)
    
    sdk_log_path = resolved_log_dir / "alpaca_sdk.log"
    formatter = logging.Formatter(_DEFAULT_FMT, datefmt=_DEFAULT_DATE_FMT)
    
    sdk_handler = RotatingFileHandler(
        sdk_log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    sdk_handler.setLevel(logging.INFO)
    sdk_handler.setFormatter(formatter)
    sdk_logger.addHandler(sdk_handler)
    sdk_logger.setLevel(logging.INFO)
    _SDK_LOGGING_CONFIGURED = True



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def setup_logger(
    name: str,
    level: int = logging.INFO,
    *,
    log_dir: Path | None = None,
    fmt: str = _DEFAULT_FMT,
    date_fmt: str = _DEFAULT_DATE_FMT,
    max_bytes: int = _MAX_BYTES,
    backup_count: int = _BACKUP_COUNT,
    console: bool = True,
    file: bool = True,
) -> logging.Logger:
    """Create (or retrieve) a logger with console and rotating-file handlers.

    Args:
        name: Logger name — typically ``__name__`` of the calling module.
        level: Minimum severity level (default ``logging.INFO``).
        log_dir: Directory for log files.  Defaults to ``<project>/logs/``.
        fmt: Log record format string.
        date_fmt: ``strftime`` date format for ``%(asctime)s``.
        max_bytes: Maximum bytes per log file before rotation.
        backup_count: Number of rotated backup files to keep.
        console: If ``True``, attach a ``StreamHandler`` (stderr).
        file: If ``True``, attach a ``RotatingFileHandler``.

    Returns:
        A configured :class:`logging.Logger` instance.

    Note:
        The function is **idempotent** — calling it multiple times with the
        same *name* will not duplicate handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate handlers on repeated calls.
    if logger.handlers:
        return logger

    formatter = logging.Formatter(fmt, datefmt=date_fmt)

    # --- Console handler ---------------------------------------------------
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # --- Rotating file handler ---------------------------------------------
    if file:
        resolved_log_dir = log_dir or _LOG_DIR
        _ensure_log_dir(resolved_log_dir)

        # Ensure Alpaca SDK logging is intercepted and rotated safely
        configure_sdk_logging(resolved_log_dir)

        # 1. Module-specific file handler
        safe_name = name.replace(".", "_").replace("/", "_").replace("\\", "_")
        log_path = resolved_log_dir / f"{safe_name}.log"

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # 2. Unified file handler (shared instance)
        global _UNIFIED_FILE_HANDLER
        if _UNIFIED_FILE_HANDLER is None:
            unified_path = resolved_log_dir / "trading_bot.log"
            _UNIFIED_FILE_HANDLER = RotatingFileHandler(
                unified_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            _UNIFIED_FILE_HANDLER.setLevel(logging.INFO)
            _UNIFIED_FILE_HANDLER.setFormatter(formatter)

        if _UNIFIED_FILE_HANDLER not in logger.handlers:
            logger.addHandler(_UNIFIED_FILE_HANDLER)

    # Don't propagate to root logger — we own our handlers.
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper: return a logger configured with project defaults.

    Equivalent to ``setup_logger(name)`` but reads more naturally at call
    sites::

        logger = get_logger(__name__)

    Args:
        name: Logger name — typically ``__name__``.

    Returns:
        A configured :class:`logging.Logger`.
    """
    return setup_logger(name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_log_dir(path: Path) -> None:
    """Create the log directory (and parents) if it does not exist."""
    path.mkdir(parents=True, exist_ok=True)
