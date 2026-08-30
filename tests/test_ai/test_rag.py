"""Test suite for RAG vector indexer and retriever."""

import pytest
from pathlib import Path
from src.ai.rag.indexer import RAGIndexer
from src.ai.rag.retriever import RAGRetriever


def test_rag_chunking():
    indexer = RAGIndexer(persist_dir=Path("data/test_chroma"))
    text = "Paragraph 1 is about risk management.\n\nParagraph 2 is about backtesting.\n\nParagraph 3 is about execution."
    chunks = indexer.chunk_text(text, chunk_size=50)
    assert len(chunks) >= 2


def test_rag_indexing_and_retrieval():
    indexer = RAGIndexer(persist_dir=Path("data/test_chroma"))
    count = indexer.index_markdown_docs(docs_dir="docs")
    assert count > 0

    retriever = RAGRetriever(indexer=indexer)
    results = retriever.retrieve("stress test margin grid", top_k=2)
    assert len(results) > 0
    assert "text" in results[0]
