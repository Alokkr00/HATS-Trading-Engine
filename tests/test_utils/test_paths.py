"""Unit tests for Dynamic Platform-Agnostic Directory Resolution."""

import os
from pathlib import Path
import pytest

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


def test_paths_exist_and_are_resolved():
    """Verify that all canonical project paths resolve to valid directories."""
    assert PROJECT_ROOT.exists()
    assert (PROJECT_ROOT / "pyproject.toml").exists()
    assert DATA_DIR == PROJECT_ROOT / "data"
    assert RAW_DATA_DIR == PROJECT_ROOT / "data" / "raw"
    assert EXECUTION_DIR == PROJECT_ROOT / "data" / "execution"
    assert CONFIG_DIR == PROJECT_ROOT / "config"
    assert LOGS_DIR == PROJECT_ROOT / "logs"
    assert DASHBOARD_DIR == PROJECT_ROOT / "src" / "dashboard"
    assert TEMPLATES_DIR == DASHBOARD_DIR / "templates"
    assert STATIC_DIR == DASHBOARD_DIR / "static"


def test_ensure_project_dirs_idempotent():
    """Verify that ensure_project_dirs creates all directory trees without error."""
    ensure_project_dirs()
    assert DATA_DIR.is_dir()
    assert RAW_DATA_DIR.is_dir()
    assert EXECUTION_DIR.is_dir()
    assert REPORTS_DIR.is_dir()
    assert CHARTS_DIR.is_dir()
    assert CHROMA_DB_DIR.is_dir()
    assert COPILOT_DIR.is_dir()
    assert LOGS_DIR.is_dir()
    assert CONFIG_DIR.is_dir()


def test_get_project_path_helper():
    """Verify subpath resolution relative to PROJECT_ROOT."""
    resolved = get_project_path("config", "settings.yaml")
    assert resolved == PROJECT_ROOT / "config" / "settings.yaml"
    assert resolved.is_file()
