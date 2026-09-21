"""Simple character-based chunking with overlap.

Character-based (not token-based) chunking keeps this dependency-free and
predictable across languages/scripts, including Bengali, where token counts
per character vary a lot by tokenizer. configs/rag.yaml controls chunk size
and overlap.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    chunk_id: int
    source_filename: str


def chunk_text(
    text: str,
    source_filename: str,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> list[Chunk]:
    if chunk_overlap_chars >= chunk_size_chars:
        raise ValueError("chunk_overlap_chars must be smaller than chunk_size_chars")

    # Prefer splitting on paragraph boundaries so chunks stay coherent;
    # fall back to hard character slicing for long boundary-free stretches.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[Chunk] = []
    buffer = ""
    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) <= chunk_size_chars:
            buffer = candidate
            continue

        if buffer:
            chunks.append(buffer)
        if len(paragraph) <= chunk_size_chars:
            buffer = paragraph
        else:
            # Hard-slice an oversized paragraph.
            start = 0
            while start < len(paragraph):
                end = start + chunk_size_chars
                chunks.append(paragraph[start:end])
                start = end - chunk_overlap_chars
            buffer = ""

    if buffer:
        chunks.append(buffer)

    return [
        Chunk(text=c, chunk_id=i, source_filename=source_filename)
        for i, c in enumerate(chunks)
    ]
