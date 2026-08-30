"""Vector store indexing pipeline for documentation and audit records."""

from __future__ import annotations

import glob
import logging
from pathlib import Path
from typing import Any, Dict, List
import chromadb
from chromadb.config import Settings

from src.ai.config import copilot_config

logger = logging.getLogger(__name__)


class RAGIndexer:
    """Manages document chunking, embeddings, and vector indexing."""

    def __init__(self, persist_dir: Path | None = None) -> None:
        self.persist_dir = persist_dir or copilot_config.chroma_db_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name="hats_research_kb",
            metadata={"description": "H.A.T.S Quantitative Strategy Docs & Audit Records"}
        )

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """Split text into manageable chunks by paragraph or word boundary."""
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""

        for p in paragraphs:
            p_clean = p.strip()
            if not p_clean:
                continue
            if len(current_chunk) + len(p_clean) < chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + p_clean
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = p_clean

        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    def index_markdown_docs(self, docs_dir: str = "docs") -> int:
        """Scan and index all markdown files in docs/ directory."""
        doc_files = glob.glob(f"{docs_dir}/*.md") + glob.glob("README.md")
        total_chunks = 0

        for file_path in doc_files:
            try:
                path_obj = Path(file_path)
                with open(path_obj, "r", encoding="utf-8") as f:
                    content = f.read()

                chunks = self.chunk_text(content)
                for idx, chunk in enumerate(chunks):
                    doc_id = f"{path_obj.name}_{idx}"
                    self.collection.upsert(
                        ids=[doc_id],
                        documents=[chunk],
                        metadatas=[{
                            "source_file": str(path_obj.name),
                            "path": str(file_path),
                            "chunk_index": idx,
                            "type": "documentation",
                        }]
                    )
                    total_chunks += 1
            except Exception as e:
                logger.error(f"Error indexing {file_path}: {e}")

        logger.info(f"Successfully indexed {total_chunks} chunks into ChromaDB.")
        return total_chunks


rag_indexer = RAGIndexer()
