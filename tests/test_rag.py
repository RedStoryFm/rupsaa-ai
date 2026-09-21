import numpy as np
import pytest

from rupsaa.rag.chunker import chunk_text
from rupsaa.rag.vector_store import ChunkMetadata, FaissVectorStore


def test_chunk_text_keeps_short_paragraphs_together():
    text = "Para one.\n\nPara two.\n\nPara three."
    chunks = chunk_text(text, "doc.txt", chunk_size_chars=200, chunk_overlap_chars=20)
    assert len(chunks) == 1
    assert "Para one." in chunks[0].text
    assert "Para three." in chunks[0].text


def test_chunk_text_splits_oversized_paragraph_with_overlap():
    long_paragraph = "x" * 500
    chunks = chunk_text(long_paragraph, "doc.txt", chunk_size_chars=200, chunk_overlap_chars=50)
    assert len(chunks) > 1
    # consecutive chunks should overlap
    assert chunks[0].text[-50:] in long_paragraph
    for i, c in enumerate(chunks):
        assert c.chunk_id == i
        assert c.source_filename == "doc.txt"


def test_chunk_text_rejects_overlap_ge_chunk_size():
    with pytest.raises(ValueError):
        chunk_text("hello", "doc.txt", chunk_size_chars=100, chunk_overlap_chars=100)


def _make_store(tmp_path, dim=4) -> FaissVectorStore:
    return FaissVectorStore(
        index_dir=tmp_path,
        index_filename="test.index",
        metadata_filename="test_metadata.jsonl",
        embedding_dim=dim,
    )


def test_vector_store_add_and_search(tmp_path):
    store = _make_store(tmp_path)
    vectors = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0, 0.0],
        ],
        dtype="float32",
    )
    metadata = [
        ChunkMetadata(chunk_id=0, source_filename="a.txt", text="alpha"),
        ChunkMetadata(chunk_id=1, source_filename="b.txt", text="beta"),
        ChunkMetadata(chunk_id=2, source_filename="a.txt", text="alpha-ish"),
    ]
    store.add(vectors, metadata)
    assert len(store) == 3

    query = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
    results = store.search(query, top_k=2)
    assert len(results) == 2
    assert results[0].metadata.text == "alpha"
    assert results[0].score > results[1].score


def test_vector_store_save_and_load_roundtrip(tmp_path):
    store = _make_store(tmp_path)
    vectors = np.array([[1.0, 0.0, 0.0, 0.0]], dtype="float32")
    metadata = [ChunkMetadata(chunk_id=0, source_filename="a.txt", text="alpha")]
    store.add(vectors, metadata)
    store.save()

    loaded_store = _make_store(tmp_path)
    found = loaded_store.load()
    assert found is True
    assert len(loaded_store) == 1
    results = loaded_store.search(np.array([1.0, 0.0, 0.0, 0.0], dtype="float32"), top_k=1)
    assert results[0].metadata.source_filename == "a.txt"


def test_vector_store_load_returns_false_when_missing(tmp_path):
    store = _make_store(tmp_path)
    assert store.load() is False


def test_vector_store_search_on_empty_store_returns_empty(tmp_path):
    store = _make_store(tmp_path)
    results = store.search(np.array([1.0, 0.0, 0.0, 0.0], dtype="float32"), top_k=5)
    assert results == []
