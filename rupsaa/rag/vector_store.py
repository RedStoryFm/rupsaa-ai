"""Vector store abstraction for RAG.

A minimal interface (add / search / save / load) so the backend can be
swapped later (e.g. FAISS -> Chroma -> a hosted vector DB) without touching
retriever.py or pipeline.py. FaissVectorStore is the only implementation for
now — FAISS was chosen over Chroma for simplicity: no server process, no
extra storage-format dependency, and the corpus size here (a knowledge base
of documents, not millions of vectors) doesn't need Chroma's extra features.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from pathlib import Path

import faiss
import numpy as np


@dataclass
class ChunkMetadata:
    chunk_id: int
    source_filename: str
    text: str


@dataclass
class SearchResult:
    metadata: ChunkMetadata
    score: float


class VectorStore(ABC):
    @abstractmethod
    def add(self, vectors: np.ndarray, metadata: list[ChunkMetadata]) -> None: ...

    @abstractmethod
    def search(self, query_vector: np.ndarray, top_k: int) -> list[SearchResult]: ...

    @abstractmethod
    def save(self) -> None: ...

    @abstractmethod
    def load(self) -> bool:
        """Returns True if an existing index was found and loaded."""

    @abstractmethod
    def __len__(self) -> int: ...


class FaissVectorStore(VectorStore):
    def __init__(self, index_dir: Path, index_filename: str, metadata_filename: str, embedding_dim: int):
        self.index_dir = Path(index_dir)
        self.index_path = self.index_dir / index_filename
        self.metadata_path = self.index_dir / metadata_filename
        self.embedding_dim = embedding_dim
        # Inner product on normalized vectors == cosine similarity.
        self.index = faiss.IndexFlatIP(embedding_dim)
        self._metadata: list[ChunkMetadata] = []

    def add(self, vectors: np.ndarray, metadata: list[ChunkMetadata]) -> None:
        if len(vectors) != len(metadata):
            raise ValueError("vectors and metadata must be the same length")
        if len(vectors) == 0:
            return
        self.index.add(np.ascontiguousarray(vectors.astype("float32")))
        self._metadata.extend(metadata)

    def search(self, query_vector: np.ndarray, top_k: int) -> list[SearchResult]:
        if len(self._metadata) == 0:
            return []
        query = np.ascontiguousarray(query_vector.astype("float32")).reshape(1, -1)
        scores, indices = self.index.search(query, min(top_k, len(self._metadata)))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results.append(SearchResult(metadata=self._metadata[idx], score=float(score)))
        return results

    def save(self) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(self.index_path))
        with open(self.metadata_path, "w", encoding="utf-8") as f:
            for m in self._metadata:
                f.write(json.dumps(asdict(m), ensure_ascii=False) + "\n")

    def load(self) -> bool:
        if not self.index_path.exists() or not self.metadata_path.exists():
            return False
        self.index = faiss.read_index(str(self.index_path))
        self._metadata = []
        with open(self.metadata_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self._metadata.append(ChunkMetadata(**json.loads(line)))
        return True

    def __len__(self) -> int:
        return len(self._metadata)
