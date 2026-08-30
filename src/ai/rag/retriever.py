"""Retrieval pipeline for querying the vector knowledge base."""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from src.ai.rag.indexer import rag_indexer
from src.ai.schemas import Citation
from src.ai.config import copilot_config

logger = logging.getLogger(__name__)


class RAGRetriever:
    """Queries vector store and formats retrieved chunks with citations."""

    def __init__(self, indexer=None) -> None:
        self.indexer = indexer or rag_indexer

    def retrieve(self, query: str, top_k: int | None = None) -> List[Dict[str, Any]]:
        """Retrieve most relevant context chunks for a query string."""
        k = top_k or copilot_config.similarity_top_k
        try:
            # Ensure index has documents
            if self.indexer.collection.count() == 0:
                self.indexer.index_markdown_docs()

            results = self.indexer.collection.query(
                query_texts=[query],
                n_results=min(k, max(1, self.indexer.collection.count()))
            )

            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            ids = results.get("ids", [[]])[0]

            retrieved = []
            for doc_id, doc_text, meta in zip(ids, docs, metas):
                retrieved.append({
                    "id": doc_id,
                    "text": doc_text,
                    "metadata": meta,
                })
            return retrieved
        except Exception as e:
            logger.error(f"Error querying vector retriever: {e}")
            return []

    def get_citations(self, query: str, top_k: int | None = None) -> List[Citation]:
        """Retrieve context and format as Pydantic Citation models."""
        chunks = self.retrieve(query, top_k)
        citations = []
        for c in chunks:
            meta = c.get("metadata", {})
            citations.append(Citation(
                source_id=c.get("id", "kb_doc"),
                title=meta.get("source_file", "Documentation"),
                url_or_path=meta.get("path", "docs/"),
                snippet=c.get("text", "")[:240] + "..."
            ))
        return citations


rag_retriever = RAGRetriever()
