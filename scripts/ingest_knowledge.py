#!/usr/bin/env python3
"""Ingest knowledge/documents/ into the RAG vector index.

Usage:
    python scripts/ingest_knowledge.py

Re-run any time files under knowledge/documents/ are added, edited, or
removed. This never requires retraining Rupsaa (fine-tuning and RAG are
decoupled by design).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.rag.pipeline import RagPipeline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    pipeline = RagPipeline()
    num_chunks = pipeline.ingest()
    print(f"Ingested {num_chunks} chunk(s) into the RAG index.")
    print(f"Index stored at: {pipeline.store.index_dir}")


if __name__ == "__main__":
    main()
