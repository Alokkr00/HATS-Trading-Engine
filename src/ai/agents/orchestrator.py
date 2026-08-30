"""LangGraph State Machine Orchestrator for H.A.T.S AI Copilot."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TypedDict
from langgraph.graph import StateGraph, END

from src.ai.agents.research_agent import research_agent
from src.ai.agents.quant_agent import quant_agent
from src.ai.agents.risk_agent import risk_agent
from src.ai.agents.critic_agent import critic_agent
from src.ai.llm import llm_client
from src.ai.schemas import Citation, ResearchReport, RiskAssessment, TradeIdea, BacktestMetricReport

logger = logging.getLogger(__name__)


class CopilotState(TypedDict):
    """State object passed between agent nodes in the LangGraph."""
    query: str
    symbol: str
    regime_info: Dict[str, Any]
    ticker_summary: Dict[str, Any]
    citations: List[Citation]
    trade_ideas: List[TradeIdea]
    backtests: List[BacktestMetricReport]
    risk_assessment: Optional[RiskAssessment]
    confidence_score: float
    critic_notes: str
    summary_text: str
    final_report: Optional[ResearchReport]


def research_node(state: CopilotState) -> Dict[str, Any]:
    """Node 1: Gather market data, regime, and knowledge citations."""
    query = state.get("query", "")
    symbol = state.get("symbol", "SPY")
    res = research_agent.run(query=query, symbol=symbol)
    return {
        "regime_info": res.get("regime", {}),
        "ticker_summary": res.get("ticker_summary", {}),
        "citations": res.get("citations", []),
    }


def quant_node(state: CopilotState) -> Dict[str, Any]:
    """Node 2: Formulate quantitative trade setups and run backtest."""
    query = state.get("query", "")
    symbol = state.get("symbol", "SPY")
    regime = state.get("regime_info", {})
    ticker = state.get("ticker_summary", {})
    res = quant_agent.run(query=query, symbol=symbol, regime_info=regime, ticker_summary=ticker)
    return {
        "trade_ideas": res.get("trade_ideas", []),
        "backtests": res.get("backtests", []),
    }


def risk_node(state: CopilotState) -> Dict[str, Any]:
    """Node 3: Execute deterministic 15-scenario stress grid and circuit breaker checks."""
    trade_ideas = state.get("trade_ideas", [])
    assessment = risk_agent.run(trade_ideas=trade_ideas)
    return {
        "risk_assessment": assessment,
    }


def critic_node(state: CopilotState) -> Dict[str, Any]:
    """Node 4: Audit groundedness, citations, and risk constraints."""
    query = state.get("query", "")
    regime = state.get("regime_info", {})
    trade_ideas = state.get("trade_ideas", [])
    risk_assessment = state.get("risk_assessment") or RiskAssessment(
        risk_compliant=True, stress_drawdown_pct=0.0, circuit_breaker_passed=True
    )
    citations = state.get("citations", [])

    critique = critic_agent.evaluate(
        query=query,
        regime_info=regime,
        trade_ideas=trade_ideas,
        risk_assessment=risk_assessment,
        citations=citations,
    )
    return {
        "confidence_score": critique.get("confidence_score", 0.85),
        "critic_notes": critique.get("critic_notes", ""),
    }


def synthesizer_node(state: CopilotState) -> Dict[str, Any]:
    """Node 5: Synthesize executive summary and compile final ResearchReport."""
    query = state.get("query", "")
    regime = state.get("regime_info", {})
    ticker = state.get("ticker_summary", {})
    risk = state.get("risk_assessment") or RiskAssessment(
        risk_compliant=True, stress_drawdown_pct=0.0, circuit_breaker_passed=True
    )
    trade_ideas = state.get("trade_ideas", [])
    backtests = state.get("backtests", [])
    citations = state.get("citations", [])
    confidence = state.get("confidence_score", 0.85)
    critic_notes = state.get("critic_notes", "")

    # Generate LLM synthesis
    prompt = f"""
    You are the Lead Quantitative Research Analyst at H.A.T.S.
    Summarize the following systematic research findings for the user query: "{query}".

    Market Context:
    - Symbol: {state.get('symbol')} (Latest Close: ${ticker.get('latest_close', 'N/A')})
    - Macro Regime: {regime.get('regime_state')} (Hurst: {regime.get('hurst_exponent')})
    - Risk Compliance: {'PASSED' if risk.risk_compliant else 'FLAGGED/REJECTED'} (Stress Drawdown: {risk.stress_drawdown_pct}%)
    - Trade Setups: {len(trade_ideas)} proposed
    - Backtest Results: {len(backtests)} verified

    Provide a concise, professional, grounded executive summary (2-3 paragraphs).
    """

    summary_text = llm_client.generate_text(prompt=prompt)

    report = ResearchReport(
        query=query,
        summary=summary_text,
        market_regime=regime.get("regime_state", "BULL_NORMAL"),
        hurst_exponent=regime.get("hurst_exponent"),
        trade_ideas=trade_ideas,
        risk_assessment=risk,
        backtest_benchmarks=backtests,
        citations=citations,
        confidence_score=confidence,
        critic_notes=critic_notes,
    )

    return {
        "summary_text": summary_text,
        "final_report": report,
    }


class CopilotOrchestrator:
    """Orchestrates multi-agent execution pipeline via LangGraph."""

    def __init__(self) -> None:
        self.workflow = StateGraph(CopilotState)

        # Register nodes
        self.workflow.add_node("research", research_node)
        self.workflow.add_node("quant", quant_node)
        self.workflow.add_node("risk", risk_node)
        self.workflow.add_node("critic", critic_node)
        self.workflow.add_node("synthesizer", synthesizer_node)

        # Set entry point & sequential edges
        self.workflow.set_entry_point("research")
        self.workflow.add_edge("research", "quant")
        self.workflow.add_edge("quant", "risk")
        self.workflow.add_edge("risk", "critic")
        self.workflow.add_edge("critic", "synthesizer")
        self.workflow.add_edge("synthesizer", END)

        self.app = self.workflow.compile()

    def run(self, query: str, symbol: str = "SPY") -> ResearchReport:
        """Run the full research pipeline on a user query."""
        initial_state: CopilotState = {
            "query": query,
            "symbol": symbol,
            "regime_info": {},
            "ticker_summary": {},
            "citations": [],
            "trade_ideas": [],
            "backtests": [],
            "risk_assessment": None,
            "confidence_score": 0.0,
            "critic_notes": "",
            "summary_text": "",
            "final_report": None,
        }

        output_state = self.app.invoke(initial_state)
        return output_state.get("final_report")


orchestrator = CopilotOrchestrator()
