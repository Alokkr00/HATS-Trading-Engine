"""Guardrails and safety policy enforcement for H.A.T.S AI Copilot."""

from __future__ import annotations

import re
from typing import Tuple
from src.ai.schemas import ResearchReport
from src.ai.config import copilot_config

# Patterns that indicate prompt injection or unsafe direct execution attempts
UNSAFE_PATTERNS = [
    r"ignore previous instructions",
    r"bypass risk",
    r"disable circuit breaker",
    r"override stress limit",
    r"send real money without confirmation",
    r"drop table",
    r"delete from orders",
]


class GuardrailEngine:
    """Validates user inputs and audits agent outputs against safety policies."""

    @staticmethod
    def validate_user_prompt(prompt: str) -> Tuple[bool, str]:
        """Check for adversarial prompt injection or prohibited commands."""
        lowered = prompt.lower()
        for pattern in UNSAFE_PATTERNS:
            if re.search(pattern, lowered):
                return False, f"Prohibited instruction detected matching pattern: {pattern}"
        return True, "Valid"

    @staticmethod
    def audit_final_report(report: ResearchReport) -> Tuple[bool, str]:
        """Enforce that reports satisfy risk and confidence thresholds."""
        # 1. Confidence score threshold check
        if report.confidence_score < copilot_config.confidence_rejection_threshold:
            return False, f"Report confidence score ({report.confidence_score}) is below minimum threshold ({copilot_config.confidence_rejection_threshold})."

        # 2. Risk check enforcement
        if not report.risk_assessment.risk_compliant and any(t.action == "BUY" for t in report.trade_ideas):
            # Check if warning is properly reflected in critic notes
            if not report.critic_notes or "failed" not in report.critic_notes.lower():
                return False, "Non-compliant trades detected without explicit risk rejection warnings."

        return True, "Audit passed"


guardrail_engine = GuardrailEngine()
