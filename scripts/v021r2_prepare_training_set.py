#!/usr/bin/env python3
"""Freeze Rupsaa V0.2.1 R2 (replacement pre-training freeze) and write its LLaMA-Factory export — never trains.

    python scripts/v021r2_prepare_training_set.py --dry-run   # plan + checks, writes nothing
    python scripts/v021r2_prepare_training_set.py             # freeze (needs FREEZE_AUTHORIZATION_R2.json)

R2 supersedes the never-trained V0.2.1 freeze (dataset sha 5e54c8f2…4e5543, tag rupsaa-v0.2.1-training),
which stays on disk untouched. R2 = the same corrective data + the owner's dance knowledge work:

  train.jsonl          = frozen V0.2 train (1380, unchanged)
                         + corrective TRAIN records x2 (the same 141 as the first freeze)
                         + dance TRAIN records x2 (24 hand-written, grounded in the owner's 60 records)
  validation / test    = frozen V0.2 validation / test, byte-identical (never trained)
  corrective_holdout   = the same 21 corrective held-out cases (never trained)
  dance_holdout        = 12 dance generalisation cases on dances absent from training (never trained)

Dance FACTS stay in RAG (knowledge/dance/, 60 owner records, hashed into the manifest); the 24 dance
rows only teach how to answer from a retrieved entry. Internal-eval placement is the same as the first
freeze (scripts/v021_prepare_training_set.py): the seed-42 5% eval positions hold only single-copy
frozen V0.2 rows, so no duplicated corrective/dance row is in both train and eval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from scripts.v021_prepare_training_set import (  # noqa: E402
    BATCH, EPOCHS, GRAD_ACC, SEED, UPSAMPLE, V02_EXPORT, V02_MANIFEST, V02_SNAPSHOT, VAL_SIZE,
    build_rows, expected_steps, holdout_ids, make_readonly, run_gate, sha256,
)

CORR_DIR = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.1"
RECORDS = CORR_DIR / "corrective_records.jsonl"
DANCE_TRAIN = CORR_DIR / "dance_records.jsonl"
DANCE_HOLDOUT = CORR_DIR / "dance_holdout_records.jsonl"
SOURCES = [CORR_DIR / "source_conversations.py", CORR_DIR / "dance_conversations.py", CORR_DIR / "REVIEW_LOG.json"]
AUTH = CORR_DIR / "FREEZE_AUTHORIZATION_R2.json"
DANCE_DIR = PROJECT_ROOT / "knowledge/dance"
OWNER_DANCE_SOURCE = PROJECT_ROOT / "data/owner/dance_knowledge_owner_60.txt"
REPORTS = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation"
OLD_EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.1"
OUT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.1_r2"
SNAPSHOT = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2.1_r2_training"
MANIFEST_NAME = "V021_R2_TRAINING_MANIFEST.json"
OLD_SHA = "5e54c8f24aad837f3d037cb661806316969a169aeca0cfe1da282a1c654e5543"
DATASET = "rupsaa_v0.2.1_r2"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def dance_knowledge_sha() -> tuple[str, int]:
    files = sorted(DANCE_DIR.glob("dance-*.json"))
    h = hashlib.sha256("".join(f"{sha256(f)}  {f.name}\n" for f in files).encode()).hexdigest()
    return h, len(files)


def inputs_sha() -> str:
    parts = [RECORDS, DANCE_TRAIN, DANCE_HOLDOUT, OWNER_DANCE_SOURCE]
    return hashlib.sha256("".join(f"{sha256(p)}  {p.name}\n" for p in parts).encode()).hexdigest() + ":" + dance_knowledge_sha()[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    v02_manifest = json.loads(V02_MANIFEST.read_text(encoding="utf-8"))
    for split in ("train", "validation", "test"):
        if sha256(V02_EXPORT / f"{split}.jsonl") != v02_manifest["export_files_sha256"][split]:
            sys.exit(f"frozen V0.2 {split}.jsonl does not match its manifest — refusing")
    old_manifest = json.loads((OLD_EXPORT / "V021_TRAINING_MANIFEST.json").read_text(encoding="utf-8"))
    if old_manifest["dataset_sha256"] != OLD_SHA:
        sys.exit("the superseded V0.2.1 freeze is not the expected one — refusing")

    # train-as-serve: every record is exactly what the runtime (with the live dance store) builds today
    from scripts.v021_build_corrective import DANCE_HOLDOUT_OUT, DANCE_OUT, OUT as CORR_OUT, build_all
    outputs, errors = build_all()
    for path, recs in ((CORR_OUT, outputs[CORR_OUT]), (DANCE_OUT, outputs[DANCE_OUT]), (DANCE_HOLDOUT_OUT, outputs[DANCE_HOLDOUT_OUT])):
        if errors or [r["messages"] for r in recs] != [r["messages"] for r in load(path)]:
            sys.exit(f"{path.name} is not what the runtime rebuilds — run scripts/v021_build_corrective.py")
    if [r["messages"] for r in load(RECORDS)] != [r["messages"] for r in load(OLD_EXPORT.parent.parent / "snapshots/rupsaa_v0.2.1_training/corrective_records.jsonl")]:
        sys.exit("corrective records differ from the reviewed first-freeze snapshot — refusing")
    run_gate("v021_corrective_checks.py")
    if not json.loads((REPORTS / "corrective_checks.json").read_text(encoding="utf-8"))["all_gates_pass"]:
        sys.exit("corpus gates fail")
    run_gate("v021_leakage_check.py")
    run_gate("v021_dance_retrieval_check.py")
    kb_sha, kb_n = dance_knowledge_sha()
    if kb_n != 60:
        sys.exit(f"knowledge/dance holds {kb_n} records, expected 60")

    corr = load(RECORDS)
    hold_ids = holdout_ids(corr)
    corr_train = [r for r in corr if r["id"] not in hold_ids]
    corr_hold = [r for r in corr if r["id"] in hold_ids]
    dance_train, dance_hold = load(DANCE_TRAIN), load(DANCE_HOLDOUT)
    v02_train = open(V02_EXPORT / "train.jsonl", encoding="utf-8").readlines()
    rows, row_map, split_info = build_rows(v02_train, corr_train + dance_train)
    dance_train_ids = {r["id"] for r in dance_train}
    for m in row_map:
        if m.get("id") in dance_train_ids:
            m["source"] = "rupsaa_v0.2.1_dance"
    per_epoch, total = expected_steps(split_info["internal_train_rows"])
    plan = {"v02_train_rows": len(v02_train), "corrective_train_records": len(corr_train), "dance_train_records": len(dance_train),
            "upsample": UPSAMPLE, "train_rows": len(rows),
            "weighted_corrective_rows": UPSAMPLE * len(corr_train), "weighted_dance_rows": UPSAMPLE * len(dance_train),
            "corrective_and_dance_share_of_rows": round(UPSAMPLE * (len(corr_train) + len(dance_train)) / len(rows), 3),
            **split_info, "expected_steps_per_epoch": per_epoch, "expected_total_steps": total,
            "corrective_holdout": len(corr_hold), "dance_holdout": len(dance_hold), "dance_knowledge_records": kb_n}
    print(json.dumps(plan, indent=1))
    if split_info["corrective_rows_in_internal_eval"] or any(m["internal_split"] == "eval" and m["source"] != "rupsaa_v0.2_train" for m in row_map):
        sys.exit("a corrective/dance row landed in the internal eval slice — refusing")
    if args.dry_run:
        print("dry run: nothing written")
        return

    if not AUTH.exists():
        sys.exit(f"No R2 freeze authorization ({AUTH.relative_to(PROJECT_ROOT)}).")
    auth = json.loads(AUTH.read_text(encoding="utf-8"))
    if not auth.get("authorized") or auth.get("inputs_sha256") != inputs_sha():
        sys.exit("R2 freeze authorization missing, not authorized, or for different inputs.")
    if OUT.exists() or SNAPSHOT.exists():
        sys.exit("the R2 freeze already exists — a freeze is never overwritten.")

    SNAPSHOT.mkdir(parents=True)
    for f in (RECORDS, DANCE_TRAIN, DANCE_HOLDOUT, *SOURCES, AUTH, OWNER_DANCE_SOURCE):
        shutil.copy2(f, SNAPSHOT / f.name)
    shutil.copytree(DANCE_DIR, SNAPSHOT / "dance_knowledge")
    OUT.mkdir(parents=True)
    (OUT / "train.jsonl").write_text("".join(rows), encoding="utf-8")
    for split in ("validation", "test"):
        shutil.copyfile(V02_EXPORT / f"{split}.jsonl", OUT / f"{split}.jsonl")
    (OUT / "corrective_holdout.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in corr_hold), encoding="utf-8")
    (OUT / "dance_holdout.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in dance_hold), encoding="utf-8")
    (OUT / "train_row_map.jsonl").write_text("".join(json.dumps(m) + "\n" for m in row_map), encoding="utf-8")
    fmt = json.loads((V02_EXPORT / "dataset_info.json").read_text(encoding="utf-8"))["rupsaa_v0.2_train"]
    info = {f"{DATASET}_{s}": {**fmt, "file_name": f"{s}.jsonl"}
            for s in ("train", "validation", "test", "corrective_holdout", "dance_holdout")}
    (OUT / "dataset_info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")

    files = {p.name: sha256(p) for p in sorted(OUT.glob("*.jsonl")) + [OUT / "dataset_info.json"]}
    order = ("train.jsonl", "validation.jsonl", "test.jsonl", "corrective_holdout.jsonl", "dance_holdout.jsonl")
    dataset_sha = hashlib.sha256("".join(f"{files[n]}  {n}\n" for n in order).encode()).hexdigest()
    frozen = load(V02_SNAPSHOT / "frozen_records.jsonl")
    base_train = [r for r in frozen if r["split"] == "train"]
    n_replies = lambda recs: sum(1 for r in recs for m in r["messages"] if m["role"] == "assistant")  # noqa: E731
    from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout.strip()
    manifest = {
        "name": DATASET, "status": "frozen", "created_at": datetime.now(timezone.utc).isoformat(), "git_head_at_freeze": git,
        "dataset_sha256": dataset_sha,
        "dataset_sha256_definition": "sha256 of the lines '<sha256>  <file>\\n' for " + ", ".join(order) + " (in that order)",
        "files_sha256": files,
        "snapshot_files_sha256": {p.name: sha256(p) for p in sorted(SNAPSHOT.iterdir()) if p.is_file()},
        "supersedes": {"dataset": "rupsaa_v0.2.1", "dataset_sha256": OLD_SHA, "tag": "rupsaa-v0.2.1-training",
                       "export": str(OLD_EXPORT.relative_to(PROJECT_ROOT)), "trained": False,
                       "reason": "owner added Dance Knowledge to the V0.2.1 cycle before any training; the old freeze "
                                 "stays on disk unmodified and must not be trained"},
        "parent_dataset": {"name": "rupsaa_v0.2", "dataset_sha256": v02_manifest["dataset_sha256"],
                           "export_files_sha256": v02_manifest["export_files_sha256"], "modified": False},
        "prompt_version": "v0.2", "system_prompt_sha256": hashlib.sha256(V02_SYSTEM_PROMPT.encode()).hexdigest(),
        "dance_knowledge": {"records": kb_n, "sha256": kb_sha, "dir": "knowledge/dance",
                            "owner_source": str(OWNER_DANCE_SOURCE.relative_to(PROJECT_ROOT)),
                            "owner_source_sha256": sha256(OWNER_DANCE_SOURCE), "snapshot_copy": "dance_knowledge/",
                            "in_lora": "no — facts are served by RAG; 24 training rows teach answer behaviour"},
        "conversations": {"base_v02_train_unique": len(base_train), "corrective_train_unique": len(corr_train),
                          "dance_train_unique": len(dance_train), "corrective_holdout": len(corr_hold),
                          "dance_holdout": len(dance_hold),
                          "unique_training_conversations": len(base_train) + len(corr_train) + len(dance_train)},
        "assistant_replies": {"base_v02_train": n_replies(base_train), "corrective_train_unique": n_replies(corr_train),
                              "dance_train_unique": n_replies(dance_train),
                              "training_total_weighted": n_replies(base_train) + UPSAMPLE * (n_replies(corr_train) + n_replies(dance_train))},
        "languages": {"base_v02_train": dict(Counter(r["language"] for r in base_train)),
                      "corrective_train_final_reply": dict(Counter(r["language"] for r in corr_train)),
                      "dance_train_final_reply": dict(Counter(r["language"] for r in dance_train)),
                      "corrective_holdout_final_reply": dict(Counter(r["language"] for r in corr_hold)),
                      "dance_holdout_final_reply": dict(Counter(r["language"] for r in dance_hold))},
        "sources": {"base_v02_train": dict(Counter(r.get("source_type", "?") for r in base_train)),
                    "corrective": dict(Counter(r["source_type"] for r in corr)),
                    "dance": dict(Counter(r["source_type"] for r in dance_train + dance_hold))},
        "weighting": {"method": "duplicate rows", "corrective_train_copies": UPSAMPLE, "dance_train_copies": UPSAMPLE,
                      "base_copies": 1, "share_of_train_rows": plan["corrective_and_dance_share_of_rows"],
                      "holdouts_duplicated": False, "row_map": "train_row_map.jsonl",
                      "justification": "same x2 as the first freeze: dance rows are behaviour examples like the corrective "
                                       "ones; 48 rows (2.8%) teach the format without making the 60 facts a LoRA target",
                      "internal_eval_placement": f"datasets.train_test_split(test_size={VAL_SIZE}, seed={SEED}) positions hold "
                                                 "only single-copy frozen V0.2 rows"},
        "splits": {"train_file_rows": len(rows), "internal_train_rows": split_info["internal_train_rows"],
                   "internal_eval_rows": split_info["internal_eval_rows"],
                   "internal_eval_rows_shared_with_v02_internal_eval": split_info["internal_eval_from_v02_internal_eval"],
                   "corrective_or_dance_rows_in_internal_eval": 0,
                   "external_validation": sum(1 for _ in open(OUT / "validation.jsonl", encoding="utf-8")),
                   "external_test": sum(1 for _ in open(OUT / "test.jsonl", encoding="utf-8")),
                   "corrective_holdout": len(corr_hold), "dance_holdout": len(dance_hold)},
        "holdout_ids": {"corrective": sorted(hold_ids), "dance": sorted(r["id"] for r in dance_hold)},
        "preserved_evaluation_sets": {
            "frozen_v02_validation_test": "byte-identical copies (files_sha256 == parent export_files_sha256)",
            "clean_v01_vs_v02_subsets": "data/production/evaluation/rupsaa_v0.2/eval_manifests.json (unchanged)",
            "unseen_terminology_24": "data/production/evaluation/rupsaa_v0.2/terminology_generalization.jsonl (unchanged)"},
        "training": {"expected_steps_per_epoch": per_epoch, "expected_total_steps": total, "batch": BATCH,
                     "gradient_accumulation": GRAD_ACC, "epochs": EPOCHS, "val_size": VAL_SIZE,
                     "config_cli": "configs/training/llamafactory_rupsaa_v0.2.1.yaml",
                     "config_gui_template": "configs/training/llamafactory_webui_rupsaa_v0.2.1.yaml",
                     "output_dir": "adapters/rupsaa-v0.2.1", "status": "NOT STARTED — owner approval required"},
        "reviews": {"corpus_checks": "data/production/reports/rupsaa_v0.2.1_preparation/corrective_checks.json",
                    "leakage": "data/production/reports/rupsaa_v0.2.1_preparation/leakage_report.json",
                    "dance_retrieval": "data/production/reports/rupsaa_v0.2.1_preparation/dance_retrieval_check.json",
                    "human_review": "data/production/reports/rupsaa_v0.2.1_preparation/CORRECTIVE_DATA_REVIEW.md"},
        "authorization": auth,
    }
    for d in (OUT, SNAPSHOT):
        (d / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    make_readonly(OUT)
    make_readonly(SNAPSHOT)
    print(f"FROZEN {DATASET}  dataset_sha256={dataset_sha}  (supersedes {OLD_SHA[:12]}…, never trained)")


if __name__ == "__main__":
    main()
