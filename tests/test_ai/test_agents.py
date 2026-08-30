"""Test suite for AI Copilot multi-agent orchestrator."""

import pytest
from src.ai.agents.research_agent import research_agent
from src.ai.agents.risk_agent import risk_agent
from src.ai.agents.critic_agent import critic_agent
from src.ai.agents.orchestrator import orchestrator
from src.ai.schemas import TradeIdea, RiskAssessment


def test_research_agent():
    res = research_agent.run(query="What is the current market regime?", symbol="SPY")
    assert "regime" in res
    assert "ticker_summary" in res
    assert "citations" in res


def test_risk_agent():
    ideas = [
        TradeIdea(
            action="BUY",
            symbol="SPY",
            strategy="donchian",
            suggested_entry=500.0,
            position_size_pct=0.05,
            rationale="Test breakout"
        )
    ]
    assessment = risk_agent.run(trade_ideas=ideas, account_equity=100000.0)
    assert isinstance(assessment, RiskAssessment)
    assert isinstance(assessment.risk_compliant, bool)
    assert assessment.stress_drawdown_pct >= 0.0


def test_critic_agent():
    risk = RiskAssessment(risk_compliant=True, stress_drawdown_pct=4.5, circuit_breaker_passed=True)
    critique = critic_agent.evaluate(
        query="Test query",
        regime_info={"regime_state": "BULL_NORMAL"},
        trade_ideas=[],
        risk_assessment=risk,
        citations=[],
    )
    assert "confidence_score" in critique
    assert 0.0 <= critique["confidence_score"] <= 1.0


def test_orchestrator_end_to_end():
    report = orchestrator.run(query="Analyze SPY regime and run risk stress test", symbol="SPY")
    assert report is not None
    assert report.query == "Analyze SPY regime and run risk stress test"
    assert report.confidence_score > 0.0
    assert report.risk_assessment is not None
    assert report.market_regime is not None
