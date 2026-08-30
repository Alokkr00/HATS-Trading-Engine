"""Test suite for AI Copilot Pydantic schemas."""

import pytest
from src.ai.schemas import (
    Citation,
    TradeIdea,
    RiskAssessment,
    BacktestMetricReport,
    ResearchReport,
    ResearchQueryRequest,
    UserFeedbackRequest,
)


def test_citation_schema():
    c = Citation(
        source_id="doc_1",
        title="Risk Strategy",
        url_or_path="docs/risk_review.md",
        snippet="Portfolio stress loss cap is 15%."
    )
    assert c.source_id == "doc_1"
    assert "15%" in c.snippet


def test_trade_idea_schema():
    idea = TradeIdea(
        action="BUY",
        symbol="SPY",
        strategy="donchian",
        suggested_entry=500.0,
        stop_loss=490.0,
        take_profit=520.0,
        position_size_pct=0.05,
        rationale="Breakout above 20-day high"
    )
    assert idea.action == "BUY"
    assert idea.symbol == "SPY"
    assert idea.stop_loss == 490.0


def test_risk_assessment_schema():
    risk = RiskAssessment(
        risk_compliant=True,
        stress_drawdown_pct=6.5,
        circuit_breaker_passed=True,
        circuit_breaker_state="NORMAL",
        short_option_margin_floor_applied=True,
        violations=[]
    )
    assert risk.risk_compliant is True
    assert risk.stress_drawdown_pct == 6.5


def test_research_report_schema():
    report = ResearchReport(
        query="Analyze SPY market regime and stress test",
        summary="SPY is in a persistent bull regime with low volatility.",
        market_regime="BULL_NORMAL",
        hurst_exponent=0.62,
        trade_ideas=[],
        risk_assessment=RiskAssessment(
            risk_compliant=True,
            stress_drawdown_pct=4.2,
            circuit_breaker_passed=True
        ),
        backtest_benchmarks=[],
        citations=[],
        confidence_score=0.92
    )
    assert report.confidence_score == 0.92
    assert report.hurst_exponent == 0.62
    dump = report.model_dump()
    assert dump["market_regime"] == "BULL_NORMAL"
