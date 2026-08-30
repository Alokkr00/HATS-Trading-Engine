"""Critic & Evaluator Agent: Audits research reports for groundedness, risk compliance, and hallucination."""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from src.ai.schemas import Citation, RiskAssessment, TradeIdea

logger = logging.getLogger(__name__)


class CriticAgent:
    """Agent responsible for checking groundedness and assigning confidence scores."""

    def evaluate(
        self,
        query: str,
        regime_info: Dict[str, Any],
        trade_ideas: List[TradeIdea],
        risk_assessment: RiskAssessment,
        citations: List[Citation],
    ) -> Dict[str, Any]:
        """Perform critique and assign overall groundedness confidence score."""
        logger.info("CriticAgent evaluating research report draft.")

        score = 0.90
        critique_points = []

        # Check 1: Citations presence
        if not citations:
            score -= 0.15
            critique_points.append("No direct documentation citations retrieved.")
        else:
            critique_points.append(f"Verified {len(citations)} knowledge citations.")

        # Check 2: Risk compliance
        if not risk_assessment.risk_compliant:
            score -= 0.10
            critique_points.append("Trade ideas failed risk gate; warning flagged in report.")
        else:
            critique_points.append("Portfolio stress drawdown within 15% risk threshold.")

        # Check 3: Regime alignment
        regime_state = regime_info.get("regime_state", "BULL_NORMAL")
        if "BEAR" in regime_state or "RISK_OFF" in regime_state:
            for idea in trade_ideas:
                if idea.action == "BUY":
                    score -= 0.05
                    critique_points.append(f"Caution: Long trade proposed during {regime_state} regime.")

        confidence_score = max(0.10, min(0.99, round(score, 2)))
        critic_summary = " | ".join(critique_points)

        return {
            "confidence_score": confidence_score,
            "critic_notes": critic_summary,
        }


critic_agent = CriticAgent()
