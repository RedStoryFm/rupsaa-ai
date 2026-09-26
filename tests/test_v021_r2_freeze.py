"""Rupsaa V0.2.1 R2 replacement freeze + the owner's 60 dance records. No model, no tokenizer download."""

import hashlib
import json
import re
from collections import Counter

import pytest

from rupsaa.config import PROJECT_ROOT

R2 = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.1_r2"
SNAP = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2.1_r2_training"
OLD = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.1"
OWNER = PROJECT_ROOT / "data/owner/dance_knowledge_owner_60.txt"
OLD_SHA = "5e54c8f24aad837f3d037cb661806316969a169aeca0cfe1da282a1c654e5543"
frozen = pytest.mark.skipif(not (R2 / "V021_R2_TRAINING_MANIFEST.json").exists(), reason="R2 not frozen")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def manifest():
    return json.loads((R2 / "V021_R2_TRAINING_MANIFEST.json").read_text(encoding="utf-8"))


@frozen
def test_r2_files_match_manifest_and_are_read_only():
    m = manifest()
    for name, expected in m["files_sha256"].items():
        assert sha(R2 / name) == expected, name
        # immutability = SHA manifest + git tag; read-only bits are best-effort (the studio's storage resets modes)
    order = ("train.jsonl", "validation.jsonl", "test.jsonl", "corrective_holdout.jsonl", "dance_holdout.jsonl")
    assert m["dataset_sha256"] == hashlib.sha256("".join(f"{m['files_sha256'][n]}  {n}\n" for n in order).encode()).hexdigest()
    assert json.loads((SNAP / "V021_R2_TRAINING_MANIFEST.json").read_text(encoding="utf-8")) == m


@frozen
def test_r2_supersedes_the_untrained_first_freeze_which_is_untouched():
    m = manifest()
    assert m["supersedes"]["dataset_sha256"] == OLD_SHA and m["supersedes"]["trained"] is False
    old = json.loads((OLD / "V021_TRAINING_MANIFEST.json").read_text(encoding="utf-8"))
    assert old["dataset_sha256"] == OLD_SHA
    for name, expected in old["files_sha256"].items():
        assert sha(OLD / name) == expected, name  # old freeze byte-identical
    assert not (PROJECT_ROOT / "adapters/rupsaa-v0.2.1").exists()  # nothing trained


@frozen
def test_r2_composition_weighting_and_holdouts():
    m = manifest()
    row_map = [json.loads(line) for line in open(R2 / "train_row_map.jsonl", encoding="utf-8")]
    by_src = Counter(r["source"] for r in row_map)
    assert by_src == {"rupsaa_v0.2_train": 1380, "rupsaa_v0.2.1_corrective": 282, "rupsaa_v0.2.1_dance": 48}
    copies = Counter(r["id"] for r in row_map if r["source"] != "rupsaa_v0.2_train")
    assert set(copies.values()) == {2} and len(copies) == 141 + 24
    trained = set(copies)
    corr_hold = {json.loads(line)["id"] for line in open(R2 / "corrective_holdout.jsonl", encoding="utf-8")}
    dance_hold = [json.loads(line) for line in open(R2 / "dance_holdout.jsonl", encoding="utf-8")]
    assert len(corr_hold) == 21 and len(dance_hold) == 12
    assert not (corr_hold | {r["id"] for r in dance_hold}) & trained
    # held-out dances never attached in any training row
    train_rows = open(R2 / "train.jsonl", encoding="utf-8").read()
    for r in dance_hold:
        for t in {t for tr in r["runtime_trace"] for t in tr["terms_used"]}:
            name = json.loads((PROJECT_ROOT / f"knowledge/dance/{t}.json").read_text(encoding="utf-8"))["name"]
            assert f"Dance: {name}\\n" not in train_rows and f"Dance: {name}\n" not in train_rows, name
    assert all(r["source"] == "rupsaa_v0.2_train" for r in row_map if r["internal_split"] == "eval")
    assert (m["splits"]["internal_train_rows"], m["splits"]["internal_eval_rows"]) == (1624, 86)
    assert m["training"]["expected_total_steps"] == 202
    assert m["splits"]["external_validation"] == 77 and m["splits"]["external_test"] == 76


@frozen
def test_frozen_dance_knowledge_copy_matches_live_store():
    live = sorted((PROJECT_ROOT / "knowledge/dance").glob("dance-*.json"))
    snap = sorted((SNAP / "dance_knowledge").glob("dance-*.json"))
    assert len(live) == len(snap) == 60
    assert [(p.name, sha(p)) for p in live] == [(p.name, sha(p)) for p in snap]
    assert manifest()["dance_knowledge"]["owner_source_sha256"] == sha(OWNER)


def test_owner_60_dances_stored_verbatim_and_enabled():
    from rupsaa.rag.dance import FUTURE_FIELDS, DanceStore

    text = OWNER.read_text(encoding="utf-8")
    blocks = re.findall(r"^(\d+)\)\s*(.+)\nOrigin:\s*(.+)\nDescription:\s*(.+)$", text, re.M)
    assert [int(b[0]) for b in blocks] == list(range(1, 61))
    store = {d.name: d for d in DanceStore(PROJECT_ROOT / "knowledge/dance").list()}
    assert len(store) == 60 and all(d.enabled for d in store.values())
    for _, name, origin, desc in blocks:
        d = store[name.strip()]
        assert (d.origin, d.description) == (origin.strip(), desc.strip()), name
        assert not d.key_movements and not any(getattr(d, f) for f in FUTURE_FIELDS), name  # nothing invented


def test_dance_retrieval_report_passes():
    rep = json.loads((PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation/dance_retrieval_check.json")
                     .read_text(encoding="utf-8"))
    assert rep["pass"] and rep["dances_fully_passing"] == 60 and not rep["false_positives"]
