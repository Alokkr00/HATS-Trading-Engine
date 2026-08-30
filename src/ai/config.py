"""Configuration settings for H.A.T.S AI Copilot."""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from src.utils.paths import CHROMA_DB_DIR, COPILOT_DIR

load_dotenv()


class CopilotConfig(BaseModel):
    """Global configuration for the AI Copilot subsystem."""

    # LLM Settings
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", "")))
    primary_model: str = Field(default_factory=lambda: os.getenv("COPILOT_PRIMARY_MODEL", "gemini-2.0-flash"))
    reasoning_model: str = Field(default_factory=lambda: os.getenv("COPILOT_REASONING_MODEL", "gemini-2.0-flash"))
    temperature: float = Field(0.2, ge=0.0, le=1.0)
    max_output_tokens: int = Field(2048)

    # RAG / Vector Store Settings
    chroma_db_dir: Path = Field(default_factory=lambda: CHROMA_DB_DIR)
    embedding_model: str = Field("text-embedding-004")
    similarity_top_k: int = Field(4)

    # Risk & Guardrail Thresholds
    max_stress_drawdown_limit: float = Field(0.15, description="Max 15% stress drawdown allowed")
    confidence_rejection_threshold: float = Field(0.60, description="Minimum confidence score required")
    forced_citations_required: bool = Field(True)

    # Logging & Storage
    copilot_log_dir: Path = Field(default_factory=lambda: COPILOT_DIR)


copilot_config = CopilotConfig()
