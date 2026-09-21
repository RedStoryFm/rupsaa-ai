"""Multilingual embedding model wrapper for RAG.

Uses intfloat/multilingual-e5-small (configs/rag.yaml). E5 models require
"query: " / "passage: " prefixes on raw text to get correctly-calibrated
similarity scores — that convention is applied here so callers never have
to remember it.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from rupsaa.config import load_rag_config


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    model_id = load_rag_config()["embedding_model_id"]
    return SentenceTransformer(model_id)


def embed_passages(texts: list[str]) -> np.ndarray:
    model = get_embedding_model()
    prefixed = [f"passage: {t}" for t in texts]
    return model.encode(prefixed, normalize_embeddings=True, convert_to_numpy=True)


def embed_query(text: str) -> np.ndarray:
    model = get_embedding_model()
    return model.encode(
        f"query: {text}", normalize_embeddings=True, convert_to_numpy=True
    )
