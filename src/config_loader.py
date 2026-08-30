"""Configuration loader for the trading bot.

Reads config/settings.yaml and config/.env, exposing them as
typed Python objects.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from src.utils.paths import PROJECT_ROOT, CONFIG_DIR


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """Load settings from YAML configuration file.

    Args:
        path: Optional path to settings.yaml. Defaults to
              config/settings.yaml relative to project root.

    Returns:
        Dictionary of configuration values.

    Raises:
        FileNotFoundError: If the settings file does not exist.
    """
    settings_path = path or (CONFIG_DIR / "settings.yaml")
    if not settings_path.exists():
        raise FileNotFoundError(f"Settings file not found: {settings_path}")

    with open(settings_path, "r", encoding="utf-8") as fh:
        settings: dict[str, Any] = yaml.safe_load(fh)

    logger.info("Loaded settings from %s", settings_path)
    return settings


def load_env(path: Path | None = None) -> None:
    """Load environment variables from .env file.

    Args:
        path: Optional path to .env file. Defaults to
              config/.env relative to project root.
    """
    env_path = path or (CONFIG_DIR / ".env")
    if env_path.exists():
        load_dotenv(env_path)
        logger.info("Loaded .env from %s", env_path)
    else:
        logger.debug("No .env file found at %s — skipping", env_path)


# Convenience: load on import
_settings: dict[str, Any] | None = None
_risk_settings: dict[str, Any] | None = None


def get_settings() -> dict[str, Any]:
    """Return cached settings, loading on first call.

    Returns:
        Dictionary of configuration values.
    """
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = load_settings()
    return _settings


def load_risk_defaults(path: Path | None = None) -> dict[str, Any]:
    """Load risk parameters from risk_defaults.yaml.

    Args:
        path: Optional path to risk_defaults.yaml.

    Returns:
        Dictionary of risk parameters.
    """
    risk_path = path or (CONFIG_DIR / "risk_defaults.yaml")
    if not risk_path.exists():
        logger.warning("Risk defaults file not found at %s. Returning empty dict.", risk_path)
        return {}

    with open(risk_path, "r", encoding="utf-8") as fh:
        risk_settings: dict[str, Any] = yaml.safe_load(fh)

    logger.info("Loaded risk defaults from %s", risk_path)
    return risk_settings


def get_risk_settings() -> dict[str, Any]:
    """Return cached risk settings, loading on first call."""
    global _risk_settings
    if _risk_settings is None:
        _risk_settings = load_risk_defaults()
    return _risk_settings

