"""Exact and near-duplicate conversation detection.

Exact duplicates: hash of normalized (role, content) pairs — catches
copy-pasted or re-imported conversations regardless of metadata.

Near duplicates: character n-gram Jaccard similarity over the full
conversation text. This is a lightweight, dependency-free, script-agnostic
choice (works the same for Bengali script, Banglish, and English without
needing a language-specific tokenizer or loading an embedding model) —
deliberately not semantic similarity. It is O(n^2) in the number of
records, so dataset_audit.py applies a length pre-filter and a hard record
count cap (configs/dataset_production.yaml near_duplicate.max_records_for_full_scan)
rather than silently taking a very long time on a large dataset. Real
semantic near-dup detection could later reuse the multilingual-e5 embedding
model already used for RAG (rupsaa/rag/embeddings.py) if lexical matching
proves insufficient — not needed at current dataset scale.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from rupsaa.dataset.normalize import normalize_text
from rupsaa.dataset.schema import ConversationRecord


def conversation_text(record: ConversationRecord) -> str:
    return "\n".join(f"{m['role']}: {normalize_text(m['content'])}" for m in record.messages)


def fingerprint(record: ConversationRecord) -> str:
    text = conversation_text(record)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_exact_duplicates(records: list[ConversationRecord]) -> list[tuple[str, str]]:
    """Returns (later_id, earlier_id) pairs — later_id is the duplicate of
    the earlier-seen earlier_id."""
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str]] = []
    for record in records:
        fp = fingerprint(record)
        if fp in seen:
            duplicates.append((record.id, seen[fp]))
        else:
            seen[fp] = record.id
    return duplicates


def char_ngrams(text: str, n: int) -> set[str]:
    text = text.lower()
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


@dataclass
class NearDuplicatePair:
    id_a: str
    id_b: str
    similarity: float


def find_near_duplicates(
    records: list[ConversationRecord],
    ngram_size: int = 5,
    threshold: float = 0.85,
    max_records: int = 4000,
) -> list[NearDuplicatePair]:
    if len(records) > max_records:
        raise ValueError(
            f"{len(records)} records exceeds max_records={max_records} for a full "
            "pairwise near-duplicate scan. Narrow with --category, or raise "
            "near_duplicate.max_records_for_full_scan in configs/dataset_production.yaml "
            "if you accept the slower runtime."
        )

    texts = [conversation_text(r) for r in records]
    shingles = [char_ngrams(t, ngram_size) for t in texts]
    lengths = [len(t) for t in texts]

    pairs: list[NearDuplicatePair] = []
    n = len(records)
    for i in range(n):
        for j in range(i + 1, n):
            # Cheap pre-filter: texts with very different lengths cannot
            # plausibly reach a high Jaccard similarity — skip the set
            # intersection work entirely for those pairs.
            len_i, len_j = lengths[i], lengths[j]
            if len_i == 0 or len_j == 0:
                continue
            if min(len_i, len_j) / max(len_i, len_j) < threshold * 0.5:
                continue
            similarity = jaccard_similarity(shingles[i], shingles[j])
            if similarity >= threshold:
                pairs.append(NearDuplicatePair(id_a=records[i].id, id_b=records[j].id, similarity=round(similarity, 4)))
    return pairs


def group_near_duplicates(
    records: list[ConversationRecord],
    ngram_size: int = 5,
    threshold: float = 0.85,
    max_records: int = 4000,
) -> list[list[str]]:
    """Clusters records into groups that are mutually near-duplicate-linked
    (via find_near_duplicates + union-find), so a train/val/test splitter
    can keep each whole cluster on one side of the split instead of leaking
    near-identical variants across train and validation/test.

    Returns a list of id-groups; every record id in `records` appears in
    exactly one group (singletons for records with no near-duplicate).
    """
    pairs = find_near_duplicates(records, ngram_size=ngram_size, threshold=threshold, max_records=max_records)

    parent: dict[str, str] = {r.id: r.id for r in records}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for pair in pairs:
        union(pair.id_a, pair.id_b)

    clusters: dict[str, list[str]] = {}
    for r in records:
        root = find(r.id)
        clusters.setdefault(root, []).append(r.id)
    return list(clusters.values())
