"""Semantic retrieval over the vector store."""

from __future__ import annotations

from rupsaa.config import PROJECT_ROOT, load_rag_config
from rupsaa.rag.embeddings import embed_query
from rupsaa.rag.vector_store import FaissVectorStore, SearchResult


def build_vector_store() -> FaissVectorStore:
    cfg = load_rag_config()
    vs_cfg = cfg["vector_store"]
    index_dir = PROJECT_ROOT / vs_cfg["index_dir"]
    return FaissVectorStore(
        index_dir=index_dir,
        index_filename=vs_cfg["index_filename"],
        metadata_filename=vs_cfg["metadata_filename"],
        embedding_dim=cfg["embedding_dim"],
    )


def retrieve(query: str, store: FaissVectorStore, top_k: int | None = None) -> list[SearchResult]:
    cfg = load_rag_config()
    top_k = top_k or cfg["retrieval"]["top_k"]
    min_score = cfg["retrieval"]["min_score"]

    if len(store) == 0:
        return []

    query_vector = embed_query(query)
    results = store.search(query_vector, top_k)
    return [r for r in results if r.score >= min_score]
