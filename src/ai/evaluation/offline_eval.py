"""Offline Evaluation Runner for H.A.T.S AI Copilot."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict
from src.ai.agents.orchestrator import orchestrator
from src.ai.evaluation.dataset import GOLDEN_BENCHMARK_DATASET
from src.ai.evaluation.metrics import evaluation_metrics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_offline_evaluation(max_cases: int | None = None) -> Dict[str, Any]:
    """Execute the golden benchmark dataset and return evaluation results."""
    dataset = GOLDEN_BENCHMARK_DATASET[:max_cases] if max_cases else GOLDEN_BENCHMARK_DATASET
    print(f"\n===========================================================")
    print(f">> Running H.A.T.S AI Copilot Offline Evaluation ({len(dataset)} Test Cases)")
    print(f"===========================================================\n")

    reports = []
    latencies = []

    for idx, test_case in enumerate(dataset, 1):
        print(f"[{idx}/{len(dataset)}] [{test_case.category.upper()}] Query: {test_case.query[:60]}...")
        start_time = time.perf_counter()
        try:
            report = orchestrator.run(query=test_case.query, symbol=test_case.expected_symbol)
            elapsed = time.perf_counter() - start_time
            latencies.append(elapsed)
            reports.append(report)
            print(f"   -> Done in {elapsed:.2f}s | Confidence: {report.confidence_score} | Risk Pass: {report.risk_assessment.risk_compliant}")
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            latencies.append(elapsed)
            logger.error(f"Error evaluating test case {test_case.id}: {e}")
            reports.append(None)

    scorecard = evaluation_metrics.calculate_scorecard(dataset, reports, latencies)

    print(f"\n===========================================================")
    print(f">> EVALUATION SCORECARD SUMMARY")
    print(f"===========================================================")
    for k, v in scorecard.items():
        print(f"  * {k.replace('_', ' ').title()}: {v}")
    print(f"===========================================================\n")

    return scorecard


if __name__ == "__main__":
    run_offline_evaluation()
