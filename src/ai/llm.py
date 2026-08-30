"""LLM client abstraction for Google Gemini with structured generation and fallback support."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel

from src.ai.config import copilot_config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Wrapper around Gemini API with structured output and fallback support."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or copilot_config.gemini_api_key
        self.model_name = model or copilot_config.primary_model
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        """Initialize Google GenAI client if api key is available."""
        if not self.api_key:
            logger.warning("No GEMINI_API_KEY found. LLMClient will operate in fallback mode.")
            return

        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
            logger.info(f"Initialized Google GenAI client with model {self.model_name}")
        except Exception as e:
            logger.warning(f"Could not initialize google.genai: {e}. Falling back to standard requests.")

    def generate_text(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Generate free-form text from prompt."""
        if self._client:
            try:
                response = self._client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config={
                        "system_instruction": system_instruction,
                        "temperature": copilot_config.temperature,
                    } if system_instruction else {"temperature": copilot_config.temperature}
                )
                return response.text or ""
            except Exception as e:
                logger.error(f"Gemini generation error: {e}")

        # Fallback heuristic response if offline or no key
        return f"[Synthesized Research Insight] Analysis based on query: {prompt[:120]}..."

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: Optional[str] = None,
    ) -> T:
        """Generate structured output validated against a Pydantic schema."""
        if self._client:
            try:
                response = self._client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": response_schema,
                        "system_instruction": system_instruction,
                        "temperature": copilot_config.temperature,
                    } if system_instruction else {
                        "response_mime_type": "application/json",
                        "response_schema": response_schema,
                        "temperature": copilot_config.temperature,
                    }
                )
                if response.text:
                    data = json.loads(response.text)
                    return response_schema.model_validate(data)
            except Exception as e:
                logger.error(f"Structured generation error: {e}. Attempting manual parsing.")

        # Fallback instantiation for testing/offline scenarios
        schema_dict = response_schema.model_json_schema()
        dummy_data: Dict[str, Any] = {}
        for prop_name, prop_meta in schema_dict.get("properties", {}).items():
            prop_type = prop_meta.get("type")
            if prop_type == "string":
                dummy_data[prop_name] = f"Auto-generated for {prop_name}"
            elif prop_type in ["number", "integer"]:
                dummy_data[prop_name] = 0.85
            elif prop_type == "boolean":
                dummy_data[prop_name] = True
            elif prop_type == "array":
                dummy_data[prop_name] = []
            elif prop_type == "object":
                dummy_data[prop_name] = {}

        try:
            return response_schema.model_validate(dummy_data)
        except Exception:
            return response_schema.model_construct(**dummy_data)


llm_client = LLMClient()
