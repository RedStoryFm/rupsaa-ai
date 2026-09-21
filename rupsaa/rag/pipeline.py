"""End-to-end RAG pipeline: ingestion and query-time retrieval.

Ingestion (documents -> extraction -> chunking -> embedding -> vector store)
is intentionally decoupled from fine-tuning: adding or changing files under
knowledge/documents/ and re-running ingest_knowledge.py never requires
retraining Rupsaa (see rupsaa/model/).
"""

from __future__ import annotations

import logging

from rupsaa.config import PROJECT_ROOT, load_rag_config
from rupsaa.rag.chunker import chunk_text
from rupsaa.rag.document_loader import load_documents_from_dir
from rupsaa.rag.embeddings import embed_passages
from rupsaa.rag.retriever import build_vector_store, retrieve
from rupsaa.rag.vector_store import ChunkMetadata, FaissVectorStore

logger = logging.getLogger("rupsaa.rag.pipeline")


class RagPipeline:
    def __init__(self, store: FaissVectorStore | None = None):
        self.store = store or build_vector_store()
        self.store.load()

    def ingest(self) -> int:
        """Re-reads all documents under knowledge/documents/, re-chunks and
        re-embeds them, and rebuilds the index from scratch. Returns the
        number of chunks indexed. Idempotent — safe to re-run any time
        knowledge files change."""
        cfg = load_rag_config()
        source_dir = PROJECT_ROOT / cfg["documents"]["source_dir"]
        chunk_cfg = cfg["chunking"]

        docs = load_documents_from_dir(source_dir, cfg["documents"]["supported_extensions"])
        logger.info("Loaded %d source document(s) from %s", len(docs), source_dir)

        all_chunks = []
        for doc in docs:
            all_chunks.extend(
                chunk_text(
                    doc.text,
                    doc.source_filename,
                    chunk_cfg["chunk_size_chars"],
                    chunk_cfg["chunk_overlap_chars"],
                )
            )

        # Rebuild fresh rather than appending, so stale chunks from removed/
        # edited documents don't linger in the index.
        self.store = build_vector_store()

        if not all_chunks:
            logger.warning("No chunks to index (no documents found).")
            self.store.save()
            return 0

        texts = [c.text for c in all_chunks]
        vectors = embed_passages(texts)
        metadata = [
            ChunkMetadata(chunk_id=c.chunk_id, source_filename=c.source_filename, text=c.text)
            for c in all_chunks
        ]
        self.store.add(vectors, metadata)
        self.store.save()
        logger.info("Indexed %d chunk(s) from %d document(s).", len(all_chunks), len(docs))
        return len(all_chunks)

    def query(self, question: str, top_k: int | None = None) -> tuple[str | None, list[dict]]:
        """Returns (formatted_context_or_None, sources).

        formatted_context is None when retrieval found nothing above the
        min_score threshold — callers must NOT fabricate context in that
        case (see rupsaa/personality/system_prompt.py RAG_INSTRUCTIONS).
        sources is always a list (possibly empty) of source dicts suitable
        for exposing directly in an API response.
        """
        results = retrieve(question, self.store, top_k)
        if not results:
            return None, []

        context_blocks = []
        sources = []
        for r in results:
            context_blocks.append(f"[Source: {r.metadata.source_filename}]\n{r.metadata.text}")
            sources.append(
                {
                    "source_filename": r.metadata.source_filename,
                    "chunk_id": r.metadata.chunk_id,
                    "score": round(r.score, 4),
                }
            )
        return "\n\n---\n\n".join(context_blocks), sources
