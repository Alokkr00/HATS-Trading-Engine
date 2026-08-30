"""Centralized Dynamic Platform-Agnostic Directory Resolution for H.A.T.S.

Provides robust, cross-platform resolution of all project paths across Windows,
Linux (Render, Ubuntu CI, Docker), and macOS, eliminating hardcoded strings and
relative path cwd dependency issues.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _find_project_root() -> Path:
    """Dynamically locate the project root directory.

    Searches upward from this file's location for standard project anchors
    (e.g., 'pyproject.toml', '.git', 'requirements.txt'), falling back to
    two levels up if anchors are not found.
    """
    # Override via environment variable if explicitly specified
    env_root = os.getenv("HATS_PROJECT_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.exists():
            return p

    current = Path(__file__).resolve().parent
    # Ascend up the directory tree
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists() or (parent / "requirements.txt").exists():
            return parent

    # Default fallback: src/utils/paths.py -> parents[2] is project root
    return Path(__file__).resolve().parents[2]


# -----------------------------------------------------------------------------
# Canonical Directory Anchors
# -----------------------------------------------------------------------------
PROJECT_ROOT: Path = _find_project_root()

# Core Data Paths
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DATA_DIR: Path = DATA_DIR / "raw"
EXECUTION_DIR: Path = DATA_DIR / "execution"
REPORTS_DIR: Path = DATA_DIR / "reports"
CHARTS_DIR: Path = REPORTS_DIR / "charts"
CHROMA_DB_DIR: Path = DATA_DIR / "chroma_db"
COPILOT_DIR: Path = DATA_DIR / "copilot"

# Logs & Config Paths
LOGS_DIR: Path = PROJECT_ROOT / "logs"
CONFIG_DIR: Path = PROJECT_ROOT / "config"

# Dashboard & Web Assets
SRC_DIR: Path = PROJECT_ROOT / "src"
DASHBOARD_DIR: Path = SRC_DIR / "dashboard"
TEMPLATES_DIR: Path = DASHBOARD_DIR / "templates"
STATIC_DIR: Path = DASHBOARD_DIR / "static"

# Canonical File Paths
DB_PATH: Path = EXECUTION_DIR / "trading_bot.db"
CIRCUIT_BREAKER_PATH: Path = EXECUTION_DIR / "circuit_breaker_state.json"
ENGINE_STATUS_PATH: Path = EXECUTION_DIR / "engine_status.json"
SECTOR_CACHE_PATH: Path = EXECUTION_DIR / "sector_cache.json"
OMS_STATE_PATH: Path = EXECUTION_DIR / "oms_state.json"


def ensure_project_dirs() -> None:
    """Idempotently create all required project directories across platforms."""
    dirs_to_create = [
        DATA_DIR,
        RAW_DATA_DIR,
        EXECUTION_DIR,
        REPORTS_DIR,
        CHARTS_DIR,
        CHROMA_DB_DIR,
        COPILOT_DIR,
        LOGS_DIR,
        CONFIG_DIR,
        TEMPLATES_DIR,
        STATIC_DIR,
    ]
    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)


def get_project_path(*subpaths: str) -> Path:
    """Resolve an arbitrary relative subpath against the dynamic PROJECT_ROOT.

    Args:
        *subpaths: Directory or file segments relative to PROJECT_ROOT.

    Returns:
        Fully resolved Path object.
    """
    return PROJECT_ROOT.joinpath(*subpaths).resolve()


# Auto-initialize core directories upon module import
ensure_project_dirs()
