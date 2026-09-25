#!/usr/bin/env python3
"""Verify the frozen Rupsaa V0.2 training set and that V0.1 is untouched. Read-only.

    python scripts/v02_verify_frozen.py            # exit 1 on any failure

Recomputes everything from the frozen files themselves (not from the
candidate or the manifest's own claims): dataset SHA-256 against the
owner-approved value, counts, split sizes, cross-split leakage over the same
four relations the freeze grouped by, the corpus diversity gate, and V0.1's
protected artifacts against release/rupsaa-v0.1/checksums.sha256.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import PROJECT_ROOT, load_dataset_config  # noqa: E402
from rupsaa.dataset.dedup import group_near_duplicates  # noqa: E402
from rupsaa.dataset.diversity import analyze_with_config  # noqa: E402
from rupsaa.dataset.schema import ConversationRecord  # noqa: E402

APPROVED_SHA256 = "96e0125e39ab2754c8540a29b6d3fee0a3132d46ae72adb9a4c3c7dcd067da33"
EXPECTED = {"conversations": 1533, "assistant_replies": 2144, "train": 1380, "validation": 77, "test": 76}
SNAPSHOT = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training"
EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2"
V01_CHECKSUMS = PROJECT_ROOT / "release/rupsaa-v0.1/checksums.sha256"
V01_RELEASE_COMMIT = "4043342"  # last commit before any V0.2 training work
SPLITS = ("train", "validation", "test")
TERM_MARKER = "\n\nReference terminology:\n"
RAG_MARKER = "Retrieved context:\n"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen() -> list[dict]:
    return [json.loads(line) for line in open(SNAPSHOT / "frozen_records.jsonl", encoding="utf-8")]


def leakage(records: list[dict]) -> list[list[str]]:
    """Groups that span more than one split, joined by: near-duplicate
    user+assistant content, same terminology entry, same retrieved passage,
    same normalised first user message."""
    content = [ConversationRecord(id=r["id"], language=r["language"], category=r["category"],
                                  source_type=r["source_type"], quality_status="approved",
                                  messages=[m for m in r["messages"] if m["role"] != "system"]) for r in records]
    cfg = load_dataset_config()["near_duplicate"]
    clusters = group_near_duplicates(content, ngram_size=cfg["ngram_size"], threshold=cfg["similarity_threshold"],
                                     max_records=max(cfg["max_records_for_full_scan"], len(content)))
    parent = {r["id"]: r["id"] for r in records}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union_all(ids):
        for other in ids[1:]:
            ra, rb = find(ids[0]), find(other)
            if ra != rb:
                parent[rb] = ra

    for c in clusters:
        union_all(c)
    keyed = defaultdict(list)
    for r in records:
        system = r["messages"][0]["content"]
        if TERM_MARKER in system:
            keyed["term:" + re.search(r"^Term: (.*)$", system.split(TERM_MARKER, 1)[1], re.M).group(1).lower()].append(r["id"])
        elif RAG_MARKER in system:
            keyed["ctx:" + system.split(RAG_MARKER, 1)[1].strip()].append(r["id"])
        first_user = next(m["content"] for m in r["messages"] if m["role"] == "user")
        keyed["user:" + re.sub(r"\W+", " ", first_user.lower()).strip()].append(r["id"])
    for ids in keyed.values():
        union_all(ids)
    split_of = {r["id"]: r["split"] for r in records}
    groups = defaultdict(list)
    for r in records:
        groups[find(r["id"])].append(r["id"])
    return [g for g in groups.values() if len({split_of[i] for i in g}) > 1]


def main() -> int:
    results: dict[str, dict] = {}

    def check(name, ok, detail):
        results[name] = {"pass": bool(ok), "detail": detail}
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    actual_sha = sha(SNAPSHOT / "frozen_records.jsonl")
    check("dataset_sha256", actual_sha == APPROVED_SHA256, actual_sha)

    manifest = json.loads((SNAPSHOT / "V02_TRAINING_MANIFEST.json").read_text(encoding="utf-8"))
    check("manifest_sha_matches", manifest["dataset_sha256"] == APPROVED_SHA256, manifest["dataset_sha256"])

    records = load_frozen()
    replies = sum(1 for r in records for m in r["messages"] if m["role"] == "assistant")
    check("counts", (len(records), replies) == (EXPECTED["conversations"], EXPECTED["assistant_replies"]),
          f"{len(records)} conversations / {replies} assistant replies")

    split_counts = Counter(r["split"] for r in records)
    check("split_counts", all(split_counts[s] == EXPECTED[s] for s in SPLITS), dict(split_counts))

    # Export files: identical to the manifest and to the frozen records.
    export_ok = True
    for s in SPLITS:
        rows = [json.loads(line)["messages"] for line in open(EXPORT / f"{s}.jsonl", encoding="utf-8")]
        frozen_rows = [r["messages"] for r in records if r["split"] == s]
        export_ok &= sha(EXPORT / f"{s}.jsonl") == manifest["export_files_sha256"][s] and rows == frozen_rows
    check("export_files_match_frozen_records", export_ok, "train/validation/test.jsonl == frozen_records.jsonl per split")

    spanning = leakage(records)
    fps = {s: {json.dumps([m for m in r["messages"] if m["role"] != "system"], sort_keys=True, ensure_ascii=False)
               for r in records if r["split"] == s} for s in SPLITS}
    overlap = {f"{a}&{b}": len(fps[a] & fps[b]) for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))}
    check("no_cross_split_leakage", not spanning and not any(overlap.values()),
          f"groups spanning splits: {len(spanning)}, content overlap: {overlap}")

    diversity = analyze_with_config([ConversationRecord(id=r["id"], language=r["language"], category=r["category"],
                                                        source_type=r["source_type"], quality_status="approved",
                                                        messages=r["messages"]) for r in records])
    check("diversity_gate", diversity.training_ready and not diversity.blocking,
          f"PASS, {len(diversity.blocking)} BLOCK, {len(diversity.warnings)} WARN" if diversity.training_ready
          else [i.describe() for i in diversity.blocking])

    # V0.1: every file in its release record, except data/dataset_info.json, which V0.2 extends
    # additively — for that file, the three V0.1 entries must equal the V0.1 release commit's.
    mismatched = []
    for line in V01_CHECKSUMS.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split(maxsplit=1)
        if rel == "data/dataset_info.json":
            continue
        if not (PROJECT_ROOT / rel).is_file() or sha(PROJECT_ROOT / rel) != digest:
            mismatched.append(rel)
    check("v01_release_files_unchanged", not mismatched, mismatched or "all V0.1 release-recorded files match")

    released = json.loads(subprocess.run(["git", "show", f"{V01_RELEASE_COMMIT}:data/dataset_info.json"], cwd=PROJECT_ROOT,
                                         capture_output=True, text=True, check=True).stdout)
    current = json.loads((PROJECT_ROOT / "data/dataset_info.json").read_text(encoding="utf-8"))
    v01_keys = sorted(k for k in released if k.startswith("rupsaa_v0.1_"))
    check("v01_dataset_registrations_unchanged", v01_keys and all(current.get(k) == released[k] for k in v01_keys),
          f"{v01_keys} identical to commit {V01_RELEASE_COMMIT}")

    v01_snapshot_changes = subprocess.run(
        ["git", "status", "--porcelain", "--", "data/production/snapshots/rupsaa_v0.1_training",
         "data/production/exports/rupsaa_v0.1", "release/rupsaa-v0.1", "configs/training/llamafactory_rupsaa_v0.1.yaml",
         "configs/training/llamafactory_webui_rupsaa_v0.1.yaml", "configs/training/rupsaa_v0.1_qlora.yaml"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    check("v01_tracked_paths_clean", not v01_snapshot_changes, v01_snapshot_changes or "no working-tree changes")

    passed = all(r["pass"] for r in results.values())
    print("\nFROZEN STATE VERIFIED" if passed else "\nFROZEN STATE VERIFICATION FAILED — STOP")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
