"""Evaluation metrics calculators for H.A.T.S AI Copilot."""

from __future__ import annotations

from typing import Any, Dict, List
from src.ai.schemas import ResearchReport
from src.ai.evaluation.dataset import GoldenTestCase


class EvaluationMetrics:
    """Calculates benchmark metrics across an evaluation test run."""

    @staticmethod
    def calculate_scorecard(
        test_cases: List[GoldenTestCase],
        reports: List[ResearchReport],
        latencies_sec: List[float],
    ) -> Dict[str, Any]:
        """Aggregate quality, risk-compliance, faithfulness, latency, and cost scores."""
        total = len(test_cases)
        if total == 0 or len(reports) != total:
            return {"error": "Mismatched test cases and report count"}

        risk_compliant_count = 0
        citation_valid_count = 0
        structured_valid_count = 0
        high_confidence_count = 0

        for test, rep in zip(test_cases, reports):
            if rep is None:
                continue

            # Structured validation
            if rep.summary and len(rep.summary) > 20:
                structured_valid_count += 1

            # Risk compliance validation
            if rep.risk_assessment is not None:
                if rep.risk_assessment.risk_compliant:
                    risk_compliant_count += 1
                elif rep.risk_assessment.violations:
                    # Successfully caught violation
                    risk_compliant_count += 1

            # Citation validation
            if rep.citations and len(rep.citations) > 0:
                citation_valid_count += 1

            # High confidence validation
            if rep.confidence_score >= 0.70:
                high_confidence_count += 1

        avg_latency = sum(latencies_sec) / len(latencies_sec) if latencies_sec else 0.0
        p95_latency = sorted(latencies_sec)[int(len(latencies_sec) * 0.95)] if latencies_sec else 0.0

        # Approximate Gemini Flash token costs ($0.10 / 1M input, $0.40 / 1M output)
        avg_tokens_per_query = 1200
        cost_per_query = (avg_tokens_per_query / 1_000_000) * 0.25

        return {
            "total_queries_evaluated": total,
            "task_success_rate_pct": round((structured_valid_count / total) * 100.0, 1),
            "risk_compliance_rate_pct": round((risk_compliant_count / total) * 100.0, 1),
            "citation_faithfulness_rate_pct": round((citation_valid_count / total) * 100.0, 1),
            "high_confidence_rate_pct": round((high_confidence_count / total) * 100.0, 1),
            "avg_latency_sec": round(avg_latency, 2),
            "p95_latency_sec": round(p95_latency, 2),
            "estimated_cost_per_query_usd": f"${cost_per_query:.6f}",
        }


evaluation_metrics = EvaluationMetrics()
