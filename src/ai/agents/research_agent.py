"""Research Agent: Queries market data, regime classification, and RAG knowledge base."""

from __future__ import annotations

import logging
from typing import Any, Dict
from src.ai.rag.retriever import rag_retriever
from src.ai.tools.data_tools import get_market_regime, fetch_ticker_data_summary

logger = logging.getLogger(__name__)


class ResearchAgent:
    """Agent responsible for gathering market regime and historical context."""

    def run(self, query: str, symbol: str = "SPY") -> Dict[str, Any]:
        """Execute research pass."""
        logger.info(f"ResearchAgent evaluating query: {query} for symbol: {symbol}")

        # 1. Classify macro market regime
        regime = get_market_regime()

        # 2. Get ticker technical summary
        ticker_summary = fetch_ticker_data_summary(symbol)

        # 3. Retrieve relevant documentation / audit context
        citations = rag_retriever.get_citations(query, top_k=3)

        return {
            "regime": regime,
            "ticker_summary": ticker_summary,
            "citations": citations,
        }


research_agent = ResearchAgent()
